"""v0.40: sem o sistema de agentes/multi-agentes e sem os níveis de esforço (Low … Omni): nada disso existe mais na API, nas configurações nem no motor; os nós de texto com IA fazem uma chamada só."""
import importlib
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store
from tests.helpers import ServerCase

ROOT = Path(__file__).resolve().parent.parent / "openflow"


class RemovedTests(unittest.TestCase):
    def test_the_modules_are_gone(self):
        for mod in ("openflow.team", "openflow.efforts", "openflow.providers.thinking", "openflow.agents"):
            with self.assertRaises(ImportError, msg=mod):
                importlib.import_module(mod)
        self.assertFalse((ROOT / "web" / "js" / "team_ui.js").exists())

    def test_defaults_have_no_team_keys(self):
        from openflow.storage import DEFAULT_SETTINGS

        self.assertNotIn("agents", DEFAULT_SETTINGS["generation"])
        self.assertNotIn("effort", DEFAULT_SETTINGS["generation"])
        self.assertEqual(DEFAULT_SETTINGS["canvas"], {"template": "text_image"})

    def test_old_settings_with_agents_and_effort_still_load(self):
        import tempfile

        from openflow.util import write_json

        home = Path(tempfile.mkdtemp())
        write_json(home / "settings.json", {"canvas": {"template": "text_image", "agents": 16, "effort": "omni"}, "generation": {"agents": 8, "effort": "mega", "temperature": 0.5}})
        s = Store(home).get_settings()
        self.assertEqual(s["generation"]["temperature"], 0.5)
        self.assertEqual(s["canvas"]["template"], "text_image")

    def test_no_source_mentions_the_removed_systems(self):
        bad = []
        for p in list(ROOT.rglob("*.py")) + list(ROOT.rglob("*.js")):
            if "native" in p.parts or p.name == "en.js":
                continue
            src = p.read_text(encoding="utf-8")
            for needle in ("import team", "teamlib", "team_chat", "efforts.", "team_ui", "request_team", "ensemble_json"):
                if needle in src:
                    bad.append((p.name, needle))
        self.assertEqual(bad, [])


class EngineTests(unittest.TestCase):
    def test_ai_text_makes_a_single_provider_call(self):
        import tempfile
        from pathlib import Path as P

        store = Store(P(tempfile.mkdtemp()))
        cid = store.projects.create("t")["id"]
        calls = []

        class Prov:
            vision = False

            def chat(self, messages, system="", temperature=0.5, max_tokens=100, **kw):
                calls.append({"system": system, "max_tokens": max_tokens, "kw": kw})
                return "  texto da IA  "

        store.save_settings({"active": {"generation": "local_hf"}, "providers": {"local_hf": {"model": "x.gguf"}}})
        nodes = [{"id": "t", "type": "text", "x": 0, "y": 0, "params": {"text": "um gato"}}, {"id": "l", "type": "llm", "x": 0, "y": 0, "params": {"instruction": "detalhe"}}]
        store.projects.save_layout(cid, {"nodes": nodes, "edges": [{"id": "e", "from": "t", "to": "l", "port": "prompt"}]})
        with mock.patch("openflow.canvas.engine.build_provider", return_value=Prov()):
            CanvasEngine(store, cid, lambda e: None, lambda: False).run(None, True)
        n = next(x for x in store.projects.get(cid)["nodes"] if x["id"] == "l")
        self.assertEqual((n["result"]["state"], n["result"]["text"]), ("done", "texto da IA"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["max_tokens"], 1500)   # sem multiplicador de esforço


class ApiTests(ServerCase):
    def test_team_route_is_gone_and_run_ignores_old_team_bodies(self):
        self.assertEqual(self.c.json("GET", "/api/team")[0], 404)
        s, p = self.c.json("POST", "/api/projects", {"name": "x", "template": "blank"})
        s, r = self.c.json("POST", f"/api/projects/{p['id']}/run", {"team": {"agents": 32, "effort": "omni"}})
        self.assertEqual(s, 200)
        self.assertIn("job_id", r)
        s, st = self.c.json("GET", "/api/settings")
        self.assertNotIn("agents", st["canvas"])
        self.assertNotIn("effort", st["canvas"])


if __name__ == "__main__":
    unittest.main()
