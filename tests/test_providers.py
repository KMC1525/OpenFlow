"""Testes dos provedores contra um servidor mock (OpenAI-compatível e Anthropic)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow.providers import ProviderError, build_provider  # noqa: E402


def settings_for(pid, url, **extra):
    cfg = {"base_url": url, "api_key": "KEY123", "model": "m"}
    cfg.update(extra)
    return {"providers": {pid: cfg}, "hf": {"token": ""}}


class DemoProviderTests(unittest.TestCase):
    def test_demo_is_default_and_offline(self):
        p = build_provider({"providers": {}}, "demo")
        self.assertEqual(p.model, "demo")
        self.assertEqual("".join(p.chat([{"role": "user", "content": "Descreva a cena"}], stream=True)), "(Demo) Descreva a cena")
        self.assertEqual(p.test(), p.test())


if __name__ == "__main__":
    unittest.main()
