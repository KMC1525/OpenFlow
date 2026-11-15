"""v0.38: regressões dos bugs achados na varredura geral (GIF como clipe parado, Editor só com áudio, regex que trava, validação de entradas da API)."""
import io
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store
from tests.helpers import ServerCase

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe_streams(path: Path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return sorted(set(r.stdout.split()))


class GraphCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("fix")["id"]

    def run_graph(self, nodes, edges=()):
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": list(edges)})
        ev = []
        CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        cur = self.cs.get(self.cid)
        return {n["id"]: n for n in cur["nodes"]}, cur

    @staticmethod
    def node(i, t, **p):
        return {"id": i, "type": t, "x": 0, "y": 0, "params": p}

    def gif(self):
        from PIL import Image

        b = io.BytesIO()
        Image.new("P", (120, 90), 3).save(b, "GIF")
        return self.cs.add_asset(self.cid, b.getvalue(), "gif", "image", name="a.gif", mime="image/gif", provider="upload")

    def audio(self):
        p = self.tmp / "a.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=2", "-c:a", "libmp3lame", str(p)], check=True)
        return self.cs.add_asset(self.cid, p.read_bytes(), "mp3", "audio", name="a.mp3", mime="audio/mpeg", provider="upload")


@unittest.skipUnless(FF, "sem ffmpeg")
class MediaFixTests(GraphCase):
    def test_a_gif_works_as_a_still_clip_in_every_video_node(self):
        g = self.gif()
        up = self.node("u", "upload", files=[g["id"]])
        up2 = self.node("u2", "upload", files=[g["id"]])
        cases = [("vid_slideshow", "images", {}), ("vid_join", "clips", {}), ("out_export", "video", {}), ("editor", "clips", {})]
        for t, port, params in cases:
            nodes = [up, up2, self.node("x", t, **params)]
            edges = [{"id": "e", "from": "u", "to": "x", "port": port}] + ([{"id": "e2", "from": "u2", "to": "x", "port": port}] if t == "vid_join" else [])
            res, cur = self.run_graph(nodes, edges)
            self.assertEqual(res["x"]["result"]["state"], "done", (t, res["x"]["result"]["error"]))
            asset = next(a for a in cur["assets"] if a["id"] == res["x"]["result"]["assets"][0])
            self.assertEqual(asset["kind"], "video", t)

    def test_the_editor_with_only_audio_makes_a_video_with_the_sound(self):
        a = self.audio()
        res, cur = self.run_graph([self.node("u", "upload", files=[a["id"]]), self.node("x", "editor")], [{"id": "e", "from": "u", "to": "x", "port": "clips"}])
        self.assertEqual(res["x"]["result"]["state"], "done", res["x"]["result"]["error"])
        asset = next(x for x in cur["assets"] if x["id"] == res["x"]["result"]["assets"][0])
        self.assertEqual(probe_streams(self.cs.asset_path(self.cid, asset["file"])), ["audio", "video"])


class RegexTests(GraphCase):
    def extract(self, text, pattern):
        txt = self.node("t", "text", text=text)
        res, _ = self.run_graph([txt, self.node("x", "text_extract", what="regex", pattern=pattern)], [{"id": "e", "from": "t", "to": "x", "port": "text"}])
        return res["x"]["result"]

    def test_a_pattern_that_never_ends_is_stopped(self):
        t = time.time()
        r = self.extract("a" * 40, "(a|a)*b")
        self.assertEqual(r["state"], "error")
        self.assertIn("demorou demais", r["error"])
        self.assertLess(time.time() - t, 15)

    def test_normal_patterns_still_work_and_unicode_survives(self):
        r = self.extract("a1 b22 c333 ção9", r"[a-zç](\d+)")
        self.assertEqual((r["state"], r["text"]), ("done", "1\n22\n333\n9"))
        self.assertEqual(self.extract("x", "(")["state"], "error")   # inválido continua com a mensagem de padrão inválido
        self.assertIn("inválido", self.extract("x", "(")["error"])


class ApiValidationTests(ServerCase):
    def test_bad_input_is_a_client_error_not_a_gateway_error(self):
        self.assertEqual(self.c.json("GET", "/api/hf/search?kind=zzz")[0], 400)
        self.assertEqual(self.c.json("GET", "/api/hf/files?repo=nada")[0], 400)
        self.assertEqual(self.c.json("POST", "/api/media/test", {"provider": ""})[0], 400)
        self.assertEqual(self.c.json("GET", "/api/media/models?provider=nada&cap=image")[0], 400)
        self.assertEqual(self.c.json("POST", "/api/media/test", {"provider": "demo"})[0], 200)


if __name__ == "__main__":
    unittest.main()
