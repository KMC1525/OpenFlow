"""Rotas da Biblioteca 2.0 (v0.27): pastas virtuais, listagem de modelos e arquivos por pasta, busca e mover itens (ver libfolders.py)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from . import hf
from .jobs import HttpError
from .libfolders import LibraryError, LibraryFolders, SCOPES
from .providers import ProviderError
from .util import text

_ID = r"(?P<fid>[\w-]+)"


def _fold(s: Any) -> str:
    import unicodedata

    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(ch)).lower()


class LibraryRoutes:
    def __init__(self, app: Any):
        self.app = app
        self.store = app.store
        self.folders = LibraryFolders(self.store.home / "library.json")

    def register(self) -> None:
        a = self.app.add
        a("GET", r"/api/library/items", self.r_items)
        a("GET", r"/api/library/folders", self.r_folders)
        a("POST", r"/api/library/folders", self.r_folder_create)
        a("PUT", rf"/api/library/folders/{_ID}", self.r_folder_update)
        a("DELETE", rf"/api/library/folders/{_ID}", self.r_folder_delete)
        a("POST", r"/api/library/move", self.r_move)
        a("GET", r"/api/storage", self.r_storage)
        a("POST", r"/api/storage/clean", self.r_storage_clean)
        a("GET", r"/api/storage/locations", self.r_locations)
        a("GET", r"/api/storage/browse", self.r_browse)
        a("POST", r"/api/storage/location", self.r_location)

    def _wrap(self, fn, *a, **k):
        try:
            return fn(*a, **k)
        except LibraryError as exc:
            raise HttpError(exc.status, str(exc))

    # ------------------------------------------------------------------ pastas
    def r_folders(self, req) -> None:
        scope = (req.query.get("scope", [""])[0] or "").strip()
        if scope and scope not in SCOPES:
            raise HttpError(400, "Escopo inválido.")
        req.json({"folders": self.folders.folders(scope)})

    def r_folder_create(self, req) -> None:
        b = req.body_json()
        b = b if isinstance(b, dict) else {}
        f = self._wrap(self.folders.create, b.get("name"), text(b.get("parent"), "", 40), text(b.get("scope"), "files", 10))
        req.json(f, 201)

    def r_folder_update(self, req, fid: str) -> None:
        b = req.body_json()
        b = b if isinstance(b, dict) else {}
        parent = text(b.get("parent"), "", 40) if "parent" in b else None
        req.json(self._wrap(self.folders.update, fid, b.get("name") if "name" in b else None, parent))

    def r_folder_delete(self, req, fid: str) -> None:
        self._wrap(self.folders.delete, fid)
        req.json({"ok": True})

    def r_move(self, req) -> None:
        b = req.body_json()
        b = b if isinstance(b, dict) else {}
        keys = [text(k, "", 400) for k in b.get("items", [])] if isinstance(b.get("items"), list) else []
        if not keys:
            raise HttpError(400, "Escolha ao menos um item.")
        n = self._wrap(self.folders.place, keys, text(b.get("folder"), "", 40))
        req.json({"moved": n})

    # ------------------------------------------------------------------ armazenamento (v0.31)
    def _downloading(self) -> bool:
        return any(self.app.jobs.running(k) for k in self.app.DOWNLOAD_KINDS)

    def r_storage(self, req) -> None:
        """Uso do disco: livre, tipo (SSD/HDD), modelos por tipo, projetos, envios e o que a limpeza pode liberar."""
        from . import diskuse

        req.json(diskuse.report(self.store, self._downloading()))

    def r_storage_clean(self, req) -> None:
        """Apaga o que sobrou: `{"what": ["partials", "temp", "orphans"]}`. Downloads parciais só saem se nenhum download está rodando."""
        from . import diskuse

        b = req.body_json()
        what = [w for w in (b.get("what") if isinstance(b, dict) and isinstance(b.get("what"), list) else []) if w in ("partials", "temp", "orphans")]
        if not what:
            raise HttpError(400, "Escolha o que limpar.")
        req.json(diskuse.clean(self.store, what, self._downloading()))

    # ------------------------------------------------------------------ onde guardar (v0.33)
    def _dirs(self) -> Dict[str, Any]:
        st = self.store
        return {"models": (st.models_dir, st.default_models_dir, "models_dir"), "files": (Path(st.projects.folder), st.default_projects_dir, "files_dir")}

    def r_locations(self, req) -> None:
        """Onde estão os modelos e os arquivos dos projetos (e as alternativas): discos e dispositivos, espaço livre e avisos (dispositivo desligado)."""
        from . import diskuse, storagepaths

        cfg = self.store.get_settings().get("storage") or {}
        out: Dict[str, Any] = {}
        for k, (cur, default, key) in self._dirs().items():
            u = storagepaths._usage(str(cur))
            out[k] = {"path": str(cur), "default": str(default), "custom": bool(cfg.get(key)), "configured": cfg.get(key) or "", "free": u["free"], "total": u["total"], "kind": diskuse.kind_of(cur)}
        req.json({**out, "volumes": storagepaths.volumes(), "warnings": list(self.store.storage_warnings), "busy": self._busy()})

    def r_browse(self, req) -> None:
        from . import storagepaths
        from .providers import ProviderError

        try:
            req.json(storagepaths.browse((req.query.get("path", [""])[0] or "")[:1000]))
        except ProviderError as exc:
            raise HttpError(400, str(exc))

    def _busy(self) -> bool:
        with self.app.jobs.lock:
            return any(j.status == "running" for j in self.app.jobs.jobs.values())

    def r_location(self, req) -> None:
        """Muda a pasta dos modelos (`kind: models`) ou dos arquivos dos projetos (`kind: files`): `{"kind", "path" ("" = a padrão), "move": true}`. Com `move`, o que já existe é copiado
        (um job com progresso) e a pasta antiga só é esvaziada no fim; sem `move`, o OpenFlow passa a usar a nova pasta e o conteúdo antigo fica onde está."""
        from . import storagepaths
        from .jobs import Job
        from .providers import ProviderError

        b = req.body_json()
        b = b if isinstance(b, dict) else {}
        kind = text(b.get("kind"), "", 10)
        if kind not in ("models", "files"):
            raise HttpError(400, "Escolha «models» ou «files».")
        if self._busy():
            raise HttpError(409, "Há uma geração, download ou outra tarefa em andamento: espere terminar (ou cancele) antes de mudar a pasta.")
        cur, default, key = self._dirs()[kind]
        picked = text(b.get("path"), "", 1000)
        try:
            dst = default if not picked else storagepaths.resolve(kind, picked)
            if not picked:
                default.mkdir(parents=True, exist_ok=True)
            move = bool(b.get("move"))
            total = storagepaths.check_move(cur, dst) if move else 0
        except ProviderError as exc:
            raise HttpError(400, str(exc))

        def switch() -> None:
            self.store.save_settings({"storage": {key: "" if dst == default else str(dst)}})

        if not move:
            switch()
            req.json({"ok": True, "path": str(dst), "moved": False})
            return

        def work(job: Job) -> None:
            job.emit({"type": "start", "file": str(dst)})
            last = [0.0]

            def progress(done: int, tot: int) -> None:
                import time as _t

                if _t.time() - last[0] > 0.4:
                    last[0] = _t.time()
                    job.emit({"type": "progress", "done": done, "total": tot})

            try:
                storagepaths.migrate(cur, dst, progress, lambda: job.cancelled, lambda m: job.emit({"type": "note", "message": m}))
            except ProviderError as exc:
                job.emit({"type": "cancelled"} if str(exc) == "cancelado" else {"type": "error", "message": str(exc)[:400]})
                return
            except OSError as exc:
                job.emit({"type": "error", "message": f"Não consegui copiar: {exc}"[:400]})
                return
            switch()
            job.emit({"type": "note", "message": "Apagando a pasta antiga…"})
            storagepaths.remove_source(cur)
            job.emit({"type": "done", "path": str(dst), "bytes": total})

        job = self.app.jobs.start("storage_move", work, {"title": str(dst), "kind": kind})
        req.json({"job_id": job.id, "path": str(dst), "moved": True, "bytes": total})

    # ------------------------------------------------------------------ itens
    def _models(self) -> List[Dict[str, Any]]:
        out = []
        for m in hf.local_models(self.store.models_dir, "all"):
            out.append({"key": f"model:{m['kind']}/{m['name']}", "scope": "models", "kind": m["kind"], "name": m["name"], "size": m.get("size", 0), "quant": m.get("quant", ""),
                        "bits": m.get("bits", 0), "tier": m.get("tier", ""), "parts": m.get("parts", 1), "mtime": m.get("mtime", 0)})
        return out

    def _files(self, kind: str, source: str) -> List[Dict[str, Any]]:
        out = []
        for f in self.app.project_routes.cs.library_files(kind, "", source, limit=5000):
            out.append({**f, "key": f"file:{f['project']}/{f['id']}", "scope": "files"})
        return out

    def r_items(self, req) -> None:
        """O conteúdo de uma pasta (ou os resultados da busca em todas): {folders, items, path, search}. `?scope=models|files&folder=<id>&q=&kind=&source=generated|upload|all`."""
        qs = req.query
        scope = (qs.get("scope", ["files"])[0] or "files").strip()
        if scope not in SCOPES:
            raise HttpError(400, "Escopo inválido.")
        folder = text(qs.get("folder", [""])[0], "", 40)
        q = (qs.get("q", [""])[0] or "").strip()[:100]
        kind = (qs.get("kind", [""])[0] or "").strip()
        source = (qs.get("source", ["all"])[0] or "all").strip()
        if source not in ("generated", "upload", "all") or kind not in ("", "image", "video", "audio", "text", "sound", "voice", "stt", "model3d"):
            raise HttpError(400, "Filtro inválido.")
        try:
            items = self._models() if scope == "models" else self._files(kind if scope == "files" else "", source)
        except ProviderError as exc:
            raise HttpError(400, str(exc))
        if scope == "models" and kind:
            items = [i for i in items if i["kind"] == kind]
        place = self.folders.placements()
        folders = self.folders.folders(scope)
        by = {f["id"]: f for f in folders}
        if folder and folder not in by:
            raise HttpError(404, "Pasta não encontrada.")
        for i in items:
            i["folder"] = place.get(i["key"], "")
        tokens = [t for t in _fold(q).split() if t]
        if tokens:   # busca em todas as pastas: o nome da pasta, do arquivo, do projeto e do modelo; cada resultado diz onde está
            def path_text(fid: str) -> str:
                return " / ".join(p["name"] for p in self.folders.path_of(fid))

            fr = []
            for f in folders:
                if all(t in _fold(f["name"]) for t in tokens):
                    fr.append({**f, "path": path_text(f.get("parent") or "")})
            ir = []
            for i in items:
                hay = _fold(" ".join(str(x) for x in (i.get("name"), i.get("project_name"), i.get("model"), i.get("quant"), i.get("kind"))))
                if all(t in hay for t in tokens):
                    ir.append({**i, "path": path_text(i["folder"])})
            req.json({"folders": fr, "items": ir, "path": [], "search": True})
            return
        kids = [dict(f, count=sum(1 for g in folders if (g.get("parent") or "") == f["id"]) + sum(1 for i in items if i["folder"] == f["id"])) for f in folders if (f.get("parent") or "") == folder]
        kids.sort(key=lambda f: _fold(f["name"]))
        here = [i for i in items if i["folder"] == folder]
        req.json({"folders": kids, "items": here, "path": self.folders.path_of(folder) if folder else [], "search": False,
                  "tree": [{"id": f["id"], "name": f["name"], "parent": f.get("parent") or ""} for f in folders]})
