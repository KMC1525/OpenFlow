"""v0.77: travamentos ao gerar e editar em máquinas fracas — o nó parecia «travado» por quatro motivos, todos tratados:
1. o botão «Parar» só era lido entre uma imagem e outra (minutos de silêncio numa máquina fraca) → agora a cada passo de difusão, com o progresso («passo 5 de 28, faltam ≈ …»);
2. o torch usava todos os núcleos da CPU e o computador inteiro engasgava → agora deixa um núcleo livre (segue o modo de desempenho);
3. o carregamento de um modelo grande (minutos) e as etapas finais sem eventos (decodificação na CPU, stable-diffusion.cpp) não diziam nada → agora um aviso periódico com o tempo decorrido;
4. um modelo maior que a RAM livre ia para a memória virtual do disco e travava o computador → agora avisa (acima de 1× a RAM livre) e recusa (acima de 2×).
Nenhum modelo real foi executado: pipelines falsos com a assinatura real do diffusers, torch simulado."""
import sys
import time
import types
import unittest
from unittest import mock

from openflow.canvas import localmodels as lm
from openflow.canvas import lowmem
from openflow.canvas import media as M
from openflow.canvas import procedural as proc
from openflow.providers import ProviderError
from openflow.util import Cancelled
from tests.test_canvas import provider
from tests.test_lowmem_v072 import make_pipe

GIB = 1024 ** 3


class Ctl:
    def __init__(self, cancel_at=None):
        self.notes, self.checks, self.cancel_at = [], 0, cancel_at

    def check(self):
        self.checks += 1
        if self.cancel_at is not None and self.checks >= self.cancel_at:
            raise Cancelled()

    def note(self, m):
        self.notes.append(m)


class PureTests(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual([lowmem.fmt_seconds(s) for s in (0, 5, 65, 3725)], ["0s", "5s", "1min05s", "1h02"])

    def test_fit(self):
        self.assertEqual(lowmem.fit(8 * GIB, 16 * GIB, "cpu")[0], "ok")
        self.assertEqual(lowmem.fit(20 * GIB, 16 * GIB, "cpu")[0], "warn")
        verdict, msg = lowmem.fit(40 * GIB, 16 * GIB, "cpu")
        self.assertEqual(verdict, "refuse")
        self.assertIn("40.0 GB", msg)
        self.assertIn("16.0 GB de RAM livre", msg)
        self.assertIn("GGUF", msg)
        self.assertIn("OPENFLOW_ALLOW_SWAP=1", msg)
        self.assertEqual(lowmem.fit(40 * GIB, 16 * GIB, "gpu")[0], "ok")                            # tudo na placa: a RAM não conta
        self.assertEqual(lowmem.fit(0, 16 * GIB, "cpu")[0], "ok")                                   # tamanho desconhecido: não atrapalha
        self.assertEqual(lowmem.fit(40 * GIB, 0, "cpu")[0], "ok")
        with mock.patch.dict("os.environ", {"OPENFLOW_ALLOW_SWAP": "1"}):
            self.assertEqual(lowmem.fit(40 * GIB, 16 * GIB, "cpu")[0], "warn")                      # de propósito: só avisa

    def test_torch_threads_always_leave_a_core_free(self):
        self.assertEqual([lowmem.torch_threads(n, "balanced") for n in (1, 2, 4, 8, 16)], [1, 2, 3, 7, 15])
        self.assertEqual([lowmem.torch_threads(n, "light") for n in (1, 2, 4, 8)], [1, 1, 2, 4])
        self.assertEqual(lowmem.torch_threads(8, "max"), 0)                                         # máximo: não mexe

    def test_effective_steps(self):
        self.assertEqual(lowmem.effective_steps(28), 28)
        self.assertEqual(lowmem.effective_steps(28, 0.75), 21)
        self.assertEqual(lowmem.effective_steps(2, 0.1), 1)
        self.assertEqual(lowmem.effective_steps(0), 0)

    def test_signature_helpers(self):
        class P:
            def __call__(self, prompt=None, num_inference_steps=50, callback_on_step_end=None): ...

        class Q:
            def __call__(self, **kw): ...
        self.assertEqual(lowmem.default_of(P(), "num_inference_steps"), 50)
        self.assertIsNone(lowmem.default_of(P(), "nao_existe"))
        self.assertTrue(lowmem.explicit(lowmem.params_of(P()), "callback_on_step_end"))
        self.assertFalse(lowmem.explicit(lowmem.params_of(Q()), "callback_on_step_end"))           # **kwargs não conta: não se inventa um argumento para um pipeline desconhecido


class StepCallbackTests(unittest.TestCase):
    def test_progress_is_throttled_and_always_shows_the_last_step(self):
        ctl, now = Ctl(), [0.0]
        cb = lowmem.step_progress(ctl, 10, "Gerando imagem", interval=2.0, clock=lambda: now[0])
        for step in range(10):
            now[0] += 1.0
            self.assertEqual(cb(None, step, 0, {"latents": 1}), {"latents": 1})                      # devolve os tensores, como o diffusers exige
        self.assertLess(len(ctl.notes), 10)
        self.assertEqual(ctl.checks, 10)                                                            # o cancelamento é lido em TODO passo
        self.assertEqual(ctl.notes[-1], "Gerando imagem: passo 10 de 10")
        self.assertTrue(any("faltam ≈" in n for n in ctl.notes[:-1]))

    def test_cancel_stops_at_the_next_step(self):
        ctl = Ctl(cancel_at=3)
        cb = lowmem.step_progress(ctl, 10)
        cb(None, 0, 0, {})
        cb(None, 1, 0, {})
        with self.assertRaises(Cancelled):
            cb(None, 2, 0, {})

    def test_unknown_total_still_reports(self):
        ctl = Ctl()
        lowmem.step_progress(ctl, 0, "Gerando vídeo", interval=0)(None, 4, 0, {})
        self.assertEqual(ctl.notes, ["Gerando vídeo: passo 5"])

    def test_a_ctl_without_methods_does_not_break_it(self):
        lowmem.step_progress(types.SimpleNamespace(), 3)(None, 0, 0, {"a": 1})

    def test_heartbeat_emits_while_the_block_runs_and_stops_after(self):
        ctl = Ctl()
        with lowmem.heartbeat(ctl, "Ainda gerando", interval=0.05):
            end = time.time() + 5   # espera os avisos em vez de contar o tempo: num runner lento (macOS do CI) 0,3 s rendia só 2
            while len(ctl.notes) < 3 and time.time() < end:
                time.sleep(0.05)
        n = len(ctl.notes)
        self.assertGreaterEqual(n, 3)
        self.assertTrue(ctl.notes[0].startswith("Ainda gerando… "))
        time.sleep(0.2)
        self.assertEqual(len(ctl.notes), n)


def diffusers_call(self, prompt=None, height=None, width=None, num_inference_steps=50, guidance_scale=7.0, generator=None, callback_on_step_end=None, callback_on_step_end_tensor_inputs=None):
    """Um pipeline que chama o callback a cada passo, como o diffusers."""
    self.seen["steps_run"] = 0
    for i in range(num_inference_steps):
        if callback_on_step_end:
            callback_on_step_end(self, i, 0, {"latents": i})
        self.seen["steps_run"] += 1
    from tests.test_lowmem_v072 import respond

    return respond(self, dict(prompt=prompt, steps=num_inference_steps, callback=callback_on_step_end))


class ImageNodeTests(unittest.TestCase):
    def setUp(self):
        M._LOCAL_CACHE.clear()
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        torch.backends.mps = None
        self.mods = {"torch": torch, "diffusers": mock.MagicMock()}

    def generate(self, ctl, model="stabilityai/sdxl-turbo", count=1, refs=(), call=diffusers_call):
        pipe_cls = make_pipe("StableDiffusionXLPipeline", call)
        self.mods["diffusers"].AutoPipelineForText2Image.from_pretrained.side_effect = lambda m, **k: pipe_cls()
        with mock.patch.dict(sys.modules, self.mods), mock.patch.object(lm, "downloaded_precision", return_value="fp32"), mock.patch.object(lm, "has_fp16_variant", return_value=False):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": model}, key="", needs_key=False)
            p.ctl = ctl
            try:
                return p.image("um gato", size="512x512", count=count, refs=list(refs)), pipe_cls
            except BaseException as exc:
                return exc, pipe_cls

    def test_progress_reaches_the_node_during_the_generation(self):
        ctl = Ctl()
        out, pipe_cls = self.generate(ctl, model="stabilityai/stable-diffusion-3.5-medium")
        self.assertEqual(out[0].mime, "image/png")
        steps = pipe_cls.seen["kw"]["steps"]
        self.assertEqual(steps, 28)
        self.assertTrue(any(n.startswith("Gerando imagem: passo ") and f"de {steps}" in n for n in ctl.notes), ctl.notes[-5:])
        self.assertEqual(pipe_cls.seen["steps_run"], 28)

    def test_stop_cancels_in_the_middle_of_the_diffusion_not_at_the_end(self):
        ref = Ctl()
        _, probe = self.generate(ref, model="stabilityai/stable-diffusion-3.5-medium")
        outside = ref.checks - 28                                                                    # as leituras de cancelamento fora do laço de passos
        ctl = Ctl(cancel_at=outside + 10)
        out, pipe_cls = self.generate(ctl, model="stabilityai/stable-diffusion-3.5-medium")
        self.assertIsInstance(out, Cancelled)                                                      # sem ser embrulhado em outro erro
        self.assertEqual(pipe_cls.seen["steps_run"], 9)                                              # parou no 10º passo, não 18 passos depois

    def test_several_images_say_which_one(self):
        ctl = Ctl()
        self.generate(ctl, model="stabilityai/sdxl-turbo", count=2)
        self.assertTrue(any("Gerando imagem 1 de 2" in n for n in ctl.notes))
        self.assertTrue(any("Gerando imagem 2 de 2" in n for n in ctl.notes))

    def test_a_pipeline_without_the_callback_still_works(self):
        from tests.test_lowmem_v072 import flux_call

        ctl = Ctl()
        out, pipe_cls = self.generate(ctl, model="black-forest-labs/FLUX.1-schnell", call=flux_call)
        self.assertEqual(out[0].mime, "image/png")
        self.assertNotIn("callback_on_step_end", pipe_cls.seen["kw"])

    def test_image_to_image_counts_only_the_steps_it_runs(self):
        def i2i(self, prompt=None, image=None, strength=0.6, num_inference_steps=50, callback_on_step_end=None, generator=None, guidance_scale=7.0):
            total = int(num_inference_steps * strength)
            for k in range(total):
                callback_on_step_end(self, k, 0, {})
            from tests.test_lowmem_v072 import respond

            return respond(self, dict(total=total))
        ctl = Ctl()
        pipe_cls = make_pipe("StableDiffusionXLPipeline", diffusers_call)
        i2i_cls = make_pipe("StableDiffusionXLImg2ImgPipeline", i2i)
        d = self.mods["diffusers"]
        d.AutoPipelineForText2Image.from_pretrained.side_effect = lambda m, **k: pipe_cls()
        d.AutoPipelineForImage2Image.from_pipe.side_effect = lambda pipe: i2i_cls()
        with mock.patch.dict(sys.modules, self.mods), mock.patch.object(lm, "downloaded_precision", return_value="fp32"), mock.patch.object(lm, "has_fp16_variant", return_value=False):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": "stabilityai/stable-diffusion-3.5-medium"}, key="", needs_key=False)
            p.ctl = ctl
            p.image("troque", size="512x512", refs=[(proc.image("r", "64x64", 1), "image/png")])
        total = i2i_cls.seen["kw"]["total"]
        self.assertTrue(any(f"de {total}" in n for n in ctl.notes), (total, ctl.notes[-3:]))      # «de 21», não «de 28»


class LoadTests(unittest.TestCase):
    def setUp(self):
        M._LOCAL_CACHE.clear()
        self.ctl = Ctl()
        M._TLS.ctl = self.ctl
        self.addCleanup(lambda: setattr(M._TLS, "ctl", None))

    def load(self, loader, plan=None, ram=16 * GIB, model="x/freeze-test"):
        with mock.patch.object(M, "_media_plan", return_value=plan if plan is not None else {}), mock.patch.object(M._perf, "memory_state", return_value={"ram_avail": ram}), mock.patch.object(M, "_limit_threads"):
            return M._local_load("image", model, loader)

    def test_a_slow_load_reports_that_it_is_working(self):
        with mock.patch.object(M, "_HEARTBEAT_S", 0.05):
            out = self.load(lambda: (time.sleep(0.35), "modelo")[1], model="x/slow-load")
        self.assertEqual(out, "modelo")
        beats = [n for n in self.ctl.notes if n.startswith("Carregando «x/slow-load» na memória")]
        self.assertGreaterEqual(len(beats), 3)
        n = len(self.ctl.notes)
        time.sleep(0.2)
        self.assertEqual(len(self.ctl.notes), n)                                                    # o aviso para quando o carregamento termina

    def test_a_model_far_bigger_than_the_ram_is_refused_before_it_freezes_the_computer(self):
        called = []
        with self.assertRaises(ProviderError) as cm:
            self.load(lambda: called.append(1), plan={"weights": 60 * GIB, "strategy": "cpu"}, ram=16 * GIB, model="x/huge")
        self.assertIn("«x/huge»", str(cm.exception))
        self.assertIn("memória virtual", str(cm.exception))
        self.assertEqual(called, [])                                                                # nem tentou carregar

    def test_a_model_a_bit_bigger_than_the_ram_only_warns(self):
        out = self.load(lambda: "ok", plan={"weights": 20 * GIB, "strategy": "cpu"}, ram=16 * GIB, model="x/bigish")
        self.assertEqual(out, "ok")
        self.assertTrue(any(n.startswith("Atenção: Este modelo ocupa 20.0 GB") for n in self.ctl.notes))

    def test_a_model_that_fits_loads_silently(self):
        self.load(lambda: "ok", plan={"weights": 6 * GIB, "strategy": "cpu"}, ram=16 * GIB, model="x/fits")
        self.assertFalse(any(n.startswith("Atenção") for n in self.ctl.notes))

    def test_a_cancel_during_the_load_is_honoured_right_after(self):
        self.ctl.cancel_at = 1
        with self.assertRaises(Cancelled):
            self.load(lambda: "modelo", model="x/cancelled")


    def test_a_ctl_left_over_from_a_cancelled_job_does_not_cancel_the_next_load(self):
        self.ctl.cancel_at = 1
        with self.assertRaises(Cancelled):
            self.load(lambda: "modelo", model="x/first")
        self.assertIsNone(getattr(M._TLS, "ctl", None))                                              # o Ctl vale só para uma chamada
        self.assertEqual(self.load(lambda: "outro", model="x/second"), "outro")                       # o trabalho seguinte carrega normalmente


class ThreadTests(unittest.TestCase):
    def run_limit(self, mode, physical, current):
        torch = types.SimpleNamespace(threads=current, get_num_threads=lambda: torch.threads, set_num_threads=lambda n: setattr(torch, "threads", n))
        M._TORCH_THREADS["orig"] = None
        with mock.patch.dict(sys.modules, {"torch": torch}), mock.patch.dict(M.PERF, {"mode": mode}), mock.patch.object(M._native, "sys_info", return_value={"physical": physical}):
            M._limit_threads()
            return torch.threads

    def test_one_core_stays_free(self):
        self.assertEqual(self.run_limit("balanced", 8, 16), 7)
        self.assertEqual(self.run_limit("balanced", 4, 8), 3)
        self.assertEqual(self.run_limit("light", 8, 16), 4)

    def test_the_max_mode_restores_every_thread(self):
        torch = types.SimpleNamespace(threads=16, get_num_threads=lambda: torch.threads, set_num_threads=lambda n: setattr(torch, "threads", n))
        M._TORCH_THREADS["orig"] = None
        with mock.patch.dict(sys.modules, {"torch": torch}), mock.patch.object(M._native, "sys_info", return_value={"physical": 8}):
            with mock.patch.dict(M.PERF, {"mode": "balanced"}):
                M._limit_threads()
            self.assertEqual(torch.threads, 7)
            with mock.patch.dict(M.PERF, {"mode": "max"}):
                M._limit_threads()
            self.assertEqual(torch.threads, 16)                                                     # voltou ao que o torch tinha

    def test_without_torch_nothing_breaks(self):
        with mock.patch.dict(sys.modules, {"torch": None}):
            M._limit_threads()


class VideoTests(unittest.TestCase):
    def test_video_reports_progress_and_can_be_cancelled(self):
        def ltx(self, prompt=None, height=None, width=None, num_frames=None, num_inference_steps=40, callback_on_step_end=None, generator=None):
            self.seen["run"] = 0
            for i in range(num_inference_steps):
                callback_on_step_end(self, i, 0, {})
                self.seen["run"] += 1
            return types.SimpleNamespace(frames=[["f"]])
        outside = None
        for cancel_at, expect_run in ((None, 40), ('rel5', 4)):
            M._LOCAL_CACHE.clear()
            torch = mock.MagicMock()
            torch.cuda.is_available.return_value = False
            torch.backends.mps = None
            d = mock.MagicMock()
            base = make_pipe("WanPipeline", ltx)
            d.DiffusionPipeline.from_pretrained.side_effect = lambda m, **k: base()
            ctl = Ctl(cancel_at=(outside + 5) if cancel_at == 'rel5' else None)
            with mock.patch.dict(sys.modules, {"torch": torch, "diffusers": d}), mock.patch.object(lm, "downloaded_precision", return_value="bf16"), mock.patch.object(lm, "has_fp16_variant", return_value=False), \
                    mock.patch.object(M, "_frames_to_mp4", side_effect=lambda frames, fps: M.Media(b"mp4", "video/mp4")), mock.patch.object(M.proc, "ffmpeg_path", return_value="ffmpeg"):
                p = provider("local_hf", "", {"video": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers"}, key="", needs_key=False)
                p.ctl = ctl
                if cancel_at:
                    with self.assertRaises(Cancelled):
                        p.video("ondas", duration=2)
                else:
                    p.video("ondas", duration=2)
            self.assertEqual(base.seen["run"], expect_run)
            if not cancel_at:
                outside = ctl.checks - 40
                self.assertTrue(any(n.startswith("Gerando vídeo: passo ") and "de 40" in n for n in ctl.notes))


class StillWorkingTests(unittest.TestCase):
    def test_the_gguf_generation_reports_while_it_runs(self):
        from tests.test_gguf_matrix_v075 import FakeSD
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        (tmp / "image").mkdir()
        (tmp / "image" / "flux1-schnell-Q4_0.gguf").write_bytes(b"g")
        M._LOCAL_CACHE.clear()
        sd = FakeSD()
        real = sd.module.StableDiffusion.generate_image

        def slow(self, **kw):
            time.sleep(0.25)
            return real(self, **kw)
        sd.module.StableDiffusion.generate_image = slow
        ctl = Ctl()
        orig = lowmem.heartbeat
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": sd.module}), mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False), \
                mock.patch.object(M.lowmem, "heartbeat", side_effect=lambda c, label, interval=15.0: orig(c, label, 0.05)):
            prov = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(tmp), "models": {"image": "flux1-schnell-Q4_0.gguf"}, "needs_key": False}, ctl)
            prov.image("x", size="512x512")
        self.assertTrue(any(n.startswith("Gerando a imagem com o modelo GGUF… ") for n in ctl.notes), ctl.notes)


if __name__ == "__main__":
    unittest.main()
