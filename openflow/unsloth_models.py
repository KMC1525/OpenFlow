"""Modelos de imagem e vídeo da organização «unsloth» no Hugging Face (v0.21): o que o OpenFlow roda (baixando junto o VAE, o codificador de texto e o tokenizer), o que tem versão melhor em outro repositório e o que ainda não roda.

A lista vem dos repositórios GGUF reais da organização e das receitas dos cartões deles. `status`:
  ready — o OpenFlow reconhece a família e baixa/usa tudo o que o modelo precisa;
  alt   — o arquivo da Unsloth é para ComfyUI/diffusers e não carrega na stable-diffusion.cpp; `use` aponta o repositório que carrega;
  beta  — roda, mas ainda não foi verificado em hardware real (v0.22: MiniMax H3 e LTX-2.x); `hint` diz o que precisa;
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
     "hint": "O arquivo da Unsloth é para ComfyUI/diffusers (nomes de tensores do checkpoint original): a stable-diffusion.cpp não o reconhece. Use o repositório leejet/flux-3-image-klein-GGUF (a versão «base», que segue melhor o prompt e usa 20 passos, está em leejet/flux-3-image-klein-base-GGUF)."},
    {"repo": "unsloth/MiniMax-H3-Image-GGUF", "kind": "image", "label": "MiniMax H3 Image", "size": "33B · ≈ 8–22 GB + 13–18 GB de texto", "status": "beta",
     "hint": "Novo na v0.30: imagens de até 16 megapixels e edição com até 16 referências (<Picture 1>, <Picture 2>…); destilado em 6 passos, sem CFG. Baixa junto o VAE de imagem e o codificador Qwen3-VL-32B (o mesmo do vídeo H3). Recomendado: UD-Q4_K_XL (13,6 GB). Pesado: placa pequena usa memória da RAM."},
    {"repo": "unsloth/ERNIE-Image-Turbo-GGUF", "kind": "image", "label": "ERNIE-Image Turbo", "size": "8B", "status": "soon", "why": "O cartão só descreve o ComfyUI-GGUF; não confirmei suporte na stable-diffusion.cpp, então o OpenFlow ainda não tem receita."},
    # ---- vídeo
    {"repo": "unsloth/Wan2.2-TI2V-5B-GGUF", "kind": "video", "label": "Wan2.2 TI2V 5B", "size": "5B", "status": "ready", "hint": "Texto ou imagem → vídeo em 720p; baixa o VAE e o UMT5-XXL junto."},
    {"repo": "unsloth/MiniMax-H3-GGUF", "kind": "video", "label": "MiniMax H3", "size": "≈ 11–21 GB + 13–18 GB de texto", "status": "beta",
     "hint": "Novo na v0.22: vídeo com áudio estéreo (WebM, até 15 s). Baixa junto o VAE de vídeo, o VAE de áudio e o codificador Qwen3-VL-32B; usa o sd-cli (CFG 1,0 e codificador de texto na CPU, como pede o cartão). Pesado: precisa de muita memória."},
    {"repo": "unsloth/LTX-2.5-GGUF", "kind": "video", "label": "LTX-2.5", "size": "22B", "status": "beta",
     "hint": "Novo na v0.22: vídeo com áudio (MP4) pelo diffusers (precisa do flow update). Os componentes do repositório diffusers (≈ 25 GB, restrito: aceite a licença e informe o token) baixam por um botão no nó."},
    {"repo": "unsloth/LTX-2.3-GGUF", "kind": "video", "label": "LTX-2.3", "size": "22B", "status": "beta",
     "hint": "Novo na v0.22: vídeo com áudio (MP4) pelo diffusers. Usa os componentes do LTX-2.5 como base (não confirmado); baixados por um botão no nó."},
    {"repo": "unsloth/LTX-2-GGUF", "kind": "video", "label": "LTX-2", "size": "19B", "status": "beta",
     "hint": "Novo na v0.22: vídeo com áudio (MP4) pelo diffusers; os componentes de Lightricks/LTX-2 (≈ 25 GB) baixam por um botão no nó."},
]


def catalog(kind: str = "") -> List[Dict[str, Any]]:
    """O catálogo (de um tipo, ou todos)."""
    return [dict(e) for e in CATALOG if not kind or e["kind"] == kind]
