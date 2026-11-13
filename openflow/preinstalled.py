"""Modelos locais pré-instalados: o OpenFlow já nasce com um modelo de texto e um de imagem prontos para rodar no seu computador.

São baixados pelo instalador (e pelo `flow update`) — ou com `flow models install` / pelo botão em Configuração → Modelos locais — e ficam
nas mesmas pastas dos demais modelos locais. A quantização deles já vem definida pelo catálogo (e você pode baixar outras na mesma aba).

Os modelos de texto pré-instalados usam uma janela de contexto base de **32K tokens** (`n_ctx`), que o usuário pode ajustar em
Configuração → Modelos locais (a escolha dele sempre prevalece).

Catálogo inicial (só estes dois):

* texto  — `empero-ai/Qwen3.8-2B-Distill` em Q8_0 (GGUF oficial do autor: `empero-ai/Qwen3.8-2B-Distill-GGUF`);
* imagem — `Tongyi-MAI/Z-Image` em Q4_K_M (GGUF `unsloth/Z-Image-GGUF`), com o VAE e o codificador de texto (Qwen3-4B) que ele precisa.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import hf
from .providers.base import ProviderError
from .termi18n import _

CATALOG: List[Dict[str, Any]] = [
    {
        "id": "text-qwen3.8-2b-distill", "kind": "text", "label": "Qwen3.8 2B Distill", "source": "empero-ai/Qwen3.8-2B-Distill", "license": "apache-2.0",
        "repo": "empero-ai/Qwen3.8-2B-Distill-GGUF", "file": "Qwen3.8-2B-Q8_0.gguf", "quant": "Q8_0", "size": 2076674432,
        "n_ctx": 32768,  # janela de contexto base dos modelos de texto pré-instalados (o usuário pode mudar)
        "hint": "Modelo de texto pequeno e rápido (2B, destilado para raciocínio): roda o nó Texto IA, o planejador de fluxos e a descrição de estilo no seu computador.",
        "companions": [],
    },
    {
        "id": "image-z-image", "kind": "image", "label": "Z-Image", "source": "Tongyi-MAI/Z-Image", "license": "apache-2.0",
        "repo": "unsloth/Z-Image-GGUF", "file": "z-image-Q4_K_M.gguf", "quant": "Q4_K_M", "size": 3850115136,
        "hint": "Modelo de imagem da Tongyi-MAI (Alibaba). Vem com o VAE e o codificador de texto (Qwen3-4B) de que precisa; roda pelo provedor GGUF local do OpenFlow.",
        "companions": [
            {"repo": "Comfy-Org/z_image_turbo", "file": "split_files/vae/ae.safetensors", "size": 335304388, "label": "VAE (ae.safetensors)", "role": "vae"},
            {"repo": "unsloth/Qwen3-4B-Instruct-2507-GGUF", "file": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf", "size": 2497281120, "label": "Codificador de texto (Qwen3-4B Q4_K_M)", "role": "text_encoder"},
        ],
        # como o OpenFlow carrega e usa este modelo (o campo "extra" do nó pode sobrescrever): "@model" = o arquivo principal; nomes de arquivo = pasta de imagens
        "load": {"diffusion_model_path": "@model", "vae_path": "ae.safetensors", "llm_path": "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"},
        "run": {"cfg_scale": 4.0, "sample_steps": 30},
    },
]


def entry(entry_id: str) -> Dict[str, Any]:
    e = next((x for x in CATALOG if x["id"] == entry_id), None)
    if not e:
        raise ProviderError("Modelo pré-instalado desconhecido.")
    return e


DEFAULT_TEXT_CTX = 32768


def default_n_ctx(filename: str) -> int:
    """Janela de contexto base (tokens) de um modelo de texto pré-instalado; 0 para os demais modelos."""
    name = Path(filename or "").name
    return next((int(e.get("n_ctx") or DEFAULT_TEXT_CTX) for e in CATALOG if e["kind"] == "text" and Path(e["file"]).name == name), 0)


def _files(e: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = [{"repo": e["repo"], "file": e["file"], "size": e["size"], "main": True}]
    out += [{"repo": c["repo"], "file": c["file"], "size": c["size"], "main": False} for c in e.get("companions", [])]
    return out


def installed(models_dir: Path, e: Dict[str, Any]) -> bool:
    folder = hf.kind_dir(models_dir, e["kind"])
    return all((folder / Path(f["file"]).name).is_file() for f in _files(e))


def status(models_dir: Path) -> List[Dict[str, Any]]:
    return [{"id": e["id"], "kind": e["kind"], "label": e["label"], "source": e["source"], "license": e["license"], "repo": e["repo"], "file": e["file"], "quant": e["quant"],
             "size": sum(f["size"] for f in _files(e)), "hint": e["hint"], "n_ctx": int(e.get("n_ctx") or 0), "parts": [Path(f["file"]).name for f in _files(e)],
             "support": [{"role": c.get("role", "text_encoder"), "label": c.get("label", ""), "name": Path(c["file"]).name, "size": c["size"]} for c in e.get("companions", [])],
             "installed": installed(models_dir, e)} for e in CATALOG]


def defaults_for(kind: str, filename: str) -> Dict[str, Any]:
    """Como carregar/usar um modelo do catálogo no OpenFlow ({"load": {...}, "run": {...}}); vazio para os demais."""
    for e in CATALOG:
        if e["kind"] == kind and Path(e["file"]).name == Path(filename).name and e.get("load"):
            return {"load": dict(e["load"]), "run": dict(e.get("run") or {})}
    return {}


def _companion_names(e: Dict[str, Any]) -> List[str]:
    return [Path(c["file"]).name for c in e.get("companions", [])]


def _catalog_entry(kind: str, filename: str) -> Optional[Dict[str, Any]]:
    return next((e for e in CATALOG if e["kind"] == kind and Path(e["file"]).name == filename), None)


def library(models_dir: Path) -> List[Dict[str, Any]]:
    """Os modelos locais instalados, para a Biblioteca: todos os tipos, com o rótulo do catálogo nos pré-instalados.
    Os arquivos de apoio de um pré-instalado (VAE, codificador de texto) aparecem junto do modelo principal, não como modelos soltos."""
    models = hf.local_models(models_dir, "all")
    hidden = set()
    for e in CATALOG:
        if installed(models_dir, e):
            hidden.update((e["kind"], n) for n in _companion_names(e))
    out = []
    for m in models:
        if (m["kind"], m["name"]) in hidden:
            continue
        e = _catalog_entry(m["kind"], m["name"])
        folder = hf.kind_dir(models_dir, m["kind"])
        extra = [n for n in _companion_names(e) if (folder / n).is_file()] if e else []
        size = m["size"] + sum((folder / n).stat().st_size for n in extra)
        out.append({**m, "id": f"{m['kind']}/{m['name']}", "size": size, "label": e["label"] if e else "", "source": e["source"] if e else "", "preinstalled": e["id"] if e else "", "extra_files": extra})
    return out


def support_mmproj_name(name: str) -> str:
    from .canvas.support import mmproj_name

    return mmproj_name(name)


def remove(models_dir: Path, items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apaga modelos locais ({kind, name}), um ou vários. Num pré-instalado, apaga também os arquivos de apoio dele (VAE, codificador de texto).
    Um modelo dividido em partes é apagado inteiro. Devolve {deleted: [...], missing: [...], freed: bytes}."""
    from .util import safe_filename

    deleted, missing, freed = [], [], 0
    for it in items:
        kind, name = str(it.get("kind") or "text"), safe_filename(it.get("name"), "")
        folder = hf.kind_dir(models_dir, kind)  # tipo inválido → ProviderError
        path = folder / name
        if not name or path.suffix != ".gguf" or not path.is_file():
            missing.append(f"{kind}/{name}")
            continue
        victims = list(hf.shard_files(folder, name))
        mm = folder / support_mmproj_name(name)   # o projetor de visão (mmproj) é só deste modelo
        if mm.is_file():
            victims.append(mm)
        e = _catalog_entry(kind, name)
        if e:
            victims += [folder / n for n in _companion_names(e)]
        for v in victims:
            if v.is_file():
                freed += v.stat().st_size
                v.unlink(missing_ok=True)
        deleted.append(f"{kind}/{name}")
    return {"deleted": deleted, "missing": missing, "freed": freed}


def _lib(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def apply(store: Any, e: Dict[str, Any]) -> List[str]:
    """Deixa o modelo pronto para usar. Só troca o provedor padrão se ele ainda é o Demo e a biblioteca que roda o modelo está instalada."""
    name, notes = Path(e["file"]).name, []
    s = store.get_settings()
    if e["kind"] == "text":
        patch: Dict[str, Any] = {"providers": {"local_hf": {"model": name}}}
        if _lib("llama_cpp"):
            # as conversas (papel "characters", em "auto") já seguem o provedor de geração ou o modelo local; só a geração precisa ser trocada
            act = {r: "local_hf" for r in ("generation",) if s["active"].get(r, "demo") == "demo"}
            if act:
                patch["active"] = act
                notes.append("ativado como modelo de texto padrão")
        elif s["active"].get("generation", "demo") == "demo":
            notes.append('para usá-lo instale a biblioteca: flow libs --extras local')
        store.save_settings(patch)
    elif e["kind"] == "image":
        patch = {"media": {"models": {"gguf_local": {"image": name}}}}
        if _lib("stable_diffusion_cpp"):
            if (s.get("media") or {}).get("active", {}).get("image", "demo") == "demo":
                patch["media"]["active"] = {"image": "gguf_local"}
                notes.append("ativado como provedor de imagem padrão do OpenFlow")
        else:
            notes.append('para usá-lo instale a biblioteca: flow libs --extras local')
        store.save_settings(patch)
    return notes


def install(store: Any, entry_id: str, token: str = "", progress: Optional[Callable[[int, int], None]] = None, cancelled: Callable[[], bool] = lambda: False,
            log: Callable[[str], None] = lambda m: None) -> Dict[str, Any]:
    """Baixa o modelo e os arquivos de que ele precisa (pula o que já está na pasta) e o deixa pronto para usar."""
    e = entry(entry_id)
    folder = hf.kind_dir(store.models_dir, e["kind"], create=True)
    todo = [f for f in _files(e) if not (folder / Path(f["file"]).name).is_file()]
    done_bytes = 0
    total = sum(f["size"] for f in todo)
    for f in todo:
        log(_("Baixando {f} ({g:.1f} GB) de {r} …", f=Path(f["file"]).name, g=f["size"] / 1024 ** 3, r=f["repo"]))

        def prog(d: int, t: int, base: int = done_bytes) -> None:
            if progress:
                progress(base + d, total or (base + t))

        hf.download_many(f["repo"], [f["file"]], folder, token, {f["file"]: f["size"]}, prog, cancelled, any_file=True)
        done_bytes += f["size"]
    notes = apply(store, e)
    return {"id": e["id"], "downloaded": [Path(f["file"]).name for f in todo], "notes": notes}


def _declined_file(home: Path) -> Path:
    return Path(home) / "preinstalled.json"


def declined(home: Path) -> List[str]:
    """Ids dos modelos pré-instalados que o usuário recusou no terminal (o instalador não pergunta de novo por eles)."""
    from .util import read_json

    data = read_json(_declined_file(home), {}) or {}
    return [x for x in data.get("declined", []) if isinstance(x, str)]


def set_declined(home: Path, ids: List[str]) -> None:
    from .util import write_json

    write_json(_declined_file(home), {"declined": sorted(set(ids))})


def install_selected(store: Any, which: str = "all", token: str = "", log: Callable[[str], None] = print, ask: Optional[Callable[[str], Optional[bool]]] = None) -> int:
    """`flow models install`: `which` = all | none | text | image | lista. Devolve 0 se tudo certo, 1 se algum falhou.
    Com `ask` (função que pergunta sim/não no terminal e devolve True, False ou None se não dá para perguntar), o que ainda não está instalado só é
    baixado se o usuário disser que sim; a recusa fica guardada e o OpenFlow não pergunta de novo (`flow models install` sem `--ask` baixa quando quiser)."""
    which = (which or "all").strip().lower()
    if which in ("none", "no", "0"):
        log(_("Modelos pré-instalados: nada a baixar (OPENFLOW_MODELS=none)."))
        return 0
    names = [x.strip() for x in which.replace(";", ",").split(",") if x.strip()]
    chosen = [e for e in CATALOG if "all" in names or e["kind"] in names or e["id"] in names]
    if not chosen:
        log(_("Modelos desconhecidos: use all, none, text, image ou os ids do catálogo."))
        return 2
    if ask is not None:
        missing = [e for e in chosen if not installed(store.models_dir, e)]
        refused = declined(store.home)
        pending = [e for e in missing if e["id"] not in refused]
        approved = False
        if missing and not pending:
            log(_("Modelos pré-instalados: você preferiu não baixar (para baixar quando quiser: flow models install)."))
        if pending:
            lines = "\n".join(f"  • {e['label']} ({hf.GGUF_KINDS[e['kind']]['label'].lower()}, {e['quant']}) — {sum(f['size'] for f in _files(e)) / 1024 ** 3:.1f} GB" for e in pending)
            answer = ask(_("O OpenFlow pode baixar agora os modelos de IA pré-instalados (precisam de espaço em disco e de internet):\n{l}\nBaixar agora?", l=lines))
            if answer is None:
                log(_("Modelos pré-instalados: não há um terminal para perguntar, então não baixei nada. Para baixar: flow models install   (ou OPENFLOW_MODELS=all no instalador)."))
            elif answer:
                approved = True
                set_declined(store.home, [x for x in refused if x not in {e["id"] for e in pending}])
            else:
                set_declined(store.home, refused + [e["id"] for e in pending])
                log(_("Ok, não vou baixar os modelos pré-instalados. Quando quiser: flow models install"))
        chosen = [e for e in chosen if installed(store.models_dir, e) or (approved and e in pending)]  # o que já existe só é conferido/configurado
    failed = 0
    for e in chosen:
        try:
            if installed(store.models_dir, e):
                log(_("{n} ({q}): já instalado.", n=e["label"], q=e["quant"]))
                apply(store, e)
                continue
            r = install(store, e["id"], token, log=log)
            log(_("{n} ({q}): pronto", n=e["label"], q=e["quant"]) + (f" — {'; '.join(_(x) for x in r['notes'])}" if r["notes"] else "") + ".")
        except ProviderError as exc:
            failed += 1
            log(_("⚠  {n}: não foi possível instalar ({e}). Tente de novo com:  flow models install", n=e["label"], e=exc))
    return 1 if failed else 0
