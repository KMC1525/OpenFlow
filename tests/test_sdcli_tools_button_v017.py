"""v0.17: o erro do nó «falta git» é uma mensagem só, com um botão que instala o que falta e compila; `flow libs` instala as ferramentas antes de compilar as bibliotecas."""
import os
import time
import unittest
from pathlib import Path
from unittest import mock

from openflow import cli
from openflow.canvas import media as M
from openflow.canvas import sdcli
from openflow.providers import ProviderError
from tests.helpers import ServerCase, TmpCase

NAME = "flux-3-image-klein-Q4_K_M.gguf"


class NodeErrorTests(TmpCase):
    def provider(self):
        p = M.GGUFMedia.__new__(M.GGUFMedia)
        p.ctl = M.Ctl(note=lambda m: None)
        p._cancelled = lambda: False
        return p

    def test_missing_tools_give_one_clear_message_with_the_install_button(self):
        p = self.provider()
        with mock.patch.object(sdcli, "find", return_value=None), mock.patch.object(sdcli, "install", side_effect=sdcli.BuildToolsMissing("Para compilar o sd-cli aqui falta: git.")):
            self.assertFalse(p._cli_fallback(M._SDUnsupportedModel("x")))
        self.assertTrue(p._cli_tools_missing)
        with mock.patch.object(sdcli, "build_tools_missing", return_value=["git"]), mock.patch.object(sdcli, "build_tools_hint", return_value="sudo apt install git build-essential"):
            msg = str(p._no_cli_error(Path(NAME)))
        self.assertIn("faltam: git", msg)
        self.assertIn("[[flow-sd-tools]]", msg)                  # o nó mostra o botão «Instalar o que falta e compilar»
        self.assertIn("flow update", msg)
        self.assertIn("sudo apt install git build-essential", msg)
        self.assertEqual(msg.count("flow update"), 1)            # uma vez só (antes a mensagem se repetia)
        self.assertNotIn("..", msg)
        self.assertNotIn("[[flow-sd-cli]]", msg)

    def test_other_failures_keep_the_old_message_and_clear_the_flag(self):
        p = self.provider()
        with mock.patch.object(sdcli, "find", return_value=None), mock.patch.object(sdcli, "install", side_effect=ProviderError("sem rede")):
            p._cli_fallback(M._SDUnsupportedModel("x"))
        self.assertFalse(p._cli_tools_missing)
        self.assertIn("sem rede", str(p._no_cli_error(Path(NAME))))


class ButtonRouteTests(ServerCase):
    def run_button(self, install, tools):
        with mock.patch.object(sdcli, "install", side_effect=install), mock.patch.object(cli, "_install_build_tools", side_effect=tools) as inst:
            s, r = self.c.json("POST", "/api/media/sd-cli", {})
            self.assertEqual(s, 200, r)
            for _ in range(100):
                s, j = self.c.json("GET", "/api/jobs/" + r["job_id"])
                if j.get("status") != "running":
                    break
                time.sleep(0.05)
        return j, inst

    def test_the_button_installs_the_missing_tools_and_builds(self):
        calls = []

        def install(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise sdcli.BuildToolsMissing("falta git")
            return Path("/x/sd-cli")

        j, inst = self.run_button(install, lambda **k: True)
        self.assertEqual(j["status"], "done", j)
        self.assertEqual(len(calls), 2)                          # tentou, instalou as ferramentas e tentou de novo
        inst.assert_called_once()
        self.assertIn("note", inst.call_args.kwargs)             # o andamento («digite a senha no terminal») chega ao botão

    def test_the_button_reports_when_the_tools_could_not_be_installed(self):
        def install(*a, **k):
            raise sdcli.BuildToolsMissing("falta git")

        j, _ = self.run_button(install, lambda **k: False)
        events = self.app.jobs.jobs[j["id"]].events                                   # o botão lê os eventos da tarefa
        errors = [e for e in events if e.get("type") == "error"]
        self.assertEqual(len(errors), 1, events)
        self.assertIn("git e compilador", errors[0]["message"])
        self.assertFalse([e for e in events if e.get("type") == "done"])


class LibsOrderTests(unittest.TestCase):
    def test_build_tools_come_before_the_native_libraries(self):
        order = []
        with mock.patch.object(cli, "_ensure_pip", return_value=True), mock.patch.object(cli, "_lib_requirements", return_value=["llama-cpp-python>=0.2.90"]), \
                mock.patch.object(cli, "_installed_version", return_value=None), mock.patch.object(cli, "_build_tools_missing", return_value=["git"]), \
                mock.patch.object(cli, "_install_build_tools", side_effect=lambda *a, **k: order.append("tools") or True), mock.patch.object(cli, "_sd_latest", return_value=True), \
                mock.patch.object(cli, "_sd_cli_refresh"), mock.patch.object(cli.subprocess, "run", side_effect=lambda cmd, *a, **k: order.append("pip") or mock.Mock(returncode=0)), \
                mock.patch.dict(os.environ, {"OPENFLOW_AUTO_TOOLS": "yes"}):
            import argparse
            import contextlib
            import io

            with contextlib.redirect_stdout(io.StringIO()):
                cli._libs(argparse.Namespace(extras="local", sd_cli=False, sd_latest=False))
        self.assertEqual(order[0], "tools")                      # antes do pip: senão o llama-cpp-python falha e nunca é refeito
        self.assertIn("pip", order)
        order.clear()
        with mock.patch.object(cli, "_ensure_pip", return_value=True), mock.patch.object(cli, "_lib_requirements", return_value=["llama-cpp-python>=0.2.90"]), \
                mock.patch.object(cli, "_installed_version", return_value=None), mock.patch.object(cli, "_build_tools_missing", return_value=["git"]), \
                mock.patch.object(cli, "_install_build_tools", side_effect=lambda *a, **k: order.append("tools") or True), mock.patch.object(cli, "_sd_latest", return_value=True), \
                mock.patch.object(cli, "_sd_cli_refresh"), mock.patch.object(cli.subprocess, "run", return_value=mock.Mock(returncode=0)), mock.patch.dict(os.environ, {"OPENFLOW_AUTO_TOOLS": "0"}):
            import argparse
            import contextlib
            import io

            with contextlib.redirect_stdout(io.StringIO()):
                cli._libs(argparse.Namespace(extras="local", sd_cli=False, sd_latest=False))
        self.assertEqual(order, [])                              # opt-out: nada é instalado sozinho


if __name__ == "__main__":
    unittest.main()
