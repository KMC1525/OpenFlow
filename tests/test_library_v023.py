"""v0.23: Biblioteca — arquivos gerados de todos os projetos e a lista de downloads."""
import time

from tests.helpers import ServerCase

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class LibraryTests(ServerCase):
    def project(self, name):
        s, c = self.c.json("POST", "/api/projects", {"name": name})
        self.assertEqual(s, 201, c)
        return c["id"]

    def test_files_lists_generated_across_projects_and_filters(self):
        store = self.app.project_routes.cs
        p1, p2 = self.project("Filme"), self.project("Livro")
        store.add_asset(p1, PNG, "png", "image", name="gato.png", mime="image/png", provider="gguf_local", model="z-image.gguf")
        store.add_asset(p2, PNG, "png", "image", name="envio.png", mime="image/png", provider="upload")
        store.add_asset(p2, b"x" * 10, "mp3", "audio", name="voz.mp3", mime="audio/mpeg", provider="openai", model="tts-1")
        s, r = self.c.json("GET", "/api/library/files")
        self.assertEqual(sorted(f["name"] for f in r["files"]), ["gato.png", "voz.mp3"])        # envios ficam de fora por padrão
        self.assertEqual({f["project_name"] for f in r["files"]}, {"Filme", "Livro"})
        self.assertEqual([f["name"] for f in self.c.json("GET", "/api/library/files?kind=audio")[1]["files"]], ["voz.mp3"])
        self.assertEqual([f["name"] for f in self.c.json("GET", "/api/library/files?source=upload")[1]["files"]], ["envio.png"])
        self.assertEqual(len(self.c.json("GET", "/api/library/files?source=all")[1]["files"]), 3)
        self.assertEqual([f["name"] for f in self.c.json("GET", "/api/library/files?q=z-image")[1]["files"]], ["gato.png"])   # acha pelo modelo
        self.assertEqual([f["name"] for f in self.c.json("GET", "/api/library/files?q=livro")[1]["files"]], ["voz.mp3"])      # e pelo projeto
        self.assertTrue(r["files"][0]["url"].startswith("/api/projects/"))

    def test_files_rejects_bad_filters(self):
        self.assertEqual(self.c.json("GET", "/api/library/files?kind=exe")[0], 400)
        self.assertEqual(self.c.json("GET", "/api/library/files?source=x")[0], 400)

    def test_downloads_show_progress_and_status(self):
        from openflow.jobs import Job

        def work(job):
            job.emit({"type": "start", "file": "m.gguf"})
            job.emit({"type": "progress", "done": 30, "total": 100})
            for _ in range(100):
                if job.cancelled:
                    break
                time.sleep(0.02)
            job.emit({"type": "cancelled"})

        job = self.app.jobs.start("download", work, {"title": "m.gguf", "repo": "acme/m"})
        time.sleep(0.15)
        s, r = self.c.json("GET", "/api/library/downloads")
        d = next(x for x in r["downloads"] if x["id"] == job.id)
        self.assertEqual((d["status"], d["done"], d["total"], d["title"], d["repo"]), ("running", 30, 100, "m.gguf", "acme/m"))
        self.assertEqual(r["running"], 1)
        self.c.json("POST", f"/api/jobs/{job.id}/cancel")
        for _ in range(100):
            if job.status != "running":
                break
            time.sleep(0.02)
        d = next(x for x in self.c.json("GET", "/api/library/downloads")[1]["downloads"] if x["id"] == job.id)
        self.assertNotEqual(d["status"], "running")

    def test_a_failed_download_is_reported_as_error(self):
        def work(job):
            job.emit({"type": "start"})
            job.emit({"type": "error", "message": "sem rede"})

        job = self.app.jobs.start("support_files", work)
        time.sleep(0.2)
        d = next(x for x in self.c.json("GET", "/api/library/downloads")[1]["downloads"] if x["id"] == job.id)
        self.assertEqual((d["status"], d["error"]), ("error", "sem rede"))

    def test_other_jobs_are_not_downloads(self):
        job = self.app.jobs.start("canvas:x", lambda j: j.emit({"type": "done"}))
        time.sleep(0.1)
        self.assertNotIn(job.id, [x["id"] for x in self.c.json("GET", "/api/library/downloads")[1]["downloads"]])

    def test_local_models_carry_a_modification_time(self):
        d = self.app.store.models_dir / "image"
        d.mkdir(parents=True, exist_ok=True)
        (d / "z-image-Q4_K_M.gguf").write_bytes(b"g")
        m = next(x for x in self.c.json("GET", "/api/hf/local?kind=image")[1]["models"] if x["name"] == "z-image-Q4_K_M.gguf")
        self.assertGreater(m["mtime"], 0)
