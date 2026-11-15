"""v0.28: CPU AMD/Intel (e ARM) para modelos locais — núcleos P/E, largura de banda da memória, planejador de threads/lotes e a estimativa de velocidade (Rust e Python dão o mesmo)."""
import os
import random
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from openflow import native, perf
from tests.helpers import ServerCase

ROOT = Path(__file__).resolve().parent.parent
GB = 1 << 30


class PlanTests(unittest.TestCase):
    """O planejador em Python (o que roda sem o núcleo Rust)."""

    def plan(self, *a):
        with mock.patch.object(native, "_lib5", return_value=None):
            return native.plan_cpu(*a)

    def test_weak_cpu_small_batches_and_speed_estimate(self):
        r = self.plan(4 * GB, 4096, 8.0, 12.0, 4, 0, 8, False, 2, 512, 8 * GB, 1)
        self.assertTrue(r["weak"])
        self.assertEqual((r["n_batch"], r["n_ubatch"], r["ctx_cap"], r["kv_q8"]), (128, 64, 4096, True))
        self.assertEqual(r["est_tps"], 2.0)                                       # 12 GB/s × 0,65 ÷ 4 GiB
        self.assertTrue(any("tokens/s" in n for n in r["notes"]))                 # avisa que é lento

    def test_strong_hybrid_cpu_uses_only_performance_cores(self):
        r = self.plan(4 * GB, 4096, 20.0, 60.0, 8, 8, 24, True, 2, 2048, 32 * GB, 1)
        self.assertFalse(r["weak"])
        self.assertEqual((r["n_threads_batch"], r["pin"], r["ctx_cap"]), (8, True, 0))
        self.assertLessEqual(r["n_threads"], 7)                                    # um núcleo de folga e só até saturar a memória
        self.assertTrue(any("híbrida" in n for n in r["notes"]))

    def test_generation_threads_stop_at_memory_saturation(self):
        # a memória satura com ~2 threads (40 ÷ 20): usar 12 só atrapalha
        r = self.plan(4 * GB, 4096, 20.0, 40.0, 12, 0, 24, False, 2, 2048, 32 * GB, 1)
        self.assertEqual(r["n_threads"], 3)
        self.assertEqual(r["n_threads_batch"], 12)                                 # a leitura do prompt usa todos

    def test_unknown_bandwidth_gives_no_estimate_but_still_plans(self):
        r = self.plan(4 * GB, 4096, 0, 0, 8, 0, 16, False, 2, 1024, 16 * GB, 1)
        self.assertEqual((r["est_tps"], r["max_gb_5tps"]), (0.0, 0.0))
        self.assertGreaterEqual(r["n_threads"], 1)

    def test_old_cpu_without_avx2_is_weak_and_warned(self):
        r = self.plan(2 * GB, 4096, 6.0, 10.0, 4, 0, 4, False, 1, 256, 8 * GB, 1)
        self.assertTrue(r["weak"])
        self.assertTrue(any("AVX2" in n for n in r["notes"]))
        self.assertFalse(r["flash"])

    def test_one_and_two_core_machines_use_all_cores(self):
        self.assertEqual(self.plan(GB, 2048, 5.0, 5.0, 2, 0, 2, False, 2, 512, 4 * GB, 0)["n_threads"], 2)
        self.assertEqual(self.plan(GB, 2048, 5.0, 5.0, 1, 0, 1, False, 2, 512, 4 * GB, 0)["n_threads"], 1)

    def test_cpu_list_parser(self):
        self.assertEqual(native._parse_cpu_list("0-3,8,10-11\n"), [0, 1, 2, 3, 8, 10, 11])
        self.assertEqual(native._parse_cpu_list("5-2"), [])

    def test_python_cpu_info_works_without_rust(self):
        with mock.patch.object(native, "_lib5", return_value=None):
            i = native.cpu_info()
        self.assertGreaterEqual(i["p_physical"], 1)
        self.assertIn(i["vendor"], ("intel", "amd", "other"))
        self.assertIsNone(native.mem_bench()) if native._lib5() is None else None


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
        if native._lib5() is None:
            self.skipTest("a biblioteca compilada não tem a interface 5")

    def test_rust_and_python_plans_are_identical(self):
        rnd = random.Random(7)
        for _ in range(300):
            a = (rnd.choice([1 << 28, 2 * GB, 4 * GB, 8 * GB, 16 * GB]), 4096, rnd.choice([0, 3.0, 8.0, 12.0, 25.0]), rnd.choice([0, 5.0, 12.0, 40.0, 90.0]), rnd.choice([1, 2, 4, 6, 8, 12]),
                 rnd.choice([0, 4, 8, 16]), rnd.choice([4, 8, 16, 24]), rnd.choice([False, True]), rnd.choice([0, 1, 2, 3, 4]), rnd.choice([0, 256, 512, 1024, 2048]), rnd.choice([2 * GB, 8 * GB, 32 * GB]), rnd.choice([0, 1, 2]))
            rust = native.plan_cpu(*a)
            with mock.patch.object(native, "_lib5", return_value=None):
                py = native.plan_cpu(*a)
            self.assertEqual(rust, py, a)

    def test_rust_reports_the_cpu_and_measures_memory(self):
        i = native.cpu_info()
        self.assertGreaterEqual(i["p_physical"], 1)
        self.assertIn(i["simd"], (0, 1, 2, 3, 4))
        self.assertEqual(len(i["p_cpus"]) + len(i["e_cpus"]), i["p_logical"] + i["e_logical"])
        b = native.mem_bench(32, 2)
        self.assertGreater(b["bw1"], 0)
        self.assertGreaterEqual(b["bwn"], b["bw1"])


class TuningTests(unittest.TestCase):
    def test_cpu_tuning_uses_the_planner_and_never_raises(self):
        info = {"p_physical": 4, "e_physical": 0, "p_logical": 8, "e_logical": 0, "hybrid": False, "simd": 2, "l2_kb": 512, "p_cpus": list(range(8))}
        with mock.patch.object(native, "cpu_info", return_value=info), mock.patch.object(native, "cached_bench", return_value={"bw1": 8.0, "bwn": 12.0}), \
                mock.patch.object(perf, "memory_state", return_value={"ram_avail": 8 * GB}), mock.patch.object(native, "_lib5", return_value=None):
            r = perf.cpu_tuning(4 * GB, 4096, "balanced")
        self.assertTrue(r["weak"])
        self.assertEqual(r["info"]["p_physical"], 4)
        with mock.patch.object(native, "cpu_info", side_effect=RuntimeError("x")):
            self.assertEqual(perf.cpu_tuning(GB, 2048, "light"), {})

    def test_pinning_only_on_hybrid_linux_and_can_be_disabled(self):
        info = {"hybrid": True, "p_cpus": [0, 1, 2, 3]}
        calls = []
        fake = mock.patch.object(os, "sched_setaffinity", lambda pid, cpus: calls.append(sorted(cpus)), create=True)
        with fake, mock.patch.dict(perf._PINNED, {"done": False, "cpus": []}), mock.patch.dict(os.environ, {"OPENFLOW_CPU_PIN": "0"}):
            self.assertFalse(perf.pin_performance_cores(info))
        with fake, mock.patch.dict(perf._PINNED, {"done": False, "cpus": []}):
            self.assertTrue(perf.pin_performance_cores(info))
            self.assertEqual(calls, [[0, 1, 2, 3]])
            self.assertTrue(perf.pin_performance_cores(info))                       # só uma vez
            self.assertEqual(len(calls), 1)
        with fake, mock.patch.dict(perf._PINNED, {"done": False, "cpus": []}):
            self.assertFalse(perf.pin_performance_cores({"hybrid": False, "p_cpus": [0, 1]}))   # CPU comum: nada a fixar


class ApiTests(ServerCase):
    def test_cpu_report_and_settings(self):
        d = self.store.models_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / "tiny-Q4_K_M.gguf").write_bytes(b"x" * 1000)
        s, r = self.c.json("GET", "/api/cpu")
        self.assertEqual(s, 200, r)
        self.assertIn("brand", r["info"])
        self.assertIn(r["info"]["simd"], (0, 1, 2, 3, 4))
        self.assertTrue(any(m["name"] == "tiny-Q4_K_M.gguf" for m in r["models"]))
        s, st = self.c.json("PUT", "/api/settings", {"performance": {"cpu_pin": False}})
        self.assertEqual(st["performance"]["cpu_pin"], False)
        self.c.json("PUT", "/api/settings", {"performance": {"cpu_pin": True}})
