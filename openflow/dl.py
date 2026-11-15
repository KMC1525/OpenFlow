"""Download rápido de arquivos grandes (modelos): várias conexões em paralelo (faixas `Range`), retomada e novas tentativas automáticas (v0.25).

Um arquivo de vários GB por uma só conexão costuma ficar muito abaixo da velocidade da internet (o servidor limita cada conexão). Aqui o arquivo é dividido em faixas baixadas ao mesmo tempo
para um `.part` pré-alocado; um arquivo `.seg` ao lado guarda quanto de cada faixa já chegou, então fechar o OpenFlow no meio e baixar de novo continua de onde parou. Se o servidor não aceita `Range`
(ou o arquivo é pequeno), cai no download de uma conexão só, que também retoma sozinho depois de uma queda de rede.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .providers import http
from .providers.base import ProviderError

MIN_SEGMENT = 32 << 20     # não vale dividir em faixas menores que isto
MIN_PARALLEL = 64 << 20    # arquivos menores baixam por uma conexão só
CHUNK = 1 << 20
RETRIES = 6
DEFAULT_CONNECTIONS = 4
MAX_CONNECTIONS = 8


class _NoRange(Exception):
    """O servidor não respeitou o pedido de faixa: usa o download de uma conexão."""


def clamp_connections(n: object) -> int:
    try:
        return max(1, min(MAX_CONNECTIONS, int(n)))  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return DEFAULT_CONNECTIONS


def _backoff(attempt: int, cancelled: Callable[[], bool]) -> None:
    end = time.time() + min(2 ** attempt, 20)
    while time.time() < end:
        if cancelled():
            raise ProviderError("cancelado")
        time.sleep(0.2)


def probe(url: str, headers: Dict[str, str], keep: bool = False) -> Tuple[str, int, bool, object]:
    """(endereço final depois dos redirecionamentos, tamanho total, aceita faixas?, resposta). Pede só o primeiro byte. Se o servidor ignora a faixa e manda o arquivo inteiro e `keep` é verdadeiro,
    a resposta continua aberta (e é devolvida) para o download de uma conexão aproveitá-la, sem pedir de novo; nos outros casos é fechada e a resposta é None."""
    resp = http.request(url, headers={**headers, "Range": "bytes=0-0"}, timeout=60)
    final = resp.geturl() or url
    m = re.match(r"bytes\s+\d+-\d+/(\d+)", resp.headers.get("Content-Range") or "")
    if resp.status == 206 and m:
        resp.close()
        return final, int(m.group(1)), True, None
    total = int(resp.headers.get("Content-Length") or 0)
    if keep and resp.status == 200:
        return final, total, False, resp
    resp.close()
    return final, total, False, None


def _segment_headers(url: str, final: str, headers: Dict[str, str]) -> Dict[str, str]:
    """O endereço final costuma ser de um CDN com a assinatura na própria URL: a credencial do Hugging Face só vai se o servidor for o mesmo."""
    if urllib.parse.urlsplit(final).netloc == urllib.parse.urlsplit(url).netloc:
        return dict(headers)
    return {k: v for k, v in headers.items() if k.lower() != "authorization"}


def _plan(total: int, connections: int) -> List[Tuple[int, int]]:
    n = max(1, min(connections, total // MIN_SEGMENT))
    size = -(-total // n)
    return [(i * size, min(total, (i + 1) * size) - 1) for i in range(n) if i * size < total]


def _sidecar(part: Path) -> Path:
    return part.with_name(part.name + ".seg")


def _load_state(part: Path, total: int, segs: List[Tuple[int, int]]) -> List[int]:
    try:
        d = json.loads(_sidecar(part).read_text())
        if d.get("total") == total and d.get("segs") == [list(s) for s in segs] and part.exists() and part.stat().st_size == total:
            return [max(0, min(int(x), e - s + 1)) for x, (s, e) in zip(d["done"], segs)]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return [0] * len(segs)


def _save_state(part: Path, total: int, segs: List[Tuple[int, int]], done: List[int]) -> None:
    try:
        tmp = _sidecar(part).with_suffix(".tmp")
        tmp.write_text(json.dumps({"total": total, "segs": [list(s) for s in segs], "done": done}))
        os.replace(tmp, _sidecar(part))
    except OSError:
        pass


def single(url: str, part: Path, headers: Dict[str, str], progress: Optional[Callable[[int, int], None]], cancelled: Callable[[], bool], first: object = None) -> int:
    """Uma conexão, retomando do `.part`; se a rede cai, tenta de novo (até `RETRIES` vezes) a partir do que já chegou."""
    attempt = 0
    total = 0
    while True:
        start = part.stat().st_size if part.exists() else 0
        hdrs = dict(headers)
        if start:
            hdrs["Range"] = f"bytes={start}-"
        try:
            if first is not None and not start:   # a resposta do teste de faixas já é o arquivo inteiro: aproveita
                resp, first = first, None
            else:
                resp = http.request(url, headers=hdrs, timeout=60)
        except ProviderError as exc:
            if getattr(exc, "status", None) == 416 and start:   # o .part já tem o arquivo inteiro
                return start
            st = getattr(exc, "status", None)
            transient = st in (429, 500, 502, 503, 504) or (st is None and start > 0)   # sem internet logo de cara: avisa já; já tinha começado: a rede pode voltar
            if attempt >= RETRIES or not transient:
                raise
            attempt += 1
            _backoff(attempt, cancelled)
            continue
        try:
            total = int(resp.headers.get("Content-Length") or 0)
            if resp.status == 206:
                total += start
            else:
                start = 0
            done = start
            with open(part, "ab" if start else "wb") as fh:
                while True:
                    if cancelled():
                        raise ProviderError("cancelado")
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            if total and done < total:
                raise OSError("conexão encerrada antes do fim")
            return done
        except (OSError, ProviderError) as exc:   # queda de rede no meio: retoma
            if isinstance(exc, ProviderError) and str(exc) == "cancelado":
                raise
            if attempt >= RETRIES:
                raise ProviderError(f"A conexão caiu e não voltou depois de {RETRIES} tentativas: {exc}") from None
            attempt += 1
            _backoff(attempt, cancelled)
        finally:
            resp.close()


def parallel(url: str, final: str, total: int, part: Path, headers: Dict[str, str], connections: int,
             progress: Optional[Callable[[int, int], None]], cancelled: Callable[[], bool]) -> int:
    segs = _plan(total, connections)
    done = _load_state(part, total, segs)
    if not any(done):   # começo do zero (ou estado inválido): pré-aloca o arquivo
        with open(part, "wb") as fh:
            fh.truncate(total)
    lock = threading.Lock()
    stop = threading.Event()
    errors: List[BaseException] = []
    cur = {"final": final}

    def worker(i: int) -> None:
        s, e = segs[i]
        attempt = 0
        try:
            with open(part, "r+b") as fh:
                while not stop.is_set():
                    with lock:
                        pos = s + done[i]
                    if pos > e:
                        return
                    try:
                        resp = http.request(cur["final"], headers={**_segment_headers(url, cur["final"], headers), "Range": f"bytes={pos}-{e}"}, timeout=60)
                    except ProviderError as exc:
                        if getattr(exc, "status", None) in (401, 403, 410) and attempt < RETRIES:   # assinatura do CDN venceu: pede o endereço de novo
                            attempt += 1
                            cur["final"] = probe(url, headers)[0]
                            continue
                        raise
                    try:
                        if resp.status != 206:
                            raise _NoRange()
                        fh.seek(pos)
                        while not stop.is_set():
                            chunk = resp.read(CHUNK)
                            if not chunk:
                                break
                            n = min(len(chunk), e - (s + done[i]) + 1)
                            fh.write(chunk[:n])
                            with lock:
                                done[i] += n
                            if s + done[i] > e:
                                break
                        attempt = 0 if s + done[i] > e else attempt
                    except OSError:
                        pass   # queda no meio da faixa: abaixo tenta de novo do ponto em que parou
                    finally:
                        resp.close()
                    with lock:
                        finished = s + done[i] > e
                    if not finished and not stop.is_set():
                        attempt += 1
                        if attempt > RETRIES:
                            raise ProviderError("A conexão caiu e não voltou depois de várias tentativas.")
                        _backoff(attempt, lambda: stop.is_set())
        except BaseException as exc:  # noqa: BLE001 — repassa à thread principal
            errors.append(exc)
            stop.set()

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(len(segs))]
    for t in threads:
        t.start()
    last_save = 0.0
    try:
        while any(t.is_alive() for t in threads):
            if cancelled():
                stop.set()
                raise ProviderError("cancelado")
            time.sleep(0.25)
            with lock:
                got = sum(done)
            if progress:
                progress(got, total)
            if time.time() - last_save > 2:
                last_save = time.time()
                with lock:
                    _save_state(part, total, segs, list(done))
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)
        with lock:
            snapshot = list(done)
        _save_state(part, total, segs, snapshot)   # cancelou ou falhou: guarda o que chegou para retomar
    if errors:
        raise errors[0]
    if sum(done) < total:
        raise ProviderError("O download terminou incompleto.")
    _sidecar(part).unlink(missing_ok=True)
    if progress:
        progress(total, total)
    return total


def fetch(url: str, part: Path, headers: Dict[str, str], connections: int = DEFAULT_CONNECTIONS,
          progress: Optional[Callable[[int, int], None]] = None, cancelled: Callable[[], bool] = lambda: False) -> int:
    """Baixa `url` para `part` (arquivo parcial) e devolve o tamanho. O chamador renomeia o `.part` para o nome final."""
    connections = clamp_connections(connections)
    legacy = part.exists() and not _sidecar(part).exists() and part.stat().st_size > 0   # .part de uma conexão só (versões antigas): continua do mesmo jeito
    first = None
    if connections > 1 and not legacy:
        try:
            final, total, ranged, first = probe(url, headers, keep=True)
        except ProviderError as exc:
            if getattr(exc, "status", None) in (401, 403, 404):
                raise
            final, total, ranged = url, 0, False
        if ranged and total >= MIN_PARALLEL:
            try:
                return parallel(url, final, total, part, headers, connections, progress, cancelled)
            except _NoRange:
                part.unlink(missing_ok=True)
                _sidecar(part).unlink(missing_ok=True)
    return single(url, part, headers, progress, cancelled, first)
