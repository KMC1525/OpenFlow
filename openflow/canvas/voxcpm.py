"""VoxCPM2 (openbmb/VoxCPM2, v0.71): o modelo de voz local de 2 B de parâmetros, 30 idiomas, saída em 48 kHz.

Aqui fica o que não precisa do modelo (Python puro, testável): reconhecer o modelo, montar o texto com a descrição da voz («Voice Design»: a descrição entre parênteses no começo do texto), repartir um texto
longo em trechos e ler os ajustes avançados do campo «Extra». Quem carrega o modelo e gera a voz é `LocalHFMedia._voice_voxcpm` (media.py), com a biblioteca `voxcpm` (pip install voxcpm).

Os quatro modos do modelo, e como o nó Voz os usa:
- Fala comum — só o texto (o idioma é reconhecido pelo texto; não há marca de idioma).
- Design de voz — o campo «Como é a voz» vira «(descrição)texto». Sem áudio de referência.
- Clonagem controlável — um áudio na entrada «Voz de referência»; a descrição, se houver, guia o estilo («(mais rápido, alegre)texto») mantendo o timbre.
- Clonagem fiel («ultimate») — o áudio de referência + o texto exato dele no campo «O que se diz na referência»: o modelo continua a fala do áudio.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

REPO = "openbmb/VoxCPM2"
MAX_DESCRIPTION = 400     # caracteres da descrição da voz
MAX_CHUNK = 420           # caracteres por trecho de texto (o modelo fica instável com entradas muito longas)
MAX_REFERENCE_SECONDS = 30.0
SILENCE_SECONDS = 0.18    # pausa posta entre os trechos de um texto longo
DEFAULTS: Dict[str, Any] = {"cfg_value": 2.0, "inference_timesteps": 10}
_KNOWN = {"cfg_value": (float, 0.5, 5.0), "inference_timesteps": (int, 2, 50), "min_len": (int, 1, 100), "max_len": (int, 64, 4096), "normalize": (bool,), "denoise": (bool,), "retry_badcase": (bool,),
          "retry_badcase_max_times": (int, 0, 8), "retry_badcase_ratio_threshold": (float, 1.0, 20.0)}


def is_voxcpm(model: Optional[str]) -> bool:
    """«openbmb/VoxCPM2», «openbmb/VoxCPM-0.5B», «OpenBMB/VoxCPM1.5», «…/voxcpm2-gguf»: o nome tem «voxcpm»."""
    return bool(re.search(r"voxcpm", model or "", re.I))


def supports_reference(model: Optional[str]) -> bool:
    """Só o VoxCPM2 (e posteriores) aceita um áudio de referência para clonar a voz; o VoxCPM 0.5B/1.5 só continua um áudio de prompt, e o OpenFlow não os usa assim."""
    m = re.search(r"voxcpm[-_ ]?v?(\d+(?:\.\d+)?)", model or "", re.I)
    if not m:
        return False
    try:
        return float(m.group(1)) >= 2
    except ValueError:
        return False


def clean_description(text: str) -> str:
    """A descrição sem parênteses (eles delimitam a descrição no texto do modelo) e em uma linha só."""
    t = re.sub(r"[()（）\r\n]+", ",", str(text or ""))   # a descrição e o estilo do projeto vêm em linhas separadas: viram itens separados por vírgula
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(\s*,)+\s*", ", ", t).strip(" ,;")
    return t[:MAX_DESCRIPTION].strip(" ,;")


def with_description(text: str, description: str) -> str:
    """«(descrição)texto». Um texto que já começa com «(…)» é do usuário e fica como está (ele já escreveu o design de voz à mão)."""
    desc = clean_description(description)
    if not desc or re.match(r"\s*[(（]", text or ""):
        return text
    return f"({desc}){text}"


def split_text(text: str, limit: int = MAX_CHUNK) -> List[str]:
    """Reparte o texto em trechos de até `limit` caracteres, cortando em fim de frase (depois em vírgula, depois em espaço). Um texto curto volta inteiro. Só vale para o texto SEM a descrição
    (ela é posta de novo em cada trecho)."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return [text] if text else []
    parts = re.findall(r"[^.!?…。！？]+[.!?…。！？]+[\"'”’)\]]*\s*|[^.!?…。！？]+$", text)
    out: List[str] = []
    cur = ""

    def flush() -> None:
        nonlocal cur
        if cur.strip():
            out.append(cur.strip())
        cur = ""
    for sent in parts:
        if len(sent) > limit:                       # uma «frase» maior que o limite: corta em vírgulas e, se preciso, em espaços
            flush()
            for piece in re.findall(r"[^,;:，、；：]+[,;:，、；：]*\s*", sent):
                while len(piece) > limit:
                    cut = piece.rfind(" ", 0, limit)
                    cut = cut if cut > limit // 3 else limit
                    if len(cur) + cut > limit:
                        flush()
                    cur += piece[:cut]
                    flush()
                    piece = piece[cut:].lstrip()
                if len(cur) + len(piece) > limit:
                    flush()
                cur += piece
            flush()
            continue
        if len(cur) + len(sent) > limit:
            flush()
        cur += sent
    flush()
    return out


def options(extra: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Os ajustes de `generate` a partir do campo «Extra» do nó (cfg_value, inference_timesteps, normalize, denoise, retry_badcase…): os desconhecidos são ignorados e os valores ficam nos limites."""
    out: Dict[str, Any] = dict(DEFAULTS)
    for key, val in (extra or {}).items():
        spec = _KNOWN.get(key)
        if not spec:
            continue
        try:
            if spec[0] is bool:
                out[key] = bool(val)
            else:
                v = spec[0](val)
                out[key] = max(spec[1], min(spec[2], v))
        except (TypeError, ValueError):
            continue
    return out
