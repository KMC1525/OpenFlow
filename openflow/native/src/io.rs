//! Pré-carga de arquivos de modelo no cache do sistema: leitura paralela (várias threads, faixas disjuntas) para o `mmap`/`from_pretrained` achar tudo já em RAM.
//!
//! Carregar um modelo de vários GB lendo em páginas aleatórias (mmap) num disco frio é lento; ler o arquivo em sequência, com várias threads e um aviso ao sistema
//! (`posix_fadvise(WILLNEED)` no Linux), costuma ser várias vezes mais rápido. Os dados lidos são descartados: o efeito é o cache do sistema operacional.

use std::fs::File;

#[cfg(any(target_os = "linux", target_os = "android"))]
extern "C" {
    fn posix_fadvise(fd: i32, offset: i64, len: i64, advice: i32) -> i32;
}

#[cfg(unix)]
fn read_at(f: &File, buf: &mut [u8], off: u64) -> std::io::Result<usize> {
    std::os::unix::fs::FileExt::read_at(f, buf, off)
}
#[cfg(windows)]
fn read_at(f: &File, buf: &mut [u8], off: u64) -> std::io::Result<usize> {
    std::os::windows::fs::FileExt::seek_read(f, buf, off)
}

/// Lê o arquivo inteiro com `threads` threads. Devolve os bytes lidos, ou -1 se não abriu.
#[no_mangle]
pub unsafe extern "C" fn flow_prefetch(path: *const u8, path_len: usize, threads: u32) -> i64 {
    if path.is_null() || path_len == 0 || path_len > 4096 {
        return -1;
    }
    let p = match std::str::from_utf8(std::slice::from_raw_parts(path, path_len)) {
        Ok(p) => p,
        Err(_) => return -1,
    };
    let f = match File::open(p) {
        Ok(f) => f,
        Err(_) => return -1,
    };
    let size = match f.metadata() {
        Ok(m) => m.len(),
        Err(_) => return -1,
    };
    if size == 0 {
        return 0;
    }
    #[cfg(any(target_os = "linux", target_os = "android"))]
    {
        use std::os::unix::io::AsRawFd;
        posix_fadvise(f.as_raw_fd(), 0, 0, 3); // POSIX_FADV_WILLNEED
    }
    const CH: u64 = 4 << 20;
    let n = (threads.clamp(1, 16) as u64).min((size + CH - 1) / CH).max(1);
    let stripe = ((size / n + CH - 1) / CH) * CH; // faixas alinhadas a 4 MiB
    let total = std::sync::atomic::AtomicU64::new(0);
    std::thread::scope(|s| {
        for i in 0..n {
            let (f, total) = (&f, &total);
            s.spawn(move || {
                let (start, end) = (i * stripe, ((i + 1) * stripe).min(size));
                let mut buf = vec![0u8; CH as usize];
                let mut off = start;
                while off < end {
                    let want = ((end - off).min(CH)) as usize;
                    match read_at(f, &mut buf[..want], off) {
                        Ok(0) | Err(_) => break,
                        Ok(k) => {
                            off += k as u64;
                            total.fetch_add(k as u64, std::sync::atomic::Ordering::Relaxed);
                        }
                    }
                }
            });
        }
    });
    total.load(std::sync::atomic::Ordering::Relaxed) as i64
}
