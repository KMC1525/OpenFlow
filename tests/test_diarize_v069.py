"""v0.69: a Transcrição separa quem fala (várias vozes no mesmo áudio): «Locutor 1: …», «Locutor 2: …», com nomes opcionais.

As vozes dos testes são o balbucio da demonstração (graves e agudas), não pessoas de verdade: serve para provar a mecânica (janelas, agrupamento, troca no meio de um trecho, texto, nó) e os limites de uma voz
só. Que a separação funcione em gravações reais — vozes humanas parecidas, ruído, fala sobreposta — NÃO é verificado. ffmpeg e numpy são reais."""
import io
import shutil
import unittest
import wave

import numpy as np

from openflow.canvas import diarize as dz
from openflow.canvas import procedural as proc
from openflow.canvas import schema
from openflow.canvas import subtitles as sub

from tests.test_speech_v062 import FakeSpeech, Project, node

FF = bool(shutil.which("ffmpeg"))
LINES = ["Bom dia a todos, vamos começar a reunião de hoje com os resultados do mês passado",
         "Obrigada, eu preparei os números e gostaria de apresentar cada um deles agora mesmo",
         "Perfeito, pode continuar que estamos todos ouvindo com bastante atenção aqui",
         "Então o primeiro ponto é o crescimento das vendas no último trimestre inteiro"]


def voice(text, seed, style):
    w = wave.open(io.BytesIO(proc.babble(text, 1.0, seed, style)), "rb")
    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype("float32") / 32768
    return np.interp(np.linspace(0, len(x) - 1, int(len(x) * dz.SR / w.getframerate())), np.arange(len(x)), x).astype("float32")


def scene(styles, seeds, rounds=2):
    xs, segs, t = [], [], 0.0
    for i, txt in enumerate(LINES * rounds):
        x = voice(txt, seeds[i % len(seeds)], styles[i % len(styles)])
        segs.append({"start": t, "end": t + len(x) / dz.SR, "text": txt})
        t += len(x) / dz.SR + 0.3
        xs += [x, np.zeros(int(0.3 * dz.SR), "float32")]
    return np.concatenate(xs), segs


DEEP, HIGH = "grave masculina", "aguda feminina"


class LabelTests(unittest.TestCase):
    def test_two_different_voices_are_found_automatically(self):
        out, found = dz.label_segments(*scene([DEEP, HIGH], [1, 2]), 0)
        self.assertEqual(found, 2)
        self.assertEqual([s["speaker"] for s in out], [0, 1] * 4)

    def test_one_voice_stays_one_voice(self):
        out, found = dz.label_segments(*scene([DEEP], [1]), 0)
        self.assertEqual(found, 1)
        self.assertEqual({s["speaker"] for s in out}, {0})
        self.assertEqual(len(out), 8)

    def test_the_order_is_the_order_of_appearance(self):
        out, _ = dz.label_segments(*scene([HIGH, DEEP], [2, 1]), 0)
        self.assertEqual([s["speaker"] for s in out], [0, 1] * 4)                 # quem fala primeiro é sempre a voz 0, seja grave ou aguda

    def test_the_count_asked_for_is_used(self):
        out, found = dz.label_segments(*scene([DEEP, HIGH], [1, 2]), 2)
        self.assertEqual((found, [s["speaker"] for s in out]), (2, [0, 1] * 4))

    def test_a_segment_where_the_voice_changes_is_split(self):
        a, b = voice(LINES[0], 1, DEEP), voice(LINES[1], 2, HIGH)
        long_seg = {"start": 0.0, "end": (len(a) + len(b)) / dz.SR, "text": LINES[0] + " " + LINES[1]}
        rest, segs = scene([DEEP, HIGH], [1, 2], 1)
        x = np.concatenate([a, b, rest])
        shifted = [dict(s, start=s["start"] + long_seg["end"], end=s["end"] + long_seg["end"]) for s in segs]
        out, found = dz.label_segments(x, [long_seg] + shifted, 2)
        head = [s for s in out if s["end"] <= long_seg["end"] + 0.01]
        self.assertEqual(found, 2)
        self.assertEqual([s["speaker"] for s in head], [0, 1])                      # um trecho virou dois, um de cada voz
        self.assertEqual(" ".join(s["text"] for s in head), LINES[0] + " " + LINES[1])   # nenhuma palavra se perde nem se repete
        self.assertAlmostEqual(head[0]["end"], len(a) / dz.SR, delta=1.0)

    def test_silence_and_tiny_segments_do_not_break(self):
        x = np.zeros(dz.SR * 3, "float32")
        out, found = dz.label_segments(x, [{"start": 0, "end": 3, "text": "oi"}, {"start": 3, "end": 3.1, "text": "x"}], 0)
        self.assertEqual((found, len(out)), (1, 2))
        out, found = dz.label_segments(x, [], 0)
        self.assertEqual((out, found), ([], 1))

    def test_segments_without_speech_keep_the_previous_speaker(self):
        x, segs = scene([DEEP, HIGH], [1, 2], 1)
        segs.insert(2, {"start": segs[1]["end"] + 0.05, "end": segs[1]["end"] + 0.2, "text": "hm"})   # curto demais para analisar
        out, _ = dz.label_segments(x, segs, 2)
        self.assertEqual(out[2]["text"], "hm")
        self.assertEqual(out[2]["speaker"], out[1]["speaker"])


class TextTests(unittest.TestCase):
    SEGS = [dict(sub.seg(0, 2, "Olá."), speaker=0), dict(sub.seg(2, 4, "Tudo bem?"), speaker=0), dict(sub.seg(4, 6, "Tudo."), speaker=1), dict(sub.seg(6, 7, "Que bom."), speaker=0)]

    def test_plain_one_line_per_turn(self):
        self.assertEqual(sub.transcript_text(self.SEGS, "plain"), "Locutor 1: Olá. Tudo bem?\nLocutor 2: Tudo.\nLocutor 1: Que bom.")

    def test_timestamps_label_every_line(self):
        self.assertEqual(sub.transcript_text(self.SEGS, "timestamps").splitlines()[2], "[0:04] Locutor 2: Tudo.")

    def test_paragraphs(self):
        self.assertEqual(sub.transcript_text(self.SEGS, "paragraphs"), "Locutor 1: Olá. Tudo bem?\n\nLocutor 2: Tudo.\n\nLocutor 1: Que bom.")

    def test_names(self):
        self.assertEqual(sub.transcript_text(self.SEGS, "plain", ["Ana", "Bruno"]).splitlines()[1], "Bruno: Tudo.")
        self.assertEqual(sub.transcript_text(self.SEGS, "plain", ["Ana"]).splitlines()[1], "Locutor 2: Tudo.")
        self.assertEqual(dz.parse_names(" Ana, Bruno;Carla \n"), ["Ana", "Bruno", "Carla"])

    def test_without_speakers_nothing_changes(self):
        plain = [sub.seg(0, 2, "um"), sub.seg(2, 4, "dois")]
        self.assertEqual(sub.transcript_text(plain, "plain"), "um dois")

    def test_the_dub_can_read_the_labels_back(self):
        out, _ = sub.assign_speakers([sub.seg(0, 1, l) for l in sub.transcript_text(self.SEGS, "plain", ["Ana", "Bruno"]).splitlines()], [["Ana"], ["Bruno"]], "labels")
        self.assertEqual([i for i, _ in out], [0, 1, 0])


class SchemaTests(unittest.TestCase):
    def test_params(self):
        d = schema.normalize_params("transcript", {})
        self.assertEqual((d["diarize"], d["speakers"], d["speaker_names"]), (False, 0, ""))        # desligado por padrão: projetos antigos saem iguais
        d = schema.normalize_params("transcript", {"diarize": True, "speakers": 99, "speaker_names": "Ana, Bruno"})
        self.assertEqual((d["diarize"], d["speakers"], d["speaker_names"]), (True, 8, "Ana, Bruno"))
        self.assertEqual(schema.normalize_params("transcript", {"diarize": "yes"})["diarize"], False)


def stereo_free_audio(project, text_styles):
    x, segs = scene(*text_styles)
    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(dz.SR)
    w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    w.close()
    aid = project.cs.add_asset(project.cid, buf.getvalue(), "wav", "audio", name="reuniao.wav", mime="audio/wav", provider="upload")["id"]
    project.ids["a"] = aid
    return segs


@unittest.skipUnless(FF, "sem ffmpeg")
class NodeTests(unittest.TestCase):
    def setup(self, styles, seeds, **params):
        pj = Project([], audio=False)
        segs = stereo_free_audio(pj, ([*styles], seeds))
        n = node("t", "transcript", format="plain", language="pt", **params)
        pj.cs.save_layout(pj.cid, {"nodes": [pj.upload("u", "a"), n], "edges": [{"from": "u", "to": "t", "port": "media"}]})
        return pj, FakeSpeech(segs=segs)

    def test_two_voices_come_out_labelled(self):
        pj, fake = self.setup([DEEP, HIGH], [1, 2], diarize=True)
        cv = pj.run(fake)
        self.assertEqual(pj.errors(), {})
        lines = pj.result(cv, "t")["text"].splitlines()
        self.assertEqual(len(lines), 8)
        self.assertEqual([l.split(":")[0] for l in lines], ["Locutor 1", "Locutor 2"] * 4)

    def test_names_and_count(self):
        pj, fake = self.setup([DEEP, HIGH], [1, 2], diarize=True, speakers=2, speaker_names="Ana, Bruno")
        text = pj.result(pj.run(fake), "t")["text"]
        self.assertTrue(text.startswith("Ana: Bom dia"))
        self.assertIn("\nBruno: Obrigada", text)

    def test_off_by_default_keeps_the_old_output(self):
        pj, fake = self.setup([DEEP, HIGH], [1, 2])
        text = pj.result(pj.run(fake), "t")["text"]
        self.assertNotIn("Locutor", text)
        self.assertTrue(text.startswith("Bom dia"))

    def test_one_voice_is_left_alone_without_warnings(self):
        pj, fake = self.setup([DEEP], [1], diarize=True)
        cv = pj.run(fake)
        self.assertNotIn("Locutor", pj.result(cv, "t")["text"])
        self.assertEqual(pj.warnings("t"), [])

    def test_a_model_without_times_cannot_separate_voices(self):
        pj, _ = self.setup([DEEP, HIGH], [1, 2], diarize=True, speakers=2)
        cv = pj.run(FakeSpeech(segs=[sub.seg(0, 9, "tudo num bloco só")], timed=False))
        self.assertEqual(pj.result(cv, "t")["text"], "tudo num bloco só")
        self.assertTrue(any("não devolve o tempo" in w and "separar as vozes" in w for w in pj.warnings("t")))

    def test_without_ffmpeg_the_transcript_survives(self):
        from unittest import mock

        pj, fake = self.setup([DEEP, HIGH], [1, 2], diarize=True, speakers=2)
        with mock.patch.object(dz, "decode", return_value=None):
            cv = pj.run(fake)
        self.assertEqual(pj.errors(), {})
        self.assertNotIn("Locutor", pj.result(cv, "t")["text"])
        self.assertTrue(any("ffmpeg" in w for w in pj.warnings("t")))

    def test_an_analysis_failure_does_not_lose_the_transcript(self):
        from unittest import mock

        pj, fake = self.setup([DEEP, HIGH], [1, 2], diarize=True)
        with mock.patch.object(dz, "label_segments", side_effect=ValueError("boom")):
            cv = pj.run(fake)
        self.assertEqual(pj.errors(), {})
        self.assertTrue(pj.result(cv, "t")["text"].startswith("Bom dia"))
        self.assertTrue(any("ValueError" in w for w in pj.warnings("t")))

    def test_names_fewer_than_voices_warn(self):
        pj, fake = self.setup([DEEP, HIGH], [1, 2], diarize=True, speaker_names="Ana")
        text = pj.result(pj.run(fake), "t")["text"]
        self.assertIn("Locutor 2:", text)
        self.assertTrue(any("1 nome" in w for w in pj.warnings("t")))


if __name__ == "__main__":
    unittest.main()
