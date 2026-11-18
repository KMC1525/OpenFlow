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

import atexit
import collections
import gc
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import native as _native
from .. import perf
from .. import perf as _perf
from ..util import hardware_info
from ..providers.base import ProviderError
from . import procedural as proc
from . import gguf_info, lowmem, mesh3d, quants, sdcli, support, voxcpm

CAP_LABELS = {"image": "imagens", "video": "vídeos", "sound": "sons e músicas", "voice": "vozes", "stt": "transcrição de áudio", "model3d": "modelos 3D"}
Ref = Tuple[bytes, str]  # (bytes, mime) de uma imagem de referência

MIME_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp", "image/gif": "gif",
    "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/ogg": "ogg", "audio/opus": "ogg",
    "audio/flac": "flac", "audio/x-flac": "flac", "audio/mp4": "m4a", "audio/aac": "aac", "audio/webm": "weba",
    "model/gltf-binary": "glb", "model/obj": "obj",
    "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov", "video/x-msvideo": "avi", "video/ogg": "ogv",
}


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
    if h[:4] == b"glTF":
        return "model/gltf-binary"
    if h[:4] == b"fLaC":
        return "audio/flac"
    if h[:3] == b"ID3" or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0):
        return "audio/mpeg"
    if data[4:8] == b"ftyp":
        return "audio/mp4" if data[8:12] in (b"M4A ", b"M4B ") else "video/mp4"
    if h[:4] == b"\x1aE\xdf\xa3":
        return "video/webm"
    return fallback


def refine_mime(data: bytes, mime: str) -> str:
    """Corrige o tipo pelas trilhas de dentro do arquivo (v0.52). `sniff_mime` só olha o contêiner: uma nota de voz em .mp4/.mov/.3gp, uma gravação .webm/.mka só com áudio ou um .m4a salvo como
    vídeo virava «vídeo» e quebrava os nós de vídeo; um vídeo Ogg (.ogv) virava «áudio». Sem o ffprobe, ou se não der para ler, o tipo fica como veio."""
    if not (mime.startswith("video/") or mime == "audio/ogg"):
        return mime
    probe = shutil.which("ffprobe")
    if not probe:
        return mime
    with tempfile.TemporaryDirectory(prefix="flow-sniff-") as td:
        f = Path(td) / "m.bin"
        f.write_bytes(data)
        try:
            r = subprocess.run([probe, "-v", "error", "-show_entries", "stream=codec_type:stream_disposition=attached_pic", "-of", "csv=p=0", str(f)], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return mime
    rows = [ln.split(",") for ln in r.stdout.splitlines() if ln.strip()]
    video = any(x[0] == "video" and not (len(x) > 1 and x[1] == "1") for x in rows)   # capa de álbum (attached_pic) não é vídeo
    audio = any(x[0] == "audio" for x in rows)
    if r.returncode != 0 or not (video or audio):
        return mime
    if mime.startswith("video/") and audio and not video:
        return {"video/mp4": "audio/mp4", "video/webm": "audio/webm", "video/quicktime": "audio/mp4"}.get(mime, "audio/" + mime.split("/")[1])
    if mime == "audio/ogg" and video:
        return "video/ogg"
    return mime


class Media:
    """Um arquivo gerado por um provedor."""

    def __init__(self, data: bytes, mime: str = "", meta: Optional[Dict[str, Any]] = None):
        self.data = data
        self.mime = (mime or sniff_mime(data) or "application/octet-stream").split(";")[0].strip().lower()
        self.meta = meta or {}

    @property
    def kind(self) -> str:
        main = self.mime.split("/")[0]
        return main if main in ("image", "audio", "video") else ("model3d" if main == "model" else "file")

    @property
    def ext(self) -> str:
        return MIME_EXT.get(self.mime, "bin")






def parse_wh(size: str) -> Tuple[int, int]:
    m = re.match(r"^(\d{2,5})x(\d{2,5})$", size or "")
    return (int(m.group(1)), int(m.group(2))) if m else (1024, 1024)


_ASPECTS = {"1:1": 1.0, "16:9": 16 / 9, "9:16": 9 / 16, "4:3": 4 / 3, "3:4": 3 / 4, "3:2": 3 / 2, "2:3": 2 / 3}




def size_of_aspect(aspect: str, long_side: int = 1280) -> Tuple[int, int]:
    try:
        a, b = [float(x) for x in aspect.split(":")]
    except (ValueError, AttributeError):
        a, b = 16.0, 9.0
    w, h = (long_side, long_side * b / a) if a >= b else (long_side * a / b, long_side)
    return int(w) // 2 * 2, int(h) // 2 * 2




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






# --------------------------------------------------------------------------- base


#: GGUF que juntam várias imagens de referência na mesma geração (edição, Kontext, FLUX.2 klein/dev, Qwen-Image 2.1): as referências valem também no modo Gerar
_QWEN_EDIT_2511 = re.compile(r"qwen[-_ ]?image[-_ ]?edit.*2511", re.I)   # v0.86: o Qwen-Image-Edit-2511 só edita bem com `--qwen-image-zero-cond-t` (cartão da stable-diffusion.cpp: «sem isso a qualidade cai muito»)
_H3_IMAGE = re.compile(r"minimax[-_ ]?h3[-_ ]?image", re.I)   # MiniMax H3 Image: edita com até 16 imagens de referência (<Picture 1>, <Picture 2>…)
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
        self.models: Dict[str, str] = dict(cfg.get("models") or {})
        self.ctl = ctl or Ctl()

    # utilidades
    def model_for(self, cap: str, override: str = "") -> str:
        return (override or self.models.get(cap) or "").strip()

    def poll(self, default: float) -> float:
        """Intervalo (s) entre consultas de trabalhos assíncronos (vídeo etc.)."""
        return float(self.cfg.get("poll_seconds") or default)

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

    def music(self, prompt: str, *, lyrics: str = "", instrumental: bool = False, bpm: int = 0, duration: int = 30, model: str = "", extra: Optional[Dict[str, Any]] = None, seed: int = 0) -> Media:
        """Uma música (v0.61). Padrão: o pedido vira texto («120 BPM», «instrumental») e vai para `sound(kind="music")`; só os provedores que cantam (`sings_lyrics`) fazem algo com a `lyrics`."""
        hints = [h for h in (f"{int(bpm)} BPM" if bpm else "", "instrumental, no vocals" if instrumental else "") if h]
        return self.sound(prompt + (", " + ", ".join(hints) if hints else ""), kind="music", duration=duration, model=model, extra=extra, seed=seed)

    def sings_lyrics(self, model: str = "") -> bool:
        """O modelo canta a letra? (A engine avisa quando não: a música sai só com o estilo.)"""
        return False

    def voice(self, text: str, *, voice: str = "", speed: float = 1.0, model: str = "", extra: Optional[Dict[str, Any]] = None, instructions: str = "", reference: Optional[Ref] = None,
              reference_text: str = "") -> Media:
        """`reference` (v0.71): um áudio (bytes, mime) com a voz a clonar e `reference_text`, o que ele diz (opcional; melhora a clonagem). Só os modelos que clonam voz (`clones_voice`) os usam."""
        raise self._no("voice")

    def clones_voice(self, model: str = "") -> bool:
        """O modelo clona a voz de um áudio de referência (v0.71)? A engine avisa quando há uma referência ligada e o modelo não clona."""
        return False

    def voice_style_note(self, model: str = "") -> str:
        """O que dizer ao usuário quando ele descreve a voz («Como é a voz») e este modelo não a lê por inteiro; vazio = a descrição vale (v0.64). O padrão: o modelo ignora a descrição."""
        return f"{self.label}{' (' + model + ')' if model else ''} não lê a descrição da voz: ela foi ignorada (a voz vem do campo «Voz» do nó)."

    def transcribe(self, data: bytes, filename: str, mime: str, *, language: str = "", model: str = "") -> str:
        raise self._no("stt")

    def transcribe_segments(self, data: bytes, filename: str, mime: str, *, language: str = "", model: str = "", duration: float = 0.0) -> List[Dict[str, Any]]:
        """A fala com TEMPO (v0.62): [{"start", "end", "text"}…]. Padrão: usa `transcribe` e devolve tudo num único trecho do começo ao fim (`timed_segments` é falso: quem precisa de tempos avisa)."""
        text = self.transcribe(data, filename, mime, language=language, model=model)
        return [{"start": 0.0, "end": float(duration or 0.0), "text": text.strip()}] if text.strip() else []

    def timed_segments(self, model: str = "") -> bool:
        """`transcribe_segments` devolve o tempo de cada trecho (e não um bloco só)?"""
        return False

    def model3d(self, prompt: str, *, image: Optional[Ref] = None, model: str = "", seed: int = 0, fmt: str = "glb", extra: Optional[Dict[str, Any]] = None) -> Media:
        """Um modelo 3D (GLB ou OBJ) a partir de um texto e/ou de uma imagem."""
        raise self._no("model3d")

    def model3d_needs_image(self, model: str = "") -> bool:
        """O modelo só aceita imagem (então o texto vira uma imagem antes)?"""
        return False

    def list_models(self, cap: str) -> List[str]:
        return []

    def test(self) -> str:
        return "ok"


# --------------------------------------------------------------------------- Demo (offline)


class DemoMedia(MediaProvider):
    id, label = "demo", "Demo (offline)"
    caps = ("image", "video", "sound", "voice", "model3d")
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

    def music(self, prompt, *, lyrics="", instrumental=False, bpm=0, duration=30, model="", extra=None, seed=0):
        return Media(proc.music(prompt, float(duration), seed, lyrics="" if instrumental else lyrics, bpm=int(bpm or 0)), "audio/wav", {"note": "demo"})

    def sings_lyrics(self, model=""):
        return True   # a demonstração «canta» a letra num balbucio rítmico (não é canto de verdade)

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions="", reference=None, reference_text=""):
        return Media(proc.babble(text, speed, proc.seed_of(voice), instructions), "audio/wav", {"note": "demo"})

    def voice_style_note(self, model=""):
        return ""   # a demonstração lê a descrição: muda o tom, o ritmo e o volume do balbucio

    def model3d(self, prompt, *, image=None, model="", seed=0, fmt="glb", extra=None):
        mix = proc.seed_of(len(image[0])) if image else 0   # com imagem, o resultado muda (não reconstrói de verdade)
        fmt = mesh3d.valid_format(fmt)
        return Media(mesh3d.encode(mesh3d.demo_mesh(prompt, seed + mix), fmt), mesh3d.MIME[fmt], {"note": "demo"})

    def transcribe(self, data, filename, mime, *, language="", model=""):
        raise ProviderError("O provedor Demo não transcreve áudio. Escolha um provedor de transcrição (OpenAI, Groq, Whisper local…) em Configuração → Mídia.")

    def test(self) -> str:
        return "Demo pronto" + ("" if proc.ffmpeg_path() else " (vídeo precisa do ffmpeg)")


# --------------------------------------------------------------------------- OpenAI e compatíveis


# --------------------------------------------------------------------------- Modelos do Hugging Face rodando localmente


_LOCAL_LOCK = threading.Lock()
_LOCAL_CACHE: Dict[Tuple[str, str], Any] = {}


def _local_import(*names: str, extra: str = "media") -> List[Any]:
    try:
        return [__import__(n, fromlist=["_"]) for n in names]
    except ImportError as exc:
        raise ProviderError(f'Modelos locais precisam das bibliotecas opcionais ({exc.name}). Instale com:  pip install "openflow[' + extra + ']"  (ou rode: flow libs)') from None


def _hf_pipeline(tf: Any, task: str, model: str, dtype: Any) -> Any:
    """`transformers.pipeline` só com arquivos já baixados (nada é baixado em silêncio). Versões novas do transformers repassam `local_files_only` sozinhas ao carregar a configuração, e repeti-lo em `model_kwargs`
    dá «got multiple values for keyword argument 'local_files_only'» (v0.66: a transcrição do Whisper falhava assim): nesse caso o modo offline vai pela variável HF_HUB_OFFLINE, que vale para todas as versões."""
    try:
        return tf.pipeline(task, model=model, torch_dtype=dtype, model_kwargs={"local_files_only": True})
    except TypeError as exc:
        if "local_files_only" not in str(exc):
            raise
    old = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        return tf.pipeline(task, model=model, torch_dtype=dtype)
    finally:
        if old is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = old


def _pick_cuda(torch: Any) -> None:
    """Com várias placas: torna «cuda» a escolhida com mais memória livre (Configurações → Desempenho → GPUs). O torch numera as placas como o nvidia-smi quando CUDA_DEVICE_ORDER=PCI_BUS_ID."""
    try:
        i = _perf.primary_gpu()
        if i is not None and torch.cuda.device_count() > 1 and i < torch.cuda.device_count():
            torch.cuda.set_device(i)
    except Exception:  # noqa: BLE001 — a escolha da placa nunca derruba a geração
        pass


def _device() -> Tuple[str, Any]:
    (torch,) = _local_import("torch")
    if _perf.device() == "cpu":   # Configurações → Desempenho → Rodar em: só CPU
        return "cpu", torch.float32
    if torch.cuda.is_available():
        _pick_cuda(torch)
        return "cuda", torch.float16
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps", torch.float16
    xpu = getattr(torch, "xpu", None)   # v0.82: placas Intel (Arc, integradas) pelo PyTorch com o pacote XPU
    try:
        if xpu is not None and xpu.is_available() is True:   # `is True`: só um bool de verdade vale
            return "xpu", torch.float16
    except Exception:  # noqa: BLE001 — um driver Intel quebrado não pode derrubar a geração: cai para a CPU
        pass
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
        elif getattr(torch, "xpu", None) is not None and torch.xpu.is_available() is True:
            torch.xpu.empty_cache()
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() is True:
            torch.mps.empty_cache()
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 — limpar o cache da placa nunca pode dar erro
        pass
    _give_back_memory()


_MEDIA_IDLE = _perf.IdleUnloader(_media_unload)
PERF: Dict[str, Any] = {}  # settings["performance"], preenchido pela rota/engine antes de gerar


_PLAN: Dict[str, Any] = {}   # plano de carga do modelo que está sendo carregado (núcleo Rust): estratégia de GPU/descarga, fatias de atenção e VAE


def resident_bytes() -> int:
    """Quanta RAM o modelo de imagem/vídeo/som carregado ocupa (o tamanho dos pesos do último plano; 0 se não há modelo carregado)."""
    with _LOCAL_LOCK:
        loaded = bool(_LOCAL_CACHE)
    return int(_PLAN.get("weights") or 0) if loaded else 0


def _apply_ram(plan: Dict[str, Any], weights: int) -> None:
    """Computador de 16 GB (v0.45, núcleo Rust: native.plan_ram): se o modelo de texto carregado e este não cabem juntos na RAM, o de texto sai antes; fatias de atenção e de VAE também ficam ligadas
    quando o modelo ocupa boa parte da RAM, e o modelo descarrega mais cedo quando ocioso."""
    try:
        from ..providers import local_llama

        ram = _perf.ram_plan(weights, 0, local_llama.resident_bytes())
        if not ram or ram.get("class") not in ("small", "16"):
            return
        plan["ram"] = ram
        if ram.get("evict_other"):
            local_llama._unload()
        plan["slicing"] = bool(plan.get("slicing")) or bool(ram.get("media_slicing"))
        plan["tiling"] = bool(plan.get("tiling")) or bool(ram.get("media_tiling"))
        plan["prefetch"] = bool(plan.get("prefetch")) and bool(ram.get("prefetch"))
    except Exception:  # noqa: BLE001 — sem plano de RAM, vale o plano de antes
        pass


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
        _apply_ram(plan, weights)
        return plan
    except Exception:  # noqa: BLE001
        return {}


def _balanced_kwargs(weights: int) -> Dict[str, Any]:
    """Várias placas (v0.59): argumentos do `from_pretrained` do diffusers para dividir o modelo entre as placas escolhidas — `device_map="balanced"` e `max_memory` (a memória usável de cada placa e, com «usar a RAM junto»,
    a RAM livre). {} quando o modelo cabe numa placa só (o plano de sempre vale), quando há uma placa só, ou quando nem as placas juntas (nem com a RAM) o comportam."""
    try:
        (torch,) = _local_import("torch")
        if not weights or _perf.device() == "cpu" or not torch.cuda.is_available() or torch.cuda.device_count() < 2:
            return {}
        pool = _perf.gpu_pool()
        if len(pool) < 2 or weights <= pool[0]["usable"]:
            return {}
        total = sum(g["usable"] for g in pool)
        cfg = _perf.memory_cfg()
        ram = int(_perf.pool_summary()["ram_usable"])
        if weights > total and (not cfg["ram_spill"] or weights > total + ram):
            return {}
        mm: Dict[Any, str] = {g["index"]: f"{max(1, g['usable'] // 1048576)}MiB" for g in pool}
        if cfg["ram_spill"] and ram > 0:
            mm["cpu"] = f"{max(1, ram // 1048576)}MiB"
        return {"device_map": "balanced", "max_memory": mm}
    except Exception:  # noqa: BLE001 — sem o plano de várias placas, vale o plano de uma
        return {}


def _load_pipeline(factory: Callable[..., Any], kw: Dict[str, Any], note: Callable[[str], None] = lambda m: None) -> Any:
    """`factory(**kw)` dividindo o modelo entre as placas quando ele não cabe numa só (v0.59); se a versão do diffusers/accelerate não aceitar (ou falhar), repete do jeito de sempre."""
    extra = _balanced_kwargs(int(_PLAN.get("weights") or 0))
    if extra:
        try:
            pipe = factory(**{**kw, **extra})
            _PLAN["balanced"] = {"gpus": [k for k in extra["max_memory"] if k != "cpu"], "ram": "cpu" in extra["max_memory"]}
            note("Modelo dividido entre as placas de vídeo" + (" e a RAM" if "cpu" in extra["max_memory"] else "") + ".")
            return pipe
        except Exception:  # noqa: BLE001
            gc.collect()
    return factory(**kw)


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
    if getattr(pipe, "hf_device_map", None) and _PLAN.get("balanced"):   # dividido entre as placas pelo device_map (v0.59): cada parte já está no seu lugar
        return pipe
    if dev == "cuda" and plan["strategy"] == "gpu" and _perf.device() == "hybrid":   # CPU + GPU juntas (v0.31): cada parte (texto, difusão, VAE) só ocupa a placa enquanto trabalha; o resto espera na RAM
        plan = dict(plan, strategy="model_offload")
    if dev == "cuda" and plan["strategy"] in ("model_offload", "sequential_offload"):
        for fn in (("enable_sequential_cpu_offload", "enable_model_cpu_offload") if plan["strategy"] == "sequential_offload" else ("enable_model_cpu_offload",)):
            try:
                getattr(pipe, fn)()
                return pipe
            except Exception:  # noqa: BLE001
                pass
    try:
        return pipe.to(dev)
    except Exception as exc:  # noqa: BLE001
        if dev != "cuda" or lowmem.oom_kind(exc) != "gpu":
            raise
        gc.collect()   # o plano achou que cabia na placa e não coube (outro programa a usa): cai para a descarga do modelo, que cabe em bem menos memória
        try:
            import torch  # type: ignore

            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        for fn in ("enable_model_cpu_offload", "enable_sequential_cpu_offload"):
            try:
                getattr(pipe, fn)()
                return pipe
            except Exception:  # noqa: BLE001
                gc.collect()
        raise ProviderError("Não coube na memória da placa de vídeo nem com a descarga para a RAM. " + lowmem.tips("gpu")) from None


_TLS = threading.local()   # o Ctl do nó que está carregando/gerando (para avisar o progresso do carregamento, que não passa pelo provedor)
_TORCH_THREADS: Dict[str, Any] = {"orig": None}
_HEARTBEAT_S = 8.0


def _limit_threads() -> None:
    """Deixa um núcleo da CPU livre para a interface e o sistema enquanto o torch gera (v0.77): o torch usa todos os núcleos por padrão e, numa máquina fraca, o computador inteiro «trava» durante a geração.
    Segue o modo de desempenho (leve: metade; equilibrado: todos menos um; máximo: todos)."""
    try:
        import torch  # type: ignore

        if _TORCH_THREADS["orig"] is None:
            _TORCH_THREADS["orig"] = int(torch.get_num_threads())
        mode = _perf.resolve(str(PERF.get("mode") or "auto"), hardware_info())
        want = lowmem.torch_threads(int(_native.sys_info().get("physical") or os.cpu_count() or 1), mode) or _TORCH_THREADS["orig"]
        if int(torch.get_num_threads()) != want:
            torch.set_num_threads(max(1, int(want)))
    except Exception:  # noqa: BLE001 — sem torch (ou sem informação do sistema) não há o que limitar
        pass


def _heartbeat(stop: threading.Event, what: str, ctl: Any, interval: float = 8.0) -> None:
    """Enquanto um modelo grande carrega (minutos, sem nenhum evento), avisa a cada poucos segundos que o OpenFlow está trabalhando — e há quanto tempo."""
    t0 = time.monotonic()
    while not stop.wait(interval):
        ctl.note(f"Carregando {what} na memória… {lowmem.fmt_seconds(time.monotonic() - t0)} (modelos grandes levam alguns minutos)")


def _local_load(cap: str, model: str, loader: Callable[[], Any]) -> Any:
    """`_local_load_locked` com o Ctl do nó (deixado por `_ready` na thread) valendo SÓ para esta chamada: um Ctl que sobra de um trabalho cancelado não pode cancelar o carregamento do trabalho seguinte."""
    try:
        return _local_load_locked(cap, model, loader)
    finally:
        _TLS.ctl = None


def _local_load_locked(cap: str, model: str, loader: Callable[[], Any]) -> Any:
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
            ctl = lowmem.safe_ctl(getattr(_TLS, "ctl", None))
            verdict, why = lowmem.fit(int(plan.get("weights") or 0), int(_perf.memory_state().get("ram_avail") or 0) if plan else 0, str(plan.get("strategy") or ""))
            if verdict == "refuse":
                raise ProviderError(f"«{model}»: {why}")
            if verdict == "warn":
                ctl.note("Atenção: " + why)
            _limit_threads()
            if plan.get("prefetch") and plan.get("files"):
                _native.prefetch(plan["files"])   # leitura paralela: o from_pretrained acha os pesos já em RAM
            stop = threading.Event()
            beat = threading.Thread(target=_heartbeat, args=(stop, f"«{model}»", ctl, _HEARTBEAT_S), daemon=True)
            beat.start()
            try:
                _LOCAL_CACHE[key] = loader()
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001
                if "torchvision" in str(exc).lower():  # ex.: processadores de visão do Qwen-Image/Qwen3-VL pedem a torchvision
                    raise ProviderError("Este modelo precisa da biblioteca torchvision, que não está instalada. Instale com:  pip install torchvision  (ou rode: flow libs --extras media) e tente de novo; depois de instalar, reinicie o OpenFlow.") from None
                kind = lowmem.oom_kind(exc)
                if kind:   # v0.72: acabou a memória ao CARREGAR (RAM ou placa): explica em vez do erro cru
                    raise ProviderError(f"Acabou a memória {lowmem.where(kind)} ao carregar «{model}». {lowmem.tips(kind)}") from None
                raise
            finally:
                stop.set()
            ctl.check()   # o usuário pode ter cancelado durante o carregamento
            if plan:
                _native.record("media", cap=cap, model=model, strategy=plan.get("strategy"), weights=plan.get("weights"), slicing=plan.get("slicing"), tiling=plan.get("tiling"))
        return _LOCAL_CACHE[key]


def _wav_from_array(arr: Any, rate: int) -> bytes:
    (np,) = _local_import("numpy")
    a = np.nan_to_num(np.asarray(arr, dtype="float32"), nan=0.0, posinf=1.0, neginf=-1.0)   # NaN/inf (modelo instável) viravam ruído estourado e um peak NaN
    a = np.squeeze(a)
    if a.size == 0:
        raise ProviderError("O modelo de áudio não devolveu nenhuma amostra. Tente de novo (ou mude a semente).")
    if a.ndim == 0:
        a = a.reshape(1)
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
    caps = ("image", "video", "sound", "voice", "stt", "model3d")
    supports_refs = True   # imagem → imagem pelo mesmo modelo
    refs_edit_only = True

    def max_refs(self, model: str = "") -> int:
        name = (model or self.model_for("image", model) or "").lower()
        if re.search(r"flux[-_. ]?3", name):
            return 10   # FLUX.3 Image Klein: até 10 imagens de referência no mesmo pedido
        if "klein" in name:
            return 4   # FLUX.2 klein edita com várias imagens de uma vez
        if re.search(r"flux[-_. ]?2", name):
            return 10   # FLUX.2 dev: até 10 imagens de referência (v0.72: antes só a primeira era usada)
        if re.search(r"qwen[-_ ]?image[-_ ]?edit[-_ ]?(plus|2509|2511)", name):
            return 3   # Qwen-Image-Edit-Plus (2509/2511): até 3 imagens
        return 1   # os demais fazem imagem → imagem (ou edição) com uma

    def refs_need_edit(self, model: str = "") -> bool:
        return self.max_refs(model) <= 1   # klein, FLUX.2 e FLUX.3 juntam várias referências também no modo Gerar

    @staticmethod
    def _defaults(model: str) -> Tuple[int, float]:
        """Passos e guidance do modelo (o padrão de cada família): FLUX.2 klein destilado 4 passos sem CFG; klein «base» 50 passos e guidance 4; FLUX.1 schnell 4 passos; FLUX.1 dev 28 passos e guidance 3,5;
        modelos «turbo»/«lightning»/«lcm» 2 passos sem CFG; os demais 25 passos e guidance 7."""
        name = model.lower()
        if re.search(r"qwen[-_ ]?image", name):   # Qwen-Image usa `true_cfg_scale` (4,0) e 50 passos; 30 já dão o resultado e poupam tempo em máquina fraca; as versões «Lightning» são destiladas (4 ou 8 passos, sem CFG)
            return ((4 if re.search(r"4[-_ ]?step", name) else 8), 1.0) if "lightning" in name else (30, 4.0)
        if re.search(r"flux[-_. ]?3", name):
            return (50, 3.5) if "base" in name else (16, 0.0)   # FLUX.3 Image Klein: destilado 16 passos sem guidance; «base» 50 passos e guidance 3,5
        if "klein" in name:
            return (50, 4.0) if "base" in name else (4, 1.0)
        if "schnell" in name:
            return 4, 0.0
        if re.search(r"z[-_ ]?image", name):   # Z-Image-Turbo: 9 passos (8 avaliações) e guidance 0; o «base» usa CFG (28 passos, guidance 4). Com «turbo» valendo 2 passos saía borrado
            return (9, 0.0) if "turbo" in name else (28, 4.0)
        if re.search(r"sd3|stable[-_ ]diffusion[-_ ]3", name):   # SD3/SD3.5: guidance 7 (o padrão antigo) satura; a documentação usa ~4,5 com 28 passos, e o «turbo» 4 passos sem guidance
            return (4, 0.0) if "turbo" in name else (28, 4.5)
        if "lightning" in name:   # SDXL-Lightning: 2, 4 ou 8 passos (o nome diz); sem o número, 4
            m = re.search(r"(\d)[-_ ]?step", name)
            return (int(m.group(1)) if m else 4), 0.0
        if any(k in name for k in ("turbo", "lcm")):
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

    def _ready(self, model: str, quantizes: bool = False) -> Dict[str, Any]:
        """Argumentos de carregamento do modelo (precisão escolhida, só arquivos locais). Recusa modelos que ainda não foram baixados. `quantizes`: quem chama sabe comprimir na faixa Q8…Q2 (imagem e vídeo
        pelo diffusers); os outros modelos (voz, som, transcrição, 3D) rodam sem compressão e o nó avisa."""
        from . import localmodels as lm

        _TLS.ctl = self.ctl
        _limit_threads()
        prec = lm.downloaded_precision(model)
        if not prec:
            raise ProviderError(f'O modelo local "{model}" ainda não foi baixado. Em Configuração → Mídia, escolha a precisão (quantização) e baixe-o antes de usar.', status=424)
        low = prec in ("fp16", "bf16") or lm.is_quant(prec)
        self.ctl.note(f"Modelo local {model} ({prec})")
        if lm.is_quant(prec) and not quantizes:
            self.ctl.note(f"A faixa {prec.upper()} só comprime modelos de imagem e vídeo: «{model}» roda sem compressão (nos pesos do fp16).")
        dtype = lm.torch_dtype(prec)
        try:   # v0.72: fp16 não roda na CPU, e o FLUX/Qwen-Image geram imagem preta em fp16: o tipo vale para o aparelho em uso
            (torch,) = _local_import("torch")
            real = lowmem.device_dtype(model, dtype, _device()[0], torch)
            if real is not dtype:
                self.ctl.note(f"Tipo numérico: {str(real).replace('torch.', '')} (o fp16 não é seguro para este modelo/aparelho).")
            dtype = real
        except Exception:  # noqa: BLE001
            pass
        return {"precision": prec, "dtype": dtype, "variant": "fp16" if low and lm.has_fp16_variant(model) else None, "tier": lm.tier_of_precision(prec)}

    def _quant_kw(self, model: str, ready: Dict[str, Any], diffusers: Any) -> Dict[str, Any]:
        """A faixa Q8…Q2 escolhida no download (v0.81): os argumentos de `from_pretrained` que comprimem o modelo de difusão e os codificadores de texto AO CARREGAR (bitsandbytes na placa NVIDIA, senão optimum-quanto, que
        roda em qualquer aparelho). Sem faixa, nada. Sem a biblioteca, o erro diz qual instalar (carregar sem comprimir estouraria a memória justo de quem escolheu a faixa)."""
        import importlib.util as iu

        tier = ready.get("tier") or ""
        if not tier:
            return {}
        bits = quants.original_bits(tier)
        if quants.original_note(tier):
            self.ctl.note(quants.original_note(tier))

        def has(name: str) -> bool:
            try:
                return iu.find_spec(name) is not None
            except (ImportError, ValueError):
                return False
        dev, _ = _device()
        backend = quants.backend_for(bits, dev == "cuda", has("bitsandbytes"), has("optimum.quanto"))
        if not backend:
            raise ProviderError(f'O modelo {model} foi baixado na faixa {tier}, que comprime os pesos ao carregar, mas falta a biblioteca de compressão. {quants.install_hint(bits, dev == "cuda")}')
        from . import localmodels as lm

        parts = quants.quantizable(lm.components(model))
        if not parts:
            self.ctl.note(f"{model} não tem um componente que dê para comprimir ({tier}): carregando sem compressão.")
            return {}
        try:
            (tf,) = _local_import("transformers")
        except Exception:  # noqa: BLE001 — sem transformers só o modelo de difusão é comprimido
            tf = None
        configs = quants.build_configs(backend, bits, ready["dtype"], diffusers, tf)
        self.ctl.note(f"Comprimindo para {tier} ({bits} bits, {'bitsandbytes' if backend == 'bnb' else 'optimum-quanto'}) ao carregar: {', '.join(sorted(parts))}.")
        return {"quantization_config": diffusers.PipelineQuantizationConfig(quant_mapping=quants.pipeline_mapping(parts, configs))}

    @staticmethod
    def _transformer_only(model: str) -> bool:
        """Repositórios que trazem só o transformador quantizado (sem o pipeline inteiro): ex. chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized. O diffusers precisaria do repositório-base para montar o resto."""
        return bool(re.search(r"(omni|uncensored)[-_.a-z0-9]*quantized$|^chatrlabs/", (model or "").lower()))

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        model = self._pick("image", model, "stabilityai/sd-turbo")
        if self._transformer_only(model):
            raise ProviderError(f'«{model}» traz só o transformador quantizado (sem o codificador de texto e o VAE): o diffusers do OpenFlow carrega repositórios completos. Use os arquivos .gguf deste repositório pelo provedor «GGUF local» (barra de pesquisa de modelos do Canvas → Q4_K_M, Q5_K_M…): o OpenFlow baixa junto o VAE e o codificador Qwen3-VL-8B.')
        (diffusers,) = _local_import("diffusers")
        dev, _ = _device()
        ready = self._ready(model, quantizes=True)

        def load() -> Any:
            if self._is_modular(model):
                if ready.get("tier"):   # v0.84: o pipeline modular (FLUX.3) não passa pela compressão ao carregar: o aviso substitui o silêncio
                    self.ctl.note(f"A faixa {ready['tier']} ainda não vale para o pipeline modular (FLUX.3): carregando sem compressão (nos pesos do fp16). Para economizar memória, use o GGUF.")
                return _slim(self._load_modular(diffusers, model, ready), dev)
            kw: Dict[str, Any] = {"torch_dtype": ready["dtype"], "local_files_only": True, **self._quant_kw(model, ready, diffusers)}
            if ready["variant"]:
                kw["variant"] = ready["variant"]
            try:
                pipe = _load_pipeline(lambda **k: diffusers.AutoPipelineForText2Image.from_pretrained(model, **k), kw, self.ctl.note)
            except Exception as exc:  # noqa: BLE001 — pipelines novos (FLUX.2 klein…) que o AutoPipeline da versão instalada ainda não conhece: a classe vem do model_index.json
                try:
                    pipe = _load_pipeline(lambda **k: diffusers.DiffusionPipeline.from_pretrained(model, **k), kw, self.ctl.note)
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
        if dev == "cpu" and max(w, h) > 768:   # na CPU o lado maior vai a 768 mantendo a proporção (antes cada lado era cortado sozinho e 1024×576 virava 768×576, esticado)
            k = 768 / max(w, h)
            w, h = int(w * k), int(h * k)
        w, h = max(256, w // 16 * 16), max(256, h // 16 * 16)   # múltiplos de 16: FLUX, Qwen-Image, SD3 e Z-Image trabalham em blocos de 16 px e o diffusers reclama (ou corta) o resto
        pil = _pil_refs(refs, self.max_refs(model)) if refs else []
        if refs and not pil:
            raise ProviderError("Não consegui ler as imagens de referência ligadas ao nó (formato não suportado).")
        i2i = None
        if pil:
            if len(pil) == 1 and self.edit_mode:   # só no modo Editar com uma imagem: mantém a proporção dela; ao Gerar (e com várias referências) vale o tamanho pedido
                w, h = _size_like(pil[0], w, h, 16 if (klein or flux3) else 8)
            if not klein and not flux3 and not lowmem.edit_style(lowmem.params_of(pipe)):   # imagem → imagem: reaproveita os pesos já carregados (o FLUX.2 klein, o FLUX Kontext, o FLUX.2 e o Qwen-Image-Edit editam pelo próprio pipeline)
                try:
                    i2i = diffusers.AutoPipelineForImage2Image.from_pipe(pipe)   # compartilha os pesos de `pipe` (não passa por _local_load: ele guarda um modelo só e descartaria o principal)
                except Exception:  # noqa: BLE001 — v0.72: o diffusers não liga este pipeline a um de imagem → imagem: antes era um erro cru no meio da geração
                    raise ProviderError(f"«{model}» não aceita uma imagem de referência neste modo (o diffusers não tem o pipeline de imagem → imagem dele). Use um modelo de edição (FLUX Kontext, FLUX.2, Qwen-Image-Edit) ou gere sem imagem ligada.") from None
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
            target = i2i or pipe
            params = lowmem.params_of(target)
            qwen = bool(re.search(r"qwen[-_ ]?image", model.lower()))
            kw = {"prompt": prompt, "width": w, "height": h, "num_inference_steps": steps, "guidance_scale": guidance,
                  "generator": torch.Generator("cpu").manual_seed(int(seed + i) if seed else int(time.time() * 1000) % (2 ** 31) + i)}
            if negative and not no_negative:
                kw["negative_prompt"] = negative
            if qwen and lowmem.accepted(params, "true_cfg_scale"):   # Qwen-Image: o CFG é `true_cfg_scale` e só vale com prompt negativo (sem ele o diffusers desliga o CFG: imagem mais fraca)
                kw.pop("guidance_scale", None)
                kw["true_cfg_scale"] = guidance
                if guidance > 1.0 and "negative_prompt" not in kw:
                    kw["negative_prompt"] = " "
            if pil and (klein or lowmem.edit_style(params)):   # edição pelo próprio pipeline (FLUX.2 klein/FLUX.2, FLUX Kontext, Qwen-Image-Edit): não há `strength`; as imagens ligadas guiam o resultado
                imgs = [cover_fit(p, w, h) for p in pil] if len(pil) == 1 else [fit_inside(p, w, h) for p in pil]   # v0.86: sem esticar (várias referências: cada uma com a própria proporção)
                if klein or lowmem.multi_image(type(target).__name__):
                    kw["image"] = imgs
                else:
                    kw["image"] = imgs[0]
            elif pil:
                kw.pop("width"), kw.pop("height")
                kw.update(image=cover_fit(pil[0], w, h), strength=0.8 if fast else 0.75)
                if fast:
                    kw["num_inference_steps"] = max(4, steps)   # modelos «turbo»: com strength < 1 sobram menos passos, e precisam de pelo menos 1
            kw = lowmem.keep(kw, params)   # só o que o pipeline aceita (o campo «Extra» do usuário vai depois, sem filtro)
            if lowmem.explicit(params, "callback_on_step_end"):   # v0.77: progresso e cancelamento a cada passo (antes só entre uma imagem e outra: o «Parar» ficava mudo por minutos)
                kw["callback_on_step_end"] = lowmem.step_progress(self.ctl, lowmem.effective_steps(int(kw.get("num_inference_steps") or steps), kw.get("strength")), f"Gerando imagem {i + 1} de {max(1, count)}" if count > 1 else "Gerando imagem")
            kw.update(extra or {})
            img = self._generate(target, kw, pipe, dev, torch, model)
            w, h = int(kw.get("width") or w), int(kw.get("height") or h)   # se o tamanho foi reduzido por falta de memória, as próximas imagens já saem no tamanho que coube
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            out.append(Media(buf.getvalue(), "image/png"))
        return out

    def _lighten(self, pipe: Any) -> None:
        """Depois de faltar memória na placa: fatias de atenção/VAE e descarga do modelo para a RAM (o que couber nesta versão do diffusers)."""
        for fn in ("enable_vae_slicing", "enable_vae_tiling", "enable_attention_slicing"):
            try:
                getattr(pipe, fn)()
            except Exception:  # noqa: BLE001
                pass
        for fn in ("enable_sequential_cpu_offload", "enable_model_cpu_offload"):
            try:
                getattr(pipe, fn)()
                break
            except Exception:  # noqa: BLE001
                pass
        self.ctl.note("Faltou memória na placa de vídeo: tentando de novo com a descarga do modelo para a RAM…")

    def _generate(self, call: Any, kw: Dict[str, Any], pipe: Any, dev: str, torch: Any, model: str) -> Any:
        """Roda o pipeline. Se acabar a memória (placa de vídeo ou RAM), tenta de novo mais leve — na placa: fatiamento do VAE e descarga para a RAM; depois, uma imagem 25% menor (até 2 reduções) — em vez de
        devolver o erro cru do torch. `kw` é atualizado com o tamanho que coube."""
        tries, shrunk, lowered = 0, 0, False
        while True:
            try:
                with lowmem.heartbeat(self.ctl, "Ainda gerando (a decodificação final da imagem também demora)"):
                    return call(**kw).images[0]
            except Exception as exc:  # noqa: BLE001
                kind = lowmem.oom_kind(exc)
                if not kind:
                    raise
                gc.collect()
                try:
                    if dev == "cuda":
                        torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass
                tries += 1
                if kind == "gpu" and not lowered and dev == "cuda":
                    lowered = True
                    self._lighten(pipe)
                    continue
                cur = (int(kw.get("width") or 0), int(kw.get("height") or 0))
                if not cur[0] and kw.get("image") is not None:   # imagem → imagem: o tamanho é o da imagem
                    first = kw["image"][0] if isinstance(kw["image"], (list, tuple)) else kw["image"]
                    cur = tuple(first.size)
                nxt = lowmem.shrink(*cur) if cur[0] and shrunk < 2 else None
                if not nxt:
                    raise ProviderError(lowmem.friendly_oom(kind, model, cur[0], cur[1], shrunk)) from None
                shrunk += 1
                if kw.get("width"):
                    kw["width"], kw["height"] = nxt
                if kw.get("image") is not None:
                    kw["image"] = [im.resize(nxt) for im in kw["image"]] if isinstance(kw["image"], (list, tuple)) else kw["image"].resize(nxt)
                self.ctl.note(f"Faltou memória: tentando de novo em {nxt[0]}×{nxt[1]}…")

    # ---- 3D (v0.37): Shap-E (texto e imagem, diffusers), TripoSR e Hunyuan3D-2 (imagem, bibliotecas próprias)
    def model3d_needs_image(self, model: str = "") -> bool:
        return mesh3d.needs_image(self._pick("model3d", model, "openai/shap-e"))

    def model3d(self, prompt, *, image=None, model="", seed=0, fmt="glb", extra=None):
        model = self._pick("model3d", model, "openai/shap-e")
        fam = mesh3d.family(model)
        if not fam:
            raise ProviderError(f'O modelo 3D "{model}" não é de uma família conhecida. Use Shap-E (openai/shap-e), TripoSR (stabilityai/TripoSR) ou Hunyuan3D-2 (tencent/Hunyuan3D-2mini) — baixe em Configuração → Mídia.')
        pil = _pil_refs([image], 1, keep_alpha=fam != "shap-e") if image else []   # TripoSR/Hunyuan3D recebem o recorte com transparência (v0.53); o Shap-E, RGB
        if image and not pil:
            raise ProviderError("Não consegui ler a imagem ligada ao nó 3D (formato não suportado).")
        if fam == "shap-e":
            if pil and not mesh3d.is_img2img(model):
                model = mesh3d.FAMILIES["shap-e"]["image_repo"]   # com imagem, o Shap-E usa a versão «img2img» (outro modelo; precisa estar baixado)
            elif not pil and mesh3d.is_img2img(model):
                raise ProviderError("O modelo openai/shap-e-img2img precisa de uma imagem ligada ao nó. Para texto → 3D use openai/shap-e.")
            mesh = self._mesh_shape(model, prompt, pil[0] if pil else None, seed, extra or {})
        else:
            if not pil:
                raise ProviderError(f"{mesh3d.FAMILIES[fam]['label']} só cria 3D a partir de uma imagem: ligue uma imagem ao nó (ou use um texto, que vira imagem antes).")
            mesh = self._mesh_tsr(model, pil[0], extra or {}) if fam == "triposr" else self._mesh_hunyuan(model, pil[0], seed, extra or {})
        fmt = mesh3d.valid_format(fmt)
        return Media(mesh3d.encode(mesh, fmt), mesh3d.MIME[fmt], {"family": fam})

    def _mesh_shape(self, model: str, prompt: str, pil: Any, seed: int, extra: Dict[str, Any]) -> Any:
        (diffusers,) = _local_import("diffusers")
        (torch,) = _local_import("torch")
        dev, _ = _device()
        ready = self._ready(model)
        cls = diffusers.ShapEImg2ImgPipeline if pil is not None else diffusers.ShapEPipeline

        def load() -> Any:
            return _slim(cls.from_pretrained(model, torch_dtype=ready["dtype"], local_files_only=True), dev)

        pipe = _local_load("model3d", model, load)
        self.ctl.note("Gerando o modelo 3D localmente…")
        gen = torch.Generator("cpu").manual_seed(int(seed) if seed else int(time.time() * 1000) % (2 ** 31))
        kw: Dict[str, Any] = {"num_inference_steps": 64, "guidance_scale": 15.0, "frame_size": 256, "output_type": "mesh", "generator": gen}
        kw.update(extra)
        out = pipe(pil if pil is not None else prompt, **kw)
        m = out.images[0]
        chans = getattr(m, "vertex_channels", None) or {}
        colors = None
        if all(k in chans for k in "RGB"):
            colors = [(float(r), float(g), float(b)) for r, g, b in zip(chans["R"].tolist(), chans["G"].tolist(), chans["B"].tolist())]
        v, f, c = mesh3d.as_lists(m.verts, m.faces, colors)
        return mesh3d.rotate_x(v, -90.0), f, c   # o Shap-E entrega a malha deitada (eixo z para cima)

    def _mesh_tsr(self, model: str, pil: Any, extra: Dict[str, Any]) -> Any:
        from . import localmodels as lm

        try:
            from tsr.system import TSR  # type: ignore
        except ImportError:
            raise ProviderError("O TripoSR precisa da biblioteca dele:  pip install git+https://github.com/VAST-AI-Research/TripoSR  (e o torch).") from None
        (torch,) = _local_import("torch")
        self._ready(model)
        snap = lm._snapshot(model)
        dev = "cuda" if torch.cuda.is_available() and _perf.device() != "cpu" else "cpu"

        def load() -> Any:
            m = TSR.from_pretrained(str(snap or model), config_name="config.yaml", weight_name="model.ckpt")
            m.renderer.set_chunk_size(8192)
            return m.to(dev)

        net = _local_load("model3d", model, load)
        self.ctl.note("Reconstruindo o objeto em 3D (TripoSR)…")
        img = pil.convert("RGBA")
        bg = img.__class__.new("RGBA", img.size, (128, 128, 128, 255))   # objeto sobre cinza médio, como o TripoSR espera
        bg.alpha_composite(img)
        with torch.no_grad():
            codes = net([bg.convert("RGB")], device=dev)
            meshes = net.extract_mesh(codes, True, resolution=int(extra.get("resolution", 256)))
        m = meshes[0]
        vc = getattr(getattr(m, "visual", None), "vertex_colors", None)
        colors = [(c[0] / 255.0, c[1] / 255.0, c[2] / 255.0) for c in vc.tolist()] if vc is not None and len(vc) == len(m.vertices) else None
        return mesh3d.as_lists(m.vertices, m.faces, colors)

    def _mesh_hunyuan(self, model: str, pil: Any, seed: int, extra: Dict[str, Any]) -> Any:
        try:
            from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # type: ignore
        except ImportError:
            raise ProviderError("O Hunyuan3D-2 precisa da biblioteca dele:  pip install git+https://github.com/Tencent/Hunyuan3D-2  (e o torch).") from None
        (torch,) = _local_import("torch")
        self._ready(model)
        dev = "cuda" if torch.cuda.is_available() and _perf.device() != "cpu" else "cpu"

        def load() -> Any:
            old = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"   # nada é baixado em silêncio
            try:
                sub = "hunyuan3d-dit-v2-mini" if "mini" in model.lower() else "hunyuan3d-dit-v2-0"
                return Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(model, subfolder=sub, use_safetensors=True, device=dev)
            finally:
                if old is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = old

        pipe = _local_load("model3d", model, load)
        self.ctl.note("Gerando o modelo 3D localmente (Hunyuan3D-2)…")
        gen = torch.Generator("cpu").manual_seed(int(seed) if seed else int(time.time() * 1000) % (2 ** 31))
        res = pipe(image=pil, num_inference_steps=int(extra.get("steps", 30)), octree_resolution=int(extra.get("octree_resolution", 256)), generator=gen, output_type="trimesh")
        m = res[0] if isinstance(res, (list, tuple)) else res
        return mesh3d.as_lists(m.vertices, m.faces)

    def _with_speed(self, media: Media, speed: float) -> Media:
        """A velocidade do nó Voz nos modelos locais (v0.68; antes só a voz de demonstração a usava): muda o ritmo sem mudar o tom (`atempo` do ffmpeg, de 0,5× a 2×). Sem ffmpeg, a fala fica na velocidade do modelo."""
        try:
            sp = float(speed)
        except (TypeError, ValueError):
            return media
        if abs(sp - 1.0) < 0.02:
            return media
        out = proc.change_tempo(media.data, max(0.5, min(2.0, sp)))
        if out is None:
            self.ctl.note("Sem o ffmpeg a velocidade da voz não muda (instale o ffmpeg para usá-la com modelos locais).")
            return media
        return Media(out, "audio/wav")

    def _expect(self, cap: str, model: str) -> None:
        """Modelo de outro tipo no campo errado (o Whisper como voz…): mensagem clara em vez de um erro da biblioteca no meio do caminho (v0.67)."""
        from . import modelkind

        why = modelkind.mismatch(cap, model)
        if why:
            raise ProviderError(why)

    def sound(self, prompt, *, kind="sfx", duration=5, model="", extra=None, seed=0):
        model = self._pick("sound", model, "facebook/musicgen-small")
        self._expect("sound", model)
        from . import soundmodels

        if soundmodels.uses_diffusers(model):   # v0.68: AudioLDM/AudioLDM2/MusicLDM e Stable Audio (Open e 3) pelo diffusers
            return self._sound_diffusers(prompt, duration, model, extra, seed)
        (tf,) = _local_import("transformers")
        ready = self._ready(model)
        pipe = _local_load("sound", model, lambda: _hf_pipeline(tf, "text-to-audio", model, ready["dtype"]))
        if duration > 30:
            self.ctl.note("Os modelos de som locais geram até 30 s de uma vez: o resultado terá 30 s (use «Repetir áudio» ou o Editor para alongar).")
        self.ctl.note("Gerando som localmente…")
        res = pipe(prompt, forward_params={"do_sample": True, "max_new_tokens": int(max(1, min(30, duration)) * 50), **(extra or {})})
        return Media(_wav_from_array(res["audio"], res["sampling_rate"]), "audio/wav")

    def _sound_diffusers(self, prompt: str, duration: float, model: str, extra: Optional[Dict[str, Any]], seed: int) -> Media:
        """Sons e músicas pelos pipelines de áudio do diffusers (AudioLDM, AudioLDM2, MusicLDM, Stable Audio Open e 3): `DiffusionPipeline` lê o `model_index.json` do repositório e devolve a classe certa."""
        from . import soundmodels

        (diffusers,) = _local_import("diffusers")
        (torch,) = _local_import("torch")
        ready = self._ready(model)
        dev = "cuda" if torch.cuda.is_available() and _perf.device() != "cpu" else "cpu"
        if dev == "cuda":
            _pick_cuda(torch)

        def load() -> Any:
            old = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"   # nada é baixado em silêncio
            try:
                return diffusers.DiffusionPipeline.from_pretrained(model, torch_dtype=ready["dtype"], local_files_only=True).to(dev)
            finally:
                if old is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = old

        pipe = _local_load("sound", model, load)
        note = soundmodels.limit_note(model, float(duration))
        if note:
            self.ctl.note(note)
        self.ctl.note("Gerando som localmente (diffusers)…")
        gen = torch.Generator("cpu").manual_seed(int(seed) if seed else int(time.time() * 1000) % (2 ** 31))
        out = pipe(prompt, generator=gen, **soundmodels.call_kwargs(type(pipe).__name__, float(duration), extra))
        audio = out.audios[0]
        arr = audio.detach().cpu().float().numpy() if hasattr(audio, "detach") else audio
        rate = soundmodels.sampling_rate(pipe)
        if not rate:
            raise ProviderError(f'Não achei a taxa de amostragem do áudio de «{model}» (o pipeline {type(pipe).__name__} não tem vae/vocoder com «sampling_rate»).')
        return Media(_wav_from_array(arr, rate), "audio/wav")

    def _voice_orpheus(self, text: str, voice: str, model: str, extra: Optional[Dict[str, Any]], description: str = "") -> Media:
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
        if dev == "cuda":
            _pick_cuda(torch)

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
        from . import voicestyle

        prompt = f"{voicestyle.orpheus_voice(voice, description)}: {text}"
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
        if dev == "cuda":
            _pick_cuda(torch)

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

    def _reference_wav(self, reference: Any, tmp: Path, keep_all: bool) -> Path:
        """O áudio de referência como WAV mono de 16 kHz num arquivo (um vídeo vira o áudio dele). Sem texto da referência, só os primeiros 30 s valem: referência longa demora e não melhora a clonagem."""
        data, mime = reference
        src = tmp / ("ref." + (MIME_EXT.get(mime, "") or "bin"))
        src.write_bytes(data)
        ff = proc.ffmpeg_path()
        if not ff:
            if mime in ("audio/wav", "audio/x-wav", "audio/wave"):
                return src
            raise ProviderError("Usar uma voz de referência precisa do ffmpeg (para ler o áudio ou o vídeo). Instale-o, ou use um áudio em WAV.")
        dst = tmp / "ref16k.wav"
        cmd = [ff, "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", *([] if keep_all else ["-t", f"{voxcpm.MAX_REFERENCE_SECONDS:g}"]), str(dst)]
        r = subprocess.run(cmd, capture_output=True, timeout=300)
        if r.returncode != 0 or not dst.exists():
            raise ProviderError("Não consegui ler o áudio de referência (o arquivo está corrompido ou não tem som).")
        return dst

    def _complete_voxcpm_download(self, model: str) -> None:
        """Um VoxCPM baixado antes da v0.71 não tem o codec de áudio (`audiovae.pth`, ≈ 377 MB) e não carrega («AudioVAE checkpoint not found»). Só esse arquivo é baixado agora — com um aviso no nó, do mesmo
        repositório que o usuário já escolheu — e, sem rede, o erro diz como resolver."""
        from . import localmodels as lm

        snap = lm._snapshot(model)
        if not voxcpm.missing_codec(snap):
            return
        self.ctl.note(f"O modelo {model} foi baixado sem o codec de áudio ({voxcpm.CODEC_DOWNLOAD}, ≈ {voxcpm.CODEC_MB} MB; downloads antes da v0.71 o pulavam): baixando só esse arquivo agora…")
        try:
            lm.fetch_files(model, [voxcpm.CODEC_DOWNLOAD])
        except ProviderError as exc:
            raise ProviderError(f"O modelo {model} está sem o codec de áudio ({voxcpm.CODEC_DOWNLOAD}) e não consegui baixá-lo agora ({exc}). Baixe o modelo de novo em Configuração → Mídia (só esse arquivo falta) "
                                f"ou coloque o {voxcpm.CODEC_DOWNLOAD} na pasta {snap}.") from None
        if voxcpm.missing_codec(lm._snapshot(model)):
            raise ProviderError(f"O repositório {model} não trouxe o codec de áudio ({voxcpm.CODEC_DOWNLOAD}). Baixe o modelo de novo em Configuração → Mídia.")

    def _voice_voxcpm(self, text: str, model: str, extra: Optional[Dict[str, Any]], instructions: str, reference: Any = None, reference_text: str = "") -> Media:
        """VoxCPM / VoxCPM2 (openbmb/VoxCPM2): fala em 30 idiomas, «design de voz» pela descrição, clonagem controlável (áudio de referência) e clonagem fiel (referência + o texto dela). Saída em 48 kHz."""
        (np,) = _local_import("numpy")
        (torch,) = _local_import("torch")
        if sys.version_info < (3, 10):
            raise ProviderError(f"A biblioteca voxcpm precisa do Python 3.10 ou mais novo (este é o {sys.version_info[0]}.{sys.version_info[1]}). Instale um Python mais novo e rode o instalador do OpenFlow de novo.")
        try:
            vox = __import__("voxcpm", fromlist=["_"])
        except ImportError as exc:
            if exc.name and exc.name.split(".")[0] != "voxcpm":   # a biblioteca está instalada, mas falta (ou quebrou) uma dependência dela
                raise ProviderError(f'A biblioteca voxcpm está instalada, mas falta a dependência «{exc.name}». Reinstale:  pip install -U voxcpm  (ou rode: flow libs --extras voxcpm).') from None
            raise ProviderError('O VoxCPM precisa da biblioteca "voxcpm" (Python 3.10 ou mais novo):  pip install voxcpm  (ou rode: flow libs --extras voxcpm).') from None
        self._ready(model)
        self._complete_voxcpm_download(model)
        dev, _ = _device()

        def load() -> Any:
            old = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"   # nada é baixado em silêncio
            try:
                try:
                    return vox.VoxCPM.from_pretrained(model, load_denoiser=False, local_files_only=True, optimize=False, device=dev)
                except ProviderError:
                    raise
                except Exception as exc:  # noqa: BLE001 — o erro cru da biblioteca («AudioVAE checkpoint not found…») não diz o que fazer
                    raise ProviderError(f"O VoxCPM não conseguiu carregar «{model}»: {type(exc).__name__}: {str(exc)[:300]}. Se o modelo foi baixado incompleto, baixe-o de novo em Configuração → Mídia.") from None
            finally:
                if old is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = old

        engine = _local_load("voice", model, load)
        opts = voxcpm.options(extra)
        use_ref = reference is not None and voxcpm.supports_reference(model)
        if reference is not None and not use_ref:
            self.ctl.note(f"«{model}» não clona voz (só o VoxCPM2 aceita áudio de referência): ignorei a referência.")
        ultimate = use_ref and bool((reference_text or "").strip())
        if ultimate and instructions.strip():
            self.ctl.note("Na clonagem fiel (referência + texto da referência) o modelo não lê a descrição da voz: ignorei a descrição.")
        chunks = voxcpm.split_text(text)
        if not chunks:
            raise ProviderError("O VoxCPM precisa de um texto para falar.")
        rate = int(getattr(engine.tts_model, "sample_rate", 0) or 48000)
        parts: List[Any] = []
        with tempfile.TemporaryDirectory() as td:
            ref_path = self._reference_wav(reference, Path(td), keep_all=ultimate) if use_ref else None
            self.ctl.note("Sintetizando voz com o VoxCPM (local)" + (" — clonando a voz de referência…" if use_ref else "…"))
            for i, chunk in enumerate(chunks):
                kw: Dict[str, Any] = dict(opts)
                if use_ref:
                    kw["reference_wav_path"] = str(ref_path)
                    if ultimate:
                        kw.update(prompt_wav_path=str(ref_path), prompt_text=reference_text.strip())
                line = chunk if ultimate else voxcpm.with_description(chunk, instructions)
                try:
                    with torch.no_grad():
                        wav = engine.generate(text=line, **kw)
                except ProviderError:
                    raise
                except Exception as exc:  # noqa: BLE001 — a mensagem da biblioteca é o que ajuda a achar o problema (memória, versão…)
                    raise ProviderError(f"O VoxCPM não conseguiu gerar a voz: {type(exc).__name__}: {str(exc)[:300]}") from None
                arr = wav.detach().cpu().float().numpy() if hasattr(wav, "detach") else np.asarray(wav, dtype="float32")
                parts.append(np.squeeze(arr))
                if i + 1 < len(chunks):
                    parts.append(np.zeros(int(voxcpm.SILENCE_SECONDS * rate), dtype="float32"))
        return Media(_wav_from_array(np.concatenate(parts), rate), "audio/wav")

    def clones_voice(self, model=""):
        return voxcpm.supports_reference(self.model_for("voice", model) or model)

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions="", reference=None, reference_text=""):
        model = self._pick("voice", model, "suno/bark-small")
        self._expect("voice", model)
        if voxcpm.is_voxcpm(model):
            return self._with_speed(self._voice_voxcpm(text, model, extra, instructions, reference, reference_text), speed)
        if re.search(r"orpheus", model, re.I):
            return self._with_speed(self._voice_orpheus(text, voice, model, extra, instructions), speed)
        if re.search(r"(^|/)csm-1b", model, re.I):
            return self._with_speed(self._voice_csm(text, voice, model, extra), speed)
        (tf,) = _local_import("transformers")
        ready = self._ready(model)
        pipe = _local_load("voice", model, lambda: _hf_pipeline(tf, "text-to-speech", model, ready["dtype"]))
        self.ctl.note("Sintetizando voz localmente…")
        res = pipe(text, **(extra or {}))
        return self._with_speed(Media(_wav_from_array(res["audio"], res["sampling_rate"]), "audio/wav"), speed)

    def voice_style_note(self, model=""):
        if voxcpm.is_voxcpm(self.model_for("voice", model) or model):
            return ""   # o VoxCPM lê a descrição inteira («Design de voz»)
        if re.search(r"orpheus", self.model_for("voice", model) or model or "", re.I):
            return "O Orpheus só usa da descrição da voz o gênero (feminina ou masculina), para escolher uma das vozes dele quando o campo «Voz» está vazio; o resto da descrição foi ignorado."
        return super().voice_style_note(self.model_for("voice", model) or model)

    def _asr(self, data, filename, mime, language, model, long_audio=False):
        model = self._pick("stt", model, "openai/whisper-small")
        self._expect("stt", model)
        (tf,) = _local_import("transformers")
        ready = self._ready(model)
        pipe = _local_load("stt", model, lambda: _hf_pipeline(tf, "automatic-speech-recognition", model, ready["dtype"]))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ("audio." + (MIME_EXT.get(mime, "") or (filename.rsplit(".", 1)[-1] if "." in filename else "wav")))
            p.write_bytes(data)
            kw: Dict[str, Any] = {"return_timestamps": True}
            if long_audio:
                kw["chunk_length_s"] = 30   # áudio mais longo que 30 s: o Whisper o lê em janelas (os tempos de cada trecho continuam corretos)
            if language and language != "auto":
                kw["generate_kwargs"] = {"language": language.split("-")[0]}
            return pipe(str(p), **kw)

    def transcribe(self, data, filename, mime, *, language="", model=""):
        from . import subtitles as sub

        return sub.collapse_loops(str(self._asr(data, filename, mime, language, model).get("text", "")))

    def transcribe_segments(self, data, filename, mime, *, language="", model="", duration=0.0):
        from . import subtitles as sub

        res = self._asr(data, filename, mime, language, model, long_audio=True)
        segs = sub.segments_from_chunks(res.get("chunks") or [], float(duration or 0.0))
        text = sub.collapse_loops(str(res.get("text", "")))
        return segs or ([sub.seg(0.0, float(duration or 3.0), text)] if text else [])

    def timed_segments(self, model=""):
        return True

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        """Vídeo local exige GPU com bastante memória. Os quadros viram MP4 pelo ffmpeg."""
        model = self._pick("video", model, "Lightricks/LTX-Video")
        (diffusers,) = _local_import("diffusers")
        ff = proc.ffmpeg_path()
        if not ff:
            raise ProviderError("O vídeo local precisa do ffmpeg para montar o arquivo (instale-o).")
        dev, _ = _device()
        ready = self._ready(model, quantizes=True)
        vkw = {"torch_dtype": ready["dtype"], "local_files_only": True, **({"variant": ready["variant"]} if ready["variant"] else {}), **self._quant_kw(model, ready, diffusers)}
        pipe = _local_load("video", model, lambda: _slim(_load_pipeline(lambda **k: diffusers.DiffusionPipeline.from_pretrained(model, **k), vkw, self.ctl.note), dev))
        w, h = size_of_aspect(aspect, long_side or (704 if dev != "cpu" else 384))
        w, h = w // 32 * 32 or 32, h // 32 * 32 or 32
        fps = 24
        params = lowmem.params_of(pipe)
        if image and not lowmem.accepted(params, "image"):   # o repositório do LTX-Video traz o pipeline de texto → vídeo, mas os mesmos pesos fazem imagem → vídeo: monta o pipeline de imagem (compartilha os pesos, sem recarregar)
            i2v = {"LTXPipeline": "LTXImageToVideoPipeline"}.get(type(pipe).__name__)
            cls = getattr(diffusers, i2v, None) if i2v else None
            if cls is not None:
                try:
                    pipe = cls.from_pipe(pipe)
                    params = lowmem.params_of(pipe)
                except Exception:  # noqa: BLE001
                    pass
        if image and not lowmem.accepted(params, "image"):   # v0.72: um modelo só de texto → vídeo recebia `image=` e quebrava com um TypeError no meio da geração
            raise ProviderError(f"«{model}» só gera vídeo a partir de texto (o pipeline dele não aceita uma imagem). Desligue a imagem do nó ou escolha um modelo de imagem → vídeo (ex.: um LTX-Video ou Wan «i2v»).")
        kw: Dict[str, Any] = {"prompt": prompt, "width": w, "height": h, "num_frames": int(max(9, min(161, duration * fps)) // 8 * 8 + 1)}
        if image:
            kw["image"] = cover_fit(open_rgb(image[0]), w, h)
        if params is not None and "frame_rate" in params:
            kw["frame_rate"] = fps   # LTX: o pipeline assume 25 quadros por segundo; o MP4 sai a 24, então diz a taxa real (senão o movimento fica ~4% mais lento)
        kw = lowmem.keep(kw, params)
        if lowmem.explicit(params, "callback_on_step_end"):   # progresso e cancelamento a cada passo (um vídeo leva muitos minutos numa máquina fraca)
            kw["callback_on_step_end"] = lowmem.step_progress(self.ctl, int((extra or {}).get("num_inference_steps") or lowmem.default_of(pipe, "num_inference_steps") or 0), "Gerando vídeo")
        kw.update(extra or {})
        (torch,) = _local_import("torch")
        self.ctl.note("Gerando vídeo localmente (pode demorar)…")
        tries = 0
        while True:
            try:
                with lowmem.heartbeat(self.ctl, "Ainda gerando o vídeo (a decodificação final também demora)"):
                    frames = pipe(**kw).frames[0]
                break
            except Exception as exc:  # noqa: BLE001
                kind = lowmem.oom_kind(exc)
                if not kind:
                    raise
                gc.collect()
                try:
                    if dev == "cuda":
                        torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass
                tries += 1
                if tries > 3:
                    raise ProviderError(lowmem.friendly_oom(kind, model, int(kw.get("width") or 0), int(kw.get("height") or 0), tries - 1)) from None
                if tries == 1 and kind == "gpu" and dev == "cuda":
                    self._lighten(pipe)
                    continue
                frames_now = int(kw.get("num_frames") or 0)
                if frames_now > 25:   # menos quadros: o vídeo fica mais curto, mas cabe
                    kw["num_frames"] = max(9, (frames_now // 2) // 8 * 8 + 1)
                    self.ctl.note(f"Faltou memória: tentando de novo com {kw['num_frames']} quadros (o vídeo fica mais curto)…")
                elif kw.get("width") and (nxt := lowmem.shrink(int(kw["width"]), int(kw["height"]), 0.75, 256, 32)):
                    kw["width"], kw["height"] = nxt
                    if kw.get("image") is not None:
                        kw["image"] = kw["image"].resize(nxt)
                    self.ctl.note(f"Faltou memória: tentando de novo em {nxt[0]}×{nxt[1]}…")
                else:
                    raise ProviderError(lowmem.friendly_oom(kind, model, int(kw.get("width") or 0), int(kw.get("height") or 0), tries - 1)) from None
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


def open_rgb(data: bytes, keep_alpha: bool = False) -> Any:
    """Imagem de entrada como RGB da PIL, do jeito que a pessoa a vê (v0.51). `.convert("RGB")` direto errava em três casos comuns: fotos de celular saíam deitadas (ignora a orientação EXIF),
    o que era transparente virava a cor escondida por baixo (em geral preto) e PNG de 16 bits saía todo branco. Aqui: gira pelo EXIF, compõe sobre branco e reduz 16 bits para 8."""
    from PIL import Image, ImageOps  # type: ignore

    im = Image.open(io.BytesIO(data))
    try:
        im = ImageOps.exif_transpose(im) or im
    except Exception:  # noqa: BLE001 — EXIF malformado: segue sem girar
        pass
    if im.mode in ("I;16", "I;16L", "I;16B", "I"):
        im = im.point(lambda v: v / 256.0, "L") if im.mode != "I" else im.point(lambda v: v / 256.0).convert("L")
    elif im.mode == "F":
        im = im.point(lambda v: v * 255.0).convert("L")
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        if keep_alpha and rgba.getchannel("A").getextrema()[0] < 255:   # modelos 3D (TripoSR, Hunyuan3D) usam a transparência para separar o objeto do fundo
            return rgba
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        return bg.convert("RGB")
    return im.convert("RGB")


def clean_png(data: bytes) -> bytes:
    """Os bytes da imagem prontos para um programa que não olha EXIF/alfa (sd-cli): se já é uma imagem comum, devolve como veio; senão, um PNG normalizado."""
    try:
        from PIL import Image  # type: ignore

        im = Image.open(io.BytesIO(data))
        plain = im.mode in ("RGB", "L") and not im.info.get("transparency") and (im.getexif().get(0x0112, 1) in (0, 1))
        if plain and im.format in ("PNG", "JPEG"):
            return data
        out = io.BytesIO()
        open_rgb(data).save(out, "PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001 — não é imagem legível: o programa dá a mensagem dele
        return data


_WEIGHT_LABELS = {"diffusion_model_path": "modelo", "model_path": "modelo", "llm_path": "codificador de texto", "llm_vision_path": "projetor de visão", "vae_path": "VAE", "t5xxl_path": "codificador T5",
                  "clip_l_path": "CLIP-L", "clip_g_path": "CLIP-G", "clip_vision_path": "CLIP vision", "tokenizer_path": "tokenizador"}


def _memory_hint(kw: Dict[str, Any], n_refs: int, stage: str) -> str:
    """Complemento da mensagem de «falta de memória» (v0.57): quanto os arquivos carregados somam, quanto o computador tem, em que etapa acabou e o que fazer (em vez de só «use uma resolução ou quantização menores»)."""
    parts = []
    for k, label in _WEIGHT_LABELS.items():
        v = kw.get(k)
        if isinstance(v, str) and v:
            try:
                parts.append((label, os.path.getsize(v) / 1e9))
            except OSError:
                continue
    total = sum(g for _, g in parts)
    out = f" Os arquivos carregados somam ≈ {total:.1f} GB ({', '.join(f'{lb} {g:.1f}' for lb, g in parts)})" if parts else ""
    try:
        info = _native.sys_info() or {}
        if info.get("ram_total"):
            out += f" e o computador tem ≈ {info['ram_total'] / 2 ** 30:.0f} GB de RAM ({(info.get('ram_avail') or 0) / 2 ** 30:.0f} GB livres agora)"
    except Exception:  # noqa: BLE001 — só informação
        pass
    out += "." if out else ""
    if stage == "weights":
        out += " Acabou ao CARREGAR os pesos, então baixar a resolução não resolve. "
    elif stage == "sampling":
        out += " Acabou durante a geração, mesmo depois de uma segunda tentativa em resolução menor. "
    else:
        out += " "
    tips = []
    if n_refs and kw.get("llm_vision_path"):
        tips.append("tire as imagens de referência (o projetor de visão só é carregado com elas)")
    tips.append("use um codificador de texto menor (ex.: Qwen3-VL-8B Q3_K_XL ou Q2_K_XL — informe o arquivo em «extra» do nó: {\"load\": {\"llm_path\": \"arquivo.gguf\"}}) ou uma quantização menor do modelo (Q3/Q2)")
    tips.append("feche outros programas")
    return out + "Para liberar memória: " + "; ".join(tips) + "."


def _pil_refs(refs: Sequence[Ref], limit: int = 4, keep_alpha: bool = False) -> List[Any]:
    """Imagens de referência (bytes, mime) como imagens RGB da PIL (como a pessoa as vê: ver `open_rgb`); as ilegíveis são ignoradas."""
    __import__("PIL")   # sem a Pillow, falha logo aqui (e não vira «formato não suportado»)

    out: List[Any] = []
    for data, _mime in list(refs)[:limit]:
        try:
            out.append(open_rgb(data, keep_alpha))
        except Exception:  # noqa: BLE001 — arquivo que não é imagem
            continue
    return out


def h3_picture_prompt(prompt: str, n: int) -> str:
    """MiniMax H3 Image: as imagens de referência (`-r`) são `<Picture 1>`, `<Picture 2>`… no prompt. Se o prompt já as cita, fica como está; senão o OpenFlow acrescenta a convenção do cartão:
    com uma referência «Edit <Picture 1>. …», com várias lista todas antes do pedido."""
    if n <= 0:
        return prompt
    # v0.86: o OpenFlow marca as imagens citadas com «@apelido (reference image N)» e, no modo Editar, abre com «Edit the provided reference image.»: o H3 só entende <Picture N>
    prompt = re.sub(r"\(reference image (\d+)(?:,[^)]*)?\)", lambda m: f"<Picture {m.group(1)}>", prompt or "")
    prompt = re.sub(r"^Edit the provided reference image\.", "Edit <Picture 1>." if n == 1 else "Edit the reference images.", prompt)
    if re.search(r"<Picture\s*\d+>", prompt):
        return prompt
    if n == 1:
        return "Edit <Picture 1>. " + prompt
    return "Reference images: " + ", ".join(f"<Picture {i}>" for i in range(1, n + 1)) + ". " + prompt


def _max_side() -> int:
    """Maior lado, em pixels, que os modelos locais (GGUF) geram: 2048 por padrão; `OPENFLOW_MAX_SIDE` muda (512 a 4096). Tamanhos grandes pedem muita RAM/VRAM e tempo."""
    try:
        return max(512, min(int(os.environ.get("OPENFLOW_MAX_SIDE", "2048")), 4096))
    except ValueError:
        return 2048


def image_difference(a: bytes, b: bytes) -> Optional[float]:
    """Quanto duas imagens diferem (0 = iguais, 1 = opostas): diferença média de brilho depois de reduzir as duas a 64×64. None se não dá para calcular (sem a Pillow ou formato ilegível)."""
    try:
        def small(data: bytes) -> Any:
            return open_rgb(data).convert("L").resize((64, 64))

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


def cover_fit(img: Any, w: int, h: int) -> Any:
    """A imagem no tamanho w×h SEM esticar (v0.86): reduz até cobrir o quadro e corta o excesso do centro. `resize((w, h))` deformava a imagem inicial quando a proporção dela não era a do vídeo
    (ex.: uma imagem quadrada gerada virando vídeo 16:9: o rosto saía achatado)."""
    from PIL import Image  # type: ignore

    iw, ih = img.size
    if (iw, ih) == (w, h):
        return img
    k = max(w / iw, h / ih)
    nw, nh = max(w, int(round(iw * k))), max(h, int(round(ih * k)))
    big = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return big.crop((left, top, left + w, top + h))


def fit_inside(img: Any, w: int, h: int, mult: int = 16) -> Any:
    """A imagem cabendo DENTRO de w×h, com a proporção dela (lados em múltiplos de `mult`): referências de edição com várias imagens não devem ser esticadas nem cortadas."""
    from PIL import Image  # type: ignore

    iw, ih = img.size
    k = min(w / iw, h / ih)
    nw, nh = max(mult, int(iw * k) // mult * mult), max(mult, int(ih * k) // mult * mult)
    return img if (nw, nh) == (iw, ih) else img.resize((nw, nh), Image.LANCZOS)


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


_NEWER_THAN_LIB = re.compile(r"flux[-_. ]?3|moss[-_ ]?image|minimax[-_ ]?h3", re.I)


def _lib_is_stale() -> bool:
    """A biblioteca instalada é a do PyPI (0.4.7 ou mais velha)? Se o `flow update`/`flow libs` compilou a do GitHub (marcador `sd_built_sha`) ou a versão é mais nova, ela pode conhecer os modelos novos."""
    try:
        from ..util import flow_home

        if (flow_home() / "sd_built_sha").is_file():
            return False
    except OSError:
        pass
    try:
        from importlib import metadata

        ver = tuple(int(x) for x in re.findall(r"\d+", metadata.version("stable-diffusion-cpp-python"))[:3])
        return ver <= (0, 4, 7)
    except Exception:  # noqa: BLE001 — sem metadados: trata como a do PyPI
        return True


def _lib_never_knows(name: str) -> bool:
    """Famílias novas que a biblioteca do PyPI (a 0.4.7, parada) nunca reconheceu (FLUX.3): vão direto ao sd-cli, sem nem tentar carregar na biblioteca (que fecha com «código -11»). Com a biblioteca do GitHub
    (compilada pelo `flow update`), vale tentar a própria biblioteca. `OPENFLOW_SD_INPROC=1` força a biblioteca."""
    return bool(_NEWER_THAN_LIB.search(name)) and os.environ.get("OPENFLOW_SD_INPROC", "") in ("", "0") and _lib_is_stale()


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
        env = _perf.gpu_env({**os.environ, "PYTHONPATH": root + os.pathsep + os.environ.get("PYTHONPATH", "")})   # várias placas: o processo da stable-diffusion.cpp usa a escolhida
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


def _lib_accepts(sdc: Any, key: str) -> bool:
    """O construtor `StableDiffusion` da biblioteca aceita o parâmetro `key`? (Verdadeiro se a assinatura não puder ser lida.)"""
    import inspect

    try:
        params = inspect.signature(sdc.StableDiffusion.__init__).parameters
    except (TypeError, ValueError, AttributeError):
        return True
    return key in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


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
        if _H3_IMAGE.search(name):
            return 16   # MiniMax H3 Image: até 16 referências
        if re.search(r"flux[-_. ]?3", name, re.I):
            return 10
        return 4 if _GGUF_MULTI_REF.search(name) else 1   # os demais modelos usam só uma imagem de partida

    def frames_edit_for(self, model: str = "") -> bool:
        name = Path(self.model_for("image", model) or model or "").name
        return bool(_GGUF_MULTI_REF.search(name) or re.search(r"flux[-_. ]?3", name, re.I) or _H3_IMAGE.search(name))

    def refs_need_edit(self, model: str = "") -> bool:
        name = Path(self.model_for("image", model) or model or "").name
        return not (_GGUF_MULTI_REF.search(name) or re.search(r"flux[-_. ]?3", name, re.I) or _H3_IMAGE.search(name))

    def _path(self, cap: str, model: str) -> Path:
        name = Path(self.model_for(cap, model)).name
        if not name:
            raise ProviderError(f"Escolha um modelo GGUF de {CAP_LABELS[cap]} em Configuração → Modelos locais ({'Imagem' if cap == 'image' else 'Vídeo'}).")
        path = Path(self.cfg.get("models_dir") or ".") / cap / name
        if not path.is_file():
            raise ProviderError(f"Modelo GGUF não encontrado: {path}. Baixe-o pela barra de pesquisa de modelos do Canvas.")
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

    def _with_quant(self, load: Dict[str, Any], path: Path, want: Any) -> Dict[str, Any]:
        """O campo «quant» do nó (Q2…Q8, v0.81): usa o arquivo numa faixa MENOR que a dele, pedindo à stable-diffusion.cpp que recomprima os pesos ao carregar (`wtype`/`--type`)."""
        from .. import hf as _hf

        tier = quants.wanted(want)
        if str(want or "").strip() and not tier:
            self.ctl.note(f"«quant: {want}» não é uma faixa conhecida (use Q2, Q3, Q4, Q6 ou Q8): ignorei.")
            return load
        load, note = quants.with_weight_type(load, _hf.parse_quant(path.name).get("quant", ""), tier)
        if note:
            self.ctl.note(note)
        return load

    def _with_support_tier(self, load: Dict[str, Any], path: Path, want: Any) -> Dict[str, Any]:
        """O campo «Faixa dos arquivos de apoio» do nó (Q2…Q8, v0.89): usa o codificador de texto e o VAE na faixa pedida, se ela já está na pasta (senão avisa como instalar e usa o arquivo como está)."""
        from . import support_tiers

        tier = quants.wanted(want)
        if str(want or "").strip() and not tier:
            self.ctl.note(f"«support_quant: {want}» não é uma faixa conhecida (use Q2, Q3, Q4, Q6 ou Q8): ignorei.")
            return load
        load, notes = support_tiers.swap_tier(path.parent, load, tier)
        for n in notes:
            self.ctl.note(n)
        return load

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
        self._cli_error = ""
        self._cli_tools_missing = False
        if (sdcli.find() is None or sdcli.installed_backend() not in ("", sdcli.backend())) and os.environ.get("OPENFLOW_SD_CLI_AUTO", "1") not in ("0", "no", "false"):   # sem sd-cli, ou o instalado é de outro tipo (CPU/GPU) que o escolhido nas configurações
            self.ctl.note("A stable-diffusion.cpp da biblioteca não reconhece este modelo: baixando o sd-cli pronto (a versão mais nova, sem compilar)…")
            try:
                sdcli.install(lambda done, total: self.ctl.note(f"Baixando o sd-cli ({sdcli.backend()})… {int(100 * done / total)}%") if total else None, self._cancelled, self.ctl.note)
                _media_unload()
            except ProviderError as err:
                if str(err) == "cancelado":
                    self.ctl.check()
                self._cli_error = str(err)
                self._cli_tools_missing = isinstance(err, sdcli.BuildToolsMissing)
                self.ctl.note(f"Não consegui baixar o sd-cli sozinho ({str(err)[:160]}).")
        return sdcli.find() is not None

    @staticmethod
    def _layout_error(path: Path) -> ProviderError:
        """O sd-cli (atual) recusou o arquivo («get sd version from file failed»): o formato dos tensores não é o que a stable-diffusion.cpp conhece (GGUF feito para ComfyUI/diffusers). Diz qual repositório serve."""
        nat = support.sd_native_for(path.name)
        if nat:
            return ProviderError(
                f"A stable-diffusion.cpp não reconhece o formato deste arquivo ({path.name}): ele é uma versão para o ComfyUI/diffusers (tensores com os nomes do checkpoint original), não a convertida para a "
                f"stable-diffusion.cpp. Baixe a do repositório {nat['repo']} (ex.: {nat['example']}): o VAE e o codificador de texto são os mesmos que você já tem. [[flow-sd-repo:{nat['repo']}]]")
        return ProviderError(f"A stable-diffusion.cpp não reconhece o formato do arquivo {path.name} (o nome dos tensores não é o que ela conhece). Provavelmente é um GGUF feito para o ComfyUI/diffusers: "
                             "procure a versão convertida para a stable-diffusion.cpp (os GGUF do autor dela, leejet, são os de referência) ou use outro arquivo/quantização.")

    def _no_cli_error(self, path: Path) -> ProviderError:
        """O modelo é mais novo que a biblioteca Python e não há `sd-cli` para gerá-lo: diz por quê e o que fazer, em vez de tentar a biblioteca (que fecharia com «código -11»). Faltando git/compilador, o erro
        oferece o botão que instala o que falta e compila; senão mostra o motivo do download que falhou."""
        why = (getattr(self, "_cli_error", "") or "").strip()
        if getattr(self, "_cli_tools_missing", False):
            miss = ", ".join(sdcli.build_tools_missing()) or "git e compilador C/C++"
            return ProviderError(
                f"O modelo {path.name} é mais novo que a stable-diffusion.cpp da biblioteca Python (a do PyPI, 0.4.7): ele precisa do sd-cli, que o OpenFlow compila neste computador, mas faltam: {miss}. "
                f"Use o botão abaixo (instala o que falta, pede a senha de administrador e compila; leva alguns minutos) ou rode  flow update  no terminal. Se preferir, instale a mão ({sdcli.build_tools_hint()}) "
                "ou aponte OPENFLOW_SD_CLI para um sd-cli seu. [[flow-sd-tools]]")
        retry = "" if re.search(r"glibc|executável pronto", why, re.I) else " [[flow-sd-cli]]"   # com glibc antiga o botão falharia de novo
        return ProviderError(
            f"O modelo {path.name} é mais novo que a stable-diffusion.cpp da biblioteca Python (a do PyPI, 0.4.7) e o OpenFlow não conseguiu o executável pronto (sd-cli) para gerá-lo"
            + (f": {why[:300]}" if why else "") + ". "
            "Soluções: rode  flow update  (ele compila a stable-diffusion.cpp mais nova do GitHub: precisa de git e de um compilador C/C++), aponte OPENFLOW_SD_CLI para um sd-cli seu, ou use outro modelo." + retry)

    def _cli_call(self, path: Path, fn: Callable[[Path], Any]) -> Any:
        """Roda `fn(sd-cli)`. Se o executável não roda neste Linux (glibc antiga), o OpenFlow o apaga, baixa o pacote compatível e tenta mais uma vez, sem pedir que a pessoa gere de novo."""
        cli = sdcli.find()
        assert cli is not None
        try:
            return fn(cli)
        except sdcli.GlibcError as exc:
            self.ctl.note(str(exc)[:200] + " Baixando o pacote compatível…")
            if not self._cli_fallback(_SDUnsupportedModel(path.name)):
                raise
            cli = sdcli.find()
            if cli is None:
                raise
            return fn(cli)

    def _engine(self, cap: str, path: Path, load: Dict[str, Any]) -> Any:
        (sdc,) = _local_import("stable_diffusion_cpp", extra="local")
        _install_sd_log(sdc)   # guarda as mensagens da stable-diffusion.cpp: quando a geração falha com «NULL pointer access», o motivo de verdade está nelas
        kw = self._load_kwargs(path, load)
        if kw.get("qwen_image_zero_cond_t") and not _lib_accepts(sdc, "qwen_image_zero_cond_t"):   # biblioteca antiga: sem a opção o 2511 edita mal — o sd-cli (que a tem) assume, em vez de rodar errado em silêncio
            raise _SDUnsupportedModel(f"A stable-diffusion-cpp-python instalada não tem a opção qwen_image_zero_cond_t, que o {path.name} exige para editar imagens. Atualize a biblioteca (flow libs) ou use o botão «Baixar o executável pronto» (sd-cli). [[flow-sd-cli]] [[flow-sd-update]]")
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
        mult = 32 if _H3_IMAGE.search(path.name) else 16   # MiniMax H3 Image: cada token cobre 32×32 pixels
        w, h = max(256, int(w * k) // mult * mult), max(256, int(h * k) // mult * mult)
        pil = _pil_refs(refs, self.max_refs(path.name)) if refs else []   # o limite é o do modelo escolhido NO NÓ (antes valia o do modelo padrão das configurações)
        if refs and not pil:
            raise ProviderError("Não consegui ler as imagens de referência ligadas ao nó (formato não suportado).")
        ref_png: List[bytes] = []
        for im in pil:
            b = io.BytesIO()
            im.save(b, format="PNG")
            ref_png.append(b.getvalue())
        multi = bool(_GGUF_MULTI_REF.search(path.name) or re.search(r"flux[-_. ]?3", path.name, re.I) or _H3_IMAGE.search(path.name))
        if ref_png and _H3_IMAGE.search(path.name):
            prompt = h3_picture_prompt(prompt, len(ref_png))   # o MiniMax H3 Image chama as referências de <Picture 1>, <Picture 2>… no prompt
        if len(pil) == 1 and self.edit_mode:
            w, h = _size_like(pil[0], w, h, mult)
        run_p = {k2: v for k2, v in extra.items() if k2 not in ("load",)}
        out: List[Media] = []
        self.ctl.note(f"A stable-diffusion-cpp-python não reconhece este modelo: gerando pelo sd-cli ({cli.name}).")
        for i in range(max(1, count)):
            self.ctl.check()
            try:
                gw, gh = w, h
                for attempt in (0, 1):
                    try:
                        data, warns = self._cli_call(path, lambda c: sdcli.generate_image(c, kw, run_p, prompt=prompt, width=gw, height=gh, seed=int(seed + i) if seed else int(time.time() * 1000) % (2 ** 31) + i, negative=negative,
                                                                                          refs=ref_png if multi else [], init=None if multi or not ref_png else ref_png[0], cancelled=self._cancelled, note=self.ctl.note))
                        break
                    except sdcli.OutOfMemory as oom:
                        if attempt == 0 and oom.stage == "sampling" and min(gw, gh) > 256:   # a memória acabou NOS PASSOS (a resolução pesa): uma segunda tentativa, em resolução menor (v0.57)
                            gw, gh = max(256, int(gw * 0.7) // mult * mult), max(256, int(gh * 0.7) // mult * mult)
                            self.ctl.note(f"Faltou memória ao gerar: tentando de novo em {gw}×{gh}…")
                            continue
                        raise ProviderError(str(oom) + _memory_hint(kw, len(ref_png), oom.stage)) from None
            except ProviderError as exc:
                if str(exc) == "cancelado":
                    self.ctl.check()   # o trabalho foi cancelado: levanta o cancelamento de verdade
                if re.search(r"requires Qwen3-VL vision weights|--llm_vision", str(exc)):   # o sd-cli pede o projetor de visão do Qwen3-VL (v0.56): explica e oferece baixar, em vez do log cru
                    raise ProviderError(f"O {(support.family_of(path.name) or {}).get('label') or 'modelo'} precisa do projetor de visão (mmproj) do Qwen3-VL para editar com imagem de referência, e o sd-cli não o recebeu. "
                                        f"Use o botão «Baixar os arquivos de apoio» no nó (≈ 1,2 GB), ou ponha na pasta {path.parent} o arquivo Qwen3-VL-8B-Instruct-mmproj-F16.gguf. [[flow-support:{path.name}]]") from None
                if "get sd version from file failed" in str(exc):   # o sd-cli atual não conhece o formato do arquivo: diz qual versão do modelo serve (em vez do log cru do sd-cli)
                    raise self._layout_error(path) from None
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
        found = support.required_found(support.find_companions(path.parent, path, fam), fam)   # o que a família marca como opcional (mmproj) não impede de carregar
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
        user_load = extra.pop("load", None) or {}
        load = {**base.get("load", {}), **user_load}
        load = self._with_quant(load, path, extra.pop("quant", ""))
        load = self._with_support_tier(load, path, extra.pop("support_quant", ""))
        if _QWEN_EDIT_2511.search(path.name):
            load.setdefault("qwen_image_zero_cond_t", True)   # v0.86 (o nó pode desligar com {"load": {"qwen_image_zero_cond_t": false}})
        fam_img = support.family_of(path.name)
        if fam_img and fam_img.get("negative_default") and not (negative or "").strip():   # a receita do modelo pede um negativo de UM espaço: negativo vazio desliga o CFG verdadeiro
            negative = fam_img["negative_default"]
        if not refs and fam_img and fam_img.get("edit_needs"):   # só gerar com texto: o projetor de visão (≈ 1,2 GB) não é carregado — ele só serve para ler imagens de referência
            load = {k: v for k, v in load.items() if k not in fam_img["edit_needs"] or k in user_load}
        if refs:   # editar (ou usar imagens de referência): a stable-diffusion.cpp exige, no Qwen-Image 2.1, o projetor de visão do Qwen3-VL — sem ele o sd-cli falha com «requires Qwen3-VL vision weights» (v0.55)
            need = [m for m in support.missing_for_edit(path.parent, path.name) if not load.get(m["key"])]
            if need:
                raise ProviderError(f"Para editar imagens, o {support.family_of(path.name)['label']} precisa de arquivos que ainda não estão aqui: {', '.join(m['label'] for m in need)} (≈ {round(sum(m['approx'] for m in need), 1)} GB). "
                                    f"Use o botão «Baixar os arquivos de apoio» no nó, ou ponha-os na pasta {path.parent}. Gerar só com texto continua funcionando sem eles. [[flow-support:{path.name}]]")
        if path.name in _SD_LITE:   # este modelo já falhou com flash attention/offload nesta máquina: começa sem eles (não recarrega duas vezes a cada imagem)
            load = {k: v for k, v in load.items() if k not in _SD_LITE_KEYS}
        if _lib_unsupported(path.name) or _lib_never_knows(path.name):   # já se sabe que a biblioteca não o reconhece
            if self._cli_fallback(_SDUnsupportedModel(path.name)):
                return self._image_cli(path, load, extra, prompt, size, count, seed, negative, refs)
            raise self._no_cli_error(path)   # sem sd-cli: não adianta carregar na biblioteca (ela recusa ou fecha com «código -11»)
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
                ref_kw["init_image"] = cover_fit(pil[0], w, h)    # demais: imagem → imagem
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
                    with lowmem.heartbeat(self.ctl, "Gerando a imagem com o modelo GGUF"):
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
        if fam and fam.get("engine") == "ltx2":   # LTX-2.x: pelo diffusers (ltx2.py), não pela stable-diffusion.cpp
            if str(extra.pop("quant", "") or "").strip():   # v0.84: a recompressão ao carregar é da stable-diffusion.cpp; o LTX-2 carrega o arquivo como ele é
                self.ctl.note("A «Quantização ao carregar» não vale para o LTX-2 (ele roda pelo diffusers): usando o arquivo como ele é. Para outra faixa, baixe ou crie o arquivo dela.")
            if str(extra.pop("support_quant", "") or "").strip():
                self.ctl.note("A «Faixa dos arquivos de apoio» não vale para o LTX-2 (os componentes vêm do repositório diffusers dele): usando os arquivos como eles são.")
            return self._video_ltx2(path, prompt, duration, aspect, image, seed, long_side, extra)
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
        vload = self._with_quant(vload, path, extra.pop("quant", ""))
        vload = self._with_support_tier(vload, path, extra.pop("support_quant", ""))
        if fam and (fam.get("video") or {}).get("container"):   # MiniMax H3…: VAE de áudio, `--backend te=cpu` e a trilha estéreo só existem no sd-cli (a biblioteca Python não os tem)
            if not self._cli_fallback(_SDUnsupportedModel(path.name)):
                raise self._no_cli_error(path)
            return self._video_cli(path, vload, extra, fam, prompt, duration, aspect, image, seed, long_side)
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
                kw["init_image"] = cover_fit(pil[0], w, h)
        kw = {"prompt": prompt, "width": w, "height": h, "seed": int(seed) if seed else -1, **kw, **extra}
        if params:   # versões da biblioteca diferem nos parâmetros: o que ela não conhece é descartado (com aviso) em vez de derrubar a geração
            dropped = [k for k in kw if k not in params]
            if dropped:
                self.ctl.note("Esta versão da stable-diffusion-cpp-python não aceita: " + ", ".join(dropped) + " (ignorados).")
                kw = {k: v for k, v in kw.items() if k in params}
        self.ctl.note("Gerando vídeo com o modelo GGUF (pode demorar)…")
        frames = fn(**kw)
        return _frames_to_mp4(frames, fps)

    def _video_ltx2(self, path: Path, prompt: str, duration: int, aspect: str, image: Optional[Ref], seed: int, long_side: int, extra: Dict[str, Any]) -> Media:
        """LTX-2 / 2.3 / 2.5 pelo diffusers (ver ltx2.py): vídeo MP4 com áudio. Os componentes do repositório base só baixam pelo botão do nó."""
        from . import ltx2

        info = ltx2.parse(path.name)
        if info is None:
            raise ProviderError(f"Não reconheci a versão do LTX-2 em {path.name}.")
        if not ltx2.components_cached(info["base"]):
            size = 0
            try:
                size = ltx2.components_size(info["base"])
            except Exception:  # noqa: BLE001 — sem rede: só não diz o tamanho
                pass
            raise ProviderError(ltx2.missing_message(info["base"], size))
        steps, cfg = ltx2.RUN[info["variant"]]
        pil = _pil_refs([image]) if image is not None else []
        w, h = ltx2.size_for(aspect, long_side)
        frames = ltx2.frames_for(duration)
        self.ctl.note(f"Carregando o LTX-{info['version']} ({info['variant']}) pelo diffusers (pode demorar e exige bastante memória)…")
        pipe = _local_load("video", f"ltx2:{path.name}:{bool(pil)}", lambda: ltx2.load_pipeline(path, info["base"], bool(pil)))
        self.ctl.note("Gerando vídeo com áudio (pode demorar)…")
        user_steps = int(extra.get("sample_steps") or 0)
        sigmas = ltx2.DISTILLED_SIGMAS if info["variant"] == "distilled" and user_steps in (0, len(ltx2.DISTILLED_SIGMAS)) else None   # v0.86: o distilled tem a escala de ruído dele (ver ltx2.DISTILLED_SIGMAS)
        data = ltx2.generate(pipe, prompt=prompt, width=w, height=h, frames=frames, steps=user_steps or steps, cfg=float(extra.get("cfg_scale") or cfg),
                             seed=int(seed or 0), image=cover_fit(pil[0], w, h) if pil else None, check=self.ctl.check, sigmas=sigmas)
        return Media(data, "video/mp4")

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
                cover_fit(pil[0], w, h).save(b, format="PNG")
                init = b.getvalue()
        container = vinfo.get("container")
        if container:   # o próprio sd-cli grava o vídeo (com áudio estéreo): nada de quadros soltos nem ffmpeg
            self.ctl.note(f"Gerando o vídeo com áudio pelo sd-cli ({cli.name}). Pode demorar bastante.")
            run_p["video_frames"] = max(9, min(int(vinfo.get("max_frames") or 361), int(round(max(1, int(duration)) * fps)) // 8 * 8 + 1))
            try:
                data, mime, warns = self._cli_call(path, lambda c: sdcli.generate_video_file(c, self._load_kwargs(path, load), run_p, prompt=prompt, width=w, height=h, seed=int(seed) if seed else -1, fps=fps, init=init, container=container, cancelled=self._cancelled, note=self.ctl.note))
            except ProviderError as exc:
                if str(exc) == "cancelado":
                    self.ctl.check()
                if "get sd version from file failed" in str(exc):
                    raise self._layout_error(path) from None
                raise
            if warns:
                self.ctl.note("Opções sem equivalente no sd-cli (ignoradas): " + ", ".join(sorted(set(warns))))
            return Media(data, mime)
        self.ctl.note(f"A stable-diffusion-cpp-python não reconhece este modelo: gerando o vídeo pelo sd-cli ({cli.name}). Pode demorar bastante.")
        try:
            frames, warns = self._cli_call(path, lambda c: sdcli.generate_video(c, self._load_kwargs(path, load), run_p, prompt=prompt, width=w, height=h, seed=int(seed) if seed else -1, fps=fps, init=init, cancelled=self._cancelled, note=self.ctl.note))
        except ProviderError as exc:
            if str(exc) == "cancelado":
                self.ctl.check()
            if "get sd version from file failed" in str(exc):
                raise self._layout_error(path) from None
            raise
        if warns:
            self.ctl.note("Opções sem equivalente no sd-cli (ignoradas): " + ", ".join(sorted(set(warns))))
        from PIL import Image  # type: ignore

        return _frames_to_mp4([Image.open(io.BytesIO(f)).convert("RGB") for f in frames], fps)

    def test(self) -> str:
        _local_import("stable_diffusion_cpp", extra="local")
        have = {k: len(list((Path(self.cfg.get("models_dir") or ".") / k).glob("*.gguf"))) for k in ("image", "video")}
        return f"stable-diffusion-cpp-python ok · modelos GGUF: {have['image']} de imagem, {have['video']} de vídeo"


# --------------------------------------------------------------------------- catálogo

MEDIA_PRESETS: Dict[str, Dict[str, Any]] = {   # v0.35: só o Demo (offline) e os modelos locais do Hugging Face; nenhum provedor de nuvem
    "demo": {
        "label": "Demo (offline, sem IA)", "kind": "demo", "caps": ["image", "video", "sound", "voice", "model3d"], "local": True,
        "hint": "Gera paisagens abstratas, sons sintetizados e vídeos simples sem chave e sem internet — ótimo para testar fluxos inteiros (vídeo precisa do ffmpeg).",
    },
    "local_hf": {
        "label": "Hugging Face local (embutido)", "kind": "local_hf", "caps": ["image", "video", "sound", "voice", "stt", "model3d"], "local": True,
        "models": {"image": "stabilityai/sd-turbo", "video": "Lightricks/LTX-Video", "sound": "facebook/musicgen-small", "voice": "suno/bark-small", "stt": "openai/whisper-small", "model3d": "openai/shap-e"},
        "suggest": {"model3d": mesh3d.SUGGEST, "image": ["stabilityai/sd-turbo", "stabilityai/sdxl-turbo", "black-forest-labs/FLUX.1-schnell", "unsloth/Z-Image-Turbo", "unsloth/FLUX.2-klein-4B", "unsloth/FLUX.1-schnell"], "video": ["Lightricks/LTX-Video"],
                    "sound": ["facebook/musicgen-small", "facebook/musicgen-medium", "facebook/musicgen-stereo-small", "cvssp/audioldm2", "cvssp/audioldm2-music", "stabilityai/stable-audio-open-1.0", "stabilityai/stable-audio-3-small-sfx"],
                    "voice": ["suno/bark-small", "facebook/mms-tts-por", "facebook/mms-tts-eng", "facebook/mms-tts-spa", "openbmb/VoxCPM2", "unsloth/orpheus-3b-0.1-ft", "unsloth/csm-1b"],
                    "stt": ["openai/whisper-small", "openai/whisper-large-v3-turbo", "unsloth/whisper-large-v3-turbo", "unsloth/whisper-small", "unsloth/whisper-base"]},
        "hint": 'Roda modelos do Hugging Face dentro do OpenFlow. Requer:  pip install "openflow[media]". Antes de usar, escolha a precisão (quantização) e baixe cada modelo aqui mesmo — nada é baixado em silêncio. Vídeo exige GPU.',
    },
    "gguf_local": {
        "label": "GGUF local (stable-diffusion.cpp)", "kind": "gguf_local", "caps": ["image", "video"], "local": True,
        "hint": 'Modelos GGUF de imagem e vídeo (FLUX, Stable Diffusion, Wan…) quantizados, rodando no OpenFlow. Requer:  pip install "openflow[local]". Baixe-os em Configuração → Modelos locais (abas Imagem e Vídeo) escolhendo a quantização.',
    },
}

_KINDS = {"demo": DemoMedia, "local_hf": LocalHFMedia, "gguf_local": GGUFMedia}


def media_config(settings: Dict[str, Any], pid: str) -> Dict[str, Any]:
    preset = MEDIA_PRESETS.get(pid)
    if not preset:
        raise ProviderError(f"O provedor «{pid}» não existe mais: desde a v0.35 o OpenFlow usa só modelos locais do Hugging Face (e o Demo). Escolha um modelo local no nó (ou em Configuração → Mídia).")
    cfg = {k: v for k, v in preset.items() if k not in ("models", "suggest")}
    media = settings.get("media") or {}
    models = dict(preset.get("models") or {})
    models.update({k: v for k, v in ((media.get("models") or {}).get(pid) or {}).items() if v})
    cfg["models"] = models
    cfg["id"] = pid
    return cfg


def build_media(settings: Dict[str, Any], pid: str, ctl: Optional[Ctl] = None, models_dir: Optional[Path] = None) -> MediaProvider:
    cfg = media_config(settings, pid)
    if models_dir:
        cfg["models_dir"] = str(models_dir)
    return _KINDS[cfg["kind"]](cfg, ctl)


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
        out.append({"id": pid, "label": p["label"], "caps": p["caps"], "local": p.get("local", False), "hint": p.get("hint", ""), "models": cfg["models"], "suggest": p.get("suggest", {})})
    return out
