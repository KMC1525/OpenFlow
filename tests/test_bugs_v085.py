"""v0.85: bugs do downloader, achados com um servidor local que quebra de propósito (Range, queda no meio, resposta em pedaços, resto de download antigo):
1. uma resposta em pedaços (Transfer-Encoding: chunked, sem Content-Length) cortada no meio levantava `IncompleteRead` e derrubava o download em vez de retomar;
2. um `.part` de OUTRA versão do arquivo (maior que o original) recebia 416 e era devolvido como «completo»: o modelo ficava corrompido, maior que o original;
3. uma página de erro/login/portal de rede baixada com status 200 virava um «modelo» .gguf (só falhava ao carregar): agora o arquivo é conferido («GGUF») antes de ganhar o nome final."""
import hashlib
import os
import socketserver
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from openflow import dl, hf
from openflow.providers.base import ProviderError

DATA = os.urandom(300_000)
STATE = {"mode": "normal", "dropped": False}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def do_GET(self):
        mode = STATE["mode"]
        if mode == "html":
            body = b"<html>Please log in to the hotel wifi</html>"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        rng = self.headers.get("Range")
        start, end, code = 0, len(DATA) - 1, 200
        if rng:
            a, _, b = rng.replace("bytes=", "").partition("-")
            start = int(a)
            end = int(b) if b else len(DATA) - 1
            if start >= len(DATA):
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(DATA)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            code = 206
        body = DATA[start:end + 1]
        self.send_response(code)
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(DATA)}")
        if mode == "chunked-drop":
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            cut = len(body) if STATE["dropped"] else len(body) // 2
            for i in range(0, cut, 8000):
                c = body[i:min(i + 8000, cut)]
                self.wfile.write(b"%x\r\n" % len(c) + c + b"\r\n")
            if cut == len(body):
                self.wfile.write(b"0\r\n\r\n")
            else:
                STATE["dropped"] = True
                self.wfile.flush()
                self.connection.close()
                self.close_connection = True
            return
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(body)


class Server(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


class DownloaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/f"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        STATE.update(mode="normal", dropped=False)
        self.part = Path(tempfile.mkdtemp()) / "f.part"
        p = mock.patch.object(dl, "_backoff", lambda attempt, cancelled: time.sleep(0.02))
        p.start()
        self.addCleanup(p.stop)

    def same(self):
        return hashlib.md5(self.part.read_bytes()).digest() == hashlib.md5(DATA).digest()

    def test_a_chunked_response_cut_in_the_middle_is_resumed(self):
        STATE["mode"] = "chunked-drop"
        n = dl.fetch(self.url, self.part, {}, 1)
        self.assertEqual(n, len(DATA))
        self.assertTrue(self.same())
        self.assertTrue(STATE["dropped"])                                                      # a queda aconteceu de verdade

    def test_a_stale_bigger_part_is_discarded_not_returned_as_complete(self):
        self.part.write_bytes(DATA + b"leftover-from-another-version")
        n = dl.fetch(self.url, self.part, {}, 1)
        self.assertEqual(n, len(DATA))
        self.assertTrue(self.same())

    def test_a_part_that_is_exactly_the_whole_file_is_kept(self):
        self.part.write_bytes(DATA)
        before = self.part.stat().st_mtime_ns
        self.assertEqual(dl.fetch(self.url, self.part, {}, 1), len(DATA))
        self.assertTrue(self.same())
        self.assertEqual(self.part.stat().st_mtime_ns, before)                                 # nada foi baixado de novo

    def test_a_half_part_is_resumed(self):
        self.part.write_bytes(DATA[:100_000])
        self.assertEqual(dl.fetch(self.url, self.part, {}, 1), len(DATA))
        self.assertTrue(self.same())


class VerifyTests(unittest.TestCase):
    def fetcher(self, content):
        def fake(url, part, headers, conns, progress, cancelled):
            part.write_bytes(content)
            return len(content)
        return fake

    def test_an_html_page_is_not_a_model(self):
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(dl, "fetch", self.fetcher(b"<html>login</html>")):
            with self.assertRaises(ProviderError) as cm:
                hf.download("acme/m", "m-Q4_K_M.gguf", tmp)
        self.assertIn("não é um modelo GGUF", str(cm.exception))
        self.assertEqual(list(tmp.iterdir()), [])                                              # nem o modelo falso nem o .part ficam

    def test_a_real_gguf_passes_and_other_files_are_not_checked(self):
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(dl, "fetch", self.fetcher(b"GGUF" + b"\0" * 100)):
            self.assertEqual(hf.download("acme/m", "m-Q4_K_M.gguf", tmp).name, "m-Q4_K_M.gguf")
        with mock.patch.object(dl, "fetch", self.fetcher(b"\x00\x01 not gguf but fine")):
            self.assertEqual(hf.download("acme/m", "vae/ae.safetensors", tmp, any_file=True).name, "ae.safetensors")

    def test_download_many_stops_on_the_bad_part_and_keeps_the_good_ones(self):
        tmp = Path(tempfile.mkdtemp())
        calls = []

        def fake(url, part, headers, conns, progress, cancelled):
            calls.append(url)
            part.write_bytes(b"GGUF-ok" if len(calls) == 1 else b"<html>")
            return 7
        with mock.patch.object(dl, "fetch", fake):
            with self.assertRaises(ProviderError):
                hf.download_many("acme/m", ["m-Q4_K_M-00001-of-00002.gguf", "m-Q4_K_M-00002-of-00002.gguf"], tmp)
        self.assertEqual(sorted(p.name for p in tmp.iterdir()), ["m-Q4_K_M-00001-of-00002.gguf"])   # a parte boa fica: o próximo download continua dela


class DownloadsPanelTests(unittest.TestCase):
    """Os trabalhos «Criar faixa» e «Modelo próprio» aparecem na aba Downloads e contam como «baixando» (limpeza de disco e mudança de pasta esperam)."""

    @classmethod
    def setUpClass(cls):
        import json
        import urllib.request

        from openflow.server import make_server
        from openflow.storage import Store

        cls.json, cls.urlopen = json, staticmethod(urllib.request.urlopen)
        cls.httpd, cls.app = make_server("127.0.0.1", 0, Store(Path(tempfile.mkdtemp())))
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def downloads(self):
        with self.urlopen(f"http://127.0.0.1:{self.port}/api/library/downloads", timeout=20) as r:
            return self.json.loads(r.read())

    def test_new_job_kinds_are_listed_with_their_progress(self):
        gate = threading.Event()

        def work(job):
            job.emit({"type": "start", "file": "flux-Q4_K.gguf"})
            job.emit({"type": "note", "message": "Criando flux-Q4_K.gguf"})
            gate.wait(20)
        jobs = [self.app.jobs.start("requant", work, {"title": "flux-Q4_K.gguf"}), self.app.jobs.start("tool_model", work, {"title": "acme/esrgan"})]
        try:
            time.sleep(0.3)
            data = self.downloads()
            kinds = {d["kind"]: d for d in data["downloads"]}
            self.assertEqual({k: kinds[k]["label"] for k in ("requant", "tool_model")}, {"requant": "Criar faixa (Q2–Q8)", "tool_model": "Modelo próprio"})
            self.assertEqual(kinds["requant"]["title"], "flux-Q4_K.gguf")
            self.assertEqual(data["running"], 2)
        finally:
            gate.set()

    def test_they_block_disk_cleaning_and_storage_moves(self):
        gate = threading.Event()
        job = self.app.jobs.start("requant", lambda j: gate.wait(20), {"title": "x"})
        try:
            time.sleep(0.2)
            self.assertTrue(any(self.app.jobs.running(k) for k in self.app.DOWNLOAD_KINDS))
        finally:
            gate.set()


if __name__ == "__main__":
    unittest.main()
