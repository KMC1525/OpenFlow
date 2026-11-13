"""Linha de comando: instalar/atualizar o OpenFlow e todas as bibliotecas dele (flow libs / flow update)."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import cli  # noqa: E402

REQUIRES = [
    'pypdf>=4.0; extra == "docs"', 'torch; extra == "media"', 'diffusers>=0.30; extra == "media"', 'llama-cpp-python>=0.2.90; extra == "local"',
    'pypdf>=4.0; extra == "all"', 'torch; extra == "all"',
]


def run_cli(argv, env=None, results=None, installed=None, remote="99.0.0", marker=None, remote_sha=""):
    """Executa `flow ...` simulando o pip. `results`: {palavra do requisito: código de saída}. `installed`: {nome da biblioteca: versão} já instalada.
    `remote`: versão do OpenFlow publicada (None = não deu para consultar). Devolve (código, comandos, saída)."""
    calls, results = [], results or {}

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        code = next((c for word, c in results.items() if any(word in part for part in cmd)), 0)
        return mock.Mock(returncode=code)

    out = io.StringIO()
    have = installed or {}
    marker = marker or Path(tempfile.mkdtemp()) / "sd_needs_newer"   # nunca o ~/.openflow de verdade
    with mock.patch.object(cli, "_sd_dir", return_value=marker.parent), mock.patch.object(cli, "_sd_remote_sha", return_value=remote_sha), mock.patch("importlib.metadata.requires", return_value=REQUIRES), mock.patch.object(cli.subprocess, "run", side_effect=fake_run), \
            mock.patch.object(cli, "_installed_version", side_effect=lambda r: have.get(cli._req_name(r))), mock.patch.object(cli, "_remote_version", return_value=remote), \
            mock.patch.dict(os.environ, env or {}, clear=False), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        if not env or "OPENFLOW_EXTRAS" not in env:
            os.environ.pop("OPENFLOW_EXTRAS", None)
        code = cli.main(argv)
    return code, calls, out.getvalue()


def pip_installs(calls):
    return [c for c in calls if "pip" in c and "install" in c]


class LibsTests(unittest.TestCase):
    def test_newest_stable_diffusion_is_built_from_github_only_when_the_canvas_asked_for_it(self):
        marker = Path(tempfile.mkdtemp()) / "sd_needs_newer"
        code, calls, _ = run_cli(["libs"], marker=marker)   # sem o aviso do Canvas: só o PyPI, como antes
        self.assertEqual(code, 0)
        self.assertFalse(any(cli.SD_GIT in c for call in calls for c in call))
        marker.write_text("qwen-image-2.1-Q4_K_M.gguf")      # o Canvas avisou: «get sd version from file failed»
        with mock.patch.object(cli.shutil, "which", return_value="/usr/bin/x"):
            code, calls, out = run_cli(["libs"], marker=marker)
        self.assertEqual(code, 0)
        git = [c for c in pip_installs(calls) if cli.SD_GIT in c]
        self.assertEqual(len(git), 1)
        self.assertIn("--force-reinstall", git[0])
        self.assertFalse(marker.exists())                    # feito: não recompila a cada atualização

    def test_failed_build_keeps_the_marker_and_reports_the_failure(self):
        marker = Path(tempfile.mkdtemp()) / "sd_needs_newer"
        marker.write_text("x")
        with mock.patch.object(cli.shutil, "which", return_value="/usr/bin/x"):
            code, calls, out = run_cli(["libs"], results={"git+https": 1}, marker=marker)
        self.assertEqual(code, 1)
        self.assertTrue(marker.exists())
        self.assertIn("flow libs --sd-latest", out)

    def test_missing_build_tools_are_named_instead_of_failing_in_pip(self):
        marker = Path(tempfile.mkdtemp()) / "sd_needs_newer"
        marker.write_text("x")
        with mock.patch.object(cli.shutil, "which", return_value=None), mock.patch.object(cli.os, "name", "posix"):
            code, calls, out = run_cli(["libs", "--extras", "local"], marker=marker)
        self.assertEqual(code, 1)
        self.assertIn("git", out)
        self.assertIn("compilador", out)
        self.assertFalse(any(cli.SD_GIT in c for call in calls for c in call))

    def test_cmake_is_not_required_because_pip_fetches_it_when_building(self):
        marker = Path(tempfile.mkdtemp()) / "sd_needs_newer"
        marker.write_text("x")
        have = {"git": "/usr/bin/git", "gcc": "/usr/bin/gcc"}   # sem cmake nem ninja no sistema
        with mock.patch.object(cli.shutil, "which", side_effect=lambda t: have.get(t)), mock.patch.object(cli.os, "name", "posix"):
            code, calls, out = run_cli(["libs", "--extras", "local"], marker=marker)
        self.assertEqual(code, 0, out)
        self.assertTrue(any(cli.SD_GIT in c for call in calls for c in call))

    def test_diffusion_ggufs_get_the_newest_library_automatically_but_only_when_github_has_news(self):
        home = Path(tempfile.mkdtemp())
        (home / "models" / "image").mkdir(parents=True)
        (home / "models" / "image" / "qwen-image-2.1-Q4_K_M.gguf").write_bytes(b"g")
        marker = home / "sd_needs_newer"            # não existe: nenhum modelo falhou ainda
        tools = mock.patch.object(cli.shutil, "which", return_value="/usr/bin/x")
        with tools:
            code, calls, out = run_cli(["libs", "--extras", "local"], marker=marker, remote_sha="abc123")
        self.assertTrue(any(cli.SD_GIT in c for call in calls for c in call))      # tem GGUF de difusão: compila na instalação/atualização
        self.assertEqual((home / "sd_built_sha").read_text(), "abc123")
        with tools:
            code, calls, out = run_cli(["libs", "--extras", "local"], marker=marker, remote_sha="abc123")
        self.assertFalse(any(cli.SD_GIT in c for call in calls for c in call))     # nada novo no GitHub: não recompila
        self.assertIn("já está na versão mais recente", out)
        with tools:
            code, calls, out = run_cli(["libs", "--extras", "local"], marker=marker, remote_sha="def456")
        self.assertTrue(any(cli.SD_GIT in c for call in calls for c in call))      # commit novo: recompila
        (home / "models" / "image" / "qwen-image-2.1-Q4_K_M.gguf").unlink()
        (home / "sd_built_sha").unlink()
        with tools:
            code, calls, out = run_cli(["libs", "--extras", "local"], marker=marker, remote_sha="zzz")
        self.assertFalse(any(cli.SD_GIT in c for call in calls for c in call))     # sem GGUF de difusão e sem aviso: não mexe

    def test_never_mode_and_the_flag(self):
        marker = Path(tempfile.mkdtemp()) / "sd_needs_newer"
        marker.write_text("x")
        code, calls, _ = run_cli(["libs"], env={"OPENFLOW_SD_LATEST": "never"}, marker=marker)
        self.assertFalse(any(cli.SD_GIT in c for call in calls for c in call))
        with mock.patch.object(cli.shutil, "which", return_value="/usr/bin/x"):
            code, calls, _ = run_cli(["libs", "--sd-latest", "--extras", "none"], marker=Path(tempfile.mkdtemp()) / "nada")
        self.assertTrue(any(cli.SD_GIT in c for call in calls for c in call))   # a flag força, mesmo sem aviso e sem outras bibliotecas


    def test_requirements_come_from_the_installed_metadata_per_extra(self):
        with mock.patch("importlib.metadata.requires", return_value=REQUIRES):
            self.assertEqual(cli._lib_requirements("media"), ["torch", "diffusers>=0.30"])
            self.assertEqual(cli._lib_requirements("docs"), ["pypdf>=4.0"])
            self.assertEqual(cli._lib_requirements("nada"), [])

    def test_default_installs_and_upgrades_every_library(self):
        code, calls, out = run_cli(["libs"])
        self.assertEqual(code, 0)
        installs = pip_installs(calls)
        self.assertEqual(len(installs), 3)  # docs, media e local, nessa ordem (da mais leve à mais pesada)
        flat = [" ".join(c) for c in installs]
        self.assertIn("pypdf>=4.0", flat[0])
        self.assertIn("torch diffusers>=0.30", flat[1])
        self.assertIn("llama-cpp-python>=0.2.90", flat[2])
        for c in installs:
            self.assertIn("--upgrade", c)
            self.assertEqual(c[c.index("--upgrade-strategy") + 1], "eager")  # atualiza também as dependências das bibliotecas
        self.assertIn("Bibliotecas prontas: docs, media, local", out)

    def test_one_failing_library_does_not_block_the_others(self):
        code, calls, out = run_cli(["libs"], results={"llama-cpp-python": 1})
        self.assertEqual(code, 1)
        self.assertEqual(len(pip_installs(calls)), 3)
        self.assertIn("com falha: local", out)
        self.assertIn("flow libs --extras local", out)

    def test_libraries_already_installed_are_not_installed_again_only_updated_if_newer(self):
        every = {"pypdf": "5.0", "torch": "2.5", "diffusers": "0.31", "llama-cpp-python": "0.3.1"}
        code, calls, out = run_cli(["libs"], installed=every)
        self.assertEqual(code, 0)
        installs = pip_installs(calls)
        self.assertEqual(len(installs), 3)
        for c in installs:
            self.assertIn("--quiet", c)  # só uma checagem: o pip não reinstala quem já está na versão mais nova
            self.assertNotIn("--force-reinstall", c)
        self.assertIn("já instaladas (pypdf 5.0)", out)
        self.assertIn("só atualizo se houver versão mais nova", out)
        self.assertIn("já estavam instaladas: docs, media, local", out)
        # sem internet: o que já está instalado não vira erro
        code, calls, out = run_cli(["libs"], installed=every, results={"pypdf": 1, "torch": 1, "llama": 1})
        self.assertEqual(code, 0)
        self.assertIn("sigo com as versões instaladas", out)

    def test_only_the_missing_library_is_reported_as_installing(self):
        code, calls, out = run_cli(["libs", "--extras", "media"], installed={"torch": "2.5"})
        self.assertEqual(code, 0)
        self.assertIn("instalando diffusers>=0.30", out)
        self.assertIn("já instaladas (só atualizo se precisar): torch", out)
        self.assertNotIn("--quiet", pip_installs(calls)[0])

    def test_choosing_libraries_and_the_environment_variable(self):
        self.assertEqual(len(pip_installs(run_cli(["libs", "--extras", "docs,media"])[1])), 2)
        self.assertEqual(len(pip_installs(run_cli(["libs"], env={"OPENFLOW_EXTRAS": "docs"})[1])), 1)
        code, calls, out = run_cli(["libs", "--extras", "none"])
        self.assertEqual((code, pip_installs(calls)), (0, []))
        code, calls, out = run_cli(["libs"], env={"OPENFLOW_EXTRAS": "none"})
        self.assertEqual(pip_installs(calls), [])
        code, calls, out = run_cli(["libs", "--extras", "docs,xyz"])
        self.assertEqual((code, calls), (2, []))
        self.assertIn("xyz", out)


class UpdateTests(unittest.TestCase):
    def test_manual_install_updates_tooling_asta_and_then_all_libraries(self):
        with mock.patch.object(cli, "_managed_app_dir", return_value=None):
            code, calls, out = run_cli(["update"])
        self.assertEqual(code, 0)
        self.assertEqual(calls[0][-3:], ["pip", "setuptools", "wheel"])  # derivados do Python: pip, setuptools e wheel
        self.assertEqual(calls[1][-1], cli.REPO_ZIP)
        self.assertIn("--upgrade", calls[1])
        self.assertEqual(calls[2][1:4], ["-m", "openflow", "libs"])  # processo novo: lê as bibliotecas da versão recém-instalada
        self.assertEqual(calls[3][1:], ["-m", "openflow", "models", "install", "--ask"])  # pergunta antes de baixar os modelos
        self.assertIn("Pronto", out)
        self.assertIn("gerenciador de pacotes", out)  # explica que o Python do sistema não é gerenciado nesse caso

    def test_update_skips_downloading_asta_when_it_is_already_the_latest(self):
        from openflow import __version__

        code, calls, out = run_cli(["update", "--no-python"], remote=__version__)
        self.assertEqual(code, 0)
        self.assertNotIn(cli.REPO_ZIP, [c[-1] for c in calls])
        self.assertIn("já é a versão mais recente", out)
        self.assertTrue(any(c[-1] == "libs" for c in calls))  # bibliotecas e modelos ainda são verificados
        # --force reinstala; versão mais nova publicada e consulta que falhou também instalam
        self.assertIn(cli.REPO_ZIP, [c[-1] for c in run_cli(["update", "--no-python", "--force"], remote=__version__)[1]])
        self.assertIn(cli.REPO_ZIP, [c[-1] for c in run_cli(["update", "--no-python"], remote="99.0.0")[1]])
        self.assertIn(cli.REPO_ZIP, [c[-1] for c in run_cli(["update", "--no-python"], remote=None)[1]])
        self.assertIn(cli.REPO_ZIP, [c[-1] for c in run_cli(["update", "--no-python"], env={"OPENFLOW_FORCE": "1"}, remote=__version__)[1]])

    def test_remote_version_reads_the_published_init_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "__init__.py"
            f.write_text('"""x"""\n\n__version__ = "0.2.10"\n')
            with mock.patch.dict(os.environ, {"OPENFLOW_VERSION_URL": f.as_uri()}):
                self.assertEqual(cli._remote_version(), "0.2.10")
                self.assertTrue(cli._flow_is_current() is (cli._version_tuple(cli.__version__) >= (0, 2, 10)))
            with mock.patch.dict(os.environ, {"OPENFLOW_VERSION_URL": (Path(tmp) / "nada").as_uri()}):
                self.assertIsNone(cli._remote_version())
                self.assertFalse(cli._flow_is_current())
        self.assertGreater(cli._version_tuple("0.2.10"), cli._version_tuple("0.2.9"))

    def test_flags_that_keep_the_system_python_alone(self):
        with mock.patch.object(cli, "_managed_app_dir", return_value=Path("/x/app")), mock.patch.object(cli, "_update_with_installer") as inst:
            calls = run_cli(["update", "--core"])[1]
            self.assertEqual(len(calls), 2)  # pip+setuptools+wheel e OpenFlow; nada de bibliotecas
            calls = run_cli(["update", "--no-python", "--extras", "docs"])[1]
            self.assertEqual(calls[2][-2:], ["--extras", "docs"])
            self.assertEqual(calls[3][1:5], ["-m", "openflow", "models", "install"])  # modelos pré-instalados também são verificados
            run_cli(["update"], env={"OPENFLOW_PYTHON": "keep"})
            inst.assert_not_called()

    def test_official_install_runs_the_installer_that_updates_python_too(self):
        script = b"#!/bin/sh\necho instalador\n"
        seen = {}

        def fake_run(cmd, *a, **k):
            seen["cmd"], seen["env"], seen["script"] = cmd, k.get("env"), Path(cmd[1]).read_bytes()
            return mock.Mock(returncode=0)

        urlopen = mock.MagicMock()
        urlopen.return_value.__enter__.return_value.read.return_value = script
        out = io.StringIO()
        with mock.patch.object(cli, "_managed_app_dir", return_value=Path("/home/u/.openflow/app")), mock.patch("urllib.request.urlopen", urlopen), \
                mock.patch.object(cli.subprocess, "run", side_effect=fake_run), mock.patch.object(cli.os, "name", "posix"), contextlib.redirect_stdout(out):
            code = cli.main(["update", "--extras", "docs,media"])
        self.assertEqual(code, 0)
        self.assertEqual(seen["cmd"][0], "sh")
        self.assertEqual(seen["script"], script)
        self.assertTrue(urlopen.call_args[0][0].endswith("/main/install.sh"))
        self.assertEqual((seen["env"]["OPENFLOW_APP_DIR"].replace("\\", "/"), seen["env"]["OPENFLOW_EXTRAS"]), ("/home/u/.openflow/app", "docs,media"))
        self.assertFalse(os.path.exists(seen["cmd"][1]))  # arquivo temporário apagado
        self.assertIn("Atualizando o Python", out.getvalue())

    def test_falls_back_when_the_installer_cannot_be_downloaded(self):
        with mock.patch.object(cli, "_managed_app_dir", return_value=Path("/home/u/.openflow/app")), mock.patch("urllib.request.urlopen", side_effect=OSError("sem rede")):
            code, calls, out = run_cli(["update"])
        self.assertEqual(code, 0)
        self.assertEqual(calls[1][-1], cli.REPO_ZIP)
        self.assertIn("Não foi possível baixar o instalador", out)

    def test_library_failures_do_not_fail_the_update_but_asta_failure_does(self):
        with mock.patch.object(cli, "_managed_app_dir", return_value=None):
            self.assertEqual(run_cli(["update"], results={"llama": 1})[0], 0)
            code, calls, _ = run_cli(["update"], results={cli.REPO_ZIP: 3})
        self.assertEqual((code, len(calls)), (3, 2))  # sem OpenFlow novo, nem tenta as bibliotecas

    def test_managed_app_dir_only_for_the_official_layout(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp).resolve() / "app"
            (app / "venv").mkdir(parents=True)
            (Path(tmp) / ".venv").mkdir()
            with mock.patch.dict(os.environ, {"OPENFLOW_APP_DIR": str(app)}):
                with mock.patch.object(cli.sys, "prefix", str(app / "venv")):
                    self.assertEqual(cli._managed_app_dir(), app)
                with mock.patch.object(cli.sys, "prefix", str(Path(tmp) / ".venv")):
                    self.assertIsNone(cli._managed_app_dir())  # ambiente de desenvolvimento / instalação manual


@unittest.skipUnless(sys.platform.startswith("linux") and os.path.exists("/bin/sh"), "instalador sh só em Linux")
class PythonInstallerTests(unittest.TestCase):
    """O install.sh instala/atualiza o Python pelo gerenciador de pacotes do sistema (simulado por comandos falsos no PATH)."""

    ROOT = Path(__file__).resolve().parent.parent

    def setUp(self):
        import shutil
        import tempfile

        self.tmp = Path(tempfile.mkdtemp(prefix="flow-inst-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for tool in ("uname", "mkdir", "rm", "ln", "id", "cat", "dirname", "env"):
            real = shutil.which(tool)
            if real:
                (self.bin / tool).symlink_to(real)
        self.log = self.tmp / "apt.log"
        (self.bin / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
        (self.bin / "apt-get").write_text(f'#!/bin/sh\necho "$@" >> {self.log}\ncase "$1" in install) [ -e {self.bin}/python3 ] || ln -s {sys.executable} {self.bin}/python3;; esac\nexit 0\n')
        for f in ("sudo", "apt-get"):
            (self.bin / f).chmod(0o755)

    def with_python(self):
        (self.bin / "python3").symlink_to(sys.executable)

    def install(self, **env):
        import subprocess

        e = {"PATH": str(self.bin), "HOME": str(self.tmp / "home"), "OPENFLOW_APP_DIR": str(self.tmp / "app"), "OPENFLOW_BIN_DIR": str(self.tmp / "ubin"), "OPENFLOW_LANG": "pt", "OPENFLOW_STEP": "python",
             "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", **env}
        (self.tmp / "home").mkdir(exist_ok=True)
        r = subprocess.run(["/bin/sh", str(self.ROOT / "install.sh")], capture_output=True, text=True, env=e, timeout=300)
        return r.returncode, r.stdout + r.stderr

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_missing_python_is_installed_with_its_venv_and_pip_packages(self):
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("instalando", out)
        self.assertIn("install -y python3 python3-venv python3-pip", " ".join(self.calls()))
        self.assertTrue((self.tmp / "app" / "venv" / "bin" / "python").exists())
        self.assertIn("prontos", out)

    def test_existing_python_is_upgraded_by_default(self):
        self.with_python()
        code, out = self.install()
        self.assertEqual(code, 0, out)
        self.assertIn("Python já instalado", out)
        self.assertIn("verificando se há versão mais nova", out)
        self.assertTrue(any(c.startswith("install -y python3 python3-venv python3-pip") for c in self.calls()))

    def test_keep_mode_never_touches_the_package_manager(self):
        self.with_python()
        code, out = self.install(OPENFLOW_PYTHON="keep")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.calls(), [])
        code, out = self.install(OPENFLOW_PYTHON="keep", PATH=str(self.tmp / "vazio"))  # sem Python e sem permissão para instalar
        self.assertNotEqual(code, 0)
        self.assertIn("Python 3.9 ou superior não encontrado", out)

    @unittest.skipIf(sys.version_info < (3, 10), "precisa de um Python mais novo que o 3.9 simulado")
    def test_a_venv_built_with_an_older_python_is_recreated(self):
        self.with_python()
        old = self.tmp / "app" / "venv" / "bin"
        old.mkdir(parents=True)
        (old / "python").write_text("#!/bin/sh\necho 3.8\n")
        (old / "python").chmod(0o755)
        code, out = self.install(OPENFLOW_PYTHON="keep")
        self.assertEqual(code, 0, out)
        self.assertIn("Recriando o ambiente", out)
        import subprocess

        ver = subprocess.run([str(self.tmp / "app" / "venv" / "bin" / "python"), "-c", "import sys; print(sys.version_info[:2] >= (3, 10))"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(ver, "True")

    def fake_installed_asta(self, version):
        """Deixa no venv um OpenFlow falso na versão dada (como se o instalador já tivesse rodado antes)."""
        code, out = self.install(OPENFLOW_PYTHON="keep")
        self.assertEqual(code, 0, out)
        venv = self.tmp / "app" / "venv"
        site = next(venv.glob("lib/python*/site-packages"))
        (site / "openflow").mkdir()
        (site / "openflow" / "__init__.py").write_text(f'__version__ = "{version}"\n')
        stub = venv / "bin" / "flow"
        self.stub_log = self.tmp / "flow-calls.log"
        stub.write_text(f'#!/bin/sh\necho "$@" >> {self.stub_log}\nexit 0\n')
        stub.chmod(0o755)

    def run_full(self, remote, models="none", **env):
        remote_file = self.tmp / "remote_init.py"
        remote_file.unlink(missing_ok=True)
        if remote is not None:
            remote_file.write_text(f'"""x"""\n__version__ = "{remote}"\n')
        if models is not None:
            env["OPENFLOW_MODELS"] = models
        return self.install(OPENFLOW_STEP="", OPENFLOW_PYTHON="keep", OPENFLOW_EXTRAS="none", OPENFLOW_VERSION_URL=remote_file.as_uri(), **env)

    def test_asta_already_at_the_latest_version_is_not_downloaded_again(self):
        self.with_python()
        self.fake_installed_asta("0.2.9")
        code, out = self.run_full("0.2.9")
        self.assertEqual(code, 0, out)
        self.assertIn("Ambiente já existe", out)
        self.assertIn("já instalado e na versão mais recente — nada a baixar", out)
        self.assertNotIn("Baixando e instalando OpenFlow", out)
        self.assertIn("OpenFlow 0.2.9 já estava atualizado", out)
        code, out = self.run_full("0.2.8")  # a publicada é mais antiga que a instalada: nada a fazer também
        self.assertIn("nada a baixar", out)

    def test_asta_is_downloaded_when_newer_forced_or_the_check_fails(self):
        self.with_python()
        self.fake_installed_asta("0.2.9")
        for remote, env in (("0.2.10", {}), ("0.2.9", {"OPENFLOW_FORCE": "1"}), (None, {})):
            code, out = self.run_full(remote, **env)
            self.assertIn("Baixando e instalando OpenFlow", out, (remote, env))  # PIP_NO_INDEX=1: o pip de verdade falha, o que basta para provar a tentativa
            self.assertNotIn("nada a baixar", out)

    def test_the_installer_asks_before_downloading_the_preinstalled_models(self):
        self.with_python()
        self.fake_installed_asta("0.2.9")

        def flow_calls():
            return self.stub_log.read_text().splitlines() if self.stub_log.exists() else []

        code, out = self.run_full("0.2.9", models=None)  # sem OPENFLOW_MODELS: o OpenFlow pergunta (sim/não) no terminal
        self.assertEqual(code, 0, out)
        self.assertEqual(flow_calls(), ["models install --ask", "native setup"])   # e, no fim, o Rust (pergunta/atualiza)
        self.stub_log.unlink()
        self.run_full("0.2.9", models="all")  # escolha explícita: baixa sem perguntar
        self.assertEqual(flow_calls(), ["models install", "native setup"])
        self.stub_log.unlink()
        code, out = self.run_full("0.2.9", models="none")
        self.assertEqual(flow_calls(), ["native setup"])   # o Rust é uma etapa à parte: OPENFLOW_RUST=no a pula
        self.assertIn("pulados", out)

    def test_python_only_flag_stops_before_installing_asta(self):
        import subprocess

        self.with_python()
        r = subprocess.run(["/bin/sh", str(self.ROOT / "install.sh"), "--python-only"], capture_output=True, text=True,
                           env={"PATH": str(self.bin), "HOME": str(self.tmp / "home"), "OPENFLOW_APP_DIR": str(self.tmp / "app"), "OPENFLOW_LANG": "pt", "OPENFLOW_PYTHON": "keep", "PIP_NO_INDEX": "1"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("prontos", r.stdout)
        self.assertNotIn("Baixando e instalando OpenFlow", r.stdout)


class InstallerTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent

    def test_installers_install_libraries_by_default_and_never_abort_for_them(self):
        sh = (self.ROOT / "install.sh").read_text(encoding="utf-8")
        ps = (self.ROOT / "install.ps1").read_text(encoding="utf-8")
        for src in (sh, ps):
            self.assertIn("models install", src)  # modelos pré-instalados (OPENFLOW_MODELS=none pula)
            self.assertIn("OPENFLOW_MODELS", src)
            self.assertIn("flow libs" if src is sh else "libs", src)
            self.assertIn("none", src)  # dá para pular com OPENFLOW_EXTRAS=none
        self.assertIn("LIBS_FAILED", sh)  # falha de biblioteca = aviso
        self.assertIn("$libsFailed", ps)
        # PowerShell 5.1: com ErrorActionPreference=Stop, o stderr de programas externos (mesmo com 2>$null) vira NativeCommandError
        self.assertNotRegex(ps, r"(?m)^\$ErrorActionPreference\s*=\s*'Stop'")
        self.assertIn("$ErrorActionPreference = 'Continue'", ps)
        # o comando `flow` precisa funcionar logo após instalar: PATH do usuário (aceitando Path vazio) e PATH deste terminal, antes das bibliotecas
        self.assertIn("if ($userPath)", ps)
        self.assertIn("$env:Path = $env:Path.TrimEnd(';')", ps)
        self.assertLess(ps.index("$env:Path = $env:Path.TrimEnd(';')"), ps.index("& $flow libs"))
        self.assertNotIn("$userPath.TrimEnd", ps)  # com Path vazio (null) isso falha em silêncio e o PATH nunca era configurado
        for needle in ("winget install --id Python.Python.3.12", "winget upgrade", "OPENFLOW_PYTHON", "pip setuptools wheel", "Recriando o ambiente"):
            self.assertIn(needle, ps)  # Windows: instala/atualiza o Python pelo winget e as ferramentas dele
        for needle in ("apt-get", "dnf", "pacman", "brew", "OPENFLOW_PYTHON", "pip setuptools wheel", "Recriando o ambiente"):
            self.assertIn(needle, sh)
        self.assertNotIn('SPEC="openflow[$EXTRAS]"', sh)
        self.assertIn("models install --ask", sh)  # pergunta sim/não antes de baixar os modelos pré-instalados
        self.assertIn("models install --ask", ps)

class AutoUpdateOnLaunchTests(unittest.TestCase):
    """`flow` (abrir) atualiza/instala tudo como o comando de instalação — só no OpenFlow instalado pelo instalador, com internet, e sem repetir a toda hora."""

    def go(self, tmp, remote, managed=True, env=None, args=None, installer=0):
        ns = cli.argparse.Namespace(**{"no_update": False, "home": str(tmp), **(args or {})})
        with mock.patch.object(cli, "_managed_app_dir", return_value=Path("/x") if managed else None), mock.patch.object(cli, "_remote_version", return_value=remote), \
                mock.patch.object(cli, "_update_with_installer", return_value=installer) as inst, mock.patch.object(cli.os, "execve") as ex, mock.patch.dict(os.environ, env or {}, clear=False):
            for k in ("OPENFLOW_NO_UPDATE", "OPENFLOW_UPDATE_EVERY"):
                if k not in (env or {}):
                    os.environ.pop(k, None)
            with contextlib.redirect_stdout(io.StringIO()):
                res = cli._auto_update(ns, ["--no-browser"])
        return res, inst, ex

    def test_a_newer_published_version_updates_everything_then_reopens(self):
        import tempfile

        with tempfile.TemporaryDirectory() as t:
            res, inst, ex = self.go(Path(t), "99.0.0")
            self.assertTrue(inst.called)
            if cli._windows():  # no Windows o instalador continua numa janela nova e o OpenFlow encerra (sem reabrir por execve)
                self.assertEqual((res, ex.called), (0, False))
            else:
                args = ex.call_args[0]
                self.assertEqual(args[1][1:], ["-m", "openflow", "--no-browser"])
                self.assertEqual(args[2]["OPENFLOW_NO_UPDATE"], "1")  # sem laço de atualização
            self.assertTrue((Path(t) / ".last-update").exists())

    def test_up_to_date_and_recently_checked_just_opens(self):
        import tempfile

        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".last-update").write_text("x")
            res, inst, ex = self.go(Path(t), cli.__version__)
            self.assertEqual((res, inst.called, ex.called), (None, False, False))
            res, inst, ex = self.go(Path(t), cli.__version__, env={"OPENFLOW_UPDATE_EVERY": "0"})  # 0 = a cada abertura
            self.assertTrue(inst.called)

    def test_never_touches_manual_installs_or_when_turned_off_or_offline_or_on_failure(self):
        import tempfile

        with tempfile.TemporaryDirectory() as t:
            for kw in ({"managed": False}, {"env": {"OPENFLOW_NO_UPDATE": "1"}}, {"args": {"no_update": True}}):
                res, inst, ex = self.go(Path(t), "99.0.0", **kw)
                self.assertEqual((res, inst.called), (None, False), kw)
            res, inst, ex = self.go(Path(t), None)   # sem internet
            self.assertEqual((res, inst.called), (None, False))
            res, inst, ex = self.go(Path(t), "99.0.0", installer=1)   # falhou: abre como está
            self.assertEqual((res, ex.called), (None, False))
            self.assertFalse((Path(t) / ".last-update").exists())

    def test_windows_closes_so_the_installer_can_replace_files(self):
        import tempfile

        with tempfile.TemporaryDirectory() as t, mock.patch.object(cli, "_windows", return_value=True):
            res, inst, ex = self.go(Path(t), "99.0.0")
            self.assertEqual((res, ex.called), (0, False))


if __name__ == "__main__":
    unittest.main()
