"""Catálogo de provedores e fábrica."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .anthropic import AnthropicProvider
from .base import Provider, ProviderError
from .demo import DemoProvider
from .lmstudio import LMStudioProvider
from .local_llama import LocalLlamaProvider
from .openai_compat import OpenAICompatProvider

# kind: demo | anthropic | openai | local_hf
PRESETS: Dict[str, Dict[str, Any]] = {
    "demo": {
        "label": "Demo (offline, sem IA)", "kind": "demo", "local": True, "needs_key": False, "vision": False,
        "hint": "Gerador de regras para testar tudo sem chave e sem internet.",
    },
    "anthropic": {
        "label": "Claude (Anthropic)", "kind": "anthropic", "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-5-5", "needs_key": True, "vision": True,
        "docs": "https://console.anthropic.com/settings/keys",
    },
    "openai": {
        "label": "ChatGPT (OpenAI)", "kind": "openai", "base_url": "https://api.openai.com/v1",
        "model": "", "needs_key": True, "vision": True, "json": True,
        "docs": "https://platform.openai.com/api-keys",
    },
    "xai": {
        "label": "Grok (xAI)", "kind": "openai", "base_url": "https://api.x.ai/v1",
        "model": "", "needs_key": True, "vision": True, "json": True,
        "docs": "https://console.x.ai",
    },
    "google": {
        "label": "Gemini (Google)", "kind": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "", "needs_key": True, "vision": True,
        "docs": "https://aistudio.google.com/apikey",
    },
    "openrouter": {
        "label": "OpenRouter (centenas de modelos)", "kind": "openai", "base_url": "https://openrouter.ai/api/v1",
        "model": "", "needs_key": True, "vision": True,
        "docs": "https://openrouter.ai/keys",
    },
    "huggingface": {
        "label": "Hugging Face (Inference)", "kind": "openai", "base_url": "https://router.huggingface.co/v1",
        "model": "", "needs_key": True, "vision": False,
        "docs": "https://huggingface.co/settings/tokens",
    },
    "ollama": {
        "label": "Ollama (local)", "kind": "openai", "base_url": "http://127.0.0.1:11434/v1",
        "model": "", "needs_key": False, "local": True, "vision": False,
        "docs": "https://ollama.com/download",
    },
    "lmstudio": {
        "label": "LM Studio (local)", "kind": "openai", "base_url": "http://127.0.0.1:1234/v1",
        "model": "", "needs_key": False, "local": True, "vision": False,
        "docs": "https://lmstudio.ai",
        "hint": "Abra o LM Studio, ligue o servidor (Developer → Start Server) e carregue um modelo: o OpenFlow detecta sozinho o servidor e o modelo carregado.",
    },
    "llamacpp": {
        "label": "llama.cpp server (local)", "kind": "openai", "base_url": "http://127.0.0.1:8080/v1",
        "model": "", "needs_key": False, "local": True, "vision": False,
        "docs": "https://github.com/ggml-org/llama.cpp",
    },
    "local_hf": {
        "label": "Hugging Face GGUF (embutido)", "kind": "local_hf", "model": "", "needs_key": False,
        "local": True, "vision": False,
        "hint": 'Roda dentro do OpenFlow. Requer:  pip install "openflow[local]"',
    },
    "custom": {
        "label": "OpenAI-compatível (personalizado)", "kind": "openai", "base_url": "",
        "model": "", "needs_key": False, "vision": False,
    },
}


def provider_config(settings: Dict[str, Any], pid: str) -> Dict[str, Any]:
    preset = PRESETS.get(pid)
    if not preset:
        raise ProviderError(f"Provedor desconhecido: {pid}")
    cfg = dict(preset)
    user = (settings.get("providers") or {}).get(pid, {})
    for key in ("base_url", "api_key", "model", "vision", "n_ctx"):
        if key in user and user[key] not in (None, ""):
            cfg[key] = user[key]
    cfg["vision_user"] = "vision" in user and user["vision"] not in (None, "")  # o usuário decidiu a visão (senão o LM Studio a detecta pelo tipo do modelo)
    if pid == "huggingface" and not cfg.get("api_key"):
        cfg["api_key"] = (settings.get("hf") or {}).get("token", "")
    cfg["id"] = pid
    return cfg


def build_provider(settings: Dict[str, Any], pid: str, models_dir: Optional[Path] = None) -> Provider:
    cfg = provider_config(settings, pid)
    kind = cfg["kind"]
    if kind == "demo":
        return DemoProvider(cfg)
    if kind == "anthropic":
        return AnthropicProvider(cfg)
    if kind == "local_hf":
        cfg["models_dir"] = str(models_dir or ".")
        cfg["performance"] = settings.get("performance") or {}
        return LocalLlamaProvider(cfg)
    if cfg.get("id") == "lmstudio":
        return LMStudioProvider(cfg)  # detecta o servidor, usa o modelo carregado e a visão (vlm)
    return OpenAICompatProvider(cfg)


# onde o provedor deixa o usuário entrar na conta e criar a chave (login já com o destino certo)
LOGIN_PAGES = {
    "anthropic": "https://console.anthropic.com/login?returnTo=%2Fsettings%2Fkeys",
    "openai": "https://platform.openai.com/login?next=%2Fapi-keys",
    "xai": "https://console.x.ai",
    "google": "https://aistudio.google.com/apikey",
    "huggingface": "https://huggingface.co/login?next=%2Fsettings%2Ftokens",
}


def describe_presets() -> List[Dict[str, Any]]:
    out = []
    for pid, p in PRESETS.items():
        out.append({
            "id": pid, "label": p["label"], "kind": p["kind"], "base_url": p.get("base_url", ""),
            "model": p.get("model", ""), "needs_key": p.get("needs_key", False), "local": p.get("local", False),
            "vision": p.get("vision", False), "docs": p.get("docs", ""), "hint": p.get("hint", ""),
            "login": LOGIN_PAGES.get(pid, ""), "oauth": pid == "openrouter",
        })
    return out
