//! Utilidades comuns do núcleo: JSON mínimo (escrita e leitura) e o protocolo de saída para o Python.
//!
//! As funções que devolvem texto escrevem JSON UTF-8 no buffer do chamador (`out`, `cap`) e retornam o tamanho escrito; se não couber, retornam o tamanho
//! necessário (maior que `cap`) e o Python chama de novo com um buffer maior. Erros: valor negativo. Nada aqui entra em pânico (a biblioteca compila com `panic = "abort"`).

use std::fmt::Write as _;

/// Escreve `s` no buffer do chamador. Devolve o tamanho de `s` (se maior que `cap`, nada foi escrito além do que coube).
pub fn put(out: *mut u8, cap: usize, s: &str) -> i64 {
    let b = s.as_bytes();
    if !out.is_null() && b.len() <= cap {
        unsafe { std::ptr::copy_nonoverlapping(b.as_ptr(), out, b.len()) };
    }
    b.len() as i64
}

pub fn esc(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    o.push('"');
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            '\r' => o.push_str("\\r"),
            '\t' => o.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(o, "\\u{:04x}", c as u32);
            }
            c => o.push(c),
        }
    }
    o.push('"');
    o
}

/// Construtor de objeto JSON plano (chaves em ordem de inserção).
pub struct Obj(String, bool);

impl Obj {
    pub fn new() -> Obj {
        Obj(String::from("{"), false)
    }
    fn key(&mut self, k: &str) {
        if self.1 {
            self.0.push(',');
        }
        self.1 = true;
        self.0.push_str(&esc(k));
        self.0.push(':');
    }
    pub fn s(mut self, k: &str, v: &str) -> Obj {
        self.key(k);
        self.0.push_str(&esc(v));
        self
    }
    pub fn i(mut self, k: &str, v: i64) -> Obj {
        self.key(k);
        let _ = write!(self.0, "{}", v);
        self
    }
    pub fn f(mut self, k: &str, v: f64) -> Obj {
        self.key(k);
        if v.is_finite() {
            let _ = write!(self.0, "{}", v);
        } else {
            self.0.push('0');
        }
        self
    }
    pub fn b(mut self, k: &str, v: bool) -> Obj {
        self.key(k);
        self.0.push_str(if v { "true" } else { "false" });
        self
    }
    #[allow(dead_code)]
    pub fn raw(mut self, k: &str, v: &str) -> Obj {
        self.key(k);
        self.0.push_str(v);
        self
    }
    pub fn strs(mut self, k: &str, v: &[String]) -> Obj {
        self.key(k);
        self.0.push('[');
        for (i, x) in v.iter().enumerate() {
            if i > 0 {
                self.0.push(',');
            }
            self.0.push_str(&esc(x));
        }
        self.0.push(']');
        self
    }
    pub fn end(mut self) -> String {
        self.0.push('}');
        self.0
    }
}

// --------------------------------------------------------------------------- leitor de JSON mínimo (cabeçalho do safetensors)
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub enum Val {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Val>),
    Obj(Vec<(String, Val)>),
}

impl Val {
    pub fn get(&self, k: &str) -> Option<&Val> {
        match self {
            Val::Obj(v) => v.iter().find(|(n, _)| n == k).map(|(_, x)| x),
            _ => None,
        }
    }
    pub fn as_str(&self) -> Option<&str> {
        match self {
            Val::Str(s) => Some(s),
            _ => None,
        }
    }
    pub fn as_f64(&self) -> Option<f64> {
        match self {
            Val::Num(n) => Some(*n),
            _ => None,
        }
    }
}

pub fn parse_json(s: &[u8]) -> Option<Val> {
    let mut p = P { s, i: 0, depth: 0 };
    let v = p.value()?;
    p.ws();
    Some(v)
}

struct P<'a> {
    s: &'a [u8],
    i: usize,
    depth: u32,
}

impl<'a> P<'a> {
    fn ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], b' ' | b'\n' | b'\r' | b'\t') {
            self.i += 1;
        }
    }
    fn eat(&mut self, c: u8) -> bool {
        self.ws();
        if self.i < self.s.len() && self.s[self.i] == c {
            self.i += 1;
            true
        } else {
            false
        }
    }
    fn lit(&mut self, w: &str) -> bool {
        if self.s[self.i..].starts_with(w.as_bytes()) {
            self.i += w.len();
            true
        } else {
            false
        }
    }
    fn string(&mut self) -> Option<String> {
        if !self.eat(b'"') {
            return None;
        }
        let mut out: Vec<u8> = Vec::new();
        while self.i < self.s.len() {
            let c = self.s[self.i];
            self.i += 1;
            match c {
                b'"' => return String::from_utf8(out).ok(),
                b'\\' => {
                    let e = *self.s.get(self.i)?;
                    self.i += 1;
                    match e {
                        b'n' => out.push(b'\n'),
                        b't' => out.push(b'\t'),
                        b'r' => out.push(b'\r'),
                        b'b' => out.push(8),
                        b'f' => out.push(12),
                        b'u' => {
                            let h = std::str::from_utf8(self.s.get(self.i..self.i + 4)?).ok()?;
                            self.i += 4;
                            let ch = char::from_u32(u32::from_str_radix(h, 16).ok()?).unwrap_or('?');
                            let mut b = [0u8; 4];
                            out.extend_from_slice(ch.encode_utf8(&mut b).as_bytes());
                        }
                        o => out.push(o),
                    }
                }
                o => out.push(o),
            }
        }
        None
    }
    fn value(&mut self) -> Option<Val> {
        self.ws();
        if self.depth > 32 || self.i >= self.s.len() {
            return None;
        }
        let c0 = self.s[self.i];
        match c0 {
            b'{' => {
                self.i += 1;
                self.depth += 1;
                let mut items = Vec::new();
                if !self.eat(b'}') {
                    loop {
                        let k = self.string()?;
                        if !self.eat(b':') {
                            return None;
                        }
                        items.push((k, self.value()?));
                        if self.eat(b',') {
                            continue;
                        }
                        if self.eat(b'}') {
                            break;
                        }
                        return None;
                    }
                }
                self.depth -= 1;
                Some(Val::Obj(items))
            }
            b'[' => {
                self.i += 1;
                self.depth += 1;
                let mut items = Vec::new();
                if !self.eat(b']') {
                    loop {
                        items.push(self.value()?);
                        if self.eat(b',') {
                            continue;
                        }
                        if self.eat(b']') {
                            break;
                        }
                        return None;
                    }
                }
                self.depth -= 1;
                Some(Val::Arr(items))
            }
            b'"' => self.string().map(Val::Str),
            b't' if self.lit("true") => Some(Val::Bool(true)),
            b'f' if self.lit("false") => Some(Val::Bool(false)),
            b'n' if self.lit("null") => Some(Val::Null),
            _ => {
                let st = self.i;
                while self.i < self.s.len() && matches!(self.s[self.i], b'-' | b'+' | b'.' | b'e' | b'E' | b'0'..=b'9') {
                    self.i += 1;
                }
                std::str::from_utf8(&self.s[st..self.i]).ok()?.parse::<f64>().ok().map(Val::Num)
            }
        }
    }
}
