"""v0.35 (sem nuvem): só modelos locais do Hugging Face (e o Demo); configurações antigas migram sem chaves."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import storage  # noqa: E402
from openflow.canvas import media as M  # noqa: E402
from openflow.canvas import schema as S  # noqa: E402
from openflow.providers import ProviderError, build_provider  # noqa: E402
from openflow.providers import registry  # noqa: E402


class LocalOnlyTests(unittest.TestCase):
    def test_registries_only_hold_local_providers(self):
        self.assertEqual(set(registry.PRESETS), {"demo", "local_hf"})
        self.assertEqual(set(M.MEDIA_PRESETS), {"demo", "local_hf", "gguf_local"})

    def test_removed_text_providers_explain_themselves(self):
        for pid in ("openai", "anthropic", "gemini", "openrouter", "lmstudio", "ollama"):
            with self.assertRaises(ProviderError) as cm:
                build_provider({"providers": {}}, pid)
            self.assertIn("v0.35", str(cm.exception))

    def test_removed_media_providers_explain_themselves(self):
        with self.assertRaises(Exception) as cm:
            M.build_media({"media": {"active": {}}}, "image", "openai")
        self.assertIn("v0.35", str(cm.exception))

    def test_old_settings_are_migrated_and_keys_dropped(self):
        old = {"providers": {"openai": {"api_key": "sk-x"}, "local_hf": {"model": "m.gguf"}}, "active": {"generation": "anthropic"},
               "media": {"active": {"image": "openai", "stt": "elevenlabs"}, "urls": {"a1111": "http://x"}, "models": {"openai": {"image": "gpt-image-1"}}}, "voice": {"mode": "server"}}
        s = storage.local_only(old)
        self.assertNotIn("sk-x", json.dumps(s))
        self.assertEqual(set(s["providers"]), {"local_hf"})
        self.assertEqual(s["active"]["generation"], "auto")
        self.assertEqual((s["media"]["active"]["image"], s["media"]["active"]["stt"]), ("demo", "local_hf"))
        self.assertNotIn("urls", s["media"])
        self.assertNotIn("voice", s)

    def test_nodes_saved_with_a_removed_provider_fall_back_to_the_default(self):
        p = S.normalize_node({"id": "i", "type": "image", "params": {"provider": "openai", "model": "gpt-image-1"}})["params"]
        self.assertEqual((p["provider"], p["model"]), ("", ""))
        p = S.normalize_node({"id": "i", "type": "image", "params": {"provider": "gguf_local", "model": "a.gguf"}})["params"]
        self.assertEqual((p["provider"], p["model"]), ("gguf_local", "a.gguf"))


if __name__ == "__main__":
    unittest.main()
