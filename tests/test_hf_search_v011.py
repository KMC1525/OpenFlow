"""v0.11: a pesquisa de modelos no Hugging Face faz as consultas ao mesmo tempo, guarda o resultado por um instante e não fica «gravando» erros."""
import threading
import time
import unittest
from unittest import mock

from openflow import hf
from openflow.providers import http
from openflow.providers.base import ProviderError


class SearchSpeedTests(unittest.TestCase):
    def setUp(self):
        hf.clear_cache()
        self.addCleanup(hf.clear_cache)

    def slow(self, delay=0.25, log=None):
        def get(url, headers=None, timeout=20):
            if log is not None:
                log.append((url, timeout, threading.get_ident()))
            time.sleep(delay)
            return [{"id": "acme/m-" + str(len(url) % 7), "downloads": 5, "likes": 1}]
        return get

    def test_the_queries_run_together_not_one_after_the_other(self):
        log = []
        with mock.patch.object(http, "get_json", self.slow(0.3, log)):
            t0 = time.time()
            hf.search("unsloth", kind="other")      # 4 tipos × 3 consultas (busca + 2 por autor) = 12 chamadas
            took = time.time() - t0
        self.assertEqual(len(log), 12)
        self.assertLess(took, 12 * 0.3 / 2, took)   # em fila seriam 3,6 s; juntas ficam perto de 2 «rodadas»
        self.assertGreater(len({th for _, _, th in log}), 1)
        self.assertTrue(all(to <= 12 for _, to, _ in log))   # cada consulta espera no máximo 12 s (antes 20 s)

    def test_the_same_search_is_answered_from_memory_for_a_moment(self):
        log = []
        with mock.patch.object(http, "get_json", self.slow(0, log)):
            a = hf.search("flux", kind="image")
            n = len(log)
            b = hf.search("flux", kind="image")
            self.assertEqual(len(log), n)           # nenhuma consulta nova
            self.assertEqual(a, b)
            hf.search("wan", kind="image")
            self.assertGreater(len(log), n)         # outro termo consulta de novo
            with mock.patch.object(hf, "CACHE_SECONDS", -1):
                hf.search("flux", kind="image")     # prazo vencido: consulta de novo
            self.assertGreater(len(log), n + 2)

    def test_failures_are_not_cached_and_a_partial_failure_still_returns_results(self):
        calls = {"n": 0}

        def flaky(url, headers=None, timeout=20):
            calls["n"] += 1
            if "text-to-video" in url:
                raise ProviderError("Hub lento")
            return [{"id": "acme/video", "downloads": 3, "likes": 0}]

        with mock.patch.object(http, "get_json", flaky):
            out = hf.search("wan", kind="video")    # uma das duas tags falha: a outra basta
            self.assertEqual([m["id"] for m in out], ["acme/video"])
            before = calls["n"]
            hf.search("wan", kind="video")
            self.assertEqual(calls["n"] - before, 3)   # só as 3 consultas da tag que falhou são refeitas (as outras 3 vêm da memória)
        with mock.patch.object(http, "get_json", side_effect=ProviderError("sem rede")):
            hf.clear_cache()
            with self.assertRaises(ProviderError) as cm:
                hf.search("x", kind="image")
        self.assertIn("sem rede", str(cm.exception))

    def test_original_format_search_and_repo_files_use_the_same_machinery(self):
        log = []
        with mock.patch.object(http, "get_json", self.slow(0.2, log)):
            t0 = time.time()
            hf.search_original("flux", cap="image")   # 2 tags
            self.assertLess(time.time() - t0, 0.35)
        tree = [{"type": "file", "path": "a.gguf", "size": 5}]
        with mock.patch.object(http, "get_json", return_value=tree) as g:
            hf.repo_files("acme/x")
            hf.repo_files("acme/x")
            self.assertEqual(g.call_count, 1)        # a lista de arquivos também vem da memória na segunda vez


if __name__ == "__main__":
    unittest.main()
