"""v0.31: armazenamento (HDD/SSD e limpeza), pentes de memória (dual/quad channel, DDR4/DDR5, NUMA), modo híbrido CPU+GPU e as telas grandes."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from openflow import diskuse, native, perf
from openflow.canvas import sdcli
from openflow.providers import local_llama
from tests.helpers import ServerCase

GB = 1 << 30


class DiskTests(unittest.TestCase):
    def test_kind_can_be_forced_and_hdd_downloads_use_one_connection(self):
        with mock.patch.dict(os.environ, {"OPENFLOW_DISK_KIND": "hdd"}):
            self.assertEqual(diskuse.kind_of("/tmp"), "hdd")
            self.assertEqual(diskuse.download_connections("/tmp", 8), 1)
        with mock.patch.dict(os.environ, {"OPENFLOW_DISK_KIND": "ssd"}):
            self.assertEqual(diskuse.download_connections("/tmp", 8), 8)
        with mock.patch.dict(os.environ, {"OPENFLOW_DISK_KIND": "hdd", "OPENFLOW_DL_HDD_CONNECTIONS": "2"}):
            self.assertEqual(diskuse.download_connections("/tmp", 8), 2)

    def test_prefetch_reads_with_one_thread_on_an_hdd(self):
        f = Path(tempfile.mkdtemp()) / "m.gguf"
        f.write_bytes(b"x" * 100)
        seen = {}

        class Lib:
            @staticmethod
            def flow_prefetch(b, n, threads):
                seen["threads"] = threads
                return 100

        with mock.patch.dict(os.environ, {"OPENFLOW_DISK_KIND": "hdd"}), mock.patch.object(native, "_lib2", return_value=Lib):
            native.prefetch(f)
        self.assertEqual(seen["threads"], 1)
        with mock.patch.dict(os.environ, {"OPENFLOW_DISK_KIND": "ssd"}), mock.patch.object(native, "_lib2", return_value=Lib):
            native.prefetch(f)
        self.assertGreaterEqual(seen["threads"], 2)


class StorageApiTests(ServerCase):
    def old(self, p, hours=3):
        t = time.time() - hours * 3600
        os.utime(p, (t, t))

    def test_report_and_clean(self):
        d = self.store.models_dir / "image"
        d.mkdir(parents=True, exist_ok=True)
        part = d / "big.gguf.part"
        part.write_bytes(b"x" * 5000)
        self.old(part)
        fresh = d / "new.gguf.part"
        fresh.write_bytes(b"y" * 10)                                  # recente: pode ser de um download em andamento
        (d / "keep.gguf").write_bytes(b"z" * 100)
        cs = self.app.project_routes.cs
        s, c = self.c.json("POST", "/api/projects", {"name": "P"})
        pid = c["id"]
        orphan = cs.asset_dir(pid) / "as_orphan.png"
        orphan.write_bytes(b"o" * 700)
        s, r = self.c.json("GET", "/api/storage")
        self.assertEqual(s, 200, r)
        self.assertGreaterEqual(r["cleanable"]["partials"]["bytes"], 5000)
        self.assertGreaterEqual(r["cleanable"]["orphans"]["bytes"], 700)
        self.assertIn(r["disk"]["kind"], ("ssd", "hdd", "unknown"))
        s, out = self.c.json("POST", "/api/storage/clean", {"what": ["partials", "orphans"]})
        self.assertEqual(s, 200, out)
        self.assertFalse(part.exists())
        self.assertFalse(orphan.exists())
        self.assertTrue(fresh.exists() and (d / "keep.gguf").exists())   # recente e modelos ficam
        self.assertEqual(self.c.json("POST", "/api/storage/clean", {"what": ["models"]})[0], 400)

    def test_nothing_partial_is_removed_while_a_download_runs(self):
        d = self.store.models_dir / "image"
        d.mkdir(parents=True, exist_ok=True)
        part = d / "run.gguf.part"
        part.write_bytes(b"x" * 100)
        self.old(part)
        import threading

        gate = threading.Event()
        job = self.app.jobs.start("download", lambda j: gate.wait(5))
        try:
            self.assertTrue(self.c.json("GET", "/api/storage")[1]["downloading"])
            self.c.json("POST", "/api/storage/clean", {"what": ["partials"]})
            self.assertTrue(part.exists())
        finally:
            gate.set()
            part.unlink(missing_ok=True)


class MemoryTests(unittest.TestCase):
    def test_modules_to_channels_and_theory(self):
        m = native.parse_memory_modules([{"capacity": 16 * GB, "speed": 5600, "configured": 5600, "type": 34, "locator": "ChannelA-DIMM0"},
                                         {"capacity": 16 * GB, "speed": 5600, "configured": 5600, "type": 34, "locator": "ChannelB-DIMM0"}])
        self.assertEqual((m["modules"], m["type"], m["channels"], m["gb"], m["theoretical_gbs"]), (2, "DDR5", 2, 32.0, 89.6))
        quad = native.parse_memory_modules([{"capacity": 8 * GB, "speed": 3200, "configured": 3200, "type": 26, "locator": f"Channel{c}-DIMM0"} for c in "ABCD"])
        self.assertEqual(quad["channels"], 4)

    def test_single_stick_and_xmp_advice(self):
        one = native.parse_memory_modules([{"capacity": 8 * GB, "speed": 3200, "configured": 2133, "type": 26, "locator": "DIMM A1"}])
        self.assertEqual(native.memory_advice(one, {"bwn": 9.0}), ["single_channel", "xmp_off"])
        two = native.parse_memory_modules([{"capacity": 8 * GB, "speed": 3200, "configured": 3200, "type": 26, "locator": "ChannelA"}, {"capacity": 8 * GB, "speed": 3200, "configured": 3200, "type": 26, "locator": "ChannelB"}])
        self.assertEqual(native.memory_advice(two, {"bwn": 40.0}), [])
        self.assertEqual(native.memory_advice(two, {"bwn": 10.0}), ["below_expected"])
        self.assertEqual(native.memory_advice({}, None), [])

    def test_without_permission_the_layout_is_empty_not_an_error(self):
        with mock.patch.dict(native._MEM_CACHE, clear=True), mock.patch.object(native.shutil, "which", return_value=None), mock.patch.object(native.sys, "platform", "linux"):
            self.assertEqual(native.memory_layout(), {})

    def test_numa_nodes_are_reported(self):
        self.assertGreaterEqual(native.cpu_info()["numa_nodes"], 1)


class HybridTests(unittest.TestCase):
    def test_device_accepts_hybrid(self):
        with mock.patch.dict(perf.CURRENT, {"device": "hybrid"}):
            self.assertEqual(perf.device(), "hybrid")

    def test_sd_cli_puts_text_encoder_and_vae_on_the_cpu(self):
        with mock.patch.dict(perf.CURRENT, {"device": "hybrid"}):
            args, warns = sdcli.build_args(Path("/x/sd-cli"), {"diffusion_model_path": "/m/a.gguf"}, {}, prompt="p", width=512, height=512, seed=1, out=Path("/t/o.png"))
        self.assertIn("--clip-on-cpu", args)
        self.assertIn("--vae-on-cpu", args)
        with mock.patch.dict(perf.CURRENT, {"device": "auto"}):
            args, _ = sdcli.build_args(Path("/x/sd-cli"), {"diffusion_model_path": "/m/a.gguf"}, {}, prompt="p", width=512, height=512, seed=1, out=Path("/t/o.png"))
        self.assertNotIn("--clip-on-cpu", args)

    def test_hybrid_tuning_only_when_part_of_the_model_stays_on_the_cpu(self):
        with mock.patch.object(perf, "cpu_tuning", return_value={"n_threads": 5, "n_threads_batch": 8}):
            self.assertEqual(perf.hybrid_tuning(8 * GB, 20, 32, 4096, "balanced"), {"n_threads": 5, "n_threads_batch": 8})
            self.assertEqual(perf.hybrid_tuning(8 * GB, 32, 32, 4096, "balanced"), {})      # tudo na placa
            self.assertEqual(perf.hybrid_tuning(8 * GB, 0, 32, 4096, "balanced"), {})

    def test_loading_falls_back_without_the_optional_arguments(self):
        calls = []

        class Fake:
            def __init__(self, **kw):
                calls.append(sorted(kw))
                if any(k in kw for k in local_llama._OPTIONAL):
                    raise TypeError("opção desconhecida")

        base = {"model_path": "m", "n_ctx": 512, "numa": 1, "offload_kqv": False, "draft_model": object()}
        local_llama._load_llama(Fake, base, {"n_batch": 128, "flash": False, "kv_q8": False})
        self.assertFalse(any(k in calls[-1] for k in local_llama._OPTIONAL))
        self.assertIn("model_path", calls[-1])
