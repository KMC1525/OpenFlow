//! Configurações e anexos do OpenFlow em disco (portado de `openflow/storage.py`): `settings.json` (com os padrões, a «forma» forçada e os segredos fora do que vai ao navegador) e a pasta `uploads/`.

use crate::uiprefs;
use crate::util::{self, deep_merge, new_id, now_iso, read_json, safe_filename, write_json};
use serde_json::{json, Map, Value};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

const LOCAL_MEDIA: [&str; 3] = ["demo", "local_hf", "gguf_local"];
const LOCAL_TEXT: [&str; 2] = ["demo", "local_hf"];

pub fn default_settings() -> Value {
    json!({
        "language": "auto",
        "ui": uiprefs::default_ui(),
        "active": {"generation": "demo"},
        "providers": {},
        "media": {
            "active": {"image": "demo", "video": "demo", "sound": "demo", "voice": "demo", "stt": "local_hf", "model3d": "demo"},
            "models": {}
        },
        "canvas": {"template": "text_image"},
        "performance": {"mode": "auto", "idle_unload_min": 10, "device": "auto", "gpus": [], "cpu_pin": true,
                        "memory": {"multi_gpu": true, "ram_spill": true, "gpu_reserve_mb": 512, "ram_reserve_gb": 2},
                        "guard": {"enabled": true, "limit": 90, "hold_s": 5, "cpu": true, "ram": true, "gpu": true}},
        "server": {"max_upload_mb": 200},
        "storage": {"models_dir": "", "files_dir": ""},
        "hf": {"token": "", "auto_support": true, "connections": 4}
    })
}

fn is_num(v: &Value) -> bool {
    v.is_number()
}

/// Força `value` a ter a «forma» de `defaults` (objeto onde o padrão é objeto; número/texto/booleano onde o padrão é do tipo).
pub fn conform(defaults: &Value, value: &Value) -> Value {
    let Some(dm) = defaults.as_object() else { return value.clone() };
    let mut out: Map<String, Value> = value.as_object().cloned().unwrap_or_default();
    for (key, dv) in dm {
        match out.get(key).cloned() {
            None => {
                out.insert(key.clone(), dv.clone());
            }
            Some(cur) => {
                let new = if dv.is_object() {
                    if cur.is_object() { conform(dv, &cur) } else { dv.clone() }
                } else if let Value::Bool(d) = dv {
                    match &cur {
                        Value::Bool(_) => cur.clone(),
                        Value::Number(n) => Value::Bool(n.as_f64().map(|f| f != 0.0).unwrap_or(false)),
                        _ => Value::Bool(*d),
                    }
                } else if is_num(dv) {
                    if is_num(&cur) { cur.clone() } else { dv.clone() }
                } else if dv.is_string() {
                    if cur.is_string() { cur.clone() } else { dv.clone() }
                } else {
                    cur.clone()
                };
                out.insert(key.clone(), new);
            }
        }
    }
    if let Some(p) = out.get("providers").and_then(|v| v.as_object()) {
        let f: Map<String, Value> = p.iter().filter(|(_, v)| v.is_object()).map(|(k, v)| (k.clone(), v.clone())).collect();
        out.insert("providers".into(), Value::Object(f));
    }
    Value::Object(out)
}

fn provider_fields(v: &Value) -> Value {
    let mut out = Map::new();
    if let Some(m) = v.get("model").and_then(|x| x.as_str()) {
        out.insert("model".into(), json!(m.trim().chars().take(300).collect::<String>()));
    }
    if let Some(Value::Number(n)) = v.get("n_ctx") {
        let f = n.as_f64().unwrap_or(-1.0);
        if f >= 0.0 {
            out.insert("n_ctx".into(), json!(f.min(4_194_304.0) as i64));
        }
    }
    Value::Object(out)
}

/// v0.35 (sem nuvem): configurações antigas com provedores de nuvem voltam ao padrão local.
pub fn local_only(s: &mut Value) {
    let obj = s.as_object_mut().unwrap();
    let provs: Map<String, Value> = obj.get("providers").and_then(|v| v.as_object()).map(|p| p.iter().filter(|(k, v)| LOCAL_TEXT.contains(&k.as_str()) && v.is_object()).map(|(k, v)| (k.clone(), provider_fields(v))).collect()).unwrap_or_default();
    obj.insert("providers".into(), Value::Object(provs));
    obj.remove("voice");
    obj.remove("generation");
    let act: Map<String, Value> = obj.get("active").and_then(|v| v.as_object()).map(|a| a.iter().map(|(r, v)| {
        let keep = v.as_str().map(|x| LOCAL_TEXT.contains(&x) || x.is_empty() || x == "auto").unwrap_or(false);
        (r.clone(), if keep { v.clone() } else { json!("auto") })
    }).collect()).unwrap_or_default();
    obj.insert("active".into(), Value::Object(act));
    let mut media = obj.get("media").and_then(|v| v.as_object()).cloned().unwrap_or_default();
    let ma: Map<String, Value> = media.get("active").and_then(|v| v.as_object()).map(|a| a.iter().map(|(c, v)| {
        let ok = v.as_str().map(|x| LOCAL_MEDIA.contains(&x)).unwrap_or(false);
        (c.clone(), if ok { v.clone() } else { json!(if c == "stt" { "local_hf" } else { "demo" }) })
    }).collect()).unwrap_or_default();
    media.insert("active".into(), Value::Object(ma));
    let models: Map<String, Value> = media.get("models").and_then(|v| v.as_object()).map(|m| m.iter().filter(|(k, v)| LOCAL_MEDIA.contains(&k.as_str()) && v.is_object()).map(|(k, v)| {
        let inner: Map<String, Value> = v.as_object().unwrap().iter().filter_map(|(c, m)| m.as_str().filter(|t| !t.trim().is_empty()).map(|t| (c.clone(), json!(t.trim().chars().take(300).collect::<String>())))).collect();
        (k.clone(), Value::Object(inner))
    }).collect()).unwrap_or_default();
    media.insert("models".into(), Value::Object(models));
    media.remove("urls");
    obj.insert("media".into(), Value::Object(media));
}

fn int_clamp(v: Option<&Value>, lo: f64, hi: f64, default: Value) -> Value {
    match v {
        Some(Value::Number(n)) => json!(n.as_f64().unwrap_or(0.0).clamp(lo, hi) as i64),
        _ => default,
    }
}

pub fn normalize_guard(cfg: Option<&Value>) -> Value {
    let empty = Map::new();
    let c = cfg.and_then(|x| x.as_object()).unwrap_or(&empty);
    let mut out = json!({"enabled": true, "limit": 90, "hold_s": 5, "cpu": true, "ram": true, "gpu": true});
    for k in ["enabled", "cpu", "ram", "gpu"] {
        if let Some(Value::Bool(b)) = c.get(k) {
            out[k] = json!(b);
        }
    }
    out["limit"] = int_clamp(c.get("limit"), 50.0, 99.0, out["limit"].clone());
    out["hold_s"] = int_clamp(c.get("hold_s"), 1.0, 60.0, out["hold_s"].clone());
    out
}

pub fn normalize_memory(raw: Option<&Value>) -> Value {
    let empty = Map::new();
    let d = raw.and_then(|x| x.as_object()).unwrap_or(&empty);
    let num = |k: &str, lo: f64, hi: f64, def: f64| -> f64 {
        match d.get(k) {
            Some(Value::Number(n)) => n.as_f64().filter(|f| f.is_finite()).map(|f| f.clamp(lo, hi)).unwrap_or(def),
            _ => def,
        }
    };
    let ram = num("ram_reserve_gb", 0.0, 64.0, 2.0);
    json!({"multi_gpu": d.get("multi_gpu") != Some(&Value::Bool(false)), "ram_spill": d.get("ram_spill") != Some(&Value::Bool(false)),
           "gpu_reserve_mb": num("gpu_reserve_mb", 0.0, 8192.0, 512.0) as i64, "ram_reserve_gb": format!("{ram:.1}").parse::<f64>().unwrap_or(ram)})
}

fn normalize_perf(settings: &mut Value) {
    if let Some(perf) = settings.get_mut("performance").and_then(|p| p.as_object_mut()) {
        let g = normalize_guard(perf.get("guard"));
        perf.insert("guard".into(), g);
        let m = normalize_memory(perf.get("memory"));
        perf.insert("memory".into(), m);
    }
}

const SECRET_PATHS: [(&str, &str); 1] = [("hf", "token")];

fn strip_flags(v: &mut Value) {
    if let Value::Object(m) = v {
        let keys: Vec<String> = m.keys().cloned().collect();
        for k in keys {
            if k == "has_key" || k.ends_with("_set") {
                m.remove(&k);
            } else if let Some(x) = m.get_mut(&k) {
                strip_flags(x);
            }
        }
    }
}

pub struct Store {
    pub home: PathBuf,
    pub settings_path: PathBuf,
    pub uploads_dir: PathBuf,
    pub default_models_dir: PathBuf,
    pub default_projects_dir: PathBuf,
    lock: Mutex<()>,
}

impl Store {
    pub fn new(home: &Path) -> Self {
        let s = Store { home: home.to_path_buf(), settings_path: home.join("settings.json"), uploads_dir: home.join("uploads"), default_models_dir: home.join("models"), default_projects_dir: home.join("projects"), lock: Mutex::new(()) };
        let _ = std::fs::create_dir_all(&s.uploads_dir);
        let _ = std::fs::create_dir_all(&s.default_models_dir);
        s
    }

    pub fn get_settings(&self) -> Value {
        let saved = read_json(&self.settings_path).filter(|v| v.is_object()).unwrap_or_else(|| json!({}));
        let defaults = default_settings();
        let mut merged = conform(&defaults, &deep_merge(&defaults, &saved));
        local_only(&mut merged);
        normalize_perf(&mut merged);
        let ui = uiprefs::normalize_ui(merged.get("ui"));
        merged["ui"] = ui;
        merged
    }

    /// Mescla `patch` nas configurações. Segredos: "" ou ausente = manter; null = apagar; texto = definir.
    pub fn save_settings(&self, patch: &Value) -> Value {
        let _g = self.lock.lock().unwrap_or_else(|e| e.into_inner());
        let mut current = self.get_settings();
        let mut patch = patch.clone();
        if !patch.is_object() {
            patch = json!({});
        }
        let prov_patch = patch.as_object_mut().unwrap().remove("providers");
        if let Some(Value::Object(pp)) = prov_patch {
            for (pid, pcfg) in pp {
                let Some(pc) = pcfg.as_object() else { continue };
                let provs = current["providers"].as_object_mut().unwrap();
                let cur = provs.entry(pid).or_insert_with(|| json!({}));
                for (k, v) in pc {
                    if k == "model" || k == "n_ctx" {
                        cur[k] = v.clone();
                    }
                }
            }
        }
        for (sec, key) in SECRET_PATHS {
            let val = patch.get_mut(sec).and_then(|p| p.as_object_mut()).and_then(|p| p.remove(key));
            match val {
                Some(Value::Null) => current[sec][key] = json!(""),
                Some(Value::String(s)) if !s.trim().is_empty() => current[sec][key] = json!(s.trim()),
                _ => {}
            }
        }
        strip_flags(&mut patch);
        let mut merged = conform(&default_settings(), &deep_merge(&current, &patch));
        let ui = uiprefs::normalize_ui(merged.get("ui"));
        merged["ui"] = ui;
        local_only(&mut merged);
        normalize_perf(&mut merged);
        let _ = write_json(&self.settings_path, &merged, true);
        merged
    }

    /// Configurações para o navegador: segredos viram flags `*_set`.
    pub fn public_settings(&self) -> Value {
        let mut s = self.get_settings();
        for (sec, key) in SECRET_PATHS {
            let set = s.get(sec).and_then(|p| p.get(key)).map(|v| v.as_str().map(|t| !t.is_empty()).unwrap_or(!v.is_null())).unwrap_or(false);
            if let Some(o) = s.get_mut(sec).and_then(|p| p.as_object_mut()) {
                o.insert(format!("{key}_set"), json!(set));
                o.insert(key.into(), json!(""));
            }
        }
        s
    }

    /// Volta uma seção ao padrão (ui, canvas, performance).
    pub fn reset_section(&self, section: &str) -> Value {
        let _g = self.lock.lock().unwrap_or_else(|e| e.into_inner());
        let mut cur = self.get_settings();
        cur[section] = default_settings()[section].clone();
        if section == "ui" {
            cur["ui"]["welcome_done"] = json!(true);
        }
        let _ = write_json(&self.settings_path, &cur, true);
        drop(_g);
        self.public_settings()
    }

    // ------------------------------------------------------------------ anexos
    pub fn save_upload_stream(&self, name: &str, mime: &str, reader: &mut impl Read, length: u64) -> std::io::Result<Value> {
        let uid = new_id("u_");
        let folder = self.uploads_dir.join(&uid);
        std::fs::create_dir_all(&folder)?;
        let fname = safe_filename(name, "arquivo");
        let target = folder.join(&fname);
        let mut fh = std::fs::File::create(&target)?;
        let mut left = length;
        let mut buf = vec![0u8; 1 << 20];
        while left > 0 {
            let take = left.min(buf.len() as u64) as usize;
            let n = reader.read(&mut buf[..take])?;
            if n == 0 {
                break;
            }
            std::io::Write::write_all(&mut fh, &buf[..n])?;
            left -= n as u64;
        }
        drop(fh);
        let size = std::fs::metadata(&target)?.len();
        let meta = json!({"id": uid, "name": fname, "mime": mime, "size": size, "created": now_iso()});
        write_json(&folder.join("meta.json"), &meta, false)?;
        Ok(meta)
    }

    pub fn get_upload(&self, uid: &str) -> Option<Value> {
        if uid.is_empty() || uid.contains('/') || uid.contains('\\') || uid.contains("..") {
            return None;
        }
        let folder = self.uploads_dir.join(uid);
        let mut meta = read_json(&folder.join("meta.json"))?;
        let name = meta.get("name")?.as_str()?.to_string();
        meta["path"] = json!(folder.join(name).to_string_lossy());
        Some(meta)
    }

    pub fn delete_upload(&self, uid: &str) -> bool {
        let uid = uid.split(':').next().unwrap_or("");
        if self.get_upload(uid).is_none() {
            return false;
        }
        let _ = std::fs::remove_dir_all(self.uploads_dir.join(uid));
        true
    }
}

#[allow(dead_code)]
pub fn unused() -> f64 {
    util::now_f64()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp() -> PathBuf {
        let p = std::env::temp_dir().join(util::new_id("flow-test-"));
        std::fs::create_dir_all(&p).unwrap();
        p
    }

    #[test]
    fn defaults_when_no_file_and_secrets_hidden() {
        let st = Store::new(&tmp());
        let s = st.get_settings();
        assert_eq!(s["ui"]["theme"], "dark");
        assert_eq!(s["performance"]["guard"]["limit"], 90);
        st.save_settings(&json!({"hf": {"token": "  abc  "}}));
        assert_eq!(st.get_settings()["hf"]["token"], "abc");
        let p = st.public_settings();
        assert_eq!(p["hf"]["token"], "");
        assert_eq!(p["hf"]["token_set"], true);
        st.save_settings(&json!({"hf": {"token": ""}}));
        assert_eq!(st.get_settings()["hf"]["token"], "abc");   // "" = manter
        st.save_settings(&json!({"hf": {"token": null}}));
        assert_eq!(st.get_settings()["hf"]["token"], "");      // null = apagar
    }

    #[test]
    fn cloud_providers_and_bad_types_are_dropped() {
        let st = Store::new(&tmp());
        std::fs::write(&st.settings_path, r#"{"providers": {"openai": {"api_key": "x"}, "local_hf": {"model": " m ", "api_key": "y"}}, "server": {"max_upload_mb": "muito"}, "performance": {"guard": {"limit": 5}}}"#).unwrap();
        let s = st.get_settings();
        assert_eq!(s["providers"], json!({"local_hf": {"model": "m"}}));
        assert_eq!(s["server"]["max_upload_mb"], 200);
        assert_eq!(s["performance"]["guard"]["limit"], 50);
    }

    #[test]
    fn uploads_roundtrip() {
        let st = Store::new(&tmp());
        let data = b"hello world";
        let meta = st.save_upload_stream("../x/a b.txt", "text/plain", &mut &data[..], data.len() as u64).unwrap();
        let id = meta["id"].as_str().unwrap().to_string();
        assert_eq!(meta["name"], "a b.txt");
        assert_eq!(meta["size"], 11);
        assert!(st.get_upload(&id).is_some());
        assert!(st.get_upload("../x").is_none());
        assert!(st.delete_upload(&format!("{id}:3")));
        assert!(!st.delete_upload(&id));
    }
}
