"""v0.78: instalar modelos locais — o download do Hugging Face local confere o espaço em disco ANTES de baixar (antes, um disco cheio só aparecia no meio, como «No space left on device») e o botão «Cancelar» vale no MEIO de um
arquivo grande (antes só entre um arquivo e outro: cancelar um .safetensors de 5 GB esperava ele terminar). O huggingface_hub e a rede são simulados; nenhum modelo real foi baixado."""
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import localmodels as lm
from openflow.providers import ProviderError

GB = 1024 ** 3
MODEL = "acme/tiny-model"


class Bar:
    """A barra de progresso do hub: `update` recebe os bytes de cada pedaço."""

    def __init__(self, total=0):
        self.total, self.n = total, 0

    def update(self, n=1):
        self.n += n
        return True


def fake_hub(cache, chunks=5, on_chunk=None, with_bar=True):
    hub = types.SimpleNamespace()
    hub.constants = types.SimpleNamespace(HF_HUB_CACHE=str(cache))
    hub.downloads = []
    hub.cached = {}
    if with_bar:
        hub.file_download = types.SimpleNamespace(tqdm=Bar)

    def try_to_load_from_cache(model, name):
        return hub.cached.get(name)

    def hf_hub_download(model, name, token=None):
        hub.downloads.append(name)
        bar = hub.file_download.tqdm(100) if with_bar else Bar(100)
        for i in range(chunks):
            if on_chunk:
                on_chunk(name, i)
            bar.update(20)
        path = Path(cache) / "models--acme--tiny-model" / "snapshots" / "abc" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return str(path)
    hub.try_to_load_from_cache, hub.hf_hub_download = try_to_load_from_cache, hf_hub_download
    return hub


FILES = [{"name": "config.json", "size": 1000}, {"name": "model.safetensors", "size": 4 * GB}]


class Case(unittest.TestCase):
    def setUp(self):
        self.cache = Path(tempfile.mkdtemp())
        p = mock.patch.object(lm, "_siblings", return_value=FILES)
        p.start()
        self.addCleanup(p.stop)

    def run_download(self, hub, free=100 * GB, cancelled=lambda: False, progress=None):
        with mock.patch.object(lm, "_hub", return_value=hub), mock.patch.object(lm.shutil, "disk_usage", return_value=types.SimpleNamespace(free=free)):
            return lm.download(MODEL, "fp16", "", progress, cancelled)


class SpaceTests(Case):
    def test_enough_space_downloads_and_registers_the_precision(self):
        hub = fake_hub(self.cache)
        snap = self.run_download(hub)
        self.assertEqual(hub.downloads, ["config.json", "model.safetensors"])
        self.assertEqual((snap / lm.MARKER).read_text(), "fp16")

    def test_a_full_disk_is_explained_before_anything_is_downloaded(self):
        hub = fake_hub(self.cache)
        with self.assertRaises(ProviderError) as cm:
            self.run_download(hub, free=2 * GB)
        msg = str(cm.exception)
        self.assertIn("Sem espaço em disco", msg)
        self.assertIn("4.0 GB", msg)
        self.assertIn("2.0 GB livres", msg)
        self.assertIn("Armazenamento", msg)
        self.assertEqual(cm.exception.status, 507)
        self.assertEqual(hub.downloads, [])                                                         # nem começou

    def test_what_is_already_in_the_cache_does_not_count(self):
        hub = fake_hub(self.cache)
        done = self.cache / "ja.safetensors"
        done.write_bytes(b"x")
        hub.cached["model.safetensors"] = str(done)                                                  # os 4 GB já estão aqui
        self.run_download(hub, free=1 * GB)                                                          # só falta o config.json
        self.assertEqual(hub.downloads, ["config.json", "model.safetensors"])

    def test_the_margin(self):
        hub = fake_hub(self.cache)
        with self.assertRaises(ProviderError):
            self.run_download(hub, free=4 * GB + 100 * 1024 ** 2)                                    # justo demais: sem folga para os temporários
        self.run_download(fake_hub(self.cache), free=4 * GB + 400 * 1024 ** 2)

    def test_a_hub_without_cache_helpers_still_checks_with_the_default_folder(self):
        hub = fake_hub(self.cache)
        del hub.constants
        del hub.try_to_load_from_cache
        with mock.patch.dict("os.environ", {"HF_HUB_CACHE": str(self.cache)}):
            with self.assertRaises(ProviderError):
                self.run_download(hub, free=1 * GB)


class CancelTests(Case):
    def test_cancel_in_the_middle_of_a_big_file(self):
        seen = {"chunks": 0}
        hub = fake_hub(self.cache, chunks=5, on_chunk=lambda name, i: seen.__setitem__("chunks", seen["chunks"] + 1))
        original = hub.file_download.tqdm
        with self.assertRaises(ProviderError) as cm:
            self.run_download(hub, cancelled=lambda: seen["chunks"] >= 3)
        self.assertEqual(str(cm.exception), "cancelado")
        self.assertEqual(hub.downloads, ["config.json"])                                              # parou DENTRO do primeiro arquivo, que tem 5 pedaços: o segundo nem começou
        self.assertEqual(seen["chunks"], 3)                                                           # no pedaço em que o pedido chegou, não no fim do arquivo
        self.assertIs(hub.file_download.tqdm, original)                                               # a barra original é devolvida
        self.assertEqual(list(self.cache.glob("**/flow_precision.txt")), [])                         # cancelado: o modelo NÃO fica marcado como baixado

    def test_cancel_before_starting_still_works(self):
        hub = fake_hub(self.cache)
        with self.assertRaises(ProviderError) as cm:
            self.run_download(hub, cancelled=lambda: True)
        self.assertEqual(str(cm.exception), "cancelado")
        self.assertEqual(hub.downloads, [])

    def test_the_bar_is_restored_even_after_an_error(self):
        hub = fake_hub(self.cache)
        original = hub.file_download.tqdm
        hub.hf_hub_download = mock.Mock(side_effect=OSError("sem rede"))
        with self.assertRaises(ProviderError):
            self.run_download(hub)
        self.assertIs(hub.file_download.tqdm, original)

    def test_a_hub_without_the_bar_downloads_normally(self):
        hub = fake_hub(self.cache, with_bar=False)
        snap = self.run_download(hub)
        self.assertTrue((snap / lm.MARKER).exists())

    def test_the_progress_still_reaches_the_screen(self):
        hub = fake_hub(self.cache)
        seen = []
        self.run_download(hub, progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen[-1], (4 * GB + 1000, 4 * GB + 1000))


class IdTests(unittest.TestCase):
    def test_a_huge_project_id_is_not_found_instead_of_a_500(self):
        from openflow.canvas.store import ProjectStore
        from openflow.storage import Store

        cs = Store(Path(tempfile.mkdtemp())).projects
        self.assertIsInstance(cs, ProjectStore)
        for cid in ("a" * 300, "x" * 101):
            self.assertFalse(cs.delete(cid))
            self.assertIsNone(cs.get(cid))
        created = cs.create("normal")["id"]
        self.assertTrue(cs.delete(created))


if __name__ == "__main__":
    unittest.main()
