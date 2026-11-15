"""Rotas da Biblioteca 2.0 (v0.27): pastas virtuais, listagem de modelos e arquivos por pasta, busca e mover itens (ver libfolders.py)."""
from __future__ import annotations

import re
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

    # ------------------------------------------------------------------ itens
    def _models(self) -> List[Dict[str, Any]]:
        out = []
        for m in hf.local_models(self.store.models_dir, "all"):
            out.append({"key": f"model:{m['kind']}/{m['name']}", "scope": "models", "kind": m["kind"], "name": m["name"], "size": m.get("size", 0), "quant": m.get("quant", ""),
                        "parts": m.get("parts", 1), "mtime": m.get("mtime", 0)})
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
        if source not in ("generated", "upload", "all") or kind not in ("", "image", "video", "audio", "text", "sound", "voice", "stt"):
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
