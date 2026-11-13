"""Voz via servidores OpenAI-compatíveis (STT/TTS) — nuvem ou 100% local.

Com `engine = "browser"` o navegador faz tudo (Web Speech API), sem custo e sem instalar nada.
Com `engine = "server"` o OpenFlow fala com qualquer API compatível (OpenAI, ou modelos locais como
Whisper / faster-whisper-server / Kokoro / Piper atrás de um endpoint /audio/*).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .providers import http
from .providers.base import ProviderError


def _headers(cfg: Dict[str, Any]) -> Dict[str, str]:
    key = cfg.get("api_key") or ""
    return {"Authorization": f"Bearer {key}"} if key else {}


def stt_enabled(settings: Dict[str, Any]) -> bool:
    cfg = (settings.get("voice") or {}).get("stt") or {}
    return cfg.get("engine") == "server" and bool(cfg.get("base_url"))


def tts_enabled(settings: Dict[str, Any]) -> bool:
    cfg = (settings.get("voice") or {}).get("tts") or {}
    return cfg.get("engine") == "server" and bool(cfg.get("base_url"))


def transcribe_bytes(settings: Dict[str, Any], data: bytes, filename: str, mime: str, lang: str = "") -> str:
    cfg = (settings.get("voice") or {}).get("stt") or {}
    if not stt_enabled(settings):
        raise ProviderError("Transcrição por servidor não configurada (Configuração → Voz).")
    fields = {"model": cfg.get("model") or "whisper-1", "response_format": "json"}
    lang = lang or cfg.get("lang") or ""
    if lang and lang != "auto":
        fields["language"] = lang.split("-")[0]
    url = cfg["base_url"].rstrip("/") + "/audio/transcriptions"
    out = http.post_multipart(url, fields, "file", filename, data, mime or "application/octet-stream", _headers(cfg))
    return str(out.get("text", "")).strip()


def transcriber(settings: Dict[str, Any]) -> Optional[Callable[[Path], str]]:
    """Função usada para transcrever anexos de áudio/vídeo (ou None se não configurado)."""
    if not stt_enabled(settings):
        return None

    def run(path: Path) -> str:
        mime = "audio/mpeg" if path.suffix.lower() == ".mp3" else "application/octet-stream"
        return transcribe_bytes(settings, path.read_bytes(), path.name, mime)

    return run


def synthesize(settings: Dict[str, Any], text: str, voice: str = "") -> Tuple[bytes, str]:
    cfg = (settings.get("voice") or {}).get("tts") or {}
    if not tts_enabled(settings):
        raise ProviderError("Síntese de voz por servidor não configurada (Configuração → Voz).")
    payload = {
        "model": cfg.get("model") or "tts-1",
        "input": text[:2000],
        "voice": voice or cfg.get("voice") or "alloy",
        "response_format": "mp3",
    }
    url = cfg["base_url"].rstrip("/") + "/audio/speech"
    return http.post_bytes(url, payload, _headers(cfg), timeout=120)
