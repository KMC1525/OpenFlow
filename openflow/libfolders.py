"""Pastas da Biblioteca (v0.27): organização virtual de modelos de IA e arquivos gerados, como no Google Drive.

As pastas existem só no OpenFlow (`library.json`): **nenhum arquivo é movido ou renomeado no disco** — os modelos continuam em `models/` e os arquivos gerados dentro dos seus projetos.
Cada item tem uma chave estável: `model:<tipo>/<arquivo>` (modelos) ou `file:<projeto>/<id do arquivo>` (arquivos gerados). Uma pasta pertence a um «escopo» (`models` ou `files`) e só guarda itens dele.
Apagar uma pasta não apaga nada: os itens e as subpastas sobem para a pasta de cima.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from .util import new_id, now_iso, read_json, write_json

SCOPES = ("models", "files")
MAX_NAME = 80
MAX_FOLDERS = 2000


class LibraryError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def scope_of(key: str) -> str:
    return "models" if key.startswith("model:") else "files" if key.startswith("file:") else ""


class LibraryFolders:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ arquivo
    def _load(self) -> Dict[str, Any]:
        d = read_json(self.path, {}) or {}
        folders = [f for f in (d.get("folders") if isinstance(d.get("folders"), list) else []) if isinstance(f, dict) and f.get("id") and f.get("scope") in SCOPES]
        items = {k: v for k, v in (d.get("items") if isinstance(d.get("items"), dict) else {}).items() if isinstance(k, str) and isinstance(v, str)}
        return {"folders": folders, "items": items}

    def _save(self, d: Dict[str, Any]) -> None:
        write_json(self.path, d)

    # ------------------------------------------------------------------ consultas
    def folders(self, scope: str = "") -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(f) for f in self._load()["folders"] if not scope or f["scope"] == scope]

    def placements(self) -> Dict[str, str]:
        with self._lock:
            d = self._load()
            ids = {f["id"] for f in d["folders"]}
            return {k: v for k, v in d["items"].items() if v in ids}

    def path_of(self, folder_id: str) -> List[Dict[str, str]]:
        """Da raiz até a pasta: [{id, name}]."""
        with self._lock:
            by = {f["id"]: f for f in self._load()["folders"]}
        out: List[Dict[str, str]] = []
        cur = folder_id
        while cur and cur in by and len(out) < 64:
            out.append({"id": cur, "name": by[cur]["name"]})
            cur = by[cur].get("parent") or ""
        return out[::-1]

    def descendants(self, folder_id: str) -> List[str]:
        with self._lock:
            fs = self._load()["folders"]
        out, todo = [], [folder_id]
        while todo:
            cur = todo.pop()
            for f in fs:
                if (f.get("parent") or "") == cur and f["id"] not in out:
                    out.append(f["id"])
                    todo.append(f["id"])
        return out

    # ------------------------------------------------------------------ pastas
    @staticmethod
    def _clean_name(name: Any) -> str:
        n = " ".join(str(name or "").split())[:MAX_NAME]
        if not n:
            raise LibraryError("Dê um nome à pasta.")
        return n

    def _check_unique(self, d: Dict[str, Any], scope: str, parent: str, name: str, ignore: str = "") -> None:
        for f in d["folders"]:
            if f["scope"] == scope and (f.get("parent") or "") == parent and f["id"] != ignore and f["name"].casefold() == name.casefold():
                raise LibraryError(f"Já existe uma pasta chamada «{name}» aqui.", 409)

    def create(self, name: Any, parent: str = "", scope: str = "files") -> Dict[str, Any]:
        if scope not in SCOPES:
            raise LibraryError("Escopo inválido.")
        name = self._clean_name(name)
        with self._lock:
            d = self._load()
            if len(d["folders"]) >= MAX_FOLDERS:
                raise LibraryError("Pastas demais.")
            if parent:
                p = next((f for f in d["folders"] if f["id"] == parent), None)
                if not p or p["scope"] != scope:
                    raise LibraryError("A pasta de cima não existe.", 404)
            self._check_unique(d, scope, parent or "", name)
            f = {"id": new_id("lf_"), "name": name, "parent": parent or "", "scope": scope, "created": now_iso()}
            d["folders"].append(f)
            self._save(d)
            return dict(f)

    def update(self, folder_id: str, name: Any = None, parent: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            d = self._load()
            f = next((x for x in d["folders"] if x["id"] == folder_id), None)
            if not f:
                raise LibraryError("Pasta não encontrada.", 404)
            new_name = self._clean_name(name) if name is not None else f["name"]
            new_parent = f.get("parent") or "" if parent is None else parent
            if new_parent:
                p = next((x for x in d["folders"] if x["id"] == new_parent), None)
                if not p or p["scope"] != f["scope"]:
                    raise LibraryError("A pasta de destino não existe.", 404)
                if new_parent == folder_id or new_parent in self._desc(d, folder_id):
                    raise LibraryError("Uma pasta não pode ir para dentro dela mesma.")
            self._check_unique(d, f["scope"], new_parent, new_name, ignore=folder_id)
            f["name"], f["parent"] = new_name, new_parent
            self._save(d)
            return dict(f)

    @staticmethod
    def _desc(d: Dict[str, Any], folder_id: str) -> List[str]:
        out, todo = [], [folder_id]
        while todo:
            cur = todo.pop()
            for f in d["folders"]:
                if (f.get("parent") or "") == cur and f["id"] not in out:
                    out.append(f["id"])
                    todo.append(f["id"])
        return out

    def delete(self, folder_id: str) -> None:
        """Só a pasta some: subpastas e itens sobem para a pasta de cima (ou a raiz)."""
        with self._lock:
            d = self._load()
            f = next((x for x in d["folders"] if x["id"] == folder_id), None)
            if not f:
                raise LibraryError("Pasta não encontrada.", 404)
            up = f.get("parent") or ""
            for x in d["folders"]:
                if (x.get("parent") or "") == folder_id:
                    x["parent"] = up
            d["folders"] = [x for x in d["folders"] if x["id"] != folder_id]
            for k, v in list(d["items"].items()):
                if v == folder_id:
                    if up:
                        d["items"][k] = up
                    else:
                        del d["items"][k]
            self._save(d)

    # ------------------------------------------------------------------ itens
    def place(self, keys: List[str], folder_id: str = "") -> int:
        """Põe itens numa pasta (vazio = raiz). Modelos só vão para pastas de modelos; arquivos, para as de arquivos."""
        with self._lock:
            d = self._load()
            if folder_id:
                f = next((x for x in d["folders"] if x["id"] == folder_id), None)
                if not f:
                    raise LibraryError("A pasta de destino não existe.", 404)
            n = 0
            for k in keys[:500]:
                sc = scope_of(str(k))
                if not sc:
                    continue
                if folder_id and sc != f["scope"]:   # type: ignore[possibly-undefined]
                    raise LibraryError("Modelos e arquivos gerados ficam em pastas separadas.")
                if folder_id:
                    d["items"][str(k)] = folder_id
                else:
                    d["items"].pop(str(k), None)
                n += 1
            self._save(d)
            return n
