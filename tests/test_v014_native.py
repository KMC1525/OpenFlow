"""v0.14 — núcleo Rust v3 e o que ele sustenta: vários agentes locais (fila com prioridade, pool de modelos), armazenamento (varredura, duplicados, limpeza) e menos CPU."""
import os
import random
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import native, perf, scheduler  # noqa: E402
from openflow.storage import Store  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402
from tests.helpers import ServerCase  # noqa: E402

G = 1 << 30
NATIVE = native.available() and native.status()["ops"]


def python_only():
    """Roda o bloco com o núcleo desligado (equivalente em Python)."""
    return mock.patch.object(native, "_lib3", return_value=None)


class AgentPlanTests(unittest.TestCase):
    CASES = [(6, 1, 5 * G, 1 << 28, 32 * G, 0, 0, 8, 16, 1), (6, 0, 0, 0, 8 * G, 0, 0, 4, 8, 1), (6, 0, 0, 0, 8 * G, 0, 0, 4, 8, 0), (5, 2, 5 * G, 1 << 30, 16 * G, 8 * G, 0, 6, 12, 2),
             (1, 1, 2 * G, 1 << 26, 4 * G, 0, 0, 2, 4, 0), (3, 2, 9 * G, 1 << 30, 64 * G, 0, 1, 10, 10, 1)]

    def test_embedded_model_serializes_agents_with_a_priority_queue(self):
        with python_only():
            r = native.plan_agents(*self.CASES[0])
        self.assertEqual((r["parallel"], r["queue"]), (1, "priority"))
        self.assertTrue(r["share_prefix"] and r["notes"])

    def test_cloud_agents_run_in_parallel_up_to_what_the_mode_allows(self):
        with python_only():
            self.assertEqual(native.plan_agents(*self.CASES[1])["parallel"], 4)
            self.assertEqual(native.plan_agents(*self.CASES[2])["parallel"], 2)   # leve

    def test_light_mode_keeps_only_one_model_resident(self):
        with python_only():
            self.assertEqual(native.plan_agents(*self.CASES[2])["resident_models"], 1)
            self.assertEqual(native.plan_agents(6, 1, 2 * G, 0, 64 * G, 0, 0, 8, 16, 2)["resident_models"], 3)

    @unittest.skipUnless(NATIVE, "núcleo Rust (interface 3) não compilado")
    def test_rust_and_python_agree_on_every_case_and_random_ones(self):
        rnd = random.Random(14)
        cases = list(self.CASES) + [(rnd.randint(1, 12), rnd.randint(0, 2), rnd.randint(1, 40) * G // 4, rnd.randint(0, 4) * G // 4, rnd.randint(1, 128) * G // 2, rnd.choice([0, 0, 8 * G, 24 * G]),
                                      rnd.randint(0, 1), rnd.randint(1, 16), rnd.randint(1, 32), rnd.randint(0, 2)) for _ in range(200)]
        for c in cases:
            a = native.plan_agents(*c)
            with python_only():
                b = native.plan_agents(*c)
            self.assertEqual(a, b, c)


class PriorityLockTests(unittest.TestCase):
    def test_interactive_requests_jump_ahead_of_background_ones(self):
        lock = scheduler.PriorityLock()
        order = []
        lock.acquire()   # alguém está gerando

        def worker(name, level, started):
            scheduler.set_priority(level)
            started.set()
            with lock:
                order.append(name)
                time.sleep(0.02)

        threads = []
        for name, level in (("fundo-1", scheduler.BACKGROUND), ("fundo-2", scheduler.BACKGROUND), ("chat", scheduler.INTERACTIVE)):
            ev = threading.Event()
            t = threading.Thread(target=worker, args=(name, level, ev))
            t.start()
            ev.wait()
            time.sleep(0.05)   # garante a ordem de chegada: fundo-1, fundo-2, chat
            threads.append(t)
        self.assertEqual(lock.waiting, 3)
        lock.release()
        for t in threads:
            t.join(5)
        self.assertEqual(order, ["chat", "fundo-1", "fundo-2"])   # o chat passou na frente; os de fundo seguem na ordem de chegada

    def test_a_waiter_that_gives_up_does_not_block_the_queue(self):
        lock = scheduler.PriorityLock()
        lock.acquire()
        got = []

        def waiter():
            with lock:
                got.append(1)

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.05)
        lock.release()
        t.join(5)
        self.assertEqual(got, [1])
        self.assertFalse(lock.locked())


class ModelPoolTests(TmpCase):
    def test_a_second_model_stays_resident_only_when_the_plan_allows_it(self):
        from openflow.providers import local_llama as ll

        loads = []

        class Llama:
            def __init__(self, **kw):
                loads.append(Path(kw["model_path"]).name)

            def n_ctx(self):
                return 4096

            def tokenize(self, b, add_bos=False):
                return list(b)

            def create_chat_completion(self, messages, temperature=0.8, max_tokens=64, stream=False, **kw):
                return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

        fake = type(sys)("llama_cpp")
        fake.Llama = Llama
        a, b = self.tmp / "a.gguf", self.tmp / "b.gguf"
        a.write_bytes(b"x")
        b.write_bytes(b"x")
        info = {"bytes": 2 * G, "layers": 24, "kv_bytes_per_token": 65536, "ctx_train": 8192, "arch": "llama", "name": "x", "quant": "Q4", "params": 3e9}
        mem = {"ram_total": 64 * G, "ram_avail": 64 * G, "vram_total": 0, "vram_free": 0, "unified": False, "phys": 8, "logical": 16, "features": []}
        hw = {"tier": "high", "ram_gb": 64, "cpus": 16, "gpu": "", "os": "Linux", "arch": "x86_64"}
        released = []
        for mode, resident in (("max", 2), ("light", 1)):
            loads.clear()
            ll._CACHE.clear()
            ll._PATHS.clear()
            ll._CTX_FLOOR.clear()
            with mock.patch.dict(sys.modules, {"llama_cpp": fake}), mock.patch.object(ll.native, "model_info", return_value=info), mock.patch.object(ll.perf, "memory_state", return_value=mem), \
                    mock.patch.object(ll, "hardware_info", return_value=hw), mock.patch.object(ll, "_release", side_effect=released.append):
                pa = ll.LocalLlamaProvider({"model": str(a), "models_dir": str(self.tmp), "performance": {"mode": mode}})
                pb = ll.LocalLlamaProvider({"model": str(b), "models_dir": str(self.tmp), "performance": {"mode": mode}})
                pa.chat([{"role": "user", "content": "oi"}])
                pb.chat([{"role": "user", "content": "oi"}])
                pa.chat([{"role": "user", "content": "oi"}])   # voltou ao primeiro: se os dois ficam residentes, não recarrega
            self.assertEqual(loads, ["a.gguf", "b.gguf"] if resident == 2 else ["a.gguf", "b.gguf", "a.gguf"], mode)
            self.assertEqual(len(ll._CACHE), resident, mode)
        self.assertTrue(released)   # ao descartar um modelo, a memória é devolvida ao sistema
        ll._CACHE.clear()
        ll._PATHS.clear()


class CpuSavingTests(unittest.TestCase):
    FF = "/usr/bin/ffmpeg"

    def test_light_and_balanced_modes_use_fewer_threads_and_a_lower_priority(self):
        si = {"physical": 8, "logical": 16}
        with mock.patch.object(native, "sys_info", return_value=si), mock.patch.object(perf.shutil, "which", return_value="/usr/bin/nice"), mock.patch.object(perf.os, "name", "posix"):
            cmd, kw = perf.wrap_command([self.FF, "-i", "a.mp4", "o.mp4"], {"mode": "light"})
            self.assertEqual(cmd[:3], ["nice", "-n", "10"])
            self.assertEqual(cmd[cmd.index("-threads") + 1], "4")   # metade dos 8 núcleos físicos
            self.assertEqual(cmd[-3:], ["-threads", "4", "o.mp4"])   # e também no codificador, logo antes do arquivo de saída
            cmd, _ = perf.wrap_command([self.FF, "-i", "a.mp4", "o.mp4"], {"mode": "balanced"})
            self.assertEqual(cmd[cmd.index("-threads") + 1], "7")
            cmd, kw = perf.wrap_command([self.FF, "-i", "a.mp4", "o.mp4"], {"mode": "max"})
            self.assertEqual(cmd, [self.FF, "-i", "a.mp4", "o.mp4"])   # máximo: do jeito de sempre

    def test_other_commands_and_explicit_threads_pass_through(self):
        with mock.patch.object(native, "sys_info", return_value={"physical": 4, "logical": 8}):
            self.assertEqual(perf.wrap_command(["ffprobe", "-i", "a"], {"mode": "light"})[0], ["ffprobe", "-i", "a"])
            cmd, _ = perf.wrap_command([self.FF, "-threads", "2", "-i", "a"], {"mode": "light"})
            self.assertEqual(cmd.count("-threads"), 1)

    def test_windows_lowers_the_priority_class(self):
        with mock.patch.object(native, "sys_info", return_value={"physical": 4, "logical": 8}), mock.patch.object(perf.os, "name", "nt"):
            _cmd, kw = perf.wrap_command(["ffmpeg.exe", "-i", "a"], {"mode": "balanced"})
            self.assertEqual(kw["creationflags"], 0x4000)


class MemoryTests(TmpCase):
    def test_release_and_evict_never_raise(self):
        p = self.tmp / "m.bin"
        p.write_bytes(os.urandom(100_000))
        self.assertIn(native.evict_file(p), (0, 1))
        self.assertEqual(native.evict_file(self.tmp / "nao"), -1)
        self.assertIsInstance(native.release_memory(), int)
        with python_only():
            self.assertIn(native.evict_file(p), (0, 1))
            self.assertIsInstance(native.release_memory(), int)


class CertificateTests(unittest.TestCase):
    def test_a_python_without_root_certificates_falls_back_to_the_system_ones(self):
        import ssl

        from openflow import util

        empty = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)   # como o Python do python.org no macOS antes do «Install Certificates»
        self.assertEqual(empty.cert_store_stats()["x509_ca"], 0)
        system = next((p for p in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/cert.pem") if os.path.isfile(p)), "")
        if not system:
            self.skipTest("sem bundle de certificados neste sistema")
        fake_certifi = type(sys)("certifi")
        fake_certifi.where = lambda: system
        with mock.patch.object(ssl, "create_default_context", return_value=empty), mock.patch.dict(sys.modules, {"certifi": fake_certifi}), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SSL_CERT_FILE", None)
            os.environ.pop("SSL_CERT_DIR", None)
            ctx = util.ssl_context()
        self.assertGreater(ctx.cert_store_stats()["x509_ca"], 0)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)   # nunca desliga a verificação


if __name__ == "__main__":
    unittest.main()


class PrebuiltCoreTests(TmpCase):
    """O núcleo Rust é obrigatório na instalação: sem compilador, baixa a biblioteca pronta da Release e confere o SHA-256."""

    def serve(self, files):
        import http.server
        import socketserver

        root = self.tmp / "www"
        root.mkdir()
        for name, data in files.items():
            (root / name).write_bytes(data)

        class H(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(root), **k)

            def log_message(self, *a):
                pass

        srv = socketserver.TCPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}"

    def built_lib(self):
        for cand in (os.environ.get("OPENFLOW_NATIVE_LIB"), str(native.SRC / "target" / "release" / native._libname()), str(native.native_dir() / native._libname())):
            if cand and os.path.isfile(cand):
                return Path(cand).read_bytes()
        return None

    def env(self, url):
        return mock.patch.dict(os.environ, {"OPENFLOW_HOME": str(self.tmp / "home"), "OPENFLOW_NATIVE_URL": url, "OPENFLOW_NATIVE_LIB": "", "OPENFLOW_NO_NATIVE": ""})

    def sums(self, data, name=None):
        import hashlib

        return f"{hashlib.sha256(data).hexdigest()}  {name or native.prebuilt_name()}\n".encode()

    def test_the_prebuilt_library_is_downloaded_verified_and_activated(self):
        lib = self.built_lib()
        if lib is None:
            self.skipTest("núcleo ainda não compilado neste ambiente")
        url = self.serve({"SHA256SUMS.txt": self.sums(lib), native.prebuilt_name(): lib})
        with self.env(url):
            self.assertEqual(native.fetch_prebuilt(verbose=False), 0)
            self.assertTrue((self.tmp / "home" / "native" / native._libname()).is_file())
            self.assertTrue(native.available())
            self.assertEqual(native.status()["abi"], native.ABI)
        native.load(force=True)

    def test_a_library_that_does_not_match_the_published_hash_is_discarded(self):
        lib = b"\x7fELF" + os.urandom(2000)
        url = self.serve({"SHA256SUMS.txt": self.sums(b"outra coisa"), native.prebuilt_name(): lib})
        with self.env(url):
            self.assertEqual(native.fetch_prebuilt(verbose=False), 1)
            self.assertFalse((self.tmp / "home" / "native" / native._libname()).exists())

    def test_a_signed_but_broken_library_is_never_installed(self):
        lib = os.urandom(3000)   # hash certo, mas não é uma biblioteca de verdade
        url = self.serve({"SHA256SUMS.txt": self.sums(lib), native.prebuilt_name(): lib})
        with self.env(url):
            self.assertEqual(native.fetch_prebuilt(verbose=False), 1)
            self.assertFalse((self.tmp / "home" / "native" / native._libname()).exists())
            self.assertFalse((self.tmp / "home" / "native" / (native._libname() + ".new")).exists())

    def test_a_release_without_this_platform_is_a_clean_failure(self):
        url = self.serve({"SHA256SUMS.txt": self.sums(b"x", "flow-core-plan9-mips.so")})
        with self.env(url):
            self.assertEqual(native.fetch_prebuilt(verbose=False), 1)

    def test_ensure_respects_the_opt_out_and_the_daily_stamp(self):
        with self.env("http://127.0.0.1:9"), mock.patch.object(native, "available", return_value=False), mock.patch.object(native, "fetch_prebuilt", return_value=1) as fetch:
            with mock.patch.dict(os.environ, {"OPENFLOW_NO_NATIVE": "1"}):
                native.ensure(wait=True)
            fetch.assert_not_called()
            native.ensure(wait=True)
            native.ensure(wait=True)   # no mesmo dia: não tenta de novo
            self.assertEqual(fetch.call_count, 1)


class SetupFlowTests(unittest.TestCase):
    """`flow native setup` no v0.14: a biblioteca pronta da Release primeiro; compilar na máquina só se ela faltar; sem compilador nem biblioteca, segue em Python sem baixar Rust à toa."""

    def run_setup(self, *, active=False, abi=native.ABI, marker="", prebuilt=1, toolchain=True, cargo=False):
        import contextlib
        import io

        calls = []
        out = io.StringIO()
        from openflow import __version__

        with mock.patch.object(native, "available", return_value=active), mock.patch.object(native, "status", return_value={"abi": abi, "path": "/x/lib", "active": active}), \
                mock.patch.object(native, "installed_for", return_value=marker or __version__), mock.patch.object(native, "fetch_prebuilt", side_effect=lambda *a, **k: (calls.append("prebuilt"), prebuilt)[1]), \
                mock.patch.object(native, "_toolchain_ok", return_value=toolchain), mock.patch.object(native, "find_tool", side_effect=lambda n: "/x/cargo" if cargo else None), \
                mock.patch.object(native, "install_rust", side_effect=lambda: (calls.append("install"), 0)[1]), mock.patch.object(native, "update_rust", side_effect=lambda: calls.append("update")), \
                mock.patch.object(native, "build", side_effect=lambda *a, **k: (calls.append("build"), 0)[1]), contextlib.redirect_stdout(out), mock.patch.dict(os.environ, {"OPENFLOW_LANG": "pt", "OPENFLOW_NATIVE_BUILD": ""}):
            code = native.setup("yes")
        return code, calls, out.getvalue()

    def test_an_active_core_of_this_version_is_left_alone(self):
        self.assertEqual(self.run_setup(active=True)[:2], (0, []))

    def test_an_old_or_missing_core_is_replaced_by_the_prebuilt_one_without_a_compiler(self):
        self.assertEqual(self.run_setup(active=True, abi=2, prebuilt=0)[:2], (0, ["prebuilt"]))
        self.assertEqual(self.run_setup(active=False, prebuilt=0, toolchain=False)[:2], (0, ["prebuilt"]))   # nem Rust nem compilador: não precisa

    def test_building_locally_is_only_the_fallback(self):
        code, calls, _ = self.run_setup(prebuilt=1, toolchain=True, cargo=False)
        self.assertEqual(calls, ["prebuilt", "install", "update", "build"])

    def test_without_a_compiler_it_does_not_download_rust_for_nothing(self):
        code, calls, out = self.run_setup(prebuilt=1, toolchain=False)
        self.assertEqual((code, calls), (0, ["prebuilt"]))
        self.assertIn("Python", out)
