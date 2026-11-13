"""Núcleo nativo (Rust) do OpenFlow — opcional, com equivalente em Python puro para tudo.

A biblioteca `libopenflow_core` (código em `openflow/native/src/lib.rs`, só biblioteca padrão do Rust) acelera a síntese de áudio do Canvas Demo (música, efeitos, voz) e
a conversão para PCM, trabalhando em buffers compartilhados (`array('d')`) em vez de um objeto Python por amostra: bem mais rápido e com uma fração da RAM.
Ela é carregada com `ctypes` (nada para instalar no Python). Para compilar:  `flow native build`  (precisa do Rust — https://rustup.rs).
Sem a biblioteca (ou com `OPENFLOW_NO_NATIVE=1`), o OpenFlow usa as versões em Python, que dão o mesmo resultado (exceto o ruído, que usa outro gerador de números aleatórios).

v0.14 — o núcleo Rust é parte **obrigatória** da instalação: os instaladores (Windows, macOS, Linux/AppImage, Android) já trazem a biblioteca pronta, e quem instala pelo terminal recebe a
biblioteca **pré-compilada** da Release (baixada e conferida por SHA-256; nada de compilador) — só se isso falhar o OpenFlow compila na máquina (`flow native setup`). O Python continua sendo
o orquestrador e o espelho de tudo: se por qualquer motivo a biblioteca não carregar, o OpenFlow segue funcionando, só mais devagar.
"""
from __future__ import annotations

import ctypes
import math
import os
import random
import shutil
import subprocess
import sys
import threading
from array import array
from pathlib import Path
from typing import Any, Dict, Optional

ABI = 4   # versão da interface desta versão do OpenFlow; bibliotecas antigas (1, 2 e 3) ainda servem: a 1 só para o áudio, a 2 também para modelos locais, a 3 para agentes/armazenamento — sem os recursos novos (análise de mídia e grafos, v0.17)
SRC = Path(__file__).resolve().parent
_LIB: Any = None
_TRIED = False
_REASON = ""
_LOCK = threading.Lock()
WAVES = {"sine": 0, "square": 1, "saw": 2, "triangle": 3}


def _libname() -> str:
    return "openflow_core.dll" if os.name == "nt" else ("libopenflow_core.dylib" if sys.platform == "darwin" else "libopenflow_core.so")


RELEASES = "https://github.com/KMC1525/OpenFlow/releases/download"


def _marker() -> Path:
    return native_dir() / "VERSION"


def installed_for() -> str:
    """A versão do OpenFlow para a qual a biblioteca instalada foi baixada/compilada (vazio se não sabemos)."""
    try:
        return _marker().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _mark(version: str = "") -> None:
    from .. import __version__

    try:
        _marker().write_text(version or __version__, encoding="utf-8")
    except OSError:
        pass


def platform_tag() -> str:
    """«linux-x86_64», «linux-aarch64», «macos-aarch64», «macos-x86_64», «windows-x86_64»… (o nome da biblioteca pré-compilada na Release)."""
    import platform

    osname = {"darwin": "macos"}.get(platform.system().lower(), platform.system().lower())
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(platform.machine().lower(), platform.machine().lower())
    return f"{osname}-{arch}"


def prebuilt_name() -> str:
    return f"flow-core-{platform_tag()}{Path(_libname()).suffix}"


def native_dir() -> Path:
    return Path(os.environ.get("OPENFLOW_HOME") or Path.home() / ".openflow") / "native"


def _candidates():
    if os.environ.get("OPENFLOW_NATIVE_LIB"):
        yield Path(os.environ["OPENFLOW_NATIVE_LIB"])
    yield native_dir() / _libname()
    yield SRC / _libname()


def _bind(lib: Any) -> None:
    dp, cp = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int16)
    lib.flow_abi_version.restype = ctypes.c_uint32
    lib.flow_tone.argtypes = [dp, ctypes.c_size_t, ctypes.c_double, ctypes.c_uint32, ctypes.c_double, ctypes.c_double, ctypes.c_uint32, ctypes.c_double, ctypes.c_size_t, ctypes.c_size_t]
    lib.flow_noise.argtypes = [dp, ctypes.c_size_t, ctypes.c_uint64, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double]
    lib.flow_mix_add.argtypes = [dp, ctypes.c_size_t, dp, ctypes.c_size_t, ctypes.c_size_t]
    lib.flow_fade_out.argtypes = [dp, ctypes.c_size_t, ctypes.c_size_t]
    lib.flow_pcm16.argtypes = [dp, ctypes.c_size_t, cp, ctypes.c_double]
    lib.flow_mul.argtypes = [dp, dp, ctypes.c_size_t, dp]
    if lib.flow_abi_version() >= 2:  # v0.12: modelos locais (cabeçalhos, hardware, planejador, pré-carga)
        u8p, sz, u64, u32, i64 = ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_int64
        lib.flow_sys_info.argtypes = [ctypes.c_void_p, sz]
        lib.flow_sys_info.restype = i64
        lib.flow_model_info.argtypes = [u8p, sz, ctypes.c_void_p, sz]
        lib.flow_model_info.restype = i64
        lib.flow_prefetch.argtypes = [u8p, sz, u32]
        lib.flow_prefetch.restype = i64
        lib.flow_plan_llm.argtypes = [u64, i64, i64, i64, i64, u32, i64, u64, u64, u32, u32, u32, u32, ctypes.c_void_p, sz]
        lib.flow_plan_llm.restype = i64
        lib.flow_plan_media.argtypes = [u64, u64, u64, u32, u32, ctypes.c_void_p, sz]
        lib.flow_plan_media.restype = i64
    if lib.flow_abi_version() >= 3:  # v0.14: vários agentes locais, armazenamento (varredura e duplicados) e memória
        u8p, sz, u64, u32, i64 = ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_int64
        lib.flow_plan_agents.argtypes = [u32, u32, u64, u64, u64, u64, u32, u32, u32, u32, ctypes.c_void_p, sz]
        lib.flow_plan_agents.restype = i64
        lib.flow_scan_dir.argtypes = [u8p, sz, u64, u32, ctypes.c_void_p, sz]
        lib.flow_scan_dir.restype = i64
        lib.flow_dup_groups.argtypes = [u8p, sz, u64, u8p, sz, u64, ctypes.c_void_p, sz]
        lib.flow_dup_groups.restype = i64
        lib.flow_release_memory.argtypes = []
        lib.flow_release_memory.restype = i64
        lib.flow_evict_file.argtypes = [u8p, sz]
        lib.flow_evict_file.restype = i64
    if lib.flow_abi_version() >= 4:  # v0.17: análise de mídia (áudio, andamento, quadros) e ordem de grafos
        sz, i64, vp, f64, u32p = ctypes.c_size_t, ctypes.c_int64, ctypes.c_void_p, ctypes.c_double, ctypes.POINTER(ctypes.c_uint32)
        lib.flow_audio_levels.argtypes = [vp, sz, sz, vp, sz]
        lib.flow_silence_ranges.argtypes = [vp, sz, f64, f64, f64, vp, sz]
        lib.flow_pick_peaks.argtypes = [vp, sz, f64, f64, sz, vp]
        lib.flow_onset_env.argtypes = [vp, sz, vp]
        lib.flow_tempo.argtypes = [vp, sz, f64, f64, f64, vp]
        lib.flow_frame_activity.argtypes = [vp, sz, sz, vp]
        lib.flow_scene_cuts.argtypes = [vp, sz, f64, f64, f64, f64, vp, sz]
        lib.flow_waveform.argtypes = [vp, sz, sz, vp]
        lib.flow_topo.argtypes = [sz, vp, vp, sz, vp, vp]
        for fn in ("audio_levels", "silence_ranges", "pick_peaks", "onset_env", "tempo", "frame_activity", "scene_cuts", "waveform", "topo"):
            getattr(lib, "flow_" + fn).restype = i64


def load(force: bool = False) -> Any:
    """A biblioteca carregada, ou None (e `status()['reason']` diz por quê)."""
    global _LIB, _TRIED, _REASON
    with _LOCK:
        if _TRIED and not force:
            return _LIB
        _TRIED, _LIB = True, None
        if os.environ.get("OPENFLOW_NO_NATIVE", "") not in ("", "0"):
            _REASON = "desligado por OPENFLOW_NO_NATIVE"
            return None
        for path in _candidates():
            if not path.is_file():
                continue
            try:
                lib = ctypes.CDLL(str(path))
                if lib.flow_abi_version() not in (1, 2, 3, ABI):
                    _REASON = f"{path.name}: versão da interface diferente (recompile com `flow native setup`)"
                    continue
                _bind(lib)
                _LIB, _REASON = lib, str(path)
                return lib
            except (OSError, AttributeError) as exc:
                _REASON = f"{path.name}: {exc}"
        _REASON = _REASON or "biblioteca não compilada (opcional: `flow native setup` instala o Rust e compila)"
        return None


def available() -> bool:
    return load() is not None


def find_tool(name: str) -> Optional[str]:
    """O caminho de `cargo`/`rustup`: no PATH, ou na pasta do rustup (~/.cargo/bin; CARGO_HOME) — o rustup recém-instalado ainda não está no PATH desta sessão."""
    exe = shutil.which(name)
    if exe:
        return exe
    home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")
    for cand in (home / "bin" / name, home / "bin" / (name + ".exe")):
        if cand.is_file():
            return str(cand)
    return None


def status() -> Dict[str, Any]:
    lib = load()
    return {"active": lib is not None, "reason": _REASON, "cargo": bool(find_tool("cargo")), "rustup": bool(find_tool("rustup")), "path": _REASON if lib is not None else "",
            "models": lib is not None and hasattr(lib, "flow_plan_llm"), "ops": lib is not None and hasattr(lib, "flow_plan_agents"), "media": lib is not None and hasattr(lib, "flow_audio_levels"),
            "abi": int(lib.flow_abi_version()) if lib is not None else 0, "last": dict(LAST)}


def rust_version() -> str:
    cargo = find_tool("cargo")
    if not cargo:
        return ""
    try:
        return subprocess.run([cargo, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def install_rust() -> int:
    """Instala o Rust (rustup, perfil mínimo, toolchain estável) na pasta do usuário — sem sudo. Devolve 0 se o `cargo` ficou disponível."""
    import tempfile
    import urllib.request

    from ..termi18n import _

    if find_tool("cargo"):
        return 0
    print(_("Instalando o Rust (rustup, perfil mínimo) na sua pasta de usuário …"))
    try:
        if os.name == "nt":
            import platform

            arch = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else ("i686" if platform.architecture()[0] == "32bit" else "x86_64")
            with urllib.request.urlopen(f"https://win.rustup.rs/{arch}", timeout=60) as r:
                data = r.read()
            with tempfile.NamedTemporaryFile("wb", suffix=".exe", delete=False) as fh:
                fh.write(data)
                exe = fh.name
            cmd = [exe, "-y", "--profile", "minimal", "--default-toolchain", "stable"]
        else:
            with urllib.request.urlopen("https://sh.rustup.rs", timeout=60) as r:
                data = r.read()
            with tempfile.NamedTemporaryFile("wb", suffix=".sh", delete=False) as fh:
                fh.write(data)
                exe = fh.name
            cmd = ["sh", exe, "-y", "--profile", "minimal", "--default-toolchain", "stable"]
        res = subprocess.run(cmd)
    except Exception as exc:  # noqa: BLE001  (sem internet, antivírus, sem permissão…)
        print(_("Não consegui baixar/instalar o Rust agora ({e}). Instale pelo https://rustup.rs e rode:  flow native setup", e=str(exc)[:160]))
        return 1
    finally:
        try:
            os.unlink(exe)
        except Exception:  # noqa: BLE001
            pass
    if res.returncode != 0 or not find_tool("cargo"):
        print(_("A instalação do Rust não terminou. Instale pelo https://rustup.rs e rode:  flow native setup"))
        return 1
    print(_("Rust instalado: {v}", v=rust_version()))
    return 0


def update_rust() -> int:
    """Atualiza o Rust (toolchain estável) com o rustup. Rust instalado por outro meio (gerenciador de pacotes) é atualizado por ele."""
    from ..termi18n import _

    rustup = find_tool("rustup")
    if not rustup:
        print(_("O Rust deste computador não foi instalado pelo rustup: atualize-o pelo mesmo meio em que o instalou (ex.: gerenciador de pacotes). Sigo com a versão atual: {v}", v=rust_version() or "?"))
        return 0
    print(_("Atualizando o Rust (rustup update stable) …"))
    res = subprocess.run([rustup, "update", "stable", "--no-self-update"] if os.name != "nt" else [rustup, "update", "stable"])
    if res.returncode != 0:
        print(_("Não consegui atualizar o Rust agora (sem internet?); sigo com a versão atual."))
    return 0


def build(verbose: bool = True) -> int:
    """Compila o núcleo com o `cargo` e instala em ~/.openflow/native. Devolve o código de saída (0 = ok)."""
    from ..termi18n import _

    cargo = find_tool("cargo")
    if not cargo:
        print(_("O Rust (cargo) não está instalado. É opcional: o OpenFlow funciona igual em Python, só mais devagar na síntese de áudio.\nInstale com:  flow native install   (ou pelo https://rustup.rs)"))
        return 1
    if not (SRC / "Cargo.toml").is_file():
        print(_("Código-fonte do núcleo não encontrado nesta instalação."))
        return 1
    dest = native_dir()
    dest.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, CARGO_TARGET_DIR=str(dest / "target"))
    res = subprocess.run([cargo, "build", "--release", "--manifest-path", str(SRC / "Cargo.toml")], env=env, capture_output=not verbose, text=True)
    if res.returncode != 0:
        if not verbose:
            print((res.stderr or "")[-800:])
        print(_("Não foi possível compilar o núcleo (o OpenFlow segue em Python)."))
        return res.returncode
    built = dest / "target" / "release" / _libname()
    if not built.is_file():
        print(_("Compilou, mas não achei a biblioteca gerada."))
        return 1
    shutil.copyfile(built, dest / _libname())
    _mark()
    shutil.rmtree(dest / "target", ignore_errors=True)  # só a biblioteca fica (a pasta de compilação ocupa centenas de MB)
    load(force=True)
    print(_("Núcleo em Rust ativo:"), status()["path"] if available() else status()["reason"])
    return 0 if available() else 1


def fetch_prebuilt(version: str = "", verbose: bool = True) -> int:
    """Baixa a biblioteca pré-compilada desta plataforma na Release do OpenFlow, confere o SHA-256 (SHA256SUMS.txt da mesma Release) e só instala se ela carrega e tem a interface certa.
    Devolve 0 se o núcleo ficou ativo. Não precisa de Rust nem de compilador. `OPENFLOW_NATIVE_URL` troca a pasta de onde baixa (espelhos, testes)."""
    import hashlib
    import urllib.request

    from .. import __version__
    from ..termi18n import _
    from ..util import ssl_context

    base = (os.environ.get("OPENFLOW_NATIVE_URL") or f"{RELEASES}/v{version or __version__}").rstrip("/")
    name = prebuilt_name()

    def say(msg: str) -> None:
        if verbose:
            print(msg)

    try:
        ctx = ssl_context()
        with urllib.request.urlopen(urllib.request.Request(f"{base}/SHA256SUMS.txt", headers={"User-Agent": "OpenFlow"}), timeout=25, context=ctx) as r:
            sums = r.read(1 << 20).decode("utf-8", "replace")
        want = next((ln.split()[0].lower() for ln in sums.splitlines() if ln.split()[-1:] and ln.split()[-1].lstrip("*") == name), "")
        if not want:
            say(_("Não há núcleo pré-compilado para {p} nesta versão.", p=platform_tag()))
            return 1
        with urllib.request.urlopen(urllib.request.Request(f"{base}/{name}", headers={"User-Agent": "OpenFlow"}), timeout=120, context=ctx) as r:
            data = r.read(64 * 1024 * 1024 + 1)
    except Exception as exc:  # noqa: BLE001  (sem internet, release ainda sem a biblioteca…)
        say(_("Não consegui baixar o núcleo pré-compilado ({e}).", e=str(exc)[:120]))
        return 1
    if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != want:
        say(_("O núcleo baixado não confere com o SHA-256 publicado — descartado."))
        return 1
    dest = native_dir()
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / (_libname() + ".new")
    tmp.write_bytes(data)
    try:
        lib = ctypes.CDLL(str(tmp))
        if lib.flow_abi_version() != ABI:
            raise OSError(f"interface {lib.flow_abi_version()} ≠ {ABI}")
        del lib
        os.replace(tmp, dest / _libname())
    except (OSError, AttributeError) as exc:
        say(_("O núcleo baixado não carrega aqui ({e}).", e=str(exc)[:120]))
        try:
            tmp.unlink()
        except OSError:
            pass
        return 1
    _mark(version)
    load(force=True)
    say(_("Núcleo em Rust ativo (pré-compilado):") + " " + (status()["path"] if available() else status()["reason"]))
    return 0 if available() else 1


_ENSURE_LOCK = threading.Lock()


def ensure(wait: bool = False) -> bool:
    """Garante o núcleo Rust: se não está ativo (ou é de uma interface antiga), baixa a biblioteca pré-compilada em segundo plano — no máximo uma vez a cada 24 h.
    Sem internet, sem permissão ou com OPENFLOW_NO_NATIVE, o OpenFlow segue em Python. Devolve True se já estava ativo."""
    if os.environ.get("OPENFLOW_NO_NATIVE", "") not in ("", "0") or os.environ.get("OPENFLOW_NO_NATIVE_FETCH", "") not in ("", "0"):
        return available()
    if available() and status()["abi"] >= ABI:
        return True
    stamp = native_dir() / ".fetch-stamp"
    try:
        import time

        if stamp.is_file() and time.time() - stamp.stat().st_mtime < 24 * 3600:
            return False
        native_dir().mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(time.time()))
    except OSError:
        return False

    def work() -> None:
        with _ENSURE_LOCK:
            try:
                fetch_prebuilt(verbose=False)
            except Exception:  # noqa: BLE001
                pass

    if wait:
        work()
        return available()
    threading.Thread(target=work, name="flow-native-fetch", daemon=True).start()
    return False


def _toolchain_ok() -> bool:
    """O computador tem o que o Rust precisa para ligar o binário (compilador/linker)? macOS: as ferramentas de linha de comando da Apple; Linux: gcc/cc/clang; Windows: não dá
    para saber barato (segue e deixa o rustup dizer)."""
    if sys.platform == "darwin":
        try:
            return subprocess.run(["xcode-select", "-p"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    if os.name == "nt":
        return True
    return any(shutil.which(c) for c in ("cc", "gcc", "clang"))


def _build_hint() -> str:
    from ..termi18n import _

    if os.name == "nt":
        return _("No Windows o Rust precisa das «Ferramentas de Build do Visual Studio» (carga «Desenvolvimento para desktop com C++»): https://visualstudio.microsoft.com/visual-cpp-build-tools/ — depois rode:  flow native setup")
    if sys.platform == "darwin":
        return _("No macOS o Rust precisa das ferramentas de linha de comando da Apple. Instale com:  xcode-select --install   — depois rode:  flow native setup")
    return _("No Linux o Rust precisa de um compilador C (gcc/cc). Ex.: sudo apt install build-essential   (ou o equivalente da sua distribuição) — depois rode:  flow native setup")


def setup(mode: str = "yes", ask: Any = None) -> int:
    """Instala/atualiza o Rust e recompila o núcleo do OpenFlow. `mode`: "yes" (padrão: instala/atualiza e recompila sozinho), "no" (não mexe) ou "ask" (pergunta no terminal). Devolve 0 em geral (o núcleo é opcional: o OpenFlow funciona igual em Python)."""
    from ..termi18n import _

    mode = (mode or "yes").strip().lower()
    if mode in ("no", "none", "0", "skip", "nao", "não", "n"):
        print(_("Rust: pulado (OPENFLOW_RUST=no)."))
        return 0
    mode = "ask" if mode == "ask" else "yes"   # padrão: automático (como as bibliotecas e os modelos); "ask" só se pedido
    from .. import __version__

    if not os.environ.get("OPENFLOW_NATIVE_BUILD") and available() and status()["abi"] >= ABI and installed_for() in (__version__, ""):   # já é desta versão do OpenFlow (ou veio num instalador/AppImage)
        print(_("Núcleo Rust: já ativo ({p}).", p=status()["path"]))
        return 0
    if not os.environ.get("OPENFLOW_NATIVE_BUILD") and fetch_prebuilt() == 0:   # o caminho normal: biblioteca pronta da Release, sem compilador
        return 0
    if not _toolchain_ok():
        print(_("Sem a biblioteca pré-compilada e sem compilador neste computador, o OpenFlow segue em Python (mais lento). ") + _build_hint())
        return 0
    have = bool(find_tool("cargo"))
    if mode == "ask":
        answer = ask(_("Atualizar o Rust e recompilar o núcleo do OpenFlow (mais rápido e leve)?") if have else
                     _("Instalar o Rust (perto de 300 MB, na sua pasta de usuário) para deixar o OpenFlow mais rápido e leve?"), default=have) if ask else None
        if answer is None:
            if not have:
                print(_("Rust: não há um terminal para perguntar, então não instalei nada. Para instalar: flow native setup --rust yes   (ou OPENFLOW_RUST=yes no instalador)."))
                return 0
        elif not answer:
            print(_("Ok, sem Rust por agora. Quando quiser:  flow native setup"))
            return 0
    if not have and install_rust() != 0:
        return 0
    update_rust()
    if build() != 0:
        print(_build_hint())
    return 0


# --------------------------------------------------------------------------- funções (nativas, com equivalente em Python)


def _ptr(a: "array[float]"):
    addr, _ = a.buffer_info()
    return ctypes.cast(addr, ctypes.POINTER(ctypes.c_double))


def zeros(n: int) -> "array[float]":
    return array("d", bytes(8 * max(0, n)))


def tone(freq: float, dur: float, wave: str = "sine", vol: float = 0.5, sweep: Optional[float] = None, sr: int = 44100) -> "array[float]":
    n = int(dur * sr)
    na, nr = max(1, int(0.005 * sr)), max(1, int(min(0.25, dur / 2) * sr))
    out = zeros(n)
    if n <= 0:
        return out
    lib = load()
    if lib is not None:
        lib.flow_tone(_ptr(out), n, freq, WAVES.get(wave, 0), vol, sweep or 0.0, 0 if sweep is None else 1, float(sr), na, nr)
        return out
    ph, tw = 0.0, 2 * math.pi
    for i in range(n):
        f = freq if sweep is None else freq + (sweep - freq) * i / max(1, n - 1)
        ph += tw * f / sr
        s = math.sin(ph) if wave == "sine" else (1.0 if math.sin(ph) >= 0 else -1.0) if wave == "square" else (2 * (ph / tw % 1) - 1) if wave == "saw" else (2 * abs(2 * (ph / tw % 1) - 1) - 1)
        out[i] = s * vol * min(1.0, i / na) * min(1.0, (n - i) / nr)
    return out


def noise(dur: float, rnd: random.Random, vol: float = 0.4, lp: float = 0.2, decay: float = 0.0, lfo: float = 0.0, sr: int = 44100) -> "array[float]":
    n = int(dur * sr)
    out = zeros(n)
    if n <= 0:
        return out
    lib = load()
    if lib is not None:
        lib.flow_noise(_ptr(out), n, rnd.getrandbits(64), vol, lp, decay, lfo, float(sr))
        return out
    y = 0.0
    for i in range(n):
        y += lp * (rnd.uniform(-1, 1) - y)
        a = vol * (math.exp(-decay * i / sr) if decay else 1.0)
        if lfo:
            a *= 0.65 + 0.35 * math.sin(2 * math.pi * lfo * i / sr)
        out[i] = y * a
    return out


def mix_add(dst: "array[float]", src: Any, offset: int) -> None:
    """dst[offset + i] += src[i] (corta no fim de dst); altera `dst` no lugar."""
    if not isinstance(src, array):
        src = array("d", src)
    n, m = len(dst), len(src)
    if offset >= n or m == 0:
        return
    lib = load()
    if lib is not None and offset >= 0:
        lib.flow_mix_add(_ptr(dst), n, _ptr(src), m, offset)
        return
    for i in range(max(0, -offset), min(m, n - offset)):
        dst[offset + i] += src[i]


def fade_out(buf: "array[float]", fade: int) -> None:
    n = len(buf)
    fade = min(fade, n)
    if fade <= 0:
        return
    lib = load()
    if lib is not None:
        lib.flow_fade_out(_ptr(buf), n, fade)
        return
    for i in range(fade):
        buf[n - 1 - i] *= i / fade


def pcm16(samples: Any, limit: float = 0.85) -> bytes:
    """Amostras (-1..1) → bytes PCM de 16 bits, normalizando o pico quando passa de `limit`."""
    if not isinstance(samples, array):
        samples = array("d", samples)
    n = len(samples)
    if n == 0:
        return b""
    lib = load()
    if lib is not None:
        out = array("h", bytes(2 * n))
        addr, _ = out.buffer_info()
        lib.flow_pcm16(_ptr(samples), n, ctypes.cast(addr, ctypes.POINTER(ctypes.c_int16)), limit)
        return out.tobytes() if sys.byteorder == "little" else _swap(out)
    peak = max(1e-6, max(abs(s) for s in samples))
    k = limit / peak if peak > limit else 1.0
    return array("h", (int(max(-1.0, min(1.0, s * k)) * 32767) for s in samples)).tobytes()


def _swap(a: "array[int]") -> bytes:  # pragma: no cover  (máquinas big-endian)
    a.byteswap()
    return a.tobytes()


# --------------------------------------------------------------------------- modelos locais (v0.12): hardware, cabeçalhos, planejador e pré-carga
# Cada função usa o Rust quando existe e tem o equivalente em Python (mesmas contas, conferidas nos testes).
import json  # noqa: E402
import struct  # noqa: E402

MIB = 1048576.0


def _call_json(fn: Any, *args: Any) -> Optional[Dict[str, Any]]:
    """Chama uma função do núcleo que devolve JSON no buffer; aumenta o buffer se preciso. None se deu erro."""
    cap = 4096
    for _try in range(2):
        buf = ctypes.create_string_buffer(cap)
        n = fn(*args, buf, cap)
        if n < 0:
            return None
        if n <= cap:
            try:
                return json.loads(buf.raw[:n].decode("utf-8"))
            except ValueError:
                return None
        cap = int(n) + 16
    return None


def _lib2() -> Any:
    lib = load()
    return lib if lib is not None and hasattr(lib, "flow_plan_llm") else None


def sys_info() -> Dict[str, Any]:
    """Núcleos lógicos/físicos, extensões da CPU e memória (total/disponível, respeitando o limite de contêiner)."""
    lib = _lib2()
    if lib is not None:
        r = _call_json(lib.flow_sys_info)
        if r:
            return r
    logical = os.cpu_count() or 1
    phys, feats, total, avail = logical, [], 0, 0
    try:
        seen = set()
        for i in range(logical):
            seen.add(Path(f"/sys/devices/system/cpu/cpu{i}/topology/thread_siblings_list").read_text().strip())
        phys = len(seen) or logical
    except OSError:
        phys = logical // 2 if logical >= 4 else logical
    try:
        flags = next((ln.split(":", 1)[1].split() for ln in Path("/proc/cpuinfo").read_text().splitlines() if ln.startswith(("flags", "Features"))), [])
        feats = [f for f in ("sse4_2", "avx", "avx2", "fma", "f16c", "avx512f", "avx512bw", "avx512vl", "neon", "asimd") if f in flags]
        feats = [{"sse4_2": "sse4.2", "asimd": "neon"}.get(f, f) for f in feats]
    except OSError:
        pass
    try:
        mem = {ln.split(":")[0]: int(ln.split()[1]) * 1024 for ln in Path("/proc/meminfo").read_text().splitlines() if ln.split()[1:2]}
        total, avail = mem.get("MemTotal", 0), mem.get("MemAvailable", mem.get("MemFree", 0))
        for pth in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
            try:
                v = int(Path(pth).read_text().strip())
                if 0 < v < total:
                    total, avail = v, min(avail, v)
            except (OSError, ValueError):
                pass
    except (OSError, ValueError, IndexError):
        pass
    if not total and os.name == "nt":
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            ms = _MS()
            ms.l = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                total, avail = int(ms.tp), int(ms.ap)
        except (AttributeError, OSError, ValueError):
            pass
    if not total:
        try:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            avail = int(total * 0.6)
        except (AttributeError, ValueError, OSError):
            pass
    import platform

    return {"logical": logical, "physical": min(phys, logical), "features": feats, "arch": platform.machine().lower(), "os": platform.system().lower(), "ram_total": total, "ram_avail": min(avail, total), "ram_exact": bool(total)}


# ----- cabeçalhos
_GGML = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 6: "Q5_0", 7: "Q5_1", 8: "Q8_0", 9: "Q8_1", 10: "Q2_K", 11: "Q3_K", 12: "Q4_K", 13: "Q5_K", 14: "Q6_K", 15: "Q8_K", 16: "IQ2_XXS",
         17: "IQ2_XS", 18: "IQ3_XXS", 19: "IQ1_S", 20: "IQ4_NL", 21: "IQ3_S", 22: "IQ2_S", 23: "IQ4_XS", 24: "I8", 25: "I16", 26: "I32", 27: "I64", 28: "F64", 29: "IQ1_M", 30: "BF16"}
_SCALAR = {0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2), 4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4), 7: ("<B", 1), 10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8)}
_ST_BYTES = {"F64": 8, "I64": 8, "U64": 8, "F32": 4, "I32": 4, "U32": 4, "F16": 2, "BF16": 2, "I16": 2, "U16": 2, "I8": 1, "U8": 1, "BOOL": 1, "F8_E4M3": 1, "F8_E5M2": 1}


def _py_gguf(path: str, size: int) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "rb", buffering=1 << 20) as f:
            if f.read(4) != b"GGUF":
                return None
            u32 = lambda: struct.unpack("<I", f.read(4))[0]  # noqa: E731
            u64 = lambda: struct.unpack("<Q", f.read(8))[0]  # noqa: E731
            version = u32()
            if version not in (2, 3):
                return None
            n_t, n_kv = u64(), u64()
            if n_kv > 1_000_000 or n_t > 10_000_000:
                return None

            def gstr() -> str:
                n = u64()
                if n > (1 << 24):
                    raise ValueError
                return f.read(n).decode("utf-8", "replace")
            m = {"arch": "", "name": "", "ctx": 0, "layers": 0, "embd": 0, "heads": 0, "heads_kv": 0, "ff": 0, "key_len": 0, "file_type": 0, "vocab": 0, "experts": 0}
            for _i in range(n_kv):
                key, t = gstr(), u32()
                if t == 8:
                    v = gstr()
                    if key == "general.architecture":
                        m["arch"] = v
                    elif key == "general.name":
                        m["name"] = v
                elif t == 9:
                    et, ln = u32(), u64()
                    if key == "tokenizer.ggml.tokens":
                        m["vocab"] = ln
                    if et == 8:
                        for _j in range(ln):
                            n = u64()
                            if n > (1 << 24):
                                return None
                            f.seek(n, 1)
                    else:
                        f.seek(_SCALAR[et][1] * ln, 1)
                else:
                    fmt, n = _SCALAR[t]
                    v = int(struct.unpack(fmt, f.read(n))[0])
                    for suf, k in ((".context_length", "ctx"), (".block_count", "layers"), (".embedding_length", "embd"), (".attention.head_count", "heads"), (".attention.head_count_kv", "heads_kv"),
                                   (".feed_forward_length", "ff"), (".attention.key_length", "key_len"), (".expert_count", "experts")):
                        if key.endswith(suf):
                            m[k] = v
                            break
                    else:
                        if key == "general.file_type":
                            m["file_type"] = v
            by, params = {}, 0.0
            for _i in range(n_t):
                n = u64()
                if n > 4096:
                    return None
                f.seek(n, 1)
                nd = u32()
                if nd > 8:
                    return None
                el = 1.0
                for _d in range(nd):
                    el *= float(u64())
                ty = u32()
                u64()
                params += el
                by[ty] = by.get(ty, 0.0) + el
        dom = max(by.items(), key=lambda kv: kv[1])[0] if by else 0
        heads = max(m["heads"], 1)
        heads_kv = m["heads_kv"] if m["heads_kv"] > 0 else heads
        head_dim = m["key_len"] if m["key_len"] > 0 else (m["embd"] // heads if m["embd"] > 0 else 0)
        return {"format": "gguf", "version": version, "bytes": size, "arch": m["arch"], "name": m["name"], "ctx_train": m["ctx"], "layers": m["layers"], "embd": m["embd"], "heads": m["heads"],
                "heads_kv": heads_kv, "ff": m["ff"], "experts": m["experts"], "vocab": m["vocab"], "tensors": n_t, "params": params, "quant": _GGML.get(dom, "?"), "file_type": m["file_type"],
                "kv_bytes_per_token": 2 * max(m["layers"], 0) * heads_kv * head_dim * 2}
    except (OSError, struct.error, KeyError, ValueError):
        return None


def _py_safetensors(path: str, size: int) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            if n == 0 or n > (1 << 28) or n + 8 > size:
                return None
            head = json.loads(f.read(n).decode("utf-8"))
    except (OSError, struct.error, ValueError):
        return None
    if not isinstance(head, dict):
        return None
    params, tensors, dts = 0.0, 0, {}
    for k, t in head.items():
        if k == "__metadata__" or not isinstance(t, dict):
            continue
        el = 1.0
        for d in t.get("shape") or []:
            el *= float(d)
        dt = t.get("dtype", "F16")
        params += el
        tensors += 1
        dts[dt] = dts.get(dt, 0.0) + el
    dom = max(dts.items(), key=lambda kv: kv[1])[0] if dts else "?"
    return {"format": "safetensors", "bytes": size, "tensors": tensors, "params": params, "dtype": dom, "weight_bytes": sum(_ST_BYTES.get(d, 2) * e for d, e in dts.items())}


def model_info(path: Any) -> Optional[Dict[str, Any]]:
    """Cabeçalho do modelo (GGUF ou safetensors) sem carregar os pesos: tamanho, arquitetura, camadas, contexto de treino, quantização e custo do cache de atenção por token. None se o arquivo não existe."""
    p = str(path)
    if not os.path.isfile(p):
        return None
    lib = _lib2()
    if lib is not None:
        r = _call_json(lambda buf, cap: lib.flow_model_info(p.encode("utf-8"), len(p.encode("utf-8")), buf, cap))
        if r:
            return r
    size = os.path.getsize(p)
    low = p.lower()
    info = _py_gguf(p, size) if low.endswith(".gguf") else _py_safetensors(p, size) if low.endswith(".safetensors") else (_py_gguf(p, size) or _py_safetensors(p, size))
    return info or {"format": "unknown", "bytes": size}


# ----- planejador
def _floor_to(v: float, q: float) -> float:
    return math.floor(v / q) * q


def plan_llm(weights: int, layers: int, kv_per_token: int, ctx_train: int, ctx_want: int, explicit: bool, ctx_cap: int, ram_avail: int, vram_free: int, unified: bool, phys: int, logical: int, mode: int) -> Dict[str, Any]:
    """Parâmetros de carga de um LLM GGUF para a memória livre agora. mode: 0 leve, 1 equilibrado, 2 máximo."""
    lib = _lib2()
    if lib is not None:
        r = _call_json(lambda buf, cap: lib.flow_plan_llm(int(weights), int(layers), int(kv_per_token), int(ctx_train), int(ctx_want), int(explicit), int(ctx_cap), int(ram_avail), int(vram_free), int(unified), int(phys), int(logical), int(mode), buf, cap))
        if r:
            return r
    inf = math.inf
    w, n_layers = float(weights), float(max(layers, 1))
    layer_bytes = w / n_layers
    kvpt = float(kv_per_token) if kv_per_token > 0 else 131072.0
    ram, vram = float(ram_avail), float(vram_free)
    has_gpu = vram > 0.0
    want = float(ctx_want) if ctx_want > 0 else 4096.0
    probe = min(want, 8192.0)
    notes = []
    usable_vram = vram * 0.90 - 600.0 * MIB
    ngl = 0.0
    if has_gpu and usable_vram > 0.0:
        per_layer = layer_bytes + kvpt * probe / n_layers * (0.53 if mode == 0 else 1.0)
        ngl = min(math.floor(usable_vram / per_layer), n_layers)
        if ngl < 1.0:
            ngl = 0.0
    all_gpu = ngl >= n_layers
    frac_gpu = 1.0 if all_gpu else ngl / n_layers
    ram_budget = max(ram * 0.80 - ngl * layer_bytes, 0.0) if unified else ram * 0.80
    cpu_weights = w * 0.15 if all_gpu else (n_layers - ngl) * layer_bytes + w * 0.05

    def ctx_for(scale: float) -> float:
        gpu_left, cpu_left = usable_vram - ngl * layer_bytes, ram_budget - cpu_weights
        tg = gpu_left / (kvpt * scale * frac_gpu) if frac_gpu > 0.0 else inf
        tc = cpu_left / (kvpt * scale * (1.0 - frac_gpu)) if frac_gpu < 1.0 else inf
        m = min(tg, tc)
        if ctx_train > 0:
            m = min(m, float(ctx_train))
        if ctx_cap > 0:
            m = min(m, float(ctx_cap))
        return _floor_to(max(m, 0.0), 256.0) if math.isfinite(m) else want
    kv_q8 = mode == 0
    ctx_max = ctx_for(0.53 if kv_q8 else 1.0)
    if not kv_q8 and ctx_max < want:
        q = ctx_for(0.53)
        if q > ctx_max:
            kv_q8, ctx_max = True, q
            notes.append("cache de atenção em 8 bits para caber mais contexto")
    kv_q4 = False
    if kv_q8 and ctx_max < want and want >= 65536.0:   # contexto longo (256K, 512K, 1M…): se nem o cache de 8 bits cabe, usa o de 4 bits
        q = ctx_for(0.28)
        if q > ctx_max:
            kv_q4, ctx_max = True, q
            notes.append("cache de atenção em 4 bits para caber o contexto longo")
    ctx = want if explicit else min(want, ctx_max)
    if ctx < 512.0:
        ctx = 512.0
        notes.append("pouca memória livre: contexto mínimo")
    if explicit and want > ctx_max and ctx_max > 0.0:
        notes.append(f"o contexto pedido ({int(want)}) passa do que cabe na memória livre ({int(ctx_max)})")
    if explicit and ctx_train > 0 and want > ctx_train:
        notes.append(f"o contexto pedido ({int(want)}) passa do que o modelo foi treinado ({int(ctx_train)}): a qualidade pode cair")
    p = float(max(phys, 1))
    lg = float(max(logical, max(phys, 1)))
    threads = min(p, 4.0) if all_gpu else (p - 1.0 if p >= 8.0 else p)
    threads_batch = max(min(threads, p), 4.0 if all_gpu else threads) if all_gpu else (lg - 1.0 if lg > p and lg >= 8.0 else threads)
    # lotes maiores aceleram a ingestão do prompt em GPU (NVIDIA 20/30/40/50) quando há folga de VRAM/RAM
    gpu_headroom = usable_vram - ngl * layer_bytes - kvpt * ctx * (0.28 if kv_q4 else 0.53 if kv_q8 else 1.0) * frac_gpu
    roomy_gpu = has_gpu and frac_gpu >= 0.5 and gpu_headroom > 1024.0 * MIB
    if mode == 0:
        n_batch = 256.0 if roomy_gpu else 128.0
    elif mode == 2 and roomy_gpu:
        n_batch = 1024.0
    elif all_gpu or mode == 2 or roomy_gpu:
        n_batch = 512.0
    else:
        n_batch = 256.0
    n_ubatch = min(256.0, n_batch) if mode == 0 else (512.0 if roomy_gpu else min(512.0, n_batch))
    # atenção flash ajuda em GPUs modernas (Turing/Ampere/Ada/Blackwell) e também com KV quantizado
    flash = has_gpu or kv_q8 or kv_q4 or mode != 0
    mlock = mode == 2 and not has_gpu and ram > w * 2.0 + kvpt * ctx
    prefetch = w < ram * 0.70
    ram_after = ram - cpu_weights - kvpt * ctx * (1.0 - frac_gpu)
    if mode == 0:
        cache_bytes = 256.0 * MIB if ram_after > 1024.0 * MIB else 128.0 * MIB
    elif ram_after > 8192.0 * MIB:
        cache_bytes = min(ram_after * 0.12, 2048.0 * MIB)
    elif ram_after > 4096.0 * MIB:
        cache_bytes = min(ram_after * 0.10, 1024.0 * MIB)
    elif ram_after > 1536.0 * MIB:
        cache_bytes = 128.0 * MIB
    else:
        cache_bytes = 0.0
    return {"n_ctx": int(ctx), "ctx_max": int(ctx_max), "n_gpu_layers": -1 if all_gpu else int(ngl), "gpu_layers_fit": int(ngl), "n_threads": int(threads), "n_threads_batch": int(threads_batch),
            "n_batch": int(n_batch), "n_ubatch": int(n_ubatch), "kv_q8": kv_q8, "kv_q4": kv_q4, "flash": flash, "mlock": mlock, "prefetch": prefetch, "cache_bytes": int(cache_bytes), "notes": notes}


def plan_media(weights: int, vram_free: int, ram_avail: int, unified: bool, mode: int) -> Dict[str, Any]:
    """Como carregar um modelo de imagem/vídeo/áudio: gpu | model_offload | sequential_offload | cpu (+ fatias de atenção/VAE)."""
    lib = _lib2()
    if lib is not None:
        r = _call_json(lambda buf, cap: lib.flow_plan_media(int(weights), int(vram_free), int(ram_avail), int(unified), int(mode), buf, cap))
        if r:
            return r
    w, vram, ram, gib = float(weights), float(vram_free), float(ram_avail), 1024.0 * MIB
    if vram <= 0.0:
        strategy, slicing, tiling = "cpu", (w > ram * 0.40 or mode == 0), mode == 0
    else:
        need, usable = w * 1.25 + 1.5 * gib, vram * 0.92
        strategy = "gpu" if (mode != 0 and need <= usable) else "model_offload" if (w * 0.55 + 1.0 * gib <= usable) else "sequential_offload"
        slicing, tiling = (mode == 0 or need > usable * 0.75), (mode == 0 or need > usable * 0.60)
    host_ok = w < ram * 0.5 if unified else w < ram * 0.70
    return {"strategy": strategy, "slicing": slicing, "tiling": tiling, "prefetch": host_ok}


# ----- pré-carga
def prefetch(paths: Any, threads: int = 0) -> int:
    """Lê os arquivos em paralelo para o cache do sistema (o carregamento do modelo depois acha tudo em RAM). Devolve os bytes lidos."""
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]
    files = [str(p) for p in paths if os.path.isfile(str(p))]
    if not files:
        return 0
    n = threads or min(8, max(2, (os.cpu_count() or 2)))
    lib = _lib2()
    total = 0
    if lib is not None:
        for p in files:
            b = p.encode("utf-8")
            r = lib.flow_prefetch(b, len(b), n)
            total += max(0, int(r))
        return total
    def _read(p: str, i: int, parts: int) -> int:
        size, got = os.path.getsize(p), 0
        stripe = max(4 << 20, -(-size // parts))
        try:
            fd = os.open(p, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        except OSError:
            return 0
        try:
            if hasattr(os, "posix_fadvise"):
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_WILLNEED)
            off, end = i * stripe, min((i + 1) * stripe, size)
            while off < end:
                if hasattr(os, "pread"):
                    chunk = os.pread(fd, min(4 << 20, end - off), off)
                else:   # Windows: sem pread; cada thread tem o seu próprio descritor, então posicionar e ler é seguro
                    os.lseek(fd, off, os.SEEK_SET)
                    chunk = os.read(fd, min(4 << 20, end - off))
                if not chunk:
                    break
                off += len(chunk)
                got += len(chunk)
        finally:
            os.close(fd)
        return got
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=n) as ex:
        for p in files:
            total += sum(ex.map(lambda i, p=p: _read(p, i, n), range(n)))
    return total


# registro do último carregamento de modelo local (aparece em Configuração → Desempenho)
LAST: Dict[str, Any] = {}


def record(kind: str, **info: Any) -> None:
    LAST[kind] = dict(info, at=int(__import__("time").time()))


def dir_weight_bytes(path: Any) -> int:
    """Soma dos arquivos de pesos (safetensors/bin/pt/ckpt/gguf) de uma pasta de modelo."""
    total = 0
    try:
        for f in Path(str(path)).rglob("*"):
            if f.suffix.lower() in (".safetensors", ".bin", ".pt", ".pth", ".ckpt", ".gguf") and (f.is_file() or f.is_symlink()):
                try:
                    total += os.path.getsize(f)
                except OSError:
                    pass
    except OSError:
        pass
    return total


def weight_files(path: Any) -> list:
    out = []
    try:
        for f in Path(str(path)).rglob("*"):
            if f.suffix.lower() in (".safetensors", ".bin", ".pt", ".pth", ".ckpt", ".gguf") and os.path.isfile(f):
                out.append(str(f))
    except OSError:
        pass
    return out


# --------------------------------------------------------------------------- v0.14: vários agentes locais, armazenamento e memória
# Cada função usa o Rust (interface 3) quando existe e tem o equivalente em Python (mesmas contas, conferidas nos testes).
AGENT_KIND = {"cloud": 0, "embedded": 1, "server": 2}


def _lib3() -> Any:
    lib = load()
    return lib if lib is not None and hasattr(lib, "flow_plan_agents") else None


def plan_agents(n_agents: int, kind: int, model_bytes: int, kv_bytes_per_agent: int, ram_avail: int, vram_free: int, unified: bool, phys: int, logical: int, mode: int) -> Dict[str, Any]:
    """Como rodar vários agentes de IA: quantos ao mesmo tempo (`parallel`), quantos modelos ficam na memória (`resident_models`), threads por agente e o tipo de fila.
    kind: 0 nuvem · 1 modelo embutido (uma instância; fila com prioridade) · 2 servidor local (LM Studio, Ollama…). mode: 0 leve, 1 equilibrado, 2 máximo."""
    lib = _lib3()
    if lib is not None:
        r = _call_json(lambda buf, cap: lib.flow_plan_agents(int(n_agents), int(kind), int(model_bytes), int(kv_bytes_per_agent), int(ram_avail), int(vram_free), int(unified), int(phys), int(logical), int(mode), buf, cap))
        if r:
            return r
    n, p = float(max(n_agents, 1)), float(max(phys, 1))
    l = float(max(logical, max(phys, 1)))
    ram, vram = float(ram_avail), float(vram_free)
    w, kv = max(float(model_bytes), 1.0), max(float(kv_bytes_per_agent), 0.0)
    notes = []
    pool = ram * 0.65 if unified else (vram * 0.85 + ram * 0.30 if vram > 0.0 else ram * 0.65)
    fit = max(math.floor(pool / (w * 1.15)), 1.0)
    resident = 1.0 if mode == 0 else (min(fit, 2.0) if mode == 1 else min(fit, 3.0))
    if kind == 0:
        parallel, threads_each, queue = min(n, {0: 2.0, 1: 4.0}.get(mode, 8.0)), 1.0, "fair"
    elif kind == 2:
        by_mem = max(math.floor((pool - w) / max(kv, 64.0 * MIB)), 1.0)
        parallel, threads_each, queue = min(n, {0: 1.0, 1: 2.0}.get(mode, 4.0), by_mem), 1.0, "fair"
    else:
        if n > 1.0:
            notes.append("modelo embutido: um agente fala por vez (fila com prioridade para o chat)")
        parallel, threads_each, queue = 1.0, (min(p, 4.0) if vram > 0.0 else (p - 1.0 if p >= 8.0 else p)), "priority"
    if kind == 1:
        threads = threads_each
    elif mode == 0:
        threads = max(math.floor(p / 2.0), 1.0)
    else:
        threads = min(max(math.floor(l / max(parallel, 1.0)), 1.0), p)
    return {"parallel": int(parallel), "resident_models": int(resident), "threads_each": int(threads), "queue": queue, "share_prefix": kind != 0 and n > 1.0, "pool_bytes": int(pool), "notes": notes}


def scan_dir(path: Any, max_entries: int = 0, threads: int = 0) -> Optional[Dict[str, Any]]:
    """Totais de uma pasta (arquivos, pastas, bytes), por tipo de arquivo e os 20 maiores — com várias threads no Rust. None se não é uma pasta. Links simbólicos não são seguidos."""
    p = str(path)
    if not os.path.isdir(p):
        return None
    lib = _lib3()
    if lib is not None:
        b = p.encode("utf-8")
        r = _call_json(lambda buf, cap: lib.flow_scan_dir(b, len(b), int(max_entries), int(threads or min(8, os.cpu_count() or 2)), buf, cap))
        if r:
            return r
    files = dirs = total = 0
    by_ext: Dict[str, list] = {}
    big: list = []
    limit = max_entries or 5_000_000
    stack = [p]
    while stack and files + dirs <= limit:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        dirs += 1
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        sz = e.stat(follow_symlinks=False).st_size
                        files += 1
                        total += sz
                        ext = os.path.splitext(e.name)[1][1:].lower()
                        ent = by_ext.setdefault(ext, [0, 0])
                        ent[0] += 1
                        ent[1] += sz
                        big.append((sz, e.path))
                        if len(big) > 400:
                            big = sorted(big, reverse=True)[:20]
                except OSError:
                    continue
    big = sorted(big, reverse=True)[:20]
    exts = sorted(by_ext.items(), key=lambda kv: (-kv[1][1], kv[0]))[:16]
    return {"files": files, "dirs": dirs, "bytes": total, "by_ext": [{"ext": k, "files": v[0], "bytes": v[1]} for k, v in exts], "largest": [{"path": q, "bytes": sz} for sz, q in big]}


def dup_groups(root: Any, min_size: int = 1 << 20, exts: Any = (), max_files: int = 200000) -> list:
    """Grupos de arquivos IDÊNTICOS sob `root` (mesmo tamanho e conteúdo, conferido byte a byte): [{"size": N, "paths": [...]}, ...] do maior para o menor.
    `exts`: só estas extensões (vazio = todas). Quem decide o que fazer com os duplicados (ex.: trocar por links) é quem chama."""
    p = str(root)
    if not os.path.isdir(p):
        return []
    ext_list = [str(e).strip().lstrip(".").lower() for e in (exts or ()) if str(e).strip()]
    lib = _lib3()
    if lib is not None:
        b, eb = p.encode("utf-8"), ",".join(ext_list).encode("utf-8")
        r = _call_json(lambda buf, cap: lib.flow_dup_groups(b, len(b), int(max(min_size, 1)), eb, len(eb), int(max_files), buf, cap))
        if r is not None:
            return r
    import filecmp
    import hashlib

    by_size: Dict[int, list] = {}
    n = 0
    stack = [p]
    while stack and n < max_files:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        sz = e.stat(follow_symlinks=False).st_size
                        if sz >= max(min_size, 1) and (not ext_list or os.path.splitext(e.name)[1][1:].lower() in ext_list):
                            by_size.setdefault(sz, []).append(e.path)
                            n += 1
                except OSError:
                    continue

    def digest(path: str, size: int, partial: bool) -> Optional[bytes]:
        h = hashlib.blake2b(digest_size=16)
        h.update(str(size).encode())
        try:
            with open(path, "rb") as f:
                if partial:
                    h.update(f.read(65536))
                    if size > 131072:
                        f.seek(size - 65536)
                        h.update(f.read(65536))
                else:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
        except OSError:
            return None
        return h.digest()

    groups: list = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        sig: Dict[bytes, list] = {}
        for q in paths:
            d1 = digest(q, size, True)
            if d1:
                sig.setdefault(d1, []).append(q)
        for l1 in (v for v in sig.values() if len(v) > 1):
            full: Dict[bytes, list] = {}
            for q in l1:
                d2 = digest(q, size, False)
                if d2:
                    full.setdefault(d2, []).append(q)
            for rest in (list(v) for v in full.values() if len(v) > 1):
                while len(rest) > 1:
                    first = rest.pop(0)
                    same = [q for q in rest if filecmp.cmp(first, q, shallow=False)]
                    rest = [q for q in rest if q not in same]
                    if same:
                        groups.append({"size": size, "paths": sorted([first] + same)})
    groups.sort(key=lambda g: (-g["size"], g["paths"]))
    return groups


def release_memory() -> int:
    """Devolve ao sistema a memória livre que o alocador ainda segura (use depois de descarregar um modelo). Bytes liberados (estimativa) ou -1 se o sistema não oferece."""
    lib = _lib3()
    if lib is not None:
        try:
            return int(lib.flow_release_memory())
        except Exception:  # noqa: BLE001
            return -1
    if sys.platform.startswith("linux"):
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
            return 0
        except (OSError, AttributeError):
            return -1
    return -1


def evict_file(path: Any) -> int:
    """Tira o arquivo (pesos de um modelo descarregado) do cache de páginas do sistema. 0 = feito, 1 = o sistema não oferece (ele mesmo gerencia), -1 = não abriu."""
    p = str(path)
    if not os.path.isfile(p):
        return -1
    lib = _lib3()
    if lib is not None:
        b = p.encode("utf-8")
        return int(lib.flow_evict_file(b, len(b)))
    if hasattr(os, "posix_fadvise"):
        try:
            fd = os.open(p, os.O_RDONLY)
        except OSError:
            return -1
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            return 0
        except OSError:
            return 1
        finally:
            os.close(fd)
    return 1


# --------------------------------------------------------------------------- v0.17: análise de mídia (Studio) e ordem de grafos (Canvas)
# Mesmo esquema: Rust (interface 4) quando existe; senão o equivalente em Python, com as mesmas contas na mesma ordem (os testes comparam os dois lados).
def _lib4() -> Any:
    lib = load()
    return lib if lib is not None and hasattr(lib, "flow_audio_levels") else None


def _addr(a: "array[Any]") -> int:
    return a.buffer_info()[0]


def audio_levels(pcm: "array[int]", win: int) -> "array[float]":
    """Nível (dB, RMS) de cada janela de `win` amostras de um PCM de 16 bits mono (`array('h')`). Silêncio = -90 dB; a última janela pode ser parcial."""
    n = len(pcm)
    if n == 0 or win <= 0:
        return array("d")
    count = (n + win - 1) // win
    out = zeros(count)
    lib = _lib4()
    if lib is not None:
        if lib.flow_audio_levels(_addr(pcm), n, win, _addr(out), count) == count:
            return out
    for k in range(count):
        chunk = pcm[k * win:(k + 1) * win]
        ss = 0
        for v in chunk:
            ss += v * v
        rms = math.sqrt(ss / len(chunk)) / 32768.0
        out[k] = -90.0 if rms <= 0.0 else max(20.0 * math.log10(rms), -90.0)
    return out


def silence_ranges(levels: "array[float]", win_s: float, thresh_db: float = -35.0, min_len: float = 0.6, limit: int = 2000) -> list:
    """Trechos de silêncio [(início, fim)] em segundos: janelas abaixo de `thresh_db` somando ao menos `min_len`."""
    n = len(levels)
    if n == 0:
        return []
    lib = _lib4()
    if lib is not None:
        out = zeros(limit * 2)
        k = lib.flow_silence_ranges(_addr(levels), n, win_s, thresh_db, min_len, _addr(out), limit)
        if k >= 0:
            return [(out[i * 2], out[i * 2 + 1]) for i in range(min(k, limit))]
    pairs: list = []
    start = None

    def push(a: int, b: int) -> None:
        t0, t1 = a * win_s, b * win_s
        if t1 - t0 >= min_len - 1e-9:
            pairs.append((t0, t1))

    for i, v in enumerate(levels):
        if v < thresh_db:
            if start is None:
                start = i
        elif start is not None:
            push(start, i)
            start = None
    if start is not None:
        push(start, n)
    return pairs[:limit]


def pick_peaks(vals: "array[float]", win_s: float, min_gap: float, limit: int) -> list:
    """Os `limit` pontos mais altos da curva, com `min_gap` segundos de distância mínima: [(instante do centro da janela, valor)], do maior para o menor."""
    n = len(vals)
    if n == 0 or limit <= 0:
        return []
    lib = _lib4()
    if lib is not None:
        out = zeros(limit * 2)
        k = lib.flow_pick_peaks(_addr(vals), n, win_s, min_gap, limit, _addr(out))
        if k >= 0:
            return [(out[i * 2], out[i * 2 + 1]) for i in range(k)]
    order = sorted(range(n), key=lambda i: (-vals[i], i))
    taken: list = []
    res: list = []
    for i in order:
        if len(res) >= limit:
            break
        t = (i + 0.5) * win_s
        if all(abs(t - u) >= min_gap - 1e-9 for u in taken):
            taken.append(t)
            res.append((t, vals[i]))
    return res


def onset_env(levels: "array[float]") -> "array[float]":
    """Subida positiva do nível (dB) de uma janela para a seguinte — onde começam as batidas e notas."""
    n = len(levels)
    out = zeros(n)
    if n == 0:
        return out
    lib = _lib4()
    if lib is not None and lib.flow_onset_env(_addr(levels), n, _addr(out)) == n:
        return out
    for i in range(1, n):
        out[i] = max(levels[i] - levels[i - 1], 0.0)
    return out


def tempo(env: "array[float]", hop_s: float, min_bpm: float = 70.0, max_bpm: float = 200.0) -> Optional[Dict[str, float]]:
    """Andamento do envelope de início de notas: {"bpm", "phase" (s até a 1ª batida), "confidence"} ou None se o sinal é curto ou sem pulso."""
    n = len(env)
    if n == 0:
        return None
    lib = _lib4()
    if lib is not None:
        out = zeros(3)
        r = lib.flow_tempo(_addr(env), n, hop_s, min_bpm, max_bpm, _addr(out))
        if r >= 0:
            return {"bpm": out[0], "phase": out[1], "confidence": out[2]} if r == 1 else None
    lag_min = max(int(math.floor(60.0 / max_bpm / hop_s)), 1)
    lag_max = int(math.ceil(60.0 / min_bpm / hop_s))
    if lag_max <= lag_min or n < lag_max * 2:
        return None
    scores = []
    for lag in range(lag_min, lag_max + 1):
        s = 0.0
        for i in range(n - lag):
            s += env[i] * env[i + lag]
        bpm = 60.0 / (lag * hop_s)
        prior = math.exp(-0.5 * (math.log2(bpm / 120.0) / 0.8) ** 2)
        scores.append(s / (n - lag) * prior)
    mean = sum(scores) / len(scores)
    best = 0
    for i, s in enumerate(scores):
        if s > scores[best]:
            best = i
    if scores[best] <= 0.0:
        return None
    lag_f = float(lag_min + best)
    if 0 < best < len(scores) - 1:
        a, b, c = scores[best - 1], scores[best], scores[best + 1]
        d = a - 2.0 * b + c
        if abs(d) > 1e-12:
            lag_f += max(-0.5, min(0.5, 0.5 * (a - c) / d))
    period = lag_f
    offs = int(math.ceil(period))
    best_off, best_sum = 0, -1.0
    for off in range(offs):
        total, k = 0.0, 0
        while True:
            ix = int(math.floor(off + k * period + 0.5))   # round() do Rust: metade para longe do zero
            if ix >= n:
                break
            total += env[ix]
            k += 1
        if total > best_sum:
            best_sum, best_off = total, off
    return {"bpm": 60.0 / (period * hop_s), "phase": best_off * hop_s, "confidence": scores[best] / mean if mean > 0 else 0.0}


def frame_activity(frames: bytes, fsize: int) -> "array[float]":
    """Diferença média absoluta (0 a 1) de cada quadro (cinza, `fsize` bytes) para o anterior; o primeiro vale 0."""
    if fsize <= 0 or not frames:
        return array("d")
    nf = len(frames) // fsize
    out = zeros(nf)
    if nf == 0:
        return out
    lib = _lib4()
    if lib is not None:
        buf = ctypes.create_string_buffer(bytes(frames[:nf * fsize]), nf * fsize)
        if lib.flow_frame_activity(ctypes.addressof(buf), nf, fsize, _addr(out)) == nf:
            return out
    for i in range(1, nf):
        a, b = frames[(i - 1) * fsize:i * fsize], frames[i * fsize:(i + 1) * fsize]
        d = 0
        for x, y in zip(a, b):
            d += abs(x - y)
        out[i] = d / (fsize * 255.0)
    return out


def scene_cuts(act: "array[float]", step_s: float, k: float = 2.5, min_abs: float = 0.08, min_gap: float = 0.6, limit: int = 2000) -> list:
    """Trocas de cena: máximos locais da atividade acima de max(min_abs, média + k·desvio), com `min_gap` s entre elas. Instantes em ordem crescente."""
    n = len(act)
    if n < 2:
        return []
    lib = _lib4()
    if lib is not None:
        out = zeros(limit)
        c = lib.flow_scene_cuts(_addr(act), n, step_s, k, min_abs, min_gap, _addr(out), limit)
        if c >= 0:
            return [out[i] for i in range(min(c, limit))]
    mean = sum(act) / n
    var = sum((v - mean) * (v - mean) for v in act) / n
    thr = max(min_abs, mean + k * math.sqrt(var))
    cand = [i for i in range(1, n) if act[i] > thr and act[i] >= act[i - 1] and act[i] > (act[i + 1] if i + 1 < n else -1.7976931348623157e308)]
    cand.sort(key=lambda i: (-act[i], i))
    taken: list = []
    for i in cand:
        t = i * step_s
        if all(abs(t - u) >= min_gap - 1e-9 for u in taken):
            taken.append(t)
    taken.sort()
    return taken[:limit]


def waveform(pcm: "array[int]", buckets: int) -> "array[float]":
    """Pico absoluto (0 a 1) de cada um de `buckets` blocos iguais do PCM — a forma de onda dos clipes."""
    n = len(pcm)
    if n == 0 or buckets <= 0:
        return zeros(max(buckets, 0))
    out = zeros(buckets)
    lib = _lib4()
    if lib is not None and lib.flow_waveform(_addr(pcm), n, buckets, _addr(out)) == buckets:
        return out
    for b in range(buckets):
        a = b * n // buckets
        z = min(max((b + 1) * n // buckets, a + 1), n)
        m = 0
        for v in pcm[min(a, n - 1):z]:
            m = max(m, abs(v))
        out[b] = min(m / 32768.0, 1.0)
    return out


def topo(n: int, edges: list) -> Dict[str, Any]:
    """Ordem de execução de um grafo de `n` nós (índices 0..n-1) com conexões [(de, para)]: Kahn com fila FIFO (estável). Devolve
    {"order": [...], "level": [...], "cycle": bool}; `level[i]` = caminho mais longo até o nó (nós do mesmo nível não dependem um do outro).
    Conexões com índice fora do intervalo são ignoradas."""
    if n <= 0:
        return {"order": [], "level": [], "cycle": False}
    good = [(a, b) for a, b in edges if 0 <= a < n and 0 <= b < n]
    lib = _lib4()
    if lib is not None:
        fr, to = array("I", [a for a, _ in good]), array("I", [b for _, b in good])
        order, level = array("I", bytes(4 * n)), array("I", bytes(4 * n))
        k = lib.flow_topo(n, _addr(fr) if good else None, _addr(to) if good else None, len(good), _addr(order), _addr(level))
        if k >= 0:
            return {"order": list(order[:k]), "level": list(level), "cycle": k < n}
    from collections import deque

    indeg = [0] * n
    adj: list = [[] for _ in range(n)]
    for a, b in good:
        adj[a].append(b)
        indeg[b] += 1
    level = [0] * n
    q = deque(i for i in range(n) if indeg[i] == 0)
    order_l: list = []
    while q:
        cur = q.popleft()
        order_l.append(cur)
        for nx in adj[cur]:
            if level[nx] < level[cur] + 1:
                level[nx] = level[cur] + 1
            indeg[nx] -= 1
            if indeg[nx] == 0:
                q.append(nx)
    return {"order": order_l, "level": level, "cycle": len(order_l) < n}
