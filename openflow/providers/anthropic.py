"""Provedor nativo da API Messages da Anthropic (Claude)."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List

from . import http, images, limits, thinking as think
from .base import Provider, ProviderError, content_images, content_text, split_system

API_VERSION = "2023-06-01"
#: janela de 1M tokens (modelos Claude que a oferecem): pedida só quando o Chat configura mais de 200K; se o modelo não a aceita, a requisição é refeita sem o cabeçalho
LONG_CONTEXT_BETA = "context-1m-2025-08-07"


class AnthropicProvider(Provider):
    vision = True

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.base = (cfg.get("base_url") or "https://api.anthropic.com").rstrip("/")
        self.key = cfg.get("api_key") or ""
        self.label = cfg.get("label", "Anthropic")
        self.long_context = False   # o Chat liga quando a janela configurada passa de 200K tokens

    def _headers(self) -> Dict[str, str]:
        if not self.key:
            raise ProviderError("Informe a chave de API da Anthropic em Configuração → Provedores.")
        h = {"x-api-key": self.key, "anthropic-version": API_VERSION}
        if self.long_context:
            h["anthropic-beta"] = LONG_CONTEXT_BETA
        return h

    def _drop_beta(self, err: ProviderError) -> bool:
        """O modelo não aceita a janela de 1M (cabeçalho beta desconhecido): refaz sem ele — a janela volta ao normal do modelo."""
        if self.long_context and err.status in (400, 403) and ("beta" in str(err).lower() or "context-1m" in str(err).lower()):
            self.long_context = False
            self.notes.append("Este modelo não aceita a janela de 1M tokens: usei a janela normal dele.")
            return True
        return False

    def _convert(self, messages: List[dict], system: str):
        sys_text, rest = split_system(messages, system)
        out: List[dict] = []
        for m in rest:
            role = "assistant" if m["role"] == "assistant" else "user"
            content = m.get("content")
            blocks: List[dict] = []
            imgs = content_images(content)
            if imgs and self.vision:
                for img in imgs:
                    ok = images.normalize(img)  # o tipo vem dos bytes (a API recusa quando o tipo declarado não bate com a imagem)
                    if not ok:
                        continue
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": ok["media_type"], "data": ok["data"]}})
            txt = content_text(content)
            if txt.strip():
                blocks.append({"type": "text", "text": txt})
            if not blocks:
                continue
            if out and out[-1]["role"] == role:  # a API exige alternância de papéis
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": blocks})
        if not out or out[0]["role"] != "user":
            out.insert(0, {"role": "user", "content": [{"type": "text", "text": "(início)"}]})
        return sys_text, out

    def _body(self, messages, system, temperature, max_tokens, stream) -> dict:
        if not self.model:
            raise ProviderError("Nenhum modelo selecionado. Escolha um modelo em Configuração → Provedores.")
        sys_text, msgs = self._convert(messages, system)
        max_tokens = limits.cap("anthropic", self.model, int(max_tokens))   # o teto que este modelo já mostrou aceitar
        body: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": int(max_tokens),
            "messages": msgs,
            "temperature": max(0.0, min(float(temperature), 1.0)),  # a API da Anthropic só aceita 0 a 1 (a interface deixa até 1,5)
            "stream": stream,
        }
        if sys_text:
            body["system"] = sys_text
        level = think.normalize(self.thinking)
        if level != "off" and think.support("anthropic", self.model)["kind"] == "budget":
            budget = think.budget_for(level, int(max_tokens))
            if budget:
                # pensamento estendido: o orçamento vai além do tamanho da resposta; a API exige temperatura 1 (então ela não é enviada)
                body["thinking"] = {"type": "enabled", "budget_tokens": budget}
                body["max_tokens"] = int(max_tokens) + budget
                body.pop("temperature", None)
                self._answer_tokens = int(max_tokens)
        return body

    def _drop_thinking(self, body: dict, err: ProviderError) -> bool:
        """O modelo recusou o pensamento estendido (versão sem o recurso ou com outro formato): refaz a pedido sem ele e avisa."""
        if err.status == 400 and "thinking" in body and ("thinking" in str(err).lower() or "budget" in str(err).lower()):
            body.pop("thinking")
            body["max_tokens"] = getattr(self, "_answer_tokens", body["max_tokens"])
            self.notes.append("Este modelo não aceitou o modo de pensamento escolhido; respondi sem ele.")
            return True
        return False

    def _shrink_tokens(self, body: dict, err: ProviderError) -> bool:
        """O modelo aceita menos tokens de resposta do que foi pedido: usa o teto dele (lido do erro) e lembra para as próximas."""
        if err.status != 400:
            return False
        new = limits.fit_from_error(str(err), int(body.get("max_tokens") or 0))
        if not new or new >= int(body["max_tokens"]):
            return False
        thinking = body.get("thinking") or {}
        if thinking.get("budget_tokens"):   # o orçamento de pensamento tem de ficar abaixo do total
            thinking["budget_tokens"] = max(1024, min(int(thinking["budget_tokens"]), new - 1024)) if new > 2048 else 0
            if not thinking["budget_tokens"]:
                body.pop("thinking")
        body["max_tokens"] = new
        self._answer_tokens = min(getattr(self, "_answer_tokens", new), new)
        limits.learn("anthropic", self.model, new)
        self.notes.append(f"Este modelo aceita no máximo {new:,} tokens por resposta: o limite foi ajustado para esse valor.".replace(",", "."))
        return True

    def _chat(self, messages, system, temperature, max_tokens, json_mode) -> str:
        body = self._body(messages, system, temperature, max_tokens, False)
        for _ in range(4):
            try:
                data = http.post_json(self.base + "/v1/messages", body, self._headers(), timeout=300, retries=2)
                break
            except ProviderError as err:
                if self._drop_thinking(body, err) or self._shrink_tokens(body, err) or self._drop_beta(err):
                    continue
                if err.status == 400 and "temperature" in str(err).lower() and "temperature" in body:
                    body.pop("temperature")
                    continue
                raise
        else:  # pragma: no cover
            raise ProviderError("A API rejeitou os parâmetros da requisição.")
        self.last_stop = "length" if data.get("stop_reason") == "max_tokens" else ("stop" if data.get("stop_reason") else "")
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return "".join(parts).strip()

    def _stream(self, messages, system, temperature, max_tokens) -> Iterator[str]:
        body = self._body(messages, system, temperature, max_tokens, True)
        for _ in range(4):
            started = False
            try:
                for evt, data in http.stream_sse(self.base + "/v1/messages", body, self._headers(), timeout=300, retries=2):
                    started = True
                    if evt == "error":
                        try:
                            err = json.loads(data).get("error", {})
                            msg = err.get("message") if isinstance(err, dict) else str(err)
                        except (json.JSONDecodeError, AttributeError):
                            msg = data
                        raise ProviderError(str(msg or data)[:300])
                    if evt == "message_delta":   # o motivo de parada chega aqui («max_tokens» = resposta cortada pelo limite)
                        try:
                            reason = json.loads(data).get("delta", {}).get("stop_reason")
                        except (json.JSONDecodeError, AttributeError):
                            reason = None
                        if reason:
                            self.last_stop = "length" if reason == "max_tokens" else "stop"
                        continue
                    if evt != "content_block_delta":
                        continue
                    try:
                        delta = json.loads(data).get("delta", {})
                    except json.JSONDecodeError:
                        continue
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield delta["text"]
                return
            except ProviderError as err:
                if not started and (self._drop_thinking(body, err) or self._shrink_tokens(body, err) or self._drop_beta(err)):
                    continue
                if not started and err.status == 400 and "temperature" in str(err).lower() and "temperature" in body:
                    body.pop("temperature")
                    continue
                raise

    def list_models(self) -> List[str]:
        data = http.get_json(self.base + "/v1/models?limit=100", self._headers(), timeout=20)
        return [m["id"] for m in data.get("data", []) if m.get("id")]
