"""Provedores de nuvem do v0.8: Qwen (Alibaba Cloud Model Studio / DashScope), Krea e Bria.

Os três trabalham do mesmo jeito: enviam o pedido, recebem o número de uma tarefa e o OpenFlow consulta até ela terminar (`_Job`). Os formatos abaixo seguem a documentação pública de cada empresa
(Qwen: `X-DashScope-Async` + `GET /tasks/{id}`; Krea: `POST /generate/image/{provedor}/{modelo}` + `GET /jobs/{id}`; Bria: `POST /v2/image/generate` + `status_url`), mas **não foram
testados com uma chave real** — ao primeiro erro de parâmetro o provedor tenta de novo só com o essencial, e a mensagem do serviço aparece inteira no nó.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..providers import http
from ..providers.base import ProviderError
from . import media as M

Ref = M.Ref

QWEN_SIZES = ("1328*1328", "1664*928", "928*1664", "1472*1104", "1104*1472")          # os tamanhos que o Qwen-Image aceita
BRIA_ASPECTS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9")
WAN_SIZES = {"16:9": "1280*720", "9:16": "720*1280", "1:1": "960*960", "4:3": "1088*832", "3:4": "832*1088"}
_BAD_REQUEST = (400, 404, 422)


def _nearest_ratio(w: int, h: int, options: Sequence[str]) -> str:
    def val(r: str) -> float:
        a, b = r.split(":")
        return float(a) / float(b)

    return min(options, key=lambda r: abs(val(r) - w / max(1, h)))


def _nearest_size(w: int, h: int, options: Sequence[str], sep: str = "*") -> str:
    def ratio(s: str) -> float:
        a, b = s.split(sep)
        return float(a) / float(b)

    return min(options, key=lambda s: abs(ratio(s) - w / max(1, h)))


def _urls(value: Any, keys: Tuple[str, ...] = ("url", "image", "image_url", "video_url", "urls")) -> List[str]:
    """Todos os endereços http(s) de uma resposta (em qualquer profundidade), sem repetir, na ordem em que aparecem."""
    out: List[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            if v.startswith(("http://", "https://")) and v not in out:
                out.append(v)
        elif isinstance(v, list):
            for i in v:
                walk(i)
        elif isinstance(v, dict):
            for k, i in v.items():
                if k in keys or isinstance(i, (dict, list)):
                    walk(i)

    walk(value)
    return out


class _Job(M.MediaProvider):
    """Base das nuvens que respondem com uma tarefa a consultar."""

    TIMEOUT = 1800.0

    def _wait(self, fetch: Callable[[], Any], state: Callable[[Any], str], what: str) -> Any:
        """Consulta `fetch()` até `state(resposta)` ser «done» (devolve a resposta) ou «failed» (erro). Respeita o cancelamento e o tempo máximo."""
        deadline = time.time() + self.TIMEOUT
        while True:
            self.ctl.check()
            res = fetch()
            st = state(res)
            if st == "done":
                return res
            if st == "failed":
                raise ProviderError(f"{self.label}: {self._why(res)}")
            if time.time() > deadline:
                raise ProviderError(f"{self.label}: {what} demorou demais (mais de {int(self.TIMEOUT // 60)} minutos).")
            self.ctl.note(f"{self.label}: gerando…")
            self.ctl.sleep(self.poll(3.0))

    @staticmethod
    def _why(res: Any) -> str:
        """A mensagem de erro de uma resposta de tarefa (campo `message`/`error`/`detail`, no topo, em `output` ou em `result`)."""
        if isinstance(res, dict):
            for box in (res, res.get("output"), res.get("result")):
                if isinstance(box, dict):
                    for k in ("message", "error", "detail", "code"):
                        v = box.get(k)
                        if v:
                            return str(v.get("message", v) if isinstance(v, dict) else v)[:300]
        return "a geração não foi concluída."

    def _download(self, urls: Sequence[str], kind: str, limit: int = 8) -> List[M.Media]:
        if not urls:
            raise ProviderError(f"{self.label}: o serviço não devolveu arquivos.")
        out = []
        for u in list(urls)[:limit]:
            self.ctl.check()
            data, mime = http.get_bytes(u, timeout=600)
            out.append(M.expect_media(data, mime, kind, self.label))
        return out

    def test(self) -> str:
        self.need_key()
        return "chave informada (o serviço só é consultado ao gerar)"


# --------------------------------------------------------------------------- Qwen (Alibaba Cloud)


class QwenMedia(_Job):
    """Qwen-Image / Qwen-Image-Edit e os vídeos Wan do Model Studio (DashScope). O endereço padrão é o internacional; troque em Configuração → Mídia para o da China ou dos EUA."""

    id, label = "qwen", "Qwen (Alibaba Cloud)"
    caps = ("image", "video")
    supports_refs = True

    def max_refs(self, model: str = "") -> int:
        return 3

    def refs_need_edit(self, model: str = "") -> bool:
        return False   # com referências o OpenFlow usa o modelo de edição também no modo Gerar

    def _h(self, async_: bool = False) -> Dict[str, str]:
        self.need_key()
        return {**M._auth(self.key), **({"X-DashScope-Async": "enable"} if async_ else {})}

    def _task(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Envia a tarefa assíncrona e espera o fim; devolve `output` da consulta."""
        sent = M._retry(self.ctl, lambda: http.post_json(f"{self.base}/{path}", body, self._h(True), timeout=120))
        tid = ((sent or {}).get("output") or {}).get("task_id") if isinstance(sent, dict) else None
        if not tid:
            raise ProviderError(f"{self.label}: resposta inesperada ao criar a tarefa ({str(sent)[:160]}).")
        res = self._wait(lambda: http.get_json(f"{self.base}/tasks/{tid}", self._h(), timeout=60),
                         lambda r: {"SUCCEEDED": "done", "FAILED": "failed", "CANCELED": "failed", "UNKNOWN": "failed"}.get(str(((r or {}).get("output") or {}).get("task_status", "")).upper(), "wait"),
                         "a tarefa")
        return res.get("output") or {}

    def _drop_and_retry(self, send: Callable[[Dict[str, Any]], Any], params: Dict[str, Any], drop: Sequence[str]) -> Any:
        """Parâmetro que o modelo não conhece: tira os opcionais e repete uma vez (a mensagem do serviço continua visível se falhar de novo)."""
        try:
            return send(params)
        except ProviderError as exc:
            if exc.status in _BAD_REQUEST and any(k in params for k in drop):
                return send({k: v for k, v in params.items() if k not in drop})
            raise

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        model = self.model_for("image", model) or "qwen-image"
        edit = bool(refs) or "edit" in model.lower()
        if refs and "edit" not in model.lower():
            self.ctl.note("Qwen: com imagens de referência o OpenFlow usou o modelo qwen-image-edit-plus.")
            model = "qwen-image-edit-plus"
        out: List[M.Media] = []
        for i in range(max(1, count)):
            params: Dict[str, Any] = {k: v for k, v in (extra or {}).items() if isinstance(v, (str, int, float, bool))}
            if seed:
                params["seed"] = (seed + i) % 2147483647
            if negative:
                params["negative_prompt"] = negative
            if edit:
                parts: List[Dict[str, str]] = [{"image": M.data_uri(d, m)} for d, m in list(refs)[:self.max_refs(model)]] + [{"text": prompt}]
                body = {"model": model, "input": {"messages": [{"role": "user", "content": parts}]}}

                def send(p: Dict[str, Any], body: Dict[str, Any] = body) -> Any:
                    return M._retry(self.ctl, lambda: http.post_json(f"{self.base}/services/aigc/multimodal-generation/generation", {**body, "parameters": p}, self._h(), timeout=300))

                res = self._drop_and_retry(send, params, ("negative_prompt", "seed"))
                urls = _urls((res or {}).get("output"))
            else:
                w, h = M.parse_wh(size)
                params["size"] = _nearest_size(w, h, QWEN_SIZES)
                params["n"] = 1

                def send_t(p: Dict[str, Any]) -> Dict[str, Any]:
                    return self._task("services/aigc/text2image/image-synthesis", {"model": model, "input": {"prompt": prompt}, "parameters": p})

                urls = _urls(self._drop_and_retry(send_t, params, ("negative_prompt", "seed")))
            out += self._download(urls[:1], "image")
        return out

    def video(self, prompt, *, duration=5, aspect="16:9", image=None, model="", extra=None, seed=0, long_side=0):
        model = self.model_for("video", model) or "wan2.2-t2v-plus"
        if image and "i2v" not in model:
            model = model.replace("t2v", "i2v") if "t2v" in model else "wan2.2-i2v-plus"
            self.ctl.note(f"Qwen: com imagem inicial o OpenFlow usou o modelo {model}.")
        inp: Dict[str, Any] = {"prompt": prompt}
        params: Dict[str, Any] = {k: v for k, v in (extra or {}).items() if isinstance(v, (str, int, float, bool))}
        if image:
            inp["img_url"] = M.data_uri(*image)
            params["resolution"] = "1080P" if long_side >= 1000 else "480P" if 0 < long_side <= 600 else "720P"
        else:
            params["size"] = WAN_SIZES.get(aspect) or _nearest_size(*M.size_of_aspect(aspect, 1280), tuple(WAN_SIZES.values()))
        params["duration"] = int(max(2, min(10, duration)))
        if seed:
            params["seed"] = seed % 2147483647

        def send(p: Dict[str, Any]) -> Dict[str, Any]:
            return self._task("services/aigc/video-synthesis", {"model": model, "input": inp, "parameters": p})

        out = self._drop_and_retry(send, params, ("duration", "seed", "size", "resolution"))
        urls = _urls(out)
        return self._download(urls[:1], "video")[0]


# --------------------------------------------------------------------------- Krea


class KreaMedia(_Job):
    """Imagens pela API da Krea: o «modelo» é `provedor/modelo` (ex.: krea/krea-3, bfl/flux-1-dev) e vira parte do endereço."""

    id, label = "krea", "Krea"
    caps = ("image",)

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        self.need_key()
        slug = (self.model_for("image", model) or "krea/krea-3").strip("/")
        if slug.count("/") != 1:
            raise ProviderError("Krea: informe o modelo como provedor/modelo (ex.: krea/krea-3 ou bfl/flux-1-dev).")
        w, h = M.parse_wh(size)
        full: Dict[str, Any] = {"prompt": prompt, "width": w // 8 * 8, "height": h // 8 * 8}
        if negative:
            full["negative_prompt"] = negative
        out: List[M.Media] = []
        for i in range(max(1, count)):
            body = dict(full)
            if seed:
                body["seed"] = (seed + i) % 2147483647
            body.update({k: v for k, v in (extra or {}).items() if isinstance(v, (str, int, float, bool))})
            try:
                job = M._retry(self.ctl, lambda: http.post_json(f"{self.base}/generate/image/{slug}", body, M._auth(self.key), timeout=120))
            except ProviderError as exc:
                if exc.status not in _BAD_REQUEST:
                    raise
                job = M._retry(self.ctl, lambda: http.post_json(f"{self.base}/generate/image/{slug}", {"prompt": prompt}, M._auth(self.key), timeout=120))   # só o prompt: o modelo escolhe o tamanho
            jid = (job or {}).get("job_id") or (job or {}).get("id") if isinstance(job, dict) else None
            if not jid:
                raise ProviderError(f"Krea: resposta inesperada ao criar o trabalho ({str(job)[:160]}).")
            res = self._wait(lambda: http.get_json(f"{self.base}/jobs/{jid}", M._auth(self.key), timeout=60),
                             lambda r: {"completed": "done", "failed": "failed", "cancelled": "failed", "canceled": "failed"}.get(str((r or {}).get("status", "")).lower(), "wait"), "o trabalho")
            out += self._download(_urls((res or {}).get("result"))[:1], "image")
        return out


# --------------------------------------------------------------------------- Bria


class BriaMedia(_Job):
    """Imagens da Bria (FIBO) pela API v2. O «modelo» é o final do endereço depois de `/v2/image/` (padrão: `generate`)."""

    id, label = "bria", "Bria (FIBO)"
    caps = ("image",)
    supports_refs = True

    def max_refs(self, model: str = "") -> int:
        return 1

    def refs_need_edit(self, model: str = "") -> bool:
        return False

    def _h(self) -> Dict[str, str]:
        self.need_key()
        return {"api_token": self.key}

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        path = (self.model_for("image", model) or "generate").strip("/")
        w, h = M.parse_wh(size)
        full: Dict[str, Any] = {"prompt": prompt, "aspect_ratio": _nearest_ratio(w, h, BRIA_ASPECTS)}
        if negative:
            full["negative_prompt"] = negative
        if refs:
            import base64

            full["images"] = [base64.b64encode(d).decode("ascii") for d, _ in list(refs)[:1]]
        out: List[M.Media] = []
        for i in range(max(1, count)):
            body = dict(full)
            if seed:
                body["seed"] = (seed + i) % 2147483647
            body.update({k: v for k, v in (extra or {}).items() if isinstance(v, (str, int, float, bool))})
            url = f"{self.base}/image/{path}"
            try:
                sent = M._retry(self.ctl, lambda: http.post_json(url, body, self._h(), timeout=180))
            except ProviderError as exc:
                if exc.status not in _BAD_REQUEST or not ({"negative_prompt", "seed"} & set(body)):
                    raise
                sent = M._retry(self.ctl, lambda: http.post_json(url, {k: v for k, v in body.items() if k not in ("negative_prompt", "seed")}, self._h(), timeout=180))
            res = sent
            if isinstance(sent, dict) and not _urls(sent.get("result")):   # resposta assíncrona: consulta a `status_url` até terminar
                status_url = sent.get("status_url") or (f"{self.base}/status/{sent['request_id']}" if sent.get("request_id") else "")
                if not status_url:
                    raise ProviderError(f"Bria: resposta inesperada ({str(sent)[:160]}).")
                res = self._wait(lambda: http.get_json(status_url, self._h(), timeout=60),
                                 lambda r: {"COMPLETED": "done", "ERROR": "failed", "FAILED": "failed", "UNKNOWN": "failed"}.get(str((r or {}).get("status", "")).upper(), "wait"), "a imagem")
            out += self._download(_urls((res or {}).get("result"))[:1], "image")
        return out


# --------------------------------------------------------------------------- registro

KINDS = {"qwen": QwenMedia, "krea": KreaMedia, "bria": BriaMedia}

PRESETS: Dict[str, Dict[str, Any]] = {
    "qwen": {
        "label": "Qwen (Alibaba Cloud)", "kind": "qwen", "caps": ["image", "video"], "base_url": "https://dashscope-intl.aliyuncs.com/api/v1", "needs_key": True,
        "docs": "https://bailian.console.alibabacloud.com/?tab=model#/api-key", "models": {"image": "qwen-image", "video": "wan2.2-t2v-plus"},
        "suggest": {"image": ["qwen-image", "qwen-image-plus", "qwen-image-edit-plus", "qwen-image-edit"], "video": ["wan2.2-t2v-plus", "wan2.2-i2v-plus", "wan2.5-t2v-preview", "wan2.5-i2v-preview"]},
        "hint": "Qwen-Image (geração e edição com até 3 referências) e vídeos Wan (texto → vídeo; com imagem inicial usa o modelo i2v). Chave do Alibaba Cloud Model Studio. Para a China, troque o endereço por https://dashscope.aliyuncs.com/api/v1. Experimental: ainda não testado com chave real.",
    },
    "krea": {
        "label": "Krea", "kind": "krea", "caps": ["image"], "base_url": "https://api.krea.ai", "needs_key": True,
        "docs": "https://www.krea.ai/settings/api-tokens", "models": {"image": "krea/krea-3"}, "suggest": {"image": ["krea/krea-3", "bfl/flux-1-dev"]},
        "hint": "Informe o modelo como provedor/modelo (ex.: krea/krea-3, bfl/flux-1-dev). Experimental: ainda não testado com chave real.",
    },
    "bria": {
        "label": "Bria (FIBO)", "kind": "bria", "caps": ["image"], "base_url": "https://engine.prod.bria-api.com/v2", "needs_key": True,
        "docs": "https://platform.bria.ai/console/account/api-keys", "models": {"image": "generate"}, "suggest": {"image": ["generate"]},
        "hint": "Geração (e uma imagem de referência) pelo FIBO da Bria, com licença comercial própria. O «modelo» é o final do endereço depois de /v2/image/. Experimental: ainda não testado com chave real.",
    },
}


def register(kinds: Dict[str, Any], presets: Dict[str, Dict[str, Any]]) -> None:
    kinds.update(KINDS)
    presets.update(PRESETS)
