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
from typing import Any, Dict, Optional

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
