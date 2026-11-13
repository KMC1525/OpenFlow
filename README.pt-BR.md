<div align="center">

# OpenFlow

**Criação criativa com IA em fluxos de nós — imagens, vídeos, sons e vozes — num app simples, aberto e local.**

Inspirado no ElevenLabs Flow e muito mais leve que o ComfyUI: ligue alguns nós, veja cada resultado no próprio nó e edite o vídeo final sem sair do app. Roda no seu computador, com modelos de empresas (API) ou 100% locais.

[Instalar](#instalar) · [O comando `flow`](#o-comando-flow) · [Projetos](#projetos--a-tela-inicial) · [Nós](#os-nós) · [Style Folder](#style-folder--pastas-e-subpastas) · [Modelos](#modelos--os-arquivos-de-apoio-se-instalam-sozinhos) · [Provedores](#provedores-de-ia) · [Núcleo Rust](#núcleo-rust) · [Desenvolvimento](#desenvolvimento) · [Changelog](CHANGELOG.md) · [English](README.md)

`MIT` · `Windows` · `macOS` · `Linux` · `Python 3.9+` · `Núcleo Rust` · `sem dependências obrigatórias` · `v0.2.0`

</div>

---

## O que é

O OpenFlow é o lado de fluxos criativos do [ASTA](https://github.com/KMC1525/ASTA) (o modo *Canvas* dele), transformado num app próprio que faz **uma coisa só**: criar com IA por meio de um fluxo de nós ligados. Mantém a arquitetura Python + Rust do ASTA e deixa de fora tudo o que não é criar.

- 🗂️ **Abre nos seus projetos.** A primeira tela lista **todos os projetos** com uma **barra de pesquisa** que procura no nome, na descrição e nos textos dentro dos nós (sem diferenciar acentos nem maiúsculas).
- 🧩 **Um fluxo de nós simples.** Cada nó tem uma saída, entradas tipadas e um resultado que você vê no próprio nó. Texto, imagem, vídeo, som, voz, transcrição, 30 nós utilitários (rodam no ffmpeg e no Python — sem modelo) e um **Editor** de vídeo embutido, com exportação em MP4.
- 🎨 **Estilo para o projeto todo.** Um *Style Prompt* e um *Style Folder* valem para todos os geradores. O Style Folder agora tem **pastas e subpastas, que você pode renomear**.
- 📦 **Os modelos se instalam com tudo o que precisam.** VAEs, codificadores de texto e arquivos `mmproj` são baixados **automaticamente, junto do modelo**.
- 🦀 **Núcleo Rust** (só biblioteca padrão, carregado por `ctypes`): síntese de áudio, ordem de execução do fluxo, planejamento de modelos locais, liberação de memória… com um espelho em Python puro de cada função.
- ⌨️ **Um comando em todos os sistemas: `flow`.** Instale, atualize e rode pelo terminal no Linux, macOS e Windows.
- 🔒 **Local e privado.** Seus projetos são pastas comuns (`project.json` + `assets/`); sem telemetria; o servidor escuta em `127.0.0.1`; chaves de API nunca chegam ao navegador.

## Instalar

Um só comando instala **e** atualiza (seus dados em `~/.openflow` nunca são tocados):

**Linux e macOS**

```bash
curl -fsSL https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.sh | sh
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.ps1 | iex
```

Depois abra um **terminal novo** e rode:

```bash
flow
```

O instalador cria um ambiente isolado (venv), instala o Python 3.9+ se faltar (apt, dnf, yum, pacman, zypper, apk, Homebrew ou winget), instala o OpenFlow, as bibliotecas opcionais, oferece os modelos pré-instalados e prepara o núcleo Rust (baixa a biblioteca pronta da Release e confere o SHA-256; só compila na sua máquina se isso falhar). O que já está instalado **não** é instalado de novo.

| Variável | O que faz |
|---|---|
| `OPENFLOW_EXTRAS=all\|none\|docs,media,local` | Bibliotecas opcionais (padrão `all`; `none` instala só o OpenFlow). Uma que falhe nunca aborta a instalação. |
| `OPENFLOW_MODELS=ask\|all\|text\|image\|none` | Modelos pré-instalados. Sem a variável o instalador **pergunta** (sim/não) antes de baixar vários GB. |
| `OPENFLOW_RUST=yes\|ask\|no` | Núcleo Rust (padrão `yes`). |
| `OPENFLOW_PYTHON=auto\|keep` | `keep` nunca mexe no Python do sistema. |
| `OPENFLOW_SOURCE=<url\|pasta>` | Instala de outra origem (um fork, uma cópia local). |
| `OPENFLOW_FORCE=1` | Reinstala mesmo que a versão já seja a mais recente. |
| `OPENFLOW_HOME`, `OPENFLOW_APP_DIR`, `OPENFLOW_BIN_DIR` | Onde ficam os dados, o programa e o comando `flow`. |
| `OPENFLOW_LANG=pt\|en` | Idioma das mensagens do terminal (padrão: o idioma do computador). |

Se preferir o pip: `pip install "openflow @ https://github.com/KMC1525/OpenFlow/archive/refs/heads/main.zip"` dá o mesmo comando `flow` (sem os extras do instalador).

## O comando `flow`

| Comando | O que faz |
|---|---|
| `flow` · `flow run` | Abre o OpenFlow no navegador (`--port`, `--host`, `--home`, `--no-browser`, `--no-update`). Ao abrir, confere atualizações (uma vez por dia, só em instalações feitas pelo instalador oficial; `--no-update` pula). |
| `flow setup` (apelido `flow install`) | Conclui uma instalação: bibliotecas opcionais, modelos pré-instalados e núcleo Rust. Pode repetir à vontade. |
| `flow update` | Atualiza o Python, o OpenFlow, as bibliotecas e o núcleo Rust — só o que falta ou tem versão nova (`--core`, `--no-python`, `--extras`, `--force`, `--rust`). |
| `flow models list\|install\|support` | Modelos pré-instalados; `support` confere cada modelo instalado e baixa o VAE, o codificador de texto ou o `mmproj` que faltar. |
| `flow libs` | Instala/atualiza as bibliotecas opcionais (`--sd-cli`, `--sd-latest` para modelos de imagem novos). |
| `flow native status\|build\|setup\|install\|update` | O núcleo Rust e o próprio Rust. |
| `flow folder` | Abre a pasta de dados (`--print` mostra o caminho). |
| `flow doctor` · `flow version` | Diagnóstico e versão. |

## Projetos — a tela inicial

O OpenFlow abre em **Projetos**: cada projeto é um cartão (miniatura, nome, nós, arquivos, data).

- **Barra de pesquisa** (aperte `/` em qualquer lugar da tela): acha projetos pelo **nome, pela descrição e pelos textos dentro dos nós** (prompts, falas, títulos, nomes de pastas de estilo). Todas as palavras precisam aparecer; acentos e maiúsculas não importam; o cartão diz onde achou e destaca o trecho. Sem resultado? Um clique cria um projeto com o nome que você digitou.
- **Ordenar** por mais recentes, nome, mais antigos ou mais arquivos (a escolha fica guardada).
- Menu em cada cartão: abrir, renomear, duplicar, baixar (`.zip`) e apagar.
- `Ctrl/⌘ + K` abre a paleta de comandos (telas, projetos e ações); `Alt + N` cria um projeto; `?` mostra os atalhos.
- Acessível desde o início: links e botões de verdade, rótulos para leitores de tela, foco visível, uso só pelo teclado, tema claro/escuro/automático, tamanho da interface de 90 a 150 %, animações reduzidas.

## Os nós

Cada nó tem **uma saída**, **entradas tipadas** e um **resultado que aparece no próprio nó**. Os resultados ficam em cache por um hash de parâmetros, entradas, estilos e modelo: só o que mudou roda de novo.

| Grupo | Nós |
|---|---|
| **Texto** | Texto · Texto IA · Transcrever · Modelo de texto · Juntar textos · Editar texto · Escolher trecho · Refinar com IA |
| **Imagem** | Imagem (gerar ou **editar**, com várias referências) · Redimensionar · Filtros e cor · Texto na imagem · Colagem · Quadro do vídeo |
| **Vídeo** | Vídeo (de texto ou de uma imagem inicial) · Cortar · Juntar clipes · Velocidade · Visual do vídeo · Imagens em vídeo |
| **Som** | Som (efeitos ou música) · Voz (texto em fala) · Cortar · Misturar · Efeitos · Áudio do vídeo · Repetir |
| **Input** | Mídia · Style Prompt · **Style Folder** · Cor e degradê · Silêncio · Link (URL) · Sorteio de texto · Data e projeto |
| **Output** | **Editor** (editor de vídeo: trilhas, bandeja, prévia, dividir/cortar, fades, legendas, MP4) · Vídeo final · GIF · Áudio final · Imagem final · Galeria |

Extras: menções com `@` a imagens, vídeos e sons do projeto dentro dos prompts; seletor de modelo em cada nó de mídia (instalados primeiro, depois cada provedor de nuvem com chave); **Gerar fluxo com IA** (uma equipe de planejador + revisor monta nós e ligações a partir de uma frase, com modelos de partida quando não há IA); **barra de busca de modelos** do Hugging Face no editor; modelos de projeto para começar rápido.

## Style Folder — pastas e subpastas

O nó **Style Folder** guarda as imagens, vídeos e áudios que definem o visual do projeto. Desde a v0.1 ele se organiza como um gerenciador de arquivos:

- **Nova pasta** (na raiz do nó) e **Nova subpasta** (dentro de qualquer pasta), até **6 níveis** e 60 pastas por nó.
- **Renomear** uma pasta pelo botão de lápis ou com duplo clique no nome; `Enter` confirma e `Esc` cancela. Os nomes são únicos entre pastas irmãs (`Luz`, `Luz (2)`…).
- **Mover arquivos** entre pastas pelo botão *Mover para…* de cada miniatura (funciona só com o teclado) ou arrastando-os até uma pasta. Solte arquivos do computador direto numa pasta para enviá-los para lá.
- **Ligar/desligar uma pasta** (botão do olho): uma pasta desligada continua no projeto mas sai do estilo, junto com tudo o que há dentro dela.
- O nome das pastas faz parte do estilo: quando o OpenFlow descreve suas referências (com o seu modelo de visão, ou pelas cores dominantes) ele passa `Personagens/Rostos/ref1.png` e a estrutura de pastas, então *Personagens*, *Iluminação* ou *Cenários* têm significado para o modelo. Renomear uma pasta ou mover um arquivo atualiza a descrição e marca como desatualizados os nós que a usam.

Projetos antigos abrem iguais (um Style Folder sem pastas funciona como antes).

## Modelos — os arquivos de apoio se instalam sozinhos

Abra **Modelos** para instalar e gerenciar modelos locais (GGUF, pelo llama.cpp e pela stable-diffusion.cpp):

- **Recomendados:** um modelo de texto pequeno e um de imagem (Z-Image), com a quantização já escolhida. O de imagem vem com o VAE e o codificador de texto dele.
- **Busca no Hugging Face** por tipo (Texto, Imagem, Vídeo, Som, Voz, Outros); você vê **todas as quantizações** (bits, tamanho, qualidade, se cabe na sua RAM, a recomendada) e escolhe qual baixar.
- **Os arquivos de apoio vêm junto, automaticamente.** Ao baixar um modelo, o OpenFlow baixa também o que ele precisa para rodar:

  | Arquivo | Quando |
  |---|---|
  | **VAE** | Modelos de imagem/vídeo de família conhecida (FLUX.2/3, Qwen-Image, Z-Image, Wan 2.1/2.2…) dos repositórios certos, ou um VAE que o repositório do próprio modelo traz ao lado. |
  | **Codificadores de texto** (`clip_l`, `t5xxl`, `umt5`, Qwen3/Mistral/Qwen-VL como codificadores LLM…) | Mesma regra do VAE. |
  | **`mmproj`** (projetor de visão) | Modelos de texto/visão cujo repositório tem `mmproj-*.gguf`; o melhor é escolhido (F16, BF16, Q8_0, F32) e salvo como `<modelo>.mmproj.gguf`, para dois modelos nunca dividirem o projetor errado. |

  Antes de baixar, a tela mostra **o que vem junto** e o tamanho. Os downloads retomam, nunca repetem o que já está na pasta, e um arquivo de apoio que falhe nunca desfaz o modelo — a tela diz o que falta e **Instalar o que falta** (ou `flow models support`) resolve. Apagar um modelo apaga o `mmproj` dele. Dá para desligar isso (caixa na tela, ou `hf.auto_support` nas configurações).
- **Instalados** mostra cada modelo com ✓ VAE · ✓ Codificador de texto · ⚠ falta …

Com a biblioteca opcional `local`, um modelo que tem um `mmproj` ao lado é carregado com entrada de imagens (melhor esforço: depende de o `llama-cpp-python` instalado conhecer a família do modelo; senão ele segue funcionando só com texto).

## Provedores de IA

**Texto** (nó Texto IA, planejador de fluxos, descrição de estilo): Claude (Anthropic), ChatGPT (OpenAI), Grok (xAI), Gemini, OpenRouter, Hugging Face Inference, LM Studio (detectado automaticamente), Ollama / servidor llama.cpp / vLLM / qualquer endpoint compatível com OpenAI, GGUF do Hugging Face embutido e **Demo** (offline).

**Mídia** (definida por tipo em *Configurações → Imagem, vídeo, som e voz*, e trocável em cada nó): OpenAI (gpt-image, TTS, Whisper), servidores compatíveis com OpenAI (Kokoro, faster-whisper, LocalAI…), ElevenLabs, Google (Gemini/Veo), Stability AI, Replicate, Hugging Face Inference, Stable Diffusion WebUI (local), **Hugging Face local** (diffusers + transformers), **GGUF local** (stable-diffusion.cpp) e **Demo** (offline: imagens procedurais, som sintetizado, vídeo Ken Burns — precisa de `ffmpeg`).

## Núcleo Rust

O OpenFlow mantém a arquitetura do ASTA: a orquestração e o servidor HTTP ficam em Python (só biblioteca padrão), sobre uma pequena **biblioteca em Rust** (`openflow/native`, só biblioteca padrão, carregada com `ctypes`). Ela faz o trabalho pesado: síntese de áudio do Demo, **ordem de execução** do fluxo, **planejamento de modelos locais** (lê o cabeçalho GGUF/safetensors e a RAM/VRAM livres para escolher contexto, camadas na GPU, threads e cache), um plano para vários agentes locais, análise de mídia (volume, silêncios, andamento) e liberação de memória. **Toda função em Rust tem um equivalente em Python** (`openflow/native/__init__.py`), então o OpenFlow funciona sem a biblioteca — só mais devagar. `flow native setup` baixa a biblioteca pronta (conferida por SHA-256) e só compila localmente se precisar; `flow doctor` mostra o estado dela.

## Seus dados

Tudo fica em `~/.openflow` (ou `OPENFLOW_HOME`), em formatos abertos:

```
settings.json                     configurações (chaves de API nunca são exportadas)
projects/<id>/project.json        nós, ligações, pastas de estilo
projects/<id>/assets/             mídias geradas e enviadas
models/ (image/ video/ …)         modelos GGUF e seus arquivos de apoio
native/                           a biblioteca Rust
```

Sem telemetria. O servidor escuta em `127.0.0.1` e confere `Host`/`Origin`. Entradas (arquivos, pacotes, URLs, saída da IA) são tratadas como não confiáveis; a IA só produz **dados** (JSON validado), nunca código. Atualizar ou desinstalar nunca apaga seus projetos.

## Estrutura do repositório

```
openflow/
  cli.py · server.py · storage.py · routes_projects.py · routes_preinstalled.py
  canvas/        motor, esquema dos nós, provedores de mídia, armazenamento, arquivos de apoio (VAE/codificadores/mmproj)
  providers/     provedores de IA de texto (nuvem, locais, Demo)
  native/        o núcleo Rust + o espelho em Python
  web/           a interface (HTML/CSS/JS puros, sem etapa de build)
install.sh · install.ps1     instaladores (Linux/macOS · Windows)
tests/                       testes em Python, Node/Playwright e Rust
```

## Desenvolvimento

```bash
git clone https://github.com/KMC1525/OpenFlow && cd OpenFlow
python -m pip install -e .
python -m openflow --no-browser --no-update      # ou: flow
python -m unittest discover -s tests -t .        # suíte completa
cargo test --release --manifest-path openflow/native/Cargo.toml
node tests/js/i18n_check.mjs                     # toda frase da interface tem tradução para o inglês
```

Os testes de navegador precisam de Node, Playwright e Chromium (`NODE_PATH` apontando para a sua instalação do `playwright`). Código compatível com Python 3.9 (sem `match`, sem `X | Y` em tempo de execução). Todo texto da interface e do terminal é em português primeiro, com tradução para o inglês (`openflow/web/js/en.js`, `openflow/term_en.py`); os testes conferem.

## Limites honestos (v0.2.0)

Verificado aqui (Linux, Python 3.13): a suíte completa de testes em Python (442 testes), os testes de navegador no Chromium, os testes em Rust e o `install.sh` de ponta a ponta contra uma cópia local. **Não verificado:** o `install.ps1` num Windows de verdade e o `install.sh` no macOS (os jobs de CI estão escritos mas não rodaram); a compilação do núcleo Rust para macOS/Windows/ARM; downloads reais de VAEs, codificadores de texto e `mmproj` do Hugging Face (os testes simulam os downloads — os nomes de arquivo dos repositórios curados e de exemplo foram conferidos nas listagens do Hugging Face); inferência com modelos GGUF e GPUs reais; entrada de imagens por `mmproj` com um modelo real; provedores de nuvem com chaves reais (os testes usam servidores falsos). Não há medições de desempenho.

## Licença e créditos

[MIT](LICENSE). O OpenFlow deriva do modo Canvas do [ASTA](https://github.com/KMC1525/ASTA) (mesmo autor). Inspirado no ElevenLabs Flow. Modelos, bibliotecas e serviços mantêm suas próprias licenças: llama.cpp, stable-diffusion.cpp, diffusers, transformers, ffmpeg e os autores dos modelos no Hugging Face.
