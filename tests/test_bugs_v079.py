"""v0.79: uma imagem truncada/corrompida fazia a exportação (e o «Imagens em vídeo») travar para sempre — o ffmpeg com `-loop 1` não desiste de um quadro que não decodifica.
Agora a imagem é conferida antes (`render.check_image`) e o erro é claro e imediato. Imagens e GIFs válidos seguem iguais."""
import io
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from openflow.canvas import render
from openflow.providers import ProviderError
from openflow.util import Cancelled

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


class Ctl:
    def check(self):
        pass

    def note(self, m):
        pass


def png_bytes() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (64, 48), "red").save(b, "PNG")
    return b.getvalue()


@unittest.skipUnless(Image and shutil.which("ffmpeg"), "precisa de Pillow e ffmpeg")
class CorruptImageTests(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def write(self, name, data):
        p = self.td / name
        p.write_bytes(data)
        return p

    def test_truncated_png_fails_fast_and_clearly(self):
        p = self.write("quebrada.png", png_bytes()[:60])
        out, box = [], {}

        def go():
            try:
                render.still_path(p, str(self.td), Ctl())
            except Exception as e:  # noqa: BLE001
                box["e"] = e

        t = threading.Thread(target=go, daemon=True)
        t.start()
        t.join(30)
        self.assertFalse(t.is_alive(), "ainda travado")
        self.assertIsInstance(box.get("e"), ProviderError)
        self.assertIn("corrompida ou incompleta", str(box["e"]))
        self.assertIn("quebrada.png", str(box["e"]))
        self.assertEqual(out, [])

    def test_garbage_file_named_png(self):
        p = self.write("lixo.png", b"isto nao e uma imagem" * 20)
        with self.assertRaises(ProviderError):
            render.check_image(p)

    def test_valid_png_passes_and_is_returned(self):
        p = self.write("ok.png", png_bytes())
        render.check_image(p)
        self.assertTrue(Path(render.still_path(p, str(self.td), Ctl())).exists())

    def test_valid_gif_still_gets_first_frame(self):
        frames = [Image.new("RGB", (32, 32), c) for c in ("red", "blue")]
        g = self.td / "a.gif"
        frames[0].save(g, save_all=True, append_images=frames[1:], duration=100, loop=0)
        r = Path(render.still_path(g, str(self.td), Ctl()))
        self.assertTrue(r.exists())
        self.assertNotEqual(r, g)

    def test_without_ffmpeg_is_a_noop(self):
        from unittest import mock
        p = self.write("q.png", png_bytes()[:60])
        with mock.patch.object(render.shutil, "which", return_value=None):
            render.check_image(p)


if __name__ == "__main__":
    unittest.main()
