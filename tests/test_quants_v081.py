"""v0.81: Q2, Q3, Q4, Q6 e Q8 para todos os modelos — escolher (lista GGUF com as cinco faixas, outros repositórios, precisão Q8…Q2 nos modelos originais), criar (uma faixa que falta, a partir de um GGUF baixado)
e usar (recomprimir ao carregar).

Nada real foi executado: o Hugging Face, o sd-cli, o llama.cpp, o diffusers, o optimum-quanto e o bitsandbytes são simulados (o que se prova é que o OpenFlow monta o pedido certo e trata os erros). Que a compressão
de verdade funcione e a qualidade de cada faixa NÃO foi verificado."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from openflow import hf
from openflow.canvas import localmodels as lm
from openflow.canvas import media as M
from openflow.canvas import quants as Q
from openflow.canvas import requant, sdcli
from openflow.providers import ProviderError
from tests.test_canvas import PNG, provider
from tests.test_lowmem_v072 import make_pipe, qwen_call
from tests.test_model_install_v078 import FILES, Case, fake_hub

GB = 1024 ** 3


def gf(*pairs):
    """Arquivos de um repositório GGUF: [(nome, GB)] → lista no formato do Hub."""
    return [{"name": n, "size": int(g * GB)} for n, g in pairs]


MODEL_FILES = gf(("m-Q2_K.gguf", 2), ("m-Q4_K_M.gguf", 4), ("m-Q4_0.gguf", 3.8), ("m-Q5_K_M.gguf", 5), ("m-Q8_0.gguf", 8), ("m-F16.gguf", 15), ("mmproj-F16.gguf", 1))


class PureTests(unittest.TestCase):
    def test_tier_of(self):
        got = {q: Q.tier_of(q) for q in ("Q4_K_M", "q4_k_m", "IQ3_XS", "UD-Q8_K_XL", "Q2_K", "Q6_K", "Q3_K_S", "Q5_K_M", "Q1_0", "F16", "BF16", "F32", "", "MXFP4")}
        self.assertEqual(got, {"Q4_K_M": "Q4", "q4_k_m": "Q4", "IQ3_XS": "Q3", "UD-Q8_K_XL": "Q8", "Q2_K": "Q2", "Q6_K": "Q6", "Q3_K_S": "Q3", "Q5_K_M": "", "Q1_0": "", "F16": "", "BF16": "", "F32": "", "": "", "MXFP4": ""})

    def test_pick_prefers_the_usual_name_and_then_the_smallest(self):
        files = hf.group_files(MODEL_FILES, 0)
        self.assertEqual(Q.pick(files, "Q4")["name"], "m-Q4_K_M.gguf")                     # Q4_K_M antes do Q4_0, mesmo o Q4_0 sendo menor
        self.assertEqual(Q.pick(files, "Q2")["name"], "m-Q2_K.gguf")
        self.assertIsNone(Q.pick(files, "Q3"))
        self.assertIsNone(Q.pick(files, "Q6"))

    def test_group_files_labels_the_tier(self):
        files = {f["name"]: f["tier"] for f in hf.group_files(MODEL_FILES, 0)}
        self.assertEqual(files, {"m-Q2_K.gguf": "Q2", "m-Q4_K_M.gguf": "Q4", "m-Q4_0.gguf": "Q4", "m-Q5_K_M.gguf": "", "m-Q8_0.gguf": "Q8", "m-F16.gguf": ""})

    def test_summary_shows_all_five_tiers_and_marks_the_missing(self):
        s = Q.summary(hf.group_files(MODEL_FILES, 0))
        self.assertEqual([(x["tier"], x["has"]) for x in s], [("Q2", True), ("Q3", False), ("Q4", True), ("Q6", False), ("Q8", True)])
        self.assertEqual([x["tier"] for x in s if x["recommended"]], ["Q4"])                  # sem saber a RAM: Q4

    def test_summary_recommends_the_best_tier_that_fits_the_ram(self):
        files = hf.group_files(MODEL_FILES, 0)
        self.assertEqual([x["tier"] for x in Q.summary(files, 16) if x["recommended"]], ["Q8"])   # 60 % de 16 GB = 9,6 GB: o Q8 (8 GB) cabe
        self.assertEqual([x["tier"] for x in Q.summary(files, 8) if x["recommended"]], ["Q4"])    # 4,8 GB: o Q4 (4 GB)
        self.assertEqual([x["tier"] for x in Q.summary(files, 2) if x["recommended"]], ["Q2"])    # nada cabe: o menor

    def test_original_models_recommend_a_tier_only_when_fp16_does_not_fit(self):
        self.assertEqual(Q.recommend_original(10 * GB, 32), "")
        self.assertEqual(Q.recommend_original(24 * GB, 16), "Q4")                              # 9,6 GB de limite: Q4 ≈ 6,9 GB (Q6 ≈ 9,9 GB não cabe)
        self.assertEqual(Q.recommend_original(24 * GB, 8), "Q2")
        self.assertEqual(Q.recommend_original(0, 8), "")
        self.assertEqual(Q.estimate(16 * GB, "Q8"), int(16 * GB * 8.5 / 16))

    def test_use_a_lower_tier_on_the_fly(self):
        load, note = Q.with_weight_type({"a": 1}, "Q8_0", "Q4")
        self.assertEqual(load, {"a": 1, "wtype": "q4_k"})
        self.assertIn("Comprimindo os pesos para Q4", note)
        self.assertEqual(Q.with_weight_type({"a": 1}, "F16", "Q2")[0]["wtype"], "q2_k")
        self.assertEqual(Q.with_weight_type({"a": 1}, "Q8_0", "Q8")[0]["a"], 1)
        same, note = Q.with_weight_type({"a": 1}, "Q4_K_M", "Q4")
        self.assertEqual((same, note), ({"a": 1}, ""))                                      # já é Q4: nada a fazer
        up, note = Q.with_weight_type({"a": 1}, "Q4_K_M", "Q8")
        self.assertNotIn("wtype", up)                                                       # subir de faixa não devolve qualidade
        self.assertIn("já é Q4", note)
        self.assertEqual(Q.with_weight_type({"a": 1}, "Q8_0", ""), ({"a": 1}, ""))
        self.assertEqual(Q.with_weight_type({}, "Q5_K_M", "Q4")[0]["wtype"], "q4_k")        # Q5 não é faixa, mas tem mais bits que o Q4

    def test_wanted_and_sd_cli_names(self):
        self.assertEqual([Q.wanted(v) for v in ("Q4", "q8", "Q4_K_M", "", None, "banana", "Q5")], ["Q4", "Q8", "Q4", "", "", "", ""])
        self.assertEqual([Q.sd_cli_type(v) for v in ("q4_k", "q2_k", "q8_0", "f16")], ["q4_K", "q2_K", "q8_0", "f16"])
        self.assertEqual(Q.SD_TYPE, {"Q2": "q2_K", "Q3": "q3_K", "Q4": "q4_K", "Q6": "q6_K", "Q8": "q8_0"})

    def test_target_name_swaps_the_quant_of_the_file(self):
        self.assertEqual(Q.target_name("flux1-dev-Q8_0.gguf", "Q4"), "flux1-dev-Q4_K.gguf")
        self.assertEqual(Q.target_name("Qwen3-8B-UD-Q8_K_XL.gguf", "Q2"), "Qwen3-8B-Q2_K.gguf")
        self.assertEqual(Q.target_name("model-F16.gguf", "Q6"), "model-Q6_K.gguf")
        self.assertEqual(Q.target_name("model.gguf", "Q3"), "model-Q3_K.gguf")
        self.assertEqual(Q.target_name("z_image_turbo-bf16.gguf", "Q8"), "z_image_turbo-Q8_0.gguf")

    def test_best_source_is_the_file_with_the_most_bits_above_the_tier(self):
        cands = [{"name": "a", "bits": 8, "size": 8, "parts": 1}, {"name": "b", "bits": 16, "size": 16, "parts": 1}, {"name": "c", "bits": 4, "size": 4, "parts": 1}, {"name": "d", "bits": 16, "size": 32, "parts": 3}]
        self.assertEqual(Q.best_source(cands, "Q4")["name"], "b")                           # F16 (e o dividido em partes não conta)
        self.assertEqual(Q.best_source([c for c in cands if c["name"] in "ac"], "Q4")["name"], "a")
        self.assertIsNone(Q.best_source([cands[2]], "Q4"))

    def test_original_format_has_only_8_4_and_2_bits(self):
        self.assertEqual({t: Q.original_bits(t) for t in Q.TIERS}, {"Q2": 2, "Q3": 4, "Q4": 4, "Q6": 8, "Q8": 8})
        self.assertIn("usa 8 bits", Q.original_note("Q6"))
        self.assertIn("usa 4 bits", Q.original_note("Q3"))
        self.assertEqual(Q.original_note("Q4"), "")

    def test_quantizable_picks_the_diffusion_model_and_text_encoders(self):
        comps = {"transformer": ["diffusers", "QwenImageTransformer2DModel"], "text_encoder": ["transformers", "Qwen2_5_VLForConditionalGeneration"], "vae": ["diffusers", "AutoencoderKLQwenImage"],
                 "scheduler": ["diffusers", "FlowMatchEulerDiscreteScheduler"], "tokenizer": ["transformers", "Qwen2Tokenizer"], "text_encoder_2": ["transformers", "T5EncoderModel"], "unet": ["diffusers", "UNet2DConditionModel"],
                 "_class_name": "X", "bad": "x"}
        self.assertEqual(Q.quantizable(comps), {"transformer": "diffusers", "text_encoder": "transformers", "text_encoder_2": "transformers", "unet": "diffusers"})

    def test_backend_choice(self):
        self.assertEqual(Q.backend_for(4, True, True, True), "bnb")
        self.assertEqual(Q.backend_for(8, True, True, False), "bnb")
        self.assertEqual(Q.backend_for(4, False, True, True), "quanto")                    # sem placa NVIDIA: quanto (roda na CPU)
        self.assertEqual(Q.backend_for(2, True, True, True), "quanto")                     # bitsandbytes não tem 2 bits
        self.assertEqual(Q.backend_for(2, True, True, False), "")
        self.assertEqual(Q.backend_for(8, False, False, False), "")

    def test_configs_for_each_backend(self):
        d = types.SimpleNamespace(BitsAndBytesConfig=lambda **k: ("bnb-d", k), QuantoConfig=lambda **k: ("quanto-d", k))
        tf = types.SimpleNamespace(BitsAndBytesConfig=lambda **k: ("bnb-t", k), QuantoConfig=lambda **k: ("quanto-t", k))
        self.assertEqual(Q.build_configs("quanto", 4, "bf16", d, tf), {"diffusers": ("quanto-d", {"weights_dtype": "int4"}), "transformers": ("quanto-t", {"weights": "int4"})})
        self.assertEqual(Q.build_configs("bnb", 4, "bf16", d, None), {"diffusers": ("bnb-d", {"load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": "bf16"})})
        self.assertEqual(Q.build_configs("bnb", 8, "bf16", d, tf)["transformers"], ("bnb-t", {"load_in_8bit": True}))
        self.assertEqual(Q.pipeline_mapping({"transformer": "diffusers", "text_encoder": "transformers"}, {"diffusers": 1}), {"transformer": 1})


class GgufRepoTests(unittest.TestCase):
    def test_base_name(self):
        self.assertEqual(hf.base_name("unsloth/Z-Image-Turbo-GGUF"), "Z-Image-Turbo")
        self.assertEqual(hf.base_name("city96/FLUX.1-dev-gguf"), "FLUX.1-dev")
        self.assertEqual(hf.base_name("a/Model"), "Model")

    def test_other_repos_with_the_missing_tiers(self):
        trees = {"x/Model-GGUF": gf(("Model-Q4_K_M.gguf", 4), ("Model-Q8_0.gguf", 8), ("Model-Q3_K_S.gguf", 3), ("Model-Q2_K.gguf", 2)),
                 "y/Model-quants": gf(("Model-Q4_K_M.gguf", 4)), "z/Other-GGUF": gf(("Other-Q2_K.gguf", 2)), "w/Model_GGUF": gf(("m-Q6_K.gguf", 6), ("m-Q2_K.gguf", 2))}

        def fake_search(q, token="", limit=20, kind="text"):
            return [{"id": "me/Model-GGUF", "downloads": 9}, {"id": "x/Model-GGUF", "downloads": 50}, {"id": "y/Model-quants", "downloads": 70}, {"id": "z/Other-GGUF", "downloads": 99}, {"id": "w/Model_GGUF", "downloads": 10}]

        with mock.patch.object(hf, "search", side_effect=fake_search), mock.patch.object(hf, "repo_files", side_effect=lambda repo, token="": trees[repo]):
            rows = hf.other_repos("me/Model-GGUF", "image", ["Q2", "Q3", "Q6"], "")
        self.assertEqual([r["repo"] for r in rows], ["x/Model-GGUF", "w/Model_GGUF"])           # y só tem Q4 e z é outro modelo; o próprio repositório fica de fora
        self.assertEqual(rows[0]["missing_covered"], ["Q2", "Q3"])
        self.assertEqual(rows[1]["missing_covered"], ["Q2", "Q6"])

    def test_other_repos_survive_a_network_failure(self):
        with mock.patch.object(hf, "search", side_effect=ProviderError("sem rede")):
            self.assertEqual(hf.other_repos("me/Model-GGUF", "image", ["Q2"], ""), [])
        with mock.patch.object(hf, "search", return_value=[{"id": "x/Model-GGUF", "downloads": 1}]), mock.patch.object(hf, "repo_files", side_effect=ProviderError("x")):
            self.assertEqual(hf.other_repos("me/Model-GGUF", "image", ["Q2"], ""), [])


class OriginalPrecisionTests(Case):
    def test_the_tiers_are_valid_precisions_that_download_the_fp16_files(self):
        for q in ("q8", "q6", "q4", "q3", "q2"):
            self.assertIn(q, lm.PRECISIONS)
            self.assertTrue(lm.is_quant(q))
        self.assertFalse(lm.is_quant("fp16"))
        files = [{"name": "model_index.json", "size": 10}, {"name": "transformer/diffusion_pytorch_model.safetensors", "size": 4 * GB}, {"name": "transformer/diffusion_pytorch_model.fp16.safetensors", "size": 2 * GB}]
        self.assertEqual([f["name"] for f in lm.select_files(files, "q4")], [f["name"] for f in lm.select_files(files, "fp16")])
        self.assertIn("transformer/diffusion_pytorch_model.fp16.safetensors", [f["name"] for f in lm.select_files(files, "q2")])

    def test_download_registers_the_tier_and_it_is_read_back(self):
        hub = fake_hub(self.cache)
        with mock.patch.object(lm, "_hub", return_value=hub), mock.patch.object(lm.shutil, "disk_usage", return_value=types.SimpleNamespace(free=100 * GB)):
            snap = lm.download("acme/tiny-model", "q4", "", None, lambda: False)
        self.assertEqual((snap / lm.MARKER).read_text(), "q4")
        with mock.patch.object(lm, "_snapshot", return_value=snap):
            self.assertEqual(lm.downloaded_precision("acme/tiny-model"), "q4")
        self.assertEqual(lm.tier_of_precision("q4"), "Q4")
        self.assertEqual(lm.tier_of_precision("fp16"), "")

    def test_options_list_the_tiers_with_the_memory_they_need(self):
        files = [{"name": "model_index.json", "size": 10}, {"name": "transformer/m.safetensors", "size": 24 * GB}, {"name": "transformer/m.fp16.safetensors", "size": 12 * GB}]
        with mock.patch.object(lm, "_siblings", return_value=files):
            o = lm.options("a/b", "", gpu=False, ram_gb=0)
            self.assertEqual([x["id"] for x in o["options"]], ["fp32", "fp16", "bf16", "q8", "q6", "q4", "q3", "q2"])
            q4 = next(x for x in o["options"] if x["id"] == "q4")
            self.assertEqual(q4["size"], next(x for x in o["options"] if x["id"] == "fp16")["size"])      # o download é o do fp16…
            self.assertAlmostEqual(q4["memory"] / (12 * GB), 4.6 / 16, places=2)                              # …e a memória cai
            self.assertEqual(o["recommended"], "fp32")
            self.assertEqual(lm.options("a/b", "", gpu=True, ram_gb=64)["recommended"], "fp16")             # a RAM dá: igual a antes
            self.assertEqual(lm.options("a/b", "", gpu=False, ram_gb=8)["recommended"], "q4")               # 12 GB de fp16 não cabem em 8 GB (limite de 4,8 GB): Q6 ≈ 4,95 GB não cabe, Q4 ≈ 3,5 GB sim

    def test_torch_dtype_of_a_tier(self):
        torch = types.SimpleNamespace(float32="f32", float16="f16", bfloat16="bf16")
        with mock.patch.dict(sys.modules, {"torch": torch}):
            self.assertEqual([lm.torch_dtype(p) for p in ("fp32", "fp16", "q4", "q2")], ["f32", "f16", "bf16", "bf16"])

    def test_the_components_come_from_model_index(self):
        snap = Path(tempfile.mkdtemp())
        (snap / "model_index.json").write_text(json.dumps({"_class_name": "P", "transformer": ["diffusers", "FluxTransformer2DModel"], "vae": ["diffusers", "AutoencoderKL"]}), encoding="utf-8")
        with mock.patch.object(lm, "_snapshot", return_value=snap):
            self.assertEqual(set(lm.components("a/b")), {"transformer", "vae"})
        with mock.patch.object(lm, "_snapshot", return_value=None):
            self.assertEqual(lm.components("a/b"), {})


class LoadQuantizedTests(unittest.TestCase):
    """Carregar um modelo baixado numa faixa: o diffusers recebe a configuração de compressão."""
    COMPS = {"transformer": ["diffusers", "QwenImageTransformer2DModel"], "text_encoder": ["transformers", "Qwen2_5_VLForConditionalGeneration"], "vae": ["diffusers", "AutoencoderKL"]}

    def setUp(self):
        M._LOCAL_CACHE.clear()
        torch = mock.MagicMock()
        torch.cuda.is_available.return_value = False
        torch.backends.mps = None
        torch.Generator.return_value.manual_seed.return_value = "gen"
        self.diffusers = mock.MagicMock()
        self.diffusers.QuantoConfig.side_effect = lambda **k: ("diffusers-quanto", k)
        self.diffusers.BitsAndBytesConfig.side_effect = lambda **k: ("diffusers-bnb", k)
        self.diffusers.PipelineQuantizationConfig.side_effect = lambda **k: ("pipeline-config", k)
        self.tf = types.SimpleNamespace(QuantoConfig=lambda **k: ("tf-quanto", k), BitsAndBytesConfig=lambda **k: ("tf-bnb", k))
        self.mods = {"torch": torch, "diffusers": self.diffusers, "transformers": self.tf}
        self.notes, self.loaded = [], []

    def generate(self, precision, libs=("optimum.quanto",), comps=None, model="Qwen/Qwen-Image"):
        pipe = make_pipe("QwenImagePipeline", qwen_call)

        def from_pretrained(m, **k):
            self.loaded.append(k)
            return pipe()
        self.diffusers.AutoPipelineForText2Image.from_pretrained.side_effect = from_pretrained
        with mock.patch.dict(sys.modules, self.mods), mock.patch.object(lm, "downloaded_precision", return_value=precision), mock.patch.object(lm, "has_fp16_variant", return_value=False), \
                mock.patch.object(lm, "components", return_value=self.COMPS if comps is None else comps), mock.patch("importlib.util.find_spec", side_effect=lambda n, *a: object() if n in libs else None):
            M._LOCAL_CACHE.clear()
            p = provider("local_hf", "", {"image": model}, key="", needs_key=False)
            p.ctl = types.SimpleNamespace(note=self.notes.append, check=lambda: None)
            return p.image("um gato", size="512x512")

    def test_a_tier_compresses_the_diffusion_model_and_the_text_encoder_with_quanto(self):
        self.generate("q4")
        cfg = self.loaded[0]["quantization_config"]
        self.assertEqual(cfg[0], "pipeline-config")
        self.assertEqual(cfg[1]["quant_mapping"], {"transformer": ("diffusers-quanto", {"weights_dtype": "int4"}), "text_encoder": ("tf-quanto", {"weights": "int4"})})   # o VAE fica de fora
        self.assertTrue(any("Comprimindo para Q4 (4 bits, optimum-quanto)" in n for n in self.notes), self.notes)

    def test_q2_is_2_bits_and_q6_is_8_with_a_note(self):
        self.generate("q2")
        self.assertEqual(self.loaded[-1]["quantization_config"][1]["quant_mapping"]["transformer"][1], {"weights_dtype": "int2"})
        self.notes.clear()
        self.generate("q6")
        self.assertEqual(self.loaded[-1]["quantization_config"][1]["quant_mapping"]["transformer"][1], {"weights_dtype": "int8"})
        self.assertTrue(any("Q6 no formato original usa 8 bits" in n for n in self.notes), self.notes)

    def test_without_a_tier_nothing_is_compressed(self):
        self.generate("fp16")
        self.assertNotIn("quantization_config", self.loaded[0])

    def test_without_a_compression_library_the_error_says_which_to_install(self):
        with self.assertRaises(ProviderError) as cm:
            self.generate("q4", libs=())
        self.assertIn("optimum-quanto", str(cm.exception))
        self.assertIn("faixa Q4", str(cm.exception))
        self.assertEqual(self.loaded, [])

    def test_a_pipeline_without_compressible_parts_loads_as_is_with_a_note(self):
        self.generate("q8", comps={"vae": ["diffusers", "AutoencoderKL"]})
        self.assertNotIn("quantization_config", self.loaded[0])
        self.assertTrue(any("não tem um componente que dê para comprimir" in n for n in self.notes), self.notes)

    def test_models_that_cannot_be_compressed_say_so(self):
        notes = []
        with mock.patch.object(lm, "downloaded_precision", return_value="q4"), mock.patch.object(lm, "has_fp16_variant", return_value=False), mock.patch.dict(sys.modules, self.mods):
            p = provider("local_hf", "", {"voice": "x/y"}, key="", needs_key=False)
            p.ctl = types.SimpleNamespace(note=notes.append, check=lambda: None)
            M.LocalHFMedia._ready(p, "x/y")
            M.LocalHFMedia._ready(p, "x/y", quantizes=True)
        self.assertEqual(sum("só comprime modelos de imagem e vídeo" in n for n in notes), 1)      # só a chamada sem `quantizes`

    def test_without_transformers_only_the_diffusion_model_is_compressed(self):
        self.mods = dict(self.mods)
        self.mods["transformers"] = None
        self.generate("q8")
        self.assertEqual(set(self.loaded[0]["quantization_config"][1]["quant_mapping"]), {"transformer"})


class GgufUseTests(unittest.TestCase):
    """Usar um arquivo GGUF numa faixa menor (campo «quant» do nó)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "image").mkdir()
        M._LOCAL_CACHE.clear()
        self.loads = []
        outer = self

        class Img:
            def save(self, buf, format="PNG"):
                buf.write(PNG)

        class StableDiffusion:
            def __init__(self, **kw):
                outer.loads.append(kw)

            def generate_image(self, prompt="", **kw):
                return [Img()]
        mod = mock.MagicMock(StableDiffusion=StableDiffusion)
        p = mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False)
        q.start()
        self.addCleanup(q.stop)
        self.notes = []

    def gen(self, name, quant):
        (self.tmp / "image" / name).write_bytes(b"gguf")
        M._LOCAL_CACHE.clear()
        p = M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {"image": name}, "needs_key": False})
        p.ctl = types.SimpleNamespace(note=self.notes.append, check=lambda: None)
        return p.image("um gato", size="512x512", extra={"load": {"model_path": "@model"}, **({"quant": quant} if quant else {})})

    def test_a_lower_tier_is_requested_from_the_library(self):
        self.gen("sdxl-Q8_0.gguf", "Q4")
        self.assertEqual(self.loads[0]["wtype"], "q4_k")
        self.assertTrue(any("Comprimindo os pesos para Q4" in n for n in self.notes), self.notes)

    def test_no_tier_or_a_higher_one_leaves_the_file_as_it_is(self):
        self.gen("sdxl-Q8_0.gguf", "")
        self.assertNotIn("wtype", self.loads[0])
        self.loads.clear()
        self.gen("sdxl-Q4_K_M.gguf", "Q8")
        self.assertNotIn("wtype", self.loads[0])
        self.assertTrue(any("já é Q4" in n for n in self.notes), self.notes)

    def test_a_wrong_value_is_ignored_with_a_note(self):
        self.gen("sdxl-Q8_0.gguf", "banana")
        self.assertNotIn("wtype", self.loads[0])
        self.assertTrue(any("não é uma faixa conhecida" in n for n in self.notes), self.notes)

    def test_the_tier_is_not_passed_to_the_generation(self):
        # «quant» não pode chegar à geração como um argumento (a biblioteca recusaria): o `generate_image` simulado aceita qualquer coisa, então confere pelo carregamento
        self.gen("sdxl-Q8_0.gguf", "Q2")
        self.assertNotIn("quant", self.loads[0])

    def test_the_sd_cli_gets_the_type_with_its_own_spelling(self):
        args, warns = sdcli.build_args(Path("/x/sd-cli"), {"diffusion_model_path": "/m/a.gguf", "wtype": "q4_k"}, {}, prompt="p", width=512, height=512, seed=1, out=Path("/o.png"))
        self.assertEqual(args[args.index("--type") + 1], "q4_K")
        self.assertEqual(warns, [])


class RequantTests(unittest.TestCase):
    def setUp(self):
        self.models = Path(tempfile.mkdtemp())
        (self.models / "image").mkdir()
        self.exe = self.models / "sd-cli"
        self.exe.write_bytes(b"x")

    def model(self, name, kind="image", size=2048):
        folder = self.models / kind if kind != "text" else self.models
        (folder / name).write_bytes(b"G" * size)
        return folder / name

    def test_plan(self):
        self.model("flux-Q8_0.gguf")
        pl = requant.plan(self.models, "image", "flux-Q8_0.gguf", "Q4")
        self.assertEqual(pl["dst"].name, "flux-Q4_K.gguf")
        self.assertEqual(pl["from"], "Q8_0")
        self.assertGreater(pl["estimate"], 0)

    def test_plan_refuses_what_makes_no_sense(self):
        self.model("flux-Q4_K_M.gguf")
        self.model("flux-Q8_0.gguf")
        self.model("flux-Q4_K.gguf")
        self.model("big-Q8_0-00001-of-00002.gguf")
        self.model("nobits.gguf")
        cases = [("image", "flux-Q4_K_M.gguf", "Q4", "já é Q4_K_M"), ("image", "flux-Q4_K_M.gguf", "Q8", "MENOS bits"), ("image", "flux-Q8_0.gguf", "Q4", "já existe"),
                 ("image", "big-Q8_0-00001-of-00002.gguf", "Q4", "dividido em partes"), ("image", "nobits.gguf", "Q4", "quantização deste arquivo"),
                 ("image", "ghost-Q8_0.gguf", "Q4", "não foi baixado"), ("image", "flux-Q8_0.gguf", "Q5", "Q2, Q3, Q4, Q6 ou Q8"), ("audio", "x.gguf", "Q4", "texto, imagem e vídeo")]
        for kind, name, tier, msg in cases:
            with self.assertRaises(ProviderError, msg=(name, tier)) as cm:
                requant.plan(self.models, kind, name, tier)
            self.assertIn(msg, str(cm.exception), (name, tier))

    def test_the_sd_cli_creates_the_file_in_the_final_name_only_when_complete(self):
        self.model("flux-Q8_0.gguf")
        seen = {}

        def fake_run(args, exe, cancelled, note, timeout=0):
            seen["args"] = list(args)
            out = Path(args[args.index("-o") + 1])
            seen["tmp"] = out.name
            out.write_bytes(b"Q" * 4096)
            note("Etapa 1/1")
            return ""
        notes = []
        with mock.patch.object(sdcli, "find", return_value=self.exe), mock.patch.object(sdcli, "run", side_effect=fake_run):
            path = requant.create(self.models, "image", "flux-Q8_0.gguf", "Q4", lambda: False, notes.append)
        self.assertEqual(path.name, "flux-Q4_K.gguf")
        self.assertTrue(path.is_file())
        self.assertEqual(seen["tmp"], "flux-Q4_K.converting.gguf")                          # nunca aparece pela metade com o nome final
        self.assertEqual(seen["args"][1:4], ["-M", "convert", "-m"])
        self.assertEqual(seen["args"][seen["args"].index("--type") + 1], "q4_K")
        self.assertFalse(list((self.models / "image").glob("*.converting.gguf")))
        self.assertTrue(any("Criando flux-Q4_K.gguf" in n for n in notes), notes)
        self.assertEqual(hf.local_models(self.models, "image")[0]["tier"] in ("Q4", "Q8"), True)

    def test_a_failed_conversion_leaves_nothing_behind(self):
        self.model("flux-Q8_0.gguf")

        def boom(args, exe, cancelled, note, timeout=0):
            Path(args[args.index("-o") + 1]).write_bytes(b"half")
            raise ProviderError("O sd-cli falhou (código 1): [E] x")
        with mock.patch.object(sdcli, "find", return_value=self.exe), mock.patch.object(sdcli, "run", side_effect=boom):
            with self.assertRaises(ProviderError):
                requant.create(self.models, "image", "flux-Q8_0.gguf", "Q4")
        self.assertEqual(sorted(p.name for p in (self.models / "image").glob("*.gguf")), ["flux-Q8_0.gguf"])

    def test_without_sd_cli_the_error_says_what_to_do(self):
        self.model("flux-Q8_0.gguf")
        with mock.patch.object(sdcli, "find", return_value=None):
            with self.assertRaises(ProviderError) as cm:
                requant.create(self.models, "image", "flux-Q8_0.gguf", "Q4")
        self.assertIn("sd-cli", str(cm.exception))

    def test_no_space_is_explained_before_starting(self):
        self.model("flux-Q8_0.gguf", size=10 * 1024 * 1024)
        with mock.patch.object(sdcli, "find", return_value=self.exe), mock.patch.object(requant.shutil, "disk_usage", return_value=types.SimpleNamespace(free=10)):
            with self.assertRaises(ProviderError) as cm:
                requant.create(self.models, "image", "flux-Q8_0.gguf", "Q4")
        self.assertIn("Sem espaço em disco", str(cm.exception))

    def test_text_models_are_quantized_by_llama_cpp_in_another_process(self):
        self.model("qwen-Q8_0.gguf", kind="text")
        runs = []

        class P:
            returncode = 0
            stdout = None

            def poll(self):
                return 0

            def wait(self):
                return 0

            def kill(self):
                pass

        def popen(cmd, **kw):
            runs.append(cmd)
            Path(cmd[4]).write_bytes(b"T" * 4096)
            return P()
        with mock.patch.object(requant.subprocess, "Popen", side_effect=popen):
            path = requant.create(self.models, "text", "qwen-Q8_0.gguf", "Q3")
        self.assertEqual(path.name, "qwen-Q3_K.gguf")
        self.assertEqual(runs[0][1], "-c")
        self.assertEqual(runs[0][-1], "12")                                                  # LLAMA_FTYPE_MOSTLY_Q3_K_M
        self.assertIn("llama_model_quantize", runs[0][2])
        self.assertIn("allow_requantize", runs[0][2])

    def test_cancel(self):
        self.model("flux-Q8_0.gguf")

        def cancelled_run(args, exe, cancelled, note, timeout=0):
            Path(args[args.index("-o") + 1]).write_bytes(b"part")
            raise ProviderError("cancelado")
        with mock.patch.object(sdcli, "find", return_value=self.exe), mock.patch.object(sdcli, "run", side_effect=cancelled_run):
            with self.assertRaises(ProviderError):
                requant.create(self.models, "image", "flux-Q8_0.gguf", "Q2")
        self.assertEqual([p.name for p in (self.models / "image").glob("*.gguf")], ["flux-Q8_0.gguf"])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import threading

        from openflow.server import make_server
        from openflow.storage import Store

        cls.store = Store(Path(tempfile.mkdtemp()))
        cls.httpd, _ = make_server("127.0.0.1", 0, cls.store)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, method, path, body=None):
        import urllib.error
        import urllib.request

        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_files_endpoint_carries_the_five_tiers(self):
        with mock.patch.object(hf, "repo_files", return_value=MODEL_FILES):
            code, data = self.call("GET", "/api/hf/files?repo=a/b-GGUF&kind=image")
        self.assertEqual(code, 200)
        self.assertEqual([(t["tier"], t["has"]) for t in data["tiers"]], [("Q2", True), ("Q3", False), ("Q4", True), ("Q6", False), ("Q8", True)])
        self.assertIn("tier", data["files"][0])

    def test_tiers_endpoint_with_and_without_alternatives(self):
        alt = [{"repo": "x/b-GGUF", "downloads": 5, "tiers": ["Q3"], "missing_covered": ["Q3"]}]
        with mock.patch.object(hf, "repo_files", return_value=MODEL_FILES), mock.patch.object(hf, "other_repos", return_value=alt) as other:
            code, data = self.call("GET", "/api/hf/tiers?repo=a/b-GGUF&kind=image")
            self.assertEqual((code, data["alternatives"]), (200, []))
            other.assert_not_called()
            code, data = self.call("GET", "/api/hf/tiers?repo=a/b-GGUF&kind=image&alts=1")
            self.assertEqual(data["alternatives"], alt)
            self.assertEqual(other.call_args[0][2], ["Q3", "Q6"])                              # procura só o que falta
        self.assertEqual(self.call("GET", "/api/hf/tiers?repo=..&kind=image")[0], 400)
        self.assertEqual(self.call("GET", "/api/hf/tiers?repo=a/b&kind=nada")[0], 400)

    def test_requant_endpoint_validates_before_starting(self):
        (self.store.models_dir / "image").mkdir(parents=True, exist_ok=True)
        (self.store.models_dir / "image" / "m-Q4_K_M.gguf").write_bytes(b"g" * 2048)
        code, data = self.call("POST", "/api/hf/requant", {"kind": "image", "name": "m-Q4_K_M.gguf", "tier": "Q8"})
        self.assertEqual(code, 400)
        self.assertIn("MENOS bits", data["error"])
        self.assertEqual(self.call("POST", "/api/hf/requant", {"kind": "image", "name": "nao-existe-Q8_0.gguf", "tier": "Q4"})[0], 400)
        self.assertEqual(self.call("POST", "/api/hf/requant", {"kind": "image", "name": "m-Q4_K_M.gguf", "tier": "Q7"})[0], 400)

    def test_requant_endpoint_runs_a_job(self):
        (self.store.models_dir / "video").mkdir(parents=True, exist_ok=True)
        (self.store.models_dir / "video" / "wan-Q8_0.gguf").write_bytes(b"g" * 2048)

        def fake_create(models_dir, kind, name, tier, cancelled, note):
            note("fazendo")
            return models_dir / kind / "wan-Q4_K.gguf"
        with mock.patch.object(requant, "create", side_effect=fake_create):
            code, data = self.call("POST", "/api/hf/requant", {"kind": "video", "name": "wan-Q8_0.gguf", "tier": "q4"})
            self.assertEqual(code, 200)
            import time
            for _ in range(50):
                job = self.call("GET", "/api/jobs/" + data["job_id"])
                if job[1].get("status") in ("done", "error"):
                    break
                time.sleep(0.1)
        self.assertEqual(job[1].get("status"), "done", job)

    def test_library_models_carry_bits_and_tier(self):
        (self.store.models_dir / "image").mkdir(parents=True, exist_ok=True)
        (self.store.models_dir / "image" / "lib-Q6_K.gguf").write_bytes(b"g" * 2048)
        code, data = self.call("GET", "/api/library/items?scope=models")
        self.assertEqual(code, 200)
        m = next(i for i in data["items"] if i["name"] == "lib-Q6_K.gguf")
        self.assertEqual((m["bits"], m["tier"]), (6, "Q6"))


if __name__ == "__main__":
    unittest.main()
