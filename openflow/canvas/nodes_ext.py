"""Canvas v0.11: 30 nós novos (5 por tipo) — Texto, Imagem, Vídeo, Som, Input e Output.

Quase todos são determinísticos (ffmpeg e Python, sem modelo de IA nem chave): só «Refinar com IA» usa o modelo de texto. Todos têm portas tipadas que se encaixam
nas dos nós antigos: texto alimenta imagem/vídeo/som/voz, vídeo vira imagem (quadro) ou áudio, imagens viram vídeo, tudo vai para o Editor e para as saídas.
`SPECS` descreve cada nó (tipo, ícone, saída, portas, grupo), `normalize()` valida os parâmetros e `RUNNERS` executa.
"""
from __future__ import annotations

import datetime
import random
import re
import shutil
import subprocess
import tempfile
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..providers import ProviderError, build_provider
from ..util import num, text
from .render import GRADES, _esc_path, _run, _tempo, find_font, has_audio, render_timeline, still_path

IMG, VID, AUD = ["image", "video"], ["video"], ["audio", "video"]
# tipo → (rótulo, ícone, saída, portas [(id, rótulo, aceita, múltipla)], grupo)
SPECS: Dict[str, Dict[str, Any]] = {
    # ---- Texto
    "text_template": {"label": "Modelo de texto", "icon": "doc", "out": "text", "group": "Texto", "ins": [("vars", "Variáveis", ["text"], True)]},
    "text_join": {"label": "Juntar textos", "icon": "plus", "out": "text", "group": "Texto", "ins": [("texts", "Textos", ["text"], True)]},
    "text_edit": {"label": "Editar texto", "icon": "type", "out": "text", "group": "Texto", "ins": [("text", "Texto", ["text"], True)]},
    "text_pick": {"label": "Escolher trecho", "icon": "doc", "out": "text", "group": "Texto", "ins": [("text", "Texto", ["text"], True)]},
    "text_refine": {"label": "Refinar com IA", "icon": "wand", "out": "text", "group": "Texto", "ins": [("text", "Texto", ["text"], True), ("style", "Estilo", ["style"], True)]},
    "text_extract": {"label": "Extrair do texto", "icon": "doc", "out": "text", "group": "Texto", "ins": [("text", "Texto", ["text"], True)]},
    "text_count": {"label": "Contar texto", "icon": "type", "out": "text", "group": "Texto", "ins": [("text", "Texto", ["text"], True)]},
    # ---- Imagem
    "img_resize": {"label": "Redimensionar", "icon": "image", "out": "image", "group": "Imagem", "ins": [("image", "Imagem", IMG, False)]},
    "img_filter": {"label": "Filtros e cor", "icon": "palette", "out": "image", "group": "Imagem", "ins": [("image", "Imagem", IMG, False)]},
    "img_text": {"label": "Texto na imagem", "icon": "type", "out": "image", "group": "Imagem", "ins": [("image", "Imagem", IMG, False), ("text", "Texto", ["text"], True)]},
    "img_collage": {"label": "Colagem", "icon": "image", "out": "image", "group": "Imagem", "ins": [("images", "Imagens", IMG, True)]},
    "img_frame": {"label": "Quadro do vídeo", "icon": "video", "out": "image", "group": "Imagem", "ins": [("video", "Vídeo", VID, False)]},
    "img_crop": {"label": "Recortar imagem", "icon": "scissors", "out": "image", "group": "Imagem", "ins": [("image", "Imagem", IMG, False)]},
    "img_watermark": {"label": "Marca d'água", "icon": "image", "out": "image", "group": "Imagem", "ins": [("image", "Imagem", IMG, False), ("logo", "Marca", ["image"], False)]},
    "char_sheet": {"label": "Ficha de personagem", "icon": "image", "out": "text", "group": "Imagem", "ins": [("text", "Descrição", ["text"], True), ("style", "Estilo", ["style"], True)]},
    "comic_page": {"label": "Página de quadrinhos", "icon": "image", "out": "text", "group": "Imagem", "ins": [("story", "Roteiro", ["text"], True), ("characters", "Personagens", ["text"], True), ("style", "Estilo", ["style"], True)]},
    # ---- Vídeo
    "vid_trim": {"label": "Cortar vídeo", "icon": "film", "out": "video", "group": "Vídeo", "ins": [("video", "Vídeo", VID, False)]},
    "vid_join": {"label": "Juntar clipes", "icon": "film", "out": "video", "group": "Vídeo", "ins": [("clips", "Clipes", ["video", "image"], True)]},
    "vid_speed": {"label": "Velocidade", "icon": "video", "out": "video", "group": "Vídeo", "ins": [("video", "Vídeo", VID, False)]},
    "vid_look": {"label": "Visual do vídeo", "icon": "palette", "out": "video", "group": "Vídeo", "ins": [("video", "Vídeo", VID, False)]},
    "vid_slideshow": {"label": "Imagens em vídeo", "icon": "film", "out": "video", "group": "Vídeo", "ins": [("images", "Imagens", IMG, True), ("audio", "Áudio", ["audio"], True)]},
    "vid_reframe": {"label": "Mudar a proporção", "icon": "film", "out": "video", "group": "Vídeo", "ins": [("video", "Vídeo", VID, False)]},
    "vid_loop": {"label": "Repetir vídeo", "icon": "refresh", "out": "video", "group": "Vídeo", "ins": [("video", "Vídeo", VID, False)]},
    "vid_audio": {"label": "Áudio no vídeo", "icon": "audio", "out": "video", "group": "Vídeo", "ins": [("video", "Vídeo", VID, False), ("audio", "Áudio", ["audio"], True)]},
    # ---- Som
    "aud_trim": {"label": "Cortar áudio", "icon": "audio", "out": "audio", "group": "Som", "ins": [("audio", "Áudio", AUD, False)]},
    "aud_mix": {"label": "Misturar áudios", "icon": "audio", "out": "audio", "group": "Som", "ins": [("audios", "Áudios", AUD, True)]},
    "aud_fx": {"label": "Efeitos de áudio", "icon": "audio", "out": "audio", "group": "Som", "ins": [("audio", "Áudio", AUD, False)]},
    "aud_from_video": {"label": "Áudio do vídeo", "icon": "audio", "out": "audio", "group": "Som", "ins": [("video", "Vídeo", VID, False)]},
    "aud_loop": {"label": "Repetir áudio", "icon": "refresh", "out": "audio", "group": "Som", "ins": [("audio", "Áudio", AUD, False)]},
    "aud_silence_cut": {"label": "Tirar silêncios", "icon": "audio", "out": "audio", "group": "Som", "ins": [("audio", "Áudio", AUD, False)]},
    # ---- Input
    "in_color": {"label": "Cor e degradê", "icon": "palette", "out": "image", "group": "Input", "ins": []},
    "in_silence": {"label": "Silêncio", "icon": "audio", "out": "audio", "group": "Input", "ins": []},
    "in_url": {"label": "Link (URL)", "icon": "upload", "out": "media", "group": "Input", "ins": []},
    "in_random": {"label": "Sorteio de texto", "icon": "wand", "out": "text", "group": "Input", "ins": []},
    "in_vars": {"label": "Data e projeto", "icon": "doc", "out": "text", "group": "Input", "ins": []},
    "in_pattern": {"label": "Padrão e textura", "icon": "palette", "out": "image", "group": "Input", "ins": []},
    # ---- Output
    "out_export": {"label": "Vídeo final", "icon": "film", "out": "video", "group": "Output", "ins": [("video", "Vídeo", ["video", "image"], False), ("audio", "Áudio", ["audio"], True), ("captions", "Legendas", ["text"], True)]},
    "out_gif": {"label": "GIF animado", "icon": "film", "out": "image", "group": "Output", "ins": [("video", "Vídeo", VID, False)]},
    "out_audio": {"label": "Áudio final", "icon": "audio", "out": "audio", "group": "Output", "ins": [("audio", "Áudio", AUD, True)]},
    "out_image": {"label": "Imagem final", "icon": "image", "out": "image", "group": "Output", "ins": [("image", "Imagem", IMG, False)]},
    "out_thumbnail": {"label": "Miniatura com título", "icon": "image", "out": "image", "group": "Output", "ins": [("image", "Imagem", IMG, False), ("text", "Título", ["text"], True)]},
    "out_gallery": {"label": "Galeria", "icon": "folder", "out": "media", "group": "Output", "ins": [("items", "Itens", ["image", "video", "audio", "text", "model3d"], True)]},
}
TEXT_OUT = {k for k, v in SPECS.items() if v["out"] == "text"}  # entregam texto; os demais entregam arquivos

PRESETS_IMG = ("none", "bw", "sepia", "vivid", "warm", "cool", "cinematic", "vhs", "phonk", "blur", "sharpen", "vignette", "invert")
FILTER_FX = dict(GRADES, sepia="colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131", blur="gblur=sigma=4", sharpen="unsharp=5:5:1.2",
                 vignette="vignette=PI/4", invert="negate", none="")
SEPARATORS = {"paragraph": "\n\n", "line": "\n", "space": " ", "comma": ", ", "dash": " — "}
TEXT_OPS = ("upper", "lower", "title", "trim", "dedupe", "sort", "reverse", "number", "no_empty", "replace")
PICK_MODES = ("lines", "sentences", "paragraphs", "words")
REFINE_MODES = ("improve", "translate", "summarize", "expand", "fix", "scenes", "captions")
EXTRACT_WHAT = ("links", "emails", "hashtags", "numbers", "quotes", "words_caps", "regex")
SHEET_VIEWS = ("front", "side", "back", "three_quarter", "face", "full_body")
SHEET_EXTRAS = ("expressions", "palette", "outfit", "props", "poses", "scale")
SHEET_POSES = {"neutral": ("neutral standing pose", "pose neutra em pé"), "tpose": ("T-pose / A-pose", "pose em T ou A"), "action": ("dynamic action pose", "pose de ação dinâmica"), "relaxed": ("relaxed casual pose", "pose descontraída")}
SHEET_BG = {"white": ("plain white background", "fundo branco liso"), "gray": ("neutral light gray background", "fundo cinza claro neutro"), "paper": ("off-white drawing-paper background", "fundo de papel de desenho"), "dark": ("dark neutral background", "fundo escuro neutro")}
COMIC_FORMATS = {"page": ("a full comic book page", "uma página inteira de quadrinhos", "portrait 2:3"), "strip": ("a horizontal comic strip", "uma tirinha horizontal", "wide 3:1"),
                 "webtoon": ("a vertical webtoon scroll", "um episódio vertical estilo webtoon", "tall 1:3"), "koma": ("a four-panel vertical strip (yonkoma)", "uma tira vertical de quatro quadros (yonkoma)", "tall 1:2"),
                 "splash": ("a single splash panel", "um único quadro de página inteira (splash)", "portrait 2:3")}
COMIC_STYLES = {"comic": ("American comic book, bold inks and dynamic shading", "quadrinho americano, traço forte e sombras dinâmicas"), "manga": ("Japanese manga, clean linework and screentones", "mangá japonês, traço limpo e retículas"),
                "franco": ("Franco-Belgian bande dessinée, ligne claire", "quadrinho franco-belga, ligne claire"), "webtoon": ("modern digital webtoon, soft colors", "webtoon digital moderno, cores suaves"),
                "cartoon": ("simple humorous cartoon strip", "tirinha de humor com desenho simples"), "indie": ("indie hand-drawn comic, sketchy lines", "quadrinho independente desenhado à mão, traço rabiscado")}
SHEET_LABELS = {
    "front": ("front view", "vista frontal"), "side": ("side view", "vista lateral"), "back": ("back view", "vista de costas"), "three_quarter": ("three-quarter view", "vista de três quartos"),
    "face": ("close-up of the face", "close do rosto"), "full_body": ("full body", "corpo inteiro"), "expressions": ("a set of facial expressions (happy, sad, angry, surprised)", "uma série de expressões faciais (feliz, triste, bravo, surpreso)"),
    "palette": ("the color palette as swatches", "a paleta de cores em amostras"), "outfit": ("outfit and clothing detail callouts", "detalhes da roupa e dos acessórios"),
    "props": ("the character's props and items", "os objetos e itens do personagem"), "poses": ("a few extra action poses", "algumas poses de ação extras"), "scale": ("a height/scale comparison chart", "uma comparação de altura e escala")}


def _multi(v: Any, allowed: Tuple[str, ...], default: Tuple[str, ...]) -> List[str]:
    if not isinstance(v, list):
        return list(default)
    return [x for x in allowed if x in v]


AUD_FX = ("none", "louder", "quieter", "faster", "slower", "reverse", "echo", "telephone", "bass", "normalize")


def _color(v: Any, d: str) -> str:
    v = str(v or "")
    return v.lower() if re.match(r"^#[0-9a-fA-F]{6}$", v) else d


def _pick(v: Any, options: Tuple[str, ...], d: str) -> str:
    return v if v in options else d


def normalize(t: str, p: Dict[str, Any]) -> Dict[str, Any]:
    n = lambda k, d, lo, hi: num(p.get(k), d, lo, hi)  # noqa: E731
    if t == "text_template":
        return {"template": text(p.get("template"), "{1}", 6000)}
    if t == "text_join":
        return {"sep": _pick(p.get("sep"), tuple(SEPARATORS) + ("custom",), "paragraph"), "custom": str(p.get("custom") or "")[:40], "numbering": bool(p.get("numbering")),
                "prefix": text(p.get("prefix"), "", 200), "suffix": text(p.get("suffix"), "", 200)}
    if t == "text_edit":
        return {"op": _pick(p.get("op"), TEXT_OPS, "trim"), "find": text(p.get("find"), "", 200), "replace": text(p.get("replace"), "", 200)}
    if t == "text_pick":
        return {"mode": _pick(p.get("mode"), PICK_MODES, "lines"), "index": int(n("index", 1, 0, 9999)), "count": int(n("count", 1, 1, 999)), "random": bool(p.get("random")), "seed": int(n("seed", 0, 0, 2 ** 31))}
    if t == "text_refine":
        return {"mode": _pick(p.get("mode"), REFINE_MODES, "improve"), "language": text(p.get("language"), "inglês", 30), "instruction": text(p.get("instruction"), "", 1000),
                "provider": text(p.get("provider"), "", 40)}
    if t == "text_extract":
        return {"what": _pick(p.get("what"), EXTRACT_WHAT, "links"), "pattern": text(p.get("pattern"), "", 200), "joiner": _pick(p.get("joiner"), ("line", "comma", "space"), "line"), "limit": int(n("limit", 0, 0, 999))}
    if t == "text_count":
        return {"what": _pick(p.get("what"), ("summary", "words", "chars", "lines"), "summary")}
    if t == "img_crop":
        return {"mode": _pick(p.get("mode"), ("ratio", "manual"), "ratio"), "ratio": _pick(p.get("ratio"), ("1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "21:9"), "1:1"),
                "x": round(n("x", 0, 0, 100), 1), "y": round(n("y", 0, 0, 100), 1), "w": round(n("w", 100, 1, 100), 1), "h": round(n("h", 100, 1, 100), 1),
                "anchor": _pick(p.get("anchor"), ("center", "top", "bottom", "left", "right"), "center")}
    if t == "img_watermark":
        return {"pos": _pick(p.get("pos"), ("br", "bl", "tr", "tl", "center"), "br"), "scale": round(n("scale", 20, 2, 80), 1), "opacity": round(n("opacity", 0.85, 0.05, 1), 2), "margin": int(n("margin", 3, 0, 20))}
    if t == "vid_reframe":
        return {"ratio": _pick(p.get("ratio"), ("9:16", "1:1", "16:9", "4:5", "4:3"), "9:16"), "mode": _pick(p.get("mode"), ("cover", "blur", "pad"), "blur"), "height": int(n("height", 1280, 240, 2160)), "bg": _color(p.get("bg"), "#000000")}
    if t == "vid_loop":
        return {"times": int(n("times", 2, 1, 20)), "duration": round(n("duration", 0, 0, 3600), 1)}
    if t == "vid_audio":
        return {"mode": _pick(p.get("mode"), ("replace", "mix", "mute"), "replace"), "volume": round(n("volume", 1, 0, 2), 2), "fit": _pick(p.get("fit"), ("video", "audio"), "video")}
    if t == "aud_silence_cut":
        return {"threshold": int(n("threshold", -40, -70, -15)), "min_silence": round(n("min_silence", 0.4, 0.1, 5), 2), "keep": round(n("keep", 0.15, 0, 1), 2)}
    if t == "char_sheet":
        return {"name": text(p.get("name"), "", 120), "description": text(p.get("description"), "", 3000), "views": _multi(p.get("views"), SHEET_VIEWS, ("front", "side", "back")),
                "extras": _multi(p.get("extras"), SHEET_EXTRAS, ("expressions", "palette")), "pose": _pick(p.get("pose"), tuple(SHEET_POSES), "neutral"), "layout": _pick(p.get("layout"), ("row", "grid", "turnaround"), "row"),
                "background": _pick(p.get("background"), tuple(SHEET_BG), "white"), "labels": p.get("labels", True) is not False, "language": _pick(p.get("language"), ("en", "pt"), "en")}
    if t == "comic_page":
        return {"format": _pick(p.get("format"), tuple(COMIC_FORMATS), "page"), "panels": int(n("panels", 6, 1, 12)), "scenes": text(p.get("scenes"), "", 4000), "layout": _pick(p.get("layout"), ("grid", "dynamic", "stacked"), "grid"),
                "style": _pick(p.get("style"), tuple(COMIC_STYLES), "comic"), "color": _pick(p.get("color"), ("color", "bw", "halftone"), "color"), "balloons": _pick(p.get("balloons"), ("text", "empty", "none"), "text"),
                "direction": _pick(p.get("direction"), ("ltr", "rtl"), "ltr"), "title": text(p.get("title"), "", 160), "language": _pick(p.get("language"), ("en", "pt"), "en")}
    if t == "in_pattern":
        return {"kind": _pick(p.get("kind"), ("checker", "stripes", "noise", "grid", "dots"), "checker"), "color": _color(p.get("color"), "#202530"), "color2": _color(p.get("color2"), "#f2f2f2"),
                "size": int(n("size", 64, 4, 512)), "width": int(n("width", 1024, 64, 4096)), "height": int(n("height", 1024, 64, 4096))}
    if t == "out_thumbnail":
        return {"layout": _pick(p.get("layout"), ("bottom", "center", "left"), "bottom"), "size": int(n("size", 9, 3, 25)), "color": _color(p.get("color"), "#ffffff"), "shade": round(n("shade", 0.55, 0, 0.9), 2),
                "width": int(n("width", 1280, 320, 3840)), "height": int(n("height", 720, 180, 2160)), "format": _pick(p.get("format"), ("jpg", "png"), "jpg")}
    if t == "img_resize":
        return {"width": int(n("width", 1024, 0, 8000)), "height": int(n("height", 1024, 0, 8000)), "mode": _pick(p.get("mode"), ("fit", "cover", "stretch", "pad"), "fit"),
                "rotate": int(n("rotate", 0, 0, 270)) // 90 * 90, "flip": _pick(p.get("flip"), ("none", "h", "v", "both"), "none"), "bg": _color(p.get("bg"), "#000000"), "format": _pick(p.get("format"), ("png", "jpg"), "png")}
    if t == "img_filter":
        return {"preset": _pick(p.get("preset"), PRESETS_IMG, "none"), "brightness": round(n("brightness", 0, -1, 1), 2), "contrast": round(n("contrast", 1, 0, 3), 2), "saturation": round(n("saturation", 1, 0, 3), 2)}
    if t == "img_text":
        return {"text": text(p.get("text"), "", 600), "pos": _pick(p.get("pos"), ("top", "center", "bottom"), "bottom"), "size": int(n("size", 5, 1, 30)), "color": _color(p.get("color"), "#ffffff"),
                "box": p.get("box", True) is not False}
    if t == "img_collage":
        return {"cols": int(n("cols", 2, 1, 6)), "cell": int(n("cell", 512, 128, 1024)), "gap": int(n("gap", 8, 0, 80)), "bg": _color(p.get("bg"), "#000000")}
    if t == "img_frame":
        return {"at": _pick(p.get("at"), ("first", "middle", "last", "seconds"), "middle"), "seconds": round(n("seconds", 1, 0, 36000), 2), "count": int(n("count", 1, 1, 4))}
    if t == "vid_trim":
        return {"start": round(n("start", 0, 0, 36000), 2), "duration": round(n("duration", 5, 0, 36000), 2)}
    if t == "vid_join":
        return {"width": int(n("width", 1280, 160, 3840)), "height": int(n("height", 720, 160, 2160)), "fps": int(n("fps", 30, 10, 60)), "image_seconds": round(n("image_seconds", 3, 0.5, 60), 1),
                "fade": round(n("fade", 0.3, 0, 2), 2), "bg": _color(p.get("bg"), "#000000")}
    if t == "vid_speed":
        return {"factor": round(n("factor", 2, 0.25, 4), 2), "reverse": bool(p.get("reverse"))}
    if t == "vid_look":
        return {"preset": _pick(p.get("preset"), PRESETS_IMG, "cinematic"), "fade_in": round(n("fade_in", 0.5, 0, 10), 1), "fade_out": round(n("fade_out", 0.5, 0, 10), 1)}
    if t == "vid_slideshow":
        return {"seconds": round(n("seconds", 3, 0.5, 30), 1), "width": int(n("width", 1280, 160, 3840)), "height": int(n("height", 720, 160, 2160)), "fps": int(n("fps", 30, 10, 60)),
                "zoom": p.get("zoom", True) is not False, "fade": round(n("fade", 0.4, 0, 2), 2), "music_volume": round(n("music_volume", 0.8, 0, 2), 2)}
    if t == "aud_trim":
        return {"start": round(n("start", 0, 0, 36000), 2), "duration": round(n("duration", 0, 0, 36000), 2), "fade_in": round(n("fade_in", 0, 0, 30), 1), "fade_out": round(n("fade_out", 0, 0, 30), 1)}
    if t == "aud_mix":
        return {"mode": _pick(p.get("mode"), ("mix", "sequence"), "mix"), "volume": round(n("volume", 1, 0, 2), 2)}
    if t == "aud_fx":
        return {"fx": _pick(p.get("fx"), AUD_FX, "normalize"), "amount": round(n("amount", 1, 0.1, 4), 2)}
    if t == "aud_from_video":
        return {"format": _pick(p.get("format"), ("mp3", "wav", "m4a"), "mp3")}
    if t == "aud_loop":
        return {"duration": round(n("duration", 30, 1, 3600), 1), "fade_out": round(n("fade_out", 1, 0, 30), 1)}
    if t == "in_color":
        return {"color": _color(p.get("color"), "#101820"), "color2": _color(p.get("color2"), "#4f8cff"), "gradient": _pick(p.get("gradient"), ("none", "vertical", "horizontal", "diagonal"), "none"),
                "width": int(n("width", 1024, 16, 4096)), "height": int(n("height", 1024, 16, 4096))}
    if t == "in_silence":
        return {"seconds": round(n("seconds", 3, 0.1, 600), 1)}
    if t == "in_url":
        return {"url": text(p.get("url"), "", 600)}
    if t == "in_random":
        return {"lines": text(p.get("lines"), "uma floresta ao amanhecer\num castelo flutuando\numa cidade neon na chuva", 6000), "count": int(n("count", 1, 1, 10)), "seed": int(n("seed", 0, 0, 2 ** 31)),
                "joiner": _pick(p.get("joiner"), ("line", "comma", "space"), "line")}
    if t == "in_vars":
        return {"template": text(p.get("template"), "{data} {hora} · {projeto}", 1000)}
    if t == "out_export":
        return {"quality": _pick(p.get("quality"), ("480p", "720p", "1080p"), "720p"), "burn": p.get("burn", True) is not False, "music_volume": round(n("music_volume", 0.6, 0, 2), 2),
                "image_seconds": round(n("image_seconds", 5, 1, 60), 1), "fps": int(n("fps", 30, 10, 60))}
    if t == "out_gif":
        return {"width": int(n("width", 480, 120, 1280)), "fps": int(n("fps", 12, 4, 30)), "max_seconds": round(n("max_seconds", 8, 1, 20), 1)}
    if t == "out_audio":
        return {"format": _pick(p.get("format"), ("mp3", "wav", "m4a"), "mp3"), "mode": _pick(p.get("mode"), ("mix", "sequence"), "sequence"), "normalize": p.get("normalize", True) is not False}
    if t == "out_image":
        return {"format": _pick(p.get("format"), ("png", "jpg", "webp"), "png"), "quality": int(n("quality", 90, 10, 100)), "max_width": int(n("max_width", 0, 0, 8000))}
    if t == "out_gallery":
        return {}
    return {}


# --------------------------------------------------------------------------- utilidades dos executores
def _need_ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        raise ValueError("Este nó precisa do ffmpeg instalado (https://ffmpeg.org). Rode «flow doctor» para conferir.")
    return ff


def _ff(eng: Any, args: List[str]) -> None:
    code, err = _run([_need_ffmpeg(), "-y", "-loglevel", "error", *args], eng.ctl)
    if code != 0:
        raise ProviderError("O ffmpeg não conseguiu processar: " + (err.strip().splitlines()[-1] if err.strip() else f"código {code}"))


def _inputs(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any], port: str, kinds: Tuple[str, ...]) -> List[Dict[str, Any]]:
    return [a for a in eng.inputs(canvas, node, port)["assets"] if a["kind"] in kinds]


def _plabel(node: Dict[str, Any], port: str) -> str:
    """Nome da porta como aparece no nó (a mensagem de erro cita o que o usuário vê, não o id interno)."""
    return next((i[1] for i in SPECS.get(node["type"], {}).get("ins", []) if i[0] == port), port)


def _first(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any], port: str, kinds: Tuple[str, ...], what: str) -> Dict[str, Any]:
    items = _inputs(eng, canvas, node, port, kinds)
    if not items:
        raise ValueError(f"Ligue {what} na entrada «{_plabel(node, port)}» deste nó.")
    return items[0]


def _path(eng: Any, a: Dict[str, Any]) -> Path:
    p = eng.cs.asset_path(eng.cid, a["file"])
    if not p:
        raise ValueError("Um arquivo de entrada não existe mais.")
    return p


def _upright(src: Path, tmp: Path, name: str) -> Path:
    """Foto de celular com orientação EXIF (deitada no arquivo, em pé na tela): vira um PNG já girado. O ffmpeg novo gira sozinho e o antigo não — assim o resultado é o mesmo em qualquer um (v0.51)."""
    try:
        from PIL import Image, ImageOps  # type: ignore

        with Image.open(src) as im:
            if im.getexif().get(0x0112, 1) in (0, 1):
                return src
            dst = tmp / f"{name}_up.png"
            (ImageOps.exif_transpose(im) or im).save(dst, "PNG")
            return dst
    except Exception:  # noqa: BLE001 — sem a Pillow ou arquivo estranho: usa o original
        return src


def _image_file(eng: Any, a: Dict[str, Any], tmp: Path, name: str = "frame") -> Path:
    """Arquivo de imagem de um item: a própria imagem, ou o quadro do meio se for um vídeo (assim vídeo também liga em portas de imagem)."""
    src = _path(eng, a)
    if a["kind"] == "image":
        return _upright(src, tmp, name)
    dst = tmp / f"{name}.png"
    _ff(eng, ["-ss", f"{max(0.0, (a.get('duration') or 2.0) / 2):.2f}", "-i", str(src), "-frames:v", "1", str(dst)])
    return dst


def _dims(path: Path) -> Optional[Tuple[int, int]]:
    """Largura e altura (px) de uma imagem: pelo cabeçalho; se o formato não for reconhecido (BMP, TIFF…), pelo ffprobe."""
    try:
        from .. import attachments

        d = attachments.image_size(path.read_bytes())
        if d and d[0] > 0 and d[1] > 0:
            return int(d[0]), int(d[1])
    except OSError:
        return None
    probe = shutil.which("ffprobe")
    if probe:
        code, out = _run_out([probe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)])
        m = re.match(r"^(\d+)x(\d+)", out.strip())
        if code == 0 and m and int(m.group(1)) > 0 and int(m.group(2)) > 0:
            return int(m.group(1)), int(m.group(2))
    return None


def _run_out(cmd: List[str]) -> Tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _save_file(eng: Any, node: Dict[str, Any], path: Path, kind: str, name: str, mime: str, **meta: Any) -> str:
    a = eng.cs.add_asset(eng.cid, path.read_bytes(), path.suffix.lstrip("."), kind, name=name, mime=mime, node=node["id"], provider="canvas", **meta)
    if not a:
        raise ProviderError("Não foi possível salvar o arquivo gerado.")
    return a["id"]


def _texts(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any], port: str) -> List[str]:
    out = []
    for src in eng._edges_to(canvas, node["id"], port):
        sn = eng._node(canvas, src)
        if sn and sn["type"] not in ("style_prompt", "style_folder"):
            t = eng.output(canvas, sn)["text"].strip()
            if t:
                out.append(t)
    return out


def _title(node: Dict[str, Any], fallback: str) -> str:
    return node.get("title") or fallback


def _vf_for(preset: str, extra: Optional[List[str]] = None) -> str:
    fx = FILTER_FX.get(preset, "")
    return ",".join([f for f in ([fx] if fx else []) + (extra or []) if f])


# --------------------------------------------------------------------------- Texto
def run_text_template(eng, canvas, node):
    vars_ = _texts(eng, canvas, node, "vars")
    tpl = node["params"]["template"]

    def sub(m: "re.Match[str]") -> str:
        k = m.group(1).lower()
        if k.isdigit():
            i = int(k) - 1
            return vars_[i] if 0 <= i < len(vars_) else ""
        if k in ("todos", "tudo", "all"):
            return "\n\n".join(vars_)
        if k in ("entrada", "texto", "input"):
            return vars_[0] if vars_ else ""
        return m.group(0)
    out = re.sub(r"\{(\w+)\}", sub, tpl).strip()
    if not out:
        raise ValueError("O modelo ficou vazio: escreva o texto e use {1}, {2}… para as entradas ligadas.")
    return {"assets": [], "text": out}


def run_text_join(eng, canvas, node):
    p = node["params"]
    items = _texts(eng, canvas, node, "texts")
    if not items:
        raise ValueError("Ligue ao menos um texto na entrada «Textos».")
    if p["numbering"]:
        items = [f"{i + 1}. {t}" for i, t in enumerate(items)]
    sep = p["custom"] if p["sep"] == "custom" else SEPARATORS[p["sep"]]
    return {"assets": [], "text": p["prefix"] + sep.join(items) + p["suffix"]}


def _join_in(eng, canvas, node, port) -> str:
    t = "\n\n".join(_texts(eng, canvas, node, port))
    if not t:
        raise ValueError(f"Ligue um texto na entrada «{_plabel(node, port)}».")
    return t


def run_text_edit(eng, canvas, node):
    p, t = node["params"], _join_in(eng, canvas, node, "text")
    lines = t.splitlines()
    op = p["op"]
    if op == "upper":
        t = t.upper()
    elif op == "lower":
        t = t.lower()
    elif op == "title":
        t = t.title()
    elif op == "trim":
        t = "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in lines).strip()
    elif op == "dedupe":
        seen, out = set(), []
        for ln in lines:
            if ln.strip().lower() not in seen:
                seen.add(ln.strip().lower())
                out.append(ln)
        t = "\n".join(out)
    elif op == "sort":
        t = "\n".join(sorted(lines, key=str.lower))
    elif op == "reverse":
        t = "\n".join(reversed(lines))
    elif op == "number":
        t = "\n".join(f"{i + 1}. {ln}" for i, ln in enumerate([x for x in lines if x.strip()]))
    elif op == "no_empty":
        t = "\n".join(ln for ln in lines if ln.strip())
    elif op == "replace":
        if not p["find"]:
            raise ValueError("Escreva o texto a procurar no campo «Procurar».")
        t = t.replace(p["find"], p["replace"])
    return {"assets": [], "text": t}


def _split(t: str, mode: str) -> List[str]:
    if mode == "lines":
        return [x.strip() for x in t.splitlines() if x.strip()]
    if mode == "paragraphs":
        return [x.strip() for x in re.split(r"\n\s*\n", t) if x.strip()]
    if mode == "words":
        return t.split()
    return [x.strip() for x in re.split(r"(?<=[.!?…])\s+", t.replace("\n", " ")) if x.strip()]


def run_text_pick(eng, canvas, node):
    p, t = node["params"], _join_in(eng, canvas, node, "text")
    parts = _split(t, p["mode"])
    if not parts:
        raise ValueError("Não encontrei trechos nesse texto.")
    if p["random"]:
        rnd = random.Random(p["seed"] or None)
        chosen = rnd.sample(parts, min(p["count"], len(parts)))
    elif p["index"] == 0:
        chosen = parts
    else:
        i = min(max(p["index"], 1), len(parts)) - 1
        chosen = parts[i:i + p["count"]]
    sep = " " if p["mode"] in ("words", "sentences") else "\n"
    return {"assets": [], "text": sep.join(chosen)}


REFINE_PROMPTS = {
    "improve": "Reescreva o texto como um prompt de geração de mídia melhor: concreto, visual, com sujeito, ambiente, luz, estilo e composição. Mantenha a ideia. Uma só versão.",
    "translate": "Traduza o texto para {language}, mantendo o sentido e o tom.",
    "summarize": "Resuma o texto em no máximo 3 frases curtas.",
    "expand": "Expanda o texto com mais detalhes e descrições, sem mudar a ideia.",
    "fix": "Corrija ortografia, pontuação e gramática, sem mudar o sentido nem o estilo.",
    "scenes": "Divida a ideia em 4 a 8 cenas curtas, uma por linha, no formato «Cena N: descrição visual».",
    "captions": "Transforme o texto em legendas curtas (até 12 palavras), uma por linha.",
}


def _demo_refine(mode: str, src: str, language: str) -> str:
    if mode == "summarize":
        return " ".join(_split(src, "sentences")[:2])
    if mode == "fix":
        return re.sub(r"\s+([,.;!?])", r"\1", re.sub(r"[ \t]+", " ", src)).strip()
    if mode == "scenes":
        parts = _split(src, "sentences") or [src]
        return "\n".join(f"Cena {i + 1}: {s}" for i, s in enumerate(parts[:8]))
    if mode == "captions":
        return "\n".join(" ".join(s.split()[:12]) for s in _split(src, "sentences"))
    if mode == "improve":
        return src.rstrip(". ") + ", cinematic lighting, highly detailed, sharp focus, balanced composition"
    if mode == "expand":
        return src.rstrip(". ") + ". Detalhes: luz suave, texturas ricas, profundidade de campo e atmosfera marcante."
    return src  # translate: sem IA configurada não há tradução


def run_text_refine(eng, canvas, node):
    p, src = node["params"], _join_in(eng, canvas, node, "text")
    instruction = REFINE_PROMPTS[p["mode"]].format(language=p["language"]) + ((" " + p["instruction"]) if p["instruction"].strip() else "")
    style = eng.styles_for(canvas, node)
    pid = p["provider"] or eng.settings["active"].get("generation", "demo")
    warnings: List[str] = []
    if pid == "demo":
        warnings.append("Sem IA de texto configurada: usei uma versão simples (em Configuração → Provedores você liga um modelo).")
        return {"assets": [], "text": _demo_refine(p["mode"], src, p["language"]), "warnings": warnings}
    provider = build_provider(eng.settings, pid, eng.store.models_dir)
    system = ("Você é um editor de texto dentro de um fluxo de produção de mídia. Cumpra a instrução usando o texto de entrada. Responda APENAS com o texto final, sem explicações nem aspas."
              + (f"\n\nEstilo do projeto: {style.render(src + ' ' + instruction)}" if style.text else ""))
    eng._check()
    out = eng.text_chat(provider, [{"role": "user", "content": f"{instruction}\n\nTexto de entrada:\n{src}"}], system, 0.5, 1500)
    return {"assets": [], "text": out, "warnings": warnings}


# --------------------------------------------------------------------------- Imagem: fichas de personagem e quadrinhos (v0.36)
def _style_text(eng, canvas, node, seed: str) -> str:
    st = eng.styles_for(canvas, node, need_digest=False)
    return st.render(seed) if st.text else ""


def run_char_sheet(eng, canvas, node):
    p = node["params"]
    pt = p["language"] == "pt"
    k = 1 if pt else 0
    src = "\n".join(_texts(eng, canvas, node, "text"))
    desc = "\n".join(x for x in (p["description"].strip(), src) if x)
    if not (p["name"] or desc):
        raise ValueError("Escreva o nome ou a descrição do personagem (ou ligue um texto).")
    views = p["views"] or ["front"]
    shown = [SHEET_LABELS[v][k] for v in views] + [SHEET_LABELS[e][k] for e in p["extras"]]
    who = p["name"] or ("o personagem" if pt else "the character")
    head = (f"Ficha de personagem (character sheet) de {who}, " if pt else f"Character design sheet of {who}, ")
    head += "uma única folha organizada, mostrando: " if pt else "a single organized sheet showing: "
    layout = {"row": ("as vistas lado a lado em uma fileira", "the views side by side in one row"), "grid": ("tudo em uma grade organizada", "everything in a tidy grid"),
              "turnaround": ("as vistas como uma volta completa (turnaround) na mesma altura e escala", "the views as a turnaround lined up at the same height and scale")}[p["layout"]][1 - k]
    parts = [head + "; ".join(shown) + ".", ("Disposição: " if pt else "Layout: ") + layout + "."]
    if desc:
        parts.append(("Personagem: " if pt else "Character: ") + desc)
    parts.append((("Pose: " if pt else "Pose: ") + SHEET_POSES[p["pose"]][k]) + "; " + SHEET_BG[p["background"]][k] + ".")
    parts.append(("As mesmas feições, proporções, roupas e cores em todas as vistas (consistência do personagem). " if pt else "Identical face, proportions, outfit and colors in every view (character consistency). ")
                 + (("Com rótulos curtos e limpos em cada vista, estilo folha de produção." if pt else "Short clean labels under each view, production-sheet look.") if p["labels"] else ("Sem texto nem rótulos." if pt else "No text or labels.")))
    st = _style_text(eng, canvas, node, desc)
    if st:
        parts.append(("Estilo: " if pt else "Style: ") + st)
    return {"assets": [], "text": "\n".join(parts), "warnings": []}


def run_comic_page(eng, canvas, node):
    p = node["params"]
    pt = p["language"] == "pt"
    k = 1 if pt else 0
    story = "\n".join(_texts(eng, canvas, node, "story"))
    raw = [ln.strip() for ln in "\n".join(x for x in (p["scenes"], story) if x.strip()).splitlines() if ln.strip()]
    if not raw:
        raise ValueError("Escreva as cenas (uma por linha) ou ligue um roteiro.")
    fmt = COMIC_FORMATS[p["format"]]
    count = 1 if p["format"] == "splash" else (4 if p["format"] == "koma" else (len(raw) if len(raw) > 1 else p["panels"]))
    count = max(1, min(12, count))
    scenes = raw[:count]
    chars = "\n".join(_texts(eng, canvas, node, "characters"))
    warnings: List[str] = []
    if len(raw) > count:
        warnings.append(f"O formato comporta {count} quadros: usei só as {count} primeiras cenas de {len(raw)}.")
    parts = [(f"Desenho de {fmt[1]}" if pt else f"Illustration of {fmt[0]}") + (f", {count} quadros" if pt else f", {count} panel{'s' if count > 1 else ''}") + f" ({fmt[2]})."]
    if p["title"]:
        parts.append(("Título: " if pt else "Title: ") + f"«{p['title']}»")
    lay = {"grid": ("quadros retangulares alinhados em uma grade com calhas brancas", "rectangular panels in an aligned grid with white gutters"),
           "dynamic": ("quadros de tamanhos e ângulos variados, alguns diagonais", "panels of varied sizes and angles, some diagonal"), "stacked": ("quadros empilhados um abaixo do outro, todos da largura da folha", "panels stacked one under another, each full width")}[p["layout"]][1 - k]
    if count > 1:
        parts.append(("Disposição: " if pt else "Layout: ") + lay + ". " + (("Leitura da direita para a esquerda (mangá)." if pt else "Read right to left (manga order).") if p["direction"] == "rtl" else ("Leitura da esquerda para a direita." if pt else "Read left to right.")))
    parts.append(("Arte: " if pt else "Art: ") + COMIC_STYLES[p["style"]][k] + ", " + {"color": ("cores cheias", "full color"), "bw": ("preto e branco", "black and white"), "halftone": ("cores com retícula (halftone)", "colors with halftone dots")}[p["color"]][1 - k] + ".")
    if chars:
        parts.append(("Personagens (manter o mesmo visual em todos os quadros): " if pt else "Characters (keep the same look in every panel): ") + chars)
    for i, ln in enumerate(scenes, 1):
        scene, _, line = ln.partition("|")
        scene, line = scene.strip(), line.strip().strip('"“”')
        row = ("Quadro " if pt else "Panel ") + f"{i}: {scene}"
        if line and p["balloons"] == "text":
            row += (f'. Balão de fala com o texto exato: "{line}"' if pt else f'. Speech balloon with the exact text: "{line}"')
        parts.append(row)
    if p["balloons"] == "empty":
        parts.append("Balões de fala vazios (sem texto)." if pt else "Empty speech balloons (no text).")
    elif p["balloons"] == "none":
        parts.append("Sem balões nem texto." if pt else "No speech balloons and no text.")
    st = _style_text(eng, canvas, node, chars + " " + " ".join(scenes))
    if st:
        parts.append(("Estilo: " if pt else "Style: ") + st)
    return {"assets": [], "text": "\n".join(parts), "warnings": warnings}


# --------------------------------------------------------------------------- Imagem
def _img_out(eng, node, tmp: Path, out: Path, name: str) -> Dict[str, Any]:
    mime = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp", "gif": "image/gif"}[out.suffix.lstrip(".")]
    return {"assets": [_save_file(eng, node, out, "image", name, mime)], "text": ""}


def run_img_resize(eng, canvas, node):
    p = node["params"]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = _image_file(eng, _first(eng, canvas, node, "image", ("image", "video"), "uma imagem"), tmp)
        vf: List[str] = []
        w, h = p["width"], p["height"]
        size = _dims(src)
        if (w or h) and size:
            sw, sh = size
            # 0 = automático: a outra medida acompanha a proporção, nunca abaixo de 1 px (antes, uma imagem muito estreita dava 0 px e o ffmpeg falhava)
            if w and not h:
                h = max(1, round(sh * w / sw))
            elif h and not w:
                w = max(1, round(sw * h / sh))
            if p["mode"] == "stretch":
                vf.append(f"scale={w}:{h}")
            elif p["mode"] == "cover":
                k = max(w / sw, h / sh)
                vf += [f"scale={max(w, round(sw * k))}:{max(h, round(sh * k))}", f"crop={w}:{h}"]
            elif p["mode"] == "pad":
                k = min(w / sw, h / sh)
                vf += [f"scale={max(1, round(sw * k))}:{max(1, round(sh * k))}", f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={p['bg']}"]
            else:
                k = min(w / sw, h / sh)
                vf.append(f"scale={max(1, round(sw * k))}:{max(1, round(sh * k))}")
        elif w or h:   # sem como medir a origem: o ffmpeg decide
            vf.append(f"scale={w or -1}:{h or -1}")
        vf += {0: [], 90: ["transpose=1"], 180: ["hflip", "vflip"], 270: ["transpose=2"]}[p["rotate"]]
        vf += {"none": [], "h": ["hflip"], "v": ["vflip"], "both": ["hflip", "vflip"]}[p["flip"]]
        out = tmp / f"o.{p['format']}"
        _ff(eng, ["-i", str(src), *(["-vf", ",".join(vf)] if vf else []), "-frames:v", "1", *(["-q:v", "2"] if p["format"] == "jpg" else []), str(out)])
        return _img_out(eng, node, tmp, out, _title(node, "Imagem"))


def run_img_filter(eng, canvas, node):
    p = node["params"]
    extra = []
    if (p["brightness"], p["contrast"], p["saturation"]) != (0, 1, 1):
        extra.append(f"eq=brightness={p['brightness']}:contrast={p['contrast']}:saturation={p['saturation']}")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = _image_file(eng, _first(eng, canvas, node, "image", ("image", "video"), "uma imagem"), tmp)
        size = _dims(src)
        preset, warns = p["preset"], []
        if preset in ("blur", "sharpen", "vhs") and size and size[0] * size[1] < 4:   # o ffmpeg quebra (corrompe a memória) ao desfocar uma imagem de 1 pixel
            warns.append("A imagem é pequena demais para este efeito: ele foi pulado.")
            preset = "none"
        vf = _vf_for(preset, extra)
        out = tmp / "o.png"
        _ff(eng, ["-i", str(src), *(["-vf", vf] if vf else []), "-frames:v", "1", str(out)])
        res = _img_out(eng, node, tmp, out, _title(node, "Imagem filtrada"))
        if warns:
            res["warnings"] = warns
        return res


def _drawtext(tmp: Path, content: str, size_expr: str, color: str, pos: str, box: bool, wrap: int = 28) -> str:
    font = find_font()
    tf = tmp / "t.txt"
    tf.write_text("\n".join(textwrap.fill(line, wrap) for line in content.splitlines() or [content]), encoding="utf-8")
    y = {"top": "h*0.06", "center": "(h-text_h)/2", "bottom": "h-text_h-h*0.06"}[pos]
    opts = [f"textfile='{_esc_path(str(tf))}'", f"fontsize={size_expr}", f"fontcolor={color}", "x=(w-text_w)/2", f"y={y}", "line_spacing=6"]
    if font:
        opts.insert(1, f"fontfile='{_esc_path(font)}'")
    if box:
        opts += ["box=1", "boxcolor=black@0.55", "boxborderw=16"]
    return "drawtext=" + ":".join(opts)


def run_img_text(eng, canvas, node):
    p = node["params"]
    content = "\n".join(x for x in (_join_text(eng, canvas, node, "text"), p["text"].strip()) if x)
    if not content:
        raise ValueError("Escreva o texto no nó ou ligue um nó de texto na entrada «Texto».")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = _image_file(eng, _first(eng, canvas, node, "image", ("image", "video"), "uma imagem"), tmp)
        out = tmp / "o.png"
        try:
            _ff(eng, ["-i", str(src), "-vf", _drawtext(tmp, content, f"h*{p['size'] / 100}", p["color"], p["pos"], p["box"]), "-frames:v", "1", str(out)])
        except ProviderError:
            raise ProviderError("Este ffmpeg não conseguiu desenhar texto (falta o filtro drawtext ou uma fonte instalada).") from None
        return _img_out(eng, node, tmp, out, _title(node, "Imagem com texto"))


def _join_text(eng, canvas, node, port) -> str:
    return "\n\n".join(_texts(eng, canvas, node, port))


def run_img_collage(eng, canvas, node):
    p = node["params"]
    items = _inputs(eng, canvas, node, "images", ("image", "video"))
    if len(items) < 2:
        raise ValueError("Ligue ao menos duas imagens na entrada «Imagens».")
    items = items[:24]
    cols = min(p["cols"], len(items))
    rows = -(-len(items) // cols)
    cell, gap = p["cell"], p["gap"]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        args: List[str] = []
        flt = []
        for i, a in enumerate(items):
            args += ["-i", str(_image_file(eng, a, tmp, f"f{i}"))]
            flt.append(f"[{i}:v]scale={cell}:{cell}:force_original_aspect_ratio=decrease,pad={cell}:{cell}:(ow-iw)/2:(oh-ih)/2:color={p['bg']},setsar=1[c{i}]")
        layout = "|".join(f"{(i % cols) * (cell + gap)}_{(i // cols) * (cell + gap)}" for i in range(len(items)))
        W, H = cols * cell + (cols - 1) * gap, rows * cell + (rows - 1) * gap
        flt.append("".join(f"[c{i}]" for i in range(len(items))) + f"xstack=inputs={len(items)}:layout={layout}:fill={p['bg']}[o]")
        out = tmp / "o.png"
        _ff(eng, [*args, "-filter_complex", ";".join(flt), "-map", "[o]", "-frames:v", "1", str(out)])
        res = _img_out(eng, node, tmp, out, _title(node, "Colagem"))
        res["warnings"] = [f"Colagem {W}×{H}px."]
        return res


def run_img_frame(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "video", ("video",), "um vídeo")
    dur = a.get("duration") or 0
    if p["count"] > 1:
        times = [dur * (i + 0.5) / p["count"] for i in range(p["count"])]
    elif p["at"] == "first":
        times = [0.0]
    elif p["at"] == "last":
        times = [max(0.0, dur - 0.1)]
    elif p["at"] == "seconds":
        times = [min(p["seconds"], max(0.0, dur - 0.05))]
    else:
        times = [dur / 2]
    ids = []
    with tempfile.TemporaryDirectory() as td:
        for i, tsec in enumerate(times):
            out = Path(td) / f"q{i}.png"
            _ff(eng, ["-ss", f"{tsec:.2f}", "-i", str(_path(eng, a)), "-frames:v", "1", str(out)])
            ids.append(_save_file(eng, node, out, "image", f"{_title(node, 'Quadro')} {i + 1}", "image/png"))
    return {"assets": ids, "text": ""}


# --------------------------------------------------------------------------- Vídeo
#: o libx264 em yuv420p exige largura e altura pares: um vídeo de 853×481 (enviado ou de um modelo) falhava no corte, na velocidade e no visual — este filtro arredonda para baixo ao par mais próximo
EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def _src_fps(path: Path, default: float = 30.0) -> float:
    """Quadros por segundo do vídeo de origem (entre 5 e 120), para o corte, a velocidade e o visual não reamostrarem para 30 fps (um vídeo de 16 ou 24 fps ganhava quadros repetidos e tremia)."""
    from .. import attachments as att

    fps = float(att.video_info(path).get("fps") or 0)
    return round(fps, 3) if 5 <= fps <= 120 else default


def _mp4_args(fps: float = 30) -> List[str]:
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-r", f"{fps:g}", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]


def _vid_out(eng, node, out: Path, name: str, **meta: Any) -> Dict[str, Any]:
    return {"assets": [_save_file(eng, node, out, "video", name, "video/mp4", **meta)], "text": ""}


def run_vid_trim(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "video", ("video",), "um vídeo")
    if p["start"] >= (a.get("duration") or 1e9):
        raise ValueError("O início do corte passa do fim do vídeo.")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp4"
        src = _path(eng, a)
        _ff(eng, ["-ss", f"{p['start']:.2f}", "-i", str(src), *(["-t", f"{p['duration']:.2f}"] if p["duration"] > 0 else []), "-vf", EVEN, *_mp4_args(_src_fps(src)), str(out)])
        return _vid_out(eng, node, out, _title(node, "Vídeo cortado"))


def _resolver(eng, canvas):
    assets = {a["id"]: a for a in canvas["assets"]}

    def resolve(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        a = assets.get(c.get("asset", ""))
        path = eng.cs.asset_path(eng.cid, a["file"]) if a else None
        if not a or not path:
            return None
        return {"path": path, "kind": a["kind"], "duration": a["duration"] or 3.0, "asset": a}
    return resolve


def _timeline(clips: List[Dict[str, Any]], audio: List[Dict[str, Any]], text_clips: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    tracks = [{"id": "t_v1", "kind": "video", "name": "V1", "muted": False, "hidden": False}, {"id": "t_a1", "kind": "audio", "name": "A1", "muted": False, "hidden": False},
              {"id": "t_a2", "kind": "audio", "name": "A2", "muted": False, "hidden": False}, {"id": "t_t1", "kind": "text", "name": "T1", "muted": False, "hidden": False}]
    from .schema import normalize_timeline
    return normalize_timeline({"tracks": tracks, "clips": clips + audio + (text_clips or [])})


def run_vid_join(eng, canvas, node):
    p = node["params"]
    items = _inputs(eng, canvas, node, "clips", ("video", "image"))
    if len(items) < 2:
        raise ValueError("Ligue ao menos dois clipes (vídeos ou imagens) na entrada «Clipes».")
    clips, cursor = [], 0.0
    for a in items[:60]:
        dur = p["image_seconds"] if a["kind"] == "image" else (a.get("duration") or 3.0)
        clips.append({"asset": a["id"], "track": "t_v1", "start": round(cursor, 3), "dur": round(dur, 3), "fit": "contain", "fade_in": p["fade"], "fade_out": p["fade"], "id": f"c{len(clips)}"})
        cursor += dur
    tl = _timeline(clips, [])
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp4"
        warns = render_timeline(tl, p["width"], p["height"], p["fps"], p["bg"], _resolver(eng, canvas), out, eng.ctl)
        res = _vid_out(eng, node, out, _title(node, "Vídeos juntos"), w=p["width"], h=p["height"])
    res["warnings"] = warns
    return res


def run_vid_speed(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "video", ("video",), "um vídeo")
    src = _path(eng, a)
    fps = _src_fps(src)
    vf = [EVEN, f"setpts=PTS/{p['factor']}"] + (["reverse"] if p["reverse"] else []) + [f"fps={fps:g}"]   # fps depois do setpts: a duração sai exata (sem ele, 3 s a 2× davam 1,67 s em vez de 1,5 s e o som terminava antes da imagem)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp4"
        af = ",".join(([_tempo(p["factor"])] if abs(p["factor"] - 1) > 0.001 else []) + (["areverse"] if p["reverse"] else []))
        has_a = has_audio(src)
        # (vf antes de af: a ordem dos -filter não importa, cada um vale para o seu fluxo)
        args = ["-i", str(src), "-vf", ",".join(vf), *(["-af", af] if af and has_a else []), *([] if has_a else ["-an"]), *_mp4_args(fps)]
        _ff(eng, [*args, str(out)])
        return _vid_out(eng, node, out, _title(node, "Vídeo em outra velocidade"))


def run_vid_look(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "video", ("video",), "um vídeo")
    dur = a.get("duration") or 0
    fx = []
    if p["fade_in"] > 0:
        fx.append(f"fade=t=in:st=0:d={p['fade_in']}")
    if p["fade_out"] > 0 and dur > p["fade_out"]:
        fx.append(f"fade=t=out:st={max(0.0, dur - p['fade_out']):.2f}:d={p['fade_out']}")
    vf = ",".join([EVEN, *([_vf_for(p["preset"], fx)] if _vf_for(p["preset"], fx) else [])])
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp4"
        src = _path(eng, a)
        _ff(eng, ["-i", str(src), "-vf", vf, *_mp4_args(_src_fps(src)), str(out)])
        return _vid_out(eng, node, out, _title(node, "Vídeo com visual novo"))


def run_vid_slideshow(eng, canvas, node):
    p = node["params"]
    imgs = _inputs(eng, canvas, node, "images", ("image", "video"))
    if not imgs:
        raise ValueError("Ligue ao menos uma imagem na entrada «Imagens».")
    audios = _inputs(eng, canvas, node, "audio", ("audio",))
    clips, cursor = [], 0.0
    for i, a in enumerate(imgs[:60]):
        clips.append({"asset": a["id"], "track": "t_v1", "start": round(cursor, 3), "dur": p["seconds"] if a["kind"] == "image" else min(a.get("duration") or p["seconds"], p["seconds"] * 2), "fit": "cover",
                      "fade_in": p["fade"], "fade_out": p["fade"], "scale": (1.08 if i % 2 else 1.0) if p["zoom"] else 1.0, "x": ((-0.04, 0.04)[i % 2] if p["zoom"] else 0), "id": f"c{i}"})
        cursor += clips[-1]["dur"]
    music, at, k = [], 0.0, 0
    while audios and at < cursor - 0.05 and k < 40:
        m = audios[k % len(audios)]
        d = min(m.get("duration") or cursor, cursor - at)
        music.append({"asset": m["id"], "track": "t_a1", "start": round(at, 3), "dur": round(d, 3), "volume": p["music_volume"], "fade_in": 0.5 if k == 0 else 0,
                      "fade_out": 1.5 if at + d >= cursor - 0.06 else 0, "id": f"m{k}"})
        at += d
        k += 1
    tl = _timeline(clips, music)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp4"
        warns = render_timeline(tl, p["width"], p["height"], p["fps"], "#000000", _resolver(eng, canvas), out, eng.ctl)
        res = _vid_out(eng, node, out, _title(node, "Apresentação"), w=p["width"], h=p["height"])
    res["warnings"] = warns
    return res


# --------------------------------------------------------------------------- Som
def _aud_args(fmt: str) -> List[str]:
    return {"mp3": ["-c:a", "libmp3lame", "-b:a", "192k"], "wav": ["-c:a", "pcm_s16le"], "m4a": ["-c:a", "aac", "-b:a", "160k"]}[fmt] + ["-ar", "44100", "-ac", "2"]


def _file_duration(path: Path) -> Optional[float]:
    probe = shutil.which("ffprobe")
    if not probe:
        return None
    code, o = _run_out([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    try:
        return float(o.strip().splitlines()[0]) if code == 0 and o.strip() else 0.0
    except ValueError:
        return 0.0


def _aud_out(eng, node, out: Path, name: str) -> Dict[str, Any]:
    d = _file_duration(out)
    if d is not None and d <= 0.001:   # corte além do fim, efeito que encurta demais…: o ffmpeg "dá certo" e grava um arquivo vazio (v0.52)
        raise ValueError("O resultado ficou sem áudio (o trecho pedido está depois do fim do áudio ou ficou curto demais).")
    mime = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4"}[out.suffix.lstrip(".")]
    return {"assets": [_save_file(eng, node, out, "audio", name, mime)], "text": ""}


def _need_sound(eng, a: Dict[str, Any]) -> Path:
    src = _path(eng, a)
    if a["kind"] == "video" and not has_audio(src):
        raise ValueError(f"O vídeo «{a['name']}» não tem áudio.")
    return src


def run_aud_trim(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "audio", ("audio", "video"), "um áudio")
    if p["start"] > 0 and p["start"] >= (a.get("duration") or 1e9):
        raise ValueError("O início do corte passa do fim do áudio.")
    src = _need_sound(eng, a)
    dur = (a.get("duration") or 0) - p["start"]
    if p["duration"] > 0:
        dur = min(dur, p["duration"]) if dur > 0 else p["duration"]
    af = []
    if p["fade_in"] > 0:
        af.append(f"afade=t=in:st=0:d={p['fade_in']}")
    if p["fade_out"] > 0 and dur > p["fade_out"]:
        af.append(f"afade=t=out:st={max(0.0, dur - p['fade_out']):.2f}:d={p['fade_out']}")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp3"
        _ff(eng, ["-ss", f"{p['start']:.2f}", "-i", str(src), *(["-t", f"{p['duration']:.2f}"] if p["duration"] > 0 else []), "-vn", *(["-af", ",".join(af)] if af else []), *_aud_args("mp3"), str(out)])
        return _aud_out(eng, node, out, _title(node, "Áudio cortado"))


def _mix_files(eng, items: List[Dict[str, Any]], mode: str, volume: float, out: Path, fmt: str, normalize: bool = False) -> None:
    srcs = [_need_sound(eng, a) for a in items[:16]]
    args: List[str] = []
    for s in srcs:
        args += ["-i", str(s)]
    n = len(srcs)
    pre = "".join(f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}];" for i in range(n))
    ins = "".join(f"[a{i}]" for i in range(n))
    core = f"{ins}concat=n={n}:v=0:a=1" if mode == "sequence" else f"{ins}amix=inputs={n}:duration=longest:normalize=0,volume={n}" if n > 1 else f"{ins}anull"
    for norm in ((True, False) if normalize else (False,)):  # loudnorm num trecho em silêncio total gera lixo (o codificador MP3 aborta): refaz sem normalizar
        tail = f",volume={volume}" + (",loudnorm=I=-16:TP=-1.5:LRA=11" if norm else "")
        try:
            _ff(eng, [*args, "-filter_complex", f"{pre}{core}{tail}[o]", "-map", "[o]", *_aud_args(fmt), str(out)])
            return
        except ProviderError:
            if not norm:
                raise


def run_aud_mix(eng, canvas, node):
    p = node["params"]
    items = _inputs(eng, canvas, node, "audios", ("audio", "video"))
    if len(items) < 2:
        raise ValueError("Ligue ao menos dois áudios na entrada «Áudios».")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp3"
        _mix_files(eng, items, p["mode"], p["volume"], out, "mp3")
        return _aud_out(eng, node, out, _title(node, "Mistura"))


def run_aud_fx(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "audio", ("audio", "video"), "um áudio")
    src, fx, amt = _need_sound(eng, a), p["fx"], p["amount"]
    af = {"none": "anull", "louder": f"volume={1 + amt}", "quieter": f"volume={1 / (1 + amt):.3f}", "faster": _tempo(1 + amt), "slower": _tempo(1 / (1 + amt)), "reverse": "areverse",
          "echo": f"aecho=0.8:0.88:{int(40 * amt) + 20}:0.4", "telephone": "highpass=f=400,lowpass=f=3400,volume=1.4", "bass": f"bass=g={min(20, 6 * amt):.1f}",
          "normalize": "loudnorm=I=-16:TP=-1.5:LRA=11"}[fx]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp3"
        try:
            _ff(eng, ["-i", str(src), "-vn", "-af", af, *_aud_args("mp3"), str(out)])
        except ProviderError:
            if fx != "normalize":
                raise
            _ff(eng, ["-i", str(src), "-vn", *_aud_args("mp3"), str(out)])  # silêncio total: não há o que normalizar
        return _aud_out(eng, node, out, _title(node, "Áudio com efeito"))


def run_aud_from_video(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "video", ("video",), "um vídeo")
    src = _need_sound(eng, a)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / f"o.{p['format']}"
        _ff(eng, ["-i", str(src), "-vn", *_aud_args(p["format"]), str(out)])
        return _aud_out(eng, node, out, _title(node, "Áudio do vídeo"))


def run_aud_loop(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "audio", ("audio", "video"), "um áudio")
    src = _need_sound(eng, a)
    af = ["aresample=44100"] + ([f"afade=t=out:st={max(0.0, p['duration'] - p['fade_out']):.2f}:d={p['fade_out']}"] if p["fade_out"] > 0 else [])
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp3"
        _ff(eng, ["-stream_loop", "-1", "-i", str(src), "-vn", "-t", f"{p['duration']:.2f}", "-af", ",".join(af), *_aud_args("mp3"), str(out)])
        return _aud_out(eng, node, out, _title(node, "Áudio repetido"))


# --------------------------------------------------------------------------- Input
def run_in_color(eng, canvas, node):
    p = node["params"]
    w, h = p["width"], p["height"]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.png"
        if p["gradient"] == "none":
            _ff(eng, ["-f", "lavfi", "-i", f"color=c={p['color']}:s={w}x{h}", "-frames:v", "1", str(out)])
        else:
            x1, y1 = {"vertical": (0, h), "horizontal": (w, 0), "diagonal": (w, h)}[p["gradient"]]
            _ff(eng, ["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0={p['color']}:c1={p['color2']}:x0=0:y0=0:x1={x1}:y1={y1}:d=1:n=2", "-frames:v", "1", str(out)])
        return _img_out(eng, node, Path(td), out, _title(node, "Cor"))


def run_in_silence(eng, canvas, node):
    p = node["params"]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp3"
        _ff(eng, ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{p['seconds']:.2f}", *_aud_args("mp3"), str(out)])
        return _aud_out(eng, node, out, _title(node, "Silêncio"))


MAX_URL_BYTES = 60 * 1024 * 1024
EXT_OF = {"image/png": ("png", "image"), "image/jpeg": ("jpg", "image"), "image/webp": ("webp", "image"), "image/gif": ("gif", "image"), "video/mp4": ("mp4", "video"), "video/webm": ("webm", "video"),
          "audio/mpeg": ("mp3", "audio"), "audio/wav": ("wav", "audio"), "audio/ogg": ("ogg", "audio"), "audio/mp4": ("m4a", "audio"), "audio/x-wav": ("wav", "audio")}


def run_in_url(eng, canvas, node):
    from .. import safeurl as ws
    from .media import sniff_mime

    url = node["params"]["url"].strip()
    if not url:
        raise ValueError("Cole o endereço (https://…) de uma imagem, vídeo ou áudio.")
    if not ws.safe_url(url):
        raise ValueError("Só links públicos http(s) são aceitos (nada de localhost ou redes privadas).")
    try:
        with ws.OPENER.open(urllib.request.Request(url, headers=ws.UA), timeout=30) as resp:
            ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            data = resp.read(MAX_URL_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ValueError(f"Não consegui baixar o link: {exc}") from None
    if len(data) > MAX_URL_BYTES:
        raise ValueError("O arquivo do link passa de 60 MB.")
    mime = sniff_mime(data[:4096]) or ctype
    if mime not in EXT_OF:
        raise ValueError("O link não é uma imagem, vídeo ou áudio que o OpenFlow leia (png, jpg, webp, gif, mp4, webm, mp3, wav, ogg, m4a).")
    ext, kind = EXT_OF[mime]
    a = eng.cs.add_asset(eng.cid, data, ext, kind, name=_title(node, url.rsplit("/", 1)[-1][:60] or "Link"), mime=mime, node=node["id"], provider="url")
    if not a:
        raise ProviderError("Não foi possível salvar o arquivo baixado.")
    return {"assets": [a["id"]], "text": ""}


def run_in_random(eng, canvas, node):
    p = node["params"]
    lines = [x.strip() for x in p["lines"].splitlines() if x.strip()]
    if not lines:
        raise ValueError("Escreva ao menos uma linha para sortear.")
    rnd = random.Random(p["seed"] or None)
    chosen = rnd.sample(lines, min(p["count"], len(lines)))
    return {"assets": [], "text": {"line": "\n", "comma": ", ", "space": " "}[p["joiner"]].join(chosen)}


def run_in_vars(eng, canvas, node):
    now = datetime.datetime.now()
    cv = canvas
    vals = {"data": now.strftime("%d/%m/%Y"), "hora": now.strftime("%H:%M"), "ano": str(now.year), "projeto": cv.get("name", ""), "nos": str(len(cv.get("nodes", []))),
            "arquivos": str(len(cv.get("assets", []))), "aleatorio": str(random.randint(1000, 9999))}
    return {"assets": [], "text": re.sub(r"\{(\w+)\}", lambda m: vals.get(m.group(1).lower(), m.group(0)), node["params"]["template"]).strip()}


# --------------------------------------------------------------------------- Output
QUALITY = {"480p": 854, "720p": 1280, "1080p": 1920}


def run_out_export(eng, canvas, node):
    p = node["params"]
    v = _first(eng, canvas, node, "video", ("video", "image"), "um vídeo ou imagem")
    audios = _inputs(eng, canvas, node, "audio", ("audio",))
    caps = _join_text(eng, canvas, node, "captions")
    long_side = QUALITY[p["quality"]]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = _path(eng, v)
        args: List[str] = []
        if v["kind"] == "image":
            src = still_path(src, tmp, eng.ctl)   # GIF → primeiro quadro (o demuxer de GIF não aceita -loop como imagem parada)
            args += ["-loop", "1", "-t", f"{p['image_seconds']:.2f}"]
        args += ["-i", str(src)]
        n_a = 0
        for a in audios[:8]:
            args += ["-stream_loop", "-1", "-i", str(_path(eng, a))]
            n_a += 1
        flt = [f"[0:v]scale='if(gt(iw,ih),{long_side},-2)':'if(gt(iw,ih),-2,{long_side})',scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[v0]"]
        label = "v0"
        warnings: List[str] = []
        if caps and p["burn"]:
            flt.append(f"[{label}]{_drawtext(tmp, caps, 'h*0.045', '#ffffff', 'bottom', True, wrap=40)}[v1]")
            label = "v1"
        has_a0 = v["kind"] == "video" and has_audio(src)
        a_in = (["[0:a]aresample=44100,aformat=channel_layouts=stereo[b0]"] if has_a0 else [])
        names = (["[b0]"] if has_a0 else [])
        for i in range(n_a):
            a_in.append(f"[{i + 1}:a]aresample=44100,aformat=channel_layouts=stereo,volume={p['music_volume'] if has_a0 else 1.0}[m{i}]")
            names.append(f"[m{i}]")
        maps = ["-map", f"[{label}]"]
        if names:
            flt += a_in
            flt.append("".join(names) + (f"amix=inputs={len(names)}:duration=first:normalize=0[ao]" if len(names) > 1 else "anull[ao]") if has_a0 or n_a else "")
            maps += ["-map", "[ao]"]
        else:
            maps += ["-an"]
        total = (v.get("duration") or p["image_seconds"]) if v["kind"] == "video" else p["image_seconds"]
        out = tmp / "o.mp4"
        flt = [f for f in flt if f]
        try:
            _ff(eng, [*args, "-filter_complex", ";".join(flt), *maps, "-t", f"{total:.2f}", *_mp4_args(p["fps"]), str(out)])
        except ProviderError:
            if not (caps and p["burn"]):
                raise
            warnings.append("As legendas foram ignoradas: este ffmpeg não conseguiu desenhar texto (falta o filtro drawtext ou uma fonte).")
            flt2 = [f for f in flt if "drawtext" not in f]
            flt2 = [f.replace("[v1]", "") if f.startswith("[v0]") else f for f in flt2]
            maps2 = [m if m != "[v1]" else "[v0]" for m in maps]
            _ff(eng, [*args, "-filter_complex", ";".join(flt2), *maps2, "-t", f"{total:.2f}", *_mp4_args(p["fps"]), str(out)])
        res = _vid_out(eng, node, out, _title(node, "Vídeo final"))
    res["warnings"] = warnings
    return res


def run_out_gif(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "video", ("video",), "um vídeo")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.gif"
        vf = f"fps={p['fps']},scale={p['width']}:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4"
        _ff(eng, ["-t", f"{p['max_seconds']:.1f}", "-i", str(_path(eng, a)), "-filter_complex", vf, "-loop", "0", str(out)])
        return _img_out(eng, node, Path(td), out, _title(node, "GIF"))


def run_out_audio(eng, canvas, node):
    p = node["params"]
    items = _inputs(eng, canvas, node, "audio", ("audio", "video"))
    if not items:
        raise ValueError("Ligue ao menos um áudio na entrada «Áudio».")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / f"o.{p['format']}"
        _mix_files(eng, items, p["mode"], 1.0, out, p["format"], normalize=p["normalize"])
        return _aud_out(eng, node, out, _title(node, "Áudio final"))


def run_out_image(eng, canvas, node):
    p = node["params"]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = _image_file(eng, _first(eng, canvas, node, "image", ("image", "video"), "uma imagem"), tmp)
        out = tmp / f"o.{p['format']}"
        q = {"jpg": ["-q:v", str(max(2, min(31, round(31 - p['quality'] * 0.29))))], "webp": ["-quality", str(p["quality"])], "png": []}[p["format"]]
        vf = [f"scale='min({p['max_width']},iw)':-2"] if p["max_width"] else []
        _ff(eng, ["-i", str(src), *(["-vf", ",".join(vf)] if vf else []), "-frames:v", "1", *q, str(out)])
        return _img_out(eng, node, tmp, out, _title(node, "Imagem final"))


def run_out_gallery(eng, canvas, node):
    ids, texts = [], []
    for src in eng._edges_to(canvas, node["id"], "items"):
        sn = eng._node(canvas, src)
        if not sn:
            continue
        o = eng.output(canvas, sn)
        ids += [a["id"] for a in o["assets"] if a["id"] not in ids]
        if o["text"].strip():
            texts.append(o["text"].strip())
    if not ids and not texts:
        raise ValueError("Ligue imagens, vídeos, áudios ou textos na entrada «Itens».")
    return {"assets": ids, "text": "\n\n".join(texts)}



# --------------------------------------------------------------------------- v0.34: nós novos
_RX_CODE = (
    "import json,re,sys\n"
    "d=json.load(sys.stdin)\n"
    "out=[]\n"
    "for m in re.finditer(d['pattern'],d['text'],re.I):\n"
    "    v=(m.group(1) if m.groups() else m.group(0)).strip()\n"
    "    if v and v not in out: out.append(v)\n"
    "    if len(out)>=500: break\n"
    "print(json.dumps(out))\n"
)


def _regex_values(pattern: str, text_: str, timeout: float = 4.0) -> List[str]:
    """Os trechos que um padrão (regex) do usuário acha, com tempo limite: roda num Python à parte (`-I`) que é encerrado se passar de `timeout` segundos."""
    import json
    import subprocess
    import sys

    try:
        r = subprocess.run([sys.executable, "-I", "-c", _RX_CODE], input=json.dumps({"pattern": pattern, "text": text_}), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ValueError("Esse padrão demorou demais para rodar (pode travar): simplifique-o.") from None
    if r.returncode != 0:
        raise ValueError("Não consegui rodar esse padrão (regex): " + (r.stderr.strip().splitlines() or ["erro"])[-1][:120])
    return json.loads(r.stdout or "[]")


def run_text_extract(eng, canvas, node):
    p, t = node["params"], _join_in(eng, canvas, node, "text")[:50000]
    pats = {"links": r"https?://[^\s<>\"')\]]+", "emails": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "hashtags": r"#[\wÀ-ÿ]+", "numbers": r"-?\d+(?:[.,]\d+)?",
            "quotes": r"[\"“«]([^\"”»\n]{1,300})[\"”»]", "words_caps": r"\b[A-ZÀ-Ý][A-ZÀ-Ý0-9]{2,}\b"}
    if p["what"] == "regex":
        if not p["pattern"]:
            raise ValueError("Escreva o padrão (expressão regular) no campo «Padrão».")
        if re.search(r"\((?:[^()]*[+*][^()]*)\)[+*{]", p["pattern"]):
            raise ValueError("Esse padrão repete um grupo que já se repete (pode travar): simplifique-o.")
        try:
            re.compile(p["pattern"], re.I)
        except re.error as exc:
            raise ValueError(f"Padrão inválido: {exc}") from None
        found = _regex_values(p["pattern"], t)   # o padrão do usuário roda num processo à parte com limite de tempo: alguns (ex.: «(a|a)*b») levam uma eternidade e o `re` não pode ser interrompido
    else:
        rx = re.compile(pats[p["what"]], re.I if p["what"] != "words_caps" else 0)
        found = []
        for m in rx.finditer(t):
            v = (m.group(1) if m.groups() else m.group(0)).strip()
            if p["what"] in ("links", "emails"):
                v = v.rstrip(".,;:!?)»”'\"")   # a pontuação da frase não faz parte do link
            if v and v not in found:
                found.append(v)
            if len(found) >= 500:
                break
    if p["limit"]:
        found = found[:p["limit"]]
    if not found:
        raise ValueError("Não achei nada no texto com esse critério.")
    return {"assets": [], "text": {"line": "\n", "comma": ", ", "space": " "}[p["joiner"]].join(found)}


def run_text_count(eng, canvas, node):
    p, t = node["params"], _join_in(eng, canvas, node, "text")
    words, chars, lines = len(t.split()), len(t), len([ln for ln in t.splitlines() if ln.strip()])
    out = {"words": str(words), "chars": str(chars), "lines": str(lines), "summary": f"{words} palavras · {chars} caracteres · {lines} linhas"}[p["what"]]
    return {"assets": [], "text": out}


def run_img_crop(eng, canvas, node):
    p = node["params"]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = _image_file(eng, _first(eng, canvas, node, "image", ("image", "video"), "uma imagem"), tmp)
        size = _dims(src)
        warns: List[str] = []
        if size:
            sw, sh = size
            if p["mode"] == "manual":
                cw, ch = max(1, round(sw * p["w"] / 100)), max(1, round(sh * p["h"] / 100))
                cx, cy = round(sw * p["x"] / 100), round(sh * p["y"] / 100)
                if cx + cw > sw or cy + ch > sh:
                    warns.append("O recorte passava da borda da imagem: encostei na borda.")
                cx, cy = max(0, min(cx, sw - min(cw, sw))), max(0, min(cy, sh - min(ch, sh)))
            else:
                a, b = (int(x) for x in p["ratio"].split(":"))
                cw, ch = (round(sh * a / b), sh) if sw / sh >= a / b else (sw, round(sw * b / a))
                cx = {"left": 0, "right": sw - min(cw, sw)}.get(p["anchor"], (sw - min(cw, sw)) // 2)
                cy = {"top": 0, "bottom": sh - min(ch, sh)}.get(p["anchor"], (sh - min(ch, sh)) // 2)
            cw, ch = max(1, min(cw, sw)), max(1, min(ch, sh))
            vf = f"crop={cw}:{ch}:{cx}:{cy}"
        elif p["mode"] == "manual":
            vf = f"crop=iw*{p['w'] / 100:.4f}:ih*{p['h'] / 100:.4f}:iw*{p['x'] / 100:.4f}:ih*{p['y'] / 100:.4f}"
        else:
            a, b = (int(x) for x in p["ratio"].split(":"))
            ox = {"left": "0", "right": "iw-ow"}.get(p["anchor"], "(iw-ow)/2")
            oy = {"top": "0", "bottom": "ih-oh"}.get(p["anchor"], "(ih-oh)/2")
            vf = f"crop='if(gte(iw/ih,{a}/{b}),ih*{a}/{b},iw)':'if(gte(iw/ih,{a}/{b}),ih,iw*{b}/{a})':{ox}:{oy}"
        out = tmp / "o.png"
        _ff(eng, ["-i", str(src), "-vf", vf, "-frames:v", "1", str(out)])
        res = _img_out(eng, node, tmp, out, _title(node, "Imagem recortada"))
        if warns:
            res["warnings"] = warns
        return res


def run_img_watermark(eng, canvas, node):
    p = node["params"]
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        base = _image_file(eng, _first(eng, canvas, node, "image", ("image", "video"), "uma imagem"), tmp, "base")
        logo = _path(eng, _first(eng, canvas, node, "logo", ("image",), "a imagem da marca"))
        m = p["margin"]
        xy = {"br": f"W-w-W*{m}/100:H-h-H*{m}/100", "bl": f"W*{m}/100:H-h-H*{m}/100", "tr": f"W-w-W*{m}/100:H*{m}/100", "tl": f"W*{m}/100:H*{m}/100", "center": "(W-w)/2:(H-h)/2"}[p["pos"]]
        flt = (f"[1:v]format=rgba,colorchannelmixer=aa={p['opacity']}[l0];[l0][0:v]scale2ref=w=oh*mdar:h=ih*{p['scale'] / 100:.4f}[lg][bg];"
               f"[bg][lg]overlay={xy}[o]")
        out = tmp / "o.png"
        # a marca ocupa `scale`% da altura da imagem; scale2ref mantém a proporção dela
        _ff(eng, ["-i", str(base), "-i", str(logo), "-filter_complex", flt, "-map", "[o]", "-frames:v", "1", str(out)])
        return _img_out(eng, node, tmp, out, _title(node, "Imagem com marca"))


def run_vid_reframe(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "video", ("video",), "um vídeo")
    src = _path(eng, a)
    ra, rb = (int(x) for x in p["ratio"].split(":"))
    H = p["height"] // 2 * 2
    W = int(round(H * ra / rb / 2)) * 2
    if p["mode"] == "cover":
        flt = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[v]"
    elif p["mode"] == "pad":
        flt = f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={p['bg']},setsar=1[v]"
    else:   # fundo desfocado com o próprio vídeo (o formato de Reels/Shorts)
        flt = (f"[0:v]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=30[bg];"
               f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    fps = _src_fps(src)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp4"
        has_a = has_audio(src)
        _ff(eng, ["-i", str(src), "-filter_complex", flt, "-map", "[v]", *(["-map", "0:a"] if has_a else ["-an"]), *_mp4_args(fps), str(out)])
        return _vid_out(eng, node, out, _title(node, f"Vídeo {p['ratio']}"), w=W, h=H)


def run_vid_loop(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "video", ("video",), "um vídeo")
    src = _path(eng, a)
    dur = a.get("duration") or 0
    total = p["duration"] if p["duration"] > 0 else dur * p["times"]
    if total <= 0:
        raise ValueError("Não sei a duração do vídeo: informe a «Duração final».")
    if total > 3600:
        raise ValueError("O vídeo final passaria de 1 hora.")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp4"
        _ff(eng, ["-stream_loop", "-1", "-i", str(src), "-t", f"{total:.2f}", "-vf", EVEN, *_mp4_args(_src_fps(src)), str(out)])
        return _vid_out(eng, node, out, _title(node, "Vídeo repetido"))


def run_vid_audio(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "video", ("video",), "um vídeo")
    src = _path(eng, a)
    auds = _inputs(eng, canvas, node, "audio", ("audio",))
    if p["mode"] != "mute" and not auds:
        raise ValueError("Ligue um áudio na entrada «Áudio» (ou escolha «Tirar o som»).")
    dur = a.get("duration") or 0
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp4"
        if p["mode"] == "mute":
            _ff(eng, ["-i", str(src), "-c:v", "copy", "-an", "-movflags", "+faststart", str(out)])
            return _vid_out(eng, node, out, _title(node, "Vídeo sem som"))
        music = Path(td) / "m.m4a"
        _mix_files(eng, auds, "sequence", p["volume"], music, "m4a")
        has_a = has_audio(src)
        if p["mode"] == "mix" and has_a:
            flt = "[0:a]aresample=44100,aformat=channel_layouts=stereo[a0];[1:a]aresample=44100,aformat=channel_layouts=stereo[a1];[a0][a1]amix=inputs=2:duration=" + ("first" if p["fit"] == "video" else "longest") + ":normalize=0[aout]"
        else:
            flt = "[1:a]aresample=44100,aformat=channel_layouts=stereo[aout]"
        end = ["-t", f"{dur:.2f}"] if p["fit"] == "video" and dur else ["-shortest"] if p["fit"] == "audio" else []
        _ff(eng, ["-i", str(src), "-i", str(music), "-filter_complex", flt, "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", *end, "-movflags", "+faststart", str(out)])
        return _vid_out(eng, node, out, _title(node, "Vídeo com outro áudio"))


def run_aud_silence_cut(eng, canvas, node):
    p = node["params"]
    a = _first(eng, canvas, node, "audio", ("audio", "video"), "um áudio")
    src = _need_sound(eng, a)
    keep = p["keep"]
    rule = f"start_periods=1:start_silence={keep}:start_threshold={p['threshold']}dB:stop_periods=-1:stop_silence={max(keep, 0.05)}:stop_threshold={p['threshold']}dB:detection=peak"
    # «min_silence»: só o silêncio mais longo que isso é cortado (o resto da pausa curta fica)
    rule = rule.replace(f"stop_silence={max(keep, 0.05)}", f"stop_silence={p['min_silence']}")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.mp3"
        _ff(eng, ["-i", str(src), "-vn", "-af", f"silenceremove={rule}", *_aud_args("mp3"), str(out)])
        if out.stat().st_size < 400:
            raise ValueError("O áudio ficou vazio: ele inteiro está abaixo do limite de silêncio. Aumente o limite (ex.: −50 dB).")
        return _aud_out(eng, node, out, _title(node, "Áudio sem silêncios"))


def run_in_pattern(eng, canvas, node):
    p = node["params"]
    w, h, s = p["width"], p["height"], p["size"]
    c1, c2 = p["color"], p["color2"]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.png"
        if p["kind"] == "noise":
            _ff(eng, ["-f", "lavfi", "-i", f"color=c={c1}:s={w}x{h}", "-vf", "noise=alls=60:allf=t+u", "-frames:v", "1", str(out)])
        else:
            base = f"color=c={c1}:s={w}x{h}"
            if p["kind"] == "checker":
                vf = f"geq=r='if(mod(floor(X/{s})+floor(Y/{s}),2),{int(c2[1:3], 16)},{int(c1[1:3], 16)})':g='if(mod(floor(X/{s})+floor(Y/{s}),2),{int(c2[3:5], 16)},{int(c1[3:5], 16)})':b='if(mod(floor(X/{s})+floor(Y/{s}),2),{int(c2[5:7], 16)},{int(c1[5:7], 16)})'"
            elif p["kind"] == "stripes":
                vf = f"geq=r='if(mod(floor((X+Y)/{s}),2),{int(c2[1:3], 16)},{int(c1[1:3], 16)})':g='if(mod(floor((X+Y)/{s}),2),{int(c2[3:5], 16)},{int(c1[3:5], 16)})':b='if(mod(floor((X+Y)/{s}),2),{int(c2[5:7], 16)},{int(c1[5:7], 16)})'"
            elif p["kind"] == "grid":
                vf = f"geq=r='if(lt(mod(X,{s}),2)+lt(mod(Y,{s}),2),{int(c2[1:3], 16)},{int(c1[1:3], 16)})':g='if(lt(mod(X,{s}),2)+lt(mod(Y,{s}),2),{int(c2[3:5], 16)},{int(c1[3:5], 16)})':b='if(lt(mod(X,{s}),2)+lt(mod(Y,{s}),2),{int(c2[5:7], 16)},{int(c1[5:7], 16)})'"
            else:   # dots
                vf = (f"geq=r='if(lt(hypot(mod(X,{s})-{s}/2,mod(Y,{s})-{s}/2),{s}/4),{int(c2[1:3], 16)},{int(c1[1:3], 16)})':g='if(lt(hypot(mod(X,{s})-{s}/2,mod(Y,{s})-{s}/2),{s}/4),{int(c2[3:5], 16)},{int(c1[3:5], 16)})':"
                      f"b='if(lt(hypot(mod(X,{s})-{s}/2,mod(Y,{s})-{s}/2),{s}/4),{int(c2[5:7], 16)},{int(c1[5:7], 16)})'")
            _ff(eng, ["-f", "lavfi", "-i", base, "-vf", vf, "-frames:v", "1", str(out)])
        return _img_out(eng, node, Path(td), out, _title(node, "Padrão"))


def run_out_thumbnail(eng, canvas, node):
    p = node["params"]
    title = _join_text(eng, canvas, node, "text").strip()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = _image_file(eng, _first(eng, canvas, node, "image", ("image", "video"), "uma imagem"), tmp)
        W, H = p["width"] // 2 * 2, p["height"] // 2 * 2
        vf = [f"scale={W}:{H}:force_original_aspect_ratio=increase", f"crop={W}:{H}"]
        if title and p["shade"] > 0:
            y0 = {"bottom": "ih*0.55", "center": "ih*0.3", "left": "0"}[p["layout"]]
            hh = {"bottom": "ih*0.45", "center": "ih*0.4", "left": "ih"}[p["layout"]]
            ww = "iw*0.55" if p["layout"] == "left" else "iw"
            vf.append(f"drawbox=x=0:y={y0}:w={ww}:h={hh}:color=black@{p['shade']}:t=fill")
        if title:
            font = find_font()
            tf = tmp / "t.txt"
            tf.write_text("\n".join(textwrap.fill(line, 22 if p["layout"] == "left" else 30) for line in title.splitlines()), encoding="utf-8")
            pos = {"bottom": ("(w-text_w)/2", "h*0.58"), "center": ("(w-text_w)/2", "(h-text_h)/2"), "left": ("w*0.04", "(h-text_h)/2")}[p["layout"]]
            opts = [f"textfile='{_esc_path(str(tf))}'", f"fontsize=h*{p['size'] / 100}", f"fontcolor={p['color']}", f"x={pos[0]}", f"y={pos[1]}", "line_spacing=8", "borderw=3", "bordercolor=black@0.7"]
            if font:
                opts.insert(1, f"fontfile='{_esc_path(font)}'")
            vf.append("drawtext=" + ":".join(opts))
        out = tmp / f"o.{p['format']}"
        try:
            _ff(eng, ["-i", str(src), "-vf", ",".join(vf), "-frames:v", "1", *(["-q:v", "3"] if p["format"] == "jpg" else []), str(out)])
        except ProviderError:
            raise ProviderError("Este ffmpeg não conseguiu desenhar o título (falta o filtro drawtext ou uma fonte instalada).") from None
        return _img_out(eng, node, tmp, out, _title(node, "Miniatura"))


RUNNERS: Dict[str, Callable[..., Dict[str, Any]]] = {k: globals()["run_" + k] for k in SPECS}
