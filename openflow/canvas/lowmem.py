"""Modelos locais de imagem em computadores fracos (v0.72): o que não depende do modelo para ser decidido e testado.

- `device_dtype`: o tipo numérico seguro para o aparelho. Um modelo baixado em fp16 quebrava na CPU («not implemented for 'Half'») e, no FLUX/Qwen-Image, gerava imagens pretas em GPUs (esses modelos são treinados em bf16 e
  estouram em fp16).
- `oom_kind` / `shrink`: reconhece falta de memória (placa de vídeo ou RAM) e calcula o tamanho menor da nova tentativa.
- `accepted` / `edit_style`: o `__call__` de cada pipeline do diffusers aceita argumentos diferentes (o Qwen-Image-Edit, o FLUX Kontext e o FLUX.2 editam com `image` e NÃO têm `strength`; o Qwen-Image usa `true_cfg_scale`):
  os argumentos pedidos são conferidos contra a assinatura real do pipeline, em vez de um `TypeError` no meio da geração.
"""
from __future__ import annotations

import contextlib
import inspect
import os
import re
import threading
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple

# modelos treinados em bfloat16: em float16 saem imagens pretas/ruído (NaN)
BF16_ONLY = re.compile(r"flux|qwen[-_ ]?image|z[-_ ]?image|chroma|hidream|omnigen|lumina|sana|cosmos|hunyuan[-_ ]?image", re.I)
# modelos grandes: na CPU, float32 dobraria a RAM (um FLUX de 12 B passaria de 48 GB), então ficam em bfloat16
BIG = re.compile(r"flux|qwen|sd3|stable-diffusion-3|wan|ltx|hunyuan|cogvideo|z[-_ ]?image|chroma|hidream|lumina|omnigen|sana|mochi|kandinsky|cosmos|stable-cascade", re.I)


def device_dtype(model: str, dtype: Any, dev: str, torch: Any) -> Any:
    """O tipo a usar de verdade. float16 na CPU não roda bem (e em muitos operadores não roda): modelos grandes vão para bfloat16 e os pequenos (Whisper, MMS, Bark…) para float32. Na GPU, os modelos
    que só aguentam bf16 (FLUX, Qwen-Image, Z-Image…) trocam fp16 por bf16 (os pesos baixados em fp16 são lidos no tipo pedido)."""
    try:
        if dtype is not torch.float16:
            return dtype
        if dev == "cpu":
            return torch.bfloat16 if BIG.search(model or "") else torch.float32
        if dev == "cuda" and BF16_ONLY.search(model or ""):
            return torch.bfloat16
    except Exception:  # noqa: BLE001 — sem torch/dispositivo conhecido, vale o tipo de sempre
        pass
    return dtype


def oom_kind(exc: BaseException) -> str:
    """«gpu» (memória da placa de vídeo, CUDA ou MPS), «ram» (memória do computador) ou «» (outro erro)."""
    text = f"{type(exc).__name__} {exc}".lower()
    if "outofmemory" in text.replace(" ", "") or "cuda out of memory" in text or "mps backend out of memory" in text or "hip out of memory" in text or "cuda error: out of memory" in text:
        return "gpu"
    if isinstance(exc, MemoryError) or any(k in text for k in ("defaultcpuallocator", "can't allocate memory", "cannot allocate memory", "not enough memory", "winerror 1455", "paging file is too small", "arquivo de paginação", "[errno 12]")):
        return "ram"
    if "out of memory" in text:
        return "gpu"
    return ""


def shrink(w: int, h: int, factor: float = 0.75, floor: int = 384, multiple: int = 16) -> Optional[tuple]:
    """O tamanho da próxima tentativa (múltiplo de 16, no mínimo `floor` no lado menor); None quando já não dá para reduzir."""
    nw, nh = max(floor, int(w * factor) // multiple * multiple), max(floor, int(h * factor) // multiple * multiple)
    return (nw, nh) if (nw, nh) != (w, h) and nw * nh < w * h else None


def params_of(call: Any) -> Optional[Set[str]]:
    """Os nomes dos argumentos que o pipeline aceita; None = aceita qualquer um (tem **kwargs) ou não deu para ler."""
    try:
        ps = inspect.signature(call).parameters
    except (TypeError, ValueError):
        return None
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in ps.values()):
        return None
    return set(ps) - {"self"}


def accepted(params: Optional[Set[str]], name: str) -> bool:
    return params is None or name in params


def edit_style(params: Optional[Set[str]]) -> bool:
    """Edita com `image` e SEM `strength` (Qwen-Image-Edit, FLUX Kontext, FLUX.2): a imagem é uma referência da edição, não um ponto de partida de imagem → imagem."""
    return params is not None and "image" in params and "strength" not in params


def multi_image(class_name: str) -> bool:
    """O pipeline junta várias imagens de referência na mesma edição (Qwen-Image-Edit-Plus, FLUX.2, FLUX.2 klein)."""
    return bool(re.search(r"EditPlus|Flux2|Klein", class_name or ""))


def keep(kw: Dict[str, Any], params: Optional[Set[str]]) -> Dict[str, Any]:
    """Só os argumentos que o pipeline conhece (os do usuário, no campo «Extra», não passam por aqui: um nome errado deve dar o erro do pipeline, não sumir)."""
    return {k: v for k, v in kw.items() if accepted(params, k)}


def tips(kind: str) -> str:
    base = "escolha uma precisão menor ao baixar (fp16/bf16) ou use uma versão quantizada em GGUF do modelo (provedor «GGUF local»: Q4_K_M ou menor)"
    if kind == "gpu":
        return "Feche outros programas que usem a placa, peça uma imagem menor, " + base + "."
    return "Feche outros programas, aumente a memória virtual (Windows: arquivo de paginação), " + base + "."


def where(kind: str) -> str:
    return "da placa de vídeo (VRAM)" if kind == "gpu" else "do computador (RAM)"


def friendly_oom(kind: str, model: str, w: int, h: int, tries: int) -> str:
    size = f"{w}×{h}" + (f", depois de reduzir o tamanho {tries}x" if tries else "")
    return f"Acabou a memória {where(kind)} ao gerar com «{model}» ({size}). {tips(kind)}"


# --------------------------------------------------------------------------- travamentos (v0.77): progresso, cancelamento e memória
def explicit(params: Optional[Set[str]], name: str) -> bool:
    """O pipeline TEM o argumento `name` na assinatura (e não só um **kwargs genérico)."""
    return params is not None and name in params


def default_of(call: Any, name: str) -> Any:
    """O valor padrão de um argumento do pipeline (ex.: `num_inference_steps` = 50), ou None."""
    try:
        d = inspect.signature(call).parameters[name].default
    except (TypeError, ValueError, KeyError):
        return None
    return None if d is inspect.Parameter.empty else d


def fmt_seconds(sec: float) -> str:
    sec = int(max(0, sec))
    return f"{sec // 3600}h{sec % 3600 // 60:02d}" if sec >= 3600 else f"{sec // 60}min{sec % 60:02d}s" if sec >= 60 else f"{sec}s"


class _SafeCtl:
    """Um Ctl que nunca quebra: sem `check` ou `note` no objeto recebido, esses passos viram «nada»."""

    def __init__(self, ctl: Any) -> None:
        self._c = ctl

    def check(self) -> None:
        f = getattr(self._c, "check", None)
        if f:
            f()

    def note(self, msg: str) -> None:
        f = getattr(self._c, "note", None)
        if f:
            f(msg)


def safe_ctl(ctl: Any) -> Any:
    return _SafeCtl(ctl)


def step_progress(ctl: Any, total: int = 0, label: str = "Gerando", interval: float = 1.5, clock: Callable[[], float] = time.monotonic) -> Callable[..., Any]:
    """O `callback_on_step_end` do diffusers: a cada passo de difusão (1) confere o cancelamento — antes só se olhava entre uma imagem e outra, e o botão «Parar» ficava mudo por minutos numa máquina fraca — e
    (2) avisa o progresso («passo 5 de 28, faltam ≈ 3min10s») no máximo a cada `interval` segundos, para o nó não parecer travado."""
    ctl = safe_ctl(ctl)
    state = {"t0": clock(), "last": -1e9}

    def callback(pipe: Any, step: int, timestep: Any, cb_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        ctl.check()
        now = clock()
        done = int(step) + 1
        if now - state["last"] >= interval or (total and done >= total):
            state["last"] = now
            if total and done <= total:
                left = (now - state["t0"]) / done * (total - done)
                ctl.note(f"{label}: passo {done} de {total}" + (f" — faltam ≈ {fmt_seconds(left)}" if done > 1 and left >= 3 else ""))
            else:
                ctl.note(f"{label}: passo {done}")
        return cb_kwargs
    return callback


def effective_steps(steps: int, strength: Optional[float] = None) -> int:
    """Quantos passos o pipeline de fato roda: em imagem → imagem com `strength` < 1 só uma parte deles."""
    if steps and strength is not None and 0 < strength < 1:
        return max(1, round(steps * strength))
    return int(steps or 0)


def fit(weights: int, ram_avail: int, strategy: str = "") -> Tuple[str, str]:
    """O modelo cabe na memória do computador? («ok» | «warn» | «refuse», mensagem). Um modelo maior que a RAM livre vai para a memória virtual do disco e o computador inteiro trava (mouse, janelas, tudo):
    acima de 1× a RAM livre avisa; acima de 2×, recusa (se for de propósito: OPENFLOW_ALLOW_SWAP=1). GPU com o modelo inteiro na placa não passa pela RAM."""
    if not weights or not ram_avail or strategy == "gpu":
        return "ok", ""
    gib = 1024 ** 3
    ratio = weights / float(ram_avail)
    if ratio <= 1.0:
        return "ok", ""
    msg = (f"Este modelo ocupa {weights / gib:.1f} GB e só há {ram_avail / gib:.1f} GB de RAM livre: ele iria para a memória virtual do disco e o computador pode travar por minutos. "
           "Use uma precisão menor ou uma versão quantizada em GGUF (provedor «GGUF local», Q4_K_M ou menor), ou feche outros programas")
    if ratio > 2.0 and os.environ.get("OPENFLOW_ALLOW_SWAP", "") not in ("1", "true", "yes"):
        return "refuse", msg + ". Para tentar mesmo assim (devagar, usando o disco), defina OPENFLOW_ALLOW_SWAP=1."
    return "warn", msg + "."


def torch_threads(physical: int, mode: str) -> int:
    """Quantas threads o torch usa na CPU: sempre deixa pelo menos um núcleo livre para a interface e o sistema (no modo máximo, tudo). 0 = não mexe."""
    physical = max(1, int(physical or 1))
    if mode == "max":
        return 0
    if mode == "light":
        return max(1, physical // 2)
    return max(1, physical - 1) if physical > 2 else physical


@contextlib.contextmanager
def heartbeat(ctl: Any, label: str, interval: float = 15.0) -> Any:
    """Enquanto uma etapa longa e sem eventos roda (a decodificação final da imagem na CPU, a stable-diffusion.cpp…), avisa a cada `interval` segundos que o OpenFlow continua trabalhando e há quanto tempo: sem isso
    o nó parece travado."""
    ctl = safe_ctl(ctl)
    stop = threading.Event()
    t0 = time.monotonic()

    def beat() -> None:
        while not stop.wait(interval):
            ctl.note(f"{label}… {fmt_seconds(time.monotonic() - t0)}")
    t = threading.Thread(target=beat, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=2)   # v0.91: sem isto um aviso já «em voo» ainda saía depois do bloco terminar
