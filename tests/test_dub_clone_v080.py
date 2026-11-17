"""v0.80: a Dublagem com o openbmb/VoxCPM2 clona SOZINHA a voz de cada pessoa que fala no áudio original (sem nós Voz e sem áudio de referência): separa os locutores, tira uma amostra de cada um e dubla cada fala
com a voz clonada de quem a disse; no mesmo idioma a transcrição da amostra segue junto (clonagem fiel).

Os locutores dos testes são o balbucio da demonstração (grave e agudo) e a biblioteca `voxcpm` é simulada (anota as chamadas e o conteúdo da amostra de cada uma): prova a mecânica, NÃO que o VoxCPM2 de verdade clone bem
nem que a separação funcione com pessoas reais."""
import hashlib
import shutil
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from openflow.canvas import autoclone as ac
from openflow.canvas import diarize as dz
from openflow.canvas import schema, speech
from openflow.canvas import subtitles as sub

from tests.test_diarize_v069 import DEEP, HIGH, scene
from tests.test_voxcpm_nodes_v075 import MODEL, Base, FakeVox, seconds

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


class PureTests(unittest.TestCase):
    def test_pick_takes_the_longest_first_whole_and_stops_at_the_target(self):
        items = [(0, 2, "a"), (3, 11, "b"), (12, 30, "c"), (31, 33, "d")]
        got = ac.pick(items, target=12.0, max_seg=10.0)
        self.assertEqual([i[0] for i in got], sorted(i[0] for i in got))            # em ordem de tempo
        self.assertEqual(got, [(0, 2, "a"), (12, 22, "")])                           # a de 18 s entra cortada em 10 s (sem transcrição); a de 8 s passaria do alvo e é pulada; a de 2 s cabe

    def test_pick_keeps_the_text_of_whole_segments(self):
        got = ac.pick([(0, 3, "um"), (4, 8, "dois")])
        self.assertEqual([t for _a, _b, t in got], ["um", "dois"])

    def test_wav_has_the_length_of_the_pieces_plus_gaps(self):
        x = (0.2 * np.sin(np.linspace(0, 3000, dz.SR * 10))).astype("float32")
        data, secs = ac.wav_bytes(x, [(0, 2, ""), (4, 7, "")])
        self.assertAlmostEqual(secs, 5 + ac.GAP, delta=0.01)
        self.assertAlmostEqual(seconds(data)[0], secs, delta=0.01)
        self.assertEqual(ac.wav_bytes(x, []), (b"", 0.0))

    def test_voiced_runs_find_the_sound_between_silences(self):
        x = np.zeros(dz.SR * 8, "float32")
        x[dz.SR * 2:dz.SR * 5] = 0.3 * np.sin(np.linspace(0, 4000, dz.SR * 3))
        runs = ac.voiced_runs(x)
        self.assertEqual(len(runs), 1)
        self.assertAlmostEqual(runs[0][0], 2.0, delta=0.15)
        self.assertAlmostEqual(runs[0][1], 5.0, delta=0.15)
        self.assertEqual(ac.voiced_runs(np.zeros(dz.SR * 3, "float32")), [])

    def test_speaker_of_uses_the_biggest_overlap_or_the_nearest(self):
        lab = [{"start": 0, "end": 5, "text": "a", "speaker": 0}, {"start": 5, "end": 10, "text": "b", "speaker": 1}]
        self.assertEqual(ac.speaker_of(lab, 4, 9), 1)
        self.assertEqual(ac.speaker_of(lab, 0, 4), 0)
        self.assertEqual(ac.speaker_of(lab, 12, 13), 1)
        self.assertEqual(ac.speaker_of([], 1, 2), 0)

    def test_plan_two_voices_gets_one_sample_each(self):
        x, segs = scene([DEEP, HIGH], [1, 2])
        labelled, voices, notes = ac.plan(x, segs, True, 0)
        self.assertEqual(len(voices), 2)
        self.assertTrue(all(v["wav"] and v["seconds"] >= ac.MIN_REF for v in voices))
        self.assertNotEqual(voices[0]["wav"], voices[1]["wav"])
        self.assertTrue(voices[0]["text"] and voices[1]["text"])
        self.assertEqual([s["speaker"] for s in labelled], [0, 1] * 4)
        self.assertEqual(notes, [])

    def test_plan_without_real_times_is_one_voice_from_the_sound(self):
        x, segs = scene([DEEP, HIGH], [1, 2])
        _lab, voices, notes = ac.plan(x, [], False, 0)
        self.assertEqual(len(voices), 1)
        self.assertTrue(voices[0]["wav"])
        self.assertEqual(voices[0]["text"], "")                                      # sem transcrição de verdade, não há texto da amostra
        _lab, voices, notes = ac.plan(x, [], False, 3)
        self.assertEqual(len(voices), 1)
        self.assertTrue(any("tempos de verdade" in n for n in notes))

    def test_a_voice_with_almost_no_speech_has_no_sample(self):
        x, segs = scene([DEEP], [1], 2)
        tiny = {"start": segs[-1]["end"] + 0.2, "end": segs[-1]["end"] + 0.9, "text": "Sim."}
        x = np.concatenate([x, np.zeros(int(0.2 * dz.SR), "float32"), np.zeros(int(0.7 * dz.SR), "float32")])
        _lab, voices, _n = ac.plan(x, segs + [tiny], True, 0)
        self.assertTrue(voices[0]["wav"])

    def test_silence_does_not_break_the_plan(self):
        x = np.zeros(dz.SR * 4, "float32")
        _lab, voices, _n = ac.plan(x, [{"start": 0, "end": 3, "text": "oi"}], True, 0)
        self.assertEqual([v["wav"] for v in voices], [b""])


class SchemaTests(unittest.TestCase):
    def test_params_are_normalized(self):
        p = schema.normalize_params("dub", {})
        self.assertEqual((p["clone"], p["speakers"]), ("auto", 0))
        p = schema.normalize_params("dub", {"clone": "off", "speakers": 99})
        self.assertEqual((p["clone"], p["speakers"]), ("off", 8))
        self.assertEqual(schema.normalize_params("dub", {"clone": "xx", "speakers": "abc"})["clone"], "auto")


class RecVox(FakeVox):
    """A biblioteca falsa, agora anotando também o conteúdo (hash) da amostra de cada chamada."""

    def __init__(self):
        super().__init__()
        self.refs = []
        orig = self.VoxCPM.from_pretrained
        outer = self

        def fp(model, **kw):
            engine = orig(model, **kw)
            gen = engine.generate

            def generate(**k):
                outer.refs.append(hashlib.md5(Path(k["reference_wav_path"]).read_bytes()).hexdigest() if "reference_wav_path" in k else None)
                return gen(**k)
            engine.generate = generate
            return engine
        self.VoxCPM.from_pretrained = staticmethod(fp)


@unittest.skipUnless(FF, "sem ffmpeg")
class DubNodeTests(Base):
    def setUp(self):
        super().setUp()
        self.fake = RecVox()
        self.patches[0].stop()
        import sys
        p = mock.patch.dict(sys.modules, {"voxcpm": self.fake})
        p.start()
        self.addCleanup(p.stop)

    def project(self, styles=(DEEP, HIGH), seeds=(1, 2), rounds=2):
        x, segs = scene(list(styles), list(seeds), rounds)
        from openflow.canvas import media
        a = self.cs.add_asset(self.cid, media._wav_from_array(x, dz.SR), "wav", "audio", name="reuniao.wav", mime="audio/wav", provider="upload")
        return a, segs

    def graph(self, segs=None, a=None, **params):
        nodes = [self.upload("u", a), self.node("d", "dub", **dict({"provider": "local_hf", "model": MODEL, "language": "keep"}, **params))]
        edges = [{"id": "e1", "from": "u", "to": "d", "port": "media"}]
        if segs is not None:
            nodes.append(self.node("t", "text", text=sub.to_srt(segs)))
            edges.append({"id": "e2", "from": "t", "to": "d", "port": "script"})
        return nodes, edges

    def test_each_speaker_is_dubbed_with_their_own_cloned_voice(self):
        a, segs = self.project()
        cv = self.run_nodes(*self.graph(segs, a))
        self.assertEqual(self.errors(), {})
        self.assertEqual(len(self.fake.calls), 8)
        self.assertTrue(all("reference_wav_path" in c for c in self.fake.calls))
        self.assertTrue(all(c["ref_exists"] == [True] for c in self.fake.calls))          # roteiro com tempos: só o timbre (clonagem controlável), sem texto da amostra
        self.assertEqual(len(set(self.fake.refs)), 2)                                     # duas vozes, duas amostras
        self.assertEqual(self.fake.refs[0::2], [self.fake.refs[0]] * 4)                    # falas 1, 3, 5, 7 → a voz grave
        self.assertEqual(self.fake.refs[1::2], [self.fake.refs[1]] * 4)
        self.assertEqual(len(self.fake.loads), 1)                                         # um modelo carregado só
        ws = self.warnings("d")
        self.assertTrue(any("Voz clonada do áudio original: Locutor 1 (amostra de" in w and "Locutor 2" in w for w in ws), ws)
        self.assertTrue(any("Vozes usadas: Locutor 1 (4 falas), Locutor 2 (4 falas)" in w for w in ws), ws)
        self.assertTrue(self.result(cv, "d")["assets"])

    def test_same_language_transcription_uses_the_faithful_cloning(self):
        a, segs = self.project()
        with mock.patch.object(speech, "transcribe_media", return_value=(segs, True, "Fake")):
            self.run_nodes(*self.graph(None, a))
        self.assertEqual(self.errors(), {})
        self.assertTrue(all(c.get("prompt_text") and "prompt_wav_path" in c for c in self.fake.calls))
        self.assertEqual({c["prompt_text"] for c in self.fake.calls[0::2]} & {c["prompt_text"] for c in self.fake.calls[1::2]}, set())   # cada um com a transcrição da amostra dele

    def test_translating_keeps_only_the_timbre(self):
        a, segs = self.project()
        with mock.patch.object(speech, "transcribe_media", return_value=(segs, True, "Fake")), mock.patch.object(speech, "translate", side_effect=lambda eng, texts, s, t, w: ["Good morning everyone, let us begin today." for _ in texts]):
            self.run_nodes(*self.graph(None, a, language="en"))
        self.assertEqual(self.errors(), {})
        self.assertTrue(all("reference_wav_path" in c and "prompt_text" not in c for c in self.fake.calls))
        self.assertEqual(len(set(self.fake.refs)), 2)                                     # as vozes seguem as do original, mesmo traduzindo

    def test_a_voice_description_keeps_the_controllable_cloning(self):
        a, segs = self.project()
        with mock.patch.object(speech, "transcribe_media", return_value=(segs, True, "Fake")):
            self.run_nodes(*self.graph(None, a, voice_style="calma"))
        self.assertTrue(all(c["text"].startswith("(calma)") and "prompt_text" not in c for c in self.fake.calls))

    def test_the_number_of_voices_can_be_forced(self):
        a, segs = self.project(styles=(DEEP,), seeds=(1,))
        self.run_nodes(*self.graph(segs, a, speakers=1))
        self.assertEqual(len(set(self.fake.refs)), 1)

    def test_one_speaker_is_one_cloned_voice_without_names(self):
        a, segs = self.project(styles=(DEEP,), seeds=(1,))
        self.run_nodes(*self.graph(segs, a))
        self.assertEqual(self.errors(), {})
        self.assertEqual(len(set(self.fake.refs)), 1)
        ws = self.warnings("d")
        self.assertTrue(any("Voz clonada do áudio original: (amostra de" in w for w in ws), ws)
        self.assertFalse(any("Vozes usadas" in w for w in ws))

    def test_a_script_without_times_is_one_cloned_voice(self):
        a, _segs = self.project()
        nodes, edges = self.graph(None, a)
        nodes.append(self.node("t", "text", text="Bom dia a todos. Vamos começar a reunião agora mesmo."))
        edges.append({"id": "e2", "from": "t", "to": "d", "port": "script"})
        self.run_nodes(nodes, edges)
        self.assertEqual(self.errors(), {})
        self.assertTrue(all("reference_wav_path" in c and "prompt_text" not in c for c in self.fake.calls))
        self.assertEqual(len(set(self.fake.refs)), 1)

    def test_turning_it_off_keeps_the_old_behaviour(self):
        a, segs = self.project()
        self.run_nodes(*self.graph(segs, a, clone="off", voice_style="narradora"))
        self.assertEqual(self.errors(), {})
        self.assertTrue(all("reference_wav_path" not in c and c["text"].startswith("(narradora)") for c in self.fake.calls))
        self.assertFalse(any("Voz clonada" in w for w in self.warnings("d")))

    def test_connected_voice_nodes_win_over_the_automatic_cloning(self):
        a, segs = self.project()
        nodes, edges = self.graph(segs, a)
        nodes.append(self.voice("v1", "Maria", voice_style="mulher calma"))
        edges.append({"id": "ev", "from": "v1", "to": "d", "port": "voices"})
        self.run_nodes(nodes, edges)
        self.assertEqual(self.errors(), {})
        self.assertTrue(all("reference_wav_path" not in c for c in self.fake.calls))
        self.assertFalse(any("Voz clonada" in w for w in self.warnings("d")))

    def test_a_model_that_does_not_clone_is_left_alone(self):
        from openflow.canvas import media as m
        with mock.patch.object(m.LocalHFMedia, "clones_voice", return_value=False):
            a, segs = self.project()
            self.run_nodes(*self.graph(segs, a))
        self.assertTrue(all("reference_wav_path" not in c for c in self.fake.calls))
        self.assertFalse(any("Voz clonada" in w for w in self.warnings("d")))

    def test_without_enough_speech_it_falls_back_to_the_node_voice(self):
        silent = self.cs.add_asset(self.cid, __import__("openflow.canvas.media", fromlist=["x"])._wav_from_array(np.zeros(dz.SR * 4, "float32"), dz.SR), "wav", "audio", name="mudo.wav", mime="audio/wav", provider="upload")
        nodes, edges = self.graph([{"start": 0, "end": 3, "text": "Olá, tudo bem?"}], silent)
        self.run_nodes(nodes, edges)
        self.assertEqual(self.errors(), {})
        self.assertTrue(all("reference_wav_path" not in c for c in self.fake.calls))
        self.assertTrue(any("fala suficiente" in w for w in self.warnings("d")))

    def test_changing_the_option_redoes_the_dub(self):
        a, segs = self.project()
        nodes, edges = self.graph(segs, a)
        self.run_nodes(nodes, edges)
        n = len(self.fake.calls)
        self.run_nodes(nodes, edges, force=False)
        self.assertEqual(len(self.fake.calls), n)
        nodes[1]["params"]["clone"] = "off"
        self.run_nodes(nodes, edges, force=False)
        self.assertGreater(len(self.fake.calls), n)


if __name__ == "__main__":
    unittest.main()
