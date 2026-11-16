"""v0.50: fundo cinza-grafite (sem preto puro), tamanho da interface de 50% a 200% e mais fontes."""
import re
import unittest
from pathlib import Path

from openflow import uiprefs
from openflow.uiprefs import normalize_font_name, normalize_scale, normalize_ui
from tests.helpers import ServerCase

WEB = Path(__file__).resolve().parent.parent / "openflow" / "web"


class ScaleTests(unittest.TestCase):
    def test_range_is_50_to_200_in_steps_of_5(self):
        self.assertEqual([normalize_scale(v) for v in (50, 75, 100, 200)], [50, 75, 100, 200])
        self.assertEqual((normalize_scale(10), normalize_scale(0), normalize_scale(-30)), (50, 50, 50))
        self.assertEqual((normalize_scale(500), normalize_scale(201)), (200, 200))
        self.assertEqual((normalize_scale(103), normalize_scale("147.6"), normalize_scale(112.5)), (105, 150, 115))

    def test_garbage_goes_back_to_100(self):
        for bad in (None, "x", [], {}, float("nan"), float("inf")):
            self.assertEqual(normalize_scale(bad), 100, bad)
        self.assertEqual(normalize_ui({"scale": "abc"})["scale"], 100)

    def test_old_values_still_valid(self):
        for v in (90, 100, 110, 125, 150):
            self.assertEqual(normalize_ui({"scale": v})["scale"], v)


class FontTests(unittest.TestCase):
    def test_more_fonts_and_invalid_ones_fall_back(self):
        self.assertGreaterEqual(len(uiprefs.FONTS), 8)
        for f in uiprefs.FONTS:
            self.assertEqual(normalize_ui({"font": f})["font"], f)
        self.assertEqual(normalize_ui({"font": "comic"})["font"], "system")
        self.assertEqual(normalize_ui({"font": 3})["font"], "system")

    def test_custom_font_name_cannot_inject_css(self):
        self.assertEqual(normalize_font_name("Fira Sans"), "Fira Sans")
        self.assertEqual(normalize_font_name('x"; } body{display:none} /*'), "x bodydisplaynone")
        self.assertEqual(normalize_font_name("a" * 200), "a" * 60)
        self.assertEqual((normalize_font_name(None), normalize_font_name(5), normalize_font_name("  ")), ("", "", ""))
        self.assertEqual(normalize_ui({"font": "custom", "font_custom": "Fira  Code"})["font_custom"], "Fira Code")
        self.assertEqual(normalize_ui({})["font_custom"], "")

    def test_every_font_has_css_and_a_card(self):
        css = (WEB / "css" / "app.css").read_text(encoding="utf-8")
        for f in uiprefs.FONTS:
            if f != "system":
                self.assertIn(f'[data-font="{f}"]', css, f)
        boot = (WEB / "js" / "boot.js").read_text(encoding="utf-8")
        for f in uiprefs.FONTS:
            self.assertIn(f"'{f}'", boot, f)


class ColorTests(unittest.TestCase):
    def test_dark_theme_is_graphite_not_pure_black(self):
        css = (WEB / "css" / "app.css").read_text(encoding="utf-8")
        root = css[css.index(":root{"):css.index("}", css.index(":root{"))]
        bg = re.search(r"--bg:(#[0-9a-f]{6});", root).group(1)
        n = int(bg[1:], 16)
        r, g, b = (n >> 16) & 255, (n >> 8) & 255, n & 255
        self.assertTrue(24 <= min(r, g, b) and max(r, g, b) <= 60, bg)   # nem preto, nem claro demais
        for var in ("--bg1", "--bg2", "--bg3"):
            self.assertNotIn(re.search(var + r":(#[0-9a-f]{3,6})", root).group(1), ("#000", "#000000", "#080808", "#101010", "#181818"))
        canvas = (WEB / "css" / "canvas.css").read_text(encoding="utf-8")
        self.assertNotIn("background-color:#050505", canvas)
        self.assertIn('content="#1e1f22"', (WEB / "index.html").read_text(encoding="utf-8"))


class ApiTests(ServerCase):
    def test_settings_round_trip(self):
        self.c.json("PUT", "/api/settings", {"ui": {"scale": 55, "font": "custom", "font_custom": "Fira Sans"}})
        ui = self.c.json("GET", "/api/settings")[1]["ui"]
        self.assertEqual((ui["scale"], ui["font"], ui["font_custom"]), (55, "custom", "Fira Sans"))
        self.c.json("PUT", "/api/settings", {"ui": {"scale": 999, "font": "rounded"}})
        ui = self.c.json("GET", "/api/settings")[1]["ui"]
        self.assertEqual((ui["scale"], ui["font"]), (200, "rounded"))
        self.c.json("PUT", "/api/settings", {"ui": {"scale": 100, "font": "system", "font_custom": ""}})


if __name__ == "__main__":
    unittest.main()
