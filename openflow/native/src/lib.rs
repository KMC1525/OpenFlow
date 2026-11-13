//! Núcleo em Rust do OpenFlow (v0.5; v0.12: carga e inferência de modelos locais — cabeçalhos GGUF/safetensors, hardware, planejador e pré-carga paralela; v0.14: vários agentes locais, armazenamento e memória). Biblioteca C (`cdylib`) carregada pelo Python via `ctypes`; só a biblioteca padrão, sem dependências.
//!
//! Faz o trabalho pesado de CPU da síntese de áudio (música, efeitos e voz do Canvas Demo) em buffers `f64`/`i16` compartilhados com o Python,
//! sem criar um objeto Python por amostra — o que, em máquinas fracas, era o gargalo (20 s de música levavam ~22 s e dezenas de MB).
//! Toda função tem o equivalente em Python puro (`openflow/native/__init__.py` cai nele se a biblioteca não existir).
//! Segurança: todas as funções validam tamanhos/ponteiros nulos; nada aqui faz E/S nem aloca memória que o Python precise liberar.

use std::f64::consts::PI;

mod io;
mod media;
mod model;
mod ops;
mod plan;
mod sys;
mod util;

/// Versão da interface (o Python recusa uma biblioteca de outra versão).
#[no_mangle]
pub extern "C" fn flow_abi_version() -> u32 {
    4
}

unsafe fn slice_mut<'a, T>(p: *mut T, n: usize) -> Option<&'a mut [T]> {
    if p.is_null() || n == 0 {
        None
    } else {
        Some(std::slice::from_raw_parts_mut(p, n))
    }
}

unsafe fn slice_ref<'a, T>(p: *const T, n: usize) -> Option<&'a [T]> {
    if p.is_null() || n == 0 {
        None
    } else {
        Some(std::slice::from_raw_parts(p, n))
    }
}

/// Tom (senoide, quadrada, dente de serra ou triangular) com envelope de ataque/relaxamento, igual ao `_tone` do Python.
/// `wave`: 0 seno, 1 quadrada, 2 serra, 3 triangular. `sweep` só vale se `has_sweep != 0`.
#[no_mangle]
pub unsafe extern "C" fn flow_tone(out: *mut f64, n: usize, freq: f64, wave: u32, vol: f64, sweep: f64, has_sweep: u32, sr: f64, attack_n: usize, release_n: usize) {
    let Some(buf) = slice_mut(out, n) else { return };
    let na = attack_n.max(1) as f64;
    let nr = release_n.max(1) as f64;
    let denom = (n.saturating_sub(1)).max(1) as f64;
    let inv_sr_tau = (2.0 * PI) / sr;
    let inv_tau = 1.0 / (2.0 * PI);
    let mut ph = 0.0f64;
    for (i, o) in buf.iter_mut().enumerate() {
        let t = i as f64;
        let f = if has_sweep != 0 { (sweep - freq).mul_add(t / denom, freq) } else { freq };
        ph += f * inv_sr_tau;
        let cyc = (ph * inv_tau).rem_euclid(1.0);
        let s = match wave {
            1 => if ph.sin() >= 0.0 { 1.0 } else { -1.0 },
            2 => cyc.mul_add(2.0, -1.0),
            3 => (2.0 * cyc - 1.0).abs().mul_add(2.0, -1.0),   // 2·|2c−1|−1, igual ao `_tone` do Python (antes o sinal vinha invertido: 1−2·|2c−1|)
            _ => ph.sin(),
        };
        let attack = (t / na).min(1.0);
        let release = (((n - i) as f64) / nr).min(1.0);
        *o = s * vol * attack * release;
    }
}

/// Gerador xorshift64* (determinístico por semente; não é o `random` do Python).
struct Rng(u64);

impl Rng {
    fn new(seed: u64) -> Self {
        Rng(if seed == 0 { 0x9E37_79B9_7F4A_7C15 } else { seed })
    }
    fn next(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    fn uniform(&mut self) -> f64 {
        ((self.next() >> 11) as f64) / ((1u64 << 53) as f64) * 2.0 - 1.0
    }
}

/// Ruído filtrado (passa-baixa de um polo) com decaimento exponencial e LFO opcionais, como o `_noise` do Python.
#[no_mangle]
pub unsafe extern "C" fn flow_noise(out: *mut f64, n: usize, seed: u64, vol: f64, lp: f64, decay: f64, lfo: f64, sr: f64) {
    let Some(buf) = slice_mut(out, n) else { return };
    let mut rng = Rng::new(seed);
    let mut y = 0.0f64;
    for (i, o) in buf.iter_mut().enumerate() {
        y += lp * (rng.uniform() - y);
        let mut a = vol * if decay != 0.0 { (-decay * (i as f64) / sr).exp() } else { 1.0 };
        if lfo != 0.0 {
            a *= 0.65 + 0.35 * (2.0 * PI * lfo * (i as f64) / sr).sin();
        }
        *o = y * a;
    }
}

/// `dst[offset + i] += src[i]` (corta no fim de `dst`).
#[no_mangle]
pub unsafe extern "C" fn flow_mix_add(dst: *mut f64, dst_len: usize, src: *const f64, src_len: usize, offset: usize) {
    let (Some(d), Some(s)) = (slice_mut(dst, dst_len), slice_ref(src, src_len)) else { return };
    if offset >= d.len() {
        return;
    }
    for (o, v) in d[offset..].iter_mut().zip(s.iter()) {
        *o += *v;
    }
}

/// Fade-out linear nas últimas `fade` amostras (`buf[n-1-i] *= i/fade`).
#[no_mangle]
pub unsafe extern "C" fn flow_fade_out(buf: *mut f64, n: usize, fade: usize) {
    let Some(b) = slice_mut(buf, n) else { return };
    let fade = fade.min(n);
    for i in 0..fade {
        b[n - 1 - i] *= (i as f64) / (fade as f64);
    }
}

/// Converte amostras `f64` em PCM de 16 bits normalizando o pico (se passar de `limit`, escala para `limit`), como o `wav_bytes` do Python.
#[no_mangle]
pub unsafe extern "C" fn flow_pcm16(src: *const f64, n: usize, out: *mut i16, limit: f64) {
    let (Some(s), Some(o)) = (slice_ref(src, n), slice_mut(out, n)) else { return };
    let peak = s.iter().fold(1e-6f64, |m, &v| {
        let a = v.abs();
        if a > m { a } else { m }
    });
    let k = if peak > limit { limit / peak } else { 1.0 };
    for (dst, &v) in o.iter_mut().zip(s.iter()) {
        *dst = (v * k).clamp(-1.0, 1.0).mul_add(32767.0, 0.0) as i16;
    }
}

/// `out[i] = a[i] * b[i]` (envelopes e ganhos em lote).
#[no_mangle]
pub unsafe extern "C" fn flow_mul(a: *const f64, b: *const f64, n: usize, out: *mut f64) {
    let (Some(x), Some(y), Some(o)) = (slice_ref(a, n), slice_ref(b, n), slice_mut(out, n)) else { return };
    for i in 0..n {
        o[i] = x[i] * y[i];
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tone_has_envelope_and_amplitude() {
        let mut b = vec![0.0f64; 4410];
        unsafe { flow_tone(b.as_mut_ptr(), b.len(), 440.0, 0, 0.5, 0.0, 0, 44100.0, 220, 1102) };
        assert!(b[0].abs() < 1e-9 && b.iter().all(|v| v.abs() <= 0.5 + 1e-9));
        assert!(b.iter().fold(0.0f64, |m, v| m.max(v.abs())) > 0.4);
    }

    #[test]
    fn triangle_starts_at_minus_one_and_peaks_at_the_half_cycle() {
        // 2·|2c−1|−1 (o mesmo do Python): em c=0 vale +1, em c=0,25 vale 0 e em c=0,5 vale −1 — conferimos pelo valor sem envelope (volume 1, ataque/relaxamento de 1 amostra)
        let sr = 1000.0;
        let mut b = vec![0.0f64; 1000];
        unsafe { flow_tone(b.as_mut_ptr(), b.len(), 1.0, 3, 1.0, 0.0, 0, sr, 1, 1) };
        let at = |i: usize| b[i];
        assert!((at(249) - (2.0 * ((250.0f64 / 1000.0) * 2.0 - 1.0).abs() - 1.0)).abs() < 1e-9, "um quarto de ciclo: {}", at(249));
        assert!(at(499) < -0.99, "meio ciclo deveria estar no vale: {}", at(499));
        assert!(at(998) > 0.99, "fim do ciclo deveria estar no pico: {}", at(998));
    }

    #[test]
    fn pcm_normalizes_the_peak() {
        let s = vec![2.0f64, -2.0, 0.5];
        let mut o = vec![0i16; 3];
        unsafe { flow_pcm16(s.as_ptr(), 3, o.as_mut_ptr(), 0.85) };
        assert_eq!(o[0], (0.85 * 32767.0) as i16);
        assert_eq!(o[1], -(0.85 * 32767.0) as i16);
    }

    #[test]
    fn mix_add_clips_at_the_end_and_ignores_null() {
        let mut d = vec![1.0f64; 4];
        let s = vec![1.0f64, 2.0, 3.0];
        unsafe {
            flow_mix_add(d.as_mut_ptr(), 4, s.as_ptr(), 3, 2);
            flow_mix_add(std::ptr::null_mut(), 4, s.as_ptr(), 3, 0);
        }
        assert_eq!(d, vec![1.0, 1.0, 2.0, 3.0]);
    }
}
