"""Arquivos de apoio instalados junto do modelo (VAE, codificadores de texto e mmproj): plano, descoberta no repositório, download, rotas e CLI."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import hf  # noqa: E402
from openflow.canvas import support  # noqa: E402
from openflow.providers.base import ProviderError  # noqa: E402
from tests.helpers import ServerCase, TmpCase  # noqa: E402

VL_TREE = [  # unsloth/Qwen2.5-VL-7B-Instruct-GGUF (nomes conferidos no Hugging Face)
    {"name": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "size": 4683072384},
    {"name": "Qwen2.5-VL-7B-Instruct-Q8_0.gguf", "size": 8098524032},
    {"name": "mmproj-BF16.gguf", "size": 1354163040},
    {"name": "mmproj-F16.gguf", "size": 1354163040},
    {"name": "mmproj-F32.gguf", "size": 2703221600},
    {"name": "README.md", "size": 18625},
]
BUNDLE_TREE = [  # um repositório de difusão que traz o VAE e os codificadores de texto ao lado do modelo
    {"name": "tiny-diffusion-Q4_K_M.gguf", "size": 3_000_000_000},
    {"name": "vae/ae.safetensors", "size": 335_000_000},
    {"name": "text_encoders/clip_l.safetensors", "size": 246_144_152},
    {"name": "text_encoders/t5xxl_fp16.safetensors", "size": 9_787_841_024},
    {"name": "text_encoders/t5xxl_fp8_e4m3fn.safetensors", "size": 4_893_934_904},
    {"name": "unet/diffusion_pytorch_model.safetensors", "size": 5_000_000_000},
]


class NamingTests(unittest.TestCase):
    def test_mmproj_has_one_name_per_model_even_for_split_models(self):
        self.assertEqual(support.mmproj_name("Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"), "Qwen2.5-VL-7B-Instruct-Q4_K_M.mmproj.gguf")
        self.assertEqual(support.mmproj_name("big-Q4_K_M-00001-of-00003.gguf"), "big-Q4_K_M.mmproj.gguf")
        self.assertIn("mmproj", support.mmproj_name("x.gguf").lower())   # as listas de modelos escondem tudo que tem «mmproj» no nome

    def test_the_best_projector_is_f16_and_the_one_named_after_the_model_wins(self):
        self.assertEqual(support._pick_mmproj(VL_TREE, "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf")["name"], "mmproj-F16.gguf")
        tree = VL_TREE + [{"name": "gemma-3-4b-it-mmproj-f16.gguf", "size": 800_000_000}]
        self.assertEqual(support._pick_mmproj(tree, "gemma-3-4b-it-Q4_K_M.gguf")["name"], "gemma-3-4b-it-mmproj-f16.gguf")
        self.assertIsNone(support._pick_mmproj([{"name": "a.gguf", "size": 1}], "a.gguf"))


class PlanTests(TmpCase):
    def test_known_family_lists_vae_and_text_encoder_with_their_own_repositories(self):
        info = support.plan(self.tmp, "flux-2-klein-4b-Q4_K_M.gguf", "image")
        roles = {i["role"]: i for i in info["items"]}
        self.assertEqual(set(roles), {"vae", "text_encoder"})
        self.assertEqual(roles["vae"]["repo"], "Comfy-Org/flux2-dev")
        self.assertEqual(info["family"], "flux2-klein-4b")
        (self.tmp / "flux2-vae.safetensors").write_bytes(b"x")   # o que já está na pasta não é baixado de novo
        self.assertEqual([i["role"] for i in support.plan(self.tmp, "flux-2-klein-4b-Q4_K_M.gguf", "image")["items"]], ["text_encoder"])

    def test_wan21_is_a_known_family(self):
        info = support.plan(self.tmp, "wan2.1-t2v-1.3B-Q4_K_M.gguf", "video")
        self.assertEqual(info["family"], "wan21-t2v")
        self.assertEqual({i["role"] for i in info["items"]}, {"vae", "text_encoder"})

    def test_text_model_gets_the_projector_of_its_repository_under_its_own_name(self):
        info = support.plan(self.tmp, "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "text", "unsloth/Qwen2.5-VL-7B-Instruct-GGUF", VL_TREE)
        self.assertEqual(len(info["items"]), 1)
        it = info["items"][0]
        self.assertEqual((it["role"], it["file"], it["dest"]), ("mmproj", "mmproj-F16.gguf", "Qwen2.5-VL-7B-Instruct-Q4_K_M.mmproj.gguf"))
        (self.tmp / it["dest"]).write_bytes(b"x")
        self.assertEqual(support.plan(self.tmp, "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "text", "unsloth/Qwen2.5-VL-7B-Instruct-GGUF", VL_TREE)["items"], [])

    def test_text_model_without_projector_needs_nothing(self):
        self.assertEqual(support.plan(self.tmp, "a-Q4_K_M.gguf", "text", "dono/a", [{"name": "a-Q4_K_M.gguf", "size": 1}])["items"], [])

    def test_unknown_diffusion_model_uses_what_its_repository_bundles(self):
        info = support.plan(self.tmp, "tiny-diffusion-Q4_K_M.gguf", "image", "dono/tiny-diffusion", BUNDLE_TREE)
        got = {(i["role"], i["file"]) for i in info["items"]}
        self.assertIn(("vae", "vae/ae.safetensors"), got)
        self.assertIn(("text_encoder", "text_encoders/clip_l.safetensors"), got)
        self.assertIn(("text_encoder", "text_encoders/t5xxl_fp8_e4m3fn.safetensors"), got)       # o fp8 (menor) no lugar do fp16 da mesma família
        self.assertNotIn(("text_encoder", "text_encoders/t5xxl_fp16.safetensors"), got)
        self.assertFalse([i for i in info["items"] if "diffusion_pytorch_model" in i["file"]])   # o «unet» do repositório não é arquivo de apoio
        self.assertTrue(all(i["repo"] == "dono/tiny-diffusion" for i in info["items"]))

    def test_status_of_reports_what_is_there_and_what_is_missing_without_network(self):
        (self.tmp / "flux2-vae.safetensors").write_bytes(b"x")
        (self.tmp / "flux-2-klein-4b-Q4_K_M.mmproj.gguf").write_bytes(b"x")
        st = support.status_of(self.tmp, "flux-2-klein-4b-Q4_K_M.gguf", "image")
        self.assertEqual([h["role"] for h in st["have"]], ["vae", "mmproj"])
        self.assertEqual([m["role"] for m in st["missing"]], ["text_encoder"])
        self.assertGreater(st["approx_gb"], 0)


class InstallTests(TmpCase):
    def test_installs_everything_that_is_missing_and_isolates_failures(self):
        calls = []

        def fake_download(repo, filename, folder, token="", progress=None, cancelled=lambda: False, any_file=False, dest_name=""):
            calls.append((repo, filename, dest_name))
            if "clip" in filename:
                raise ProviderError("HTTP 404")
            (Path(folder) / (dest_name or Path(filename).name)).write_bytes(b"ok")
            return Path(folder) / (dest_name or Path(filename).name)

        notes = []
        with mock.patch.object(hf, "download", fake_download):
            res = support.install_with_model(self.tmp, "tiny-diffusion-Q4_K_M.gguf", "image", "dono/tiny-diffusion", "tok", BUNDLE_TREE, note=notes.append)
        self.assertIn("ae.safetensors", res["installed"])
        self.assertEqual([f["label"] for f in res["failed"]], ["Codificador de texto (clip_l.safetensors)"])      # a falha de um não impede os outros
        self.assertTrue((self.tmp / "ae.safetensors").is_file())
        self.assertTrue(any("Baixando" in n for n in notes))

    def test_the_projector_is_saved_under_the_model_name(self):
        saved = {}

        def fake_download(repo, filename, folder, token="", progress=None, cancelled=lambda: False, any_file=False, dest_name=""):
            saved["args"] = (repo, filename, dest_name, any_file)
            (Path(folder) / dest_name).write_bytes(b"ok")

        with mock.patch.object(hf, "download", fake_download):
            res = support.install_with_model(self.tmp, "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "text", "unsloth/Qwen2.5-VL-7B-Instruct-GGUF", "", VL_TREE)
        self.assertEqual(saved["args"], ("unsloth/Qwen2.5-VL-7B-Instruct-GGUF", "mmproj-F16.gguf", "Qwen2.5-VL-7B-Instruct-Q4_K_M.mmproj.gguf", True))
        self.assertEqual(res["installed"], ["Qwen2.5-VL-7B-Instruct-Q4_K_M.mmproj.gguf"])
        self.assertIsNotNone(support.mmproj_for(self.tmp, "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"))

    def test_cancelling_stops_and_not_enough_disk_is_reported(self):
        def cancel(*a, **k):
            raise ProviderError("cancelado")

        with mock.patch.object(hf, "download", cancel), self.assertRaises(ProviderError):
            support.install_with_model(self.tmp, "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "text", "dono/x", "", VL_TREE)
        with mock.patch("openflow.canvas.support.shutil.disk_usage", return_value=mock.Mock(free=10)):
            res = support.install_with_model(self.tmp, "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "text", "dono/x", "", VL_TREE)
        self.assertIn("espaço", res["failed"][0]["error"])
        self.assertEqual(res["installed"], [])

    def test_download_to_another_name_is_validated(self):
        with self.assertRaises(ProviderError):
            hf.download("dono/x", "mmproj-F16.gguf", self.tmp, dest_name="../evil.gguf", any_file=True)
        with self.assertRaises(ProviderError):
            hf.download("dono/x", "mmproj-F16.gguf", self.tmp, dest_name="a/b.gguf", any_file=True)


class SupportApiTests(ServerCase):
    def setUp(self):
        self.store.save_settings({"hf": {"auto_support": True}})
        for kind in ("text", "image"):
            for f in hf.kind_dir(self.store.models_dir, kind, create=True).glob("*"):
                if f.is_file():
                    f.unlink()

    def run_download(self, body, tree):
        def fake_many(repo, names, dest, *a, **k):
            (dest / names[0]).write_bytes(b"GGUF")
            return dest / names[0]

        installed = []

        def fake_install(folder, name, kind, repo="", token="", repo_tree=None, progress=None, cancelled=lambda: False, note=lambda m: None):
            plan = support.plan(folder, name, kind, repo, repo_tree)
            for it in plan["items"]:
                (Path(folder) / it["dest"]).write_bytes(b"x")
                installed.append(it["dest"])
            return {"installed": [i["dest"] for i in plan["items"]], "failed": [], "items": plan["items"], "family": plan["family"]}

        with mock.patch.object(hf, "download_many", fake_many), mock.patch.object(hf, "repo_files", return_value=tree), mock.patch.object(support, "install_with_model", fake_install):
            s, job = self.c.json("POST", "/api/hf/download", body)
            self.assertEqual(s, 200, job)
            events = self.c.sse(f"/api/jobs/{job['job_id']}/events")
        return events, installed

    def test_downloading_a_vision_model_brings_the_projector(self):
        events, installed = self.run_download({"repo": "unsloth/Qwen2.5-VL-7B-Instruct-GGUF", "file": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "quant": "Q4_K_M", "kind": "text"}, VL_TREE)
        self.assertEqual(installed, ["Qwen2.5-VL-7B-Instruct-Q4_K_M.mmproj.gguf"])
        done = [e for e in events if e["type"] == "done"][0]
        self.assertEqual(done["support"], ["Qwen2.5-VL-7B-Instruct-Q4_K_M.mmproj.gguf"])
        self.assertTrue(any(e["type"] == "support" and e["items"][0]["role"] == "mmproj" for e in events))

    def test_downloading_an_image_model_of_a_known_family_brings_vae_and_text_encoder(self):
        events, installed = self.run_download({"repo": "dono/flux", "file": "flux-2-klein-4b-Q4_K_M.gguf", "quant": "Q4_K_M", "kind": "image"}, [])
        self.assertEqual(sorted(installed), ["Qwen3-4B-Q4_K_M.gguf", "flux2-vae.safetensors"])
        self.assertEqual([e for e in events if e["type"] == "done"][0]["support_failed"], [])

    def test_a_plain_model_downloads_alone_and_the_setting_turns_it_off(self):
        events, installed = self.run_download({"repo": "dono/tiny", "file": "tiny-Q4_K_M.gguf", "quant": "Q4_K_M", "kind": "image"}, [{"name": "tiny-Q4_K_M.gguf", "size": 1}])
        self.assertEqual(installed, [])
        self.store.save_settings({"hf": {"auto_support": False}})
        events, installed = self.run_download({"repo": "dono/flux", "file": "flux-2-klein-4b-Q4_K_M.gguf", "quant": "Q4_K_M", "kind": "image"}, [])
        self.assertEqual(installed, [])
        events, installed = self.run_download({"repo": "unsloth/Qwen2.5-VL-7B-Instruct-GGUF", "file": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "quant": "Q4_K_M", "kind": "text", "support": True}, VL_TREE)
        self.assertEqual(installed, [])   # desligado nas configurações: o pedido do navegador não religa
        self.store.save_settings({"hf": {"auto_support": True}})
        events, installed = self.run_download({"repo": "unsloth/Qwen2.5-VL-7B-Instruct-GGUF", "file": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "quant": "Q4_K_M", "kind": "text", "support": False}, VL_TREE)
        self.assertEqual(installed, [])   # «Só o modelo» na tela

    def test_files_route_previews_what_will_come_along(self):
        grouped = hf.group_files([f for f in VL_TREE if f["name"].endswith(".gguf") and "mmproj" not in f["name"]], 16)
        with mock.patch.object(hf, "repo_files", return_value=VL_TREE):
            s, r = self.c.json("GET", "/api/hf/files?repo=unsloth/Qwen2.5-VL-7B-Instruct-GGUF&kind=text")
        self.assertEqual(s, 200, r)
        self.assertEqual([f["name"] for f in r["files"]], [f["name"] for f in grouped])
        self.assertEqual([x["role"] for x in r["support"]], ["mmproj"])     # a tela mostra «vem junto: projetor de visão»
        self.assertNotIn("mmproj", json_names(r["files"]))

    def test_status_and_repair_route_for_installed_models(self):
        folder = hf.kind_dir(self.store.models_dir, "image", create=True)
        (folder / "flux-2-klein-4b-Q4_K_M.gguf").write_bytes(b"GGUF")
        s, r = self.c.json("GET", "/api/models/support")
        self.assertEqual(s, 200)
        me = next(m for m in r["models"] if m["name"] == "flux-2-klein-4b-Q4_K_M.gguf")
        self.assertEqual({m["role"] for m in me["missing"]}, {"vae", "text_encoder"})

        def fake_download(repo, filename, folder, token="", progress=None, cancelled=lambda: False, any_file=False, dest_name=""):
            (Path(folder) / (dest_name or Path(filename).name)).write_bytes(b"ok")

        with mock.patch.object(hf, "download", fake_download):
            s, job = self.c.json("POST", "/api/models/support/install", {"kind": "image", "name": "flux-2-klein-4b-Q4_K_M.gguf"})
            self.assertEqual(s, 200, job)
            events = self.c.sse(f"/api/jobs/{job['job_id']}/events")
        self.assertEqual(sorted([e for e in events if e["type"] == "done"][0]["files"]), ["Qwen3-4B-Q4_K_M.gguf", "flux2-vae.safetensors"])
        me = next(m for m in self.c.json("GET", "/api/models/support")[1]["models"] if m["name"] == "flux-2-klein-4b-Q4_K_M.gguf")
        self.assertEqual(me["missing"], [])
        self.assertEqual(self.c.json("POST", "/api/models/support/install", {"kind": "image", "name": "nao-existe.gguf"})[0], 404)

    def test_deleting_a_model_removes_its_projector(self):
        folder = hf.kind_dir(self.store.models_dir, "text", create=True)
        (folder / "vl-Q4_K_M.gguf").write_bytes(b"GGUF")
        (folder / "vl-Q4_K_M.mmproj.gguf").write_bytes(b"GGUF")
        (folder / "other-Q4_K_M.mmproj.gguf").write_bytes(b"GGUF")
        s, _ = self.c.json("DELETE", "/api/hf/local/vl-Q4_K_M.gguf?kind=text")
        self.assertEqual(s, 200)
        self.assertEqual(sorted(p.name for p in folder.glob("*.gguf")), ["other-Q4_K_M.mmproj.gguf"])    # o projetor de outro modelo fica
        self.assertEqual([m["name"] for m in hf.local_models(self.store.models_dir, "text")], [])        # e nenhum mmproj aparece como «modelo»


def json_names(files):
    return " ".join(f["name"] for f in files)


if __name__ == "__main__":
    unittest.main()


class LocalLlamaVisionTests(TmpCase):
    """O mmproj baixado junto do modelo liga a visão do provedor local (melhor esforço; o carregamento real depende do llama-cpp-python)."""

    def provider(self, name="vl-Q4_K_M.gguf", with_mmproj=True):
        from openflow.providers.local_llama import LocalLlamaProvider

        (self.tmp / name).write_bytes(b"GGUF")
        if with_mmproj:
            (self.tmp / support.mmproj_name(name)).write_bytes(b"GGUF")
        return LocalLlamaProvider({"model": name, "models_dir": str(self.tmp)})

    def test_images_go_to_the_model_only_when_it_has_a_projector(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "descreva"}, {"type": "image", "media_type": "image/png", "data": "QUJD"}]}]
        out = self.provider()._messages(msgs, "")
        self.assertEqual(out[0]["content"][1], {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}})
        plain = self.provider("x-Q4_K_M.gguf", with_mmproj=False)._messages(msgs, "")
        self.assertEqual(plain[0]["content"], "descreva")        # sem mmproj: texto, como sempre

    def test_without_the_library_the_handler_is_simply_absent(self):
        from openflow.providers import local_llama as ll

        self.assertIsNone(ll.vision_handler(self.tmp / "nada.gguf"))     # sem mmproj
        self.provider()
        with mock.patch.dict(sys.modules, {"llama_cpp": None}):
            self.assertIsNone(ll.vision_handler(self.tmp / "vl-Q4_K_M.gguf"))

    def test_the_handler_follows_the_model_family_and_failures_fall_back_to_text(self):
        from openflow.providers import local_llama as ll

        self.provider("Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf")
        made = []

        class Fmt:
            class Qwen25VLChatHandler:
                def __init__(self, clip_model_path, verbose=False):
                    made.append(("qwen25", Path(clip_model_path).name))

            class Llava15ChatHandler:
                def __init__(self, clip_model_path, verbose=False):
                    raise RuntimeError("projetor incompatível")

        fake = mock.Mock(llama_chat_format=Fmt)
        with mock.patch.dict(sys.modules, {"llama_cpp": fake, "llama_cpp.llama_chat_format": Fmt}):
            self.assertIsNotNone(ll.vision_handler(self.tmp / "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"))
            self.provider("outro-Q4_K_M.gguf")
            self.assertIsNone(ll.vision_handler(self.tmp / "outro-Q4_K_M.gguf"))       # o manipulador falhou: segue só com texto
        self.assertEqual(made, [("qwen25", "Qwen2.5-VL-7B-Instruct-Q4_K_M.mmproj.gguf")])

    def test_images_do_not_count_as_base64_tokens(self):
        from openflow.providers.local_llama import fit_messages

        big = {"role": "user", "content": [{"type": "text", "text": "oi"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 2_000_000}}]}
        msgs, _ = fit_messages([{"role": "system", "content": "s"}, big], lambda t: len(t.split()), 4096, 512)
        self.assertEqual(len(msgs), 2)      # a imagem (~600 tokens) cabe; o texto do base64 não conta


class LibraryDeleteTests(TmpCase):
    def test_deleting_from_the_library_also_removes_the_projector(self):
        from openflow import preinstalled

        folder = hf.kind_dir(self.tmp, "text", create=True)
        (folder / "vl-Q4_K_M.gguf").write_bytes(b"GGUF")
        (folder / "vl-Q4_K_M.mmproj.gguf").write_bytes(b"GGUF")
        (folder / "outro-Q4_K_M.mmproj.gguf").write_bytes(b"GGUF")
        res = preinstalled.remove(self.tmp, [{"kind": "text", "name": "vl-Q4_K_M.gguf"}])
        self.assertEqual(res["deleted"], ["text/vl-Q4_K_M.gguf"])
        self.assertEqual(sorted(p.name for p in folder.glob("*.gguf")), ["outro-Q4_K_M.mmproj.gguf"])
