"""v0.91 — o programa `flow` em Rust de ponta a ponta: sobe de verdade numa porta livre e responde por HTTP.
Interface embutida, Host/Origin, configurações e anexos (feitos em Rust) e o repasse das demais rotas ao worker Python (inclusive o encerramento dele junto com o `flow`)."""
import http.client
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.rust_bin import ROOT, flow_bin

BIN = flow_bin()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(BIN, "sem o binário `flow` (cargo build em rust/)")
class RustServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Path(tempfile.mkdtemp(prefix="openflow-rs-"))
        cls.port = free_port()
        env = dict(os.environ, OPENFLOW_WORKER_SRC=str(ROOT), OPENFLOW_NO_UPDATE="1", OPENFLOW_NO_GUARD="1", OPENFLOW_HOME=str(cls.home), PYTHONIOENCODING="utf-8")
        cls.proc = subprocess.Popen([str(BIN), "--no-browser", "--no-update", "--port", str(cls.port), "--home", str(cls.home)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        t0 = time.time()
        while time.time() - t0 < 20:
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.3).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("o flow não abriu a porta")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        if cls.proc.stdout:
            cls.proc.stdout.close()

    def req(self, method, path, body=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        hdrs = dict(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=hdrs)
        r = conn.getresponse()
        payload = r.read()
        out = (r.status, dict(r.getheaders()), payload)
        conn.close()
        return out

    def js(self, method, path, body=None, **kw):
        st, _h, payload = self.req(method, path, body, **kw)
        return st, json.loads(payload)

    # ------------------------------------------------------------------ interface e segurança
    def test_the_embedded_ui_is_served(self):
        st, h, body = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn("text/html", h["Content-Type"])
        self.assertIn(b"OpenFlow", body)
        self.assertEqual(h.get("Cache-Control"), "no-store")
        st, h, body = self.req("GET", "/js/api.js")
        self.assertEqual((st, h["Content-Type"].split(";")[0]), (200, "text/javascript"))
        self.assertEqual(self.req("GET", "/nada.js")[0], 404)                  # arquivo que não existe
        self.assertEqual(self.req("GET", "/qualquer/rota/da/spa")[0], 200)    # rota do app: volta ao index.html
        self.assertEqual(self.req("GET", "/%2e%2e/%2e%2e/etc/passwd")[0], 404)
        self.assertEqual(self.req("POST", "/")[0], 405)

    def test_the_service_worker_carries_the_version(self):
        st, _h, body = self.req("GET", "/sw.js")
        self.assertEqual(st, 200)
        self.assertNotIn(b"__OPENFLOW_VERSION__", body)
        ver = subprocess.run([str(BIN), "version"], capture_output=True, text=True).stdout.strip()
        self.assertIn(ver.encode(), body)

    def test_host_and_origin_are_validated(self):
        self.assertEqual(self.js("GET", "/api/settings", headers={"Host": "evil.com"})[0], 403)
        st, body = self.js("POST", "/api/settings/reset", {"section": "ui"}, headers={"Origin": "http://evil.com"})
        self.assertEqual(st, 403)
        self.assertIn("Origem", body["error"])
        host = f"127.0.0.1:{self.port}"
        self.assertEqual(self.js("POST", "/api/settings/reset", {"section": "ui"}, headers={"Origin": f"http://{host}", "Host": host})[0], 200)

    def test_unknown_api_route_is_a_json_404(self):
        st, body = self.js("GET", "/api/isto/nao/existe")
        self.assertEqual(st, 404)
        self.assertEqual(body, {"error": "Rota não encontrada"})

    # ------------------------------------------------------------------ rotas feitas em Rust
    def test_settings_roundtrip_in_rust(self):
        self.js("POST", "/api/settings/reset", {"section": "ui"})   # os testes compartilham o servidor: parte do padrão
        st, s = self.js("GET", "/api/settings")
        self.assertEqual(st, 200)
        self.assertEqual(s["ui"]["theme"], "dark")
        self.assertEqual(s["hf"], {"token": "", "auto_support": True, "connections": 4, "token_set": False})
        st, s = self.js("PUT", "/api/settings", {"ui": {"theme": "light", "scale": 133}, "hf": {"token": " segredo "}})
        self.assertEqual((s["ui"]["theme"], s["ui"]["scale"], s["hf"]["token"], s["hf"]["token_set"]), ("light", 135, "", True))
        self.assertNotIn("segredo", self.req("GET", "/api/settings/export")[2].decode())     # a exportação nunca leva o token
        on_disk = json.loads((self.home / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["hf"]["token"], "segredo")
        st, exp = self.js("GET", "/api/settings/export")
        self.assertEqual(exp["schema"], "openflow.settings.v1")
        self.assertEqual(self.js("POST", "/api/settings/import", {"schema": "x"})[0], 400)
        st, imp = self.js("POST", "/api/settings/import", exp)
        self.assertIn("ui", imp["imported"])
        self.assertEqual(self.js("POST", "/api/settings/reset", {"section": "nope"})[0], 400)
        st, s = self.js("POST", "/api/settings/reset", {"section": "ui"})
        self.assertEqual((s["ui"]["theme"], s["ui"]["welcome_done"]), ("dark", True))
        self.assertEqual(self.js("PUT", "/api/settings", raw=b"[1]")[0], 400)

    def test_uploads_in_rust(self):
        st, meta = self.js("POST", "/api/uploads", headers={"X-Filename": "..%2Fmeu%20arquivo.txt", "Content-Type": "text/plain"}, raw=b"conteudo")
        self.assertEqual(st, 200)
        self.assertEqual((meta["name"], meta["size"], meta["mime"]), ("meu arquivo.txt", 8, "text/plain"))
        self.assertTrue(re.match(r"^u_[0-9a-f]{10}$", meta["id"]))
        self.assertEqual((self.home / "uploads" / meta["id"] / "meu arquivo.txt").read_bytes(), b"conteudo")
        self.assertEqual(self.js("DELETE", f"/api/uploads/{meta['id']}")[1], {"ok": True})
        self.assertEqual(self.js("DELETE", f"/api/uploads/{meta['id']}")[1], {"ok": False})
        self.js("PUT", "/api/settings", {"server": {"max_upload_mb": 1}})
        st, body = self.js("POST", "/api/uploads", raw=b"x" * (1024 * 1024 + 1), headers={"X-Filename": "grande.bin"})
        self.assertEqual(st, 413)
        self.js("PUT", "/api/settings", {"server": {"max_upload_mb": 200}})

    # ------------------------------------------------------------------ repasse ao worker Python
    def test_other_routes_go_to_the_python_worker(self):
        st, state = self.js("GET", "/api/state")
        self.assertEqual(st, 200)
        self.assertEqual(state["home"], str(self.home))
        st, listing = self.js("GET", "/api/projects")
        self.assertEqual(st, 200)
        st, made = self.js("POST", "/api/projects", {"template": "blank", "name": "via rust"})
        self.assertEqual(st, 201)
        st, got = self.js("GET", f"/api/projects/{made['id']}")
        self.assertEqual((st, got["name"]), (200, "via rust"))
        self.assertEqual(self.js("DELETE", f"/api/projects/{made['id']}")[0], 200)
        # as configurações gravadas pelo Rust valem para o worker (o mesmo arquivo)
        self.js("PUT", "/api/settings", {"ui": {"theme": "light"}})
        self.assertEqual(self.js("GET", "/api/state")[1]["settings"]["ui"]["theme"], "light")

    def test_sse_passes_through(self):
        st, made = self.js("POST", "/api/projects", {"template": "blank", "name": "sse"})
        st, run = self.js("POST", f"/api/projects/{made['id']}/run", {})
        self.assertEqual(st, 200)
        jid = run["job_id"]
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        conn.request("GET", f"/api/jobs/{jid}/events")
        r = conn.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn("text/event-stream", r.getheader("Content-Type"))
        seen = []
        buf = b""
        while True:
            chunk = r.read(1)
            if not chunk:
                break
            buf += chunk
            if buf.endswith(b"\n\n"):
                for line in buf.decode().splitlines():
                    if line.startswith("data:"):
                        seen.append(json.loads(line[5:]))
                buf = b""
                if seen and seen[-1].get("type") in ("end", "done"):
                    break
        conn.close()
        self.assertTrue(seen)
        self.js("DELETE", f"/api/projects/{made['id']}")

    def test_dev_commands_do_not_break_the_cli(self):
        r = subprocess.run([str(BIN), "version"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout.strip(), r"^\d+\.\d+\.\d+$")


@unittest.skipUnless(BIN, "sem o binário `flow`")
class WorkerLifecycleTests(unittest.TestCase):
    def test_the_worker_dies_with_the_flow_process(self):
        home = Path(tempfile.mkdtemp(prefix="openflow-rs2-"))
        port = free_port()
        env = dict(os.environ, OPENFLOW_WORKER_SRC=str(ROOT), OPENFLOW_NO_UPDATE="1", OPENFLOW_NO_GUARD="1", OPENFLOW_HOME=str(home))
        proc = subprocess.Popen([str(BIN), "--no-browser", "--no-update", "--port", str(port), "--home", str(home)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
                    break
                except OSError:
                    time.sleep(0.1)
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
            conn.request("GET", "/api/projects")
            self.assertEqual(conn.getresponse().status, 200)   # liga o worker
            conn.close()
            if os.name != "nt":
                kids = subprocess.run(["pgrep", "-f", f"openflow worker --port"], capture_output=True, text=True).stdout.split()
                self.assertTrue(kids, "o worker deveria estar rodando")
            proc.kill()   # à força: nada de limpeza no Rust
            proc.wait(10)
            if os.name != "nt":
                for _ in range(60):
                    still = [p for p in subprocess.run(["pgrep", "-f", "openflow worker --port"], capture_output=True, text=True).stdout.split()]
                    if not still:
                        break
                    time.sleep(0.2)
                self.assertFalse(still, "o worker ficou órfão")
        finally:
            proc.kill()


if __name__ == "__main__":
    unittest.main()
