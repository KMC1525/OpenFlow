"""v0.68: suporte a modelos locais de som e voz do Hugging Face — sons e músicas pelos pipelines de áudio do diffusers (AudioLDM, AudioLDM2, MusicLDM, Stable Audio Open e 3), a velocidade do nó Voz nos
modelos de voz locais (antes só a voz de demonstração a usava) e a compatibilidade/sugestões da busca.

Nenhum modelo foi executado: `diffusers` e `torch` são simulados (os argumentos de cada pipeline foram conferidos lendo o código do diffusers 0.43), e o ffmpeg e o numpy são de verdade. Que um
AudioLDM2 ou um Stable Audio de verdade gerem o som, e com a qualidade esperada, não foi verificado."""
import io
import shutil
import types
import unittest
import wave
from unittest import mock

import numpy as np

from openflow.canvas import media, soundmodels
from openflow.canvas import procedural as proc
from openflow.canvas.media import LocalHFMedia, Media
from openflow.providers import ProviderError

FF = bool(shutil.which("ffmpeg"))


def seconds(data):
    w = wave.open(io.BytesIO(data), "rb")
    return w.getnframes() / w.getframerate(), w.getnchannels(), w.getframerate()


class FamilyTests(unittest.TestCase):
    def test_families(self):
        self.assertEqual(soundmodels.family("facebook/musicgen-small"), "musicgen")
        self.assertEqual(soundmodels.family("facebook/musicgen-stereo-medium"), "musicgen")
        self.assertEqual(soundmodels.family("cvssp/audioldm2"), "audioldm")
        self.assertEqual(soundmodels.family("cvssp/audioldm2-music"), "audioldm")
        self.assertEqual(soundmodels.family("ucsd-reach/musicldm"), "audioldm")
        self.assertEqual(soundmodels.family("stabilityai/stable-audio-open-1.0"), "stable-audio-open")
        self.assertEqual(soundmodels.family("stabilityai/stable-audio-3-small-sfx"), "stable-audio-3")
        self.assertEqual(soundmodels.family("stabilityai/stable-audio-3-medium"), "stable-audio-3")
        self.assertEqual(soundmodels.family("suno/bark-small"), "")
        self.assertEqual(soundmodels.family(None), "")

    def test_who_uses_diffusers(self):
        self.assertTrue(all(soundmodels.uses_diffusers(m) for m in ("cvssp/audioldm2", "stabilityai/stable-audio-open-1.0", "stabilityai/stable-audio-3-medium", "ucsd-reach/musicldm")))
        self.assertFalse(any(soundmodels.uses_diffusers(m) for m in ("facebook/musicgen-small", "suno/bark-small", "")))


class CallKwargsTests(unittest.TestCase):
    def test_each_pipeline_gets_its_own_time_argument(self):
        self.assertEqual(soundmodels.call_kwargs("StableAudio3Pipeline", 12.5), {"duration": 12.5})
        self.assertEqual(soundmodels.call_kwargs("StableAudioPipeline", 12.5), {"audio_end_in_s": 12.5, "num_inference_steps": 100})
        self.assertEqual(soundmodels.call_kwargs("AudioLDM2Pipeline", 8), {"audio_length_in_s": 8.0, "num_inference_steps": 50})
        self.assertEqual(soundmodels.call_kwargs("AudioLDMPipeline", 8)["audio_length_in_s"], 8.0)
        self.assertEqual(soundmodels.call_kwargs("MusicLDMPipeline", 8)["audio_length_in_s"], 8.0)

    def test_the_limits(self):
        self.assertEqual(soundmodels.call_kwargs("StableAudioPipeline", 500)["audio_end_in_s"], 47.0)
        self.assertEqual(soundmodels.call_kwargs("StableAudio3Pipeline", 5000)["duration"], 190.0)
        self.assertEqual(soundmodels.call_kwargs("AudioLDM2Pipeline", 500)["audio_length_in_s"], 30.0)
        self.assertEqual(soundmodels.call_kwargs("StableAudio3Pipeline", 0)["duration"], 1.0)

    def test_the_extra_field_wins(self):
        kw = soundmodels.call_kwargs("AudioLDM2Pipeline", 8, {"num_inference_steps": 20, "guidance_scale": 5})
        self.assertEqual((kw["num_inference_steps"], kw["guidance_scale"], kw["audio_length_in_s"]), (20, 5, 8.0))

    def test_the_sampling_rate(self):
        ns = types.SimpleNamespace
        self.assertEqual(soundmodels.sampling_rate(ns(vae=ns(config=ns(sampling_rate=44100)))), 44100)        # Stable Audio 3
        self.assertEqual(soundmodels.sampling_rate(ns(vae=ns(sampling_rate=44100))), 44100)                   # Stable Audio Open
        self.assertEqual(soundmodels.sampling_rate(ns(vocoder=ns(config=ns(sampling_rate=16000)))), 16000)     # AudioLDM2
        self.assertEqual(soundmodels.sampling_rate(ns(vae=ns(config=ns()), vocoder=ns(config=ns(sampling_rate=16000)))), 16000)
        self.assertEqual(soundmodels.sampling_rate(ns()), 0)

    def test_the_limit_note(self):
        self.assertIn("até 47 s", soundmodels.limit_note("stabilityai/stable-audio-open-1.0", 60))
        self.assertEqual(soundmodels.limit_note("stabilityai/stable-audio-open-1.0", 30), "")
        self.assertIn("até 30 s", soundmodels.limit_note("cvssp/audioldm2", 90))
        self.assertEqual(soundmodels.limit_note("unknown/model", 999), "")


class FakeTorch:
    class cuda:
        @staticmethod
        def is_available():
            return False

    class Generator:
        def __init__(self, dev="cpu"):
            self.seed = None

        def manual_seed(self, s):
            self.seed = s
            return self


class Tensor:
    """O que o diffusers devolve em `.audios[0]`: um tensor (canais, amostras) com .detach().cpu().float().numpy()."""

    def __init__(self, arr):
        self.arr = np.asarray(arr, dtype="float32")

    def detach(self):
        return self

    def cpu(self):
        return self

    def float(self):
        return self

    def numpy(self):
        return self.arr


def fake_diffusers(pipe_cls_name, audio, vae_rate=None, vocoder_rate=None):
    calls = {}
    ns = types.SimpleNamespace

    class Pipe:
        def __init__(self):
            self.vae = ns(config=ns(sampling_rate=vae_rate)) if vae_rate else None
            self.vocoder = ns(config=ns(sampling_rate=vocoder_rate)) if vocoder_rate else None

        def to(self, dev):
            calls["device"] = dev
            return self

        def __call__(self, prompt, **kw):
            calls["prompt"], calls["kw"] = prompt, kw
            return ns(audios=[Tensor(audio)])
    Pipe.__name__ = pipe_cls_name

    class DiffusionPipeline:
        @staticmethod
        def from_pretrained(model, **kw):
            calls["load"] = (model, kw)
            return Pipe()
    return ns(DiffusionPipeline=DiffusionPipeline), calls


class SoundDiffusersTests(unittest.TestCase):
    def run_sound(self, model, cls, audio, duration=8, extra=None, vae_rate=None, vocoder_rate=None):
        diff, calls = fake_diffusers(cls, audio, vae_rate, vocoder_rate)
        lp = LocalHFMedia({"id": "local_hf"})
        notes = []
        lp.ctl = types.SimpleNamespace(note=notes.append)
        imports = {"diffusers": diff, "torch": FakeTorch, "numpy": np}
        with mock.patch.object(media, "_local_import", side_effect=lambda *names, **kw: [imports[n] for n in names]), mock.patch.object(lp, "_ready", return_value={"dtype": "fp16"}):
            out = lp.sound("chuva forte", kind="sfx", duration=duration, model=model, extra=extra, seed=7)
        return out, calls, notes

    def test_audioldm2_mono(self):
        out, calls, notes = self.run_sound("cvssp/audioldm2-v068", "AudioLDM2Pipeline", np.sin(np.linspace(0, 200, 16000 * 2)), duration=2, vocoder_rate=16000)
        self.assertEqual(out.mime, "audio/wav")
        dur, ch, rate = seconds(out.data)
        self.assertEqual((round(dur, 2), ch, rate), (2.0, 1, 16000))
        self.assertEqual(calls["load"][0], "cvssp/audioldm2-v068")
        self.assertTrue(calls["load"][1]["local_files_only"])                                            # nada é baixado em silêncio
        self.assertEqual(calls["prompt"], "chuva forte")
        self.assertEqual(calls["kw"]["audio_length_in_s"], 2.0)
        self.assertEqual(calls["kw"]["generator"].seed, 7)
        self.assertEqual(calls["device"], "cpu")

    def test_stable_audio_open_stereo(self):
        stereo = np.stack([np.sin(np.linspace(0, 300, 44100)), np.cos(np.linspace(0, 300, 44100))])     # (canais, amostras), como o diffusers devolve
        out, calls, _ = self.run_sound("stabilityai/stable-audio-open-v068", "StableAudioPipeline", stereo, duration=1, vae_rate=44100)
        dur, ch, rate = seconds(out.data)
        self.assertEqual((round(dur, 2), ch, rate), (1.0, 2, 44100))
        self.assertEqual(calls["kw"]["audio_end_in_s"], 1.0)

    def test_stable_audio_3_uses_duration(self):
        out, calls, _ = self.run_sound("stabilityai/stable-audio-3-v068", "StableAudio3Pipeline", np.sin(np.linspace(0, 100, 44100)).reshape(1, -1), duration=1, vae_rate=44100)
        self.assertEqual(calls["kw"]["duration"], 1.0)
        self.assertNotIn("audio_end_in_s", calls["kw"])
        self.assertEqual(seconds(out.data)[2], 44100)

    def test_the_extra_field_reaches_the_pipeline(self):
        _, calls, _ = self.run_sound("cvssp/audioldm2-v068b", "AudioLDM2Pipeline", np.zeros(16000) + 0.1, duration=1, vocoder_rate=16000, extra={"num_inference_steps": 10})
        self.assertEqual(calls["kw"]["num_inference_steps"], 10)

    def test_a_long_request_is_capped_and_the_user_is_told(self):
        _, calls, notes = self.run_sound("stabilityai/stable-audio-open-v068c", "StableAudioPipeline", np.zeros(44100) + 0.1, duration=120, vae_rate=44100)
        self.assertEqual(calls["kw"]["audio_end_in_s"], 47.0)
        self.assertTrue(any("até 47 s" in n for n in notes))

    def test_a_pipeline_without_a_sampling_rate_says_so(self):
        with self.assertRaises(ProviderError) as cm:
            self.run_sound("cvssp/audioldm2-v068d", "AudioLDM2Pipeline", np.zeros(100) + 0.1)
        self.assertIn("taxa de amostragem", str(cm.exception))

    def test_a_wrong_kind_is_still_refused_before_loading(self):
        lp = LocalHFMedia({"id": "local_hf"})
        with self.assertRaises(ProviderError) as cm:
            lp.sound("x", model="openai/whisper-small")
        self.assertIn("modelo de transcrição", str(cm.exception))

    def test_musicgen_keeps_the_transformers_path(self):
        lp = LocalHFMedia({"id": "local_hf"})
        with mock.patch.object(lp, "_sound_diffusers") as d, mock.patch.object(media, "_local_import", side_effect=ProviderError("sem transformers")):
            with self.assertRaises(ProviderError):
                lp.sound("x", model="facebook/musicgen-small")
        d.assert_not_called()


@unittest.skipUnless(FF, "sem ffmpeg")
class SpeedTests(unittest.TestCase):
    def setUp(self):
        self.lp = LocalHFMedia({"id": "local_hf"})
        self.lp.ctl = types.SimpleNamespace(note=lambda m: None)
        self.wav = Media(proc.babble("Bom dia a todos, vamos começar a reunião de hoje.", 1.0, 1), "audio/wav")

    def test_faster_and_slower_without_changing_the_pitch(self):
        base = seconds(self.wav.data)[0]
        fast = self.lp._with_speed(self.wav, 2.0)
        slow = self.lp._with_speed(self.wav, 0.5)
        self.assertAlmostEqual(seconds(fast.data)[0], base / 2, delta=0.15)
        self.assertAlmostEqual(seconds(slow.data)[0], base * 2, delta=0.3)
        self.assertEqual(fast.mime, "audio/wav")

    def test_normal_speed_returns_the_same_object(self):
        self.assertIs(self.lp._with_speed(self.wav, 1.0), self.wav)
        self.assertIs(self.lp._with_speed(self.wav, 1.01), self.wav)
        self.assertIs(self.lp._with_speed(self.wav, "x"), self.wav)

    def test_out_of_range_is_clamped(self):
        base = seconds(self.wav.data)[0]
        self.assertAlmostEqual(seconds(self.lp._with_speed(self.wav, 9).data)[0], base / 2, delta=0.15)

    def test_without_ffmpeg_the_voice_is_left_alone_and_the_user_is_told(self):
        notes = []
        self.lp.ctl = types.SimpleNamespace(note=notes.append)
        with mock.patch.object(proc, "ffmpeg_path", return_value=None):
            self.assertIs(self.lp._with_speed(self.wav, 1.5), self.wav)
        self.assertTrue(any("ffmpeg" in n for n in notes))

    def test_the_voice_models_apply_it(self):
        pipe = lambda text, **kw: {"audio": np.sin(np.linspace(0, 400, 16000 * 2)), "sampling_rate": 16000}          # 2 s de fala
        tf = types.SimpleNamespace(pipeline=lambda task, **kw: pipe)
        with mock.patch.object(media, "_local_import", side_effect=lambda *names, **kw: [tf if n == "transformers" else np for n in names]), \
                mock.patch.object(self.lp, "_ready", return_value={"dtype": None}):
            normal = self.lp.voice("oi", voice="", speed=1.0, model="facebook/mms-tts-v068")
            quick = self.lp.voice("oi", voice="", speed=2.0, model="facebook/mms-tts-v068")
        self.assertAlmostEqual(seconds(normal.data)[0], 2.0, delta=0.05)
        self.assertAlmostEqual(seconds(quick.data)[0], 1.0, delta=0.15)

    def test_orpheus_and_csm_apply_it_too(self):
        two = Media(media._wav_from_array(np.sin(np.linspace(0, 400, 24000 * 2)), 24000), "audio/wav")
        with mock.patch.object(self.lp, "_voice_orpheus", return_value=two), mock.patch.object(self.lp, "_voice_csm", return_value=two):
            a = self.lp.voice("oi", speed=2.0, model="unsloth/orpheus-3b-0.1-ft")
            b = self.lp.voice("oi", speed=2.0, model="unsloth/csm-1b")
        self.assertAlmostEqual(seconds(a.data)[0], 1.0, delta=0.15)
        self.assertAlmostEqual(seconds(b.data)[0], 1.0, delta=0.15)

    def test_the_demo_voice_is_not_slowed_twice(self):
        from openflow.canvas.media import DemoMedia

        d = DemoMedia({"id": "demo"})
        fast = d.voice("Bom dia a todos, vamos começar", speed=1.5).data
        base = d.voice("Bom dia a todos, vamos começar", speed=1.0).data
        self.assertLess(seconds(fast)[0], seconds(base)[0])                                          # a demo já usa a velocidade por conta própria


class SuggestTests(unittest.TestCase):
    def test_new_models_are_suggested(self):
        sug = media.MEDIA_PRESETS["local_hf"]["suggest"]
        for m in ("facebook/musicgen-small", "cvssp/audioldm2", "stabilityai/stable-audio-open-1.0", "stabilityai/stable-audio-3-small-sfx"):
            self.assertIn(m, sug["sound"])
            self.assertEqual(soundmodels.family(m) or "musicgen", soundmodels.family(m) or "musicgen")
        self.assertIn("facebook/mms-tts-eng", sug["voice"])
        self.assertEqual(sug["sound"][0], "facebook/musicgen-small")                                  # o padrão continua sendo o primeiro


if __name__ == "__main__":
    unittest.main()
