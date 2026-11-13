"""Rotas HTTP dos projetos: documentos, execução (job + SSE), mídias do projeto, pastas de estilo e provedores de mídia."""
from __future__ import annotations

import json
import mimetypes
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, Dict

from .canvas.engine import CanvasEngine
from .canvas.flow import FlowPipeline
from . import archives
from . import team as teamlib
from .canvas.media import MIME_EXT, build_media, describe_media_presets, sniff_mime
from .canvas.schema import ASPECTS, CAPS, NODE_TYPES, SIZES, TEMPLATES, VIDEO_RESOLUTIONS, describe_types, find_folder, normalize_params, normalize_result
from .jobs import HttpError, Job
from .providers import ProviderError
from .hf import REPO_RE
from .util import hardware_info, new_id, safe_filename, text


class ProjectRoutes:
    def __init__(self, app: Any):
        self.app = app
        self.store = app.store
        self.cs = app.store.projects

    def register(self) -> None:
        a = self.app.add
        a("GET", r"/api/project-templates", self.r_templates)
        a("GET", r"/api/projects", self.r_list)
        a("POST", r"/api/projects", self.r_create)
        a("POST", r"/api/projects/import", self.r_import)
        a("GET", r"/api/projects/(?P<cid>[\w-]+)", self.r_get)
        a("PUT", r"/api/projects/(?P<cid>[\w-]+)", self.r_save)
        a("DELETE", r"/api/projects/(?P<cid>[\w-]+)", self.r_delete)
        a("POST", r"/api/projects/(?P<cid>[\w-]+)/meta", self.r_meta)
        a("POST", r"/api/projects/(?P<cid>[\w-]+)/duplicate", self.r_duplicate)
        a("POST", r"/api/projects/(?P<cid>[\w-]+)/run", self.r_run)
        a("POST", r"/api/projects/(?P<cid>[\w-]+)/flow", self.r_flow)
        a("POST", r"/api/projects/(?P<cid>[\w-]+)/nodes/(?P<nid>[\w-]+)/autofill", self.r_autofill)
        a("GET", r"/api/projects/(?P<cid>[\w-]+)/download", self.r_download)
        a("GET", r"/api/projects/(?P<cid>[\w-]+)/mentions", self.r_mentions)
        a("POST", r"/api/projects/(?P<cid>[\w-]+)/assets", self.r_asset_upload)
        a("GET", r"/api/projects/(?P<cid>[\w-]+)/assets/(?P<fname>[\w][\w.-]*)", self.r_asset_get)
        a("DELETE", r"/api/projects/(?P<cid>[\w-]+)/assets/(?P<aid>[\w-]+)", self.r_asset_delete)

        a("GET", r"/api/media/providers", self.r_media_providers)
        a("POST", r"/api/media/test", self.r_media_test)
        a("GET", r"/api/media/models", self.r_media_models)
        a("GET", r"/api/media/installed", self.r_media_installed)
        a("POST", r"/api/media/support/download", self.r_support_download)
        a("POST", r"/api/media/sd-latest", self.r_sd_latest)
        a("POST", r"/api/media/sd-cli", self.r_sd_cli)
        a("GET", r"/api/media/hub/search", self.r_hub_search)
        a("POST", r"/api/media/hub/use", self.r_hub_use)
        a("GET", r"/api/media/local/state", self.r_local_state)
        a("GET", r"/api/media/local/options", self.r_local_options)
        a("GET", r"/api/media/local/quants", self.r_local_quants)
        a("POST", r"/api/media/local/download", self.r_local_download)

    # ------------------------------------------------------------------ documentos
    def _canvas(self, cid: str) -> Dict[str, Any]:
        c = self.cs.get(cid)
        if not c:
            raise HttpError(404, "Projeto não encontrado")
        return c

    def _job(self, cid: str):
        return self.app.jobs.running(f"canvas:{cid}")

    def r_templates(self, req) -> None:
        req.json({"templates": TEMPLATES, "types": describe_types(), "caps": list(CAPS), "sizes": list(SIZES), "aspects": list(ASPECTS), "resolutions": list(VIDEO_RESOLUTIONS),
                  "defaults": {k: normalize_params(k, {}) for k in NODE_TYPES}, "default_result": normalize_result({})})

    def r_list(self, req) -> None:
        """Todos os projetos. `?q=` pesquisa no nome, na descrição e nos textos dos nós; `?sort=updated|created|name|files`."""
        q = text(req.query.get("q", [""])[0], "", 120)
        sort = text(req.query.get("sort", ["updated"])[0], "updated", 12)
        req.json(self.cs.list(q, sort if sort in ("updated", "created", "name", "files") else "updated"))

    def r_create(self, req) -> None:
        body = req.body_json()
        body = body if isinstance(body, dict) else {}
        c = self.cs.create(text(body.get("name"), "", 80), text(body.get("template"), "blank", 20), text(body.get("prompt"), "", 6000))
        ids = [text(i, "", 60) for i in body.get("attachment_ids")][:20] if isinstance(body.get("attachment_ids"), list) else []
        if ids:
            c = self._attach_uploads(c["id"], ids) or c
        req.json(c, 201)

    def _attach_uploads(self, cid: str, ids: list):
        """Anexos do compositor viram nós: imagens/vídeos/áudios → um nó "Mídia"; documentos com texto → um nó "Texto" cada."""
        from . import attachments as att

        limit = int(self.store.get_settings()["server"].get("max_upload_mb", 200)) * 1024 * 1024
        files, texts = [], []
        for meta in self.store.get_uploads(ids, limit=20, max_members=60):   # pacotes (ZIP, RAR…) já vêm abertos: cada arquivo de dentro é um anexo
            path = Path(meta["path"])
            if meta.get("error"):
                continue
            if not path.is_file() or path.stat().st_size > limit:
                continue
            data = path.read_bytes()
            mime = sniff_mime(data)
            kind = mime.split("/")[0]
            if kind in ("image", "audio", "video"):
                a = self.cs.add_asset(cid, data, MIME_EXT.get(mime, "bin"), kind, name=meta["name"], mime=mime, provider="upload")
                if a:
                    files.append(a["id"])
            else:
                item = att.analyze(path, meta["name"], meta.get("mime", ""), max_chars=6000)
                if item.get("text"):
                    texts.append((meta["name"], item["text"]))
        nodes, y = [], 40
        if files:
            nodes.append({"id": new_id("n_"), "type": "upload", "x": -360, "y": y, "title": "Anexos", "params": {"files": files}})
            y += 300
        for name, body_text in texts[:6]:
            nodes.append({"id": new_id("n_"), "type": "text", "x": -360, "y": y, "title": name[:40], "params": {"text": body_text}})
            y += 240
        return self.cs.append_nodes(cid, nodes) if nodes else None

    def r_import(self, req) -> None:
        """Cria um projeto a partir de um `.zip` baixado do OpenFlow (corpo cru do arquivo)."""
        limit = int(self.store.get_settings()["server"].get("max_upload_mb", 200)) * 1024 * 1024
        c = self.cs.import_zip(req.body_bytes(limit))
        if not c:
            raise HttpError(400, "Este arquivo não é um projeto do OpenFlow (.zip com project.json e assets/).")
        req.json(self.cs.summary(c), 201)

    def r_get(self, req, cid: str) -> None:
        self._canvas(cid)
        job = self._job(cid)
        if not job:
            self.cs.reset_running(cid)  # nó "em execução" sem tarefa: a execução foi interrompida
        c = self._canvas(cid)
        c["stale"] = CanvasEngine(self.store, cid).stale_ids(c)
        c["job_id"] = job.id if job else ""
        req.json(c)

    def r_save(self, req, cid: str) -> None:
        body = req.body_json(32 * 1024 * 1024)
        if not isinstance(body, dict):
            raise HttpError(400, "JSON inválido")
        saved = self.cs.save_layout(cid, body)
        if not saved:
            raise HttpError(404, "Projeto não encontrado")
        req.json({"id": cid, "updated": saved["updated"], "stale": CanvasEngine(self.store, cid).stale_ids(saved)})

    def r_meta(self, req, cid: str) -> None:
        body = req.body_json()
        c = self.cs.update_meta(cid, body.get("name") if "name" in body else None, body.get("description") if "description" in body else None)
        if not c:
            raise HttpError(404, "Projeto não encontrado")
        req.json(self.cs.summary(c))

    def r_delete(self, req, cid: str) -> None:
        if self._job(cid):
            raise HttpError(409, "Este projeto está gerando. Cancele a geração antes de apagá-lo.")
        req.json({"ok": self.cs.delete(cid)})

    def r_duplicate(self, req, cid: str) -> None:
        c = self.cs.duplicate(cid)
        if not c:
            raise HttpError(404, "Projeto não encontrado")
        req.json(self.cs.summary(c), 201)

    # ------------------------------------------------------------------ execução
    def r_run(self, req, cid: str) -> None:
        self._canvas(cid)
        body = req.body_json()
        body = body if isinstance(body, dict) else {}
        running = self._job(cid)
        if running:
            raise HttpError(409, json.dumps({"job_id": running.id}))
        nodes = [text(n, "", 24) for n in (body.get("nodes") or [])][:200] if isinstance(body.get("nodes"), list) else None
        force = bool(body.get("force"))
        team = teamlib.request_team(body)   # equipe escolhida na barra do editor (esforço e agentes dos nós de texto com IA)

        def work(job: Job) -> None:
            CanvasEngine(self.store, cid, job.emit, lambda: job.cancelled, team=team).run(nodes or None, force)

        job = self.app.jobs.start(f"canvas:{cid}", work)
        req.json({"job_id": job.id})

    def r_flow(self, req, cid: str) -> None:
        """Gera um fluxo (nós e ligações) a partir de um prompt, com a equipe escolhida (Planejador → Revisor). Não grava nada: o navegador insere o resultado no canvas."""
        c = self._canvas(cid)
        body = req.body_json()
        body = body if isinstance(body, dict) else {}
        prompt = text(body.get("prompt"), "", 6000)
        if not prompt:
            raise HttpError(400, "Descreva o fluxo que você quer criar.")
        running = self.app.jobs.running(f"canvasflow:{cid}")
        if running:
            raise HttpError(409, json.dumps({"job_id": running.id}))
        flow_req = {"prompt": prompt, "team": teamlib.request_team(body), "existing": c["nodes"], "x": body.get("x"), "y": body.get("y")}

        def work(job: Job) -> None:
            FlowPipeline(self.store, job.emit, lambda: job.cancelled).run(flow_req)

        job = self.app.jobs.start(f"canvasflow:{cid}", work)
        req.json({"job_id": job.id})

    def r_autofill(self, req, cid: str, nid: str) -> None:
        c = self._canvas(cid)
        node = next((n for n in c["nodes"] if n["id"] == nid), None)
        if not node or node["type"] != "editor":
            raise HttpError(404, "Nó Editor não encontrado")
        eng = CanvasEngine(self.store, cid)
        tl = eng.auto_timeline(c, node)
        self.cs.patch_node_params(cid, nid, {"timeline": tl})
        node = next(n for n in self._canvas(cid)["nodes"] if n["id"] == nid)
        req.json({"timeline": node["params"]["timeline"]})

    # ------------------------------------------------------------------ mídias do canvas
    def r_asset_upload(self, req, cid: str) -> None:
        self._canvas(cid)
        limit = int(self.store.get_settings()["server"].get("max_upload_mb", 200)) * 1024 * 1024
        if req.content_length() > limit:
            raise HttpError(413, f"Arquivo maior que o limite de {limit // 1024 // 1024} MB")
        name = safe_filename(urllib.parse.unquote(req.headers.get("X-Filename", "arquivo")), "arquivo")
        data = req.body_bytes(limit)
        if archives.archive_kind(name):   # ZIP, RAR, 7z, TAR…: as imagens, vídeos e áudios de dentro viram arquivos do canvas (uma resposta com `also` quando há mais de um)
            return self._asset_upload_archive(req, cid, name, data)
        mime = sniff_mime(data)  # o tipo vem do conteúdo, nunca do nome nem do Content-Type enviado
        kind = mime.split("/")[0] if mime.split("/")[0] in ("image", "audio", "video") else ""
        if not data or not kind:
            raise HttpError(400, "Envie uma imagem, um vídeo ou um áudio válido (PNG, JPG, WebP, GIF, MP4, WebM, MP3, WAV, OGG, FLAC, M4A…).")
        file_ext = MIME_EXT.get(mime, "bin")
        a = self.cs.add_asset(cid, data, file_ext, kind, name=name, mime=mime, node=text(req.query.get("node", [""])[0], "", 24), provider="upload")
        if not a:
            raise HttpError(400, "Não foi possível salvar o arquivo.")
        self._attach(cid, text(req.query.get("node", [""])[0], "", 24), text(req.query.get("folder", [""])[0], "", 24), [a["id"]])  # já anexa ao nó (Mídia ou Style Folder, na pasta indicada)
        req.json(a, 201)

    def _attach(self, cid: str, node_id: str, folder_id: str, ids: list) -> None:
        """Põe arquivos num nó Mídia ou Style Folder; num Style Folder, `folder_id` escolhe a pasta/subpasta (sem ela, vão para a raiz do nó)."""
        if not node_id or not ids:
            return
        node = next((n for n in self._canvas(cid)["nodes"] if n["id"] == node_id), None)
        if not node or node["type"] not in ("upload", "style_folder"):
            return
        if node["type"] == "style_folder" and folder_id:
            folders = node["params"]["folders"]
            f = find_folder(folders, folder_id)
            if f is not None:
                f["files"] = f["files"] + list(ids)
                self.cs.patch_node_params(cid, node_id, {"folders": folders})
                return
        self.cs.patch_node_params(cid, node_id, {"files": node["params"]["files"] + list(ids)})

    def _asset_upload_archive(self, req, cid: str, name: str, data: bytes) -> None:
        try:
            members = archives.media_members(data, name, sniff_mime)
        except archives.ArchiveError as exc:
            raise HttpError(400, str(exc))
        node_id = text(req.query.get("node", [""])[0], "", 24)
        recs = []
        for mname, mdata, mime in members:
            a = self.cs.add_asset(cid, mdata, MIME_EXT.get(mime, "bin"), mime.split("/")[0], name=mname, mime=mime, node=node_id, provider="upload")
            if a:
                recs.append(a)
        if not recs:
            raise HttpError(400, "O pacote não tem imagens, vídeos nem áudios que o OpenFlow aceite (PNG, JPG, WebP, GIF, MP4, WebM, MP3, WAV, OGG…).")
        self._attach(cid, node_id, text(req.query.get("folder", [""])[0], "", 24), [a["id"] for a in recs])
        req.json(dict(recs[0], also=recs[1:]), 201)

    def r_asset_get(self, req, cid: str, fname: str) -> None:
        c = self._canvas(cid)
        path = self.cs.asset_path(cid, fname)
        if not path:
            raise HttpError(404, "Arquivo não encontrado")
        rec = next((a for a in c["assets"] if a["file"] == fname), None)
        mime = (rec or {}).get("mime") or mimetypes.guess_type(fname)[0] or "application/octet-stream"
        if mime.split("/")[0] not in ("image", "audio", "video"):
            mime = "application/octet-stream"
        dl = "1" in (req.query.get("download") or [])
        req.file(path, mime, download_name=(rec or {}).get("name", fname) if dl else "", cache=True)

    def r_asset_delete(self, req, cid: str, aid: str) -> None:
        self._canvas(cid)
        if self._job(cid):
            raise HttpError(409, "Este projeto está gerando. Aguarde terminar ou cancele.")
        req.json({"ok": self.cs.delete_asset(cid, aid)})

    def r_download(self, req, cid: str) -> None:
        c = self._canvas(cid)
        with tempfile.TemporaryDirectory() as tmp:
            zp = Path(tmp) / "canvas.zip"
            with zipfile.ZipFile(zp, "w", zipfile.ZIP_STORED) as z:
                z.writestr("project.json", json.dumps(c, ensure_ascii=False, indent=2))
                for a in c["assets"]:
                    p = self.cs.asset_path(cid, a["file"])
                    if p:
                        z.write(p, f"assets/{a['file']}")
            req.file(zp, "application/zip", download_name=f"{safe_filename(c['name'], 'canvas')}.zip")

    # ------------------------------------------------------------------ provedores de mídia
    def r_media_providers(self, req) -> None:
        req.json({"providers": describe_media_presets(self.store.get_settings()), "active": self.store.get_settings()["media"]["active"]})

    def r_media_test(self, req) -> None:
        body = req.body_json()
        pid = text(body.get("provider"), "", 40)
        try:
            prov = build_media(self.store.get_settings(), pid, models_dir=self.store.models_dir)
            req.json({"ok": True, "message": prov.test()})
        except ProviderError as exc:
            raise HttpError(502, str(exc))

    def r_media_models(self, req) -> None:
        pid = text(req.query.get("provider", [""])[0], "", 40)
        cap = text(req.query.get("cap", ["image"])[0], "image", 12)
        try:
            req.json({"models": build_media(self.store.get_settings(), pid, models_dir=self.store.models_dir).list_models(cap)})
        except ProviderError as exc:
            raise HttpError(502, str(exc))

    def r_support_download(self, req) -> None:
        """Baixa os arquivos de apoio (VAE, codificador de texto…) que faltam ao lado de um GGUF de difusão de imagem (Qwen-Image, FLUX…). Só a pedido da pessoa (botão no nó)."""
        import re as _re

        from . import hf
        from .canvas import support

        body = req.body_json()
        model = text((body if isinstance(body, dict) else {}).get("model"), "", 200)
        if not _re.match(r"^[\w][\w .+()=-]{0,200}\.gguf$", model):
            raise HttpError(400, "Informe o arquivo GGUF do modelo.")
        cap = "video" if text((body if isinstance(body, dict) else {}).get("cap"), "", 8) == "video" else "image"
        folder = hf.kind_dir(self.store.models_dir, cap, create=True)
        info = support.missing(folder, model)
        if not info["family"]:
            raise HttpError(400, "Este modelo não é de uma família com arquivos de apoio conhecidos (Qwen-Image, FLUX, Z-Image, Wan2.2…).")
        if not info["missing"]:
            raise HttpError(400, "Os arquivos de apoio deste modelo já estão na pasta.")
        running = self.app.jobs.running("support_files")
        if running:
            raise HttpError(409, json.dumps({"job_id": running.id}))
        token = self._hf_token()

        def work(job: Job) -> None:
            import time

            job.emit({"type": "start", "files": [m["label"] for m in info["missing"]], "approx_gb": info["approx_gb"]})
            last = [0.0]

            def progress(done: int, total: int) -> None:
                if time.time() - last[0] > 0.4:
                    last[0] = time.time()
                    job.emit({"type": "progress", "done": done, "total": total})

            got = support.download_missing(folder, model, token, progress, lambda: job.cancelled, lambda m: job.emit({"type": "note", "message": m}))
            job.emit({"type": "done", "files": got})

        job = self.app.jobs.start("support_files", work)
        req.json({"job_id": job.id, "files": [m["label"] for m in info["missing"]], "approx_gb": info["approx_gb"]})

    def r_sd_cli(self, req) -> None:
        """Baixa o `sd-cli` pré-compilado da stable-diffusion.cpp (sem git nem compilador) para `<dados>/bin/sd-cpp/`: o OpenFlow passa a usá-lo nos modelos que a biblioteca Python não reconhece. Só a pedido (botão no nó)."""
        running = self.app.jobs.running("sd_cli")
        if running:
            raise HttpError(409, json.dumps({"job_id": running.id}))

        def work(job: Job) -> None:
            from .canvas import media, sdcli
            from .providers import ProviderError

            job.emit({"type": "start"})
            try:
                exe = sdcli.install(lambda done, total: job.emit({"type": "progress", "done": done, "total": total}), lambda: job.cancelled, lambda m: job.emit({"type": "note", "message": m}))
            except ProviderError as exc:
                job.emit({"type": "cancelled"} if str(exc) == "cancelado" else {"type": "error", "message": str(exc)[:400]})
                return
            media._media_unload()
            job.emit({"type": "done", "path": str(exe)})

        job = self.app.jobs.start("sd_cli", work)
        req.json({"job_id": job.id})

    def r_sd_latest(self, req) -> None:
        """Compila a stable-diffusion-cpp-python mais nova do GitHub (`flow libs --sd-latest`) quando o modelo não é reconhecido pela que veio do PyPI. Só a pedido da pessoa (botão no nó); leva minutos."""
        running = self.app.jobs.running("sd_latest")
        if running:
            raise HttpError(409, json.dumps({"job_id": running.id}))

        def work(job: Job) -> None:
            import subprocess
            import sys as _sys

            from .canvas import media

            job.emit({"type": "start"})
            media._media_unload()   # fecha o processo da biblioteca antiga: o próximo uso sobe um com a nova
            proc = subprocess.Popen([_sys.executable, "-m", "openflow", "libs", "--extras", "none", "--sd-latest"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            tail: list = []
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    tail = (tail + [line])[-8:]
                    job.emit({"type": "note", "message": line[:200]})
                if job.cancelled:
                    proc.terminate()
                    break
            code = proc.wait()
            if job.cancelled:
                job.emit({"type": "cancelled"})
            elif code == 0:
                job.emit({"type": "done"})
            else:
                job.emit({"type": "error", "message": " | ".join(tail)[-400:] or "A compilação falhou."})

        job = self.app.jobs.start("sd_latest", work)
        req.json({"job_id": job.id})

    def r_media_installed(self, req) -> None:
        """Modelos instalados neste computador para um tipo (image, video, sound, voice, stt): GGUF baixados e modelos do Hugging Face local."""
        from .canvas import installed

        cap = text(req.query.get("cap", ["image"])[0], "image", 12)
        if cap not in CAPS:
            raise HttpError(400, "Tipo de modelo inválido.")
        req.json({"cap": cap, "items": installed.installed(self.store.get_settings(), self.store.models_dir, cap)})

    def r_mentions(self, req, cid: str) -> None:
        """As imagens, vídeos e sons que podem ser citados com «@» neste canvas (apelido, nome, tipo, arquivo), do mais novo para o mais antigo; `q` filtra pelo apelido."""
        from .canvas import mentions

        c = self._canvas(cid)
        q = text(req.query.get("q", [""])[0], "", 60).lower()
        items = [{"id": m["id"], "slug": m["slug"], "name": m["name"], "kind": m["kind"], "url": f"/api/projects/{cid}/assets/{m['file']}"} for m in mentions.table(c) if not q or q in m["slug"]]
        req.json({"items": items[:50]})

    # ------------------------------------------------------------------ barra de busca de modelos (Hugging Face) no topo do editor
    HUB_CAPS = ("image", "video", "sound", "voice", "stt", "text")
    GGUF_CAP_KIND = {"image": "image", "video": "video", "text": "text"}   # só estes têm provedor GGUF no OpenFlow (sons e vozes usam o formato original)

    def r_hub_search(self, req) -> None:
        """Busca modelos no Hugging Face por capacidade. `format=gguf` (várias quantizações por arquivo) ou `format=original` (fp32/fp16/bf16 e versões comprimidas da comunidade)."""
        from . import hf

        q = text(req.query.get("q", [""])[0], "", 120)
        cap = text(req.query.get("cap", ["image"])[0], "image", 12)
        fmt = "gguf" if req.query.get("format", ["gguf"])[0] != "original" else "original"
        if cap not in self.HUB_CAPS:
            raise HttpError(400, "Escolha o tipo do modelo.")
        if fmt == "gguf" and cap not in self.GGUF_CAP_KIND:
            fmt = "original"
        try:
            if fmt == "gguf":
                found = [dict(r, cap=cap, format="gguf") for r in hf.search(q or "gguf", self._hf_token(), kind=self.GGUF_CAP_KIND[cap])]
            else:
                found = hf.search_original(q, self._hf_token(), cap)
        except ProviderError as exc:
            raise HttpError(502, str(exc))
        except Exception as exc:  # noqa: BLE001 — sem rede / Hugging Face fora do ar
            raise HttpError(502, f"Não foi possível pesquisar no Hugging Face: {exc}")
        req.json({"results": found, "format": fmt, "cap": cap})

    def r_hub_use(self, req) -> None:
        """Passa a usar um modelo baixado: vira o padrão da capacidade em Configuração → Mídia e, se vier `canvas` + `node`, também o modelo desse nó."""
        from .canvas.media import MEDIA_PRESETS

        b = req.body_json()
        b = b if isinstance(b, dict) else {}
        cap, provider, model = text(b.get("cap"), "", 12), text(b.get("provider"), "", 20), text(b.get("model"), "", 200)
        if cap not in self.HUB_CAPS or provider not in ("gguf_local", "local_hf") or not model:
            raise HttpError(400, "Informe o tipo, o provedor (gguf_local ou local_hf) e o modelo.")
        if provider == "gguf_local":
            if cap not in ("image", "video") or not (self.store.models_dir / cap / Path(model).name).is_file():
                raise HttpError(404, "Esse arquivo GGUF não foi baixado ainda (ou não é de imagem/vídeo).")
            model = Path(model).name
        elif not REPO_RE.match(model):
            raise HttpError(400, "Informe o modelo no formato dono/nome.")
        node_type = {"image": "image", "video": "video", "sound": "sound", "voice": "voice", "stt": "transcribe", "text": "llm"}[cap]
        if cap == "text":   # modelo de texto GGUF baixado: provedor «Hugging Face GGUF (embutido)» da conversa
            if not (self.store.models_dir / Path(model).name).is_file():
                raise HttpError(404, "Esse arquivo GGUF não foi baixado ainda.")
            self.store.save_settings({"providers": {"local_hf": {"model": Path(model).name}}})
            pid = "local_hf"
            label = "Hugging Face GGUF (embutido)"
        else:
            self.store.save_settings({"media": {"active": {cap: provider}, "models": {provider: {cap: model}}}})
            pid, label = provider, MEDIA_PRESETS[provider]["label"]
        patched = False
        cid, nid = text(b.get("canvas"), "", 40), text(b.get("node"), "", 40)
        if cid and nid:
            cv = self.cs.get(cid)
            n = next((x for x in (cv or {}).get("nodes", []) if x["id"] == nid), None)
            if n and n["type"] == node_type:
                patch = {"provider": pid} if cap == "text" else {"provider": pid, "model": model}
                patched = self.cs.patch_node_params(cid, nid, patch)
        req.json({"ok": True, "provider": pid, "label": label, "model": model, "cap": cap, "node_updated": patched})

    # ------------------------------------------------------------------ modelos locais: a precisão é escolhida antes do download
    def _hf_token(self) -> str:
        return (self.store.get_settings().get("hf") or {}).get("token", "")

    def r_local_state(self, req) -> None:
        from .canvas import localmodels as lm
        from .canvas.media import media_config

        cfg = media_config(self.store.get_settings(), "local_hf")
        try:
            lm._hub()
            libs = True
        except ProviderError:
            libs = False
        out = {}
        for cap, model in cfg["models"].items():
            out[cap] = {"model": model, "precision": lm.downloaded_precision(model) if libs and model else ""}
        req.json({"libs": libs, "models": out})

    def r_local_options(self, req) -> None:
        from .canvas import localmodels as lm

        model = text(req.query.get("model", [""])[0], "", 200)
        if not REPO_RE.match(model):
            raise HttpError(400, "Informe o modelo no formato dono/nome.")
        try:
            req.json(lm.options(model, self._hf_token(), bool(hardware_info().get("gpu"))))
        except ProviderError as exc:
            raise HttpError(502, str(exc))
        except Exception as exc:  # noqa: BLE001 — erros da biblioteca do Hugging Face (repositório inexistente, sem rede…)
            raise HttpError(502, f"Não foi possível consultar o modelo: {exc}")

    def r_local_quants(self, req) -> None:
        """Versões menores (quantizadas, da comunidade) do modelo, para baixar no lugar do original."""
        from .canvas import localmodels as lm

        model = text(req.query.get("model", [""])[0], "", 200)
        if not REPO_RE.match(model):
            raise HttpError(400, "Informe o modelo no formato dono/nome.")
        try:
            req.json({"model": model, "variants": lm.quantized_variants(model, self._hf_token())})
        except Exception as exc:  # noqa: BLE001 — sem rede / Hugging Face fora do ar
            raise HttpError(502, f"Não foi possível procurar versões menores: {exc}")

    def r_local_download(self, req) -> None:
        from .canvas import localmodels as lm

        body = req.body_json()
        model, precision = text(body.get("model"), "", 200), text(body.get("precision"), "", 8)
        if not REPO_RE.match(model):
            raise HttpError(400, "Informe o modelo no formato dono/nome.")
        if precision not in lm.PRECISIONS:
            raise HttpError(400, "Escolha a precisão (quantização) do modelo antes de baixar.")
        running = self.app.jobs.running("local_model")
        if running:
            raise HttpError(409, json.dumps({"job_id": running.id}))

        def work(job: Job) -> None:
            import time

            job.emit({"type": "start", "model": model, "precision": precision})
            last = [0.0]

            def progress(done: int, total: int) -> None:
                if time.time() - last[0] > 0.4:
                    last[0] = time.time()
                    job.emit({"type": "progress", "done": done, "total": total})

            lm.download(model, precision, self._hf_token(), progress, lambda: job.cancelled)
            job.emit({"type": "done", "model": model, "precision": precision})

        job = self.app.jobs.start("local_model", work)
        req.json({"job_id": job.id})
