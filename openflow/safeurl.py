"""Download seguro de links públicos (nó «Link»): só http(s) para hosts públicos — nunca localhost nem redes privadas, nem por redirecionamento (SSRF)."""
from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

from .providers import http
from .util import ssl_context

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0 OpenFlow", "Accept": "*/*", "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}


def safe_url(url: str) -> bool:
    """http(s) para um host público: recusa localhost, redes privadas e endereços especiais."""
    try:
        sp = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if sp.scheme not in ("http", "https") or not sp.hostname:
        return False
    host = sp.hostname
    if http.is_local_host(host):
        return False
    try:
        infos = socket.getaddrinfo(host, sp.port or (443 if sp.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Cada redirecionamento também precisa apontar para um host público."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_url(newurl):
            raise urllib.error.HTTPError(newurl, 403, "redirecionamento para endereço não público", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(_SafeRedirect, urllib.request.HTTPSHandler(context=ssl_context()))
