"""v0.47: regressões da varredura geral (configurações com tipos errados, GLB inválido enviado como arquivo)."""
import json
import tempfile
import unittest
from pathlib import Path

from openflow.canvas import mesh3d
from openflow.storage import Store
from openflow.util import write_json
from tests.helpers import ServerCase


class SettingsTypeTests(unittest.TestCase):
    def test_provider_and_media_model_values_must_be_text_and_numbers(self):
        home = Path(tempfile.mkdtemp())
        write_json(home / "settings.json", {"providers": {"local_hf": {"model": 5, "n_ctx": "x"}, "demo": {"model": ["a"], "n_ctx": True}},
                                            "media": {"models": {"local_hf": {"image": 7, "sound": "  musicgen  ", "voice": None}, "gguf_local": "texto", "demo": {"image": "x"}}}})
        s = Store(home).get_settings()
        self.assertEqual(s["providers"]["local_hf"], {})
        self.assertEqual(s["providers"]["demo"], {})
        self.assertEqual(s["media"]["models"], {"local_hf": {"sound": "musicgen"}, "demo": {"image": "x"}})

    def test_valid_values_survive_and_are_clamped(self):
        st = Store(Path(tempfile.mkdtemp()))
        st.save_settings({"providers": {"local_hf": {"model": "  a.gguf ", "n_ctx": 8192.0}}})
        self.assertEqual(st.get_settings()["providers"]["local_hf"], {"model": "a.gguf", "n_ctx": 8192})
        st.save_settings({"providers": {"local_hf": {"n_ctx": 10 ** 12}}})
        self.assertEqual(st.get_settings()["providers"]["local_hf"]["n_ctx"], 4194304)
        st.save_settings({"providers": {"local_hf": {"n_ctx": -5}}})
        self.assertNotIn("n_ctx", st.get_settings()["providers"]["local_hf"])   # um valor negativo volta ao automático


class UploadTests(ServerCase):
    def test_a_broken_glb_is_refused_and_a_real_one_is_accepted(self):
        s, p = self.c.json("POST", "/api/projects", {"name": "3D", "template": "blank"})
        for data in (b"glTF" + b"\x00" * 30, b"glTF\x02\x00\x00\x00" + b"\xff" * 40):
            st, _, body = self.c.req("POST", f"/api/projects/{p['id']}/assets", raw=data, headers={"X-Filename": "x.glb"})
            self.assertEqual(st, 400, body)
            self.assertIn("GLB", json.loads(body)["error"])
        good = mesh3d.encode(mesh3d.demo_mesh("bola"), "glb")
        st, _, body = self.c.req("POST", f"/api/projects/{p['id']}/assets", raw=good, headers={"X-Filename": "ok.glb"})
        self.assertEqual((st, json.loads(body)["kind"]), (201, "model3d"))

    def test_the_canvas_meta_tells_the_node_limit_and_the_server_keeps_that_many(self):
        s, m = self.c.json("GET", "/api/project-templates")
        self.assertEqual(s, 200)
        self.assertEqual(m["limits"], {"nodes": 200, "edges": 600})
        s, p = self.c.json("POST", "/api/projects", {"name": "L", "template": "blank"})
        nodes = [{"id": f"n{i}", "type": "text", "x": 0, "y": 0, "params": {"text": "x"}} for i in range(250)]
        self.c.json("PUT", f"/api/projects/{p['id']}", {"nodes": nodes, "edges": []})
        self.assertEqual(len(self.c.json("GET", f"/api/projects/{p['id']}")[1]["nodes"]), 200)

    def test_the_settings_import_with_wrong_types_cannot_poison_the_file(self):
        payload = {"schema": "openflow.settings.v1", "settings": {"providers": {"local_hf": {"model": 5, "n_ctx": "x"}}, "media": {"models": {"local_hf": {"image": 3}}}}}
        self.assertEqual(self.c.json("POST", "/api/settings/import", payload)[0], 200)
        s, r = self.c.json("GET", "/api/settings")
        self.assertEqual(r["providers"].get("local_hf", {}), {})
        self.assertEqual(r["media"]["models"].get("local_hf", {}), {})
        s, st = self.c.json("GET", "/api/media/providers")
        self.assertEqual(s, 200)


if __name__ == "__main__":
    unittest.main()
