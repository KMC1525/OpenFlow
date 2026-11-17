"""v0.73: system prompts internos do Style Folder e do Style Prompt — o OpenFlow instrui a IA por conta própria para descrever as pastas com precisão (FOLDER_SYSTEM), organizar o texto livre do Style Prompt no formato
fixo (PROMPT_SYSTEM) e usar o estilo sem atropelar o pedido (APPLY_RULES).

A IA é de mentira (devolve o que o teste manda); que um modelo de texto de verdade siga essas regras, e o quanto isso melhora as imagens, NÃO foi medido."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import engine as engine_mod
from openflow.canvas import lyrics, schema
from openflow.canvas import media as M
from openflow.canvas import styles as S
from openflow.canvas.engine import CanvasEngine
from openflow.providers import ProviderError
from openflow.storage import Store

PROSE = ("O projeto é uma animação em aquarela com cores suaves, traço fino e luz dourada de fim de tarde, sempre com enquadramentos abertos. Ana é uma menina ruiva de olhos verdes que usa uma capa azul. "
         "Bia é loira, baixinha e usa óculos redondos. Caio é careca, alto e usa um colete marrom. Duda tem tranças longas e jaqueta amarela. Nunca use preto puro.")
STRUCTURED = ("ESTILO GERAL: animação em aquarela, cores suaves, traço fino, luz dourada de fim de tarde\nPERSONAGEM — Ana: menina ruiva de olhos verdes e capa azul\nPERSONAGEM — Bia: loira, baixinha, óculos redondos\n"
              "PERSONAGEM — Caio: careca, alto, colete marrom\nPERSONAGEM — Duda: tranças longas e jaqueta amarela\nCONSISTÊNCIA: nunca usar preto puro")


class PureTests(unittest.TestCase):
    def test_the_internal_prompts_carry_the_rules(self):
        self.assertIn("PERSONAGEM — <Nome>", S.FOLDER_SYSTEM)                                   # o formato que o parser lê continua
        self.assertIn("ESTILO GERAL", S.FOLDER_SYSTEM)
        self.assertIn("REGRAS DE PRECISÃO", S.FOLDER_SYSTEM)
        self.assertIn("nunca invente", S.FOLDER_SYSTEM)
        self.assertIn("a nota vence", S.FOLDER_SYSTEM)
        self.assertIn("NÃO invente", S.PROMPT_SYSTEM)
        self.assertIn("@menções", S.PROMPT_SYSTEM)
        for head in ("ESTILO GERAL:", "PERSONAGEM — <Nome>:", "CENÁRIO — <Nome>:", "OBJETO — <Nome>:", "CONSISTÊNCIA:"):
            self.assertIn(head, S.PROMPT_SYSTEM)
        self.assertIs(engine_mod.STYLE_SYSTEM, S.FOLDER_SYSTEM)

    def test_the_format_the_prompts_ask_for_is_the_format_the_parser_reads(self):
        sample = "\n".join(l.split(":", 1)[0] + ": exemplo" for l in S.PROMPT_SYSTEM.splitlines() if l.startswith(("ESTILO GERAL:", "PERSONAGEM", "CENÁRIO", "OBJETO", "CONSISTÊNCIA")))
        sample = sample.replace("<Nome>", "Ana")
        p = S.parse(sample)
        self.assertEqual(p["general"], "exemplo")
        self.assertEqual({e["kind"] for e in p["entities"]}, {"character", "scenery", "object"})
        self.assertEqual(p["consistency"], "exemplo")

    def test_apply_block(self):
        self.assertEqual(S.apply_block(""), "")
        self.assertEqual(S.apply_block("   ", "en"), "")
        pt, en = S.apply_block("aquarela"), S.apply_block("aquarela", "en")
        self.assertTrue(pt.startswith("\n\nREGRAS DE USO DO ESTILO DO PROJETO") and pt.endswith("Estilo do projeto: aquarela"))
        self.assertIn("the request wins", en)
        self.assertTrue(en.endswith("Project style: aquarela"))

    def test_media_style_is_short_and_says_it_is_the_look(self):
        self.assertEqual(S.media_style(""), "")
        out = S.media_style("aquarela suave")
        self.assertIn("not its subject or action", out)
        self.assertTrue(out.endswith("aquarela suave"))
        self.assertLess(len(S.MEDIA_STYLE_LABEL), 90)                                            # poucos tokens: modelos de imagem leem pouco

    def test_the_chatter_around_the_answer_is_dropped(self):
        self.assertEqual(S.strip_preamble("Claro! Aqui está:\n```\nESTILO GERAL: aquarela\nPERSONAGEM — Ana: ruiva\n```"), "ESTILO GERAL: aquarela\nPERSONAGEM — Ana: ruiva")
        self.assertEqual(S.strip_preamble("Claro! Aqui está o seu estilo: ótimo projeto."), "")
        self.assertEqual(S.strip_preamble(""), "")

    def test_which_style_prompts_deserve_the_ai(self):
        self.assertTrue(S.needs_structuring(PROSE))
        self.assertFalse(S.needs_structuring("Ilustração em aquarela, cores suaves, traço delicado"))      # curto
        self.assertFalse(S.needs_structuring(STRUCTURED))                                                    # já no formato
        self.assertFalse(S.needs_structuring("Personagem: Ana — ruiva\n" + "x" * 200))                       # tem cabeçalho
        self.assertFalse(S.needs_structuring(""))


class SchemaTests(unittest.TestCase):
    def test_refine_param(self):
        self.assertTrue(schema.normalize_params("style_prompt", {})["refine"])
        self.assertFalse(schema.normalize_params("style_prompt", {"refine": False})["refine"])
        self.assertTrue(schema.normalize_params("style_prompt", {"text": "x", "global": False})["refine"])

    def test_lyrics_system_prompt_gets_the_rules(self):
        sp = lyrics.system_prompt({"language": "pt", "structure": "song", "rhyme": "aabb", "genre": "", "mood": ""}, "aquarela")
        self.assertIn("RULES FOR USING THE PROJECT STYLE", sp)
        self.assertIn("Project style: aquarela", sp)
        self.assertNotIn("RULES FOR USING", lyrics.system_prompt({"language": "pt", "structure": "song", "rhyme": "aabb"}))


class Fake(M.MediaProvider):
    id, label, caps, supports_refs = "fake", "Falso", ("image",), False

    def __init__(self):
        self.seen, self.cfg, self.ctl, self.edit_mode = [], {}, None, False

    def image(self, prompt, *, size="1024x1024", count=1, seed=0, negative="", refs=(), model="", extra=None):
        import io
        from PIL import Image

        self.seen.append(prompt)
        b = io.BytesIO()
        Image.new("RGB", (8, 8)).save(b, "PNG")
        return [M.Media(b.getvalue(), "image/png")]


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()))
        self.cs = self.store.projects
        self.cid = self.cs.create("estilo")["id"]
        self.chats = []
        self.reply = STRUCTURED

    def engine(self, nodes, edges=()):
        self.cs.save_layout(self.cid, {"nodes": nodes, "edges": list(edges)})
        self.ev = []
        return CanvasEngine(self.store, self.cid, self.ev.append, lambda: False)

    def with_ai(self):
        self.store.save_settings({"active": {"generation": "openai"}})

    def chat(self, provider, messages, system, temp, max_tokens):
        self.chats.append((messages[0]["content"], system))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply

    def sp(self, text=PROSE, **params):
        return {"id": "sp", "type": "style_prompt", "x": 0, "y": 0, "params": dict({"text": text, "global": True}, **params)}

    def digest(self, eng):
        cv = self.cs.get(self.cid)
        node = next(n for n in cv["nodes"] if n["id"] == "sp")
        with mock.patch("openflow.canvas.engine.build_provider", return_value=object()), mock.patch.object(CanvasEngine, "text_chat", side_effect=self.chat):
            return eng.prompt_digest(cv, node), cv, node

    def test_the_ai_organizes_a_long_style_prompt_with_the_internal_prompt(self):
        self.with_ai()
        eng = self.engine([self.sp()])
        out, _, _ = self.digest(eng)
        self.assertEqual(self.chats[0][1], S.PROMPT_SYSTEM)
        self.assertEqual(self.chats[0][0], PROSE)                                           # o texto do usuário vai como está
        parsed = S.parse(out)
        self.assertEqual(sorted(e["name"] for e in parsed["entities"]), ["Ana", "Bia", "Caio", "Duda"])
        self.assertEqual(parsed["consistency"], "nunca usar preto puro")

    def test_the_result_is_cached_until_the_text_or_the_model_changes(self):
        self.with_ai()
        eng = self.engine([self.sp()])
        self.digest(eng)
        self.digest(eng)
        self.assertEqual(len(self.chats), 1)
        eng = self.engine([self.sp(PROSE + " Cenas sempre ao ar livre.")])
        self.digest(eng)
        self.assertEqual(len(self.chats), 2)

    def test_styles_for_uses_the_organized_text_and_only_cited_characters_enter_the_prompt(self):
        self.with_ai()
        fake = Fake()
        im = {"id": "im", "type": "image", "x": 0, "y": 0, "params": {"prompt": "Ana tomando café", "mode": "generate"}}
        eng = self.engine([self.sp(), im])
        orig = CanvasEngine._provider
        self.addCleanup(lambda: setattr(CanvasEngine, "_provider", orig))
        CanvasEngine._provider = lambda self, node: (fake, "fake", "fake-model")
        with mock.patch("openflow.canvas.engine.build_provider", return_value=object()), mock.patch.object(CanvasEngine, "text_chat", side_effect=self.chat):
            eng.run(None, True)
        prompt = fake.seen[0]
        self.assertIn("Ana", prompt)
        self.assertIn("menina ruiva de olhos verdes", prompt)
        self.assertNotIn("óculos redondos", prompt)                                      # Bia, Caio e Duda não foram citados: com o texto corrido antes, entravam todos
        self.assertIn("Style guide (the look of the whole result", prompt)               # o estilo chega com a moldura curta
        self.assertIn("aquarela", prompt)

    def test_without_the_ai_the_text_is_used_as_before(self):
        eng = self.engine([self.sp()])                                                   # provedor Demo
        cv = self.cs.get(self.cid)
        st = eng.styles_for(cv, {"id": "n", "type": "image", "params": {"ignore_global_styles": False}})
        self.assertEqual(st.texts, [PROSE])
        self.assertEqual(self.chats, [])

    def test_the_switch_the_short_text_and_the_structured_text_skip_the_ai(self):
        self.with_ai()
        for params in ({"text": PROSE, "refine": False}, {"text": "Aquarela suave, cores quentes"}, {"text": STRUCTURED}):
            eng = self.engine([self.sp(**params)])
            cv = self.cs.get(self.cid)
            with mock.patch("openflow.canvas.engine.build_provider", return_value=object()), mock.patch.object(CanvasEngine, "text_chat", side_effect=self.chat):
                eng.styles_for(cv, {"id": "n", "type": "image", "params": {}})
            self.assertEqual(self.chats, [], params)

    def test_a_bad_answer_or_an_error_falls_back_to_the_original_text(self):
        self.with_ai()
        for reply in ("Claro! Aqui está o seu estilo: ótimo projeto.", ProviderError("sem créditos")):
            self.reply = reply
            eng = self.engine([self.sp(PROSE + f" {id(reply)}")])
            out, cv, node = self.digest(eng)
            self.assertEqual(out, "")
            st = eng.styles_for(cv, {"id": "n", "type": "image", "params": {}}, need_digest=False)
            self.assertTrue(st.texts[0].startswith("O projeto é uma animação"))
        self.assertTrue(any(e.get("type") == "note" and "Style Prompt" in e.get("message", "") for e in self.ev))

    def test_changing_the_style_prompt_makes_the_dependent_node_stale(self):
        self.with_ai()
        eng = self.engine([self.sp()])
        cv = self.cs.get(self.cid)
        node = {"id": "im", "type": "image", "params": {}}
        before = eng.styles_for(cv, node, need_digest=False).signature()
        cv2 = {**cv, "nodes": [dict(cv["nodes"][0], params=dict(cv["nodes"][0]["params"], refine=False))]}
        after = eng.styles_for(cv2, node, need_digest=False).signature()
        self.assertNotEqual(before, after)

    def test_the_folder_digest_uses_the_internal_prompt(self):
        from PIL import Image

        self.with_ai()
        tmp = Path(tempfile.mkdtemp())
        pth = tmp / "maria.png"
        Image.new("RGB", (16, 16), "red").save(pth)
        a = self.cs.add_asset(self.cid, pth.read_bytes(), "png", "image", name="maria.png", mime="image/png", provider="upload")
        sf = {"id": "sf", "type": "style_folder", "x": 0, "y": 0, "params": {"folders": [{"id": "f1", "name": "Personagens", "files": [a["id"]], "folders": []}], "notes": "", "global": True}}
        eng = self.engine([sf])
        cv = self.cs.get(self.cid)

        class Prov:
            vision = True
        with mock.patch("openflow.canvas.engine.build_provider", return_value=Prov()), mock.patch.object(CanvasEngine, "text_chat", side_effect=self.chat):
            eng.folder_digest(cv, cv["nodes"][0], force=True)
        self.assertEqual(self.chats[0][1], S.FOLDER_SYSTEM)

    def test_text_nodes_receive_the_usage_rules(self):
        self.with_ai()
        llm = {"id": "t", "type": "llm", "x": 0, "y": 0, "params": {"instruction": "Escreva uma legenda para a Ana", "provider": "", "temperature": 0.5}}
        eng = self.engine([self.sp(STRUCTURED), llm])
        cv = self.cs.get(self.cid)
        seen = {}

        def chat(provider, messages, system, temp, max_tokens):
            seen["system"] = system
            return "ok"
        with mock.patch("openflow.canvas.engine.build_provider", return_value=object()), mock.patch.object(CanvasEngine, "text_chat", side_effect=chat):
            eng._llm(cv, next(n for n in cv["nodes"] if n["id"] == "t"))
        self.assertIn("REGRAS DE USO DO ESTILO DO PROJETO", seen["system"])
        self.assertIn("Estilo do projeto:", seen["system"])
        self.assertIn("menina ruiva", seen["system"])

    def test_text_nodes_without_style_have_no_rules(self):
        self.with_ai()
        llm = {"id": "t", "type": "llm", "x": 0, "y": 0, "params": {"instruction": "Escreva", "provider": "", "temperature": 0.5}}
        eng = self.engine([llm])
        cv = self.cs.get(self.cid)
        seen = {}

        def chat(provider, messages, system, temp, max_tokens):
            seen["system"] = system
            return "ok"
        with mock.patch("openflow.canvas.engine.build_provider", return_value=object()), mock.patch.object(CanvasEngine, "text_chat", side_effect=chat):
            eng._llm(cv, cv["nodes"][0])
        self.assertNotIn("REGRAS DE USO", seen["system"])


if __name__ == "__main__":
    unittest.main()
