"""Modelos locais do Canvas (diffusers/transformers): o usuário escolhe a precisão (quantização) ANTES de qualquer download.

Nada é baixado em silêncio: o provedor "Hugging Face local" só carrega modelos que o usuário baixou aqui, escolhendo a precisão:

* **fp32** — original, maior arquivo e mais memória; é o que funciona em CPU;
* **fp16** — metade do tamanho e da memória, mais rápido em placa de vídeo (GPU); em CPU pode ser lento ou não funcionar;
* **bf16** — como o fp16, mas com a faixa de valores do fp32; exige GPU/CPU recentes.

Só os arquivos da precisão escolhida são baixados (variantes `.fp16.safetensors` quando o repositório as tem). A escolha fica em
`settings.media.precision[modelo]`.
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import urllib.parse

import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..providers.base import ProviderError

PRECISIONS = ("fp32", "fp16", "bf16")
LABELS = {"fp32": "fp32 · original", "fp16": "fp16 · metade do tamanho", "bf16": "bf16 · metade do tamanho"}
HINTS = {"fp32": "Maior e mais lento, mas funciona em qualquer computador (inclusive só com CPU).",
         "fp16": "Metade do tamanho e da memória; ideal com placa de vídeo (GPU). Em CPU pode ser lento ou falhar.",
         "bf16": "Como o fp16, com a faixa de valores do fp32; pede um processador/GPU recente."}
WEIGHT_EXT = (".safetensors", ".bin", ".pt", ".pth", ".ckpt", ".msgpack", ".h5", ".onnx", ".onnx_data", ".tflite", ".mlmodel", ".gguf")
SKIP_EXT = (".md", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".wav", ".mp3", ".flac")
MARKER = "flow_precision.txt"
REPO_OK = re.compile(r"^[\w.-]+/[\w.-]+$")


def _hub() -> Any:
    try:
        import huggingface_hub  # type: ignore

        return huggingface_hub
    except ImportError:
        raise ProviderError('Modelos locais precisam das bibliotecas opcionais (huggingface_hub). Instale com:  pip install "openflow[media]"  (ou rode: flow libs)') from None


def select_files(files: List[Dict[str, Any]], precision: str) -> List[Dict[str, Any]]:
    """Quais arquivos do repositório baixar para a precisão escolhida (pesos duplicados em outros formatos/variantes ficam de fora)."""
    names = [f["name"] for f in files]
    has_st = any(n.endswith(".safetensors") for n in names)
    diffusers_layout = "model_index.json" in names or "modular_model_index.json" in names   # o FLUX.3 usa o pipeline modular
    low = precision in ("fp16", "bf16")

    def is_variant(n: str) -> bool:
        return ".fp16." in n or ".bf16." in n

    def twin(n: str) -> str:  # nome da variante fp16 de um peso
        stem, dot, ext = n.rpartition(".")
        return f"{stem}.fp16.{ext}" if dot else n

    out = []
    for f in files:
        n = f["name"]
        low_n = n.lower()
        if n.startswith(".") or low_n.endswith(SKIP_EXT):
            continue
        if diffusers_layout and n.startswith("variants/"):
            continue  # versões quantizadas alternativas (fp8, nvfp4…), que o diffusers comum não lê: baixar também dobraria o tamanho
        if not low_n.endswith(WEIGHT_EXT):
            out.append(f)
            continue
        if low_n.rsplit("/", 1)[-1] == "audiovae.pth":
            out.append(f)   # VoxCPM: o codec de áudio é um .pth (não há versão safetensors dele): sem ele o modelo não fala
            continue
        if has_st and not low_n.endswith((".safetensors", ".onnx_data")) and not low_n.endswith(".gguf"):
            continue  # só safetensors quando existe
        if low_n.endswith((".onnx", ".onnx_data", ".tflite", ".mlmodel")):
            continue
        if diffusers_layout and "/" not in n:
            continue  # checkpoint único na raiz repete os pesos das pastas (unet/, vae/…)
        if is_variant(n):
            if low:
                out.append(f)  # fp16 e bf16 usam a variante fp16 (bf16 só muda o tipo ao carregar)
            continue
        if low and twin(n) in names:
            continue  # existe a variante fp16 deste peso: baixa só ela
        out.append(f)
    return out


def _siblings(model: str, token: str) -> List[Dict[str, Any]]:
    info = _hub().HfApi().model_info(model, files_metadata=True, token=token or None)
    return [{"name": s.rfilename, "size": int(getattr(s, "size", 0) or 0)} for s in (info.siblings or [])]


def options(model: str, token: str = "", gpu: bool = False) -> Dict[str, Any]:
    """As precisões possíveis para um modelo, com o tamanho do download de cada uma e a recomendada para este computador."""
    files = _siblings(model, token)
    out = []
    for p in PRECISIONS:
        chosen = select_files(files, p)
        out.append({"id": p, "label": LABELS[p], "hint": HINTS[p], "size": sum(f["size"] for f in chosen), "files": len(chosen)})
    rec = "fp16" if gpu else "fp32"
    for o in out:
        o["recommended"] = o["id"] == rec
    return {"model": model, "options": out, "recommended": rec}


# Quantizações menores: repositórios de terceiros derivados do modelo (a própria Hugging Face liga cada um ao original). A precisão fp32/fp16/bf16 do modelo original
# só muda o tipo dos números; estes são pesos já comprimidos (8 ou 4 bits), com downloads bem menores.
def _quant_kind(mid: str, tags: List[str]) -> Dict[str, Any]:
    key = " ".join([mid.lower()] + [str(t).lower() for t in tags])
    def has(*w: str) -> bool:
        return any(x in key for x in w)
    if has("gguf"):
        return {"kind": "GGUF", "loadable": False, "note": "formato GGUF (llama.cpp / stable-diffusion.cpp): use o provedor GGUF em Configuração → Mídia"}
    if has("awq", "gptq", "mlx", "onnx", "openvino", "coreml", "exl2"):
        return {"kind": "outro", "loadable": False, "note": "formato que o carregador embutido não lê"}
    if has("nf4", "4bit", "4-bit", "int4", "bnb-4"):
        return {"kind": "int4", "loadable": True, "note": "4 bits · pede a biblioteca bitsandbytes (placa NVIDIA)"}
    if has("8bit", "8-bit", "int8", "bnb-8"):
        return {"kind": "int8", "loadable": True, "note": "8 bits · pede a biblioteca bitsandbytes (placa NVIDIA)"}
    if has("fp8", "float8"):
        return {"kind": "fp8", "loadable": True, "note": "fp8 · metade do fp16; exige GPU recente"}
    return {"kind": "outro", "loadable": True, "note": "versão comprimida da comunidade"}


def quantized_variants(model: str, token: str = "", limit: int = 12) -> List[Dict[str, Any]]:
    """Versões menores (quantizadas) do modelo feitas pela comunidade, das mais baixadas para as menos."""
    from ..providers import http

    q = urllib.parse.urlencode([("filter", f"base_model:quantized:{model}"), ("sort", "downloads"), ("direction", "-1"), ("limit", str(limit)),
                                ("expand[]", "downloads"), ("expand[]", "usedStorage"), ("expand[]", "tags"), ("expand[]", "library_name")])
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = http.get_json(f"https://huggingface.co/api/models?{q}", headers, timeout=20)
    out = []
    for m in data if isinstance(data, list) else []:
        mid = m.get("id") or m.get("modelId")
        if not isinstance(mid, str) or not REPO_OK.match(mid):
            continue
        info = _quant_kind(mid, m.get("tags") or [])
        out.append({"id": mid, "size": int(m.get("usedStorage") or 0), "downloads": int(m.get("downloads") or 0), **info})
    out.sort(key=lambda x: (not x["loadable"], x["size"] or 1 << 60))  # as que o OpenFlow carrega primeiro, das menores para as maiores
    return out


def _snapshot(model: str) -> Optional[Path]:
    try:
        return Path(_hub().snapshot_download(model, local_files_only=True))
    except Exception:  # noqa: BLE001 — não está no cache
        return None


def downloaded_precision(model: str) -> str:
    """Precisão com que o modelo foi baixado ("" se não foi baixado pelo OpenFlow)."""
    try:
        snap = _snapshot(model)
    except ProviderError:
        return ""
    marker = snap / MARKER if snap else None
    if marker and marker.is_file():
        p = marker.read_text(encoding="utf-8").strip()
        return p if p in PRECISIONS else ""
    return ""


def has_fp16_variant(model: str) -> bool:
    snap = _snapshot(model)
    return bool(snap and any(".fp16." in p.name for p in snap.rglob("*") if p.is_file() or p.is_symlink()))


def _incomplete_bytes(model: str) -> int:
    try:
        cache = Path(_hub().constants.HF_HUB_CACHE) / ("models--" + model.replace("/", "--")) / "blobs"
        return sum(p.stat().st_size for p in cache.glob("*.incomplete"))
    except Exception:  # noqa: BLE001
        return 0


def _gated_or(exc: Exception, model: str, token: str) -> ProviderError:
    """Modelos «gated» (FLUX.3 klein…) só baixam depois de aceitar a licença no site, com o token da conta: explica isso em vez de mostrar o erro cru do Hub."""
    name = exc.__class__.__name__
    code = getattr(getattr(exc, "response", None), "status_code", 0)
    if "Gated" in name or code in (401, 403) or re.search(r"\b(401|403)\b|gated|restricted|access to model", str(exc), re.I):
        return ProviderError(f"O modelo «{model}» é restrito: abra https://huggingface.co/{model}, aceite a licença com a sua conta e coloque o token (com permissão de leitura) em Configuração → Hugging Face"
                             + ("" if token else " — nenhum token está configurado agora") + ". Depois baixe de novo.", status=403)
    return ProviderError(f"Não foi possível baixar «{model}»: {exc}")


def _cache_dir(hub: Any) -> Path:
    """Onde o huggingface_hub guarda os modelos baixados (a pasta que enche)."""
    try:
        return Path(hub.constants.HF_HUB_CACHE)
    except Exception:  # noqa: BLE001
        base = os.environ.get("HF_HUB_CACHE") or os.path.join(os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface"), "hub")
        return Path(base)


def check_space(hub: Any, model: str, files: List[Dict[str, Any]]) -> None:
    """Confere se há espaço em disco para o que falta baixar (v0.78). Sem isso, um disco cheio só aparecia no meio do download — depois de gastar minutos e rede — como «No space left on device» cru."""
    pending = 0
    for f in files:
        try:
            cached = hub.try_to_load_from_cache(model, f["name"])
        except Exception:  # noqa: BLE001
            cached = None
        if not (isinstance(cached, (str, os.PathLike)) and Path(cached).is_file()):
            pending += int(f.get("size") or 0)
    if not pending:
        return
    folder = _cache_dir(hub)
    probe = folder
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return
    if free < pending * 1.02 + (200 << 20):
        gb = 1024 ** 3
        raise ProviderError(f"Sem espaço em disco para «{model}»: faltam baixar {pending / gb:.1f} GB e há {free / gb:.1f} GB livres em {folder}. Libere espaço, escolha uma precisão menor (fp16/bf16) "
                            "ou mude a pasta dos modelos em Configuração → Armazenamento.", status=507)


@contextlib.contextmanager
def cancellable(hub: Any, cancelled: Callable[[], bool]) -> Any:
    """Faz o «Cancelar» valer no MEIO de um arquivo grande (v0.78): antes só era lido entre um arquivo e outro, e cancelar um .safetensors de 5 GB esperava ele terminar. A barra de progresso do huggingface_hub
    (`file_download.tqdm`) passa a levantar o cancelamento a cada pedaço recebido; o arquivo parcial fica em .incomplete e o próximo download continua dele. Se a versão do hub não tem essa barra, nada muda."""
    fd = getattr(hub, "file_download", None)
    base = getattr(fd, "tqdm", None)
    if fd is None or base is None:
        yield
        return

    class CancellableBar(base):  # type: ignore[misc, valid-type]
        def update(self, n: Any = 1) -> Any:
            if cancelled():
                raise ProviderError("cancelado")
            return super().update(n)
    fd.tqdm = CancellableBar
    try:
        yield
    finally:
        fd.tqdm = base


def download(model: str, precision: str, token: str = "", progress: Optional[Callable[[int, int], None]] = None, cancelled: Callable[[], bool] = lambda: False) -> Path:
    """Baixa os arquivos da precisão escolhida, um a um (dá para cancelar entre arquivos), e registra a escolha."""
    if precision not in PRECISIONS:
        raise ProviderError("Escolha a precisão (quantização) do modelo antes de baixar.")
    hub = _hub()
    try:
        files = select_files(_siblings(model, token), precision)
    except Exception as exc:  # noqa: BLE001
        raise _gated_or(exc, model, token) from None
    if not files:
        raise ProviderError("Nenhum arquivo utilizável neste repositório.")
    check_space(hub, model, files)
    total = sum(f["size"] for f in files)
    done, snap = 0, None
    for f in files:
        if cancelled():
            raise ProviderError("cancelado")
        stop = threading.Event()

        def poll(base: int = done) -> None:
            while not stop.wait(0.5):
                if progress:
                    progress(base + _incomplete_bytes(model), total)

        t = threading.Thread(target=poll, daemon=True)
        t.start()
        try:
            with cancellable(hub, cancelled):
                snap = Path(hub.hf_hub_download(model, f["name"], token=token or None)).parents[len(Path(f["name"]).parts) - 1]
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _gated_or(exc, model, token) from None
        finally:
            stop.set()
            t.join(1)
        done += f["size"]
        if progress:
            progress(done, total)
    if snap is None:
        raise ProviderError("O download não gerou arquivos.")
    (snap / MARKER).write_text(precision, encoding="utf-8")
    return snap


def fetch_files(model: str, names: List[str], token: str = "") -> List[Path]:
    """Baixa só os arquivos `names` de um modelo que já está baixado (os que faltaram: ex. o codec de áudio do VoxCPM que os downloads antes da v0.71 pulavam). Devolve os caminhos."""
    hub = _hub()
    out = []
    for n in names:
        try:
            out.append(Path(hub.hf_hub_download(model, n, token=token or None)))
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _gated_or(exc, model, token) from None
    return out


def torch_dtype(precision: str) -> Any:
    import torch  # type: ignore

    return {"fp32": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}[precision]
