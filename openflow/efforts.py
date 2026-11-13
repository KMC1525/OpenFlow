"""Níveis de esforço — Low · Medium · High · Extra · Mega · Max · Ultra · Omni — dos nós de texto com IA e do planejador de fluxos (ver `team.py`).

O esforço vale **igualmente** para modelos de nuvem (frontier) e locais, porque a maior parte dele é do próprio motor do OpenFlow — quantos passos cada agente pode dar, quantas rodadas de revisão
e correção, quanto contexto cada agente enxerga, se roda os testes, se escreve testes novos, se o plano é revisado antes de começar. Além disso, onde o provedor/modelo tem «tempo de pensamento»
(`providers/thinking.py`: Claude, OpenAI o-series/GPT-5, Gemini 2.5+, gpt-oss…), o nível correspondente é pedido ao modelo; nos demais (a maioria dos locais) só o orçamento do motor cresce.
"""
from __future__ import annotations

from typing import Any, Dict, List

LEVELS = ("low", "medium", "high", "extra", "mega", "max", "ultra", "omni")
DEFAULT = "high"

# turns: ações por agente · plan_steps: tarefas do plano · revisions: rodadas de correção após a revisão · obs_chars: tamanho do resultado visto a cada passo · history: passos recentes lembrados
# op_tokens: tamanho da resposta de cada passo · thinking: tempo de pensamento pedido quando há suporte · review: revisor de IA · tests: roda os testes do projeto ao final · self_check: o agente confere o próprio passo
# critique_plan: o plano é criticado e refeito antes de começar · explore: o agente é orientado a ler mais do projeto antes de mexer
PROFILES: Dict[str, Dict[str, Any]] = {
    "low": {"label": "Low", "hint": "Rápido e mínimo: a menor mudança que resolve. Poucos passos e nenhuma revisão por IA.",
            "turns": 12, "plan_steps": 3, "revisions": 0, "obs_chars": 3000, "history": 6, "op_tokens": 1800, "thinking": "off", "review": False, "tests": False, "self_check": False, "critique_plan": False, "explore": 0},
    "medium": {"label": "Medium", "hint": "Equilibrado para tarefas pequenas: um plano curto, uma revisão e testes quando já existirem.",
               "turns": 24, "plan_steps": 5, "revisions": 0, "obs_chars": 4000, "history": 8, "op_tokens": 2400, "thinking": "slow", "review": True, "tests": True, "self_check": False, "critique_plan": False, "explore": 1},
    "high": {"label": "High", "hint": "Padrão: lê o código antes de mexer, roda os testes e corrige uma vez o que a revisão apontar.",
             "turns": 40, "plan_steps": 7, "revisions": 1, "obs_chars": 5000, "history": 10, "op_tokens": 3000, "thinking": "medium", "review": True, "tests": True, "self_check": False, "critique_plan": False, "explore": 2},
    "extra": {"label": "Extra", "hint": "Mais cuidado: explora mais arquivos, pensa mais por passo e confere cada tarefa ao terminar.",
              "turns": 60, "plan_steps": 8, "revisions": 1, "obs_chars": 6000, "history": 12, "op_tokens": 3600, "thinking": "high", "review": True, "tests": True, "self_check": True, "critique_plan": False, "explore": 3},
    "mega": {"label": "Mega", "hint": "Para mudanças médias e grandes: duas rodadas de correção, escreve testes novos e confere cada tarefa.",
             "turns": 80, "plan_steps": 9, "revisions": 2, "obs_chars": 7000, "history": 14, "op_tokens": 4200, "thinking": "xhigh", "review": True, "tests": True, "self_check": True, "critique_plan": False, "explore": 4},
    "max": {"label": "Max", "hint": "Máximo de passos e contexto por agente; o plano passa por uma crítica antes de começar.",
            "turns": 110, "plan_steps": 10, "revisions": 2, "obs_chars": 8000, "history": 16, "op_tokens": 5000, "thinking": "xhigh", "review": True, "tests": True, "self_check": True, "critique_plan": True, "explore": 5},
    "ultra": {"label": "Ultra", "hint": "Refatorações e bases de código grandes: plano criticado, três rodadas de correção e raciocínio no teto do modelo.",
              "turns": 150, "plan_steps": 12, "revisions": 3, "obs_chars": 9000, "history": 18, "op_tokens": 6000, "thinking": "ultra", "review": True, "tests": True, "self_check": True, "critique_plan": True, "explore": 6},
    "omni": {"label": "Omni", "hint": "Tudo ligado: exploração ampla, plano criticado, conferência dupla e até três rodadas de correção. Demora e gasta mais.",
             "turns": 220, "plan_steps": 14, "revisions": 3, "obs_chars": 10000, "history": 20, "op_tokens": 7000, "thinking": "ultra", "review": True, "tests": True, "self_check": True, "critique_plan": True, "explore": 8},
}

# o que cada nível diz ao agente (entra no system prompt; em inglês, como os demais prompts)
GUIDANCE: Dict[str, str] = {
    "low": "Effort LOW: be fast and minimal. Make the smallest change that solves the request. Do not explore beyond the files you need, do not refactor, do not add extras.",
    "medium": "Effort MEDIUM: read the files you are about to change, make a focused change, and run the existing tests once if there are any.",
    "high": "Effort HIGH: read the relevant code and its neighbours before editing, follow the project's conventions, run the project's tests and linter when they exist, and fix what they report.",
    "extra": "Effort EXTRA: explore the surrounding code and callers before editing, consider edge cases and error handling, run the tests and linter, and re-read your own diff before finishing.",
    "mega": "Effort MEGA: investigate thoroughly, handle edge cases, write or update tests for what you change, run the full test suite and linter, and re-read every file you changed before finishing.",
    "max": "Effort MAX: be exhaustive. Map the affected modules, check callers and dependants, write tests for new behaviour and regressions, run tests/linter/build, and verify the result against the goal point by point.",
    "ultra": "Effort ULTRA: treat the task as a careful engineering change. Map the architecture first, plan the change in safe steps, keep the build green after each step, write tests, and double-check security, performance and compatibility.",
    "omni": "Effort OMNI: do everything a principal engineer would: study the whole affected area, design before coding, implement in small verified steps, write thorough tests, run build/tests/linter, review your own diff critically, update docs and changelogs, and report honestly what was and was not verified.",
}


def normalize(level: Any) -> str:
    s = str(level or "").strip().lower()
    return s if s in LEVELS else DEFAULT


def profile(level: Any) -> Dict[str, Any]:
    lv = normalize(level)
    return {"id": lv, **PROFILES[lv]}


def guidance(level: Any) -> str:
    return GUIDANCE[normalize(level)]


def listing() -> List[Dict[str, Any]]:
    """Os oito níveis para a tela (rótulo, descrição e o que muda em cada um)."""
    return [{"id": k, "label": PROFILES[k]["label"], "hint": PROFILES[k]["hint"], "turns": PROFILES[k]["turns"], "revisions": PROFILES[k]["revisions"], "tests": PROFILES[k]["tests"],
             "review": PROFILES[k]["review"], "thinking": PROFILES[k]["thinking"], "critique_plan": PROFILES[k]["critique_plan"]} for k in LEVELS]


def thinking_level(level: Any) -> str:
    """O nível de «tempo de pensamento» (`providers/thinking.py`) que corresponde ao esforço."""
    return PROFILES[normalize(level)]["thinking"]
