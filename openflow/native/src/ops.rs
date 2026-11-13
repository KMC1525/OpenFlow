//! Operações de sistema do núcleo (v0.14, interface 3): plano de execução de vários agentes de IA locais, varredura de pastas e arquivos duplicados (armazenamento),
//! devolução de memória ao sistema e remoção de arquivos de modelo do cache de páginas.
//!
//! Tudo só com a biblioteca padrão do Rust; cada função tem o equivalente em Python (`openflow/native/__init__.py`) e os testes conferem que os dois dão o mesmo resultado.

use crate::util::{put, Obj};
use std::collections::HashMap;
use std::fs;
use std::hash::Hasher;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

const MIB: f64 = 1048576.0;

// --------------------------------------------------------------------------- plano de execução de vários agentes
/// Quantos agentes rodam ao mesmo tempo, quantos modelos ficam residentes e quantas threads cada agente usa.
/// `kind`: 0 = nuvem (limitado pela API), 1 = modelo embutido (uma instância no processo), 2 = servidor local (LM Studio, Ollama, llama.cpp: ele mesmo atende em paralelo).
/// `mode`: 0 leve, 1 equilibrado, 2 máximo.
#[no_mangle]
pub extern "C" fn flow_plan_agents(
    n_agents: u32, kind: u32, model_bytes: u64, kv_bytes_per_agent: u64, ram_avail: u64, vram_free: u64, unified: u32, phys: u32, logical: u32, mode: u32, out: *mut u8, cap: usize,
) -> i64 {
    let n = n_agents.max(1) as f64;
    let p = phys.max(1) as f64;
    let l = logical.max(phys.max(1)) as f64;
    let ram = ram_avail as f64;
    let vram = vram_free as f64;
    let w = (model_bytes as f64).max(1.0);
    let kv = (kv_bytes_per_agent as f64).max(0.0);
    let mut notes: Vec<String> = Vec::new();

    // modelos que cabem ao mesmo tempo na memória (GPU primeiro; memória unificada compartilha a RAM)
    let pool = if unified != 0 { ram * 0.65 } else if vram > 0.0 { vram * 0.85 + ram * 0.30 } else { ram * 0.65 };
    let fit = (pool / (w * 1.15)).floor().max(1.0);
    let resident = match mode {
        0 => 1.0,
        1 => fit.min(2.0),
        _ => fit.min(3.0),
    };

    let (parallel, threads_each, queue) = match kind {
        0 => {
            // nuvem: a espera é de rede; o limite é o que a API aguenta sem 429
            let cap_by_mode = match mode { 0 => 2.0, 1 => 4.0, _ => 8.0 };
            (n.min(cap_by_mode), 1.0, "fair")
        }
        2 => {
            // servidor local: ele enfileira e pode atender alguns pedidos juntos; mais que isso só disputa CPU/GPU
            let cap_by_mode = match mode { 0 => 1.0, 1 => 2.0, _ => 4.0 };
            let by_mem = ((pool - w) / kv.max(64.0 * MIB)).floor().max(1.0);
            (n.min(cap_by_mode).min(by_mem), 1.0, "fair")
        }
        _ => {
            // modelo embutido: uma instância gera por vez (a trava do llama.cpp); os agentes entram numa fila com prioridade e dividem o cache do prompt
            if n > 1.0 {
                notes.push("modelo embutido: um agente fala por vez (fila com prioridade para o chat)".to_string());
            }
            (1.0, if vram > 0.0 { p.min(4.0) } else if p >= 8.0 { p - 1.0 } else { p }, "priority")
        }
    };
    let threads = if kind == 1 { threads_each } else if mode == 0 { (p / 2.0).floor().max(1.0) } else { (l / parallel.max(1.0)).floor().max(1.0).min(p) };
    let share_prefix = kind != 0 && n > 1.0;
    let s = Obj::new()
        .i("parallel", parallel as i64).i("resident_models", resident as i64).i("threads_each", threads as i64).s("queue", queue).b("share_prefix", share_prefix)
        .i("pool_bytes", pool as i64).strs("notes", &notes).end();
    put(out, cap, &s)
}

// --------------------------------------------------------------------------- varredura de pastas
struct Walk {
    files: u64,
    bytes: u64,
    dirs: u64,
    by_ext: HashMap<String, (u64, u64)>,
    largest: Vec<(u64, String)>,
}

fn ext_of(p: &Path) -> String {
    p.extension().and_then(|e| e.to_str()).map(|e| e.to_ascii_lowercase()).unwrap_or_default()
}

/// O arquivo entra na lista dos maiores? (checado ANTES de montar o texto do caminho: a maioria dos arquivos não entra e não precisa de alocação)
fn qualifies(v: &[(u64, String)], size: u64, keep: usize) -> bool {
    v.len() < keep || size > v.last().map(|x| x.0).unwrap_or(0)
}

fn push_largest(v: &mut Vec<(u64, String)>, size: u64, path: &str, keep: usize) {
    if qualifies(v, size, keep) {
        v.push((size, path.to_string()));
        v.sort_by(|a, b| b.0.cmp(&a.0));
        v.truncate(keep);
    }
}

/// Percorre `root` com várias threads (uma pilha de pastas compartilhada). Não segue links simbólicos. Devolve JSON com totais, tipos e os maiores arquivos.
#[no_mangle]
pub unsafe extern "C" fn flow_scan_dir(path: *const u8, path_len: usize, max_entries: u64, threads: u32, out: *mut u8, cap: usize) -> i64 {
    let root = match path_arg(path, path_len) {
        Some(r) => r,
        None => return -1,
    };
    if !root.is_dir() {
        return -1;
    }
    let stack: Mutex<Vec<PathBuf>> = Mutex::new(vec![root.clone()]);
    let total = Mutex::new(Walk { files: 0, bytes: 0, dirs: 0, by_ext: HashMap::new(), largest: Vec::new() });
    let busy = std::sync::atomic::AtomicUsize::new(0);
    let limit = if max_entries == 0 { 5_000_000 } else { max_entries };
    let n = threads.clamp(1, 16) as usize;
    std::thread::scope(|s| {
        for _ in 0..n {
            s.spawn(|| {
                let mut local = Walk { files: 0, bytes: 0, dirs: 0, by_ext: HashMap::new(), largest: Vec::new() };
                loop {
                    let next = {
                        let mut g = stack.lock().unwrap();
                        let item = g.pop();
                        if item.is_some() {
                            busy.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                        }
                        item
                    };
                    match next {
                        Some(dir) => {
                            let mut sub_dirs: Vec<PathBuf> = Vec::new();
                            if let Ok(rd) = fs::read_dir(&dir) {
                                for e in rd.flatten() {
                                    let Ok(ft) = e.file_type() else { continue };
                                    if ft.is_symlink() {
                                        continue;
                                    }
                                    if ft.is_dir() {
                                        local.dirs += 1;
                                        sub_dirs.push(e.path());
                                    } else if ft.is_file() {
                                        if let Ok(m) = e.metadata() {
                                            let sz = m.len();
                                            local.files += 1;
                                            local.bytes += sz;
                                            let name = e.file_name();
                                            let ex = ext_of(Path::new(&name));   // só o nome do arquivo: não monta o caminho inteiro por arquivo
                                            match local.by_ext.get_mut(&ex) {
                                                Some(ent) => {
                                                    ent.0 += 1;
                                                    ent.1 += sz;
                                                }
                                                None => {
                                                    local.by_ext.insert(ex, (1, sz));
                                                }
                                            }
                                            if qualifies(&local.largest, sz, 20) {
                                                push_largest(&mut local.largest, sz, &e.path().to_string_lossy(), 20);
                                            }
                                        }
                                    }
                                }
                            }
                            if !sub_dirs.is_empty() {   // uma única trava para todas as subpastas da pasta (antes: uma trava por subpasta)
                                stack.lock().unwrap().extend(sub_dirs);
                            }
                            busy.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
                        }
                        None => {
                            if busy.load(std::sync::atomic::Ordering::SeqCst) == 0 && stack.lock().unwrap().is_empty() {
                                break;
                            }
                            // Short backoff instead of a tight spin: much kinder to weak CPUs while others are still scanning.
                            std::thread::sleep(std::time::Duration::from_millis(1));
                        }
                    }
                    if local.files + local.dirs > limit {
                        break;
                    }
                }
                let mut t = total.lock().unwrap();
                t.files += local.files;
                t.bytes += local.bytes;
                t.dirs += local.dirs;
                for (k, v) in local.by_ext {
                    let e = t.by_ext.entry(k).or_insert((0, 0));
                    e.0 += v.0;
                    e.1 += v.1;
                }
                for (sz, p) in local.largest {
                    push_largest(&mut t.largest, sz, &p, 20);
                }
            });
        }
    });
    let t = total.into_inner().unwrap();
    let mut exts: Vec<(String, (u64, u64))> = t.by_ext.into_iter().collect();
    exts.sort_by(|a, b| b.1 .1.cmp(&a.1 .1).then(a.0.cmp(&b.0)));
    exts.truncate(16);
    let mut ext_json = String::from("[");
    for (i, (k, (c, b))) in exts.iter().enumerate() {
        if i > 0 {
            ext_json.push(',');
        }
        ext_json.push_str(&Obj::new().s("ext", k).i("files", *c as i64).i("bytes", *b as i64).end());
    }
    ext_json.push(']');
    let mut big_json = String::from("[");
    for (i, (sz, p)) in t.largest.iter().enumerate() {
        if i > 0 {
            big_json.push(',');
        }
        big_json.push_str(&Obj::new().s("path", p).i("bytes", *sz as i64).end());
    }
    big_json.push(']');
    let s = Obj::new().i("files", t.files as i64).i("dirs", t.dirs as i64).i("bytes", t.bytes as i64).raw("by_ext", &ext_json).raw("largest", &big_json).end();
    put(out, cap, &s)
}

unsafe fn path_arg(path: *const u8, len: usize) -> Option<PathBuf> {
    if path.is_null() || len == 0 || len > 4096 {
        return None;
    }
    std::str::from_utf8(std::slice::from_raw_parts(path, len)).ok().map(PathBuf::from)
}

// --------------------------------------------------------------------------- arquivos duplicados
fn hash_range(path: &Path, head_tail_only: bool, size: u64) -> Option<u64> {
    let mut f = fs::File::open(path).ok()?;
    let mut h = std::collections::hash_map::DefaultHasher::new();
    h.write_u64(size);
    let mut buf = vec![0u8; if head_tail_only { 65536 } else { 1 << 20 }];   // cabeça+cauda só lê 64 KiB: não aloca 1 MiB por arquivo
    if head_tail_only {
        let k = f.read(&mut buf[..65536.min(size as usize).max(1)]).ok()?;
        h.write(&buf[..k]);
        if size > 131072 {
            use std::io::{Seek, SeekFrom};
            f.seek(SeekFrom::Start(size - 65536)).ok()?;
            let k = f.read(&mut buf[..65536]).ok()?;
            h.write(&buf[..k]);
        }
    } else {
        loop {
            let k = f.read(&mut buf).ok()?;
            if k == 0 {
                break;
            }
            h.write(&buf[..k]);
        }
    }
    Some(h.finish())
}

fn same_bytes(a: &Path, b: &Path) -> bool {
    let (Ok(mut fa), Ok(mut fb)) = (fs::File::open(a), fs::File::open(b)) else { return false };
    let (mut ba, mut bb) = (vec![0u8; 1 << 18], vec![0u8; 1 << 18]);
    loop {
        let (ra, rb) = match (read_full(&mut fa, &mut ba), read_full(&mut fb, &mut bb)) {
            (Some(x), Some(y)) => (x, y),
            _ => return false,
        };
        if ra != rb || ba[..ra] != bb[..rb] {
            return false;
        }
        if ra == 0 {
            return true;
        }
    }
}

fn read_full(f: &mut fs::File, buf: &mut [u8]) -> Option<usize> {
    let mut got = 0;
    while got < buf.len() {
        match f.read(&mut buf[got..]) {
            Ok(0) => break,
            Ok(k) => got += k,
            Err(_) => return None,
        }
    }
    Some(got)
}

fn collect_files(root: &Path, min_size: u64, max_files: usize, exts: &[String], out: &mut Vec<(u64, PathBuf)>) {
    let mut stack = vec![root.to_path_buf()];
    while let Some(dir) = stack.pop() {
        let Ok(rd) = fs::read_dir(&dir) else { continue };
        for e in rd.flatten() {
            let Ok(ft) = e.file_type() else { continue };
            if ft.is_symlink() {
                continue;
            }
            if ft.is_dir() {
                stack.push(e.path());
            } else if ft.is_file() {
                let Ok(m) = e.metadata() else { continue };
                if m.len() >= min_size && (exts.is_empty() || exts.contains(&ext_of(&e.path()))) {
                    out.push((m.len(), e.path()));
                    if out.len() >= max_files {
                        return;
                    }
                }
            }
        }
    }
}

/// Grupos de arquivos IDÊNTICOS (mesmo tamanho, mesmo conteúdo — confirmado byte a byte) sob `root`, com pelo menos `min_size` bytes. `exts` = extensões separadas por vírgula (vazio = todas).
/// Devolve JSON `[{"size":N,"paths":[...]},...]` (do maior para o menor).
#[no_mangle]
pub unsafe extern "C" fn flow_dup_groups(path: *const u8, path_len: usize, min_size: u64, exts: *const u8, exts_len: usize, max_files: u64, out: *mut u8, cap: usize) -> i64 {
    let root = match path_arg(path, path_len) {
        Some(r) if r.is_dir() => r,
        _ => return -1,
    };
    let ext_list: Vec<String> = if exts.is_null() || exts_len == 0 {
        Vec::new()
    } else {
        std::str::from_utf8(std::slice::from_raw_parts(exts, exts_len)).unwrap_or("").split(',').map(|x| x.trim().trim_start_matches('.').to_ascii_lowercase()).filter(|x| !x.is_empty()).collect()
    };
    let mut files: Vec<(u64, PathBuf)> = Vec::new();
    collect_files(&root, min_size.max(1), if max_files == 0 { 200_000 } else { max_files as usize }, &ext_list, &mut files);
    let mut by_size: HashMap<u64, Vec<PathBuf>> = HashMap::new();
    for (sz, p) in files {
        by_size.entry(sz).or_default().push(p);
    }
    let mut groups: Vec<(u64, Vec<PathBuf>)> = Vec::new();
    for (size, list) in by_size.into_iter().filter(|(_, l)| l.len() > 1) {
        // 1) cabeça+cauda  2) conteúdo inteiro  3) conferência byte a byte
        let mut by_sig: HashMap<u64, Vec<PathBuf>> = HashMap::new();
        for p in list {
            if let Some(h) = hash_range(&p, true, size) {
                by_sig.entry(h).or_default().push(p);
            }
        }
        for (_, l1) in by_sig.into_iter().filter(|(_, l)| l.len() > 1) {
            let mut by_full: HashMap<u64, Vec<PathBuf>> = HashMap::new();
            for p in l1 {
                if let Some(h) = hash_range(&p, false, size) {
                    by_full.entry(h).or_default().push(p);
                }
            }
            for (_, l2) in by_full.into_iter().filter(|(_, l)| l.len() > 1) {
                let mut rest = l2;
                while rest.len() > 1 {
                    let first = rest.remove(0);
                    let (same, other): (Vec<PathBuf>, Vec<PathBuf>) = rest.into_iter().partition(|p| same_bytes(&first, p));
                    if !same.is_empty() {
                        let mut g = vec![first];
                        g.extend(same);
                        g.sort();
                        groups.push((size, g));
                    }
                    rest = other;
                }
            }
        }
    }
    groups.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
    let mut j = String::from("[");
    for (i, (size, paths)) in groups.iter().enumerate() {
        if i > 0 {
            j.push(',');
        }
        let ps: Vec<String> = paths.iter().map(|p| p.to_string_lossy().to_string()).collect();
        j.push_str(&Obj::new().i("size", *size as i64).strs("paths", &ps).end());
    }
    j.push(']');
    put(out, cap, &j)
}

// --------------------------------------------------------------------------- memória
#[cfg(all(target_os = "linux", target_env = "gnu"))]
extern "C" {
    fn malloc_trim(pad: usize) -> i32;
}

#[cfg(any(target_os = "linux", target_os = "android"))]
fn rss_bytes() -> u64 {
    fs::read_to_string("/proc/self/statm").ok().and_then(|s| s.split_whitespace().nth(1).and_then(|v| v.parse::<u64>().ok())).unwrap_or(0) * 4096
}
#[cfg(not(any(target_os = "linux", target_os = "android")))]
fn rss_bytes() -> u64 {
    0
}

/// Devolve ao sistema a memória livre que o alocador ainda segura (depois de descarregar um modelo, o Python liberou os objetos mas a RAM continua "do processo").
/// Linux/glibc: `malloc_trim`; macOS: `malloc_zone_pressure_relief`. Devolve os bytes liberados (estimativa pelo RSS; 0 onde não dá para medir), ou -1 se não há como.
#[no_mangle]
pub extern "C" fn flow_release_memory() -> i64 {
    let before = rss_bytes();
    #[cfg(all(target_os = "linux", target_env = "gnu"))]
    {
        unsafe { malloc_trim(0) };
        return before.saturating_sub(rss_bytes()) as i64;
    }
    #[cfg(target_os = "macos")]
    {
        extern "C" {
            fn malloc_zone_pressure_relief(zone: *mut std::os::raw::c_void, goal: usize) -> usize;
        }
        return unsafe { malloc_zone_pressure_relief(std::ptr::null_mut(), 0) } as i64;
    }
    #[allow(unreachable_code)]
    {
        let _ = before;
        -1
    }
}

#[cfg(any(target_os = "linux", target_os = "android"))]
extern "C" {
    fn posix_fadvise(fd: i32, offset: i64, len: i64, advice: i32) -> i32;
}

/// Tira o arquivo (pesos de um modelo descarregado) do cache de páginas do sistema: a RAM que ele ocupava volta a ficar livre. Linux: `posix_fadvise(DONTNEED)`.
/// Devolve 0 se fez, 1 se o sistema não oferece isso (macOS/Windows: o sistema gerencia sozinho), -1 se não abriu o arquivo.
#[no_mangle]
pub unsafe extern "C" fn flow_evict_file(path: *const u8, path_len: usize) -> i64 {
    let p = match path_arg(path, path_len) {
        Some(p) => p,
        None => return -1,
    };
    let Ok(_f) = fs::File::open(&p) else { return -1 };
    #[cfg(any(target_os = "linux", target_os = "android"))]
    {
        use std::os::unix::io::AsRawFd;
        return if posix_fadvise(_f.as_raw_fd(), 0, 0, 4) == 0 { 0 } else { 1 }; // POSIX_FADV_DONTNEED
    }
    #[allow(unreachable_code)]
    1
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmpdir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("flow-ops-{}-{}", name, std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    fn call_json(f: impl Fn(*mut u8, usize) -> i64) -> String {
        let mut buf = vec![0u8; 1 << 16];
        let n = f(buf.as_mut_ptr(), buf.len());
        assert!(n >= 0 && (n as usize) <= buf.len());
        String::from_utf8(buf[..n as usize].to_vec()).unwrap()
    }

    #[test]
    fn plan_agents_embedded_model_serializes_and_cloud_parallelizes() {
        let emb = call_json(|o, c| flow_plan_agents(6, 1, 5 << 30, 1 << 28, 32 << 30, 0, 0, 8, 16, 1, o, c));
        assert!(emb.contains("\"parallel\":1") && emb.contains("\"queue\":\"priority\""), "{emb}");
        let cloud = call_json(|o, c| flow_plan_agents(6, 0, 0, 0, 8 << 30, 0, 0, 4, 8, 1, o, c));
        assert!(cloud.contains("\"parallel\":4"), "{cloud}");
        let light = call_json(|o, c| flow_plan_agents(6, 0, 0, 0, 8 << 30, 0, 0, 4, 8, 0, o, c));
        assert!(light.contains("\"parallel\":2") && light.contains("\"resident_models\":1"), "{light}");
    }

    #[test]
    fn scan_counts_files_and_ignores_symlinks() {
        let d = tmpdir("scan");
        fs::create_dir_all(d.join("a/b")).unwrap();
        fs::write(d.join("a/x.gguf"), vec![1u8; 1000]).unwrap();
        fs::write(d.join("a/b/y.png"), vec![2u8; 500]).unwrap();
        fs::write(d.join("z.png"), vec![3u8; 10]).unwrap();
        #[cfg(unix)]
        std::os::unix::fs::symlink(d.join("a/x.gguf"), d.join("link.gguf")).unwrap();
        let p = d.to_string_lossy().to_string();
        let j = call_json(|o, c| unsafe { flow_scan_dir(p.as_ptr(), p.len(), 0, 4, o, c) });
        assert!(j.contains("\"files\":3") && j.contains("\"bytes\":1510"), "{j}");
        assert!(j.contains("\"ext\":\"gguf\""), "{j}");
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn scan_keeps_only_the_twenty_largest_and_counts_nested_folders() {
        let d = tmpdir("scan-big");
        for i in 0..5 {
            fs::create_dir_all(d.join(format!("d{}/sub/deep", i))).unwrap();
        }
        let mut total = 0u64;
        for i in 0..30u64 {
            let sz = 100 + i * 10;
            total += sz;
            let dir = d.join(format!("d{}/sub/deep", i % 5));
            fs::write(dir.join(format!("f{}.dat", i)), vec![7u8; sz as usize]).unwrap();
        }
        let p = d.to_string_lossy().to_string();
        let j = call_json(|o, c| unsafe { flow_scan_dir(p.as_ptr(), p.len(), 0, 3, o, c) });
        assert!(j.contains("\"files\":30") && j.contains(&format!("\"bytes\":{}", total)) && j.contains("\"dirs\":15"), "{j}");
        assert_eq!(j.matches("\"path\"").count(), 20, "{j}");        // só os 20 maiores
        assert!(j.contains("\"bytes\":390}") && !j.contains("\"bytes\":100}"), "{j}");   // o maior (390) entra, o menor (100) não
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn duplicates_are_confirmed_byte_by_byte() {
        let d = tmpdir("dups");
        fs::create_dir_all(d.join("sub")).unwrap();
        let big: Vec<u8> = (0..300_000u32).map(|i| (i % 251) as u8).collect();
        fs::write(d.join("a.bin"), &big).unwrap();
        fs::write(d.join("sub/b.bin"), &big).unwrap();
        let mut other = big.clone();
        other[150_000] ^= 0xff; // mesmo tamanho, cabeça e cauda iguais, miolo diferente
        fs::write(d.join("c.bin"), &other).unwrap();
        fs::write(d.join("tiny.bin"), b"x").unwrap();
        let p = d.to_string_lossy().to_string();
        let e = "bin";
        let j = call_json(|o, cap| unsafe { flow_dup_groups(p.as_ptr(), p.len(), 1000, e.as_ptr(), e.len(), 0, o, cap) });
        assert!(j.contains("a.bin") && j.contains("b.bin") && !j.contains("c.bin") && !j.contains("tiny.bin"), "{j}");
        let _ = fs::remove_dir_all(&d);
    }
}
