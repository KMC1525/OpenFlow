"""v0.51: bugs ao editar imagens nos nós do Canvas — tamanhos automáticos em imagens muito estreitas, recortes de 0 px, desfoque em 1 px, e fotos com orientação EXIF / transparência / 16 bits como referência."""
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from openflow.canvas import media, nodes_ext
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def png(im, fmt="PNG", **kw):
    b = io.BytesIO()
    im.save(b, fmt, **kw)
    return b.getvalue()


class OpenRgbTests(unittest.TestCase):
    def test_transparent_pixels_become_white_not_the_hidden_color(self):
        self.assertEqual(media.open_rgb(png(Image.new("RGBA", (4, 4), (255, 0, 0, 0)))).getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(media.open_rgb(png(Image.new("RGBA", (4, 4), (255, 0, 0, 255)))).getpixel((0, 0)), (255, 0, 0))
        half = media.open_rgb(png(Image.new("RGBA", (4, 4), (0, 0, 0, 128)))).getpixel((0, 0))
        self.assertTrue(120 <= half[0] <= 135, half)
        p = Image.new("P", (4, 4), 0)
        self.assertEqual(media.open_rgb(png(p, transparency=0)).getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(media.open_rgb(png(Image.new("LA", (4, 4), (0, 0)))).getpixel((0, 0)), (255, 255, 255))

    def test_exif_orientation_is_applied(self):
        ex = Image.Exif()
        ex[0x0112] = 6
        self.assertEqual(media.open_rgb(png(Image.new("RGB", (200, 100), "blue"), "JPEG", exif=ex)).size, (100, 200))
        self.assertEqual(media.open_rgb(png(Image.new("RGB", (200, 100), "blue"), "JPEG")).size, (200, 100))

    def test_sixteen_bit_png_keeps_its_brightness(self):
        v = media.open_rgb(png(Image.new("I;16", (4, 4), 30000))).getpixel((0, 0))
        self.assertTrue(110 <= v[0] <= 125, v)          # 30000/65535 ≈ 46% → ~117 (antes: tudo branco)

    def test_other_modes_and_garbage(self):
        self.assertEqual(media.open_rgb(png(Image.new("CMYK", (4, 4)), "JPEG")).mode, "RGB")
        self.assertEqual(media.open_rgb(png(Image.new("L", (4, 4), 90))).getpixel((0, 0)), (90, 90, 90))
        with self.assertRaises(Exception):
            media.open_rgb(b"nao e imagem")
        self.assertEqual(media._pil_refs([(b"lixo", "image/png"), (png(Image.new("RGB", (2, 2))), "image/png")]).__len__(), 1)

    def test_clean_png_only_rewrites_when_needed(self):
        plain = png(Image.new("RGB", (5, 5), "red"))
        self.assertEqual(media.clean_png(plain), plain)
        out = Image.open(io.BytesIO(media.clean_png(png(Image.new("RGBA", (5, 5), (1, 2, 3, 0))))))
        self.assertEqual((out.mode, out.getpixel((0, 0))), ("RGB", (255, 255, 255)))
        ex = Image.Exif()
        ex[0x0112] = 6
        self.assertEqual(Image.open(io.BytesIO(media.clean_png(png(Image.new("RGB", (200, 100)), "JPEG", exif=ex)))).size, (100, 200))
        self.assertEqual(media.clean_png(b"lixo"), b"lixo")

    def test_difference_ignores_transparency_and_garbage(self):
        a = png(Image.new("RGBA", (8, 8), (255, 0, 0, 0)))
        self.assertEqual(media.image_difference(a, png(Image.new("RGB", (8, 8), "white"))), 0.0)
        self.assertIsNone(media.image_difference(b"x", a))


@unittest.skipUnless(FF, "sem ffmpeg")
class NodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("edit")["id"]
        cls.logo = cls.add(Image.new("RGBA", (100, 50), (0, 0, 255, 255)), "PNG", "logo.png")

    @classmethod
    def add(cls, im, fmt, name, **kw):
        ext = name.rsplit(".", 1)[1]
        return cls.cs.add_asset(cls.cid, png(im, fmt, **kw), ext, "image", name=name, mime="image/" + ("jpeg" if fmt == "JPEG" else fmt.lower()), provider="upload")

    def run_node(self, ntype, params, asset, port="image"):
        nodes = [{"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [asset["id"]]}}, {"id": "x", "type": ntype, "x": 0, "y": 0, "params": params}]
        edges = [{"from": "u", "to": "x", "port": port}]
        if ntype == "img_watermark":
            nodes.append({"id": "l", "type": "upload", "x": 0, "y": 0, "params": {"files": [self.logo["id"]]}})
            edges.append({"from": "l", "to": "x", "port": "logo"})
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": edges})
        ev = []
        CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        errs = [e.get("message") for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("state") == "error"]
        self.assertEqual(errs, [], errs)
        done = [e for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("assets")][-1]
        a = next(a for a in self.cs.get(self.cid)["assets"] if a["id"] == done["assets"][0])
        with Image.open(self.cs.asset_path(self.cid, a["file"])) as im:
            return im.size, done.get("warnings") or []

    def test_resize_auto_side_never_hits_zero_pixels(self):
        thin = self.add(Image.new("RGB", (50, 4000), "gray"), "PNG", "thin.png")
        self.assertEqual(self.run_node("img_resize", {"width": 0, "height": 50}, thin)[0], (1, 50))      # antes: 0 px → erro do ffmpeg
        wide = self.add(Image.new("RGB", (4000, 50), "gray"), "PNG", "wide.png")
        self.assertEqual(self.run_node("img_resize", {"width": 2, "height": 2, "rotate": 90}, wide)[0], (1, 2))   # encaixa em 2×1 e gira 90°
        self.assertEqual(self.run_node("img_resize", {"width": 7, "height": 0, "rotate": 270, "flip": "both", "format": "jpg"}, wide)[0], (1, 7))

    def test_resize_modes_keep_their_meaning(self):
        a = self.add(Image.new("RGB", (800, 400), "orange"), "PNG", "a.png")
        self.assertEqual(self.run_node("img_resize", {"width": 100, "height": 100, "mode": "fit"}, a)[0], (100, 50))
        self.assertEqual(self.run_node("img_resize", {"width": 100, "height": 100, "mode": "pad"}, a)[0], (100, 100))
        self.assertEqual(self.run_node("img_resize", {"width": 100, "height": 100, "mode": "cover"}, a)[0], (100, 100))
        self.assertEqual(self.run_node("img_resize", {"width": 100, "height": 100, "mode": "stretch"}, a)[0], (100, 100))
        self.assertEqual(self.run_node("img_resize", {"width": 400, "height": 0}, a)[0], (400, 200))
        self.assertEqual(self.run_node("img_resize", {"width": 0, "height": 100}, a)[0], (200, 100))
        self.assertEqual(self.run_node("img_resize", {"width": 0, "height": 0}, a)[0], (800, 400))

    def test_crop_never_produces_zero_pixels_and_warns_at_the_edge(self):
        one = self.add(Image.new("RGB", (1, 1), "red"), "PNG", "one.png")
        for params in ({"mode": "ratio", "ratio": "21:9"}, {"mode": "manual", "x": 33, "y": 33, "w": 33, "h": 33}, {"mode": "manual", "x": 90, "y": 90, "w": 50, "h": 50}):
            self.assertEqual(self.run_node("img_crop", params, one)[0], (1, 1), params)
        wide = self.add(Image.new("RGB", (4000, 50), "gray"), "PNG", "wide2.png")
        self.assertEqual(self.run_node("img_crop", {"mode": "manual", "x": 0, "y": 0, "w": 1, "h": 1}, wide)[0], (40, 1))
        a = self.add(Image.new("RGB", (800, 400), "orange"), "PNG", "a2.png")
        self.assertEqual(self.run_node("img_crop", {"mode": "ratio", "ratio": "1:1"}, a)[0], (400, 400))
        self.assertEqual(self.run_node("img_crop", {"mode": "ratio", "ratio": "9:16", "anchor": "left"}, a)[0], (225, 400))
        size, warns = self.run_node("img_crop", {"mode": "manual", "x": 90, "y": 90, "w": 50, "h": 50}, a)
        self.assertEqual(size, (400, 200))
        self.assertTrue(any("borda" in w for w in warns), warns)

    def test_blur_on_a_one_pixel_image_is_skipped_with_a_warning(self):
        one = self.add(Image.new("RGB", (1, 1), "red"), "PNG", "one2.png")
        for preset in ("blur", "sharpen", "vhs"):
            size, warns = self.run_node("img_filter", {"preset": preset}, one)      # antes: o ffmpeg corrompia a memória e fechava
            self.assertEqual(size, (1, 1))
            self.assertTrue(any("pequena" in w for w in warns), (preset, warns))
        self.assertEqual(self.run_node("img_filter", {"preset": "blur"}, self.add(Image.new("RGB", (40, 40), "red"), "PNG", "ok.png"))[1], [])

    def test_exif_photo_is_edited_upright_by_every_ffmpeg(self):
        ex = Image.Exif()
        ex[0x0112] = 6
        photo = self.add(Image.new("RGB", (200, 100), "blue"), "JPEG", "foto.jpg", exif=ex)       # no arquivo 200×100, na tela 100×200
        self.assertEqual(self.run_node("img_resize", {"width": 50, "height": 0}, photo)[0], (50, 100))
        self.assertEqual(self.run_node("img_crop", {"mode": "ratio", "ratio": "1:1"}, photo)[0], (100, 100))
        self.assertEqual(self.run_node("img_filter", {"preset": "bw"}, photo)[0], (100, 200))

    def test_bmp_dimensions_come_from_ffprobe(self):
        bmp = self.add(Image.new("RGB", (60, 30), "blue"), "BMP", "b.bmp")
        self.assertEqual(self.run_node("img_resize", {"width": 30, "height": 0}, bmp)[0], (30, 15))
        p = self.tmp / "x.bmp"
        Image.new("RGB", (60, 30)).save(p)
        self.assertEqual(nodes_ext._dims(p), (60, 30))
        self.assertIsNone(nodes_ext._dims(self.tmp / "nao-existe.png"))


if __name__ == "__main__":
    unittest.main()
