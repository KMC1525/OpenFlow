"""v0.71: suporte ao openbmb/VoxCPM2 — fala em 30 idiomas, design de voz pela descrição, clonagem controlável e clonagem fiel por um áudio de referência, em 48 kHz.

A biblioteca `voxcpm` (e o torch) são SIMULADOS aqui: os argumentos de `VoxCPM.from_pretrained` e de `generate` foram conferidos lendo o código do voxcpm 2.0.3, e o README/config do openbmb/VoxCPM2 foram lidos pelo
Hub. NENHUM modelo real foi baixado ou executado (o Hugging Face está bloqueado onde isto foi desenvolvido): que o VoxCPM2 gere a voz, clone bem e fale em português, não foi verificado. O ffmpeg e o numpy são reais."""
import contextlib
import io
import shutil
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

from openflow import soundsearch as ss
from openflow.canvas import engine as engine_mod
from openflow.canvas import localmodels as lm
from openflow.canvas import media, modelkind, schema, speech
from openflow.canvas import procedural as proc
from openflow.canvas import voxcpm as vx
from openflow.canvas.engine import CanvasEngine
from openflow.canvas.media import LocalHFMedia, Media, MediaProvider
from openflow.providers import ProviderError
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
REPO_FILES = ["", ".gitattributes", "README.md", "audiovae.pth", "config.json", "model.safetensors", "special_tokens_map.json", "tokenization_voxcpm2.py", "tokenizer.json", "tokenizer_config.json"]   # o que o openbmb/VoxCPM2 tem no Hub


def seconds(data):
    w = wave.open(io.BytesIO(data), "rb")
    return w.getnframes() / w.getframerate(), w.getframerate()


class PureTests(unittest.TestCase):
    def test_which_models(self):
        for m in ("openbmb/VoxCPM2", "openbmb/VoxCPM-0.5B", "OpenBMB/VoxCPM1.5", "foo/voxcpm2-bf16"):
            self.assertTrue(vx.is_voxcpm(m), m)
        for m in ("suno/bark-small", "", None, "unsloth/orpheus-3b-0.1-ft"):
            self.assertFalse(vx.is_voxcpm(m), m)
        self.assertTrue(vx.supports_reference("openbmb/VoxCPM2"))
        self.assertTrue(vx.supports_reference("openbmb/VoxCPM3"))
        self.assertFalse(vx.supports_reference("openbmb/VoxCPM1.5"))
        self.assertFalse(vx.supports_reference("openbmb/VoxCPM-0.5B"))
        self.assertFalse(vx.supports_reference("suno/bark-small"))

    def test_voice_design_text(self):
        self.assertEqual(vx.with_description("Olá!", "mulher jovem, voz doce"), "(mulher jovem, voz doce)Olá!")
        self.assertEqual(vx.with_description("Olá!", "  "), "Olá!")
        self.assertEqual(vx.with_description("Olá!", "jovem (calma)\nfeminina"), "(jovem, calma, feminina)Olá!")    # parênteses e quebras de linha da descrição não quebram a sintaxe
        self.assertEqual(vx.with_description("(voz grave)Olá!", "outra"), "(voz grave)Olá!")                           # quem já escreveu o design à mão fica como está
        self.assertLessEqual(len(vx.clean_description("x" * 5000)), vx.MAX_DESCRIPTION)

    def test_split_short_text_is_whole(self):
        self.assertEqual(vx.split_text("Uma frase só."), ["Uma frase só."])
        self.assertEqual(vx.split_text("   "), [])

    def test_split_long_text_keeps_every_word_and_respects_the_limit(self):
        sent = "Esta é uma frase razoavelmente longa, com vírgulas, para testar o corte do texto."
        text = " ".join(sent for _ in range(20))
        chunks = vx.split_text(text, 200)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(len(c) <= 200 for c in chunks), [len(c) for c in chunks])
        self.assertTrue(all(c.rstrip()[-1] in ".!?" for c in chunks))                         # corta em fim de frase quando dá
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_split_a_huge_sentence_without_punctuation(self):
        text = " ".join(f"palavra{i}" for i in range(400))
        chunks = vx.split_text(text, 150)
        self.assertTrue(all(len(c) <= 150 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_options_are_validated(self):
        self.assertEqual(vx.options(None), {"cfg_value": 2.0, "inference_timesteps": 10})
        o = vx.options({"cfg_value": "3.5", "inference_timesteps": 999, "normalize": 1, "denoise": False, "voz": "x", "max_len": "abc"})
        self.assertEqual((o["cfg_value"], o["inference_timesteps"], o["normalize"], o["denoise"]), (3.5, 50, True, False))
        self.assertNotIn("voz", o)
        self.assertNotIn("max_len", o)


class DownloadTests(unittest.TestCase):
    def files(self):
        return [{"name": n, "size": 10} for n in REPO_FILES[1:]]

    def test_the_audio_codec_is_downloaded_with_the_weights(self):
        for prec in ("fp32", "fp16", "bf16"):
            names = {f["name"] for f in lm.select_files(self.files(), prec)}
            self.assertIn("audiovae.pth", names, prec)                                           # antes o .pth era descartado quando há safetensors
            self.assertIn("model.safetensors", names)
            self.assertTrue({"config.json", "tokenizer.json", "tokenizer_config.json", "tokenization_voxcpm2.py"} <= names, prec)
            self.assertNotIn("README.md", names)

    def test_other_pth_files_are_still_skipped_next_to_safetensors(self):
        files = [{"name": n, "size": 1} for n in ("model.safetensors", "old_weights.pth", "audiovae.pth")]
        self.assertEqual({f["name"] for f in lm.select_files(files, "fp16")}, {"model.safetensors", "audiovae.pth"})


class KindAndSearchTests(unittest.TestCase):
    def test_kind_and_suggestions(self):
        self.assertEqual(modelkind.kind_of("openbmb/VoxCPM2"), "voice")
        self.assertIn("openbmb/VoxCPM2", media.MEDIA_PRESETS["local_hf"]["suggest"]["voice"])
        with self.assertRaises(ProviderError):
            LocalHFMedia({"id": "local_hf"}).sound("x", model="openbmb/VoxCPM2")                 # um modelo de voz não serve para sons

    def row(self, **kw):
        return dict({"id": "openbmb/VoxCPM2", "tags": ["voxcpm", "text-to-speech", "tts", "voice-cloning", "voice-design"], "library": "voxcpm", "pipeline_tag": "text-to-speech", "downloads": 5, "likes": 5}, **kw)

    def test_the_search_badge(self):
        for topic in ("tts", "clone", "design"):
            c = ss.compat("voice", topic, self.row())
            self.assertEqual(c["level"], "ok", topic)
            self.assertIn("voxcpm", c["reason"])
        self.assertEqual(ss.compat("voice", "tts", self.row(tags=["gguf"], library="gguf"))["level"], "no")
        self.assertEqual(ss.compat("voice", "dub", self.row())["level"], "no")                   # dublar fala → fala continua fora
        self.assertEqual(ss.compat("voice", "clone", {"id": "someone/rvc-model", "tags": ["rvc"], "library": "", "pipeline_tag": "audio-to-audio"})["level"], "no")

    def test_the_topics_of_the_real_model(self):
        self.assertTrue({"tts", "clone", "design"} <= set(ss.topics_of(self.row())))


class FakeEngine:
    """O objeto `voxcpm.VoxCPM`: anota o que recebe e devolve uma onda de 1 s por chamada (48 kHz)."""

    def __init__(self, rate=48000):
        self.tts_model = types.SimpleNamespace(sample_rate=rate)
        self.calls = []
        self.ref_seen = []

    def generate(self, **kw):
        self.calls.append(kw)
        for key in ("reference_wav_path", "prompt_wav_path"):
            if key in kw:
                self.ref_seen.append((key, Path(kw[key]).exists()))
        return np.sin(np.linspace(0, 440, self.tts_model.sample_rate)).astype("float32")


class FakeTorch:
    @staticmethod
    def no_grad():
        return contextlib.nullcontext()


def fake_library(engine, loads):
    class VoxCPM:
        @staticmethod
        def from_pretrained(model, **kw):
            loads.append((model, kw))
            return engine
    return types.SimpleNamespace(VoxCPM=VoxCPM)


class GenerateTests(unittest.TestCase):
    n = 0

    def setUp(self):
        GenerateTests.n += 1
        self.model = f"openbmb/VoxCPM2-t{GenerateTests.n}"                                       # o carregador guarda um modelo por nome
        self.engine, self.loads, self.notes = FakeEngine(), [], []
        self.lp = LocalHFMedia({"id": "local_hf"})
        self.lp.ctl = types.SimpleNamespace(note=self.notes.append)

    def speak(self, text="Olá, mundo.", model=None, **kw):
        imports = {"numpy": np, "torch": FakeTorch}
        with mock.patch.dict(sys.modules, {"voxcpm": fake_library(self.engine, self.loads)}), mock.patch.object(media, "_local_import", side_effect=lambda *n, **k: [imports[x] for x in n]), \
                mock.patch.object(media, "_device", return_value=("cpu", None)), mock.patch.object(self.lp, "_ready", return_value={"dtype": None}):
            return self.lp.voice(text, model=model or self.model, **kw)

    def wav_ref(self, secs=2.0):
        t = np.linspace(0, secs, int(16000 * secs))
        return Media(media._wav_from_array(0.3 * np.sin(2 * np.pi * 220 * t), 16000), "audio/wav")

    def test_plain_speech_comes_out_at_48k(self):
        out = self.speak("Bom dia, pessoal.")
        self.assertEqual(seconds(out.data), (1.0, 48000))
        self.assertEqual(out.mime, "audio/wav")
        model, kw = self.loads[0]
        self.assertEqual(model, self.model)
        self.assertTrue(kw["local_files_only"])                                                  # nada é baixado em silêncio
        self.assertFalse(kw["load_denoiser"])
        self.assertEqual(kw["device"], "cpu")
        call = self.engine.calls[0]
        self.assertEqual(call["text"], "Bom dia, pessoal.")                                      # sem descrição, o texto vai como está
        self.assertEqual((call["cfg_value"], call["inference_timesteps"]), (2.0, 10))
        self.assertNotIn("reference_wav_path", call)

    def test_the_model_is_loaded_once(self):
        self.speak("Um.")
        self.speak("Dois.")
        self.assertEqual(len(self.loads), 1)

    def test_voice_design_from_the_description(self):
        self.speak("Bem-vindos!", instructions="mulher jovem, voz doce e animada")
        self.assertEqual(self.engine.calls[0]["text"], "(mulher jovem, voz doce e animada)Bem-vindos!")
        self.assertNotIn("reference_wav_path", self.engine.calls[0])

    def test_the_style_of_the_project_goes_into_the_description_too(self):
        from openflow.canvas import voicestyle

        self.speak("Oi.", instructions=voicestyle.compose("grave e calma", "tom de documentário"))
        self.assertEqual(self.engine.calls[0]["text"], "(grave e calma, tom de documentário)Oi.")

    @unittest.skipUnless(FF, "sem ffmpeg")
    def test_controllable_cloning_with_a_reference(self):
        ref = (self.wav_ref(2.0).data, "audio/wav")
        self.speak("Esta é uma voz clonada.", instructions="um pouco mais rápido, alegre", reference=ref)
        call = self.engine.calls[0]
        self.assertEqual(call["text"], "(um pouco mais rápido, alegre)Esta é uma voz clonada.")             # o estilo guia a voz clonada
        self.assertIn("reference_wav_path", call)
        self.assertNotIn("prompt_wav_path", call)
        self.assertNotIn("prompt_text", call)
        self.assertEqual(self.engine.ref_seen, [("reference_wav_path", True)])                              # o arquivo existia na hora de gerar
        self.assertFalse(Path(call["reference_wav_path"]).exists())                                         # e foi apagado depois

    @unittest.skipUnless(FF, "sem ffmpeg")
    def test_ultimate_cloning_uses_the_reference_and_its_transcript(self):
        ref = (self.wav_ref(2.0).data, "audio/wav")
        self.speak("Fala nova.", instructions="alegre", reference=ref, reference_text="Texto da referência.")
        call = self.engine.calls[0]
        self.assertEqual(call["text"], "Fala nova.")                                                         # sem descrição: nesse modo ela não é lida
        self.assertEqual((call["prompt_text"], call["prompt_wav_path"]), ("Texto da referência.", call["reference_wav_path"]))
        self.assertTrue(any("ignorei a descrição" in n for n in self.notes))

    @unittest.skipUnless(FF, "sem ffmpeg")
    def test_a_video_reference_is_read_through_its_audio_and_long_ones_are_trimmed(self):
        tmp = Path(tempfile.mkdtemp())
        mp4 = tmp / "v.mp4"
        import subprocess

        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=40", "-f", "lavfi", "-i", "sine=frequency=300:duration=40", "-shortest", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        seen = {}

        def gen(**kw):
            r = wave.open(kw["reference_wav_path"], "rb")
            seen["secs"], seen["rate"], seen["ch"] = r.getnframes() / r.getframerate(), r.getframerate(), r.getnchannels()
            return np.zeros(48000, dtype="float32") + 0.1
        self.engine.generate = gen
        self.speak("Oi.", reference=(mp4.read_bytes(), "video/mp4"))
        self.assertAlmostEqual(seen["secs"], 30.0, delta=0.5)                                               # sem o texto da referência, só os primeiros 30 s
        self.assertEqual((seen["rate"], seen["ch"]), (16000, 1))

    def test_a_model_that_cannot_clone_ignores_the_reference_and_says_so(self):
        self.model = "openbmb/VoxCPM1.5-t"
        out = self.speak("Oi.", reference=(b"x", "audio/wav"))
        self.assertNotIn("reference_wav_path", self.engine.calls[0])
        self.assertTrue(any("não clona voz" in n for n in self.notes))
        self.assertEqual(seconds(out.data)[1], 48000)
        self.assertFalse(self.lp.clones_voice("openbmb/VoxCPM1.5"))
        self.assertTrue(self.lp.clones_voice("openbmb/VoxCPM2"))

    def test_a_long_text_is_spoken_in_pieces_with_pauses(self):
        sent = "Esta é uma frase de teste que se repete bastante para passar do limite de um trecho."
        text = " ".join(sent for _ in range(10))
        out = self.speak(text, instructions="calma")
        n = len(self.engine.calls)
        self.assertGreater(n, 1)
        self.assertTrue(all(c["text"].startswith("(calma)") for c in self.engine.calls))                    # a descrição vale em cada trecho (a mesma voz)
        self.assertAlmostEqual(seconds(out.data)[0], n * 1.0 + (n - 1) * vx.SILENCE_SECONDS, delta=0.05)

    def test_advanced_options_from_the_extra_field(self):
        self.speak("Oi.", extra={"cfg_value": 3, "inference_timesteps": 20, "normalize": True})
        call = self.engine.calls[0]
        self.assertEqual((call["cfg_value"], call["inference_timesteps"], call["normalize"]), (3.0, 20, True))

    @unittest.skipUnless(FF, "sem ffmpeg")
    def test_speed_is_applied_after_generating(self):
        slow = self.speak("Oi.", speed=0.5)
        self.assertAlmostEqual(seconds(slow.data)[0], 2.0, delta=0.15)

    def test_a_library_error_has_a_clear_message(self):
        def boom(**kw):
            raise RuntimeError("CUDA out of memory")
        self.engine.generate = boom
        with self.assertRaises(ProviderError) as cm:
            self.speak("Oi.")
        self.assertIn("VoxCPM não conseguiu gerar a voz", str(cm.exception))
        self.assertIn("out of memory", str(cm.exception))

    def test_without_the_library_it_says_how_to_install(self):
        imports = {"numpy": np, "torch": FakeTorch}
        with mock.patch.dict(sys.modules, {"voxcpm": None}), mock.patch.object(media, "_local_import", side_effect=lambda *n, **k: [imports[x] for x in n]):
            with self.assertRaises(ProviderError) as cm:
                self.lp.voice("Oi.", model="openbmb/VoxCPM2")
        self.assertIn("pip install voxcpm", str(cm.exception))
        self.assertIn("--extras voxcpm", str(cm.exception))

    def test_a_model_not_downloaded_is_refused_before_loading(self):
        imports = {"numpy": np, "torch": FakeTorch}
        with mock.patch.dict(sys.modules, {"voxcpm": fake_library(self.engine, self.loads)}), mock.patch.object(media, "_local_import", side_effect=lambda *n, **k: [imports[x] for x in n]), \
                mock.patch.object(lm, "downloaded_precision", return_value=""):
            with self.assertRaises(ProviderError) as cm:
                self.lp.voice("Oi.", model="openbmb/VoxCPM2")
        self.assertIn("ainda não foi baixado", str(cm.exception))
        self.assertEqual(self.loads, [])

    def test_the_voice_style_note_is_empty_for_voxcpm(self):
        self.assertEqual(self.lp.voice_style_note("openbmb/VoxCPM2"), "")
        self.assertNotEqual(self.lp.voice_style_note("suno/bark-small"), "")


class CloningProvider(MediaProvider):
    id, label, caps = "clone", "Clone", ("voice",)

    def __init__(self, clones=True):
        super().__init__({"id": "clone"})
        self.clones, self.calls = clones, []

    def clones_voice(self, model=""):
        return self.clones

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions="", reference=None, reference_text=""):
        self.calls.append({"text": text, "reference": reference, "reference_text": reference_text, "instructions": instructions})
        return Media(proc.babble(text, 1.0, 1), "audio/wav")


class Project:
    def __init__(self, nodes, edges, seconds_=4.0):
        self.store = Store(Path(tempfile.mkdtemp()))
        self.cs = self.store.projects
        self.cid = self.cs.create("clone")["id"]
        self.ref = self.cs.add_asset(self.cid, proc.music("calma", seconds_, 1), "wav", "audio", name="ref.wav", mime="audio/wav", provider="upload")
        self.cs.save_layout(self.cid, {"nodes": [dict(n, params=json_params(n, self.ref)) for n in nodes], "edges": edges})

    def run(self, provider):
        self.events = []
        with mock.patch.object(engine_mod, "build_media", return_value=provider), mock.patch.object(speech, "build_media", return_value=provider):
            CanvasEngine(self.store, self.cid, self.events.append, lambda: False).run(None, True)
        return self.cs.get(self.cid)

    def errors(self):
        return {e["id"]: e.get("message") for e in self.events if e.get("type") == "node" and e.get("state") == "error"}

    def warnings(self, nid):
        return [w for e in self.events if e.get("type") == "node" and e.get("id") == nid for w in e.get("warnings", [])]


def json_params(n, ref):
    p = dict(n.get("params") or {})
    if n["type"] == "upload":
        p["files"] = [ref["id"]]
    return p


class NodeTests(unittest.TestCase):
    def test_the_voice_node_has_a_reference_port(self):
        pd = schema.port_def("voice", "reference")
        self.assertEqual(pd["accepts"], ["audio", "video"])
        self.assertFalse(pd["multi"])
        self.assertTrue(schema.compatible("audio", pd["accepts"]))
        self.assertTrue(schema.compatible("video", pd["accepts"]))
        self.assertFalse(schema.compatible("image", pd["accepts"]))
        self.assertEqual(schema.normalize_params("voice", {})["reference_text"], "")
        self.assertEqual(schema.normalize_params("voice", {"reference_text": "x" * 5000})["reference_text"], "x" * 1000)

    def nodes(self, **voice):
        return [{"id": "r", "type": "upload", "x": 0, "y": 0}, {"id": "v", "type": "voice", "x": 0, "y": 0, "params": dict({"text": "Olá, mundo."}, **voice)}], [{"from": "r", "to": "v", "port": "reference"}]

    def test_the_reference_reaches_a_model_that_clones(self):
        pj = Project(*self.nodes(reference_text="Fala de referência."))
        prov = CloningProvider(True)
        pj.run(prov)
        self.assertEqual(pj.errors(), {})
        call = prov.calls[0]
        self.assertEqual(call["reference"][1], "audio/wav")
        self.assertGreater(len(call["reference"][0]), 1000)
        self.assertEqual(call["reference_text"], "Fala de referência.")
        self.assertEqual(pj.warnings("v"), [])

    def test_a_model_that_does_not_clone_gets_no_reference_and_the_user_is_told(self):
        pj = Project(*self.nodes())
        prov = CloningProvider(False)
        pj.run(prov)
        self.assertEqual(pj.errors(), {})
        self.assertIsNone(prov.calls[0]["reference"])
        self.assertTrue(any("não clona voz" in w for w in pj.warnings("v")))

    def test_without_a_reference_nothing_changes(self):
        pj = Project([{"id": "v", "type": "voice", "x": 0, "y": 0, "params": {"text": "Oi."}}], [])
        prov = CloningProvider(True)
        pj.run(prov)
        self.assertEqual(pj.errors(), {})
        self.assertIsNone(prov.calls[0]["reference"])

    def test_changing_the_reference_text_or_the_file_makes_the_node_stale(self):
        pj = Project(*self.nodes())
        pj.run(CloningProvider(True))
        eng = CanvasEngine(pj.store, pj.cid, lambda e: None, lambda: False)
        cv = pj.cs.get(pj.cid)
        h1 = eng.node_hash(cv, next(n for n in cv["nodes"] if n["id"] == "v"))
        cv["nodes"][1]["params"]["reference_text"] = "outro"
        self.assertNotEqual(h1, eng.node_hash(cv, next(n for n in cv["nodes"] if n["id"] == "v")))
        cv["nodes"][1]["params"]["reference_text"] = ""
        cv["edges"] = []
        self.assertNotEqual(h1, eng.node_hash(cv, next(n for n in cv["nodes"] if n["id"] == "v")))


@unittest.skipUnless(FF, "sem ffmpeg")
class DubTests(unittest.TestCase):
    def test_each_character_can_clone_their_own_reference(self):
        nodes = [{"id": "u", "type": "upload", "x": 0, "y": 0}, {"id": "r", "type": "upload", "x": 0, "y": 0}, {"id": "t", "type": "text", "x": 0, "y": 0, "params": {"text": "Maria: Bom dia.\nJoão: Olá, tudo bem?"}},
                 {"id": "m", "type": "voice", "x": 0, "y": 0, "title": "Maria", "params": {"reference_text": "Texto da Maria."}}, {"id": "j", "type": "voice", "x": 0, "y": 0, "title": "João", "params": {}},
                 {"id": "d", "type": "dub", "x": 0, "y": 0, "params": {"language": "keep"}}]
        edges = [{"from": "u", "to": "d", "port": "media"}, {"from": "t", "to": "d", "port": "script"}, {"from": "m", "to": "d", "port": "voices"}, {"from": "j", "to": "d", "port": "voices"}, {"from": "r", "to": "m", "port": "reference"}]
        pj = Project(nodes, edges, 6.0)
        prov = CloningProvider(True)
        pj.run(prov)
        self.assertEqual(pj.errors(), {})
        by = {c["text"]: c for c in prov.calls}
        self.assertIsNotNone(by["Bom dia."]["reference"])                                            # a Maria clona a referência dela…
        self.assertEqual(by["Bom dia."]["reference_text"], "Texto da Maria.")
        self.assertIsNone(by["Olá, tudo bem?"]["reference"])                                          # …e o João, sem referência, usa a voz normal

    def test_a_dub_voice_with_a_reference_on_a_model_that_does_not_clone_warns_once(self):
        nodes = [{"id": "u", "type": "upload", "x": 0, "y": 0}, {"id": "r", "type": "upload", "x": 0, "y": 0}, {"id": "t", "type": "text", "x": 0, "y": 0, "params": {"text": "Maria: Um.\nMaria: Dois."}},
                 {"id": "m", "type": "voice", "x": 0, "y": 0, "title": "Maria", "params": {}}, {"id": "d", "type": "dub", "x": 0, "y": 0, "params": {"language": "keep"}}]
        edges = [{"from": "u", "to": "d", "port": "media"}, {"from": "t", "to": "d", "port": "script"}, {"from": "m", "to": "d", "port": "voices"}, {"from": "r", "to": "m", "port": "reference"}]
        pj = Project(nodes, edges, 6.0)
        prov = CloningProvider(False)
        pj.run(prov)
        self.assertEqual(pj.errors(), {})
        self.assertTrue(all(c["reference"] is None for c in prov.calls))
        self.assertEqual(len([w for w in pj.warnings("d") if "não clona voz" in w]), 1)


if __name__ == "__main__":
    unittest.main()
