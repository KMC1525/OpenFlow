"""v0.78: bugs achados na caça geral — o servidor recusa Content-Length inválido e corpo em pedaços (antes: lidos como «corpo vazio», e a requisição passava como válida), um id de projeto enorme é «não existe» (antes: erro 500 «File name too long»),
e o motivo de o núcleo Rust estar inativo sai no idioma do terminal (em inglês saía em português)."""
import ast
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("OPENFLOW_NO_GUARD", "1")

from openflow import native  # noqa: E402
from openflow.server import make_server  # noqa: E402
from openflow.storage import Store  # noqa: E402


class ServerEdgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd, _ = make_server("127.0.0.1", 0, Store(Path(tempfile.mkdtemp())))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def raw(self, request: bytes) -> bytes:
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        try:
            s.sendall(request)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            return data
        finally:
            s.close()

    def status(self, request: bytes) -> int:
        return int(self.raw(request).split(b" ", 2)[1])

    def post(self, headers: str, body: bytes = b"{}") -> int:
        return self.status(f"POST /api/projects HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n{headers}\r\n".encode() + body)

    def test_a_bad_content_length_is_refused(self):
        self.assertEqual(self.post("Content-Length: -5\r\n"), 400)
        self.assertEqual(self.post("Content-Length: abc\r\n"), 400)
        self.assertEqual(self.post("Content-Length: 99999999999\r\n"), 413)
        self.assertEqual(self.post("Content-Length: 2\r\n"), 201)                                   # o normal continua funcionando

    def test_a_chunked_body_is_refused_instead_of_read_as_empty(self):
        self.assertEqual(self.post("Transfer-Encoding: chunked\r\n", b"2\r\n{}\r\n0\r\n\r\n"), 411)

    def test_a_huge_project_id_is_not_a_server_error(self):
        for method, want in (("GET", 404), ("DELETE", 200)):                                        # apagar o que não existe é idempotente: {"ok": false}
            self.assertEqual(self.status(f"{method} /api/projects/{'a' * 300} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode()), want, method)

    def test_unknown_paths_never_serve_files_outside_the_web_folder(self):
        for p in ("/static/../../etc/passwd", "/%2e%2e/%2e%2e/etc/passwd", "/js/../../server.py"):
            raw = self.raw(f"GET {p} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
            self.assertNotIn(b"root:", raw)
            self.assertNotIn(b"import ", raw)


class TerminalReasonTests(unittest.TestCase):
    def test_the_reason_follows_the_terminal_language(self):
        with mock.patch.dict(os.environ, {"OPENFLOW_LANG": "en"}):
            self.assertEqual(native.translate_reason("desligado por OPENFLOW_NO_NATIVE"), "turned off by OPENFLOW_NO_NATIVE")
            self.assertIn("library not built", native.translate_reason("biblioteca não compilada (opcional: `flow native setup` instala o Rust e compila)"))
            self.assertEqual(native.translate_reason("x.so: versão da interface diferente (recompile com `flow native setup`)"), "x.so: interface version differs (rebuild with `flow native setup`)")
            self.assertEqual(native.translate_reason(""), "")
            self.assertEqual(native.translate_reason("erro desconhecido"), "erro desconhecido")                  # sem tradução: fica como veio
        with mock.patch.dict(os.environ, {"OPENFLOW_LANG": "pt"}):
            self.assertEqual(native.translate_reason("desligado por OPENFLOW_NO_NATIVE"), "desligado por OPENFLOW_NO_NATIVE")
            self.assertEqual(native.translate_reason("x.so: versão da interface diferente (recompile com `flow native setup`)"), "x.so: versão da interface diferente (recompile com `flow native setup`)")

    def test_every_fixed_reason_in_the_code_has_an_english_translation(self):
        import re

        from openflow import term_en

        src = (Path(native.__file__)).read_text(encoding="utf-8")
        for m in re.finditer(r'_REASON\s*=\s*(?:_REASON or )?("[^"\n]+")', src):
            self.assertIn(ast.literal_eval(m.group(1)), term_en.EN)


if __name__ == "__main__":
    unittest.main()
