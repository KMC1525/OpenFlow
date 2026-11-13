"""v0.17 — Canvas: motor otimizado (índices, leitura em cache, ordem pelo núcleo) e busca de modelos no Hugging Face."""
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import native  # noqa: E402
from openflow.canvas.engine import CanvasEngine  # noqa: E402
from openflow.storage import Store  # noqa: E402
from tests import media_tools as tools  # noqa: E402
from tests.test_canvas import edge, node  # noqa: E402
from tests.helpers import TmpCase  # noqa: E402
from tests.helpers import ServerCase  # noqa: E402

FF = tools.have_ffmpeg()


class Base(TmpCase):
    def setUp(self):
        super().setUp()
        self.store = Store(self.tmp)
        self.cs = self.store.projects

    def make(self, nodes, edges, name="t"):
        c = self.cs.create(name)
        return self.cs.save_layout(c["id"], {"nodes": nodes, "edges": edges})

    def run_engine(self, cid, targets=None, force=False):
        ev = []
        return CanvasEngine(self.store, cid, ev.append).run(targets, force), ev


class EngineSpeedTests(Base):
    def test_topological_order_and_levels_match_the_graph(self):
        c = self.make([node("text", nid="a", text="x"), node("image", nid="b"), node("video", nid="c"), node("sound", nid="d")],
                      [edge("a", "b", "prompt"), edge("b", "c", "image"), edge("a", "d", "prompt")])
        cv = self.cs.get(c["id"])
        self.assertEqual(sorted(CanvasEngine.topo(cv)), ["a", "b", "c", "d"])
        lv = CanvasEngine.levels(cv)
        self.assertEqual((lv["a"], lv["b"], lv["c"], lv["d"]), (0, 1, 2, 1))
        pos = {i: k for k, i in enumerate(CanvasEngine.topo(cv))}
        self.assertTrue(pos["a"] < pos["b"] < pos["c"] and pos["a"] < pos["d"])

    def test_engine_does_not_reread_the_file_for_cached_nodes(self):
        n = 40
        nodes = [node("text", nid="t", text="uma praia")] + [node("image", nid=f"i{k}") for k in range(n)]
        c = self.make(nodes, [edge("t", f"i{k}", "prompt") for k in range(n)])
        self.run_engine(c["id"])
        with mock.patch.object(self.cs, "get", wraps=self.cs.get) as get:
            stats, _ = self.run_engine(c["id"])
        self.assertEqual((stats["ran"], stats["cached"]), (0, n))
        self.assertLessEqual(get.call_count, 3, get.call_count)       # antes: uma leitura do arquivo inteiro por nó

    def test_big_flow_plan_and_stale_stay_fast_and_correct(self):
        n = 195          # o canvas aceita até 200 nós
        nodes = [node("text", nid="t", text="x")] + [node("image", nid=f"i{k}") for k in range(n)]
        edges = [edge("t", f"i{k}", "prompt") for k in range(n)]
        c = self.make(nodes, edges)
        cv = self.cs.get(c["id"])
        eng = CanvasEngine(self.store, c["id"])
        t0 = time.time()
        stale = eng.stale_ids(cv)
        plan = eng.plan(cv, None)
        self.assertLess(time.time() - t0, 2.0)
        self.assertEqual(len(stale), n)                  # nada rodou ainda: todos os geradores estão desatualizados
        self.assertEqual(len(plan), n)                   # o texto não é «executável»; só os geradores
        self.assertEqual(plan, [f"i{k}" for k in range(n)])
        sub = eng.plan(cv, ["i7"])
        self.assertEqual(sub, ["i7"])

    def test_results_set_by_the_engine_are_visible_without_a_reload(self):
        c = self.make([node("text", nid="t", text="a"), node("image", nid="i")], [edge("t", "i", "prompt")])
        eng = CanvasEngine(self.store, c["id"])
        cv = eng.canvas()
        self.assertIs(eng.canvas(), cv)                                       # nada mudou: o mesmo objeto
        eng._set_result("i", {"state": "done", "assets": [], "text": "oi", "hash": "h"})
        self.assertIs(eng.canvas(), cv)
        self.assertEqual(eng._node(cv, "i")["result"]["text"], "oi")          # e já com o resultado novo
        self.assertEqual(self.cs.get(c["id"])["nodes"][1]["result"]["text"], "oi")
        self.cs.patch_node_params(c["id"], "t", {"text": "b"})                # alguém gravou por fora: o motor relê
        self.assertIsNot(eng.canvas(), cv)
        self.assertEqual(eng._node(eng.canvas(), "t")["params"]["text"], "b")


@unittest.skipUnless(FF, "ffmpeg não instalado")
class HubApi(ServerCase):
    """Barra de busca de modelos do Canvas: pesquisa no Hugging Face (servidor simulado), quantizações e «usar»."""

    def fake_get(self, url, headers=None, timeout=20):
        if "pipeline_tag=text-to-image" in url and "gguf" in url:
            return [{"id": "acme/flux-gguf", "downloads": 50, "likes": 3}, {"id": "acme/other-gguf", "downloads": 90, "likes": 1}]
        if "pipeline_tag=text-to-audio" in url:
            return [{"id": "facebook/musicgen-small", "downloads": 1000, "likes": 9, "tags": ["text-to-audio"]}, {"id": "lixo sem barra", "downloads": 5}]
        return []

    def test_search_gguf_and_original_formats(self):
        with mock.patch("openflow.providers.http.get_json", side_effect=self.fake_get):
            s, r = self.c.json("GET", "/api/media/hub/search?q=flux&cap=image&format=gguf")
            self.assertEqual(s, 200, r)
            self.assertEqual([m["id"] for m in r["results"]], ["acme/other-gguf", "acme/flux-gguf"])        # mais baixado primeiro
            self.assertEqual({m["format"] for m in r["results"]}, {"gguf"})
            s, r = self.c.json("GET", "/api/media/hub/search?q=music&cap=sound&format=gguf")                 # som não tem provedor GGUF: cai no formato original
            self.assertEqual((s, r["format"]), (200, "original"))
            self.assertEqual([m["id"] for m in r["results"]], ["facebook/musicgen-small"])                  # id inválido é descartado
        self.assertEqual(self.c.json("GET", "/api/media/hub/search?cap=nada")[0], 400)

    def test_search_reports_network_failures(self):
        from openflow.providers.base import ProviderError

        with mock.patch("openflow.providers.http.get_json", side_effect=ProviderError("sem rede")):
            s, r = self.c.json("GET", "/api/media/hub/search?cap=image")
        self.assertEqual(s, 502)
        self.assertIn("sem rede", json.dumps(r))

    def test_use_sets_defaults_and_the_selected_node(self):
        (self.store.models_dir / "image").mkdir(parents=True, exist_ok=True)
        (self.store.models_dir / "image" / "flux-Q4_K_M.gguf").write_bytes(b"GGUF")
        cv = self.store.projects.create("Modelos")
        self.store.projects.save_layout(cv["id"], {"nodes": [node("image", nid="img"), node("sound", nid="snd")], "edges": []})
        s, r = self.c.json("POST", "/api/media/hub/use", {"cap": "image", "provider": "gguf_local", "model": "flux-Q4_K_M.gguf", "canvas": cv["id"], "node": "img"})
        self.assertEqual(s, 200, r)
        self.assertTrue(r["node_updated"])
        st = self.store.get_settings()["media"]
        self.assertEqual((st["active"]["image"], st["models"]["gguf_local"]["image"]), ("gguf_local", "flux-Q4_K_M.gguf"))
        n = next(x for x in self.store.projects.get(cv["id"])["nodes"] if x["id"] == "img")
        self.assertEqual((n["params"]["provider"], n["params"]["model"]), ("gguf_local", "flux-Q4_K_M.gguf"))
        # nó de outro tipo não é tocado; arquivo que não foi baixado e provedor inválido são recusados
        s, r = self.c.json("POST", "/api/media/hub/use", {"cap": "image", "provider": "gguf_local", "model": "flux-Q4_K_M.gguf", "canvas": cv["id"], "node": "snd"})
        self.assertFalse(r["node_updated"])
        self.assertEqual(self.c.json("POST", "/api/media/hub/use", {"cap": "image", "provider": "gguf_local", "model": "nao-baixado.gguf"})[0], 404)
        self.assertEqual(self.c.json("POST", "/api/media/hub/use", {"cap": "image", "provider": "openai", "model": "x"})[0], 400)
        self.assertEqual(self.c.json("POST", "/api/media/hub/use", {"cap": "sound", "provider": "gguf_local", "model": "x.gguf"})[0], 404)
        s, r = self.c.json("POST", "/api/media/hub/use", {"cap": "sound", "provider": "local_hf", "model": "facebook/musicgen-small"})
        self.assertEqual(s, 200, r)
        self.assertEqual(self.store.get_settings()["media"]["models"]["local_hf"]["sound"], "facebook/musicgen-small")
        self.assertEqual(self.c.json("POST", "/api/media/hub/use", {"cap": "sound", "provider": "local_hf", "model": "sem-barra"})[0], 400)


class SimpleNodeTests(Base):
    """v0.17.1 — os nós de mídia mostram só Provedor, Modelo e Resolução; o que já estava salvo continua valendo."""

    def test_video_resolution_is_normalized_and_old_canvases_open_unchanged(self):
        from openflow.canvas.schema import normalize_params

        self.assertEqual(normalize_params("video", {})["resolution"], 0)
        self.assertEqual([normalize_params("video", {"resolution": r})["resolution"] for r in (480, "720", 1080, 999, "x", None, -5)], [480, 720, 1080, 0, 0, 0, 0])
        old = normalize_params("image", {"negative": "borrado", "seed": 7, "extra": {"quality": "high"}, "ignore_global_styles": True, "size": "1280x720"})
        self.assertEqual((old["negative"], old["seed"], old["extra"], old["ignore_global_styles"], old["size"]), ("borrado", 7, {"quality": "high"}, True, "1280x720"))

    @unittest.skipUnless(FF, "ffmpeg não instalado")
    def test_video_resolution_reaches_the_provider_and_changes_the_demo_frame_size(self):
        from tests import media_tools as T

        sizes = {}
        for res in (0, 480, 720):
            c = self.make([node("text", nid="t", text="uma praia"), node("video", nid="v", duration=1, aspect="16:9", resolution=res)], [edge("t", "v", "prompt")], name=f"r{res}")
            self.run_engine(c["id"])
            cv = self.cs.get(c["id"])
            a = next(x for x in cv["assets"] if x["kind"] == "video")
            info = T.probe(self.cs.asset_path(c["id"], a["file"]))
            sizes[res] = max(info["w"], info["h"])
        self.assertEqual((sizes[0], sizes[480], sizes[720]), (640, 480, 720))        # automática = 640 no Demo
        # mudar a resolução deixa o nó desatualizado (muda o hash)
        c = self.make([node("text", nid="t", text="x"), node("video", nid="v", duration=1, resolution=480)], [edge("t", "v", "prompt")])
        self.run_engine(c["id"])
        self.cs.patch_node_params(c["id"], "v", {"resolution": 720})
        self.assertIn("v", CanvasEngine(self.store, c["id"]).stale_ids(self.cs.get(c["id"])))

    def test_every_provider_accepts_long_side(self):
        import inspect

        from openflow.canvas import media as M

        for cls in (M.MediaProvider, M.DemoMedia, M.OpenAIMedia, M.GGUFMedia):
            self.assertIn("long_side", inspect.signature(cls.video).parameters, cls.__name__)
        for name in ("GoogleMedia", "ReplicateMedia", "HFInferenceMedia", "LocalHFMedia"):
            if hasattr(M, name):
                self.assertIn("long_side", inspect.signature(getattr(M, name).video).parameters, name)


class SimpleNodeApi(ServerCase):
    def test_meta_lists_the_video_resolutions(self):
        self.assertEqual(self.c.json("GET", "/api/project-templates")[1]["resolutions"], [0, 480, 720, 1080])


if __name__ == "__main__":
    unittest.main()
