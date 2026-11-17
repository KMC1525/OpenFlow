"""v0.74: compatibilidade geral dos modelos locais do OpenFlow — cada família de modelo de imagem (SD/SDXL turbo, SD3, FLUX.1 schnell/dev, FLUX Kontext, FLUX.2 dev e klein, Z-Image, Qwen-Image, Qwen-Image-Edit/Plus) e de
vídeo (LTX texto→vídeo e imagem→vídeo, Wan) é exercitada nos dois modos (gerar e editar) com um pipeline falso que tem a ASSINATURA REAL do `__call__` do diffusers 0.43 (lida no código-fonte), e o catálogo de modelos
sugeridos é conferido (tipo, passos e guidance, limite de referências).

NENHUM modelo real foi baixado ou executado (o Hugging Face está bloqueado onde isto foi desenvolvido): isto prova que os argumentos certos chegam ao pipeline certo, não que a imagem sai boa."""
import sys
import types
import unittest
from unittest import mock

from openflow.canvas import localmodels as lm
from openflow.canvas import media as M
from openflow.canvas import mesh3d, modelkind, soundmodels
from openflow.canvas import procedural as proc
from openflow.canvas.media import LocalHFMedia
from tests.test_canvas import PNG, provider
from tests.test_lowmem_v072 import flux2_call, flux_call, flux_i2i_call, kontext_call, make_pipe, qwen_call, qwen_edit_call, respond


def zimage_call(self, prompt=None, height=None, width=None, num_inference_steps=50, sigmas=None, guidance_scale=5.0, cfg_normalization=False, cfg_truncation=1.0, negative_prompt=None, num_images_per_prompt=1, generator=None):
    return respond(self, dict(prompt=prompt, height=height, width=width, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale, negative_prompt=negative_prompt))


def zimage_i2i_call(self, prompt=None, image=None, strength=0.6, height=None, width=None, num_inference_steps=50, sigmas=None, guidance_scale=5.0, negative_prompt=None, generator=None):
    return respond(self, dict(prompt=prompt, image=image, strength=strength, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale))


def sd3_call(self, prompt=None, prompt_2=None, prompt_3=None, height=None, width=None, num_inference_steps=28, sigmas=None, guidance_scale=7.0, negative_prompt=None, generator=None):
    return respond(self, dict(prompt=prompt, height=height, width=width, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale, negative_prompt=negative_prompt))


def sd3_i2i_call(self, prompt=None, height=None, width=None, image=None, strength=0.6, num_inference_steps=50, sigmas=None, guidance_scale=7.0, negative_prompt=None, generator=None):
    return respond(self, dict(prompt=prompt, image=image, strength=strength, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale, negative_prompt=negative_prompt))


def sdxl_call(self, prompt=None, prompt_2=None, height=None, width=None, num_inference_steps=50, guidance_scale=5.0, negative_prompt=None, generator=None):
    return respond(self, dict(prompt=prompt, height=height, width=width, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale, negative_prompt=negative_prompt))


def sdxl_i2i_call(self, prompt=None, prompt_2=None, image=None, strength=0.3, num_inference_steps=50, guidance_scale=5.0, negative_prompt=None, generator=None):
    return respond(self, dict(prompt=prompt, image=image, strength=strength, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale, negative_prompt=negative_prompt))


def qwen_i2i_call(self, prompt=None, negative_prompt=None, true_cfg_scale=4.0, image=None, height=None, width=None, strength=0.6, num_inference_steps=50, guidance_scale=None, generator=None):
    return respond(self, dict(prompt=prompt, image=image, strength=strength, true_cfg_scale=true_cfg_scale, num_inference_steps=num_inference_steps))


def klein_call(self, image=None, prompt=None, height=None, width=None, num_inference_steps=50, sigmas=None, guidance_scale=4.0, generator=None):
    return respond(self, dict(image=image, prompt=prompt, height=height, width=width, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale))


# modelo (nome no Hub) → (classe do pipeline carregado, classe do pipeline de imagem → imagem ou None, tipo de edição esperado: "strength" | "image" | "none")
IMAGE_FAMILIES = {
    "stabilityai/sd-turbo": ("StableDiffusionXLPipeline", sdxl_call, sdxl_i2i_call, "strength"),
    "stabilityai/sdxl-turbo": ("StableDiffusionXLPipeline", sdxl_call, sdxl_i2i_call, "strength"),
    "stabilityai/stable-diffusion-3.5-medium": ("StableDiffusion3Pipeline", sd3_call, sd3_i2i_call, "strength"),
    "black-forest-labs/FLUX.1-schnell": ("FluxPipeline", flux_call, flux_i2i_call, "strength"),
    "black-forest-labs/FLUX.1-dev": ("FluxPipeline", flux_call, flux_i2i_call, "strength"),
    "black-forest-labs/FLUX.1-Kontext-dev": ("FluxKontextPipeline", kontext_call, None, "image"),
    "black-forest-labs/FLUX.2-dev": ("Flux2Pipeline", flux2_call, None, "image"),
    "black-forest-labs/FLUX.2-klein-4B": ("Flux2KleinPipeline", klein_call, None, "image"),
    "unsloth/Z-Image-Turbo": ("ZImagePipeline", zimage_call, zimage_i2i_call, "strength"),
    "Qwen/Qwen-Image": ("QwenImagePipeline", qwen_call, qwen_i2i_call, "strength"),
    "Qwen/Qwen-Image-Edit": ("QwenImageEditPipeline", qwen_edit_call, None, "image"),
    "Qwen/Qwen-Image-Edit-2509": ("QwenImageEditPlusPipeline", qwen_edit_call, None, "image"),
}


class ImageMatrixTests(unittest.TestCase):
    def setUp(self):
        M._LOCAL_CACHE.clear()
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        torch.backends.mps = None
        torch.Generator.return_value.manual_seed.return_value = "gen"
        self.mods = {"torch": torch, "diffusers": mock.MagicMock()}

    def run_model(self, model, size="768x768", refs=(), mode="generate", **kw):
        cls_name, call, i2i_call, _ = IMAGE_FAMILIES[model]
        pipe_cls, i2i_cls = make_pipe(cls_name, call), (make_pipe(cls_name.replace("Pipeline", "Img2ImgPipeline"), i2i_call) if i2i_call else None)
        d = self.mods["diffusers"]
        d.AutoPipelineForText2Image.from_pretrained.side_effect = lambda m, **k: pipe_cls()
        if i2i_cls:
            d.AutoPipelineForImage2Image.from_pipe.side_effect = lambda pipe: i2i_cls()
        with mock.patch.dict(sys.modules, self.mods), mock.patch.object(lm, "downloaded_precision", return_value="bf16"), mock.patch.object(lm, "has_fp16_variant", return_value=False):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": model}, key="", needs_key=False)
            p.edit_mode = mode == "edit"
            p.ctl = types.SimpleNamespace(note=lambda m: None, check=lambda: None)
            out = p.image("um gato de capa", size=size, refs=list(refs), **kw)
        seen = (i2i_cls or pipe_cls).seen if refs and i2i_cls else pipe_cls.seen
        return out, seen["kw"], p

    def test_every_family_generates_with_its_own_defaults(self):
        for model in IMAGE_FAMILIES:
            out, kw, _ = self.run_model(model)
            steps, guidance = LocalHFMedia._defaults(model)
            self.assertEqual(out[0].mime, "image/png", model)
            self.assertEqual(kw["num_inference_steps"], steps, model)
            if "guidance_scale" in kw and kw["guidance_scale"] is not None:
                self.assertEqual(kw["guidance_scale"], guidance, model)
            self.assertEqual((kw["width"], kw["height"]), (768, 768), model)                    # CPU: o lado maior vai a 768
            self.assertEqual(kw["width"] % 16, 0, model)

    def test_every_family_edits_with_one_reference_the_way_its_pipeline_takes_it(self):
        ref = [(proc.image("r", "96x64", 1), "image/png")]
        for model, (_c, _call, _i2i, how) in IMAGE_FAMILIES.items():
            out, kw, _ = self.run_model(model, size="512x512", refs=ref, mode="edit")
            self.assertEqual(out[0].mime, "image/png", model)
            self.assertIsNotNone(kw.get("image"), model)
            if how == "strength":
                self.assertIn("strength", kw, model)
                self.assertTrue(0 < kw["strength"] < 1, model)
            else:
                self.assertNotIn("strength", kw, model)                                           # edita direto, sem strength (o bug da v0.72)

    def test_edit_with_awkward_reference_images_keeps_sizes_valid(self):
        from PIL import Image
        import io

        def enc(im, fmt="PNG"):
            b = io.BytesIO()
            im.save(b, fmt)
            return (b.getvalue(), "image/" + fmt.lower())
        refs = {"1x1": enc(Image.new("RGB", (1, 1))), "tira": enc(Image.new("RGB", (4000, 12))), "torre": enc(Image.new("RGB", (12, 4000))), "cmyk": enc(Image.new("CMYK", (80, 60)), "JPEG"),
                "rgba": enc(Image.new("RGBA", (80, 60), (255, 0, 0, 0)))}
        for model in ("black-forest-labs/FLUX.1-Kontext-dev", "Qwen/Qwen-Image-Edit", "black-forest-labs/FLUX.2-klein-4B", "stabilityai/sdxl-turbo", "black-forest-labs/FLUX.1-dev"):
            for name, ref in refs.items():
                out, kw, _ = self.run_model(model, size="1024x1024", refs=[ref], mode="edit")
                self.assertEqual(out[0].mime, "image/png", f"{model} {name}")
                w, h = (kw.get("width"), kw.get("height")) if kw.get("width") else kw["image"].size if not isinstance(kw["image"], list) else kw["image"][0].size
                self.assertTrue(w >= 256 and h >= 256 and w % 8 == 0 and h % 8 == 0, f"{model} {name}: {w}x{h}")
                self.assertLessEqual(max(w, h), 1024, f"{model} {name}: {w}x{h}")

    def test_generate_with_a_reference_on_models_that_need_edit_mode_still_works(self):
        ref = [(proc.image("r", "64x64", 1), "image/png")]
        for model in ("black-forest-labs/FLUX.1-dev", "unsloth/Z-Image-Turbo", "Qwen/Qwen-Image-Edit"):
            out, kw, _ = self.run_model(model, size="512x512", refs=ref, mode="generate")
            self.assertEqual(out[0].mime, "image/png", model)

    def test_multi_reference_models_get_all_their_images(self):
        refs = [(proc.image(f"r{i}", "64x64", i + 1), "image/png") for i in range(6)]
        want = {"black-forest-labs/FLUX.2-klein-4B": 4, "black-forest-labs/FLUX.2-dev": 6, "Qwen/Qwen-Image-Edit-2509": 3}
        for model, n in want.items():
            _, kw, p = self.run_model(model, size="512x512", refs=refs, mode="edit")
            self.assertEqual(len(kw["image"]), n, model)
            self.assertEqual(p.max_refs(model), {"black-forest-labs/FLUX.2-dev": 10}.get(model, n), model)
        for model in ("black-forest-labs/FLUX.1-Kontext-dev", "Qwen/Qwen-Image-Edit", "black-forest-labs/FLUX.1-dev", "stabilityai/sdxl-turbo"):
            _, kw, p = self.run_model(model, size="512x512", refs=refs, mode="edit")
            self.assertEqual(p.max_refs(model), 1, model)
            self.assertFalse(isinstance(kw["image"], list), model)

    def test_negative_prompt_only_where_it_makes_sense(self):
        takes = {"stabilityai/stable-diffusion-3.5-medium", "Qwen/Qwen-Image", "Qwen/Qwen-Image-Edit", "Qwen/Qwen-Image-Edit-2509"}   # usam CFG de verdade
        for model in IMAGE_FAMILIES:
            _, kw, _ = self.run_model(model, size="512x512", negative="feio")
            self.assertEqual(kw.get("negative_prompt") == "feio", model in takes, model)       # destilados (guidance 0) e os pipelines do FLUX não têm prompt negativo

    def test_aspect_ratio_survives_on_the_cpu(self):
        for model in ("black-forest-labs/FLUX.1-schnell", "Qwen/Qwen-Image", "unsloth/Z-Image-Turbo"):
            _, kw, _ = self.run_model(model, size="1344x768")
            self.assertEqual((kw["width"], kw["height"]), (768, 432), model)
            _, kw, _ = self.run_model(model, size="576x1024")
            self.assertEqual((kw["width"], kw["height"]), (432, 768), model)

    def test_count_and_seed_reach_every_family(self):
        for model in IMAGE_FAMILIES:
            out, _, _ = self.run_model(model, size="512x512", count=2, seed=7)
            self.assertEqual(len(out), 2, model)


class DefaultsTableTests(unittest.TestCase):
    def test_known_defaults(self):
        d = LocalHFMedia._defaults
        self.assertEqual(d("black-forest-labs/FLUX.1-schnell"), (4, 0.0))
        self.assertEqual(d("black-forest-labs/FLUX.1-dev"), (28, 3.5))
        self.assertEqual(d("black-forest-labs/FLUX.1-Kontext-dev"), (28, 3.5))
        self.assertEqual(d("black-forest-labs/FLUX.2-klein-4B"), (4, 1.0))
        self.assertEqual(d("black-forest-labs/FLUX.2-klein-base-4B"), (50, 4.0))
        self.assertEqual(d("black-forest-labs/flux-3-image-klein"), (16, 0.0))
        self.assertEqual(d("unsloth/Z-Image-Turbo"), (9, 0.0))                                   # antes: 2 passos (a regra «turbo» genérica) → imagem borrada
        self.assertEqual(d("Tongyi-MAI/Z-Image"), (28, 4.0))
        self.assertEqual(d("stabilityai/stable-diffusion-3.5-large"), (28, 4.5))                  # antes: guidance 7 (satura)
        self.assertEqual(d("stabilityai/stable-diffusion-3.5-large-turbo"), (4, 0.0))
        self.assertEqual(d("ByteDance/SDXL-Lightning-8step"), (8, 0.0))
        self.assertEqual(d("stabilityai/sd-turbo"), (2, 0.0))
        self.assertEqual(d("stabilityai/sdxl-turbo"), (2, 0.0))
        self.assertEqual(d("Qwen/Qwen-Image"), (30, 4.0))
        self.assertEqual(d("runwayml/stable-diffusion-v1-5"), (25, 7.0))

    def test_every_suggested_image_model_has_sane_defaults(self):
        for m in M.MEDIA_PRESETS["local_hf"]["suggest"]["image"]:
            steps, guidance = LocalHFMedia._defaults(m)
            self.assertTrue(1 <= steps <= 60 and 0.0 <= guidance <= 10.0, m)


class CatalogTests(unittest.TestCase):
    def test_every_suggestion_is_of_the_kind_it_is_listed_under(self):
        sug = M.MEDIA_PRESETS["local_hf"]["suggest"]
        kinds = {"voice": "voice", "stt": "stt", "sound": "sound"}
        for cap, want in kinds.items():
            for m in sug[cap]:
                self.assertIn(modelkind.kind_of(m), (want, ""), f"{cap}: {m}")
        for cap in ("image", "video"):
            for m in sug[cap]:
                self.assertEqual(modelkind.kind_of(m), "", f"{cap}: {m} foi reconhecido como modelo de áudio")

    def test_suggestions_have_no_duplicates_and_the_default_comes_first(self):
        for cap, models in M.MEDIA_PRESETS["local_hf"]["suggest"].items():
            self.assertEqual(len(models), len(set(models)), cap)
        self.assertEqual(M.MEDIA_PRESETS["local_hf"]["suggest"]["image"][0], "stabilityai/sd-turbo")
        self.assertEqual(M.MEDIA_PRESETS["local_hf"]["suggest"]["sound"][0], "facebook/musicgen-small")

    def test_sound_and_3d_suggestions_are_families_the_code_knows(self):
        sug = M.MEDIA_PRESETS["local_hf"]["suggest"]
        for m in sug["sound"]:
            self.assertTrue(soundmodels.family(m) or "musicgen" in m.lower(), m)
        for m in sug["model3d"]:
            self.assertTrue(mesh3d.family(m), m)

    def test_voice_suggestions_route_to_a_real_path(self):
        from openflow.canvas import voxcpm

        lp = LocalHFMedia({"id": "local_hf"})
        for m in M.MEDIA_PRESETS["local_hf"]["suggest"]["voice"]:
            routed = "voxcpm" if voxcpm.is_voxcpm(m) else "orpheus" if "orpheus" in m.lower() else "csm" if "csm-1b" in m.lower() else "pipeline"
            self.assertTrue(routed, m)
            lp._expect("voice", m)                                                              # nenhum é recusado como modelo de outro tipo

    def test_the_model_kind_guard_never_blocks_a_suggested_model_under_its_own_capability(self):
        lp = LocalHFMedia({"id": "local_hf"})
        for cap, models in M.MEDIA_PRESETS["local_hf"]["suggest"].items():
            if cap in ("voice", "stt", "sound"):
                for m in models:
                    lp._expect(cap, m)


class GgufFamiliesTests(unittest.TestCase):
    """As famílias de GGUF (stable-diffusion.cpp): a tabela de `support.FAMILIES` precisa ser coerente — um erro nela só aparece quando alguém tenta usar aquele modelo."""

    def test_the_table_is_coherent(self):
        import re

        from openflow.canvas import sdcli, support

        ids = [f["id"] for f in support.FAMILIES]
        self.assertEqual(len(ids), len(set(ids)))
        for f in support.FAMILIES:
            re.compile(f["name"])
            self.assertTrue(f["label"] and f["need"], f["id"])
            for pattern in f.get("load", {}).values():
                re.compile(pattern)
            for key in f.get("run", {}):
                self.assertIn(key, sdcli.RUN_FLAGS, f"{f['id']}: {key}")
            for v in f.get("variants", []):
                re.compile(v["match"])
                for key in v["run"]:
                    self.assertIn(key, sdcli.RUN_FLAGS, f"{f['id']} variante: {key}")
            self.assertTrue(set(f.get("downloads", {})) <= set(f.get("load", {})), f["id"])            # só se baixa o que o modelo sabe carregar
            self.assertTrue(set(f.get("optional", [])) <= set(f.get("load", {})), f["id"])
            self.assertTrue(set(f.get("edit_needs", [])) <= set(f.get("load", {})), f["id"])
            steps = f.get("run", {}).get("sample_steps", 20)
            self.assertTrue(1 <= steps <= 100, f["id"])

    def test_typical_file_names_find_their_family(self):
        from openflow.canvas import support

        for name, label in (("z_image_turbo-Q4_K_M.gguf", "Z-Image"), ("flux1-dev-Q4_K_S.gguf", "FLUX"), ("flux2-klein-4b-Q4_K_M.gguf", "FLUX.2 klein (4B)"), ("flux-2-klein-9B-Q4_0.gguf", "FLUX.2 klein (9B)"),
                            ("qwen-image-Q4_K_M.gguf", "Qwen-Image"), ("Qwen-Image-Edit-2509-Q4_K_M.gguf", "Qwen-Image-Edit"), ("qwen-image-2.1-Q4_K_M.gguf", "Qwen-Image 2.1"), ("wan2.1_t2v_1.3B-Q4.gguf", "Wan2.1 T2V")):
            fam = support.family_of(name)
            self.assertEqual((fam or {}).get("label"), label, name)
        self.assertIsNone(support.family_of("modelo-desconhecido.gguf"))

    def test_the_turbo_variants_use_few_steps_and_no_cfg(self):
        from openflow.canvas import support

        for name in ("z_image_turbo-Q4_K_M.gguf", "Z-Image-Turbo-Q8_0.gguf"):
            run = support.run_for(support.family_of(name), name)
            self.assertEqual((run["sample_steps"], run["cfg_scale"]), (8, 1.0), name)
        base = support.run_for(support.family_of("z_image-Q4_K_M.gguf"), "z_image-Q4_K_M.gguf")
        self.assertEqual((base["sample_steps"], base["cfg_scale"]), (30, 4.0))


class VideoMatrixTests(unittest.TestCase):
    def run_video(self, cls_name, call, image=None, i2v=None):
        M._LOCAL_CACHE.clear()
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        torch.backends.mps = None
        d = mock.MagicMock()
        base = make_pipe(cls_name, call)
        d.DiffusionPipeline.from_pretrained.side_effect = lambda m, **k: base()
        if i2v:
            d.LTXImageToVideoPipeline.from_pipe.side_effect = lambda pipe: i2v()
        with mock.patch.dict(sys.modules, {"torch": torch, "diffusers": d}), mock.patch.object(lm, "downloaded_precision", return_value="bf16"), mock.patch.object(lm, "has_fp16_variant", return_value=False), \
                mock.patch.object(M, "_frames_to_mp4", side_effect=lambda frames, fps: M.Media(b"mp4", "video/mp4", {"fps": fps})), mock.patch.object(M.proc, "ffmpeg_path", return_value="ffmpeg"):
            p = provider("local_hf", "", {"video": "Lightricks/LTX-Video"}, key="", needs_key=False)
            p.ctl = types.SimpleNamespace(note=lambda m: None, check=lambda: None)
            return p.video("ondas", duration=2, aspect="16:9", image=image), base, i2v

    def test_ltx_text_to_video_reports_the_real_frame_rate(self):
        def ltx(self, prompt=None, negative_prompt=None, height=None, width=None, num_frames=None, frame_rate=25, num_inference_steps=50, guidance_scale=3.0, generator=None):
            return respond(self, dict(prompt=prompt, width=width, height=height, num_frames=num_frames, frame_rate=frame_rate))
        out, base, _ = self.run_video("LTXPipeline", ltx)
        kw = base.seen["kw"]
        self.assertEqual(kw["frame_rate"], 24)                                                    # o pipeline assumia 25
        self.assertEqual((kw["width"] % 32, kw["height"] % 32, (kw["num_frames"] - 1) % 8), (0, 0, 0))

    def test_ltx_image_to_video_builds_the_i2v_pipeline_from_the_same_weights(self):
        def ltx(self, prompt=None, height=None, width=None, num_frames=None, frame_rate=25):
            return respond(self, dict(prompt=prompt))

        def ltx_i2v(self, image=None, prompt=None, height=None, width=None, num_frames=None, frame_rate=25):
            return respond(self, dict(image=image, prompt=prompt, width=width, height=height))
        i2v = make_pipe("LTXImageToVideoPipeline", ltx_i2v)
        _, base, i2v_cls = self.run_video("LTXPipeline", ltx, image=(PNG, "image/png"), i2v=i2v)
        self.assertNotIn("kw", base.seen)                                                         # o pipeline de texto não rodou
        self.assertIsNotNone(i2v_cls.seen["kw"]["image"])
        self.assertEqual(i2v_cls.seen["kw"]["image"].size, (i2v_cls.seen["kw"]["width"], i2v_cls.seen["kw"]["height"]))


if __name__ == "__main__":
    unittest.main()
