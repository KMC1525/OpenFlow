"""Nó Imagem com várias referências (Texto com @ + Mídia + Style Folder): modelos que juntam referências as usam também no modo Gerar e o tamanho pedido não é trocado pela 1ª foto."""
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow.canvas import media as M  # noqa: E402
from tests.test_canvas import PNG  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402


def png(w, h):
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(b, format="PNG")
    return b.getvalue()


class RefsInGenerateModeTests(TmpCase):
    def fake(self):
        runs = []

        class Img:
            def save(self, buf, format="PNG"):
                buf.write(PNG)

        class SD:
            def __init__(self, **kw):
                pass

            def generate_image(self, prompt, width, height, seed, cfg_scale=1.0, sample_steps=20, sample_method="euler", ref_images=None, init_image=None):
                runs.append({"w": width, "h": height, "refs": len(ref_images or [])})
                return [Img()]

        return mock.MagicMock(StableDiffusion=SD), runs

    def prov(self, name):
        (self.tmp / "image").mkdir(exist_ok=True)
        for n in (name, "flux2-vae.safetensors", "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"):
            (self.tmp / "image" / n).write_bytes(b"x")
        M._LOCAL_CACHE.clear()
        return M._KINDS["gguf_local"]({"id": "gguf_local", "label": "g", "models_dir": str(self.tmp), "models": {"image": name}, "needs_key": False})

    def test_models_that_merge_references_use_them_in_generate_mode_and_the_others_do_not(self):
        for name, need in (("flux-2-klein-4b-Q4_K_M.gguf", False), ("qwen-image-2.1-Q4_K_M.gguf", False), ("flux2-dev-Q4_K_M.gguf", False), ("flux-3-image-klein-Q4_K_M.gguf", False),
                           ("FLUX.1-Kontext-dev-Q4_K_S.gguf", False), ("flux1-dev-Q4_K_S.gguf", True), ("sd-turbo-Q8_0.gguf", True)):
            self.assertEqual(self.prov(name).refs_need_edit(), need, name)
        hf = M._KINDS["local_hf"]({"id": "local_hf", "label": "l", "models_dir": str(self.tmp), "models": {}, "needs_key": False})
        self.assertFalse(hf.refs_need_edit("black-forest-labs/FLUX.2-klein-4B"))
        self.assertFalse(hf.refs_need_edit("black-forest-labs/flux-3-image-klein"))
        self.assertTrue(hf.refs_need_edit("stabilityai/sd-turbo"))
        self.assertTrue(M.MediaProvider({}).refs_need_edit() is False)   # o padrão segue o atributo antigo

    def test_several_references_keep_the_requested_thumbnail_size(self):
        mod, runs = self.fake()
        p = self.prov("flux-2-klein-4b-Q4_K_M.gguf")
        refs = [(png(512, 768), "image/png"), (png(768, 512), "image/png"), (png(640, 640), "image/png"), (png(1000, 500), "image/png")]
        with mock.patch.dict(sys.modules, {"stable_diffusion_cpp": mod}):
            p.image("thumb de gameplay", size="1280x720", refs=refs)
            p.edit_mode = True
            p.image("editar a foto", size="1280x720", refs=refs[:1])
            p.edit_mode = False
            p.image("thumb com uma foto de rosto", size="1280x720", refs=refs[:1])   # modo Gerar com UMA referência em retrato: a thumb continua 16:9
        self.assertEqual(runs[0], {"w": 1280, "h": 720, "refs": 4})   # uma montagem: o tamanho pedido (16:9), não o retrato da 1ª foto
        self.assertEqual((runs[1]["w"], runs[1]["h"], runs[1]["refs"]), (848, 1280, 1))   # edição de uma imagem: mantém a proporção dela
        self.assertEqual(runs[2], {"w": 1280, "h": 720, "refs": 1})   # gerar com uma só referência: vale o tamanho pedido (bug da v0.6: saía em retrato)

    def test_the_engine_sends_references_in_generate_mode_to_a_multi_reference_model(self):
        from openflow.canvas import engine as E
        from tests.test_canvas import edge, node
        from openflow.canvas import procedural as proc
        from openflow.storage import Store

        store = Store(self.tmp / "home")
        cs = store.projects
        c = cs.create("t")
        ids = [cs.add_asset(c["id"], proc.image(f"i{i}", "64x64", i + 1), "png", "image", name=f"f{i}.png", mime="image/png")["id"] for i in range(3)]
        cs.save_layout(c["id"], {"nodes": [node("upload", nid="u", files=ids), node("image", nid="g", prompt="uma thumb")], "edges": [edge("u", "g", "refs")]})
        seen = {}

        class Multi:
            supports_refs = True
            refs_edit_only = True
            label = "Multi"

            def max_refs(self, model=""):
                return 4

            def refs_need_edit(self, model=""):
                return False

            def image(self, prompt, *, refs=(), **k):
                seen["n"] = len(refs)
                return [M.Media(PNG, "image/png")]

        events = []
        with mock.patch.object(E, "build_media", lambda *a, **k: Multi()):
            E.CanvasEngine(store, c["id"], events.append).run(None, False)
        self.assertEqual(seen["n"], 3)
        self.assertFalse([w for e in events for w in (e.get("warnings") or []) if "Editar" in w])


class EditModeTests(TmpCase):
    def run_edit(self, mode, answer, frames=True):
        from openflow.canvas import engine as E
        from tests.test_canvas import edge, node
        from openflow.canvas import procedural as proc
        from openflow.storage import Store

        store = Store(self.tmp / "home")
        cs = store.projects
        c = cs.create("t")
        src = proc.image("original", "96x96", 3)
        aid = cs.add_asset(c["id"], src, "png", "image", name="a.png", mime="image/png")["id"]
        cs.save_layout(c["id"], {"nodes": [node("upload", nid="u", files=[aid]), node("image", nid="g", prompt="aumente o tamanho do título", mode=mode)], "edges": [edge("u", "g", "refs")]})
        seen = {}

        class Fake:
            supports_refs = True
            refs_edit_only = True
            label = "Fake"
            edit_mode = False

            def max_refs(self, model=""):
                return 4

            def refs_need_edit(self, model=""):
                return False

            def frames_edit_for(self, model=""):
                return frames

            def image(self, prompt, *, refs=(), **k):
                seen["prompt"] = prompt
                return [M.Media(src if answer == "same" else proc.image("outra coisa", "96x96", 9), "image/png")]

        events = []
        with mock.patch.object(E, "build_media", lambda *a, **k: Fake()):
            E.CanvasEngine(store, c["id"], events.append).run(None, False)
        return seen["prompt"], [w for e in events for w in (e.get("warnings") or [])]

    def test_the_edit_request_becomes_a_clear_instruction_only_in_edit_mode(self):
        prompt, _ = self.run_edit("edit", "other")
        self.assertIn("aumente o tamanho do título", prompt)
        self.assertTrue(prompt.startswith("Edit the provided reference image."))
        self.assertIn("keep everything else exactly the same", prompt)
        prompt, _ = self.run_edit("generate", "other")
        self.assertEqual(prompt, "aumente o tamanho do título")   # ao gerar, o texto vai como está
        prompt, _ = self.run_edit("edit", "other", frames=False)
        self.assertEqual(prompt, "aumente o tamanho do título")   # modelos que editam por imagem inicial (strength) também não recebem a moldura

    def test_an_edit_that_changed_nothing_is_reported(self):
        _, warns = self.run_edit("edit", "same")
        self.assertTrue([w for w in warns if "quase igual à imagem de entrada" in w], warns)
        _, warns = self.run_edit("edit", "other")
        self.assertFalse([w for w in warns if "quase igual" in w], warns)

    def test_image_difference(self):
        from openflow.canvas import procedural as proc

        a, b = proc.image("a", "96x96", 1), proc.image("b", "96x96", 2)
        self.assertEqual(M.image_difference(a, a), 0.0)
        self.assertGreater(M.image_difference(a, b), 0.05)
        self.assertIsNone(M.image_difference(b"nao e imagem", a))


if __name__ == "__main__":
    unittest.main()
