"""v0.86 — Bugs ao editar: o que os modelos de imagem e vídeo recebem ao editar imagens e vídeos gerados (FLUX.3, Qwen-Image-Edit 2511, LTX-2.5, MiniMax H3…).
Tudo com a stable-diffusion.cpp / diffusers SIMULADOS: prova que o OpenFlow monta o pedido certo; que o modelo real gere bem NÃO foi verificado."""
import io
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import engine as E
from openflow.canvas import ltx2
from openflow.canvas import media as M
from openflow.canvas import procedural as proc
from openflow.canvas import sdcli, support
from tests.helpers import TmpCase
from tests.test_canvas import PNG
from tests.test_gguf_matrix_v075 import FakeSD, companion_names


def png(w, h, color=(200, 30, 30)):
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, format="PNG")
    return b.getvalue()


class QwenEdit2511Tests(unittest.TestCase):
    NAME = "Qwen-Image-Edit-2511-Q4_K_M.gguf"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "image").mkdir()
        M._LOCAL_CACHE.clear()
        self.sd = FakeSD()
        p = mock.patch.dict(sys.modules, {"stable_diffusion_cpp": self.sd.module})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False)
        q.start()
        self.addCleanup(q.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def provider(self, name):
        (self.tmp / "image" / name).write_bytes(b"gguf")
        for fname in companion_names(support.family_of(name)).values():
            (self.tmp / "image" / fname).write_bytes(b"x")
        M._LOCAL_CACHE.clear()
        return M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {"image": name}, "needs_key": False})

    def test_the_2511_is_loaded_with_zero_cond_t_and_the_2509_is_not(self):
        prov = self.provider(self.NAME)
        prov.edit_mode = True
        prov.image("troque a capa", size="768x768", refs=[(proc.image("r", "96x64", 1), "image/png")], model=self.NAME)
        self.assertIs(self.sd.loads[-1].get("qwen_image_zero_cond_t"), True)
        self.sd.loads.clear()
        other = "Qwen-Image-Edit-2509-Q4_K_M.gguf"
        prov = self.provider(other)
        prov.edit_mode = True
        prov.image("troque a capa", size="768x768", refs=[(proc.image("r", "96x64", 1), "image/png")], model=other)
        self.assertNotIn("qwen_image_zero_cond_t", self.sd.loads[-1])

    def test_the_node_can_turn_it_off(self):
        prov = self.provider(self.NAME)
        prov.image("um gato", size="512x512", extra={"load": {"qwen_image_zero_cond_t": False}}, model=self.NAME)
        self.assertIs(self.sd.loads[-1].get("qwen_image_zero_cond_t"), False)

    def test_an_old_library_without_the_option_is_not_used_silently(self):
        class Old:
            def __init__(self, model_path=None, diffusion_model_path=None, vae_path=None, llm_path=None, llm_vision_path=None, **_none):
                raise AssertionError("não devia carregar")

        Old.__init__ = lambda self, model_path=None, diffusion_model_path=None, vae_path=None, llm_path=None, llm_vision_path=None, offload_params_to_cpu=False, diffusion_flash_attn=False: None
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mock.MagicMock(StableDiffusion=Old)}):
            prov = self.provider(self.NAME)
            with self.assertRaises(M.ProviderError) as cm:
                prov.image("um gato", size="512x512", model=self.NAME)
        self.assertIn("qwen_image_zero_cond_t", str(cm.exception))

    def test_the_sd_cli_gets_the_switch(self):
        fam = support.family_of(self.NAME)
        load = {"diffusion_model_path": "/m/q.gguf", **{k: "/m/" + v for k, v in companion_names(fam).items()}, "qwen_image_zero_cond_t": True}
        args, warns = sdcli.build_args(Path("/x/sd-cli"), load, {"cfg_scale": 2.5}, prompt="p", width=512, height=512, seed=1, refs=[Path("/r.png")], out=Path("/o.png"))
        self.assertIn("--qwen-image-zero-cond-t", args)
        self.assertNotIn("qwen_image_zero_cond_t", warns)
        args, _ = sdcli.build_args(Path("/x/sd-cli"), {**load, "qwen_image_zero_cond_t": False}, {}, prompt="p", width=512, height=512, seed=1, out=Path("/o.png"))
        self.assertNotIn("--qwen-image-zero-cond-t", args)


class Ltx2DistilledTests(unittest.TestCase):
    def run_generate(self, **kw):
        seen = {}

        class Pipe:
            class vocoder:
                class config:
                    output_sampling_rate = 24000

            def __call__(self, prompt=None, sigmas=None, num_inference_steps=30, **rest):
                seen.update(sigmas=sigmas, steps=num_inference_steps, **rest)

                class A:
                    def float(self):
                        return self

                    def cpu(self):
                        return self
                return [object()], [A()]

        torch = mock.MagicMock()

        def enc(video, fps, audio, audio_sample_rate, output_path):
            Path(output_path).write_bytes(b"mp4")
        with mock.patch.object(ltx2, "_imports", return_value=(torch, mock.MagicMock(), enc)):
            data = ltx2.generate(Pipe(), prompt="p", width=64, height=64, frames=9, cfg=1.0, **kw)
        self.assertEqual(data, b"mp4")
        return seen

    def test_the_distilled_schedule_is_passed_to_the_pipeline(self):
        got = self.run_generate(steps=8, sigmas=ltx2.DISTILLED_SIGMAS)
        self.assertEqual(got["sigmas"], [1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875])
        self.assertEqual(got["steps"], 8)

    def test_the_dev_model_keeps_the_default_schedule(self):
        got = self.run_generate(steps=30)
        self.assertIsNone(got["sigmas"])
        self.assertEqual(got["steps"], 30)

    def test_the_provider_uses_the_schedule_only_for_the_distilled_file(self):
        calls = []
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "video").mkdir()
        with mock.patch.object(ltx2, "components_cached", return_value=True), mock.patch.object(ltx2, "load_pipeline", return_value=object()), \
                mock.patch.object(ltx2, "generate", side_effect=lambda *a, **k: calls.append(k) or b"mp4"):
            for name in ("ltx-2.5-22b-distilled-UD-Q4_K_XL.gguf", "ltx-2.5-22b-dev-Q4_K_M.gguf"):
                (tmp / "video" / name).write_bytes(b"gguf")
                M._LOCAL_CACHE.clear()
                prov = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(tmp), "models": {"video": name}, "needs_key": False})
                prov.video("um gato", duration=2, aspect="16:9", model=name)
            prov.video("um gato", duration=2, aspect="16:9", model="ltx-2.5-22b-distilled-UD-Q4_K_XL.gguf", extra={"sample_steps": 4})
        self.assertEqual(calls[0]["sigmas"], ltx2.DISTILLED_SIGMAS)
        self.assertIsNone(calls[1]["sigmas"])
        self.assertIsNone(calls[2]["sigmas"])   # passos escolhidos pela pessoa: vale a escolha, sem a escala do distilled

    def test_the_start_image_is_cropped_not_stretched(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "video").mkdir()
        name = "ltx-2.5-22b-distilled-UD-Q4_K_XL.gguf"
        (tmp / "video" / name).write_bytes(b"gguf")
        calls = []
        with mock.patch.object(ltx2, "components_cached", return_value=True), mock.patch.object(ltx2, "load_pipeline", return_value=object()), \
                mock.patch.object(ltx2, "generate", side_effect=lambda *a, **k: calls.append(k) or b"mp4"):
            M._LOCAL_CACHE.clear()
            prov = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(tmp), "models": {"video": name}, "needs_key": False})
            prov.video("anime", duration=2, aspect="16:9", image=(png(512, 512), "image/png"), model=name)
        img = calls[0]["image"]
        self.assertEqual(img.size, (calls[0]["width"], calls[0]["height"]))


class CoverFitTests(unittest.TestCase):
    def test_cover_fit_crops_the_center_and_keeps_the_proportion(self):
        from PIL import Image

        im = Image.new("RGB", (100, 100), (0, 0, 255))
        for y in range(0, 15):
            for x in range(100):
                im.putpixel((x, y), (255, 0, 0))            # faixa de cima (será cortada)
        out = M.cover_fit(im, 160, 90)
        self.assertEqual(out.size, (160, 90))
        self.assertEqual(out.getpixel((80, 2)), (0, 0, 255))   # a faixa vermelha do topo saiu no corte; o centro ficou

    def test_fit_inside_keeps_the_proportion(self):
        from PIL import Image

        out = M.fit_inside(Image.new("RGB", (400, 200)), 128, 128)
        self.assertEqual(out.size, (128, 64))
        self.assertEqual(M.fit_inside(Image.new("RGB", (64, 64)), 64, 64).size, (64, 64))


class H3PromptTests(unittest.TestCase):
    def test_reference_markers_become_picture_tags(self):
        out = M.h3_picture_prompt("Edit the provided reference image. Apply exactly this change: troque a roupa de @a (reference image 1, a frame of the video)", 1)
        self.assertTrue(out.startswith("Edit <Picture 1>. Apply"), out)
        self.assertIn("@a <Picture 1>", out)
        self.assertNotIn("reference image", out)
        out = M.h3_picture_prompt("troque @a (reference image 1) pela @b (reference image 2)", 2)
        self.assertEqual(out, "troque @a <Picture 1> pela @b <Picture 2>")

    def test_a_plain_prompt_still_gets_the_card_convention(self):
        self.assertEqual(M.h3_picture_prompt("faça um gato", 1), "Edit <Picture 1>. faça um gato")
        self.assertTrue(M.h3_picture_prompt("faça um gato", 2).startswith("Reference images: <Picture 1>, <Picture 2>."))
        self.assertEqual(M.h3_picture_prompt("já cita <Picture 2>", 2), "já cita <Picture 2>")


class LowQuantWarningTests(TmpCase):
    def test_low_quant_helper(self):
        self.assertEqual(E._low_quant("flux-3-image-klein-UD-Q2_K_XL.gguf"), "Q2_K_XL")
        self.assertEqual(E._low_quant("x-Q3_K_S.gguf"), "Q3_K_S")
        self.assertEqual(E._low_quant("x-Q4_K_M.gguf"), "")
        self.assertEqual(E._low_quant(""), "")

    def run_same(self, model):
        from openflow.storage import Store
        from tests.test_canvas import edge, node

        store = Store(self.tmp / "home")
        cs = store.projects
        c = cs.create("t")
        src = proc.image("original", "96x96", 3)
        aid = cs.add_asset(c["id"], src, "png", "image", name="a.png", mime="image/png")["id"]
        cs.save_layout(c["id"], {"nodes": [node("upload", nid="u", files=[aid]), node("image", nid="g", prompt="diminui levemente o circulo", mode="edit", model=model)], "edges": [edge("u", "g", "refs")]})

        class Fake:
            supports_refs = True
            refs_edit_only = True
            label = "Fake"
            edit_mode = False

            def max_refs(self, model=""):
                return 4

            def refs_need_edit(self, model=""):
                return False

            def frames_edit_for(self, model=""):
                return True

            def image(self, prompt, *, refs=(), **k):
                return [M.Media(src, "image/png")]

        events = []
        with mock.patch.object(E, "build_media", lambda *a, **k: Fake()):
            E.CanvasEngine(store, c["id"], events.append).run(None, False)
        return [w for e in events for w in (e.get("warnings") or []) if "quase igual" in w]

    def test_the_warning_blames_a_very_low_quant(self):
        w = self.run_same("flux-3-image-klein-UD-Q2_K_XL.gguf")
        self.assertTrue(w and "Q2_K_XL" in w[0] and "Q4" in w[0], w)

    def test_the_warning_stays_generic_for_a_good_quant(self):
        w = self.run_same("flux-3-image-klein-Q8_0.gguf")
        self.assertTrue(w and "quantização do modelo" not in w[0], w)


@unittest.skipUnless(shutil.which("ffmpeg"), "precisa do ffmpeg")
class ContinueFromLastFrameTests(TmpCase):
    def make_video(self, path):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=64x64:r=10:d=2", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=10:d=1",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p", "-pix_fmt", "yuv420p", str(path)], check=True)

    def test_the_video_node_continues_from_the_last_frame_but_images_use_the_middle(self):
        from openflow.storage import Store
        from openflow.canvas import engine as Eg

        store = Store(self.tmp / "home")
        cs = store.projects
        c = cs.create("t")
        vid = self.tmp / "v.mp4"
        self.make_video(vid)
        a = cs.add_asset(c["id"], vid.read_bytes(), "mp4", "video", name="v.mp4", mime="video/mp4")
        eng = Eg.CanvasEngine(store, c["id"], lambda ev: None)
        asset = {**a, "kind": "video", "duration": 3.0}
        from PIL import Image

        def color(got):
            return Image.open(io.BytesIO(got[0])).convert("RGB").getpixel((32, 32))

        mid = color(eng._video_frame(asset))
        last = color(eng._video_frame(asset, last=True))
        self.assertGreater(mid[0], 150, mid)    # 1,5 s: ainda no trecho vermelho
        self.assertGreater(last[2], 150, last)  # o último quadro é azul


if __name__ == "__main__":
    unittest.main()
