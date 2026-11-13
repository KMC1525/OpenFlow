"""Modo de desempenho: quanto de RAM/VRAM e CPU os modelos locais podem usar.

`settings.performance.mode`:
* ``auto`` (padrão) — decide pelo hardware: PC fraco → leve; intermediário → equilibrado; potente → máximo;
* ``light`` — o mínimo de memória: janela de contexto limitada, cache de atenção quantizado (q8), modelos descarregados logo que ficam ociosos,
  modelos de imagem/áudio em fp16 com fatias de atenção e descarregando para a CPU o que não está em uso;
* ``balanced`` — meio-termo;
* ``max`` — tudo na memória, sem limites do OpenFlow.
Os pesos continuam sendo mapeados do disco (mmap): só as páginas usadas ocupam RAM.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Optional

MODES = ("auto", "light", "balanced", "max")
DEFAULTS = {"mode": "auto", "idle_unload_min": 10}


def resolve(mode: str, hw: Dict[str, Any]) -> str:
    if mode in ("light", "balanced", "max"):
        return mode
    return {"low": "light", "medium": "balanced", "high": "max"}.get(hw.get("tier", "medium"), "balanced")


def profile(perf: Optional[Dict[str, Any]], hw: Dict[str, Any]) -> Dict[str, Any]:
    """Parâmetros concretos para o modo escolhido (`perf` = settings["performance"], pode ser {})."""
    perf = perf if isinstance(perf, dict) else {}
    mode = resolve(str(perf.get("mode") or "auto"), hw)
    try:
        idle = max(0, min(int(perf.get("idle_unload_min", DEFAULTS["idle_unload_min"])), 24 * 60))
    except (TypeError, ValueError):
        idle = DEFAULTS["idle_unload_min"]
    base = {
        "light": {"ctx_cap": 4096, "n_batch": 128, "kv_q8": True, "flash": True, "idle_s": min(idle, 3) * 60 if idle else 0, "media_offload": True, "attention_slicing": True},
        "balanced": {"ctx_cap": 16384, "n_batch": 256, "kv_q8": False, "flash": True, "idle_s": idle * 60, "media_offload": False, "attention_slicing": False},
        "max": {"ctx_cap": 0, "n_batch": 512, "kv_q8": False, "flash": False, "idle_s": 0, "media_offload": False, "attention_slicing": False},
    }[mode]
    return {"mode": mode, **base}


def describe(p: Dict[str, Any]) -> str:
    return {"light": "leve (menos RAM/VRAM)", "balanced": "equilibrado", "max": "máximo"}[p["mode"]]


def cap_context(n: int, p: Dict[str, Any], explicit: bool) -> int:
    """Limita a janela de contexto no modo leve/equilibrado — mas nunca contraria um valor que o usuário definiu à mão."""
    cap = int(p.get("ctx_cap") or 0)
    return n if explicit or not cap else min(n, cap)


class IdleUnloader:
    """Descarrega um recurso pesado (modelo na RAM/VRAM) depois de `idle_s` segundos sem uso."""

    def __init__(self, unload: Callable[[], None]):
        self._unload, self._last, self._idle, self._timer = unload, time.time(), 0, None
        self._lock = threading.Lock()

    def touch(self, idle_s: int) -> None:
        with self._lock:
            self._last, self._idle = time.time(), int(idle_s)
            if self._timer is not None:
                self._timer.cancel()
            self._timer = None
            if self._idle > 0:
                self._timer = threading.Timer(self._idle + 1, self._fire)
                self._timer.daemon = True
                self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            if self._idle <= 0 or time.time() - self._last < self._idle:
                return
        try:
            self._unload()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- menos CPU: subprocessos (ffmpeg…) com prioridade baixa e menos threads
_FFMPEG_NAMES = ("ffmpeg", "ffmpeg.exe")
CURRENT: Dict[str, Any] = {}   # settings["performance"] em vigor (o Store atualiza ao abrir e ao salvar): quem roda o ffmpeg não precisa receber as configurações


def configure(perf_cfg: Optional[Dict[str, Any]]) -> None:
    CURRENT.clear()
    CURRENT.update(perf_cfg if isinstance(perf_cfg, dict) else {})


def run(cmd: list, **kw: Any) -> "subprocess.CompletedProcess":
    """`subprocess.run` que gasta menos CPU nas chamadas do ffmpeg (ver `wrap_command`)."""
    cmd, extra = wrap_command(cmd)
    for k, v in extra.items():
        kw[k] = kw.get(k, 0) | v if k == "creationflags" else kw.setdefault(k, v)
    return subprocess.run(cmd, **kw)


def cpu_profile(perf_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Quanto da CPU as tarefas pesadas fora do Python (ffmpeg) podem usar. Leve: metade dos núcleos físicos e prioridade baixa; equilibrado: todos os físicos menos um e prioridade
    baixa (a interface continua fluida enquanto exporta); máximo: tudo, prioridade normal. O resultado é o mesmo — muda só o tempo e o calor/ruído/bateria."""
    from . import native
    from .util import hardware_info

    mode = resolve(str((perf_cfg or {}).get("mode") or "auto"), hardware_info())
    si = native.sys_info()
    phys = max(1, int(si.get("physical") or 1))
    threads = {"light": max(1, phys // 2), "balanced": max(1, phys - 1 if phys > 2 else phys), "max": 0}[mode]
    return {"mode": mode, "ffmpeg_threads": threads, "low_priority": mode != "max"}


def wrap_command(cmd: list, perf_cfg: Optional[Dict[str, Any]] = None) -> tuple:
    """(comando, kwargs do subprocess) para rodar `cmd` gastando menos CPU conforme o modo de desempenho. Só mexe em chamadas do ffmpeg:
    acrescenta `-threads N` e, onde existe, baixa a prioridade (`nice` no macOS/Linux; classe «abaixo do normal» no Windows). Qualquer outro comando passa intacto."""
    cmd = list(cmd)
    perf_cfg = CURRENT if perf_cfg is None else perf_cfg
    kwargs: Dict[str, Any] = {}
    if not cmd or os.path.basename(str(cmd[0])).lower() not in _FFMPEG_NAMES:
        return cmd, kwargs
    prof = cpu_profile(perf_cfg)
    if prof["ffmpeg_threads"] and "-threads" not in cmd and len(cmd) > 2:
        n = str(prof["ffmpeg_threads"])
        # `-threads` vale para o próximo arquivo: antes da primeira entrada limita a decodificação; antes da saída (o último argumento) limita o codificador
        cmd = [cmd[0], "-threads", n, *cmd[1:-1], "-threads", n, cmd[-1]]
    if prof["low_priority"]:
        if os.name == "nt":
            kwargs["creationflags"] = 0x00004000   # BELOW_NORMAL_PRIORITY_CLASS
        elif shutil.which("nice"):
            cmd = ["nice", "-n", "10", *cmd]
    return cmd, kwargs


# --------------------------------------------------------------------------- memória livre agora (para o planejador do núcleo Rust)
MODE_NUM = {"light": 0, "balanced": 1, "max": 2}
_GPU_CACHE: Dict[str, Any] = {"t": 0.0, "v": (0, 0, False)}


def gpu_memory(ram_total: int = 0, ram_avail: int = 0) -> tuple:
    """(VRAM total, VRAM livre, memória unificada?) em bytes. NVIDIA: nvidia-smi. Apple Silicon: a GPU usa a RAM (≈65% dela). Sem GPU: zeros."""
    now = time.time()
    if now - _GPU_CACHE["t"] < 3.0:
        return _GPU_CACHE["v"]
    v: tuple = (0, 0, False)
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
            if out:
                tot, free = (int(float(x)) * 1048576 for x in out[0].split(","))
                v = (tot, free, False)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    if v[0] == 0 and platform.system() == "Darwin" and "arm" in platform.machine().lower() and ram_total:
        v = (int(ram_total * 0.65), int(min(ram_avail, ram_total) * 0.65), True)
    _GPU_CACHE.update(t=now, v=v)
    return v


def memory_state() -> Dict[str, Any]:
    """RAM/VRAM livres e núcleos agora (núcleo Rust quando há; senão Python)."""
    from . import native

    si = native.sys_info()
    total, free, unified = gpu_memory(int(si.get("ram_total") or 0), int(si.get("ram_avail") or 0))
    return {"ram_total": int(si.get("ram_total") or 0), "ram_avail": int(si.get("ram_avail") or 0), "vram_total": total, "vram_free": free, "unified": unified,
            "phys": int(si.get("physical") or 1), "logical": int(si.get("logical") or 1), "features": si.get("features", [])}
