"""Provedor para APIs compatíveis com a OpenAI (Chat Completions).

Cobre OpenAI, xAI (Grok), Google Gemini (endpoint compatível), OpenRouter,
Hugging Face Inference, Ollama, LM Studio, llama.cpp server, vLLM e outros.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Dict, Iterator, List

from . import http, images, limits, thinking as think
from .base import Provider, ProviderError, content_images, content_text, split_system


def normalize_base(base: str, add_v1: bool = False) -> str:
    """Endereço da API como o usuário costuma digitar: sem esquema ("localhost:11434" → http://…) e, nos servidores locais, sem o /v1
    (o Ollama e o llama.cpp respondem em /v1: "http://localhost:11434" vira "http://localhost:11434/v1")."""
    b = (base or "").strip().rstrip("/")
    if not b:
        return ""
    if "://" not in b:
        b = "http://" + b
    if add_v1 and urllib.parse.urlsplit(b).path in ("", "/"):
        b += "/v1"
    return b


_IMAGE_ERR = re.compile(r"image|base64|'url'|\"url\"|vision|multimodal|modalit", re.I)


def _text(content: Any) -> str:
    """O texto da resposta: alguns servidores devolvem uma lista de partes em vez de uma string."""
    if isinstance(content, list):
        return "".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content)
    return str(content or "")


def _stop(reason: Any) -> str:
    """O motivo de parada da API → «length» (cortada pelo limite de tokens), «stop» (terminou) ou «»."""
    r = str(reason or "").lower()
    if r in ("length", "max_tokens", "max_output_tokens"):
        return "length"
    return "stop" if r else ""


class OpenAICompatProvider(Provider):
    #: provedores em que o usuário digita o endereço do servidor (e costuma esquecer o /v1)
    LOCAL_IDS = ("ollama", "llamacpp", "custom", "lmstudio")
    #: servidores locais só aceitam PNG/JPEG de forma confiável: o resto é convertido (ffmpeg) ou fica de fora
    STRICT_IMAGE_IDS = ("ollama", "llamacpp", "custom", "lmstudio")

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.base = normalize_base(cfg.get("base_url") or "", add_v1=cfg.get("id") in self.LOCAL_IDS)
        self.key = cfg.get("api_key") or ""
        self.use_json_mode = bool(cfg.get("json"))
        self.allowed_images = images.STRICT_TYPES if cfg.get("id") in self.STRICT_IMAGE_IDS else None
        self.images_dropped = 0  # imagens que não foram enviadas (formato não aceito ou recusadas pelo servidor): o Runner avisa
        self.label = cfg.get("label", "OpenAI-compatível")

    # ------------------------------------------------------------ helpers
    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        return h

    def _convert(self, messages: List[dict], system: str) -> List[dict]:
        sys_text, rest = split_system(messages, system)
        out: List[dict] = []
        if sys_text:
            out.append({"role": "system", "content": sys_text})
        for m in rest:
            content = m.get("content")
            imgs = content_images(content)
            if imgs and self.vision:
                txt = content_text(content)
                img_parts: List[dict] = []
                for img in imgs:
                    ok = images.normalize(img, self.allowed_images)
                    if not ok:
                        self.images_dropped += 1
                        continue
                    img_parts.append({"type": "image_url", "image_url": {"url": f"data:{ok['media_type']};base64,{ok['data']}"}})
                if len(img_parts) < len(imgs):
                    txt += f"\n[{len(imgs) - len(img_parts)} imagem(ns) anexada(s) não pôde(ram) ser enviada(s) a este provedor]"
                if not img_parts:
                    out.append({"role": m["role"], "content": txt})
                else:
                    out.append({"role": m["role"], "content": ([{"type": "text", "text": txt}] if txt else []) + img_parts})
            else:
                txt = content_text(content)
                if imgs and not self.vision:
                    txt += f"\n[{len(imgs)} imagem(ns) anexada(s) — este provedor está sem visão]"
                out.append({"role": m["role"], "content": txt})
        return out

    def _payload(self, messages, system, temperature, max_tokens, json_mode, stream) -> dict:
        if not self.model:
            raise ProviderError("Nenhum modelo selecionado. Escolha um modelo em Configuração → Provedores.")
        max_tokens = limits.cap(self.cfg.get("id", ""), self.model, int(max_tokens))   # o teto que este modelo já mostrou aceitar (sem outra ida e volta)
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": self._convert(messages, system),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if json_mode and self.use_json_mode:
            body["response_format"] = {"type": "json_object"}
        level = think.normalize(self.thinking)
        kind = think.support(self.cfg.get("id", ""), self.model)["kind"]
        if level != "off" and kind in ("effort", "reasoning"):
            body.update(think.body_extra(kind, level, int(max_tokens)))
            body["max_tokens"] = think.total_tokens(kind, level, int(max_tokens))  # a folga de raciocínio vai além do tamanho da resposta
            self._answer_tokens = int(max_tokens)
        return body

    def _adapt(self, body: dict, err: ProviderError) -> bool:
        """Ajusta parâmetros que o modelo rejeita (modelos de raciocínio, etc.). True = tentar de novo."""
        msg = str(err).lower()
        if err.status not in (400, 415, 422):
            return False
        if _IMAGE_ERR.search(msg) and self._strip_images(body):  # o servidor recusou as imagens (formato, modelo sem visão…): segue só com o texto
            return True
        if ("reasoning" in msg or "thinking" in msg) and ("reasoning_effort" in body or "reasoning" in body):  # o modelo não aceita o parâmetro de raciocínio
            body.pop("reasoning_effort", None)
            body.pop("reasoning", None)
            key = "max_tokens" if "max_tokens" in body else "max_completion_tokens"
            body[key] = getattr(self, "_answer_tokens", body.get(key))
            self.notes.append("Este modelo não aceitou o modo de pensamento escolhido; respondi sem ele.")
            return True
        if "max_completion_tokens" in msg and "max_tokens" in body:
            body["max_completion_tokens"] = body.pop("max_tokens")
            return True
        if self._shrink_tokens(body, err):   # pediu mais resposta do que o modelo aguenta: usa o teto dele (lido do erro) e lembra
            return True
        if "temperature" in msg and "temperature" in body:
            body.pop("temperature")
            return True
        if "response_format" in msg and "response_format" in body:
            body.pop("response_format")
            return True
        return False

    def _shrink_tokens(self, body: dict, err: ProviderError) -> bool:
        key = "max_tokens" if "max_tokens" in body else "max_completion_tokens" if "max_completion_tokens" in body else ""
        if not key:
            return False
        new = limits.fit_from_error(str(err), int(body[key]))
        if not new or new >= int(body[key]):
            return False
        body[key] = new
        self._answer_tokens = min(getattr(self, "_answer_tokens", new), new)
        limits.learn(self.cfg.get("id", ""), self.model, new)
        self.notes.append(f"Este modelo aceita no máximo {new:,} tokens por resposta: o limite foi ajustado para esse valor.".replace(",", "."))
        return True

    def _strip_images(self, body: dict) -> bool:
        """Troca as imagens das mensagens por uma nota de texto. True se havia imagens."""
        found = 0
        for m in body.get("messages", []):
            c = m.get("content")
            if isinstance(c, list):
                n = sum(1 for p in c if isinstance(p, dict) and p.get("type") == "image_url")
                if n:
                    found += n
                    txt = "\n".join(str(p.get("text", "")) for p in c if isinstance(p, dict) and p.get("type") == "text")
                    m["content"] = txt + f"\n[{n} imagem(ns) anexada(s) não pôde(ram) ser enviada(s): o provedor recusou o formato ou o modelo não tem visão]"
        self.images_dropped += found
        return found > 0

    def _url(self) -> str:
        if not self.base:
            raise ProviderError("Informe a URL base do provedor em Configuração → Provedores.")
        return self.base + "/chat/completions"

    # ------------------------------------------------------------ chat
    def _chat(self, messages, system, temperature, max_tokens, json_mode) -> str:
        body = self._payload(messages, system, temperature, max_tokens, json_mode, False)
        for _ in range(4):
            try:
                data = http.post_json(self._url(), body, self._headers(), timeout=300, retries=2)
                break
            except ProviderError as err:
                if not self._adapt(body, err):
                    raise
        else:  # pragma: no cover
            raise ProviderError("O provedor rejeitou os parâmetros da requisição.")
        try:
            choice = data["choices"][0]
            msg = choice["message"]
            self.last_stop = _stop(choice.get("finish_reason"))
            return _text(msg.get("content")).strip()
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"Resposta inesperada do provedor: {json.dumps(data)[:300]}") from None

    def _stream(self, messages, system, temperature, max_tokens) -> Iterator[str]:
        body = self._payload(messages, system, temperature, max_tokens, False, True)
        for _ in range(4):
            gen = http.stream_sse(self._url(), body, self._headers(), timeout=300, retries=2)
            try:
                first = True
                for _evt, data in gen:
                    if data == "[DONE]":
                        return
                    try:
                        obj = json.loads(data)
                        if isinstance(obj, dict) and obj.get("error"):  # erro no meio do streaming (limite, modelo caiu…)
                            err_obj = obj["error"]
                            raise ProviderError(str(err_obj.get("message") if isinstance(err_obj, dict) else err_obj)[:400] or "O provedor interrompeu a resposta.")
                        choice = (obj.get("choices") or [{}])[0]
                        delta = _text((choice.get("delta") or {}).get("content"))
                        if choice.get("finish_reason"):
                            self.last_stop = _stop(choice.get("finish_reason"))
                    except (json.JSONDecodeError, AttributeError, IndexError, TypeError):
                        continue
                    if delta:
                        first = False
                        yield delta
                return
            except ProviderError as err:
                if first and self._adapt(body, err):
                    continue
                raise
        raise ProviderError("O provedor rejeitou os parâmetros da requisição.")

    def list_models(self) -> List[str]:
        if not self.base:
            return []
        data = http.get_json(self.base + "/models", self._headers(), timeout=20)
        items = data.get("data", data.get("models", [])) if isinstance(data, dict) else data
        ids = []
        for it in items or []:
            mid = it.get("id") or it.get("name") if isinstance(it, dict) else str(it)
            if mid:
                ids.append(str(mid).replace("models/", "", 1))
        return sorted(set(ids))
