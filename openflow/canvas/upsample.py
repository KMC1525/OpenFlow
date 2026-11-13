"""Expansão do prompt para modelos que só rendem bem com legendas de cena completas (FLUX.3 Image Klein).

O cartão do FLUX.3 Image Klein pede que todo prompt passe por um *expansor*: o modelo foi treinado com legendas completas (meio e estilo, cena, luz e câmera, cada sujeito com cores,
materiais e posição) e um pedido curto «como digitado» dá um resultado genérico. O expansor oficial é outro modelo de 9B (18,8 GB), que o OpenFlow não baixa em silêncio; no lugar dele, o
OpenFlow usa o **modelo de texto já configurado** (Configuração → Modelo) com as instruções abaixo, escritas pelo OpenFlow a partir do que o cartão descreve. Desliga-se com `{"upsample": false}`
no campo «extra» do nó; um prompt que já é uma legenda longa (≥ 60 palavras) não é expandido de novo."""
from __future__ import annotations

import re
from typing import Any

NEEDS = re.compile(r"flux[-_. ]?3", re.I)
LONG_WORDS = 60

_COMMON = (" Write ONE paragraph in English, with no preamble, no title, no quotes and no list. Describe: the medium and visual style; the scene and framing; the lighting and camera; and each subject "
           "with its colors, materials, pose and position in the frame. Keep every fact the user gave (names, counts, colors, any text that must appear, in quotes) and invent only plausible, "
           "consistent details. Keep any markers like «name (reference image N)» exactly as written. Do not mention that you are expanding a prompt.")
SYSTEM_T2I = "You turn a short image request into the full scene caption an image model was trained on." + _COMMON
SYSTEM_I2I = ("You turn a short image-editing instruction into the full scene caption of the RESULT: a complete caption of the reference image(s) with the requested edit folded in. "
              "Say what stays the same and what changes." + _COMMON)


def wants(model: str) -> bool:
    return bool(NEEDS.search(model or ""))


def is_caption(prompt: str) -> bool:
    return len((prompt or "").split()) >= LONG_WORDS


def expand(provider: Any, prompt: str, *, edit: bool, refs: int = 0) -> str:
    """O prompt expandido pelo modelo de texto (levanta ProviderError/ValueError se o modelo falhar)."""
    note = f"\n\n(There are {refs} reference image(s); they are not shown to you. Refer to them as the user did.)" if edit and refs else ""
    out = str(provider.chat([{"role": "user", "content": prompt.strip() + note}], system=SYSTEM_I2I if edit else SYSTEM_T2I, temperature=0.4, max_tokens=700)).strip()
    out = re.sub(r"^[\"'«“]+|[\"'»”]+$", "", out).strip()
    if not out:
        raise ValueError("o modelo de texto não devolveu nada")
    return out
