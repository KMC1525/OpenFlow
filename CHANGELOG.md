# Changelog

Formato: `## [versão] — data`. Cada versão traz o que mudou para quem usa e, com honestidade, o que **não** foi verificado. [English](CHANGELOG.en.md)

## [0.9.0] — 2026-11-14

### Novo
- **Wan (Alibaba) local, em GGUF:** **Wan2.2 T2V A14B** (texto → vídeo), **Wan2.2 I2V A14B** (imagem → vídeo) e **Wan2.1 I2V 14B** (imagem → vídeo), além do Wan2.1 T2V e do Wan2.2 TI2V 5B que já existiam. Vídeo em 480p (832×480 ou 480×832), até 81 quadros (≈ 5 s a 16 quadros/s).
- Os A14B usam **dois modelos** (ruído baixo + ruído alto): escolha o `…LowNoise…gguf` e o OpenFlow baixa sozinho o `…HighNoise…gguf` **da mesma quantização**, junto do VAE do Wan2.1 e do codificador UMT5-XXL. O Wan2.1 I2V baixa também o CLIP vision. Esses arquivos de apoio não aparecem na lista de modelos.
- Modelos imagem → vídeo exigem a «Imagem inicial» do nó Vídeo (a mensagem diz o que fazer); o texto → vídeo A14B avisa que ignorou uma imagem ligada.
- Parâmetros do ruído alto (`high_noise_cfg_scale`, `high_noise_sample_steps`, `high_noise_sample_method`) e `clip_vision_path` também valem pelo `sd-cli`.

### Ainda não verificado
- Nenhum modelo Wan foi gerado de verdade aqui (sem modelo nem placa); os repositórios e arquivos foram conferidos no Hugging Face e os testes cobrem o reconhecimento, os arquivos de apoio e a montagem do comando.
- Passos e CFG iniciais (20 passos no ruído baixo, 10 no alto, CFG 3,5) vêm da documentação da stable-diffusion.cpp; ajuste em Parâmetros extras se o resultado não agradar. Os A14B pedem muita RAM/VRAM e tempo.

## [0.8.0] — 2026-11-14

### Novo
- **Qwen (Alibaba Cloud)** como provedor de nuvem: imagens (Qwen-Image, geração e **edição** com até 3 referências pelo Qwen-Image-Edit) e **vídeos Wan** (texto → vídeo e imagem → vídeo). Chave do Model Studio; endereço internacional por padrão (troque para o da China em Configuração → Mídia).
- **Krea** como provedor de nuvem: informe o modelo como `provedor/modelo` (`krea/krea-3`, `bfl/flux-1-dev`…).
- **Bria (FIBO)** como provedor de nuvem: geração com uma imagem de referência.
- **Modelos locais (GGUF)** com os arquivos de apoio baixados junto: **Qwen-Image-Edit** (2509/2511; VAE, codificador Qwen2.5-VL e o projetor de visão `mmproj`), **Krea 2** (Raw e Turbo), **FLUX.1 Krea [dev]** e **Bria FIBO 2.0** (Dev e Edit Turbo), com passos e CFG de cada variante.
- Os provedores novos tentam de novo só com o essencial se o serviço recusar um parâmetro opcional, e mostram a mensagem do serviço inteira.

### Ainda não verificado
- Os três provedores de nuvem seguem a documentação pública (envio + consulta da tarefa), mas **não foram testados com chave real**; os testes usam respostas simuladas.
- Krea 2 e FIBO 2.0 locais dependem de a stable-diffusion.cpp instalada reconhecer a arquitetura; se não reconhecer, o nó avisa. Qwen-Image-Edit usa o `llm_vision_path` da biblioteca.
- Wan 2.2 A14B (dois modelos, alto e baixo ruído) local não entrou nesta versão; o Wan 2.2 TI2V 5B e o Wan 2.1 seguem como antes, e o Wan na nuvem vem pelo Qwen.
- Licenças: Krea 2 (Krea 2 Community License) e FIBO 2.0 (CC BY-NC 4.0 nos GGUF) restringem o uso comercial.

## [0.7.0] — 2026-11-14

### Corrigido
- **Miniaturas (e qualquer imagem) saíam em retrato** quando uma única foto em retrato era ligada como referência (ou vinha da pasta de estilos) no modo **Gerar**: o modelo local herdava a proporção da foto e ignorava a resolução escolhida (16:9 virava vertical). Agora, ao Gerar, vale sempre a resolução do nó; só no modo **Editar** com uma imagem o resultado mantém a proporção dela (o lado maior segue a resolução escolhida). Vale para a biblioteca Python e para o `sd-cli`.

## [0.6.0] — 2026-11-14

### Novo
- **Mais resoluções para gerar e editar imagens:** de 25+ opções agrupadas em Quadrado, Paisagem e Retrato — de 512×512 a 2048×2048, 1920×1080, 1080×1920, 2560×1080, 832×1216, 1344×768 e outras (as grandes aparecem como «pesado»). Valem no modo Gerar e no modo Editar.
- Os modelos locais (GGUF) geravam no máximo 1024 px no lado maior; agora o limite é **2048 px** (`OPENFLOW_MAX_SIDE`, de 512 a 4096). Resoluções grandes pedem muita RAM/VRAM e tempo, sobretudo na CPU. Provedores de nuvem continuam ajustando para os tamanhos que a API aceita.
- Não verificado: geração real nas resoluções grandes (sem modelo aqui).

## [0.5.0] — 2026-11-14

### Corrigido
- **«get sd version from file failed» ainda aparecia no terminal com o FLUX.3.** Modelos FLUX.3 (que a biblioteca do PyPI nunca reconheceu) agora vão **direto ao `sd-cli`**, sem nem tentar carregar na biblioteca; e essa mensagem de recusa não é mais repetida no terminal (o OpenFlow já trata a recusa sozinho). `OPENFLOW_SD_INPROC=1` força a biblioteca.
- Não verificado: a geração real com o FLUX.3 Klein (sem o modelo nem o `sd-cli` aqui); se o `sd-cli` recusar o modelo, o nó mostra a saída dele.

## [0.4.0] — 2026-11-14

### Novo
- **Configurações → Desempenho → Rodar em:** *Automático* (usa a placa de vídeo se houver), *Só CPU* ou *GPU*. Vale para os modelos de texto (llama.cpp), os de mídia em PyTorch e para o `sd-cli`: o OpenFlow baixa sozinho o executável do tipo certo (cuda12 em NVIDIA, vulkan em AMD/Intel, cpu) e troca quando você muda a opção. `OPENFLOW_SD_BACKEND` continua mandando.

### Limites
- A biblioteca `stable-diffusion-cpp-python` usa o que foi compilado nela; a opção controla o `sd-cli`, o llama.cpp e o PyTorch. Não verificado com GPU de verdade (aqui não há placa): testado com a detecção simulada.

## [0.3.0] — 2026-11-14

### Corrigido
- **FLUX.3 Image Klein (e outros modelos que a biblioteca recusa) ainda mostrava «get sd version from file failed» no terminal a cada geração.** A mensagem vinha da biblioteca, que tentava carregar o modelo inteiro antes de o OpenFlow cair no `sd-cli`. Agora, depois da primeira recusa, o modelo fica registrado (`sd_unsupported.txt` na pasta de dados) e as gerações seguintes vão **direto ao `sd-cli`**, sem recarregar nem repetir o erro. `flow libs --sd-latest` limpa o registro (a biblioteca nova pode reconhecer o modelo).

### Não verificado
- Eu não tinha a mensagem de erro do nó nem o resultado do `sd-cli` no seu computador: se o `sd-cli` também recusar o FLUX.3 Klein (a versão dele pode ainda não ter esse formato), o nó mostrará a saída dele. Testado só com a lógica simulada; sem o modelo nem o download do `sd-cli` aqui.

## [0.2.0] — 2026-11-14

### Corrigido
- **Modelos que a stable-diffusion.cpp da biblioteca não reconhece** (ex.: FLUX.3 Image Klein: «get sd version from file failed» no terminal e a geração parada). Agora o OpenFlow **baixa sozinho o `sd-cli` pronto** (a stable-diffusion.cpp mais nova, sem compilar) e gera por ele, com os mesmos arquivos de apoio; antes era preciso clicar num botão do nó. Desligue com `OPENFLOW_SD_CLI_AUTO=0`; se o download falhar, o botão do nó continua valendo.
- **Barra de progresso com lixo na tela** (`########… 359/359 - 2.08GB/s[K`): os códigos de terminal do sd-cli (como «apagar linha») eram mostrados no nó. Agora são removidos de todas as mensagens de progresso, que aparecem como «Etapa 359/359 · 2.08GB/s».
- No CI, os testes em Python 3.9 no Linux rodam em `ubuntu-22.04` (o `ubuntu-latest` atual não tem Python 3.9 no `setup-python`).

### Novo
- **Importar projeto (.zip)** na tela inicial: cria um projeto novo a partir de um `.zip` baixado do OpenFlow (`POST /api/projects/import`). O arquivo é tratado como não confiável (só entram os arquivos listados no projeto, com nomes seguros e limite de tamanho).

### Verificado / não verificado
- Testes automáticos novos para o download automático do sd-cli, a limpeza do progresso e a importação (incluindo `.zip` hostil). **Não verificado:** a geração com o FLUX.3 Klein de verdade (precisa do modelo, da GPU/CPU e do download do `sd-cli` do GitHub, bloqueado aqui): a correção foi validada com a saída do sd-cli simulada.

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
