"""v0.62: Dublagem, Legendas e Transcrição — três nós no grupo Som: Transcrição (fala → texto, com marcas de tempo), Legendas (SRT/VTT para qualquer reprodutor) e Dublagem (traduz e fala por cima do original).

Não há modelo de transcrição nem de voz de verdade aqui: a fala vem de um provedor de mentira com tempos conhecidos, e a voz é o balbucio da demonstração. Que o Whisper local acerte as palavras e os tempos, ou
que um modelo de voz de verdade soe bem, não é verificado. O ffmpeg é real (os testes que o usam pulam sem ele)."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openflow.canvas import engine as engine_mod
from openflow.canvas import procedural as proc
from openflow.canvas import schema, speech
from openflow.canvas import subtitles as sub
from openflow.canvas.engine import CanvasEngine
from openflow.canvas.media import DemoMedia, LocalHFMedia, Media, MediaProvider
from openflow.providers import ProviderError
from openflow.storage import Store

FF = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
SEGS = [sub.seg(0.5, 3.0, "Olá, tudo bem com você?"), sub.seg(4.0, 7.0, "Hoje vamos falar sobre o mar.")]


def node(nid, ntype, **params):
    return {"id": nid, "type": ntype, "x": 0, "y": 0, "params": params}


class FakeSpeech(MediaProvider):
    """Transcreve sempre os mesmos dois trechos e fala com o balbucio da demonstração."""
    id, label, caps = "fake", "Fake", ("stt", "voice")

    def __init__(self, segs=SEGS, timed=True):
        super().__init__({"id": "fake"})
        self.segs, self.timed, self.spoken, self.heard = list(segs), timed, [], []

    def transcribe_segments(self, data, filename, mime, *, language="", model="", duration=0.0):
        self.heard.append((language, mime, len(data)))
        return [dict(s) for s in self.segs]

    def timed_segments(self, model=""):
        return self.timed

    def voice(self, text, *, voice="", speed=1.0, model="", extra=None, instructions=""):
        self.spoken.append((text, voice, speed))
        return Media(proc.babble(text, speed, 1), "audio/wav")


class Project:
    def __init__(self, nodes, edges=(), audio=True, video=False, seconds=9.0):
        self.store = Store(Path(tempfile.mkdtemp()))
        self.cs = self.store.projects
        self.cid = self.cs.create("fala")["id"]
        self.tmp = Path(tempfile.mkdtemp())
        self.ids = {}
        if audio:
            wav = proc.music("calma", seconds, 1)
            self.ids["a"] = self.cs.add_asset(self.cid, wav, "wav", "audio", name="aula.wav", mime="audio/wav", provider="upload")["id"]
        if video:
            wav = self.tmp / "a.wav"
            wav.write_bytes(proc.music("calma", seconds, 1))
            mp4 = self.tmp / "v.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=blue:s=160x120:d={seconds}", "-i", str(wav), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(mp4)], check=True)
            self.ids["v"] = self.cs.add_asset(self.cid, mp4.read_bytes(), "mp4", "video", name="aula.mp4", mime="video/mp4", provider="upload")["id"]
        self.cs.save_layout(self.cid, {"nodes": [n for n in nodes], "edges": list(edges)})

    def upload(self, nid, key):
        return node(nid, "upload", files=[self.ids[key]])

    def run(self, provider=None, force=True, chat=None):
        self.events = []
        ctx = [mock.patch.object(engine_mod, "build_media", return_value=provider), mock.patch.object(speech, "build_media", return_value=provider)] if provider else []
        if chat:
            ctx.append(mock.patch.object(CanvasEngine, "text_chat", chat))
            ctx.append(mock.patch("openflow.canvas.speech.build_provider", return_value=object()))
        for c in ctx:
            c.start()
        try:
            CanvasEngine(self.store, self.cid, self.events.append, lambda: False).run(None, force)
        finally:
            for c in ctx:
                c.stop()
        return self.cs.get(self.cid)

    def errors(self):
        return {e["id"]: e.get("message") for e in self.events if e.get("type") == "node" and e.get("state") == "error"}

    def warnings(self, nid):
        return [w for e in self.events if e.get("type") == "node" and e.get("id") == nid for w in e.get("warnings", [])]

    @staticmethod
    def result(cv, nid):
        return next(n for n in cv["nodes"] if n["id"] == nid)["result"]

    def asset(self, cv, nid):
        a = next(x for x in cv["assets"] if x["id"] == self.result(cv, nid)["assets"][0])
        return a, self.cs.asset_path(self.cid, a["file"])


def streams(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)], capture_output=True, text=True).stdout
    d = json.loads(out)
    return [s["codec_type"] for s in d["streams"]], float(d["format"]["duration"])


class TimeTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(sub.fmt_time(3723.456), "01:02:03,456")
        self.assertEqual(sub.fmt_time(3723.456, "."), "01:02:03.456")
        self.assertEqual(sub.fmt_time(59.9996), "00:01:00,000")          # arredonda sem escrever «00:00:59,1000»
        self.assertEqual(sub.fmt_time(-5), "00:00:00,000")
        self.assertEqual(sub.short_time(65), "1:05")
        self.assertEqual(sub.short_time(3725), "1:02:05")

    def test_parse(self):
        self.assertEqual(sub.parse_time("00:01:02,500"), 62.5)
        self.assertEqual(sub.parse_time("01:02.5"), 62.5)
        self.assertEqual(sub.parse_time("1:02:03.004"), 3723.004)
        self.assertEqual(sub.parse_time("00:00:01"), 1.0)
        self.assertIsNone(sub.parse_time("abc"))
        self.assertIsNone(sub.parse_time(""))


class FormatTests(unittest.TestCase):
    def test_srt_and_vtt(self):
        srt = sub.to_srt(SEGS)
        self.assertEqual(srt, "1\n00:00:00,500 --> 00:00:03,000\nOlá, tudo bem com você?\n\n2\n00:00:04,000 --> 00:00:07,000\nHoje vamos falar sobre o mar.\n")
        vtt = sub.to_vtt(SEGS)
        self.assertTrue(vtt.startswith("WEBVTT\n\n00:00:00.500 --> 00:00:03.000\n"))
        self.assertNotIn(",", vtt.split("\n")[2].split("-->")[0])       # VTT: ponto nos milissegundos
        self.assertEqual(sub.to_srt([sub.seg(0, 1, "  "), sub.seg(1, 2, "x")]).split("\n")[0], "1")   # cue vazio não ocupa número

    def test_round_trip(self):
        for fmt in (sub.to_srt, sub.to_vtt):
            back = sub.parse(fmt(SEGS))
            self.assertEqual([(s["start"], s["end"], s["text"]) for s in back], [(s["start"], s["end"], s["text"]) for s in SEGS])

    def test_parse_real_world_files(self):
        raw = "﻿WEBVTT - exemplo\n\nNOTE um comentário\n\nintro\n00:01.000 --> 00:02.500 align:start position:0%\n<i>Olá</i> <b>mundo</b>\n\n1:02:03.000 --> 1:02:04.000\nsegunda\nlinha\n"
        segs = sub.parse(raw.replace("\n", "\r\n"))
        self.assertEqual([(s["start"], s["end"], s["text"]) for s in segs], [(1.0, 2.5, "Olá mundo"), (3723.0, 3724.0, "segunda linha")])
        self.assertEqual(sub.parse("1\n00:00:01,000 --> 00:00:02,000\n{\\an8}Em cima\n")[0]["text"], "Em cima")
        self.assertEqual(sub.parse("não é legenda"), [])
        self.assertEqual(sub.parse("1\nxx --> yy\nlinha\n"), [])

    def test_looks_timed(self):
        self.assertTrue(sub.looks_timed(sub.to_srt(SEGS)))
        self.assertTrue(sub.looks_timed("00:00:01.000 --> 00:00:02.000\nx"))
        self.assertFalse(sub.looks_timed("Um texto -> com setas"))
        self.assertFalse(sub.looks_timed(""))

    def test_wrap_keeps_every_word_and_balances_lines(self):
        text = "Hoje vamos falar sobre o mar e sobre as ondas que chegam devagar na areia"
        out = sub.wrap(text, 42, 2)
        self.assertEqual(" ".join(out.split()), text)
        lines = out.split("\n")
        self.assertEqual(len(lines), 2)
        self.assertLess(abs(len(lines[0]) - len(lines[1])), 18)
        self.assertEqual(sub.wrap("curto", 42, 2), "curto")
        self.assertEqual(sub.wrap(text, 20, 1), text)                   # uma linha só: nada é cortado
        long = sub.wrap("palavra " * 30, 20, 2)
        self.assertEqual(len(long.split("\n")), 2)
        self.assertEqual(" ".join(long.split()), ("palavra " * 30).strip())
        self.assertEqual(sub.wrap("", 42), "")


class AdjustTests(unittest.TestCase):
    def test_shift(self):
        s = sub.shift(SEGS, 1.5)
        self.assertEqual((s[0]["start"], s[0]["end"]), (2.0, 4.5))
        s = sub.shift(SEGS, -2.0)
        self.assertEqual([(x["start"], x["end"]) for x in s], [(0.0, 1.0), (2.0, 5.0)])     # a 1ª perde o começo
        self.assertEqual(len(sub.shift(SEGS, -10)), 0)                                         # tudo antes do zero some

    def test_split_long_by_length_and_time(self):
        long = sub.seg(0, 12, "Uma frase bem comprida, que passa do limite de tempo e de tamanho de uma legenda comum, então precisa ser dividida em várias partes legíveis.")
        parts = sub.split_long([long], 60, 5.0)
        self.assertGreaterEqual(len(parts), 3)
        self.assertEqual(" ".join(p["text"] for p in parts), long["text"])
        self.assertAlmostEqual(parts[0]["start"], 0.0)
        self.assertAlmostEqual(parts[-1]["end"], 12.0, places=2)
        for a, b in zip(parts, parts[1:]):
            self.assertAlmostEqual(a["end"], b["start"], places=2)                             # sem buracos nem sobreposição
        self.assertTrue(all(p["end"] - p["start"] <= 5.2 for p in parts))
        short = sub.split_long(SEGS, 84, 6.0)
        self.assertEqual([s["text"] for s in short], [s["text"] for s in SEGS])                # as curtas ficam como estão

    def test_tidy_orders_and_removes_overlaps(self):
        messy = [sub.seg(5, 9, "terceira"), sub.seg(0, 4, "primeira"), sub.seg(3, 6, "segunda"), sub.seg(10, 10, "curta"), sub.seg(11, 12, "   ")]
        out = sub.tidy(messy)
        self.assertEqual([s["text"] for s in out], ["primeira", "segunda", "terceira", "curta"])
        for a, b in zip(out, out[1:]):
            self.assertLess(a["end"], b["start"])
        self.assertTrue(all(s["end"] > s["start"] for s in out))
        self.assertGreaterEqual(out[-1]["end"] - out[-1]["start"], 0.4)                       # duração mínima legível

    def test_spread_distributes_the_text_over_the_time(self):
        text = "Primeira frase curta. Segunda frase um pouco mais comprida que a primeira! E a terceira?\nQuarta linha."
        out = sub.spread(text, 20.0)
        self.assertEqual(len(out), 4)
        self.assertAlmostEqual(out[0]["start"], 0.0, places=1)
        self.assertAlmostEqual(out[-1]["end"], 20.0, delta=0.2)
        self.assertGreater(out[1]["end"] - out[1]["start"], out[0]["end"] - out[0]["start"])    # a frase maior ganha mais tempo
        self.assertEqual(sub.spread("", 10), [])
        self.assertEqual(sub.spread("texto", 0), [])
        many = sub.spread("palavra " * 100, 30.0, max_chars=40)
        self.assertGreater(len(many), 10)                                                       # texto sem pontuação também é dividido


class TranscriptTests(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(sub.transcript_text(SEGS, "plain"), "Olá, tudo bem com você? Hoje vamos falar sobre o mar.")
        self.assertEqual(sub.transcript_text(SEGS, "timestamps"), "[0:00] Olá, tudo bem com você?\n[0:04] Hoje vamos falar sobre o mar.")
        gap = [sub.seg(0, 2, "um"), sub.seg(2.5, 4, "dois"), sub.seg(9, 11, "três")]
        self.assertEqual(sub.transcript_text(gap, "paragraphs"), "um dois\n\ntrês")              # pausa longa = novo parágrafo
        self.assertEqual(sub.transcript_text([], "plain"), "")

    def test_chunks_from_the_speech_model(self):
        chunks = [{"text": " Olá", "timestamp": (0.0, 2.0)}, {"text": " mundo", "timestamp": (2.0, None)}, {"text": "  ", "timestamp": (5.0, 6.0)}]
        s = sub.segments_from_chunks(chunks, 10.0)
        self.assertEqual([(x["start"], x["end"], x["text"]) for x in s], [(0.0, 2.0, "Olá"), (2.0, 5.0, "mundo")])    # o fim que falta vem do começo do próximo
        last = sub.segments_from_chunks([{"text": "fim", "timestamp": (8.0, None)}], 10.0)
        self.assertEqual(last[0]["end"], 10.0)                                                  # o último sem fim vai até o fim do áudio
        self.assertEqual(sub.segments_from_chunks([{"text": "x", "timestamp": (4.0, None)}], 0)[0]["end"], 7.0)
        self.assertEqual(sub.segments_from_chunks([], 5), [])


class SchemaTests(unittest.TestCase):
    def test_palette_and_ports(self):
        group = dict(schema.PALETTE)["Som"]
        self.assertEqual(group[4:8], ["voice", "dub", "transcript", "sub"])
        self.assertEqual([p[0] for p in schema.NODE_TYPES["dub"]["ins"]], ["media", "script", "voices"])   # v0.63: +«Vozes» (nós Voz, um por personagem)
        self.assertEqual([p[0] for p in schema.NODE_TYPES["sub"]["ins"]], ["media", "text"])
        self.assertEqual((schema.NODE_TYPES["transcript"]["out"], schema.NODE_TYPES["sub"]["out"], schema.NODE_TYPES["dub"]["out"]), ("text", "text", "media"))
        for t in ("dub", "transcript", "sub"):
            self.assertIn(t, schema.GENERATORS)

    def test_connections(self):
        media = schema.port_def("dub", "media")["accepts"]
        self.assertTrue(schema.compatible("media", media))     # o nó Mídia (arquivo enviado)
        self.assertTrue(schema.compatible("video", media))
        self.assertTrue(schema.compatible("audio", media))
        self.assertFalse(schema.compatible("image", media))
        self.assertFalse(schema.compatible("text", media))
        self.assertTrue(schema.compatible("text", schema.port_def("dub", "script")["accepts"]))
        self.assertTrue(schema.compatible("media", schema.port_def("transcript", "media")["accepts"]))
        self.assertTrue(schema.compatible("audio", schema.port_def("vid_audio", "audio")["accepts"]))   # a dublagem (saída «media») cabe nas portas de mídia de outros nós
        self.assertTrue(schema.compatible(schema.NODE_TYPES["dub"]["out"], schema.port_def("vid_audio", "audio")["accepts"]))

    def test_params_are_clamped(self):
        p = schema.normalize_params("sub", {"max_chars": 999, "lines": 9, "offset": -99, "max_seconds": 0, "format": "x", "translate_to": "xx", "language": "klingon", "duration": -5})
        self.assertEqual((p["max_chars"], p["lines"], p["offset"], p["max_seconds"], p["format"], p["translate_to"], p["language"], p["duration"]), (80, 3, -30.0, 1.0, "srt", "", "auto", 0))
        self.assertEqual(schema.normalize_params("sub", {"format": "vtt", "translate_to": "en", "language": "pt"})["format"], "vtt")
        self.assertEqual(schema.normalize_params("sub", {"translate_to": "en"})["translate_to"], "en")
        d = schema.normalize_params("dub", {"language": "klingon", "mix": "duck", "original_volume": 9, "speed": 9, "fit": False, "source_language": "xx"})
        self.assertEqual((d["language"], d["mix"], d["original_volume"], d["speed"], d["fit"], d["source_language"]), ("en", "duck", 1.0, 2.0, False, "auto"))
        self.assertEqual(schema.normalize_params("dub", {"language": "keep"})["language"], "keep")
        t = schema.normalize_params("transcript", {"format": "?", "language": "pt"})
        self.assertEqual((t["format"], t["language"]), ("plain", "pt"))


class ProviderApiTests(unittest.TestCase):
    def test_default_segments_wrap_the_plain_transcription(self):
        class Plain(MediaProvider):
            caps = ("stt",)

            def transcribe(self, data, filename, mime, *, language="", model=""):
                return " tudo num bloco "
        p = Plain({"id": "p"})
        self.assertEqual(p.transcribe_segments(b"x", "a.wav", "audio/wav", duration=12.0), [{"start": 0.0, "end": 12.0, "text": "tudo num bloco"}])
        self.assertFalse(p.timed_segments())

    def test_demo_does_not_transcribe(self):
        with self.assertRaises(ProviderError):
            DemoMedia({"id": "demo"}).transcribe_segments(b"x", "a.wav", "audio/wav")

    def test_local_whisper_keeps_the_timestamps(self):
        lp = LocalHFMedia({"id": "local_hf"})
        seen = []

        def fake_asr(data, filename, mime, language, model, long_audio=False):
            seen.append((language, long_audio))
            return {"text": " Olá mundo", "chunks": [{"text": " Olá", "timestamp": (0.0, 1.0)}, {"text": " mundo", "timestamp": (1.0, 2.5)}]}
        with mock.patch.object(lp, "_asr", fake_asr):
            segs = lp.transcribe_segments(b"x", "a.wav", "audio/wav", language="pt", duration=3.0)
            text = lp.transcribe(b"x", "a.wav", "audio/wav")
        self.assertEqual([(s["start"], s["end"], s["text"]) for s in segs], [(0.0, 1.0, "Olá"), (1.0, 2.5, "mundo")])
        self.assertEqual(seen, [("pt", True), ("", False)])        # com tempos: o áudio longo é lido em janelas de 30 s; o texto simples segue como antes
        self.assertEqual(text, "Olá mundo")
        self.assertTrue(lp.timed_segments())

    def test_local_whisper_without_chunks_returns_one_block(self):
        lp = LocalHFMedia({"id": "local_hf"})
        with mock.patch.object(lp, "_asr", lambda *a, **k: {"text": "só texto"}):
            self.assertEqual(lp.transcribe_segments(b"x", "a.wav", "audio/wav", duration=4.0), [{"start": 0.0, "end": 4.0, "text": "só texto"}])
            self.assertEqual(lp.transcribe_segments(b"x", "a.wav", "audio/wav"), [{"start": 0.0, "end": 3.0, "text": "só texto"}])


@unittest.skipUnless(FF, "sem ffmpeg")
class TranscriptEngineTests(unittest.TestCase):
    def test_formats(self):
        for fmt, expect in (("plain", "Olá, tudo bem com você? Hoje vamos falar sobre o mar."), ("timestamps", "[0:00] Olá, tudo bem com você?\n[0:04] Hoje vamos falar sobre o mar.")):
            pj = Project([node("t", "transcript", format=fmt, language="pt")], [])
            pj.cs.save_layout(pj.cid, {"nodes": [pj.upload("u", "a"), node("t", "transcript", format=fmt, language="pt")], "edges": [{"from": "u", "to": "t", "port": "media"}]})
            fake = FakeSpeech()
            cv = pj.run(fake)
            self.assertEqual(pj.errors(), {})
            self.assertEqual(pj.result(cv, "t")["text"], expect)
            self.assertEqual(fake.heard[0][0], "pt")

    def test_a_model_without_times_says_so(self):
        pj = Project([])
        pj.cs.save_layout(pj.cid, {"nodes": [pj.upload("u", "a"), node("t", "transcript", format="timestamps")], "edges": [{"from": "u", "to": "t", "port": "media"}]})
        cv = pj.run(FakeSpeech(segs=[sub.seg(0, 5, "bloco")], timed=False))
        self.assertEqual(pj.result(cv, "t")["text"], "bloco")
        self.assertTrue(any("não devolve o tempo" in w for w in pj.warnings("t")))

    def test_a_video_is_read_through_its_audio(self):
        pj = Project([], video=True, audio=False)
        pj.cs.save_layout(pj.cid, {"nodes": [pj.upload("u", "v"), node("t", "transcript")], "edges": [{"from": "u", "to": "t", "port": "media"}]})
        fake = FakeSpeech()
        pj.run(fake)
        self.assertEqual(pj.errors(), {})
        self.assertEqual(fake.heard[0][1], "audio/mpeg")             # o vídeo virou um áudio antes de ir ao modelo

    def test_errors_are_clear(self):
        pj = Project([node("t", "transcript")])
        pj.run(FakeSpeech())
        self.assertIn("Ligue um vídeo ou áudio", pj.errors()["t"])
        self.assertIn("Transcrição", pj.errors()["t"])
        pj2 = Project([])
        pj2.cs.save_layout(pj2.cid, {"nodes": [pj2.upload("u", "a"), node("t", "transcript")], "edges": [{"from": "u", "to": "t", "port": "media"}]})
        pj2.run(FakeSpeech(segs=[]))
        self.assertIn("Não encontrei fala", pj2.errors()["t"])

    def test_without_a_speech_model_the_error_is_the_provider_s(self):
        pj = Project([])
        pj.cs.save_layout(pj.cid, {"nodes": [pj.upload("u", "a"), node("t", "transcript")], "edges": [{"from": "u", "to": "t", "port": "media"}]})
        with mock.patch.object(speech, "build_media", return_value=DemoMedia({"id": "demo"})):
            pj.run()
        self.assertIn("Demo não transcreve", pj.errors()["t"])


@unittest.skipUnless(FF, "sem ffmpeg")
class SubEngineTests(unittest.TestCase):
    def pj(self, params, with_media=True, text=None, ):
        nodes, edges = [], []
        pj = Project([])
        if with_media:
            nodes.append(pj.upload("u", "a"))
            edges.append({"from": "u", "to": "s", "port": "media"})
        if text is not None:
            nodes.append(node("t", "text", text=text))
            edges.append({"from": "t", "to": "s", "port": "text"})
        nodes.append(node("s", "sub", **params))
        pj.cs.save_layout(pj.cid, {"nodes": nodes, "edges": edges})
        return pj

    def test_srt_and_vtt_from_the_speech(self):
        pj = self.pj({"format": "srt"})
        cv = pj.run(FakeSpeech())
        self.assertEqual(pj.errors(), {})
        self.assertEqual(pj.result(cv, "s")["text"], sub.to_srt(SEGS).strip())      # o resultado do nó não guarda a linha em branco do fim
        self.assertTrue(any("2 legenda(s) em SRT" in w for w in pj.warnings("s")))
        pj2 = self.pj({"format": "vtt", "offset": 1.0})
        text = pj2.result(pj2.run(FakeSpeech()), "s")["text"]
        self.assertTrue(text.startswith("WEBVTT"))
        self.assertIn("00:00:01.500 --> 00:00:04.000", text)             # adiantar/atrasar

    def test_long_speech_is_split_and_wrapped(self):
        big = [sub.seg(0, 14, "Uma fala bem comprida que o modelo devolveu num único trecho de catorze segundos, e que não cabe numa legenda só, nem em duas linhas curtas de leitura.")]
        pj = self.pj({"max_chars": 30, "lines": 2, "max_seconds": 5})
        text = pj.result(pj.run(FakeSpeech(segs=big)), "s")["text"]
        cues = sub.parse(text)
        self.assertGreaterEqual(len(cues), 3)
        self.assertTrue(all(c["end"] - c["start"] <= 5.3 for c in cues))
        self.assertTrue(all(len(line) <= 34 for blk in text.split("\n\n") for line in blk.split("\n")[2:]))     # cada linha cabe (30 + uma palavra)

    def test_a_timed_text_is_reformatted_without_the_speech_model(self):
        srt = "1\n00:00:01,000 --> 00:00:03,000\nPrimeira\n\n2\n00:00:04,000 --> 00:00:06,000\nSegunda\n"
        pj = self.pj({"format": "vtt", "offset": 0.5}, with_media=False, text=srt)
        cv = pj.run()                                                   # sem provedor de mentira: não chama a transcrição
        self.assertEqual(pj.errors(), {})
        self.assertEqual(pj.result(cv, "s")["text"], "WEBVTT\n\n00:00:01.500 --> 00:00:03.500\nPrimeira\n\n00:00:04.500 --> 00:00:06.500\nSegunda")

    def test_a_plain_text_is_spread_over_the_media(self):
        pj = self.pj({"format": "srt"}, text="Primeira frase. Segunda frase, maior que a primeira. Terceira.")
        cv = pj.run()
        self.assertEqual(pj.errors(), {})
        cues = sub.parse(pj.result(cv, "s")["text"])
        self.assertEqual(len(cues), 3)
        self.assertAlmostEqual(cues[-1]["end"], 9.0, delta=0.3)          # a duração do áudio de entrada (9 s)
        self.assertTrue(any("não tinha tempos" in w for w in pj.warnings("s")))

    def test_a_plain_text_without_media_needs_the_duration(self):
        pj = self.pj({}, with_media=False, text="Uma frase. Outra frase.")
        pj.run()
        self.assertIn("duração", pj.errors()["s"])
        pj2 = self.pj({"duration": 10}, with_media=False, text="Uma frase. Outra frase.")
        cues = sub.parse(pj2.result(pj2.run(), "s")["text"])
        self.assertAlmostEqual(cues[-1]["end"], 10.0, delta=0.3)

    def test_nothing_connected(self):
        pj = self.pj({}, with_media=False)
        pj.run()
        self.assertIn("Ligue um vídeo ou áudio", pj.errors()["s"])

    def test_unreadable_subtitles_are_reported(self):
        pj = self.pj({}, with_media=False, text="00:00:01,000 --> 99\nxx")
        pj.run()
        self.assertIn("SRT ou VTT", pj.errors()["s"])

    def test_translation_keeps_the_times(self):
        seen = {}

        def chat(self_, provider, messages, system, temperature, max_tokens):
            seen["user"], seen["system"] = messages[0]["content"], system
            return "1| Hello, how are you?\n2| Today we will talk about the sea."
        pj = self.pj({"translate_to": "en", "language": "pt"})
        pj.store.save_settings({"active": {"generation": "llm1"}})
        cv = pj.run(FakeSpeech(), chat=chat)
        self.assertEqual(pj.errors(), {})
        cues = sub.parse(pj.result(cv, "s")["text"])
        self.assertEqual([(c["start"], c["end"], c["text"]) for c in cues], [(0.5, 3.0, "Hello, how are you?"), (4.0, 7.0, "Today we will talk about the sea.")])
        self.assertIn("1| Olá, tudo bem com você?", seen["user"])
        self.assertIn("English", seen["system"])
        self.assertIn("Brazilian Portuguese", seen["system"])

    def test_translation_missing_lines_stay_and_are_reported(self):
        pj = self.pj({"translate_to": "en"})
        pj.store.save_settings({"active": {"generation": "llm1"}})
        cv = pj.run(FakeSpeech(), chat=lambda *a, **k: "1| Hello!\nlixo sem número")
        cues = sub.parse(pj.result(cv, "s")["text"])
        self.assertEqual([c["text"] for c in cues], ["Hello!", "Hoje vamos falar sobre o mar."])
        self.assertTrue(any("1 linha(s) ficaram no idioma original" in w for w in pj.warnings("s")))

    def test_without_a_text_model_it_says_it_did_not_translate(self):
        pj = self.pj({"translate_to": "en"})
        cv = pj.run(FakeSpeech())
        self.assertEqual(pj.errors(), {})
        self.assertEqual(sub.parse(pj.result(cv, "s")["text"])[0]["text"], "Olá, tudo bem com você?")
        self.assertTrue(any("não traduzi" in w for w in pj.warnings("s")))


@unittest.skipUnless(FF, "sem ffmpeg")
class DubEngineTests(unittest.TestCase):
    def pj(self, params, kind="a", script=None, video=False):
        pj = Project([], video=video, audio=not video)
        nodes = [pj.upload("u", kind), node("d", "dub", **params)]
        edges = [{"from": "u", "to": "d", "port": "media"}]
        if script is not None:
            nodes.append(node("t", "text", text=script))
            edges.append({"from": "t", "to": "d", "port": "script"})
        pj.cs.save_layout(pj.cid, {"nodes": nodes, "edges": edges})
        return pj

    def test_audio_dub_replaces_the_original(self):
        pj = self.pj({"language": "keep", "mix": "replace"})
        fake = FakeSpeech()
        cv = pj.run(fake)
        self.assertEqual(pj.errors(), {})
        a, path = pj.asset(cv, "d")
        self.assertEqual((a["kind"], a["mime"]), ("audio", "audio/mpeg"))
        kinds, dur = streams(path)
        self.assertEqual(kinds, ["audio"])
        self.assertAlmostEqual(dur, 9.0, delta=0.3)                     # a duração do original
        self.assertEqual([s[0] for s in fake.spoken], [s["text"] for s in SEGS])
        self.assertIn("[0:04] Hoje vamos falar sobre o mar.", pj.result(cv, "d")["text"])     # o que foi dublado fica no resultado

    def test_duck_keeps_the_original_underneath(self):
        replace = self.pj({"language": "keep", "mix": "replace"})
        duck = self.pj({"language": "keep", "mix": "duck", "original_volume": 0.3})
        r = replace.asset(replace.run(FakeSpeech()), "d")[1].read_bytes()
        d = duck.asset(duck.run(FakeSpeech()), "d")[1].read_bytes()
        self.assertNotEqual(r, d)
        self.assertEqual(duck.errors(), {})

    def test_video_dub_keeps_the_picture_and_swaps_the_sound(self):
        pj = self.pj({"language": "keep"}, kind="v", video=True)
        cv = pj.run(FakeSpeech())
        self.assertEqual(pj.errors(), {})
        a, path = pj.asset(cv, "d")
        self.assertEqual((a["kind"], a["mime"]), ("video", "video/mp4"))
        kinds, dur = streams(path)
        self.assertEqual(sorted(kinds), ["audio", "video"])
        self.assertAlmostEqual(dur, 9.0, delta=0.3)
        self.assertEqual(a["name"], "aula (dublado)")

    def test_translation_then_voice(self):
        spoken = []

        class Voice(FakeSpeech):
            def voice(self, text, **kw):
                spoken.append(text)
                return super().voice(text, **kw)
        pj = self.pj({"language": "en", "source_language": "pt"})
        pj.store.save_settings({"active": {"generation": "llm1"}})
        pj.run(Voice(), chat=lambda *a, **k: "1| Hello, how are you?\n2| Today we talk about the sea.")
        self.assertEqual(pj.errors(), {})
        self.assertEqual(spoken, ["Hello, how are you?", "Today we talk about the sea."])

    def test_a_script_replaces_the_transcription_and_works_offline(self):
        srt = "1\n00:00:00,500 --> 00:00:03,500\nBom dia a todos\n\n2\n00:00:05,000 --> 00:00:08,000\nVamos começar\n"
        pj = self.pj({"language": "en"}, script=srt)
        cv = pj.run()                                                   # nenhum provedor de mentira: voz Demo e SEM modelo de transcrição
        self.assertEqual(pj.errors(), {})
        a, path = pj.asset(cv, "d")
        self.assertEqual(a["kind"], "audio")
        self.assertIn("[0:05] Vamos começar", pj.result(cv, "d")["text"])
        self.assertTrue(any("Voz de demonstração" in w for w in pj.warnings("d")))
        self.assertFalse(any("não traduzi" in w for w in pj.warnings("d")))     # o roteiro é dublado como está: não se traduz

    def test_a_plain_script_is_spread_over_the_file(self):
        pj = self.pj({}, script="Primeira frase. Segunda frase um pouco maior. Terceira.")
        cv = pj.run()
        self.assertEqual(pj.errors(), {})
        self.assertTrue(any("não tinha tempos" in w for w in pj.warnings("d")))
        self.assertAlmostEqual(streams(pj.asset(cv, "d")[1])[1], 9.0, delta=0.4)

    def test_speech_that_does_not_fit_is_sped_up_or_pushed_back(self):
        tight = [sub.seg(0.0, 0.8, "Uma frase longa demais para caber em menos de um segundo de tempo"), sub.seg(1.0, 1.5, "Outra frase longa também para caber aqui")]
        fit = self.pj({"language": "keep", "fit": True})
        fit.run(FakeSpeech(segs=tight))
        self.assertEqual(fit.errors(), {})
        self.assertTrue(any("foram acelerados" in w for w in fit.warnings("d")))
        nofit = self.pj({"language": "keep", "fit": False})
        nofit.run(FakeSpeech(segs=tight))
        self.assertFalse(any("acelerados" in w for w in nofit.warnings("d")))
        self.assertTrue(any("começaram mais de 0,3 s depois" in w for w in nofit.warnings("d")))      # a fala nunca se sobrepõe: o 2º trecho atrasa

    def test_place_never_overlaps_and_keeps_the_start(self):
        pj = Project([])
        eng = CanvasEngine(pj.store, pj.cid, lambda e: None, lambda: False)
        wav = proc.babble("palavras suficientes para uma fala de pelo menos um segundo ou mais", 1.0, 1)
        clips = [(sub.seg(2.0, 4.0, "a"), Media(wav, "audio/wav")), (sub.seg(2.5, 4.0, "b"), Media(wav, "audio/wav"))]
        track, fitted, late = speech.place(eng, clips, 6.0, False, [])
        self.assertEqual(len(track), max(int(6.0 * speech.DUB_SR), len(track)))
        self.assertEqual(sum(1 for v in track[: int(1.9 * speech.DUB_SR)] if v), 0)          # silêncio antes do começo do 1º trecho
        self.assertGreater(sum(1 for v in track[int(2.0 * speech.DUB_SR): int(2.5 * speech.DUB_SR)] if v), 100)
        self.assertEqual((fitted, late), (0, 1))                                              # o 2º começou depois do 1º terminar

    def test_errors(self):
        pj = Project([node("d", "dub")])
        pj.run(FakeSpeech())
        self.assertIn("Ligue um vídeo ou áudio", pj.errors()["d"])
        self.assertIn("Dublagem", pj.errors()["d"])
        empty = self.pj({"language": "keep"})
        empty.run(FakeSpeech(segs=[]))
        self.assertIn("Não encontrei fala", empty.errors()["d"])
        bad = self.pj({}, script="00:00:01,000 --> 99\nruim")
        bad.run()
        self.assertIn("SRT ou VTT", bad.errors()["d"])

    def test_many_segments_are_capped(self):
        many = [sub.seg(i * 0.4, i * 0.4 + 0.3, f"fala {i}") for i in range(speech.MAX_DUB_SEGS + 20)]
        pj = self.pj({"language": "keep"})
        with mock.patch.object(speech, "place", return_value=(speech.array("h", bytes(2 * speech.DUB_SR * 9)), 0, 0)):
            fake = FakeSpeech(segs=many)
            pj.run(fake)
        self.assertEqual(pj.errors(), {})
        self.assertEqual(len(fake.spoken), speech.MAX_DUB_SEGS)
        self.assertTrue(any(f"no máximo {speech.MAX_DUB_SEGS} trechos" in w for w in pj.warnings("d")))

    def test_the_cache_follows_the_script(self):
        srt = "1\n00:00:00,500 --> 00:00:03,500\nBom dia\n"
        pj = self.pj({"language": "en"}, script=srt)
        pj.run()
        pj.run(force=False)
        self.assertTrue(any(e.get("state") == "cached" and e.get("id") == "d" for e in pj.events))
        cv = pj.cs.get(pj.cid)
        nodes = cv["nodes"]
        next(n for n in nodes if n["id"] == "t")["params"]["text"] = srt.replace("Bom dia", "Boa noite")
        pj.cs.save_layout(pj.cid, {"nodes": nodes, "edges": cv["edges"]})
        pj.run(force=False)
        self.assertTrue(any(e.get("state") == "done" and e.get("id") == "d" for e in pj.events))


if __name__ == "__main__":
    unittest.main()
