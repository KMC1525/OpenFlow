"""v0.25: downloads rápidos — várias conexões (Range), retomada, novas tentativas e velocidade/tempo restante."""
import hashlib
import http.server
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from openflow import dl, hf
from openflow.providers.base import ProviderError
from tests.helpers import ServerCase

DATA = os.urandom(3_000_000)


def make_server(ranges=True, fail_first=0, delay=0.0):
    state = {"requests": [], "failed": 0}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = self.headers.get("Range")
            state["requests"].append(rng)
            data = DATA
            if rng and ranges:
                a, b = rng.split("=")[1].split("-")
                a, b = int(a), int(b) if b else len(data) - 1
                if fail_first and a > 0 and state["failed"] < fail_first:   # derruba a conexão no meio de uma faixa
                    state["failed"] += 1
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {a}-{b}/{len(data)}")
                    self.send_header("Content-Length", str(b - a + 1))
                    self.end_headers()
                    self.wfile.write(data[a:a + 100_000])
                    self.wfile.flush()
                    self.connection.close()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {a}-{b}/{len(data)}")
                self.send_header("Content-Length", str(b - a + 1))
                self.end_headers()
                for i in range(a, b + 1, 65536):
                    if delay:
                        time.sleep(delay)
                    self.wfile.write(data[i:min(b + 1, i + 65536)])
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p1 = mock.patch.object(dl, "MIN_SEGMENT", 500_000)
        self.p2 = mock.patch.object(dl, "MIN_PARALLEL", 1_000_000)
        self.p1.start(); self.p2.start()
        self.addCleanup(self.p1.stop); self.addCleanup(self.p2.stop)

    def run_fetch(self, srv, conns=4, progress=None, cancelled=lambda: False):
        part = self.tmp / "m.gguf.part"
        url = f"http://127.0.0.1:{srv.server_address[1]}/m"
        return part, dl.fetch(url, part, {}, conns, progress, cancelled)

    def test_parallel_download_is_byte_exact_and_uses_ranges(self):
        srv, st = make_server()
        part, total = self.run_fetch(srv)
        self.assertEqual((total, hashlib.sha256(part.read_bytes()).hexdigest()), (len(DATA), hashlib.sha256(DATA).hexdigest()))
        self.assertGreaterEqual(len([r for r in st["requests"] if r and r != "bytes=0-0"]), 4)    # faixas em paralelo
        self.assertFalse((self.tmp / "m.gguf.part.seg").exists())                                   # sem sobra do estado de retomada

    def test_server_without_range_falls_back_to_one_connection(self):
        srv, st = make_server(ranges=False)
        part, total = self.run_fetch(srv)
        self.assertEqual(part.read_bytes(), DATA)

    def test_one_connection_setting_skips_the_probe(self):
        srv, st = make_server()
        part, _ = self.run_fetch(srv, conns=1)
        self.assertEqual(part.read_bytes(), DATA)
        self.assertNotIn("bytes=0-0", st["requests"])

    def test_a_dropped_connection_is_retried_from_where_it_stopped(self):
        srv, st = make_server(fail_first=2)
        with mock.patch.object(dl, "_backoff", lambda a, c: None):
            part, total = self.run_fetch(srv)
        self.assertEqual(part.read_bytes(), DATA)
        self.assertEqual(st["failed"], 2)

    def test_cancel_keeps_the_state_and_a_new_run_resumes(self):
        srv, st = make_server(delay=0.05)
        seen = []
        calls = {"n": 0}

        def cancelled():
            calls["n"] += 1
            return calls["n"] > 2

        part = self.tmp / "m.gguf.part"
        url = f"http://127.0.0.1:{srv.server_address[1]}/m"
        with self.assertRaises(ProviderError):
            dl.fetch(url, part, {}, 4, lambda d, t: seen.append(d), cancelled)
        self.assertTrue((self.tmp / "m.gguf.part.seg").exists())
        before = len(st["requests"])
        total = dl.fetch(url, part, {}, 4, None, lambda: False)
        self.assertEqual((total, part.read_bytes()), (len(DATA), DATA))

    def test_progress_reaches_the_total(self):
        srv, _ = make_server()
        seen = []
        self.run_fetch(srv, progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(seen[-1], (len(DATA), len(DATA)))

    def test_old_single_connection_part_files_still_resume(self):
        srv, st = make_server()
        part = self.tmp / "m.gguf.part"
        part.write_bytes(DATA[:700_000])      # .part de uma versão antiga, sem arquivo .seg
        url = f"http://127.0.0.1:{srv.server_address[1]}/m"
        dl.fetch(url, part, {}, 4, None, lambda: False)
        self.assertEqual(part.read_bytes(), DATA)
        self.assertIn("bytes=700000-", st["requests"])

    def test_server_without_range_is_asked_only_once(self):
        srv, st = make_server(ranges=False)
        self.run_fetch(srv)
        self.assertEqual(len(st["requests"]), 1)          # a resposta do teste de faixas já era o arquivo: não pede de novo

    def test_no_internet_at_the_start_fails_at_once(self):
        t0 = time.time()
        with self.assertRaises(ProviderError):
            dl.fetch("http://127.0.0.1:9/x", self.tmp / "m.part", {}, 4, None, lambda: False)   # porta fechada
        self.assertLess(time.time() - t0, 5)

    def test_plan_splits_big_files_only(self):
        with mock.patch.object(dl, "MIN_SEGMENT", 32 << 20):
            self.assertEqual(len(dl._plan(10 << 20, 4)), 1)
            segs = dl._plan(1000 << 20, 4)
            self.assertEqual((len(segs), segs[0][0], segs[-1][1]), (4, 0, (1000 << 20) - 1))

    def test_connections_are_clamped(self):
        self.assertEqual((dl.clamp_connections(0), dl.clamp_connections(99), dl.clamp_connections("x"), dl.clamp_connections(6)), (1, 8, 4, 6))


class HfDownloadTests(unittest.TestCase):
    def test_hf_download_goes_through_the_fast_path_and_renames(self):
        tmp = Path(tempfile.mkdtemp())

        def fake(url, part, headers, conns, progress, cancelled):
            part.write_bytes(b"gguf")
            self.assertTrue(url.endswith("/acme/m/resolve/main/m-Q4_K_M.gguf"))
            self.assertEqual(conns, 5)
            return 4

        from openflow import diskuse

        with mock.patch.object(dl, "fetch", fake), mock.patch.object(diskuse, "kind_of", return_value="ssd"):
            hf.CONNECTIONS = 5
            try:
                out = hf.download("acme/m", "m-Q4_K_M.gguf", tmp)
            finally:
                hf.CONNECTIONS = 4
        self.assertEqual((out.name, out.read_bytes()), ("m-Q4_K_M.gguf", b"gguf"))
        self.assertFalse((tmp / "m-Q4_K_M.gguf.part").exists())


class SettingsAndSpeedTests(ServerCase):
    def test_connections_setting_is_saved_and_applied(self):
        s, r = self.c.json("PUT", "/api/settings", {"hf": {"connections": 6}})
        self.assertEqual(r["hf"]["connections"], 6)
        self.app._hf_token()
        self.assertEqual(hf.CONNECTIONS, 6)
        self.c.json("PUT", "/api/settings", {"hf": {"connections": 4}})
        self.app._hf_token()

    def test_library_downloads_report_speed_and_eta(self):
        def work(job):
            job.emit({"type": "start"})
            job.emit({"type": "progress", "done": 0, "total": 1000000})
            time.sleep(0.5)
            job.emit({"type": "progress", "done": 500, "total": 1000000})
            for _ in range(100):
                if job.cancelled:
                    break
                time.sleep(0.02)

        job = self.app.jobs.start("download", work, {"title": "m.gguf"})
        time.sleep(0.8)
        d = next(x for x in self.c.json("GET", "/api/library/downloads")[1]["downloads"] if x["id"] == job.id)
        self.assertGreater(d["speed"], 0)
        self.assertGreater(d["eta"], 0)
        job.cancel()
