//! O worker Python (opcional, em transição): o que ainda não foi portado para Rust roda no servidor Python do pacote `openflow`, escutando só em 127.0.0.1 numa porta privada.
//! O Rust o liga sob demanda (na primeira rota que precisa dele), repassa a requisição como está e o encerra junto com o `flow`.

use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub struct Worker {
    pub home: PathBuf,
    state: Mutex<State>,
}

struct State {
    child: Option<Child>,
    port: Option<u16>,
    keep: Option<ChildStdin>, // mantida aberta: quando o `flow` morre, ela fecha e o worker encerra junto
}

pub fn exe_name(base: &str) -> String {
    if cfg!(windows) { format!("{base}.exe") } else { base.to_string() }
}

/// A pasta que contém o pacote `openflow/` (o código do worker): OPENFLOW_WORKER_SRC, `<home>/worker/src` ou, no desenvolvimento, a pasta do repositório acima do binário.
pub fn source_dir(home: &Path) -> Option<PathBuf> {
    let mut cands: Vec<PathBuf> = Vec::new();
    if let Ok(p) = std::env::var("OPENFLOW_WORKER_SRC") {
        if !p.is_empty() {
            cands.push(PathBuf::from(p));
        }
    }
    cands.push(home.join("worker").join("src"));
    if let Ok(exe) = std::env::current_exe() {
        let mut d = exe.parent().map(|p| p.to_path_buf());
        for _ in 0..5 {
            if let Some(dir) = d {
                cands.push(dir.clone());
                d = dir.parent().map(|p| p.to_path_buf());
            } else {
                break;
            }
        }
    }
    cands.into_iter().find(|c| c.join("openflow").join("__init__.py").is_file())
}

/// O venv do instalador: OPENFLOW_APP_DIR/venv, ou a pasta padrão do instalador do sistema (`~/.openflow/app` no Linux/macOS, `%LOCALAPPDATA%\\OpenFlow\\app` no Windows).
fn app_venv_python(home: &Path) -> Vec<PathBuf> {
    let mut dirs: Vec<PathBuf> = Vec::new();
    if let Ok(d) = std::env::var("OPENFLOW_APP_DIR") {
        if !d.is_empty() {
            dirs.push(PathBuf::from(d));
        }
    }
    dirs.push(home.join("app"));
    if let Ok(l) = std::env::var("LOCALAPPDATA") {
        dirs.push(PathBuf::from(l).join("OpenFlow").join("app"));
    }
    dirs.push(home.join("worker"));
    dirs.into_iter().map(|d| if cfg!(windows) { d.join("venv").join("Scripts").join("python.exe") } else { d.join("venv").join("bin").join("python") }).filter(|p| p.is_file()).collect()
}

/// Um Python que roda o worker: o programa, argumentos antes do `-m` e se ele precisa do PYTHONPATH do código-fonte (o do venv do instalador já tem o `openflow` instalado).
pub struct Py {
    pub exe: String,
    pub pre: Vec<String>,
    pub needs_src: bool,
}

fn runs(exe: &str, pre: &[String], code: &str) -> bool {
    Command::new(exe).args(pre).args(["-c", code]).stdout(Stdio::null()).stderr(Stdio::null()).status().map(|s| s.success()).unwrap_or(false)
}

/// O Python do worker: OPENFLOW_PYTHON, o venv do instalador (com o `openflow` instalado) ou um `python3`/`python`/`py -3` do sistema (3.9+, com o código-fonte do worker no PYTHONPATH).
pub fn find_python(home: &Path) -> Option<Py> {
    let ver = "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)";
    let has_pkg = "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1); import openflow";
    let has_src = source_dir(home).is_some();
    let mut cands: Vec<(String, Vec<String>)> = Vec::new();
    if let Ok(p) = std::env::var("OPENFLOW_PYTHON") {
        if !p.is_empty() && p != "auto" && p != "keep" {
            cands.push((p, vec![]));
        }
    }
    for v in app_venv_python(home) {
        cands.push((v.to_string_lossy().into_owned(), vec![]));
    }
    cands.push(("python3".into(), vec![]));
    cands.push(("python".into(), vec![]));
    cands.push(("py".into(), vec!["-3".into()]));
    for (exe, pre) in cands {
        if !runs(&exe, &pre, ver) {
            continue;
        }
        if runs(&exe, &pre, "import openflow") {
            return Some(Py { exe, pre, needs_src: false });   // venv do instalador (ou o OpenFlow instalado com pip)
        }
        if has_src {
            return Some(Py { exe, pre, needs_src: true });
        }
    }
    let _ = has_pkg;
    None
}

impl Worker {
    pub fn new(home: PathBuf) -> Self {
        Worker { home, state: Mutex::new(State { child: None, port: None, keep: None }) }
    }

    /// Comando `python [-3] -m openflow <args>` já com o PYTHONPATH do código do worker (usado também para os comandos do terminal ainda não portados).
    pub fn python_command(&self) -> Result<Command, String> {
        let py = find_python(&self.home).ok_or_else(|| "O worker Python do OpenFlow não foi encontrado (Python 3.9+ com o pacote openflow; rode o instalador de novo).".to_string())?;
        let mut c = Command::new(&py.exe);
        c.args(&py.pre).arg("-m").arg("openflow").env("PYTHONIOENCODING", "utf-8").env("OPENFLOW_HOME", &self.home);
        if py.needs_src {
            if let Some(src) = source_dir(&self.home) {
                c.env("PYTHONPATH", src);
            }
        }
        Ok(c)
    }

    /// Garante o worker no ar e devolve a porta.
    pub fn ensure(&self) -> Result<u16, String> {
        let mut st = self.state.lock().map_err(|_| "worker travado".to_string())?;
        let port_now = st.port;
        if let (Some(child), Some(port)) = (st.child.as_mut(), port_now) {
            if child.try_wait().ok().flatten().is_none() {
                return Ok(port);
            }
        }
        st.child = None;
        st.port = None;
        let listener = TcpListener::bind(("127.0.0.1", 0)).map_err(|e| e.to_string())?;
        let port = listener.local_addr().map_err(|e| e.to_string())?.port();
        drop(listener);
        let mut cmd = self.python_command()?;
        cmd.args(["worker", "--port", &port.to_string(), "--watch-stdin"]).env("OPENFLOW_NO_UPDATE", "1").stdin(Stdio::piped());
        if std::env::var("OPENFLOW_WORKER_LOG").is_err() {
            cmd.stdout(Stdio::null());
        }
        let mut child = cmd.spawn().map_err(|e| format!("Não consegui iniciar o worker Python: {e}"))?;
        st.keep = child.stdin.take();
        st.child = Some(child);
        st.port = Some(port);
        let t0 = Instant::now();
        while t0.elapsed() < Duration::from_secs(40) {
            if TcpStream::connect_timeout(&format!("127.0.0.1:{port}").parse().unwrap(), Duration::from_millis(300)).is_ok() {
                return Ok(port);
            }
            if let Some(c) = st.child.as_mut() {
                if let Ok(Some(status)) = c.try_wait() {
                    st.child = None;
                    st.port = None;
                    return Err(format!("O worker Python terminou ao iniciar ({status})."));
                }
            }
            std::thread::sleep(Duration::from_millis(80));
        }
        Err("O worker Python não respondeu a tempo.".into())
    }

    /// A porta do worker se ele já está no ar (não o liga).
    pub fn running_port(&self) -> Option<u16> {
        let mut st = self.state.lock().ok()?;
        let port = st.port?;
        let alive = st.child.as_mut().map(|c| c.try_wait().ok().flatten().is_none()).unwrap_or(false);
        if alive { Some(port) } else { None }
    }

    /// Avisa o worker (se estiver no ar) de que as configurações mudaram em disco: ele relê pastas de armazenamento e desempenho.
    pub fn notify_settings(&self) {
        if let Some(port) = self.running_port() {
            use std::io::{Read, Write};
            if let Ok(mut s) = TcpStream::connect(("127.0.0.1", port)) {
                let _ = s.set_read_timeout(Some(Duration::from_secs(5)));
                let _ = s.write_all(format!("POST /api/_internal/reload HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes());
                let mut sink = Vec::new();
                let _ = s.read_to_end(&mut sink);
            }
        }
    }

    pub fn stop(&self) {
        if let Ok(mut st) = self.state.lock() {
            if let Some(mut c) = st.child.take() {
                let _ = c.kill();
                let _ = c.wait();
            }
            st.port = None;
            st.keep = None;
        }
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        self.stop();
    }
}
