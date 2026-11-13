"""Gerar fluxo do Canvas a partir de um prompt (caixa embaixo do canvas): construção validada, método automático e a rota com equipe."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow.canvas import flow as F  # noqa: E402
from tests.helpers import ServerCase  # noqa: E402


class BuildTests(unittest.TestCase):
    def test_a_plan_becomes_valid_nodes_and_edges_laid_out_in_columns(self):
        plan = {"nodes": [{"key": "t", "type": "text", "params": {"text": "um farol"}}, {"key": "i", "type": "image", "params": {"prompt": "farol", "size": "9x9"}},
                          {"key": "v", "type": "video", "params": {"duration": 99}}, {"key": "x", "type": "hacker"}],
                "edges": [{"from": "t", "to": "i", "port": "prompt"}, {"from": "i", "to": "v", "port": "image"}, {"from": "v", "to": "t", "port": "prompt"},   # ciclo
                          {"from": "t", "to": "v", "port": "nope"}, {"from": "zz", "to": "v", "port": "prompt"}]}
        out = F.build(plan, (100, 50))
        self.assertEqual([n["type"] for n in out["nodes"]], ["text", "image", "video"])   # tipo desconhecido descartado
        self.assertEqual(len(out["edges"]), 2)
        self.assertEqual(out["dropped"], 2 + 0)   # ciclo e porta inexistente (a chave desconhecida nem entra na conta)
        im = out["nodes"][1]
        self.assertEqual(im["params"]["size"], "1024x1024")   # parâmetro inválido volta ao padrão
        self.assertEqual(out["nodes"][2]["params"]["duration"], 30)
        self.assertEqual([n["x"] for n in out["nodes"]], [100, 460, 820])
        self.assertTrue(all(n["id"].startswith("n_") for n in out["nodes"]))

    def test_problems_flag_missing_inputs(self):
        out = F.build({"nodes": [{"key": "i", "type": "image"}, {"key": "e", "type": "editor"}], "edges": []})
        self.assertEqual(len(F.problems(out)), 2)
        self.assertEqual(F.problems({"nodes": [], "edges": []}), ["o fluxo está vazio"])

    def test_fallback_picks_a_template_from_the_words(self):
        kinds = lambda r: [n["type"] for n in F.build(F.fallback_plan(r))["nodes"]]  # noqa: E731
        self.assertIn("editor", kinds("cena de farol com narração"))
        self.assertEqual(kinds("uma gato"), ["text", "image"])
        self.assertEqual(kinds("anime um astronauta em vídeo"), ["text", "image", "video"])
        self.assertTrue(all(F.problems(F.build(F.fallback_plan(r))) == [] for r in ("gato", "vídeo", "cena", "estilo aquarela")))


class PipelineTests(unittest.TestCase):
    def test_ai_planner_and_reviewer_with_a_four_agent_table(self):
        import tempfile
        from unittest import mock

        from openflow.storage import Store

        calls = []

        class Prov:
            vision, model, thinking, cfg = False, "m", "off", {"id": "x"}

            def chat(self, messages, system="", **kw):
                text = messages[0]["content"]
                calls.append("[[OPENFLOW_AGENT:flow_reviewer]]" in system and "reviewer" or "planner")
                if "Flow Reviewer" in text:
                    return json.dumps({"approved": True, "score": 9, "summary": "ok", "issues": []})
                return json.dumps({"title": "Farol", "nodes": [{"key": "a", "type": "text", "params": {"text": "um farol"}}, {"key": "b", "type": "image"}], "edges": [{"from": "a", "to": "b", "port": "prompt"}]})

        store = Store(Path(tempfile.mkdtemp()))
        store.save_settings({"active": {"generation": "openai"}, "canvas": {"agents": 4, "effort": "high"}})
        events = []
        with mock.patch.object(F, "build_provider", return_value=Prov()):
            out = F.FlowPipeline(store, events.append).run({"prompt": "um farol", "existing": []})
        self.assertEqual([n["type"] for n in out["nodes"]], ["text", "image"])
        self.assertEqual(out["team"]["agents"], 4)
        self.assertEqual(calls.count("planner"), 5)   # 4 agentes + o Sintetizador
        self.assertEqual(out["warnings"], [])


class ApiTests(ServerCase):
    def test_flow_job_in_demo_mode_returns_a_runnable_flow_with_the_team(self):
        status, cv = self.c.json("POST", "/api/projects", {"name": "Fluxo", "template": "blank"})
        self.assertIn(status, (200, 201))
        status, r = self.c.json("POST", f"/api/projects/{cv['id']}/flow", {"prompt": "uma thumb com um gato", "team": {"agents": 4, "effort": "mega"}, "x": 500, "y": 40})
        self.assertEqual(status, 200, r)
        events = self.c.sse(f"/api/jobs/{r['job_id']}/events")
        start = next(e for e in events if e["type"] == "start")
        self.assertEqual((start["team"]["agents"], start["team"]["effort"]), (4, "mega"))
        done = next(e for e in events if e["type"] == "done")
        self.assertEqual([n["type"] for n in done["nodes"]], ["text", "image"])
        self.assertEqual(done["nodes"][0]["x"], 500)
        self.assertEqual(len(done["edges"]), 1)
        status, _ = self.c.json("POST", f"/api/projects/{cv['id']}/flow", {"prompt": ""})
        self.assertEqual(status, 400)
        status, _ = self.c.json("POST", "/api/projects/nao-existe/flow", {"prompt": "x"})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
