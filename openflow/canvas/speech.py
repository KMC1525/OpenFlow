"""Fala em vídeos e sons (v0.62): os nós Transcrição (`transcript`), Legendas (`sub`) e Dublagem (`dub`).

- **Transcrição:** o modelo de transcrição (Whisper local) devolve a fala com tempo; sai como texto corrido, com marcas de tempo ou em parágrafos.
- **Legendas:** SRT ou VTT para qualquer reprodutor, a partir da fala do vídeo/áudio ou de um texto (que pode já ser uma legenda). Divide cues longos, quebra linhas, adianta/atrasa e traduz com o modelo de texto.
- **Dublagem:** a fala (transcrita, ou o roteiro/legendas ligados) é traduzida, falada por segmento pelo modelo de voz, encaixada no tempo de cada trecho e misturada ao áudio ou vídeo original.

Os nós rodam pela engine (`eng`): ela dá as entradas, o provedor e o cancelamento. A parte sem modelo está em `subtitles.py`.
"""
from __future__ import annotations

import re
import sys
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..providers import ProviderError, build_provider
from . import autoclone, diarize
from . import subtitles as sub
from . import voicestyle
from .media import MIME_EXT, build_media, media_config, pick_provider
from .nodes_ext import _aud_args, _ff, _file_duration, _need_ffmpeg, _save_file

DUB_SR = 24000          # taxa da faixa dublada (mono): a maioria dos modelos de voz fala a 22–24 kHz
MAX_DUB_SEGS = 300      # trechos por dublagem (cada um é uma chamada ao modelo de voz)
MAX_TEMPO = 1.6         # o quanto uma fala é acelerada para caber no tempo do trecho (acima disso soa apressada demais)
MAX_SPEECH = 800        # caracteres falados por trecho


def _label(node: Dict[str, Any], port: str) -> str:
    from .schema import NODE_TYPES

    return next((i[1] for i in NODE_TYPES[node["type"]]["ins"] if i[0] == port), port)


def media_input(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any], port: str = "media") -> Optional[Dict[str, Any]]:
    """O primeiro áudio/vídeo ligado na porta (None se não há)."""
    return next((a for a in eng.inputs(canvas, node, port)["assets"] if a["kind"] in ("audio", "video")), None)


NODE_NAMES = {"transcript": "Transcrição", "sub": "Legendas", "dub": "Dublagem"}


def need_media(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any], port: str = "media") -> Dict[str, Any]:
    a = media_input(eng, canvas, node, port)
    if not a:
        raise ValueError(f"Ligue um vídeo ou áudio na entrada «{_label(node, port)}» do nó {NODE_NAMES.get(node['type'], '')}.")
    return a


def transcribe_media(eng: Any, src: Dict[str, Any], language: str, provider: str = "", model: str = "") -> Tuple[List[Dict[str, Any]], bool, str]:
    """A fala do arquivo com tempo. Devolve (segmentos, o provedor devolveu tempos?, nome do provedor). Um vídeo passa antes por uma extração só do áudio."""
    from .engine import _audio_of_video

    path = eng.cs.asset_path(eng.cid, src["file"])
    if not path:
        raise ValueError("O arquivo de entrada não existe mais.")
    data, mime, name = path.read_bytes(), src["mime"], src["name"]
    if src["kind"] == "video":
        extracted = _audio_of_video(path, eng.ctl)
        if extracted:
            data, mime, name = extracted
    pid = pick_provider(eng.settings, "stt", provider)
    prov = build_media(eng.settings, pid, eng.ctl, eng.store.models_dir)
    use_model = model or media_config(eng.settings, pid)["models"].get("stt", "")
    eng._check()
    eng.ctl.note("Transcrevendo a fala…")
    segs = prov.transcribe_segments(data, name, mime, language="" if language in ("", "auto") else language, model=model, duration=float(src.get("duration") or 0.0))
    return segs, bool(prov.timed_segments(use_model)), prov.label


_NUMBERED = re.compile(r"^\s*(\d{1,4})\s*[|:)\].\-]\s*(.*)$")


def translate(eng: Any, texts: List[str], source: str, target: str, warnings: List[str]) -> List[str]:
    """Traduz as linhas com o modelo de texto ativo, em lotes numerados (uma linha entra, uma linha sai). Sem modelo de texto (Demo) as linhas ficam como estão, com um aviso; a que o modelo não devolver
    também fica no idioma original, e o aviso diz quantas."""
    pid = eng.settings["active"].get("generation", "demo")
    if pid == "demo" or not texts:
        if texts:
            warnings.append("Sem modelo de texto configurado: não traduzi (em Configuração → Provedores você liga um modelo de texto). O texto ficou no idioma original.")
        return list(texts)
    provider = build_provider(eng.settings, pid, eng.store.models_dir)
    dst = sub.LANGS_EN.get(target, target)
    src = sub.LANGS_EN.get(source, "") if source and source != "auto" else ""
    system = (f"You are a professional audiovisual translator. Translate each numbered line {('from ' + src + ' ') if src else ''}into {dst}, keeping the meaning, the tone and roughly the same length so it can be spoken or read in the same time. "
              "Answer with exactly one line per input line, in the same order, in the format `N| translation` (keep the number). No comments, no quotes, no markdown, never merge or split lines.")
    out = list(texts)
    missing = 0
    for start in range(0, len(texts), 40):
        batch = texts[start:start + 40]
        eng._check()
        raw = eng.text_chat(provider, [{"role": "user", "content": "\n".join(f"{i + 1}| {t.replace(chr(10), ' ')}" for i, t in enumerate(batch))}], system, 0.2, 3000)
        got: Dict[int, str] = {}
        for line in str(raw).splitlines():
            m = _NUMBERED.match(line)
            if m and m.group(2).strip():
                got[int(m.group(1))] = m.group(2).strip()
        for i in range(len(batch)):
            if i + 1 in got:
                out[start + i] = got[i + 1]
            else:
                missing += 1
    if missing:
        warnings.append(f"{missing} linha(s) ficaram no idioma original: o modelo de texto não devolveu a tradução delas.")
    return out


# ----------------------------------------------------------------------------- Transcrição
def run_transcript(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
    p = node["params"]
    src = need_media(eng, canvas, node)
    warnings: List[str] = []
    segs, timed, label = transcribe_media(eng, src, p["language"], p["provider"], p["model"])
    if not timed and p["format"] != "plain":
        warnings.append(f"{label} não devolve o tempo de cada trecho: a transcrição saiu num bloco só (o formato «{'Com marcas de tempo' if p['format'] == 'timestamps' else 'Parágrafos'}» não se aplica).")
    names: List[str] = []
    if p.get("diarize") and timed:
        segs, names = who_speaks(eng, src, segs, int(p.get("speakers") or 0), p.get("speaker_names", ""), warnings)
    elif int(p.get("speakers") or 0) > 1 and not timed:
        warnings.append(f"{label} não devolve o tempo de cada trecho, então não consigo separar as vozes (use um modelo de transcrição com tempos, como o Whisper).")
    text = sub.transcript_text(segs, p["format"] if timed else "plain", names)
    if not text.strip():
        raise ValueError("Não encontrei fala neste arquivo (ou o modelo não entendeu nada).")
    return {"assets": [], "text": text, "warnings": warnings}


def who_speaks(eng: Any, src: Dict[str, Any], segs: List[Dict[str, Any]], count: int, names_text: str, warnings: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Separa as vozes da transcrição (v0.69). Em automático (`count` 0) uma voz só deixa tudo como estava; sem ffmpeg/numpy ou com falha na leitura do áudio, a transcrição sai sem locutores
    (e o aviso aparece só quando o usuário pediu mais de uma voz)."""
    from . import diarize

    asked = count > 1
    path = eng.cs.asset_path(eng.cid, src["file"])
    x = diarize.decode(path) if path else None
    if x is None:
        if asked:
            warnings.append("Não consegui separar as vozes: isso precisa do ffmpeg e do numpy (pip install numpy) e de um áudio legível.")
        return segs, []
    eng._check()
    eng.ctl.note("Separando as vozes…")
    try:
        out, found = diarize.label_segments(x, segs, count)
    except Exception as exc:   # análise de apoio: falhar não pode perder a transcrição
        warnings.append(f"Não consegui separar as vozes ({type(exc).__name__}); a transcrição saiu sem locutores.")
        return segs, []
    if found <= 1:
        if asked:
            warnings.append("Só encontrei uma voz neste áudio.")
        return segs, []
    given = diarize.parse_names(names_text)
    if given and len(given) < found:
        warnings.append(f"Você deu {len(given)} nome(s) e há {found} vozes: as outras ficam como «Locutor N».")
    eng.ctl.note(f"{found} vozes encontradas.")
    return out, given


# ----------------------------------------------------------------------------- Legendas
def run_sub(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
    p = node["params"]
    warnings: List[str] = []
    text_in = eng.inputs(canvas, node, "text")["text"].strip()
    src = media_input(eng, canvas, node)
    lang = p["language"]
    if text_in:
        if sub.looks_timed(text_in):
            segs = sub.parse(text_in)
            if not segs:
                raise ValueError("Não consegui ler as legendas ligadas (esperava SRT ou VTT: «00:00:01,000 --> 00:00:03,000»).")
        else:
            total = float(src.get("duration") or 0.0) if src else 0.0
            if total <= 0 and src:
                total = float(_file_duration(eng.cs.asset_path(eng.cid, src["file"]) or Path("")) or 0.0)
            total = total or float(p["duration"])
            if total <= 0:
                raise ValueError("Para distribuir o texto no tempo preciso da duração: ligue o vídeo/áudio na entrada «Vídeo ou áudio» ou escreva a duração (s) no nó.")
            segs = sub.spread(text_in, total, p["max_chars"] * p["lines"])
            warnings.append(f"O texto não tinha tempos: distribuí as {len(segs)} legendas ao longo de {total:.0f} s, em proporção ao tamanho de cada uma (não acompanha a fala de verdade).")
    elif src:
        segs, timed, label = transcribe_media(eng, src, lang, p["provider"], p["model"])
        if not timed:
            warnings.append(f"{label} não devolve o tempo de cada trecho: a legenda saiu num cue só, do começo ao fim. Use um modelo de transcrição com tempos (Whisper local).")
    else:
        raise ValueError("Ligue um vídeo ou áudio na entrada «Vídeo ou áudio» (para transcrever) ou um texto na entrada «Texto ou legendas».")
    if p["translate_to"]:
        texts = translate(eng, [s["text"] for s in segs], lang, p["translate_to"], warnings)
        segs = [sub.seg(s["start"], s["end"], t) for s, t in zip(segs, texts)]
    cut = sub.split_long(segs, p["max_chars"] * p["lines"], p["max_seconds"])
    segs = sub.tidy(sub.shift(cut, p["offset"]))
    if not segs:
        if cut and p["offset"]:   # v0.74: o erro dizia «não encontrei fala» quando, na verdade, o deslocamento empurrou todas as legendas para antes do zero
            raise ValueError(f"Com «Adiantar/atrasar» em {p['offset']:g} s todas as legendas ficariam antes do início do arquivo. Use um valor menor (a fala termina em {max(s['end'] for s in cut):.1f} s).")
        raise ValueError("Não encontrei fala para legendar.")
    out = (sub.to_vtt if p["format"] == "vtt" else sub.to_srt)(segs, p["max_chars"], p["lines"])
    warnings.insert(0, f"{len(segs)} legenda(s) em {p['format'].upper()}: use o botão «Baixar» do nó e carregue o arquivo no reprodutor.")
    return {"assets": [], "text": out, "warnings": warnings}


# ----------------------------------------------------------------------------- Dublagem
def _pcm(eng: Any, data: bytes, mime: str, tempo: float = 1.0) -> "array[int]":
    """A fala sintetizada (qualquer formato) em PCM 16 bits mono a 24 kHz, com a velocidade ajustada (`tempo` 1,0 = normal)."""
    ext = MIME_EXT.get((mime or "").split(";")[0].strip().lower(), "wav")
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / f"in.{ext}", Path(td) / "out.wav"
        src.write_bytes(data)
        af = ["-af", f"atempo={tempo:.3f}"] if abs(tempo - 1.0) > 0.01 else []
        _ff(eng, ["-i", str(src), "-vn", "-ac", "1", "-ar", str(DUB_SR), *af, "-c:a", "pcm_s16le", str(dst)])
        with wave.open(str(dst), "rb") as w:
            frames = w.readframes(w.getnframes())
    pcm = array("h")
    pcm.frombytes(frames)
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm


def place(eng: Any, clips: List[Tuple[Dict[str, Any], Any]], duration: float, fit: bool, warnings: List[str]) -> Tuple["array[int]", int, int]:
    """Põe a fala de cada trecho na faixa, no tempo dele. Uma fala mais longa que o trecho é acelerada (`fit`, até 1,6×); se ainda passar, o trecho seguinte começa depois dela (a fala nunca se sobrepõe).
    Devolve (a faixa, quantos foram acelerados, quantos atrasaram mais de 0,3 s)."""
    placed: List[Tuple[int, "array[int]"]] = []
    cursor = 0.0
    fitted = late = 0
    for i, (s, media) in enumerate(clips):
        eng._check()
        pcm = _pcm(eng, media.data, media.mime)
        clip = len(pcm) / DUB_SR
        nxt = clips[i + 1][0]["start"] if i + 1 < len(clips) else (duration if duration > s["start"] else s["start"] + clip)
        avail = max(0.3, nxt - s["start"] - 0.05)
        if fit and clip > avail + 0.05:
            tempo = min(MAX_TEMPO, clip / avail)
            pcm = _pcm(eng, media.data, media.mime, tempo)
            clip = len(pcm) / DUB_SR
            fitted += 1
        pos = max(s["start"], cursor)
        if pos > s["start"] + 0.3:
            late += 1
        placed.append((int(pos * DUB_SR), pcm))
        cursor = pos + clip + 0.05
    total = max([int(duration * DUB_SR)] + [off + len(p) for off, p in placed])
    track = array("h", bytes(2 * total))
    for off, pcm in placed:
        track[off:off + len(pcm)] = pcm
    return track, fitted, late


def _write_wav(path: Path, track: "array[int]") -> None:
    data = array("h", track)
    if sys.byteorder == "big":
        data.byteswap()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(DUB_SR)
        w.writeframes(data.tobytes())


def mux(eng: Any, src_path: Path, kind: str, track: Path, out: Path, mode: str, volume: float, has_orig_audio: bool) -> None:
    """Junta a faixa dublada ao arquivo original: `replace` troca o áudio; `duck` mantém o original baixinho por baixo (`volume`)."""
    duck = mode == "duck" and has_orig_audio
    mix_a = f"[0:a]aresample=44100,volume={volume:.2f}[o];[1:a]aresample=44100[d];[o][d]amix=inputs=2:duration=longest:normalize=0[m]"
    mix_b = f"[0:a]aresample=44100,volume={volume:.2f}[o];[1:a]aresample=44100[d];[o][d]amix=inputs=2:duration=longest,volume=2[m]"   # ffmpeg sem a opção normalize
    if kind == "audio":
        if not duck:
            _ff(eng, ["-i", str(track), *_aud_args("mp3"), str(out)])
            return
        try:
            _ff(eng, ["-i", str(src_path), "-i", str(track), "-filter_complex", mix_a, "-map", "[m]", *_aud_args("mp3"), str(out)])
        except ProviderError:
            _ff(eng, ["-i", str(src_path), "-i", str(track), "-filter_complex", mix_b, "-map", "[m]", *_aud_args("mp3"), str(out)])
        return
    audio = ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    tries: List[List[str]] = []
    for vcodec in (["-c:v", "copy"], ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]):
        if duck:
            tries += [["-i", str(src_path), "-i", str(track), "-filter_complex", mix_a, "-map", "0:v:0", "-map", "[m]", *vcodec, *audio, str(out)],
                      ["-i", str(src_path), "-i", str(track), "-filter_complex", mix_b, "-map", "0:v:0", "-map", "[m]", *vcodec, *audio, str(out)]]
        else:
            tries.append(["-i", str(src_path), "-i", str(track), "-map", "0:v:0", "-map", "1:a:0", *vcodec, *audio, str(out)])
    last: Optional[ProviderError] = None
    for args in tries:
        try:
            _ff(eng, args)
            return
        except ProviderError as exc:
            last = exc
    raise last or ProviderError("O ffmpeg não conseguiu juntar a dublagem ao vídeo.")


def _reference_of(eng: Any, canvas: Dict[str, Any], vn: Dict[str, Any]) -> Optional[Tuple[bytes, str]]:
    """A voz de referência ligada a um nó Voz (v0.71), como (bytes, mime), para clonar a voz de um personagem na Dublagem; None se não há."""
    a = next((x for x in eng.inputs(canvas, vn, "reference")["assets"] if x["kind"] in ("audio", "video")), None)
    data = eng._asset_bytes(a) if a else None
    return (data, a["mime"]) if data else None


def voice_profiles(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any], warnings: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """As vozes ligadas à porta «Vozes» da Dublagem (v0.63), na ordem das conexões. Cada nó Voz vira um perfil: o nome do personagem (o título do nó, ou o nome da voz, ou «Voz 1», «Voz 2»…), o provedor e o
    modelo dele, a voz, a velocidade e o estilo. O que não é um nó Voz é ignorado (com aviso)."""
    out: List[Dict[str, Any]] = []
    for src in eng._edges_to(canvas, node["id"], "voices"):
        vn = eng._node(canvas, src)
        if not vn:
            continue
        if vn["type"] != "voice":
            if warnings is not None:
                warnings.append(f"«{vn.get('title') or vn['type']}» não é um nó Voz: ignorei (na entrada «Vozes» ligue nós Voz).")
            continue
        vp = vn["params"]
        pid = pick_provider(eng.settings, "voice", vp.get("provider", ""))
        title = (vn.get("title") or "").strip()
        n = len(out) + 1
        aliases = [a for a in (title, str(vp.get("voice") or "").strip(), f"Voz {n}") if a]
        out.append({"id": vn["id"], "name": aliases[0], "aliases": aliases, "pid": pid, "model": vp.get("model") or media_config(eng.settings, pid)["models"].get("voice", ""), "model_override": vp.get("model", ""),
                    "voice": vp.get("voice", ""), "voice_style": str(vp.get("voice_style") or ""), "speed": vp.get("speed", 1.0), "extra": vp.get("extra") or {}, "style": eng.styles_for(canvas, vn), "node": vn,
                    "reference": _reference_of(eng, canvas, vn), "reference_text": str(vp.get("reference_text") or "")})
    return out


def profile_signature(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any]) -> List[Any]:
    """O que as vozes ligadas têm de ajuste (nome, modelo, voz, velocidade, estilo), para o cache da Dublagem: trocar a voz de um personagem refaz a dublagem; o áudio de exemplo do nó Voz não entra."""
    import json

    sig: List[Any] = []
    for src in eng._edges_to(canvas, node["id"], "voices"):
        vn = eng._node(canvas, src)
        if not vn or vn["type"] != "voice":
            continue
        vp = vn["params"]
        pid = pick_provider(eng.settings, "voice", vp.get("provider", ""))
        sig.append([vn["id"], vn.get("title", ""), pid, vp.get("model") or media_config(eng.settings, pid)["models"].get("voice", ""), vp.get("voice", ""), vp.get("voice_style", ""), vp.get("speed", 1.0),
                    json.dumps(vp.get("extra") or {}, sort_keys=True), eng.styles_for(canvas, vn, need_digest=False).signature(), eng.style_ids(canvas, vn),
                    [a["id"] for a in eng.inputs(canvas, vn, "reference")["assets"]], vp.get("reference_text", "")])
    return sig


def _auto_voices(eng: Any, path: Path, base: Dict[str, Any], orig: List[Dict[str, Any]], orig_timed: bool, transcribed: bool, segs: List[Dict[str, Any]], p: Dict[str, Any],
                 warnings: List[str]) -> Optional[Tuple[List[Dict[str, Any]], List[Tuple[int, str]]]]:
    """Dublagem automática com a voz de cada locutor (v0.80): se o modelo de voz clona voz e o usuário não ligou nós Voz, tira do áudio original uma amostra da voz de cada pessoa e dubla cada fala com a voz
    clonada de quem a disse (`autoclone`). Devolve (perfis, quem fala cada trecho) ou None (modelo que não clona, sem numpy/ffmpeg, sem fala suficiente: a dublagem segue com a voz do nó)."""
    prov = base.get("prov")
    if prov is None or not prov.clones_voice(base["model_override"] or base["model"]):
        return None
    x = diarize.decode(path)
    if x is None:
        warnings.append("Não consegui clonar a voz do original: isso precisa do ffmpeg e do numpy (pip install numpy) e de um áudio legível. Dublei com a voz do nó.")
        return None
    eng._check()
    eng.ctl.note("Separando as vozes do original e preparando a clonagem de cada uma…")
    labelled, voices, notes = autoclone.plan(x, orig, orig_timed, p["speakers"])
    warnings += notes
    if not any(v["wav"] for v in voices):
        warnings.append("Não achei fala suficiente no original (menos de 1,5 s) para clonar a voz: dublei com a voz do nó.")
        return None
    same_language = p["language"] == "keep" and transcribed and not str(base.get("voice_style") or "").strip()   # a clonagem fiel (amostra + texto dela) pede o mesmo idioma e uma transcrição de verdade
    profiles: List[Dict[str, Any]] = []
    for i, v in enumerate(voices):
        prof = dict(base, name=diarize.speaker_name(i, []) if len(voices) > 1 else "", aliases=[])
        if v["wav"]:
            prof["reference"] = (v["wav"], "audio/wav")
            prof["reference_text"] = v["text"] if same_language else ""
        profiles.append(prof)
    who = [(min(len(profiles) - 1, autoclone.speaker_of(labelled, s["start"], s["end"])) if labelled else 0, s["text"]) for s in segs]
    done = [f"{(diarize.speaker_name(i, []) + ' ') if len(voices) > 1 else ''}(amostra de {v['seconds']:g} s)".strip() for i, v in enumerate(voices) if v["wav"]]
    warnings.append("Voz clonada do áudio original: " + ", ".join(done) + ". Música ou ruído de fundo no original vão para a voz clonada também.")
    for i, v in enumerate(voices):
        if not v["wav"] and len(voices) > 1:
            warnings.append(f"«{diarize.speaker_name(i, [])}» fala pouco no original (menos de 1,5 s): ficou com a voz do nó.")
    return profiles, who


def run_dub(eng: Any, canvas: Dict[str, Any], node: Dict[str, Any]) -> Dict[str, Any]:
    p = node["params"]
    warnings: List[str] = []
    _need_ffmpeg()
    src = need_media(eng, canvas, node)
    path = eng.cs.asset_path(eng.cid, src["file"])
    if not path:
        raise ValueError("O arquivo de entrada não existe mais.")
    duration = float(src.get("duration") or 0.0) or float(_file_duration(path) or 0.0)
    script = eng.inputs(canvas, node, "script")["text"].strip()
    orig: List[Dict[str, Any]] = []     # a fala original, com os tempos dela (para separar e clonar as vozes: v0.80)
    orig_timed = transcribed = False
    if script:
        if sub.looks_timed(script):
            segs = sub.parse(script)
            if not segs:
                raise ValueError("Não consegui ler as legendas ligadas em «Roteiro» (esperava SRT ou VTT).")
            orig, orig_timed = list(segs), True
        else:
            if duration <= 0:
                raise ValueError("Não consegui medir a duração do arquivo para distribuir o roteiro no tempo.")
            segs = sub.spread(script, duration, 160)
            warnings.append("O roteiro não tinha tempos: distribuí a fala ao longo do arquivo em proporção ao tamanho de cada frase.")
    else:
        segs, timed, label = transcribe_media(eng, src, p["source_language"])
        orig, orig_timed, transcribed = list(segs), bool(timed), True
        if not timed:
            warnings.append(f"{label} não devolve o tempo de cada trecho: a dublagem saiu como uma fala só, do começo ao fim.")
        if p["language"] != "keep":
            texts = translate(eng, [s["text"] for s in segs], p["source_language"], p["language"], warnings)
            segs = [sub.seg(s["start"], s["end"], t) for s, t in zip(segs, texts)]
    segs = sub.tidy(sub.split_long(segs, 240, 18.0))
    if not segs:
        raise ValueError("Não encontrei fala para dublar.")
    if len(segs) > MAX_DUB_SEGS:
        warnings.append(f"A dublagem tem no máximo {MAX_DUB_SEGS} trechos: dublei os primeiros {MAX_DUB_SEGS} de {len(segs)}.")
        segs = segs[:MAX_DUB_SEGS]
    profiles = voice_profiles(eng, canvas, node, warnings)
    if profiles:   # nós Voz ligados (v0.63): valem no lugar da voz do próprio nó; cada personagem fala com a sua
        who, extra_warn = sub.assign_speakers(segs, [v["aliases"] for v in profiles], p["assign"])
        warnings += extra_warn
    else:
        _prov, own_pid, _model = eng._provider(node)
        profiles = [{"name": "", "aliases": [], "pid": own_pid, "model": _model, "model_override": p["model"], "voice": p["voice"], "voice_style": p["voice_style"], "speed": p["speed"], "extra": p["extra"], "style": None, "prov": _prov}]
        who = [(0, s["text"]) for s in segs]
        if p["clone"] == "auto":   # v0.80: o modelo clona voz (VoxCPM2) e não há nós Voz: a voz de cada locutor do original é clonada sozinha
            auto = _auto_voices(eng, path, profiles[0], orig, orig_timed, transcribed, segs, p, warnings)
            if auto:
                profiles, who = auto
    clips: List[Tuple[Dict[str, Any], Any]] = []
    spoken: List[Dict[str, Any]] = []
    counts = [0] * len(profiles)
    built: Dict[str, Any] = {}
    cloned_warned: List[str] = []
    for i, (s, (vi, line)) in enumerate(zip(segs, who)):
        eng._check()
        eng.ctl.note(f"Dublando {i + 1} de {len(segs)}…")
        v = profiles[vi]
        prov = v.get("prov") or built.setdefault(v["pid"], build_media(eng.settings, v["pid"], eng.ctl, eng.store.models_dir))
        instructions = voicestyle.compose(v.get("voice_style", ""), v["style"].render(line) if v.get("style") is not None else "")
        ref = v.get("reference") if v.get("reference") and prov.clones_voice(v["model_override"] or v["model"]) else None
        if v.get("reference") and not ref and v["name"] not in cloned_warned:
            cloned_warned.append(v["name"])
            warnings.append(f"«{v['name'] or 'Voz'}»: o modelo de voz não clona voz, então a «Voz de referência» foi ignorada.")
        clips.append((s, prov.voice(line[:MAX_SPEECH], voice=v["voice"], speed=v["speed"], model=v["model_override"], extra=v["extra"], instructions=instructions, **({"reference": ref, "reference_text": v.get("reference_text", "")} if ref else {}))))
        spoken.append(sub.seg(s["start"], s["end"], (v["name"] + ": " if len(profiles) > 1 and v["name"] else "") + line))
        counts[vi] += 1
    if len(profiles) > 1:
        warnings.append("Vozes usadas: " + ", ".join(f"{v['name']} ({n} fala{'s' if n != 1 else ''})" for v, n in zip(profiles, counts) if n) + ".")
    noted: List[str] = []
    for v, n in zip(profiles, counts):   # «Como é a voz» (v0.64): o modelo que não a lê por inteiro avisa
        if n and str(v.get("voice_style") or "").strip():
            note = (v.get("prov") or built.get(v["pid"])).voice_style_note(v.get("model_override") or v.get("model") or "")
            if note and note not in noted:
                noted.append(note)
    warnings += noted
    if any(v["pid"] == "demo" for v, n in zip(profiles, counts) if n):
        warnings.append("Voz de demonstração: um balbucio no ritmo do texto, não fala de verdade. Escolha um modelo de voz em Configuração → Mídia para uma dublagem real.")
    track, fitted, late = place(eng, clips, duration, p["fit"], warnings)
    if fitted:
        warnings.append(f"{fitted} trecho(s) foram acelerados (até {MAX_TEMPO}×) para caber no tempo da fala original.")
    if late:
        warnings.append(f"{late} trecho(s) começaram mais de 0,3 s depois do original: a fala dublada ficou mais longa que o espaço dela (use uma velocidade maior ou um roteiro mais curto).")
    name = (Path(src["name"]).stem or "dublagem") + " (dublado)"
    from .render import has_audio

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "dub.wav"
        _write_wav(wav, track)
        ext = "mp4" if src["kind"] == "video" else "mp3"
        out = Path(td) / f"out.{ext}"
        mux(eng, path, src["kind"], wav, out, p["mix"], p["original_volume"], has_audio(path))
        res = {"assets": [_save_file(eng, node, out, src["kind"], name, "video/mp4" if ext == "mp4" else "audio/mpeg")], "text": sub.transcript_text(spoken, "timestamps"), "warnings": warnings}
    return res


RUNNERS = {"transcript": run_transcript, "sub": run_sub, "dub": run_dub}
