"""v0.84: bugs achados na caça — o fluxo das faixas Q2–Q8 de ponta a ponta, (o campo de modelo do nó «Modelo PyTorch/TensorFlow» saiu na v0.87) e a linha de comando:
1. o campo do nó é texto livre: um nome comprido demais ou uma pasta sem permissão (/proc) dava OSError/PermissionError e a tela de status do nó recebia «erro interno» (500);
2. `flow torch --index 'a b;rm -rf /'` mostrava um comando para copiar com o texto solto dentro; agora o índice é validado;
3. `flow models quant --name x` (arquivo que não está baixado) dizia «só modelos de texto, imagem e vídeo»;
4. a «Quantização ao carregar» no LTX-2 (diffusers) e a faixa Q… no pipeline modular (FLUX.3) eram ignoradas em silêncio."""
import json
import os
import sys
import tempfile
import threading
import types
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from openflow.canvas import frameworks as fw
from openflow.canvas import media as M
from openflow.providers import ProviderError


class TorchIndexTests(unittest.TestCase):
    def test_valid_indexes(self):
        for ok in ("cu130", "rocm7.1", "xpu", "cpu", "nightly/cu130", "cu12_6"):
            self.assertTrue(fw.valid_index(ok), ok)
        for bad in ("", "a b", "a;rm -rf /", "../x", "a/../b", "-x", "x" * 60, "a\nb", "$(id)", "a&b", "https://evil/x"):
            self.assertFalse(fw.valid_index(bad), bad)

    def test_a_bad_index_is_refused_everywhere(self):
        with self.assertRaises(ValueError):
            fw.torch_command("nvidia", "Linux", "a b;rm")
        with self.assertRaises(ValueError):
            fw.torch_install("nvidia", "Linux", index="../x", run=lambda c: 0)
        with mock.patch.dict(os.environ, {"OPENFLOW_TORCH_INDEX": "x y"}):
            with self.assertRaises(ValueError):
                fw.torch_install("nvidia", "Linux", run=lambda c: 0)

    def test_the_cli_refuses_a_bad_index_without_printing_a_command(self):
        import contextlib
        import io

        from openflow import cli

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), mock.patch.object(fw, "vendors", return_value=["nvidia"]):
            code = cli._torch(types.SimpleNamespace(install=False, index="a b;rm -rf /"))
        self.assertEqual(code, 2)
        self.assertNotIn("pip install", buf.getvalue())
        self.assertNotIn("rm -rf", buf.getvalue().replace("a b;rm -rf /", ""))

    def test_the_cli_names_a_missing_model(self):
        import contextlib
        import io

        from openflow import cli
        from openflow.storage import Store

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli._models_quant(Store(Path(tempfile.mkdtemp())), types.SimpleNamespace(name="nao-baixado-Q8_0.gguf", tier="Q4", kind=""))
        self.assertEqual(code, 1)
        self.assertIn("nao-baixado-Q8_0.gguf", buf.getvalue())
        self.assertNotIn("Só modelos de texto", buf.getvalue())
        self.assertNotIn("Only text, image and video", buf.getvalue())


class SilentTierTests(unittest.TestCase):
    def test_ltx2_says_the_tier_does_not_apply(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "video").mkdir()
        (tmp / "video" / "ltx-2.5-22b-distilled-UD-Q8_0.gguf").write_bytes(b"g")
        notes = []
        M._LOCAL_CACHE.clear()
        p = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(tmp), "models": {"video": "ltx-2.5-22b-distilled-UD-Q8_0.gguf"}, "needs_key": False})
        p.ctl = types.SimpleNamespace(note=notes.append, check=lambda: None)
        with mock.patch.object(M.GGUFMedia, "_video_ltx2", return_value=M.Media(b"v", "video/mp4")) as ltx:
            p.video("x", extra={"quant": "Q4", "sample_steps": 8})
        self.assertTrue(any("não vale para o LTX-2" in n for n in notes), notes)
        self.assertNotIn("quant", ltx.call_args[0][-1])
        self.assertEqual(ltx.call_args[0][-1].get("sample_steps"), 8)                               # os outros ajustes seguem

    def test_ltx2_without_a_tier_says_nothing(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "video").mkdir()
        (tmp / "video" / "ltx-2.5-22b-distilled-UD-Q8_0.gguf").write_bytes(b"g")
        notes = []
        M._LOCAL_CACHE.clear()
        p = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(tmp), "models": {"video": "ltx-2.5-22b-distilled-UD-Q8_0.gguf"}, "needs_key": False})
        p.ctl = types.SimpleNamespace(note=notes.append, check=lambda: None)
        with mock.patch.object(M.GGUFMedia, "_video_ltx2", return_value=M.Media(b"v", "video/mp4")):
            p.video("x", extra={})
        self.assertFalse(any("Quantização" in n for n in notes))

    def test_the_modular_pipeline_says_the_tier_is_not_applied(self):
        from openflow.canvas import localmodels as lm

        M._LOCAL_CACHE.clear()
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        torch.backends.mps = None
        diffusers = mock.MagicMock()
        notes = []
        with mock.patch.dict(sys.modules, {"torch": torch, "diffusers": diffusers}), mock.patch.object(lm, "downloaded_precision", return_value="q4"), mock.patch.object(lm, "has_fp16_variant", return_value=False), \
                mock.patch.object(M.LocalHFMedia, "_is_modular", return_value=True), mock.patch.object(M.LocalHFMedia, "_load_modular", return_value=mock.MagicMock()), mock.patch.object(M, "_slim", side_effect=lambda p, d: p):
            p = M._KINDS["local_hf"]({"id": "local_hf", "label": "l", "models": {"image": "black-forest-labs/FLUX.3-klein"}, "needs_key": False, "models_dir": tempfile.mkdtemp()})
            p.ctl = types.SimpleNamespace(note=notes.append, check=lambda: None)
            try:
                p.image("um gato", size="512x512")
            except Exception:  # noqa: BLE001 — o pipeline falso não gera nada: só importa o aviso antes dele
                pass
        self.assertTrue(any("pipeline modular" in n and "Q4" in n for n in notes), notes)


class KeepGpuTorchTests(unittest.TestCase):
    """`flow update`/`flow libs` não trocam um PyTorch de placa de vídeo (2.15.0+cu130) pelo do PyPI (no Windows, só de CPU)."""

    def pip_args(self, installed, extras="media"):
        from tests.test_cli import pip_installs, run_cli

        code, calls, out = run_cli(["libs", "--extras", extras], installed=installed)
        return code, [part for c in pip_installs(calls) for part in c], out

    def test_a_cuda_build_is_left_alone(self):
        code, parts, out = self.pip_args({"torch": "2.15.0+cu130", "torchvision": "0.30.0+cu130", "diffusers": "0.31"})
        self.assertEqual(code, 0)
        self.assertNotIn("torch", parts)
        self.assertNotIn("torchvision", parts)
        self.assertIn("diffusers>=0.30", parts)                                                    # o resto do grupo atualiza normalmente
        self.assertIn("PyTorch com placa de vídeo mantido", out)
        self.assertIn("torch 2.15.0+cu130", out)
        self.assertIn("flow torch --install", out)

    def test_rocm_and_xpu_builds_too(self):
        for v in ("2.15.0+rocm7.1", "2.15.0+xpu"):
            _code, parts, _out = self.pip_args({"torch": v, "diffusers": "0.31"})
            self.assertNotIn("torch", parts, v)

    def test_a_cpu_build_or_a_plain_one_is_updated_as_before(self):
        for v in ("2.15.0+cpu", "2.15.0"):
            _code, parts, out = self.pip_args({"torch": v, "diffusers": "0.31"})
            self.assertIn("torch", parts, v)
            self.assertNotIn("mantido", out)

    def test_not_installed_is_installed(self):
        _code, parts, _out = self.pip_args({})
        self.assertIn("torch", parts)

    def test_the_windows_cpu_build_with_an_nvidia_card_gets_a_hint(self):
        self.assertIsNone(fw.quick_torch_hint("2.15.0+cu130", ["nvidia"], "Windows"))
        self.assertIsNone(fw.quick_torch_hint("2.15.0", ["nvidia"], "Linux"))                  # no Linux o pacote do PyPI já é o da CUDA
        self.assertIsNone(fw.quick_torch_hint("2.15.0", [], "Windows"))
        self.assertIsNone(fw.quick_torch_hint("", ["nvidia"], "Windows"))
        for v in ("2.15.0", "2.15.0+cpu"):
            h = fw.quick_torch_hint(v, ["nvidia"], "Windows")
            self.assertEqual(h["level"], "warn")
            self.assertIn("flow torch --install", h["text"])
            self.assertIn("flow torch --install", h["text_en"])
            self.assertIn("/whl/cu130", h["command"])

    def test_libs_ends_with_the_hint_on_windows_with_an_nvidia_card(self):
        with mock.patch.object(fw, "vendors", return_value=["nvidia"]), mock.patch.object(fw, "dist_version", return_value="2.15.0"), mock.patch("platform.system", return_value="Windows"):
            _code, _parts, out = self.pip_args({"torch": "2.15.0", "diffusers": "0.31"})
        self.assertRegex(out, r"Há uma placa NVIDIA, mas o PyTorch 2.15.0 do PyPI|There is an NVIDIA card, but PyTorch 2.15.0 from PyPI")
        self.assertIn("flow torch --install", out)
        with mock.patch.object(fw, "vendors", return_value=["nvidia"]), mock.patch.object(fw, "dist_version", return_value="2.15.0+cu130"), mock.patch("platform.system", return_value="Windows"):
            _code, _parts, out = self.pip_args({"torch": "2.15.0+cu130", "diffusers": "0.31"})
        self.assertNotRegex(out, r"Há uma placa NVIDIA|There is an NVIDIA card")

    def test_keep_gpu_torch_unit(self):
        from openflow import cli

        with mock.patch.object(cli, "_installed_version", side_effect=lambda r: {"torch": "2.1+cu121", "torchvision": "0.2", "numpy": "2+cu"}.get(cli._req_name(r))):
            keep, kept = cli._keep_gpu_torch(["torch", "torchvision", "numpy", "pillow"])
        self.assertEqual((keep, kept), (["torchvision", "numpy", "pillow"], ["torch 2.1+cu121"]))     # só torch e torchvision; numpy com «+» não conta


if __name__ == "__main__":
    unittest.main()
