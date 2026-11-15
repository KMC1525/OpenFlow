//! CPU AMD/Intel (e ARM) para modelos locais (v0.28): identifica o processador, separa núcleos de desempenho (P) dos de eficiência (E) em CPUs híbridas, mede a largura de banda da memória
//! (o que limita a velocidade de geração de texto na CPU) e planeja threads, lotes e a velocidade esperada para um modelo.
//!
//! A geração de cada token lê **todos** os pesos do modelo da RAM: em CPU, tokens/s ≈ largura de banda ÷ tamanho do modelo. Por isso mais threads que o necessário para saturar a memória só atrapalham
//! (e, em CPUs híbridas, as threads que caem nos núcleos E seguram as dos P). O mesmo cálculo existe em Python (`native/__init__.py`); os testes conferem que os dois dão o mesmo resultado.

use crate::util::{put, Obj};
use std::time::Instant;

fn read(p: &str) -> Option<String> {
    std::fs::read_to_string(p).ok()
}

/// Lista de CPUs do Linux («0-7,16-19») → índices.
pub fn parse_cpu_list(s: &str) -> Vec<usize> {
    let mut out = Vec::new();
    for part in s.trim().split(',') {
        let part = part.trim();
        if part.is_empty() {
            continue;
        }
        if let Some((a, b)) = part.split_once('-') {
            if let (Ok(a), Ok(b)) = (a.trim().parse::<usize>(), b.trim().parse::<usize>()) {
                if b >= a && b - a < 4096 {
                    out.extend(a..=b);
                }
            }
        } else if let Ok(v) = part.parse::<usize>() {
            out.push(v);
        }
    }
    out
}

pub struct Topology {
    pub hybrid: bool,
    pub p_cpus: Vec<usize>, // CPUs lógicas dos núcleos de desempenho
    pub e_cpus: Vec<usize>,
    pub p_phys: usize,
    pub e_phys: usize,
}

fn phys_of(cpus: &[usize]) -> usize {
    let mut seen: Vec<String> = Vec::new();
    for i in cpus {
        if let Some(s) = read(&format!("/sys/devices/system/cpu/cpu{}/topology/thread_siblings_list", i)) {
            let s = s.trim().to_string();
            if !s.is_empty() && !seen.contains(&s) {
                seen.push(s);
            }
        }
    }
    if seen.is_empty() { cpus.len().max(1) } else { seen.len() }
}

pub fn topology() -> Topology {
    let logical = crate::sys::logical_cores();
    #[cfg(any(target_os = "linux", target_os = "android"))]
    {
        // Intel híbrido (Alder Lake e mais novos): o kernel separa os dois tipos de núcleo
        let core = read("/sys/devices/cpu_core/cpus").map(|s| parse_cpu_list(&s)).unwrap_or_default();
        let atom = read("/sys/devices/cpu_atom/cpus").map(|s| parse_cpu_list(&s)).unwrap_or_default();
        if !core.is_empty() && !atom.is_empty() {
            let (pp, ep) = (phys_of(&core), phys_of(&atom));
            return Topology { hybrid: true, p_cpus: core, e_cpus: atom, p_phys: pp, e_phys: ep };
        }
        // AMD (Zen 4c/5c), ARM big.LITTLE: grupos de frequência máxima bem diferentes
        let mut freqs: Vec<(usize, u64)> = Vec::new();
        for i in 0..logical {
            if let Some(f) = read(&format!("/sys/devices/system/cpu/cpu{}/cpufreq/cpuinfo_max_freq", i)).and_then(|s| s.trim().parse::<u64>().ok()) {
                freqs.push((i, f));
            }
        }
        if freqs.len() == logical && logical >= 4 {
            let hi = freqs.iter().map(|x| x.1).max().unwrap_or(0);
            let lo = freqs.iter().map(|x| x.1).min().unwrap_or(0);
            if lo > 0 && hi as f64 >= lo as f64 * 1.25 {
                let cut = (hi as f64 * 0.80) as u64;
                let p: Vec<usize> = freqs.iter().filter(|x| x.1 >= cut).map(|x| x.0).collect();
                let e: Vec<usize> = freqs.iter().filter(|x| x.1 < cut).map(|x| x.0).collect();
                if !p.is_empty() && !e.is_empty() {
                    let (pp, ep) = (phys_of(&p), phys_of(&e));
                    return Topology { hybrid: true, p_cpus: p, e_cpus: e, p_phys: pp, e_phys: ep };
                }
            }
        }
    }
    let all: Vec<usize> = (0..logical).collect();
    let phys = crate::sys::physical_cores();
    Topology { hybrid: false, p_cpus: all, e_cpus: Vec::new(), p_phys: phys, e_phys: 0 }
}

#[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
mod x86 {
    #[cfg(target_arch = "x86")]
    use std::arch::x86::{__cpuid, __cpuid_count};
    #[cfg(target_arch = "x86_64")]
    use std::arch::x86_64::{__cpuid, __cpuid_count};

    pub fn vendor() -> String {
        let r = unsafe { __cpuid(0) };
        let mut b = Vec::new();
        for v in [r.ebx, r.edx, r.ecx] {
            b.extend_from_slice(&v.to_le_bytes());
        }
        String::from_utf8_lossy(&b).to_string()
    }
    pub fn brand() -> String {
        let max = unsafe { __cpuid(0x8000_0000) }.eax;
        if max < 0x8000_0004 {
            return String::new();
        }
        let mut b = Vec::new();
        for leaf in 0x8000_0002u32..=0x8000_0004 {
            let r = unsafe { __cpuid(leaf) };
            for v in [r.eax, r.ebx, r.ecx, r.edx] {
                b.extend_from_slice(&v.to_le_bytes());
            }
        }
        String::from_utf8_lossy(&b).trim_matches(char::from(0)).trim().to_string()
    }
    /// bit «híbrido» do leaf 7 (Intel Alder Lake e mais novos)
    pub fn hybrid_bit() -> bool {
        if unsafe { __cpuid(0) }.eax < 7 {
            return false;
        }
        unsafe { __cpuid_count(7, 0) }.edx & (1 << 15) != 0
    }
    /// (L2 por núcleo em KiB, L3 total em KiB) pelo cpuid (leaf 4 na Intel, 0x8000001D na AMD)
    pub fn caches(amd: bool) -> (u64, u64) {
        let leaf = if amd { 0x8000_001Du32 } else { 4 };
        let (mut l2, mut l3) = (0u64, 0u64);
        for sub in 0..16 {
            let r = unsafe { __cpuid_count(leaf, sub) };
            let kind = r.eax & 0x1f;
            if kind == 0 {
                break;
            }
            let level = (r.eax >> 5) & 0x7;
            let ways = ((r.ebx >> 22) & 0x3ff) as u64 + 1;
            let parts = ((r.ebx >> 12) & 0x3ff) as u64 + 1;
            let line = (r.ebx & 0xfff) as u64 + 1;
            let sets = r.ecx as u64 + 1;
            let kb = ways * parts * line * sets / 1024;
            if kind != 2 && level == 2 {
                l2 = kb;
            }
            if kind != 2 && level == 3 {
                l3 = kb;
            }
        }
        (l2, l3)
    }
    pub fn extra_features() -> Vec<&'static str> {
        let mut f = Vec::new();
        if unsafe { __cpuid(0) }.eax >= 7 {
            let r7 = unsafe { __cpuid_count(7, 0) };
            let r71 = if r7.eax >= 1 { unsafe { __cpuid_count(7, 1) } } else { r7 };
            if r7.ecx & (1 << 11) != 0 { f.push("avx512_vnni"); }
            if r71.eax & (1 << 4) != 0 { f.push("avx_vnni"); }
            if r7.edx & (1 << 24) != 0 { f.push("amx_tile"); }
            if r7.ebx & (1 << 8) != 0 { f.push("bmi2"); }
            if r7.ecx & (1 << 1) != 0 { f.push("avx512_vbmi"); }
            if r71.eax & (1 << 5) != 0 { f.push("avx512_bf16"); }
        }
        f
    }
}

/// Código do melhor conjunto SIMD: 0 nenhum/SSE, 1 AVX, 2 AVX2(+FMA), 3 AVX-512, 4 NEON.
pub fn simd_level(features: &[String]) -> u32 {
    let has = |n: &str| features.iter().any(|f| f == n);
    if has("avx512f") && has("avx512bw") && has("avx512vl") {
        3
    } else if has("avx2") && has("fma") {
        2
    } else if has("avx") {
        1
    } else if has("neon") {
        4
    } else {
        0
    }
}

#[no_mangle]
pub extern "C" fn flow_cpu_info(out: *mut u8, cap: usize) -> i64 {
    let topo = topology();
    let mut feats = crate::sys::features();
    #[allow(unused_mut)]
    let (mut vendor, mut brand, mut l2, mut l3) = (String::from("other"), String::new(), 0u64, 0u64);
    #[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
    {
        let v = x86::vendor();
        let amd = v == "AuthenticAMD";
        vendor = if amd { "amd".into() } else if v == "GenuineIntel" { "intel".into() } else { "other".into() };
        brand = x86::brand();
        let c = x86::caches(amd);
        l2 = c.0;
        l3 = c.1;
        for e in x86::extra_features() {
            feats.push(e.to_string());
        }
        if x86::hybrid_bit() && !topo.hybrid {
            // o processador diz que é híbrido, mas o sistema não separa os núcleos (Windows/macOS): sem a lista, não dá para fixar threads
        }
    }
    #[cfg(not(any(target_arch = "x86", target_arch = "x86_64")))]
    {
        if let Some(s) = read("/proc/cpuinfo") {
            if let Some(l) = s.lines().find(|l| l.starts_with("model name") || l.starts_with("Model")) {
                brand = l.split(':').nth(1).unwrap_or("").trim().to_string();
            }
        }
    }
    let ids = |v: &Vec<usize>| format!("[{}]", v.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(","));
    let s = Obj::new()
        .s("vendor", &vendor)
        .s("brand", &brand)
        .b("hybrid", topo.hybrid)
        .i("p_physical", topo.p_phys as i64)
        .i("e_physical", topo.e_phys as i64)
        .i("p_logical", topo.p_cpus.len() as i64)
        .i("e_logical", topo.e_cpus.len() as i64)
        .raw("p_cpus", &ids(&topo.p_cpus))
        .raw("e_cpus", &ids(&topo.e_cpus))
        .i("l2_kb", l2 as i64)
        .i("l3_kb", l3 as i64)
        .i("simd", simd_level(&feats) as i64)
        .strs("features", &feats)
        .end();
    put(out, cap, &s)
}

/// Lê `bytes` de um buffer uma vez, somando (a soma impede o compilador de descartar a leitura; é vetorizada).
fn stream(buf: &[u64]) -> u64 {
    let mut a = [0u64; 8];
    for c in buf.chunks_exact(8) {
        for k in 0..8 {
            a[k] = a[k].wrapping_add(c[k]);
        }
    }
    a.iter().fold(0u64, |x, y| x.wrapping_add(*y))
}

/// Largura de banda de leitura da memória em GB/s com `threads` threads, sobre `mb` MiB (maior que o cache). Melhor de 3 passadas (cada thread lê a sua fatia).
fn bandwidth(mb: usize, threads: usize) -> f64 {
    let n = (mb << 20) / 8;
    let mut buf: Vec<u64> = vec![1; n];
    for (i, v) in buf.iter_mut().enumerate().step_by(512) {
        *v = i as u64; // toca todas as páginas antes de medir
    }
    let t = threads.max(1);
    let per = (n / t) / 8 * 8;
    let mut best: f64 = 0.0;
    let mut sink = 0u64;
    for _ in 0..3 {
        let t0 = Instant::now();
        let total = std::thread::scope(|sc| {
            let hs: Vec<_> = (0..t).map(|k| { let part = &buf[k * per..(k + 1) * per]; sc.spawn(move || stream(part)) }).collect();
            hs.into_iter().fold(0u64, |x, h| x.wrapping_add(h.join().unwrap_or(0)))
        });
        sink = sink.wrapping_add(total);
        let dt = t0.elapsed().as_secs_f64();
        if dt > 0.0 {
            best = best.max((per * t * 8) as f64 / dt / 1e9);
        }
    }
    if sink == 0xdead_beef_dead_beef {
        best += 0.0; // nunca acontece; mantém `sink` vivo
    }
    best
}

/// Mede a memória: {bw1, bwn, threads, mb}. Leva uns 0,3 a 1 s. `threads` = quantas threads usar na medida em múltiplas threads (0 = núcleos físicos).
#[no_mangle]
pub extern "C" fn flow_mem_bench(mb: u32, threads: u32, out: *mut u8, cap: usize) -> i64 {
    let mb = (mb as usize).clamp(32, 512);
    let t = if threads == 0 { crate::sys::physical_cores() } else { threads as usize }.clamp(1, 64);
    let bw1 = bandwidth(mb, 1);
    let bwn = if t > 1 { bandwidth(mb, t) } else { bw1 };
    let s = Obj::new().f("bw1", (bw1 * 100.0).round() / 100.0).f("bwn", (bwn.max(bw1) * 100.0).round() / 100.0).i("threads", t as i64).i("mb", mb as i64).end();
    put(out, cap, &s)
}

/// GFLOPS (int8/FP32 misto, estimativa grosseira) por núcleo para cada nível SIMD — só serve para estimar a leitura do prompt.
fn gflops_per_core(simd: u32) -> f64 {
    match simd {
        3 => 60.0,
        2 => 35.0,
        1 => 18.0,
        4 => 25.0,
        _ => 8.0,
    }
}

#[no_mangle]
pub extern "C" fn flow_plan_cpu(weights: u64, ctx: i64, bw1: f64, bwn: f64, p_phys: u32, e_phys: u32, logical: u32, hybrid: u32, simd: u32, l2_kb: u64, ram_avail: u64, mode: u32, out: *mut u8, cap: usize) -> i64 {
    let w = weights as f64;
    let gb = w / 1073741824.0;
    let p = p_phys.max(1) as f64;
    let l = logical.max(p_phys.max(1)) as f64;
    let (bw1, bwn) = if bwn > 0.0 && bw1 > 0.0 { (bw1, bwn.max(bw1)) } else { (0.0, 0.0) };
    let known = bwn > 0.0;
    // threads de geração: o suficiente para saturar a memória (e uma de folga), sem passar dos núcleos de desempenho
    let sat = if known { (bwn / bw1).ceil().clamp(1.0, p) } else { p };
    let mut gen = (sat + 1.0).min(p);
    if gen >= p && p >= 6.0 {
        gen = p - 1.0; // deixa um núcleo para o sistema e a interface
    }
    if p <= 2.0 {
        gen = p;
    }
    let gen = gen.max(1.0);
    let batch_threads = p; // ingestão do prompt é limitada pela conta: todos os núcleos de desempenho
    // fraca: poucos núcleos, SIMD antigo, memória lenta ou pouca RAM
    let weak = p <= 4.0 || simd < 2 || (known && bwn < 15.0) || ram_avail < (6u64 << 30);
    let l2 = if l2_kb > 0 { l2_kb as f64 } else { 1024.0 };
    let n_ubatch = if weak || l2 < 768.0 { 64.0 } else if mode == 2 { 256.0 } else { 128.0 };
    let n_batch = if weak { 128.0 } else if mode == 2 { 512.0 } else { 256.0 };
    let est_tps = if known && w > 0.0 { bwn * 0.65 / gb } else { 0.0 };
    // ~4,6 bits por peso → parâmetros; ~2 operações por parâmetro por token de prompt; 35% de eficiência
    let params = w * 8.0 / 4.6;
    let est_pp = if w > 0.0 { batch_threads * gflops_per_core(simd) * 1e9 * 0.35 / (2.0 * params) } else { 0.0 };
    let ctx_cap = if weak { 4096 } else { 0 };
    // maior modelo que ainda gera pelo menos 5 e 10 tokens/s
    let max5 = if known { bwn * 0.65 / 5.0 } else { 0.0 };
    let max10 = if known { bwn * 0.65 / 10.0 } else { 0.0 };
    let mut notes: Vec<String> = Vec::new();
    if simd < 2 {
        notes.push("a CPU não tem AVX2: a geração será bem lenta".to_string());
    }
    if known && est_tps > 0.0 && est_tps < 2.0 {
        notes.push(format!("deve gerar só ~{:.1} tokens/s com este modelo: prefira um menor ou uma quantização menor", est_tps));
    }
    if hybrid != 0 && e_phys > 0 {
        notes.push(format!("CPU híbrida: a geração usa só os {} núcleos de desempenho", p_phys));
    }
    let _ = (ctx, l);
    let s = Obj::new()
        .i("n_threads", gen as i64).i("n_threads_batch", batch_threads as i64).i("n_batch", n_batch as i64).i("n_ubatch", n_ubatch as i64)
        .b("weak", weak).b("kv_q8", weak).b("flash", simd >= 2).i("ctx_cap", ctx_cap)
        .f("est_tps", (est_tps * 10.0).round() / 10.0).f("est_pp", (est_pp * 10.0).round() / 10.0)
        .f("max_gb_5tps", (max5 * 10.0).round() / 10.0).f("max_gb_10tps", (max10 * 10.0).round() / 10.0)
        .b("pin", hybrid != 0 && e_phys > 0).strs("notes", &notes).end();
    put(out, cap, &s)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn call(f: impl Fn(*mut u8, usize) -> i64) -> String {
        let mut buf = vec![0u8; 8192];
        let n = f(buf.as_mut_ptr(), buf.len()) as usize;
        String::from_utf8(buf[..n].to_vec()).unwrap()
    }

    #[test]
    fn cpu_lists_parse() {
        assert_eq!(parse_cpu_list("0-3,8,10-11\n"), vec![0, 1, 2, 3, 8, 10, 11]);
        assert!(parse_cpu_list("").is_empty());
        assert!(parse_cpu_list("5-2").is_empty());
    }

    #[test]
    fn cpu_info_is_json_with_basics() {
        let s = call(|o, c| flow_cpu_info(o, c));
        assert!(s.contains("\"p_physical\":") && s.contains("\"simd\":") && s.contains("\"features\":"));
    }

    #[test]
    fn bandwidth_is_positive() {
        let s = call(|o, c| flow_mem_bench(32, 2, o, c));
        assert!(s.contains("\"bw1\":") && s.contains("\"bwn\":"), "{}", s);
    }

    #[test]
    fn weak_cpu_gets_small_batches_and_estimates() {
        // 4 núcleos, AVX2, 12 GB/s, modelo de 4 GiB
        let s = call(|o, c| flow_plan_cpu(4 << 30, 4096, 8.0, 12.0, 4, 0, 8, 0, 2, 512, 8 << 30, 1, o, c));
        assert!(s.contains("\"weak\":true") && s.contains("\"n_batch\":128") && s.contains("\"n_ubatch\":64"), "{}", s);
        assert!(s.contains("\"est_tps\":2"), "{}", s);
    }

    #[test]
    fn strong_hybrid_uses_only_p_cores() {
        let s = call(|o, c| flow_plan_cpu(4 << 30, 4096, 20.0, 60.0, 8, 8, 24, 1, 2, 2048, 32 << 30, 1, o, c));
        assert!(s.contains("\"weak\":false") && s.contains("\"pin\":true") && s.contains("\"n_threads_batch\":8"), "{}", s);
    }
}
