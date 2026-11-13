"""Arquivos de apoio dos modelos (v0.1): VAE, codificadores de texto e projetor de visão (mmproj).

Qwen-Image, FLUX, Z-Image, Wan… trazem só o «transformador» e precisam do VAE e dos codificadores de texto **na mesma pasta**; modelos de texto com visão (Qwen-VL, Gemma 3…) precisam do
`mmproj`. Aqui ficam as famílias conhecidas (como reconhecer o modelo, que arquivo de apoio cada parâmetro de carga espera e de onde baixá-lo) **e** a descoberta no próprio repositório
(o `mmproj-*.gguf`, `*vae*.safetensors`, `clip_l`, `t5xxl`… que o autor publicou ao lado do modelo).

Os arquivos de apoio são instalados **automaticamente junto do modelo** (`install_with_model`, chamado pelo download da busca, pelos pré-instalados e por `flow models support`); o botão «Baixar os
arquivos de apoio» do nó continua existindo para quem já tinha o modelo. Desligue em Configuração → Modelos (`hf.auto_support`).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import hf

FAMILIES: List[Dict[str, Any]] = [
    # ---- Unsloth (v0.17.30): Qwen-Image 2.1 e Turbo, Z-Image e Turbo (imagem) e Wan2.2 TI2V 5B (vídeo). As receitas vêm dos cartões dos repositórios unsloth/*-GGUF (VAE, codificador de texto, passos e CFG).
    {"id": "qwen-image-2.1", "name": r"qwen[-_ ]?image[-_ ]?2[._]?1", "label": "Qwen-Image 2.1", "cap": "image",
     "load": {"vae_path": r"qwen[-_]?image[-_]?2[._]?1[-_]?vae.*\.safetensors$", "llm_path": r"^qwen[-_]?3[-_]?vl[-_]?8b[-_]?instruct(?!.*mmproj)[^/]*\.gguf$"},
     "run": {"cfg_scale": 6.0, "sample_steps": 20, "sample_method": "euler"}, "variants": [{"match": r"turbo", "run": {"cfg_scale": 1.0, "sample_steps": 8, "sample_method": "euler"}}],   # Turbo: 8 passos, CFG 1
     "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE do Qwen-Image 2.1 (qwen_image_2.1_vae_bf16.safetensors, em unsloth/Qwen-Image-2.1-FP8) e o codificador de texto Qwen3-VL-8B-Instruct (um .gguf, ex.: unsloth/Qwen3-VL-8B-Instruct-GGUF)",
     "downloads": {"vae_path": {"repo": "unsloth/Qwen-Image-2.1-FP8", "file": "vae/qwen_image_2.1_vae_bf16.safetensors", "label": "VAE do Qwen-Image 2.1", "approx": 0.68},
                   "llm_path": {"repo": "unsloth/Qwen3-VL-8B-Instruct-GGUF", "file": "Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf", "label": "Codificador de texto Qwen3-VL-8B-Instruct (UD-Q4_K_XL)", "approx": 5.1}}},
    {"id": "z-image", "name": r"z[-_ ]?image", "label": "Z-Image", "cap": "image",
     "load": {"vae_path": r"^ae\.safetensors$", "llm_path": r"^qwen[-_]?3[-_]?4b[-_]?instruct[-_]?2507(?!.*mmproj)[^/]*\.gguf$"},
     "run": {"cfg_scale": 4.0, "sample_steps": 30}, "variants": [{"match": r"turbo", "run": {"cfg_scale": 1.0, "sample_steps": 8}}],   # Turbo: 8 passos, sem CFG; o Z-Image «base» usa 30 passos e CFG 4
     "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE (ae.safetensors) e o codificador de texto Qwen3-4B-Instruct-2507 (um .gguf, ex.: unsloth/Qwen3-4B-Instruct-2507-GGUF)",
     "downloads": {"vae_path": {"repo": "Comfy-Org/z_image_turbo", "file": "split_files/vae/ae.safetensors", "label": "VAE (ae.safetensors)", "approx": 0.34},
                   "llm_path": {"repo": "unsloth/Qwen3-4B-Instruct-2507-GGUF", "file": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "label": "Codificador de texto Qwen3-4B-Instruct-2507 (Q4_K_M)", "approx": 2.5}}},
    {"id": "wan22-ti2v-5b", "name": r"wan[-_. ]?2[._]?2.*ti2v", "label": "Wan2.2 TI2V 5B", "cap": "video",
     "load": {"vae_path": r"wan[-_]?2[._]?2[-_]?vae.*\.safetensors$", "t5xxl_path": r"umt5[-_]?xxl.*\.(safetensors|gguf)$"},
     "run": {"cfg_scale": 5.0, "sample_steps": 30, "flow_shift": 5.0, "sample_method": "euler"},
     "video": {"fps": 24, "sizes": {"landscape": [1280, 704], "portrait": [704, 1280]}, "max_frames": 121},   # 720p apenas (1280×704 ou 704×1280); quadros = 4k+1 (o VAE comprime 4× no tempo)
     "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE do Wan2.2 (Wan2.2_VAE.safetensors, em unsloth/Wan2.2-TI2V-5B-GGUF) e o codificador de texto UMT5-XXL (um .gguf, ex.: city96/umt5-xxl-encoder-gguf)",
     "downloads": {"vae_path": {"repo": "unsloth/Wan2.2-TI2V-5B-GGUF", "file": "VAE/Wan2.2_VAE.safetensors", "label": "VAE do Wan2.2", "approx": 1.4},
                   "t5xxl_path": {"repo": "city96/umt5-xxl-encoder-gguf", "file": "umt5-xxl-encoder-Q4_K_M.gguf", "label": "Codificador de texto UMT5-XXL (Q4_K_M)", "approx": 3.7}}},
    {"id": "wan21-t2v", "name": r"wan[-_. ]?2[._]?1.*t2v", "label": "Wan2.1 T2V", "cap": "video",
     "load": {"vae_path": r"wan[-_]?2[._]?1[-_]?vae.*\.safetensors$", "t5xxl_path": r"umt5[-_]?xxl.*\.(safetensors|gguf)$"},
     "run": {"cfg_scale": 6.0, "sample_steps": 30, "flow_shift": 5.0, "sample_method": "euler"},
     "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE do Wan2.1 (wan_2.1_vae.safetensors) e o codificador de texto UMT5-XXL (umt5_xxl_fp8_e4m3fn_scaled.safetensors), ambos em Comfy-Org/Wan_2.1_ComfyUI_repackaged",
     "downloads": {"vae_path": {"repo": "Comfy-Org/Wan_2.1_ComfyUI_repackaged", "file": "split_files/vae/wan_2.1_vae.safetensors", "label": "VAE do Wan2.1", "approx": 0.25},
                   "t5xxl_path": {"repo": "Comfy-Org/Wan_2.1_ComfyUI_repackaged", "file": "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", "label": "Codificador de texto UMT5-XXL (fp8)", "approx": 6.7}}},
    {"id": "qwen-image", "name": r"qwen[-_ ]?image", "label": "Qwen-Image",
     "load": {"vae_path": r"qwen.*image.*vae", "llm_path": r"qwen2[._]?5.*vl.*\.gguf$"}, "marker": "transformer_blocks.0.img_mod.1.weight", "run": {"cfg_scale": 2.5, "flow_shift": 3.0, "sample_method": "euler"}, "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE (qwen_image_vae.safetensors, em Comfy-Org/Qwen-Image_ComfyUI) e o codificador de texto Qwen2.5-VL (um .gguf, ex.: unsloth/Qwen2.5-VL-7B-Instruct-GGUF)",
     "downloads": {"vae_path": {"repo": "Comfy-Org/Qwen-Image_ComfyUI", "file": "split_files/vae/qwen_image_vae.safetensors", "label": "VAE do Qwen-Image", "approx": 0.25},
                   "llm_path": {"repo": "unsloth/Qwen2.5-VL-7B-Instruct-GGUF", "file": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf", "label": "Codificador de texto Qwen2.5-VL (Q4_K_M)", "approx": 4.7}}},
    {"id": "flux2-dev", "name": r"flux[-_. ]?2[-_. ]?dev", "label": "FLUX.2 dev (32B)", "cap": "image",   # unsloth/FLUX.2-dev-GGUF: o codificador de texto é o Mistral-Small-3.2-24B (receita do cartão da stable-diffusion.cpp)
     "load": {"vae_path": r"flux2[-_]?(ae|vae)", "llm_path": r"^mistral[-_]?small[-_]?3[._]?2[-_]?24b[-_]?instruct[-_]?2506(?!.*mmproj)[^/]*\.gguf$"},
     "run": {"cfg_scale": 1.0, "sample_steps": 28, "sample_method": "euler"}, "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE do FLUX.2 (flux2-vae.safetensors, em Comfy-Org/flux2-dev) e o codificador de texto Mistral-Small-3.2-24B-Instruct (um .gguf, ex.: unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF)",
     "downloads": {"vae_path": {"repo": "Comfy-Org/flux2-dev", "file": "split_files/vae/flux2-vae.safetensors", "label": "VAE do FLUX.2", "approx": 0.34},
                   "llm_path": {"repo": "unsloth/Mistral-Small-3.2-24B-Instruct-2506-GGUF", "file": "Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf", "label": "Codificador de texto Mistral-Small-3.2-24B (Q4_K_M)", "approx": 14.3}}},
    {"id": "flux2-klein-9b", "name": r"flux[-_. ]?2.*9b", "label": "FLUX.2 klein (9B)",
     "load": {"vae_path": r"flux2[-_]?(ae|vae)", "llm_path": r"^qwen[-_]?3[-_]8b(?![-_]?(instruct|vl|thinking|embedding|2507))[^/]*\.gguf$"}, "marker": "double_blocks.",
     "run": {"cfg_scale": 1.0, "sample_steps": 4, "sample_method": "euler"}, "run_base": {"cfg_scale": 4.0, "sample_steps": 50, "sample_method": "euler"},   # klein é destilado (4 passos, sem CFG); o «base» usa 50 passos e CFG 4
     "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE do FLUX.2 (flux2-vae.safetensors, em Comfy-Org/flux2-dev) e o codificador de texto Qwen3-8B (um .gguf, ex.: unsloth/Qwen3-8B-GGUF)",
     "downloads": {"vae_path": {"repo": "Comfy-Org/flux2-dev", "file": "split_files/vae/flux2-vae.safetensors", "label": "VAE do FLUX.2", "approx": 0.34},
                   "llm_path": {"repo": "unsloth/Qwen3-8B-GGUF", "file": "Qwen3-8B-Q4_K_M.gguf", "label": "Codificador de texto Qwen3-8B (Q4_K_M)", "approx": 5.0}}},
    {"id": "flux2-klein-4b", "name": r"flux[-_. ]?2.*4b", "label": "FLUX.2 klein (4B)",
     "load": {"vae_path": r"flux2[-_]?(ae|vae)", "llm_path": r"^qwen[-_]?3[-_]4b(?![-_]?(instruct|vl|thinking|embedding|2507))[^/]*\.gguf$"}, "marker": "double_blocks.",
     "run": {"cfg_scale": 1.0, "sample_steps": 4, "sample_method": "euler"}, "run_base": {"cfg_scale": 4.0, "sample_steps": 50, "sample_method": "euler"},   # klein é destilado (4 passos, sem CFG); o «base» usa 50 passos e CFG 4
     "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE do FLUX.2 (flux2-vae.safetensors, em Comfy-Org/flux2-dev) e o codificador de texto Qwen3-4B (um .gguf, ex.: unsloth/Qwen3-4B-GGUF)",
     "downloads": {"vae_path": {"repo": "Comfy-Org/flux2-dev", "file": "split_files/vae/flux2-vae.safetensors", "label": "VAE do FLUX.2", "approx": 0.34},
                   "llm_path": {"repo": "unsloth/Qwen3-4B-GGUF", "file": "Qwen3-4B-Q4_K_M.gguf", "label": "Codificador de texto Qwen3-4B (Q4_K_M)", "approx": 2.5}}},
    {"id": "flux3-klein", "name": r"flux[-_. ]?3(?!.*pup)", "label": "FLUX.3 Image Klein",   # «pup» = o expansor de prompt (um modelo de texto), não é de imagem
     "load": {"vae_path": r"flux2[-_]?(ae|vae)", "llm_path": r"^qwen[-_]?3[-_]?vl[-_]?4b[-_]?instruct(?!.*mmproj)[^/]*\.gguf$"},
     "run": {"cfg_scale": 1.0, "sample_steps": 16}, "run_base": {"cfg_scale": 3.5, "sample_steps": 50},   # destilado: 16 passos, sem guidance; «base»: 50 passos, guidance 3,5 (cartão do modelo)
     "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE do FLUX.2/3 (flux2-vae.safetensors, em Comfy-Org/flux2-dev) e o codificador de texto Qwen3-VL-4B-Instruct (um .gguf, ex.: unsloth/Qwen3-VL-4B-Instruct-GGUF)",
     "downloads": {"vae_path": {"repo": "Comfy-Org/flux2-dev", "file": "split_files/vae/flux2-vae.safetensors", "label": "VAE do FLUX.2/3", "approx": 0.34},
                   "llm_path": {"repo": "unsloth/Qwen3-VL-4B-Instruct-GGUF", "file": "Qwen3-VL-4B-Instruct-Q4_K_M.gguf", "label": "Codificador de texto Qwen3-VL-4B-Instruct (Q4_K_M)", "approx": 2.5}}},
    {"id": "flux", "name": r"flux(?![-_. ]?[23])", "label": "FLUX",
     "load": {"vae_path": r"^ae\.safetensors$", "clip_l_path": r"clip[_-]?l.*\.safetensors$", "t5xxl_path": r"t5xxl.*\.(safetensors|gguf)$"}, "marker": "double_blocks.", "run": {}, "options": {"offload_params_to_cpu": True, "diffusion_flash_attn": True},
     "need": "o VAE (ae.safetensors), o clip_l.safetensors e o t5xxl (safetensors ou .gguf)",
     "downloads": {"vae_path": {"repo": "Comfy-Org/z_image_turbo", "file": "split_files/vae/ae.safetensors", "label": "VAE (ae.safetensors)", "approx": 0.33},
                   "clip_l_path": {"repo": "comfyanonymous/flux_text_encoders", "file": "clip_l.safetensors", "label": "clip_l", "approx": 0.25},
                   "t5xxl_path": {"repo": "comfyanonymous/flux_text_encoders", "file": "t5xxl_fp8_e4m3fn.safetensors", "label": "t5xxl (fp8)", "approx": 4.9}}},
]


def run_for(fam: Dict[str, Any], filename: str) -> Dict[str, Any]:
    """Os parâmetros de geração da família; a variante «base» (sem destilação) usa os de `run_base`, se a família tem, e `variants` (ex.: «turbo») trocam os parâmetros pelo nome do arquivo."""
    name = Path(filename).name
    for v in fam.get("variants") or []:
        if re.search(v["match"], name, re.I):
            return dict(v["run"])
    if fam.get("run_base") and re.search(r"base", name, re.I):
        return dict(fam["run_base"])
    return dict(fam.get("run") or {})


def family_of(filename: str) -> Optional[Dict[str, Any]]:
    return next((f for f in FAMILIES if re.search(f["name"], Path(filename).name, re.I)), None)


def find_companions(folder: Path, model: Path, fam: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """Para cada parâmetro de carga da família, o nome do arquivo de apoio achado em `folder` (None se falta)."""
    files = sorted(f for f in folder.iterdir() if f.is_file() and f != model and not f.name.endswith(".part")) if folder.is_dir() else []
    out: Dict[str, Optional[str]] = {}
    for key, pat in fam["load"].items():
        hit = next((f for f in files if re.search(pat, f.name, re.I)), None)
        out[key] = hit.name if hit else None
    return out


def missing(folder: Path, filename: str) -> Dict[str, Any]:
    """{family, missing: [{key, label, repo, file, approx}], approx_gb} do que falta para o modelo `filename` (vazio se não é de uma família conhecida ou se está tudo lá)."""
    fam = family_of(filename)
    if not fam:
        return {"family": "", "missing": [], "approx_gb": 0.0}
    found = find_companions(folder, folder / Path(filename).name, fam)
    todo = [{"key": k, **fam["downloads"][k]} for k, v in found.items() if v is None]
    return {"family": fam["id"], "label": fam["label"], "missing": todo, "approx_gb": round(sum(t["approx"] for t in todo), 1)}


def download_missing(folder: Path, filename: str, token: str = "", progress: Optional[Callable[[int, int], None]] = None,
                     cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None) -> List[str]:
    """Baixa para `folder` os arquivos de apoio que faltam (retoma downloads parciais). Devolve os nomes baixados."""
    info = missing(folder, filename)
    got: List[str] = []
    n = len(info["missing"])
    for i, t in enumerate(info["missing"]):
        note(f"Baixando {t['label']} ({i + 1}/{n})…")
        base = i

        def prog(done: int, total: int, base: int = base) -> None:
            if progress:   # progresso geral: cada arquivo vale uma fatia igual
                progress(int((base + (done / total if total else 0)) * 1000), n * 1000)

        folder.mkdir(parents=True, exist_ok=True)
        hf.download_many(t["repo"], [t["file"]], folder, token, None, prog, cancelled, any_file=True)
        got.append(Path(t["file"]).name)
    return got


# --------------------------------------------------------------------------- instalação automática junto do modelo (v0.1)
ROLE_OF_KEY = {"vae_path": "vae", "llm_path": "text_encoder", "clip_l_path": "text_encoder", "clip_g_path": "text_encoder", "t5xxl_path": "text_encoder"}
ROLE_LABEL = {"vae": "VAE", "text_encoder": "Codificador de texto", "mmproj": "Projetor de visão (mmproj)"}
_SHARD_RE = re.compile(r"^(?P<base>.+)-(?P<n>\d{5})-of-(?P<total>\d{5})\.gguf$", re.I)
_VAE_RE = re.compile(r"^ae\.|vae", re.I)   # aplicado ao nome do arquivo: «ae.safetensors» (FLUX) ou qualquer «…vae…»
_ENC_RE = re.compile(r"(clip[_-]?[lg]\b|t5xxl|umt5)", re.I)
_EXT_RE = re.compile(r"\.(safetensors|gguf)$", re.I)
_MMPROJ_PREF = ("f16", "bf16", "q8_0", "f32")   # projetores pesam centenas de MB: a precisão alta custa pouco e a visão é sensível a ela


def model_stem(filename: str) -> str:
    """O nome do modelo sem a extensão e sem o sufixo de partes (`-00001-of-00003`)."""
    name = Path(filename).name
    m = _SHARD_RE.match(name)
    return m.group("base") if m else re.sub(r"\.gguf$", "", name, flags=re.I)


def mmproj_name(filename: str) -> str:
    """Nome local do projetor de visão de um modelo: `<modelo>.mmproj.gguf` (o mesmo `mmproj-F16.gguf` pode existir em vários repositórios, então cada modelo guarda o seu)."""
    return f"{model_stem(filename)}.mmproj.gguf"


def mmproj_for(folder: Path, filename: str) -> Optional[Path]:
    """O projetor de visão do modelo, se já está na pasta."""
    p = Path(folder) / mmproj_name(filename)
    return p if p.is_file() else None


def _pick_mmproj(files: List[Dict[str, Any]], filename: str) -> Optional[Dict[str, Any]]:
    """O melhor `mmproj*.gguf` do repositório para o modelo: o que traz o nome do modelo, senão o de precisão preferida (F16, BF16, Q8_0, F32)."""
    cands = [f for f in files if "mmproj" in Path(f["name"]).name.lower() and f["name"].lower().endswith(".gguf")]
    if not cands:
        return None
    stem = re.sub(r"[-_.]?(i?q\d\w*|bf16|f16|f32|ud-\w+)$", "", model_stem(filename), flags=re.I).lower()
    named = [f for f in cands if stem and stem in Path(f["name"]).name.lower()]
    pool = named or [f for f in cands if "/" not in f["name"]] or cands

    def rank(f: Dict[str, Any]) -> int:
        low = Path(f["name"]).name.lower()
        for i, q in enumerate(_MMPROJ_PREF):
            if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(q), low):
                return i
        return len(_MMPROJ_PREF)

    return sorted(pool, key=lambda f: (rank(f), f["size"]))[0]


def _discover(files: List[Dict[str, Any]], fam: Optional[Dict[str, Any]], folder: Path) -> List[Dict[str, Any]]:
    """Modelo de família desconhecida cujo repositório traz VAE/codificadores de texto ao lado: devolve o que falta na pasta (um de cada tipo; os menores primeiro)."""
    if fam:
        return []
    have = {f.name.lower() for f in folder.iterdir() if f.is_file()} if folder.is_dir() else set()
    out: List[Dict[str, Any]] = []
    cands = [f for f in files if _EXT_RE.search(f["name"]) and "mmproj" not in f["name"].lower() and not re.search(r"(^|/)(transformer|unet|diffusion_models?)/", f["name"], re.I)
             and not f["name"].lower().endswith("diffusion_pytorch_model.safetensors") and Path(f["name"]).name.lower() != "model.safetensors"]
    vaes = sorted((f for f in cands if _VAE_RE.search(Path(f["name"]).name)), key=lambda f: f["size"])
    if vaes and vaes[0]["size"] < 2 * 1024 ** 3 and Path(vaes[0]["name"]).name.lower() not in have:
        out.append({"role": "vae", "file": vaes[0]["name"], "size": vaes[0]["size"], "dest": Path(vaes[0]["name"]).name, "label": "VAE (" + Path(vaes[0]["name"]).name + ")"})
    seen = set()
    for f in sorted((f for f in cands if _ENC_RE.search(Path(f["name"]).name)), key=lambda f: f["size"]):
        base = re.sub(r"[-_.]?(fp\d+\w*|bf16|f16|q\d\w*|scaled|e4m3fn)", "", Path(f["name"]).stem, flags=re.I).lower()
        if base in seen or Path(f["name"]).name.lower() in have:
            continue
        seen.add(base)
        out.append({"role": "text_encoder", "file": f["name"], "size": f["size"], "dest": Path(f["name"]).name, "label": "Codificador de texto (" + Path(f["name"]).name + ")"})
    return out


def plan(folder: Path, filename: str, kind: str = "image", repo: str = "", repo_tree: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """O que falta ao lado do modelo `filename` (em `folder`): {family, label, items: [{role, repo, file, dest, size, label}], total_bytes}.

    Fontes, nesta ordem: a família conhecida (`FAMILIES`: repositórios certos do VAE e dos codificadores), o `mmproj` do repositório do modelo (modelos de texto/visão) e, se a família
    é desconhecida, o VAE/codificadores que o repositório traz ao lado. `repo_tree` = arquivos do repositório (`hf.repo_files`); sem ele só vale a família conhecida."""
    folder = Path(folder)
    fam = family_of(filename) or (next((f for f in FAMILIES if repo and re.search(f["name"], repo.split("/")[-1], re.I) and f.get("cap", kind) == kind), None))
    items: List[Dict[str, Any]] = []
    if fam:
        found = find_companions(folder, folder / Path(filename).name, fam)
        for key, got in found.items():
            if got is None:
                d = fam["downloads"][key]
                items.append({"role": ROLE_OF_KEY.get(key, "text_encoder"), "key": key, "repo": d["repo"], "file": d["file"], "dest": Path(d["file"]).name, "label": d["label"], "size": int(d["approx"] * 1e9)})
    tree = repo_tree or []
    if kind in ("text", "other") and tree and not mmproj_for(folder, filename):
        mm = _pick_mmproj(tree, filename)
        if mm and repo:
            items.append({"role": "mmproj", "repo": repo, "file": mm["name"], "dest": mmproj_name(filename), "label": "Projetor de visão (" + Path(mm["name"]).name + ")", "size": mm["size"]})
    if kind in ("image", "video") and tree and repo:
        items += [dict(i, repo=repo) for i in _discover(tree, fam, folder)]
    return {"family": fam["id"] if fam else "", "label": fam["label"] if fam else "", "items": items, "total_bytes": sum(int(i.get("size") or 0) for i in items)}


def install_with_model(folder: Path, filename: str, kind: str, repo: str = "", token: str = "", repo_tree: Optional[List[Dict[str, Any]]] = None,
                       progress: Optional[Callable[[int, int], None]] = None, cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None) -> Dict[str, Any]:
    """Baixa para `folder` o VAE, os codificadores de texto e o mmproj que faltam ao modelo `filename` (retoma downloads parciais; não baixa de novo o que já está lá).

    Devolve {installed: [nomes], failed: [{label, error}], items: [...]}. A falha de um arquivo de apoio **não desfaz** o modelo: o chamador mostra o aviso e o botão do nó refaz o que faltou."""
    info = plan(folder, filename, kind, repo, repo_tree)
    items = info["items"]
    out: Dict[str, Any] = {"installed": [], "failed": [], "items": items, "family": info["family"]}
    if not items:
        return out
    Path(folder).mkdir(parents=True, exist_ok=True)
    need = sum(int(i.get("size") or 0) for i in items)
    if need and shutil.disk_usage(folder).free < need * 1.02 + (50 << 20):
        out["failed"].append({"label": "todos", "error": "Sem espaço em disco suficiente para os arquivos de apoio."})
        return out
    n = len(items)
    for i, it in enumerate(items):
        note(f"Baixando {it['label']} ({i + 1}/{n})…")

        def prog(done: int, total: int, base: int = i) -> None:
            if progress:   # progresso geral dos arquivos de apoio: cada um vale uma fatia igual
                progress(int((base + (done / total if total else 0)) * 1000), n * 1000)

        try:
            hf.download(it["repo"], it["file"], Path(folder), token, prog, cancelled, any_file=True, dest_name=it["dest"] if it["dest"] != Path(it["file"]).name else "")
            out["installed"].append(it["dest"])
        except Exception as exc:   # noqa: BLE001 — ProviderError, rede, disco: o modelo principal já está baixado
            if str(exc) == "cancelado":
                raise
            out["failed"].append({"label": it["label"], "error": str(exc)[:200]})
    return out


def status_of(folder: Path, filename: str, kind: str) -> Dict[str, Any]:
    """Estado dos arquivos de apoio de um modelo já baixado, sem rede: {family, label, have: [{role, name}], missing: [{role, label, approx_gb}]}. O mmproj só é conferido se já está na pasta."""
    folder = Path(folder)
    fam = family_of(filename)
    have: List[Dict[str, str]] = []
    miss: List[Dict[str, Any]] = []
    if fam:
        found = find_companions(folder, folder / Path(filename).name, fam)
        for key, got in found.items():
            role = ROLE_OF_KEY.get(key, "text_encoder")
            if got:
                have.append({"role": role, "name": got})
            else:
                d = fam["downloads"][key]
                miss.append({"role": role, "label": d["label"], "approx_gb": d["approx"]})
    mm = mmproj_for(folder, filename)
    if mm:
        have.append({"role": "mmproj", "name": mm.name})
    return {"family": fam["id"] if fam else "", "label": fam["label"] if fam else "", "have": have, "missing": miss, "approx_gb": round(sum(m["approx_gb"] for m in miss), 1)}
