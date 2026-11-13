"""Chamadas estruturadas (JSON) a um provedor, com reparo e novas tentativas."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..providers.base import Provider, ProviderError


def salvage_json(raw: str) -> Any:
    """Último recurso para uma resposta CORTADA: descarta o pedaço final incompleto e fecha strings/listas/objetos abertos. Só para agentes cujo resultado
    parcial é aceitável (cada um tem valores padrão para o que faltar)."""
    from ..util import strip_reasoning

    text = strip_reasoning(str(raw or "")).strip()
    if "{" not in text and "{" in str(raw or ""):
        text = re.sub(r"</?think[^>]*>", "", str(raw), flags=re.I).strip()
    fence = re.search(r"```(?:json)?\s*(.*)", text, re.S | re.I)
    if fence and "{" in fence.group(1):
        text = fence.group(1).replace("```", "").strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("nenhum objeto JSON na resposta")
    text = text[start:]
    for _ in range(40):  # tira o último item incompleto até o resto fechar num JSON válido
        stack, in_str, esc = [], False, False
        for ch in text:
            if in_str:
                esc = (not esc) if ch == "\\" else False
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        cand = text + ('"' if in_str else "")
        cand = re.sub(r"[,:\s]+$", "", cand) if not in_str else cand
        cand = re.sub(r",\s*$", "", cand) + "".join(reversed(stack))
        for variant in (cand, re.sub(r",\s*([}\]])", r"\1", cand), re.sub(r'"[^"]*"\s*:\s*([}\]])', r"\1", cand)):
            try:
                obj = json.loads(variant)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        cut = max(text.rfind(","), text.rfind("{"), text.rfind("["))
        if cut <= 0:
            break
        text = text[:cut]
    raise ValueError("não consegui recuperar a resposta cortada")


def extract_json(raw: str, lenient: bool = False) -> Any:
    """Extrai o primeiro objeto JSON de um texto. Tolera cercas ```json, texto em volta, vírgulas sobrando e o «raciocínio» `<think>…</think>` que modelos
    como Qwen3/DeepSeek R1 escrevem antes da resposta (as chaves dentro dele não viram o objeto). Um trecho entre chaves que não é JSON (ex.: «{exemplo}» numa frase)
    é pulado; uma resposta cortada no meio levanta ValueError (o chamador pede de novo)."""
    if raw is None:
        raise ValueError("resposta vazia")
    from ..util import strip_reasoning

    text = strip_reasoning(str(raw)).strip()
    if lenient and "{" not in text and "{" in str(raw):  # <think> que nunca fechou (tokens acabaram) ou resposta escrita dentro do raciocínio: procura o JSON ali
        text = re.sub(r"</?think[^>]*>", "", str(raw), flags=re.I).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fence and "{" in fence.group(1):
        text = fence.group(1).strip()
    pos, last_err = 0, ""
    while True:
        start = text.find("{", pos)
        if start < 0:
            raise ValueError(last_err or "nenhum objeto JSON na resposta")
        depth, in_str, esc, end = 0, False, False, -1
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            raise ValueError("objeto JSON incompleto (resposta cortada?)")
        chunk = text[start:end + 1]
        try:
            return json.loads(chunk)
        except json.JSONDecodeError as exc:
            try:
                return json.loads(re.sub(r",\s*([}\]])", r"\1", chunk))
            except json.JSONDecodeError:
                last_err = f"JSON inválido: {exc.msg}"
                pos = end + 1  # tenta o próximo objeto depois deste trecho


def build_user_message(instruction: str, payload: Dict[str, Any], images: Optional[List[dict]], vision: bool):
    text = f"{instruction}\n\nINPUT_JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    if images and vision:
        parts: List[dict] = [{"type": "text", "text": text}]
        for img in images:
            parts.append({"type": "image", "media_type": img["media_type"], "data": img["data"]})
        return parts
    return text


def call_json(
    provider: Provider,
    system: str,
    instruction: str,
    payload: Dict[str, Any],
    *,
    images: Optional[List[dict]] = None,
    temperature: float = 0.8,
    max_tokens: int = 4096,
    attempts: int = 2,
    salvage: bool = False,
    cancelled: Optional[Callable[[], bool]] = None,
) -> Tuple[Dict[str, Any], str]:
    """Chama o provedor esperando JSON. Devolve (objeto, texto_bruto)."""
    messages: List[dict] = [
        {"role": "user", "content": build_user_message(instruction, payload, images, provider.vision)}
    ]
    last_err = "desconhecido"
    raw = ""
    json_mode = True
    want = re.search(r"Output JSON:\s*(\{.*\})", instruction, re.S)  # o formato esperado, repetido na nova tentativa
    for attempt in range(attempts):
        if cancelled and cancelled():
            raise ProviderError("cancelado")
        raw = provider.chat(messages, system=system, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
        if not str(raw or "").strip():
            # resposta VAZIA: o mais comum é um modelo que «pensa» e gasta todo o limite de tokens no raciocínio, ou um servidor que devolve vazio com o modo JSON ligado. Repete a MESMA pergunta com
            # mais espaço e sem forçar o modo JSON — mandar de volta uma mensagem vazia da IA (como nas respostas inválidas) só confunde o modelo e alguns provedores recusam.
            last_err = "resposta vazia"
            max_tokens = min(max_tokens * 2, 16384)
            json_mode = False
            continue
        try:
            obj = extract_json(str(raw), lenient=attempt == attempts - 1)  # na última tentativa aceita o JSON escrito dentro do raciocínio
            if not isinstance(obj, dict):
                raise ValueError("o JSON não é um objeto")
            return obj, str(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            last_err = str(exc)
            if "incompleto" in last_err or "cortada" in last_err:
                max_tokens = min(max_tokens * 2, 16384)  # resposta cortada: da próxima vez cabe mais
                if salvage and attempt == attempts - 1:
                    try:
                        return salvage_json(str(raw)), str(raw)
                    except ValueError:
                        pass
            messages.append({"role": "assistant", "content": str(raw)[:6000]})
            messages.append({
                "role": "user",
                "content": f"Your reply was not valid JSON ({last_err}). Reply again with ONLY the corrected, complete JSON object: no reasoning, no commentary, and keep it short." + (f" Expected format: {want.group(1)}" if want else ""),
            })
            temperature = max(0.2, temperature - 0.3)
    snippet = " ".join(str(raw or "").split())[:90]
    raise ValueError(f"JSON inválido após {attempts} tentativas: {last_err}" + (f" — a IA respondeu: «{snippet}»" if snippet else " — a IA respondeu vazio"))
