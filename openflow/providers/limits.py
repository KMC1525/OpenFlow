"""Limites de tokens dos modelos: quanto cada um aceita de resposta e de janela de contexto.

Os provedores recusam um `max_tokens` acima do que o modelo aguenta (cada modelo tem o seu teto) com mensagens bem diferentes. Em vez de o usuário descobrir isso
por tentativa e erro — e de a resposta longa que ele pediu virar um erro —, o OpenFlow **lê o teto na própria mensagem de erro**, refaz o pedido com o valor certo e
**lembra** dele para as próximas respostas daquele modelo (sem outra ida e volta).

Também há uma tabela *conservadora* de janelas de contexto conhecidas (`known_context`), só para a interface mostrar «este modelo aceita até X» — o valor
que vale é sempre o que o usuário configurou, nunca contrariado em silêncio.
"""
from __future__ import annotations

import re
import threading
from typing import Dict, Optional, Tuple

#: teto de saída aprendido por (provedor, modelo): {("openai", "gpt-x"): 16384}
_LEARNED: Dict[Tuple[str, str], int] = {}
_LOCK = threading.Lock()

_TOKEN_WORDS = re.compile(r"max[_ ]?(?:completion[_ ]?)?tokens|max[_ ]?output[_ ]?tokens|output tokens|completion tokens|maxoutputtokens|valid range", re.I)
_EXCLUSIVE = re.compile(r"(\d[\d,_]*)\s*\(\s*exclusive\s*\)", re.I)
_NUM = re.compile(r"(?<![\w.])(\d[\d,_]*)(?![\w.])")
_CTX_ERR = re.compile(r"maximum context length is (\d[\d,_]*) tokens.*?(?:requested|you requested|resulted in)[^\d]*(\d[\d,_]*)", re.I | re.S)
_CTX_PARTS = re.compile(r"(\d[\d,_]*)\s*(?:tokens)?\s*in the messages.*?(\d[\d,_]*)\s*(?:tokens)?\s*in the completion", re.I | re.S)


def _int(s: str) -> int:
    return int(re.sub(r"[,_]", "", s))


def fit_from_error(message: str, requested: int) -> Optional[int]:
    """O `max_tokens` que o provedor aceita, lido da mensagem de erro (ou None se a mensagem não fala disso).

    Cobre os formatos reais:
      • OpenAI: «max_tokens is too large: 200000. This model supports at most 16384 completion tokens»
      • Anthropic: «max_tokens: 100000 > 64000, which is the maximum allowed number of output tokens for …»
      • Gemini: «… maxOutputTokens value of 100000 but the supported range is from 1 (inclusive) to 8193 (exclusive)»
      • DeepSeek: «Invalid max_tokens value, the valid range of max_tokens is [1, 8192]»
      • OpenRouter/OpenAI (contexto): «maximum context length is 128000 tokens. However, you requested 140000 tokens (130000 in the messages, 10000 in the completion)»
        → o que sobra da janela depois do texto enviado.
    """
    msg = str(message or "")
    requested = int(requested or 0)
    if requested <= 0:
        return None
    m = _CTX_ERR.search(msg)
    if m:
        ctx = _int(m.group(1))
        parts = _CTX_PARTS.search(msg)
        sent = _int(parts.group(1)) if parts else None
        if sent is not None and ctx - sent >= 256 and ctx - sent < requested:
            return max(256, ctx - sent - 32)   # margem: a contagem do provedor pode diferir um pouco da nossa
        return None
    if not _TOKEN_WORDS.search(msg):
        return None
    ex = _EXCLUSIVE.search(msg)
    if ex and 256 <= _int(ex.group(1)) - 1 < requested:
        return _int(ex.group(1)) - 1
    cands = [n for n in (_int(x) for x in _NUM.findall(msg)) if 256 <= n < requested]
    return max(cands) if cands else None


def learn(provider_id: str, model: str, limit: int) -> None:
    if provider_id and model and limit >= 256:
        with _LOCK:
            _LEARNED[(provider_id, model)] = int(limit)


def cap(provider_id: str, model: str, requested: int) -> int:
    """`requested`, limitado pelo teto que já aprendemos para este modelo (se houver)."""
    with _LOCK:
        lim = _LEARNED.get((provider_id, model))
    return min(int(requested), lim) if lim else int(requested)


def forget() -> None:
    with _LOCK:
        _LEARNED.clear()


# --------------------------------------------------------------------------- janelas de contexto conhecidas (só para a interface informar)
# (regex do nome do modelo → tokens). Valores conservadores de modelos conhecidos; modelos novos ou desconhecidos simplesmente não aparecem.
_KNOWN = [
    (re.compile(r"llama-?4-?scout", re.I), 10_000_000),
    (re.compile(r"gemini-(1\.5-pro)", re.I), 2_000_000),
    (re.compile(r"gemini-(1\.5|2|3)", re.I), 1_000_000),
    (re.compile(r"grok-4(\.\d)?-fast|grok-4-1", re.I), 2_000_000),
    (re.compile(r"grok-4|grok-code", re.I), 256_000),
    (re.compile(r"gpt-4\.1", re.I), 1_000_000),
    (re.compile(r"gpt-5", re.I), 400_000),
    (re.compile(r"(^|[/-])o[134](-|$)", re.I), 200_000),
    (re.compile(r"claude.*(sonnet-4|opus-4-[6-9]|fable|mythos|opus-5|sonnet-5)", re.I), 1_000_000),
    (re.compile(r"claude", re.I), 200_000),
    (re.compile(r"qwen3?-?(coder-)?(plus|flash|turbo|max)|qwen-?long|qwen2\.5-1m", re.I), 1_000_000),
    (re.compile(r"minimax-m[12]|llama-?4-?maverick", re.I), 1_000_000),
    (re.compile(r"kimi-k2|glm-4\.[5-9]|deepseek|mistral-large|mistral-medium|command-r|qwen3|qwen2\.5", re.I), 128_000),
]


def known_context(model: str) -> int:
    """Janela de contexto conhecida do modelo (tokens), ou 0 se não sabemos."""
    name = str(model or "")
    for rx, n in _KNOWN:
        if rx.search(name):
            return n
    return 0
