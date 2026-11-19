"""v0.72: modelos locais de imagem (FLUX, Qwen-Image e outros) em computadores fracos.

Cada pipeline falso tem a ASSINATURA REAL do `__call__` do diffusers 0.43 (lida no código-fonte: o Qwen-Image-Edit, o FLUX Kontext e o FLUX.2 editam com `image` e não têm `strength`; o Qwen-Image usa `true_cfg_scale`),
e o torch/diffusers são simulados. NENHUM modelo real foi baixado ou executado: que o FLUX ou o Qwen-Image gerem de fato em um computador fraco, e o quanto de memória usam, não foi verificado."""
import sys
import types
import unittest
from unittest import mock

from openflow.canvas import localmodels as lm
from openflow.canvas import lowmem
from openflow.canvas import media as M
from openflow.canvas import procedural as proc
from openflow.canvas.media import LocalHFMedia
from openflow.providers import ProviderError
from tests.test_canvas import PNG, provider


class T:   # um «torch» mínimo para os tipos numéricos
    float16, bfloat16, float32 = "fp16", "bf16", "fp32"


class OutOfMemoryError(RuntimeError):
    pass


class DtypeTests(unittest.TestCase):
    def test_cpu_never_gets_fp16(self):
        self.assertEqual(lowmem.device_dtype("stabilityai/sd-turbo", T.float16, "cpu", T), T.float32)
        self.assertEqual(lowmem.device_dtype("openai/whisper-small", T.float16, "cpu", T), T.float32)
        self.assertEqual(lowmem.device_dtype("black-forest-labs/FLUX.1-dev", T.float16, "cpu", T), T.bfloat16)    # grande: float32 dobraria a RAM
        self.assertEqual(lowmem.device_dtype("Qwen/Qwen-Image", T.float16, "cpu", T), T.bfloat16)
        self.assertEqual(lowmem.device_dtype("Lightricks/LTX-Video", T.float16, "cpu", T), T.bfloat16)
        self.assertEqual(lowmem.device_dtype("x/y", T.bfloat16, "cpu", T), T.bfloat16)
        self.assertEqual(lowmem.device_dtype("x/y", T.float32, "cpu", T), T.float32)

    def test_flux_and_qwen_image_use_bf16_on_the_gpu(self):
        for m in ("black-forest-labs/FLUX.1-schnell", "Qwen/Qwen-Image-Edit", "Tongyi-MAI/Z-Image-Turbo", "black-forest-labs/FLUX.2-klein-4B", "lodestones/Chroma"):
            self.assertEqual(lowmem.device_dtype(m, T.float16, "cuda", T), T.bfloat16, m)
        self.assertEqual(lowmem.device_dtype("stabilityai/sdxl-turbo", T.float16, "cuda", T), T.float16)           # SDXL aguenta fp16
        self.assertEqual(lowmem.device_dtype("stabilityai/stable-diffusion-3.5-medium", T.float16, "cuda", T), T.float16)

    def test_a_missing_torch_keeps_the_type(self):
        self.assertEqual(lowmem.device_dtype("a/b", "x", "cpu", None), "x")


class OomTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(lowmem.oom_kind(OutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")), "gpu")
        self.assertEqual(lowmem.oom_kind(RuntimeError("MPS backend out of memory (MPS allocated: 8 GB)")), "gpu")
        self.assertEqual(lowmem.oom_kind(MemoryError()), "ram")
        self.assertEqual(lowmem.oom_kind(RuntimeError("[enforce fail at alloc_cpu.cpp] DefaultCPUAllocator: can't allocate memory: you tried to allocate 5368709120 bytes")), "ram")
        self.assertEqual(lowmem.oom_kind(OSError("[WinError 1455] O arquivo de paginação é muito pequeno para concluir a operação")), "ram")
        self.assertEqual(lowmem.oom_kind(ValueError("tamanho inválido")), "")

    def test_shrink(self):
        self.assertEqual(lowmem.shrink(1024, 1024), (768, 768))
        self.assertEqual(lowmem.shrink(1024, 576), (768, 432))
        self.assertIsNone(lowmem.shrink(384, 384))
        self.assertEqual(lowmem.shrink(512, 512), (384, 384))

    def test_messages_point_at_what_to_do(self):
        gpu, ram = lowmem.friendly_oom("gpu", "m", 512, 512, 2), lowmem.friendly_oom("ram", "m", 512, 512, 0)
        self.assertIn("placa de vídeo", gpu)
        self.assertIn("depois de reduzir o tamanho 2x", gpu)
        self.assertIn("GGUF", gpu)
        self.assertIn("arquivo de paginação", ram)


class SignatureTests(unittest.TestCase):
    def test_real_signatures(self):
        class QwenEdit:
            def __call__(self, image=None, prompt=None, negative_prompt=None, true_cfg_scale=4.0, height=None, width=None, num_inference_steps=50, guidance_scale=None, generator=None): ...

        class Img2Img:
            def __call__(self, prompt=None, image=None, strength=0.6, num_inference_steps=28, guidance_scale=7.0): ...

        class Plain:
            def __call__(self, prompt=None, width=None, height=None): ...

        class Anything:
            def __call__(self, **kw): ...
        self.assertTrue(lowmem.edit_style(lowmem.params_of(QwenEdit())))
        self.assertFalse(lowmem.edit_style(lowmem.params_of(Img2Img())))                 # tem `strength`: é imagem → imagem
        self.assertFalse(lowmem.edit_style(lowmem.params_of(Plain())))
        self.assertIsNone(lowmem.params_of(Anything()))                                  # **kwargs: aceita tudo, nada é filtrado
        self.assertFalse(lowmem.edit_style(None))
        self.assertEqual(lowmem.keep({"a": 1, "strength": 2}, {"a"}), {"a": 1})
        self.assertEqual(lowmem.keep({"a": 1, "strength": 2}, None), {"a": 1, "strength": 2})
        self.assertTrue(lowmem.multi_image("QwenImageEditPlusPipeline"))
        self.assertTrue(lowmem.multi_image("Flux2Pipeline"))
        self.assertFalse(lowmem.multi_image("QwenImageEditPipeline"))
        self.assertFalse(lowmem.multi_image("FluxKontextPipeline"))


def make_pipe(name, signature_call):
    """Um pipeline de mentira cuja classe tem o nome e a assinatura do pipeline do diffusers."""
    seen: dict = {}

    def init(self):
        self.moves = []

    def to(self, dev):
        self.moves.append(dev)
        return self

    ns = {"__init__": init, "to": to, "seen": seen, "__call__": signature_call}
    return type(name, (), ns)


def respond(self, kw):
    self.seen["kw"] = kw
    self.seen.setdefault("calls", []).append(kw)

    class Img:
        def save(self, buf, format="PNG"):
            buf.write(PNG)
    return mock.Mock(images=[Img()], frames=[["f"]])


def qwen_call(self, prompt=None, negative_prompt=None, true_cfg_scale=4.0, height=None, width=None, num_inference_steps=50, sigmas=None, guidance_scale=None, generator=None, max_sequence_length=512):
    return respond(self, dict(prompt=prompt, negative_prompt=negative_prompt, true_cfg_scale=true_cfg_scale, height=height, width=width, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale))


def qwen_edit_call(self, image=None, prompt=None, negative_prompt=None, true_cfg_scale=4.0, height=None, width=None, num_inference_steps=50, sigmas=None, guidance_scale=None, generator=None):
    return respond(self, dict(image=image, prompt=prompt, negative_prompt=negative_prompt, true_cfg_scale=true_cfg_scale, height=height, width=width, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale))


def kontext_call(self, image=None, prompt=None, negative_prompt=None, true_cfg_scale=1.0, height=None, width=None, num_inference_steps=28, sigmas=None, guidance_scale=3.5, generator=None):
    return respond(self, dict(image=image, prompt=prompt, height=height, width=width, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale))


def flux2_call(self, image=None, prompt=None, height=None, width=None, num_inference_steps=50, sigmas=None, guidance_scale=4.0, generator=None):
    return respond(self, dict(image=image, prompt=prompt, height=height, width=width, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale))


def flux_call(self, prompt=None, prompt_2=None, negative_prompt=None, true_cfg_scale=1.0, height=None, width=None, num_inference_steps=28, sigmas=None, guidance_scale=3.5, generator=None):
    return respond(self, dict(prompt=prompt, height=height, width=width, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale))


def flux_i2i_call(self, prompt=None, image=None, strength=0.6, height=None, width=None, num_inference_steps=28, guidance_scale=7.0, generator=None):
    return respond(self, dict(prompt=prompt, image=image, strength=strength, num_inference_steps=num_inference_steps, guidance_scale=guidance_scale))


class ImageTests(unittest.TestCase):
    def setUp(self):
        M._LOCAL_CACHE.clear()
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        torch.backends.mps = None
        torch.Generator.return_value.manual_seed.return_value = "gen"
        self.mods = {"torch": torch, "diffusers": mock.MagicMock()}
        self.notes = []

    def run_model(self, model, pipe_cls, size="1024x1024", refs=(), edit=False, precision="bf16", i2i_cls=None, **kw):
        d = self.mods["diffusers"]
        d.AutoPipelineForText2Image.from_pretrained.side_effect = lambda m, **k: pipe_cls()
        if i2i_cls:
            d.AutoPipelineForImage2Image.from_pipe.side_effect = lambda pipe: i2i_cls()
        with mock.patch.dict(sys.modules, self.mods), mock.patch.object(lm, "downloaded_precision", return_value=precision), mock.patch.object(lm, "has_fp16_variant", return_value=False):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": model}, key="", needs_key=False)
            p.edit_mode = edit
            p.ctl = types.SimpleNamespace(note=self.notes.append, check=lambda: None)
            return p, p.image("um gato", size=size, refs=list(refs), **kw)

    def test_qwen_image_uses_true_cfg_with_a_negative_prompt(self):
        pipe = make_pipe("QwenImagePipeline", qwen_call)
        self.run_model("Qwen/Qwen-Image", pipe)
        kw = pipe.seen["kw"]
        self.assertEqual((kw["true_cfg_scale"], kw["num_inference_steps"]), (4.0, 30))
        self.assertIsNone(kw["guidance_scale"])                 # o Qwen-Image não usa guidance_scale (era mandado 7.0 e ignorado com aviso)
        self.assertEqual(kw["negative_prompt"], " ")            # sem prompt negativo o diffusers desliga o CFG
        self.assertEqual((kw["width"], kw["height"]), (768, 768))   # CPU: o lado maior vai a 768

    def test_qwen_image_lightning_is_distilled(self):
        self.assertEqual(LocalHFMedia._defaults("lightx2v/Qwen-Image-Lightning-8steps"), (8, 1.0))
        self.assertEqual(LocalHFMedia._defaults("lightx2v/Qwen-Image-Lightning-4steps"), (4, 1.0))
        self.assertEqual(LocalHFMedia._defaults("Qwen/Qwen-Image-Edit"), (30, 4.0))
        pipe = make_pipe("QwenImagePipeline", qwen_call)
        self.run_model("lightx2v/Qwen-Image-Lightning-4steps", pipe)
        kw = pipe.seen["kw"]
        self.assertEqual((kw["true_cfg_scale"], kw["num_inference_steps"], kw["negative_prompt"]), (1.0, 4, None))

    def test_qwen_image_edit_does_not_get_strength(self):
        pipe = make_pipe("QwenImageEditPipeline", qwen_edit_call)
        p, _ = self.run_model("Qwen/Qwen-Image-Edit", pipe, size="512x512", refs=[(proc.image("a", "96x64", 1), "image/png")], edit=True)
        kw = pipe.seen["kw"]
        self.assertNotIn("strength", kw)
        self.assertIsNotNone(kw["image"])
        self.assertFalse(isinstance(kw["image"], list))          # o pipeline de edição simples recebe uma imagem
        self.assertEqual(kw["true_cfg_scale"], 4.0)
        self.mods["diffusers"].AutoPipelineForImage2Image.from_pipe.assert_not_called()          # antes, o from_pipe quebrava com este pipeline

    def test_qwen_image_edit_plus_gets_several_images(self):
        pipe = make_pipe("QwenImageEditPlusPipeline", qwen_edit_call)
        refs = [(proc.image(f"r{i}", "64x64", i + 1), "image/png") for i in range(3)]
        self.run_model("Qwen/Qwen-Image-Edit-2509", pipe, size="512x512", refs=refs, edit=False)
        self.assertEqual(len(pipe.seen["kw"]["image"]), 3)

    def test_a_single_image_editor_uses_one_reference_and_multi_image_models_say_how_many(self):
        p = LocalHFMedia({"id": "local_hf"})
        self.assertEqual(p.max_refs("Qwen/Qwen-Image-Edit"), 1)
        self.assertEqual(p.max_refs("Qwen/Qwen-Image-Edit-2509"), 3)
        self.assertEqual(p.max_refs("Qwen/Qwen-Image-Edit-Plus"), 3)
        self.assertEqual(p.max_refs("black-forest-labs/FLUX.2-dev"), 10)
        self.assertEqual(p.max_refs("black-forest-labs/FLUX.2-klein-4B"), 4)
        self.assertEqual(p.max_refs("black-forest-labs/FLUX.1-Kontext-dev"), 1)
        self.assertFalse(p.refs_need_edit("Qwen/Qwen-Image-Edit-2509"))
        pipe = make_pipe("QwenImageEditPipeline", qwen_edit_call)
        refs = [(proc.image(f"r{i}", "64x64", i + 1), "image/png") for i in range(2)]
        self.run_model("Qwen/Qwen-Image-Edit", pipe, size="512x512", refs=refs)
        self.assertFalse(isinstance(pipe.seen["kw"]["image"], list))

    def test_flux_kontext_edits_with_guidance_and_no_strength(self):
        pipe = make_pipe("FluxKontextPipeline", kontext_call)
        self.run_model("black-forest-labs/FLUX.1-Kontext-dev", pipe, size="512x512", refs=[(proc.image("a", "64x64", 1), "image/png")], edit=True)
        kw = pipe.seen["kw"]
        self.assertNotIn("strength", kw)
        self.assertEqual(kw["guidance_scale"], 3.5)
        self.assertIsNotNone(kw["image"])

    def test_flux2_dev_edits_through_its_own_pipeline(self):
        pipe = make_pipe("Flux2Pipeline", flux2_call)
        refs = [(proc.image(f"r{i}", "64x64", i + 1), "image/png") for i in range(2)]
        self.run_model("black-forest-labs/FLUX.2-dev", pipe, size="512x512", refs=refs)
        self.assertEqual(len(pipe.seen["kw"]["image"]), 2)
        self.mods["diffusers"].AutoPipelineForImage2Image.from_pipe.assert_not_called()

    def test_plain_flux_is_still_image_to_image_with_strength(self):
        pipe, i2i = make_pipe("FluxPipeline", flux_call), make_pipe("FluxImg2ImgPipeline", flux_i2i_call)
        self.run_model("black-forest-labs/FLUX.1-dev", pipe, size="512x512", refs=[(proc.image("a", "64x64", 1), "image/png")], i2i_cls=i2i)
        kw = i2i.seen["kw"]
        self.assertEqual(kw["strength"], 0.75)
        self.assertNotIn("negative_prompt", kw)

    def test_a_model_with_no_image_to_image_says_so_instead_of_a_raw_error(self):
        pipe = make_pipe("FluxPipeline", flux_call)
        self.mods["diffusers"].AutoPipelineForImage2Image.from_pipe.side_effect = ValueError("AutoPipeline can't find a pipeline linked to FluxPipeline")
        d = self.mods["diffusers"]
        d.AutoPipelineForText2Image.from_pretrained.side_effect = lambda m, **k: pipe()
        with mock.patch.dict(sys.modules, self.mods), mock.patch.object(lm, "downloaded_precision", return_value="bf16"), mock.patch.object(lm, "has_fp16_variant", return_value=False):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": "x/FLUX.1-dev"}, key="", needs_key=False)
            with self.assertRaises(ProviderError) as cm:
                p.image("oi", size="512x512", refs=[(proc.image("a", "64x64", 1), "image/png")])
        self.assertIn("não aceita uma imagem de referência", str(cm.exception))

    def test_cpu_size_keeps_the_aspect_ratio_and_multiples_of_16(self):
        pipe = make_pipe("FluxPipeline", flux_call)
        self.run_model("black-forest-labs/FLUX.1-schnell", pipe, size="1024x576")
        kw = pipe.seen["kw"]
        self.assertEqual((kw["width"], kw["height"]), (768, 432))          # antes: 768×576 (esticado)
        pipe = make_pipe("FluxPipeline", flux_call)
        self.run_model("black-forest-labs/FLUX.1-schnell", pipe, size="520x330")
        self.assertEqual((pipe.seen["kw"]["width"], pipe.seen["kw"]["height"]), (512, 320))
        self.assertTrue(all(v % 16 == 0 for v in (pipe.seen["kw"]["width"], pipe.seen["kw"]["height"])))

    def test_the_pipeline_is_loaded_in_a_safe_dtype_for_the_device(self):
        pipe = make_pipe("FluxPipeline", flux_call)
        with mock.patch.object(lowmem, "device_dtype", wraps=lowmem.device_dtype) as dd:
            self.run_model("black-forest-labs/FLUX.1-dev", pipe, size="512x512", precision="fp16")
        self.assertTrue(dd.called)
        load = self.mods["diffusers"].AutoPipelineForText2Image.from_pretrained.call_args.kwargs
        self.assertIs(load["torch_dtype"], self.mods["torch"].bfloat16)     # CPU + FLUX baixado em fp16 → bfloat16


class RetryTests(unittest.TestCase):
    def provider(self):
        p = LocalHFMedia({"id": "local_hf"})
        p.ctl = types.SimpleNamespace(note=lambda m: self.notes.append(m), check=lambda: None)
        return p

    def setUp(self):
        self.notes = []
        self.torch = mock.MagicMock()

    class Pipe:
        def __init__(self, fail_times, exc):
            self.fail_times, self.exc, self.sizes, self.calls = fail_times, exc, [], 0
            self.hooks = []

        def __call__(self, **kw):
            self.calls += 1
            self.sizes.append((kw.get("width"), kw.get("height")))
            if self.calls <= self.fail_times:
                raise self.exc
            return mock.Mock(images=["IMG"])

        def enable_vae_slicing(self):
            self.hooks.append("slicing")

        def enable_sequential_cpu_offload(self):
            self.hooks.append("sequential")

    def test_gpu_oom_first_enables_offload_then_succeeds(self):
        pipe = self.Pipe(1, OutOfMemoryError("CUDA out of memory"))
        kw = {"width": 1024, "height": 1024}
        self.assertEqual(self.provider()._generate(pipe, kw, pipe, "cuda", self.torch, "m"), "IMG")
        self.assertEqual(pipe.sizes, [(1024, 1024), (1024, 1024)])              # mesma resolução: o que mudou foi a descarga para a RAM
        self.assertEqual(pipe.hooks, ["slicing", "sequential"])
        self.assertTrue(any("descarga" in n for n in self.notes))

    def test_persistent_oom_shrinks_the_image_twice_then_explains(self):
        pipe = self.Pipe(99, OutOfMemoryError("CUDA out of memory"))
        kw = {"width": 1024, "height": 1024}
        with self.assertRaises(ProviderError) as cm:
            self.provider()._generate(pipe, kw, pipe, "cuda", self.torch, "Qwen/Qwen-Image")
        self.assertEqual(pipe.sizes, [(1024, 1024), (1024, 1024), (768, 768), (576, 576)])
        self.assertIn("Acabou a memória da placa de vídeo", str(cm.exception))
        self.assertIn("Qwen/Qwen-Image", str(cm.exception))

    def test_cpu_ram_oom_shrinks_without_touching_offload(self):
        pipe = self.Pipe(1, MemoryError())
        kw = {"width": 768, "height": 432}
        self.provider()._generate(pipe, kw, pipe, "cpu", self.torch, "m")
        self.assertEqual(pipe.sizes[-1], (576, 384))
        self.assertEqual((kw["width"], kw["height"]), (576, 384))               # o chamador fica sabendo o tamanho que coube
        self.assertEqual(pipe.hooks, [])

    def test_other_errors_are_not_swallowed(self):
        pipe = self.Pipe(5, ValueError("prompt inválido"))
        with self.assertRaises(ValueError):
            self.provider()._generate(pipe, {"width": 512, "height": 512}, pipe, "cuda", self.torch, "m")
        self.assertEqual(pipe.calls, 1)

    def test_image_to_image_shrinks_the_reference_image(self):
        from PIL import Image

        sizes = []

        class P:
            def __call__(self, **kw):
                sizes.append(kw["image"].size)
                if len(sizes) == 1:
                    raise MemoryError()
                return mock.Mock(images=["IMG"])
        kw = {"image": Image.new("RGB", (1024, 1024))}
        self.provider()._generate(P(), kw, P(), "cpu", self.torch, "m")
        self.assertEqual(sizes, [(1024, 1024), (768, 768)])

    def test_no_room_to_shrink_explains(self):
        pipe = self.Pipe(99, MemoryError())
        with self.assertRaises(ProviderError) as cm:
            self.provider()._generate(pipe, {"width": 384, "height": 384}, pipe, "cpu", self.torch, "m")
        self.assertIn("do computador (RAM)", str(cm.exception))


class LoadTests(unittest.TestCase):
    def test_running_out_of_memory_while_loading_is_explained(self):
        M._LOCAL_CACHE.clear()

        def loader():
            raise RuntimeError("[enforce fail at alloc_cpu.cpp:117] DefaultCPUAllocator: can't allocate memory: you tried to allocate 23800000000 bytes")
        with self.assertRaises(ProviderError) as cm:
            M._local_load("image", "x/flux-oom-test", loader)
        self.assertIn("Acabou a memória do computador (RAM) ao carregar «x/flux-oom-test»", str(cm.exception))
        self.assertIn("arquivo de paginação", str(cm.exception))

    def test_other_load_errors_pass_through(self):
        M._LOCAL_CACHE.clear()
        with self.assertRaises(KeyError):
            M._local_load("image", "x/other-test", lambda: (_ for _ in ()).throw(KeyError("x")))

    def test_the_final_move_to_the_gpu_falls_back_to_offload(self):
        class Pipe:
            hf_device_map = None

            def __init__(self):
                self.used = []

            def to(self, dev):
                raise OutOfMemoryError("CUDA out of memory")

            def enable_model_cpu_offload(self):
                self.used.append("model")

        pipe = Pipe()
        with mock.patch.object(M, "_PLAN", {"strategy": "gpu"}), mock.patch.object(M._perf, "device", return_value="gpu"):
            out = M._slim(pipe, "cuda")
        self.assertIs(out, pipe)
        self.assertEqual(pipe.used, ["model"])


class VideoTests(unittest.TestCase):
    def run_video(self, pipe_cls, **kw):
        M._LOCAL_CACHE.clear()
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        torch.backends.mps = None
        d = mock.MagicMock()
        d.DiffusionPipeline.from_pretrained.side_effect = lambda m, **k: pipe_cls()
        notes = []
        with mock.patch.dict(sys.modules, {"torch": torch, "diffusers": d}), mock.patch.object(lm, "downloaded_precision", return_value="bf16"), mock.patch.object(lm, "has_fp16_variant", return_value=False), \
                mock.patch.object(M, "_frames_to_mp4", side_effect=lambda frames, fps: M.Media(b"mp4", "video/mp4", {"frames": frames})), mock.patch.object(M.proc, "ffmpeg_path", return_value="ffmpeg"):
            p = provider("local_hf", "", {"video": "Lightricks/LTX-Video"}, key="", needs_key=False)
            p.ctl = types.SimpleNamespace(note=notes.append, check=lambda: None)
            return p.video("ondas", **kw), notes

    def test_a_text_only_video_model_refuses_an_image_clearly(self):
        def call(self, prompt=None, width=None, height=None, num_frames=None):
            return mock.Mock(frames=[["f"]])
        with self.assertRaises(ProviderError) as cm:
            self.run_video(make_pipe("WanPipeline", call), image=(PNG, "image/png"))
        self.assertIn("só gera vídeo a partir de texto", str(cm.exception))

    def test_video_oom_halves_the_frames_then_the_size(self):
        seen = []

        def call(self, prompt=None, width=None, height=None, num_frames=None):
            seen.append((width, height, num_frames))
            if len(seen) < 3:
                raise MemoryError()
            return mock.Mock(frames=[["f"]])
        out, notes = self.run_video(make_pipe("LTXPipeline", call), duration=5, aspect="16:9", long_side=480)
        self.assertEqual(out.mime, "video/mp4")
        self.assertEqual(seen[0][2], 121)
        self.assertEqual(seen[1][2], 57)                                  # menos quadros primeiro
        self.assertEqual(seen[2][2], 25)
        self.assertTrue(any("quadros" in n for n in notes))

    def test_video_gives_up_with_an_explanation(self):
        def call(self, prompt=None, width=None, height=None, num_frames=None):
            raise OutOfMemoryError("CUDA out of memory")
        with self.assertRaises(ProviderError) as cm:
            self.run_video(make_pipe("LTXPipeline", call), duration=2)
        self.assertIn("Acabou a memória", str(cm.exception))


class VoxcpmLibsTests(unittest.TestCase):
    def setUp(self):
        from tests.helpers import voxcpm_python_ok

        p = voxcpm_python_ok()   # a checagem do Python 3.10 vale só no test_python_39 (que a liga de novo)
        self.addCleanup(p.stop)

    def test_all_includes_voxcpm_on_python_310_plus(self):
        from openflow import cli

        with mock.patch.object(cli.sys, "version_info", (3, 11, 0)):
            self.assertIn("voxcpm", cli._wanted_libs("all")[0])
        with mock.patch.object(cli.sys, "version_info", (3, 9, 0)):
            self.assertNotIn("voxcpm", cli._wanted_libs("all")[0])
            self.assertEqual(cli._wanted_libs("voxcpm")[0], ["voxcpm"])        # pedido explicitamente, o pip diz o que acontece

    def test_the_extras_are_declared(self):
        text = (__import__("pathlib").Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('voxcpm = ["voxcpm; python_version >= \'3.10\'"]', text)
        self.assertIn("voxcpm; python_version >= '3.10'\"]", text.split("\nall = ")[1].splitlines()[0])

    def test_missing_dependency_is_told_apart_from_a_missing_library(self):
        import builtins

        real = builtins.__import__

        def fake(name, *a, **k):
            if name == "voxcpm":
                raise ImportError("No module named 'funasr'", name="funasr")
            return real(name, *a, **k)
        lp = LocalHFMedia({"id": "local_hf"})
        lp.ctl = types.SimpleNamespace(note=lambda m: None)
        imports = {"numpy": __import__("numpy"), "torch": mock.MagicMock()}
        with mock.patch.object(M, "_local_import", side_effect=lambda *n, **k: [imports[x] for x in n]), mock.patch.object(builtins, "__import__", side_effect=fake):
            with self.assertRaises(ProviderError) as cm:
                lp._voice_voxcpm("oi", "openbmb/VoxCPM2", None, "", None, "")
        self.assertIn("falta a dependência «funasr»", str(cm.exception))

    def test_python_39_gets_a_clear_message(self):
        lp = LocalHFMedia({"id": "local_hf"})
        imports = {"numpy": __import__("numpy"), "torch": mock.MagicMock()}
        with mock.patch.object(M, "_local_import", side_effect=lambda *n, **k: [imports[x] for x in n]), mock.patch.object(M, "_voxcpm_python_ok", return_value=False):
            with self.assertRaises(ProviderError) as cm:
                lp._voice_voxcpm("oi", "openbmb/VoxCPM2", None, "", None, "")
        self.assertIn("Python 3.10", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
