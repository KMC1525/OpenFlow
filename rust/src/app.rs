//! A aplicação: validação de Host/Origin (anti DNS-rebinding/CSRF, como no servidor Python), roteador, interface estática e o repasse ao worker Python das rotas ainda não portadas.

use crate::http::{read_request, HttpError, Req, Res};
use crate::{assets, proxy, worker::Worker};
use serde_json::{json, Value};
use std::io::BufReader;
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::Arc;

pub struct App {
    pub home: PathBuf,
    pub bind_host: String,
    pub worker: Worker,
    pub routes: Vec<Route>,
}

pub type Handler = fn(&App, &mut Req, &Params) -> Res;
pub type Params = Vec<(String, String)>;

pub struct Route {
    method: &'static str,
    segs: Vec<Seg>,
    handler: Handler,
}

enum Seg {
    Lit(String),
    Param(String),
}

pub fn param<'a>(p: &'a Params, name: &str) -> &'a str {
    p.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str()).unwrap_or("")
}

impl App {
    pub fn new(home: PathBuf, bind_host: &str) -> Self {
        let mut app = App { worker: Worker::new(home.clone()), home, bind_host: bind_host.to_string(), routes: Vec::new() };
        crate::routes::register(&mut app);
        app
    }

    /// `pattern`: segmentos separados por «/»; `{nome}` captura um segmento.
    pub fn add(&mut self, method: &'static str, pattern: &str, handler: Handler) {
        let segs = pattern.trim_matches('/').split('/').map(|s| if s.starts_with('{') && s.ends_with('}') { Seg::Param(s[1..s.len() - 1].to_string()) } else { Seg::Lit(s.to_string()) }).collect();
        self.routes.push(Route { method, segs, handler });
    }

    fn matches(route: &Route, path: &str) -> Option<Params> {
        let parts: Vec<&str> = path.trim_matches('/').split('/').collect();
        if parts.len() != route.segs.len() {
            return None;
        }
        let mut out = Vec::new();
        for (seg, part) in route.segs.iter().zip(parts) {
            match seg {
                Seg::Lit(l) => {
                    if l != part {
                        return None;
                    }
                }
                Seg::Param(n) => {
                    if part.is_empty() {
                        return None;
                    }
                    out.push((n.clone(), crate::http::unquote(part)));
                }
            }
        }
        Some(out)
    }

    pub fn host_allowed(&self, host_header: &str) -> bool {
        let host = host_header.trim().to_ascii_lowercase();
        let name = if let Some(rest) = host.strip_prefix('[') { rest.split(']').next().unwrap_or("").to_string() } else { host.split(':').next().unwrap_or("").to_string() };
        if matches!(name.as_str(), "localhost" | "127.0.0.1" | "::1") {
            return true;
        }
        !matches!(self.bind_host.as_str(), "127.0.0.1" | "localhost" | "::1") // exposto na rede por escolha do usuário (flow --host)
    }

    fn handle(&self, req: &mut Req) -> Res {
        if !self.host_allowed(req.header("host").unwrap_or("")) {
            return Err(HttpError::new(403, "Host não permitido"));
        }
        if matches!(req.method.as_str(), "POST" | "PUT" | "DELETE") {
            if let Some(origin) = req.header("origin") {
                let netloc = origin.split_once("://").map(|(_, r)| r.split('/').next().unwrap_or("")).unwrap_or("");
                if netloc != req.header("host").unwrap_or("") {
                    return Err(HttpError::new(403, "Origem não permitida"));
                }
            }
        }
        let path = req.path.clone();
        if path.starts_with("/api/") {
            let method = if req.method == "HEAD" { "GET".to_string() } else { req.method.clone() };
            for r in &self.routes {
                if r.method != method {
                    continue;
                }
                if let Some(p) = Self::matches(r, &path) {
                    return (r.handler)(self, req, &p);
                }
            }
            // rota ainda não portada: o worker Python responde
            return self.to_worker(req);
        }
        if matches!(req.method.as_str(), "GET" | "HEAD") {
            return assets::serve(req);
        }
        Err(HttpError::new(405, "Método não permitido"))
    }

    pub fn to_worker(&self, req: &mut Req) -> Res {
        match self.worker.ensure() {
            Ok(port) => proxy::forward(req, port),
            Err(e) => Err(HttpError::new(503, format!("{e} Esta função ainda usa o worker Python do OpenFlow (flow worker install)."))),
        }
    }

    pub fn serve_conn(self: &Arc<Self>, stream: TcpStream) {
        let _ = stream.set_nodelay(true);
        let out = match stream.try_clone() {
            Ok(o) => o,
            Err(_) => return,
        };
        let mut reader = BufReader::new(stream);
        let mut out = out;
        loop {
            let mut req = match read_request(reader, out) {
                Ok(Some(r)) => r,
                Ok(None) => return,
                Err((rd, mut o, e)) => {
                    let _ = crate::app::write_error(&mut o, e.status, &e.message);
                    drop(rd);
                    return;
                }
            };
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.handle(&mut req)));
            match result {
                Ok(Ok(())) => {}
                Ok(Err(e)) => {
                    if !req.responded {
                        let mut payload = json!({ "error": e.message });
                        if e.status == 409 {
                            if let Ok(Value::Object(m)) = serde_json::from_str::<Value>(&e.message) {
                                for (k, v) in m {
                                    payload[k] = v;
                                }
                            }
                        }
                        let _ = req.json_status(e.status, &payload);
                    }
                }
                Err(_) => {
                    if !req.responded {
                        let _ = req.json_status(500, &json!({ "error": "Erro interno" }));
                    }
                    req.close = true;
                }
            }
            if req.close || req.sse {
                return;
            }
            if !req.body_read {
                // corpo não lido (rota que não o usou): descarta para não bagunçar a próxima requisição
                match req.content_length() {
                    Ok(n) if n > 0 && n <= 8 * 1024 * 1024 => {
                        let mut sink = vec![0u8; n as usize];
                        let _ = std::io::Read::read_exact(&mut req.reader, &mut sink);
                    }
                    Ok(0) => {}
                    _ => return,
                }
            }
            reader = req.reader;
            out = req.out;
        }
    }
}

pub fn write_error(out: &mut TcpStream, status: u16, message: &str) -> std::io::Result<()> {
    use std::io::Write;
    let data = serde_json::to_vec(&json!({ "error": message })).unwrap_or_default();
    let head = format!("HTTP/1.1 {} {}\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", status, crate::http::reason(status), data.len());
    out.write_all(head.as_bytes())?;
    out.write_all(&data)
}

pub fn serve(app: Arc<App>, listener: TcpListener) {
    for conn in listener.incoming() {
        if let Ok(stream) = conn {
            let app = Arc::clone(&app);
            std::thread::spawn(move || app.serve_conn(stream));
        }
    }
}
