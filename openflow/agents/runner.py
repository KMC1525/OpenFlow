"""Base comum dos pipelines multi-agentes (mundos 3D, avatars, jogos 2D).

Cada etapa é um *agente*: recebe instruções + JSON de entrada e devolve um objeto JSON.
Resposta inválida → fallback determinístico (a entrega nunca falha por culpa do modelo);
erro de rede/credencial → o job falha com uma mensagem clara.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import team as teamlib
from ..providers import ProviderError
from . import prompts
from .llm import call_json

TRANSIENT = (408, 409, 425, 429, 500, 502, 503, 504, 529)


class Cancelled(Exception):
    pass


class Runner:
    #: domínio do pipeline: define o preâmbulo do prompt de sistema dos agentes
    domain = "flow"

    def __init__(self, store, emit: Callable[[dict], None], cancelled: Callable[[], bool] = lambda: False):
        self.store = store

        def announce(ev: dict) -> None:   # o evento «start» leva a equipe da execução (agentes e esforço) para a tela
            if isinstance(ev, dict) and ev.get("type") == "start" and "team" not in ev:
                ev = {**ev, "team": self.team.public()}
            emit(ev)

        self.emit = announce
        self.cancelled = cancelled
        self.logs: List[Tuple[str, str]] = []
        self.warnings: List[str] = []
        self._log_n = 0
        self._log_lock = threading.Lock()
        #: equipe da seção (agentes em paralelo + esforço): `configure_team()` troca; o padrão (1 agente, High) é o comportamento de sempre
        self.team = teamlib.Team()
        # preenchidos por cada pipeline em run()
        self.provider: Any = None
        self.gen: Dict[str, Any] = {}
        self.language = "the same language as the user's prompt"

    # ------------------------------------------------------------------ helpers
    def _check(self) -> None:
        if self.cancelled():
            raise Cancelled()

    def _step(self, sid: str, status: str, **detail: Any) -> None:
        self.emit({"type": "step", "id": sid, "status": status, "detail": detail, "t": time.time()})

    def configure_team(self, cfg: Any, req: Any = None, provider_id: str = "", **kw: Any) -> "teamlib.Team":
        """Lê a equipe da seção (`cfg`) e do pedido (`req`) e pede ao provedor o tempo de pensamento do esforço. O evento «start» seguinte leva a equipe para a tela."""
        self.team = teamlib.from_config(cfg, req, **kw)
        if self.provider is not None:
            teamlib.apply_thinking(self.provider, self.team, provider_id)
        return self.team

    def _log(self, agent: str, system: str, instruction: str, payload: Any, output: str) -> None:
        with self._log_lock:
            self._log_n += 1
            n = self._log_n
        body = (
            f"# Agente: {agent}\n\n## Instruções\n\n```\n{system}{instruction}\n```\n\n"
            f"## Entrada (JSON)\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)[:20000]}\n```\n\n"
            f"## Saída\n\n```json\n{output}\n```\n"
        )
        self.logs.append((f"{n:02d}-{agent}.md", body))

    def _note_dropped_images(self, agent: str) -> None:
        """O provedor não conseguiu enviar imagens (formato não aceito ou recusadas): a etapa seguiu só com o texto — avisa em vez de falhar."""
        n = int(getattr(self.provider, "images_dropped", 0) or 0)
        if n:
            self.provider.images_dropped = 0
            self.warnings.append(f"{agent}: {n} imagem(ns) não puderam ser enviadas ao provedor (formato não aceito ou modelo sem visão); seguiu só com o texto")

    def _call(self, system: str, agent: str, instruction: str, payload: Dict[str, Any], images: Optional[List[dict]], tokens_mult: float, salvage: bool, tag: str = "") -> Optional[Dict[str, Any]]:
        """UMA chamada de agente, com reparo do JSON e novas tentativas em erro passageiro. JSON inválido → None; erro de rede/credencial sobe."""
        last: Optional[Exception] = None
        for attempt in range(3):
            self._check()
            try:
                obj, raw = call_json(
                    self.provider, system, instruction, payload, images=images,
                    temperature=float(self.gen.get("temperature", 0.8)),
                    max_tokens=int(int(self.gen.get("max_tokens", 6000)) * tokens_mult * self.team.tokens_mult),
                    salvage=salvage, cancelled=self.cancelled,
                )
                self._log(agent + tag, system, instruction, payload, raw)
                return obj
            except ProviderError as exc:
                if str(exc) == "cancelado":
                    raise Cancelled() from None
                last = exc
                if exc.status in TRANSIENT and attempt < 2:
                    for _ in range(int(3 * (attempt + 1) * 2)):  # espera cancelável
                        self._check()
                        time.sleep(0.5)
                    continue
                raise
            except ValueError as exc:  # JSON inválido mesmo após reparo
                last = exc
                break
        self._last_error = str(last)
        return None

    def _agent(
        self, step: str, agent: str, instruction: str, payload: Dict[str, Any], fallback: Callable[[Dict[str, Any]], Dict[str, Any]],
        *, images: Optional[List[dict]] = None, tokens_mult: float = 1.0, feedback: bool = False, salvage: bool = False, solo: bool = False,
    ) -> Tuple[Dict[str, Any], bool]:
        """Executa um agente. JSON inválido → fallback determinístico. Erro de rede/credencial → falha o job.

        Com a equipe em 4 a 32 agentes (`self.team`), a etapa vira uma mesa em paralelo + um Sintetizador (`team.ensemble_json`); rodadas de correção (`feedback`) e etapas `solo` rodam com um só.
        De Max para cima, as etapas de plano ainda passam por uma rodada de crítica."""
        self._check()
        self._step(step, "running", revision=feedback)
        system = prompts.system_prompt(agent, self.language, self.gen.get("content", "free"), self.domain)
        self._last_error = ""
        team = self.team if not (feedback or solo) else teamlib.Team(1, self.team.effort)
        counter = [0]

        def ask(ins: str, pl: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            counter[0] += 1
            tag = f"-t{counter[0]:02d}" if team.multi else ""
            return self._call(system, agent, ins, pl, images, tokens_mult, salvage, tag)

        obj = teamlib.ensemble_json(ask, team, instruction, payload, cancelled=self.cancelled, fatal=(Cancelled,), note=lambda m: self.emit({"type": "note", "message": f"{agent}: {m}"}))
        self._check()
        if obj is not None and agent in teamlib.PLAN_AGENTS and self.team.critique and not feedback:
            obj = teamlib.critique_json(ask, instruction, payload, obj)
            self._check()
        self._note_dropped_images(agent)
        if obj is not None:
            return obj, False
        last = self._last_error or "JSON inválido"
        self.warnings.append(f"{agent}: fallback ({last})")
        self.emit({"type": "note", "message": f"{agent}: a IA não devolveu um JSON válido ({str(last)[:120]}); usei o método automático"})
        out = fallback(payload)
        self._log(agent, system, instruction, payload, "// FALLBACK determinístico: " + str(last) + "\n" + json.dumps(out, ensure_ascii=False, indent=2))
        return out, True
