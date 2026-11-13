"""Interface no navegador (Chromium via Playwright): projetos e pesquisa, editor de fluxos, pastas de estilo, modelos e Editor de vídeo. Pulado se Playwright/Chromium não existirem."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from openflow.server import make_server
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
        r = subprocess.run(["node", str(BROWSER / name)], capture_output=True, text=True, timeout=300, env={**os.environ, "OPENFLOW_PORT": str(self.port), **(extra_env or {})})
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

    def test_04_models_screen_installed_support_files_and_hugging_face_search(self):
        self.run_script("models_ui.js")

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

    def test_11_prompt_box_generates_a_flow_and_minimizes(self):
        self.run_script("canvas_flow_ui.js")

    def test_12_model_search_bar_quantizations_download_and_use(self):
        self.run_script("canvas_hub_ui.js")


if __name__ == "__main__":
    unittest.main()
