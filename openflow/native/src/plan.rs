//! Planejador de carga/inferência: transforma o tamanho real do modelo + o hardware livre agora em parâmetros concretos.
//!
//! * LLM (GGUF): camadas na GPU, janela de contexto que cabe, threads (núcleos físicos), lote, cache de atenção em 8 bits, `mlock`, pré-carga e cache de prompt.
//! * Mídia (diffusers/transformers): na GPU inteiro, com descarga do modelo, com descarga sequencial ou na CPU; fatias de atenção/VAE.
//! O mesmo cálculo existe em Python (`openflow/native/__init__.py`) com as mesmas contas — os testes conferem que os dois dão o mesmo resultado.

use crate::util::{put, Obj};

const MIB: f64 = 1048576.0;

fn floor_to(v: f64, q: f64) -> f64 {
    (v / q).floor() * q
}

#[no_mangle]
pub extern "C" fn flow_plan_llm(
    weights: u64, layers: i64, kv_per_token: i64, ctx_train: i64, ctx_want: i64, explicit: u32, ctx_cap: i64, ram_avail: u64, vram_free: u64, unified: u32, phys: u32, logical: u32,
    mode: u32, out: *mut u8, cap: usize,
) -> i64 {
    let w = weights as f64;
    let n_layers = layers.max(1) as f64;
    let layer_bytes = w / n_layers;
    let kvpt = if kv_per_token > 0 { kv_per_token as f64 } else { 131072.0 };
    let ram = ram_avail as f64;
    let vram = vram_free as f64;
    let has_gpu = vram > 0.0;
    let want = if ctx_want > 0 { ctx_want as f64 } else { 4096.0 };
    let probe = want.min(8192.0);
    let mut notes: Vec<String> = Vec::new();

    // 1) camadas na GPU (o cache de atenção das camadas na GPU também mora lá)
    let usable_vram = vram * 0.90 - 600.0 * MIB;
    let mut ngl: f64 = 0.0;
    if has_gpu && usable_vram > 0.0 {
        let per_layer = layer_bytes + kvpt * probe / n_layers * if mode == 0 { 0.53 } else { 1.0 };
        ngl = (usable_vram / per_layer).floor().min(n_layers);
        if ngl < 1.0 {
            ngl = 0.0;
        }
    }
    let all_gpu = ngl >= n_layers;
    let frac_gpu = if all_gpu { 1.0 } else { ngl / n_layers };

    // 2) janela de contexto que cabe na memória (RAM e VRAM juntas), com o cache em f16 ou, se faltar, em 8 bits
    let ram_budget = if unified != 0 { (ram * 0.80 - ngl * layer_bytes).max(0.0) } else { ram * 0.80 };
    let cpu_weights = if all_gpu { w * 0.15 } else { (n_layers - ngl) * layer_bytes + w * 0.05 };
    let ctx_for = |scale: f64| -> f64 {
        let gpu_left = usable_vram - ngl * layer_bytes;
        let cpu_left = ram_budget - cpu_weights;
        let tg = if frac_gpu > 0.0 { gpu_left / (kvpt * scale * frac_gpu) } else { f64::INFINITY };
        let tc = if frac_gpu < 1.0 { cpu_left / (kvpt * scale * (1.0 - frac_gpu)) } else { f64::INFINITY };
        let mut m = tg.min(tc);
        if ctx_train > 0 {
            m = m.min(ctx_train as f64);
        }
        if ctx_cap > 0 {
            m = m.min(ctx_cap as f64);
        }
        if m.is_finite() { floor_to(m.max(0.0), 256.0) } else { want }
    };
    let mut kv_q8 = mode == 0;
    let mut ctx_max = ctx_for(if kv_q8 { 0.53 } else { 1.0 });
    if !kv_q8 && ctx_max < want {
        let q = ctx_for(0.53);
        if q > ctx_max {
            kv_q8 = true;
            ctx_max = q;
            notes.push("cache de atenção em 8 bits para caber mais contexto".to_string());
        }
    }
    // contexto longo (64K ou mais — 256K, 512K, 1M…): se nem o cache de 8 bits cabe, usa o de 4 bits (mais compacto, com uma perda pequena de qualidade)
    let mut kv_q4 = false;
    if kv_q8 && ctx_max < want && want >= 65536.0 {
        let q = ctx_for(0.28);
        if q > ctx_max {
            kv_q4 = true;
            ctx_max = q;
            notes.push("cache de atenção em 4 bits para caber o contexto longo".to_string());
        }
    }
    let mut ctx = if explicit != 0 { want } else { want.min(ctx_max) };
    if ctx < 512.0 {
        ctx = 512.0;
        notes.push("pouca memória livre: contexto mínimo".to_string());
    }
    if explicit != 0 && want > ctx_max && ctx_max > 0.0 {
        notes.push(format!("o contexto pedido ({}) passa do que cabe na memória livre ({})", want as i64, ctx_max as i64));
    }
    if explicit != 0 && ctx_train > 0 && want > ctx_train as f64 {
        notes.push(format!("o contexto pedido ({}) passa do que o modelo foi treinado ({}): a qualidade pode cair", want as i64, ctx_train));
    }

    // 3) threads, lotes e memória
    let p = (phys.max(1)) as f64;
    let l = (logical.max(phys.max(1))) as f64;
    let threads = if all_gpu { p.min(4.0) } else if p >= 8.0 { p - 1.0 } else { p };
    let threads_batch = if all_gpu { threads.max(4.0).min(p) } else if l > p && l >= 8.0 { l - 1.0 } else { threads };
    // lotes maiores aceleram a ingestão do prompt em GPU (NVIDIA 20/30/40/50) quando há folga de VRAM/RAM
    let gpu_headroom = usable_vram - ngl * layer_bytes - kvpt * ctx * (if kv_q4 { 0.28 } else if kv_q8 { 0.53 } else { 1.0 }) * frac_gpu;
    let roomy_gpu = has_gpu && frac_gpu >= 0.5 && gpu_headroom > 1024.0 * MIB;
    let n_batch = if mode == 0 {
        if roomy_gpu { 256.0 } else { 128.0 }
    } else if mode == 2 && roomy_gpu {
        1024.0
    } else if all_gpu || mode == 2 || roomy_gpu {
        512.0
    } else {
        256.0
    };
    let n_ubatch = if mode == 0 { 256.0f64.min(n_batch) } else if roomy_gpu { 512.0 } else { 512.0f64.min(n_batch) };
    // atenção flash ajuda em GPUs modernas (Turing/Ampere/Ada/Blackwell) e também com KV quantizado
    let flash = has_gpu || kv_q8 || kv_q4 || mode != 0;
    let mlock = mode == 2 && !has_gpu && ram > w * 2.0 + kvpt * ctx;
    let prefetch = w < ram * 0.70;
    let ram_after = ram - cpu_weights - kvpt * ctx * (1.0 - frac_gpu);
    let cache_bytes = if mode == 0 {
        if ram_after > 1024.0 * MIB { 256.0 * MIB } else { 128.0 * MIB }
    } else if ram_after > 8192.0 * MIB {
        (ram_after * 0.12).min(2048.0 * MIB)
    } else if ram_after > 4096.0 * MIB {
        (ram_after * 0.10).min(1024.0 * MIB)
    } else if ram_after > 1536.0 * MIB {
        128.0 * MIB
    } else {
        0.0
    };

    let s = Obj::new()
        .i("n_ctx", ctx as i64).i("ctx_max", ctx_max as i64).i("n_gpu_layers", if all_gpu { -1 } else { ngl as i64 }).i("gpu_layers_fit", ngl as i64)
        .i("n_threads", threads as i64).i("n_threads_batch", threads_batch as i64).i("n_batch", n_batch as i64).i("n_ubatch", n_ubatch as i64)
        .b("kv_q8", kv_q8).b("kv_q4", kv_q4).b("flash", flash).b("mlock", mlock).b("prefetch", prefetch).i("cache_bytes", cache_bytes as i64)
        .strs("notes", &notes).end();
    put(out, cap, &s)
}

#[no_mangle]
pub extern "C" fn flow_plan_media(weights: u64, vram_free: u64, ram_avail: u64, unified: u32, mode: u32, out: *mut u8, cap: usize) -> i64 {
    let w = weights as f64;
    let vram = vram_free as f64;
    let ram = ram_avail as f64;
    let gib = 1024.0 * MIB;
    let (strategy, slicing, tiling);
    if vram <= 0.0 {
        strategy = "cpu";
        slicing = w > ram * 0.40 || mode == 0;
        tiling = mode == 0;
    } else {
        let need = w * 1.25 + 1.5 * gib;
        let usable = vram * 0.92;
        strategy = if mode != 0 && need <= usable { "gpu" } else if w * 0.55 + 1.0 * gib <= usable { "model_offload" } else { "sequential_offload" };
        slicing = mode == 0 || need > usable * 0.75;
        tiling = mode == 0 || need > usable * 0.60;
    }
    let host_ok = if unified != 0 { w < ram * 0.5 } else { w < ram * 0.70 };
    let s = Obj::new().s("strategy", strategy).b("slicing", slicing).b("tiling", tiling).b("prefetch", host_ok).end();
    put(out, cap, &s)
}
