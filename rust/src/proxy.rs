//! Repassa a requisição, byte a byte, ao worker Python e devolve a resposta (inclusive SSE) como veio.
//! O worker responde em HTTP/1.0 e fecha a conexão: copiar até o fim basta.

use crate::http::{HttpError, Req, Res};
use std::io::{Read, Write};
use std::net::TcpStream;

pub fn forward(req: &mut Req, port: u16) -> Res {
    let mut up = TcpStream::connect(("127.0.0.1", port)).map_err(|e| HttpError::new(502, format!("Worker Python indisponível: {e}")))?;
    let len = req.content_length()?;
    let mut head = format!("{} {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n", req.method, req.target, port);
    for (k, v) in &req.headers {
        // o Host/Origin do navegador já foram validados aqui; o worker só vê o endereço privado dele
        if matches!(k.as_str(), "host" | "origin" | "connection" | "keep-alive" | "proxy-connection" | "upgrade") {
            continue;
        }
        head.push_str(&format!("{k}: {v}\r\n"));
    }
    head.push_str("\r\n");
    up.write_all(head.as_bytes()).map_err(|e| HttpError::new(502, e.to_string()))?;
    // corpo (pode ser um upload grande: copia em blocos, sem guardar na memória)
    let mut left = len;
    let mut buf = vec![0u8; 256 * 1024];
    while left > 0 {
        let take = left.min(buf.len() as u64) as usize;
        let n = req.reader.read(&mut buf[..take]).map_err(|e| HttpError::new(400, e.to_string()))?;
        if n == 0 {
            break;
        }
        up.write_all(&buf[..n]).map_err(|e| HttpError::new(502, e.to_string()))?;
        left -= n as u64;
    }
    req.body_read = true;
    req.responded = true;
    req.close = true;
    loop {
        let n = match up.read(&mut buf) {
            Ok(0) | Err(_) => break,
            Ok(n) => n,
        };
        if req.out.write_all(&buf[..n]).is_err() {
            break; // o navegador fechou (ex.: parou de ouvir o SSE)
        }
        let _ = req.out.flush();
    }
    Ok(())
}
