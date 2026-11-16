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
    """Confere um GLB (cabeçalho, JSON e contagens): {vertices, triangles, colors}. Levanta ValueError se não for um GLB válido.

    Conta todas as malhas do arquivo (não só a primeira) e aceita primitivas sem índices (a lista de vértices já é a de triângulos) e bytes sobrando depois do último bloco (v0.53)."""
    if len(data) < 28 or data[:4] != b"glTF":
        raise ValueError("não é um GLB")
    magic, ver, total = struct.unpack("<4sII", data[:12])
    n, kind = struct.unpack("<II", data[12:20])
    if ver != 2 or kind != 0x4E4F534A or total > len(data) or 20 + n > total:
        raise ValueError("GLB inválido")
    doc = json.loads(data[20:20 + n])
    acc = doc["accessors"]
    verts = tris = 0
    colors = False
    for mesh in doc["meshes"]:
        for prim in mesh["primitives"]:
            if prim.get("mode", 4) not in (4, 5, 6):   # pontos e linhas não são superfície
                continue
            count = acc[prim["attributes"]["POSITION"]]["count"]
            n_idx = acc[prim["indices"]]["count"] if prim.get("indices") is not None else count
            verts += count
            tris += n_idx // 3 if prim.get("mode", 4) == 4 else max(0, n_idx - 2)
            colors = colors or "COLOR_0" in prim["attributes"]
    if not verts or not tris:
        raise ValueError("GLB sem malha")
    return {"vertices": verts, "triangles": tris, "colors": colors}


def obj_info(data: bytes) -> Dict[str, Any]:
    """Confere um OBJ de texto: {vertices, triangles, colors}. Levanta ValueError se não for um OBJ com malha (vértices numéricos e faces que apontam para vértices existentes)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("não é um OBJ") from None
    verts = 0
    faces: List[List[int]] = []
    colors = True
    for ln in text.splitlines():
        parts = ln.split()
        if not parts or parts[0].startswith("#"):
            continue
        if parts[0] == "v":
            if len(parts) < 4:
                raise ValueError("vértice incompleto")
            nums = [float(x) for x in parts[1:7]]
            if any(x != x or x in (float("inf"), float("-inf")) for x in nums):
                raise ValueError("vértice inválido")
            colors = colors and len(parts) >= 7
            verts += 1
        elif parts[0] == "f":
            if len(parts) < 4:
                raise ValueError("face incompleta")
            faces.append([int(x.split("/")[0]) for x in parts[1:]])
    if verts < 3 or not faces:
        raise ValueError("OBJ sem malha")
    for f in faces:
        for i in f:
            if i == 0 or abs(i) > verts:
                raise ValueError("face aponta para um vértice que não existe")
    return {"vertices": verts, "triangles": sum(len(f) - 2 for f in faces), "colors": colors}


def looks_like_obj(data: bytes) -> bool:
    """Pelos primeiros bytes: texto com linhas «v x y z» e «f …» (o OBJ não tem assinatura; só vale depois de `obj_info` confirmar)."""
    head = data[:4096]
    if b"\x00" in head:
        return False
    try:
        t = head.decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return False
    lines = [ln.split() for ln in t.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    return len(lines) >= 3 and sum(1 for x in lines if x[0] == "v" and len(x) >= 4) >= 2


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
