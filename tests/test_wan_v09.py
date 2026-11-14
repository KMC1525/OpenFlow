"""v0.9: modelos Wan locais (Alibaba): Wan2.2 T2V/I2V A14B (dois modelos) e Wan2.1 I2V."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import media as M
from openflow.canvas import sdcli, support
from openflow.providers.base import ProviderError

LOW_T = "Wan2.2-T2V-A14B-LowNoise-Q4_K_M.gguf"
HIGH_T = "Wan2.2-T2V-A14B-HighNoise-Q4_K_M.gguf"


class FamilyTests(unittest.TestCase):
    def test_families_are_recognised_and_the_high_noise_file_is_not_a_model(self):
        for name, fam in {LOW_T: "wan22-t2v-a14b", "Wan2.2-I2V-A14B-LowNoise-Q8_0.gguf": "wan22-i2v-a14b", "wan2.1-i2v-14b-480p-Q4_K_M.gguf": "wan21-i2v",
                          "wan2.1-t2v-14b-Q4_K_M.gguf": "wan21-t2v", "Wan2.2-TI2V-5B-Q4_K_M.gguf": "wan22-ti2v-5b"}.items():
            self.assertEqual(support.family_of(name)["id"], fam, name)
        for high in (HIGH_T, "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"):
            self.assertIsNone(support.family_of(high), high)   # o ruído alto é arquivo de apoio do LowNoise
        self.assertEqual(support.family_of(LOW_T)["video"]["image"], "ignored")
        self.assertEqual(support.family_of("Wan2.2-I2V-A14B-LowNoise-Q8_0.gguf")["video"]["image"], "required")

    def test_the_high_noise_model_is_downloaded_with_the_same_quantization(self):
        fam = support.family_of(LOW_T)
        spec = support.download_spec(fam, "high_noise_diffusion_model_path", LOW_T)
        self.assertEqual((spec["repo"], spec["file"]), ("QuantStack/Wan2.2-T2V-A14B-GGUF", "HighNoise/" + HIGH_T))
        spec = support.download_spec(support.family_of("Wan2.2-I2V-A14B-LowNoise-Q8_0.gguf"), "high_noise_diffusion_model_path", "Wan2.2-I2V-A14B-LowNoise-Q8_0.gguf")
        self.assertEqual((spec["repo"], spec["file"]), ("QuantStack/Wan2.2-I2V-A14B-GGUF", "HighNoise/Wan2.2-I2V-A14B-HighNoise-Q8_0.gguf"))

    def test_companions_are_planned_found_and_prefer_the_matching_quant(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / LOW_T).write_bytes(b"x")
            plan = support.plan(folder, LOW_T, "video")
            self.assertEqual({i["dest"] for i in plan["items"]}, {"wan_2.1_vae.safetensors", "umt5-xxl-encoder-Q4_K_M.gguf", HIGH_T})
            roles = {i["dest"]: i["role"] for i in plan["items"]}
            self.assertEqual(roles[HIGH_T], "model")
            for n in ("wan_2.1_vae.safetensors", "umt5-xxl-encoder-Q4_K_M.gguf", "Wan2.2-T2V-A14B-HighNoise-Q2_K.gguf", HIGH_T, "Wan2.2-I2V-A14B-HighNoise-Q4_K_M.gguf"):
                (folder / n).write_bytes(b"x")
            found = support.find_companions(folder, folder / LOW_T, support.family_of(LOW_T))
            self.assertEqual(found["high_noise_diffusion_model_path"], HIGH_T)   # mesma quantização, e não o I2V nem o Q2_K
            self.assertEqual(support.plan(folder, LOW_T, "video")["items"], [])
            (folder / "wan2.1-i2v-14b-480p-Q4_K_M.gguf").write_bytes(b"x")
            dest = {i["dest"] for i in support.plan(folder, "wan2.1-i2v-14b-480p-Q4_K_M.gguf", "video")["items"]}
            self.assertEqual(dest, {"clip_vision_h.safetensors"})   # VAE e UMT5 já estavam na pasta

    def test_support_files_do_not_show_up_as_models(self):
        from openflow.canvas import installed

        self.assertTrue(installed.SUPPORT_RE.search(HIGH_T))
        self.assertTrue(installed.SUPPORT_RE.search("clip_vision_h.safetensors"))
        self.assertFalse(installed.SUPPORT_RE.search(LOW_T))


class CliTests(unittest.TestCase):
    def test_sd_cli_gets_the_two_model_and_clip_vision_options(self):
        fam = support.family_of(LOW_T)
        load = {"diffusion_model_path": "/m/low.gguf", "high_noise_diffusion_model_path": "/m/high.gguf", "vae_path": "/m/vae.safetensors", "t5xxl_path": "/m/t5.gguf", "clip_vision_path": "/m/cv.safetensors"}
        args, warns = sdcli.build_args(Path("/x/sd-cli"), load, support.run_for(fam, LOW_T), prompt="ondas", width=832, height=480, seed=1, out=Path("/t/f_%05d.png"), video=True)
        pairs = {args[i]: args[i + 1] for i in range(len(args) - 1)}
        self.assertEqual((pairs["--high-noise-diffusion-model"], pairs["--clip_vision"], pairs["--high-noise-cfg-scale"], pairs["--high-noise-steps"], pairs["--high-noise-sampling-method"]),
                         ("/m/high.gguf", "/m/cv.safetensors", "3.5", "10", "euler"))
        self.assertEqual(warns, [])


class StartImageTests(unittest.TestCase):
    def prov(self):
        p = M.GGUFMedia.__new__(M.GGUFMedia)
        self.notes = []
        p.ctl = M.Ctl(note=self.notes.append)
        return p

    def test_i2v_needs_an_image_t2v_ignores_it_and_ti2v_takes_both(self):
        p = self.prov()
        img = (b"png", "image/png")
        with self.assertRaises(ProviderError) as cm:
            p._start_image(support.family_of("wan2.1-i2v-14b-480p-Q4_K_M.gguf")["video"], None)
        self.assertIn("Imagem inicial", str(cm.exception))
        self.assertEqual(p._start_image(support.family_of("wan2.1-i2v-14b-480p-Q4_K_M.gguf")["video"], img), img)
        self.assertIsNone(p._start_image(support.family_of(LOW_T)["video"], img))
        self.assertTrue(any("ignorada" in n for n in self.notes))
        self.assertEqual(p._start_image(support.family_of("Wan2.2-TI2V-5B-Q4_K_M.gguf")["video"], img), img)
        self.assertIsNone(p._start_image({}, None))


if __name__ == "__main__":
    unittest.main()
