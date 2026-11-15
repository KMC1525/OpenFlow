"""Onde a Biblioteca guarda as coisas (v0.33): os **modelos** e os **arquivos dos projetos** (imagens, vídeos e sons gerados ou enviados) podem ficar em outra pasta — um HD/SSD externo, um pendrive
ou outro disco do computador. Este módulo lista os volumes, valida a pasta escolhida e **move** o que já existe (copiando primeiro e só apagando a origem no fim, para um erro ou um cancelamento
nunca deixar o OpenFlow sem os modelos).
"""
from __future__ import annotations

import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List

from . import diskuse
from .providers.base import ProviderError

CHUNK = 4 << 20
SUBFOLDER = {"models": "OpenFlow-modelos", "files": "OpenFlow-projetos"}


def _usage(p: str) -> Dict[str, int]:
    try:
        u = shutil.disk_usage(p)
        return {"free": u.free, "total": u.total}
    except OSError:
        return {"free": 0, "total": 0}


def volumes() -> List[Dict[str, Any]]:
    """Discos e dispositivos que o computador enxerga: [{path, label, removable, free, total, kind}] — o do usuário (home), os discos montados e os externos."""
    out: List[Dict[str, Any]] = []
    seen = set()

    def add(path: str, label: str, removable: bool = False) -> None:
        if path in seen or not os.path.isdir(path):
            return
        seen.add(path)
        out.append({"path": path, "label": label, "removable": removable, **_usage(path), "kind": diskuse.kind_of(path)})

    sysname = platform.system()
    add(str(Path.home()), "Pasta do usuário")
    if sysname == "Windows":
        try:
            import ctypes

            mask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
            for i in range(26):
                if mask & (1 << i):
                    letter = f"{chr(65 + i)}:\\"
                    kind = ctypes.windll.kernel32.GetDriveTypeW(letter)  # type: ignore[attr-defined]  # 2 removível · 3 fixo · 4 rede
                    if kind in (2, 3, 4):
                        add(letter, letter + (" (externo)" if kind == 2 else " (rede)" if kind == 4 else ""), kind == 2)
        except Exception:  # noqa: BLE001
            pass
    elif sysname == "Darwin":
        for d in sorted(Path("/Volumes").glob("*")):
            add(str(d), d.name, d.is_mount() and d.name != "Macintosh HD")
    else:
        roots = [Path("/media"), Path("/run/media"), Path("/mnt")]
        for r in roots:
            if not r.is_dir():
                continue
            for d in sorted(r.glob("*")):
                subs = [x for x in sorted(d.glob("*")) if x.is_dir() and os.path.ismount(x)] if (r.name in ("media", "media") and d.is_dir() and not os.path.ismount(d)) else []
                for x in subs or [d]:
                    if x.is_dir() and os.path.ismount(x):
                        add(str(x), x.name, r.name in ("media",))
    return out


def browse(path: str) -> Dict[str, Any]:
    """As subpastas de `path` (só nomes, até 500) e a pasta de cima; sem `path`, os volumes."""
    if not path:
        return {"path": "", "parent": "", "dirs": [v["path"] for v in volumes()], "volumes": True}
    p = Path(path).expanduser()
    if not p.is_dir():
        raise ProviderError("Essa pasta não existe (ou o dispositivo foi desconectado).")
    dirs: List[str] = []
    try:
        for e in sorted(os.scandir(p), key=lambda x: x.name.lower()):
            if e.is_dir(follow_symlinks=False) and not e.name.startswith("."):
                dirs.append(e.name)
            if len(dirs) >= 500:
                break
    except PermissionError:
        raise ProviderError("Sem permissão para abrir essa pasta.") from None
    parent = "" if p.parent == p else str(p.parent)
    return {"path": str(p), "parent": parent, "dirs": dirs, "volumes": False}


def _writable(p: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=p, prefix=".flow-write-", delete=True):
            return True
    except OSError:
        return False


def resolve(kind: str, picked: str) -> Path:
    """A pasta escolhida, validada. Raiz de um disco ou de um dispositivo vira uma subpasta do OpenFlow (não se espalha modelos na raiz do pendrive). Levanta ProviderError em português."""
    if not picked or not picked.strip():
        raise ProviderError("Escolha uma pasta.")
    p = Path(picked.strip()).expanduser()
    if not p.is_absolute():
        raise ProviderError("Use um caminho completo (ex.: D:\\\\Modelos ou /media/usuario/HD/modelos).")
    if not p.exists():
        if not p.parent.is_dir():
            raise ProviderError("Essa pasta não existe e a de cima também não: o dispositivo está conectado?")
    elif not p.is_dir():
        raise ProviderError("Isso é um arquivo, não uma pasta.")
    if p.exists() and (os.path.ismount(p) or p.parent == p):
        p = p / SUBFOLDER.get(kind, "OpenFlow")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProviderError(f"Não consegui criar a pasta: {exc}") from None
    if not _writable(p):
        raise ProviderError("Sem permissão para gravar nessa pasta (ou o dispositivo está somente leitura).")
    return p.resolve()


def _tree(src: Path) -> List[Path]:
    files: List[Path] = []
    for root, _dirs, names in os.walk(src):
        for n in names:
            files.append(Path(root) / n)
    return files


def check_move(src: Path, dst: Path) -> int:
    """Confere se dá para mover `src` → `dst` (pastas separadas, espaço livre) e devolve os bytes a copiar."""
    s, d = src.resolve(), dst.resolve()
    if s == d:
        raise ProviderError("Essa já é a pasta em uso.")
    if d in s.parents or s in d.parents:
        raise ProviderError("A nova pasta não pode ficar dentro da atual (nem a atual dentro da nova).")
    total = sum(f.stat().st_size for f in _tree(s) if f.exists())
    if _usage(str(d))["free"] < total * 1.02 + (100 << 20):   # copia primeiro (a origem só sai no fim): precisa de espaço mesmo no mesmo disco
        raise ProviderError(f"Falta espaço na nova pasta: o conteúdo ocupa {total / 1024 ** 3:.1f} GB e há {_usage(str(d))['free'] / 1024 ** 3:.1f} GB livres.")
    return total


def _same_device(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_dev == b.stat().st_dev
    except OSError:
        return False


def migrate(src: Path, dst: Path, progress: Callable[[int, int], None], cancelled: Callable[[], bool], note: Callable[[str], None] = lambda m: None) -> int:
    """Copia tudo de `src` para `dst` (mesmo disco: renomeia, sem copiar). A origem só é apagada **depois** de tudo copiado e conferido; cancelar ou falhar desfaz as cópias novas. Devolve os bytes."""
    src, dst = src.resolve(), dst.resolve()
    files = [f for f in _tree(src) if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    same_dev = _same_device(src, dst)
    created: List[Path] = []
    done = 0
    progress(0, total)
    try:
        for f in files:
            if cancelled():
                raise ProviderError("cancelado")
            rel = f.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            size = f.stat().st_size
            if target.exists() and target.stat().st_size == size:   # já copiado (retomada)
                done += size
                progress(done, total)
                continue
            note(f"Copiando {rel}…")
            part = target.with_name(target.name + ".part")
            created.append(target)
            if same_dev:
                shutil.copy2(f, part)   # mesmo disco: copia também (a origem fica intacta até o fim)
            else:
                with open(f, "rb") as r, open(part, "wb") as w:
                    while True:
                        if cancelled():
                            raise ProviderError("cancelado")
                        chunk = r.read(CHUNK)
                        if not chunk:
                            break
                        w.write(chunk)
                        done += len(chunk)
                        progress(done, total)
                shutil.copystat(f, part, follow_symlinks=False)
            if same_dev:
                done += size
                progress(done, total)
            if part.stat().st_size != size:
                raise ProviderError(f"A cópia de {rel} ficou com tamanho diferente: abortei sem apagar nada.")
            os.replace(part, target)
    except BaseException:
        for t in created:   # desfaz: nada fica pela metade na pasta nova
            try:
                t.unlink()
                t.with_name(t.name + ".part").unlink()
            except OSError:
                pass
        for t in created:
            try:
                t.with_name(t.name + ".part").unlink()
            except OSError:
                pass
        raise
    return total


def remove_source(src: Path) -> None:
    """Depois de a nova pasta estar em uso: apaga o conteúdo da antiga (a pasta em si fica, vazia)."""
    for child in list(src.iterdir()):
        try:
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
        except OSError:
            pass
