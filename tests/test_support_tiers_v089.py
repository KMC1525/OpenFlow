"""v0.89 — faixas Q2/Q3/Q4/Q6/Q8 dos codificadores de texto e VAEs: achar, obter (baixar a pronta ou criar), usar no nó, API, terminal.
Tudo com sd-cli, llama.cpp e Hugging Face SIMULADOS: prova que o OpenFlow monta o pedido certo; que os programas reais comprimam bem NÃO foi verificado."""
import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from openflow import hf
from openflow.canvas import media as M
from openflow.canvas import quants, requant, support, support_tiers as T
from openflow.providers import ProviderError
from tests.helpers import ServerCase
from tests.test_gguf_matrix_v075 import FakeSD


def touch(folder, name, size=2048):
    Path(folder, name).write_bytes(b"x" * size)


class NamesTests(unittest.TestCase):
    def test_stem_ignores_the_tier_and_the_precision(self):
        self.assertEqual(T.stem("Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf"), T.stem("Qwen3-VL-8B-Instruct-Q8_0.gguf"))
        self.assertEqual(T.stem("t5xxl_fp8_e4m3fn.safetensors"), T.stem("t5xxl_fp8_e4m3fn-Q4_K.gguf"))
        self.assertEqual(T.stem("flux2-vae-bf16.safetensors"), "flux2-vae")
        self.assertNotEqual(T.stem("ae.safetensors"), T.stem("clip_l.safetensors"))

    def test_bits_and_target_names(self):
        self.assertEqual((T.bits_of("x-Q8_0.gguf"), T.bits_of("x_fp8_e4m3fn.safetensors"), T.bits_of("clip_l.safetensors"), T.bits_of("a-BF16.gguf")), (8, 8, 16, 16))
        self.assertEqual(T.target_name("t5xxl_fp8_e4m3fn.safetensors", "Q4"), "t5xxl_fp8_e4m3fn-Q4_K.gguf")
        self.assertEqual(T.target_name("qwen3-8b-Q8_0.gguf", "Q2"), "qwen3-8b-Q2_K.gguf")

    def test_which_files_are_encoders_or_vaes(self):
        key = T.companion_key
        self.assertEqual((key("ae.safetensors"), key("clip_l.safetensors"), key("t5xxl_fp8_e4m3fn.safetensors"), key("Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf")), ("vae_path", "clip_l_path", "t5xxl_path", "llm_path"))
        self.assertEqual(key("ae-Q4_K.gguf"), "vae_path")   # a faixa criada continua sendo «o mesmo VAE»
        for n in ("flux1-dev-Q4_K_S.gguf", "mmproj-F16.gguf", "minimax_h3_audio_vae_fp32.safetensors", "clip_vision_h.safetensors", "x.part"):
            self.assertEqual(key(n), "", n)

    def test_tools(self):
        self.assertEqual((T.tool_for("Qwen3-4B-Q4_K_M.gguf"), T.tool_for("t5xxl_fp8_e4m3fn.safetensors"), T.tool_for("umt5-xxl-encoder-Q8_0.gguf"), T.tool_for("ae.safetensors")), ("llama", "sdcli", "sdcli", "sdcli"))


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_present_and_lower(self):
        for n in ("t5xxl_fp8_e4m3fn.safetensors", "t5xxl_fp8_e4m3fn-Q4_K.gguf", "t5xxl_fp8_e4m3fn-Q2_K.gguf", "clip_l.safetensors"):
            touch(self.tmp, n)
        have = T.present(self.tmp, "t5xxl_fp8_e4m3fn.safetensors")
        self.assertEqual(sorted(have), ["Q2", "Q4"])
        self.assertEqual(have["Q4"]["name"], "t5xxl_fp8_e4m3fn-Q4_K.gguf")
        self.assertEqual([v["name"] for v in T.variants(self.tmp, "t5xxl_fp8_e4m3fn-Q2_K.gguf")][:1], ["t5xxl_fp8_e4m3fn.safetensors"])   # do que tem mais bits para o que tem menos

    def test_swap_tier_uses_the_installed_tier_and_says_what_is_missing(self):
        for n in ("ae.safetensors", "ae-Q8_0.gguf", "t5xxl_fp8_e4m3fn.safetensors"):
            touch(self.tmp, n)
        load = {"diffusion_model_path": "@model", "vae_path": "ae.safetensors", "t5xxl_path": "t5xxl_fp8_e4m3fn.safetensors", "wtype": None}
        out, notes = T.swap_tier(self.tmp, load, "Q8")
        self.assertEqual(out["vae_path"], "ae-Q8_0.gguf")
        self.assertEqual(out["t5xxl_path"], "t5xxl_fp8_e4m3fn.safetensors")   # sem Q8 do t5xxl: fica como está…
        self.assertEqual(len(notes), 1)
        self.assertIn("Q8", notes[0])
        self.assertIn("Codificador de texto", notes[0])   # …e o aviso diz qual e como instalar
        self.assertEqual(T.swap_tier(self.tmp, load, ""), (load, []))

    def test_the_auto_choice_never_picks_a_low_tier_by_alphabet(self):
        fam = support.family_of("flux1-dev-Q4_K_S.gguf")
        for n in ("flux1-dev-Q4_K_S.gguf", "ae.safetensors", "ae-Q2_K.gguf", "ae-Q8_0.gguf", "clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors", "t5xxl_fp8_e4m3fn-Q2_K.gguf"):
            touch(self.tmp, n)
        found = support.find_companions(self.tmp, self.tmp / "flux1-dev-Q4_K_S.gguf", fam)
        self.assertEqual(found["vae_path"], "ae.safetensors")                  # o padrão da família, não a «ae-Q2_K.gguf» que vem antes no alfabeto
        self.assertEqual(found["t5xxl_path"], "t5xxl_fp8_e4m3fn.safetensors")
        (self.tmp / "ae.safetensors").unlink()
        self.assertEqual(support.find_companions(self.tmp, self.tmp / "flux1-dev-Q4_K_S.gguf", fam)["vae_path"], "ae-Q8_0.gguf")   # sem o original: a de mais qualidade
        (self.tmp / "ae-Q8_0.gguf").unlink()
        self.assertEqual(support.find_companions(self.tmp, self.tmp / "flux1-dev-Q4_K_S.gguf", fam)["vae_path"], "ae-Q2_K.gguf")   # só a Q2: ela mesma


class CreateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "image").mkdir()
        self.f = self.tmp / "image"
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.notes = []

    def run_create(self, name, tier, size=4 * 1024 * 1024):
        touch(self.f, name, size)
        calls = {}

        def fake_sdcli(exe, src, tmp, tier_, cancelled, note):
            calls["sdcli"] = (src.name, tier_)
            tmp.write_bytes(b"y" * (size // 4))

        def fake_llama(src, tmp, tier_, cancelled, note):
            calls["llama"] = (src.name, tier_)
            tmp.write_bytes(b"y" * (size // 4))

        with mock.patch.object(requant.sdcli, "find", return_value=Path("/x/sd-cli")), mock.patch.object(requant, "convert_sdcli", fake_sdcli), mock.patch.object(requant, "convert_llama", fake_llama), \
                mock.patch.object(requant, "_need_space", lambda *a: None):
            path = requant.create(self.tmp, "image", name, tier, lambda: False, self.notes.append)
        return path, calls

    def test_a_safetensors_t5_is_converted_by_the_sd_cli(self):
        path, calls = self.run_create("t5xxl_fp8_e4m3fn.safetensors" if False else "clip_l.safetensors", "Q4")
        self.assertEqual(path.name, "clip_l-Q4_K.gguf")
        self.assertEqual(calls, {"sdcli": ("clip_l.safetensors", "Q4")})
        self.assertTrue(any("MB" in n for n in self.notes))

    def test_an_llm_encoder_in_the_image_folder_goes_to_llama_not_to_the_sd_cli(self):
        path, calls = self.run_create("Qwen3-VL-8B-Instruct-Q8_0.gguf", "Q3")
        self.assertEqual(calls, {"llama": ("Qwen3-VL-8B-Instruct-Q8_0.gguf", "Q3")})
        self.assertEqual(path.name, "Qwen3-VL-8B-Instruct-Q3_K.gguf")

    def test_a_vae_that_barely_shrinks_is_reported(self):
        touch(self.f, "ae.safetensors", 4 * 1024 * 1024)

        def fake(exe, src, tmp, tier_, cancelled, note):
            tmp.write_bytes(b"y" * (4 * 1024 * 1024 - 1000))   # quase não encolheu

        with mock.patch.object(requant.sdcli, "find", return_value=Path("/x/sd-cli")), mock.patch.object(requant, "convert_sdcli", fake), mock.patch.object(requant, "_need_space", lambda *a: None):
            requant.create(self.tmp, "image", "ae.safetensors", "Q8", lambda: False, self.notes.append)
        self.assertTrue(any("mal encolheu" in n for n in self.notes), self.notes)

    def test_refuses_a_tier_that_is_not_smaller(self):
        touch(self.f, "clip_l-Q4_K.gguf")
        with self.assertRaises(ProviderError) as cm:
            requant.plan(self.tmp, "image", "clip_l-Q4_K.gguf", "Q6")
        self.assertIn("MENOS bits", str(cm.exception))

    def test_a_plain_diffusion_gguf_still_uses_the_old_path(self):
        touch(self.f, "flux1-dev-Q8_0.gguf")
        pl = requant.plan(self.tmp, "image", "flux1-dev-Q8_0.gguf", "Q4")
        self.assertNotIn("tool", pl)
        self.assertEqual(pl["dst"].name, "flux1-dev-Q4_K.gguf")


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "image").mkdir()
        self.f = self.tmp / "image"
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def files_of(self, names):
        return [{"name": n, "size": 1_000_000} for n in names]

    def test_repo_option_for_an_llm_picks_the_file_of_the_tier(self):
        names = ["Qwen3-8B-Q2_K.gguf", "Qwen3-8B-Q3_K_M.gguf", "Qwen3-8B-Q4_K_M.gguf", "Qwen3-8B-Q6_K.gguf", "Qwen3-8B-Q8_0.gguf", "README.md"]
        with mock.patch.object(hf, "repo_files", return_value=self.files_of(names)):
            got = T.repo_option("Qwen3-8B-Q4_K_M.gguf", "Q2")
        self.assertEqual((got["repo"], got["file"]), ("unsloth/Qwen3-8B-GGUF", "Qwen3-8B-Q2_K.gguf"))

    def test_repo_option_for_a_safetensors_t5_uses_the_known_gguf_repo(self):
        with mock.patch.object(hf, "repo_files", return_value=self.files_of(["t5-v1_1-xxl-encoder-Q4_K_M.gguf", "t5-v1_1-xxl-encoder-Q8_0.gguf"])) as rf:
            got = T.repo_option("t5xxl_fp8_e4m3fn.safetensors", "Q8")
        self.assertEqual((rf.call_args[0][0], got["file"]), ("city96/t5-v1_1-xxl-encoder-gguf", "t5-v1_1-xxl-encoder-Q8_0.gguf"))

    def test_there_is_no_ready_tier_for_a_vae(self):
        with mock.patch.object(hf, "repo_files", side_effect=AssertionError("não devia consultar a rede")):
            self.assertIsNone(T.repo_option("ae.safetensors", "Q4"))

    def test_the_downloaded_tier_keeps_the_stem_of_the_file_you_have(self):
        self.assertEqual(T.dest_name_for("t5xxl_fp8_e4m3fn.safetensors", "t5-v1_1-xxl-encoder-Q4_K_M.gguf", "Q4_K_M"), "t5xxl_fp8_e4m3fn-Q4_K_M.gguf")
        self.assertEqual(T.dest_name_for("Qwen3-8B-Q8_0.gguf", "Qwen3-8B-Q2_K.gguf", "Q2_K"), "Qwen3-8B-Q2_K.gguf")

    def test_auto_downloads_when_the_repo_has_it_and_creates_when_it_does_not(self):
        touch(self.f, "t5xxl_fp8_e4m3fn.safetensors", 8192)
        got = {}

        def fake_download(repo, filename, folder, token, progress, cancelled, any_file=False, dest_name="", connections=0):
            got["dl"] = (repo, filename, dest_name)
            Path(folder, dest_name).write_bytes(b"z" * 100)
            return Path(folder, dest_name)

        with mock.patch.object(T, "repo_option", return_value={"repo": "city96/t5-v1_1-xxl-encoder-gguf", "file": "t5-v1_1-xxl-encoder-Q4_K_M.gguf", "size": 1000}), mock.patch.object(hf, "download", fake_download):
            res = T.install_tier(self.tmp, "image", "t5xxl_fp8_e4m3fn.safetensors", "Q4")
        self.assertEqual(res, {"name": "t5xxl_fp8_e4m3fn-Q4_K_M.gguf", "how": "download"})
        self.assertEqual(sorted(T.present(self.f, "t5xxl_fp8_e4m3fn.safetensors")), ["Q4"])   # o swap_tier acha a que foi baixada
        # sem faixa pronta: cria
        with mock.patch.object(T, "repo_option", return_value=None), mock.patch.object(requant, "create", return_value=self.f / "t5xxl_fp8_e4m3fn-Q3_K.gguf") as cr:
            res = T.install_tier(self.tmp, "image", "t5xxl_fp8_e4m3fn.safetensors", "Q3")
        self.assertEqual((res["how"], cr.call_count), ("create", 1))
        # sem rede: também cria
        with mock.patch.object(T, "repo_option", side_effect=OSError("sem rede")), mock.patch.object(requant, "create", return_value=self.f / "x-Q2_K.gguf"):
            self.assertEqual(T.install_tier(self.tmp, "image", "t5xxl_fp8_e4m3fn.safetensors", "Q2")["how"], "create")

    def test_download_only_says_why_when_there_is_nothing_to_download(self):
        touch(self.f, "ae.safetensors")
        with self.assertRaises(ProviderError) as cm:
            T.install_tier(self.tmp, "image", "ae.safetensors", "Q4", "download")
        self.assertIn("Criar", str(cm.exception))

    def test_an_installed_tier_is_not_made_again(self):
        touch(self.f, "clip_l.safetensors")
        touch(self.f, "clip_l-Q4_K.gguf")
        self.assertEqual(T.install_tier(self.tmp, "image", "clip_l.safetensors", "Q4"), {"name": "clip_l-Q4_K.gguf", "how": "present"})

    def test_bad_requests(self):
        for kw in ({"kind": "text"}, {"tier": "Q5"}, {"how": "magia"}, {"name": "flux1-dev-Q8_0.gguf"}):
            args = {"kind": "image", "name": "clip_l.safetensors", "tier": "Q4", "how": "auto", **kw}
            with self.assertRaises(ProviderError, msg=str(kw)):
                T.install_tier(self.tmp, args["kind"], args["name"], args["tier"], args["how"])


class DownloadWithTierTests(unittest.TestCase):
    """Ao baixar os arquivos de apoio de um modelo já na faixa escolhida, o codificador que o repositório tem pronto vem direto nela (não o padrão maior)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_the_text_encoder_comes_in_the_tier_and_the_vae_as_usual(self):
        touch(self.tmp, "flux1-dev-Q4_K_S.gguf")
        got = []

        def fake_dl(repo, filename, folder, token, progress, cancelled, any_file=False, dest_name="", connections=0):
            got.append((repo, filename, dest_name))
            Path(folder, dest_name or Path(filename).name).write_bytes(b"x" * 50)
            return Path(folder, dest_name or Path(filename).name)

        def fake_many(repo, files, folder, token, listing, progress, cancelled, any_file=False):
            got.append((repo, files[0], ""))
            Path(folder, Path(files[0]).name).write_bytes(b"x" * 50)

        def opt(name, tier, token=""):
            return {"repo": "city96/t5-v1_1-xxl-encoder-gguf", "file": "t5-v1_1-xxl-encoder-Q3_K_M.gguf", "size": 10} if T.stem(name) == "t5xxl_fp8_e4m3fn" else None

        with mock.patch.object(T, "repo_option", opt), mock.patch.object(hf, "download", fake_dl), mock.patch.object(hf, "download_many", fake_many):
            files = support.download_missing(self.tmp, "flux1-dev-Q4_K_S.gguf", "", None, lambda: False, lambda m: None, "Q3")
        self.assertIn("t5xxl_fp8_e4m3fn-Q3_K_M.gguf", files)                              # já na faixa, com o radical do arquivo que a receita usa
        self.assertNotIn("t5xxl_fp8_e4m3fn.safetensors", files)                           # o padrão (4,9 GB) nem foi baixado
        self.assertIn("ae.safetensors", files)                                            # o VAE não tem faixa pronta: vem como sempre
        self.assertIn("clip_l.safetensors", files)

    def test_without_a_tier_nothing_changes(self):
        touch(self.tmp, "flux1-dev-Q4_K_S.gguf")
        names = []
        with mock.patch.object(T, "repo_option", side_effect=AssertionError("não devia consultar")), mock.patch.object(hf, "download_many", lambda repo, files, folder, *a, **k: names.append(Path(files[0]).name)):
            files = support.download_missing(self.tmp, "flux1-dev-Q4_K_S.gguf")
        self.assertEqual(sorted(files), ["ae.safetensors", "clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"])


class NodeUseTests(unittest.TestCase):
    """O campo «Faixa dos arquivos de apoio» do nó: a carga do modelo recebe o VAE/codificador da faixa pedida."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "image").mkdir()
        self.f = self.tmp / "image"
        M._LOCAL_CACHE.clear()
        self.sd = FakeSD()
        p = mock.patch.dict(sys.modules, {"stable_diffusion_cpp": self.sd.module})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(M.GGUFMedia, "_cli_fallback", return_value=False)
        q.start()
        self.addCleanup(q.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.name = "flux1-dev-Q4_K_S.gguf"
        for n in (self.name, "ae.safetensors", "ae-Q8_0.gguf", "clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"):
            touch(self.f, n)
        self.notes = []

    def provider(self):
        M._LOCAL_CACHE.clear()
        ctl = mock.Mock()
        ctl.note = self.notes.append
        return M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {"image": self.name}, "needs_key": False}, ctl)

    def test_the_vae_of_the_asked_tier_is_loaded(self):
        self.provider().image("um gato", size="512x512", model=self.name, extra={"support_quant": "Q8"})
        load = self.sd.loads[-1]
        self.assertTrue(load["vae_path"].endswith("ae-Q8_0.gguf"), load)
        self.assertTrue(load["clip_l_path"].endswith("clip_l.safetensors"))   # sem Q8 de clip_l: como está
        self.assertTrue(any("clip_l.safetensors" in n and "Q8" in n for n in self.notes), self.notes)
        self.assertNotIn("support_quant", self.sd.runs[-1])                   # o campo não vaza para a geração

    def test_without_the_field_nothing_changes(self):
        self.provider().image("um gato", size="512x512", model=self.name)
        self.assertTrue(self.sd.loads[-1]["vae_path"].endswith("ae.safetensors"))

    def test_an_unknown_tier_is_ignored_with_a_note(self):
        self.provider().image("um gato", size="512x512", model=self.name, extra={"support_quant": "Q5"})
        self.assertTrue(any("não é uma faixa conhecida" in n for n in self.notes), self.notes)
        self.assertTrue(self.sd.loads[-1]["vae_path"].endswith("ae.safetensors"))


class ApiTests(ServerCase):
    def folder(self):
        f = self.store.models_dir / "image"
        f.mkdir(parents=True, exist_ok=True)
        for old in f.iterdir():   # o servidor é compartilhado entre os testes da classe: cada um começa com a pasta vazia
            old.unlink()
        return f

    def test_listing_and_tier_job(self):
        f = self.folder()
        for n in ("ae.safetensors", "clip_l.safetensors", "flux1-dev-Q4_K_S.gguf", "mmproj-F16.gguf"):
            touch(f, n)
        status, out = self.c.json("GET", "/api/models/support/files")
        self.assertEqual(status, 200)
        names = {x["name"]: x for x in out["files"]}
        self.assertEqual(sorted(names), ["ae.safetensors", "clip_l.safetensors"])    # o modelo de difusão e o mmproj não são «apoio»
        self.assertEqual(names["ae.safetensors"]["role"], "vae")
        self.assertEqual(names["ae.safetensors"]["lower"], ["Q2", "Q3", "Q4", "Q6", "Q8"])
        with mock.patch("openflow.canvas.support_tiers.install_tier", return_value={"name": "clip_l-Q4_K.gguf", "how": "create"}) as it:
            status, job = self.c.json("POST", "/api/models/support/tier", {"kind": "image", "name": "clip_l.safetensors", "tier": "q4", "how": "create"})
            self.assertEqual(status, 200)
            ev = self.c.sse(f"/api/jobs/{job['job_id']}/events")
        self.assertEqual([e["name"] for e in ev if e["type"] == "done"], ["clip_l-Q4_K.gguf"])
        self.assertEqual(it.call_args[0][2:5], ("clip_l.safetensors", "Q4", "create"))
        jobs = self.c.json("GET", "/api/library/downloads")[1]
        self.assertIn("support_tier", [d["kind"] for d in jobs["downloads"]])

    def test_bad_requests_are_refused(self):
        f = self.folder()
        touch(f, "clip_l-Q4_K.gguf")
        post = lambda b: self.c.json("POST", "/api/models/support/tier", b)[0]   # noqa: E731
        self.assertEqual(post({"kind": "text", "name": "clip_l.safetensors", "tier": "Q4"}), 400)
        self.assertEqual(post({"kind": "image", "name": "clip_l-Q4_K.gguf", "tier": "Q5"}), 400)
        self.assertEqual(post({"kind": "image", "name": "nao-baixado.safetensors", "tier": "Q4"}), 404)
        self.assertEqual(post({"kind": "image", "name": "clip_l-Q4_K.gguf", "tier": "Q6", "how": "create"}), 400)   # Q6 não é menor que Q4


class CliTests(unittest.TestCase):
    def test_quant_listing_and_support_tier(self):
        import contextlib
        import types

        from openflow import cli
        from openflow.storage import Store

        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        store = Store(home)
        f = hf.kind_dir(store.models_dir, "image", create=True)
        touch(f, "ae.safetensors")
        touch(f, "clip_l.safetensors")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli._models_quant(store, types.SimpleNamespace(name="", tier="", kind=""))
        out = buf.getvalue()
        self.assertIn("ae.safetensors", out)
        self.assertIn("dá para criar: Q2, Q3, Q4, Q6, Q8", out.replace("can create", "dá para criar") if "can create" in out else out)
        calls = []
        with mock.patch.object(T, "install_tier", side_effect=lambda md, kind, name, tier, how, *a: calls.append((name, tier, how)) or {"name": name + ".x", "how": "create"}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                bad = cli._support_tier_all(store, "Q4", "create", "")
        self.assertEqual((bad, sorted(c[0] for c in calls)), (0, ["ae.safetensors", "clip_l.safetensors"]))
        self.assertEqual({c[1:] for c in calls}, {("Q4", "create")})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli._support_tier_all(store, "Q5", "auto", ""), 1)


if __name__ == "__main__":
    unittest.main()
