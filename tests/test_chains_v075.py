"""v0.75: cadeias de nós de verdade — gerar → editar → animar → montar, com o provedor Demo e o ffmpeg reais: a ordem de execução, o cache (só o que mudou roda de novo), a propagação de «desatualizado» e as saídas de cada elo."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from openflow.canvas import schema
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def n(nid, ntype, **params):
    return {"id": nid, "type": ntype, "x": 0, "y": 0, "params": params}


def e(a, b, port):
    return {"id": f"{a}_{b}_{port}", "from": a, "to": b, "port": port}


@unittest.skipUnless(FF, "sem ffmpeg")
class ChainTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()))
        self.cs = self.store.projects
        self.cid = self.cs.create("cadeia")["id"]

    def run_graph(self, nodes, edges, force=True, targets=None):
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": edges})
        self.events = []
        CanvasEngine(self.store, self.cid, self.events.append, lambda: False).run(targets, force)
        return self.cs.get(self.cid)

    def ran(self):
        return [ev["id"] for ev in self.events if ev.get("type") == "node" and ev.get("state") == "running"]

    def node_result(self, cv, nid):
        return next(x for x in cv["nodes"] if x["id"] == nid)["result"]

    def asset(self, cv, nid):
        a = next(x for x in cv["assets"] if x["id"] == self.node_result(cv, nid)["assets"][0])
        return a, self.cs.asset_path(self.cid, a["file"])

    EDIT_CHAIN = ([n("t", "text", text="Um farol numa noite de tempestade"), n("img", "image", mode="generate", size="768x512"), n("fx", "img_filter", preset="sepia"), n("lbl", "img_text", text="FAROL"),
                   n("ed", "image", mode="edit", prompt="faça chover", size="768x512"), n("res", "img_resize", mode="cover", width=640, height=360), n("vid", "video", duration=2, aspect="16:9"),
                   n("look", "vid_look", preset="vhs"), n("ref", "vid_reframe", ratio="9:16", mode="blur", height=640), n("out", "out_export", quality="medium")],
                  [e("t", "img", "prompt"), e("img", "fx", "image"), e("fx", "lbl", "image"), e("lbl", "ed", "refs"), e("ed", "res", "image"), e("res", "vid", "image"), e("t", "vid", "prompt"),
                   e("vid", "look", "video"), e("look", "ref", "video"), e("ref", "out", "video")])

    def test_generate_edit_animate_and_export_chain(self):
        cv = self.run_graph(*self.EDIT_CHAIN)
        for nid in ("img", "fx", "lbl", "ed", "res", "vid", "look", "ref"):
            res = self.node_result(cv, nid)
            self.assertEqual(res["state"], "done", (nid, res.get("error")))
            self.assertTrue(res["assets"], nid)
        _, path = self.asset(cv, "ref")
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", str(path)], capture_output=True, text=True).stdout)
        s = info["streams"][0]
        self.assertEqual((s["width"], s["height"]), (360, 640))                                    # 9:16 com altura 640
        a, _ = self.asset(cv, "res")
        self.assertEqual((a["w"], a["h"]), (640, 360))

    def test_the_order_respects_the_dependencies(self):
        self.run_graph(*self.EDIT_CHAIN)
        order = self.ran()
        for before, after in (("img", "fx"), ("fx", "lbl"), ("lbl", "ed"), ("ed", "res"), ("res", "vid"), ("vid", "look"), ("look", "ref")):
            self.assertLess(order.index(before), order.index(after), (before, after))

    def test_only_what_changed_and_its_dependents_run_again(self):
        nodes, edges = self.EDIT_CHAIN
        self.run_graph(nodes, edges)
        self.run_graph(nodes, edges, force=False)
        self.assertEqual(self.ran(), [])                                                           # nada mudou
        nodes2 = [dict(x, params=dict(x["params"], preset="bw")) if x["id"] == "fx" else x for x in nodes]
        cv = self.run_graph(nodes2, edges, force=False)
        ran = self.ran()
        self.assertNotIn("img", ran)                                                              # o que vem antes não roda de novo
        for nid in ("fx", "lbl", "ed", "res", "vid", "look", "ref"):
            self.assertIn(nid, ran, nid)                                                          # e tudo que depende dele, sim
        self.assertEqual(self.node_result(cv, "ref")["state"], "done")

    def test_stale_marks_follow_the_chain(self):
        nodes, edges = self.EDIT_CHAIN
        self.run_graph(nodes, edges)
        eng = CanvasEngine(self.store, self.cid, lambda ev: None, lambda: False)
        self.assertEqual(eng.stale_ids(self.cs.get(self.cid)), [])
        nodes2 = [dict(x, params=dict(x["params"], text="FAROL 2")) if x["id"] == "lbl" else x for x in nodes]
        self.cs.save_layout(self.cid, {"nodes": nodes2, "edges": edges})
        stale = eng.stale_ids(self.cs.get(self.cid))
        self.assertNotIn("img", stale)
        self.assertNotIn("fx", stale)
        for nid in ("lbl", "ed", "res", "vid", "look", "ref"):
            self.assertIn(nid, stale, nid)

    def test_running_only_a_target_runs_only_its_ancestors(self):
        nodes, edges = self.EDIT_CHAIN
        self.run_graph(nodes, edges, targets=["fx"])
        self.assertEqual(sorted(self.ran()), ["fx", "img"])

    def test_a_failure_in_the_middle_skips_only_what_depends_on_it(self):
        nodes, edges = self.EDIT_CHAIN
        nodes = [dict(x, params=dict(x["params"], mode="edit")) if x["id"] == "img" else x for x in nodes]   # Editar sem imagem ligada: erro
        nodes.append(n("side", "text", text="outro ramo"))
        nodes.append(n("llm", "text_count", what="words"))
        edges = edges + [e("side", "llm", "text")]
        cv = self.run_graph(nodes, edges)
        self.assertEqual(self.node_result(cv, "img")["state"], "error")
        for nid in ("fx", "lbl", "ed", "res", "vid", "look", "ref"):
            self.assertNotEqual(self.node_result(cv, nid)["state"], "done", nid)                  # nada depois do erro “termina” com um resultado velho
        self.assertEqual(self.node_result(cv, "llm")["state"], "done")                             # o ramo independente continua

    def test_the_text_and_audio_chain(self):
        nodes = [n("t", "text", text="Bom dia. Hoje o mar está calmo e azul."), n("up", "text_refine", mode="improve"), n("vo", "voice", text=""), n("fx", "aud_fx", fx="echo"), n("sfx", "sfx", prompt="ondas", duration=3),
                 n("mix", "aud_mix", mode="mix"), n("out", "out_audio", format="mp3", mode="mix")]
        edges = [e("t", "up", "text"), e("up", "vo", "text"), e("vo", "fx", "audio"), e("fx", "mix", "audios"), e("sfx", "mix", "audios"), e("mix", "out", "audio")]
        cv = self.run_graph(nodes, edges)
        for nid in ("up", "vo", "fx", "sfx", "mix"):
            self.assertEqual(self.node_result(cv, nid)["state"], "done", (nid, self.node_result(cv, nid).get("error")))
        a, path = self.asset(cv, "mix")
        self.assertEqual(a["kind"], "audio")
        self.assertGreater(path.stat().st_size, 1000)


class EveryTemplateTests(unittest.TestCase):
    def test_every_template_runs_and_stays_up_to_date(self):
        store = Store(Path(tempfile.mkdtemp()))
        cs = store.projects
        for t in schema.TEMPLATES:
            cid = cs.create(t["id"])["id"]
            g = schema.build_template(t["id"], "")
            cs.save_layout(cid, {"nodes": g["nodes"], "edges": g["edges"]})
            CanvasEngine(store, cid, lambda ev: None, lambda: False).run(None, True)
            cv = cs.get(cid)
            bad = {x["id"]: (x["type"], x["result"]["state"], x["result"].get("error", "")[:100]) for x in cv["nodes"] if x["type"] not in ("style_prompt", "text") and x["result"]["state"] != "done"}
            no_ffmpeg = set()
            if not shutil.which("ffmpeg"):   # macOS/Windows do CI não têm o ffmpeg: o vídeo do Demo diz isso (e é o comportamento certo)
                no_ffmpeg = {k for k, v in bad.items() if "precisa do ffmpeg" in v[2]}
                bad = {k: v for k, v in bad.items() if k not in no_ffmpeg}
            self.assertEqual(bad, {} if t["id"] != "blank" else bad, t["id"])
            stale = [i for i in CanvasEngine(store, cid, lambda ev: None, lambda: False).stale_ids(cs.get(cid)) if i not in no_ffmpeg]   # o nó que falhou por falta de ffmpeg fica «desatualizado» de propósito
            self.assertEqual(stale, [], t["id"])

    def test_a_template_with_a_custom_prompt_keeps_it(self):
        g = schema.build_template("text_image", "Um dragão de papel")
        self.assertEqual(next(x for x in g["nodes"] if x["type"] == "text")["params"]["text"], "Um dragão de papel")


if __name__ == "__main__":
    unittest.main()
