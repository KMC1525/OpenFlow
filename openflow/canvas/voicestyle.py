"""Descrição da voz (v0.64): o campo «Como é a voz» do nó Voz («grave e calma, de narrador», «feminina, jovem e animada»…).

Tudo aqui é Python puro, sem modelo: junta a descrição ao estilo do projeto no pedido ao modelo de voz (`instructions`), lê da descrição o que um modelo simples consegue usar — tom, ritmo, volume e o gênero
da voz — e escolhe uma das vozes do Orpheus pelo gênero. Palavras em português e em inglês; acentos e maiúsculas não importam.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List

MAX_LEN = 600


def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("ascii").casefold()


def compose(description: str, style: str = "") -> str:
    """O pedido de estilo que vai ao modelo de voz: a descrição da voz primeiro e, se há, o estilo do projeto (Style Prompt) depois."""
    return "\n".join(x for x in ((description or "").strip()[:MAX_LEN], (style or "").strip()) if x)


# (palavras, fator): cada palavra reconhecida multiplica o tom, o ritmo ou o volume (todos limitados no fim)
_PITCH = [(r"\b(grav[ea]s?|profund[ao]s?|baix[ao]s?|rouc[ao]s?|deep|low|bass|baritone|barítono|baritono)\b", 0.72), (r"\b(masculin[ao]s?|homem|male|man)\b", 0.82), (r"\b(agud[ao]s?|fin[ao]s?|high|shrill|pitched)\b", 1.35),
          (r"\b(feminin[ao]s?|mulher|female|woman|girl|menina)\b", 1.25), (r"\b(crianca|criancas|infantil|child|kid|young girl|jovem|young)\b", 1.2), (r"\b(velh[ao]s?|idos[ao]s?|old|elderly)\b", 0.88)]
_RATE = [(r"\b(rapid[ao]s?|veloz|acelerad[ao]s?|fast|quick|animad[ao]s?|energetic[ao]s?|empolgad[ao]s?|excited|upbeat)\b", 1.3), (r"\b(lent[ao]s?|pausad[ao]s?|devagar|slow|calm[ao]s?|tranquil[ao]s?|relaxad[ao]s?|sonolent[ao]s?|sleepy)\b", 0.75),
         (r"\b(urgente|urgent|nervos[ao]s?|nervous|ansios[ao]s?|anxious)\b", 1.2)]
_GAIN = [(r"\b(sussurr\w*|whisper\w*|baixinho|quiet|murmur\w*|intim[ao]s?)\b", 0.5), (r"\b(suave|soft|gentle|delicad[ao]s?)\b", 0.75)]   # só mais baixo: o balbucio já sai no volume máximo (o PCM normaliza o pico), então «mais alto» não existiria
_FEMALE = r"\b(feminin[ao]s?|mulher|female|woman|girl|menina|garota|moca)\b"
_MALE = r"\b(masculin[ao]s?|homem|male|man|boy|menino|garoto|rapaz)\b"


def _factor(text: str, table: List[tuple]) -> float:
    f = 1.0
    for pat, k in table:
        if re.search(pat, text):
            f *= k
    return f


def traits(description: str) -> Dict[str, float]:
    """O que se lê da descrição: `pitch` (tom, 1 = normal), `rate` (ritmo da fala) e `gain` (volume, de 0,4 a 1: só se pede mais baixo). Tom e ritmo ficam entre 0,6 e 1,6; sem palavras reconhecidas, tudo 1,0."""
    t = _norm(description)
    clip = lambda v: round(max(0.6, min(1.6, v)), 3)  # noqa: E731
    return {"pitch": clip(_factor(t, _PITCH)), "rate": clip(_factor(t, _RATE)), "gain": round(max(0.4, min(1.0, _factor(t, _GAIN))), 3)}


def gender(description: str) -> str:
    """«female», «male» ou «» (a descrição não diz, ou diz os dois)."""
    t = _norm(description)
    f, m = bool(re.search(_FEMALE, t)), bool(re.search(_MALE, t))
    return "female" if f and not m else "male" if m and not f else ""


ORPHEUS_FEMALE = ("tara", "leah", "jess", "mia", "zoe")
ORPHEUS_MALE = ("leo", "dan", "zac")


def orpheus_voice(voice: str, description: str = "") -> str:
    """A voz do Orpheus a usar: a que o nó pediu, se é uma das do modelo; senão, pelo gênero da descrição (a primeira feminina ou masculina); senão «tara» (a padrão)."""
    name = (voice or "").strip().lower()
    if name in ORPHEUS_FEMALE + ORPHEUS_MALE:
        return name
    g = gender(description)
    return ORPHEUS_MALE[0] if g == "male" else ORPHEUS_FEMALE[0]
