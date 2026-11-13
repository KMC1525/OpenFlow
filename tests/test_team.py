"""Equipe de agentes de todas as seções: 1/2/4/8/12/16/20/24/28/32 agentes (mesa em paralelo + revisão entre pares + Sintetizador) e esforço Low … Omni (`openflow/team.py`)."""
import json
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import team  # noqa: E402
from openflow.agents.runner import Cancelled, Runner  # noqa: E402
from openflow.storage import DEFAULT_SETTINGS, Store  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402
from tests.helpers import ServerCase  # noqa: E402

INFO = {"id": "x", "label": "Modelo X", "model": "m1", "demo": False, "auto": False, "reason": ""}


class PureTests(unittest.TestCase):
    def test_the_counts_and_the_eight_levels_are_the_code_ones(self):
        self.assertEqual(team.COUNTS, (1, 2, 4, 8, 12, 16, 20, 24, 28, 32))
        self.assertEqual(team.LEVELS, ("low", "medium", "high", "extra", "mega", "max", "ultra", "omni"))
        self.assertEqual(len(team.LENSES), team.MAX_AGENTS)

    def test_two_agents_run_as_a_table_of_two_with_a_synthesizer(self):
        t = team.make(2, "low")
        self.assertEqual((t.agents, t.multi, t.workers, t.peers), (2, True, 2, 0))
        self.assertEqual(team.calls_per_step(2), 3)       # 2 rascunhos em paralelo + 1 síntese
        calls = []

        def ask(ins, pl):
            calls.append(ins)
            return {"v": len(calls)}

        out = team.ensemble_json(ask, t, "tarefa", {"x": 1})
        self.assertIsNotNone(out)
        self.assertEqual(len(calls), 3)

    def test_agents_snap_to_the_nearest_allowed_count(self):
        got = {v: team.normalize_agents(v) for v in (1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 14, 16, 18, 22, 26, 30, 32, 99, 0, -3, "8", "x", None, 4.7)}
        self.assertEqual(got, {1: 1, 2: 2, 3: 4, 4: 4, 5: 4, 6: 8, 7: 8, 8: 8, 10: 12, 11: 12, 12: 12, 14: 16, 16: 16, 18: 20, 22: 24, 26: 28, 30: 32, 32: 32, 99: 32, 0: 1, -3: 1, "8": 8, "x": 1, None: 1, 4.7: 4})
        self.assertEqual(team.normalize_effort("OMNI"), "omni")
        self.assertEqual((team.normalize_effort("zzz"), team.normalize_effort(None, "low")), ("high", "low"))

    def test_team_from_settings_and_request(self):
        t = team.from_config({"agents": 8, "effort": "mega"})
        self.assertEqual((t.agents, t.effort, t.multi, t.workers, t.thinking), (8, "mega", True, 8, "xhigh"))
        t = team.from_config({"agents": 8, "effort": "mega"}, {"team": {"agents": 16, "effort": "low"}})
        self.assertEqual((t.agents, t.effort, t.workers), (16, "low", 16))
        self.assertEqual(team.make(32).workers, 32)   # com 32 agentes, todos ao mesmo tempo
        self.assertEqual(team.from_config({"agents": "off"}).agents, 1)   # o «agents» antigo do Chat («off»/«plan»/«review») não é um número
        self.assertEqual(team.from_config({}).public(), {"agents": 1, "effort": "high", "thinking": "medium", "peers": 0, "calls_per_step": 1})
        self.assertEqual(team.make(4, "omni").public()["calls_per_step"], 5)
        self.assertEqual([team.make(n).public()["calls_per_step"] for n in (16, 20, 24, 28, 32)], [17, 26, 31, 36, 41])   # a partir de 20 há N/4 revisores entre pares
        self.assertEqual([team.make(n).peers for n in (1, 4, 16, 20, 24, 28, 32)], [0, 0, 0, 5, 6, 7, 8])

    def test_request_team_only_keeps_valid_choices(self):
        self.assertEqual(team.request_team({"team": {"agents": 12, "effort": "Ultra"}}), {"agents": 12, "effort": "ultra"})
        self.assertEqual(team.request_team({"agents": "4", "effort": "x"}), {"agents": 4})
        self.assertEqual(team.request_team({"team": {"agents": True}}), {})
        self.assertEqual(team.request_team("lixo"), {})

    def test_effort_moves_revisions_around_the_legacy_setting_with_high_as_the_neutral_point(self):
        rev = lambda lv, legacy: team.make(1, lv).revisions(legacy)  # noqa: E731
        self.assertEqual([rev(lv, 1) for lv in team.LEVELS], [0, 0, 1, 1, 2, 2, 3, 3])
        self.assertEqual([rev(lv, 0) for lv in team.LEVELS], [0, 0, 0, 0, 2, 2, 3, 3])   # quem desligou as revisões continua sem elas no High
        self.assertEqual(rev("high", 2), 2)
        self.assertEqual(rev("low", 2), 0)
        self.assertEqual(team.make(1, "omni").revisions(1, cap=2), 2)

    def test_options_lists_everything_the_screens_need(self):
        o = team.options()
        self.assertEqual(o["agents"], [1, 2, 4, 8, 12, 16, 20, 24, 28, 32])
        self.assertEqual([e["id"] for e in o["efforts"]], list(team.LEVELS))
        self.assertEqual(o["calls_per_step"], {"1": 1, "2": 3, "4": 5, "8": 9, "12": 13, "16": 17, "20": 26, "24": 31, "28": 36, "32": 41})

    def test_apply_thinking_only_where_the_model_supports_it(self):
        class P:
            thinking = "off"
            model = "claude-sonnet-4-5"
            cfg = {"id": "anthropic"}

        p = P()
        self.assertEqual(team.apply_thinking(p, team.make(1, "mega")), "xhigh")
        self.assertEqual(p.thinking, "xhigh")
        p.cfg = {"id": "ollama"}
        p.model = "llama3"
        self.assertEqual(team.apply_thinking(p, team.make(1, "omni")), "off")
        self.assertEqual(p.thinking, "off")
        self.assertEqual(team.apply_thinking(p, team.make(1, "omni"), "openai", "gpt-5"), "ultra")


class EnsembleTests(unittest.TestCase):
    def make_ask(self, fail_on=(), merge_fail=False, slow=None, peer_fail=()):
        calls, lock = [], threading.Lock()

        def ask(ins, pl):
            with lock:
                calls.append((ins, pl))
                n = len(calls)
            if ins.startswith("TEAM MODE — you are the Synthesizer"):
                if merge_fail:
                    return None
                return {"merged": True, "from": [d["agent"] for d in pl["drafts"]], "lenses": [d["lens"] for d in pl["drafts"]]}
            if ins.startswith("TEAM MODE — PEER REVIEW"):
                j = int(ins.split("peer reviewer ")[1].split(" of")[0])
                return None if j in peer_fail else {"peer": j, "read": len(pl["drafts"]), "from": [d["agent"] for d in pl["drafts"]]}
            who = int(ins.split("agent ")[1].split(" of")[0]) if ins.startswith("TEAM MODE — you are agent") else 0
            if who in fail_on:
                return None
            return {"draft": who}

        return ask, calls

    def test_one_agent_is_a_single_plain_call(self):
        ask, calls = self.make_ask()
        out = team.ensemble_json(ask, team.make(1), "Do it. Output JSON: {}", {"a": 1})
        self.assertEqual(out, {"draft": 0})
        self.assertEqual([c[0] for c in calls], ["Do it. Output JSON: {}"])

    def test_four_agents_draft_in_parallel_with_different_lenses_and_one_synthesizer(self):
        ask, calls = self.make_ask()
        out = team.ensemble_json(ask, team.make(4), "Do it. Output JSON: {}", {"a": 1})
        self.assertEqual(len(calls), 5)   # 4 rascunhos + 1 síntese
        self.assertEqual(out["from"], [1, 2, 3, 4])
        self.assertEqual(len(set(out["lenses"])), 4)
        drafts = [c for c in calls if "you are agent" in c[0]]
        self.assertTrue(all(c[0].endswith("Do it. Output JSON: {}") and c[1] == {"a": 1} for c in drafts))
        synth = [c for c in calls if "you are the Synthesizer" in c[0]][0]
        self.assertEqual(synth[1]["task_input"], {"a": 1})
        self.assertTrue(synth[0].endswith("Output JSON: {}"))   # o formato esperado continua no fim: o reparo de JSON o encontra

    def test_sixteen_agents_use_all_sixteen_lenses(self):
        ask, calls = self.make_ask()
        out = team.ensemble_json(ask, team.make(16), "x", {})
        self.assertEqual(len(calls), 17)
        self.assertEqual(sorted(set(out["lenses"])), sorted(k for k, _ in team.LENSES[:16]))   # 16 agentes: as 16 primeiras lentes, sem revisão entre pares
        self.assertFalse([c for c in calls if c[0].startswith("TEAM MODE — PEER REVIEW")])

    def test_thirty_two_agents_use_thirty_two_distinct_lenses_and_peer_review(self):
        ask, calls = self.make_ask()
        out = team.ensemble_json(ask, team.make(32), "x", {})
        drafts = [c for c in calls if "you are agent" in c[0]]
        self.assertEqual(len(drafts), 32)
        self.assertEqual(len({c[0].split("Your lens: ")[1].split(".")[0] for c in drafts}), 32)
        self.assertEqual(len(team.LENSES), 32)
        self.assertEqual(len(calls), 41)   # 32 rascunhos + 8 revisores + 1 síntese
        self.assertEqual(out["from"], [f"peer-{j}" for j in range(1, 9)])   # a síntese lê as versões revistas

    def test_big_teams_review_each_others_drafts_before_the_synthesis(self):
        for n, peers in ((20, 5), (24, 6), (28, 7)):
            ask, calls = self.make_ask()
            out = team.ensemble_json(ask, team.make(n), "Do it. Output JSON: {}", {"a": 1})
            reviewers = [c for c in calls if c[0].startswith("TEAM MODE — PEER REVIEW")]
            self.assertEqual((len(calls), len(reviewers)), (n + peers + 1, peers))
            self.assertTrue(all(len(c[1]["drafts"]) == n and c[1]["task_input"] == {"a": 1} and c[0].endswith("Output JSON: {}") for c in reviewers))   # cada revisor lê TODOS os rascunhos
            self.assertEqual(len(out["from"]), peers)

    def test_peer_review_falls_back_when_reviewers_fail(self):
        ask, calls = self.make_ask(peer_fail=(1, 2, 3, 4, 5))
        out = team.ensemble_json(ask, team.make(20), "x", {})
        self.assertEqual(out["from"], list(range(1, 21)))   # nenhum revisor valeu: a síntese lê os 20 rascunhos
        ask, calls = self.make_ask(peer_fail=(1, 2, 3, 4))
        out = team.ensemble_json(ask, team.make(20), "x", {})
        self.assertEqual(out["peer"], 5)   # só um revisor valeu: o resultado dele é o final (sem síntese de um só)
        self.assertEqual(len(calls), 20 + 5)
        ask, calls = self.make_ask(merge_fail=True)
        out = team.ensemble_json(ask, team.make(24), "x", {})
        self.assertEqual(out["peer"], 1)   # a síntese caiu: vale a primeira versão revisada

    def test_peer_review_is_skipped_for_small_teams_and_when_cancelled(self):
        ask, calls = self.make_ask()
        team.ensemble_json(ask, team.make(16), "x", {})
        self.assertFalse([c for c in calls if c[0].startswith("TEAM MODE — PEER REVIEW")])
        ask, calls = self.make_ask()
        team.ensemble_json(ask, team.make(20), "x", {}, cancelled=lambda: True)
        self.assertEqual(calls, [])

    def test_a_failing_agent_does_not_stop_the_table(self):
        ask, calls = self.make_ask(fail_on=(2, 3))
        out = team.ensemble_json(ask, team.make(4), "x", {})
        self.assertEqual(out["from"], [1, 4])

    def test_failed_synthesis_falls_back_to_the_first_valid_draft_and_no_draft_means_none(self):
        ask, _ = self.make_ask(merge_fail=True)
        self.assertEqual(team.ensemble_json(ask, team.make(4), "x", {}), {"draft": 1})
        ask, calls = self.make_ask(fail_on=(1, 2, 3, 4))
        self.assertIsNone(team.ensemble_json(ask, team.make(4), "x", {}))   # nenhum JSON válido: o chamador usa o método automático
        self.assertEqual(len(calls), 4)   # sem rascunhos não há o que sintetizar

    def test_a_single_valid_draft_skips_the_synthesizer(self):
        ask, calls = self.make_ask(fail_on=(2, 3, 4))
        self.assertEqual(team.ensemble_json(ask, team.make(4), "x", {}), {"draft": 1})
        self.assertEqual(len(calls), 4)

    def test_real_errors_surface_only_when_every_agent_failed_and_fatal_ones_always(self):
        class Boom(Exception):
            pass

        def always(ins, pl):
            raise Boom("rede")

        with self.assertRaises(Boom):
            team.ensemble_json(always, team.make(4), "x", {})

        def one_bad(ins, pl):
            if "agent 2 of" in ins:
                raise Boom("só um")
            return {"ok": 1}

        self.assertEqual(team.ensemble_json(one_bad, team.make(4), "x", {}, merge=False), {"ok": 1})
        with self.assertRaises(Boom):
            team.ensemble_json(one_bad, team.make(4), "x", {}, fatal=(Boom,))

    def test_a_long_set_of_drafts_is_trimmed_to_the_budget(self):
        seen = {}

        def ask(ins, pl):
            if "you are the Synthesizer" in ins:
                seen["n"] = len(pl["drafts"])
                return {"ok": 1}
            return {"big": "x" * 20000}

        team.ensemble_json(ask, team.make(8), "x", {})
        self.assertLess(seen["n"], 8)
        self.assertGreaterEqual(seen["n"], 1)

    def test_critique_returns_the_better_version_or_keeps_the_draft(self):
        self.assertEqual(team.critique_json(lambda i, p: {"better": p["draft"]["v"] + 1}, "x", {}, {"v": 1}), {"better": 2})
        self.assertEqual(team.critique_json(lambda i, p: None, "x", {}, {"v": 1}), {"v": 1})

        def boom(i, p):
            raise ValueError("x")

        self.assertEqual(team.critique_json(boom, "x", {}, {"v": 1}), {"v": 1})


class ScriptedProvider:
    """Provedor de JSON: guarda cada chamada; o «rascunho» do agente N devolve {"who": N}; a síntese devolve a união."""
    vision = False
    model = "m"
    thinking = "off"
    cfg = {"id": "x"}

    def __init__(self, reply=None):
        self.calls, self.lock, self.reply = [], threading.Lock(), reply

    def chat(self, messages, system="", temperature=0.8, max_tokens=100, json_mode=False, stream=False):
        text = messages[0]["content"] if isinstance(messages[0]["content"], str) else messages[0]["content"][0]["text"]
        with self.lock:
            self.calls.append({"text": text, "max_tokens": max_tokens, "thinking": self.thinking})
        if self.reply is not None:
            return self.reply(text)
        if "you are the Synthesizer" in text:
            payload = json.loads(text.split("INPUT_JSON:\n", 1)[1])
            return json.dumps({"title": "merged", "n": len(payload["drafts"])})
        if "CRITIQUE ROUND" in text:
            return json.dumps({"title": "critiqued"})
        return json.dumps({"title": "draft"})


class RunnerTests(TmpCase):
    def runner(self, provider, **cfg):
        events = []
        r = Runner(Store(self.tmp / "home"), events.append)
        r.provider = provider
        r.gen = {"temperature": 0.5, "max_tokens": 1000, "content": "free"}
        r.configure_team(cfg, None, "x")
        return r, events

    def test_default_team_keeps_the_old_single_call(self):
        prov = ScriptedProvider()
        r, _ = self.runner(prov)
        out, fb = r._agent("planner", "planner", "Plan. Output JSON: {}", {"a": 1}, lambda p: {"title": "fb"})
        self.assertEqual((out, fb, len(prov.calls)), ({"title": "draft"}, False, 1))
        self.assertEqual(prov.calls[0]["max_tokens"], 1000)

    def test_four_agents_run_a_table_per_step_and_the_logs_keep_every_agent(self):
        prov = ScriptedProvider()
        r, _ = self.runner(prov, agents=4, effort="high")
        out, fb = r._agent("designer", "architect", "Do. Output JSON: {}", {"a": 1}, lambda p: {"title": "fb"})
        self.assertEqual((out, fb), ({"title": "merged", "n": 4}, False))
        self.assertEqual(len(prov.calls), 5)
        self.assertEqual(len(r.logs), 5)   # um registro por agente + a síntese
        self.assertEqual(len({name for name, _ in r.logs}), 5)

    def test_revision_rounds_and_solo_steps_use_a_single_agent(self):
        prov = ScriptedProvider()
        r, _ = self.runner(prov, agents=8)
        r._agent("designer", "architect", "Fix. Output JSON: {}", {}, lambda p: {}, feedback=True)
        r._agent("polisher", "architect", "Polish. Output JSON: {}", {}, lambda p: {}, solo=True)
        self.assertEqual(len(prov.calls), 2)

    def test_invalid_json_from_every_agent_uses_the_deterministic_fallback(self):
        prov = ScriptedProvider(reply=lambda text: "isto não é JSON")
        r, events = self.runner(prov, agents=4)
        out, fb = r._agent("planner", "planner", "Plan. Output JSON: {}", {"a": 1}, lambda p: {"title": "fallback"})
        self.assertEqual((out, fb), ({"title": "fallback"}, True))
        self.assertTrue(any("fallback" in w for w in r.warnings))

    def test_high_effort_levels_enlarge_the_answer_and_planning_steps_get_a_critique_from_max(self):
        prov = ScriptedProvider()
        r, _ = self.runner(prov, effort="omni")
        out, _ = r._agent("planner", "planner", "Plan. Output JSON: {}", {}, lambda p: {})
        self.assertEqual(out, {"title": "critiqued"})   # Omni: o plano passa por uma rodada de crítica
        self.assertEqual(prov.calls[0]["max_tokens"], 2000)   # 1000 × 2,0
        prov = ScriptedProvider()
        r, _ = self.runner(prov, effort="high")
        r._agent("planner", "planner", "Plan. Output JSON: {}", {}, lambda p: {})
        self.assertEqual(len(prov.calls), 1)

    def test_thinking_is_requested_from_the_provider_when_supported(self):
        prov = ScriptedProvider()
        prov.model = "claude-sonnet-4-5"
        events = []
        r = Runner(Store(self.tmp / "h2"), events.append)
        r.provider = prov
        r.configure_team({"effort": "mega"}, None, "anthropic")
        self.assertEqual(prov.thinking, "xhigh")
        r.emit({"type": "start", "steps": []})
        self.assertEqual(events[0]["team"], {"agents": 1, "effort": "mega", "thinking": "xhigh", "peers": 0, "calls_per_step": 1})

    def test_cancelling_during_a_table_stops_the_step(self):
        prov = ScriptedProvider()
        r, _ = self.runner(prov, agents=4)
        r.cancelled = lambda: True
        with self.assertRaises(Cancelled):
            r._agent("planner", "planner", "x", {}, lambda p: {})


class SettingsTests(TmpCase):
    def test_every_section_has_a_team_with_safe_defaults(self):
        self.assertEqual(team.SECTIONS, ("generation", "canvas"))
        s = Store(self.tmp / "home").get_settings()
        for key in team.SECTIONS:
            self.assertEqual((s[key]["agents"], s[key]["effort"]), (1, "high"), key)

    def test_hand_edited_values_snap_to_valid_ones(self):
        st = Store(self.tmp / "home")
        st.save_settings({"generation": {"agents": 5, "effort": "ULTRA"}, "canvas": {"agents": 99, "effort": "nope"}})
        s = st.get_settings()
        self.assertEqual((s["generation"]["agents"], s["generation"]["effort"]), (4, "ultra"))
        self.assertEqual((s["canvas"]["agents"], s["canvas"]["effort"]), (32, "high"))

    def test_imported_settings_carry_the_team_but_never_a_secret(self):
        from openflow import uiprefs

        patch = uiprefs.import_patch({"schema": uiprefs.EXPORT_SCHEMA, "settings": {"canvas": {"agents": 4, "effort": "low"}, "voice": {"tts": {"api_key": "segredo", "engine": "browser"}}}})
        self.assertEqual(patch["canvas"], {"agents": 4, "effort": "low"})
        self.assertNotIn("api_key", patch["voice"]["tts"])


class ApiTests(ServerCase):
    def test_team_options_endpoint(self):
        status, o = self.c.json("GET", "/api/team")
        self.assertEqual(status, 200)
        self.assertEqual(o["agents"], [1, 2, 4, 8, 12, 16, 20, 24, 28, 32])
        self.assertEqual([e["id"] for e in o["efforts"]], list(team.LEVELS))
        self.assertTrue(all("hint" in e and "thinking" in e for e in o["efforts"]))

    def test_the_team_chosen_in_the_editor_reaches_the_flow_planner(self):
        status, p = self.c.json("POST", "/api/projects", {"name": "Equipe", "template": "blank"})
        self.assertEqual(status, 201)
        status, r = self.c.json("POST", f"/api/projects/{p['id']}/flow", {"prompt": "um gato dormindo", "agents": 4, "effort": "mega"})
        self.assertEqual(status, 200, r)
        events = self.c.sse(f"/api/jobs/{r['job_id']}/events")
        start = next(e for e in events if e["type"] == "start")
        self.assertEqual((start["team"]["agents"], start["team"]["effort"]), (4, "mega"))
        self.assertEqual(events[-2]["type"], "done")


if __name__ == "__main__":
    unittest.main()
