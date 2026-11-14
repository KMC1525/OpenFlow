"""Modelos locais do Hugging Face (GGUF) rodando dentro do próprio OpenFlow.

Requer o extra opcional:  pip install "openflow[local]"  (llama-cpp-python).
Para um caminho sem dependências extras, use Ollama / LM Studio / llama.cpp server,
que são suportados como provedores OpenAI-compatíveis.
"""
from __future__ import annotations

import gc
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Tuple

from .. import native, perf, scheduler
from ..util import hardware_info
from .base import Provider, ProviderError, content_images, content_text, split_system

_CACHE: Dict[str, Any] = {}   # modelos carregados (do menos para o mais recentemente usado)
_LOCK = scheduler.PriorityLock()   # fila justa com prioridade: o chat passa na frente de tarefas em segundo plano
_PATHS: Dict[str, str] = {}   # chave do cache → arquivo do modelo (para tirá-lo do cache de páginas ao descarregar)


def _n_ctx(tier: str) -> int:
    return {"low": 2048, "medium": 4096, "high": 8192}.get(tier, 4096)


MAX_CTX = 1 << 20


def _release(paths) -> None:
    """Depois de descarregar modelos: tira os pesos do cache de páginas e devolve ao sistema a memória que o alocador ainda segura (núcleo Rust)."""
    for p in paths:
        try:
            native.evict_file(p)
        except Exception:  # noqa: BLE001
            pass
    try:
        native.release_memory()
    except Exception:  # noqa: BLE001
        pass


def _unload() -> None:
    with _LOCK:
        paths = list(_PATHS.values())
        _CACHE.clear()
        _PATHS.clear()
    gc.collect()
    _release(paths)


def _resident_limit(path: str, want_ctx: int, prof: Dict[str, Any]) -> int:
    """Quantos modelos podem ficar carregados ao mesmo tempo (núcleo Rust: pelo tamanho do modelo e a memória livre). Padrão 1 (hardware leve)."""
    try:
        info = native.model_info(path) or {}
        mem = perf.memory_state()
        plan = native.plan_agents(2, native.AGENT_KIND["embedded"], int(info.get("bytes") or 0), int(info.get("kv_bytes_per_token") or 0) * int(want_ctx), mem["ram_avail"], mem["vram_free"],
                                  mem["unified"], mem["phys"], mem["logical"], perf.MODE_NUM[prof["mode"]])
        return max(1, int(plan.get("resident_models") or 1))
    except Exception:  # noqa: BLE001
        return 1


_IDLE = perf.IdleUnloader(_unload)
_CTX_FLOOR: Dict[str, int] = {}   # janela mínima já necessária por modelo: só cresce (várias respostas de tamanhos diferentes não recarregam o modelo a cada vez)
_PLAIN: set = set()   # modelos que ficaram mudos com as opções de economia (flash attention / cache KV de 8 bits): recarregados só com o básico


def _load_llama(Llama: Any, base: Dict[str, Any], prof: Dict[str, Any]) -> Any:
    """Carrega o modelo com as opções do plano (núcleo Rust: threads, lotes, cache de atenção, mlock…); versões antigas do llama-cpp-python que não conhecem alguma opção
    recebem menos opções, até o carregamento básico."""
    extra: Dict[str, Any] = {"n_batch": prof["n_batch"], "use_mmap": True}
    if prof.get("n_ubatch"):
        extra["n_ubatch"] = prof["n_ubatch"]
    if prof.get("n_threads_batch"):
        extra["n_threads_batch"] = prof["n_threads_batch"]
    if prof.get("mlock"):
        extra["use_mlock"] = True
    if prof["flash"]:
        extra["flash_attn"] = True
    if prof["kv_q8"]:
        bits = 2 if prof.get("kv_q4") else 8   # 8 = GGML_TYPE_Q8_0 (cache de atenção pela metade), 2 = GGML_TYPE_Q4_0 (um quarto: contextos de 256K a 1M); exigem flash attention
        extra.update(type_k=bits, type_v=bits, flash_attn=True)
    older = {k: v for k, v in extra.items() if k not in ("n_ubatch", "n_threads_batch", "use_mlock")}
    basic = {k: v for k, v in extra.items() if k in ("n_batch", "use_mmap")}
    for kw in (extra, older, basic):
        try:
            return Llama(**base, **kw)
        except Exception:  # noqa: BLE001  (versão/backend sem essas opções: tenta com menos)
            continue
    return Llama(**base)


def _plan(path: str, hw: Dict[str, Any], prof: Dict[str, Any], want_ctx: int, explicit: bool) -> Dict[str, Any]:
    """Plano de carga com o núcleo Rust: lê o cabeçalho do GGUF e a memória livre agora. Qualquer falha cai no comportamento antigo (hardware_info)."""
    try:
        info = native.model_info(path) or {}
        mem = perf.memory_state()
        if mem["ram_avail"] <= 0:   # memória desconhecida (sem o núcleo Rust fora do Linux): sem plano, vale o comportamento antigo — nunca encolher a janela por falta de dado
            return {}
        gpu_known = bool(hw.get("gpu")) or mem["unified"]
        plan = native.plan_llm(int(info.get("bytes") or 0), int(info.get("layers") or 0), int(info.get("kv_bytes_per_token") or 0), int(info.get("ctx_train") or 0), int(want_ctx), explicit,
                               0, mem["ram_avail"], mem["vram_free"] if gpu_known else 0, mem["unified"], mem["phys"], mem["logical"], perf.MODE_NUM[prof["mode"]])
        plan["info"] = {k: info.get(k) for k in ("arch", "name", "quant", "layers", "ctx_train", "bytes", "params")}
        return plan
    except Exception:  # noqa: BLE001
        return {}


def context_size(configured: Any, model_name: str, tier: str) -> int:
    """Janela de contexto (tokens): o valor que o usuário definiu; senão o padrão do modelo pré-instalado (32K para os de texto); senão pelo hardware."""
    try:
        n = int(configured or 0)
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        return max(512, min(n, MAX_CTX))
    from .. import preinstalled  # import tardio: evita ciclo (preinstalled → hf → providers)

    return preinstalled.default_n_ctx(model_name) or _n_ctx(tier)


# nome do manipulador de imagens do llama-cpp-python por família de modelo (o que não casar usa o do LLaVA)
_VISION_HANDLERS = (("qwen2.5-vl", "Qwen25VLChatHandler"), ("qwen2_5_vl", "Qwen25VLChatHandler"), ("qwen3-vl", "Qwen3VLChatHandler"), ("gemma-3", "Gemma3ChatHandler"), ("gemma3", "Gemma3ChatHandler"),
                    ("minicpm", "MiniCPMv26ChatHandler"), ("moondream", "MoondreamChatHandler"), ("llava-1.6", "Llava16ChatHandler"), ("llava-v1.6", "Llava16ChatHandler"), ("llava", "Llava15ChatHandler"))


def mmproj_of(model_path: Path) -> Any:
    """O projetor de visão (mmproj) que o OpenFlow baixou junto do modelo: `<modelo>.mmproj.gguf` na mesma pasta (ver canvas/support.py)."""
    from ..canvas import support

    return support.mmproj_for(model_path.parent, model_path.name)


def vision_handler(model_path: Path) -> Any:
    """Manipulador de chat com visão para o modelo, se há mmproj e a versão instalada do llama-cpp-python sabe usar essa família. Melhor esforço: None = o modelo roda só com texto."""
    mm = mmproj_of(model_path)
    if not mm:
        return None
    try:
        from llama_cpp import llama_chat_format as fmt  # type: ignore
    except ImportError:
        return None
    low = model_path.name.lower()
    names = [h for key, h in _VISION_HANDLERS if key in low] or ["Llava15ChatHandler"]
    for name in names:
        cls = getattr(fmt, name, None)
        if cls is None:
            continue
        try:
            return cls(clip_model_path=str(mm), verbose=False)
        except Exception:  # noqa: BLE001  (projetor incompatível com este manipulador: tenta o próximo / segue só com texto)
            continue
    return None


class ContextTooLong(ValueError):
    """A conversa não cabe na janela de contexto. É um ValueError de propósito: os pipelines tratam como "resposta inválida" (caem nas regras)
    e o chat mostra a mensagem com o que fazer, em vez de derrubar a geração inteira."""


def fit_messages(msgs: List[dict], count: Callable[[str], int], ctx: int, max_tokens: int) -> Tuple[List[dict], int]:
    """Cabe a conversa na janela de contexto: mantém a mensagem de sistema e a última, e descarta as mais antigas até sobrar espaço para a resposta.
    Devolve (mensagens, max_tokens ajustado). Sem isto, uma conversa longa estoura o contexto (ValueError do llama.cpp) e o avatar para de responder."""
    max_tokens = max(64, min(int(max_tokens), ctx // 2))
    budget = ctx - max_tokens - 16
    def size(m: dict) -> int:   # mensagem com imagens: só o texto é contado (o base64 não vira token); cada imagem vale ~600 tokens do contexto
        c = m.get("content")
        if isinstance(c, list):
            txt = " ".join(str(x.get("text") or "") for x in c if isinstance(x, dict) and x.get("type") == "text")
            return count(txt) + 8 + 600 * sum(1 for x in c if isinstance(x, dict) and x.get("type") == "image_url")
        return count(str(c or "")) + 8

    sizes = [size(m) for m in msgs]
    system = [i for i, m in enumerate(msgs) if m.get("role") == "system"][:1]
    keep = set(system)
    used = sum(sizes[i] for i in keep)
    for i in range(len(msgs) - 1, -1, -1):  # das mais novas para as mais antigas
        if i in keep:
            continue
        if used + sizes[i] > budget and i != len(msgs) - 1:
            break  # a última (a pergunta atual) entra sempre
        keep.add(i)
        used += sizes[i]
    out = [m for i, m in enumerate(msgs) if i in keep]
    while len(out) > 1 and out[1 if out[0].get("role") == "system" else 0].get("role") == "assistant":
        out.pop(1 if out[0].get("role") == "system" else 0)  # modelos com template estrito exigem começar pelo usuário
    return out, max_tokens


class LocalLlamaProvider(Provider):
    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self.label = cfg.get("label", "Hugging Face local")
        self.models_dir = Path(cfg.get("models_dir", "."))
        self.n_ctx_cfg = cfg.get("n_ctx")
        self.perf_cfg = cfg.get("performance") or {}

    def _model_path(self) -> Path:
        name = self.model
        if not name:
            raise ProviderError("Baixe e selecione um modelo GGUF em Configuração → Modelos locais.")
        path = Path(name)
        if not path.is_absolute():
            path = self.models_dir / name
        if not path.exists():
            raise ProviderError(f"Modelo não encontrado: {path}")
        return path

    def _llm(self):
        need_reply = int(getattr(self, "_need_reply", 0) or 0)   # tamanho da resposta pedida (definido por _chat/_stream antes de chamar)
        try:
            from llama_cpp import Llama  # type: ignore
        except ImportError:
            raise ProviderError(
                'Para usar modelos locais embutidos instale o extra:  pip install "openflow[local]"  '
                "(ou use Ollama / LM Studio como provedor)."
            ) from None
        path = str(self._model_path())
        hw = hardware_info()
        prof = perf.profile(self.perf_cfg, hw)
        if path in _PLAIN:
            prof = dict(prof, flash=False, kv_q8=False, kv_q4=False)
        want = perf.cap_context(context_size(self.n_ctx_cfg, Path(path).name, hw["tier"]), prof, explicit=bool(self.n_ctx_cfg))
        if not self.n_ctx_cfg and need_reply > 0:   # janela automática: tem de caber a resposta pedida (2K no Chat, mais nos agentes) com espaço para a conversa; antes a resposta era encolhida para a metade da janela
            _CTX_FLOOR[path] = max(_CTX_FLOOR.get(path, 0), min(MAX_CTX, 2 * int(need_reply) + 1024))
            want = max(want, _CTX_FLOOR[path])
        key = f"{path}|{want}|{prof['mode']}|{int(prof['flash'])}{int(prof['kv_q8'])}"  # a chave não usa a memória livre do momento (senão recarregaria o modelo a cada variação); mudar a janela de contexto ou o modo recarrega
        plan = _plan(path, hw, prof, want, bool(self.n_ctx_cfg)) if key not in _CACHE else {}
        ctx = int(plan.get("n_ctx") or want)
        if plan:   # o plano manda nos parâmetros de carga; o modo "mudo" (flash/KV 8 bits) continua sendo respeitado
            prof = dict(prof, n_batch=plan["n_batch"], n_ubatch=plan["n_ubatch"], n_threads_batch=plan["n_threads_batch"], mlock=plan["mlock"],
                        flash=plan["flash"] and path not in _PLAIN, kv_q8=plan["kv_q8"] and path not in _PLAIN, kv_q4=bool(plan.get("kv_q4")) and path not in _PLAIN)
        with _LOCK:
            llm = _CACHE.get(key)
            if llm is not None:
                _CACHE[key] = _CACHE.pop(key)   # mais recente por último
            if llm is None:
                dev = perf.device()   # Configurações → Desempenho → Rodar em: automático, só CPU ou GPU
                use_gpu = dev != "cpu" and (dev == "gpu" or bool(hw.get("gpu")) or (hw["os"] == "Darwin" and "arm" in hw["arch"].lower()))
                ngl = int(plan["n_gpu_layers"]) if plan and use_gpu else (-1 if use_gpu else 0)
                threads = int(plan["n_threads"]) if plan else max(1, hw["cpus"] - 1)
                base = dict(model_path=path, n_ctx=ctx, n_threads=threads, n_gpu_layers=ngl, verbose=False)
                handler = vision_handler(Path(path))   # modelo com mmproj ao lado: aceita imagens
                if handler is not None:
                    base["chat_handler"] = handler
                limit = _resident_limit(path, ctx, prof) if plan else 1   # vários agentes com modelos diferentes: mantém mais de um na RAM só se couber; senão, um só
                dropped = []
                while len(_CACHE) >= limit:
                    old_key = next(iter(_CACHE))   # o menos usado recentemente
                    _CACHE.pop(old_key, None)
                    dropped.append(_PATHS.pop(old_key, ""))
                if dropped:
                    gc.collect()
                    _release([d for d in dropped if d])
                if plan.get("prefetch"):
                    native.prefetch([path])   # leitura paralela para o cache do sistema: o mmap acha tudo em RAM (carga bem mais rápida em disco frio)
                llm = _load_llama(Llama, base, prof)
                if plan.get("cache_bytes"):
                    try:   # cache de prompt: o prefixo repetido da conversa (sistema + histórico) não é recalculado a cada resposta
                        from llama_cpp import LlamaRAMCache  # type: ignore

                        llm.set_cache(LlamaRAMCache(capacity_bytes=int(plan["cache_bytes"])))
                    except Exception:  # noqa: BLE001
                        pass
                _CACHE[key] = llm
                _PATHS[key] = path
                native.record("llm", model=Path(path).name, n_ctx=ctx, n_gpu_layers=ngl, n_threads=threads, kv_q8=bool(prof["kv_q8"]), kv_q4=bool(prof.get("kv_q4")), flash=bool(prof["flash"]), notes=plan.get("notes", []),
                              quant=(plan.get("info") or {}).get("quant"), layers=(plan.get("info") or {}).get("layers"))
        _IDLE.touch(prof["idle_s"])
        return llm, path

    def _sees(self) -> bool:
        """O modelo escolhido tem mmproj ao lado (a visão só funciona se a biblioteca também sabe a família dele; senão as imagens são ignoradas, como sempre)."""
        try:
            return mmproj_of(self._model_path()) is not None
        except ProviderError:
            return False

    def _messages(self, messages: List[dict], system: str) -> List[dict]:
        sys_text, rest = split_system(messages, system)
        out = [{"role": "system", "content": sys_text}] if sys_text else []
        vision = self.vision or self._sees()
        for m in rest:
            imgs = content_images(m.get("content")) if vision else []
            if imgs:   # texto + imagens no formato OpenAI (data URL), que o manipulador de visão entende
                parts = [{"type": "text", "text": content_text(m.get("content"))}]
                parts += [{"type": "image_url", "image_url": {"url": f"data:{i.get('media_type', 'image/png')};base64,{i.get('data', '')}"}} for i in imgs]
                out.append({"role": m["role"], "content": parts})
            else:
                out.append({"role": m["role"], "content": content_text(m.get("content"))})
        return out

    def _prepare(self, llm: Any, messages: List[dict], system: str, max_tokens: int) -> Tuple[List[dict], int]:
        ctx = int(llm.n_ctx()) if callable(getattr(llm, "n_ctx", None)) else 2048
        count = lambda t: len(llm.tokenize(t.encode("utf-8"), add_bos=False)) if hasattr(llm, "tokenize") else len(t) // 3 + 1  # noqa: E731
        return fit_messages(self._messages(messages, system), count, ctx, max_tokens)   # (o texto de uma mensagem com imagens conta como a lista: o prompt da imagem em si pesa pouco no contexto)

    @staticmethod
    def _wrap(exc: Exception) -> Exception:
        msg = str(exc)
        if "context" in msg.lower() or "exceed" in msg.lower():
            return ContextTooLong("A conversa não cabe na janela de contexto do modelo local. Aumente a janela em Configuração → Provedores → "
                                 "Hugging Face GGUF → Janela de contexto, ou reinicie a conversa.")
        return ProviderError(f"O modelo local falhou: {msg[:300]}")

    def _chat(self, messages, system, temperature, max_tokens, json_mode) -> str:
        self._need_reply = max_tokens
        llm, path = self._llm()
        msgs, max_tokens = self._prepare(llm, messages, system, max_tokens)
        with _LOCK:
            try:
                try:
                    res = llm.create_chat_completion(messages=msgs, temperature=temperature, max_tokens=max_tokens,
                                                     **({"response_format": {"type": "json_object"}} if json_mode else {}))
                except (TypeError, KeyError):  # versão do llama-cpp-python sem response_format: segue sem a gramática JSON
                    if not json_mode:
                        raise
                    res = llm.create_chat_completion(messages=msgs, temperature=temperature, max_tokens=max_tokens)
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001  (ValueError de contexto, RuntimeError do llama.cpp…)
                raise self._wrap(exc) from None
        out = (res["choices"][0]["message"].get("content") or "").strip()
        fr = str(res["choices"][0].get("finish_reason") or "")
        self.last_stop = "length" if fr == "length" else ("stop" if fr else "")
        if not out and self._go_plain(path):  # modelo mudo com as opções de economia: recarrega só com o básico e tenta de novo
            return self._chat(messages, system, temperature, max_tokens, json_mode)
        return out

    @staticmethod
    def _go_plain(path: str) -> bool:
        if path in _PLAIN:
            return False
        _PLAIN.add(path)
        with _LOCK:
            _CACHE.clear()
            _PATHS.clear()
        gc.collect()
        return True

    def _stream(self, messages, system, temperature, max_tokens) -> Iterator[str]:
        self._need_reply = max_tokens
        llm, path = self._llm()
        msgs, max_tokens = self._prepare(llm, messages, system, max_tokens)
        got = False
        with _LOCK:
            try:
                for chunk in llm.create_chat_completion(messages=msgs, temperature=temperature, max_tokens=max_tokens, stream=True):
                    fr = chunk["choices"][0].get("finish_reason")
                    if fr:
                        self.last_stop = "length" if fr == "length" else "stop"
                    delta = chunk["choices"][0].get("delta", {}).get("content")
                    if delta:
                        got = True
                        yield delta
            except GeneratorExit:
                raise
            except ProviderError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise self._wrap(exc) from None
        if not got and self._go_plain(path):  # mudo: tenta de novo com o carregamento básico
            yield from self._stream(messages, system, temperature, max_tokens)

    def list_models(self) -> List[str]:
        """Os GGUF de texto baixados (um modelo dividido em partes aparece uma vez; arquivos de visão/mmproj ficam de fora)."""
        from .. import hf

        return sorted(m["name"] for m in hf.local_models(self.models_dir, "text"))
