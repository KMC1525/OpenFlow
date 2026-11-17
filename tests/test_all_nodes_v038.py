"""v0.38: TODOS os tipos de nó rodam de verdade (motor + ffmpeg + provedor Demo) com entradas válidas ligadas; só o «Transcrever» pode falhar, e só por faltar a biblioteca opcional do Whisper."""
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from openflow.canvas import schema
from openflow.canvas.engine import CanvasEngine
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
MULTI2 = ("img_collage", "vid_join", "aud_mix")                       # pedem ao menos duas entradas
SKIP = {"text", "upload", "style_prompt", "style_folder", "in_url", "ai_model"}    # sem execução própria / pedem a internet / pedem um arquivo de modelo (o ai_model é testado em test_modelrun_v082)
PARAMS = {"text_extract": {"what": "numbers"}, "img_text": {"text": "Olá"}, "in_random": {"lines": "a\nb\nc"}, "text_template": {"template": "X {1}"}}


@unittest.skipUnless(FF, "sem ffmpeg")
class EveryNodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image

        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        cls.cid = cls.cs.create("todos")["id"]

        def ff(name, args):
            p = cls.tmp / name
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, str(p)], check=True)
            return p

        b = io.BytesIO()
        Image.new("RGB", (640, 360), "orange").save(b, "PNG")
        img = cls.cs.add_asset(cls.cid, b.getvalue(), "png", "image", name="a.png", mime="image/png", provider="upload")
        v = ff("v.mp4", ["-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=2", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"])
        vid = cls.cs.add_asset(cls.cid, v.read_bytes(), "mp4", "video", name="v.mp4", mime="video/mp4", provider="upload")
        a = ff("a.mp3", ["-f", "lavfi", "-i", "sine=frequency=880:duration=3", "-c:a", "libmp3lame"])
        aud = cls.cs.add_asset(cls.cid, a.read_bytes(), "mp3", "audio", name="a.mp3", mime="audio/mpeg", provider="upload")
        from openflow.canvas import mesh3d

        glb = cls.cs.add_asset(cls.cid, mesh3d.encode(mesh3d.demo_mesh("vaso"), "glb"), "glb", "model3d", name="vaso.glb", mime="model/gltf-binary", provider="upload")
        cls.src = {
            "text": {"id": "s_text", "type": "text", "params": {"text": "Uma floresta ao amanhecer, névoa suave. Contato ana@ex.com #luz 12"}},
            "image": {"id": "s_image", "type": "upload", "params": {"files": [img["id"]]}},
            "video": {"id": "s_video", "type": "upload", "params": {"files": [vid["id"]]}},
            "audio": {"id": "s_audio", "type": "upload", "params": {"files": [aud["id"]]}},
            "style": {"id": "s_style", "type": "style_prompt", "params": {"text": "aquarela suave"}},
            "model3d": {"id": "s_model3d", "type": "upload", "params": {"files": [glb["id"]]}},     # v0.58: os nós 3D (textura, esqueleto, animação) pedem um modelo
        }

    def graph_for(self, t):
        spec = schema.NODE_TYPES[t]
        nodes = {"x": {"id": "x", "type": t, "x": 0, "y": 0, "params": PARAMS.get(t, {})}}
        edges = []
        for pid, _label, accepts, multi in spec["ins"]:
            kind = "style" if pid == "style" else next((k for k in ("text", "image", "video", "audio", "model3d") if k in accepts), "image" if "media" in accepts else None)
            if kind is None:
                continue
            if kind == "text" and t in ("image", "video", "sound", "voice", "model3d", "llm") and pid not in ("prompt", "text"):
                continue
            nodes[self.src[kind]["id"]] = {**self.src[kind], "x": 0, "y": 0}
            edges.append({"id": "e_" + pid, "from": self.src[kind]["id"], "to": "x", "port": pid})
            if multi and t in MULTI2:
                nodes["s2"] = {**self.src[kind], "id": "s2", "x": 0, "y": 0}
                edges.append({"id": "e2", "from": "s2", "to": "x", "port": pid})
        return list(nodes.values()), edges

    def test_every_node_type_runs(self):
        problems = []
        ran = 0
        for t in schema.NODE_TYPES:
            if t in SKIP:
                continue
            nodes, edges = self.graph_for(t)
            self.cs.save_layout(self.cid, {"nodes": nodes, "edges": edges})
            CanvasEngine(self.store, self.cid, lambda e: None, lambda: False).run(None, True)
            cur = self.cs.get(self.cid)
            n = next(x for x in cur["nodes"] if x["id"] == "x")
            res = n["result"]
            ran += 1
            if res["state"] != "done":
                if t in ("transcribe", "transcript") and "bibliotecas opcionais" in res["error"]:   # v0.62: «Transcrição» também precisa do modelo de transcrição (Whisper local); Legendas e Dublagem aqui recebem um texto e rodam sem ele
                    continue
                problems.append((t, res["state"], res["error"][:140]))
                continue
            out = schema.NODE_TYPES[t]["out"]
            if out in ("image", "video", "audio", "model3d"):
                if not res["assets"]:
                    problems.append((t, "sem arquivo"))
                for aid in res["assets"]:
                    a = next(x for x in cur["assets"] if x["id"] == aid)
                    path = self.cs.asset_path(self.cid, a["file"])
                    if not path or path.stat().st_size == 0:
                        problems.append((t, "arquivo vazio"))
            elif out == "text" and not res["text"].strip():
                problems.append((t, "texto vazio"))
        self.assertEqual(problems, [])
        self.assertEqual(ran, len(schema.NODE_TYPES) - len(SKIP))


if __name__ == "__main__":
    unittest.main()
