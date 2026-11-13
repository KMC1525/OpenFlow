# Changelog

Formato: `## [versão] — data`. Cada versão traz o que mudou para quem usa e, com honestidade, o que **não** foi verificado. [English](CHANGELOG.en.md)

## [0.1.0] — 2026-11-13

Primeira versão do **OpenFlow**: o modo Canvas do [ASTA](https://github.com/KMC1525/ASTA) virou um app próprio, focado só em criação criativa com IA por fluxos de nós (estilo ElevenLabs Flow), com interface simples e acessível.

### Novo
- **Tela inicial de projetos com barra de pesquisa.** O OpenFlow abre na lista de todos os projetos (cartões com miniatura, nós, arquivos e data). A pesquisa (`/` foca o campo) procura no **nome, na descrição e nos textos dos nós** (prompts, falas, títulos e nomes de pastas de estilo), sem diferenciar acentos nem maiúsculas; todas as palavras precisam aparecer; o cartão mostra onde achou e destaca o trecho. Sem resultado, um botão cria um projeto com o nome digitado. Ordenação por mais recentes, nome, mais antigos ou mais arquivos (lembrada). Menu por cartão: abrir, renomear, duplicar, baixar `.zip`, apagar. API: `GET /api/projects?q=…&sort=…`.
- **Style Folder com pastas e subpastas.** No nó Style Folder: **Nova pasta**, **Nova subpasta** (até 6 níveis e 60 pastas por nó), **renomear** (botão de lápis, duplo clique, `Enter`/`Esc`), nomes únicos entre pastas irmãs, **mover arquivos** entre pastas (botão *Mover para…*, arrastar e soltar), enviar arquivos direto para uma pasta, **ligar/desligar** uma pasta e apagar. O nome das pastas entra na descrição do estilo; renomear ou mover marca os nós como desatualizados. Projetos antigos abrem iguais. API: `POST /api/projects/<id>/assets?node=…&folder=…`.
- **VAEs, codificadores de texto e mmproj instalados junto do modelo, automaticamente.** Ao baixar um modelo (tela Modelos), o OpenFlow baixa também: o **VAE** e os **codificadores de texto** (famílias conhecidas — FLUX.2/3, Qwen-Image, Z-Image, Wan 2.1/2.2 — ou o que o próprio repositório traz ao lado) e o **mmproj** de modelos de visão (escolhe F16/BF16/Q8_0/F32 e salva como `<modelo>.mmproj.gguf`). A tela mostra antes **o que vem junto** e o tamanho; os downloads retomam e não repetem o que já existe; a falha de um arquivo de apoio não desfaz o modelo. **Instalar o que falta** na tela (ou `flow models support`) repara modelos já baixados; apagar um modelo apaga o `mmproj` dele. Desligável (`hf.auto_support`). Com a biblioteca `local`, um modelo com `mmproj` é carregado com entrada de imagens (melhor esforço).
- **O comando `flow`** em Linux, macOS e Windows: `flow` (abre), `flow setup`/`flow install`, `flow update`, `flow models list|install|support`, `flow libs`, `flow native`, `flow folder`, `flow doctor`, `flow version`.
- **Instaladores por terminal**: `install.sh` (Linux e macOS) e `install.ps1` (Windows) instalam e atualizam com o mesmo comando — Python (se faltar), ambiente isolado, OpenFlow, bibliotecas opcionais, modelos pré-instalados (perguntando antes) e núcleo Rust.
- **Telas novas e simples:** *Projetos*, *Modelos* (recomendados, busca no Hugging Face com todas as quantizações, instalados com o estado dos arquivos de apoio) e *Configurações* (texto IA, mídia, voz, projetos, aparência, desempenho).
- **Acessibilidade:** links e botões de verdade, rótulos para leitores de tela, foco visível, uso só pelo teclado, tema claro/escuro/automático, tamanho 90–150 %, animações reduzidas; paleta `Ctrl/⌘+K`, `Alt+N` (novo projeto), `/` (pesquisar), `?` (atalhos).

### Mantido do Canvas do ASTA
- Todos os nós (texto, imagem, vídeo, som, voz, transcrição, 30 nós utilitários e o Editor de vídeo com MP4), menções `@`, seletor de modelo por nó, **Gerar fluxo com IA**, estilos globais, cache por hash, busca de modelos no editor, provedores de mídia (OpenAI, ElevenLabs, Google, Stability, Replicate, Hugging Face, Stable Diffusion WebUI, Hugging Face local, GGUF local, Demo).
- **Backend Rust mantido:** o núcleo `openflow_core` (`openflow/native`) com espelho em Python de cada função (`flow native setup` baixa a biblioteca pronta e confere o SHA-256).

### Mudou em relação ao ASTA
- Fora do OpenFlow (continuam no ASTA): chat, Game Engine, Scriber, Data, Avatars, Studio, Computer Use, Code, Work, Rebuild, app para celular e instaladores gráficos (`.exe`, `.pkg`, AppImage, APK). O **Enviar ao Studio** saiu junto com o Studio.
- Dados em `~/.openflow` (`OPENFLOW_HOME`); projetos em `projects/<id>/project.json`; API em `/api/projects`; variáveis `OPENFLOW_*`.
- A busca de modelos no Hugging Face agora **devolve o erro** quando nenhuma consulta chega lá (antes mostrava «nada encontrado»).
- **Corrigido no núcleo Rust:** a onda triangular da síntese de áudio saía com o sinal invertido em relação ao espelho em Python (`1−2·|2c−1|` em vez de `2·|2c−1|−1`); o teste de equivalência Rust ↔ Python do ASTA já falhava com o núcleo compilado. Agora os dois batem, com um teste novo em Rust.

### Verificado
- Linux, Python 3.13: suíte completa em Python (442 testes; com o núcleo Rust compilado nenhum é pulado, inclusive os de equivalência Rust ↔ Python), testes de navegador no Chromium (projetos e pesquisa, pastas e subpastas, modelos e arquivos de apoio, editor, nós, menções, seletor de modelo, vídeo), 14 testes em Rust, verificação de traduções, `install.sh` de ponta a ponta contra uma cópia local e `flow doctor`/`flow version` do resultado.

### Não verificado (honestidade)
- `install.ps1` num Windows de verdade e `install.sh` no macOS; os jobs de CI para Linux/macOS/Windows estão escritos, mas não rodaram. Compilação do núcleo Rust para macOS, Windows e ARM.
- Downloads reais de VAEs, codificadores de texto e `mmproj` do Hugging Face: os testes simulam os downloads (os nomes de arquivo dos repositórios curados e de exemplo foram conferidos nas listagens do Hugging Face, mas nenhum arquivo grande foi baixado).
- Inferência com modelos GGUF e GPUs reais; entrada de imagens por `mmproj` com um modelo real (depende de o `llama-cpp-python` instalado conhecer a família do modelo); provedores de nuvem com chaves reais.
- Nenhuma medição de desempenho.
