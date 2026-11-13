#!/bin/sh
# OpenFlow — instalador/atualizador para Linux e macOS (comando `flow`).
#
#   curl -fsSL https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.sh | sh
#
# O MESMO comando instala e atualiza. Seus dados (~/.openflow: projetos, modelos,
# configurações) nunca são tocados. Opções (variáveis de ambiente):
#   OPENFLOW_EXTRAS=all|none|docs,media,local   bibliotecas opcionais do OpenFlow. Padrão: all (instala/atualiza TODAS: PDFs mais
#                                       precisos, modelos locais de imagem/vídeo/som/voz do OpenFlow e modelos GGUF embutidos).
#                                       "none" instala só o OpenFlow (sem dependências). Uma biblioteca que falhe não aborta a instalação.
#   OPENFLOW_SOURCE=<url|pasta|requisito>   instala de outra origem (padrão: GitHub, branch main)
#   OPENFLOW_APP_DIR=<pasta>                onde fica o programa (padrão: ~/.openflow/app)
#   OPENFLOW_BIN_DIR=<pasta>                onde fica o comando `flow` (padrão: ~/.local/bin)
#   OPENFLOW_MODELS=all|none|text|image     modelos locais pré-instalados: Qwen3.8 2B Distill (texto, Q8_0, ~2 GB) e Z-Image (imagem, Q4_K_M, ~6 GB
#                                       com o VAE e o codificador de texto). Sem esta variável o instalador PERGUNTA no terminal (sim/não) antes de
#                                       baixar; "all"/"text"/"image" baixa sem perguntar e "none" pula.
#   OPENFLOW_PYTHON=auto|keep               auto (padrão): instala o Python se faltar e o atualiza (com pip, venv, setuptools e wheel)
#                                       pelo gerenciador de pacotes do sistema (apt, dnf, yum, pacman, zypper, apk, Homebrew).
#                                       keep: nunca mexe no Python do sistema.
#   OPENFLOW_FORCE=1                        reinstala o OpenFlow mesmo que a versão instalada já seja a mais recente.
#   OPENFLOW_RUST=yes|ask|no                Núcleo Rust (mais rápido e leve; parte do OpenFlow): yes (padrão) baixa a biblioteca pronta da Release e, só se isso falhar, instala o Rust e compila
#                                       na máquina (pasta do usuário, sem sudo); ask pergunta no terminal; no pula.
#   OPENFLOW_NATIVE_FILE=<arquivo>          núcleo Rust já compilado (os instaladores usam isto); é copiado em vez de baixado.
# O que já está instalado NÃO é instalado de novo: o Python só é atualizado se o gerenciador de pacotes tiver versão nova, o ambiente
# (venv) é reaproveitado, o OpenFlow só é baixado se houver versão mais nova, e as bibliotecas/modelos já presentes só são atualizados se precisar.
# Argumentos: sh -s -- --run            inicia o OpenFlow ao terminar.
#             sh -s -- --python-only    só instala/atualiza o Python e as ferramentas dele (pip, setuptools, wheel).
set -eu

SOURCE="${OPENFLOW_SOURCE:-https://github.com/KMC1525/OpenFlow/archive/refs/heads/main.zip}"
APP_DIR="${OPENFLOW_APP_DIR:-$HOME/.openflow/app}"
BIN_DIR="${OPENFLOW_BIN_DIR:-$HOME/.local/bin}"
EXTRAS="${OPENFLOW_EXTRAS:-}"
RUN=0
PYONLY=0
for arg in "$@"; do [ "$arg" = "--run" ] && RUN=1; [ "$arg" = "--python-only" ] && PYONLY=1; done

# Idioma dos textos = idioma do computador (pt ou en). OPENFLOW_LANG=pt|en força. Vale também para o `flow` chamado daqui (ele lê OPENFLOW_LANG).
detect_lang() {
  for v in "${OPENFLOW_LANG:-}" "${LC_ALL:-}" "${LC_MESSAGES:-}" "${LANGUAGE:-}" "${LANG:-}"; do
    case "$v" in ""|C|POSIX|C.*) continue ;; pt*|PT*) echo pt; return ;; *) echo en; return ;; esac
  done
  if [ "$(uname -s)" = "Darwin" ] && command -v defaults >/dev/null 2>&1; then
    case "$(defaults read -g AppleLanguages 2>/dev/null | tr -d '() ",\n' | cut -c1-2)" in pt) echo pt; return ;; esac
  fi
  echo en
}
OPENFLOW_L="$(detect_lang)"
export OPENFLOW_LANG="$OPENFLOW_L"
L() { if [ "$OPENFLOW_L" = "pt" ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

say "$(L "OpenFlow — instalação/atualização" "OpenFlow — install/update")"

# macOS: o Terminal nem sempre tem o Homebrew no PATH (Apple Silicon fica em /opt/homebrew; Intel em /usr/local). Sem isto «brew» e os Pythons dele "não existem" para o instalador.
if [ "$(uname -s)" = "Darwin" ]; then
  for brewbin in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$brewbin" ] && ! command -v brew >/dev/null 2>&1; then eval "$("$brewbin" shellenv)"; fi
  done
  PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin"; export PATH
fi

# 1) Python 3.9+ — instala se faltar e atualiza (com o pip, o venv e as ferramentas de empacotamento) usando o gerenciador
#    de pacotes do sistema. Pode pedir a sua senha (sudo). OPENFLOW_PYTHON=keep: nunca mexe no Python do sistema.
# macOS sem as «Command Line Tools»: /usr/bin/python3 é só um atalho que ABRE uma janela de instalação em vez de rodar o Python. Não o executamos.
mac_stub() {
  [ "$(uname -s)" = "Darwin" ] || return 1
  case "$(command -v "$1" 2>/dev/null)" in
    /usr/bin/python3|/usr/bin/python) ! xcode-select -p >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}
find_python() {
  PY=""
  for cand in python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3 python; do
    mac_stub "$cand" && continue
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      PY="$cand"; return 0
    fi
  done
  return 1
}
as_root() {
  if [ "$(id -u)" = "0" ]; then "$@"
  elif command -v sudo >/dev/null 2>&1; then sudo "$@"
  else return 1; fi
}
# pkg_python install|upgrade → 0 se um gerenciador de pacotes concluiu; 1 se não há gerenciador/permissão/falhou
pkg_python() {
  mode="$1"
  case "$(uname -s)" in
    Darwin)
      command -v brew >/dev/null 2>&1 || return 1
      if [ "$mode" = "install" ]; then brew install python
      elif brew list --formula 2>/dev/null | grep -Eq '^python(@3\.[0-9]+)?$'; then brew upgrade python || true; fi ;;
    *)
      if command -v apt-get >/dev/null 2>&1; then
        as_root apt-get update -qq && as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip
      elif command -v dnf >/dev/null 2>&1; then
        as_root dnf install -y python3 python3-pip && { [ "$mode" = "install" ] || as_root dnf upgrade -y python3 python3-pip; }
      elif command -v yum >/dev/null 2>&1; then
        as_root yum install -y python3 python3-pip && { [ "$mode" = "install" ] || as_root yum update -y python3 python3-pip; }
      elif command -v pacman >/dev/null 2>&1; then
        as_root pacman -S --noconfirm --needed python python-pip
      elif command -v zypper >/dev/null 2>&1; then
        as_root zypper --non-interactive install --no-recommends python3 python3-pip && { [ "$mode" = "install" ] || as_root zypper --non-interactive update python3 python3-pip; }
      elif command -v apk >/dev/null 2>&1; then
        as_root apk add --upgrade python3 py3-pip
      else return 1; fi ;;
  esac
}
python_hint() {
  case "$(uname -s)" in
    Darwin) echo "brew install python   (ou https://www.python.org/downloads/)" ;;
    *)      echo "sudo apt install python3 python3-venv python3-pip   (Debian/Ubuntu)  ·  sudo dnf install python3   (Fedora)  ·  sudo pacman -S python   (Arch)" ;;
  esac
}
PYMODE="${OPENFLOW_PYTHON:-auto}"
if find_python; then
  if [ "$PYMODE" != "keep" ]; then
    PYBEFORE="$($PY --version 2>&1)"
    note "$(L "Python já instalado ($PYBEFORE) — verificando se há versão mais nova …" "Python already installed ($PYBEFORE) — checking for a newer version …")"
    pkg_python upgrade >/dev/null || note "$(L "Não foi possível atualizar o Python automaticamente (sem gerenciador de pacotes ou permissão); seguindo com o atual." "Could not update Python automatically (no package manager or permission); continuing with the current one.")"
    find_python || true   # a atualização pode ter trazido uma versão mais nova
    if [ "$($PY --version 2>&1)" != "$PYBEFORE" ]; then note "$(L "Python atualizado: $PYBEFORE → $($PY --version 2>&1)" "Python updated: $PYBEFORE → $($PY --version 2>&1)")"; else note "$(L "Python já está na versão mais recente disponível." "Python is already at the latest available version.")"; fi
  fi
else
  [ "$PYMODE" = "keep" ] && die "$(L "Python 3.9 ou superior não encontrado. Instale com: $(python_hint)" "Python 3.9 or newer not found. Install with: $(python_hint)")"
  note "$(L "Python 3.9+ não encontrado — instalando …" "Python 3.9+ not found — installing …")"
  pkg_python install >/dev/null || true
  find_python || die "$(L "Não consegui instalar o Python 3.9+ automaticamente. Instale com: $(python_hint)" "Could not install Python 3.9+ automatically. Install with: $(python_hint)")"
fi
note "$(L "Python: $($PY --version 2>&1)" "Python: $($PY --version 2>&1)")"

# 2) ambiente isolado (não suja o Python do sistema). Se o Python foi atualizado para uma versão mais nova, o ambiente é recriado.
mkdir -p "$APP_DIR"
PYV="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
VENVPY="$APP_DIR/venv/bin/python"
if [ -e "$APP_DIR/venv" ]; then
  VV="$("$VENVPY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  if [ -z "$VV" ] || "$PY" -c 'import sys; a, b = (tuple(map(int, v.split("."))) for v in sys.argv[1:3]); sys.exit(0 if a < b else 1)' "$VV" "$PYV"; then
    note "$(L "Recriando o ambiente para o Python $PYV (antes: ${VV:-quebrado}) — as bibliotecas serão reinstaladas …" "Recreating the environment for Python $PYV (before: ${VV:-broken}) — the libraries will be reinstalled …")"
    rm -rf "$APP_DIR/venv"
  fi
fi
if [ -x "$VENVPY" ]; then
  note "$(L "Ambiente já existe ($APP_DIR/venv) — reaproveitando." "Environment already exists ($APP_DIR/venv) — reusing it.")"
else
  note "$(L "Criando ambiente em $APP_DIR/venv …" "Creating environment in $APP_DIR/venv …")"
  "$PY" -m venv "$APP_DIR/venv" >/dev/null 2>&1 || {
    rm -rf "$APP_DIR/venv"
    # Debian/Ubuntu: o módulo venv vem num pacote separado
    if [ "$PYMODE" != "keep" ] && pkg_python install >/dev/null 2>&1 && "$PY" -m venv "$APP_DIR/venv" >/dev/null 2>&1; then :; else
      rm -rf "$APP_DIR/venv"
      die "$(L "Não foi possível criar o ambiente virtual. No Debian/Ubuntu instale: sudo apt install python3-venv" "Could not create the virtual environment. On Debian/Ubuntu install: sudo apt install python3-venv")"
    fi
  }
fi
# ferramentas do Python (pip, setuptools, wheel) sempre na versão mais recente
"$VENVPY" -m pip install --upgrade --quiet --disable-pip-version-check pip setuptools wheel >/dev/null 2>&1 \
  || note "$(L "⚠ Não foi possível atualizar o pip/setuptools/wheel agora (sem internet?); seguindo." "⚠ Could not update pip/setuptools/wheel right now (no internet?); continuing.")"
if [ "${OPENFLOW_STEP:-}" = "python" ] || [ "$PYONLY" = "1" ]; then say "$(L "✓ Python $PYV e ferramentas (pip, setuptools, wheel) prontos." "✓ Python $PYV and tools (pip, setuptools, wheel) ready.")"; exit 0; fi

# 3) instala / atualiza
SPEC="openflow"
case "$SOURCE" in
  *://*|git+*) REQ="$SPEC @ $SOURCE" ;;
  /*|./*|../*|~*) REQ="$SPEC @ file://$(cd "$SOURCE" && pwd)" ;;
  *) REQ="$SOURCE" ;;
esac
OLD="$("$APP_DIR/venv/bin/python" -I -c 'import openflow; print(openflow.__version__)' 2>/dev/null || true)"
# Só baixa o OpenFlow se ele não está instalado ou se há uma versão mais nova. Com a origem padrão (ou OPENFLOW_VERSION_URL) a versão publicada é
# consultada; com outra origem (OPENFLOW_SOURCE) não há como saber, então instala. OPENFLOW_FORCE=1 sempre reinstala.
SKIP_FLOW=0
if [ -n "$OLD" ] && [ -x "$APP_DIR/venv/bin/flow" ] && { [ "${OPENFLOW_FORCE:-0}" = "0" ] || [ -z "${OPENFLOW_FORCE:-}" ]; } && { [ -z "${OPENFLOW_SOURCE:-}" ] || [ -n "${OPENFLOW_VERSION_URL:-}" ]; }; then
  REMOTE="$(OPENFLOW_VERSION_URL="${OPENFLOW_VERSION_URL:-https://raw.githubusercontent.com/KMC1525/OpenFlow/main/openflow/__init__.py}" "$APP_DIR/venv/bin/python" -I -c '
import os, re, urllib.request
try:
    with urllib.request.urlopen(os.environ["OPENFLOW_VERSION_URL"], timeout=20) as r:
        m = re.search(r"__version__\s*=\s*[\"\x27]([^\"\x27]+)", r.read(8192).decode("utf-8", "replace"))
    print(m.group(1) if m else "")
except Exception:
    print("")
' 2>/dev/null || true)"
  if [ -n "$REMOTE" ] && "$APP_DIR/venv/bin/python" -I -c 'import re, sys
t = lambda v: tuple(int(x) for x in re.findall(r"\d+", v)[:4])
sys.exit(0 if t(sys.argv[1]) <= t(sys.argv[2]) else 1)' "$REMOTE" "$OLD"; then
    SKIP_FLOW=1
  fi
fi
if [ "$SKIP_FLOW" = "1" ]; then
  note "$(L "OpenFlow $OLD já instalado e na versão mais recente — nada a baixar." "OpenFlow $OLD already installed and up to date — nothing to download.")"
else
  note "$(L "Baixando e instalando OpenFlow …" "Downloading and installing OpenFlow …")"
  "$APP_DIR/venv/bin/python" -m pip install --upgrade --disable-pip-version-check --quiet --no-cache-dir "$REQ" \
    || die "$(L "Falha ao instalar. Verifique sua conexão e tente de novo." "Installation failed. Check your connection and try again.")"
fi
NEW="$("$APP_DIR/venv/bin/python" -I -c 'import openflow; print(openflow.__version__)')"

# 4) comando `flow`
mkdir -p "$BIN_DIR"
ln -sf "$APP_DIR/venv/bin/flow" "$BIN_DIR/flow"

# 5) bibliotecas do OpenFlow (todas, a menos que OPENFLOW_EXTRAS diga outra coisa). A lista vem da versão recém-instalada.
LIBS_FAILED=0
case "$EXTRAS" in
  none|core) note "$(L "Bibliotecas opcionais: puladas (OPENFLOW_EXTRAS=$EXTRAS)." "Optional libraries: skipped (OPENFLOW_EXTRAS=$EXTRAS).")" ;;
  *) say "$(L "Bibliotecas do OpenFlow: instalo o que falta e atualizo o que tiver versão mais nova (a primeira vez pode demorar e baixar vários GB) …" "OpenFlow libraries: installing what is missing and updating what has a newer version (the first time can take long and download several GB) …")"
     if [ -n "$EXTRAS" ]; then OPENFLOW_EXTRAS="$EXTRAS" "$APP_DIR/venv/bin/flow" libs || LIBS_FAILED=1
     else "$APP_DIR/venv/bin/flow" libs || LIBS_FAILED=1; fi ;;
esac

if [ -z "$OLD" ]; then say "$(L "✓ OpenFlow $NEW instalado." "✓ OpenFlow $NEW installed.")"; elif [ "$OLD" = "$NEW" ]; then say "$(L "✓ OpenFlow $NEW já estava atualizado." "✓ OpenFlow $NEW was already up to date.")"; else say "$(L "✓ OpenFlow atualizado: $OLD → $NEW." "✓ OpenFlow updated: $OLD → $NEW.")"; fi
# 6) modelos locais pré-instalados (texto e imagem). Sem OPENFLOW_MODELS, o OpenFlow PERGUNTA no terminal (sim/não) antes de baixar; o que já está na pasta é pulado
MODELS_FAILED=0
case "${OPENFLOW_MODELS:-ask}" in
  none|no|0) note "$(L "Modelos pré-instalados: pulados (OPENFLOW_MODELS=${OPENFLOW_MODELS})." "Pre-installed models: skipped (OPENFLOW_MODELS=${OPENFLOW_MODELS}).")" ;;
  ask) "$APP_DIR/venv/bin/flow" models install --ask || MODELS_FAILED=1 ;;
  *) say "$(L "Modelos locais pré-instalados: baixo só o que ainda não está na pasta (vários GB na primeira vez) …" "Pre-installed local models: downloading only what is not in the folder yet (several GB the first time) …")"
     "$APP_DIR/venv/bin/flow" models install || MODELS_FAILED=1 ;;
esac

# 7) núcleo Rust — parte obrigatória do OpenFlow. Os instaladores (macOS .pkg etc.) já trazem a biblioteca pronta (OPENFLOW_NATIVE_FILE): ela é copiada para cá antes de tudo.
if [ -n "${OPENFLOW_NATIVE_FILE:-}" ] && [ -f "$OPENFLOW_NATIVE_FILE" ]; then
  NDIR="${OPENFLOW_HOME:-$HOME/.openflow}/native"
  mkdir -p "$NDIR"
  case "$(uname -s)" in Darwin) NLIB="libopenflow_core.dylib" ;; *) NLIB="libopenflow_core.so" ;; esac
  if cp "$OPENFLOW_NATIVE_FILE" "$NDIR/$NLIB"; then printf '%s' "$NEW" > "$NDIR/VERSION"; note "$(L "Núcleo Rust copiado do instalador." "Rust core copied from the installer.")"; fi
fi
#    Sem ela, `flow native setup` baixa a biblioteca PRÉ-COMPILADA da Release (conferida por SHA-256, sem compilador) e só compila na máquina se isso falhar:
#    Rust instalado se faltar, atualizado se já existir.
#    OPENFLOW_RUST=yes (padrão: automático, como as bibliotecas e os modelos) | ask (pergunta no terminal) | no (pula).
OPENFLOW_RUST="${OPENFLOW_RUST:-yes}" "$APP_DIR/venv/bin/flow" native setup || note "$(L "Rust: não foi possível concluir agora (opcional; o OpenFlow usa Python). Tente depois:  flow native setup" "Rust: could not finish right now (optional; OpenFlow uses Python). Try later:  flow native setup")"

if [ "$MODELS_FAILED" = "1" ]; then
  note "$(L "⚠ Alguns modelos pré-instalados não foram baixados (veja acima). O OpenFlow já funciona; para tentar de novo: flow models install" "⚠ Some pre-installed models were not downloaded (see above). OpenFlow already works; to try again: flow models install")"
fi
if [ "$LIBS_FAILED" = "1" ]; then
  note "$(L "⚠ Algumas bibliotecas opcionais não foram instaladas (veja acima). O OpenFlow já funciona; para tentar de novo: flow libs" "⚠ Some optional libraries were not installed (see above). OpenFlow already works; to try again: flow libs")"
fi
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) case "${SHELL:-}" in
       */zsh)  RCFILE="~/.zshrc" ;;
       */bash) if [ "$(uname -s)" = "Darwin" ]; then RCFILE="~/.bash_profile"; else RCFILE="~/.bashrc"; fi ;;
       */fish) RCFILE="" ;;
       *)      RCFILE="~/.profile" ;;
     esac
     note "$(L "Adicione ao seu PATH para usar o comando 'flow':" "Add this to your PATH to use the 'flow' command:")"
     if [ -z "$RCFILE" ]; then note "$(L "  fish_add_path $BIN_DIR   (e abra um novo terminal)" "  fish_add_path $BIN_DIR   (and open a new terminal)")"
     else note "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> $RCFILE   $(L "(e abra um novo terminal)" "(and open a new terminal)")"; fi
     note "$(L "Até lá, abra o OpenFlow com o caminho completo:  $BIN_DIR/flow" "Until then, open OpenFlow with the full path:  $BIN_DIR/flow")" ;;
esac
echo
note "$(L "Para abrir o OpenFlow:   flow" "To open OpenFlow:   flow")"
note "$(L "Para atualizar:       rode este mesmo comando de novo (ou: flow update) — atualiza o OpenFlow e as bibliotecas dele" "To update:            run this same command again (or: flow update) — it updates OpenFlow, its libraries and (optionally) Rust")"
echo

if [ "$RUN" = "1" ]; then exec "$APP_DIR/venv/bin/flow"; fi
