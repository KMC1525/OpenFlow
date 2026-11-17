"""Remover marca d'água (v0.70): onde ela está e como apagar.

A remoção em si é do ffmpeg: o filtro `delogo` refaz a área escolhida a partir dos pixels em volta (e o `removelogo`, a partir de uma máscara que você liga ao nó). Isso funciona bem em marcas pequenas sobre fundos
suaves e deixa uma mancha borrada onde o fundo tem detalhe — não é um modelo de pintura (inpainting) e não «adivinha» o que havia por baixo.

Aqui fica a parte sem ffmpeg: a conta da área (canto ou caixa, em % do quadro, já ajustada aos limites que o `delogo` aceita) e a detecção automática em vídeo (numpy): uma marca fixa é o que não se mexe,
com bordas, enquanto o resto do vídeo muda. Um vídeo quase parado (slides, câmera presa) não permite distinguir a marca do fundo, e a detecção avisa em vez de chutar.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional, Tuple

Box = Tuple[int, int, int, int]   # x, y, largura, altura (px)


def region(where: str, pos: str, w_pct: float, h_pct: float, x_pct: float, y_pct: float, margin_pct: float, W: int, H: int) -> Box:
    """A área a refazer, em pixels. `corner`: um retângulo de w_pct × h_pct (% do quadro) no canto `pos`, afastado `margin_pct`%; `box`: x/y/largura/altura em % do quadro."""
    bw, bh = max(2, round(W * w_pct / 100)), max(2, round(H * h_pct / 100))
    if where == "box":
        x, y = round(W * x_pct / 100), round(H * y_pct / 100)
    else:
        mx, my = round(W * margin_pct / 100), round(H * margin_pct / 100)
        x = {"tl": mx, "bl": mx, "tr": W - bw - mx, "br": W - bw - mx, "center": (W - bw) // 2}.get(pos, W - bw - mx)
        y = {"tl": my, "tr": my, "bl": H - bh - my, "br": H - bh - my, "center": (H - bh) // 2}.get(pos, H - bh - my)
    return fit(x, y, bw, bh, W, H)


def fit(x: int, y: int, w: int, h: int, W: int, H: int) -> Box:
    """Ajusta a área aos limites do `delogo`: dentro do quadro e sem encostar nas bordas (uma faixa de 1 px em volta precisa existir)."""
    w, h = max(2, min(int(w), W - 2)), max(2, min(int(h), H - 2))
    x, y = max(1, min(int(x), W - w - 1)), max(1, min(int(y), H - h - 1))
    return x, y, w, h


def delogo_filter(box: Box) -> str:
    x, y, w, h = box
    return f"delogo=x={x}:y={y}:w={w}:h={h}"


def removelogo_filter(mask: Path) -> str:
    p = str(mask).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    return f"removelogo=filename={p}"


# ----------------------------------------------------------------------------- detecção automática (vídeo)
SAMPLE_W = 480
FRAMES = 14
CORNER_W, CORNER_H = 0.38, 0.32     # cada canto procurado: 38 % da largura × 32 % da altura
STATIC_STD = 6.0                    # variação (0–255) abaixo da qual um pixel conta como parado
EDGE_MIN = 14.0                     # e a borda (diferença para o vizinho) acima da qual conta como traço da marca


def sample_frames(path: Path, duration: float, W: int, H: int, ffmpeg: Optional[str] = None) -> Any:
    """Quadros em cinza espalhados pelo vídeo, redimensionados para ≤ 480 px de largura: um vetor (quadros, altura, largura) ou None."""
    ff = ffmpeg or shutil.which("ffmpeg")
    try:
        import numpy as np
    except ImportError:
        return None
    if not ff or W < 16 or H < 16:
        return None
    sw = min(SAMPLE_W, W) // 2 * 2
    sh = max(2, round(H * sw / W) // 2 * 2)
    rate = FRAMES / max(float(duration or 0), 1.0)
    try:
        r = subprocess.run([ff, "-v", "error", "-i", str(path), "-an", "-vf", f"fps={rate:.5f},scale={sw}:{sh},format=gray", "-frames:v", str(FRAMES), "-f", "rawvideo", "-"], capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        return None
    n = len(r.stdout) // (sw * sh)
    if r.returncode != 0 or n < 4:
        return None
    return np.frombuffer(r.stdout[:n * sw * sh], dtype="uint8").reshape(n, sh, sw).astype("float32")


def detect(frames: Any, W: int, H: int) -> Tuple[Optional[Box], str]:
    """A marca fixa nos cantos: (área em px do vídeo original, "") ou (None, motivo). A área é o retângulo dos pixels que não mudam e têm borda (letras, contornos), com uma folga em volta."""
    import numpy as np

    n, sh, sw = frames.shape
    std = frames.std(axis=0)
    mean = frames.mean(axis=0)
    edge = np.zeros_like(mean)
    edge[:, 1:] = np.maximum(edge[:, 1:], np.abs(np.diff(mean, axis=1)))
    edge[1:, :] = np.maximum(edge[1:, :], np.abs(np.diff(mean, axis=0)))
    static = std < STATIC_STD
    if static.mean() > 0.7:
        return None, "o vídeo quase não muda (slides, câmera parada): não dá para separar a marca do fundo. Escolha a área à mão."
    cand = static & (edge > EDGE_MIN)
    # linhas e colunas inteiras paradas são bordas pretas/molduras do vídeo, não marca
    cand[cand.mean(axis=1) > 0.6, :] = False
    cand[:, cand.mean(axis=0) > 0.6] = False
    cw, ch = int(sw * CORNER_W), int(sh * CORNER_H)
    best: Optional[Tuple[int, Box]] = None
    for ox, oy in ((0, 0), (sw - cw, 0), (0, sh - ch), (sw - cw, sh - ch)):
        sub = cand[oy:oy + ch, ox:ox + cw]
        count = int(sub.sum())
        if count < max(12, int(0.004 * cw * ch)):
            continue
        ys, xs = np.nonzero(sub)
        x0, x1 = int(np.percentile(xs, 1)), int(np.percentile(xs, 99))
        y0, y1 = int(np.percentile(ys, 1)), int(np.percentile(ys, 99))
        area = (x1 - x0 + 1) * (y1 - y0 + 1)
        if count / area < 0.03 or area > 0.8 * cw * ch:     # espalhado demais: textura do fundo, não marca
            continue
        if best is None or count > best[0]:
            best = (count, (ox + x0, oy + y0, x1 - x0 + 1, y1 - y0 + 1))
    if not best:
        return None, "não encontrei uma marca fixa nos cantos. Escolha a área à mão (ou ligue uma máscara)."
    x, y, w, h = best[1]
    pad = max(3, round(sw * 0.012))
    k = W / sw
    return fit(round((x - pad) * k), round((y - pad) * k), round((w + 2 * pad) * k), round((h + 2 * pad) * k), W, H), ""


def describe(box: Box, W: int, H: int) -> str:
    x, y, w, h = box
    return f"x {x * 100 / W:.0f}%, y {y * 100 / H:.0f}%, {w * 100 / W:.0f}% × {h * 100 / H:.0f}% do quadro"
