"""v0.58 — modelos 3D completos: ler (GLB/OBJ) e gravar GLB com esqueleto, animação e textura; esqueleto automático, animações e textura procedurais. Sem dependências.

`mesh3d.py` só grava uma malha simples (posições, índices e cores). Aqui um `Model` carrega tudo o que os três nós novos (Esqueleto 3D, Animação 3D e Textura 3D) precisam passar adiante:

- geometria: `verts`, `faces`, `colors` (por vértice, opcional);
- textura: `uvs` (por vértice), `texture` (PNG/JPEG já codificado) e o material (`tint`, `metallic`, `roughness`);
- esqueleto: `joints` (nome, pai, posição de repouso) e `skin` (por vértice, 4 juntas e 4 pesos);
- animação: `animations` (uma lista de «clipes»; cada trilha move uma junta ou o modelo todo).

Limites assumidos (de propósito, para ficar simples e previsível): uma só pele (skin), juntas sem rotação de repouso (as posições bastam para o corpo em repouso), todas as malhas do arquivo viram uma só, e animações de arquivos
de fora são lidas como trilhas de translação/rotação/escala de juntas (interpolação cúbica vira linear).
"""
from __future__ import annotations

import base64
import json
import math
import random

import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple

Vec = Tuple[float, float, float]

MAX_VERTS = 400_000          # acima disso o esqueleto automático (distância vértice×osso) levaria minutos
MAX_JOINTS = 64
_CTYPES = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class Joint:
    __slots__ = ("name", "parent", "pos")

    def __init__(self, name: str, parent: int, pos: Vec):
        self.name, self.parent, self.pos = name, parent, (float(pos[0]), float(pos[1]), float(pos[2]))


class Model:
    """Um modelo 3D: ver o módulo."""

    def __init__(self) -> None:
        self.verts: List[Vec] = []
        self.faces: List[Tuple[int, int, int]] = []
        self.colors: Optional[List[Vec]] = None
        self.uvs: Optional[List[Tuple[float, float]]] = None
        self.texture: Optional[bytes] = None
        self.tint: Tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0)
        self.metallic = 0.0
        self.roughness = 0.9
        self.joints: List[Joint] = []
        self.skin: Optional[List[Tuple[Tuple[int, int, int, int], Tuple[float, float, float, float]]]] = None
        self.animations: List[Dict[str, Any]] = []

    def copy(self) -> "Model":
        m = Model()
        m.verts, m.faces = list(self.verts), list(self.faces)
        m.colors = list(self.colors) if self.colors is not None else None
        m.uvs = list(self.uvs) if self.uvs is not None else None
        m.texture, m.tint, m.metallic, m.roughness = self.texture, self.tint, self.metallic, self.roughness
        m.joints = [Joint(j.name, j.parent, j.pos) for j in self.joints]
        m.skin = list(self.skin) if self.skin is not None else None
        m.animations = [dict(a, tracks=[dict(t) for t in a["tracks"]]) for a in self.animations]
        return m

    def bbox(self) -> Tuple[Vec, Vec]:
        if not self.verts:
            raise ValueError("O modelo 3D está vazio.")
        return ((min(v[0] for v in self.verts), min(v[1] for v in self.verts), min(v[2] for v in self.verts)),
                (max(v[0] for v in self.verts), max(v[1] for v in self.verts), max(v[2] for v in self.verts)))

    def info(self) -> Dict[str, Any]:
        return {"vertices": len(self.verts), "triangles": len(self.faces), "joints": len(self.joints), "textured": bool(self.texture and self.uvs),
                "animations": [a["name"] for a in self.animations], "colors": self.colors is not None}


# --------------------------------------------------------------------------- matrizes (4×4, ordem de colunas do glTF)
_I = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _mmul(a: Sequence[float], b: Sequence[float]) -> List[float]:
    o = [0.0] * 16
    for c in range(4):
        for r in range(4):
            o[c * 4 + r] = sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
    return o


def _trs(t: Sequence[float], q: Sequence[float], s: Sequence[float]) -> List[float]:
    x, y, z, w = q
    return [(1 - 2 * (y * y + z * z)) * s[0], 2 * (x * y + z * w) * s[0], 2 * (x * z - y * w) * s[0], 0, 2 * (x * y - z * w) * s[1], (1 - 2 * (x * x + z * z)) * s[1], 2 * (y * z + x * w) * s[1], 0,
            2 * (x * z + y * w) * s[2], 2 * (y * z - x * w) * s[2], (1 - 2 * (x * x + y * y)) * s[2], 0, t[0], t[1], t[2], 1]


def _node_matrix(n: Dict[str, Any]) -> List[float]:
    if isinstance(n.get("matrix"), list) and len(n["matrix"]) == 16:
        return [float(v) for v in n["matrix"]]
    return _trs(n.get("translation") or (0, 0, 0), n.get("rotation") or (0, 0, 0, 1), n.get("scale") or (1, 1, 1))


def _apply(m: Sequence[float], p: Sequence[float]) -> Vec:
    return (m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12], m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13], m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14])


def _affine_inverse_translation(m: Sequence[float]) -> Vec:
    """Translação da inversa de uma matriz afim (a posição de uma junta a partir da sua «inverse bind matrix»)."""
    a, b, c, d, e, f, g, h, i = m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        return (-m[12], -m[13], -m[14])
    inv = [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det], [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det], [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]
    t = (m[12], m[13], m[14])
    return tuple(-(inv[r][0] * t[0] + inv[r][1] * t[1] + inv[r][2] * t[2]) for r in range(3))  # type: ignore[return-value]


# --------------------------------------------------------------------------- quaternions
def q_axis(axis: Sequence[float], deg: float) -> Tuple[float, float, float, float]:
    n = math.sqrt(sum(a * a for a in axis)) or 1.0
    h = math.radians(deg) / 2
    s = math.sin(h) / n
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(h))


def q_mul(a: Sequence[float], b: Sequence[float]) -> Tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


# --------------------------------------------------------------------------- leitura
def read_model(data: bytes) -> Model:
    """GLB (glTF binário) ou OBJ (texto) → `Model`. Levanta ValueError com uma mensagem clara se o arquivo não for um modelo."""
    if data[:4] == b"glTF":
        return _read_glb(data)
    return _read_obj(data)


def _read_obj(data: bytes) -> Model:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("O arquivo não é um modelo 3D (GLB ou OBJ).") from None
    pos: List[Vec] = []
    cols: List[Vec] = []
    uv: List[Tuple[float, float]] = []
    tris: List[List[Tuple[int, int]]] = []
    colored = True
    for ln in text.splitlines():
        p = ln.split()
        if not p or p[0].startswith("#"):
            continue
        if p[0] == "v" and len(p) >= 4:
            pos.append((float(p[1]), float(p[2]), float(p[3])))
            if len(p) >= 7:
                cols.append((float(p[4]), float(p[5]), float(p[6])))
            else:
                colored = False
        elif p[0] == "vt" and len(p) >= 3:
            uv.append((float(p[1]), float(p[2])))
        elif p[0] == "f" and len(p) >= 4:
            ref = []
            for tok in p[1:]:
                parts = tok.split("/")
                vi = int(parts[0])
                vi = len(pos) + vi if vi < 0 else vi - 1
                ti = -1
                if len(parts) > 1 and parts[1]:
                    t = int(parts[1])
                    ti = len(uv) + t if t < 0 else t - 1
                if not (0 <= vi < len(pos)):
                    raise ValueError("O OBJ tem uma face que aponta para um vértice que não existe.")
                ref.append((vi, ti))
            for i in range(1, len(ref) - 1):
                tris.append([ref[0], ref[i], ref[i + 1]])
    if len(pos) < 3 or not tris:
        raise ValueError("O arquivo não é um modelo 3D (GLB ou OBJ) com malha.")
    if len(pos) > MAX_VERTS * 5:
        raise ValueError("O modelo tem vértices demais.")
    m = Model()
    if uv and any(t >= 0 for tri in tris for _, t in tri):   # com coordenadas de textura: um vértice por par (posição, uv)
        index: Dict[Tuple[int, int], int] = {}
        for tri in tris:
            f = []
            for key in tri:
                if key not in index:
                    index[key] = len(m.verts)
                    m.verts.append(pos[key[0]])
                    if colored:
                        cols_v = cols[key[0]]
                        m.colors = (m.colors or []) + [cols_v]
                    m.uvs = (m.uvs or []) + [uv[key[1]] if 0 <= key[1] < len(uv) else (0.0, 0.0)]
                f.append(index[key])
            m.faces.append((f[0], f[1], f[2]))
    else:
        m.verts = pos
        m.colors = cols if colored and len(cols) == len(pos) else None
        m.faces = [(t[0][0], t[1][0], t[2][0]) for t in tris]
    return m


def _read_glb(data: bytes) -> Model:
    if len(data) < 28:
        raise ValueError("GLB inválido.")
    ver, total = struct.unpack("<II", data[4:12])
    if ver != 2 or total > len(data):
        raise ValueError("GLB inválido.")
    doc: Optional[Dict[str, Any]] = None
    blob = b""
    off = 12
    while off + 8 <= total:
        ln, kind = struct.unpack("<II", data[off:off + 8])
        body = data[off + 8:off + 8 + ln]
        if kind == 0x4E4F534A and doc is None:
            doc = json.loads(body)
        elif kind == 0x004E4942 and not blob:
            blob = body
        off += 8 + ln
    if not doc or not doc.get("meshes"):
        raise ValueError("O GLB não tem nenhuma malha.")
    views = doc.get("bufferViews", [])
    accs = doc.get("accessors", [])

    def view_bytes(vi: int) -> bytes:
        v = views[vi]
        o = int(v.get("byteOffset", 0))
        return blob[o:o + int(v["byteLength"])]

    def read_acc(ai: int) -> List[Tuple[float, ...]]:
        a = accs[ai]
        fmt, size = _CTYPES[a["componentType"]]
        comp = _NCOMP[a["type"]]
        n = int(a["count"])
        if a.get("bufferView") is None:
            return [tuple([0.0] * comp)] * n
        v = views[a["bufferView"]]
        base = int(v.get("byteOffset", 0)) + int(a.get("byteOffset", 0))
        stride = int(v.get("byteStride") or size * comp)
        out: List[Tuple[float, ...]] = []
        norm = bool(a.get("normalized"))
        mx = {"b": 127.0, "B": 255.0, "h": 32767.0, "H": 65535.0}.get(fmt, 1.0)
        if stride == size * comp:
            raw = struct.unpack_from("<%d%s" % (n * comp, fmt), blob, base)
            it = [tuple(raw[i * comp:(i + 1) * comp]) for i in range(n)]
        else:
            it = [struct.unpack_from("<%d%s" % (comp, fmt), blob, base + i * stride) for i in range(n)]
        for t in it:
            out.append(tuple(max(x / mx, -1.0) for x in t) if norm else tuple(float(x) if fmt != "I" and fmt not in "bBhH" else x for x in t))
        return out

    nodes = doc.get("nodes", [])
    parent_of: Dict[int, int] = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent_of[c] = i
    glob: Dict[int, List[float]] = {}

    def gm(i: int) -> List[float]:
        if i not in glob:
            glob[i] = _mmul(gm(parent_of[i]), _node_matrix(nodes[i])) if i in parent_of else _node_matrix(nodes[i])
        return glob[i]

    sc = (doc.get("scenes") or [{}])[doc.get("scene", 0) if doc.get("scenes") else 0]
    roots = sc.get("nodes") if nodes else None
    mesh_nodes: List[int] = []

    def collect(i: int, seen: set) -> None:
        if i in seen:
            return
        seen.add(i)
        if "mesh" in nodes[i]:
            mesh_nodes.append(i)
        for c in nodes[i].get("children", []):
            collect(c, seen)
    if nodes:
        seen: set = set()
        for r in (roots if roots is not None else [i for i in range(len(nodes)) if i not in parent_of]):
            collect(r, seen)
    sources: List[Tuple[Dict[str, Any], Optional[List[float]], Optional[int]]] = []   # (malha, matriz global do nó, índice do nó)
    for ni in mesh_nodes:
        sources.append((doc["meshes"][nodes[ni]["mesh"]], gm(ni), ni))
    if not sources:
        sources = [(mesh, None, None) for mesh in doc["meshes"]]

    # pele (a primeira): juntas e posições de repouso
    skin_def = None
    joint_nodes: List[int] = []
    for _mesh, _g, ni in sources:
        if ni is not None and nodes[ni].get("skin") is not None:
            skin_def = doc["skins"][nodes[ni]["skin"]]
            joint_nodes = list(skin_def["joints"])
            break
    m = Model()
    jindex = {nid: k for k, nid in enumerate(joint_nodes)}
    if skin_def is not None:
        if len(joint_nodes) > MAX_JOINTS:
            raise ValueError(f"O esqueleto tem juntas demais ({len(joint_nodes)}; o máximo é {MAX_JOINTS}).")
        ibm = read_acc(skin_def["inverseBindMatrices"]) if skin_def.get("inverseBindMatrices") is not None else []
        for k, nid in enumerate(joint_nodes):
            par = -1
            a = parent_of.get(nid)
            while a is not None:
                if a in jindex:
                    par = jindex[a]
                    break
                a = parent_of.get(a)
            pos = _affine_inverse_translation(ibm[k]) if k < len(ibm) else (gm(nid)[12], gm(nid)[13], gm(nid)[14])
            m.joints.append(Joint(nodes[nid].get("name") or f"junta_{k}", par, pos))

    have_color = have_uv = False
    parts: List[Dict[str, Any]] = []
    tex_done = False
    for mesh, g, ni in sources:
        skinned = ni is not None and nodes[ni].get("skin") is not None and skin_def is not None
        for prim in mesh.get("primitives", []):
            mode = prim.get("mode", 4)
            if mode not in (4, 5, 6) or "POSITION" not in prim.get("attributes", {}):
                continue
            att = prim["attributes"]
            P = [(p[0], p[1], p[2]) for p in read_acc(att["POSITION"])]
            if g is not None and not skinned:
                P = [_apply(g, p) for p in P]
            idx = [int(i[0]) for i in read_acc(prim["indices"])] if prim.get("indices") is not None else list(range(len(P)))
            tris: List[Tuple[int, int, int]] = []
            if mode == 4:
                tris = [(idx[i], idx[i + 1], idx[i + 2]) for i in range(0, len(idx) - 2, 3)]
            elif mode == 5:
                tris = [((idx[i + 1], idx[i], idx[i + 2]) if i % 2 else (idx[i], idx[i + 1], idx[i + 2])) for i in range(len(idx) - 2)]
            else:
                tris = [(idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1)]
            part: Dict[str, Any] = {"P": P, "T": [t for t in tris if max(t) < len(P)]}
            if "COLOR_0" in att:
                part["C"] = [(c[0], c[1], c[2]) for c in read_acc(att["COLOR_0"])]
                have_color = True
            if "TEXCOORD_0" in att:
                part["U"] = [(u[0], u[1]) for u in read_acc(att["TEXCOORD_0"])]
                have_uv = True
            if skinned and "JOINTS_0" in att and "WEIGHTS_0" in att:
                J, W = read_acc(att["JOINTS_0"]), read_acc(att["WEIGHTS_0"])
                part["S"] = [(tuple(int(x) for x in j[:4]), tuple(float(x) for x in w[:4])) for j, w in zip(J, W)]
            mat = (doc.get("materials") or [{}])[prim["material"]] if prim.get("material") is not None and doc.get("materials") else {}
            pbr = mat.get("pbrMetallicRoughness", {})
            part["mat"] = pbr
            if not tex_done and pbr.get("baseColorTexture") is not None:
                try:
                    tex = doc["textures"][pbr["baseColorTexture"]["index"]]
                    img = doc["images"][tex["source"]]
                    if img.get("bufferView") is not None:
                        m.texture = view_bytes(img["bufferView"])
                    elif str(img.get("uri", "")).startswith("data:"):
                        m.texture = base64.b64decode(img["uri"].split(",", 1)[1])
                    tex_done = m.texture is not None
                except (KeyError, IndexError, ValueError, TypeError):
                    m.texture = None
            parts.append(part)
    if not parts or sum(len(p["P"]) for p in parts) < 3:
        raise ValueError("O GLB não tem superfície (só pontos ou linhas).")
    any_skin = any("S" in p for p in parts)
    for p in parts:
        base = len(m.verts)
        m.verts += p["P"]
        m.faces += [(a + base, b + base, c + base) for a, b, c in p["T"]]
        if have_color:
            m.colors = (m.colors or []) + (p.get("C") or [(0.78, 0.78, 0.8)] * len(p["P"]))
        if have_uv:
            m.uvs = (m.uvs or []) + (p.get("U") or [(0.0, 0.0)] * len(p["P"]))
        if any_skin:
            m.skin = (m.skin or []) + (p.get("S") or [((0, 0, 0, 0), (1.0, 0.0, 0.0, 0.0))] * len(p["P"]))
    if len(m.verts) > MAX_VERTS * 5:
        raise ValueError("O modelo tem vértices demais.")
    pbr0 = parts[0]["mat"]
    if pbr0.get("baseColorFactor"):
        bf = pbr0["baseColorFactor"]
        m.tint = (float(bf[0]), float(bf[1]), float(bf[2]), float(bf[3]) if len(bf) > 3 else 1.0)
    m.metallic = float(pbr0.get("metallicFactor", 0.0))
    m.roughness = float(pbr0.get("roughnessFactor", 0.9))
    if m.uvs is None or not m.texture:
        m.texture = m.texture if m.uvs is not None else None

    # animações (a primeira)
    if doc.get("animations") and m.joints is not None:
        anim = doc["animations"][0]
        tracks = []
        mesh_node_set = set(mesh_nodes)
        for ch in anim.get("channels", []):
            tgt = ch.get("target", {})
            path = tgt.get("path")
            node = tgt.get("node")
            if path not in ("translation", "rotation", "scale") or node is None:
                continue
            samp = anim["samplers"][ch["sampler"]]
            times = [t[0] for t in read_acc(samp["input"])]
            vals = [tuple(v) for v in read_acc(samp["output"])]
            if samp.get("interpolation") == "CUBICSPLINE" and len(vals) == 3 * len(times):
                vals = vals[1::3]
            if len(vals) != len(times):
                continue
            if node in jindex:
                target: Tuple[str, int] = ("joint", jindex[node])
            elif node in mesh_node_set or node in roots_of(nodes, parent_of, mesh_nodes):
                target = ("root", 0)
            else:
                continue
            tracks.append({"target": target, "path": path, "times": times, "values": vals})
        if tracks:
            m.animations.append({"name": anim.get("name") or "animação", "duration": max(max(t["times"]) for t in tracks), "tracks": tracks})
    return m


def roots_of(nodes: List[Dict[str, Any]], parent_of: Dict[int, int], mesh_nodes: List[int]) -> set:
    """Os nós que são a malha ou ancestrais dela (uma animação do «objeto todo» pode estar num pai da malha)."""
    out = set(mesh_nodes)
    for mn in mesh_nodes:
        a = parent_of.get(mn)
        while a is not None:
            out.add(a)
            a = parent_of.get(a)
    return out


# --------------------------------------------------------------------------- gravação
def _pad(b: bytes) -> bytes:
    return b + b"\x00" * (-len(b) % 4)


def write_glb(m: Model) -> bytes:
    """`Model` → GLB 2.0 (uma malha; com cores, UV + textura, pele + juntas e animação quando o modelo as tem)."""
    if not m.verts or not m.faces:
        raise ValueError("A malha 3D está vazia.")
    n = len(m.verts)
    blob = bytearray()
    views: List[Dict[str, Any]] = []
    accs: List[Dict[str, Any]] = []

    def add_view(data: bytes, target: Optional[int] = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        v: Dict[str, Any] = {"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)}
        if target:
            v["target"] = target
        blob.extend(data)
        views.append(v)
        return len(views) - 1

    def add_acc(data: bytes, ctype: int, type_: str, count: int, target: Optional[int] = None, mn: Any = None, mx: Any = None, norm: bool = False) -> int:
        a: Dict[str, Any] = {"bufferView": add_view(data, target), "componentType": ctype, "count": count, "type": type_}
        if mn is not None:
            a["min"], a["max"] = mn, mx
        if norm:
            a["normalized"] = True
        accs.append(a)
        return len(accs) - 1

    idx = add_acc(b"".join(struct.pack("<3I", *f) for f in m.faces), 5125, "SCALAR", len(m.faces) * 3, 34963)
    lo = [min(v[i] for v in m.verts) for i in range(3)]
    hi = [max(v[i] for v in m.verts) for i in range(3)]
    attrs = {"POSITION": add_acc(b"".join(struct.pack("<3f", *v) for v in m.verts), 5126, "VEC3", n, 34962, lo, hi)}
    if m.colors is not None and len(m.colors) == n:
        attrs["COLOR_0"] = add_acc(b"".join(struct.pack("<3f", *c) for c in m.colors), 5126, "VEC3", n, 34962)
    textured = bool(m.texture and m.uvs is not None and len(m.uvs) == n)
    if m.uvs is not None and len(m.uvs) == n:
        attrs["TEXCOORD_0"] = add_acc(b"".join(struct.pack("<2f", *u) for u in m.uvs), 5126, "VEC2", n, 34962)
    skinned = bool(m.joints and m.skin is not None and len(m.skin) == n)
    if skinned:
        attrs["JOINTS_0"] = add_acc(b"".join(struct.pack("<4H", *j) for j, _ in m.skin), 5123, "VEC4", n, 34962)   # type: ignore[union-attr]
        attrs["WEIGHTS_0"] = add_acc(b"".join(struct.pack("<4f", *w) for _, w in m.skin), 5126, "VEC4", n, 34962)   # type: ignore[union-attr]

    mat: Dict[str, Any] = {"pbrMetallicRoughness": {"baseColorFactor": list(m.tint), "metallicFactor": m.metallic, "roughnessFactor": m.roughness}, "doubleSided": True}
    doc: Dict[str, Any] = {"asset": {"version": "2.0", "generator": "OpenFlow"}, "scene": 0}
    if textured:
        mime = "image/jpeg" if m.texture[:3] == b"\xff\xd8\xff" else "image/png"   # type: ignore[index]
        doc["images"] = [{"bufferView": add_view(m.texture), "mimeType": mime}]   # type: ignore[arg-type]
        doc["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}]
        doc["textures"] = [{"sampler": 0, "source": 0}]
        mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0, "texCoord": 0}
    doc["materials"] = [mat]
    doc["meshes"] = [{"primitives": [{"attributes": attrs, "indices": idx, "material": 0, "mode": 4}]}]
    gnodes: List[Dict[str, Any]] = [{"name": "modelo", "mesh": 0}]
    scene_nodes = [0]
    if skinned:
        J = len(m.joints)
        children: Dict[int, List[int]] = {}
        for k, j in enumerate(m.joints):
            if j.parent >= 0:
                children.setdefault(j.parent, []).append(k + 1)
        for k, j in enumerate(m.joints):
            pp = m.joints[j.parent].pos if j.parent >= 0 else (0.0, 0.0, 0.0)
            node: Dict[str, Any] = {"name": j.name, "translation": [j.pos[0] - pp[0], j.pos[1] - pp[1], j.pos[2] - pp[2]]}
            if k in children:   # `children` é indexado pela junta pai (0, 1, …) e guarda os NÓS filhos (junta + 1: o nó 0 é a malha)
                node["children"] = children[k]
            gnodes.append(node)
        ibm = b"".join(struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -j.pos[0], -j.pos[1], -j.pos[2], 1) for j in m.joints)
        root_joints = [k + 1 for k, j in enumerate(m.joints) if j.parent < 0]
        doc["skins"] = [{"joints": list(range(1, J + 1)), "inverseBindMatrices": add_acc(ibm, 5126, "MAT4", J), "skeleton": root_joints[0] if root_joints else 1}]
        gnodes[0]["skin"] = 0
        scene_nodes += root_joints
    if m.animations:
        anims = []
        for clip in m.animations:
            samplers: List[Dict[str, Any]] = []
            channels: List[Dict[str, Any]] = []
            for tr in clip["tracks"]:
                kind, jidx = tr["target"]
                if kind == "joint" and (not skinned or jidx >= len(m.joints)):
                    continue
                node_i = jidx + 1 if kind == "joint" else (scene_nodes[1] if skinned and scene_nodes[1:] else 0)   # modelo com pele: «o objeto todo» é a junta raiz (a malha com pele ignora a própria transformação)
                comp = 4 if tr["path"] == "rotation" else 3
                inp = add_acc(struct.pack("<%df" % len(tr["times"]), *tr["times"]), 5126, "SCALAR", len(tr["times"]), None, [min(tr["times"])], [max(tr["times"])])
                out = add_acc(b"".join(struct.pack("<%df" % comp, *v) for v in tr["values"]), 5126, "VEC4" if comp == 4 else "VEC3", len(tr["values"]))
                samplers.append({"input": inp, "output": out, "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1, "target": {"node": node_i, "path": tr["path"]}})
            if channels:
                anims.append({"name": clip["name"], "samplers": samplers, "channels": channels})
        if anims:
            doc["animations"] = anims
    doc["nodes"] = gnodes
    doc["scenes"] = [{"nodes": scene_nodes}]
    doc["accessors"], doc["bufferViews"] = accs, views
    doc["buffers"] = [{"byteLength": len(_pad(bytes(blob)))}]
    # o preenchimento do bloco JSON é com espaços (a especificação); o do BIN, com zeros
    raw = json.dumps(doc, separators=(",", ":")).encode()
    raw += b" " * (-len(raw) % 4)
    bn = bytes(blob) + b"\x00" * (-len(blob) % 4)
    total = 12 + 8 + len(raw) + 8 + len(bn)
    return struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(bn), 0x004E4942) + bn


# --------------------------------------------------------------------------- esqueleto automático
RIG_STYLES = ("humanoid", "spine", "chain")


def _humanoid(lo: Vec, hi: Vec) -> List[Joint]:
    H = hi[1] - lo[1] or 1.0
    cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2

    def P(dx: float, fy: float, dz: float = 0.0) -> Vec:
        return (cx + dx * H, lo[1] + fy * H, cz + dz * H)

    j: List[Joint] = []

    def add(name: str, parent: str, pos: Vec) -> None:
        j.append(Joint(name, next((k for k, x in enumerate(j) if x.name == parent), -1), pos))

    add("quadril", "", P(0, 0.53))
    add("coluna", "quadril", P(0, 0.62))
    add("peito", "coluna", P(0, 0.72))
    add("pescoco", "peito", P(0, 0.82))
    add("cabeca", "pescoco", P(0, 0.89))
    for side, sg in (("e", -1), ("d", 1)):   # esquerda = -x, direita = +x (de frente para o modelo, que olha para +z)
        add(f"ombro_{side}", "peito", P(sg * 0.07, 0.78))
        add(f"braco_{side}", f"ombro_{side}", P(sg * 0.14, 0.76))
        add(f"antebraco_{side}", f"braco_{side}", P(sg * 0.22, 0.62))
        add(f"mao_{side}", f"antebraco_{side}", P(sg * 0.28, 0.50))
        add(f"coxa_{side}", "quadril", P(sg * 0.06, 0.50))
        add(f"canela_{side}", f"coxa_{side}", P(sg * 0.06, 0.28))
        add(f"pe_{side}", f"canela_{side}", P(sg * 0.06, 0.05))
        add(f"ponta_{side}", f"pe_{side}", P(sg * 0.06, 0.02, 0.09))
    return j


def _chain(lo: Vec, hi: Vec, n: int, axis: int, prefix: str) -> List[Joint]:
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    out: List[Joint] = []
    for k in range(n):
        p = list(c)
        p[axis] = lo[axis] + (hi[axis] - lo[axis]) * (k / max(1, n - 1))
        out.append(Joint(f"{prefix}_{k}", k - 1, tuple(p)))   # type: ignore[arg-type]
    return out


def auto_rig(m: Model, style: str = "humanoid", bones: int = 8, smooth: float = 0.5) -> Model:
    """Esqueleto procedural: coloca as juntas pelas proporções da caixa do modelo e calcula os pesos da pele por distância ao osso (até 4 juntas por vértice, mistura suave).

    `humanoid`: 21 juntas (quadril, coluna, peito, pescoço, cabeça, ombros, braços, antebraços, mãos, coxas, canelas, pés), supondo o modelo em pé, olhando para +z, com os braços ao lado do corpo (pose A).
    `spine`: corrente vertical de `bones` juntas (árvores, vasos, personagens simples). `chain`: corrente ao longo do maior eixo (cobras, caudas, braços)."""
    if len(m.verts) > MAX_VERTS:
        raise ValueError(f"O modelo tem vértices demais para o esqueleto automático ({len(m.verts)}; o máximo é {MAX_VERTS}). Reduza a malha antes.")
    style = style if style in RIG_STYLES else "humanoid"
    out = m.copy()
    out.animations = []   # as animações antigas apontavam para as juntas antigas
    lo, hi = out.bbox()
    n = max(2, min(MAX_JOINTS, int(bones)))
    if style == "humanoid":
        joints = _humanoid(lo, hi)
    elif style == "spine":
        joints = _chain(lo, hi, n, 1, "coluna")
    else:
        ext = [hi[i] - lo[i] for i in range(3)]
        joints = _chain(lo, hi, n, ext.index(max(ext)), "elo")
    out.joints = joints
    # segmentos de cada junta: dela até cada filho (a folha ganha um pedaço no prolongamento do osso do pai)
    segs: List[List[Tuple[Vec, Vec]]] = []
    for k, jt in enumerate(joints):
        kids = [c for c in joints if c.parent == k]
        if kids:
            segs.append([(jt.pos, c.pos) for c in kids])
        else:
            pp = joints[jt.parent].pos if jt.parent >= 0 else (jt.pos[0], jt.pos[1] - 0.05, jt.pos[2])
            d = (jt.pos[0] - pp[0], jt.pos[1] - pp[1], jt.pos[2] - pp[2])
            segs.append([(jt.pos, (jt.pos[0] + d[0] * 0.6, jt.pos[1] + d[1] * 0.6, jt.pos[2] + d[2] * 0.6))])
    H = (hi[1] - lo[1]) or max(hi[0] - lo[0], hi[2] - lo[2]) or 1.0
    eps = 0.02 * H
    power = 1.5 + 4.5 * (1.0 - max(0.0, min(1.0, float(smooth))))   # smooth 1 → misturas largas; 0 → quase rígido
    flat = [(k, a, (b[0] - a[0], b[1] - a[1], b[2] - a[2])) for k, ss in enumerate(segs) for a, b in ss]
    flat = [(k, a, d, (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) or 1e-12) for k, a, d in flat]
    skin = []
    for v in out.verts:
        best: Dict[int, float] = {}
        for k, a, d, dd in flat:
            t = ((v[0] - a[0]) * d[0] + (v[1] - a[1]) * d[1] + (v[2] - a[2]) * d[2]) / dd
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            dx, dy, dz = v[0] - (a[0] + d[0] * t), v[1] - (a[1] + d[1] * t), v[2] - (a[2] + d[2] * t)
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if k not in best or dist < best[k]:
                best[k] = dist
        near = sorted(best.items(), key=lambda kv: kv[1])[:4]
        raw = [1.0 / (d + eps) ** power for _, d in near]
        s = sum(raw) or 1.0
        js = [k for k, _ in near] + [0] * (4 - len(near))
        ws = [r / s for r in raw] + [0.0] * (4 - len(near))
        skin.append((tuple(js), tuple(ws)))   # type: ignore[arg-type]
    out.skin = skin
    return out


# --------------------------------------------------------------------------- animação
ANIM_KINDS = ("spin", "bounce", "float", "pulse", "wobble", "sway", "walk", "wave", "idle")
NEEDS_SKELETON = ("sway", "walk", "wave", "idle")


def _times(duration: float, steps: int) -> List[float]:
    return [round(duration * i / steps, 4) for i in range(steps + 1)]


def animate(m: Model, kind: str = "spin", duration: float = 4.0, amplitude: float = 1.0, name: str = "") -> Model:
    """Cria uma animação em laço (o último quadro repete o primeiro). Substitui as animações que o modelo já tinha.

    Para o modelo todo (`spin`, `bounce`, `float`, `pulse`, `wobble`): sem esqueleto move o próprio modelo; com esqueleto move a junta raiz.
    Com esqueleto: `sway` (todas as juntas ondulam, em fase deslocada: caudas, cobras, árvores), `walk` (pernas e braços — estilo humanoide), `wave` (acena com o braço direito), `idle` (respira)."""
    kind = kind if kind in ANIM_KINDS else "spin"
    dur = max(0.2, min(60.0, float(duration)))
    amp = max(0.05, min(5.0, float(amplitude)))
    out = m.copy()
    skinned = bool(out.joints and out.skin is not None)
    if kind in NEEDS_SKELETON and not skinned:
        raise ValueError("Esta animação precisa de um esqueleto: ligue um nó «Esqueleto 3D» antes dele.")
    lo, hi = out.bbox()
    H = (hi[1] - lo[1]) or 1.0
    root_target: Tuple[str, int] = ("joint", next((k for k, j in enumerate(out.joints) if j.parent < 0), 0)) if skinned else ("root", 0)
    tracks: List[Dict[str, Any]] = []

    def track(target: Tuple[str, int], path: str, times: List[float], values: List[Tuple[float, ...]]) -> None:
        tracks.append({"target": target, "path": path, "times": times, "values": values})

    def rest(k: int) -> Vec:
        j = out.joints[k]
        pp = out.joints[j.parent].pos if j.parent >= 0 else (0.0, 0.0, 0.0)
        return (j.pos[0] - pp[0], j.pos[1] - pp[1], j.pos[2] - pp[2])

    if kind == "spin":
        n = 12
        ts = _times(dur, n)
        track(root_target, "rotation", ts, [q_axis((0, 1, 0), 360.0 * i / n) if i < n else (0.0, 0.0, 0.0, 1.0) for i in range(n + 1)])
    elif kind == "bounce":
        n = 24
        ts = _times(dur, n)
        base = rest(root_target[1]) if skinned else (0.0, 0.0, 0.0)
        track(root_target, "translation", ts, [(base[0], base[1] + amp * 0.25 * H * abs(math.sin(math.pi * 2 * (i / n))), base[2]) for i in range(n + 1)])
    elif kind == "float":
        n = 24
        ts = _times(dur, n)
        base = rest(root_target[1]) if skinned else (0.0, 0.0, 0.0)
        track(root_target, "translation", ts, [(base[0], base[1] + amp * 0.08 * H * math.sin(2 * math.pi * i / n), base[2]) for i in range(n + 1)])
        track(root_target, "rotation", ts, [q_axis((0, 1, 0), amp * 25 * math.sin(2 * math.pi * i / n)) for i in range(n + 1)])
    elif kind == "pulse":
        n = 16
        ts = _times(dur, n)
        track(root_target, "scale", ts, [(s, s, s) for s in (1 + amp * 0.12 * math.sin(2 * math.pi * i / n) for i in range(n + 1))])
    elif kind == "wobble":
        n = 24
        ts = _times(dur, n)
        track(root_target, "rotation", ts, [q_mul(q_axis((0, 0, 1), amp * 12 * math.sin(2 * math.pi * i / n)), q_axis((1, 0, 0), amp * 8 * math.sin(2 * math.pi * i / n + 1.2))) for i in range(n + 1)])
    elif kind == "sway":
        n = 24
        ts = _times(dur, n)
        for k, j in enumerate(out.joints):
            if j.parent < 0:
                continue
            d = rest(k)
            axis = (d[1], -d[0], 0.0)   # d × z: eixo perpendicular ao osso (e a z)
            if abs(axis[0]) + abs(axis[1]) < 1e-9:
                axis = (0.0, 1.0, 0.0)
            track(("joint", k), "rotation", ts, [q_axis(axis, amp * 14 * math.sin(2 * math.pi * i / n - 0.6 * k)) for i in range(n + 1)])
    elif kind == "walk":
        names = {j.name: k for k, j in enumerate(out.joints)}
        legs = [(names.get("coxa_e"), 1), (names.get("coxa_d"), -1)]
        knees = [(names.get("canela_e"), 1), (names.get("canela_d"), -1)]
        arms = [(names.get("braco_e"), -1), (names.get("braco_d"), 1)]
        if not any(k is not None for k, _ in legs + arms):
            raise ValueError("O esqueleto não tem pernas nem braços com nomes de humanoide: use o estilo «Humanoide» no nó Esqueleto 3D.")
        n = 24
        ts = _times(dur, n)
        for k, sg in legs:
            if k is not None:
                track(("joint", k), "rotation", ts, [q_axis((1, 0, 0), sg * amp * 30 * math.sin(2 * math.pi * i / n)) for i in range(n + 1)])
        for k, sg in knees:
            if k is not None:
                track(("joint", k), "rotation", ts, [q_axis((1, 0, 0), amp * 25 * max(0.0, -sg * math.sin(2 * math.pi * i / n))) for i in range(n + 1)])
        for k, sg in arms:
            if k is not None:
                track(("joint", k), "rotation", ts, [q_axis((1, 0, 0), sg * amp * 25 * math.sin(2 * math.pi * i / n)) for i in range(n + 1)])
        hip = names.get("quadril", root_target[1])
        b = rest(hip)
        track(("joint", hip), "translation", ts, [(b[0], b[1] + amp * 0.012 * H * abs(math.sin(2 * math.pi * i / n)), b[2]) for i in range(n + 1)])
    elif kind == "wave":
        names = {j.name: k for k, j in enumerate(out.joints)}
        arm, fore = names.get("braco_d"), names.get("antebraco_d")
        if arm is None:
            raise ValueError("O esqueleto não tem o braço direito com nome de humanoide: use o estilo «Humanoide» no nó Esqueleto 3D.")
        n = 24
        ts = _times(dur, n)
        up = -(100.0 + 35.0 * min(amp, 1.5))   # levanta o braço (rotação em z; o braço direito está em +x)
        track(("joint", arm), "rotation", ts, [q_axis((0, 0, 1), up * min(1.0, i / 4, (n - i) / 4)) for i in range(n + 1)])
        if fore is not None:
            track(("joint", fore), "rotation", ts, [q_axis((0, 0, 1), amp * 28 * math.sin(2 * math.pi * 3 * i / n)) for i in range(n + 1)])
    else:   # idle
        n = 24
        ts = _times(dur, n)
        names = {j.name: k for k, j in enumerate(out.joints)}
        target = names.get("peito", len(out.joints) // 2)
        track(("joint", target), "rotation", ts, [q_axis((1, 0, 0), amp * 2.5 * math.sin(2 * math.pi * i / n)) for i in range(n + 1)])
        head = names.get("cabeca")
        if head is not None:
            track(("joint", head), "rotation", ts, [q_axis((0, 1, 0), amp * 6 * math.sin(2 * math.pi * i / n + 0.8)) for i in range(n + 1)])
    out.animations = [{"name": name or kind, "duration": dur, "tracks": tracks}]
    return out


# --------------------------------------------------------------------------- textura: UV e padrões
PROJECTIONS = ("box", "planar", "cylindrical", "spherical")
PATTERNS = ("checker", "stripes", "bricks", "noise", "gradient", "wood")


def _vertex_normals(m: Model) -> List[Vec]:
    nrm = [[0.0, 0.0, 0.0] for _ in m.verts]
    for a, b, c in m.faces:
        A, B, C = m.verts[a], m.verts[b], m.verts[c]
        u, v = (B[0] - A[0], B[1] - A[1], B[2] - A[2]), (C[0] - A[0], C[1] - A[1], C[2] - A[2])
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        for i in (a, b, c):
            nrm[i][0] += n[0]
            nrm[i][1] += n[1]
            nrm[i][2] += n[2]
    return [tuple(x) for x in nrm]   # type: ignore[misc]


def project_uvs(m: Model, projection: str = "box", tile: float = 1.0, rotate: float = 0.0) -> Model:
    """Calcula as coordenadas de textura (UV) do modelo. `box` projeta cada face pelo eixo dominante da sua normal (duplica vértices nas arestas), `planar` de frente (plano xy), `cylindrical` em volta
    do eixo y, `spherical` em volta do centro. Triângulos que cruzam a emenda da projeção (cilíndrica/esférica) são refeitos com vértices próprios, para a textura não «voltar» na face."""
    out = m.copy()
    projection = projection if projection in PROJECTIONS else "box"
    lo, hi = out.bbox()
    ext = [max(1e-9, hi[i] - lo[i]) for i in range(3)]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    rot = math.radians(rotate)
    cr, sr = math.cos(rot), math.sin(rot)

    def finish(u: float, v: float) -> Tuple[float, float]:
        u, v = (u - 0.5) * tile, (v - 0.5) * tile
        return (u * cr - v * sr + 0.5 * tile, u * sr + v * cr + 0.5 * tile)

    def attach(nv: List[Vec], nf: List[Tuple[int, int, int]], src: List[int], uv: List[Tuple[float, float]]) -> None:
        out.verts, out.faces, out.uvs = nv, nf, uv
        if out.colors is not None:
            out.colors = [out.colors[i] for i in src]
        if out.skin is not None:
            out.skin = [out.skin[i] for i in src]

    if projection == "planar":
        out.uvs = [finish((v[0] - lo[0]) / ext[0], (v[1] - lo[1]) / ext[1]) for v in out.verts]
        return out
    if projection == "box":
        nv: List[Vec] = []
        src: List[int] = []
        uv: List[Tuple[float, float]] = []
        nf: List[Tuple[int, int, int]] = []
        for a, b, cc in out.faces:
            A, B, C = out.verts[a], out.verts[b], out.verts[cc]
            u, w = (B[0] - A[0], B[1] - A[1], B[2] - A[2]), (C[0] - A[0], C[1] - A[1], C[2] - A[2])
            n = (abs(u[1] * w[2] - u[2] * w[1]), abs(u[2] * w[0] - u[0] * w[2]), abs(u[0] * w[1] - u[1] * w[0]))
            ax = n.index(max(n))
            i0, i1 = {0: (2, 1), 1: (0, 2), 2: (0, 1)}[ax]
            base = len(nv)
            for vi in (a, b, cc):
                p = out.verts[vi]
                nv.append(p)
                src.append(vi)
                uv.append(finish((p[i0] - lo[i0]) / ext[i0], (p[i1] - lo[i1]) / ext[i1]))
            nf.append((base, base + 1, base + 2))
        attach(nv, nf, src, uv)
        return out
    # cilíndrica e esférica: u pelo ângulo em torno de y; v pela altura (cilindro) ou pela latitude (esfera)
    uu: List[float] = []
    vv: List[float] = []
    for p in out.verts:
        x, y, z = p[0] - c[0], p[1] - c[1], p[2] - c[2]
        uu.append(0.5 + math.atan2(x, z) / (2 * math.pi))
        vv.append((p[1] - lo[1]) / ext[1] if projection == "cylindrical" else 0.5 + math.atan2(y, math.hypot(x, z)) / math.pi)
    nv = list(out.verts)
    src = list(range(len(nv)))
    puv = [(u, v) for u, v in zip(uu, vv)]
    nf = []
    for a, b, cc in out.faces:
        ids = [a, b, cc]
        us = [puv[i][0] for i in ids]
        if max(us) - min(us) > 0.5:   # cruza a emenda: os vértices «do outro lado» ganham cópias com u + 1
            new = []
            for i in ids:
                if puv[i][0] < 0.5:
                    nv.append(out.verts[i])
                    src.append(i)
                    puv.append((puv[i][0] + 1.0, puv[i][1]))
                    new.append(len(nv) - 1)
                else:
                    new.append(i)
            nf.append((new[0], new[1], new[2]))
        else:
            nf.append((a, b, cc))
    attach(nv, nf, src, [finish(u, v) for u, v in puv])
    return out


def _hex(c: str) -> Tuple[int, int, int]:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def pattern_png(kind: str, c1: str = "#c0c0c0", c2: str = "#404040", size: int = 512, seed: int = 0) -> bytes:
    """Textura procedural (PNG RGB) sem dependências: xadrez, listras, tijolos, ruído, degradê ou madeira, entre as duas cores."""
    from . import procedural

    kind = kind if kind in PATTERNS else "checker"
    size = max(32, min(2048, int(size)))
    a, b = _hex(c1), _hex(c2)
    rnd = random.Random(seed)
    grid = 16
    lat = [[rnd.random() for _ in range(grid)] for _ in range(grid)]

    def vnoise(x: float, y: float) -> float:
        xi, yi = int(math.floor(x)), int(math.floor(y))
        fx, fy = x - xi, y - yi
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        g = lambda i, j: lat[j % grid][i % grid]  # noqa: E731
        top = g(xi, yi) * (1 - fx) + g(xi + 1, yi) * fx
        bot = g(xi, yi + 1) * (1 - fx) + g(xi + 1, yi + 1) * fx
        return top * (1 - fy) + bot * fy

    def fbm(x: float, y: float) -> float:
        return (vnoise(x, y) * 0.5 + vnoise(x * 2, y * 2) * 0.25 + vnoise(x * 4, y * 4) * 0.125 + vnoise(x * 8, y * 8) * 0.0625) / 0.9375

    def mix(t: float) -> Tuple[int, int, int]:
        t = 0.0 if t < 0 else 1.0 if t > 1 else t
        return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))

    buf = bytearray(size * size * 3)
    for y in range(size):
        fy = y / size
        row = y * size * 3
        for x in range(size):
            fx = x / size
            if kind == "checker":
                t = float((int(fx * 8) + int(fy * 8)) % 2)
            elif kind == "stripes":
                t = float(int(fx * 8) % 2)
            elif kind == "bricks":
                r = int(fy * 8)
                bx = (fx * 4 + (0.5 if r % 2 else 0.0)) % 1.0
                by = (fy * 8) % 1.0
                t = 1.0 if (bx < 0.06 or by < 0.1) else 0.0 + 0.25 * vnoise(fx * 40, fy * 40)
            elif kind == "noise":
                t = fbm(fx * 6, fy * 6)
            elif kind == "gradient":
                t = fy
            else:   # wood
                d = math.sqrt((fx - 0.5) ** 2 + ((fy - 0.5) * 0.15) ** 2) * 28 + fbm(fx * 4, fy * 4) * 3
                t = 0.5 + 0.5 * math.sin(d * 2 * math.pi)
            rgb = mix(t)
            i = row + x * 3
            buf[i], buf[i + 1], buf[i + 2] = rgb
    return procedural._png(size, size, buf)


def texturize(m: Model, image: Optional[bytes], projection: str = "box", tile: float = 1.0, rotate: float = 0.0, pattern: str = "checker", color1: str = "#c0c0c0", color2: str = "#404040",
              size: int = 512, tint: str = "#ffffff", metallic: float = 0.0, roughness: float = 0.8, keep_colors: bool = False, seed: int = 0) -> Model:
    """Põe uma textura no modelo: `image` (PNG/JPEG já pronto) ou, sem imagem, um padrão procedural. Recalcula as UVs (`project_uvs`) e ajusta o material. As cores por vértice saem (a menos que `keep_colors`),
    porque se multiplicariam pela textura e a escureceriam."""
    out = project_uvs(m, projection, tile, rotate)
    out.texture = image if image else pattern_png(pattern, color1, color2, size, seed)
    r, g, b = _hex(tint)
    out.tint = (r / 255.0, g / 255.0, b / 255.0, 1.0)
    out.metallic = max(0.0, min(1.0, float(metallic)))
    out.roughness = max(0.0, min(1.0, float(roughness)))
    if not keep_colors:
        out.colors = None
    return out


# --------------------------------------------------------------------------- pose (referência em Python do que o visualizador faz em JS)
def _slerp(a: Sequence[float], b: Sequence[float], t: float) -> List[float]:
    d = sum(x * y for x, y in zip(a, b))
    s = -1.0 if d < 0 else 1.0
    d *= s
    if d > 0.9995:
        r = [x + (s * y - x) * t for x, y in zip(a, b)]
        n = math.sqrt(sum(x * x for x in r)) or 1.0
        return [x / n for x in r]
    th = math.acos(min(1.0, d))
    sn = math.sin(th)
    wa, wb = math.sin((1 - t) * th) / sn, math.sin(t * th) / sn
    return [wa * x + wb * s * y for x, y in zip(a, b)]


def _sample(tr: Dict[str, Any], t: float) -> List[float]:
    ts, vs = tr["times"], tr["values"]
    if len(ts) == 1 or t <= ts[0]:
        return list(vs[0])
    if t >= ts[-1]:
        return list(vs[-1])
    i = 0
    while i < len(ts) - 2 and t >= ts[i + 1]:
        i += 1
    k = (t - ts[i]) / ((ts[i + 1] - ts[i]) or 1.0)
    a, b = vs[i], vs[i + 1]
    return _slerp(a, b, k) if tr["path"] == "rotation" else [x + (y - x) * k for x, y in zip(a, b)]


def pose(m: Model, t: float = 0.0) -> Tuple[List[Vec], List[Vec]]:
    """As posições dos vértices e das juntas no instante `t` (s) da primeira animação (em laço): pele linear de até 4 juntas e, por fim, as trilhas do modelo todo. É a referência de `poseModel`, em model_viewer.js."""
    clip = m.animations[0] if m.animations else None
    tt = (t % clip["duration"]) if clip and clip["duration"] > 0 else 0.0
    tracks = clip["tracks"] if clip else []

    def value(target: Tuple[str, int], T: List[float], Q: List[float], S: List[float]) -> Tuple[List[float], List[float], List[float]]:
        for tr in tracks:
            if tr["target"] == target:
                v = _sample(tr, tt)
                if tr["path"] == "translation":
                    T = v
                elif tr["path"] == "rotation":
                    Q = v
                else:
                    S = v
        return T, Q, S

    verts: List[Vec] = list(m.verts)
    joints: List[Vec] = []
    if m.joints and m.skin is not None:
        G: Dict[int, List[float]] = {}

        def glob(j: int) -> List[float]:
            if j not in G:
                jt = m.joints[j]
                pp = m.joints[jt.parent].pos if jt.parent >= 0 else (0.0, 0.0, 0.0)
                T, Q, S = value(("joint", j), [jt.pos[0] - pp[0], jt.pos[1] - pp[1], jt.pos[2] - pp[2]], [0.0, 0.0, 0.0, 1.0], [1.0, 1.0, 1.0])
                loc = _trs(T, Q, S)
                G[j] = _mmul(glob(jt.parent), loc) if jt.parent >= 0 else loc
            return G[j]
        SM = []
        for j, jt in enumerate(m.joints):
            SM.append(_mmul(glob(j), [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -jt.pos[0], -jt.pos[1], -jt.pos[2], 1]))
        joints = [(glob(j)[12], glob(j)[13], glob(j)[14]) for j in range(len(m.joints))]
        out: List[Vec] = []
        for v, (js, ws) in zip(m.verts, m.skin):
            tw = sum(w for w in ws if w > 0)
            if tw <= 1e-6:
                out.append(v)
                continue
            acc = [0.0, 0.0, 0.0]
            for j, w in zip(js, ws):
                if w > 0:
                    p = _apply(SM[j], v)
                    acc[0] += w * p[0]
                    acc[1] += w * p[1]
                    acc[2] += w * p[2]
            out.append((acc[0] / tw, acc[1] / tw, acc[2] / tw))
        verts = out
    root = [tr for tr in tracks if tr["target"][0] == "root"]
    if root:
        T, Q, S = value(("root", 0), [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], [1.0, 1.0, 1.0])
        M = _trs(T, Q, S)
        verts = [_apply(M, v) for v in verts]
        joints = [_apply(M, j) for j in joints]
    return verts, joints
