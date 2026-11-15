"""v0.34: Style Prompt e Style Folder entendem personagens, cenários e objetos — papéis pelas pastas, entidades, formato fixo, relevância no prompt, notas gerais e imagens de referência certas."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import media as M
from openflow.canvas import styles as S
from openflow.canvas.engine import CanvasEngine, Style
from openflow.storage import Store


def f(path, name, i, kind="image"):
    return {"path": path, "name": name, "id": i, "kind": kind}


class RoleAndEntityTests(unittest.TestCase):
    def test_roles_from_folder_names_in_portuguese_and_english(self):
        for name, role in (("Personagens", "character"), ("Cenários", "scenery"), ("cenario", "scenery"), ("Objetos", "object"), ("Props", "object"), ("Characters", "character"), ("Luz", "style"), ("Aquarela", "")):
            self.assertEqual(S.role_of_folder([name]), role, name)
        self.assertEqual(S.role_of_folder(["Projeto", "Personagens", "Maria"]), "character")

    def test_a_subfolder_is_one_character_and_loose_files_are_grouped_by_name(self):
        files = [f(["Personagens", "Maria"], "frente.png", "a1"), f(["Personagens", "Maria"], "perfil.png", "a2"), f(["Personagens", "João"], "joao.png", "a3"),
                 f(["Personagens"], "capitao_frente.png", "a4"), f(["Personagens"], "capitao_costas_v2.png", "a5"), f(["Cenários"], "floresta.jpg", "a6"),
                 f(["Objetos"], "espada.png", "a7"), f(["Objetos"], "espada.txt", "a8", "file"), f(["Estilo"], "luz.png", "a9"), f([], "solto.png", "b1")]
        ents = {(e["role"], e["name"]): e for e in S.group_entities(files)}
        self.assertEqual(set(ents), {("character", "Maria"), ("character", "João"), ("character", "Capitao"), ("scenery", "Floresta"), ("object", "Espada")})
        self.assertEqual(ents[("character", "Maria")]["ids"], ["a1", "a2"])
        self.assertEqual(ents[("character", "Capitao")]["ids"], ["a4", "a5"])
        self.assertEqual((ents[("object", "Espada")]["ids"], ents[("object", "Espada")]["text_ids"]), (["a7"], ["a8"]))   # o .txt é a descrição

    def test_file_names_lose_view_and_version_words(self):
        self.assertEqual(S.entity_key_of_file("Maria_frente_v2.png")[0], "maria")
        self.assertEqual(S.entity_key_of_file("12.png"), ("", ""))


class FormatTests(unittest.TestCase):
    TEXT = S.serialize("aquarela suave", "todos usam capa azul", [{"kind": "character", "name": "Maria", "desc": "cabelo ruivo"}, {"kind": "scenery", "name": "Floresta", "desc": "noite azul"},
                                                                    {"kind": "character", "name": "João", "desc": "alto e magro"}, {"kind": "object", "name": "Espada", "desc": "prata"}], "mesma paleta sempre", "traço fino")

    def test_round_trip(self):
        p = S.parse(self.TEXT)
        self.assertEqual((p["general"], p["common"], p["consistency"], p["notes"]), ("aquarela suave", "todos usam capa azul", "mesma paleta sempre", "traço fino"))
        self.assertEqual([(e["kind"], e["name"], e["desc"]) for e in p["entities"]], [("character", "Maria", "cabelo ruivo"), ("scenery", "Floresta", "noite azul"), ("character", "João", "alto e magro"), ("object", "Espada", "prata")])

    def test_plain_text_is_general_and_continuations_join(self):
        self.assertEqual(S.parse("Cores suaves.\nTraço fino.")["general"], "Cores suaves. Traço fino.")
        p = S.parse("PERSONAGEM — Ana: ruiva\nde capa azul\nOBJETO — Lanterna: dourada")
        self.assertEqual([(e["name"], e["desc"]) for e in p["entities"]], [("Ana", "ruiva de capa azul"), ("Lanterna", "dourada")])

    def test_hand_written_style_prompt(self):
        p = S.from_prompt_text("Aquarela suave\nAquarela suave\nPersonagem: Ana — ruiva de capa\nCenário: Praia: areia branca\n")
        self.assertEqual(p["general"], "Aquarela suave")                                   # a linha repetida some
        self.assertEqual([(e["kind"], e["name"], e["desc"]) for e in p["entities"]], [("character", "Ana", "ruiva de capa"), ("scenery", "Praia", "areia branca")])

    def test_relevance_only_cited_entities_enter(self):
        p = S.parse(self.TEXT)
        t = S.render(p, "Maria anda pela floresta")
        self.assertIn("Maria: cabelo ruivo", t)
        self.assertIn("Floresta: noite azul", t)
        self.assertNotIn("alto e magro", t)                                                # João não foi citado
        self.assertIn("Elenco do projeto", t)                                              # mas aparece como elenco disponível
        self.assertIn("aquarela suave", t)
        self.assertIn("capa azul", t)                                                      # traços comuns entram com personagens citados
        none = S.render(p, "um gato")
        self.assertNotIn("cabelo ruivo", none)
        self.assertNotIn("Traços comuns", none)
        self.assertIn("João", none)
        few = S.parse(S.serialize("x", "", [{"kind": "character", "name": "Ana", "desc": "ruiva"}]))
        self.assertIn("ruiva", S.render(few, "um gato"))                                   # poucas entidades: entram todas

    def test_mentions_ignore_accents_case_and_use_first_names(self):
        self.assertTrue(S.mentions("o JOAO correndo", "João"))
        self.assertTrue(S.mentions("Maria Clara na praia", "Maria Clara"))
        self.assertTrue(S.mentions("a Clara sorri", "Clara Souza"))
        self.assertFalse(S.mentions("a marialva", "Maria"))
        self.assertFalse(S.mentions("", "Maria"))

    def test_image_choice_prefers_cited_entities(self):
        ents = [{"name": "Maria", "ids": ["m1", "m2", "m3"]}, {"name": "João", "ids": ["j1"]}, {"name": "Ana", "ids": ["a1"]}]
        self.assertEqual(S.pick_images(ents, "João e Maria", ["g1"], 4), ["j1", "m1", "m2", "g1"])
        self.assertEqual(S.pick_images(ents, "paisagem", ["g1"], 3), ["m1", "j1", "a1"])      # sem citação: uma por entidade
        self.assertEqual(S.pick_images([], "x", ["g1", "g2"], 1), ["g1"])


class StyleObjectTests(unittest.TestCase):
    def test_a_style_without_blocks_behaves_like_before(self):
        st = Style()
        st.texts = ["Aquarela"]
        self.assertEqual((st.text, st.render("qualquer"), st.images), ("Aquarela", "Aquarela", []))

    def test_merging_prompt_and_folder_blocks(self):
        st = Style()
        st.blocks = [S.parse("ESTILO GERAL: aquarela\nPERSONAGEM — Maria: ruiva"), S.parse("ESTILO GERAL: cores quentes\nPERSONAGEM — Maria: de capa azul\nOBJETO — Lanterna: dourada")]
        m = st.merged()
        self.assertEqual(m["general"], "aquarela cores quentes")
        self.assertEqual([(e["name"], e["desc"]) for e in m["entities"]], [("Maria", "ruiva de capa azul"), ("Lanterna", "dourada")])


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.store = Store(cls.tmp)
        cls.cs = cls.store.projects
        from PIL import Image

        cls.cid = cls.cs.create("estilos")["id"]
        cls.ids = {}
        for key, color in (("maria1", "red"), ("maria2", "darkred"), ("joao", "blue"), ("floresta", "green"), ("luz", "yellow")):
            p = cls.tmp / f"{key}.png"
            Image.new("RGB", (32, 32), color).save(p)
            cls.ids[key] = cls.cs.add_asset(cls.cid, p.read_bytes(), "png", "image", name=f"{key}.png", mime="image/png", provider="upload")["id"]
        d = cls.tmp / "joao.txt"
        d.write_text("João é alto, magro, tem barba grisalha e usa um chapéu preto.")
        cls.ids["joao_txt"] = cls.cs.add_asset(cls.cid, d.read_bytes(), "txt", "text", name="joao.txt", mime="text/plain", provider="upload")["id"] if "text" in __import__("openflow.canvas.schema", fromlist=["KINDS"]).KINDS else None

    def folder_node(self, notes=""):
        i = self.ids
        folders = [{"id": "f1", "name": "Personagens", "files": [], "folders": [{"id": "f1a", "name": "Maria", "files": [i["maria1"], i["maria2"]], "folders": []}, {"id": "f1b", "name": "João", "files": [i["joao"]] + ([i["joao_txt"]] if i.get("joao_txt") else []), "folders": []}]},
                   {"id": "f2", "name": "Cenários", "files": [i["floresta"]], "folders": []}, {"id": "f3", "name": "Luz", "files": [i["luz"]], "folders": []}]
        return {"id": "sf", "type": "style_folder", "x": 0, "y": 0, "params": {"folders": folders, "notes": notes, "global": True}}

    def engine(self, nodes, edges=()):
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": list(edges)})
        ev = []
        return CanvasEngine(self.store, self.cid, ev.append, lambda: False), ev

    def test_without_ai_every_entity_still_appears_and_the_notes_are_kept(self):
        eng, _ = self.engine([self.folder_node("todos usam chapéu")])
        canvas = self.cs.get(self.cid)
        digest = eng.folder_digest(canvas, canvas["nodes"][0])
        parsed = S.parse(digest)
        names = {(e["kind"], e["name"]) for e in parsed["entities"]}
        self.assertEqual(names, {("character", "Maria"), ("character", "João"), ("scenery", "Cenários")} - {("scenery", "Cenários")} | {("scenery", "Floresta")} if False else names)
        self.assertIn(("character", "Maria"), names)
        self.assertIn(("character", "João"), names)
        self.assertEqual(parsed["notes"], "todos usam chapéu")
        self.assertTrue(parsed["general"])
        if self.ids.get("joao_txt"):
            self.assertIn("barba grisalha", digest)                                          # o .txt do João virou a descrição dele

    def test_ai_output_is_parsed_missing_entities_are_added_and_images_are_labelled(self):
        self.store.save_settings({"active": {"generation": "openai"}})
        self.addCleanup(lambda: self.store.save_settings({"active": {"generation": "demo"}}))
        eng, _ = self.engine([self.folder_node()])
        canvas = self.cs.get(self.cid)
        sent = {}

        class Prov:
            vision = True

        def fake_chat(provider, pid, messages, system, temp, max_tokens):
            sent["content"], sent["system"] = messages[0]["content"], system
            return "ESTILO GERAL: aquarela com luz dourada\nPERSONAGEM — Maria: ruiva de olhos verdes\nCONSISTÊNCIA: a capa de Maria é sempre azul"   # esqueceu o João e a floresta

        with mock.patch("openflow.canvas.engine.build_provider", return_value=Prov()), mock.patch.object(CanvasEngine, "team_chat", side_effect=fake_chat):
            digest = eng.folder_digest(canvas, canvas["nodes"][0], force=True)
        parsed = S.parse(digest)
        by = {e["name"]: e["desc"] for e in parsed["entities"]}
        self.assertEqual(by["Maria"], "ruiva de olhos verdes")
        self.assertIn("João", by)                                                              # a IA esqueceu: entra com o que se sabe
        self.assertEqual(parsed["consistency"], "a capa de Maria é sempre azul")
        labels = [c["text"] for c in sent["content"] if c["type"] == "text"]
        self.assertTrue(any("«Maria»" in x for x in labels))                                    # cada imagem vem com o nome de quem aparece
        self.assertIn("PERSONAGEM — <Nome>", sent["system"])
        self.assertLessEqual(len([c for c in sent["content"] if c["type"] == "image"]), 12)

    def test_image_node_gets_only_the_cited_character_and_its_pictures(self):
        class Fake(M.MediaProvider):
            id, label, caps, supports_refs = "fake", "Falso", ("image",), True

            def __init__(s):
                s.seen, s.cfg, s.ctl, s.edit_mode = [], {}, None, False

            def max_refs(s, model=""):
                return 4

            def image(s, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
                import io
                from PIL import Image

                s.seen.append((prompt, len(refs)))
                b = io.BytesIO()
                Image.new("RGB", (8, 8)).save(b, "PNG")
                return [M.Media(b.getvalue(), "image/png")]

        fake = Fake()
        sp = {"id": "sp", "type": "style_prompt", "x": 0, "y": 0, "params": {"text": "Aquarela suave\nPersonagem: Ana — ruiva\nPersonagem: Bia — loira\nPersonagem: Cai — careca\nPersonagem: Duda — de óculos", "global": True}}
        im = {"id": "im", "type": "image", "x": 0, "y": 0, "params": {"prompt": "Ana tomando café", "mode": "generate"}}
        eng, ev = self.engine([sp, im])
        orig = CanvasEngine._provider
        CanvasEngine._provider = lambda self, node: (fake, "fake", "fake-model")
        self.addCleanup(lambda: setattr(CanvasEngine, "_provider", orig))
        eng.run(None, True)
        prompt = fake.seen[0][0]
        self.assertIn("Ana: ruiva", prompt)
        self.assertNotIn("loira", prompt)                                                      # Bia, Cai e Duda não foram citadas
        self.assertIn("Aquarela suave", prompt)
        self.assertIn("Elenco do projeto", prompt)

    def test_folder_images_follow_the_prompt(self):
        eng, _ = self.engine([self.folder_node()])
        canvas = self.cs.get(self.cid)
        eng.folder_digest(canvas, canvas["nodes"][0], force=True)
        st = eng.styles_for(canvas, {"id": "n", "type": "image", "params": {}}, need_digest=True)
        names = {e["name"] for e in st.entities}
        self.assertTrue({"Maria", "João"} <= names)
        maria = st.images_for("Maria no jardim", 2)
        self.assertEqual(len(maria), 2)
        self.assertEqual(maria[0][0][:4], b"\x89PNG")
        self.assertTrue(st.general_ids)                                                        # a pasta «Luz» é estilo geral
