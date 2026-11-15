"""v0.29: placas de vídeo NVIDIA/AMD/Intel para modelos locais — detecção, planejador (Rust e Python iguais), llama.cpp só-CPU tratado como CPU e o sd-cli certo."""
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow import native, perf
from openflow.providers import local_llama
from tests.helpers import ServerCase
from tests.test_cpu_v028 import _rust_lib

GB = 1 << 30
MB = 1 << 20


def py_plan(*a):
    with mock.patch.object(native, "_lib6", return_value=None):
        return native.plan_gpu(*a)


class PlannerTests(unittest.TestCase):
    def test_small_card_keeps_the_cache_in_ram_for_more_layers(self):
        # 4 GiB de modelo, 32 camadas, cache de 1 GiB: com o cache na placa cabem menos camadas
        r = py_plan(4 * GB, 32, 131072, 8192, 4096 * MB, 4096 * MB, "nvidia", False, 0, 0, 16 * GB, 1)
        self.assertFalse(r["offload_kqv"])
        self.assertTrue(any("RAM" in n for n in r["notes"]))
        self.assertGreater(r["layers_fit"], 0)

    def test_roomy_card_runs_everything_on_the_card(self):
        r = py_plan(4 * GB, 32, 131072, 4096, 12288 * MB, 11000 * MB, "nvidia", False, 360.0, 40.0, 32 * GB, 1)
        self.assertEqual((r["n_gpu_layers"], r["offload_kqv"], r["flash"], r["use_gpu"]), (-1, True, True, True))
        self.assertGreater(r["est_tps"], r["est_tps_cpu"])                           # a placa rende mais que a CPU

    def test_vulkan_cards_do_not_get_flash_attention(self):
        for vendor in ("amd", "intel"):
            self.assertFalse(py_plan(2 * GB, 24, 65536, 4096, 8192 * MB, 8000 * MB, vendor, False, 0, 0, 16 * GB, 1)["flash"], vendor)

    def test_integrated_gpu_is_not_used_by_default(self):
        r = py_plan(2 * GB, 24, 65536, 4096, 8192 * MB, 6000 * MB, "intel", True, 0, 0, 16 * GB, 1)
        self.assertFalse(r["use_gpu"])
        self.assertTrue(any("integrada" in n for n in r["notes"]))

    def test_a_card_without_room_for_a_layer_says_so(self):
        r = py_plan(8 * GB, 32, 131072, 4096, 2048 * MB, 900 * MB, "nvidia", False, 0, 0, 16 * GB, 1)
        self.assertEqual((r["layers_fit"], r["use_gpu"]), (0, False))
        self.assertTrue(any("CPU" in n for n in r["notes"]))

    def test_small_cards_reserve_more_memory(self):
        small = py_plan(GB, 24, 65536, 2048, 4096 * MB, 4096 * MB, "nvidia", False, 0, 0, 16 * GB, 1)["reserve_mb"]
        big = py_plan(GB, 24, 65536, 2048, 12288 * MB, 12288 * MB, "nvidia", False, 0, 0, 16 * GB, 1)["reserve_mb"]
        self.assertGreater(small, big)

    def test_bandwidth_table(self):
        self.assertEqual(native.gpu_bandwidth("NVIDIA GeForce RTX 3060"), 360.0)
        self.assertEqual(native.gpu_bandwidth("NVIDIA GeForce RTX 3060 Ti"), 448.0)
        self.assertEqual(native.gpu_bandwidth("Navi 23 [Radeon RX 6600/6600 XT]"), 224.0)
        self.assertEqual(native.gpu_bandwidth("Placa Desconhecida"), 0.0)


@unittest.skipUnless(os.name == "posix" and _rust_lib(), "núcleo Rust não compilado")
class RustParityTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, {"OPENFLOW_NATIVE_LIB": str(_rust_lib())})
        p.start()
        self.addCleanup(p.stop)
        native._LIB, native._TRIED = None, False
        self.addCleanup(lambda: (setattr(native, "_LIB", None), setattr(native, "_TRIED", False)))
        if native._lib6() is None:
            self.skipTest("a biblioteca compilada não tem a interface 6")

    def test_rust_and_python_gpu_plans_are_identical(self):
        rnd = random.Random(11)
        for _ in range(400):
            tot = rnd.choice([0, 2 * GB, 4 * GB, 6 * GB, 8 * GB, 12 * GB, 24 * GB])
            a = (rnd.choice([GB, 2 * GB, 4 * GB, 8 * GB, 16 * GB]), rnd.choice([24, 32, 40]), rnd.choice([0, 65536, 131072]), rnd.choice([2048, 4096, 8192, 32768]), tot,
                 int(tot * rnd.choice([0.2, 0.6, 0.95])), rnd.choice(["nvidia", "amd", "intel", "apple"]), rnd.choice([False, True]), rnd.choice([0, 128.0, 360.0]), rnd.choice([0, 20.0, 50.0]),
                 rnd.choice([4 * GB, 16 * GB]), rnd.choice([0, 1, 2]))
            rust = native.plan_gpu(*a)
            self.assertEqual(rust, py_plan(*a), a)

    def test_gpu_info_is_a_list(self):
        self.assertIsInstance(native.gpu_info(), list)


class DetectionAndSupportTests(unittest.TestCase):
    GPUS = [{"index": 0, "vendor": "intel", "name": "Intel UHD", "integrated": True, "vram_total": 0, "vram_free": 0, "backend": "vulkan", "bw_gbs": 0},
            {"index": 1, "vendor": "amd", "name": "Navi 23 [Radeon RX 6600]", "integrated": False, "vram_total": 8 * GB, "vram_free": 7 * GB, "backend": "vulkan", "bw_gbs": 224.0}]

    def test_the_best_discrete_gpu_ignores_integrated_ones(self):
        with mock.patch.object(native, "gpu_info", return_value=self.GPUS):
            self.assertEqual(perf.best_discrete_gpu()["name"], "Navi 23 [Radeon RX 6600]")
            self.assertEqual(perf.gpu_tuning(4 * GB, 32, 131072, 4096, "balanced")["gpu"]["vendor"], "amd")

    def test_only_an_integrated_gpu_gives_a_plan_that_declines_it(self):
        with mock.patch.object(native, "gpu_info", return_value=self.GPUS[:1]), mock.patch.object(native, "cached_bench", return_value={}):
            r = perf.gpu_tuning(2 * GB, 24, 65536, 4096, "balanced")
        self.assertFalse(r["use_gpu"])

    def test_no_gpu_gives_no_plan(self):
        with mock.patch.object(native, "gpu_info", return_value=[]):
            self.assertEqual(perf.gpu_tuning(GB, 24, 65536, 4096, "balanced"), {})

    def test_vram_of_a_non_nvidia_card_feeds_the_planner(self):
        perf._GPU_CACHE["t"] = 0.0
        with mock.patch.object(perf.shutil, "which", return_value=None), mock.patch.object(native, "gpu_info", return_value=self.GPUS):
            total, free, unified = perf.gpu_memory(0, 0)
        perf._GPU_CACHE["t"] = 0.0
        self.assertEqual((total, free, unified), (8 * GB, 7 * GB, False))

    def test_llama_support_reading(self):
        fake = mock.Mock(llama_supports_gpu_offload=lambda: False)
        with mock.patch.dict(sys.modules, {"llama_cpp": fake}):
            self.assertEqual(native.llama_gpu_support(), {"installed": True, "offload": False})
        old = mock.Mock(spec=[])                                                       # versão sem a função: assume que funciona
        with mock.patch.dict(sys.modules, {"llama_cpp": old}):
            self.assertEqual(native.llama_gpu_support(), {"installed": True, "offload": True})

    def test_sd_cli_uses_vulkan_for_a_discrete_amd_or_intel_card(self):
        from openflow.canvas import sdcli

        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(sdcli, "_nvidia", return_value=False), mock.patch.object(sdcli.platform, "system", return_value="Linux"), \
                mock.patch.object(perf, "device", return_value="auto"):
            os.environ.pop("OPENFLOW_SD_BACKEND", None)
            with mock.patch.object(native, "gpu_info", return_value=self.GPUS):
                self.assertEqual(sdcli.backend(), "vulkan")
            with mock.patch.object(native, "gpu_info", return_value=self.GPUS[:1]):   # só integrada
                self.assertEqual(sdcli.backend(), "cpu")


class LlamaIntegrationTests(unittest.TestCase):
    """O modelo carrega como CPU quando o llama-cpp-python instalado não usa a placa."""

    def load(self, offload):
        loaded = []

        class FakeLlama:
            def __init__(self, **kw):
                loaded.append(kw)

        tmp = Path(tempfile.mkdtemp())
        model = tmp / "Qwen-Q4_K_M.gguf"
        model.write_bytes(b"x" * 1000)
        local_llama._CACHE.clear()
        local_llama._SUPPORT.clear()
        hw = {"tier": "medium", "ram_gb": 16, "cpus": 8, "gpu": "NVIDIA GeForce RTX 3060", "os": "Linux", "arch": "x86_64"}
        mem = {"ram_total": 16 * GB, "ram_avail": 12 * GB, "vram_total": 12 * GB, "vram_free": 11 * GB, "unified": False, "phys": 4, "logical": 8, "features": []}
        fake = mock.Mock(Llama=FakeLlama, llama_supports_gpu_offload=lambda: offload)
        info = {"bytes": 4 * GB, "layers": 32, "kv_bytes_per_token": 131072, "ctx_train": 8192, "arch": "llama"}
        from openflow.providers import provider_config

        with mock.patch.dict(sys.modules, {"llama_cpp": fake}), mock.patch.object(local_llama, "hardware_info", return_value=hw), mock.patch.object(local_llama.perf, "memory_state", return_value=mem), \
                mock.patch.object(native, "model_info", return_value=info), mock.patch.object(native, "gpu_info", return_value=[{"index": 0, "vendor": "nvidia", "name": "NVIDIA GeForce RTX 3060", "integrated": False,
                                                                                                                              "vram_total": 12 * GB, "vram_free": 11 * GB, "backend": "cuda", "bw_gbs": 360.0}]):
            cfg = provider_config({"providers": {"local_hf": {"model": str(model)}}}, "local_hf")
            local_llama.LocalLlamaProvider(cfg)._llm()
        local_llama._CACHE.clear()
        local_llama._SUPPORT.clear()
        return loaded[0]

    def test_cpu_only_build_is_planned_as_cpu(self):
        kw = self.load(False)
        self.assertEqual(kw["n_gpu_layers"], 0)
        self.assertIn("só CPU", native.LAST.get("gpu_note", ""))

    def test_a_gpu_build_offloads_everything_when_it_fits(self):
        kw = self.load(True)
        self.assertEqual(kw["n_gpu_layers"], -1)
        self.assertTrue(kw.get("offload_kqv", True))


class ApiTests(ServerCase):
    def test_gpu_report(self):
        gpus = [{"index": 0, "vendor": "amd", "name": "Navi 23 [Radeon RX 6600]", "integrated": False, "vram_total": 8 * GB, "vram_free": 7 * GB, "backend": "vulkan", "bw_gbs": 224.0}]
        d = self.store.models_dir
        d.mkdir(parents=True, exist_ok=True)
        (d / "tiny-Q4_K_M.gguf").write_bytes(b"x" * 1000)
        with mock.patch.object(native, "gpu_info", return_value=gpus), mock.patch.object(native, "llama_gpu_support", return_value={"installed": True, "offload": False}):
            s, r = self.c.json("GET", "/api/gpu")
        self.assertEqual(s, 200, r)
        self.assertEqual((r["backend"], r["best"], r["llama"]["offload"]), ("vulkan", "Navi 23 [Radeon RX 6600]", False))
        self.assertTrue(any(m["name"] == "tiny-Q4_K_M.gguf" for m in r["models"]))
