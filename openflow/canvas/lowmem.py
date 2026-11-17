"""Modelos locais de imagem em computadores fracos (v0.72): o que não depende do modelo para ser decidido e testado.

- `device_dtype`: o tipo numérico seguro para o aparelho. Um modelo baixado em fp16 quebrava na CPU («not implemented for 'Half'») e, no FLUX/Qwen-Image, gerava imagens pretas em GPUs (esses modelos são treinados em bf16 e
  estouram em fp16).
- `oom_kind` / `shrink`: reconhece falta de memória (placa de vídeo ou RAM) e calcula o tamanho menor da nova tentativa.
- `accepted` / `edit_style`: o `__call__` de cada pipeline do diffusers aceita argumentos diferentes (o Qwen-Image-Edit, o FLUX Kontext e o FLUX.2 editam com `image` e NÃO têm `strength`; o Qwen-Image usa `true_cfg_scale`):
  os argumentos pedidos são conferidos contra a assinatura real do pipeline, em vez de um `TypeError` no meio da geração.
"""
from __future__ import annotations

import inspect
import re
from typing import Any, Dict, Optional, Set

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
