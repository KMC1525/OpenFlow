"""Escolha automática do provedor de IA do texto (v0.35: só o Demo e o modelo local GGUF do Hugging Face): o provedor de geração configurado, se estiver usável; senão o modelo local instalado; só se nada existir, o Demo.
Um provedor escolhido explicitamente (que não seja `auto`/`demo`) é sempre respeitado: se faltar o modelo ou a biblioteca, o erro aparece."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .registry import PRESETS, build_provider, provider_config

AUTO_VALUES = ("", "auto", "demo")


def _llama_installed() -> bool:
    try:
        return importlib.util.find_spec("llama_cpp") is not None
    except (ImportError, ValueError):
        return False


def local_text_model(settings: Dict[str, Any], models_dir: Optional[Path]) -> str:
    """Nome do GGUF de texto a usar: o escolhido nas configurações (se o arquivo existe) ou o pré-instalado já baixado; "" se não há."""
    if not models_dir:
        return ""
    models_dir = Path(models_dir)
    chosen = str(((settings.get("providers") or {}).get("local_hf") or {}).get("model") or "")
    if chosen:
        path = Path(chosen)
        if (path if path.is_absolute() else models_dir / chosen).is_file():
            return chosen
    from .. import preinstalled

    for e in preinstalled.CATALOG:
        if e["kind"] == "text" and (models_dir / Path(e["file"]).name).is_file():
            return Path(e["file"]).name
    return ""


def usable(settings: Dict[str, Any], pid: str, models_dir: Optional[Path]) -> bool:
    """O provedor tem o que precisa para responder (modelo baixado e biblioteca)? O Demo conta como "não": não é IA."""
    if pid not in PRESETS:
        return False
    cfg = provider_config(settings, pid)
    if cfg["kind"] == "local_hf":
        return bool(local_text_model(settings, models_dir)) and _llama_installed()
    return False


def _info(pid: str, provider: Any, auto: bool, reason: str = "") -> Dict[str, Any]:
    if hasattr(provider, "prepare") and not getattr(provider, "model", ""):
        try:
            provider.prepare()  # LM Studio: descobre o modelo carregado para mostrar qual responde
        except Exception:  # noqa: BLE001  (o erro com instruções aparece quando a conversa tentar usar o provedor)
            pass
    label = PRESETS.get(pid, {}).get("label", pid)
    return {"id": pid, "label": label, "model": getattr(provider, "model", "") or "", "demo": pid == "demo", "auto": auto, "reason": reason}


def resolve(settings: Dict[str, Any], role: str, models_dir: Optional[Path]) -> Tuple[Any, Dict[str, Any]]:
    """(provedor pronto, info) do papel `role`. `info`: {id, label, model, demo, auto, reason} — `reason` explica o Demo."""
    requested = str((settings.get("active") or {}).get(role) or "auto").lower()
    if requested not in AUTO_VALUES:
        provider = build_provider(settings, requested, models_dir)
        return provider, _info(requested, provider, False)
    gen = str((settings.get("active") or {}).get("generation") or "demo")
    if role != "generation" and gen not in AUTO_VALUES and usable(settings, gen, models_dir):
        provider = build_provider(settings, gen, models_dir)
        return provider, _info(gen, provider, True)
    model = local_text_model(settings, models_dir)
    if model and _llama_installed():
        s = copy.deepcopy(settings)
        s.setdefault("providers", {}).setdefault("local_hf", {})["model"] = model
        provider = build_provider(s, "local_hf", models_dir)
        return provider, _info("local_hf", provider, True)
    if model:
        reason = f"O modelo local {model} está instalado, mas falta a biblioteca llama-cpp-python: rode  flow libs --extras local  e reinicie o OpenFlow."
    else:
        reason = "Não há modelo de texto local instalado: baixe um pela barra de pesquisa de modelos dentro de um projeto (Canvas)."
    provider = build_provider(settings, "demo", models_dir)
    return provider, _info("demo", provider, True, reason)
