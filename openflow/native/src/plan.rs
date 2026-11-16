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

// ---------------------------------------------------------------------------------------------------- v0.45 · computadores de 16 GB (DDR4 e DDR5)
/// Planejador de memória por «classe de RAM» (a de 16 GB é a mais comum e a mais apertada): quanto sobra para os modelos depois do sistema e do navegador, se o outro modelo (texto ↔ mídia) precisa sair da RAM antes,
/// o contexto que cabe, lotes e threads pela velocidade real da memória (DDR4/DDR5 e canais) e as opções de carga de mídia que poupam RAM.
/// `mem_type`: 0 desconhecido · 1 DDR3 · 2 DDR4 · 3 DDR5 · 4 LPDDR; `mem_mts`: MT/s configurados (0 = o típico do tipo); `mode`: 0 leve · 1 equilibrado · 2 máximo.
#[no_mangle]
pub extern "C" fn flow_plan_ram(
    ram_total: u64, ram_avail: u64, weights: u64, other_resident: u64, kv_per_token: u64, mem_type: u32, mem_mts: u32, channels: u32, phys: u32, mode: u32, out: *mut u8, cap: usize,
) -> i64 {
    let gib = 1024.0 * MIB;
    let total = ram_total as f64;
    let avail = if ram_avail > 0 { ram_avail as f64 } else { total * 0.7 };
    let w = weights as f64;
    let other = other_resident as f64;
    let kvpt = if kv_per_token > 0 { kv_per_token as f64 } else { 131072.0 };
    let class = if total <= 0.0 { "unknown" } else if total < 11.5 * gib { "small" } else if total < 24.5 * gib { "16" } else { "large" };
    let mut notes: Vec<String> = Vec::new();

    // 1) o que sobra para os modelos: o total menos o que o sistema, o navegador e o próprio OpenFlow usam (≈ 22% do total, entre 2,5 e 6 GiB)
    let reserve = (total * 0.22).max(2.5 * gib).min(6.0 * gib);
    let cap_total = (total - reserve).max(0.0);
    let budget_now = (avail - 0.5 * gib).max(0.0).min(cap_total);
    let budget_free = (avail + other - 0.5 * gib).max(0.0).min(cap_total);   // se o outro modelo saísse da RAM
    let evict_other = other > 0.0 && w * 1.05 > budget_now * 0.92;
    let budget = if evict_other { budget_free } else { budget_now };
    if evict_other {
        notes.push("pouca RAM livre: o outro modelo (texto ou mídia) sai da memória antes de carregar este".to_string());
    }
    let tight = w > budget * 0.60;
    if tight && w <= budget {
        notes.push("o modelo ocupa mais da metade da RAM disponível: opções que poupam memória".to_string());
    } else if w > budget {
        notes.push("o modelo é maior que a RAM disponível: vai usar disco (mmap) e ficar lento".to_string());
    }

    // 2) contexto que cabe na RAM que sobra (cache de atenção em f16 ou, se aperta, em 8 bits)
    let kv_q8 = tight || class == "small" || mode == 0;
    let room = (budget - w * 1.05 - 0.5 * gib).max(0.0);
    let per_tok = kvpt * if kv_q8 { 0.53 } else { 1.0 };
    let ctx_cap = floor_to(room / per_tok, 256.0).max(512.0);

    // 3) a velocidade da memória manda na geração por CPU: DDR4/DDR5 × MT/s × canais → GB/s; cada núcleo só «puxa» ~12 GB/s (16 no DDR5), então mais threads que isso só atrapalham
    let typical = match mem_type { 1 => 1333.0, 2 => 2666.0, 3 => 4800.0, 4 => 6400.0, _ => 2400.0 };
    let mts = if mem_mts > 0 { mem_mts as f64 } else { typical };
    let ch = (channels.max(1)).min(4) as f64;
    let theoretical = mts * 8.0 * ch / 1000.0;
    let bw = theoretical * 0.75;
    let core_bw = if mem_type == 3 || mem_type == 4 { 16.0 } else { 12.0 };
    let p = (phys.max(1)) as f64;
    let useful = (bw / core_bw).ceil().max(2.0).min(p.max(2.0));
    if ch <= 1.0 && total > 0.0 {
        notes.push("memória em canal único: a velocidade cai pela metade (dois pentes iguais dobram)".to_string());
    }

    // 4) lotes: memória rápida aguenta lotes grandes; com RAM apertada, lotes pequenos (os buffers de cálculo também ocupam RAM)
    let n_batch = if tight { 128.0 } else if bw >= 60.0 { 512.0 } else { 256.0 };
    let n_ubatch = if tight || bw < 40.0 { 128.0 } else { 256.0 };

    // 5) o resto
    let mlock = mode == 2 && w <= budget * 0.40;
    let prefetch = w <= budget * 0.65;
    let idle_s: i64 = if tight { 120 } else if class == "16" { 300 } else { 0 };   // 0 = como o usuário configurou
    let media_low_cpu_mem = class != "large";
    let media_sequential = w > budget * 0.55;
    let media_slicing = class != "large" && w > budget * 0.30;
    let media_tiling = budget < 10.0 * gib || w > budget * 0.35;

    let s = Obj::new()
        .s("class", class).i("reserve", reserve as i64).i("budget", budget as i64).b("tight", tight).b("evict_other", evict_other).b("fits", w * 1.05 <= budget)
        .i("ctx_cap", ctx_cap as i64).b("kv_q8", kv_q8).b("mlock", mlock).b("prefetch", prefetch)
        .f("bw_gbs", (bw * 10.0).round() / 10.0).i("useful_threads", useful as i64).i("n_batch", n_batch as i64).i("n_ubatch", n_ubatch as i64).i("idle_s", idle_s)
        .b("media_low_cpu_mem", media_low_cpu_mem).b("media_sequential", media_sequential).b("media_slicing", media_slicing).b("media_tiling", media_tiling)
        .strs("notes", &notes).end();
    put(out, cap, &s)
}

#[cfg(test)]
mod ram_tests {
    use super::*;

    const GIB: u64 = 1 << 30;

    fn plan(total: u64, avail: u64, w: u64, other: u64, kv: u64, ty: u32, mts: u32, ch: u32, phys: u32, mode: u32) -> String {
        let mut buf = vec![0u8; 1 << 14];
        let n = flow_plan_ram(total, avail, w, other, kv, ty, mts, ch, phys, mode, buf.as_mut_ptr(), buf.len());
        assert!(n > 0 && (n as usize) <= buf.len());
        String::from_utf8(buf[..n as usize].to_vec()).unwrap()
    }

    #[test]
    fn a_16gb_machine_reserves_for_the_system_and_evicts_the_other_model_when_it_does_not_fit() {
        // 16 GB, 10 GB livres: um modelo de 6 GB cabe sozinho
        let ok = plan(16 * GIB, 10 * GIB, 6 * GIB, 0, 1 << 18, 2, 3200, 2, 8, 1);
        assert!(ok.contains("\"class\":\"16\"") && ok.contains("\"evict_other\":false") && ok.contains("\"fits\":true"), "{ok}");
        // o outro modelo (7 GB) está na RAM e só 4 GB estão livres: carregar um de 8 GB exige tirá-lo
        let ev = plan(16 * GIB, 4 * GIB, 8 * GIB, 7 * GIB, 1 << 18, 2, 3200, 2, 8, 1);
        assert!(ev.contains("\"evict_other\":true") && ev.contains("\"tight\":true"), "{ev}");
    }

    #[test]
    fn memory_speed_sets_threads_and_batches() {
        // DDR4-3200 dual (≈ 38 GB/s úteis) × DDR5-5600 dual (≈ 67 GB/s) × DDR4 em canal único
        let d4 = plan(16 * GIB, 12 * GIB, 4 * GIB, 0, 1 << 17, 2, 3200, 2, 8, 1);
        let d5 = plan(16 * GIB, 12 * GIB, 4 * GIB, 0, 1 << 17, 3, 5600, 2, 8, 1);
        let s1 = plan(16 * GIB, 12 * GIB, 4 * GIB, 0, 1 << 17, 2, 3200, 1, 8, 1);
        assert!(d4.contains("\"n_batch\":256") && d4.contains("\"useful_threads\":4"), "{d4}");
        assert!(d5.contains("\"n_batch\":512") && d5.contains("\"useful_threads\":5") && d5.contains("\"bw_gbs\":67.2"), "{d5}");
        assert!(s1.contains("\"useful_threads\":2") && s1.contains("canal único"), "{s1}");
    }

    #[test]
    fn context_cap_follows_the_free_room_and_tightness_compresses_the_cache() {
        let tight = plan(16 * GIB, 9 * GIB, 7 * GIB, 0, 1 << 18, 2, 3200, 2, 8, 1);
        assert!(tight.contains("\"kv_q8\":true") && tight.contains("\"n_batch\":128"), "{tight}");
        let roomy = plan(16 * GIB, 13 * GIB, 2 * GIB, 0, 1 << 17, 3, 5600, 2, 8, 1);
        assert!(roomy.contains("\"kv_q8\":false") && roomy.contains("\"tight\":false"), "{roomy}");
    }

    #[test]
    fn media_options_save_ram_on_small_and_16gb_classes_only() {
        let m = plan(16 * GIB, 8 * GIB, 6 * GIB, 0, 0, 2, 3200, 2, 8, 1);
        assert!(m.contains("\"media_low_cpu_mem\":true") && m.contains("\"media_sequential\":true") && m.contains("\"media_slicing\":true") && m.contains("\"media_tiling\":true"), "{m}");
        let big = plan(64 * GIB, 50 * GIB, 6 * GIB, 0, 0, 3, 6000, 2, 16, 1);
        assert!(big.contains("\"class\":\"large\"") && big.contains("\"media_low_cpu_mem\":false") && big.contains("\"media_sequential\":false"), "{big}");
    }

    #[test]
    fn unknown_memory_never_panics() {
        let u = plan(0, 0, 0, 0, 0, 0, 0, 0, 0, 1);
        assert!(u.contains("\"class\":\"unknown\""), "{u}");
    }
}
