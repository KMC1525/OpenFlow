"""v0.91 — o `flow` em Rust dá as MESMAS respostas que o Python nas partes já portadas (configurações, preferências, exportação, mesclagem, nomes de arquivo).
Cada caso roda no Python e no `flow dev …` e os JSON são comparados."""
import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.rust_bin import flow_bin

BIN = flow_bin()


def rust(cmd: str, payload):
    r = subprocess.run([str(BIN), "dev", cmd], input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=60)   # bytes UTF-8 nos dois sentidos: no Windows o texto «local» seria cp1252
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.decode("utf-8"))


@unittest.skipUnless(BIN, "sem o binário `flow` (cargo build em rust/)")
class ParityTests(unittest.TestCase):
    def test_normalize_ui(self):
        from openflow.uiprefs import normalize_ui

        cases = [{}, None, {"theme": "light"}, {"theme": "nope", "accent": "#ABC"}, {"accent": "#a1b2c3", "scale": 137}, {"scale": 9999}, {"scale": -4}, {"scale": "130"}, {"scale": True},
                 {"scale": 52.5}, {"scale": 47.4}, {"density": "compact", "motion": "reduce", "font": "mono"}, {"font": "custom", "font_custom": "Fira \"Code\";x"},
                 {"font_custom": "  Ação   Ñandú-2.0 _x  "}, {"font_custom": 5}, {"shortcuts": False}, {"shortcuts": 0}, {"welcome_done": True}, {"welcome_done": 1}, {"accent": 12},
                 {"accent": "#12"}, {"accent": "red"}, "texto", [1, 2], {"theme": 3}, {"font_custom": "x" * 200}]
        for c in cases:
            self.assertEqual(rust("normalize_ui", c), normalize_ui(c), c)

    def test_export_and_import(self):
        from openflow.uiprefs import export_settings, import_patch

        full = {"language": "en", "ui": {"theme": "light"}, "canvas": {"template": "x"}, "performance": {"mode": "light"}, "active": {"generation": "demo"}, "media": {"active": {}, "models": {}},
                "hf": {"token": "SEGREDO"}, "providers": {"local_hf": {"model": "m", "n_ctx": 0, "api_key": "k"}, "demo": {"model": ""}, "bad": 5}}
        self.assertEqual(rust("export", full), export_settings(full))
        exported = export_settings(full)
        self.assertEqual(rust("import", exported), {"ok": import_patch(exported)})
        for bad in ({}, {"schema": "x"}, {"schema": "openflow.settings.v1"}, {"schema": "openflow.settings.v1", "settings": 3}):
            with self.assertRaises(ValueError):
                import_patch(bad)
            self.assertIn("error", rust("import", bad))
        odd = {"schema": "openflow.settings.v1", "settings": {"language": "fr", "ui": {"theme": "zzz"}, "media": {"active": 3, "models": {"a": 1}}, "active": {"a": "b", "c": 3}, "providers": {"p": {"model": "m", "x": 1}, "q": "no"}}}
        self.assertEqual(rust("import", odd), {"ok": import_patch(odd)})

    def test_deep_merge_and_safe_filename(self):
        from openflow.util import deep_merge, safe_filename

        for base, patch in [({"a": 1, "b": {"x": 1}}, {"b": {"y": 2}, "c": 3}), ({}, {"a": {"b": {"c": 1}}}), ({"a": [1]}, {"a": {"x": 1}}), ({"a": {"x": 1}}, {"a": 5})]:
            self.assertEqual(rust("deep_merge", {"base": base, "patch": patch}), deep_merge(base, patch))
        names = ["a.txt", "../../etc/passwd", "a:b*c?.txt", "  ..  ", "C:\\x\\foto.png", "", "x" * 300, "ação.png", "a\tb", "..."]
        if os.name == "nt":   # o `os.path.basename` do Python no Windows trata «a:» como letra de unidade e a corta; o Rust é igual em todo sistema
            names = [n for n in names if ":" not in n or n.startswith("C:")]
        for name in names:
            self.assertEqual(rust("safe_filename", {"name": name, "default": "arquivo"}), safe_filename(name, "arquivo"), name)

    def test_settings_load_and_patch_sequences(self):
        from openflow.storage import Store

        saved_cases = [
            None,
            {},
            {"language": "en", "ui": {"theme": "light", "scale": 120}},
            {"providers": {"openai": {"api_key": "x"}, "local_hf": {"model": " m ", "api_key": "y", "n_ctx": 4096}, "demo": {"n_ctx": -1}}},
            {"server": {"max_upload_mb": "muito"}, "performance": {"guard": {"limit": 5, "hold_s": 999, "cpu": "sim"}, "memory": {"gpu_reserve_mb": 99999, "ram_reserve_gb": 1.26, "multi_gpu": False}}},
            {"media": {"active": {"image": "openai", "stt": "x", "voice": "gguf_local"}, "models": {"local_hf": {"image": " sd ", "voice": 3}, "cloud": {"image": "x"}}, "urls": {"a": 1}}, "active": {"generation": "claude", "image": "local_hf"}},
            {"hf": {"token": "abc", "connections": "oito", "auto_support": 1}, "voice": {"x": 1}, "generation": {"y": 1}, "custom_key": {"keep": True}},
            {"ui": "quebrado", "canvas": 5, "storage": {"models_dir": 3}},
        ]
        patch_seqs = [
            [],
            [{"ui": {"theme": "light", "scale": 80}}, {"language": "pt-BR"}],
            [{"hf": {"token": " novo "}}, {"hf": {"token": ""}}, {"hf": {"token": None}}],
            [{"providers": {"local_hf": {"model": "q", "n_ctx": 2048, "api_key": "no"}, "openai": {"model": "x"}}}],
            [{"performance": {"guard": {"limit": 120, "enabled": False}, "mode": "light"}}, {"performance": {"memory": {"ram_reserve_gb": 5.55}}}],
            [{"hf": {"token_set": True, "has_key": True}, "ui": {"x_set": 1}}],
            [{"media": {"active": {"image": "local_hf", "video": "nope"}}}],
        ]
        for saved in saved_cases:
            for patches in patch_seqs:
                with tempfile.TemporaryDirectory() as d:
                    if saved is not None:
                        (Path(d) / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
                    st = Store(Path(d))
                    expect = [{"get": st.get_settings(), "public": st.public_settings()}]
                    for p in patches:
                        st.save_settings(copy.deepcopy(p))
                        expect.append({"get": st.get_settings(), "public": st.public_settings()})
                got = rust("settings", {"saved": saved, "patches": patches})
                self.assertEqual(got, expect, (saved, patches))


if __name__ == "__main__":
    unittest.main()
