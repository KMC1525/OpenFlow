"""Persistência em disco do OpenFlow: configurações, projetos (fluxos de nós + mídias), anexos temporários e modelos locais.

Tudo é JSON/arquivos comuns dentro de OPENFLOW_HOME (padrão ~/.openflow):

    settings.json
    projects/<id>/project.json          um projeto (nós, conexões, ativos, pastas de estilo)
    projects/<id>/assets/<arquivo>      mídias geradas ou enviadas
    uploads/<id>/                       (anexos aguardando uso)
    models/                             (modelos GGUF baixados do Hugging Face; image/ video/ sound/ voice/ other/ em subpastas)
    native/                             (biblioteca do núcleo Rust)
"""
from __future__ import annotations

import copy
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .canvas.store import ProjectStore
from .uiprefs import DEFAULT_UI, normalize_ui
from .util import deep_merge, flow_home, new_id, now_iso, read_json, safe_filename, write_json

DEFAULT_SETTINGS: Dict[str, Any] = {
    "language": "auto",  # auto | pt-BR | en
    "ui": DEFAULT_UI,  # aparência: tema, cor de destaque, escala, densidade…
    "active": {"generation": "demo"},  # provedor de texto dos nós «Texto IA» e do planejador de fluxos
    "providers": {},
    "generation": {
        "temperature": 0.8,
        "max_tokens": 6000,
        "content": "free",  # free (SFW e NSFW, sem filtros do OpenFlow) | sfw
        "agents": 1, "effort": "high",  # equipe: 1/2/4/8/12/16/20/24/28/32 agentes em paralelo · esforço Low … Omni (ver team.py)
    },
    "voice": {
        "stt": {"engine": "browser", "base_url": "", "api_key": "", "model": "whisper-1", "lang": "auto"},
        "tts": {"engine": "browser", "base_url": "", "api_key": "", "model": "tts-1", "voice": "alloy"},
    },
    "media": {
        # provedor padrão de cada capacidade (cada nó pode escolher outro)
        "active": {"image": "demo", "video": "demo", "sound": "demo", "voice": "demo", "stt": "voice_settings"},  # transcrição: usa a voz das configurações
        "models": {},  # {"openai": {"image": "gpt-image-1"}} — modelo por provedor e capacidade
        "urls": {},  # {"a1111": "http://127.0.0.1:7860"} — endereço de servidores (locais ou compatíveis)
    },
    "canvas": {"template": "text_image", "agents": 1, "effort": "high"},  # equipe dos nós de texto (IA) e do planejador de fluxos
    "performance": {"mode": "auto", "idle_unload_min": 10, "device": "auto"},  # auto | light | balanced | max — veja perf.py
    "server": {"max_upload_mb": 200},
    "hf": {"token": "", "auto_support": True},  # auto_support: baixa junto do modelo o VAE, os codificadores de texto e o mmproj (ver canvas/support.py)
}


def conform(defaults: Any, value: Any) -> Any:
    """Força `value` a ter a «forma» de `defaults`: onde o padrão é um objeto, o valor precisa ser um objeto (senão volta ao padrão); onde o padrão é um número/texto/booleano,
    um valor de outro tipo é descartado. Um settings.json editado à mão (ou uma chamada de API errada) não derruba mais a tela inteira."""
    if not isinstance(defaults, dict):
        return value
    out = dict(value) if isinstance(value, dict) else {}
    for key, dv in defaults.items():
        if key not in out:
            out[key] = copy.deepcopy(dv)
        elif isinstance(dv, dict):
            out[key] = conform(dv, out[key]) if isinstance(out[key], dict) else copy.deepcopy(dv)
        elif isinstance(dv, bool):
            if not isinstance(out[key], bool):
                out[key] = bool(out[key]) if isinstance(out[key], (int, float)) else dv
        elif isinstance(dv, (int, float)):
            if isinstance(out[key], bool) or not isinstance(out[key], (int, float)):
                out[key] = dv
        elif isinstance(dv, str):
            if not isinstance(out[key], str):
                out[key] = dv
    providers = out.get("providers")
    if isinstance(providers, dict):
        out["providers"] = {k: v for k, v in providers.items() if isinstance(v, dict)}
    return out


def _normalize_teams(settings: dict) -> None:
    """Equipe de cada seção (agentes 1/4 a 32 e esforço Low … Omni): valor fora da lista (edição manual, API) vira o valor aceito mais próximo."""
    from . import team

    for key in team.SECTIONS:
        sec = settings.get(key)
        if not isinstance(sec, dict):
            continue
        sec["agents"] = team.normalize_agents(sec.get("agents"))
        sec["effort"] = team.normalize_effort(sec.get("effort"), team.DEFAULT_EFFORT)


# Caminhos (dentro de settings) que contêm segredos e nunca são enviados ao navegador.
SECRET_PATHS = [
    ("hf", "token"),
    ("voice", "stt", "api_key"),
    ("voice", "tts", "api_key"),
]


def _get_path(data: dict, path: tuple) -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _set_path(data: dict, path: tuple, value: Any) -> None:
    cur = data
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


def _strip_flags(data: Any) -> None:
    """Remove flags somente-leitura (`*_set`, `has_key`) que o navegador pode devolver."""
    if isinstance(data, dict):
        for key in list(data.keys()):
            if key == "has_key" or key.endswith("_set"):
                data.pop(key, None)
            else:
                _strip_flags(data[key])


class Store:
    def __init__(self, home: Optional[Path] = None):
        self.home = Path(home) if home else flow_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.home / "settings.json"
        self.projects = ProjectStore(self.home / "projects")
        self.uploads_dir = self.home / "uploads"
        self.models_dir = self.home / "models"
        for d in (self.uploads_dir, self.models_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        from . import perf

        perf.configure(self.get_settings().get("performance"))

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        saved = read_json(self.settings_path, {}) or {}
        merged = conform(DEFAULT_SETTINGS, deep_merge(copy.deepcopy(DEFAULT_SETTINGS), saved if isinstance(saved, dict) else {}))
        _normalize_teams(merged)
        merged["ui"] = normalize_ui(merged.get("ui"))  # valor inválido (API/edição manual) volta ao padrão em vez de quebrar a interface
        return merged

    def save_settings(self, patch: dict) -> dict:
        """Mescla `patch` nas configurações.

        Segredos: "" ou ausente = manter; null = apagar; texto = definir.
        """
        with self._lock:
            current = self.get_settings()
            patch = copy.deepcopy(patch or {})
            # provedores: tratados à parte (chave por id)
            prov_patch = patch.pop("providers", None) or {}
            for pid, pcfg in prov_patch.items():
                if not isinstance(pcfg, dict):
                    continue
                cur = current["providers"].setdefault(pid, {})
                for k, v in pcfg.items():
                    if k == "has_key" or k.endswith("_set"):
                        continue
                    if k == "api_key":
                        if v is None:
                            cur.pop("api_key", None)
                        elif isinstance(v, str) and v.strip():
                            cur["api_key"] = v.strip()
                        continue
                    cur[k] = v
            # demais segredos: "" = manter, null = apagar, texto = definir
            for path in SECRET_PATHS:
                parent = _get_path(patch, path[:-1])
                if not isinstance(parent, dict) or path[-1] not in parent:
                    continue
                val = parent.pop(path[-1])
                if val is None:
                    _set_path(current, path, "")
                elif isinstance(val, str) and val.strip():
                    _set_path(current, path, val.strip())
            _strip_flags(patch)
            merged = conform(DEFAULT_SETTINGS, deep_merge(current, patch))  # valor do tipo errado (API/edição manual) nunca chega ao disco
            merged["ui"] = normalize_ui(merged.get("ui"))
            write_json(self.settings_path, merged, private=True)
            from . import perf

            perf.configure(merged.get("performance"))
            return merged

    def public_settings(self) -> dict:
        """Configurações para o navegador: segredos viram flags `has_key`."""
        s = copy.deepcopy(self.get_settings())
        for pid, pcfg in s.get("providers", {}).items():
            key = pcfg.pop("api_key", "")
            pcfg["has_key"] = bool(key)
        for path in SECRET_PATHS:
            val = _get_path(s, path)
            _set_path(s, path[:-1] + (path[-1] + "_set",), bool(val))
            _set_path(s, path, "")
        return s

    # ------------------------------------------------------------------ uploads
    def save_upload_stream(self, name: str, mime: str, stream, length: int, chunk: int = 1 << 20) -> dict:
        uid = new_id("u_")
        folder = self.uploads_dir / uid
        folder.mkdir(parents=True, exist_ok=True)
        fname = safe_filename(name, "arquivo")
        target = folder / fname
        remaining = length
        with open(target, "wb") as fh:
            while remaining > 0:
                data = stream.read(min(chunk, remaining))
                if not data:
                    break
                fh.write(data)
                remaining -= len(data)
        meta = {"id": uid, "name": fname, "mime": mime or "", "size": target.stat().st_size, "created": now_iso()}
        write_json(folder / "meta.json", meta)
        return meta

    def get_upload(self, uid: str) -> Optional[dict]:
        if not uid or "/" in uid or "\\" in uid or ".." in uid:
            return None
        folder = self.uploads_dir / uid
        meta = read_json(folder / "meta.json")
        if not isinstance(meta, dict):
            return None
        meta["path"] = str(folder / meta["name"])
        return meta

    def delete_upload(self, uid: str) -> bool:
        uid = str(uid or "").split(":", 1)[0]   # «u_abc:3» = um arquivo de dentro de um pacote: apagar o anexo apaga o pacote inteiro
        if not self.get_upload(uid):
            return False
        shutil.rmtree(self.uploads_dir / uid, ignore_errors=True)
        return True

    def get_uploads(self, ids, limit: int = 40, expand: bool = True, max_members: int = 120) -> list:
        """Os anexos de uma lista de ids. Com `expand`, um pacote (ZIP, RAR, 7z, TAR…) é aberto e **cada arquivo de dentro vira um anexo** (id «u_abc:3», nome «pacote.zip/pasta/arquivo.txt»).
        Pacote ilegível/com senha vira um anexo só, com `error`."""
        from . import archives

        out: list = []
        for uid in [u for u in (ids or []) if isinstance(u, str)][:limit]:
            meta = self.get_upload(uid)
            if not meta:
                continue
            kind = archives.archive_kind(meta["name"], Path(meta["path"])) if expand else ""
            if not kind:
                out.append(meta)
                continue
            try:
                members = self._unpack(meta, max_members)
            except archives.ArchiveError as exc:
                out.append(dict(meta, error=str(exc), archive_kind=kind))
                continue
            if not members:
                out.append(dict(meta, error="O pacote não tem nenhum arquivo utilizável.", archive_kind=kind))
                continue
            out.extend(members)
        return out

    def _unpack(self, meta: dict, max_members: int) -> list:
        """Abre o pacote do anexo `meta` (uma vez; fica em uploads/<id>/_unpacked) e devolve os arquivos de dentro como metadados de anexo."""
        from . import archives

        folder = self.uploads_dir / meta["id"] / "_unpacked"
        index = folder / "_index.json"
        data = read_json(index) if index.is_file() else None
        if not isinstance(data, dict):
            shutil.rmtree(folder, ignore_errors=True)
            res = archives.expand(meta["path"], folder, meta["name"])   # resolve() abaixo: no macOS /var é um link para /private/var
            data = {"files": [{"name": f["name"], "path": str(Path(f["path"]).resolve().relative_to(folder.resolve())).replace("\\", "/"), "size": f["size"]} for f in res["files"]], "skipped": res["skipped"]}
            write_json(index, data)
        out = []
        for i, f in enumerate(data["files"][:max_members]):
            p = folder / f["path"]
            if p.is_file():
                out.append({"id": f"{meta['id']}:{i}", "name": f"{meta['name']}/{f['name']}", "mime": "", "size": f["size"], "created": meta.get("created", ""), "path": str(p),
                            "archive": meta["name"], "skipped": data["skipped"] if i == 0 else []})
        return out

    # ------------------------------------------------------------------ histórico (o Job do OpenFlow não guarda memória de seções)
    def remember(self, *args: Any, **kwargs: Any) -> None:
        return None
