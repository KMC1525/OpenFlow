"""v0.75: modelos GGUF (stable-diffusion.cpp) — cada família de imagem é carregada com os arquivos de apoio certos e gera/edita com os parâmetros dela, com a biblioteca `stable_diffusion_cpp` simulada (um `generate_image` com a assinatura
da biblioteca). Que o sd.cpp real gere a imagem, e com boa qualidade, NÃO foi verificado: isto prova que o OpenFlow monta o pedido certo para cada família."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import media as M
from openflow.canvas import procedural as proc
from openflow.canvas import support
from openflow.providers import ProviderError
from tests.test_canvas import PNG

# arquivo de modelo → família esperada, se aceita várias imagens de referência (edição) e passos/cfg da geração só com texto
IMAGE_FILES = {
    "z_image_turbo-Q4_K_M.gguf": ("z-image", False, (8, 1.0)),
    "Z-Image-Q4_K_M.gguf": ("z-image", False, (30, 4.0)),
    "qwen-image-2.1-Q4_K_M.gguf": ("qwen-image-2.1", True, (20, 6.0)),
    "Qwen-Image-Edit-2509-Q4_K_M.gguf": ("qwen-image-edit", True, (None, 2.5)),
    "Qwen-Image-Q4_K_M.gguf": ("qwen-image", False, (None, 2.5)),
    "Qwen-Image-Lightning-8steps-V1.1-Q4_K_M.gguf": ("qwen-image", False, (8, 1.0)),        # v0.75: Lightning é destilado: 8 passos, sem CFG
    "Qwen-Image-Edit-2509-Lightning-4steps-Q4.gguf": ("qwen-image-edit", True, (4, 1.0)),
    "flux1-dev-Q4_K_S.gguf": ("flux", False, (28, 1.0)),
    "flux1-schnell-Q4_0.gguf": ("flux", False, (4, 1.0)),
    "FLUX.1-Kontext-dev-Q4_K_M.gguf": ("flux", True, (28, 1.0)),
    "flux1-krea-dev-Q4_K_M.gguf": ("flux1-krea", False, (28, 1.0)),
    "FLUX.2-klein-4B-Q8_0.gguf": ("flux2-klein-4b", True, (4, 1.0)),
    "flux-2-klein-base-4B-Q4_K_M.gguf": ("flux2-klein-4b", True, (50, 4.0)),
    "FLUX.2-klein-9B-Q4_K_M.gguf": ("flux2-klein-9b", True, (4, 1.0)),
    "FLUX.2-dev-Q4_K_M.gguf": ("flux2-dev", True, (28, 1.0)),
}


def companion_names(fam):
    return {key: spec.get("dest") or Path(spec["file"]).name for key, spec in (fam.get("downloads") or {}).items()}


class FakeSD:
    """`stable_diffusion_cpp` com a assinatura de `generate_image` da biblioteca."""

    def __init__(self):
        self.loads, self.runs = [], []
        outer = self

        class Img:
            def save(self, buf, format="PNG"):
                buf.write(PNG)

        class StableDiffusion:
            def __init__(self, **kw):
                outer.loads.append(kw)

            def generate_image(self, prompt="", negative_prompt="", width=512, height=512, seed=-1, sample_steps=20, cfg_scale=7.0, sample_method=None, flow_shift=None, init_image=None, ref_images=None,
                               strength=0.75, **rest):
                outer.runs.append(dict(prompt=prompt, negative_prompt=negative_prompt, width=width, height=height, seed=seed, sample_steps=sample_steps, cfg_scale=cfg_scale, init_image=init_image,
                                       ref_images=ref_images, strength=strength))
                return [Img()]
        self.module = mock.MagicMock(StableDiffusion=StableDiffusion)


class GgufImageMatrixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "image").mkdir()
        M._LOCAL_CACHE.clear()
        self.sd = FakeSD()
        p = mock.patch.dict(sys.modules, {"stable_diffusion_cpp": self.sd.module})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False)
        q.start()
        self.addCleanup(q.stop)

    def provider(self, name):
        (self.tmp / "image" / name).write_bytes(b"gguf")
        fam = support.family_of(name)
        for fname in companion_names(fam).values():
            (self.tmp / "image" / fname).write_bytes(b"x")
        M._LOCAL_CACHE.clear()
        return M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {"image": name}, "needs_key": False})

    def test_every_family_is_recognised_from_a_typical_file_name(self):
        for name, (fam_id, _multi, _run) in IMAGE_FILES.items():
            self.assertEqual((support.family_of(name) or {}).get("id"), fam_id, name)

    def test_every_family_generates_with_its_companions_and_its_parameters(self):
        for name, (fam_id, _multi, (steps, cfg)) in IMAGE_FILES.items():
            self.sd.loads.clear()
            self.sd.runs.clear()
            out = self.provider(name).image("um gato de capa", size="1280x720", seed=3)
            self.assertEqual(out[0].mime, "image/png", name)
            load, run = self.sd.loads[0], self.sd.runs[0]
            fam = support.family_of(name)
            if fam_id not in ("flux",):
                for key, fname in companion_names(fam).items():
                    if key in (fam.get("edit_needs") or []):
                        continue                                                               # o projetor de visão só carrega ao editar
                    self.assertTrue(str(load.get(key, "")).endswith(fname), f"{name}: {key} -> {load.get(key)}")
            self.assertEqual(run["cfg_scale"], cfg, name)
            if steps is not None:
                self.assertEqual(run["sample_steps"], steps, name)
            self.assertEqual((run["width"] % 16, run["height"] % 16), (0, 0), name)
            self.assertEqual((run["width"], run["height"]), (1280, 720), name)                 # a proporção e o tamanho pedidos
            self.assertIsNone(run["ref_images"], name)
            self.assertIsNone(run["init_image"], name)

    def test_every_family_edits_the_way_it_can(self):
        refs = [(proc.image(f"r{i}", "96x64", i + 1), "image/png") for i in range(5)]
        for name, (fam_id, multi, _run) in IMAGE_FILES.items():
            self.sd.loads.clear()
            self.sd.runs.clear()
            prov = self.provider(name)
            prov.edit_mode = True
            try:
                out = prov.image("troque a capa por vermelha", size="768x768", refs=refs[:1], model=name)
            except ProviderError as exc:
                self.fail(f"{name}: {exc}")
            run = self.sd.runs[0]
            self.assertEqual(out[0].mime, "image/png", name)
            if multi:
                self.assertIsNotNone(run["ref_images"], name)                                     # modelos de edição: a imagem vai como referência
                self.assertIsNone(run["init_image"], name)
            else:
                self.assertIsNotNone(run["init_image"], name)                                     # os demais: imagem → imagem
                self.assertIsNone(run["ref_images"], name)
                self.assertTrue(0 < run["strength"] < 1, name)

    def test_several_references_are_cut_at_the_family_limit(self):
        refs = [(proc.image(f"r{i}", "96x64", i + 1), "image/png") for i in range(6)]
        for name in ("Qwen-Image-Edit-2509-Q4_K_M.gguf", "FLUX.2-klein-4B-Q8_0.gguf"):
            self.sd.runs.clear()
            prov = self.provider(name)
            prov.edit_mode = False
            prov.image("junte as imagens", size="768x768", refs=refs, model=name)
            self.assertEqual(len(self.sd.runs[0]["ref_images"]), 4, name)

    def test_the_reference_limit_per_family(self):
        prov = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {}, "needs_key": False})
        for name, (fam_id, multi, _run) in IMAGE_FILES.items():
            if fam_id in ("flux2-dev",):
                continue
            want = 4 if multi else 1
            self.assertEqual(prov.max_refs(name), want, name)

    def test_the_vae_of_qwen_image_2_1_is_not_taken_by_the_other_qwen_families(self):
        folder = self.tmp / "image"
        for n in ("qwen_image_2.1_vae_bf16.safetensors", "qwen_image_vae.safetensors", "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "mmproj-F16.gguf"):
            (folder / n).write_bytes(b"x")
        (folder / "Qwen-Image-Edit-2509-Q4_K_M.gguf").write_bytes(b"g")
        found = support.find_companions(folder, folder / "Qwen-Image-Edit-2509-Q4_K_M.gguf", support.family_of("Qwen-Image-Edit-2509-Q4_K_M.gguf"))
        self.assertTrue(found["vae_path"].endswith("qwen_image_vae.safetensors"), found)           # antes podia ser o VAE do 2.1: imagens estragadas
        (folder / "qwen-image-2.1-Q4_K_M.gguf").write_bytes(b"g")
        found = support.find_companions(folder, folder / "qwen-image-2.1-Q4_K_M.gguf", support.family_of("qwen-image-2.1-Q4_K_M.gguf"))
        self.assertTrue((found["vae_path"] or "").endswith("qwen_image_2.1_vae_bf16.safetensors"), found)

    def test_missing_companions_are_listed_for_the_support_button(self):
        folder = self.tmp / "image"
        (folder / "Qwen-Image-Edit-Q4_K_M.gguf").write_bytes(b"gguf")                          # sem VAE, codificador de texto nem projetor
        info = support.missing(folder, "Qwen-Image-Edit-Q4_K_M.gguf")
        self.assertEqual({m["key"] for m in info["missing"]}, {"vae_path", "llm_path", "llm_vision_path"})
        self.assertGreater(info["approx_gb"], 5)


if __name__ == "__main__":
    unittest.main()
