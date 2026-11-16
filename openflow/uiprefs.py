"""Preferências de interface (aparência) — `settings.ui` — e exportação/importação das configurações.

Tudo que o usuário personaliza na tela vive aqui, validado: um valor inválido (por API ou edição manual) volta ao padrão em vez de quebrar a interface.
"""
from __future__ import annotations

import re
from typing import Any, Dict

THEMES = ("dark", "light", "auto")  # auto = segue o sistema operacional
SCALE_MIN, SCALE_MAX, SCALE_STEP = 50, 200, 5  # % da interface (v0.50: de 50% a 200%, de 5 em 5)
DENSITIES = ("comfortable", "compact")
MOTIONS = ("auto", "reduce", "full")  # auto = respeita o sistema; reduce = sem animações; full = sempre animar
FONTS = ("system", "inter", "humanist", "rounded", "verdana", "readable", "book", "serif", "mono", "custom")   # v0.50: mais fontes (todas do próprio computador; "custom" = o nome de uma fonte instalada)
LANGS = ("auto", "pt-BR", "en")

DEFAULT_UI: Dict[str, Any] = {
    "theme": "dark",
    "accent": "",  # "" = padrão do tema · ou "#rrggbb"
    "scale": 100,
    "density": "comfortable",
    "motion": "auto",
    "font": "system",
    "font_custom": "",  # nome de uma fonte instalada no computador (usada com font = "custom")
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


_FONT_NAME = re.compile(r"[^\w .\-]", re.UNICODE)


def normalize_font_name(value: Any) -> str:
    """Nome de fonte seguro para ir ao CSS: só letras, números, espaço, ponto e hífen (nada de aspas, vírgulas ou `;`)."""
    return " ".join(_FONT_NAME.sub("", str(value or "")).split())[:60] if isinstance(value, str) else ""


def normalize_scale(value: Any) -> int:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 100
    if n != n or n in (float("inf"), float("-inf")):
        return 100
    step = int(n / SCALE_STEP + 0.5) * SCALE_STEP   # meio arredonda para cima, igual ao Math.round do boot.js
    return int(max(SCALE_MIN, min(SCALE_MAX, step)))


def normalize_ui(data: Any) -> Dict[str, Any]:
    """Preferências válidas (todas as chaves presentes); o que for inválido volta ao padrão."""
    d = data if isinstance(data, dict) else {}
    return {
        "theme": _choice(d.get("theme"), THEMES, DEFAULT_UI["theme"]),
        "accent": normalize_accent(d.get("accent")),
        "scale": normalize_scale(d.get("scale", 100)),
        "density": _choice(d.get("density"), DENSITIES, DEFAULT_UI["density"]),
        "motion": _choice(d.get("motion"), MOTIONS, DEFAULT_UI["motion"]),
        "font": _choice(d.get("font"), FONTS, DEFAULT_UI["font"]),
        "font_custom": normalize_font_name(d.get("font_custom")),
        "shortcuts": d.get("shortcuts") is not False,
        "welcome_done": d.get("welcome_done") is True,
    }


# --------------------------------------------------------------------------- exportar / importar configurações (sem segredos)

EXPORT_SCHEMA = "openflow.settings.v1"
EXPORT_SECTIONS = ("language", "ui", "canvas", "performance", "active", "media")
RESETTABLE = ("ui", "canvas", "performance")   # os provedores e o token do Hugging Face não entram no "restaurar padrões"
_PROVIDER_FIELDS = ("model", "n_ctx")


def export_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Configurações para levar a outro computador: as preferências e o que dá para reaproveitar. **Nunca** chaves de API nem tokens."""
    out: Dict[str, Any] = {k: settings[k] for k in EXPORT_SECTIONS if k in settings}
    out["providers"] = {pid: {k: v for k, v in (cfg or {}).items() if k in _PROVIDER_FIELDS and v not in (None, "")}
                        for pid, cfg in (settings.get("providers") or {}).items() if isinstance(cfg, dict)}
    return {"schema": EXPORT_SCHEMA, "settings": out}


def import_patch(payload: Any) -> Dict[str, Any]:
    """Transforma um arquivo exportado em um *patch* seguro para `save_settings`: só seções conhecidas, sem segredos, UI validada."""
    if not isinstance(payload, dict) or payload.get("schema") != EXPORT_SCHEMA or not isinstance(payload.get("settings"), dict):
        raise ValueError("Este arquivo não é uma exportação de configurações do OpenFlow.")
    src = payload["settings"]
    patch: Dict[str, Any] = {}
    for key in ("canvas", "performance"):
        if isinstance(src.get(key), dict):
            patch[key] = src[key]
    if isinstance(src.get("ui"), dict):
        patch["ui"] = normalize_ui(src["ui"])
    if src.get("language") in LANGS:
        patch["language"] = src["language"]
    if isinstance(src.get("media"), dict):
        m = src["media"]
        patch["media"] = {k: m[k] for k in ("active", "models") if isinstance(m.get(k), dict)}
    if isinstance(src.get("active"), dict):
        patch["active"] = {k: v for k, v in src["active"].items() if isinstance(v, str)}
    if isinstance(src.get("providers"), dict):
        patch["providers"] = {pid: {k: v for k, v in cfg.items() if k in _PROVIDER_FIELDS} for pid, cfg in src["providers"].items() if isinstance(cfg, dict)}
    return patch
