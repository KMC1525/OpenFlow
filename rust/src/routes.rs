//! Rotas já portadas para Rust. O que não está aqui é repassado ao worker Python (ver `app::App::to_worker`).

use crate::app::{param, App, Params};
use crate::http::{HttpError, Req, Res};
use crate::{uiprefs, util};
use serde_json::{json, Value};

pub fn register(app: &mut App) {
    app.add("GET", "/api/settings", settings_get);
    app.add("PUT", "/api/settings", settings_put);
    app.add("GET", "/api/settings/export", settings_export);
    app.add("POST", "/api/settings/import", settings_import);
    app.add("POST", "/api/settings/reset", settings_reset);
    app.add("POST", "/api/uploads", upload);
    app.add("DELETE", "/api/uploads/{uid}", upload_delete);
}

fn body_object(req: &mut Req) -> Result<Value, HttpError> {
    let v = req.body_json()?;
    util::clean_json(&v, 0).map_err(|_| HttpError::new(400, "JSON inválido: aninhado fundo demais"))
}

fn settings_get(app: &App, req: &mut Req, _p: &Params) -> Res {
    req.json(&app.store.public_settings())?;
    Ok(())
}

fn settings_put(app: &App, req: &mut Req, _p: &Params) -> Res {
    let body = body_object(req)?;
    app.store.save_settings(&body);
    app.worker.notify_settings();
    req.json(&app.store.public_settings())?;
    Ok(())
}

fn settings_export(app: &App, req: &mut Req, _p: &Params) -> Res {
    let data = uiprefs::export_settings(&app.store.get_settings());
    let txt = serde_json::to_string_pretty(&data).unwrap_or_default();
    req.bytes(200, "application/json; charset=utf-8", txt.as_bytes(), &[])?;
    Ok(())
}

fn settings_import(app: &App, req: &mut Req, _p: &Params) -> Res {
    let body = body_object(req)?;
    let patch = uiprefs::import_patch(&body).map_err(|e| HttpError::new(400, e))?;
    app.store.save_settings(&patch);
    app.worker.notify_settings();
    let keys: Vec<String> = { let mut k: Vec<String> = patch.as_object().map(|o| o.keys().cloned().collect()).unwrap_or_default(); k.sort(); k };
    req.json(&json!({"imported": keys, "settings": app.store.public_settings()}))?;
    Ok(())
}

fn settings_reset(app: &App, req: &mut Req, _p: &Params) -> Res {
    let body = body_object(req)?;
    let section = body.get("section").and_then(|s| s.as_str()).unwrap_or("");
    if !uiprefs::RESETTABLE.contains(&section) {
        return Err(HttpError::new(400, format!("Seção inválida. Opções: {}", uiprefs::RESETTABLE.join(", "))));
    }
    let out = app.store.reset_section(section);
    app.worker.notify_settings();
    req.json(&out)?;
    Ok(())
}

fn upload(app: &App, req: &mut Req, _p: &Params) -> Res {
    let settings = app.store.get_settings();
    let mb = settings["server"]["max_upload_mb"].as_f64().unwrap_or(200.0) as u64;
    let limit = mb * 1024 * 1024;
    let length = req.content_length()?;
    if length > limit {
        return Err(HttpError::new(413, format!("Arquivo maior que o limite de {} MB", limit / 1024 / 1024)));
    }
    let name = crate::http::unquote(req.header("x-filename").unwrap_or("arquivo"));
    let mime = req.header("content-type").unwrap_or("").to_string();
    req.body_read = true;
    let meta = app.store.save_upload_stream(&name, &mime, &mut req.reader, length).map_err(HttpError::from)?;
    req.json(&meta)?;
    Ok(())
}

fn upload_delete(app: &App, req: &mut Req, p: &Params) -> Res {
    let ok = app.store.delete_upload(param(p, "uid"));
    req.json(&json!({"ok": ok}))?;
    Ok(())
}
