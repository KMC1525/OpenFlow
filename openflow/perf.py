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
from typing import Any, Callable, Dict, Optional, Sequence

os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")   # o torch e o CUDA numeram as placas como o nvidia-smi (senão «placa 1» podia ser outra)

MODES = ("auto", "light", "balanced", "max")
DEVICES = ("auto", "cpu", "gpu", "hybrid")   # `settings.performance.device`: onde os modelos rodam (hybrid = CPU e GPU juntas, v0.31)
MEMORY_DEFAULTS = {"multi_gpu": True, "ram_spill": True, "gpu_reserve_mb": 512, "ram_reserve_gb": 2}   # v0.59: dividir modelos entre as placas · usar a RAM para o que não couber · folgas
DEFAULTS = {"mode": "auto", "idle_unload_min": 10, "device": "auto", "gpus": [], "cpu_pin": True, "memory": MEMORY_DEFAULTS}   # gpus: índices das placas NVIDIA a usar ([] = todas)


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


# --------------------------------------------------------------------------- memória por classe de RAM (v0.45: computadores de 16 GB, DDR4/DDR5)
def ram_plan(weights: int, kv_per_token: int = 0, other_resident: int = 0) -> Dict[str, Any]:
    """Plano de memória deste computador para carregar um modelo de `weights` bytes (núcleo Rust: native.plan_ram): quanto sobra depois do sistema, se o outro modelo (texto ou mídia, `other_resident`
    bytes) precisa sair da RAM, o contexto que cabe, threads e lotes pela velocidade da memória (DDR4/DDR5 e canais) e as opções de mídia que poupam RAM. {} se não deu para planejar."""
    try:
        from . import native
        from .util import hardware_info

        mem = memory_state()
        if mem["ram_total"] <= 0:
            return {}
        lay = native.memory_layout() or {}
        ty = native.MEM_TYPE.get(str(lay.get("type") or "").upper().replace("-", ""), 0)
        mode = MODE_NUM[profile(CURRENT, hardware_info())["mode"]]
        return native.plan_ram(mem["ram_total"], mem["ram_avail"], int(weights), int(other_resident), int(kv_per_token), ty, int(lay.get("configured_speed") or lay.get("speed") or 0),
                               int(lay.get("channels") or 0), mem["phys"], mode)
    except Exception:  # noqa: BLE001 — sem plano, vale o comportamento de antes
        return {}


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


def hybrid_tuning(weights: int, ngl: int, layers: int, ctx: int, mode: str) -> Dict[str, Any]:
    """CPU + GPU juntas: threads para as camadas que ficam na CPU (a fração de camadas fora da placa). Com o modelo inteiro na placa não há o que a CPU leve: {}."""
    if ngl <= 0 or layers <= 0:
        return {}
    cpu_share = 1.0 if ngl < 0 else max(0.0, 1.0 - ngl / float(layers))
    if cpu_share <= 0.0:
        return {}
    t = cpu_tuning(int(weights * cpu_share) or int(weights), ctx, mode)
    return {"n_threads": t.get("n_threads"), "n_threads_batch": t.get("n_threads_batch")} if t else {}


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


# --------------------------------------------------------------------------- memória das placas + RAM (v0.59)
def normalize_memory(raw: Any) -> Dict[str, Any]:
    """`settings.performance.memory` válido: duas chaves ligar/desligar e as folgas (VRAM deixada livre em cada placa: 0–8192 MB; RAM deixada livre: 0–64 GB). Valor inválido volta ao padrão."""
    d = raw if isinstance(raw, dict) else {}

    def num(key: str, lo: float, hi: float) -> float:
        v = d.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
            return MEMORY_DEFAULTS[key]
        return max(lo, min(hi, float(v)))
    return {"multi_gpu": d.get("multi_gpu") is not False, "ram_spill": d.get("ram_spill") is not False,
            "gpu_reserve_mb": int(num("gpu_reserve_mb", 0, 8192)), "ram_reserve_gb": round(num("ram_reserve_gb", 0, 64), 1)}


def memory_cfg() -> Dict[str, Any]:
    return normalize_memory(CURRENT.get("memory"))


def gpu_pool() -> list:
    """As placas que o OpenFlow pode usar juntas agora: [{index, name, total, free, usable}] (bytes), a de mais memória livre primeiro. `usable` = livre menos a folga de cada placa. Com «dividir entre as placas»
    desligado, só a principal. Vazio sem NVIDIA."""
    cfg = memory_cfg()
    sel = set(selected_gpus())
    reserve = int(cfg["gpu_reserve_mb"]) * 1048576
    pool = [dict(g, usable=max(0, int(g["free"]) - reserve)) for g in gpu_status() if g["index"] in sel]
    pool.sort(key=lambda g: -g["free"])
    return pool if cfg["multi_gpu"] else pool[:1]


def pool_summary() -> Dict[str, Any]:
    """O que o planejador tem para trabalhar: as placas do `gpu_pool`, a soma de VRAM e a RAM (total, livre e usável, descontada a folga)."""
    from . import native

    pool = gpu_pool()
    si = native.sys_info()
    ram_total, ram_avail = int(si.get("ram_total") or 0), int(si.get("ram_avail") or 0)
    cfg = memory_cfg()
    return {"gpus": pool, "vram_total": sum(g["total"] for g in pool), "vram_free": sum(g["free"] for g in pool), "vram_usable": sum(g["usable"] for g in pool),
            "ram_total": ram_total, "ram_avail": ram_avail, "ram_usable": max(0, ram_avail - int(cfg["ram_reserve_gb"] * 2 ** 30)), "config": cfg}


def placement(need: int, pool: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Onde cabem `need` bytes de modelo: «gpu» (numa placa), «multi_gpu» (dividido entre as placas, em proporção à memória usável de cada uma), «gpu+ram» / «multi_gpu+ram» (o que passa da VRAM vai para a RAM,
    se «usar RAM junto» está ligado), «ram» (sem placa) ou «no_fit». É aritmética pura sobre `pool_summary()` (injetável nos testes)."""
    pool = pool if pool is not None else pool_summary()
    need = max(0, int(need))
    gpus = pool["gpus"]
    cfg = pool["config"]
    ram = int(pool["ram_usable"])
    out: Dict[str, Any] = {"need": need, "vram_usable": int(pool["vram_usable"]), "ram_usable": ram, "gpus": [], "ram_bytes": 0, "multi_gpu": False}
    if not gpus:
        out.update(strategy="ram" if need <= ram else "no_fit", ram_bytes=need if need <= ram else 0, fits=need <= ram)
        return out
    best = gpus[0]["usable"]
    if need <= best:
        out.update(strategy="gpu", fits=True, gpus=[{"index": gpus[0]["index"], "bytes": need}])
        return out
    total = sum(g["usable"] for g in gpus)
    if len(gpus) >= 2 and need <= total:
        share = [{"index": g["index"], "bytes": int(need * g["usable"] / total)} for g in gpus if g["usable"] > 0]
        out.update(strategy="multi_gpu", fits=True, gpus=share, multi_gpu=True)
        return out
    if cfg["ram_spill"]:
        vram = total if len(gpus) >= 2 else best
        spill = need - vram
        if spill <= ram:
            share = [{"index": g["index"], "bytes": int(vram * g["usable"] / (total or 1))} for g in gpus if g["usable"] > 0] if len(gpus) >= 2 else [{"index": gpus[0]["index"], "bytes": int(vram)}]
            out.update(strategy="multi_gpu+ram" if len(gpus) >= 2 else "gpu+ram", fits=True, gpus=share, ram_bytes=int(spill), multi_gpu=len(gpus) >= 2)
            return out
    out.update(strategy="no_fit", fits=False)
    return out


def assign_components(sizes: Dict[str, int], free: Sequence[int], reserve: int = 0) -> Dict[str, int]:
    """Imagem/vídeo pelo sd-cli: em qual placa fica cada parte (v0.59). `sizes`: bytes de `diffusion`, `te` (codificadores de texto) e `vae`; `free`: memória livre de cada placa, a principal primeiro.
    O modelo de difusão fica na principal (ele não se divide); o codificador de texto e o VAE vão para outra placa se, com a difusão e uma folga de ativações (15 %), não couberem na principal.
    Devolve só o que sai da principal: {«te»: 1, «vae»: 1}. {} quando tudo cabe nela (ou não há segunda placa, ou a difusão sozinha não cabe: aí vale a descarga para a RAM)."""
    if len(free) < 2:
        return {}
    avail = [max(0, int(f) - int(reserve)) for f in free]
    diff = int(sizes.get("diffusion") or 0)
    rest = {k: int(v) for k, v in sizes.items() if k != "diffusion" and v}
    if diff + sum(rest.values()) + int(0.15 * diff) <= avail[0]:
        return {}
    if diff + int(0.15 * diff) > avail[0]:
        return {}
    avail[0] -= diff + int(0.15 * diff)
    out: Dict[str, int] = {}
    for name, size in sorted(rest.items(), key=lambda kv: -kv[1]):
        if size <= avail[0]:
            avail[0] -= size
            continue
        cand = [i for i in range(1, len(avail)) if avail[i] >= size]
        if cand:
            i = max(cand, key=lambda k: avail[k])
            avail[i] -= size
            out[name] = i
    return out


def gpu_order() -> list:
    """Os índices das placas escolhidas, a de mais memória livre primeiro (a ordem em que o processo à parte as enxerga: CUDA0 é a principal)."""
    return [g["index"] for g in gpu_pool()]


def llama_split() -> Dict[str, Any]:
    """Parâmetros do llama.cpp para várias placas: `tensor_split` (a camada de cada placa em proporção à memória usável de cada uma; as não escolhidas recebem 0) e `main_gpu`. Com «dividir entre as placas»
    desligado, o modelo vai inteiro na principal. Com uma placa só (ou sem NVIDIA): {}."""
    st = gpu_status()
    if len(st) < 2:
        return {}
    pool = gpu_pool()
    if len(pool) < 2:   # uma placa escolhida entre várias (ou «dividir» desligado): o modelo inteiro nela
        first = pool[0]["index"] if pool else selected_gpus()[0]
        return {"main_gpu": first, "tensor_split": [1.0 if g["index"] == first else 0.0 for g in st]}
    usable = {g["index"]: g["usable"] for g in pool}
    tot = float(sum(usable.values())) or 1.0
    return {"main_gpu": pool[0]["index"], "tensor_split": [round(usable[g["index"]] / tot, 4) if g["index"] in usable else 0.0 for g in st]}


def gpu_env(env: Dict[str, str], multi: bool = False) -> Dict[str, str]:
    """Para processos à parte (sd-cli): `CUDA_VISIBLE_DEVICES` quando há mais de uma placa. Normal: só a escolhida com mais memória livre. Com `multi` (v0.59, componentes em placas diferentes): todas as escolhidas, a principal
    primeiro (CUDA0). Uma variável já definida pelo usuário manda."""
    if env.get("CUDA_VISIBLE_DEVICES") or device() == "cpu" or len(gpu_status()) < 2:
        return env
    if multi:
        order = gpu_order()
        if len(order) >= 2:
            return dict(env, CUDA_VISIBLE_DEVICES=",".join(str(i) for i in order))
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
    if v[0] == 0:   # AMD/Intel dedicadas (Linux, /sys/class/drm): a maior memória livre (v0.29)
        g = best_discrete_gpu()
        if g and g.get("vram_total"):
            v = (int(g["vram_total"]), int(g["vram_free"]), False)
    if v[0] == 0 and platform.system() == "Darwin" and "arm" in platform.machine().lower() and ram_total:
        v = (int(ram_total * 0.65), int(min(ram_avail, ram_total) * 0.65), True)
    _GPU_CACHE.update(t=now, v=v)
    return v


def best_discrete_gpu() -> Optional[Dict[str, Any]]:
    """A placa de vídeo dedicada para os modelos de texto: NVIDIA (a escolhida com mais memória livre) ou, sem NVIDIA, a AMD/Intel dedicada com mais memória livre. None se não há."""
    try:
        from . import native

        gpus = [g for g in native.gpu_info() if not g.get("integrated") and g.get("vram_total")]
    except Exception:  # noqa: BLE001
        return None
    nv = [g for g in gpus if g["vendor"] == "nvidia"]
    if nv:
        sel = set(selected_gpus()) or {g["index"] for g in nv}
        nv = [g for g in nv if g["index"] in sel] or nv
        return max(nv, key=lambda g: g["vram_free"])
    return max(gpus, key=lambda g: g["vram_free"]) if gpus else None


def pooled_gpu(g: Dict[str, Any]) -> Dict[str, Any]:
    """`g` (a melhor placa) como o planejador de texto deve enxergá-la: com duas ou mais placas NVIDIA escolhidas e «dividir entre as placas» ligado, uma «placa» com a soma da VRAM total e da usável; senão, a própria `g`."""
    if g.get("vendor") != "nvidia" or g.get("integrated"):
        return g
    pool = gpu_pool()
    if len(pool) < 2:
        return g
    return dict(g, vram_total=sum(x["total"] for x in pool), vram_free=sum(x["usable"] for x in pool), name=f"{len(pool)} placas ({' + '.join(str(x['index']) for x in pool)})", pooled=[x["index"] for x in pool])


def gpu_tuning(weights: int, layers: int, kv_per_token: int, ctx: int, mode: str) -> Dict[str, Any]:
    """Plano da placa de vídeo para um modelo de texto (native.plan_gpu): camadas na placa, cache de atenção na VRAM ou na RAM, atenção flash e velocidade esperada. {} sem placa dedicada
    ou se algo falhar — quem chama segue com o plano antigo."""
    try:
        from . import native

        g = best_discrete_gpu()
        integrated = False
        if g is None:   # só integrada: o planejador decide que não vale (a menos que o usuário force «GPU»)
            ig = [x for x in native.gpu_info() if x.get("integrated")]
            if not ig:
                return {}
            g, integrated = ig[0], True
        g = pooled_gpu(g) if not integrated else g   # várias placas NVIDIA escolhidas (v0.59): o llama.cpp divide as camadas entre elas, então o planejador conta a memória USÁVEL de todas juntas
        bench = native.cached_bench() or {}
        mem = memory_state()
        plan = native.plan_gpu(int(weights), int(layers), int(kv_per_token), int(ctx), int(g.get("vram_total") or 0), int(g.get("vram_free") or 0), g["vendor"], integrated, float(g.get("bw_gbs") or 0),
                               float(bench.get("bwn") or 0), int(mem.get("ram_avail") or 0), MODE_NUM.get(mode, 1))
        plan["gpu"] = {k: g.get(k) for k in ("index", "vendor", "name", "backend", "vram_total", "vram_free", "integrated", "pooled")}
        return plan
    except Exception:  # noqa: BLE001
        return {}


def memory_state() -> Dict[str, Any]:
    """RAM/VRAM livres e núcleos agora (núcleo Rust quando há; senão Python)."""
    from . import native

    si = native.sys_info()
    total, free, unified = gpu_memory(int(si.get("ram_total") or 0), int(si.get("ram_avail") or 0))
    return {"ram_total": int(si.get("ram_total") or 0), "ram_avail": int(si.get("ram_avail") or 0), "vram_total": total, "vram_free": free, "unified": unified,
            "phys": int(si.get("physical") or 1), "logical": int(si.get("logical") or 1), "features": si.get("features", [])}
