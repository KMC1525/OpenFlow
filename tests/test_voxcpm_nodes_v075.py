"""v0.75: os nós Voz e Dublagem de ponta a ponta com o modelo openbmb/VoxCPM2.

Aqui NADA do OpenFlow é de mentira, da interface do nó até o provedor local (`LocalHFMedia._voice_voxcpm`): só a biblioteca `voxcpm` (e o torch/dispositivo/download) é simulada — uma biblioteca falsa que anota cada chamada a `generate` e
devolve uma onda de 48 kHz com a duração proporcional ao texto, como uma voz de verdade faria. O ffmpeg e o numpy são reais. Que o VoxCPM2 de verdade soe bem, clone bem e fale português bem NÃO foi verificado."""
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

from openflow.canvas import localmodels as lm
from openflow.canvas import media
from openflow.canvas import procedural as proc
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
MODEL = "openbmb/VoxCPM2"
RATE = 48000


class FakeTorch:
    @staticmethod
    def no_grad():
        return contextlib.nullcontext()


class FakeVox:
    """A biblioteca `voxcpm`: `VoxCPM.from_pretrained(...)` devolve um motor que anota as chamadas."""

    def __init__(self, seconds_per_char=0.04):
        self.calls, self.loads, self.spc = [], [], seconds_per_char
        outer = self

        class Engine:
            tts_model = types.SimpleNamespace(sample_rate=RATE)

            def generate(self, **kw):
                text = kw["text"]
                outer.calls.append(dict(kw, ref_exists=[Path(kw[k]).exists() for k in ("reference_wav_path", "prompt_wav_path") if k in kw]))
                n = int(max(0.3, len(text) * outer.spc) * RATE)
                return (0.3 * np.sin(np.linspace(0, 400 * np.pi, n))).astype("float32")

        class VoxCPM:
            @staticmethod
            def from_pretrained(model, **kw):
                outer.loads.append((model, kw))
                return Engine()
        self.VoxCPM = VoxCPM


def seconds(data):
    w = wave.open(io.BytesIO(data), "rb")
    return w.getnframes() / w.getframerate(), w.getframerate()


class Base(unittest.TestCase):
    def setUp(self):
        media._LOCAL_CACHE.clear()
        self.fake = FakeVox()
        self.store = Store(Path(tempfile.mkdtemp()))
        self.cs = self.store.projects
        self.cid = self.cs.create("voxcpm")["id"]
        imports = {"numpy": np, "torch": FakeTorch}
        self.patches = [mock.patch.dict(sys.modules, {"voxcpm": self.fake}), mock.patch.object(media, "_local_import", side_effect=lambda *n, **k: [imports[x] for x in n]),
                        mock.patch.object(media, "_device", return_value=("cpu", None)), mock.patch.object(lm, "downloaded_precision", return_value="bf16"), mock.patch.object(lm, "has_fp16_variant", return_value=False), mock.patch.object(lm, "torch_dtype", return_value="bf16")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.assets = {}

    def audio(self, name="ref.wav", seconds_=3.0):
        t = np.linspace(0, seconds_, int(16000 * seconds_))
        data = media._wav_from_array(0.3 * np.sin(2 * np.pi * 220 * t), 16000) if True else b""
        a = self.cs.add_asset(self.cid, data, "wav", "audio", name=name, mime="audio/wav", provider="upload")
        return a

    def run_nodes(self, nodes, edges=(), force=True):
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": list(edges)})
        self.events = []
        CanvasEngine(self.store, self.cid, self.events.append, lambda: False).run(None, force)
        return self.cs.get(self.cid)

    def result(self, cv, nid):
        return next(n for n in cv["nodes"] if n["id"] == nid)["result"]

    def errors(self):
        return {e["id"]: e.get("message") for e in self.events if e.get("type") == "node" and e.get("state") == "error"}

    def warnings(self, nid):
        return [w for e in self.events if e.get("type") == "node" and e.get("id") == nid for w in e.get("warnings", [])]

    def asset_bytes(self, cv, nid):
        a = next(x for x in cv["assets"] if x["id"] == self.result(cv, nid)["assets"][0])
        return self.cs.asset_path(self.cid, a["file"]).read_bytes()

    @staticmethod
    def node(nid, ntype, title="", **params):
        n = {"id": nid, "type": ntype, "x": 0, "y": 0, "params": params}
        if title:
            n["title"] = title
        return n

    def upload(self, nid, *assets):
        return self.node(nid, "upload", files=[a["id"] for a in assets])

    def voice(self, nid, title="", **params):
        return self.node(nid, "voice", title, provider="local_hf", model=MODEL, **params)


class VoiceNodeTests(Base):
    def test_plain_speech_through_the_node(self):
        cv = self.run_nodes([self.voice("v", text="Bom dia, pessoal. Vamos começar.")])
        self.assertEqual(self.errors(), {})
        self.assertEqual(self.fake.calls[0]["text"], "Bom dia, pessoal. Vamos começar.")
        self.assertEqual(self.fake.loads[0][0], MODEL)
        self.assertTrue(self.fake.loads[0][1]["local_files_only"])
        dur, rate = seconds(self.asset_bytes(cv, "v"))
        self.assertEqual(rate, RATE)                                                           # 48 kHz até o arquivo do projeto
        self.assertAlmostEqual(dur, 33 * 0.04, delta=0.1)
        self.assertEqual(self.warnings("v"), [])                                               # o VoxCPM lê a descrição: nada a avisar

    def test_voice_design_and_the_project_style(self):
        style = self.node("s", "style_prompt", text="tom de documentário", **{"global": True})
        self.run_nodes([style, self.voice("v", text="Era uma vez.", voice_style="homem idoso, voz grave e calma")])
        self.assertEqual(self.errors(), {})
        self.assertEqual(self.fake.calls[0]["text"], "(homem idoso, voz grave e calma, tom de documentário)Era uma vez.")

    def test_voice_design_text_with_parentheses_from_the_user_is_respected(self):
        self.run_nodes([self.voice("v", text="(voz de robô)Olá, humano.", voice_style="alegre")])
        self.assertEqual(self.fake.calls[0]["text"], "(voz de robô)Olá, humano.")

    def test_controllable_cloning_from_an_audio_reference(self):
        if not FF:
            self.skipTest("sem ffmpeg")
        ref = self.audio()
        cv = self.run_nodes([self.upload("r", ref), self.voice("v", text="Esta é a minha voz clonada.", voice_style="mais rápido")], [{"id": "e", "from": "r", "to": "v", "port": "reference"}])
        self.assertEqual(self.errors(), {})
        call = self.fake.calls[0]
        self.assertEqual(call["text"], "(mais rápido)Esta é a minha voz clonada.")
        self.assertIn("reference_wav_path", call)
        self.assertNotIn("prompt_text", call)
        self.assertEqual(call["ref_exists"], [True])
        self.assertEqual(seconds(self.asset_bytes(cv, "v"))[1], RATE)

    def test_ultimate_cloning_with_the_reference_text(self):
        if not FF:
            self.skipTest("sem ffmpeg")
        ref = self.audio()
        self.run_nodes([self.upload("r", ref), self.voice("v", text="Texto novo.", voice_style="alegre", reference_text="Texto da referência.")], [{"id": "e", "from": "r", "to": "v", "port": "reference"}])
        call = self.fake.calls[0]
        self.assertEqual((call["text"], call["prompt_text"]), ("Texto novo.", "Texto da referência."))
        self.assertEqual(call["prompt_wav_path"], call["reference_wav_path"])
        self.assertEqual(call["ref_exists"], [True, True])

    def test_a_video_works_as_the_reference(self):
        if not FF:
            self.skipTest("sem ffmpeg")
        import subprocess

        tmp = Path(tempfile.mkdtemp())
        mp4 = tmp / "r.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=2", "-f", "lavfi", "-i", "sine=frequency=300:duration=2", "-shortest", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        vid = self.cs.add_asset(self.cid, mp4.read_bytes(), "mp4", "video", name="r.mp4", mime="video/mp4", provider="upload")
        self.run_nodes([self.upload("r", vid), self.voice("v", text="Oi.")], [{"id": "e", "from": "r", "to": "v", "port": "reference"}])
        self.assertEqual(self.errors(), {})
        self.assertIn("reference_wav_path", self.fake.calls[0])

    def test_a_long_text_is_spoken_in_pieces_and_joined(self):
        sent = "Esta é uma frase de teste que se repete bastante para passar do limite de um trecho."
        cv = self.run_nodes([self.voice("v", text=" ".join([sent] * 12))])
        self.assertEqual(self.errors(), {})
        n = len(self.fake.calls)
        self.assertGreater(n, 2)
        dur, _ = seconds(self.asset_bytes(cv, "v"))
        self.assertAlmostEqual(dur, sum(len(c["text"]) for c in self.fake.calls) * 0.04 + (n - 1) * 0.18, delta=0.3)

    def test_speed_changes_the_length_without_changing_the_pitch_machinery(self):
        if not FF:
            self.skipTest("sem ffmpeg")
        normal = seconds(self.asset_bytes(self.run_nodes([self.voice("v", text="Uma frase para medir a velocidade da voz.", speed=1.0)]), "v"))[0]
        fast = seconds(self.asset_bytes(self.run_nodes([self.voice("v", text="Uma frase para medir a velocidade da voz.", speed=2.0)]), "v"))[0]
        self.assertAlmostEqual(fast, normal / 2, delta=0.15)

    def test_the_result_is_cached_and_a_change_regenerates(self):
        nodes = [self.voice("v", text="Olá.")]
        self.run_nodes(nodes)
        self.run_nodes(nodes, force=False)
        self.assertEqual(len(self.fake.calls), 1)                                              # nada mudou: sem nova chamada ao modelo
        self.run_nodes([self.voice("v", text="Olá.", voice_style="calma")], force=False)
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(len(self.fake.loads), 1)                                              # e o modelo continua carregado

    def test_a_reference_on_a_model_that_cannot_clone_warns_and_still_speaks(self):
        ref = self.audio()
        pipe = lambda text, **kw: {"audio": np.sin(np.linspace(0, 400, 16000)), "sampling_rate": 16000}  # noqa: E731
        tf = types.SimpleNamespace(pipeline=lambda task, **kw: pipe)
        imports = {"numpy": np, "torch": FakeTorch, "transformers": tf}
        with mock.patch.object(media, "_local_import", side_effect=lambda *n, **k: [imports[x] for x in n]):
            cv = self.run_nodes([self.upload("r", ref), self.node("v", "voice", provider="local_hf", model="facebook/mms-tts-por", text="Olá.")], [{"id": "e", "from": "r", "to": "v", "port": "reference"}])
        self.assertEqual(self.errors(), {})
        self.assertTrue(any("não clona voz" in w for w in self.warnings("v")))
        self.assertEqual(seconds(self.asset_bytes(cv, "v"))[1], 16000)

    def test_clear_errors_in_the_node(self):
        with mock.patch.object(lm, "downloaded_precision", return_value=""):
            self.run_nodes([self.voice("v", text="Oi.")])
        self.assertIn("ainda não foi baixado", self.errors()["v"])
        with mock.patch.dict(sys.modules, {"voxcpm": None}):
            self.run_nodes([self.voice("v", text="Oi.")])
        self.assertIn("pip install voxcpm", self.errors()["v"])
        self.fake.VoxCPM.from_pretrained = staticmethod(lambda model, **kw: types.SimpleNamespace(tts_model=types.SimpleNamespace(sample_rate=RATE), generate=mock.Mock(side_effect=RuntimeError("CUDA out of memory"))))
        media._LOCAL_CACHE.clear()
        self.run_nodes([self.voice("v", text="Oi.")])
        self.assertIn("VoxCPM não conseguiu gerar a voz", self.errors()["v"])


@unittest.skipUnless(FF, "sem ffmpeg")
class DubNodeTests(Base):
    SCRIPT = "Maria: Bom dia, pessoal. Hoje vamos falar do mar.\nJoão: Bom dia! Eu trouxe o café para todos.\nMaria: Então vamos começar a reunião agora mesmo."

    def source(self, kind="audio", seconds_=12.0):
        if kind == "audio":
            return self.cs.add_asset(self.cid, proc.music("calma", seconds_, 1), "wav", "audio", name="aula.wav", mime="audio/wav", provider="upload")
        import subprocess

        tmp = Path(tempfile.mkdtemp())
        mp4 = tmp / "v.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=blue:s=160x120:d={seconds_}", "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds_}", "-shortest", "-pix_fmt", "yuv420p", str(mp4)], check=True)
        return self.cs.add_asset(self.cid, mp4.read_bytes(), "mp4", "video", name="aula.mp4", mime="video/mp4", provider="upload")

    def dub(self, **params):
        return self.node("d", "dub", **dict({"provider": "local_hf", "model": MODEL, "language": "keep"}, **params))

    def graph(self, voices=(), refs=None, src_kind="audio", script=None, **dub_params):
        src = self.source(src_kind)
        nodes = [self.upload("u", src), self.node("t", "text", text=self.SCRIPT if script is None else script), self.dub(**dub_params)]
        edges = [{"id": "e1", "from": "u", "to": "d", "port": "media"}, {"id": "e2", "from": "t", "to": "d", "port": "script"}]
        for i, v in enumerate(voices):
            nodes.append(v)
            edges.append({"id": f"ev{i}", "from": v["id"], "to": "d", "port": "voices"})
        for vid, ref in (refs or {}).items():
            nodes.append(self.upload("r_" + vid, ref))
            edges.append({"id": "er_" + vid, "from": "r_" + vid, "to": vid, "port": "reference"})
        return nodes, edges

    def test_dub_with_the_nodes_own_voxcpm2_voice(self):
        cv = self.run_nodes(*self.graph(voice_style="mulher calma, de apresentadora"))
        self.assertEqual(self.errors(), {})
        texts = [c["text"] for c in self.fake.calls]
        self.assertTrue(all(t.startswith("(mulher calma, de apresentadora)") for t in texts), texts)
        self.assertGreaterEqual(len(texts), 3)
        self.assertEqual(self.result(cv, "d")["assets"] and len(self.result(cv, "d")["assets"]), 1)
        self.assertIn("[0:00]", self.result(cv, "d")["text"])

    def test_each_character_has_a_designed_or_cloned_voice(self):
        ref = self.audio("joao.wav")
        maria = self.voice("vm", "Maria", voice_style="mulher jovem, voz doce")
        joao = self.voice("vj", "João", reference_text="Texto falado na referência do João.")
        nodes, edges = self.graph([maria, joao], refs={"vj": ref})
        cv = self.run_nodes(nodes, edges)
        self.assertEqual(self.errors(), {})
        calls = self.fake.calls
        maria_calls = [c for c in calls if c["text"].startswith("(mulher jovem, voz doce)")]
        joao_calls = [c for c in calls if not c["text"].startswith("(")]
        self.assertEqual(len(maria_calls) + len(joao_calls), len(calls))
        self.assertGreaterEqual(len(maria_calls), 3)                                            # as falas da Maria: voz criada pela descrição, sem referência
        self.assertTrue(all("reference_wav_path" not in c for c in maria_calls))
        self.assertTrue(joao_calls and all("café" in c["text"] or "Eu trouxe" in c["text"] or "Bom dia!" in c["text"] for c in joao_calls), [c["text"] for c in joao_calls])
        self.assertTrue(all(c["prompt_text"] == "Texto falado na referência do João." and c["ref_exists"] == [True, True] for c in joao_calls))   # o João: clonagem fiel com a referência dele
        self.assertTrue(any("Vozes usadas: Maria" in w and "João" in w for w in self.warnings("d")))
        self.assertEqual(len(self.fake.loads), 1)                                               # um modelo carregado para todos os personagens
        self.assertTrue(self.result(cv, "d")["assets"])

    def test_the_dubbed_audio_follows_the_original_length(self):
        import json
        import subprocess

        cv = self.run_nodes(*self.graph(voice_style="calma"))
        self.assertEqual(self.errors(), {})
        a = next(x for x in cv["assets"] if x["id"] == self.result(cv, "d")["assets"][0])
        path = self.cs.asset_path(self.cid, a["file"])
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True).stdout)
        self.assertAlmostEqual(float(info["format"]["duration"]), 12.0, delta=1.0)

    def test_dubbing_a_video_keeps_the_picture_and_replaces_the_sound(self):
        import json
        import subprocess

        cv = self.run_nodes(*self.graph(src_kind="video", mix="replace"))
        self.assertEqual(self.errors(), {})
        a = next(x for x in cv["assets"] if x["id"] == self.result(cv, "d")["assets"][0])
        self.assertEqual(a["kind"], "video")
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(self.cs.asset_path(self.cid, a["file"]))], capture_output=True, text=True).stdout)
        self.assertEqual(sorted(s["codec_type"] for s in info["streams"]), ["audio", "video"])

    def test_mix_modes_fit_and_alternate_assignment(self):
        for params in ({"mix": "duck", "original_volume": 0.2}, {"mix": "replace", "fit": False}, {"assign": "alternate"}):
            self.fake.calls.clear()
            media._LOCAL_CACHE.clear()
            maria, joao = self.voice("vm", "Maria", voice_style="alegre"), self.voice("vj", "João", voice_style="grave")
            cv = self.run_nodes(*self.graph([maria, joao], src_kind="video", **params))
            self.assertEqual(self.errors(), {}, params)
            self.assertTrue(self.result(cv, "d")["assets"], params)
            self.assertGreaterEqual(len(self.fake.calls), 3, params)
        order = [c["text"][:7] for c in self.fake.calls]
        self.assertEqual(order[0], "(alegre")                                                   # alternando: a primeira fala é da primeira voz…
        self.assertEqual(order[1], "(grave)")                                                   # …a segunda, da segunda

    def test_the_speed_of_the_dub_voice(self):
        cv = self.run_nodes(*self.graph(speed=1.5, fit=False))
        self.assertEqual(self.errors(), {})
        self.assertTrue(self.result(cv, "d")["assets"])

    def test_a_long_line_is_split_and_every_word_is_spoken(self):
        long_line = "Maria: " + " ".join(f"Frase número {i} do roteiro, falada pela Maria com calma." for i in range(14))
        self.run_nodes(*self.graph(script=long_line))
        self.assertEqual(self.errors(), {})
        spoken = " ".join(c["text"] for c in self.fake.calls)
        for i in range(14):
            self.assertIn(f"Frase número {i} ", spoken)

    def test_a_dub_without_the_downloaded_model_says_so(self):
        with mock.patch.object(lm, "downloaded_precision", return_value=""):
            self.run_nodes(*self.graph())
        self.assertIn("ainda não foi baixado", self.errors()["d"])

    def test_the_dub_is_cached_until_a_voice_changes(self):
        maria = self.voice("vm", "Maria", voice_style="alegre")
        nodes, edges = self.graph([maria])
        self.run_nodes(nodes, edges)
        n = len(self.fake.calls)
        self.run_nodes(nodes, edges, force=False)
        self.assertEqual(len(self.fake.calls), n)
        nodes2 = [dict(x, params=dict(x["params"], voice_style="séria")) if x["id"] == "vm" else x for x in nodes]
        self.run_nodes(nodes2, edges, force=False)
        self.assertGreater(len(self.fake.calls), n)


if __name__ == "__main__":
    unittest.main()
