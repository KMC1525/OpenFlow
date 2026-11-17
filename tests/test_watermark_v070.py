"""v0.70: o nó Marca d'água também REMOVE marcas d'água de imagens e vídeos (ffmpeg `delogo`/`removelogo`), com a área escolhida num canto, numa caixa em %, achada sozinha no vídeo ou dada por uma máscara.

O ffmpeg e o numpy são reais; as imagens e os vídeos são sintéticos (marca branca sobre fundo liso ou sobre ruído em movimento). Que a remoção fique bonita em fotos e vídeos de verdade, com fundo cheio de detalhe,
NÃO é verificado: o `delogo` só refaz a área a partir dos pixels em volta, sem «adivinhar» o que havia por baixo."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from openflow.canvas import schema, watermark as wm
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
try:
    import numpy  # noqa: F401
    from PIL import Image, ImageDraw
    DEPS = True
except ImportError:
    DEPS = False


class GeometryTests(unittest.TestCase):
    def test_corner_box(self):
        self.assertEqual(wm.region("corner", "br", 20, 10, 0, 0, 3, 1000, 500), (770, 435, 200, 50))
        self.assertEqual(wm.region("corner", "tl", 20, 10, 0, 0, 3, 1000, 500), (30, 15, 200, 50))
        self.assertEqual(wm.region("corner", "center", 20, 10, 0, 0, 0, 1000, 500), (400, 225, 200, 50))

    def test_box_in_percent(self):
        self.assertEqual(wm.region("box", "br", 10, 10, 50, 40, 3, 1000, 500), (500, 200, 100, 50))

    def test_it_never_touches_the_border(self):
        x, y, w, h = wm.region("corner", "br", 30, 30, 0, 0, 0, 100, 100)
        self.assertLessEqual(x + w, 99)
        self.assertLessEqual(y + h, 99)
        self.assertGreaterEqual(wm.fit(-5, -5, 10, 10, 100, 100)[0], 1)
        self.assertEqual(wm.fit(0, 0, 500, 500, 100, 100), (1, 1, 98, 98))

    def test_filters(self):
        self.assertEqual(wm.delogo_filter((10, 20, 30, 40)), "delogo=x=10:y=20:w=30:h=40")
        self.assertEqual(wm.removelogo_filter(Path("C:\\a b\\m.png")), "removelogo=filename=C\\:/a b/m.png")


class SchemaTests(unittest.TestCase):
    def test_params_and_ports(self):
        d = schema.normalize_params("img_watermark", {})
        self.assertEqual((d["mode"], d["where"], d["rm_w"], d["rm_h"]), ("add", "corner", 22, 10))          # sem mexer, o nó segue pondo a marca
        d = schema.normalize_params("img_watermark", {"mode": "remove", "where": "auto", "rm_w": 999, "rm_x": -3})
        self.assertEqual((d["mode"], d["where"], d["rm_w"], d["rm_x"]), ("remove", "auto", 100, 0))
        self.assertEqual(schema.normalize_params("img_watermark", {"mode": "x", "where": "y"})["mode"], "add")
        self.assertIsNotNone(schema.port_def("img_watermark", "mask"))
        self.assertTrue(schema.compatible("media", schema.port_def("img_watermark", "image")["accepts"]))
        self.assertTrue(schema.compatible(schema.NODE_TYPES["img_watermark"]["out"], schema.port_def("vid_loop", "video")["accepts"]))   # a saída agora pode ser um vídeo


@unittest.skipUnless(FF and DEPS, "sem ffmpeg/numpy/PIL")
class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("marca")["id"]
        cls.logo_png = cls.tmp / "logo.png"
        lg = Image.new("RGBA", (120, 36), (0, 0, 0, 0))
        d = ImageDraw.Draw(lg)
        for i in range(6):
            d.rectangle([4 + i * 19, 6, 14 + i * 19, 30], fill=(255, 255, 255, 255))
        d.rectangle([0, 0, 119, 35], outline=(255, 255, 255, 255), width=2)
        lg.save(cls.logo_png)
        # foto: fundo laranja liso 800x400 com a marca branca embaixo à direita
        bg = Image.new("RGB", (800, 400), (255, 165, 0))
        bg.paste(lg, (800 - 120 - 20, 400 - 36 - 16), lg)
        cls.photo_file = cls.tmp / "foto.png"
        bg.save(cls.photo_file)
        cls.photo = cls.add(cls.photo_file, "image", "image/png")
        cls.plain = cls.tmp / "liso.png"
        Image.new("RGB", (800, 400), (255, 165, 0)).save(cls.plain)
        # vídeo: ruído em movimento + marca no canto de baixo à direita, com som
        cls.video_file = cls.tmp / "v.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "nullsrc=s=640x360:r=12:d=3,geq=random(1)*255:128:128", "-i", str(cls.logo_png), "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                        "-filter_complex", "[0][1]overlay=W-w-20:H-h-16,format=yuv420p[v]", "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(cls.video_file)], check=True)
        cls.video = cls.add(cls.video_file, "video", "video/mp4")
        # vídeo parado (sem como achar a marca)
        cls.still_file = cls.tmp / "parado.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(cls.photo_file), "-t", "3", "-r", "12", "-pix_fmt", "yuv420p", "-vf", "scale=640:320", str(cls.still_file)], check=True)
        cls.still = cls.add(cls.still_file, "video", "video/mp4")
        # máscara: branco só em cima da marca da foto
        m = Image.new("L", (800, 400), 0)
        ImageDraw.Draw(m).rectangle([800 - 120 - 24, 400 - 36 - 20, 800 - 20 + 4, 400 - 16 + 4], fill=255)
        cls.mask_file = cls.tmp / "mask.png"
        m.save(cls.mask_file)
        cls.mask = cls.add(cls.mask_file, "image", "image/png")

    @classmethod
    def add(cls, path, kind, mime):
        return cls.cs.add_asset(cls.cid, path.read_bytes(), path.suffix.lstrip("."), kind, name=path.name, mime=mime, provider="upload")

    def run_node(self, source, params, mask=None):
        nodes = [{"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [source["id"]]}}, {"id": "x", "type": "img_watermark", "x": 0, "y": 0, "params": {"mode": "remove", **params}}]
        edges = [{"from": "u", "to": "x", "port": "image"}]
        if mask:
            nodes.append({"id": "m", "type": "upload", "x": 0, "y": 0, "params": {"files": [mask["id"]]}})
            edges.append({"from": "m", "to": "x", "port": "mask"})
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": edges})
        ev = []
        CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        err = [e.get("message") for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("state") == "error"]
        done = [e for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("assets")]
        warns = [w for e in ev if e.get("type") == "node" and e.get("id") == "x" for w in e.get("warnings", [])]
        asset = next(a for a in self.cs.get(self.cid)["assets"] if a["id"] == done[-1]["assets"][0]) if done else None
        return err, asset, warns

    def image(self, asset):
        return Image.open(self.cs.asset_path(self.cid, asset["file"])).convert("RGB")

    def bright(self, im, box):
        crop = im.crop(box)
        raw = crop.tobytes()
        return max(sum(raw[i:i + 3]) for i in range(0, len(raw), 3))

    LOGO_BOX = (800 - 120 - 20, 400 - 36 - 16, 800 - 20, 400 - 16)

    def test_image_corner_removes_the_mark(self):
        before = self.bright(Image.open(self.photo_file).convert("RGB"), self.LOGO_BOX)
        self.assertEqual(before, 765)                                                      # a marca branca está lá
        err, asset, _ = self.run_node(self.photo, {"where": "corner", "pos": "br", "rm_w": 20, "rm_h": 12, "margin": 2})
        self.assertEqual(err, [])
        self.assertEqual(asset["kind"], "image")
        im = self.image(asset)
        self.assertEqual(im.size, (800, 400))
        self.assertLess(self.bright(im, self.LOGO_BOX), 600)                                # o branco sumiu: o miolo da marca ficou da cor do fundo
        self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(im.getpixel((10, 10)), (255, 165, 0))))   # o resto da foto não mudou

    def test_image_box_in_percent(self):
        err, asset, _ = self.run_node(self.photo, {"where": "box", "rm_x": 80, "rm_y": 85, "rm_w": 18, "rm_h": 12})
        self.assertEqual(err, [])
        self.assertLess(self.bright(self.image(asset), self.LOGO_BOX), 600)

    def test_image_with_a_mask(self):
        err, asset, _ = self.run_node(self.photo, {}, mask=self.mask)
        self.assertEqual(err, [])
        self.assertLess(self.bright(self.image(asset), self.LOGO_BOX), 600)

    def test_automatic_needs_a_video(self):
        err, asset, _ = self.run_node(self.photo, {"where": "auto"})
        self.assertTrue(err and "só funciona em vídeo" in err[0])

    def test_video_corner_keeps_size_sound_and_removes_the_mark(self):
        err, asset, _ = self.run_node(self.video, {"where": "corner", "pos": "br", "rm_w": 22, "rm_h": 14, "margin": 3})
        self.assertEqual(err, [])
        self.assertEqual(asset["kind"], "video")
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(self.cs.asset_path(self.cid, asset["file"]))], capture_output=True, text=True).stdout)
        kinds = {s["codec_type"]: s for s in info["streams"]}
        self.assertEqual((int(kinds["video"]["width"]), int(kinds["video"]["height"])), (640, 360))
        self.assertIn("audio", kinds)                                                       # o som continua

    def test_video_auto_finds_the_mark(self):
        err, asset, warns = self.run_node(self.video, {"where": "auto"})
        self.assertEqual(err, [])
        self.assertEqual(asset["kind"], "video")
        self.assertTrue(any("Marca encontrada" in w for w in warns))
        frames = wm.sample_frames(self.cs.asset_path(self.cid, asset["file"]), 3, 640, 360)
        before = wm.sample_frames(self.video_file, 3, 640, 360)
        self.assertGreater(wm.detect(before, 640, 360)[0] is not None, 0)                       # antes a marca era achada…
        self.assertIsNone(wm.detect(frames, 640, 360)[0])                                       # …depois de removida, não há mais marca fixa nos cantos

    def test_auto_says_so_when_the_video_does_not_move(self):
        err, asset, _ = self.run_node(self.still, {"where": "auto"})
        self.assertTrue(err and "quase não muda" in err[0])

    def test_detect_ignores_a_video_without_a_mark(self):
        import numpy as np

        rng = np.random.default_rng(1)
        frames = rng.integers(0, 255, (14, 270, 480)).astype("float32")
        box, why = wm.detect(frames, 640, 360)
        self.assertIsNone(box)
        self.assertIn("não encontrei", why)

    def test_detect_finds_the_corner_of_the_synthetic_mark(self):
        frames = wm.sample_frames(self.video_file, 3, 640, 360)
        box, _ = wm.detect(frames, 640, 360)
        x, y, w, h = box
        self.assertTrue(x <= 505 and y <= 312 and x + w >= 615 and y + h >= 340, box)       # cobre a marca (500,308)–(620,344)
        self.assertLess(w * h, 640 * 360 * 0.08)                                            # sem exagerar na área

    def test_adding_still_works(self):
        nodes = [{"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [self.cs.get(self.cid)["assets"][0]["id"]]}}, {"id": "x", "type": "img_watermark", "x": 0, "y": 0, "params": {}}]
        lg = self.add(self.logo_png, "image", "image/png")
        nodes.append({"id": "l", "type": "upload", "x": 0, "y": 0, "params": {"files": [lg["id"]]}})
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": [{"from": "u", "to": "x", "port": "image"}, {"from": "l", "to": "x", "port": "logo"}]})
        ev = []
        CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        self.assertEqual([e for e in ev if e.get("type") == "node" and e.get("state") == "error"], [])


if __name__ == "__main__":
    unittest.main()
