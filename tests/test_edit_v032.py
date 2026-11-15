"""v0.32: edição de vídeos — dimensões ímpares, taxa de quadros da origem, duração exata na velocidade e largura/altura dos vídeos anotadas."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from openflow import attachments as att
from openflow.canvas import nodes_ext
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe(path: Path):
    o = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,duration", "-of", "json", str(path)], capture_output=True, text=True).stdout
    return {s["codec_type"]: s for s in json.loads(o)["streams"]}


@unittest.skipUnless(FF, "sem ffmpeg")
class EditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("edit")["id"]

    def video(self, name, w, h, fps, secs, audio=True):
        p = self.tmp / f"{name}.mp4"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate={fps}:duration={secs}"]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p" if w % 2 == 0 and h % 2 == 0 else "yuv444p"] + (["-c:a", "aac"] if audio else []) + [str(p)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-300:])
        return self.cs.add_asset(self.cid, p.read_bytes(), "mp4", "video", name=name, mime="video/mp4", provider="upload")

    def run_node(self, asset, ntype, **params):
        nodes = [{"id": "src", "type": "upload", "x": 0, "y": 0, "params": {"files": [asset["id"]]}}, {"id": "x", "type": ntype, "x": 0, "y": 0, "params": params}]
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": [{"from": "src", "to": "x", "port": "video"}]})
        ev = []
        CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        errs = [e for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("state") == "error"]
        self.assertEqual(errs, [], errs)
        done = [e for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("assets")]
        a = next(x for x in self.cs.get(self.cid)["assets"] if x["id"] == done[-1]["assets"][0])
        return probe(self.cs.asset_path(self.cid, a["file"]))

    def test_videos_get_their_size_annotated(self):
        a = self.video("tam", 640, 360, 24, 1)
        self.assertEqual((a["w"], a["h"]), (640, 360))

    def test_video_info(self):
        a = self.video("info", 320, 180, 12, 1)
        vi = att.video_info(self.cs.asset_path(self.cid, a["file"]))
        self.assertEqual((vi["w"], vi["h"], round(vi["fps"])), (320, 180, 12))
        self.assertEqual(att.video_info(self.tmp / "nao-existe.mp4"), {})

    def test_odd_sized_videos_can_be_trimmed_sped_up_and_restyled(self):
        a = self.video("odd", 853, 481, 24, 2)
        for t, params in (("vid_trim", {}), ("vid_speed", {"factor": 2}), ("vid_look", {})):
            v = self.run_node(a, t, **params)["video"]
            self.assertEqual((int(v["width"]) % 2, int(v["height"]) % 2), (0, 0), t)

    def test_the_source_frame_rate_is_kept(self):
        a = self.video("fps12", 640, 360, 12, 2)
        for t, params in (("vid_trim", {}), ("vid_speed", {"factor": 2}), ("vid_look", {})):
            self.assertEqual(self.run_node(a, t, **params)["video"]["r_frame_rate"], "12/1", t)

    def test_speed_keeps_the_duration_exact_and_in_sync_with_the_audio(self):
        a = self.video("dur", 640, 360, 12, 3)
        r = self.run_node(a, "vid_speed", factor=2)
        self.assertAlmostEqual(float(r["video"]["duration"]), 1.5, delta=0.01)
        self.assertAlmostEqual(float(r["audio"]["duration"]), float(r["video"]["duration"]), delta=0.05)
        r = self.run_node(a, "vid_speed", factor=4)
        self.assertAlmostEqual(float(r["video"]["duration"]), 0.75, delta=0.01)

    def test_a_silent_video_still_works(self):
        a = self.video("mudo", 640, 360, 16, 2, audio=False)
        r = self.run_node(a, "vid_speed", factor=2)
        self.assertNotIn("audio", r)
        self.assertAlmostEqual(float(r["video"]["duration"]), 1.0, delta=0.05)

    def test_src_fps_falls_back_when_unreadable(self):
        self.assertEqual(nodes_ext._src_fps(self.tmp / "nada.mp4"), 30.0)
        self.assertIn("scale=trunc", nodes_ext.EVEN)
