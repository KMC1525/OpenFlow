"""Execução de um Canvas: roda os nós na ordem das conexões, com cache por hash e estilos do projeto.

* Cada nó gerador chama um provedor de mídia (ou o provedor de texto, no "Texto IA") e grava os arquivos no canvas.
* O resultado só é refeito quando algo mudou: parâmetros, entradas, estilos, provedor/modelo (hash do nó). "Gerar de novo" força.
* "Style Prompt" e "Style Folder" marcados como globais valem para todos os nós do projeto; ligados a um nó, valem para ele.
* O Editor monta a linha do tempo com as saídas dos nós ligados e exporta um MP4 com o ffmpeg.
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import attachments as att
from .. import native
from .. import team as teamlib
from ..agents.runner import Cancelled
from ..providers import ProviderError, build_provider
from ..util import now_iso
from . import procedural as proc
from . import media as media_mod
from .media import Ctl, Media, build_media, media_config, pick_provider
from .render import render_timeline
from . import mentions as mentions_mod
from . import upsample
from . import nodes_ext
from .schema import EXT_TYPES, GENERATORS, NODE_TYPES, normalize_result, style_files

RUNNABLE = GENERATORS + ("editor",) + EXT_TYPES
IMAGE_DEFAULT_SECONDS = 3.0
STYLE_IMAGES_MAX = 3
KEEP_HISTORY = 24
CAP_OF = {"image": "image", "video": "video", "sound": "sound", "voice": "voice", "transcribe": "stt"}


def _sig(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:32]


def palette_of(path: Path, n: int = 4) -> List[str]:
    """Cores dominantes de uma imagem (ou do 1º quadro de um vídeo) usando o ffmpeg — dica de estilo para modelos só de texto."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return []
    try:
        r = subprocess.run([ff, "-loglevel", "error", "-i", str(path), "-vf", "scale=8:8:flags=area", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    raw = r.stdout
    if r.returncode != 0 or len(raw) < 192:
        return []
    buckets: Dict[Tuple[int, int, int], List[Tuple[int, int, int]]] = {}
    for i in range(0, 192, 3):
        px = (raw[i], raw[i + 1], raw[i + 2])
        buckets.setdefault((px[0] // 64, px[1] // 64, px[2] // 64), []).append(px)
    top = sorted(buckets.values(), key=len, reverse=True)[:n]
    return ["#%02x%02x%02x" % tuple(sum(p[c] for p in grp) // len(grp) for c in range(3)) for grp in top]


class Style:
    """Estilos que valem para um nó: texto (Style Prompt + descrição das pastas) e imagens de referência."""

    def __init__(self) -> None:
        self.texts: List[str] = []
        self.images: List[Tuple[bytes, str]] = []
        self.parts: List[str] = []  # o que identifica o estilo (texto dos Style Prompt e conteúdo das pastas) — vai no hash do nó

    @property
    def text(self) -> str:
        return " ".join(t.strip() for t in self.texts if t.strip())

    def signature(self) -> str:
        return _sig(self.parts)


class CanvasEngine:
    def __init__(self, store: Any, cid: str, emit: Optional[Callable[[dict], None]] = None, cancelled: Callable[[], bool] = lambda: False, team: Optional[Dict[str, Any]] = None):
        self.store = store
        self.team_req = team or {}
        self.cs = store.projects
        self.cid = cid
        self.settings = store.get_settings()
        media_mod.PERF = self.settings.get("performance") or {}
        self.emit = emit or (lambda ev: None)
        self.cancelled = cancelled
        self._cur = ""
        self._cv: Optional[Dict[str, Any]] = None   # canvas em memória e a versão do armazenamento em que ele vale
        self._cv_rev = -1
        self._ix_for: Optional[Dict[str, Any]] = None
        self._ix: Dict[str, Any] = {}
        self.ctl = Ctl(check=self._check, note=lambda m: self.emit({"type": "note", "node": self._cur, "message": m}))

    # ------------------------------------------------------------------ utilidades
    def _check(self) -> None:
        if self.cancelled():
            raise Cancelled()

    def team_chat(self, provider: Any, pid: str, messages: List[Dict[str, Any]], system: str, temperature: float, max_tokens: int) -> str:
        """Uma chamada de texto da IA com a equipe do Canvas (`settings.canvas`: 1/2/4/8/12/16/20/24/28/32 agentes e esforço Low … Omni): o esforço pede o pensamento ao modelo e dá mais espaço à resposta;
        com 4+ agentes, cada um escreve notas privadas (em paralelo) que o redator final usa. Com 1 agente e esforço High é a chamada de sempre."""
        team = teamlib.from_config(self.settings.get("canvas"), self.team_req)
        teamlib.apply_thinking(provider, team, pid)
        notes = ""
        if team.multi:
            kept, provider.thinking = provider.thinking, "off"
            try:
                notes = teamlib.team_notes(provider, messages, team, cancelled=self.cancelled, note=lambda m: self.emit({"type": "note", "node": self._cur, "message": m}))
            finally:
                provider.thinking = kept
            self._check()
        return str(provider.chat(messages, system=system + teamlib.notes_block(notes), temperature=temperature, max_tokens=int(max_tokens * team.tokens_mult))).strip()

    def canvas(self) -> Dict[str, Any]:
        """O canvas atual. Só relê o arquivo quando alguém gravou depois da última leitura (fluxos grandes lidos nó a nó faziam centenas de leituras iguais)."""
        rev = self.cs.rev(self.cid)
        if self._cv is None or rev != self._cv_rev:
            c = self.cs.get(self.cid)
            if not c:
                raise ValueError("Projeto não encontrado.")
            self._cv, self._cv_rev = c, rev
        return self._cv

    def _set_result(self, nid: str, result: Dict[str, Any]) -> None:
        """Grava o resultado de um nó e mantém o canvas em memória em dia, sem reler o arquivo (se foi só a nossa gravação)."""
        before = self.cs.rev(self.cid)
        ok = self.cs.set_node_result(self.cid, nid, result)
        if ok and self._cv is not None and self._cv_rev == before and self.cs.rev(self.cid) == before + 1:
            n = self._node(self._cv, nid)
            if n is not None:
                n["result"] = normalize_result(result)
                self._cv_rev = before + 1

    def _index(self, canvas: Dict[str, Any]) -> Dict[str, Any]:
        """Tabelas de consulta do canvas (nó por id, arquivo por id, conexões que chegam em cada porta e em cada nó), refeitas só quando o canvas muda."""
        size = (len(canvas["nodes"]), len(canvas["edges"]), len(canvas["assets"]))
        if self._ix_for is not canvas or self._ix.get("n") != size:
            into: Dict[Tuple[str, str], List[str]] = {}
            preds: Dict[str, List[str]] = {}
            for e in canvas["edges"]:
                into.setdefault((e["to"], e["port"]), []).append(e["from"])
                preds.setdefault(e["to"], []).append(e["from"])
            self._ix_for = canvas
            self._ix = {"n": size, "nodes": {n["id"]: n for n in canvas["nodes"]}, "assets": {a["id"]: a for a in canvas["assets"]}, "into": into, "preds": preds}
        return self._ix

    def _node(self, canvas: Dict[str, Any], nid: str) -> Optional[Dict[str, Any]]:
        return self._index(canvas)["nodes"].get(nid)

    def _assets(self, canvas: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return self._index(canvas)["assets"]

    def _asset_bytes(self, a: Dict[str, Any]) -> Optional[bytes]:
        p = self.cs.asset_path(self.cid, a["file"])
        return p.read_bytes() if p else None

    def _edges_to(self, canvas: Dict[str, Any], nid: str, port: str) -> List[str]:
        return list(self._index(canvas)["into"].get((nid, port), ()))

    # ------------------------------------------------------------------ saída de um nó
    def output(self, canvas: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
        """O que um nó entrega às conexões: {"text": str, "assets": [asset…]}."""
        assets = self._assets(canvas)
        t, p, r = node["type"], node["params"], node["result"]
        if t == "text":
            return {"text": p["text"], "assets": []}
        if t == "upload":
            return {"text": "", "assets": [assets[i] for i in p["files"] if i in assets]}
        if t in nodes_ext.TEXT_OUT or t in ("llm", "transcribe"):
            return {"text": r["text"] if r["state"] == "done" else "", "assets": []}
        if t in EXT_TYPES:  # nós novos que entregam arquivos (a Galeria entrega também o texto que recebeu)
            return {"text": r["text"] if r["state"] == "done" and t == "out_gallery" else "", "assets": [assets[i] for i in r["assets"] if i in assets] if r["state"] == "done" else []}
        if t in ("image", "video", "sound", "voice", "editor"):
            return {"text": "", "assets": [assets[i] for i in r["assets"] if i in assets] if r["state"] == "done" else []}
        return {"text": "", "assets": []}

    def inputs(self, canvas: Dict[str, Any], node: Dict[str, Any], port: str) -> Dict[str, Any]:
        texts: List[str] = []
        assets: List[Dict[str, Any]] = []
        for src in self._edges_to(canvas, node["id"], port):
            sn = self._node(canvas, src)
            if not sn or sn["type"] in ("style_prompt", "style_folder"):
                continue
            o = self.output(canvas, sn)
            if o["text"].strip():
                texts.append(o["text"].strip())
            assets += o["assets"]
        return {"text": "\n\n".join(texts), "assets": assets}

    # ------------------------------------------------------------------ estilos
    def style_ids(self, canvas: Dict[str, Any], node: Dict[str, Any]) -> List[str]:
        ids: List[str] = []
        if not node["params"].get("ignore_global_styles"):
            ids += [n["id"] for n in canvas["nodes"] if n["type"] in ("style_prompt", "style_folder") and n["params"].get("global", True)]
        for src in self._edges_to(canvas, node["id"], "style"):
            if src not in ids:
                ids.append(src)
        return ids

    def styles_for(self, canvas: Dict[str, Any], node: Dict[str, Any], need_digest: bool = True) -> Style:
        st = Style()
        assets = self._assets(canvas)
        for sid in self.style_ids(canvas, node):
            sn = self._node(canvas, sid)
            if not sn:
                continue
            if sn["type"] == "style_prompt":
                if sn["params"]["text"].strip():
                    st.texts.append(sn["params"]["text"].strip())
                    st.parts.append(sn["params"]["text"].strip())
            elif sn["type"] == "style_folder" and style_files(sn["params"]):
                key = self.folder_key(canvas, sn)
                st.parts.append(f"{sid}:{key}")
                if need_digest:
                    digest = self.folder_digest(canvas, sn)
                    if digest:
                        st.texts.append(digest)
                else:
                    st.texts.append(sn["result"]["digest"] if sn["result"]["digest_key"] == key else "")
                for _path, aid in style_files(sn["params"]):
                    a = assets.get(aid)
                    if a and a["kind"] == "image" and len(st.images) < STYLE_IMAGES_MAX and need_digest:
                        b = self._asset_bytes(a)
                        if b:
                            st.images.append((b, a["mime"]))
        return st

    def folder_key(self, canvas: Dict[str, Any], node: Dict[str, Any]) -> str:
        assets = self._assets(canvas)
        pid = self.settings["active"].get("generation", "demo")
        return _sig([[("/".join(path), i, assets[i]["bytes"]) for path, i in style_files(node["params"]) if i in assets], pid])

    def folder_digest(self, canvas: Dict[str, Any], node: Dict[str, Any], force: bool = False) -> str:
        """Descreve as mídias do Style Folder (com o provedor de IA configurado, se tiver visão) e guarda a descrição no nó."""
        key = self.folder_key(canvas, node)
        if not force and node["result"]["digest_key"] == key and node["result"]["digest"]:
            return node["result"]["digest"]
        assets = self._assets(canvas)
        items, pal = [], []
        groups: Dict[str, int] = {}
        for folder, aid in style_files(node["params"]):
            a = assets.get(aid)
            path = self.cs.asset_path(self.cid, a["file"]) if a else None
            if not a or not path:
                continue
            label = "/".join(folder + [a["name"]])   # o nome da pasta é uma dica de estilo («Personagens», «Cenários», «Luz»…)
            groups["/".join(folder)] = groups.get("/".join(folder), 0) + 1
            items.append(att.analyze(path, label, a["mime"], max_chars=1500))
            if a["kind"] in ("image", "video"):
                pal += palette_of(path, 3)
        if not items:
            return ""
        notes = att.build_digest(items, 6000)
        named = [f"{k} ({v})" for k, v in groups.items() if k]
        if named:
            notes += "\n\nPastas de referência (o nome de cada pasta diz o que ela mostra): " + "; ".join(named)
        palette = ", ".join(dict.fromkeys(pal))[:200]
        text = ""
        try:
            pid = self.settings["active"].get("generation", "demo")
            provider = build_provider(self.settings, pid, self.store.models_dir)
            if pid != "demo":
                content: List[Dict[str, Any]] = [{"type": "text", "text": "Arquivos de referência de estilo de um projeto criativo:\n\n" + notes + (f"\n\nCores dominantes: {palette}" if palette else "")}]
                if provider.vision:
                    content += [{"type": "image", **img} for img in att.collect_images(items, 6)]
                self._check()
                text = self.team_chat(provider, pid, [{"role": "user", "content": content}], STYLE_SYSTEM, 0.3, 500)
        except (ProviderError, ValueError) as exc:
            self.emit({"type": "note", "node": node["id"], "message": f"Não foi possível descrever o estilo com a IA ({exc}); usando as informações básicas dos arquivos."})
        if not text:
            kinds = ", ".join(sorted({i["kind"] for i in items}))
            text = f"Seguir o estilo de {len(items)} arquivo(s) de referência ({kinds})" + (f"; cores dominantes {palette}" if palette else "") + "."
        res = dict(node["result"])
        res.update({"digest": text[:4000], "digest_key": key})
        self._set_result(node["id"], res)
        node["result"] = res
        return text[:4000]

    # ------------------------------------------------------------------ hash (cache)
    def provider_for(self, node: Dict[str, Any]) -> Tuple[str, str]:
        cap = CAP_OF.get(node["type"], "")
        if not cap:
            return "", ""
        pid = pick_provider(self.settings, cap, node["params"].get("provider", ""))
        return pid, node["params"].get("model") or media_config(self.settings, pid)["models"].get(cap, "")

    def node_hash(self, canvas: Dict[str, Any], node: Dict[str, Any]) -> str:
        t = node["type"]
        data: Dict[str, Any] = {"type": t, "params": node["params"]}
        if t in ("image", "video", "sound", "voice", "llm", "transcribe", "editor") or t in EXT_TYPES:
            ports: Dict[str, Any] = {}
            for pid_, _label, _acc, _multi in NODE_TYPES[t]["ins"]:
                if pid_ == "style":
                    continue
                items = []
                for src in self._edges_to(canvas, node["id"], pid_):
                    sn = self._node(canvas, src)
                    if sn:
                        o = self.output(canvas, sn)
                        items.append([_sig(o["text"]), [a["id"] for a in o["assets"]]])
                ports[pid_] = items
            data["in"] = ports
        if t in ("image", "video"):   # as imagens citadas com @ no prompt entram no hash: citar outra (ou trocar o arquivo) deixa o nó desatualizado
            txt = "\n\n".join(x for x in (self.inputs(canvas, node, "prompt")["text"], node["params"].get("prompt", "").strip()) if x)   # o @ vale também no texto de um nó Texto ligado
            data["mentions"] = mentions_mod.ids_in(canvas, txt)
        if t in ("image", "video", "sound", "voice", "llm", "text_refine"):
            data["style"] = self.styles_for(canvas, node, need_digest=False).signature()
            data["style_ids"] = self.style_ids(canvas, node)
        if t in CAP_OF:
            try:
                data["provider"] = self.provider_for(node)
            except ProviderError:
                data["provider"] = "?"
        if t in ("llm", "text_refine") or (t == "image" and upsample.wants(node["params"].get("model", ""))):
            data["llm"] = self.settings["active"].get("generation", "demo")   # o texto de saída (ou o prompt expandido do FLUX.3) depende do modelo de texto configurado
        if t in ("in_vars", "in_url", "out_gallery"):  # dependem de algo fora dos parâmetros: o resultado vale até o usuário pedir de novo
            data["fixed"] = True
        return _sig(data)

    def stale_ids(self, canvas: Dict[str, Any]) -> List[str]:
        """Nós geradores cujo resultado está desatualizado (nunca rodou, algo mudou ou um nó de entrada está desatualizado)."""
        by_id = self._index(canvas)["nodes"]
        preds = self._index(canvas)["preds"]
        order = self.topo(canvas)
        stale: Dict[str, bool] = {}
        for nid in order:
            n = by_id[nid]
            if n["type"] not in RUNNABLE:
                stale[nid] = False
                continue
            s = n["result"]["state"] != "done" or n["result"]["hash"] != self.node_hash(canvas, n)
            if not s:
                s = any(stale.get(src) for src in preds.get(nid, ()))
            stale[nid] = s
        return [i for i, v in stale.items() if v]

    # ------------------------------------------------------------------ plano
    @staticmethod
    def topo(canvas: Dict[str, Any]) -> List[str]:
        """Ordem de execução (Kahn, fila FIFO — estável). Núcleo Rust (interface 4) quando existe; o mesmo cálculo em Python senão. Nós presos num ciclo ficam de fora."""
        ids = [n["id"] for n in canvas["nodes"]]
        pos = {i: k for k, i in enumerate(ids)}
        edges = [(pos[e["from"]], pos[e["to"]]) for e in canvas["edges"] if e["from"] in pos and e["to"] in pos]
        return [ids[k] for k in native.topo(len(ids), edges)["order"]]

    @staticmethod
    def levels(canvas: Dict[str, Any]) -> Dict[str, int]:
        """Nível de cada nó (caminho mais longo desde uma raiz): nós do mesmo nível não dependem um do outro."""
        ids = [n["id"] for n in canvas["nodes"]]
        pos = {i: k for k, i in enumerate(ids)}
        r = native.topo(len(ids), [(pos[e["from"]], pos[e["to"]]) for e in canvas["edges"] if e["from"] in pos and e["to"] in pos])
        return {i: r["level"][k] for k, i in enumerate(ids)}

    def plan(self, canvas: Dict[str, Any], targets: Optional[List[str]]) -> List[str]:
        order = self.topo(canvas)
        if not targets:
            return [i for i in order if self._node(canvas, i)["type"] in RUNNABLE]
        need = set()
        stack = list(targets)
        preds = self._index(canvas)["preds"]
        while stack:
            cur = stack.pop()
            if cur in need:
                continue
            need.add(cur)
            stack += preds.get(cur, ())
        return [i for i in order if i in need and self._node(canvas, i)["type"] in RUNNABLE]

    # ------------------------------------------------------------------ execução
    def run(self, targets: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
        """Roda os nós (todos, ou os alvos e o que eles precisam). `force` refaz também os alvos que já estavam prontos."""
        canvas = self.canvas()
        for t in targets or []:
            if not self._node(canvas, t):
                raise ValueError("Nó não encontrado.")
        plan = self.plan(canvas, targets)
        if not plan:
            self.emit({"type": "start", "nodes": []})
            for t in targets or []:  # nós de estilo: gera/atualiza a descrição da pasta
                n = self._node(canvas, t)
                if n and n["type"] == "style_folder":
                    self._cur = t
                    self.emit({"type": "node", "id": t, "state": "running"})
                    self.folder_digest(canvas, n, force=force)
                    self.emit({"type": "node", "id": t, "state": "done"})
            return {"ran": 0, "cached": 0, "errors": 0, "skipped": 0}
        self.emit({"type": "start", "nodes": plan})
        stats = {"ran": 0, "cached": 0, "errors": 0, "skipped": 0}
        failed: set = set()
        for nid in plan:
            self._check()
            canvas = self.canvas()
            node = self._node(canvas, nid)
            if not node:
                continue
            self._cur = nid
            if any(src in failed for src in self._index(canvas)["preds"].get(nid, ())):
                self.emit({"type": "node", "id": nid, "state": "skipped", "message": "Um nó de entrada falhou."})
                failed.add(nid)
                stats["skipped"] += 1
                continue
            forced = force and (not targets or nid in targets)
            h = self.node_hash(canvas, node)
            if not forced and node["result"]["state"] == "done" and node["result"]["hash"] == h:
                self.emit({"type": "node", "id": nid, "state": "cached"})
                stats["cached"] += 1
                continue
            self._set_result(nid, {**node["result"], "state": "running", "error": ""})
            self.emit({"type": "node", "id": nid, "state": "running"})
            try:
                res = self._execute(canvas, node, forced)
                fresh = self.canvas()  # o Editor preenche sua própria linha do tempo ao rodar: o hash vale para o estado final do nó
                h = self.node_hash(fresh, self._node(fresh, nid) or node)
                res.update({"state": "done", "hash": h, "ts": now_iso(), "error": ""})
                res.setdefault("digest", node["result"]["digest"])
                res.setdefault("digest_key", node["result"]["digest_key"])
                self._set_result(nid, res)
                self.cs.prune_node_assets(self.cid, nid, KEEP_HISTORY)
                self.emit({"type": "node", "id": nid, "state": "done", "assets": res["assets"], "text": res["text"][:400], "warnings": res.get("warnings", [])})
                stats["ran"] += 1
            except Cancelled:
                self._set_result(nid, {**node["result"], "state": "idle"})
                raise
            except (ProviderError, ValueError) as exc:
                if str(exc) == "cancelado":
                    self._set_result(nid, {**node["result"], "state": "idle"})
                    raise Cancelled()
                self._fail(node, str(exc), stats, failed)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._fail(node, f"Erro inesperado: {exc}", stats, failed)
        self.emit({"type": "summary", **stats})
        return stats

    def _fail(self, node: Dict[str, Any], msg: str, stats: Dict[str, int], failed: set) -> None:
        self._set_result(node["id"], {**node["result"], "state": "error", "error": msg[:1600]})
        self.emit({"type": "node", "id": node["id"], "state": "error", "message": msg[:1600]})
        stats["errors"] += 1
        failed.add(node["id"])

    def _execute(self, canvas: Dict[str, Any], node: Dict[str, Any], forced: bool) -> Dict[str, Any]:
        t = node["type"]
        if t in EXT_TYPES:
            return nodes_ext.RUNNERS[t](self, canvas, node)
        if t == "editor":
            return self._editor(canvas, node)
        if t == "llm":
            return self._llm(canvas, node)
        if t == "transcribe":
            return self._transcribe(canvas, node)
        return self._generate(canvas, node, forced)

    # ------------------------------------------------------------------ geradores de mídia
    def _provider(self, node: Dict[str, Any]) -> Tuple[Any, str, str]:
        pid, model = self.provider_for(node)
        return build_media(self.settings, pid, self.ctl, self.store.models_dir), pid, model

    @staticmethod
    def _title(node: Dict[str, Any], fallback: str) -> str:
        return node.get("title") or fallback

    def _save(self, node: Dict[str, Any], media: Media, kind: str, name: str, prompt: str, pid: str, model: str) -> str:
        a = self.cs.add_asset(self.cid, media.data, media.ext, kind, name=name, mime=media.mime, node=node["id"], prompt=prompt[:600], provider=pid, model=model)
        if not a:
            raise ProviderError("Não foi possível salvar o arquivo gerado.")
        return a["id"]

    def _generate(self, canvas: Dict[str, Any], node: Dict[str, Any], forced: bool) -> Dict[str, Any]:
        t, p = node["type"], node["params"]
        style = self.styles_for(canvas, node)
        seed = p.get("seed", 0) or (random.randint(1, 2 ** 31 - 1) if forced else 0)
        prov, pid, model = self._provider(node)
        warnings: List[str] = []
        ids: List[str] = []
        if t == "image":
            base = "\n\n".join(x for x in (self.inputs(canvas, node, "prompt")["text"], p["prompt"].strip()) if x)
            if not base:
                raise ValueError("O nó Imagem precisa de um prompt: escreva nele ou ligue um nó de texto.")
            raw_base = base
            base, ment_ids, missing = mentions_mod.resolve(canvas, base)   # «@mídia» no prompt (ou num Texto ligado): imagens e quadros de vídeo viram as primeiras referências
            warnings += [f"@{m}: não há mídia com esse apelido neste canvas — ficou como texto." for m in missing]
            ment_refs, ment_warn = self._mention_media(canvas, ment_ids, "imagem")
            warnings += ment_warn
            refs = _unique_refs(ment_refs + self.image_inputs(canvas, node, "refs"))[:mentions_mod.MAX_REFS]   # a mesma imagem citada com @ e ligada em «Referências» vale uma vez só
            if p["mode"] == "edit" and not refs:
                raise ValueError("No modo Editar, ligue uma imagem na entrada \"Referências\".")
            body = base
            prompt = body + (f"\n\nStyle: {style.text}" if style.text else "")
            use_refs = list(refs)
            if not use_refs and style.images and getattr(prov, "supports_refs", False) and _style_refs_ok(pid, model):
                use_refs = list(style.images)  # modelos que aceitam várias imagens usam o Style Folder como referência
            needs_edit = getattr(prov, "refs_need_edit", lambda m="": getattr(prov, "refs_edit_only", False))(p["model"] or model)   # por modelo: o klein junta referências também no modo Gerar
            if use_refs and prov.supports_refs and needs_edit and p["mode"] != "edit":
                warnings.append(f"{prov.label} só usa imagens de referência no modo Editar (imagem → imagem). No modo Gerar elas viram só texto — para editar uma imagem, escolha «Editar».")
                use_refs = []
            elif use_refs and prov.supports_refs:
                cap = getattr(prov, "max_refs", lambda m="": 99)(p["model"] or model)
                if len(use_refs) > cap:
                    warnings.append(f"Este modelo usa só {cap} imagem(ns) de referência: usei {'a primeira' if cap == 1 else 'as ' + str(cap) + ' primeiras'} e ignorei as outras {len(use_refs) - cap}.")
                    use_refs = use_refs[:cap]
            if use_refs and not prov.supports_refs and p["mode"] == "edit":
                raise ValueError(f"{prov.label} não consegue editar imagens (não aceita imagem de entrada). Escolha outro modelo no nó, ou volte o modo para Gerar.")
            if use_refs and not prov.supports_refs:
                warnings.append(f"{prov.label} não aceita imagens de referência — usei só o texto.")
                use_refs = []
            if ment_ids and not use_refs:   # as imagens citadas não chegam ao modelo: sem a marcação «reference image N», que não apontaria para nada
                body = mentions_mod.plain(canvas, raw_base)
                prompt = body + (f"\n\nStyle: {style.text}" if style.text else "")
            extra = dict(p["extra"])
            if extra.pop("upsample", True) and upsample.wants(p["model"] or model) and not upsample.is_caption(body):   # FLUX.3 Image Klein: pede legendas de cena completas
                try:
                    llm_pid = self.settings["active"].get("generation", "demo")
                    if llm_pid == "demo":
                        warnings.append("O FLUX.3 Image Klein rende melhor com legendas de cena completas: configure um modelo de texto em Configuração para o OpenFlow expandir o prompt (ou escreva a legenda inteira).")
                    else:
                        self._check()
                        caption = upsample.expand(build_provider(self.settings, llm_pid, self.store.models_dir), body, edit=bool(use_refs), refs=len(use_refs))
                        prompt = caption + (f"\n\nStyle: {style.text}" if style.text else "")
                        warnings.append("Prompt expandido para o FLUX.3: " + caption[:300] + ("…" if len(caption) > 300 else ""))
                except (ProviderError, ValueError) as exc:
                    warnings.append(f"Não consegui expandir o prompt ({exc}); usei o texto como está — o FLUX.3 rende melhor com legendas completas.")
            medias = prov.image(prompt, size=p["size"], count=p["count"], seed=seed, negative=p["negative"], refs=use_refs, model=p["model"], extra=extra)
            for i, m in enumerate(medias):
                ids.append(self._save(node, m, "image", f"{self._title(node, 'Imagem')} {i + 1}", prompt, pid, model))
            return {"assets": ids, "text": "", "warnings": warnings}
        if t == "video":
            base = "\n\n".join(x for x in (self.inputs(canvas, node, "prompt")["text"], p["prompt"].strip()) if x)
            base, ment_ids, missing = mentions_mod.resolve(canvas, base)
            warnings += [f"@{m}: não há mídia com esse apelido neste canvas — ficou como texto." for m in missing]
            ment_refs, ment_warn = self._mention_media(canvas, ment_ids, "vídeo")
            warnings += ment_warn
            first = next(iter(self.image_inputs(canvas, node, "image")), None) or next(iter(ment_refs), None)   # a 1ª imagem (ou quadro de vídeo) citada vira a imagem inicial, se nenhuma está ligada
            if len(ment_refs) > 1:
                warnings.append("O vídeo usa uma só imagem inicial: só a primeira citada com @ virou imagem; as outras valem como texto.")
            if not base and not first:
                raise ValueError("O nó Vídeo precisa de um prompt (ou de uma imagem inicial ligada).")
            start = first
            prompt = (base or "Animate this image with gentle, natural motion") + (f"\n\nStyle: {style.text}" if style.text else "")
            m = prov.video(prompt, duration=p["duration"], aspect=p["aspect"], image=start, model=p["model"], extra=p["extra"], seed=seed, long_side=p["resolution"])
            return {"assets": [self._save(node, m, "video", self._title(node, "Vídeo"), prompt, pid, model)], "text": "", "warnings": warnings}
        if t == "sound":
            prompt = p["prompt"].strip() or self.inputs(canvas, node, "prompt")["text"]
            if not prompt:
                raise ValueError("O nó Som precisa de uma descrição (ex.: \"chuva forte com trovões\").")
            prompt = (prompt + (f"\n\nStyle: {style.text}" if style.text else "")) if p["kind"] == "music" else prompt
            m = prov.sound(prompt, kind=p["kind"], duration=p["duration"], model=p["model"], extra=p["extra"], seed=seed)
            return {"assets": [self._save(node, m, "audio", self._title(node, "Música" if p["kind"] == "music" else "Som"), prompt, pid, model)], "text": "", "warnings": warnings}
        if t == "voice":
            speech = "\n\n".join(x for x in (self.inputs(canvas, node, "text")["text"], p["text"].strip()) if x)
            if not speech:
                raise ValueError("O nó Voz precisa de um texto para falar.")
            m = prov.voice(speech, voice=p["voice"], speed=p["speed"], model=p["model"], extra=p["extra"], instructions=style.text)
            return {"assets": [self._save(node, m, "audio", self._title(node, "Voz"), speech, pid, model)], "text": "", "warnings": warnings}
        raise ValueError(f"Tipo de nó sem gerador: {t}")

    def _video_frame(self, a: Dict[str, Any]) -> Optional[Tuple[bytes, str]]:
        """O quadro do meio de um vídeo do canvas como (png, mime)."""
        src = self.cs.asset_path(self.cid, a["file"])
        ff = shutil.which("ffmpeg")
        if not (ff and src):
            return None
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / "f.png"
            r = subprocess.run([ff, "-y", "-loglevel", "error", "-ss", f"{(a.get('duration') or 2.0) / 2:.2f}", "-i", str(src), "-frames:v", "1", str(dst)], capture_output=True, timeout=120)
            return (dst.read_bytes(), "image/png") if r.returncode == 0 and dst.exists() else None

    def _mention_media(self, canvas: Dict[str, Any], ids: List[str], target: str) -> Tuple[List[Tuple[bytes, str]], List[str]]:
        """As mídias citadas com @ como imagens de referência: imagem → ela mesma; vídeo → o quadro do meio; som → nada (só texto), com aviso. `target`: «imagem» ou «vídeo» (para a mensagem)."""
        assets = self._assets(canvas)
        out: List[Tuple[bytes, str]] = []
        warn: List[str] = []
        for i in ids:
            a = assets.get(i)
            if not a:
                continue
            if a["kind"] == "audio":
                warn.append(f"«{a.get('name') or i}» é um som: modelos de {target} não usam áudio como referência — ficou só como texto.")
                continue
            got = (self._asset_bytes(a), a["mime"]) if a["kind"] == "image" else self._video_frame(a)
            if got and got[0]:
                out.append(got)
            else:
                warn.append(f"«{a.get('name') or i}» não pôde ser lida (arquivo ausente ou vídeo sem quadro): a imagem citada não foi enviada como referência.")
        return out, warn

    def image_inputs(self, canvas: Dict[str, Any], node: Dict[str, Any], port: str) -> List[Tuple[bytes, str]]:
        """Imagens de uma porta como (bytes, mime). Um vídeo ligado numa porta de imagem entra pelo quadro do meio."""
        out: List[Tuple[bytes, str]] = []
        for a in self.inputs(canvas, node, port)["assets"]:
            if a["kind"] == "image":
                b = self._asset_bytes(a)
                if b:
                    out.append((b, a["mime"]))
            elif a["kind"] == "video":
                fr = self._video_frame(a)
                if fr:
                    out.append(fr)
        return out

    def _transcribe(self, canvas: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
        src = next((a for a in self.inputs(canvas, node, "audio")["assets"] if a["kind"] in ("audio", "video")), None)
        if not src:
            raise ValueError("Ligue um áudio ou vídeo na entrada do nó Transcrever.")
        data = self._asset_bytes(src)
        if data is None:
            raise ValueError("O arquivo de entrada não existe mais.")
        prov, pid, model = self._provider(node)
        mime, name = src["mime"], src["name"]
        if src["kind"] == "video":  # extrai só o áudio (arquivos de vídeo costumam passar do limite dos serviços)
            data, mime, name = _audio_of_video(self.cs.asset_path(self.cid, src["file"]), self.ctl) or (data, mime, name)
        return {"assets": [], "text": prov.transcribe(data, name, mime, language=node["params"]["language"], model=node["params"]["model"])}

    def _llm(self, canvas: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
        p = node["params"]
        source = self.inputs(canvas, node, "prompt")["text"]
        if not (p["instruction"].strip() or source):
            raise ValueError("O nó Texto IA precisa de uma instrução ou de um texto ligado na entrada.")
        style = self.styles_for(canvas, node)
        pid = p["provider"] or self.settings["active"].get("generation", "demo")
        provider = build_provider(self.settings, pid, self.store.models_dir)
        if pid == "demo":
            return {"assets": [], "text": proc.demo_llm(p["instruction"], source, style.text)}
        system = LLM_SYSTEM + (f"\n\nEstilo do projeto (siga-o): {style.text}" if style.text else "")
        user = (p["instruction"].strip() + ("\n\n" if p["instruction"].strip() and source else "") + (f"Texto de entrada:\n{source}" if source else "")).strip()
        self._check()
        out = self.team_chat(provider, pid, [{"role": "user", "content": user}], system, p["temperature"], 1500)
        return {"assets": [], "text": out}

    # ------------------------------------------------------------------ Editor
    def resolve_clip(self, canvas: Dict[str, Any], clip: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        assets = self._assets(canvas)
        a = None
        if clip.get("node"):
            sn = self._node(canvas, clip["node"])
            outs = self.output(canvas, sn)["assets"] if sn else []
            a = outs[clip["idx"]] if clip["idx"] < len(outs) else (outs[0] if outs else None)
        if not a and clip.get("asset"):
            a = assets.get(clip["asset"])
        path = self.cs.asset_path(self.cid, a["file"]) if a else None
        if not a or not path or a["kind"] not in ("image", "video", "audio"):
            return None
        return {"path": path, "kind": a["kind"], "duration": a["duration"] or (IMAGE_DEFAULT_SECONDS if a["kind"] == "image" else 3.0), "asset": a}

    def auto_timeline(self, canvas: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
        """Monta uma linha do tempo com as saídas dos nós ligados: imagens/vídeos em sequência, áudios juntos a partir do início, textos como legenda."""
        tl = node["params"]["timeline"]
        vtrack = next((t["id"] for t in tl["tracks"] if t["kind"] == "video"), "t_v1")
        atracks = [t["id"] for t in tl["tracks"] if t["kind"] == "audio"] or ["t_a1"]
        ttrack = next((t["id"] for t in tl["tracks"] if t["kind"] == "text"), "")
        tracks = list(tl["tracks"])
        if not any(t["id"] == vtrack for t in tracks):
            tracks.insert(0, {"id": vtrack, "kind": "video", "name": "V1", "muted": False, "hidden": False})
        clips: List[Dict[str, Any]] = []
        cursor, n_audio, captions = 0.0, 0, []
        for src in self._edges_to(canvas, node["id"], "clips"):
            sn = self._node(canvas, src)
            if not sn:
                continue
            outs = self.output(canvas, sn)
            if outs["text"].strip():
                captions.append(outs["text"].strip())
            for idx, a in enumerate(outs["assets"]):
                dur = a["duration"] or (IMAGE_DEFAULT_SECONDS if a["kind"] == "image" else 3.0)
                base = {"asset": a["id"], "node": src, "idx": idx, "dur": round(dur, 2)}
                if a["kind"] in ("image", "video"):
                    clips.append({**base, "track": vtrack, "start": round(cursor, 2), "fit": "contain"})
                    cursor += dur
                elif a["kind"] == "audio":
                    while len(atracks) <= n_audio and len(atracks) < 6:
                        tid = f"t_a{len(atracks) + 1}"
                        tracks.append({"id": tid, "kind": "audio", "name": f"A{len(atracks) + 1}", "muted": False, "hidden": False})
                        atracks.append(tid)
                    clips.append({**base, "track": atracks[min(n_audio, len(atracks) - 1)], "start": 0})
                    n_audio += 1
        if captions:
            if not ttrack:
                ttrack = "t_t1"
                tracks.append({"id": ttrack, "kind": "text", "name": "T1", "muted": False, "hidden": False})
            total = max([c["start"] + c["dur"] for c in clips] + [3.0])
            clips.append({"track": ttrack, "text": captions[0][:300], "start": 0, "dur": round(total, 2), "size": 44, "bg": "#000000", "pos": "bottom"})
        return {**tl, "tracks": tracks, "clips": clips}

    def _editor(self, canvas: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
        p = node["params"]
        tl = p["timeline"]
        if not tl["clips"]:
            tl = self.auto_timeline(canvas, node)
            self.cs.patch_node_params(self.cid, node["id"], {"timeline": tl})
            tl = self._node(self.canvas(), node["id"])["params"]["timeline"]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.mp4"
            warnings = render_timeline(tl, p["width"], p["height"], p["fps"], p["bg"], lambda c: self.resolve_clip(canvas, c), out, self.ctl)
            data = out.read_bytes()
        a = self.cs.add_asset(self.cid, data, "mp4", "video", name=self._title(node, "Montagem"), mime="video/mp4", node=node["id"], provider="editor", w=p["width"], h=p["height"])
        if not a:
            raise ProviderError("Não foi possível salvar o vídeo exportado.")
        return {"assets": [a["id"]], "text": "", "warnings": warnings}


STYLE_SYSTEM = (
    "Você escreve guias de estilo curtos para projetos criativos. Receberá a descrição de arquivos de referência (imagens, vídeos, áudios, textos). "
    "Descreva em 3 a 6 frases o estilo COMUM a eles: para imagem/vídeo, paleta de cores, traço/textura, iluminação, composição e clima; para áudio, timbre, ritmo e atmosfera. "
    "Seja concreto e útil como complemento de um prompt de geração. Não cite nomes de arquivos. Responda só com a descrição, no idioma predominante dos textos (padrão: português)."
)
LLM_SYSTEM = "Você é um assistente de escrita criativa dentro de um fluxo de produção de mídia. Cumpra a instrução usando o texto de entrada. Se houver menções como @nome (apelidos de imagens, vídeos ou sons do projeto), mantenha-as exatamente como estão no texto final. Responda APENAS com o texto final, sem explicações nem aspas."


def _unique_refs(refs: List[Tuple[bytes, str]]) -> List[Tuple[bytes, str]]:
    """Tira as imagens repetidas (mesmo conteúdo), mantendo a ordem da primeira vez: as citadas com @ vêm antes, na ordem em que aparecem no texto, e a numeração «reference image N» do prompt continua apontando para a imagem certa."""
    import hashlib

    seen, out = set(), []
    for data, mime in refs:
        key = hashlib.sha1(data).digest()
        if key not in seen:
            seen.add(key)
            out.append((data, mime))
    return out


def _style_refs_ok(pid: str, model: str) -> bool:
    """Só alguns modelos tratam várias imagens como "referência de estilo" sem virar uma edição das imagens."""
    return (pid in ("openai",) and (model or "gpt-image-1").startswith("gpt-image")) or pid == "google"


def _audio_of_video(path: Optional[Path], ctl: Ctl) -> Optional[Tuple[bytes, str, str]]:
    ff = shutil.which("ffmpeg")
    if not ff or not path:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "a.mp3"
        try:
            r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(dst)], capture_output=True, timeout=600)
        except (OSError, subprocess.SubprocessError):
            return None
        return (dst.read_bytes(), "audio/mpeg", "audio.mp3") if r.returncode == 0 and dst.exists() else None
