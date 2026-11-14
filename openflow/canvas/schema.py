"""Canvas: tipos de nó (com portas tipadas), validação do grafo, linha do tempo do Editor e modelos de partida.

Um Canvas é um fluxo simples (inspirado no ElevenLabs Flow): nós com uma saída e entradas tipadas, ligados por conexões.
Estilos ("Style Prompt" e "Style Folder") valem para o projeto todo; o nó "Editor" monta uma linha do tempo com mídias dos outros nós.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..util import new_id, now_iso, num, slugify, text
from . import nodes_ext

SCHEMA = "openflow.project.v1"
MAX_NODES, MAX_EDGES, MAX_CLIPS = 200, 600, 400
SIZES = (   # quadrado · paisagem · retrato (largura×altura); os modelos locais ajustam para múltiplos de 16 e o lado maior vai até MAX_SIDE
    "512x512", "768x768", "1024x1024", "1280x1280", "1536x1536", "2048x2048",
    "768x512", "1024x576", "1024x768", "1280x720", "1344x768", "1216x832", "1536x1024", "1536x864", "1920x1080", "2048x1152", "2048x1536", "2560x1080",
    "512x768", "576x1024", "768x1024", "720x1280", "768x1344", "832x1216", "1024x1536", "864x1536", "1080x1920", "1152x2048", "1536x2048")
ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4")
KINDS = ("image", "video", "audio", "text")
CAPS = ("image", "video", "sound", "voice", "stt")  # capacidades de provedores de mídia

# tipos: out = tipo da saída; ins = portas de entrada [(id, rótulo, aceita, múltipla)]
NODE_TYPES: Dict[str, Dict[str, Any]] = {
    "text": {"label": "Texto", "icon": "type", "out": "text", "ins": []},
    "llm": {"label": "Texto IA", "icon": "wand", "out": "text", "ins": [("prompt", "Entrada", ["text"], True), ("style", "Estilo", ["style"], True)]},
    "upload": {"label": "Mídia", "icon": "upload", "out": "media", "ins": []},
    "image": {"label": "Imagem", "icon": "image", "out": "image", "ins": [("prompt", "Prompt", ["text"], True), ("refs", "Referências", ["image", "video"], True), ("style", "Estilo", ["style"], True)]},
    "video": {"label": "Vídeo", "icon": "video", "out": "video", "ins": [("prompt", "Prompt", ["text"], True), ("image", "Imagem inicial", ["image", "video"], False), ("style", "Estilo", ["style"], True)]},
    "sound": {"label": "Som", "icon": "audio", "out": "audio", "ins": [("prompt", "Prompt", ["text"], True), ("style", "Estilo", ["style"], True)]},
    "voice": {"label": "Voz", "icon": "mic", "out": "audio", "ins": [("text", "Fala", ["text"], True), ("style", "Estilo", ["style"], True)]},
    "transcribe": {"label": "Transcrever", "icon": "doc", "out": "text", "ins": [("audio", "Áudio/vídeo", ["audio", "video"], False)]},
    "style_prompt": {"label": "Style Prompt", "icon": "palette", "out": "style", "ins": []},
    "style_folder": {"label": "Style Folder", "icon": "folder", "out": "style", "ins": []},
    "editor": {"label": "Editor", "icon": "film", "out": "video", "ins": [("clips", "Clipes", ["image", "video", "audio", "text"], True)]},
}
for _k, _v in nodes_ext.SPECS.items():  # v0.11: 5 nós novos por tipo (nodes_ext.py)
    NODE_TYPES[_k] = {"label": _v["label"], "icon": _v["icon"], "out": _v["out"], "ins": _v["ins"]}
GENERATORS = ("llm", "image", "video", "sound", "voice", "transcribe")  # nós que chamam um modelo
EXT_TYPES = tuple(nodes_ext.SPECS)  # nós novos: rodam ffmpeg/Python (só «Refinar com IA» usa o modelo de texto)
# ordem e grupos da paleta: Texto, Imagem, Vídeo, Som, Input, Output
PALETTE = [("Texto", ["text", "llm", "transcribe", "text_template", "text_join", "text_edit", "text_pick", "text_refine"]),
           ("Imagem", ["image", "img_resize", "img_filter", "img_text", "img_collage", "img_frame"]),
           ("Vídeo", ["video", "vid_trim", "vid_join", "vid_speed", "vid_look", "vid_slideshow"]),
           ("Som", ["sound", "voice", "aud_trim", "aud_mix", "aud_fx", "aud_from_video", "aud_loop"]),
           ("Input", ["upload", "style_prompt", "style_folder", "in_color", "in_silence", "in_url", "in_random", "in_vars"]),
           ("Output", ["editor", "out_export", "out_gif", "out_audio", "out_image", "out_gallery"])]


def compatible(out_type: str, accepts: List[str]) -> bool:
    """Uma saída `out_type` pode ligar numa porta que aceita `accepts`? O nó Mídia (upload) entrega "media" — um arquivo de imagem, vídeo
    ou áudio ainda não classificado — e pode ir a qualquer porta de mídia; o motor então só usa os arquivos do tipo certo."""
    if out_type in accepts:
        return True
    if out_type == "media":
        return any(a in accepts for a in ("image", "video", "audio", "media"))
    return out_type in ("image", "video", "audio") and "media" in accepts


def port_def(ntype: str, port: str) -> Optional[Dict[str, Any]]:
    for pid, label, accepts, multi in NODE_TYPES[ntype]["ins"]:
        if pid == port:
            return {"id": pid, "label": label, "accepts": accepts, "multi": multi}
    return None


def describe_types() -> List[Dict[str, Any]]:
    return [{"type": k, "label": v["label"], "icon": v["icon"], "out": v["out"], "group": next((g for g, ts in PALETTE if k in ts), ""),
             "ins": [{"id": i[0], "label": i[1], "accepts": i[2], "multi": i[3]} for i in v["ins"]]} for k, v in NODE_TYPES.items()]


# --------------------------------------------------------------------------- parâmetros por tipo

def _json_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) and len(str(v)) < 4000 else {}


def _files(v: Any) -> List[str]:
    return [text(i, "", 60) for i in (v if isinstance(v, list) else []) if text(i, "", 60)][:60]


# --- Style Folder: pastas e subpastas (v0.1) ---------------------------------------------------------------
MAX_FOLDERS, MAX_FOLDER_DEPTH, MAX_FOLDER_NAME = 60, 6, 40


def normalize_folders(raw: Any, _depth: int = 1, _budget: Optional[List[int]] = None, _ids: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    """Árvore de pastas do Style Folder: [{id, name, files, folders, enabled, open}]. Até 6 níveis e 60 pastas por nó; nomes únicos entre irmãs (um repetido ganha « (2)»).
    Uma pasta desligada (`enabled: false`) fica de fora do estilo, junto com tudo o que há dentro dela."""
    budget = _budget if _budget is not None else [MAX_FOLDERS]
    ids = _ids if _ids is not None else set()
    out: List[Dict[str, Any]] = []
    names: Set[str] = set()
    for f in raw if isinstance(raw, list) else []:
        if budget[0] <= 0 or _depth > MAX_FOLDER_DEPTH:
            break
        f = f if isinstance(f, dict) else {}
        budget[0] -= 1
        fid = text(f.get("id"), "", 24)
        if not re.match(r"^[\w-]+$", fid) or fid in ids:
            fid = new_id("f_")
        ids.add(fid)
        name = text(f.get("name"), "Pasta", MAX_FOLDER_NAME).replace("/", "-").replace("\\", "-") or "Pasta"
        base, n = name, 2
        while name.lower() in names:
            suffix = f" ({n})"
            name = base[:MAX_FOLDER_NAME - len(suffix)] + suffix
            n += 1
        names.add(name.lower())
        out.append({"id": fid, "name": name, "files": _files(f.get("files")), "folders": normalize_folders(f.get("folders"), _depth + 1, budget, ids),
                    "enabled": f.get("enabled", True) is not False, "open": f.get("open", True) is not False})
    return out


def folder_paths(folders: List[Dict[str, Any]], prefix: Optional[List[str]] = None, only_enabled: bool = True) -> List[Tuple[List[str], str]]:
    """Todos os arquivos das pastas, na ordem da árvore: [(caminho da pasta, id do arquivo)]; com `only_enabled`, pastas desligadas (e o que há dentro) ficam de fora."""
    out: List[Tuple[List[str], str]] = []
    for f in folders:
        if only_enabled and not f.get("enabled", True):
            continue
        path = (prefix or []) + [f["name"]]
        out += [(path, fid) for fid in f["files"]]
        out += folder_paths(f["folders"], path, only_enabled)
    return out


def style_files(params: Dict[str, Any]) -> List[Tuple[List[str], str]]:
    """Os arquivos que valem como estilo num Style Folder: os da raiz e os das pastas ligadas: [(caminho da pasta ([] = raiz), id do arquivo)]. Sem repetir arquivo."""
    seen: Set[str] = set()
    out: List[Tuple[List[str], str]] = []
    for path, fid in [([], i) for i in params.get("files", [])] + folder_paths(params.get("folders", [])):
        if fid not in seen:
            seen.add(fid)
            out.append((path, fid))
    return out


def prune_folder_files(folders: List[Dict[str, Any]], keep: Set[str]) -> None:
    """Tira das pastas (recursivamente) os arquivos que não existem mais no projeto."""
    for f in folders:
        f["files"] = [i for i in f["files"] if i in keep]
        prune_folder_files(f["folders"], keep)


def all_folder_files(folders: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for f in folders:
        out += f["files"] + all_folder_files(f["folders"])
    return out


def find_folder(folders: List[Dict[str, Any]], fid: str) -> Optional[Dict[str, Any]]:
    for f in folders:
        if f["id"] == fid:
            return f
        hit = find_folder(f["folders"], fid)
        if hit:
            return hit
    return None


def _color(v: Any, d: str) -> str:
    v = str(v or "")
    return v.lower() if re.match(r"^#[0-9a-fA-F]{6}$", v) else d


def normalize_timeline(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    tracks, ids = [], set()
    for t in (raw.get("tracks") if isinstance(raw.get("tracks"), list) else [])[:12]:
        t = t if isinstance(t, dict) else {}
        tid = slugify(t.get("id") or "", "", 16).replace("-", "_") or f"t{len(tracks) + 1}"
        kind = t.get("kind") if t.get("kind") in ("video", "audio", "text") else "video"
        if tid in ids:
            continue
        ids.add(tid)
        tracks.append({"id": tid, "kind": kind, "name": text(t.get("name"), tid.upper(), 12), "muted": bool(t.get("muted")), "hidden": bool(t.get("hidden"))})
    if not tracks:
        tracks = [{"id": "t_v1", "kind": "video", "name": "V1", "muted": False, "hidden": False}, {"id": "t_a1", "kind": "audio", "name": "A1", "muted": False, "hidden": False}]
    kinds = {t["id"]: t["kind"] for t in tracks}
    clips = []
    for c in (raw.get("clips") if isinstance(raw.get("clips"), list) else [])[:MAX_CLIPS]:
        c = c if isinstance(c, dict) else {}
        tr = c.get("track") if c.get("track") in kinds else None
        if not tr:
            continue
        clips.append({
            "id": slugify(c.get("id") or "", "", 24).replace("-", "_") or new_id("c_"), "track": tr, "asset": text(c.get("asset"), "", 60) if kinds[tr] != "text" else "",
            "node": text(c.get("node"), "", 24) if kinds[tr] != "text" else "", "idx": int(num(c.get("idx"), 0, 0, 50)),
            "start": round(num(c.get("start"), 0, 0, 36000), 3), "dur": round(num(c.get("dur"), 3, 0.1, 36000), 3), "in": round(num(c.get("in"), 0, 0, 36000), 3),
            "volume": round(num(c.get("volume"), 1, 0, 2), 2), "fade_in": round(num(c.get("fade_in"), 0, 0, 30), 2), "fade_out": round(num(c.get("fade_out"), 0, 0, 30), 2),
            "opacity": round(num(c.get("opacity"), 1, 0, 1), 2), "fit": c.get("fit") if c.get("fit") in ("contain", "cover", "stretch") else "contain",
            "x": round(num(c.get("x"), 0, -1, 1), 3), "y": round(num(c.get("y"), 0, -1, 1), 3), "scale": round(num(c.get("scale"), 1, 0.1, 4), 2),
            "text": text(c.get("text"), "", 300) if kinds[tr] == "text" else "", "size": int(num(c.get("size"), 48, 8, 300)), "color": _color(c.get("color"), "#ffffff"),
            "bg": _color(c.get("bg"), "") if c.get("bg") else "", "pos": c.get("pos") if c.get("pos") in ("top", "center", "bottom") else "bottom",
        })
    clips = [c for c in clips if kinds[c["track"]] == "text" or c["asset"] or c["node"]]  # "node": segue a saída mais recente de um nó ligado
    return {"tracks": tracks, "clips": clips, "duration": round(max([c["start"] + c["dur"] for c in clips] + [0]), 3)}


VIDEO_RESOLUTIONS = (0, 480, 720, 1080)   # lado maior em px; 0 = automática (o que o modelo/provedor escolher)


def _resolution(v: Any) -> int:
    n = int(num(v, 0, 0, 4096))
    return n if n in VIDEO_RESOLUTIONS else 0


def normalize_params(ntype: str, p: Any) -> Dict[str, Any]:
    p = p if isinstance(p, dict) else {}
    prov = text(p.get("provider"), "", 40)
    model = text(p.get("model"), "", 160)
    if ntype == "text":
        return {"text": text(p.get("text"), "", 20000)}
    if ntype == "llm":
        return {"instruction": text(p.get("instruction"), "", 4000), "temperature": round(num(p.get("temperature"), 0.7, 0, 1.5), 2), "provider": prov, "ignore_global_styles": bool(p.get("ignore_global_styles"))}
    if ntype == "upload":
        return {"files": _files(p.get("files"))}
    if ntype == "image":
        return {"prompt": text(p.get("prompt"), "", 6000), "mode": "edit" if p.get("mode") == "edit" else "generate", "size": p.get("size") if p.get("size") in SIZES else "1024x1024",
                "count": int(num(p.get("count"), 1, 1, 4)), "seed": int(num(p.get("seed"), 0, 0, 2 ** 31)), "negative": text(p.get("negative"), "", 1000), "provider": prov, "model": model,
                "extra": _json_dict(p.get("extra")), "ignore_global_styles": bool(p.get("ignore_global_styles"))}
    if ntype == "video":
        return {"prompt": text(p.get("prompt"), "", 6000), "duration": int(num(p.get("duration"), 5, 1, 30)), "aspect": p.get("aspect") if p.get("aspect") in ASPECTS else "16:9", "resolution": _resolution(p.get("resolution")), "provider": prov, "model": model,
                "extra": _json_dict(p.get("extra")), "ignore_global_styles": bool(p.get("ignore_global_styles"))}
    if ntype == "sound":
        return {"prompt": text(p.get("prompt"), "", 2000), "kind": "music" if p.get("kind") == "music" else "sfx", "duration": int(num(p.get("duration"), 5, 1, 120)), "provider": prov, "model": model,
                "extra": _json_dict(p.get("extra")), "ignore_global_styles": bool(p.get("ignore_global_styles"))}
    if ntype == "voice":
        return {"text": text(p.get("text"), "", 8000), "voice": text(p.get("voice"), "", 80), "speed": round(num(p.get("speed"), 1, 0.5, 2), 2), "provider": prov, "model": model,
                "extra": _json_dict(p.get("extra")), "ignore_global_styles": bool(p.get("ignore_global_styles"))}
    if ntype == "transcribe":
        return {"provider": prov, "model": model, "language": text(p.get("language"), "", 12)}
    if ntype == "style_prompt":
        return {"text": text(p.get("text"), "", 6000), "global": p.get("global", True) is not False}
    if ntype == "style_folder":
        return {"files": _files(p.get("files")), "folders": normalize_folders(p.get("folders")), "global": p.get("global", True) is not False}
    if ntype in nodes_ext.SPECS:
        return nodes_ext.normalize(ntype, p)
    if ntype == "editor":
        return {"timeline": normalize_timeline(p.get("timeline")), "width": int(num(p.get("width"), 1280, 160, 3840)), "height": int(num(p.get("height"), 720, 160, 2160)),
                "fps": int(num(p.get("fps"), 30, 10, 60)), "bg": _color(p.get("bg"), "#000000")}
    return {}


def normalize_result(r: Any) -> Dict[str, Any]:
    r = r if isinstance(r, dict) else {}
    state = r.get("state") if r.get("state") in ("idle", "running", "done", "error") else "idle"
    return {"state": state, "assets": _files(r.get("assets")), "text": text(r.get("text"), "", 40000), "error": text(r.get("error"), "", 1600), "hash": text(r.get("hash"), "", 64),
            "ts": text(r.get("ts"), "", 40), "digest": text(r.get("digest"), "", 4000), "digest_key": text(r.get("digest_key"), "", 64)}


def normalize_node(n: Any, keep_result: bool = True) -> Optional[Dict[str, Any]]:
    n = n if isinstance(n, dict) else {}
    ntype = n.get("type")
    if ntype not in NODE_TYPES:
        return None
    nid = slugify(n.get("id") or "", "", 24).replace("-", "_") or new_id("n_")
    out = {"id": nid, "type": ntype, "x": round(num(n.get("x"), 0, -20000, 20000), 1), "y": round(num(n.get("y"), 0, -20000, 20000), 1), "w": int(num(n.get("w"), 280, 200, 520)),
           "title": text(n.get("title"), "", 40), "params": normalize_params(ntype, n.get("params"))}
    out["result"] = normalize_result(n.get("result")) if keep_result else normalize_result({})
    return out


def _creates_cycle(edges: List[Dict[str, str]], frm: str, to: str) -> bool:
    adj: Dict[str, List[str]] = {}
    for e in edges:
        adj.setdefault(e["from"], []).append(e["to"])
    stack, seen = [to], set()
    while stack:
        cur = stack.pop()
        if cur == frm:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack += adj.get(cur, [])
    return False


def normalize_edges(edges: Any, nodes: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    by_id = {n["id"]: n for n in nodes}
    out: List[Dict[str, str]] = []
    seen: Set[tuple] = set()
    for e in (edges if isinstance(edges, list) else [])[:MAX_EDGES * 2]:
        e = e if isinstance(e, dict) else {}
        a, b, port = text(e.get("from"), "", 24), text(e.get("to"), "", 24), text(e.get("port"), "", 24)
        if a not in by_id or b not in by_id or a == b:
            continue
        pd = port_def(by_id[b]["type"], port)
        if not pd or not compatible(NODE_TYPES[by_id[a]["type"]]["out"], pd["accepts"]):
            continue
        key = (a, b, port)
        if key in seen:
            continue
        if not pd["multi"] and any(x["to"] == b and x["port"] == port for x in out):  # porta simples: mantém a primeira
            continue
        if _creates_cycle(out, a, b):
            continue
        seen.add(key)
        out.append({"id": text(e.get("id"), "", 24) or new_id("e_"), "from": a, "to": b, "port": port})
        if len(out) >= MAX_EDGES:
            break
    return out


def normalize_asset(a: Any) -> Optional[Dict[str, Any]]:
    a = a if isinstance(a, dict) else {}
    aid = text(a.get("id"), "", 60)
    fname = text(a.get("file"), "", 140)
    kind = a.get("kind") if a.get("kind") in KINDS else ""
    if not aid or not kind or not re.match(r"^[\w][\w.-]*$", fname) or ".." in fname:
        return None
    return {"id": aid, "kind": kind, "mime": text(a.get("mime"), "application/octet-stream", 80), "name": text(a.get("name"), fname, 120), "file": fname,
            "bytes": int(num(a.get("bytes"), 0, 0, 2 ** 40)), "w": int(num(a.get("w"), 0, 0, 20000)), "h": int(num(a.get("h"), 0, 0, 20000)),
            "duration": round(num(a.get("duration"), 0, 0, 100000), 2), "created": text(a.get("created"), "", 40), "node": text(a.get("node"), "", 24),
            "prompt": text(a.get("prompt"), "", 600), "provider": text(a.get("provider"), "", 40), "model": text(a.get("model"), "", 120)}


def normalize_canvas(data: Any, keep_id: Optional[str] = None) -> Dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    nodes, ids = [], set()
    for n in (data.get("nodes") if isinstance(data.get("nodes"), list) else [])[:MAX_NODES]:
        nn = normalize_node(n)
        if nn and nn["id"] not in ids:
            ids.add(nn["id"])
            nodes.append(nn)
    vp = data.get("viewport") if isinstance(data.get("viewport"), dict) else {}
    assets, aids = [], set()
    for a in (data.get("assets") if isinstance(data.get("assets"), list) else [])[:4000]:
        na = normalize_asset(a)
        if na and na["id"] not in aids:
            aids.add(na["id"])
            assets.append(na)
    for n in nodes:  # arquivos que não existem mais saem dos nós
        for key in ("files",):
            if key in n["params"]:
                n["params"][key] = [f for f in n["params"][key] if f in aids]
        if "folders" in n["params"]:
            prune_folder_files(n["params"]["folders"], aids)
        n["result"]["assets"] = [f for f in n["result"]["assets"] if f in aids]
    return {"schema": SCHEMA, "id": keep_id or text(data.get("id"), "", 60), "name": text(data.get("name"), "Novo canvas", 80), "description": text(data.get("description"), "", 400),
            "viewport": {"x": round(num(vp.get("x"), 0, -100000, 100000), 1), "y": round(num(vp.get("y"), 0, -100000, 100000), 1), "zoom": round(num(vp.get("zoom"), 1, 0.2, 2.5), 3)},
            "nodes": nodes, "edges": normalize_edges(data.get("edges"), nodes), "assets": assets, "created": text(data.get("created"), "", 40), "updated": text(data.get("updated"), "", 40)}


# --------------------------------------------------------------------------- modelos de partida


def _n(ntype: str, x: float, y: float, **params: Any) -> Dict[str, Any]:
    return {"id": new_id("n_"), "type": ntype, "x": x, "y": y, "params": params}


def _e(a: Dict[str, Any], b: Dict[str, Any], port: str) -> Dict[str, str]:
    return {"id": new_id("e_"), "from": a["id"], "to": b["id"], "port": port}


TEMPLATES = [
    {"id": "blank", "label": "Em branco", "hint": "Um canvas vazio: adicione os nós que quiser."},
    {"id": "text_image", "label": "Texto → Imagem", "hint": "Um prompt de texto que vira uma imagem."},
    {"id": "image_video", "label": "Texto → Imagem → Vídeo", "hint": "Gera uma imagem e anima em um vídeo curto."},
    {"id": "styled", "label": "Com estilo do projeto", "hint": "Style Prompt + prompt + imagem: o estilo vale para todo o canvas."},
    {"id": "scene", "label": "Cena completa (imagem, voz e Editor)", "hint": "Roteiro → imagem → vídeo + narração + som, tudo montado no Editor."},
]


def build_template(template: str, prompt: str = "") -> Dict[str, Any]:
    prompt = text(prompt, "", 6000)
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []
    if template == "text_image":
        t_, im = _n("text", 60, 120, text=prompt or "Uma floresta ao amanhecer, névoa suave"), _n("image", 420, 80)
        nodes, edges = [t_, im], [_e(t_, im, "prompt")]
    elif template == "image_video":
        t_, im, vd = _n("text", 60, 160, text=prompt or "Um astronauta caminhando num planeta de cristais"), _n("image", 420, 100), _n("video", 800, 100, duration=5)
        nodes, edges = [t_, im, vd], [_e(t_, im, "prompt"), _e(t_, vd, "prompt"), _e(im, vd, "image")]
    elif template == "styled":
        st, t_, im = _n("style_prompt", 60, 40, text="Ilustração em aquarela, cores suaves, traço delicado", **{"global": True}), _n("text", 60, 280, text=prompt or "Um gato dormindo numa janela"), _n("image", 420, 160)
        nodes, edges = [st, t_, im], [_e(t_, im, "prompt")]
    elif template == "scene":
        st = _n("style_prompt", 40, 20, text="Cinematográfico, luz natural, cores quentes", **{"global": True})
        sc = _n("text", 40, 300, text=prompt or "Uma faroleira acende o farol numa noite de tempestade")
        im, vd = _n("image", 400, 20), _n("video", 780, 20, duration=5)
        vo = _n("voice", 400, 700, text="A tempestade chegou, mas a luz do farol não vai se apagar.")
        sf = _n("sound", 780, 640, kind="sfx", prompt="trovão distante e ondas batendo nas rochas", duration=8)
        ed = _n("editor", 1160, 260)
        nodes = [st, sc, im, vd, vo, sf, ed]
        edges = [_e(sc, im, "prompt"), _e(sc, vd, "prompt"), _e(im, vd, "image"), _e(vd, ed, "clips"), _e(vo, ed, "clips"), _e(sf, ed, "clips")]
    return {"nodes": nodes, "edges": edges}
