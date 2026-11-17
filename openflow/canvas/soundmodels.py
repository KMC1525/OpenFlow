"""Famílias de modelos de SOM locais do Hugging Face que o OpenFlow roda (v0.68) e como chamar cada uma.

* **MusicGen** (transformers, `pipeline("text-to-audio")`): música e sons de até 30 s; as variantes «stereo» e «melody» (só com texto) usam o mesmo caminho.
* **AudioLDM / AudioLDM2 / MusicLDM** (diffusers): bons em efeitos sonoros e ambientes; `audio_length_in_s` e `num_inference_steps`.
* **Stable Audio Open** e **Stable Audio 3** (diffusers): música e efeitos de até 47 s (Open) ou mais (3); `audio_end_in_s` (Open) ou `duration` (3).

Os argumentos foram conferidos no código do diffusers 0.43 (`pipeline_audioldm2.py`, `pipeline_stable_audio.py`, `pipeline_stable_audio_3.py`) e do transformers 5.23; nenhum modelo foi executado aqui.
Tudo Python puro (sem importar torch/diffusers), para testar sem os modelos.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_FAMILIES = (
    ("stable-audio-3", re.compile(r"stable-audio-3", re.I)),
    ("stable-audio-open", re.compile(r"stable-audio(?!-3)", re.I)),
    ("audioldm", re.compile(r"(audioldm|musicldm)", re.I)),
    ("musicgen", re.compile(r"musicgen", re.I)),
)
DIFFUSERS = ("stable-audio-3", "stable-audio-open", "audioldm")
MAX_SECONDS: Dict[str, float] = {"musicgen": 30.0, "stable-audio-open": 47.0, "stable-audio-3": 190.0, "audioldm": 30.0}   # o que o modelo gera de uma vez (os de diffusers aceitam mais, mas perdem qualidade)


def family(model: str) -> str:
    """«musicgen», «audioldm», «stable-audio-open», «stable-audio-3» ou «» (a família de sons pelo nome do repositório)."""
    for name, pat in _FAMILIES:
        if pat.search(str(model or "")):
            return name
    return ""


def uses_diffusers(model: str) -> bool:
    return family(model) in DIFFUSERS


def call_kwargs(pipeline_class: str, duration: float, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Os argumentos de tempo do pipeline pelo NOME da classe que o diffusers carregou (ele lê o `model_index.json`): `StableAudio3Pipeline(duration=)`, `StableAudioPipeline(audio_end_in_s=)` e
    `AudioLDM2Pipeline`/`AudioLDMPipeline`/`MusicLDMPipeline(audio_length_in_s=)`. `extra` (campo «Extra» do nó) vence."""
    d = max(1.0, float(duration))
    name = str(pipeline_class or "")
    if "StableAudio3" in name:
        kw: Dict[str, Any] = {"duration": min(d, MAX_SECONDS["stable-audio-3"])}
    elif "StableAudio" in name:
        kw = {"audio_end_in_s": min(d, MAX_SECONDS["stable-audio-open"]), "num_inference_steps": 100}
    else:
        kw = {"audio_length_in_s": min(d, MAX_SECONDS["audioldm"]), "num_inference_steps": 50}
    kw.update(extra or {})
    return kw


def sampling_rate(pipe: Any) -> int:
    """A taxa de amostragem do áudio que o pipeline devolve: o VAE (Stable Audio) ou o vocoder (AudioLDM, MusicLDM). 0 se não achou."""
    for path in (("vae", "config", "sampling_rate"), ("vae", "sampling_rate"), ("vocoder", "config", "sampling_rate")):
        obj: Any = pipe
        for attr in path:
            obj = getattr(obj, attr, None)
            if obj is None:
                break
        else:
            if isinstance(obj, (int, float)) and obj > 0:
                return int(obj)
    return 0


def limit_note(model: str, duration: float) -> str:
    """O aviso quando a duração pedida passa do que o modelo gera de uma vez (vazio se cabe)."""
    fam = family(model)
    cap = MAX_SECONDS.get(fam)
    if cap and duration > cap:
        return f"Este modelo ({fam}) gera até {cap:.0f} s de uma vez: o resultado terá {cap:.0f} s (use «Repetir áudio» ou o Editor para alongar)."
    return ""
