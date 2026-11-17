"""As cinco faixas de quantização do OpenFlow (v0.81): Q2, Q3, Q4, Q6 e Q8 para TODOS os modelos, para quem tem pouca memória.

«Q8» quer dizer ≈ 8 bits por peso, «Q4» ≈ 4 bits… (nos arquivos GGUF são os tipos Q8_0, Q6_K, Q4_K, Q3_K e Q2_K do llama.cpp). Quanto menos bits, menor o arquivo e a memória usada — e pior a qualidade.
O que é de cada formato:

- **GGUF** (texto, imagem, vídeo): cada repositório traz as faixas que o autor quis. Aqui cada arquivo ganha a sua faixa (`tier_of`), a lista mostra as cinco (as que faltam aparecem apagadas) e uma faixa que falta
  pode ser **criada** a partir de um arquivo já baixado (`requant.py`: sd-cli `-M convert` para imagem/vídeo, `llama_model_quantize` para texto) ou **usada na hora** em imagem/vídeo (a stable-diffusion.cpp
  recomprime os pesos ao carregar: `--type`).
- **Original** (diffusers/transformers): a faixa é escolhida no download (como a precisão fp16/bf16) e os pesos são comprimidos AO CARREGAR (bitsandbytes na placa NVIDIA, ou optimum-quanto em qualquer
  aparelho, inclusive a CPU). O download continua do tamanho do fp16; a memória usada cai. O formato original só tem 8, 4 e 2 bits: Q6 usa 8 e Q3 usa 4 (o vizinho de cima, que não piora a qualidade).

Aqui fica o que não depende de modelo, bibliotecas nem rede (Python puro, testável).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

TIERS = ("Q2", "Q3", "Q4", "Q6", "Q8")
#: bits por peso de verdade de cada faixa (os tipos K guardam escalas junto dos pesos), para estimar o tamanho de um arquivo a partir do fp16 (16 bits)
BITS = {"Q2": 2.6, "Q3": 3.5, "Q4": 4.6, "Q6": 6.6, "Q8": 8.5}
NOMINAL = {"Q2": 2, "Q3": 3, "Q4": 4, "Q6": 6, "Q8": 8}
LABELS = {"Q2": "Q2 · ≈ 2–3 bits: o menor; perde bastante qualidade", "Q3": "Q3 · ≈ 3 bits: bem pequeno; perde qualidade", "Q4": "Q4 · ≈ 4 bits: o melhor equilíbrio para quem tem pouca memória",
          "Q6": "Q6 · ≈ 6 bits: quase igual ao original", "Q8": "Q8 · ≈ 8 bits: praticamente sem perda"}
#: tipo da stable-diffusion.cpp (`--type`, no sd-cli) de cada faixa
SD_TYPE = {"Q2": "q2_K", "Q3": "q3_K", "Q4": "q4_K", "Q6": "q6_K", "Q8": "q8_0"}
#: tipo do llama.cpp (nome, valor de `LLAMA_FTYPE_MOSTLY_*`) de cada faixa
LLAMA_TYPE = {"Q2": ("Q2_K", 10), "Q3": ("Q3_K_M", 12), "Q4": ("Q4_K_M", 15), "Q6": ("Q6_K", 18), "Q8": ("Q8_0", 7)}
#: como as faixas se chamam no nome de um arquivo criado aqui (`modelo-Q4_K.gguf`)
FILE_LABEL = {"Q2": "Q2_K", "Q3": "Q3_K", "Q4": "Q4_K", "Q6": "Q6_K", "Q8": "Q8_0"}
#: qual arquivo da faixa o OpenFlow recomenda (o primeiro que o repositório tiver)
PREFERENCE = {"Q2": ("Q2_K", "Q2_K_S", "Q2_K_L", "Q2_K_XL", "IQ2_M", "IQ2_S", "IQ2_XS", "IQ2_XXS"),
              "Q3": ("Q3_K_M", "Q3_K_S", "Q3_K_L", "Q3_K_XL", "Q3_K", "IQ3_M", "IQ3_S", "IQ3_XS", "IQ3_XXS"),
              "Q4": ("Q4_K_M", "Q4_K_S", "Q4_K", "Q4_K_L", "Q4_K_XL", "Q4_0", "Q4_1", "IQ4_XS", "IQ4_NL"),
              "Q6": ("Q6_K", "Q6_K_L", "Q6_K_XL"),
              "Q8": ("Q8_0", "Q8_K_XL", "Q8_K")}
_TIER_RE = re.compile(r"^(?:UD-)?(?:IQ|Q|TQ)(\d)", re.I)


def tier_of(quant: str) -> str:
    """«Q4_K_M» → «Q4», «IQ3_XS» → «Q3», «UD-Q8_K_XL» → «Q8». Q5, Q1, F16, BF16… não são uma das cinco faixas: «»."""
    m = _TIER_RE.match((quant or "").strip())
    if not m:
        return ""
    t = f"Q{m.group(1)}"
    return t if t in TIERS else ""


def estimate(fp16_bytes: int, tier: str) -> int:
    """O tamanho aproximado de um modelo de `fp16_bytes` bytes na faixa `tier`."""
    return int(fp16_bytes * BITS[tier] / 16.0) if tier in BITS and fp16_bytes > 0 else 0


def _rank(quant: str, tier: str) -> int:
    q = (quant or "").upper().replace("UD-", "")
    order = PREFERENCE.get(tier, ())
    return order.index(q) if q in order else len(order)


def pick(files: Sequence[Dict[str, Any]], tier: str) -> Optional[Dict[str, Any]]:
    """O arquivo da faixa `tier` (ou None): o de nome preferido (Q4_K_M antes de Q4_0…); entre iguais, o menor."""
    cand = [f for f in files if (f.get("tier") or tier_of(f.get("quant", ""))) == tier]
    return min(cand, key=lambda f: (_rank(f.get("quant", ""), tier), f.get("size", 0), f.get("name", ""))) if cand else None


def summary(files: Sequence[Dict[str, Any]], ram_gb: float = 0.0) -> List[Dict[str, Any]]:
    """As cinco faixas de um repositório GGUF: [{tier, bits, label, has, name, quant, size, fits, recommended}]. A recomendada é a MAIOR faixa que cabe em 60 % da RAM (a melhor qualidade possível);
    sem saber a RAM, Q4."""
    out = []
    for t in TIERS:
        f = pick(files, t)
        out.append({"tier": t, "bits": NOMINAL[t], "label": LABELS[t], "has": bool(f), "name": f["name"] if f else "", "quant": f.get("quant", "") if f else "", "size": f.get("size", 0) if f else 0,
                    "fits": bool(f) and bool(ram_gb) and f["size"] <= ram_gb * 0.6 * 1024 ** 3, "recommended": False})
    have = [o for o in out if o["has"]]
    best = None
    if ram_gb:
        fitting = [o for o in have if o["fits"]]
        best = max(fitting, key=lambda o: o["bits"]) if fitting else (min(have, key=lambda o: o["size"]) if have else None)
    elif have:
        best = next((o for o in have if o["tier"] == "Q4"), have[0])
    if best:
        best["recommended"] = True
    return out


def recommend_original(fp16_bytes: int, ram_gb: float) -> str:
    """Para um modelo original (fp16 de `fp16_bytes`): a MAIOR faixa cujo uso estimado cabe em 60 % da RAM; «» se o fp16 já cabe (ou não dá para saber)."""
    if not fp16_bytes or not ram_gb:
        return ""
    limit = ram_gb * 0.6 * 1024 ** 3
    if fp16_bytes <= limit:
        return ""
    for t in reversed(TIERS):
        if estimate(fp16_bytes, t) <= limit:
            return t
    return "Q2"


def sd_cli_type(wtype: str) -> str:
    """O nome que o sd-cli (`--type`) aceita para o nome que a biblioteca Python usa («q4_k» → «q4_K»)."""
    m = re.match(r"^q(\d)_k$", wtype or "", re.I)
    return f"q{m.group(1)}_K" if m else wtype


def wanted(value: Any) -> str:
    """A faixa pedida no campo «quant» do nó («Q4», «q4», «Q4_K_M»…) → «Q4»; «» se não pediu nenhuma (ou não é uma faixa)."""
    v = str(value or "").strip()
    return tier_of(v) if v else ""


def with_weight_type(load: Dict[str, Any], file_quant: str, tier: str) -> Tuple[Dict[str, Any], str]:
    """Usa um arquivo na faixa `tier` mesmo que ele seja de outra: pede à stable-diffusion.cpp que recomprima os pesos ao carregar (`wtype`). Devolve (carga, aviso). Só vale para uma faixa MENOR que
    a do arquivo (recomprimir para cima não devolve qualidade); a igual não faz nada."""
    if not tier:
        return load, ""
    have = tier_of(file_quant)
    if have and NOMINAL[have] <= NOMINAL[tier]:
        return load, ("" if have == tier else f"O arquivo já é {have}: não há o que comprimir para {tier} (a quantização pedida só vale para uma faixa menor que a do arquivo).")
    return {**load, "wtype": SD_TYPE[tier].lower()}, f"Comprimindo os pesos para {tier} ao carregar (a stable-diffusion.cpp recomprime o arquivo{' ' + file_quant if file_quant else ''}): a carga demora um pouco mais, a memória cai."


def target_name(src_name: str, tier: str) -> str:
    """O nome do arquivo criado: o quant do nome de origem trocado pelo da faixa («modelo-Q8_0.gguf» → «modelo-Q4_K.gguf»; sem quant no nome, ele é acrescentado)."""
    stem = src_name[:-5] if src_name.lower().endswith(".gguf") else src_name
    label = FILE_LABEL[tier]
    new, n = re.subn(r"(?<![A-Za-z0-9])(?:UD-)?(?:IQ|Q)\d(?:_[A-Z0-9]+)*|(?<![A-Za-z0-9])(?:BF16|F16|F32)(?![A-Za-z0-9])", label, stem, count=1, flags=re.I)
    return (new if n else f"{stem}-{label}") + ".gguf"


def best_source(candidates: Sequence[Dict[str, Any]], tier: str) -> Optional[Dict[str, Any]]:
    """De qual arquivo já baixado criar a faixa `tier`: o de MAIS bits (menos perda na recompressão) entre os de bits acima da faixa. Arquivos divididos em partes ficam de fora."""
    ok = [c for c in candidates if int(c.get("parts", 1) or 1) <= 1 and int(c.get("bits", 0) or 0) > NOMINAL.get(tier, 99)]
    return max(ok, key=lambda c: (int(c.get("bits", 0)), c.get("size", 0))) if ok else None


# ------------------------------------------------------------------------------------------------- formato original (diffusers/transformers)
#: bits que o formato original sabe fazer: Q6 e Q3 usam o vizinho de cima
ORIGINAL_BITS = {"Q8": 8, "Q6": 8, "Q4": 4, "Q3": 4, "Q2": 2}
_SKIP_COMPONENTS = re.compile(r"vae|scheduler|tokenizer|processor|feature_extractor|safety|image_encoder|controlnet|adapter|upsampler", re.I)


def original_bits(tier: str) -> int:
    return ORIGINAL_BITS[tier]


def original_note(tier: str) -> str:
    bits = ORIGINAL_BITS.get(tier, 0)
    return f"{tier} no formato original usa {bits} bits (o formato só tem 8, 4 e 2 bits; para {NOMINAL[tier]} bits de verdade use o GGUF)." if bits and bits != NOMINAL.get(tier) else ""


def quantizable(components: Dict[str, Sequence[str]]) -> Dict[str, str]:
    """Dos componentes de um pipeline (`model_index.json`: nome → [biblioteca, classe]) os que valem a pena comprimir: o modelo de difusão (transformer/UNet) e os codificadores de texto grandes. → {nome: biblioteca}."""
    out: Dict[str, str] = {}
    for name, spec in components.items():
        if not isinstance(spec, (list, tuple)) or len(spec) < 2 or name.startswith("_") or _SKIP_COMPONENTS.search(name):
            continue
        lib, cls = str(spec[0]), str(spec[1])
        if lib == "diffusers" and re.search(r"transformer|unet|prior", cls, re.I):
            out[name] = "diffusers"
        elif lib == "transformers" and name.startswith("text_encoder"):
            out[name] = "transformers"
    return out


def backend_for(bits: int, cuda: bool, have_bnb: bool, have_quanto: bool) -> str:
    """«bnb» (bitsandbytes: 8 e 4 bits, só na placa NVIDIA, mais rápido) ou «quanto» (optimum-quanto: 8, 4 e 2 bits, qualquer aparelho); «» se não há nenhum instalado que sirva."""
    if bits in (4, 8) and cuda and have_bnb:
        return "bnb"
    if have_quanto:
        return "quanto"
    return ""


def install_hint(bits: int, cuda: bool) -> str:
    if bits in (4, 8) and cuda:
        return "Instale a biblioteca de compressão:  pip install optimum-quanto  (ou bitsandbytes, para placa NVIDIA)  — ou rode:  flow libs --extras quant"
    return "Instale a biblioteca de compressão:  pip install optimum-quanto  (ou rode:  flow libs --extras quant)"


def build_configs(backend: str, bits: int, compute_dtype: Any, diffusers: Any, transformers: Any) -> Dict[str, Any]:
    """Os objetos de configuração de cada biblioteca: {"diffusers": …, "transformers": …} (a de transformers fica de fora se ela não está instalada)."""
    out: Dict[str, Any] = {}
    if backend == "bnb":
        kw: Dict[str, Any] = {"load_in_8bit": True} if bits == 8 else {"load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": compute_dtype}
        out["diffusers"] = diffusers.BitsAndBytesConfig(**kw)
        if transformers is not None:
            out["transformers"] = transformers.BitsAndBytesConfig(**kw)
    else:
        out["diffusers"] = diffusers.QuantoConfig(weights_dtype=f"int{bits}")
        if transformers is not None:
            out["transformers"] = transformers.QuantoConfig(weights=f"int{bits}")
    return out


def pipeline_mapping(parts: Dict[str, str], configs: Dict[str, Any]) -> Dict[str, Any]:
    """{componente: configuração} para o `PipelineQuantizationConfig(quant_mapping=…)` do diffusers."""
    return {name: configs[lib] for name, lib in parts.items() if lib in configs}
