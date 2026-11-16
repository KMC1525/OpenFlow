"""v0.41: ChatR Labs · Qwen-Image 2.1 Uncensored Omni Quantized — os GGUF do repositório são reconhecidos como Qwen-Image 2.1 com a receita do cartão (35 passos, CFG 5,0), baixam junto o VAE e o Qwen3-VL-8B,
aparecem no catálogo, e o que o OpenFlow não carrega (transformador só para o diffusers) explica o caminho certo."""
import tempfile
import unittest
from pathlib import Path

from openflow import hf, unsloth_models
from openflow.canvas import media as M
from openflow.canvas import support
from openflow.providers.base import ProviderError

REPO = "chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized"
GGUF = {"BF16": 14230297376, "Q8_0": 7687183136, "Q6_K": 5996878624, "Q5_K_M": 5212543776, "Q4_K_M": 4474346272, "Q4_0": 4197522208}
TREE = ([{"name": f"qwen-image-2.1-step90000-{q}.gguf", "size": s} for q, s in GGUF.items()]
        + [{"name": "qwen-image-2.1-step90000-FP8-comfy.safetensors", "size": 7116789419}, {"name": "qwen-image-2.1-step90000-INT8-ConvRot-comfy.safetensors", "size": 7256791144},
           {"name": "qwen-image-2.1-step90000-NVFP4-comfy.safetensors", "size": 4197574792}, {"name": "qwen-image-2.1-step90000-NF4-bnb/diffusion_pytorch_model.safetensors", "size": 3670960573},
           {"name": "qwen-image-2.1-step90000-BF16/config.json", "size": 370}, {"name": "workflow_example.json", "size": 14487}, {"name": "README.md", "size": 14715}])


class FamilyTests(unittest.TestCase):
    def test_every_gguf_of_the_repo_is_a_qwen_image_21_with_the_card_recipe(self):
        for q in GGUF:
            name = f"qwen-image-2.1-step90000-{q}.gguf"
            fam = support.family_of(name)
            self.assertEqual(fam["id"], "qwen-image-2.1", name)
            self.assertEqual(support.run_for(fam, name), {"cfg_scale": 5.0, "sample_steps": 35, "sample_method": "euler"}, name)

    def test_the_official_models_keep_their_own_recipes(self):
        f = lambda n: support.run_for(support.family_of(n), n)  # noqa: E731
        self.assertEqual((f("Qwen-Image-2.1-Q4_K_M.gguf")["cfg_scale"], f("Qwen-Image-2.1-Q4_K_M.gguf")["sample_steps"]), (6.0, 20))
        self.assertEqual((f("Qwen-Image-2.1-Turbo-Q4_K_M.gguf")["cfg_scale"], f("Qwen-Image-2.1-Turbo-Q4_K_M.gguf")["sample_steps"]), (1.0, 8))

    def test_it_joins_several_references_like_the_official_model(self):
        self.assertTrue(M._GGUF_MULTI_REF.search("qwen-image-2.1-step90000-Q5_K_M.gguf"))

    def test_the_repo_lists_only_the_gguf_files_with_their_quantizations(self):
        files = hf.group_files([f for f in TREE if f["name"].lower().endswith(".gguf") and hf.FILE_RE.match(Path(f["name"]).name)], 32)
        self.assertEqual(sorted(f["quant"] for f in files), sorted(GGUF))
        self.assertEqual([f["quant"] for f in files if f.get("recommended")], ["Q4_K_M"])
        self.assertIsNone(support.sd_compat_warning(REPO))   # não é um repositório com aviso de incompatibilidade

    def test_the_vae_and_the_qwen3_vl_encoder_come_along_and_the_comfy_files_are_not_mistaken_for_them(self):
        plan = support.plan(Path(tempfile.mkdtemp()), "qwen-image-2.1-step90000-Q4_K_M.gguf", "image", REPO, TREE)
        self.assertEqual(plan["family"], "qwen-image-2.1")
        got = {(i["role"], i["repo"], i["file"]) for i in plan["items"]}
        self.assertEqual(got, {("vae", "unsloth/Qwen-Image-2.1-FP8", "vae/qwen_image_2.1_vae_bf16.safetensors"), ("text_encoder", "unsloth/Qwen3-VL-8B-Instruct-GGUF", "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf"),
                       ("mmproj", "unsloth/Qwen3-VL-8B-Instruct-GGUF", "mmproj-F16.gguf")})   # v0.55: o projetor de visão, para editar com imagem de referência


class CatalogTests(unittest.TestCase):
    def test_listed_as_experimental_with_the_license_and_the_formats(self):
        e = next(x for x in unsloth_models.catalog("image") if x["repo"] == REPO)
        self.assertEqual(e["status"], "beta")           # roda, mas não foi verificado em hardware real
        for word in ("35 passos", "CFG 5,0", "Qwen Research", "diffusers", "ComfyUI", ".gguf"):
            self.assertIn(word, e["hint"])

    def test_the_hint_has_an_english_translation(self):
        js = (Path(__file__).resolve().parent.parent / "openflow" / "web" / "js" / "en.js").read_text(encoding="utf-8")
        e = next(x for x in unsloth_models.catalog("image") if x["repo"] == REPO)
        self.assertIn("'" + e["hint"].replace("'", "\\'") + "':", js)


class DiffusersTests(unittest.TestCase):
    def test_the_transformer_only_repo_explains_to_use_the_gguf_files(self):
        self.assertTrue(M.LocalHFMedia._transformer_only(REPO))
        self.assertFalse(M.LocalHFMedia._transformer_only("stabilityai/sd-turbo"))
        p = M.LocalHFMedia({"id": "local_hf", "models": {"image": REPO}})
        with self.assertRaises(ProviderError) as cm:
            p.image("um gato", model=REPO)
        msg = str(cm.exception)
        self.assertIn(".gguf", msg)
        self.assertIn("GGUF local", msg)


if __name__ == "__main__":
    unittest.main()
