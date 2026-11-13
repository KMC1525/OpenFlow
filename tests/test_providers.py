"""Testes dos provedores contra um servidor mock (OpenAI-compatível e Anthropic)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow.agents.llm import call_json  # noqa: E402
from openflow.providers import ProviderError, build_provider  # noqa: E402
from openflow.providers.anthropic import AnthropicProvider  # noqa: E402
from openflow.providers.openai_compat import OpenAICompatProvider  # noqa: E402
from tests.helpers import MockProviderServer  # noqa: E402


def settings_for(pid, url, **extra):
    cfg = {"base_url": url, "api_key": "KEY123", "model": "m"}
    cfg.update(extra)
    return {"providers": {pid: cfg}, "hf": {"token": ""}}


class OpenAICompatTests(unittest.TestCase):
    def test_chat_stream_models_and_headers(self):
        with MockProviderServer() as srv:
            p = build_provider(settings_for("custom", srv.url + "/v1"), "custom")
            self.assertIsInstance(p, OpenAICompatProvider)
            msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "oi"}]
            self.assertIn("ok", p.chat(msgs, system="EXTRA"))
            req = srv.requests[-1]
            self.assertEqual(req["headers"]["authorization"], "Bearer KEY123")
            self.assertEqual(req["body"]["messages"][0], {"role": "system", "content": "EXTRA\n\nSYS"})
            self.assertEqual(req["body"]["messages"][1]["content"], "oi")
            self.assertEqual("".join(p.chat(msgs, stream=True)), "Olá, mundo")
            self.assertTrue(srv.requests[-1]["body"]["stream"])
            self.assertEqual(p.list_models(), ["model-a", "model-b"])

    def test_images_only_sent_with_vision(self):
        img = {"type": "image", "media_type": "image/png", "data": "QUJD"}
        msgs = [{"role": "user", "content": [{"type": "text", "text": "veja"}, img]}]
        with MockProviderServer() as srv:
            p = build_provider(settings_for("custom", srv.url + "/v1", vision=True), "custom")
            p.chat(msgs)
            content = srv.requests[-1]["body"]["messages"][0]["content"]
            self.assertEqual(content[1]["image_url"]["url"], "data:image/png;base64,QUJD")
            p2 = build_provider(settings_for("custom", srv.url + "/v1", vision=False), "custom")
            p2.chat(msgs)
            content2 = srv.requests[-1]["body"]["messages"][0]["content"]
            self.assertIsInstance(content2, str)
            self.assertIn("imagem", content2)

    def test_adapts_max_tokens_for_reasoning_models(self):
        with MockProviderServer() as srv:
            p = build_provider(settings_for("custom", srv.url + "/v1", model="reasoner"), "custom")
            p.chat([{"role": "user", "content": "x"}], max_tokens=50)
            body = srv.requests[-1]["body"]
            self.assertNotIn("max_tokens", body)
            self.assertEqual(body["max_completion_tokens"], 50)

    def test_errors_are_clear_and_do_not_leak_key(self):
        with MockProviderServer() as srv:
            p = build_provider(settings_for("custom", srv.url + "/v1", model="bad-key"), "custom")
            with self.assertRaises(ProviderError) as cm:
                p.chat([{"role": "user", "content": "x"}])
            self.assertEqual(cm.exception.status, 401)
            self.assertNotIn("KEY123", str(cm.exception))
        with self.assertRaises(ProviderError):
            build_provider({"providers": {"custom": {"base_url": "http://127.0.0.1:1/v1", "model": "m"}}}, "custom").chat([{"role": "user", "content": "x"}])
        with self.assertRaises(ProviderError):
            build_provider({"providers": {}}, "openai").chat([{"role": "user", "content": "x"}])  # sem modelo

    def test_call_json_parses_structured_output(self):
        with MockProviderServer() as srv:
            p = build_provider(settings_for("custom", srv.url + "/v1", json=True), "custom")
            obj, raw = call_json(p, "[[OPENFLOW_AGENT:x]]", "Faça", {"a": 1})
            self.assertEqual(obj["ok"], True)
            self.assertIn("INPUT_JSON", srv.requests[-1]["body"]["messages"][-1]["content"])


class AnthropicTests(unittest.TestCase):
    def test_messages_api(self):
        with MockProviderServer() as srv:
            p = build_provider(settings_for("anthropic", srv.url), "anthropic")
            self.assertIsInstance(p, AnthropicProvider)
            msgs = [{"role": "system", "content": "SYS"}, {"role": "assistant", "content": "oi"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
            self.assertEqual(p.chat(msgs, max_tokens=77), "resposta anthropic")
            req = srv.requests[-1]
            self.assertEqual(req["headers"]["x-api-key"], "KEY123")
            self.assertEqual(req["headers"]["anthropic-version"], "2023-06-01")
            body = req["body"]
            self.assertEqual(body["system"], "SYS")
            self.assertEqual(body["max_tokens"], 77)
            # a API exige começar por "user" e alternar papéis (mensagens seguidas são fundidas)
            self.assertEqual([m["role"] for m in body["messages"]], ["user", "assistant", "user"])
            self.assertEqual(len(body["messages"][2]["content"]), 2)
            self.assertEqual("".join(p.chat(msgs, stream=True)), "Oi Claude")

    def test_requires_key(self):
        p = build_provider({"providers": {"anthropic": {"model": "m"}}}, "anthropic")
        with self.assertRaises(ProviderError):
            p.chat([{"role": "user", "content": "x"}])


class DemoProviderTests(unittest.TestCase):
    def test_demo_is_default_and_offline(self):
        p = build_provider({"providers": {}}, "demo")
        self.assertEqual(p.model, "demo")
        self.assertEqual("".join(p.chat([{"role": "user", "content": "Descreva a cena"}], stream=True)), "(Demo) Descreva a cena")
        self.assertEqual(p.test(), p.test())
        # os agentes do planejador de fluxos recebem um JSON vazio (o pipeline cai no método automático)
        self.assertEqual(p.chat([{"role": "system", "content": "[[OPENFLOW_AGENT:flow_planner]]"}, {"role": "user", "content": "INPUT_JSON: {}"}]), "{}")


if __name__ == "__main__":
    unittest.main()
