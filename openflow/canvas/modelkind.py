"""Que tipo de modelo é um repositório do Hugging Face (v0.67), pelo nome: transcrição, voz ou sons/músicas.

O Hugging Face local lista TODO modelo baixado em todos os seletores; escolher o Whisper (fala → texto) como «modelo de voz» entregava o texto a um modelo que espera áudio e quebrava com
«could not convert string to float: 'E aí e aí…'». Aqui o tipo sai do nome (as famílias que o OpenFlow conhece e as parecidas); nome desconhecido = tipo desconhecido (""), e o que é desconhecido
continua aparecendo e funcionando como antes.
"""
from __future__ import annotations

import re
from typing import Dict

_STT = re.compile(r"(whisper|wav2vec|hubert|wavlm|parakeet|canary|conformer|moonshine|speech2text|speecht5[-_]asr|(^|[/_-])asr([/_-]|$))", re.I)
_VOICE = re.compile(r"((^|[/_-])bark|mms-tts|(^|[/_-])vits|speecht5|orpheus|(^|[/_-])csm|kokoro|xtts|parler|vibevoice|f5-tts|chatterbox|outetts|voxcpm|(^|[/_-])tts([/_-]|$))", re.I)
_SOUND = re.compile(r"(musicgen|audioldm|musicldm|stable-audio|audiogen|ace-?step|riffusion|soundeffect|diffrhythm)", re.I)

LABEL: Dict[str, str] = {"stt": "transcrição (fala → texto)", "voice": "voz (texto → fala)", "sound": "sons e músicas"}
EXAMPLES: Dict[str, str] = {"stt": "Whisper", "voice": "Bark, MMS-TTS, Orpheus, CSM ou VoxCPM", "sound": "MusicGen"}


_SOUND_NAME = re.compile(r"^(yue|tango)([-_.0-9]|$)", re.I)   # só o NOME do modelo, não o da organização («yuewen/…» e «tango-labs/…» podem ser modelos de imagem)


def kind_of(model: str) -> str:
    """«stt», «voice», «sound» ou «» (não dá para saber pelo nome)."""
    name = str(model or "")
    if _STT.search(name):
        return "stt"
    if _SOUND.search(name) or _SOUND_NAME.search(name.rsplit("/", 1)[-1]):
        return "sound"
    if _VOICE.search(name):
        return "voice"
    return ""


def mismatch(cap: str, model: str) -> str:
    """O aviso quando `model` é de outro tipo que não `cap` (vazio se serve, ou se não dá para saber)."""
    k = kind_of(model)
    if not k or k == cap or cap not in LABEL:
        return ""
    return (f"«{model}» é um modelo de {LABEL[k]}, não de {LABEL[cap]}. No campo «Modelo» do nó (ou em Configuração → Mídia) escolha um modelo de {LABEL[cap]} ({EXAMPLES[cap]}); "
            f"o de {LABEL[k]} fica para o nó de {'transcrição' if k == 'stt' else 'voz' if k == 'voice' else 'sons e músicas'}.")
