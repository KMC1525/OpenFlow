"""v0.82: baixar e achar os modelos do nó «Modelo PyTorch/TensorFlow» — só os arquivos do framework escolhido, marcados como «para o nó» (não viram modelo de imagem), a busca mostra o framework de cada repositório e a API diz o que o nó vai achar.
O huggingface_hub e a rede são simulados; nenhum modelo real foi baixado."""
import json
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from openflow import hf
from openflow.canvas import localmodels as lm
from openflow.canvas import media as M
from openflow.canvas import modelrun as mr
from openflow.providers import ProviderError
from tests.test_canvas import provider
from tests.test_model_install_v078 import Case, fake_hub

GB = 1024 ** 3
REPO_FILES = [{"name": "config.json", "size": 100}, {"name": "README.md", "size": 5}, {"name": "model.safetensors", "size": 4 * GB}, {"name": "pytorch_model.bin", "size": 4 * GB},
              {"name": "esrgan.pt", "size": 70 * 1024 ** 2}, {"name": "esrgan.pt2", "size": 71 * 1024 ** 2}, {"name": "tf/esrgan.keras", "size": 60 * 1024 ** 2},
              {"name": "tf/tf_model.h5", "size": 9 * GB}, {"name": "saved_model/saved_model.pb", "size": 3 * 1024 ** 2}, {"name": "saved_model/variables/variables.index", "size": 1000},
              {"name": "saved_model/variables/variables.data-00000-of-00001", "size": 50 * 1024 ** 2}, {"name": "model.onnx", "size": 70 * 1024 ** 2}, {"name": "weights.gguf", "size": GB}]


class SelectTests(unittest.TestCase):
    def names(self, fw):
        return sorted(f["name"] for f in lm.select_tool_files(REPO_FILES, fw))

    def test_torch_keeps_only_runnable_torch_files_and_the_small_ones(self):
        self.assertEqual(self.names("torch"), ["config.json", "esrgan.pt", "esrgan.pt2"])

    def test_tf_keeps_keras_and_the_savedmodel_but_not_transformers_weights(self):
        n = self.names("tf")
        self.assertEqual(n, ["config.json", "saved_model/saved_model.pb", "saved_model/variables/variables.data-00000-of-00001", "saved_model/variables/variables.index", "tf/esrgan.keras"])
        self.assertNotIn("tf/tf_model.h5", n)

    def test_framework_of_a_file(self):
        self.assertEqual([lm.tool_framework_of(n) for n in ("a.keras", "a.h5", "tf_model.h5", "sub/model.weights.h5", "saved_model.pb", "variables/v.index", "a.pt", "a.pth", "a.pt2", "a.safetensors", "config.json")],
                         ["tf", "tf", "", "", "tf", "tf", "torch", "torch", "torch", "", ""])

    def test_options_lists_only_the_frameworks_the_repo_has(self):
        with mock.patch.object(lm, "_siblings", return_value=REPO_FILES):
            o = lm.tool_options("acme/esrgan")
        self.assertEqual(set(o["frameworks"]), {"torch", "tf"})
        self.assertEqual(o["frameworks"]["torch"]["files"], 3)
        self.assertGreater(o["frameworks"]["tf"]["size"], 100 * 1024 ** 2)
        with mock.patch.object(lm, "_siblings", return_value=[{"name": "model.safetensors", "size": 5}, {"name": "tf_model.h5", "size": 5}]):
            self.assertEqual(lm.tool_options("acme/x")["frameworks"], {})                              # só pesos: nada que o nó rode


class DownloadTests(Case):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(lm, "_siblings", return_value=REPO_FILES)
        p.start()
        self.addCleanup(p.stop)

    def dl(self, framework, hub=None):
        hub = hub or fake_hub(self.cache)
        with mock.patch.object(lm, "_hub", return_value=hub), mock.patch.object(lm.shutil, "disk_usage", return_value=types.SimpleNamespace(free=100 * GB)):
            return hub, lm.download("acme/tiny-model", "fp32", "", None, lambda: False, framework=framework)

    def test_downloads_only_the_chosen_framework_and_marks_it(self):
        hub, snap = self.dl("tf")
        self.assertEqual(sorted(hub.downloads), sorted(f["name"] for f in lm.select_tool_files(REPO_FILES, "tf")))
        self.assertEqual((snap / lm.FRAMEWORK_MARKER).read_text(), "tf")
        self.assertEqual((snap / lm.MARKER).read_text(), "fp32")
        with mock.patch.object(lm, "_snapshot", return_value=snap):
            self.assertEqual(lm.downloaded_framework("acme/tiny-model"), "tf")

    def test_a_normal_download_is_not_marked(self):
        hub = fake_hub(self.cache)
        with mock.patch.object(lm, "_hub", return_value=hub), mock.patch.object(lm.shutil, "disk_usage", return_value=types.SimpleNamespace(free=100 * GB)):
            snap = lm.download("acme/tiny-model", "fp16", "", None, lambda: False)
        self.assertFalse((snap / lm.FRAMEWORK_MARKER).exists())
        with mock.patch.object(lm, "_snapshot", return_value=snap):
            self.assertEqual(lm.downloaded_framework("acme/tiny-model"), "")

    def test_a_wrong_framework_is_refused_before_anything_is_downloaded(self):
        hub = fake_hub(self.cache)
        with mock.patch.object(lm, "_hub", return_value=hub):
            with self.assertRaises(ProviderError):
                lm.download("acme/tiny-model", "fp32", "", None, lambda: False, framework="jax")
        self.assertEqual(hub.downloads, [])

    def test_a_tool_model_is_not_an_image_model(self):
        _hub, snap = self.dl("torch")
        M._LOCAL_CACHE.clear()
        with mock.patch.object(lm, "_snapshot", return_value=snap), mock.patch.object(lm, "downloaded_precision", return_value="fp32"):
            p = provider("local_hf", "", {"image": "acme/tiny-model"}, key="", needs_key=False)
            p.ctl = types.SimpleNamespace(note=lambda m: None, check=lambda: None)
            with self.assertRaises(ProviderError) as cm:
                p._ready("acme/tiny-model")
        self.assertIn("Modelo PyTorch/TensorFlow", str(cm.exception))

    def test_tool_models_are_not_listed_among_the_installed_hf_models(self):
        from openflow.canvas import installed

        root = Path(tempfile.mkdtemp())
        for name, marked in (("models--a--img", False), ("models--b--tool", True)):
            snap = root / name / "snapshots" / "abc"
            snap.mkdir(parents=True)
            (snap / lm.MARKER).write_text("fp16")
            if marked:
                (snap / lm.FRAMEWORK_MARKER).write_text("tf")
        with mock.patch.object(installed, "hf_cache_dir", return_value=root):
            self.assertEqual([m["model"] for m in installed.downloaded_hf_models()], ["a/img"])


class SearchTests(unittest.TestCase):
    def test_original_search_rows_carry_the_frameworks(self):
        data = [{"id": "acme/a", "downloads": 9, "likes": 1, "tags": ["pytorch", "safetensors", "image-to-image"], "library_name": "diffusers"},
                {"id": "acme/b", "downloads": 8, "likes": 1, "tags": ["tf", "keras"], "library_name": "keras"},
                {"id": "acme/c", "downloads": 7, "likes": 1, "tags": ["jax", "pytorch", "tf"], "library_name": "transformers"}]
        hf.clear_cache()
        with mock.patch.object(hf.http, "get_json", return_value=data):
            rows = hf.search_original("", "", "tool")
        got = {r["id"]: r["frameworks"] for r in rows}
        self.assertEqual(got, {"acme/a": ["pytorch"], "acme/b": ["tensorflow"], "acme/c": ["pytorch", "tensorflow", "jax"]})

    def test_the_tool_search_asks_for_image_to_image_models(self):
        urls = []
        hf.clear_cache()
        with mock.patch.object(hf.http, "get_json", side_effect=lambda url, headers=None, timeout=0: urls.append(url) or []):
            hf.search_original("esrgan", "", "tool")
        self.assertTrue(urls and all("image-to-image" in u for u in urls))


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from openflow.server import make_server
        from openflow.storage import Store

        cls.store = Store(Path(tempfile.mkdtemp()))
        cls.httpd, _ = make_server("127.0.0.1", 0, cls.store)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, method, path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_info_for_a_local_file_a_missing_file_and_an_empty_field(self):
        d = Path(tempfile.mkdtemp())
        (d / "up.keras").write_bytes(b"x")
        code, r = self.call("GET", "/api/tool/info?model=" + urllib.request.quote(str(d / "up.keras")))
        self.assertEqual((code, r["found"], r["kind"], r["framework"], r["label"]), (200, True, "keras", "tf", "up.keras"))
        self.assertIn("libs", r)
        code, r = self.call("GET", "/api/tool/info?model=" + urllib.request.quote(str(d / "nope.pt")))
        self.assertEqual((r["found"], "Não achei" in r["error"]), (False, True))
        self.assertEqual(self.call("GET", "/api/tool/info?model=")[1]["found"], False)
        code, r = self.call("GET", "/api/tool/info?model=" + urllib.request.quote(str(d / "up.keras")) + "&framework=torch")
        self.assertFalse(r["found"])                                                                  # o nó pede PyTorch e o arquivo é Keras

    def test_info_says_which_library_is_missing(self):
        d = Path(tempfile.mkdtemp())
        (d / "net.pt").write_bytes(b"x")
        with mock.patch("openflow.canvas.frameworks.has_module", side_effect=lambda n: n != "torch"):
            r = self.call("GET", "/api/tool/info?model=" + urllib.request.quote(str(d / "net.pt")))[1]
        self.assertEqual((r["found"], r["missing_lib"]), (True, "PyTorch"))

    def test_files_and_validation(self):
        with mock.patch.object(lm, "_siblings", return_value=REPO_FILES):
            code, r = self.call("GET", "/api/tool/files?model=acme/esrgan")
        self.assertEqual((code, set(r["frameworks"])), (200, {"torch", "tf"}))
        self.assertEqual(self.call("GET", "/api/tool/files?model=..")[0], 400)

    def test_download_needs_a_framework_and_runs_a_job(self):
        self.assertEqual(self.call("POST", "/api/tool/download", {"model": "acme/esrgan", "framework": "jax"})[0], 400)
        self.assertEqual(self.call("POST", "/api/tool/download", {"model": "..", "framework": "tf"})[0], 400)
        seen = {}

        def fake_download(model, precision, token, progress, cancelled, framework=""):
            seen.update(model=model, precision=precision, framework=framework)
            return Path(".")
        with mock.patch.object(lm, "download", side_effect=fake_download):
            code, r = self.call("POST", "/api/tool/download", {"model": "acme/esrgan", "framework": "tf"})
            self.assertEqual(code, 200)
            import time
            for _ in range(60):
                st = self.call("GET", "/api/jobs/" + r["job_id"])[1].get("status")
                if st in ("done", "error"):
                    break
                time.sleep(0.1)
        self.assertEqual((st, seen), ("done", {"model": "acme/esrgan", "precision": "fp32", "framework": "tf"}))

    def test_use_sets_the_node_model(self):
        cid = self.store.projects.create("uso")["id"]
        self.store.projects.save_layout(cid, {"nodes": [{"id": "m", "type": "ai_model", "x": 0, "y": 0, "params": {}}, {"id": "i", "type": "image", "x": 0, "y": 0, "params": {}}], "edges": []})
        snap = Path(tempfile.mkdtemp())
        (snap / "esrgan.pt").write_bytes(b"x")
        with mock.patch.object(lm, "_snapshot", return_value=snap):
            code, r = self.call("POST", "/api/media/hub/use", {"cap": "tool", "provider": "tool", "model": "acme/esrgan", "canvas": cid, "node": "m"})
            self.assertEqual((code, r["node_updated"]), (200, True))
            code, r = self.call("POST", "/api/media/hub/use", {"cap": "tool", "provider": "tool", "model": "acme/esrgan", "canvas": cid, "node": "i"})
            self.assertEqual((code, r["node_updated"]), (200, False))                                  # o nó selecionado não é do tipo certo
        node = next(n for n in self.store.projects.get(cid)["nodes"] if n["id"] == "m")
        self.assertEqual(node["params"]["model"], "acme/esrgan")
        with mock.patch.object(lm, "_snapshot", return_value=None):
            self.assertEqual(self.call("POST", "/api/media/hub/use", {"cap": "tool", "provider": "tool", "model": "acme/other"})[0], 404)   # ainda não foi baixado

    def test_the_hub_accepts_the_tool_cap(self):
        hf.clear_cache()
        with mock.patch.object(hf.http, "get_json", return_value=[{"id": "acme/z", "downloads": 1, "likes": 0, "tags": ["tf"], "library_name": "keras"}]):
            code, r = self.call("GET", "/api/media/hub/search?q=&cap=tool&format=original")
        self.assertEqual(code, 200)
        self.assertEqual(r["results"][0]["frameworks"], ["tensorflow"])

    def test_frameworks_endpoint(self):
        fake = {"system": "Linux", "machine": "x86_64", "python": "3.13", "gpu_vendors": [], "torch": {"installed": False}, "tensorflow": {"installed": False, "keras": ""},
                "advice": {"torch": [{"level": "warn", "text": "x", "text_en": "x"}], "tensorflow": []}}
        with mock.patch("openflow.canvas.frameworks.report", return_value=fake) as rep:
            code, r = self.call("GET", "/api/media/frameworks?refresh=1")
            self.assertEqual((code, r["advice"]["torch"][0]["level"]), (200, "warn"))
            self.call("GET", "/api/media/frameworks")
            self.assertEqual(rep.call_count, 1)                                                        # o 2º pedido vem do cache de 30 s
            self.call("GET", "/api/media/frameworks?refresh=1")
            self.assertEqual(rep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
