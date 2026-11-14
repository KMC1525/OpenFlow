"""O sd-cli pré-compilado da stable-diffusion.cpp: escolha do arquivo da Release, download/instalação (simulados), linha de comando e o uso como saída quando a biblioteca Python não reconhece o modelo."""
import io
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow.canvas import media as M  # noqa: E402
from openflow.canvas import sdcli  # noqa: E402
from openflow.providers import ProviderError  # noqa: E402
from tests.test_canvas import PNG  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402

ASSETS = [{"name": n, "size": 1000, "browser_download_url": "https://example.invalid/" + n} for n in (
    "sd-master-abc1234-bin-Linux-Ubuntu-24.04-x86_64.zip", "sd-master-abc1234-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip", "sd-master-abc1234-bin-Linux-Ubuntu-24.04-x86_64-rocm-10.1.0.zip",
    "sd-master-abc1234-bin-Darwin-macOS-15.1-arm64.zip", "sd-master-abc1234-bin-win-cpu-x64.zip", "sd-master-abc1234-bin-win-cuda12-x64.zip", "sd-master-abc1234-bin-win-vulkan-x64.zip",
    "cudart-sd-bin-win-cu12-x64.zip")]

FAKE_CLI = """#!{py}
import shutil, sys
a = sys.argv[1:]
if "-h" in a:
    print("usage: sd-cli [options]  --diffusion-model PATH")
    sys.exit(0)
out = a[a.index("-o") + 1]
open(out.replace("%05d", "00001").replace("%03d", "001") if "%0" in out else out, "wb").write(open({png!r}, "rb").read())
open({log!r}, "w").write("\\n".join(a))
"""


class PickAssetTests(unittest.TestCase):
    def test_each_system_gets_its_own_release_file(self):
        names = lambda s, m, w="cpu": (sdcli.pick_asset(ASSETS, s, m, w) or {}).get("name")  # noqa: E731
        self.assertEqual(names("Linux", "x86_64"), "sd-master-abc1234-bin-Linux-Ubuntu-24.04-x86_64.zip")
        self.assertEqual(names("Linux", "x86_64", "vulkan"), "sd-master-abc1234-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip")
        self.assertIsNone(names("Linux", "aarch64"))   # a Release não traz ARM: avisa em vez de baixar o errado
        self.assertEqual(names("Darwin", "arm64"), "sd-master-abc1234-bin-Darwin-macOS-15.1-arm64.zip")
        self.assertIsNone(names("Darwin", "x86_64"))
        self.assertEqual(names("Windows", "AMD64"), "sd-master-abc1234-bin-win-cpu-x64.zip")
        self.assertEqual(names("Windows", "AMD64", "cuda"), "sd-master-abc1234-bin-win-cuda12-x64.zip")
        self.assertEqual(names("Windows", "AMD64", "vulkan"), "sd-master-abc1234-bin-win-vulkan-x64.zip")
        self.assertIsNone(names("FreeBSD", "x86_64"))

    def test_backend_comes_from_the_environment_and_defaults_to_cpu(self):
        with mock.patch.dict(os.environ, {"OPENFLOW_SD_BACKEND": "Vulkan"}):
            self.assertEqual(sdcli.backend(), "vulkan")
        with mock.patch.dict(os.environ, {"OPENFLOW_SD_BACKEND": "xpto"}):
            self.assertEqual(sdcli.backend(), "cpu")


class BuildArgsTests(unittest.TestCase):
    def test_load_and_run_parameters_become_sd_cli_options(self):
        exe = Path("/x/sd-cli")
        load = {"diffusion_model_path": "/m/model.gguf", "vae_path": "/m/vae.safetensors", "llm_path": "/m/llm.gguf", "offload_params_to_cpu": True, "diffusion_flash_attn": True, "estranho": 1}
        args, warns = sdcli.build_args(exe, load, {"cfg_scale": 1.0, "sample_steps": 4, "sample_method": "euler", "outra": 3}, prompt="um gato", width=1024, height=576, seed=7, negative="feio",
                                       refs=[Path("/t/r0.png"), Path("/t/r1.png")], out=Path("/t/out.png"))
        self.assertEqual(args[:3], ["/x/sd-cli", "-M", "img_gen"])
        pairs = {args[i]: args[i + 1] for i in range(len(args) - 1)}
        self.assertEqual((pairs["--diffusion-model"], pairs["--vae"], pairs["--llm"], pairs["--cfg-scale"], pairs["--steps"], pairs["--sampling-method"]), ("/m/model.gguf", "/m/vae.safetensors", "/m/llm.gguf", "1.0", "4", "euler"))
        self.assertEqual((pairs["-W"], pairs["-H"], pairs["-s"], pairs["-n"], pairs["-p"]), ("1024", "576", "7", "feio", "um gato"))
        self.assertEqual([args[i + 1] for i, a in enumerate(args) if a == "-r"], ["/t/r0.png", "/t/r1.png"])   # várias referências: -r repetido
        self.assertIn("--offload-to-cpu", args)
        self.assertEqual(sorted(warns), ["estranho", "outra"])
        v, _ = sdcli.build_args(exe, {}, {"video_frames": 73, "fps": 24}, prompt="x", width=1280, height=704, seed=1, out=Path("/t/f_%05d.png"), video=True)
        self.assertEqual(v[1:3], ["-M", "vid_gen"])
        self.assertIn("--video-frames", v)


@unittest.skipIf(os.name == "nt", "o executável de teste é um script POSIX")
class InstallAndUseTests(TmpCase):
    def fake_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("sd-cli", FAKE_CLI.format(py=sys.executable, png=str(self.tmp / "out.png"), log=str(self.tmp / "args.log")))
            z.writestr("libggml.so", b"x")
        return buf.getvalue()

    def setUp(self):
        super().setUp()
        (self.tmp / "out.png").write_bytes(PNG)
        self.patch = mock.patch.dict(os.environ, {"OPENFLOW_HOME": str(self.tmp / "home")})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def install(self):
        data = self.fake_zip()

        def fake_download(url, dest, progress, cancelled):
            dest.write_bytes(data)
            if progress:
                progress(len(data), len(data))

        notes = []
        with mock.patch.object(sdcli, "latest_release", return_value={"tag_name": "master-1-abc1234", "assets": ASSETS}), mock.patch.object(sdcli, "_download", fake_download), \
                mock.patch("platform.system", return_value="Linux"), mock.patch("platform.machine", return_value="x86_64"):
            exe = sdcli.install(note=notes.append)
        return exe, notes

    def test_install_extracts_marks_executable_probes_and_remembers_the_version(self):
        exe, notes = self.install()
        self.assertEqual(exe.name, "sd-cli")
        self.assertTrue(exe.stat().st_mode & stat.S_IXUSR)
        self.assertEqual(sdcli.find(), exe)
        self.assertEqual((exe.parent / "VERSION").read_text(), "master-1-abc1234")
        self.assertTrue(any("sd-master-abc1234-bin-Linux" in n for n in notes))

    def test_install_without_a_release_file_for_this_system_explains(self):
        with mock.patch.object(sdcli, "latest_release", return_value={"tag_name": "t", "assets": ASSETS}), mock.patch("platform.system", return_value="Linux"), mock.patch("platform.machine", return_value="riscv64"):
            with self.assertRaises(ProviderError) as cm:
                sdcli.install()
        self.assertIn("Não há executável pronto", str(cm.exception))

    def test_a_download_that_breaks_the_probe_is_reported(self):
        with zipfile.ZipFile(io.BytesIO(), "w"):
            pass
        bad = io.BytesIO()
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("sd-cli", "#!/bin/sh\nexit 3\n")

        def fake_download(url, dest, progress, cancelled):
            dest.write_bytes(bad.getvalue())

        with mock.patch.object(sdcli, "latest_release", return_value={"tag_name": "t", "assets": ASSETS}), mock.patch.object(sdcli, "_download", fake_download), \
                mock.patch("platform.system", return_value="Linux"), mock.patch("platform.machine", return_value="x86_64"):
            with self.assertRaises(ProviderError) as cm:
                sdcli.install()
        self.assertIn("não roda", str(cm.exception))

    def provider(self, name):
        (self.tmp / "image").mkdir(exist_ok=True)
        for n in (name, "flux2-vae.safetensors", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "qwen_3_4b.gguf"):
            (self.tmp / "image" / n).write_bytes(b"x")
        M._LOCAL_CACHE.clear()
        return M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {"image": name}, "needs_key": False})

    def test_an_unrecognized_model_is_generated_by_the_cli_when_it_is_installed(self):
        exe, _ = self.install()
        p = self.provider("flux-2-klein-4b-Q4_K_M.gguf")
        notes = []
        p.ctl = mock.MagicMock(note=notes.append, check=lambda: None)
        with mock.patch.object(M.GGUFMedia, "_engine", side_effect=M._SDUnsupportedModel("get sd version from file failed")):
            out = p.image("uma thumb", size="1280x720", seed=5, refs=[(PNG, "image/png"), (PNG, "image/png")])
        self.assertEqual(out[0].data, PNG)
        args = (self.tmp / "args.log").read_text().split("\n")
        self.assertEqual(args.count("-r"), 2)   # klein junta as duas referências
        self.assertEqual(args[args.index("--steps") + 1], "4")
        self.assertEqual((args[args.index("-W") + 1], args[args.index("-H") + 1]), ("1024", "576"))   # o tamanho pedido, não o da foto
        self.assertTrue(any("sd-cli" in n for n in notes))

    def test_without_the_cli_the_error_offers_the_download_before_compiling(self):
        p = self.provider("flux-2-klein-4b-Q4_K_M.gguf")
        with mock.patch.object(M.GGUFMedia, "_engine", side_effect=M._SDUnsupportedModel("A stable-diffusion.cpp instalada não reconhece o modelo [[flow-sd-cli]] [[flow-sd-update]]")), \
                mock.patch.object(sdcli, "find", return_value=None):
            with self.assertRaises(M._SDUnsupportedModel) as cm:
                p.image("x")
        self.assertIn("[[flow-sd-cli]]", str(cm.exception))

    def test_wan_video_through_the_cli_uses_720p_and_assembles_the_frames(self):
        from PIL import Image  # noqa: F401

        exe, _ = self.install()
        (self.tmp / "video").mkdir(exist_ok=True)
        for n in ("Wan2.2-TI2V-5B-Q4_K_M.gguf", "Wan2.2_VAE.safetensors", "umt5-xxl-encoder-Q4_K_M.gguf"):
            (self.tmp / "video" / n).write_bytes(b"x")
        M._LOCAL_CACHE.clear()
        p = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {"video": "Wan2.2-TI2V-5B-Q4_K_M.gguf"}, "needs_key": False})
        p.ctl = mock.MagicMock(note=lambda m: None, check=lambda: None)
        with mock.patch.object(M.GGUFMedia, "_engine", side_effect=M._SDUnsupportedModel("x")), mock.patch.object(M, "_frames_to_mp4", return_value=M.Media(b"mp4", "video/mp4")) as mp4:
            out = p.video("uma raposa", duration=3, aspect="16:9")
        self.assertEqual(out.mime, "video/mp4")
        args = (self.tmp / "args.log").read_text().split("\n")
        self.assertEqual((args[args.index("-M") + 1], args[args.index("-W") + 1], args[args.index("-H") + 1], args[args.index("--video-frames") + 1]), ("vid_gen", "1280", "704", "73"))
        self.assertEqual(mp4.call_args[0][1], 24)


if __name__ == "__main__":
    unittest.main()


class NeedCompanionsTests(TmpCase):
    def test_flux2_klein_without_vae_and_llm_asks_for_support_files_instead_of_running_sd_cli(self):
        folder = self.tmp / "image"
        folder.mkdir()
        model = folder / "flux-2-klein-4b-Q4_K_M.gguf"
        model.write_bytes(b"x")
        with self.assertRaises(ProviderError) as cm:
            M.GGUFMedia._need_companions(model, {})
        self.assertIn("flow-support:flux-2-klein-4b-Q4_K_M.gguf", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


class AutoCliTests(unittest.TestCase):
    """Modelo que a biblioteca não reconhece («get sd version from file failed», ex.: FLUX.3 Klein): o OpenFlow baixa o sd-cli sozinho e segue."""

    def provider(self):
        from openflow.canvas import media as M

        notes = []
        p = M.GGUFMedia.__new__(M.GGUFMedia)
        p.ctl = M.Ctl(note=notes.append)
        p._cancelled = lambda: False
        return M, p, notes

    def test_downloads_the_cli_once_and_then_uses_it(self):
        M, p, notes = self.provider()
        state = {"exe": None, "installs": 0}

        def install(progress, cancelled, note):
            state["installs"] += 1
            state["exe"] = Path("/tmp/sd-cli")
            return state["exe"]

        with mock.patch.object(M.sdcli, "find", lambda: state["exe"]), mock.patch.object(M.sdcli, "install", install), mock.patch.object(M, "_media_unload", lambda: None):
            self.assertTrue(p._cli_fallback(M._SDUnsupportedModel("get sd version from file failed")))
            self.assertTrue(p._cli_fallback(M._SDUnsupportedModel("de novo")))
        self.assertEqual(state["installs"], 1)
        self.assertTrue(any("baixando o sd-cli" in n for n in notes))

    def test_other_errors_and_the_off_switch_do_not_download(self):
        M, p, _ = self.provider()
        with mock.patch.object(M.sdcli, "find", lambda: None), mock.patch.object(M.sdcli, "install", side_effect=AssertionError("não devia baixar")):
            self.assertFalse(p._cli_fallback(M._SDLoadError("sem memória")))
            with mock.patch.dict("os.environ", {"OPENFLOW_SD_CLI_AUTO": "0"}):
                self.assertFalse(p._cli_fallback(M._SDUnsupportedModel("x")))

    def test_a_failed_download_keeps_the_button_message(self):
        M, p, notes = self.provider()
        with mock.patch.object(M.sdcli, "find", lambda: None), mock.patch.object(M.sdcli, "install", side_effect=M.ProviderError("sem rede")):
            self.assertFalse(p._cli_fallback(M._SDUnsupportedModel("x")))
        self.assertTrue(any("use o botão do nó" in n for n in notes))


class RememberedUnsupportedTests(TmpCase):
    def test_a_refused_model_goes_straight_to_the_cli_next_time(self):
        os.environ["OPENFLOW_HOME"] = str(self.tmp)
        try:
            self.assertFalse(M._lib_unsupported("flux-3-image-klein-Q4_K_M.gguf"))
            M._mark_lib_unsupported("flux-3-image-klein-Q4_K_M.gguf")
            M._mark_lib_unsupported("flux-3-image-klein-Q4_K_M.gguf")
            self.assertTrue(M._lib_unsupported("flux-3-image-klein-Q4_K_M.gguf"))
            self.assertFalse(M._lib_unsupported("outro.gguf"))
            self.assertEqual((self.tmp / "sd_unsupported.txt").read_text().splitlines(), ["flux-3-image-klein-Q4_K_M.gguf"])    # sem repetir
        finally:
            os.environ.pop("OPENFLOW_HOME", None)


class DeviceChoiceTests(TmpCase):
    """Configurações → Desempenho → Rodar em: automático, só CPU ou GPU."""

    def setUp(self):
        super().setUp()
        from openflow import perf

        self.perf = perf
        self.addCleanup(perf.configure, {})
        self.addCleanup(os.environ.pop, "OPENFLOW_SD_BACKEND", None)
        os.environ.pop("OPENFLOW_SD_BACKEND", None)

    def pick(self, device, nvidia, system="Linux"):
        self.perf.configure({"device": device})
        with mock.patch.object(sdcli, "_nvidia", lambda: nvidia), mock.patch.object(sdcli.platform, "system", lambda: system):
            return sdcli.backend()

    def test_backend_follows_the_setting(self):
        self.assertEqual(self.pick("cpu", True), "cpu")                 # só CPU nunca usa a placa, mesmo com NVIDIA
        self.assertEqual(self.pick("auto", True), "cuda12")
        self.assertEqual(self.pick("auto", False), "cpu")
        self.assertEqual(self.pick("gpu", True), "cuda12")
        self.assertEqual(self.pick("gpu", False), "vulkan")             # AMD/Intel
        self.assertEqual(self.pick("gpu", False, "Darwin"), "cpu")      # macOS: o executável padrão já usa a placa (Metal)
        self.assertEqual(self.perf.device(), "gpu")

    def test_invalid_value_is_automatic_and_the_environment_wins(self):
        self.perf.configure({"device": "quantum"})
        self.assertEqual(self.perf.device(), "auto")
        os.environ["OPENFLOW_SD_BACKEND"] = "vulkan"
        self.perf.configure({"device": "cpu"})
        self.assertEqual(sdcli.backend(), "vulkan")

    def test_a_cli_of_another_kind_is_downloaded_again(self):
        os.environ["OPENFLOW_HOME"] = str(self.tmp)
        self.addCleanup(os.environ.pop, "OPENFLOW_HOME", None)
        sdcli.bin_dir().mkdir(parents=True)
        (sdcli.bin_dir() / "BACKEND").write_text("cpu")
        self.assertEqual(sdcli.installed_backend(), "cpu")
        notes, calls = [], []
        p = M.GGUFMedia.__new__(M.GGUFMedia)
        p.ctl, p._cancelled = M.Ctl(note=notes.append), (lambda: False)
        self.perf.configure({"device": "gpu"})
        with mock.patch.object(sdcli, "_nvidia", lambda: True), mock.patch.object(sdcli, "find", lambda: Path("/tmp/sd-cli")), mock.patch.object(M, "_media_unload", lambda: None), \
                mock.patch.object(sdcli, "install", lambda *a, **k: calls.append(sdcli.backend())):
            self.assertTrue(p._cli_fallback(M._SDUnsupportedModel("x")))
        self.assertEqual(calls, ["cuda12"])

    def test_the_setting_is_saved_and_normalized(self):
        from openflow.storage import Store

        st = Store(self.tmp)
        self.assertEqual(st.get_settings()["performance"]["device"], "auto")
        st.save_settings({"performance": {"device": "cpu"}})
        self.assertEqual(st.get_settings()["performance"]["device"], "cpu")


class QuietAndDirectTests(TmpCase):
    def test_flux3_goes_straight_to_the_cli_and_the_version_error_is_not_echoed(self):
        self.assertTrue(M._lib_never_knows("flux-3-image-klein-Q4_K_M.gguf"))
        self.assertTrue(M._lib_never_knows("FLUX.3-dev-Q8_0.gguf"))
        self.assertFalse(M._lib_never_knows("flux-2-klein-4b-Q4_K_M.gguf"))
        with mock.patch.dict(os.environ, {"OPENFLOW_SD_INPROC": "1"}):
            self.assertFalse(M._lib_never_knows("flux-3-image-klein-Q4_K_M.gguf"))
        import contextlib

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            M._echo(3, "stable-diffusion.cpp:299  - get sd version from file failed: ''")
            M._echo(1, "loading vae")
            M._echo(0, "debug")
        self.assertEqual(err.getvalue().strip(), "loading vae")
