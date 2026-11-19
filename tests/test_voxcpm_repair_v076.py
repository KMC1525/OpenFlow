"""v0.76: «AudioVAE checkpoint not found» na Dublagem com o openbmb/VoxCPM2.

A causa: o seletor de arquivos do download descartava o `audiovae.pth` (o codec de áudio do VoxCPM) quando o repositório tem `.safetensors` — corrigido na v0.71, mas quem baixou o modelo antes ficou com uma pasta incompleta
e a biblioteca falhava com o erro cru. Agora o OpenFlow percebe a falta, baixa só esse arquivo (com um aviso no nó) e, se não der, explica o que fazer. A biblioteca `voxcpm` e a rede são simuladas; o ffmpeg é real."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import localmodels as lm
from openflow.canvas import voxcpm
from openflow.providers import ProviderError
from tests.test_voxcpm_nodes_v075 import FF, MODEL, Base, DubNodeTests
from tests.helpers import voxcpm_python_ok



_VOX_PATCH = None


def setUpModule():
    global _VOX_PATCH
    _VOX_PATCH = voxcpm_python_ok()   # os testes simulam a biblioteca voxcpm: a exigência de Python 3.10 não é o assunto deles


def tearDownModule():
    if _VOX_PATCH is not None:
        _VOX_PATCH.stop()


class MissingCodecTests(unittest.TestCase):
    def test_detection(self):
        d = Path(tempfile.mkdtemp())
        self.assertTrue(voxcpm.missing_codec(d))
        (d / "model.safetensors").write_bytes(b"x")
        self.assertTrue(voxcpm.missing_codec(d))
        (d / "audiovae.pth").write_bytes(b"x")
        self.assertFalse(voxcpm.missing_codec(d))
        d2 = Path(tempfile.mkdtemp())
        (d2 / "audiovae.safetensors").write_bytes(b"x")
        self.assertFalse(voxcpm.missing_codec(d2))
        self.assertFalse(voxcpm.missing_codec(None))                                              # sem pasta conhecida: nada a consertar

    def test_the_download_selector_keeps_the_codec(self):
        files = [{"name": n, "size": 1} for n in ("model.safetensors", "audiovae.pth", "config.json", "tokenizer.json")]
        for prec in ("fp32", "fp16", "bf16"):
            self.assertIn("audiovae.pth", {f["name"] for f in lm.select_files(files, prec)})

    def test_fetch_files_asks_the_hub_for_exactly_those_files(self):
        hub = mock.MagicMock()
        hub.hf_hub_download.side_effect = lambda model, name, token=None: f"/cache/{name}"
        with mock.patch.object(lm, "_hub", return_value=hub):
            out = lm.fetch_files(MODEL, ["audiovae.pth"])
        self.assertEqual(out, [Path("/cache/audiovae.pth")])
        hub.hf_hub_download.assert_called_once_with(MODEL, "audiovae.pth", token=None)

    def test_fetch_files_explains_a_network_failure(self):
        hub = mock.MagicMock()
        hub.hf_hub_download.side_effect = OSError("sem rede")
        with mock.patch.object(lm, "_hub", return_value=hub):
            with self.assertRaises(ProviderError) as cm:
                lm.fetch_files(MODEL, ["audiovae.pth"])
        self.assertIn("Não foi possível baixar", str(cm.exception))


class IncompleteModelBase(Base):
    def setUp(self):
        super().setUp()
        self.snap = Path(tempfile.mkdtemp())
        (self.snap / "model.safetensors").write_bytes(b"x")
        (self.snap / "config.json").write_text("{}")
        p = mock.patch.object(lm, "_snapshot", side_effect=lambda model: self.snap)
        p.start()
        self.addCleanup(p.stop)
        self.fetched = []

    def fake_fetch(self, model, names, token=""):
        self.fetched.append((model, list(names)))
        for n in names:
            (self.snap / n).write_bytes(b"codec")
        return [self.snap / n for n in names]


class VoiceNodeRepairTests(IncompleteModelBase):
    def test_the_voice_node_completes_the_download_and_then_speaks(self):
        with mock.patch.object(lm, "fetch_files", side_effect=self.fake_fetch):
            cv = self.run_nodes([self.voice("v", text="Olá, mundo.")])
            first = list(self.events)
            self.run_nodes([self.voice("v", text="Outra frase.")])
        self.assertEqual(self.errors(), {})
        self.assertEqual(self.fetched, [(MODEL, ["audiovae.pth"])])                               # baixou uma vez só, e só o que faltava
        self.assertTrue(self.fake.calls)
        self.assertTrue(self.result(cv, "v")["assets"])
        notes = [e["message"] for e in first if e.get("type") == "note"]
        self.assertTrue(any("sem o codec de áudio" in m and "baixando só esse arquivo" in m for m in notes), notes)       # o aviso aparece no nó

    def test_without_network_the_node_says_what_to_do(self):
        with mock.patch.object(lm, "fetch_files", side_effect=ProviderError("Não foi possível baixar «openbmb/VoxCPM2»: sem rede")):
            self.run_nodes([self.voice("v", text="Olá.")])
        err = self.errors()["v"]
        self.assertIn("sem o codec de áudio", err)
        self.assertIn("Configuração → Mídia", err)
        self.assertNotIn("Erro inesperado", err)                                                   # antes: «Erro inesperado: AudioVAE checkpoint not found…»
        self.assertEqual(self.fake.calls, [])

    def test_a_repository_that_does_not_bring_the_codec_is_explained(self):
        with mock.patch.object(lm, "fetch_files", return_value=[]):
            self.run_nodes([self.voice("v", text="Olá.")])
        self.assertIn("não trouxe o codec de áudio", self.errors()["v"])

    def test_the_raw_library_error_is_rewritten(self):
        (self.snap / "audiovae.pth").write_bytes(b"c")                                              # a pasta está completa, mas a biblioteca ainda falha
        self.fake.VoxCPM.from_pretrained = staticmethod(lambda model, **kw: (_ for _ in ()).throw(FileNotFoundError("AudioVAE checkpoint not found. Expected either a or b")))
        self.run_nodes([self.voice("v", text="Olá.")])
        err = self.errors()["v"]
        self.assertIn("O VoxCPM não conseguiu carregar", err)
        self.assertIn("AudioVAE checkpoint not found", err)
        self.assertIn("baixe-o de novo", err)

    def test_a_complete_model_never_touches_the_network(self):
        (self.snap / "audiovae.pth").write_bytes(b"c")
        with mock.patch.object(lm, "fetch_files", side_effect=AssertionError("não deveria baixar")):
            self.run_nodes([self.voice("v", text="Olá.")])
        self.assertEqual(self.errors(), {})


@unittest.skipUnless(FF, "sem ffmpeg")
class DubRepairTests(IncompleteModelBase):
    """A Dublagem da imagem do problema: modelo `openbmb/VoxCPM2`, vozes alternadas, aceleração para caber no tempo."""
    SCRIPT, source, dub, graph = DubNodeTests.SCRIPT, DubNodeTests.source, DubNodeTests.dub, DubNodeTests.graph

    def test_the_dub_of_the_screenshot_now_works(self):
        with mock.patch.object(lm, "fetch_files", side_effect=self.fake_fetch):
            cv = self.run_nodes(*self.graph(language="keep", assign="alternate", mix="replace", fit=True, speed=1.0))
        self.assertEqual(self.errors(), {})
        self.assertEqual(len(self.fetched), 1)
        self.assertTrue(self.result(cv, "d")["assets"])

    def test_the_dub_says_what_to_do_when_the_codec_cannot_be_downloaded(self):
        with mock.patch.object(lm, "fetch_files", side_effect=ProviderError("sem rede")):
            self.run_nodes(*self.graph(language="keep"))
        self.assertIn("sem o codec de áudio", self.errors()["d"])


if __name__ == "__main__":
    unittest.main()
