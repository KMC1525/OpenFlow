//! A interface web (openflow/web) embutida no binário: um único arquivo `flow`, sem pasta de instalação.

use crate::http::{unquote, HttpError, Req, Res};
use include_dir::{include_dir, Dir};

static WEB: Dir = include_dir!("$CARGO_MANIFEST_DIR/../openflow/web");

pub fn mime(path: &str) -> &'static str {
    let ext = path.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "html" => "text/html; charset=utf-8",
        "json" => "application/json; charset=utf-8",
        "md" => "text/markdown; charset=utf-8",
        "svg" => "image/svg+xml",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "ogg" | "opus" => "audio/ogg",
        "webm" => "audio/webm",
        "zip" => "application/zip",
        "ico" => "image/x-icon",
        "txt" => "text/plain; charset=utf-8",
        "mp4" => "video/mp4",
        "m4a" => "audio/mp4",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "flac" => "audio/flac",
        "mov" => "video/quicktime",
        "mkv" => "video/x-matroska",
        "webmanifest" => "application/manifest+json",
        "glb" => "model/gltf-binary",
        _ => "application/octet-stream",
    }
}

pub fn serve(req: &mut Req) -> Res {
    let raw = unquote(req.path.trim_start_matches('/'));
    let mut rel = if raw.is_empty() { "index.html".to_string() } else { raw };
    if rel.contains('\0') || rel.split('/').any(|p| p == "..") {
        return Err(HttpError::new(404, "Não encontrado"));
    }
    if rel == "sw.js" {
        // service worker carimbado com a versão (muda quando o OpenFlow é atualizado)
        let f = WEB.get_file("sw.js").ok_or_else(|| HttpError::new(404, "Não encontrado"))?;
        let data = String::from_utf8_lossy(f.contents()).replace("__OPENFLOW_VERSION__", env!("CARGO_PKG_VERSION")).into_bytes();
        req.bytes(200, "text/javascript; charset=utf-8", &data, &[("Service-Worker-Allowed", "/".to_string())])?;
        return Ok(());
    }
    let file = match WEB.get_file(&rel) {
        Some(f) => f,
        None => {
            if rel.rsplit('/').next().unwrap_or("").contains('.') {
                return Err(HttpError::new(404, "Não encontrado"));
            }
            rel = "index.html".to_string();
            WEB.get_file("index.html").ok_or_else(|| HttpError::new(404, "Não encontrado"))?
        }
    };
    req.bytes(200, mime(&rel), file.contents(), &[])?;
    Ok(())
}
