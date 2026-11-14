"""v0.15: quando nenhum executável pronto roda neste Linux (glibc antiga), o OpenFlow compila o sd-cli aqui."""
import os
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import sdcli
from openflow.providers import ProviderError
from tests.helpers import TmpCase

U26 = "sd-master-abc-bin-Linux-Ubuntu-26.04-x86_64.zip"


class BuildTests(TmpCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"OPENFLOW_HOME": str(self.tmp), "OPENFLOW_SD_CLI_BUILD": "1"})   # aqui a compilação está ligada (as simulações impedem o git/cmake de verdade)
        env.start()
        self.addCleanup(env.stop)
        self.steps = []
        stack = [mock.patch.object(sdcli.platform, "system", return_value="Linux"), mock.patch.object(sdcli.platform, "machine", return_value="x86_64"),
                 mock.patch.object(sdcli, "sys_platform", return_value="linux"), mock.patch.object(sdcli, "backend", return_value="cpu"),
                 mock.patch.object(sdcli, "glibc_version", return_value=(2, 39)), mock.patch.object(sdcli, "build_tools_missing", return_value=[]),
                 mock.patch.object(sdcli, "_cmake", return_value=["cmake"]), mock.patch.object(sdcli, "_run_build", self.fake_build),
                 mock.patch.object(sdcli, "latest_release", return_value={"tag_name": "master-1104-5dcfa79", "assets": [{"name": U26, "size": 1, "browser_download_url": "https://x/" + U26}]})]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)

    def fake_build(self, cmd, cwd, cancelled, note, label, timeout=3600):
        self.steps.append((label, list(cmd)))
        if cmd[0] == "git":                                   # o «clone»: cria a pasta do código
            Path(cmd[-1]).mkdir(parents=True)
        elif "--build" in cmd:                                # a «compilação»: gera o executável e as bibliotecas
            work = Path(cmd[cmd.index("--build") + 1]).parent
            out = work / "build" / "bin"
            out.mkdir(parents=True)
            (out / sdcli.EXE).write_text("#!/bin/sh\necho usage: sd-cli --diffusion-model\n")
            (work / "build" / "libstable-diffusion.so").write_text("lib")
            (out / "libggml-base.so.0").write_text("lib")
            (work / "build" / "CMakeFiles").mkdir()
            (work / "build" / "CMakeFiles" / "libnao.so").write_text("lixo")

    def test_when_every_prebuilt_package_needs_a_newer_glibc_the_cli_is_built_here(self):
        notes = []
        with mock.patch.object(sdcli, "_probe", return_value=(True, "")):
            exe = sdcli.install(note=notes.append)
        self.assertEqual(exe, sdcli.bin_dir() / sdcli.EXE)
        self.assertEqual([lab for lab, _ in self.steps], ["Baixando o código-fonte", "Configurando", "Compilando"])
        self.assertIn("-DSD_BUILD_EXAMPLES=ON", self.steps[1][1])
        self.assertNotIn("-DSD_CUDA=ON", self.steps[1][1])
        self.assertEqual(sorted(p.name for p in sdcli.bin_dir().iterdir()), sorted([sdcli.EXE, "BACKEND", "VERSION", "libggml-base.so.0", "libstable-diffusion.so"]))   # só as bibliotecas de verdade
        self.assertEqual((sdcli.bin_dir() / "VERSION").read_text(), "master-1104-5dcfa79")
        self.assertEqual((sdcli.bin_dir() / "BACKEND").read_text(), "cpu")
        self.assertTrue(any("vai compilar o sd-cli aqui" in n for n in notes))
        self.assertFalse((sdcli.bin_dir().parent / "sd-src").exists())              # o código-fonte é apagado
        self.assertEqual(sdcli.find(), sdcli.bin_dir() / sdcli.EXE)                  # e o executável passa a ser usado

    def test_a_build_that_does_not_run_never_replaces_the_installed_cli(self):
        sdcli.bin_dir().mkdir(parents=True)
        (sdcli.bin_dir() / sdcli.EXE).write_text("antigo")
        (sdcli.bin_dir() / "VERSION").write_text("v0")
        with mock.patch.object(sdcli, "_probe", return_value=(False, "erro")):
            with self.assertRaises(ProviderError) as cm:
                sdcli.install()
        self.assertIn("não roda", str(cm.exception))
        self.assertEqual((sdcli.bin_dir() / sdcli.EXE).read_text(), "antigo")

    def test_missing_build_tools_are_named_with_the_command_to_install_them(self):
        with mock.patch.object(sdcli, "build_tools_missing", return_value=["compilador C/C++"]), mock.patch.object(sdcli, "build_tools_hint", return_value="sudo apt install git build-essential"):
            with self.assertRaises(ProviderError) as cm:
                sdcli.install()
        self.assertIn("compilador C/C++", str(cm.exception))
        self.assertIn("sudo apt install git build-essential", str(cm.exception))
        self.assertEqual(self.steps, [])                                           # nada foi baixado à toa

    def test_the_build_can_be_turned_off_and_then_the_old_message_stays(self):
        with mock.patch.dict(os.environ, {"OPENFLOW_SD_CLI_BUILD": "0"}):
            with self.assertRaises(ProviderError) as cm:
                sdcli.install()
        self.assertIn("glibc 2.43", str(cm.exception))
        self.assertIn("2.39", str(cm.exception))
        self.assertEqual(self.steps, [])

    def test_the_gpu_backend_is_built_only_when_its_tools_exist(self):
        with mock.patch.object(sdcli, "backend", return_value="cuda12"), mock.patch.object(sdcli.shutil, "which", side_effect=lambda n: "/usr/bin/nvcc" if n == "nvcc" else None), \
                mock.patch.object(sdcli, "_probe", return_value=(True, "")):
            sdcli.install()
        self.assertIn("-DSD_CUDA=ON", self.steps[1][1])
        self.assertEqual((sdcli.bin_dir() / "BACKEND").read_text(), "cuda12")
        self.steps.clear()
        notes = []
        with mock.patch.object(sdcli, "backend", return_value="cuda12"), mock.patch.object(sdcli.shutil, "which", return_value=None), mock.patch.object(sdcli, "_probe", return_value=(True, "")):
            sdcli.install(note=notes.append)
        self.assertNotIn("-DSD_CUDA=ON", self.steps[1][1])                           # sem nvcc: compila para CPU e avisa
        self.assertTrue(any("faltam as ferramentas da GPU" in n for n in notes))


class RunBuildTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "usa o sh")
    def test_progress_lines_are_reported_failures_explain_and_cancel_works(self):
        notes = []
        sdcli._run_build(["sh", "-c", "echo '[ 10%] Building a.o'; echo '[ 90%] Linking'"], None, lambda: False, notes.append, "Compilando")
        self.assertTrue(notes and notes[0].startswith("Compilando: "))
        with self.assertRaises(ProviderError) as cm:
            sdcli._run_build(["sh", "-c", "echo 'erro: arquivo.h não existe'; exit 3"], None, lambda: False, lambda m: None, "Compilando")
        self.assertIn("código 3", str(cm.exception))
        self.assertIn("arquivo.h", str(cm.exception))
        with self.assertRaises(ProviderError) as cm:
            sdcli._run_build(["sh", "-c", "echo x; sleep 5"], None, lambda: True, lambda m: None, "Compilando")
        self.assertEqual(str(cm.exception), "cancelado")


if __name__ == "__main__":
    unittest.main()
