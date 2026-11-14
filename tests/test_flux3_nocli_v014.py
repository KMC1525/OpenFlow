"""v0.14: FLUX.3 sem sd-cli não tenta a biblioteca (que fecha com «código -11»): diz o motivo e o que fazer; com a biblioteca do GitHub, vale tentar a biblioteca."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import media as M
from openflow.canvas import sdcli
from openflow.providers.base import ProviderError
from tests.helpers import TmpCase

NAME = "flux-3-image-klein-Q4_K_M.gguf"


class NoCliTests(TmpCase):
    def setUp(self):
        super().setUp()
        os.environ["OPENFLOW_HOME"] = str(self.tmp)
        self.addCleanup(os.environ.pop, "OPENFLOW_HOME", None)
        (self.tmp / "image").mkdir()
        for n in (NAME, "flux2-vae.safetensors", "Qwen3-VL-4B-Instruct-Q4_K_M.gguf"):
            (self.tmp / "image" / n).write_bytes(b"x")
        M._LOCAL_CACHE.clear()
        self.p = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {"image": NAME}, "needs_key": False})
        self.notes = []
        self.p.ctl = M.Ctl(note=self.notes.append)
        self.p._cancelled = lambda: False

    def test_without_a_cli_the_library_is_not_tried_and_the_real_reason_is_shown(self):
        engine = mock.Mock(side_effect=AssertionError("a biblioteca não devia ser carregada"))
        with mock.patch.object(M, "_lib_is_stale", return_value=True), mock.patch.object(sdcli, "find", return_value=None), mock.patch.object(M.GGUFMedia, "_engine", engine), \
                mock.patch.object(sdcli, "install", side_effect=ProviderError("O sd-cli baixado exige a glibc 2.43 e este Linux tem 2.39.")):
            with self.assertRaises(ProviderError) as cm:
                self.p.image("uma thumb")
        msg = str(cm.exception)
        self.assertIn("glibc 2.43", msg)                   # o motivo do download que falhou
        self.assertIn("flow update", msg)                  # o que fazer
        self.assertNotIn("«get sd version", msg)           # nada da mensagem antiga da biblioteca
        self.assertNotIn("[[flow-sd-cli]]", msg)           # com glibc antiga o botão falharia de novo
        engine.assert_not_called()

    def test_the_github_library_is_tried_first_and_the_pypi_one_is_not(self):
        with mock.patch("importlib.metadata.version", return_value="0.4.7"):
            self.assertTrue(M._lib_is_stale())
            self.assertTrue(M._lib_never_knows(NAME))
        with mock.patch("importlib.metadata.version", return_value="0.5.1"):
            self.assertFalse(M._lib_is_stale())
            self.assertFalse(M._lib_never_knows(NAME))     # biblioteca mais nova: vale tentar
        (self.tmp / "sd_built_sha").write_text("abc")
        with mock.patch("importlib.metadata.version", return_value="0.4.7"):
            self.assertFalse(M._lib_is_stale())            # compilada do GitHub pelo `flow update` (mesmo com número de versão igual)
            self.assertFalse(M._lib_never_knows(NAME))
        self.assertFalse(M._lib_never_knows("flux-2-klein-Q4.gguf"))


if __name__ == "__main__":
    unittest.main()
