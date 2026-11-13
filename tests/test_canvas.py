"""Canvas: esquema/validação do grafo, armazenamento, geradores procedurais, adaptadores de provedores (com servidor simulado),
motor de execução (cache, estilos, erros, cancelamento), Editor (ffmpeg) e API HTTP."""
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow.agents.runner import Cancelled  # noqa: E402
from openflow.canvas import media as M  # noqa: E402
from openflow.canvas import procedural as proc  # noqa: E402
from openflow.canvas import schema as S  # noqa: E402
from openflow.canvas.engine import CanvasEngine, palette_of  # noqa: E402
from openflow.canvas.render import render_timeline  # noqa: E402
from openflow.canvas.store import ProjectStore  # noqa: E402
from openflow.providers.base import ProviderError  # noqa: E402
from openflow.storage import Store  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402
from tests.helpers import ServerCase  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
PNG = proc.image("teste de mock", "64x64", 1)
WAV = proc.sound_fx("chuva", 1.0, 1)
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" * 50
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def node(ntype, x=0, y=0, nid=None, **params):
    return {"id": nid or f"n_{ntype}_{x}", "type": ntype, "x": x, "y": y, "params": params}


def edge(a, b, port):
    return {"from": a, "to": b, "port": port}


class MediaMock:
    """Imita (de forma mínima) as APIs de mídia dos provedores e grava o que recebe."""

    def __init__(self):
        self.requests = []
        self.polls = {}
        self.fail_next = []  # status HTTP a devolver nas próximas chamadas POST
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _read(self):
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _send(self, status, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _rec(self, method):
                raw = self._read() if method != "GET" else b""
                ctype = self.headers.get("Content-Type", "")
                body = None
                if "json" in ctype:
                    body = json.loads(raw or b"{}")
                rec = {"method": method, "path": self.path, "h": {k.lower(): v for k, v in self.headers.items()}, "body": body, "raw": raw}
                outer.requests.append(rec)
                return rec

            def do_GET(self):
                rec = self._rec("GET")
                p = self.path.split("?")[0]
                base = f"http://127.0.0.1:{outer.port}"
                if p.endswith("/models") and p.startswith("/v1/") and "/models/" not in p:
                    return self._send(200, {"data": [{"id": "gpt-image-1"}, {"id": "tts-1"}, {"id": "whisper-1"}, {"id": "gpt-4o"}]})
                if p == "/v1/voices":
                    return self._send(200, {"voices": [{"voice_id": "abc123abc123abc123ab", "name": "Rachel"}, {"voice_id": "zzz999zzz999zzz999zz", "name": "Antônio"}]})
                if p == "/v1/models/black-forest-labs/flux-schnell":
                    props = {"prompt": {}, "aspect_ratio": {}, "num_outputs": {}, "seed": {}}
                    return self._send(200, {"latest_version": {"id": "v123", "openapi_schema": {"components": {"schemas": {"Input": {"properties": props}}}}}})
                if p == "/v1/models/owner/community":
                    return self._send(200, {"latest_version": {"id": "ver999", "openapi_schema": {"components": {"schemas": {"Input": {"properties": {"prompt": {}}}}}}}})
                if p == "/v1/predictions/p1":
                    n = outer.polls["p1"] = outer.polls.get("p1", 0) + 1
                    if n < 2:
                        return self._send(200, {"status": "processing", "urls": {"get": f"{base}/v1/predictions/p1"}})
                    return self._send(200, {"status": "succeeded", "output": [f"{base}/files/a.png"]})
                if p == "/v1/account":
                    return self._send(200, {"username": "tester"})
                if p == "/files/a.png":
                    return self._send(200, PNG, "image/png")
                if p == "/files/v.mp4":
                    return self._send(200, MP4, "application/octet-stream")
                if p == "/v1/videos/vid1":
                    n = outer.polls["vid1"] = outer.polls.get("vid1", 0) + 1
                    return self._send(200, {"id": "vid1", "status": "in_progress" if n < 2 else "completed", "progress": 50})
                if p == "/v1/videos/vid1/content":
                    return self._send(200, MP4, "video/mp4")
                if p == "/v1beta/operations/op1":
                    n = outer.polls["op1"] = outer.polls.get("op1", 0) + 1
                    if n < 2:
                        return self._send(200, {"name": "operations/op1", "done": False})
                    return self._send(200, {"name": "operations/op1", "done": True, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": f"{base}/files/v.mp4"}}]}}})
                if p == "/sdapi/v1/sd-models":
                    return self._send(200, [{"title": "sd15.safetensors", "model_name": "sd15"}])
                if p == "/v1beta/models":
                    return self._send(200, {"models": [{"name": "models/gemini-2.5-flash-image"}, {"name": "models/veo-3.0-fast-generate-001"}]})
                self._send(404, {"error": f"nope {p}"})

            def do_POST(self):
                rec = self._rec("POST")
                p = self.path.split("?")[0]
                base = f"http://127.0.0.1:{outer.port}"
                if outer.fail_next:
                    st = outer.fail_next.pop(0)
                    return self._send(st, {"error": {"message": f"falha simulada {st}"}})
                b = rec["body"] or {}
                if p == "/v1/images/generations":
                    n = int(b.get("n", 1))
                    if b.get("prompt", "").startswith("FILE-URL"):
                        return self._send(200, {"data": [{"url": "file:///etc/hostname"}]})
                    if b.get("prompt", "").startswith("JSON-OK"):
                        return self._send(200, {"data": [{"url": f"{base}/files/a.png"}]})
                    return self._send(200, {"data": [{"b64_json": b64(proc.image(b.get("prompt", "") + str(i), "64x64", i))} for i in range(n)]})
                if p == "/v1/images/edits":
                    return self._send(200, {"data": [{"b64_json": b64(PNG)}]})
                if p == "/v1/audio/speech":
                    if b.get("input", "").startswith("ERRO"):
                        return self._send(200, {"error": {"message": "voz indisponível"}})
                    return self._send(200, MP3, "audio/mpeg")
                if p == "/v1/audio/transcriptions":
                    return self._send(200, {"text": "olá mundo transcrito"})
                if p == "/v1/videos":
                    return self._send(200, {"id": "vid1", "status": "queued"})
                if p.startswith("/v1/text-to-speech/"):
                    return self._send(200, MP3, "audio/mpeg")
                if p == "/v1/sound-generation" or p == "/v1/music":
                    return self._send(200, MP3, "audio/mpeg")
                if p == "/v1/speech-to-text":
                    return self._send(200, {"text": "transcrição elevenlabs", "language_code": "pt"})
                if p == "/v1/models/black-forest-labs/flux-schnell/predictions":
                    return self._send(200, {"id": "p1", "status": "processing", "urls": {"get": f"{base}/v1/predictions/p1", "cancel": f"{base}/v1/predictions/p1/cancel"}})
                if p == "/v1/models/owner/community/predictions":
                    return self._send(404, {"detail": "The requested resource could not be found."})
                if p == "/v1/predictions":
                    return self._send(200, {"id": "p1", "status": "processing", "urls": {"get": f"{base}/v1/predictions/p1"}})
                if p.startswith("/v2beta/stable-image/generate/"):
                    return self._send(200, PNG, "image/png")
                if p.startswith("/hf-inference/models/openai/whisper"):
                    return self._send(200, {"text": "texto do whisper hf"})
                if p.startswith("/hf-inference/models/"):
                    return self._send(200, PNG, "image/png")
                if p == "/sdapi/v1/txt2img" or p == "/sdapi/v1/img2img":
                    return self._send(200, {"images": [b64(PNG), b64(PNG)]})
                if p.endswith(":generateContent"):
                    if "imageConfig" in json.dumps(b) and "NOIMAGECONFIG" in json.dumps(b):
                        return self._send(400, {"error": {"message": "Unknown name \"imageConfig\""}})
                    return self._send(200, {"candidates": [{"content": {"parts": [{"text": "ok"}, {"inlineData": {"mimeType": "image/png", "data": b64(PNG)}}]}}]})
                if p.endswith(":predictLongRunning"):
                    return self._send(200, {"name": "operations/op1"})
                self._send(404, {"error": f"nope {p}"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def last(self, path_part, method="POST"):
        return next(r for r in reversed(self.requests) if path_part in r["path"] and r["method"] == method)


def provider(kind, base, models=None, key="k", **cfg):
    return M._KINDS[kind]({"id": kind, "label": kind, "base_url": base, "api_key": key, "needs_key": bool(key), "models": models or {}, "poll_seconds": 0.02, **cfg})


# --------------------------------------------------------------------------- esquema


class SchemaTests(unittest.TestCase):
    def test_edges_are_validated(self):
        nodes = [S.normalize_node(n) for n in (node("text", nid="t1"), node("text", nid="t2"), node("image", nid="i1"), node("video", nid="v1"), node("sound", nid="s1"),
                                              node("editor", nid="e1"), node("upload", nid="u1"), node("style_prompt", nid="sp"))]
        edges = S.normalize_edges([
            edge("t1", "i1", "prompt"), edge("t1", "i1", "prompt"),  # duplicada
            edge("t2", "i1", "prompt"),  # porta múltipla: aceita
            edge("i1", "v1", "image"), edge("t1", "v1", "image"),  # texto numa porta de imagem: recusado
            edge("s1", "i1", "refs"),  # áudio em porta de imagem/mídia: recusado
            edge("u1", "i1", "refs"),  # "mídia" genérica entra em porta de imagem
            edge("v1", "i1", "refs"),  # vídeo não é imagem nem mídia? ("media" aceita vídeo)
            edge("sp", "i1", "style"), edge("i1", "i1", "prompt"),  # laço
            edge("v1", "t1", "prompt"), edge("zz", "i1", "prompt"), edge("t1", "i1", "inexistente"),
            edge("i1", "e1", "clips"), edge("v1", "e1", "clips"), edge("s1", "e1", "clips"),
        ], nodes)
        keys = {(e["from"], e["to"], e["port"]) for e in edges}
        self.assertEqual(len(keys), len(edges))
        self.assertIn(("t1", "i1", "prompt"), keys)
        self.assertIn(("t2", "i1", "prompt"), keys)
        self.assertIn(("i1", "v1", "image"), keys)
        self.assertNotIn(("t1", "v1", "image"), keys)
        self.assertNotIn(("s1", "i1", "refs"), keys)
        self.assertIn(("u1", "i1", "refs"), keys)
        self.assertIn(("sp", "i1", "style"), keys)
        self.assertNotIn(("i1", "i1", "prompt"), keys)
        self.assertEqual([k for k in keys if k[0] == "zz" or k[2] == "inexistente"], [])
        self.assertTrue({("i1", "e1", "clips"), ("v1", "e1", "clips"), ("s1", "e1", "clips")} <= keys)

    def test_cycles_and_single_ports(self):
        nodes = [S.normalize_node(n) for n in (node("llm", nid="a"), node("llm", nid="b"), node("text", nid="t"), node("text", nid="t2"), node("video", nid="v"), node("image", nid="i"), node("image", nid="i2"))]
        e = S.normalize_edges([edge("a", "b", "prompt"), edge("b", "a", "prompt")], nodes)
        self.assertEqual(len(e), 1)  # fecharia um ciclo
        e = S.normalize_edges([edge("i", "v", "image"), edge("i2", "v", "image")], nodes)
        self.assertEqual([(x["from"], x["to"]) for x in e], [("i", "v")])  # porta simples: mantém a primeira

    def test_params_are_clamped_and_cleaned(self):
        n = S.normalize_node(node("image", prompt="x" * 9000, size="9x9", count=99, seed=-4, mode="zzz", extra={"a": 1}, provider="  openai ", ignore_global_styles=1))
        p = n["params"]
        self.assertEqual((len(p["prompt"]), p["size"], p["count"], p["seed"], p["mode"], p["provider"]), (6000, "1024x1024", 4, 0, "generate", "openai"))
        self.assertTrue(p["ignore_global_styles"])
        self.assertIsNone(S.normalize_node({"type": "nao_existe"}))
        self.assertTrue(S.normalize_node(node("style_prompt"))["params"]["global"])
        self.assertFalse(S.normalize_node(node("style_folder", **{"global": False}))["params"]["global"])
        v = S.normalize_node(node("video", duration=999, aspect="3:7"))["params"]
        self.assertEqual((v["duration"], v["aspect"]), (30, "16:9"))

    def test_timeline_normalization(self):
        tl = S.normalize_timeline({"tracks": [{"id": "v1", "kind": "video"}, {"id": "v1", "kind": "audio"}, {"id": "tx", "kind": "text"}],
                                   "clips": [{"track": "v1", "asset": "a", "start": -5, "dur": 0, "volume": 9}, {"track": "nope", "asset": "a"}, {"track": "v1"},
                                             {"track": "tx", "text": "Oi", "dur": 2, "color": "red", "pos": "x"}, {"track": "v1", "node": "n1", "idx": 2}]})
        self.assertEqual([t["id"] for t in tl["tracks"]], ["v1", "tx"])
        c = tl["clips"]
        self.assertEqual(len(c), 3)  # sem arquivo/nó e trilha inexistente caem
        self.assertEqual((c[0]["start"], c[0]["dur"], c[0]["volume"]), (0, 0.1, 2))
        self.assertEqual((c[1]["text"], c[1]["color"], c[1]["pos"]), ("Oi", "#ffffff", "bottom"))
        self.assertEqual((c[2]["node"], c[2]["idx"]), ("n1", 2))
        self.assertEqual(S.normalize_timeline({})["tracks"][0]["kind"], "video")  # padrão: V1 + A1

    def test_every_template_builds_a_valid_connected_canvas(self):
        for t in S.TEMPLATES:
            base = S.build_template(t["id"], "um teste")
            c = S.normalize_canvas({"name": "x", "nodes": base["nodes"], "edges": base["edges"]}, keep_id="cv_x")
            self.assertEqual(len(c["nodes"]), len(base["nodes"]), t["id"])
            self.assertEqual(len(c["edges"]), len(base["edges"]), t["id"])  # nenhuma conexão do modelo é descartada
        scene = S.build_template("scene")
        self.assertIn("editor", [n["type"] for n in scene["nodes"]])
        self.assertIn("style_prompt", [n["type"] for n in scene["nodes"]])

    def test_mandatory_node_types_exist(self):
        for t in ("editor", "style_prompt", "style_folder", "image", "video", "sound", "voice", "text", "llm", "upload", "transcribe"):
            self.assertIn(t, S.NODE_TYPES)
        self.assertEqual(S.NODE_TYPES["style_prompt"]["out"], "style")
        self.assertEqual(S.NODE_TYPES["style_folder"]["out"], "style")


# --------------------------------------------------------------------------- armazenamento


class StoreTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.cs = ProjectStore(self.tmp / "canvases")

    def test_create_list_duplicate_delete_and_ids(self):
        c = self.cs.create("Meu canvas", "image_video", "um robô")
        self.assertTrue(c["id"].startswith("pj_"))
        self.assertEqual(len(c["nodes"]), 3)
        self.assertEqual([x["id"] for x in self.cs.list()], [c["id"]])
        d = self.cs.duplicate(c["id"])
        self.assertNotEqual(d["id"], c["id"])
        self.assertEqual(len(self.cs.list()), 2)
        self.assertTrue(self.cs.delete(d["id"]))
        self.assertFalse(self.cs.delete("../../etc"))
        self.assertIsNone(self.cs.get("../x"))
        self.assertIsNone(self.cs.get("nao_existe"))

    def test_assets_dimensions_thumb_and_path_safety(self):
        c = self.cs.create("a")
        a = self.cs.add_asset(c["id"], PNG, "png", "image", name="img.png", mime="image/png", node="n1")
        self.assertEqual((a["w"], a["h"], a["kind"]), (64, 64, "image"))
        self.assertTrue(self.cs.asset_path(c["id"], a["file"]).is_file())
        for bad in ("../project.json", "..", "a/b", "", ".hidden", "x\\y"):
            self.assertIsNone(self.cs.asset_path(c["id"], bad), bad)
        self.assertIsNone(self.cs.add_asset(c["id"], b"x", "png", "texto"))  # tipo inválido não deixa arquivo órfão
        self.assertEqual(len(list((self.cs.asset_dir(c["id"])).iterdir())), 1)
        self.assertIn(a["file"], self.cs.summary(self.cs.get(c["id"]))["thumb"])
        self.assertEqual(self.cs.add_asset(c["id"], b"x" * 10, "../../evil", "audio")["file"].split(".")[-1], "evil"[:5])  # extensão sanitizada
        self.assertEqual(len(list((self.cs.asset_dir(c["id"])).glob("*"))), 2)

    def test_save_layout_keeps_server_owned_results_and_assets(self):
        c = self.cs.create("a", "text_image")
        im = next(n for n in c["nodes"] if n["type"] == "image")
        a = self.cs.add_asset(c["id"], PNG, "png", "image", node=im["id"])
        self.cs.set_node_result(c["id"], im["id"], {"state": "done", "assets": [a["id"]], "hash": "h1"})
        # o navegador salva o layout com resultados antigos/vazios e ativos inventados: nada disso vale
        body = {"name": "Renomeado", "nodes": [{**n, "x": n["x"] + 50, "result": {"state": "idle", "assets": ["fake"]}} for n in c["nodes"]], "edges": c["edges"],
                "assets": [{"id": "fake", "kind": "image", "file": "fake.png"}], "viewport": {"x": 5, "y": 6, "zoom": 1.5}}
        saved = self.cs.save_layout(c["id"], body)
        n2 = next(n for n in saved["nodes"] if n["id"] == im["id"])
        self.assertEqual((n2["result"]["state"], n2["result"]["assets"], n2["result"]["hash"]), ("done", [a["id"]], "h1"))
        self.assertEqual([x["id"] for x in saved["assets"]], [a["id"]])
        self.assertEqual((saved["name"], saved["viewport"]["zoom"], n2["x"], len(saved["edges"])), ("Renomeado", 1.5, im["x"] + 50, 1))

    def test_delete_asset_cleans_nodes_and_clips(self):
        c = self.cs.create("a")
        a = self.cs.add_asset(c["id"], PNG, "png", "image")
        b = self.cs.add_asset(c["id"], WAV, "wav", "audio")
        up = node("upload", nid="up", files=[a["id"], b["id"]])
        ed = node("editor", nid="ed", timeline={"tracks": [{"id": "v", "kind": "video"}], "clips": [{"track": "v", "asset": a["id"]}, {"track": "v", "asset": b["id"]}, {"track": "v", "node": "up"}]})
        self.cs.save_layout(c["id"], {"nodes": [up, ed], "edges": [], "assets": []})
        self.assertTrue(self.cs.delete_asset(c["id"], a["id"]))
        cur = self.cs.get(c["id"])
        self.assertEqual(next(n for n in cur["nodes"] if n["id"] == "up")["params"]["files"], [b["id"]])
        clips = next(n for n in cur["nodes"] if n["id"] == "ed")["params"]["timeline"]["clips"]
        self.assertEqual(sorted((c_["asset"], c_["node"]) for c_ in clips), [("", "up"), (b["id"], "")])
        self.assertIsNone(self.cs.asset_path(c["id"], a["file"]))
        self.assertFalse(self.cs.delete_asset(c["id"], "as_nao"))

    def test_history_pruning_keeps_referenced_assets(self):
        c = self.cs.create("a")
        self.cs.save_layout(c["id"], {"nodes": [node("image", nid="i")], "edges": []})
        ids = [self.cs.add_asset(c["id"], PNG + bytes([i]), "png", "image", node="i")["id"] for i in range(6)]
        self.cs.set_node_result(c["id"], "i", {"state": "done", "assets": [ids[0]]})  # o mais antigo está em uso
        removed = self.cs.prune_node_assets(c["id"], "i", keep=2)
        left = [a["id"] for a in self.cs.get(c["id"])["assets"]]
        self.assertEqual(removed, 3)
        self.assertEqual(sorted(left), sorted([ids[0], ids[4], ids[5]]))

    def test_reset_running(self):
        c = self.cs.create("a", "text_image")
        im = next(n for n in c["nodes"] if n["type"] == "image")
        self.cs.set_node_result(c["id"], im["id"], {"state": "running"})
        self.assertTrue(self.cs.reset_running(c["id"]))
        self.assertEqual(next(n for n in self.cs.get(c["id"])["nodes"] if n["id"] == im["id"])["result"]["state"], "idle")


# --------------------------------------------------------------------------- geradores procedurais


class ProceduralTests(unittest.TestCase):
    def test_images_are_valid_deterministic_and_prompt_driven(self):
        a = proc.image("floresta ao amanhecer", "128x96", 1)
        self.assertEqual(a[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(a, proc.image("floresta ao amanhecer", "128x96", 1))
        self.assertNotEqual(a, proc.image("floresta ao amanhecer", "128x96", 2))
        self.assertNotEqual(a, proc.image("cidade neon à noite", "128x96", 1))
        from openflow import attachments as att

        self.assertEqual(att.image_size(a), (128, 96))
        self.assertEqual(proc.parse_size("4000x2000", 1024), (1024, 512))
        self.assertEqual(proc.parse_size("lixo", 1024), (768, 768))

    def test_audio_is_valid_wav(self):
        for data in (proc.sound_fx("chuva forte", 1.5, 1), proc.sound_fx("explosão", 1.0, 1), proc.music("calma", 3, 1), proc.babble("olá, tudo bem?", 1.0, 1)):
            import io

            with wave.open(io.BytesIO(data)) as w:
                self.assertGreater(w.getnframes(), 1000)
                self.assertEqual(w.getsampwidth(), 2)
        self.assertNotEqual(proc.sound_fx("chuva", 1, 1), proc.sound_fx("trovão", 1, 1))

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg não instalado")
    def test_video_from_image(self):
        v = proc.video_from_image(PNG, 1, (64, 64), 12, 1)
        self.assertEqual(M.sniff_mime(v), "video/mp4")

    def test_demo_llm_and_sniffing(self):
        out = proc.demo_llm("detalhe", "um gato", "aquarela")
        self.assertIn("um gato", out)
        self.assertIn("aquarela", out)
        self.assertEqual(M.sniff_mime(PNG), "image/png")
        self.assertEqual(M.sniff_mime(WAV), "audio/wav")
        self.assertEqual(M.sniff_mime(MP3), "audio/mpeg")
        self.assertEqual(M.sniff_mime(MP4), "video/mp4")
        self.assertEqual(M.sniff_mime(b"hello"), "")


# --------------------------------------------------------------------------- adaptadores de provedores


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = MediaMock()
        cls.mock.__enter__()
        cls.old_delay = M.RETRY_DELAY
        M.RETRY_DELAY = 0.01

    @classmethod
    def tearDownClass(cls):
        cls.mock.__exit__()
        M.RETRY_DELAY = cls.old_delay

    def setUp(self):
        self.mock.requests.clear()
        self.mock.polls.clear()
        self.mock.fail_next.clear()

    def test_openai_image_generation_edit_and_url_response(self):
        p = provider("openai", self.mock.url + "/v1", {"image": "gpt-image-1"})
        out = p.image("um gato", size="1280x720", count=2, negative="borrado")
        self.assertEqual([m.mime for m in out], ["image/png", "image/png"])
        body = self.mock.last("/images/generations")["body"]
        self.assertEqual((body["model"], body["n"], body["size"]), ("gpt-image-1", 2, "1536x1024"))
        self.assertNotIn("response_format", body)  # gpt-image-1 não aceita
        self.assertIn("Evite: borrado", body["prompt"])
        self.assertEqual(self.mock.last("/images/generations")["h"]["authorization"], "Bearer k")
        # dall-e-3: uma chamada por imagem, b64_json explícito
        self.mock.requests.clear()
        p.image("x", size="1024x1024", count=2, model="dall-e-3")
        calls = [r for r in self.mock.requests if "generations" in r["path"]]
        self.assertEqual(len(calls), 2)
        self.assertEqual((calls[0]["body"]["response_format"], calls[0]["body"]["n"], calls[0]["body"]["size"]), ("b64_json", 1, "1024x1024"))
        # imagem de referência → /images/edits em multipart
        p.image("edite", refs=[(PNG, "image/png"), (PNG, "image/png")], size="1024x1024")
        ed = self.mock.last("/images/edits")
        self.assertIn("multipart/form-data", ed["h"]["content-type"])
        self.assertEqual(ed["raw"].count(b'name="image[]"'), 2)
        self.assertIn(b'name="prompt"', ed["raw"])
        # resposta com URL em vez de base64 (servidores compatíveis)
        self.assertEqual(len(p.image("JSON-OK", model="x")), 1)

    def test_urls_returned_by_a_provider_must_be_http(self):
        p = provider("openai", self.mock.url + "/v1", {"image": "x"})
        with self.assertRaises(ProviderError) as cm:
            p.image("FILE-URL")
        self.assertIn("inválido", str(cm.exception))

    def test_openai_voice_stt_models_and_errors(self):
        p = provider("openai", self.mock.url + "/v1", {"voice": "tts-1", "stt": "whisper-1"})
        v = p.voice("Olá!", voice="nova", speed=1.5)
        self.assertEqual((v.kind, v.ext), ("audio", "mp3"))
        body = self.mock.last("/audio/speech")["body"]
        self.assertEqual((body["voice"], body["speed"], body["model"], body["response_format"]), ("nova", 1.5, "tts-1", "mp3"))
        self.assertNotIn("instructions", body)
        p.voice("Oi", model="gpt-4o-mini-tts", instructions="fale calmamente")
        self.assertEqual(self.mock.last("/audio/speech")["body"]["instructions"], "fale calmamente")
        self.assertEqual(p.transcribe(WAV, "a.wav", "audio/wav", language="pt-BR"), "olá mundo transcrito")
        raw = self.mock.last("/audio/transcriptions")["raw"]
        self.assertIn(b'name="language"\r\n\r\npt', raw)
        self.assertIn(b"gpt-image-1", "".join(p.list_models("image")).encode())
        self.assertTrue(p.test().startswith("conectado"))
        with self.assertRaises(ProviderError) as cm:  # 200 com JSON de erro não vira "áudio"
            p.voice("ERRO aqui")
        self.assertIn("voz indisponível", str(cm.exception))
        with self.assertRaises(ProviderError) as cm:
            provider("openai", self.mock.url + "/v1", key="", needs_key=True).voice("x")
        self.assertIn("chave", str(cm.exception))

    def test_retry_on_rate_limit_but_not_on_auth_errors(self):
        p = provider("openai", self.mock.url + "/v1")
        self.mock.fail_next += [429, 503]
        self.assertEqual(len(p.image("x", model="gpt-image-1")), 1)
        self.assertEqual(len([r for r in self.mock.requests if r["method"] == "POST"]), 3)
        self.mock.requests.clear()
        self.mock.fail_next += [401]
        with self.assertRaises(ProviderError) as cm:
            p.image("x", model="gpt-image-1")
        self.assertEqual(cm.exception.status, 401)
        self.assertEqual(len([r for r in self.mock.requests if r["method"] == "POST"]), 1)

    def test_openai_video_job_polling(self):
        p = provider("openai", self.mock.url + "/v1")
        out = p.video("um drone sobre o mar", duration=5, aspect="9:16", image=(PNG, "image/png"))
        self.assertEqual(out.kind, "video")
        raw = self.mock.last("/v1/videos")["raw"]
        for needle in (b'name="seconds"\r\n\r\n4', b'name="size"\r\n\r\n720x1280', b'name="input_reference"', b"sora-2"):
            self.assertIn(needle, raw)
        self.assertGreaterEqual(self.mock.polls["vid1"], 2)

    def test_elevenlabs_voice_by_name_sound_music_and_stt(self):
        p = provider("elevenlabs", self.mock.url + "/v1")
        v = p.voice("Olá", voice="Rachel", speed=3)
        self.assertEqual(v.kind, "audio")
        rec = self.mock.last("/text-to-speech/")
        self.assertIn("/text-to-speech/abc123abc123abc123ab", rec["path"])
        self.assertEqual(rec["h"]["xi-api-key"], "k")
        self.assertEqual(rec["body"]["voice_settings"]["speed"], 1.2)  # limitado ao máximo da API
        with self.assertRaises(ProviderError) as cm:
            p.voice("x", voice="Inexistente")
        self.assertIn("Rachel", str(cm.exception))
        p.sound("trovão", kind="sfx", duration=99)
        self.assertEqual(self.mock.last("/sound-generation")["body"]["duration_seconds"], 22.0)
        p.sound("calma", kind="music", duration=20)
        self.assertEqual(self.mock.last("/v1/music")["body"]["music_length_ms"], 20000)
        self.assertEqual(p.transcribe(WAV, "a.wav", "audio/wav"), "transcrição elevenlabs")
        self.assertEqual(p.list_models("voice"), ["Rachel", "Antônio"])
        with self.assertRaises(ProviderError):
            p.image("x")  # capacidade que o provedor não tem

    def test_replicate_filters_inputs_by_schema_and_polls(self):
        p = provider("replicate", self.mock.url + "/v1", {"image": "black-forest-labs/flux-schnell"})
        out = p.image("um farol", size="1280x720", count=2, seed=7, negative="x")
        self.assertEqual(len(out), 1)  # o mock devolve um arquivo
        post = self.mock.last("flux-schnell/predictions")
        inp = post["body"]["input"]
        self.assertEqual((inp["prompt"], inp["aspect_ratio"], inp["num_outputs"], inp["seed"]), ("um farol", "16:9", 2, 7))
        for dropped in ("width", "height", "output_format", "negative_prompt"):  # o modelo não aceita: não é enviado
            self.assertNotIn(dropped, inp)
        self.assertEqual(post["h"]["prefer"], "wait=45")
        self.assertGreaterEqual(self.mock.polls["p1"], 2)
        # modelo da comunidade: 404 no endpoint de modelos → usa a versão mais recente
        self.mock.polls.clear()
        p.image("x", model="owner/community")
        self.assertEqual(self.mock.last("/v1/predictions")["body"]["version"], "ver999")
        with self.assertRaises(ProviderError) as cm:
            provider("replicate", self.mock.url + "/v1").image("x")
        self.assertIn("modelo", str(cm.exception).lower())
        self.assertIn("tester", p.test())

    def test_stability_a1111_huggingface_google(self):
        s = provider("stability", self.mock.url, {"image": "ultra"})
        self.assertEqual(s.image("x", size="1280x720")[0].mime, "image/png")
        rec = self.mock.last("/generate/ultra")
        self.assertEqual((rec["h"]["authorization"], rec["h"]["accept"]), ("Bearer k", "image/*"))
        self.assertIn(b'name="aspect_ratio"\r\n\r\n16:9', rec["raw"])
        self.assertTrue(len(provider("stability", self.mock.url, {"image": "sd3.5-large"}).image("x", refs=[(PNG, "image/png")])) == 1)
        self.assertIn(b"image-to-image", self.mock.last("/generate/sd3")["raw"])

        a = provider("a1111", self.mock.url, key="", needs_key=False)
        out = a.image("x", size="512x512", count=2, seed=5, negative="feio", model="sd15.safetensors")
        self.assertEqual(len(out), 2)
        body = self.mock.last("txt2img")["body"]
        self.assertEqual((body["width"], body["seed"], body["negative_prompt"], body["override_settings"]["sd_model_checkpoint"]), (512, 5, "feio", "sd15.safetensors"))
        a.image("x", refs=[(PNG, "image/png")])
        self.assertTrue(self.mock.last("img2img")["body"]["init_images"])
        self.assertEqual(a.list_models("image"), ["sd15.safetensors"])

        h = provider("huggingface", self.mock.url + "/hf-inference/models", {"image": "black-forest-labs/FLUX.1-schnell", "stt": "openai/whisper-large-v3"})
        self.assertEqual(h.image("x", count=2)[0].kind, "image")
        self.assertEqual(self.mock.last("FLUX.1-schnell")["body"]["parameters"]["width"], 1024)
        self.assertEqual(h.transcribe(WAV, "a.wav", "audio/wav"), "texto do whisper hf")
        self.assertEqual(self.mock.last("whisper")["raw"][:4], b"RIFF")  # corpo bruto, não multipart
        with self.assertRaises(ProviderError):
            provider("huggingface", self.mock.url + "/hf-inference/models").image("x")  # sem modelo

        g = provider("google", self.mock.url + "/v1beta", {"image": "gemini-2.5-flash-image", "video": "veo-3.0-fast-generate-001"})
        self.assertEqual(g.image("x", size="720x1280", refs=[(PNG, "image/png")])[0].mime, "image/png")
        rec = self.mock.last(":generateContent")
        self.assertEqual(rec["h"]["x-goog-api-key"], "k")
        self.assertEqual(rec["body"]["generationConfig"]["imageConfig"]["aspectRatio"], "9:16")
        self.assertEqual(len(rec["body"]["contents"][0]["parts"]), 2)
        self.mock.requests.clear()
        g.image("NOIMAGECONFIG")  # o modelo recusa imageConfig (400): tenta de novo sem ele
        gens = [r for r in self.mock.requests if r["path"].endswith(":generateContent")]
        self.assertEqual(len(gens), 2)
        self.assertNotIn("imageConfig", gens[1]["body"]["generationConfig"])
        vid = g.video("x", duration=5, aspect="16:9")
        self.assertEqual(vid.kind, "video")
        self.assertEqual(self.mock.last(":predictLongRunning")["body"]["parameters"]["durationSeconds"], 4)  # 5 s → valor aceito mais próximo (empate: o menor)
        self.assertIn("veo", " ".join(g.list_models("video")))

    def test_registry_resolution_and_secrets(self):
        settings = {"media": {"active": {"image": "openai"}, "models": {"openai": {"image": "dall-e-3"}}, "urls": {"a1111": "http://x:1"}}, "providers": {"openai": {"api_key": "sk-1"}}, "hf": {"token": "hf_1"}}
        self.assertEqual(M.pick_provider(settings, "image"), "openai")
        self.assertEqual(M.pick_provider(settings, "sound"), "demo")
        self.assertEqual(M.pick_provider(settings, "image", "a1111"), "a1111")
        for bad in (("video", "a1111"), ("image", "elevenlabs"), ("image", "nada")):
            with self.assertRaises(ProviderError):
                M.pick_provider(settings, bad[0], bad[1])
        cfg = M.media_config(settings, "openai")
        self.assertEqual((cfg["api_key"], cfg["models"]["image"], cfg["models"]["voice"]), ("sk-1", "dall-e-3", "tts-1"))
        self.assertEqual(M.media_config(settings, "a1111")["base_url"], "http://x:1")
        self.assertEqual(M.media_config(settings, "huggingface")["api_key"], "hf_1")  # reaproveita o token do Hugging Face
        desc = {d["id"]: d for d in M.describe_media_presets(settings)}
        self.assertTrue(desc["openai"]["has_key"])
        self.assertFalse(desc["elevenlabs"]["has_key"])
        self.assertNotIn("api_key", json.dumps(desc))
        self.assertNotIn("sk-1", json.dumps(desc))
        self.assertTrue({"demo", "openai", "elevenlabs", "replicate", "huggingface", "local_hf", "a1111", "stability", "google"} <= set(desc))

    def test_expect_media_rejects_html_and_wrong_types(self):
        with self.assertRaises(ProviderError):
            M.expect_media(b"<html>erro</html>", "text/html", "image")
        with self.assertRaises(ProviderError):
            M.expect_media(PNG, "image/png", "audio")
        self.assertEqual(M.expect_media(PNG, "application/octet-stream", "image").mime, "image/png")
        self.assertEqual(M.size_of_aspect("9:16", 1280), (720, 1280))
        self.assertEqual(M.aspect_of("1280x720"), "16:9")


class FakeHub:
    """Imita o `huggingface_hub` (lista de arquivos, download arquivo a arquivo e cache em disco)."""

    FILES = {"model_index.json": 1, "README.md": 9, "sd_turbo.safetensors": 5000, "unet/config.json": 2, "unet/diffusion_pytorch_model.safetensors": 3400, "unet/diffusion_pytorch_model.fp16.safetensors": 1700,
             "unet/diffusion_pytorch_model.bin": 3400, "vae/config.json": 2, "vae/diffusion_pytorch_model.safetensors": 330, "vae/diffusion_pytorch_model.fp16.safetensors": 165,
             "text_encoder/model.safetensors": 1400, "text_encoder/model.fp16.safetensors": 700, "tokenizer/vocab.json": 3}

    def __init__(self, root):
        self.root, self.downloaded, self.calls = Path(root), [], 0
        outer = self

        class Api:
            def model_info(self, model, files_metadata=False, token=None):
                return mock.Mock(siblings=[mock.Mock(rfilename=n, size=sz) for n, sz in outer.FILES.items()])

        def snapshot_download(model, local_files_only=False, **kw):
            snap = outer.root / ("models--" + model.replace("/", "--")) / "snapshots" / "abc"
            if not snap.exists():
                raise FileNotFoundError("não está no cache")
            return str(snap)

        def hf_hub_download(model, filename, token=None, **kw):
            outer.downloaded.append(filename)
            path = outer.root / ("models--" + model.replace("/", "--")) / "snapshots" / "abc" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
            return str(path)

        self.module = mock.MagicMock(HfApi=Api, snapshot_download=snapshot_download, hf_hub_download=hf_hub_download)
        self.module.constants.HF_HUB_CACHE = str(self.root)


class LocalModelPrecisionTests(TmpCase):
    def test_files_are_chosen_per_precision_without_duplicated_weights(self):
        from openflow.canvas import localmodels as lm

        files = [{"name": n, "size": sz} for n, sz in FakeHub.FILES.items()]
        fp32 = {f["name"] for f in lm.select_files(files, "fp32")}
        fp16 = {f["name"] for f in lm.select_files(files, "fp16")}
        self.assertIn("unet/diffusion_pytorch_model.safetensors", fp32)
        self.assertNotIn("unet/diffusion_pytorch_model.fp16.safetensors", fp32)
        self.assertIn("unet/diffusion_pytorch_model.fp16.safetensors", fp16)
        self.assertNotIn("unet/diffusion_pytorch_model.safetensors", fp16)
        for never in ("sd_turbo.safetensors", "unet/diffusion_pytorch_model.bin", "README.md"):  # checkpoint duplicado na raiz, formato .bin, documentação
            self.assertNotIn(never, fp32 | fp16)
        self.assertTrue({"model_index.json", "unet/config.json", "tokenizer/vocab.json"} <= fp16 & fp32)
        self.assertEqual(lm.select_files(files, "bf16"), lm.select_files(files, "fp16"))  # bf16 usa os mesmos arquivos do fp16

    def test_options_show_the_download_size_of_each_precision(self):
        from openflow.canvas import localmodels as lm

        with mock.patch.dict(sys.modules, {"huggingface_hub": FakeHub(self.tmp).module}):
            on_gpu = lm.options("stabilityai/sd-turbo", "", True)
            on_cpu = lm.options("stabilityai/sd-turbo", "", False)
        sizes = {o["id"]: o["size"] for o in on_gpu["options"]}
        self.assertEqual((sizes["fp32"], sizes["fp16"], sizes["bf16"]), (3400 + 330 + 1400 + 8, 1700 + 165 + 700 + 8, 1700 + 165 + 700 + 8))
        self.assertLess(sizes["fp16"], sizes["fp32"])
        self.assertEqual((on_gpu["recommended"], on_cpu["recommended"]), ("fp16", "fp32"))
        self.assertEqual(sum(o["recommended"] for o in on_gpu["options"]), 1)

    def test_download_requires_a_choice_and_records_it(self):
        from openflow.canvas import localmodels as lm

        hub = FakeHub(self.tmp)
        with mock.patch.dict(sys.modules, {"huggingface_hub": hub.module}):
            with self.assertRaises(ProviderError):
                lm.download("stabilityai/sd-turbo", "")
            self.assertEqual(hub.downloaded, [])  # sem escolha, nada é baixado
            self.assertEqual(lm.downloaded_precision("stabilityai/sd-turbo"), "")
            seen = []
            lm.download("stabilityai/sd-turbo", "fp16", "", lambda d, t: seen.append((d, t)))
            from openflow.canvas import localmodels as lm2

            self.assertEqual(sorted(hub.downloaded), sorted(f["name"] for f in lm2.select_files([{"name": n, "size": z} for n, z in FakeHub.FILES.items()], "fp16")))
            self.assertNotIn("unet/diffusion_pytorch_model.safetensors", hub.downloaded)
            self.assertEqual(lm.downloaded_precision("stabilityai/sd-turbo"), "fp16")
            self.assertTrue(lm.has_fp16_variant("stabilityai/sd-turbo"))
            self.assertEqual(seen[-1][0], seen[-1][1])
            with self.assertRaises(ProviderError) as cm:
                lm.download("outro/modelo", "fp32", "", None, lambda: True)  # cancelado antes do 1º arquivo
            self.assertIn("cancelado", str(cm.exception))


class GGUFMediaTests(TmpCase):
    """Modelos GGUF de imagem/vídeo pela stable-diffusion.cpp (aqui substituída por um módulo falso)."""

    def fake_sdcpp(self):
        loads, runs = [], []

        class Img:
            def save(self, buf, format="PNG"):
                buf.write(PNG)

        class SD:
            def __init__(self, **kw):
                loads.append(kw)

            def txt2img(self, **kw):
                runs.append(kw)
                return [Img()]

        return mock.MagicMock(StableDiffusion=SD), loads, runs

    def setUp(self):
        super().setUp()
        (self.tmp / "image").mkdir()
        (self.tmp / "image" / "flux-Q4_K_S.gguf").write_bytes(b"gguf")
        (self.tmp / "image" / "ae.safetensors").write_bytes(b"vae")
        M._LOCAL_CACHE.clear()

    def prov(self, **models):
        return M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": models, "needs_key": False})

    def test_image_from_a_quantized_gguf_file(self):
        mod, loads, runs = self.fake_sdcpp()
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}):
            out = self.prov(image="flux-Q4_K_S.gguf").image("um gato", size="1024x768", seed=5, negative="feio")
        self.assertEqual(out[0].mime, "image/png")
        self.assertEqual(loads[0], {"model_path": str(self.tmp / "image" / "flux-Q4_K_S.gguf")})
        self.assertEqual((runs[0]["width"], runs[0]["height"], runs[0]["seed"], runs[0]["negative_prompt"]), (1024, 768, 5, "feio"))

    def test_load_options_resolve_the_model_and_companion_files(self):
        mod, loads, runs = self.fake_sdcpp()
        extra = {"load": {"diffusion_model_path": "@model", "vae_path": "ae.safetensors", "keep_clip_on_cpu": True}, "sample_steps": 4}
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}):
            self.prov(image="flux-Q4_K_S.gguf").image("x", extra=extra)
        self.assertEqual(loads[0], {"diffusion_model_path": str(self.tmp / "image" / "flux-Q4_K_S.gguf"), "vae_path": str(self.tmp / "image" / "ae.safetensors"), "keep_clip_on_cpu": True})
        self.assertEqual(runs[0]["sample_steps"], 4)  # o que está fora de "load" vai para a geração

    def test_preinstalled_z_image_loads_with_its_vae_and_text_encoder_and_node_extra_wins(self):
        mod, loads, runs = self.fake_sdcpp()
        for n in ("z-image-Q4_K_M.gguf", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"):
            (self.tmp / "image" / n).write_bytes(b"g")
        img = self.tmp / "image"
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}):
            self.prov(image="z-image-Q4_K_M.gguf").image("x")
            M._LOCAL_CACHE.clear()
            self.prov(image="z-image-Q4_K_M.gguf").image("x", extra={"cfg_scale": 1.0, "load": {"vae_path": "ae.safetensors"}})
        self.assertEqual(loads[0], {"diffusion_model_path": str(img / "z-image-Q4_K_M.gguf"), "vae_path": str(img / "ae.safetensors"), "llm_path": str(img / "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")})
        self.assertEqual((runs[0]["cfg_scale"], runs[0]["sample_steps"]), (4.0, 30))
        self.assertEqual((runs[1]["cfg_scale"], runs[1]["sample_steps"]), (1.0, 30))  # o "extra" do nó sobrescreve só o que ele define

    def test_missing_model_or_library_or_video_support_explain_what_to_do(self):
        mod, _, _ = self.fake_sdcpp()
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}):
            for models, call, needle in ((dict(), lambda p: p.image("x"), "Escolha um modelo GGUF"), (dict(image="nao.gguf"), lambda p: p.image("x"), "não encontrado"),
                                         (dict(), lambda p: p.video("x"), "Escolha um modelo GGUF")):
                with self.assertRaises(ProviderError) as cm:
                    call(self.prov(**models))
                self.assertIn(needle, str(cm.exception))
            (self.tmp / "video").mkdir()
            (self.tmp / "video" / "wan-Q4_0.gguf").write_bytes(b"g")
            with self.assertRaises(ProviderError) as cm:
                self.prov(video="wan-Q4_0.gguf").video("x")  # esta versão da biblioteca não gera vídeo
            self.assertIn("não gera vídeo", str(cm.exception))
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": None}):
            with self.assertRaises(ProviderError) as cm:
                self.prov(image="flux-Q4_K_S.gguf").image("x")
            self.assertIn('pip install "openflow[local]"', str(cm.exception))

    def test_registry_lists_the_provider_for_image_and_video_only(self):
        d = {p["id"]: p for p in M.describe_media_presets({"media": {}})}
        self.assertEqual(d["gguf_local"]["caps"], ["image", "video"])
        self.assertEqual(M.pick_provider({"media": {}}, "image", "gguf_local"), "gguf_local")
        with self.assertRaises(ProviderError):
            M.pick_provider({"media": {}}, "voice", "gguf_local")


class LocalHFTests(unittest.TestCase):
    """Os modelos locais precisam de torch/diffusers: aqui eles são substituídos por módulos falsos só para exercitar o caminho de código."""

    def fake_modules(self):
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        torch.backends.mps = None
        torch.Generator.return_value.manual_seed.return_value = "gen"

        class Img:
            def save(self, buf, format="PNG"):
                buf.write(PNG)

        calls = {}

        class Pipe:
            def to(self, dev):
                calls["device"] = dev
                return self

            def __call__(self, **kw):
                calls["kw"] = kw
                return mock.Mock(images=[Img()])

        diffusers = mock.MagicMock()
        diffusers.AutoPipelineForText2Image.from_pretrained.side_effect = lambda model, **kw: (calls.setdefault("model", model), Pipe())[1]
        return {"torch": torch, "diffusers": diffusers}, calls

    def test_connected_image_makes_the_local_model_do_image_to_image(self):
        from openflow.canvas import localmodels as lm

        mods, calls = self.fake_modules()
        i2i_calls = {}

        class Img:
            def save(self, buf, format="PNG"):
                buf.write(PNG)

        class I2I:
            def __call__(self, **kw):
                i2i_calls["kw"] = kw
                return mock.Mock(images=[Img()])

        mods["diffusers"].AutoPipelineForImage2Image.from_pipe.side_effect = lambda pipe: I2I()
        with mock.patch.dict(sys.modules, mods), mock.patch.object(lm, "downloaded_precision", return_value="fp16"), mock.patch.object(lm, "has_fp16_variant", return_value=True):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": "stabilityai/sd-turbo"}, key="", needs_key=False)
            out = p.image("deixe azul", size="1024x1024", refs=[(PNG, "image/png")])
        self.assertEqual(out[0].mime, "image/png")
        kw = i2i_calls["kw"]
        self.assertIn("image", kw)
        self.assertNotIn("width", kw)
        self.assertTrue(0 < kw["strength"] < 1 and kw["num_inference_steps"] >= 2)
        self.assertNotIn("kw", calls)   # o texto→imagem não rodou

    def test_flux2_klein_loads_through_the_model_index_runs_distilled_and_edits_with_several_images(self):
        from openflow.canvas import localmodels as lm

        mods, calls = self.fake_modules()
        diffusers = mods["diffusers"]
        diffusers.AutoPipelineForText2Image.from_pretrained.side_effect = ValueError("Flux2KleinPipeline não está no AutoPipeline desta versão")   # versão do diffusers que ainda não mapeia o FLUX.2
        pipes = []

        class Pipe:
            def to(self, dev):
                return self

            def __call__(self, **kw):
                calls["kw"] = kw
                from tests.test_canvas import PNG as _P

                class Img:
                    def save(self, buf, format="PNG"):
                        buf.write(_P)

                return mock.Mock(images=[Img()])

        diffusers.DiffusionPipeline.from_pretrained.side_effect = lambda model, **kw: (pipes.append(model), Pipe())[1]
        refs = [(proc.image(f"r{i}", "64x64", i + 1), "image/png") for i in range(5)]
        with mock.patch.dict(sys.modules, mods), mock.patch.object(lm, "downloaded_precision", return_value="bf16"), mock.patch.object(lm, "has_fp16_variant", return_value=False):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": "black-forest-labs/FLUX.2-klein-4B"}, key="", needs_key=False)
            p.image("um gato", size="512x512", negative="feio")
            kw = dict(calls["kw"])
            self.assertEqual(pipes, ["black-forest-labs/FLUX.2-klein-4B"])            # o AutoPipeline não conhece: a classe vem do model_index.json
            self.assertEqual((kw["num_inference_steps"], kw["guidance_scale"]), (4, 1.0))   # destilado
            self.assertNotIn("negative_prompt", kw)                                    # o pipeline do FLUX não aceita prompt negativo
            self.assertNotIn("image", kw)
            p.image("junte os dois", size="512x512", refs=refs)
            kw = calls["kw"]
            self.assertEqual(len(kw["image"]), 4)                                      # edita com até 4 imagens de uma vez
            self.assertEqual(p.max_refs("black-forest-labs/FLUX.2-klein-4B"), 4)
            self.assertEqual(p.max_refs("stabilityai/sd-turbo"), 1)

    def test_a_new_pipeline_that_no_diffusers_version_loads_explains_how_to_update(self):
        from openflow.canvas import localmodels as lm

        mods, _ = self.fake_modules()
        mods["diffusers"].AutoPipelineForText2Image.from_pretrained.side_effect = ValueError("desconhecido")
        mods["diffusers"].DiffusionPipeline.from_pretrained.side_effect = ValueError("Flux2KleinPipeline")
        with mock.patch.dict(sys.modules, mods), mock.patch.object(lm, "downloaded_precision", return_value="bf16"), mock.patch.object(lm, "has_fp16_variant", return_value=False):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": "black-forest-labs/FLUX.2-klein-4B"}, key="", needs_key=False)
            with self.assertRaises(ProviderError) as cm:
                p.image("x")
        self.assertIn("pip install -U diffusers", str(cm.exception))

    def test_flux3_klein_loads_the_modular_pipeline_without_the_prompt_upsampler_and_offline(self):
        import types

        from openflow.canvas import localmodels as lm

        mods, calls = self.fake_modules()
        consts = types.SimpleNamespace(HF_HUB_OFFLINE=False)
        mods["huggingface_hub"] = types.SimpleNamespace(constants=consts)
        seen = {}

        class Out:
            def save(self, buf, format="PNG"):
                buf.write(PNG)

        class Blocks:
            sub_blocks = {"prompt_upsampler": object(), "denoise": object()}

            def init_pipeline(self, model):
                seen["init_with"] = (model, sorted(self.sub_blocks))
                return Mod()

        class Mod:
            blocks = Blocks()

            def load_components(self, dtype=None):
                seen["dtype"], seen["offline"] = dtype, consts.HF_HUB_OFFLINE

            def to(self, dev):
                return self

            def __call__(self, **kw):
                seen["kw"] = kw
                return [Out()]

        mods["diffusers"].ModularPipeline.from_pretrained.side_effect = lambda model, **k: Mod()
        refs = [(proc.image(f"r{i}", "64x64", i + 1), "image/png") for i in range(3)]
        with mock.patch.dict(sys.modules, mods), mock.patch.object(lm, "downloaded_precision", return_value="bf16"), mock.patch.object(lm, "has_fp16_variant", return_value=False), \
                mock.patch.object(M.LocalHFMedia, "_is_modular", staticmethod(lambda model: True)):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": "black-forest-labs/flux-3-image-klein"}, key="", needs_key=False)
            out = p.image("uma capa de revista", size="512x512", refs=refs, negative="feio")
        self.assertEqual(out[0].mime, "image/png")
        self.assertEqual(seen["init_with"], ("black-forest-labs/flux-3-image-klein", ["denoise"]))   # sem o expansor de 9B (18,8 GB de outro repositório)
        self.assertTrue(seen["offline"])                                                              # nada é baixado em silêncio
        self.assertFalse(consts.HF_HUB_OFFLINE)                                                       # e o modo offline não vaza para o resto do OpenFlow
        kw = seen["kw"]
        self.assertEqual((kw["prompt"], kw["output"], len(kw["image"])), ("uma capa de revista", "images", 3))
        self.assertNotIn("negative_prompt", kw)
        self.assertEqual(p.max_refs("black-forest-labs/flux-3-image-klein"), 10)
        self.assertEqual(M.LocalHFMedia._defaults("black-forest-labs/flux-3-image-klein"), (16, 0.0))
        self.assertEqual(M.LocalHFMedia._defaults("black-forest-labs/flux-3-image-klein-base"), (50, 3.5))

    def test_image_pipeline_uses_the_downloaded_precision_and_only_local_files(self):
        from openflow.canvas import localmodels as lm

        mods, calls = self.fake_modules()
        with mock.patch.dict(sys.modules, mods), mock.patch.object(lm, "downloaded_precision", return_value="fp16"), mock.patch.object(lm, "has_fp16_variant", return_value=True):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": "stabilityai/sd-turbo"}, key="", needs_key=False)
            out = p.image("um gato", size="1024x1024", count=1, seed=3)
        self.assertEqual(out[0].mime, "image/png")
        self.assertEqual(calls["model"], "stabilityai/sd-turbo")
        self.assertEqual(calls["device"], "cpu")
        self.assertEqual((calls["kw"]["num_inference_steps"], calls["kw"]["guidance_scale"], calls["kw"]["width"]), (2, 0.0, 768))  # turbo e CPU: leve
        load = mods["diffusers"].AutoPipelineForText2Image.from_pretrained.call_args.kwargs
        self.assertEqual((load["local_files_only"], load["variant"], load["torch_dtype"]), (True, "fp16", mods["torch"].float16))  # nunca baixa sozinho

    def test_a_model_that_was_not_downloaded_is_refused_instead_of_downloaded_silently(self):
        from openflow.canvas import localmodels as lm

        mods, calls = self.fake_modules()
        mods["transformers"] = mock.MagicMock()
        with mock.patch.dict(sys.modules, mods), mock.patch.object(lm, "downloaded_precision", return_value=""):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": "stabilityai/sd-turbo", "sound": "facebook/musicgen-small"}, key="", needs_key=False)
            for call in (lambda: p.image("x"), lambda: p.sound("x"), lambda: p.voice("x"), lambda: p.transcribe(WAV, "a.wav", "audio/wav")):
                with self.assertRaises(ProviderError) as cm:
                    call()
                self.assertIn("ainda não foi baixado", str(cm.exception))
                self.assertIn("precisão (quantização)", str(cm.exception))
        self.assertNotIn("model", calls)  # o modelo nem chegou a ser carregado

    def test_a_not_downloaded_model_falls_back_to_one_that_is_downloaded(self):
        from openflow.canvas import localmodels as lm

        mods, calls = self.fake_modules()
        have = lambda m: "fp16" if m == "stabilityai/sdxl-turbo" else ""  # noqa: E731 — só um modelo sugerido está baixado
        with mock.patch.dict(sys.modules, mods), mock.patch.object(lm, "downloaded_precision", side_effect=have), mock.patch.object(lm, "has_fp16_variant", return_value=False):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": "Qwen/Qwen-Image-2.1"}, key="", needs_key=False)  # o escolhido nunca foi baixado
            out = p.image("uma floresta", size="512x512", count=1, seed=1)
        self.assertEqual(out[0].mime, "image/png")
        self.assertEqual(calls["model"], "stabilityai/sdxl-turbo")  # usou o que já estava baixado, sem baixar nada
        with mock.patch.dict(sys.modules, mods), mock.patch.object(lm, "downloaded_precision", return_value=""):
            M._LOCAL_CACHE.clear()
            with self.assertRaises(ProviderError) as cm:  # nada baixado: continua explicando como baixar (e a tela mostra o botão)
                provider("local_hf", "", {"image": "Qwen/Qwen-Image-2.1"}, key="", needs_key=False).image("x")
            self.assertIn("Qwen/Qwen-Image-2.1", str(cm.exception))
            self.assertEqual(cm.exception.status, 424)

    def test_smaller_community_quantizations_are_listed_and_classified(self):
        from openflow.canvas import localmodels as lm

        data = [{"id": "x/m-gguf", "usedStorage": 5, "downloads": 9, "tags": ["gguf"]}, {"id": "x/m-nf4", "usedStorage": 12_000_000_000, "downloads": 5, "tags": ["bitsandbytes"]},
                {"id": "x/m-fp8", "usedStorage": 16_000_000_000, "downloads": 3, "tags": []}, {"id": "x/m-awq", "usedStorage": 9, "downloads": 1, "tags": ["awq"]}, {"id": "ruim id", "tags": []}]
        seen = {}

        def fake_get(url, headers=None, timeout=0):
            seen["url"] = url
            return data
        with mock.patch("openflow.providers.http.get_json", fake_get):
            out = lm.quantized_variants("Qwen/Qwen-Image-2.1")
        self.assertIn("base_model%3Aquantized%3AQwen%2FQwen-Image-2.1", seen["url"])
        self.assertEqual([v["id"] for v in out], ["x/m-nf4", "x/m-fp8", "x/m-gguf", "x/m-awq"])  # as carregáveis primeiro, da menor para a maior; id inválido some
        by = {v["id"]: v for v in out}
        self.assertEqual((by["x/m-nf4"]["kind"], by["x/m-fp8"]["kind"], by["x/m-gguf"]["kind"]), ("int4", "fp8", "GGUF"))
        self.assertTrue(by["x/m-nf4"]["loadable"] and not by["x/m-gguf"]["loadable"] and not by["x/m-awq"]["loadable"])

    def test_missing_torchvision_gets_a_clear_install_message(self):
        M._LOCAL_CACHE.clear()
        def loader():
            raise ImportError("Qwen3VLVideoProcessor requires the Torchvision library but it was not found in your environment.")
        with self.assertRaises(ProviderError) as cm:
            M._local_load("image", "Qwen/Qwen-Image-2.1", loader)
        self.assertIn("pip install torchvision", str(cm.exception))
        self.assertNotIn("Qwen/Qwen-Image-2.1", M._LOCAL_CACHE)
        with self.assertRaises(ValueError):   # outros erros passam como estavam
            M._local_load("image", "a/b", lambda: (_ for _ in ()).throw(ValueError("outro")))
        M._LOCAL_CACHE.clear()

    def test_missing_libraries_explain_how_to_install(self):
        with mock.patch.dict(sys.modules, {"torch": None, "diffusers": None, "transformers": None}):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", key="", needs_key=False)
            for call in (lambda: p.image("x"), lambda: p.sound("x"), lambda: p.voice("x"), lambda: p.transcribe(WAV, "a.wav", "audio/wav")):
                with self.assertRaises(ProviderError) as cm:
                    call()
                self.assertIn('pip install "openflow[media]"', str(cm.exception))


# --------------------------------------------------------------------------- motor


class EngineTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.store = Store(self.tmp)
        self.cs = self.store.projects

    def make(self, nodes, edges, name="t"):
        c = self.cs.create(name)
        return self.cs.save_layout(c["id"], {"nodes": nodes, "edges": edges})

    def run_engine(self, cid, targets=None, force=False, cancelled=lambda: False):
        ev = []
        stats = CanvasEngine(self.store, cid, ev.append, cancelled).run(targets, force)
        return stats, ev

    def result(self, cid, nid):
        return next(n for n in self.cs.get(cid)["nodes"] if n["id"] == nid)["result"]

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg não instalado")  # o modelo «scene» tem nós de vídeo/editor
    def test_template_runs_end_to_end_and_uses_the_cache(self):
        c = self.cs.create("t", "scene", "Uma faroleira acende o farol")
        stats, ev = self.run_engine(c["id"])
        self.assertEqual((stats["ran"], stats["errors"], stats["cached"]), (5, 0, 0))
        cur = self.cs.get(c["id"])
        kinds = {n["type"]: [next(a for a in cur["assets"] if a["id"] == i)["kind"] for i in n["result"]["assets"]] for n in cur["nodes"] if n["result"]["assets"]}
        self.assertEqual(kinds, {"image": ["image"], "video": ["video"], "voice": ["audio"], "sound": ["audio"], "editor": ["video"]} if HAVE_FFMPEG else kinds)
        self.assertEqual([e["state"] for e in ev if e["type"] == "node" and e["state"] != "running"], ["done"] * 5)
        eng = CanvasEngine(self.store, c["id"])
        self.assertEqual(eng.stale_ids(cur), [])
        # nada mudou: tudo vem do cache
        stats, ev = self.run_engine(c["id"])
        self.assertEqual((stats["ran"], stats["cached"]), (0, 5))
        # mudar o texto refaz só o que depende dele (imagem → vídeo → editor), e não a voz/som
        txt = next(n for n in cur["nodes"] if n["type"] == "text")
        self.cs.patch_node_params(c["id"], txt["id"], {"text": "Um dragão sobrevoa a montanha"})
        stale = {n["type"] for n in cur["nodes"] if n["id"] in CanvasEngine(self.store, c["id"]).stale_ids(self.cs.get(c["id"]))}
        self.assertEqual(stale, {"image", "video", "editor"})
        stats, _ = self.run_engine(c["id"])
        self.assertEqual((stats["ran"], stats["cached"]), (3, 2))
        # "gerar de novo" num alvo refaz só esse nó, com outra semente
        img = next(n for n in cur["nodes"] if n["type"] == "image")
        before = self.result(c["id"], img["id"])["assets"]
        stats, _ = self.run_engine(c["id"], [img["id"]], force=True)
        self.assertEqual(stats["ran"], 1)
        self.assertNotEqual(self.result(c["id"], img["id"])["assets"], before)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg não instalado")
    def test_editor_auto_timeline_and_export_duration(self):
        c = self.cs.create("t", "scene")
        self.run_engine(c["id"])
        cur = self.cs.get(c["id"])
        ed = next(n for n in cur["nodes"] if n["type"] == "editor")
        tl = ed["params"]["timeline"]
        self.assertEqual({t["kind"] for t in tl["tracks"]}, {"video", "audio"})
        self.assertEqual(sorted(c_["track"] for c_ in tl["clips"] if c_["start"] == 0 and c_["track"].startswith("t_a")), ["t_a1", "t_a2"])  # voz e som tocam juntos
        asset = next(a for a in cur["assets"] if a["id"] == ed["result"]["assets"][0])
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(self.cs.asset_path(c["id"], asset["file"]))], capture_output=True, text=True)
        self.assertAlmostEqual(float(probe.stdout), tl["duration"], delta=0.6)
        self.assertEqual((asset["w"], asset["h"]), (1280, 720))

    def test_editor_follows_connected_nodes_when_they_regenerate(self):
        c = self.make([node("text", nid="t", text="uma praia"), node("image", nid="i"), node("editor", nid="e")], [edge("t", "i", "prompt"), edge("i", "e", "clips")])
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg não instalado")
        self.run_engine(c["id"])
        first = self.result(c["id"], "i")["assets"][0]
        clip = next(n for n in self.cs.get(c["id"])["nodes"] if n["id"] == "e")["params"]["timeline"]["clips"][0]
        self.assertEqual((clip["node"], clip["asset"]), ("i", first))
        self.run_engine(c["id"], ["i"], force=True)
        self.assertNotEqual(self.result(c["id"], "i")["assets"][0], first)
        eng = CanvasEngine(self.store, c["id"])
        self.assertIn("e", eng.stale_ids(self.cs.get(c["id"])))  # o Editor percebe que a imagem mudou
        stats, _ = self.run_engine(c["id"])
        self.assertEqual(stats["ran"], 1)
        cur = self.cs.get(c["id"])
        resolved = eng.resolve_clip(cur, next(n for n in cur["nodes"] if n["id"] == "e")["params"]["timeline"]["clips"][0])
        self.assertEqual(resolved["asset"]["id"], self.result(c["id"], "i")["assets"][0])  # clipe ligado ao nó usa a imagem nova

    def test_errors_isolate_branches_and_skip_dependents(self):
        c = self.make([node("text", nid="t", text="x"), node("image", nid="bad", provider="a1111"), node("image", nid="ok"), node("video", nid="dep"), node("sound", nid="s", prompt="chuva", duration=1)],
                      [edge("t", "bad", "prompt"), edge("t", "ok", "prompt"), edge("bad", "dep", "image")])
        s = self.store.get_settings()
        self.store.save_settings({"media": {"urls": {"a1111": "http://127.0.0.1:9"}}})  # porta fechada
        stats, ev = self.run_engine(c["id"])
        self.assertEqual((stats["ran"], stats["errors"], stats["skipped"]), (2, 1, 1))
        self.assertEqual(self.result(c["id"], "bad")["state"], "error")
        self.assertIn("conectar", self.result(c["id"], "bad")["error"])
        self.assertEqual(self.result(c["id"], "ok")["state"], "done")
        self.assertEqual(self.result(c["id"], "dep")["state"], "idle")
        self.assertEqual([e["state"] for e in ev if e.get("id") == "dep" and e["state"] != "running"], ["skipped"])
        del s

    def test_edit_mode_refuses_a_model_that_cannot_take_an_input_image(self):
        from openflow.canvas import engine as E

        c = self.cs.create("t")
        a = self.cs.add_asset(c["id"], PNG, "png", "image", name="foto.png", mime="image/png")
        self.cs.save_layout(c["id"], {"nodes": [node("upload", nid="u", files=[a["id"]]), node("image", nid="e", mode="edit", prompt="deixe azul"), node("image", nid="g", prompt="um gato")],
                                      "edges": [edge("u", "e", "refs"), edge("u", "g", "refs")]})

        class NoRefs:
            supports_refs = False
            label = "Modelo X"

            def image(self, *a, **k):
                return [M.Media(PNG, "image/png")]

        with mock.patch.object(E, "build_media", lambda *a, **k: NoRefs()):
            _, ev = self.run_engine(c["id"])
        states = {e["id"]: e for e in ev if e.get("state") in ("error", "done")}
        self.assertEqual(states["e"]["state"], "error")
        self.assertIn("não consegue editar", states["e"]["message"])
        self.assertEqual(states["g"]["state"], "done")   # no modo Gerar a referência só vira aviso
        self.assertTrue(states["g"]["warnings"])

    def test_local_models_use_references_only_in_edit_mode_and_only_as_many_as_they_take(self):
        from openflow.canvas import engine as E

        c = self.cs.create("t")
        ids = [self.cs.add_asset(c["id"], proc.image(f"imagem {i}", "64x64", i + 1), "png", "image", name=f"f{i}.png", mime="image/png")["id"] for i in range(3)]   # três imagens diferentes (iguais valeriam uma só)
        self.cs.save_layout(c["id"], {"nodes": [node("upload", nid="u", files=ids), node("image", nid="g", prompt="um gato"), node("image", nid="e", mode="edit", prompt="deixe azul")],
                                      "edges": [edge("u", "g", "refs"), edge("u", "e", "refs")]})
        seen = {}

        class Local:
            supports_refs = True
            refs_edit_only = True
            label = "Local"

            def max_refs(self, model=""):
                return 1

            def image(self, prompt, *, refs=(), **k):
                seen[prompt] = len(refs)
                return [M.Media(PNG, "image/png")]

        with mock.patch.object(E, "build_media", lambda *a, **k: Local()):
            _, ev = self.run_engine(c["id"])
        warns = {e["id"]: e.get("warnings") for e in ev if e.get("state") == "done"}
        self.assertEqual(seen.get("um gato"), 0)             # modo Gerar: as referências não viram a imagem de partida
        self.assertTrue(any("Editar" in w for w in warns["g"]))
        self.assertEqual(seen["deixe azul"], 1)           # modo Editar: este modelo usa uma só
        self.assertTrue(any("ignorei as outras 2" in w for w in warns["e"]))

    def test_mentions_lose_their_reference_marks_when_the_model_does_not_get_the_images(self):
        from openflow.canvas import engine as E

        c = self.cs.create("t")
        a = self.cs.add_asset(c["id"], PNG, "png", "image", name="Foto Perfil.png", mime="image/png")
        self.cs.save_layout(c["id"], {"nodes": [node("image", nid="g", prompt="@foto-perfil no centro, com @ninguem ao lado")], "edges": []})
        prompts = []

        class Local:
            supports_refs = True
            refs_edit_only = True
            label = "Local"

            def max_refs(self, model=""):
                return 1

            def image(self, prompt, **k):
                prompts.append(prompt)
                return [M.Media(PNG, "image/png")]

        with mock.patch.object(E, "build_media", lambda *a, **k: Local()):
            self.run_engine(c["id"])
        self.assertEqual(prompts, ["foto-perfil no centro, com @ninguem ao lado"])   # sem «(reference image 1)»; o que não casa com mídia fica como estava
        del a

    def test_the_same_image_cited_with_at_and_connected_to_references_is_sent_once(self):
        from openflow.canvas import engine as E

        c = self.cs.create("t")
        names = ["foto-perfil.png", "fnaf-1-office.png", "fnaf-1-bonnie.png"]
        ids = [self.cs.add_asset(c["id"], proc.image(n, "64x64", i + 1), "png", "image", name=n, mime="image/png")["id"] for i, n in enumerate(names)]
        self.cs.save_layout(c["id"], {"nodes": [node("text", nid="t", text="@foto_perfil no centro, fundo @fnaf-1-office e o @fnaf-1-bonnie"), node("upload", nid="u", files=ids), node("image", nid="i", mode="edit")],
                                      "edges": [edge("t", "i", "prompt"), edge("u", "i", "refs")]})
        seen = {}

        class Cloud:
            supports_refs = True
            label = "Nuvem"

            def image(self, prompt, *, refs=(), **k):
                seen["prompt"], seen["n"] = prompt, len(refs)
                return [M.Media(PNG, "image/png")]

        with mock.patch.object(E, "build_media", lambda *a, **k: Cloud()):
            _, ev = self.run_engine(c["id"])
        self.assertEqual(seen["n"], 3)                        # 3 imagens, não 6: as citadas e as ligadas são as mesmas
        self.assertIn("(reference image 1)", seen["prompt"])  # «@foto_perfil» (com sublinhado) também casa com «foto-perfil»
        self.assertIn("(reference image 3)", seen["prompt"])
        self.assertEqual([e.get("warnings") for e in ev if e.get("id") == "i" and e["state"] == "done"], [[]])

    def test_flux3_prompts_are_expanded_by_the_configured_text_model_unless_they_are_already_captions(self):
        from openflow.canvas import engine as E

        c = self.cs.create("t")
        self.cs.save_layout(c["id"], {"nodes": [node("image", nid="short", prompt="um gato na janela", model="black-forest-labs/flux-3-image-klein"),
                                                node("image", nid="long", prompt=" ".join(["palavra"] * 70), model="black-forest-labs/flux-3-image-klein"),
                                                node("image", nid="off", prompt="um cão", model="black-forest-labs/flux-3-image-klein", extra={"upsample": False}),
                                                node("image", nid="other", prompt="um pato", model="gpt-image-1")], "edges": []})
        sent, chats = {}, []

        class LLM:
            def chat(self, messages, system="", **k):
                chats.append((messages[0]["content"], system))
                return '"A macro photograph of a tabby cat on a sunlit window sill, soft morning light."'

        class Prov:
            supports_refs = False
            label = "P"

            def image(self, prompt, *, extra=None, **k):
                sent[prompt[:12]] = (prompt, dict(extra or {}))
                return [M.Media(PNG, "image/png")]

        settings = self.store.get_settings()
        settings["active"]["generation"] = "fake-llm"
        with mock.patch.object(E, "build_media", lambda *a, **k: Prov()), mock.patch.object(E, "build_provider", lambda *a, **k: LLM()), \
                mock.patch.object(self.store, "get_settings", return_value=settings):
            _, ev = self.run_engine(c["id"])
        self.assertEqual(len(chats), 1)                                                   # só o prompt curto do FLUX.3 foi expandido
        self.assertIn("scene caption", chats[0][1])
        self.assertTrue(sent["A macro phot"][0].startswith("A macro photograph"))  # as aspas do modelo de texto saem
        self.assertIn("palavra palavra", sent["palavra pala"][0])                 # legenda longa: segue como está
        self.assertEqual(sent["um cão"][0], "um cão")                                      # {"upsample": false}
        self.assertEqual(sent["um cão"][1], {})                                            # e a chave não chega ao provedor
        self.assertEqual(sent["um pato"][0], "um pato")                                    # outros modelos não são expandidos
        warns = {e["id"]: e.get("warnings") for e in ev if e.get("state") == "done"}
        self.assertTrue(any(w.startswith("Prompt expandido") for w in warns["short"]))

    def test_validation_messages(self):
        c = self.make([node("image", nid="i"), node("video", nid="v"), node("voice", nid="vo"), node("sound", nid="so"), node("llm", nid="l"), node("transcribe", nid="tr"), node("image", nid="ed", mode="edit", prompt="x")], [])
        _, ev = self.run_engine(c["id"])
        errs = {e["id"]: e["message"] for e in ev if e.get("state") == "error"}
        self.assertEqual(set(errs), {"i", "v", "vo", "so", "l", "tr", "ed"})
        self.assertIn("prompt", errs["i"])
        self.assertIn("Referências", errs["ed"])
        self.assertIn("áudio", errs["tr"].lower())

    def test_global_and_connected_styles_apply_and_can_be_ignored(self):
        c = self.make([node("style_prompt", nid="g", text="aquarela suave", **{"global": True}), node("style_prompt", nid="local", text="contorno preto", **{"global": False}),
                       node("text", nid="t", text="uma casa"), node("image", nid="a"), node("image", nid="b", ignore_global_styles=True), node("image", nid="c"), node("llm", nid="l", instruction="amplie")],
                      [edge("t", "a", "prompt"), edge("t", "b", "prompt"), edge("t", "c", "prompt"), edge("local", "c", "style"), edge("t", "l", "prompt")])
        self.run_engine(c["id"])
        cur = self.cs.get(c["id"])

        def prompt_of(nid):
            n = next(x for x in cur["nodes"] if x["id"] == nid)
            return next(a for a in cur["assets"] if a["id"] == n["result"]["assets"][0])["prompt"]

        self.assertIn("aquarela suave", prompt_of("a"))
        self.assertNotIn("contorno preto", prompt_of("a"))  # só vale onde está ligado
        self.assertNotIn("aquarela suave", prompt_of("b"))  # o nó escolheu ignorar os estilos globais
        self.assertIn("contorno preto", prompt_of("c"))
        self.assertIn("aquarela suave", prompt_of("c"))
        self.assertIn("aquarela suave", self.result(c["id"], "l")["text"])  # o Texto IA também segue o estilo
        # editar o estilo global invalida os nós que ele afeta (e só eles)
        self.cs.patch_node_params(c["id"], "g", {"text": "óleo sobre tela"})
        stale = set(CanvasEngine(self.store, c["id"]).stale_ids(self.cs.get(c["id"])))
        self.assertEqual(stale, {"a", "c", "l"})

    def test_style_folder_is_described_cached_and_applied(self):
        c = self.cs.create("t")
        refs = [self.cs.add_asset(c["id"], proc.image(p, "96x96", i), "png", "image", name=f"ref{i}.png", mime="image/png") for i, p in enumerate(("floresta noite", "praia sol"))]
        self.cs.save_layout(c["id"], {"nodes": [node("style_folder", nid="sf", files=[a["id"] for a in refs], **{"global": True}), node("image", nid="i", prompt="um barco")], "edges": []})
        stats, _ = self.run_engine(c["id"])
        self.assertEqual(stats["errors"], 0)
        digest = self.result(c["id"], "sf")["digest"]
        self.assertTrue(digest)
        self.assertIn("2 arquivo", digest)
        if HAVE_FFMPEG:
            self.assertRegex(digest, r"#[0-9a-f]{6}")  # paleta dominante
        cur = self.cs.get(c["id"])
        img = next(n for n in cur["nodes"] if n["id"] == "i")
        self.assertIn("Style:", next(a for a in cur["assets"] if a["id"] == img["result"]["assets"][0])["prompt"])
        # a descrição fica guardada: sem mudar os arquivos, não é refeita
        key = self.result(c["id"], "sf")["digest_key"]
        self.run_engine(c["id"], force=True, targets=["i"])
        self.assertEqual(self.result(c["id"], "sf")["digest_key"], key)
        # trocar os arquivos muda o estilo e invalida a imagem
        self.cs.delete_asset(c["id"], refs[1]["id"])
        self.assertIn("i", CanvasEngine(self.store, c["id"]).stale_ids(self.cs.get(c["id"])))

    def test_style_folder_uses_the_text_model_when_configured(self):
        from tests.helpers import MockProviderServer

        with MockProviderServer() as srv:
            self.store.save_settings({"providers": {"custom": {"base_url": srv.url + "/v1", "model": "m", "vision": True}}, "active": {"generation": "custom"}})
            c = self.cs.create("t")
            a = self.cs.add_asset(c["id"], PNG, "png", "image", name="r.png", mime="image/png")
            self.cs.save_layout(c["id"], {"nodes": [node("style_folder", nid="sf", files=[a["id"]])], "edges": []})
            self.run_engine(c["id"], ["sf"])
            req = next(r for r in srv.requests if r["path"].endswith("/chat/completions"))
            parts = req["body"]["messages"][-1]["content"]
            self.assertTrue(any(p.get("type") == "image_url" for p in parts))  # a imagem de referência vai para o modelo com visão
            self.assertTrue(self.result(c["id"], "sf")["digest"])

    def test_llm_chains_into_image_prompt(self):
        c = self.make([node("text", nid="t", text="um gato"), node("llm", nid="l", instruction="detalhe a cena"), node("image", nid="i")], [edge("t", "l", "prompt"), edge("l", "i", "prompt")])
        self.run_engine(c["id"])
        text_out = self.result(c["id"], "l")["text"]
        self.assertIn("um gato", text_out)
        cur = self.cs.get(c["id"])
        img = next(n for n in cur["nodes"] if n["id"] == "i")
        self.assertIn(text_out, next(a for a in cur["assets"] if a["id"] == img["result"]["assets"][0])["prompt"])

    def test_transcribe_node_with_a_speech_server(self):
        with MediaMock() as srv:
            self.store.save_settings({"media": {"active": {"stt": "custom"}, "urls": {"custom": srv.url + "/v1"}}})
            c = self.cs.create("t")
            a = self.cs.add_asset(c["id"], WAV, "wav", "audio", name="fala.wav", mime="audio/wav")
            self.cs.save_layout(c["id"], {"nodes": [node("upload", nid="u", files=[a["id"]]), node("transcribe", nid="tr", language="pt"), node("image", nid="i")],
                                           "edges": [edge("u", "tr", "audio"), edge("tr", "i", "prompt")]})
            stats, _ = self.run_engine(c["id"])
            self.assertEqual(stats["errors"], 0, self.result(c["id"], "tr"))
            self.assertEqual(self.result(c["id"], "tr")["text"], "olá mundo transcrito")
            cur = self.cs.get(c["id"])
            self.assertIn("olá mundo transcrito", next(x for x in cur["assets"] if x["node"] == "i")["prompt"])  # a transcrição alimenta a imagem

    def test_external_provider_through_node_settings_and_default(self):
        with MediaMock() as srv:
            self.store.save_settings({"providers": {"openai": {"api_key": "sk-test"}}, "media": {"urls": {"openai": srv.url + "/v1"}, "active": {"image": "openai"}, "models": {"openai": {"image": "gpt-image-1"}}}})
            c = self.make([node("image", nid="i", prompt="um robô", count=2), node("voice", nid="v", text="Olá", provider="demo")], [])
            stats, _ = self.run_engine(c["id"])
            self.assertEqual(stats["errors"], 0, [self.result(c["id"], n)["error"] for n in ("i", "v")])
            cur = self.cs.get(c["id"])
            assets = {a["id"]: a for a in cur["assets"]}
            imgs = [assets[i] for i in self.result(c["id"], "i")["assets"]]
            self.assertEqual(len(imgs), 2)
            self.assertEqual((imgs[0]["provider"], imgs[0]["model"]), ("openai", "gpt-image-1"))
            self.assertEqual(assets[self.result(c["id"], "v")["assets"][0]]["provider"], "demo")
            self.assertEqual(srv.last("/images/generations")["h"]["authorization"], "Bearer sk-test")
            # trocar de provedor/modelo invalida o cache
            self.cs.patch_node_params(c["id"], "i", {"model": "dall-e-3"})
            self.assertIn("i", CanvasEngine(self.store, c["id"]).stale_ids(self.cs.get(c["id"])))

    def test_force_without_targets_regenerates_every_node(self):
        c = self.make([node("text", nid="t", text="uma ilha"), node("image", nid="i"), node("sound", nid="s", prompt="vento", duration=1)], [edge("t", "i", "prompt")])
        self.run_engine(c["id"])
        before = (self.result(c["id"], "i")["assets"], self.result(c["id"], "s")["assets"])
        stats, _ = self.run_engine(c["id"], force=True)
        self.assertEqual((stats["ran"], stats["cached"]), (2, 0))
        self.assertNotEqual((self.result(c["id"], "i")["assets"], self.result(c["id"], "s")["assets"]), before)

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg não instalado")  # o modelo «scene» tem nós de vídeo/editor
    def test_cancellation_leaves_nodes_idle(self):
        c = self.cs.create("t", "scene")
        calls = {"n": 0}

        def cancelled():
            calls["n"] += 1
            return calls["n"] > 6

        with self.assertRaises(Cancelled):
            self.run_engine(c["id"], cancelled=cancelled)
        states = {n["result"]["state"] for n in self.cs.get(c["id"])["nodes"]}
        self.assertNotIn("running", states)
        self.assertIn("done", states)  # o que terminou antes de cancelar permanece

    def test_palette_of_image(self):
        if not HAVE_FFMPEG:
            self.skipTest("ffmpeg não instalado")
        p = self.tmp / "x.png"
        p.write_bytes(proc.image("praia sol", "64x64", 1))
        pal = palette_of(p)
        self.assertTrue(pal and all(re.match(r"^#[0-9a-f]{6}$", c) for c in pal))
        self.assertEqual(palette_of(self.tmp / "nao.png"), [])


class RenderTests(TmpCase):
    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg não instalado")
    def test_layers_audio_mix_text_and_errors(self):
        img = self.tmp / "a.png"
        img.write_bytes(proc.image("floresta", "320x180", 1))
        snd = self.tmp / "s.wav"
        snd.write_bytes(proc.sound_fx("chuva", 3.0, 1))
        files = {"img": {"path": img, "kind": "image", "duration": 3}, "snd": {"path": snd, "kind": "audio", "duration": 3}}
        tl = S.normalize_timeline({"tracks": [{"id": "v1", "kind": "video"}, {"id": "v2", "kind": "video"}, {"id": "a1", "kind": "audio"}, {"id": "t1", "kind": "text"}],
                                   "clips": [{"track": "v1", "asset": "img", "start": 0, "dur": 2}, {"track": "v2", "asset": "img", "start": 1, "dur": 1, "scale": 0.3, "opacity": 0.5},
                                             {"track": "a1", "asset": "snd", "start": 0.5, "dur": 2, "volume": 0.5, "fade_out": 1}, {"track": "t1", "text": "Legenda", "start": 0, "dur": 2},
                                             {"track": "v1", "asset": "sumiu", "start": 2, "dur": 1}]})
        out = self.tmp / "o.mp4"
        warnings = render_timeline(tl, 320, 180, 12, "#000000", lambda c: files.get(c["asset"]), out)
        self.assertTrue(any("não existe" in w for w in warnings))
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "default=nw=1", str(out)], capture_output=True, text=True).stdout
        self.assertIn("codec_type=video", probe)
        self.assertIn("codec_type=audio", probe)
        self.assertAlmostEqual(float(re.search(r"duration=([\d.]+)", probe).group(1)), 2.5, delta=0.3)
        with self.assertRaises(ProviderError) as cm:
            render_timeline(S.normalize_timeline({}), 320, 180, 12, "#000000", lambda c: None, self.tmp / "vazio.mp4")
        self.assertIn("vazia", str(cm.exception))


# --------------------------------------------------------------------------- API HTTP


class CanvasApiTests(ServerCase):
    def test_crud_templates_layout_and_downloads(self):
        status, meta = self.c.json("GET", "/api/project-templates")
        self.assertEqual(status, 200)
        self.assertEqual({t["id"] for t in meta["templates"]}, {t["id"] for t in S.TEMPLATES})
        self.assertIn("editor", [t["type"] for t in meta["types"]])
        status, c = self.c.json("POST", "/api/projects", {"name": "Projeto A", "template": "styled", "prompt": "um gato"})
        self.assertEqual(status, 201)
        cid = c["id"]
        self.assertEqual(self.c.json("GET", "/api/projects")[1][0]["id"], cid)
        status, full = self.c.json("GET", f"/api/projects/{cid}")
        self.assertEqual((len(full["nodes"]), full["job_id"]), (3, ""))
        self.assertEqual(sorted(full["stale"]), sorted(n["id"] for n in full["nodes"] if n["type"] == "image"))
        # salvar layout (o que o navegador faz sozinho)
        full["nodes"][0]["x"] = 321
        status, saved = self.c.json("PUT", f"/api/projects/{cid}", {"nodes": full["nodes"], "edges": full["edges"], "viewport": {"x": 1, "y": 2, "zoom": 0.8}, "name": "Projeto A"})
        self.assertEqual(status, 200, saved)
        self.assertEqual(self.c.json("GET", f"/api/projects/{cid}")[1]["nodes"][0]["x"], 321)
        self.assertEqual(self.c.json("PUT", "/api/projects/nao_existe", {"nodes": []})[0], 404)
        status, m = self.c.json("POST", f"/api/projects/{cid}/meta", {"name": "Renomeado", "description": "d"})
        self.assertEqual((m["name"], m["description"]), ("Renomeado", "d"))
        status, dup = self.c.json("POST", f"/api/projects/{cid}/duplicate")
        self.assertEqual(status, 201)
        self.assertEqual(self.c.json("DELETE", f"/api/projects/{dup['id']}")[1], {"ok": True})
        self.assertEqual(self.c.json("GET", f"/api/projects/{dup['id']}")[0], 404)
        status, headers, body = self.c.req("GET", f"/api/projects/{cid}/download")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/zip")
        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertIn("project.json", z.namelist())
        self.c.json("DELETE", f"/api/projects/{cid}")

    def test_run_job_events_results_and_media_serving(self):
        cid = self.c.json("POST", "/api/projects", {"name": "B", "template": "text_image", "prompt": "uma montanha"})[1]["id"]
        status, r = self.c.json("POST", f"/api/projects/{cid}/run", {})
        self.assertEqual(status, 200, r)
        events = self.c.sse(f"/api/jobs/{r['job_id']}/events")
        types = [e["type"] for e in events]
        self.assertEqual(types[0], "start")
        self.assertIn("summary", types)
        self.assertEqual(events[-1], {"type": "end", "status": "done", "seq": events[-1].get("seq")} if "seq" in events[-1] else {"type": "end", "status": "done"})
        status, cur = self.c.json("GET", f"/api/projects/{cid}")
        img = next(n for n in cur["nodes"] if n["type"] == "image")
        self.assertEqual(img["result"]["state"], "done")
        self.assertEqual(cur["stale"], [])
        asset = next(a for a in cur["assets"] if a["id"] == img["result"]["assets"][0])
        status, headers, body = self.c.req("GET", f"/api/projects/{cid}/assets/{asset['file']}")
        self.assertEqual((status, headers["Content-Type"], body[:4]), (200, "image/png", b"\x89PNG"))
        self.assertIn("Accept-Ranges", headers)
        status, headers, part = self.c.req("GET", f"/api/projects/{cid}/assets/{asset['file']}", headers={"Range": "bytes=0-7"})
        self.assertEqual((status, len(part), headers["Content-Range"].split("/")[0]), (206, 8, "bytes 0-7"))
        status, headers, _ = self.c.req("GET", f"/api/projects/{cid}/assets/{asset['file']}?download=1")
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(self.c.req("GET", f"/api/projects/{cid}/assets/..%2Fcanvas.json")[0], 404)
        self.assertEqual(self.c.req("GET", f"/api/projects/{cid}/assets/project.json")[0], 404)  # só arquivos registrados em assets/
        # rodar de novo: tudo em cache; apagar o arquivo limpa o nó
        r2 = self.c.json("POST", f"/api/projects/{cid}/run", {})[1]
        ev2 = self.c.sse(f"/api/jobs/{r2['job_id']}/events")
        self.assertEqual(next(e for e in ev2 if e["type"] == "summary")["cached"], 1)
        self.assertEqual(self.c.json("DELETE", f"/api/projects/{cid}/assets/{asset['id']}")[1], {"ok": True})
        cur = self.c.json("GET", f"/api/projects/{cid}")[1]
        self.assertEqual(next(n for n in cur["nodes"] if n["type"] == "image")["result"]["assets"], [])
        self.assertEqual(self.c.json("POST", f"/api/projects/{cid}/run", {"nodes": ["nao_existe"]})[0], 200)  # o job falha com mensagem, não derruba o servidor
        self.c.json("DELETE", f"/api/projects/{cid}")

    def test_layout_autosave_cannot_erase_results(self):
        cid = self.c.json("POST", "/api/projects", {"template": "text_image"})[1]["id"]
        r = self.c.json("POST", f"/api/projects/{cid}/run", {})[1]
        self.c.sse(f"/api/jobs/{r['job_id']}/events")
        old = self.c.json("GET", f"/api/projects/{cid}")[1]
        for n in old["nodes"]:
            n["result"] = {"state": "idle", "assets": []}
        old["assets"] = []
        self.assertEqual(self.c.json("PUT", f"/api/projects/{cid}", old)[0], 200)
        now = self.c.json("GET", f"/api/projects/{cid}")[1]
        self.assertEqual(next(n for n in now["nodes"] if n["type"] == "image")["result"]["state"], "done")
        self.assertEqual(len(now["assets"]), 1)

    def test_upload_media_and_attach_to_nodes(self):
        c = self.c.json("POST", "/api/projects", {"name": "U"})[1]
        cid = c["id"]
        full = self.c.json("GET", f"/api/projects/{cid}")[1]
        self.c.json("PUT", f"/api/projects/{cid}", {"nodes": [node("style_folder", nid="sf"), node("upload", nid="up")], "edges": [], "viewport": full["viewport"]})
        status, a = self.c.json("POST", f"/api/projects/{cid}/assets?node=sf", raw=PNG, headers={"X-Filename": "refer%C3%AAncia.png", "Content-Type": "application/octet-stream"})
        self.assertEqual((status, a["kind"], a["mime"], a["name"]), (201, "image", "image/png", "referência.png"))
        status, w = self.c.json("POST", f"/api/projects/{cid}/assets?node=up", raw=WAV, headers={"X-Filename": "som.wav"})
        self.assertEqual((w["kind"], w["mime"]), ("audio", "audio/wav"))
        # um HTML disfarçado de PNG não passa
        status, err = self.c.json("POST", f"/api/projects/{cid}/assets", raw=b"<script>alert(1)</script>", headers={"X-Filename": "x.png"})
        self.assertEqual(status, 400)
        self.assertEqual(self.c.json("POST", f"/api/projects/{cid}/assets", raw=b"", headers={"X-Filename": "x.png"})[0], 400)
        self.assertEqual(self.c.json("POST", f"/api/projects/{cid}/assets", raw=b"texto", headers={"X-Filename": "nota.txt"})[0], 400)
        cur = self.c.json("GET", f"/api/projects/{cid}")[1]
        self.assertEqual(next(n for n in cur["nodes"] if n["id"] == "sf")["params"]["files"], [a["id"]])
        self.assertEqual(next(n for n in cur["nodes"] if n["id"] == "up")["params"]["files"], [w["id"]])
        status, headers, _ = self.c.req("GET", f"/api/projects/{cid}/assets/{w['file']}")
        self.assertEqual(headers["Content-Type"], "audio/wav")
        self.c.json("DELETE", f"/api/projects/{cid}")

    def test_composer_attachments_become_nodes(self):
        up_img = self.c.json("POST", "/api/uploads", raw=PNG, headers={"X-Filename": "ref.png", "Content-Type": "image/png"})[1]
        up_txt = self.c.json("POST", "/api/uploads", raw="Roteiro: a faroleira acende o farol.".encode(), headers={"X-Filename": "roteiro.txt", "Content-Type": "text/plain"})[1]
        status, c = self.c.json("POST", "/api/projects", {"template": "text_image", "prompt": "x", "attachment_ids": [up_img["id"], up_txt["id"], "nao_existe"]})
        self.assertEqual(status, 201)
        by_type = {n["type"]: n for n in c["nodes"] if n["type"] in ("upload", "text") and n["x"] < 0}
        self.assertEqual(len(by_type["upload"]["params"]["files"]), 1)
        self.assertIn("faroleira", by_type["text"]["params"]["text"])
        self.assertEqual(by_type["text"]["title"], "roteiro.txt")
        self.assertEqual([a["kind"] for a in c["assets"]], ["image"])
        self.c.json("DELETE", f"/api/projects/{c['id']}")

    def test_local_models_need_a_precision_choice_before_any_download(self):
        hub = FakeHub(self.tmp)
        with mock.patch.dict(sys.modules, {"huggingface_hub": hub.module}):
            self.assertEqual(self.c.json("POST", "/api/media/local/download", {"model": "stabilityai/sd-turbo"})[0], 400)  # sem precisão: nada baixa
            self.assertEqual(self.c.json("POST", "/api/media/local/download", {"model": "../x", "precision": "fp16"})[0], 400)
            self.assertEqual(hub.downloaded, [])
            status, opts = self.c.json("GET", "/api/media/local/options?model=stabilityai/sd-turbo")
            self.assertEqual(status, 200)
            self.assertEqual({o["id"] for o in opts["options"]}, {"fp32", "fp16", "bf16"})
            self.assertEqual(self.c.json("GET", "/api/media/local/options?model=nada")[0], 400)
            self.assertEqual(self.c.json("GET", "/api/media/local/quants?model=nada")[0], 400)
            with mock.patch("openflow.providers.http.get_json", return_value=[{"id": "c/m-fp8", "usedStorage": 7, "tags": []}]):
                st, q = self.c.json("GET", "/api/media/local/quants?model=stabilityai/sd-turbo")
            self.assertEqual((st, q["variants"][0]["id"], q["variants"][0]["kind"]), (200, "c/m-fp8", "fp8"))
            state = self.c.json("GET", "/api/media/local/state")[1]
            self.assertTrue(state["libs"])
            self.assertEqual(state["models"]["image"]["precision"], "")
            job = self.c.json("POST", "/api/media/local/download", {"model": "stabilityai/sd-turbo", "precision": "fp16"})[1]
            ev = self.c.sse(f"/api/jobs/{job['job_id']}/events")
            self.assertEqual([e["precision"] for e in ev if e["type"] == "done"], ["fp16"])
            self.assertEqual(self.c.json("GET", "/api/media/local/state")[1]["models"]["image"]["precision"], "fp16")

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg não instalado")
    def test_editor_autofill_endpoint(self):
        cid = self.c.json("POST", "/api/projects", {"template": "scene"})[1]["id"]
        r = self.c.json("POST", f"/api/projects/{cid}/run", {"nodes": [n["id"] for n in self.c.json("GET", f"/api/projects/{cid}")[1]["nodes"] if n["type"] in ("image", "voice")]})[1]
        self.c.sse(f"/api/jobs/{r['job_id']}/events")
        cur = self.c.json("GET", f"/api/projects/{cid}")[1]
        ed = next(n for n in cur["nodes"] if n["type"] == "editor")
        status, out = self.c.json("POST", f"/api/projects/{cid}/nodes/{ed['id']}/autofill")
        self.assertEqual(status, 200)
        self.assertEqual(len(out["timeline"]["clips"]), 1)  # só a imagem e a voz já tinham resultado; a imagem não está ligada ao Editor, a voz sim
        self.assertEqual(self.c.json("POST", f"/api/projects/{cid}/nodes/nao/autofill")[0], 404)
        self.c.json("DELETE", f"/api/projects/{cid}")

    def test_media_providers_endpoint_never_leaks_keys_and_tests_connection(self):
        with MediaMock() as srv:
            self.c.json("PUT", "/api/settings", {"providers": {"openai": {"api_key": "sk-SECRETO"}}, "media": {"urls": {"openai": srv.url + "/v1"}, "active": {"image": "openai"}}})
            status, r = self.c.json("GET", "/api/media/providers")
            self.assertEqual(status, 200)
            self.assertNotIn("SECRETO", json.dumps(r))
            by = {p["id"]: p for p in r["providers"]}
            self.assertTrue(by["openai"]["has_key"])
            self.assertEqual(r["active"]["image"], "openai")
            self.assertEqual(by["openai"]["base_url"], srv.url + "/v1")
            status, t = self.c.json("POST", "/api/media/test", {"provider": "openai"})
            self.assertEqual((status, t["ok"]), (200, True))
            self.assertIn("conectado", t["message"])
            status, models = self.c.json("GET", "/api/media/models?provider=openai&cap=image")
            self.assertIn("gpt-image-1", models["models"])
            self.assertEqual(self.c.json("POST", "/api/media/test", {"provider": "elevenlabs"})[0], 502)  # sem chave
            self.assertEqual(self.c.json("POST", "/api/media/test", {"provider": "nada"})[0], 502)
            self.assertEqual(self.c.json("POST", "/api/media/test", {"provider": "demo"})[1]["ok"], True)
        self.c.json("PUT", "/api/settings", {"providers": {"openai": {"api_key": None}}, "media": {"urls": {"openai": ""}, "active": {"image": "demo"}}})


if __name__ == "__main__":
    unittest.main()
