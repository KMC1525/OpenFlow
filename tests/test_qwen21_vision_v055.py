"""v0.55: Qwen-Image 2.1 (inclusive o «Uncensored Omni Quantized» da ChatR Labs) ao editar com imagem de referência — o sd-cli exige o projetor de visão (mmproj) do Qwen3-VL
(«Qwen Image 2.1 editing requires Qwen3-VL vision weights; provide --llm_vision…»). Ele vem junto com o modelo, só é exigido ao editar e tem nome próprio na pasta."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import media as M
from openflow.canvas import support
from openflow.providers.base import ProviderError

MODEL = "qwen-image-2.1-step90000-Q4_K_M.gguf"
VAE = "qwen_image_2.1_vae_bf16.safetensors"
LLM = "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf"
VISION = "Qwen3-VL-8B-Instruct-mmproj-F16.gguf"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30


def folder(*extra):
    d = Path(tempfile.mkdtemp())
    for n in (MODEL, VAE, LLM, *extra):
        (d / n).write_bytes(b"x")
    return d


class FamilyTests(unittest.TestCase):
    def test_the_family_knows_the_vision_projector_and_where_to_get_it(self):
        fam = support.family_of(MODEL)
        self.assertEqual(fam["id"], "qwen-image-2.1")
        self.assertIn("llm_vision_path", fam["load"])
        self.assertEqual(fam["optional"], ["llm_vision_path"])
        d = support.download_spec(fam, "llm_vision_path", MODEL)
        self.assertEqual((d["repo"], d["file"], d["dest"]), ("unsloth/Qwen3-VL-8B-Instruct-GGUF", "mmproj-F16.gguf", VISION))     # nome próprio: o do Qwen2.5-VL também é mmproj-F16.gguf

    def test_it_is_found_next_to_the_model_and_not_confused_with_the_text_encoder(self):
        fam = support.family_of(MODEL)
        found = support.find_companions(folder(VISION), Path("/x") / MODEL, fam)
        self.assertEqual((found["llm_path"], found["llm_vision_path"], found["vae_path"]), (LLM, VISION, VAE))
        self.assertIsNone(support.find_companions(folder(), Path("/x") / MODEL, fam)["llm_vision_path"])
        # o mmproj de OUTRO modelo (Qwen2.5-VL) não vale para este
        self.assertIsNone(support.find_companions(folder("mmproj-F16.gguf"), Path("/x") / MODEL, fam)["llm_vision_path"])

    def test_the_download_plan_and_status_include_it(self):
        d = folder()
        plan = support.plan(d, MODEL, "image")
        self.assertIn(("mmproj", VISION), {(i["role"], i["dest"]) for i in plan["items"]})
        self.assertIn("mmproj", {m["role"] for m in support.status_of(d, MODEL, "image")["missing"]})
        full = folder(VISION)
        self.assertEqual(support.plan(full, MODEL, "image")["items"], [])
        self.assertEqual(support.status_of(full, MODEL, "image")["missing"], [])

    def test_missing_for_edit_only_lists_what_editing_needs(self):
        self.assertEqual([m["key"] for m in support.missing_for_edit(folder(), MODEL)], ["llm_vision_path"])
        self.assertEqual(support.missing_for_edit(folder(VISION), MODEL), [])
        self.assertEqual(support.missing_for_edit(folder(), "flux-2-klein-4b-Q4_K_M.gguf"), [])       # outras famílias não mudam
        self.assertEqual(support.missing_for_edit(folder(), "arquivo-desconhecido.gguf"), [])

    def test_older_installs_without_the_projector_still_load_for_generation(self):
        d = folder()
        p = M.GGUFMedia({"models_dir": str(d.parent)})
        auto = p._auto_load(d / MODEL)
        self.assertEqual(auto["load"]["llm_path"], LLM)             # antes de tornar opcional, a falta do mmproj derrubaria o carregamento automático
        self.assertNotIn("llm_vision_path", auto["load"])
        auto = p._auto_load(folder(VISION) / MODEL)
        self.assertEqual(auto["load"]["llm_vision_path"], VISION)


class EditTests(unittest.TestCase):
    def provider(self, *extra):
        d = folder(*extra)
        (d.parent / "image").mkdir(exist_ok=True)
        root = Path(tempfile.mkdtemp())
        (root / "image").mkdir()
        for f in d.iterdir():
            (root / "image" / f.name).write_bytes(b"x")
        return M.GGUFMedia({"models_dir": str(root), "models": {"image": MODEL}}), root / "image"

    def test_editing_without_the_projector_explains_instead_of_failing_in_sd_cli(self):
        p, _ = self.provider()
        with mock.patch.object(M.GGUFMedia, "_engine", side_effect=AssertionError("não devia chegar ao motor")):
            with self.assertRaises(ProviderError) as cm:
                p.image("troque o fundo", refs=[(PNG, "image/png")])
        msg = str(cm.exception)
        self.assertIn("Projetor de visão", msg)
        self.assertIn("editar", msg)
        self.assertIn("Gerar só com texto continua funcionando", msg)
        self.assertIn(f"[[flow-support:{MODEL}]]", msg)               # o botão «Baixar os arquivos de apoio» do nó

    def test_generating_from_text_never_needs_it_and_does_not_load_it(self):
        p, d = self.provider(VISION)
        seen = {}

        def engine(self, cap, path, load):
            seen["load"] = dict(load)
            raise ProviderError("parou aqui")
        with mock.patch.object(M.GGUFMedia, "_engine", engine), mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False):
            with self.assertRaises(ProviderError):
                p.image("um gato")
        self.assertNotIn("llm_vision_path", seen["load"])             # não carrega ≈ 1,2 GB à toa
        p2, _ = self.provider()                                       # sem o arquivo também gera
        with mock.patch.object(M.GGUFMedia, "_engine", engine), mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False):
            with self.assertRaises(ProviderError) as cm:
                p2.image("um gato")
        self.assertEqual(str(cm.exception).count("Projetor de visão"), 0)

    def test_editing_with_the_projector_passes_it_to_the_loader(self):
        p, d = self.provider(VISION)
        seen = {}

        def engine(self, cap, path, load):
            seen["load"] = dict(load)
            raise ProviderError("parou aqui")
        with mock.patch.object(M.GGUFMedia, "_engine", engine), mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False):
            with self.assertRaises(ProviderError):
                p.image("troque o fundo", refs=[(PNG, "image/png")])
        self.assertEqual(seen["load"]["llm_vision_path"], VISION)
        self.assertEqual(seen["load"]["llm_path"], LLM)

    def test_the_sd_cli_gets_the_llm_vision_flag(self):
        from openflow.canvas import sdcli
        args, _ = sdcli.build_args(Path("/x/sd-cli"), {"diffusion_model_path": "/m/a.gguf", "llm_vision_path": "/m/" + VISION}, {}, prompt="p", width=512, height=512, seed=1, out=Path("/tmp/o.png"))
        self.assertIn("--llm_vision", args)
        self.assertEqual(args[args.index("--llm_vision") + 1], "/m/" + VISION)

    def test_other_families_and_custom_load_are_untouched(self):
        p, d = self.provider()
        (d / "flux-2-klein-4b-Q4_K_M.gguf").write_bytes(b"x")
        self.assertEqual(support.missing_for_edit(d, "flux-2-klein-4b-Q4_K_M.gguf"), [])
        seen = {}

        def engine(self, cap, path, load):
            seen["load"] = dict(load)
            raise ProviderError("parou aqui")
        with mock.patch.object(M.GGUFMedia, "_engine", engine), mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False):
            with self.assertRaises(ProviderError):
                p.image("troque", refs=[(PNG, "image/png")], extra={"load": {"llm_vision_path": "meu-mmproj.gguf"}})      # quem informou o seu mmproj não é barrado
        self.assertEqual(seen["load"]["llm_vision_path"], "meu-mmproj.gguf")


if __name__ == "__main__":
    unittest.main()
