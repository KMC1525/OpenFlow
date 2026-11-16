"""Letras de música (v0.61): o nó Letra escreve (com o modelo de texto) ou arruma a letra de uma música e a entrega como texto, pronta para a porta «Letra» do nó Música.

Tudo aqui é Python puro e testável sem modelo: as estruturas (estrofes e refrões), a limpeza das marcas de seção («[Verse 1]», «[Chorus]»), o pedido ao modelo de texto e uma letra de exemplo para quando
não há modelo de texto configurado (o provedor Demo).
"""
from __future__ import annotations

import random
import re
from typing import Dict, List, Tuple

from .procedural import seed_of

LANGS: Dict[str, str] = {"pt": "português do Brasil", "en": "English", "es": "español", "fr": "français", "it": "italiano", "de": "Deutsch"}
LANG_EN: Dict[str, str] = {"pt": "Brazilian Portuguese", "en": "English", "es": "Spanish", "fr": "French", "it": "Italian", "de": "German"}
# estrutura → [(seção, linhas)]
STRUCTS: Dict[str, List[Tuple[str, int]]] = {
    "song": [("Verse 1", 4), ("Chorus", 4), ("Verse 2", 4), ("Chorus", 4), ("Bridge", 4), ("Chorus", 4)],
    "short": [("Verse 1", 4), ("Chorus", 4)],
    "hook": [("Chorus", 4)],
    "rap": [("Verse 1", 8), ("Hook", 4), ("Verse 2", 8), ("Hook", 4)],
}
RHYMES = {"aabb": "AABB (each pair of lines rhymes)", "abab": "ABAB (alternating rhyme)", "free": "free verse (rhyme only when it sounds natural)"}

_SECTION_WORDS = {"intro": "Intro", "verse": "Verse", "verso": "Verse", "estrofe": "Verse", "chorus": "Chorus", "refrão": "Chorus", "refrao": "Chorus", "coro": "Chorus", "bridge": "Bridge", "ponte": "Bridge",
                  "outro": "Outro", "hook": "Hook", "pre-chorus": "Pre-Chorus", "prechorus": "Pre-Chorus", "pré-refrão": "Pre-Chorus", "pre-refrão": "Pre-Chorus", "pre-refrao": "Pre-Chorus", "pré-refrao": "Pre-Chorus"}
_SECTION_RE = re.compile(r"^\s*[\[(]?\s*(" + "|".join(sorted((re.escape(k) for k in _SECTION_WORDS), key=len, reverse=True)) + r")\s*(\d{0,2})\s*[\])]?\s*:?\s*$", re.I)
_ANY_TAG = re.compile(r"^\s*\[[^\]\n]{1,40}\]\s*$")


def section_tag(line: str) -> str:
    """«Refrão:», «(chorus 2)», «[verso 1]» → «[Chorus]», «[Chorus 2]», «[Verse 1]»; vazio se a linha não é uma marca de seção."""
    m = _SECTION_RE.match(line)
    if not m:
        return ""
    name = _SECTION_WORDS[m.group(1).lower()]
    return f"[{name}{(' ' + m.group(2)) if m.group(2) else ''}]"


def tidy(raw: str, tags: bool = True, limit: int = 8000) -> str:
    """A letra arrumada: marcas de seção no mesmo formato («[Verse 1]»), uma linha em branco entre as seções, sem espaços sobrando e sem aspas/markdown em volta. Com `tags` falso, as marcas saem."""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"^```[a-z]*\n|\n```$", "", text)   # modelos às vezes devolvem a letra num bloco de código
    out: List[str] = []
    for line in text.split("\n"):
        line = line.rstrip()
        tag = section_tag(line) or (line.strip() if _ANY_TAG.match(line) else "")
        if tag:
            if not tags:
                continue
            if out and out[-1] != "":
                out.append("")
            out.append(tag)
            continue
        line = re.sub(r"^\s*#+\s*|^\s*[-*•]\s+", "", line) if line.strip() else ""
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line.strip())
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)[:limit]


def structure_text(structure: str) -> str:
    return ", ".join(f"[{name}] ({lines} lines)" for name, lines in STRUCTS.get(structure, STRUCTS["song"]))


def system_prompt(p: Dict[str, object], style: str = "") -> str:
    """O pedido ao modelo de texto: letra original, no idioma, gênero e clima pedidos, na estrutura escolhida, com as marcas de seção em colchetes (é o que os modelos de música leem)."""
    lang = LANG_EN.get(str(p.get("language")), "Brazilian Portuguese")
    bits = [
        "You are a professional songwriter working inside a media production flow. Write ORIGINAL song lyrics from the theme you are given — never copy existing songs.",
        f"Language of the lyrics: {lang}.",
        f"Structure, with the section tags in square brackets on their own line: {structure_text(str(p.get('structure')))}.",
        f"Rhyme scheme: {RHYMES.get(str(p.get('rhyme')), RHYMES['aabb'])}.",
        "Singable lines of similar length (6–10 syllables), a memorable repeated chorus, concrete images instead of clichés.",
    ]
    if p.get("genre"):
        bits.append(f"Genre: {p['genre']}.")
    if p.get("mood"):
        bits.append(f"Mood: {p['mood']}.")
    if style:
        bits.append(f"Project style: {style}")
    bits.append("Output ONLY the lyrics (the section tags and the lines): no title, no comments, no quotes, no markdown.")
    return " ".join(bits)


# ---- letra de exemplo (sem modelo de texto)
_PT = {
    "Verse": ["Eu vejo {a} no fim do dia", "E sinto {b} dentro de mim", "Cada passo me leva a {c}", "Sem pressa de chegar ao fim", "A noite chama {a} de volta", "E o vento fala de {b}", "Guardo {c} no peito inteiro", "Quem sabe o que ainda vem"],
    "Chorus": ["{A}, {a}, canta comigo", "Vem ver {b} amanhecer", "Nada vai nos deter agora", "Porque {c} vai permanecer"],
    "Bridge": ["E se tudo ficar em silêncio", "Ainda sobra {a} pra mim", "Respiro fundo e sigo em frente", "Com {b} até o fim"],
}
_EN = {
    "Verse": ["I see {a} at the end of the day", "And I feel {b} deep inside", "Every step is leading me to {c}", "No hurry to reach the other side", "The night calls {a} back again", "And the wind is singing of {b}", "I keep {c} inside my chest", "Who knows what is coming next"],
    "Chorus": ["{A}, {a}, sing along with me", "Watch {b} rise up with the sun", "Nothing's gonna stop us now", "Because {c} will carry on"],
    "Bridge": ["And if everything goes quiet", "There is still {a} for me", "I breathe in deep and keep on going", "With {b} until the end"],
}
_STOP = set("para com uma que dos das nos nas por sobre entre sem mais muito como the and for with from that this about into over under".split())


def demo(theme: str, language: str = "pt", structure: str = "song", seed: int = 0) -> str:
    """Uma letra de EXEMPLO montada com as palavras do tema (sem IA): serve para testar o fluxo inteiro offline. Para letras de verdade, configure um modelo de texto em Configuração → Provedores."""
    rnd = random.Random(seed_of("lyr", theme, language, structure, seed))
    words = [w for w in re.findall(r"[\wÀ-ÿ]{4,}", theme.lower()) if w not in _STOP] or ["a vida" if language == "pt" else "life"]
    pool = _PT if language == "pt" else _EN
    out: List[str] = []
    count: Dict[str, int] = {}
    for name, lines in STRUCTS.get(structure, STRUCTS["song"]):
        kind = "Chorus" if name in ("Chorus", "Hook") else ("Bridge" if name == "Bridge" else "Verse")
        pick = lambda: rnd.choice(words)  # noqa: E731
        a, b, c = pick(), pick(), pick()
        if kind == "Chorus":
            a, b, c = words[0], words[-1], words[len(words) // 2]   # o refrão repete: as mesmas palavras em todas as vezes
        base = pool[kind]
        if kind == "Verse":
            start = (count.get("Verse", 0) * 4) % len(base)
            sel = [base[(start + i) % len(base)] for i in range(lines)]
        else:
            sel = [base[i % len(base)] for i in range(lines)]
        count[kind] = count.get(kind, 0) + 1
        out.append(f"[{name}]")
        out += [s.format(a=a, b=b, c=c, A=a[:1].upper() + a[1:]) for s in sel]
        out.append("")
    return "\n".join(out).strip()
