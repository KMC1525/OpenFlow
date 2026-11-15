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

os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")   # o torch e o CUDA numeram as placas como o nvidia-smi (senão «placa 1» podia ser outra)

MODES = ("auto", "light", "balanced", "max")
DEVICES = ("auto", "cpu", "gpu")   # `settings.performance.device`: onde os modelos rodam
DEFAULTS = {"mode": "auto", "idle_unload_min": 10, "device": "auto", "gpus": [], "cpu_pin": True}   # gpus: índices das placas NVIDIA a usar ([] = todas)


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


def device() -> str:
    """Onde rodar os modelos: ``auto`` (usa a placa de vídeo se houver), ``cpu`` (nunca usa a GPU) ou ``gpu`` (usa a placa de vídeo, mesmo que o OpenFlow não a detecte)."""
    v = str(CURRENT.get("device") or "auto").lower()
    return v if v in DEVICES else "auto"


# --------------------------------------------------------------------------- CPU (v0.28)
_PINNED: Dict[str, Any] = {"done": False, "cpus": []}


def cpu_tuning(weights: int, ctx: int, mode: str) -> Dict[str, Any]:
    """Como rodar um modelo de `weights` bytes só na CPU: threads de geração e de leitura do prompt, lotes, cache de atenção em 8 bits e velocidade esperada (núcleo Rust: native.plan_cpu, que usa a
    largura de banda da memória medida uma vez neste computador). {} se não deu para planejar — quem chama segue com o comportamento de antes."""
    try:
        from . import native

        info = native.cpu_info()
        bench = native.cached_bench() or {}
        mem = memory_state()
        plan = native.plan_cpu(int(weights), int(ctx), float(bench.get("bw1") or 0), float(bench.get("bwn") or 0), int(info.get("p_physical") or 1), int(info.get("e_physical") or 0),
                               int(info.get("p_logical") or 1) + int(info.get("e_logical") or 0), bool(info.get("hybrid")), int(info.get("simd") or 0), int(info.get("l2_kb") or 0),
                               int(mem.get("ram_avail") or 0), MODE_NUM.get(mode, 1))
        plan["info"], plan["bench"] = info, bench
        return plan
    except Exception:  # noqa: BLE001 — melhor esforço
        return {}


def pin_performance_cores(info: Dict[str, Any]) -> bool:
    """CPU híbrida (Intel P+E, AMD Zen c): prende o processo aos núcleos de desempenho (Linux, `sched_setaffinity`). As threads de geração que caem nos núcleos de eficiência seguram as dos de desempenho;
    com a afinidade, cada token sai mais rápido. Desligue em Configurações → Desempenho (ou OPENFLOW_CPU_PIN=0). Windows e macOS: o sistema já agenda sozinho; nada é feito."""
    if _PINNED["done"]:
        return bool(_PINNED["cpus"])
    _PINNED["done"] = True
    if os.environ.get("OPENFLOW_CPU_PIN", "") in ("0", "no", "false") or CURRENT.get("cpu_pin") is False:
        return False
    cpus = [int(c) for c in info.get("p_cpus") or []]
    if not info.get("hybrid") or not cpus or not hasattr(os, "sched_setaffinity"):
        return False
    try:
        os.sched_setaffinity(0, set(cpus))
        _PINNED["cpus"] = cpus
        return True
    except (OSError, ValueError):
        return False


def unpin_cores() -> None:
    """Desfaz a afinidade (para o usuário desligar a opção sem reiniciar o OpenFlow)."""
    if _PINNED["cpus"] and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(range(os.cpu_count() or 1)))
        except (OSError, ValueError):
            pass
    _PINNED.update(done=False, cpus=[])


# --------------------------------------------------------------------------- várias placas de vídeo (v0.26)
def gpu_status() -> list:
    """[{index, name, total, free}] (bytes) das placas NVIDIA agora, com a memória livre de cada uma (cache de 3 s). Vazio sem NVIDIA."""
    now = time.time()
    c = _GPU_STATUS
    if now - c["t"] < 3.0:
        return c["v"]
    out: list = []
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            raw = subprocess.run([smi, "--query-gpu=index,name,memory.total,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
            for line in raw:
                p = [x.strip() for x in line.split(",")]
                if len(p) >= 4 and p[0].isdigit():
                    out.append({"index": int(p[0]), "name": ", ".join(p[1:-2]), "total": int(float(p[-2])) * 1048576, "free": int(float(p[-1])) * 1048576})
        except (OSError, subprocess.SubprocessError, ValueError):
            out = []
    c.update(t=now, v=out)
    return out


_GPU_STATUS: Dict[str, Any] = {"t": 0.0, "v": []}


def selected_gpus() -> list:
    """Os índices das placas NVIDIA que o OpenFlow pode usar: as escolhidas em Configurações → Desempenho → GPUs (as que existem) ou todas, se nada foi escolhido."""
    present = [g["index"] for g in gpu_status()]
    raw = CURRENT.get("gpus")
    want = []
    for x in raw if isinstance(raw, list) else []:
        try:
            want.append(int(x))
        except (TypeError, ValueError):
            pass
    chosen = [i for i in present if i in want]
    return chosen or present


def primary_gpu() -> Optional[int]:
    """A placa para modelos que usam uma só (imagem, vídeo, som, sd-cli): a escolhida com mais memória livre agora. None sem NVIDIA."""
    sel = set(selected_gpus())
    st = [g for g in gpu_status() if g["index"] in sel]
    return max(st, key=lambda g: g["free"])["index"] if st else None


def llama_split() -> Dict[str, Any]:
    """Parâmetros do llama.cpp para várias placas: `tensor_split` (a camada de cada placa em proporção à memória livre; as não escolhidas recebem 0) e `main_gpu`. Com uma placa só (ou sem NVIDIA): {}."""
    st = gpu_status()
    sel = selected_gpus()
    if len(st) < 2:
        return {}
    free = {g["index"]: g["free"] for g in st}
    if len(sel) < 2:   # uma placa escolhida entre várias: o modelo inteiro nela
        return {"main_gpu": sel[0], "tensor_split": [1.0 if g["index"] == sel[0] else 0.0 for g in st]}
    tot = float(sum(free[i] for i in sel)) or 1.0
    return {"main_gpu": primary_gpu() or sel[0], "tensor_split": [round(free[g["index"]] / tot, 4) if g["index"] in sel else 0.0 for g in st]}


def gpu_env(env: Dict[str, str]) -> Dict[str, str]:
    """Para processos à parte (sd-cli): `CUDA_VISIBLE_DEVICES` com a placa certa — a de mais memória livre entre as escolhidas — quando há mais de uma placa. Uma variável já definida pelo usuário manda."""
    if env.get("CUDA_VISIBLE_DEVICES") or device() == "cpu" or len(gpu_status()) < 2:
        return env
    i = primary_gpu()
    if i is not None:
        env = dict(env, CUDA_VISIBLE_DEVICES=str(i))
    return env


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
