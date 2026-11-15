"""Armazenamento (v0.31): que tipo de disco guarda os modelos (SSD ou HDD), quanto o OpenFlow ocupa e a limpeza do que sobrou.

* **HDD:** leituras e escritas em paralelo no mesmo arquivo viram acessos aleatórios e o disco gira em vão. Nos HDD os downloads usam uma conexão só (gravação sequencial, arquivo sem fragmentar) e a pré-carga
  do modelo lê com uma thread só. Em SSD tudo segue paralelo.
* **Limpeza:** downloads parciais abandonados (`.part`/`.seg`), temporários de gerações interrompidas e arquivos de projeto que nenhum projeto usa mais. Nada que esteja em uso é apagado.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

_KIND_CACHE: Dict[str, str] = {}
STALE_S = 3600   # parcial/temporário mais velho que isto (e sem download rodando) é considerado abandonado


def _linux_kind(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return "unknown"
    base = Path(f"/sys/dev/block/{os.major(st.st_dev)}:{os.minor(st.st_dev)}")
    try:
        real = base.resolve()
    except OSError:
        return "unknown"
    cur = real
    for _ in range(4):   # partição → disco inteiro: o `queue/rotational` fica no disco
        f = cur / "queue" / "rotational"
        if f.is_file():
            try:
                return "hdd" if f.read_text().strip() == "1" else "ssd"
            except OSError:
                return "unknown"
        cur = cur.parent
    return "unknown"


def _run(cmd: List[str], timeout: float = 8.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:  # noqa: BLE001
        return ""


def kind_of(path: Any) -> str:
    """«ssd», «hdd» ou «unknown» para o disco onde `path` está (guardado em memória). macOS: quase todos são SSD (pergunta ao diskutil)."""
    p = os.path.abspath(str(path))
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    key = p if os.path.ismount(p) else p
    root = os.environ.get("OPENFLOW_DISK_KIND", "").lower()
    if root in ("ssd", "hdd"):
        return root
    if key in _KIND_CACHE:
        return _KIND_CACHE[key]
    sysname = platform.system()
    kind = "unknown"
    if sysname == "Linux":
        kind = _linux_kind(p)
    elif sysname == "Windows":
        letter = os.path.splitdrive(p)[0].rstrip(":")
        if re.fullmatch(r"[A-Za-z]", letter or ""):
            out = _run(["powershell", "-NoProfile", "-Command", f"(Get-Partition -DriveLetter {letter} | Get-Disk | Get-PhysicalDisk).MediaType"]).strip().lower()
            kind = "hdd" if out == "hdd" else "ssd" if out in ("ssd", "nvme") else "unknown"
    elif sysname == "Darwin":
        out = _run(["diskutil", "info", p])
        kind = "ssd" if re.search(r"Solid State:\s+Yes", out) else "hdd" if re.search(r"Solid State:\s+No", out) else "unknown"
    _KIND_CACHE[key] = kind
    return kind


def download_connections(dest: Any, wanted: int) -> int:
    """Conexões de download para um destino: em HDD, uma só (gravação sequencial); `OPENFLOW_DL_HDD_CONNECTIONS` muda."""
    if kind_of(dest) == "hdd":
        try:
            return max(1, min(int(wanted), int(os.environ.get("OPENFLOW_DL_HDD_CONNECTIONS", "1"))))
        except ValueError:
            return 1
    return wanted


def _size(path: Path) -> int:
    total = 0
    try:
        for e in os.scandir(path):
            try:
                if e.is_file(follow_symlinks=False):
                    total += e.stat(follow_symlinks=False).st_size
                elif e.is_dir(follow_symlinks=False):
                    total += _size(Path(e.path))
            except OSError:
                pass
    except OSError:
        pass
    return total


def _partials(models_dir: Path) -> List[Path]:
    out: List[Path] = []
    if models_dir.is_dir():
        for p in models_dir.rglob("*"):
            if p.is_file() and (p.name.endswith(".part") or p.name.endswith(".part.seg") or p.name.endswith(".seg.tmp")):
                out.append(p)
    return out


def _temp_leftovers() -> List[Path]:
    tmp = Path(tempfile.gettempdir())
    out: List[Path] = []
    try:
        for p in tmp.iterdir():
            if p.is_dir() and re.match(r"^(flow-sdcli-|flow-ltx2-|flow-media-|flow-pack-|flow-sd-|flow-unpack-)", p.name):
                out.append(p)
    except OSError:
        pass
    return out


def _orphans(project_store: Any) -> List[Path]:
    """Arquivos em `assets/` de um projeto que o `project.json` dele não lista (sobra de uma geração interrompida ou de um projeto restaurado)."""
    out: List[Path] = []
    try:
        folders = [d for d in project_store.folder.iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in folders:
        c = project_store.get(d.name)
        ad = d / "assets"
        if not c or not ad.is_dir():
            continue
        keep = {a["file"] for a in c["assets"]}
        for f in ad.iterdir():
            if f.is_file() and f.name not in keep:
                out.append(f)
    return out


def _old(p: Path) -> bool:
    try:
        return time.time() - p.stat().st_mtime > STALE_S
    except OSError:
        return False


def report(store: Any, downloading: bool) -> Dict[str, Any]:
    """O uso do disco: espaço livre, tipo do disco, tamanho de cada parte e o que a limpeza pode liberar (sem apagar nada)."""
    home = store.home
    models = {k: _size(store.models_dir / k) for k in ("image", "video", "sound", "voice", "stt")} if store.models_dir.is_dir() else {}
    models["text"] = sum(p.stat().st_size for p in store.models_dir.glob("*") if p.is_file() and not p.name.endswith((".part", ".seg")))
    proj = _size(Path(store.projects.folder))
    uploads = _size(store.uploads_dir)
    parts = [] if downloading else [p for p in _partials(store.models_dir) if _old(p)]
    temps = [p for p in _temp_leftovers() if _old(p)]
    orphans = _orphans(store.projects)
    sz = lambda lst: sum((_size(p) if p.is_dir() else p.stat().st_size) for p in lst if p.exists())  # noqa: E731
    du = shutil.disk_usage(home)
    return {"disk": {"kind": kind_of(store.models_dir), "free": du.free, "total": du.total}, "models": models, "projects": proj, "uploads": uploads,
            "cleanable": {"partials": {"files": len(parts), "bytes": sz(parts)}, "temp": {"files": len(temps), "bytes": sz(temps)}, "orphans": {"files": len(orphans), "bytes": sz(orphans)}},
            "downloading": downloading}


def clean(store: Any, what: List[str], downloading: bool) -> Dict[str, Any]:
    """Apaga o que sobrou (`partials`, `temp`, `orphans`). Com um download rodando, os parciais ficam: podem estar em uso."""
    freed, removed = 0, 0
    todo: List[Path] = []
    if "partials" in what and not downloading:
        todo += [p for p in _partials(store.models_dir) if _old(p)]
    if "temp" in what:
        todo += [p for p in _temp_leftovers() if _old(p)]
    if "orphans" in what:
        todo += _orphans(store.projects)
    for p in todo:
        try:
            if p.is_dir():
                n = _size(p)
                shutil.rmtree(p, ignore_errors=True)
            else:
                n = p.stat().st_size
                p.unlink()
            freed += n
            removed += 1
        except OSError:
            pass
    return {"freed": freed, "removed": removed}
