<div align="center">

# OpenFlow

**Criação com IA em fluxos de nós — imagens, vídeos, sons, vozes e 3D — local, aberta e simples.**

Ligue alguns nós, veja cada resultado no próprio nó e edite o vídeo final sem sair do app. Tudo roda no seu computador, com modelos locais do Hugging Face. Sem contas, sem chaves de API, sem telemetria.

[Instalar](#instalar) · [Usar](#usar) · [Nós](#nós) · [Modelos](#modelos) · [Configurações](#configurações) · [Seus dados](#seus-dados) · [Desenvolvimento](#desenvolvimento) · [Changelog](CHANGELOG.md) · [English](README.md)

`MIT` · `Windows` · `macOS` · `Linux` · `Python 3.9+` · `Núcleo Rust` · `v0.63.0`

</div>

---

O OpenFlow é o modo *Canvas* do [ASTA](https://github.com/KMC1525/ASTA) transformado num app próprio: Python (só biblioteca padrão) + um núcleo pequeno em Rust, interface em HTML/CSS/JS puro e um comando só, `flow`.

## Instalar

Um comando instala **e** atualiza (seus dados em `~/.openflow` nunca são tocados):

```bash
curl -fsSL https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.sh | sh        # Linux / macOS
```

```powershell
irm https://raw.githubusercontent.com/KMC1525/OpenFlow/main/install.ps1 | iex             # Windows
```

Abra um terminal novo e rode `flow`. O instalador cria um ambiente isolado, instala o Python 3.9+ se faltar, as bibliotecas opcionais, os modelos pré-instalados (ele **pergunta** antes de baixar vários GB) e o núcleo Rust (biblioteca pronta, conferida por SHA-256). Com pip: `pip install "openflow @ https://github.com/KMC1525/OpenFlow/archive/refs/heads/main.zip"`.

Variáveis úteis: `OPENFLOW_EXTRAS=all|none|docs,media,local` · `OPENFLOW_MODELS=ask|all|text|image|none` · `OPENFLOW_RUST=yes|ask|no` · `OPENFLOW_PYTHON=auto|keep` · `OPENFLOW_SOURCE=<url|pasta>` · `OPENFLOW_FORCE=1` · `OPENFLOW_HOME` · `OPENFLOW_LANG=pt|en`.

## Usar

| Comando | O que faz |
|---|---|
| `flow` | Abre o OpenFlow no navegador (`--port`, `--host`, `--home`, `--no-browser`, `--no-update`). |
| `flow update` | Atualiza o OpenFlow, as bibliotecas (inclusive a stable-diffusion.cpp) e o núcleo Rust. |
| `flow setup` | Conclui uma instalação: bibliotecas, modelos pré-instalados, núcleo Rust. Pode repetir. |
| `flow libs` · `flow models` · `flow native` | Bibliotecas opcionais · modelos pré-instalados e arquivos de apoio · o núcleo Rust. |
| `flow doctor` · `flow version` · `flow folder` | Diagnóstico · versão · abre a pasta de dados. |

A primeira tela lista seus **projetos**, com barra de busca (nomes, descrições e textos dos nós; `/` foca nela). `Ctrl/⌘+K` abre a paleta de comandos, `Alt+N` cria um projeto, `?` lista os atalhos. A **Biblioteca** guarda seus modelos e arquivos gerados em pastas virtuais (arrastar e soltar, busca, downloads, uso de armazenamento, discos externos).

## Nós

Cada nó tem uma saída, entradas tipadas e um resultado visível nele. Os resultados ficam em cache por um hash de parâmetros, entradas, estilos e modelo: só o que mudou roda de novo.

| Grupo | Nós |
|---|---|
| **Texto** | Texto · Texto IA · Transcrever · Modelo · Juntar · Editar · Escolher trecho · Refinar com IA · Extrair · Contar |
| **Imagem** | Imagem (gerar ou **editar**, várias referências) · Redimensionar · Filtros · Texto · Colagem · Quadro · Recortar · Marca d'água · **Ficha de personagem** · **Página de quadrinhos** |
| **Vídeo** | Vídeo (de texto ou imagem) · Cortar · Juntar · Velocidade · Visual · Imagens em vídeo · Proporção · Repetir · Áudio |
| **Som** | **Música · Letra · SFX · Dublagem · Transcrição · Legendas** · Som · Voz · Cortar · Misturar · Efeitos · Áudio do vídeo · Repetir · Tirar silêncios |
| **Input** | Mídia · Style Prompt · **Style Folder** · Cor · Silêncio · Link · Sorteio de texto · Data · Padrão |
| **3D** | **Modelo 3D** (texto ou imagem → GLB/OBJ; visualizador no nó) · **Textura 3D** (imagem ou padrão pronto, com projeção) · **Esqueleto 3D** (esqueleto e pele automáticos) · **Animação 3D** (girar, pular, ondular, andar, acenar…; toca no visualizador) |
| **Output** | **Editor** (trilhas, dividir/cortar, fades, legendas, MP4) · Vídeo final · GIF · Áudio · Imagem · Miniatura · Galeria |

O Style Prompt e o Style Folder (pastas e subpastas, renomeáveis) valem para todos os geradores. Menções com `@` trazem imagens, vídeos e sons do projeto para dentro dos prompts.

## Modelos

**Toda pesquisa e download de modelos acontece na barra de pesquisa de modelos no topo do editor do Canvas**, com um indicador de downloads ao lado (progresso, velocidade, tempo restante, cancelar). Clique nela para ver um catálogo de modelos conhecidos (ele só lista), pesquisar no Hugging Face por tipo ou colar um endereço `dono/nome`. Em imagem e vídeo escolha **GGUF** (a quantização: bits, tamanho, qualidade, cabe na sua RAM?) ou o formato **original** do diffusers; texto é só GGUF; som, voz, transcrição e 3D usam o formato original.

- **Arquivos de apoio vêm junto:** VAE, codificadores de texto e `mmproj` baixam com o modelo (desligue em *Configurações → Desempenho → Downloads de modelos*).
- **Provedores:** só locais — *Hugging Face local* (diffusers, transformers), *GGUF local* (llama.cpp no texto, stable-diffusion.cpp em imagem/vídeo) e um *Demo* offline. 3D: Shap-E, TripoSR, Hunyuan3D-2.
- Famílias conhecidas: Qwen-Image 2.1 (inclusive o Uncensored Omni da ChatR Labs), FLUX.1/2/3, Z-Image, Wan, MiniMax H3, LTX-2.x, MOSS-Image e outras.

## Configurações

**Texto (IA)** modelo e janela de contexto · **Imagem, vídeo, som e voz** modelo padrão de cada tipo · **Projetos** modelo inicial · **Aparência** tema, cor, tamanho, fonte, idioma · **Desempenho** modo, CPU/GPU (várias placas somando a VRAM, VRAM + RAM juntas, híbrido CPU+GPU), planejador por classe de RAM para máquinas de 16 GB (DDR4/DDR5), conexões por download, token do Hugging Face (modelos restritos).

## Seus dados

Tudo fica em `~/.openflow` (ou `OPENFLOW_HOME`, ou nas pastas que você escolher na Biblioteca), em formatos abertos: `settings.json` · `projects/<id>/project.json` + `assets/` · `models/` · `native/`. Sem telemetria; o servidor escuta em `127.0.0.1` e confere `Host`/`Origin`; entradas (arquivos, pacotes, links, saída dos modelos) são tratadas como não confiáveis; atualizar ou desinstalar nunca apaga seus projetos.

## Desenvolvimento

```bash
git clone https://github.com/KMC1525/OpenFlow && cd OpenFlow
python -m pip install -e .
python -m openflow --no-browser --no-update
python -m unittest discover -s tests -t .                  # suíte completa (os testes de navegador pedem Node + Playwright)
cargo test --release --manifest-path openflow/native/Cargo.toml
node tests/js/i18n_check.mjs                               # toda frase da interface tem tradução em inglês
```

O núcleo Rust (`openflow/native`) faz a síntese de áudio, a ordem de execução, o planejamento de modelos locais e de RAM, a detecção de CPU/GPU e a liberação de memória; **toda função tem um espelho em Python**, então o OpenFlow funciona sem ele, só mais devagar. Os textos da interface e do terminal são em português com tradução para o inglês (`openflow/web/js/en.js`, `openflow/term_en.py`); código compatível com Python 3.9.

## Limites honestos

Verificado em Linux (Python 3.13): a suíte Python, os testes no Chromium, os testes em Rust e o `install.sh`. **Não verificado:** o `install.ps1` num Windows de verdade, macOS, builds do núcleo Rust para macOS/Windows/ARM, downloads reais do Hugging Face (os testes os simulam), inferência com modelos e GPUs reais e a velocidade em máquinas reais de 16 GB. O changelog de cada versão lista o que ela não verificou.

## Licença

[MIT](LICENSE). Derivado do [ASTA](https://github.com/KMC1525/ASTA) (mesmo autor), inspirado no ElevenLabs Flow. Modelos, bibliotecas e ferramentas mantêm suas licenças (llama.cpp, stable-diffusion.cpp, diffusers, transformers, ffmpeg e os autores dos modelos).
