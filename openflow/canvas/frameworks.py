"""PyTorch e TensorFlow no OpenFlow (v0.82): o que está instalado, em que aparelhos roda, o que falta para usar a placa de vídeo e o comando certo para instalar.

Por que isto existe: o pip instala o PyTorch «padrão», e o padrão depende do sistema — no Windows é a versão SÓ DE CPU (quem tem placa NVIDIA fica sem GPU sem perceber), no Linux é a CUDA, e placas AMD e Intel
precisam de um índice próprio de pacotes. O TensorFlow também: no Windows nativo ele não usa a placa de vídeo (só no WSL2), e no Linux a GPU vem do extra `[and-cuda]`. Aqui o OpenFlow olha o computador e a instalação
de cada biblioteca e diz, em português claro, se a GPU está sendo usada e o que fazer se não estiver.

Também reconhece, pelos nomes dos arquivos e pelas etiquetas do Hugging Face, em que framework um modelo foi feito (`detect`), para a busca mostrar PyTorch, TensorFlow/Keras, JAX ou ONNX de cada repositório.

Tudo aqui é Python puro e decide só com o que recebe (testável sem as bibliotecas); `torch_info` e `tf_info` é que importam as bibliotecas, uma vez, para perguntar o que elas veem.
"""
from __future__ import annotations

import importlib.metadata as md
import importlib.util
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence

#: índices de pacotes do PyTorch por tipo de placa, do mais novo para o mais antigo (o `flow torch --install` tenta um depois do outro; `OPENFLOW_TORCH_INDEX` força um)
TORCH_INDEXES = {"nvidia": ["cu130", "cu128", "cu126"], "amd": ["rocm7.1", "rocm7.0", "rocm6.4"], "intel": ["xpu"], "cpu": ["cpu"]}
INDEX_URL = "https://download.pytorch.org/whl/{index}"
#: a última versão do Python para a qual o TensorFlow publica pacotes (a 2.21 chega ao 3.13)
TF_MAX_PYTHON = (3, 13)


def dist_version(*names: str) -> str:
    """A versão instalada de um pacote (o primeiro de `names` que existir), lida dos metadados — sem importar a biblioteca. «» se nenhum está instalado."""
    for n in names:
        try:
            return md.version(n)
        except md.PackageNotFoundError:
            continue
        except Exception:  # noqa: BLE001 — metadados quebrados: é como não estar instalado
            continue
    return ""


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# ----------------------------------------------------------------------------- o computador
def vendors() -> List[str]:
    """As marcas de placa de vídeo do computador: «nvidia», «amd», «intel», «apple» (Apple Silicon). Melhor esforço, sem as bibliotecas."""
    from .. import util

    out: List[str] = []
    try:
        if util.gpu_list():
            out.append("nvidia")
    except Exception:  # noqa: BLE001
        pass
    try:
        from .. import native

        for g in native.gpu_info():
            v = str(g.get("vendor") or "")
            if v in ("amd", "intel", "nvidia") and v not in out:
                out.append(v)
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "darwin" and os.uname().machine == "arm64" and "apple" not in out:
        out.append("apple")
    return out


# ----------------------------------------------------------------------------- PyTorch
_INDEX_OK = re.compile(r"^(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._/-]{0,39}$")


def valid_index(index: str) -> bool:
    """O nome de um índice do PyTorch (`cu130`, `rocm7.1`, `nightly/cu130`): letras, números, ponto, traço e barra, sem «..». Vai parar numa URL e num comando que a pessoa copia: nada de espaços ou «;» (v0.84)."""
    return bool(_INDEX_OK.match(index or ""))


def torch_command(vendor: str, system: str, index: str = "") -> str:
    """O comando do pip para instalar o PyTorch certo para a placa `vendor` neste `system` («Linux», «Windows», «Darwin»). Sem placa suportada, a versão só de CPU."""
    exe = "python -m pip install --upgrade torch torchvision"
    if index and not valid_index(index):
        raise ValueError(f"Índice do PyTorch inválido: {index!r} (use algo como cu130, rocm7.1, xpu ou cpu).")
    if system == "Darwin":
        return exe   # no macOS o pacote padrão já traz o MPS (placa da Apple)
    kind = vendor if vendor in TORCH_INDEXES else "cpu"
    if kind == "amd" and system != "Linux":
        kind = "cpu"   # a versão ROCm do PyTorch só existe para Linux
    idx = index or TORCH_INDEXES[kind][0]
    return f"{exe} --index-url {INDEX_URL.format(index=idx)}"


def torch_install(vendor: str, system: str, index: str = "", run: Any = None) -> Dict[str, Any]:
    """Instala o PyTorch certo para a placa `vendor` (`flow torch --install`): tenta os índices do mais novo ao mais antigo até o pip achar um pacote para este Python e este sistema. `run(comando) -> código` é o
    que executa (os testes trocam). Devolve {ok, index, tried, command}."""
    run = run or _pip_run
    kind = vendor if vendor in TORCH_INDEXES else "cpu"
    if kind == "amd" and system != "Linux":
        kind = "cpu"
    forced = index or os.environ.get("OPENFLOW_TORCH_INDEX", "")
    if forced and not valid_index(forced):
        raise ValueError(f"Índice do PyTorch inválido: {forced!r} (use algo como cu130, rocm7.1, xpu ou cpu).")
    candidates = [forced] if forced else ([""] if system == "Darwin" else list(TORCH_INDEXES[kind]))
    tried: List[str] = []
    for idx in candidates:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "torch", "torchvision"] + (["--index-url", INDEX_URL.format(index=idx)] if idx else [])
        tried.append(idx or "pypi")
        if run(cmd) == 0:
            return {"ok": True, "index": idx or "pypi", "tried": tried, "command": " ".join(cmd)}
    return {"ok": False, "index": "", "tried": tried, "command": ""}


def _pip_run(cmd: List[str]) -> int:
    import subprocess

    return subprocess.call(cmd)


def torch_info(probe: bool = True) -> Dict[str, Any]:
    """O que o PyTorch instalado vê: {installed, version, build, cuda, mps, xpu, devices, error?}. `probe=False` só lê a versão instalada (sem importar a biblioteca, que demora)."""
    version = dist_version("torch")
    if not version:
        return {"installed": False}
    info: Dict[str, Any] = {"installed": True, "version": version, "build": "", "cuda": False, "mps": False, "xpu": False, "devices": []}
    if not probe:
        return info
    try:
        import torch  # type: ignore
    except Exception as exc:  # noqa: BLE001 — instalação quebrada (falta uma biblioteca da CUDA, DLL…): é uma informação útil, não uma exceção
        info["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        return info
    info["version"] = str(getattr(torch, "__version__", version))
    cuda_built = str(getattr(getattr(torch, "version", None), "cuda", None) or "")
    hip_built = str(getattr(getattr(torch, "version", None), "hip", None) or "")
    info["build"] = f"ROCm {hip_built}" if hip_built else (f"CUDA {cuda_built}" if cuda_built else "CPU")
    devices: List[Dict[str, Any]] = []
    try:
        if torch.cuda.is_available():
            info["cuda"] = True
            for i in range(torch.cuda.device_count()):
                p = torch.cuda.get_device_properties(i)
                devices.append({"kind": "rocm" if hip_built else "cuda", "index": i, "name": str(p.name), "vram": int(p.total_memory), "capability": f"{p.major}.{p.minor}"})
    except Exception:  # noqa: BLE001
        pass
    try:
        info["mps"] = bool(getattr(getattr(torch, "backends", None), "mps", None) and torch.backends.mps.is_available())
        if info["mps"]:
            devices.append({"kind": "mps", "index": 0, "name": "Apple GPU (MPS)", "vram": 0, "capability": ""})
    except Exception:  # noqa: BLE001
        pass
    try:
        xpu = getattr(torch, "xpu", None)
        if xpu is not None and xpu.is_available():
            info["xpu"] = True
            for i in range(xpu.device_count()):
                devices.append({"kind": "xpu", "index": i, "name": str(xpu.get_device_name(i)), "vram": int(getattr(xpu.get_device_properties(i), "total_memory", 0) or 0), "capability": ""})
    except Exception:  # noqa: BLE001
        pass
    info["devices"] = devices
    return info


def quick_torch_hint(version: str, gpu_vendors: Sequence[str], system: str) -> Optional[Dict[str, str]]:
    """O aviso barato (sem importar o PyTorch) para o fim de `flow libs`/`flow update`: no Windows o pacote do PyPI é a versão SÓ DE CPU; se o computador tem uma placa NVIDIA e o PyTorch instalado não vem de um
    índice de placa («2.15.0+cu130»), diz o comando. None se não há o que avisar."""
    if not version or system != "Windows" or "nvidia" not in gpu_vendors:
        return None
    local = version.split("+", 1)[1].lower() if "+" in version else ""
    if local and not local.startswith("cpu"):
        return None
    return _a("warn", f"Há uma placa NVIDIA, mas o PyTorch {version} do PyPI no Windows é a versão só de CPU: os modelos locais ficam muito mais lentos. Para usar a placa:  flow torch --install",
              f"There is an NVIDIA card, but PyTorch {version} from PyPI on Windows is the CPU-only build: local models get much slower. To use the card:  flow torch --install", torch_command("nvidia", system))


def best_device(info: Dict[str, Any]) -> str:
    """O aparelho que o OpenFlow usa com este PyTorch: «cuda» (NVIDIA ou AMD/ROCm), «xpu» (Intel), «mps» (Apple) ou «cpu»."""
    if info.get("cuda"):
        return "cuda"
    if info.get("xpu"):
        return "xpu"
    if info.get("mps"):
        return "mps"
    return "cpu"


def _a(level: str, text: str, en: str, command: str = "") -> Dict[str, str]:
    """Um conselho: `text` em português, `text_en` em inglês (o programa e o terminal escolhem pelo idioma), `command` opcional para copiar."""
    d = {"level": level, "text": text, "text_en": en}
    if command:
        d["command"] = command
    return d


def torch_advice(info: Dict[str, Any], gpu_vendors: Sequence[str], system: str, machine: str = "") -> List[Dict[str, str]]:
    """O que fazer com o PyTorch: [{level: ok|info|warn|error, text, text_en, command?}]. Não usa a placa de vídeo que o computador tem? Diz por quê e o comando certo."""
    vend = next((v for v in gpu_vendors if v in ("nvidia", "amd", "intel")), "cpu")
    if not info.get("installed"):
        return [_a("warn", "O PyTorch não está instalado: os modelos locais de imagem, vídeo, som e voz precisam dele.", "PyTorch is not installed: local image, video, sound and voice models need it.", torch_command(vend, system))]
    if info.get("error"):
        return [_a("error", f"O PyTorch está instalado ({info.get('version', '?')}), mas não carrega: {info['error']}. Reinstale-o.", f"PyTorch is installed ({info.get('version', '?')}) but does not load: {info['error']}. Reinstall it.", torch_command(vend, system))]
    dev = best_device(info)
    if dev != "cpu":
        names = ", ".join(d["name"] for d in info.get("devices", [])) or dev
        return [_a("ok", f"O PyTorch {info.get('version', '')} ({info.get('build', '')}) usa a placa de vídeo: {names}.", f"PyTorch {info.get('version', '')} ({info.get('build', '')}) is using the graphics card: {names}.")]
    build = str(info.get("build") or "")
    out: List[Dict[str, str]] = []
    for v in gpu_vendors:
        if v == "nvidia" and system != "Darwin":
            why, why_en = (("é a versão só de CPU", "it is the CPU-only build") if build == "CPU" else (f"é a {build}, mas não achou a placa (driver da NVIDIA desatualizado ou instalação incompleta)", f"it is the {build} build but did not find the card (outdated NVIDIA driver or incomplete install)"))
            out.append(_a("warn", f"Há uma placa NVIDIA neste computador, mas o PyTorch roda na CPU: {why}. Os modelos locais ficam muito mais lentos.", f"There is an NVIDIA card in this computer, but PyTorch runs on the CPU: {why_en}. Local models get much slower.", torch_command("nvidia", system)))
        elif v == "amd":
            if system == "Linux":
                out.append(_a("warn", "Há uma placa AMD, mas o PyTorch instalado não a usa (a versão ROCm só existe para Linux e placas compatíveis).", "There is an AMD card, but the installed PyTorch does not use it (the ROCm build only exists for Linux and compatible cards).", torch_command("amd", system)))
            else:
                out.append(_a("info", "Há uma placa AMD, mas o PyTorch oficial para AMD (ROCm) só existe para Linux. Aqui use o provedor «GGUF local» (stable-diffusion.cpp com Vulkan) ou o WSL2.", "There is an AMD card, but the official PyTorch for AMD (ROCm) only exists for Linux. Here use the “local GGUF” provider (stable-diffusion.cpp with Vulkan) or WSL2."))
        elif v == "intel" and system != "Darwin":
            out.append(_a("info", "Há uma placa Intel: o PyTorch pode usá-la (aparelho «xpu») com o pacote do índice XPU.", "There is an Intel card: PyTorch can use it (the “xpu” device) with the XPU index package.", torch_command("intel", system)))
        elif v == "apple" and build != "CPU":
            out.append(_a("info", "Apple Silicon: o PyTorch deveria usar o MPS; confira se o Python é o nativo (arm64), não o do Rosetta.", "Apple Silicon: PyTorch should use MPS; check that Python is the native one (arm64), not the Rosetta one."))
    return out or [_a("ok", f"O PyTorch {info.get('version', '')} roda na CPU (este computador não tem uma placa de vídeo que ele possa usar).", f"PyTorch {info.get('version', '')} runs on the CPU (this computer has no graphics card it can use).")]


# ----------------------------------------------------------------------------- TensorFlow
def import_tensorflow() -> Any:
    """Importa o TensorFlow SEM derrubar o OpenFlow. O PyTorch e o TensorFlow trazem, cada um, uma cópia do LLVM; se o `torch.export` (ou o `torch._dynamo`) for importado DEPOIS do TensorFlow, o processo inteiro fecha com
    «LLVM ERROR: inconsistency in registered CommandLine options» — e o OpenFlow roda os dois na mesma janela. A ordem que funciona (testada com o PyTorch 2.15 e o TensorFlow 2.21): o PyTorch e esses dois módulos primeiro.
    Todo `import tensorflow` do OpenFlow passa por aqui."""
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")   # sem as mensagens de aviso do TensorFlow no terminal
    if has_module("torch"):
        for mod in ("torch", "torch.export", "torch._dynamo"):
            try:
                importlib.import_module(mod)
            except Exception:  # noqa: BLE001 — um PyTorch quebrado não impede o TensorFlow (que é outra biblioteca)
                break
    import tensorflow as tf  # type: ignore

    return tf


def tf_info(probe: bool = True) -> Dict[str, Any]:
    """O que o TensorFlow instalado vê: {installed, version, keras, backend, gpus, built_with_cuda, error?}."""
    version = dist_version("tensorflow", "tensorflow-cpu", "tensorflow-gpu", "tensorflow-macos", "tf-nightly")
    keras = dist_version("keras")
    if not version:
        return {"installed": False, "keras": keras}
    info: Dict[str, Any] = {"installed": True, "version": version, "keras": keras, "backend": "", "gpus": [], "built_with_cuda": False, "probed": bool(probe)}
    if not probe:
        return info
    try:
        tf = import_tensorflow()
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        return info
    info["version"] = str(getattr(tf, "__version__", version))
    try:
        info["built_with_cuda"] = bool(tf.test.is_built_with_cuda())
    except Exception:  # noqa: BLE001
        pass
    try:
        info["gpus"] = [{"name": str(getattr(d, "name", "")), "details": _tf_gpu_details(tf, d)} for d in tf.config.list_physical_devices("GPU")]
    except Exception:  # noqa: BLE001
        pass
    try:
        import keras  # type: ignore

        info["keras"] = str(getattr(keras, "__version__", keras if isinstance(keras, str) else ""))
        info["backend"] = str(keras.backend.backend())
    except Exception:  # noqa: BLE001
        pass
    return info


def _tf_gpu_details(tf: Any, device: Any) -> str:
    try:
        d = tf.config.experimental.get_device_details(device)
        return str(d.get("device_name") or "")
    except Exception:  # noqa: BLE001
        return ""


def tf_command(system: str, nvidia: bool) -> str:
    base = "python -m pip install --upgrade"
    if nvidia and system == "Linux":
        return f'{base} "tensorflow[and-cuda]"'
    return f"{base} tensorflow"


def tf_advice(info: Dict[str, Any], gpu_vendors: Sequence[str], system: str, py: Sequence[int] = ()) -> List[Dict[str, str]]:
    """O que fazer com o TensorFlow: [{level, text, text_en, command?}]. Só avisa de GPU quando o computador tem uma placa que ele poderia usar."""
    py = tuple(py) or tuple(sys.version_info[:2])
    nvidia = "nvidia" in gpu_vendors
    cmd = tf_command(system, nvidia)
    if not info.get("installed"):
        if py > TF_MAX_PYTHON:
            return [_a("info", f"O TensorFlow ainda não publica pacotes para o Python {py[0]}.{py[1]} (o último é o {TF_MAX_PYTHON[0]}.{TF_MAX_PYTHON[1]}). Modelos Keras 3 (.keras) rodam com o PyTorch como motor: pip install keras (e KERAS_BACKEND=torch).",
                       f"TensorFlow does not publish packages for Python {py[0]}.{py[1]} yet (the latest is {TF_MAX_PYTHON[0]}.{TF_MAX_PYTHON[1]}). Keras 3 models (.keras) run with PyTorch as the engine: pip install keras (and KERAS_BACKEND=torch).")]
        return [_a("info", "O TensorFlow não está instalado: o OpenFlow não precisa dele (os modelos locais usam o PyTorch); instale só se você usa o TensorFlow neste Python.", "TensorFlow is not installed: OpenFlow does not need it (local models use PyTorch); install it only if you use TensorFlow in this Python.", cmd)]
    if info.get("error"):
        return [_a("error", f"O TensorFlow está instalado ({info.get('version', '?')}), mas não carrega: {info['error']}. Reinstale-o.", f"TensorFlow is installed ({info.get('version', '?')}) but does not load: {info['error']}. Reinstall it.", cmd)]
    if info.get("probed") is False:   # v0.83: carregar o TensorFlow custa ≈ 400 MB de RAM e alguns segundos: só quando a pessoa pede
        return [_a("info", f"O TensorFlow {info.get('version', '')} está instalado. Para saber se ele usa a placa de vídeo é preciso carregá-lo (≈ 400 MB de RAM): use «Verificar o TensorFlow».", f"TensorFlow {info.get('version', '')} is installed. Knowing whether it uses the graphics card means loading it (≈ 400 MB of RAM): use “Check TensorFlow”.")]
    if info.get("gpus"):
        names = ", ".join(g["name"] for g in info["gpus"])
        return [_a("ok", f"O TensorFlow {info.get('version', '')} usa a placa de vídeo: {names}.", f"TensorFlow {info.get('version', '')} is using the graphics card: {names}.")]
    if nvidia and system == "Windows":
        return [_a("info", "O TensorFlow 2.11 ou mais novo não usa a placa de vídeo no Windows nativo (só no WSL2). Aqui ele roda na CPU.", "TensorFlow 2.11 or newer does not use the graphics card on native Windows (only on WSL2). Here it runs on the CPU.")]
    if nvidia and system == "Linux":
        return [_a("warn", "Há uma placa NVIDIA, mas o TensorFlow roda na CPU: instale a versão com a CUDA.", "There is an NVIDIA card, but TensorFlow runs on the CPU: install the CUDA build.", cmd)]
    return [_a("ok", f"O TensorFlow {info.get('version', '')} roda na CPU.", f"TensorFlow {info.get('version', '')} runs on the CPU.")]


# ----------------------------------------------------------------------------- tudo junto
def report(probe: bool = True, probe_tf: bool = True) -> Dict[str, Any]:
    """O retrato do PyTorch e do TensorFlow neste computador, com os conselhos: {system, python, gpus, torch, tensorflow, advice: {torch, tensorflow}}. `probe_tf=False` (o que a tela faz) só carrega o
    TensorFlow se ele já estiver carregado: importá-lo custa ≈ 400 MB de RAM e vários segundos, e quem só abriu as Configurações não deve pagar isso (v0.83)."""
    import platform

    system = platform.system() or sys.platform
    gv = vendors()
    t, f = torch_info(probe), tf_info(probe and (probe_tf or "tensorflow" in sys.modules))
    t["device"] = best_device(t) if t.get("installed") and not t.get("error") else ""
    return {"system": system, "machine": platform.machine(), "python": platform.python_version(), "gpu_vendors": gv, "torch": t, "tensorflow": f,
            "advice": {"torch": torch_advice(t, gv, system, platform.machine()), "tensorflow": tf_advice(f, gv, system)}}


# ----------------------------------------------------------------------------- em que framework um modelo foi feito
_TF_FILE = re.compile(r"(^|/)(tf_model\.h5|saved_model\.pb|keras_metadata\.pb|[^/]+\.keras|model\.weights\.h5)$", re.I)
_TORCH_FILE = re.compile(r"\.(safetensors|bin|pt|pth|ckpt)$", re.I)
_TAG_FRAMEWORK = {"pytorch": "pytorch", "torch": "pytorch", "safetensors": "pytorch", "tf": "tensorflow", "tensorflow": "tensorflow", "tf-keras": "tensorflow", "keras": "tensorflow", "saved_model": "tensorflow",
                  "jax": "jax", "flax": "jax", "onnx": "onnx", "gguf": "gguf"}
LABELS = {"pytorch": "PyTorch", "tensorflow": "TensorFlow", "jax": "JAX", "onnx": "ONNX", "gguf": "GGUF"}


def detect(files: Sequence[str] = (), tags: Sequence[str] = (), library: str = "") -> List[str]:
    """Os frameworks de um modelo, pelos NOMES dos arquivos e pelas ETIQUETAS (tags e `library_name`) do Hugging Face: [«pytorch», «tensorflow», «jax», «onnx», «gguf»], nessa ordem. Vazio = não deu para saber."""
    found = set()
    for f in files:
        n = str(f)
        low = n.lower()
        if _TF_FILE.search(n):
            found.add("tensorflow")
        elif low.endswith(".msgpack"):
            found.add("jax")
        elif low.endswith((".onnx", ".onnx_data")):
            found.add("onnx")
        elif low.endswith(".gguf"):
            found.add("gguf")
        elif _TORCH_FILE.search(n):
            found.add("pytorch")
    for t in list(tags) + [library]:
        fw = _TAG_FRAMEWORK.get(str(t or "").strip().lower())
        if fw:
            found.add(fw)
    return [k for k in LABELS if k in found]
