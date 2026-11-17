"""v0.74: «Testando tudo» — cada nó do OpenFlow roda de verdade (motor + ffmpeg + provedor Demo) com entradas comuns e difíceis (imagem JPEG de 333×517, vídeo de 321×241 sem áudio, imagem de 17×9), com cada opção de cada
campo; e os nós de imagem e vídeo são exercitados nos dois modos (gerar e editar) com 0 a 5 referências, vários tamanhos e proporções, em provedores de mentira que registram o que recebem.

Uma execução pode falhar só com uma mensagem de validação que explica o que fazer («Escreva o texto a procurar…», «ligue um nó Esqueleto 3D…», «o vídeo não tem áudio»): isso é o esperado e fica numa lista fechada.
Qualquer outra falha (erro do ffmpeg, exceção, arquivo vazio, vídeo com dimensão ímpar) é um defeito."""
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import media as M
from openflow.canvas import mesh3d, schema
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
SKIP = {"text", "upload", "style_prompt", "style_folder", "in_url"}                      # sem execução própria / pedem a internet
MULTI2 = ("img_collage", "vid_join", "aud_mix")                                          # pedem ao menos duas entradas
BASE = {"text_extract": {"what": "numbers"}, "img_text": {"text": "Olá"}, "in_random": {"lines": "a\nb\nc"}, "text_template": {"template": "X {1}"}}
EXPECTED = re.compile(r"Escreva o (texto a procurar|padrão)|Não achei nada no texto|precisa de um esqueleto|passa do fim|não tem áudio|ficou vazio|antes do início|bibliotecas opcionais")


def option_table():
    """Cada opção de cada campo `_pick(p.get("campo"), (opções…), padrão)` de `nodes_ext`/`schema`, lida do código (assim um campo novo entra no teste sozinho)."""
    import ast

    out = {}
    for name in ("nodes_ext", "schema"):
        mod = __import__(f"openflow.canvas.{name}", fromlist=["x"])
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) and node.test.left.id in ("t", "ntype") \
                    and isinstance(node.test.ops[0], ast.Eq) and isinstance(node.test.comparators[0], ast.Constant):
                for call in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_pick" and len(call.args) >= 3 and isinstance(call.args[0], ast.Call) \
                            and getattr(call.args[0].func, "attr", "") == "get" and isinstance(call.args[0].args[0], ast.Constant):
                        try:
                            vals = list(eval(compile(ast.Expression(call.args[1]), "x", "eval"), vars(mod)))
                        except Exception:  # noqa: BLE001
                            continue
                        out.setdefault(node.test.comparators[0].value, {})[call.args[0].args[0].value] = vals
    return out


class NormalizeEveryNodeTests(unittest.TestCase):
    def test_no_node_crashes_on_hostile_values(self):
        hostile = (None, "", "x", -10 ** 9, 10 ** 9, 0, float("nan"), float("inf"), [], {}, [1, 2], {"a": 1}, True, "NaN", "1e999")
        for t in schema.NODE_TYPES:
            base = schema.normalize_params(t, {})
            self.assertIsInstance(base, dict, t)
            for key in list(base):
                for v in hostile:
                    out = schema.normalize_params(t, {key: v})
                    self.assertIsInstance(out, dict, f"{t}.{key}={v!r}")
            self.assertIsInstance(schema.normalize_params(t, None), dict, t)
            self.assertIsInstance(schema.normalize_params(t, "texto"), dict, t)

    def test_every_option_the_code_offers_normalizes_to_itself(self):
        for t, fields in option_table().items():
            for key, vals in fields.items():
                for v in vals:
                    self.assertEqual(schema.normalize_params(t, {key: v}).get(key), v, f"{t}.{key}={v}")

    def test_the_option_table_is_not_empty(self):
        table = option_table()
        self.assertGreater(len(table), 25)
        self.assertGreater(sum(len(v) for v in table.values()), 50)


@unittest.skipUnless(FF, "sem ffmpeg")
class EveryNodeEveryOptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image

        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("tudo")["id"]
        cls.sets = {}

        def ff(name, args):
            p = cls.tmp / name
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(p)], check=True)
            return p

        def add(path, kind, mime):
            return cls.cs.add_asset(cls.cid, path.read_bytes(), path.suffix.lstrip("."), kind, name=path.name, mime=mime, provider="upload")

        def make(tag, w, h, vw, vh, audio, fmt):
            b = io.BytesIO()
            im = Image.new("RGB", (w, h), "orange")
            for x in range(0, w, 7):
                im.putpixel((x, x % h), (0, 0, 255))
            im.save(b, fmt)
            ext = fmt.lower().replace("jpeg", "jpg")
            img = cls.cs.add_asset(cls.cid, b.getvalue(), ext, "image", name=f"{tag}.{ext}", mime="image/" + ("jpeg" if ext == "jpg" else ext), provider="upload")
            even = vw % 2 == 0 and vh % 2 == 0
            args = ["-f", "lavfi", "-i", f"testsrc=size={vw}x{vh}:rate=24:duration=2"] + (["-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "aac"] if audio else []) \
                + (["-c:v", "libx264", "-pix_fmt", "yuv420p"] if even else ["-c:v", "mpeg4"])
            vid = add(ff(f"{tag}.mp4", args), "video", "video/mp4")
            aud = add(ff(f"{tag}.mp3", ["-f", "lavfi", "-i", "sine=frequency=880:duration=3", "-c:a", "libmp3lame"]), "audio", "audio/mpeg")
            glb = cls.cs.add_asset(cls.cid, mesh3d.encode(mesh3d.demo_mesh("vaso"), "glb"), "glb", "model3d", name="v.glb", mime="model/gltf-binary", provider="upload")
            cls.sets[tag] = {
                "text": {"id": "s_text", "type": "text", "params": {"text": "Uma floresta ao amanhecer, névoa suave. Contato ana@ex.com #luz 12"}},
                "image": {"id": "s_image", "type": "upload", "params": {"files": [img["id"]]}}, "video": {"id": "s_video", "type": "upload", "params": {"files": [vid["id"]]}},
                "audio": {"id": "s_audio", "type": "upload", "params": {"files": [aud["id"]]}}, "style": {"id": "s_style", "type": "style_prompt", "params": {"text": "aquarela suave"}},
                "model3d": {"id": "s_model3d", "type": "upload", "params": {"files": [glb["id"]]}}}
        make("normal", 640, 360, 640, 360, True, "PNG")
        make("odd", 333, 517, 321, 241, False, "JPEG")                                    # imagem retrato JPEG; vídeo de dimensão ímpar e sem áudio
        make("tiny", 17, 9, 64, 36, True, "PNG")
        cls.options = option_table()

    def graph(self, t, tag, params):
        spec, src = schema.NODE_TYPES[t], self.sets[tag]
        nodes = {"x": {"id": "x", "type": t, "x": 0, "y": 0, "params": dict(BASE.get(t, {}), **params)}}
        edges = []
        for pid, _label, accepts, multi in spec["ins"]:
            kind = "style" if pid == "style" else next((k for k in ("text", "image", "video", "audio", "model3d") if k in accepts), "image" if "media" in accepts else None)
            if kind is None:
                continue
            if kind == "text" and t in ("image", "video", "sound", "voice", "model3d", "llm") and pid not in ("prompt", "text"):
                continue
            nodes[src[kind]["id"]] = {**src[kind], "x": 0, "y": 0}
            edges.append({"id": "e_" + pid, "from": src[kind]["id"], "to": "x", "port": pid})
            if multi and t in MULTI2:
                nodes["s2"] = {**src[kind], "id": "s2", "x": 0, "y": 0}
                edges.append({"id": "e2", "from": "s2", "to": "x", "port": pid})
        return list(nodes.values()), edges

    def run_node(self, t, tag, params):
        nodes, edges = self.graph(t, tag, params)
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": edges})
        CanvasEngine(self.store, self.cid, lambda e: None, lambda: False).run(None, True)
        cur = self.cs.get(self.cid)
        res = next(x for x in cur["nodes"] if x["id"] == "x")["result"]
        if res["state"] != "done":
            return None if EXPECTED.search(res["error"]) else f"{res['state']}: {res['error'][:200]}"
        out = schema.NODE_TYPES[t]["out"]
        if out in ("image", "video", "audio", "model3d", "media") and t != "out_gallery":   # a Galeria só mostra o que recebe
            if not res["assets"]:
                return "sem arquivo"
            for aid in res["assets"]:
                a = next(x for x in cur["assets"] if x["id"] == aid)
                path = self.cs.asset_path(self.cid, a["file"])
                if not path or path.stat().st_size == 0:
                    return "arquivo vazio"
                if a["kind"] == "video":
                    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type", "-of", "json", str(path)], capture_output=True, text=True)
                    if r.returncode != 0:
                        return "vídeo ilegível"
                    for s in json.loads(r.stdout)["streams"]:
                        if s["codec_type"] == "video" and (s["width"] % 2 or s["height"] % 2) and t not in ("vid_audio", "dub"):   # «Áudio no vídeo» e «Dublagem» copiam o vídeo sem recodificar: mantêm a dimensão da entrada
                            return f"vídeo com dimensão ímpar {s['width']}x{s['height']}"
                elif a["kind"] == "image":
                    from PIL import Image

                    with Image.open(path) as im:
                        im.load()
        elif out == "text" and not res["text"].strip():
            return "texto vazio"
        return None

    def test_every_node_runs_with_the_defaults_on_every_input_set(self):
        problems = []
        for t in schema.NODE_TYPES:
            if t in SKIP:
                continue
            for tag in self.sets:
                msg = self.run_node(t, tag, {})
                if msg:
                    problems.append((t, tag, msg))
        self.assertEqual(problems, [])

    def test_every_option_of_every_field_on_the_hostile_inputs(self):
        problems = []
        n = 0
        for t, fields in self.options.items():
            if t in SKIP or t not in schema.NODE_TYPES:
                continue
            for key, vals in fields.items():
                for v in vals:
                    n += 1
                    msg = self.run_node(t, "odd", {key: v})
                    if msg:
                        problems.append((t, key, v, msg))
        self.assertGreater(n, 50)
        self.assertEqual(problems, [])

    def test_extreme_numbers_are_clamped_not_crashed_on_the_nodes_that_edit_media(self):
        problems = []
        light = ("img_resize", "img_crop", "img_text", "img_collage", "img_watermark", "img_filter", "aud_trim", "aud_fx")        # o máximo só nos nós rápidos (um vídeo repetido 20× demora)
        heavy = ("vid_trim", "vid_speed", "vid_reframe", "vid_loop", "vid_slideshow", "vid_look")
        for t in light + heavy:
            for key, val in schema.normalize_params(t, {}).items():
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    for ext in ((-10 ** 9, 10 ** 9) if t in light else (-10 ** 9,)):
                        msg = self.run_node(t, "normal", {key: ext})
                        if msg:
                            problems.append((t, key, ext, msg))
        self.assertEqual(problems, [])


class Fake(M.MediaProvider):
    """Provedor de mentira de imagem e vídeo que anota o que recebe."""
    id, label, caps = "fake", "Falso", ("image", "video")
    supports_refs = True

    def __init__(self, refs_edit_only=False, cap=4):
        self.cfg, self.ctl, self.edit_mode, self.seen = {}, None, False, []
        self.refs_edit_only, self.cap = refs_edit_only, cap

    def max_refs(self, model=""):
        return self.cap

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        from PIL import Image

        self.seen.append(("image", prompt, size, count, len(refs)))
        b = io.BytesIO()
        Image.new("RGB", (8, 8), "red").save(b, "PNG")
        return [M.Media(b.getvalue(), "image/png") for _ in range(count)]

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        self.seen.append(("video", prompt, duration, aspect, image is not None))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "o.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=12:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
            return M.Media(out.read_bytes(), "video/mp4")


@unittest.skipUnless(FF, "sem ffmpeg")
class ImageAndVideoGenerateAndEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image

        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("iv")["id"]
        cls.imgs = {}
        for tag, (w, h, fmt, mode) in {"png": (640, 360, "PNG", "RGB"), "jpg": (333, 517, "JPEG", "RGB"), "webp": (200, 200, "WEBP", "RGB"), "tiny": (17, 9, "PNG", "RGB"), "big": (2600, 1500, "PNG", "RGB"), "alpha": (100, 100, "PNG", "RGBA")}.items():
            b = io.BytesIO()
            Image.new(mode, (w, h), (0, 128, 128, 90) if mode == "RGBA" else "teal").save(b, fmt)
            ext = fmt.lower().replace("jpeg", "jpg")
            cls.imgs[tag] = cls.cs.add_asset(cls.cid, b.getvalue(), ext, "image", name=f"{tag}.{ext}", mime="image/" + ("jpeg" if ext == "jpg" else ext), provider="upload")
        v = cls.tmp / "v.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(v)], check=True)
        cls.vid = cls.cs.add_asset(cls.cid, v.read_bytes(), "mp4", "video", name="v.mp4", mime="video/mp4", provider="upload")

    def run_graph(self, nodes, edges, prov=None):
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": edges})
        ev = []
        ctx = mock.patch.object(CanvasEngine, "_provider", lambda self, node: (prov, "fake", "fake-model")) if prov is not None else mock.patch.object(CanvasEngine, "_noop", create=True)
        with ctx:
            CanvasEngine(self.store, self.cid, ev.append, lambda: False).run(None, True)
        cur = self.cs.get(self.cid)
        res = next(x for x in cur["nodes"] if x["id"] == "x")["result"]
        warns = [w for e in ev if e.get("type") == "node" and e.get("id") == "x" for w in e.get("warnings", [])]
        return res, warns

    def up(self, *assets):
        return {"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [a["id"] for a in assets]}}

    def image_graph(self, mode, size, refs, count):
        nodes = [{"id": "x", "type": "image", "x": 0, "y": 0, "params": {"prompt": "um gato", "mode": mode, "size": size, "count": count}}]
        edges = []
        if refs:
            nodes.append(self.up(*[self.vid if r == "vid" else self.imgs[r] for r in refs]))
            edges.append({"id": "e", "from": "u", "to": "x", "port": "refs"})
        return nodes, edges

    def test_image_node_generate_and_edit_on_every_provider(self):
        providers = {"demo": None, "fake": Fake(), "fake_edit_only": Fake(refs_edit_only=True), "fake_one_ref": Fake(cap=1)}
        refsets = ([], ["png"], ["jpg", "webp"], ["tiny"], ["big"], ["alpha"], ["png", "jpg", "webp", "tiny", "alpha"], ["vid"])
        problems = []
        for pname, prov in providers.items():
            for mode in ("generate", "edit"):
                for size in ("512x512", "1024x576", "576x1024", "2560x1080"):
                    for refs in refsets:
                        count = 2 if (size == "512x512" and len(refs) == 1) else 1
                        nodes, edges = self.image_graph(mode, size, refs, count)
                        res, warns = self.run_graph(nodes, edges, prov)
                        tag = (pname, mode, size, tuple(refs))
                        if mode == "edit" and not refs:
                            if res["state"] == "done":
                                problems.append((*tag, "o modo Editar sem imagem deveria recusar"))
                            elif "ligue uma imagem" not in res["error"].lower():
                                problems.append((*tag, res["error"][:120]))
                            continue
                        if res["state"] != "done":
                            problems.append((*tag, res["state"], res["error"][:140]))
                        elif len(res["assets"]) != count:
                            problems.append((*tag, f"esperava {count} imagem(ns), veio {len(res['assets'])}"))
        self.assertEqual(problems, [])

    def test_the_references_reach_the_provider_in_the_right_number(self):
        five = ["png", "jpg", "webp", "tiny", "alpha"]
        for cap, want_edit, want_gen in ((4, 4, 4), (1, 1, 1)):
            prov = Fake(cap=cap)
            nodes, edges = self.image_graph("edit", "512x512", five, 1)
            res, warns = self.run_graph(nodes, edges, prov)
            self.assertEqual(prov.seen[-1][4], want_edit)
            self.assertTrue(any("usa só" in w for w in warns))                                 # o corte vem com aviso
        prov = Fake(refs_edit_only=True)                                                      # só edita por referência: no modo Gerar elas viram texto, com aviso
        nodes, edges = self.image_graph("generate", "512x512", ["png"], 1)
        res, warns = self.run_graph(nodes, edges, prov)
        self.assertEqual(prov.seen[-1][4], 0)
        self.assertTrue(any("só usa imagens de referência no modo Editar" in w for w in warns))
        prov = Fake(refs_edit_only=True)
        nodes, edges = self.image_graph("edit", "512x512", ["png"], 1)
        self.run_graph(nodes, edges, prov)
        self.assertEqual(prov.seen[-1][4], 1)

    def test_the_style_reaches_the_prompt_in_generate_and_edit(self):
        for mode in ("generate", "edit"):
            prov = Fake()
            nodes, edges = self.image_graph(mode, "512x512", ["png"], 1)
            nodes.append({"id": "s", "type": "style_prompt", "x": 0, "y": 0, "params": {"text": "aquarela suave", "global": True}})
            self.run_graph(nodes, edges, prov)
            self.assertIn("Style guide (the look of the whole result", prov.seen[-1][1], mode)
            self.assertIn("aquarela suave", prov.seen[-1][1], mode)

    def test_video_node_with_and_without_a_start_image_on_every_provider(self):
        problems = []
        for pname, prov in {"demo": None, "fake": Fake()}.items():
            for aspect in ("16:9", "9:16", "1:1"):
                for dur in (1, 30):
                    for start in (None, "alpha", "tiny", "vid"):
                        nodes = [{"id": "x", "type": "video", "x": 0, "y": 0, "params": {"prompt": "ondas", "duration": dur, "aspect": aspect}}]
                        edges = []
                        if start:
                            nodes.append(self.up(self.vid if start == "vid" else self.imgs[start]))
                            edges.append({"id": "e", "from": "u", "to": "x", "port": "image"})
                        res, _ = self.run_graph(nodes, edges, prov)
                        if res["state"] != "done":
                            problems.append((pname, aspect, dur, start, res["error"][:140]))
        self.assertEqual(problems, [])

    def test_video_prompt_alone_or_image_alone_and_neither(self):
        res, _ = self.run_graph([{"id": "x", "type": "video", "x": 0, "y": 0, "params": {"prompt": "", "duration": 2}}], [], Fake())
        self.assertEqual(res["state"], "error")
        self.assertIn("prompt", res["error"].lower())
        nodes = [{"id": "x", "type": "video", "x": 0, "y": 0, "params": {"prompt": "", "duration": 2}}, self.up(self.imgs["png"])]
        res, _ = self.run_graph(nodes, [{"id": "e", "from": "u", "to": "x", "port": "image"}], Fake())
        self.assertEqual(res["state"], "done")                                                   # só a imagem inicial basta


@unittest.skipUnless(FF, "sem ffmpeg")
class SubtitleOffsetTests(unittest.TestCase):
    def test_an_offset_that_pushes_every_cue_before_zero_is_explained(self):
        from tests.test_speech_v062 import FakeSpeech, Project, node

        pj = Project([])
        pj.cs.save_layout(pj.cid, {"nodes": [pj.upload("u", "a"), node("s", "sub", offset=-30)], "edges": [{"from": "u", "to": "s", "port": "media"}]})
        pj.run(FakeSpeech())
        err = pj.errors()["s"]
        self.assertIn("antes do início", err)                                                    # antes: «Não encontrei fala para legendar» (mentira: a fala existia)
        self.assertIn("-30", err)
        pj.cs.save_layout(pj.cid, {"nodes": [pj.upload("u", "a"), node("s", "sub", offset=-1)], "edges": [{"from": "u", "to": "s", "port": "media"}]})
        pj.run(FakeSpeech())
        self.assertEqual(pj.errors(), {})


if __name__ == "__main__":
    unittest.main()
