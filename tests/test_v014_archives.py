"""v0.14 — ZIP/RAR (e 7z, TAR) como anexos em todas as seções: extração segura, análise, uploads do Chat, Canvas e Studio."""
import io
import os
import stat
import sys
import tarfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import archives, attachments as att  # noqa: E402
from openflow.storage import Store  # noqa: E402
from tests.media_tools import tiny_png  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402
from tests.helpers import ServerCase  # noqa: E402


def make_zip(path: Path, members: dict, symlink: str = "") -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "/etc/passwd")
    return path


class CleanNameTests(unittest.TestCase):
    def test_unsafe_names_are_refused(self):
        for bad in ("../x.txt", "a/../../x.txt", "/etc/passwd", "C:\\Windows\\x.dll", "c:/x", "..\\..\\x", "", "/", "a/b/.."):
            self.assertIsNone(archives.clean_name(bad), bad)

    def test_safe_names_are_normalized(self):
        self.assertEqual(archives.clean_name("pasta\\sub\\arquivo.txt"), "pasta/sub/arquivo.txt")
        self.assertEqual(archives.clean_name("./a//b.txt"), "a/b.txt")
        self.assertEqual(archives.clean_name("con.txt"), "_con.txt")   # nome reservado do Windows
        self.assertEqual(archives.clean_name('a<b>:c.txt'), "a_b__c.txt")


class ZipTests(TmpCase):
    def test_extracts_files_and_survives_zip_slip(self):
        z = make_zip(self.tmp / "p.zip", {"README.md": "# Olá", "docs/a.txt": "texto a", "../evil.txt": "x", "/abs.txt": "x", "C:\\win.txt": "x", "a/../../up.txt": "x"}, symlink="link.txt")
        dest = self.tmp / "out"
        res = archives.extract(z, dest)
        self.assertEqual(sorted(f["name"] for f in res["files"]), ["README.md", "docs/a.txt"])
        self.assertTrue(any("inseguro" in s for s in res["skipped"]))
        self.assertTrue(any("link simbólico" in s for s in res["skipped"]))
        self.assertFalse((self.tmp / "evil.txt").exists() or (self.tmp.parent / "evil.txt").exists() or Path("/abs.txt").exists())
        for f in res["files"]:   # tudo dentro da pasta de destino
            self.assertTrue(Path(f["path"]).resolve().is_relative_to(dest.resolve()))
        self.assertEqual((dest / "docs" / "a.txt").read_text(), "texto a")

    def test_the_written_size_is_capped_not_the_declared_one(self):
        z = make_zip(self.tmp / "bomb.zip", {"zeros.bin": b"\0" * (5 * 1024 * 1024), "ok.txt": "pequeno"})
        res = archives.extract(z, self.tmp / "o", max_total=1024 * 1024, max_member=1024 * 1024)
        self.assertEqual([f["name"] for f in res["files"]], ["ok.txt"])
        self.assertTrue(any("grande demais" in s for s in res["skipped"]))
        self.assertFalse((self.tmp / "o" / "zeros.bin").exists())

    def test_file_count_is_limited(self):
        z = make_zip(self.tmp / "many.zip", {f"f{i}.txt": "x" for i in range(30)})
        res = archives.extract(z, self.tmp / "o", max_files=10)
        self.assertEqual(len(res["files"]), 10)
        self.assertTrue(any("limite de 10" in s for s in res["skipped"]))

    def test_duplicate_names_do_not_overwrite(self):
        buf = self.tmp / "dup.zip"
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.txt", "um")
            z.writestr("A.TXT", "dois")
        res = archives.extract(buf, self.tmp / "o")
        self.assertEqual(len(res["files"]), 2)
        self.assertEqual(sorted(Path(f["path"]).read_text() for f in res["files"]), ["dois", "um"])

    def test_a_broken_zip_gives_a_clear_error(self):
        bad = self.tmp / "bad.zip"
        bad.write_bytes(b"PK\x03\x04isto nao e um zip")
        with self.assertRaises(archives.ArchiveError) as cm:
            archives.extract(bad, self.tmp / "o")
        self.assertIn("ZIP", str(cm.exception))

    def test_accents_written_by_windows_zip_tools_are_fixed(self):
        z = make_zip(self.tmp / "w.zip", {"xxxxxxxx.txt": "oi"})
        raw = z.read_bytes().replace(b"xxxxxxxx", "ação-ção".encode("cp850"))   # nome em cp850, sem a marca UTF-8 (Explorer do Windows em português)
        z.write_bytes(raw)
        res = archives.extract(z, self.tmp / "o")
        self.assertEqual([f["name"] for f in res["files"]], ["ação-ção.txt"])

    def test_nested_archives_are_opened_one_level(self):
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("deep.txt", "no fundo")
        z = make_zip(self.tmp / "outer.zip", {"inner.zip": inner.getvalue(), "top.txt": "topo"})
        res = archives.expand(z, self.tmp / "o", "outer.zip")
        self.assertEqual(sorted(f["name"] for f in res["files"]), ["inner.zip/deep.txt", "top.txt"])


class TarTests(TmpCase):
    def test_tar_gz_skips_links_and_unsafe_names(self):
        p = self.tmp / "p.tar.gz"
        with tarfile.open(p, "w:gz") as t:
            data = b"conteudo"
            info = tarfile.TarInfo("ok/a.txt")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
            ev = tarfile.TarInfo("../fora.txt")
            ev.size = 1
            t.addfile(ev, io.BytesIO(b"x"))
            ln = tarfile.TarInfo("link")
            ln.type, ln.linkname = tarfile.SYMTYPE, "/etc/passwd"
            t.addfile(ln)
        self.assertEqual(archives.archive_kind("p.tar.gz"), "tar")
        res = archives.extract(p, self.tmp / "o")
        self.assertEqual([f["name"] for f in res["files"]], ["ok/a.txt"])
        self.assertEqual(len(res["skipped"]), 2)
        self.assertFalse((self.tmp / "fora.txt").exists())


class KindTests(TmpCase):
    def test_detection_by_name_and_signature(self):
        self.assertEqual(archives.archive_kind("a.ZIP"), "zip")
        self.assertEqual(archives.archive_kind("a.rar"), "rar")
        self.assertEqual(archives.archive_kind("a.cbr"), "rar")
        self.assertEqual(archives.archive_kind("a.7z"), "7z")
        self.assertEqual(archives.archive_kind("a.tgz"), "tar")
        self.assertEqual(archives.archive_kind("a.txt"), "")
        self.assertEqual(archives.archive_kind("planilha.xlsx"), "")   # xlsx/docx/pptx são ZIPs por dentro, mas são documentos
        f = self.tmp / "semext"
        f.write_bytes(b"Rar!\x1a\x07\x00rest")
        self.assertEqual(archives.archive_kind("semext", f), "rar")


@unittest.skipIf(os.name == "nt", "ferramenta falsa em shell")
class ExternalToolTests(TmpCase):
    """RAR e 7z dependem de uma ferramenta do sistema: aqui um `unrar` falso exercita todo o caminho (limites, links e fuga de pasta são filtrados)."""

    def fake_tool(self, name="unrar"):
        bindir = self.tmp / "bin"
        bindir.mkdir()
        payload = self.tmp / "payload"
        (payload / "sub").mkdir(parents=True)
        (payload / "leia.txt").write_text("do rar")
        (payload / "sub" / "b.md").write_text("fundo")
        script = bindir / name
        script.write_text(f'#!/bin/sh\nfor last; do :; done\ncp -r "{payload}"/. "$last"\nln -s /etc/passwd "$last/link.txt"\nexit 0\n')
        script.chmod(0o755)
        return bindir

    def test_rar_goes_through_the_system_tool_and_links_are_dropped(self):
        rar = self.tmp / "x.rar"
        rar.write_bytes(b"Rar!\x1a\x07\x00falso")
        with mock.patch.dict(os.environ, {"PATH": str(self.fake_tool()) + os.pathsep + "/usr/bin:/bin"}):
            res = archives.extract(rar, self.tmp / "o")
        self.assertEqual(sorted(f["name"] for f in res["files"]), ["leia.txt", "sub/b.md"])   # o link simbólico que a ferramenta criou ficou de fora
        self.assertEqual((self.tmp / "o" / "leia.txt").read_text(), "do rar")

    def test_rar_without_any_tool_explains_what_to_install(self):
        rar = self.tmp / "x.rar"
        rar.write_bytes(b"Rar!\x1a\x07\x00falso")
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "vazio")}):
            with self.assertRaises(archives.ArchiveError) as cm:
                archives.extract(rar, self.tmp / "o")
        self.assertIn("unar", str(cm.exception))
        self.assertIn("brew install", str(cm.exception))


class AnalyzeTests(TmpCase):
    def test_a_zip_is_listed_and_its_files_are_read(self):
        z = make_zip(self.tmp / "pacote.zip", {"README.md": "# Meu jogo\nUm jogo de fazenda.", "docs/regras.txt": "Plante e colha.", "arte/sol.png": tiny_png(), "bin/x.dat": b"\0\1\2\3"})
        item = att.analyze(z, "pacote.zip")
        self.assertEqual(item["kind"], "archive")
        self.assertIn("[Pacote pacote.zip: 4 arquivo(s)", item["text"])
        self.assertIn("- docs/regras.txt", item["text"])
        self.assertIn("--- README.md ---\n# Meu jogo", item["text"])
        self.assertIn("Plante e colha.", item["text"])
        self.assertTrue(item["text"].index("README.md ---") < item["text"].index("regras.txt ---"))   # README primeiro
        self.assertEqual(len(item["images"]), 1)   # a imagem de dentro segue como imagem para modelos com visão
        digest = att.build_digest([item])
        self.assertIn("Anexo 1: pacote.zip (archive", digest)

    def test_a_password_zip_or_missing_tool_becomes_a_note_not_a_crash(self):
        bad = self.tmp / "q.zip"
        bad.write_bytes(b"PK\x03\x04lixo")
        item = att.analyze(bad, "q.zip")
        self.assertEqual(item["kind"], "archive")
        self.assertTrue(any("ZIP" in n for n in item["notes"]))
        rar = self.tmp / "q.rar"
        rar.write_bytes(b"Rar!\x1a\x07\x00x")
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "nada")}):
            item = att.analyze(rar, "q.rar")
        self.assertTrue(any("ferramenta" in n for n in item["notes"]))


class StoreTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.store = Store(self.tmp / "home")

    def upload(self, name, data):
        return self.store.save_upload_stream(name, "", io.BytesIO(data), len(data))

    def test_get_uploads_opens_packages_and_leaves_loose_files_alone(self):
        z = make_zip(self.tmp / "p.zip", {"a.txt": "AAA", "b/c.txt": "CCC"})
        up_zip, up_txt = self.upload("p.zip", z.read_bytes()), self.upload("solto.txt", b"solto")
        metas = self.store.get_uploads([up_zip["id"], up_txt["id"]])
        self.assertEqual([m["name"] for m in metas], ["p.zip/a.txt", "p.zip/b/c.txt", "solto.txt"])
        self.assertEqual(Path(metas[1]["path"]).read_text(), "CCC")
        self.assertTrue(metas[0]["id"].startswith(up_zip["id"] + ":"))
        self.assertEqual([m["name"] for m in self.store.get_uploads([up_zip["id"]], expand=False)], ["p.zip"])   # Rebuild usa o pacote cru
        self.assertTrue(self.store.delete_upload(metas[0]["id"]))   # apagar um arquivo de dentro apaga o anexo
        self.assertIsNone(self.store.get_upload(up_zip["id"]))

    def test_a_broken_package_stays_one_attachment_with_the_error(self):
        up = self.upload("quebrado.zip", b"PK\x03\x04nada")
        (m,) = self.store.get_uploads([up["id"]])
        self.assertIn("ZIP", m["error"])

    def test_the_package_is_opened_only_once(self):
        z = make_zip(self.tmp / "p.zip", {"a.txt": "AAA"})
        up = self.upload("p.zip", z.read_bytes())
        self.store.get_uploads([up["id"]])
        with mock.patch.object(archives, "expand", side_effect=AssertionError("abriu de novo")):
            self.assertEqual(len(self.store.get_uploads([up["id"]])), 1)


class UploadRouteTests(ServerCase):
    def test_canvas_upload_of_a_zip_imports_the_media_inside(self):
        _, cv = self.c.json("POST", "/api/projects", {"name": "Z", "template": "blank"})
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("um.png", tiny_png((1, 2, 3)))
            f.writestr("dois.png", tiny_png((9, 8, 7)))
            f.writestr("leia.txt", "não é mídia")
        status, a = self.c.json("POST", f"/api/projects/{cv['id']}/assets", raw=z.getvalue(), headers={"X-Filename": "imagens.zip", "Content-Type": "application/zip"})
        self.assertEqual(status, 201, a)
        self.assertEqual(a["kind"], "image")
        self.assertEqual(len(a["also"]), 1)
        _, full = self.c.json("GET", f"/api/projects/{cv['id']}")
        self.assertEqual(len(full["assets"]), 2)

    def test_canvas_zip_without_media_is_a_clear_400(self):
        _, cv = self.c.json("POST", "/api/projects", {"name": "Z2", "template": "blank"})
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("leia.txt", "só texto")
        status, r = self.c.json("POST", f"/api/projects/{cv['id']}/assets", raw=z.getvalue(), headers={"X-Filename": "texto.zip"})
        self.assertEqual(status, 400)
        self.assertIn("imagens, vídeos nem áudios", r["error"])

    def test_project_media_upload_of_a_zip_imports_the_media_inside(self):
        _, pr = self.c.json("POST", "/api/projects", {"name": "Z"})
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("a.png", tiny_png((5, 5, 5)))
        status, a = self.c.json("POST", f"/api/projects/{pr['id']}/assets", raw=z.getvalue(), headers={"X-Filename": "midias.zip"})
        self.assertEqual(status, 201, a)
        self.assertEqual(a["kind"], "image")
        self.assertEqual(a["also"], [])

    def test_general_upload_accepts_a_zip(self):
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("x.txt", "oi")
        status, meta = self.c.json("POST", "/api/uploads", raw=z.getvalue(), headers={"X-Filename": "x.zip", "Content-Type": "application/zip"})
        self.assertEqual(status, 200, meta)
        self.assertEqual(meta["name"], "x.zip")
        self.assertEqual([m["name"] for m in self.store.get_uploads([meta["id"]])], ["x.zip/x.txt"])


if __name__ == "__main__":
    unittest.main()
