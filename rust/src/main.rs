//! `flow` — o OpenFlow em Rust (v0.91). Um binário: servidor HTTP, interface web embutida e a linha de comando.

mod app;
mod assets;
mod dev;
mod http;
mod proxy;
mod routes;
mod settings;
mod uiprefs;
mod util;
mod worker;

use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Command, ExitCode};
use std::sync::Arc;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

const BANNER: &str = r"
   ___                   _____ _
  / _ \ _ __   ___ _ __ |  ___| | _____      __
 | | | | '_ \ / _ \ '_ \| |_  | |/ _ \ \ /\ / /
 | |_| | |_) |  __/ | | |  _| | | (_) \ V  V /
  \___/| .__/ \___|_| |_|_|   |_|\___/ \_/\_/     v";

pub fn home_dir(arg: Option<&str>) -> PathBuf {
    if let Some(h) = arg.filter(|s| !s.is_empty()) {
        return PathBuf::from(h);
    }
    if let Ok(h) = std::env::var("OPENFLOW_HOME") {
        if !h.is_empty() {
            return PathBuf::from(h);
        }
    }
    let base = std::env::var("USERPROFILE").or_else(|_| std::env::var("HOME")).unwrap_or_else(|_| ".".into());
    PathBuf::from(base).join(".openflow")
}

fn open_browser(url: &str) {
    let r = if cfg!(windows) {
        Command::new("cmd").args(["/c", "start", "", url]).spawn()
    } else if cfg!(target_os = "macos") {
        Command::new("open").arg(url).spawn()
    } else {
        Command::new("xdg-open").arg(url).spawn()
    };
    let _ = r;
}

struct RunArgs {
    host: String,
    port: u16,
    no_browser: bool,
    home: Option<String>,
}

fn parse_run(args: &[String]) -> Result<RunArgs, String> {
    let mut r = RunArgs { host: "127.0.0.1".into(), port: 8787, no_browser: false, home: None };
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--host" => r.host = it.next().ok_or("--host precisa de um valor")?.clone(),
            "--port" => r.port = it.next().ok_or("--port precisa de um valor")?.parse().map_err(|_| "porta inválida".to_string())?,
            "--home" => r.home = Some(it.next().ok_or("--home precisa de um valor")?.clone()),
            "--no-browser" => r.no_browser = true,
            "--no-update" => {}
            "run" => {}
            other => return Err(format!("argumento desconhecido: {other}")),
        }
    }
    Ok(r)
}

fn run(args: &[String]) -> ExitCode {
    let a = match parse_run(args) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("flow: {e}");
            return ExitCode::from(2);
        }
    };
    let home = home_dir(a.home.as_deref());
    let _ = std::fs::create_dir_all(&home);
    std::env::set_var("OPENFLOW_HOME", &home);
    let mut bound = None;
    for p in a.port..a.port.saturating_add(20) {
        if let Ok(l) = TcpListener::bind((a.host.as_str(), p)) {
            bound = Some((l, p));
            break;
        }
    }
    let Some((listener, port)) = bound else {
        eprintln!("Não foi possível abrir nenhuma porta entre {} e {}.", a.port, a.port + 19);
        return ExitCode::from(1);
    };
    let shown = if matches!(a.host.as_str(), "127.0.0.1" | "0.0.0.0" | "::") { "localhost" } else { a.host.as_str() };
    let url = format!("http://{shown}:{port}/");
    println!("{BANNER}{VERSION}\n");
    println!("  WebUI:   {url}");
    println!("  Dados:   {}", home.display());
    if !matches!(a.host.as_str(), "127.0.0.1" | "localhost" | "::1") {
        println!("  Rede:    o OpenFlow está acessível por outros aparelhos da sua rede (sem senha): use só em redes de confiança.");
    }
    println!("  Pare com Ctrl+C.\n");
    let application = Arc::new(app::App::new(home, &a.host));
    if !a.no_browser {
        let u = url.clone();
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(800));
            open_browser(&u);
        });
    }
    app::serve(application, listener);
    ExitCode::SUCCESS
}

/// Comandos do terminal ainda não portados: rodam no Python do worker (`python -m openflow <args>`).
fn delegate(args: &[String]) -> ExitCode {
    let home = home_dir(None);
    let w = worker::Worker::new(home);
    match w.python_command() {
        Ok(mut c) => match c.args(args).status() {
            Ok(s) => ExitCode::from(s.code().unwrap_or(1).clamp(0, 255) as u8),
            Err(e) => {
                eprintln!("flow: não consegui rodar o Python: {e}");
                ExitCode::from(1)
            }
        },
        Err(e) => {
            eprintln!("flow: {e}");
            ExitCode::from(1)
        }
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(|s| s.as_str()) {
        None => run(&args),
        Some("version") | Some("--version") | Some("-V") => {
            println!("{VERSION}");
            ExitCode::SUCCESS
        }
        Some("run") => run(&args[1..]),
        Some("dev") => dev::run(&args[1..]),
        Some(a) if a.starts_with("--") => run(&args),
        Some(_) => delegate(&args),
    }
}
