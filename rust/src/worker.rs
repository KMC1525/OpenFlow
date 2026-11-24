//! O worker Python (opcional, em transição): o que ainda não foi portado para Rust roda no servidor Python do pacote `openflow`, escutando só em 127.0.0.1 numa porta privada.
//! O Rust o liga sob demanda (na primeira rota que precisa dele), repassa a requisição como está e o encerra junto com o `flow`.

use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub struct Worker {
    pub home: PathBuf,
    state: Mutex<State>,
}

struct State {
    child: Option<Child>,
    port: Option<u16>,
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

fn venv_python(home: &Path) -> PathBuf {
    let v = home.join("worker").join("venv");
    if cfg!(windows) { v.join("Scripts").join("python.exe") } else { v.join("bin").join("python") }
}

/// O Python que roda o worker: OPENFLOW_PYTHON, o venv do worker, ou um `python3`/`python`/`py -3` do sistema (3.9 ou mais novo). `(programa, argumentos antes do -m)`.
pub fn find_python(home: &Path) -> Option<(String, Vec<String>)> {
    let mut cands: Vec<(String, Vec<String>)> = Vec::new();
    if let Ok(p) = std::env::var("OPENFLOW_PYTHON") {
        if !p.is_empty() && p != "auto" && p != "keep" {
            cands.push((p, vec![]));
        }
    }
    let vp = venv_python(home);
    if vp.is_file() {
        cands.push((vp.to_string_lossy().into_owned(), vec![]));
    }
    cands.push(("python3".into(), vec![]));
    cands.push(("python".into(), vec![]));
    cands.push(("py".into(), vec!["-3".into()]));
    for (exe, pre) in cands {
        let ok = Command::new(&exe).args(&pre).args(["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"]).stdout(Stdio::null()).stderr(Stdio::null()).status().map(|s| s.success()).unwrap_or(false);
        if ok {
            return Some((exe, pre));
        }
    }
    None
}

impl Worker {
    pub fn new(home: PathBuf) -> Self {
        Worker { home, state: Mutex::new(State { child: None, port: None }) }
    }

    /// Comando `python [-3] -m openflow <args>` já com o PYTHONPATH do código do worker (usado também para os comandos do terminal ainda não portados).
    pub fn python_command(&self) -> Result<Command, String> {
        let src = source_dir(&self.home).ok_or_else(|| "O worker Python do OpenFlow não está instalado (rode: flow worker install).".to_string())?;
        let (exe, pre) = find_python(&self.home).ok_or_else(|| "Python 3.9 ou mais novo não encontrado (necessário só para os recursos que ainda dependem do worker Python).".to_string())?;
        let mut c = Command::new(exe);
        c.args(pre).arg("-m").arg("openflow").env("PYTHONPATH", src).env("PYTHONIOENCODING", "utf-8").env("OPENFLOW_HOME", &self.home);
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
        cmd.args(["worker", "--port", &port.to_string()]).env("OPENFLOW_NO_UPDATE", "1").stdin(Stdio::null());
        if std::env::var("OPENFLOW_WORKER_LOG").is_err() {
            cmd.stdout(Stdio::null());
        }
        let child = cmd.spawn().map_err(|e| format!("Não consegui iniciar o worker Python: {e}"))?;
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
        }
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        self.stop();
    }
}
