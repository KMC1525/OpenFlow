"""Canvas v0.11: os 30 nós novos (Texto, Imagem, Vídeo, Som, Input, Output) rodam de verdade (ffmpeg real) e se conectam entre si e com os antigos."""
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow.canvas import nodes_ext, schema  # noqa: E402
from openflow.canvas.engine import CanvasEngine  # noqa: E402
from openflow.storage import Store  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg"))


def ff(*a):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)


class SchemaTests(unittest.TestCase):
    def test_five_new_nodes_per_type_and_the_palette_is_reorganized(self):
        groups = {}
        for k, v in nodes_ext.SPECS.items():
            groups.setdefault(v["group"], []).append(k)
        self.assertEqual({g: len(v) for g, v in groups.items()}, {"Texto": 5, "Imagem": 5, "Vídeo": 5, "Som": 5, "Input": 5, "Output": 5})
        self.assertEqual([g for g, _ in schema.PALETTE], ["Texto", "Imagem", "Vídeo", "Som", "Input", "Output"])
        listed = [t for _, ts in schema.PALETTE for t in ts]
        self.assertEqual(sorted(listed), sorted(schema.NODE_TYPES))  # todo nó (antigo e novo) está na paleta, uma vez só
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual({t["group"] for t in schema.describe_types()}, {"Texto", "Imagem", "Vídeo", "Som", "Input", "Output"})
        for k in schema.NODE_TYPES:  # todo nó tem parâmetros válidos por padrão
            self.assertIsInstance(schema.normalize_params(k, {}), dict)
        for k in nodes_ext.SPECS:
            self.assertIn(k, nodes_ext.RUNNERS)

    def test_every_output_type_can_reach_a_node_that_uses_it(self):
        """Integração: de cada tipo de saída (texto, imagem, vídeo, áudio, mídia) existe porta compatível em nós antigos e novos, e tudo entra no Editor e na Galeria."""
        for out in ("text", "image", "video", "audio", "media"):
            targets = [(t, p["id"]) for t, v in schema.NODE_TYPES.items() for p in [schema.port_def(t, i[0]) for i in v["ins"]] if schema.compatible(out, p["accepts"])]
            self.assertGreaterEqual(len(targets), 4, out)
            self.assertIn(("editor", "clips"), targets)
            self.assertIn(("out_gallery", "items"), targets)
        self.assertTrue(schema.compatible("video", schema.port_def("image", "refs")["accepts"]))   # vídeo vira imagem de referência (quadro)
        self.assertTrue(schema.compatible("video", schema.port_def("video", "image")["accepts"]))
        self.assertTrue(schema.compatible("video", schema.port_def("transcribe", "audio")["accepts"]))
        self.assertTrue(schema.compatible("text", schema.port_def("voice", "text")["accepts"]))

    def test_old_projects_still_load(self):
        n = schema.normalize_node({"type": "image", "params": {"prompt": "x"}})
        self.assertEqual(n["type"], "image")
        self.assertIsNone(schema.normalize_node({"type": "nao_existe"}))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg não instalado")
class RunTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.store = Store(self.tmp / "home")
        self.cs = self.store.projects
        m = self.tmp / "m"
        m.mkdir()
        ff("-f", "lavfi", "-i", "testsrc2=d=4:s=320x240:r=24", "-f", "lavfi", "-i", "sine=f=300:d=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(m / "v.mp4"))
        ff("-f", "lavfi", "-i", "color=c=red:s=320x240", "-frames:v", "1", str(m / "p1.png"))
        ff("-f", "lavfi", "-i", "color=c=blue:s=200x300", "-frames:v", "1", str(m / "p2.png"))
        ff("-f", "lavfi", "-i", "sine=f=220:d=3", "-c:a", "pcm_s16le", str(m / "a1.wav"))
        ff("-f", "lavfi", "-i", "sine=f=440:d=2", "-c:a", "pcm_s16le", str(m / "a2.wav"))
        self.m = m
        self.cv = self.cs.create("Projeto X")
        self.cid = self.cv["id"]
        self.ids = {}
        for key, fn, kind, mime in (("v", "v.mp4", "video", "video/mp4"), ("p1", "p1.png", "image", "image/png"), ("p2", "p2.png", "image", "image/png"),
                                    ("a1", "a1.wav", "audio", "audio/wav"), ("a2", "a2.wav", "audio", "audio/wav")):
            a = self.cs.add_asset(self.cid, (m / fn).read_bytes(), fn.rsplit(".", 1)[1], kind, name=fn, mime=mime)
            self.ids[key] = a["id"]

    def build(self, node_type, params, feeds):
        """Um grafo: fontes (upload/text) → o nó testado. feeds: {porta: [chave_da_fonte, ...]} com chaves v, p1, p2, a1, a2, txt, txt2."""
        nodes = [{"id": "sut", "type": node_type, "x": 600, "y": 0, "params": params}]
        edges = []
        for port, keys in feeds.items():
            for k in keys:
                nid = "src_" + k
                if not any(n["id"] == nid for n in nodes):
                    if k.startswith("txt"):
                        nodes.append({"id": nid, "type": "text", "x": 0, "y": 0, "params": {"text": {"txt": "Uma floresta ao amanhecer. Névoa suave. Pássaros cantam.", "txt2": "segundo texto"}[k]}})
                    else:
                        nodes.append({"id": nid, "type": "upload", "x": 0, "y": 0, "params": {"files": [self.ids[k]]}})
                edges.append({"from": nid, "to": "sut", "port": port})
        cur = self.cs.save_layout(self.cid, {"nodes": nodes, "edges": edges})
        return cur

    def run_node(self, node_type, params, feeds):
        self.build(node_type, params, feeds)
        stats = CanvasEngine(self.store, self.cid, lambda e: None).run(["sut"], True)
        cur = self.cs.get(self.cid)
        node = next(n for n in cur["nodes"] if n["id"] == "sut")
        self.assertEqual(stats["errors"], 0, node["result"]["error"])
        self.assertEqual(node["result"]["state"], "done")
        assets = {a["id"]: a for a in cur["assets"]}
        return node["result"], [assets[i] for i in node["result"]["assets"]]

    # ---- Texto
    def test_text_nodes(self):
        r, _ = self.run_node("text_template", {"template": "Cena: {1} / {2} / {todos}"}, {"vars": ["txt", "txt2"]})
        self.assertTrue(r["text"].startswith("Cena: Uma floresta") and "/ segundo texto /" in r["text"])
        r, _ = self.run_node("text_join", {"sep": "custom", "custom": " | ", "numbering": True, "prefix": "[", "suffix": "]"}, {"texts": ["txt", "txt2"]})
        self.assertEqual(r["text"], "[1. Uma floresta ao amanhecer. Névoa suave. Pássaros cantam. | 2. segundo texto]")
        r, _ = self.run_node("text_edit", {"op": "upper"}, {"text": ["txt2"]})
        self.assertEqual(r["text"], "SEGUNDO TEXTO")
        r, _ = self.run_node("text_edit", {"op": "replace", "find": "segundo", "replace": "terceiro"}, {"text": ["txt2"]})
        self.assertEqual(r["text"], "terceiro texto")
        r, _ = self.run_node("text_pick", {"mode": "sentences", "index": 2, "count": 1}, {"text": ["txt"]})
        self.assertEqual(r["text"], "Névoa suave.")
        r, _ = self.run_node("text_pick", {"mode": "words", "random": True, "count": 2, "seed": 7}, {"text": ["txt"]})
        self.assertEqual(len(r["text"].split()), 2)
        r, _ = self.run_node("text_refine", {"mode": "scenes"}, {"text": ["txt"]})  # sem IA (demo): versão simples
        self.assertIn("Cena 1: Uma floresta ao amanhecer.", r["text"])
        self.assertTrue(r.get("error") == "")

    def test_text_refine_calls_the_text_model_when_one_is_configured(self):
        self.store.save_settings({"active": {"generation": "openai"}})

        class P:
            def chat(self, messages, system="", **kw):
                self.msg = messages[0]["content"]
                return "A forest at dawn, soft mist."
        prov = P()
        self.build("text_refine", {"mode": "translate", "language": "inglês"}, {"text": ["txt"]})
        with mock.patch("openflow.canvas.nodes_ext.build_provider", return_value=prov):
            CanvasEngine(self.store, self.cid, lambda e: None).run(["sut"], True)
        node = next(n for n in self.cs.get(self.cid)["nodes"] if n["id"] == "sut")
        self.assertEqual(node["result"]["text"], "A forest at dawn, soft mist.")
        self.assertIn("inglês", prov.msg)

    # ---- Imagem
    def test_image_nodes(self):
        _, a = self.run_node("img_resize", {"width": 100, "height": 100, "mode": "cover", "rotate": 90, "flip": "h"}, {"image": ["p1"]})
        self.assertEqual((a[0]["kind"], a[0]["w"], a[0]["h"]), ("image", 100, 100))
        _, a = self.run_node("img_resize", {"width": 150, "height": 0}, {"image": ["p2"]})
        self.assertEqual(a[0]["w"], 150)
        self.assertAlmostEqual(a[0]["h"], 225, delta=1)  # só a largura: mantém a proporção (altura par)
        _, a = self.run_node("img_filter", {"preset": "bw", "brightness": 0.1}, {"image": ["p1"]})
        self.assertEqual(a[0]["kind"], "image")
        _, a = self.run_node("img_text", {"text": "Olá"}, {"image": ["p1"], "text": ["txt2"]})
        self.assertEqual(a[0]["kind"], "image")
        r, a = self.run_node("img_collage", {"cols": 2, "cell": 128, "gap": 4}, {"images": ["p1", "p2", "v"]})  # inclui um vídeo (quadro dele)
        self.assertEqual((a[0]["w"], a[0]["h"]), (2 * 128 + 4, 2 * 128 + 4))
        _, a = self.run_node("img_frame", {"count": 3}, {"video": ["v"]})
        self.assertEqual([x["kind"] for x in a], ["image"] * 3)
        _, a = self.run_node("img_resize", {"width": 64, "height": 64}, {"image": ["v"]})  # vídeo numa porta de imagem: quadro do meio
        self.assertEqual((a[0]["kind"], a[0]["w"]), ("image", 64) if a[0]["w"] == 64 else ("image", a[0]["w"]))

    # ---- Vídeo
    def test_video_nodes(self):
        _, a = self.run_node("vid_trim", {"start": 1, "duration": 2}, {"video": ["v"]})
        self.assertAlmostEqual(a[0]["duration"], 2, delta=0.4)
        _, a = self.run_node("vid_join", {"width": 320, "height": 240, "image_seconds": 1, "fade": 0.1}, {"clips": ["v", "p1"]})
        self.assertAlmostEqual(a[0]["duration"], 5, delta=0.6)
        _, a = self.run_node("vid_speed", {"factor": 2, "reverse": True}, {"video": ["v"]})
        self.assertAlmostEqual(a[0]["duration"], 2, delta=0.5)
        _, a = self.run_node("vid_look", {"preset": "vhs", "fade_in": 0.3, "fade_out": 0.3}, {"video": ["v"]})
        self.assertAlmostEqual(a[0]["duration"], 4, delta=0.5)
        _, a = self.run_node("vid_slideshow", {"seconds": 1.5, "width": 320, "height": 240}, {"images": ["p1", "p2"], "audio": ["a1"]})
        self.assertAlmostEqual(a[0]["duration"], 3, delta=0.5)

    # ---- Som
    def test_sound_nodes(self):
        _, a = self.run_node("aud_trim", {"start": 0.5, "duration": 1, "fade_out": 0.2}, {"audio": ["a1"]})
        self.assertAlmostEqual(a[0]["duration"], 1, delta=0.3)
        _, a = self.run_node("aud_mix", {"mode": "sequence"}, {"audios": ["a1", "a2"]})
        self.assertAlmostEqual(a[0]["duration"], 5, delta=0.4)
        _, a = self.run_node("aud_mix", {"mode": "mix"}, {"audios": ["a1", "a2"]})
        self.assertAlmostEqual(a[0]["duration"], 3, delta=0.4)
        for fx in nodes_ext.AUD_FX:
            _, a = self.run_node("aud_fx", {"fx": fx}, {"audio": ["a1"]})
            self.assertEqual(a[0]["kind"], "audio", fx)
        _, a = self.run_node("aud_from_video", {"format": "wav"}, {"video": ["v"]})
        self.assertEqual((a[0]["kind"], a[0]["mime"]), ("audio", "audio/wav"))
        _, a = self.run_node("aud_loop", {"duration": 7, "fade_out": 0.5}, {"audio": ["a2"]})
        self.assertAlmostEqual(a[0]["duration"], 7, delta=0.4)

    # ---- Input
    def test_input_nodes(self):
        _, a = self.run_node("in_color", {"color": "#ff0000", "width": 64, "height": 32}, {})
        self.assertEqual((a[0]["w"], a[0]["h"]), (64, 32))
        _, a = self.run_node("in_color", {"color": "#000000", "color2": "#ffffff", "gradient": "vertical", "width": 64, "height": 64}, {})
        self.assertEqual(a[0]["kind"], "image")
        _, a = self.run_node("in_silence", {"seconds": 2}, {})
        self.assertAlmostEqual(a[0]["duration"], 2, delta=0.3)
        r, _ = self.run_node("in_random", {"lines": "a\nb\nc", "count": 2, "seed": 3, "joiner": "comma"}, {})
        self.assertEqual(len(r["text"].split(", ")), 2)
        r2, _ = self.run_node("in_random", {"lines": "a\nb\nc", "count": 2, "seed": 3, "joiner": "comma"}, {})
        self.assertEqual(r["text"], r2["text"])  # mesma semente, mesmo sorteio
        r, _ = self.run_node("in_vars", {"template": "{projeto} · {ano} · {x}"}, {})
        self.assertTrue(r["text"].startswith("Projeto X · 20") and r["text"].endswith("· {x}"))

    def test_url_node_refuses_private_addresses_and_downloads_public_media(self):
        self.build("in_url", {"url": "http://127.0.0.1:1/x.png"}, {})
        stats = CanvasEngine(self.store, self.cid, lambda e: None).run(["sut"], True)
        node = next(n for n in self.cs.get(self.cid)["nodes"] if n["id"] == "sut")
        self.assertEqual(stats["errors"], 1)
        self.assertIn("públicos", node["result"]["error"])
        import io

        class Resp(io.BytesIO):
            headers = {"Content-Type": "image/png"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        png = (self.m / "p1.png").read_bytes()
        self.build("in_url", {"url": "https://exemplo.test/foto.png"}, {})
        with mock.patch("openflow.websearch.safe_url", return_value=True), mock.patch("openflow.websearch._OPENER.open", return_value=Resp(png)):
            stats = CanvasEngine(self.store, self.cid, lambda e: None).run(["sut"], True)
        self.assertEqual(stats["errors"], 0)
        cur = self.cs.get(self.cid)
        node = next(n for n in cur["nodes"] if n["id"] == "sut")
        self.assertEqual(next(a for a in cur["assets"] if a["id"] == node["result"]["assets"][0])["kind"], "image")

    # ---- Output
    def test_output_nodes(self):
        r, a = self.run_node("out_export", {"quality": "480p", "burn": True}, {"video": ["v"], "audio": ["a1"], "captions": ["txt2"]})
        self.assertEqual(a[0]["kind"], "video")
        self.assertAlmostEqual(a[0]["duration"], 4, delta=0.6)
        _, a = self.run_node("out_export", {"quality": "480p", "image_seconds": 2}, {"video": ["p1"], "audio": ["a1"]})  # imagem + áudio → vídeo
        self.assertAlmostEqual(a[0]["duration"], 2, delta=0.5)
        _, a = self.run_node("out_gif", {"width": 160, "fps": 8, "max_seconds": 2}, {"video": ["v"]})
        self.assertEqual((a[0]["kind"], a[0]["mime"]), ("image", "image/gif"))
        _, a = self.run_node("out_audio", {"format": "m4a", "mode": "sequence"}, {"audio": ["a1", "a2"]})
        self.assertEqual((a[0]["kind"], a[0]["mime"]), ("audio", "audio/mp4"))
        for fmt in ("png", "jpg", "webp"):
            _, a = self.run_node("out_image", {"format": fmt, "max_width": 100}, {"image": ["p1"]})
            self.assertEqual((a[0]["kind"], a[0]["w"]), ("image", 100), fmt)
        r, a = self.run_node("out_gallery", {}, {"items": ["p1", "v", "a1", "txt"]})
        self.assertEqual({x["kind"] for x in a}, {"image", "video", "audio"})
        self.assertIn("Uma floresta", r["text"])

    def test_missing_inputs_explain_what_to_connect(self):
        for t, port in (("img_resize", "image"), ("vid_trim", "video"), ("aud_trim", "audio"), ("out_export", "video"), ("text_edit", "text")):
            self.build(t, {}, {})
            stats = CanvasEngine(self.store, self.cid, lambda e: None).run(["sut"], True)
            node = next(n for n in self.cs.get(self.cid)["nodes"] if n["id"] == "sut")
            self.assertEqual((stats["errors"], "«" in node["result"]["error"] or port in node["result"]["error"]), (1, True), t)
            self.assertNotIn("«video»", node["result"]["error"] + "«text»")

    # ---- integração: cadeia que mistura nós antigos e novos de todos os tipos
    def test_a_chain_across_all_types_runs_and_caches(self):
        nodes = [
            {"id": "t", "type": "text", "params": {"text": "Uma floresta ao amanhecer"}},
            {"id": "r", "type": "text_refine", "params": {"mode": "improve"}},
            {"id": "img", "type": "image", "params": {"size": "512x512"}},
            {"id": "flt", "type": "img_filter", "params": {"preset": "sepia"}},
            {"id": "show", "type": "vid_slideshow", "params": {"seconds": 1.2, "width": 320, "height": 240}},
            {"id": "sil", "type": "in_silence", "params": {"seconds": 2}},
            {"id": "fx", "type": "aud_fx", "params": {"fx": "echo"}},
            {"id": "out", "type": "out_export", "params": {"quality": "480p"}},
            {"id": "gal", "type": "out_gallery", "params": {}},
            {"id": "fr", "type": "img_frame", "params": {}},
        ]
        edges = [
            {"from": "t", "to": "r", "port": "text"}, {"from": "r", "to": "img", "port": "prompt"}, {"from": "img", "to": "flt", "port": "image"},
            {"from": "flt", "to": "show", "port": "images"}, {"from": "sil", "to": "fx", "port": "audio"}, {"from": "fx", "to": "show", "port": "audio"},
            {"from": "show", "to": "out", "port": "video"}, {"from": "fx", "to": "out", "port": "audio"}, {"from": "r", "to": "out", "port": "captions"},
            {"from": "show", "to": "fr", "port": "video"}, {"from": "fr", "to": "gal", "port": "items"}, {"from": "out", "to": "gal", "port": "items"},
        ]
        cur = self.cs.save_layout(self.cid, {"nodes": [{"x": 0, "y": 0, **n} for n in nodes], "edges": edges})
        self.assertEqual(len(cur["edges"]), len(edges))  # todas as conexões entre tipos diferentes foram aceitas
        stats = CanvasEngine(self.store, self.cid, lambda e: None).run()
        self.assertEqual(stats["errors"], 0, [n["result"]["error"] for n in self.cs.get(self.cid)["nodes"] if n["result"]["error"]])
        cur = self.cs.get(self.cid)
        gal = next(n for n in cur["nodes"] if n["id"] == "gal")
        kinds = sorted(next(a for a in cur["assets"] if a["id"] == i)["kind"] for i in gal["result"]["assets"])
        self.assertEqual(kinds, ["image", "video"])
        again = CanvasEngine(self.store, self.cid, lambda e: None).run()
        self.assertEqual(again["ran"], 0)
        # mudar o texto de entrada refaz a cadeia que depende dele
        self.cs.patch_node_params(self.cid, "t", {"text": "Um castelo na neve"})
        stale = set(CanvasEngine(self.store, self.cid).stale_ids(self.cs.get(self.cid)))
        self.assertTrue({"r", "img", "flt", "show", "out", "gal", "fr"} <= stale)
        self.assertNotIn("sil", stale)


if __name__ == "__main__":
    unittest.main()
