"""Interface: toda frase em português usada na WebUI precisa ter tradução em inglês (web/js/en.js)."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "Node.js não instalado")
class TranslationTests(unittest.TestCase):
    def test_every_ui_phrase_has_an_english_translation(self):
        r = subprocess.run(["node", str(ROOT / "tests" / "js" / "i18n_check.mjs")], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["missing"], [], "frases sem tradução em openflow/web/js/en.js")
        self.assertEqual(out["empty"], [])
        self.assertGreater(out["keys"], 500)

    def test_placeholders_match_in_both_languages(self):
        import re

        src = (ROOT / "openflow" / "web" / "js" / "en.js").read_text(encoding="utf-8")
        for pt, en in re.findall(r"^  '((?:[^'\\]|\\.)*)': '((?:[^'\\]|\\.)*)',?$", src, flags=re.M):
            self.assertEqual(sorted(re.findall(r"\{(\w+)\}", pt)), sorted(re.findall(r"\{(\w+)\}", en)), pt[:70])


if __name__ == "__main__":
    unittest.main()
