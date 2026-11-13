"""Idioma do terminal (igual ao do computador) e Rust opcional (`flow native setup`, `flow update --rust`, instaladores)."""
import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import cli, native, termi18n  # noqa: E402
from openflow.term_en import EN  # noqa: E402
from tests.test_cli import run_cli  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLEAN = {k: "" for k in ("OPENFLOW_LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")}


def lang_with(**env) -> str:
    with mock.patch.dict(os.environ, {**CLEAN, **env}):
        return termi18n.system_lang(refresh=True)


class DetectionTests(unittest.TestCase):
    def tearDown(self):
        termi18n.system_lang(refresh=True)

    def test_portuguese_variants_and_everything_else(self):
        for v in ("pt_BR.UTF-8", "pt_PT", "pt", "pt-BR", "PT_BR"):
            self.assertEqual(lang_with(LANG=v), "pt", v)
        for v in ("en_US.UTF-8", "es_ES.UTF-8", "ja_JP", "de_DE", "fr"):
            self.assertEqual(lang_with(LANG=v), "en", v)

    def test_priority_force_and_unset(self):
        self.assertEqual(lang_with(LC_ALL="pt_BR.UTF-8", LANG="en_US"), "pt")      # LC_ALL vence LANG
        self.assertEqual(lang_with(LANGUAGE="pt:en", LANG="en_US"), "pt")           # primeiro idioma de LANGUAGE
        self.assertEqual(lang_with(OPENFLOW_LANG="en", LANG="pt_BR.UTF-8"), "en")      # OPENFLOW_LANG força
        self.assertEqual(lang_with(OPENFLOW_LANG="pt", LANG="en_US.UTF-8"), "pt")
        self.assertEqual(lang_with(LANG="C.UTF-8"), "en")                            # C/POSIX não dizem nada: cai no inglês
        with mock.patch.object(termi18n.sys, "platform", "linux"), mock.patch.object(termi18n.os, "name", "posix"):
            self.assertEqual(lang_with(), "en")

    def test_translation_and_formatting(self):
        with mock.patch.dict(os.environ, {**CLEAN, "OPENFLOW_LANG": "en"}):
            self.assertEqual(termi18n._("Pronto! Reinicie o OpenFlow para usar a nova versão."), "Done! Restart OpenFlow to use the new version.")
            self.assertEqual(termi18n._("Rust instalado: {v}", v="cargo 1.80"), "Rust installed: cargo 1.80")
            self.assertEqual(termi18n._("frase sem tradução {x}", x=1), "frase sem tradução 1")   # sem tradução, fica em português
        with mock.patch.dict(os.environ, {**CLEAN, "OPENFLOW_LANG": "pt"}):
            self.assertEqual(termi18n._("Rust instalado: {v}", v="cargo 1.80"), "Rust instalado: cargo 1.80")

    def test_every_terminal_message_in_the_code_has_an_english_translation(self):
        missing = []
        for f in ("openflow/cli.py", "openflow/preinstalled.py", "openflow/native/__init__.py"):
            for n in ast.walk(ast.parse((ROOT / f).read_text(encoding="utf-8"))):
                if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_" and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    if n.args[0].value not in EN:
                        missing.append(n.args[0].value[:70])
        for d in cli.LIBS.values():
            if d not in EN:
                missing.append(d[:70])
        self.assertEqual(missing, [])
        for pt, en in EN.items():                                                   # os {campos} são os mesmos nas duas línguas
            self.assertEqual(sorted(re.findall(r"\{(\w+)", pt)), sorted(re.findall(r"\{(\w+)", en)), pt[:60])
            self.assertTrue(en.strip(), pt[:60])


class CliLanguageTests(unittest.TestCase):
    def test_cli_output_follows_the_language(self):
        _, _, pt = run_cli(["libs"], env={"OPENFLOW_LANG": "pt"})
        _, _, en = run_cli(["libs"], env={"OPENFLOW_LANG": "en"})
        self.assertIn("Bibliotecas prontas", pt)
        self.assertIn("Libraries ready", en)
        self.assertNotIn("Bibliotecas", en)

    def test_help_is_translated(self):
        import contextlib
        import io

        for lang, needle in (("pt", "mostra diagnóstico do ambiente"), ("en", "shows the environment diagnostics")):
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"OPENFLOW_LANG": lang}), contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                cli.main(["--help"])
            self.assertIn(needle, out.getvalue())

    def test_installer_gets_the_same_language_and_rust_choice(self):
        seen = {}

        def fake_run(cmd, env=None, **k):
            seen["env"] = env
            return mock.Mock(returncode=0)

        with mock.patch.object(cli, "_managed_app_dir", return_value=Path("/home/u/.openflow/app")), mock.patch("urllib.request.urlopen") as uo, \
                mock.patch.object(cli.subprocess, "run", side_effect=fake_run), mock.patch.object(cli.os, "name", "posix"), mock.patch.dict(os.environ, {"OPENFLOW_LANG": "en"}):
            uo.return_value.__enter__.return_value.read.return_value = b"echo hi"
            cli._update_with_installer(__import__("argparse").Namespace(force=False, core=False, extras="", no_python=False, rust="yes"))
        self.assertEqual((seen["env"]["OPENFLOW_LANG"], seen["env"]["OPENFLOW_RUST"]), ("en", "yes"))


class RustTests(unittest.TestCase):
    def run_setup(self, mode, have=True, answer=None, install_code=0, build_code=0):
        calls = []
        asked = []

        def ask(q, default=False):
            asked.append((q, default))
            return answer

        def installed():
            calls.append("install")
            return install_code

        # o caminho do Rust na máquina (v0.14: a biblioteca pronta da Release vem primeiro): aqui ela está indisponível e o compilador existe, para exercitar a instalação/compilação
        with mock.patch.object(native, "available", return_value=False), mock.patch.object(native, "fetch_prebuilt", return_value=1), mock.patch.object(native, "_toolchain_ok", return_value=True), \
                mock.patch.object(native, "find_tool", side_effect=lambda n: "/x/cargo" if (have or "install" in calls) else None), mock.patch.object(native, "install_rust", side_effect=installed), \
                mock.patch.object(native, "update_rust", side_effect=lambda: calls.append("update")), mock.patch.object(native, "build", side_effect=lambda *a, **k: (calls.append("build"), build_code)[1]):
            import contextlib
            import io

            out = io.StringIO()
            with contextlib.redirect_stdout(out), mock.patch.dict(os.environ, {"OPENFLOW_LANG": "pt"}):
                code = native.setup(mode, ask=ask)
        return code, calls, asked, out.getvalue()

    def test_no_does_nothing(self):
        code, calls, asked, out = self.run_setup("no", have=False)
        self.assertEqual((code, calls, asked), (0, [], []))
        self.assertIn("pulado", out)

    def test_yes_installs_updates_and_builds_without_asking(self):
        code, calls, asked, _ = self.run_setup("yes", have=False)
        self.assertEqual((code, calls, asked), (0, ["install", "update", "build"], []))
        _, calls, _, _ = self.run_setup("yes", have=True)
        self.assertEqual(calls, ["update", "build"])                                  # já tem Rust: só atualiza e recompila

    def test_default_is_automatic_no_question(self):
        for have in (False, True):
            code, calls, asked, _ = self.run_setup(None, have=have)                  # sem escolha: faz sozinho, como as bibliotecas e os modelos
            self.assertEqual(asked, [])
            self.assertEqual(calls, (["install"] if not have else []) + ["update", "build"])
        with mock.patch.dict(os.environ, {"OPENFLOW_RUST": ""}):
            with mock.patch.object(native, "setup", return_value=0) as su:
                cli.main(["native", "setup"])
                self.assertEqual(su.call_args[0][0], "yes")

    def test_ask_respects_the_answer_and_never_installs_without_a_terminal(self):
        code, calls, asked, _ = self.run_setup("ask", have=False, answer=True)
        self.assertEqual(calls, ["install", "update", "build"])
        self.assertFalse(asked[0][1])                                                  # instalar: padrão «não»
        _, calls, asked, out = self.run_setup("ask", have=False, answer=False)
        self.assertEqual(calls, [])
        self.assertIn("sem Rust", out)
        _, calls, _, out = self.run_setup("ask", have=False, answer=None)              # sem terminal e sem Rust: não instala nada
        self.assertEqual(calls, [])
        self.assertIn("não há um terminal", out)
        _, calls, asked, _ = self.run_setup("ask", have=True, answer=None)             # sem terminal mas com Rust: atualiza e recompila
        self.assertEqual(calls, ["update", "build"])
        _, calls, asked, _ = self.run_setup("ask", have=True, answer=True)
        self.assertTrue(asked[0][1])                                                   # atualizar o que já existe: padrão «sim»

    def test_failures_are_soft_and_explain_what_to_install(self):
        code, calls, _, out = self.run_setup("yes", have=False, install_code=1)
        self.assertEqual((code, calls), (0, ["install"]))                              # não deu para instalar: segue sem quebrar
        code, calls, _, out = self.run_setup("yes", have=True, build_code=1)
        self.assertEqual(code, 0)
        self.assertTrue(any(w in out for w in ("gcc", "xcode-select", "Build Tools", "Ferramentas de Build")))  # dica do compilador do sistema

    def test_find_tool_looks_in_the_rustup_folder(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            bindir = Path(d) / "bin"
            bindir.mkdir()
            exe = bindir / ("cargo.exe" if os.name == "nt" else "cargo")
            exe.write_text("x")
            with mock.patch.object(native.shutil, "which", return_value=None), mock.patch.dict(os.environ, {"CARGO_HOME": d}):
                self.assertEqual(native.find_tool("cargo"), str(exe))
                self.assertIsNone(native.find_tool("rustup"))

    def test_cli_native_commands_and_update_flag(self):
        with mock.patch.object(native, "setup", return_value=0) as su, mock.patch.dict(os.environ, {"OPENFLOW_RUST": "yes"}):
            self.assertEqual(cli.main(["native", "setup"]), 0)
            self.assertEqual(su.call_args[0][0], "yes")                                # OPENFLOW_RUST vale quando não há --rust
            cli.main(["native", "setup", "--rust", "no"])
            self.assertEqual(su.call_args[0][0], "no")
        with mock.patch.object(native, "install_rust", return_value=0) as ir, mock.patch.object(native, "build", return_value=0) as bu:
            cli.main(["native", "install"])
            self.assertTrue(ir.called and bu.called)
        with mock.patch.object(native, "update_rust") as ur, mock.patch.object(native, "build", return_value=0):
            cli.main(["native", "update"])
            self.assertTrue(ur.called)
        # `flow update --no-python --rust yes` (sem o instalador): roda o `native setup` com a escolha
        _, calls, _ = run_cli(["update", "--no-python", "--rust", "yes"], env={"OPENFLOW_FORCE": "1"})
        self.assertIn([sys.executable, "-m", "openflow", "native", "setup", "--rust", "yes"], calls)
        _, calls, _ = run_cli(["update", "--no-python"], env={"OPENFLOW_FORCE": "1"})
        self.assertIn([sys.executable, "-m", "openflow", "native", "setup"], calls)       # sem a flag: o próprio setup pergunta (ou usa OPENFLOW_RUST)
        _, calls, _ = run_cli(["update", "--no-python", "--core"], env={"OPENFLOW_FORCE": "1"})
        self.assertNotIn("setup", [part for c in calls for part in c])                 # --core: só o OpenFlow


class InstallerScriptTests(unittest.TestCase):
    def test_sh_syntax_language_detection_and_rust_step(self):
        sh = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertEqual(subprocess.run(["sh", "-n", str(ROOT / "install.sh")]).returncode, 0)
        fn = sh[sh.index("detect_lang() {"):sh.index('OPENFLOW_L="$(detect_lang)"')]
        for env, want in (({"LANG": "pt_BR.UTF-8"}, "pt"), ({"LANG": "en_US.UTF-8"}, "en"), ({"LC_ALL": "pt_PT.UTF-8", "LANG": "en_US"}, "pt"), ({"LANG": "C.UTF-8"}, "en"),
                          ({"OPENFLOW_LANG": "en", "LANG": "pt_BR"}, "en"), ({"LANGUAGE": "pt:en"}, "pt"), ({}, "en")):
            got = subprocess.run(["sh", "-c", fn + "\ndetect_lang"], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", **env}).stdout.strip()
            self.assertEqual(got, want, env)
        # toda mensagem das funções say/note/die passa por L (pt/en)
        bare = [m for m in re.findall(r'\b(?:say|note|die) "([^"$][^"]*)"', sh) if not m.startswith("$(L")]
        self.assertEqual([b for b in bare if re.search(r"[A-Za-zÀ-ÿ]{4,}", b) and "export PATH" not in b], [])
        self.assertIn("flow\" native setup", sh)
        self.assertIn("OPENFLOW_RUST", sh)
        self.assertIn('OPENFLOW_RUST="${OPENFLOW_RUST:-yes}"', sh)                              # automático por padrão
        self.assertNotIn("command -v cargo", sh)                                      # a lógica do Rust agora vive no `flow native setup`

    @unittest.skipIf(os.name == "nt", "o sh do Git for Windows não repassa argumentos UTF-8 de forma confiável; o instalador .sh é para macOS/Linux")
    def test_sh_messages_are_printed_in_the_detected_language(self):
        sh = (ROOT / "install.sh").read_text(encoding="utf-8")
        head = sh[sh.index("# Idioma dos textos"):sh.index("say \"$(L \"OpenFlow — instalação/atualização\"")]
        for lang, want in (("pt_BR.UTF-8", "OpenFlow — instalação/atualização"), ("en_US.UTF-8", "OpenFlow — install/update")):
            out = subprocess.run(["sh", "-c", head + '\nsay "$(L "OpenFlow — instalação/atualização" "OpenFlow — install/update")"'], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "LANG": lang}).stdout
            self.assertIn(want, out)

    def test_ps1_has_language_helper_rust_step_and_every_message_is_bilingual(self):
        ps = (ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertIn("function L($pt, $en)", ps)
        self.assertIn("Get-UICulture", ps)
        self.assertIn("OPENFLOW_RUST", ps)
        self.assertIn("& $flow native setup", ps)
        self.assertIn("$env:OPENFLOW_RUST = 'yes'", ps)
        self.assertNotIn("Get-Command cargo", ps)
        calls = re.findall(r"\b(Say|Note|Die) (\S.{0,3})", ps)
        self.assertTrue(calls)
        self.assertEqual([c for c in calls if not c[1].startswith("(L") and not c[1].startswith("$m") and c[1] != '("Py'], [])   # 'Python: <versão>' não tem texto a traduzir
        self.assertEqual(ps.count("{"), ps.count("}"))


if __name__ == "__main__":
    unittest.main()


class FolderCommandTests(unittest.TestCase):
    def test_folder_opens_the_data_folder_and_print_only_prints(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "dados"
            out = io.StringIO()
            with mock.patch.object(cli.subprocess, "run") as run, contextlib.redirect_stdout(out), mock.patch.object(cli.sys, "platform", "linux"), mock.patch.object(cli.os, "name", "posix"):
                self.assertEqual(cli.main(["folder", "--home", str(home)]), 0)
                self.assertEqual(run.call_args[0][0], ["xdg-open", str(home)])
            self.assertTrue(home.is_dir())                                   # cria se ainda não existir
            self.assertIn(str(home), out.getvalue())
            with mock.patch.object(cli.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()) as o2:
                self.assertEqual(cli.main(["folder", "--print", "--home", str(home)]), 0)
                run.assert_not_called()
            self.assertEqual(o2.getvalue().strip(), str(home))
            with mock.patch.object(cli.subprocess, "run", side_effect=OSError("sem xdg-open")), contextlib.redirect_stdout(io.StringIO()), mock.patch.object(cli.sys, "platform", "linux"), mock.patch.object(cli.os, "name", "posix"):
                self.assertEqual(cli.main(["folder", "--home", str(home)]), 1)   # sem gerenciador de arquivos: avisa e devolve erro
            with mock.patch.object(cli.sys, "platform", "darwin"), mock.patch.object(cli.os, "name", "posix"), mock.patch.object(cli.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
                cli.main(["folder", "--home", str(home)])
                self.assertEqual(run.call_args[0][0][0], "open")
