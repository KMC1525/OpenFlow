//! Hardware do computador: núcleos físicos/lógicos, extensões da CPU (AVX2, AVX-512, NEON…) e memória (total e disponível, respeitando limite de contêiner).

use crate::util::{put, Obj};

fn read(p: &str) -> Option<String> {
    std::fs::read_to_string(p).ok()
}

pub fn logical_cores() -> usize {
    std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1)
}

/// Núcleos físicos (sem contar o hyper-threading/SMT). Linux: pares de threads irmãs em /sys; nos demais, estimativa pelos lógicos.
pub fn physical_cores() -> usize {
    let logical = logical_cores();
    #[cfg(any(target_os = "linux", target_os = "android"))]
    {
        let mut seen: Vec<String> = Vec::new();
        for i in 0..logical.max(1) {
            if let Some(s) = read(&format!("/sys/devices/system/cpu/cpu{}/topology/thread_siblings_list", i)) {
                let s = s.trim().to_string();
                if !s.is_empty() && !seen.contains(&s) {
                    seen.push(s);
                }
            }
        }
        if !seen.is_empty() {
            return seen.len().min(logical);
        }
    }
    #[cfg(target_os = "macos")]
    {
        return logical; // Apple Silicon e Intel recentes: os lógicos já são, na prática, a contagem útil
    }
    #[allow(unreachable_code)]
    {
        if logical >= 4 { logical / 2 } else { logical }
    }
}

pub fn features() -> Vec<String> {
    let mut f: Vec<String> = Vec::new();
    #[cfg(any(target_arch = "x86", target_arch = "x86_64"))]
    {
        macro_rules! chk { ($($n:tt),*) => { $( if std::arch::is_x86_feature_detected!($n) { f.push($n.to_string()); } )* } }
        chk!("sse4.2", "avx", "avx2", "fma", "f16c", "avx512f", "avx512bw", "avx512vl");
    }
    #[cfg(target_arch = "aarch64")]
    {
        f.push("neon".to_string());
    }
    f
}

/// (total, disponível) em bytes. Dentro de contêiner (cgroup) vale o limite dele.
pub fn memory() -> (u64, u64, bool) {
    #[cfg(any(target_os = "linux", target_os = "android"))]
    {
        if let Some(m) = read("/proc/meminfo") {
            let kb = |k: &str| -> u64 {
                m.lines().find(|l| l.starts_with(k)).and_then(|l| l.split_whitespace().nth(1)).and_then(|v| v.parse::<u64>().ok()).unwrap_or(0) * 1024
            };
            let (mut total, mut avail) = (kb("MemTotal:"), kb("MemAvailable:"));
            if avail == 0 {
                avail = kb("MemFree:") + kb("Cached:");
            }
            for p in ["/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"] {
                if let Some(v) = read(p).and_then(|s| s.trim().parse::<u64>().ok()) {
                    if v > 0 && v < total {
                        total = v;
                        avail = avail.min(v);
                    }
                }
            }
            return (total, avail.min(total), true);
        }
    }
    #[cfg(target_os = "windows")]
    {
        #[repr(C)]
        struct MemStatus { len: u32, load: u32, total: u64, avail: u64, tp: u64, ap: u64, tv: u64, av: u64, ext: u64 }
        extern "system" { fn GlobalMemoryStatusEx(b: *mut MemStatus) -> i32; }
        let mut s = MemStatus { len: std::mem::size_of::<MemStatus>() as u32, load: 0, total: 0, avail: 0, tp: 0, ap: 0, tv: 0, av: 0, ext: 0 };
        if unsafe { GlobalMemoryStatusEx(&mut s) } != 0 {
            return (s.total, s.avail, true);
        }
    }
    #[cfg(target_os = "macos")]
    {
        extern "C" { fn sysctlbyname(name: *const std::os::raw::c_char, oldp: *mut std::os::raw::c_void, oldlenp: *mut usize, newp: *mut std::os::raw::c_void, newlen: usize) -> i32; }
        let mut v: u64 = 0;
        let mut n = std::mem::size_of::<u64>();
        let name = b"hw.memsize\0";
        if unsafe { sysctlbyname(name.as_ptr() as *const _, &mut v as *mut u64 as *mut _, &mut n, std::ptr::null_mut(), 0) } == 0 && v > 0 {
            return (v, v / 10 * 6, false); // sem leitura barata da memória livre: estima 60%
        }
    }
    (0, 0, false)
}

#[no_mangle]
pub extern "C" fn flow_sys_info(out: *mut u8, cap: usize) -> i64 {
    let (total, avail, exact) = memory();
    let s = Obj::new()
        .i("logical", logical_cores() as i64)
        .i("physical", physical_cores() as i64)
        .strs("features", &features())
        .s("arch", std::env::consts::ARCH)
        .s("os", std::env::consts::OS)
        .i("ram_total", total as i64)
        .i("ram_avail", avail as i64)
        .b("ram_exact", exact)
        .end();
    put(out, cap, &s)
}
