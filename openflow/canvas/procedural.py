"""Geradores procedurais (sem IA, sem rede, só biblioteca padrão) usados pelo provedor "Demo" do Canvas.

Servem para testar fluxos inteiros offline: imagens (paisagens abstratas guiadas pelas palavras do prompt), efeitos sonoros e música
sintetizados, uma "voz" de demonstração (balbucio, sem fala real) e vídeo (efeito Ken Burns sobre uma imagem, via ffmpeg se houver).
Tudo é determinístico: o mesmo prompt/estilo/seed gera o mesmo resultado.
"""
from __future__ import annotations

import array
import hashlib
import io
import math
import random
import re
import shutil
import struct
import subprocess
import tempfile
import wave
import zlib
from pathlib import Path
from typing import List, Optional, Tuple

from .. import native, perf
from ..providers.base import ProviderError

SR = 22050
RGB = Tuple[int, int, int]


def seed_of(*parts: object) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12], 16)


def parse_size(size: str, max_side: int = 1024) -> Tuple[int, int]:
    m = re.match(r"^(\d{2,5})x(\d{2,5})$", size or "")
    w, h = (int(m.group(1)), int(m.group(2))) if m else (768, 768)
    k = min(1.0, max_side / max(w, h))
    return max(64, int(w * k) // 2 * 2), max(64, int(h * k) // 2 * 2)


# --------------------------------------------------------------------------- imagens

def _png(w: int, h: int, buf: bytearray) -> bytes:
    raw = b"".join(b"\x00" + bytes(buf[y * w * 3:(y + 1) * w * 3]) for y in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _mix(a: RGB, b: RGB, t: float) -> RGB:
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def _hsv(h: float, s: float, v: float) -> RGB:
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


# (palavras, céu-topo, céu-base, chão, destaque, extra)
THEMES = [
    (("noite", "night", "estrela", "star", "lua", "moon", "madrugada"), (6, 8, 30), (30, 40, 90), (10, 14, 40), (235, 235, 210), "stars"),
    (("pôr do sol", "por do sol", "sunset", "entardecer", "crepúsculo", "dusk", "amanhecer", "sunrise", "dawn", "horizonte"), (80, 40, 110), (255, 150, 90), (50, 30, 60), (255, 230, 170), "sun"),
    (("mar", "oceano", "ocean", "sea", "praia", "beach", "farol", "lighthouse", "navio", "ship", "onda"), (60, 130, 190), (170, 220, 235), (20, 70, 120), (255, 245, 190), "sea"),
    (("floresta", "forest", "bosque", "árvore", "arvore", "tree", "selva", "jungle", "mata"), (90, 150, 140), (200, 230, 200), (25, 70, 40), (255, 250, 200), "trees"),
    (("deserto", "desert", "areia", "sand", "duna", "egito", "egypt"), (240, 170, 90), (250, 220, 150), (190, 130, 60), (255, 240, 200), "dunes"),
    (("neve", "snow", "gelo", "ice", "inverno", "winter"), (140, 170, 210), (235, 242, 250), (225, 235, 245), (255, 255, 255), "trees"),
    (("espaço", "espaco", "space", "galáxia", "galaxy", "planeta", "planet", "astronauta", "astronaut", "nebulosa", "cosmos", "cristal"), (6, 4, 26), (60, 30, 110), (20, 12, 50), (160, 220, 255), "stars"),
    (("cidade", "city", "cyberpunk", "neon", "rua", "street", "urbano", "futurista"), (20, 20, 50), (110, 60, 140), (12, 12, 30), (255, 90, 190), "city"),
    (("fogo", "fire", "vulcão", "vulcao", "volcano", "lava", "dragão", "dragao", "dragon", "inferno"), (60, 8, 8), (230, 90, 30), (30, 8, 8), (255, 210, 90), "sun"),
]


class _Img:
    def __init__(self, w: int, h: int):
        self.w, self.h, self.buf = w, h, bytearray(w * h * 3)

    def gradient(self, top: RGB, bot: RGB, y0: int = 0, y1: Optional[int] = None) -> None:
        y1 = self.h if y1 is None else y1
        for y in range(y0, y1):
            row = bytes(_mix(top, bot, (y - y0) / max(1, y1 - y0 - 1))) * self.w
            self.buf[y * self.w * 3:(y + 1) * self.w * 3] = row

    def rect(self, x0: int, y0: int, x1: int, y1: int, c: RGB) -> None:
        x0, x1 = max(0, x0), min(self.w, x1)
        if x1 <= x0:
            return
        row = bytes(c) * (x1 - x0)
        for y in range(max(0, y0), min(self.h, y1)):
            self.buf[(y * self.w + x0) * 3:(y * self.w + x1) * 3] = row

    def circle(self, cx: float, cy: float, r: float, c: RGB) -> None:
        for y in range(max(0, int(cy - r)), min(self.h, int(cy + r) + 1)):
            dx = math.sqrt(max(0.0, r * r - (y - cy) ** 2))
            x0, x1 = max(0, int(cx - dx)), min(self.w, int(cx + dx) + 1)
            if x1 > x0:
                self.buf[(y * self.w + x0) * 3:(y * self.w + x1) * 3] = bytes(c) * (x1 - x0)

    def hills(self, base: float, amp: float, rnd: random.Random, c: RGB, step: int = 4) -> None:
        n = self.w // step + 2
        ph = [rnd.random() * 6.28 for _ in range(3)]
        hs = [base - amp * (0.5 + 0.28 * math.sin(i * step * 0.006 + ph[0]) + 0.2 * math.sin(i * step * 0.017 + ph[1]) + 0.08 * math.sin(i * step * 0.04 + ph[2])) for i in range(n)]
        for y in range(max(0, int(min(hs))), self.h):
            i = 0
            while i < n:
                if hs[i] <= y:
                    j = i
                    while j < n and hs[j] <= y:
                        j += 1
                    x0, x1 = i * step, min(self.w, j * step)
                    if x1 > x0:
                        self.buf[(y * self.w + x0) * 3:(y * self.w + x1) * 3] = bytes(c) * (x1 - x0)
                    i = j
                else:
                    i += 1

    def tri(self, cx: float, top: float, base: float, half: float, c: RGB) -> None:
        for y in range(max(0, int(top)), min(self.h, int(base))):
            k = (y - top) / max(1.0, base - top)
            x0, x1 = max(0, int(cx - half * k)), min(self.w, int(cx + half * k) + 1)
            if x1 > x0:
                self.buf[(y * self.w + x0) * 3:(y * self.w + x1) * 3] = bytes(c) * (x1 - x0)


def image(prompt: str, size: str = "768x768", seed: int = 0, style: str = "") -> bytes:
    """Paisagem abstrata determinística guiada pelas palavras do prompt (e do estilo)."""
    w, h = parse_size(size)
    low = f"{prompt} {style}".lower()
    rnd = random.Random(seed_of("img", prompt, style, seed))
    theme = next((t for t in THEMES if any(k in low for k in t[0])), None)
    if theme:
        _, top, bot, ground, accent, extra = theme
    else:
        hue = rnd.random()
        top, bot, ground, accent, extra = _hsv(hue, 0.55, 0.35), _hsv((hue + 0.08) % 1, 0.45, 0.85), _hsv((hue + 0.5) % 1, 0.5, 0.18), _hsv((hue + 0.12) % 1, 0.2, 1.0), rnd.choice(["sun", "stars", "trees"])
    img = _Img(w, h)
    img.gradient(top, bot, 0, int(h * 0.72))
    img.gradient(ground, _mix(ground, (0, 0, 0), 0.5), int(h * 0.72), h)
    if extra == "stars":
        for _ in range(int(w * h / 3500)):
            img.circle(rnd.random() * w, rnd.random() * h * 0.65, rnd.choice([0.8, 1.2, 1.8]), (235, 240, 255))
    cx, cy = w * (0.2 + 0.6 * rnd.random()), h * (0.16 + 0.2 * rnd.random())
    img.circle(cx, cy, h * (0.07 + 0.05 * rnd.random()) * (1.6 if extra == "sun" else 1), accent)
    if extra == "sea":
        img.gradient(_mix(top, (0, 40, 90), 0.5), (20, 70, 120), int(h * 0.62), int(h * 0.82))
        for i in range(10):
            yy = int(h * 0.63 + i * h * 0.02)
            img.rect(int(w * rnd.random() * 0.5), yy, int(w * (0.4 + rnd.random() * 0.6)), yy + 2, _mix((255, 255, 255), (150, 200, 230), 0.4))
    hill_cols = [_mix(bot, ground, 0.35), _mix(bot, ground, 0.62), _mix(bot, ground, 0.9)]
    for i, c in enumerate(hill_cols):
        img.hills(h * (0.62 + 0.09 * i), h * (0.18 - 0.03 * i), rnd, c)
    if extra == "trees":
        for _ in range(int(w / 28)):
            x, base = rnd.random() * w, h * (0.78 + 0.2 * rnd.random())
            s = h * (0.1 + 0.18 * rnd.random())
            img.rect(int(x - s * 0.04), int(base - s * 0.25), int(x + s * 0.04), int(base), (45, 30, 20))
            img.tri(x, base - s, base - s * 0.2, s * 0.32, _mix(ground, (20, 90, 50), 0.6 + 0.3 * rnd.random()))
    elif extra == "city":
        x = 0
        while x < w:
            bw, bh = int(w * (0.04 + 0.05 * rnd.random())), int(h * (0.12 + 0.35 * rnd.random()))
            img.rect(x, int(h * 0.78) - bh, x + bw, int(h * 0.78), _mix(ground, (60, 40, 90), 0.4))
            for wy in range(int(h * 0.78) - bh + 6, int(h * 0.78) - 6, 14):
                for wx in range(x + 5, x + bw - 6, 11):
                    if rnd.random() < 0.45:
                        img.rect(wx, wy, wx + 5, wy + 7, rnd.choice([accent, (255, 230, 150), (90, 220, 255)]))
            x += bw + int(w * 0.004)
    elif extra == "dunes":
        for i in range(3):
            img.hills(h * (0.8 + 0.07 * i), h * 0.1, rnd, _mix(ground, (255, 220, 150), 0.25 * (2 - i) / 2 + 0.1))
    return _png(w, h, img.buf)


def png_of(prompt: str, size: str = "512x512") -> bytes:
    return image(prompt, size)


# --------------------------------------------------------------------------- áudio

def wav_bytes(samples: List[float]) -> bytes:
    pcm = native.pcm16(samples)  # Rust quando existe (flow native build); senão Python — mesmo resultado
    bio = io.BytesIO()
    with wave.open(bio, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(pcm)
    return bio.getvalue()


def _env(n: int, a: float = 0.01, r: float = 0.2) -> List[float]:
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    return [min(1.0, i / na) * min(1.0, (n - i) / nr) for i in range(n)]


def _tone(freq: float, dur: float, wave_: str = "sine", vol: float = 0.5, sweep: Optional[float] = None) -> List[float]:
    return native.tone(freq, dur, wave_, vol, sweep, SR).tolist()


def _noise(dur: float, rnd: random.Random, vol: float = 0.4, lp: float = 0.2, decay: float = 0.0, lfo: float = 0.0) -> List[float]:
    return native.noise(dur, rnd, vol, lp, decay, lfo, SR).tolist()


def _mixdown(parts: List[List[float]], n: Optional[int] = None) -> List[float]:
    n = n or max((len(p) for p in parts), default=0)
    out = [0.0] * n
    for p in parts:
        for i, v in enumerate(p[:n]):
            out[i] += v
    return out


def _cat(*parts: List[float]) -> List[float]:
    out: List[float] = []
    for p in parts:
        out += p
    return out


SFX_WORDS = [
    (("explos", "explod", "bomba", "bomb", "boom", "estrondo"), "explosion"), (("laser", "tiro", "shoot", "blaster", "pew"), "laser"), (("moeda", "coin", "ouro", "gold", "pickup"), "coin"),
    (("pulo", "pular", "jump", "boing"), "jump"), (("soco", "punch", "hit", "pancada", "impacto", "impact", "bater"), "hit"), (("chuva", "rain", "garoa", "drizzle", "tempestade", "storm"), "rain"),
    (("vento", "wind", "ventania", "brisa"), "wind"), (("trovão", "trovao", "thunder", "trovejar"), "thunder"), (("onda", "wave", "mar ", "ocean", "oceano"), "waves"),
    (("passo", "step", "footstep", "andar", "walking"), "steps"), (("magia", "magic", "feitiço", "spell", "encant"), "magic"), (("alarme", "alarm", "sirene", "siren"), "alarm"),
    (("pássaro", "passaro", "bird", "canto", "chirp"), "bird"), (("porta", "door", "knock", "batida"), "knock"),
]


def _fx(kind: str, dur: float, rnd: random.Random) -> List[float]:
    if kind == "explosion":
        return _mixdown([_noise(min(dur, 1.6), rnd, 0.9, 0.12, 2.6), _tone(110, min(dur, 1.2), "sine", 0.7, 28)])
    if kind == "laser":
        return _cat(_tone(1500, 0.22, "saw", 0.35, 180), _tone(1300, 0.18, "saw", 0.3, 160))
    if kind == "coin":
        return _cat(_tone(988, 0.08, "square", 0.3), _tone(1319, 0.35, "square", 0.3))
    if kind == "jump":
        return _tone(260, 0.25, "square", 0.35, 760)
    if kind == "hit":
        return _mixdown([_noise(0.25, rnd, 0.9, 0.35, 14), _tone(160, 0.22, "sine", 0.8, 50)])
    if kind == "rain":
        return _noise(dur, rnd, 0.35, 0.55, 0, 0.3)
    if kind == "wind":
        return _noise(dur, rnd, 0.5, 0.05, 0, 0.18)
    if kind == "thunder":
        return _cat(_noise(0.4, rnd, 0.3, 0.08, 1.0), _noise(max(1.0, dur - 0.4), rnd, 0.95, 0.06, 1.7))
    if kind == "waves":
        return _noise(dur, rnd, 0.6, 0.07, 0, 0.14)
    if kind == "steps":
        out: List[float] = []
        while len(out) < dur * SR:
            out += _noise(0.07, rnd, 0.6, 0.2, 40) + [0.0] * int(SR * (0.32 + rnd.random() * 0.06))
        return out
    if kind == "magic":
        return _mixdown([_tone(f, 0.5, "sine", 0.22, f * 1.5) for f in (523, 659, 784, 1047)] + [_noise(0.5, rnd, 0.08, 0.7, 4)])
    if kind == "alarm":
        return _cat(*[_tone(880 if i % 2 == 0 else 660, 0.25, "square", 0.3) for i in range(max(2, int(dur / 0.25)))])
    if kind == "bird":
        return _cat(*[_tone(2400 + rnd.random() * 900, 0.09, "sine", 0.3, 3300 + rnd.random() * 600) + [0.0] * int(SR * 0.05) for _ in range(rnd.randint(3, 6))])
    if kind == "knock":
        return _cat(*[_mixdown([_noise(0.09, rnd, 0.9, 0.12, 30), _tone(140, 0.1, "sine", 0.7, 90)]) + [0.0] * int(SR * 0.16) for _ in range(3)])
    return _cat(*[_tone(300 + rnd.random() * 700, 0.1, "square", 0.25) for _ in range(5)])


def sound_fx(prompt: str, duration: float = 4.0, seed: int = 0) -> bytes:
    rnd = random.Random(seed_of("fx", prompt, seed))
    low = f" {prompt.lower()} "
    kinds = [k for words, k in SFX_WORDS if any(w in low for w in words)][:3] or ["blip"]
    parts = [_fx(k, max(0.5, min(duration, 30)), rnd) for k in kinds]
    out = _mixdown(parts, int(min(30.0, max(0.5, duration)) * SR) if any(k in ("rain", "wind", "waves") for k in kinds) else None)
    return wav_bytes(out)


MOODS = [
    (("triste", "sad", "melanc", "saudade", "nostalg", "chor"), ("minor", 62, 0.9)), (("tenso", "tense", "suspense", "terror", "horror", "perigo", "danger", "dark", "sombrio"), ("phrygian", 96, 1.0)),
    (("épico", "epico", "epic", "batalha", "battle", "heroi", "hero", "aventura"), ("minor", 118, 1.2)), (("alegre", "happy", "feliz", "festa", "party", "joy", "divertid", "fun"), ("major", 124, 1.1)),
    (("misterio", "mystery", "mágic", "magic", "sonho", "dream", "espaço", "space"), ("dorian", 78, 0.9)), (("calm", "relax", "paz", "peace", "ambient", "suave", "soft", "lofi", "lo-fi"), ("pentatonic", 72, 0.8)),
]
SCALE = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "dorian": [0, 2, 3, 5, 7, 9, 10], "phrygian": [0, 1, 3, 5, 7, 8, 10], "pentatonic": [0, 2, 4, 7, 9]}


def music(prompt: str, duration: float = 20.0, seed: int = 0) -> bytes:
    """Música generativa (acordes, baixo e melodia) cujo clima segue as palavras do prompt."""
    rnd = random.Random(seed_of("mus", prompt, seed))
    low = prompt.lower()
    scale_name, bpm, density = next((m for words, m in MOODS if any(w in low for w in words)), ("major", 90, 1.0))
    sc = SCALE[scale_name]
    root = 48 + rnd.randrange(0, 7)
    beat = 60.0 / bpm
    total = int(min(120.0, max(2.0, duration)) * SR)
    hz = lambda n: 440.0 * 2 ** ((n - 69) / 12)  # noqa: E731
    note = lambda deg, octv: root + sc[deg % len(sc)] + 12 * (deg // len(sc) + octv)  # noqa: E731
    prog = [0, 5, 3, 4] if scale_name == "major" else [0, 5, 2, 4]
    out = native.zeros(total)  # buffer de doubles (8 bytes/amostra) em vez de uma lista de objetos float
    t, bar = 0.0, 0
    while int(t * SR) < total:
        d = prog[bar % len(prog)]
        for deg, vol, wf in ((d, 0.16, "triangle"), (d + 2, 0.10, "sine"), (d + 4, 0.10, "sine")):
            native.mix_add(out, native.tone(hz(note(deg, 0)), beat * 4, wf, vol, None, SR), int(t * SR))
        seg = native.tone(hz(note(d, -1)), beat * 2, "sine", 0.22, None, SR)
        for k in (0, 2):
            native.mix_add(out, seg, int((t + k * beat) * SR))
        for s in range(8):
            if rnd.random() < 0.55 * density:
                deg = d + rnd.choice([0, 2, 4, 7, 4, 2, 1])
                native.mix_add(out, native.tone(hz(note(deg, 2)), beat * 0.9, "triangle", 0.12, None, SR), int((t + s * beat / 2) * SR))
        t += beat * 4
        bar += 1
    native.fade_out(out, int(min(1.5, duration / 4) * SR))
    return wav_bytes(out)


VOWELS = {"a": (800, 1200), "e": (500, 1800), "i": (320, 2300), "o": (500, 900), "u": (330, 800)}


def babble(text: str, speed: float = 1.0, seed: int = 0) -> bytes:
    """Voz de DEMONSTRAÇÃO: um balbucio que acompanha o ritmo do texto (não é fala real; use um provedor de voz para isso)."""
    rnd = random.Random(seed_of("voice", text, seed))
    base = 150 + (seed_of("pitch", text[:12], seed) % 90)
    sylls = max(1.0, speed)
    out: List[float] = []
    for ch in text.lower()[:1200]:
        if ch in VOWELS or ch in "áàâãéêíóôõúü":
            v = {"á": "a", "à": "a", "â": "a", "ã": "a", "é": "e", "ê": "e", "í": "i", "ó": "o", "ô": "o", "õ": "o", "ú": "u", "ü": "u"}.get(ch, ch)
            f1, f2 = VOWELS[v]
            f0 = base * (1 + 0.18 * math.sin(len(out) / 4000) + rnd.uniform(-0.04, 0.04))
            n = int(0.085 / sylls * SR)
            seg = []
            for i in range(n):
                tt = i / SR
                s = 0.5 * math.sin(2 * math.pi * f0 * tt) + 0.25 * math.sin(2 * math.pi * f1 * tt) * math.exp(-tt * 18) + 0.18 * math.sin(2 * math.pi * f2 * tt) * math.exp(-tt * 25)
                seg.append(s)
            e = _env(n, 0.01, 0.03)
            out += [a * b for a, b in zip(seg, e)]
        elif ch.isalpha():
            out += _noise(0.03 / sylls, rnd, 0.22, 0.6, 20)
        elif ch in ".!?":
            out += [0.0] * int(SR * 0.28 / sylls)
        elif ch in ",;:":
            out += [0.0] * int(SR * 0.14 / sylls)
        elif ch.isspace():
            out += [0.0] * int(SR * 0.05 / sylls)
    return wav_bytes(out or [0.0] * int(SR * 0.3))


# --------------------------------------------------------------------------- vídeo (ffmpeg)

def ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def video_from_image(png: bytes, seconds: int, size: Tuple[int, int], fps: int = 24, seed: int = 0) -> bytes:
    """Efeito Ken Burns (zoom/pan suave) sobre uma imagem → MP4. Requer ffmpeg."""
    ff = ffmpeg_path()
    if not ff:
        raise ProviderError("O vídeo do provedor Demo precisa do ffmpeg (instale-o) — ou configure um provedor de vídeo na aba Mídia.")
    w, h = size[0] // 2 * 2, size[1] // 2 * 2
    frames = max(2, int(seconds * fps))
    rnd = random.Random(seed)
    zx, zy = (0.5 + (rnd.random() - 0.5) * 0.3), (0.5 + (rnd.random() - 0.5) * 0.3)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "i.png", Path(tmp) / "o.mp4"
        src.write_bytes(png)
        vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
              f"zoompan=z='min(zoom+0.0012,1.28)':x='(iw-iw/zoom)*{zx:.2f}':y='(ih-ih/zoom)*{zy:.2f}':d={frames}:s={w}x{h}:fps={fps},format=yuv420p")
        r = perf.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(dst)], capture_output=True, timeout=300)
        if r.returncode != 0 or not dst.exists():
            raise ProviderError("ffmpeg falhou ao gerar o vídeo: " + r.stderr.decode("utf-8", "replace")[-300:])
        return dst.read_bytes()


# --------------------------------------------------------------------------- texto (LLM de demonstração)

def demo_llm(instruction: str, source: str, styles: str = "") -> str:
    """"Texto IA" offline: reescreve o prompt acrescentando detalhes visuais (útil para encadear com nós de imagem)."""
    base = (source or instruction or "").strip()
    rnd = random.Random(seed_of("llm", base, instruction))
    extras = rnd.sample(["luz suave", "composição cinematográfica", "alto nível de detalhe", "profundidade de campo", "cores equilibradas", "atmosfera envolvente", "texturas realistas"], 3)
    out = f"{base}. " + ", ".join(extras).capitalize() + "."
    if instruction.strip() and source.strip():
        out = f"[{instruction.strip()}] " + out
    if styles:
        out += f" Estilo: {styles}."
    return out
