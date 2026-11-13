import os
import subprocess
import sys
import unittest
from array import array
from pathlib import Path

from openflow import native, perf
from openflow.providers import local_llama as ll

LIB = os.environ.get("OPENFLOW_NATIVE_LIB") or "/tmp/flow_target/release/libopenflow_core.so"
ROOT = Path(__file__).resolve().parent.parent


class PerfProfile(unittest.TestCase):
    def test_auto_follows_tier(self):
        self.assertEqual(perf.profile({}, {"tier": "low"})["mode"], "light")
        self.assertEqual(perf.profile({}, {"tier": "medium"})["mode"], "balanced")
        self.assertEqual(perf.profile({"mode": "auto"}, {"tier": "high"})["mode"], "max")
        self.assertEqual(perf.profile({"mode": "light"}, {"tier": "high"})["mode"], "light")

    def test_bad_values_do_not_crash(self):
        self.assertEqual(perf.profile({"mode": "??", "idle_unload_min": "x"}, {"tier": "low"})["mode"], "light")
        self.assertEqual(perf.profile(None, {})["mode"], "balanced")

    def test_context_cap_never_overrides_user(self):
        p = perf.profile({"mode": "light"}, {})
        self.assertEqual(perf.cap_context(32768, p, explicit=False), 4096)
        self.assertEqual(perf.cap_context(32768, p, explicit=True), 32768)
        self.assertEqual(perf.cap_context(32768, perf.profile({"mode": "max"}, {}), explicit=False), 32768)

    def test_light_unloads_sooner(self):
        self.assertLessEqual(perf.profile({"mode": "light", "idle_unload_min": 30}, {})["idle_s"], 180)
        self.assertEqual(perf.profile({"mode": "light", "idle_unload_min": 0}, {})["idle_s"], 0)

    def test_idle_unloader(self):
        import time
        hits = []
        u = perf.IdleUnloader(lambda: hits.append(1))
        u.touch(1)
        time.sleep(2.3)
        self.assertEqual(hits, [1])
        u.touch(0)  # desligado: não agenda nada


class LlamaLoad(unittest.TestCase):
    def test_falls_back_to_basic_kwargs(self):
        calls = []

        class Old:
            def __init__(self, **kw):
                calls.append(sorted(kw))
                if "flash_attn" in kw or "type_k" in kw:
                    raise TypeError("unexpected kwarg")
        prof = perf.profile({"mode": "light"}, {})
        ll._load_llama(Old, {"model_path": "x", "n_ctx": 512}, prof)
        self.assertGreaterEqual(len(calls), 2)
        self.assertNotIn("flash_attn", calls[-1])
        self.assertIn("n_batch", calls[-1])

    def test_light_asks_for_quantized_kv(self):
        seen = {}

        class New:
            def __init__(self, **kw):
                seen.update(kw)
        ll._load_llama(New, {"model_path": "x"}, perf.profile({"mode": "light"}, {}))
        self.assertEqual((seen["type_k"], seen["type_v"], seen["flash_attn"]), (8, 8, True))


class MuteModelRetry(unittest.TestCase):
    """Um modelo que fica mudo com flash attention/KV de 8 bits é recarregado só com o carregamento básico e responde."""

    def test_empty_stream_and_chat_reload_plain(self):
        import sys
        import tempfile

        loads = []

        class Llama:
            def __init__(self, **kw):
                self.mute = bool(kw.get("flash_attn") or kw.get("type_k"))
                loads.append(sorted(k for k in kw if k in ("flash_attn", "type_k", "n_batch")))

            def n_ctx(self):
                return 4096

            def tokenize(self, b, add_bos=False):
                return list(b)

            def create_chat_completion(self, messages, temperature=0.8, max_tokens=64, stream=False, **kw):
                if stream:
                    return iter([] if self.mute else [{"choices": [{"delta": {"content": "oi"}}]}, {"choices": [{"delta": {"content": " lá"}}]}])
                return {"choices": [{"message": {"content": "" if self.mute else "resposta"}}]}

        with tempfile.TemporaryDirectory() as d:
            m = Path(d) / "m.gguf"
            m.write_bytes(b"x")
            ll._CACHE.clear()
            ll._PLAIN.discard(str(m))
            fake = type(sys)("llama_cpp")
            fake.Llama = Llama
            from unittest import mock

            with mock.patch.dict(sys.modules, {"llama_cpp": fake}), mock.patch.object(ll, "hardware_info", return_value={"tier": "low", "ram_gb": 4, "cpus": 2, "gpu": "", "os": "Linux", "arch": "x86_64"}):
                p = ll.LocalLlamaProvider({"model": str(m), "models_dir": d, "performance": {"mode": "light"}})
                self.assertEqual("".join(p.chat([{"role": "user", "content": "oi"}], stream=True)), "oi lá")
                self.assertEqual(len(loads), 2)
                self.assertIn("flash_attn", loads[0])
                self.assertNotIn("flash_attn", loads[1])
                self.assertNotIn("type_k", loads[1])
                ll._PLAIN.discard(str(m))
                ll._CACHE.clear()
                self.assertEqual(p.chat([{"role": "user", "content": "oi"}]), "resposta")
            ll._CACHE.clear()
            ll._PLAIN.discard(str(m))


class Settings(unittest.TestCase):
    def test_default_and_conform(self):
        from openflow.storage import DEFAULT_SETTINGS, conform
        self.assertEqual(DEFAULT_SETTINGS["performance"]["mode"], "auto")
        self.assertEqual(conform(DEFAULT_SETTINGS, {"performance": "lixo"})["performance"]["mode"], "auto")


@unittest.skipUnless(Path(LIB).exists(), "biblioteca Rust não compilada")
class NativeEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["OPENFLOW_NATIVE_LIB"] = LIB
        native.load(force=True)
        assert native.available()

    @staticmethod
    def _ref(freq, dur, wave, vol, sr=44100):
        import math
        n = int(dur * sr)
        na, nr = max(1, int(0.005 * sr)), max(1, int(min(0.25, dur / 2) * sr))
        out, ph, tw = [], 0.0, 2 * math.pi
        for i in range(n):
            ph += tw * freq / sr
            fr = ph / tw % 1
            v = {"sine": math.sin(ph), "square": 1.0 if math.sin(ph) >= 0 else -1.0, "saw": 2 * fr - 1, "triangle": 2 * abs(2 * fr - 1) - 1}[wave]
            out.append(v * vol * min(1.0, i / na) * min(1.0, (n - i) / nr))
        return out

    def test_tone_matches_python(self):
        for wave in ("sine", "square", "saw", "triangle"):
            a, ref = native.tone(440.0, 0.05, wave, 0.5), self._ref(440.0, 0.05, wave, 0.5)
            self.assertEqual(len(a), len(ref), wave)
            # tolerância: nos saltos (quadrada/serra) um erro de fase minúsculo pode cair do outro lado
            bad = sum(1 for x, y in zip(a, ref) if abs(x - y) > 1e-6)
            self.assertLessEqual(bad, 3, wave)

    def test_pcm16_clips_and_sizes(self):
        b = native.pcm16(array("d", [0.0, 2.0, -2.0, 0.5]))
        self.assertEqual(len(b), 8)

    def test_mix_and_fade(self):
        dst = native.zeros(10)
        native.mix_add(dst, array("d", [1.0] * 4), 8)  # passa do fim: corta
        self.assertEqual(list(dst)[:8], [0.0] * 8)
        self.assertEqual(list(dst)[8:], [1.0, 1.0])
        buf = array("d", [1.0] * 100)
        native.fade_out(buf, 50)
        self.assertAlmostEqual(buf[0], 1.0)
        self.assertLess(buf[-1], 0.05)

    def test_music_native_vs_python_same_length(self):
        code = ("from openflow.canvas import procedural as p; r=p.music('calm piano',3,1); print(len(r))")
        out = []
        for env in ({"OPENFLOW_NATIVE_LIB": LIB}, {"OPENFLOW_NO_NATIVE": "1"}):
            r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env={**os.environ, **env, "PYTHONPATH": str(ROOT)})
            self.assertEqual(r.returncode, 0, r.stderr)
            out.append(r.stdout.strip())
        self.assertEqual(out[0], out[1])


class Cli(unittest.TestCase):
    def test_native_status_and_doctor(self):
        env = {**os.environ, "PYTHONPATH": str(ROOT), "OPENFLOW_NO_NATIVE": "1"}
        for args, needle in ((["native"], "Núcleo Rust"), (["doctor"], "Modo de desempenho")):
            r = subprocess.run([sys.executable, "-m", "openflow.cli", *args], cwd=ROOT, capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(needle, r.stdout)


if __name__ == "__main__":
    unittest.main()
