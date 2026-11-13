"""Style Folder com pastas e subpastas: validação, o que entra no estilo, renomear/mover, envio direto numa pasta e pesquisa pelo nome da pasta."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow.canvas import procedural as proc  # noqa: E402
from openflow.canvas import schema as S  # noqa: E402
from openflow.canvas.engine import CanvasEngine  # noqa: E402
from openflow.storage import Store  # noqa: E402
from tests.helpers import ServerCase, TmpCase  # noqa: E402

PNG = proc.image("estilo", "64x64", 1)


def folder(name, files=(), folders=(), **kw):
    return {"name": name, "files": list(files), "folders": list(folders), **kw}


class NormalizeTests(unittest.TestCase):
    def test_tree_is_validated_and_gets_ids(self):
        p = S.normalize_params("style_folder", {"files": ["a"], "folders": [folder("Aquarela", ["b"], [folder("Detalhes", ["c"])]), "lixo", None]})
        self.assertEqual([f["name"] for f in p["folders"]], ["Aquarela", "Pasta", "Pasta (2)"])      # entradas inválidas viram pastas «Pasta» (nome padrão, único entre irmãs)
        top = p["folders"][0]
        self.assertTrue(top["id"].startswith("f_") and top["folders"][0]["id"] != top["id"])
        self.assertEqual((top["enabled"], top["open"], top["folders"][0]["files"]), (True, True, ["c"]))
        self.assertEqual(S.normalize_params("style_folder", {})["folders"], [])      # projetos antigos (sem pastas) abrem iguais

    def test_names_are_unique_among_siblings_cleaned_and_limited(self):
        p = S.normalize_params("style_folder", {"folders": [folder("Luz"), folder("luz"), folder("LUZ "), folder("a/b\\c"), folder("x" * 100)]})
        names = [f["name"] for f in p["folders"]]
        self.assertEqual(names[:3], ["Luz", "luz (2)", "LUZ (3)"])
        self.assertEqual(names[3], "a-b-c")                  # barras não entram no nome (o nome vira parte de um caminho no resumo do estilo)
        self.assertEqual(len(names[4]), S.MAX_FOLDER_NAME)
        inner = S.normalize_params("style_folder", {"folders": [folder("Luz", folders=[folder("Luz")])]})["folders"][0]
        self.assertEqual(inner["folders"][0]["name"], "Luz")  # em níveis diferentes o mesmo nome vale

    def test_depth_and_count_are_limited(self):
        deep = folder("n0")
        cur = deep
        for i in range(1, 12):
            nxt = folder(f"n{i}")
            cur["folders"] = [nxt]
            cur = nxt
        p = S.normalize_params("style_folder", {"folders": [deep]})
        depth, f = 0, p["folders"][0]
        while f:
            depth += 1
            f = f["folders"][0] if f["folders"] else None
        self.assertEqual(depth, S.MAX_FOLDER_DEPTH)
        wide = S.normalize_params("style_folder", {"folders": [folder(f"p{i}") for i in range(200)]})
        self.assertEqual(len(wide["folders"]), S.MAX_FOLDERS)

    def test_ids_never_repeat_and_bad_ids_are_replaced(self):
        p = S.normalize_params("style_folder", {"folders": [folder("a", id="f_x"), folder("b", id="f_x"), folder("c", id="../hack")]})
        ids = [f["id"] for f in p["folders"]]
        self.assertEqual(len(set(ids)), 3)
        self.assertTrue(all(S.re.match(r"^[\w-]+$", i) for i in ids))

    def test_style_files_skip_disabled_folders_and_repeats(self):
        p = S.normalize_params("style_folder", {"files": ["r"], "folders": [folder("A", ["a", "r"], [folder("A1", ["a1"])]), folder("B", ["b"], enabled=False, folders=[folder("B1", ["b1"])]), folder("C", ["c"])]})
        self.assertEqual(S.style_files(p), [([], "r"), (["A"], "a"), (["A", "A1"], "a1"), (["C"], "c")])
        self.assertEqual(sorted(S.all_folder_files(p["folders"])), ["a", "a1", "b", "b1", "c", "r"])

    def test_find_folder_and_unknown_files_are_pruned_with_the_project(self):
        cv = S.normalize_canvas({"nodes": [{"id": "sf", "type": "style_folder", "params": {"files": ["x"], "folders": [folder("A", ["x", "gone"], [folder("A1", ["gone"])])]}}],
                                 "assets": [{"id": "x", "kind": "image", "file": "x.png"}]})
        p = cv["nodes"][0]["params"]
        self.assertEqual((p["files"], p["folders"][0]["files"], p["folders"][0]["folders"][0]["files"]), (["x"], ["x"], []))
        self.assertEqual(S.find_folder(p["folders"], p["folders"][0]["folders"][0]["id"])["name"], "A1")
        self.assertIsNone(S.find_folder(p["folders"], "nao-existe"))


class StoreTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.store = Store(self.tmp)
        self.cs = self.store.projects
        self.cv = self.cs.create("Estilos")

    def with_files(self, folders_for):
        ids = [self.cs.add_asset(self.cv["id"], PNG, "png", "image", name=f"ref{i}.png", mime="image/png")["id"] for i in range(3)]
        self.assertTrue(self.cs.save_layout(self.cv["id"], {"nodes": [{"id": "sf", "type": "style_folder", "params": folders_for(ids)}]}))
        return ids

    def test_deleting_a_file_leaves_every_folder(self):
        ids = self.with_files(lambda i: {"files": [i[0]], "folders": [folder("A", [i[0], i[1]], [folder("B", [i[1], i[2]])])]})
        self.assertTrue(self.cs.delete_asset(self.cv["id"], ids[1]))
        p = self.cs.get(self.cv["id"])["nodes"][0]["params"]
        self.assertEqual((p["folders"][0]["files"], p["folders"][0]["folders"][0]["files"]), ([ids[0]], [ids[2]]))

    def test_files_in_folders_count_as_in_use(self):
        ids = self.with_files(lambda i: {"folders": [folder("A", [i[0]], [folder("B", [i[1]])])]})
        used = self.cs.referenced_assets(self.cs.get(self.cv["id"]))
        self.assertEqual(used, {ids[0], ids[1]})

    def test_the_layout_save_keeps_the_tree_the_browser_sent(self):
        self.with_files(lambda i: {"folders": [folder("Aquarela", [i[0]]), folder("Luz")]})
        cur = self.cs.get(self.cv["id"])["nodes"][0]["params"]
        cur["folders"][0]["name"] = "Aquarela 2"
        cur["folders"][1]["enabled"] = False
        self.cs.save_layout(self.cv["id"], {"nodes": [{"id": "sf", "type": "style_folder", "params": cur}]})
        again = self.cs.get(self.cv["id"])["nodes"][0]["params"]
        self.assertEqual([(f["name"], f["enabled"]) for f in again["folders"]], [("Aquarela 2", True), ("Luz", False)])


class EngineTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.store = Store(self.tmp)
        self.cs = self.store.projects
        self.cv = self.cs.create("Estilos")
        self.ids = [self.cs.add_asset(self.cv["id"], proc.image(f"ref{i}", "64x64", i), "png", "image", name=f"ref{i}.png", mime="image/png")["id"] for i in range(3)]

    def style(self, folders, files=()):
        self.cs.save_layout(self.cv["id"], {"nodes": [{"id": "sf", "type": "style_folder", "params": {"files": list(files), "folders": folders, "global": True}},
                                                      {"id": "im", "type": "image", "params": {"prompt": "um gato"}}]})
        eng = CanvasEngine(self.store, self.cv["id"])
        c = eng.canvas()
        return eng, c, eng._node(c, "im")

    def test_references_in_subfolders_count_and_disabled_folders_do_not(self):
        eng, c, im = self.style([folder("Rosto", [self.ids[1]], [folder("Olhos", [self.ids[2]])]), folder("Fora", [self.ids[0]], enabled=False)])
        st = eng.styles_for(c, im)
        self.assertEqual(len(st.images), 2)                                  # os dois arquivos ligados; o da pasta desligada fica de fora
        eng2, c2, im2 = self.style([folder("Rosto", [self.ids[1]], [folder("Olhos", [self.ids[2]])]), folder("Fora", [self.ids[0]], enabled=True)])
        st2 = eng2.styles_for(c2, im2)
        self.assertEqual(len(st2.images), 3)                                 # ligando a pasta, o arquivo entra…
        self.assertNotEqual(st.signature(), st2.signature())                 # …e o nó passa a contar como desatualizado

    def test_the_digest_lists_the_folder_names_and_changes_when_a_folder_is_renamed_or_a_file_moves(self):
        eng, c, _ = self.style([folder("Personagens", [self.ids[0]]), folder("Cenários", [self.ids[1]])])
        sf = eng._node(c, "sf")
        text = eng.folder_digest(c, sf)
        self.assertTrue(text)
        key_a = eng.folder_key(c, sf)
        # renomear a pasta muda a chave (a descrição é refeita)
        eng2, c2, _ = self.style([folder("Heróis", [self.ids[0]]), folder("Cenários", [self.ids[1]])])
        key_b = eng2.folder_key(c2, eng2._node(c2, "sf"))
        self.assertNotEqual(key_a, key_b)
        # mover o arquivo de pasta também
        eng3, c3, _ = self.style([folder("Heróis", []), folder("Cenários", [self.ids[1], self.ids[0]])])
        self.assertNotEqual(key_b, eng3.folder_key(c3, eng3._node(c3, "sf")))
        # desligar uma pasta muda o que vale, logo a chave
        eng4, c4, _ = self.style([folder("Heróis", [self.ids[0]], enabled=False), folder("Cenários", [self.ids[1]])])
        self.assertNotEqual(key_b, eng4.folder_key(c4, eng4._node(c4, "sf")))

    def test_folder_names_reach_the_analysis_of_the_references(self):
        seen = {}
        from openflow import attachments as att

        real = att.analyze

        def spy(path, name, mime, max_chars=0):
            seen.setdefault("names", []).append(name)
            return real(path, name, mime, max_chars=max_chars)

        eng, c, _ = self.style([folder("Personagens", [self.ids[0]], [folder("Rosto", [self.ids[1]])])], files=[self.ids[2]])
        from unittest import mock

        with mock.patch.object(att, "analyze", spy):
            eng.folder_digest(c, eng._node(c, "sf"), force=True)
        self.assertEqual(sorted(seen["names"]), ["Personagens/Rosto/ref1.png", "Personagens/ref0.png", "ref2.png"])


class ApiTests(ServerCase):
    def project(self, name="Pastas"):
        s, p = self.c.json("POST", "/api/projects", {"name": name, "template": "blank"})
        self.assertEqual(s, 201)
        return p["id"]

    def test_upload_straight_into_a_subfolder(self):
        pid = self.project()
        tree = [folder("Aquarela", [], [folder("Detalhes")], id="f_a")]
        tree[0]["folders"][0]["id"] = "f_b"
        self.c.json("PUT", f"/api/projects/{pid}", {"name": "Pastas", "nodes": [{"id": "sf", "type": "style_folder", "params": {"folders": tree}}]})
        s, a = self.c.json("POST", f"/api/projects/{pid}/assets?node=sf&folder=f_b", raw=PNG, headers={"X-Filename": "ref.png", "Content-Type": "image/png"})
        self.assertEqual(s, 201, a)
        p = self.c.json("GET", f"/api/projects/{pid}")[1]["nodes"][0]["params"]
        self.assertEqual((p["files"], p["folders"][0]["files"], p["folders"][0]["folders"][0]["files"]), ([], [], [a["id"]]))
        # pasta desconhecida: o arquivo vai para a raiz do nó
        s, b = self.c.json("POST", f"/api/projects/{pid}/assets?node=sf&folder=f_zzz", raw=PNG, headers={"X-Filename": "ref2.png", "Content-Type": "image/png"})
        p = self.c.json("GET", f"/api/projects/{pid}")[1]["nodes"][0]["params"]
        self.assertEqual(p["files"], [b["id"]])

    def test_the_templates_route_lists_the_empty_tree_as_default(self):
        s, meta = self.c.json("GET", "/api/project-templates")
        self.assertEqual(s, 200)
        self.assertEqual(meta["defaults"]["style_folder"]["folders"], [])

    def test_search_finds_a_project_by_the_name_of_a_style_folder(self):
        pid = self.project("Campanha de verão")
        self.c.json("PUT", f"/api/projects/{pid}", {"name": "Campanha de verão", "nodes": [{"id": "sf", "type": "style_folder", "params": {"folders": [folder("Paleta tropical")]}}]})
        s, r = self.c.json("GET", "/api/projects?q=tropical")
        self.assertEqual(s, 200)
        hit = next(x for x in r if x["id"] == pid)
        self.assertEqual(hit["match"], "pasta de estilo: Paleta tropical")


if __name__ == "__main__":
    unittest.main()
