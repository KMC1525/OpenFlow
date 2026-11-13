"""Tempo de pensamento do Chat: slow · medium · high · extra high · ultra (e «off»).

Cada provedor/modelo expõe isso de um jeito, e nem todo modelo tem o recurso. `support()` diz, para um provedor e um modelo, **se há suporte e como**;
a interface só mostra o seletor ao lado do nome do modelo quando há. Os modos:

  • `budget`  — Claude (pensamento estendido): `thinking: {type: enabled, budget_tokens}`; o orçamento vai **além** do tamanho da resposta.
  • `effort`  — modelos de raciocínio da OpenAI (o-series, GPT-5), Gemini 2.5+/3 (endpoint compatível), gpt-oss (LM Studio/Ollama…): `reasoning_effort`.
  • `reasoning` — OpenRouter: `reasoning: {effort}` (o OpenRouter ignora em modelos sem o recurso).
Os cinco níveis crescem em tempo/tokens gastos pensando; acima de `high`, os provedores de «esforço» só têm três degraus (low/medium/high), então
`extra high` e `ultra` usam `high` com mais folga de tokens para o raciocínio — e o aviso diz isso.
"""
from __future__ import annotations

import re
from typing import Any, Dict

LEVELS = ("off", "slow", "medium", "high", "xhigh", "ultra")
LABELS = {"off": "Desligado", "slow": "Slow", "medium": "Medium", "high": "High", "xhigh": "Extra high", "ultra": "Ultra"}
#: tokens de pensamento (Claude) e folga extra para raciocínio embutido (OpenAI/Gemini…)
BUDGET = {"slow": 1024, "medium": 4000, "high": 10000, "xhigh": 20000, "ultra": 32000}
HEADROOM = {"slow": 1000, "medium": 4000, "high": 8000, "xhigh": 16000, "ultra": 24000}
EFFORT = {"slow": "low", "medium": "medium", "high": "high", "xhigh": "high", "ultra": "high"}
#: maior `max_tokens` total aceito com pensamento (modelos Claude mais antigos limitam a saída em 32k)
MAX_TOTAL = 32000

_CLAUDE = re.compile(r"claude-(3-7|(opus|sonnet|haiku)-[4-9]|[4-9]|fable|mythos)|(opus|sonnet|haiku)-[4-9]|fable", re.I)
_OPENAI = re.compile(r"^(o[1-9]|gpt-5)|/(o[1-9]|gpt-5)", re.I)
_GEMINI = re.compile(r"gemini-(2\.5|[3-9])", re.I)
_OSS = re.compile(r"gpt-oss", re.I)
_ROUTER = re.compile(r"(^|/)(o[1-9]|gpt-5|claude|gemini-(2\.5|[3-9])|deepseek-r1|qwen3|grok-[3-9]|glm-4\.[5-9]|kimi-k2)", re.I)


def normalize(level: Any) -> str:
    s = str(level or "off").strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    return {"extrahigh": "xhigh", "xhigh": "xhigh", "off": "off", "none": "off"}.get(s, s) if s in ("extrahigh", "xhigh", "off", "none") or s in LEVELS else "off"


def support(provider_id: str, model: str) -> Dict[str, Any]:
    """{supported, kind, note}: o provedor `provider_id` com o modelo `model` aceita escolher o tempo de pensamento?"""
    pid, m = (provider_id or "").lower(), model or ""
    kind = ""
    if pid == "anthropic" and _CLAUDE.search(m):
        kind = "budget"
    elif pid == "openai" and _OPENAI.search(m):
        kind = "effort"
    elif pid == "gemini" and _GEMINI.search(m):
        kind = "effort"
    elif pid in ("lmstudio", "ollama", "llamacpp", "custom") and _OSS.search(m):
        kind = "effort"
    elif pid == "openrouter" and _ROUTER.search(m):
        kind = "reasoning"
    note = {"budget": "Pensamento estendido do Claude: o nível define quantos tokens ele pode gastar pensando antes de responder.",
            "effort": "Esforço de raciocínio do modelo (low/medium/high): extra high e ultra usam high com mais folga de tokens.",
            "reasoning": "Esforço de raciocínio via OpenRouter (vale para modelos que têm o recurso)."}.get(kind, "")
    return {"supported": bool(kind), "kind": kind, "note": note}


def body_extra(kind: str, level: str, max_tokens: int) -> Dict[str, Any]:
    """Campos a mesclar no corpo da requisição para `level` (já normalizado, ≠ off). `max_tokens` = tamanho da resposta pedida."""
    if kind == "effort":
        return {"reasoning_effort": EFFORT[level]}
    if kind == "reasoning":
        return {"reasoning": {"effort": EFFORT[level]}}
    return {}


def total_tokens(kind: str, level: str, answer: int) -> int:
    """`max_tokens` a enviar: a resposta + a folga de pensamento (o tamanho da resposta nas configurações vale só para o texto visível)."""
    if kind == "budget":
        return answer + budget_for(level, answer)
    if kind in ("effort", "reasoning"):
        return answer + HEADROOM[level]
    return answer


def budget_for(level: str, answer: int) -> int:
    """Orçamento de pensamento do Claude: o do nível, limitado para caber em MAX_TOTAL; 0 se não cabe o mínimo (1024)."""
    b = min(BUDGET[level], MAX_TOTAL - int(answer))
    return b if b >= 1024 else 0
