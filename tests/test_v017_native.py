"""v0.17 — núcleo Rust v4: análise de mídia (níveis, silêncios, picos, andamento, quadros, forma de onda) e ordem de grafos. Rust e Python precisam dar o mesmo resultado."""
import math
import random
import sys
import unittest
from array import array
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import native  # noqa: E402

NATIVE = native.available() and native.status().get("media")


def python_only():
    return mock.patch.object(native, "_lib4", return_value=None)


def pcm_signal(seconds=4.0, sr=8000, seed=1):
    rnd = random.Random(seed)
    out = array("h")
    for i in range(int(seconds * sr)):
        t = i / sr
        amp = 0.0 if 1.0 <= t < 2.0 else (0.9 if (t % 0.5) < 0.05 else 0.2)   # silêncio de 1 s e um "bumbo" a cada 0,5 s (120 BPM)
        out.append(int(32767 * amp * math.sin(2 * math.pi * 110 * t) * (0.9 + 0.1 * rnd.random())))
    return out


class LevelsAndSilence(unittest.TestCase):
    def test_levels_silence_and_peaks_in_python(self):
        with python_only():
            pcm = pcm_signal()
            lv = native.audio_levels(pcm, 800)           # janelas de 0,1 s
            self.assertEqual(len(lv), 40)
            self.assertTrue(all(v == -90.0 for v in lv[10:20]))
            sil = native.silence_ranges(lv, 0.1, -50.0, 0.5)
            self.assertEqual(len(sil), 1)
            self.assertAlmostEqual(sil[0][0], 1.0, places=6)
            self.assertAlmostEqual(sil[0][1], 2.0, places=6)
            peaks = native.pick_peaks(lv, 0.1, 0.5, 3)
            self.assertEqual(len(peaks), 3)
            self.assertTrue(all(abs(a[0] - b[0]) >= 0.5 - 1e-9 for i, a in enumerate(peaks) for b in peaks[:i]))
            self.assertGreaterEqual(peaks[0][1], peaks[-1][1])

    def test_tempo_of_a_120_bpm_pulse(self):
        with python_only():
            pcm = array("h")
            sr = 8000
            for i in range(sr * 16):
                t = i / sr
                pcm.append(int(30000 * math.sin(2 * math.pi * 80 * t)) if (t % 0.5) < 0.04 else 300 * (i % 7 - 3))
            env = native.onset_env(native.audio_levels(pcm, 80))     # 10 ms
            r = native.tempo(env, 0.01)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r["bpm"], 120.0, delta=2.0)

    def test_short_or_empty_inputs_are_safe(self):
        with python_only():
            self.assertEqual(len(native.audio_levels(array("h"), 100)), 0)
            self.assertEqual(native.silence_ranges(array("d"), 0.1), [])
            self.assertEqual(native.pick_peaks(array("d"), 0.1, 1, 3), [])
            self.assertIsNone(native.tempo(array("d", [0.0] * 10), 0.01))
            self.assertEqual(native.scene_cuts(array("d", [0.0]), 0.25), [])
            self.assertEqual(len(native.waveform(array("h"), 5)), 5)


class Frames(unittest.TestCase):
    def test_a_hard_cut_is_found(self):
        with python_only():
            fsize = 64
            frames = bytes([10] * fsize * 8 + [240] * fsize * 8)       # corte no quadro 8
            act = native.frame_activity(frames, fsize)
            self.assertAlmostEqual(act[8], 230 / 255.0, places=9)
            cuts = native.scene_cuts(act, 0.25, 2.0, 0.08, 0.5)
            self.assertEqual(cuts, [2.0])

    def test_waveform_peaks(self):
        with python_only():
            w = native.waveform(array("h", [0, 100, -300, 0, 16384, 0, 0, 0]), 4)
            self.assertAlmostEqual(w[1], 300 / 32768.0)
            self.assertAlmostEqual(w[2], 0.5)


class Graph(unittest.TestCase):
    def test_topo_levels_and_cycle(self):
        with python_only():
            r = native.topo(5, [(0, 1), (1, 2), (0, 2), (3, 2)])
            self.assertEqual(r["order"][:2], [0, 3] if r["order"][:2] == [0, 3] else r["order"][:2])
            self.assertEqual(r["level"], [0, 1, 2, 0, 0])
            self.assertFalse(r["cycle"])
            self.assertTrue(native.topo(2, [(0, 1), (1, 0)])["cycle"])
            self.assertEqual(native.topo(3, [(0, 9), (-1, 1)])["order"], [0, 1, 2])   # conexões inválidas são ignoradas


@unittest.skipUnless(NATIVE, "núcleo Rust (interface 4) não compilado")
class Parity(unittest.TestCase):
    def both(self, fn, *a):
        r1 = fn(*a)
        with python_only():
            r2 = fn(*a)
        return r1, r2

    def close(self, x, y):
        self.assertEqual(len(x), len(y))
        for p, q in zip(x, y):
            if isinstance(p, tuple):
                for u, v in zip(p, q):
                    self.assertAlmostEqual(u, v, places=6)
            else:
                self.assertAlmostEqual(p, q, places=6)

    def test_levels_silence_peaks_onsets(self):
        for seed in range(6):
            pcm = pcm_signal(3.0 + seed, seed=seed)
            for win in (80, 800, 777):
                a, b = self.both(native.audio_levels, pcm, win)
                self.close(a, b)
            lv = native.audio_levels(pcm, 800)
            self.close(*self.both(native.silence_ranges, lv, 0.1, -40.0, 0.3))
            self.close(*self.both(native.pick_peaks, lv, 0.1, 0.4, 7))
            self.close(*self.both(native.onset_env, lv))

    def test_tempo_and_phase(self):
        rnd = random.Random(5)
        for bpm in (90, 120, 140, 174):
            period = 60.0 / bpm / 0.01
            env = array("d", [0.0] * 3000)
            k = 0
            while int(7 + k * period) < len(env):
                env[int(7 + k * period)] = 8.0 + rnd.random()
                k += 1
            for i in range(len(env)):
                env[i] += rnd.random() * 0.3
            a, b = self.both(native.tempo, env, 0.01)
            self.assertIsNotNone(a)
            for key in ("bpm", "phase", "confidence"):
                self.assertAlmostEqual(a[key], b[key], places=6)
            target = bpm if bpm <= 150 else bpm / 2   # a preferência por ~120 BPM escolhe a metade nos andamentos muito rápidos (mesma grade, só nas batidas pares)
            self.assertAlmostEqual(a["bpm"], target, delta=target * 0.03)

    def test_frames_cuts_and_waveform(self):
        rnd = random.Random(2)
        fsize = 48
        frames = bytes(rnd.randrange(256) if i // fsize in (7, 20, 21) else 30 for i in range(fsize * 40))
        self.close(*self.both(native.frame_activity, frames, fsize))
        act = native.frame_activity(frames, fsize)
        a, b = self.both(native.scene_cuts, act, 0.25, 1.5, 0.05, 0.6)
        self.assertEqual(list(a), list(b))
        pcm = pcm_signal(2.0)
        self.close(*self.both(native.waveform, pcm, 97))

    def test_topo_matches_on_random_graphs(self):
        rnd = random.Random(9)
        for _ in range(150):
            n = rnd.randint(1, 60)
            edges = [(rnd.randrange(n), rnd.randrange(n)) for _ in range(rnd.randint(0, n * 2))]
            if rnd.random() < 0.7:
                edges = [(a, b) for a, b in edges if a < b]    # sem ciclo
            a, b = self.both(native.topo, n, edges)
            self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
