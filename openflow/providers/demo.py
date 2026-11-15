"""Provedor Demo: funciona 100% offline, sem IA, para testar o fluxo e a interface.

Os nós de mídia têm geradores procedurais próprios (`canvas/procedural.py`); aqui só ficam as chamadas de texto.
"""
from __future__ import annotations

from typing import Iterator, List

from .base import Provider, content_text, split_system


class DemoProvider(Provider):
    id = "demo"
    label = "Demo (offline)"
    vision = False

    def __init__(self, cfg):
        super().__init__(cfg)
        self.model = "demo"

    def _chat(self, messages, system, temperature, max_tokens, json_mode) -> str:
        _sys, rest = split_system(messages, system)
        last_user = ""
        for msg in reversed(rest):
            if msg["role"] == "user":
                last_user = content_text(msg.get("content"))
                break
        return ("(Demo) " + last_user.strip())[:600] if last_user.strip() else "(Demo)"

    def _stream(self, messages, system, temperature, max_tokens) -> Iterator[str]:
        text = self._chat(messages, system, temperature, max_tokens, False)
        for i in range(0, len(text), 6):
            yield text[i:i + 6]

    def list_models(self) -> List[str]:
        return ["demo"]
