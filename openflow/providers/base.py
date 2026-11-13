"""Interface comum dos provedores de IA.

Mensagens internas: {"role": "system|user|assistant", "content": str | [partes]}
Partes: {"type": "text", "text": str} ou
        {"type": "image", "media_type": "image/png", "data": "<base64>"}
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

Message = Dict[str, Any]


class ProviderError(Exception):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def split_system(messages: List[Message], system: str = "") -> Tuple[str, List[Message]]:
    """Separa mensagens `system` do restante e as concatena ao `system` dado."""
    sys_parts = [system] if system else []
    rest: List[Message] = []
    for m in messages:
        if m.get("role") == "system":
            sys_parts.append(content_text(m.get("content")))
        else:
            rest.append(m)
    return "\n\n".join(p for p in sys_parts if p), rest


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    out = []
    for part in content or []:
        if isinstance(part, dict) and part.get("type") == "text":
            out.append(part.get("text", ""))
    return "\n".join(out)


def content_images(content: Any) -> List[dict]:
    if isinstance(content, str):
        return []
    return [p for p in (content or []) if isinstance(p, dict) and p.get("type") == "image"]


class Provider:
    """Provedor de chat. Subclasses implementam `_chat` e `_stream`."""

    id = "provider"
    label = "Provedor"
    vision = False
    #: tempo de pensamento pedido pelo Chat (off|slow|medium|high|xhigh|ultra); só vale onde `thinking.support()` diz que há suporte
    thinking = "off"

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.notes: List[str] = []  # avisos para a interface (ex.: o modelo recusou o modo de pensamento e a resposta veio sem ele)
        #: por que a última resposta parou: "length" (bateu no limite de tokens — o texto foi cortado), "stop" (terminou) ou "" (não sei). O Chat usa isto para continuar sozinho.
        self.last_stop = ""
        self.model = cfg.get("model", "")
        self.vision = bool(cfg.get("vision", self.vision))

    # API pública ---------------------------------------------------------
    def chat(
        self,
        messages: List[Message],
        system: str = "",
        temperature: float = 0.8,
        max_tokens: int = 1024,
        json_mode: bool = False,
        stream: bool = False,
    ) -> Union[str, Iterator[str]]:
        self.last_stop = ""
        if stream:
            return self._stream(messages, system, temperature, max_tokens)
        return self._chat(messages, system, temperature, max_tokens, json_mode)

    def list_models(self) -> List[str]:
        return []

    def test(self) -> str:
        reply = self.chat(
            [{"role": "user", "content": "Reply with the single word: OK"}], max_tokens=16, temperature=0
        )
        return str(reply).strip()[:80]

    # a implementar -------------------------------------------------------
    def _chat(self, messages, system, temperature, max_tokens, json_mode) -> str:  # pragma: no cover
        raise NotImplementedError

    def _stream(self, messages, system, temperature, max_tokens) -> Iterator[str]:  # pragma: no cover
        yield self._chat(messages, system, temperature, max_tokens, False)
