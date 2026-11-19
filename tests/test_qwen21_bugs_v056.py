"""v0.56: bugs ao gerar e editar com o Qwen-Image 2.1 (ChatR Labs «Uncensored Omni Quantized») — erro do sd-cli legível, limite de referências pelo modelo do nó, negativo recomendado e mensagem própria quando o projetor de visão falta."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import media as M
from openflow.canvas import sdcli, support
from openflow.providers.base import ProviderError

MODEL = "qwen-image-2.1-step90000-Q4_0.gguf"
OTHER = "z-image-turbo-Q4_K_M.gguf"
FILES = (MODEL, OTHER, "qwen_image_2.1_vae_bf16.safetensors", "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf", "Qwen3-VL-8B-Instruct-mmproj-F16.gguf", "ae.safetensors", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf")
def _png():
    import io
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(b, "PNG")
    return b.getvalue()


PNG = _png()

CAPTURE = ["| | ####################################### 98/98 - 739.37MB/s", "[I] loading tensors completed, taking 0.20s (read: 0.04s)", "--- model_loader.cpp:1437 | [I] encode_first_stage completed, taking 9.75s",
           "--- image.cpp:509 | [E] Qwen Image 2.1 editing requires Qwen3-VL vision weights; provide --llm_vision or a combined encoder", "--- conditioner.hpp:2837 | [E] failed to encode prompt",
           "--- image.cpp:575 | [E] generate failed", "--- main.cpp:1001"]


class FailureTextTests(unittest.TestCase):
    def test_progress_bars_do_not_hide_the_cause(self):
        t = sdcli.failure_text(CAPTURE)
        self.assertNotIn("####", t)
        self.assertNotIn("739.37MB/s", t)
        self.assertIn("requires Qwen3-VL vision weights", t)
        self.assertIn("failed to encode prompt", t)
        self.assertTrue(t.index("requires Qwen3-VL") < t.index("main.cpp"))      # o erro vem antes do contexto
        self.assertNotIn("---", t)

    def test_logs_without_errors_and_empty_logs(self):
        self.assertEqual(sdcli.failure_text(["a", "| |", "b"]), "a | b")
        self.assertIn("sem mensagem", sdcli.failure_text([]))
        self.assertIn("sem mensagem", sdcli.failure_text(["| #### 1/9", "====== 2/9"]))
        self.assertLessEqual(len(sdcli.failure_text(["[E] " + "x" * 3000])), 601)

    def test_progress_detection(self):
        self.assertTrue(sdcli._is_progress("| | ################ 98/98 - 739MB/s"))
        self.assertFalse(sdcli._is_progress("[E] 3/4 tensors failed"))
        self.assertFalse(sdcli._is_progress("loading 12 files"))

    def test_run_raises_the_readable_message(self):
        import sys
        script = "import sys\nfor l in " + repr(CAPTURE) + ":\n    print(l)\nsys.exit(1)\n"
        with self.assertRaises(ProviderError) as cm:
            sdcli.run([sys.executable, "-c", script], Path(sys.executable))
        msg = str(cm.exception)
        self.assertIn("código 1", msg)
        self.assertIn("requires Qwen3-VL vision weights", msg)
        self.assertNotIn("####", msg)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / "image").mkdir()
        for n in FILES:
            (self.root / "image" / n).write_bytes(b"x")
        M._LOCAL_CACHE.clear()

    def provider(self, default=OTHER):
        return M.GGUFMedia({"models_dir": str(self.root), "models": {"image": default}})

    def test_the_reference_limit_is_the_chosen_models_not_the_default_one(self):
        refs = [(PNG, "image/png")] * 3
        p = self.provider(default=OTHER)                  # o modelo padrão aceita 1 imagem; o do nó (Qwen 2.1), 4
        self.assertEqual((p.max_refs(OTHER), p.max_refs(MODEL)), (1, 4))
        calls = {}

        def gen(c, kw, run_p, **k):
            calls["refs"] = len(k["refs"])
            return b"\x89PNG", []
        with mock.patch.object(M.sdcli, "find", return_value=Path("/x/sd-cli")), mock.patch.object(M.sdcli, "generate_image", gen), \
                mock.patch.object(M.GGUFMedia, "_cli_call", lambda self, path, fn: fn(Path("/x/sd-cli"))), mock.patch.object(M.GGUFMedia, "_need_companions", staticmethod(lambda *a: None)):
            p._image_cli(self.root / "image" / MODEL, {"diffusion_model_path": "@model"}, {}, "troque", "512x512", 1, 5, "", refs)
        self.assertEqual(calls["refs"], 3)               # antes: 1 (o limite do modelo padrão)

    def test_the_recommended_negative_is_used_when_empty(self):
        seen = {}

        def engine(self, cap, path, load):
            raise ProviderError("parou aqui")

        def cli(self, path, load, extra, prompt, size, count, seed, negative, refs):
            seen["negative"] = negative
            return []
        for neg, want in (("", " "), ("   ", " "), ("blur, texto", "blur, texto")):
            p = self.provider(default=MODEL)
            with mock.patch.object(M.GGUFMedia, "_engine", engine), mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=True), mock.patch.object(M.GGUFMedia, "_image_cli", cli):
                p.image("um gato", negative=neg)
            self.assertEqual(seen["negative"], want, repr(neg))
        p = self.provider(default=OTHER)                 # outras famílias não mudam
        with mock.patch.object(M.GGUFMedia, "_engine", engine), mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=True), mock.patch.object(M.GGUFMedia, "_image_cli", cli):
            p.image("um gato", negative="")
        self.assertEqual(seen["negative"], "")
        self.assertEqual(support.family_of(MODEL)["negative_default"], " ")

    def test_the_sd_cli_receives_the_negative_and_the_vision_projector(self):
        args, _ = sdcli.build_args(Path("/x/sd-cli"), {"diffusion_model_path": "/m/a.gguf", "llm_vision_path": "/m/v.gguf"}, {}, prompt="p", width=512, height=512, seed=1, negative=" ", refs=[Path("/r.png")], out=Path("/o.png"))
        self.assertEqual(args[args.index("-n") + 1], " ")
        self.assertIn("--llm_vision", args)
        self.assertEqual(Path(args[args.index("-r") + 1]), Path("/r.png"))   # no Windows o caminho vira «\\r.png»

    def test_the_vision_error_from_sd_cli_becomes_an_actionable_message(self):
        p = self.provider(default=MODEL)

        def fail(self, path, fn):
            raise ProviderError("O sd-cli falhou (código 1): " + sdcli.failure_text(CAPTURE))
        with mock.patch.object(M.sdcli, "find", return_value=Path("/x/sd-cli")), mock.patch.object(M.GGUFMedia, "_cli_call", fail), mock.patch.object(M.GGUFMedia, "_need_companions", staticmethod(lambda *a: None)):
            with self.assertRaises(ProviderError) as cm:
                p._image_cli(self.root / "image" / MODEL, {"diffusion_model_path": "@model"}, {}, "troque", "512x512", 1, 5, "", [(PNG, "image/png")])
        msg = str(cm.exception)
        self.assertIn("projetor de visão", msg)
        self.assertIn(f"[[flow-support:{MODEL}]]", msg)
        self.assertNotIn("sd-cli falhou", msg)


if __name__ == "__main__":
    unittest.main()
