"""v0.59: Multi GPU Upgrade — VRAM de várias placas juntas (texto, imagem, vídeo) e VRAM + RAM ao mesmo tempo.

Não há placa de vídeo de verdade aqui: tudo roda com placas simuladas (`gpu_status` trocado) e com um `torch`/`sd-cli` de mentira. O que vale em hardware real não é verificado por estes testes."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from openflow import perf
from openflow.canvas import media, sdcli
from tests.helpers import ServerCase

GB = 1 << 30
MB = 1 << 20


def cards(*free, total=24):
    return [{"index": i, "name": f"GPU {i}", "total": total * GB, "free": int(f * GB)} for i, f in enumerate(free)]


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = dict(perf.CURRENT)
        self.addCleanup(lambda: (perf.CURRENT.clear(), perf.CURRENT.update(self.saved)))

    def use(self, status, memory=None, selected=None, device="auto"):
        perf.CURRENT.clear()
        perf.CURRENT.update({"gpus": selected or [], "device": device})
        if memory is not None:
            perf.CURRENT["memory"] = memory
        p = mock.patch.object(perf, "gpu_status", return_value=status)
        p.start()
        self.addCleanup(p.stop)


class NormalizeTests(unittest.TestCase):
    def test_defaults_and_invalid_values(self):
        d = perf.normalize_memory(None)
        self.assertEqual(d, {"multi_gpu": True, "ram_spill": True, "gpu_reserve_mb": 512, "ram_reserve_gb": 2.0})
        self.assertEqual(perf.normalize_memory("x"), d)
        bad = perf.normalize_memory({"multi_gpu": "no", "gpu_reserve_mb": "9", "ram_reserve_gb": float("nan"), "ram_spill": 0})
        self.assertEqual((bad["gpu_reserve_mb"], bad["ram_reserve_gb"]), (512, 2.0))
        self.assertTrue(bad["multi_gpu"])   # só `False` de verdade desliga

    def test_clamped_and_switches(self):
        d = perf.normalize_memory({"multi_gpu": False, "ram_spill": False, "gpu_reserve_mb": 99999, "ram_reserve_gb": -5})
        self.assertEqual(d, {"multi_gpu": False, "ram_spill": False, "gpu_reserve_mb": 8192, "ram_reserve_gb": 0.0})
        self.assertEqual(perf.normalize_memory({"gpu_reserve_mb": True})["gpu_reserve_mb"], 512)   # bool não é número


class PoolTests(Base):
    def test_pool_is_sorted_by_free_memory_and_discounts_the_reserve(self):
        self.use(cards(10, 30, 20), {"gpu_reserve_mb": 1024})
        pool = perf.gpu_pool()
        self.assertEqual([g["index"] for g in pool], [1, 2, 0])
        self.assertEqual(pool[0]["usable"], 30 * GB - 1024 * MB)
        self.assertEqual(perf.gpu_order(), [1, 2, 0])

    def test_multi_gpu_off_keeps_only_the_primary(self):
        self.use(cards(10, 30), {"multi_gpu": False})
        self.assertEqual([g["index"] for g in perf.gpu_pool()], [1])
        self.assertEqual(perf.llama_split(), {"main_gpu": 1, "tensor_split": [0.0, 1.0]})

    def test_chosen_gpus_only(self):
        self.use(cards(10, 30, 20), selected=[0, 2])
        self.assertEqual(sorted(g["index"] for g in perf.gpu_pool()), [0, 2])

    def test_llama_split_is_proportional_to_usable_memory(self):
        self.use(cards(10.5, 30.5), {"gpu_reserve_mb": 512})   # usável: 10 e 30 GB
        sp = perf.llama_split()
        self.assertEqual(sp["main_gpu"], 1)
        self.assertEqual(sp["tensor_split"], [0.25, 0.75])

    def test_single_gpu_changes_nothing(self):
        self.use(cards(12))
        self.assertEqual(perf.llama_split(), {})

    def test_pooled_gpu_sums_the_vram_of_nvidia_cards(self):
        self.use(cards(10.5, 30.5), {"gpu_reserve_mb": 512})
        best = {"vendor": "nvidia", "integrated": False, "index": 1, "name": "GPU 1", "vram_total": 24 * GB, "vram_free": 30 * GB}
        p = perf.pooled_gpu(best)
        self.assertEqual(p["pooled"], [1, 0])
        self.assertEqual(p["vram_total"], 48 * GB)
        self.assertEqual(p["vram_free"], 40 * GB)
        self.assertEqual(perf.pooled_gpu(dict(best, vendor="amd")), dict(best, vendor="amd"))   # AMD/Intel: não divide
        self.use(cards(10.5, 30.5), {"multi_gpu": False})
        self.assertEqual(perf.pooled_gpu(best), best)

    def test_gpu_env_exposes_all_cards_only_when_components_are_split(self):
        self.use(cards(10, 30))
        self.assertEqual(perf.gpu_env({})["CUDA_VISIBLE_DEVICES"], "1")
        self.assertEqual(perf.gpu_env({}, multi=True)["CUDA_VISIBLE_DEVICES"], "1,0")
        self.assertEqual(perf.gpu_env({"CUDA_VISIBLE_DEVICES": "0"}, multi=True)["CUDA_VISIBLE_DEVICES"], "0")   # o usuário manda


class TextPlanTests(Base):
    def plan(self, memory):
        g = {"vendor": "nvidia", "integrated": False, "index": 0, "name": "A", "backend": "cuda", "vram_total": 24 * GB, "vram_free": 22 * GB, "bw_gbs": 900}
        self.use(cards(22, 22), memory)
        with mock.patch.object(perf, "best_discrete_gpu", return_value=g):
            return perf.gpu_tuning(30 * GB, 60, 200000, 4096, "balanced")

    def test_a_model_bigger_than_one_card_gets_all_its_layers_on_two(self):
        pooled = self.plan({"multi_gpu": True})
        single = self.plan({"multi_gpu": False})
        if not pooled:
            self.skipTest("planejador nativo indisponível")
        self.assertEqual(pooled["layers_fit"], 60)
        self.assertEqual(pooled["gpu"]["pooled"], [0, 1])
        self.assertLess(single["layers_fit"], 60)   # numa placa só, o resto fica na RAM
        self.assertFalse(single["gpu"].get("pooled"))


class PlacementTests(unittest.TestCase):
    @staticmethod
    def pool(free, ram=32, spill=True):
        gp = [{"index": i, "name": f"G{i}", "total": 24 * GB, "free": f * GB, "usable": f * GB} for i, f in enumerate(free)]
        return {"gpus": gp, "vram_total": 24 * GB * len(gp), "vram_free": sum(g["free"] for g in gp), "vram_usable": sum(g["usable"] for g in gp), "ram_total": 64 * GB, "ram_avail": ram * GB,
                "ram_usable": ram * GB, "config": {"multi_gpu": True, "ram_spill": spill, "gpu_reserve_mb": 0, "ram_reserve_gb": 0}}

    def test_fits_one_card(self):
        r = perf.placement(10 * GB, self.pool([20, 20]))
        self.assertEqual((r["strategy"], r["fits"], r["multi_gpu"]), ("gpu", True, False))

    def test_needs_two_cards(self):
        r = perf.placement(30 * GB, self.pool([20, 10]))
        self.assertEqual((r["strategy"], r["fits"], r["multi_gpu"]), ("multi_gpu", True, True))
        self.assertEqual({g["index"]: g["bytes"] for g in r["gpus"]}, {0: 20 * GB, 1: 10 * GB})

    def test_cards_plus_ram(self):
        r = perf.placement(40 * GB, self.pool([20, 10]))
        self.assertEqual(r["strategy"], "multi_gpu+ram")
        self.assertEqual(r["ram_bytes"], 10 * GB)
        r = perf.placement(30 * GB, self.pool([20]))
        self.assertEqual((r["strategy"], r["ram_bytes"]), ("gpu+ram", 10 * GB))

    def test_ram_spill_off_means_no_fit(self):
        r = perf.placement(40 * GB, self.pool([20, 10], spill=False))
        self.assertEqual((r["strategy"], r["fits"]), ("no_fit", False))

    def test_no_gpu_uses_ram_or_nothing(self):
        self.assertEqual(perf.placement(8 * GB, self.pool([], ram=16))["strategy"], "ram")
        self.assertEqual(perf.placement(30 * GB, self.pool([], ram=16))["strategy"], "no_fit")

    def test_too_big_for_everything(self):
        self.assertEqual(perf.placement(500 * GB, self.pool([20, 10], ram=16))["strategy"], "no_fit")


class AssignComponentsTests(unittest.TestCase):
    def test_everything_fits_the_primary(self):
        self.assertEqual(perf.assign_components({"diffusion": 8 * GB, "te": 4 * GB, "vae": GB // 2}, [24 * GB, 24 * GB]), {})

    def test_text_encoder_and_vae_move_to_the_other_card(self):
        # a difusão (14 GB + 15 %) ocupa a principal; o codificador de texto (12 GB) e o VAE não cabem com ela
        r = perf.assign_components({"diffusion": 14 * GB, "te": 12 * GB, "vae": GB}, [24 * GB, 16 * GB])
        self.assertEqual(r.get("te"), 1)

    def test_diffusion_alone_does_not_fit_means_no_split(self):
        self.assertEqual(perf.assign_components({"diffusion": 30 * GB, "te": GB}, [24 * GB, 24 * GB]), {})

    def test_single_card(self):
        self.assertEqual(perf.assign_components({"diffusion": 8 * GB, "te": 30 * GB}, [24 * GB]), {})

    def test_reserve_is_discounted(self):
        free = [24 * GB, 24 * GB]
        sizes = {"diffusion": 10 * GB, "te": 10 * GB}
        self.assertEqual(perf.assign_components(sizes, free), {})
        self.assertEqual(perf.assign_components(sizes, free, reserve=2 * GB).get("te"), None)   # 22 GB: ainda cabe
        self.assertEqual(perf.assign_components({"diffusion": 10 * GB, "te": 12 * GB}, free, reserve=2 * GB), {"te": 1})


class SdCliTests(Base):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp(prefix="openflow-v059-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def file(self, name, size):
        p = self.tmp / name
        with open(p, "wb") as f:
            f.truncate(size)
        return str(p)

    def test_backend_args(self):
        self.assertEqual(sdcli.backend_args({}), [])
        self.assertEqual(sdcli.backend_args({"vae": 1, "te": 1}), ["--backend", "te=CUDA1,vae=CUDA1"])

    def test_component_split_needs_cuda_two_cards_and_backend_support(self):
        self.use(cards(16, 24), {"gpu_reserve_mb": 0})
        load = {"diffusion_model_path": self.file("d.gguf", 13 * GB), "llm_path": self.file("t.gguf", 12 * GB), "vae_path": self.file("v.safetensors", 1 * MB)}
        exe = Path("/nonexistent/sd-cli")
        with mock.patch.object(sdcli, "_backend_kind", return_value="cuda12"), mock.patch.object(sdcli, "supports_backend", return_value=True):
            split = sdcli.component_split(load, exe)
            self.assertEqual(split.get("te"), 1)   # a principal é a de 24 GB; o texto não cabe junto da difusão... (ver `assign_components`)
        with mock.patch.object(sdcli, "_backend_kind", return_value="cuda12"), mock.patch.object(sdcli, "supports_backend", return_value=False):
            self.assertEqual(sdcli.component_split(load, exe), {})   # sd-cli sem `--backend`
        with mock.patch.object(sdcli, "_backend_kind", return_value="vulkan"), mock.patch.object(sdcli, "supports_backend", return_value=True):
            self.assertEqual(sdcli.component_split(load, exe), {})   # Vulkan: nomes de dispositivo diferentes
        with mock.patch.object(sdcli, "_backend_kind", return_value="cuda12"), mock.patch.object(sdcli, "supports_backend", return_value=True):
            perf.CURRENT["memory"] = {"multi_gpu": False}
            self.assertEqual(sdcli.component_split(load, exe), {})   # «dividir entre as placas» desligado
            perf.CURRENT["memory"] = {}
            perf.CURRENT["device"] = "cpu"
            self.assertEqual(sdcli.component_split(load, exe), {})

    def test_component_split_single_card_or_missing_files(self):
        self.use(cards(24))
        with mock.patch.object(sdcli, "_backend_kind", return_value="cuda12"), mock.patch.object(sdcli, "supports_backend", return_value=True):
            self.assertEqual(sdcli.component_split({"diffusion_model_path": self.file("d.gguf", GB)}), {})
            self.use(cards(24, 24))
            self.assertEqual(sdcli.component_split({"diffusion_model_path": "/nope.gguf", "llm_path": "/nope2.gguf"}), {})

    def test_supports_backend_reads_the_help_once(self):
        exe = Path(self.tmp / "sd-cli")
        sdcli._BACKEND_OK.pop(str(exe), None)
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return types.SimpleNamespace(stdout="usage: sd-cli ...\n  --backend <comp=dev>\n", stderr="")
        with mock.patch.object(sdcli.subprocess, "run", fake_run):
            self.assertTrue(sdcli.supports_backend(exe))
            self.assertTrue(sdcli.supports_backend(exe))
        self.assertEqual(len(calls), 1)
        exe2 = Path(self.tmp / "sd-cli2")
        with mock.patch.object(sdcli.subprocess, "run", side_effect=OSError("x")):
            self.assertFalse(sdcli.supports_backend(exe2))


def fake_torch(devices=2):
    cuda = types.SimpleNamespace(is_available=lambda: devices > 0, device_count=lambda: devices)
    return types.SimpleNamespace(cuda=cuda)


class BalancedTests(Base):
    def pool(self, *free, **mem):
        self.use(cards(*free), dict({"gpu_reserve_mb": 0, "ram_reserve_gb": 0}, **mem))

    def call(self, weights, torch=None, ram=32):
        torch = torch or fake_torch()
        info = {"ram_total": 64 * GB, "ram_avail": ram * GB}
        with mock.patch.object(media, "_local_import", return_value=[torch]), mock.patch("openflow.native.sys_info", return_value=info):
            return media._balanced_kwargs(weights)

    def test_fits_one_card_keeps_the_usual_plan(self):
        self.pool(24, 24)
        self.assertEqual(self.call(10 * GB), {})

    def test_split_across_two_cards(self):
        self.pool(24, 24)
        r = self.call(30 * GB)
        self.assertEqual(r["device_map"], "balanced")
        self.assertEqual({k: v for k, v in r["max_memory"].items() if k != "cpu"}, {0: f"{24 * 1024}MiB", 1: f"{24 * 1024}MiB"})
        self.assertIn("cpu", r["max_memory"])   # «usar a RAM junto» ligado

    def test_ram_spill_off_has_no_cpu_entry_and_no_overflow(self):
        self.pool(24, 24, ram_spill=False)
        self.assertNotIn("cpu", self.call(30 * GB)["max_memory"])
        self.assertEqual(self.call(60 * GB), {})

    def test_too_big_even_with_ram(self):
        self.pool(24, 24)
        self.assertEqual(self.call(200 * GB, ram=16), {})

    def test_one_card_cpu_device_or_no_cuda(self):
        self.pool(24)
        self.assertEqual(self.call(40 * GB), {})
        self.pool(24, 24)
        self.assertEqual(self.call(30 * GB, torch=fake_torch(0)), {})
        self.assertEqual(self.call(30 * GB, torch=fake_torch(1)), {})
        perf.CURRENT["device"] = "cpu"
        self.assertEqual(self.call(30 * GB), {})

    def test_load_pipeline_falls_back_when_diffusers_rejects_it(self):
        calls = []

        def factory(**kw):
            calls.append(kw)
            if "device_map" in kw:
                raise ValueError("device_map não suportado")
            return "pipe"
        with mock.patch.object(media, "_balanced_kwargs", return_value={"device_map": "balanced", "max_memory": {0: "1MiB"}}):
            old = dict(media._PLAN)
            self.addCleanup(lambda: (media._PLAN.clear(), media._PLAN.update(old)))
            media._PLAN.clear()
            media._PLAN["weights"] = 1
            self.assertEqual(media._load_pipeline(factory, {"a": 1}), "pipe")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("balanced", media._PLAN)

    def test_load_pipeline_records_the_split(self):
        notes = []
        with mock.patch.object(media, "_balanced_kwargs", return_value={"device_map": "balanced", "max_memory": {0: "1MiB", 1: "1MiB", "cpu": "1MiB"}}):
            old = dict(media._PLAN)
            self.addCleanup(lambda: (media._PLAN.clear(), media._PLAN.update(old)))
            media._PLAN.clear()
            media._PLAN["weights"] = 1
            self.assertEqual(media._load_pipeline(lambda **kw: "pipe", {}, notes.append), "pipe")
        self.assertEqual(media._PLAN["balanced"], {"gpus": [0, 1], "ram": True})
        self.assertTrue(notes and "placas" in notes[0])


class ApiTests(ServerCase):
    def test_settings_memory_is_clamped_and_exported(self):
        self.c.json("PUT", "/api/settings", {"performance": {"memory": {"gpu_reserve_mb": 99999, "ram_reserve_gb": -3, "multi_gpu": False, "ram_spill": "x"}}})
        s, r = self.c.json("GET", "/api/settings")
        m = r["performance"]["memory"]
        self.assertEqual((m["gpu_reserve_mb"], m["ram_reserve_gb"], m["multi_gpu"], m["ram_spill"]), (8192, 0.0, False, True))
        self.c.json("PUT", "/api/settings", {"performance": {"memory": {"multi_gpu": True}}})

    def test_memory_route_reports_the_pool_and_where_models_fit(self):
        fake = [{"index": 0, "name": "A", "total": 24 * GB, "free": 20 * GB}, {"index": 1, "name": "B", "total": 24 * GB, "free": 20 * GB}]
        with mock.patch.object(perf, "gpu_status", return_value=fake), mock.patch.object(perf, "selected_gpus", return_value=[0, 1]):
            s, r = self.c.json("GET", "/api/perf/memory")
        self.assertEqual(s, 200)
        self.assertEqual(len(r["pool"]["gpus"]), 2)
        self.assertTrue(r["multi_gpu_possible"])
        self.assertEqual(r["pool"]["config"]["multi_gpu"], True)
        self.assertIsInstance(r["models"], list)

    def test_memory_route_without_nvidia(self):
        with mock.patch.object(perf, "gpu_status", return_value=[]):
            s, r = self.c.json("GET", "/api/perf/memory")
        self.assertEqual(s, 200)
        self.assertEqual(r["pool"]["gpus"], [])
        self.assertFalse(r["multi_gpu_possible"])


if __name__ == "__main__":
    unittest.main()
