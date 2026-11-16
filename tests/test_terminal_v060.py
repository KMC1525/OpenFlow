"""v0.60: Windows e macOS no terminal — saída do console que não derruba o `flow`, instalador do Windows lido como UTF-8, porta exclusiva no Windows e memória/núcleos do macOS sem o núcleo Rust.

Não há Windows nem macOS aqui: o que depende do sistema é testado com saídas de comando e sockets simulados. O que vale em um computador de verdade não é verificado por estes testes."""
import io
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow import cli, native
from openflow.server import Server, exclusive_port, make_server
from openflow.storage import Store

GB = 1 << 30
ROOT = Path(__file__).resolve().parent.parent


class ConsoleTests(unittest.TestCase):
    def fake_stdout(self, encoding="cp1252"):
        raw = io.BytesIO()
        return raw, io.TextIOWrapper(raw, encoding=encoding, errors="strict", write_through=True)

    def test_a_character_the_code_page_lacks_crashed_print(self):
        raw, out = self.fake_stdout()
        with self.assertRaises(UnicodeEncodeError):
            out.write("✓ pronto")   # o que acontecia com `flow models list | clip` no Windows

    def test_stdio_safe_replaces_instead_of_crashing(self):
        raw, out = self.fake_stdout()
        err_raw, err = self.fake_stdout("cp437")
        with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
            cli.stdio_safe()
            print("✓ OpenFlow → atualizado … ⚠ ação")
            print("⚠ falhou", file=sys.stderr)
        text = raw.getvalue().decode("cp1252")
        self.assertIn("OpenFlow", text)
        self.assertIn("?", text)            # ✓ e → não existem em cp1252
        self.assertIn("…", text)            # … existe em cp1252 (0x85) e fica
        self.assertIn(b"?", err_raw.getvalue())

    def test_stdio_safe_ignores_streams_without_reconfigure(self):
        with mock.patch.object(sys, "stdout", io.StringIO()), mock.patch.object(sys, "stderr", object()):
            cli.stdio_safe()   # não levanta


class WindowsInstallerTests(unittest.TestCase):
    def test_without_bom_windows_powershell_breaks_the_script(self):
        ps1 = (ROOT / "install.ps1").read_bytes()
        self.assertFalse(ps1.startswith(b"\xef\xbb\xbf"))      # o publicado fica sem BOM (o `irm | iex` não o aceita no começo)
        as_ansi = ps1.decode("cp1252", errors="replace")       # como o PowerShell 5.1 lê um arquivo sem BOM
        self.assertIn("“", as_ansi)                       # o «✓» (E2 9C 93) vira «“»: fecha o texto no meio de "✓ …"
        self.assertEqual(ps1.decode("utf-8"), cli.powershell_script_bytes(ps1).decode("utf-8-sig"))

    def test_bom_is_added_once(self):
        self.assertEqual(cli.powershell_script_bytes(b"x"), b"\xef\xbb\xbfx")
        self.assertEqual(cli.powershell_script_bytes(b"\xef\xbb\xbfx"), b"\xef\xbb\xbfx")

    def test_flow_update_on_windows_runs_the_script_with_a_bom(self):
        script = "Write-Host \"✓ pronto — ação\"\n".encode("utf-8")
        seen = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_popen(cmd, **kw):
            seen["cmd"] = cmd
            seen["bytes"] = Path(cmd[cmd.index("-File") + 1]).read_bytes()
            return mock.Mock()
        args = mock.Mock(rust="", force=False, core=False, extras="")
        with mock.patch.object(cli, "_windows", return_value=True), mock.patch.object(cli, "_managed_app_dir", return_value=Path(tempfile.gettempdir())), \
                mock.patch("urllib.request.urlopen", return_value=Resp(script)), mock.patch.object(cli.subprocess, "Popen", fake_popen):
            self.assertEqual(cli._update_with_installer(args), 0)
        self.assertEqual(seen["bytes"], b"\xef\xbb\xbf" + script)
        self.assertIn("-File", seen["cmd"])
        os.unlink(seen["cmd"][seen["cmd"].index("-File") + 1])

    def test_flow_update_elsewhere_keeps_the_script_as_it_is(self):
        script = b"echo oi\n"
        seen = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_run(cmd, **kw):
            seen["bytes"] = Path(cmd[1]).read_bytes()
            return mock.Mock(returncode=0)
        args = mock.Mock(rust="", force=False, core=False, extras="")
        with mock.patch.object(cli, "_windows", return_value=False), mock.patch.object(cli, "_managed_app_dir", return_value=Path(tempfile.gettempdir())), \
                mock.patch("urllib.request.urlopen", return_value=Resp(script)), mock.patch.object(cli.subprocess, "run", fake_run):
            self.assertEqual(cli._update_with_installer(args), 0)
        self.assertEqual(seen["bytes"], script)   # sh: sem BOM


class PortTests(unittest.TestCase):
    def test_windows_gets_an_exclusive_port(self):
        calls = []
        sock = mock.Mock(setsockopt=lambda *a: calls.append(a))
        with mock.patch.object(socket, "SO_EXCLUSIVEADDRUSE", -5, create=True):
            self.assertTrue(exclusive_port(sock, windows=True))
            self.assertEqual(calls, [(socket.SOL_SOCKET, -5, 1)])
            calls.clear()
            self.assertFalse(exclusive_port(sock, windows=False))   # Linux/macOS: o SO_REUSEADDR normal basta
            self.assertEqual(calls, [])

    def test_windows_without_the_option_or_with_an_error_does_not_crash(self):
        sock = mock.Mock()
        with mock.patch.object(socket, "SO_EXCLUSIVEADDRUSE", None, create=True):   # Python sem a opção
            self.assertFalse(exclusive_port(sock, windows=True))
        sock.setsockopt.assert_not_called()
        sock.setsockopt.side_effect = OSError("x")
        with mock.patch.object(socket, "SO_EXCLUSIVEADDRUSE", -5, create=True):
            self.assertFalse(exclusive_port(sock, windows=True))

    def test_reuse_address_is_off_only_on_windows(self):
        self.assertEqual(Server.allow_reuse_address, os.name != "nt")

    def test_a_second_instance_cannot_take_the_same_port(self):
        st = Store(Path(tempfile.mkdtemp()))
        first, _app = make_server("127.0.0.1", 0, st)
        self.addCleanup(first.server_close)
        with self.assertRaises(OSError):
            make_server("127.0.0.1", first.server_address[1], st)


VM_STAT_ARM = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               10000.
Pages active:                            200000.
Pages inactive:                           50000.
Pages speculative:                         2000.
Pages purgeable:                           1000.
Pages wired down:                         90000.
"""
VM_STAT_INTEL = VM_STAT_ARM.replace("16384", "4096")


class MacTests(unittest.TestCase):
    def test_vm_stat_gives_the_memory_macos_can_hand_back(self):
        self.assertEqual(native.parse_vm_stat(VM_STAT_ARM), (10000 + 50000 + 2000 + 1000) * 16384)
        self.assertEqual(native.parse_vm_stat(VM_STAT_INTEL), (10000 + 50000 + 2000 + 1000) * 4096)
        self.assertEqual(native.parse_vm_stat("sem nada"), 0)

    def test_intel_cpu_features(self):
        self.assertEqual(native.parse_darwin_features("FPU SSE SSE4.2 AVX1.0 F16C FMA AVX2 AVX512F"), ["sse4.2", "avx", "avx2", "fma", "f16c", "avx512f"])
        self.assertEqual(native.parse_darwin_features(""), [])

    def test_python_fallback_reads_the_mac_instead_of_returning_zero_ram(self):
        table = {"hw.physicalcpu": "8", "hw.memsize": str(16 * GB), "machdep.cpu.features": "SSE4.2 AVX1.0 FMA F16C", "machdep.cpu.leaf7_features": "AVX2"}
        with mock.patch.object(native.sys, "platform", "darwin"), mock.patch.object(native, "_sysctl", lambda n: table.get(n, "")), mock.patch.object(native, "darwin_mem_avail", return_value=6 * GB), \
                mock.patch("platform.machine", return_value="x86_64"), mock.patch.object(native, "_lib2", return_value=None), mock.patch.object(native.os, "cpu_count", return_value=16):
            si = native.sys_info()
        self.assertEqual((si["logical"], si["physical"]), (16, 8))
        self.assertEqual(si["features"], ["sse4.2", "avx", "avx2", "fma", "f16c"])
        self.assertEqual((si["ram_total"], si["ram_avail"], si["ram_exact"]), (16 * GB, 6 * GB, True))

    def test_apple_silicon_has_no_hyper_threading(self):
        with mock.patch.object(native.sys, "platform", "darwin"), mock.patch.object(native, "_sysctl", lambda n: {"hw.memsize": str(8 * GB)}.get(n, "")), mock.patch.object(native, "darwin_mem_avail", return_value=0), \
                mock.patch("platform.machine", return_value="arm64"), mock.patch.object(native, "_lib2", return_value=None), mock.patch.object(native.os, "cpu_count", return_value=8):
            si = native.sys_info()
        self.assertEqual(si["physical"], 8)          # antes: metade dos lógicos
        self.assertEqual(si["features"], ["neon"])
        self.assertEqual(si["ram_total"], 8 * GB)
        self.assertEqual(si["ram_avail"], int(8 * GB * 0.6))   # sem vm_stat: a mesma estimativa do núcleo Rust

    def test_the_rust_estimate_is_replaced_by_the_real_reading_on_macos(self):
        core = {"logical": 8, "physical": 8, "features": ["neon"], "arch": "aarch64", "os": "macos", "ram_total": 16 * GB, "ram_avail": int(16 * GB * 0.6), "ram_exact": False}
        with mock.patch.object(native.sys, "platform", "darwin"), mock.patch.object(native, "_lib2", return_value=mock.Mock()), mock.patch.object(native, "_call_json", return_value=dict(core)), \
                mock.patch.object(native, "darwin_mem_avail", return_value=3 * GB):
            si = native.sys_info()
        self.assertEqual((si["ram_avail"], si["ram_exact"]), (3 * GB, True))
        exact = dict(core, ram_exact=True)
        with mock.patch.object(native.sys, "platform", "darwin"), mock.patch.object(native, "_lib2", return_value=mock.Mock()), mock.patch.object(native, "_call_json", return_value=dict(exact)), \
                mock.patch.object(native, "darwin_mem_avail", return_value=3 * GB):
            self.assertEqual(native.sys_info()["ram_avail"], exact["ram_avail"])   # exata: não mexe
        with mock.patch.object(native.sys, "platform", "linux"), mock.patch.object(native, "_lib2", return_value=mock.Mock()), mock.patch.object(native, "_call_json", return_value=dict(core)):
            self.assertEqual(native.sys_info()["ram_avail"], core["ram_avail"])    # outros sistemas: não mexe

    def test_vm_stat_is_read_once_per_two_seconds(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return mock.Mock(stdout=VM_STAT_ARM)
        native._DARWIN_AVAIL.update(t=0.0, v=0.0)
        with mock.patch.object(native.subprocess, "run", fake_run):
            a = native.darwin_mem_avail()
            b = native.darwin_mem_avail()
        self.assertEqual((a, b), (63000 * 16384, 63000 * 16384))
        self.assertEqual(len(calls), 1)
        native._DARWIN_AVAIL.update(t=0.0, v=0.0)

    def test_vm_stat_missing_gives_zero(self):
        native._DARWIN_AVAIL.update(t=0.0, v=0.0)
        with mock.patch.object(native.subprocess, "run", side_effect=OSError("sem vm_stat")):
            self.assertEqual(native.darwin_mem_avail(), 0)
        native._DARWIN_AVAIL.update(t=0.0, v=0.0)


if __name__ == "__main__":
    unittest.main()
