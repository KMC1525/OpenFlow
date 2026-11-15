//! Placas de vídeo NVIDIA, AMD e Intel (v0.29): detecção (nvidia-smi; no Linux, /sys/class/drm para AMD e Intel), tipo (dedicada ou integrada) e backend recomendado, e o planejador de quantas
//! camadas de um modelo de texto vão para a placa — com ou sem o cache de atenção nela — e da velocidade esperada.
//!
//! Na GPU, a geração também é limitada pela memória: cada token lê os pesos que estão na placa (largura de banda da VRAM) e os que ficaram na RAM (largura de banda da RAM).
//! Placas fracas (2–6 GB, notebooks) ganham muito mais deixando o cache de atenção na RAM e enchendo a VRAM só com camadas. O mesmo cálculo existe em Python (`native/__init__.py`).

use crate::util::{esc, put};
use std::process::Command;

const MIB: f64 = 1048576.0;

struct Gpu {
    index: i64,
    vendor: &'static str, // nvidia | amd | intel | apple
    name: String,
    integrated: bool,
    vram_total: u64,
    vram_free: u64,
    pci: String,
}

fn read(p: &str) -> Option<String> {
    std::fs::read_to_string(p).ok().map(|s| s.trim().to_string())
}

/// Nome do dispositivo PCI no banco `pci.ids` do sistema (Linux): «Navi 23 [Radeon RX 6600/6600 XT]».
fn pci_name(vendor: &str, device: &str) -> Option<String> {
    for p in ["/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids", "/usr/share/pci.ids"] {
        if let Some(txt) = std::fs::read_to_string(p).ok() {
            let mut in_vendor = false;
            for line in txt.lines() {
                if line.starts_with('#') || line.is_empty() {
                    continue;
                }
                if !line.starts_with('\t') {
                    in_vendor = line.starts_with(vendor);
                } else if in_vendor && line.starts_with('\t') && !line.starts_with("\t\t") {
                    let l = line.trim_start();
                    if l.starts_with(device) {
                        return Some(l[device.len()..].trim().to_string());
                    }
                }
            }
        }
    }
    None
}

fn nvidia() -> Vec<Gpu> {
    let out = Command::new("nvidia-smi").args(["--query-gpu=index,name,memory.total,memory.free", "--format=csv,noheader,nounits"]).output();
    let mut v = Vec::new();
    if let Ok(o) = out {
        if o.status.success() {
            for line in String::from_utf8_lossy(&o.stdout).lines() {
                let p: Vec<&str> = line.split(',').map(|x| x.trim()).collect();
                if p.len() >= 4 {
                    if let (Ok(i), Ok(t), Ok(f)) = (p[0].parse::<i64>(), p[p.len() - 2].parse::<f64>(), p[p.len() - 1].parse::<f64>()) {
                        v.push(Gpu { index: i, vendor: "nvidia", name: p[1..p.len() - 2].join(", "), integrated: false, vram_total: (t * MIB) as u64, vram_free: (f * MIB) as u64, pci: String::new() });
                    }
                }
            }
        }
    }
    v
}

#[cfg(any(target_os = "linux", target_os = "android"))]
fn sysfs() -> Vec<Gpu> {
    let mut v = Vec::new();
    let mut cards: Vec<String> = std::fs::read_dir("/sys/class/drm").map(|d| d.filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_string()).collect()).unwrap_or_default();
    cards.sort();
    for c in cards {
        // só «cardN» (não «cardN-HDMI-A-1»)
        if !c.starts_with("card") || c[4..].chars().any(|ch| !ch.is_ascii_digit()) {
            continue;
        }
        let dev = format!("/sys/class/drm/{}/device", c);
        let vend = read(&format!("{}/vendor", dev)).unwrap_or_default().to_lowercase();
        let did = read(&format!("{}/device", dev)).unwrap_or_default().to_lowercase();
        let (vid, dh) = (vend.trim_start_matches("0x").to_string(), did.trim_start_matches("0x").to_string());
        let idx = c[4..].parse::<i64>().unwrap_or(0);
        if vid == "1002" {
            let total = read(&format!("{}/mem_info_vram_total", dev)).and_then(|s| s.parse::<u64>().ok()).unwrap_or(0);
            let used = read(&format!("{}/mem_info_vram_used", dev)).and_then(|s| s.parse::<u64>().ok()).unwrap_or(0);
            let name = pci_name("1002", &dh).unwrap_or_else(|| format!("AMD GPU ({}:{})", vid, dh));
            v.push(Gpu { index: idx, vendor: "amd", name, integrated: total <= (2u64 << 30), vram_total: total, vram_free: total.saturating_sub(used), pci: format!("{}:{}", vid, dh) });
        } else if vid == "8086" {
            // Arc (dedicada) expõe a memória local; as integradas usam a RAM
            let lmem = read(&format!("/sys/class/drm/{}/lmem_total_bytes", c)).and_then(|s| s.parse::<u64>().ok()).unwrap_or(0);
            let name = pci_name("8086", &dh).unwrap_or_else(|| format!("Intel GPU ({}:{})", vid, dh));
            v.push(Gpu { index: idx, vendor: "intel", name, integrated: lmem == 0, vram_total: lmem, vram_free: lmem, pci: format!("{}:{}", vid, dh) });
        }
    }
    v
}

#[cfg(not(any(target_os = "linux", target_os = "android")))]
fn sysfs() -> Vec<Gpu> {
    Vec::new()
}

fn all() -> Vec<Gpu> {
    let mut v = nvidia();
    v.extend(sysfs());
    v
}

fn backend_of(g: &Gpu) -> &'static str {
    match g.vendor {
        "nvidia" => "cuda",
        "apple" => "metal",
        _ => "vulkan",
    }
}

#[no_mangle]
pub extern "C" fn flow_gpu_info(out: *mut u8, cap: usize) -> i64 {
    let gpus = all();
    let items: Vec<String> = gpus
        .iter()
        .map(|g| {
            format!(
                "{{\"index\":{},\"vendor\":{},\"name\":{},\"integrated\":{},\"vram_total\":{},\"vram_free\":{},\"backend\":{},\"pci\":{}}}",
                g.index, esc(g.vendor), esc(&g.name), g.integrated, g.vram_total, g.vram_free, esc(backend_of(g)), esc(&g.pci)
            )
        })
        .collect();
    put(out, cap, &format!("{{\"gpus\":[{}]}}", items.join(",")))
}

/// Planejador de GPU para um modelo de texto. `vendor`: 0 NVIDIA, 1 AMD, 2 Intel, 3 Apple. `kind`: 0 dedicada, 1 integrada.
/// `bw_gpu`/`bw_cpu`: largura de banda (GB/s) da VRAM e da RAM (0 = desconhecida). Devolve camadas na GPU, se o cache de atenção fica na placa, atenção flash, velocidade esperada e avisos.
#[no_mangle]
pub extern "C" fn flow_plan_gpu(weights: u64, layers: i64, kv_per_token: i64, ctx: i64, vram_total: u64, vram_free: u64, vendor: u32, kind: u32, bw_gpu: f64, bw_cpu: f64, ram_avail: u64, mode: u32, out: *mut u8, cap: usize) -> i64 {
    let w = weights as f64;
    let n_layers = layers.max(1) as f64;
    let layer_bytes = w / n_layers;
    let kvpt = if kv_per_token > 0 { kv_per_token as f64 } else { 131072.0 };
    let ctx_f = ctx.max(512) as f64;
    let kv_total = kvpt * ctx_f * if mode == 0 { 0.53 } else { 1.0 };
    let vram = vram_free as f64;
    let total = vram_total as f64;
    // reserva: o sistema (monitor, navegador) usa a VRAM também; mais folga nas placas pequenas, que é onde ela falta
    let reserve = (600.0 + if total > 0.0 && total <= 6144.0 * MIB { 400.0 } else { 0.0 }) * MIB;
    let usable = (vram * 0.92 - reserve).max(0.0);
    let mut notes: Vec<String> = Vec::new();
    let integrated = kind != 0;
    let fit = |kv_on_gpu: bool| -> f64 {
        let per = layer_bytes + if kv_on_gpu { kv_total / n_layers } else { 0.0 };
        if per <= 0.0 { 0.0 } else { (usable / per).floor().min(n_layers).max(0.0) }
    };
    let (a, b) = (fit(true), fit(false));
    let time_for = |ngl: f64| -> f64 {
        // segundos por token: pesos na GPU lidos na VRAM, o resto na RAM
        let gb = |x: f64| x / 1073741824.0;
        let g = if bw_gpu > 0.0 { gb(ngl * layer_bytes) / bw_gpu } else { 0.0 };
        let c = if bw_cpu > 0.0 { gb((n_layers - ngl) * layer_bytes) / bw_cpu } else { 0.0 };
        g + c
    };
    let known = bw_gpu > 0.0 && bw_cpu > 0.0;
    // com o cache de atenção na RAM cabem mais camadas na placa; só vale quando a conta de velocidade (ou, sem ela, o número de camadas) ganha
    let mut kv_on_gpu = true;
    let mut ngl = a;
    if b > a && a < n_layers {
        let better = if known { time_for(b) < time_for(a) * 0.97 } else { true };
        if better {
            kv_on_gpu = false;
            ngl = b;
            notes.push("o cache de atenção fica na RAM para caber mais camadas na placa".to_string());
        }
    }
    if integrated {
        notes.push("GPU integrada: usa a mesma RAM do processador; o ganho é pequeno e a CPU costuma render igual".to_string());
    }
    if ngl < 1.0 {
        ngl = 0.0;
    }
    let all_gpu = ngl >= n_layers;
    let est_tps = if known && w > 0.0 { let t = time_for(ngl); if t > 0.0 { 0.65 / t } else { 0.0 } } else { 0.0 };
    let est_cpu = if bw_cpu > 0.0 && w > 0.0 { bw_cpu * 0.65 / (w / 1073741824.0) } else { 0.0 };
    if ngl > 0.0 && !all_gpu {
        notes.push(format!("{} de {} camadas na placa; o resto roda na CPU", ngl as i64, n_layers as i64));
    }
    if ngl == 0.0 && vram_free > 0 {
        notes.push("a placa não tem memória livre suficiente nem para uma camada: o modelo roda na CPU".to_string());
    }
    // atenção flash: NVIDIA e Apple; nos backends Vulkan (AMD/Intel) a compatibilidade varia, então fica desligada
    let flash = vendor == 0 || vendor == 3;
    let _ = ram_avail;
    let s = crate::util::Obj::new()
        .i("n_gpu_layers", if all_gpu { -1 } else { ngl as i64 }).i("layers_fit", ngl as i64).b("offload_kqv", kv_on_gpu || ngl == 0.0).b("flash", flash)
        .b("use_gpu", ngl > 0.0 && !(integrated && vendor != 3))
        .f("est_tps", (est_tps * 10.0 + 0.5).floor() / 10.0)
        .f("est_tps_cpu", (est_cpu * 10.0 + 0.5).floor() / 10.0)
        .i("reserve_mb", (reserve / MIB) as i64).strs("notes", &notes).end();
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
    fn gpu_info_is_json() {
        let s = call(|o, c| flow_gpu_info(o, c));
        assert!(s.starts_with("{\"gpus\":["), "{}", s);
    }

    #[test]
    fn small_card_keeps_the_cache_in_ram_to_fit_more_layers() {
        // modelo de 4 GiB, 32 camadas, 4 GB de VRAM livre, contexto 8192 com 128 KiB/token (1 GiB de cache)
        let s = call(|o, c| flow_plan_gpu(4 << 30, 32, 131072, 8192, 4096 << 20, 4096 << 20, 0, 0, 0.0, 0.0, 16 << 30, 1, o, c));
        assert!(s.contains("\"offload_kqv\":false"), "{}", s);
    }

    #[test]
    fn roomy_card_runs_everything_on_the_gpu() {
        let s = call(|o, c| flow_plan_gpu(4 << 30, 32, 131072, 4096, 12288 << 20, 11000 << 20, 0, 0, 360.0, 40.0, 32 << 30, 1, o, c));
        assert!(s.contains("\"n_gpu_layers\":-1") && s.contains("\"offload_kqv\":true") && s.contains("\"flash\":true"), "{}", s);
    }

    #[test]
    fn integrated_gpu_is_not_used_by_default() {
        let s = call(|o, c| flow_plan_gpu(2 << 30, 24, 65536, 4096, 8192 << 20, 6000 << 20, 2, 1, 0.0, 0.0, 16 << 30, 1, o, c));
        assert!(s.contains("\"use_gpu\":false"), "{}", s);
    }
}
