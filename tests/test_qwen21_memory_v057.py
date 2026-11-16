"""v0.57: «falta de memória» do sd-cli (código -9, Qwen-Image 2.1 com imagem de referência) — a mensagem diz em que etapa acabou, quanto os arquivos somam e o que fazer; falta durante os passos tenta de novo em resolução menor; a barra de progresso cortada não polui a mensagem."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from openflow.canvas import media as M
from openflow.canvas import sdcli
from openflow.providers.base import ProviderError

WEIGHTS_TAIL = ["[I] loading tensors completed, taking 2.04s (read: 2.02s, memcpy: 0.00s)", "--- model_loader.cpp:1437 | [I] qwen3vl build cached graph cut plan done (2 ms)",
                "--- ggml_graph_cut.cpp:1032 | [I] get_learned_condition completed, taking 47.78s", "--- image.cpp:664 | [I] generating image: 1/1 - seed 1705211315",
                "--- image.cpp:1005 | [I] qwen_image_2_1 build cached graph cut plan done (3 ms)", "|## | 6/297 - 0.00MB/s"]
SAMPLING_TAIL = ["--- image.cpp:664 | [I] generating image: 1/1 - seed 7", "|=====>    | 12/35 - 2.40s/it"]


def png():
    b = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(b, "PNG")
    return b.getvalue()


class StageTests(unittest.TestCase):
    def test_stage_from_the_progress_unit(self):
        self.assertEqual(sdcli.oom_stage(WEIGHTS_TAIL), "weights")        # bytes/s: carregando os pesos
        self.assertEqual(sdcli.oom_stage(SAMPLING_TAIL), "sampling")      # s/it: nos passos
        self.assertEqual(sdcli.oom_stage(["[I] algo"]), "unknown")
        self.assertEqual(sdcli.oom_stage([]), "unknown")
        self.assertEqual(sdcli.oom_stage(["|# | 3/9 - 1.1it/s"]), "sampling")

    def test_a_cut_progress_bar_is_not_part_of_the_message(self):
        self.assertTrue(sdcli._is_progress("|## | 6/297 - 0.00MB/s"))      # sem os «###» (o log foi cortado): antes entrava na mensagem
        self.assertTrue(sdcli._is_progress("| 12/35 - 2.40s/it"))
        self.assertFalse(sdcli._is_progress("[E] 3/4 tensors failed"))
        t = sdcli.failure_text(WEIGHTS_TAIL)
        self.assertNotIn("6/297", t)
        self.assertNotIn("0.00MB/s", t)

    def test_run_raises_out_of_memory_with_the_stage_when_the_system_kills_it(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("SIGKILL como o OOM killer: só no Linux")
        script = "import os, signal, sys\nfor l in " + repr(WEIGHTS_TAIL) + ":\n    print(l, flush=True)\nos.kill(os.getpid(), signal.SIGKILL)\n"
        with self.assertRaises(sdcli.OutOfMemory) as cm:
            sdcli.run([sys.executable, "-c", script], Path(sys.executable))
        self.assertEqual(cm.exception.stage, "weights")
        self.assertIn("falta de memória", str(cm.exception))
        self.assertIsInstance(cm.exception, ProviderError)               # quem captura ProviderError continua funcionando


class HintTests(unittest.TestCase):
    def files(self):
        d = Path(tempfile.mkdtemp())
        kw = {}
        for key, name, mb in (("diffusion_model_path", "m.gguf", 4), ("llm_path", "t.gguf", 5), ("llm_vision_path", "v.gguf", 1), ("vae_path", "ae.safetensors", 1)):
            (d / name).write_bytes(b"x" * mb * 1_000_000)
            kw[key] = str(d / name)
        return kw

    def test_the_hint_sums_the_files_and_says_what_to_do(self):
        with mock.patch.object(M._native, "sys_info", return_value={"ram_total": 16 << 30, "ram_avail": 3 << 30}):
            h = M._memory_hint(self.files(), 1, "weights")
        self.assertIn("modelo", h)
        self.assertIn("codificador de texto", h)
        self.assertIn("projetor de visão", h)
        self.assertIn("16 GB de RAM (3 GB livres agora)", h)
        self.assertIn("CARREGAR os pesos", h)
        self.assertIn("baixar a resolução não resolve", h)
        self.assertIn("tire as imagens de referência", h)
        self.assertIn("Q3_K_XL", h)
        self.assertIn('"llm_path"', h)

    def test_without_references_the_reference_tip_is_left_out_and_sampling_is_explained(self):
        kw = self.files()
        kw.pop("llm_vision_path")
        h = M._memory_hint(kw, 0, "sampling")
        self.assertNotIn("tire as imagens de referência", h)
        self.assertIn("durante a geração", h)
        self.assertNotIn("CARREGAR", h)

    def test_no_files_and_no_hardware_info_do_not_break_it(self):
        with mock.patch.object(M._native, "sys_info", side_effect=RuntimeError("sem núcleo")):
            h = M._memory_hint({}, 0, "unknown")
        self.assertTrue(h.strip().startswith("Para liberar memória") or "Para liberar memória" in h)


class RetryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "image").mkdir()
        for n in ("qwen-image-2.1-step90000-Q4_0.gguf", "qwen_image_2.1_vae_bf16.safetensors", "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf", "Qwen3-VL-8B-Instruct-mmproj-F16.gguf"):
            (self.root / "image" / n).write_bytes(b"x" * 1000)
        M._LOCAL_CACHE.clear()
        self.prov = M.GGUFMedia({"models_dir": str(self.root), "models": {"image": "qwen-image-2.1-step90000-Q4_0.gguf"}})
        self.path = self.root / "image" / "qwen-image-2.1-step90000-Q4_0.gguf"
        self.kw = {"diffusion_model_path": "@model", "llm_path": "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf", "llm_vision_path": "Qwen3-VL-8B-Instruct-mmproj-F16.gguf", "vae_path": "qwen_image_2.1_vae_bf16.safetensors"}

    def run_cli(self, outcomes, refs=()):
        sizes, notes = [], []
        it = iter(outcomes)

        def gen(c, kw, run_p, **k):
            sizes.append((k["width"], k["height"]))
            r = next(it)
            if isinstance(r, Exception):
                raise r
            return r, []
        self.prov.ctl.note = notes.append
        with mock.patch.object(M.sdcli, "find", return_value=Path("/x/sd-cli")), mock.patch.object(M.sdcli, "generate_image", gen), \
                mock.patch.object(M.GGUFMedia, "_cli_call", lambda self, path, fn: fn(Path("/x/sd-cli"))), mock.patch.object(M.GGUFMedia, "_need_companions", staticmethod(lambda *a: None)):
            try:
                out = self.prov._image_cli(self.path, self.kw, {}, "uma thumb", "1024x576", 1, 5, " ", list(refs))
                return out, sizes, notes, None
            except ProviderError as exc:
                return None, sizes, notes, exc

    def test_running_out_of_memory_during_the_steps_retries_once_in_a_smaller_size(self):
        oom = sdcli.OutOfMemory("O sd-cli falhou (código -9): falta de memória", "sampling")
        out, sizes, notes, err = self.run_cli([oom, b"\x89PNG"])
        self.assertIsNone(err)
        self.assertEqual(len(out), 1)
        self.assertEqual(sizes, [(1024, 576), (704, 400)])                   # 0,7×, em múltiplos de 16
        self.assertTrue(any("Faltou memória" in n and "704×400" in n for n in notes), notes)

    def test_running_out_of_memory_while_loading_the_weights_does_not_retry_and_explains(self):
        oom = sdcli.OutOfMemory("O sd-cli falhou (código -9): falta de memória", "weights")
        out, sizes, notes, err = self.run_cli([oom, b"\x89PNG"], refs=[(png(), "image/png")])
        self.assertIsNotNone(err)
        self.assertEqual(sizes, [(1024, 576)])                              # uma só tentativa: reduzir a imagem não ajuda quando a memória acaba nos pesos
        msg = str(err)
        self.assertIn("falta de memória", msg)
        self.assertIn("CARREGAR os pesos", msg)
        self.assertIn("tire as imagens de referência", msg)

    def test_a_second_failure_during_the_steps_is_explained_after_the_retry(self):
        oom = sdcli.OutOfMemory("O sd-cli falhou (código -9): falta de memória", "sampling")
        out, sizes, notes, err = self.run_cli([oom, oom])
        self.assertEqual(len(sizes), 2)
        self.assertIn("segunda tentativa", str(err))

    def test_other_failures_are_not_retried(self):
        out, sizes, notes, err = self.run_cli([ProviderError("O sd-cli falhou (código 1): [E] algo")])
        self.assertEqual(len(sizes), 1)
        self.assertIn("código 1", str(err))
        out, sizes, notes, err = self.run_cli([sdcli.OutOfMemory("falta de memória", "unknown")])
        self.assertEqual(len(sizes), 1)                                      # etapa desconhecida: sem tentativa extra


if __name__ == "__main__":
    unittest.main()
