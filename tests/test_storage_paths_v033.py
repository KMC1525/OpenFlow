"""v0.33: Biblioteca em outras pastas — modelos e arquivos dos projetos em um disco externo ou outra pasta, com mover seguro."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from openflow import storagepaths as sp
from openflow.providers import ProviderError
from openflow.storage import Store
from tests.helpers import ServerCase


def tree(root: Path, files: dict):
    for rel, n in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * n)


class ResolveTests(unittest.TestCase):
    def test_validation_messages(self):
        for bad in ("", "   ", "relativa/pasta"):
            with self.assertRaises(ProviderError):
                sp.resolve("models", bad)
        f = Path(tempfile.mkdtemp()) / "arquivo.txt"
        f.write_text("x")
        with self.assertRaises(ProviderError):
            sp.resolve("models", str(f))
        with self.assertRaises(ProviderError) as cm:
            sp.resolve("models", "/nao/existe/nem/o/pai")
        self.assertIn("conectado", str(cm.exception))

    def test_creates_the_folder_and_a_disk_root_becomes_a_subfolder(self):
        d = Path(tempfile.mkdtemp()) / "modelos"
        self.assertEqual(sp.resolve("models", str(d)), d.resolve())
        self.assertTrue(d.is_dir())
        root = Path(tempfile.mkdtemp())
        with mock.patch.object(sp.os.path, "ismount", return_value=True):
            self.assertEqual(sp.resolve("files", str(root)), (root / "OpenFlow-projetos").resolve())

    def test_read_only_folder_is_refused(self):
        d = Path(tempfile.mkdtemp())
        with mock.patch.object(sp, "_writable", return_value=False), self.assertRaises(ProviderError) as cm:
            sp.resolve("models", str(d))
        self.assertIn("permissão", str(cm.exception))

    def test_browse_lists_visible_subfolders(self):
        d = Path(tempfile.mkdtemp())
        (d / "a").mkdir()
        (d / ".oculta").mkdir()
        (d / "arquivo").write_text("x")
        b = sp.browse(str(d))
        self.assertEqual((b["dirs"], b["parent"]), (["a"], str(d.parent)))
        with self.assertRaises(ProviderError):
            sp.browse(str(d / "nada"))
        self.assertTrue(sp.browse("")["volumes"])


class MigrateTests(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.src, self.dst = base / "src", base / "dst"
        self.src.mkdir()
        self.dst.mkdir()
        tree(self.src, {"image/a.gguf": 4000, "text/b.gguf": 1000, "vae.safetensors": 10})

    def test_copy_then_remove_source(self):
        seen = []
        n = sp.migrate(self.src, self.dst, lambda d, t: seen.append((d, t)), lambda: False)
        self.assertEqual(n, 5010)
        self.assertEqual(seen[-1], (5010, 5010))
        self.assertTrue((self.src / "image" / "a.gguf").exists())                  # a origem só sai depois de tudo copiado
        self.assertEqual((self.dst / "image" / "a.gguf").stat().st_size, 4000)
        sp.remove_source(self.src)
        self.assertEqual(list(self.src.iterdir()), [])
        self.assertTrue(self.src.is_dir())

    def test_cancel_rolls_back_the_new_copies(self):
        calls = {"n": 0}

        def cancelled():
            calls["n"] += 1
            return calls["n"] > 1

        with self.assertRaises(ProviderError):
            sp.migrate(self.src, self.dst, lambda d, t: None, cancelled)
        self.assertEqual([p for p in self.dst.rglob("*") if p.is_file()], [])      # nada pela metade na pasta nova
        self.assertTrue((self.src / "image" / "a.gguf").exists())                  # e a origem intacta

    def test_a_second_run_resumes_what_is_already_there(self):
        sp.migrate(self.src, self.dst, lambda d, t: None, lambda: False)
        notes = []
        sp.migrate(self.src, self.dst, lambda d, t: None, lambda: False, notes.append)
        self.assertEqual(notes, [])                                                # nada para copiar de novo

    def test_checks(self):
        with self.assertRaises(ProviderError):
            sp.check_move(self.src, self.src)
        with self.assertRaises(ProviderError):
            sp.check_move(self.src, self.src / "dentro")
        with self.assertRaises(ProviderError):
            sp.check_move(self.src / "image", self.src)
        with mock.patch.object(sp, "_usage", return_value={"free": 100, "total": 1000}), self.assertRaises(ProviderError) as cm:
            sp.check_move(self.src, self.dst)
        self.assertIn("espaço", str(cm.exception))
        self.assertEqual(sp.check_move(self.src, self.dst), 5010)


class StoreTests(unittest.TestCase):
    def test_default_then_custom_then_disconnected(self):
        home = Path(tempfile.mkdtemp())
        st = Store(home)
        self.assertEqual((st.models_dir, Path(st.projects.folder)), (home / "models", home / "projects"))
        ext = Path(tempfile.mkdtemp()) / "hd"
        st.save_settings({"storage": {"models_dir": str(ext / "m"), "files_dir": str(ext / "p")}})
        self.assertEqual((st.models_dir, Path(st.projects.folder)), (ext / "m", ext / "p"))
        self.assertTrue((ext / "m").is_dir())
        self.assertEqual(Store(home).models_dir, ext / "m")                         # lembra depois de reabrir
        st.save_settings({"storage": {"models_dir": "/proc/nao-existe/hd", "files_dir": ""}})   # um caminho que não dá para criar: como um disco externo desligado
        st2 = Store(home)
        self.assertEqual(st2.models_dir, home / "models")                           # dispositivo desligado: cai na padrão, sem quebrar
        self.assertTrue(st2.storage_warnings)
        st.save_settings({"storage": {"models_dir": "", "files_dir": ""}})
        self.assertEqual(st.models_dir, home / "models")


class ApiTests(ServerCase):
    def wait(self, jid):
        for _ in range(100):
            j = self.c.json("GET", "/api/jobs/" + jid)[1]
            if j.get("status") != "running":
                return j
            time.sleep(0.05)

    def tearDown(self):
        self.store.save_settings({"storage": {"models_dir": "", "files_dir": ""}})
        self.store.apply_storage(self.store.get_settings())

    def test_locations_and_validation(self):
        s, r = self.c.json("GET", "/api/storage/locations")
        self.assertEqual(s, 200, r)
        self.assertEqual((r["models"]["custom"], r["files"]["custom"]), (False, False))
        self.assertTrue(r["volumes"])
        self.assertEqual(self.c.json("POST", "/api/storage/location", {"kind": "x", "path": "/tmp"})[0], 400)
        self.assertEqual(self.c.json("POST", "/api/storage/location", {"kind": "models", "path": "relativo"})[0], 400)
        self.assertEqual(self.c.json("POST", "/api/storage/location", {"kind": "models", "path": str(self.store.models_dir / "dentro"), "move": True})[0], 400)

    def test_switch_without_moving(self):
        ext = Path(tempfile.mkdtemp()) / "m"
        s, r = self.c.json("POST", "/api/storage/location", {"kind": "models", "path": str(ext), "move": False})
        self.assertEqual((s, r["moved"]), (200, False))
        self.assertEqual(self.store.models_dir.resolve(), ext.resolve())   # macOS: /var/folders… é um link para /private/var/folders…
        self.assertEqual(self.c.json("GET", "/api/storage/locations")[1]["models"]["custom"], True)

    def test_moving_models_keeps_them_listed_and_empties_the_old_folder(self):
        old = self.store.models_dir
        tree(old, {"image/z-Q4_K_M.gguf": 3000})
        ext = Path(tempfile.mkdtemp()) / "hd"
        s, r = self.c.json("POST", "/api/storage/location", {"kind": "models", "path": str(ext), "move": True})
        self.assertEqual(s, 200, r)
        self.assertEqual(self.wait(r["job_id"])["status"], "done")
        self.assertEqual(self.store.models_dir.resolve(), ext.resolve())
        self.assertTrue((ext / "image" / "z-Q4_K_M.gguf").exists())
        self.assertFalse((old / "image" / "z-Q4_K_M.gguf").exists())
        names = [m["name"] for m in self.c.json("GET", "/api/hf/local?kind=image")[1]["models"]]
        self.assertIn("z-Q4_K_M.gguf", names)
        s, back = self.c.json("POST", "/api/storage/location", {"kind": "models", "path": "", "move": True})   # volta para a padrão
        self.assertEqual(self.wait(back["job_id"])["status"], "done")
        self.assertEqual(self.store.models_dir, old)
        self.assertTrue((old / "image" / "z-Q4_K_M.gguf").exists())

    def test_moving_project_files(self):
        s, c = self.c.json("POST", "/api/projects", {"name": "Mover"})
        pid = c["id"]
        self.app.project_routes.cs.add_asset(pid, b"\x89PNG" + b"0" * 20, "png", "image", name="mv.png", mime="image/png", provider="upload")
        ext = Path(tempfile.mkdtemp()) / "proj"
        s, r = self.c.json("POST", "/api/storage/location", {"kind": "files", "path": str(ext), "move": True})
        self.assertEqual(s, 200, r)
        self.assertEqual(self.wait(r["job_id"])["status"], "done")
        self.assertTrue((ext / pid / "project.json").exists())
        self.assertEqual(self.c.json("GET", f"/api/projects/{pid}")[0], 200)       # o projeto abre normalmente na nova pasta
        names = [f["name"] for f in self.c.json("GET", "/api/library/files?source=all")[1]["files"]]
        self.assertIn("mv.png", names)

    def test_refused_while_a_task_runs(self):
        import threading

        gate = threading.Event()
        job = self.app.jobs.start("canvas:x", lambda j: gate.wait(5))
        try:
            s, r = self.c.json("POST", "/api/storage/location", {"kind": "models", "path": str(Path(tempfile.mkdtemp()) / "a"), "move": False})
            self.assertEqual(s, 409, r)
        finally:
            gate.set()
            time.sleep(0.1)
