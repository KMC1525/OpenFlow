"""v0.16: `flow update` instala sozinho o que falta para compilar (git, compilador) e depois instala/atualiza o sd-cli."""
import contextlib
import io
import os
import unittest
from unittest import mock

from openflow import cli
from openflow.canvas import sdcli
from openflow.providers import ProviderError


def run(cmds, which, root=False, tty=True, left=None, fail_last=False):
    """Roda `_install_build_tools` com um gerenciador de pacotes simulado. `left`: o que ainda falta depois dos comandos."""
    out, calls = io.StringIO(), []

    def fake_run(cmd, *a, **k):
        calls.append(list(cmd))
        return mock.Mock(returncode=1 if fail_last and cmd[-1] != "-qq" else 0)

    seq = iter(left if left is not None else [[]])
    with mock.patch.object(cli.shutil, "which", side_effect=lambda t: ("/usr/bin/" + t) if t in which else None), mock.patch.object(cli.subprocess, "run", side_effect=fake_run), \
            mock.patch.object(cli.sys, "platform", "linux"), mock.patch.object(cli.os, "name", "posix"), mock.patch.object(cli.os, "geteuid", return_value=0 if root else 1000, create=True), \
            mock.patch.object(cli.sys.stdin, "isatty", return_value=tty), mock.patch.object(cli, "_build_tools_missing", side_effect=lambda: next(seq, [])), contextlib.redirect_stdout(out):
        ok = cli._install_build_tools(cmds)
    return ok, calls, out.getvalue()


class InstallToolsTests(unittest.TestCase):
    def test_apt_installs_only_what_is_missing_with_sudo(self):
        ok, calls, out = run(["git", "compilador C/C++"], {"apt-get", "sudo"})
        self.assertTrue(ok)
        self.assertEqual(calls, [["sudo", "apt-get", "update", "-qq"], ["sudo", "apt-get", "install", "-y", "git", "build-essential"]])
        self.assertIn("pode pedir a sua senha", out)
        self.assertIn("sudo apt-get install -y git build-essential", out)
        _, calls, _ = run(["git"], {"apt-get", "sudo"})
        self.assertEqual(calls[-1], ["sudo", "apt-get", "install", "-y", "git"])          # só o git
        _, calls, _ = run(["compilador C/C++"], {"apt-get", "sudo"})
        self.assertEqual(calls[-1], ["sudo", "apt-get", "install", "-y", "build-essential"])

    def test_root_needs_no_sudo_and_a_script_without_a_terminal_never_waits_for_a_password(self):
        _, calls, _ = run(["git"], {"apt-get", "sudo"}, root=True)
        self.assertEqual(calls[-1][0], "apt-get")
        _, calls, _ = run(["git"], {"apt-get", "sudo"}, tty=False)
        self.assertEqual(calls[-1][:3], ["sudo", "-n", "apt-get"])

    def test_other_package_managers(self):
        both = ["git", "compilador C/C++"]
        self.assertEqual(run(both, {"dnf", "sudo"})[1][-1], ["sudo", "dnf", "install", "-y", "git", "gcc-c++", "make"])
        self.assertEqual(run(both, {"pacman", "sudo"})[1][-1], ["sudo", "pacman", "-S", "--noconfirm", "--needed", "git", "base-devel"])
        self.assertEqual(run(both, {"zypper", "sudo"})[1][-1], ["sudo", "zypper", "--non-interactive", "install", "git", "gcc-c++", "make"])
        self.assertEqual(run(both, {"apk"}, root=True)[1][-1], ["apk", "add", "git", "build-base"])

    def test_no_package_manager_or_no_sudo_explains_instead_of_failing(self):
        ok, calls, out = run(["git"], {"sudo"})
        self.assertFalse(ok)
        self.assertEqual(calls, [])
        self.assertIn("não reconheci o gerenciador de pacotes", out)
        ok, calls, out = run(["git"], {"apt-get"})
        self.assertFalse(ok)
        self.assertIn("não há o sudo", out)
        self.assertIn("apt-get install -y git", out)

    def test_a_failing_install_or_something_still_missing_returns_false(self):
        ok, _, out = run(["git"], {"apt-get", "sudo"}, fail_last=True)
        self.assertFalse(ok)
        self.assertIn("Não consegui instalar", out)
        ok, _, out = run(["git", "compilador C/C++"], {"apt-get", "sudo"}, left=[["compilador C/C++"]])
        self.assertFalse(ok)
        self.assertIn("Ainda falta: compilador C/C++", out)

    def test_macos_and_windows_only_explain(self):
        for plat, name in (("darwin", "posix"), ("win32", "nt")):
            out = io.StringIO()
            with mock.patch.object(cli.sys, "platform", plat), mock.patch.object(cli.os, "name", name), mock.patch.object(cli, "_build_tools_hint", return_value="xcode-select --install"), \
                    mock.patch.object(cli.subprocess, "run", side_effect=AssertionError("não deve rodar nada")), contextlib.redirect_stdout(out):
                self.assertFalse(cli._install_build_tools(["git"]))
            self.assertIn("Faltam ferramentas para compilar", out.getvalue())


class UpdateFlowTests(unittest.TestCase):
    def test_flow_update_turns_the_automatic_tools_on_and_core_or_the_opt_out_do_not(self):
        def seen(argv, env=None):
            got = {}

            def fake_run(cmd, *a, **k):
                if cmd[-1] == "libs":
                    got["tools"] = os.environ.get("OPENFLOW_AUTO_TOOLS")
                return mock.Mock(returncode=0)

            with mock.patch.dict(os.environ, env or {}, clear=False), mock.patch.object(cli.subprocess, "run", side_effect=fake_run), mock.patch.object(cli, "_ensure_pip", return_value=True), \
                    mock.patch.object(cli, "_remote_version", return_value="0.0.1"), mock.patch.object(cli, "_managed_app_dir", return_value=None), contextlib.redirect_stdout(io.StringIO()):
                if not env:
                    os.environ.pop("OPENFLOW_AUTO_TOOLS", None)
                cli.main(argv)
            return got.get("tools")

        self.assertEqual(seen(["update", "--no-python"]), "yes")
        self.assertIsNone(seen(["update", "--no-python", "--core"]))
        self.assertEqual(seen(["update", "--no-python"], {"OPENFLOW_AUTO_TOOLS": "0"}), "0")

    def test_the_library_build_installs_the_tools_first_when_allowed(self):
        import tempfile
        from pathlib import Path

        marker = Path(tempfile.mkdtemp()) / "sd_needs_newer"
        marker.write_text("x")
        state = {"installed": False}

        def missing():
            return [] if state["installed"] else ["git", "compilador C/C++"]

        def install(m):
            state["installed"] = True
            return True

        pips = []
        with mock.patch.object(cli, "_build_tools_missing", side_effect=missing), mock.patch.object(cli, "_install_build_tools", side_effect=install) as inst, mock.patch.object(cli, "_sd_dir", return_value=marker.parent), \
                mock.patch.object(cli, "_sd_remote_sha", return_value="abc"), mock.patch.object(cli.subprocess, "run", side_effect=lambda cmd, *a, **k: pips.append(cmd) or mock.Mock(returncode=0)), contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.dict(os.environ, {"OPENFLOW_AUTO_TOOLS": "yes"}):
                self.assertTrue(cli._sd_latest(False))
            self.assertTrue(any(cli.SD_GIT in c for call in pips for c in call))              # com as ferramentas instaladas, compilou
            inst.assert_called_once()
            state["installed"] = False
            marker.write_text("x")   # a compilação bem-sucedida apaga o aviso: recria para pedir de novo
            (marker.parent / "sd_built_sha").unlink(missing_ok=True)
            pips.clear()
            inst.reset_mock()
            with mock.patch.dict(os.environ, {"OPENFLOW_AUTO_TOOLS": "0"}):
                self.assertFalse(cli._sd_latest(False))                                      # opt-out: só avisa
            inst.assert_not_called()
            self.assertFalse(any(cli.SD_GIT in c for call in pips for c in call))


class SdCliInstallTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.tmp = Path(tempfile.mkdtemp())
        os.environ["OPENFLOW_HOME"] = str(self.tmp)
        self.addCleanup(os.environ.pop, "OPENFLOW_HOME", None)

    def test_missing_tools_are_installed_and_the_cli_install_is_retried_once(self):
        attempts = []

        def install(**k):
            attempts.append(1)
            if len(attempts) == 1:
                raise sdcli.BuildToolsMissing("Para compilar o sd-cli aqui falta: git.")

        with mock.patch.object(sdcli, "install", side_effect=install), mock.patch.object(cli, "_install_build_tools", return_value=True) as tools, mock.patch.dict(os.environ, {"OPENFLOW_AUTO_TOOLS": "yes"}), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertTrue(cli._sd_cli_install())
        self.assertEqual(len(attempts), 2)
        tools.assert_called_once()
        attempts.clear()
        with mock.patch.object(sdcli, "install", side_effect=sdcli.BuildToolsMissing("falta git")), mock.patch.object(cli, "_install_build_tools", return_value=False), \
                mock.patch.dict(os.environ, {"OPENFLOW_AUTO_TOOLS": "yes"}), contextlib.redirect_stdout(io.StringIO()) as out2:
            self.assertFalse(cli._sd_cli_install())
        self.assertIn("Não consegui instalar o sd-cli", out2.getvalue())
        with mock.patch.object(sdcli, "install", side_effect=ProviderError("sem rede")), contextlib.redirect_stdout(io.StringIO()) as out3:
            self.assertFalse(cli._sd_cli_install())
        self.assertIn("sem rede", out3.getvalue())

    def test_refresh_installs_a_missing_cli_only_in_flow_update_and_updates_an_old_one(self):
        with mock.patch.object(cli, "_sd_cli_install", return_value=True) as inst, contextlib.redirect_stdout(io.StringIO()):
            cli._sd_cli_refresh()                       # fora do flow update: nunca baixou, não baixa à toa
            inst.assert_not_called()
            cli._sd_cli_refresh(install_missing=True)   # no flow update, para quem tem modelos que precisam dele
            inst.assert_called_once()
            inst.reset_mock()
            sdcli.bin_dir().mkdir(parents=True)
            (sdcli.bin_dir() / "VERSION").write_text("master-1")
            with mock.patch.object(sdcli, "latest_release", return_value={"tag_name": "master-2"}):
                cli._sd_cli_refresh()
            inst.assert_called_once()                   # versão nova: instala/compila de novo
            inst.reset_mock()
            with mock.patch.object(sdcli, "latest_release", return_value={"tag_name": "master-1"}):
                cli._sd_cli_refresh()
            inst.assert_not_called()

    def test_the_node_error_points_to_flow_update(self):
        with mock.patch.object(sdcli, "build_tools_missing", return_value=["git"]):
            with self.assertRaises(sdcli.BuildToolsMissing) as cm:
                sdcli.build_from_source()
        self.assertIn("flow update", str(cm.exception))
        self.assertIn("instala o que falta sozinho", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
