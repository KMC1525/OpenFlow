"""v0.44: configurações legadas ou inúteis saíram (chaves de API, endereços, «vision», seção `generation` do Chat do ASTA, voz em servidor, avisos de «sem chave»)."""
import json
import tempfile
import unittest
from pathlib import Path

from openflow import uiprefs
from openflow.canvas import media as M
from openflow.providers import registry
from openflow.storage import DEFAULT_SETTINGS, Store
from openflow.util import write_json
from tests.helpers import ServerCase

JS = Path(__file__).resolve().parent.parent / "openflow" / "web" / "js"


class DefaultsTests(unittest.TestCase):
    def test_the_defaults_have_only_what_is_read(self):
        self.assertEqual(set(DEFAULT_SETTINGS), {"language", "ui", "active", "providers", "media", "canvas", "performance", "server", "storage", "hf"})
        self.assertEqual(DEFAULT_SETTINGS["canvas"], {"template": "text_image"})

    def test_old_files_are_cleaned_on_load_and_on_save(self):
        home = Path(tempfile.mkdtemp())
        write_json(home / "settings.json", {"generation": {"temperature": 0.9, "max_tokens": 1, "content": "sfw"}, "voice": {"stt": {"mode": "server"}},
                                            "providers": {"local_hf": {"model": "a.gguf", "n_ctx": 8192, "api_key": "sk-x", "base_url": "http://x", "vision": True}},
                                            "media": {"active": {"image": "demo"}, "urls": {"a1111": "http://x"}}})
        st = Store(home)
        s = st.get_settings()
        self.assertNotIn("generation", s)
        self.assertNotIn("voice", s)
        self.assertEqual(s["providers"]["local_hf"], {"model": "a.gguf", "n_ctx": 8192})
        self.assertNotIn("urls", s["media"])
        st.save_settings({"providers": {"local_hf": {"api_key": "sk-nova", "base_url": "http://y", "vision": False, "model": "b.gguf"}}})
        raw = json.loads((home / "settings.json").read_text())
        self.assertNotIn("sk-nova", json.dumps(raw))
        self.assertEqual(raw["providers"]["local_hf"], {"model": "b.gguf", "n_ctx": 8192})
        self.assertNotIn("generation", raw)


class ApiShapeTests(unittest.TestCase):
    def test_presets_describe_only_local_providers_without_key_fields(self):
        for p in registry.describe_presets():
            self.assertEqual(set(p), {"id", "label", "kind", "model", "local", "hint"})
        for p in M.describe_media_presets({}):
            self.assertEqual(set(p), {"id", "label", "caps", "local", "hint", "models", "suggest"})

    def test_media_providers_have_no_key_or_url_plumbing(self):
        prov = M.DemoMedia({"id": "demo"})
        for attr in ("key", "base", "need_key", "need_url"):
            self.assertFalse(hasattr(prov, attr), attr)
        cfg = M.media_config({}, "local_hf")
        self.assertNotIn("api_key", cfg)
        self.assertNotIn("base_url", cfg)

    def test_export_and_import_carry_only_what_exists(self):
        out = uiprefs.export_settings(Store(Path(tempfile.mkdtemp())).get_settings())
        self.assertEqual(set(out["settings"]) - {"providers"}, {"language", "ui", "canvas", "performance", "active", "media"})
        self.assertNotIn("voice", out["settings"])
        patch = uiprefs.import_patch({"schema": uiprefs.EXPORT_SCHEMA, "settings": {"generation": {"x": 1}, "voice": {"stt": {}}, "providers": {"local_hf": {"model": "m", "api_key": "k", "base_url": "u"}},
                                                                                   "media": {"urls": {"a": "b"}, "active": {"image": "demo"}}}})
        self.assertNotIn("generation", patch)
        self.assertNotIn("voice", patch)
        self.assertEqual(patch["providers"], {"local_hf": {"model": "m"}})
        self.assertEqual(patch["media"], {"active": {"image": "demo"}})
        self.assertEqual(uiprefs.RESETTABLE, ("ui", "canvas", "performance"))


class RoutesTests(ServerCase):
    def test_state_and_settings_have_no_key_flags_and_the_models_route_is_gone(self):
        s, r = self.c.json("GET", "/api/state")
        self.assertEqual(s, 200)
        self.assertEqual(set(r["presets"][0]), {"id", "label", "kind", "model", "local", "hint"})
        self.assertNotIn("generation", r["settings"])
        self.assertTrue(all("has_key" not in v for v in r["settings"]["providers"].values()))
        self.assertEqual(self.c.json("POST", "/api/providers/models", {"id": "demo"})[0], 404)
        self.assertEqual(self.c.json("POST", "/api/providers/test", {"id": "demo", "config": {}})[0], 200)
        s, _ = self.c.json("POST", "/api/settings/reset", {"section": "generation"})
        self.assertEqual(s, 400)

    def test_the_provider_card_saves_only_model_and_context(self):
        self.c.json("PUT", "/api/settings", {"providers": {"local_hf": {"model": "x.gguf", "n_ctx": 4096, "api_key": "zzz", "vision": True, "base_url": "http://x"}}})
        s, r = self.c.json("GET", "/api/settings")
        self.assertEqual(r["providers"]["local_hf"], {"model": "x.gguf", "n_ctx": 4096})
        self.c.json("PUT", "/api/settings", {"providers": {"local_hf": {"model": "", "n_ctx": 0}}})


class SourceTests(unittest.TestCase):
    def test_the_settings_screen_has_no_cloud_leftovers(self):
        src = (JS / "views" / "settings.js").read_text(encoding="utf-8") + (JS / "canvas_nodes.js").read_text(encoding="utf-8")
        for needle in ("needs_key", "has_key", "api_key", "base_url", "Carregar modelos", "loadModels", "isChar", "sem chave", "Sem chave de API", "providers/models", "'vision'", "vision:"):
            self.assertNotIn(needle, src, needle)


if __name__ == "__main__":
    unittest.main()
