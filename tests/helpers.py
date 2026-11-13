"""Utilitários de teste: servidor mock de provedores e cliente HTTP bruto."""
from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple


class MockProviderServer:
    """Imita APIs OpenAI-compatível e Anthropic; grava as requisições recebidas."""

    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silencioso
                pass

            def _body(self) -> dict:
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def _json(self, obj, status=200):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _sse(self, events: List[Tuple[Optional[str], dict]]):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for ev, obj in events:
                    if ev:
                        self.wfile.write(f"event: {ev}\n".encode())
                    self.wfile.write(b"data: " + (obj if isinstance(obj, bytes) else json.dumps(obj).encode()) + b"\n\n")
                self.wfile.flush()

            def do_GET(self):
                outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
                if self.path.endswith("/models"):
                    return self._json({"data": [{"id": "model-b"}, {"id": "model-a"}]})
                self._json({"error": "nope"}, 404)

            def do_POST(self):
                body = self._body()
                outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if self.path.endswith("/chat/completions"):
                    if body.get("model") == "reasoner" and "max_tokens" in body:
                        return self._json({"error": {"message": "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead."}}, 400)
                    if body.get("model") == "bad-key":
                        return self._json({"error": {"message": "Incorrect API key provided"}}, 401)
                    if body.get("stream"):
                        chunks = [{"choices": [{"delta": {"content": c}}]} for c in ("Olá", ", ", "mundo")]
                        return self._sse([(None, c) for c in chunks] + [(None, b"[DONE]")])
                    return self._json({"choices": [{"message": {"content": '{"ok": true, "text": "olá"}'}}]})
                if self.path.endswith("/v1/messages"):
                    if body.get("stream"):
                        evs: List[Tuple[Optional[str], dict]] = [("message_start", {"type": "message_start"})]
                        for c in ("Oi", " ", "Claude"):
                            evs.append(("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": c}}))
                        evs.append(("message_stop", {"type": "message_stop"}))
                        return self._sse(evs)
                    return self._json({"content": [{"type": "text", "text": "resposta anthropic"}]})
                self._json({"error": "nope"}, 404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class Client:
    """Cliente HTTP bruto (permite forjar Host/Origin)."""

    def __init__(self, port: int):
        self.port = port

    def req(self, method: str, path: str, body: Any = None, headers: Optional[Dict[str, str]] = None, raw: Optional[bytes] = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        hdrs = dict(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        out = (resp.status, dict(resp.getheaders()), payload)
        conn.close()
        return out

    def json(self, method: str, path: str, body: Any = None, **kw):
        status, _h, payload = self.req(method, path, body, **kw)
        try:
            return status, json.loads(payload)
        except ValueError:
            return status, payload

    def sse(self, path: str, body: Any = None, method: str = "GET", limit: int = 400) -> List[dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        hdrs = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=hdrs)
        resp = conn.getresponse()
        events: List[dict] = []
        buf = b""
        while len(events) < limit:
            chunk = resp.read(1)
            if not chunk:
                break
            buf += chunk
            if buf.endswith(b"\n\n"):
                for line in buf.decode().splitlines():
                    if line.startswith("data:"):
                        events.append(json.loads(line[5:]))
                buf = b""
                if events and events[-1].get("type") in ("end",):
                    break
        conn.close()
        return events


# --------------------------------------------------------------------------- bases dos testes (pasta temporária e servidor real em uma porta livre)
import shutil as _shutil  # noqa: E402
import sys as _sys  # noqa: E402
import tempfile as _tempfile  # noqa: E402
import unittest as _unittest  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))


class TmpCase(_unittest.TestCase):
    def setUp(self):
        self.tmp = _Path(_tempfile.mkdtemp(prefix="openflow-test-"))
        self.addCleanup(_shutil.rmtree, self.tmp, ignore_errors=True)


class ServerCase(_unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from openflow.server import make_server
        from openflow.storage import Store

        cls.tmp = _Path(_tempfile.mkdtemp(prefix="openflow-srv-"))
        cls.store = Store(cls.tmp)
        cls.httpd, cls.app = make_server("127.0.0.1", 0, cls.store)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.c = Client(cls.port)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        _shutil.rmtree(cls.tmp, ignore_errors=True)
