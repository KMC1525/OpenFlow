"""v0.53: bugs ao gerar e editar sons, vozes e modelos 3D — leitura de GLB/OBJ (Python e visualizador), envio de OBJ, voz de demonstração com números, áudio com NaN e transparência nos modelos 3D."""
import io
import json
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from PIL import Image

from openflow.canvas import media, mesh3d
from openflow.canvas import procedural as proc
from tests.helpers import ServerCase

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def glb(doc, blob=b"", trailing=b""):
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\x00" * (-len(blob) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + (struct.pack("<II", len(blob), 0x004E4942) + blob if blob else b"")
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body + trailing


def f32(*v):
    return struct.pack("<%df" % len(v), *v)


TRI = f32(0, 0, 0, 1, 0, 0, 0, 1, 0)


def simple(mode=None, indices=None, extra_attr=None, nodes=None, meshes=None, blob=TRI, acc=None, views=None):
    prim = {"attributes": {"POSITION": 0, **(extra_attr or {})}}
    if mode is not None:
        prim["mode"] = mode
    if indices is not None:
        prim["indices"] = indices
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes or [{"mesh": 0}], "meshes": meshes or [{"primitives": [prim]}],
           "accessors": acc or [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}], "bufferViews": views or [{"buffer": 0, "byteOffset": 0, "byteLength": len(blob)}], "buffers": [{"byteLength": len(blob)}]}
    return doc, blob


class GlbInfoTests(unittest.TestCase):
    def test_our_own_glb_still_validates(self):
        v, f, c = mesh3d.demo_mesh("rosca")
        info = mesh3d.glb_info(mesh3d.encode((v, f, c), "glb"))
        self.assertEqual((info["vertices"], info["triangles"], info["colors"]), (len(v), len(f), True))

    def test_a_primitive_without_indices_is_valid(self):
        info = mesh3d.glb_info(glb(*simple()))      # antes: KeyError → «Esse arquivo não é um modelo 3D GLB válido»
        self.assertEqual((info["vertices"], info["triangles"]), (3, 1))

    def test_every_mesh_is_counted_and_trailing_bytes_are_tolerated(self):
        doc, blob = simple(meshes=[{"primitives": [{"attributes": {"POSITION": 0}}]}, {"primitives": [{"attributes": {"POSITION": 0}}]}], nodes=[{"mesh": 0}, {"mesh": 1}])
        doc["scenes"] = [{"nodes": [0, 1]}]
        self.assertEqual(mesh3d.glb_info(glb(doc, blob, trailing=b"\x00\x00\x00\x00"))["triangles"], 2)

    def test_points_only_or_garbage_is_rejected(self):
        with self.assertRaises(ValueError):
            mesh3d.glb_info(glb(*simple(mode=0)))
        for bad in (b"glTF" + b"\x00" * 40, b"", b"glTF\x02\x00\x00\x00"):
            with self.assertRaises((ValueError, KeyError, IndexError, TypeError, struct.error)):
                mesh3d.glb_info(bad)


class ObjTests(unittest.TestCase):
    OBJ = b"# cubo\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\nf -4 -3 -2\n"

    def test_obj_info_counts_quads_and_negative_indices(self):
        self.assertEqual(mesh3d.obj_info(self.OBJ), {"vertices": 4, "triangles": 3, "colors": False})
        self.assertTrue(mesh3d.looks_like_obj(self.OBJ))
        self.assertTrue(mesh3d.obj_info(mesh3d.encode(mesh3d.demo_mesh("x"), "obj"))["colors"])

    def test_invalid_objs_are_rejected(self):
        for bad in (b"v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 9\n", b"v 0 0 0\nv 1 0\nv 1 1 0\nf 1 2 3\n", b"v 0 0 0\nv 1 0 0\nv 1 1 0\n", b"v 0 0 0\nv a b c\nv 1 1 0\nf 1 2 3\n", b"\xff\xfe\x00bin", b"v 0 0 0\nv 1 0 0\nv 1 1 0\nf 0 1 2\n"):
            with self.assertRaises((ValueError, IndexError)):
                mesh3d.obj_info(bad)
        self.assertFalse(mesh3d.looks_like_obj(b"Ola, isto e so um texto normal.\nSem malha.\n"))
        self.assertFalse(mesh3d.looks_like_obj(b"\x00" * 50))


class UploadTests(ServerCase):
    def test_obj_is_accepted_as_a_3d_model_and_text_is_not(self):
        s, p = self.c.json("POST", "/api/projects", {"name": "3D", "template": "blank"})
        s, a = self.c.json("POST", f"/api/projects/{p['id']}/assets", raw=ObjTests.OBJ, headers={"X-Filename": "cubo.obj"})
        self.assertEqual((s, a["kind"], a["mime"]), (201, "model3d", "model/obj"))
        self.assertTrue(a["file"].endswith(".obj"))
        s, e = self.c.json("POST", f"/api/projects/{p['id']}/assets", raw=b"v 0 0 0\nv 1 0 0\nv 1 1 0\nf 1 2 9\n", headers={"X-Filename": "ruim.obj"})
        self.assertEqual(s, 400)
        self.assertIn("OBJ", e["error"])
        s, e = self.c.json("POST", f"/api/projects/{p['id']}/assets", raw=b"apenas texto\n", headers={"X-Filename": "a.txt"})
        self.assertEqual(s, 400)

    def test_glb_without_indices_can_be_uploaded(self):
        s, p = self.c.json("POST", "/api/projects", {"name": "3D2", "template": "blank"})
        s, a = self.c.json("POST", f"/api/projects/{p['id']}/assets", raw=glb(*simple()), headers={"X-Filename": "tri.glb"})
        self.assertEqual((s, a["kind"]), (201, "model3d"))


@unittest.skipUnless(NODE, "sem node")
class ViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())

    def parse(self, **files):
        paths = []
        for name, data in files.items():
            p = self.tmp / name
            p.write_bytes(data)
            paths.append(str(p))
        r = subprocess.run([NODE, str(ROOT / "tests" / "js" / "model_viewer_check.mjs"), *paths], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        return json.loads(r.stdout)

    def test_the_demo_glb_and_obj_read_back(self):
        mesh = mesh3d.demo_mesh("vaso")
        out = self.parse(**{"a.glb": mesh3d.encode(mesh, "glb"), "a.obj": mesh3d.encode(mesh, "obj")})
        for k in ("a.glb", "a.obj"):
            self.assertEqual((out[k]["vertices"], out[k]["triangles"]), (len(mesh[0]), len(mesh[1])), k)
            self.assertLess(out[k]["maxIndex"], out[k]["vertices"])
            self.assertIsNotNone(out[k]["colors"])

    def test_no_indices_strip_fan_and_uint16(self):
        blob = f32(0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0)
        acc4 = [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"}]
        out = self.parse(**{"noidx.glb": glb(*simple()),
                            "strip.glb": glb(*simple(mode=5, blob=blob, acc=acc4)),
                            "fan.glb": glb(*simple(mode=6, blob=blob, acc=acc4)),
                            "points.glb": glb(*simple(mode=0))})
        self.assertEqual(out["noidx.glb"]["triangles"], 1)
        self.assertEqual(out["strip.glb"]["triangles"], 2)
        self.assertEqual(out["fan.glb"]["triangles"], 2)
        self.assertIn("error", out["points.glb"])
        idx16 = struct.pack("<3H", 0, 1, 2) + b"\x00\x00"
        doc, b = simple(indices=1, blob=TRI + idx16, acc=[{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}, {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"}],
                        views=[{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 6}])
        self.assertEqual(self.parse(**{"u16.glb": glb(doc, b)})["u16.glb"]["triangles"], 1)

    def test_all_meshes_and_node_transforms_are_used(self):
        doc, blob = simple(nodes=[{"mesh": 0}, {"mesh": 0, "translation": [10, 0, 0]}], meshes=[{"primitives": [{"attributes": {"POSITION": 0}}]}])
        doc["scenes"] = [{"nodes": [0, 1]}]
        r = self.parse(**{"two.glb": glb(doc, blob)})["two.glb"]
        self.assertEqual((r["vertices"], r["triangles"]), (6, 2))
        self.assertAlmostEqual(r["minX"], 0.0)
        self.assertAlmostEqual(r["maxX"], 11.0)          # a 2ª instância foi deslocada 10 em x (antes só a 1ª malha, sem transformação)
        doc, blob = simple(nodes=[{"children": [1], "scale": [2, 2, 2]}, {"mesh": 0, "translation": [1, 0, 0]}])
        self.assertAlmostEqual(self.parse(**{"nest.glb": glb(doc, blob)})["nest.glb"]["maxX"], 4.0)     # (1·2)+ translação 1 → escala do pai aplicada: x = 2*1 + 2*1

    def test_normalized_byte_colors_and_material_color(self):
        col = bytes([255, 0, 0, 255] * 3)
        acc = [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}, {"bufferView": 1, "componentType": 5121, "count": 3, "type": "VEC4", "normalized": True}]
        doc, b = simple(extra_attr={"COLOR_0": 1}, blob=TRI + col, acc=acc, views=[{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 12}])
        self.assertEqual(self.parse(**{"col.glb": glb(doc, b)})["col.glb"]["colors"], [1.0, 0.0, 0.0])      # antes: 255 (tudo estourava para branco)
        doc, b = simple()
        doc["materials"] = [{"pbrMetallicRoughness": {"baseColorFactor": [0.2, 0.4, 0.6, 1]}}]
        doc["meshes"][0]["primitives"][0]["material"] = 0
        self.assertEqual(self.parse(**{"mat.glb": glb(doc, b)})["mat.glb"]["colors"], [0.2, 0.4, 0.6])

    def test_obj_negative_indices_quads_crlf_and_bad_faces(self):
        obj = b"v 0 0 0\r\nv 1 0 0\r\nv 1 1 0\r\nv 0 1 0\r\nf 1/1/1 2/2/2 3/3/3 4/4/4\r\nf -3 -2 -1\r\nf 1 2 99\r\n"
        r = self.parse(**{"q.obj": obj})["q.obj"]
        self.assertEqual((r["vertices"], r["triangles"]), (4, 3))       # o quadrilátero vira 2, o negativo 1 e a face inválida é ignorada
        self.assertIn("error", self.parse(**{"vazio.obj": b"# nada\n"})["vazio.obj"])

    def test_garbage_glb_gives_a_clear_error(self):
        r = self.parse(**{"x.glb": b"glTF" + b"\x02\x00\x00\x00" + b"\x10\x00\x00\x00" + b"\x00" * 40})["x.glb"]
        self.assertIn("error", r)


class SoundVoiceTests(unittest.TestCase):
    @staticmethod
    def peak(data):
        import array
        with wave.open(io.BytesIO(data)) as w:
            s = array.array("h", w.readframes(w.getnframes()))
            return max((abs(x) for x in s), default=0), w.getnframes() / w.getframerate()

    def test_demo_voice_speaks_numbers_and_symbols(self):
        for text in ("1234567890", "50% de $20 & #tag", "123"):
            pk, dur = self.peak(proc.babble(text))
            self.assertGreater(pk, 1000, text)             # antes: silêncio total
            self.assertGreater(dur, 0.2, text)
        self.assertEqual(self.peak(proc.babble("... ..."))[0], 0)     # só pausas continua mudo
        self.assertGreater(self.peak(proc.babble("a" * 2500))[1], 100)   # antes só os 1200 primeiros caracteres eram falados

    def test_demo_music_can_be_one_second(self):
        self.assertAlmostEqual(self.peak(proc.music("calmo", 1.0))[1], 1.0, delta=0.05)         # antes: mínimo de 2 s
        self.assertAlmostEqual(self.peak(proc.music("calmo", 5.0))[1], 5.0, delta=0.05)

    def test_wav_from_array_survives_nan_and_empty(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("sem numpy")
        pcm = media._wav_from_array(np.array([0.1, float("nan"), float("inf"), -float("inf"), 0.5], dtype="float32"), 16000)
        with wave.open(io.BytesIO(pcm)) as w:
            self.assertEqual(w.getnframes(), 5)
        with self.assertRaises(media.ProviderError):
            media._wav_from_array(np.array([], dtype="float32"), 16000)
        with wave.open(io.BytesIO(media._wav_from_array(np.float32(0.3), 8000))) as w:      # escalar solto
            self.assertEqual(w.getnframes(), 1)

    def test_transparent_reference_keeps_alpha_only_for_3d_models(self):
        b = io.BytesIO()
        Image.new("RGBA", (6, 6), (255, 0, 0, 0)).save(b, "PNG")
        data = b.getvalue()
        self.assertEqual(media.open_rgb(data).mode, "RGB")
        self.assertEqual(media.open_rgb(data, keep_alpha=True).mode, "RGBA")
        b = io.BytesIO()
        Image.new("RGBA", (6, 6), (255, 0, 0, 255)).save(b, "PNG")
        self.assertEqual(media.open_rgb(b.getvalue(), keep_alpha=True).mode, "RGB")        # opaco: sem alfa, o modelo remove o fundo sozinho
        self.assertEqual(media._pil_refs([(data, "image/png")], 1, keep_alpha=True)[0].mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
