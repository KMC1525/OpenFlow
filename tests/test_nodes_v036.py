"""v0.36: nós «Ficha de personagem» e «Página de quadrinhos» — montam o prompt de verdade (rodando o motor) e alimentam o nó Imagem."""
import tempfile
import unittest
from pathlib import Path

from openflow.canvas import nodes_ext, schema
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

NEW = ["char_sheet", "comic_page"]


class SpecTests(unittest.TestCase):
    def test_registered_everywhere(self):
        for k in NEW:
            self.assertIn(k, nodes_ext.SPECS)
            self.assertIn(k, nodes_ext.RUNNERS)
            self.assertIn(k, schema.NODE_TYPES)
            self.assertEqual(schema.NODE_TYPES[k]["out"], "text")
        listed = [t for _, ts in schema.PALETTE for t in ts]
        self.assertTrue(all(k in listed for k in NEW))
        js = (Path(__file__).resolve().parent.parent / "openflow" / "web" / "js" / "canvas_nodes.js").read_text(encoding="utf-8")
        for k in NEW:
            self.assertGreaterEqual(js.count(k), 4, k)

    def test_parameters_are_clamped(self):
        n = schema.normalize_params
        self.assertEqual(n("comic_page", {"panels": 99, "format": "x", "style": "?"})["panels"], 12)
        self.assertEqual((n("comic_page", {"format": "x"})["format"], n("comic_page", {"style": "?"})["style"]), ("page", "comic"))
        self.assertEqual(n("char_sheet", {"views": ["side", "zzz", "front"]})["views"], ["front", "side"])  # só vistas válidas, na ordem do catálogo
        self.assertEqual(n("char_sheet", {})["views"], ["front", "side", "back"])
        self.assertEqual(n("char_sheet", {"language": "fr", "background": "?"})["language"], "en")


class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("fichas")["id"]

    def run_graph(self, nodes, edges=()):
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": list(edges)})
        ev = []
        CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        return ev

    def node(self, ntype, params=None, nid="x"):
        return {"id": nid, "type": ntype, "x": 0, "y": 0, "params": params or {}}

    def out(self, ev, nid="x"):
        errs = [e for e in ev if e.get("type") == "node" and e.get("id") == nid and e.get("state") == "error"]
        self.assertEqual(errs, [], errs)
        done = [e for e in ev if e.get("type") == "node" and e.get("id") == nid and e.get("state") == "done"]
        self.assertTrue(done)
        return self.cs.get(self.cid)["nodes"][[n["id"] for n in self.cs.get(self.cid)["nodes"]].index(nid)]["result"]

    def err(self, ev, nid="x"):
        return " ".join((e.get("message") or "") for e in ev if e.get("type") == "node" and e.get("id") == nid and e.get("state") == "error")

    def test_character_sheet_prompt(self):
        r = self.out(self.run_graph([self.node("char_sheet", {"name": "Aurora", "description": "capitã de cabelo azul e casaco vermelho", "views": ["front", "back"], "extras": ["expressions", "palette"], "layout": "turnaround", "background": "gray"})]))
        t = r["text"]
        for want in ("Aurora", "front view", "back view", "facial expressions", "color palette", "turnaround", "light gray", "capitã de cabelo azul", "consistency"):
            self.assertIn(want, t)
        self.assertNotIn("side view", t)

    def test_character_sheet_portuguese_without_labels_and_linked_text(self):
        txt = {"id": "t", "type": "text", "x": 0, "y": 0, "params": {"text": "um robô gentil"}}
        r = self.out(self.run_graph([txt, self.node("char_sheet", {"language": "pt", "labels": False})], [{"from": "t", "to": "x", "port": "text"}]))
        self.assertIn("Ficha de personagem", r["text"])
        self.assertIn("um robô gentil", r["text"])
        self.assertIn("Sem texto nem rótulos", r["text"])

    def test_character_sheet_needs_a_description(self):
        self.assertIn("personagem", self.err(self.run_graph([self.node("char_sheet", {})])))

    def test_comic_page_scenes_dialogue_and_characters(self):
        chars = {"id": "c", "type": "text", "x": 0, "y": 0, "params": {"text": "Aurora: capitã de cabelo azul"}}
        scenes = "A capitã chega ao porto | Finalmente em casa!\nUm gato a observa\nAurora sorri | Olá, amigo"
        r = self.out(self.run_graph([chars, self.node("comic_page", {"scenes": scenes, "style": "manga", "color": "bw", "direction": "rtl", "title": "Volta"})], [{"from": "c", "to": "x", "port": "characters"}]))
        t = r["text"]
        for want in ("3 panels", "Panel 1: A capitã chega ao porto", 'exact text: "Finalmente em casa!"', "Panel 2: Um gato a observa", "manga", "black and white", "right to left", "«Volta»", "Aurora: capitã de cabelo azul"):
            self.assertIn(want, t)
        self.assertNotIn("exact text: \"Um gato", t)

    def test_comic_formats_and_balloon_options(self):
        many = "\n".join(f"cena {i}" for i in range(1, 8))
        r = self.out(self.run_graph([self.node("comic_page", {"scenes": many, "format": "koma", "balloons": "none"})]))
        self.assertIn("4 panels", r["text"])
        self.assertIn("No speech balloons", r["text"])
        self.assertTrue(any("4" in w for w in r.get("warnings", [])) or "cena 5" not in r["text"])
        self.assertNotIn("cena 5", r["text"])
        r = self.out(self.run_graph([self.node("comic_page", {"scenes": "uma explosão | BOOM", "format": "splash", "language": "pt", "balloons": "empty"})]))
        self.assertIn("1 quadros", r["text"])
        self.assertIn("vazios", r["text"])
        self.assertNotIn("BOOM", r["text"])

    def test_comic_page_needs_scenes(self):
        self.assertIn("cenas", self.err(self.run_graph([self.node("comic_page", {})])))

    def test_style_prompt_is_appended(self):
        sp = {"id": "s", "type": "style_prompt", "x": 0, "y": 0, "params": {"text": "aquarela suave, tons pastel"}}
        r = self.out(self.run_graph([sp, self.node("char_sheet", {"name": "Lia"})], [{"from": "s", "to": "x", "port": "style"}]))
        self.assertIn("aquarela suave", r["text"])

    def test_the_prompt_feeds_an_image_node(self):
        g = [self.node("char_sheet", {"name": "Lia", "description": "menina com chapéu verde"}, "x"), {"id": "i", "type": "image", "x": 0, "y": 0, "params": {"provider": "demo", "size": "512x512"}}]
        ev = self.run_graph(g, [{"from": "x", "to": "i", "port": "prompt"}])
        self.assertEqual(self.err(ev, "i"), "")
        cur = self.cs.get(self.cid)
        img = next(n for n in cur["nodes"] if n["id"] == "i")
        asset = next(a for a in cur["assets"] if a["id"] == img["result"]["assets"][0])
        self.assertIn("Character design sheet of Lia", asset["prompt"])


if __name__ == "__main__":
    unittest.main()
