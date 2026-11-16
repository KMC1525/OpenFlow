"""Interface no navegador (Chromium via Playwright): projetos e pesquisa, editor de fluxos, pastas de estilo, modelos e Editor de vídeo. Pulado se Playwright/Chromium não existirem."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

os.environ.setdefault("OPENFLOW_NO_GUARD", "1")   # v0.49: sem a proteção do computador nos testes

from openflow.server import make_server  # noqa: E402
from openflow.storage import Store

ROOT = Path(__file__).resolve().parent.parent
BROWSER = Path(__file__).resolve().parent / "browser"


def _playwright_ok() -> bool:
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, text=True, cwd=str(ROOT))
    return r.returncode == 0


@unittest.skipUnless(_playwright_ok(), "Playwright (Node) não disponível")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="openflow-browser-"))
        cls.httpd, _ = make_server("127.0.0.1", 0, Store(cls.tmp))
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_script(self, name: str, extra_env=None) -> None:
        r = subprocess.run(["node", str(BROWSER / name)], capture_output=True, text=True, timeout=300, env={**os.environ, "OPENFLOW_PORT": str(self.port), "OPENFLOW_NO_GUARD": "1", **(extra_env or {})})
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        failed = [k for k, v in out["checks"].items() if not v]
        self.assertEqual(out["errors"], [])
        self.assertEqual(failed, [], f"verificações que falharam: {failed}")
        self.assertGreater(len(out["checks"]), 3)

    def test_01_every_screen_loads_on_desktop_and_phone(self):
        self.run_script("smoke_ui.js")

    def test_02_projects_home_search_create_rename_duplicate_delete(self):
        self.run_script("projects_ui.js")

    def test_03_style_folder_subfolders_rename_move_toggle_delete(self):
        self.run_script("style_folder_ui.js")

    def test_05_flow_editor_and_video_timeline(self):
        self.run_script("canvas_ui.js")

    def test_06_new_nodes_palette_controls_and_a_real_chain(self):
        self.run_script("canvas_nodes_ui.js")

    def test_07_media_nodes_show_only_model_and_resolution(self):
        self.run_script("canvas_simple_nodes_ui.js")

    def test_08_at_mentions_pick_images_for_the_prompt(self):
        self.run_script("canvas_mention_ui.js")

    def test_09_model_picker_lists_installed_and_cloud_models(self):
        self.run_script("canvas_model_picker_ui.js")

    def test_10_missing_gguf_support_files_offer_a_download_button(self):
        self.run_script("canvas_support_ui.js")

    def test_12_model_search_bar_quantizations_download_and_use(self):
        self.run_script("canvas_hub_ui.js")

    def test_13_text_node_linked_to_image_and_video_shows_the_linked_text(self):
        self.run_script("canvas_text_link_ui.js")

    def test_15_library_models_generated_files_and_downloads_tabs(self):
        self.run_script("library_ui.js")

    def test_16_big_screens_node_search_and_storage_panel(self):
        self.run_script("screens_ui.js")

    def test_17_3d_model_node_viewer_and_library(self):
        self.run_script("model3d_ui.js")

    def test_20_model_search_only_in_the_canvas_bar_and_library_has_none(self):
        self.run_script("hub_v042_ui.js")

    def test_21_downloads_are_followed_next_to_the_canvas_search_bar(self):
        self.run_script("downloads_v043_ui.js")

    def test_22_leaving_the_canvas_releases_global_listeners_and_polling(self):
        self.run_script("leaks_v047_ui.js")

    def test_23_the_node_limit_warns_instead_of_losing_the_new_node(self):
        self.run_script("limits_v047_ui.js")

    def test_24_the_computer_guard_card_and_stop_banner(self):
        self.run_script("guard_v049_ui.js")

    def test_25_design_graphite_background_scale_and_fonts(self):
        self.run_script("design_v050_ui.js")

    def test_19_the_ai_flow_generator_and_the_team_picker_are_gone(self):
        self.run_script("no_flow_ai_ui.js")

    def test_18_sweep_all_screens_and_all_nodes(self):
        self.run_script("sweep_ui.js")


if __name__ == "__main__":
    unittest.main()
