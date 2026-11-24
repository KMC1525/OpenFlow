//! Utilidades (portadas de `openflow/util.py`): ids, datas, nomes de arquivo seguros, mesclagem de JSON e escrita atômica.

use serde_json::{Map, Value};
use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};

static COUNTER: AtomicU64 = AtomicU64::new(0);

/// Id aleatório: prefixo + 10 dígitos hexadecimais (como `secrets.token_hex(5)`).
pub fn new_id(prefix: &str) -> String {
    let mut h = RandomState::new().build_hasher();
    h.write_u64(COUNTER.fetch_add(1, Ordering::Relaxed));
    h.write_u128(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0));
    h.write_u32(std::process::id());
    format!("{prefix}{:010x}", h.finish() & 0xff_ffff_ffff)
}

/// Data (UTC) de um número de dias desde 1970-01-01.
fn civil(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

pub fn iso_from_secs(secs: i64) -> String {
    let (y, m, d) = civil(secs.div_euclid(86_400));
    let t = secs.rem_euclid(86_400);
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}+00:00", t / 3600, (t % 3600) / 60, t % 60)
}

pub fn now_secs() -> i64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
}

pub fn now_iso() -> String {
    iso_from_secs(now_secs())
}

pub fn now_f64() -> f64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0)
}

/// Nome de arquivo seguro (sem diretórios, sem caracteres de controle), como `safe_filename` do Python.
pub fn safe_filename(name: &str, default: &str) -> String {
    let n = name.replace('\\', "/");
    let base = n.rsplit('/').next().unwrap_or("");
    let cleaned: String = base.chars().map(|c| if (c as u32) < 0x20 || matches!(c, '<' | '>' | ':' | '"' | '|' | '?' | '*') { '_' } else { c }).collect();
    let trimmed = cleaned.trim_matches(|c| c == '.' || c == ' ');
    let cut: String = trimmed.chars().take(120).collect();
    if cut.is_empty() { default.to_string() } else { cut }
}

/// Mescla `patch` em `base` recursivamente (devolve um novo objeto; a ordem das chaves é a de `base` e as novas vão ao fim).
pub fn deep_merge(base: &Value, patch: &Value) -> Value {
    let (Some(b), Some(p)) = (base.as_object(), patch.as_object()) else { return patch.clone() };
    let mut out: Map<String, Value> = b.clone();
    for (k, v) in p {
        let merged = match (out.get(k), v) {
            (Some(cur), Value::Object(_)) if cur.is_object() => deep_merge(cur, v),
            _ => v.clone(),
        };
        out.insert(k.clone(), merged);
    }
    Value::Object(out)
}

/// Texto do JSON sem bytes nulos (o resto dos «surrogates» soltos já não chega: o analisador de JSON do Rust os recusa). Erro se aninhado fundo demais.
pub fn clean_json(v: &Value, depth: u32) -> Result<Value, String> {
    match v {
        Value::String(s) => Ok(Value::String(if s.contains('\0') { s.replace('\0', "") } else { s.clone() })),
        Value::Array(a) => {
            if depth > 100 {
                return Err("JSON aninhado fundo demais".into());
            }
            Ok(Value::Array(a.iter().map(|x| clean_json(x, depth + 1)).collect::<Result<_, _>>()?))
        }
        Value::Object(o) => {
            if depth > 100 {
                return Err("JSON aninhado fundo demais".into());
            }
            let mut m = Map::new();
            for (k, x) in o {
                m.insert(if k.contains('\0') { k.replace('\0', "") } else { k.clone() }, clean_json(x, depth + 1)?);
            }
            Ok(Value::Object(m))
        }
        other => Ok(other.clone()),
    }
}

pub fn read_json(path: &Path) -> Option<Value> {
    let txt = std::fs::read_to_string(path).ok()?;
    serde_json::from_str(&txt).ok()
}

/// Escrita atômica (arquivo temporário + troca), com `indent=2` como o Python; `private`: só o dono lê (0600).
pub fn write_json(path: &Path, data: &Value, private: bool) -> std::io::Result<()> {
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let tmp = path.with_file_name(format!(".tmp-{}.json", new_id("")));
    let txt = serde_json::to_string_pretty(data).unwrap_or_default();
    std::fs::write(&tmp, txt)?;
    #[cfg(unix)]
    if private {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&tmp, std::fs::Permissions::from_mode(0o600));
    }
    #[cfg(not(unix))]
    let _ = private;
    std::fs::rename(&tmp, path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp);
        e
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn ids_and_dates() {
        let id = new_id("u_");
        assert!(id.starts_with("u_") && id.len() == 12, "{id}");
        assert_ne!(new_id("x"), new_id("x"));
        assert_eq!(iso_from_secs(0), "1970-01-01T00:00:00+00:00");
        assert_eq!(iso_from_secs(1_700_000_000), "2023-11-14T22:13:20+00:00");
        assert_eq!(iso_from_secs(951_782_400), "2000-02-29T00:00:00+00:00");
    }

    #[test]
    fn safe_names() {
        assert_eq!(safe_filename("../../etc/passwd", "f"), "passwd");
        assert_eq!(safe_filename("a:b*c?.txt", "f"), "a_b_c_.txt");
        assert_eq!(safe_filename("  ..  ", "arquivo"), "arquivo");
        assert_eq!(safe_filename("C:\\x\\foto.png", "f"), "foto.png");
        assert_eq!(safe_filename(&"a".repeat(300), "f").len(), 120);
    }

    #[test]
    fn merge_keeps_order_and_recurses() {
        let base = json!({"a": 1, "b": {"x": 1, "y": 2}, "c": 3});
        let patch = json!({"b": {"y": 9, "z": 5}, "d": 4, "a": 7});
        let m = deep_merge(&base, &patch);
        assert_eq!(serde_json::to_string(&m).unwrap(), r#"{"a":7,"b":{"x":1,"y":9,"z":5},"c":3,"d":4}"#);
    }

    #[test]
    fn clean_removes_nul_and_limits_depth() {
        assert_eq!(clean_json(&json!({"a\u{0}": "x\u{0}y"}), 0).unwrap(), json!({"a": "xy"}));
        let mut v = json!(1);
        for _ in 0..120 {
            v = json!([v]);
        }
        assert!(clean_json(&v, 0).is_err());
    }
}
