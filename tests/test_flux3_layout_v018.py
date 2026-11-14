"""v0.18: GGUF do FLUX.3 feito para ComfyUI/diffusers (unsloth…) não carrega no sd-cli: o erro e a busca apontam o repositório convertido para a stable-diffusion.cpp."""
import os
import unittest
from pathlib import Path
from unittest import mock

from openflow import hf
from openflow.canvas import media as M
from openflow.canvas import sdcli, support
from openflow.providers import ProviderError
from tests.helpers import ServerCase, TmpCase

LOG = ("O sd-cli falhou (código 1): .gguf' --- diffusion_engine.cpp:750 | [I] load /home/u/.openflow/models/image/flux2-vae.safetensors using safetensors format --- model_loader.cpp:226 | "
       "[E] get sd version from file failed: '' --- diffusion_engine.cpp:975 | [I] new_sd_ctx_t failed --- main.cpp:975")


class CompatTests(unittest.TestCase):
    def test_the_native_repository_is_known_by_file_or_repo_name(self):
        for name in ("flux-3-image-klein-Q4_K_M.gguf", "flux3-image-klein-Q4_K.gguf", "FLUX.3-klein-Q8_0.gguf"):
            self.assertEqual(support.sd_native_for(name)["repo"], "leejet/flux-3-image-klein-GGUF", name)
        self.assertEqual(support.sd_native_for("x.gguf", "unsloth/flux-3-image-klein-GGUF")["repo"], "leejet/flux-3-image-klein-GGUF")
        self.assertIsNone(support.sd_native_for("flux-3-image-klein-pup-Q4.gguf"))          # o expansor de prompt é um modelo de texto
        self.assertIsNone(support.sd_native_for("qwen-image-Q4.gguf"))
        self.assertIsNone(support.sd_native_for("flux-2-klein-4b-Q4.gguf"))

    def test_only_the_non_native_repositories_get_the_warning(self):
        w = support.sd_compat_warning("unsloth/flux-3-image-klein-GGUF")
        self.assertEqual(w["repo"], "leejet/flux-3-image-klein-GGUF")
        self.assertIn("get sd version from file failed", w["text"])
        self.assertIsNone(support.sd_compat_warning("leejet/flux-3-image-klein-GGUF"))
        self.assertIsNotNone(support.sd_compat_warning("Abiray/flux-3-image-klein-GGUF"))   # outro autor: avisa (só o leejet é confirmado)
        self.assertIsNone(support.sd_compat_warning("unsloth/Qwen-Image-GGUF"))


class NodeErrorTests(TmpCase):
    def setUp(self):
        super().setUp()
        os.environ["OPENFLOW_HOME"] = str(self.tmp)
        self.addCleanup(os.environ.pop, "OPENFLOW_HOME", None)
        (self.tmp / "image").mkdir()
        for n in ("flux-3-image-klein-Q4_K_M.gguf", "flux2-vae.safetensors", "Qwen3-VL-4B-Instruct-Q4_K_M.gguf"):
            (self.tmp / "image" / n).write_bytes(b"x")
        M._LOCAL_CACHE.clear()
        self.p = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {"image": "flux-3-image-klein-Q4_K_M.gguf"}, "needs_key": False})
        self.p.ctl = M.Ctl(note=lambda m: None)
        self.p._cancelled = lambda: False

    def test_the_raw_sd_cli_log_becomes_a_clear_message_with_the_compatible_repository(self):
        with mock.patch.object(M, "_lib_is_stale", return_value=True), mock.patch.object(sdcli, "find", return_value=Path("/x/sd-cli")), mock.patch.object(sdcli, "generate_image", side_effect=ProviderError(LOG)), \
                mock.patch.object(sdcli, "installed_backend", return_value=sdcli.backend()):
            with self.assertRaises(ProviderError) as cm:
                self.p.image("uma thumb")
        msg = str(cm.exception)
        self.assertIn("leejet/flux-3-image-klein-GGUF", msg)
        self.assertIn("flux3-image-klein-Q4_K.gguf", msg)
        self.assertIn("[[flow-sd-repo:leejet/flux-3-image-klein-GGUF]]", msg)       # o nó mostra «Abrir … em Modelos»
        self.assertNotIn("diffusion_engine.cpp", msg)                               # nada do log cru
        self.assertNotIn("main.cpp:975", msg)

    def test_other_models_get_the_generic_message_without_a_button(self):
        err = M.GGUFMedia._layout_error(Path("algum-modelo-Q4.gguf"))
        self.assertNotIn("[[flow-sd-repo", str(err))
        self.assertIn("leejet", str(err))

    def test_other_sd_cli_failures_are_untouched(self):
        with mock.patch.object(M, "_lib_is_stale", return_value=True), mock.patch.object(sdcli, "find", return_value=Path("/x/sd-cli")), mock.patch.object(sdcli, "generate_image", side_effect=ProviderError("O sd-cli falhou (código -9): falta de memória")), \
                mock.patch.object(sdcli, "installed_backend", return_value=sdcli.backend()):
            with self.assertRaises(ProviderError) as cm:
                self.p.image("uma thumb")
        self.assertIn("falta de memória", str(cm.exception))


class SearchWarningTests(ServerCase):
    def test_opening_a_non_native_flux3_repository_shows_the_warning(self):
        tree = [{"name": "flux-3-image-klein-Q4_K_M.gguf", "size": 3_000_000_000}]
        with mock.patch.object(hf, "repo_files", return_value=tree):
            s, r = self.c.json("GET", "/api/hf/files?repo=unsloth/flux-3-image-klein-GGUF&kind=image")
            self.assertEqual(s, 200, r)
            self.assertEqual(r["compat"]["repo"], "leejet/flux-3-image-klein-GGUF")
            s, r = self.c.json("GET", "/api/hf/files?repo=leejet/flux-3-image-klein-GGUF&kind=image")
            self.assertIsNone(r["compat"])
            s, r = self.c.json("GET", "/api/hf/files?repo=unsloth/Qwen-Image-GGUF&kind=image")
            self.assertIsNone(r["compat"])


if __name__ == "__main__":
    unittest.main()
