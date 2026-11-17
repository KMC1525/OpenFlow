"""v0.67: «could not convert string to float: 'E aí e aí…'» — um modelo de TRANSCRIÇÃO (Whisper) escolhido como modelo de VOZ na Dublagem. As listas de modelos instalados agora separam por tipo, o OpenFlow recusa
o modelo de tipo errado com uma mensagem clara, e o laço de repetição «E aí e aí e aí…» que o Whisper inventa em trechos sem fala é cortado.

O transformers/Whisper de verdade não são usados (o caso da imagem é reproduzido com o modelo errado indo para o carregador local, que recusa antes de qualquer biblioteca)."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import engine as engine_mod
from openflow.canvas import installed, media, modelkind
from openflow.canvas import subtitles as sub
from openflow.canvas.engine import CanvasEngine
from openflow.canvas.media import LocalHFMedia
from openflow.providers import ProviderError
from tests.helpers import ServerCase
from tests.test_dub_voices_v063 import FF, Project


class KindTests(unittest.TestCase):
    def test_kinds(self):
        for name in ("openai/whisper-small", "openai/whisper-large-v3", "distil-whisper/distil-large-v3", "facebook/wav2vec2-large-960h", "facebook/hubert-large-ls960-ft", "nvidia/parakeet-tdt-0.6b", "UsefulSensors/moonshine-base"):
            self.assertEqual(modelkind.kind_of(name), "stt", name)
        for name in ("suno/bark-small", "facebook/mms-tts-por", "unsloth/orpheus-3b-0.1-ft", "unsloth/csm-1b", "microsoft/speecht5_tts", "hexgrad/Kokoro-82M", "coqui/XTTS-v2", "parler-tts/parler-tts-mini-v1"):
            self.assertEqual(modelkind.kind_of(name), "voice", name)
        for name in ("facebook/musicgen-small", "facebook/musicgen-medium", "cvssp/audioldm2", "stabilityai/stable-audio-open-1.0", "ACE-Step/Ace-Step1.5"):
            self.assertEqual(modelkind.kind_of(name), "sound", name)

    def test_unknown_names_stay_unknown(self):
        for name in ("someone/odd-model", "stabilityai/sd-turbo", "Lightricks/LTX-Video", "", None, "acme/studio"):
            self.assertEqual(modelkind.kind_of(name), "", name)           # não dá para saber: continua aparecendo e funcionando como antes

    def test_the_speecht5_variants(self):
        self.assertEqual(modelkind.kind_of("microsoft/speecht5_asr"), "stt")
        self.assertEqual(modelkind.kind_of("microsoft/speecht5_tts"), "voice")

    def test_the_message(self):
        m = modelkind.mismatch("voice", "openai/whisper-small")
        self.assertIn("«openai/whisper-small» é um modelo de transcrição", m)
        self.assertIn("não de voz", m)
        self.assertIn("Bark, MMS-TTS, Orpheus, CSM ou VoxCPM", m)
        self.assertIn("MusicGen", modelkind.mismatch("sound", "suno/bark-small"))
        self.assertIn("Whisper", modelkind.mismatch("stt", "facebook/musicgen-small"))
        self.assertEqual(modelkind.mismatch("voice", "suno/bark-small"), "")                 # o tipo certo
        self.assertEqual(modelkind.mismatch("voice", "someone/odd-model"), "")               # tipo desconhecido: deixa passar
        self.assertEqual(modelkind.mismatch("image", "openai/whisper-small"), "")            # só vale para som, voz e transcrição


class InstalledListTests(unittest.TestCase):
    DOWNLOADED = [{"model": "openai/whisper-small", "precision": "fp16"}, {"model": "facebook/musicgen-small", "precision": "fp16"}, {"model": "suno/bark-small", "precision": "fp16"},
                  {"model": "someone/odd-model", "precision": "fp16"}, {"model": "stabilityai/sd-turbo", "precision": "fp16"}]

    def names(self, cap):
        with mock.patch.object(installed, "downloaded_hf_models", return_value=self.DOWNLOADED):
            from openflow.storage import Store

            store = Store(Path(tempfile.mkdtemp()))
            return [i["model"] for i in installed.installed(store.get_settings(), store.models_dir, cap)]

    def test_each_list_only_shows_models_of_its_kind(self):
        self.assertEqual(self.names("voice"), ["suno/bark-small", "someone/odd-model", "stabilityai/sd-turbo"])          # o Whisper e o MusicGen saíram da lista de voz
        self.assertEqual(self.names("stt"), ["openai/whisper-small", "someone/odd-model", "stabilityai/sd-turbo"])
        self.assertEqual(self.names("sound"), ["facebook/musicgen-small", "someone/odd-model", "stabilityai/sd-turbo"])

    def test_image_list_has_no_audio_models(self):
        got = self.names("image")
        self.assertEqual(got, ["someone/odd-model", "stabilityai/sd-turbo"])


class LocalGuardTests(unittest.TestCase):
    def test_a_transcription_model_as_the_voice_model_says_so_clearly(self):
        lp = LocalHFMedia({"id": "local_hf"})
        with self.assertRaises(ProviderError) as cm:
            lp.voice("E aí e aí e aí", model="openai/whisper-small")
        self.assertIn("é um modelo de transcrição", str(cm.exception))
        self.assertNotIn("float", str(cm.exception))

    def test_the_other_wrong_combinations(self):
        lp = LocalHFMedia({"id": "local_hf"})
        with self.assertRaises(ProviderError) as cm:
            lp.sound("chuva", model="suno/bark-small")
        self.assertIn("modelo de voz", str(cm.exception))
        with self.assertRaises(ProviderError) as cm:
            lp.transcribe(b"x", "a.wav", "audio/wav", model="facebook/musicgen-small")
        self.assertIn("modelo de sons e músicas", str(cm.exception))

    def test_unknown_names_are_not_blocked(self):
        lp = LocalHFMedia({"id": "local_hf"})
        lp._expect("voice", "someone/odd-model")           # não levanta
        lp._expect("voice", "suno/bark-small")


@unittest.skipUnless(FF, "sem ffmpeg")
class DubTests(unittest.TestCase):
    def test_the_dub_of_the_screenshot_now_fails_with_a_clear_message(self):
        srt = "1\n00:00:00,500 --> 00:00:03,500\nE aí e aí e aí\n"
        pj = Project(srt, [], dub={"language": "en", "model": "openai/whisper-small"})
        with mock.patch.object(engine_mod, "build_media", return_value=LocalHFMedia({"id": "local_hf"})):
            pj.run()
        err = pj.errors()["d"]
        self.assertIn("«openai/whisper-small» é um modelo de transcrição", err)
        self.assertNotIn("could not convert string to float", err)


class RouteTests(ServerCase):
    def use(self, cap, model):
        return self.c.json("POST", "/api/media/hub/use", {"cap": cap, "provider": "local_hf", "model": model})

    def test_use_refuses_the_wrong_kind(self):
        s, r = self.use("voice", "openai/whisper-small")
        self.assertEqual(s, 400)
        self.assertIn("modelo de transcrição", str(r))
        s, r = self.use("stt", "suno/bark-small")
        self.assertEqual(s, 400)
        self.assertIn("modelo de voz", str(r))

    def test_use_accepts_the_right_kind_and_unknown_names(self):
        self.assertEqual(self.use("stt", "openai/whisper-small")[0], 200)
        self.assertEqual(self.use("voice", "suno/bark-small")[0], 200)
        self.assertEqual(self.use("sound", "facebook/musicgen-small")[0], 200)
        self.assertEqual(self.use("voice", "someone/odd-model")[0], 200)
        self.assertEqual(self.use("image", "stabilityai/sd-turbo")[0], 200)


class LoopTests(unittest.TestCase):
    def test_a_whisper_loop_is_cut(self):
        loop = "E aí " + "e aí " * 40
        self.assertEqual(sub.collapse_loops(loop), "E aí e aí")
        self.assertEqual(sub.collapse_loops("Obrigado. " * 30), "Obrigado. Obrigado.")
        self.assertEqual(sub.collapse_loops("Bom dia a todos. " + "Obrigado. " * 20 + "Até logo."), "Bom dia a todos. Obrigado. Obrigado. Até logo.")

    def test_normal_repetitions_stay(self):
        self.assertEqual(sub.collapse_loops("la " * 8 + "hoje vamos falar sobre o mar e as ondas"), ("la " * 8 + "hoje vamos falar sobre o mar e as ondas"))
        self.assertEqual(sub.collapse_loops("Eu te amo. Eu te amo. Eu te amo. Eu te amo, de verdade, para sempre."), "Eu te amo. Eu te amo. Eu te amo. Eu te amo, de verdade, para sempre.")
        self.assertEqual(sub.collapse_loops("curto"), "curto")
        self.assertEqual(sub.collapse_loops(""), "")

    def test_case_and_punctuation_do_not_hide_a_loop(self):
        text = " ".join(["Tchau!", "tchau", "TCHAU,"] * 8)
        self.assertEqual(sub.collapse_loops(text), "Tchau! tchau")        # as três formas contam como a mesma palavra (maiúsculas e pontuação não contam): um laço de 24 repetições fica com duas

    def test_segments_from_the_speech_model_are_cleaned(self):
        chunks = [{"text": " " + "E aí " * 30, "timestamp": (0.0, 20.0)}, {"text": " Fim.", "timestamp": (20.0, 22.0)}]
        segs = sub.segments_from_chunks(chunks)
        self.assertEqual([s["text"] for s in segs], ["E aí E aí", "Fim."])
        self.assertEqual(segs[0]["end"], 20.0)                                                  # o tempo do trecho não muda

    def test_local_whisper_returns_clean_text(self):
        lp = LocalHFMedia({"id": "local_hf"})
        res = {"text": " " + "E aí " * 30, "chunks": [{"text": " " + "E aí " * 30, "timestamp": (0.0, 5.0)}]}
        with mock.patch.object(lp, "_asr", return_value=res):
            self.assertEqual(lp.transcribe(b"x", "a.wav", "audio/wav"), "E aí E aí")
            self.assertEqual(lp.transcribe_segments(b"x", "a.wav", "audio/wav", duration=5.0)[0]["text"], "E aí E aí")
        with mock.patch.object(lp, "_asr", return_value={"text": " " + "Tchau. " * 40}):
            self.assertEqual(lp.transcribe_segments(b"x", "a.wav", "audio/wav", duration=5.0)[0]["text"], "Tchau. Tchau.")


if __name__ == "__main__":
    unittest.main()
