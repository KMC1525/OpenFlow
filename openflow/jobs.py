"""Tarefas em segundo plano (com eventos para SSE) e o erro HTTP usado pelas rotas.

Fica separado do servidor para que os módulos de rotas (avatars, jogos 2D, canvas)
possam usá-lo sem import circular.
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Callable, Dict, List, Optional

from .agents.runner import Cancelled
from .providers import ProviderError
from .util import new_id


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


MAX_EVENTS = 2000    # eventos guardados por tarefa; ao passar disso os mais antigos saem
KEEP_EVENTS = 1500


class Job:
    def __init__(self, kind: str):
        self.id = new_id("j_")
        self.kind = kind
        self.events: List[dict] = []
        self.base = 0   # quantos eventos antigos já foram descartados: `seq` e os índices do SSE são ABSOLUTOS (não mudam quando a lista é aparada)
        self.status = "running"  # running | done | error | cancelled
        self.cond = threading.Condition()
        self._cancel = threading.Event()
        self.created = time.time()
        self.result: Optional[dict] = None

    def emit(self, ev: dict) -> None:
        with self.cond:
            ev = dict(ev)
            ev["seq"] = self.base + len(self.events)
            self.events.append(ev)
            if len(self.events) > MAX_EVENTS:   # tarefa muito longa (equipes grandes): aparar o começo sem renumerar o resto
                drop = len(self.events) - KEEP_EVENTS
                del self.events[:drop]
                self.base += drop
            self.cond.notify_all()

    @property
    def total(self) -> int:
        """Quantos eventos a tarefa já emitiu (inclui os descartados): o próximo índice absoluto."""
        return self.base + len(self.events)

    def since(self, idx: int) -> List[dict]:
        """Os eventos de índice absoluto >= `idx` (quem pediu um trecho já descartado recebe a partir do mais antigo que ainda existe). Chamar com `cond` segurada."""
        return self.events[max(0, int(idx) - self.base):]

    def finish(self, status: str, result: Optional[dict] = None) -> None:
        with self.cond:
            self.status = status
            self.result = result
            self.cond.notify_all()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()


class JobManager:
    def __init__(self, store=None) -> None:
        self.jobs: Dict[str, Job] = {}
        self.lock = threading.Lock()
        self.store = store

    def start(self, kind: str, fn: Callable[[Job], Optional[dict]]) -> Job:
        job = Job(kind)
        with self.lock:
            for jid in [j for j, x in self.jobs.items() if x.status != "running" and time.time() - x.created > 3600]:
                self.jobs.pop(jid, None)
            self.jobs[job.id] = job

        def _remember(status: str, result: Optional[dict], err: str = "") -> None:
            if not self.store:
                return
            try:
                detail = {"job_id": job.id, "kind": kind, "status": status}
                if err:
                    detail["error"] = err[:300]
                if isinstance(result, dict):
                    for k in ("id", "project_id", "world_id", "game_id", "canvas_id", "studio_id", "text_id", "name", "title", "path"):
                        if k in result and result[k] not in (None, ""):
                            detail[k] = result[k]
                title = f"{kind}: {status}"
                summary = err[:400] if err else ("concluído" if status == "done" else status)
                self.store.remember("jobs", kind, title, summary, detail, [status])
            except Exception:
                pass

        def run() -> None:
            from . import scheduler

            scheduler.set_priority(scheduler.BACKGROUND)   # a conversa que o usuário espera passa na frente de uma geração longa no modelo local embutido
            try:
                res = fn(job)
                job.finish("done", res)
                _remember("done", res)
            except Cancelled:
                job.emit({"type": "cancelled"})
                job.finish("cancelled")
                _remember("cancelled", None)
            except ProviderError as exc:
                if str(exc) == "cancelado":
                    job.emit({"type": "cancelled"})
                    job.finish("cancelled")
                    _remember("cancelled", None)
                else:
                    job.emit({"type": "error", "message": str(exc), "kind": "provider"})
                    job.finish("error")
                    _remember("error", None, str(exc))
            except ValueError as exc:  # entrada inválida: mensagem para o usuário, sem traceback
                job.emit({"type": "error", "message": str(exc), "kind": "validation"})
                job.finish("error")
                _remember("error", None, str(exc))
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                job.emit({"type": "error", "message": str(exc) or exc.__class__.__name__, "kind": "internal"})
                job.finish("error")
                _remember("error", None, str(exc))

        threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
        return job

    def get(self, jid: str) -> Optional[Job]:
        return self.jobs.get(jid)

    def running(self, kind: str) -> Optional[Job]:
        return next((j for j in self.jobs.values() if j.kind == kind and j.status == "running"), None)
