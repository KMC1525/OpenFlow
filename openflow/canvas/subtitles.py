"""Legendas e transcrição (v0.62): tempos, formatos SRT/VTT, leitura de legendas prontas, quebra de linhas e cues, texto distribuído no tempo, e a transcrição com marcas de tempo.

Tudo aqui é Python puro, sem modelo nem ffmpeg: os nós Legendas, Transcrição e Dublagem (speech.py) chamam estas funções com os segmentos que o modelo de transcrição devolveu. Um segmento é
{"start": segundos, "end": segundos, "text": "..."}.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

Seg = Dict[str, Any]

LANGS: Dict[str, str] = {"pt": "português do Brasil", "en": "English", "es": "español", "fr": "français", "it": "italiano", "de": "Deutsch", "ja": "日本語", "ko": "한국어", "zh": "中文", "ru": "русский"}
LANGS_EN: Dict[str, str] = {"pt": "Brazilian Portuguese", "en": "English", "es": "Spanish", "fr": "French", "it": "Italian", "de": "German", "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "ru": "Russian"}
MAX_CUES = 2000


def seg(start: float, end: float, text: str) -> Seg:
    return {"start": round(max(0.0, float(start)), 3), "end": round(max(0.0, float(end)), 3), "text": str(text or "").strip()}


# ----------------------------------------------------------------------------- tempos
def fmt_time(t: float, sep: str = ",") -> str:
    """«01:02:03,456» (SRT, sep=«,») ou «01:02:03.456» (VTT, sep=«.»); arredonda para o milissegundo sem estourar (59,9996 s → 01:00,000)."""
    ms = int(round(max(0.0, float(t)) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


_TIME = re.compile(r"(?:(\d{1,3}):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?")


def parse_time(s: str) -> Optional[float]:
    """«00:01:02,500», «01:02.5» ou «1:02:03.004» → segundos; None se não é um tempo."""
    m = _TIME.fullmatch((s or "").strip())
    if not m:
        return None
    h, mi, sec, frac = m.groups()
    ms = int((frac or "0").ljust(3, "0")[:3])
    return int(h or 0) * 3600 + int(mi) * 60 + int(sec) + ms / 1000.0


def short_time(t: float) -> str:
    """«1:05» ou «1:02:03»: o tempo da transcrição com marcas de tempo."""
    s = int(max(0.0, t))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# ----------------------------------------------------------------------------- formatos
def wrap(text: str, max_chars: int = 42, max_lines: int = 2) -> str:
    """O texto de uma legenda em até `max_lines` linhas de `max_chars` (quebra nos espaços, procurando linhas parecidas). O que não cabe continua na última linha: nada é cortado."""
    words = " ".join((text or "").split()).split(" ")
    words = [w for w in words if w]
    if not words:
        return ""
    whole = " ".join(words)
    if len(whole) <= max_chars or max_lines <= 1:
        return whole
    lines = max(1, min(max_lines, -(-len(whole) // max_chars)))   # quantas linhas fazem falta
    target = len(whole) / lines
    out: List[str] = []
    cur = ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max(target, 1) and len(out) < lines - 1 and len(cur) >= target * 0.6:
            out.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    out.append(cur)
    return "\n".join(out)


def to_srt(segs: List[Seg], max_chars: int = 42, max_lines: int = 2) -> str:
    out = []
    for i, s in enumerate(c for c in segs if c["text"].strip()):
        out.append(f"{i + 1}\n{fmt_time(s['start'])} --> {fmt_time(s['end'])}\n{wrap(s['text'], max_chars, max_lines)}\n")
    return "\n".join(out)


def to_vtt(segs: List[Seg], max_chars: int = 42, max_lines: int = 2) -> str:
    out = ["WEBVTT\n"]
    for s in (c for c in segs if c["text"].strip()):
        out.append(f"{fmt_time(s['start'], '.')} --> {fmt_time(s['end'], '.')}\n{wrap(s['text'], max_chars, max_lines)}\n")
    return "\n".join(out)


def looks_timed(text: str) -> bool:
    """O texto já é uma legenda (SRT ou VTT)? Tem ao menos uma linha «tempo --> tempo»."""
    return bool(re.search(r"^\s*[\d:.,]+\s*-->\s*[\d:.,]+", text or "", re.M))


def parse(text: str) -> List[Seg]:
    """Lê uma legenda SRT ou VTT (com ou sem número de cue, com vírgula ou ponto nos milissegundos, tags <i>/<b> e configurações de posição depois do tempo) em segmentos."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    out: List[Seg] = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        idx = next((i for i, ln in enumerate(lines) if "-->" in ln), -1)
        if idx < 0:
            continue
        a, _, b = lines[idx].partition("-->")
        start, end = parse_time(a), parse_time(b.strip().split()[0] if b.strip() else "")
        if start is None or end is None:
            continue
        body = re.sub(r"<[^>]+>|\{\\[^}]*\}", "", " ".join(x.strip() for x in lines[idx + 1:])).strip()
        if body:
            out.append(seg(start, end, body))
        if len(out) >= MAX_CUES:
            break
    return out


# ----------------------------------------------------------------------------- ajustes
def shift(segs: List[Seg], offset: float) -> List[Seg]:
    """Adianta (negativo) ou atrasa (positivo) todas as legendas; o que ficaria antes do zero é cortado em zero."""
    out = []
    for s in segs:
        a, b = max(0.0, s["start"] + offset), s["end"] + offset
        if b > 0:
            out.append(seg(a, max(b, a + 0.05), s["text"]))
    return out


def _halve(seg_: Seg) -> List[Seg]:
    """Parte uma legenda em duas, perto do meio do texto (de preferência depois de pontuação), repartindo o tempo em proporção ao tamanho de cada parte."""
    words = seg_["text"].split(" ")
    total = len(seg_["text"])
    best, best_cost, run = 1, None, 0
    for i in range(1, len(words)):
        run += len(words[i - 1]) + 1
        cost = abs(run - total / 2) - (total * 0.12 if words[i - 1][-1:] in ".!?,;:…" else 0)
        if best_cost is None or cost < best_cost:
            best, best_cost = i, cost
    a, b = " ".join(words[:best]), " ".join(words[best:])
    mid = seg_["start"] + (seg_["end"] - seg_["start"]) * len(a) / max(1, len(a) + len(b))
    return [seg(seg_["start"], mid, a), seg(mid, seg_["end"], b)]


def split_long(segs: List[Seg], max_chars: int = 84, max_seconds: float = 6.0) -> List[Seg]:
    """Divide as legendas longas demais (texto ou tempo) em partes que cabem nos dois limites: parte ao meio, de preferência depois de pontuação, e repete nas partes que ainda passam. O tempo se reparte em proporção
    ao tamanho do texto. Uma palavra sozinha nunca é cortada."""
    out: List[Seg] = []
    for s in segs:
        todo = [seg(s["start"], s["end"], " ".join(s["text"].split()))]
        done: List[Seg] = []
        while todo and len(done) + len(todo) < MAX_CUES:
            cur = todo.pop(0)
            too_long = len(cur["text"]) > max_chars or (max_seconds > 0 and cur["end"] - cur["start"] > max_seconds + 0.001)
            if too_long and " " in cur["text"]:
                todo[0:0] = _halve(cur)
            else:
                done.append(cur)
        out += done + todo
    return out


def tidy(segs: List[Seg], min_seconds: float = 0.4, gap: float = 0.02) -> List[Seg]:
    """Legendas em ordem, sem cues vazios, sem sobreposição (cada uma termina antes da próxima começar) e com uma duração mínima legível."""
    items = sorted((s for s in segs if s["text"].strip()), key=lambda s: (s["start"], s["end"]))
    out: List[Seg] = []
    for i, s in enumerate(items):
        start, end = s["start"], max(s["end"], s["start"] + min_seconds)
        nxt = items[i + 1]["start"] if i + 1 < len(items) else None
        if nxt is not None and end > nxt - gap:
            end = max(start + 0.05, nxt - gap)
        out.append(seg(start, end, s["text"]))
    return out[:MAX_CUES]


_SENT = re.compile(r"(?<=[.!?…])\s+|\n+")


def spread(text: str, total_seconds: float, max_chars: int = 84, start: float = 0.0) -> List[Seg]:
    """Um texto sem tempos vira legendas distribuídas ao longo de `total_seconds`: uma por frase/linha, com o tempo de cada uma em proporção ao tamanho (as longas são divididas)."""
    pieces = [p.strip() for p in _SENT.split(text or "") if p.strip()]
    if not pieces or total_seconds <= 0:
        return []
    chunks: List[str] = []
    for p in pieces:
        chunks += [p] if len(p) <= max_chars else [c["text"] for c in split_long([seg(0, 1, p)], max_chars, 0)]
    weight = [max(1, len(c)) for c in chunks]
    tot = float(sum(weight))
    out: List[Seg] = []
    t = start
    for c, w in zip(chunks, weight):
        d = total_seconds * w / tot
        out.append(seg(t, t + d, c))
        t += d
    return tidy(out)[:MAX_CUES]


# ----------------------------------------------------------------------------- transcrição
def transcript_text(segs: List[Seg], mode: str = "plain") -> str:
    """A transcrição: `plain` (tudo corrido), `timestamps` (uma linha por trecho, «[1:05] texto») ou `paragraphs` (um parágrafo a cada pausa longa ou frase final depois de uns 400 caracteres)."""
    items = [s for s in segs if s["text"].strip()]
    if mode == "timestamps":
        return "\n".join(f"[{short_time(s['start'])}] {s['text'].strip()}" for s in items)
    if mode == "paragraphs":
        paras: List[str] = []
        cur = ""
        last_end = 0.0
        for s in items:
            if cur and (s["start"] - last_end > 1.5 or (len(cur) > 400 and cur.rstrip()[-1:] in ".!?…")):
                paras.append(cur)
                cur = ""
            cur = (cur + " " + s["text"].strip()) if cur else s["text"].strip()
            last_end = s["end"]
        if cur:
            paras.append(cur)
        return "\n\n".join(paras)
    return " ".join(s["text"].strip() for s in items)


def segments_from_chunks(chunks: List[Dict[str, Any]], total: float = 0.0) -> List[Seg]:
    """Os `chunks` do pipeline de reconhecimento de fala do transformers («timestamp»: (início, fim), o fim do último pode ser None) em segmentos."""
    out: List[Seg] = []
    for i, c in enumerate(chunks or []):
        ts = c.get("timestamp") or c.get("timestamps") or (0.0, None)
        a = ts[0] if ts and ts[0] is not None else (out[-1]["end"] if out else 0.0)
        b = ts[1] if len(ts) > 1 and ts[1] is not None else None
        if b is None:   # o último trecho costuma vir sem fim: vale o começo do próximo, o fim do áudio ou alguns segundos
            nxt = chunks[i + 1].get("timestamp", (None,))[0] if i + 1 < len(chunks) else None
            b = nxt if nxt is not None else (total if total > a else a + 3.0)
        text = str(c.get("text") or "").strip()
        if text:
            out.append(seg(a, max(b, a + 0.05), text))
    return out


# ----------------------------------------------------------------------------- personagens (v0.63)
def norm_name(s: str) -> str:
    """O nome de um personagem para comparar: sem acentos, sem maiúsculas, só letras e números separados por um espaço («João  Silva» = «joao silva»)."""
    import unicodedata

    base = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("ascii").casefold()
    return " ".join(re.findall(r"[a-z0-9]+", base))


_LABEL_KNOWN = r"(?:\[\s*(?P<b>[^\]\n]{1,30}?)\s*\]|\(\s*(?P<p>[^)\n]{1,30}?)\s*\)|(?P<c>[^\W\d_][^:\n\[\]()]{0,28}?)\s*:)"
_LABEL_RE = re.compile(r"^\s*(?:[-–—]\s*)?" + _LABEL_KNOWN + r"\s*(?P<rest>.*)$", re.S)
_COLON_RE = re.compile(r"^\s*(?:[-–—]\s*)?(?P<c>[^\W\d_][\w .'’-]{0,24}?)\s*:\s+(?P<rest>\S.*)$", re.S)


def assign_speakers(segs: List[Seg], names: List[List[str]], mode: str = "labels") -> "tuple[List[tuple[int, str]], List[str]]":
    """Quem fala cada trecho (v0.63): devolve, para cada segmento, (índice do locutor, texto sem a marca) e os avisos.

    `names[i]` são os apelidos do locutor `i` (o nome do nó Voz e o nome da voz). Uma marca vale no começo do texto, em três formas: «Maria: fala», «[Maria] fala» e «(Maria) fala» — só quando o nome é de um locutor
    conhecido (assim «[Música]» ou «(rindo)» continuam como texto). A marca vale até a próxima (um roteiro sem marca em cada frase segue com o mesmo locutor); antes da primeira marca, vale o primeiro locutor.
    `mode="alternate"`: as falas alternam entre os locutores, uma de cada vez (um diálogo de duas pessoas sem marcas); as marcas conhecidas saem do texto do mesmo jeito. Um «Nome:» desconhecido que se repete
    em dois ou mais trechos é tratado como marca de um personagem sem voz ligada: sai do texto (não é lido em voz alta) e o aviso diz qual."""
    table = {norm_name(a): i for i, al in enumerate(names) for a in al if norm_name(a)}
    unknown: Dict[str, int] = {}
    for s in segs:
        m = _COLON_RE.match(s["text"])
        if m and norm_name(m.group("c")) not in table and norm_name(m.group("c")):
            unknown[norm_name(m.group("c"))] = unknown.get(norm_name(m.group("c")), 0) + 1
    repeated = {k for k, n in unknown.items() if n >= 2}
    out: List["tuple[int, str]"] = []
    current, matched, stripped_unknown = 0, 0, []
    for i, s in enumerate(segs):
        text = s["text"]
        m = _LABEL_RE.match(text)
        label = (m.group("b") or m.group("p") or m.group("c")) if m else None
        key = norm_name(label or "")
        if m and key in table and m.group("rest").strip():
            current, text = table[key], m.group("rest").strip()
            matched += 1
        else:
            mc = _COLON_RE.match(text)
            if mc and norm_name(mc.group("c")) in repeated:
                text = mc.group("rest").strip()
                if mc.group("c").strip() not in stripped_unknown:
                    stripped_unknown.append(mc.group("c").strip())
        out.append(((i % len(names)) if mode == "alternate" and names else current, text))
    warns: List[str] = []
    if stripped_unknown:
        warns.append("Personagens sem voz ligada: " + ", ".join(f"«{n}»" for n in stripped_unknown[:6]) + ". As falas deles saíram com a voz do trecho anterior (ligue um nó Voz com esse nome para dar uma voz a cada um).")
    if len(names) > 1 and mode == "labels" and not matched:
        warns.append(f"Há {len(names)} vozes ligadas, mas nenhuma fala tem marca de personagem («Nome: fala»): usei só a primeira voz. Marque as falas com o nome do nó Voz ou escolha «Alternar entre as vozes».")
    return out, warns
