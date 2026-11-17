"""Várias vozes na transcrição (v0.69): descobre QUEM fala cada trecho de um áudio e põe o nome («Locutor 1», «Locutor 2»…) na transcrição.

Não usa modelo baixado: é um reconhecimento de voz clássico com numpy — o áudio é cortado em janelas de 1 s de fala, cada janela vira um vetor (cepstro em escala mel + altura da voz) e as janelas são
agrupadas por semelhança (agrupamento hierárquico). Um trecho da transcrição em que a voz muda no meio é dividido no ponto da troca (o texto é repartido pelo tempo, então a divisão é aproximada).

Limites honestos: separa vozes bem diferentes (timbre e altura) com áudio razoável; vozes parecidas, fala sobreposta, música ao fundo ou ruído forte confundem. Dizer quantas pessoas falam («Vozes» no nó)
é mais confiável do que deixar em automático. Sem numpy ou sem ffmpeg, a transcrição sai como antes.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SR = 16000
WIN = 1.0                 # segundos de fala por janela de análise
MIN_SPEECH = 0.35         # uma janela precisa de pelo menos isso de fala (s) para valer
MIN_RUN = 2               # o mínimo de janelas seguidas de uma voz para contar como troca de locutor
MAX_SPEAKERS = 8
PITCH_WEIGHT = 3.0        # a altura da voz (log Hz) pesa mais que um coeficiente do cepstro
JUMP_RATIO = 1.5          # a fusão que juntaria duas vozes precisa ser pelo menos 1,5× a anterior…
JUMP_MIN = 18.0           # …e passar deste valor absoluto (uma voz só varia até uns 13 nas gravações de teste)
LABEL = "Locutor"


def numpy_ok() -> bool:
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def decode(path: Path, ffmpeg: Optional[str] = None) -> Any:
    """O áudio do arquivo (ou do vídeo) como vetor float32 mono de 16 kHz; None sem ffmpeg/numpy ou se a leitura falha."""
    ff = ffmpeg or shutil.which("ffmpeg")
    if not ff or not numpy_ok():
        return None
    import numpy as np

    try:
        r = subprocess.run([ff, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True, timeout=900)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or len(r.stdout) < 2:
        return None
    return np.frombuffer(r.stdout[:len(r.stdout) // 2 * 2], dtype="<i2").astype("float32") / 32768.0


# ----------------------------------------------------------------------------- características
_FRAME, _HOP, _MELS, _CEPS = 400, 160, 26, 13
_cache: Dict[str, Any] = {}


def _bank() -> Tuple[Any, Any, Any]:
    if "bank" not in _cache:
        import numpy as np

        n_fft = 512
        mel = lambda f: 2595 * np.log10(1 + f / 700)           # noqa: E731
        inv = lambda m: 700 * (10 ** (m / 2595) - 1)           # noqa: E731
        pts = inv(np.linspace(mel(60), mel(7600), _MELS + 2))
        bins = np.floor((n_fft + 1) * pts / SR).astype(int)
        fb = np.zeros((_MELS, n_fft // 2 + 1), dtype="float32")
        for i in range(_MELS):
            a, b, c = bins[i], bins[i + 1], bins[i + 2]
            for k in range(a, b):
                fb[i, k] = (k - a) / max(1, b - a)
            for k in range(b, c):
                fb[i, k] = (c - k) / max(1, c - b)
        dct = np.cos(np.pi / _MELS * (np.arange(_MELS) + 0.5)[None, :] * np.arange(1, _CEPS)[:, None]).astype("float32")   # c1..c12 (sem c0: o volume não conta)
        _cache["bank"] = (np.hamming(_FRAME).astype("float32"), fb, dct)
    return _cache["bank"]


def _frames(x: Any) -> Any:
    import numpy as np

    n = 1 + (len(x) - _FRAME) // _HOP
    if n < 1:
        return None
    idx = np.arange(_FRAME)[None, :] + _HOP * np.arange(n)[:, None]
    return x[idx]


def _f0(frame_block: Any) -> Any:
    """A altura (Hz) de cada quadro, por autocorrelação (60–400 Hz); 0 onde não há voz clara."""
    import numpy as np

    out = np.zeros(len(frame_block), dtype="float32")
    lo, hi = int(SR / 400), int(SR / 60)
    for i, fr in enumerate(frame_block):
        fr = fr - fr.mean()
        e = float(np.dot(fr, fr))
        if e < 1e-6:
            continue
        ac = np.correlate(fr, fr, "full")[len(fr) - 1:]
        seg = ac[lo:hi]
        k = int(np.argmax(seg))
        if seg[k] > 0.35 * ac[0]:
            out[i] = SR / (lo + k)
    return out


def window_features(x: Any) -> Optional[Any]:
    """O vetor de uma janela de áudio (cepstro mel: média e desvio dos 12 coeficientes + altura da voz) ou None se quase não há fala."""
    import numpy as np

    fr = _frames(x)
    if fr is None or len(fr) < 10:
        return None
    energy = (fr ** 2).mean(axis=1)
    keep = energy > max(energy.max() * 10 ** (-3.0), 1e-9)                      # só os quadros até 30 dB abaixo do mais forte
    if keep.sum() * _HOP / SR < MIN_SPEECH:
        return None
    win, fb, dct = _bank()
    sp = np.abs(np.fft.rfft(fr[keep] * win, 512)) ** 2
    ceps = np.log(sp @ fb.T + 1e-10) @ dct.T
    f0 = _f0(fr[keep])
    voiced = f0[f0 > 0]
    pitch = float(np.log(np.median(voiced))) if len(voiced) >= 5 else float("nan")
    return np.concatenate([ceps.mean(axis=0), ceps.std(axis=0) * 0.5, [pitch]]).astype("float64")


def _fill_pitch(feats: List[Any]) -> None:
    """Janelas sem altura clara (sussurro, consoantes) recebem a mediana das outras, para não pesarem na comparação."""
    import numpy as np

    vals = [f[-1] for f in feats if not np.isnan(f[-1])]
    mid = float(np.median(vals)) if vals else 0.0
    for f in feats:
        if np.isnan(f[-1]):
            f[-1] = mid


# ----------------------------------------------------------------------------- agrupamento
def _linkage(d: Any) -> List[Tuple[int, int, float]]:
    """Agrupamento hierárquico de ligação média: lista de (grupo a, grupo b, distância) a cada fusão (o grupo novo recebe o próximo número, a partir de n)."""
    import numpy as np

    n = len(d)
    members: Dict[int, List[int]] = {i: [i] for i in range(n)}
    link = {(i, j): float(d[i, j]) for i in range(n) for j in range(i + 1, n)}
    nxt, merges = n, []
    while len(members) > 1:
        (a, b), h = min(link.items(), key=lambda kv: kv[1])
        merged = members.pop(a) + members.pop(b)
        merges.append((a, b, h))
        link = {k: v for k, v in link.items() if a not in k and b not in k}
        for k, mem in members.items():
            link[(k, nxt)] = float(np.mean(d[np.ix_(mem, merged)]))
        members[nxt] = merged
        nxt += 1
    return merges


def _cut(merges: List[Tuple[int, int, float]], n: int, k: int) -> List[int]:
    """Os rótulos 0..k-1 de cada item quando o agrupamento é cortado em k grupos."""
    parent = list(range(n + len(merges)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for m, (a, b, _) in enumerate(merges[:max(0, n - k)]):
        parent[find(a)] = parent[find(b)] = n + m
    roots: Dict[int, int] = {}
    return [roots.setdefault(find(i), len(roots)) for i in range(n)]


def pick_count(merges: List[Tuple[int, int, float]], n: int, limit: int = MAX_SPEAKERS) -> int:
    """Quantas vozes há: onde o agrupamento dá o maior salto de distância (a voz nova é bem mais distante que a variação normal de quem fala). Sem um salto claro, é uma voz só."""
    if n < 2 * MIN_RUN or len(merges) < 3:
        return 1
    heights = [h for _, _, h in merges]
    best_k, best_ratio = 1, 0.0
    for k in range(2, min(limit, n - 1) + 1):
        kept, avoided = heights[n - k - 1], heights[n - k]        # a última fusão feita para ficar com k grupos, e a próxima (que juntaria duas vozes)
        ratio = avoided / max(kept, 1e-9)
        if avoided >= JUMP_MIN and ratio >= JUMP_RATIO and ratio > best_ratio:
            best_k, best_ratio = k, ratio
    return best_k


def _smooth(labels: List[int]) -> List[int]:
    """Uma voz só vale com MIN_RUN janelas seguidas: o que é mais curto passa para o locutor da janela anterior (ou da seguinte, no começo)."""
    out = list(labels)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(out):
            j = i
            while j < len(out) and out[j] == out[i]:
                j += 1
            if j - i < MIN_RUN and (i > 0 or j < len(out)):
                fill = out[i - 1] if i > 0 else out[j]
                out[i:j] = [fill] * (j - i)
                changed = True
                break
            i = j
    return out


# ----------------------------------------------------------------------------- transcrição com locutores
def _split_text(text: str, fractions: List[float]) -> List[str]:
    """Reparte as palavras do texto em pedaços proporcionais às frações (a divisão cai onde a fração manda; aproximada)."""
    words = text.split()
    if len(fractions) == 1 or len(words) < len(fractions):
        return [text] + [""] * (len(fractions) - 1) if len(fractions) > 1 else [text]
    total = sum(fractions) or 1.0
    cuts, acc = [], 0.0
    for f in fractions[:-1]:
        acc += f / total
        cuts.append(max(1, min(len(words) - 1, int(round(acc * len(words))))))
    parts, prev = [], 0
    for c in cuts + [len(words)]:
        parts.append(" ".join(words[prev:c]))
        prev = c
    return parts


def label_segments(x: Any, segs: List[Dict[str, Any]], count: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """Põe «speaker» (0, 1, 2…, na ordem em que as vozes aparecem) em cada trecho. `count` = quantas vozes (0 = descobrir). Devolve (trechos, quantas vozes). Um trecho em que a voz troca vira dois."""
    import numpy as np

    total = len(x) / SR
    wins: List[Tuple[int, float, float, Any]] = []   # (índice do trecho, início, fim, vetor)
    for si, s in enumerate(segs):
        a, b = max(0.0, float(s["start"])), min(total, float(s["end"]))
        if b - a < MIN_SPEECH or not s["text"].strip():
            continue
        n = max(1, int(round((b - a) / WIN)))
        edges = np.linspace(a, b, n + 1)
        for i in range(n):
            f = window_features(x[int(edges[i] * SR):int(edges[i + 1] * SR)])
            if f is not None:
                wins.append((si, float(edges[i]), float(edges[i + 1]), f))
    if len(wins) < 2:
        return [dict(s, speaker=0) for s in segs], 1
    feats = [w[3] for w in wins]
    _fill_pitch(feats)
    m = np.vstack(feats)
    w = np.ones(m.shape[1])
    w[_CEPS - 1:2 * (_CEPS - 1)] = 0.5      # o desvio dos coeficientes pesa menos que a média
    w[-1] = PITCH_WEIGHT
    d = np.sqrt((((m[:, None, :] - m[None, :, :]) * w) ** 2).sum(axis=2))     # sem normalizar: assim uma voz só não é dividida à força
    merges = _linkage(d)
    k = max(1, min(MAX_SPEAKERS, int(count))) if count else pick_count(merges, len(wins))
    k = min(k, len(wins))
    labels = _cut(merges, len(wins), k) if k > 1 else [0] * len(wins)
    # a ordem dos locutores é a do primeiro aparecimento; trechos sem janela herdam o locutor do anterior
    order: Dict[int, int] = {}
    labels = _smooth(labels) if k > 1 else labels
    for lb in labels:
        order.setdefault(lb, len(order))
    by_seg: Dict[int, List[Tuple[float, float, int]]] = {}
    for (si, a, b, _), lb in zip(wins, labels):
        by_seg.setdefault(si, []).append((a, b, order[lb]))
    out: List[Dict[str, Any]] = []
    last = 0
    for si, s in enumerate(segs):
        runs: List[List[Any]] = []
        for a, b, sp in by_seg.get(si, []):
            if runs and runs[-1][2] == sp:
                runs[-1][1] = b
            else:
                runs.append([a, b, sp])
        if not runs:
            out.append(dict(s, speaker=last))
            continue
        if len(runs) == 1:
            last = runs[0][2]
            out.append(dict(s, speaker=last))
            continue
        parts = _split_text(s["text"], [r[1] - r[0] for r in runs])
        for r, txt in zip(runs, parts):
            if txt.strip():
                out.append({"start": round(r[0], 3), "end": round(r[1], 3), "text": txt.strip(), "speaker": r[2]})
                last = r[2]
    return out, len(order)


# ----------------------------------------------------------------------------- nomes
def parse_names(text: str) -> List[str]:
    """«Ana, Bruno; Carla» → ["Ana", "Bruno", "Carla"] (a ordem é a do primeiro aparecimento de cada voz)."""
    return [n.strip()[:30] for n in re.split(r"[,;\n]", text or "") if n.strip()][:MAX_SPEAKERS]


def speaker_name(index: int, names: List[str]) -> str:
    return names[index] if 0 <= index < len(names) else f"{LABEL} {index + 1}"
