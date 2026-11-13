"""Persistência dos Canvas: um documento (project.json) + pasta de mídias por canvas.

    projects/<id>/project.json
    projects/<id>/assets/<asset_id>.<ext>

Resultados dos nós e a lista de ativos pertencem ao servidor (o navegador só salva o layout), assim o
salvamento automático do editor nunca apaga o que um job acabou de gerar.
"""
from __future__ import annotations

import re
import shutil
import threading
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..util import new_id, now_iso, read_json, write_json
from .schema import all_folder_files, build_template, normalize_asset, normalize_canvas, normalize_result, prune_folder_files

_ID_RE = re.compile(r"^[\w-]+$")


def _fold(s: Any) -> str:
    """Minúsculas e sem acentos: «Cenário» e «cenario» são a mesma palavra na pesquisa."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(ch)).lower()


_TEXT_PARAMS = ("text", "prompt", "instruction")


def _match(c: Dict[str, Any], tokens: List[str]) -> Optional[str]:
    """Onde o projeto casa com a pesquisa: "" (no nome), "descrição", ou o trecho do nó (título/texto). None se alguma palavra não aparece em lugar nenhum."""
    fields = [("", c["name"]), ("descrição", c["description"])]
    for n in c["nodes"]:
        label = n["title"] or n["type"]
        fields.append((label, n["title"]))
        for k in _TEXT_PARAMS:
            v = n["params"].get(k)
            if isinstance(v, str) and v.strip():
                fields.append((v.strip().replace("\n", " ")[:80], v))
        if n["type"] == "style_folder":
            fields += [("pasta de estilo: " + f["name"], f["name"]) for f in _all_folders(n["params"].get("folders", []))]
    hay = [(where, _fold(text)) for where, text in fields if text]
    blob = " ".join(h for _w, h in hay)
    if not all(t in blob for t in tokens):
        return None
    for where, h in hay:   # o primeiro campo que tem a primeira palavra diz «onde»
        if tokens[0] in h:
            return where
    return ""


def _all_folders(folders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for f in folders:
        out.append(f)
        out += _all_folders(f["folders"])
    return out


class ProjectStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._revs: Dict[str, int] = {}   # versão de cada canvas na memória: sobe a cada gravação (o motor só relê o arquivo quando ela muda)

    def rev(self, cid: str) -> int:
        return self._revs.get(cid, 0)

    # ------------------------------------------------------------------ caminhos
    def _dir(self, cid: str) -> Optional[Path]:
        return self.folder / cid if cid and _ID_RE.match(cid) and ".." not in cid else None

    def asset_dir(self, cid: str) -> Optional[Path]:
        d = self._dir(cid)
        return d / "assets" if d else None

    def asset_path(self, cid: str, fname: str) -> Optional[Path]:
        ad = self.asset_dir(cid)
        if not ad or not re.match(r"^[\w][\w.-]*$", fname or "") or ".." in fname:
            return None
        p = ad / fname
        return p if p.is_file() else None

    # ------------------------------------------------------------------ documentos
    def get(self, cid: str) -> Optional[Dict[str, Any]]:
        d = self._dir(cid)
        data = read_json(d / "project.json") if d else None
        return normalize_canvas(data, keep_id=cid) if isinstance(data, dict) else None

    def _write(self, canvas: Dict[str, Any]) -> Dict[str, Any]:
        canvas["updated"] = now_iso()
        write_json(self.folder / canvas["id"] / "project.json", canvas)
        self._revs[canvas["id"]] = self._revs.get(canvas["id"], 0) + 1
        return canvas

    def summary(self, c: Dict[str, Any]) -> Dict[str, Any]:
        thumb = next((f"/api/projects/{c['id']}/assets/{a['file']}" for a in c["assets"] if a["kind"] == "image"), "")
        return {"id": c["id"], "name": c["name"], "description": c["description"], "created": c["created"], "updated": c["updated"], "nodes": len(c["nodes"]),
                "assets": len(c["assets"]), "thumb": thumb}

    def list(self, q: str = "", sort: str = "updated") -> List[Dict[str, Any]]:
        """Resumo de todos os projetos. `q` pesquisa (sem diferenciar acentos nem maiúsculas; todas as palavras precisam aparecer) no nome, na descrição e nos textos dos nós
        (títulos, prompts, instruções, falas); cada resultado diz onde achou em `match`. `sort`: updated (padrão, mais recentes primeiro), created, name ou files."""
        tokens = [t for t in _fold(q).split() if t]
        out = []
        for d in self.folder.iterdir():
            c = self.get(d.name) if d.is_dir() else None
            if not c or not c["id"]:
                continue
            row = self.summary(c)
            if tokens:
                where = _match(c, tokens)
                if where is None:
                    continue
                row["match"] = where
            out.append(row)
        if sort == "name":
            out.sort(key=lambda c: _fold(c["name"]))
        elif sort == "created":
            out.sort(key=lambda c: c.get("created", ""), reverse=True)
        elif sort == "files":
            out.sort(key=lambda c: (-c["assets"], _fold(c["name"])))
        else:
            out.sort(key=lambda c: c.get("updated", ""), reverse=True)
        return out

    def create(self, name: str = "", template: str = "blank", prompt: str = "") -> Dict[str, Any]:
        with self._lock:
            cid = new_id("pj_")
            (self.folder / cid / "assets").mkdir(parents=True, exist_ok=True)
            base = build_template(template, prompt)
            canvas = normalize_canvas({"name": name or "Novo canvas", "nodes": base["nodes"], "edges": base["edges"]}, keep_id=cid)
            canvas["created"] = now_iso()
            return self._write(canvas)

    def save_layout(self, cid: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Salva nós/conexões/viewport vindos do navegador, preservando resultados e ativos do servidor."""
        with self._lock:
            cur = self.get(cid)
            if not cur:
                return None
            merged = dict(body or {})
            merged["assets"] = cur["assets"]
            merged.setdefault("name", cur["name"])
            merged.setdefault("description", cur["description"])
            new = normalize_canvas(merged, keep_id=cid)
            results = {n["id"]: n["result"] for n in cur["nodes"]}
            for n in new["nodes"]:
                n["result"] = results.get(n["id"], normalize_result({}))
            new["created"] = cur["created"]
            return self._write(new)

    def append_nodes(self, cid: str, nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Acrescenta nós (já com ids únicos) a um canvas existente, mantendo o resto como está."""
        with self._lock:
            cur = self.get(cid)
            if not cur:
                return None
            merged = normalize_canvas({**cur, "nodes": cur["nodes"] + list(nodes)}, keep_id=cid)
            merged["created"] = cur["created"]
            return self._write(merged)

    def update_meta(self, cid: str, name: Optional[str], description: Optional[str]) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self.get(cid)
            if not cur:
                return None
            if name is not None:
                cur["name"] = (name or "").strip()[:80] or cur["name"]
            if description is not None:
                cur["description"] = description[:400]
            return self._write(cur)

    def delete(self, cid: str) -> bool:
        d = self._dir(cid)
        if not d or not d.exists():
            return False
        with self._lock:
            shutil.rmtree(d, ignore_errors=True)
        return True

    def duplicate(self, cid: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self.get(cid)
            src = self._dir(cid)
            if not cur or not src:
                return None
            new_cid = new_id("pj_")
            shutil.copytree(src, self.folder / new_cid)
            cur["id"], cur["name"], cur["created"] = new_cid, (cur["name"] + " (2)")[:80], now_iso()
            return self._write(cur)

    # ------------------------------------------------------------------ ativos e resultados
    def add_asset(self, cid: str, data: bytes, ext: str, kind: str, name: str = "", mime: str = "", **meta: Any) -> Optional[Dict[str, Any]]:
        """Grava um arquivo no canvas e o registra. `meta`: node, prompt, provider, model, w, h, duration."""
        ad = self.asset_dir(cid)
        ext = re.sub(r"[^a-z0-9]", "", (ext or "bin").lower())[:5] or "bin"
        if not ad:
            return None
        with self._lock:
            cur = self.get(cid)
            if not cur:
                return None
            aid = new_id("as_")
            fname = f"{aid}.{ext}"
            ad.mkdir(parents=True, exist_ok=True)
            (ad / fname).write_bytes(data)
            from .. import attachments as att

            rec: Dict[str, Any] = {"id": aid, "kind": kind, "mime": mime or "application/octet-stream", "name": name or fname, "file": fname, "bytes": len(data), "created": now_iso(), **meta}
            if kind == "image" and not rec.get("w"):
                dims = att.image_size(data)
                if dims:
                    rec["w"], rec["h"] = int(dims[0]), int(dims[1])
            if kind in ("audio", "video") and not rec.get("duration"):
                dur = att._duration(ad / fname)
                if dur:
                    rec["duration"] = round(dur, 2)
            na = normalize_asset(rec)
            if not na:
                (ad / fname).unlink(missing_ok=True)
                return None
            cur["assets"].append(na)
            self._write(cur)
            return na

    def delete_asset(self, cid: str, aid: str) -> bool:
        with self._lock:
            cur = self.get(cid)
            if not cur:
                return False
            a = next((x for x in cur["assets"] if x["id"] == aid), None)
            if not a:
                return False
            p = self.asset_path(cid, a["file"])
            if p:
                p.unlink(missing_ok=True)
            cur["assets"] = [x for x in cur["assets"] if x["id"] != aid]
            for n in cur["nodes"]:
                if "files" in n["params"]:
                    n["params"]["files"] = [f for f in n["params"]["files"] if f != aid]
                if "folders" in n["params"]:
                    prune_folder_files(n["params"]["folders"], {a["id"] for a in cur["assets"]})
                n["result"]["assets"] = [f for f in n["result"]["assets"] if f != aid]
                if n["type"] == "editor":
                    tl = n["params"]["timeline"]
                    tl["clips"] = [c for c in tl["clips"] if c.get("asset") != aid]
            self._write(cur)
            return True

    def referenced_assets(self, cur: Dict[str, Any]) -> set:
        """Ids de arquivos em uso: resultados dos nós, uploads/estilos e clipes fixos dos Editores."""
        used: set = set()
        for n in cur["nodes"]:
            used.update(n["result"]["assets"])
            used.update(n["params"].get("files", []))
            used.update(all_folder_files(n["params"].get("folders", [])))
            if n["type"] == "editor":
                used.update(c["asset"] for c in n["params"]["timeline"]["clips"] if c.get("asset"))
        return used

    def prune_node_assets(self, cid: str, nid: str, keep: int = 24) -> int:
        """Mantém um histórico de até `keep` arquivos antigos por nó (os que não estão em uso são apagados, do mais velho ao mais novo)."""
        with self._lock:
            cur = self.get(cid)
            if not cur:
                return 0
            used = self.referenced_assets(cur)
            old = [a for a in cur["assets"] if a["node"] == nid and a["id"] not in used]
            old.sort(key=lambda a: a["created"])
            drop = old[:-keep] if keep > 0 and len(old) > keep else (old if keep <= 0 else [])
            for a in drop:
                p = self.asset_path(cid, a["file"])
                if p:
                    p.unlink(missing_ok=True)
            if drop:
                gone = {a["id"] for a in drop}
                cur["assets"] = [a for a in cur["assets"] if a["id"] not in gone]
                self._write(cur)
            return len(drop)

    def reset_running(self, cid: str) -> bool:
        """Nós que ficaram "em execução" (servidor reiniciado ou tarefa interrompida) voltam a "parado"."""
        with self._lock:
            cur = self.get(cid)
            if not cur:
                return False
            changed = False
            for n in cur["nodes"]:
                if n["result"]["state"] == "running":
                    n["result"]["state"] = "idle"
                    changed = True
            if changed:
                self._write(cur)
            return changed

    def set_node_result(self, cid: str, nid: str, result: Dict[str, Any]) -> bool:
        with self._lock:
            cur = self.get(cid)
            node = next((n for n in cur["nodes"] if n["id"] == nid), None) if cur else None
            if not node:
                return False
            node["result"] = normalize_result(result)
            self._write(cur)
            return True

    def patch_node_params(self, cid: str, nid: str, patch: Dict[str, Any]) -> bool:
        with self._lock:
            cur = self.get(cid)
            node = next((n for n in cur["nodes"] if n["id"] == nid), None) if cur else None
            if not node:
                return False
            from .schema import normalize_params

            node["params"] = normalize_params(node["type"], {**node["params"], **patch})
            self._write(cur)
            return True
