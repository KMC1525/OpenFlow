"""v0.27: Biblioteca 2.0 — pastas e subpastas virtuais para modelos e arquivos, busca em todas as pastas, mover itens e importar arquivos para outro projeto."""
import tempfile
import unittest
from pathlib import Path

from openflow.libfolders import LibraryError, LibraryFolders
from tests.helpers import ServerCase

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class FolderStoreTests(unittest.TestCase):
    def setUp(self):
        self.lf = LibraryFolders(Path(tempfile.mkdtemp()) / "library.json")

    def test_create_nest_rename_and_unique_names(self):
        a = self.lf.create("Animais", "", "files")
        b = self.lf.create("Pets", a["id"], "files")
        self.assertEqual([x["name"] for x in self.lf.path_of(b["id"])], ["Animais", "Pets"])
        with self.assertRaises(LibraryError) as cm:
            self.lf.create("animais", "", "files")                    # sem diferenciar maiúsculas
        self.assertEqual(cm.exception.status, 409)
        self.lf.create("Animais", "", "models")                      # escopos separados: o mesmo nome vale
        self.assertEqual(self.lf.update(b["id"], name="Gatos")["name"], "Gatos")
        with self.assertRaises(LibraryError):
            self.lf.create("   ", "", "files")

    def test_a_folder_cannot_go_inside_itself_or_across_scopes(self):
        a = self.lf.create("A", "", "files")
        b = self.lf.create("B", a["id"], "files")
        with self.assertRaises(LibraryError):
            self.lf.update(a["id"], parent=b["id"])                  # ciclo
        with self.assertRaises(LibraryError):
            self.lf.update(a["id"], parent=a["id"])
        m = self.lf.create("M", "", "models")
        with self.assertRaises(LibraryError):
            self.lf.update(a["id"], parent=m["id"])
        with self.assertRaises(LibraryError):
            self.lf.create("X", m["id"], "files")

    def test_items_only_go_to_folders_of_their_kind(self):
        f, m = self.lf.create("F", "", "files"), self.lf.create("M", "", "models")
        self.assertEqual(self.lf.place(["file:p/as_1"], f["id"]), 1)
        with self.assertRaises(LibraryError):
            self.lf.place(["model:image/x.gguf"], f["id"])
        self.assertEqual(self.lf.place(["model:image/x.gguf"], m["id"]), 1)
        self.assertEqual(self.lf.placements(), {"file:p/as_1": f["id"], "model:image/x.gguf": m["id"]})
        self.lf.place(["file:p/as_1"], "")                           # volta para a raiz
        self.assertNotIn("file:p/as_1", self.lf.placements())

    def test_deleting_a_folder_lifts_its_contents_and_never_loses_them(self):
        a = self.lf.create("A", "", "files")
        b = self.lf.create("B", a["id"], "files")
        self.lf.place(["file:p/1"], b["id"])
        self.lf.place(["file:p/2"], a["id"])
        self.lf.delete(b["id"])
        self.assertEqual(self.lf.placements()["file:p/1"], a["id"])
        self.lf.delete(a["id"])
        self.assertEqual(self.lf.placements(), {})                   # na raiz: sem pasta
        self.assertEqual(self.lf.folders(), [])

    def test_survives_a_corrupted_file(self):
        self.lf.path.write_text("{ not json")
        self.assertEqual(self.lf.folders(), [])
        self.lf.create("Novo", "", "files")                           # e volta a funcionar


class ApiTests(ServerCase):
    def setUp(self):
        self.app.library_routes.folders.path.unlink(missing_ok=True)   # o servidor é compartilhado entre os testes: cada um começa sem pastas

    def project(self, name):
        s, c = self.c.json("POST", "/api/projects", {"name": name})
        self.assertEqual(s, 201, c)
        return c["id"]

    def test_tree_items_search_and_move_through_the_api(self):
        cs = self.app.project_routes.cs
        p1, p2 = self.project("Filme"), self.project("Livro")
        a1 = cs.add_asset(p1, PNG, "png", "image", name="lib27-gato.png", mime="image/png", provider="gguf_local", model="lib27-z-image")
        a2 = cs.add_asset(p2, PNG, "png", "image", name="lib27-paisagem.png", mime="image/png", provider="upload")
        k1, k2 = f"file:{p1}/{a1['id']}", f"file:{p2}/{a2['id']}"
        s, animais = self.c.json("POST", "/api/library/folders", {"name": "Animais", "scope": "files"})
        self.assertEqual(s, 201)
        s, pets = self.c.json("POST", "/api/library/folders", {"name": "Pets", "scope": "files", "parent": animais["id"]})
        self.assertEqual(self.c.json("POST", "/api/library/move", {"items": [k1], "folder": pets["id"]})[1], {"moved": 1})
        _, root = self.c.json("GET", "/api/library/items?scope=files")
        self.assertEqual(([f["name"] for f in root["folders"]], [i["name"] for i in root["items"] if i["project"] in (p1, p2)]), (["Animais"], ["lib27-paisagem.png"]))   # o gato está em Animais/Pets
        self.assertEqual(root["folders"][0]["count"], 1)
        _, inside = self.c.json("GET", f"/api/library/items?scope=files&folder={pets['id']}")
        self.assertEqual(([i["name"] for i in inside["items"]], [p["name"] for p in inside["path"]]), (["lib27-gato.png"], ["Animais", "Pets"]))
        _, found = self.c.json("GET", "/api/library/items?scope=files&q=lib27-gato")
        self.assertTrue(found["search"])
        hit = next(i for i in found["items"] if i["project"] == p1)
        self.assertEqual((hit["name"], hit["path"]), ("lib27-gato.png", "Animais / Pets"))
        self.assertEqual([i["name"] for i in self.c.json("GET", "/api/library/items?scope=files&q=lib27-z")[1]["items"]], ["lib27-gato.png"])   # acha pelo modelo
        self.assertEqual([f["name"] for f in self.c.json("GET", "/api/library/items?scope=files&q=pets")[1]["folders"]], ["Pets"])           # e pela pasta
        self.assertEqual([i["name"] for i in self.c.json("GET", "/api/library/items?scope=files&source=upload")[1]["items"] if i["project"] == p2], ["lib27-paisagem.png"])
        self.assertEqual(self.c.json("GET", "/api/library/items?scope=files&folder=lf_nope")[0], 404)

    def test_models_are_listed_and_organised_separately(self):
        d = self.store.models_dir / "image"
        d.mkdir(parents=True, exist_ok=True)
        (d / "flux-Q4_K_M.gguf").write_bytes(b"g")
        s, m = self.c.json("POST", "/api/library/folders", {"name": "Imagem", "scope": "models"})
        self.assertEqual(self.c.json("POST", "/api/library/move", {"items": ["model:image/flux-Q4_K_M.gguf"], "folder": m["id"]})[0], 200)
        self.assertEqual([i["name"] for i in self.c.json("GET", f"/api/library/items?scope=models&folder={m['id']}")[1]["items"]], ["flux-Q4_K_M.gguf"])
        self.assertEqual([i["name"] for i in self.c.json("GET", "/api/library/items?scope=models")[1]["items"] if i["name"] == "flux-Q4_K_M.gguf"], [])
        s, f = self.c.json("POST", "/api/library/folders", {"name": "Arq", "scope": "files"})
        self.assertEqual(self.c.json("POST", "/api/library/move", {"items": ["model:image/flux-Q4_K_M.gguf"], "folder": f["id"]})[0], 400)   # modelo em pasta de arquivos

    def test_rename_move_and_delete_folders(self):
        _, a = self.c.json("POST", "/api/library/folders", {"name": "A", "scope": "files"})
        _, b = self.c.json("POST", "/api/library/folders", {"name": "B", "scope": "files"})
        self.assertEqual(self.c.json("PUT", f"/api/library/folders/{b['id']}", {"name": "Bb", "parent": a["id"]})[1]["parent"], a["id"])
        self.assertEqual(self.c.json("PUT", f"/api/library/folders/{a['id']}", {"parent": b["id"]})[0], 400)
        self.assertEqual(self.c.json("DELETE", f"/api/library/folders/{a['id']}")[0], 200)
        self.assertEqual([f["parent"] for f in self.c.json("GET", "/api/library/folders?scope=files")[1]["folders"] if f["name"] == "Bb"], [""])
        self.assertEqual(self.c.json("GET", "/api/library/folders?scope=x")[0], 400)

    def test_import_copies_a_file_into_another_project(self):
        cs = self.app.project_routes.cs
        p1, p2 = self.project("Origem"), self.project("Destino")
        a = cs.add_asset(p1, PNG, "png", "image", name="lib27-gato.png", mime="image/png", provider="gguf_local", model="z", prompt="um gato")
        s, r = self.c.json("POST", f"/api/projects/{p2}/assets/import", {"project": p1, "asset": a["id"]})
        self.assertEqual(s, 201, r)
        self.assertEqual((r["name"], r["model"], r["prompt"], r["provider"]), ("lib27-gato.png", "z", "um gato", "gguf_local"))
        self.assertNotEqual(r["id"], a["id"])
        self.assertTrue(cs.asset_path(p2, r["file"]))
        s, same = self.c.json("POST", f"/api/projects/{p1}/assets/import", {"project": p1, "asset": a["id"]})
        self.assertEqual(same["id"], a["id"])                                    # no mesmo projeto não duplica
        self.assertEqual(self.c.json("POST", f"/api/projects/{p2}/assets/import", {"project": p1, "asset": "as_nope"})[0], 404)
