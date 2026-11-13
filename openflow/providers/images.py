"""Imagens enviadas aos modelos de visão: formatos aceitos por servidores mais exigentes (LM Studio, Ollama, llama.cpp) e conversão.

Nuvem (Claude, OpenAI, Gemini…) aceita PNG, JPEG, WebP e GIF. Servidores locais costumam aceitar só PNG e JPEG e respondem com erros como
«'url' field must be a base64 encoded image» quando recebem outra coisa (GIF, WebP…). Aqui o OpenFlow converte para PNG com o ffmpeg quando ele existe.
"""
from __future__ import annotations

import base64
import shutil
import subprocess
from typing import Dict, Optional

STRICT_TYPES = ("image/png", "image/jpeg")


def sniff(data: bytes) -> str:
    """Tipo real da imagem pelos bytes (não confia no que foi declarado)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def to_png(data: bytes) -> Optional[bytes]:
    """Converte qualquer imagem que o ffmpeg entenda (GIF, WebP, BMP…) em PNG (primeiro quadro). None se não há ffmpeg ou falhou."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    try:
        res = subprocess.run([ff, "-loglevel", "error", "-i", "pipe:0", "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "pipe:1"],
                             input=data, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 and res.stdout[:8] == b"\x89PNG\r\n\x1a\n" else None


def normalize(img: Dict[str, str], allowed: Optional[tuple] = None) -> Optional[Dict[str, str]]:
    """Imagem {media_type, data(base64)} pronta para o servidor: tipo conferido pelos bytes e, se o servidor só aceita `allowed`, convertida.
    Devolve None quando não dá para enviá-la (formato não aceito e sem como converter, ou base64 inválido)."""
    try:
        raw = base64.b64decode("".join(str(img.get("data", "")).split()), validate=False)
    except (ValueError, TypeError):
        return None
    if not raw:
        return None
    real = sniff(raw) or str(img.get("media_type") or "image/png")
    if allowed is None or real in allowed:
        return {"media_type": real, "data": base64.b64encode(raw).decode("ascii")}
    png = to_png(raw)
    return {"media_type": "image/png", "data": base64.b64encode(png).decode("ascii")} if png else None
