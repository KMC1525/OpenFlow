"""Catálogo de provedores e fábrica (v0.35: só o Demo e os modelos locais do Hugging Face — nenhum provedor de nuvem)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import Provider, ProviderError
from .demo import DemoProvider
from .local_llama import LocalLlamaProvider

# kind: demo | local_hf
PRESETS: Dict[str, Dict[str, Any]] = {
    "demo": {
        "label": "Demo (offline, sem IA)", "kind": "demo", "local": True,
        "hint": "Gerador de regras para testar tudo sem chave e sem internet.",
    },
    "local_hf": {
        "label": "Hugging Face GGUF (embutido)", "kind": "local_hf", "model": "",
        "local": True,
        "hint": 'Roda dentro do OpenFlow, com modelos baixados do Hugging Face. Requer:  pip install "openflow[local]"',
    },
}


def provider_config(settings: Dict[str, Any], pid: str) -> Dict[str, Any]:
    preset = PRESETS.get(pid)
    if not preset:
        raise ProviderError(f"O provedor «{pid}» não existe mais: desde a v0.35 o OpenFlow usa só modelos locais do Hugging Face (e o Demo). Escolha o Demo ou o Hugging Face GGUF em Configuração → Provedores.")
    cfg = dict(preset)
    user = (settings.get("providers") or {}).get(pid, {})
    for key in ("model", "n_ctx"):
        if key in user and user[key] not in (None, ""):
            cfg[key] = user[key]
    cfg["id"] = pid
    return cfg


def build_provider(settings: Dict[str, Any], pid: str, models_dir: Optional[Path] = None) -> Provider:
    cfg = provider_config(settings, pid)
    if cfg["kind"] == "demo":
        return DemoProvider(cfg)
    cfg["models_dir"] = str(models_dir or ".")
    cfg["performance"] = settings.get("performance") or {}
    return LocalLlamaProvider(cfg)


def describe_presets() -> List[Dict[str, Any]]:
    out = []
    for pid, p in PRESETS.items():
        out.append({
            "id": pid, "label": p["label"], "kind": p["kind"], "model": p.get("model", ""), "local": True, "hint": p.get("hint", ""),
        })
    return out
