"""v0.21: modelos de imagem e vídeo da Unsloth: família MOSS-Image, FLUX.1 com CFG 1, catálogo na tela Modelos."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow import hf, unsloth_models
from openflow.canvas import installed, sdcli, support
from openflow.canvas import media as M
from tests.helpers import ServerCase

MOSS = "MOSS-Image-SFT-UD-Q4_K_XL.gguf"


class FamilyTests(unittest.TestCase):
    def test_every_ready_unsloth_model_file_is_recognised_by_a_family(self):
        files = {"MOSS-Image-SFT-UD-Q4_K_XL.gguf": "moss-image", "MOSS-Image-Base-Q8_0.gguf": "moss-image", "qwen-image-2512-Q4_K_M.gguf": "qwen-image", "qwen-image-Q4_K_M.gguf": "qwen-image",
                 "Qwen-Image-2.1-UD-Q4_K_XL.gguf": "qwen-image-2.1", "Qwen-Image-2.1-Turbo-UD-Q4_K_XL.gguf": "qwen-image-2.1", "qwen-image-edit-2511-Q4_K_M.gguf": "qwen-image-edit",
                 "qwen-image-edit-2509-Q4_K_M.gguf": "qwen-image-edit", "z-image-turbo-Q4_K_M.gguf": "z-image", "z-image-Q4_K_M.gguf": "z-image", "FLUX.2-klein-4B-Q4_K_M.gguf": "flux2-klein-4b",
                 "FLUX.2-klein-9B-Q4_K_M.gguf": "flux2-klein-9b", "FLUX.2-klein-base-9B-Q4_K_M.gguf": "flux2-klein-9b", "flux2-dev-Q4_K_M.gguf": "flux2-dev", "flux1-schnell-Q4_K_M.gguf": "flux",
                 "flux1-dev-Q4_K_M.gguf": "flux", "flux1-kontext-dev-Q4_K_M.gguf": "flux", "Wan2.2-TI2V-5B-Q4_K_M.gguf": "wan22-ti2v-5b"}
        for name, fam in files.items():
            self.assertEqual((support.family_of(name) or {}).get("id"), fam, name)

    def test_flux1_uses_cfg_1_instead_of_the_default_7(self):
        for name, steps in (("flux1-schnell-Q4_K_M.gguf", 4), ("flux1-dev-Q4_K_M.gguf", 28), ("flux1-kontext-dev-Q4_K_M.gguf", 28), ("flux1-krea-dev-Q4_K_S.gguf", 28)):
            run = support.run_for(support.family_of(name), name)
            self.assertEqual((run["cfg_scale"], run["sample_steps"]), (1.0, steps), name)

    def test_moss_image_recipe_and_companions(self):
        fam = support.family_of(MOSS)
        self.assertEqual(support.run_for(fam, MOSS), {"cfg_scale": 3.0, "sample_steps": 50})
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / MOSS).write_bytes(b"x")
            plan = support.plan(folder, MOSS, "image")
            items = {i["dest"]: i for i in plan["items"]}
            self.assertEqual(set(items), {"moss-image-vae.safetensors", "Qwen3.5-9B-Q8_0.gguf", "moss-image-tokenizer.json"})
            self.assertEqual((items["moss-image-vae.safetensors"]["repo"], items["moss-image-vae.safetensors"]["file"]), ("unsloth/MOSS-Image-SFT-FP8", "vae/diffusion_pytorch_model.safetensors"))
            self.assertEqual(items["moss-image-tokenizer.json"]["file"], "tokenizer/tokenizer.json")
            self.assertEqual(items["Qwen3.5-9B-Q8_0.gguf"]["repo"], "unsloth/Qwen3.5-9B-GGUF")
            for n in items:
                (folder / n).write_bytes(b"x")
            self.assertEqual(support.plan(folder, MOSS, "image")["items"], [])                         # tudo ao lado: nada a baixar
            found = support.find_companions(folder, folder / MOSS, fam)
            self.assertEqual(found, {"vae_path": "moss-image-vae.safetensors", "llm_path": "Qwen3.5-9B-Q8_0.gguf", "tokenizer_path": "moss-image-tokenizer.json"})
            self.assertEqual(sorted(support.status_of(folder, MOSS, "image")["missing"]), [])

    def test_renamed_support_files_are_saved_under_their_own_name(self):
        saved = []
        with tempfile.TemporaryDirectory() as d, mock.patch.object(hf, "download", side_effect=lambda repo, file, folder, token, prog, canc, **k: saved.append((repo, file, k.get("dest_name")))), \
                mock.patch.object(hf, "download_many", side_effect=lambda repo, files, *a, **k: saved.append((repo, files[0], None))):
            (Path(d) / MOSS).write_bytes(b"x")
            got = support.download_missing(Path(d), MOSS)
        self.assertEqual(sorted(got), ["Qwen3.5-9B-Q8_0.gguf", "moss-image-tokenizer.json", "moss-image-vae.safetensors"])
        self.assertIn(("unsloth/MOSS-Image-SFT-FP8", "vae/diffusion_pytorch_model.safetensors", "moss-image-vae.safetensors"), saved)       # o VAE «diffusion_pytorch_model» não colide com outros
        self.assertIn(("unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q8_0.gguf", None), saved)

    def test_support_files_are_not_listed_as_models_and_the_pypi_library_is_skipped(self):
        self.assertTrue(installed.SUPPORT_RE.search("Qwen3.5-9B-Q8_0.gguf"))
        self.assertFalse(installed.SUPPORT_RE.search(MOSS))
        with mock.patch.object(M, "_lib_is_stale", return_value=True):
            self.assertTrue(M._lib_never_knows(MOSS))                                                  # a biblioteca 0.4.7 não conhece o MOSS-Image: vai direto ao sd-cli
            self.assertFalse(M._lib_never_knows("z-image-turbo-Q4_K_M.gguf"))
        with mock.patch.object(M, "_lib_is_stale", return_value=False):
            self.assertFalse(M._lib_never_knows(MOSS))

    def test_the_sd_cli_gets_the_moss_arguments_from_the_model_card(self):
        fam = support.family_of(MOSS)
        load = {"diffusion_model_path": "/m/moss.gguf", "llm_path": "/m/q.gguf", "vae_path": "/m/vae.safetensors", "tokenizer_path": "/m/tok.json", **fam["options"]}
        args, warns = sdcli.build_args(Path("/x/sd-cli"), load, support.run_for(fam, MOSS), prompt="uma placa", width=1024, height=1024, seed=42, out=Path("/t/o.png"))
        pairs = {args[i]: args[i + 1] for i in range(len(args) - 1)}
        self.assertEqual((pairs["--tokenizer"], pairs["--llm"], pairs["--vae"], pairs["--cfg-scale"], pairs["--steps"]), ("/m/tok.json", "/m/q.gguf", "/m/vae.safetensors", "3.0", "50"))
        self.assertEqual(warns, [])


class CatalogTests(ServerCase):
    def test_catalog_is_honest_about_what_runs(self):
        cat = unsloth_models.catalog()
        self.assertTrue(all(e["repo"].startswith("unsloth/") and e["kind"] in ("image", "video") for e in cat))
        by = {e["repo"]: e for e in cat}
        self.assertEqual(by["unsloth/MOSS-Image-SFT-GGUF"]["status"], "ready")
        self.assertEqual(by["unsloth/Wan2.2-TI2V-5B-GGUF"]["status"], "ready")
        self.assertEqual(by["unsloth/flux-3-image-klein-GGUF"]["status"], "alt")
        self.assertEqual(by["unsloth/flux-3-image-klein-GGUF"]["use"], support.SD_NATIVE[0]["repo"])      # aponta o mesmo repositório do aviso da v0.18
        for repo in ("unsloth/MiniMax-H3-GGUF", "unsloth/LTX-2.5-GGUF", "unsloth/LTX-2.3-GGUF", "unsloth/LTX-2-GGUF"):
            self.assertEqual(by[repo]["status"], "beta", repo)                                            # v0.22: rodam, mas sem verificação em hardware real
        self.assertEqual(by["unsloth/ERNIE-Image-Turbo-GGUF"]["status"], "soon")
        self.assertTrue(by["unsloth/ERNIE-Image-Turbo-GGUF"]["why"])                                      # diz por que ainda não
        for e in cat:
            if e["status"] in ("ready", "beta"):
                self.assertTrue(e["hint"], e["repo"])

    def test_every_ready_model_has_a_family(self):
        for e in unsloth_models.catalog():
            if e["status"] != "ready":
                continue
            probe = e["repo"].split("/")[-1].replace("-GGUF", "") + "-Q4_K_M.gguf"
            self.assertIsNotNone(support.family_of(probe) or support.family_of(probe.replace("FLUX.1-", "flux1-")), e["repo"])

    def test_the_endpoint_filters_by_kind(self):
        s, r = self.c.json("GET", "/api/unsloth/catalog?kind=video")
        self.assertEqual(s, 200)
        self.assertTrue(r["models"] and all(m["kind"] == "video" for m in r["models"]))
        s, r = self.c.json("GET", "/api/unsloth/catalog")
        self.assertEqual({m["kind"] for m in r["models"]}, {"image", "video"})


if __name__ == "__main__":
    unittest.main()
