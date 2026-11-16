"""v0.61: Música e SFX — três nós novos no grupo Som: Música (gera músicas, com ou sem letra), Letra (escreve ou arruma a letra) e SFX (efeitos sonoros, até 4 variações).

Tudo roda com o provedor Demo (offline) e com provedores de mentira: não há modelo de música real aqui, então que um modelo de verdade cante a letra ou gere boa música não é verificado."""
import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from openflow.canvas import engine as engine_mod
from openflow.canvas import lyrics as L
from openflow.canvas import procedural as proc
from openflow.canvas import schema
from openflow.canvas.engine import CanvasEngine
from openflow.canvas.media import Media, MediaProvider
from openflow.storage import Store


def seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def node(nid, ntype, **params):
    return {"id": nid, "type": ntype, "x": 0, "y": 0, "params": params}


class Project:
    """Um projeto com o canvas dado, rodado pela engine de verdade (Demo)."""

    def __init__(self, nodes, edges=()):
        self.store = Store(Path(tempfile.mkdtemp()))
        self.cs = self.store.projects
        self.cid = self.cs.create("som")["id"]
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": list(edges)})

    def run(self, force=True, targets=None):
        self.events = []
        CanvasEngine(self.store, self.cid, self.events.append, lambda: False).run(targets, force)
        return self.cs.get(self.cid)

    def errors(self):
        return {e["id"]: e.get("message") for e in self.events if e.get("type") == "node" and e.get("state") == "error"}

    def audio(self, cv, nid):
        res = next(n for n in cv["nodes"] if n["id"] == nid)["result"]
        return [self.cs.asset_path(self.cid, a["file"]).read_bytes() for a in cv["assets"] if a["id"] in res["assets"]]

    def warnings(self, nid):
        return [w for e in self.events if e.get("type") == "node" and e.get("id") == nid for w in e.get("warnings", [])]


class SchemaTests(unittest.TestCase):
    def test_the_sound_group_and_the_ports(self):
        group = dict(schema.PALETTE)["Som"]
        self.assertEqual(group[:4], ["music", "lyrics", "sfx", "sound"])   # o nó Som antigo continua
        self.assertEqual([p[0] for p in schema.NODE_TYPES["music"]["ins"]], ["prompt", "lyrics", "style"])
        self.assertEqual([p[0] for p in schema.NODE_TYPES["sfx"]["ins"]], ["prompt"])
        self.assertEqual((schema.NODE_TYPES["lyrics"]["out"], schema.NODE_TYPES["music"]["out"], schema.NODE_TYPES["sfx"]["out"]), ("text", "audio", "audio"))
        self.assertIn("music", schema.GENERATORS)
        self.assertIn("sfx", schema.GENERATORS)
        self.assertIn("lyrics", schema.EXT_TYPES)

    def test_a_lyrics_node_connects_to_the_music_lyrics_port(self):
        self.assertTrue(schema.compatible(schema.NODE_TYPES["lyrics"]["out"], schema.port_def("music", "lyrics")["accepts"]))
        self.assertFalse(schema.compatible("audio", schema.port_def("music", "lyrics")["accepts"]))

    def test_music_params_are_clamped(self):
        p = schema.normalize_params("music", {"prompt": "x" * 5000, "duration": 9999, "bpm": 10, "instrumental": 1, "seed": -3, "provider": "demo"})
        self.assertEqual((len(p["prompt"]), p["duration"], p["bpm"], p["instrumental"], p["seed"]), (2000, 240, 0, True, 0))   # BPM abaixo de 40 = automático
        self.assertEqual(schema.normalize_params("music", {"bpm": 9999})["bpm"], 220)
        self.assertEqual(schema.normalize_params("music", {"duration": 0})["duration"], 5)
        self.assertEqual(schema.normalize_params("music", {})["duration"], 30)

    def test_sfx_params_are_clamped(self):
        p = schema.normalize_params("sfx", {"duration": 500, "variations": 99})
        self.assertEqual((p["duration"], p["variations"]), (30, 4))
        p = schema.normalize_params("sfx", {"duration": 0, "variations": 0})
        self.assertEqual((p["duration"], p["variations"]), (1, 1))

    def test_lyrics_params_fall_back_to_valid_options(self):
        from openflow.canvas import nodes_ext

        p = nodes_ext.normalize("lyrics", {"mode": "x", "language": "klingon", "structure": "?", "rhyme": "?", "tags": False, "theme": "t" * 5000})
        self.assertEqual((p["mode"], p["language"], p["structure"], p["rhyme"], p["tags"], len(p["theme"])), ("write", "pt", "song", "aabb", False, 2000))


class LyricsTests(unittest.TestCase):
    def test_section_tags(self):
        self.assertEqual(L.section_tag("Refrão:"), "[Chorus]")
        self.assertEqual(L.section_tag("(chorus 2)"), "[Chorus 2]")
        self.assertEqual(L.section_tag("[verso 1]"), "[Verse 1]")
        self.assertEqual(L.section_tag("Pré-refrão"), "[Pre-Chorus]")
        self.assertEqual(L.section_tag("Ponte"), "[Bridge]")
        self.assertEqual(L.section_tag("Refrão do meu coração"), "")     # uma linha da letra que só começa com a palavra não é marca
        self.assertEqual(L.section_tag("Eu canto o refrão"), "")

    def test_tidy(self):
        raw = "```\nverso 1\nA luz  \n\n\n\nvai chegar\nRefrão:\n- canta comigo\n```"
        self.assertEqual(L.tidy(raw), "[Verse 1]\nA luz\n\nvai chegar\n\n[Chorus]\ncanta comigo")
        self.assertEqual(L.tidy("[Verse 1]\nA\n[Chorus]\nB", tags=False), "A\nB")
        self.assertEqual(L.tidy(""), "")
        self.assertEqual(L.tidy("x\n" * 9000, limit=50)[:2], "x\n")
        self.assertLessEqual(len(L.tidy("x\n" * 9000, limit=50)), 50)

    def test_demo_lyrics_follow_the_structure_and_the_theme(self):
        short = L.demo("saudade do mar azul", "pt", "short", 1)
        self.assertEqual([x for x in short.split("\n") if x.startswith("[")], ["[Verse 1]", "[Chorus]"])
        self.assertIn("saudade", short)
        full = L.demo("night drive", "en", "song")
        self.assertEqual([x for x in full.split("\n") if x.startswith("[")], ["[Verse 1]", "[Chorus]", "[Verse 2]", "[Chorus]", "[Bridge]", "[Chorus]"])
        chorus = [s for s in full.split("\n\n") if s.startswith("[Chorus]")]
        self.assertEqual(len(set(chorus)), 1)    # o refrão repete igual
        self.assertEqual(L.demo("night drive", "en", "song"), full)    # determinístico
        self.assertEqual(len(L.demo("x", "pt", "hook").split("\n")), 5)

    def test_system_prompt(self):
        sp = L.system_prompt({"language": "es", "structure": "rap", "rhyme": "abab", "genre": "trap", "mood": "dark"}, "estilo X")
        for needle in ("Spanish", "[Hook] (4 lines)", "ABAB", "Genre: trap", "Mood: dark", "estilo X", "ORIGINAL"):
            self.assertIn(needle, sp)
        self.assertIn("Brazilian Portuguese", L.system_prompt({"language": "pt", "structure": "song"}))


class ProceduralTests(unittest.TestCase):
    def test_lyrics_and_tempo_change_the_music_but_not_its_length(self):
        base = proc.music("calma piano", 10, 3)
        sung = proc.music("calma piano", 10, 3, lyrics="[Verse 1]\nO mar é azul\nA luz vai chegar")
        fast = proc.music("calma piano", 10, 3, bpm=170)
        self.assertNotEqual(sung, base)
        self.assertNotEqual(fast, base)
        self.assertEqual([seconds(x) for x in (base, sung, fast)], [10.0, 10.0, 10.0])
        self.assertEqual(proc.music("calma piano", 10, 3), base)                                     # determinístico
        self.assertEqual(proc.music("calma piano", 10, 3, lyrics="[Chorus]\n(Verse)"), base)         # só marcas de seção: nada para cantar

    def test_sung_text_drops_section_marks(self):
        self.assertEqual(proc.sung_text("[Verse 1]\nO mar\n\n(Refrão)\nCanta"), "O mar\nCanta")

    def test_a_long_lyric_still_fits_the_song(self):
        out = proc.music("rock", 6, 1, lyrics="\n".join(["uma linha bem comprida de letra para cantar"] * 40))
        self.assertEqual(seconds(out), 6.0)


class FakeProvider(MediaProvider):
    id = "fake"
    label = "Fake"
    caps = ("sound",)

    def __init__(self, seconds_back=None, sings=False):
        super().__init__({"id": "fake"})
        self.calls = []
        self.seconds_back, self.sings = seconds_back, sings

    def sound(self, prompt, *, kind="sfx", duration=5, model="", extra=None, seed=0):
        self.calls.append(("sound", prompt, kind, duration, seed))
        return Media(proc.wav_bytes([0.0] * int(proc.SR * float(self.seconds_back or duration))), "audio/wav")

    def sings_lyrics(self, model=""):
        return self.sings


class ProviderApiTests(unittest.TestCase):
    def test_default_music_turns_the_request_into_text_for_sound(self):
        fp = FakeProvider()
        fp.music("jazz suave", lyrics="la la", instrumental=True, bpm=90, duration=12, seed=2)
        self.assertEqual(fp.calls[0][2:], ("music", 12, 2))
        self.assertIn("90 BPM", fp.calls[0][1])
        self.assertIn("instrumental", fp.calls[0][1])
        self.assertNotIn("la la", fp.calls[0][1])           # um modelo que não canta nunca recebe a letra como se fosse estilo
        fp2 = FakeProvider()
        fp2.music("jazz suave")
        self.assertEqual(fp2.calls[0][1], "jazz suave")
        self.assertFalse(fp2.sings_lyrics())

    def test_demo_provider_sings_unless_instrumental(self):
        from openflow.canvas.media import DemoMedia

        d = DemoMedia({"id": "demo"})
        self.assertTrue(d.sings_lyrics())
        a = d.music("pop", lyrics="[Chorus]\nla la la la", duration=8, seed=1).data
        b = d.music("pop", lyrics="[Chorus]\nla la la la", instrumental=True, duration=8, seed=1).data
        c = d.music("pop", duration=8, seed=1).data
        self.assertEqual(b, c)
        self.assertNotEqual(a, c)


class EngineTests(unittest.TestCase):
    def test_lyrics_to_music_end_to_end(self):
        pj = Project([node("l", "lyrics", mode="manual", text="Refrão:\nvamos cantar\nde manhã", tags=True), node("m", "music", prompt="pop alegre", duration=8, seed=7)],
                     [{"from": "l", "to": "m", "port": "lyrics"}])
        cv = pj.run()
        self.assertEqual(pj.errors(), {})
        res = {n["id"]: n["result"] for n in cv["nodes"]}
        self.assertEqual(res["l"]["text"], "[Chorus]\nvamos cantar\nde manhã")
        (song,) = pj.audio(cv, "m")
        self.assertEqual(seconds(song), 8.0)
        asset = next(a for a in cv["assets"] if a["id"] == res["m"]["assets"][0])
        self.assertEqual(asset["kind"], "audio")
        self.assertIn("vamos cantar", asset["prompt"])    # a letra fica registrada no arquivo gerado
        plain = Project([node("m", "music", prompt="pop alegre", duration=8, seed=7)])
        self.assertNotEqual(plain.audio(plain.run(), "m")[0], song)    # a letra mudou o resultado (a demo a «canta»)

    def test_write_mode_without_a_text_model_makes_an_example_and_says_so(self):
        pj = Project([node("l", "lyrics", theme="a estrada à noite", language="pt", structure="short")])
        cv = pj.run()
        self.assertEqual(pj.errors(), {})
        text = next(n for n in cv["nodes"] if n["id"] == "l")["result"]["text"]
        self.assertTrue(text.startswith("[Verse 1]"))
        self.assertIn("estrada", text)
        self.assertTrue(any("exemplo" in w for w in pj.warnings("l")))

    def test_lyrics_theme_can_come_from_a_connected_text(self):
        pj = Project([node("t", "text", text="o farol e a tempestade"), node("l", "lyrics", structure="hook")], [{"from": "t", "to": "l", "port": "text"}])
        cv = pj.run()
        self.assertEqual(pj.errors(), {})
        self.assertIn("farol", next(n for n in cv["nodes"] if n["id"] == "l")["result"]["text"])

    def test_lyrics_with_a_text_model_uses_the_prompt_and_tidies_the_answer(self):
        pj = Project([node("l", "lyrics", theme="o mar", language="en", genre="folk", structure="short", provider="llm1")])
        seen = {}

        def fake_chat(self_, provider, messages, system, temperature, max_tokens):
            seen.update(messages=messages, system=system)
            return "```\nverse 1\nThe sea is wide\nChorus:\nSing it loud\n```"
        with mock.patch.object(engine_mod.CanvasEngine, "text_chat", fake_chat), mock.patch("openflow.canvas.nodes_ext.build_provider", return_value=object()):
            cv = pj.run()
        self.assertEqual(pj.errors(), {})
        self.assertEqual(next(n for n in cv["nodes"] if n["id"] == "l")["result"]["text"], "[Verse 1]\nThe sea is wide\n\n[Chorus]\nSing it loud")
        self.assertIn("o mar", seen["messages"][0]["content"])
        self.assertIn("English", seen["system"])
        self.assertIn("Genre: folk", seen["system"])

    def test_lyrics_errors_are_clear(self):
        pj = Project([node("a", "lyrics", mode="manual"), node("b", "lyrics")])
        pj.run()
        errs = pj.errors()
        self.assertIn("letra", errs["a"])
        self.assertIn("tema", errs["b"])

    def test_music_needs_a_description_or_lyrics(self):
        pj = Project([node("m", "music")])
        pj.run()
        self.assertIn("Música precisa", pj.errors()["m"])
        ok = Project([node("m", "music", lyrics="[Chorus]\nla la la", duration=5)])
        ok.run()
        self.assertEqual(ok.errors(), {})     # só a letra já basta

    def test_instrumental_ignores_the_lyrics_and_says_so(self):
        pj = Project([node("m", "music", prompt="rock", lyrics="[Chorus]\nla la", instrumental=True, duration=6, seed=1)])
        cv = pj.run()
        self.assertEqual(pj.errors(), {})
        self.assertTrue(any("Instrumental" in w for w in pj.warnings("m")))
        plain = Project([node("m", "music", prompt="rock", instrumental=True, duration=6, seed=1)])
        self.assertEqual(plain.audio(plain.run(), "m"), pj.audio(cv, "m"))

    def test_a_model_that_cannot_sing_gets_no_lyrics_and_a_warning(self):
        fp = FakeProvider(sings=False)
        pj = Project([node("m", "music", prompt="rock", lyrics="[Chorus]\nla la", duration=5)])
        with mock.patch.object(engine_mod, "build_media", return_value=fp):
            pj.run()
        self.assertEqual(pj.errors(), {})
        self.assertTrue(any("não canta" in w for w in pj.warnings("m")))
        self.assertNotIn("la la", fp.calls[0][1])
        singer = FakeProvider(sings=True)
        pj2 = Project([node("m", "music", prompt="rock", lyrics="[Chorus]\nla la", duration=5)])
        with mock.patch.object(engine_mod, "build_media", return_value=singer):
            pj2.run()
        self.assertFalse(any("não canta" in w for w in pj2.warnings("m")))

    def test_a_shorter_result_than_asked_is_reported(self):
        fp = FakeProvider(seconds_back=3)
        pj = Project([node("m", "music", prompt="rock", duration=30), node("s", "sfx", prompt="trovão", duration=10)])
        with mock.patch.object(engine_mod, "build_media", return_value=fp):
            pj.run()
        self.assertTrue(any("3 s dos 30 s" in w for w in pj.warnings("m")))
        self.assertTrue(any("3 s dos 10 s" in w for w in pj.warnings("s")))

    def test_sfx_makes_distinct_variations(self):
        pj = Project([node("s", "sfx", prompt="explosão e trovão", duration=3, variations=3, seed=5)])
        cv = pj.run()
        self.assertEqual(pj.errors(), {})
        files = pj.audio(cv, "s")
        self.assertEqual(len(files), 3)
        self.assertEqual(len(set(files)), 3)
        self.assertTrue(all(abs(seconds(f) - 3) < 0.6 for f in files))
        names = [a["name"] for a in cv["assets"] if a["id"] in next(n for n in cv["nodes"] if n["id"] == "s")["result"]["assets"]]
        self.assertEqual(sorted(names), ["SFX 1", "SFX 2", "SFX 3"])
        again = Project([node("s", "sfx", prompt="explosão e trovão", duration=3, variations=1, seed=5)])
        self.assertEqual(again.audio(again.run(), "s")[0], files[0])    # a 1ª variação é a mesma de uma só

    def test_sfx_needs_a_description(self):
        pj = Project([node("s", "sfx")])
        pj.run()
        self.assertIn("SFX precisa", pj.errors()["s"])

    def test_sfx_takes_the_text_from_a_connected_node(self):
        pj = Project([node("t", "text", text="passos na chuva"), node("s", "sfx", duration=2)], [{"from": "t", "to": "s", "port": "prompt"}])
        pj.run()
        self.assertEqual(pj.errors(), {})

    def test_the_cache_follows_the_lyrics(self):
        pj = Project([node("l", "lyrics", mode="manual", text="um\ndois"), node("m", "music", prompt="pop", duration=5, seed=2)], [{"from": "l", "to": "m", "port": "lyrics"}])
        pj.run()
        cv = pj.run(force=False)
        self.assertTrue(any(e.get("state") == "cached" and e.get("id") == "m" for e in pj.events))     # nada mudou: reaproveita
        nodes = cv["nodes"]
        nodes[0]["params"]["text"] = "outra letra"
        pj.cs.save_layout(pj.cid, {"nodes": nodes, "edges": cv["edges"]})
        pj.run(force=False)
        self.assertTrue(any(e.get("state") == "done" and e.get("id") == "m" for e in pj.events))       # a letra mudou: a música é gerada de novo


if __name__ == "__main__":
    unittest.main()
