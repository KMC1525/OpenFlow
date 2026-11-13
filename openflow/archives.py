"""Pacotes compactados como anexos: ZIP, RAR, 7z, TAR (.tar.gz/.tgz/.tar.bz2/.tar.xz) e quadrinhos .cbz/.cbr.

O usuário pode anexar um pacote nos nós de mídia e no editor de projetos: o OpenFlow abre o pacote **com segurança**, e os arquivos de
dentro passam a ser tratados como anexos soltos (texto, documentos, imagens, áudios e vídeos).

Segurança (o pacote vem de fora e não é confiável):
  • nomes com `..`, caminho absoluto, letra de unidade (`C:`) ou barra invertida **nunca saem da pasta de destino** (zip-slip);
  • links simbólicos, dispositivos e outros itens que não são arquivos comuns são ignorados;
  • limites de quantidade de arquivos, de tamanho de cada um e de tamanho total **realmente escrito** (não confia no tamanho declarado: zip-bomb);
  • pacotes dentro de pacotes só são abertos até `MAX_DEPTH` níveis; pacote com senha é recusado com uma mensagem clara.

ZIP e TAR usam só a biblioteca padrão. RAR e 7z precisam de uma ferramenta do sistema (nada para instalar no Python): `unrar`, `unar`, `7z`/`7zz`/`7za`
ou `bsdtar` (o `tar` do macOS e do Windows 10+ já é o bsdtar e lê RAR e 7z).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAX_FILES = 400                  # arquivos extraídos por pacote
MAX_MEMBER = 600 * 1024 * 1024   # bytes de cada arquivo
MAX_TOTAL = 1536 * 1024 * 1024   # bytes de tudo que é escrito
MAX_DEPTH = 2                    # pacote dentro de pacote
TOOL_TIMEOUT = 300               # segundos para RAR/7z

_EXT_KIND = {"zip": "zip", "cbz": "zip", "rar": "rar", "cbr": "rar", "7z": "7z", "tar": "tar", "tgz": "tar", "tbz2": "tar", "tbz": "tar", "txz": "tar"}
_TAR_SUFFIX = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")
ARCHIVE_EXT = set(_EXT_KIND) | {"gz"}  # .gz só conta quando é .tar.gz (ver archive_kind)
_WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)


class ArchiveError(Exception):
    """O pacote não pôde ser aberto (senha, formato, ferramenta ausente…). A mensagem é para o usuário."""


def archive_kind(name: str, path: Optional[Path] = None) -> str:
    """"zip" | "rar" | "7z" | "tar" ou "" se não é um pacote. Vale o nome; sem extensão conhecida, os primeiros bytes do arquivo (assinatura)."""
    low = (name or "").lower()
    if low.endswith(_TAR_SUFFIX):
        return "tar"
    ext = low.rsplit(".", 1)[-1] if "." in low else ""
    if ext in _EXT_KIND:
        return _EXT_KIND[ext]
    if path is not None and ext in ("", "bin", "dat", "download"):
        try:
            with open(path, "rb") as f:
                head = f.read(8)
        except OSError:
            return ""
        if head[:4] == b"PK\x03\x04":
            return "zip"
        if head[:6] == b"Rar!\x1a\x07":
            return "rar"
        if head[:6] == b"7z\xbc\xaf\x27\x1c":
            return "7z"
    return ""


def _clean_part(p: str) -> str:
    p = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", p).strip(" ")
    p = p.rstrip(".") if p not in (".", "..") else p
    if _WIN_RESERVED.match(p):
        p = "_" + p
    return p[:120]


def clean_name(name: str) -> Optional[str]:
    """Caminho relativo seguro dentro do pacote ("a/b.txt"), ou None se o nome tenta sair da pasta ou não é utilizável."""
    n = str(name or "").replace("\\", "/")
    if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
        return None
    parts = [p for p in n.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    parts = [_clean_part(p) for p in parts]
    if any(not p for p in parts):
        return None
    return "/".join(parts)


def _fix_zip_name(info: zipfile.ZipInfo) -> str:
    """Nomes sem a marca UTF-8 chegam decodificados como cp437; zips feitos no Windows em português usam cp850 e os do Linux/macOS, UTF-8 — conserta os dois."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        raw = info.filename.encode("cp437")
    except UnicodeEncodeError:
        return info.filename
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if any("─" <= c <= "╿" for c in info.filename):   # desenho de caixas = acentos mal lidos
        try:
            fixed = raw.decode("cp850")
            if not any("─" <= c <= "╿" for c in fixed):
                return fixed
        except UnicodeDecodeError:
            pass
    return info.filename


class _Sink:
    """Escolhe o nome final de cada arquivo (sem colisões) e conta o que foi escrito."""

    def __init__(self, dest: Path, max_files: int, max_total: int, max_member: int):
        self.dest, self.max_files, self.max_total, self.max_member = dest, max_files, max_total, max_member
        self.total = 0
        self.files: List[Dict[str, Any]] = []
        self.skipped: List[str] = []
        self.used: set = set()

    def slot(self, rel: str) -> Optional[Path]:
        if len(self.files) >= self.max_files:
            self.skipped.append(f"{rel}: limite de {self.max_files} arquivos por pacote")
            return None
        final, k = rel, 1
        while final.lower() in self.used:
            k += 1
            stem, dot, ext = rel.rpartition(".")
            final = f"{stem} ({k}).{ext}" if dot and "/" not in ext else f"{rel} ({k})"
        self.used.add(final.lower())
        path = self.dest / final
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def add(self, rel: str, path: Path, size: int) -> None:
        self.files.append({"name": str(path.relative_to(self.dest)).replace(os.sep, "/"), "path": path, "size": size})
        self.total += size

    def result(self, kind: str) -> Dict[str, Any]:
        return {"kind": kind, "files": self.files, "skipped": self.skipped, "total": self.total}


def _copy_capped(src, dst: Path, limit: int) -> int:
    """Copia `src` para `dst` escrevendo no máximo `limit`+1 bytes: passou do limite, apaga e devolve -1 (o tamanho declarado no pacote não é confiável)."""
    written = 0
    with open(dst, "wb") as out:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            written += len(chunk)
            if written > limit:
                break
            out.write(chunk)
    if written > limit:
        try:
            dst.unlink()
        except OSError:
            pass
        return -1
    return written


def _extract_zip(path: Path, sink: _Sink) -> None:
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, NotImplementedError, EOFError, ValueError, OverflowError, RuntimeError) as exc:   # NotImplementedError: «zip file version 9.4» (cabeçalho adulterado/de uma versão do formato que o Python não lê)
        raise ArchiveError(f"O ZIP está corrompido ou não é um ZIP válido ({exc}).") from None
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        encrypted = sum(1 for i in infos if i.flag_bits & 0x1)
        if infos and encrypted == len(infos):
            raise ArchiveError("O ZIP tem senha. Tire a senha (ou extraia no computador) e anexe de novo.")
        for info in infos:
            display = _fix_zip_name(info)
            rel = clean_name(display)
            if rel is None:
                sink.skipped.append(f"{display}: nome inseguro (ignorado)")
                continue
            if info.flag_bits & 0x1:
                sink.skipped.append(f"{rel}: protegido por senha")
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:   # link simbólico
                sink.skipped.append(f"{rel}: link simbólico (ignorado)")
                continue
            if info.file_size > sink.max_member or sink.total + min(info.file_size, sink.max_member) > sink.max_total:
                sink.skipped.append(f"{rel}: grande demais")
                continue
            dst = sink.slot(rel)
            if dst is None:
                continue
            try:
                with zf.open(info) as src:
                    n = _copy_capped(src, dst, min(sink.max_member, sink.max_total - sink.total))
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError, zlib_error) as exc:
                sink.skipped.append(f"{rel}: não foi possível ler ({str(exc)[:60]})")
                try:
                    dst.unlink()
                except OSError:
                    pass
                continue
            if n < 0:
                sink.skipped.append(f"{rel}: grande demais")
                continue
            sink.add(rel, dst, n)


try:   # zlib.error pode vir de um fluxo comprimido quebrado
    from zlib import error as zlib_error
except ImportError:   # pragma: no cover
    zlib_error = ValueError  # type: ignore[assignment,misc]


def _extract_tar(path: Path, sink: _Sink) -> None:
    try:
        tf = tarfile.open(path, "r:*")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ArchiveError(f"O arquivo TAR está corrompido ou não é um TAR válido ({exc}).") from None
    with tf:
        try:
            for m in tf:
                if not m.isfile():   # pastas, links, dispositivos, FIFOs: nada disso vira arquivo
                    if not m.isdir():
                        sink.skipped.append(f"{m.name}: não é um arquivo comum (ignorado)")
                    continue
                rel = clean_name(m.name)
                if rel is None:
                    sink.skipped.append(f"{m.name}: nome inseguro (ignorado)")
                    continue
                if m.size > sink.max_member or sink.total + min(m.size, sink.max_member) > sink.max_total:
                    sink.skipped.append(f"{rel}: grande demais")
                    continue
                dst = sink.slot(rel)
                if dst is None:
                    continue
                src = tf.extractfile(m)
                if src is None:
                    continue
                n = _copy_capped(src, dst, min(sink.max_member, sink.max_total - sink.total))
                if n < 0:
                    sink.skipped.append(f"{rel}: grande demais")
                    continue
                sink.add(rel, dst, n)
        except (tarfile.TarError, EOFError, OSError) as exc:
            if not sink.files:
                raise ArchiveError(f"O arquivo TAR está corrompido ({exc}).") from None
            sink.skipped.append(f"o pacote termina antes do fim ({str(exc)[:60]})")


# --------------------------------------------------------------------------- RAR e 7z: ferramentas do sistema


def _is_bsdtar(exe: str) -> bool:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "bsdtar" in out.lower() or "libarchive" in out.lower()


def tools_for(kind: str) -> List[Tuple[str, str]]:
    """[(nome da ferramenta, caminho)] que sabem abrir este formato, na ordem de preferência."""
    cands: List[Tuple[str, str]] = []
    order = {"rar": ("unrar", "unar", "7zz", "7z", "7za", "bsdtar", "tar"), "7z": ("7zz", "7z", "7za", "unar", "bsdtar", "tar")}.get(kind, ())
    for name in order:
        exe = shutil.which(name)
        if not exe:
            continue
        if name == "tar" and not _is_bsdtar(exe):   # o tar do GNU não abre RAR/7z; o do macOS e do Windows (bsdtar) abre
            continue
        if name in ("7za", "7zr") and kind == "rar":   # 7za sozinho não lê RAR
            continue
        cands.append((name, exe))
    return cands


def tool_hint(kind: str) -> str:
    if kind == "rar":
        return ("Para abrir arquivos RAR o OpenFlow usa uma ferramenta do sistema que não está instalada. Instale uma: macOS «brew install unar» (ou «brew install sevenzip»); "
                "Linux «sudo apt install unrar» (ou p7zip-full / unar); Windows: o tar.exe do Windows 10+ já abre RAR — atualize o Windows, ou instale o 7-Zip (7-zip.org).")
    return ("Para abrir arquivos 7z o OpenFlow usa uma ferramenta do sistema que não está instalada. Instale uma: macOS «brew install sevenzip»; "
            "Linux «sudo apt install p7zip-full»; Windows: 7-Zip (7-zip.org).")


def _command(name: str, exe: str, archive: Path, dest: Path) -> List[str]:
    if name == "unrar":
        return [exe, "x", "-y", "-idq", "-p-", "-o+", str(archive), str(dest) + os.sep]
    if name == "unar":
        return [exe, "-q", "-D", "-f", "-p", "", "-o", str(dest), str(archive)]
    if name in ("7z", "7zz", "7za"):
        return [exe, "x", "-y", "-bd", "-bso0", "-bsp0", f"-o{dest}", str(archive)]
    return [exe, "-xf", str(archive), "-C", str(dest)]   # bsdtar


def _dir_bytes(root: Path) -> int:
    total = 0
    for base, _dirs, files in os.walk(root):
        for f in files:
            try:
                total += os.lstat(os.path.join(base, f)).st_size
            except OSError:
                pass
    return total


def _run_capped(cmd: List[str], dest: Path, cap: int, timeout: int) -> Tuple[int, str, bool]:
    """Roda a ferramenta e a interrompe se a pasta de destino passar de `cap` bytes (zip-bomb) ou do tempo. Devolve (código, erro, estourou)."""
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    blown = {"v": False}
    stop = threading.Event()

    def watch() -> None:
        t0 = time.time()
        while not stop.wait(0.25):
            if time.time() - t0 > timeout or _dir_bytes(dest) > cap:
                blown["v"] = True
                try:
                    proc.kill()
                except OSError:
                    pass
                return

    th = threading.Thread(target=watch, daemon=True)
    th.start()
    try:
        _out, err = proc.communicate()
    finally:
        stop.set()
        th.join(1)
    return proc.returncode, (err or b"").decode("utf-8", "replace")[-400:], blown["v"]


def _extract_external(path: Path, kind: str, sink: _Sink) -> None:
    tools = tools_for(kind)
    if not tools:
        raise ArchiveError(tool_hint(kind))
    last = ""
    for name, exe in tools:
        with tempfile.TemporaryDirectory(prefix="flow-unpack-") as tmp:
            work = Path(tmp)
            code, err, blown = _run_capped(_command(name, exe, path, work), work, sink.max_total, TOOL_TIMEOUT)
            if blown:
                raise ArchiveError("O pacote é grande demais depois de aberto (ou demorou demais) e foi interrompido por segurança.")
            found = _collect_dir(work, sink)
            if found or code == 0:
                if not found and code == 0:
                    raise ArchiveError("O pacote está vazio.")
                return
            last = err.strip() or f"código {code}"
            if re.search(r"password|senha|encrypted|wrong pass", last, re.I):
                raise ArchiveError("O pacote tem senha. Tire a senha (ou extraia no computador) e anexe de novo.")
    raise ArchiveError(f"Não consegui abrir o pacote ({last[:160]}).")


def _collect_dir(work: Path, sink: _Sink) -> bool:
    """Move para o destino os arquivos que a ferramenta extraiu, já filtrados: sem links, sem sair da pasta, dentro dos limites."""
    root = work.resolve()
    got = False
    for base, dirs, files in os.walk(work, followlinks=False):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(base, d))]
        for f in sorted(files):
            src = Path(base) / f
            if src.is_symlink() or not src.is_file():
                continue
            try:
                src.resolve().relative_to(root)
            except ValueError:
                continue
            rel = clean_name(str(src.relative_to(work)))
            if rel is None:
                continue
            size = src.stat().st_size
            if size > sink.max_member or sink.total + size > sink.max_total:
                sink.skipped.append(f"{rel}: grande demais")
                continue
            dst = sink.slot(rel)
            if dst is None:
                continue
            shutil.move(str(src), str(dst))
            sink.add(rel, dst, size)
            got = True
    return got


# --------------------------------------------------------------------------- API


def extract(path: Any, dest: Any, name: str = "", *, max_files: int = MAX_FILES, max_total: int = MAX_TOTAL, max_member: int = MAX_MEMBER) -> Dict[str, Any]:
    """Abre o pacote em `dest` (pasta que já existe ou é criada). Devolve {kind, files: [{name, path, size}], skipped: [...], total}. ArchiveError se não der."""
    path, dest = Path(path), Path(dest)
    kind = archive_kind(name or path.name, path)
    if not kind:
        raise ArchiveError("Formato de pacote não reconhecido.")
    dest.mkdir(parents=True, exist_ok=True)
    sink = _Sink(dest.resolve(), max_files, max_total, max_member)
    if kind == "zip":
        _extract_zip(path, sink)
    elif kind == "tar":
        _extract_tar(path, sink)
    else:
        _extract_external(path, kind, sink)
    sink.files.sort(key=lambda f: f["name"].lower())
    return sink.result(kind)


def media_members(data: bytes, name: str, sniff: Any, max_members: int = 200) -> List[Tuple[str, bytes, str]]:
    """Para os nós de mídia e o Editor: abre o pacote (bytes) e devolve [(nome, bytes, mime)] das imagens, vídeos e áudios de dentro. `sniff(bytes) -> mime` decide pelo conteúdo."""
    out: List[Tuple[str, bytes, str]] = []
    with tempfile.TemporaryDirectory(prefix="flow-media-") as tmp:
        src = Path(tmp) / "pack.bin"
        src.write_bytes(data)
        res = expand(src, Path(tmp) / "x", name or "pack.zip")
        for f in res["files"]:
            if len(out) >= max_members:
                break
            with open(f["path"], "rb") as fh:
                head = fh.read(4096)
            mime = sniff(head) or ""
            if mime.split("/")[0] in ("image", "audio", "video"):
                out.append((f["name"].rsplit("/", 1)[-1], Path(f["path"]).read_bytes(), mime))
    return out


def expand(path: Any, dest: Any, name: str = "", depth: int = 0) -> Dict[str, Any]:
    """`extract` e, dentro de `MAX_DEPTH` níveis, abre também os pacotes que estavam dentro do pacote (os arquivos deles entram na lista com o caminho "pacote.zip/…")."""
    res = extract(path, dest, name)
    if depth >= MAX_DEPTH - 1:
        return res
    out = []
    for f in res["files"]:
        if archive_kind(f["name"], f["path"]):
            try:
                sub = expand(f["path"], Path(dest) / (f["name"] + ".d"), f["name"], depth + 1)
            except ArchiveError as exc:
                res["skipped"].append(f"{f['name']}: {exc}")
                out.append(f)
                continue
            for g in sub["files"]:
                out.append({"name": f"{f['name']}/{g['name']}", "path": g["path"], "size": g["size"]})
            res["skipped"].extend(sub["skipped"])
        else:
            out.append(f)
    res["files"] = out
    return res
