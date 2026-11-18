"""Faixas de quantização (Q2, Q3, Q4, Q6, Q8) dos arquivos de apoio de um modelo: os **codificadores de texto** (LLM, T5/UMT5, CLIP) e os **VAEs** (v0.89).

Três coisas, sem tocar no modelo de difusão:

1. **Achar as faixas que já estão na pasta** (`variants`, `present`): o mesmo arquivo em outra faixa tem o mesmo «radical» (`t5xxl_fp8_e4m3fn.safetensors` e `t5xxl_fp8_e4m3fn-Q4_K.gguf`).
2. **Obter uma faixa que falta:** baixar a pronta do repositório (quando o repositório do arquivo tem GGUF nessa faixa, `repo_option`) ou criar uma a partir do arquivo baixado (`plan`/`requant.create`:
   `llama_model_quantize` para LLM em GGUF, `sd-cli -M convert` para T5/UMT5/CLIP/VAE).
3. **Usar a faixa pedida ao carregar o modelo** (`swap_tier`): troca, na carga do modelo, o arquivo de apoio pelo da faixa pedida no nó (campo «Faixa dos arquivos de apoio»).

Limites honestos: a quantização do ggml só atinge tensores cuja primeira dimensão é múltipla do bloco (32; 256 nas faixas «K»). Os pesos de convolução 3×3 de um **VAE** não são (o 3 não divide o bloco): num VAE
quase nada é quantizado, o arquivo mal encolhe e `create` avisa o tamanho que deu. Nos codificadores de texto (camadas lineares grandes) o ganho é o esperado. Os comandos seguem a documentação e o código da
stable-diffusion.cpp e do llama.cpp, mas NÃO foram executados contra os programas de verdade."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import hf
from ..providers.base import ProviderError
from . import quants

#: parâmetros de carga que são codificador de texto ou VAE (o resto — mmproj, CLIP vision, VAE de áudio, tokenizador — fica como está)
QUANT_KEYS = ("vae_path", "llm_path", "t5xxl_path", "clip_l_path", "clip_g_path")
ROLE_OF = {"vae_path": "vae", "llm_path": "text_encoder", "t5xxl_path": "text_encoder", "clip_l_path": "text_encoder", "clip_g_path": "text_encoder"}
ROLE_LABEL = {"vae": "VAE", "text_encoder": "Codificador de texto"}
#: do que tem mais qualidade para o que tem menos: a ordem em que o «Automático» escolhe entre as faixas que já estão na pasta (a Q2 criada de propósito nunca vira a escolha por acaso)
AUTO_ORDER = ("Q8", "Q6", "Q4", "Q3", "Q2")
#: repositórios com GGUF prontos de codificadores que a família baixa como .safetensors (o repositório do .safetensors não tem faixas)
GGUF_REPOS = {r"^t5xxl": "city96/t5-v1_1-xxl-encoder-gguf"}

_EXT = re.compile(r"\.(safetensors|gguf)$", re.I)
_SKIP = re.compile(r"(\.part$|\.converting\.gguf$|mmproj|clip[_-]?vision|audio[_-]?vae|tokenizer)", re.I)
_SHARD = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)


def stem(name: str) -> str:
    """O «radical» de um arquivo: sem extensão, sem o tipo de quantização/precisão (Q4_K_M, UD-, BF16…): `qwen3-8b-UD-Q4_K_XL.gguf` e `qwen3-8b-Q8_0.gguf` → `qwen3-8b`."""
    base = _EXT.sub("", Path(name).name)
    base = re.sub(r"[-_.]UD(?=[-_.]|$)", "", base, flags=re.I)
    base = hf.QUANT_RE.sub("", base)
    return re.sub(r"[-_.]{2,}", "-", base).strip("-_. ").lower()


def bits_of(name: str) -> int:
    """Bits por peso do arquivo pelo nome: GGUF → o do tipo («Q8_0» 8, «BF16» 16); .safetensors → «fp8» 8, senão 16 (o padrão de um checkpoint de apoio). 0 se não dá para saber."""
    low = Path(name).name.lower()
    if low.endswith(".gguf"):
        return int(hf.parse_quant(name).get("bits") or 0)
    if re.search(r"(?<![a-z0-9])fp8", low):
        return 8
    if re.search(r"(?<![a-z0-9])(fp32|f32)", low):
        return 32
    return 16


def companion_key(name: str) -> str:
    """Qual parâmetro de carga («vae_path», «llm_path», «t5xxl_path», «clip_l_path»…) este arquivo é nas receitas das famílias; «» se não é codificador de texto nem VAE de nenhuma delas."""
    from . import support

    n = Path(name).name
    if not _EXT.search(n) or _SKIP.search(n):
        return ""
    want = stem(n)
    for fam in support.FAMILIES:   # pelo padrão de nome que a família usa para achar o arquivo…
        for key, pat in (fam.get("load") or {}).items():
            if key in QUANT_KEYS and re.search(pat, n, re.I):
                return key
    for fam in support.FAMILIES:   # …ou pelo radical do arquivo que ela baixa (pega também as faixas criadas: «ae-Q4_K.gguf»)
        for key, spec in (fam.get("downloads") or {}).items():
            if key in QUANT_KEYS and spec.get("file") and stem(spec.get("dest") or spec["file"]) == want:
                return key
    return ""


def is_support_file(name: str) -> bool:
    """É o codificador de texto ou o VAE de alguma família conhecida (e não o modelo de difusão, o mmproj, o CLIP vision, o VAE de áudio ou o tokenizador)?"""
    return bool(companion_key(name))


def tool_for(name: str) -> str:
    """O programa que comprime este arquivo: «llama» (LLM em GGUF: Qwen, Mistral…) ou «sdcli» (T5/UMT5/CLIP e VAE, em safetensors ou GGUF)."""
    return "llama" if companion_key(name) == "llm_path" and Path(name).name.lower().endswith(".gguf") else "sdcli"


def target_name(name: str, tier: str) -> str:
    """O nome do arquivo criado: «t5xxl_fp8_e4m3fn.safetensors» → «t5xxl_fp8_e4m3fn-Q4_K.gguf»; um GGUF troca o tipo («x-Q8_0.gguf» → «x-Q4_K.gguf»)."""
    n = Path(name).name
    if n.lower().endswith(".gguf"):
        return quants.target_name(n, tier)
    return _EXT.sub("", n) + "-" + quants.FILE_LABEL[tier] + ".gguf"


def variants(folder: Path, name: str) -> List[Dict[str, Any]]:
    """Os arquivos de `folder` que são o MESMO arquivo de apoio `name` em outra faixa/precisão (inclusive ele): [{name, size, quant, bits, tier, format}], dos de mais bits para os de menos."""
    want = stem(name)
    out: List[Dict[str, Any]] = []
    if not want or not Path(folder).is_dir():
        return out
    for f in sorted(Path(folder).iterdir()):
        if not f.is_file() or _SKIP.search(f.name) or not _EXT.search(f.name) or _SHARD.search(f.name) or stem(f.name) != want:
            continue
        q = hf.parse_quant(f.name) if f.suffix.lower() == ".gguf" else {"quant": "", "bits": bits_of(f.name)}
        out.append({"name": f.name, "size": f.stat().st_size, "quant": q.get("quant", ""), "bits": int(q.get("bits") or 0), "tier": quants.tier_of(q.get("quant", "")), "format": f.suffix.lower().lstrip(".")})
    return sorted(out, key=lambda v: (-v["bits"], v["name"]))


def present(folder: Path, name: str) -> Dict[str, Dict[str, Any]]:
    """{faixa: arquivo} das faixas Q2…Q8 que já estão na pasta para este arquivo de apoio (a preferida de cada faixa)."""
    vs = variants(folder, name)
    out: Dict[str, Dict[str, Any]] = {}
    for t in quants.TIERS:
        v = quants.pick(vs, t)
        if v:
            out[t] = v
    return out


def auto_rank(name: str, default_name: str = "") -> Tuple[int, int, str]:
    """A ordem do «Automático» entre arquivos do mesmo apoio: o arquivo padrão da família primeiro, depois o original (safetensors/BF16/F16/F32), depois Q8 → Q2."""
    n = Path(name).name
    if default_name and n.lower() == Path(default_name).name.lower():
        return (0, 0, n)
    t = quants.tier_of(hf.parse_quant(n).get("quant", "")) if n.lower().endswith(".gguf") else ""
    if not t:
        return (1, 0, n)
    return (2, AUTO_ORDER.index(t), n)


def swap_tier(folder: Path, load: Dict[str, Any], tier: str) -> Tuple[Dict[str, Any], List[str]]:
    """Na carga do modelo, troca cada codificador de texto/VAE pela faixa `tier` que já está na pasta. Devolve (carga, avisos): o que não tem essa faixa fica como está, com o aviso de como instalar."""
    if not tier:
        return load, []
    out, notes = dict(load), []
    for key in QUANT_KEYS:
        v = load.get(key)
        if not isinstance(v, str) or not v or v == "@model":
            continue
        cur = Path(v).name
        have = present(Path(folder), cur)
        got = have.get(tier)
        role = ROLE_LABEL[ROLE_OF[key]]
        if got:
            out[key] = got["name"]
            continue
        vs = variants(Path(folder), cur)
        c = next((x for x in vs if x["name"] == cur), None)
        if c and c["tier"] == tier:
            continue
        notes.append(f"{role} ({cur}) não tem a faixa {tier} instalada: usei o arquivo como está. Instale em Biblioteca → Arquivos de apoio (ou: flow models support --tier {tier}).")
    return out, notes


# --------------------------------------------------------------------------- criar uma faixa a partir do arquivo baixado
def plan(folder: Path, name: str, tier: str) -> Dict[str, Any]:
    """O que seria feito para criar a faixa `tier` do arquivo de apoio `name`: {src, dst, tool, from}; levanta ProviderError dizendo por que não dá."""
    folder = Path(folder)
    if tier not in quants.TIERS:
        raise ProviderError("Escolha a faixa: Q2, Q3, Q4, Q6 ou Q8.")
    src = folder / Path(name).name
    if not src.is_file() or not _EXT.search(src.name):
        raise ProviderError("Esse arquivo de apoio não foi baixado (ou não está nesta pasta).")
    if _SHARD.search(src.name):
        raise ProviderError("Este arquivo está dividido em partes (-0000N-of-0000M): só dá para criar uma faixa a partir de um arquivo inteiro.")
    cands = [v for v in variants(folder, src.name) if v["bits"] > quants.NOMINAL[tier] and not _SHARD.search(v["name"])]
    if not cands:
        bits = bits_of(src.name)
        raise ProviderError(f"{src.name} já é {('de ' + str(bits) + ' bits') if bits else 'pequeno'}: só dá para criar uma faixa com MENOS bits que o arquivo de origem ({tier} tem {quants.NOMINAL[tier]}). Use uma versão maior (Q8, BF16, F16…) de origem.")
    best = max(cands, key=lambda v: (v["bits"], v["size"]))
    dst = folder / target_name(best["name"], tier)
    if dst.exists():
        raise ProviderError(f"{dst.name} já existe.")
    return {"src": folder / best["name"], "dst": dst, "tool": tool_for(best["name"]), "from": best["quant"] or (f"{best['bits']} bits" if best["bits"] else "original"), "tier": tier}


def size_note(src: Path, dst: Path) -> str:
    """Um resumo do tamanho depois de criar a faixa, com o aviso de que um VAE quase não encolhe (as convoluções 3×3 não entram na quantização do ggml)."""
    a, b = src.stat().st_size, dst.stat().st_size
    msg = f"{dst.name}: {b / 1024 ** 2:.0f} MB (o original tem {a / 1024 ** 2:.0f} MB)."
    if companion_key(src.name) == "vae_path" and b > 0.9 * a:
        msg += " Um VAE tem poucos pesos quantizáveis (as convoluções 3×3 ficam como estão): o arquivo mal encolheu."
    return msg


# --------------------------------------------------------------------------- baixar a faixa pronta do repositório do arquivo
def repo_option(name: str, tier: str, token: str = "") -> Optional[Dict[str, Any]]:
    """A faixa `tier` PRONTA, num repositório do Hugging Face, do arquivo de apoio `name` (pelas receitas das famílias): {repo, file, size} ou None. Consulta a rede só se há um repositório com GGUF para o arquivo."""
    from . import support

    want = stem(name)
    repo = ""
    for fam in support.FAMILIES:
        for key, spec in (fam.get("downloads") or {}).items():
            if key not in QUANT_KEYS or not spec.get("repo"):
                continue
            base = Path(spec.get("dest") or spec["file"]).name
            if stem(base) != want:
                continue
            if base.lower().endswith(".gguf"):
                repo = spec["repo"]
            else:
                repo = next((r for pat, r in GGUF_REPOS.items() if re.search(pat, base, re.I)), "")
            if repo:
                break
        if repo:
            break
    if not repo:
        return None
    files = []
    for f in hf.repo_files(repo, token):
        n = Path(f["name"]).name
        if not n.lower().endswith(".gguf") or _SHARD.search(n) or _SKIP.search(n):
            continue
        q = hf.parse_quant(n)
        files.append({"name": f["name"], "size": f["size"], "quant": q["quant"], "tier": quants.tier_of(q["quant"])})
    got = quants.pick(files, tier)
    return {"repo": repo, "file": got["name"], "size": got["size"]} if got else None


def listing(models_dir: Path) -> List[Dict[str, Any]]:
    """Os arquivos de apoio (codificadores de texto e VAEs) baixados nas pastas de imagem e de vídeo, com a faixa de cada um e as faixas que ainda dá para obter: sem rede."""
    out: List[Dict[str, Any]] = []
    for kind in ("image", "video"):
        folder = hf.kind_dir(models_dir, kind)
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            key = companion_key(f.name) if f.is_file() else ""
            if not key or _SHARD.search(f.name):
                continue
            q = hf.parse_quant(f.name) if f.suffix.lower() == ".gguf" else {"quant": "", "bits": bits_of(f.name)}
            bits = int(q.get("bits") or 0)
            role = ROLE_OF[key]
            have = present(folder, f.name)
            out.append({"kind": kind, "name": f.name, "size": f.stat().st_size, "key": key, "role": role, "role_label": ROLE_LABEL[role], "quant": q.get("quant", ""), "bits": bits, "format": f.suffix.lower().lstrip("."),
                        "tier": quants.tier_of(q.get("quant", "")), "have": sorted(have), "lower": [t for t in quants.TIERS if bits > quants.NOMINAL[t] and t not in have]})
    return out


# --------------------------------------------------------------------------- obter uma faixa: baixar pronta ou criar
def dest_name_for(name: str, repo_file: str, quant: str) -> str:
    """Como gravar a faixa baixada: com o MESMO radical do arquivo de apoio que a pessoa já tem (para `swap_tier` achá-la), mesmo que o repositório a chame de outra coisa."""
    got = Path(repo_file).name
    if stem(got) == stem(name):
        return got
    base = _EXT.sub("", Path(name).name)
    base = hf.QUANT_RE.sub("", re.sub(r"[-_.]UD(?=[-_.]|$)", "", base, flags=re.I)).strip("-_. ")
    return f"{base}-{quant or 'GGUF'}.gguf"


def install_tier(models_dir: Path, kind: str, name: str, tier: str, how: str = "auto", token: str = "", progress: Optional[Callable[[int, int], None]] = None,
                 cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None) -> Dict[str, Any]:
    """Põe na pasta a faixa `tier` do arquivo de apoio `name`: «download» baixa a pronta do repositório, «create» a cria do arquivo baixado, «auto» tenta baixar e, se o repositório não tem essa faixa
    (ou não há rede), cria. Devolve {name, how}; levanta ProviderError com o motivo se nada serviu."""
    from . import requant

    if kind not in ("image", "video"):
        raise ProviderError("Os arquivos de apoio ficam nas pastas de imagem e de vídeo.")
    if tier not in quants.TIERS:
        raise ProviderError("Escolha a faixa: Q2, Q3, Q4, Q6 ou Q8.")
    if how not in ("auto", "download", "create"):
        raise ProviderError("Escolha como obter: baixar, criar ou automático.")
    folder = hf.kind_dir(models_dir, kind, create=True)
    if not companion_key(name):
        raise ProviderError("Esse arquivo não é um codificador de texto nem um VAE conhecido.")
    have = present(folder, name).get(tier)
    if have:
        return {"name": have["name"], "how": "present"}
    why = ""
    if how in ("auto", "download"):
        note("Procurando a faixa pronta no repositório…")
        try:
            opt = repo_option(name, tier, token)
        except ProviderError as exc:
            opt, why = None, str(exc)
        except Exception as exc:  # noqa: BLE001 — sem rede, repositório fora do ar…
            opt, why = None, f"não consegui consultar o repositório ({type(exc).__name__})"
        if opt:
            dest = dest_name_for(name, opt["file"], hf.parse_quant(opt["file"]).get("quant", ""))
            note(f"Baixando {Path(opt['file']).name} de {opt['repo']} ({opt['size'] / 1024 ** 3:.1f} GB)…")
            hf.download(opt["repo"], opt["file"], folder, token, progress, cancelled, any_file=True, dest_name=dest)
            return {"name": dest, "how": "download"}
        if how == "download":
            raise ProviderError(f"Não há uma faixa {tier} pronta para {name} nos repositórios conhecidos" + (f" ({why})" if why else "") + ". Use «Criar» para comprimir o arquivo que você já tem.")
        note("Sem faixa pronta" + (f" ({why})" if why else "") + f": criando a {tier} a partir do arquivo baixado…")
    path = requant.create(models_dir, kind, name, tier, cancelled, note)
    return {"name": path.name, "how": "create"}


def ensure_for_model(models_dir: Path, kind: str, model: str, tier: str, token: str = "", progress: Optional[Callable[[int, int], None]] = None,
                     cancelled: Callable[[], bool] = lambda: False, note: Callable[[str], None] = lambda m: None) -> Tuple[List[str], List[Dict[str, str]]]:
    """Depois de instalar os arquivos de apoio de um modelo (`model`, de `kind`), obtém a faixa `tier` do codificador de texto e do VAE dele: ([arquivos obtidos], [{label, error}])."""
    from . import support

    got: List[str] = []
    failed: List[Dict[str, str]] = []
    if not tier:
        return got, failed
    folder = hf.kind_dir(models_dir, kind)
    fam = support.family_of(model)
    if kind not in ("image", "video") or not fam:
        return got, failed
    for key, cname in support.find_companions(folder, folder / Path(model).name, fam).items():
        if key not in QUANT_KEYS or not cname:
            continue
        try:
            res = install_tier(models_dir, kind, cname, tier, "auto", token, progress, cancelled, note)
            if res["how"] != "present":
                got.append(res["name"])
        except ProviderError as exc:
            if str(exc) == "cancelado":
                raise
            failed.append({"label": f"{cname} → {tier}", "error": str(exc)})
    return got, failed
