//! Servidor HTTP/1.1 mínimo sobre `std::net` (uma thread por conexão): leitura da requisição, respostas JSON/bytes/arquivo (com `Range`) e SSE.
//! Mesmas regras do servidor Python: `Cache-Control: no-store`, `nosniff`, sem `Transfer-Encoding: chunked` na entrada (411).

use serde_json::Value;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::net::TcpStream;

pub const MAX_HEAD: usize = 64 * 1024;

#[derive(Debug)]
pub struct HttpError {
    pub status: u16,
    pub message: String,
}

impl HttpError {
    pub fn new(status: u16, message: impl Into<String>) -> Self {
        HttpError { status, message: message.into() }
    }
}

impl From<io::Error> for HttpError {
    fn from(e: io::Error) -> Self {
        HttpError::new(500, format!("Erro de E/S: {e}"))
    }
}

pub type Res = Result<(), HttpError>;

pub struct Req {
    pub method: String,
    pub target: String,
    pub path: String,
    pub query: Vec<(String, String)>,
    pub headers: Vec<(String, String)>,
    pub reader: BufReader<TcpStream>,
    pub out: TcpStream,
    pub body_read: bool,
    pub sse: bool,
    pub close: bool,
    pub responded: bool,
}

pub fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push(h * 16 + l);
                i += 3;
                continue;
            }
        }
        out.push(if b[i] == b'+' { b' ' } else { b[i] });
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// Como `percent_decode`, mas sem tratar «+» como espaço (caminhos de arquivo).
pub fn unquote(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let (Some(h), Some(l)) = (hex(b[i + 1]), hex(b[i + 2])) {
                out.push(h * 16 + l);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn hex(c: u8) -> Option<u8> {
    match c {
        b'0'..=b'9' => Some(c - b'0'),
        b'a'..=b'f' => Some(c - b'a' + 10),
        b'A'..=b'F' => Some(c - b'A' + 10),
        _ => None,
    }
}

pub fn parse_query(q: &str) -> Vec<(String, String)> {
    q.split('&').filter(|p| !p.is_empty()).map(|p| match p.split_once('=') {
        Some((k, v)) => (percent_decode(k), percent_decode(v)),
        None => (percent_decode(p), String::new()),
    }).collect()
}

fn read_line_limited(r: &mut BufReader<TcpStream>, buf: &mut Vec<u8>, limit: usize) -> io::Result<usize> {
    buf.clear();
    let n = r.by_ref().take(limit as u64).read_until(b'\n', buf)?;
    Ok(n)
}

/// Lê a próxima requisição da conexão; `Ok(None)` se o cliente fechou.
pub fn read_request(reader: BufReader<TcpStream>, out: TcpStream) -> Result<Option<Req>, (BufReader<TcpStream>, TcpStream, HttpError)> {
    let mut reader = reader;
    let mut line = Vec::new();
    match read_line_limited(&mut reader, &mut line, 16 * 1024) {
        Ok(0) => return Ok(None),
        Ok(_) => {}
        Err(_) => return Ok(None),
    }
    let text = String::from_utf8_lossy(&line).trim().to_string();
    if text.is_empty() {
        return Ok(None);
    }
    let mut parts = text.split_whitespace();
    let (method, target) = match (parts.next(), parts.next()) {
        (Some(m), Some(t)) => (m.to_string(), t.to_string()),
        _ => return Err((reader, out, HttpError::new(400, "Requisição inválida"))),
    };
    let mut headers: Vec<(String, String)> = Vec::new();
    let mut total = line.len();
    loop {
        let mut h = Vec::new();
        match read_line_limited(&mut reader, &mut h, 16 * 1024) {
            Ok(0) | Err(_) => return Ok(None),
            Ok(_) => {}
        }
        total += h.len();
        if total > MAX_HEAD {
            return Err((reader, out, HttpError::new(431, "Cabeçalhos grandes demais")));
        }
        let s = String::from_utf8_lossy(&h);
        let s = s.trim_end_matches(['\r', '\n']);
        if s.is_empty() {
            break;
        }
        if let Some((k, v)) = s.split_once(':') {
            headers.push((k.trim().to_ascii_lowercase(), v.trim().to_string()));
        }
    }
    let (path, query) = match target.split_once('?') {
        Some((p, q)) => (p.to_string(), parse_query(q)),
        None => (target.clone(), Vec::new()),
    };
    let keep = headers.iter().find(|(k, _)| k == "connection").map(|(_, v)| !v.eq_ignore_ascii_case("close")).unwrap_or(true);
    Ok(Some(Req { method, target, path, query, headers, reader, out, body_read: false, sse: false, close: !keep, responded: false }))
}

impl Req {
    pub fn header(&self, name: &str) -> Option<&str> {
        self.headers.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str())
    }

    pub fn q(&self, name: &str) -> Option<&str> {
        self.query.iter().find(|(k, _)| k == name).map(|(_, v)| v.as_str())
    }

    pub fn content_length(&self) -> Result<u64, HttpError> {
        if self.header("transfer-encoding").map(|v| v.to_ascii_lowercase().contains("chunked")).unwrap_or(false) {
            return Err(HttpError::new(411, "Envie o corpo com Content-Length (corpo em pedaços não é aceito)"));
        }
        match self.header("content-length") {
            None => Ok(0),
            Some(raw) if raw.trim().is_empty() => Ok(0),
            Some(raw) => raw.trim().parse::<i64>().ok().filter(|n| *n >= 0).map(|n| n as u64).ok_or_else(|| HttpError::new(400, "Content-Length inválido")),
        }
    }

    pub fn body_bytes(&mut self, limit: u64) -> Result<Vec<u8>, HttpError> {
        let n = self.content_length()?;
        if n > limit {
            return Err(HttpError::new(413, "Corpo da requisição muito grande"));
        }
        self.body_read = true;
        let mut buf = vec![0u8; n as usize];
        self.reader.read_exact(&mut buf).map_err(|_| HttpError::new(400, "Corpo incompleto"))?;
        Ok(buf)
    }

    /// Corpo JSON: sempre um objeto (como o servidor Python).
    pub fn body_json(&mut self) -> Result<Value, HttpError> {
        let raw = self.body_bytes(8 * 1024 * 1024)?;
        if raw.is_empty() {
            return Ok(Value::Object(Default::default()));
        }
        let v: Value = serde_json::from_slice(&raw).map_err(|_| HttpError::new(400, "JSON inválido"))?;
        if !v.is_object() {
            return Err(HttpError::new(400, "JSON inválido: esperava um objeto {…}"));
        }
        Ok(v)
    }

    pub fn head(&mut self, status: u16, mime: &str, length: Option<u64>, extra: &[(&str, String)]) -> io::Result<()> {
        let mut h = format!("HTTP/1.1 {} {}\r\nContent-Type: {}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n", status, reason(status), mime);
        if let Some(n) = length {
            h.push_str(&format!("Content-Length: {n}\r\n"));
        }
        for (k, v) in extra {
            // `extra` sobrescreve os padrões (ex.: Cache-Control de mídias imutáveis)
            if let Some(pos) = h.to_ascii_lowercase().find(&format!("\r\n{}:", k.to_ascii_lowercase())) {
                let start = pos + 2;
                if let Some(end) = h[start..].find("\r\n") {
                    h.replace_range(start..start + end + 2, "");
                }
            }
            h.push_str(&format!("{k}: {v}\r\n"));
        }
        if self.close {
            h.push_str("Connection: close\r\n");
        }
        h.push_str("\r\n");
        self.responded = true;
        self.out.write_all(h.as_bytes())
    }

    pub fn json(&mut self, v: &Value) -> io::Result<()> {
        self.json_status(200, v)
    }

    pub fn json_status(&mut self, status: u16, v: &Value) -> io::Result<()> {
        let data = serde_json::to_vec(v).unwrap_or_default();
        self.bytes(status, "application/json; charset=utf-8", &data, &[])
    }

    pub fn bytes(&mut self, status: u16, mime: &str, data: &[u8], extra: &[(&str, String)]) -> io::Result<()> {
        self.head(status, mime, Some(data.len() as u64), extra)?;
        if self.method != "HEAD" {
            self.out.write_all(data)?;
        }
        self.out.flush()
    }

    pub fn sse_start(&mut self) -> io::Result<()> {
        if !self.body_read {
            if let Ok(n) = self.content_length() {
                if n > 0 && n <= 1024 * 1024 {
                    self.body_read = true;
                    let mut sink = vec![0u8; n as usize];
                    let _ = self.reader.read_exact(&mut sink);
                }
            }
        }
        self.sse = true;
        self.close = true;
        self.responded = true;
        self.out.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\nCache-Control: no-cache, no-transform\r\nX-Accel-Buffering: no\r\nConnection: close\r\n\r\n")?;
        self.out.flush()
    }

    pub fn sse_send(&mut self, v: &Value, id: Option<u64>) -> io::Result<()> {
        let mut s = String::new();
        if let Some(i) = id {
            s.push_str(&format!("id: {i}\n"));
        }
        s.push_str("data: ");
        s.push_str(&serde_json::to_string(v).unwrap_or_default());
        s.push_str("\n\n");
        self.out.write_all(s.as_bytes())?;
        self.out.flush()
    }

    pub fn sse_comment(&mut self, text: &str) -> io::Result<()> {
        self.out.write_all(format!(": {text}\n\n").as_bytes())?;
        self.out.flush()
    }
}

pub fn reason(status: u16) -> &'static str {
    match status {
        200 => "OK",
        206 => "Partial Content",
        302 => "Found",
        304 => "Not Modified",
        400 => "Bad Request",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        409 => "Conflict",
        411 => "Length Required",
        413 => "Payload Too Large",
        416 => "Range Not Satisfiable",
        431 => "Request Header Fields Too Large",
        500 => "Internal Server Error",
        501 => "Not Implemented",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        _ => "OK",
    }
}
