"""v0.30: MiniMax H3 Image (imagem e edição) e o MiniMax H3 de vídeo — família, receita do cartão, arquivos de apoio, referências <Picture N> e tamanhos."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow import unsloth_models
from openflow.canvas import media as M
from openflow.canvas import sdcli, support

IMG = "minimax_h3_image_pruned-UD-Q4_K_XL.gguf"
VID = "minimax_h3_fl2va_pruned-UD-Q4_K_XL.gguf"
REF = "minimax_h3_ref2va_pruned-Q4_K.gguf"


class FamilyTests(unittest.TestCase):
    def test_image_video_and_references_are_separate_families(self):
        self.assertEqual((support.family_of(IMG)["id"], support.family_of(IMG)["cap"]), ("minimax-h3-image", "image"))
        self.assertEqual((support.family_of(VID)["id"], support.family_of(VID)["cap"]), ("minimax-h3", "video"))
        self.assertEqual(support.family_of(REF)["id"], "minimax-h3-ref")
        self.assertEqual(support.family_of("minimax-h3-image-Q8_0.gguf")["id"], "minimax-h3-image")            # outros nomes de arquivo da comunidade

    def test_the_cards_recipe(self):
        run = support.run_for(support.family_of(IMG), IMG)
        self.assertEqual((run["cfg_scale"], run["sample_steps"], run["sample_method"], run["sigmas"], run["rng"]), (1.0, 6, "euler", "minimax-h3-image", "cpu"))

    def test_companions_and_downloads(self):
        fam = support.family_of(IMG)
        self.assertEqual(support.download_spec(fam, "vae_path", IMG)["repo"], "MiniMaxAI/MiniMax-H3-Image")
        self.assertEqual(support.download_spec(fam, "vae_path", IMG)["dest"], "minimax-h3-image-vae.safetensors")   # não colide com outros «diffusion_pytorch_model»
        self.assertEqual(support.download_spec(fam, "llm_path", IMG)["file"], "qwen3vl_32b_minimax_h3-Q4_K_M.gguf")
        self.assertEqual(support.download_spec(fam, "llm_path", "minimax_h3_image_pruned-UD-Q2_K_XL.gguf")["file"], "qwen3vl_32b_minimax_h3-Q2_K_M.gguf")
        with tempfile.TemporaryDirectory() as d:
            for n in (IMG, "minimax-h3-image-vae.safetensors", "qwen3vl_32b_minimax_h3-Q4_K_M.gguf"):
                (Path(d) / n).write_bytes(b"x")
            found = support.find_companions(Path(d), Path(d) / IMG, fam)
            self.assertTrue(all(v is not None for v in found.values()), found)

    def test_sd_cli_arguments(self):
        load = {"diffusion_model_path": "/m/i.gguf", "vae_path": "/m/v.safetensors", "llm_path": "/m/q.gguf", "offload_params_to_cpu": True}
        args, warns = sdcli.build_args(Path("/x/sd-cli"), load, support.run_for(support.family_of(IMG), IMG), prompt="p", width=1024, height=1024, seed=1, out=Path("/t/o.png"), refs=[Path("/t/r.png")])
        self.assertEqual(warns, [])
        self.assertEqual(args[args.index("--sigmas") + 1], "minimax-h3-image")
        self.assertEqual(args[args.index("--rng") + 1], "cpu")
        self.assertEqual(args[args.index("--steps") + 1], "6")
        self.assertIn("-r", args)

    def test_the_library_never_loads_it(self):
        self.assertTrue(M._lib_never_knows(IMG) or M._NEWER_THAN_LIB.search(IMG))


class PromptTests(unittest.TestCase):
    def test_picture_convention(self):
        self.assertEqual(M.h3_picture_prompt("troque o fundo", 1), "Edit <Picture 1>. troque o fundo")
        self.assertEqual(M.h3_picture_prompt("junte", 3), "Reference images: <Picture 1>, <Picture 2>, <Picture 3>. junte")
        self.assertEqual(M.h3_picture_prompt("Edit <Picture 2> only", 2), "Edit <Picture 2> only")      # o prompt já cita: não mexe
        self.assertEqual(M.h3_picture_prompt("um gato", 0), "um gato")


class ProviderTests(unittest.TestCase):
    def provider(self, name):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "image").mkdir()
        (tmp / "image" / name).write_bytes(b"x")
        return M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(tmp), "models": {"image": name}, "needs_key": False}), tmp

    def test_up_to_16_references_and_edit_mode(self):
        p, _ = self.provider(IMG)
        self.assertEqual(p.max_refs(""), 16)
        self.assertTrue(p.frames_edit_for(""))
        self.assertFalse(p.refs_need_edit(""))                        # as referências valem também no modo Gerar

    def test_image_cli_uses_multiples_of_32_and_the_picture_prompt(self):
        p, tmp = self.provider(IMG)
        for n in ("minimax-h3-image-vae.safetensors", "qwen3vl_32b_minimax_h3-Q4_K_M.gguf"):
            (tmp / "image" / n).write_bytes(b"x")
        seen = {}

        def fake(exe, load, run_p, **kw):
            seen.update(kw, run=run_p)
            return b"PNG", []

        from PIL import Image
        import io

        buf = io.BytesIO()
        Image.new("RGB", (64, 48), "red").save(buf, "PNG")
        ref = (buf.getvalue(), "image/png")
        with mock.patch.object(sdcli, "find", return_value=Path("/x/sd-cli")), mock.patch.object(sdcli, "generate_image", side_effect=fake), mock.patch.object(p, "_cli_call", side_effect=lambda path, fn: fn(Path("/x/sd-cli"))):
            p._image_cli(tmp / "image" / IMG, support.family_of(IMG) and {"diffusion_model_path": "@model", "vae_path": "minimax-h3-image-vae.safetensors", "llm_path": "qwen3vl_32b_minimax_h3-Q4_K_M.gguf"}, support.run_for(support.family_of(IMG), IMG), "troque", "1000x700", 1, 1, "", [ref])
        self.assertEqual((seen["width"] % 32, seen["height"] % 32), (0, 0))
        self.assertTrue(seen["prompt"].startswith("Edit <Picture 1>."))
        self.assertEqual(len(seen["refs"]), 1)


class CatalogTests(unittest.TestCase):
    def test_catalog_lists_the_image_model(self):
        by = {e["repo"]: e for e in unsloth_models.catalog()}
        e = by["unsloth/MiniMax-H3-Image-GGUF"]
        self.assertEqual((e["kind"], e["status"]), ("image", "beta"))
