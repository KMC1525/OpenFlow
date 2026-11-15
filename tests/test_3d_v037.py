"""v0.37: modelos 3D locais — malhas (GLB/OBJ), nó «Modelo 3D», roteamento das famílias (Shap-E, TripoSR, Hunyuan3D) e integração com o motor."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import installed, media as M, mesh3d, schema
from openflow.canvas.engine import CanvasEngine
from openflow.providers.base import ProviderError
from openflow.storage import Store
from tests.helpers import ServerCase

PNG = None


def tiny_png() -> bytes:
    import io

    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (64, 64), "orange").save(b, "PNG")
    return b.getvalue()


class MeshTests(unittest.TestCase):
    def test_glb_is_a_valid_gltf_with_colors(self):
        v, f, c = mesh3d.demo_mesh("um vaso azul", 3)
        data = mesh3d.encode((v, f, c), "glb")
        info = mesh3d.glb_info(data)
        self.assertEqual(info["vertices"], len(v))
        self.assertEqual(info["triangles"], len(f))
        self.assertTrue(info["colors"])
        self.assertEqual(M.sniff_mime(data), "model/gltf-binary")
        self.assertEqual(len(data) % 4, 0)

    def test_mesh_is_centered_and_fits_a_cube(self):
        v, f, c = mesh3d.demo_mesh("cubo")
        out = mesh3d.fit_unit([(x + 50, y * 3 + 7, z) for x, y, z in v])
        for i in range(3):
            lo, hi = min(p[i] for p in out), max(p[i] for p in out)
            self.assertLessEqual(hi - lo, 2.0 + 1e-6)
            self.assertAlmostEqual((lo + hi) / 2, 0.0, places=5)

    def test_obj_text(self):
        v, f, c = mesh3d.demo_mesh("bola")
        txt = mesh3d.encode((v, f, c), "obj").decode()
        self.assertEqual(sum(1 for ln in txt.splitlines() if ln.startswith("v ")), len(v))
        self.assertEqual(sum(1 for ln in txt.splitlines() if ln.startswith("f ")), len(f))
        self.assertIn("f 1 ", txt.split("\n", len(v) + 1)[-1] + "f 1 ")

    def test_invalid_meshes_are_refused(self):
        with self.assertRaises(ValueError):
            mesh3d.to_glb([], [])
        with self.assertRaises(ValueError):
            mesh3d.as_lists([(0, 0, 0)], [(0, 1, 2)])
        with self.assertRaises(ValueError):
            mesh3d.glb_info(b"nope")

    def test_demo_is_deterministic_and_shapes_follow_the_prompt(self):
        self.assertEqual(mesh3d.demo_mesh("bola", 1)[0], mesh3d.demo_mesh("bola", 1)[0])
        self.assertNotEqual(mesh3d.demo_mesh("bola", 1)[0], mesh3d.demo_mesh("bola", 2)[0])
        for word, shape in (("uma rosca", "torus"), ("a cube", "cube"), ("vaso", "vase"), ("árvore", "cone"), ("bola", "sphere")):
            self.assertEqual(mesh3d.demo_shape(word), shape)
        for shape_prompt in ("rosca", "cubo", "cone", "vaso", "bola"):
            v, f, _ = mesh3d.demo_mesh(shape_prompt)
            self.assertTrue(v and f and max(i for t in f for i in t) < len(v), shape_prompt)

    def test_numpy_like_inputs_are_converted(self):
        class Arr:
            def __init__(self, x):
                self.x = x

            def detach(self):
                return self

            def cpu(self):
                return self

            def tolist(self):
                return self.x

        v, f, c = mesh3d.as_lists(Arr([[0, 0, 0], [1, 0, 0], [0, 1, 0]]), Arr([[0, 1, 2]]), Arr([[2, 0, 0.5]] * 3))
        self.assertEqual((len(v), len(f), c[0]), (3, 1, (1.0, 0.0, 0.5)))   # as cores ficam entre 0 e 1

    def test_families(self):
        self.assertEqual([mesh3d.family(m) for m in ("openai/shap-e", "openai/shap-e-img2img", "stabilityai/TripoSR", "tencent/Hunyuan3D-2mini", "x/y")], ["shap-e", "shap-e", "triposr", "hunyuan3d", ""])
        self.assertTrue(mesh3d.needs_image("stabilityai/TripoSR"))
        self.assertTrue(mesh3d.needs_image("tencent/Hunyuan3D-2"))
        self.assertFalse(mesh3d.needs_image("openai/shap-e"))
        self.assertTrue(mesh3d.is_img2img("openai/shap-e-img2img"))


class ProviderTests(unittest.TestCase):
    def test_registry_lists_3d_for_demo_and_local_hf_only(self):
        self.assertIn("model3d", M.MEDIA_PRESETS["demo"]["caps"])
        self.assertIn("model3d", M.MEDIA_PRESETS["local_hf"]["caps"])
        self.assertNotIn("model3d", M.MEDIA_PRESETS["gguf_local"]["caps"])
        self.assertEqual(M.MEDIA_PRESETS["local_hf"]["models"]["model3d"], "openai/shap-e")
        self.assertIn("stabilityai/TripoSR", M.MEDIA_PRESETS["local_hf"]["suggest"]["model3d"])
        self.assertEqual(M.pick_provider({"media": {"active": {"model3d": "demo"}}}, "model3d"), "demo")
        with self.assertRaises(ProviderError):
            M.pick_provider({}, "model3d", "gguf_local")

    def test_demo_produces_glb_and_obj(self):
        d = M.DemoMedia({"id": "demo"})
        g = d.model3d("um vaso", seed=1)
        self.assertEqual((g.mime, g.ext, g.kind), ("model/gltf-binary", "glb", "model3d"))
        self.assertGreater(mesh3d.glb_info(g.data)["triangles"], 100)
        o = d.model3d("um vaso", fmt="obj")
        self.assertEqual((o.mime, o.ext), ("model/obj", "obj"))
        self.assertNotEqual(d.model3d("x", image=(tiny_png(), "image/png")).data, d.model3d("x").data)  # com imagem o resultado muda

    def test_other_providers_refuse_3d_clearly(self):
        with self.assertRaises(ProviderError) as cm:
            M.GGUFMedia({"id": "gguf_local"}).model3d("x")
        self.assertIn("3D", str(cm.exception))

    def local(self):
        p = M.LocalHFMedia({"id": "local_hf", "models": {"model3d": "openai/shap-e"}})
        p._pick = lambda cap, model, default: model or default   # sem baixar nada de verdade
        return p

    def test_local_routing_shap_e_text_and_image(self):
        p = self.local()
        calls = []
        with mock.patch.object(M.LocalHFMedia, "_mesh_shape", lambda self, model, prompt, pil, seed, extra: calls.append((model, prompt, pil is not None)) or mesh3d.demo_mesh("x")):
            self.assertEqual(p.model3d("um gato", model="openai/shap-e").mime, "model/gltf-binary")
            p.model3d("", image=(tiny_png(), "image/png"), model="openai/shap-e")
        self.assertEqual(calls[0], ("openai/shap-e", "um gato", False))
        self.assertEqual(calls[1], ("openai/shap-e-img2img", "", True))   # com imagem usa a versão img2img
        with self.assertRaises(ProviderError) as cm:
            p.model3d("texto", model="openai/shap-e-img2img")
        self.assertIn("imagem", str(cm.exception))

    def test_local_image_only_models_need_an_image(self):
        p = self.local()
        self.assertTrue(p.model3d_needs_image("stabilityai/TripoSR"))
        self.assertFalse(p.model3d_needs_image("openai/shap-e"))
        for m in ("stabilityai/TripoSR", "tencent/Hunyuan3D-2mini"):
            with self.assertRaises(ProviderError) as cm:
                p.model3d("só texto", model=m)
            self.assertIn("imagem", str(cm.exception))
        with mock.patch.object(M.LocalHFMedia, "_mesh_tsr", lambda self, model, pil, extra: mesh3d.demo_mesh("tsr")), \
                mock.patch.object(M.LocalHFMedia, "_mesh_hunyuan", lambda self, model, pil, seed, extra: mesh3d.demo_mesh("hy")):
            for m in ("stabilityai/TripoSR", "tencent/Hunyuan3D-2mini"):
                self.assertTrue(p.model3d("", image=(tiny_png(), "image/png"), model=m, fmt="obj").mime == "model/obj")

    def test_unknown_model_and_unreadable_image(self):
        p = self.local()
        with self.assertRaises(ProviderError) as cm:
            p.model3d("x", model="alguem/modelo-qualquer")
        self.assertIn("Shap-E", str(cm.exception))
        with self.assertRaises(ProviderError):
            p.model3d("x", image=(b"nao e imagem", "image/png"), model="openai/shap-e")

    def test_missing_libraries_explain_how_to_install(self):
        p = self.local()
        import builtins

        real = builtins.__import__

        def no(name, *a, **k):
            if name in ("tsr.system", "hy3dgen.shapegen") or name.startswith(("tsr", "hy3dgen")):
                raise ImportError(name)
            return real(name, *a, **k)

        with mock.patch.object(M.LocalHFMedia, "_ready", lambda self, model: {}), mock.patch("builtins.__import__", no):
            for m, hint in (("stabilityai/TripoSR", "TripoSR"), ("tencent/Hunyuan3D-2mini", "Hunyuan3D")):
                with self.assertRaises(ProviderError) as cm:
                    p.model3d("", image=(tiny_png(), "image/png"), model=m)
                self.assertIn(hint, str(cm.exception))
                self.assertIn("pip install", str(cm.exception))

    def test_installed_list_separates_3d_models(self):
        fake = [{"model": "openai/shap-e", "precision": "fp16"}, {"model": "stabilityai/sd-turbo", "precision": "fp16"}]
        with mock.patch.object(installed, "downloaded_hf_models", lambda: fake):
            d3 = [i["model"] for i in installed.installed({}, Path("."), "model3d")]
            im = [i["model"] for i in installed.installed({}, Path("."), "sound")]
        self.assertEqual(d3, ["openai/shap-e"])
        self.assertEqual(im, ["stabilityai/sd-turbo"])


class SchemaTests(unittest.TestCase):
    def test_node_type_palette_and_params(self):
        self.assertIn("model3d", schema.NODE_TYPES)
        self.assertEqual(schema.NODE_TYPES["model3d"]["out"], "model3d")
        self.assertIn(("3D", ["model3d"]), schema.PALETTE)
        self.assertIn("model3d", schema.CAPS)
        self.assertIn("model3d", schema.KINDS)
        p = schema.normalize_params("model3d", {"format": "zzz", "provider": "openai", "model": "x", "seed": -3, "prompt": "p"})
        self.assertEqual((p["format"], p["provider"], p["model"], p["seed"]), ("glb", "", "", 0))
        self.assertEqual(schema.normalize_params("model3d", {"format": "obj"})["format"], "obj")

    def test_gallery_accepts_3d(self):
        ins = dict((i[0], i[2]) for i in schema.NODE_TYPES["out_gallery"]["ins"])
        self.assertIn("model3d", ins["items"])
        self.assertTrue(schema.compatible("model3d", ins["items"]))
        self.assertFalse(schema.compatible("model3d", ["image"]))

    def test_js_lists_know_the_node(self):
        js = Path(__file__).resolve().parent.parent / "openflow" / "web" / "js"
        src = (js / "canvas_nodes.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(src.count("model3d"), 8)
        self.assertTrue((js / "model_viewer.js").is_file())


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("3d")["id"]

    def run_graph(self, nodes, edges=()):
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": list(edges)})
        ev = []
        CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        return ev

    def node(self, t, params=None, nid="x"):
        return {"id": nid, "type": t, "x": 0, "y": 0, "params": params or {}}

    def asset_of(self, nid="x"):
        cur = self.cs.get(self.cid)
        n = next(n for n in cur["nodes"] if n["id"] == nid)
        return n, [next(a for a in cur["assets"] if a["id"] == i) for i in n["result"]["assets"]]

    def test_text_to_3d_saves_a_glb_asset(self):
        ev = self.run_graph([self.node("model3d", {"prompt": "um vaso de cerâmica"})])
        self.assertEqual([e for e in ev if e.get("state") == "error"], [])
        n, assets = self.asset_of()
        self.assertEqual((n["result"]["state"], len(assets), assets[0]["kind"], assets[0]["mime"]), ("done", 1, "model3d", "model/gltf-binary"))
        data = self.cs.asset_path(self.cid, assets[0]["file"]).read_bytes()
        self.assertGreater(mesh3d.glb_info(data)["vertices"], 100)
        self.assertEqual(assets[0]["provider"], "demo")

    def test_prompt_comes_from_a_linked_text_and_obj_format(self):
        txt = {"id": "t", "type": "text", "x": 0, "y": 0, "params": {"text": "uma bola"}}
        self.run_graph([txt, self.node("model3d", {"format": "obj"})], [{"from": "t", "to": "x", "port": "prompt"}])
        _, assets = self.asset_of()
        self.assertEqual((assets[0]["mime"], assets[0]["file"].endswith(".obj")), ("model/obj", True))

    def test_image_to_3d_and_gallery(self):
        a = self.cs.add_asset(self.cid, tiny_png(), "png", "image", name="f.png", mime="image/png")
        up = {"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [a["id"]]}}
        gal = self.node("out_gallery", {}, "g")
        ev = self.run_graph([up, self.node("model3d", {}), gal], [{"from": "u", "to": "x", "port": "image"}, {"from": "x", "to": "g", "port": "items"}])
        self.assertEqual([e for e in ev if e.get("state") == "error"], [])
        _, assets = self.asset_of("g")
        self.assertEqual([x["kind"] for x in assets], ["model3d"])

    def test_empty_node_explains_what_is_missing(self):
        ev = self.run_graph([self.node("model3d", {})])
        msg = " ".join(e.get("message", "") for e in ev if e.get("state") == "error")
        self.assertIn("prompt", msg)

    def test_text_goes_through_an_image_first_for_image_only_models(self):
        seen = {}

        class Fake(M.DemoMedia):
            def model3d_needs_image(self, model=""):
                return True

            def model3d(self, prompt, *, image=None, model="", seed=0, fmt="glb", extra=None):
                seen["image"] = image
                return super().model3d(prompt, image=image, model=model, seed=seed, fmt=fmt)

        import openflow.canvas.engine as E

        real = E.build_media
        with mock.patch.object(E, "build_media", lambda settings, pid, ctl=None, models_dir=None: Fake({"id": "demo"}, ctl) if pid == "demo" else real(settings, pid, ctl, models_dir)):
            ev = self.run_graph([self.node("model3d", {"prompt": "uma xícara"})])
        self.assertEqual([e for e in ev if e.get("state") == "error"], [])
        self.assertIsNotNone(seen["image"])
        self.assertTrue(seen["image"][1].startswith("image/"))
        done = [e for e in ev if e.get("id") == "x" and e.get("state") == "done"][-1]
        self.assertTrue(any("duas etapas" in w or "virou uma imagem" in w for w in done.get("warnings", [])))


class ApiTests(ServerCase):
    def test_settings_and_installed_and_hub_accept_3d(self):
        s, r = self.c.json("GET", "/api/media/installed?cap=model3d")
        self.assertEqual((s, r["cap"]), (200, "model3d"))
        s, r = self.c.json("GET", "/api/media/providers")
        self.assertIn("model3d", next(p for p in r["providers"] if p["id"] == "local_hf")["caps"])
        self.assertEqual(r["active"].get("model3d"), "demo")
        s, _ = self.c.json("GET", "/api/hub/search?cap=model3d&q=")
        self.assertNotEqual(s, 400)   # a busca no Hugging Face pode falhar sem rede (502), mas o tipo vale
        s, r = self.c.json("POST", "/api/media/hub/use", {"cap": "model3d", "provider": "local_hf", "model": "openai/shap-e"})
        self.assertEqual(s, 200)
        self.assertEqual(self.c.json("GET", "/api/media/providers")[1]["active"]["model3d"], "local_hf")
        self.c.json("PUT", "/api/settings", {"media": {"active": {"model3d": "demo"}}})

    def test_a_generated_glb_is_served_and_listed_in_the_library(self):
        s, p = self.c.json("POST", "/api/projects", {"name": "3D", "template": "blank"})
        data = mesh3d.encode(mesh3d.demo_mesh("cubo"), "glb")
        s, a = self.c.json("POST", f"/api/projects/{p['id']}/assets", raw=data, headers={"X-Filename": "m.glb", "Content-Type": "model/gltf-binary"})
        self.assertEqual((s, a["kind"]), (201, "model3d"))
        st, h, body = self.c.req("GET", f"/api/projects/{p['id']}/assets/{a['file']}")
        self.assertEqual(st, 200)
        self.assertEqual(body[:4], b"glTF")
        self.assertIn("model/gltf-binary", json.dumps(dict(h)).lower() if not isinstance(h, str) else h.lower())
        s, r = self.c.json("GET", "/api/library/files?kind=model3d&source=all")
        self.assertTrue(any(f["kind"] == "model3d" for f in r["files"]))


if __name__ == "__main__":
    unittest.main()
