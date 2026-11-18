"""LTX-2, LTX-2.3 e LTX-2.5 (Lightricks) pelo `diffusers` (v0.22): vídeo **com áudio** a partir dos GGUF da Unsloth (ou de um repositório no formato diffusers).

Os GGUF da Unsloth (`unsloth/LTX-2*-GGUF`) trazem só o transformador («denoiser») no formato do ComfyUI. O OpenFlow o carrega com `LTX2VideoTransformer3DModel.from_single_file(…, GGUFQuantizationConfig)`
e monta o resto do pipeline (codificador de texto Gemma, VAEs, vocoder, conectores) a partir do repositório diffusers da Lightricks (`BASES`), como na documentação do diffusers:
`LTX2Pipeline` (texto → vídeo) ou `LTX2ImageToVideoPipeline` (imagem inicial) e `encode_video(…, audio=…)` para o MP4 com a trilha sonora.

Os componentes (≈ 25 GB, o codificador de texto é o maior) **nunca baixam em silêncio**: faltando, o nó pede o clique no botão que os baixa (`download_components`).
Esta rota exige `diffusers` com o LTX-2 (≥ 0.43), `torch`, `gguf` e `av` (`pip install "openflow[media]"`; o `flow update` instala).
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..providers.base import ProviderError

#: repositório diffusers de onde vêm os componentes de cada versão (o LTX-2.3 não tem repositório diffusers próprio: usa o do 2.5, que é do mesmo porte de 22B — **não confirmado**)
BASES = {"2": "Lightricks/LTX-2", "2.3": "Lightricks/LTX-2.5-Diffusers", "2.5": "Lightricks/LTX-2.5-Diffusers"}
#: (passos, CFG) — o «dev» é o modelo completo; o «distilled» é o destilado (8 passos, sem CFG), segundo os cartões
RUN = {"dev": (30, 3.0), "distilled": (8, 1.0)}
#: v0.86: o modelo «distilled» foi treinado com ESTAS 8 etapas de ruído (receita do diffusers: `sigmas=DISTILLED_SIGMA_VALUES, num_inference_steps=8, guidance_scale=1.0`); sem elas o diffusers usa uma
#: escala linear (1,0 → 0,125) e o vídeo (principalmente a partir de uma imagem) sai borrado e sem seguir a imagem inicial
DISTILLED_SIGMAS = [1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875]
NEGATIVE = "worst quality, inconsistent motion, blurry, jittery, distorted"   # o do exemplo da documentação do diffusers
FPS = 24
#: o que NÃO se baixa do repositório diffusers: o transformador (vem do GGUF), arquivos soltos de mídia e os pesos duplicados do codificador de texto
IGNORE = ["transformer/*", "transformer_full/*", "text_encoder/diffusion_pytorch_model*", "*.mp4", "*.png", "*.webp", "*.jpg", "*.md", "ltx-*.safetensors", "*.gitattributes"]


def parse(name: str) -> Optional[Dict[str, str]]:
    """{version: «2»|«2.3»|«2.5», variant: «dev»|«distilled»} de um arquivo `ltx-2.5-22b-distilled-UD-Q4_K_XL.gguf` (None se não é do LTX-2.x)."""
    base = Path(name).name
    m = re.search(r"ltx[-_. ]?2(?:[._-]?(\d))?(?![\d])", base, re.I)
    if not m:
        return None
    ver = "2" + ("." + m.group(1) if m.group(1) else "")
    if ver not in BASES:
        ver = "2.5"
    return {"version": ver, "variant": "distilled" if re.search(r"distil", base, re.I) else "dev", "base": BASES[ver]}


def size_for(aspect: str, long_side: int = 0) -> Tuple[int, int]:
    """Largura × altura em múltiplos de 32 (o LTX-2 exige), a partir da proporção e do lado maior (padrão 768)."""
    try:
        a, b = [float(x) for x in str(aspect).split(":")]
    except ValueError:
        a, b = 16.0, 9.0
    long = long_side if long_side >= 480 else 768
    w, h = (long, long * b / a) if a >= b else (long * a / b, long)
    return max(32, int(round(w / 32)) * 32), max(32, int(round(h / 32)) * 32)


def frames_for(duration: float, fps: int = FPS, max_seconds: float = 20.0) -> int:
    """Número de quadros: múltiplo de 8 + 1 (regra do LTX-2): 5 s a 24 fps = 121."""
    secs = max(1.0, min(float(duration or 5), max_seconds))
    return 8 * max(1, int(round(secs * fps / 8))) + 1


def _hub() -> Any:
    try:
        import huggingface_hub  # type: ignore

        return huggingface_hub
    except ImportError:
        raise ProviderError("O LTX-2 precisa das bibliotecas de mídia: rode  flow update  (ou  pip install \"openflow[media]\").") from None


def components_cached(base: str) -> bool:
    """Os componentes (codificador de texto, VAEs, vocoder…) de `base` já estão no cache do Hugging Face?"""
    hub = _hub()
    try:
        return all(isinstance(hub.try_to_load_from_cache(base, f), str) for f in ("model_index.json", "text_encoder/config.json"))
    except Exception:  # noqa: BLE001
        return False


def components_size(base: str, token: str = "") -> int:
    """Tamanho (bytes) do que `download_components` baixa — da lista de arquivos do repositório, sem os ignorados."""
    from fnmatch import fnmatch

    from .. import hf

    total = 0
    for f in hf.repo_files(base, token):
        if not any(fnmatch(f["name"], pat) for pat in IGNORE):
            total += int(f.get("size") or 0)
    return total


def download_components(base: str, token: str = "", note: Callable[[str], None] = lambda m: None, cancelled: Callable[[], bool] = lambda: False) -> str:
    """Baixa os componentes de `base` (sem o transformador) para o cache do Hugging Face. Só a pedido da pessoa (botão do nó)."""
    hub = _hub()
    note(f"Baixando os componentes de {base} (codificador de texto, VAEs, vocoder)…")
    if cancelled():
        raise ProviderError("cancelado")
    try:
        path = hub.snapshot_download(base, ignore_patterns=IGNORE, token=token or None)
    except Exception as exc:  # noqa: BLE001 — repositório restrito (gated), rede, disco
        msg = str(exc)
        if "401" in msg or "403" in msg or "gated" in msg.lower():
            raise ProviderError(f"{base} é um repositório restrito: aceite a licença na página do modelo e informe o token do Hugging Face em Configurações → Desempenho → Downloads de modelos. ({msg[:120]})") from None
        raise ProviderError(f"Não consegui baixar {base}: {msg[:200]}") from None
    return str(path)


def _imports() -> Tuple[Any, Any, Any]:
    try:
        import diffusers  # type: ignore
        import torch  # type: ignore
    except ImportError:
        raise ProviderError("O LTX-2 precisa de torch e diffusers: rode  flow update  (ou  pip install \"openflow[media]\").") from None
    for cls in ("LTX2Pipeline", "LTX2ImageToVideoPipeline", "LTX2VideoTransformer3DModel", "GGUFQuantizationConfig"):
        if not hasattr(diffusers, cls):
            raise ProviderError(f"O diffusers instalado ({getattr(diffusers, '__version__', '?')}) não tem o LTX-2 ({cls}): rode  flow update  para atualizá-lo (precisa da 0.43 ou mais nova).")
    try:
        from diffusers.utils import encode_video  # type: ignore
    except ImportError:
        raise ProviderError("O diffusers instalado não traz o `encode_video` do LTX-2: rode  flow update.") from None
    return torch, diffusers, encode_video


def load_pipeline(path: Optional[Path], base: str, image: bool, token: str = "", offload: bool = True) -> Any:
    """O pipeline do LTX-2 com o transformador do GGUF `path` (ou o do repositório, se `path` é None), só dos arquivos já baixados (`local_files_only`)."""
    torch, diffusers, _ = _imports()
    kw: Dict[str, Any] = {"torch_dtype": torch.bfloat16, "local_files_only": True}
    if token:
        kw["token"] = token
    if path is not None:
        try:
            kw["transformer"] = diffusers.LTX2VideoTransformer3DModel.from_single_file(
                str(path), quantization_config=diffusers.GGUFQuantizationConfig(compute_dtype=torch.bfloat16), torch_dtype=torch.bfloat16, config=base, subfolder="transformer", local_files_only=True)
        except Exception as exc:  # noqa: BLE001 — formato/versão do arquivo não bate com o repositório base
            raise ProviderError(f"Não consegui carregar {path.name} como transformador do LTX-2 (configuração de {base}): {str(exc)[:240]}. Confira se o arquivo é o da mesma versão do repositório base e se o diffusers está atualizado (flow update).") from None
    cls = diffusers.LTX2ImageToVideoPipeline if image else diffusers.LTX2Pipeline
    try:
        pipe = cls.from_pretrained(base, **kw)
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(f"Não consegui montar o pipeline do LTX-2 com {base}: {str(exc)[:240]}") from None
    if offload and torch.cuda.is_available():
        pipe.enable_model_cpu_offload()
    return pipe


def generate(pipe: Any, *, prompt: str, negative: str = "", width: int, height: int, frames: int, steps: int, cfg: float, seed: int = 0, image: Any = None,
             check: Callable[[], None] = lambda: None, extra: Optional[Dict[str, Any]] = None, sigmas: Optional[List[float]] = None) -> bytes:
    """Gera o vídeo (com áudio) e devolve os bytes do MP4. `image`: imagem PIL inicial (pipeline de imagem → vídeo)."""
    torch, _, encode_video = _imports()
    import inspect

    kw: Dict[str, Any] = {"prompt": prompt, "negative_prompt": negative or NEGATIVE, "width": width, "height": height, "num_frames": frames, "frame_rate": float(FPS),
                          "num_inference_steps": steps, "guidance_scale": cfg, "output_type": "np", "return_dict": False}
    if image is not None:
        kw["image"] = image
    if seed:
        kw["generator"] = torch.Generator("cpu").manual_seed(int(seed))
    try:
        takes_sigmas = "sigmas" in inspect.signature(pipe.__call__).parameters
    except (TypeError, ValueError):
        takes_sigmas = True
    if sigmas and takes_sigmas:
        kw["sigmas"] = [float(x) for x in sigmas]
        kw["num_inference_steps"] = len(kw["sigmas"])
    kw.update(extra or {})
    try:
        if "callback_on_step_end" in inspect.signature(pipe.__call__).parameters:   # cancelar no meio da geração
            def step(_pipe: Any, _i: int, _t: Any, cb: Dict[str, Any]) -> Dict[str, Any]:
                check()
                return cb

            kw["callback_on_step_end"] = step
    except (TypeError, ValueError):
        pass
    video, audio = pipe(**kw)
    with tempfile.TemporaryDirectory(prefix="flow-ltx2-") as d:
        out = Path(d) / "out.mp4"
        encode_video(video[0], fps=FPS, audio=audio[0].float().cpu(), audio_sample_rate=pipe.vocoder.config.output_sampling_rate, output_path=str(out))
        if not out.is_file():
            raise ProviderError("O LTX-2 terminou, mas o MP4 não foi gravado.")
        return out.read_bytes()


def missing_message(base: str, size: int) -> str:
    """O erro do nó quando os componentes não estão baixados: diz o que é, o tamanho e oferece o botão (marcador `[[flow-ltx2:base]]`)."""
    gb = f"≈ {size / 1024 ** 3:.0f} GB" if size else "vários GB"
    return (f"O LTX-2 precisa dos componentes de {base} (codificador de texto Gemma, VAEs e vocoder; {gb}) além do arquivo GGUF do modelo. Eles ainda não estão baixados: use o botão abaixo "
            f"(baixa do Hugging Face e leva um bom tempo) e execute o nó de novo. [[flow-ltx2:{base}]]")
