"""v0.82: PyTorch e TensorFlow — o que está instalado, em que aparelho roda, o que fazer para usar a placa de vídeo e em que framework cada modelo foi feito.

As decisões (`*_advice`, `torch_command`, `detect`) são de Python puro e testadas com dados de mentira; a sondagem das bibliotecas (`torch_info`, `tf_info`) é testada com bibliotecas simuladas e, se o PyTorch e o TensorFlow
estiverem instalados (no ambiente de desenvolvimento há os dois, num ambiente à parte), também com as de verdade. Nada foi testado com uma placa de vídeo de verdade."""
import importlib.util
import subprocess
import sys
import types
import unittest
from unittest import mock

from openflow.canvas import frameworks as fw

HAS_TORCH = importlib.util.find_spec("torch") is not None
HAS_TF = importlib.util.find_spec("tensorflow") is not None


class CommandTests(unittest.TestCase):
    def test_torch_command_per_card(self):
        self.assertEqual(fw.torch_command("nvidia", "Windows"), "python -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu130")
        self.assertIn("/whl/cu130", fw.torch_command("nvidia", "Linux"))
        self.assertIn("/whl/rocm7.1", fw.torch_command("amd", "Linux"))
        self.assertIn("/whl/cpu", fw.torch_command("amd", "Windows"))                       # ROCm só existe para Linux
        self.assertIn("/whl/xpu", fw.torch_command("intel", "Windows"))
        self.assertIn("/whl/cpu", fw.torch_command("", "Linux"))
        self.assertNotIn("--index-url", fw.torch_command("apple", "Darwin"))                 # macOS: o pacote padrão já traz o MPS
        self.assertIn("/whl/cu126", fw.torch_command("nvidia", "Linux", "cu126"))

    def test_tf_command(self):
        self.assertIn("tensorflow[and-cuda]", fw.tf_command("Linux", True))
        self.assertEqual(fw.tf_command("Windows", True), "python -m pip install --upgrade tensorflow")
        self.assertEqual(fw.tf_command("Linux", False), "python -m pip install --upgrade tensorflow")


class InstallTests(unittest.TestCase):
    def test_tries_the_indexes_newest_first_until_one_works(self):
        calls = []

        def run(cmd):
            calls.append(cmd[-1])
            return 0 if cmd[-1].endswith("cu128") else 1
        r = fw.torch_install("nvidia", "Linux", run=run)
        self.assertEqual((r["ok"], r["index"], r["tried"]), (True, "cu128", ["cu130", "cu128"]))
        self.assertEqual(calls, ["https://download.pytorch.org/whl/cu130", "https://download.pytorch.org/whl/cu128"])
        self.assertIn("torch torchvision", r["command"])

    def test_gives_up_after_the_last_index(self):
        r = fw.torch_install("nvidia", "Windows", run=lambda cmd: 1)
        self.assertEqual((r["ok"], r["tried"]), (False, ["cu130", "cu128", "cu126"]))

    def test_macos_uses_the_default_package_and_amd_on_windows_the_cpu_one(self):
        seen = []
        fw.torch_install("apple", "Darwin", run=lambda cmd: seen.append(cmd) or 0)
        self.assertNotIn("--index-url", seen[0])
        r = fw.torch_install("amd", "Windows", run=lambda cmd: 0)
        self.assertEqual(r["index"], "cpu")

    def test_a_forced_index(self):
        r = fw.torch_install("nvidia", "Linux", index="cu126", run=lambda cmd: 0)
        self.assertEqual((r["index"], r["tried"]), ("cu126", ["cu126"]))
        with mock.patch.dict("os.environ", {"OPENFLOW_TORCH_INDEX": "nightly/cu130"}):
            self.assertEqual(fw.torch_install("nvidia", "Linux", run=lambda cmd: 0)["tried"], ["nightly/cu130"])


class TorchAdviceTests(unittest.TestCase):
    def adv(self, info, vendors, system="Linux"):
        return fw.torch_advice(info, vendors, system)

    def test_not_installed(self):
        a = self.adv({"installed": False}, ["nvidia"])
        self.assertEqual(a[0]["level"], "warn")
        self.assertTrue(a[0]["text_en"])
        self.assertIn("cu130", a[0]["command"])
        self.assertIn("/whl/cpu", self.adv({"installed": False}, [])[0]["command"])

    def test_broken_install(self):
        a = self.adv({"installed": True, "version": "2.15", "error": "OSError: libcudnn.so"}, ["nvidia"])
        self.assertEqual(a[0]["level"], "error")
        self.assertIn("libcudnn", a[0]["text"])
        self.assertIn("command", a[0])

    def test_gpu_in_use_is_ok(self):
        info = {"installed": True, "version": "2.15", "build": "CUDA 13.0", "cuda": True, "devices": [{"kind": "cuda", "name": "RTX 4060"}]}
        a = self.adv(info, ["nvidia"])
        self.assertEqual((a[0]["level"], len(a)), ("ok", 1))
        self.assertIn("RTX 4060", a[0]["text"])

    def test_the_windows_cpu_only_torch_with_an_nvidia_card(self):
        info = {"installed": True, "version": "2.15", "build": "CPU", "cuda": False, "devices": []}
        a = self.adv(info, ["nvidia"], "Windows")
        self.assertEqual(a[0]["level"], "warn")
        self.assertIn("versão só de CPU", a[0]["text"])
        self.assertIn("--index-url https://download.pytorch.org/whl/cu130", a[0]["command"])

    def test_a_cuda_build_that_does_not_see_the_card(self):
        a = self.adv({"installed": True, "version": "2.15", "build": "CUDA 13.0", "cuda": False, "devices": []}, ["nvidia"])
        self.assertIn("driver da NVIDIA", a[0]["text"])

    def test_amd_and_intel_and_apple(self):
        cpu = {"installed": True, "version": "2.15", "build": "CPU", "cuda": False, "devices": []}
        self.assertIn("rocm", self.adv(cpu, ["amd"], "Linux")[0]["command"])
        a = self.adv(cpu, ["amd"], "Windows")
        self.assertEqual((a[0]["level"], "command" in a[0]), ("info", False))
        self.assertIn("xpu", self.adv(cpu, ["intel"], "Linux")[0]["command"])
        self.assertEqual(self.adv({"installed": True, "version": "2.15", "build": "CPU", "mps": True, "devices": [{"kind": "mps", "name": "Apple GPU (MPS)"}]}, ["apple"], "Darwin")[0]["level"], "ok")
        self.assertEqual(self.adv(cpu, [], "Linux")[0]["level"], "ok")                         # sem placa: CPU é o esperado

    def test_best_device(self):
        self.assertEqual(fw.best_device({"cuda": True, "xpu": True}), "cuda")
        self.assertEqual(fw.best_device({"xpu": True}), "xpu")
        self.assertEqual(fw.best_device({"mps": True}), "mps")
        self.assertEqual(fw.best_device({}), "cpu")


class TfAdviceTests(unittest.TestCase):
    def test_not_installed(self):
        a = fw.tf_advice({"installed": False}, ["nvidia"], "Linux", (3, 13))
        self.assertEqual(a[0]["level"], "info")
        self.assertIn("and-cuda", a[0]["command"])
        a = fw.tf_advice({"installed": False}, [], "Linux", (3, 14))
        self.assertIn("3.14", a[0]["text"])
        self.assertNotIn("command", a[0])

    def test_gpu_states(self):
        ok = fw.tf_advice({"installed": True, "version": "2.21", "gpus": [{"name": "/physical_device:GPU:0"}]}, ["nvidia"], "Linux", (3, 13))
        self.assertEqual(ok[0]["level"], "ok")
        win = fw.tf_advice({"installed": True, "version": "2.21", "gpus": []}, ["nvidia"], "Windows", (3, 13))
        self.assertIn("WSL2", win[0]["text"])
        lin = fw.tf_advice({"installed": True, "version": "2.21", "gpus": []}, ["nvidia"], "Linux", (3, 13))
        self.assertEqual(lin[0]["level"], "warn")
        self.assertIn("and-cuda", lin[0]["command"])
        cpu = fw.tf_advice({"installed": True, "version": "2.21", "gpus": []}, [], "Linux", (3, 13))
        self.assertEqual(cpu[0]["level"], "ok")
        err = fw.tf_advice({"installed": True, "version": "2.21", "error": "ImportError: x"}, [], "Linux", (3, 13))
        self.assertEqual(err[0]["level"], "error")


class LibsTests(unittest.TestCase):
    def test_tensorflow_is_opt_in(self):
        from openflow import cli
        self.assertNotIn("tensorflow", cli._wanted_libs("all")[0])
        self.assertNotIn("tensorflow", cli._wanted_libs("")[0])
        self.assertEqual(cli._wanted_libs("tensorflow")[0], ["tensorflow"])
        self.assertIn("tensorflow", cli.LIBS)

    def test_every_advice_comes_in_both_languages(self):
        cpu = {"installed": True, "version": "2.15", "build": "CPU", "cuda": False, "devices": []}
        cases = [fw.torch_advice({"installed": False}, ["nvidia"], "Linux"), fw.torch_advice({"installed": True, "version": "1", "error": "x"}, [], "Windows"),
                 fw.torch_advice(cpu, ["nvidia", "amd", "intel", "apple"], "Linux"), fw.torch_advice(cpu, ["amd"], "Windows"), fw.torch_advice(cpu, [], "Linux"),
                 fw.tf_advice({"installed": False}, ["nvidia"], "Linux", (3, 13)), fw.tf_advice({"installed": False}, [], "Linux", (3, 14)), fw.tf_advice({"installed": True, "version": "2", "gpus": []}, ["nvidia"], "Windows", (3, 13)),
                 fw.tf_advice({"installed": True, "version": "2", "gpus": []}, ["nvidia"], "Linux", (3, 13)), fw.tf_advice({"installed": True, "version": "2", "gpus": [{"name": "g"}]}, [], "Linux", (3, 13))]
        for advice in cases:
            for a in advice:
                self.assertTrue(a["text"] and a["text_en"] and a["level"] in ("ok", "info", "warn", "error"), a)
                self.assertNotEqual(a["text"], a["text_en"])


class DetectTests(unittest.TestCase):
    def test_by_file_names(self):
        self.assertEqual(fw.detect(["config.json", "model.safetensors"]), ["pytorch"])
        self.assertEqual(fw.detect(["tf_model.h5", "config.json"]), ["tensorflow"])
        self.assertEqual(fw.detect(["saved_model.pb", "variables/variables.index"]), ["tensorflow"])
        self.assertEqual(fw.detect(["model.keras"]), ["tensorflow"])
        self.assertEqual(fw.detect(["pytorch_model.bin", "tf_model.h5", "flax_model.msgpack", "model.onnx"]), ["pytorch", "tensorflow", "jax", "onnx"])
        self.assertEqual(fw.detect(["a-Q4_K_M.gguf"]), ["gguf"])
        self.assertEqual(fw.detect(["README.md"]), [])

    def test_by_tags_and_library(self):
        self.assertEqual(fw.detect(tags=["transformers", "tf", "keras", "region:us"]), ["tensorflow"])
        self.assertEqual(fw.detect(tags=["pytorch", "jax"]), ["pytorch", "jax"])
        self.assertEqual(fw.detect(library="keras"), ["tensorflow"])
        self.assertEqual(fw.detect(library="tf-keras"), ["tensorflow"])
        self.assertEqual(fw.detect(["x.safetensors"], ["tf"]), ["pytorch", "tensorflow"])


class ProbeTests(unittest.TestCase):
    def test_not_installed(self):
        with mock.patch.object(fw, "dist_version", return_value=""):
            self.assertEqual(fw.torch_info(), {"installed": False})
            self.assertEqual(fw.tf_info(), {"installed": False, "keras": ""})

    def test_without_importing(self):
        with mock.patch.object(fw, "dist_version", return_value="2.15.0"):
            self.assertEqual(fw.torch_info(probe=False)["version"], "2.15.0")

    def fake_torch(self, cuda=False, mps=False, xpu=False, hip="", cu="13.0"):
        props = types.SimpleNamespace(name="RTX 4060", total_memory=8 * 1024 ** 3, major=8, minor=9)
        t = types.SimpleNamespace(__version__="2.15.0+cu130", version=types.SimpleNamespace(cuda=None if hip else cu, hip=hip or None),
                                  cuda=types.SimpleNamespace(is_available=lambda: cuda, device_count=lambda: 1, get_device_properties=lambda i: props),
                                  backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps)),
                                  xpu=types.SimpleNamespace(is_available=lambda: xpu, device_count=lambda: 1, get_device_name=lambda i: "Intel Arc A770", get_device_properties=lambda i: types.SimpleNamespace(total_memory=16 * 1024 ** 3)))
        return t

    def probe(self, **kw):
        with mock.patch.object(fw, "dist_version", return_value="2.15.0"), mock.patch.dict(sys.modules, {"torch": self.fake_torch(**kw)}):
            return fw.torch_info()

    def test_cuda_card(self):
        i = self.probe(cuda=True)
        self.assertEqual((i["cuda"], i["build"], i["devices"][0]["name"], i["devices"][0]["vram"], i["devices"][0]["capability"]), (True, "CUDA 13.0", "RTX 4060", 8 * 1024 ** 3, "8.9"))
        self.assertEqual(fw.best_device(i), "cuda")

    def test_rocm_card(self):
        i = self.probe(cuda=True, hip="6.4")
        self.assertEqual((i["build"], i["devices"][0]["kind"]), ("ROCm 6.4", "rocm"))

    def test_intel_and_apple_and_cpu(self):
        i = self.probe(xpu=True)
        self.assertEqual((fw.best_device(i), i["devices"][0]["name"]), ("xpu", "Intel Arc A770"))
        self.assertEqual(fw.best_device(self.probe(mps=True)), "mps")
        i = self.probe(cu="")
        self.assertEqual((i["build"], fw.best_device(i), i["devices"]), ("CPU", "cpu", []))

    def test_a_broken_install_is_reported_not_raised(self):
        with mock.patch.object(fw, "dist_version", return_value="2.15.0"), mock.patch.dict(sys.modules, {"torch": None}):
            i = fw.torch_info()
        self.assertTrue(i["installed"])
        self.assertIn("Error", i["error"])

    def test_report_joins_everything(self):
        with mock.patch.object(fw, "torch_info", return_value={"installed": False}), mock.patch.object(fw, "tf_info", return_value={"installed": False, "keras": ""}), mock.patch.object(fw, "vendors", return_value=["nvidia"]):
            r = fw.report()
        self.assertEqual(set(r), {"system", "machine", "python", "gpu_vendors", "torch", "tensorflow", "advice"})
        self.assertEqual(r["gpu_vendors"], ["nvidia"])
        self.assertEqual(r["advice"]["torch"][0]["level"], "warn")
        self.assertEqual(r["torch"]["device"], "")

    def test_vendors_never_raises(self):
        with mock.patch("openflow.util.gpu_list", side_effect=OSError("x")), mock.patch("openflow.native.gpu_info", side_effect=RuntimeError("x")):
            self.assertIsInstance(fw.vendors(), list)


@unittest.skipUnless(HAS_TORCH, "sem PyTorch")
class RealTorchProbe(unittest.TestCase):
    def test_real_probe(self):
        i = fw.torch_info()
        self.assertTrue(i["installed"])
        self.assertIn(i["build"].split()[0], ("CUDA", "ROCm", "CPU"))
        self.assertIn(fw.best_device(i), ("cuda", "xpu", "mps", "cpu"))


@unittest.skipUnless(HAS_TF, "sem TensorFlow")
class RealTfProbe(unittest.TestCase):
    def test_real_probe(self):
        i = fw.tf_info()
        self.assertTrue(i["installed"])
        self.assertRegex(i["version"], r"^\d+\.\d+")
        self.assertIsInstance(i["gpus"], list)


@unittest.skipUnless(HAS_TORCH and HAS_TF, "precisa do PyTorch e do TensorFlow")
class ImportOrderTests(unittest.TestCase):
    """O PyTorch e o TensorFlow juntos: importar o TensorFlow antes do `torch.export` derruba o processo («LLVM ERROR: inconsistency in registered CommandLine options»). `import_tensorflow` evita."""

    def run_py(self, code):
        return subprocess.run([sys.executable, "-W", "ignore", "-c", code], capture_output=True, text=True, timeout=240, env={**__import__("os").environ, "TF_CPP_MIN_LOG_LEVEL": "3"})

    def test_the_guarded_import_survives_torch_export_after_tensorflow(self):
        code = ("from openflow.canvas import frameworks as fw\nfw.import_tensorflow()\nimport torch\n"
                "class M(torch.nn.Module):\n    def forward(self, x):\n        return x * 2\n"
                "torch.export.export(M(), (torch.zeros(1, 3),))\nprint('ok')\n")
        r = self.run_py(code)
        self.assertEqual((r.returncode, r.stdout.strip().splitlines()[-1:]), (0, ["ok"]), r.stderr[-400:])


if __name__ == "__main__":
    unittest.main()
