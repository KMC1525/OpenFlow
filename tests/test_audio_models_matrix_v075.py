"""v0.75: compatibilidade dos modelos locais de SOM, VOZ e TRANSCRIÇÃO — cada modelo sugerido (e variações de nome) vai pelo caminho certo do provedor local, com `transformers`/`diffusers`/`voxcpm` simulados.
Nenhum modelo real foi executado: isto prova o roteamento e os argumentos, não a qualidade do áudio."""
import sys
import types
import unittest
from unittest import mock

import numpy as np

from openflow.canvas import localmodels as lm
from openflow.canvas import media, modelkind
from openflow.canvas.media import LocalHFMedia, Media
from openflow.providers import ProviderError
from tests.helpers import voxcpm_python_ok


def wav(seconds=1.0, rate=16000):
    return media._wav_from_array(0.3 * np.sin(np.linspace(0, 200 * np.pi, int(seconds * rate))), rate)



_VOX_PATCH = None


def setUpModule():
    global _VOX_PATCH
    _VOX_PATCH = voxcpm_python_ok()   # os testes simulam a biblioteca voxcpm: a exigência de Python 3.10 não é o assunto deles


def tearDownModule():
    if _VOX_PATCH is not None:
        _VOX_PATCH.stop()


class Base(unittest.TestCase):
    def setUp(self):
        media._LOCAL_CACHE.clear()
        self.lp = LocalHFMedia({"id": "local_hf"})
        self.lp.ctl = types.SimpleNamespace(note=lambda m: None, check=lambda: None)
        self.calls = []

    def patched(self, extra_imports=None):
        imports = {"numpy": np, "torch": mock.MagicMock(), **(extra_imports or {})}
        return [mock.patch.object(media, "_local_import", side_effect=lambda *n, **k: [imports[x] for x in n]), mock.patch.object(media, "_device", return_value=("cpu", None)),
                mock.patch.object(lm, "downloaded_precision", return_value="fp32"), mock.patch.object(lm, "has_fp16_variant", return_value=False), mock.patch.object(lm, "torch_dtype", return_value="fp32")]


class VoiceMatrixTests(Base):
    def test_every_suggested_voice_model_takes_its_own_path(self):
        pipe_calls = []
        tf = types.SimpleNamespace(pipeline=lambda task, **kw: (pipe_calls.append((task, kw)), lambda text, **k: {"audio": np.sin(np.linspace(0, 100, 16000)), "sampling_rate": 16000})[1])
        for model in media.MEDIA_PRESETS["local_hf"]["suggest"]["voice"]:
            media._LOCAL_CACHE.clear()
            routed = []
            fake_vox = types.SimpleNamespace(VoxCPM=types.SimpleNamespace(from_pretrained=lambda m, **kw: types.SimpleNamespace(tts_model=types.SimpleNamespace(sample_rate=48000), generate=lambda **k: routed.append("voxcpm") or np.zeros(4800, "float32") + 0.1)))
            ctx = self.patched({"transformers": tf})
            ctx += [mock.patch.object(self.lp, "_voice_orpheus", side_effect=lambda *a, **k: routed.append("orpheus") or Media(wav(), "audio/wav")),
                    mock.patch.object(self.lp, "_voice_csm", side_effect=lambda *a, **k: routed.append("csm") or Media(wav(), "audio/wav")), mock.patch.dict(sys.modules, {"voxcpm": fake_vox})]
            for c in ctx:
                c.start()
            try:
                out = self.lp.voice("Olá, mundo.", model=model, speed=1.0)
            finally:
                for c in reversed(ctx):
                    c.stop()
            self.assertEqual(out.mime, "audio/wav", model)
            want = "voxcpm" if "voxcpm" in model.lower() else "orpheus" if "orpheus" in model.lower() else "csm" if "csm" in model.lower() else None
            self.assertEqual(routed, [want] if want else [], model)
        self.assertTrue(pipe_calls and all(task == "text-to-speech" for task, _ in pipe_calls))      # bark e mms-tts usam o pipeline text-to-speech

    def test_whisper_and_other_non_voice_models_are_refused_as_voice(self):
        for model in ("openai/whisper-small", "unsloth/whisper-base", "facebook/musicgen-small", "cvssp/audioldm2"):
            with self.assertRaises(ProviderError, msg=model) as cm:
                self.lp.voice("Oi.", model=model)
            self.assertIn("não de voz", str(cm.exception), model)


class SoundMatrixTests(Base):
    def test_every_suggested_sound_model_is_generated_with_the_right_library(self):
        chunks = []

        class Pipe:
            def __call__(self, prompt, **kw):
                chunks.append(("transformers", kw))
                return {"audio": np.sin(np.linspace(0, 100, 32000)).reshape(1, -1), "sampling_rate": 32000}
        tf = types.SimpleNamespace(pipeline=lambda task, **kw: Pipe())

        def diff_pipe(name):
            class D:
                vae = types.SimpleNamespace(config=types.SimpleNamespace(sampling_rate=44100), sampling_rate=44100)
                vocoder = types.SimpleNamespace(config=types.SimpleNamespace(sampling_rate=16000))

                def to(self, dev):
                    return self

                def __call__(self, prompt, **kw):
                    chunks.append((name, kw))
                    return types.SimpleNamespace(audios=[types.SimpleNamespace(detach=lambda: types.SimpleNamespace(cpu=lambda: types.SimpleNamespace(float=lambda: types.SimpleNamespace(numpy=lambda: np.sin(np.linspace(0, 100, 44100)).astype("float32").reshape(1, -1)))))])
            D.__name__ = name
            return D()
        for model in media.MEDIA_PRESETS["local_hf"]["suggest"]["sound"]:
            media._LOCAL_CACHE.clear()
            chunks.clear()
            cls = "StableAudio3Pipeline" if "stable-audio-3" in model else "StableAudioPipeline" if "stable-audio" in model else "AudioLDM2Pipeline"
            diffusers = types.SimpleNamespace(DiffusionPipeline=types.SimpleNamespace(from_pretrained=lambda m, **kw: diff_pipe(cls)))
            torch = mock.MagicMock()
            torch.cuda.is_available.return_value = False
            ctx = self.patched({"transformers": tf, "diffusers": diffusers, "torch": torch})
            for c in ctx:
                c.start()
            try:
                out = self.lp.sound("chuva forte", kind="sfx", duration=4, model=model, seed=1)
            finally:
                for c in reversed(ctx):
                    c.stop()
            self.assertEqual(out.mime, "audio/wav", model)
            self.assertEqual(chunks[0][0], "transformers" if "musicgen" in model else cls, model)
            kw = chunks[0][1]
            if "stable-audio-3" in model:
                self.assertEqual(kw["duration"], 4.0, model)
            elif "stable-audio" in model:
                self.assertEqual(kw["audio_end_in_s"], 4.0, model)
            elif "audioldm" in model:
                self.assertEqual(kw["audio_length_in_s"], 4.0, model)

    def test_wrong_kind_is_refused(self):
        for model in ("openai/whisper-small", "suno/bark-small", "openbmb/VoxCPM2"):
            with self.assertRaises(ProviderError, msg=model):
                self.lp.sound("x", model=model)


class SttMatrixTests(Base):
    def test_every_suggested_transcription_model_returns_timed_segments(self):
        calls = []

        def make_pipe(task, **kw):
            def pipe(path, **k):
                calls.append(k)
                return {"text": "olá mundo", "chunks": [{"text": "olá", "timestamp": (0.0, 0.5)}, {"text": "mundo", "timestamp": (0.5, None)}]}
            return pipe
        tf = types.SimpleNamespace(pipeline=make_pipe)
        for model in media.MEDIA_PRESETS["local_hf"]["suggest"]["stt"]:
            media._LOCAL_CACHE.clear()
            ctx = self.patched({"transformers": tf})
            for c in ctx:
                c.start()
            try:
                segs = self.lp.transcribe_segments(wav(2.0), "a.wav", "audio/wav", language="pt", model=model, duration=2.0)
                text = self.lp.transcribe(wav(2.0), "a.wav", "audio/wav", model=model)
            finally:
                for c in reversed(ctx):
                    c.stop()
            self.assertEqual([s["text"] for s in segs], ["olá", "mundo"], model)
            self.assertEqual(segs[0]["end"], 0.5, model)
            self.assertEqual(text, "olá mundo", model)
            self.assertTrue(self.lp.timed_segments(model))
        self.assertTrue(all(k.get("return_timestamps") for k in calls))

    def test_non_transcription_models_are_refused(self):
        for model in ("suno/bark-small", "facebook/musicgen-small", "openbmb/VoxCPM2"):
            with self.assertRaises(ProviderError, msg=model) as cm:
                self.lp.transcribe(wav(), "a.wav", "audio/wav", model=model)
            self.assertIn("não de transcrição", str(cm.exception), model)


class KindNamesTests(unittest.TestCase):
    def test_real_world_model_names(self):
        table = {
            "voice": ["suno/bark", "suno/bark-small", "facebook/mms-tts-por", "microsoft/speecht5_tts", "kakao-enterprise/vits-ljs", "hexgrad/Kokoro-82M", "coqui/XTTS-v2", "parler-tts/parler-tts-mini-v1",
                      "unsloth/orpheus-3b-0.1-ft", "canopylabs/orpheus-3b-0.1-ft", "unsloth/csm-1b", "sesame/csm-1b", "openbmb/VoxCPM2", "openbmb/VoxCPM-0.5B", "SWivid/F5-TTS", "ResembleAI/chatterbox", "OuteAI/OuteTTS-0.3-1B"],
            "stt": ["openai/whisper-large-v3", "openai/whisper-small", "distil-whisper/distil-large-v3", "unsloth/whisper-base", "facebook/wav2vec2-base-960h", "nvidia/parakeet-tdt-0.6b-v2", "UsefulSensors/moonshine-base"],
            "sound": ["facebook/musicgen-small", "facebook/musicgen-stereo-medium", "cvssp/audioldm2", "cvssp/audioldm2-music", "ucsd-reach/musicldm", "stabilityai/stable-audio-open-1.0", "stabilityai/stable-audio-3-small-sfx",
                      "ACE-Step/ACE-Step-v1-3.5B", "riffusion/riffusion-model-v1", "m-a-p/YuE-s1-7B-anneal-en-cot", "declare-lab/tango", "declare-lab/tango-2", "yue-music"],
            "": ["stabilityai/sd-turbo", "black-forest-labs/FLUX.1-dev", "Qwen/Qwen-Image", "Lightricks/LTX-Video", "openai/shap-e", "meta-llama/Llama-3.2-1B",
               "yuewen/some-image-model", "tangolike/anything", "tango-labs/flux-lora"],           # nomes de organização que começam como um modelo de áudio não podem esconder o modelo de imagem
        }
        wrong = [(m, want, modelkind.kind_of(m)) for want, models in table.items() for m in models if modelkind.kind_of(m) != want]
        self.assertEqual(wrong, [])


if __name__ == "__main__":
    unittest.main()
