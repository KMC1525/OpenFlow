"""v0.22: MiniMax H3 (sd-cli, VAE de vídeo + de áudio, te=cpu, WebM com áudio) e LTX-2 / 2.3 / 2.5 (diffusers)."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from openflow import unsloth_models
from openflow.canvas import ltx2, sdcli, support
from openflow.canvas import media as M
from openflow.providers import ProviderError
from tests.helpers import ServerCase

H3 = "minimax_h3_fl2va_pruned-UD-Q2_K_XL.gguf"


class H3Tests(unittest.TestCase):
    def test_families(self):
        self.assertEqual(support.family_of(H3)["id"], "minimax-h3")
        self.assertEqual(support.family_of("minimax_h3_ref2va_pruned-Q4_K.gguf")["id"], "minimax-h3-ref")
        self.assertEqual(support.family_of("ltx-2.5-22b-distilled-UD-Q4_K_XL.gguf")["id"], "ltx2")

    def test_text_encoder_follows_the_quantisation(self):
        fam = support.family_of(H3)
        self.assertEqual(support.download_spec(fam, "llm_path", H3)["file"], "qwen3vl_32b_minimax_h3-Q2_K_M.gguf")
        self.assertEqual(support.download_spec(fam, "llm_path", "minimax_h3_fl2va_pruned-Q4_K.gguf")["file"], "qwen3vl_32b_minimax_h3-Q4_K_M.gguf")
        self.assertEqual(support.download_spec(fam, "vae_path", H3)["repo"], "Comfy-Org/MiniMax-H3")
        self.assertIn("audio_vae", support.download_spec(fam, "audio_vae_path", H3)["file"])

    def test_cli_arguments(self):
        load = {"diffusion_model_path": "/m/h3.gguf", "vae_path": "/m/v.safetensors", "audio_vae_path": "/m/a.safetensors", "llm_path": "/m/q.gguf", "te_on_cpu": True, "diffusion_flash_attn": True}
        args, warns = sdcli.build_args(Path("/x/sd-cli"), load, {"cfg_scale": 1.0, "fps": 24, "video_frames": 121}, prompt="p", width=960, height=544, seed=1, out=Path("/t/o.webm"), video=True)
        self.assertEqual(warns, [])
        self.assertIn("--audio-vae", args)
        self.assertEqual(args[args.index("--backend") + 1], "te=cpu")
        self.assertEqual(args[args.index("--cfg-scale") + 1], "1.0")
        self.assertEqual(args[args.index("-M") + 1], "vid_gen")

    def test_installed_hides_the_text_encoder(self):
        from openflow.canvas import installed

        self.assertTrue(installed.SUPPORT_RE.search("qwen3vl_32b_minimax_h3-Q4_K_M.gguf"))

    def test_generate_video_file_returns_webm(self):
        def fake_run(args, exe, cancelled, note):
            Path(args[args.index("-o") + 1]).write_bytes(b"WEBM")
            return ""

        with mock.patch.object(sdcli, "run", fake_run):
            data, mime, warns = sdcli.generate_video_file(Path("/x/sd-cli"), {"diffusion_model_path": "/m"}, {}, prompt="p", width=960, height=544, seed=1, fps=24)
        self.assertEqual((data, mime), (b"WEBM", "video/webm"))


class Ltx2Tests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(ltx2.parse("ltx-2.5-22b-distilled-UD-Q4_K_XL.gguf"), {"version": "2.5", "variant": "distilled", "base": "Lightricks/LTX-2.5-Diffusers"})
        self.assertEqual(ltx2.parse("ltx-2-19b-dev-Q4_K_M.gguf")["version"], "2")
        self.assertEqual(ltx2.parse("ltx-2.3-22b-dev-Q4_K_M.gguf")["base"], ltx2.BASES["2.3"])
        self.assertIsNone(ltx2.parse("flux1-dev.gguf"))

    def test_sizes_and_frames(self):
        for a in ("16:9", "9:16", "1:1", "4:3"):
            w, h = ltx2.size_for(a)
            self.assertEqual((w % 32, h % 32), (0, 0))
        self.assertEqual(ltx2.frames_for(5), 121)
        self.assertEqual((ltx2.frames_for(3) - 1) % 8, 0)

    def test_missing_message_has_the_button_marker(self):
        self.assertIn("[[flow-ltx2:Lightricks/LTX-2]]", ltx2.missing_message("Lightricks/LTX-2", 25 * 1024 ** 3))

    def test_download_never_fetches_the_transformer(self):
        calls = {}
        hub = types.SimpleNamespace(snapshot_download=lambda base, **kw: calls.update(kw) or "/cache/x")
        with mock.patch.object(ltx2, "_hub", lambda: hub):
            self.assertEqual(ltx2.download_components("Lightricks/LTX-2"), "/cache/x")
        self.assertIn("transformer/*", calls["ignore_patterns"])

    def test_gated_error_is_explained(self):
        def boom(*a, **k):
            raise RuntimeError("401 gated repo")

        with mock.patch.object(ltx2, "_hub", lambda: types.SimpleNamespace(snapshot_download=boom)):
            with self.assertRaises(ProviderError) as cm:
                ltx2.download_components("Lightricks/LTX-2.5-Diffusers")
        self.assertIn("restrito", str(cm.exception))

    def test_old_diffusers_is_explained(self):
        fake = types.ModuleType("diffusers")
        fake.__version__ = "0.30.0"
        with mock.patch.dict(sys.modules, {"diffusers": fake, "torch": types.ModuleType("torch")}):
            with self.assertRaises(ProviderError) as cm:
                ltx2._imports()
        self.assertIn("flow update", str(cm.exception))

    def test_media_asks_for_the_button_when_components_are_missing(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "video").mkdir()
            (Path(d) / "video" / "ltx-2-19b-dev-Q4_K_M.gguf").write_bytes(b"x")
            prov = M.GGUFMedia({"models_dir": d, "models": {}})
            with mock.patch.object(ltx2, "components_cached", return_value=False), mock.patch.object(ltx2, "components_size", return_value=0):
                with self.assertRaises(ProviderError) as cm:
                    prov.video("a cat", model="ltx-2-19b-dev-Q4_K_M.gguf")
        self.assertIn("[[flow-ltx2:Lightricks/LTX-2]]", str(cm.exception))


class CatalogAndRouteTests(ServerCase):
    def test_catalog_marks_them_beta(self):
        by = {e["repo"]: e for e in unsloth_models.catalog()}
        for r in ("unsloth/MiniMax-H3-GGUF", "unsloth/LTX-2-GGUF", "unsloth/LTX-2.3-GGUF", "unsloth/LTX-2.5-GGUF"):
            self.assertEqual(by[r]["status"], "beta")

    def test_route_downloads_components(self):
        import time

        with mock.patch.object(ltx2, "download_components", return_value="/cache/x"):
            st, r = self.c.json("POST", "/api/media/ltx2-components", {"base": "Lightricks/LTX-2"})
            self.assertEqual(st, 200, r)
            for _ in range(100):
                st, j = self.c.json("GET", "/api/jobs/" + r["job_id"])
                if j.get("status") != "running":
                    break
                time.sleep(0.05)
        self.assertEqual(j["status"], "done", j)

    def test_route_refuses_unknown_repositories(self):
        st, _ = self.c.json("POST", "/api/media/ltx2-components", {"base": "evil/repo"})
        self.assertEqual(st, 400)
