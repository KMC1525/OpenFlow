"""v0.58: 3D 2 — três nós novos (Textura 3D, Esqueleto 3D e Animação 3D) e o visualizador que mostra textura, esqueleto e animação."""
import json
import math
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from openflow.canvas import mesh3d, schema
from openflow.canvas import model3d_ops as ops
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def demo(prompt="vaso"):
    return ops.read_model(mesh3d.encode(mesh3d.demo_mesh(prompt), "glb"))


def standing_figure():
    """Um «boneco» de caixas em pé: pernas, tronco, braços ao lado e cabeça (2 unidades de altura)."""
    verts, faces = [], []

    def box(x0, x1, y0, y1, z0, z1):
        b = len(verts)
        verts.extend([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
        for a, c, d in ((0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)):
            faces.append((b + a, b + c, b + d))
    box(-0.20, -0.04, 0.0, 0.95, -0.08, 0.08)       # perna esquerda (-x)
    box(0.04, 0.20, 0.0, 0.95, -0.08, 0.08)         # perna direita (+x)
    box(-0.22, 0.22, 0.95, 1.55, -0.10, 0.10)       # tronco
    box(-0.42, -0.26, 0.95, 1.50, -0.07, 0.07)      # braço esquerdo
    box(0.26, 0.42, 0.95, 1.50, -0.07, 0.07)        # braço direito
    box(-0.12, 0.12, 1.60, 1.95, -0.12, 0.12)       # cabeça
    m = ops.Model()
    m.verts, m.faces = verts, faces
    return m


class ReadWriteTests(unittest.TestCase):
    def test_a_plain_model_round_trips_with_colors(self):
        m = demo()
        d = ops.write_glb(m)
        info = mesh3d.glb_info(d)                          # o mesmo validador do envio de arquivos
        self.assertEqual((info["vertices"], info["triangles"], info["colors"]), (len(m.verts), len(m.faces), True))
        r = ops.read_model(d)
        self.assertEqual((len(r.verts), len(r.faces)), (len(m.verts), len(m.faces)))
        self.assertAlmostEqual(r.verts[10][1], m.verts[10][1], places=5)
        self.assertIsNone(r.skin)
        self.assertEqual(r.animations, [])

    def test_obj_with_texture_coordinates_and_garbage(self):
        o = ops.read_model(b"v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nf 1/1 2/2 3/3 4/4\n")
        self.assertEqual((len(o.verts), len(o.faces), o.uvs is not None), (4, 2, True))
        for bad in (b"nada", b"\xff\xfe", b"v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 9\n", b"glTF" + b"\x00" * 40):
            with self.assertRaises(ValueError):
                ops.read_model(bad)

    def test_a_foreign_glb_with_node_transforms_is_flattened(self):
        from tests.test_3d_audio_v053 import TRI, glb, simple
        doc, blob = simple(nodes=[{"mesh": 0}, {"mesh": 0, "translation": [10, 0, 0]}], meshes=[{"primitives": [{"attributes": {"POSITION": 0}}]}])
        doc["scenes"] = [{"nodes": [0, 1]}]
        m = ops.read_model(glb(doc, blob))
        self.assertEqual((len(m.verts), len(m.faces)), (6, 2))
        self.assertAlmostEqual(max(v[0] for v in m.verts), 11.0)

    def test_everything_survives_a_write_and_read(self):
        m = ops.texturize(demo(), None, "box", 2, 0, "bricks", size=64)
        m = ops.auto_rig(m, "spine", 5)
        m = ops.animate(m, "sway", 3)
        r = ops.read_model(ops.write_glb(m))
        self.assertEqual(len(r.joints), 5)
        self.assertEqual([j.parent for j in r.joints], [-1, 0, 1, 2, 3])
        self.assertTrue(r.texture and r.texture[:4] == b"\x89PNG" and r.uvs is not None and len(r.uvs) == len(r.verts))
        self.assertEqual(len(r.skin), len(r.verts))
        self.assertEqual(len(r.animations), 1)
        self.assertEqual(len(r.animations[0]["tracks"]), 4)         # sway: uma trilha por junta que não é a raiz
        self.assertAlmostEqual(r.animations[0]["duration"], 3.0, places=3)
        self.assertEqual(mesh3d.glb_info(ops.write_glb(m))["vertices"], len(m.verts))


class RigTests(unittest.TestCase):
    def test_styles_and_joint_counts(self):
        m = demo()
        self.assertEqual(len(ops.auto_rig(m, "humanoid").joints), 21)
        self.assertEqual([j.name for j in ops.auto_rig(m, "spine", 4).joints], ["coluna_0", "coluna_1", "coluna_2", "coluna_3"])
        self.assertEqual(len(ops.auto_rig(m, "chain", 7).joints), 7)
        self.assertEqual(len(ops.auto_rig(m, "estilo-inexistente").joints), 21)      # estilo inválido: humanoide
        self.assertEqual(len(ops.auto_rig(m, "spine", 999).joints), ops.MAX_JOINTS)
        self.assertEqual(len(ops.auto_rig(m, "spine", 1).joints), 2)

    def test_the_skin_is_a_valid_blend(self):
        r = ops.auto_rig(demo(), "spine", 6)
        for js, ws in r.skin:
            self.assertAlmostEqual(sum(ws), 1.0, places=6)
            self.assertTrue(all(w >= 0 for w in ws))
            self.assertTrue(all(0 <= j < 6 for j in js))
            self.assertEqual(len(set(j for j, w in zip(js, ws) if w > 0)), len([w for w in ws if w > 0]))

    def test_vertices_follow_the_nearest_bone(self):
        r = ops.auto_rig(demo(), "spine", 6)
        lo, hi = r.bbox()
        top = max(range(len(r.verts)), key=lambda i: r.verts[i][1])
        bottom = min(range(len(r.verts)), key=lambda i: r.verts[i][1])
        dom = lambda i: r.skin[i][0][max(range(4), key=lambda k: r.skin[i][1][k])]    # noqa: E731
        share = lambda i, ids: sum(w for j, w in zip(*r.skin[i]) if j in ids)    # noqa: E731
        self.assertIn(dom(top), (4, 5))                                   # a ponta de cima fica entre as duas últimas juntas (empate no osso do topo)
        self.assertGreater(share(top, (4, 5)), 0.8)
        self.assertEqual(dom(bottom), 0)
        self.assertGreater(share(bottom, (0, 1)), 0.8)

    def test_humanoid_binds_each_limb_to_its_own_joints(self):
        r = ops.auto_rig(standing_figure(), "humanoid")
        names = [j.name for j in r.joints]
        dom = lambda i: names[r.skin[i][0][max(range(4), key=lambda k: r.skin[i][1][k])]]    # noqa: E731
        by_pos = lambda x, y: min(range(len(r.verts)), key=lambda i: (r.verts[i][0] - x) ** 2 + (r.verts[i][1] - y) ** 2 + r.verts[i][2] ** 2)    # noqa: E731
        self.assertIn(dom(by_pos(-0.12, 0.02)), ("pe_e", "ponta_e", "canela_e"))       # pé esquerdo (-x)
        self.assertIn(dom(by_pos(0.12, 0.02)), ("pe_d", "ponta_d", "canela_d"))
        self.assertIn(dom(by_pos(0.34, 1.0)), ("mao_d", "antebraco_d", "braco_d"))       # mão direita (+x)
        self.assertIn(dom(by_pos(0.0, 1.92)), ("cabeca", "pescoco"))
        self.assertTrue(all(j.parent < k for k, j in enumerate(r.joints)))             # pais antes dos filhos

    def test_limits_and_replacement(self):
        big = demo()
        big.verts = big.verts * 700            # 420 mil vértices
        with self.assertRaises(ValueError) as cm:
            ops.auto_rig(big)
        self.assertIn("vértices demais", str(cm.exception))
        a = ops.animate(ops.auto_rig(demo(), "spine", 3), "sway")
        b = ops.auto_rig(a, "chain", 4)
        self.assertEqual((len(b.joints), b.animations), (4, []))                       # animações do esqueleto antigo saem
        self.assertEqual(len(a.joints), 3)                                              # a entrada não é alterada


class AnimateTests(unittest.TestCase):
    def test_every_whole_model_animation_loops(self):
        m = demo()
        for kind in ("spin", "bounce", "float", "pulse", "wobble"):
            a = ops.animate(m, kind, 2.0)
            clip = a.animations[0]
            self.assertEqual(clip["name"], kind)
            self.assertEqual(clip["duration"], 2.0)
            for tr in clip["tracks"]:
                self.assertEqual(tr["target"], ("root", 0))
                self.assertEqual(tr["times"][0], 0.0)
                self.assertEqual(tr["times"][-1], 2.0)
                self.assertTrue(all(b > a_ for a_, b in zip(tr["times"], tr["times"][1:])))
                if tr["path"] == "rotation":
                    f, l = tr["values"][0], tr["values"][-1]
                    self.assertAlmostEqual(abs(sum(x * y for x, y in zip(f, l))), 1.0, places=6)      # o último quadro é o primeiro (mesma rotação)
                else:
                    for x, y in zip(tr["values"][0], tr["values"][-1]):
                        self.assertAlmostEqual(x, y, places=6)

    def test_skeleton_animations_need_a_skeleton(self):
        for kind in ops.NEEDS_SKELETON:
            with self.assertRaises(ValueError) as cm:
                ops.animate(demo(), kind)
            self.assertIn("esqueleto", str(cm.exception))
        with self.assertRaises(ValueError) as cm:
            ops.animate(ops.auto_rig(demo(), "spine", 4), "walk")
        self.assertIn("Humanoide", str(cm.exception))
        with self.assertRaises(ValueError):
            ops.animate(ops.auto_rig(demo(), "spine", 4), "wave")

    def test_humanoid_animations_move_the_right_joints(self):
        h = ops.auto_rig(standing_figure(), "humanoid")
        names = [j.name for j in h.joints]
        walk = ops.animate(h, "walk", 2.0).animations[0]["tracks"]
        moved = {names[t["target"][1]] for t in walk}
        self.assertTrue({"coxa_e", "coxa_d", "canela_e", "braco_e", "braco_d", "quadril"} <= moved)
        wave = ops.animate(h, "wave", 2.0).animations[0]["tracks"]
        self.assertEqual({names[t["target"][1]] for t in wave}, {"braco_d", "antebraco_d"})
        idle = ops.animate(h, "idle", 2.0).animations[0]["tracks"]
        self.assertEqual({names[t["target"][1]] for t in idle}, {"peito", "cabeca"})

    def test_with_a_skeleton_the_whole_model_moves_by_the_root_joint(self):
        r = ops.auto_rig(demo(), "spine", 4)
        a = ops.animate(r, "spin", 2.0)
        self.assertEqual(a.animations[0]["tracks"][0]["target"], ("joint", 0))
        v0, _ = ops.pose(a, 0.0)
        v1, _ = ops.pose(a, 0.5)                          # um quarto de volta em torno de y
        i = max(range(len(v0)), key=lambda k: v0[k][0])
        self.assertAlmostEqual(v1[i][0], v0[i][0] * math.cos(math.pi / 2) + (v0[i][2]) * math.sin(math.pi / 2), delta=0.08)

    def test_parameters_are_clamped_and_the_input_is_kept(self):
        m = demo()
        self.assertEqual(ops.animate(m, "spin", 9999).animations[0]["duration"], 60.0)
        self.assertEqual(ops.animate(m, "spin", 0).animations[0]["duration"], 0.2)
        self.assertEqual(ops.animate(m, "coisa-estranha").animations[0]["name"], "spin")
        self.assertEqual(m.animations, [])
        a = ops.animate(ops.animate(m, "spin"), "bounce")
        self.assertEqual([c["name"] for c in a.animations], ["bounce"])               # uma animação por modelo: a nova substitui a antiga

    def test_the_written_glb_is_valid_gltf(self):
        a = ops.animate(ops.auto_rig(standing_figure(), "humanoid"), "walk", 1.5)
        d = ops.write_glb(a)
        n = struct.unpack("<I", d[12:16])[0]
        doc = json.loads(d[20:20 + n])
        self.assertEqual(len(doc["skins"][0]["joints"]), 21)
        for ch in doc["animations"][0]["channels"]:
            self.assertLess(ch["target"]["node"], len(doc["nodes"]))
            smp = doc["animations"][0]["samplers"][ch["sampler"]]
            self.assertEqual(doc["accessors"][smp["input"]]["count"], doc["accessors"][smp["output"]]["count"])
            self.assertEqual(smp["interpolation"], "LINEAR")
        att = doc["meshes"][0]["primitives"][0]["attributes"]
        self.assertEqual(doc["accessors"][att["JOINTS_0"]]["componentType"], 5123)
        self.assertEqual(doc["accessors"][att["WEIGHTS_0"]]["type"], "VEC4")
        self.assertEqual(doc["accessors"][doc["skins"][0]["inverseBindMatrices"]]["type"], "MAT4")
        self.assertEqual(len(d) % 4, 0)
        self.assertEqual(struct.unpack("<I", d[8:12])[0], len(d))


class TextureTests(unittest.TestCase):
    def test_projections_give_valid_uvs(self):
        m = demo()
        for proj in ops.PROJECTIONS:
            t = ops.texturize(m, None, proj, 1, 0, "checker", size=64)
            self.assertEqual(len(t.uvs), len(t.verts), proj)
            self.assertTrue(all(math.isfinite(u) and math.isfinite(v) for u, v in t.uvs), proj)
            self.assertTrue(all(max(f) < len(t.verts) for f in t.faces), proj)
            if proj in ("cylindrical", "spherical"):      # nenhum triângulo «volta» a textura (u espalhado por mais de meia volta)
                for f in t.faces:
                    us = [t.uvs[i][0] for i in f]
                    self.assertLessEqual(max(us) - min(us), 0.5 + 1e-9, proj)
        self.assertGreater(len(ops.texturize(m, None, "box").verts), len(m.verts))      # a caixa duplica vértices

    def test_tile_and_rotation_change_the_uvs(self):
        m = demo()
        a = ops.texturize(m, None, "planar", 1, 0, size=64).uvs
        b = ops.texturize(m, None, "planar", 4, 0, size=64).uvs
        c = ops.texturize(m, None, "planar", 1, 90, size=64).uvs
        self.assertAlmostEqual(max(u for u, _ in b) - min(u for u, _ in b), 4 * (max(u for u, _ in a) - min(u for u, _ in a)), places=4)
        self.assertNotEqual(a[5], c[5])

    def test_patterns_are_real_pngs(self):
        seen = set()
        for pat in ops.PATTERNS:
            png = ops.pattern_png(pat, "#ff0000", "#0000ff", 64, 1)
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", png[16:24]), (64, 64))
            seen.add(png)
        self.assertEqual(len(seen), len(ops.PATTERNS))         # cada padrão é diferente
        self.assertNotEqual(ops.pattern_png("noise", "#000000", "#ffffff", 64, 1), ops.pattern_png("noise", "#000000", "#ffffff", 64, 2))

    def test_an_image_is_embedded_as_is_and_the_material_is_set(self):
        png = ops.pattern_png("stripes", "#00ff00", "#000000", 32)
        t = ops.texturize(demo(), png, "planar", tint="#ff8000", metallic=0.4, roughness=0.3)
        self.assertEqual(t.texture, png)
        self.assertEqual(t.tint, (1.0, 128 / 255.0, 0.0, 1.0))
        self.assertEqual((t.metallic, t.roughness), (0.4, 0.3))
        self.assertIsNone(t.colors)                                    # as cores por vértice saem
        self.assertIsNotNone(ops.texturize(demo(), png, "planar", keep_colors=True).colors)
        d = ops.write_glb(t)
        n = struct.unpack("<I", d[12:16])[0]
        doc = json.loads(d[20:20 + n])
        self.assertEqual(doc["images"][0]["mimeType"], "image/png")
        self.assertEqual(doc["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"], 0)
        self.assertIn("TEXCOORD_0", doc["meshes"][0]["primitives"][0]["attributes"])

    def test_the_skin_follows_duplicated_vertices(self):
        r = ops.auto_rig(demo(), "spine", 4)
        t = ops.texturize(r, None, "box", size=64)
        self.assertEqual(len(t.skin), len(t.verts))
        self.assertGreater(len(t.verts), len(r.verts))
        self.assertEqual(len(t.joints), 4)


class NodeTests(unittest.TestCase):
    def test_palette_and_specs(self):
        self.assertIn(("3D", ["model3d", "tex3d", "rig3d", "anim3d"]), schema.PALETTE)
        for k in ("tex3d", "rig3d", "anim3d"):
            t = schema.NODE_TYPES[k]
            self.assertEqual(t["out"], "model3d")
            self.assertEqual(t["ins"][0][0], "model")
            self.assertIsInstance(schema.normalize_params(k, {}), dict)
        self.assertEqual(schema.NODE_TYPES["tex3d"]["ins"][1][0], "image")
        self.assertTrue(schema.compatible("media", ["model3d"]))        # o nó Mídia (GLB/OBJ enviado) liga nas portas 3D
        self.assertTrue(schema.compatible("model3d", ["model3d"]))
        self.assertFalse(schema.compatible("image", ["model3d"]))

    def test_parameters_are_clamped(self):
        n = schema.normalize_params
        self.assertEqual(n("rig3d", {"style": "x", "bones": 999, "smooth": 5}), {"style": "humanoid", "bones": 32, "smooth": 1})
        self.assertEqual(n("anim3d", {"kind": "walk", "duration": 0, "amplitude": 99}), {"kind": "walk", "duration": 0.5, "amplitude": 3})
        t = n("tex3d", {"projection": "x", "tile": 0, "rotate": 9999, "color1": "azul", "size": 5, "roughness": 3})
        self.assertEqual((t["projection"], t["tile"], t["rotate"], t["color1"], t["size"], t["roughness"]), ("box", 0.25, 359, "#c8c8c8", 128, 1))

    @unittest.skipUnless(FF, "sem ffmpeg")
    def test_a_chain_texture_skeleton_animation_runs_in_the_engine(self):
        from PIL import Image
        import io
        tmp = Path(tempfile.mkdtemp())
        store = Store(tmp)
        cs = store.projects
        cid = cs.create("3d2")["id"]
        glb = cs.add_asset(cid, mesh3d.encode(mesh3d.demo_mesh("vaso"), "glb"), "glb", "model3d", name="vaso.glb", mime="model/gltf-binary", provider="upload")
        b = io.BytesIO()
        Image.new("RGB", (64, 64), "orange").save(b, "PNG")
        img = cs.add_asset(cid, b.getvalue(), "png", "image", name="tex.png", mime="image/png", provider="upload")
        nodes = [{"id": "u", "type": "upload", "x": 0, "y": 0, "params": {"files": [glb["id"]]}}, {"id": "i", "type": "upload", "x": 0, "y": 0, "params": {"files": [img["id"]]}},
                 {"id": "t", "type": "tex3d", "x": 0, "y": 0, "params": {"projection": "cylindrical"}}, {"id": "r", "type": "rig3d", "x": 0, "y": 0, "params": {"style": "spine", "bones": 5}},
                 {"id": "x", "type": "anim3d", "x": 0, "y": 0, "params": {"kind": "sway", "duration": 2}}]
        edges = [{"from": "u", "to": "t", "port": "model"}, {"from": "i", "to": "t", "port": "image"}, {"from": "t", "to": "r", "port": "model"}, {"from": "r", "to": "x", "port": "model"}]
        cs.save_layout(cid, {"nodes": nodes, "edges": edges})
        ev = []
        CanvasEngine(store, cid, ev.append, lambda: False).run(None, True)
        errs = [e.get("message") for e in ev if e.get("type") == "node" and e.get("state") == "error"]
        self.assertEqual(errs, [])
        cur = cs.get(cid)
        res = {n["id"]: n["result"] for n in cur["nodes"]}
        for nid in ("t", "r", "x"):
            self.assertEqual(res[nid]["state"], "done", nid)
        final = next(a for a in cur["assets"] if a["id"] == res["x"]["assets"][0])
        self.assertEqual((final["kind"], final["mime"]), ("model3d", "model/gltf-binary"))
        m = ops.read_model(cs.asset_path(cid, final["file"]).read_bytes())
        self.assertEqual((len(m.joints), len(m.animations), m.animations[0]["name"]), (5, 1, "sway"))
        self.assertTrue(m.texture and m.texture[:4] == b"\x89PNG" and m.uvs is not None)              # a textura veio do nó anterior e continuou até o fim
        tex_only = next(a for a in cur["assets"] if a["id"] == res["t"]["assets"][0])
        self.assertEqual(ops.read_model(cs.asset_path(cid, tex_only["file"]).read_bytes()).joints, [])  # cada etapa só acrescenta a sua parte
        # avisos úteis e erro amigável
        nodes[4]["params"] = {"kind": "walk"}
        cs.save_layout(cid, {"nodes": nodes[:2] + [nodes[2]], "edges": edges[:2]})
        cs.save_layout(cid, {"nodes": [nodes[0], {"id": "x", "type": "anim3d", "x": 0, "y": 0, "params": {"kind": "walk"}}], "edges": [{"from": "u", "to": "x", "port": "model"}]})
        ev = []
        CanvasEngine(store, cid, ev.append, lambda: False).run(None, True)
        msg = " ".join(e.get("message") or "" for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("state") == "error")
        self.assertIn("esqueleto", msg)
        cs.save_layout(cid, {"nodes": [{"id": "x", "type": "rig3d", "x": 0, "y": 0, "params": {}}], "edges": []})
        ev = []
        CanvasEngine(store, cid, ev.append, lambda: False).run(None, True)
        msg = " ".join(e.get("message") or "" for e in ev if e.get("type") == "node" and e.get("id") == "x" and e.get("state") == "error")
        self.assertIn("Ligue um modelo 3D", msg)


@unittest.skipUnless(NODE, "sem node")
class ViewerPoseTests(unittest.TestCase):
    """O visualizador (JS, rodando de verdade em Node) tem de calcular a mesma pose que a referência em Python."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())

    def js(self, model, times):
        p = self.tmp / "m.glb"
        p.write_bytes(ops.write_glb(model))
        r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "model_pose_check.mjs"), str(p), *[str(t) for t in times]], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-600:])
        return json.loads(r.stdout)

    def assertSamePose(self, model, times):
        out = self.js(model, times)
        for t in times:
            v, j = ops.pose(model, t)
            got = out["poses"][str(t)]["pos"]
            self.assertEqual(len(got), 3 * len(v))
            worst = max(abs(got[3 * i + k] - v[i][k]) for i in range(len(v)) for k in range(3))
            self.assertLess(worst, 2e-4, f"t={t}: pior diferença {worst}")
            if j:
                gj = out["poses"][str(t)]["joints"]
                self.assertLess(max(abs(gj[i][k] - j[i][k]) for i in range(len(j)) for k in range(3)), 2e-4)
        return out

    def test_the_reader_finds_joints_animation_and_texture(self):
        m = ops.texturize(demo(), None, "cylindrical", size=64)
        m = ops.animate(ops.auto_rig(m, "humanoid"), "walk", 2.0)
        s = self.js(m, [0])["summary"]
        self.assertEqual(s["joints"], 21)
        self.assertEqual(s["jointNames"][0], "quadril")
        self.assertEqual(s["parents"][0], -1)
        self.assertEqual(s["texture"]["mime"], "image/png")
        self.assertTrue(s["uv"])
        self.assertEqual(s["anim"]["duration"], 2.0)
        self.assertTrue(all(t["joint"] >= 0 for t in s["anim"]["tracks"]))
        self.assertEqual(self.js(demo(), [0])["summary"]["joints"], 0)

    def test_rest_pose_equals_the_model(self):
        r = ops.auto_rig(demo(), "spine", 6)
        out = self.js(r, [0])
        got = out["poses"]["0"]["pos"]
        self.assertLess(max(abs(got[3 * i + k] - r.verts[i][k]) for i in range(len(r.verts)) for k in range(3)), 1e-4)     # IBM e juntas coerentes: a pele não deforma o repouso

    def test_whole_model_animations_match_the_reference(self):
        for kind in ("spin", "bounce", "float", "pulse", "wobble"):
            self.assertSamePose(ops.animate(demo(), kind, 2.0), [0, 0.37, 0.5, 1.1, 1.99, 2.4])

    def test_skinned_animations_match_the_reference(self):
        self.assertSamePose(ops.animate(ops.auto_rig(demo(), "spine", 6), "sway", 3.0), [0, 0.4, 1.0, 2.2])
        self.assertSamePose(ops.animate(ops.auto_rig(demo(), "chain", 5), "spin", 2.0), [0, 0.5, 1.3])
        h = ops.auto_rig(standing_figure(), "humanoid")
        for kind in ("walk", "wave", "idle"):
            self.assertSamePose(ops.animate(h, kind, 2.0), [0, 0.3, 0.8, 1.7])

    def test_poses_really_move(self):
        a = ops.animate(ops.auto_rig(demo(), "spine", 6), "sway", 3.0)
        out = self.js(a, [0, 0.75])
        d = max(abs(x - y) for x, y in zip(out["poses"]["0"]["pos"], out["poses"]["0.75"]["pos"]))
        self.assertGreater(d, 0.02)
        s = ops.animate(demo(), "spin", 4.0)
        out = self.js(s, [0, 1])
        p0, p1 = out["poses"]["0"]["pos"], out["poses"]["1"]["pos"]
        i = max(range(len(p0) // 3), key=lambda k: p0[3 * k])             # o vértice mais à direita (+x) vai para -z depois de um quarto de volta
        self.assertAlmostEqual(p1[3 * i + 2], -p0[3 * i], delta=0.02)


if __name__ == "__main__":
    unittest.main()
