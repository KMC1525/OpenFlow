"""Busca na web nativa do OpenFlow — funciona com **qualquer** modelo (nuvem ou local) e em qualquer prompt do Chat ou de uma ferramenta de criação.

Só biblioteca padrão. Motores (`chat.web.engine`):
  • `auto` (padrão, sem chave): DuckDuckGo; se falhar ou vier vazio, Wikipédia.
  • `duckduckgo`, `wikipedia`  — sem chave.
  • `brave` (chave), `tavily` (chave), `searxng` (endereço da sua instância).
Depois da busca o OpenFlow lê o texto das primeiras páginas (`fetch_pages`) e monta um bloco numerado «[1] título — url — trecho» que entra no contexto do
modelo, que cita as fontes como [1], [2]. Segurança: só `http(s)`, endereços que apontam para a própria máquina/rede privada são recusados nas páginas
dos resultados (SSRF), tamanho e tempo limitados.
"""
from __future__ import annotations

import html
import json
import re
import socket
import ipaddress
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

from .providers import http
from .providers.base import ProviderError
from .util import ssl_context

MAX_RESULTS = 10
PAGE_BYTES = 400_000
PAGE_CHARS = 3500
CONTEXT_CHARS = 12000
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0 OpenFlow", "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8", "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}


class SearchError(Exception):
    pass


# --------------------------------------------------------------------------- configuração
def web_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    c = ((settings.get("chat") or {}).get("web") or {})
    try:
        n = int(c.get("results", 5))
    except (TypeError, ValueError):
        n = 5
    try:
        pages = int(c.get("read_pages", 2))
    except (TypeError, ValueError):
        pages = 2
    engine = str(c.get("engine") or "auto").lower()
    if engine not in ("auto", "duckduckgo", "wikipedia", "brave", "tavily", "searxng"):
        engine = "auto"
    return {"engine": engine, "results": max(1, min(MAX_RESULTS, n)), "read_pages": max(0, min(5, pages)), "default": bool(c.get("default", False)),
            "brave_key": str(c.get("brave_key") or ""), "tavily_key": str(c.get("tavily_key") or ""), "searxng_url": str(c.get("searxng_url") or "").strip().rstrip("/"),
            "language": str(c.get("language") or "auto")}


# --------------------------------------------------------------------------- segurança das URLs
def safe_url(url: str) -> bool:
    """http(s) para um host público: recusa localhost, redes privadas e endereços especiais (o resultado da busca não pode apontar para a máquina do usuário)."""
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


# --------------------------------------------------------------------------- HTML → texto
class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form", "iframe", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(src: str, limit: int = PAGE_CHARS) -> Dict[str, str]:
    p = _Text()
    try:
        p.feed(src)
        p.close()
    except Exception:  # noqa: BLE001  (HTML quebrado: aproveita o que deu)
        pass
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.parts).split("\n")]
    lines = [ln for ln in lines if len(ln) > 25 or (ln and len(lines) < 6)]  # tira menus e rótulos soltos
    txt = re.sub(r"\n{2,}", "\n", "\n".join(lines)).strip()
    return {"title": re.sub(r"\s+", " ", p.title).strip(), "text": txt[:limit]}


# --------------------------------------------------------------------------- motores
def _get(url: str, headers: Optional[dict] = None, timeout: float = 12, payload: Optional[dict] = None, raw: bool = False):
    hdrs = dict(_UA)
    hdrs.update(headers or {})
    try:
        with http.request(url, payload, hdrs, timeout=timeout, raw_body=None) as resp:
            data = resp.read(PAGE_BYTES * 2)
            ctype = resp.headers.get("Content-Type", "")
    except ProviderError as exc:
        raise SearchError(str(exc)) from None
    return data if raw else (data, ctype)


def _decode(data: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "latin-1"]:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def _ddg(query: str, n: int, lang: str) -> List[Dict[str, str]]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query, "kl": "br-pt" if lang == "pt" else "wt-wt"})
    data, ctype = _get(url)
    page = _decode(data, ctype)
    out: List[Dict[str, str]] = []
    for m in re.finditer(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="[^"]*result__a|\Z)', page, re.S):
        href, title, rest = html.unescape(m.group(1)), m.group(2), m.group(3)
        if href.startswith("//"):
            href = "https:" + href
        if "duckduckgo.com/l/" in href:  # link de redirecionamento: a URL real vem em uddg=
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query).get("uddg")
            if not q:
                continue
            href = q[0]
        if "duckduckgo.com/y.js" in href or not href.startswith("http"):  # anúncio
            continue
        sn = re.search(r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>', rest, re.S)
        out.append({"title": _clean(title), "url": href, "snippet": _clean(sn.group(1)) if sn else ""})
        if len(out) >= n:
            break
    if not out and re.search(r"anomaly|captcha|unusual traffic", page, re.I):
        raise SearchError("O DuckDuckGo pediu verificação (muitas buscas seguidas). Tente de novo em instantes ou escolha outro motor em Configuração → Chat.")
    return out


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def _wikipedia(query: str, n: int, lang: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for code in ([lang, "en"] if lang != "en" else ["en"]):
        url = f"https://{code}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query, "srlimit": n, "format": "json", "utf8": 1})
        data, _ = _get(url)
        for it in (json.loads(data.decode("utf-8", "replace")).get("query", {}).get("search") or []):
            title = it.get("title", "")
            out.append({"title": f"{title} — Wikipédia" if code == "pt" else f"{title} — Wikipedia", "url": f"https://{code}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")), "snippet": _clean(it.get("snippet", ""))})
        if out:
            break
    return out[:n]


def _brave(query: str, n: int, key: str) -> List[Dict[str, str]]:
    if not key:
        raise SearchError("Informe a chave da Brave Search em Configuração → Chat.")
    data, _ = _get("https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode({"q": query, "count": n}), {"X-Subscription-Token": key, "Accept": "application/json"})
    res = (json.loads(data.decode("utf-8", "replace")).get("web") or {}).get("results") or []
    return [{"title": _clean(r.get("title", "")), "url": r.get("url", ""), "snippet": _clean(r.get("description", ""))} for r in res[:n] if r.get("url")]


def _tavily(query: str, n: int, key: str) -> List[Dict[str, str]]:
    if not key:
        raise SearchError("Informe a chave da Tavily em Configuração → Chat.")
    try:
        data = http.post_json("https://api.tavily.com/search", {"query": query, "max_results": n}, {"Authorization": f"Bearer {key}"}, timeout=20)
    except ProviderError as exc:
        raise SearchError(str(exc)) from None
    return [{"title": _clean(r.get("title", "")), "url": r.get("url", ""), "snippet": _clean(r.get("content", ""))[:400]} for r in (data.get("results") or [])[:n] if r.get("url")]


def _searxng(query: str, n: int, base: str) -> List[Dict[str, str]]:
    if not base:
        raise SearchError("Informe o endereço da sua instância SearXNG em Configuração → Chat.")
    if "://" not in base:
        base = "http://" + base
    data, _ = _get(base + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"}))
    try:
        res = json.loads(data.decode("utf-8", "replace")).get("results") or []
    except json.JSONDecodeError:
        raise SearchError("A instância SearXNG não devolveu JSON: ative o formato json em settings.yml (search.formats).") from None
    return [{"title": _clean(r.get("title", "")), "url": r.get("url", ""), "snippet": _clean(r.get("content", ""))} for r in res[:n] if r.get("url")]


def guess_lang(text: str, ui_lang: str = "auto") -> str:
    if ui_lang in ("pt", "en"):
        return ui_lang
    t = " " + text.lower() + " "
    pt = sum(t.count(w) for w in (" que ", " não ", " como ", " para ", " uma ", " com ", " qual ", " é ", " do ", " da ", " em ", "ção"))
    en = sum(t.count(w) for w in (" the ", " what ", " how ", " is ", " of ", " and ", " to ", " for ", " with "))
    return "pt" if pt > en else "en"


def search(query: str, settings: Dict[str, Any], n: Optional[int] = None, ui_lang: str = "auto") -> Dict[str, Any]:
    """{engine, query, results:[{title,url,snippet}]}. Levanta SearchError com mensagem útil."""
    cfg = web_config(settings)
    query = re.sub(r"\s+", " ", str(query or "")).strip()[:300]
    if not query:
        raise SearchError("Nada para pesquisar.")
    n = max(1, min(MAX_RESULTS, n or cfg["results"]))
    lang = guess_lang(query, cfg["language"] if cfg["language"] != "auto" else ui_lang)
    eng = cfg["engine"]
    errors: List[str] = []
    order = ["duckduckgo", "wikipedia"] if eng == "auto" else [eng]
    for name in order:
        try:
            if name == "duckduckgo":
                res = _ddg(query, n, lang)
            elif name == "wikipedia":
                res = _wikipedia(query, n, lang)
            elif name == "brave":
                res = _brave(query, n, cfg["brave_key"])
            elif name == "tavily":
                res = _tavily(query, n, cfg["tavily_key"])
            else:
                res = _searxng(query, n, cfg["searxng_url"])
        except SearchError as exc:
            errors.append(f"{name}: {exc}")
            continue
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        res = [r for r in res if r.get("url", "").startswith(("http://", "https://"))]
        if res:
            return {"engine": name, "query": query, "results": res[:n]}
    raise SearchError("Não encontrei resultados na web." + ((" " + " · ".join(errors)) if errors else ""))


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Cada redirecionamento também precisa apontar para um host público."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_url(newurl):
            raise urllib.error.HTTPError(newurl, 403, "redirecionamento para endereço não público", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_SafeRedirect, urllib.request.HTTPSHandler(context=ssl_context()))


def fetch_page(url: str, limit: int = PAGE_CHARS) -> Dict[str, str]:
    """Texto principal de uma página pública ({title, text}); {} se não deu."""
    if not safe_url(url):
        return {}
    try:
        with _OPENER.open(urllib.request.Request(url, headers=_UA), timeout=8) as resp:
            ctype = resp.headers.get("Content-Type", "")
            if ctype and not re.search(r"html|text|xml", ctype, re.I):
                return {}
            data = resp.read(PAGE_BYTES)
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    return html_to_text(_decode(data, ctype), limit)


def gather(query: str, settings: Dict[str, Any], ui_lang: str = "auto") -> Dict[str, Any]:
    """Busca + leitura das primeiras páginas (em paralelo). {engine, query, sources, text}."""
    cfg = web_config(settings)
    found = search(query, settings, ui_lang=ui_lang)
    sources: List[Dict[str, Any]] = []
    for i, r in enumerate(found["results"], 1):
        host = (urllib.parse.urlsplit(r["url"]).hostname or "").removeprefix("www.")
        sources.append({"n": i, "title": r["title"] or host, "url": r["url"], "host": host, "snippet": r["snippet"], "text": ""})
    todo = sources[:cfg["read_pages"]]
    if todo:
        def read(s):
            return s["n"], fetch_page(s["url"])
        with ThreadPoolExecutor(max_workers=min(6, len(todo))) as ex:
            futs = {ex.submit(read, s): s for s in todo}
            for fut in as_completed(futs):
                try:
                    n, page = fut.result()
                except Exception:
                    continue
                for s in sources:
                    if s["n"] == n:
                        s["text"] = (page or {}).get("text", "")
                        if not s.get("title") and page and page.get("title"):
                            s["title"] = page["title"]
                        break
    return {"engine": found["engine"], "query": found["query"], "sources": sources, "text": context_block(sources)}


def context_block(sources: List[Dict[str, Any]], limit: int = CONTEXT_CHARS) -> str:
    parts: List[str] = []
    used = 0
    for s in sources:
        remaining = limit - used
        if remaining < 200:
            break
        body = (s.get("text") or "").strip() or s.get("snippet", "")
        chunk = f"[{s['n']}] {s['title']}\n{s['url']}\n{body}".strip()[:remaining]
        parts.append(chunk)
        used += len(chunk) + 2
    return "\n\n".join(parts)


def public_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fontes para a interface (na ordem em que a busca devolveu): título, link, host, trecho e se a página foi lida por inteiro."""
    return [{"n": s["n"], "title": s["title"][:140], "url": s["url"][:500], "host": s["host"][:80], "snippet": (s.get("snippet") or "")[:300], "read": bool(s.get("text"))} for s in sources]


def heuristic_query(text: str) -> str:
    """Consulta de busca a partir da pergunta quando não dá para pedir ao modelo: tira a pontuação sobrando e limita o tamanho."""
    q = re.sub(r"\s+", " ", text or "").strip()
    q = re.sub(r"^(por favor|please|me diga|me explique|pesquise|busque|procure|search for|search|look up|tell me)[, ]+", "", q, flags=re.I)
    return q[:200]


# --------------------------------------------------------------------------- links colados no Chat (páginas com imagens e vídeos)
LINK_MAX = 6              # links lidos por mensagem
LINK_CHARS = 16000        # texto de cada página
LINK_IMAGES = 6           # imagens de cada página mostradas ao modelo (com visão)
IMAGE_BYTES = 4_000_000
_URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)
_VIDEO_HOSTS = ("youtube.com", "youtu.be", "youtube-nocookie.com", "vimeo.com", "dailymotion.com", "twitch.tv", "tiktok.com", "streamable.com", "loom.com")
_IMG_OK = ("image/jpeg", "image/png", "image/webp", "image/gif")


def extract_urls(text: str, limit: int = LINK_MAX) -> List[str]:
    """Links http(s) do texto, sem repetir e sem a pontuação que sobra no fim da frase."""
    out: List[str] = []
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,;:!?»”’")
        if u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


class _Media(HTMLParser):
    """Imagens, vídeos e metadados (og:*, twitter:*) de uma página (galerias inclusas)."""

    _LAZY = ("src", "data-src", "data-original", "data-lazy-src", "data-pin-media", "data-image", "data-hi-res", "data-full", "data-zoom-image")

    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.images: List[Dict[str, str]] = []
        self.videos: List[Dict[str, str]] = []
        self.meta: Dict[str, str] = {}
        self.meta_all: Dict[str, List[str]] = {}
        self._video_open = False
        self._skip = 0

    def _abs(self, u: str) -> str:
        u = (u or "").strip()
        if not u or u.startswith(("data:", "javascript:", "blob:", "#")):
            return ""
        try:
            return urllib.parse.urljoin(self.base, u)
        except ValueError:
            return ""

    def _img(self, u: str, alt: str = "") -> None:
        u = self._abs(u)
        if u.startswith(("http://", "https://")) and all(i["url"] != u for i in self.images) and len(self.images) < 80:
            self.images.append({"url": u, "alt": re.sub(r"\s+", " ", alt or "").strip()[:160]})

    def _vid(self, u: str, title: str = "") -> None:
        u = self._abs(u)
        if u.startswith(("http://", "https://")) and all(v["url"] != u for v in self.videos) and len(self.videos) < 20:
            self.videos.append({"url": u, "title": re.sub(r"\s+", " ", title or "").strip()[:160]})

    def _srcset(self, value: str) -> List[str]:
        out = []
        for part in (value or "").split(","):
            u = part.strip().split(" ")[0] if part.strip() else ""
            if u:
                out.append(u)
        return out

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            val = a.get("content") or ""
            if key and val:
                if key not in self.meta:
                    self.meta[key] = val
                self.meta_all.setdefault(key, []).append(val)
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            if "image" in rel and a.get("href"):
                self._img(a["href"], a.get("title", "") or "imagem")
        elif tag == "img":
            for k in self._LAZY:
                if a.get(k):
                    self._img(a[k], a.get("alt", ""))
            for k in ("srcset", "data-srcset"):
                for u in self._srcset(a.get(k, "")):
                    self._img(u, a.get("alt", ""))
            w, h = a.get("width", ""), a.get("height", "")
            if w.isdigit() and h.isdigit() and int(w) < 60 and int(h) < 60:
                pass
        elif tag == "source":
            if self._video_open:
                self._vid(a.get("src", ""))
            for u in self._srcset(a.get("srcset", "")):
                self._img(u, a.get("alt", "") or "imagem")
        elif tag == "video":
            self._video_open = True
            self._vid(a.get("src", ""), a.get("title", "") or a.get("aria-label", ""))
            if a.get("poster"):
                self._img(a["poster"], "capa do vídeo")
        elif tag == "iframe":
            src = self._abs(a.get("src") or a.get("data-src") or "")
            host = (urllib.parse.urlsplit(src).hostname or "").lower() if src else ""
            if src and any(host == h or host.endswith("." + h) for h in _VIDEO_HOSTS):
                self._vid(src, a.get("title", ""))
        elif tag == "a":
            href = self._abs(a.get("href", ""))
            host = (urllib.parse.urlsplit(href).hostname or "").lower() if href else ""
            if href and re.search(r"\.(jpg|jpeg|png|webp|gif|avif)(\?|$)", href, re.I):
                self._img(href, a.get("title", "") or a.get("aria-label", ""))
            if href and (re.search(r"\.(mp4|webm|mov|m4v|mkv)(\?|$)", href, re.I) or any(host == h or host.endswith("." + h) for h in _VIDEO_HOSTS)):
                self._vid(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1
        if tag == "video":
            self._video_open = False


def page_media(src: str, base: str) -> Dict[str, Any]:
    """{images:[{url,alt}], videos:[{url,title}], meta:{...}} de um HTML (inclui galerias e metadados)."""
    p = _Media(base)
    try:
        p.feed(src)
        p.close()
    except Exception:  # noqa: BLE001
        pass
    lead_keys = ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src", "image")
    lead = []
    for k in lead_keys:
        for v in (p.meta_all.get(k) or ([p.meta.get(k)] if p.meta.get(k) else [])):
            u = p._abs(v)
            if u.startswith(("http://", "https://")) and u not in lead:
                lead.append(u)
    # JSON-LD e URLs de imagem embutidas (útil em galerias como Pinterest/Instagram/pawchive)
    for m in re.finditer(r'"(?:contentUrl|image|thumbnailUrl|url)"\s*:\s*"(https?://[^"\s]+)"', src or ""):
        u = p._abs(m.group(1))
        if u.startswith(("http://", "https://")) and re.search(r"\.(jpg|jpeg|png|webp|gif|avif)|/pin/|/media|/image|pbs\.twimg|cdninstagram|pinimg|pawchive", u, re.I):
            if u not in lead and len(lead) < 30:
                lead.append(u)
    for m in re.finditer(r"https?://[^\s\"'<>]+?\.(?:jpg|jpeg|png|webp|gif|avif)(?:\?[^\s\"'<>]*)?", src or "", re.I):
        u = p._abs(m.group(0))
        if u.startswith(("http://", "https://")) and len(lead) < 40 and u not in lead and not re.search(r"(sprite|pixel|tracking|1x1|icon|logo)", u, re.I):
            lead.append(u)
    images = []
    for u in lead[:3]:
        images.append({"url": u, "alt": p.meta.get("og:image:alt", "") or "imagem de destaque"})
    images += [i for i in p.images if all(i["url"] != j["url"] for j in images)]
    videos: List[Dict[str, str]] = []
    for k in ("og:video:url", "og:video:secure_url", "og:video", "twitter:player:stream", "twitter:player"):
        for v in (p.meta_all.get(k) or ([p.meta.get(k)] if p.meta.get(k) else [])):
            u = p._abs(v)
            if u.startswith(("http://", "https://")) and all(u != x["url"] for x in videos):
                videos.append({"url": u, "title": p.meta.get("og:title", "")})
    videos += [v for v in p.videos if all(v["url"] != w["url"] for w in videos)]
    return {"images": images[:60], "videos": videos[:12], "meta": p.meta}



def fetch_image(url: str) -> Optional[Dict[str, str]]:
    """Baixa uma imagem pública ({media_type, data base64}) para mostrar a um modelo com visão; None se não deu."""
    import base64
    if not safe_url(url):
        return None
    try:
        with _OPENER.open(urllib.request.Request(url, headers=_UA), timeout=8) as resp:
            ctype = (resp.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
            if ctype == "image/jpg":
                ctype = "image/jpeg"
            if ctype not in _IMG_OK:
                return None
            data = resp.read(IMAGE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not data or len(data) > IMAGE_BYTES:
        return None
    return {"media_type": ctype, "data": base64.b64encode(data).decode("ascii")}


_IMG_WORDS = re.compile(r"imag|foto|figura|print|screenshot|captura|ilustra|diagrama|gr[áa]fico|infogr|banner|thumb|capa\b|image|picture|photo|pic\b|diagram|chart|graphic|illustration", re.I)
_VID_WORDS = re.compile(r"v[ií]deo|assist|transcri|legenda|[áa]udio|fala|filme|clipe|trailer|aula|watch|clip\b|footage|movie|subtitle|caption|speech|audio|recording|reel", re.I)
VIDEO_BYTES = 60_000_000
VIDEO_MAX = 2
_VIDEO_EXT = re.compile(r"\.(mp4|webm|mov|m4v|mkv|avi)(\?|$)", re.I)


def link_intent(prompt: str) -> Dict[str, Any]:
    """O que o usuário pede sobre o conteúdo dos links: olhar as imagens e/ou os vídeos."""
    txt = _URL_RE.sub(" ", prompt or "")
    imgs, vids = bool(_IMG_WORDS.search(txt)), bool(_VID_WORDS.search(txt))
    return {"images": imgs, "videos": vids, "max_images": 10 if imgs else LINK_IMAGES}


def download_media(url: str, dest_dir: Path, max_bytes: int = VIDEO_BYTES) -> Optional[Path]:
    """Baixa um arquivo de vídeo público para `dest_dir`; None se não deu."""
    if not safe_url(url):
        return None
    try:
        with _OPENER.open(urllib.request.Request(url, headers=_UA), timeout=20) as resp:
            ctype = (resp.headers.get("Content-Type", "") or "").lower()
            if ctype and not re.search(r"video|audio|octet-stream", ctype):
                return None
            try:
                if int(resp.headers.get("Content-Length") or 0) > max_bytes:
                    return None
            except ValueError:
                pass
            m = _VIDEO_EXT.search(urllib.parse.urlsplit(url).path + "?")
            ext = m.group(1).lower() if m else "mp4"
            out = dest_dir / f"video.{ext}"
            total = 0
            with out.open("wb") as fh:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        return None
                    fh.write(chunk)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return out if total else None


def _platform_download(url: str, dest_dir: Path) -> Optional[Path]:
    """YouTube, Vimeo etc.: só com o `yt-dlp` instalado. Sem ele, o vídeo fica só descrito."""
    import shutil
    import subprocess
    exe = shutil.which("yt-dlp")
    if not exe or not safe_url(url):
        return None
    try:
        subprocess.run([exe, "-q", "--no-playlist", "--max-filesize", str(VIDEO_BYTES), "-f", "worst[ext=mp4]/worst", "--socket-timeout", "15", "-o", str(dest_dir / "video.%(ext)s"), url],
                       capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    found = sorted(dest_dir.glob("video.*"))
    return found[0] if found else None


def analyze_video(url: str, transcribe: Optional[Any] = None, max_chars: int = 8000) -> Dict[str, Any]:
    """Baixa e analisa um vídeo: {text (transcrição), frames:[{media_type,data}], notes}."""
    import tempfile
    from . import attachments as att
    res: Dict[str, Any] = {"text": "", "frames": [], "notes": []}
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        path = download_media(url, d) if _VIDEO_EXT.search(urllib.parse.urlsplit(url).path + "?") else None
        if path is None:
            path = _platform_download(url, d)
        if path is None:
            res["notes"].append("não deu para baixar o vídeo (grande demais, protegido ou plataforma sem o yt-dlp instalado)")
            return res
        item = att.analyze(path, path.name, "video/mp4", max_chars=max_chars, transcribe=transcribe)
        res["text"], res["frames"], res["notes"] = item.get("text", ""), item.get("images", []), item.get("notes", [])
    return res


def _fetch_images_parallel(urls: List[str], limit: int) -> List[Dict[str, str]]:
    want = [u for u in urls[: max(limit * 2, 12)] if isinstance(u, str)]
    out: List[Dict[str, str]] = []
    if not want or limit <= 0:
        return out
    with ThreadPoolExecutor(max_workers=min(6, len(want))) as ex:
        futs = [ex.submit(fetch_image, u) for u in want]
        for fut in as_completed(futs):
            try:
                pic = fut.result()
            except Exception:
                pic = None
            if pic:
                out.append(pic)
                if len(out) >= limit:
                    break
    return out


def read_link(url: str, want_images: bool = True, max_images: int = LINK_IMAGES) -> Dict[str, Any]:
    """Lê um link colado pelo usuário: texto, imagens e vídeos da página (imagens baixadas em paralelo)."""
    out: Dict[str, Any] = {"url": url, "title": "", "kind": "page", "text": "", "images": [], "videos": [], "pics": [], "error": ""}
    if not safe_url(url):
        out["error"] = "endereço não público ou inválido"
        return out
    try:
        with _OPENER.open(urllib.request.Request(url, headers=_UA), timeout=10) as resp:
            ctype = (resp.headers.get("Content-Type", "") or "").split(";")[0].strip().lower()
            final = resp.geturl() or url
            if ctype.startswith("image/"):
                out["kind"] = "image"
                data = resp.read(IMAGE_BYTES + 1)
                ctype = "image/jpeg" if ctype == "image/jpg" else ctype
                if want_images and ctype in _IMG_OK and 0 < len(data) <= IMAGE_BYTES:
                    import base64
                    out["pics"].append({"media_type": ctype, "data": base64.b64encode(data).decode("ascii")})
                out["images"].append({"url": final, "alt": ""})
                return out
            if ctype.startswith(("video/", "audio/")):
                out["kind"] = "video" if ctype.startswith("video/") else "file"
                out["videos"].append({"url": final, "title": ""})
                return out
            if ctype and not re.search(r"html|text|xml|json", ctype):
                out["kind"] = "file"
                out["error"] = f"tipo de arquivo não lido ({ctype})"
                return out
            raw = resp.read(PAGE_BYTES * 2)
    except urllib.error.HTTPError as exc:
        out["error"] = f"o site respondeu {exc.code}"
        return out
    except (urllib.error.URLError, OSError, ValueError) as exc:
        out["error"] = str(getattr(exc, "reason", exc))[:120] or "não abriu"
        return out
    src = _decode(raw, ctype)
    if "json" in ctype:
        out["text"] = src[:LINK_CHARS]
        return out
    page = html_to_text(src, LINK_CHARS)
    media = page_media(src, final)
    meta = media["meta"]
    out["title"] = page["title"] or meta.get("og:title", "")
    desc = meta.get("og:description") or meta.get("description") or ""
    out["text"] = (desc + "\n" + page["text"]).strip() if desc and desc not in page["text"] else page["text"]
    out["images"], out["videos"] = media["images"][:max(24, max_images * 2)], media["videos"]
    host = (urllib.parse.urlsplit(final).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in _VIDEO_HOSTS) and not out["videos"]:
        out["videos"].append({"url": final, "title": out["title"]})
    if out["videos"] and not page["text"]:
        out["kind"] = "video"
    if want_images and out["images"]:
        out["pics"] = _fetch_images_parallel([im["url"] for im in out["images"]], max_images)
    return out


def links_context(urls: List[str], want_images: bool = True, budget: int = 30000, prompt: str = "", transcribe: Optional[Any] = None) -> Dict[str, Any]:
    """Lê vários links (em paralelo) conforme o pedido: {text, items, images}."""
    want = link_intent(prompt)
    url_list = [u for u in (urls or [])[:LINK_MAX] if isinstance(u, str)]

    def one(iu):
        i, u = iu
        r = read_link(u, want_images, want["max_images"])
        host = (urllib.parse.urlsplit(u).hostname or "").removeprefix("www.")
        analyzed = 0
        vid_blocks: List[str] = []
        if r["videos"] and (want["videos"] or r["kind"] == "video"):
            vids = r["videos"][:VIDEO_MAX]
            if len(vids) > 1:
                with ThreadPoolExecutor(max_workers=min(2, len(vids))) as vex:
                    vfuts = {vex.submit(analyze_video, v["url"], transcribe): v for v in vids}
                    vres = {}
                    for fut in as_completed(vfuts):
                        try:
                            vres[id(vfuts[fut])] = fut.result()
                        except Exception:
                            vres[id(vfuts[fut])] = {"text": "", "frames": [], "notes": ["falha ao analisar o vídeo"]}
                analyses = [vres.get(id(v), {"text": "", "frames": [], "notes": []}) for v in vids]
            else:
                analyses = [analyze_video(vids[0]["url"], transcribe)] if vids else []
            for v, a in zip(vids, analyses):
                if a["text"] or a["frames"]:
                    analyzed += 1
                    r["pics"] += a["frames"]
                    vid_blocks.append(f"Vídeo {v['url']}" + (f" — {v['title']}" if v["title"] else "") + (f" ({'; '.join(a['notes'])})" if a["notes"] else "")
                                      + (f"\n{a['text']}" if a["text"] else "") + (f"\n({len(a['frames'])} quadros do vídeo seguem junto desta mensagem)" if a["frames"] else ""))
                else:
                    vid_blocks.append(f"Vídeo {v['url']}" + (f" — {v['title']}" if v["title"] else "") + f" (não analisado: {'; '.join(a['notes']) or 'sem quadros nem áudio'})")
        item = {"n": i, "url": u[:500], "host": host[:80], "title": (r["title"] or host)[:140], "kind": r["kind"], "read": bool(r["text"] or r["pics"] or r["videos"]),
                "images": len(r["images"]), "videos": len(r["videos"]), "analyzed_videos": analyzed, "error": r["error"]}
        lines = [f"[Link {i}] {r['title'] or host}", u]
        if r["error"]:
            lines.append(f"(não consegui abrir: {r['error']})")
        if r["kind"] == "image":
            lines.append("(o link é uma imagem" + ("; ela segue junto desta mensagem)" if r["pics"] else ")"))
        if r["text"]:
            lines.append(r["text"][: max(3000, budget // max(1, len(url_list)))])
        if r["images"] and r["kind"] != "image":
            lines.append("Imagens da página:" + "".join(f"\n  - {im['url']}" + (f" — {im['alt']}" if im["alt"] else "") for im in r["images"][:16]))
            if r["pics"]:
                lines.append(f"({len(r['pics'])} imagens/quadros seguem junto desta mensagem para você ver)")
        if vid_blocks:
            lines.append("Vídeos da página:\n" + "\n".join(vid_blocks))
        elif r["videos"]:
            lines.append("Vídeos da página (não analisados — o usuário não pediu; se precisar, diga que dá para analisar se ele pedir):" + "".join(f"\n  - {v['url']}" + (f" — {v['title']}" if v["title"] else "") for v in r["videos"][:8]))
        return i, "\n".join(lines), item, r["pics"]

    results = {}
    if len(url_list) > 1:
        with ThreadPoolExecutor(max_workers=min(4, len(url_list))) as ex:
            futs = [ex.submit(one, (i, u)) for i, u in enumerate(url_list, 1)]
            for fut in as_completed(futs):
                try:
                    i, block, item, pics = fut.result()
                except Exception:
                    continue
                results[i] = (block, item, pics)
    else:
        for i, u in enumerate(url_list, 1):
            try:
                results[i] = one((i, u))[1:]
            except Exception:
                results[i] = (f"[Link {i}] {u}\n(não consegui ler)", {"n": i, "url": u[:500], "host": "", "title": u[:140], "kind": "page", "read": False, "images": 0, "videos": 0, "analyzed_videos": 0, "error": "erro"}, [])

    parts: List[str] = []
    items: List[Dict[str, Any]] = []
    images: List[Dict[str, str]] = []
    for i in range(1, len(url_list) + 1):
        block, item, pics = results.get(i, ("", {"n": i, "url": "", "host": "", "title": "", "kind": "page", "read": False, "images": 0, "videos": 0, "analyzed_videos": 0, "error": ""}, []))
        parts.append(block)
        items.append(item)
        images += pics
    return {"text": "\n\n".join(parts)[:budget], "items": items, "images": images[:16]}
