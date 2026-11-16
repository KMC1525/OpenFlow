"""v0.66: o erro «AutoConfig.from_pretrained() got multiple values for keyword argument 'local_files_only'» ao transcrever (Whisper local) — o transformers novo já passa `local_files_only` sozinho.

O transformers de verdade não é usado: um `tf` de mentira reproduz a recusa do argumento repetido. Que o Whisper carregue e transcreva com o transformers real não foi verificado aqui."""
import os
import unittest
from unittest import mock

from openflow.canvas import media
from openflow.canvas.media import LocalHFMedia

REPEATED = "transformers.models.auto.configuration_auto.AutoConfig.from_pretrained() got multiple values for keyword argument 'local_files_only'"


class NewTransformers:
    """O transformers que recusa `local_files_only` dentro de `model_kwargs`."""

    def __init__(self):
        self.calls, self.offline = [], []

    def pipeline(self, task, **kw):
        self.calls.append((task, kw))
        if "local_files_only" in (kw.get("model_kwargs") or {}):
            raise TypeError(REPEATED)
        self.offline.append(os.environ.get("HF_HUB_OFFLINE"))
        return lambda *a, **k: {"text": " olá", "chunks": [{"text": " olá", "timestamp": (0.0, 1.0)}]}


class OldTransformers:
    def __init__(self):
        self.calls = []

    def pipeline(self, task, **kw):
        self.calls.append((task, kw))
        return "pipe"


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.pop("HF_HUB_OFFLINE", None)
        self.addCleanup(lambda: os.environ.__setitem__("HF_HUB_OFFLINE", self.saved) if self.saved is not None else os.environ.pop("HF_HUB_OFFLINE", None))

    def test_the_repeated_argument_falls_back_to_the_offline_variable(self):
        tf = NewTransformers()
        pipe = media._hf_pipeline(tf, "automatic-speech-recognition", "openai/whisper-small", None)
        self.assertTrue(callable(pipe))
        self.assertEqual(len(tf.calls), 2)
        self.assertIn("local_files_only", tf.calls[0][1]["model_kwargs"])            # primeiro tenta do jeito de sempre
        self.assertNotIn("model_kwargs", tf.calls[1][1])                              # e sem o argumento repetido na segunda
        self.assertEqual(tf.offline, ["1"])                                           # offline pela variável, durante o carregamento
        self.assertNotIn("HF_HUB_OFFLINE", os.environ)                               # e a variável volta como estava

    def test_the_variable_is_restored_to_what_the_user_had(self):
        os.environ["HF_HUB_OFFLINE"] = "0"
        media._hf_pipeline(NewTransformers(), "text-to-speech", "x/y", None)
        self.assertEqual(os.environ["HF_HUB_OFFLINE"], "0")

    def test_the_old_way_still_works_in_one_call(self):
        tf = OldTransformers()
        self.assertEqual(media._hf_pipeline(tf, "text-to-audio", "facebook/musicgen-small", "bf16"), "pipe")
        self.assertEqual(len(tf.calls), 1)
        self.assertEqual(tf.calls[0][1], {"model": "facebook/musicgen-small", "torch_dtype": "bf16", "model_kwargs": {"local_files_only": True}})

    def test_other_type_errors_are_not_swallowed(self):
        class Broken:
            def pipeline(self, task, **kw):
                raise TypeError("outro problema qualquer")
        with self.assertRaises(TypeError):
            media._hf_pipeline(Broken(), "text-to-speech", "x/y", None)


class WhisperTests(unittest.TestCase):
    def local(self):
        lp = LocalHFMedia({"id": "local_hf"})
        return lp

    def test_the_transcription_that_failed_in_the_screenshot_now_works(self):
        tf = NewTransformers()
        lp = self.local()
        with mock.patch.object(media, "_local_import", return_value=[tf]), mock.patch.object(lp, "_ready", return_value={"dtype": None}):
            text = lp.transcribe(b"RIFF....", "a.wav", "audio/wav", model="openai/whisper-v066-a")
            segs = lp.transcribe_segments(b"RIFF....", "a.wav", "audio/wav", model="openai/whisper-v066-a", duration=3.0)
        self.assertEqual(text, "olá")
        self.assertEqual([(x["start"], x["end"], x["text"]) for x in segs], [(0.0, 1.0, "olá")])

    def test_sound_and_voice_models_load_the_same_way(self):
        for method, model, kwargs in (("sound", "facebook/musicgen-v066", {"prompt": "chuva"}), ("voice", "facebook/mms-tts-v066", {"text": "oi"})):
            tf = NewTransformers()
            lp = self.local()
            with mock.patch.object(media, "_local_import", return_value=[tf]), mock.patch.object(lp, "_ready", return_value={"dtype": None}), \
                    mock.patch.object(media, "_wav_from_array", return_value=b"RIFF"), mock.patch.object(lp, "_pick", return_value=model):
                tf_pipe = tf.pipeline

                def pipe_with_audio(task, **kw):
                    p = tf_pipe(task, **kw)
                    return lambda *a, **k: {"audio": [0.0, 0.1], "sampling_rate": 16000}
                tf.pipeline = pipe_with_audio
                out = getattr(lp, method)(*kwargs.values())
            self.assertEqual(out.mime, "audio/wav", method)


if __name__ == "__main__":
    unittest.main()
