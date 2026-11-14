"""v0.8: Qwen (Alibaba Cloud), Krea e Bria + as famílias locais novas (Qwen-Image-Edit, Krea 2, FIBO 2.0, FLUX.1 Krea)."""
import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import media as M
from openflow.canvas import support
from openflow.providers import http
from openflow.providers.base import ProviderError
from tests.test_canvas import MP4, PNG


class Fake:
    """Troca post_json/get_json/get_bytes: `routes` = [(parte da URL, resposta ou função(url, body, headers))]; guarda tudo em `calls`."""

    def __init__(self, routes, files=None):
        self.routes, self.files, self.calls = list(routes), files or {}, []

    def _hit(self, method, url, body=None, headers=None):
        self.calls.append((method, url, body, headers or {}))
        for part, res in self.routes:
            if part in url:
                if callable(res):
                    return res(url, body, headers)
                if isinstance(res, list):
                    return res.pop(0) if len(res) > 1 else res[0]
                return res
        raise AssertionError("rota sem resposta: " + url)

    def __enter__(self):
        self.ps = [mock.patch.object(http, "post_json", lambda url, body, headers=None, **k: self._hit("POST", url, body, headers)),
                   mock.patch.object(http, "get_json", lambda url, headers=None, **k: self._hit("GET", url, None, headers)),
                   mock.patch.object(http, "get_bytes", lambda url, headers=None, **k: (self.files[url], "application/octet-stream"))]
        for p in self.ps:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self.ps:
            p.stop()


def prov(pid, **cfg):
    p = M.MEDIA_PRESETS[pid]
    base = {k: v for k, v in p.items() if k not in ("models", "suggest")}
    base.update({"id": pid, "api_key": "k", "models": dict(p.get("models") or {}), "poll_seconds": 0.01, **cfg})
    return M._KINDS[base["kind"]](base)


class PresetsTests(unittest.TestCase):
    def test_the_new_providers_are_listed_with_their_capabilities(self):
        ids = [p["id"] for p in M.describe_media_presets({})]
        for pid in ("qwen", "krea", "bria"):
            self.assertIn(pid, ids)
        self.assertLess(ids.index("stability"), ids.index("qwen"))
        self.assertLess(ids.index("bria"), ids.index("replicate"))
        self.assertEqual(ids[-1], "custom")
        self.assertEqual(M.pick_provider({}, "video", "qwen"), "qwen")
        with self.assertRaises(ProviderError):
            M.pick_provider({}, "video", "krea")   # a Krea (aqui) só faz imagem


class QwenTests(unittest.TestCase):
    def test_text_to_image_is_async_polled_and_uses_a_supported_size(self):
        url = "https://x.test/img.png"
        fake = Fake([("image-synthesis", {"output": {"task_id": "t1"}}),
                     ("/tasks/t1", [{"output": {"task_status": "RUNNING"}}, {"output": {"task_status": "SUCCEEDED", "results": [{"url": url}]}}])], {url: PNG})
        with fake:
            out = prov("qwen").image("um farol", size="1280x720", seed=3, negative="borrão")
        self.assertEqual((out[0].kind, out[0].data), ("image", PNG))
        post = fake.calls[0]
        self.assertTrue(post[1].endswith("/services/aigc/text2image/image-synthesis"))
        self.assertEqual(post[3]["X-DashScope-Async"], "enable")
        self.assertEqual(post[3]["Authorization"], "Bearer k")
        self.assertEqual(post[2]["parameters"], {"seed": 3, "negative_prompt": "borrão", "size": "1664*928", "n": 1})   # 16:9 → o tamanho do Qwen mais próximo
        self.assertEqual(len([c for c in fake.calls if c[0] == "GET"]), 2)

    def test_references_switch_to_the_edit_model_and_send_the_images(self):
        url = "https://x.test/e.png"
        fake = Fake([("multimodal-generation", {"output": {"choices": [{"message": {"content": [{"image": url}]}}]}})], {url: PNG})
        with fake:
            out = prov("qwen").image("tire o fundo", refs=[(PNG, "image/png")] * 5)
        self.assertEqual(out[0].data, PNG)
        body = fake.calls[0][2]
        self.assertEqual(body["model"], "qwen-image-edit-plus")
        parts = body["input"]["messages"][0]["content"]
        self.assertEqual([("image" in x) for x in parts], [True, True, True, False])   # 3 imagens (o limite) e o texto
        self.assertEqual(parts[-1], {"text": "tire o fundo"})
        self.assertNotIn("X-DashScope-Async", fake.calls[0][3])

    def test_an_unknown_optional_parameter_is_dropped_and_retried_once(self):
        url = "https://x.test/e.png"
        calls = []

        def gen(u, body, h):
            calls.append(body)
            if "seed" in body["parameters"]:
                raise ProviderError("InvalidParameter: seed", status=400)
            return {"output": {"choices": [{"message": {"content": [{"image": url}]}}]}}

        with Fake([("multimodal-generation", gen)], {url: PNG}):
            prov("qwen").image("x", seed=5, refs=[(PNG, "image/png")])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("seed", calls[1]["parameters"])

    def test_a_failed_task_reports_the_service_message(self):
        with Fake([("image-synthesis", {"output": {"task_id": "t"}}), ("/tasks/t", {"output": {"task_status": "FAILED", "message": "conteúdo recusado"}})]):
            with self.assertRaises(ProviderError) as cm:
                prov("qwen").image("x")
        self.assertIn("conteúdo recusado", str(cm.exception))

    def test_video_text_and_image_to_video(self):
        url = "https://x.test/v.mp4"
        fake = Fake([("video-synthesis", {"output": {"task_id": "v"}}), ("/tasks/v", {"output": {"task_status": "SUCCEEDED", "video_url": url}})], {url: MP4})
        with fake:
            out = prov("qwen").video("ondas", duration=5, aspect="9:16", seed=2)
            self.assertEqual(out.kind, "video")
            body = fake.calls[0][2]
            self.assertEqual((body["model"], body["parameters"]["size"], body["parameters"]["duration"]), ("wan2.2-t2v-plus", "720*1280", 5))
            fake.calls.clear()
            prov("qwen").video("ondas", image=(PNG, "image/png"), long_side=1080)
        body = fake.calls[0][2]
        self.assertEqual(body["model"], "wan2.2-i2v-plus")   # com imagem inicial: modelo i2v
        self.assertTrue(body["input"]["img_url"].startswith("data:image/png;base64,"))
        self.assertEqual(body["parameters"]["resolution"], "1080P")
        self.assertNotIn("size", body["parameters"])

    def test_missing_key_is_reported(self):
        with self.assertRaises(ProviderError) as cm:
            prov("qwen", api_key="").image("x")
        self.assertIn("chave", str(cm.exception).lower())


class KreaTests(unittest.TestCase):
    def test_model_slug_goes_in_the_path_and_the_job_is_polled(self):
        url = "https://x.test/k.png"
        fake = Fake([("/generate/image/krea/krea-3", {"job_id": "j1", "status": "queued"}),
                     ("/jobs/j1", [{"status": "processing"}, {"status": "completed", "result": {"urls": [url]}}])], {url: PNG})
        with fake:
            out = prov("krea").image("um gato", size="1920x1080", seed=4, count=1)
        self.assertEqual(out[0].data, PNG)
        body = fake.calls[0][2]
        self.assertEqual((body["prompt"], body["width"], body["height"], body["seed"]), ("um gato", 1920, 1080, 4))
        self.assertEqual(fake.calls[0][3]["Authorization"], "Bearer k")

    def test_other_providers_models_and_bad_slug(self):
        url = "https://x.test/k.png"
        fake = Fake([("/generate/image/bfl/flux-1-dev", {"job_id": "j"}), ("/jobs/j", {"status": "completed", "result": {"urls": [url]}})], {url: PNG})
        with fake:
            prov("krea").image("x", model="bfl/flux-1-dev")
        with self.assertRaises(ProviderError):
            prov("krea").image("x", model="sem-barra")

    def test_a_rejected_size_is_retried_with_only_the_prompt_and_failure_is_reported(self):
        seen = []

        def post(u, body, h):
            seen.append(body)
            if "width" in body:
                raise ProviderError("width inválido", status=422)
            return {"job_id": "j"}

        with Fake([("/generate/image/", post), ("/jobs/j", {"status": "failed", "error": "sem créditos"})]):
            with self.assertRaises(ProviderError) as cm:
                prov("krea").image("x", size="1024x1024")
        self.assertEqual(seen[1], {"prompt": "x"})
        self.assertIn("sem créditos", str(cm.exception))


class BriaTests(unittest.TestCase):
    def test_async_generation_with_status_url_and_reference(self):
        url = "https://x.test/b.png"
        fake = Fake([("/v2/image/generate", {"request_id": "r1", "status_url": "https://engine.test/v2/status/r1"}),
                     ("/v2/status/r1", [{"status": "IN_PROGRESS"}, {"status": "COMPLETED", "result": {"image_url": url, "seed": 9}}])], {url: PNG})
        with fake:
            out = prov("bria").image("um carro", size="1344x768", seed=9, refs=[(PNG, "image/png")] * 2)
        self.assertEqual(out[0].data, PNG)
        post = fake.calls[0]
        self.assertEqual(post[3]["api_token"], "k")
        self.assertEqual((post[2]["aspect_ratio"], post[2]["seed"]), ("16:9", 9))
        self.assertEqual(post[2]["images"], [base64.b64encode(PNG).decode()])   # só 1 referência
        self.assertNotIn("Authorization", post[3])

    def test_synchronous_answer_and_error_state(self):
        url = "https://x.test/b.png"
        with Fake([("/image/generate", {"result": {"image_url": url}, "request_id": "r"})], {url: PNG}):
            self.assertEqual(prov("bria").image("x")[0].data, PNG)
        with Fake([("/image/generate", {"request_id": "r", "status_url": "https://e.test/s"}), ("e.test/s", {"status": "ERROR", "error": {"message": "prompt recusado"}})]):
            with self.assertRaises(ProviderError) as cm:
                prov("bria").image("x")
        self.assertIn("prompt recusado", str(cm.exception))


class FamiliesTests(unittest.TestCase):
    def test_new_local_families_are_recognised_with_their_recipes(self):
        cases = {"qwen-image-edit-2511-Q4_K_M.gguf": "qwen-image-edit", "Qwen-Image-Edit-2509-Q8_0.gguf": "qwen-image-edit", "qwen-image-Q4_K_M.gguf": "qwen-image",
                 "krea2_turbo-Q4_K_M.gguf": "krea2", "fibo2-dev-Q8_0.gguf": "fibo2", "fibo2-edit-turbo-Q4_K_M.gguf": "fibo2", "flux1-krea-dev-Q4_K_S.gguf": "flux1-krea", "flux1-dev-Q4_K_S.gguf": "flux"}
        for name, fam in cases.items():
            self.assertEqual(support.family_of(name)["id"], fam, name)
        run = lambda n: support.run_for(support.family_of(n), n)   # noqa: E731
        self.assertEqual((run("krea2_turbo-Q4.gguf")["sample_steps"], run("krea2_turbo-Q4.gguf")["cfg_scale"]), (8, 1.0))
        self.assertEqual(run("krea2_raw-Q4.gguf")["sample_steps"], 30)
        self.assertEqual((run("fibo2-edit-turbo-Q4.gguf")["sample_steps"], run("fibo2-dev-Q8.gguf")["sample_steps"]), (4, 50))

    def test_companions_are_planned_for_each_new_family(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            for name, want in {"qwen-image-edit-2511-Q4_K_M.gguf": {"qwen_image_vae.safetensors", "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "mmproj-F16.gguf"},
                               "krea2_turbo-Q4_K_M.gguf": {"qwen_image_vae.safetensors", "Qwen3-VL-4B-Instruct-Q4_K_M.gguf"},
                               "fibo2-dev-Q8_0.gguf": {"flux2-vae.safetensors", "Qwen3-VL-4B-Instruct-Q4_K_M.gguf"},
                               "flux1-krea-dev-Q4_K_S.gguf": {"ae.safetensors", "clip_l.safetensors", "t5xxl_fp8_e4m3fn.safetensors"}}.items():
                (folder / name).write_bytes(b"x")
                plan = support.plan(folder, name, "image")
                self.assertEqual({i["dest"] for i in plan["items"]}, want, name)
            roles = {i["dest"]: i["role"] for i in support.plan(folder, "qwen-image-edit-2511-Q4_K_M.gguf", "image")["items"]}
            self.assertEqual(roles["mmproj-F16.gguf"], "mmproj")

    def test_installed_companions_are_found_and_the_edit_model_takes_references(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            model = folder / "qwen-image-edit-2511-Q4_K_M.gguf"
            for n in (model.name, "qwen_image_vae.safetensors", "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "mmproj-F16.gguf", "unrelated.mmproj.gguf"):
                (folder / n).write_bytes(b"x")
            found = support.find_companions(folder, model, support.family_of(model.name))
            self.assertEqual(found, {"vae_path": "qwen_image_vae.safetensors", "llm_path": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "llm_vision_path": "mmproj-F16.gguf"})
            self.assertEqual(support.plan(folder, model.name, "image")["items"], [])
        self.assertTrue(M._GGUF_MULTI_REF.search("qwen-image-edit-2511-Q4_K_M.gguf"))
        self.assertTrue(M._GGUF_MULTI_REF.search("fibo2-edit-turbo-Q4_K_M.gguf"))


if __name__ == "__main__":
    unittest.main()
