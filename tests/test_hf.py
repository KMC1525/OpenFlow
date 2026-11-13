"""Modelos locais do Hugging Face: identificação e escolha da quantização, modelos divididos em partes e download."""
import json
import re
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import hf  # noqa: E402
from openflow.providers.base import ProviderError  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402
from tests.helpers import ServerCase  # noqa: E402

GB = 1024 ** 3
FILES = {  # nome no repositório → conteúdo
    "tiny-Q2_K.gguf": b"2" * 200, "tiny-Q4_K_M.gguf": b"4" * 400, "tiny-Q5_K_M.gguf": b"5" * 500, "tiny-Q8_0.gguf": b"8" * 800, "tiny-F16.gguf": b"f" * 1600,
    "mmproj-tiny-F16.gguf": b"p" * 50,
    "big/huge-Q4_K_M-00001-of-00003.gguf": b"a" * 300, "big/huge-Q4_K_M-00002-of-00003.gguf": b"b" * 300, "big/huge-Q4_K_M-00003-of-00003.gguf": b"c" * 100,
    "broken-Q6_K-00001-of-00002.gguf": b"x" * 10,  # falta a parte 2
    "README.md": b"# readme",
}


class FakeHF:
    def __init__(self):
        outer = self
        self.downloads = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/api/models?"):
                    return self._json([{"id": "dono/modelo", "downloads": 1234, "likes": 7}])
                if "/tree/main" in self.path:
                    tree = [{"type": "file", "path": n, "size": len(b), "lfs": {"size": len(b)}} for n, b in FILES.items()] + [{"type": "directory", "path": "big"}]
                    return self._json(tree)
                m = re.match(r"^/dono/modelo/resolve/main/(.+)$", self.path)
                if m:
                    import urllib.parse
                    name = urllib.parse.unquote(m.group(1))
                    data = FILES.get(name)
                    if data is None:
                        return self._json({"error": "nope"}, 404)
                    outer.downloads.append(name)
                    rng = re.match(r"bytes=(\d+)-", self.headers.get("Range") or "")
                    start = int(rng.group(1)) if rng else 0
                    self.send_response(206 if rng else 200)
                    self.send_header("Content-Length", str(len(data) - start))
                    self.end_headers()
                    self.wfile.write(data[start:])
                    return
                self._json({"error": "nope"}, 404)

            def _json(self, obj, status=200):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class QuantTests(unittest.TestCase):
    def test_quantization_is_read_from_the_file_name(self):
        cases = {"Qwen2.5-7B-Instruct-Q4_K_M.gguf": ("Q4_K_M", 4, "good"), "model.Q8_0.gguf": ("Q8_0", 8, "lossless"), "gemma-IQ3_XXS.gguf": ("IQ3_XXS", 3, "low"),
                 "x-UD-Q4_K_XL.gguf": ("Q4_K_XL", 4, "good"), "llama-f16.gguf": ("F16", 16, "original"), "llama-bf16.gguf": ("BF16", 16, "original"),
                 "q2_k/m-Q2_K-00001-of-00002.gguf": ("Q2_K", 2, "very_low"), "m-Q6_K.gguf": ("Q6_K", 6, "high"), "tinyllama.gguf": ("", 0, "")}
        for name, (q, bits, quality) in cases.items():
            r = hf.parse_quant(name)
            self.assertEqual((r["quant"], r["bits"], r["quality"]), (q, bits, quality), name)

    def test_grouping_parts_filtering_and_recommendation(self):
        raw = [{"name": n, "size": len(b) * 1000} for n, b in FILES.items() if n.endswith(".gguf")]
        opts = hf.group_files(raw, 0)
        names = [o["name"] for o in opts]
        self.assertNotIn("mmproj-tiny-F16.gguf", names)  # projetor de visão não é uma quantização
        self.assertFalse([n for n in names if "broken" in n])  # partes faltando: não dá para usar
        huge = next(o for o in opts if o["name"].startswith("big/"))
        self.assertEqual((huge["parts"], huge["size"], len(huge["files"]), huge["quant"]), (3, 700000, 3, "Q4_K_M"))
        self.assertEqual(list(huge["sizes"].values()), [300000, 300000, 100000])
        self.assertEqual([o["size"] for o in opts], sorted(o["size"] for o in opts))
        self.assertEqual(sum(o["recommended"] for o in opts), 1)
        # com bastante RAM: a recomendada é a Q4_K_M (equilíbrio), nunca a F16
        big = hf.group_files([{"name": "m-Q2_K.gguf", "size": 3 * GB}, {"name": "m-Q4_K_M.gguf", "size": 5 * GB}, {"name": "m-Q8_0.gguf", "size": 9 * GB}, {"name": "m-F16.gguf", "size": 20 * GB}], 32)
        self.assertEqual([o["quant"] for o in big if o["recommended"]], ["Q4_K_M"])
        self.assertEqual([o["fits"] for o in big], [True, True, True, False])  # F16: 20 GB > 60% de 32 GB
        # RAM curta: a maior que cabe; sem nenhuma que caiba, a menor de todas
        mid = hf.group_files([{"name": "m-Q2_K.gguf", "size": 3 * GB}, {"name": "m-Q3_K_M.gguf", "size": 4 * GB}, {"name": "m-Q8_0.gguf", "size": 9 * GB}], 8)
        self.assertEqual([o["quant"] for o in mid if o["recommended"]], ["Q3_K_M"])
        tiny = hf.group_files([{"name": "m-Q4_K_M.gguf", "size": 5 * GB}, {"name": "m-Q8_0.gguf", "size": 9 * GB}], 4)
        self.assertEqual([o["quant"] for o in tiny if o["recommended"]], ["Q4_K_M"])
        self.assertFalse(any(o["fits"] for o in tiny))


class DownloadTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeHF()
        patcher = mock.patch.object(hf, "HF", self.fake.url)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.fake.close)
        self.models = self.tmp / "models"
        self.models.mkdir()

    def test_list_files_over_http(self):
        opts = hf.list_files("dono/modelo", "", 16)
        self.assertEqual([o["quant"] for o in opts if o["recommended"]], ["Q4_K_M"])
        self.assertTrue({"Q2_K", "Q4_K_M", "Q5_K_M", "Q8_0", "F16"} <= {o["quant"] for o in opts})
        with self.assertRaises(ProviderError):
            hf.list_files("../../x", "")

    def test_split_model_downloads_every_part_with_summed_progress(self):
        opt = next(o for o in hf.list_files("dono/modelo", "", 16) if o["parts"] == 3)
        seen = []
        first = hf.download_many("dono/modelo", opt["files"], self.models, "", opt["sizes"], lambda d, t: seen.append((d, t)))
        self.assertEqual(first.name, "huge-Q4_K_M-00001-of-00003.gguf")
        self.assertEqual(sorted(p.name for p in self.models.glob("*.gguf")), ["huge-Q4_K_M-00001-of-00003.gguf", "huge-Q4_K_M-00002-of-00003.gguf", "huge-Q4_K_M-00003-of-00003.gguf"])
        self.assertEqual(seen[-1], (700, 700))
        self.assertTrue(all(t == 700 for _, t in seen))
        local = hf.local_models(self.models)
        self.assertEqual([(m["name"], m["parts"], m["size"], m["quant"]) for m in local], [("huge-Q4_K_M-00001-of-00003.gguf", 3, 700, "Q4_K_M")])
        # retomada: partes já completas não são baixadas de novo
        self.fake.downloads.clear()
        hf.download_many("dono/modelo", opt["files"], self.models, "", opt["sizes"])
        self.assertEqual(self.fake.downloads, [])
        # uma parte faltando esconde o modelo (ele não carregaria)
        (self.models / "huge-Q4_K_M-00002-of-00003.gguf").unlink()
        self.assertEqual(hf.local_models(self.models), [])

    def test_validation_and_disk_check(self):
        with self.assertRaises(ProviderError):
            hf.download_many("dono/modelo", [], self.models)
        with self.assertRaises(ProviderError):
            hf.download_many("dono/modelo", ["../evil.gguf"], self.models)
        with mock.patch("openflow.hf.shutil.disk_usage", return_value=mock.Mock(free=10)):
            with self.assertRaises(ProviderError) as cm:
                hf.download_many("dono/modelo", ["tiny-Q4_K_M.gguf"], self.models, "", {"tiny-Q4_K_M.gguf": 400})
        self.assertIn("espaço", str(cm.exception))


class GgufKindsTests(ServerCase):
    """Modelos GGUF separados por tipo: texto, imagem, vídeo, som, voz e outros (busca, pasta e lista próprias)."""



class HfApiTests(ServerCase):
    def test_choose_a_quantization_download_use_and_delete(self):
        fake = FakeHF()
        try:
            with mock.patch.object(hf, "HF", fake.url):
                status, r = self.c.json("GET", "/api/hf/files?repo=dono/modelo")
                self.assertEqual(status, 200)
                files = r["files"]
                self.assertTrue(all("quant" in f and "recommended" in f and "fits" in f for f in files))
                q5 = next(f for f in files if f["quant"] == "Q5_K_M")
                status, job = self.c.json("POST", "/api/hf/download", {"repo": "dono/modelo", "files": q5["files"], "sizes": q5["sizes"], "quant": "Q5_K_M"})
                self.assertEqual(status, 200)
                ev = self.c.sse(f"/api/jobs/{job['job_id']}/events")
                self.assertEqual([e for e in ev if e["type"] == "done"][0]["name"], "tiny-Q5_K_M.gguf")
                local = self.c.json("GET", "/api/hf/local")[1]["models"]
                self.assertIn(("tiny-Q5_K_M.gguf", "Q5_K_M"), [(m["name"], m["quant"]) for m in local])
                # modelo dividido: baixa as 3 partes, aparece uma vez e apaga tudo de uma vez
                big = next(f for f in files if f["parts"] == 3)
                job = self.c.json("POST", "/api/hf/download", {"repo": "dono/modelo", "files": big["files"], "sizes": big["sizes"], "quant": "Q4_K_M"})[1]
                self.c.sse(f"/api/jobs/{job['job_id']}/events")
                local = self.c.json("GET", "/api/hf/local")[1]["models"]
                self.assertEqual([m["parts"] for m in local if m["name"].startswith("huge")], [3])
                self.assertEqual(self.c.json("DELETE", "/api/hf/local/" + big["files"][0].split("/")[-1])[0], 200)
                self.assertEqual([m["name"] for m in self.c.json("GET", "/api/hf/local")[1]["models"] if m["name"].startswith("huge")], [])
                self.assertEqual(len(list(self.store.models_dir.glob("huge*"))), 0)
                self.c.json("DELETE", "/api/hf/local/tiny-Q5_K_M.gguf")
                # compatibilidade: o campo antigo `file` continua funcionando
                job = self.c.json("POST", "/api/hf/download", {"repo": "dono/modelo", "file": "tiny-Q2_K.gguf", "quant": "Q2_K"})[1]
                self.assertTrue([e for e in self.c.sse(f"/api/jobs/{job['job_id']}/events") if e["type"] == "done"])
                self.c.json("DELETE", "/api/hf/local/tiny-Q2_K.gguf")
                self.assertEqual(self.c.json("POST", "/api/hf/download", {"repo": "dono/modelo"})[0], 400)
                # sem escolher a quantização o OpenFlow não baixa nada, nem com a lista de arquivos pronta
                status, err = self.c.json("POST", "/api/hf/download", {"repo": "dono/modelo", "files": ["tiny-Q2_K.gguf"]})
                self.assertEqual(status, 400)
                self.assertIn("quantização", err["error"])
                self.assertFalse((self.store.models_dir / "tiny-Q2_K.gguf").exists())
        finally:
            fake.close()


if __name__ == "__main__":
    unittest.main()
