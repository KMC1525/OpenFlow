"""Modelos instalados neste computador, para o seletor de modelo dos nós do Canvas (v0.17.3).

* **GGUF** de imagem e vídeo baixados em `<dados>/models/image` e `models/video` (provedor «GGUF local»);
* modelos do **Hugging Face local** baixados pelo OpenFlow (a pasta de cache tem o marcador `flow_precision.txt`, que guarda a precisão escolhida).
Os de nuvem (OpenAI, OpenRouter, xAI…) vêm dos provedores (`/api/media/models`) e das sugestões; aqui só entra o que está no disco.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from .. import hf
from .media import MEDIA_PRESETS, media_config
from .localmodels import MARKER, PRECISIONS


SUPPORT_RE = re.compile(r"(qwen2[._]?5.*vl|qwen3-|t5xxl|clip[_-]?[lg]\b|clip[_-]?vision|umt5|mmproj|high[-_]?noise)", re.I)   # `high-noise`: o segundo modelo do Wan2.2 A14B


def hf_cache_dir() -> Path:
    env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if env:
        return Path(env)
    return Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub"


def downloaded_hf_models() -> List[Dict[str, str]]:
    """Os modelos que o OpenFlow baixou no cache do Hugging Face: [{model: "dono/nome", precision}]."""
    root = hf_cache_dir()
    out: List[Dict[str, str]] = []
    if not root.is_dir():
        return out
    for d in sorted(root.glob("models--*--*")):
        parts = d.name[len("models--"):].split("--", 1)
        if len(parts) != 2 or not all(parts):
            continue
        for marker in (d / "snapshots").glob(f"*/{MARKER}") if (d / "snapshots").is_dir() else ():
            try:
                prec = marker.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if prec in PRECISIONS:
                out.append({"model": f"{parts[0]}/{parts[1]}", "precision": prec})
                break
    return out


def installed(settings: Dict[str, Any], models_dir: Path, cap: str) -> List[Dict[str, Any]]:
    """[{provider, model, label, size?, detail}] dos modelos locais utilizáveis para a capacidade `cap` (image, video, sound, voice, stt)."""
    items: List[Dict[str, Any]] = []
    if cap in ("image", "video"):
        from .. import preinstalled

        support = {Path(c["file"]).name for e in preinstalled.CATALOG for c in e.get("companions", [])}
        for m in hf.local_models(models_dir, cap):
            if m["name"] in support or SUPPORT_RE.search(m["name"]):   # codificadores de texto e afins são arquivos de apoio de outro modelo, não modelos para escolher
                continue
            items.append({"provider": "gguf_local", "model": m["name"], "label": m["name"], "size": m.get("size", 0), "detail": " · ".join(x for x in (m.get("quant") or "", "GGUF") if x)})
    preset = MEDIA_PRESETS.get("local_hf") or {}
    if cap in preset.get("caps", []):
        cfg = media_config(settings, "local_hf")
        known = {cfg["models"].get(cap, "")} | set((preset.get("suggest") or {}).get(cap, []))
        for d in downloaded_hf_models():
            items.append({"provider": "local_hf", "model": d["model"], "label": d["model"], "size": 0, "detail": d["precision"] + " · Hugging Face local", "match": d["model"] in known})
    return items
