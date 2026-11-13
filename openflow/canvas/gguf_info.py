"""Leitura mínima do cabeçalho de um arquivo GGUF: os nomes dos tensores (sem carregar pesos). Serve para saber, antes de entregar o arquivo à stable-diffusion.cpp,
se ele tem o que ela procura para reconhecer o modelo — quando não reconhece, a biblioteca derruba o programa inteiro (falha de segmentação) em vez de dar erro."""
from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO, List, Optional

_SCALAR = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}   # tipos GGUF de tamanho fixo (uint8…float64); 8 = string; 9 = array
MAX_NAMES = 200000


def _u32(f: BinaryIO) -> int:
    return struct.unpack("<I", f.read(4))[0]


def _u64(f: BinaryIO) -> int:
    return struct.unpack("<Q", f.read(8))[0]


def _skip_value(f: BinaryIO, vtype: int) -> None:
    if vtype in _SCALAR:
        f.seek(_SCALAR[vtype], 1)
    elif vtype == 8:
        f.seek(_u64(f), 1)
    elif vtype == 9:
        et, n = _u32(f), _u64(f)
        if et in _SCALAR:
            f.seek(_SCALAR[et] * n, 1)
        else:
            for _ in range(min(n, 10_000_000)):
                _skip_value(f, et)
    else:
        raise ValueError("tipo GGUF desconhecido")


def tensor_names(path: Path, limit: int = MAX_NAMES) -> Optional[List[str]]:
    """Nomes dos tensores de um GGUF; None se o arquivo não é um GGUF legível (nesse caso não há o que conferir)."""
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return None
            version = _u32(f)
            if version < 2:
                return None
            n_tensors, n_kv = _u64(f), _u64(f)
            if n_tensors > MAX_NAMES or n_kv > 1_000_000:
                return None
            for _ in range(n_kv):
                f.seek(_u64(f), 1)          # chave
                _skip_value(f, _u32(f))     # valor
            names: List[str] = []
            for _ in range(min(n_tensors, limit)):
                ln = _u64(f)
                if ln > 4096:
                    return None
                names.append(f.read(ln).decode("utf-8", "replace"))
                n_dims = _u32(f)
                f.seek(8 * n_dims + 4 + 8, 1)   # dimensões, tipo, deslocamento
            return names
    except (OSError, struct.error, ValueError):
        return None
