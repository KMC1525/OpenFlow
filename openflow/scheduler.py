"""Fila com prioridade para o que só pode acontecer uma vez por vez (o modelo local embutido).

Vários agentes disputam o mesmo modelo na memória: a conversa que o usuário está esperando (Chat, Avatars) não pode ficar atrás de uma geração de mundo de minutos.
`PriorityLock` é uma trava justa: quem tem prioridade maior (número menor) entra antes; com a mesma prioridade, a ordem de chegada. Tarefas em segundo plano (jobs) rodam com
prioridade baixa; a interface, com a alta. Usa-se como `with lock:` e a prioridade vem da thread (`set_priority`)."""
from __future__ import annotations

import heapq
import itertools
import threading
from typing import List, Tuple

INTERACTIVE, BACKGROUND = 0, 1
_local = threading.local()


def set_priority(level: int) -> None:
    """Prioridade da thread atual para as próximas esperas (0 = interativa, padrão; 1 = segundo plano)."""
    _local.level = int(level)


def priority() -> int:
    return int(getattr(_local, "level", INTERACTIVE))


def inherit(fn):
    """Embrulha `fn` para rodar em OUTRA thread (pool de agentes, trabalhadores) com a prioridade da thread que a embrulhou. A prioridade é por thread: sem isto, os agentes de uma
    tarefa em segundo plano nasceriam interativos e passariam na frente da conversa do usuário no modelo local embutido."""
    level = priority()

    def run(*args, **kwargs):
        set_priority(level)
        return fn(*args, **kwargs)
    return run


class PriorityLock:
    def __init__(self) -> None:
        self._cv = threading.Condition()
        self._held = False
        self._queue: List[Tuple[int, int]] = []
        self._seq = itertools.count()
        self.waiting = 0

    def acquire(self, level: int = -1) -> None:
        ticket = (priority() if level < 0 else int(level), next(self._seq))
        with self._cv:
            heapq.heappush(self._queue, ticket)
            self.waiting = len(self._queue)
            try:
                while self._held or self._queue[0] != ticket:
                    self._cv.wait()
            except BaseException:   # interrompido esperando: sai da fila e deixa o próximo passar
                self._queue.remove(ticket)
                heapq.heapify(self._queue)
                self.waiting = len(self._queue)
                self._cv.notify_all()
                raise
            heapq.heappop(self._queue)
            self.waiting = len(self._queue)
            self._held = True

    def release(self) -> None:
        with self._cv:
            self._held = False
            self._cv.notify_all()

    def locked(self) -> bool:
        return self._held

    def __enter__(self) -> "PriorityLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
