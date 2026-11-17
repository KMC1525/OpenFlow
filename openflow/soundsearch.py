"""Busca de modelos de som no Hugging Face (v0.65): assuntos (música, efeitos, voz, dublagem…), limpeza do ruído e o selo «roda no OpenFlow».

O filtro `text-to-audio` do Hub mistura de tudo: modelos de vídeo que também geram áudio (LTX), assistentes «omni», conversores de voz, codecs e vozes de texto → fala ao lado das músicas. Aqui cada resultado é
classificado pelas tags, pela biblioteca e pelo nome em **assuntos**; o que não é som sai; e cada um ganha um selo dizendo se o OpenFlow **tem suporte** àquela família de modelo (hoje: MusicGen para sons e músicas,
Bark, MMS-TTS, Orpheus e CSM para voz, Whisper para transcrição). Tudo Python puro, sem rede (a consulta ao Hub está em `hf.search_sound`).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

# capacidade do nó → [(assunto, rótulo)]; o primeiro é o padrão
TOPICS: Dict[str, List[Tuple[str, str]]] = {
    "sound": [("music", "Música"), ("sfx", "Efeitos sonoros (SFX)"), ("tools", "Separar e melhorar áudio")],
    "voice": [("tts", "Voz (texto → fala)"), ("clone", "Clonar ou trocar a voz"), ("design", "Voz criada por descrição"), ("dub", "Dublagem (fala → fala em outro idioma)")],
    "stt": [("asr", "Transcrição e legendas")],
}
DEFAULT_TOPIC = {cap: topics[0][0] for cap, topics in TOPICS.items()}

# o que perguntar ao Hub por assunto: pares (pipeline_tag, tag extra ou None). As tags extras trazem o que o `pipeline_tag` sozinho esconde no meio do ruído.
FETCH: Dict[Tuple[str, str], List[Tuple[str, Optional[str]]]] = {
    ("sound", "music"): [("text-to-audio", "music"), ("text-to-audio", "music-generation"), ("text-to-audio", "text-to-music"), ("text-to-audio", "text2music"), ("text-to-audio", None)],
    ("sound", "sfx"): [("text-to-audio", "sound-effects"), ("text-to-audio", "sfx"), ("text-to-audio", None)],
    ("sound", "tools"): [("audio-to-audio", "source-separation"), ("audio-to-audio", "speech-enhancement"), ("audio-to-audio", "audio-separation"), ("audio-to-audio", None)],
    ("voice", "tts"): [("text-to-speech", None)],
    ("voice", "clone"): [("audio-to-audio", "voice-conversion"), ("text-to-speech", "voice-cloning"), ("audio-to-audio", "rvc")],
    ("voice", "design"): [("text-to-speech", "voice-design"), ("text-to-speech", "emotion-control")],
    ("voice", "dub"): [("audio-to-audio", "speech-to-speech"), ("automatic-speech-recognition", "speech-translation"), ("audio-to-audio", "speech-translation"), ("audio-to-audio", None)],
    ("stt", "asr"): [("automatic-speech-recognition", None)],
}


def check_topic(cap: str, topic: str) -> str:
    """O assunto pedido, se vale para a capacidade; senão o padrão dela. ("" para capacidades sem assuntos.)"""
    if cap not in TOPICS:
        return ""
    return topic if any(topic == t for t, _ in TOPICS[cap]) else DEFAULT_TOPIC[cap]


def _norm(s: Any) -> str:
    return unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode("ascii").casefold()


# ----------------------------------------------------------------------------- classificação
VIDEO_TAGS = {"text-to-video", "image-to-video", "video-to-video", "audio-to-video", "video-to-audio", "text-to-audio-video", "image-to-audio-video", "image-text-to-audio-video", "audio-video"}
NOISE_TAGS = {"any-to-any", "neural-vocoder", "vocoder", "codec", "audio-codec", "tokenizer", "audio-tokenizer", "speech-tokenizer"}
NOISE_NAMES = re.compile(r"(bigvgan|hifigan|vocos|codec|tokenizer|vocoder)", re.I)

_TAGS = {
    "music": {"music", "music-generation", "text-to-music", "text2music", "song-generation", "lyrics-to-song", "singing", "musicgen"},
    "sfx": {"sound-effects", "sound-effect", "sfx", "foley"},
    "tools": {"source-separation", "audio-separation", "stem-separation", "music-separation", "speech-enhancement", "denoising", "noise-suppression", "dereverberation", "audio-super-resolution", "speaker-diarization"},
    "clone": {"voice-conversion", "voice-cloning", "voice-clone", "singing-voice-conversion", "rvc", "seed-vc", "openvoice"},
    "design": {"voice-design", "emotion-control"},
    "dub": {"speech-to-speech", "speech-translation", "speech-to-speech-translation", "s2st", "dubbing"},
}
_NAMES = {
    "music": re.compile(r"(musicgen|ace-?step|(^|[/_-])yue|songgen|song-gen|diffrhythm|heartmula|magenta|riffusion|mustango|jukebox|music)", re.I),
    "sfx": re.compile(r"(audioldm|sound-?effect|soundeffect|(^|[/_-])sfx|audiogen|make-an-audio|(^|[/_-])tango)", re.I),
    "tools": re.compile(r"(demucs|roformer|(^|[/_-])uvr|deepfilter|denois|separat|enhanc)", re.I),
    "clone": re.compile(r"(\brvc\b|rvc[_-]|openvoice|knn-vc|seed-vc|xtts|voice-?clon)", re.I),
    "dub": re.compile(r"(seamless|translatotron|dubbing|speech-to-speech)", re.I),
}


def _facts(row: Dict[str, Any]) -> Tuple[str, Set[str], str, str]:
    tags = {str(t).lower() for t in (row.get("tags") or [])}
    return str(row.get("id") or "").lower(), tags, str(row.get("library") or "").lower(), str(row.get("pipeline_tag") or "").lower()


def is_noise(row: Dict[str, Any]) -> bool:
    """Não é um modelo de som que o usuário procura: modelo de vídeo que também gera áudio, assistente «omni» ou codec/vocoder."""
    mid, tags, _lib, tag = _facts(row)
    return bool(tags & VIDEO_TAGS or tags & NOISE_TAGS or tag in ("text-to-video", "image-to-video", "video-to-video", "any-to-any") or NOISE_NAMES.search(mid.split("/")[-1]))


def topics_of(row: Dict[str, Any]) -> List[str]:
    """Os assuntos de um resultado (um modelo pode ter vários: o Stable Audio faz música e efeitos): music, sfx, tools, tts, clone, design, dub, asr. Vazio se é ruído."""
    if is_noise(row):
        return []
    mid, tags, _lib, tag = _facts(row)
    out: List[str] = []
    for topic in ("music", "sfx", "tools", "clone", "design", "dub"):
        if tags & _TAGS[topic] or (topic in _NAMES and _NAMES[topic].search(mid)):
            out.append(topic)
    if tag == "text-to-speech" or tags & {"text-to-speech", "tts"}:
        out.append("tts")
    if tag == "automatic-speech-recognition" or "automatic-speech-recognition" in tags:
        out.append("asr")
    return out


# ----------------------------------------------------------------------------- «roda no OpenFlow?»
def _transformers_like(row: Dict[str, Any]) -> bool:
    """O repositório é da biblioteca transformers (ou não diz a biblioteca, mas não é GGUF nem código próprio)."""
    _mid, tags, lib, _tag = _facts(row)
    if "custom_code" in tags or "gguf" in tags or lib in ("gguf", "ggml", "audio.cpp"):
        return False
    return lib == "transformers" or (lib == "" and "transformers" in tags)


def _diffusers_like(row: Dict[str, Any]) -> bool:
    """Repositório no formato do diffusers (v0.68: AudioLDM, MusicLDM e Stable Audio): não é GGUF, nem ONNX/TFLite, nem precisa de código próprio. A biblioteca pode vir como «diffusers», «stable-audio-3» ou vazia."""
    _mid, tags, lib, _tag = _facts(row)
    if tags & {"custom_code", "gguf", "onnx", "tflite"} or lib in ("gguf", "ggml", "audio.cpp", "onnx"):
        return False
    return lib in ("diffusers", "stable-audio-3", "stable-audio", "") or "diffusers" in tags


_FAMILIES = {
    "sound": ("MusicGen, AudioLDM, MusicLDM e Stable Audio", re.compile(r"musicgen|audioldm|musicldm|stable-audio", re.I)),
    "voice": ("Bark, MMS-TTS (VITS), Orpheus, CSM ou VoxCPM", re.compile(r"(^|[/_-])bark|mms-tts|(^|[/_-])vits|orpheus|(^|[/_-])csm|voxcpm", re.I)),
    "stt": ("Whisper", re.compile(r"whisper", re.I)),
}


def compat(cap: str, topic: str, row: Dict[str, Any]) -> Dict[str, str]:
    """O selo do resultado: {"level": "ok"|"no", "reason": texto}. «ok» = o OpenFlow tem suporte a esta FAMÍLIA de modelo (não quer dizer que este repositório específico foi testado); «no» = o OpenFlow ainda não roda."""
    mid, tags, lib, _tag = _facts(row)
    fam = _FAMILIES.get(cap)
    if cap == "voice" and topic in ("tts", "clone", "design") and re.search(r"voxcpm", mid, re.I) and not tags & {"gguf", "onnx", "tflite"} and lib in ("voxcpm", "", "pytorch"):
        what = {"tts": "fala em vários idiomas", "clone": "clona a voz de um áudio de referência (entrada «Voz de referência» do nó Voz)", "design": "cria a voz pela descrição («Como é a voz» do nó Voz)"}[topic]
        return {"level": "ok", "reason": f"Família VoxCPM: o OpenFlow tem suporte ({what}; usa a biblioteca voxcpm: pip install voxcpm)."}
    ok_topic = (cap, topic) in (("sound", "music"), ("sound", "sfx"), ("voice", "tts"), ("stt", "asr"))
    if not ok_topic:
        what = {"clone": "trocar ou clonar vozes", "design": "criar vozes por descrição", "dub": "dublar fala em outro idioma", "tools": "separar ou melhorar áudio"}.get(topic, "este tipo de tarefa")
        return {"level": "no", "reason": f"O OpenFlow ainda não tem um nó para {what} com este tipo de modelo (a dublagem do OpenFlow junta a transcrição, a tradução e a voz)."}
    if cap == "sound" and ok_topic:   # sons e músicas: MusicGen (transformers) ou os pipelines de áudio do diffusers
        from .canvas import soundmodels

        f = soundmodels.family(mid)
        if f == "musicgen" and _transformers_like(row):
            return {"level": "ok", "reason": "Família MusicGen: o OpenFlow tem suporte (usa a biblioteca transformers)."}
        if f in soundmodels.DIFFUSERS and _diffusers_like(row):
            return {"level": "ok", "reason": f"Família {({'audioldm': 'AudioLDM / MusicLDM', 'stable-audio-open': 'Stable Audio Open', 'stable-audio-3': 'Stable Audio 3'})[f]}: o OpenFlow tem suporte (usa a biblioteca diffusers)."}
    elif fam and fam[1].search(mid + " " + " ".join(sorted(tags))) and _transformers_like(row):
        return {"level": "ok", "reason": f"Família {fam[0]}: o OpenFlow tem suporte (usa a biblioteca transformers)."}
    want = fam[0] if fam else "outra família"
    if "custom_code" in tags:
        why = "ele precisa de código próprio do repositório"
    elif "gguf" in tags or lib in ("gguf", "ggml", "audio.cpp"):
        why = f"ele está em um formato ({lib or 'GGUF'}) que o OpenFlow não usa para {'sons' if cap == 'sound' else 'voz' if cap == 'voice' else 'transcrição'}"
    elif lib and lib != "transformers":
        why = f"ele usa a biblioteca «{lib}»"
    else:
        why = "ele não é de uma família com suporte"
    return {"level": "no", "reason": f"O OpenFlow roda {want}; este modelo não roda ({why})."}


def describe(row: Dict[str, Any], cap: str, topic: str) -> Dict[str, Any]:
    """O resultado como a interface o recebe: id, downloads, likes, assuntos, biblioteca e o selo de compatibilidade."""
    return {"id": row["id"], "downloads": int(row.get("downloads") or 0), "likes": int(row.get("likes") or 0), "cap": cap, "format": "original", "topic": topic, "topics": topics_of(row),
            "library": str(row.get("library") or ""), "compat": compat(cap, topic, row)}


def rank(rows: List[Dict[str, Any]], cap: str, topic: str, limit: int = 24) -> List[Dict[str, Any]]:
    """Fica só quem tem o assunto pedido (e não é ruído); os que o OpenFlow roda vêm primeiro, depois os mais baixados."""
    keep = [r for r in rows if topic in topics_of(r)]
    out = [describe(r, cap, topic) for r in keep]
    out.sort(key=lambda r: (r["compat"]["level"] != "ok", -r["downloads"], r["id"]))
    return out[:limit]


# ----------------------------------------------------------------------------- a pesquisa digitada
_STOP = {"musica", "musicas", "cancao", "cancoes", "efeito", "efeitos", "sonoro", "sonoros", "som", "sons", "voz", "vozes", "fala", "falas", "dublagem", "dublar", "dublado", "legenda", "legendas", "transcricao",
         "transcrever", "modelo", "modelos", "para", "de", "da", "do", "das", "dos", "e", "com", "um", "uma", "em", "no", "na", "nos", "nas", "por", "pelo", "pela", "ao", "o", "a", "os", "as", "audio", "audios",
         "sound", "sounds", "model", "models", "the", "an", "for", "and", "of", "in", "voice", "voices", "speech", "music", "effects"}
# palavras de idioma → a tag de idioma do Hub (o resultado fica só com modelos que declaram o idioma)
LANG_WORDS = {"portugues": "pt", "brasileiro": "pt", "portuguese": "pt", "ingles": "en", "english": "en", "espanhol": "es", "spanish": "es", "frances": "fr", "french": "fr", "alemao": "de", "german": "de",
              "italiano": "it", "italian": "it", "japones": "ja", "japanese": "ja", "chines": "zh", "chinese": "zh", "coreano": "ko", "korean": "ko", "russo": "ru", "russian": "ru"}


def expand_query(q: str) -> List[str]:
    """O que vai no campo de busca do Hub. As palavras que só dizem o assunto («música», «efeitos sonoros», «dublagem»…) já são o filtro de assunto e as de idioma viram a tag de idioma (`languages_in`): ambas saem da
    busca de texto (o Hub procura em inglês, pelo nome e pelas tags). Sobra o nome do modelo, do autor ou da família («musicgen», «stabilityai», «whisper large»). Sem sobras: vazio (navega os mais baixados do assunto)."""
    raw = (q or "").strip()
    if not raw:
        return []
    if "/" in raw:
        return [raw]
    words = [w for w in re.split(r"\s+", raw) if w and _norm(w) not in _STOP and _norm(w) not in LANG_WORDS]
    return [" ".join(words)] if words else []


def languages_in(q: str) -> List[str]:
    """Os idiomas pedidos na pesquisa («voz em português» → [«pt»]), como tags de idioma do Hub, sem repetir."""
    out: List[str] = []
    for w in re.split(r"\s+", (q or "").strip()):
        code = LANG_WORDS.get(_norm(w))
        if code and code not in out:
            out.append(code)
    return out
