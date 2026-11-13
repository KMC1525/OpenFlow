"""v0.12 núcleo Rust para modelos locais: cabeçalhos GGUF/safetensors, hardware, planejador e pré-carga — o Rust e o Python têm de dar o MESMO resultado."""
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openflow import native  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def gguf_bytes(layers=32, embd=4096, heads=32, heads_kv=8, ctx=8192, arch="llama", tokens=50, quant=12, extra=True) -> bytes:
    def s(x: str) -> bytes:
        b = x.encode()
        return struct.pack("<Q", len(b)) + b
    kv = []
    kv.append(s("general.architecture") + struct.pack("<I", 8) + s(arch))
    kv.append(s("general.name") + struct.pack("<I", 8) + s("Modelo de Teste"))
    for k, v in ((f"{arch}.context_length", ctx), (f"{arch}.block_count", layers), (f"{arch}.embedding_length", embd), (f"{arch}.attention.head_count", heads),
                 (f"{arch}.attention.head_count_kv", heads_kv), (f"{arch}.feed_forward_length", 14336)):
        kv.append(s(k) + struct.pack("<I", 4) + struct.pack("<I", v))
    kv.append(s("general.file_type") + struct.pack("<I", 4) + struct.pack("<I", 15))
    kv.append(s("tokenizer.ggml.rope") + struct.pack("<I", 6) + struct.pack("<f", 1.5))
    toks = b"".join(s(f"tok{i}") for i in range(tokens))
    kv.append(s("tokenizer.ggml.tokens") + struct.pack("<I", 9) + struct.pack("<I", 8) + struct.pack("<Q", tokens) + toks)
    if extra:
        kv.append(s("tokenizer.ggml.scores") + struct.pack("<I", 9) + struct.pack("<I", 6) + struct.pack("<Q", tokens) + b"\0" * 4 * tokens)
    tensors = [("blk.0.attn_q.weight", [embd, embd], quant), ("token_embd.weight", [embd, 1000], 1), ("output_norm.weight", [embd], 0)]
    t = b""
    for name, dims, ty in tensors:
        t += s(name) + struct.pack("<I", len(dims)) + b"".join(struct.pack("<Q", d) for d in dims) + struct.pack("<I", ty) + struct.pack("<Q", 0)
    return b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", len(tensors)) + struct.pack("<Q", len(kv)) + b"".join(kv) + t + b"\0" * 4096


def safetensors_bytes() -> bytes:
    head = {"__metadata__": {"format": "pt"}, "a.weight": {"dtype": "F16", "shape": [1000, 1000], "data_offsets": [0, 2000000]}, "b.bias": {"dtype": "F32", "shape": [10], "data_offsets": [2000000, 2000040]}}
    h = json.dumps(head).encode()
    return struct.pack("<Q", len(h)) + h + b"\0" * 2000040


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="flow-nm-"))
        (cls.tmp / "m.gguf").write_bytes(gguf_bytes())
        (cls.tmp / "x.gguf").write_bytes(gguf_bytes(layers=48, embd=5120, heads=40, heads_kv=40, arch="qwen2", tokens=7, quant=14, extra=False))
        (cls.tmp / "w.safetensors").write_bytes(safetensors_bytes())
        (cls.tmp / "lixo.gguf").write_bytes(b"isto nao e um gguf")
        cls.lib = None
        cargo = native.find_tool("cargo")
        if cargo and os.environ.get("OPENFLOW_NO_NATIVE_TEST") != "1":
            env = dict(os.environ, CARGO_TARGET_DIR=str(cls.tmp / "target"))
            r = subprocess.run([cargo, "build", "--release", "--manifest-path", str(ROOT / "openflow" / "native" / "Cargo.toml")], env=env, capture_output=True)
            so = cls.tmp / "target" / "release" / native._libname()
            if r.returncode == 0 and so.is_file():
                cls.lib = so

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("OPENFLOW_NATIVE_LIB", None)
        native.load(force=True)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def use(self, rust: bool):
        if rust:
            if not self.lib:
                self.skipTest("sem o Rust (cargo) para compilar o núcleo")
            os.environ["OPENFLOW_NATIVE_LIB"] = str(self.lib)
            os.environ.pop("OPENFLOW_NO_NATIVE", None)
        else:
            os.environ["OPENFLOW_NO_NATIVE"] = "1"
        native.load(force=True)
        self.assertEqual(native.available(), rust)

    def tearDown(self):
        os.environ.pop("OPENFLOW_NO_NATIVE", None)


class HeaderTests(Base):
    def check_headers(self):
        g = native.model_info(self.tmp / "m.gguf")
        self.assertEqual((g["format"], g["arch"], g["name"], g["layers"], g["ctx_train"], g["heads_kv"], g["quant"], g["vocab"]), ("gguf", "llama", "Modelo de Teste", 32, 8192, 8, "Q4_K", 50))
        self.assertEqual(g["kv_bytes_per_token"], 2 * 32 * 8 * (4096 // 32) * 2)  # K+V, f16
        self.assertEqual(g["bytes"], (self.tmp / "m.gguf").stat().st_size)
        x = native.model_info(self.tmp / "x.gguf")
        self.assertEqual((x["arch"], x["layers"], x["quant"], x["heads_kv"]), ("qwen2", 48, "Q6_K", 40))
        s = native.model_info(self.tmp / "w.safetensors")
        self.assertEqual((s["format"], s["tensors"], s["params"], s["dtype"], s["weight_bytes"]), ("safetensors", 2, 1000010.0, "F16", 2000040.0))
        self.assertEqual(native.model_info(self.tmp / "lixo.gguf")["format"], "unknown")
        self.assertIsNone(native.model_info(self.tmp / "nao_existe.gguf"))
        return g, x, s

    def test_python_reads_headers(self):
        self.use(False)
        self.check_headers()

    def test_rust_reads_headers_and_matches_python(self):
        self.use(True)
        rust = self.check_headers()
        self.use(False)
        py = self.check_headers()
        for a, b in zip(rust, py):
            for k in set(a) | set(b):
                self.assertEqual(a.get(k), b.get(k), k)


class HardwareTests(Base):
    def test_sys_info_makes_sense(self):
        for rust in (False, True):
            self.use(rust)
            i = native.sys_info()
            self.assertGreaterEqual(i["logical"], i["physical"] >= 1 and 1)
            self.assertLessEqual(i["physical"], i["logical"])
            self.assertTrue(i["ram_total"] > 0 and 0 < i["ram_avail"] <= i["ram_total"])

    @unittest.skipUnless(sys.platform.startswith("linux"), "o espelho em Python lê as extensões da CPU só do /proc/cpuinfo (Linux)")
    def test_rust_and_python_agree_on_cores_and_features(self):
        self.use(True)
        r = native.sys_info()
        self.use(False)
        p = native.sys_info()
        self.assertEqual((r["logical"], r["physical"]), (p["logical"], p["physical"]))
        self.assertEqual(set(r["features"]) & {"avx2", "fma"}, set(p["features"]) & {"avx2", "fma"})


class PlanTests(Base):
    GIB = 1 << 30

    def llm(self, **kw):
        a = dict(weights=4 * self.GIB, layers=32, kv_per_token=131072, ctx_train=8192, ctx_want=8192, explicit=False, ctx_cap=0, ram_avail=16 * self.GIB, vram_free=0, unified=False, phys=8, logical=16, mode=1)
        a.update(kw)
        return native.plan_llm(**a)

    def scenarios(self):
        G = self.GIB
        return [
            self.llm(),                                            # CPU, RAM de sobra
            self.llm(vram_free=12 * G),                            # cabe tudo na GPU
            self.llm(weights=14 * G, vram_free=8 * G),             # parte das camadas na GPU
            self.llm(weights=14 * G, vram_free=2 * G, ram_avail=8 * G),  # quase tudo na CPU
            self.llm(ram_avail=3 * G, weights=2 * G),              # pouca RAM
            self.llm(ctx_want=65536, ctx_train=131072, ram_avail=12 * G),  # contexto grande: tenta cache de 8 bits
            self.llm(mode=0), self.llm(mode=2, ram_avail=64 * G),  # leve e máximo
            self.llm(ctx_want=32768, explicit=True, ram_avail=4 * G, weights=3 * G),   # o usuário pediu mais do que cabe
            self.llm(vram_free=10 * G, unified=True, ram_avail=16 * G),  # memória unificada (Apple)
            self.llm(layers=0, kv_per_token=0, ctx_train=0, ctx_want=0),  # modelo sem metadados
        ]

    def test_cpu_plan_uses_physical_cores_and_fits_memory(self):
        self.use(False)
        p = self.llm()
        self.assertEqual((p["n_gpu_layers"], p["n_threads"], p["n_ctx"]), (0, 7, 8192))   # 8 núcleos físicos: deixa 1 livre
        self.assertEqual(p["n_threads_batch"], 15)
        self.assertTrue(p["prefetch"])
        self.assertGreater(p["cache_bytes"], 0)

    def test_gpu_plan_offloads_layers_by_free_vram(self):
        self.use(False)
        G = self.GIB
        self.assertEqual(self.llm(vram_free=12 * G)["n_gpu_layers"], -1)                                  # cabe inteiro
        part = self.llm(weights=14 * G, vram_free=8 * G)
        self.assertTrue(0 < part["n_gpu_layers"] < 32, part)                                              # só parte das camadas
        self.assertEqual(self.llm(weights=14 * G, vram_free=300 * (1 << 20))["n_gpu_layers"], 0)          # VRAM mínima: tudo na CPU
        self.assertLessEqual(self.llm(vram_free=12 * G)["n_threads"], 4)                                  # tudo na GPU: poucas threads

    def test_context_shrinks_to_what_fits_and_user_choice_is_respected(self):
        self.use(False)
        G = self.GIB
        tight = self.llm(weights=3 * G, ram_avail=4 * G, ctx_want=32768, ctx_train=32768)
        self.assertLess(tight["n_ctx"], 32768)
        self.assertEqual(tight["n_ctx"], tight["ctx_max"] if tight["n_ctx"] >= 512 else 512)
        forced = self.llm(weights=3 * G, ram_avail=4 * G, ctx_want=32768, ctx_train=32768, explicit=True)
        self.assertEqual(forced["n_ctx"], 32768)                                                           # nunca contraria o que o usuário definiu
        self.assertTrue(any("passa do que cabe" in n for n in forced["notes"]))
        self.assertTrue(self.llm(ctx_want=65536, ctx_train=131072, ram_avail=10 * G)["kv_q8"])             # falta memória: cache de atenção em 8 bits

    def test_modes(self):
        self.use(False)
        light, bal, mx = self.llm(mode=0), self.llm(mode=1), self.llm(mode=2, ram_avail=64 * self.GIB)
        self.assertEqual((light["n_batch"], bal["n_batch"], mx["n_batch"]), (128, 256, 512))
        self.assertTrue(light["kv_q8"] and not mx["kv_q8"] and mx["mlock"] and not bal["mlock"])

    def test_media_plan(self):
        self.use(False)
        G = self.GIB
        self.assertEqual(native.plan_media(2 * G, 0, 16 * G, False, 1)["strategy"], "cpu")
        self.assertEqual(native.plan_media(2 * G, 12 * G, 16 * G, False, 1)["strategy"], "gpu")
        self.assertEqual(native.plan_media(2 * G, 12 * G, 16 * G, False, 0)["strategy"], "model_offload")   # modo leve sempre descarrega
        self.assertEqual(native.plan_media(10 * G, 8 * G, 32 * G, False, 1)["strategy"], "model_offload")
        self.assertEqual(native.plan_media(31 * G, 8 * G, 64 * G, False, 1)["strategy"], "sequential_offload")
        self.assertTrue(native.plan_media(10 * G, 8 * G, 32 * G, False, 1)["tiling"])

    def test_rust_plans_match_python_exactly(self):
        self.use(True)
        rust = self.scenarios()
        media = [native.plan_media(w * self.GIB // 2, v * self.GIB // 2, 16 * self.GIB, u, m) for w in (1, 4, 20, 60) for v in (0, 4, 16, 40) for u in (False, True) for m in (0, 1, 2)]
        rnd = random.Random(3)
        fuzz_args = [dict(weights=rnd.randint(1, 60) * (1 << 29), layers=rnd.randint(0, 80), kv_per_token=rnd.choice([0, 65536, 163840, 524288]), ctx_train=rnd.choice([0, 4096, 32768, 131072]),
                          ctx_want=rnd.choice([0, 2048, 8192, 32768]), explicit=rnd.random() < 0.3, ctx_cap=rnd.choice([0, 4096, 16384]), ram_avail=rnd.randint(1, 64) * (1 << 29),
                          vram_free=rnd.choice([0, 0, 2, 6, 12, 24]) * (1 << 30), unified=rnd.random() < 0.2, phys=rnd.randint(1, 32), logical=rnd.randint(1, 64), mode=rnd.randint(0, 2)) for _ in range(200)]
        fuzz = [native.plan_llm(**a) for a in fuzz_args]
        self.use(False)
        self.assertEqual(rust, self.scenarios())
        self.assertEqual(media, [native.plan_media(w * self.GIB // 2, v * self.GIB // 2, 16 * self.GIB, u, m) for w in (1, 4, 20, 60) for v in (0, 4, 16, 40) for u in (False, True) for m in (0, 1, 2)])
        self.assertEqual(fuzz, [native.plan_llm(**a) for a in fuzz_args])


class PrefetchTests(Base):
    def test_prefetch_reads_every_byte_in_parallel(self):
        big = self.tmp / "big.bin"
        big.write_bytes(os.urandom(9 * (1 << 20) + 123))
        for rust in (False, True):
            self.use(rust)
            self.assertEqual(native.prefetch([big], threads=4), big.stat().st_size)
            self.assertEqual(native.prefetch([big, self.tmp / "m.gguf", self.tmp / "nada"]), big.stat().st_size + (self.tmp / "m.gguf").stat().st_size)
            self.assertEqual(native.prefetch([]), 0)


if __name__ == "__main__":
    unittest.main()


class IntegrationTests(Base):
    """O plano do núcleo realmente governa o carregamento do LLM local e dos modelos de mídia."""

    def test_llm_load_follows_the_plan_and_prefetches_and_sets_the_prompt_cache(self):
        from unittest import mock

        from openflow import perf
        from openflow.providers import local_llama as ll

        seen, calls = {}, []

        class Llama:
            def __init__(self, **kw):
                seen.update(kw)

            def n_ctx(self):
                return seen["n_ctx"]

            def set_cache(self, c):
                calls.append(("cache", c.capacity_bytes))

        class Ram:
            def __init__(self, capacity_bytes):
                self.capacity_bytes = capacity_bytes
        fake = type(sys)("llama_cpp")
        fake.Llama, fake.LlamaRAMCache = Llama, Ram
        G = 1 << 30
        mem = {"ram_total": 32 * G, "ram_avail": 24 * G, "vram_total": 12 * G, "vram_free": 11 * G, "unified": False, "phys": 8, "logical": 16, "features": []}
        self.use(False)
        ll._CACHE.clear()
        hw = {"tier": "high", "ram_gb": 32, "cpus": 16, "gpu": "NVIDIA RTX", "os": "Linux", "arch": "x86_64"}
        with mock.patch.dict(sys.modules, {"llama_cpp": fake}), mock.patch.object(ll, "hardware_info", return_value=hw), mock.patch.object(perf, "memory_state", return_value=mem), \
                mock.patch.object(native, "prefetch", side_effect=lambda p, *a: calls.append(("prefetch", [str(x) for x in p])) or 0):
            p = ll.LocalLlamaProvider({"model": str(self.tmp / "m.gguf"), "models_dir": str(self.tmp), "performance": {"mode": "balanced"}})
            p._llm()
        self.assertEqual((seen["n_threads"], seen["n_gpu_layers"], seen["n_ctx"]), (4, -1, 8192))       # o modelo pequeno cabe todo na GPU: poucas threads; contexto de treino 8192
        self.assertEqual((seen["n_threads_batch"], seen["n_batch"], seen["flash_attn"]), (4, 512, True))   # tudo na GPU: lote grande
        self.assertIn(("prefetch", [str(self.tmp / "m.gguf")]), calls)
        self.assertTrue(any(c[0] == "cache" and c[1] > 0 for c in calls))                                 # cache de prompt ligado
        last = native.LAST["llm"]
        self.assertEqual((last["model"], last["quant"], last["layers"]), ("m.gguf", "Q4_K", 32))
        ll._CACHE.clear()

    def test_llm_context_is_cut_to_what_fits_but_never_below_the_users_choice(self):
        from unittest import mock

        from openflow import perf
        from openflow.providers import local_llama as ll

        seen = {}

        class Llama:
            def __init__(self, **kw):
                seen.update(kw)

            def n_ctx(self):
                return seen["n_ctx"]
        fake = type(sys)("llama_cpp")
        fake.Llama = Llama
        G = 1 << 30
        tight = {"ram_total": 4 * G, "ram_avail": 1 * G, "vram_total": 0, "vram_free": 0, "unified": False, "phys": 2, "logical": 4, "features": []}
        hw = {"tier": "low", "ram_gb": 4, "cpus": 4, "gpu": "", "os": "Linux", "arch": "x86_64"}
        self.use(False)
        # modelo grande (arquivo de 3 GB só no tamanho informado) com pouca RAM livre
        big = self.tmp / "big.gguf"
        big.write_bytes(gguf_bytes(layers=32, embd=4096, heads=32, heads_kv=8, ctx=32768))
        for cfg, expect_small in (({}, True), ({"n_ctx": 32768}, False)):
            ll._CACHE.clear()
            with mock.patch.dict(sys.modules, {"llama_cpp": fake}), mock.patch.object(ll, "hardware_info", return_value=hw), mock.patch.object(perf, "memory_state", return_value=tight), \
                    mock.patch.object(native, "model_info", return_value=dict(native.model_info(big), bytes=3 * G)):
                ll.LocalLlamaProvider({"model": str(big), "models_dir": str(self.tmp), "performance": {"mode": "balanced"}, **cfg})._llm()
            self.assertEqual(seen["n_ctx"] < 32768, expect_small, (cfg, seen["n_ctx"]))
        ll._CACHE.clear()

    def test_media_plan_picks_offload_by_real_weight_size_and_free_vram(self):
        from unittest import mock

        from openflow import perf
        from openflow.canvas import localmodels as lm
        from openflow.canvas import media as M

        snap = self.tmp / "snap"
        snap.mkdir(exist_ok=True)
        (snap / "unet.safetensors").write_bytes(b"\0" * 1024)
        G = 1 << 30
        self.use(False)
        for weights_gib, vram_gib, expect in ((2, 12, "gpu"), (10, 8, "model_offload"), (30, 8, "sequential_offload")):
            mem = {"ram_total": 64 * G, "ram_avail": 48 * G, "vram_total": vram_gib * G, "vram_free": vram_gib * G, "unified": False, "phys": 8, "logical": 16, "features": []}
            with mock.patch.object(lm, "_snapshot", return_value=snap), mock.patch.object(native, "dir_weight_bytes", return_value=weights_gib * G), mock.patch.object(perf, "memory_state", return_value=mem):
                plan = M._media_plan("x/y")
            self.assertEqual(plan["strategy"], expect, (weights_gib, vram_gib))

            class Pipe:
                def __init__(self):
                    self.calls = []

                def __getattr__(self, name):
                    def f(*a):
                        self.calls.append(name)
                        return self
                    return f
            pipe = Pipe()
            M._PLAN.clear()
            M._PLAN.update(plan)
            M._slim(pipe, "cuda")
            M._PLAN.clear()
            first = {"gpu": "to", "model_offload": "enable_model_cpu_offload", "sequential_offload": "enable_sequential_cpu_offload"}[expect]
            self.assertIn(first, pipe.calls, (expect, pipe.calls))
        # sem plano (tamanho desconhecido) vale o modo de desempenho de antes
        M._PLAN.clear()
        p2 = Pipe()
        M._slim(p2, "cpu")
        self.assertEqual(p2.calls, ["to"])
        self.assertEqual(M._media_plan("modelo/que-nao-existe"), {})

    def test_local_load_prefetches_weights_and_records_the_plan(self):
        from unittest import mock

        from openflow.canvas import media as M

        got = []
        M._LOCAL_CACHE.clear()
        plan = {"strategy": "gpu", "slicing": False, "tiling": False, "prefetch": True, "weights": 5, "files": ["/x/a.safetensors"]}
        with mock.patch.object(M, "_media_plan", return_value=plan), mock.patch.object(native, "prefetch", side_effect=lambda f, *a: got.append(list(f)) or 0):
            self.assertEqual(M._local_load("image", "a/b", lambda: "pipe"), "pipe")
            self.assertEqual(M._local_load("image", "a/b", lambda: "outro"), "pipe")   # já carregado: nada a refazer
        self.assertEqual(got, [["/x/a.safetensors"]])
        self.assertEqual(native.LAST["media"]["strategy"], "gpu")
        M._LOCAL_CACHE.clear()
        M._PLAN.clear()
