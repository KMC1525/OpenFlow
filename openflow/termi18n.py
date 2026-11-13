"""Idioma dos textos do terminal (linha de comando e instaladores): o mesmo idioma do computador do usuário.

Português (qualquer variante: pt, pt-BR, pt-PT…) ou inglês — qualquer outro idioma cai no inglês. A detecção olha, nesta ordem:
`OPENFLOW_LANG` (pt|en, força) → `LC_ALL` → `LC_MESSAGES` → `LANGUAGE` → `LANG` → (macOS) `AppleLanguages` → (Windows) idioma da interface do usuário.
`_()` recebe o texto em português (a fonte) e devolve a versão no idioma do computador; os `{campos}` são preenchidos com os argumentos nomeados.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict, Optional

_CACHE: Optional[str] = None


def _from_code(code: str) -> Optional[str]:
    c = (code or "").strip().lower()
    if not c or c in ("c", "posix"):
        return None
    c = c.split(":")[0].replace("-", "_")
    return "pt" if c.startswith("pt") else "en"


def _mac_lang() -> Optional[str]:
    try:
        out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=3).stdout
        for tok in out.replace("(", " ").replace(")", " ").replace(",", " ").replace('"', " ").split():
            return _from_code(tok)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _windows_lang() -> Optional[str]:
    try:
        import ctypes

        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
        return "pt" if (lid & 0x3FF) == 0x16 else "en"   # 0x16 = LANG_PORTUGUESE
    except Exception:  # noqa: BLE001
        return None


def system_lang(refresh: bool = False) -> str:
    """"pt" ou "en", o idioma do computador (ou o forçado por OPENFLOW_LANG)."""
    global _CACHE
    forced = _from_code(os.environ.get("OPENFLOW_LANG", ""))
    if forced:
        return forced
    if _CACHE is not None and not refresh:
        return _CACHE
    found: Optional[str] = None
    for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        found = _from_code(os.environ.get(var, ""))
        if found:
            break
    if not found and sys.platform == "darwin":
        found = _mac_lang()
    if not found and os.name == "nt":
        found = _windows_lang()
    _CACHE = found or "en"
    return _CACHE


def _(pt: str, **kw: Any) -> str:
    """O texto no idioma do computador. `pt` é a frase em português (com `{campos}`); sem tradução, fica em português."""
    s = pt if system_lang() == "pt" else EN.get(pt, pt)
    return s.format(**kw) if kw else s


from .term_en import EN  # noqa: E402  (tradução inglesa dos textos; a fonte é o português)
