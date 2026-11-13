"""Linha de comando do OpenFlow — o comando `flow`:  flow [run|setup|update|libs|models|native|folder|doctor|version]"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from . import __version__
from .termi18n import _, system_lang

REPO_ZIP = "https://github.com/KMC1525/OpenFlow/archive/refs/heads/main.zip"
BANNER = r"""
   ___                   _____ _
  / _ \ _ __   ___ _ __ |  ___| | _____      __
 | | | | '_ \ / _ \ '_ \| |_  | |/ _ \ \ /\ / /
 | |_| | |_) |  __/ | | |  _| | | (_) \ V  V /
  \___/| .__/ \___|_| |_|_|   |_|\___/ \_/\_/     v{version}
       |_|
"""


def _windows() -> bool:
    return os.name == "nt"


def _auto_update(args: argparse.Namespace, argv) -> object:
    """Ao abrir o OpenFlow pelo comando `flow`: atualiza/instala tudo como o comando de instalação (Python, OpenFlow, bibliotecas, modelos pré-instalados).
    Roda quando há versão nova publicada e, mesmo sem ela, a cada OPENFLOW_UPDATE_EVERY horas (padrão 24; 0 = a cada abertura) — o instalador pula o que já está em dia.
    Só vale para o OpenFlow instalado pelo instalador oficial (instalação manual/editável nunca é mexida); sem internet, abre normalmente.
    Devolve None para seguir abrindo; um número para encerrar com esse código (Windows: o instalador continua numa janela nova)."""
    import time
    from pathlib import Path

    if getattr(args, "no_update", False) or os.environ.get("OPENFLOW_NO_UPDATE", "") not in ("", "0"):
        return None
    if _managed_app_dir() is None:
        if os.environ.get("OPENFLOW_INSTALLER"):   # instalador do Windows / AppImage: não se atualizam sozinhos, mas avisam (uma linha) quando há versão nova
            remote = _remote_version(timeout=4.0)
            if remote and _version_tuple(remote) > _version_tuple(__version__):
                print(_("Há uma versão nova do OpenFlow ({v}). Para atualizar: flow update  (ou baixe o instalador novo em https://github.com/KMC1525/OpenFlow/releases/latest)", v=remote) + "\n")
        return None
    home = Path(args.home or os.environ.get("OPENFLOW_HOME") or Path.home() / ".openflow").expanduser()
    stamp = home / ".last-update"
    try:
        hours = float(os.environ.get("OPENFLOW_UPDATE_EVERY", "24"))
    except ValueError:
        hours = 24.0
    remote = _remote_version(timeout=6.0)
    if remote is None:  # sem internet (ou GitHub fora do ar): abre do jeito que está
        return None
    newer = _version_tuple(remote) > _version_tuple(__version__)
    try:
        due = time.time() - stamp.stat().st_mtime >= hours * 3600
    except OSError:
        due = True
    if not newer and not due:
        return None
    print(f"OpenFlow {__version__}: " + (_("há uma versão nova ({v}). ", v=remote) if newer else _("verificando atualizações. ")) + _("Atualizando o Python, o OpenFlow e as bibliotecas (para pular: flow --no-update)…"))
    code = _update_with_installer(argparse.Namespace(force=False, core=False, extras="", no_python=False, rust=""))
    if code != 0:
        print(_("Não foi possível atualizar agora; abrindo o OpenFlow como está."))
        return None
    try:
        home.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass
    if _windows():
        return 0  # o instalador segue numa janela nova e o OpenFlow precisa estar fechado para ele trocar os arquivos
    print("\n" + _("Abrindo o OpenFlow atualizado…") + "\n")
    sys.stdout.flush()
    os.execve(sys.executable, [sys.executable, "-m", "openflow", *list(argv)], dict(os.environ, OPENFLOW_NO_UPDATE="1"))
    return None  # pragma: no cover


def _run(args: argparse.Namespace) -> int:
    if args.home:
        os.environ["OPENFLOW_HOME"] = args.home
    from . import native
    from .server import make_server
    from .storage import Store

    if not getattr(args, "no_update", False):
        native.ensure()   # núcleo Rust obrigatório: sem ele, baixa a biblioteca pré-compilada em segundo plano (sem compilador, no máximo 1 vez por dia)
    store = Store()
    httpd = None
    port = args.port
    for candidate in range(port, port + 20):
        try:
            httpd, app = make_server(args.host, candidate, store)
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        print(_("Não foi possível abrir nenhuma porta entre {a} e {b}.", a=args.port, b=args.port + 19), file=sys.stderr)
        return 1
    shown = "localhost" if args.host in ("127.0.0.1", "0.0.0.0", "::") else args.host
    url = f"http://{shown}:{port}/"
    print(BANNER.format(version=__version__))
    print(f"  WebUI:   {url}")
    print(_("  Dados:   {p}", p=store.home))
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(_("  Rede:    o OpenFlow está acessível por outros aparelhos da sua rede (sem senha): use só em redes de confiança."))
    print(_("  Pare com Ctrl+C.") + "\n")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\n" + _("Até logo!"))
    finally:
        httpd.server_close()
    return 0


# Bibliotecas opcionais do OpenFlow (extras do pacote): nome → para que servem. A ordem é da mais leve para a mais pesada.
LIBS = {
    "docs": "extração de PDFs mais precisa",
    "media": "modelos locais de imagem, vídeo, som e voz (PyTorch, diffusers, transformers — vários GB)",
    "local": "modelos GGUF embutidos: texto, imagem e vídeo (llama-cpp-python e stable-diffusion-cpp-python; compilam código nativo)",
}


def _lib_desc(extra: str) -> str:
    return _(LIBS[extra])


def _wanted_libs(spec: str):
    """Extras escolhidos: "" ou "all" = todos; "none" = nenhum; ou uma lista separada por vírgula. Devolve (lista, desconhecidos)."""
    spec = (spec or os.environ.get("OPENFLOW_EXTRAS") or "all").strip().lower()
    if spec in ("none", "core", "no", "0"):
        return [], []
    names = [x.strip() for x in spec.replace(";", ",").split(",") if x.strip()]
    if "all" in names:
        return list(LIBS), []
    return [n for n in LIBS if n in names], [n for n in names if n not in LIBS]


def _lib_requirements(extra: str):
    """Requisitos pip de um extra, lidos dos metadados do OpenFlow instalado (sempre os da versão atual)."""
    import re
    from importlib import metadata

    out = []
    for line in metadata.requires("openflow") or []:
        req, _, marker = line.partition(";")
        if re.search(r"extra\s*==\s*[\"']%s[\"']" % re.escape(extra), marker):
            out.append(req.strip())
    return out


def _req_name(req: str) -> str:
    import re

    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
    return m.group(1) if m else req.strip()


def _installed_version(req: str):
    """Versão instalada da biblioteca de um requisito pip, ou None se ela não está neste ambiente."""
    from importlib import metadata

    try:
        return metadata.version(_req_name(req))
    except Exception:  # noqa: BLE001  (PackageNotFoundError e metadados quebrados)
        return None


def _ensure_pip() -> bool:
    """O Python embutido do instalador do Windows não traz o pip: instala (ensurepip ou, se faltar, o get-pip.py oficial). True se o pip está disponível."""
    import importlib.util

    if importlib.util.find_spec("pip") is not None:
        return True
    print(_("Instalando o pip neste Python (uma vez) …"))
    try:
        import ensurepip  # noqa: F401

        if subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], capture_output=True).returncode == 0:
            return True
    except ImportError:
        pass
    import tempfile
    import urllib.request

    from .util import ssl_context

    try:
        with urllib.request.urlopen("https://bootstrap.pypa.io/get-pip.py", timeout=60, context=ssl_context()) as resp:
            data = resp.read()
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as fh:
            fh.write(data)
            path = fh.name
        try:
            return subprocess.run([sys.executable, path, "--no-warn-script-location", "--disable-pip-version-check"]).returncode == 0
        finally:
            os.unlink(path)
    except Exception as exc:  # noqa: BLE001  (sem internet…)
        print(_("Não consegui instalar o pip ({e}). Sem ele não dá para instalar bibliotecas opcionais nem atualizar por aqui; baixe o instalador novo em https://github.com/KMC1525/OpenFlow/releases/latest", e=str(exc)[:120]))
        return False


def _sd_cli_install() -> int:
    """`flow libs --sd-cli`: baixa o sd-cli pré-compilado da stable-diffusion.cpp (sem git nem compilador) para a pasta de dados."""
    from .canvas import sdcli
    from .providers import ProviderError

    last = [0.0]

    def progress(done: int, total: int) -> None:
        if total and time.time() - last[0] > 2:
            last[0] = time.time()
            print("  " + _("{p}% baixado", p=int(100 * done / total)), flush=True)

    try:
        exe = sdcli.install(progress, lambda: False, lambda m: print(m, flush=True))
    except ProviderError as exc:
        print("⚠  " + str(exc), file=sys.stderr)
        return 1
    print(_("sd-cli instalado em {p}. O OpenFlow o usa nos modelos que a biblioteca Python não reconhece.", p=exe))
    return 0


def _libs(args: argparse.Namespace) -> int:
    """Instala o que falta e atualiza (só se houver versão mais nova) as bibliotecas opcionais do OpenFlow. Uma que falhe não impede as outras.
    O que já está instalado não é instalado de novo: o pip só mexe nele se existir uma versão mais nova."""
    if getattr(args, "sd_cli", False):
        return _sd_cli_install()
    chosen, unknown = _wanted_libs(getattr(args, "extras", "") or "")
    sd_force = bool(getattr(args, "sd_latest", False))
    if unknown:
        print(_("Bibliotecas desconhecidas: {u}. Opções: {o}, all, none.", u=", ".join(unknown), o=", ".join(LIBS)), file=sys.stderr)
        return 2
    if not chosen and not sd_force:
        print(_("Bibliotecas opcionais: nada a instalar (OPENFLOW_EXTRAS=none)."))
        return 0
    if not _ensure_pip():
        return 1
    failed, present = [], []
    for extra in chosen:
        reqs = _lib_requirements(extra)
        if not reqs:
            print(_("Bibliotecas «{x}»: nenhuma listada nesta versão — pulando.", x=extra))
            continue
        have = {r: _installed_version(r) for r in reqs}
        missing = [r for r in reqs if not have[r]]
        base = [sys.executable, "-m", "pip", "install", "--upgrade", "--upgrade-strategy", "eager", "--disable-pip-version-check"]
        if not missing:
            print("\n" + _("Bibliotecas «{x}» ({d}): já instaladas ({v}) — só atualizo se houver versão mais nova.", x=extra, d=_lib_desc(extra), v=", ".join(f"{_req_name(r)} {v}" for r, v in have.items())))
            res = subprocess.run([*base, "--quiet", *reqs])
            if res.returncode != 0:
                print(_("⚠  Não consegui verificar atualizações de «{x}» agora (sem internet?); sigo com as versões instaladas.", x=extra))
            present.append(extra)
            continue
        ok_now = [r for r in reqs if have[r]]
        print("\n" + _("Bibliotecas «{x}» ({d}): instalando {m}", x=extra, d=_lib_desc(extra), m=", ".join(missing)) + (_(" · já instaladas (só atualizo se precisar): {k}", k=", ".join(ok_now)) if ok_now else ""))
        res = subprocess.run([*base, *reqs])
        if res.returncode != 0:
            failed.append(extra)
            print(_("⚠  Não foi possível instalar «{x}». O OpenFlow funciona sem ela; tente de novo depois com:  flow libs --extras {x}", x=extra))
    if ("local" in chosen or sd_force) and not _sd_latest(sd_force):
        failed.append("local (stable-diffusion.cpp mais nova)")
    if not chosen:   # só a stable-diffusion.cpp (botão do nó): sem o resumo das outras bibliotecas
        return 1 if failed else 0
    ok = [e for e in chosen if e not in failed]
    print("\n" + _("Bibliotecas prontas: {l}", l=", ".join(ok) or _("nenhuma")) + (_(" (já estavam instaladas: {p})", p=", ".join(present)) if present else "")
          + (_(" · com falha: {f}", f=", ".join(failed)) if failed else ""))
    return 1 if failed else 0


SD_GIT = "stable-diffusion-cpp-python @ git+https://github.com/william-murray1204/stable-diffusion-cpp-python.git"   # a versão do PyPI (0.4.7) pode ser mais antiga que os modelos novos; a do GitHub traz a stable-diffusion.cpp mais recente


def _sd_dir():
    from .util import flow_home

    return flow_home()


def _sd_marker():
    return _sd_dir() / "sd_needs_newer"   # escrito pelo OpenFlow quando a stable-diffusion.cpp instalada não reconhece um modelo («get sd version from file failed»)


def _sd_remote_sha() -> str:
    """O commit mais novo da stable-diffusion-cpp-python no GitHub (vazio se não deu para consultar)."""
    try:
        r = subprocess.run(["git", "ls-remote", SD_GIT.split("@ git+", 1)[1], "HEAD"], capture_output=True, text=True, timeout=30)
        return str(r.stdout).split()[0] if r.returncode == 0 and str(r.stdout).split() else ""
    except Exception:  # noqa: BLE001  (sem git, sem rede, tempo esgotado…)
        return ""


def _uses_diffusion_ggufs() -> bool:
    """A pessoa tem GGUF de difusão de imagem (Qwen-Image, FLUX…) baixado? Esses modelos dependem da stable-diffusion.cpp mais nova."""
    from .canvas import support

    folder = _sd_dir() / "models" / "image"
    try:
        return any(support.family_of(f.name) for f in folder.glob("*.gguf"))
    except OSError:
        return False


def _build_tools_missing() -> list:
    """O que falta para compilar a stable-diffusion.cpp: git e um compilador C/C++. (O cmake e o ninja o próprio pip baixa na hora de compilar, não precisam estar instalados.)"""
    if os.name == "nt":
        return []   # no Windows o compilador (Visual Studio Build Tools) é conferido pelo próprio pip, que mostra o erro
    return [t for t in ("git",) if not shutil.which(t)] + ([] if any(shutil.which(c) for c in ("cc", "gcc", "clang")) else ["compilador C/C++"])


def _build_tools_hint() -> str:
    if sys.platform == "darwin":
        return "xcode-select --install"
    return "sudo apt install git build-essential" if shutil.which("apt") else "sudo dnf install git gcc-c++" if shutil.which("dnf") else "instale git e um compilador C/C++"


def _sd_latest(force: bool = False) -> bool:
    """Mantém a stable-diffusion-cpp-python na versão mais nova do GitHub (compila a stable-diffusion.cpp: precisa de git e de um compilador C/C++, e leva alguns minutos). O PyPI parou na 0.4.7.
    OPENFLOW_SD_LATEST=auto (padrão): na instalação e na atualização, quando o OpenFlow avisou que um modelo não foi reconhecido ou a pessoa tem GGUF de difusão (Qwen-Image, FLUX…) — e só se o GitHub
    tem commit novo desde a última compilação; =always: sempre que houver commit novo; =never: nunca. `force` (flow libs --sd-latest) compila sem perguntar.
    True se instalou ou não era preciso; False se tentou e falhou (o OpenFlow continua com a versão que já tinha)."""
    mode = (os.environ.get("OPENFLOW_SD_LATEST") or "auto").strip().lower()
    marker, built = _sd_marker(), _sd_dir() / "sd_built_sha"
    if mode in ("never", "no", "0") and not force:
        return True
    wanted = force or mode in ("always", "yes", "1") or marker.exists() or _uses_diffusion_ggufs()
    if not wanted:
        return True
    remote = _sd_remote_sha()
    try:
        have = built.read_text(encoding="utf-8").strip()
    except OSError:
        have = ""
    if not force and not marker.exists() and remote and remote == have:
        print("\n" + _("stable-diffusion-cpp-python: já está na versão mais recente do GitHub."))
        return True
    miss = _build_tools_missing()
    if miss:
        print("\n" + _("⚠  Para compilar a stable-diffusion.cpp mais nova falta: {m}. Instale com:  {c}  — e rode de novo:  flow libs --sd-latest", m=", ".join(miss), c=_build_tools_hint()))
        return False
    print("\n" + _("Instalando a stable-diffusion-cpp-python mais nova (do GitHub): compila código nativo e pode levar vários minutos…"))
    res = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-deps", "--no-cache-dir", "--disable-pip-version-check", SD_GIT])
    if res.returncode != 0:
        print(_("⚠  Não consegui compilar a versão mais nova. O OpenFlow segue com a que já está instalada; tente de novo depois com:  flow libs --sd-latest"))
        return False
    for f in (marker,):
        try:
            f.unlink()
        except OSError:
            pass
    if remote:
        try:
            built.write_text(remote, encoding="utf-8")
        except OSError:
            pass
    print(_("stable-diffusion-cpp-python atualizada. Abra o OpenFlow de novo para usá-la."))
    return True


RAW = "https://raw.githubusercontent.com/KMC1525/OpenFlow/main/"


def _version_tuple(v: str):
    import re

    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4])


def _remote_version(timeout: float = 20.0):
    """Versão do OpenFlow publicada na branch principal (OPENFLOW_VERSION_URL troca o endereço), ou None se não deu para consultar."""
    import re
    import urllib.request

    try:
        with urllib.request.urlopen(os.environ.get("OPENFLOW_VERSION_URL") or RAW + "openflow/__init__.py", timeout=timeout) as resp:
            m = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", resp.read(8192).decode("utf-8", "replace"))
        return m.group(1) if m else None
    except Exception:  # noqa: BLE001
        return None


def _flow_is_current(force: bool = False) -> bool:
    """True se o OpenFlow instalado já é a versão publicada (ou mais nova): nesse caso não há o que baixar nem reinstalar."""
    if force or os.environ.get("OPENFLOW_FORCE", "") not in ("", "0"):
        return False
    remote = _remote_version()
    return bool(remote) and _version_tuple(remote) <= _version_tuple(__version__)


def _managed_app_dir():
    """Pasta do programa se este OpenFlow foi instalado pelo instalador oficial (…/app/venv); None se foi instalado à mão (pip, editável)."""
    from pathlib import Path

    prefix = Path(sys.prefix).resolve()
    if prefix.name != "venv":
        return None
    default = (Path(os.environ["LOCALAPPDATA"]) / "OpenFlow" / "app") if os.name == "nt" and os.environ.get("LOCALAPPDATA") else Path.home() / ".openflow" / "app"
    app = Path(os.environ.get("OPENFLOW_APP_DIR") or default).expanduser().resolve()
    return app if prefix == app / "venv" else None


def _update_with_installer(args: argparse.Namespace) -> int:
    """Roda o instalador oficial: ele atualiza o Python (e o pip/setuptools/wheel), o OpenFlow e as bibliotecas — o mesmo que o comando de instalação.
    Devolve o código de saída, ou -1 se não foi possível usar o instalador (sem internet, instalação manual…)."""
    import tempfile
    import urllib.request

    app = _managed_app_dir()
    if app is None:
        if not os.environ.get("OPENFLOW_INSTALLER"):   # Windows (.exe) e AppImage têm o próprio Python: atualizam o OpenFlow com o pip, sem esta mensagem
            print(_("Este OpenFlow não foi instalado pelo instalador oficial: o Python do sistema não é gerenciado por ele (atualize-o pelo gerenciador de pacotes do seu sistema)."))
        return -1
    windows = os.name == "nt"
    name = "install.ps1" if windows else "install.sh"
    try:
        with urllib.request.urlopen(RAW + name, timeout=30) as resp:
            script = resp.read()
    except Exception as exc:  # noqa: BLE001
        print(_("Não foi possível baixar o instalador ({e}); atualizando só o OpenFlow e as bibliotecas.", e=exc))
        return -1
    env = dict(os.environ, OPENFLOW_APP_DIR=str(app), OPENFLOW_LANG=system_lang())   # o instalador fala o mesmo idioma
    if getattr(args, "rust", ""):
        env["OPENFLOW_RUST"] = args.rust
    if getattr(args, "force", False):
        env["OPENFLOW_FORCE"] = "1"
    if getattr(args, "core", False):
        env["OPENFLOW_EXTRAS"] = "none"
    elif getattr(args, "extras", ""):
        env["OPENFLOW_EXTRAS"] = args.extras
    with tempfile.NamedTemporaryFile("wb", suffix=os.path.splitext(name)[1], delete=False) as fh:
        fh.write(script)
        path = fh.name
    if windows:
        # o instalador recria arquivos que este processo está usando: ele continua numa janela nova, depois que o flow.exe terminar
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path], env=env, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        print(_("A atualização continua numa nova janela (Python, OpenFlow e bibliotecas). Quando terminar, abra o OpenFlow de novo."))
        return 0
    try:
        return subprocess.run(["sh", path], env=env).returncode
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


YES = ("s", "sim", "y", "yes")
NO = ("", "n", "nao", "não", "no")


def _ask_terminal(question: str, default: bool = False):
    """Pergunta sim/não no terminal e devolve True/False; None se não há um terminal para perguntar. Funciona também com `curl … | sh`,
    em que o stdin é o próprio script: nesse caso lê do terminal de verdade (/dev/tty, ou CONIN$ no Windows). Enter = o padrão (`default`, normalmente não)."""
    stream, opened = None, None
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            stream = sys.stdin
        else:
            opened = stream = open("CONIN$" if os.name == "nt" else "/dev/tty", "r", encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    try:
        print(f"\n{question} " + ("[S/n]" if default and system_lang() == "pt" else "[s/N]" if system_lang() == "pt" else "[Y/n]" if default else "[y/N]") + " ", end="", flush=True)
        for _try in range(3):
            line = stream.readline()
            if not line:  # fim da entrada: ninguém para responder
                print()
                return None
            answer = line.strip().lower()
            if answer in YES:
                return True
            if answer == "":
                return default
            if answer in NO:
                return False
            print(_("Responda s (sim) ou n (não): "), end="", flush=True)
        return False
    finally:
        if opened is not None:
            opened.close()


def _models(args: argparse.Namespace) -> int:
    """`flow models list|install`: os modelos locais pré-instalados (texto e imagem). `install --ask` pergunta (sim/não) antes de baixar;
    com OPENFLOW_MODELS definido (all, text, image…) a resposta já foi dada e não pergunta."""
    if getattr(args, "home", None):
        os.environ["OPENFLOW_HOME"] = args.home
    from . import preinstalled
    from .storage import Store

    store = Store()
    if args.action == "list":
        for m in preinstalled.status(store.models_dir):
            print(f"{'✓' if m['installed'] else '·'} {m['id']:<26} {m['kind']:<6} {m['label']} ({m['quant']}) · {m['size'] / 1024 ** 3:.1f} GB · {m['repo']}")
        return 0
    if args.action == "support":
        return _models_support(store)
    token = (store.get_settings().get("hf") or {}).get("token", "")
    explicit = args.which or os.environ.get("OPENFLOW_MODELS") or ""
    ask = _ask_terminal if getattr(args, "ask", False) and not explicit else None
    return preinstalled.install_selected(store, explicit or "all", token, ask=ask)


def _models_support(store) -> int:
    """`flow models support`: confere os arquivos de apoio (VAE, codificadores de texto, mmproj) de cada modelo instalado e baixa o que falta."""
    from . import hf
    from .canvas import support
    from .providers import ProviderError

    token = (store.get_settings().get("hf") or {}).get("token", "")
    todo, bad = 0, 0
    for kind in ("image", "video", "text"):
        folder = hf.kind_dir(store.models_dir, kind)
        for m in hf.local_models(store.models_dir, kind):
            st = support.status_of(folder, m["name"], kind)
            if not st["missing"]:
                if st["have"]:
                    print(f"✓ {m['name']}: " + ", ".join(f"{_(support.ROLE_LABEL[h['role']])} ({h['name']})" for h in st["have"]))
                continue
            todo += 1
            print(f"· {m['name']}: " + _("faltam {l} (≈ {g} GB)", l=", ".join(x["label"] for x in st["missing"]), g=st["approx_gb"]))
            try:
                res = support.install_with_model(folder, m["name"], kind, "", token, None, None, lambda: False, lambda x: print("  " + x, flush=True))
            except ProviderError as exc:
                print("⚠  " + str(exc))
                bad += 1
                continue
            for f in res["failed"]:
                print("⚠  " + _("{l}: não baixou ({e})", l=f["label"], e=f["error"]))
                bad += 1
    if not todo and not bad:
        print(_("Nenhum modelo instalado precisa de arquivos de apoio agora."))
    return 1 if bad else 0


def _setup(args: argparse.Namespace) -> int:
    """`flow setup` (ou `flow install`): conclui a instalação — bibliotecas opcionais, modelos pré-instalados (com VAE, codificadores de texto e mmproj) e o núcleo Rust. É o que o instalador roda no fim e pode ser repetido à vontade."""
    code = 0
    if getattr(args, "home", None):
        os.environ["OPENFLOW_HOME"] = args.home
    chosen = argparse.Namespace(extras=getattr(args, "extras", ""), sd_cli=False, sd_latest=False)
    if _libs(chosen) != 0:
        code = 1
    if os.environ.get("OPENFLOW_MODELS", "ask").lower() not in ("none", "no", "0"):
        if _models(argparse.Namespace(action="install", which="", ask=True, home=getattr(args, "home", None))) != 0:
            code = 1
    from . import native

    if native.setup(getattr(args, "rust", "") or os.environ.get("OPENFLOW_RUST") or "yes", ask=_ask_terminal) not in (0, None):
        print(_("Rust: não foi possível concluir agora (opcional; o OpenFlow usa Python). Tente depois:  flow native setup"))
    return code


def _update(args: argparse.Namespace) -> int:
    """Atualiza o Python, o OpenFlow e todas as bibliotecas dele — só o que ainda não está instalado ou tem versão mais nova. --core: só o OpenFlow e as ferramentas do Python; --no-python: sem mexer no Python."""
    if not getattr(args, "no_python", False) and not getattr(args, "core", False) and os.environ.get("OPENFLOW_PYTHON", "auto") != "keep":
        print(_("Atualizando o Python, o OpenFlow e as bibliotecas dele…"))
        code = _update_with_installer(args)
        if code >= 0:
            if code == 0 and os.name != "nt":
                print("\n" + _("Pronto! Reinicie o OpenFlow para usar a nova versão."))
            return code
    print(_("Verificando as ferramentas do Python e o OpenFlow…"))
    if not _ensure_pip():
        return 1
    subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "--disable-pip-version-check", "pip", "setuptools", "wheel"])  # já atualizadas = nada a fazer; falha = aviso
    if _flow_is_current(getattr(args, "force", False)):
        print(_("OpenFlow {v} já é a versão mais recente — nada a baixar. (Para reinstalar mesmo assim: flow update --force)", v=__version__))
    else:
        res = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "--no-cache-dir", REPO_ZIP])
        if res.returncode != 0:
            return res.returncode
    if not getattr(args, "core", False):
        # processo novo: lê os metadados da versão recém-instalada (ela pode ter bibliotecas novas)
        lib_cmd = [sys.executable, "-m", "openflow", "libs"] + (["--extras", args.extras] if getattr(args, "extras", "") else [])
        subprocess.run(lib_cmd)  # falhas de bibliotecas opcionais viram aviso; o OpenFlow já está atualizado
        subprocess.run([sys.executable, "-m", "openflow", "models", "install", "--ask"])  # modelos pré-instalados: pergunta antes de baixar (pula o que já existe)
        subprocess.run([sys.executable, "-m", "openflow", "native", "setup"] + (["--rust", args.rust] if getattr(args, "rust", "") else []))  # Rust: instala/atualiza (pergunta) e recompila o núcleo
    print("\n" + _("Pronto! Reinicie o OpenFlow para usar a nova versão."))
    return 0


def _native(args: argparse.Namespace) -> int:
    """`flow native status|build|install|update|setup`: o núcleo Rust opcional e o próprio Rust (instalar/atualizar)."""
    from . import native

    if args.action == "build":
        return native.build()
    if args.action == "install":
        code = native.install_rust()
        return code if code else native.build()
    if args.action == "update":
        native.update_rust()
        return native.build()
    if args.action == "setup":
        return native.setup(getattr(args, "rust", "") or os.environ.get("OPENFLOW_RUST") or "yes", ask=_ask_terminal)
    st = native.status()
    print(_("Núcleo Rust: ") + (_("ativo") if st["active"] else _("inativo — usando Python puro, mais lento (rode: flow native setup)")) + (f" — {_(st['reason'])}" if st["reason"] else ""))
    print("cargo: " + (native.rust_version() if st["cargo"] else _("não encontrado (opcional: o OpenFlow baixa a biblioteca pronta)")) + ("" if not st["cargo"] else " · rustup: " + (_("sim") if st["rustup"] else _("não"))))
    print(_("Interface: {a} · plataforma: {p} · biblioteca pronta da Release: {n}", a=st["abi"], p=native.platform_tag(), n=native.prebuilt_name()))
    return 0


def _folder(args: argparse.Namespace) -> int:
    """`flow folder`: abre a pasta dos dados locais do OpenFlow (conversas, projetos, mídias, modelos, configurações) no gerenciador de arquivos.
    `--print` só mostra o caminho; `--app` abre a pasta do programa instalado em vez da dos dados."""
    from pathlib import Path

    from .util import flow_home

    if getattr(args, "home", None):
        os.environ["OPENFLOW_HOME"] = args.home
    if getattr(args, "app", False):
        target = _managed_app_dir() or Path(__file__).resolve().parent
    else:
        target = Path(flow_home())
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    print(target)
    if getattr(args, "print", False):
        return 0
    try:
        if os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=True)
        else:
            subprocess.run(["xdg-open", str(target)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        print(_("Não consegui abrir o gerenciador de arquivos aqui; abra o caminho acima manualmente."))
        return 1
    return 0


def _doctor(_args: argparse.Namespace) -> int:
    from .util import flow_home, hardware_info

    hw = hardware_info(refresh=True)
    print(f"OpenFlow {__version__}")
    print(f"Python {hw['python']} · {hw['os']} {hw['arch']}")
    print(_("CPU: {n} núcleos · RAM: {r} GB · GPU: {g}", n=hw["cpus"], r=hw["ram_gb"], g=hw["gpu"] or _("não detectada (NVIDIA)")))
    print(_("Nível de hardware: {t}", t=hw["tier"]))
    try:
        from importlib import metadata

        print(f"pip {metadata.version('pip')} · setuptools {metadata.version('setuptools')}")
    except Exception:  # noqa: BLE001
        print(_("pip: não encontrado neste ambiente"))
    print("ffmpeg: " + (_("sim") if hw["ffmpeg"] else _("não (opcional: análise de vídeo/áudio)")))
    print(_("Pasta de dados: {p}", p=flow_home()))
    try:
        from . import native, perf

        nst = native.status()
        print(_("Núcleo Rust: ") + (_("ativo") if nst["active"] else _("inativo — usando Python puro, mais lento (rode: flow native setup)")))
        print("Rust: " + (native.rust_version() if nst["cargo"] else _("não instalado (não precisa: o OpenFlow baixa o núcleo pronto)")))
        print(_("Modo de desempenho: ") + _(perf.describe(perf.profile({}, hw))))
    except Exception:  # noqa: BLE001
        pass
    print(_("Idioma do terminal: {l}", l=system_lang()))
    try:
        import llama_cpp  # type: ignore  # noqa: F401

        print(_("Modelos locais embutidos (llama-cpp-python): disponível"))
    except ImportError:
        print(_('Modelos locais embutidos: não instalado (opcional: pip install "openflow[local]")'))
    try:
        from .providers import lmstudio

        lm = lmstudio.probe(timeout=1.5)
        if lm["running"]:
            print(_("LM Studio: rodando em {u} · modelo carregado: {m}", u=lm["url"], m=", ".join(lm["loaded"]) or _("nenhum (carregue um no LM Studio)")))
        else:
            print(_("LM Studio: não detectado em {u} (opcional: abra o LM Studio e ligue o servidor em Developer → Start Server)", u=lm["url"]))
    except Exception:  # noqa: BLE001
        pass
    libs = []
    for mod in ("torch", "diffusers", "transformers"):
        try:
            __import__(mod)
            libs.append(mod)
        except ImportError:
            pass
    if len(libs) == 3:
        print(_("Modelos locais de mídia do OpenFlow (torch, diffusers, transformers): disponível"))
    else:
        print(_('Modelos locais de mídia do OpenFlow: não instalado (opcional: pip install "openflow[media]")'))
    return 0


def main(argv=None) -> int:
    from .util import fix_default_certs

    fix_default_certs()   # macOS + Python do python.org: sem isto toda chamada HTTPS (atualização, modelos, Rust) falhava por falta de certificados
    parser = argparse.ArgumentParser(prog="flow", description=_("OpenFlow — criação criativa com IA em fluxos de nós (estilo ElevenLabs Flow): imagens, vídeos, sons e vozes, num app local, aberto e simples"))
    sub = parser.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help=_("inicia o OpenFlow no navegador (padrão)"))
    for p in (parser, run):
        p.add_argument("--host", default="127.0.0.1", help=_("endereço (padrão 127.0.0.1)"))
        p.add_argument("--port", type=int, default=8787, help=_("porta (padrão 8787)"))
        p.add_argument("--no-browser", action="store_true", help=_("não abrir o navegador"))
        p.add_argument("--home", help=_("pasta de dados (padrão ~/.openflow)"))
        p.add_argument("--no-update", action="store_true", help=_("não atualiza/instala nada ao abrir (também OPENFLOW_NO_UPDATE=1)"))
    for name in ("setup", "install"):
        st = sub.add_parser(name, help=_("conclui a instalação: bibliotecas, modelos pré-instalados (com VAE, codificadores de texto e mmproj) e o núcleo Rust"))
        st.add_argument("--extras", default="", help=_("bibliotecas: all (padrão), none ou lista (docs,media,local)"))
        st.add_argument("--rust", choices=("ask", "yes", "no"), default="", help=_("Rust: yes = faz sozinho (padrão), ask = pergunta, no = pula (também OPENFLOW_RUST)"))
        st.add_argument("--home", help=_("pasta de dados (padrão ~/.openflow)"))
    upd = sub.add_parser("update", help=_("atualiza o Python, o OpenFlow, as bibliotecas dele e (opcional) o Rust para a versão mais recente"))
    upd.add_argument("--core", action="store_true", help=_("atualiza só o OpenFlow (e pip/setuptools/wheel), sem o Python do sistema nem as bibliotecas opcionais"))
    upd.add_argument("--no-python", action="store_true", help=_("não atualiza o Python do sistema (atualiza o OpenFlow, o pip e as bibliotecas)"))
    upd.add_argument("--extras", default="", help=_("bibliotecas a atualizar: all (padrão), none ou lista (docs,media,local)"))
    upd.add_argument("--force", action="store_true", help=_("reinstala o OpenFlow mesmo que já esteja na versão mais recente"))
    upd.add_argument("--rust", choices=("ask", "yes", "no"), default="", help=_("Rust (núcleo rápido do OpenFlow): yes = instala/atualiza sozinho (padrão), ask = pergunta, no = pula (também OPENFLOW_RUST)"))
    mod = sub.add_parser("models", help=_("modelos locais: list | install (pré-instalados, com VAE, codificadores de texto e mmproj) | support (confere e baixa o que falta dos modelos instalados)"))
    mod.add_argument("action", choices=("list", "install", "support"), nargs="?", default="list")
    mod.add_argument("--which", default="", help=_("all (padrão), none, text, image ou ids (também OPENFLOW_MODELS)"))
    mod.add_argument("--ask", action="store_true", help=_("pergunta no terminal (sim/não) antes de baixar o que falta; sem efeito se --which ou OPENFLOW_MODELS já disseram o que fazer"))
    mod.add_argument("--home", help=_("pasta de dados (padrão ~/.openflow)"))
    libs = sub.add_parser("libs", help=_("instala/atualiza as bibliotecas opcionais do OpenFlow (docs, media, local)"))
    libs.add_argument("--extras", default="", help=_("all (padrão), none ou lista separada por vírgula (docs,media,local)"))
    libs.add_argument("--sd-cli", action="store_true", help=_("baixa o executável pronto da stable-diffusion.cpp (sd-cli), sem compilar, para modelos de imagem que a biblioteca Python não reconhece"))
    libs.add_argument("--sd-latest", action="store_true", help=_("compila a stable-diffusion-cpp-python mais nova do GitHub (para modelos de imagem novos que a do PyPI não reconhece)"))
    nat = sub.add_parser("native", help=_("Rust e núcleo rápido do OpenFlow: status | build | install | update | setup"))
    nat.add_argument("action", choices=("status", "build", "install", "update", "setup"), nargs="?", default="status")
    nat.add_argument("--rust", choices=("ask", "yes", "no"), default="", help=_("com setup: yes = faz sozinho (padrão), ask = pergunta, no = pula (também OPENFLOW_RUST)"))
    fol = sub.add_parser("folder", help=_("abre a pasta dos dados locais do OpenFlow no seu computador"))
    fol.add_argument("--print", action="store_true", help=_("só mostra o caminho, sem abrir"))
    fol.add_argument("--app", action="store_true", help=_("abre a pasta do programa instalado em vez da dos dados"))
    fol.add_argument("--home", help=_("pasta de dados (padrão ~/.openflow)"))
    sub.add_parser("doctor", help=_("mostra diagnóstico do ambiente"))
    sub.add_parser("version", help=_("mostra a versão"))
    args = parser.parse_args(argv)
    if args.cmd in ("setup", "install"):
        return _setup(args)
    if args.cmd == "update":
        return _update(args)
    if args.cmd == "models":
        return _models(args)
    if args.cmd == "libs":
        return _libs(args)
    if args.cmd == "native":
        return _native(args)
    if args.cmd == "folder":
        return _folder(args)
    if args.cmd == "doctor":
        return _doctor(args)
    if args.cmd == "version":
        print(__version__)
        return 0
    done = _auto_update(args, list(argv) if argv is not None else sys.argv[1:])
    if done is not None:
        return done
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
