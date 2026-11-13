"""Gerar um fluxo do Canvas a partir de um prompt: Planejador → Revisor (equipe de agentes: ver `team.py`), com validação determinística e um método automático (modelos de partida).

A IA só devolve **dados** (nós com tipo e parâmetros + ligações por chave); quem valida tipos, portas, compatibilidade e ciclos é o `schema.py`, e o resultado só entra no canvas pelo navegador (nada
é gravado aqui). Sem IA (Demo) ou com resposta inválida, vale um modelo de partida escolhido pelas palavras do pedido: sempre sai um fluxo.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..agents.runner import Runner
from ..providers import build_provider
from ..util import new_id, text
from . import schema as S

STEPS = ["planner", "reviewer", "build"]
MAX_FLOW_NODES = 24

# parâmetros que a IA pode preencher em cada tipo (o resto fica no padrão do nó)
FILL = {"text": "text", "llm": "instruction", "image": "prompt, size (e.g. 1024x1024), count", "video": "prompt, duration (s), aspect (16:9|9:16|1:1)", "sound": "prompt, kind (sfx|music), duration (s)",
        "voice": "text (what is spoken)", "style_prompt": "text (the look of the whole flow), global (true)", "text_refine": "mode, instruction", "img_text": "text overlay settings"}

PLANNER = """ROLE: Flow Planner.
Design a Canvas node flow that fulfils the user's request in INPUT_JSON.request. `catalog` lists every node type with its output type and input ports; `existing` summarizes nodes already in the canvas
(do not recreate them; you may mention them as context). Use the FEWEST nodes that fully do the job (usually 3 to 12): a Text node holds a prompt; Image/Video/Sound/Voice nodes generate media and take
the Text through their "prompt"/"text" port; a Style Prompt node (global) sets one look for everything; the Editor joins clips (port "clips") into a final video. Edges go from a node's output to an input port
of another node, the output type must fit the port, and there can be no cycles. Write real, specific prompts inside the nodes (not placeholders), in the user's language.
Output JSON:
{"title": str, "nodes": [{"key": "short unique key", "type": <catalog type>, "title": "optional short title", "params": {<only the fields listed in catalog[type].fill>}}],
 "edges": [{"from": key, "to": key, "port": <input port id of the target>}], "notes": str}"""

REVIEWER = """ROLE: Flow Reviewer.
Review the flow in INPUT_JSON.flow (already validated: invalid edges were dropped; `problems` lists what the validator found) against INPUT_JSON.request. Check: does it produce what was asked, are all needed
inputs connected, are prompts specific, is there anything missing (e.g. no Editor to join clips, no text feeding a generator) or superfluous. Be strict but fair: approve when it is good enough to run.
Output JSON: {"approved": bool, "score": 0-10, "summary": str, "issues": [{"problem": str, "fix": str}]}"""


def catalog() -> List[Dict[str, Any]]:
    return [{"type": k, "label": v["label"], "out": v["out"], "ins": [{"port": i[0], "accepts": i[2], "multi": i[3]} for i in v["ins"]], "fill": FILL.get(k, "")} for k, v in S.NODE_TYPES.items()]


def summarize(nodes: List[Dict[str, Any]], limit: int = 40) -> List[Dict[str, Any]]:
    return [{"type": n.get("type"), "title": n.get("title") or "", "text": text((n.get("params") or {}).get("text") or (n.get("params") or {}).get("prompt") or "", "", 120)} for n in nodes[:limit]]


# ---------------------------------------------------------------------------------- construção determinística
def build(plan: Any, origin: Tuple[float, float] = (60, 60)) -> Dict[str, Any]:
    """Plano da IA → {nodes, edges} válidos do Canvas (tipos, parâmetros, portas, compatibilidade e ciclos validados; posições em camadas da esquerda para a direita)."""
    plan = plan if isinstance(plan, dict) else {}
    keyed: Dict[str, Dict[str, Any]] = {}
    for raw in (plan.get("nodes") if isinstance(plan.get("nodes"), list) else [])[:MAX_FLOW_NODES]:
        raw = raw if isinstance(raw, dict) else {}
        key = text(raw.get("key") or raw.get("id"), "", 40)
        if not key or key in keyed or raw.get("type") not in S.NODE_TYPES:
            continue
        n = S.normalize_node({"id": new_id("n_"), "type": raw["type"], "title": raw.get("title"), "params": raw.get("params") if isinstance(raw.get("params"), dict) else {}}, keep_result=False)
        if n:
            keyed[key] = n
    nodes = list(keyed.values())
    edges_in = []
    for e in (plan.get("edges") if isinstance(plan.get("edges"), list) else []):
        e = e if isinstance(e, dict) else {}
        a, b = keyed.get(text(e.get("from"), "", 40)), keyed.get(text(e.get("to"), "", 40))
        if a and b:
            edges_in.append({"from": a["id"], "to": b["id"], "port": text(e.get("port"), "", 24)})
    edges = S.normalize_edges(edges_in, nodes)
    _layout(nodes, edges, origin)
    return {"nodes": nodes, "edges": edges, "dropped": len(edges_in) - len(edges)}


def _layout(nodes: List[Dict[str, Any]], edges: List[Dict[str, str]], origin: Tuple[float, float]) -> None:
    depth = {n["id"]: 0 for n in nodes}
    for _ in range(len(nodes)):   # camadas: a coluna de um nó é a maior distância até uma fonte
        for e in edges:
            depth[e["to"]] = max(depth[e["to"]], depth[e["from"]] + 1)
    rows: Dict[int, int] = {}
    for n in nodes:
        d = depth[n["id"]]
        n["x"] = round(origin[0] + d * 360, 1)
        n["y"] = round(origin[1] + rows.get(d, 0) * 300, 1)
        rows[d] = rows.get(d, 0) + 1


def problems(flow: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    nodes, edges = flow["nodes"], flow["edges"]
    if not nodes:
        return ["o fluxo está vazio"]
    if flow.get("dropped"):
        out.append(f"{flow['dropped']} ligação(ões) inválida(s) foram descartadas (porta, tipo ou ciclo)")
    for n in nodes:
        t_ = n["type"]
        wired = {e["port"] for e in edges if e["to"] == n["id"]}
        p = n["params"]
        if t_ in ("image", "video", "sound") and "prompt" not in wired and not str(p.get("prompt") or "").strip():
            out.append(f"o nó {S.NODE_TYPES[t_]['label']} não tem prompt nem texto ligado")
        if t_ == "voice" and "text" not in wired and not str(p.get("text") or "").strip():
            out.append("o nó Voz não tem fala nem texto ligado")
        if t_ == "editor" and "clips" not in wired:
            out.append("o Editor não recebe nenhum clipe")
    return out[:12]


# ---------------------------------------------------------------------------------- método automático
def fallback_plan(request: str) -> Dict[str, Any]:
    """Sem IA: escolhe um modelo de partida pelas palavras do pedido."""
    r = request.lower()
    if re.search(r"narra|voz|voice|fala|cena|filme|curta|short|trailer|história|story|scene", r):
        tpl = "scene"
    elif re.search(r"v[ií]deo|anim|clipe|movie|video", r):
        tpl = "image_video"
    elif re.search(r"estilo|style|aquarela|watercolor|cinematogr", r):
        tpl = "styled"
    else:
        tpl = "text_image"
    t_ = S.build_template(tpl, request)
    idx = {n["id"]: f"k{i}" for i, n in enumerate(t_["nodes"])}
    return {"title": request[:60], "notes": "método automático", "nodes": [{"key": idx[n["id"]], "type": n["type"], "params": n["params"]} for n in t_["nodes"]],
            "edges": [{"from": idx[e["from"]], "to": idx[e["to"]], "port": e["port"]} for e in t_["edges"]]}


class FlowPipeline(Runner):
    domain = "canvas"

    def __init__(self, store: Any, emit: Callable[[dict], None], cancelled: Callable[[], bool] = lambda: False):
        super().__init__(store, emit, cancelled)

    def run(self, req: Dict[str, Any]) -> Dict[str, Any]:
        settings = self.store.get_settings()
        request = text(req.get("prompt"), "", 6000)
        if not request:
            raise ValueError("Descreva o fluxo que você quer criar.")
        pid = settings["active"].get("generation", "demo")
        self.provider = build_provider(settings, pid, self.store.models_dir)
        self.gen = {"temperature": 0.5, "max_tokens": 3500, "content": "sfw" if (settings.get("generation") or {}).get("content") == "sfw" else "free"}
        self.language = "the same language as the user's request"
        self.configure_team(settings.get("canvas"), req, pid)
        self.emit({"type": "start", "steps": STEPS, "provider": pid, "model": self.provider.model, "demo": pid == "demo"})
        existing = summarize(req.get("existing") if isinstance(req.get("existing"), list) else [])
        payload = {"request": request, "catalog": catalog(), "existing": existing}
        origin = (float(req.get("x") or 60), float(req.get("y") or 60))

        self._step("planner", "running")
        if pid == "demo":
            self._check()
            plan, fb = fallback_plan(request), True
            self.warnings.append("modo Demo (sem IA): usei um modelo de partida; configure um modelo de texto para a IA montar o fluxo")
        else:
            plan, fb = self._agent("planner", "flow_planner", PLANNER, payload, lambda p: fallback_plan(request))
        flow = build(plan, origin)
        if not flow["nodes"]:
            plan, fb = fallback_plan(request), True
            flow = build(plan, origin)
        self._step("planner", "warn" if fb else "done", nodes=len(flow["nodes"]))

        self._step("reviewer", "running")
        review: Dict[str, Any] = {"approved": True, "issues": []}
        found = problems(flow)
        if pid != "demo" and not fb:
            for r in range(self.team.revisions(1)):
                review, _ = self._agent("reviewer", "flow_reviewer", REVIEWER, {"request": request, "flow": plan, "problems": found}, lambda p: {"approved": not found, "score": 6, "summary": "", "issues": [{"problem": x, "fix": ""} for x in found]})
                issues = [i for i in (review.get("issues") or []) if isinstance(i, dict)]
                if review.get("approved", True) or not issues:
                    break
                self.emit({"type": "revision", "round": r + 1, "issues": len(issues)})
                fix = "\n".join(f"- {i.get('problem')} → {i.get('fix')}" for i in issues)[:3000]
                plan2, fb2 = self._agent("planner", "flow_planner", PLANNER + "\n\nFEEDBACK TO FIX:\n" + fix, {**payload, "previous": plan}, lambda p: plan, feedback=True)
                flow2 = build(plan2, origin)
                if flow2["nodes"] and not fb2:
                    plan, flow, found = plan2, flow2, problems(flow2)
        self._step("reviewer", "done" if review.get("approved", True) and not found else "warn", issues=len(found))
        self._step("build", "done", nodes=len(flow["nodes"]), edges=len(flow["edges"]))
        if found:
            self.warnings.extend(found)
        result = {"type": "done", "title": text(plan.get("title"), "", 80), "nodes": flow["nodes"], "edges": flow["edges"], "notes": text(plan.get("notes"), "", 400),
                  "warnings": self.warnings[:12], "team": self.team.public()}
        self.emit(result)
        return result
