"""v0.52: melhorias gerais — o tipo de um arquivo enviado vem das trilhas (áudio dentro de .mp4 é áudio, .ogv é vídeo) e nós de áudio não gravam arquivos vazios."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from openflow.canvas import media
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store
from tests.helpers import ServerCase

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
V = ["-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=1"]
A = ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"]


def make(tmp: Path, name: str, *args) -> bytes:
    p = tmp / name
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-300:]
    return p.read_bytes()


@unittest.skipUnless(FF, "sem ffmpeg")
class RefineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())

    def kind(self, name, *args):
        data = make(self.tmp, name, *args)
        return media.refine_mime(data, media.sniff_mime(data))

    def test_audio_only_containers_are_audio(self):
        self.assertEqual(self.kind("a.mp4", *A, "-c:a", "aac"), "audio/mp4")           # nota de voz salva como .mp4
        self.assertEqual(self.kind("a.mov", *A, "-c:a", "aac"), "audio/mp4")
        self.assertEqual(self.kind("a.webm", *A, "-c:a", "libopus"), "audio/webm")
        self.assertEqual(self.kind("a.mka", *A, "-c:a", "aac"), "audio/webm")
        self.assertEqual(self.kind("a.3gp", *A, "-c:a", "aac"), "audio/mp4")

    def test_real_videos_and_other_types_stay_as_they_are(self):
        self.assertEqual(self.kind("v.mp4", *V, "-c:v", "libx264", "-pix_fmt", "yuv420p"), "video/mp4")
        self.assertEqual(self.kind("v2.mp4", *V, *A, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"), "video/mp4")   # vídeo com som
        self.assertEqual(self.kind("v.webm", *V, "-c:v", "libvpx-vp9"), "video/webm")
        self.assertEqual(self.kind("a.mp3", *A, "-c:a", "libmp3lame"), "audio/mpeg")
        self.assertEqual(self.kind("a.ogg", *A, "-c:a", "libvorbis"), "audio/ogg")
        self.assertEqual(self.kind("a.m4a", *A, "-c:a", "aac"), "audio/mp4")

    def test_a_video_in_an_ogg_container_is_video(self):
        self.assertEqual(self.kind("v.ogv", *V, "-c:v", "libtheora"), "video/ogg")

    def test_unreadable_data_keeps_the_sniffed_type(self):
        self.assertEqual(media.refine_mime(b"\x00\x00\x00\x18ftypmp42" + b"x" * 40, "video/mp4"), "video/mp4")
        self.assertEqual(media.refine_mime(b"qualquer", "image/png"), "image/png")
        self.assertEqual(media.MIME_EXT["video/ogg"], "ogv")


@unittest.skipUnless(FF, "sem ffmpeg")
class UploadTests(ServerCase):
    def test_a_voice_note_in_mp4_is_stored_as_audio(self):
        tmp = Path(tempfile.mkdtemp())
        s, p = self.c.json("POST", "/api/projects", {"name": "U", "template": "blank"})
        data = make(tmp, "voz.mp4", *A, "-c:a", "aac")
        s, a = self.c.json("POST", f"/api/projects/{p['id']}/assets", raw=data, headers={"X-Filename": "voz.mp4"})
        self.assertEqual((s, a["kind"], a["mime"]), (201, "audio", "audio/mp4"))
        self.assertTrue(a["file"].endswith(".m4a") or a["file"].endswith(".mp4"))
        self.assertAlmostEqual(a["duration"], 1.0, delta=0.2)
        video = make(tmp, "cli.mp4", *V, "-c:v", "libx264", "-pix_fmt", "yuv420p")
        s, v = self.c.json("POST", f"/api/projects/{p['id']}/assets", raw=video, headers={"X-Filename": "cli.mp4"})
        self.assertEqual((s, v["kind"], (v["w"], v["h"])), (201, "video", (160, 90)))


@unittest.skipUnless(FF, "sem ffmpeg")
class AudioNodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("aud")["id"]
        d = make(cls.tmp, "m.mp3", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "libmp3lame")
        cls.mp3 = cls.cs.add_asset(cls.cid, d, "mp3", "audio", name="m.mp3", mime="audio/mpeg", provider="upload")
        d = make(cls.tmp, "s.wav", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.05")
        cls.short = cls.cs.add_asset(cls.cid, d, "wav", "audio", name="s.wav", mime="audio/wav", provider="upload")

    def run_node(self, ntype, params, asset):
        nodes = [{"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [asset["id"]]}}, {"id": "x", "type": ntype, "x": 0, "y": 0, "params": params}]
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": [{"from": "u", "to": "x", "port": "audio"}]})
        ev = []
        CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        errs = " ".join(e.get("message") or "" for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("state") == "error")
        done = [e for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("assets")]
        return errs, done

    def test_trim_past_the_end_is_an_error_not_an_empty_file(self):
        errs, done = self.run_node("aud_trim", {"start": 50, "duration": 1}, self.mp3)
        self.assertIn("passa do fim", errs)
        self.assertEqual(done, [])

    def test_valid_trim_still_works(self):
        errs, done = self.run_node("aud_trim", {"start": 1, "duration": 1}, self.mp3)
        self.assertEqual(errs, "")
        a = next(a for a in self.cs.get(self.cid)["assets"] if a["id"] == done[-1]["assets"][0])
        self.assertAlmostEqual(a["duration"], 1.0, delta=0.15)

    def test_an_effect_that_leaves_nothing_is_an_error(self):
        errs, done = self.run_node("aud_fx", {"fx": "faster", "amount": 4}, self.short)     # 0,05 s ÷ 5 → o ffmpeg gravava um arquivo vazio
        self.assertTrue("sem áudio" in errs or done, errs)
        if done:
            a = next(a for a in self.cs.get(self.cid)["assets"] if a["id"] == done[-1]["assets"][0])
            self.assertGreater(a.get("duration") or 0, 0)


if __name__ == "__main__":
    unittest.main()
