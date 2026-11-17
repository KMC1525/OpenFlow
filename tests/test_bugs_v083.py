"""v0.83: bugs achados na caça — quatro, nos recursos das últimas versões:
1. «Quantização ao carregar» pedia Q8 para um arquivo Q5 (e outros tipos que não são uma das cinco faixas) e «recomprimia para cima»: agora só vale para uma faixa MENOR;
2. criar uma faixa de um modelo de TEXTO podia travar para sempre: a saída do llama.cpp ia para um pipe que ninguém lia (o buffer enche, o processo para);
3. «Procurar em outros repositórios» oferecia outro modelo («Z-Image-Turbo» para quem procura o «Z-Image»);
4. o nó «Modelo PyTorch/TensorFlow» varria a pasta inteira (e a pasta pessoal, se fosse o caminho) a cada conferência do canvas."""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from openflow import hf
from openflow.canvas import modelrun as mr
from openflow.canvas import nodes_ext
from openflow.canvas import quants as Q
from openflow.canvas import requant


class UseTierTests(unittest.TestCase):
    def test_file_bits(self):
        self.assertEqual([Q.file_bits(q) for q in ("Q5_K_M", "IQ3_XS", "UD-Q8_K_XL", "Q1_0", "F16", "BF16", "F32", "", "MXFP4", "Q4_0")], [5, 3, 8, 1, 16, 16, 32, 0, 0, 4])

    def test_a_q5_file_is_not_recompressed_up_to_q6_or_q8(self):
        for tier in ("Q6", "Q8"):
            load, note = Q.with_weight_type({}, "Q5_K_M", tier)
            self.assertNotIn("wtype", load, tier)
            self.assertIn("já é Q5_K_M (5 bits)", note)
        self.assertEqual(Q.with_weight_type({}, "Q5_K_M", "Q4")[0], {"wtype": "q4_k"})            # para baixo continua valendo
        self.assertEqual(Q.with_weight_type({}, "Q5_K_M", "Q2")[0], {"wtype": "q2_k"})

    def test_other_non_tier_types(self):
        self.assertNotIn("wtype", Q.with_weight_type({}, "Q1_0", "Q2")[0])
        self.assertNotIn("wtype", Q.with_weight_type({}, "IQ4_XS", "Q6")[0])
        self.assertEqual(Q.with_weight_type({}, "BF16", "Q8")[0], {"wtype": "q8_0"})
        self.assertEqual(Q.with_weight_type({}, "", "Q4")[0], {"wtype": "q4_k"})                  # tipo desconhecido: tenta (o arquivo pode ser F16)


class LlamaQuantizeTests(unittest.TestCase):
    def test_a_chatty_child_does_not_deadlock(self):
        d = Path(tempfile.mkdtemp())
        src, dst = d / "m-Q8_0.gguf", d / "out.gguf"
        src.write_bytes(b"x")
        chatty = ("import sys\nfor i in range(40000):\n    sys.stderr.write('[quantize] tensor blk.%d.attn_q.weight q8_0 -> q4_K size = 12.00 MiB -> 3.00 MiB\\n' % i)\n"
                  "open(sys.argv[2], 'wb').write(b'G' * 4096)\n")
        box = {}

        def go():
            try:
                with mock.patch.object(requant, "_LLAMA_SCRIPT", chatty):
                    requant.convert_llama(src, dst, "Q4", lambda: False, lambda m: None)
                box["ok"] = True
            except Exception as exc:  # noqa: BLE001
                box["err"] = exc
        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(60)
        self.assertFalse(t.is_alive(), "travou: o filho ficou preso escrevendo num pipe que ninguém lê")
        self.assertTrue(box.get("ok"), box)
        self.assertEqual(dst.stat().st_size, 4096)

    def test_the_error_shows_the_end_of_a_long_log(self):
        d = Path(tempfile.mkdtemp())
        src = d / "m-Q8_0.gguf"
        src.write_bytes(b"x")
        failing = "import sys\nfor i in range(20000):\n    sys.stderr.write('linha %d\\n' % i)\nsys.stderr.write('llama_model_quantize: failed to quantize: bad tensor\\n')\nsys.exit(3)\n"
        with mock.patch.object(requant, "_LLAMA_SCRIPT", failing):
            with self.assertRaises(Exception) as cm:
                requant.convert_llama(src, d / "o.gguf", "Q4", lambda: False, lambda m: None)
        self.assertIn("bad tensor", str(cm.exception))
        self.assertIn("código 3", str(cm.exception))

    def test_cancel_kills_the_child(self):
        d = Path(tempfile.mkdtemp())
        src = d / "m-Q8_0.gguf"
        src.write_bytes(b"x")
        with mock.patch.object(requant, "_LLAMA_SCRIPT", "import time\ntime.sleep(60)\n"):
            t0 = time.time()
            with self.assertRaises(Exception) as cm:
                requant.convert_llama(src, d / "o.gguf", "Q4", lambda: time.time() - t0 > 1.0, lambda m: None)
        self.assertEqual(str(cm.exception), "cancelado")
        self.assertLess(time.time() - t0, 10)


class OtherReposTests(unittest.TestCase):
    def test_only_the_same_model_is_offered(self):
        def fake_search(q, token="", limit=20, kind="text"):
            return [{"id": "a/Z-Image-GGUF", "downloads": 1}, {"id": "b/Z-Image-Turbo-GGUF", "downloads": 99}, {"id": "c/z-image-gguf", "downloads": 50}, {"id": "d/Z-Image-Edit-GGUF", "downloads": 9},
                    {"id": "e/Z_Image_quantized", "downloads": 7}]
        tree = [{"name": "m-Q2_K.gguf", "size": 1}, {"name": "m-Q3_K_S.gguf", "size": 2}]
        with mock.patch.object(hf, "search", side_effect=fake_search), mock.patch.object(hf, "repo_files", return_value=tree):
            rows = hf.other_repos("a/Z-Image-GGUF", "image", ["Q2", "Q3"], "")
        self.assertEqual(sorted(r["repo"] for r in rows), ["c/z-image-gguf", "e/Z_Image_quantized"])      # nem o Turbo nem o Edit: são outros modelos

    def test_the_turbo_does_not_get_the_base_model(self):
        with mock.patch.object(hf, "search", return_value=[{"id": "a/Z-Image-GGUF", "downloads": 5}, {"id": "b/Z-Image-Turbo-GGUF", "downloads": 9}]), mock.patch.object(hf, "repo_files", return_value=[{"name": "m-Q2_K.gguf", "size": 1}]):
            rows = hf.other_repos("x/Z-Image-Turbo-GGUF", "image", ["Q2"], "")
        self.assertEqual([r["repo"] for r in rows], ["b/Z-Image-Turbo-GGUF"])


class ScanTests(unittest.TestCase):
    def test_walk_is_bounded_in_files_and_depth(self):
        d = Path(tempfile.mkdtemp())
        for i in range(mr.MAX_SCAN + 500):
            (d / f"f{i}.txt").write_bytes(b"")
        self.assertEqual(len(list(mr.walk(d))), mr.MAX_SCAN)
        deep = Path(tempfile.mkdtemp())
        cur = deep
        for i in range(mr.MAX_DEPTH + 3):
            cur = cur / f"d{i}"
            cur.mkdir()
            (cur / f"m{i}.keras").write_bytes(b"x")
        found = [p.name for p in mr.walk(deep)]
        self.assertIn(f"m{mr.MAX_DEPTH - 1}.keras", found)
        self.assertNotIn(f"m{mr.MAX_DEPTH + 2}.keras", found)

    def test_hidden_cache_and_linked_folders_are_skipped(self):
        d = Path(tempfile.mkdtemp())
        for sub in (".git", "__pycache__", "node_modules", ".hidden", "ok"):
            (d / sub).mkdir()
            (d / sub / "m.keras").write_bytes(b"x")
        outside = Path(tempfile.mkdtemp())
        (outside / "secret.keras").write_bytes(b"x")
        try:
            os.symlink(outside, d / "link")
        except OSError:
            pass
        names = sorted(str(p.relative_to(d)) for p in mr.walk(d))
        self.assertEqual(names, [os.path.join("ok", "m.keras")])

    def test_candidates_on_a_huge_folder_return_quickly(self):
        d = Path(tempfile.mkdtemp())
        for i in range(6000):
            (d / f"x{i}.txt").write_bytes(b"")
        (d / "net.pt").write_bytes(b"x")
        t0 = time.time()
        self.assertEqual([c.name for c in mr.candidates(d)], ["net.pt"] if "net.pt" in [p.name for p in mr.walk(d)] else [])
        self.assertLess(time.time() - t0, 5)


class SignatureCacheTests(unittest.TestCase):
    def test_the_signature_is_cached_for_a_few_seconds(self):
        nodes_ext._SIG_CACHE.clear()
        node = {"params": {"model": "/x/model.keras", "framework": "auto"}}
        eng = mock.Mock()
        calls = []
        with mock.patch.object(mr, "resolve", side_effect=lambda *a, **k: calls.append(1) or (Path("/x/model.keras"), "keras")), mock.patch.object(mr, "fingerprint", return_value="1-2"):
            a = nodes_ext.model_signature(eng, node)
            b = nodes_ext.model_signature(eng, node)
            self.assertEqual((a, b, len(calls)), ("/x/model.keras|1-2", "/x/model.keras|1-2", 1))
            node2 = {"params": {"model": "/x/other.keras", "framework": "auto"}}
            nodes_ext.model_signature(eng, node2)
            self.assertEqual(len(calls), 2)                                                      # outro modelo: outra chave
        nodes_ext._SIG_CACHE.clear()


class ModelNodeImageTests(unittest.TestCase):
    """O nó «Modelo PyTorch/TensorFlow» com imagens ruins: erro claro, não «Erro inesperado»."""

    def run_node(self, data, wh=None):
        import io

        from PIL import Image

        from openflow.canvas import modelrun
        from openflow.canvas.engine import CanvasEngine
        from openflow.storage import Store
        from tests.test_modelrun_v082 import FakeRunner

        store = Store(Path(tempfile.mkdtemp()))
        cs = store.projects
        cid = cs.create("x")["id"]
        a = cs.add_asset(cid, data, "png", "image", name="f.png", mime="image/png", provider="upload")
        model = Path(tempfile.mkdtemp()) / "up.keras"
        model.write_bytes(b"x")
        cs.save_layout(cid, {"nodes": [{"id": "m", "type": "ai_model", "x": 0, "y": 0, "params": {"model": str(model)}}, {"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [a["id"]]}}],
                             "edges": [{"id": "e", "from": "u", "to": "m", "port": "image"}]})
        events = []
        with mock.patch.object(modelrun, "load_keras", return_value=FakeRunner()), mock.patch.object(Image, "MAX_IMAGE_PIXELS", wh or Image.MAX_IMAGE_PIXELS):
            CanvasEngine(store, cid, events.append, lambda: False).run(None, True)
        return next((e.get("message") for e in events if e.get("type") == "node" and e.get("id") == "m" and e.get("state") == "error"), None)

    def png(self, w=40, h=30):
        import io

        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (w, h), (9, 9, 9)).save(b, "PNG")
        return b.getvalue()

    def test_a_decompression_bomb_is_explained(self):
        msg = self.run_node(self.png(200, 200), wh=1000)
        self.assertIsNotNone(msg)
        self.assertIn("grande demais", msg)
        self.assertNotIn("inesperado", msg.lower())

    def test_a_truncated_image_is_explained(self):
        msg = self.run_node(self.png()[:60])
        self.assertIn("corrompido ou incompleto", msg or "")

    def test_a_good_image_runs(self):
        self.assertIsNone(self.run_node(self.png()))


class FrameworksCardTests(unittest.TestCase):
    """O card das Configurações não carrega o TensorFlow (≈ 400 MB de RAM) só porque alguém abriu a tela."""

    def test_the_screen_report_does_not_import_tensorflow(self):
        from openflow.canvas import frameworks as fw
        seen = []
        with mock.patch.object(fw, "torch_info", return_value={"installed": False}), mock.patch.object(fw, "vendors", return_value=[]), \
                mock.patch.object(fw, "tf_info", side_effect=lambda probe=True: seen.append(probe) or {"installed": True, "version": "2.21.0", "keras": "3", "probed": probe, "gpus": []}), \
                mock.patch.dict(sys.modules, {}, clear=False):
            sys.modules.pop("tensorflow", None)
            r = fw.report(probe_tf=False)
            self.assertEqual(seen, [False])
            self.assertIn("Verificar o TensorFlow", r["advice"]["tensorflow"][0]["text"])
            self.assertIn("Check TensorFlow", r["advice"]["tensorflow"][0]["text_en"])
            seen.clear()
            fw.report(probe_tf=True)
            self.assertEqual(seen, [True])
            seen.clear()
            with mock.patch.dict(sys.modules, {"tensorflow": types_module()}):
                fw.report(probe_tf=False)                                                         # já carregado: ler é de graça
            self.assertEqual(seen, [True])

    def test_the_api_loads_tensorflow_only_when_asked(self):
        import json
        import urllib.request

        from openflow.server import make_server
        from openflow.storage import Store

        httpd, _ = make_server("127.0.0.1", 0, Store(Path(tempfile.mkdtemp())))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        port = httpd.server_address[1]
        calls = []
        fake = {"system": "Linux", "machine": "x", "python": "3", "gpu_vendors": [], "torch": {"installed": False}, "tensorflow": {"installed": False, "keras": ""}, "advice": {"torch": [], "tensorflow": []}}
        try:
            with mock.patch("openflow.canvas.frameworks.report", side_effect=lambda **kw: calls.append(kw) or fake):
                for q in ("?refresh=1", "?tf=1"):
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/media/frameworks{q}", timeout=20).read()
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertEqual(calls, [{"probe_tf": False}, {"probe_tf": True}])


def types_module():
    import types
    return types.ModuleType("tensorflow")


if __name__ == "__main__":
    unittest.main()
