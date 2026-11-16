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
    "active": {"generation": "demo"},  # provedor de texto dos nós «Texto IA» e da descrição de estilo
    "providers": {},
    "media": {
        # provedor padrão de cada capacidade (cada nó pode escolher outro)
        "active": {"image": "demo", "video": "demo", "sound": "demo", "voice": "demo", "stt": "local_hf", "model3d": "demo"},   # transcrição: o Whisper local (precisa de openflow[media])
        "models": {},  # {"local_hf": {"image": "stabilityai/sd-turbo"}} — modelo por provedor e capacidade
    },
    "canvas": {"template": "text_image"},
    "performance": {"mode": "auto", "idle_unload_min": 10, "device": "auto", "gpus": [], "cpu_pin": True},  # auto | light | balanced | max — veja perf.py
    "server": {"max_upload_mb": 200},
    "storage": {"models_dir": "", "files_dir": ""},   # v0.33: onde guardar os modelos e os arquivos dos projetos ("" = a pasta padrão do OpenFlow; um disco externo, outro disco…)
    "hf": {"token": "", "auto_support": True, "connections": 4},  # auto_support: baixa junto do modelo o VAE, os codificadores de texto e o mmproj (ver canvas/support.py); connections: conexões simultâneas por download (1 a 8; ver dl.py)
}


LOCAL_MEDIA = ("demo", "local_hf", "gguf_local")   # v0.35: os únicos provedores de mídia
LOCAL_TEXT = ("demo", "local_hf")                   # e de texto
_AUTO = ("", "auto")


def local_only(settings: dict) -> dict:
    """v0.35 (sem nuvem): configurações antigas com provedores de nuvem ou servidores (OpenAI, Claude, Gemini, OpenRouter, Ollama, LM Studio…) voltam ao padrão local: os provedores e chaves de API que
    não existem mais são ignorados (e saem do arquivo na próxima gravação) e os padrões apontam para o Demo ou o modelo local."""
    s = settings
    prov = s.get("providers") if isinstance(s.get("providers"), dict) else {}
    s["providers"] = {k: {f: v[f] for f in ("model", "n_ctx") if f in v} for k, v in prov.items() if k in LOCAL_TEXT and isinstance(v, dict)}   # v0.44: do provedor só valem o modelo e a janela de contexto (chave de API, endereço e «vision» eram da nuvem)
    for k in ("voice", "generation"):   # seções antigas (voz em servidor; temperatura/tokens/«content» do Chat do ASTA): ninguém mais lê
        s.pop(k, None)
    act = s.get("active") if isinstance(s.get("active"), dict) else {}
    s["active"] = {r: (v if (v in LOCAL_TEXT or v in _AUTO) else "auto") for r, v in act.items()}
    media = s.get("media") if isinstance(s.get("media"), dict) else {}
    ma = media.get("active") if isinstance(media.get("active"), dict) else {}
    media["active"] = {c: (v if v in LOCAL_MEDIA else ("local_hf" if c == "stt" else "demo")) for c, v in ma.items()}
    media["models"] = {k: v for k, v in (media.get("models") or {}).items() if k in LOCAL_MEDIA}
    media.pop("urls", None)
    s["media"] = media
    return s


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


# Caminhos (dentro de settings) que contêm segredos e nunca são enviados ao navegador.
SECRET_PATHS = [
    ("hf", "token"),
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
        self.default_models_dir = self.home / "models"
        self.default_projects_dir = self.home / "projects"
        self.projects = ProjectStore(self.default_projects_dir)
        self.uploads_dir = self.home / "uploads"
        self._models_dir = self.default_models_dir
        self.storage_warnings: list = []
        for d in (self.uploads_dir, self.default_models_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        from . import perf

        s = self.get_settings()
        perf.configure(s.get("performance"))
        self.apply_storage(s)

    # ------------------------------------------------------------------ onde guardar (v0.33)
    @property
    def models_dir(self) -> Path:
        return self._models_dir

    @models_dir.setter
    def models_dir(self, value: Any) -> None:
        self._models_dir = Path(value)

    def _usable_dir(self, chosen: str, default: Path, label: str) -> Path:
        """A pasta configurada, se está acessível e dá para gravar; senão a padrão, com um aviso (dispositivo externo desconectado, pasta apagada…)."""
        if not chosen:
            return default
        p = Path(chosen).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            probe = p / ".flow-write-probe"
            probe.write_bytes(b"")
            probe.unlink()
            return p
        except OSError:
            self.storage_warnings.append(f"{label}: a pasta {chosen} não está acessível (dispositivo desconectado?). Usando a pasta padrão até ela voltar.")
            return default

    def apply_storage(self, settings: dict) -> None:
        """Passa a usar as pastas de `settings["storage"]` para os modelos e os projetos. Pasta inacessível → a padrão, com aviso em `storage_warnings` (nada quebra com um disco externo desligado)."""
        cfg = settings.get("storage") or {}
        self.storage_warnings = []
        self._models_dir = self._usable_dir(str(cfg.get("models_dir") or ""), self.default_models_dir, "Modelos")
        folder = self._usable_dir(str(cfg.get("files_dir") or ""), self.default_projects_dir, "Arquivos dos projetos")
        if Path(self.projects.folder) != folder:
            folder.mkdir(parents=True, exist_ok=True)
            self.projects.folder = folder

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict:
        saved = read_json(self.settings_path, {}) or {}
        merged = conform(DEFAULT_SETTINGS, deep_merge(copy.deepcopy(DEFAULT_SETTINGS), saved if isinstance(saved, dict) else {}))
        local_only(merged)
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
                    if k in ("model", "n_ctx"):   # os únicos ajustes de um provedor local (o resto é ignorado)
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
            local_only(merged)
            write_json(self.settings_path, merged, private=True)
            from . import perf

            perf.configure(merged.get("performance"))
            self.apply_storage(merged)
            return merged

    def public_settings(self) -> dict:
        """Configurações para o navegador: segredos (o token do Hugging Face) viram flags `*_set`."""
        s = copy.deepcopy(self.get_settings())
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
