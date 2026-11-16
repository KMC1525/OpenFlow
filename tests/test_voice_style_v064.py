"""v0.64: Estilo de voz — o campo «Como é a voz» do nó Voz (e da Dublagem), logo abaixo do texto que será falado.

Nenhum modelo de voz de verdade foi usado: o que é verificado é o caminho da descrição até o provedor (`instructions`), o efeito que ela tem na voz de demonstração (tom, ritmo, volume), a escolha da voz do Orpheus
pelo gênero (sem rodar o modelo) e os avisos de quando o modelo não lê a descrição."""
import array
import io
import math
import unittest
import wave
from unittest import mock

from openflow.canvas import media as media_mod
from openflow.canvas import procedural as proc
from openflow.canvas import schema
from openflow.canvas import voicestyle as vs
from openflow.canvas.media import DemoMedia, LocalHFMedia, Media, MediaProvider
from tests.test_dub_voices_v063 import FF, Project

TEXT = "Bom dia a todos, vamos começar a reunião de hoje."


def pcm(data: bytes):
    w = wave.open(io.BytesIO(data), "rb")
    a = array.array("h")
    a.frombytes(w.readframes(w.getnframes()))
    return a, w.getframerate()


def seconds(data):
    a, sr = pcm(data)
    return len(a) / sr


def zero_crossings_per_second(data):
    a, sr = pcm(data)
    return sum(1 for i in range(1, len(a)) if (a[i - 1] < 0) != (a[i] < 0)) / (len(a) / sr)


def rms(data):
    a, _ = pcm(data)
    return math.sqrt(sum(x * x for x in a) / len(a))


class ComposeTests(unittest.TestCase):
    def test_description_first_then_the_project_style(self):
        self.assertEqual(vs.compose("grave e calma", "estilo do projeto"), "grave e calma\nestilo do projeto")
        self.assertEqual(vs.compose("  grave  ", ""), "grave")
        self.assertEqual(vs.compose("", "só o estilo"), "só o estilo")
        self.assertEqual(vs.compose("", ""), "")
        self.assertEqual(len(vs.compose("x" * 5000)), vs.MAX_LEN)


class TraitTests(unittest.TestCase):
    def test_words_move_the_pitch_the_pace_and_the_volume(self):
        self.assertLess(vs.traits("voz grave e profunda")["pitch"], 1.0)
        self.assertLess(vs.traits("masculina")["pitch"], 1.0)
        self.assertGreater(vs.traits("voz aguda")["pitch"], 1.0)
        self.assertGreater(vs.traits("feminina e jovem")["pitch"], vs.traits("feminina")["pitch"])      # somam
        self.assertGreater(vs.traits("rápida e animada")["rate"], 1.0)
        self.assertLess(vs.traits("calma e lenta")["rate"], 1.0)
        self.assertLess(vs.traits("sussurrando")["gain"], 1.0)
        self.assertLess(vs.traits("sussurrando")["gain"], vs.traits("suave")["gain"])

    def test_english_accents_and_case(self):
        self.assertEqual(vs.traits("DEEP voice, SLOW and quiet"), vs.traits("deep voice slow quiet"))
        self.assertLess(vs.traits("deep")["pitch"], 1.0)
        self.assertGreater(vs.traits("fast")["rate"], 1.0)
        self.assertEqual(vs.traits("BARÍTONO"), vs.traits("baritono"))
        self.assertEqual(vs.traits("GRAVE"), vs.traits("grave"))

    def test_nothing_recognized_changes_nothing(self):
        self.assertEqual(vs.traits(""), {"pitch": 1.0, "rate": 1.0, "gain": 1.0})
        self.assertEqual(vs.traits("uma pessoa bem simpática do interior"), {"pitch": 1.0, "rate": 1.0, "gain": 1.0})
        self.assertEqual(vs.traits("graveto"), {"pitch": 1.0, "rate": 1.0, "gain": 1.0})              # palavra inteira: «graveto» não é «grave»

    def test_limits(self):
        t = vs.traits("feminina aguda jovem criança fina")
        self.assertLessEqual(t["pitch"], 1.6)
        t = vs.traits("grave profunda masculina velha baixa")
        self.assertGreaterEqual(t["pitch"], 0.6)
        self.assertGreaterEqual(vs.traits("sussurrando suave baixinho")["gain"], 0.4)
        self.assertLessEqual(vs.traits("gritando forte")["gain"], 1.0)                                  # só se pede mais baixo


class GenderTests(unittest.TestCase):
    def test_gender(self):
        self.assertEqual(vs.gender("voz feminina, jovem"), "female")
        self.assertEqual(vs.gender("uma mulher calma"), "female")
        self.assertEqual(vs.gender("a young woman"), "female")
        self.assertEqual(vs.gender("voz masculina grave"), "male")
        self.assertEqual(vs.gender("um homem"), "male")
        self.assertEqual(vs.gender("an old man"), "male")
        self.assertEqual(vs.gender("female"), "female")          # «female» não conta como «male»
        self.assertEqual(vs.gender("homem e mulher conversando"), "")
        self.assertEqual(vs.gender("calma e lenta"), "")
        self.assertEqual(vs.gender("humano"), "")

    def test_orpheus_voice(self):
        self.assertEqual(vs.orpheus_voice("zoe", "voz de homem"), "zoe")                      # a voz pedida no campo «Voz» manda
        self.assertEqual(vs.orpheus_voice(" LEO ", ""), "leo")
        self.assertEqual(vs.orpheus_voice("", "voz masculina"), "leo")
        self.assertEqual(vs.orpheus_voice("", "voz feminina"), "tara")
        self.assertEqual(vs.orpheus_voice("", ""), "tara")                                    # a padrão de antes
        self.assertEqual(vs.orpheus_voice("", "homem e mulher"), "tara")
        self.assertEqual(vs.orpheus_voice("nao-existe", "homem"), "leo")
        for v in vs.ORPHEUS_FEMALE + vs.ORPHEUS_MALE:
            self.assertIn(v, media_mod.ORPHEUS_VOICES)                                        # todas existem no modelo


class DemoVoiceTests(unittest.TestCase):
    def test_a_description_changes_the_pitch(self):
        base = zero_crossings_per_second(proc.babble(TEXT, 1.0, 1))
        low = zero_crossings_per_second(proc.babble(TEXT, 1.0, 1, "voz grave"))
        high = zero_crossings_per_second(proc.babble(TEXT, 1.0, 1, "voz aguda"))
        self.assertLess(low, base)
        self.assertLess(base, high)

    def test_a_description_changes_the_pace(self):
        base = seconds(proc.babble(TEXT, 1.0, 1))
        self.assertLess(seconds(proc.babble(TEXT, 1.0, 1, "rápida")), base * 0.85)
        self.assertGreater(seconds(proc.babble(TEXT, 1.0, 1, "lenta e calma")), base * 1.2)

    def test_a_description_changes_the_volume(self):
        self.assertLess(rms(proc.babble(TEXT, 1.0, 1, "sussurrando")), rms(proc.babble(TEXT, 1.0, 1)) * 0.8)

    def test_without_recognized_words_the_voice_is_the_same_as_before(self):
        base = proc.babble(TEXT, 1.0, 1)
        self.assertEqual(proc.babble(TEXT, 1.0, 1, ""), base)
        self.assertEqual(proc.babble(TEXT, 1.0, 1, "uma pessoa simpática"), base)
        self.assertEqual(proc.babble(TEXT, 1.0, 1, "grave"), proc.babble(TEXT, 1.0, 1, "grave"))     # determinístico

    def test_the_demo_provider_reads_it(self):
        d = DemoMedia({"id": "demo"})
        plain = d.voice(TEXT, voice="x", instructions="").data
        grave = d.voice(TEXT, voice="x", instructions="voz grave").data
        self.assertNotEqual(plain, grave)
        self.assertEqual(d.voice_style_note(), "")                                             # a demonstração lê a descrição: sem aviso


class ProviderTests(unittest.TestCase):
    def test_the_default_provider_says_it_ignores_the_description(self):
        class Plain(MediaProvider):
            label = "Meu provedor"
        note = Plain({"id": "p"}).voice_style_note("modelo-x")
        self.assertIn("Meu provedor (modelo-x)", note)
        self.assertIn("não lê a descrição da voz", note)

    def test_local_models(self):
        lp = LocalHFMedia({"id": "local_hf"})
        self.assertIn("só usa da descrição da voz o gênero", lp.voice_style_note("unsloth/orpheus-3b-0.1-ft"))
        self.assertIn("não lê a descrição da voz", lp.voice_style_note("suno/bark-small"))
        self.assertIn("suno/bark-small", lp.voice_style_note("suno/bark-small"))

    def test_orpheus_gets_the_description(self):
        lp = LocalHFMedia({"id": "local_hf"})
        with mock.patch.object(lp, "_voice_orpheus", return_value="ok") as f:
            lp.voice("oi", voice="", model="unsloth/orpheus-3b-0.1-ft", instructions="voz masculina")
        self.assertEqual(f.call_args.args[-1], "voz masculina")
        with mock.patch.object(lp, "_voice_csm", return_value="ok") as g:
            lp.voice("oi", voice="1", model="unsloth/csm-1b", instructions="voz masculina")
        self.assertTrue(g.called)                                                                 # o CSM segue como antes


class SchemaTests(unittest.TestCase):
    def test_the_param(self):
        self.assertEqual(schema.normalize_params("voice", {})["voice_style"], "")
        self.assertEqual(schema.normalize_params("voice", {"voice_style": "grave"})["voice_style"], "grave")
        self.assertEqual(len(schema.normalize_params("voice", {"voice_style": "x" * 5000})["voice_style"]), 600)
        self.assertEqual(schema.normalize_params("dub", {"voice_style": "feminina"})["voice_style"], "feminina")
        self.assertEqual(schema.normalize_params("dub", {})["voice_style"], "")

    def test_voice_params_keep_their_other_fields(self):
        p = schema.normalize_params("voice", {"text": "oi", "voice": "tara", "speed": 1.2, "voice_style": "calma"})
        self.assertEqual((p["text"], p["voice"], p["speed"]), ("oi", "tara", 1.2))


class Recorder(MediaProvider):
    id, label, caps = "fake", "Fake", ("voice",)

    def __init__(self, note=""):
        super().__init__({"id": "fake"})
        self.calls, self.note = [], note

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        self.calls.append({"text": text, "voice": voice, "instructions": instructions})
        return Media(proc.babble(text, speed, 1), "audio/wav")

    def voice_style_note(self, model=""):
        return self.note


def voice_project(params, style=None):
    from openflow.canvas.engine import CanvasEngine  # noqa: F401
    pj = Project(None, [])
    cv = pj.cs.get(pj.cid)
    nodes = [{"id": "v", "type": "voice", "x": 0, "y": 0, "params": params}]
    edges = []
    if style:
        nodes.append({"id": "sp", "type": "style_prompt", "x": 0, "y": 0, "params": {"text": style, "global": False}})
        edges.append({"from": "sp", "to": "v", "port": "style"})
    pj.cs.save_layout(pj.cid, {"nodes": nodes, "edges": edges})
    return pj


class VoiceNodeTests(unittest.TestCase):
    def test_the_description_and_the_project_style_reach_the_model(self):
        pj = voice_project({"text": "Olá, mundo", "voice_style": "grave e calma, de narrador"}, style="fale com carinho")
        rec = Recorder()
        pj.run(rec)
        self.assertEqual(pj.errors(), {})
        ins = rec.calls[0]["instructions"]
        self.assertTrue(ins.startswith("grave e calma, de narrador\n"))       # a descrição vem primeiro
        self.assertIn("carinho", ins)
        self.assertEqual(rec.calls[0]["text"], "Olá, mundo")

    def test_without_a_description_nothing_changes_and_no_warning(self):
        pj = voice_project({"text": "Olá"})
        rec = Recorder(note="não leio")
        pj.run(rec)
        self.assertEqual(rec.calls[0]["instructions"], "")
        self.assertEqual(pj.warnings("v"), [])

    def test_a_model_that_does_not_read_it_warns(self):
        pj = voice_project({"text": "Olá", "voice_style": "feminina"})
        pj.run(Recorder(note="O modelo X não lê a descrição da voz."))
        self.assertIn("O modelo X não lê a descrição da voz.", pj.warnings("v"))
        silent = voice_project({"text": "Olá", "voice_style": "feminina"})
        silent.run(Recorder(note=""))
        self.assertEqual(silent.warnings("v"), [])

    def test_the_demo_voice_follows_the_description_end_to_end(self):
        out = {}
        for key, style in (("plain", ""), ("grave", "voz grave e lenta")):
            pj = voice_project({"text": TEXT, "voice_style": style, "voice": "x"})
            cv = pj.run()                                                     # sem provedor de mentira: a voz Demo de verdade
            self.assertEqual(pj.errors(), {})
            res = next(n for n in cv["nodes"] if n["id"] == "v")["result"]
            a = next(x for x in cv["assets"] if x["id"] == res["assets"][0])
            out[key] = pj.cs.asset_path(pj.cid, a["file"]).read_bytes()
            if style:
                self.assertEqual(pj.warnings("v"), [])                        # a demonstração lê a descrição: sem aviso
        self.assertNotEqual(out["plain"], out["grave"])
        self.assertGreater(seconds(out["grave"]), seconds(out["plain"]))

    def test_the_cache_follows_the_description(self):
        pj = voice_project({"text": "Olá", "voice_style": "grave"})
        pj.run(Recorder())
        pj.run(Recorder(), force=False)
        self.assertEqual(pj.states()["v"], "cached")
        cv = pj.cs.get(pj.cid)
        next(n for n in cv["nodes"] if n["id"] == "v")["params"]["voice_style"] = "aguda"
        pj.cs.save_layout(pj.cid, {"nodes": cv["nodes"], "edges": cv["edges"]})
        pj.run(Recorder(), force=False)
        self.assertEqual(pj.states()["v"], "done")


@unittest.skipUnless(FF, "sem ffmpeg")
class DubTests(unittest.TestCase):
    def test_a_connected_voice_brings_its_description_to_the_dub(self):
        pj = Project("Maria: Bom dia, pessoal.\nJoão: Bom dia!", [{"title": "Maria", "params": {"voice": "tara", "voice_style": "feminina e animada"}},
                                                                   {"title": "João", "params": {"voice": "leo", "voice_style": "grave e calma"}}])
        rec = Recorder(note="X não lê a descrição.")
        cv = pj.run(rec)
        self.assertEqual(pj.errors(), {})
        self.assertEqual([(c["voice"], c["instructions"]) for c in rec.calls], [("tara", "feminina e animada"), ("leo", "grave e calma")])
        self.assertEqual(pj.warnings().count("X não lê a descrição."), 1)       # o mesmo aviso aparece uma vez só
        self.assertEqual(len(next(n for n in cv["nodes"] if n["id"] == "d")["result"]["assets"]), 1)

    def test_the_dub_own_voice_description(self):
        pj = Project("Uma fala simples.", [], dub={"voice": "padrao", "voice_style": "narrador sério"})
        rec = Recorder()
        pj.run(rec)
        self.assertEqual([c["instructions"] for c in rec.calls], ["narrador sério"])

    def test_a_voice_without_a_description_does_not_warn_in_the_dub(self):
        pj = Project("Maria: oi", [{"title": "Maria", "params": {"voice": "tara"}}])
        pj.run(Recorder(note="X não lê a descrição."))
        self.assertNotIn("X não lê a descrição.", pj.warnings())

    def test_the_demo_dub_changes_with_the_description(self):
        def dub(style):
            pj = Project("Maria: Bom dia a todos, vamos começar a reunião.", [{"title": "Maria", "params": {"voice": "tara", "voice_style": style}}])
            cv = pj.run()
            res = next(n for n in cv["nodes"] if n["id"] == "d")["result"]
            a = next(x for x in cv["assets"] if x["id"] == res["assets"][0])
            return pj.cs.asset_path(pj.cid, a["file"]).read_bytes()
        self.assertNotEqual(dub(""), dub("voz aguda e rápida"))

    def test_the_dub_cache_follows_the_connected_voice_description(self):
        pj = Project("Maria: oi tudo bem", [{"title": "Maria", "params": {"voice": "tara", "voice_style": "grave"}}])
        pj.run(Recorder())
        pj.run(Recorder(), force=False)
        self.assertEqual(pj.states()["d"], "cached")
        cv = pj.cs.get(pj.cid)
        next(n for n in cv["nodes"] if n["id"] == "v0")["params"]["voice_style"] = "aguda"
        pj.cs.save_layout(pj.cid, {"nodes": cv["nodes"], "edges": cv["edges"]})
        pj.run(Recorder(), force=False)
        self.assertEqual(pj.states()["d"], "done")


if __name__ == "__main__":
    unittest.main()
