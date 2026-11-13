//! Análise de mídia e de fluxos do núcleo (v0.17, interface 4): níveis de áudio, silêncios, picos, andamento (BPM) e batidas, atividade de quadros (cortes de cena),
//! forma de onda e ordem de execução de grafos (Canvas).
//!
//! O Studio e o Canvas gastavam a maior parte do tempo em laços de Python sobre milhões de amostras (ou sobre centenas de nós e conexões). Aqui os mesmos cálculos
//! rodam sobre buffers contínuos, sem criar um objeto Python por amostra. Cada função tem o equivalente em Python (`openflow/native/__init__.py`) com as mesmas contas,
//! na mesma ordem — os testes conferem os dois lados, inclusive com entradas aleatórias.
//!
//! Segurança: toda função valida ponteiros nulos e tamanhos, nunca escreve além de `cap` e não faz E/S.

use std::collections::VecDeque;

unsafe fn sl<'a, T>(p: *const T, n: usize) -> Option<&'a [T]> {
    if p.is_null() || n == 0 {
        None
    } else {
        Some(std::slice::from_raw_parts(p, n))
    }
}

unsafe fn sm<'a, T>(p: *mut T, n: usize) -> Option<&'a mut [T]> {
    if p.is_null() || n == 0 {
        None
    } else {
        Some(std::slice::from_raw_parts_mut(p, n))
    }
}

/// Nível de volume (dB, RMS) de cada janela de `win` amostras de um PCM de 16 bits mono. A última janela pode ser parcial.
/// Devolve quantas janelas existem (escreve no máximo `cap`). Silêncio absoluto vale -90 dB.
#[no_mangle]
pub unsafe extern "C" fn flow_audio_levels(pcm: *const i16, n: usize, win: usize, out: *mut f64, cap: usize) -> i64 {
    let (Some(s), Some(o)) = (sl(pcm, n), sm(out, cap)) else { return -1 };
    if win == 0 {
        return -1;
    }
    let count = (n + win - 1) / win;
    for (k, chunk) in s.chunks(win).enumerate() {
        if k >= o.len() {
            break;
        }
        let mut ss: i64 = 0;
        for &v in chunk {
            let x = v as i64;
            ss += x * x;
        }
        let rms = ((ss as f64) / (chunk.len() as f64)).sqrt() / 32768.0;
        o[k] = if rms <= 0.0 { -90.0 } else { (20.0 * rms.log10()).max(-90.0) };
    }
    count as i64
}

/// Trechos de silêncio: sequências de janelas abaixo de `thresh_db` que somam pelo menos `min_len` segundos. Escreve pares (início, fim) em segundos;
/// devolve quantos pares existem (escreve no máximo `cap_pairs`).
#[no_mangle]
pub unsafe extern "C" fn flow_silence_ranges(levels: *const f64, n: usize, win_s: f64, thresh_db: f64, min_len: f64, out: *mut f64, cap_pairs: usize) -> i64 {
    let (Some(l), Some(o)) = (sl(levels, n), sm(out, cap_pairs * 2)) else { return -1 };
    let mut pairs = 0usize;
    let mut start: Option<usize> = None;
    let mut push = |a: usize, b: usize, pairs: &mut usize| {
        let (t0, t1) = (a as f64 * win_s, b as f64 * win_s);
        if t1 - t0 >= min_len - 1e-9 {
            if *pairs < cap_pairs {
                o[*pairs * 2] = t0;
                o[*pairs * 2 + 1] = t1;
            }
            *pairs += 1;
        }
    };
    for (i, &v) in l.iter().enumerate() {
        if v < thresh_db {
            if start.is_none() {
                start = Some(i);
            }
        } else if let Some(a) = start.take() {
            push(a, i, &mut pairs);
        }
    }
    if let Some(a) = start {
        push(a, l.len(), &mut pairs);
    }
    pairs as i64
}

/// Os `limit` pontos mais altos de uma curva, com pelo menos `min_gap` segundos entre dois escolhidos. Escreve pares (instante do centro da janela, valor), do maior para o menor;
/// devolve quantos achou. Empates: o índice menor primeiro.
#[no_mangle]
pub unsafe extern "C" fn flow_pick_peaks(vals: *const f64, n: usize, win_s: f64, min_gap: f64, limit: usize, out: *mut f64) -> i64 {
    let (Some(v), Some(o)) = (sl(vals, n), sm(out, limit * 2)) else { return -1 };
    let mut idx: Vec<usize> = (0..v.len()).collect();
    idx.sort_by(|&a, &b| v[b].partial_cmp(&v[a]).unwrap_or(std::cmp::Ordering::Equal).then(a.cmp(&b)));
    let mut taken: Vec<f64> = Vec::new();
    let mut k = 0usize;
    for i in idx {
        if k >= limit {
            break;
        }
        let t = (i as f64 + 0.5) * win_s;
        if taken.iter().all(|u| (t - u).abs() >= min_gap - 1e-9) {
            taken.push(t);
            o[k * 2] = t;
            o[k * 2 + 1] = v[i];
            k += 1;
        }
    }
    k as i64
}

/// Envelope de início de notas: subida positiva do nível (dB) de uma janela para a seguinte. `env[0] = 0`.
#[no_mangle]
pub unsafe extern "C" fn flow_onset_env(levels: *const f64, n: usize, out: *mut f64) -> i64 {
    let (Some(l), Some(o)) = (sl(levels, n), sm(out, n)) else { return -1 };
    o[0] = 0.0;
    for i in 1..l.len() {
        o[i] = (l[i] - l[i - 1]).max(0.0);
    }
    n as i64
}

/// Andamento: autocorrelação do envelope (passo `hop_s`) entre `min_bpm` e `max_bpm`, com preferência suave por ~120 BPM (evita a metade/dobro).
/// Escreve `[bpm, fase_em_segundos, confiança]`. Devolve 1 se achou, 0 se o sinal é curto/sem pulso.
#[no_mangle]
pub unsafe extern "C" fn flow_tempo(env: *const f64, n: usize, hop_s: f64, min_bpm: f64, max_bpm: f64, out: *mut f64) -> i64 {
    let (Some(e), Some(o)) = (sl(env, n), sm(out, 3)) else { return -1 };
    let lag_min = (60.0 / max_bpm / hop_s).floor().max(1.0) as usize;
    let lag_max = (60.0 / min_bpm / hop_s).ceil() as usize;
    if lag_max <= lag_min || e.len() < lag_max * 2 {
        return 0;
    }
    let mut scores: Vec<f64> = Vec::with_capacity(lag_max - lag_min + 1);
    for lag in lag_min..=lag_max {
        let mut s = 0.0f64;
        for i in 0..e.len() - lag {
            s += e[i] * e[i + lag];
        }
        let bpm = 60.0 / (lag as f64 * hop_s);
        let prior = (-0.5 * ((bpm / 120.0).log2() / 0.8).powi(2)).exp();
        scores.push(s / ((e.len() - lag) as f64) * prior);
    }
    let mean = scores.iter().sum::<f64>() / scores.len() as f64;
    let mut best = 0usize;
    for (i, &s) in scores.iter().enumerate() {
        if s > scores[best] {
            best = i;
        }
    }
    if scores[best] <= 0.0 {
        return 0;
    }
    // refina o atraso com uma parábola pelos vizinhos
    let mut lag_f = (lag_min + best) as f64;
    if best > 0 && best + 1 < scores.len() {
        let (a, b, c) = (scores[best - 1], scores[best], scores[best + 1]);
        let d = a - 2.0 * b + c;
        if d.abs() > 1e-12 {
            lag_f += (0.5 * (a - c) / d).clamp(-0.5, 0.5);
        }
    }
    let period = lag_f; // em janelas
    let offs = period.ceil() as usize;
    let (mut best_off, mut best_sum) = (0usize, -1.0f64);
    for off in 0..offs {
        let mut sum = 0.0f64;
        let mut k = 0usize;
        loop {
            let pos = off as f64 + k as f64 * period;
            let ix = pos.round() as usize;
            if ix >= e.len() {
                break;
            }
            sum += e[ix];
            k += 1;
        }
        if sum > best_sum {
            best_sum = sum;
            best_off = off;
        }
    }
    o[0] = 60.0 / (period * hop_s);
    o[1] = best_off as f64 * hop_s;
    o[2] = if mean > 0.0 { scores[best] / mean } else { 0.0 };
    1
}

/// Atividade visual: diferença média absoluta (0 a 1) de cada quadro para o anterior. `frames` são `nframes` quadros em cinza de `fsize` bytes cada.
#[no_mangle]
pub unsafe extern "C" fn flow_frame_activity(frames: *const u8, nframes: usize, fsize: usize, out: *mut f64) -> i64 {
    let (Some(f), Some(o)) = (sl(frames, nframes.saturating_mul(fsize)), sm(out, nframes)) else { return -1 };
    if fsize == 0 {
        return -1;
    }
    o[0] = 0.0;
    for i in 1..nframes {
        let (a, b) = (&f[(i - 1) * fsize..i * fsize], &f[i * fsize..(i + 1) * fsize]);
        let mut d: u64 = 0;
        for k in 0..fsize {
            d += (a[k] as i32 - b[k] as i32).unsigned_abs() as u64;
        }
        o[i] = d as f64 / (fsize as f64 * 255.0);
    }
    nframes as i64
}

/// Trocas de cena numa curva de atividade: máximos locais acima de `max(min_abs, média + k·desvio)`, com `min_gap` segundos entre elas. Escreve os instantes em ordem crescente.
#[no_mangle]
pub unsafe extern "C" fn flow_scene_cuts(act: *const f64, n: usize, step_s: f64, k: f64, min_abs: f64, min_gap: f64, out: *mut f64, cap: usize) -> i64 {
    let (Some(a), Some(o)) = (sl(act, n), sm(out, cap)) else { return -1 };
    let mean = a.iter().sum::<f64>() / a.len() as f64;
    let var = a.iter().map(|v| (v - mean) * (v - mean)).sum::<f64>() / a.len() as f64;
    let thr = min_abs.max(mean + k * var.sqrt());
    let mut cand: Vec<usize> = Vec::new();
    for i in 1..a.len() {
        let next = if i + 1 < a.len() { a[i + 1] } else { f64::MIN };
        if a[i] > thr && a[i] >= a[i - 1] && a[i] > next {
            cand.push(i);
        }
    }
    cand.sort_by(|&x, &y| a[y].partial_cmp(&a[x]).unwrap_or(std::cmp::Ordering::Equal).then(x.cmp(&y)));
    let mut taken: Vec<f64> = Vec::new();
    for i in cand {
        let t = i as f64 * step_s;
        if taken.iter().all(|u| (t - u).abs() >= min_gap - 1e-9) {
            taken.push(t);
        }
    }
    taken.sort_by(|x, y| x.partial_cmp(y).unwrap_or(std::cmp::Ordering::Equal));
    for (i, t) in taken.iter().enumerate() {
        if i < o.len() {
            o[i] = *t;
        }
    }
    taken.len() as i64
}

/// Forma de onda para desenhar nos clipes: o pico absoluto (0 a 1) de cada um de `buckets` blocos iguais.
#[no_mangle]
pub unsafe extern "C" fn flow_waveform(pcm: *const i16, n: usize, buckets: usize, out: *mut f64) -> i64 {
    let (Some(s), Some(o)) = (sl(pcm, n), sm(out, buckets)) else { return -1 };
    for b in 0..buckets {
        let (a, z) = (b * n / buckets, ((b + 1) * n / buckets).max(b * n / buckets + 1).min(n));
        let mut m: i32 = 0;
        for &v in &s[a.min(n - 1)..z] {
            m = m.max((v as i32).abs());
        }
        o[b] = (m as f64 / 32768.0).min(1.0);
    }
    buckets as i64
}

/// Ordem de execução de um grafo (Canvas): Kahn com fila FIFO — a mesma ordem estável do Python — e o nível de cada nó (caminho mais longo desde uma raiz;
/// nós do mesmo nível não dependem um do outro). Devolve quantos nós foram ordenados (menos que `n` = há ciclo). Conexões com índice inválido são ignoradas.
#[no_mangle]
pub unsafe extern "C" fn flow_topo(n: usize, from: *const u32, to: *const u32, m: usize, order: *mut u32, level: *mut u32) -> i64 {
    let (Some(o), Some(lv)) = (sm(order, n), sm(level, n)) else { return -1 };
    let edges: Vec<(usize, usize)> = match (sl(from, m), sl(to, m)) {
        (Some(f), Some(t)) => f.iter().zip(t.iter()).map(|(&a, &b)| (a as usize, b as usize)).filter(|&(a, b)| a < n && b < n).collect(),
        _ => Vec::new(),
    };
    let mut indeg = vec![0u32; n];
    let mut adj: Vec<Vec<usize>> = vec![Vec::new(); n];
    for &(a, b) in &edges {
        adj[a].push(b);
        indeg[b] += 1;
    }
    for v in lv.iter_mut() {
        *v = 0;
    }
    let mut q: VecDeque<usize> = (0..n).filter(|&i| indeg[i] == 0).collect();
    let mut k = 0usize;
    while let Some(cur) = q.pop_front() {
        o[k] = cur as u32;
        k += 1;
        for &nx in &adj[cur] {
            if lv[nx] < lv[cur] + 1 {
                lv[nx] = lv[cur] + 1;
            }
            indeg[nx] -= 1;
            if indeg[nx] == 0 {
                q.push_back(nx);
            }
        }
    }
    k as i64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn levels_of_a_full_scale_square_wave_are_near_zero_db() {
        let pcm: Vec<i16> = (0..800).map(|i| if i % 2 == 0 { 32767 } else { -32767 }).collect();
        let mut out = vec![0.0f64; 8];
        let n = unsafe { flow_audio_levels(pcm.as_ptr(), pcm.len(), 100, out.as_mut_ptr(), out.len()) };
        assert_eq!(n, 8);
        assert!(out.iter().all(|v| *v > -0.1 && *v <= 0.0));
        let zero = vec![0i16; 100];
        let mut o1 = vec![0.0f64; 1];
        unsafe { flow_audio_levels(zero.as_ptr(), 100, 100, o1.as_mut_ptr(), 1) };
        assert_eq!(o1[0], -90.0);
    }

    #[test]
    fn silences_need_the_minimum_length() {
        let lv = [-20.0, -80.0, -80.0, -80.0, -20.0, -80.0, -20.0];
        let mut out = [0.0f64; 8];
        let k = unsafe { flow_silence_ranges(lv.as_ptr(), lv.len(), 0.5, -50.0, 1.0, out.as_mut_ptr(), 4) };
        assert_eq!(k, 1);
        assert_eq!((out[0], out[1]), (0.5, 2.0));
    }

    #[test]
    fn peaks_keep_their_distance() {
        let v = [1.0, 9.0, 8.0, 2.0, 7.0, 1.0];
        let mut out = [0.0f64; 6];
        let k = unsafe { flow_pick_peaks(v.as_ptr(), v.len(), 1.0, 2.0, 3, out.as_mut_ptr()) };
        assert_eq!(k, 2);
        assert_eq!(out[1], 9.0);
        assert_eq!(out[3], 7.0);
    }

    #[test]
    fn tempo_finds_a_120_bpm_pulse() {
        let hop = 0.01;
        let mut env = vec![0.0f64; 2000];
        let mut i = 7usize;
        while i < env.len() {
            env[i] = 10.0;
            i += 50; // 0,5 s = 120 BPM
        }
        let mut out = [0.0f64; 3];
        let r = unsafe { flow_tempo(env.as_ptr(), env.len(), hop, 70.0, 200.0, out.as_mut_ptr()) };
        assert_eq!(r, 1);
        assert!((out[0] - 120.0).abs() < 1.5, "bpm {}", out[0]);
        assert!((out[1] - 0.07).abs() < 0.02, "fase {}", out[1]);
    }

    #[test]
    fn frame_activity_and_cuts() {
        let mut f = vec![0u8; 16 * 6];
        for i in 3..6 {
            for k in 0..16 {
                f[i * 16 + k] = 255;
            }
        }
        let mut act = vec![0.0f64; 6];
        unsafe { flow_frame_activity(f.as_ptr(), 6, 16, act.as_mut_ptr()) };
        assert_eq!(act[3], 1.0);
        let mut cuts = [0.0f64; 4];
        let k = unsafe { flow_scene_cuts(act.as_ptr(), 6, 0.25, 1.0, 0.3, 0.5, cuts.as_mut_ptr(), 4) };
        assert_eq!(k, 1);
        assert_eq!(cuts[0], 0.75);
    }

    #[test]
    fn topo_orders_and_detects_cycles() {
        let (from, to) = ([0u32, 1, 0], [1u32, 2, 2]);
        let (mut o, mut lv) = ([0u32; 3], [0u32; 3]);
        let k = unsafe { flow_topo(3, from.as_ptr(), to.as_ptr(), 3, o.as_mut_ptr(), lv.as_mut_ptr()) };
        assert_eq!((k, o, lv), (3, [0, 1, 2], [0, 1, 2]));
        let (from, to) = ([0u32, 1], [1u32, 0]);
        let k = unsafe { flow_topo(2, from.as_ptr(), to.as_ptr(), 2, o.as_mut_ptr(), lv.as_mut_ptr()) };
        assert_eq!(k, 0);
    }

    #[test]
    fn waveform_takes_the_peak_of_each_bucket() {
        let pcm = [0i16, 100, -300, 0, 16384, 0, 0, 0];
        let mut out = [0.0f64; 4];
        unsafe { flow_waveform(pcm.as_ptr(), 8, 4, out.as_mut_ptr()) };
        assert!((out[0] - 100.0 / 32768.0).abs() < 1e-12);
        assert!((out[1] - 300.0 / 32768.0).abs() < 1e-12);
        assert!((out[2] - 0.5).abs() < 1e-12);
    }
}
