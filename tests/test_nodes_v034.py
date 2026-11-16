"""v0.34: 10 nós novos no canvas (Texto, Imagem, Vídeo, Som, Input, Output) — cada um roda de verdade (ffmpeg) e é conferido."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from openflow.canvas import nodes_ext, schema
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
NEW = ["text_extract", "text_count", "img_crop", "img_watermark", "vid_reframe", "vid_loop", "vid_audio", "aud_silence_cut", "in_pattern", "out_thumbnail"]


def probe(path: Path):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,duration", "-of", "json", str(path)], capture_output=True, text=True).stdout
    return {s["codec_type"]: s for s in json.loads(o)["streams"]}


class SpecTests(unittest.TestCase):
    def test_the_ten_new_nodes_are_registered_everywhere(self):
        for k in NEW:
            self.assertIn(k, nodes_ext.SPECS, k)
            self.assertIn(k, nodes_ext.RUNNERS, k)
            self.assertIn(k, schema.NODE_TYPES, k)
            self.assertIsInstance(schema.normalize_params(k, {}), dict)
        listed = [t for _, ts in schema.PALETTE for t in ts]
        self.assertTrue(all(k in listed for k in NEW))

    def test_parameters_are_clamped(self):
        n = schema.normalize_params
        self.assertEqual(n("vid_loop", {"times": 999})["times"], 20)
        self.assertEqual(n("aud_silence_cut", {"threshold": 0})["threshold"], -15)
        self.assertEqual(n("img_crop", {"ratio": "5:7"})["ratio"], "1:1")
        self.assertEqual(n("in_pattern", {"kind": "x", "color": "vermelho"})["color"], "#202530")
        self.assertEqual(n("img_watermark", {"opacity": 5})["opacity"], 1)

    def test_every_new_node_is_in_the_javascript_lists(self):
        js = (Path(__file__).resolve().parent.parent / "openflow" / "web" / "js" / "canvas_nodes.js").read_text(encoding="utf-8")
        for k in NEW:
            self.assertGreaterEqual(js.count(k), 3, k)        # grupo, ajuda/rótulo e formulário


@unittest.skipUnless(FF, "sem ffmpeg")
class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("novos")["id"]
        cls.video = cls.add(cls.ff("v.mp4", ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]), "video", "video/mp4")
        cls.silent = cls.add(cls.ff("mudo.mp4", ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p"]), "video", "video/mp4")
        cls.music = cls.add(cls.ff("m.mp3", ["-f", "lavfi", "-i", "sine=frequency=880:duration=5", "-c:a", "libmp3lame"]), "audio", "audio/mpeg")
        # fala (tom) – silêncio de 1 s – tom: para tirar silêncios
        cls.gappy = cls.add(cls.ff("g.mp3", ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-f", "lavfi", "-i", "sine=frequency=660:duration=1",
                                             "-filter_complex", "[1:a]atrim=duration=1[s];[0:a][s][2:a]concat=n=3:v=0:a=1[a]", "-map", "[a]", "-c:a", "libmp3lame"]), "audio", "audio/mpeg")
        from PIL import Image

        im = cls.tmp / "foto.png"
        Image.new("RGB", (800, 400), "orange").save(im)
        cls.photo = cls.add(im, "image", "image/png")
        lg = cls.tmp / "logo.png"
        Image.new("RGBA", (100, 50), (0, 0, 255, 255)).save(lg)
        cls.logo = cls.add(lg, "image", "image/png")

    @classmethod
    def ff(cls, name, args):
        p = cls.tmp / name
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(p)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-300:]
        return p

    @classmethod
    def add(cls, path, kind, mime):
        return cls.cs.add_asset(cls.cid, path.read_bytes(), path.suffix.lstrip("."), kind, name=path.name, mime=mime, provider="upload")

    def run_graph(self, nodes, edges):
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": edges})
        ev = []
        CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        return ev

    def up(self, nid, *assets):
        return {"id": nid, "type": "upload", "x": 0, "y": 0, "params": {"files": [a["id"] for a in assets]}}

    def node(self, ntype, params=None, nid="x"):
        return {"id": nid, "type": ntype, "x": 0, "y": 0, "params": params or {}}

    def result(self, ev, nid="x"):
        errs = [e for e in ev if e.get("type") == "node" and e.get("id") == nid and e.get("state") == "error"]
        self.assertEqual(errs, [], errs)
        done = [e for e in ev if e.get("type") == "node" and e.get("id") == nid and (e.get("assets") or e.get("text"))]
        self.assertTrue(done, "sem resultado")
        last = done[-1]
        files = [next(a for a in self.cs.get(self.cid)["assets"] if a["id"] == i) for i in last.get("assets", [])]
        return last.get("text", ""), files

    def probe_of(self, asset):
        return probe(self.cs.asset_path(self.cid, asset["file"]))

    def error_of(self, ev, nid="x"):
        return " ".join((e.get("message") or "") for e in ev if e.get("type") == "node" and e.get("id") == nid and e.get("state") == "error")

    def text_in(self, text):
        return {"id": "t", "type": "text", "x": 0, "y": 0, "params": {"text": text}}

    # ------------------------------------------------------------------ texto
    def test_text_extract(self):
        src = "Veja https://a.com/x e http://b.org, escreva para ana@ex.com ou bob@ex.org. #luz #Sombra 12 e 3,5 \"uma frase\" e AAA"
        for what, want in (("links", ["https://a.com/x", "http://b.org"]), ("emails", ["ana@ex.com", "bob@ex.org"]), ("hashtags", ["#luz", "#Sombra"]), ("numbers", ["12", "3,5"]), ("quotes", ["uma frase"]), ("words_caps", ["AAA"])):
            text, _ = self.result(self.run_graph([self.text_in(src), self.node("text_extract", {"what": what})], [{"from": "t", "to": "x", "port": "text"}]))
            self.assertEqual([x for x in text.splitlines()][: len(want)], want, what)
        text, _ = self.result(self.run_graph([self.text_in("a1 b22 c333"), self.node("text_extract", {"what": "regex", "pattern": r"[a-z](\d+)", "joiner": "comma"})], [{"from": "t", "to": "x", "port": "text"}]))
        self.assertEqual(text, "1, 22, 333")
        text, _ = self.result(self.run_graph([self.text_in("1 2 3 4 5"), self.node("text_extract", {"what": "numbers", "limit": 2, "joiner": "space"})], [{"from": "t", "to": "x", "port": "text"}]))
        self.assertEqual(text, "1 2")

    def test_text_extract_errors_are_friendly(self):
        e = [{"from": "t", "to": "x", "port": "text"}]
        self.assertIn("Padrão", self.error_of(self.run_graph([self.text_in("abc"), self.node("text_extract", {"what": "regex"})], e)))
        self.assertIn("inválido", self.error_of(self.run_graph([self.text_in("abc"), self.node("text_extract", {"what": "regex", "pattern": "(["})], e)))
        self.assertIn("travar", self.error_of(self.run_graph([self.text_in("aaa"), self.node("text_extract", {"what": "regex", "pattern": "(a+)+$"})], e)))
        self.assertIn("nada", self.error_of(self.run_graph([self.text_in("sem links"), self.node("text_extract", {"what": "links"})], e)))

    def test_text_count(self):
        e = [{"from": "t", "to": "x", "port": "text"}]
        text, _ = self.result(self.run_graph([self.text_in("um dois\ntrês"), self.node("text_count")], e))
        self.assertEqual(text, "3 palavras · 12 caracteres · 2 linhas")
        text, _ = self.result(self.run_graph([self.text_in("um dois\ntrês"), self.node("text_count", {"what": "words"})], e))
        self.assertEqual(text, "3")

    # ------------------------------------------------------------------ imagem
    def test_img_crop_ratio_and_manual(self):
        e = [{"from": "src", "to": "x", "port": "image"}]
        _, f = self.result(self.run_graph([self.up("src", self.photo), self.node("img_crop", {"ratio": "1:1"})], e))
        self.assertEqual((f[0]["w"], f[0]["h"]), (400, 400))                                  # 800×400 → quadrado pela altura
        _, f = self.result(self.run_graph([self.up("src", self.photo), self.node("img_crop", {"ratio": "9:16"})], e))
        self.assertEqual((f[0]["w"], f[0]["h"]), (225, 400))
        _, f = self.result(self.run_graph([self.up("src", self.photo), self.node("img_crop", {"mode": "manual", "x": 50, "y": 0, "w": 50, "h": 50})], e))
        self.assertEqual((f[0]["w"], f[0]["h"]), (400, 200))

    def test_img_watermark_changes_the_corner_only(self):
        from PIL import Image
        import io

        e = [{"from": "src", "to": "x", "port": "image"}, {"from": "lg", "to": "x", "port": "logo"}]
        _, f = self.result(self.run_graph([self.up("src", self.photo), self.up("lg", self.logo), self.node("img_watermark", {"pos": "br", "scale": 25, "opacity": 1, "margin": 2})], e))
        im = Image.open(io.BytesIO(self.cs.asset_path(self.cid, f[0]["file"]).read_bytes())).convert("RGB")
        self.assertEqual((im.width, im.height), (800, 400))
        self.assertTrue(all(abs(a - b) <= 3 for a, b in zip(im.getpixel((5, 5)), (255, 165, 0))))                                  # canto de cima continua laranja
        br = im.getpixel((int(800 * 0.92), int(400 * 0.9)))
        self.assertGreater(br[2], 150)                                                        # o canto de baixo recebeu a marca azul
        self.assertIn("marca", self.error_of(self.run_graph([self.up("src", self.photo), self.node("img_watermark")], e[:1])))

    # ------------------------------------------------------------------ vídeo
    def test_vid_reframe_modes(self):
        e = [{"from": "src", "to": "x", "port": "video"}]
        for mode in ("blur", "cover", "pad"):
            _, f = self.result(self.run_graph([self.up("src", self.video), self.node("vid_reframe", {"ratio": "9:16", "mode": mode, "height": 640})], e))
            pr = self.probe_of(f[0])
            self.assertEqual((int(pr["video"]["width"]), int(pr["video"]["height"])), (360, 640), mode)
            self.assertIn("audio", pr, mode)
        _, f = self.result(self.run_graph([self.up("src", self.silent), self.node("vid_reframe", {"ratio": "1:1", "mode": "blur", "height": 480})], e))
        pr = self.probe_of(f[0])
        self.assertEqual((int(pr["video"]["width"]), int(pr["video"]["height"])), (480, 480))
        self.assertNotIn("audio", pr)                                                         # sem som continua sem som

    def test_vid_loop(self):
        e = [{"from": "src", "to": "x", "port": "video"}]
        _, f = self.result(self.run_graph([self.up("src", self.silent), self.node("vid_loop", {"times": 3})], e))
        self.assertAlmostEqual(float(self.probe_of(f[0])["video"]["duration"]), 3.0, delta=0.2)
        _, f = self.result(self.run_graph([self.up("src", self.silent), self.node("vid_loop", {"duration": 2.5})], e))
        self.assertAlmostEqual(float(self.probe_of(f[0])["video"]["duration"]), 2.5, delta=0.2)

    def test_vid_audio_replace_mix_and_mute(self):
        e = [{"from": "src", "to": "x", "port": "video"}, {"from": "mu", "to": "x", "port": "audio"}]
        nodes = lambda v, p: [self.up("src", v), self.up("mu", self.music), self.node("vid_audio", p)]  # noqa: E731
        _, f = self.result(self.run_graph(nodes(self.silent, {"mode": "replace"}), e))                 # vídeo mudo ganha a música, no tamanho do vídeo
        pr = self.probe_of(f[0])
        self.assertIn("audio", pr)
        self.assertAlmostEqual(float(pr["video"]["duration"]), 1.0, delta=0.2)
        self.assertLess(float(pr["audio"]["duration"]), 1.3)
        _, f = self.result(self.run_graph(nodes(self.video, {"mode": "mix", "volume": 0.5}), e))
        self.assertIn("audio", self.probe_of(f[0]))
        _, f = self.result(self.run_graph([self.up("src", self.video), self.node("vid_audio", {"mode": "mute"})], e[:1]))
        self.assertNotIn("audio", self.probe_of(f[0]))
        self.assertIn("áudio", self.error_of(self.run_graph([self.up("src", self.video), self.node("vid_audio", {"mode": "replace"})], e[:1])))

    # ------------------------------------------------------------------ som
    def test_aud_silence_cut_shortens_the_gap(self):
        e = [{"from": "src", "to": "x", "port": "audio"}]
        _, f = self.result(self.run_graph([self.up("src", self.gappy), self.node("aud_silence_cut", {"threshold": -40, "min_silence": 0.3, "keep": 0.1})], e))
        self.assertLess(f[0]["duration"], 2.6)                                                # 3 s com 1 s de silêncio no meio
        self.assertGreater(f[0]["duration"], 1.8)
        self.assertIn("vazio", self.error_of(self.run_graph([self.up("src", self.gappy), self.node("aud_silence_cut", {"threshold": -15})], e)))   # (v0.52) antes passava sem erro: `or "vazio"` escondia que o nó salvava um áudio de 0 s

    # ------------------------------------------------------------------ input e output
    def test_in_pattern_all_kinds(self):
        for kind in ("checker", "stripes", "noise", "grid", "dots"):
            _, f = self.result(self.run_graph([self.node("in_pattern", {"kind": kind, "width": 128, "height": 96, "size": 16})], []))
            self.assertEqual((f[0]["w"], f[0]["h"]), (128, 96), kind)

    def test_in_pattern_checker_really_alternates(self):
        from PIL import Image
        import io

        _, f = self.result(self.run_graph([self.node("in_pattern", {"kind": "checker", "color": "#000000", "color2": "#ffffff", "width": 64, "height": 64, "size": 16})], []))
        im = Image.open(io.BytesIO(self.cs.asset_path(self.cid, f[0]["file"]).read_bytes())).convert("L")
        self.assertEqual((im.getpixel((2, 2)), im.getpixel((18, 2)), im.getpixel((18, 18))), (0, 255, 0))

    def test_out_thumbnail(self):
        e = [{"from": "src", "to": "x", "port": "image"}, {"from": "t", "to": "x", "port": "text"}]
        for layout in ("bottom", "center", "left"):
            _, f = self.result(self.run_graph([self.up("src", self.photo), self.text_in("Meu título muito legal"), self.node("out_thumbnail", {"layout": layout})], e))
            self.assertEqual((f[0]["w"], f[0]["h"], f[0]["mime"]), (1280, 720, "image/jpeg"), layout)
        _, f = self.result(self.run_graph([self.up("src", self.photo), self.node("out_thumbnail", {"format": "png", "width": 640, "height": 360})], e[:1]))   # sem título também vale
        self.assertEqual((f[0]["w"], f[0]["h"]), (640, 360))
