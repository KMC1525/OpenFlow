"""v0.45: computadores de 16 GB (DDR4 e DDR5) — planejador de memória por classe de RAM (núcleo Rust + espelho em Python), integrado ao modelo de texto, à mídia e à tela de desempenho."""
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow import native, perf
from openflow.canvas import media as M
from openflow.providers import local_llama as LL
from tests.helpers import ServerCase

ROOT = Path(__file__).resolve().parent.parent
G = 1 << 30


def python_only():
    return mock.patch.object(native, "_lib7", return_value=None)


class PlanTests(unittest.TestCase):
    def plan(self, total=16 * G, avail=10 * G, w=6 * G, other=0, kv=1 << 18, ty=2, mts=3200, ch=2, phys=8, mode=1):
        with python_only():
            return native.plan_ram(total, avail, w, other, kv, ty, mts, ch, phys, mode)

    def test_the_16gb_class_reserves_for_the_system(self):
        r = self.plan()
        self.assertEqual(r["class"], "16")
        self.assertGreater(r["reserve"], int(3.4 * G))
        self.assertLess(r["budget"], 16 * G - r["reserve"] + 1)
        self.assertEqual(self.plan(total=8 * G, avail=5 * G, w=2 * G)["class"], "small")
        self.assertEqual(self.plan(total=64 * G, avail=50 * G)["class"], "large")
        self.assertEqual(self.plan(total=0, avail=0, w=0)["class"], "unknown")

    def test_the_other_model_leaves_the_ram_only_when_both_do_not_fit(self):
        self.assertFalse(self.plan(avail=10 * G, w=6 * G, other=0)["evict_other"])
        self.assertFalse(self.plan(avail=10 * G, w=3 * G, other=5 * G)["evict_other"])
        r = self.plan(avail=4 * G, w=8 * G, other=7 * G)
        self.assertTrue(r["evict_other"])
        self.assertTrue(any("sai da memória" in n for n in r["notes"]))

    def test_ddr5_and_dual_channel_get_more_threads_and_bigger_batches_than_ddr4_single(self):
        d4 = self.plan(w=4 * G, ty=2, mts=3200, ch=2)
        d5 = self.plan(w=4 * G, ty=3, mts=5600, ch=2)
        s1 = self.plan(w=4 * G, ty=2, mts=3200, ch=1)
        self.assertEqual((d4["n_batch"], d5["n_batch"]), (256, 512))
        self.assertGreater(d5["bw_gbs"], d4["bw_gbs"] * 1.5)
        self.assertGreaterEqual(d5["useful_threads"], d4["useful_threads"])
        self.assertGreater(d4["useful_threads"], s1["useful_threads"])
        self.assertTrue(any("canal único" in n for n in s1["notes"]))

    def test_tight_loads_compress_the_cache_and_shrink_the_batches(self):
        r = self.plan(avail=9 * G, w=7 * G)
        self.assertTrue(r["tight"] and r["kv_q8"])
        self.assertEqual((r["n_batch"], r["n_ubatch"]), (128, 128))
        self.assertEqual(r["idle_s"], 120)
        self.assertFalse(r["mlock"])
        roomy = self.plan(avail=13 * G, w=2 * G, ty=3, mts=5600)
        self.assertFalse(roomy["tight"] or roomy["kv_q8"])

    def test_context_cap_follows_the_room_that_is_left(self):
        small = self.plan(avail=9 * G, w=6 * G, kv=1 << 19)["ctx_cap"]
        big = self.plan(avail=13 * G, w=3 * G, kv=1 << 19)["ctx_cap"]
        self.assertGreater(big, small)
        self.assertGreaterEqual(small, 512)
        self.assertEqual(small % 256, 0)

    def test_media_options_only_for_small_and_16gb_classes(self):
        m = self.plan(avail=8 * G, w=6 * G)
        self.assertTrue(m["media_low_cpu_mem"] and m["media_sequential"] and m["media_slicing"] and m["media_tiling"])
        big = self.plan(total=64 * G, avail=50 * G, w=6 * G, ty=3, mts=6000, phys=16)
        self.assertFalse(big["media_low_cpu_mem"] or big["media_sequential"] or big["media_slicing"])


def _rust_lib():
    p = ROOT / "openflow" / "native" / "target" / "release" / "libopenflow_core.so"
    if p.is_file():
        return p
    if shutil.which("cargo") and os.environ.get("OPENFLOW_TEST_BUILD_RUST", "1") != "0":
        r = subprocess.run(["cargo", "build", "--release", "--offline"], cwd=str(ROOT / "openflow" / "native"), capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and p.is_file():
            return p
    return None


@unittest.skipUnless(os.name == "posix" and _rust_lib(), "núcleo Rust não compilado")
class RustParityTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"OPENFLOW_NATIVE_LIB": str(_rust_lib())})
        patcher.start()
        self.addCleanup(patcher.stop)
        native._LIB, native._TRIED = None, False
        self.addCleanup(lambda: (setattr(native, "_LIB", None), setattr(native, "_TRIED", False)))
        if native._lib7() is None:
            self.skipTest("a biblioteca compilada não tem a interface 7")

    def test_rust_and_python_plans_are_identical(self):
        rnd = random.Random(45)
        for _ in range(400):
            args = (rnd.choice([0, 4 * G, 8 * G, 12 * G, 16 * G, 24 * G, 32 * G, 64 * G]), rnd.randint(0, 40) * G // 2, rnd.randint(0, 30) * G // 2, rnd.choice([0, 0, 3 * G, 7 * G]),
                    rnd.choice([0, 1 << 16, 1 << 18, 1 << 20]), rnd.randint(0, 4), rnd.choice([0, 2133, 2666, 3200, 4800, 5600, 6400]), rnd.randint(0, 5), rnd.randint(0, 24), rnd.randint(0, 2))
            rust = native.plan_ram(*args)
            with python_only():
                py = native.plan_ram(*args)
            self.assertEqual(rust, py, args)

    def test_abi_is_7_and_older_libraries_are_still_accepted_by_the_loader(self):
        self.assertEqual(native.ABI, 7)
        self.assertEqual(int(native.load().flow_abi_version()), 7)


class IntegrationTests(unittest.TestCase):
    def fake_ram(self, **over):
        base = {"class": "16", "reserve": 3.5 * G, "budget": 9 * G, "tight": False, "evict_other": False, "fits": True, "ctx_cap": 6144, "kv_q8": False, "mlock": False, "prefetch": True, "bw_gbs": 38.4,
                "useful_threads": 4, "n_batch": 256, "n_ubatch": 128, "idle_s": 300, "media_low_cpu_mem": True, "media_sequential": False, "media_slicing": True, "media_tiling": True, "notes": []}
        base.update(over)
        return base

    def llm_plan(self):
        return {"n_ctx": 16384, "ctx_max": 16384, "n_gpu_layers": 0, "gpu_layers_fit": 0, "n_threads": 8, "n_threads_batch": 12, "n_batch": 512, "n_ubatch": 512, "kv_q8": False, "kv_q4": False,
                "flash": False, "mlock": True, "prefetch": True, "cache_bytes": 1 << 30, "notes": []}

    def test_the_text_plan_is_trimmed_to_the_ram_that_is_left(self):
        plan = self.llm_plan()
        with mock.patch.object(perf, "ram_plan", return_value=self.fake_ram(tight=True, kv_q8=True, mlock=False, prefetch=False)):
            LL._apply_ram(plan, {"bytes": 6 * G, "layers": 32, "kv_bytes_per_token": 1 << 17}, 16384, False)
        self.assertEqual((plan["n_ctx"], plan["n_batch"], plan["n_ubatch"], plan["n_threads"]), (6144, 256, 128, 4))
        self.assertTrue(plan["kv_q8"] and plan["flash"])
        self.assertFalse(plan["mlock"] or plan["prefetch"])
        self.assertLessEqual(plan["cache_bytes"], 128 << 20)
        self.assertTrue(any("16 GB" in n for n in plan["notes"]))

    def test_an_explicit_context_is_never_shrunk(self):
        plan = self.llm_plan()
        with mock.patch.object(perf, "ram_plan", return_value=self.fake_ram()):
            LL._apply_ram(plan, {"bytes": 4 * G, "layers": 32, "kv_bytes_per_token": 1 << 17}, 16384, True)
        self.assertEqual(plan["n_ctx"], 16384)

    def test_big_machines_are_left_alone_and_the_gpu_part_does_not_count(self):
        plan = self.llm_plan()
        with mock.patch.object(perf, "ram_plan", return_value=self.fake_ram(**{"class": "large"})):
            LL._apply_ram(plan, {"bytes": 6 * G, "layers": 32}, 16384, False)
        self.assertEqual((plan["n_ctx"], plan["n_batch"]), (16384, 512))
        seen = {}
        with mock.patch.object(perf, "ram_plan", side_effect=lambda w, kv=0, other=0: seen.update(w=w) or {}):
            LL._apply_ram(dict(self.llm_plan(), n_gpu_layers=-1), {"bytes": 10 * G, "layers": 40}, 4096, False)
        self.assertAlmostEqual(seen["w"], 10 * G * 0.15, delta=10)   # tudo na placa: só ~15% fica na RAM

    def test_the_media_model_leaves_the_ram_when_the_text_model_would_not_fit_with_it(self):
        gone = []
        plan = {"strategy": "cpu", "slicing": False, "tiling": False, "prefetch": True}
        with mock.patch.object(perf, "ram_plan", return_value=self.fake_ram(evict_other=True, prefetch=False)), mock.patch.object(LL, "_unload", lambda: gone.append(1)):
            M._apply_ram(plan, 6 * G)
        self.assertEqual(gone, [1])
        self.assertTrue(plan["slicing"] and plan["tiling"])
        self.assertFalse(plan["prefetch"])

    def test_and_the_text_model_asks_the_media_model_to_leave(self):
        gone = []
        with mock.patch.object(perf, "ram_plan", return_value=self.fake_ram(evict_other=True)), mock.patch.object(M, "_media_unload", lambda: gone.append(1)):
            LL._apply_ram(self.llm_plan(), {"bytes": 8 * G, "layers": 32}, 4096, False)
        self.assertEqual(gone, [1])

    def test_resident_bytes_count_only_loaded_models(self):
        tmp = Path(tempfile.mkdtemp()) / "m.gguf"
        tmp.write_bytes(b"x" * 1000)
        with mock.patch.dict(LL._PATHS, {"k": str(tmp)}, clear=False):
            self.assertGreaterEqual(LL.resident_bytes(), 1000)
        with mock.patch.dict(M._PLAN, {"weights": 5 * G}):
            with mock.patch.dict(M._LOCAL_CACHE, {}, clear=True):
                self.assertEqual(M.resident_bytes(), 0)
            with mock.patch.dict(M._LOCAL_CACHE, {("image", "m"): object()}, clear=True):
                self.assertEqual(M.resident_bytes(), 5 * G)

    def test_ram_plan_failures_never_break_loading(self):
        with mock.patch.object(native, "plan_ram", side_effect=RuntimeError("x")):
            self.assertEqual(perf.ram_plan(4 * G), {})
        plan = self.llm_plan()
        before = dict(plan)
        with mock.patch.object(perf, "ram_plan", return_value={}):
            LL._apply_ram(plan, {"bytes": 4 * G, "layers": 32}, 4096, False)
        self.assertEqual(plan, before)


class ApiTests(ServerCase):
    def test_the_cpu_report_has_the_ram_plan(self):
        s, r = self.c.json("GET", "/api/cpu")
        self.assertEqual(s, 200)
        self.assertIn("ram", r)
        if r["ram"]:
            self.assertIn(r["ram"]["class"], ("small", "16", "large", "unknown"))


if __name__ == "__main__":
    unittest.main()
