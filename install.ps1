# OpenFlow — instalador/atualizador para Windows (PowerShell 5.1+).
#
#   irm https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.ps1 | iex
#
# O MESMO comando instala e atualiza. Seus dados (%USERPROFILE%\.openflow) nunca são tocados.
# Variáveis opcionais: $env:OPENFLOW_EXTRAS = "all" (padrão: instala/atualiza TODAS as bibliotecas do OpenFlow) | "none" (só o OpenFlow)
#                                         | lista: "docs,media,local". Uma biblioteca que falhe não aborta a instalação.
#                      $env:OPENFLOW_MODELS = (vazio: PERGUNTA no terminal, sim/não, antes de baixar os modelos locais pré-instalados: Qwen3.8 2B Distill Q8_0 (texto)
#                                         e Z-Image Q4_K_M (imagem)) | "all" | "text" | "image" (baixam sem perguntar) | "none" (pula)
#                      $env:OPENFLOW_PYTHON = "auto" (padrão: instala o Python se faltar e o atualiza pelo winget, com pip/setuptools/wheel)
#                                         | "keep" (nunca mexe no Python do sistema)
#                      $env:OPENFLOW_STEP = "python" → só instala/atualiza o Python e as ferramentas dele.
#                      $env:OPENFLOW_SOURCE = <url|pasta>   (padrão: GitHub, branch main)
#                      $env:OPENFLOW_FORCE = "1" → reinstala o OpenFlow mesmo que a versão instalada já seja a mais recente.
#                      $env:OPENFLOW_RUST = "yes" (padrão: baixa o núcleo Rust pronto da Release e, só se isso falhar, instala o Rust e compila, sozinho, na pasta do usuário) | "ask" (pergunta) | "no" (pula)
#                      $env:OPENFLOW_LANG = "pt" | "en" → idioma dos textos (padrão: o idioma do computador).
# O que já está instalado NÃO é instalado de novo: o Python só é atualizado se o winget tiver versão nova, o ambiente (venv) é reaproveitado,
# o OpenFlow só é baixado se houver versão mais nova, e as bibliotecas/modelos já presentes só são atualizados se precisar.

# 'Continue' de propósito: no Windows PowerShell 5.1, com 'Stop' qualquer texto que um programa externo (python, pip, winget) escreva no stderr
# — até com 2>$null — vira uma exceção (NativeCommandError). Os erros que importam são checados por $LASTEXITCODE e por -ErrorAction Stop.
$ErrorActionPreference = 'Continue'
# Windows PowerShell 5.1 em Windows 10 antigo / Server 2016 só liga o TLS 1.2 se pedirem: sem isto o download do GitHub falha com «Could not create SSL/TLS secure channel» (v0.60).
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
$Source = if ($env:OPENFLOW_SOURCE) { $env:OPENFLOW_SOURCE } else { 'https://github.com/KMC1525/OpenFlow/archive/refs/heads/main.zip' }
$Extras = $env:OPENFLOW_EXTRAS
$Root   = Join-Path $env:LOCALAPPDATA 'OpenFlow'
$AppDir = Join-Path $Root 'app'
$BinDir = Join-Path $Root 'bin'

# Idioma dos textos = idioma do computador (pt ou en). $env:OPENFLOW_LANG = "pt" | "en" força. O `flow` chamado daqui lê a mesma variável.
$AstaLang = 'en'
try {
  $forced = "$($env:OPENFLOW_LANG)".ToLower()
  if ($forced) { $AstaLang = if ($forced -like 'pt*') { 'pt' } else { 'en' } }
  else { $AstaLang = if ((Get-UICulture).Name -like 'pt*') { 'pt' } else { 'en' } }
} catch { }
$env:OPENFLOW_LANG = $AstaLang
function L($pt, $en) { if ($AstaLang -eq 'pt') { return $pt } else { return $en } }

function Say($m)  { Write-Host $m -ForegroundColor White }
function Note($m) { Write-Host "  $m" }
function Die($m)  { Write-Host "✗ $m" -ForegroundColor Red; throw $m }

Say (L 'OpenFlow — instalação/atualização' 'OpenFlow — install/update')

# 1) Python 3.9+ — instala se faltar e atualiza (o winget também atualiza o pip que vem com ele). $env:OPENFLOW_PYTHON = "keep": nunca mexe no Python do sistema.
$PyMode = if ($env:OPENFLOW_PYTHON) { $env:OPENFLOW_PYTHON } else { 'auto' }
function Find-Python {
  foreach ($cand in @(@('py', '-3'), @('python'), @('python3'))) {
    try {
      $exe = $cand[0]; $args0 = @($cand | Select-Object -Skip 1)
      & $exe @args0 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
      if ($LASTEXITCODE -eq 0) { return ,@(@($exe) + $args0) }   # a vírgula mantém o ARRAY: com um só elemento («python») o PowerShell o transformava na string «python», e $py[0] virava «p» (v0.90)
    } catch { }
  }
  return $null
}
function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User') }
function Winget-Python($mode) {
  # winget (vem com o Windows 10/11): "install" instala o Python 3.12; "upgrade" atualiza as versões do Python instaladas por ele
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
  $flags = @('--exact', '--silent', '--accept-package-agreements', '--accept-source-agreements')
  $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  try {
    if ($mode -eq 'install') { & winget install --id Python.Python.3.12 @flags | Out-Null; return ($LASTEXITCODE -eq 0) }
    foreach ($id in @('Python.Python.3.13', 'Python.Python.3.12', 'Python.Python.3.11', 'Python.Python.3.10', 'Python.Python.3.9')) {
      & winget list --id $id --exact 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) { & winget upgrade --id $id @flags | Out-Null }
    }
    return $true
  } finally { $ErrorActionPreference = $prev }
}
$py = Find-Python
if ($py) {
  if ($PyMode -ne 'keep') {
    $pyBefore = "$(& $py[0] @($py | Select-Object -Skip 1) --version)"
    Note (L "Python já instalado ($pyBefore) — verificando se há versão mais nova …" "Python already installed ($pyBefore) — checking for a newer version …")
    if (Winget-Python 'upgrade') {
      Refresh-Path; $py = Find-Python
      $pyAfter = "$(& $py[0] @($py | Select-Object -Skip 1) --version)"
      if ($pyAfter -ne $pyBefore) { Note (L "Python atualizado: $pyBefore → $pyAfter" "Python updated: $pyBefore → $pyAfter") } else { Note (L 'Python já está na versão mais recente disponível.' 'Python is already at the latest available version.') }
    } else { Note (L 'Não foi possível atualizar o Python automaticamente (sem o winget); seguindo com o atual.' 'Could not update Python automatically (no winget); continuing with the current one.') }
  }
} else {
  if ($PyMode -eq 'keep') { Die (L 'Python 3.9 ou superior não encontrado. Instale com:  winget install Python.Python.3.12   (ou https://www.python.org/downloads/) e rode este comando de novo.' 'Python 3.9 or newer not found. Install with:  winget install Python.Python.3.12   (or https://www.python.org/downloads/) and run this command again.') }
  Note (L 'Python 3.9+ não encontrado — instalando com o winget …' 'Python 3.9+ not found — installing with winget …')
  [void](Winget-Python 'install'); Refresh-Path; $py = Find-Python
  if (-not $py) { Die (L 'Não consegui instalar o Python 3.9+ automaticamente. Instale com:  winget install Python.Python.3.12   (ou https://www.python.org/downloads/) e rode este comando de novo.' 'Could not install Python 3.9+ automatically. Install with:  winget install Python.Python.3.12   (or https://www.python.org/downloads/) and run this command again.') }
}
Note ("Python: " + (& $py[0] @($py | Select-Object -Skip 1) --version))

# 2) ambiente isolado. Se o Python foi atualizado para uma versão mais nova, o ambiente é recriado.
New-Item -ItemType Directory -Force -ErrorAction Stop -Path $AppDir, $BinDir | Out-Null
$venv = Join-Path $AppDir 'venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
$pyV = (& $py[0] @($py | Select-Object -Skip 1) -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if (Test-Path $venv) {
  $vv = $null
  try { $vv = (& $venvPy -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null) } catch { }
  $vv = if ($vv) { "$vv".Trim() } else { '' }
  if ((-not $vv) -or ([version]$vv -lt [version]$pyV)) {
    Note (L "Recriando o ambiente para o Python $pyV (antes: $(if ($vv) { $vv } else { 'quebrado' })) — as bibliotecas serão reinstaladas …" "Recreating the environment for Python $pyV (before: $(if ($vv) { $vv } else { 'broken' })) — the libraries will be reinstalled …")
    try { Remove-Item -Recurse -Force -ErrorAction Stop $venv }
    catch { Die (L "Não consegui apagar o ambiente antigo ($venv): algum programa o está usando. Feche o OpenFlow (e os terminais com o flow aberto) e rode este comando de novo." "Could not delete the old environment ($venv): a program is using it. Close OpenFlow (and any terminal running flow) and run this command again.") }
  }
}
if (Test-Path $venvPy) { Note (L "Ambiente já existe ($venv) — reaproveitando." "Environment already exists ($venv) — reusing it.") }
else {
  Note (L "Criando ambiente em $venv …" "Creating environment in $venv …")
  & $py[0] @($py | Select-Object -Skip 1) -m venv $venv
  if ($LASTEXITCODE -ne 0) { Die (L 'Não foi possível criar o ambiente virtual.' 'Could not create the virtual environment.') }
}
# ferramentas do Python (pip, setuptools, wheel) sempre na versão mais recente
$prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& $venvPy -m pip install --upgrade --quiet --disable-pip-version-check pip setuptools wheel 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Note (L '⚠ Não foi possível atualizar o pip/setuptools/wheel agora (sem internet?); seguindo.' '⚠ Could not update pip/setuptools/wheel right now (no internet?); continuing.') }
$ErrorActionPreference = $prevEap
if ($env:OPENFLOW_STEP -eq 'python') { Say (L "✓ Python $pyV e ferramentas (pip, setuptools, wheel) prontos." "✓ Python $pyV and tools (pip, setuptools, wheel) ready."); return }

# 3) instala / atualiza
$spec = 'openflow'
if ($Source -match '://') { $req = "$spec @ $Source" }
elseif (Test-Path $Source) { $req = "$spec @ " + ([System.Uri](Resolve-Path -ErrorAction Stop $Source).Path).AbsoluteUri }
else { $req = $Source }
$old = & $venvPy -I -c "import openflow; print(openflow.__version__)" 2>$null   # OpenFlow ainda não instalado: o Python escreve um erro no stderr, que é descartado
if ($LASTEXITCODE -ne 0) { $old = $null }
# Só baixa o OpenFlow se ele não está instalado ou se há uma versão mais nova. Com a origem padrão (ou OPENFLOW_VERSION_URL) a versão publicada é
# consultada; com outra origem (OPENFLOW_SOURCE) não há como saber, então instala. OPENFLOW_FORCE=1 sempre reinstala.
$skipAsta = $false
$force = $env:OPENFLOW_FORCE -and ($env:OPENFLOW_FORCE -ne '0')
if ($old -and (Test-Path (Join-Path $venv 'Scripts\flow.exe')) -and (-not $force) -and ((-not $env:OPENFLOW_SOURCE) -or $env:OPENFLOW_VERSION_URL)) {
  $verUrl = if ($env:OPENFLOW_VERSION_URL) { $env:OPENFLOW_VERSION_URL } else { 'https://raw.githubusercontent.com/KMC1525/OpenFlow/main/openflow/__init__.py' }
  $remote = $null
  try {
    $txt = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -Uri $verUrl -ErrorAction Stop).Content
    if ($txt -is [byte[]]) { $txt = [System.Text.Encoding]::UTF8.GetString($txt) }
    if ($txt -match "__version__\s*=\s*[`"']([0-9][0-9.]*)") { $remote = $Matches[1] }
  } catch { }
  try { if ($remote -and ([version]$remote -le [version]("$old".Trim()))) { $skipAsta = $true } } catch { }
}
if ($skipAsta) { Note (L "OpenFlow $old já instalado e na versão mais recente — nada a baixar." "OpenFlow $old already installed and up to date — nothing to download.") }
else {
  Note (L 'Baixando e instalando OpenFlow …' 'Downloading and installing OpenFlow …')
  & $venvPy -m pip install --upgrade --disable-pip-version-check --quiet --no-cache-dir $req
  if ($LASTEXITCODE -ne 0) { Die (L 'Falha ao instalar. Verifique sua conexão e tente de novo.' 'Installation failed. Check your connection and try again.') }
}
$new = & $venvPy -I -c "import openflow; print(openflow.__version__)"

# 4) comando `flow`
# O atalho aponta para o flow.exe pelo caminho RELATIVO ao próprio arquivo (bin\..\app\venv): gravado em ASCII, um caminho absoluto com acento (C:\Users\João\…) virava «Jo?o» e o comando `flow` não abria (v0.90).
$shim = Join-Path $BinDir 'flow.cmd'
Set-Content -ErrorAction Stop -Path $shim -Value "@echo off`r`n`"%~dp0..\app\venv\Scripts\flow.exe`" %*" -Encoding ASCII

# v0.91: o `flow` é o programa em Rust (flow.exe, um arquivo só); o Python do ambiente vira o worker opcional dele. Sem o binário (sem internet, OPENFLOW_FLOW_RUST=no), vale o atalho acima (Python) — nada deixa de funcionar.
# Um flow.exe em uso não pode ser apagado, mas pode ser renomeado: o antigo vira flow.exe.old<pid> (apagado na próxima vez).
function Install-RustFlow {
  if ($env:OPENFLOW_FLOW_RUST -eq 'no') { return $false }
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ('flow-' + [guid]::NewGuid().ToString('N') + '.exe')
  try {
    if ($env:OPENFLOW_FLOW_BIN -and (Test-Path $env:OPENFLOW_FLOW_BIN)) { Copy-Item -Force -ErrorAction Stop $env:OPENFLOW_FLOW_BIN $tmp }
    else {
      $base = if ($env:OPENFLOW_RELEASE_URL) { $env:OPENFLOW_RELEASE_URL } else { "https://github.com/KMC1525/OpenFlow/releases/download/v$new" }
      $sums = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 -Uri "$base/SHA256SUMS.txt" -ErrorAction Stop).Content
      if ($sums -is [byte[]]) { $sums = [System.Text.Encoding]::UTF8.GetString($sums) }
      $line = @($sums -split "`n" | Where-Object { $_ -match 'flow-windows-x86_64\.exe\s*$' })[0]
      $want = if ($line) { ("$line".Trim() -split '\s+')[0] } else { '' }
      Invoke-WebRequest -UseBasicParsing -TimeoutSec 600 -Uri "$base/flow-windows-x86_64.exe" -OutFile $tmp -ErrorAction Stop
      if ((-not $want) -or ((Get-FileHash -Algorithm SHA256 $tmp).Hash.ToLower() -ne $want.ToLower())) { return $false }
    }
    $v = & $tmp version 2>$null
    if ("$v".Trim() -ne "$new") { return $false }
    $dest = Join-Path $BinDir 'flow.exe'
    if (Test-Path $dest) {
      try { Remove-Item -Force -ErrorAction Stop $dest } catch { Rename-Item -Force -ErrorAction Stop $dest ('flow.exe.old' + $PID) }
    }
    Move-Item -Force -ErrorAction Stop $tmp $dest
    return $true
  } catch { return $false }
  finally { if (Test-Path $tmp) { Remove-Item -Force -ErrorAction SilentlyContinue $tmp } }
}
Get-ChildItem -ErrorAction SilentlyContinue (Join-Path $BinDir 'flow.exe.old*') | ForEach-Object { Remove-Item -Force -ErrorAction SilentlyContinue $_.FullName }
if (Install-RustFlow) { Note (L 'Comando flow: programa em Rust (o Python fica como worker opcional).' 'flow command: the Rust program (Python stays as the optional worker).') }
else {
  $oldExe = Join-Path $BinDir 'flow.exe'
  if (Test-Path $oldExe) { try { Remove-Item -Force -ErrorAction Stop $oldExe } catch { try { Rename-Item -Force -ErrorAction Stop $oldExe ('flow.exe.old' + $PID) } catch { } } }   # um flow.exe antigo não pode ficar na frente do Python desta versão
  Note (L 'Comando flow: versão em Python (o programa em Rust não está disponível agora; tente de novo depois).' 'flow command: the Python version (the Rust program is not available right now; try again later).')
}

# 4b) o comando `flow` no PATH — do usuário (para novos terminais) e deste terminal (para usar já). Feito ANTES das bibliotecas, que demoram.
$flow = Join-Path $venv 'Scripts\flow.exe'
function Same-Dir($a, $b) { return ($a.TrimEnd('\') -ieq $b.TrimEnd('\')) }
# O Path do usuário no registro costuma ter entradas «%USERPROFILE%\…» (tipo REG_EXPAND_SZ). Ler com GetEnvironmentVariable e regravar trocava tudo pelo valor já expandido (e o tipo por REG_SZ): perdia as variáveis (v0.90).
# Aqui o valor CRU é lido e só se acrescenta a pasta; devolve $null se ela já está lá.
function Merge-PathEntry($raw, $dir) {
  $parts = @(if ($raw) { "$raw" -split ';' | Where-Object { $_ } })
  foreach ($p in $parts) { if (Same-Dir ([Environment]::ExpandEnvironmentVariables($p)) $dir) { return $null } }
  return (($parts + $dir) -join ';')
}
function Add-UserPath($dir) {
  try {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    try {
      $raw = $key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
      $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
      try { $kind = $key.GetValueKind('Path') } catch { }
      $merged = Merge-PathEntry $raw $dir
      if ($null -eq $merged) { return $false }
      $key.SetValue('Path', $merged, $kind)
    } finally { $key.Close() }
    [Environment]::SetEnvironmentVariable('OPENFLOW_PATH_REFRESH', $null, 'User')   # só para o Windows avisar os programas abertos de que o ambiente mudou
    return $true
  } catch {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $merged = Merge-PathEntry $userPath $dir
    if ($null -eq $merged) { return $false }
    [Environment]::SetEnvironmentVariable('Path', $merged, 'User')
    return $true
  }
}
if (Add-UserPath $BinDir) { Note (L 'Adicionei o comando ao seu PATH.' 'I added the command to your PATH.') }
if (-not (($env:Path -split ';') | Where-Object { $_ -and (Same-Dir $_ $BinDir) })) { $env:Path = $env:Path.TrimEnd(';') + ';' + $BinDir }   # vale já neste terminal (com `irm | iex`)

# 5) bibliotecas do OpenFlow (todas, a menos que OPENFLOW_EXTRAS diga outra coisa); a lista vem da versão recém-instalada
$libsFailed = $false
if ($Extras -in @('none', 'core')) { Note (L "Bibliotecas opcionais: puladas (OPENFLOW_EXTRAS=$Extras)." "Optional libraries: skipped (OPENFLOW_EXTRAS=$Extras).") }
else {
  Say (L 'Bibliotecas do OpenFlow: instalo o que falta e atualizo o que tiver versão mais nova (a primeira vez pode demorar e baixar vários GB) …' 'OpenFlow libraries: installing what is missing and updating what has a newer version (the first time can take long and download several GB) …')
  $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'   # avisos do pip no stderr não podem abortar o instalador
  & $flow libs
  if ($LASTEXITCODE -ne 0) { $libsFailed = $true }
  $ErrorActionPreference = $prevEap
}

# 6) modelos locais pré-instalados (texto e imagem). Sem $env:OPENFLOW_MODELS, o OpenFlow PERGUNTA no terminal (sim/não) antes de baixar; o que já está na pasta é pulado
$modelsFailed = $false
if ($env:OPENFLOW_MODELS -in @('none', 'no', '0')) { Note (L "Modelos pré-instalados: pulados (OPENFLOW_MODELS=$($env:OPENFLOW_MODELS))." "Pre-installed models: skipped (OPENFLOW_MODELS=$($env:OPENFLOW_MODELS)).") }
elseif (-not $env:OPENFLOW_MODELS) {
  & $flow models install --ask
  if ($LASTEXITCODE -ne 0) { $modelsFailed = $true }
}
else {
  Say (L 'Modelos locais pré-instalados: baixo só o que ainda não está na pasta (vários GB na primeira vez) …' 'Pre-installed local models: downloading only what is not in the folder yet (several GB the first time) …')
  & $flow models install
  if ($LASTEXITCODE -ne 0) { $modelsFailed = $true }
}
# 7) Rust (opcional, deixa o OpenFlow mais rápido e leve): instala o Rust se faltar, atualiza se já existir e recompila o núcleo do OpenFlow.
#    $env:OPENFLOW_RUST = "yes" (padrão: automático, como as bibliotecas e os modelos) | "ask" (pergunta no terminal) | "no" (pula).
if (-not $env:OPENFLOW_RUST) { $env:OPENFLOW_RUST = 'yes' }
$prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
& $flow native setup
if ($LASTEXITCODE -ne 0) { Note (L 'Rust: não foi possível concluir agora (opcional; o OpenFlow usa Python). Tente depois:  flow native setup' 'Rust: could not finish right now (optional; OpenFlow uses Python). Try later:  flow native setup') }
$ErrorActionPreference = $prevEap
if ($modelsFailed) { Note (L '⚠ Alguns modelos pré-instalados não foram baixados (veja acima). O OpenFlow já funciona; para tentar de novo: flow models install' '⚠ Some pre-installed models were not downloaded (see above). OpenFlow already works; to try again: flow models install') }

if (-not $old) { Say (L "✓ OpenFlow $new instalado." "✓ OpenFlow $new installed.") }
elseif ($old -eq $new) { Say (L "✓ OpenFlow $new já estava atualizado." "✓ OpenFlow $new was already up to date.") }
else { Say (L "✓ OpenFlow atualizado: $old → $new." "✓ OpenFlow updated: $old → $new.") }
if ($libsFailed) { Note (L '⚠ Algumas bibliotecas opcionais não foram instaladas (veja acima). O OpenFlow já funciona; para tentar de novo: flow libs' '⚠ Some optional libraries were not installed (see above). OpenFlow already works; to try again: flow libs') }
Write-Host ''
if (Get-Command flow -ErrorAction SilentlyContinue) { Note (L 'Para abrir o OpenFlow:   flow' 'To open OpenFlow:   flow') }
else {
  Note (L "Para abrir o OpenFlow:   & '$flow'" "To open OpenFlow:   & '$flow'")
  Note (L "O comando 'flow' só será reconhecido em terminais NOVOS (feche e abra o PowerShell) ou, neste, depois de rodar o instalador com:  irm <endereço> | iex" "The 'flow' command will only be recognized in NEW terminals (close and reopen PowerShell) or, in this one, after running the installer with:  irm <address> | iex")
}
Note (L 'Para atualizar:       rode este mesmo comando de novo (ou: flow update) — atualiza o OpenFlow e as bibliotecas dele' 'To update:            run this same command again (or: flow update) — it updates OpenFlow, its libraries and (optionally) Rust')
