"""Dublagem com a voz de cada locutor (v0.80): quando o modelo de voz clona voz (openbmb/VoxCPM2), a Dublagem sozinha tira do áudio ORIGINAL uma amostra da voz de cada pessoa que fala e dubla cada
fala com a voz clonada dela — sem o usuário ligar nenhum nó Voz nem áudio de referência.

Os passos (tudo com numpy e ffmpeg; nenhum modelo a mais é baixado):
1. descobrir quem fala cada trecho (a mesma separação de vozes da Transcrição, `diarize`) — só se o roteiro/a transcrição tem tempos de verdade;
2. para cada voz, escolher as falas mais longas dela (até ≈ 12 s, cada uma com no máximo 10 s) e juntá-las numa amostra WAV de 16 kHz;
3. dublar cada fala com a amostra da voz de quem a disse. Dublando no MESMO idioma (sem tradução) a transcrição da amostra segue junto: é a «clonagem fiel» do VoxCPM2 (a voz continua a amostra);
   traduzindo para outro idioma só o timbre vale («clonagem controlável»).

Limites honestos: a separação de vozes confunde vozes parecidas, fala ao mesmo tempo e música ao fundo; uma amostra com música ou ruído clona a música e o ruído junto; um locutor com menos de 1,5 s de
fala fica sem amostra e é dublado com a voz padrão do nó.
"""
from __future__ import annotations

import io
import wave
from typing import Any, Dict, List, Tuple

from . import diarize

SR = diarize.SR
REF_TARGET = 12.0        # segundos de amostra por voz (o VoxCPM2 clona bem com ≈ 5–15 s; mais que isso só demora)
REF_MAX_SEG = 10.0       # uma fala só entra na amostra com no máximo isso (o início dela)
MIN_REF = 1.5            # amostras menores que isto não clonam: a voz fica sem amostra
GAP = 0.12               # silêncio posto entre duas falas da amostra
MAX_TEXT = 1000


def voiced_runs(x: Any, sr: int = SR) -> List[Tuple[float, float]]:
    """Os trechos com fala (ou som) do áudio, para quando não há tempos de verdade: quadros de 50 ms com energia acima de 30 % do percentil 90, ligados quando a pausa é menor que 0,3 s; sobram só os de
    pelo menos 0,8 s."""
    import numpy as np

    hop = int(sr * 0.05)
    n = len(x) // hop
    if n < 4:
        return []
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    top = float(np.percentile(rms, 90))
    if top < 1e-4:
        return []
    on = rms > max(0.3 * top, 1e-4)
    runs: List[List[int]] = []
    for i, v in enumerate(on):
        if v:
            if runs and i - runs[-1][1] <= 6:
                runs[-1][1] = i + 1
            else:
                runs.append([i, i + 1])
    return [(a * 0.05, b * 0.05) for a, b in runs if (b - a) * 0.05 >= 0.8]


def pick(items: List[Tuple[float, float, str]], target: float = REF_TARGET, max_seg: float = REF_MAX_SEG) -> List[Tuple[float, float, str]]:
    """Escolhe as falas da amostra: as mais longas primeiro, só falas inteiras (uma que passaria de `target` é pulada e tenta-se uma mais curta), até somar `target`; devolve em ordem de tempo. Uma fala maior que
    `max_seg` entra cortada nele e perde a transcrição (o texto não bate mais com o áudio)."""
    chosen: List[Tuple[float, float, str]] = []
    total = 0.0
    for a, b, t in sorted(items, key=lambda i: i[1] - i[0], reverse=True):
        length = min(b - a, max_seg)
        if length < 0.4 or (chosen and total + length > target):
            continue
        chosen.append((a, a + length, t if b - a <= max_seg else ""))
        total += length
        if total >= target:
            break
    return sorted(chosen)


def wav_bytes(x: Any, ranges: List[Tuple[float, float, str]], sr: int = SR) -> Tuple[bytes, float]:
    """O WAV mono de 16 bits com as falas escolhidas (uma pausa curta entre elas) e a duração dele em segundos."""
    import numpy as np

    pieces: List[Any] = []
    gap = np.zeros(int(GAP * sr), dtype="float32")
    for a, b, _t in ranges:
        seg = x[max(0, int(a * sr)):int(b * sr)]
        if len(seg):
            if pieces:
                pieces.append(gap)
            pieces.append(seg)
    if not pieces:
        return b"", 0.0
    y = np.concatenate(pieces)
    pk = float(np.max(np.abs(y)))
    if pk < 1e-3:                       # silêncio: não há voz para clonar
        return b"", 0.0
    if pk > 1.0:
        y = y / pk
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    return buf.getvalue(), len(y) / sr


def speaker_of(labelled: List[Dict[str, Any]], start: float, end: float, default: int = 0) -> int:
    """O locutor que fala mais tempo dentro de [start, end] (pelos trechos separados); sem sobreposição, o do trecho mais perto."""
    best, best_ov = None, 0.0
    for s in labelled:
        ov = min(end, s["end"]) - max(start, s["start"])
        if ov > best_ov:
            best, best_ov = s.get("speaker", 0), ov
    if best is not None:
        return int(best)
    if not labelled:
        return default
    mid = (start + end) / 2.0
    return int(min(labelled, key=lambda s: abs((s["start"] + s["end"]) / 2.0 - mid)).get("speaker", default))


def plan(x: Any, orig: List[Dict[str, Any]], timed: bool, count: int = 0) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """Das falas originais e do áudio sai (trechos com «speaker», as vozes, avisos). Cada voz: {«wav», «seconds», «text», «speech»}; `wav` é b"" se a voz ficou sem amostra.
    Sem tempos de verdade (`timed` falso: roteiro sem tempos, ou um modelo de transcrição que devolve um trecho só) é uma voz só, amostrada dos trechos com som."""
    notes: List[str] = []
    labelled: List[Dict[str, Any]] = []
    found = 1
    total = len(x) / SR
    if timed and orig:
        try:
            labelled, found = diarize.label_segments(x, orig, count)
        except Exception as exc:   # análise de apoio: falhar não pode perder a dublagem
            notes.append(f"Não consegui separar as vozes do original ({type(exc).__name__}): dublei com uma voz só.")
            labelled, found = [], 1
    elif count > 1:
        notes.append("Só dá para separar as vozes quando a fala tem tempos de verdade (transcrição com tempos, ou legendas SRT/VTT no roteiro): dublei com uma voz só.")
    groups: Dict[int, List[Tuple[float, float, str]]] = {i: [] for i in range(max(1, found))}
    if labelled:
        for s in labelled:
            groups.setdefault(int(s.get("speaker", 0)), []).append((max(0.0, s["start"]), min(total, s["end"]), s["text"]))
    else:
        groups[0] = [(a, b, "") for a, b in voiced_runs(x)]
    voices: List[Dict[str, Any]] = []
    for i in sorted(groups):
        items = groups[i]
        chosen = pick(items)
        data, secs = wav_bytes(x, chosen) if chosen else (b"", 0.0)
        if secs < MIN_REF:
            data, secs = b"", 0.0
        texts = [t for _a, _b, t in chosen]
        text = " ".join(t.strip() for t in texts)[:MAX_TEXT] if texts and all(t.strip() for t in texts) else ""
        voices.append({"wav": data, "seconds": round(secs, 1), "text": text, "speech": round(sum(b - a for a, b, _ in items), 1)})
    return labelled, voices, notes
