"""Provedores de mídia do Canvas: geram imagens, vídeos, sons, vozes e transcrições.

Cada provedor declara o que sabe fazer (`caps`: "image", "video", "sound", "voice", "stt") e implementa só isso.
Há três famílias, todas sem dependências obrigatórias (urllib):

* **Offline** — "Demo" (geradores procedurais, para testar fluxos inteiros sem chave e sem internet).
* **APIs de empresas** — OpenAI e compatíveis (xAI, Together, servidores locais…), ElevenLabs, Google (Gemini/Veo),
  Stability AI, Replicate (catálogo enorme de modelos) e Hugging Face Inference.
* **Modelos locais** — Stable Diffusion WebUI (A1111/Forge) e modelos do Hugging Face rodando dentro do OpenFlow
  (`pip install "openflow[media]"`: diffusers + transformers, carregados só quando você usa).

Os adaptadores de APIs externas seguem a documentação pública de cada serviço e são testados com servidores simulados;
o campo "extra" (JSON) de cada nó permite ajustar qualquer parâmetro específico de um modelo.
"""
from __future__ import annotations

import base64
import atexit
import collections
import gc
import io
import math
import os
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from .. import native as _native
from .. import perf
from .. import perf as _perf
from ..util import hardware_info
from ..providers import http
from ..providers.base import ProviderError
from . import procedural as proc
from . import gguf_info, sdcli, support

CAP_LABELS = {"image": "imagens", "video": "vídeos", "sound": "sons e músicas", "voice": "vozes", "stt": "transcrição de áudio"}
Ref = Tuple[bytes, str]  # (bytes, mime) de uma imagem de referência
RETRY_DELAY = 2.0  # espera antes de repetir uma chamada recusada por excesso de uso (os testes reduzem)

MIME_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp", "image/gif": "gif",
    "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/ogg": "ogg", "audio/opus": "ogg",
    "audio/flac": "flac", "audio/x-flac": "flac", "audio/mp4": "m4a", "audio/aac": "aac", "audio/webm": "weba",
    "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov", "video/x-msvideo": "avi",
}
DEFAULT_MIME = {"image": "image/png", "audio": "audio/mpeg", "video": "video/mp4"}


# --------------------------------------------------------------------------- utilidades


def sniff_mime(data: bytes, fallback: str = "") -> str:
    """Descobre o tipo da mídia pelos primeiros bytes (alguns provedores devolvem Content-Type genérico)."""
    h = data[:16]
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if h[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if h[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if h[:4] == b"GIF8":
        return "image/gif"
    if h[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio/wav"
    if h[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "video/x-msvideo"
    if h[:4] == b"OggS":
        return "audio/ogg"
    if h[:4] == b"fLaC":
        return "audio/flac"
    if h[:3] == b"ID3" or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    if data[4:8] == b"ftyp":
        return "audio/mp4" if data[8:12] in (b"M4A ", b"M4B ") else "video/mp4"
    if h[:4] == b"\x1aE\xdf\xa3":
        return "video/webm"
    return fallback


class Media:
    """Um arquivo gerado por um provedor."""

    def __init__(self, data: bytes, mime: str = "", meta: Optional[Dict[str, Any]] = None):
        self.data = data
        self.mime = (mime or sniff_mime(data) or "application/octet-stream").split(";")[0].strip().lower()
        self.meta = meta or {}

    @property
    def kind(self) -> str:
        return self.mime.split("/")[0] if self.mime.split("/")[0] in ("image", "audio", "video") else "file"

    @property
    def ext(self) -> str:
        return MIME_EXT.get(self.mime, "bin")


def expect_media(data: bytes, mime: str, kind: str, who: str = "O provedor") -> Media:
    """Garante que a resposta é mesmo uma mídia do tipo esperado — e não um JSON/HTML de erro com status 200."""
    real = sniff_mime(data) or (mime or "").split(";")[0].strip().lower()
    if not data or real.endswith("json") or real.startswith("text/") or data[:1] in (b"{", b"<", b"["):
        detail = ""
        try:
            obj = json.loads(data.decode("utf-8", "replace"))
            err = obj.get("error", obj.get("detail", obj)) if isinstance(obj, dict) else obj
            detail = err.get("message", json.dumps(err, ensure_ascii=False)) if isinstance(err, dict) else str(err)
        except (ValueError, AttributeError):
            detail = data[:200].decode("utf-8", "replace")
        raise ProviderError(f"{who} não devolveu {'uma ' + kind if kind != 'any' else 'a mídia'}: {detail[:300] or 'resposta vazia'}")
    if kind != "any" and not real.startswith(kind + "/"):
        if real in ("application/octet-stream", "binary/octet-stream", ""):
            real = DEFAULT_MIME.get(kind, real)
        else:
            raise ProviderError(f"{who} devolveu um arquivo inesperado ({real}) em vez de {kind}.")
    return Media(data, real)


def data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def parse_wh(size: str) -> Tuple[int, int]:
    m = re.match(r"^(\d{2,5})x(\d{2,5})$", size or "")
    return (int(m.group(1)), int(m.group(2))) if m else (1024, 1024)


_ASPECTS = {"1:1": 1.0, "16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "3:2": 3 / 2, "2:3": 2 / 3}


def aspect_of(size: str) -> str:
    """Proporção (como "16:9") mais próxima de um tamanho "WxH"."""
    w, h = parse_wh(size)
    return min(_ASPECTS, key=lambda k: abs(_ASPECTS[k] - w / h))


def size_of_aspect(aspect: str, long_side: int = 1280) -> Tuple[int, int]:
    try:
        a, b = [float(x) for x in aspect.split(":")]
    except (ValueError, AttributeError):
        a, b = 16.0, 9.0
    w, h = (long_side, long_side * b / a) if a >= b else (long_side * a / b, long_side)
    return int(w) // 2 * 2, int(h) // 2 * 2


def _nearest(value: float, options: Sequence[float]) -> float:
    return min(options, key=lambda o: abs(o - value))


_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")


def clean_terminal(msg: str) -> str:
    """Tira códigos de terminal (cores, «apagar linha» \\x1b[K) e retornos de carro de uma linha de log; fica o último trecho visível."""
    msg = _ANSI.sub("", str(msg or "")).replace("\x1b", "")
    return (msg.split("\r")[-1] if "\r" in msg else msg).strip()


class Ctl:
    """Ligação do provedor com o job: cancelamento e mensagens de progresso."""

    def __init__(self, check: Optional[Callable[[], None]] = None, note: Optional[Callable[[str], None]] = None):
        self._check, self._note = check, note

    def check(self) -> None:
        if self._check:
            self._check()

    def note(self, msg: str) -> None:
        msg = clean_terminal(msg)
        if self._note and msg:
            self._note(msg)

    def sleep(self, secs: float) -> None:
        end = time.time() + secs
        while time.time() < end:
            self.check()
            time.sleep(min(0.4, max(0.0, end - time.time())))


def _retry(ctl: Ctl, fn: Callable[[], Any], tries: int = 3, statuses: Tuple[int, ...] = (429, 502, 503, 504)) -> Any:
    """Repete chamadas recusadas por excesso de uso/indisponibilidade temporária (nunca erros de conteúdo ou de chave)."""
    delay = RETRY_DELAY
    for i in range(tries):
        ctl.check()
        try:
            return fn()
        except ProviderError as exc:
            if exc.status not in statuses or i == tries - 1:
                raise
            ctl.note(f"Provedor ocupado ({exc.status}); tentando de novo em {delay:.0f}s…")
            ctl.sleep(delay)
            delay *= 2.5
    return None


def _auth(key: str, header: str = "Authorization", scheme: str = "Bearer ") -> Dict[str, str]:
    return {header: f"{scheme}{key}"} if key else {}


# --------------------------------------------------------------------------- base


#: GGUF que juntam várias imagens de referência na mesma geração (edição, Kontext, FLUX.2 klein/dev, Qwen-Image 2.1): as referências valem também no modo Gerar
_GGUF_MULTI_REF = re.compile(r"edit|kontext|klein|qwen[-_]?image[-_]?2[._]?1|flux[-_. ]?2[-_. ]?dev", re.I)


class MediaProvider:
    id = "media"
    label = "Provedor"
    caps: Tuple[str, ...] = ()
    edit_mode = False      # o nó está no modo Editar (a engine liga antes de gerar): só então uma única referência dita a proporção do resultado
    supports_refs = False  # aceita imagens de referência (edição/estilo) no nó Imagem
    refs_edit_only = False  # só usa as referências no modo Editar (imagem → imagem); no modo Gerar elas não podem virar a imagem de partida

    def max_refs(self, model: str = "") -> int:
        """Quantas imagens de referência o modelo realmente usa (as demais seriam ignoradas em silêncio)."""
        return 8

    def frames_edit_for(self, model: str = "") -> bool:
        """O OpenFlow deve reescrever o pedido do modo Editar como instrução de edição? Só nos modelos locais que editam por referência (Kontext, FLUX.2 klein, FLUX.3, Qwen-Image-Edit…)."""
        return False

    def refs_need_edit(self, model: str = "") -> bool:
        """As referências só valem no modo Editar? Modelos que juntam várias referências na mesma imagem (FLUX.2 klein, Qwen-Image 2.1, Kontext…) as usam também no modo Gerar; os de «imagem → imagem» não."""
        return bool(self.refs_edit_only)

    def __init__(self, cfg: Dict[str, Any], ctl: Optional[Ctl] = None):
        self.cfg = cfg
        self.id = cfg.get("id", self.id)
        self.label = cfg.get("label", self.label)
        self.base = (cfg.get("base_url") or "").rstrip("/")
        self.key = (cfg.get("api_key") or "").strip()
        self.models: Dict[str, str] = dict(cfg.get("models") or {})
        self.ctl = ctl or Ctl()

    # utilidades
    def model_for(self, cap: str, override: str = "") -> str:
        return (override or self.models.get(cap) or "").strip()

    def poll(self, default: float) -> float:
        """Intervalo (s) entre consultas de trabalhos assíncronos (vídeo etc.)."""
        return float(self.cfg.get("poll_seconds") or default)

    def need_key(self) -> None:
        if self.cfg.get("needs_key") and not self.key:
            raise ProviderError(f"{self.label}: informe a chave de API em Configuração → Mídia.")

    def need_url(self) -> None:
        if not self.base:
            raise ProviderError(f"{self.label}: informe o endereço do servidor em Configuração → Mídia.")

    def _no(self, cap: str) -> ProviderError:
        return ProviderError(f"{self.label} não oferece geração de {CAP_LABELS.get(cap, cap)}. Escolha outro provedor no nó (ou em Configuração → Mídia).")

    # API pública (as subclasses implementam o que suportam)
    def image(self, prompt: str, *, size: str = "1024x1024", count: int = 1, seed: int = 0, negative: str = "", refs: Sequence[Ref] = (),
              model: str = "", extra: Optional[Dict[str, Any]] = None) -> List[Media]:
        raise self._no("image")

    def video(self, prompt: str, *, duration: int = 5, aspect: str = "16:9", image: Optional[Ref] = None, model: str = "",
              extra: Optional[Dict[str, Any]] = None, seed: int = 0, long_side: int = 0) -> Media:
        """`long_side`: lado maior da resolução pedida (480, 720, 1080; 0 = a do provedor). Só vale onde o OpenFlow escolhe o tamanho (Demo e modelos locais); a nuvem usa os tamanhos dela."""
        raise self._no("video")

    def sound(self, prompt: str, *, kind: str = "sfx", duration: int = 5, model: str = "", extra: Optional[Dict[str, Any]] = None, seed: int = 0) -> Media:
        raise self._no("sound")

    def voice(self, text: str, *, voice: str = "", speed: float = 1.0, model: str = "", extra: Optional[Dict[str, Any]] = None, instructions: str = "") -> Media:
        raise self._no("voice")

    def transcribe(self, data: bytes, filename: str, mime: str, *, language: str = "", model: str = "") -> str:
        raise self._no("stt")

    def list_models(self, cap: str) -> List[str]:
        return []

    def test(self) -> str:
        return "ok"


# --------------------------------------------------------------------------- Demo (offline)


class DemoMedia(MediaProvider):
    id, label = "demo", "Demo (offline)"
    caps = ("image", "video", "sound", "voice")
    supports_refs = True

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        w, h = parse_wh(size)
        mix = proc.seed_of(*[len(r[0]) for r in refs]) if refs else 0  # com referência, o resultado muda (não edita de verdade)
        return [Media(proc.image(prompt, f"{w}x{h}", seed + i + mix), "image/png", {"note": "demo"}) for i in range(max(1, count))]

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        w, h = size_of_aspect(aspect, long_side or 640)
        png = image[0] if image and sniff_mime(image[0]) == "image/png" else proc.image(prompt, f"{w}x{h}", seed)
        return Media(proc.video_from_image(png, duration, (w, h), 24, seed), "video/mp4", {"note": "demo"})

    def sound(self, prompt, *, kind="sfx", duration=5, model="", extra=None, seed=0):
        data = proc.music(prompt, float(duration), seed) if kind == "music" else proc.sound_fx(prompt, float(duration), seed)
        return Media(data, "audio/wav", {"note": "demo"})

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        return Media(proc.babble(text, speed, proc.seed_of(voice)), "audio/wav", {"note": "demo"})

    def transcribe(self, data, filename, mime, *, language="", model=""):
        raise ProviderError("O provedor Demo não transcreve áudio. Escolha um provedor de transcrição (OpenAI, Groq, Whisper local…) em Configuração → Mídia.")

    def test(self) -> str:
        return "Demo pronto" + ("" if proc.ffmpeg_path() else " (vídeo precisa do ffmpeg)")


# --------------------------------------------------------------------------- OpenAI e compatíveis


class OpenAIMedia(MediaProvider):
    """OpenAI e qualquer servidor com a mesma API (xAI, Together, LocalAI, Kokoro-FastAPI, faster-whisper-server…)."""

    id, label = "openai", "OpenAI"
    caps = ("image", "video", "voice", "stt")
    supports_refs = True

    def _h(self) -> Dict[str, str]:
        self.need_key()
        self.need_url()
        return _auth(self.key)

    @staticmethod
    def _size(model: str, size: str) -> str:
        w, h = parse_wh(size)
        if model.startswith("dall-e-3"):
            return "1024x1024" if w == h else ("1792x1024" if w > h else "1024x1792")
        if model.startswith("dall-e-2"):
            return "512x512" if max(w, h) <= 512 else "1024x1024"
        if model.startswith("gpt-image"):
            return "1024x1024" if w == h else ("1536x1024" if w > h else "1024x1536")
        return f"{w}x{h}"

    def _images_from(self, res: Any) -> List[Media]:
        out: List[Media] = []
        for item in (res.get("data") if isinstance(res, dict) else None) or []:
            if item.get("b64_json"):
                out.append(expect_media(base64.b64decode(item["b64_json"]), "", "image", self.label))
            elif item.get("url"):
                data, mime = http.get_bytes(item["url"])
                out.append(expect_media(data, mime, "image", self.label))
        if not out:
            raise ProviderError(f"{self.label} não devolveu nenhuma imagem.")
        return out

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        h = self._h()
        model = self.model_for("image", model)
        extra = extra or {}
        prompt = prompt + (f"\n\nEvite: {negative}" if negative else "")
        calls = count if model.startswith("dall-e-3") else 1  # dall-e-3 só aceita n=1
        n = 1 if calls > 1 else count
        out: List[Media] = []
        for _ in range(calls):
            if refs:
                fields: Dict[str, Any] = {"prompt": prompt, "n": str(n)}
                if model:
                    fields["model"] = model
                if not self.cfg.get("no_size"):
                    fields["size"] = self._size(model, size)
                fields.update({k: v for k, v in extra.items() if isinstance(v, (str, int, float))})
                field = "image[]" if model.startswith("gpt-image") or not model else "image"
                files = [(field, f"ref{i}.{MIME_EXT.get(m, 'png')}", d, m) for i, (d, m) in enumerate(refs[:8])]
                res = _retry(self.ctl, lambda: http.post_multipart_files(self.base + "/images/edits", fields, files, h, timeout=400))
            else:
                body: Dict[str, Any] = {"prompt": prompt, "n": n}
                if model:
                    body["model"] = model
                if not self.cfg.get("no_size"):
                    body["size"] = self._size(model, size)
                if not model.startswith("gpt-image"):
                    body["response_format"] = "b64_json"
                body.update(extra)
                res = _retry(self.ctl, lambda: http.post_json(self.base + "/images/generations", body, h, timeout=400))
            out += self._images_from(res)
        return out[:max(1, count)]

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        h = self._h()
        model = self.model_for("voice", model) or "tts-1"
        body: Dict[str, Any] = {"model": model, "input": text[:4096], "voice": voice or self.cfg.get("voice") or "alloy", "response_format": "mp3"}
        if abs(speed - 1) > 0.01:
            body["speed"] = max(0.25, min(4.0, speed))
        if instructions and model.startswith("gpt-4o"):
            body["instructions"] = instructions[:1000]
        body.update(extra or {})
        data, mime = _retry(self.ctl, lambda: http.post_bytes(self.base + "/audio/speech", body, {**h, "Accept": "audio/*"}, timeout=240))
        return expect_media(data, mime, "audio", self.label)

    def transcribe(self, data, filename, mime, *, language="", model=""):
        h = self._h()
        fields = {"model": self.model_for("stt", model) or "whisper-1", "response_format": "json"}
        if language and language != "auto":
            fields["language"] = language.split("-")[0]
        out = _retry(self.ctl, lambda: http.post_multipart(self.base + "/audio/transcriptions", fields, "file", filename or "audio.mp3", data, mime or "audio/mpeg", h, timeout=600))
        return str(out.get("text", "") if isinstance(out, dict) else out).strip()

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        """Sora (API de vídeos da OpenAI): cria o trabalho, acompanha até concluir e baixa o MP4."""
        h = self._h()
        model = self.model_for("video", model) or "sora-2"
        w, hh = size_of_aspect(aspect, 1280)
        landscape = w >= hh
        fields: Dict[str, Any] = {"model": model, "prompt": prompt, "seconds": str(int(_nearest(duration, (4, 8, 12)))), "size": "1280x720" if landscape else "720x1280"}
        fields.update({k: v for k, v in (extra or {}).items() if isinstance(v, (str, int, float))})
        files = [("input_reference", "start.png", image[0], image[1])] if image else []
        job = _retry(self.ctl, lambda: http.post_multipart_files(self.base + "/videos", fields, files, h, timeout=120))
        vid = job.get("id") if isinstance(job, dict) else None
        if not vid:
            raise ProviderError(f"{self.label}: resposta inesperada ao criar o vídeo.")
        deadline = time.time() + 1500
        while True:
            self.ctl.check()
            st = http.get_json(f"{self.base}/videos/{vid}", h, timeout=60)
            status = st.get("status")
            if status == "completed":
                break
            if status in ("failed", "cancelled", "canceled"):
                err = st.get("error") or {}
                raise ProviderError(f"{self.label}: o vídeo falhou — {err.get('message') if isinstance(err, dict) else err or status}")
            if time.time() > deadline:
                raise ProviderError(f"{self.label}: o vídeo demorou demais (mais de 25 minutos).")
            self.ctl.note(f"Gerando vídeo… {int(st.get('progress') or 0)}%")
            self.ctl.sleep(self.poll(5))
        data, mime = http.get_bytes(f"{self.base}/videos/{vid}/content", {**h, "Accept": "video/*"}, timeout=900)
        return expect_media(data, mime, "video", self.label)

    def list_models(self, cap: str) -> List[str]:
        res = http.get_json(self.base + "/models", self._h(), timeout=30)
        ids = sorted({m.get("id", "") for m in (res.get("data") if isinstance(res, dict) else res) or [] if isinstance(m, dict)})
        pat = {"image": r"image|dall-e|flux|stable|sdxl", "voice": r"tts|speech|kokoro|piper|voice", "stt": r"whisper|transcribe|stt", "video": r"sora|video"}.get(cap, r".")
        return [i for i in ids if re.search(pat, i, re.I)] or ids[:50]

    def test(self) -> str:
        res = http.get_json(self.base + "/models", self._h(), timeout=30)
        n = len((res.get("data") if isinstance(res, dict) else res) or [])
        return f"conectado ({n} modelos)"


# --------------------------------------------------------------------------- ElevenLabs


class ElevenLabsMedia(MediaProvider):
    id, label = "elevenlabs", "ElevenLabs"
    caps = ("voice", "sound", "stt")
    DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"

    def __init__(self, cfg, ctl=None):
        super().__init__(cfg, ctl)
        self._voices: Optional[List[Dict[str, Any]]] = None

    def _h(self) -> Dict[str, str]:
        self.need_key()
        return {"xi-api-key": self.key}

    def _voice_list(self) -> List[Dict[str, Any]]:
        if self._voices is None:
            res = http.get_json(self.base + "/voices", self._h(), timeout=30)
            self._voices = [v for v in (res.get("voices") if isinstance(res, dict) else []) or [] if isinstance(v, dict)]
        return self._voices

    def _voice_id(self, voice: str) -> str:
        voice = (voice or "").strip()
        if not voice:
            return self.DEFAULT_VOICE
        if re.match(r"^[A-Za-z0-9]{18,24}$", voice):
            return voice
        for v in self._voice_list():
            if (v.get("name") or "").strip().lower() == voice.lower():
                return v["voice_id"]
        names = ", ".join(v.get("name", "") for v in self._voice_list()[:8])
        raise ProviderError(f"ElevenLabs: voz \"{voice}\" não encontrada. Algumas disponíveis: {names or '(nenhuma)'}.")

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        h = self._h()
        body: Dict[str, Any] = {"text": text[:5000], "model_id": self.model_for("voice", model) or "eleven_multilingual_v2",
                                "voice_settings": {"speed": max(0.7, min(1.2, speed))}}
        body.update(extra or {})
        url = f"{self.base}/text-to-speech/{self._voice_id(voice)}?output_format=mp3_44100_128"
        data, mime = _retry(self.ctl, lambda: http.post_bytes(url, body, {**h, "Accept": "audio/mpeg"}, timeout=240))
        return expect_media(data, mime, "audio", self.label)

    def sound(self, prompt, *, kind="sfx", duration=5, model="", extra=None, seed=0):
        h = self._h()
        if kind == "music":  # API de música (recente): enviada tal como documentada; ajuste com o campo "extra" se mudar
            body: Dict[str, Any] = {"prompt": prompt, "music_length_ms": int(max(10, min(300, duration)) * 1000)}
            if model:
                body["model_id"] = model
            body.update(extra or {})
            url = f"{self.base}/music?output_format=mp3_44100_128"
        else:
            body = {"text": prompt, "duration_seconds": round(max(0.5, min(22.0, float(duration))), 1), "prompt_influence": 0.4}
            if model:
                body["model_id"] = model
            body.update(extra or {})
            url = f"{self.base}/sound-generation?output_format=mp3_44100_128"
        data, mime = _retry(self.ctl, lambda: http.post_bytes(url, body, {**h, "Accept": "audio/mpeg"}, timeout=400))
        return expect_media(data, mime, "audio", self.label)

    def transcribe(self, data, filename, mime, *, language="", model=""):
        h = self._h()
        fields = {"model_id": self.model_for("stt", model) or "scribe_v1"}
        if language and language != "auto":
            fields["language_code"] = language.split("-")[0]
        out = _retry(self.ctl, lambda: http.post_multipart_files(self.base + "/speech-to-text", fields, [("file", filename or "audio.mp3", data, mime or "audio/mpeg")], h, timeout=900))
        return str(out.get("text", "") if isinstance(out, dict) else out).strip()

    def list_models(self, cap: str) -> List[str]:
        return [f"{v.get('name', '')}" for v in self._voice_list()] if cap == "voice" else []

    def test(self) -> str:
        n = len(self._voice_list())
        return f"conectado ({n} vozes)"


# --------------------------------------------------------------------------- Google (Gemini / Veo)


class GoogleMedia(MediaProvider):
    id, label = "google", "Google (Gemini / Veo)"
    caps = ("image", "video")
    supports_refs = True

    def _h(self) -> Dict[str, str]:
        self.need_key()
        return {"x-goog-api-key": self.key}

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        h = self._h()
        model = self.model_for("image", model) or "gemini-2.5-flash-image"
        prompt = prompt + (f"\n\nEvite: {negative}" if negative else "")
        parts: List[Dict[str, Any]] = [{"text": prompt}] + [{"inline_data": {"mime_type": m, "data": base64.b64encode(d).decode("ascii")}} for d, m in refs[:6]]
        out: List[Media] = []
        for _ in range(max(1, count)):
            gen: Dict[str, Any] = {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": aspect_of(size)}}
            gen.update((extra or {}).get("generationConfig", {}) if isinstance((extra or {}).get("generationConfig"), dict) else {})
            body = {"contents": [{"parts": parts}], "generationConfig": gen}
            url = f"{self.base}/models/{model}:generateContent"
            try:
                res = _retry(self.ctl, lambda: http.post_json(url, body, h, timeout=300))
            except ProviderError as exc:
                if exc.status == 400 and "imageConfig" in str(exc):  # modelo sem controle de proporção
                    gen.pop("imageConfig", None)
                    res = _retry(self.ctl, lambda: http.post_json(url, body, h, timeout=300))
                else:
                    raise
            out += self._images_from(res)
        return out[:max(1, count)]

    def _images_from(self, res: Any) -> List[Media]:
        imgs: List[Media] = []
        texts: List[str] = []
        for cand in (res.get("candidates") if isinstance(res, dict) else None) or []:
            for part in (cand.get("content") or {}).get("parts", []):
                inl = part.get("inlineData") or part.get("inline_data")
                if inl and inl.get("data"):
                    imgs.append(expect_media(base64.b64decode(inl["data"]), inl.get("mimeType") or inl.get("mime_type") or "", "image", self.label))
                elif part.get("text"):
                    texts.append(part["text"])
        if not imgs:
            block = ((res or {}).get("promptFeedback") or {}).get("blockReason") if isinstance(res, dict) else ""
            raise ProviderError(f"{self.label}: nenhuma imagem devolvida" + (f" (bloqueado: {block})" if block else f" — o modelo respondeu: {' '.join(texts)[:200]}" if texts else "."))
        return imgs

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        h = self._h()
        model = self.model_for("video", model) or "veo-3.0-fast-generate-001"
        inst: Dict[str, Any] = {"prompt": prompt}
        if image:
            inst["image"] = {"bytesBase64Encoded": base64.b64encode(image[0]).decode("ascii"), "mimeType": image[1]}
        params: Dict[str, Any] = {"aspectRatio": "9:16" if aspect in ("9:16", "3:4") else "16:9", "durationSeconds": int(_nearest(duration, (4, 6, 8)))}
        params.update(extra or {})
        op = _retry(self.ctl, lambda: http.post_json(f"{self.base}/models/{model}:predictLongRunning", {"instances": [inst], "parameters": params}, h, timeout=120))
        name = op.get("name") if isinstance(op, dict) else None
        if not name:
            raise ProviderError(f"{self.label}: resposta inesperada ao criar o vídeo.")
        deadline = time.time() + 1500
        while True:
            self.ctl.check()
            st = http.get_json(f"{self.base}/{name}", h, timeout=60)
            if st.get("done"):
                break
            if time.time() > deadline:
                raise ProviderError(f"{self.label}: o vídeo demorou demais (mais de 25 minutos).")
            self.ctl.note("Gerando vídeo…")
            self.ctl.sleep(self.poll(8))
        if st.get("error"):
            raise ProviderError(f"{self.label}: {(st['error'] or {}).get('message', st['error'])}")
        resp = st.get("response") or {}
        samples = (resp.get("generateVideoResponse") or resp).get("generatedSamples") or resp.get("videos") or []
        uri = ((samples[0].get("video") or {}).get("uri") if samples and isinstance(samples[0], dict) else "") or ""
        if not uri:
            reasons = (resp.get("generateVideoResponse") or {}).get("raiMediaFilteredReasons")
            raise ProviderError(f"{self.label}: nenhum vídeo devolvido" + (f" (filtrado: {reasons[0]})" if reasons else "."))
        data, mime = http.get_bytes(uri, {**h, "Accept": "video/*"}, timeout=900)
        return expect_media(data, mime, "video", self.label)

    def list_models(self, cap: str) -> List[str]:
        res = http.get_json(self.base + "/models?pageSize=200", self._h(), timeout=30)
        names = [m.get("name", "").replace("models/", "") for m in res.get("models", []) if isinstance(m, dict)]
        pat = {"image": r"image|imagen", "video": r"veo"}.get(cap, r".")
        return [n for n in names if re.search(pat, n, re.I)]

    def test(self) -> str:
        res = http.get_json(self.base + "/models?pageSize=5", self._h(), timeout=30)
        return f"conectado ({len(res.get('models', []))}+ modelos)"


def _image_size_tier(size: str) -> str:
    """O «image_size» do OpenRouter (1K/2K/4K) que corresponde ao lado maior pedido."""
    w, h = parse_wh(size)
    side = max(w, h)
    return "1K" if side <= 1280 else "2K" if side <= 2560 else "4K"


def _data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime or 'image/png'};base64,{base64.b64encode(data).decode('ascii')}"


_DATA_URI = re.compile(r"data:(image/[\w.+-]+);base64,([A-Za-z0-9+/=\s]+)")


def _openrouter_images(res: Any) -> List[Tuple[Optional[str], str]]:
    """As imagens de uma resposta de chat do OpenRouter: `message.images[].image_url.url`, partes `image_url` do conteúdo ou data URIs soltas no texto → [(mime|None, data URI ou URL)]."""
    out: List[Tuple[Optional[str], str]] = []
    for ch in (res.get("choices") if isinstance(res, dict) else None) or []:
        msg = (ch or {}).get("message") or {}
        parts = list(msg.get("images") or [])
        if isinstance(msg.get("content"), list):
            parts += [p for p in msg["content"] if isinstance(p, dict) and p.get("type") in ("image_url", "output_image", "image")]
        for p in parts:
            u = p.get("image_url") if isinstance(p, dict) else None
            url = u.get("url") if isinstance(u, dict) else (u if isinstance(u, str) else (p.get("url") if isinstance(p, dict) else None))
            if isinstance(url, str) and url:
                out.append((None, url))
        if not out and isinstance(msg.get("content"), str):
            out += [(m.group(1), m.group(0)) for m in _DATA_URI.finditer(msg["content"])]
    return out


_OR_AUDIO_FORMATS = {"wav": "wav", "mp3": "mp3", "mpeg": "mp3", "aiff": "aiff", "aac": "aac", "ogg": "ogg", "flac": "flac", "m4a": "m4a", "mp4": "m4a", "x-wav": "wav", "wave": "wav"}


class OpenRouterMedia(MediaProvider):
    """OpenRouter com a MESMA chave do chat: **imagens** (geração e edição com até 4 referências), **vídeos** (POST /videos, assíncrono: envia, consulta e baixa), **vozes** (POST /audio/speech)
    e **transcrição** (modelos de chat que ouvem áudio). Serve ao Studio e ao Canvas. Os modelos mudam sempre: «Carregar modelos» lista os atuais de cada tipo, pelas modalidades que o OpenRouter
    declara (`architecture.input_modalities`/`output_modalities`).

    Imagens: a rota própria `POST /images` (geração e edição: `input_references`) para os modelos do catálogo `GET /images/models` — o que o modelo aceita (proporção, resolução, seed) vem desse catálogo e uma opção
    recusada (400) é tirada numa nova tentativa. Modelos só de chat multimodal (ou servidor sem a rota) vão pelo chat com `modalities`; se o chat responde «é um modelo só de imagem, use /images», o OpenFlow muda de rota.
    Vídeos: `POST /videos` assíncrono, com duração/proporção/resolução escolhidas dentre as do `GET /videos/models` e o download pela URL do próprio job."""

    id, label = "openrouter", "OpenRouter"
    caps = ("image", "video", "voice", "stt")
    supports_refs = True
    #: servidores (base) em que a rota `/images` não existe: a imagem vai direto pelo chat
    _no_images: Set[str] = set()

    #: limites conhecidos de referências por modelo (o catálogo e a mensagem de erro do provedor valem mais do que isto)
    _REF_LIMITS = ((re.compile(r"^x-ai/|grok", re.I), 3),)

    def max_refs(self, model: str = "") -> int:
        """Quantas referências o modelo aceita: o catálogo (`input_references` com `max`), o limite aprendido de uma recusa («must have between 0 and 3 items»), um limite conhecido (xAI: 3) ou 4."""
        name = model or self.model_for("image", model) or ""
        learned = OpenRouterMedia._learned_refs.get(name)
        if learned:
            return learned
        try:
            sp = (self._catalog("images").get(name) or {}).get("supported_parameters") or {}
        except Exception:  # noqa: BLE001
            sp = {}
        d = sp.get("input_references")
        if isinstance(d, dict) and isinstance(d.get("max"), int) and d["max"] > 0:
            return int(d["max"])
        for rx, n in self._REF_LIMITS:
            if rx.search(name):
                return n
        return 4

    #: modelo → limite de referências aprendido de uma recusa do provedor
    _learned_refs: Dict[str, int] = {}

    def _h(self) -> Dict[str, str]:
        self.need_key()
        return {"Authorization": f"Bearer {self.key}", "X-Title": "OpenFlow", "HTTP-Referer": "https://github.com/KMC1525/OpenFlow"}

    def _chat(self, body: Dict[str, Any], timeout: float = 300) -> Dict[str, Any]:
        try:
            res = _retry(self.ctl, lambda: http.post_json(f"{self.base}/chat/completions", body, self._h(), timeout=timeout))
        except ProviderError as exc:
            if exc.status == 402:
                raise ProviderError("OpenRouter: sem créditos para esta chamada. Adicione créditos em openrouter.ai/credits ou escolha um modelo mais barato.", status=402) from None
            raise
        if isinstance(res, dict) and isinstance(res.get("error"), dict):   # o OpenRouter devolve erros de provedor com status 200
            raise ProviderError(f"{self.label}: {res['error'].get('message') or res['error']}")
        return res if isinstance(res, dict) else {}

    def _image_via_chat(self, prompt: str, size: str, count: int, negative: str, refs: Sequence[Ref], model: str, extra: Optional[Dict[str, Any]], via_images: bool = False) -> List[Media]:
        """Geração/edição pelo chat: `modalities` + `image_config`; as referências vão como `image_url` (data URI) antes do texto."""
        text_part = prompt + (f"\n\nEvite: {negative}" if negative else "")
        content: Any = text_part
        if refs:
            content = [{"type": "text", "text": text_part}] + [{"type": "image_url", "image_url": {"url": _data_uri(d, m)}} for d, m in list(refs)[:4]]
        body: Dict[str, Any] = {"model": model, "messages": [{"role": "user", "content": content}], "modalities": ["image", "text"],
                                "image_config": {"aspect_ratio": aspect_of(size), "image_size": _image_size_tier(size)}}
        body.update(extra or {})
        out: List[Media] = []
        for _ in range(max(1, count)):
            try:
                res = self._chat(body)
            except ProviderError as exc:
                msg = str(exc).lower()
                if not via_images and ("/images" in msg or "images endpoint" in msg or "cannot be used with the chat" in msg):   # «é um modelo só de imagem: use /api/v1/images» (ex.: openai/gpt-image-2.6-flare)
                    self.ctl.note("Este modelo só gera imagem: usando a rota de imagens do OpenRouter…")
                    return self._image_via_images(prompt, size, count, 0, negative, refs, model, extra)
                if exc.status in (400, 404, 422) and ("modalit" in msg or "image_config" in msg or "image_size" in msg):   # o modelo só gera imagem (ou não conhece a configuração): tenta de novo mais simples
                    self.ctl.note("O modelo não aceitou estas opções de imagem: tentando de novo só com a proporção…")
                    body["modalities"] = ["image"]
                    body["image_config"] = {"aspect_ratio": aspect_of(size)}
                    res = self._chat(body)
                else:
                    raise
            got = 0
            for mime, url in _openrouter_images(res):
                m = _DATA_URI.match(url) if url.startswith("data:") else None
                if m:
                    out.append(expect_media(base64.b64decode(re.sub(r"\s", "", m.group(2))), m.group(1), "image", self.label))
                    got += 1
                elif url.startswith("http"):
                    data, mt = http.get_bytes(url, self._h(), timeout=300)
                    out.append(expect_media(data, mt, "image", self.label))
                    got += 1
            if not got:
                txt = str((((res.get("choices") or [{}])[0] or {}).get("message") or {}).get("content") or "")[:200].strip()
                raise ProviderError(f"{self.label}: o modelo {model} não devolveu imagem" + (f" (respondeu: «{txt}»)" if txt else "") + ". Escolha um modelo com saída de imagem («Carregar modelos»).")
            if len(out) >= count:
                break
        return out[:max(1, count)]

    # ---- catálogo: o que cada modelo aceita (GET /images/models e /videos/models, sem chave), guardado por 10 minutos
    _catalog_cache: Dict[Tuple[str, str], Tuple[float, Dict[str, Dict[str, Any]]]] = {}

    def _catalog(self, kind: str) -> Dict[str, Dict[str, Any]]:
        """{id do modelo: registro} de «images» ou «videos»; {} se o servidor não responde (aí as chamadas seguem sem validação prévia)."""
        key = (self.base, kind)
        hit = OpenRouterMedia._catalog_cache.get(key)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
        out: Dict[str, Dict[str, Any]] = {}
        try:
            res = http.get_json(f"{self.base}/{kind}/models", {"X-Title": "OpenFlow"}, timeout=20)
            out = {m["id"]: m for m in ((res.get("data") if isinstance(res, dict) else None) or []) if isinstance(m, dict) and m.get("id")}
        except Exception:  # noqa: BLE001 — catálogo é opcional
            out = {}
        OpenRouterMedia._catalog_cache[key] = (time.time(), out)
        return out

    @staticmethod
    def _nearest_ratio(w: int, h: int, values: Sequence[str]) -> str:
        """A proporção da lista mais próxima de w:h («auto» não conta)."""
        best, dist = "", 1e9
        for v in values:
            try:
                a, b = [float(x) for x in str(v).split(":")]
            except ValueError:
                continue
            d = abs(math.log((a / b) / (w / max(1, h))))
            if d < dist:
                best, dist = str(v), d
        return best

    def _image_body(self, model: str, prompt: str, size: str, seed: int, refs: Sequence[Ref], extra: Optional[Dict[str, Any]], entry: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """(corpo completo, corpo mínimo) da rota `/images`. O completo leva só o que o catálogo diz que o modelo aceita (proporção, resolução, seed); `size` em pixels não é enviado (a xAI e outros o recusam).
        As referências vão em `input_references` (URL ou data URL). Sem catálogo, só a proporção."""
        sp = (entry or {}).get("supported_parameters") or {}
        w, h = parse_wh(size)
        minimal: Dict[str, Any] = {"model": model, "prompt": prompt}
        if refs:
            minimal["input_references"] = [{"type": "image_url", "image_url": {"url": _data_uri(d, m)}} for d, m in list(refs)[:self.max_refs(model)]]
        full = dict(minimal)
        if not sp or "aspect_ratio" in sp:
            vals = [v for v in ((sp.get("aspect_ratio") or {}).get("values") or []) if v != "auto"]
            full["aspect_ratio"] = (self._nearest_ratio(w, h, vals) if vals else aspect_of(size)) or aspect_of(size)
        if "resolution" in sp:
            vals = (sp.get("resolution") or {}).get("values") or []
            tier = _image_size_tier(size)
            if not vals or tier in vals:
                full["resolution"] = tier
            elif vals:   # o modelo não tem esse degrau: o mais próximo do pedido
                order = {"512": 0, "768": 1, "1K": 2, "1.5K": 3, "2K": 4, "4K": 5}
                full["resolution"] = min(vals, key=lambda v: abs(order.get(str(v), 2) - order.get(tier, 2)))
        if seed and "seed" in sp:
            full["seed"] = int(seed)
        full.update({k: v for k, v in (extra or {}).items() if k not in ("load",)})
        return full, minimal

    def _image_via_images(self, prompt: str, size: str, count: int, seed: int, negative: str, refs: Sequence[Ref], model: str, extra: Optional[Dict[str, Any]]) -> List[Media]:
        """A rota dedicada `POST /images` (geração e edição: `input_references`), a certa para os modelos que só geram imagem (OpenAI gpt-image, xAI, FLUX, Seedream…)."""
        h = self._h()
        entry = self._catalog("images").get(model)
        text_part = prompt + (f"\n\nEvite: {negative}" if negative else "")
        full, minimal = self._image_body(model, text_part, size, seed, refs, extra, entry)
        out: List[Media] = []
        for i in range(max(1, count)):
            body = dict(full)
            if "seed" in body and i:
                body["seed"] = int(body["seed"]) + i   # cada imagem do lote com a sua semente
            try:
                res = _retry(self.ctl, lambda: http.post_json(f"{self.base}/images", body, h, timeout=600))
            except ProviderError as exc:
                if exc.status == 402:
                    raise ProviderError("OpenRouter: sem créditos para esta chamada. Adicione créditos em openrouter.ai/credits ou escolha um modelo mais barato.", status=402) from None
                if exc.status in (404, 405, 501) and not out and not entry:   # sem a rota própria (servidor compatível mais simples): o chat com `modalities` é o caminho
                    OpenRouterMedia._no_images.add(self.base)
                    return self._image_via_chat(prompt, size, count, negative, refs, model, extra, via_images=True)
                m = re.search(r"between\s+\d+\s+and\s+(\d+)\s+items|at most\s+(\d+)\s+(?:items|images|references)|maximum of\s+(\d+)", str(exc), re.I)
                lim = int(next(g for g in m.groups() if g)) if m else 0
                if exc.status in (400, 422) and lim and refs and len(body.get("input_references") or []) > lim:   # «input_references: must have between 0 and 3 items» (xAI): usa só as primeiras e lembra o limite
                    OpenRouterMedia._learned_refs[model] = lim
                    self.ctl.note(f"Este modelo aceita no máximo {lim} imagens de referência: usando só as {lim} primeiras.")
                    minimal["input_references"] = minimal["input_references"][:lim]
                    full["input_references"] = full["input_references"][:lim]
                    body = dict(full)
                    res = _retry(self.ctl, lambda: http.post_json(f"{self.base}/images", body, h, timeout=600))
                elif exc.status in (400, 422) and body != minimal:   # alguma opção (proporção, resolução, seed…) não vale para este modelo: tenta de novo só com o essencial
                    self.ctl.note("O modelo não aceitou algumas opções de imagem: tentando de novo só com o texto e as referências…")
                    body = dict(minimal)
                    full = dict(minimal)
                    res = _retry(self.ctl, lambda: http.post_json(f"{self.base}/images", body, h, timeout=600))
                else:
                    raise
            items = (res.get("data") if isinstance(res, dict) else None) or []
            got = 0
            for it in items:
                b64 = it.get("b64_json") if isinstance(it, dict) else None
                if b64:
                    out.append(expect_media(base64.b64decode(b64), (it.get("media_type") or "image/png"), "image", self.label))
                    got += 1
                elif isinstance(it, dict) and it.get("url"):
                    data, mime = http.get_bytes(it["url"], h, timeout=300)
                    out.append(expect_media(data, mime, "image", self.label))
                    got += 1
            if not got:
                err = res.get("error") if isinstance(res, dict) else None
                raise ProviderError(f"{self.label}: nenhuma imagem devolvida" + (f" ({err.get('message', err) if isinstance(err, dict) else err})." if err else "."))
            if len(out) >= count:
                break
        return out[:max(1, count)]

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        self._h()
        model = self.model_for("image", model) or "google/gemini-2.5-flash-image"
        cat = self._catalog("images")
        # modelos do catálogo de imagens (inclui edição por referências) vão pela rota `/images`; os que só existem como chat multimodal (ou servidor sem a rota) vão pelo chat
        if self.base in self._no_images or (cat and model not in cat):
            return self._image_via_chat(prompt, size, count, negative, refs, model, extra)
        return self._image_via_images(prompt, size, count, seed, negative, refs, model, extra)

    def _video_entry(self, model: str) -> Dict[str, Any]:
        return self._catalog("videos").get(model) or {}

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        h = self._h()
        model = self.model_for("video", model) or "google/veo-3.1"
        ent = self._video_entry(model)
        body: Dict[str, Any] = {"model": model, "prompt": prompt}
        # o que o catálogo diz que o modelo aceita (duração, proporção, resolução); valores fora da lista dão 400
        durs = [int(x) for x in (ent.get("supported_durations") or []) if isinstance(x, (int, float))]
        body["duration"] = min(durs, key=lambda d: abs(d - int(duration))) if durs else int(duration)
        ratios = [str(x) for x in (ent.get("supported_aspect_ratios") or [])]
        body["aspect_ratio"] = aspect if (not ratios or aspect in ratios) else (self._nearest_ratio(*size_of_aspect(aspect, 1000), ratios) or aspect)
        ress = [str(x) for x in (ent.get("supported_resolutions") or [])]
        if ress:   # o degrau mais perto do pedido (sem pedido, ~720p: barato e suficiente)
            short = {"480p": 480, "720p": 720, "768p": 768, "1080p": 1080, "1K": 1024, "2K": 2048, "4K": 2160}
            target = int(long_side * 9 / 16) if long_side else 720
            body["resolution"] = min(ress, key=lambda r: abs(short.get(r, 720) - target))
        if seed:
            body["seed"] = int(seed)
        body.update({k: v for k, v in (extra or {}).items() if k != "load"})
        if image:
            body["frame_images"] = [{"type": "image_url", "image_url": {"url": f"data:{image[1]};base64,{base64.b64encode(image[0]).decode('ascii')}"}, "frame_type": "first_frame"}]
        try:
            job = _retry(self.ctl, lambda: http.post_json(f"{self.base}/videos", body, h, timeout=120))
        except ProviderError as exc:
            if exc.status == 402:
                raise ProviderError("OpenRouter: sem créditos para esta chamada. Adicione créditos em openrouter.ai/credits ou escolha um modelo mais barato.", status=402) from None
            if exc.status in (400, 422):   # alguma opção não vale para este modelo: tira a imagem inicial e as opções de qualidade, na ordem, e tenta de novo
                for drop, why in (("frame_images", "a imagem inicial"), ("resolution", "a resolução"), ("seed", "a semente"), ("aspect_ratio", "a proporção")):
                    if drop not in body:
                        continue
                    body.pop(drop)
                    self.ctl.note(f"Este modelo de vídeo não aceitou {why}: tentando de novo sem isso.")
                    try:
                        job = _retry(self.ctl, lambda: http.post_json(f"{self.base}/videos", body, h, timeout=120))
                        break
                    except ProviderError as exc2:
                        if exc2.status not in (400, 422):
                            raise
                        exc = exc2
                else:
                    raise exc
            else:
                raise
        vid, poll = (job.get("id") if isinstance(job, dict) else None), (job.get("polling_url") if isinstance(job, dict) else None)
        if not vid and not poll:
            raise ProviderError(f"{self.label}: resposta inesperada ao criar o vídeo.")
        poll = poll or f"{self.base}/videos/{vid}"
        deadline = time.time() + 1800
        while True:
            self.ctl.check()
            st = http.get_json(poll, h, timeout=60)
            status = str((st or {}).get("status", "")).lower()
            if status == "completed":
                break
            if status in ("failed", "cancelled", "expired"):
                raise ProviderError(f"{self.label}: vídeo {status}" + (f" — {st.get('error')}" if st.get("error") else "."))
            if time.time() > deadline:
                raise ProviderError(f"{self.label}: o vídeo demorou demais (mais de 30 minutos).")
            self.ctl.note("Gerando vídeo…")
            self.ctl.sleep(self.poll(10))
        vid = vid or st.get("id")
        urls = [u for u in (st.get("unsigned_urls") or []) if isinstance(u, str) and u.startswith("http")]
        data, mime = http.get_bytes(urls[0] if urls else f"{self.base}/videos/{vid}/content?index=0", {**h, "Accept": "video/*"}, timeout=900)   # a URL não é assinada: leva a chave
        return expect_media(data, mime, "video", self.label)

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        h = self._h()
        model = self.model_for("voice", model) or "openai/gpt-4o-mini-tts"
        body: Dict[str, Any] = {"model": model, "input": text[:4000], "voice": voice or "alloy", "response_format": "mp3", "speed": speed}
        body.update(extra or {})
        data, mime = _retry(self.ctl, lambda: http.post_bytes(f"{self.base}/audio/speech", body, h, timeout=300))
        return expect_media(data, mime or "audio/mpeg", "audio", self.label)

    def transcribe(self, data, filename, mime, *, language="", model=""):
        """Transcrição por um modelo de chat que ouve áudio (`input_audio` em base64): pede a fala palavra por palavra, sem comentários. Formatos fora da lista viram MP3 pelo ffmpeg."""
        h = self._h()
        model = self.model_for("stt", model) or "google/gemini-2.5-flash"
        ext = (filename.rsplit(".", 1)[-1] if "." in (filename or "") else "").lower() or (mime or "").split("/")[-1].lower()
        fmt = _OR_AUDIO_FORMATS.get(ext) or _OR_AUDIO_FORMATS.get((mime or "").split("/")[-1].lower())
        if not fmt:
            ff = proc.ffmpeg_path()
            if not ff:
                raise ProviderError(f"OpenRouter: o formato de áudio «{ext or mime}» não é aceito e não há ffmpeg para converter em MP3. Envie WAV, MP3, M4A, OGG ou FLAC.")
            with tempfile.TemporaryDirectory() as tmp:
                src, dst = Path(tmp) / ("in." + (ext or "bin")), Path(tmp) / "out.mp3"
                src.write_bytes(data)
                r = subprocess.run([ff, "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(dst)], capture_output=True, timeout=300)
                if r.returncode != 0 or not dst.is_file():
                    raise ProviderError("OpenRouter: não consegui converter o áudio para MP3 (o arquivo é um áudio válido?).")
                data, fmt = dst.read_bytes(), "mp3"
        lang = f" O idioma da fala é «{language.split('-')[0]}»." if language and language != "auto" else ""
        body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Transcreva a fala deste áudio palavra por palavra, no idioma original, sem traduzir, sem resumir e sem comentários." + lang + " Responda só com a transcrição."},
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(data).decode("ascii"), "format": fmt}}]}]}
        res = self._chat(body, timeout=600)
        msg = (((res.get("choices") or [{}])[0] or {}).get("message") or {})
        content = msg.get("content")
        txt = "".join(p.get("text", "") for p in content if isinstance(p, dict)) if isinstance(content, list) else str(content or "")
        txt = txt.strip()
        if not txt:
            raise ProviderError(f"OpenRouter: o modelo {model} não devolveu texto. Escolha um modelo que aceite áudio de entrada («Carregar modelos»).")
        return txt

    def list_models(self, cap: str) -> List[str]:
        """Modelos de cada tipo pelas modalidades declaradas: imagem = saída de imagem; voz = saída de áudio; transcrição = entrada de áudio com saída de texto; vídeo = `/videos/models`."""
        self.need_key()
        if cap == "video":
            res = http.get_json(f"{self.base}/videos/models", self._h(), timeout=30)
            return sorted({m.get("id") for m in (res.get("data") or []) if isinstance(m, dict) and m.get("id")})
        if cap not in ("image", "voice", "stt"):
            return []   # o OpenRouter não tem som/música: nada a listar
        extra_ids: set = set()
        if cap == "image":   # o catálogo próprio de imagens (os modelos da rota `/images`: OpenAI gpt-image, xAI, FLUX, Seedream…) soma-se aos de chat com saída de imagem
            extra_ids = set(self._catalog("images"))
        res = http.get_json(f"{self.base}/models" + ("?output_modalities=image" if cap == "image" else ""), self._h(), timeout=30)
        want_in, want_out = {"image": (None, "image"), "voice": (None, "audio"), "stt": ("audio", "text")}[cap]
        ids = set()
        for m in (res.get("data") or []) if isinstance(res, dict) else []:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
            ins, outs = set(arch.get("input_modalities") or []), set(arch.get("output_modalities") or [])
            if cap == "image" and not arch:
                ids.add(m["id"])   # a resposta já veio filtrada pelo servidor (sem detalhes de arquitetura)
            elif (want_in is None or want_in in ins) and (want_out is None or want_out in outs):
                ids.add(m["id"])
        return sorted(ids | extra_ids | (set(MEDIA_PRESETS["openrouter"]["suggest"].get(cap, [])) if cap in ("voice",) else set()))

    def test(self) -> str:
        res = http.get_json(f"{self.base}/auth/key", self._h(), timeout=30)
        return "chave válida" + (f" ({(res.get('data') or {}).get('label')})" if isinstance(res, dict) and isinstance(res.get("data"), dict) and res["data"].get("label") else "")


# --------------------------------------------------------------------------- Stability AI


class StabilityMedia(MediaProvider):
    id, label = "stability", "Stability AI"
    caps = ("image",)
    supports_refs = True

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        self.need_key()
        model = (self.model_for("image", model) or "core").lower()
        endpoint = "core" if model == "core" else "ultra" if model == "ultra" else "sd3"
        fields: Dict[str, Any] = {"prompt": prompt, "output_format": "png", "aspect_ratio": aspect_of(size) if aspect_of(size) in ("1:1", "16:9", "9:16", "3:2", "2:3", "4:3") else "1:1"}
        if aspect_of(size) == "4:3":
            fields["aspect_ratio"] = "5:4"
        elif aspect_of(size) == "3:4":
            fields["aspect_ratio"] = "4:5"
        if negative:
            fields["negative_prompt"] = negative
        if endpoint == "sd3":
            fields["model"] = model
        files: List[Tuple[str, str, bytes, str]] = []
        if refs and endpoint != "core":
            fields.update({"mode": "image-to-image", "strength": 0.6} if endpoint == "sd3" else {"strength": 0.6})
            fields.pop("aspect_ratio", None)
            files.append(("image", "ref.png", refs[0][0], refs[0][1]))
        fields.update({k: v for k, v in (extra or {}).items() if isinstance(v, (str, int, float))})
        out: List[Media] = []
        for i in range(max(1, count)):
            if seed or i:
                fields["seed"] = (seed + i) % 4294967294
            data, mime = _retry(self.ctl, lambda: http.post_multipart_files(f"{self.base}/v2beta/stable-image/generate/{endpoint}", fields, files,
                                                                              {**_auth(self.key), "Accept": "image/*"}, timeout=300, raw=True))
            out.append(expect_media(data, mime, "image", self.label))
        return out

    def test(self) -> str:
        self.need_key()
        res = http.get_json(self.base + "/v1/user/balance", _auth(self.key), timeout=30)
        return f"conectado (créditos: {res.get('credits', '?')})"


# --------------------------------------------------------------------------- Replicate


class ReplicateMedia(MediaProvider):
    """Replicate roda milhares de modelos de várias empresas. Informe o modelo como `dono/nome` (ou `dono/nome:versão`)."""

    id, label = "replicate", "Replicate"
    caps = ("image", "video", "sound", "voice")
    supports_refs = True
    _info: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[str]]] = {}
    IMAGE_KEYS = ("image", "input_image", "first_frame_image", "start_image", "init_image", "image_url", "input_images")

    def _h(self, wait: bool = False) -> Dict[str, str]:
        self.need_key()
        return {**_auth(self.key), **({"Prefer": "wait=45"} if wait else {})}

    def _model_info(self, slug: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """(propriedades de entrada do modelo, id da versão mais recente) — para só enviar parâmetros que o modelo aceita."""
        key = self.base + "|" + slug
        if key not in self._info:
            props, latest = None, None
            try:
                info = http.get_json(f"{self.base}/models/{slug}", self._h(), timeout=30)
                ver = info.get("latest_version") or {}
                latest = ver.get("id")
                inp = (((ver.get("openapi_schema") or {}).get("components") or {}).get("schemas") or {}).get("Input") or {}
                props = inp.get("properties") or None
            except ProviderError:
                pass
            self._info[key] = (props, latest)
        return self._info[key]

    def _run(self, slug: str, wanted: Dict[str, Any], extra: Optional[Dict[str, Any]], kind: str, image_value: Any = None) -> List[Media]:
        if not slug:
            raise ProviderError("Replicate: informe o modelo (ex.: black-forest-labs/flux-schnell) no nó ou em Configuração → Mídia.")
        name, _, version = slug.partition(":")
        props, latest = self._model_info(name)
        inp = dict(wanted)
        if image_value is not None:
            key = next((k for k in self.IMAGE_KEYS if props and k in props), "image")
            inp[key] = [image_value] if key == "input_images" else image_value
        if props is not None:
            inp = {k: v for k, v in inp.items() if k in props}
        inp.update(extra or {})
        h = self._h(wait=True)
        if version:
            url, body = f"{self.base}/predictions", {"version": version, "input": inp}
        else:
            url, body = f"{self.base}/models/{name}/predictions", {"input": inp}
        try:
            pred = _retry(self.ctl, lambda: http.post_json(url, body, h, timeout=120))
        except ProviderError as exc:
            if exc.status == 404 and latest and not version:  # modelo da comunidade: precisa de versão
                pred = _retry(self.ctl, lambda: http.post_json(f"{self.base}/predictions", {"version": latest, "input": inp}, h, timeout=120))
            else:
                raise
        return self._collect(pred, kind)

    def _collect(self, pred: Any, kind: str) -> List[Media]:
        deadline = time.time() + 1800
        while isinstance(pred, dict) and pred.get("status") in ("starting", "processing"):
            if time.time() > deadline:
                raise ProviderError("Replicate: a geração demorou demais (mais de 30 minutos).")
            try:
                self.ctl.check()
            except BaseException:
                cancel = (pred.get("urls") or {}).get("cancel")
                if cancel:
                    try:
                        http.post_json(cancel, {}, self._h(), timeout=20)
                    except ProviderError:
                        pass
                raise
            self.ctl.note("Replicate: gerando…")
            self.ctl.sleep(self.poll(2.5))
            pred = http.get_json(pred["urls"]["get"], self._h(), timeout=60)
        if not isinstance(pred, dict) or pred.get("status") != "succeeded":
            raise ProviderError(f"Replicate: {(pred or {}).get('error') or 'a geração não foi concluída'}" if isinstance(pred, dict) else "Replicate: resposta inesperada.")
        urls: List[str] = []

        def walk(v: Any) -> None:
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                urls.append(v)
            elif isinstance(v, list):
                for i in v:
                    walk(i)
            elif isinstance(v, dict):
                for i in v.values():
                    walk(i)

        walk(pred.get("output"))
        if not urls:
            raise ProviderError("Replicate: o modelo não devolveu arquivos.")
        out = []
        for u in urls[:8]:
            data, mime = http.get_bytes(u, timeout=600)
            out.append(expect_media(data, mime, kind, self.label))
        return out

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        wanted: Dict[str, Any] = {"prompt": prompt, "aspect_ratio": aspect_of(size), "output_format": "png"}
        w, h = parse_wh(size)
        wanted.update({"width": w, "height": h})
        if count > 1:
            wanted["num_outputs"] = count
        if seed:
            wanted["seed"] = seed
        if negative:
            wanted["negative_prompt"] = negative
        props, _ = self._model_info(self.model_for("image", model).partition(":")[0]) if self.model_for("image", model) else (None, None)
        if props is not None and "aspect_ratio" in props:
            wanted.pop("width", None)
            wanted.pop("height", None)
        elif props is None:  # sem esquema conhecido: manda só o essencial
            for k in ("width", "height", "output_format"):
                wanted.pop(k, None)
        return self._run(self.model_for("image", model), wanted, extra, "image", data_uri(*refs[0]) if refs else None)[:max(1, count)]

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        wanted: Dict[str, Any] = {"prompt": prompt, "duration": int(duration), "aspect_ratio": aspect}
        if seed:
            wanted["seed"] = seed
        return self._run(self.model_for("video", model), wanted, extra, "video", data_uri(*image) if image else None)[0]

    def sound(self, prompt, *, kind="sfx", duration=5, model="", extra=None, seed=0):
        wanted: Dict[str, Any] = {"prompt": prompt, "duration": int(duration)}
        if seed:
            wanted["seed"] = seed
        return self._run(self.model_for("sound", model), wanted, extra, "audio")[0]

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        wanted: Dict[str, Any] = {"text": text, "prompt": text, "speed": speed}
        if voice:
            wanted["voice"] = voice
        slug = self.model_for("voice", model)
        props, _ = self._model_info(slug.partition(":")[0]) if slug else (None, None)
        if props is not None and "text" in props:
            wanted.pop("prompt", None)
        elif props is None:
            wanted.pop("prompt", None)
        return self._run(slug, wanted, extra, "audio")[0]

    def test(self) -> str:
        res = http.get_json(self.base + "/account", self._h(), timeout=30)
        return f"conectado ({res.get('username', 'conta')})"


# --------------------------------------------------------------------------- Hugging Face Inference


class HFInferenceMedia(MediaProvider):
    id, label = "huggingface", "Hugging Face (Inference)"
    caps = ("image", "sound", "voice", "stt")

    def _call(self, model: str, payload: Optional[Dict[str, Any]] = None, raw: Optional[bytes] = None, ctype: str = "", accept: str = "*/*") -> Tuple[bytes, str]:
        self.need_key()
        if not model:
            raise ProviderError("Hugging Face: informe o modelo (ex.: black-forest-labs/FLUX.1-schnell) no nó ou em Configuração → Mídia.")
        url = f"{self.base}/{model}"
        headers = {**_auth(self.key), "Accept": accept}
        if raw is not None:
            headers["Content-Type"] = ctype or "application/octet-stream"

        def go() -> Tuple[bytes, str]:
            with http.request(url, payload, headers, raw_body=raw, timeout=600) as resp:
                return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")

        return _retry(self.ctl, go, tries=4, statuses=(429, 502, 503, 504))

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        model = self.model_for("image", model)
        w, h = parse_wh(size)
        out = []
        for i in range(max(1, count)):
            params: Dict[str, Any] = {"width": w, "height": h}
            if negative:
                params["negative_prompt"] = negative
            if seed or i:
                params["seed"] = seed + i
            params.update(extra or {})
            data, mime = self._call(model, {"inputs": prompt, "parameters": params, "options": {"wait_for_model": True}}, accept="image/*")
            out.append(expect_media(data, mime, "image", self.label))
        return out

    def sound(self, prompt, *, kind="sfx", duration=5, model="", extra=None, seed=0):
        data, mime = self._call(self.model_for("sound", model), {"inputs": prompt, "parameters": dict(extra or {}), "options": {"wait_for_model": True}}, accept="audio/*")
        return expect_media(data, mime, "audio", self.label)

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        data, mime = self._call(self.model_for("voice", model), {"inputs": text, "parameters": dict(extra or {}), "options": {"wait_for_model": True}}, accept="audio/*")
        return expect_media(data, mime, "audio", self.label)

    def transcribe(self, data, filename, mime, *, language="", model=""):
        body, _ = self._call(self.model_for("stt", model), raw=data, ctype=mime or "audio/mpeg", accept="application/json")
        try:
            out = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            raise ProviderError("Hugging Face: resposta de transcrição inválida.") from None
        if isinstance(out, dict) and out.get("error"):
            raise ProviderError(f"Hugging Face: {out['error']}")
        return str(out.get("text", "") if isinstance(out, dict) else out).strip()

    def test(self) -> str:
        self.need_key()
        res = http.get_json("https://huggingface.co/api/whoami-v2", _auth(self.key), timeout=30)
        return f"conectado ({res.get('name', 'conta')})"


# --------------------------------------------------------------------------- Stable Diffusion WebUI (A1111 / Forge, local)


class A1111Media(MediaProvider):
    id, label = "a1111", "Stable Diffusion WebUI (local)"
    caps = ("image",)
    supports_refs = True

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        self.need_url()
        w, h = parse_wh(size)
        body: Dict[str, Any] = {"prompt": prompt, "negative_prompt": negative, "width": w, "height": h, "seed": seed if seed else -1, "batch_size": max(1, min(4, count)), "n_iter": 1,
                                "steps": 25, "send_images": True, "save_images": False}
        model = self.model_for("image", model)
        if model:
            body["override_settings"] = {"sd_model_checkpoint": model}
        path = "txt2img"
        if refs:
            path = "img2img"
            body.update({"init_images": [base64.b64encode(refs[0][0]).decode("ascii")], "denoising_strength": 0.6})
        body.update(extra or {})
        res = _retry(self.ctl, lambda: http.post_json(f"{self.base}/sdapi/v1/{path}", body, _auth(self.key), timeout=900))
        imgs = [expect_media(base64.b64decode(b.split(",", 1)[-1]), "", "image", self.label) for b in (res.get("images") if isinstance(res, dict) else None) or []]
        if not imgs:
            raise ProviderError("Stable Diffusion WebUI não devolveu imagens (a WebUI foi iniciada com --api?).")
        return imgs[:max(1, count)]

    def list_models(self, cap: str) -> List[str]:
        self.need_url()
        res = http.get_json(self.base + "/sdapi/v1/sd-models", _auth(self.key), timeout=30)
        return [m.get("title", "") for m in res if isinstance(m, dict)]

    def test(self) -> str:
        return f"conectado ({len(self.list_models('image'))} modelos)"


# --------------------------------------------------------------------------- Modelos do Hugging Face rodando localmente

_LOCAL_LOCK = threading.Lock()
_LOCAL_CACHE: Dict[Tuple[str, str], Any] = {}


def _local_import(*names: str, extra: str = "media") -> List[Any]:
    try:
        return [__import__(n, fromlist=["_"]) for n in names]
    except ImportError as exc:
        raise ProviderError(f'Modelos locais precisam das bibliotecas opcionais ({exc.name}). Instale com:  pip install "openflow[' + extra + ']"  (ou rode: flow libs)') from None


def _device() -> Tuple[str, Any]:
    (torch,) = _local_import("torch")
    if _perf.device() == "cpu":   # Configurações → Desempenho → Rodar em: só CPU
        return "cpu", torch.float32
    if torch.cuda.is_available():
        return "cuda", torch.float16
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps", torch.float16
    return "cpu", torch.float32


def _give_back_memory() -> None:
    """Depois de descarregar um modelo de mídia: tira os pesos do cache de páginas e devolve ao sistema a RAM que o alocador ainda segura (núcleo Rust)."""
    try:
        for f in (_PLAN.get("files") or [])[:64]:
            _native.evict_file(f)
        _native.release_memory()
    except Exception:  # noqa: BLE001
        pass


def _media_unload() -> None:
    with _LOCAL_LOCK:
        _LOCAL_CACHE.clear()
    gc.collect()
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    _give_back_memory()


_MEDIA_IDLE = _perf.IdleUnloader(_media_unload)
PERF: Dict[str, Any] = {}  # settings["performance"], preenchido pela rota/engine antes de gerar


_PLAN: Dict[str, Any] = {}   # plano de carga do modelo que está sendo carregado (núcleo Rust): estratégia de GPU/descarga, fatias de atenção e VAE


def _media_plan(model: str) -> Dict[str, Any]:
    """Plano de carga a partir do tamanho REAL dos pesos baixados e da memória livre agora. Qualquer falha devolve {} (comportamento antigo)."""
    try:
        from . import localmodels as lm

        snap = lm._snapshot(model)
        weights = _native.dir_weight_bytes(snap) if snap else 0
        if not weights:
            return {}
        mem = _perf.memory_state()
        mode = _perf.MODE_NUM[_perf.profile(PERF, hardware_info())["mode"]]
        plan = _native.plan_media(weights, mem["vram_free"], mem["ram_avail"], mem["unified"], mode)
        plan.update(weights=weights, files=_native.weight_files(snap))
        return plan
    except Exception:  # noqa: BLE001
        return {}


def _slim(pipe: Any, dev: str) -> Any:
    """Coloca o modelo no dispositivo seguindo o plano: tudo na GPU, descarga do modelo, descarga sequencial (cabe em pouca VRAM) ou CPU; fatias de atenção/VAE quando o plano pede.
    Sem plano (tamanho desconhecido), vale o modo de desempenho como antes."""
    plan = dict(_PLAN)
    prof = _perf.profile(PERF, hardware_info())
    if not plan.get("strategy"):
        plan = {"strategy": "model_offload" if prof["media_offload"] and dev == "cuda" else "gpu", "slicing": prof["media_offload"], "tiling": prof["media_offload"]}
    for flag, fns in (("slicing", ("enable_attention_slicing", "enable_vae_slicing")), ("tiling", ("enable_vae_tiling",))):
        if plan.get(flag):
            for fn in fns:
                try:
                    getattr(pipe, fn)()
                except Exception:  # noqa: BLE001
                    pass
    if dev == "cuda" and plan["strategy"] in ("model_offload", "sequential_offload"):
        for fn in (("enable_sequential_cpu_offload", "enable_model_cpu_offload") if plan["strategy"] == "sequential_offload" else ("enable_model_cpu_offload",)):
            try:
                getattr(pipe, fn)()
                return pipe
            except Exception:  # noqa: BLE001
                pass
    return pipe.to(dev)


def _local_load(cap: str, model: str, loader: Callable[[], Any]) -> Any:
    """Mantém só um modelo local na memória por vez (hardware modesto). Antes de carregar: plano (núcleo Rust) e pré-carga paralela dos pesos para o cache do sistema."""
    _MEDIA_IDLE.touch(_perf.profile(PERF, hardware_info())["idle_s"])
    with _LOCAL_LOCK:
        key = (cap, model)
        if key not in _LOCAL_CACHE:
            had = bool(_LOCAL_CACHE)
            _LOCAL_CACHE.clear()
            gc.collect()
            try:
                import torch  # type: ignore

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            if had:
                _give_back_memory()   # trocou de modelo: a RAM do anterior volta antes de carregar o novo
            plan = _media_plan(model)
            _PLAN.clear()
            _PLAN.update(plan)
            if plan.get("prefetch") and plan.get("files"):
                _native.prefetch(plan["files"])   # leitura paralela: o from_pretrained acha os pesos já em RAM
            try:
                _LOCAL_CACHE[key] = loader()
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001
                if "torchvision" in str(exc).lower():  # ex.: processadores de visão do Qwen-Image/Qwen3-VL pedem a torchvision
                    raise ProviderError("Este modelo precisa da biblioteca torchvision, que não está instalada. Instale com:  pip install torchvision  (ou rode: flow libs --extras media) e tente de novo; depois de instalar, reinicie o OpenFlow.") from None
                raise
            if plan:
                _native.record("media", cap=cap, model=model, strategy=plan.get("strategy"), weights=plan.get("weights"), slicing=plan.get("slicing"), tiling=plan.get("tiling"))
        return _LOCAL_CACHE[key]


def _wav_from_array(arr: Any, rate: int) -> bytes:
    (np,) = _local_import("numpy")
    a = np.asarray(arr, dtype="float32")
    a = np.squeeze(a)
    if a.ndim == 2 and a.shape[0] <= 8 < a.shape[1]:
        a = a.T
    if a.ndim > 2:
        a = a.reshape(-1)
    peak = float(np.max(np.abs(a))) or 1.0
    if peak > 1.0:
        a = a / peak
    pcm = (np.clip(a, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1 if pcm.ndim == 1 else pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


# ---- Vozes da Unsloth que não passam pelo `pipeline("text-to-speech")`: Orpheus (LLM que fala em «tokens» de áudio, decodificados pelo SNAC) e Sesame CSM
ORPHEUS_VOICES = ("tara", "leah", "jess", "leo", "dan", "mia", "zac", "zoe")
ORPHEUS_CODEC = "hubertsiuzdak/snac_24khz"
_ORPHEUS_START, _ORPHEUS_END_TEXT, _ORPHEUS_END_HUMAN, _ORPHEUS_END_SPEECH, _ORPHEUS_START_SPEECH, _ORPHEUS_AUDIO_BASE = 128259, 128009, 128260, 128258, 128257, 128266


def orpheus_codes(generated: Sequence[int]) -> List[int]:
    """Os tokens gerados pelo Orpheus → códigos de áudio: corta depois do último «início de fala», tira o fim, aprova só grupos completos de 7 e tira o deslocamento dos tokens de áudio."""
    ids = [int(t) for t in generated]
    cut = max((i for i, t in enumerate(ids) if t == _ORPHEUS_START_SPEECH), default=-1)
    ids = [t for t in ids[cut + 1:] if t != _ORPHEUS_END_SPEECH]
    ids = ids[: len(ids) // 7 * 7]
    return [t - _ORPHEUS_AUDIO_BASE for t in ids]


def orpheus_layers(codes: Sequence[int]) -> Tuple[List[int], List[int], List[int]]:
    """Cada grupo de 7 códigos vira 1 + 2 + 4 códigos das três camadas do SNAC (24 kHz), cada camada com o seu deslocamento de 4096."""
    l1: List[int] = []
    l2: List[int] = []
    l3: List[int] = []
    for i in range(len(codes) // 7):
        c = codes[7 * i: 7 * i + 7]
        l1.append(c[0])
        l2.append(c[1] - 4096)
        l3.append(c[2] - 2 * 4096)
        l3.append(c[3] - 3 * 4096)
        l2.append(c[4] - 4 * 4096)
        l3.append(c[5] - 5 * 4096)
        l3.append(c[6] - 6 * 4096)
    return l1, l2, l3


class LocalHFMedia(MediaProvider):
    """Modelos do Hugging Face dentro do próprio OpenFlow (diffusers/transformers).

    Nada é baixado em silêncio: o usuário escolhe a precisão (quantização) e baixa o modelo em Configuração → Mídia (veja `localmodels.py`);
    aqui só são carregados modelos já baixados, na precisão escolhida.
    """

    id, label = "local_hf", "Hugging Face local (embutido)"
    caps = ("image", "video", "sound", "voice", "stt")
    supports_refs = True   # imagem → imagem pelo mesmo modelo
    refs_edit_only = True

    def max_refs(self, model: str = "") -> int:
        name = (model or self.model_for("image", model) or "").lower()
        if re.search(r"flux[-_. ]?3", name):
            return 10   # FLUX.3 Image Klein: até 10 imagens de referência no mesmo pedido
        return 4 if "klein" in name else 1   # FLUX.2 klein edita com várias imagens de uma vez; os demais fazem imagem → imagem com uma

    def refs_need_edit(self, model: str = "") -> bool:
        return self.max_refs(model) <= 1   # klein e FLUX.3 juntam várias referências também no modo Gerar

    @staticmethod
    def _defaults(model: str) -> Tuple[int, float]:
        """Passos e guidance do modelo (o padrão de cada família): FLUX.2 klein destilado 4 passos sem CFG; klein «base» 50 passos e guidance 4; FLUX.1 schnell 4 passos; FLUX.1 dev 28 passos e guidance 3,5;
        modelos «turbo»/«lightning»/«lcm» 2 passos sem CFG; os demais 25 passos e guidance 7."""
        name = model.lower()
        if re.search(r"flux[-_. ]?3", name):
            return (50, 3.5) if "base" in name else (16, 0.0)   # FLUX.3 Image Klein: destilado 16 passos sem guidance; «base» 50 passos e guidance 3,5
        if "klein" in name:
            return (50, 4.0) if "base" in name else (4, 1.0)
        if "schnell" in name:
            return 4, 0.0
        if any(k in name for k in ("turbo", "lightning", "lcm")):
            return 2, 0.0
        if "flux" in name:
            return 28, 3.5
        return 25, 7.0

    @staticmethod
    def _is_modular(model: str) -> bool:
        """O repositório baixado usa o pipeline modular do diffusers (FLUX.3 Image Klein: `modular_model_index.json`, sem `model_index.json`)?"""
        from . import localmodels as lm

        snap = lm._snapshot(model)
        return bool(snap and (snap / "modular_model_index.json").is_file() and not (snap / "model_index.json").is_file())

    @staticmethod
    def _load_modular(diffusers: Any, model: str, ready: Dict[str, Any]) -> Any:
        """Carrega um pipeline modular só com arquivos locais e SEM o expansor de prompt do modelo (um modelo de 9B, 18,8 GB, de outro repositório: nada é baixado em silêncio) —
        o OpenFlow expande o prompt pelo modelo de texto configurado (`canvas/upsample.py`)."""
        import huggingface_hub as hub  # type: ignore

        (torch,) = _local_import("torch")
        mp = getattr(diffusers, "ModularPipeline", None)
        if mp is None:
            raise ProviderError(f"O modelo {model} usa o pipeline modular do diffusers, que esta versão não tem. Atualize:  pip install -U diffusers transformers  (ou: flow libs).")
        consts = hub.constants
        old = consts.HF_HUB_OFFLINE
        consts.HF_HUB_OFFLINE = True   # nunca baixa: só o que o OpenFlow baixou com a precisão escolhida
        try:
            pipe = mp.from_pretrained(model)
            sub = getattr(getattr(pipe, "blocks", None), "sub_blocks", None)
            if sub is not None and "prompt_upsampler" in sub:
                sub.pop("prompt_upsampler")
                pipe = pipe.blocks.init_pipeline(model)
            pipe.load_components(dtype={"vae": torch.float32, "default": ready["dtype"]})
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Não foi possível carregar {model}: {exc}. Confira se os arquivos foram baixados (Configuração → Mídia) e se o diffusers/transformers estão atualizados:  pip install -U diffusers transformers.") from None
        finally:
            consts.HF_HUB_OFFLINE = old
        return pipe

    def _pick(self, cap: str, model: str, default: str) -> str:
        """O modelo pedido; se ele ainda não foi baixado, usa outro já baixado da mesma função (o padrão ou uma sugestão) em vez de falhar. Se nenhum foi baixado, devolve o pedido
        (e `_ready` explica como baixar). Nada é baixado em silêncio."""
        from . import localmodels as lm

        want = self.model_for(cap, model) or default
        try:
            if lm.downloaded_precision(want):
                return want
            for alt in [default] + list((MEDIA_PRESETS.get("local_hf") or {}).get("suggest", {}).get(cap, [])):
                if alt != want and lm.downloaded_precision(alt):
                    self.ctl.note(f'O modelo "{want}" ainda não foi baixado: usando "{alt}", que já está baixado.')
                    return alt
        except ProviderError:
            pass  # sem as bibliotecas de modelos locais: `_ready` mostra a mensagem de instalação
        return want

    def _ready(self, model: str) -> Dict[str, Any]:
        """Argumentos de carregamento do modelo (precisão escolhida, só arquivos locais). Recusa modelos que ainda não foram baixados."""
        from . import localmodels as lm

        prec = lm.downloaded_precision(model)
        if not prec:
            raise ProviderError(f'O modelo local "{model}" ainda não foi baixado. Em Configuração → Mídia, escolha a precisão (quantização) e baixe-o antes de usar.', status=424)
        low = prec in ("fp16", "bf16")
        self.ctl.note(f"Modelo local {model} ({prec})")
        return {"precision": prec, "dtype": lm.torch_dtype(prec), "variant": "fp16" if low and lm.has_fp16_variant(model) else None}

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        model = self._pick("image", model, "stabilityai/sd-turbo")
        (diffusers,) = _local_import("diffusers")
        dev, _ = _device()
        ready = self._ready(model)

        def load() -> Any:
            if self._is_modular(model):
                return _slim(self._load_modular(diffusers, model, ready), dev)
            kw: Dict[str, Any] = {"torch_dtype": ready["dtype"], "local_files_only": True}
            if ready["variant"]:
                kw["variant"] = ready["variant"]
            try:
                pipe = diffusers.AutoPipelineForText2Image.from_pretrained(model, **kw)
            except Exception as exc:  # noqa: BLE001 — pipelines novos (FLUX.2 klein…) que o AutoPipeline da versão instalada ainda não conhece: a classe vem do model_index.json
                try:
                    pipe = diffusers.DiffusionPipeline.from_pretrained(model, **kw)
                except Exception:  # noqa: BLE001
                    raise ProviderError(f"Não foi possível carregar {model}: {exc}. Se o modelo é novo (FLUX.2…), atualize as bibliotecas:  pip install -U diffusers transformers  (ou: flow libs).") from None
            return _slim(pipe, dev)

        pipe = _local_load("image", model, load)
        (torch,) = _local_import("torch")
        steps, guidance = self._defaults(model)
        modular = hasattr(pipe, "load_components")   # pipeline modular (FLUX.3 Image Klein)
        flux3 = bool(re.search(r"flux[-_. ]?3", model.lower()))
        fast = guidance == 0.0 or "klein" in model.lower()   # modelos destilados: sem prompt negativo (e, no FLUX, o pipeline nem o aceita)
        no_negative = fast or "flux" in model.lower()
        klein = "klein" in model.lower() and not flux3
        w, h = parse_wh(size)
        w, h = (min(w, 768), min(h, 768)) if dev == "cpu" else (w, h)
        w, h = max(256, w // 8 * 8), max(256, h // 8 * 8)
        pil = _pil_refs(refs, 10 if flux3 else 4 if klein else 1) if refs else []
        if refs and not pil:
            raise ProviderError("Não consegui ler as imagens de referência ligadas ao nó (formato não suportado).")
        i2i = None
        if pil:
            if len(pil) == 1 and self.edit_mode:   # só no modo Editar com uma imagem: mantém a proporção dela; ao Gerar (e com várias referências) vale o tamanho pedido
                w, h = _size_like(pil[0], w, h, 16 if (klein or flux3) else 8)
            if not klein and not flux3:   # imagem → imagem: reaproveita os pesos já carregados (o FLUX.2 klein edita pelo próprio pipeline, com várias imagens)
                i2i = diffusers.AutoPipelineForImage2Image.from_pipe(pipe)   # compartilha os pesos de `pipe` (não passa por _local_load: ele guarda um modelo só e descartaria o principal)
        out = []
        for i in range(max(1, count)):
            self.ctl.check()
            self.ctl.note("Gerando imagem localmente…")
            if modular:   # FLUX.3: o pipeline modular recebe prompt, imagens e semente; tamanho/passos são pedidos e, se esta versão não os aceita, o pedido repete sem eles
                gen = torch.Generator("cpu").manual_seed(int(seed + i) if seed else int(time.time() * 1000) % (2 ** 31) + i)
                mkw: Dict[str, Any] = {"prompt": prompt, "generator": gen, "output": "images"}
                if pil:
                    mkw["image"] = pil if len(pil) > 1 else pil[0]
                mkw.update(extra or {})
                opt = {"width": w, "height": h}
                if "base" in model.lower():
                    opt.update(num_inference_steps=steps, guidance_scale=guidance)
                imgs = None
                for drop in range(3):
                    try:
                        imgs = pipe(**{**mkw, **(opt if drop == 0 else {k: v for k, v in opt.items() if drop == 1 and k not in ("width", "height")})})
                        break
                    except (TypeError, ValueError, KeyError):
                        if drop == 2:
                            raise
                img = (imgs[0] if isinstance(imgs, (list, tuple)) else getattr(imgs, "images", [imgs])[0])
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                out.append(Media(buf.getvalue(), "image/png"))
                continue
            kw = {"prompt": prompt, "width": w, "height": h, "num_inference_steps": steps, "guidance_scale": guidance,
                  "generator": torch.Generator("cpu").manual_seed(int(seed + i) if seed else int(time.time() * 1000) % (2 ** 31) + i)}
            if negative and not no_negative:
                kw["negative_prompt"] = negative
            if pil and klein:
                kw["image"] = [p.resize((w, h)) for p in pil]   # edição do FLUX.2 klein: todas as imagens ligadas guiam o resultado
            elif pil:
                kw.pop("width"), kw.pop("height")
                kw.update(image=pil[0].resize((w, h)), strength=0.8 if fast else 0.75)
                if fast:
                    kw["num_inference_steps"] = max(4, steps)   # modelos «turbo»: com strength < 1 sobram menos passos, e precisam de pelo menos 1
            kw.update(extra or {})
            img = (i2i or pipe)(**kw).images[0]
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            out.append(Media(buf.getvalue(), "image/png"))
        return out

    def sound(self, prompt, *, kind="sfx", duration=5, model="", extra=None, seed=0):
        model = self._pick("sound", model, "facebook/musicgen-small")
        (tf,) = _local_import("transformers")
        ready = self._ready(model)
        pipe = _local_load("sound", model, lambda: tf.pipeline("text-to-audio", model=model, torch_dtype=ready["dtype"], model_kwargs={"local_files_only": True}))
        self.ctl.note("Gerando som localmente…")
        res = pipe(prompt, forward_params={"do_sample": True, "max_new_tokens": int(max(1, min(30, duration)) * 50), **(extra or {})})
        return Media(_wav_from_array(res["audio"], res["sampling_rate"]), "audio/wav")

    def _voice_orpheus(self, text: str, voice: str, model: str, extra: Optional[Dict[str, Any]]) -> Media:
        """Orpheus (unsloth/orpheus-3b-0.1-ft…): o LLM gera tokens de áudio e o SNAC (`hubertsiuzdak/snac_24khz`, baixado em Modelos locais) os decodifica em 24 kHz."""
        from . import localmodels as lm

        (tf,) = _local_import("transformers")
        (torch,) = _local_import("torch")
        try:
            snac = __import__("snac", fromlist=["_"])
        except ImportError:
            raise ProviderError('O Orpheus precisa do decodificador de áudio SNAC:  pip install snac  (e baixe o modelo "' + ORPHEUS_CODEC + '" em Configuração → Mídia).') from None
        ready = self._ready(model)
        if not lm.downloaded_precision(ORPHEUS_CODEC):
            raise ProviderError(f'O Orpheus usa o decodificador "{ORPHEUS_CODEC}" (≈ 80 MB), que ainda não foi baixado. Baixe-o em Configuração → Mídia antes de usar.', status=424)
        dev = "cuda" if torch.cuda.is_available() and _perf.device() != "cpu" else "cpu"

        def load() -> Any:
            old = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"   # nada é baixado em silêncio
            try:
                tok = tf.AutoTokenizer.from_pretrained(model, local_files_only=True)
                lm_ = tf.AutoModelForCausalLM.from_pretrained(model, torch_dtype=ready["dtype"], local_files_only=True).to(dev)
                codec = snac.SNAC.from_pretrained(ORPHEUS_CODEC).eval().to(dev)
            finally:
                if old is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = old
            return tok, lm_, codec

        tok, lm_, codec = _local_load("voice", model, load)
        name = (voice or "tara").strip().lower()
        prompt = f"{name if name in ORPHEUS_VOICES else 'tara'}: {text}"
        ids = tok(prompt, return_tensors="pt").input_ids
        ids = torch.cat([torch.tensor([[_ORPHEUS_START]]), ids, torch.tensor([[_ORPHEUS_END_TEXT, _ORPHEUS_END_HUMAN]])], dim=1).to(dev)
        self.ctl.note("Sintetizando voz com o Orpheus (local)…")
        gen_kw: Dict[str, Any] = {"max_new_tokens": 1200, "do_sample": True, "temperature": 0.6, "top_p": 0.95, "repetition_penalty": 1.1, "eos_token_id": _ORPHEUS_END_SPEECH, **(extra or {})}
        with torch.no_grad():
            out = lm_.generate(input_ids=ids, attention_mask=torch.ones_like(ids), **gen_kw)
        codes = orpheus_codes(out[0].tolist())
        if not codes:
            raise ProviderError("O Orpheus não devolveu áudio para este texto. Tente um texto maior ou outra voz.")
        l1, l2, l3 = orpheus_layers(codes)
        with torch.no_grad():
            audio = codec.decode([torch.tensor(l, device=dev).unsqueeze(0) for l in (l1, l2, l3)])
        return Media(_wav_from_array(audio.detach().cpu().numpy(), 24000), "audio/wav")

    def _voice_csm(self, text: str, voice: str, model: str, extra: Optional[Dict[str, Any]]) -> Media:
        """Sesame CSM (unsloth/csm-1b): `CsmForConditionalGeneration` + `processor.apply_chat_template`; o «falante» é 0 ou 1."""
        (tf,) = _local_import("transformers")
        (torch,) = _local_import("torch")
        ready = self._ready(model)
        dev = "cuda" if torch.cuda.is_available() and _perf.device() != "cpu" else "cpu"

        def load() -> Any:
            old = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"
            try:
                return tf.AutoProcessor.from_pretrained(model, local_files_only=True), tf.CsmForConditionalGeneration.from_pretrained(model, torch_dtype=ready["dtype"], local_files_only=True).to(dev)
            except AttributeError:
                raise ProviderError("Esta versão do transformers não tem o CSM (CsmForConditionalGeneration). Atualize:  pip install -U transformers") from None
            finally:
                if old is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = old

        proc, lm_ = _local_load("voice", model, load)
        speaker = "1" if str(voice).strip() == "1" else "0"
        conv = [{"role": speaker, "content": [{"type": "text", "text": text}]}]
        inputs = proc.apply_chat_template(conv, tokenize=True, return_dict=True).to(dev)
        self.ctl.note("Sintetizando voz com o CSM (local)…")
        with torch.no_grad():
            audio = lm_.generate(**inputs, output_audio=True, **(extra or {}))
        first = audio[0] if isinstance(audio, (list, tuple)) else audio
        return Media(_wav_from_array(first.to(torch.float32).cpu().numpy(), 24000), "audio/wav")

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        model = self._pick("voice", model, "suno/bark-small")
        if re.search(r"orpheus", model, re.I):
            return self._voice_orpheus(text, voice, model, extra)
        if re.search(r"(^|/)csm-1b", model, re.I):
            return self._voice_csm(text, voice, model, extra)
        (tf,) = _local_import("transformers")
        ready = self._ready(model)
        pipe = _local_load("voice", model, lambda: tf.pipeline("text-to-speech", model=model, torch_dtype=ready["dtype"], model_kwargs={"local_files_only": True}))
        self.ctl.note("Sintetizando voz localmente…")
        res = pipe(text, **(extra or {}))
        return Media(_wav_from_array(res["audio"], res["sampling_rate"]), "audio/wav")

    def transcribe(self, data, filename, mime, *, language="", model=""):
        model = self._pick("stt", model, "openai/whisper-small")
        (tf,) = _local_import("transformers")
        ready = self._ready(model)
        pipe = _local_load("stt", model, lambda: tf.pipeline("automatic-speech-recognition", model=model, torch_dtype=ready["dtype"], model_kwargs={"local_files_only": True}))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ("audio." + (MIME_EXT.get(mime, "") or (filename.rsplit(".", 1)[-1] if "." in filename else "wav")))
            p.write_bytes(data)
            kw: Dict[str, Any] = {"return_timestamps": True}
            if language and language != "auto":
                kw["generate_kwargs"] = {"language": language.split("-")[0]}
            res = pipe(str(p), **kw)
        return str(res.get("text", "")).strip()

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        """Vídeo local exige GPU com bastante memória. Os quadros viram MP4 pelo ffmpeg."""
        model = self._pick("video", model, "Lightricks/LTX-Video")
        (diffusers,) = _local_import("diffusers")
        ff = proc.ffmpeg_path()
        if not ff:
            raise ProviderError("O vídeo local precisa do ffmpeg para montar o arquivo (instale-o).")
        dev, _ = _device()
        ready = self._ready(model)
        vkw = {"torch_dtype": ready["dtype"], "local_files_only": True, **({"variant": ready["variant"]} if ready["variant"] else {})}
        pipe = _local_load("video", model, lambda: _slim(diffusers.DiffusionPipeline.from_pretrained(model, **vkw), dev))
        w, h = size_of_aspect(aspect, long_side or (704 if dev != "cpu" else 384))
        w, h = w // 32 * 32 or 32, h // 32 * 32 or 32
        fps = 24
        kw: Dict[str, Any] = {"prompt": prompt, "width": w, "height": h, "num_frames": int(max(9, min(161, duration * fps)) // 8 * 8 + 1)}
        if image:
            from PIL import Image  # type: ignore

            kw["image"] = Image.open(io.BytesIO(image[0])).convert("RGB").resize((w, h))
        kw.update(extra or {})
        self.ctl.note("Gerando vídeo localmente (pode demorar)…")
        frames = pipe(**kw).frames[0]
        return _frames_to_mp4(frames, fps)

    def test(self) -> str:
        _local_import("torch")
        dev, _ = _device()
        have = [m for m in ("diffusers", "transformers") if shutil.which("python") is not None and _has(m)]
        return f"torch ok · dispositivo: {dev} · bibliotecas: {', '.join(have) or 'nenhuma'}"


def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False


# --------------------------------------------------------------------------- Voz da Configuração (STT/TTS por servidor)


def _frames_to_mp4(frames: Any, fps: int) -> Media:
    """Quadros (imagens PIL) → MP4 pelo ffmpeg."""
    ff = proc.ffmpeg_path()
    if not ff:
        raise ProviderError("Montar o vídeo precisa do ffmpeg (instale-o).")
    with tempfile.TemporaryDirectory() as tmp:
        for i, fr in enumerate(frames):
            fr.save(Path(tmp) / f"f{i:05d}.png")
        dst = Path(tmp) / "o.mp4"
        r = perf.run([ff, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(Path(tmp) / "f%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)],
                           capture_output=True, timeout=600)
        if r.returncode != 0 or not dst.exists():
            raise ProviderError("ffmpeg falhou ao montar o vídeo: " + r.stderr.decode("utf-8", "replace")[-200:])
        return Media(dst.read_bytes(), "video/mp4")


def _pil_refs(refs: Sequence[Ref], limit: int = 4) -> List[Any]:
    """Imagens de referência (bytes, mime) como imagens RGB da PIL; as ilegíveis são ignoradas."""
    from PIL import Image  # type: ignore

    out: List[Any] = []
    for data, _mime in list(refs)[:limit]:
        try:
            out.append(Image.open(io.BytesIO(data)).convert("RGB"))
        except Exception:  # noqa: BLE001 — arquivo que não é imagem
            continue
    return out


def _max_side() -> int:
    """Maior lado, em pixels, que os modelos locais (GGUF) geram: 2048 por padrão; `OPENFLOW_MAX_SIDE` muda (512 a 4096). Tamanhos grandes pedem muita RAM/VRAM e tempo."""
    try:
        return max(512, min(int(os.environ.get("OPENFLOW_MAX_SIDE", "2048")), 4096))
    except ValueError:
        return 2048


def image_difference(a: bytes, b: bytes) -> Optional[float]:
    """Quanto duas imagens diferem (0 = iguais, 1 = opostas): diferença média de brilho depois de reduzir as duas a 64×64. None se não dá para calcular (sem a Pillow ou formato ilegível)."""
    try:
        from PIL import Image  # type: ignore

        def small(data: bytes) -> Any:
            return Image.open(io.BytesIO(data)).convert("L").resize((64, 64))

        pa, pb = small(a).tobytes(), small(b).tobytes()
        return sum(abs(x - y) for x, y in zip(pa, pb)) / (255.0 * len(pa))
    except Exception:   # noqa: BLE001 — só um aviso: nunca derruba a geração
        return None


def _size_like(ref: Any, w: int, h: int, mult: int) -> Tuple[int, int]:
    """Tamanho com a proporção da imagem de referência e o mesmo lado maior do tamanho pedido (editar não deve esticar a imagem)."""
    rw, rh = ref.size
    long = max(w, h)
    k = long / max(rw, rh)
    return max(256, int(rw * k) // mult * mult), max(256, int(rh * k) // mult * mult)


_SD_LOG: "collections.deque[Tuple[int, str]]" = collections.deque(maxlen=120)   # (nível, texto) das mensagens da stable-diffusion.cpp; níveis: 0 debug, 1 info, 2 aviso, 3 erro
_SD_CB: Any = None
_SD_LITE: set = set()   # modelos que só funcionaram sem as opções abaixo
_SD_LITE_KEYS = ("diffusion_flash_attn", "flash_attn", "offload_params_to_cpu")


def _unsupported_file() -> Path:
    from ..util import flow_home

    return flow_home() / "sd_unsupported.txt"


def _lib_unsupported(name: str) -> bool:
    """A biblioteca já recusou este modelo («get sd version from file failed»)? Então as próximas gerações vão direto ao sd-cli, sem carregar tudo para falhar de novo (e sem a mensagem de erro no terminal)."""
    try:
        return name in _unsupported_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return False


_NEWER_THAN_LIB = re.compile(r"flux[-_. ]?3", re.I)


def _lib_never_knows(name: str) -> bool:
    """Famílias novas que a biblioteca do PyPI (a 0.4.7, parada) nunca reconheceu (FLUX.3): vão direto ao sd-cli, sem nem tentar carregar na biblioteca. `OPENFLOW_SD_INPROC=1` força a biblioteca."""
    return bool(_NEWER_THAN_LIB.search(name)) and os.environ.get("OPENFLOW_SD_INPROC", "") in ("", "0")


_QUIET = re.compile(r"get sd version from file failed", re.I)


def _echo(level: int, line: str) -> None:
    """Mostra no terminal o log da biblioteca, menos a recusa de versão (o OpenFlow trata sozinho trocando para o sd-cli: o erro só assustava)."""
    if level >= 1 and line and not _QUIET.search(line):
        print(line, file=sys.stderr, flush=True)


def _mark_lib_unsupported(name: str) -> None:
    try:
        if not _lib_unsupported(name):
            with open(_unsupported_file(), "a", encoding="utf-8") as fh:
                fh.write(name + "\n")
    except OSError:
        pass


def _install_sd_log(sdc: Any) -> None:
    """Troca o callback de log da stable-diffusion-cpp-python por um que guarda as últimas mensagens (e continua mostrando-as no terminal)."""
    global _SD_CB
    try:
        import ctypes

        def cb(level, text, data):  # noqa: ANN001
            try:
                line = (text or b"").decode("utf-8", "replace").rstrip()
                _SD_LOG.append((int(level), line))
                _echo(int(level), line)
            except Exception:  # noqa: BLE001 — um callback nunca pode derrubar a geração
                pass

        _SD_CB = sdc.sd_log_callback(cb)   # guardado em variável global: o ctypes libera o callback se ninguém o referencia
        sdc.sd_set_log_callback(_SD_CB, ctypes.c_void_p(0))
    except Exception:  # noqa: BLE001 — versões sem esse recurso: segue sem capturar
        _SD_CB = None


def _sd_env(sdc: Any, short: bool = False) -> str:
    """Versão da stable-diffusion-cpp-python e backend (CPU/CUDA/Vulkan…) para a mensagem de erro; vazio se a biblioteca não informa."""
    bits = []
    try:
        ver = getattr(sdc, "__version__", "")
        if ver:
            bits.append(f"stable-diffusion-cpp-python {ver}")
        if short:
            return f" [{bits[0]}]" if bits else ""
        info = sdc.sd_get_system_info()
        info = info.decode("utf-8", "replace") if isinstance(info, bytes) else str(info)
        if info.strip():
            bits.append(info.strip().replace("\n", " ")[:160])
    except Exception:  # noqa: BLE001 — informação opcional
        pass
    return f" [{' · '.join(bits)}]" if bits else ""


def _sd_reason() -> str:
    """O motivo da falha, das últimas mensagens de aviso/erro da biblioteca («failed to allocate…», «unknown tensor…»); vazio se não há."""
    lines = [t for lvl, t in list(_SD_LOG) if lvl >= 2 and t][-4:] or [t for _, t in list(_SD_LOG) if t][-3:]   # sem aviso/erro: as últimas linhas mostram até onde a biblioteca chegou
    return " | ".join(l[:220] for l in lines)


def _tensor_hint(path: Path) -> str:
    """Para o erro: o tensor pelo qual a stable-diffusion.cpp reconhece a família do modelo e nomes de tensores do arquivo (os de fora dos blocos e os do primeiro bloco: mostram a arquitetura). Vazio se não há o que dizer."""
    fam = support.family_of(path.name)
    names = gguf_info.tensor_names(path) if path.suffix.lower() == ".gguf" else None
    if not fam or not fam.get("marker") or not names or any(fam["marker"] in n for n in names):
        return ""
    short = [n.replace("model.diffusion_model.", "") for n in names]
    top = [n for n in short if not re.search(r"\.\d+\.", n)][:4]
    block = [n for n in short if re.search(r"(^|\.)0\.", n)][:4]
    return f"O arquivo não tem o tensor «{fam['marker']}» do {fam['label']}; tem {len(names)} tensores (ex.: {', '.join(top + block)}). "


class _SDCrashed(ProviderError):
    """O processo da stable-diffusion.cpp fechou de repente (falha de segmentação, falta de memória…) enquanto gerava. `oom`: foi morto pelo sistema (SIGKILL, código -9/137), quase sempre falta de memória."""

    oom = False


class _SDProxy:
    """O modelo da stable-diffusion.cpp rodando em um processo À PARTE (`sd_worker`), com a mesma interface do objeto da biblioteca (`generate_image`).
    A biblioteca é C++ e pode derrubar o processo (falha de segmentação) ao recusar um modelo ou sem memória: assim cai só o processo dela, e o OpenFlow mostra o erro."""

    def __init__(self, proc: Any, params: List[str]):
        self.proc, self._params = proc, set(params)
        self._model = type("M", (), {"model": 1})()
        atexit.register(self.close)

    @staticmethod
    def _spawn() -> Any:
        import subprocess

        root = str(Path(__file__).resolve().parents[2])
        env = {**os.environ, "PYTHONPATH": root + os.pathsep + os.environ.get("PYTHONPATH", "")}
        return subprocess.Popen([sys.executable, "-m", "openflow.canvas.sd_worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)   # stderr herdado: o log da biblioteca aparece no terminal

    @staticmethod
    def _call(proc: Any, msg: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
        """Envia uma mensagem e lê até a resposta final, guardando as linhas de log no caminho. (resposta, None) ou (None, código de saída) se o processo caiu."""
        import json

        try:
            proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
            proc.stdin.flush()
        except (OSError, ValueError):
            return None, proc.wait()
        while True:
            line = proc.stdout.readline()
            if not line:
                return None, proc.wait()
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if "log" in data:
                _SD_LOG.append((int(data["log"][0]), str(data["log"][1])))
                continue
            return data, None

    @classmethod
    def start(cls, kw: Dict[str, Any]) -> Tuple[Optional["_SDProxy"], Optional[int]]:
        """Sobe o processo e carrega o modelo. (proxy, None) se carregou; (None, None) se a biblioteca recusou o modelo; (None, código) se o processo caiu."""
        proc = cls._spawn()
        reply, code = cls._call(proc, {"op": "load", "kw": kw})
        if reply is not None and reply.get("ok"):
            return cls(proc, reply.get("params") or []), None
        try:
            proc.kill()
            for pipe in (proc.stdin, proc.stdout):
                pipe.close()
        except OSError:
            pass
        return None, code

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc.wait(timeout=5)
            for pipe in (self.proc.stdin, self.proc.stdout):
                pipe.close()
        except Exception:  # noqa: BLE001 — encerrar nunca pode dar erro (também roda no atexit e no __del__)
            pass

    __del__ = close

    def generate_image(self, **kw: Any) -> List[Any]:
        import json
        import shutil
        import tempfile

        from PIL import Image  # type: ignore

        tmp = tempfile.mkdtemp(prefix="flow-sd-")
        try:
            def as_path(img: Any, name: str) -> str:
                f = os.path.join(tmp, name)
                img.save(f, format="PNG")
                return f

            for key in ("init_image", "mask_image", "control_image"):
                if kw.get(key) is not None and not isinstance(kw[key], str):
                    kw[key] = as_path(kw[key], key + ".png")
            if kw.get("ref_images"):
                kw["ref_images"] = [r if isinstance(r, str) else as_path(r, f"ref{i}.png") for i, r in enumerate(kw["ref_images"])]
            reply, code = self._call(self.proc, {"op": "gen", "kw": kw, "out": tmp})
            if reply is None:   # o processo caiu: esquece este modelo (a próxima geração sobe outro)
                with _LOCAL_LOCK:
                    for k in [k for k, v in _LOCAL_CACHE.items() if v is self]:
                        del _LOCAL_CACHE[k]
                crash = _SDCrashed(f"O processo da stable-diffusion.cpp fechou de repente durante a geração (código {code}"
                                   + (", falha de segmentação" if code in (-11, 139) else ", o sistema o encerrou por falta de memória (RAM)" if code in (-9, 137) else "") + "). O OpenFlow continua aberto; "
                                   "tente uma resolução menor, uma quantização menor (Q3/Q2) ou feche outros programas.")
                crash.oom = code in (-9, 137)
                raise crash
            if not reply.get("ok"):
                raise ValueError(reply.get("error") or "falha na geração")
            out = []
            for f in reply.get("files", []):
                with open(f, "rb") as fh:
                    out.append(Image.open(io.BytesIO(fh.read())).convert("RGB"))
            return out
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class _SDLoadError(ProviderError):
    """O modelo não carregou na stable-diffusion.cpp (a biblioteca não avisa: devolve um contexto nulo e o erro só aparece depois como «NULL pointer access»)."""


class _SDUnsupportedModel(_SDLoadError):
    """A stable-diffusion.cpp embutida na biblioteca instalada não reconhece o formato do modelo («get sd version from file failed»): tentar de novo não adianta."""


class GGUFMedia(MediaProvider):
    """Modelos GGUF de imagem e vídeo (FLUX, Stable Diffusion, Wan…) rodando dentro do OpenFlow pela stable-diffusion.cpp (`pip install "openflow[local]"`).

    Os arquivos são baixados em Configuração → Modelos locais (aba Imagem ou Vídeo, com a quantização à sua escolha) e ficam em
    `<dados>/models/image` e `<dados>/models/video`. O campo "extra" do nó aceita `{"load": {...}}` (argumentos do modelo; o texto "@model" vira o arquivo
    escolhido e nomes de arquivo viram caminhos na mesma pasta, ex.: {"diffusion_model_path": "@model", "vae_path": "ae.safetensors"}) e, fora de "load",
    argumentos da geração (steps, cfg_scale…).
    """

    id, label = "gguf_local", "GGUF local (stable-diffusion.cpp)"
    caps = ("image", "video")
    supports_refs = True   # imagem → imagem (init_image) ou, em modelos de edição (Qwen-Image-Edit, FLUX Kontext), ref_images
    refs_edit_only = True

    def max_refs(self, model: str = "") -> int:
        name = Path(self.model_for("image", model) or model or "").name
        if re.search(r"flux[-_. ]?3", name, re.I):
            return 10
        return 4 if _GGUF_MULTI_REF.search(name) else 1   # os demais modelos usam só uma imagem de partida

    def frames_edit_for(self, model: str = "") -> bool:
        name = Path(self.model_for("image", model) or model or "").name
        return bool(_GGUF_MULTI_REF.search(name) or re.search(r"flux[-_. ]?3", name, re.I))

    def refs_need_edit(self, model: str = "") -> bool:
        name = Path(self.model_for("image", model) or model or "").name
        return not (_GGUF_MULTI_REF.search(name) or re.search(r"flux[-_. ]?3", name, re.I))

    def _path(self, cap: str, model: str) -> Path:
        name = Path(self.model_for(cap, model)).name
        if not name:
            raise ProviderError(f"Escolha um modelo GGUF de {CAP_LABELS[cap]} em Configuração → Modelos locais ({'Imagem' if cap == 'image' else 'Vídeo'}).")
        path = Path(self.cfg.get("models_dir") or ".") / cap / name
        if not path.is_file():
            raise ProviderError(f"Modelo GGUF não encontrado: {path}. Baixe-o em Configuração → Modelos locais.")
        return path

    @staticmethod
    def _load_kwargs(path: Path, load: Dict[str, Any]) -> Dict[str, Any]:
        """Os parâmetros de carga com «@model» e os nomes de arquivo resolvidos para caminhos (a pasta do modelo)."""
        kw: Dict[str, Any] = {}
        for k, v in load.items():
            if isinstance(v, str) and v == "@model":
                kw[k] = str(path)
            elif isinstance(v, str) and k.endswith("_path") and (path.parent / Path(v).name).is_file():
                kw[k] = str(path.parent / Path(v).name)
            else:
                kw[k] = v
        if not kw:
            kw["model_path"] = str(path)
        return kw

    def _cancelled(self) -> bool:
        try:
            self.ctl.check()
            return False
        except Exception:  # noqa: BLE001  (o `check` do job levanta o cancelamento)
            return True

    def _cli_fallback(self, exc: Exception) -> bool:
        """A biblioteca não serve para este modelo (não o reconhece ou nem está instalada) e há um `sd-cli` pré-compilado para tentar?
        Se ainda não há `sd-cli`, o OpenFlow baixa o executável pronto sozinho (uns 30 MB; desligue com OPENFLOW_SD_CLI_AUTO=0) em vez de pedir um clique no nó."""
        if not (isinstance(exc, _SDUnsupportedModel) or "bibliotecas opcionais" in str(exc)):
            return False
        if (sdcli.find() is None or sdcli.installed_backend() not in ("", sdcli.backend())) and os.environ.get("OPENFLOW_SD_CLI_AUTO", "1") not in ("0", "no", "false"):   # sem sd-cli, ou o instalado é de outro tipo (CPU/GPU) que o escolhido nas configurações
            self.ctl.note("A stable-diffusion.cpp da biblioteca não reconhece este modelo: baixando o sd-cli pronto (a versão mais nova, sem compilar)…")
            try:
                sdcli.install(lambda done, total: self.ctl.note(f"Baixando o sd-cli ({sdcli.backend()})… {int(100 * done / total)}%") if total else None, self._cancelled, self.ctl.note)
                _media_unload()
            except ProviderError as err:
                if str(err) == "cancelado":
                    self.ctl.check()
                self.ctl.note(f"Não consegui baixar o sd-cli sozinho ({str(err)[:160]}); use o botão do nó.")
        return sdcli.find() is not None

    def _engine(self, cap: str, path: Path, load: Dict[str, Any]) -> Any:
        (sdc,) = _local_import("stable_diffusion_cpp", extra="local")
        _install_sd_log(sdc)   # guarda as mensagens da stable-diffusion.cpp: quando a geração falha com «NULL pointer access», o motivo de verdade está nelas
        kw = self._load_kwargs(path, load)
        isolated = isinstance(getattr(sdc, "__file__", None), str) and os.environ.get("OPENFLOW_SD_INPROC", "") in ("", "0")   # biblioteca de verdade: roda em processo à parte (ver `_SDProxy`)

        def build() -> Any:
            _SD_LOG.clear()   # o motivo de uma falha de carga é registrado AQUI, durante a criação do modelo (antes, era apagado antes de gerar)
            crashed: Optional[int] = None
            if isolated:
                sd, crashed = _SDProxy.start(kw)
                ok = crashed is None and sd is not None
            else:
                sd = sdc.StableDiffusion(**kw)
                ok = bool(getattr(getattr(sd, "_model", None), "model", 1))   # a carga que falha devolve um ponteiro NULO (não None): a biblioteca segue com um contexto vazio
            if not ok:
                raise self._load_error(path, kw, sdc, crashed)
            return sd

        return _local_load("gguf-" + cap, f"{path}|{sorted(kw.items())}", build)   # um modelo que não carregou nunca fica em cache

    def _load_error(self, path: Path, kw: Dict[str, Any], sdc: Any, crashed: Optional[int]) -> ProviderError:
        """O erro de um modelo que não carregou: não reconhecido (biblioteca antiga), processo que caiu (falha de segmentação) ou outro motivo do log."""
        hint = _tensor_hint(path)
        if any("get sd version" in t for _, t in list(_SD_LOG)):   # a versão do modelo não foi reconhecida: a stable-diffusion.cpp desta biblioteca é antiga demais para ele
            try:   # avisa o `flow libs` (instalação e atualização), que então compila a biblioteca mais nova do GitHub
                from ..util import flow_home

                (flow_home() / "sd_needs_newer").write_text(path.name, encoding="utf-8")
                _mark_lib_unsupported(path.name)
            except OSError:
                pass
            return _SDUnsupportedModel(
                f"A stable-diffusion.cpp instalada não reconhece o modelo {path.name} («get sd version from file failed»)"
                + (f" e fechou (código {crashed}) — o OpenFlow a roda em outro processo e continua aberto" if crashed else "") + ". " + hint
                + "Provavelmente é de outra arquitetura ou mais novo que a biblioteca (a do PyPI é a 0.4.7, a mais nova publicada). "
                "Use o botão «Baixar o executável pronto» (a stable-diffusion.cpp mais nova, sem compilar), ou atualize a biblioteca (compila a versão do GitHub: precisa de git, cmake e compilador C++), ou use outro arquivo/quantização. [[flow-sd-cli]] [[flow-sd-update]]" + _sd_env(sdc, short=True))
        why = _sd_reason()
        files = ", ".join(Path(v).name for k, v in kw.items() if k.endswith("_path") and isinstance(v, str))
        return _SDLoadError(
            f"O modelo {path.name} não carregou na stable-diffusion.cpp"
            + (f" (o processo dela fechou de repente: código {crashed})" if crashed else "") + ". "
            + (f"Motivo informado pela biblioteca: {why}. " if why else "A biblioteca não registrou nenhum motivo. ")
            + ("Parece falta de memória: o modelo e o codificador de texto juntos não cabem na RAM livre; feche outros programas ou use uma quantização menor (Q3/Q2). " if re.search(r"alloc|out of memory|oom|memory", why, re.I) or crashed in (-9, 137) else "")
            + f"Arquivos carregados: {files}. " + hint + _sd_env(sdc))

    @staticmethod
    def _need_companions(path: Path, load: Dict[str, Any]) -> None:
        """Modelo de família conhecida sem os arquivos de apoio (VAE, codificador de texto): o sd-cli receberia só `-m` e falharia com «get sd version from file failed». Avisa o que falta e oferece baixar."""
        info = support.missing(path.parent, path.name)
        if info["missing"] and not any(k != "model_path" and k.endswith("_path") and v for k, v in load.items() if v != "@model"):
            raise ProviderError(f"Faltam os arquivos de apoio do {info['label']}: {', '.join(m['label'] for m in info['missing'])} (≈ {info['approx_gb']} GB); sem eles o modelo não carrega. "
                                f"Use o botão «Baixar os arquivos de apoio» no nó, ou ponha-os na pasta {path.parent}. [[flow-support:{path.name}]]")

    def _image_cli(self, path: Path, load: Dict[str, Any], extra: Dict[str, Any], prompt: str, size: str, count: int, seed: int, negative: str, refs: Sequence[Ref]) -> List[Media]:
        """A imagem pelo `sd-cli` pré-compilado (a biblioteca Python não reconhece o modelo): os mesmos arquivos de apoio e parâmetros; referências por `-r` (modelos multi-referência) ou imagem inicial `-i`."""
        cli = sdcli.find()
        assert cli is not None
        self._need_companions(path, load)
        kw = self._load_kwargs(path, load)
        w, h = parse_wh(size)
        k = min(1.0, float(_max_side()) / max(w, h))
        w, h = max(256, int(w * k) // 16 * 16), max(256, int(h * k) // 16 * 16)
        pil = _pil_refs(refs, self.max_refs("")) if refs else []
        if refs and not pil:
            raise ProviderError("Não consegui ler as imagens de referência ligadas ao nó (formato não suportado).")
        ref_png: List[bytes] = []
        for im in pil:
            b = io.BytesIO()
            im.save(b, format="PNG")
            ref_png.append(b.getvalue())
        multi = bool(_GGUF_MULTI_REF.search(path.name) or re.search(r"flux[-_. ]?3", path.name, re.I))
        if len(pil) == 1 and self.edit_mode:
            w, h = _size_like(pil[0], w, h, 16)
        run_p = {k2: v for k2, v in extra.items() if k2 not in ("load",)}
        out: List[Media] = []
        self.ctl.note(f"A stable-diffusion-cpp-python não reconhece este modelo: gerando pelo sd-cli ({cli.name}).")
        for i in range(max(1, count)):
            self.ctl.check()
            try:
                data, warns = sdcli.generate_image(cli, kw, run_p, prompt=prompt, width=w, height=h, seed=int(seed + i) if seed else int(time.time() * 1000) % (2 ** 31) + i, negative=negative,
                                                    refs=ref_png if multi else [], init=None if multi or not ref_png else ref_png[0], cancelled=self._cancelled, note=self.ctl.note)
            except ProviderError as exc:
                if str(exc) == "cancelado":
                    self.ctl.check()   # o trabalho foi cancelado: levanta o cancelamento de verdade
                raise
            if warns and i == 0:
                self.ctl.note("Opções sem equivalente no sd-cli (ignoradas): " + ", ".join(sorted(set(warns))))
            out.append(Media(data, "image/png"))
        return out

    def _auto_load(self, path: Path) -> Dict[str, Any]:
        """Para um GGUF de família conhecida (Qwen-Image, FLUX…, ver `support.FAMILIES`), acha os arquivos de apoio na mesma pasta e monta o carregamento. {} se não é uma família conhecida
        ou se falta algum apoio (carregar só o arquivo do modelo faz a biblioteca falhar com «NULL pointer access»; o erro então oferece baixar o que falta)."""
        fam = support.family_of(path.name)
        if not fam:
            return {}
        found = support.find_companions(path.parent, path, fam)
        if any(v is None for v in found.values()):
            return {}
        return {"load": {"diffusion_model_path": "@model", **found, **fam.get("options", {})}, "run": support.run_for(fam, path.name)}   # `options`: memória e atenção como na documentação da stable-diffusion.cpp

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        from .. import preinstalled

        path = self._path("image", model)
        base = preinstalled.defaults_for("image", path.name)  # modelos pré-instalados já vêm com o jeito certo de carregar; o "extra" do nó sobrescreve
        if not base and not (extra or {}).get("load"):
            base = self._auto_load(path)   # famílias conhecidas (Qwen-Image, FLUX): acha o VAE e o codificador de texto ao lado do modelo
        extra = {**base.get("run", {}), **(extra or {})}
        load = {**base.get("load", {}), **(extra.pop("load", None) or {})}
        if path.name in _SD_LITE:   # este modelo já falhou com flash attention/offload nesta máquina: começa sem eles (não recarrega duas vezes a cada imagem)
            load = {k: v for k, v in load.items() if k not in _SD_LITE_KEYS}
        if (_lib_unsupported(path.name) or _lib_never_knows(path.name)) and self._cli_fallback(_SDUnsupportedModel(path.name)):   # já se sabe que a biblioteca não o reconhece
            return self._image_cli(path, load, extra, prompt, size, count, seed, negative, refs)
        try:
            sd = self._engine("image", path, load)
        except ProviderError as exc:
            if self._cli_fallback(exc):   # a biblioteca não reconhece o modelo (ou não está instalada): o sd-cli pré-compilado faz a imagem, com os mesmos arquivos e parâmetros
                return self._image_cli(path, load, extra, prompt, size, count, seed, negative, refs)
            if isinstance(exc, _SDUnsupportedModel) or not isinstance(exc, _SDLoadError):
                raise
            lite = {k: v for k, v in load.items() if k not in _SD_LITE_KEYS}
            if len(lite) == len(load):
                raise
            self.ctl.note("O modelo não carregou: tentando de novo sem flash attention e sem descarregar pesos para a RAM…")
            sd = self._engine("image", path, lite)   # se falhar de novo, o erro desta segunda tentativa vale
            load = lite
            _SD_LITE.add(path.name)
        sdc_mod = sys.modules.get("stable_diffusion_cpp")
        used = ", ".join(Path(v).name for k, v in load.items() if k.endswith("_path") and isinstance(v, str) and v != "@model")   # os arquivos de apoio de fato carregados (para o erro)
        w, h = parse_wh(size)
        k = min(1.0, float(_max_side()) / max(w, h))   # o lado maior vai até MAX_SIDE (padrão 2048) mantendo a proporção (antes cada lado era cortado sozinho: 1280×720 virava 1024×720)
        w, h = max(256, int(w * k) // 16 * 16), max(256, int(h * k) // 16 * 16)   # múltiplos de 16: Qwen-Image/FLUX/Z-Image falham com tamanhos que não são
        pil = _pil_refs(refs, self.max_refs(model)) if refs else []
        if refs and not pil:
            raise ProviderError("Não consegui ler as imagens de referência ligadas ao nó (formato não suportado).")
        ref_kw: Dict[str, Any] = {}
        if pil:
            import inspect

            gen_fn = getattr(sd, "generate_image", None) or getattr(sd, "txt2img", None)
            try:
                params = set(getattr(sd, "_params", None) or (inspect.signature(gen_fn).parameters if gen_fn else ()))   # no processo à parte, os parâmetros vêm da carga
            except (TypeError, ValueError):
                params = set()
            if len(pil) == 1 and self.edit_mode:   # só no modo Editar com uma imagem: mantém a proporção dela; ao Gerar (ou com várias referências) vale o tamanho pedido (uma thumb não herda a forma da foto)
                w, h = _size_like(pil[0], w, h, 16)
            if _GGUF_MULTI_REF.search(path.name) and "ref_images" in params:
                ref_kw["ref_images"] = pil                       # modelos de edição: as imagens guiam a edição
            elif "init_image" in params:
                ref_kw["init_image"] = pil[0].resize((w, h))    # demais: imagem → imagem
                ref_kw.setdefault("strength", 0.75)
            else:
                raise ProviderError("A versão instalada da stable-diffusion-cpp-python não aceita imagens de entrada (init_image/ref_images). Atualize-a (flow libs) ou use um modelo de nuvem para editar.")
        out = []
        for i in range(max(1, count)):
            self.ctl.check()
            self.ctl.note("Gerando imagem com o modelo GGUF…")
            kw = {"prompt": prompt, "width": w, "height": h, "seed": int(seed + i) if seed else int(time.time() * 1000) % (2 ** 31) + i, **ref_kw, **extra}
            if negative:
                kw.setdefault("negative_prompt", negative)
            gen = getattr(sd, "generate_image", None) or getattr(sd, "txt2img", None)   # a stable-diffusion-cpp-python nova chama `generate_image`; a antiga, `txt2img`
            if gen is None:
                raise ProviderError("A versão instalada da stable-diffusion-cpp-python não tem um gerador de imagem conhecido (generate_image/txt2img). Atualize-a (flow libs).")
            imgs, scale = None, 1.0
            while imgs is None:
                _install_sd_log(_local_import("stable_diffusion_cpp", extra="local")[0])   # o construtor da biblioteca troca o callback de log: reinstala o nosso antes de cada geração
                _SD_LOG.clear()
                try:
                    imgs = gen(**{**kw, "width": max(256, int(w * scale) // 16 * 16), "height": max(256, int(h * scale) // 16 * 16)})
                except _SDCrashed as exc:   # o sistema matou o processo por falta de memória: o modelo é recarregado e a imagem sai de novo em resolução menor (a memória das ativações cai com a área)
                    if not exc.oom or scale <= 0.4 or max(w, h) * scale <= 384:
                        raise
                    scale = 0.5625 if scale > 0.6 else 0.375
                    self.ctl.note(f"Faltou memória (o sistema encerrou a stable-diffusion.cpp): tentando de novo em {int(w * scale) // 16 * 16}×{int(h * scale) // 16 * 16}…")
                    sd = self._engine("image", path, load)
                    gen = getattr(sd, "generate_image", None) or getattr(sd, "txt2img", None)
                    continue
                except (ValueError, RuntimeError, OSError) as exc:
                    if not ("null pointer" in str(exc).lower() or "nullptr" in str(exc).lower()):
                        raise
                    if scale > 0.6 and max(w, h) > 640:   # quase sempre falta de memória: tenta uma vez mais com 60% do tamanho
                        scale = 0.5625
                        self.ctl.note("Sem memória para este tamanho: tentando de novo com resolução menor…")
                        continue
                    lite = {k: v for k, v in load.items() if k not in _SD_LITE_KEYS}
                    if len(lite) < len(load):
                        _SD_LITE.add(path.name)   # última tentativa: sem as opções de atenção/memória (alguns backends — CPU, Vulkan, placas antigas — não as suportam e a geração volta nula)
                        load = lite
                        self.ctl.note("Tentando de novo sem flash attention e sem descarregar pesos para a RAM…")
                        sd = self._engine("image", path, load)
                        gen = getattr(sd, "generate_image", None) or getattr(sd, "txt2img", None)
                        scale = 1.0
                        continue
                    info = support.missing(path.parent, path.name)
                    fix = (f" Faltam os arquivos de apoio do {info['label']}: {', '.join(m['label'] for m in info['missing'])} (≈ {info['approx_gb']} GB). Use o botão «Baixar os arquivos de apoio» no nó, "
                           f"ou ponha-os na pasta {path.parent}. [[flow-support:{path.name}]]") if info["missing"] else ""
                    why = _sd_reason() or ("a biblioteca não registrou nenhum motivo — veja o terminal onde o OpenFlow roda" + (f"; arquivos de apoio carregados: {used}" if used else "; nenhum arquivo de apoio foi carregado") + _sd_env(sdc_mod))
                    mem = (" Parece falta de memória: feche outros programas, use uma quantização menor (Q3/Q2) ou uma resolução menor." if re.search(r"alloc|out of memory|oom", why, re.I) else "")
                    raise ProviderError(f"A geração com {path.name} falhou na stable-diffusion.cpp («{exc}»)." + (f" Motivo informado pela biblioteca: {why}." if why else "")
                                        + mem + " Modelos GGUF só de difusão (Qwen-Image, FLUX, Z-Image…) precisam do VAE e do codificador de texto na mesma pasta, e a biblioteca precisa ser recente (flow libs)." + fix) from None
            for img in (imgs if isinstance(imgs, (list, tuple)) else [imgs])[:1]:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                out.append(Media(buf.getvalue(), "image/png"))
        return out

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        import inspect

        extra = dict(extra or {})
        path = self._path("video", model)
        fam = support.family_of(path.name)
        fam = fam if fam and fam.get("cap") == "video" else None
        base: Dict[str, Any] = {}
        if fam and not extra.get("load"):   # família conhecida (Wan2.2 TI2V…, ver `support.FAMILIES`): acha o VAE e o codificador de texto ao lado do modelo
            found = support.find_companions(path.parent, path, fam)
            if any(v is None for v in found.values()):
                info = support.missing(path.parent, path.name)
                raise ProviderError(f"Faltam os arquivos de apoio do {info['label']}: {', '.join(m['label'] for m in info['missing'])} (≈ {info['approx_gb']} GB). Use o botão «Baixar os arquivos de apoio» no nó, "
                                    f"ou ponha-os na pasta {path.parent}. [[flow-support:{path.name}]]")
            base = {"load": {"diffusion_model_path": "@model", **found, **fam.get("options", {})}, "run": support.run_for(fam, path.name)}
        extra = {**base.get("run", {}), **extra}
        vload = {**base.get("load", {}), **(extra.pop("load", None) or {})}
        try:
            sd = self._engine("video", path, vload)
        except ProviderError as exc:
            if self._cli_fallback(exc):   # a biblioteca não reconhece o modelo: o sd-cli pré-compilado gera os quadros
                return self._video_cli(path, vload, extra, fam, prompt, duration, aspect, image, seed, long_side)
            raise
        fn = getattr(sd, "txt2vid", None) or getattr(sd, "generate_video", None)
        if fn is None:
            raise ProviderError("A versão instalada da stable-diffusion-cpp-python não gera vídeo. Atualize-a (flow libs) ou use outro provedor de vídeo.")
        try:
            params = set(getattr(sd, "_params", None) or inspect.signature(fn).parameters)   # no processo à parte, os parâmetros vêm da carga
        except (TypeError, ValueError):
            params = set()
        vinfo = (fam or {}).get("video") or {}
        image = self._start_image(vinfo, image)
        fps = int(vinfo.get("fps") or 16)
        kw: Dict[str, Any] = {}
        if vinfo:   # tamanho e número de quadros que o modelo aceita (Wan2.2 TI2V 5B: só 720p; quadros = 4k+1)
            w, h = vinfo["sizes"]["portrait" if str(aspect) in ("9:16", "3:4") else "landscape"]
            frames_n = max(5, min(int(vinfo.get("max_frames") or 121), 4 * round((max(1, int(duration)) * fps - 1) / 4) + 1))
            kw[next((k for k in ("video_frames", "num_frames", "frames") if k in params), "video_frames")] = frames_n
        else:
            w, h = size_of_aspect(aspect, long_side or 640)
            w, h = w // 8 * 8, h // 8 * 8
        if image is not None and "init_image" in params:   # imagem inicial (modelos TI2V aceitam texto + imagem)
            pil = _pil_refs([image])
            if pil:
                kw["init_image"] = pil[0].resize((w, h))
        kw = {"prompt": prompt, "width": w, "height": h, "seed": int(seed) if seed else -1, **kw, **extra}
        if params:   # versões da biblioteca diferem nos parâmetros: o que ela não conhece é descartado (com aviso) em vez de derrubar a geração
            dropped = [k for k in kw if k not in params]
            if dropped:
                self.ctl.note("Esta versão da stable-diffusion-cpp-python não aceita: " + ", ".join(dropped) + " (ignorados).")
                kw = {k: v for k, v in kw.items() if k in params}
        self.ctl.note("Gerando vídeo com o modelo GGUF (pode demorar)…")
        frames = fn(**kw)
        return _frames_to_mp4(frames, fps)

    def _start_image(self, vinfo: Dict[str, Any], image: Optional[Ref]) -> Optional[Ref]:
        """A imagem inicial do vídeo conforme o modelo: imagem → vídeo (Wan I2V) exige uma; texto → vídeo (Wan T2V A14B) a ignora, com aviso; os demais (TI2V…) aceitam as duas coisas."""
        mode = vinfo.get("image")
        if mode == "required" and image is None:
            raise ProviderError("Este modelo faz imagem → vídeo: ligue uma imagem à entrada «Imagem inicial» do nó Vídeo (ou escolha um modelo texto → vídeo, como o Wan2.2 T2V A14B ou o TI2V 5B).")
        if mode == "ignored" and image is not None:
            self.ctl.note("Este modelo é texto → vídeo: a imagem inicial foi ignorada (use um modelo I2V ou TI2V para animar uma imagem).")
            return None
        return image

    def _video_cli(self, path: Path, load: Dict[str, Any], extra: Dict[str, Any], fam: Optional[Dict[str, Any]], prompt: str, duration: int, aspect: str, image: Optional[Ref], seed: int, long_side: int) -> Media:
        """O vídeo pelo `sd-cli` (`-M vid_gen`): os quadros saem numerados e o OpenFlow os monta em MP4 pelo ffmpeg."""
        cli = sdcli.find()
        assert cli is not None
        self._need_companions(path, load)
        vinfo = (fam or {}).get("video") or {}
        image = self._start_image(vinfo, image)
        fps = int(vinfo.get("fps") or 16)
        run_p = {k: v for k, v in extra.items() if k != "load"}
        if vinfo:
            w, h = vinfo["sizes"]["portrait" if str(aspect) in ("9:16", "3:4") else "landscape"]
            run_p["video_frames"] = max(5, min(int(vinfo.get("max_frames") or 121), 4 * round((max(1, int(duration)) * fps - 1) / 4) + 1))
        else:
            w, h = size_of_aspect(aspect, long_side or 640)
            w, h = w // 8 * 8, h // 8 * 8
        init = None
        if image is not None:
            pil = _pil_refs([image])
            if pil:
                b = io.BytesIO()
                pil[0].resize((w, h)).save(b, format="PNG")
                init = b.getvalue()
        self.ctl.note(f"A stable-diffusion-cpp-python não reconhece este modelo: gerando o vídeo pelo sd-cli ({cli.name}). Pode demorar bastante.")
        try:
            frames, warns = sdcli.generate_video(cli, self._load_kwargs(path, load), run_p, prompt=prompt, width=w, height=h, seed=int(seed) if seed else -1, fps=fps, init=init, cancelled=self._cancelled, note=self.ctl.note)
        except ProviderError as exc:
            if str(exc) == "cancelado":
                self.ctl.check()
            raise
        if warns:
            self.ctl.note("Opções sem equivalente no sd-cli (ignoradas): " + ", ".join(sorted(set(warns))))
        from PIL import Image  # type: ignore

        return _frames_to_mp4([Image.open(io.BytesIO(f)).convert("RGB") for f in frames], fps)

    def test(self) -> str:
        _local_import("stable_diffusion_cpp", extra="local")
        have = {k: len(list((Path(self.cfg.get("models_dir") or ".") / k).glob("*.gguf"))) for k in ("image", "video")}
        return f"stable-diffusion-cpp-python ok · modelos GGUF: {have['image']} de imagem, {have['video']} de vídeo"


class VoiceSettingsMedia(MediaProvider):
    """Usa o servidor de voz já configurado em Configuração → Voz (OpenAI-compatível: nuvem ou local)."""

    id, label = "voice_settings", "Voz da Configuração"
    caps = ("voice", "stt")

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        from .. import voice as vc

        settings = self.cfg.get("settings") or {}
        if not vc.tts_enabled(settings):
            raise ProviderError("Configure um servidor de síntese de voz em Configuração → Voz (modo servidor).")
        data, mime = vc.synthesize(settings, text, voice)
        return expect_media(data, mime, "audio", self.label)

    def transcribe(self, data, filename, mime, *, language="", model=""):
        from .. import voice as vc

        settings = self.cfg.get("settings") or {}
        if not vc.stt_enabled(settings):
            raise ProviderError("Configure um servidor de transcrição em Configuração → Voz (modo servidor).")
        return vc.transcribe_bytes(settings, data, filename or "audio.mp3", mime or "audio/mpeg", language).strip()

    def test(self) -> str:
        from .. import voice as vc

        s = self.cfg.get("settings") or {}
        return f"síntese {'ativa' if vc.tts_enabled(s) else 'desligada'} · transcrição {'ativa' if vc.stt_enabled(s) else 'desligada'}"


# --------------------------------------------------------------------------- catálogo

MEDIA_PRESETS: Dict[str, Dict[str, Any]] = {
    "demo": {
        "label": "Demo (offline, sem IA)", "kind": "demo", "caps": ["image", "video", "sound", "voice"], "local": True, "needs_key": False,
        "hint": "Gera paisagens abstratas, sons sintetizados e vídeos simples sem chave e sem internet — ótimo para testar fluxos inteiros (vídeo precisa do ffmpeg).",
    },
    "openai": {
        "label": "OpenAI", "kind": "openai", "caps": ["image", "video", "voice", "stt"], "base_url": "https://api.openai.com/v1", "needs_key": True,
        "docs": "https://platform.openai.com/api-keys", "models": {"image": "gpt-image-1", "video": "sora-2", "voice": "tts-1", "stt": "whisper-1"},
        "suggest": {"image": ["gpt-image-1", "dall-e-3"], "video": ["sora-2", "sora-2-pro"], "voice": ["tts-1", "tts-1-hd", "gpt-4o-mini-tts"], "stt": ["whisper-1", "gpt-4o-transcribe"]},
        "hint": "Imagens (com edição e referências), vozes, transcrição e vídeo (Sora, experimental).",
    },
    "xai": {
        "label": "xAI (Grok Imagine)", "kind": "openai", "caps": ["image"], "base_url": "https://api.x.ai/v1", "needs_key": True, "no_size": True,
        "docs": "https://console.x.ai", "models": {"image": "grok-2-image"}, "suggest": {"image": ["grok-2-image"]},
    },
    "elevenlabs": {
        "label": "ElevenLabs", "kind": "elevenlabs", "caps": ["voice", "sound", "stt"], "base_url": "https://api.elevenlabs.io/v1", "needs_key": True,
        "docs": "https://elevenlabs.io/app/settings/api-keys",
        "models": {"voice": "eleven_multilingual_v2", "stt": "scribe_v1"}, "suggest": {"voice": ["eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_v3"], "stt": ["scribe_v1"]},
        "hint": 'Vozes realistas (no nó Voz use o nome ou o ID da voz), efeitos sonoros e música (experimental).',
    },
    "openrouter": {
        "label": "OpenRouter", "kind": "openrouter", "caps": ["image", "video", "voice", "stt"], "base_url": "https://openrouter.ai/api/v1", "needs_key": True,
        "docs": "https://openrouter.ai/keys", "models": {"image": "google/gemini-2.5-flash-image", "video": "google/veo-3.1", "voice": "openai/gpt-4o-mini-tts", "stt": "google/gemini-2.5-flash"},
        "suggest": {"image": ["google/gemini-2.5-flash-image", "openai/gpt-image-1", "openai/gpt-image-2", "black-forest-labs/flux.2-pro", "bytedance-seed/seedream-4.5"], "video": ["google/veo-3.1", "alibaba/wan-2.7", "bytedance/seedance-2.0", "minimax/hailuo-3"], "voice": ["openai/gpt-4o-mini-tts", "openai/tts-1"],
                    "stt": ["google/gemini-2.5-flash", "google/gemini-2.5-flash-lite", "openai/gpt-4o-audio-preview"]},
        "hint": "Imagens (geração e edição com até 4 referências, pela rota própria de imagens — OpenAI gpt-image, xAI, FLUX, Seedream…), vídeos (assíncronos; duração, proporção e resolução seguem o catálogo de cada modelo), vozes e transcrição com a mesma chave (ou login) do OpenRouter, a mesma do chat. Use «Carregar modelos» para ver os modelos atuais de cada tipo (as modalidades vêm do próprio OpenRouter).",
    },
    "google": {
        "label": "Google (Gemini / Veo)", "kind": "google", "caps": ["image", "video"], "base_url": "https://generativelanguage.googleapis.com/v1beta", "needs_key": True,
        "docs": "https://aistudio.google.com/apikey", "models": {"image": "gemini-2.5-flash-image", "video": "veo-3.0-fast-generate-001"},
        "suggest": {"image": ["gemini-2.5-flash-image", "imagen-4.0-generate-001"], "video": ["veo-3.0-fast-generate-001", "veo-3.0-generate-001"]},
        "hint": "A mesma chave do Gemini. Vídeo (Veo) é experimental e pode exigir plano pago.",
    },
    "stability": {
        "label": "Stability AI", "kind": "stability", "caps": ["image"], "base_url": "https://api.stability.ai", "needs_key": True,
        "docs": "https://platform.stability.ai/account/keys", "models": {"image": "core"}, "suggest": {"image": ["core", "ultra", "sd3.5-large", "sd3.5-large-turbo", "sd3.5-medium"]},
    },
    "replicate": {
        "label": "Replicate (milhares de modelos)", "kind": "replicate", "caps": ["image", "video", "sound", "voice"], "base_url": "https://api.replicate.com/v1", "needs_key": True,
        "docs": "https://replicate.com/account/api-tokens",
        "models": {"image": "black-forest-labs/flux-schnell", "video": "minimax/video-01", "sound": "meta/musicgen", "voice": "jaaari/kokoro-82m"},
        "suggest": {"image": ["black-forest-labs/flux-schnell", "black-forest-labs/flux-dev", "stability-ai/sdxl"], "video": ["minimax/video-01", "kwaivgi/kling-v2.1", "wan-video/wan-2.2-t2v-fast"],
                    "sound": ["meta/musicgen"], "voice": ["jaaari/kokoro-82m"]},
        "hint": "Informe o modelo como dono/nome. O OpenFlow lê o esquema do modelo e só envia os parâmetros que ele aceita.",
    },
    "huggingface": {
        "label": "Hugging Face (Inference)", "kind": "huggingface", "caps": ["image", "sound", "voice", "stt"], "base_url": "https://router.huggingface.co/hf-inference/models", "needs_key": True,
        "docs": "https://huggingface.co/settings/tokens",
        "models": {"image": "black-forest-labs/FLUX.1-schnell", "sound": "facebook/musicgen-small", "voice": "facebook/mms-tts-eng", "stt": "openai/whisper-large-v3"},
        "suggest": {"image": ["black-forest-labs/flux-3-image-klein", "black-forest-labs/FLUX.2-klein-4B", "black-forest-labs/FLUX.1-schnell", "stabilityai/stable-diffusion-xl-base-1.0"], "voice": ["facebook/mms-tts-eng", "facebook/mms-tts-por", "suno/bark-small"],
                    "sound": ["facebook/musicgen-small"], "stt": ["openai/whisper-large-v3", "openai/whisper-small"]},
        "hint": "Usa a mesma chave do Hugging Face (Configuração → Provedores). A disponibilidade de cada modelo depende do serviço.",
    },
    "a1111": {
        "label": "Stable Diffusion WebUI (local)", "kind": "a1111", "caps": ["image"], "base_url": "http://127.0.0.1:7860", "needs_key": False, "local": True,
        "docs": "https://github.com/AUTOMATIC1111/stable-diffusion-webui", "hint": "AUTOMATIC1111 ou Forge, iniciado com a opção --api. Gera no seu computador.",
    },
    "local_hf": {
        "label": "Hugging Face local (embutido)", "kind": "local_hf", "caps": ["image", "video", "sound", "voice", "stt"], "needs_key": False, "local": True,
        "models": {"image": "stabilityai/sd-turbo", "video": "Lightricks/LTX-Video", "sound": "facebook/musicgen-small", "voice": "suno/bark-small", "stt": "openai/whisper-small"},
        "suggest": {"image": ["stabilityai/sd-turbo", "stabilityai/sdxl-turbo", "black-forest-labs/FLUX.1-schnell", "unsloth/Z-Image-Turbo", "unsloth/FLUX.2-klein-4B", "unsloth/FLUX.1-schnell"], "video": ["Lightricks/LTX-Video"],
                    "sound": ["facebook/musicgen-small"], "voice": ["suno/bark-small", "facebook/mms-tts-por", "unsloth/orpheus-3b-0.1-ft", "unsloth/csm-1b"],
                    "stt": ["openai/whisper-small", "openai/whisper-large-v3-turbo", "unsloth/whisper-large-v3-turbo", "unsloth/whisper-small", "unsloth/whisper-base"]},
        "hint": 'Roda modelos do Hugging Face dentro do OpenFlow. Requer:  pip install "openflow[media]". Antes de usar, escolha a precisão (quantização) e baixe cada modelo aqui mesmo — nada é baixado em silêncio. Vídeo exige GPU.',
    },
    "gguf_local": {
        "label": "GGUF local (stable-diffusion.cpp)", "kind": "gguf_local", "caps": ["image", "video"], "needs_key": False, "local": True,
        "hint": 'Modelos GGUF de imagem e vídeo (FLUX, Stable Diffusion, Wan…) quantizados, rodando no OpenFlow. Requer:  pip install "openflow[local]". Baixe-os em Configuração → Modelos locais (abas Imagem e Vídeo) escolhendo a quantização.',
    },
    "voice_settings": {
        "label": "Voz da Configuração", "kind": "voice_settings", "caps": ["voice", "stt"], "needs_key": False, "local": True,
        "hint": "Usa o servidor de voz já configurado em Configuração → Voz (Whisper, Kokoro, OpenAI…).",
    },
    "custom": {
        "label": "Servidor compatível com OpenAI (personalizado)", "kind": "openai", "caps": ["image", "voice", "stt"], "base_url": "", "needs_key": False, "local": True,
        "hint": "Qualquer servidor com /images/generations, /audio/speech ou /audio/transcriptions (LocalAI, Kokoro-FastAPI, faster-whisper-server, Together…).",
    },
}

_KINDS = {"demo": DemoMedia, "openrouter": OpenRouterMedia, "openai": OpenAIMedia, "elevenlabs": ElevenLabsMedia, "google": GoogleMedia, "stability": StabilityMedia, "replicate": ReplicateMedia,
          "huggingface": HFInferenceMedia, "a1111": A1111Media, "local_hf": LocalHFMedia, "gguf_local": GGUFMedia, "voice_settings": VoiceSettingsMedia}

from . import media_cloud as _cloud   # noqa: E402  (v0.8: Qwen, Krea e Bria; o módulo usa as classes acima)

_KINDS.update(_cloud.KINDS)
_at = list(MEDIA_PRESETS)
MEDIA_PRESETS.update({k: v for k, v in _cloud.PRESETS.items()})
_order = _at[:_at.index("replicate")] + list(_cloud.PRESETS) + _at[_at.index("replicate"):]   # as nuvens novas ficam junto das outras, antes das locais e do «personalizado»
MEDIA_PRESETS = {k: MEDIA_PRESETS[k] for k in _order}


def media_config(settings: Dict[str, Any], pid: str) -> Dict[str, Any]:
    preset = MEDIA_PRESETS.get(pid)
    if not preset:
        raise ProviderError(f"Provedor de mídia desconhecido: {pid}")
    cfg = {k: v for k, v in preset.items() if k not in ("models", "suggest")}
    media = settings.get("media") or {}
    url = ((media.get("urls") or {}).get(pid) or "").strip()
    if url:
        cfg["base_url"] = url
    key = ((settings.get("providers") or {}).get(pid) or {}).get("api_key", "")
    if pid == "huggingface" and not key:
        key = (settings.get("hf") or {}).get("token", "")
    cfg["api_key"] = key
    models = dict(preset.get("models") or {})
    models.update({k: v for k, v in ((media.get("models") or {}).get(pid) or {}).items() if v})
    cfg["models"] = models
    cfg["id"] = pid
    if pid == "voice_settings":
        cfg["settings"] = settings
    return cfg


def build_media(settings: Dict[str, Any], pid: str, ctl: Optional[Ctl] = None, models_dir: Optional[Path] = None) -> MediaProvider:
    cfg = media_config(settings, pid)
    if models_dir:
        cfg["models_dir"] = str(models_dir)
    return _KINDS.get(cfg["kind"], OpenAIMedia)(cfg, ctl)


def pick_provider(settings: Dict[str, Any], cap: str, node_pid: str = "") -> str:
    """Provedor de um nó: o escolhido nele, senão o padrão da capacidade (Configuração → Mídia), senão o Demo."""
    pid = node_pid or ((settings.get("media") or {}).get("active") or {}).get(cap) or "demo"
    preset = MEDIA_PRESETS.get(pid)
    if not preset:
        raise ProviderError(f"Provedor de mídia desconhecido: {pid}")
    if cap not in preset["caps"]:
        raise ProviderError(f"{preset['label']} não oferece {CAP_LABELS.get(cap, cap)}. Escolha outro provedor no nó (ou em Configuração → Mídia).")
    return pid


def describe_media_presets(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for pid, p in MEDIA_PRESETS.items():
        cfg = media_config(settings, pid)
        out.append({"id": pid, "label": p["label"], "caps": p["caps"], "base_url": cfg.get("base_url", ""), "default_url": p.get("base_url", ""), "needs_key": p.get("needs_key", False),
                    "has_key": bool(cfg.get("api_key")), "local": p.get("local", False), "docs": p.get("docs", ""), "hint": p.get("hint", ""),
                    "models": cfg["models"], "suggest": p.get("suggest", {})})
    return out
