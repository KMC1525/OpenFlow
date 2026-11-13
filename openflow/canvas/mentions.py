"""Menções com «@» nos prompts do Canvas (v0.17.2; vídeos e sons na v0.17.4): `@nome` aponta para uma mídia **específica** do projeto e a usa como referência da geração.

* Cada **imagem, vídeo ou som** do canvas (enviado ou gerado) tem um *apelido* — o nome sem extensão, em minúsculas, sem acentos e com hífens (`Foto Perfil.png` → `foto-perfil`).
  Nomes repetidos ficam com `-2`, `-3`… (a mais antiga mantém o apelido simples), então um apelido sempre aponta para uma imagem só.
* Na hora de gerar, cada `@apelido` achado no prompt vira `apelido (reference image N)` e a imagem entra como referência N (na ordem em que foi citada). Um **vídeo** citado entra pelo
  quadro do meio (`apelido (reference image N, a frame of the video)`); um **som** não é imagem: fica no texto como `apelido (audio reference)` e o nó avisa que modelos de imagem/vídeo não usam áudio.
* O `@` vale em qualquer texto que chegue a um nó Imagem ou Vídeo — o prompt do próprio nó ou um nó de Texto ligado a ele.
* Um `@` que não casa com nenhuma imagem fica como está no texto e vira aviso; e-mails (`a@b.com`) nunca são tomados por menção.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Tuple

MENTION_RE = re.compile(r"(?<![\w@.])@([A-Za-z0-9][A-Za-z0-9_-]*)")
MAX_REFS = 6
KINDS = ("image", "video", "audio")


def slug(name: str) -> str:
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name or "")
    s = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-") or "imagem"


def table(canvas: Dict[str, Any]) -> List[Dict[str, Any]]:
    """As imagens, vídeos e sons do canvas com o apelido único de cada um, do mais novo para o mais antigo."""
    # mais antiga primeiro; no mesmo segundo vale a ordem em que entraram no canvas (o id é sorteado e não serve de desempate)
    imgs = [a for _, a in sorted(((i, a) for i, a in enumerate(canvas.get("assets", [])) if a.get("kind") in KINDS), key=lambda x: (x[1].get("created", ""), x[0]))]
    seen: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for a in imgs:
        base = slug(a.get("name", ""))
        seen[base] = seen.get(base, 0) + 1
        out.append({"id": a["id"], "slug": base if seen[base] == 1 else f"{base}-{seen[base]}", "name": a.get("name", ""), "file": a.get("file", ""), "kind": a.get("kind", "image"), "created": a.get("created", ""), "node": a.get("node", "")})
    out.reverse()
    return out


def resolve(canvas: Dict[str, Any], prompt: str) -> Tuple[str, List[str], List[str]]:
    """(prompt reescrito, ids das imagens citadas na ordem da 1ª citação, menções sem imagem). Sem `@` válido o prompt volta igual."""
    tb = table(canvas)
    by = {m["slug"]: m for m in tb}
    by_id = {m["id"]: m for m in tb}
    order: List[str] = []
    missing: List[str] = []
    visual: List[str] = []   # só imagens e quadros de vídeo recebem número de referência

    def sub(m: "re.Match[str]") -> str:
        tok = m.group(1)
        it = by.get(tok.lower()) or by.get(tok.lower().replace("_", "-")) or by_id.get(tok)   # «@foto_perfil» também vale para «foto-perfil»
        if not it:
            if tok not in missing:
                missing.append(tok)
            return m.group(0)
        aid = it["id"]
        if aid not in order:
            order.append(aid)
        if it["kind"] == "audio":
            return f"{tok} (audio reference)"
        if aid not in visual:
            visual.append(aid)
        n = visual.index(aid) + 1
        return f"{tok} (reference image {n}{', a frame of the video' if it['kind'] == 'video' else ''})"

    return MENTION_RE.sub(sub, prompt or ""), order[:MAX_REFS], missing


def plain(canvas: Dict[str, Any], prompt: str) -> str:
    """O prompt sem a marcação de referência: `@apelido` vira só `apelido`. Para modelos que não recebem as imagens (a marcação «reference image N» não aponta para nada)."""
    by = {m["slug"] for m in table(canvas)}
    return MENTION_RE.sub(lambda m: m.group(1) if m.group(1).lower() in by else m.group(0), prompt or "")


def ids_in(canvas: Dict[str, Any], prompt: str) -> List[str]:
    return resolve(canvas, prompt)[1]
