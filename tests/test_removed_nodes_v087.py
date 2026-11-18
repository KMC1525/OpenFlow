"""v0.87 — os nós «Editor» e «Modelo PyTorch/TensorFlow» saíram: não existem mais no esquema, na API nem na paleta, e um projeto antigo que os tinha abre sem eles (com aviso), mantendo os arquivos que eles geraram."""
import json
import unittest

from openflow.canvas import schema
from tests.helpers import ServerCase
from tests.test_canvas import PNG, node


class SchemaTests(unittest.TestCase):
    def test_the_two_node_types_are_gone(self):
        for t in ("editor", "ai_model"):
            self.assertNotIn(t, schema.NODE_TYPES)
            self.assertNotIn(t, [x for _, ts in schema.PALETTE for x in ts])
            self.assertIsNone(schema.normalize_node({"type": t, "id": "x"}))

    def test_the_scene_template_ends_in_the_final_video(self):
        base = schema.build_template("scene")
        types = [n["type"] for n in base["nodes"]]
        self.assertIn("out_export", types)
        self.assertNotIn("editor", types)
        c = schema.normalize_canvas({"nodes": base["nodes"], "edges": base["edges"]}, keep_id="cv_x")
        self.assertEqual(len(c["edges"]), len(base["edges"]))   # nenhuma conexão do modelo se perde

    def test_an_old_project_loses_only_the_removed_nodes_and_says_so(self):
        raw = {"nodes": [node("text", nid="t"), {**node("editor", nid="ed"), "title": "Montagem final"}, node("ai_model", nid="m")],
               "edges": [{"id": "e1", "from": "t", "to": "ed", "port": "clips"}], "assets": []}
        c = schema.normalize_canvas(raw, keep_id="cv_x")
        self.assertEqual([n["id"] for n in c["nodes"]], ["t"])
        self.assertEqual(c["edges"], [])
        self.assertEqual([r["title"] for r in c["removed_nodes"]], ["Montagem final", "Modelo PyTorch/TensorFlow"])
        again = schema.normalize_canvas(c, keep_id="cv_x")   # reler o que já foi limpo não perde o aviso
        self.assertEqual(len(again["removed_nodes"]), 2)
        self.assertNotIn("removed_nodes", schema.normalize_canvas({"nodes": [node("text", nid="t")]}))


class ApiTests(ServerCase):
    def test_the_old_endpoints_are_gone(self):
        cid = self.c.json("POST", "/api/projects", {"template": "blank"})[1]["id"]
        self.assertEqual(self.c.json("POST", f"/api/projects/{cid}/nodes/x/autofill")[0], 404)
        for path in ("/api/tool/info?model=a", "/api/tool/files?model=a/b"):
            self.assertEqual(self.c.json("GET", path)[0], 404, path)
        self.assertEqual(self.c.json("POST", "/api/tool/download", {"model": "a/b", "framework": "torch"})[0], 404)
        self.assertEqual(self.c.json("GET", "/api/media/hub/search?cap=tool&q=esrgan")[0], 400)
        self.c.json("DELETE", f"/api/projects/{cid}")

    def test_an_old_project_file_opens_without_the_nodes_and_keeps_its_files(self):
        cid = self.c.json("POST", "/api/projects", {"template": "blank"})[1]["id"]
        a = self.store.projects.add_asset(cid, PNG, "png", "image", name="montagem.png", mime="image/png", node="ed")
        path = self.store.projects.folder / cid / "project.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["nodes"] = [{"id": "ed", "type": "editor", "x": 0, "y": 0, "params": {"timeline": {"tracks": [], "clips": []}}, "result": {"state": "done", "assets": [a["id"]]}},
                         {"id": "m", "type": "ai_model", "x": 0, "y": 0, "params": {"model": "/x/y.pt"}}]
        data["assets"] = json.loads(path.read_text(encoding="utf-8"))["assets"]
        path.write_text(json.dumps(data), encoding="utf-8")
        status, cv = self.c.json("GET", f"/api/projects/{cid}")
        self.assertEqual(status, 200)
        self.assertEqual(cv["nodes"], [])
        self.assertEqual(len(cv["removed_nodes"]), 2)
        self.assertIn(a["id"], [x["id"] for x in cv["assets"]])   # o vídeo/imagem que o Editor gerou continua no projeto
        self.assertIsNotNone(self.store.projects.asset_path(cid, a["file"]))
        self.c.json("DELETE", f"/api/projects/{cid}")


class QuantNameTests(unittest.TestCase):
    def test_ternary_quants_are_recognised_as_very_low(self):
        from openflow import hf
        from openflow.canvas import quants

        self.assertEqual((hf.parse_quant("m-TQ2_0.gguf")["quant"], hf.parse_quant("m-TQ2_0.gguf")["bits"]), ("TQ2_0", 2))
        self.assertEqual(hf.parse_quant("m-TQ1_0.gguf")["quality"], "very_low")
        self.assertEqual(quants.tier_of("TQ2_0"), "Q2")


if __name__ == "__main__":
    unittest.main()
