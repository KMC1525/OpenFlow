"""Auxiliares dos testes de mídia: ffmpeg/ffprobe presentes? e a ficha (duração, largura, altura) de um arquivo."""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any, Dict


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe(path: Path) -> Dict[str, Any]:
    """{dur, w, h, audio, video} de um arquivo de mídia (zeros se o ffprobe não existir)."""
    out: Dict[str, Any] = {"dur": 0.0, "w": 0, "h": 0, "audio": False, "video": False}
    fp = shutil.which("ffprobe")
    if not fp:
        return out
    try:
        r = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,duration", "-of", "json", str(path)], capture_output=True, timeout=60)
        j = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return out
    try:
        out["dur"] = float((j.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        pass
    for s in j.get("streams") or []:
        if s.get("codec_type") == "audio":
            out["audio"] = True
        elif s.get("codec_type") == "video":
            out["video"] = True
            out["w"], out["h"] = int(s.get("width") or 0), int(s.get("height") or 0)
    return out


def tiny_png(color=(200, 80, 80)) -> bytes:
    """Um PNG de 1×1 pixel da cor pedida."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    raw = b"\x00" + bytes(color)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
