"""Preferências de interface (aparência) — `settings.ui` — e exportação/importação das configurações.

Tudo que o usuário personaliza na tela vive aqui, validado: um valor inválido (por API ou edição manual) volta ao padrão em vez de quebrar a interface.
"""
from __future__ import annotations

import re
from typing import Any, Dict

THEMES = ("dark", "light", "auto")  # auto = segue o sistema operacional
SCALES = (90, 100, 110, 125, 150)  # % da interface
DENSITIES = ("comfortable", "compact")
MOTIONS = ("auto", "reduce", "full")  # auto = respeita o sistema; reduce = sem animações; full = sempre animar
FONTS = ("system", "serif", "mono")
LANGS = ("auto", "pt-BR", "en")

DEFAULT_UI: Dict[str, Any] = {
    "theme": "dark",
    "accent": "",  # "" = padrão do tema · ou "#rrggbb"
    "scale": 100,
    "density": "comfortable",
    "motion": "auto",
    "font": "system",
    "shortcuts": True,
    "welcome_done": False,
}

_HEX = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$")


def _choice(value: Any, allowed: tuple, default: Any) -> Any:
    return value if isinstance(value, (str, int)) and not isinstance(value, bool) and value in allowed else default


def normalize_accent(value: Any) -> str:
    s = str(value or "").strip().lower()
    if not _HEX.match(s):
        return ""
    return "#" + "".join(c * 2 for c in s[1:]) if len(s) == 4 else s


def normalize_ui(data: Any) -> Dict[str, Any]:
    """Preferências válidas (todas as chaves presentes); o que for inválido volta ao padrão."""
    d = data if isinstance(data, dict) else {}
    try:
        scale = int(float(d.get("scale", 100)))
    except (TypeError, ValueError):
        scale = 100
    return {
        "theme": _choice(d.get("theme"), THEMES, DEFAULT_UI["theme"]),
        "accent": normalize_accent(d.get("accent")),
        "scale": scale if scale in SCALES else 100,
        "density": _choice(d.get("density"), DENSITIES, DEFAULT_UI["density"]),
        "motion": _choice(d.get("motion"), MOTIONS, DEFAULT_UI["motion"]),
        "font": _choice(d.get("font"), FONTS, DEFAULT_UI["font"]),
        "shortcuts": d.get("shortcuts") is not False,
        "welcome_done": d.get("welcome_done") is True,
    }


# --------------------------------------------------------------------------- exportar / importar configurações (sem segredos)

EXPORT_SCHEMA = "openflow.settings.v1"
EXPORT_SECTIONS = ("language", "ui", "generation", "canvas", "performance", "active", "media")
RESETTABLE = ("ui", "generation", "canvas", "performance")   # voz e provedores têm chaves de API: não entram no "restaurar padrões"
_PROVIDER_FIELDS = ("base_url", "model", "vision", "n_ctx")  # nunca `api_key`


def export_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Configurações para levar a outro computador: as preferências e o que dá para reaproveitar. **Nunca** chaves de API nem tokens."""
    out: Dict[str, Any] = {k: settings[k] for k in EXPORT_SECTIONS if k in settings}
    out["providers"] = {pid: {k: v for k, v in (cfg or {}).items() if k in _PROVIDER_FIELDS and v not in (None, "")}
                        for pid, cfg in (settings.get("providers") or {}).items() if isinstance(cfg, dict)}
    voice = settings.get("voice") or {}
    out["voice"] = {part: {k: v for k, v in (voice.get(part) or {}).items() if k != "api_key"} for part in ("stt", "tts")}
    return {"schema": EXPORT_SCHEMA, "settings": out}


def import_patch(payload: Any) -> Dict[str, Any]:
    """Transforma um arquivo exportado em um *patch* seguro para `save_settings`: só seções conhecidas, sem segredos, UI validada."""
    if not isinstance(payload, dict) or payload.get("schema") != EXPORT_SCHEMA or not isinstance(payload.get("settings"), dict):
        raise ValueError("Este arquivo não é uma exportação de configurações do OpenFlow.")
    src = payload["settings"]
    patch: Dict[str, Any] = {}
    for key in ("generation", "canvas", "performance"):
        if isinstance(src.get(key), dict):
            patch[key] = src[key]
    if isinstance(src.get("ui"), dict):
        patch["ui"] = normalize_ui(src["ui"])
    if src.get("language") in LANGS:
        patch["language"] = src["language"]
    if isinstance(src.get("media"), dict):
        m = src["media"]
        patch["media"] = {k: m[k] for k in ("active", "models", "urls") if isinstance(m.get(k), dict)}
    if isinstance(src.get("active"), dict):
        patch["active"] = {k: v for k, v in src["active"].items() if isinstance(v, str)}
    if isinstance(src.get("providers"), dict):
        patch["providers"] = {pid: {k: v for k, v in cfg.items() if k in _PROVIDER_FIELDS} for pid, cfg in src["providers"].items() if isinstance(cfg, dict)}
    if isinstance(src.get("voice"), dict):
        patch["voice"] = {part: {k: v for k, v in (src["voice"].get(part) or {}).items() if k != "api_key"} for part in ("stt", "tts") if isinstance(src["voice"].get(part), dict)}
    return patch
