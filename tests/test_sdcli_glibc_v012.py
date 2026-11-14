"""v0.12: o sd-cli baixado precisa rodar neste Linux: pacote escolhido pela glibc, testado antes de trocar e removido se não roda."""
import os
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import sdcli
from openflow.providers import ProviderError
from tests.helpers import TmpCase


def assets(*names):
    return [{"name": n, "size": 1000, "browser_download_url": "https://example.invalid/" + n} for n in names]


U22 = "sd-master-abc-bin-Linux-Ubuntu-22.04-x86_64.zip"
U24 = "sd-master-abc-bin-Linux-Ubuntu-24.04-x86_64.zip"
U26 = "sd-master-abc-bin-Linux-Ubuntu-26.04-x86_64.zip"
U24V = "sd-master-abc-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip"


class GlibcPickTests(unittest.TestCase):
    def test_the_package_must_fit_the_glibc_of_this_linux(self):
        a = assets(U26, U24, U22, U24V)
        pick = lambda g, w="cpu": [x["name"] for x in sdcli.pick_assets(a, "Linux", "x86_64", w, g)]   # noqa: E731
        self.assertEqual(pick((2, 43)), [U26, U24, U22])                  # glibc nova: o mais novo primeiro
        self.assertEqual(pick((2, 39)), [U24, U22])                       # o caso do usuário (Ubuntu 24.04): o pacote do 26.04 (glibc 2.43) fica de fora
        self.assertEqual(pick((2, 35)), [U22])
        self.assertEqual(pick((2, 31)), [])                               # nada serve: a mensagem de erro explica
        self.assertEqual(pick((2, 39), "vulkan"), [U24V, U24, U22])
        self.assertEqual(sdcli.pick_asset(a, "Linux", "x86_64", "cpu", (2, 39))["name"], U24)
        self.assertEqual(pick(None)[0], U26)                              # glibc desconhecida: como antes
        self.assertEqual(sdcli.asset_glibc("sd-x-bin-Linux-Ubuntu-28.04-x86_64.zip"), (2, 45))   # versão fora da tabela: assume uma glibc ainda mais nova
        self.assertIsNone(sdcli.asset_glibc("sd-master-abc-bin-Darwin-macOS-15.1-arm64.zip"))

    def test_glibc_errors_are_recognised_and_explained(self):
        txt = "/x/sd-cli: /lib/x86_64-linux-gnu/libm.so.6: version `GLIBC_2.43' not found (required by /x/libstable-diffusion.so)"
        with mock.patch.object(sdcli, "glibc_version", return_value=(2, 39)):
            msg = sdcli.glibc_error(txt)
        self.assertIn("glibc 2.43", msg)
        self.assertIn("2.39", msg)
        self.assertEqual(sdcli.glibc_error("outro erro qualquer"), "")


class InstallSafetyTests(TmpCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"OPENFLOW_HOME": str(self.tmp), "OPENFLOW_SD_CLI_BUILD": "0"})   # SEM compilar (a compilação tem os testes da v0.15); restaura o ambiente ao fim
        env.start()
        self.addCleanup(env.stop)

    def fake(self, names, probe):
        from openflow import archives

        notes = []

        def download(url, dest, progress, cancelled):
            Path(dest).write_bytes(url.encode())

        def extract(zip_path, out, name):
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / sdcli.EXE).write_text("bin:" + Path(name).name)

        rel = {"tag_name": "master-abc", "assets": assets(*names)}
        stack = [mock.patch.object(sdcli, "latest_release", return_value=rel), mock.patch.object(sdcli, "_download", download), mock.patch.object(archives, "extract", extract),
                 mock.patch.object(sdcli, "_probe", probe), mock.patch.object(sdcli.platform, "system", return_value="Linux"), mock.patch.object(sdcli.platform, "machine", return_value="x86_64"),
                 mock.patch.object(sdcli, "backend", return_value="cpu")]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)
        return notes

    def test_a_package_that_does_not_run_is_skipped_and_the_next_one_is_installed(self):
        calls = []

        def probe(exe):
            calls.append(Path(exe).read_text())
            return (U22 in Path(exe).read_text(), "version `GLIBC_2.43' not found")

        notes = self.fake([U26, U22], probe)
        with mock.patch.object(sdcli, "glibc_version", return_value=(2, 43)):   # glibc nova: tenta o 26.04, falha no teste e cai para o 22.04
            exe = sdcli.install(note=notes.append)
        self.assertEqual(calls, ["bin:" + U26, "bin:" + U22])
        self.assertEqual(exe.read_text(), "bin:" + U22)
        self.assertTrue((sdcli.bin_dir() / "VERSION").is_file())
        self.assertTrue(any("tentando outro" in n for n in notes))

    def test_a_failing_package_never_replaces_the_installed_one_and_is_not_left_behind(self):
        sdcli.bin_dir().mkdir(parents=True)
        (sdcli.bin_dir() / sdcli.EXE).write_text("antigo")
        (sdcli.bin_dir() / "VERSION").write_text("velho")
        self.fake([U24], lambda exe: (False, "version `GLIBC_2.43' not found"))
        with mock.patch.object(sdcli, "glibc_version", return_value=(2, 39)):
            with self.assertRaises(ProviderError) as cm:
                sdcli.install()
        self.assertIn("2.43", str(cm.exception))
        self.assertEqual((sdcli.bin_dir() / sdcli.EXE).read_text(), "antigo")   # o que funcionava continua lá
        self.assertFalse(Path(str(sdcli.bin_dir()) + ".new").exists())

    def test_when_every_package_needs_a_newer_glibc_the_error_says_so(self):
        self.fake([U26], lambda exe: (True, ""))
        with mock.patch.object(sdcli, "glibc_version", return_value=(2, 35)):
            with self.assertRaises(ProviderError) as cm:
                sdcli.install()
        self.assertIn("glibc 2.43", str(cm.exception))
        self.assertIn("2.35", str(cm.exception))
        self.assertFalse(sdcli.bin_dir().exists())

    def test_an_unfinished_install_is_not_used(self):
        sdcli.bin_dir().mkdir(parents=True)
        (sdcli.bin_dir() / sdcli.EXE).write_text("quebrado")
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(sdcli.find())          # sem VERSION (não passou no teste): não serve
            (sdcli.bin_dir() / "VERSION").write_text("v1")
            self.assertEqual(sdcli.find().name, sdcli.EXE)

    @unittest.skipIf(os.name == "nt", "o executável de teste é um script POSIX")
    def test_a_glibc_failure_while_generating_removes_the_managed_cli(self):
        d = sdcli.bin_dir()
        d.mkdir(parents=True)
        exe = d / sdcli.EXE
        exe.write_text("#!/bin/sh\necho \"$0: /lib/libm.so.6: version \\`GLIBC_2.43' not found (required by x)\" >&2\nexit 1\n")
        exe.chmod(0o755)
        (d / "VERSION").write_text("v1")
        with self.assertRaises(ProviderError) as cm:
            sdcli.run([str(exe)], exe)
        self.assertIn("glibc 2.43", str(cm.exception))
        self.assertFalse(d.exists())                  # apagado: a próxima geração baixa o pacote compatível


class RetryTests(unittest.TestCase):
    def test_a_glibc_failure_downloads_the_compatible_cli_and_retries_once(self):
        from openflow.canvas import media as M

        p = M.GGUFMedia.__new__(M.GGUFMedia)
        notes = []
        p.ctl = M.Ctl(note=notes.append)
        clis = [Path("/x/sd-cli-quebrado"), Path("/y/sd-cli-novo")]
        used = []

        def fn(cli):
            used.append(cli)
            if cli.name.endswith("quebrado"):
                raise sdcli.GlibcError("O sd-cli baixado exige a glibc 2.43 e este Linux tem 2.39.")
            return "ok"

        with mock.patch.object(sdcli, "find", side_effect=lambda: clis[0] if not used else clis[1]), mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=True) as fb:
            self.assertEqual(p._cli_call(Path("m.gguf"), fn), "ok")
        self.assertEqual(used, clis)
        fb.assert_called_once()
        self.assertTrue(any("Baixando o pacote compatível" in n for n in notes))
        with mock.patch.object(sdcli, "find", return_value=clis[0]), mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False):
            with self.assertRaises(sdcli.GlibcError):   # sem como baixar outro: o erro explicativo chega ao nó
                p._cli_call(Path("m.gguf"), fn)


if __name__ == "__main__":
    unittest.main()
