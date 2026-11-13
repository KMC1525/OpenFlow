//! Leitura rápida do CABEÇALHO de modelos locais (sem carregar os pesos): GGUF (llama.cpp) e safetensors (diffusers/transformers).
//!
//! Com isso o OpenFlow sabe, em milissegundos e antes de carregar, o tamanho do modelo, a arquitetura, o nº de camadas, a janela de contexto de treino, a quantização
//! dominante e quanto o cache de atenção custa por token — e decide camadas na GPU, janela de contexto, threads e estratégia de descarga com números reais.

use crate::util::{parse_json, put, Obj, Val};
use std::fs::File;
use std::io::{BufReader, Read, Seek, SeekFrom};

const MAX_STR: u64 = 1 << 24;

fn rd<R: Read>(r: &mut R, n: usize) -> Option<Vec<u8>> {
    let mut b = vec![0u8; n];
    r.read_exact(&mut b).ok()?;
    Some(b)
}
fn u32le<R: Read>(r: &mut R) -> Option<u32> {
    Some(u32::from_le_bytes(rd(r, 4)?.try_into().ok()?))
}
fn u64le<R: Read>(r: &mut R) -> Option<u64> {
    Some(u64::from_le_bytes(rd(r, 8)?.try_into().ok()?))
}
fn gstr<R: Read>(r: &mut R) -> Option<String> {
    let n = u64le(r)?;
    if n > MAX_STR {
        return None;
    }
    Some(String::from_utf8_lossy(&rd(r, n as usize)?).into_owned())
}

#[derive(Default)]
struct Meta {
    arch: String,
    name: String,
    ctx: i64,
    layers: i64,
    embd: i64,
    heads: i64,
    heads_kv: i64,
    ff: i64,
    key_len: i64,
    file_type: i64,
    vocab: i64,
    experts: i64,
}

/// Bytes de um valor escalar do GGUF (None para string/array).
fn scalar_size(t: u32) -> Option<u64> {
    Some(match t {
        0 | 1 | 7 => 1,
        2 | 3 => 2,
        4 | 5 | 6 => 4,
        10 | 11 | 12 => 8,
        _ => return None,
    })
}

fn read_scalar<R: Read>(r: &mut R, t: u32) -> Option<f64> {
    let b = rd(r, scalar_size(t)? as usize)?;
    Some(match t {
        0 | 7 => b[0] as f64,
        1 => b[0] as i8 as f64,
        2 => u16::from_le_bytes([b[0], b[1]]) as f64,
        3 => i16::from_le_bytes([b[0], b[1]]) as f64,
        4 => u32::from_le_bytes(b[..4].try_into().ok()?) as f64,
        5 => i32::from_le_bytes(b[..4].try_into().ok()?) as f64,
        6 => f32::from_le_bytes(b[..4].try_into().ok()?) as f64,
        10 => u64::from_le_bytes(b[..8].try_into().ok()?) as f64,
        11 => i64::from_le_bytes(b[..8].try_into().ok()?) as f64,
        _ => f64::from_le_bytes(b[..8].try_into().ok()?),
    })
}

fn ggml_name(t: u32) -> &'static str {
    match t {
        0 => "F32", 1 => "F16", 2 => "Q4_0", 3 => "Q4_1", 6 => "Q5_0", 7 => "Q5_1", 8 => "Q8_0", 9 => "Q8_1", 10 => "Q2_K", 11 => "Q3_K", 12 => "Q4_K", 13 => "Q5_K",
        14 => "Q6_K", 15 => "Q8_K", 16 => "IQ2_XXS", 17 => "IQ2_XS", 18 => "IQ3_XXS", 19 => "IQ1_S", 20 => "IQ4_NL", 21 => "IQ3_S", 22 => "IQ2_S", 23 => "IQ4_XS",
        24 => "I8", 25 => "I16", 26 => "I32", 27 => "I64", 28 => "F64", 29 => "IQ1_M", 30 => "BF16", _ => "?",
    }
}

fn gguf(path: &str, size: u64) -> Option<String> {
    let mut r = BufReader::with_capacity(1 << 20, File::open(path).ok()?);
    if rd(&mut r, 4)? != b"GGUF" {
        return None;
    }
    let version = u32le(&mut r)?;
    if !(2..=3).contains(&version) {
        return None;
    }
    let n_tensors = u64le(&mut r)?;
    let n_kv = u64le(&mut r)?;
    if n_kv > 1_000_000 || n_tensors > 10_000_000 {
        return None;
    }
    let mut m = Meta::default();
    for _ in 0..n_kv {
        let key = gstr(&mut r)?;
        let t = u32le(&mut r)?;
        let wanted = |suffix: &str| key.ends_with(suffix);
        match t {
            8 => {
                let v = gstr(&mut r)?;
                if key == "general.architecture" {
                    m.arch = v;
                } else if key == "general.name" {
                    m.name = v;
                }
            }
            9 => {
                let et = u32le(&mut r)?;
                let len = u64le(&mut r)?;
                if key == "tokenizer.ggml.tokens" {
                    m.vocab = len as i64;
                }
                if et == 8 {
                    for _ in 0..len {
                        let n = u64le(&mut r)?;
                        if n > MAX_STR {
                            return None;
                        }
                        r.seek_relative(n as i64).ok()?;
                    }
                } else {
                    let each = scalar_size(et)?;
                    r.seek_relative((each.checked_mul(len)?) as i64).ok()?;
                }
            }
            _ => {
                let v = read_scalar(&mut r, t)? as i64;
                if wanted(".context_length") { m.ctx = v }
                else if wanted(".block_count") { m.layers = v }
                else if wanted(".embedding_length") { m.embd = v }
                else if wanted(".attention.head_count") { m.heads = v }
                else if wanted(".attention.head_count_kv") { m.heads_kv = v }
                else if wanted(".feed_forward_length") { m.ff = v }
                else if wanted(".attention.key_length") { m.key_len = v }
                else if wanted(".expert_count") { m.experts = v }
                else if key == "general.file_type" { m.file_type = v }
            }
        }
    }
    // tensores: parâmetros totais e a quantização dominante (por nº de elementos)
    let mut by_type: Vec<(u32, f64)> = Vec::new();
    let mut params: f64 = 0.0;
    for _ in 0..n_tensors {
        let n = u64le(&mut r)?;
        if n > 4096 {
            return None;
        }
        r.seek_relative(n as i64).ok()?;
        let nd = u32le(&mut r)?;
        if nd > 8 {
            return None;
        }
        let mut el: f64 = 1.0;
        for _ in 0..nd {
            el *= u64le(&mut r)? as f64;
        }
        let ty = u32le(&mut r)?;
        let _off = u64le(&mut r)?;
        params += el;
        match by_type.iter_mut().find(|(t, _)| *t == ty) {
            Some(e) => e.1 += el,
            None => by_type.push((ty, el)),
        }
    }
    let dom = by_type.iter().cloned().fold((0u32, -1.0f64), |a, b| if b.1 > a.1 { b } else { a }).0;
    let heads = m.heads.max(1);
    let heads_kv = if m.heads_kv > 0 { m.heads_kv } else { heads };
    let head_dim = if m.key_len > 0 { m.key_len } else if m.embd > 0 { m.embd / heads } else { 0 };
    let kv_per_token = 2 * m.layers.max(0) * heads_kv * head_dim * 2; // K e V em f16
    let _ = r.seek(SeekFrom::Current(0));
    Some(
        Obj::new()
            .s("format", "gguf").i("version", version as i64).i("bytes", size as i64).s("arch", &m.arch).s("name", &m.name)
            .i("ctx_train", m.ctx).i("layers", m.layers).i("embd", m.embd).i("heads", m.heads).i("heads_kv", heads_kv).i("ff", m.ff)
            .i("experts", m.experts).i("vocab", m.vocab).i("tensors", n_tensors as i64).f("params", params).s("quant", ggml_name(dom))
            .i("file_type", m.file_type).i("kv_bytes_per_token", kv_per_token)
            .end(),
    )
}

fn st_bytes(dt: &str) -> f64 {
    match dt {
        "F64" | "I64" | "U64" => 8.0,
        "F32" | "I32" | "U32" => 4.0,
        "F16" | "BF16" | "I16" | "U16" => 2.0,
        "I8" | "U8" | "BOOL" | "F8_E4M3" | "F8_E5M2" => 1.0,
        _ => 2.0,
    }
}

fn safetensors(path: &str, size: u64) -> Option<String> {
    let mut f = File::open(path).ok()?;
    let mut lb = [0u8; 8];
    f.read_exact(&mut lb).ok()?;
    let n = u64::from_le_bytes(lb);
    if n == 0 || n > (1 << 28) || n + 8 > size {
        return None;
    }
    let mut hb = vec![0u8; n as usize];
    f.read_exact(&mut hb).ok()?;
    let v = parse_json(&hb)?;
    let items = match &v {
        Val::Obj(o) => o,
        _ => return None,
    };
    let (mut params, mut tensors) = (0.0f64, 0i64);
    let mut dts: Vec<(String, f64)> = Vec::new();
    for (k, t) in items {
        if k == "__metadata__" {
            continue;
        }
        let dt = t.get("dtype").and_then(|d| d.as_str()).unwrap_or("F16").to_string();
        let mut el = 1.0f64;
        if let Some(Val::Arr(sh)) = t.get("shape") {
            for d in sh {
                el *= d.as_f64().unwrap_or(1.0);
            }
        }
        params += el;
        tensors += 1;
        match dts.iter_mut().find(|(d, _)| *d == dt) {
            Some(e) => e.1 += el,
            None => dts.push((dt, el)),
        }
    }
    let dom = dts.iter().fold(("?".to_string(), -1.0f64), |a, b| if b.1 > a.1 { b.clone() } else { a }).0;
    let weight_bytes: f64 = dts.iter().map(|(d, e)| st_bytes(d) * e).sum();
    Some(Obj::new().s("format", "safetensors").i("bytes", size as i64).i("tensors", tensors).f("params", params).s("dtype", &dom).f("weight_bytes", weight_bytes).end())
}

/// Cabeçalho do modelo em JSON (`format`: gguf | safetensors | unknown). Devolve o tamanho do JSON, ou -1 se o arquivo não abre.
#[no_mangle]
pub unsafe extern "C" fn flow_model_info(path: *const u8, path_len: usize, out: *mut u8, cap: usize) -> i64 {
    if path.is_null() || path_len == 0 || path_len > 4096 {
        return -1;
    }
    let p = match std::str::from_utf8(std::slice::from_raw_parts(path, path_len)) {
        Ok(p) => p,
        Err(_) => return -1,
    };
    let size = match std::fs::metadata(p) {
        Ok(m) if m.is_file() => m.len(),
        _ => return -1,
    };
    let lower = p.to_ascii_lowercase();
    let s = if lower.ends_with(".gguf") { gguf(p, size) } else if lower.ends_with(".safetensors") { safetensors(p, size) } else { gguf(p, size).or_else(|| safetensors(p, size)) };
    put(out, cap, &s.unwrap_or_else(|| Obj::new().s("format", "unknown").i("bytes", size as i64).end()))
}
