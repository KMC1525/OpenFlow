"""v0.13: `flow update` sempre atualiza todas as bibliotecas para as versões mais novas (e o sd-cli e a stable-diffusion.cpp do GitHub)."""
import argparse
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow import cli
from tests.test_cli import pip_installs, run_cli


class UpdateAlwaysTests(unittest.TestCase):
    def update_env(self, argv):
        """O valor de OPENFLOW_SD_LATEST que o processo de `libs` herda quando se roda `flow update`."""
        seen = {}

        def fake_run(cmd, *a, **k):
            if cmd[-1] == "libs":
                seen["sd"] = os.environ.get("OPENFLOW_SD_LATEST")
            return mock.Mock(returncode=0)

        with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(cli.subprocess, "run", side_effect=fake_run), mock.patch.object(cli, "_ensure_pip", return_value=True), \
                mock.patch.object(cli, "_remote_version", return_value="0.0.1"), mock.patch.object(cli, "_managed_app_dir", return_value=None), contextlib.redirect_stdout(io.StringIO()):
            os.environ.pop("OPENFLOW_SD_LATEST", None)
            cli.main(argv)
        return seen.get("sd")

    def test_flow_update_asks_for_the_newest_stable_diffusion_even_without_a_new_model(self):
        self.assertEqual(self.update_env(["update", "--no-python"]), "always")
        self.assertIsNone(self.update_env(["update", "--no-python", "--core"]))     # --core: sem bibliotecas
        with mock.patch.dict(os.environ, {"OPENFLOW_SD_LATEST": "never"}):         # quem desligou de propósito continua desligado
            seen = {}

            def fake_run(cmd, *a, **k):
                if cmd[-1] == "libs":
                    seen["sd"] = os.environ.get("OPENFLOW_SD_LATEST")
                return mock.Mock(returncode=0)

            with mock.patch.object(cli.subprocess, "run", side_effect=fake_run), mock.patch.object(cli, "_ensure_pip", return_value=True), mock.patch.object(cli, "_remote_version", return_value="0.0.1"), \
                    mock.patch.object(cli, "_managed_app_dir", return_value=None), contextlib.redirect_stdout(io.StringIO()):
                cli.main(["update", "--no-python"])
            self.assertEqual(seen["sd"], "never")

    def test_always_mode_builds_when_github_has_a_new_commit_and_skips_when_it_does_not(self):
        marker = Path(tempfile.mkdtemp()) / "sd_needs_newer"
        every = {"pypdf": "5.0", "torch": "2.5", "diffusers": "0.31", "llama-cpp-python": "0.3.1"}
        with mock.patch.object(cli, "_build_tools_missing", return_value=[]):
            _, calls, _ = run_cli(["libs"], installed=every, env={"OPENFLOW_SD_LATEST": "always"}, marker=marker, remote_sha="abc123")
            self.assertTrue(any(c[-1] == cli.SD_GIT for c in calls))               # sem modelo novo e sem aviso, mas «always» + commit novo = compila
            (marker.parent / "sd_built_sha").write_text("abc123")
            _, calls, out = run_cli(["libs"], installed=every, env={"OPENFLOW_SD_LATEST": "always"}, marker=marker, remote_sha="abc123")
            self.assertFalse(any(c[-1] == cli.SD_GIT for c in calls))              # mesmo commit: não recompila
            self.assertIn("já está na versão mais recente", out)

    def test_one_failing_library_does_not_block_the_others_of_its_group(self):
        every = {"pypdf": "5.0", "torch": "2.5", "diffusers": "0.31", "llama-cpp-python": "0.3.1"}
        code, calls, out = run_cli(["libs", "--extras", "media"], installed=every, results={"torch": 1})   # o grupo «media» falha por causa do torch
        installs = pip_installs(calls)
        self.assertIn("uma biblioteca por vez", out)
        singles = [c[-1] for c in installs if not ({"torch", "diffusers>=0.30"} <= set(c)) and c[-1] in ("torch", "diffusers>=0.30")]   # chamadas de uma só biblioteca (a do grupo leva as duas)
        self.assertEqual(sorted(singles), ["diffusers>=0.30", "torch"])           # depois do grupo falhar, cada uma é tentada sozinha (o diffusers atualiza mesmo com o torch falhando)
        self.assertIn("Não consegui atualizar agora: torch", out)
        self.assertNotIn("diffusers (sem internet", out)
        self.assertEqual(code, 0)                                                   # só atualização: nunca vira erro

    def test_summary_lists_what_changed_or_says_everything_was_current(self):
        versions = {"pypdf": "5.0"}
        calls = []

        def fake_run(cmd, *a, **k):
            calls.append(cmd)
            if "pypdf>=4.0" in cmd:
                versions["pypdf"] = "5.1"
            return mock.Mock(returncode=0)

        out = io.StringIO()
        with mock.patch.object(cli.subprocess, "run", side_effect=fake_run), mock.patch.object(cli, "_ensure_pip", return_value=True), mock.patch.object(cli, "_sd_cli_refresh"), \
                mock.patch.object(cli, "_lib_requirements", return_value=["pypdf>=4.0"]), mock.patch.object(cli, "_installed_version", side_effect=lambda r: versions.get(cli._req_name(r))), contextlib.redirect_stdout(out):
            cli._libs(argparse.Namespace(extras="docs", sd_cli=False, sd_latest=False))
            self.assertIn("Atualizadas: pypdf 5.0 → 5.1", out.getvalue())
            out.truncate(0)
            out.seek(0)
            cli._libs(argparse.Namespace(extras="docs", sd_cli=False, sd_latest=False))
        self.assertIn("Todas as bibliotecas já estavam nas versões mais novas", out.getvalue())


class SdCliRefreshTests(unittest.TestCase):
    def setUp(self):
        from openflow.canvas import sdcli

        self.sdcli = sdcli
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["OPENFLOW_HOME"] = str(self.tmp)
        self.addCleanup(os.environ.pop, "OPENFLOW_HOME", None)

    def run_refresh(self, latest):
        out = io.StringIO()
        with mock.patch.object(self.sdcli, "latest_release", return_value={"tag_name": latest}), mock.patch.object(self.sdcli, "install") as inst, contextlib.redirect_stdout(out):
            cli._sd_cli_refresh()
        return inst, out.getvalue()

    def test_the_downloaded_cli_follows_the_newest_release(self):
        inst, _ = self.run_refresh("master-2")
        inst.assert_not_called()                          # nunca baixado: não baixa à toa (o OpenFlow o baixa quando um modelo precisar)
        self.sdcli.bin_dir().mkdir(parents=True)
        (self.sdcli.bin_dir() / "VERSION").write_text("master-1")
        inst, out = self.run_refresh("master-2")
        inst.assert_called_once()
        self.assertIn("master-1 → master-2", out)
        inst, out = self.run_refresh("master-1")
        inst.assert_not_called()
        self.assertIn("já é a versão mais recente", out)
        with mock.patch.object(self.sdcli, "latest_release", side_effect=OSError("sem rede")), contextlib.redirect_stdout(io.StringIO()) as o:
            cli._sd_cli_refresh()                         # sem rede: aviso, nunca erro
        self.assertIn("sigo com a instalada", o.getvalue())


if __name__ == "__main__":
    unittest.main()
