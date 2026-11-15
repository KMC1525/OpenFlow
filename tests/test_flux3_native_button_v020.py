"""v0.20: o erro «não reconhece o formato» agora tem o botão que baixa o GGUF compatível equivalente (Q4_K_M → Q4_K do leejet) e já o escolhe no nó."""
import time
import unittest
from pathlib import Path
from unittest import mock

from openflow import hf
from tests.helpers import ServerCase
from tests.test_canvas import node

LEEJET = [{"name": f"flux3-image-klein-{q}.gguf", "size": s} for q, s in (("Q2_K", 2_277_604_544), ("Q3_K", 2_813_385_920), ("Q4_0", 3_514_023_104), ("Q4_K", 3_514_023_104),
                                                                               ("Q5_K", 4_173_446_336), ("Q6_K", 4_874_083_520), ("Q8_0", 6_151_716_032))]


class PickTests(unittest.TestCase):
    def groups(self):
        return hf.group_files(LEEJET, 16)

    def test_the_equivalent_quantization_is_chosen(self):
        g = self.groups()
        self.assertEqual(hf.pick_equivalent("flux-3-image-klein-Q4_K_M.gguf", g)["name"], "flux3-image-klein-Q4_K.gguf")     # Q4_K_M ≈ Q4_K (não o Q4_0)
        self.assertEqual(hf.pick_equivalent("flux-3-image-klein-Q4_K_S.gguf", g)["name"], "flux3-image-klein-Q4_K.gguf")
        self.assertEqual(hf.pick_equivalent("x-Q5_K_M.gguf", g)["name"], "flux3-image-klein-Q5_K.gguf")
        self.assertEqual(hf.pick_equivalent("x-Q8_0.gguf", g)["name"], "flux3-image-klein-Q8_0.gguf")
        self.assertEqual(hf.pick_equivalent("x-Q4_0.gguf", g)["name"], "flux3-image-klein-Q4_0.gguf")                       # igual exato antes da família
        self.assertEqual(hf.pick_equivalent("x-IQ3_XS.gguf", g)["bits"], 3)                                                  # sem família igual: os bits mais próximos
        self.assertIsNotNone(hf.pick_equivalent("sem-quantizacao.gguf", g))                                                   # sem rótulo: a recomendada
        self.assertIsNone(hf.pick_equivalent("x-Q4_K_M.gguf", []))


class RouteTests(ServerCase):
    def setUp(self):
        self.files = {}

    def download(self, repo, names, dest, token, sizes, progress, cancelled, *a, **k):
        self.files["repo"], self.files["names"] = repo, list(names)
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / names[0]).write_bytes(b"gguf")
        return Path(dest) / names[0]

    def test_info_then_download_and_use_on_the_node(self):
        cv = self.store.projects.create("Modelos")
        self.store.projects.save_layout(cv["id"], {"nodes": [node("image", nid="im", model="flux-3-image-klein-Q4_K_M.gguf", provider="gguf_local")], "edges": []})
        with mock.patch.object(hf, "repo_files", return_value=LEEJET), mock.patch.object(hf, "download_many", side_effect=self.download):
            s, r = self.c.json("GET", "/api/media/sd-native?model=flux-3-image-klein-Q4_K_M.gguf")
            self.assertEqual(s, 200, r)
            self.assertEqual((r["repo"], r["file"], r["quant"], r["installed"]), ("leejet/flux-3-image-klein-GGUF", "flux3-image-klein-Q4_K.gguf", "Q4_K", False))
            self.assertEqual(self.c.json("GET", "/api/media/sd-native?model=qwen-image-Q4.gguf")[0], 404)              # sem repositório de referência conhecido
            s, r = self.c.json("POST", "/api/media/sd-native", {"model": "flux-3-image-klein-Q4_K_M.gguf", "canvas": cv["id"], "node": "im"})
            self.assertEqual(s, 200, r)
            self.assertEqual(r["file"], "flux3-image-klein-Q4_K.gguf")
            for _ in range(100):
                if self.app.jobs.jobs[r["job_id"]].status != "running":
                    break
                time.sleep(0.05)
        self.assertEqual(self.files["repo"], "leejet/flux-3-image-klein-GGUF")
        self.assertEqual(self.files["names"], ["flux3-image-klein-Q4_K.gguf"])
        n = next(x for x in self.store.projects.get(cv["id"])["nodes"] if x["id"] == "im")
        self.assertEqual(n["params"]["model"], "flux3-image-klein-Q4_K.gguf")                                              # o nó já usa o arquivo novo
        self.assertEqual(self.store.get_settings()["media"]["models"]["gguf_local"]["image"], "flux3-image-klein-Q4_K.gguf")
        with mock.patch.object(hf, "repo_files", return_value=LEEJET):
            s, r = self.c.json("GET", "/api/media/sd-native?model=flux-3-image-klein-Q4_K_M.gguf")
            self.assertTrue(r["installed"])                                                                                 # já baixado: o botão vira «Usar»

    def test_network_failure_is_reported(self):
        from openflow.providers.base import ProviderError

        with mock.patch.object(hf, "repo_files", side_effect=ProviderError("sem rede")):
            s, r = self.c.json("GET", "/api/media/sd-native?model=flux-3-image-klein-Q4_K_M.gguf")
        self.assertEqual(s, 502)
        self.assertIn("sem rede", str(r))


if __name__ == "__main__":
    unittest.main()
