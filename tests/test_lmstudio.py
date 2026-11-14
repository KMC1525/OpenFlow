"""LM Studio: detecção do servidor, lista de modelos, modelo carregado, visão, instruções de erro, escolha automática e conversa com avatars."""
import json
import socket
import sys
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow.util import strip_reasoning  # noqa: E402
from openflow.providers import ProviderError, auto, build_provider, lmstudio  # noqa: E402
from openflow.storage import DEFAULT_SETTINGS  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402
from tests.helpers import ServerCase  # noqa: E402

MODELS = [
    {"id": "text-embedding-nomic", "type": "embeddings", "state": "loaded"},
    {"id": "qwen3-8b", "type": "llm", "state": "not-loaded", "arch": "qwen3", "quantization": "Q4_K_M", "max_context_length": 40960},
    {"id": "gemma-3-12b", "type": "vlm", "state": "loaded", "arch": "gemma3", "quantization": "Q4_K_M", "loaded_context_length": 8192},
    {"id": "llama-3.2-3b", "type": "llm", "state": "loaded", "arch": "llama", "quantization": "Q8_0"},
]


class FakeLMStudio:
    """Servidor falso do LM Studio: /api/v0/models (estado dos modelos), /v1/models e /v1/chat/completions (com streaming)."""

    def __init__(self, models=None, native=True, api_key="", reply=("Oi", ", ", "tudo bem?"), delay=0.0):
        """`reply`: pedaços da resposta, ou uma função (nº da chamada, corpo da requisição) → pedaços. `delay`: pausa entre os pedaços do streaming (para testar «Parar»)."""
        self.models, self.native, self.api_key, self.reply, self.delay, self.calls = list(MODELS if models is None else models), native, api_key, reply, delay, 0
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj, status=200):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _auth(self):
                if outer.api_key and self.headers.get("Authorization") != f"Bearer {outer.api_key}":
                    self._send({"error": {"message": "Invalid API key"}}, 401)
                    return False
                return True

            def do_GET(self):
                outer.requests.append(("GET", self.path, None))
                if not self._auth():
                    return
                if self.path == "/api/v0/models" and outer.native:
                    return self._send({"object": "list", "data": outer.models})
                if self.path == "/v1/models":
                    return self._send({"object": "list", "data": [{"id": m["id"], "object": "model"} for m in outer.models]})
                self._send({"error": "Unexpected endpoint or method."}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                outer.requests.append(("POST", self.path, body))
                if not self._auth():
                    return
                if not self.path.endswith("/chat/completions"):
                    return self._send({"error": "nope"}, 404)
                loaded = [m["id"] for m in outer.models if m.get("state") == "loaded" and m.get("type") != "embeddings"]
                if body.get("model") not in [m["id"] for m in outer.models] or body.get("model") in ("text-embedding-nomic",):
                    return self._send({"error": {"message": f"model '{body.get('model')}' not found"}}, 404)
                outer.calls += 1
                chunks = list(outer.reply(outer.calls, body) if callable(outer.reply) else outer.reply)
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    try:
                        for c in chunks:
                            if outer.delay:
                                time.sleep(outer.delay)
                            self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": c}}]}).encode() + b"\n\n")
                            self.wfile.flush()
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                    except OSError:  # o OpenFlow fechou a conexão (botão Parar)
                        pass
                    return
                self._send({"choices": [{"message": {"content": "".join(chunks)}}], "model": body["model"], "loaded": loaded})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LMStudioBase(unittest.TestCase):
    def setUp(self):
        super().setUp()
        lmstudio.forget()
        self.addCleanup(lmstudio.forget)


class ProbeTests(LMStudioBase):
    def test_root_url_accepts_every_way_people_type_it(self):
        for given in ("", "http://127.0.0.1:1234", "http://127.0.0.1:1234/", "http://127.0.0.1:1234/v1", "http://127.0.0.1:1234/v1/", "http://127.0.0.1:1234/api/v0"):
            self.assertEqual(lmstudio.root_url(given), "http://127.0.0.1:1234", given)
        self.assertEqual(lmstudio.root_url("http://192.168.0.5:4321/v1"), "http://192.168.0.5:4321")

    def test_running_server_lists_only_chat_models_loaded_first_with_vision_and_details(self):
        fake = FakeLMStudio()
        self.addCleanup(fake.close)
        info = lmstudio.probe(fake.url + "/v1")
        self.assertTrue(info["running"] and info["native"])
        self.assertEqual([m["id"] for m in info["models"]], ["gemma-3-12b", "llama-3.2-3b", "qwen3-8b"])  # carregados primeiro; embeddings fora
        self.assertEqual(info["loaded"], ["gemma-3-12b", "llama-3.2-3b"])
        g = info["models"][0]
        self.assertEqual((g["vision"], g["loaded"], g["quant"], g["ctx"]), (True, True, "Q4_K_M", 8192))
        self.assertFalse(info["models"][1]["vision"])
        self.assertEqual(info["models"][2]["max_ctx"], 40960)

    def test_older_lm_studio_without_the_native_api_still_works_through_v1_models(self):
        fake = FakeLMStudio(native=False)
        self.addCleanup(fake.close)
        info = lmstudio.probe(fake.url)
        self.assertTrue(info["running"])
        self.assertFalse(info["native"])
        self.assertIn("qwen3-8b", [m["id"] for m in info["models"]])
        self.assertNotIn("text-embedding-nomic", [m["id"] for m in info["models"]])  # embeddings reconhecidos pelo nome
        self.assertTrue(info["loaded"])  # sem a API nativa a lista é tratada como disponível

    def test_server_down_is_reported_without_raising(self):
        info = lmstudio.probe(f"http://127.0.0.1:{free_port()}", timeout=1)
        self.assertFalse(info["running"])
        self.assertEqual((info["models"], info["loaded"]), ([], []))
        self.assertTrue(info["error"])

    def test_a_server_that_asks_for_a_key_counts_as_running(self):
        fake = FakeLMStudio(api_key="segredo")
        self.addCleanup(fake.close)
        info = lmstudio.probe(fake.url)
        self.assertTrue(info["running"])
        self.assertTrue(info["error"])
        ok = lmstudio.probe(fake.url, api_key="segredo")
        self.assertTrue(ok["running"] and ok["loaded"])

    def test_detect_is_cached_briefly_so_a_stopped_server_cannot_slow_every_message(self):
        port = free_port()
        a = lmstudio.detect(f"http://127.0.0.1:{port}")
        with mock.patch.object(lmstudio, "probe", side_effect=AssertionError("não devia consultar de novo")):
            self.assertIs(lmstudio.detect(f"http://127.0.0.1:{port}"), a)
        lmstudio.forget()
        with mock.patch.object(lmstudio, "probe", return_value={"running": True, "loaded": []}) as p:
            lmstudio.detect(f"http://127.0.0.1:{port}")
            self.assertEqual(p.call_count, 1)


class WhyNotConnectedTests(LMStudioBase):
    def test_errors_are_classified_so_the_ui_can_say_what_to_fix(self):
        for msg, kind in (("Não foi possível conectar a 192.168.0.10:1234: [Errno 111] Connection refused", "refused"), ("[WinError 10061] recusou", "refused"),
                          ("Não foi possível conectar a x: timed out", "timeout"), ("<urlopen error [Errno -2] Name or service not known>", "dns"),
                          ("[Errno 113] No route to host", "unreachable"), ("algo estranho", "other")):
            self.assertEqual(lmstudio.classify_error(msg), kind, msg)

    def test_probe_of_a_closed_port_reports_why(self):
        info = lmstudio.probe(f"http://127.0.0.1:{free_port()}", timeout=1)
        self.assertFalse(info["running"])
        self.assertIn(info["kind"], ("refused", "timeout") if os.name == "nt" else ("refused",))   # o Windows pode deixar a conexão expirar em vez de recusar


class ExplainTests(LMStudioBase):
    def test_chat_error_for_a_computer_on_the_network_says_what_to_fix_not_just_start_the_server(self):
        refused = {"running": False, "kind": "refused", "error": "x"}
        self.assertIn("Serve on Local Network", lmstudio.explain(refused, "http://192.168.100.115:1234"))
        self.assertIn("firewall", lmstudio.explain({"running": False, "kind": "timeout"}, "http://192.168.100.115:1234"))
        self.assertIn("mesmo Wi-Fi", lmstudio.explain({"running": False, "kind": "dns"}, "http://pc.local:1234"))
        self.assertIn("Start Server", lmstudio.explain({"running": False}, "http://127.0.0.1:1234"))  # no próprio computador: o conselho de sempre

    def test_in_the_android_app_loopback_means_the_phone_itself(self):
        old = os.environ.get("OPENFLOW_STRICT_LOOPBACK")
        os.environ["OPENFLOW_STRICT_LOOPBACK"] = "1"
        self.addCleanup(lambda: os.environ.pop("OPENFLOW_STRICT_LOOPBACK", None) if old is None else os.environ.__setitem__("OPENFLOW_STRICT_LOOPBACK", old))
        msg = lmstudio.explain({"running": False}, "http://127.0.0.1:1234")
        self.assertIn("não roda neste aparelho", msg)
        self.assertIn("LM Studio no computador", msg)

    def test_a_failed_check_is_cached_only_briefly_and_remote_hosts_get_more_time(self):
        calls = []
        real = lmstudio.probe

        def fake(base, key="", timeout=2.0):
            calls.append(timeout)
            return {"running": False, "url": base, "models": [], "loaded": [], "native": False, "error": "timed out", "kind": "timeout"}

        lmstudio.probe = fake
        self.addCleanup(lambda: setattr(lmstudio, "probe", real))
        lmstudio.detect("http://192.168.0.9:1234")
        self.assertEqual(calls, [5.0, 5.0])  # rede: 5 s e uma segunda tentativa
        calls.clear()
        lmstudio.forget()
        lmstudio.detect("http://127.0.0.1:1234")
        self.assertEqual(calls, [1.0])  # no próprio aparelho: 1 s, sem repetir


class ScanTests(LMStudioBase):
    def test_scan_finds_the_lm_studio_of_another_computer_on_the_network(self):
        fake = FakeLMStudio()
        self.addCleanup(fake.close)
        port = int(fake.url.rsplit(":", 1)[1])
        found = lmstudio.scan(["127.0.0.1", "127.0.0.2"], port=port, timeout=0.5)
        self.assertEqual([f["url"] for f in found][:1], [fake.url])
        self.assertEqual(found[0]["models"], 3)  # só os de chat (embeddings fora)
        self.assertEqual(lmstudio.scan(["127.0.0.1"], port=free_port(), timeout=0.2), [])  # nada escutando: lista vazia, sem erro


class ProviderTests(LMStudioBase):
    def provider(self, fake, **user):
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        s["providers"]["lmstudio"] = {"base_url": fake.url + "/v1", **user}
        return build_provider(s, "lmstudio")

    def test_preset_builds_the_lm_studio_provider(self):
        fake = FakeLMStudio()
        self.addCleanup(fake.close)
        self.assertIsInstance(self.provider(fake), lmstudio.LMStudioProvider)

    def test_without_a_chosen_model_it_uses_the_loaded_one_and_detects_vision(self):
        fake = FakeLMStudio()
        self.addCleanup(fake.close)
        p = self.provider(fake)
        self.assertEqual(p.chat([{"role": "user", "content": "oi"}]), "Oi, tudo bem?")
        self.assertEqual(p.model, "gemma-3-12b")  # o primeiro carregado (aqui, um modelo com visão)
        self.assertTrue(p.vision)
        sent = [r for r in fake.requests if r[0] == "POST"][-1][2]
        self.assertEqual(sent["model"], "gemma-3-12b")

    def test_the_user_choice_wins_over_detection_including_vision(self):
        fake = FakeLMStudio()
        self.addCleanup(fake.close)
        p = self.provider(fake, model="llama-3.2-3b")
        p.chat([{"role": "user", "content": "oi"}])
        self.assertEqual((p.model, p.vision), ("llama-3.2-3b", False))
        q = self.provider(fake, model="gemma-3-12b", vision=False)  # o usuário desligou a visão: vale o que ele disse
        q.chat([{"role": "user", "content": "oi"}])
        self.assertFalse(q.vision)

    def test_streaming_and_the_system_prompt_reach_the_server(self):
        fake = FakeLMStudio()
        self.addCleanup(fake.close)
        p = self.provider(fake, model="llama-3.2-3b")
        text = "".join(p.chat([{"role": "user", "content": "oi"}], system="Você é a Aya.", stream=True))
        self.assertEqual(text, "Oi, tudo bem?")
        body = [r for r in fake.requests if r[0] == "POST"][-1][2]
        self.assertTrue(body["stream"])
        self.assertEqual(body["messages"][0], {"role": "system", "content": "Você é a Aya."})

    def test_api_key_is_sent_when_configured(self):
        fake = FakeLMStudio(api_key="segredo")
        self.addCleanup(fake.close)
        p = self.provider(fake, model="llama-3.2-3b", api_key="segredo")
        self.assertEqual(p.chat([{"role": "user", "content": "oi"}]), "Oi, tudo bem?")

    def test_no_loaded_model_explains_what_to_do(self):
        fake = FakeLMStudio(models=[{"id": "qwen3-8b", "type": "llm", "state": "not-loaded"}])
        self.addCleanup(fake.close)
        with self.assertRaises(ProviderError) as cm:
            self.provider(fake).chat([{"role": "user", "content": "oi"}])
        self.assertIn("nenhum modelo está carregado", str(cm.exception))
        self.assertIn("qwen3-8b", str(cm.exception))

    def test_server_down_explains_how_to_start_it(self):
        p = build_provider({**json.loads(json.dumps(DEFAULT_SETTINGS)), "providers": {"lmstudio": {"base_url": f"http://127.0.0.1:{free_port()}/v1"}}}, "lmstudio")
        with self.assertRaises(ProviderError) as cm:
            p.chat([{"role": "user", "content": "oi"}])
        self.assertIn("Start Server", str(cm.exception))
        with self.assertRaises(ProviderError):
            "".join(p.chat([{"role": "user", "content": "oi"}], stream=True))

    def test_unknown_model_gets_a_helpful_message_and_list_models_is_filtered(self):
        fake = FakeLMStudio()
        self.addCleanup(fake.close)
        with self.assertRaises(ProviderError) as cm:
            self.provider(fake, model="nao-existe").chat([{"role": "user", "content": "oi"}])
        self.assertIn("não achou o modelo", str(cm.exception))
        self.assertEqual(self.provider(fake).list_models(), ["gemma-3-12b", "llama-3.2-3b", "qwen3-8b"])


class ChoiceTests(LMStudioBase, TmpCase):
    def settings(self, active=None, lm=None):
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        s["active"].update(active or {})
        if lm is not None:
            s["providers"]["lmstudio"] = lm
        return s

    def test_auto_picks_lm_studio_when_it_is_running_with_a_loaded_model(self):
        fake = FakeLMStudio()
        self.addCleanup(fake.close)
        (self.tmp / "Qwen3.8-2B-Q8_0.gguf").write_bytes(b"x")  # mesmo com o modelo embutido instalado, o LM Studio vem antes
        with mock.patch.object(auto, "_llama_installed", return_value=True):
            provider, info = auto.resolve(self.settings(lm={"base_url": fake.url + "/v1"}), "characters", self.tmp)
        self.assertEqual((info["id"], info["model"], info["demo"], info["auto"]), ("lmstudio", "gemma-3-12b", False, True))

    def test_explicit_lm_studio_and_generation_following(self):
        fake = FakeLMStudio()
        self.addCleanup(fake.close)
        lm = {"base_url": fake.url + "/v1", "model": "llama-3.2-3b"}
        self.assertEqual(auto.resolve(self.settings({"characters": "lmstudio"}, lm), "characters", self.tmp)[1]["model"], "llama-3.2-3b")
        info = auto.resolve(self.settings({"generation": "lmstudio"}, lm), "characters", self.tmp)[1]  # papel em auto segue a geração
        self.assertEqual((info["id"], info["model"]), ("lmstudio", "llama-3.2-3b"))

    def test_running_without_loaded_model_or_not_running_falls_back_and_mentions_lm_studio(self):
        empty = FakeLMStudio(models=[{"id": "qwen3-8b", "type": "llm", "state": "not-loaded"}])
        self.addCleanup(empty.close)
        info = auto.resolve(self.settings(lm={"base_url": empty.url + "/v1"}), "characters", self.tmp)[1]
        self.assertTrue(info["demo"])
        self.assertIn("LM Studio", info["reason"])
        lmstudio.forget()
        info = auto.resolve(self.settings(lm={"base_url": f"http://127.0.0.1:{free_port()}/v1"}), "characters", self.tmp)[1]
        self.assertTrue(info["demo"])

    def test_chosen_model_counts_as_usable_even_if_the_server_is_off(self):
        s = self.settings({"generation": "lmstudio"}, {"base_url": f"http://127.0.0.1:{free_port()}/v1", "model": "meu"})
        self.assertTrue(auto.usable(s, "lmstudio", self.tmp))
        self.assertFalse(auto.usable(self.settings(lm={"base_url": f"http://127.0.0.1:{free_port()}/v1"}), "lmstudio", self.tmp))


class ReasoningTests(unittest.TestCase):
    def test_think_blocks_never_reach_the_chat(self):
        self.assertEqual(strip_reasoning("<think>vou pensar…</think>Oi! Tudo bem?"), "Oi! Tudo bem?")
        self.assertEqual(strip_reasoning("<THINK>a\nb</THINK>\n\nOlá"), "\n\nOlá")
        self.assertEqual(strip_reasoning("Oi <think>ainda pensando"), "Oi ")  # aberto durante o streaming
        self.assertEqual(strip_reasoning("raciocínio solto</think>Resposta final"), "Resposta final")  # o modelo já começou pensando
        self.assertEqual(strip_reasoning("sem nada especial"), "sem nada especial")


if __name__ == "__main__":
    unittest.main()
