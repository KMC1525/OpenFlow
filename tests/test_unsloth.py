"""Modelos da Unsloth no Canvas: Qwen-Image 2.1 (+Turbo), Z-Image (+Turbo) e Wan2.2 TI2V 5B (vídeo) pela stable-diffusion.cpp — famílias, arquivos de apoio, parâmetros e vídeo."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy  # noqa: F401,E402  (importado antes dos módulos falsos: o numpy não pode ser importado de novo depois que o sys.modules é restaurado)
from openflow.canvas import media as M  # noqa: E402
from openflow.canvas import support  # noqa: E402
from openflow.providers import ProviderError  # noqa: E402
from tests.test_canvas import PNG  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402
from tests.helpers import ServerCase  # noqa: E402


class FamilyTests(unittest.TestCase):
    def test_unsloth_files_map_to_the_right_family_and_parameters(self):
        got = {n: (support.family_of(n) or {}).get("id") for n in (
            "qwen-image-2.1-Q4_K_M.gguf", "qwen-image-2.1-turbo-Q8_0.gguf", "qwen-image-2512-Q4_K_M.gguf", "Qwen-Image-Q4_K_M.gguf", "z-image-turbo-Q4_K_M.gguf", "z-image-Q4_K_M.gguf",
            "Wan2.2-TI2V-5B-Q4_K_M.gguf", "FLUX.2-klein-4B-Q4_K_M.gguf", "flux-3-image-klein-Q4_K_M.gguf", "FLUX.1-schnell-Q4_K_S.gguf", "outro-modelo.gguf")}
        self.assertEqual(got, {"qwen-image-2.1-Q4_K_M.gguf": "qwen-image-2.1", "qwen-image-2.1-turbo-Q8_0.gguf": "qwen-image-2.1", "qwen-image-2512-Q4_K_M.gguf": "qwen-image",
                               "Qwen-Image-Q4_K_M.gguf": "qwen-image", "z-image-turbo-Q4_K_M.gguf": "z-image", "z-image-Q4_K_M.gguf": "z-image", "Wan2.2-TI2V-5B-Q4_K_M.gguf": "wan22-ti2v-5b",
                               "FLUX.2-klein-4B-Q4_K_M.gguf": "flux2-klein-4b", "flux-3-image-klein-Q4_K_M.gguf": "flux3-klein", "FLUX.1-schnell-Q4_K_S.gguf": "flux", "outro-modelo.gguf": None})
        run = lambda n: support.run_for(support.family_of(n), n)  # noqa: E731
        self.assertEqual((run("qwen-image-2.1-Q4_K_M.gguf")["cfg_scale"], run("qwen-image-2.1-Q4_K_M.gguf")["sample_steps"]), (6.0, 20))
        self.assertEqual((run("qwen-image-2.1-turbo-Q4_K_M.gguf")["cfg_scale"], run("qwen-image-2.1-turbo-Q4_K_M.gguf")["sample_steps"]), (1.0, 8))   # Turbo: 8 passos, CFG 1
        self.assertEqual((run("z-image-turbo-Q4_K_M.gguf")["cfg_scale"], run("z-image-turbo-Q4_K_M.gguf")["sample_steps"]), (1.0, 8))
        self.assertEqual((run("z-image-Q4_K_M.gguf")["cfg_scale"], run("z-image-Q4_K_M.gguf")["sample_steps"]), (4.0, 30))
        self.assertEqual(run("Wan2.2-TI2V-5B-Q4_K_M.gguf")["flow_shift"], 5.0)

    def test_flux2_dev_has_its_own_family_with_the_mistral_encoder(self):
        fam = support.family_of("flux2-dev-Q4_K_M.gguf")
        self.assertEqual(fam["id"], "flux2-dev")
        self.assertEqual(fam["downloads"]["llm_path"]["repo"], "unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF")
        self.assertEqual(support.family_of("FLUX.2-klein-9B-Q4_K_M.gguf")["id"], "flux2-klein-9b")   # as klein não mudam
        self.assertEqual(M._KINDS["gguf_local"]({"id": "g", "label": "g", "models_dir": ".", "models": {"image": "flux2-dev-Q4_K_M.gguf"}, "needs_key": False}).max_refs(), 4)

    def test_every_family_download_points_to_a_repo_and_a_file_for_each_companion(self):
        for fam in support.FAMILIES:
            self.assertEqual(set(fam["downloads"]), set(fam["load"]), fam["id"])
            for key, d in fam["downloads"].items():
                d = support.download_spec(fam, key, "Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf")   # o nome só importa para o arquivo «derivado» do modelo (HighNoise)
                self.assertRegex(d["repo"], r"^[\w.-]+/[\w.-]+$")
                self.assertTrue(d["file"] and d["approx"] > 0)

    def test_missing_lists_what_to_download_and_finds_companions_by_name(self):
        import tempfile

        d = Path(tempfile.mkdtemp())
        (d / "qwen-image-2.1-Q4_K_M.gguf").write_bytes(b"g")
        info = support.missing(d, "qwen-image-2.1-Q4_K_M.gguf")
        self.assertEqual([(m["key"], m["repo"], m["file"]) for m in info["missing"]],
                         [("vae_path", "unsloth/Qwen-Image-2.1-FP8", "vae/qwen_image_2.1_vae_bf16.safetensors"), ("llm_path", "unsloth/Qwen3-VL-8B-Instruct-GGUF", "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf")])
        (d / "qwen_image_2.1_vae_bf16.safetensors").write_bytes(b"v")
        (d / "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf").write_bytes(b"t")
        (d / "Qwen3-VL-8B-Instruct-mmproj-F16.gguf").write_bytes(b"x")   # o mmproj não é o codificador
        self.assertEqual(support.missing(d, "qwen-image-2.1-Q4_K_M.gguf")["missing"], [])
        (d / "Wan2.2-TI2V-5B-Q4_K_M.gguf").write_bytes(b"g")
        self.assertEqual([m["key"] for m in support.missing(d, "Wan2.2-TI2V-5B-Q4_K_M.gguf")["missing"]], ["vae_path", "t5xxl_path"])
        (d / "Wan2.2_VAE.safetensors").write_bytes(b"v")
        (d / "umt5-xxl-encoder-Q4_K_M.gguf").write_bytes(b"t")
        self.assertEqual(support.missing(d, "Wan2.2-TI2V-5B-Q4_K_M.gguf")["missing"], [])


class GGUFTests(TmpCase):
    def fake(self):
        loads, runs, vids = [], [], []

        class Img:
            def save(self, buf, format="PNG"):
                buf.write(PNG)

        class SD:
            def __init__(self, **kw):
                loads.append(kw)

            def generate_image(self, prompt, width, height, seed, cfg_scale=1.0, sample_steps=20, sample_method="euler", flow_shift=0.0, ref_images=None, init_image=None):
                runs.append(dict(prompt=prompt, width=width, height=height, cfg_scale=cfg_scale, sample_steps=sample_steps, ref_images=ref_images))
                return [Img()]

            def generate_video(self, prompt, width, height, seed, video_frames=1, cfg_scale=1.0, sample_steps=20, init_image=None):   # sem flow_shift: a versão «antiga» da biblioteca
                vids.append(dict(prompt=prompt, width=width, height=height, video_frames=video_frames, cfg_scale=cfg_scale, sample_steps=sample_steps, init_image=init_image))
                return ["frame"] * video_frames

        return mock.MagicMock(StableDiffusion=SD), loads, runs, vids

    def put(self, kind, *names):
        (self.tmp / kind).mkdir(exist_ok=True)
        for n in names:
            (self.tmp / kind / n).write_bytes(b"x")

    def prov(self, **models):
        M._LOCAL_CACHE.clear()
        return M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": models, "needs_key": False})

    def test_qwen_image_2_1_turbo_loads_its_vae_and_vl_encoder_and_runs_8_steps(self):
        mod, loads, runs, _ = self.fake()
        self.put("image", "qwen-image-2.1-turbo-Q4_K_M.gguf", "qwen_image_2.1_vae_bf16.safetensors", "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf")
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}):
            self.prov(image="qwen-image-2.1-turbo-Q4_K_M.gguf").image("um gato", size="1024x1024")
        d = self.tmp / "image"
        self.assertEqual((loads[0]["diffusion_model_path"], loads[0]["vae_path"], loads[0]["llm_path"]), (str(d / "qwen-image-2.1-turbo-Q4_K_M.gguf"), str(d / "qwen_image_2.1_vae_bf16.safetensors"), str(d / "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf")))
        self.assertEqual((runs[0]["cfg_scale"], runs[0]["sample_steps"]), (1.0, 8))

    def test_qwen_image_2_1_accepts_reference_images_for_editing(self):
        from PIL import Image  # noqa: F401  (só roda com Pillow; sem ele o teste é pulado)
        mod, loads, runs, _ = self.fake()
        self.put("image", "qwen-image-2.1-Q4_K_M.gguf", "qwen_image_2.1_vae_bf16.safetensors", "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf")
        p = self.prov(image="qwen-image-2.1-Q4_K_M.gguf")
        self.assertEqual(p.max_refs(), 4)
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}):
            p.image("troque o fundo", refs=[(PNG, "image/png")])
        self.assertTrue(runs[0]["ref_images"])

    def test_z_image_turbo_runs_8_steps_without_cfg(self):
        mod, loads, runs, _ = self.fake()
        self.put("image", "z-image-turbo-Q4_K_M.gguf", "ae.safetensors", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}):
            self.prov(image="z-image-turbo-Q4_K_M.gguf").image("x")
        self.assertEqual((runs[0]["cfg_scale"], runs[0]["sample_steps"]), (1.0, 8))
        self.assertTrue(loads[0]["llm_path"].endswith("Qwen3-4B-Instruct-2507-Q4_K_M.gguf"))

    def test_wan_video_uses_720p_4k_plus_1_frames_and_drops_parameters_the_library_does_not_know(self):
        mod, loads, runs, vids = self.fake()
        self.put("video", "Wan2.2-TI2V-5B-Q4_K_M.gguf", "Wan2.2_VAE.safetensors", "umt5-xxl-encoder-Q4_K_M.gguf")
        notes = []
        p = self.prov(video="Wan2.2-TI2V-5B-Q4_K_M.gguf")
        p.ctl = mock.MagicMock(note=notes.append)
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}), mock.patch.object(M, "_frames_to_mp4", return_value=M.Media(b"mp4", "video/mp4")) as mp4:
            p.video("uma raposa correndo", duration=3, aspect="16:9")
            p.video("retrato", duration=5, aspect="9:16")
        self.assertEqual((vids[0]["width"], vids[0]["height"], vids[0]["video_frames"]), (1280, 704, 73))   # 3 s × 24 fps → 4k+1
        self.assertEqual((vids[1]["width"], vids[1]["height"], vids[1]["video_frames"]), (704, 1280, 121))   # limite de 121 quadros
        self.assertEqual((vids[0]["cfg_scale"], vids[0]["sample_steps"]), (5.0, 30))
        self.assertEqual(mp4.call_args[0][1], 24)
        self.assertTrue(any("flow_shift" in n for n in notes))
        self.assertTrue(loads[0]["t5xxl_path"].endswith("umt5-xxl-encoder-Q4_K_M.gguf") and loads[0]["vae_path"].endswith("Wan2.2_VAE.safetensors"))

    def test_wan_video_without_companions_explains_and_offers_the_download(self):
        mod, *_ = self.fake()
        self.put("video", "Wan2.2-TI2V-5B-Q4_K_M.gguf")
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}):
            with self.assertRaises(ProviderError) as cm:
                self.prov(video="Wan2.2-TI2V-5B-Q4_K_M.gguf").video("x")
        self.assertIn("[[flow-support:Wan2.2-TI2V-5B-Q4_K_M.gguf]]", str(cm.exception))
        self.assertIn("UMT5", str(cm.exception))

    def test_other_video_gguf_keeps_the_old_behavior(self):
        mod, loads, runs, vids = self.fake()
        self.put("video", "qualquer-Q4_0.gguf")
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}), mock.patch.object(M, "_frames_to_mp4", return_value=M.Media(b"mp4", "video/mp4")) as mp4:
            self.prov(video="qualquer-Q4_0.gguf").video("x", aspect="16:9")
        self.assertEqual(loads[0], {"model_path": str(self.tmp / "video" / "qualquer-Q4_0.gguf")})
        self.assertEqual(mp4.call_args[0][1], 16)
        self.assertNotIn("video_frames", {k for k, v in vids[0].items() if v is None})


class VoiceTests(TmpCase):
    """Orpheus e CSM da Unsloth: a decodificação dos tokens (pura) e o caminho da voz com módulos simulados."""

    def test_orpheus_tokens_become_snac_layers(self):
        base = M._ORPHEUS_AUDIO_BASE
        raw = [128259, 1, 2, 128257] + [base + 10, base + 4096 + 11, base + 8192 + 12, base + 12288 + 13, base + 16384 + 14, base + 20480 + 15, base + 24576 + 16] + [base + 99, base + 98] + [128258]
        codes = M.orpheus_codes(raw)
        self.assertEqual(len(codes), 7)   # só grupos completos de 7; o fim de fala sai; o texto antes do início de fala é ignorado
        l1, l2, l3 = M.orpheus_layers(codes)
        self.assertEqual((l1, l2, l3), ([10], [11, 14], [12, 13, 15, 16]))
        l1, l2, l3 = M.orpheus_layers(M.orpheus_codes([128257] + [base] * 14))
        self.assertEqual((len(l1), len(l2), len(l3)), (2, 4, 8))   # 1 : 2 : 4
        self.assertEqual(M.orpheus_codes([1, 2, 3]), [])

    def prov(self):
        M._LOCAL_CACHE.clear()
        return M._KINDS["local_hf"]({"id": "local_hf", "label": "l", "models_dir": str(self.tmp), "models": {}, "needs_key": False})

    def fake_stack(self, tokens):
        calls = {}

        class Out:
            def __getitem__(self, i):
                return mock.MagicMock(tolist=lambda: tokens)

        class LM:
            def to(self, d):
                return self

            def generate(self, **kw):
                calls["generate"] = kw
                return Out()

        class Audio:
            def detach(self):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return [[0.1, -0.1] * 50]

        class Codec:
            def eval(self):
                return self

            def to(self, d):
                return self

            def decode(self, layers):
                calls["layers"] = len(layers)
                return Audio()

        tf = mock.MagicMock()
        tf.AutoTokenizer.from_pretrained.return_value = mock.MagicMock(return_value=mock.MagicMock(input_ids=mock.MagicMock()))
        tf.AutoModelForCausalLM.from_pretrained.return_value = LM()
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        torch.tensor.side_effect = lambda v, **kw: mock.MagicMock(unsqueeze=lambda d: ("layer", len(v)))
        snac = mock.MagicMock()
        snac.SNAC.from_pretrained.return_value = Codec()
        return tf, torch, snac, calls

    def test_orpheus_voice_uses_the_named_voice_and_the_snac_codec(self):
        base = M._ORPHEUS_AUDIO_BASE
        tf, torch, snac, calls = self.fake_stack([128257] + [base + i for i in range(14)])
        p = self.prov()
        with mock.patch.dict(sys.modules, {"transformers": tf, "torch": torch, "snac": snac}), \
                mock.patch("openflow.canvas.localmodels.downloaded_precision", return_value="fp16"), mock.patch("openflow.canvas.localmodels.torch_dtype", return_value="fp16"), \
                mock.patch("openflow.canvas.localmodels.has_fp16_variant", return_value=False):
            out = p.voice("Olá, mundo", voice="leo", model="unsloth/orpheus-3b-0.1-ft")
        self.assertEqual(out.mime, "audio/wav")
        self.assertEqual(out.data[:4], b"RIFF")
        self.assertEqual(calls["layers"], 3)
        self.assertEqual(calls["generate"]["eos_token_id"], 128258)
        self.assertEqual(tf.AutoTokenizer.from_pretrained.call_args[0][0], "unsloth/orpheus-3b-0.1-ft")
        self.assertEqual(tf.AutoTokenizer.from_pretrained.return_value.call_args[0][0], "leo: Olá, mundo")
        self.assertEqual(tf.AutoTokenizer.from_pretrained.call_args[1], {"local_files_only": True})   # nada é baixado em silêncio

    def test_orpheus_explains_a_missing_codec_or_library(self):
        tf, torch, snac, _ = self.fake_stack([])
        with mock.patch.dict(sys.modules, {"transformers": tf, "torch": torch, "snac": snac}), mock.patch("openflow.canvas.localmodels.downloaded_precision", side_effect=lambda m: "fp16" if "orpheus" in m else ""), \
                mock.patch("openflow.canvas.localmodels.torch_dtype", return_value="fp16"), mock.patch("openflow.canvas.localmodels.has_fp16_variant", return_value=False):
            with self.assertRaises(ProviderError) as cm:
                self.prov().voice("x", model="unsloth/orpheus-3b-0.1-ft")
        self.assertIn("snac_24khz", str(cm.exception))
        with mock.patch.dict(sys.modules, {"transformers": tf, "torch": torch, "snac": None}):
            with self.assertRaises(ProviderError) as cm:
                self.prov().voice("x", model="unsloth/orpheus-3b-0.1-ft")
        self.assertIn("pip install snac", str(cm.exception))

    def test_csm_voice_builds_a_chat_turn_for_the_speaker(self):
        calls = {}

        class Audio:
            def to(self, d):
                return self

            def cpu(self):
                return self

            def numpy(self):
                return [0.2, -0.2] * 50

        class LM:
            def to(self, d):
                return self

            def generate(self, **kw):
                calls["generate"] = kw
                return [Audio()]

        proc = mock.MagicMock()
        proc.apply_chat_template.return_value.to.return_value = {"input_ids": 1}
        tf = mock.MagicMock()
        tf.AutoProcessor.from_pretrained.return_value = proc
        tf.CsmForConditionalGeneration.from_pretrained.return_value = LM()
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        with mock.patch.dict(sys.modules, {"transformers": tf, "torch": torch}), mock.patch("openflow.canvas.localmodels.downloaded_precision", return_value="fp16"), \
                mock.patch("openflow.canvas.localmodels.torch_dtype", return_value="fp16"), mock.patch("openflow.canvas.localmodels.has_fp16_variant", return_value=False):
            out = self.prov().voice("Hello there", voice="1", model="unsloth/csm-1b")
        self.assertEqual(out.data[:4], b"RIFF")
        self.assertEqual(proc.apply_chat_template.call_args[0][0], [{"role": "1", "content": [{"type": "text", "text": "Hello there"}]}])
        self.assertTrue(calls["generate"]["output_audio"])

    def test_suggestions_include_the_unsloth_voice_and_whisper_models(self):
        sug = M.MEDIA_PRESETS["local_hf"]["suggest"]
        self.assertIn("unsloth/orpheus-3b-0.1-ft", sug["voice"])
        self.assertIn("unsloth/csm-1b", sug["voice"])
        self.assertIn("unsloth/whisper-large-v3-turbo", sug["stt"])


class ApiTests(ServerCase):
    def test_support_download_for_video_looks_in_the_video_folder(self):
        d = self.store.models_dir / "video"
        d.mkdir(parents=True, exist_ok=True)
        for n in ("Wan2.2-TI2V-5B-Q4_K_M.gguf", "Wan2.2_VAE.safetensors", "umt5-xxl-encoder-Q4_K_M.gguf"):
            (d / n).write_bytes(b"x")
        status, r = self.c.json("POST", "/api/media/support/download", {"model": "Wan2.2-TI2V-5B-Q4_K_M.gguf", "cap": "video"})
        self.assertEqual(status, 400)
        self.assertIn("já estão na pasta", str(r))
        status, r = self.c.json("POST", "/api/media/support/download", {"model": "Wan2.2-TI2V-5B-Q4_K_M.gguf"})   # sem «cap»: procura em image/ e não acha os apoios
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
