"""Busca e download de modelos GGUF no Hugging Face (sem dependências externas).

Cada repositório costuma trazer o mesmo modelo em várias **quantizações** (Q2_K … Q8_0, F16): quanto menos bits, menor o arquivo
e a necessidade de RAM, e menor a qualidade. `list_files` identifica a quantização de cada arquivo, junta modelos divididos em
partes (`-00001-of-00003.gguf`) numa só opção e indica qual cabe na sua RAM; o usuário escolhe qual baixar.
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .providers import http
from .providers.base import ProviderError

HF = "https://huggingface.co"
REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[A-Za-z0-9][\w.-]{0,95}$")
FILE_RE = re.compile(r"^[\w][\w .+()=-]{0,200}\.gguf$")
QUANT_RE = re.compile(r"(?<![A-Za-z0-9])((?:IQ|Q)\d(?:_[A-Z0-9]+)*|BF16|F16|F32|MXFP4)(?![A-Za-z0-9])", re.I)
SHARD_RE = re.compile(r"^(?P<base>.+)-(?P<n>\d{5})-of-(?P<total>\d{5})\.gguf$", re.I)
# qualidade esperada por número de bits (aproximação dos guias do llama.cpp)
QUALITY = {1: "very_low", 2: "very_low", 3: "low", 4: "good", 5: "very_good", 6: "high", 8: "lossless"}
PREFERRED = ("Q4_K_M", "Q5_K_M", "Q4_K_S", "Q5_K_S", "Q6_K", "Q4_0", "Q8_0", "Q3_K_L", "Q3_K_M")  # ordem de preferência ao recomendar


def parse_quant(name: str) -> Dict[str, Any]:
    """Quantização de um arquivo pelo nome: {"quant": "Q4_K_M", "bits": 4, "quality": "good"} (vazio se não achar)."""
    base = Path(name).name
    m = SHARD_RE.match(base)
    base = (m.group("base") + ".gguf") if m else base
    found = QUANT_RE.findall(base)
    if not found:
        return {"quant": "", "bits": 0, "quality": ""}
    q = found[-1].upper()
    if q in ("F16", "BF16"):
        return {"quant": q, "bits": 16, "quality": "original"}
    if q == "F32":
        return {"quant": q, "bits": 32, "quality": "original"}
    if q == "MXFP4":
        return {"quant": q, "bits": 4, "quality": "good"}
    bits = int(re.search(r"\d", q).group())
    return {"quant": q, "bits": bits, "quality": QUALITY.get(bits, "good")}


# Tipos de modelo GGUF (separados por pasta e por busca): chave → (rótulo, filtros "pipeline_tag" do Hugging Face)
GGUF_KINDS: Dict[str, Dict[str, Any]] = {
    "text": {"label": "Texto", "tags": ["text-generation"]},
    "image": {"label": "Imagem", "tags": ["text-to-image", "image-to-image"]},
    "video": {"label": "Vídeo", "tags": ["text-to-video", "image-to-video"]},
    "sound": {"label": "Som e música", "tags": ["text-to-audio"]},
    "voice": {"label": "Voz", "tags": ["text-to-speech", "automatic-speech-recognition"]},
    "other": {"label": "Outros", "tags": ["feature-extraction", "image-text-to-text", "image-to-text", "sentence-similarity"]},
}


def check_kind(kind: str) -> str:
    if kind not in GGUF_KINDS:
        raise ProviderError("Tipo de modelo inválido.")
    return kind


def kind_dir(models_dir: Path, kind: str, create: bool = False) -> Path:
    """Pasta dos modelos de um tipo: os de texto ficam na raiz (como sempre), os demais em `image/`, `video/`, `sound/`, `voice/`, `other/`."""
    d = models_dir if check_kind(kind) == "text" else models_dir / kind
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


# --------------------------------------------------------------------------- consultas à API do Hub: em paralelo e com cache curto
SEARCH_TIMEOUT = 12.0     # segundos por consulta (antes 20 s, uma depois da outra: uma busca de «Outros» podia levar minutos se o Hub estivesse lento)
CACHE_SECONDS = 90.0      # a mesma busca/lista de arquivos dentro desse prazo vem da memória
_CACHE: Dict[Any, Any] = {}
_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _get_json_cached(url: str, token: str, timeout: float) -> Any:
    """`GET` JSON do Hub com cache de `CACHE_SECONDS`. Só respostas bem-sucedidas entram no cache (um erro de rede nunca fica «gravado»). A chave inclui a função de rede em uso (os testes a trocam)."""
    key = (id(http.get_json), url, bool(token))
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    data = http.get_json(url, _headers(token), timeout=timeout)
    with _CACHE_LOCK:
        if len(_CACHE) >= 128:   # pequeno e simples: descarta o mais antigo
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k][0]), None)
        _CACHE[key] = (time.time(), data)
    return data


def _fetch_all(urls: List[str], token: str, timeout: float = SEARCH_TIMEOUT) -> List[Any]:
    """Consulta todas as `urls` ao mesmo tempo: devolve, na mesma ordem, a resposta (JSON) de cada uma ou a exceção `ProviderError` que ela deu."""
    def one(u: str) -> Any:
        try:
            return _get_json_cached(u, token, timeout)
        except ProviderError as exc:
            return exc

    if len(urls) <= 1:
        return [one(u) for u in urls]
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as ex:
        return list(ex.map(one, urls))


def _author_queries(query: str) -> List[Dict[str, str]]:
    """Consultas extras por autor/perfil (ex.: "unsloth", "empero-ai") para achar todos os modelos de um perfil do Hugging Face."""
    q = (query or "").strip()
    if not q or "/" in q or " " in q:
        return []
    # nome simples de autor/org: tenta também filtrar por author (e busca vazia dentro do autor)
    return [{"author": q, "search": ""}, {"author": q, "search": q}]


def search(query: str, token: str = "", limit: int = 20, kind: str = "text") -> List[Dict[str, Any]]:
    """Busca repositórios GGUF do tipo pedido (texto, imagem, vídeo, som, voz, outros), do mais baixado para o menos. Aceita buscar por perfil/autor (ex.: "unsloth")."""
    found: Dict[str, Dict[str, Any]] = {}
    queries = [{"search": query}]
    queries += _author_queries(query)
    answered, failure = False, None
    urls = []
    for tag in GGUF_KINDS[check_kind(kind)]["tags"]:
        for extra in queries:
            params = {**extra, "filter": "gguf", "pipeline_tag": tag, "sort": "downloads", "direction": "-1", "limit": str(max(limit, 30))}
            urls.append(f"{HF}/api/models?{urllib.parse.urlencode(params)}")
    for data in _fetch_all(urls, token):
        if isinstance(data, ProviderError):
            failure = data
            continue
        answered = True
        for m in data if isinstance(data, list) else []:
            if isinstance(m, dict) and (m.get("id") or m.get("modelId")):
                mid = m.get("id") or m.get("modelId")
                row = found.setdefault(mid, {"id": mid, "downloads": m.get("downloads", 0) or 0, "likes": m.get("likes", 0) or 0, "kind": kind})
                row["downloads"] = max(int(row.get("downloads") or 0), int(m.get("downloads") or 0))
                row["likes"] = max(int(row.get("likes") or 0), int(m.get("likes") or 0))
    if not answered and failure is not None:   # nenhuma consulta chegou ao Hugging Face (sem rede, fora do ar): dizer isso em vez de «nada encontrado»
        raise failure
    return sorted(found.values(), key=lambda m: -m["downloads"])[:limit]


# Capacidades dos nós → filtros "pipeline_tag" do Hugging Face para modelos no formato original (diffusers/transformers), sem exigir GGUF
ORIGINAL_TAGS: Dict[str, List[str]] = {
    "image": ["text-to-image", "image-to-image"], "video": ["text-to-video", "image-to-video"], "sound": ["text-to-audio"], "voice": ["text-to-speech"], "stt": ["automatic-speech-recognition"],
    "text": ["text-generation"],
}


def search_original(query: str, token: str = "", cap: str = "image", limit: int = 20) -> List[Dict[str, Any]]:
    """Busca modelos (qualquer formato) de uma capacidade dos nós — imagem, vídeo, som, voz, transcrição ou texto —, do mais baixado para o menos. Aceita buscar por perfil/autor."""
    if cap not in ORIGINAL_TAGS:
        raise ProviderError("Capacidade inválida.")
    found: Dict[str, Dict[str, Any]] = {}
    queries = [{"search": query}]
    queries += _author_queries(query)
    answered, failure = False, None
    urls = []
    for tag in ORIGINAL_TAGS[cap]:
        for extra in queries:
            params = {**extra, "pipeline_tag": tag, "sort": "downloads", "direction": "-1", "limit": str(max(limit, 30))}
            urls.append(f"{HF}/api/models?{urllib.parse.urlencode(params)}")
    for data in _fetch_all(urls, token):
        if isinstance(data, ProviderError):
            failure = data
            continue
        answered = True
        for m in data if isinstance(data, list) else []:
            mid = m.get("id") or m.get("modelId") if isinstance(m, dict) else None
            if isinstance(mid, str) and REPO_RE.match(mid):
                row = found.setdefault(mid, {"id": mid, "downloads": int(m.get("downloads") or 0), "likes": int(m.get("likes") or 0), "cap": cap, "format": "original", "gguf": "gguf" in [str(t).lower() for t in (m.get("tags") or [])]})
                row["downloads"] = max(int(row.get("downloads") or 0), int(m.get("downloads") or 0))
                row["likes"] = max(int(row.get("likes") or 0), int(m.get("likes") or 0))
                row["gguf"] = row["gguf"] or ("gguf" in [str(t).lower() for t in (m.get("tags") or [])])
    if not answered and failure is not None:
        raise failure
    return sorted(found.values(), key=lambda m: -m["downloads"])[:limit]


def group_files(raw: List[Dict[str, Any]], ram_gb: float = 0) -> List[Dict[str, Any]]:
    """Agrupa arquivos GGUF em opções de download: junta partes divididas, ignora projetores de visão (mmproj) e marca a recomendada.

    Cada opção: {name (arquivo principal), files (todas as partes), sizes (por parte), size (soma), parts, quant, bits, quality, fits, recommended}.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    for f in raw:
        base = Path(f["name"]).name
        if "mmproj" in base.lower():
            continue
        m = SHARD_RE.match(base)
        key = str(Path(f["name"]).parent / m.group("base")) if m else f["name"]
        g = groups.setdefault(key, {"parts": {}, "total": int(m.group("total")) if m else 1})
        g["parts"][int(m.group("n")) if m else 1] = f
    out = []
    for g in groups.values():
        if len(g["parts"]) != g["total"]:  # partes faltando no repositório: não dá para usar
            continue
        parts = [g["parts"][k] for k in sorted(g["parts"])]
        out.append({"name": parts[0]["name"], "files": [p["name"] for p in parts], "sizes": {p["name"]: p["size"] for p in parts}, "size": sum(p["size"] for p in parts), "parts": len(parts), **parse_quant(parts[0]["name"])})
    out.sort(key=lambda f: (f["size"], f["name"]))
    limit = ram_gb * 0.6 * 1024 ** 3
    for f in out:
        f["fits"] = bool(ram_gb) and f["size"] <= limit
        f["recommended"] = False
    fitting = [f for f in out if f["fits"] and f["quant"]]
    pick = None
    for q in PREFERRED:  # a melhor entre as preferidas que cabem; senão a maior que cabe até 6 bits; senão a menor de todas
        pick = next((f for f in fitting if f["quant"] == q and f["bits"] <= 6), None)
        if pick:
            break
    pick = pick or next(iter(sorted([f for f in fitting if f["bits"] <= 6], key=lambda f: -f["size"])), None) or (out[0] if out else None)
    if pick:
        pick["recommended"] = True
    return out


def repo_files(repo: str, token: str = "") -> List[Dict[str, Any]]:
    """Todos os arquivos de um repositório do Hugging Face: [{name (caminho), size}]. Serve para achar o que o modelo precisa ao lado (VAE, codificadores de texto, mmproj)."""
    if not REPO_RE.match(repo or ""):
        raise ProviderError("Repositório inválido (use o formato dono/nome).")
    data = _get_json_cached(f"{HF}/api/models/{repo}/tree/main?recursive=1", token, 20)
    out = []
    for it in data if isinstance(data, list) else []:
        path = it.get("path", "") if isinstance(it, dict) else ""
        if it.get("type") == "file" and path and ".." not in path:
            out.append({"name": path, "size": int((it.get("lfs") or {}).get("size") or it.get("size") or 0)})
    return out


def list_files(repo: str, token: str = "", ram_gb: float = 0) -> List[Dict[str, Any]]:
    files = [f for f in repo_files(repo, token) if f["name"].lower().endswith(".gguf") and FILE_RE.match(Path(f["name"]).name)]
    return group_files(files, ram_gb)


def shard_files(models_dir: Path, name: str) -> List[Path]:
    """Todos os arquivos de um modelo local: ele mesmo ou, se for dividido, todas as partes."""
    m = SHARD_RE.match(Path(name).name)
    if not m:
        return [models_dir / Path(name).name]
    total = int(m.group("total"))
    return [models_dir / f"{m.group('base')}-{k:05d}-of-{total:05d}.gguf" for k in range(1, total + 1)]


def local_models(models_dir: Path, kind: str = "text") -> List[Dict[str, Any]]:
    """Modelos baixados do tipo pedido ("all" = todos, cada um com o seu `kind`). Um modelo dividido em partes aparece uma vez, com o tamanho total."""
    if kind == "all":
        return [m for k in GGUF_KINDS for m in local_models(models_dir, k)]
    folder = kind_dir(models_dir, kind)
    out = []
    for p in sorted(folder.glob("*.gguf")):
        m = SHARD_RE.match(p.name)
        if m and int(m.group("n")) != 1:
            continue
        parts = [x for x in shard_files(folder, p.name)]
        if not all(x.exists() for x in parts):
            continue  # partes faltando: o modelo não carrega
        if "mmproj" in p.name.lower():
            continue
        out.append({"name": p.name, "kind": kind, "size": sum(x.stat().st_size for x in parts), "parts": len(parts), **parse_quant(p.name)})
    return out


ANY_FILE_RE = re.compile(r"^[\w][\w .+()=/-]{0,200}$")


def download(
    repo: str, filename: str, models_dir: Path, token: str = "",
    progress: Optional[Callable[[int, int], None]] = None, cancelled: Callable[[], bool] = lambda: False, any_file: bool = False, dest_name: str = "",
) -> Path:
    """`any_file=True` (arquivos de apoio e catálogo de pré-instalados) permite arquivos que não são .gguf, como o VAE `.safetensors`.
    `dest_name` grava com outro nome (o mmproj de cada modelo vira `<modelo>.mmproj.gguf`: dois repositórios podem ter o mesmo `mmproj-F16.gguf`)."""
    ok_name = ANY_FILE_RE.match(filename) and Path(filename).name == filename.rsplit("/", 1)[-1] if any_file else FILE_RE.match(Path(filename).name)
    if not REPO_RE.match(repo or "") or not ok_name or ".." in filename:
        raise ProviderError("Repositório ou arquivo inválido.")
    if dest_name and (Path(dest_name).name != dest_name or ".." in dest_name or not ANY_FILE_RE.match(dest_name)):
        raise ProviderError("Nome de destino inválido.")
    dest = models_dir / (dest_name or Path(filename).name)
    part = dest.with_suffix(dest.suffix + ".part")
    start = part.stat().st_size if part.exists() else 0
    headers = _headers(token)
    if start:
        headers["Range"] = f"bytes={start}-"
    url = f"{HF}/{repo}/resolve/main/{urllib.parse.quote(filename)}"
    resp = http.request(url, headers=headers, timeout=60)
    try:
        total = int(resp.headers.get("Content-Length") or 0)
        if resp.status == 206:
            total += start
        else:
            start = 0  # servidor ignorou o Range
        mode = "ab" if start else "wb"
        done = start
        with open(part, mode) as fh:
            while True:
                if cancelled():
                    raise ProviderError("cancelado")
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    finally:
        resp.close()
    os.replace(part, dest)
    return dest


def download_many(
    repo: str, filenames: List[str], models_dir: Path, token: str = "", sizes: Optional[Dict[str, int]] = None,
    progress: Optional[Callable[[int, int], None]] = None, cancelled: Callable[[], bool] = lambda: False, any_file: bool = False,
) -> Path:
    """Baixa uma opção (um arquivo ou todas as partes de um modelo dividido) com progresso somado. Devolve o arquivo principal."""
    if not filenames or len(filenames) > 99:
        raise ProviderError("Nada para baixar.")
    sizes = sizes or {}
    total = sum(int(sizes.get(f, 0)) for f in filenames)
    if total:
        pending = total - sum((models_dir / Path(f).name).stat().st_size for f in filenames if (models_dir / Path(f).name).exists())
        if shutil.disk_usage(models_dir).free < max(0, pending) * 1.02 + (50 << 20):
            raise ProviderError("Sem espaço em disco suficiente para este modelo.")
    base = 0
    first: Optional[Path] = None
    for i, f in enumerate(filenames):
        done_file = models_dir / Path(f).name
        if sizes.get(f) and done_file.exists() and done_file.stat().st_size == int(sizes[f]):  # parte já baixada (retomada)
            base += int(sizes[f])
            first = first or done_file
            if progress:
                progress(base, total)
            continue

        def prog(done: int, tot: int, base: int = base) -> None:
            if progress:
                progress(base + done, total or (base + tot))

        path = download(repo, f, models_dir, token, prog, cancelled, any_file)
        first = first or path
        base += int(sizes.get(f, 0)) or path.stat().st_size
    return first  # type: ignore[return-value]
