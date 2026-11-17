"""Estilo estruturado (v0.34): o Style Prompt e o Style Folder entendem **personagens, cenários, objetos** e o estilo geral — não só «um estilo».

* **Papéis:** o nome da pasta diz o que ela mostra («Personagens», «Cenários», «Objetos», «Estilo»…, em português ou inglês). Uma subpasta dentro dela é UMA entidade (`Personagens/Maria/frente.png`, `…/perfil.png`);
  sem subpastas, arquivos com o mesmo começo de nome viram a mesma entidade (`maria_frente.png`, `maria_perfil.png`). Um `.txt`/`.md` com o nome da entidade é a descrição dela.
* **Texto no formato fixo** (o que a IA devolve, o que o Style Prompt pode escrever à mão e o que o OpenFlow monta sem IA): linhas `ESTILO GERAL: …`, `TRAÇOS COMUNS DOS PERSONAGENS: …`,
  `PERSONAGEM — Maria: …`, `CENÁRIO — Floresta: …`, `OBJETO — Espada: …`, `CONSISTÊNCIA: …`.
* **Relevância:** `Style.render(prompt)` põe o estilo geral e **só as entidades que o prompt cita** (as demais viram uma linha «Elenco disponível»), e `images_for(prompt)` escolhe as imagens de referência
  dessas entidades primeiro — um Style Folder com 30 personagens não despeja os 30 em cada geração.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

ROLE_WORDS = {
    "character": ("personagem", "personagens", "character", "characters", "pessoa", "pessoas", "protagonista", "elenco", "cast", "heroi", "heroína", "vilao", "retrato", "portrait", "people"),
    "scenery": ("cenario", "cenarios", "scenery", "scene", "scenes", "setting", "settings", "ambiente", "ambientes", "location", "locations", "local", "locais", "lugar", "lugares", "fundo", "fundos", "background", "backgrounds", "environment", "paisagem"),
    "object": ("objeto", "objetos", "object", "objects", "item", "itens", "items", "prop", "props", "produto", "produtos", "product", "products", "arma", "armas", "veiculo", "veiculos", "vehicle"),
    "style": ("estilo", "estilos", "style", "styles", "paleta", "palette", "luz", "iluminacao", "lighting", "textura", "texturas", "texture", "mood", "clima", "traco", "referencia", "referencias"),
}
ROLE_LABEL = {"character": "PERSONAGEM", "scenery": "CENÁRIO", "object": "OBJETO"}
ROLE_PT = {"character": "personagem", "scenery": "cenário", "object": "objeto", "style": "estilo"}
VIEW_WORDS = {"frente", "front", "perfil", "profile", "costas", "back", "lado", "side", "rosto", "face", "corpo", "body", "full", "close", "closeup", "pose", "poses", "ref", "reference", "referencia", "final", "v", "versao",
              "version", "sheet", "turnaround", "expressoes", "expressions", "angulo", "angle", "antes", "depois", "copy", "copia", "novo", "new", "edit", "edited", "img", "image", "foto", "photo"}
TEXT_EXT = {"txt", "md", "markdown", "text", "docx", "odt", "rtf"}
MAX_GENERAL = 1200
MAX_ENTITY = 600


def fold(s: Any) -> str:
    """Minúsculas e sem acentos (para comparar nomes e pastas)."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(ch)).lower()


def role_of_folder(path: List[str]) -> str:
    """O papel que o nome das pastas indica (a pasta mais interna que bate; vazio = sem papel)."""
    for name in reversed(path):
        words = set(re.findall(r"[a-z]+", fold(name)))
        for role, keys in ROLE_WORDS.items():
            if words & set(keys):
                return role
    return ""


def _clean_stem(stem: str) -> List[str]:
    return [w for w in re.split(r"[\s_\-.()]+", fold(stem)) if w]


def entity_key_of_file(filename: str) -> Tuple[str, str]:
    """(chave, nome de exibição) de um arquivo solto: `maria_frente_v2.png` → («maria», «Maria»). Sem palavras de vista/versão/número; vazio se só sobrou isso."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename)
    words = [w for w in _clean_stem(stem) if w not in VIEW_WORDS and not re.fullmatch(r"v?\d+", w)]
    if not words:
        return "", ""
    key = words[0] if len(words) == 1 else " ".join(words[:2])
    shown = " ".join(w.capitalize() for w in re.split(r"[\s_\-.()]+", stem) if w and fold(w) in set(key.split()))
    return key, shown or key.title()


def group_entities(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """De [{path (lista de pastas), name (arquivo), id, kind}] → entidades [{role, name, ids (imagens/vídeos), text_ids (descrições), folder}].
    Papel: o das pastas; entidade: a subpasta logo abaixo da pasta de papel, ou o nome do arquivo."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for f in files:
        path = list(f.get("path") or [])
        role = role_of_folder(path)
        # índice da pasta que deu o papel
        ridx = -1
        for i in range(len(path) - 1, -1, -1):
            if role and any(role_of_folder([path[i]]) == role for _ in (0,)):
                ridx = i
                break
        sub = path[ridx + 1] if (ridx >= 0 and len(path) > ridx + 1) else ""
        if sub:
            key, shown = fold(sub), sub.strip()
        else:
            key, shown = entity_key_of_file(f["name"])
        if not key:
            key, shown = "", ""
        if not role and not key:
            continue
        k = (role, key or "_geral")
        e = out.setdefault(k, {"role": role, "name": shown, "key": key, "ids": [], "text_ids": [], "folder": "/".join(path)})
        ext = f["name"].rsplit(".", 1)[-1].lower() if "." in f["name"] else ""
        if ext in TEXT_EXT:
            e["text_ids"].append(f["id"])
        elif f.get("kind") in ("image", "video"):
            e["ids"].append(f["id"])
    ents = [e for e in out.values() if e["ids"] or e["text_ids"]]
    # só as pastas de personagem/cenário/objeto geram entidades nomeadas; arquivos sem papel só viram entidade se tiverem descrição própria (um .txt) ou vários arquivos com o mesmo nome
    keep = []
    for e in ents:
        if e["role"] in ("character", "scenery", "object") and e["name"]:
            keep.append(e)
        elif not e["role"] and e["name"] and e["text_ids"] and e["ids"]:
            e["role"] = "object"
            keep.append(e)
    return keep


# --------------------------------------------------------------------------- formato fixo
_HEAD = re.compile(r"^\s*(ESTILO GERAL|ESTILO|TRAÇOS COMUNS(?: DOS PERSONAGENS)?|TRACOS COMUNS(?: DOS PERSONAGENS)?|CONSISTÊNCIA|CONSISTENCIA|NOTAS|PERSONAGEM|CENÁRIO|CENARIO|OBJETO|CHARACTER|SCENERY|SETTING|OBJECT|STYLE)"
                   r"(?:\s*[—–-]\s*([^:\n]{1,60}?))?\s*:\s*(.*)$", re.I)
_KIND = {"personagem": "character", "character": "character", "cenario": "scenery", "cenário": "scenery", "scenery": "scenery", "setting": "scenery", "objeto": "object", "object": "object"}


def parse(text: str) -> Dict[str, Any]:
    """O texto no formato fixo → {general, common, consistency, notes, entities: [{kind, name, desc}], rest}. Linhas sem cabeçalho continuam o item anterior; texto sem nenhum cabeçalho vira `general`."""
    general: List[str] = []
    common: List[str] = []
    cons: List[str] = []
    notes: List[str] = []
    ents: List[Dict[str, Any]] = []
    cur: Optional[List[str]] = None
    started = False
    for line in (text or "").splitlines():
        m = _HEAD.match(line)
        if m:
            started = True
            head, name, body = fold(m.group(1)), (m.group(2) or "").strip(), m.group(3).strip()
            if head in _KIND and not name and body:   # «Personagem: Ana — ruiva» e «Personagem: Ana: ruiva»
                mm = re.match(r"^(.{1,60}?)\s+[—–-]\s+(.*)$", body) or re.match(r"^([^:]{1,60}):\s*(.*)$", body)
                if mm:
                    name, body = mm.group(1).strip(), mm.group(2).strip()
            if head in _KIND and name:
                e = {"kind": _KIND[head], "name": name, "desc": [body] if body else []}
                ents.append(e)
                cur = e["desc"]
            elif head.startswith(("estilo", "style")):
                cur = general
                if body:
                    general.append(body)
            elif head.startswith(("tracos", "traços")):
                cur = common
                if body:
                    common.append(body)
            elif head.startswith(("consist",)):
                cur = cons
                if body:
                    cons.append(body)
            elif head.startswith("notas"):
                cur = notes
                if body:
                    notes.append(body)
            else:   # «PERSONAGEM: …» sem nome: vira nota geral
                cur = general
                if body:
                    general.append(body)
        elif line.strip():
            (cur if cur is not None else general).append(line.strip())
        elif not started:
            continue
    j = lambda xs: " ".join(x for x in xs if x).strip()  # noqa: E731
    return {"general": j(general), "common": j(common), "consistency": j(cons), "notes": j(notes), "entities": [{"kind": e["kind"], "name": e["name"], "desc": j(e["desc"])} for e in ents]}


def serialize(general: str, common: str, entities: List[Dict[str, Any]], consistency: str = "", notes: str = "") -> str:
    lines = []
    if general:
        lines.append("ESTILO GERAL: " + general[:MAX_GENERAL])
    if common:
        lines.append("TRAÇOS COMUNS DOS PERSONAGENS: " + common[:MAX_GENERAL])
    if notes:
        lines.append("NOTAS: " + notes[:MAX_GENERAL])
    for e in entities:
        lines.append(f"{ROLE_LABEL.get(e['kind'], 'OBJETO')} — {e['name']}: " + (e.get("desc") or "(sem descrição)")[:MAX_ENTITY])
    if consistency:
        lines.append("CONSISTÊNCIA: " + consistency[:MAX_GENERAL])
    return "\n".join(lines)


def from_prompt_text(text: str) -> Dict[str, Any]:
    """Um Style Prompt escrito à mão: tira as linhas repetidas e espaços sobrando e reconhece `Personagem: Maria — …` (e as outras seções) quando existirem."""
    seen, lines = set(), []
    for ln in (text or "").splitlines():
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        key = fold(ln)
        if ln and key not in seen:
            seen.add(key)
            lines.append(ln)
    return parse("\n".join(lines))


# --------------------------------------------------------------------------- uso no prompt
def mentions(prompt: str, name: str) -> bool:
    """O prompt cita a entidade? (nome inteiro, sem acentos nem maiúsculas; um nome composto vale se o 1º nome aparece sozinho)."""
    p = " " + re.sub(r"[^\w]+", " ", fold(prompt)) + " "
    n = re.sub(r"[^\w]+", " ", fold(name)).strip()
    if not n:
        return False
    if f" {n} " in p:
        return True
    first = n.split()[0]
    return len(first) >= 3 and f" {first} " in p


def render(parsed: Dict[str, Any], prompt: str = "", max_chars: int = 1800) -> str:
    """O estilo para um prompt: geral + traços comuns + entidades citadas (ou todas, se são poucas) + consistência. Sem citações, as entidades viram uma linha de elenco."""
    ents = parsed.get("entities", [])
    cited = [e for e in ents if mentions(prompt, e["name"])]
    if not prompt.strip() or len(ents) <= 3:
        chosen, rest = ents, []
    else:
        chosen, rest = cited, [e for e in ents if e not in cited]
    parts = []
    if parsed.get("general"):
        parts.append(parsed["general"])
    if parsed.get("common") and (chosen or not ents):
        parts.append("Traços comuns dos personagens: " + parsed["common"])
    if parsed.get("notes"):
        parts.append(parsed["notes"])
    for e in chosen:
        parts.append(f"{ROLE_PT.get(e['kind'], 'objeto').capitalize()} {e['name']}: {e['desc']}".strip() if e.get("desc") else f"{ROLE_PT.get(e['kind'], 'objeto').capitalize()} {e['name']}")
    if rest:
        parts.append("Elenco do projeto (não use se o pedido não citar): " + ", ".join(e["name"] for e in rest[:30]))
    if parsed.get("consistency") and (chosen or not ents):
        parts.append("Consistência: " + parsed["consistency"])
    text = " ".join(x.strip() for x in parts if x and x.strip())
    return text[:max_chars]


def _position(prompt: str, name: str) -> int:
    p = " " + re.sub(r"[^\w]+", " ", fold(prompt)) + " "
    n = re.sub(r"[^\w]+", " ", fold(name)).strip()
    for cand in (n, n.split()[0] if n else ""):
        i = p.find(f" {cand} ") if cand else -1
        if i >= 0:
            return i
    return 10 ** 9


def pick_images(entities: List[Dict[str, Any]], prompt: str, general_ids: List[str], limit: int) -> List[str]:
    """Quais arquivos de imagem mandar como referência: primeiro os das entidades que o prompt cita, depois os de estilo geral; sem citação, uma imagem por entidade e depois as gerais."""
    cited = [e for e in entities if mentions(prompt, e["name"])]
    cited.sort(key=lambda e: _position(prompt, e["name"]))   # na ordem em que o prompt os cita
    order: List[str] = []
    if cited:   # uma imagem de cada citada, depois a segunda de cada…: com o limite curto, ninguém fica de fora
        for rnd in range(2):
            for e in cited:
                order += e["ids"][rnd:rnd + 1]
    else:
        for e in entities:
            order += e["ids"][:1]
    order += general_ids
    seen, out = set(), []
    for i in order:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out[:limit]


# --------------------------------------------------------------------------- system prompts internos (v0.73)
# Texto que o OpenFlow entrega à IA por conta própria — o usuário não o vê nem o edita. Os três juntos fazem o estilo ser aplicado com precisão em todo o projeto:
# FOLDER_SYSTEM descreve as pastas de referência (Style Folder), PROMPT_SYSTEM organiza o texto livre do Style Prompt e APPLY_RULES diz às etapas de texto (Texto IA, Refinar, Letra…) COMO usar o estilo.
FOLDER_SYSTEM = (
    "Você é o diretor de arte e de continuidade de um projeto criativo. Escreva o guia de estilo e as fichas de personagens, cenários e objetos a partir do que receber: as entidades encontradas (com o papel de cada "
    "uma), as notas do usuário, a descrição dos arquivos e imagens legendadas com o nome de quem aparece nelas. O guia será anexado a CADA prompt de geração do projeto, então precisa ser exato, concreto e curto. "
    "Responda SOMENTE neste formato, uma linha por item (sem markdown, sem listas, sem comentários, sem linhas vazias):\n"
    "ESTILO GERAL: 2 a 4 frases sobre o que vale para TODA imagem do projeto: técnica/traço/textura, paleta (cores concretas: «verde-musgo», «laranja queimado»), iluminação, composição e câmera, clima. "
    "Nada de personagens específicos nem de enredo aqui.\n"
    "TRAÇOS COMUNS DOS PERSONAGENS: o que TODOS os personagens têm em comum (proporções, figurino, traço do desenho, idade aparente…). Omita a linha se há menos de dois personagens.\n"
    "PERSONAGEM — <Nome>: só traços FIXOS e visuais, dos mais reconhecíveis aos menores: idade aparente, corpo/altura, rosto, cabelo (cor, corte), olhos, pele, roupas (peças e cores), acessórios, marcas únicas, postura típica.\n"
    "CENÁRIO — <Nome>: tipo de lugar, elementos principais, materiais, hora do dia, luz, clima e cores.\n"
    "OBJETO — <Nome>: forma, tamanho, material, cor, acabamento e detalhes que o identificam.\n"
    "CONSISTÊNCIA: 1 a 2 frases com o que NUNCA deve mudar entre uma imagem e outra (cores de roupa, cicatriz, estilo de traço…).\n"
    "REGRAS DE PRECISÃO: (1) descreva só o que VÊ nas imagens ou o que as notas dizem; na dúvida, omita — nunca invente. (2) Use exatamente os nomes das entidades encontradas, uma linha por entidade, sem criar outras. "
    "(3) Nas fichas, nada de ação, emoção do momento, roupa de uma cena só ou enredo: só o que se repete em todas as imagens daquela entidade (se as imagens divergem, vale o que se repete). "
    "(4) Não repita o estilo geral dentro das fichas. (5) Prefira palavras que um modelo de imagem entende (cor, material, forma, número) a adjetivos vagos como «bonito» ou «interessante». "
    "(6) Se uma nota do usuário contradiz as imagens, a nota vence. (7) Não cite nomes de arquivos nem de pastas. (8) Escreva no idioma predominante dos textos (padrão: português)."
)
PROMPT_SYSTEM = (
    "Você organiza o texto de um Style Prompt — escrito à mão pelo usuário — no guia de estilo estruturado que o OpenFlow anexa a cada prompt de geração do projeto. Reescreva SÓ o que o texto diz, no formato abaixo, "
    "uma linha por item (sem markdown, sem listas, sem comentários, sem linhas vazias):\n"
    "ESTILO GERAL: o que vale para toda imagem/vídeo/som do projeto (técnica, paleta, luz, composição, clima, época, tom).\n"
    "TRAÇOS COMUNS DOS PERSONAGENS: só se o texto dá traços compartilhados por vários personagens.\n"
    "PERSONAGEM — <Nome>: a ficha de um personagem que o texto descreve.\n"
    "CENÁRIO — <Nome>: a ficha de um lugar que o texto descreve.\n"
    "OBJETO — <Nome>: a ficha de um objeto que o texto descreve.\n"
    "CONSISTÊNCIA: o que o texto diz que NUNCA muda (ou «sempre», «obrigatório», «jamais»).\n"
    "REGRAS: (1) NÃO invente: use apenas informações do texto, com as mesmas palavras e termos técnicos; não acrescente cores, marcas ou detalhes. (2) Mantenha nomes próprios, @menções e números exatamente como estão. "
    "(3) Uma entidade só existe se o texto lhe dá nome E características; não crie entidades. (4) Traços que valem para tudo vão em ESTILO GERAL, os de uma entidade vão na ficha dela, e não os repita nos dois. "
    "(5) Proibições do texto («sem neon», «nunca em preto e branco») entram em CONSISTÊNCIA, com as mesmas palavras. (6) Omita as linhas sem conteúdo. "
    "(7) Se o texto já é curto e claro, devolva-o inteiro em ESTILO GERAL. (8) Mantenha o idioma do texto."
)
APPLY_RULES = (
    "REGRAS DE USO DO ESTILO DO PROJETO: (1) o estilo orienta o tom, o vocabulário e a linguagem visual; ele NUNCA muda o assunto nem a instrução do usuário — se o pedido e o estilo se contradizem, o pedido vence. "
    "(2) Use as fichas de personagem, cenário e objeto só dos que o texto cita, com os nomes exatamente como estão no estilo. (3) O que está em «Consistência» é regra fixa: não contradiga. "
    "(4) Não copie o estilo literalmente nem o mencione na resposta."
)
APPLY_RULES_EN = (
    "RULES FOR USING THE PROJECT STYLE: (1) the style guides tone, vocabulary and visual language; it NEVER changes the subject or the user's instruction — if the request and the style contradict each other, the request wins. "
    "(2) Use the character, scenery and object sheets only for the ones the text mentions, with the names exactly as in the style. (3) What is under «Consistency» is a fixed rule: do not contradict it. "
    "(4) Do not copy the style verbatim or mention it in the answer."
)
MEDIA_STYLE_LABEL = "Style guide (the look of the whole result, not its subject or action): "


def apply_block(style_text: str, lang: str = "pt") -> str:
    """O bloco que vai ao `system` de uma etapa de texto: as regras de uso do estilo + o estilo do projeto (vazio se não há estilo)."""
    if not (style_text or "").strip():
        return ""
    return ("\n\n" + APPLY_RULES_EN + "\nProject style: " if lang == "en" else "\n\n" + APPLY_RULES + "\nEstilo do projeto: ") + style_text.strip()


def media_style(style_text: str) -> str:
    """O trecho de estilo que fecha um prompt de imagem, vídeo ou música: curto (os modelos de imagem leem poucos tokens) e diz que ele descreve o visual, não o assunto."""
    return ("\n\n" + MEDIA_STYLE_LABEL + style_text.strip()) if (style_text or "").strip() else ""


def needs_structuring(raw: str) -> bool:
    """O Style Prompt vale ser organizado pela IA? Só texto corrido e longo, sem os cabeçalhos do formato fixo (um estilo curto como «aquarela, cores suaves» já está bom, e um texto já estruturado também)."""
    t = (raw or "").strip()
    if len(t) < 140:
        return False
    return not any(_HEAD.match(line) for line in t.splitlines())


def strip_preamble(text: str) -> str:
    """A resposta da IA a partir da primeira linha do formato fixo («ESTILO GERAL: …», «PERSONAGEM — …»); conversa antes dela («Claro! Aqui está…») e blocos ``` saem. Sem nenhuma linha do formato, devolve ""
    (a resposta não serve — vale o texto original do usuário)."""
    lines = [ln for ln in (text or "").replace("```", "").splitlines()]
    for i, ln in enumerate(lines):
        if _HEAD.match(ln):
            return "\n".join(lines[i:]).strip()
    return ""
