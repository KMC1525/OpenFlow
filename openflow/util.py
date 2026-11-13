"""Utilitários sem dependências: ids, JSON atômico, hardware, coerção numérica."""
from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def flow_home() -> Path:
    """Pasta de dados do usuário (OPENFLOW_HOME ou ~/.openflow)."""
    custom = os.environ.get("OPENFLOW_HOME")
    base = Path(custom).expanduser() if custom else Path.home() / ".openflow"
    base.mkdir(parents=True, exist_ok=True)
    return base


def new_id(prefix: str = "") -> str:
    return prefix + secrets.token_hex(5)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str, default: str = "item", max_len: int = 48) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].strip("-")) or default


def safe_filename(name: str, default: str = "file") -> str:
    """Nome de arquivo seguro (sem diretórios, sem caracteres de controle)."""
    name = os.path.basename(str(name or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f<>:\"|?*]", "_", name).strip(". ")
    return name[:120] or default


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json(path: Path, data: Any, private: bool = False) -> None:
    """Escrita atômica: grava em arquivo temporário e troca."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        if private:
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def num(value: Any, default: float, lo: Optional[float] = None, hi: Optional[float] = None) -> float:
    """Converte para número com limites; valores inválidos viram `default`."""
    try:
        out = float(value)
        if out != out or out in (float("inf"), float("-inf")):
            raise ValueError
    except (TypeError, ValueError):
        out = float(default)
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def text(value: Any, default: str = "", max_len: int = 4000) -> str:
    if value is None:
        return default
    s = str(value).strip()
    return s[:max_len] if s else default


def deep_merge(base: dict, patch: dict) -> dict:
    """Mescla `patch` em `base` recursivamente (retorna novo dict)."""
    out = dict(base)
    for key, val in (patch or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


# --------------------------------------------------------------------------- hardware


def _ram_gb() -> Optional[float]:
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal"):
                        return int(line.split()[1]) / 1024 / 1024
        elif sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3)
            return int(out.stdout.strip()) / 1024 ** 3
        elif os.name == "nt":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MemStatus()
            stat.dwLength = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
            return stat.ullTotalPhys / 1024 ** 3
    except Exception:
        return None
    return None


def _gpu_name() -> Optional[str]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=3,
        )
        line = out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else ""
        return line or None
    except Exception:
        return None


_HW_CACHE: Optional[dict] = None


def _run_out(cmd: list, timeout: float = 6.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:  # noqa: BLE001 — ferramenta ausente/sem permissão: só não mostra o item
        return ""


def _read_first(path: str) -> str:
    try:
        return Path(path).read_text(errors="ignore").strip()
    except Exception:  # noqa: BLE001
        return ""


def hardware_components() -> list:
    """Lista [{type, name}] com o tipo e o nome de cada componente do PC (melhor esforço; o que não for detectado some)."""
    out: list = []

    def add(kind: str, name: str) -> None:
        name = " ".join((name or "").split())
        if name and name.lower() not in ("none", "unknown", "to be filled by o.e.m.", "default string") and {"type": kind, "name": name} not in out:
            out.append({"type": kind, "name": name})

    sysname = platform.system()
    if sysname == "Linux":
        cpu = next((l.split(":", 1)[1] for l in _read_first("/proc/cpuinfo").splitlines() if l.lower().startswith("model name")), "")
        add("CPU", cpu)
        add("Placa-mãe", " ".join(x for x in (_read_first("/sys/class/dmi/id/board_vendor"), _read_first("/sys/class/dmi/id/board_name")) if x))
        add("Computador", " ".join(x for x in (_read_first("/sys/class/dmi/id/sys_vendor"), _read_first("/sys/class/dmi/id/product_name")) if x))
        add("BIOS", " ".join(x for x in (_read_first("/sys/class/dmi/id/bios_vendor"), _read_first("/sys/class/dmi/id/bios_version")) if x))
        if shutil.which("lspci"):
            for line in _run_out(["lspci"]).splitlines():
                if any(k in line for k in ("VGA compatible", "3D controller", "Display controller")):
                    add("GPU", line.split(": ", 1)[-1])
                elif "Audio device" in line or "Multimedia audio" in line:
                    add("Áudio", line.split(": ", 1)[-1])
                elif "Ethernet controller" in line or "Network controller" in line:
                    add("Rede", line.split(": ", 1)[-1])
        if shutil.which("lsblk"):
            import shlex
            for line in _run_out(["lsblk", "-dP", "-o", "NAME,MODEL,SIZE,TYPE"]).splitlines():
                try:
                    f = dict(x.split("=", 1) for x in shlex.split(line))
                except ValueError:
                    continue
                if f.get("TYPE") == "disk" and f.get("MODEL", "").strip() and not f.get("NAME", "").startswith(("loop", "zram", "ram")):
                    add("Disco", f"{f['MODEL'].strip()} ({f.get('SIZE', '')})")
    elif sysname == "Darwin":
        add("CPU", _run_out(["sysctl", "-n", "machdep.cpu.brand_string"]))
        add("Computador", _run_out(["sysctl", "-n", "hw.model"]))
        for line in _run_out(["system_profiler", "SPDisplaysDataType"], 15).splitlines():
            if line.strip().startswith("Chipset Model:"):
                add("GPU", line.split(":", 1)[1])
    elif sysname == "Windows":
        def ps(q: str) -> list:
            return [x.strip() for x in _run_out(["powershell", "-NoProfile", "-Command", q], 15).splitlines() if x.strip()]
        for x in ps("(Get-CimInstance Win32_Processor).Name"):
            add("CPU", x)
        for x in ps("(Get-CimInstance Win32_VideoController).Name"):
            add("GPU", x)
        for x in ps("$b=Get-CimInstance Win32_BaseBoard; $b.Manufacturer+' '+$b.Product"):
            add("Placa-mãe", x)
        for x in ps("(Get-CimInstance Win32_DiskDrive).Model"):
            add("Disco", x)
        for x in ps("(Get-CimInstance Win32_PhysicalMemory | ForEach-Object { $_.Manufacturer+' '+$_.PartNumber+' '+[math]::Round($_.Capacity/1GB)+' GB '+$_.Speed+' MHz' })"):
            add("Memória (pente)", x)
        for x in ps("(Get-CimInstance Win32_SoundDevice).Name"):
            add("Áudio", x)
    gpu = _gpu_name()
    if gpu:
        for g in gpu.split(";"):
            add("GPU (NVIDIA)", g.strip())
    ram = _ram_gb()
    if ram is not None:
        add("Memória RAM", f"{round(ram, 1)} GB")
    add("Sistema operacional", " ".join(x for x in (platform.system(), platform.release(), platform.machine()) if x))
    return out


def hardware_info(refresh: bool = False) -> dict:
    """Detecta CPU/RAM (e GPU NVIDIA, se houver) e classifica em low/medium/high."""
    global _HW_CACHE
    if _HW_CACHE is not None and not refresh:
        return _HW_CACHE
    cpus = os.cpu_count() or 2
    ram = _ram_gb()
    eff_ram = ram if ram is not None else 8.0
    if eff_ram < 6 or cpus <= 2:
        tier = "low"
    elif eff_ram >= 16 and cpus >= 8:
        tier = "high"
    else:
        tier = "medium"
    _HW_CACHE = {
        "os": platform.system() or sys.platform,
        "arch": platform.machine(),
        "python": platform.python_version(),
        "cpus": cpus,
        "ram_gb": round(ram, 1) if ram is not None else None,
        "gpu": _gpu_name(),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "tier": tier,
        "components": hardware_components(),
    }
    return _HW_CACHE


# --------------------------------------------------------------------------- certificados HTTPS (macOS com o Python do python.org)
_CERTS_DONE = False


def ssl_context():
    """Contexto TLS para as conexões HTTPS do OpenFlow. O Python instalado pelo python.org no macOS vem SEM certificados raiz (até alguém rodar o «Install Certificates.command»):
    toda chamada HTTPS falha com CERTIFICATE_VERIFY_FAILED — o OpenFlow não conseguia falar com provedores de IA, buscar atualizações nem baixar modelos. Aqui, se o contexto padrão
    não tem nenhuma autoridade raiz, carregamos as do `certifi` (se instalado) ou as do Chaveiro do macOS. Nunca desliga a verificação."""
    import ssl

    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) > 0 or os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return ctx
    try:
        import certifi  # type: ignore

        ctx.load_verify_locations(cafile=certifi.where())
        return ctx
    except Exception:  # noqa: BLE001  (certifi ausente ou quebrado)
        pass
    if sys.platform == "darwin":
        try:
            import subprocess

            pem = subprocess.run(["/usr/bin/security", "find-certificate", "-a", "-p", "/System/Library/Keychains/SystemRootCertificates.keychain", "/Library/Keychains/System.keychain"],
                                 capture_output=True, text=True, timeout=30).stdout
            if "BEGIN CERTIFICATE" in pem:
                ctx.load_verify_locations(cadata=pem)
        except Exception:  # noqa: BLE001
            pass
    return ctx


def fix_default_certs() -> bool:
    """Faz TODA chamada HTTPS do Python (urllib sem contexto próprio) usar `ssl_context()`. Só mexe se o contexto padrão não tem certificados; devolve True se corrigiu."""
    global _CERTS_DONE
    import ssl

    if _CERTS_DONE:
        return False
    _CERTS_DONE = True
    try:
        if ssl.create_default_context().cert_store_stats().get("x509_ca", 0) > 0:
            return False
    except Exception:  # noqa: BLE001
        return False
    fixed = ssl_context()
    if fixed.cert_store_stats().get("x509_ca", 0) <= 0:
        return False
    ssl._create_default_https_context = lambda *a, **k: ssl_context()   # type: ignore[assignment,misc]
    return True


_NUL, _LONE_SURROGATE = re.compile("\x00"), re.compile("[\ud800-\udfff]")


def clean_json(v: Any, depth: int = 0) -> Any:
    """Texto vindo do JSON sem bytes nulos e sem «surrogates» soltos (o JSON permite «\\ud800», mas nem o sistema de arquivos nem o UTF-8 aceitam: davam erro 500 ao salvar)."""
    if isinstance(v, str):
        return _LONE_SURROGATE.sub("\ufffd", _NUL.sub("", v)) if ("\x00" in v or _LONE_SURROGATE.search(v)) else v
    if depth > 100:
        raise ValueError("JSON aninhado fundo demais")   # nenhuma tela manda isso; copiar/salvar uma estrutura dessas estouraria a pilha (erro 500)
    if isinstance(v, dict):
        return {(clean_json(k, depth + 1) if isinstance(k, str) else k): clean_json(x, depth + 1) for k, x in v.items()}
    if isinstance(v, list):
        return [clean_json(x, depth + 1) for x in v]
    return v


# --------------------------------------------------------------------------- texto de modelos e rede local
_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.S | re.I)


def strip_reasoning(raw: str) -> str:
    """Tira o "raciocínio" de modelos que o escrevem junto da resposta (<think>…</think>: Qwen3, DeepSeek R1…, comuns no LM Studio e no Ollama).
    Um <think> ainda aberto (durante o streaming) esconde o resto; um </think> sem abertura (o modelo já começou pensando) descarta o que veio antes."""
    s = _THINK_RE.sub("", raw or "")
    i = s.lower().find("<think")
    if i >= 0:
        s = s[:i]
    j = s.lower().rfind("</think")
    if j >= 0:
        s = s[s.find(">", j) + 1:]
    return s


_LAN_CACHE: dict = {"t": 0.0, "ips": []}


def lan_ips() -> list:
    """Endereços IPv4 do computador na rede local (o primeiro é o da saída padrão), sem loopback. O resultado vale por 30 s."""
    import socket
    import time

    if time.time() - float(_LAN_CACHE["t"]) < 30 and _LAN_CACHE["ips"]:
        return list(_LAN_CACHE["ips"])
    found: list = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("10.255.255.255", 1))   # UDP: não envia nada, só descobre qual interface seria usada
        found.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        found.extend(i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    out: list = []
    for ip in found:
        if ip and not ip.startswith(("127.", "0.", "169.254.")) and ip not in out:
            out.append(ip)
    _LAN_CACHE.update(t=time.time(), ips=list(out))
    return out
