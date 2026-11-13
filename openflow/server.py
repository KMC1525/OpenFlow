"""Servidor HTTP do OpenFlow (somente biblioteca padrão).

- Serve a WebUI (openflow/web).
- API JSON em /api/*, com Server-Sent Events para o progresso das gerações e dos downloads.
- Escuta apenas em 127.0.0.1 por padrão; valida Host/Origin (anti DNS-rebinding/CSRF).
"""
from __future__ import annotations

import json
import mimetypes
import re
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__, hf, native, team, voice
from .jobs import HttpError, Job, JobManager  # noqa: F401  (reexportados)
from .providers import ProviderError, build_provider, describe_presets, provider_config
from .routes_preinstalled import PreinstalledRoutes
from .routes_projects import ProjectRoutes
from .storage import Store
from .util import clean_json as _clean_json, hardware_info, safe_filename, text, write_json

WEB_DIR = Path(__file__).parent / "web"

MIME = {
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8", ".md": "text/markdown; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".ogg": "audio/ogg", ".webm": "audio/webm", ".zip": "application/zip", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
    ".mp4": "video/mp4", ".m4a": "audio/mp4", ".webp": "image/webp", ".gif": "image/gif", ".flac": "audio/flac", ".opus": "audio/ogg",
    ".mov": "video/quicktime", ".mkv": "video/x-matroska", ".webmanifest": "application/manifest+json",
}


def _disk_version() -> str:
    """Versão que está instalada em disco agora (lida de openflow/__init__.py). Difere de `__version__` quando o OpenFlow foi atualizado e este processo ainda é o antigo."""
    try:
        m = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", (Path(__file__).parent / "__init__.py").read_text(encoding="utf-8"))
        return m.group(1) if m else __version__
    except OSError:
        return __version__


def guess_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return MIME.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


# --------------------------------------------------------------------------- aplicação


def _native_status() -> dict:
    try:
        st = native.status()
        si = native.sys_info()
        return {"active": st["active"], "cargo": st["cargo"], "models": st.get("models", False), "ops": st.get("ops", False), "abi": st.get("abi", 0), "last": st.get("last", {}),
                "cores": [si.get("physical"), si.get("logical")], "features": si.get("features", [])}
    except Exception:  # noqa: BLE001
        return {"active": False, "cargo": False}


class App:
    def __init__(self, store: Store, bind_host: str = "127.0.0.1"):
        self.store = store
        self.jobs = JobManager(store)
        self.bind_host = bind_host
        self.routes: List[Tuple[str, "re.Pattern[str]", Callable]] = []
        self._register()

    # ----- roteamento
    def add(self, method: str, pattern: str, fn: Callable) -> None:
        self.routes.append((method, re.compile("^" + pattern + "$"), fn))

    def dispatch(self, req: "Request") -> bool:
        for method, rx, fn in self.routes:
            if method != req.method and not (req.method == "HEAD" and method == "GET"):  # HEAD = GET sem corpo
                continue
            m = rx.match(req.path)
            if m:
                fn(req, **m.groupdict())
                return True
        return False

    def host_allowed(self, host_header: str) -> bool:
        host = (host_header or "").strip().lower()
        if host.startswith("["):
            name = host[1:host.find("]")] if "]" in host else host
        else:
            name = host.split(":")[0]
        if name in ("localhost", "127.0.0.1", "::1"):
            return True
        return self.bind_host not in ("127.0.0.1", "localhost", "::1")  # exposto na rede por escolha do usuário (flow --host)

    # ----- helpers de provedor
    def provider(self, role: str = "generation", settings: Optional[dict] = None):
        settings = settings or self.store.get_settings()
        pid = settings["active"].get(role, "demo")
        return build_provider(settings, pid, self.store.models_dir), pid

    def _provider_from_request(self, body: dict):
        settings = self.store.get_settings()
        pid = body.get("id") or "demo"
        cfg = body.get("config") or {}
        override = settings["providers"].setdefault(pid, {})
        for k in ("base_url", "model"):
            if k in cfg and isinstance(cfg[k], str):  # campo vazio vale: testar sem modelo escolhido (ex.: LM Studio em automático) não pode herdar o salvo
                override[k] = cfg[k].strip()
        if cfg.get("api_key"):
            override["api_key"] = cfg["api_key"]
        if "vision" in cfg:
            override["vision"] = bool(cfg["vision"])
        if cfg.get("n_ctx"):
            override["n_ctx"] = cfg["n_ctx"]
        return build_provider(settings, pid, self.store.models_dir)

    # ------------------------------------------------------------------ rotas
    def _register(self) -> None:
        a = self.add
        a("GET", r"/api/state", self.r_state)
        a("GET", r"/api/settings", self.r_settings_get)
        a("GET", r"/api/team", self.r_team)
        a("PUT", r"/api/settings", self.r_settings_put)
        a("GET", r"/api/settings/export", self.r_settings_export)
        a("POST", r"/api/settings/import", self.r_settings_import)
        a("POST", r"/api/settings/reset", self.r_settings_reset)
        a("POST", r"/api/providers/test", self.r_provider_test)
        a("POST", r"/api/providers/models", self.r_provider_models)
        a("GET", r"/api/lmstudio", self.r_lmstudio)
        a("POST", r"/api/lmstudio/scan", self.r_lmstudio_scan)

        a("POST", r"/api/uploads", self.r_upload)
        a("DELETE", r"/api/uploads/(?P<uid>[\w-]+)", self.r_upload_delete)
        a("GET", r"/api/jobs/(?P<jid>[\w-]+)", self.r_job_get)
        a("GET", r"/api/jobs", self.r_jobs)
        a("GET", r"/api/jobs/(?P<jid>[\w-]+)/events", self.r_job_events)
        a("POST", r"/api/jobs/(?P<jid>[\w-]+)/cancel", self.r_job_cancel)

        a("GET", r"/api/hf/search", self.r_hf_search)
        a("GET", r"/api/hf/files", self.r_hf_files)
        a("GET", r"/api/hf/local", self.r_hf_local)
        a("POST", r"/api/hf/download", self.r_hf_download)
        a("DELETE", r"/api/hf/local/(?P<name>[^/]+)", self.r_hf_delete)
        a("GET", r"/api/models/support", self.r_support_status)
        a("POST", r"/api/models/support/install", self.r_support_install)

        a("POST", r"/api/voice/tts", self.r_tts)
        a("POST", r"/api/voice/stt", self.r_stt)

        self.project_routes = ProjectRoutes(self)
        self.project_routes.register()
        self.preinstalled_routes = PreinstalledRoutes(self)
        self.preinstalled_routes.register()

    # ----- estado / configurações
    def r_state(self, req: "Request") -> None:
        s = self.store.get_settings()
        req.json({
            "version": __version__, "disk_version": _disk_version(), "hardware": hardware_info(), "native": _native_status(), "home": str(self.store.home),
            "presets": describe_presets(), "settings": self.store.public_settings(),
            "configured": [pid for pid in s["providers"] if s["providers"][pid].get("api_key") or s["providers"][pid].get("model") or s["providers"][pid].get("base_url")],
        })

    def r_team(self, req: "Request") -> None:
        """As opções de equipe: 1/2/4/8/12/16/20/24/28/32 agentes e os oito níveis de esforço (Low … Omni)."""
        req.json(team.options())

    def r_settings_get(self, req: "Request") -> None:
        req.json(self.store.public_settings())

    def r_settings_put(self, req: "Request") -> None:
        body = req.body_json()
        if not isinstance(body, dict):
            raise HttpError(400, "JSON inválido")
        self.store.save_settings(body)
        req.json(self.store.public_settings())

    def r_settings_export(self, req: "Request") -> None:
        """Baixa as configurações como arquivo, sem chaves de API nem tokens."""
        from . import uiprefs

        data = uiprefs.export_settings(self.store.get_settings())
        req.bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8")

    def r_settings_import(self, req: "Request") -> None:
        from . import uiprefs

        body = req.body_json()
        try:
            patch = uiprefs.import_patch(body)
        except ValueError as exc:
            raise HttpError(400, str(exc))
        self.store.save_settings(patch)
        req.json({"imported": sorted(patch), "settings": self.store.public_settings()})

    def r_settings_reset(self, req: "Request") -> None:
        """Volta uma seção das configurações ao padrão (ui, generation, canvas, performance). Chaves de API nunca são tocadas."""
        import copy

        from . import uiprefs
        from .storage import DEFAULT_SETTINGS

        body = req.body_json()
        section = str(body.get("section") or "") if isinstance(body, dict) else ""
        if section not in uiprefs.RESETTABLE:
            raise HttpError(400, "Seção inválida. Opções: " + ", ".join(uiprefs.RESETTABLE))
        with self.store._lock:
            current = self.store.get_settings()
            current[section] = copy.deepcopy(DEFAULT_SETTINGS[section])
            if section == "ui":
                current["ui"]["welcome_done"] = True  # restaurar a aparência não reabre as boas-vindas
            write_json(self.store.settings_path, current, private=True)
        req.json(self.store.public_settings())

    def r_provider_test(self, req: "Request") -> None:
        body = req.body_json()
        try:
            provider = self._provider_from_request(body)
            started = time.time()
            reply = provider.test()
            req.json({"ok": True, "reply": reply, "ms": int((time.time() - started) * 1000), "model": provider.model})
        except ProviderError as exc:
            req.json({"ok": False, "error": str(exc)})

    def r_provider_models(self, req: "Request") -> None:
        body = req.body_json()
        try:
            provider = self._provider_from_request(body)
            req.json({"ok": True, "models": provider.list_models()})
        except ProviderError as exc:
            req.json({"ok": False, "error": str(exc), "models": []})

    def r_lmstudio(self, req: "Request") -> None:
        """Estado do LM Studio agora: servidor rodando?, modelos de chat (carregados primeiro) e o que o OpenFlow vai usar."""
        from .providers import lmstudio

        cfg = provider_config(self.store.get_settings(), "lmstudio")
        info = lmstudio.probe(req.query.get("url", [""])[0] or cfg.get("base_url") or "", cfg.get("api_key") or "", timeout=3)
        lmstudio.forget()  # o usuário acabou de pedir: o cache não pode esconder o que mudou (ligou o servidor, carregou um modelo)
        info["selected"] = cfg.get("model") or (info["loaded"][0] if info["loaded"] else "")
        info["hint"] = lmstudio.HOW_TO_START
        req.json(info)

    def r_lmstudio_scan(self, req: "Request") -> None:
        """Procura o LM Studio de outro computador na rede local (a pedido do usuário)."""
        from .providers import lmstudio

        req.body_json()
        req.json({"servers": lmstudio.scan()})

    # ----- uploads
    def r_upload(self, req: "Request") -> None:
        settings = self.store.get_settings()
        limit = int(settings["server"].get("max_upload_mb", 200)) * 1024 * 1024
        length = req.content_length()
        if length > limit:
            raise HttpError(413, f"Arquivo maior que o limite de {limit // 1024 // 1024} MB")
        name = urllib.parse.unquote(req.headers.get("X-Filename", "arquivo"))
        meta = self.store.save_upload_stream(name, req.headers.get("Content-Type", ""), req.rfile, length)
        req.json(meta)

    def r_upload_delete(self, req: "Request", uid: str) -> None:
        req.json({"ok": self.store.delete_upload(uid)})

    # ----- tarefas em segundo plano
    def r_job_get(self, req: "Request", jid: str) -> None:
        job = self.jobs.get(jid)
        if not job:
            raise HttpError(404, "Tarefa não encontrada")
        req.json({"id": job.id, "kind": job.kind, "status": job.status, "events": job.total})

    def r_jobs(self, req: "Request") -> None:
        """As tarefas em segundo plano (as que rodam primeiro, depois as mais novas). `?status=running` filtra."""
        want = (req.query.get("status", [""])[0] or "").strip()
        with self.jobs.lock:
            items = list(self.jobs.jobs.values())
        items = [j for j in items if not want or j.status == want]
        items.sort(key=lambda j: (j.status != "running", -j.created))
        req.json({"jobs": [{"id": j.id, "kind": j.kind, "status": j.status, "events": j.total, "created": j.created} for j in items[:100]],
                  "running": sum(1 for j in items if j.status == "running")})

    def r_job_cancel(self, req: "Request", jid: str) -> None:
        job = self.jobs.get(jid)
        if not job:
            raise HttpError(404, "Tarefa não encontrada")
        job.cancel()
        req.json({"ok": True})

    def r_job_events(self, req: "Request", jid: str) -> None:
        job = self.jobs.get(jid)
        if not job:
            raise HttpError(404, "Tarefa não encontrada")
        raw = (req.query.get("from", [""])[0] or "").strip() or str(req.h.headers.get("Last-Event-ID") or "").strip()   # o navegador reconecta sozinho mandando o último id
        idx = int(raw) if raw.isdigit() else 0
        req.sse_start()
        while True:
            with job.cond:
                idx = max(idx, job.base)   # pediu um trecho já descartado: segue do mais antigo que existe
                while idx >= job.total and job.status == "running":
                    job.cond.wait(timeout=10)
                    if idx >= job.total and job.status == "running":
                        break
                batch = job.since(idx)
                status = job.status
            for ev in batch:
                req.sse_send(ev, ev.get("seq", idx) + 1)
            idx += len(batch)
            if not batch and status == "running":
                req.sse_comment("keepalive")
            if status != "running" and idx >= job.total:
                req.sse_send({"type": "end", "status": status})
                return

    # ----- modelos do Hugging Face
    def _hf_token(self) -> str:
        return self.store.get_settings()["hf"].get("token", "")

    def _auto_support(self) -> bool:
        return self.store.get_settings()["hf"].get("auto_support", True) is not False

    def r_hf_search(self, req: "Request") -> None:
        q = (req.query.get("q", [""])[0] or "gguf").strip()
        try:
            req.json({"results": hf.search(q, self._hf_token(), kind=hf.check_kind(req.query.get("kind", ["text"])[0] or "text"))})
        except ProviderError as exc:
            raise HttpError(502, str(exc))

    def r_hf_files(self, req: "Request") -> None:
        """As quantizações de um repositório + os arquivos de apoio (VAE, codificadores de texto, mmproj) que serão baixados junto do modelo."""
        from .canvas import support

        repo = req.query.get("repo", [""])[0]
        kind = req.query.get("kind", [""])[0]
        try:
            tree = hf.repo_files(repo, self._hf_token())
            files = hf.group_files([f for f in tree if f["name"].lower().endswith(".gguf") and hf.FILE_RE.match(Path(f["name"]).name)], hardware_info().get("ram_gb") or 0)
        except ProviderError as exc:
            raise HttpError(502, str(exc))
        out: Dict[str, Any] = {"files": files, "support": []}
        if files and self._auto_support():
            main = next((f for f in files if f.get("recommended")), files[0])
            k = kind if kind in hf.GGUF_KINDS else ("text" if not support.family_of(main["name"]) else "image")
            info = support.plan(hf.kind_dir(self.store.models_dir, k), Path(main["name"]).name, k, repo, tree)
            out["support"] = [{"role": i["role"], "label": i["label"], "size": i["size"]} for i in info["items"]]
        req.json(out)

    def r_hf_local(self, req: "Request") -> None:
        kind = req.query.get("kind", ["text"])[0] or "text"  # sem `kind`: só os de texto (o que o provedor de IA lista)
        try:
            models = hf.local_models(self.store.models_dir, kind if kind == "all" else hf.check_kind(kind))
            for m in models:
                if m.get("kind") == "text":   # contexto em que o modelo foi treinado e custo do cache de atenção (lidos do cabeçalho, sem carregar os pesos)
                    info = native.model_info(hf.kind_dir(self.store.models_dir, "text") / m["name"]) or {}
                    m["ctx_train"], m["kv_bytes_per_token"] = int(info.get("ctx_train") or 0), int(info.get("kv_bytes_per_token") or 0)
            req.json({"models": models, "kinds": {k: v["label"] for k, v in hf.GGUF_KINDS.items()}})
        except ProviderError as exc:
            raise HttpError(400, str(exc))

    def r_hf_delete(self, req: "Request", name: str) -> None:
        from .canvas import support

        name = urllib.parse.unquote(name)
        try:
            folder = hf.kind_dir(self.store.models_dir, req.query.get("kind", ["text"])[0] or "text")
        except ProviderError as exc:
            raise HttpError(400, str(exc))
        path = folder / safe_filename(name)
        if not path.exists() or path.suffix != ".gguf":
            raise HttpError(404, "Modelo não encontrado")
        for p in hf.shard_files(folder, path.name):  # modelo dividido: apaga todas as partes
            p.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        mm = support.mmproj_for(folder, path.name)   # o projetor de visão é só deste modelo
        if mm:
            mm.unlink(missing_ok=True)
        req.json({"ok": True})

    def r_hf_download(self, req: "Request") -> None:
        """Baixa um modelo e, junto, o VAE, os codificadores de texto e o mmproj de que ele precisa (a menos que `hf.auto_support` esteja desligado)."""
        from .canvas import support

        body = req.body_json()
        repo = text(body.get("repo"), "", 200)
        if not text(body.get("quant"), "", 40):  # o OpenFlow nunca escolhe a quantização pelo usuário
            raise HttpError(400, "Escolha a quantização antes de baixar (campo quant, ex.: Q4_K_M).")
        names = [text(f, "", 260) for f in body.get("files")][:99] if isinstance(body.get("files"), list) else [text(body.get("file"), "", 260)]
        names = [n for n in names if n]
        if not names:
            raise HttpError(400, "Escolha uma quantização para baixar.")
        try:
            kind = text(body.get("kind"), "text", 8) or "text"
            dest = hf.kind_dir(self.store.models_dir, kind, create=True)
        except ProviderError as exc:
            raise HttpError(400, str(exc))
        sizes = {n: int(body["sizes"].get(n, 0)) for n in names} if isinstance(body.get("sizes"), dict) and all(isinstance(v, (int, float)) for v in body["sizes"].values()) else {}
        auto = self._auto_support() and body.get("support") is not False

        def work(job: Job) -> None:
            job.emit({"type": "start", "file": names[0], "parts": len(names)})
            last = [0.0]

            def progress(done: int, total: int) -> None:
                if time.time() - last[0] > 0.4:
                    last[0] = time.time()
                    job.emit({"type": "progress", "done": done, "total": total})

            path = hf.download_many(repo, names, dest, self._hf_token(), sizes, progress, lambda: job.cancelled)
            extra: List[str] = []
            failed: List[Dict[str, str]] = []
            if auto and path.suffix.lower() == ".gguf":
                try:
                    tree = hf.repo_files(repo, self._hf_token())
                except ProviderError:
                    tree = []   # sem a lista do repositório só vale a família conhecida
                info = support.plan(dest, path.name, kind, repo, tree)
                if info["items"]:
                    job.emit({"type": "note", "message": "Baixando também os arquivos de apoio: " + ", ".join(i["label"] for i in info["items"]) + f" (≈ {info['total_bytes'] / 1024 ** 3:.1f} GB)…"})
                    job.emit({"type": "support", "items": [{"role": i["role"], "label": i["label"], "size": i["size"]} for i in info["items"]]})
                    res = support.install_with_model(dest, path.name, kind, repo, self._hf_token(), tree, progress, lambda: job.cancelled, lambda m: job.emit({"type": "note", "message": m}))
                    extra, failed = res["installed"], res["failed"]
                    for f in failed:   # o modelo já está baixado: a falha dos apoios não o desfaz (o botão «Baixar os arquivos de apoio» refaz)
                        job.emit({"type": "note", "message": f"Não baixou {f['label']}: {f['error']}"})
            job.emit({"type": "done", "name": path.name, "support": extra, "support_failed": failed})

        job = self.jobs.start("download", work)
        req.json({"job_id": job.id})

    def r_support_status(self, req: "Request") -> None:
        """Os arquivos de apoio (VAE, codificadores de texto, mmproj) de cada modelo de imagem, vídeo e texto instalado: o que tem e o que falta. Sem rede."""
        from .canvas import support

        out = []
        for kind in ("image", "video", "text"):
            folder = hf.kind_dir(self.store.models_dir, kind)
            for m in hf.local_models(self.store.models_dir, kind):
                st = support.status_of(folder, m["name"], kind)
                if st["family"] or st["have"] or st["missing"]:
                    out.append({"kind": kind, "name": m["name"], **st})
        req.json({"models": out, "auto": self._auto_support()})

    def r_support_install(self, req: "Request") -> None:
        """Instala o que falta de arquivos de apoio de um modelo já baixado (`kind` + `name`) ou de todos (sem `name`)."""
        from .canvas import support

        body = req.body_json()
        kind, name = text(body.get("kind"), "", 8), text(body.get("name"), "", 260)
        todo = []
        for k in (kind,) if kind else ("image", "video", "text"):
            try:
                folder = hf.kind_dir(self.store.models_dir, k, create=True)
            except ProviderError as exc:
                raise HttpError(400, str(exc))
            for m in hf.local_models(self.store.models_dir, k):
                if not name or m["name"] == name:
                    todo.append((k, folder, m["name"]))
        if not todo:
            raise HttpError(404, "Modelo não encontrado.")
        running = self.jobs.running("support_files")
        if running:
            raise HttpError(409, json.dumps({"job_id": running.id}))
        token = self._hf_token()

        def work(job: Job) -> None:
            job.emit({"type": "start"})
            last = [0.0]

            def progress(done: int, total: int) -> None:
                if time.time() - last[0] > 0.4:
                    last[0] = time.time()
                    job.emit({"type": "progress", "done": done, "total": total})

            got: List[str] = []
            failed: List[Dict[str, str]] = []
            for k, folder, fname in todo:
                guess = support.family_of(fname)
                if k in ("image", "video") and not guess:
                    continue   # sem família conhecida e sem repositório de origem: nada a baixar por aqui
                res = support.install_with_model(folder, fname, k, "", token, None, progress, lambda: job.cancelled, lambda m: job.emit({"type": "note", "message": m}))
                got += res["installed"]
                failed += res["failed"]
            job.emit({"type": "done", "files": got, "failed": failed})

        job = self.jobs.start("support_files", work)
        req.json({"job_id": job.id})

    # ----- voz
    def r_tts(self, req: "Request", pid: str = "") -> None:
        body = req.body_json()
        try:
            audio, mime = voice.synthesize(self.store.get_settings(), text(body.get("text"), "", 2000), text(body.get("voice"), "", 60))
        except ProviderError as exc:
            raise HttpError(502, str(exc))
        req.bytes(audio, mime)

    def r_stt(self, req: "Request", pid: str = "") -> None:
        data = req.body_bytes(30 * 1024 * 1024)
        mime = req.headers.get("Content-Type", "audio/webm").split(";")[0]
        ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(mime, "webm")
        try:
            txt = voice.transcribe_bytes(self.store.get_settings(), data, f"audio.{ext}", mime, req.headers.get("X-Lang", ""))
        except ProviderError as exc:
            raise HttpError(502, str(exc))
        req.json({"text": txt})

    # ----- web ui estática
    def serve_static(self, req: "Request") -> None:
        rel = urllib.parse.unquote(req.path.lstrip("/")) or "index.html"
        if rel == "sw.js":  # service worker, carimbado com a versão (muda quando o OpenFlow é atualizado)
            data = (WEB_DIR / "sw.js").read_text(encoding="utf-8").replace("__OPENFLOW_VERSION__", __version__).encode("utf-8")
            req._head(200, "text/javascript; charset=utf-8", len(data), {"Service-Worker-Allowed": "/"})
            if req.method != "HEAD":
                req.h.wfile.write(data)
            return
        if "\x00" in rel:   # byte nulo no endereço: o sistema de arquivos levantaria ValueError (erro 500)
            raise HttpError(404, "Não encontrado")
        target = (WEB_DIR / rel).resolve()
        if not _under(target, WEB_DIR) or not target.is_file():
            if "." in rel.rsplit("/", 1)[-1]:
                raise HttpError(404, "Não encontrado")
            target = WEB_DIR / "index.html"
        req.file(target, guess_mime(str(target)))


# --------------------------------------------------------------------------- requisição


def _under(target: Path, root: Path) -> bool:
    """`target` está dentro de `root`? (comparação por pastas, não por prefixo de texto: «/x/web2» não está dentro de «/x/web».)"""
    root = Path(root).resolve()
    return target == root or root in target.parents


def _as_list(v):
    """Lista vinda do JSON do navegador/API: qualquer outra coisa vira lista vazia (em vez de um erro 500)."""
    return v if isinstance(v, list) else []


class Request:
    def __init__(self, handler: "Handler", method: str):
        self.h = handler
        self.method = method
        parsed = urllib.parse.urlsplit(handler.path)
        self.path = parsed.path
        self.query = urllib.parse.parse_qs(parsed.query)
        self.headers = handler.headers
        self.rfile = handler.rfile
        self._sse = False

    # entrada
    def content_length(self) -> int:
        try:
            return max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            return 0

    def body_bytes(self, limit: int = 8 * 1024 * 1024) -> bytes:
        n = self.content_length()
        if n > limit:
            raise HttpError(413, "Corpo da requisição muito grande")
        self._body_read = True
        return self.rfile.read(n) if n else b""

    def body_json(self, limit: int = 8 * 1024 * 1024) -> Any:
        raw = self.body_bytes(limit)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):   # RecursionError: «[[[[…» com milhares de níveis
            raise HttpError(400, "JSON inválido")
        if not isinstance(data, dict):  # todas as rotas esperam um objeto: lista/texto/número virariam um erro 500 lá dentro
            raise HttpError(400, "JSON inválido: esperava um objeto {…}")
        try:
            return _clean_json(data)
        except ValueError:
            raise HttpError(400, "JSON inválido: aninhado fundo demais")

    # saída
    def _head(self, status: int, mime: str, length: Optional[int], extra: Optional[Dict[str, str]] = None) -> None:
        h = self.h
        h.send_response(status)
        headers = {"Content-Type": mime, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
        if length is not None:
            headers["Content-Length"] = str(length)
        headers.update(extra or {})  # `extra` pode sobrescrever (ex.: Cache-Control de mídias imutáveis)
        for k, v in headers.items():
            h.send_header(k, v)
        h.end_headers()

    def json(self, obj: Any, status: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._head(status, "application/json; charset=utf-8", len(data))
        if self.method != "HEAD":
            self.h.wfile.write(data)

    def bytes(self, data: bytes, mime: str, status: int = 200, headers: Optional[Dict[str, str]] = None) -> None:
        self._head(status, mime, len(data), headers)
        if self.method != "HEAD":
            self.h.wfile.write(data)

    def file(self, path: Path, mime: str, download_name: str = "", cache: bool = False, headers: Optional[Dict[str, str]] = None) -> None:
        """Envia um arquivo, com suporte a `Range` (necessário p/ buscar em <video>/<audio>)."""
        size = path.stat().st_size
        extra = {"Accept-Ranges": "bytes"}
        if cache:  # arquivos com id único (nunca mudam)
            extra["Cache-Control"] = "private, max-age=3600"
        if download_name:
            extra["Content-Disposition"] = f'attachment; filename="{safe_filename(download_name)}"'
        extra.update(headers or {})
        status, start, end = 200, 0, size - 1
        rng = (self.headers.get("Range") or "").strip()
        m = re.match(r"^bytes=(\d*)-(\d*)$", rng)
        if m and size and (m.group(1) or m.group(2)):
            a, b = m.groups()
            if not a:  # sufixo: os últimos N bytes
                start, end = max(0, size - int(b)), size - 1
            else:
                start, end = int(a), min(int(b), size - 1) if b else size - 1
            if start > end or start >= size:
                self._head(416, "text/plain", 0, {"Content-Range": f"bytes */{size}"})
                return
            status = 206
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = max(0, end - start + 1) if size else 0
        self._head(status, mime, length, extra)
        if self.method == "HEAD":
            return
        with open(path, "rb") as fh:
            fh.seek(start)
            left = length
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                self.h.wfile.write(chunk)
                left -= len(chunk)

    def static(self, root: Path, rel: str) -> None:
        if "\x00" in rel:
            raise HttpError(404, "Arquivo não encontrado")
        target = (root / rel).resolve()
        if not _under(target, root) or not target.is_file():
            raise HttpError(404, "Arquivo não encontrado")
        self.file(target, guess_mime(rel))

    def redirect(self, url: str) -> None:
        self._head(302, "text/plain", 0, {"Location": url})

    def sse_start(self) -> None:
        if not getattr(self, "_body_read", False):  # corpo não lido (ex.: «regenerar» manda {}): fechar o socket com dados pendentes dá RST (macOS) e corta a resposta
            try:
                n = self.content_length()
                if 0 < n <= 1024 * 1024:
                    self._body_read = True
                    self.rfile.read(n)
            except (HttpError, OSError, ValueError):
                pass
        self._sse = True
        self.h.send_response(200)
        self.h.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.h.send_header("Cache-Control", "no-cache, no-transform")
        self.h.send_header("X-Accel-Buffering", "no")
        self.h.send_header("Connection", "close")
        self.h.end_headers()
        self.h.wfile.flush()

    def sse_send(self, obj: Any, event_id: Optional[int] = None) -> None:
        head = b"id: %d\n" % event_id if isinstance(event_id, int) else b""   # com `id`, a reconexão automática do navegador continua de onde parou
        self.h.wfile.write(head + b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n")
        self.h.wfile.flush()

    def sse_comment(self, text_: str) -> None:
        self.h.wfile.write(f": {text_}\n\n".encode("utf-8"))
        self.h.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "OpenFlow/" + __version__
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:  # silencioso; erros vão para stderr via handler
        pass

    def _handle(self, method: str) -> None:
        req = Request(self, method)
        try:
            if not self.app.host_allowed(self.headers.get("Host", "")):
                raise HttpError(403, "Host não permitido")
            if method in ("POST", "PUT", "DELETE"):
                origin = self.headers.get("Origin")
                if origin:
                    if urllib.parse.urlsplit(origin).netloc != self.headers.get("Host", ""):
                        raise HttpError(403, "Origem não permitida")
            path = req.path
            if path.startswith("/api/"):
                if not self.app.dispatch(req):
                    raise HttpError(404, "Rota não encontrada")
            elif method in ("GET", "HEAD"):
                self.app.serve_static(req)
            else:
                raise HttpError(405, "Método não permitido")
        except HttpError as exc:
            if req._sse:
                return
            payload: Any = {"error": exc.message}
            if exc.status == 409:
                try:
                    payload.update(json.loads(exc.message))
                except ValueError:
                    pass
            req.json(payload, exc.status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            if not req._sse:
                try:
                    req.json({"error": f"Erro interno: {exc}"}, 500)
                except OSError:
                    pass

    def do_GET(self) -> None:
        self._handle("GET")

    def do_HEAD(self) -> None:
        self._handle("HEAD")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64
    app: Optional["App"] = None


def make_server(host: str, port: int, store: Optional[Store] = None) -> Tuple[Server, App]:
    store = store or Store()
    app = App(store, host)

    class BoundHandler(Handler):
        pass

    BoundHandler.app = app
    httpd = Server((host, port), BoundHandler)
    httpd.app = app
    return httpd, app
