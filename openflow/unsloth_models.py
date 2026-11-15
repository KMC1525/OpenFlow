"""Modelos de imagem e vídeo da organização «unsloth» no Hugging Face (v0.21): o que o OpenFlow roda (baixando junto o VAE, o codificador de texto e o tokenizer), o que tem versão melhor em outro repositório e o que ainda não roda.

A lista vem dos repositórios GGUF reais da organização e das receitas dos cartões deles. `status`:
  ready — o OpenFlow reconhece a família e baixa/usa tudo o que o modelo precisa;
  alt   — o arquivo da Unsloth é para ComfyUI/diffusers e não carrega na stable-diffusion.cpp; `use` aponta o repositório que carrega;
  soon  — ainda sem receita no OpenFlow (o cartão só descreve o ComfyUI ou precisa de recursos que o OpenFlow não tem); `why` diz o motivo.
"""
from __future__ import annotations

from typing import Any, Dict, List

CATALOG: List[Dict[str, Any]] = [
    # ---- imagem
    {"repo": "unsloth/Qwen-Image-2.1-GGUF", "kind": "image", "label": "Qwen-Image 2.1", "size": "20B", "status": "ready", "hint": "Geração de imagem com texto legível; aceita várias referências."},
    {"repo": "unsloth/Qwen-Image-2.1-Turbo-GGUF", "kind": "image", "label": "Qwen-Image 2.1 Turbo", "size": "20B", "status": "ready", "hint": "A versão rápida: 8 passos, sem CFG."},
    {"repo": "unsloth/Qwen-Image-2512-GGUF", "kind": "image", "label": "Qwen-Image 2512", "size": "20B", "status": "ready", "hint": "Atualização do Qwen-Image; usa a receita do Qwen-Image."},
    {"repo": "unsloth/Qwen-Image-GGUF", "kind": "image", "label": "Qwen-Image", "size": "20B", "status": "ready", "hint": "O Qwen-Image original."},
    {"repo": "unsloth/Qwen-Image-Edit-2511-GGUF", "kind": "image", "label": "Qwen-Image-Edit 2511", "size": "20B", "status": "ready", "hint": "Edição de imagens (modo Editar); baixa também o projetor de visão."},
    {"repo": "unsloth/Qwen-Image-Edit-2509-GGUF", "kind": "image", "label": "Qwen-Image-Edit 2509", "size": "20B", "status": "ready", "hint": "Edição de imagens (modo Editar)."},
    {"repo": "unsloth/Z-Image-Turbo-GGUF", "kind": "image", "label": "Z-Image Turbo", "size": "6B", "status": "ready", "hint": "Leve e rápido (8 passos): o melhor ponto de partida em computadores modestos."},
    {"repo": "unsloth/Z-Image-GGUF", "kind": "image", "label": "Z-Image", "size": "6B", "status": "ready", "hint": "A versão base do Z-Image (mais passos, mais variedade)."},
    {"repo": "unsloth/FLUX.2-klein-4B-GGUF", "kind": "image", "label": "FLUX.2 klein 4B", "size": "4B", "status": "ready", "hint": "Rápido (4 passos); junta várias referências."},
    {"repo": "unsloth/FLUX.2-klein-9B-GGUF", "kind": "image", "label": "FLUX.2 klein 9B", "size": "9B", "status": "ready", "hint": "Mais qualidade que o 4B."},
    {"repo": "unsloth/FLUX.2-klein-base-4B-GGUF", "kind": "image", "label": "FLUX.2 klein base 4B", "size": "4B", "status": "ready", "hint": "Sem destilação: 50 passos, para afinar."},
    {"repo": "unsloth/FLUX.2-klein-base-9B-GGUF", "kind": "image", "label": "FLUX.2 klein base 9B", "size": "9B", "status": "ready", "hint": "Sem destilação: 50 passos, para afinar."},
    {"repo": "unsloth/FLUX.2-dev-GGUF", "kind": "image", "label": "FLUX.2 dev", "size": "32B", "status": "ready", "hint": "O maior da família: exige bastante RAM/VRAM."},
    {"repo": "unsloth/FLUX.1-schnell-GGUF", "kind": "image", "label": "FLUX.1 schnell", "size": "12B", "status": "ready", "hint": "4 passos; precisa do VAE, do clip_l e do t5xxl (baixados junto)."},
    {"repo": "unsloth/FLUX.1-dev-GGUF", "kind": "image", "label": "FLUX.1 dev", "size": "12B", "status": "ready", "hint": "Licença não comercial."},
    {"repo": "unsloth/FLUX.1-Kontext-dev-GGUF", "kind": "image", "label": "FLUX.1 Kontext dev", "size": "12B", "status": "ready", "hint": "Edição de imagens com instruções (modo Editar)."},
    {"repo": "unsloth/MOSS-Image-SFT-GGUF", "kind": "image", "label": "MOSS-Image SFT", "size": "5,1B", "status": "ready", "hint": "Novo na v0.21: bom com texto e layouts. Precisa do codificador Qwen3.5-9B (≈ 9,5 GB, baixado junto) e do sd-cli mais novo."},
    {"repo": "unsloth/MOSS-Image-Base-GGUF", "kind": "image", "label": "MOSS-Image Base", "size": "5,1B", "status": "ready", "hint": "A base do MOSS-Image (o SFT segue melhor as instruções)."},
    {"repo": "unsloth/flux-3-image-klein-GGUF", "kind": "image", "label": "FLUX.3 Image Klein", "size": "5,6B", "status": "alt", "use": "leejet/flux-3-image-klein-GGUF",
     "hint": "O arquivo da Unsloth é para ComfyUI/diffusers (nomes de tensores do checkpoint original): a stable-diffusion.cpp não o reconhece. Use o repositório leejet/flux-3-image-klein-GGUF."},
    {"repo": "unsloth/ERNIE-Image-Turbo-GGUF", "kind": "image", "label": "ERNIE-Image Turbo", "size": "8B", "status": "soon", "why": "O cartão só descreve o ComfyUI-GGUF; não confirmei suporte na stable-diffusion.cpp, então o OpenFlow ainda não tem receita."},
    # ---- vídeo
    {"repo": "unsloth/Wan2.2-TI2V-5B-GGUF", "kind": "video", "label": "Wan2.2 TI2V 5B", "size": "5B", "status": "ready", "hint": "Texto ou imagem → vídeo em 720p; baixa o VAE e o UMT5-XXL junto."},
    {"repo": "unsloth/MiniMax-H3-GGUF", "kind": "video", "label": "MiniMax H3", "size": "≈ 11–21 GB + 13–18 GB de texto", "status": "soon",
     "why": "Roda na stable-diffusion.cpp, mas precisa de um VAE de vídeo e um de áudio (da Comfy-Org), de opções especiais do sd-cli (--backend te=cpu, CFG 1,0) e entrega vídeo com áudio estéreo; o OpenFlow ainda monta só vídeo sem áudio."},
    {"repo": "unsloth/LTX-2.5-GGUF", "kind": "video", "label": "LTX-2.5", "size": "22B", "status": "soon", "why": "O cartão descreve só o ComfyUI (conectores, VAE de áudio e codificador Gemma 3 12B); sem receita para a stable-diffusion.cpp."},
    {"repo": "unsloth/LTX-2.3-GGUF", "kind": "video", "label": "LTX-2.3", "size": "22B", "status": "soon", "why": "O cartão descreve só o ComfyUI; sem receita para a stable-diffusion.cpp."},
    {"repo": "unsloth/LTX-2-GGUF", "kind": "video", "label": "LTX-2", "size": "19B", "status": "soon", "why": "O cartão descreve só o ComfyUI; sem receita para a stable-diffusion.cpp."},
]


def catalog(kind: str = "") -> List[Dict[str, Any]]:
    """O catálogo (de um tipo, ou todos)."""
    return [dict(e) for e in CATALOG if not kind or e["kind"] == kind]
