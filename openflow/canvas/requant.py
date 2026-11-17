"""Criar uma faixa de quantização que o repositório não tem (v0.81): a partir de um GGUF já baixado, o OpenFlow gera o Q2, Q3, Q4, Q6 ou Q8 que faltar — e assim TODO modelo baixado pode ser usado em qualquer faixa.

- **Imagem e vídeo:** `sd-cli -M convert -m origem.gguf -o destino.gguf --type q4_K` (a stable-diffusion.cpp relê os tensores e grava de novo na faixa pedida).
- **Texto:** `llama_model_quantize` da biblioteca llama-cpp-python (com `allow_requantize`), num processo à parte (dá para cancelar e uma falha da biblioteca não derruba o OpenFlow).

Limites honestos: comprimir um arquivo que já é comprimido (Q8 → Q4) perde mais qualidade do que comprimir o original (F16/BF16 → Q4): por isso a origem é sempre o arquivo de MAIS bits que você tem. Só funciona com arquivos
inteiros (um modelo dividido em partes `-0000N-of-0000M` não é aceito) e precisa de espaço livre para o arquivo novo. Os comandos foram escritos de acordo com a documentação e o código da stable-diffusion.cpp e do
llama.cpp, mas NÃO foram executados contra os programas de verdade.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import hf
from ..providers.base import ProviderError
from . import quants, sdcli

KINDS = ("text", "image", "video")
_LLAMA_SCRIPT = (
    "import sys, ctypes\n"
    "import llama_cpp\n"
    "p = llama_cpp.llama_model_quantize_default_params()\n"
    "p.ftype = int(sys.argv[3])\n"
    "p.allow_requantize = True\n"
    "p.nthread = 0\n"
    "r = llama_cpp.llama_model_quantize(sys.argv[1].encode('utf-8'), sys.argv[2].encode('utf-8'), ctypes.byref(p))\n"
    "sys.exit(0 if r == 0 else 3)\n"
)


def sources(models_dir: Path, kind: str) -> List[Dict[str, Any]]:
    """Os modelos baixados de um tipo que dá para usar de origem (inteiros, com a faixa conhecida)."""
    return [m for m in hf.local_models(models_dir, kind) if m.get("parts", 1) <= 1 and m.get("bits")]


def plan(models_dir: Path, kind: str, name: str, tier: str) -> Dict[str, Any]:
    """O que seria feito: {src, dst, tier, estimate (bytes)}; levanta ProviderError dizendo por que não dá."""
    if kind not in KINDS:
        raise ProviderError("Só modelos de texto, imagem e vídeo (GGUF) podem ganhar uma faixa nova.")
    if tier not in quants.TIERS:
        raise ProviderError("Escolha a faixa: Q2, Q3, Q4, Q6 ou Q8.")
    folder = hf.kind_dir(models_dir, kind)
    src = folder / Path(name).name
    if src.suffix.lower() != ".gguf" or not src.is_file():
        raise ProviderError("Esse arquivo GGUF não foi baixado (ou não está nesta pasta).")
    if hf.SHARD_RE.match(src.name):
        raise ProviderError("Este modelo está dividido em partes (-0000N-of-0000M): só dá para criar uma faixa a partir de um arquivo inteiro.")
    info = hf.parse_quant(src.name)
    bits = int(info.get("bits") or 0)
    if not bits:
        raise ProviderError("Não consegui saber a quantização deste arquivo pelo nome; renomeie-o com a faixa (ex.: modelo-Q8_0.gguf).")
    if bits <= quants.NOMINAL[tier]:
        raise ProviderError(f"Este arquivo já é {info['quant']} ({bits} bits): só dá para criar uma faixa com MENOS bits que ele ({tier} tem {quants.NOMINAL[tier]}). Use um arquivo maior (Q8, F16…) de origem.")
    dst = folder / quants.target_name(src.name, tier)
    if dst.exists():
        raise ProviderError(f"{dst.name} já existe.")
    eff = 16 if bits >= 16 else quants.BITS.get(f"Q{bits}", bits)
    return {"src": src, "dst": dst, "tier": tier, "estimate": int(src.stat().st_size * quants.BITS[tier] / max(eff, 1.0)), "from": info["quant"]}


def _need_space(dst: Path, estimate: int) -> None:
    try:
        free = shutil.disk_usage(dst.parent).free
    except OSError:
        return
    need = int(estimate * 1.1)
    if free < need:
        raise ProviderError(f"Sem espaço em disco para criar «{dst.name}»: faltam ≈ {need / 1024 ** 3:.1f} GB e há {free / 1024 ** 3:.1f} GB livres em {dst.parent}. Libere espaço ou apague outro modelo.")


def convert_sdcli(exe: Path, src: Path, tmp: Path, tier: str, cancelled: Callable[[], bool], note: Callable[[str], None]) -> None:
    args = [str(exe), "-M", "convert", "-m", str(src), "-o", str(tmp), "--type", quants.SD_TYPE[tier]]
    try:
        sdcli.run(args, exe, cancelled, note, timeout=6 * 3600)
    except ProviderError as exc:
        if "invalid weight format" in str(exc):
            raise ProviderError(f"O sd-cli instalado não conhece o formato {quants.SD_TYPE[tier]}. Atualize-o (flow update).") from None
        raise


def convert_llama(src: Path, tmp: Path, tier: str, cancelled: Callable[[], bool], note: Callable[[str], None]) -> None:
    name, ftype = quants.LLAMA_TYPE[tier]
    note(f"Comprimindo para {name} com o llama.cpp…")
    p = subprocess.Popen([sys.executable, "-c", _LLAMA_SCRIPT, str(src), str(tmp), str(ftype)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    start = time.time()
    try:
        while p.poll() is None:
            if cancelled():
                p.terminate()
                raise ProviderError("cancelado")
            if time.time() - start > 6 * 3600:
                p.terminate()
                raise ProviderError("A compressão demorou demais e foi interrompida.")
            time.sleep(0.3)
    finally:
        if p.poll() is None:
            p.kill()
        out = p.stdout.read() if p.stdout else ""
        p.wait()
        if p.stdout:
            p.stdout.close()
    if p.returncode != 0:
        if "No module named" in out and "llama_cpp" in out:
            raise ProviderError("Comprimir um modelo de texto precisa da biblioteca llama-cpp-python:  pip install llama-cpp-python  (ou rode: flow libs --extras local).")
        raise ProviderError("O llama.cpp não conseguiu comprimir o arquivo (código %s): %s" % (p.returncode, " | ".join(ln.strip() for ln in out.strip().splitlines()[-4:])[:500] or "sem mensagem"))


def create(models_dir: Path, kind: str, name: str, tier: str, cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None) -> Path:
    """Cria o arquivo da faixa `tier` a partir do GGUF baixado `name` e devolve o caminho. O arquivo só aparece com o nome final quando está completo (antes, `.converting.gguf`)."""
    pl = plan(models_dir, kind, name, tier)
    src, dst = pl["src"], pl["dst"]
    _need_space(dst, pl["estimate"])
    exe: Optional[Path] = None
    if kind in ("image", "video"):
        exe = sdcli.find()
        if exe is None:
            raise ProviderError("Criar uma faixa de imagem/vídeo precisa do sd-cli (stable-diffusion.cpp). Rode  flow update  ou use o botão «Baixar o executável pronto» em um nó de imagem.")
    tmp = dst.with_name(dst.stem + ".converting.gguf")
    tmp.unlink(missing_ok=True)
    note(f"Criando {dst.name} a partir de {src.name} ({pl['from']} → {tier}); ≈ {pl['estimate'] / 1024 ** 3:.1f} GB.")
    try:
        if exe is not None:
            convert_sdcli(exe, src, tmp, tier, cancelled, note)
        else:
            convert_llama(src, tmp, tier, cancelled, note)
        if not tmp.is_file() or tmp.stat().st_size < 1024:
            raise ProviderError("A compressão terminou sem gerar o arquivo. Veja o terminal onde o OpenFlow roda.")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    return dst
