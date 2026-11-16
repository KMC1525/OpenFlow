"""v0.65: a barra de pesquisa de modelos do Canvas para SOM — assuntos (música, efeitos, voz, dublagem…), sem o ruído do filtro `text-to-audio` do Hub e com o selo «roda no OpenFlow».

As fixtures têm a forma dos resultados reais do Hugging Face (tags, biblioteca e tarefa de cada modelo, conforme a API do Hub devolveu em novembro de 2026). A consulta ao Hub é simulada: a busca de verdade pela rede
(`urllib` do OpenFlow, não a ferramenta usada para conferir os dados) não foi exercitada aqui."""
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from openflow import hf
from openflow import soundsearch as ss
from openflow.providers import ProviderError, http
from tests.helpers import ServerCase


def R(mid, tags, lib="", tag="text-to-audio", downloads=1000, likes=1):
    return {"id": mid, "tags": tags, "library_name": lib, "pipeline_tag": tag, "downloads": downloads, "likes": likes}


MUSICGEN = R("facebook/musicgen-medium", ["transformers", "pytorch", "musicgen", "text-to-audio"], "transformers", downloads=2_000_000)
LTX = R("Lightricks/LTX-2.5", ["diffusion-single-file", "image-to-video", "text-to-video", "audio-to-video", "text-to-audio", "audio-to-audio"], "diffusion-single-file", "image-to-video", 2_800_000)
ACE = R("ACE-Step/Ace-Step1.5", ["transformers", "diffusers", "acestep", "audio", "music", "text2music", "text-to-audio", "custom_code"], "transformers", downloads=103_900)
STABLE = R("stabilityai/stable-audio-3-medium", ["stable-audio-3", "music", "sound-effects", "text-to-audio"], "stable-audio-3", downloads=130_000)
MOSS = R("OpenMOSS-Team/MOSS-SoundEffect-v2.0", ["diffusers", "text-to-audio", "sound-effects", "audio-generation"], "diffusers", downloads=6_700)
OMNI = R("Qwen/Qwen3-Omni-30B-A3B-Instruct", ["transformers", "text-to-audio", "any-to-any"], "transformers", "any-to-any", 353_000)
VIBE = R("microsoft/VibeVoice-1.5B", ["transformers", "vibevoice", "text-to-audio", "text-to-speech"], "transformers", "text-to-speech", 216_000)
MMS = R("facebook/mms-tts-por", ["transformers", "vits", "text-to-audio", "mms", "text-to-speech"], "transformers", "text-to-speech", 50_000)
KOKORO = R("hexgrad/Kokoro-82M", ["text-to-speech", "en"], "", "text-to-speech", 12_900_000)
BIGVGAN = R("nvidia/bigvgan_v2_22khz_80band_256x", ["PyTorch", "neural-vocoder", "audio-generation", "audio-to-audio"], "PyTorch", "audio-to-audio", 1_800_000)
WHISPER = R("openai/whisper-small", ["transformers", "whisper", "automatic-speech-recognition"], "transformers", "automatic-speech-recognition", 5_000_000)
SEAMLESS = R("facebook/seamless-m4t-v2-large", ["transformers", "seamless_m4t_v2", "audio-to-audio", "text-to-speech", "automatic-speech-recognition"], "transformers", "automatic-speech-recognition", 292_000)
RVC = R("YukiKaze1337/DaFeiYu_rvc_v2_40k", ["rvc", "voice-conversion", "singing-voice-conversion", "audio-to-audio"], "rvc", "audio-to-audio", 845)
SAM = R("audio-cpp/SAM-Audio-GGUF", ["audio.cpp", "gguf", "audio-separation", "audio-to-audio"], "audio.cpp", "audio-to-audio", 304_000)
OMNIVOICE = R("k2-fsa/OmniVoice", ["omnivoice", "voice-cloning", "voice-design", "text-to-speech"], "omnivoice", "text-to-speech", 4_100_000)
ORPHEUS = R("unsloth/orpheus-3b-0.1-ft", ["transformers", "safetensors", "llama", "text-to-speech", "unsloth"], "transformers", "text-to-speech", 40_000)
ORPHEUS_GGUF = R("someone/orpheus-3b-0.1-ft-Q4_K_M-GGUF", ["gguf", "text-to-speech"], "gguf", "text-to-speech", 9_000)
ALL = [MUSICGEN, LTX, ACE, STABLE, MOSS, OMNI, VIBE, MMS, KOKORO, BIGVGAN, WHISPER, SEAMLESS, RVC, SAM, OMNIVOICE, ORPHEUS, ORPHEUS_GGUF]


def row(r):
    return {"id": r["id"], "tags": r["tags"], "library": r["library_name"], "pipeline_tag": r["pipeline_tag"], "downloads": r["downloads"], "likes": r["likes"]}


class ClassifyTests(unittest.TestCase):
    def topics(self, r):
        return ss.topics_of(row(r))

    def test_the_noise_of_the_text_to_audio_filter_is_gone(self):
        for r in (LTX, OMNI, BIGVGAN):
            self.assertTrue(ss.is_noise(row(r)), r["id"])
            self.assertEqual(self.topics(r), [], r["id"])
        for r in (MUSICGEN, ACE, VIBE, WHISPER, RVC):
            self.assertFalse(ss.is_noise(row(r)), r["id"])

    def test_music_effects_and_both(self):
        self.assertEqual(self.topics(MUSICGEN), ["music"])                 # o MusicGen não tem a tag «music»: vale a família no nome/tags
        self.assertEqual(self.topics(ACE), ["music"])
        self.assertEqual(self.topics(MOSS), ["sfx"])
        self.assertEqual(self.topics(STABLE), ["music", "sfx"])           # o Stable Audio faz os dois

    def test_speech_topics(self):
        self.assertEqual(self.topics(VIBE), ["tts"])                       # voz que o `text-to-audio` mistura com a música: não é música
        self.assertEqual(self.topics(KOKORO), ["tts"])
        self.assertEqual(self.topics(WHISPER), ["asr"])
        self.assertEqual(self.topics(RVC), ["clone"])
        self.assertEqual(self.topics(SAM), ["tools"])
        self.assertEqual(sorted(self.topics(SEAMLESS)), ["asr", "dub", "tts"])
        self.assertEqual(sorted(self.topics(OMNIVOICE)), ["clone", "design", "tts"])

    def test_topic_names_and_defaults(self):
        self.assertEqual(ss.check_topic("sound", "sfx"), "sfx")
        self.assertEqual(ss.check_topic("sound", "dub"), "music")          # assunto que não é da capacidade: o padrão dela
        self.assertEqual(ss.check_topic("voice", ""), "tts")
        self.assertEqual(ss.check_topic("stt", "x"), "asr")
        self.assertEqual(ss.check_topic("image", "music"), "")             # capacidade sem assuntos
        for cap, items in ss.TOPICS.items():
            for topic, _label in items:
                self.assertIn((cap, topic), ss.FETCH)                      # todo assunto tem consulta ao Hub


class CompatTests(unittest.TestCase):
    def level(self, cap, topic, r):
        return ss.compat(cap, topic, row(r))["level"]

    def test_supported_families(self):
        self.assertEqual(self.level("sound", "music", MUSICGEN), "ok")
        self.assertEqual(self.level("voice", "tts", MMS), "ok")            # MMS-TTS (VITS)
        self.assertEqual(self.level("voice", "tts", ORPHEUS), "ok")
        self.assertEqual(self.level("stt", "asr", WHISPER), "ok")
        self.assertEqual(self.level("voice", "tts", R("suno/bark-small", ["transformers", "bark", "text-to-audio"], "transformers", "text-to-speech")), "ok")
        self.assertEqual(self.level("voice", "tts", R("unsloth/csm-1b", ["transformers", "csm", "text-to-speech"], "transformers", "text-to-speech")), "ok")

    def test_not_supported_and_why(self):
        c = ss.compat("sound", "music", row(ACE))
        self.assertEqual(c["level"], "no")
        self.assertIn("código próprio", c["reason"])
        self.assertIn("MusicGen", c["reason"])
        self.assertIn("stable-audio-3", ss.compat("sound", "sfx", row(STABLE))["reason"])
        self.assertIn("diffusers", ss.compat("sound", "sfx", row(MOSS))["reason"])
        self.assertEqual(self.level("voice", "tts", KOKORO), "no")         # o mais baixado de todos: o OpenFlow não o roda
        self.assertEqual(self.level("voice", "tts", VIBE), "no")
        self.assertEqual(self.level("voice", "tts", ORPHEUS_GGUF), "no")   # o mesmo nome, em GGUF: não
        self.assertIn("formato", ss.compat("voice", "tts", row(ORPHEUS_GGUF))["reason"])
        self.assertEqual(self.level("stt", "asr", SEAMLESS), "no")

    def test_topics_without_a_node_never_say_ok(self):
        for topic, r in (("clone", RVC), ("dub", SEAMLESS), ("tools", SAM), ("design", OMNIVOICE)):
            cap = "sound" if topic == "tools" else "voice"
            c = ss.compat(cap, topic, row(r))
            self.assertEqual(c["level"], "no", topic)
            self.assertIn("ainda não tem um nó", c["reason"])
        self.assertEqual(self.level("voice", "clone", WHISPER), "no")      # mesmo uma família suportada: este assunto não roda

    def test_a_family_name_is_not_enough_without_the_right_library(self):
        fake = R("someone/musicgen-ggml", ["gguf", "musicgen", "text-to-audio"], "gguf")
        self.assertEqual(self.level("sound", "music", fake), "no")
        nolib = R("someone/musicgen-tuned", ["transformers", "musicgen", "text-to-audio"], "")
        self.assertEqual(self.level("sound", "music", nolib), "ok")        # sem o campo da biblioteca, mas com a tag «transformers»


class RankTests(unittest.TestCase):
    def test_music_keeps_only_music_and_runnable_ones_come_first(self):
        out = ss.rank([row(r) for r in ALL], "sound", "music")
        self.assertEqual([x["id"] for x in out], ["facebook/musicgen-medium", "stabilityai/stable-audio-3-medium", "ACE-Step/Ace-Step1.5"])
        self.assertEqual([x["compat"]["level"] for x in out], ["ok", "no", "no"])
        self.assertEqual(out[1]["topics"], ["music", "sfx"])

    def test_effects(self):
        out = ss.rank([row(r) for r in ALL], "sound", "sfx")
        self.assertEqual([x["id"] for x in out], ["stabilityai/stable-audio-3-medium", "OpenMOSS-Team/MOSS-SoundEffect-v2.0"])   # nenhum roda: do mais baixado ao menos

    def test_voice_and_transcription(self):
        tts = ss.rank([row(r) for r in ALL], "voice", "tts")
        self.assertEqual([x["id"] for x in tts][:2], ["facebook/mms-tts-por", "unsloth/orpheus-3b-0.1-ft"])                    # os que rodam primeiro (por downloads: 50 mil antes de 40 mil)
        self.assertEqual({x["compat"]["level"] for x in tts[:2]}, {"ok"})
        self.assertEqual({x["compat"]["level"] for x in tts[2:]}, {"no"})
        asr = ss.rank([row(r) for r in ALL], "stt", "asr")
        self.assertEqual([x["id"] for x in asr], ["openai/whisper-small", "facebook/seamless-m4t-v2-large"])

    def test_the_shape_and_the_limit(self):
        x = ss.rank([row(MUSICGEN)], "sound", "music")[0]
        self.assertEqual({k: x[k] for k in ("id", "downloads", "likes", "cap", "format", "topic", "library")}, {"id": "facebook/musicgen-medium", "downloads": 2_000_000, "likes": 1, "cap": "sound", "format": "original", "topic": "music", "library": "transformers"})
        many = [row(R(f"a/musicgen-{i}", ["transformers", "musicgen"], "transformers", downloads=i)) for i in range(50)]
        self.assertEqual(len(ss.rank(many, "sound", "music", limit=10)), 10)
        self.assertEqual(ss.rank([], "sound", "music"), [])


class QueryTests(unittest.TestCase):
    def test_subject_words_leave_the_text_search(self):
        self.assertEqual(ss.expand_query(""), [])
        self.assertEqual(ss.expand_query("música"), [])
        self.assertEqual(ss.expand_query("Efeitos Sonoros"), [])
        self.assertEqual(ss.expand_query("efeitos sonoros de chuva"), ["chuva"])
        self.assertEqual(ss.expand_query("musicgen"), ["musicgen"])
        self.assertEqual(ss.expand_query("whisper large"), ["whisper large"])
        self.assertEqual(ss.expand_query("dublagem"), [])
        self.assertEqual(ss.expand_query("stabilityai/stable-audio-3-medium"), ["stabilityai/stable-audio-3-medium"])    # dono/nome vai inteiro

    def test_languages_become_tags(self):
        self.assertEqual(ss.expand_query("voz em português"), [])
        self.assertEqual(ss.languages_in("voz em português"), ["pt"])
        self.assertEqual(ss.languages_in("voz em Português e inglês"), ["pt", "en"])
        self.assertEqual(ss.languages_in("whisper"), [])
        self.assertEqual(ss.languages_in("english Portuguese english"), ["en", "pt"])
        self.assertEqual(ss.expand_query("kokoro português"), ["kokoro"])


def hub(rows_by_substring, calls=None):
    """Um Hub de mentira: devolve as linhas da primeira regra cujo texto aparece na URL."""
    def get(url, headers=None, timeout=0):
        if calls is not None:
            calls.append(url)
        for needle, rows in rows_by_substring:
            if needle in url:
                return rows
        return []
    return get


class SearchSoundTests(unittest.TestCase):
    def setUp(self):
        hf.clear_cache()
        self.addCleanup(hf.clear_cache)

    def params(self, url):
        q = parse_qs(urlparse(url).query)
        return {k: v for k, v in q.items()}

    def test_it_asks_the_hub_by_tag_and_cleans_the_answer(self):
        calls = []
        with mock.patch.object(http, "get_json", hub([("", [MUSICGEN, LTX, ACE, STABLE, VIBE, OMNI])], calls)):
            out = hf.search_sound("", "", "sound", "music")
        self.assertEqual([x["id"] for x in out], ["facebook/musicgen-medium", "stabilityai/stable-audio-3-medium", "ACE-Step/Ace-Step1.5"])
        filters = sorted((self.params(u).get("filter") or [""])[0] for u in calls)
        self.assertEqual(filters, ["", "music", "music-generation", "text-to-music", "text2music"])      # uma consulta por tag do assunto + a geral
        self.assertTrue(all(self.params(u)["pipeline_tag"] == ["text-to-audio"] for u in calls))
        self.assertTrue(all("search" not in self.params(u) for u in calls))                              # sem texto: navega os mais baixados

    def test_the_typed_text_goes_to_the_search_and_the_language_to_a_tag(self):
        calls = []
        with mock.patch.object(http, "get_json", hub([("", [MMS])], calls)):
            hf.search_sound("kokoro em português", "", "voice", "tts")
        p = self.params(calls[0])
        self.assertEqual((p["search"], p["pipeline_tag"], p["filter"]), (["kokoro"], ["text-to-speech"], ["pt"]))
        calls.clear()
        with mock.patch.object(http, "get_json", hub([("", [])], calls)):
            hf.search_sound("voz em português", "", "voice", "tts")
        self.assertNotIn("search", self.params(calls[0]))
        self.assertEqual(self.params(calls[0])["filter"], ["pt"])
        calls.clear()
        with mock.patch.object(http, "get_json", hub([("", [])], calls)):
            hf.search_sound("português", "", "sound", "music")                                         # idioma só vale para voz e transcrição
        self.assertTrue(all("pt" not in self.params(u).get("filter", []) for u in calls))

    def test_a_single_word_also_searches_the_author(self):
        calls = []
        with mock.patch.object(http, "get_json", hub([("", [])], calls)):
            hf.search_sound("stabilityai", "", "sound", "sfx")
        self.assertTrue(any(self.params(u).get("author") == ["stabilityai"] for u in calls))

    def test_duplicates_are_merged(self):
        a = R("facebook/musicgen-medium", ["transformers"], "transformers", downloads=10)
        b = R("facebook/musicgen-medium", ["musicgen", "text-to-audio"], "", downloads=500)
        def get(url, headers=None, timeout=0):
            return [a] if url.endswith("filter=music") else [b] if url.endswith("limit=50") else []   # a consulta da tag «music» traz um registro; a geral, outro do mesmo modelo
        with mock.patch.object(http, "get_json", get):
            out = hf.search_sound("", "", "sound", "music")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["downloads"], 500)
        self.assertEqual(out[0]["compat"]["level"], "ok")                                                # as tags das duas respostas se juntam

    def test_invalid_ids_are_dropped(self):
        with mock.patch.object(http, "get_json", hub([("", [dict(MUSICGEN, id="lixo sem barra"), MUSICGEN])])):
            out = hf.search_sound("", "", "sound", "music")
        self.assertEqual([x["id"] for x in out], ["facebook/musicgen-medium"])

    def test_network_failures(self):
        with mock.patch.object(http, "get_json", side_effect=ProviderError("sem rede")):
            with self.assertRaises(ProviderError) as cm:
                hf.search_sound("", "", "sound", "music")
        self.assertIn("sem rede", str(cm.exception))
        hf.clear_cache()

        def flaky(url, headers=None, timeout=0):
            if url.endswith("filter=music"):
                raise ProviderError("Hub lento")
            return [MUSICGEN]
        calls = []
        with mock.patch.object(http, "get_json", lambda url, headers=None, timeout=0: (calls.append(url), flaky(url))[1]):   # uma consulta falha: as outras bastam
            self.assertEqual([x["id"] for x in hf.search_sound("", "", "sound", "music")], ["facebook/musicgen-medium"])
        self.assertTrue(any(u.endswith("filter=music") for u in calls))                                  # a consulta que falha existiu de verdade

    def test_an_unknown_capability_and_topic(self):
        with self.assertRaises(ProviderError):
            hf.search_sound("", "", "image", "music")
        calls = []
        with mock.patch.object(http, "get_json", hub([("", [])], calls)):
            hf.search_sound("", "", "voice", "nao-existe")                                               # assunto inválido: o padrão da capacidade
        self.assertTrue(all(self.params(u)["pipeline_tag"] == ["text-to-speech"] for u in calls))


class RouteTests(ServerCase):
    def setUp(self):
        hf.clear_cache()
        self.addCleanup(hf.clear_cache)

    def test_topics_route(self):
        s, r = self.c.json("GET", "/api/media/hub/topics")
        self.assertEqual(s, 200)
        self.assertEqual([t["id"] for t in r["topics"]["sound"]], ["music", "sfx", "tools"])
        self.assertEqual([t["id"] for t in r["topics"]["voice"]], ["tts", "clone", "design", "dub"])
        self.assertEqual([t["id"] for t in r["topics"]["stt"]], ["asr"])
        self.assertNotIn("image", r["topics"])
        self.assertTrue(all(t["label"] for items in r["topics"].values() for t in items))

    def test_sound_search_by_topic(self):
        with mock.patch.object(http, "get_json", hub([("", [MUSICGEN, LTX, ACE, STABLE, MOSS])])):
            s, r = self.c.json("GET", "/api/media/hub/search?cap=sound&topic=music")
            self.assertEqual((s, r["format"], r["topic"]), (200, "original", "music"))
            self.assertEqual([m["id"] for m in r["results"]], ["facebook/musicgen-medium", "stabilityai/stable-audio-3-medium", "ACE-Step/Ace-Step1.5"])
            self.assertEqual(r["results"][0]["compat"]["level"], "ok")
            s, r = self.c.json("GET", "/api/media/hub/search?cap=sound&topic=sfx")
            self.assertEqual([m["id"] for m in r["results"]], ["stabilityai/stable-audio-3-medium", "OpenMOSS-Team/MOSS-SoundEffect-v2.0"])
            s, r = self.c.json("GET", "/api/media/hub/search?cap=sound&topic=invalido")
            self.assertEqual(r["topic"], "music")                                                        # assunto inválido: o padrão

    def test_voice_and_transcription(self):
        with mock.patch.object(http, "get_json", hub([("", [MMS, KOKORO, VIBE, WHISPER, SEAMLESS])])):
            s, r = self.c.json("GET", "/api/media/hub/search?cap=voice&topic=tts&q=")
            self.assertEqual(s, 200)
            self.assertEqual([m["id"] for m in r["results"]], ["facebook/mms-tts-por", "hexgrad/Kokoro-82M", "facebook/seamless-m4t-v2-large", "microsoft/VibeVoice-1.5B"])   # o que roda primeiro; depois por downloads
            s, r = self.c.json("GET", "/api/media/hub/search?cap=stt")
            self.assertEqual((r["topic"], r["results"][0]["id"]), ("asr", "openai/whisper-small"))

    def test_the_other_capabilities_are_unchanged(self):
        def get(url, headers=None, timeout=0):
            if "pipeline_tag=text-to-image" in url:
                return [{"id": "acme/flux", "downloads": 5, "likes": 1, "tags": ["text-to-image"]}]
            return []
        with mock.patch.object(http, "get_json", get):
            s, r = self.c.json("GET", "/api/media/hub/search?cap=image&format=original&q=flux")
        self.assertEqual((s, r["topic"], [m["id"] for m in r["results"]]), (200, "", ["acme/flux"]))
        self.assertNotIn("compat", r["results"][0])

    def test_network_failure_is_a_502(self):
        with mock.patch.object(http, "get_json", side_effect=ProviderError("sem rede")):
            s, r = self.c.json("GET", "/api/media/hub/search?cap=sound&topic=music")
        self.assertEqual(s, 502)
        self.assertIn("sem rede", str(r))


if __name__ == "__main__":
    unittest.main()
