"""v0.88 — Caçando Bugs 7: o que foi achado e corrigido (cada teste falha sem a correção)."""
import unittest
from unittest import mock

from openflow.canvas import engine as E
from openflow.canvas import media as M
from openflow.canvas import procedural as proc
from tests.helpers import TmpCase
from tests.test_canvas import edge, node


class VideoMentionTests(TmpCase):
    def run_video(self, prompt):
        from openflow.storage import Store

        store = Store(self.tmp / "home")
        cs = store.projects
        c = cs.create("t")
        src = proc.image("original", "96x96", 3)
        a = cs.add_asset(c["id"], src, "png", "image", name="gato.png", mime="image/png")
        b = cs.add_asset(c["id"], proc.image("outra", "96x96", 4), "png", "image", name="cao.png", mime="image/png")
        cs.save_layout(c["id"], {"nodes": [node("video", nid="v", prompt=prompt)], "edges": []})
        seen = {}

        class Fake:
            label = "Fake"

            def video(self, prompt, *, image=None, **k):
                seen.update(prompt=prompt, image=image)
                return M.Media(b"x", "video/mp4")

        with mock.patch.object(E, "build_media", lambda *a, **k: Fake()):
            E.CanvasEngine(store, c["id"], lambda ev: None).run(None, False)
        return seen, a, b

    def test_the_video_prompt_has_no_reference_image_markers(self):
        seen, _a, _b = self.run_video("o @gato correndo atrás do @cao")
        self.assertNotIn("reference image", seen["prompt"])
        self.assertIn("gato correndo atrás do cao", seen["prompt"])
        self.assertIsNotNone(seen["image"])   # a primeira citada continua sendo a imagem inicial


if __name__ == "__main__":
    unittest.main()
