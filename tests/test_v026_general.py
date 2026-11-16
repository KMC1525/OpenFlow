"""v0.26: várias placas de vídeo, `flow libs --sd-cli` com o código de saída certo, links públicos seguros e a limpeza do que sobrou do ASTA."""
import argparse
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from openflow import cli, perf, util
from openflow.providers import ProviderError

GB = 1 << 30


def gpus(*free):
    return [{"index": i, "name": f"GPU {i}", "total": 24 * GB, "free": f * GB} for i, f in enumerate(free)]


class MultiGpuTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(perf.CURRENT)
        self.addCleanup(lambda: (perf.CURRENT.clear(), perf.CURRENT.update(self.saved)))

    def use(self, status, selected=None):
        perf.CURRENT.clear()
        perf.CURRENT.update({"gpus": selected or []})
        patch = mock.patch.object(perf, "gpu_status", return_value=status)
        patch.start()
        self.addCleanup(patch.stop)

    def test_all_gpus_are_used_when_none_is_chosen(self):
        self.use(gpus(10, 20))
        self.assertEqual(perf.selected_gpus(), [0, 1])
        self.assertEqual(perf.primary_gpu(), 1)                       # a com mais memória livre

    def test_chosen_gpus_only_and_unknown_ones_are_ignored(self):
        self.use(gpus(10, 20, 5), [0, 2, 9])
        self.assertEqual(perf.selected_gpus(), [0, 2])
        self.assertEqual(perf.primary_gpu(), 0)
        self.use(gpus(10, 20), [7])                                   # só índices que não existem: volta a todas
        self.assertEqual(perf.selected_gpus(), [0, 1])

    def test_llama_split_is_proportional_to_free_memory(self):
        self.use(gpus(10, 30))
        perf.CURRENT["memory"] = {"gpu_reserve_mb": 0}   # v0.59: a divisão é pela memória USÁVEL (livre menos a folga de cada placa); sem folga, é a livre
        sp = perf.llama_split()
        self.assertEqual(sp["tensor_split"], [0.25, 0.75])
        self.assertEqual(sp["main_gpu"], 1)
        perf.CURRENT["memory"] = {}   # folga padrão (512 MB por placa): (10-0,5) : (30-0,5)
        self.assertEqual(perf.llama_split()["tensor_split"], [0.2436, 0.7564])

    def test_llama_split_with_one_chosen_gpu_keeps_the_model_on_it(self):
        self.use(gpus(10, 30, 8), [2])
        self.assertEqual(perf.llama_split(), {"main_gpu": 2, "tensor_split": [0.0, 0.0, 1.0]})

    def test_a_single_gpu_changes_nothing(self):
        self.use(gpus(12))
        self.assertEqual(perf.llama_split(), {})
        self.assertEqual(perf.gpu_env({"A": "1"}), {"A": "1"})

    def test_sd_cli_gets_the_freest_chosen_gpu_unless_the_user_set_one(self):
        self.use(gpus(10, 20, 30), [0, 1])
        self.assertEqual(perf.gpu_env({})["CUDA_VISIBLE_DEVICES"], "1")
        self.assertEqual(perf.gpu_env({"CUDA_VISIBLE_DEVICES": "2"})["CUDA_VISIBLE_DEVICES"], "2")
        perf.CURRENT["device"] = "cpu"
        self.assertNotIn("CUDA_VISIBLE_DEVICES", perf.gpu_env({}))

    def test_nvidia_smi_lists_every_gpu(self):
        out = subprocess.CompletedProcess([], 0, stdout="0, NVIDIA RTX 4090, 24564\n1, NVIDIA RTX 3090, 24576\n", stderr="")
        with mock.patch.object(util.shutil, "which", return_value="/usr/bin/nvidia-smi"), mock.patch.object(util.subprocess, "run", return_value=out):
            g = util.gpu_list()
            name = util._gpu_name()
        self.assertEqual([(x["index"], x["name"], x["mem_mb"]) for x in g], [(0, "NVIDIA RTX 4090", 24564), (1, "NVIDIA RTX 3090", 24576)])
        self.assertIn("RTX 4090", name)
        self.assertIn("RTX 3090", name)                                # antes só a primeira placa aparecia

    def test_the_default_settings_have_the_gpu_list(self):
        self.assertEqual(perf.DEFAULTS["gpus"], [])


class LibsExitCodeTests(unittest.TestCase):
    def test_sd_cli_success_exits_zero_and_failure_one(self):
        ns = argparse.Namespace(sd_cli=True)
        with mock.patch.object(cli, "_sd_cli_install", return_value=True):
            self.assertEqual(cli._libs(ns), 0)
        with mock.patch.object(cli, "_sd_cli_install", return_value=False):
            self.assertEqual(cli._libs(ns), 1)

    def test_there_is_a_single_installer(self):
        src = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertEqual(src.count("def _sd_cli_install("), 1)


class SafeUrlTests(unittest.TestCase):
    def test_private_and_odd_addresses_are_refused(self):
        from openflow import safeurl

        for u in ("http://localhost/x", "http://127.0.0.1/x", "http://192.168.1.5/x", "file:///etc/passwd", "ftp://example.com/x", "not a url", "http:///x"):
            self.assertFalse(safeurl.safe_url(u), u)

    def test_a_public_address_is_accepted_and_redirects_are_checked(self):
        import socket
        import urllib.error

        from openflow import safeurl

        fake = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with mock.patch.object(safeurl.socket, "getaddrinfo", return_value=fake):
            self.assertTrue(safeurl.safe_url("https://example.com/a.png"))
        with mock.patch.object(safeurl, "safe_url", return_value=False):
            with self.assertRaises(urllib.error.HTTPError):
                safeurl._SafeRedirect().redirect_request(mock.Mock(), None, 302, "x", {}, "http://127.0.0.1/")


class CleanupTests(unittest.TestCase):
    def test_the_chat_web_search_module_from_asta_is_gone(self):
        with self.assertRaises(ImportError):
            __import__("openflow.websearch")

    def test_no_unused_icons_of_removed_features(self):
        src = (Path(__file__).resolve().parent.parent / "openflow" / "web" / "js" / "ui.js").read_text(encoding="utf-8")
        for name in ("worldbuilding", "scriber", "mountain", "rocket", "bucket", "lasso"):
            self.assertNotIn(f"  {name}:", src)
