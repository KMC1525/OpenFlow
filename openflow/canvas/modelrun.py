"""Modelos próprios (v0.82): aplicar a uma imagem um modelo de imagem → imagem feito em PyTorch (TorchScript) ou em TensorFlow/Keras — ampliar a resolução, tirar ruído, colorir, mudar o estilo…

O que roda (e só isto — o OpenFlow não carrega o que não consegue rodar com segurança):
- **Keras** (`.keras`, `.h5` de modelo completo) pelo `keras.saving.load_model(..., safe_mode=True)`: camadas `Lambda` (código dentro do arquivo) são recusadas;
- **SavedModel** do TensorFlow (pasta com `saved_model.pb`) pelo `keras.layers.TFSMLayer` (só inferência);
- **torch.export** (`.pt2`, o sucessor do TorchScript) pelo `torch.export.load(...).module()`;
- **TorchScript** (`.pt`, `.pth`, `.ts`) pelo `torch.jit.load` (o PyTorch já o marca como obsoleto, mas ainda roda). Um `.pt` que é um «pickle» de modelo NÃO é carregado (o pickle executa código do arquivo): o erro diz como exportar para TorchScript.

Onde o modelo está: um caminho no computador, uma pasta, ou um repositório `dono/nome` já baixado (opcionalmente `dono/nome::arquivo`); nada é baixado em silêncio.

Como a imagem entra e sai: a imagem vira um vetor (1, altura, largura, canais) com os valores na faixa que o modelo espera (`0-1`, `0-255` ou `-1-1`); no PyTorch o vetor é transposto para (1, canais, altura, largura) (`layout`). A saída é lida de volta e a faixa dela
é reconhecida sozinha. Imagens grandes: o lado maior é reduzido a `max_side`, ou processadas em blocos (`tile`) — o que importa em computadores com pouca memória.

Limites honestos: só serve para modelos que recebem UMA imagem e devolvem UMA imagem (1, 3 ou 4 canais). Modelos de texto, de vários inputs ou de classificação não rodam aqui. Quem decide se o modelo é bom é o modelo.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from ..providers.base import ProviderError

KERAS_EXT = (".keras", ".h5")
TORCH_EXT = (".pt", ".pth", ".ts", ".torchscript")
EXPORT_EXT = (".pt2",)   # torch.export.save (o sucessor do TorchScript, que o PyTorch já marca como obsoleto)
RANGES = ("0-1", "0-255", "-1-1")
RANGES_OUT = ("auto",) + RANGES
MAX_BYTES_WARN = 1 << 30
_SKIP_H5 = ("tf_model.h5", "model.weights.h5")      # pesos de transformers / só pesos: não são um modelo Keras completo
_PREFER = re.compile(r"(^|[^a-z])(model|best|generator|net|main|final)([^a-z]|$)", re.I)
REPO = re.compile(r"^[\w.-]+/[\w.-]+$")
MAX_SCAN = 4000      # arquivos olhados ao procurar um modelo numa pasta (v0.83: apontar para a pasta pessoal, por engano, varria o disco inteiro e travava o nó)
MAX_DEPTH = 6
_SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".cache"}


def walk(folder: Path):
    """Os arquivos de uma pasta (até `MAX_DEPTH` níveis e `MAX_SCAN` arquivos), sem as pastas ocultas e as de cache — sem seguir atalhos para fora."""
    base = Path(folder)
    seen = 0
    for root, dirs, files in os.walk(base, followlinks=False):
        depth = len(Path(root).relative_to(base).parts)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS) if depth < MAX_DEPTH else []
        for f in sorted(files):
            seen += 1
            if seen > MAX_SCAN:
                return
            yield Path(root) / f


# ----------------------------------------------------------------------------- achar o modelo
def kind_of(path: Path) -> str:
    """«keras», «savedmodel», «torchscript» ou «» (formato que o OpenFlow não roda)."""
    p = Path(path)
    if p.is_dir():
        return "savedmodel" if (p / "saved_model.pb").is_file() else ""
    low = p.name.lower()
    if low in _SKIP_H5:
        return ""
    if low.endswith(KERAS_EXT):
        return "keras"
    if low.endswith(EXPORT_EXT):
        return "torchexport"
    if low.endswith(TORCH_EXT):
        return "torchscript"
    return ""


def framework_of(kind: str) -> str:
    return {"keras": "tf", "savedmodel": "tf", "torchscript": "torch", "torchexport": "torch"}.get(kind, "")


def candidates(folder: Path, framework: str = "") -> List[Path]:
    """Os modelos que dá para rodar dentro de uma pasta (ela mesma, se é um SavedModel), do mais provável ao menos: o que tem «model/best/generator» no nome, depois o maior."""
    folder = Path(folder)
    found: List[Path] = []
    if (folder / "saved_model.pb").is_file():
        found.append(folder)
    for p in walk(folder):
        if p.name == "saved_model.pb" and p.parent != folder:
            found.append(p.parent)
        elif kind_of(p):
            found.append(p)
    if framework in ("tf", "torch"):
        found = [c for c in found if framework_of(kind_of(c)) == framework]

    def size(p: Path) -> int:
        try:
            return sum(f.stat().st_size for f in walk(p)) if p.is_dir() else p.stat().st_size
        except OSError:
            return 0
    return sorted(found, key=lambda p: (0 if _PREFER.search(p.stem if p.is_file() else p.name) else 1, -size(p), str(p)))


def resolve(model: str, framework: str = "", models_dir: Optional[Path] = None) -> Tuple[Path, str]:
    """Do texto do nó ao arquivo/pasta do modelo e o seu «kind». Levanta ProviderError dizendo o que fazer."""
    from . import localmodels as lm

    ref = (model or "").strip()
    if not ref:
        raise ProviderError("Escolha o modelo do nó: o caminho de um arquivo (.keras, .h5, .pt, .pth), de uma pasta SavedModel, ou um repositório dono/nome já baixado.")
    wanted = ""
    if "::" in ref and REPO.match(ref.split("::", 1)[0]):
        ref, wanted = ref.split("::", 1)
    local = Path(os.path.expanduser(ref))
    base: Optional[Path] = None
    if local.exists():
        base = local
    elif models_dir is not None and "/" not in ref and (Path(models_dir) / "custom" / ref).exists():
        base = Path(models_dir) / "custom" / ref
    elif REPO.match(ref):
        try:
            base = lm._snapshot(ref)
        except ProviderError:
            base = None
        if base is None:
            raise ProviderError(f"O modelo «{ref}» ainda não foi baixado. Baixe-o pela barra de pesquisa de modelos (tipo «Modelos próprios») ou pelo botão do nó; nada é baixado em silêncio.")
    if base is None:
        raise ProviderError(f"Não achei o modelo «{ref}» neste computador (confira o caminho). Aceita um arquivo .keras/.h5/.pt/.pth, uma pasta SavedModel ou um repositório dono/nome baixado.")
    if wanted:
        target = base / wanted
        if not target.exists() or ".." in Path(wanted).parts:
            raise ProviderError(f"O arquivo «{wanted}» não está em {ref}.")
        base = target
    kind = kind_of(base)
    if kind:
        if framework in ("tf", "torch") and framework_of(kind) != framework:
            raise ProviderError(f"«{base.name}» é um modelo {'TensorFlow/Keras' if framework_of(kind) == 'tf' else 'PyTorch'}, mas o nó pede {'TensorFlow' if framework == 'tf' else 'PyTorch'}. Deixe «Framework» em Automático.")
        return base, kind
    if base.is_dir():
        found = candidates(base, framework)
        if found:
            return found[0], kind_of(found[0])
        raise ProviderError(f"Não achei, em {base}, um modelo que o OpenFlow rode (.keras, .h5 completo, SavedModel, .pt2 ou TorchScript .pt/.pth). " + _why_not(base))
    raise ProviderError(f"«{base.name}» não é um formato que o OpenFlow rode. Aceita .keras, .h5 (modelo completo), SavedModel (pasta), torch.export (.pt2) e TorchScript (.pt/.pth). " + _why_not(base))


def _why_not(path: Path) -> str:
    low = path.name.lower()
    names = [p.name.lower() for p in path.iterdir()] if path.is_dir() else [low]
    if any(n.endswith(".safetensors") for n in names):
        return "Um .safetensors só tem os PESOS, sem a estrutura do modelo: não dá para rodar sozinho."
    if any(n.endswith((".onnx", ".gguf")) for n in names):
        return "ONNX e GGUF não são rodados por este nó."
    if low in _SKIP_H5 or any(n in _SKIP_H5 for n in names):
        return "Este .h5 é só de pesos (ou de um modelo transformers): o Keras precisa do modelo completo."
    return ""


# ----------------------------------------------------------------------------- carregar
class Runner:
    """Um modelo carregado: `infer` recebe (1, H, W, C) float32 e devolve (1, H', W', C') float32."""

    def __init__(self, kind: str, path: Path, infer: Callable[[Any], Any], fixed_hw: Optional[Tuple[int, int]] = None, channels: int = 3, layout: str = "NHWC", label: str = ""):
        self.kind, self.path, self.infer, self.fixed_hw, self.channels, self.layout, self.label = kind, path, infer, fixed_hw, channels, layout, label


def load_keras(path: Path, kind: str, cpu: bool = False) -> Runner:
    import numpy as np

    try:
        from . import frameworks

        frameworks.import_tensorflow()   # na ordem certa (PyTorch antes): o contrário derruba o programa inteiro
        import keras  # type: ignore
    except ImportError as exc:
        raise ProviderError("Este modelo precisa do TensorFlow/Keras, que não está instalado:  pip install tensorflow  (ou rode: flow libs --extras tensorflow).") from exc
    try:
        if kind == "savedmodel":
            layer = keras.layers.TFSMLayer(str(path), call_endpoint="serving_default")
            fixed, ch = None, 3

            def call(x: Any) -> Any:
                out = layer(x)
                if isinstance(out, dict):
                    out = out[sorted(out)[0]] if "output_0" not in out else out["output_0"]
                return out
        else:
            model = keras.saving.load_model(str(path), compile=False, safe_mode=True)
            shape = getattr(model, "input_shape", None)
            if isinstance(shape, list):
                if len(shape) != 1:
                    raise ProviderError(f"O modelo tem {len(shape)} entradas: este nó só roda modelos com UMA imagem de entrada.")
                shape = shape[0]
            if not (isinstance(shape, (tuple, list)) and len(shape) == 4):
                raise ProviderError(f"A entrada do modelo ({shape}) não é uma imagem (batch, altura, largura, canais).")
            h, w, ch = shape[1], shape[2], shape[3]
            fixed = (int(h), int(w)) if h and w else None
            ch = int(ch) if ch else 3

            def call(x: Any) -> Any:
                return model(x, training=False)
    except ProviderError:
        raise
    except Exception as exc:  # noqa: BLE001 — o Keras explica melhor que qualquer tradução (Lambda recusada pelo safe_mode, versão do arquivo…)
        raise ProviderError(f"O Keras não conseguiu carregar «{Path(path).name}»: {type(exc).__name__}: {str(exc)[:300]}. Arquivos com camadas Lambda são recusados de propósito (executariam código do arquivo).") from None

    def infer(x: Any) -> Any:
        out = call(x)
        return np.asarray(out.numpy() if hasattr(out, "numpy") else out, dtype="float32")
    return Runner(kind, Path(path), infer, fixed, ch, "NHWC", "Keras" if kind == "keras" else "SavedModel")


def _need_torch() -> Any:
    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise ProviderError("Este modelo precisa do PyTorch, que não está instalado:  pip install torch  (ou rode: flow libs --extras media).") from exc
    return torch


def load_torchexport(path: Path, device: str) -> Runner:
    """Um `.pt2` (torch.export). Se o arquivo foi exportado com tamanho fixo, a entrada fica fixa nesse tamanho (descoberto testando um tamanho maior que o do exemplo)."""
    torch = _need_torch()
    import numpy as np

    try:
        ep = torch.export.load(str(path))
        module = ep.module()
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"O PyTorch não conseguiu abrir «{Path(path).name}» como um programa exportado (torch.export): {type(exc).__name__}: {str(exc)[:200]}.") from None
    dev = "cpu"
    if device != "cpu":
        try:
            module = module.to(device)
            dev = device
        except Exception:  # noqa: BLE001 — constantes da placa original dentro do arquivo: roda na CPU
            dev = "cpu"

    def infer(x: Any) -> Any:
        t = torch.from_numpy(np.ascontiguousarray(x)).to(dev)
        with torch.inference_mode():
            out = module(t)
        if isinstance(out, (tuple, list)):
            out = out[0]
        return out.detach().float().cpu().numpy()
    fixed = None
    try:
        ex = ep.example_inputs[0][0]
        n, c, h, w = (int(v) for v in ex.shape)
        try:
            infer(np.zeros((n, c, h + 8, w + 8), dtype="float32"))
        except AssertionError:   # «Guard failed: x.size()[2] == 8»: o tamanho está fixo no arquivo
            fixed = (h, w)
        except Exception:  # noqa: BLE001 — outro motivo: o erro aparece ao rodar de verdade
            pass
    except Exception:  # noqa: BLE001
        pass
    return Runner("torchexport", Path(path), infer, fixed, 3, "NCHW", "torch.export")


def load_torchscript(path: Path, device: str) -> Runner:
    torch = _need_torch()
    import warnings

    import numpy as np

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)   # «torch.jit.load is deprecated»: o aviso não ajuda quem só quer rodar o modelo
            module = torch.jit.load(str(path), map_location=device)
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"«{Path(path).name}» não é um TorchScript que o PyTorch consiga abrir ({type(exc).__name__}: {str(exc)[:200]}). O OpenFlow não carrega «pickles» de modelo (executam código do arquivo): "
                            "exporte com torch.export.save(torch.export.export(modelo, (exemplo,)), 'modelo.pt2') (ou, no TorchScript, torch.jit.trace(modelo, exemplo).save('modelo.pt')).") from None
    module.eval()

    def infer(x: Any) -> Any:
        t = torch.from_numpy(np.ascontiguousarray(x)).to(device)
        with torch.inference_mode():
            out = module(t)
        if isinstance(out, (tuple, list)):
            out = out[0]
        return out.detach().float().cpu().numpy()
    return Runner("torchscript", Path(path), infer, None, 3, "NCHW", "TorchScript")


# ----------------------------------------------------------------------------- imagem ⇄ vetor
def to_array(img: Any, rng: str, channels: int) -> Any:
    """Imagem PIL → vetor (1, H, W, C) float32 na faixa `rng`."""
    import numpy as np

    mode = {1: "L", 3: "RGB", 4: "RGBA"}.get(channels, "RGB")
    arr = np.asarray(img.convert(mode), dtype="float32")
    if arr.ndim == 2:
        arr = arr[:, :, None]
    if rng == "0-1":
        arr = arr / 255.0
    elif rng == "-1-1":
        arr = arr / 127.5 - 1.0
    return arr[None]


def detect_range(out: Any, rng_in: str) -> str:
    """A faixa da saída: o que passa de 1,5 é 0-255; o que fica abaixo de −0,05 é −1…1; o resto é 0-1 (o mais comum). Sem pistas, a da entrada."""
    lo, hi = float(out.min()), float(out.max())
    if hi > 1.5:
        return "0-255"
    if lo < -0.05:
        return "-1-1"
    if hi - lo < 1e-6:
        return rng_in
    return "0-1"


def to_image(arr: Any, rng: str) -> Any:
    """Vetor (1, H, W, C) ou (H, W, C) → imagem PIL (1 canal: cinza; 3: RGB; 4: RGBA)."""
    import numpy as np
    from PIL import Image

    a = np.asarray(arr, dtype="float32")
    if a.ndim == 4:
        a = a[0]
    if a.ndim == 2:
        a = a[:, :, None]
    if a.ndim != 3 or a.shape[2] not in (1, 3, 4):
        raise ProviderError(f"A saída do modelo tem formato {tuple(a.shape)}: este nó só entende imagens de 1, 3 ou 4 canais.")
    r = detect_range(a, "0-1") if rng == "auto" else rng
    if r == "0-1":
        a = a * 255.0
    elif r == "-1-1":
        a = (a + 1.0) * 127.5
    a = np.clip(np.rint(a), 0, 255).astype("uint8")
    return Image.fromarray(a[:, :, 0] if a.shape[2] == 1 else a, {1: "L", 3: "RGB", 4: "RGBA"}[a.shape[2]])


def _pad_multiple(arr: Any, mult: int) -> Tuple[Any, int, int]:
    import numpy as np

    h, w = arr.shape[1], arr.shape[2]
    ph, pw = (-h) % mult, (-w) % mult
    if ph or pw:
        arr = np.pad(arr, ((0, 0), (0, ph), (0, pw), (0, 0)), mode="reflect" if h > 1 and w > 1 and ph < h and pw < w else "edge")
    return arr, h, w


def _run(runner: Runner, arr: Any) -> Any:
    """Uma passada do modelo, com a troca de layout (PyTorch: canais primeiro)."""
    import numpy as np

    x = np.transpose(arr, (0, 3, 1, 2)) if runner.layout == "NCHW" else arr
    out = runner.infer(np.ascontiguousarray(x, dtype="float32"))
    if out.ndim == 3:
        out = out[None]
    if out.ndim == 4 and runner.layout == "NCHW":
        out = np.transpose(out, (0, 2, 3, 1))
    if out.ndim == 2:
        out = out[None, :, :, None]
    return out


def apply(runner: Runner, img: Any, *, rng_in: str = "0-1", rng_out: str = "auto", max_side: int = 1024, tile: int = 0, multiple: int = 1, channels: int = 0, check: Callable[[], None] = lambda: None,
          note: Callable[[str], None] = lambda m: None) -> Any:
    """Roda o modelo na imagem PIL e devolve a imagem PIL. Tamanho fixo do modelo → a imagem é redimensionada para ele; senão o lado maior é limitado a `max_side` e a imagem pode ir em blocos (`tile`)."""
    from PIL import Image

    ch = int(channels or runner.channels or 3)
    src = img
    if runner.fixed_hw:
        fh, fw = runner.fixed_hw
        if src.size != (fw, fh):
            note(f"O modelo só aceita {fw}×{fh}: redimensionei a imagem ({src.size[0]}×{src.size[1]}).")
            src = src.resize((fw, fh), Image.LANCZOS)
        out = _run(runner, to_array(src, rng_in, ch))
        return to_image(out, rng_out)
    w0, h0 = src.size
    if max_side and max(w0, h0) > max_side:
        k = max_side / float(max(w0, h0))
        src = src.resize((max(1, int(w0 * k)), max(1, int(h0 * k))), Image.LANCZOS)
        note(f"Reduzi a imagem de {w0}×{h0} para {src.size[0]}×{src.size[1]} (limite de {max_side} px no lado maior; mude em «Lado maior máximo»).")
    arr = to_array(src, rng_in, ch)
    mult = max(1, int(multiple))
    if tile and tile >= 32 and max(src.size) > tile:
        out = _tiled(runner, arr, int(tile), mult, check, note)
    else:
        padded, h, w = _pad_multiple(arr, mult)
        check()
        out = _run(runner, padded)
        s = out.shape[1] / padded.shape[1]
        out = out[:, :int(round(h * s)), :int(round(w * s)), :]
    return to_image(out, rng_out)


def _tiled(runner: Runner, arr: Any, tile: int, mult: int, check: Callable[[], None], note: Callable[[str], None]) -> Any:
    """O modelo em blocos de `tile` px com 16 px de sobra em volta (a sobra é descartada: some a emenda). A escala (saída/entrada) é medida no primeiro bloco."""
    import numpy as np

    H, W = arr.shape[1], arr.shape[2]
    pad = 16
    ys, xs = list(range(0, H, tile)), list(range(0, W, tile))
    total = len(ys) * len(xs)
    result = None
    scale = 1.0
    done = 0
    for y in ys:
        for x in xs:
            check()
            y0, y1, x0, x1 = max(0, y - pad), min(H, y + tile + pad), max(0, x - pad), min(W, x + tile + pad)
            block, bh, bw = _pad_multiple(arr[:, y0:y1, x0:x1, :], mult)
            out = _run(runner, block)
            if result is None:
                scale = out.shape[1] / block.shape[1]
                result = np.zeros((1, int(round(H * scale)), int(round(W * scale)), out.shape[3]), dtype="float32")
            oy0, ox0 = int(round((y - y0) * scale)), int(round((x - x0) * scale))
            th, tw = min(tile, H - y), min(tile, W - x)
            oh, ow = int(round(th * scale)), int(round(tw * scale))
            piece = out[:, oy0:oy0 + oh, ox0:ox0 + ow, :]
            ry, rx = int(round(y * scale)), int(round(x * scale))
            result[:, ry:ry + piece.shape[1], rx:rx + piece.shape[2], :] = piece
            done += 1
            if total > 1:
                note(f"Bloco {done} de {total}…")
    return result


def fingerprint(path: Path) -> str:
    """Muda quando o modelo muda (tamanho e data do arquivo, ou da pasta toda): faz o nó rodar de novo e o cache de modelos carregar de novo."""
    p = Path(path)
    try:
        if p.is_dir():
            parts = [(str(f.relative_to(p)), f.stat().st_size, int(f.stat().st_mtime)) for f in walk(p)]
            return f"{len(parts)}-{abs(hash(tuple(parts))) & 0xFFFFFFFF}"
        st = p.stat()
        return f"{st.st_size}-{int(st.st_mtime)}"
    except OSError:
        return ""
