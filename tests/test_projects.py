"""Projetos: lista, pesquisa (nome, descrição e textos dos nós; sem acentos), ordenação, arquivos web e segurança básica do servidor."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import __version__  # noqa: E402
from openflow.server import WEB_DIR  # noqa: E402
from openflow.storage import Store  # noqa: E402
from tests.helpers import ServerCase, TmpCase  # noqa: E402


class SearchStoreTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.cs = Store(self.tmp).projects
        self.a = self.cs.create("Floresta Mágica", "text_image", "Uma floresta ao amanhecer, névoa suave")["id"]
        self.b = self.cs.create("Cenário urbano", "blank")["id"]
        self.c = self.cs.create("Teste", "image_video", "astronauta no planeta de cristais")["id"]
        self.cs.update_meta(self.b, None, "Ruas molhadas à noite, neon")
        from openflow.util import read_json, write_json

        for pid, (created, updated) in {self.a: ("2026-01-01T10:00:00+00:00", "2026-01-03T10:00:00+00:00"), self.b: ("2026-01-02T10:00:00+00:00", "2026-01-04T10:00:00+00:00"),
                                        self.c: ("2026-01-03T10:00:00+00:00", "2026-01-02T10:00:00+00:00")}.items():   # datas distintas: a ordenação não depende do relógio (o segundo)
            f = self.cs.folder / pid / "project.json"
            d = read_json(f)
            d["created"], d["updated"] = created, updated
            write_json(f, d)

    def names(self, q="", sort="updated"):
        return [r["name"] for r in self.cs.list(q, sort)]

    def test_no_query_lists_everything_newest_first(self):
        self.assertEqual(sorted(self.names()), ["Cenário urbano", "Floresta Mágica", "Teste"])
        self.assertEqual(self.names(), ["Cenário urbano", "Floresta Mágica", "Teste"])

    def test_search_ignores_case_and_accents_and_needs_every_word(self):
        self.assertEqual(self.names("FLORESTA"), ["Floresta Mágica"])
        self.assertEqual(self.names("cenario"), ["Cenário urbano"])
        self.assertEqual(self.names("magica floresta"), ["Floresta Mágica"])       # a ordem das palavras não importa
        self.assertEqual(self.names("floresta urbano"), [])                         # todas as palavras precisam aparecer no mesmo projeto
        self.assertEqual(self.names("nada por aqui"), [])

    def test_search_looks_into_descriptions_and_node_texts_and_says_where(self):
        by = {r["name"]: r.get("match") for r in self.cs.list("neon")}
        self.assertEqual(by, {"Cenário urbano": "descrição"})
        by = {r["name"]: r.get("match") for r in self.cs.list("nevoa")}
        self.assertEqual(by, {"Floresta Mágica": "Uma floresta ao amanhecer, névoa suave"})
        self.assertEqual({r["name"]: r.get("match") for r in self.cs.list("floresta")}, {"Floresta Mágica": ""})      # no nome: nada a explicar

    def test_sorting(self):
        self.assertEqual(self.names("", "name"), ["Cenário urbano", "Floresta Mágica", "Teste"])
        self.assertEqual(self.names("", "created"), ["Teste", "Cenário urbano", "Floresta Mágica"])
        self.assertEqual(self.names("", "files"), ["Cenário urbano", "Floresta Mágica", "Teste"])     # sem arquivos em nenhum: desempate pelo nome
        self.assertEqual(self.names("", "qualquer"), ["Cenário urbano", "Floresta Mágica", "Teste"])  # ordenação desconhecida = a padrão (mais recentes)


class ProjectApiTests(ServerCase):
    def test_list_search_and_sort_over_http(self):
        for name in ("Alfa", "Beta", "Gama"):
            self.assertEqual(self.c.json("POST", "/api/projects", {"name": name, "template": "blank"})[0], 201)
        s, r = self.c.json("GET", "/api/projects?q=bet")
        self.assertEqual((s, [p["name"] for p in r]), (200, ["Beta"]))
        s, r = self.c.json("GET", "/api/projects?sort=name")
        self.assertEqual([p["name"] for p in r if p["name"] in ("Alfa", "Beta", "Gama")], ["Alfa", "Beta", "Gama"])
        s, r = self.c.json("GET", "/api/projects?q=" + "x" * 500)                  # pesquisa enorme: cortada, sem erro
        self.assertEqual((s, r), (200, []))

    def test_state_reports_version_and_the_rust_core_status(self):
        s, r = self.c.json("GET", "/api/state")
        self.assertEqual((s, r["version"]), (200, __version__))
        self.assertIn("native", r)
        self.assertEqual(r["settings"]["active"]["generation"], "demo")
        self.assertNotIn("characters", r["settings"]["active"])

    def test_spa_fallback_and_missing_files(self):
        s, h, body = self.c.req("GET", "/")
        self.assertEqual(s, 200)
        self.assertIn(b"<title>OpenFlow</title>", body)
        self.assertEqual(self.c.req("GET", "/project/qualquer")[0], 200)           # rotas da tela caem no index.html
        self.assertEqual(self.c.req("GET", "/js/nao-existe.js")[0], 404)
        s, _h, body = self.c.req("GET", "/../../etc/passwd")                        # fora da pasta web: nunca entrega o arquivo (cai no index.html)
        self.assertNotIn(b"root:", body)

    def test_foreign_host_and_origin_are_refused(self):
        self.assertEqual(self.c.req("GET", "/api/state", headers={"Host": "evil.example.com"})[0], 403)
        self.assertEqual(self.c.req("POST", "/api/projects", {"name": "x"}, headers={"Origin": "http://evil.example.com"})[0], 403)

    def test_web_files_do_not_use_names_that_ad_blockers_block(self):
        """Bloqueadores de anúncios/rastreadores barram nomes de scripts de rastreamento conhecidos (ex.: «quant.js»): a tela quebrava só para quem os usa."""
        risky = {"quant.js", "analytics.js", "ga.js", "gtag.js", "gtm.js", "ads.js", "track.js", "tracker.js", "tracking.js", "pixel.js", "beacon.js", "metrics.js", "stats.js", "telemetry.js", "banner.js", "advert.js"}
        names = {p.name.lower() for p in WEB_DIR.rglob("*") if p.is_file()}
        self.assertEqual(names & risky, set())

    def test_every_script_the_page_imports_exists(self):
        import re

        for js in WEB_DIR.rglob("*.js"):
            src = js.read_text(encoding="utf-8")
            for m in re.finditer(r"""(?:from|import)\s*\(?\s*['"](\.{1,2}/[^'"]+\.js)['"]""", src):
                self.assertTrue((js.parent / m.group(1)).resolve().is_file(), f"{js.name} importa {m.group(1)}, que não existe")
        index = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        for ref in re.findall(r'(?:src|href)="(/[^"#]+\.(?:js|css|png|webmanifest))"', index):
            self.assertTrue((WEB_DIR / ref.lstrip("/")).is_file(), ref)

    def test_settings_never_leak_secrets(self):
        self.c.json("PUT", "/api/settings", {"hf": {"token": "hf_segredo"}, "providers": {"openai": {"api_key": "sk-segredo"}}})
        s, r = self.c.json("GET", "/api/settings")
        self.assertNotIn("segredo", json.dumps(r))
        self.assertTrue(r["hf"]["token_set"] and r["providers"]["openai"]["has_key"])
        s, _h, body = self.c.req("GET", "/api/settings/export")
        self.assertNotIn(b"segredo", body)


if __name__ == "__main__":
    unittest.main()
