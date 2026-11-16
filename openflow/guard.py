"""Proteção do computador (v0.49): se o consumo do hardware passa de um limite (padrão 90%) por alguns segundos enquanto o OpenFlow está trabalhando, **tudo o que o OpenFlow faz é parado**.

O que é medido, no computador inteiro (não só no OpenFlow): processador (CPU), memória (RAM) e placa de vídeo (memória de vídeo e, nas NVIDIA, o uso da GPU). Cada medida pode ser ligada ou desligada;
o limite e o tempo (em segundos) que ela precisa ficar acima dele valem para todas — assim um pico curto não derruba uma geração.

Quando dispara (`stop_all`): as tarefas em andamento (execuções do canvas, downloads…) são canceladas, os processos filhos (ffmpeg, sd-cli, ffprobe…) são encerrados e os modelos carregados saem da memória.
Só dispara se o OpenFlow está de fato trabalhando (tarefa rodando ou processo filho vivo): um computador sobrecarregado por outro programa, com o OpenFlow parado, não gera alarme.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULTS: Dict[str, Any] = {"enabled": True, "limit": 90, "hold_s": 5, "cpu": True, "ram": True, "gpu": True}
METRICS = ("cpu", "ram", "gpu")
COOLDOWN_S = 20.0   # depois de disparar, não dispara de novo por este tempo (dá tempo de a carga cair)


def normalize(cfg: Any) -> Dict[str, Any]:
    """Configuração válida (valor de tipo errado, vindo da API ou de edição à mão, volta ao padrão; limite entre 50 e 99 e tempo entre 1 e 60 s)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    out = dict(DEFAULTS)
    for k in ("enabled", "cpu", "ram", "gpu"):
        if isinstance(cfg.get(k), bool):
            out[k] = cfg[k]
    for k, lo, hi in (("limit", 50, 99), ("hold_s", 1, 60)):
        v = cfg.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = int(min(max(v, lo), hi))
    return out


# --------------------------------------------------------------------------- medidas (cada uma devolve 0–100, ou None se não dá para medir neste sistema)
_CPU_PREV: Dict[str, Tuple[float, float]] = {}


def _cpu_times() -> Optional[Tuple[float, float]]:
    """(tempo total, tempo ocioso) acumulados do sistema, ou None."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/stat", "r", encoding="utf-8") as fh:
                parts = fh.readline().split()
            vals = [float(x) for x in parts[1:9]]
            idle = vals[3] + vals[4]
            return sum(vals), idle
        except (OSError, ValueError, IndexError):
            return None
    if os.name == "nt":
        try:
            import ctypes

            class FT(ctypes.Structure):
                _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

            idle, kern, user = FT(), FT(), FT()
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
                return None
            v = lambda f: float((f.hi << 32) | f.lo)  # noqa: E731
            return v(kern) + v(user), v(idle)   # no Windows o tempo do kernel já inclui o ocioso
        except (AttributeError, OSError, ValueError):
            return None
    return None


def cpu_percent() -> Optional[float]:
    """Uso do processador (todo o sistema) desde a última chamada. A primeira chamada só guarda o ponto de partida."""
    cur = _cpu_times()
    if cur is None:
        return _cpu_fallback()
    prev = _CPU_PREV.get("t")
    _CPU_PREV["t"] = cur
    if not prev or cur[0] <= prev[0]:
        return None
    return max(0.0, min(100.0, 100.0 * (1.0 - (cur[1] - prev[1]) / (cur[0] - prev[0]))))


def _cpu_fallback() -> Optional[float]:
    """macOS e afins: a carga média de 1 minuto dividida pelos núcleos (aproximação)."""
    try:
        return max(0.0, min(100.0, 100.0 * os.getloadavg()[0] / (os.cpu_count() or 1)))
    except (AttributeError, OSError):
        return None


def ram_percent() -> Optional[float]:
    """Uso da memória RAM (todo o sistema): 100 × (1 − disponível/total)."""
    try:
        from . import native

        si = native.sys_info()
        total, avail = int(si.get("ram_total") or 0), int(si.get("ram_avail") or 0)
        if total <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (1.0 - avail / total)))
    except Exception:  # noqa: BLE001
        return None


_GPU_CACHE: Dict[str, Any] = {"t": 0.0, "v": None}


def gpu_percent() -> Optional[float]:
    """O maior entre o uso da memória de vídeo (NVIDIA/AMD/Intel dedicadas) e o uso da GPU (só NVIDIA, pelo nvidia-smi). Consulta no máximo a cada 3 s. None sem placa dedicada."""
    now = time.time()
    if now - _GPU_CACHE["t"] < 3.0:
        return _GPU_CACHE["v"]
    best: List[float] = []
    try:
        from . import perf

        total, free, unified = perf.gpu_memory(0, 0)
        if total > 0 and not unified:
            best.append(100.0 * (1.0 - free / total))
    except Exception:  # noqa: BLE001
        pass
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=4).stdout
            vals = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", out)]
            if vals:
                best.append(max(vals))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    v = max(best) if best else None
    _GPU_CACHE.update(t=now, v=v)
    return v


def sample() -> Dict[str, Optional[float]]:
    return {"cpu": cpu_percent(), "ram": ram_percent(), "gpu": gpu_percent()}


# --------------------------------------------------------------------------- processos filhos
def children_of(pid: int) -> List[int]:
    """Todos os descendentes (filhos, netos…) de um processo. Linux: /proc; macOS/BSD: pgrep -P; Windows: PowerShell. Lista vazia se não dá para saber."""
    out: List[int] = []
    try:
        if sys.platform.startswith("linux"):
            kids: Dict[int, List[int]] = {}
            for name in os.listdir("/proc"):
                if not name.isdigit():
                    continue
                try:
                    with open(f"/proc/{name}/stat", "r", encoding="utf-8", errors="replace") as fh:
                        stat = fh.read()
                    ppid = int(stat.rsplit(")", 1)[1].split()[1])
                except (OSError, ValueError, IndexError):
                    continue
                kids.setdefault(ppid, []).append(int(name))
            todo = [pid]
            while todo:
                for c in kids.get(todo.pop(), []):
                    out.append(c)
                    todo.append(c)
        elif os.name == "nt":
            ps = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId)\" }"], capture_output=True, text=True, timeout=10).stdout
            kids = {}
            for ln in ps.splitlines():
                a = ln.split()
                if len(a) == 2 and a[0].isdigit() and a[1].isdigit():
                    kids.setdefault(int(a[1]), []).append(int(a[0]))
            todo = [pid]
            while todo:
                for c in kids.get(todo.pop(), []):
                    out.append(c)
                    todo.append(c)
        elif shutil.which("pgrep"):
            todo = [pid]
            while todo:
                r = subprocess.run(["pgrep", "-P", str(todo.pop())], capture_output=True, text=True, timeout=5).stdout.split()
                for c in r:
                    if c.isdigit():
                        out.append(int(c))
                        todo.append(int(c))
    except (OSError, subprocess.SubprocessError):
        pass
    return [p for p in out if p != pid]


def kill_pids(pids: List[int]) -> int:
    """Encerra os processos (SIGKILL; no Windows, taskkill /F). Devolve quantos foram encerrados."""
    n = 0
    for p in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True, timeout=10)
            else:
                os.kill(p, 9)
            n += 1
        except (OSError, subprocess.SubprocessError, ProcessLookupError, PermissionError):
            pass
    return n


# --------------------------------------------------------------------------- a proteção
class Guard:
    """Vigia o hardware e, passando do limite por `hold_s` segundos com o OpenFlow trabalhando, para tudo. `app` = o servidor (precisa de `jobs` e `store`)."""

    def __init__(self, app: Any, sampler: Callable[[], Dict[str, Optional[float]]] = sample, now: Callable[[], float] = time.time) -> None:
        self.app = app
        self.sampler = sampler
        self.now = now
        self.lock = threading.Lock()
        self.latest: Dict[str, Optional[float]] = {"cpu": None, "ram": None, "gpu": None}
        self.over_since: Dict[str, Optional[float]] = {m: None for m in METRICS}
        self.last_trip: Optional[Dict[str, Any]] = None
        self.trips = 0
        self._cool_until = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---- configuração e estado
    def config(self) -> Dict[str, Any]:
        try:
            return normalize(((self.app.store.get_settings().get("performance") or {}).get("guard")))
        except Exception:  # noqa: BLE001
            return dict(DEFAULTS)

    def running_jobs(self) -> List[Any]:
        with self.app.jobs.lock:
            return [j for j in self.app.jobs.jobs.values() if j.status == "running"]

    def busy(self) -> bool:
        """O OpenFlow está trabalhando agora (tarefa rodando ou processo filho vivo)?"""
        return bool(self.running_jobs()) or bool(children_of(os.getpid()))

    def status(self) -> Dict[str, Any]:
        cfg = self.config()
        with self.lock:
            return {"enabled": cfg["enabled"], "limit": cfg["limit"], "hold_s": cfg["hold_s"], "watch": {m: cfg[m] for m in METRICS}, "metrics": dict(self.latest),
                    "supported": {m: self.latest[m] is not None for m in METRICS}, "over": [m for m in METRICS if self.over_since[m] is not None], "last_trip": self.last_trip, "trips": self.trips,
                    "running": len(self.running_jobs())}

    # ---- decisão (uma amostra por chamada; testável sem relógio nem hardware)
    def observe(self, metrics: Dict[str, Optional[float]], busy: bool, cfg: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Registra uma amostra e devolve o motivo (dict) se é hora de parar tudo, senão None."""
        cfg = cfg or self.config()
        t = self.now()
        with self.lock:
            self.latest = dict(metrics)
            if not cfg["enabled"] or not busy:
                self.over_since = {m: None for m in METRICS}
                return None
            tripped: List[Dict[str, Any]] = []
            for m in METRICS:
                v = metrics.get(m)
                if not cfg[m] or v is None or v < cfg["limit"]:
                    self.over_since[m] = None
                    continue
                if self.over_since[m] is None:
                    self.over_since[m] = t
                if t - self.over_since[m] >= cfg["hold_s"]:
                    tripped.append({"metric": m, "value": round(float(v), 1), "seconds": round(t - self.over_since[m], 1)})
            if not tripped or t < self._cool_until:
                return None
            return {"metrics": tripped, "limit": cfg["limit"], "hold_s": cfg["hold_s"]}

    # ---- ação
    def stop_all(self, reason: Dict[str, Any], manual: bool = False) -> Dict[str, Any]:
        """Cancela as tarefas, encerra os processos filhos e descarrega os modelos. Devolve o resumo (também guardado em `last_trip`)."""
        label = {"cpu": "processador", "ram": "memória RAM", "gpu": "placa de vídeo"}
        if manual:
            why = "Parada manual."
        else:
            why = "Proteção do computador: " + ", ".join(f"{label[x['metric']]} em {x['value']:g}% por {x['seconds']:g} s" for x in reason["metrics"]) + f" (limite {reason['limit']}%)."
        jobs = self.running_jobs()
        for j in jobs:
            try:
                j.meta["stopped_by"] = "guard"
                j.emit({"type": "note", "message": why + " Tudo foi parado."})
                j.cancel()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.6)   # as tarefas veem o cancelamento e encerram os próprios processos; o que sobrar é encerrado à força
        killed = kill_pids(children_of(os.getpid()))
        models = 0
        for fn in (self._unload_text, self._unload_media):
            try:
                models += 1 if fn() else 0
            except Exception:  # noqa: BLE001
                pass
        with self.lock:
            self.trips += 1
            self.last_trip = {"id": self.trips, "ts": round(self.now(), 1), "manual": manual, "reason": why, "metrics": dict(self.latest), "stopped": {"jobs": len(jobs), "processes": killed, "models": models}}
            self._cool_until = self.now() + COOLDOWN_S
            self.over_since = {m: None for m in METRICS}
            return dict(self.last_trip)

    @staticmethod
    def _unload_text() -> bool:
        from .providers import local_llama

        had = bool(local_llama._CACHE)
        local_llama._unload()
        return had

    @staticmethod
    def _unload_media() -> bool:
        from .canvas import media

        with media._LOCAL_LOCK:
            had = bool(media._LOCAL_CACHE)
        media._media_unload()
        return had

    # ---- vigia
    def tick(self) -> Optional[Dict[str, Any]]:
        metrics = self.sampler()
        cfg = self.config()
        busy = self.busy() if cfg["enabled"] else False
        reason = self.observe(metrics, busy, cfg)
        return self.stop_all(reason) if reason else None

    def start(self, interval: float = 1.0) -> None:
        if self._thread is not None:
            return

        def loop() -> None:
            cpu_percent()   # ponto de partida da medida de CPU
            while not self._stop.wait(interval):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 — o vigia nunca derruba o servidor
                    pass

        self._thread = threading.Thread(target=loop, daemon=True, name="openflow-guard")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
