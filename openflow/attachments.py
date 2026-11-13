"""Leitura de anexos de qualquer tipo para o prompt dos agentes.

Texto/código, documentos (docx, odt, pdf), planilhas (xlsx, ods, csv), apresentações
(pptx, odp), imagens, áudios e vídeos. Usa só a biblioteca padrão; se `ffmpeg` /
`pypdf` estiverem instalados, extrai mais (quadros de vídeo, trilha de áudio, PDFs).
Áudio é transcrito se houver um serviço STT configurado (Configuração → Voz).
"""
from __future__ import annotations

import base64
import html
import re
import shutil
import struct
import subprocess
import tempfile
import wave
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from xml.etree import ElementTree as ET

from . import archives

TEXT_EXT = {
    "txt", "md", "markdown", "csv", "tsv", "json", "jsonl", "yaml", "yml", "xml", "html", "htm", "css", "js", "mjs",
    "ts", "tsx", "jsx", "py", "rb", "go", "rs", "java", "c", "h", "cpp", "hpp", "cs", "php", "sh", "bat", "ps1", "sql",
    "log", "ini", "toml", "cfg", "srt", "vtt", "tex", "rst", "svg", "gd", "lua", "glsl", "obj", "mtl",
}
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "tif", "tiff"}
AUDIO_EXT = {"mp3", "wav", "ogg", "oga", "m4a", "flac", "aac", "opus", "wma"}
VIDEO_EXT = {"mp4", "mov", "mkv", "webm", "avi", "m4v", "wmv", "flv"}
VISION_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}

MAX_IMAGE_BYTES = 4_500_000


def _ext(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _run(cmd: List[str], timeout: int = 120) -> Optional[subprocess.CompletedProcess]:
    try:
        from . import perf

        return perf.run(cmd, capture_output=True, timeout=timeout)   # ffmpeg com menos threads e prioridade baixa conforme o modo de desempenho
    except (OSError, subprocess.SubprocessError):
        return None


def _human(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024 or unit == "GB":
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{n} B"


def _strip_xml(xml: str, para: str) -> str:
    xml = re.sub(para, "\n", xml)
    xml = re.sub(r"<w:tab\s*/>|<w:br\s*/>", " ", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    xml = html.unescape(xml)
    return re.sub(r"\n{3,}", "\n\n", xml).strip()


# --------------------------------------------------------------------------- documentos


def _docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return _strip_xml(z.read("word/document.xml").decode("utf-8", "replace"), r"</w:p>")


def _pptx(path: Path) -> str:
    out = []
    with zipfile.ZipFile(path) as z:
        def order(n: str) -> int:
            m = re.search(r"(\d+)\.xml$", n)
            return int(m.group(1)) if m else 0

        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=order)
        for i, name in enumerate(slides, 1):
            body = _strip_xml(z.read(name).decode("utf-8", "replace"), r"</a:p>")
            if body:
                out.append(f"[Slide {i}]\n{body}")
        notes = sorted((n for n in z.namelist() if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", n)), key=order)
        for name in notes:
            body = _strip_xml(z.read(name).decode("utf-8", "replace"), r"</a:p>")
            if body:
                out.append(f"[Notas]\n{body}")
    return "\n\n".join(out)


def _xlsx(path: Path, max_rows: int = 200, max_cols: int = 30) -> str:
    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def col_index(ref: str) -> int:
        letters = re.match(r"[A-Z]+", ref or "A")
        n = 0
        for ch in (letters.group(0) if letters else "A"):
            n = n * 26 + (ord(ch) - 64)
        return n - 1

    out = []
    with zipfile.ZipFile(path) as z:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root:
                shared.append("".join(t.text or "" for t in si.iter() if local(t.tag) == "t"))
        names: List[str] = []
        if "xl/workbook.xml" in z.namelist():
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            names = [el.attrib.get("name", "") for el in wb.iter() if local(el.tag) == "sheet"]
        sheets = sorted((n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                        key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[-1]).group(1)))  # type: ignore[union-attr]
        for idx, sheet in enumerate(sheets):
            rows: List[str] = []
            root = ET.fromstring(z.read(sheet))
            for row in root.iter():
                if local(row.tag) != "row":
                    continue
                cells: Dict[int, str] = {}
                for c in row:
                    if local(c.tag) != "c":
                        continue
                    ci = col_index(c.attrib.get("r", ""))
                    if ci >= max_cols:
                        continue
                    ctype = c.attrib.get("t")
                    val = ""
                    for child in c:
                        if local(child.tag) == "v" and child.text is not None:
                            val = child.text
                            if ctype == "s":
                                try:
                                    val = shared[int(val)]
                                except (ValueError, IndexError):
                                    pass
                        elif local(child.tag) == "is":
                            val = "".join(t.text or "" for t in child.iter() if local(t.tag) == "t")
                    cells[ci] = val
                if cells:
                    width = max(cells) + 1
                    rows.append(",".join(cells.get(i, "").replace("\n", " ") for i in range(width)))
                if len(rows) >= max_rows:
                    rows.append("… (linhas omitidas)")
                    break
            title = names[idx] if idx < len(names) else f"Planilha {idx + 1}"
            out.append(f"[{title}]\n" + "\n".join(rows))
    return "\n\n".join(out)


def _odf(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("content.xml").decode("utf-8", "replace")
    xml = re.sub(r"</text:p>|</text:h>|</table:table-row>", "\n", xml)
    xml = re.sub(r"</table:table-cell>", "\t", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(xml)).strip()


def _rtf(raw: str) -> str:
    raw = re.sub(r"\\'[0-9a-fA-F]{2}", "", raw)
    raw = re.sub(r"\\[a-z]+-?\d* ?", " ", raw)
    return re.sub(r"[{}]", "", raw)


def _pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages[:60]).strip()
        if text:
            return text
    except ImportError:
        pass
    except Exception:  # noqa: BLE001  (PDF fora do padrão → tenta o método simples)
        pass
    import zlib

    data = path.read_bytes()
    out: List[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        chunk = m.group(1)
        try:
            chunk = zlib.decompress(chunk)
        except zlib.error:
            pass
        for tj in re.finditer(rb"\[(.*?)\]\s*TJ|\((.*?)\)\s*Tj", chunk, re.S):
            if tj.group(1) is not None:
                pieces = re.findall(rb"\((.*?)(?<!\\)\)", tj.group(1), re.S)
                out.append(b"".join(pieces).decode("latin-1", "replace"))
            else:
                out.append(tj.group(2).decode("latin-1", "replace"))
    text = " ".join(out)
    text = re.sub(r"\\([()\\])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- imagens


def image_size(data: bytes) -> Optional[tuple]:
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", data[16:24])
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", data[6:10])
        if data[:2] == b"\xff\xd8":
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                seg = struct.unpack(">H", data[i + 2:i + 4])[0]
                i += 2 + seg
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            kind = data[12:16]
            if kind == b"VP8X":
                return (int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1)
            if kind == b"VP8 ":
                return struct.unpack("<HH", data[26:30])[0] & 0x3FFF, struct.unpack("<HH", data[26:30])[1] & 0x3FFF
            if kind == b"VP8L":
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    except (struct.error, IndexError):
        return None
    return None


def _resize_with_ffmpeg(path: Path, max_side: int = 1568) -> Optional[bytes]:
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "o.jpg"
        res = _run([ff, "-y", "-loglevel", "error", "-i", str(path), "-vf",
                    f"scale='min({max_side},iw)':'min({max_side},ih)':force_original_aspect_ratio=decrease",
                    "-frames:v", "1", "-q:v", "4", str(out)], 60)
        if res and res.returncode == 0 and out.exists():
            return out.read_bytes()
    return None


# --------------------------------------------------------------------------- mídia


def _duration(path: Path) -> Optional[float]:
    probe = shutil.which("ffprobe")
    if probe:
        res = _run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], 20)
        if res and res.returncode == 0:
            try:
                return float(res.stdout.decode().strip())
            except ValueError:
                pass
    if _ext(path.name) == "wav":
        try:
            with wave.open(str(path), "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except (wave.Error, EOFError, RuntimeError, struct.error, OSError, ValueError):
            return None
    return None


def _small_audio(path: Path, tmp: Path) -> Path:
    """Reduz o áudio (mono, 16 kHz, 32 kbps) para transcrição barata e rápida."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return path
    out = tmp / "a.mp3"
    res = _run([ff, "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(out)], 300)
    return out if res and res.returncode == 0 and out.exists() else path


def _video_frames(path: Path, duration: Optional[float], n: int = 4) -> List[bytes]:
    ff = shutil.which("ffmpeg")
    if not ff or not duration:
        return []
    frames: List[bytes] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            out = Path(tmp) / f"f{i}.jpg"
            t = duration * (i + 0.5) / n
            res = _run([ff, "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale='min(768,iw)':-2", "-q:v", "5", str(out)], 60)
            if res and res.returncode == 0 and out.exists():
                frames.append(out.read_bytes())
    return frames


# --------------------------------------------------------------------------- API pública


def analyze(
    path: Path,
    name: str,
    mime: str = "",
    *,
    max_chars: int = 20000,
    transcribe: Optional[Callable[[Path], str]] = None,
    _depth: int = 0,
) -> Dict[str, Any]:
    """Lê um anexo e devolve {name, kind, size, text, images, notes}. Um pacote (ZIP, RAR, 7z, TAR…) é aberto e o conteúdo dele entra no texto (kind «archive»)."""
    path = Path(path)
    ext = _ext(name)
    size = path.stat().st_size
    item: Dict[str, Any] = {"name": name, "ext": ext, "size": size, "kind": "file", "text": "", "images": [], "notes": []}

    def finish(text: str) -> Dict[str, Any]:
        text = text.strip()
        if len(text) > max_chars:
            item["notes"].append(f"texto truncado ({len(text)} → {max_chars} caracteres)")
            text = text[:max_chars]
        item["text"] = text
        return item

    try:
        if archives.archive_kind(name, path):
            item["kind"] = "archive"
            if _depth >= 1:
                item["notes"].append("pacote dentro de pacote: não aberto")
                return item
            return _archive(path, name, item, max_chars, transcribe, finish)
        if ext in IMAGE_EXT or mime.startswith("image/"):
            item["kind"] = "image"
            data = path.read_bytes()
            dims = image_size(data)
            if dims:
                item["notes"].append(f"{dims[0]}×{dims[1]} px")
            payload, media = data, VISION_MIME.get(ext)
            big = len(data) > 1_500_000 or (dims and max(dims) > 2000)
            if media is None or big:
                resized = _resize_with_ffmpeg(path)
                if resized:
                    payload, media = resized, "image/jpeg"
            if media and len(payload) <= MAX_IMAGE_BYTES:
                item["images"].append({"media_type": media, "data": base64.b64encode(payload).decode("ascii")})
            else:
                item["notes"].append("imagem grande/formato não suportado e sem ffmpeg para reduzir: enviada só como metadados")
            return item
        if ext in AUDIO_EXT or mime.startswith("audio/"):
            item["kind"] = "audio"
            dur = _duration(path)
            if dur:
                item["notes"].append(f"duração {dur:.0f}s")
            if transcribe:
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        txt = transcribe(_small_audio(path, Path(tmp)))
                        return finish(f"[Transcrição]\n{txt}") if txt else item
                    except Exception as exc:  # noqa: BLE001
                        item["notes"].append(f"transcrição falhou: {exc}")
            else:
                item["notes"].append("sem serviço de transcrição configurado (Configuração → Voz)")
            return item
        if ext in VIDEO_EXT or mime.startswith("video/"):
            item["kind"] = "video"
            dur = _duration(path)
            if dur:
                item["notes"].append(f"duração {dur:.0f}s")
            for frame in _video_frames(path, dur):
                item["images"].append({"media_type": "image/jpeg", "data": base64.b64encode(frame).decode("ascii")})
            if item["images"]:
                item["notes"].append(f"{len(item['images'])} quadros amostrados")
            elif not shutil.which("ffmpeg"):
                item["notes"].append("instale o ffmpeg para analisar quadros do vídeo")
            if transcribe and shutil.which("ffmpeg"):
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        txt = transcribe(_small_audio(path, Path(tmp)))
                        if txt:
                            return finish(f"[Transcrição do áudio]\n{txt}")
                    except Exception as exc:  # noqa: BLE001
                        item["notes"].append(f"transcrição falhou: {exc}")
            return item
        if ext == "docx":
            item["kind"] = "document"
            return finish(_docx(path))
        if ext == "pptx":
            item["kind"] = "presentation"
            return finish(_pptx(path))
        if ext in ("xlsx", "xlsm"):
            item["kind"] = "spreadsheet"
            return finish(_xlsx(path))
        if ext in ("odt", "ods", "odp"):
            item["kind"] = {"odt": "document", "ods": "spreadsheet", "odp": "presentation"}[ext]
            return finish(_odf(path))
        if ext == "pdf":
            item["kind"] = "document"
            txt = _pdf(path)
            if not txt:
                item["notes"].append('sem texto extraível (PDF escaneado?). Para melhorar: pip install "openflow[docs]"')
            return finish(txt)
        if ext == "rtf":
            item["kind"] = "document"
            return finish(_rtf(path.read_text("utf-8", "replace")))
        head = path.read_bytes()[:4096]
        if ext in TEXT_EXT or (b"\x00" not in head and head):
            item["kind"] = "spreadsheet" if ext in ("csv", "tsv") else "text"
            raw = path.read_bytes()[: max_chars * 4]
            try:
                txt = raw.decode("utf-8")
            except UnicodeDecodeError:
                txt = raw.decode("latin-1", "replace")
            return finish(txt)
        item["notes"].append("formato binário não suportado: enviado só o nome e o tamanho")
        return item
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        item["notes"].append(f"não foi possível ler o arquivo: {exc}")
        return item


def _priority(f: Dict[str, Any]) -> tuple:
    """Dentro de um pacote, o que ajuda mais a entender o conteúdo vem primeiro: README/documentação, depois textos pequenos, imagens e o resto."""
    base = f["name"].rsplit("/", 1)[-1].lower()
    ext = _ext(base)
    if base.startswith(("readme", "leia", "leeme", "sobre", "about", "license")):
        rank = 0
    elif ext in ("md", "txt", "rst", "pdf", "docx", "odt"):
        rank = 1
    elif ext in TEXT_EXT or ext in ("xlsx", "pptx", "ods", "odp", "rtf"):
        rank = 2
    elif ext in IMAGE_EXT:
        rank = 3
    elif ext in AUDIO_EXT or ext in VIDEO_EXT:
        rank = 4
    else:
        rank = 5
    return (rank, f["size"])


def _archive(path: Path, name: str, item: Dict[str, Any], max_chars: int, transcribe: Optional[Callable[[Path], str]], finish: Callable[[str], Dict[str, Any]]) -> Dict[str, Any]:
    """Abre o pacote numa pasta temporária, lista o conteúdo e lê os arquivos de dentro (os mais úteis primeiro) até esgotar o limite de texto."""
    with tempfile.TemporaryDirectory(prefix="flow-pack-") as tmp:
        try:
            res = archives.expand(path, Path(tmp) / "x", name)
        except archives.ArchiveError as exc:
            item["notes"].append(str(exc))
            return item
        files = res["files"]
        total = sum(f["size"] for f in files)
        item["notes"].append(f"{len(files)} arquivo(s) dentro, {_human(total)}")
        item["notes"].extend(res["skipped"][:4])
        lines = [f"[Pacote {name}: {len(files)} arquivo(s), {_human(total)}]"] + [f"- {f['name']} ({_human(f['size'])})" for f in files[:150]]
        if len(files) > 150:
            lines.append(f"… e mais {len(files) - 150} arquivo(s)")
        header = "\n".join(lines)
        budget = max_chars - len(header) - 8
        sections: List[str] = []
        media_left = 3   # áudio/vídeo é caro de analisar (ffmpeg, transcrição): só os primeiros
        for f in sorted(files, key=_priority):
            if budget < 400:
                break
            ext = _ext(f["name"])
            if ext in AUDIO_EXT or ext in VIDEO_EXT:
                if media_left <= 0:
                    continue
                media_left -= 1
            inner = analyze(f["path"], f["name"], "", max_chars=max(400, min(budget, max_chars // 2)), transcribe=transcribe, _depth=1)
            for img in inner.get("images", []):
                if len(item["images"]) < 8:
                    item["images"].append(img)
            body = inner.get("text", "")
            if body:
                section = f"--- {f['name']} ---\n{body}"
                sections.append(section)
                budget -= len(section) + 2
        return finish(header + ("\n\n" + "\n\n".join(sections) if sections else ""))


def build_digest(items: List[Dict[str, Any]], max_total: int = 60000) -> str:
    """Texto único descrevendo todos os anexos (vai no prompt dos agentes)."""
    if not items:
        return ""
    parts = []
    budget = max_total
    for i, it in enumerate(items, 1):
        head = f"### Anexo {i}: {it['name']} ({it['kind']}, {_human(it['size'])})"
        if it["notes"]:
            head += "\n(" + "; ".join(it["notes"]) + ")"
        body = it.get("text", "")
        if len(body) > budget:
            body = body[:max(0, budget)] + "\n… (restante omitido)"
        budget -= len(body)
        parts.append(head + ("\n" + body if body else ""))
    return "\n\n".join(parts)


def collect_images(items: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, str]]:
    images: List[Dict[str, str]] = []
    for it in items:
        for img in it.get("images", []):
            if len(images) < limit:
                images.append(img)
    return images
