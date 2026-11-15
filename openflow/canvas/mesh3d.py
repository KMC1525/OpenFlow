"""v0.37 — modelos 3D: gravação de malhas (GLB e OBJ, sem dependências), uma malha de demonstração offline e o roteamento das famílias de modelos locais.

Uma malha é `(verts, faces, colors)`: `verts` = lista de (x, y, z), `faces` = lista de (a, b, c) com índices, `colors` = lista de (r, g, b) entre 0 e 1 ou `None`.
Os modelos locais (Shap-E, TripoSR, Hunyuan3D…) entregam tensores/arrays; `as_lists` os converte. O GLB gravado aqui tem uma única malha (POSITION, COLOR_0 opcional e índices),
que é o que o visualizador da interface lê.
"""
from __future__ import annotations

import json
import math
import random
import re
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple

Vec = Tuple[float, float, float]
Mesh = Tuple[List[Vec], List[Tuple[int, int, int]], Optional[List[Vec]]]

MAX_VERTS = 2_000_000
FORMATS = ("glb", "obj")
MIME = {"glb": "model/gltf-binary", "obj": "model/obj"}

# família → (rótulo, aceita texto, aceita imagem, repositório padrão do Hugging Face)
FAMILIES: Dict[str, Dict[str, Any]] = {
    "shap-e": {"label": "Shap-E", "text": True, "image": True, "repo": "openai/shap-e", "image_repo": "openai/shap-e-img2img"},
    "triposr": {"label": "TripoSR", "text": False, "image": True, "repo": "stabilityai/TripoSR"},
    "hunyuan3d": {"label": "Hunyuan3D-2", "text": False, "image": True, "repo": "tencent/Hunyuan3D-2mini"},
}
SUGGEST = ["openai/shap-e", "openai/shap-e-img2img", "stabilityai/TripoSR", "tencent/Hunyuan3D-2mini", "tencent/Hunyuan3D-2"]


def family(model: str) -> str:
    """A família de um modelo 3D pelo nome do repositório (vazio = desconhecida)."""
    n = (model or "").lower()
    if "shap-e" in n or "shap_e" in n:
        return "shap-e"
    if "triposr" in n or "tripo-sr" in n:
        return "triposr"
    if "hunyuan3d" in n or "hunyuan-3d" in n:
        return "hunyuan3d"
    return ""


def needs_image(model: str) -> bool:
    """O modelo só aceita imagem (TripoSR, Hunyuan3D)? Então o texto vira uma imagem antes (duas etapas)."""
    fam = FAMILIES.get(family(model))
    return bool(fam) and not fam["text"]


def is_img2img(model: str) -> bool:
    return family(model) == "shap-e" and "img2img" in model.lower()


def as_lists(verts: Any, faces: Any, colors: Any = None) -> Mesh:
    """Aceita listas, arrays do numpy ou tensores do torch."""
    def listy(x: Any) -> Any:
        for attr in ("detach", "cpu"):
            if hasattr(x, attr):
                x = getattr(x, attr)()
        return x.tolist() if hasattr(x, "tolist") else x

    v = [(float(a[0]), float(a[1]), float(a[2])) for a in listy(verts)]
    f = [(int(a[0]), int(a[1]), int(a[2])) for a in listy(faces)]
    if len(v) > MAX_VERTS:
        raise ValueError("A malha 3D tem vértices demais.")
    c = None
    if colors is not None:
        cc = listy(colors)
        if len(cc) == len(v):
            c = [(min(1.0, max(0.0, float(a[0]))), min(1.0, max(0.0, float(a[1]))), min(1.0, max(0.0, float(a[2])))) for a in cc]
    bad = next((i for tri in f for i in tri if i < 0 or i >= len(v)), None)
    if bad is not None:
        raise ValueError("A malha 3D tem faces com índices fora dos vértices.")
    return v, f, c


def rotate_x(verts: Sequence[Vec], degrees: float) -> List[Vec]:
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return [(x, y * c - z * s, y * s + z * c) for x, y, z in verts]


def fit_unit(verts: Sequence[Vec]) -> List[Vec]:
    """Centra a malha na origem e a encaixa num cubo de lado 2 (o visualizador e outros programas a abrem no tamanho certo)."""
    if not verts:
        return []
    lo = [min(v[i] for v in verts) for i in range(3)]
    hi = [max(v[i] for v in verts) for i in range(3)]
    mid = [(lo[i] + hi[i]) / 2 for i in range(3)]
    big = max(hi[i] - lo[i] for i in range(3)) or 1.0
    k = 2.0 / big
    return [((x - mid[0]) * k, (y - mid[1]) * k, (z - mid[2]) * k) for x, y, z in verts]


def to_glb(verts: Sequence[Vec], faces: Sequence[Tuple[int, int, int]], colors: Optional[Sequence[Vec]] = None) -> bytes:
    """GLB (glTF 2.0 binário) com uma malha: POSITION, COLOR_0 (opcional) e índices de 32 bits."""
    if not verts or not faces:
        raise ValueError("A malha 3D está vazia.")
    pos = b"".join(struct.pack("<3f", *v) for v in verts)
    idx = b"".join(struct.pack("<3I", *f) for f in faces)
    col = b"".join(struct.pack("<3f", *c) for c in colors) if colors else b""
    chunks = [(idx, 34963), (pos, 34962)] + ([(col, 34962)] if col else [])
    blob, views, off = b"", [], 0
    for data, target in chunks:
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data), "target": target})
        blob += data
        off += len(data)
    lo = [min(v[i] for v in verts) for i in range(3)]
    hi = [max(v[i] for v in verts) for i in range(3)]
    acc = [{"bufferView": 0, "componentType": 5125, "count": len(faces) * 3, "type": "SCALAR"},
           {"bufferView": 1, "componentType": 5126, "count": len(verts), "type": "VEC3", "min": lo, "max": hi}]
    attrs = {"POSITION": 1}
    if col:
        acc.append({"bufferView": 2, "componentType": 5126, "count": len(verts), "type": "VEC3"})
        attrs["COLOR_0"] = 2
    doc = {"asset": {"version": "2.0", "generator": "OpenFlow"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
           "meshes": [{"primitives": [{"attributes": attrs, "indices": 0, "material": 0, "mode": 4}]}],
           "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9}, "doubleSided": True}],
           "accessors": acc, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\x00" * (-len(blob) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob


def to_obj(verts: Sequence[Vec], faces: Sequence[Tuple[int, int, int]], colors: Optional[Sequence[Vec]] = None) -> bytes:
    """OBJ em texto; com cores, cada vértice leva «r g b» depois de x y z (extensão aceita pelo Blender e MeshLab)."""
    if not verts or not faces:
        raise ValueError("A malha 3D está vazia.")
    lines = ["# OpenFlow"]
    for i, v in enumerate(verts):
        lines.append("v %.6f %.6f %.6f" % v + (" %.4f %.4f %.4f" % tuple(colors[i]) if colors else ""))
    lines += ["f %d %d %d" % (a + 1, b + 1, c + 1) for a, b, c in faces]
    return ("\n".join(lines) + "\n").encode()


def encode(mesh: Mesh, fmt: str = "glb", fit: bool = True) -> bytes:
    verts, faces, colors = mesh
    if fit:
        verts = fit_unit(verts)
    return (to_obj if fmt == "obj" else to_glb)(verts, faces, colors)


def glb_info(data: bytes) -> Dict[str, Any]:
    """Confere um GLB (cabeçalho, JSON e contagens): {vertices, triangles, colors}. Levanta ValueError se não for um GLB válido."""
    if len(data) < 28 or data[:4] != b"glTF":
        raise ValueError("não é um GLB")
    magic, ver, total = struct.unpack("<4sII", data[:12])
    n, kind = struct.unpack("<II", data[12:20])
    if ver != 2 or kind != 0x4E4F534A or total != len(data):
        raise ValueError("GLB inválido")
    doc = json.loads(data[20:20 + n])
    prim = doc["meshes"][0]["primitives"][0]
    acc = doc["accessors"]
    return {"vertices": acc[prim["attributes"]["POSITION"]]["count"], "triangles": acc[prim["indices"]]["count"] // 3, "colors": "COLOR_0" in prim["attributes"]}


# --------------------------------------------------------------------------- malha de demonstração (offline)
_DEMO_SHAPES = ("sphere", "torus", "cube", "cone", "vase")


def demo_shape(prompt: str) -> str:
    p = (prompt or "").lower()
    for key, shape in (("rosca", "torus"), ("donut", "torus"), ("anel", "torus"), ("ring", "torus"), ("caixa", "cube"), ("cubo", "cube"), ("box", "cube"), ("cube", "cube"),
                       ("cone", "cone"), ("árvore", "cone"), ("tree", "cone"), ("vaso", "vase"), ("vase", "vase"), ("copo", "vase"), ("bola", "sphere"), ("ball", "sphere")):
        if key in p:
            return shape
    return _DEMO_SHAPES[sum(map(ord, p)) % len(_DEMO_SHAPES)]


def demo_mesh(prompt: str = "", seed: int = 0, detail: int = 24) -> Mesh:
    """Uma forma simples (esfera, rosca, cubo, cone ou vaso) com leve deformação e cores por altura — para testar fluxos 3D sem modelo e sem internet."""
    rnd = random.Random((sum(map(ord, prompt or "")) * 31 + int(seed)) & 0xFFFFFFFF)
    shape = demo_shape(prompt)
    hue = rnd.random()
    n = max(8, min(64, detail))
    verts: List[Vec] = []
    faces: List[Tuple[int, int, int]] = []

    def grid(fn, nu: int, nv: int, wrap_u: bool = True) -> None:
        base = len(verts)
        for j in range(nv + 1):
            for i in range(nu + (0 if wrap_u else 1)):
                verts.append(fn(i / nu, j / nv))
        row = nu + (0 if wrap_u else 1)
        for j in range(nv):
            for i in range(nu):
                a = base + j * row + i
                b = base + j * row + (i + 1) % row if wrap_u else a + 1
                c, d = a + row, (b + row)
                faces.append((a, b, d))
                faces.append((a, d, c))

    bump = rnd.uniform(0.04, 0.12)
    freq = rnd.randint(2, 5)
    if shape == "torus":
        grid(lambda u, v: ((1 + 0.4 * math.cos(2 * math.pi * v)) * math.cos(2 * math.pi * u), 0.4 * math.sin(2 * math.pi * v) * (1 + bump * math.sin(freq * 2 * math.pi * u)), (1 + 0.4 * math.cos(2 * math.pi * v)) * math.sin(2 * math.pi * u)), n, n // 2)
    elif shape == "cube":
        for axis in range(3):
            for sign in (-1, 1):
                base = len(verts)
                k = 6
                for j in range(k + 1):
                    for i in range(k + 1):
                        a, b = -1 + 2 * i / k, -1 + 2 * j / k
                        p = [a, b]
                        p.insert(axis, float(sign))
                        verts.append((p[0], p[1], p[2]))
                for j in range(k):
                    for i in range(k):
                        q = base + j * (k + 1) + i
                        tri = [(q, q + 1, q + k + 2), (q, q + k + 2, q + k + 1)]
                        faces += tri if sign > 0 else [(t[0], t[2], t[1]) for t in tri]
    elif shape == "cone":
        grid(lambda u, v: ((1 - v) * math.cos(2 * math.pi * u), 2 * v - 1, (1 - v) * math.sin(2 * math.pi * u)), n, 12)
    elif shape == "vase":
        grid(lambda u, v: ((0.55 + 0.45 * math.sin(math.pi * v * 1.6 + 0.4) * (1 + bump * math.sin(freq * 2 * math.pi * u))) * math.cos(2 * math.pi * u), 2 * v - 1,
                           (0.55 + 0.45 * math.sin(math.pi * v * 1.6 + 0.4) * (1 + bump * math.sin(freq * 2 * math.pi * u))) * math.sin(2 * math.pi * u)), n, n)
    else:
        grid(lambda u, v: (math.sin(math.pi * v) * math.cos(2 * math.pi * u) * (1 + bump * math.sin(freq * 2 * math.pi * u)), math.cos(math.pi * v), math.sin(math.pi * v) * math.sin(2 * math.pi * u) * (1 + bump * math.sin(freq * 2 * math.pi * u))), n, n)
    ys = [v[1] for v in verts]
    lo, hi = min(ys), max(ys)
    colors = []
    for v in verts:
        t = (v[1] - lo) / ((hi - lo) or 1)
        h = (hue + 0.25 * t) % 1.0
        colors.append(_hsv(h, 0.55, 0.65 + 0.3 * t))
    return verts, faces, colors


def _hsv(h: float, s: float, v: float) -> Vec:
    i = int(h * 6)
    f = h * 6 - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]


def valid_format(fmt: Any) -> str:
    return fmt if fmt in FORMATS else "glb"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "modelo").lower()).strip("-")[:40] or "modelo"
