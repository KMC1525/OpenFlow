//! Comandos internos (`flow dev …`) usados pelos testes de paridade com o Python: leem um JSON na entrada padrão e escrevem o resultado em JSON.

use crate::{settings, uiprefs, util};
use serde_json::{json, Value};
use std::io::Read;
use std::process::ExitCode;

pub fn run(args: &[String]) -> ExitCode {
    let mut input = String::new();
    let _ = std::io::stdin().read_to_string(&mut input);
    let v: Value = serde_json::from_str(&input).unwrap_or(Value::Null);
    let out = match args.first().map(|s| s.as_str()) {
        Some("normalize_ui") => uiprefs::normalize_ui(Some(&v)),
        Some("export") => uiprefs::export_settings(&v),
        Some("import") => match uiprefs::import_patch(&v) {
            Ok(p) => json!({"ok": p}),
            Err(e) => json!({"error": e}),
        },
        Some("deep_merge") => util::deep_merge(&v["base"], &v["patch"]),
        Some("safe_filename") => json!(util::safe_filename(v["name"].as_str().unwrap_or(""), v["default"].as_str().unwrap_or("file"))),
        // v = {"saved": <settings.json>, "patches": [<patch>, …]}: lê, aplica os patches em sequência e devolve o que o navegador veria depois de cada um
        Some("settings") => {
            let home = std::env::temp_dir().join(util::new_id("flow-dev-"));
            let _ = std::fs::create_dir_all(&home);
            if !v["saved"].is_null() {
                let _ = std::fs::write(home.join("settings.json"), serde_json::to_string(&v["saved"]).unwrap_or_default());
            }
            let st = settings::Store::new(&home);
            let mut steps = vec![json!({"get": st.get_settings(), "public": st.public_settings()})];
            for p in v["patches"].as_array().cloned().unwrap_or_default() {
                st.save_settings(&p);
                steps.push(json!({"get": st.get_settings(), "public": st.public_settings()}));
            }
            let _ = std::fs::remove_dir_all(&home);
            Value::Array(steps)
        }
        _ => json!({"error": "comando dev desconhecido"}),
    };
    println!("{}", serde_json::to_string(&out).unwrap_or_default());
    ExitCode::SUCCESS
}
