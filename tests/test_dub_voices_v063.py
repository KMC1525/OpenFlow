"""v0.63: vozes customizadas na Dublagem — nós Voz ligados à porta «Vozes» (uma ou várias) dão uma voz a cada personagem do roteiro.

Roda com provedores de voz de mentira (que anotam o que foi pedido) e o ffmpeg real; não há modelo de voz de verdade aqui. Que um modelo de voz de verdade soe como a pessoa que cada personagem deveria ser não é verificado."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import engine as engine_mod
from openflow.canvas import procedural as proc
from openflow.canvas import schema, speech
from openflow.canvas import subtitles as sub
from openflow.canvas.engine import CanvasEngine
from openflow.canvas.media import Media, MediaProvider
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
S = lambda *texts: [sub.seg(i, i + 1, t) for i, t in enumerate(texts)]  # noqa: E731
NAMES = [["Maria", "tara"], ["João", "leo"], ["Narradora"]]


class SpeakerTests(unittest.TestCase):
    def test_names_are_compared_without_accents_or_case(self):
        self.assertEqual(sub.norm_name("  João  da-Silva "), "joao da silva")
        self.assertEqual(sub.norm_name("MARIA"), sub.norm_name("maria"))
        self.assertEqual(sub.norm_name("!!"), "")

    def test_the_three_mark_forms_and_the_sticky_voice(self):
        out, warns = sub.assign_speakers(S("Maria: Olá, tudo bem?", "Tudo certo por aqui.", "[João] Oi!", "(narradora) Eles riram.", "joão: de novo"), NAMES)
        self.assertEqual(out, [(0, "Olá, tudo bem?"), (0, "Tudo certo por aqui."), (1, "Oi!"), (2, "Eles riram."), (1, "de novo")])   # a marca vale até a próxima
        self.assertEqual(warns, [])

    def test_the_voice_name_works_as_an_alias_and_the_first_voice_is_the_default(self):
        out, _ = sub.assign_speakers(S("Sem marca no começo", "TARA: com o nome da voz", "Leo: outra"), NAMES)
        self.assertEqual([i for i, _ in out], [0, 0, 1])
        self.assertEqual(out[1][1], "com o nome da voz")

    def test_only_known_names_are_marks(self):
        out, warns = sub.assign_speakers(S("(rindo) Que bom", "[Música] tema", "Atenção: o trem chega", "Maria: oi"), NAMES)
        self.assertEqual([t for _, t in out], ["(rindo) Que bom", "[Música] tema", "Atenção: o trem chega", "oi"])      # nada que não seja um locutor conhecido é cortado
        self.assertEqual([i for i, _ in out], [0, 0, 0, 0])

    def test_an_empty_line_after_the_mark_is_not_a_mark(self):
        out, _ = sub.assign_speakers(S("Maria:", "Maria: fala"), NAMES)
        self.assertEqual(out[0], (0, "Maria:"))

    def test_a_repeated_unknown_name_is_stripped_and_reported(self):
        out, warns = sub.assign_speakers(S("João: oi", "Fulano: bom dia", "Fulano: tchau", "Ciclano: uma vez só"), NAMES)
        self.assertEqual([t for _, t in out], ["oi", "bom dia", "tchau", "Ciclano: uma vez só"])           # «Fulano» repete: é um personagem; «Ciclano» aparece uma vez: pode ser texto
        self.assertEqual([i for i, _ in out], [1, 1, 1, 1])                                                  # sem voz própria: continuam com a voz anterior
        self.assertEqual(len(warns), 1)
        self.assertIn("«Fulano»", warns[0])
        self.assertNotIn("Ciclano", warns[0])

    def test_alternate_mode(self):
        out, warns = sub.assign_speakers(S("a", "b", "c", "d", "e"), NAMES[:2], "alternate")
        self.assertEqual([i for i, _ in out], [0, 1, 0, 1, 0])
        self.assertEqual(warns, [])
        out, _ = sub.assign_speakers(S("Maria: a", "b"), NAMES[:2], "alternate")
        self.assertEqual(out, [(0, "a"), (1, "b")])                                                          # a marca conhecida sai do texto mesmo alternando

    def test_several_voices_but_no_marks_warns(self):
        out, warns = sub.assign_speakers(S("a", "b"), NAMES)
        self.assertEqual([i for i, _ in out], [0, 0])
        self.assertEqual(len(warns), 1)
        self.assertIn("3 vozes ligadas", warns[0])
        self.assertEqual(sub.assign_speakers(S("a", "b"), NAMES[:1])[1], [])                                 # uma voz só: nada a avisar
        self.assertEqual(sub.assign_speakers([], NAMES), ([], ["Há 3 vozes ligadas, mas nenhuma fala tem marca de personagem («Nome: fala»): usei só a primeira voz. Marque as falas com o nome do nó Voz ou escolha «Alternar entre as vozes»."]))


class SchemaTests(unittest.TestCase):
    def test_the_voices_port(self):
        self.assertEqual([p[0] for p in schema.NODE_TYPES["dub"]["ins"]], ["media", "script", "voices"])
        accepts = schema.port_def("dub", "voices")["accepts"]
        self.assertTrue(schema.compatible(schema.NODE_TYPES["voice"]["out"], accepts))      # a saída de um nó Voz liga na porta
        self.assertFalse(schema.compatible("text", accepts))
        self.assertTrue(schema.port_def("dub", "voices")["multi"])                          # uma ou várias

    def test_assign_param(self):
        self.assertEqual(schema.normalize_params("dub", {"assign": "alternate"})["assign"], "alternate")
        self.assertEqual(schema.normalize_params("dub", {"assign": "x"})["assign"], "labels")
        self.assertEqual(schema.normalize_params("dub", {})["assign"], "labels")


class FakeVoice(MediaProvider):
    id, label, caps = "fake", "Fake", ("voice",)

    def __init__(self, tag=""):
        super().__init__({"id": "fake"})
        self.tag, self.calls = tag, []

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        self.calls.append({"text": text, "voice": voice, "speed": speed, "model": model, "extra": extra, "instructions": instructions})
        return Media(proc.babble(text, speed, 1), "audio/wav")


class Project:
    def __init__(self, script, voices, dub=None, extra_nodes=(), extra_edges=(), seconds=9.0):
        self.store = Store(Path(tempfile.mkdtemp()))
        self.cs = self.store.projects
        self.cid = self.cs.create("vozes")["id"]
        a = self.cs.add_asset(self.cid, proc.music("calma", seconds, 1), "wav", "audio", name="aula.wav", mime="audio/wav", provider="upload")
        nodes = [{"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [a["id"]]}}, {"id": "d", "type": "dub", "x": 0, "y": 0, "params": dict({"language": "keep"}, **(dub or {}))}]
        edges = [{"from": "u", "to": "d", "port": "media"}]
        if script is not None:
            nodes.append({"id": "t", "type": "text", "x": 0, "y": 0, "params": {"text": script}})
            edges.append({"from": "t", "to": "d", "port": "script"})
        for i, v in enumerate(voices):
            nodes.append({"id": f"v{i}", "type": "voice", "x": 0, "y": 0, **v})
            edges.append({"from": f"v{i}", "to": "d", "port": "voices"})
        self.cs.save_layout(self.cid, {"nodes": nodes + list(extra_nodes), "edges": edges + list(extra_edges)})

    def run(self, provider=None, force=True, targets=None):
        self.events = []
        ctx = [mock.patch.object(engine_mod, "build_media", side_effect=provider if callable(provider) else None, return_value=provider if not callable(provider) else None),
               mock.patch.object(speech, "build_media", side_effect=provider if callable(provider) else None, return_value=provider if not callable(provider) else None)] if provider else []
        for c in ctx:
            c.start()
        try:
            CanvasEngine(self.store, self.cid, self.events.append, lambda: False).run(targets, force)
        finally:
            for c in ctx:
                c.stop()
        return self.cs.get(self.cid)

    def errors(self):
        return {e["id"]: e.get("message") for e in self.events if e.get("type") == "node" and e.get("state") == "error"}

    def states(self):
        return {e["id"]: e["state"] for e in self.events if e.get("type") == "node"}

    def warnings(self, nid="d"):
        return [w for e in self.events if e.get("type") == "node" and e.get("id") == nid for w in e.get("warnings", [])]

    @staticmethod
    def result(cv, nid):
        return next(n for n in cv["nodes"] if n["id"] == nid)["result"]


MARIA = {"title": "Maria", "params": {"voice": "tara", "speed": 1.1}}
JOAO = {"title": "João", "params": {"voice": "leo", "speed": 0.9}}
SCRIPT = "Maria: Bom dia, pessoal.\nJoão: Bom dia! Tudo bem?\nTudo ótimo por aqui.\n[Maria] Vamos começar."


@unittest.skipUnless(FF, "sem ffmpeg")
class DubVoicesTests(unittest.TestCase):
    def test_each_character_speaks_with_their_own_voice(self):
        pj = Project(SCRIPT, [MARIA, JOAO])
        fake = FakeVoice()
        cv = pj.run(fake)
        self.assertEqual(pj.errors(), {})
        self.assertEqual([(c["text"], c["voice"], c["speed"]) for c in fake.calls],
                         [("Bom dia, pessoal.", "tara", 1.1), ("Bom dia!", "leo", 0.9), ("Tudo bem?", "leo", 0.9), ("Tudo ótimo por aqui.", "leo", 0.9), ("Vamos começar.", "tara", 1.1)])
        text = self.result(cv)["text"]
        self.assertIn("Maria: Bom dia, pessoal.", text)
        self.assertIn("João: Tudo ótimo por aqui.", text)
        self.assertTrue(any("Maria (2 falas), João (3 falas)" in w for w in pj.warnings()))
        self.assertEqual(len(self.result(cv)["assets"]), 1)

    result = staticmethod(lambda cv, nid="d": next(n for n in cv["nodes"] if n["id"] == nid)["result"])

    def test_a_single_connected_voice_replaces_the_node_s_own_voice(self):
        pj = Project("Uma fala simples. Outra fala.", [{"title": "Locutor", "params": {"voice": "ana", "speed": 1.3}}], dub={"voice": "padrao", "speed": 0.7})
        fake = FakeVoice()
        pj.run(fake)
        self.assertEqual(pj.errors(), {})
        self.assertTrue(fake.calls)
        self.assertTrue(all((c["voice"], c["speed"]) == ("ana", 1.3) for c in fake.calls))
        self.assertFalse(any("Vozes usadas" in w for w in pj.warnings()))      # uma voz só: sem o resumo

    def test_without_connected_voices_the_node_s_own_voice_is_used_as_before(self):
        pj = Project("Uma fala simples.", [], dub={"voice": "padrao", "speed": 0.8})
        fake = FakeVoice()
        pj.run(fake)
        self.assertEqual([(c["voice"], c["speed"]) for c in fake.calls], [("padrao", 0.8)])

    def test_alternate_between_the_voices(self):
        pj = Project("Primeira fala. Segunda fala. Terceira fala. Quarta fala.", [MARIA, JOAO], dub={"assign": "alternate"})
        fake = FakeVoice()
        pj.run(fake)
        self.assertEqual([c["voice"] for c in fake.calls], ["tara", "leo", "tara", "leo"])

    def test_several_voices_without_marks_use_the_first_and_warn(self):
        pj = Project("Uma fala sem marca. Outra fala sem marca.", [MARIA, JOAO])
        fake = FakeVoice()
        pj.run(fake)
        self.assertEqual({c["voice"] for c in fake.calls}, {"tara"})
        self.assertTrue(any("nenhuma fala tem marca de personagem" in w for w in pj.warnings()))

    def test_untitled_voices_answer_to_the_voice_name_and_to_voz_n(self):
        pj = Project("tara: primeira\nVoz 2: segunda\nleo: terceira", [{"params": {"voice": "tara"}}, {"params": {"voice": "leo"}}])
        fake = FakeVoice()
        pj.run(fake)
        self.assertEqual([(c["text"], c["voice"]) for c in fake.calls], [("primeira", "tara"), ("segunda", "leo"), ("terceira", "leo")])

    def test_each_voice_can_use_its_own_provider(self):
        built = {}

        def build(settings, pid, ctl, models_dir):
            built.setdefault(pid, FakeVoice(pid))
            return built[pid]
        pj = Project("Maria: oi\nJoão: olá", [{"title": "Maria", "params": {"voice": "a", "provider": "demo"}}, {"title": "João", "params": {"voice": "b", "provider": "local_hf"}}])
        pj.run(build)
        self.assertEqual(pj.errors(), {})
        self.assertEqual([c["voice"] for c in built["demo"].calls], ["a"])
        self.assertEqual([c["voice"] for c in built["local_hf"].calls], ["b"])

    def test_the_voice_node_style_goes_to_the_model(self):
        style = {"id": "sp", "type": "style_prompt", "x": 0, "y": 0, "params": {"text": "fale com carinho e calma", "global": False}}
        pj = Project("Maria: oi tudo bem", [MARIA], extra_nodes=[style], extra_edges=[{"from": "sp", "to": "v0", "port": "style"}])
        fake = FakeVoice()
        pj.run(fake)
        self.assertEqual(pj.errors(), {})
        self.assertIn("carinho", fake.calls[0]["instructions"])

    def test_a_node_that_is_not_a_voice_is_ignored_with_a_warning(self):
        pj = Project("Maria: oi", [MARIA], extra_nodes=[{"id": "m", "type": "sound", "title": "Trovão", "x": 0, "y": 0, "params": {}}], extra_edges=[{"from": "m", "to": "d", "port": "voices"}])
        fake = FakeVoice()
        pj.run(fake)
        self.assertTrue(any("«Trovão» não é um nó Voz" in w for w in pj.warnings()))
        self.assertEqual([c["voice"] for c in fake.calls], ["tara"])

    def test_the_dub_does_not_wait_for_the_voice_nodes(self):
        pj = Project(SCRIPT, [MARIA, JOAO])
        cv = CanvasEngine(pj.store, pj.cid, lambda e: None, lambda: False).canvas()
        eng = CanvasEngine(pj.store, pj.cid, lambda e: None, lambda: False)
        plan = eng.plan(cv, ["d"])
        self.assertIn("d", plan)
        self.assertNotIn("v0", plan)                                    # as vozes são configuração, não etapas do caminho
        self.assertNotIn("v1", plan)
        self.assertEqual(eng._index(cv)["preds"]["d"], ["u", "t"])

    def test_a_failing_voice_node_does_not_skip_the_dub(self):
        pj = Project("Maria: oi", [MARIA], extra_nodes=[], extra_edges=[])
        cv = pj.cs.get(pj.cid)
        next(n for n in cv["nodes"] if n["id"] == "v0")["params"]["text"] = "fala de exemplo"          # o nó Voz TEM texto e vai gerar um áudio de exemplo
        pj.cs.save_layout(pj.cid, {"nodes": cv["nodes"], "edges": cv["edges"]})
        fake = FakeVoice()

        def boom(text, **kw):
            if text == "fala de exemplo":
                raise ValueError("falhou de propósito")
            return Media(proc.babble(text, 1.0, 1), "audio/wav")
        fake.voice = boom
        pj.run(fake)
        self.assertIn("v0", pj.errors())
        self.assertEqual(pj.states()["d"], "done")                       # a Dublagem rodou mesmo assim

    def test_a_voice_node_without_text_feeding_a_dub_is_not_an_error(self):
        pj = Project("Maria: oi", [MARIA])
        pj.run(FakeVoice())
        self.assertEqual(pj.errors(), {})
        self.assertEqual(pj.states()["v0"], "done")
        self.assertTrue(any("só define a voz" in w for w in pj.warnings("v0")))

    def test_a_loose_voice_node_without_text_is_still_an_error(self):
        store = Store(Path(tempfile.mkdtemp()))
        cid = store.projects.create("x")["id"]
        store.projects.save_layout(cid, {"nodes": [{"id": "v", "type": "voice", "x": 0, "y": 0, "params": {}}], "edges": []})
        ev = []
        CanvasEngine(store, cid, ev.append, lambda: False).run(None, True)
        self.assertTrue(any(e.get("state") == "error" and "precisa de um texto" in (e.get("message") or "") for e in ev))

    def test_the_cache_follows_the_voices_but_not_their_sample_audio(self):
        pj = Project(SCRIPT, [MARIA, JOAO])
        fake = FakeVoice()
        pj.run(fake)
        pj.run(fake, force=False)
        self.assertEqual(pj.states()["d"], "cached")                     # nada mudou
        cv = pj.cs.get(pj.cid)
        next(n for n in cv["nodes"] if n["id"] == "v0")["params"]["voice"] = "outra"
        pj.cs.save_layout(pj.cid, {"nodes": cv["nodes"], "edges": cv["edges"]})
        fake2 = FakeVoice()
        pj.run(fake2, force=False)
        self.assertEqual(pj.states()["d"], "done")                       # trocar a voz de um personagem refaz a dublagem
        self.assertIn("outra", [c["voice"] for c in fake2.calls])
        cv = pj.cs.get(pj.cid)
        next(n for n in cv["nodes"] if n["id"] == "v1")["title"] = "Zé"
        pj.cs.save_layout(pj.cid, {"nodes": cv["nodes"], "edges": cv["edges"]})
        pj.run(FakeVoice(), force=False)
        self.assertEqual(pj.states()["d"], "done")                       # e o nome do personagem também (muda quem fala o quê)

    def test_the_sample_audio_regenerating_does_not_redo_the_dub(self):
        pj = Project(SCRIPT, [MARIA])
        cv = pj.cs.get(pj.cid)
        next(n for n in cv["nodes"] if n["id"] == "v0")["params"]["text"] = "um exemplo"
        pj.cs.save_layout(pj.cid, {"nodes": cv["nodes"], "edges": cv["edges"]})
        pj.run(FakeVoice())
        pj.run(FakeVoice(), force=False)
        self.assertEqual(pj.states()["d"], "cached")
        pj.run(FakeVoice(), force=True, targets=["v0"])                  # o áudio de exemplo foi refeito (força) e o hash da Dublagem continua o mesmo
        pj.run(FakeVoice(), force=False)
        self.assertEqual(pj.states()["d"], "cached")


if __name__ == "__main__":
    unittest.main()
