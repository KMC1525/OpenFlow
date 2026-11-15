"""v0.24: FLUX.3 Image Klein — versão «base» com repositório e receita próprios, quantizações da Unsloth e receita do docs da stable-diffusion.cpp."""
import unittest
from pathlib import Path

from openflow import hf, unsloth_models
from openflow.canvas import sdcli, support

DIST, BASE = "flux3-image-klein-Q4_K.gguf", "flux3-image-klein-base-Q4_K.gguf"


class RecipeTests(unittest.TestCase):
    def test_distilled_and_base_recipes(self):
        d, b = support.run_for(support.family_of(DIST), DIST), support.run_for(support.family_of(BASE), BASE)
        self.assertEqual((d["cfg_scale"], d["sample_steps"], d["sample_method"]), (1.0, 16, "euler"))
        self.assertEqual((b["cfg_scale"], b["sample_steps"], b["sample_method"]), (3.5, 20, "euler"))

    def test_every_flux3_file_name_is_one_family(self):
        for n in (DIST, BASE, "flux-3-image-klein-UD-Q4_K_XL.gguf", "flux-3-image-klein-base-Q8_0.gguf"):
            self.assertEqual(support.family_of(n)["id"], "flux3-klein", n)
        self.assertNotEqual((support.family_of("flux-3-image-klein-pup-Q4_K_M.gguf") or {}).get("id"), "flux3-klein")   # o expansor de prompt é de texto

    def test_arguments_carry_euler_and_the_encoder(self):
        load = {"diffusion_model_path": "/m/b.gguf", "vae_path": "/m/v.safetensors", "llm_path": "/m/q.gguf", "offload_params_to_cpu": True}
        args, warns = sdcli.build_args(Path("/x/sd-cli"), load, support.run_for(support.family_of(BASE), BASE), prompt="p", width=1024, height=1024, seed=1, out=Path("/t/o.png"))
        self.assertEqual(warns, [])
        self.assertEqual(args[args.index("--sampling-method") + 1], "euler")
        self.assertEqual(args[args.index("--steps") + 1], "20")


class NativeRepoTests(unittest.TestCase):
    def test_base_has_its_own_repository(self):
        self.assertEqual(support.sd_native_for(BASE)["repo"], "leejet/flux-3-image-klein-base-GGUF")
        self.assertEqual(support.sd_native_for("x.gguf", "someone/flux-3-image-klein-base-GGUF")["repo"], "leejet/flux-3-image-klein-base-GGUF")
        self.assertEqual(support.sd_native_for(DIST)["repo"], "leejet/flux-3-image-klein-GGUF")
        self.assertIsNone(support.sd_compat_warning("leejet/flux-3-image-klein-base-GGUF"))
        self.assertEqual(support.sd_compat_warning("Abiray/flux-3-image-klein-base-GGUF")["repo"], "leejet/flux-3-image-klein-base-GGUF")

    def test_unsloth_xl_quantisations_map_to_the_k_quants(self):
        groups = [{"quant": q, "bits": int(q[1]), "files": [q], "recommended": q == "Q4_K"} for q in ("Q2_K", "Q3_K", "Q4_0", "Q4_K", "Q5_K", "Q6_K", "Q8_0")]
        for name, want in (("flux-3-image-klein-UD-Q4_K_XL.gguf", "Q4_K"), ("flux-3-image-klein-UD-Q5_K_XL.gguf", "Q5_K"), ("flux-3-image-klein-Q3_K_M.gguf", "Q3_K"), ("flux-3-image-klein-UD-Q2_K_XL.gguf", "Q2_K")):
            self.assertEqual(hf.pick_equivalent(name, groups)["quant"], want, name)

    def test_catalog_mentions_the_base_repository(self):
        e = next(x for x in unsloth_models.catalog() if x["repo"] == "unsloth/flux-3-image-klein-GGUF")
        self.assertIn("leejet/flux-3-image-klein-base-GGUF", e["hint"])


if __name__ == "__main__":
    unittest.main()
