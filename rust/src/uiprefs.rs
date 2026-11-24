//! Preferências de interface (`settings.ui`) e exportação/importação das configurações (portado de `openflow/uiprefs.py`).

use serde_json::{json, Map, Value};

const THEMES: [&str; 3] = ["dark", "light", "auto"];
const DENSITIES: [&str; 2] = ["comfortable", "compact"];
const MOTIONS: [&str; 3] = ["auto", "reduce", "full"];
const FONTS: [&str; 10] = ["system", "inter", "humanist", "rounded", "verdana", "readable", "book", "serif", "mono", "custom"];
const LANGS: [&str; 3] = ["auto", "pt-BR", "en"];
pub const RESETTABLE: [&str; 3] = ["ui", "canvas", "performance"];
pub const EXPORT_SCHEMA: &str = "openflow.settings.v1";
const EXPORT_SECTIONS: [&str; 6] = ["language", "ui", "canvas", "performance", "active", "media"];

pub fn default_ui() -> Value {
    json!({"theme": "dark", "accent": "", "scale": 100, "density": "comfortable", "motion": "auto", "font": "system", "font_custom": "", "shortcuts": true, "welcome_done": false})
}

fn choice(v: Option<&Value>, allowed: &[&str], default: &str) -> String {
    match v.and_then(|x| x.as_str()) {
        Some(s) if allowed.contains(&s) => s.to_string(),
        _ => default.to_string(),
    }
}

fn is_hex(s: &str) -> bool {
    let b = s.strip_prefix('#').unwrap_or("");
    (b.len() == 3 || b.len() == 6) && s.starts_with('#') && b.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
}

pub fn normalize_accent(v: Option<&Value>) -> String {
    let s = match v {
        Some(Value::String(s)) => s.trim().to_lowercase(),
        Some(Value::Null) | None => String::new(),
        Some(Value::Bool(false)) => String::new(),
        Some(other) => other.to_string().trim().to_lowercase(),
    };
    if !is_hex(&s) {
        return String::new();
    }
    if s.len() == 4 {
        let mut o = String::from("#");
        for c in s[1..].chars() {
            o.push(c);
            o.push(c);
        }
        o
    } else {
        s
    }
}

pub fn normalize_font_name(v: Option<&Value>) -> String {
    let Some(Value::String(s)) = v else { return String::new() };
    let kept: String = s.chars().filter(|c| c.is_alphanumeric() || *c == '_' || *c == ' ' || *c == '.' || *c == '-').collect();
    let joined = kept.split_whitespace().collect::<Vec<_>>().join(" ");
    joined.chars().take(60).collect()
}

pub fn normalize_scale(v: Option<&Value>) -> i64 {
    let n = match v {
        Some(Value::Number(n)) => n.as_f64().unwrap_or(100.0),
        Some(Value::String(s)) => s.trim().parse::<f64>().unwrap_or(100.0),
        Some(Value::Bool(b)) => if *b { 1.0 } else { 0.0 },
        _ => 100.0,
    };
    if !n.is_finite() {
        return 100;
    }
    let step = ((n / 5.0 + 0.5) as i64) * 5; // `int()` do Python trunca para zero, como o `as i64`
    step.clamp(50, 200)
}

/// Preferências válidas (todas as chaves presentes); o que for inválido volta ao padrão.
pub fn normalize_ui(data: Option<&Value>) -> Value {
    let empty = Map::new();
    let d = data.and_then(|x| x.as_object()).unwrap_or(&empty);
    let mut out = Map::new();
    out.insert("theme".into(), json!(choice(d.get("theme"), &THEMES, "dark")));
    out.insert("accent".into(), json!(normalize_accent(d.get("accent"))));
    out.insert("scale".into(), json!(normalize_scale(Some(d.get("scale").unwrap_or(&json!(100))))));
    out.insert("density".into(), json!(choice(d.get("density"), &DENSITIES, "comfortable")));
    out.insert("motion".into(), json!(choice(d.get("motion"), &MOTIONS, "auto")));
    out.insert("font".into(), json!(choice(d.get("font"), &FONTS, "system")));
    out.insert("font_custom".into(), json!(normalize_font_name(d.get("font_custom"))));
    out.insert("shortcuts".into(), json!(d.get("shortcuts") != Some(&Value::Bool(false))));
    out.insert("welcome_done".into(), json!(d.get("welcome_done") == Some(&Value::Bool(true))));
    Value::Object(out)
}

/// Configurações para levar a outro computador: preferências e o que dá para reaproveitar. Nunca chaves de API nem tokens.
pub fn export_settings(settings: &Value) -> Value {
    let mut out = Map::new();
    for k in EXPORT_SECTIONS {
        if let Some(v) = settings.get(k) {
            out.insert(k.into(), v.clone());
        }
    }
    let mut provs = Map::new();
    if let Some(p) = settings.get("providers").and_then(|x| x.as_object()) {
        for (pid, cfg) in p {
            if let Some(c) = cfg.as_object() {
                let mut m = Map::new();
                for k in ["model", "n_ctx"] {
                    if let Some(v) = c.get(k) {
                        if !v.is_null() && v != &json!("") {
                            m.insert(k.into(), v.clone());
                        }
                    }
                }
                provs.insert(pid.clone(), Value::Object(m));
            }
        }
    }
    out.insert("providers".into(), Value::Object(provs));
    json!({"schema": EXPORT_SCHEMA, "settings": Value::Object(out)})
}

/// Transforma um arquivo exportado em um patch seguro para `save_settings`.
pub fn import_patch(payload: &Value) -> Result<Value, String> {
    let ok = payload.get("schema").and_then(|s| s.as_str()) == Some(EXPORT_SCHEMA) && payload.get("settings").map(|s| s.is_object()).unwrap_or(false);
    if !ok {
        return Err("Este arquivo não é uma exportação de configurações do OpenFlow.".into());
    }
    let src = &payload["settings"];
    let mut patch = Map::new();
    for key in ["canvas", "performance"] {
        if src.get(key).map(|v| v.is_object()).unwrap_or(false) {
            patch.insert(key.into(), src[key].clone());
        }
    }
    if src.get("ui").map(|v| v.is_object()).unwrap_or(false) {
        patch.insert("ui".into(), normalize_ui(src.get("ui")));
    }
    if let Some(l) = src.get("language").and_then(|v| v.as_str()) {
        if LANGS.contains(&l) {
            patch.insert("language".into(), json!(l));
        }
    }
    if let Some(m) = src.get("media").and_then(|v| v.as_object()) {
        let mut mm = Map::new();
        for k in ["active", "models"] {
            if m.get(k).map(|v| v.is_object()).unwrap_or(false) {
                mm.insert(k.into(), m[k].clone());
            }
        }
        patch.insert("media".into(), Value::Object(mm));
    }
    if let Some(a) = src.get("active").and_then(|v| v.as_object()) {
        let mm: Map<String, Value> = a.iter().filter(|(_, v)| v.is_string()).map(|(k, v)| (k.clone(), v.clone())).collect();
        patch.insert("active".into(), Value::Object(mm));
    }
    if let Some(p) = src.get("providers").and_then(|v| v.as_object()) {
        let mm: Map<String, Value> = p.iter().filter_map(|(pid, cfg)| cfg.as_object().map(|c| {
            let f: Map<String, Value> = c.iter().filter(|(k, _)| k.as_str() == "model" || k.as_str() == "n_ctx").map(|(k, v)| (k.clone(), v.clone())).collect();
            (pid.clone(), Value::Object(f))
        })).collect();
        patch.insert("providers".into(), Value::Object(mm));
    }
    Ok(Value::Object(patch))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ui_falls_back_to_defaults() {
        let v = normalize_ui(Some(&json!({"theme": "nope", "accent": "#ABC", "scale": 137, "shortcuts": false, "font_custom": "Fira \"Code\";x"})));
        assert_eq!(v["theme"], "dark");
        assert_eq!(v["accent"], "#aabbcc");
        assert_eq!(v["scale"], 135);
        assert_eq!(v["shortcuts"], false);
        assert_eq!(v["font_custom"], "Fira Codex");
        assert_eq!(normalize_scale(Some(&json!(9999))), 200);
        assert_eq!(normalize_scale(Some(&json!("x"))), 100);
    }

    #[test]
    fn export_has_no_secrets_and_import_validates() {
        let s = json!({"language": "en", "hf": {"token": "SEGREDO"}, "providers": {"local_hf": {"model": "m", "api_key": "k", "n_ctx": 0}}, "ui": default_ui()});
        let e = export_settings(&s);
        assert!(!serde_json::to_string(&e).unwrap().contains("SEGREDO"));
        assert_eq!(e["settings"]["providers"]["local_hf"], json!({"model": "m", "n_ctx": 0}));
        assert!(import_patch(&json!({"schema": "x"})).is_err());
        assert_eq!(import_patch(&e).unwrap()["language"], "en");
    }
}
