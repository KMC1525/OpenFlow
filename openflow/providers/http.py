"""Cliente HTTP mínimo (urllib) com JSON e SSE. Sem dependências externas."""
from __future__ import annotations

import ipaddress
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .. import __version__
from .base import ProviderError

RETRYABLE = (429, 502, 503, 529)
_QUOTA = re.compile(r"quota|billing|insufficient|credit|exceeded your current|saldo|crédito", re.I)
USER_AGENT = f"OpenFlow/{__version__} (+https://github.com/KMC1525/OpenFlow)"


def _ctx() -> ssl.SSLContext:
    from ..util import ssl_context

    return ssl_context()   # no macOS com o Python do python.org o contexto padrão não tem certificados: ver util.ssl_context


def _read_error(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        body = ""
    try:
        data = json.loads(body)
        err = data.get("error", data)
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err, ensure_ascii=False)
        return str(err)[:600]
    except Exception:  # noqa: BLE001
        return body[:600]


_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def is_local_host(host: str) -> bool:
    """localhost, 127.x, ::1, redes privadas (192.168.x, 10.x…) e nomes .local: servidores na própria máquina ou na rede de casa (Ollama, LM Studio…)."""
    host = (host or "").strip("[]").lower()
    if host in ("localhost", "ip6-localhost") or host.endswith((".local", ".lan", ".home.arpa", ".ts.net")):   # .ts.net: nomes MagicDNS do Tailscale (o PC de casa, de fora de casa)
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 4 and ip in _CGNAT:   # 100.64.0.0/10: endereços de VPN (Tailscale e similares), que também não passam pelo proxy do sistema
        return True
    return ip.is_loopback or ip.is_private or ip.is_link_local


_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=_ctx()))


def request(
    url: str,
    payload: Optional[dict] = None,
    headers: Optional[Dict[str, str]] = None,
    method: Optional[str] = None,
    timeout: float = 120,
    raw_body: Optional[bytes] = None,
    retries: int = 0,
):
    """Abre uma requisição e devolve a resposta (file-like). Levanta ProviderError.
    `retries`: tentativas extras quando o servidor está sobrecarregado (429/502/503/529), esperando o `Retry-After` (até 8 s). Limite de cota/créditos
    esgotados (também 429) nunca é repetido: não adianta."""
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    hdrs.update(headers or {})
    data = raw_body
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    try:
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method or ("POST" if data is not None else "GET"))
    except ValueError:
        raise ProviderError(f"Endereço inválido: «{url[:120]}». Use o formato http://servidor:porta/v1") from None
    direct = is_local_host(urllib.parse.urlsplit(url).hostname or "")
    for attempt in range(retries + 1):
        try:
            # servidor local/da rede de casa nunca passa pelo proxy do sistema (HTTP_PROXY): ele não enxerga o 127.0.0.1 de quem pede
            if direct:
                return _DIRECT.open(req, timeout=timeout)
            return urllib.request.urlopen(req, timeout=timeout, context=_ctx())
        except urllib.error.HTTPError as exc:
            msg = _read_error(exc) or str(exc.reason)
            if exc.code in RETRYABLE and attempt < retries and not _QUOTA.search(msg):
                try:
                    wait = float(exc.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    wait = 0
                time.sleep(min(max(wait, 0.5 * (attempt + 1)), 8.0))
                continue
            raise ProviderError(msg, status=exc.code) from None
        except urllib.error.URLError as exc:
            raise ProviderError(f"Não foi possível conectar a {urllib.parse.urlsplit(url).netloc or url[:60]}: {exc.reason}") from None
        except (TimeoutError, OSError) as exc:
            raise ProviderError(f"Falha de rede: {exc}") from None
    raise ProviderError("Falha de rede.")  # pragma: no cover


def get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30) -> Any:
    with request(url, headers=headers, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def post_json(url: str, payload: dict, headers: Optional[Dict[str, str]] = None, timeout: float = 120, retries: int = 0) -> Any:
    with request(url, payload, headers, timeout=timeout, retries=retries) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def post_bytes(url: str, payload: dict, headers: Optional[Dict[str, str]] = None, timeout: float = 120) -> Tuple[bytes, str]:
    with request(url, payload, headers, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")


def post_multipart(
    url: str, fields: Dict[str, str], file_field: str, filename: str, file_bytes: bytes, file_mime: str,
    headers: Optional[Dict[str, str]] = None, timeout: float = 180,
) -> Any:
    boundary = "----flow" + uuid.uuid4().hex
    parts = []
    for key, val in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'.encode("utf-8")
        )
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {file_mime}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    hdrs = dict(headers or {})
    hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    with request(url, headers=hdrs, method="POST", timeout=timeout, raw_body=b"".join(parts)) as resp:
        body = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"text": body}


def multipart_body(fields: Dict[str, Any], files: List[Tuple[str, str, bytes, str]]) -> Tuple[bytes, str]:
    """Monta um corpo multipart/form-data. `files`: [(campo, nome_do_arquivo, bytes, mime)]. Devolve (corpo, content_type)."""
    boundary = "----flow" + uuid.uuid4().hex
    parts: List[bytes] = []
    for key, val in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'.encode("utf-8"))
    for field, filename, data, mime in files:
        safe = filename.replace('"', "").replace("\r", "").replace("\n", "")
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{safe}"\r\nContent-Type: {mime}\r\n\r\n'.encode("utf-8"))
        parts.append(data)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def post_multipart_files(
    url: str, fields: Dict[str, Any], files: List[Tuple[str, str, bytes, str]],
    headers: Optional[Dict[str, str]] = None, timeout: float = 300, raw: bool = False,
) -> Any:
    """POST multipart com vários arquivos. `raw=True` devolve (bytes, content_type); senão o JSON (ou {"text": ...})."""
    body, ctype = multipart_body(fields, files)
    hdrs = dict(headers or {})
    hdrs["Content-Type"] = ctype
    with request(url, headers=hdrs, method="POST", timeout=timeout, raw_body=body) as resp:
        data, mime = resp.read(), resp.headers.get("Content-Type", "application/octet-stream")
    if raw:
        return data, mime
    text_ = data.decode("utf-8", "replace")
    try:
        return json.loads(text_)
    except json.JSONDecodeError:
        return {"text": text_}


def get_bytes(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 300, max_bytes: int = 400 * 1024 * 1024) -> Tuple[bytes, str]:
    """Baixa um arquivo (imagem/vídeo/áudio devolvido por uma API). Limita o tamanho."""
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):  # nunca file://, ftp:// etc. vindos de uma resposta de API
        raise ProviderError("O provedor devolveu um endereço de arquivo inválido.")
    with request(url, headers={"Accept": "*/*", **(headers or {})}, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ProviderError("O arquivo devolvido pelo provedor é grande demais.")
        return data, resp.headers.get("Content-Type", "application/octet-stream")


def stream_sse(
    url: str, payload: dict, headers: Optional[Dict[str, str]] = None, timeout: float = 300, retries: int = 0
) -> Iterator[Tuple[str, str]]:
    """Gera tuplas (evento, dados) de uma resposta Server-Sent Events."""
    hdrs = {"Accept": "text/event-stream"}
    hdrs.update(headers or {})
    resp = request(url, payload, hdrs, timeout=timeout, retries=retries)
    event = "message"
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                event = "message"
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                yield event, line[5:].strip()
    finally:
        resp.close()
