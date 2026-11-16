# Changelog

Formato: `## [versão] — data`. Cada versão traz o que mudou para quem usa e, com honestidade, o que **não** foi verificado. [English](CHANGELOG.en.md)

## [0.44.0] — 2026-11-16

### Removido — configurações legadas ou inúteis
- **Texto (IA):** saíram o botão «Carregar modelos» (nunca aparecia nos provedores que sobraram), os campos escondidos de endereço, chave de API e «vision» (o cartão passou a gravar só o **modelo** e a **janela de contexto**), os rótulos «local» e «geração» (virou «em uso») e restos de código do tempo da nuvem.
- **Imagem, vídeo, som e voz:** saíram o aviso «sem chave», o ponto de «configurado», o selo «local» (todos os provedores são locais) e a palavra «conexão» do teste.
- **Aparência:** o texto de «Padrões da aparência» não fala mais de chaves e avatares; o texto do núcleo Rust não fala mais de «agentes».
- **Arquivo de configurações:** a seção `generation` (temperatura, tokens e «content» herdados do Chat do ASTA, que ninguém lia), a seção `voice`, as chaves de API, os endereços e o `vision` dos provedores e o `media.urls` saem do `settings.json` na próxima gravação; arquivos antigos continuam carregando. A exportação/importação de configurações e o «Restaurar padrões» deixaram de tratar dessas seções.
- **API:** `GET /api/state` e `/api/media/providers` não trazem mais `needs_key`, `has_key`, `base_url`, `docs`, `login`, `oauth` e afins; a rota `POST /api/providers/models` saiu; os provedores de mídia perderam `key`, `base`, `need_key` e `need_url`.
- Em «Modelo» dos nós: «Configurar provedores e chaves…» virou «Configurar provedores…» e «Sem modelo da nuvem», «Sem modelo (Demo)».

### Mantido de propósito
- **Token do Hugging Face** (modelos restritos), conexões por download, «baixar junto o VAE…», Desempenho (CPU, GPU, Rust), Aparência (tema, cor, escala, densidade, fonte, animações, idioma), Projetos e a escolha de precisão dos downloads em Imagem, vídeo, som e voz: tudo isso é lido pelo app.

### Ainda não verificado
- Não revisei a tela a tela de todas as combinações de idioma (a checagem de traduções cobre os textos novos).
- Ficaram fora desta limpeza campos internos sem tela (por exemplo `server.max_upload_mb`, que o app lê).

## [0.43.0] — 2026-11-16

### Novo — acompanhar os downloads de modelos dentro do Canvas
- Um botão de **downloads** fica logo à direita da barra de pesquisa de modelos no topo do editor: mostra quantos downloads estão rodando (contador e uma barrinha de progresso geral) e, ao clicar, abre um painel com **cada download**: nome, repositório, porcentagem, bytes baixados, velocidade e tempo restante, nota do passo atual, botão **Cancelar**, e os **recentes** da sessão (concluídos, cancelados e os que falharam, com o motivo).
- Atualiza sozinho (a cada 1 s com download ou painel aberto; a cada 4 s parado) e na hora quando você aperta Baixar na barra de pesquisa. Fecha com Esc ou clicando fora; no celular o painel ocupa a largura da tela.
- Usa os mesmos dados da aba Downloads da Biblioteca (`/api/library/downloads`): inclui downloads de modelos, arquivos de apoio (VAE, codificador de texto), modelos recomendados e a biblioteca do sd-cli.

### Ainda não verificado
- Testado com respostas simuladas da API de downloads (o ambiente não tem rede para baixar modelos de verdade); a lista em si vem de um endpoint que já existia e é coberto pelos testes da Biblioteca.
- O painel mostra os downloads **desta sessão do servidor**: reiniciar o OpenFlow zera a lista de recentes (como na Biblioteca).

## [0.42.0] — 2026-11-16

### Mudou — pesquisar e baixar modelos agora é só pela barra de pesquisa do Canvas
- **A barra de pesquisa de modelos do Canvas** (no topo do editor) ganhou tudo o que a tela de modelos da Biblioteca tinha: ao clicar nela aparecem os **recomendados** (modelos «prontos para instalar» e o catálogo GGUF da Unsloth e de parceiros, como o ChatR Labs); dá para **colar um endereço `dono/nome`** (o repositório abre direto, mesmo que a busca não o liste); a lista de quantizações mostra o aviso de repositório incompatível e o que **vem junto** (VAE, codificador de texto, mmproj).
- **Formato não-GGUF:** imagem e vídeo escolhem entre **GGUF** (quantizações) e **Original** (diffusers, com a precisão fp32/fp16/bf16); som, voz, transcrição e 3D usam o formato original; o **texto só roda GGUF** (llama.cpp), então o formato fica travado em GGUF.
- **Biblioteca:** saíram o botão «Baixar mais modelos», a tela de busca/download de modelos (`views/models.js`) e a rota `GET /api/hf/search`. A Biblioteca só guarda, organiza, usa e apaga modelos e arquivos; a aba Downloads continua mostrando o progresso.
- Os avisos que antes mandavam para a Biblioteca/Modelos (nó sem o modelo baixado, repositório compatível com a stable-diffusion.cpp, boas-vindas, mensagens do servidor) agora abrem ou apontam a barra de pesquisa do Canvas.
- **Configurações → Desempenho → Downloads de modelos:** passaram para cá as conexões por download, o «baixar junto o VAE/codificadores/mmproj» e o token do Hugging Face (modelos restritos), que moravam na tela de modelos removida.
- Corrigido: o texto do núcleo Rust ainda dizia «Agentes, armazenamento e memória» (agentes saíram na v0.40).

### Ainda não verificado
- A pesquisa de verdade no Hugging Face não rodou aqui (sem rede no ambiente): os testes de navegador usam respostas simuladas da API.
- Modelos de texto no formato original (transformers) não rodam no OpenFlow, por isso o texto só pesquisa GGUF.
- O download de modelos continua disponível também em Configurações → Imagem, vídeo, som e voz (a escolha de precisão de cada provedor) e nos modelos recomendados do `flow setup`: só a Biblioteca perdeu a pesquisa e o download.

## [0.41.0] — 2026-11-16

### Novo — ChatR Labs · Qwen-Image 2.1 Uncensored Omni Quantized
- O repositório [`chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized`](https://huggingface.co/chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized) (Qwen-Image 2.1 com um adaptador Omni «sem censura» fundido e quantizado, passo 90000) aparece em **Modelos → Modelos da Unsloth e de parceiros** como *Experimental*, com a lista das quantizações GGUF (Q4_0 ≈ 4,2 GB … Q8_0 ≈ 7,7 GB e BF16 ≈ 14 GB; Q4_K_M é a recomendada) e o botão «Ver quantizações».
- Os arquivos `qwen-image-2.1-step90000-*.gguf` são reconhecidos como **Qwen-Image 2.1** e usam a **receita do cartão: 35 passos e CFG 5,0** (os modelos oficiais do Qwen-Image 2.1 e o Turbo mantêm as receitas deles: 20 passos/CFG 6,0 e 8 passos/CFG 1,0). Edição com várias referências, como no Qwen-Image 2.1.
- Ao baixar o GGUF, o OpenFlow baixa junto o **VAE do Qwen-Image 2.1** e o **codificador de texto Qwen3-VL-8B** (≈ 5,8 GB, sem baixar de novo se já existirem); os `-comfy.safetensors` e as pastas do diffusers do repositório não são confundidos com arquivos de apoio.
- As pastas NF4/INT8/FP8 (só transformador, para o diffusers) e os `-comfy` (só ComfyUI) **não** rodam no OpenFlow: o provedor «Hugging Face local» recusa o repositório com uma mensagem que aponta os `.gguf` e o provedor «GGUF local».
- Corrigido: os modelos «Experimental» do catálogo (MiniMax H3, LTX-2.x…) não tinham o botão «Ver quantizações»; agora têm.
- A licença do modelo é a **Qwen Research** (só pesquisa e uso não comercial) e isso consta na dica do catálogo.

### Ainda não verificado
- **Nenhum desses GGUF foi gerado aqui** (sem pesos nem GPU). Não confirmei se a stable-diffusion.cpp instalada reconhece os nomes de tensores dos GGUF do ChatR Labs (layout «297»: o mesmo estilo dos GGUF da Unsloth); se não reconhecer, o aviso do nó diz e o botão de atualizar a biblioteca aparece, como nos outros modelos.
- O cartão manda `er_sde` + `simple` no ComfyUI; o OpenFlow usa `euler` (o sampler que as outras receitas do Qwen-Image 2.1 usam na stable-diffusion.cpp). O prompt negativo de um espaço só vale para o diffusers/ComfyUI.

## [0.40.0] — 2026-11-16

### Removido — agentes, multi-agentes e níveis de esforço (Low … Omni) do ASTA
- Saíram a **mesa de agentes** (1 a 32 agentes em paralelo, notas privadas, revisão entre pares e Sintetizador — `team.py`), os **níveis de esforço** Low · Medium · High · Extra · Mega · Max · Ultra · Omni (`efforts.py`) e o «tempo de pensamento» pedido ao modelo (`providers/thinking.py`), junto da rota `GET /api/team`, do seletor de equipe da barra do canvas, do cartão «Equipe de agentes» em Configurações → Projeto, do campo `team` no pedido de execução e dos textos, estilos e testes deles.
- Os nós de texto com IA («Texto IA», «Refinar com IA») e a descrição de estilo agora fazem **uma única chamada** ao modelo, com o tamanho de resposta fixo do nó (sem multiplicador de esforço).
- Configurações antigas com `agents`/`effort` continuam carregando (as chaves são ignoradas).

### Ainda não verificado
- Mantive o **planejador do núcleo Rust** (`plan_agents`): hoje só serve para decidir quantos modelos de texto locais podem ficar carregados na memória ao mesmo tempo e para a fila com prioridade do modelo embutido; a ABI do núcleo e o Rust não foram mexidos (não recompilei nada). Se quiser, ele também sai numa versão própria.
- `Cancelled` e a fila de prioridade (`scheduler.py`) ficam: são do cancelamento e da fila do modelo local, não dos agentes.

## [0.39.0] — 2026-11-15

### Removido (por enquanto) — «Gerar fluxo com IA»
- Saíram a **caixa de prompt do canvas** («Gerar fluxo com IA»), a rota `POST /api/projects/{id}/flow`, o pipeline Planejador → Revisor (`canvas/flow.py`) e o pacote `agents/` que só ele usava, além dos textos, estilos e testes dele. Projetos, nós, modelos de projeto (templates) e tudo mais continuam como estavam; montar o fluxo agora é só pela paleta, por arrastar e soltar, ou pelos modelos de projeto.
- **Fica:** a equipe (esforço Low…Omni e 1–32 agentes) dos nós de texto com IA — o seletor foi para a barra do topo do canvas, ao lado de «Executar tudo» (antes morava dentro da caixa de prompt) — e a mesa de agentes (`team.py`), que os nós «Texto IA» e «Refinar com IA» usam. O Demo não trata mais o marcador de agente do planejador.
- O que era `Cancelled` do pacote removido agora está em `openflow/util.py`.

### Ainda não verificado
- Não removi `team.ensemble_json`/`critique_json` (a mesa de agentes que devolvia JSON): ficaram sem uso na aplicação, mas cobertos por testes, para quando o recurso voltar.
- Em telas médias a barra do topo quebra em duas linhas (equipe + Executar tudo embaixo); conferi só por captura de tela em 1500, 1100 e 390 px.

## [0.38.0] — 2026-11-15

### Corrigido — varredura geral (todos os nós, telas e a API)
- **GIF como imagem parada num vídeo** (Editor, «Juntar clipes», «Imagens em vídeo» e «Vídeo final») falhava com «Option not found» do ffmpeg; agora o GIF entra pelo primeiro quadro.
- **Editor com só áudio** na linha do tempo falhava com «Error opening output files»; agora gera um vídeo de fundo liso com o som.
- **«Extrair do texto» com padrão (regex) que nunca termina** (ex.: `(a|a)*b`) travava a execução sem poder cancelar; agora o padrão roda num processo à parte com limite de 4 s e avisa «demorou demais».
- Entradas inválidas da API (tipo de busca, repositório, provedor que não existe) respondiam 502 («gateway»); agora respondem 400.
- Lint: f-string sem campos.

### Testado
- **Os 54 tipos de nó (49 executáveis; os outros 5 são Texto, Mídia, Style Prompt, Style Folder e Link) rodam de verdade** (motor + ffmpeg + Demo) com entradas válidas ligadas — `tests/test_all_nodes_v038.py`; só o «Transcrever» depende da biblioteca opcional do Whisper.
- Matriz de entradas estranhas (imagem RGBA/cinza/paleta/WebP/GIF/CMYK/16 bits/minúscula/gigante; vídeo vertical/sem som/dimensão ímpar/fps quebrado/WebM/curtíssimo; áudio WAV mono/OGG/FLAC/M4A/curto) contra todos os nós de mídia.
- Varredura de navegador (`sweep_ui.js`): todas as telas em 390, 1500 e 3440 px sem rolagem horizontal, todas as abas de Configurações, e todos os nós do canvas com cada opção de cada lista e valores estranhos nos campos, depois rodando tudo — sem erros de página.
- Fuzz de 1.700 requisições nas rotas da API e de 8 mil parâmetros de nós: nenhum erro 500; leitura/escrita fora da pasta, zip-slip, segredos nas exportações e origem cruzada continuam bloqueados.

### Ainda não verificado
- Modelos locais reais (llama.cpp, diffusers, Shap-E…) seguem sem execução aqui, por falta dos pesos.
- O «Transcrever» não rodou (falta a biblioteca do Whisper neste ambiente).

## [0.37.0] — 2026-11-15

### Novo — modelos 3D locais (texto → 3D e imagem → 3D)
- **Nó «Modelo 3D»** (grupo novo **3D** na paleta): prompt e/ou imagem → arquivo **GLB** ou **OBJ**, com visualizador no próprio nó (arraste para girar, roda para aproximar, giro automático) e na ampliação; botão Baixar; a Galeria aceita o modelo; a Biblioteca ganhou o tipo «Modelos 3D».
- **Modelos locais do Hugging Face:** **Shap-E** (`openai/shap-e` texto → 3D; `openai/shap-e-img2img` imagem → 3D, escolhido sozinho quando há imagem ligada), **TripoSR** (`stabilityai/TripoSR`) e **Hunyuan3D-2** (`tencent/Hunyuan3D-2mini` / `-2`), só imagem. Com um texto, TripoSR e Hunyuan3D geram antes uma imagem do objeto com o modelo de imagem padrão (duas etapas, avisado no nó).
- Baixar/usar: «3D» na barra de busca de modelos do Canvas (Hugging Face: text-to-3d / image-to-3d) e em Configurações → Mídia; os modelos 3D baixados aparecem só na lista do nó 3D. Nada é baixado em silêncio.
- **Demo offline:** formas procedurais (esfera, rosca, cubo, cone, vaso) com cores — para testar fluxos 3D sem modelo.
- Gravação de GLB e OBJ própria (sem dependências); a malha é centrada e encaixada num cubo de lado 2.

### Ainda não verificado
- **Nenhum modelo 3D real foi executado aqui** (sem pesos, GPU nem as bibliotecas TripoSR/Hunyuan3D): Shap-E, TripoSR e Hunyuan3D-2 foram testados só com substitutos nos testes. A orientação da malha do Shap-E (girada −90° em X) e os nomes de subpasta/argumentos do Hunyuan3D e do TripoSR seguem a documentação deles e podem precisar de ajuste.
- O visualizador é um renderizador simples (sem texturas; usa cores por vértice) e desenha no máximo ~40 mil faces por vez.
- Saídas com textura (UV) dos modelos grandes não são gravadas: só geometria e cor por vértice.

## [0.36.0] — 2026-11-15

### Novo — 2 nós no grupo Imagem para facilitar prompts difíceis
- **Ficha de personagem:** nome, descrição, vistas (frente, lado, costas, três quartos, rosto, corpo inteiro), extras (expressões, paleta de cores, roupa, objetos, poses, comparação de altura), disposição (fileira, turnaround ou grade), pose, fundo, rótulos. Entradas: «Descrição» (textos) e «Estilo». Pede consistência do personagem em todas as vistas.
- **Página de quadrinhos:** formato (página, tirinha, webtoon, yonkoma, splash), cenas em linhas `cena | fala`, personagens ligados, disposição, estilo (americano, mangá, franco-belga, webtoon, cartoon, indie), cor/P&B/retícula, balões (com falas, vazios, sem), sentido de leitura (mangá), título. Cenas além do que o formato comporta geram um aviso.
- Os dois entregam **texto** (o prompt): ligue no nó Imagem. Prompt em inglês (recomendado para os modelos) ou português; um Style Prompt/Folder ligado entra no final. Paleta agora com 53 nós.

### Ainda não verificado
- O prompt é montado de forma determinística; quão bem cada modelo local desenha fichas e quadros (e o texto dentro dos balões) depende do modelo e não foi medido aqui sem os pesos.

## [0.35.0] — 2026-11-15

### Mudou — sem nuvem (por enquanto): só modelos locais do Hugging Face
- **Removidos** todos os provedores de nuvem/frontier (OpenAI, Claude, Grok, Gemini, OpenRouter, ElevenLabs, Stability, Qwen, Krea, Bria, Replicate, Hugging Face Inference…) **e também os servidores locais** (Ollama, LM Studio, servidor llama.cpp, A1111, endpoints compatíveis com OpenAI, voz em modo servidor): sobram **Hugging Face local**, **GGUF local** e o **Demo** offline.
- Configurações antigas migram sozinhas: provedores e chaves removidos são ignorados (e saem do `settings.json` na próxima gravação); padrões voltam ao Demo/automático; nós salvos com um provedor removido usam o padrão do projeto. A aba «Voz» e os campos de chave/URL saíram das Configurações.
- Mensagem clara quando algo pede um provedor que não existe mais.

### Ainda não verificado
- Migração testada com configurações sintéticas, não com instalações antigas reais.
- Modelos locais reais (llama.cpp, diffusers) seguem não exercitados aqui sem os pesos.

## [0.34.0] — 2026-11-15

### Novo — 10 nós novos no canvas (os atuais continuam; todos testados rodando de verdade)
- **Texto:** **Extrair do texto** (links, e-mails, hashtags, números, frases entre aspas, PALAVRAS EM MAIÚSCULAS ou um padrão/regex — com proteção contra padrões que travam) · **Contar texto** (palavras, caracteres, linhas).
- **Imagem:** **Recortar imagem** (por proporção 1:1, 16:9, 9:16, 4:3, 3:2, 21:9 mantendo o centro/topo/base/lado, ou por área em %) · **Marca d'água** (logo no canto, com tamanho, margem e opacidade).
- **Vídeo:** **Mudar a proporção** (9:16 vertical, 1:1, 4:5…: fundo desfocado — o formato de Reels/Shorts —, preencher e cortar, ou bordas; mantém o som e a taxa de quadros) · **Repetir vídeo** (N vezes ou até uma duração) · **Áudio no vídeo** (trocar, misturar ou tirar o som; terminar no vídeo ou no áudio).
- **Som:** **Tirar silêncios** (limite em dB, silêncio mínimo e respiro mantido).
- **Input:** **Padrão e textura** (xadrez, listras, grade, bolinhas e ruído, em duas cores).
- **Output:** **Miniatura com título** (imagem recortada em 16:9 com o título por cima, faixa escura e 3 posições; JPG ou PNG).
- Cada nó tem ícone, ajuda, portas, formulário e tradução; a paleta (agora com **busca**, v0.31) os lista nos grupos de sempre.

### Melhorado — Style Prompt e Style Folder entendem personagens, cenários e objetos
- **Papéis pelas pastas:** o nome da pasta diz o que ela mostra — «Personagens», «Cenários», «Objetos», «Estilo»/«Luz»… (também em inglês). **Uma subpasta é uma entidade** (`Personagens/Maria/frente.png`, `perfil.png`); sem subpastas, arquivos com o mesmo começo de nome viram a mesma (`maria_frente.png` + `maria_perfil_v2.png` → Maria). Um **`.txt`/`.md` com o nome da entidade é a descrição dela**.
- **Descrição estruturada, uma linha por item:** `ESTILO GERAL`, `TRAÇOS COMUNS DOS PERSONAGENS`, `PERSONAGEM — Maria: …` (idade aparente, cabelo, olhos, pele, roupas, acessórios, marcas, postura), `CENÁRIO — Floresta: …`, `OBJETO — Espada: …`, `CONSISTÊNCIA: …` (o que nunca muda entre imagens). A IA com visão recebe **cada imagem legendada com o nome de quem aparece** (até 10 por entidade+estilo) e responde nesse formato; **toda entidade aparece**, mesmo que a IA esqueça uma (entra com o que se sabe: texto ao lado, cores, nº de imagens), e sem IA o OpenFlow monta o mesmo formato com o que tem.
- **Características gerais:** novo campo no Style Folder («todos os personagens usam uniforme azul; traço fino…») entra em todas as descrições. O Style Prompt reconhece `Personagem: Ana — ruiva` (e as outras seções) e tira linhas repetidas.
- **Só o que o prompt precisa:** um Style Folder com 30 personagens não despeja os 30 em cada geração. O prompt «Maria anda pela floresta» recebe o estilo geral, a ficha da **Maria** e do cenário **Floresta**, os traços comuns e a consistência; os outros viram uma linha «Elenco do projeto». (Até 3 entidades entram todas.) Vale para Imagem, Vídeo, Som, Voz, Texto IA e Refinar com IA.
- **Imagens de referência certas:** as imagens mandadas ao modelo agora são as das entidades **citadas** no prompt (uma de cada, depois a segunda…, na ordem em que aparecem), depois as de estilo geral — antes eram sempre as 3 primeiras do nó.
- A descrição aparece no nó linha a linha, com o papel em destaque.

### Ainda não verificado
- Testei a descrição por IA com um modelo **simulado** (o formato pedido, a leitura da resposta, as imagens legendadas e a entidade esquecida); **não testei com um modelo de visão de verdade**, então a qualidade das fichas de personagem depende do modelo.
- Papéis pelas pastas dependem dos nomes (palavras comuns em português e inglês); pastas com outros nomes viram estilo geral. Nomes de arquivo como «IMG_0034.png» não geram entidade.
- A relevância reconhece o nome da entidade no prompt (sem acento e maiúsculas; o primeiro nome basta). Um apelido ou pronome («ela») não é seguido.
- Os nós novos foram testados com vídeos e imagens sintéticos do ffmpeg; «Marca d'água» e «Miniatura» dependem do ffmpeg ter o filtro de texto/fonte (como os nós de texto que já existiam).

## [0.33.0] — 2026-11-15

### Novo — Biblioteca em outras pastas (HD/SSD externo, pendrive, outro disco)
- **Biblioteca → Armazenamento → «Onde guardar»:** escolha **onde ficam os modelos de IA** e **onde ficam os arquivos dos projetos** (imagens, vídeos e sons gerados ou enviados) — um HD ou SSD externo, um pendrive ou outra pasta do próprio computador. Cada um tem a sua pasta («padrão» ou «personalizada»), com o espaço livre, o tipo (SSD/HDD) e o botão **Alterar…**, que lista os **discos e dispositivos** do computador (com o espaço livre e o selo «externo»), deixa navegar pelas pastas ou digitar o caminho e oferece **«Usar a padrão»** para voltar.
- **Mover o que já existe, com segurança:** a opção «Mover o que já existe» **copia primeiro** (com barra de progresso, cancelável e também visível na aba Downloads), confere o tamanho de cada arquivo, **troca a pasta em uso só no fim** e só então esvazia a pasta antiga; falha ou cancelamento **desfaz as cópias novas** e a pasta antiga fica intacta, então nunca falta modelo. Reinicia de onde parou se repetir. Sem «mover», o OpenFlow passa a usar a nova pasta e o conteúdo antigo fica onde está (avisado na janela).
- **Disco externo desligado não quebra o OpenFlow:** se a pasta configurada não está acessível (dispositivo desconectado, pasta apagada), ele **usa a padrão e mostra um aviso** no cartão; quando o disco volta, a pasta escolhida volta a valer.
- **Proteções:** a nova pasta precisa existir (ou a de cima, para criar uma), aceitar gravação e **ter espaço** para o conteúdo; não pode ficar dentro da atual (nem a atual dentro dela); a **raiz de um disco** vira uma subpasta «OpenFlow-modelos»/«OpenFlow-projetos» (nada de espalhar arquivos na raiz do pendrive); e não muda nada com uma geração, download ou outra tarefa em andamento. Novas rotas: `GET /api/storage/locations`, `GET /api/storage/browse` e `POST /api/storage/location`; a configuração fica em `storage.models_dir` e `storage.files_dir`.
- A pasta dos modelos vale para tudo: downloads, arquivos de apoio, a lista da Biblioteca, o `flow models …` do terminal e a carga dos modelos. Os mapas de pastas e as configurações ficam na pasta de dados do OpenFlow.

### Ainda não verificado
- **Não testei com um disco externo de verdade:** os testes usam pastas temporárias (a cópia, o desfazer, a validação, a troca de pasta e o aviso de pasta inacessível rodam; o aviso com o dispositivo realmente desligado foi simulado com um caminho que não dá para criar). A **lista de dispositivos** segue a convenção de cada sistema (Linux `/media`, `/run/media`, `/mnt`; macOS `/Volumes`; Windows letras de unidade) e **não foi executada no Windows nem no macOS**.
- Mover entre discos lentos (HDD externo por USB 2) pode levar bastante tempo; o desempenho **não** foi medido. Rodar modelos a partir de um disco externo lento deixa o carregamento mais demorado (o OpenFlow pré-carrega o modelo na RAM).
- **Não são movidos:** o cache do Hugging Face (componentes do LTX-2), o `sd-cli`, os arquivos enviados soltos (`uploads`), as configurações e o mapa de pastas da Biblioteca — ficam na pasta de dados do OpenFlow.
- Importar as configurações em outro computador traz os caminhos: se não existirem lá, vale o aviso e a pasta padrão.

## [0.32.0] — 2026-11-15

### Corrigido — bugs ao editar vídeos (e imagens) gerados
Procurei rodando cada nó de edição (cortar, velocidade, visual, quadro, GIF, exportar, juntar, apresentação; redimensionar, filtro, texto, colagem) com vídeos e imagens de tamanhos, taxas de quadros e trilhas diferentes (largura/altura ímpares, retrato, muito curto, sem áudio, 12/16/24 fps, imagem de 1×1 e de 3000×200 px). Os bugs achados:
- **Vídeo com largura ou altura ímpar (ex.: 853×481) não podia ser cortado, acelerado nem receber «Visual»:** o ffmpeg recusava («Nothing was written into output file»). Agora o tamanho é arredondado para o par mais próximo (852×480) antes de codificar.
- **Corte, velocidade e visual convertiam tudo para 30 fps:** um vídeo de 16 ou 24 fps (o normal dos modelos) ganhava quadros repetidos e tremia, e um de 12 fps virava 30. Agora a **taxa de quadros de origem é mantida**.
- **Velocidade: a duração saía errada e o som terminava antes da imagem** (3 s a 2× davam 1,67 s de vídeo para 1,51 s de som em vez de 1,5 s nos dois). Agora o vídeo sai com a duração exata (1,50 s a 2×, 0,75 s a 4×), em sincronia com o áudio.
- **Vídeos enviados ou gerados ficavam sem largura e altura anotadas** (só as imagens tinham): agora elas são lidas com o `ffprobe` ao salvar.
- O restante passou sem erros: imagens de 1×1 e 3000×200, texto com `%`, aspas e barra, vídeo sem áudio, vídeo muito curto, juntar vídeos de tamanhos e proporções diferentes, e a edição de imagem pelo motor (uma ou várias referências, vídeo como referência, limite de referências do modelo).

### Ainda não verificado
- Testei com vídeos sintéticos do ffmpeg (`testsrc`), não com saídas reais de modelos de vídeo nem com vídeos de celular (rotação por metadados, VFR de verdade).
- Não achei bugs no modo «Editar» das imagens além do que já estava corrigido; a qualidade de uma edição depende do modelo (não é verificável aqui). Um resultado «quase igual» continua só avisando.
- `reverse` na velocidade carrega o vídeo inteiro na memória (limite do filtro do ffmpeg): vídeos longos em resolução alta podem pesar.

## [0.31.0] — 2026-11-15

### Novo — Melhorias gerais 2.0
- **Telas grandes e ultrawide:** acima de 1700 px a página, a barra lateral, a paleta de nós e o painel de arquivos do canvas crescem junto com a janela (antes o conteúdo ficava numa coluna de 1180 px no meio de um monitor de 3440 px); degraus em 1700, 2200 e 3000 px e um ajuste para telas 21:9 ou mais largas. A Biblioteca ganha colunas e cartões maiores. Nada rola para o lado em 1920, 3440 e no celular (testado).
- **Busca de nós na paleta do canvas:** um campo no topo da aba dos nós filtra pelo nome, pela descrição e pelo grupo (sem diferenciar acentos nem maiúsculas); **Enter** adiciona o primeiro resultado ao fluxo e **Esc** limpa.
- **Memória RAM dual/quad channel, DDR4/DDR5:** o planejador da v0.28 já usava a largura de banda medida para escolher as threads de geração (uma memória de 4 canais satura com mais threads que uma de 1); agora o OpenFlow também **lê os pentes** (Windows pelo SMBIOS/PowerShell; Linux pelo `dmidecode`, quando houver permissão): quantidade, DDR4/DDR5, velocidade, **canais** e a largura de banda teórica, mostrados em Desempenho → Processador. E **avisa o que ajuda**: um pente só (canal único: a velocidade dos modelos é metade), **XMP/EXPO desligado** (a memória roda abaixo do que o pente suporta) e velocidade medida bem abaixo da teórica. Em **servidores e Threadripper/EPYC com vários nós NUMA** o llama.cpp passa a distribuir threads e memória entre os nós.
- **Armazenamento (HDD e SSD):** o OpenFlow detecta se os modelos estão num **HDD ou SSD**. Em **HDD** baixa por **uma conexão só** (gravação sequencial, sem fragmentar o arquivo) e pré-carrega o modelo com **uma thread** (leituras em paralelo viram buscas aleatórias e o disco fica mais lento); em SSD segue paralelo. Nova seção **Biblioteca → Armazenamento**: espaço livre/total, quanto ocupam os modelos (por tipo), projetos e envios, e **limpeza** de downloads incompletos abandonados há mais de 1 hora, temporários de gerações interrompidas e arquivos de projeto que nenhum projeto usa mais — nunca apaga modelos nem arquivos em uso (com um download rodando, os parciais ficam). Rotas `GET /api/storage` e `POST /api/storage/clean`.
- **Rodar os modelos locais na CPU e na GPU ao mesmo tempo:** nova opção **«Híbrido: CPU e GPU juntas»** em Desempenho → Rodar em. **Texto:** a placa leva as camadas que couberem, a CPU o resto (com as threads certas para a parte dela) e ainda **propõe os próximos tokens** (decodificação especulativa por consulta ao prompt) que a placa confirma — sem mudar a resposta. **Imagem e vídeo:** o codificador de texto e o VAE rodam na **CPU** e a placa fica só com o modelo de difusão (cabem modelos e tamanhos maiores); no diffusers, cada parte só ocupa a placa enquanto trabalha.

### Ainda não verificado
- **Híbrido não faz um token sair mais rápido por si só:** a geração de texto passa pelas camadas em sequência, então o ganho é de **capacidade** (modelos que não cabem só na placa) e, quando o texto se repete, da decodificação especulativa. A decodificação especulativa depende da versão do llama-cpp-python (sem ela, só a divisão de camadas); nunca a cronometrei.
- **Os pentes de memória só foram lidos em teste com dados simulados:** não rodei no Windows (PowerShell) nem num Linux com `dmidecode`; sem permissão (o normal no Linux) a leitura fica vazia e só aparece a velocidade medida. A conta de canais pelo nome da posição («ChannelA», «BANK 1») é **estimativa**.
- **Detecção de HDD/SSD:** Linux (`/sys/block/.../rotational`) e macOS (`diskutil`) seguem a documentação; o Windows usa `Get-PhysicalDisk` e **não foi executado**. Discos USB, RAID e nuvem podem aparecer como «desconhecido» (tratados como SSD). Neste computador de teste o disco virtual aparece como HDD.
- NUMA: `numa=1` (distribuir) é o valor da documentação do llama.cpp; não tenho uma máquina com vários nós para testar.
- Telas grandes: conferi só pelo tamanho das caixas e a ausência de rolagem lateral num Chromium simulado de 3440×1440; não olhei num monitor real.

## [0.30.0] — 2026-11-15

### Novo — MiniMax H3 Image (imagem e edição) e o MiniMax H3 completo
- **MiniMax H3 Image** (`unsloth/MiniMax-H3-Image-GGUF`, 33B): roda no OpenFlow pelo `sd-cli` com a receita do cartão — **6 passos, CFG 1,0, `euler`, `--sigmas minimax-h3-image` e `--rng cpu`** (os dois últimos não são opcionais), descarga de parâmetros para a CPU. Baixa junto o **VAE de imagem** (do `MiniMaxAI/MiniMax-H3-Image`, gravado como `minimax-h3-image-vae.safetensors` para não colidir com outros «diffusion_pytorch_model») e o **codificador Qwen3-VL-32B** do MiniMax H3 (Q2_K_M para os denoisers Q2, Q4_K_M para os demais). Recomendado pelo cartão: `UD-Q4_K_XL` (13,6 GB).
- **Edição com até 16 referências:** as imagens ligadas ao nó vão como `-r` e o OpenFlow usa a convenção do modelo: **`<Picture 1>`, `<Picture 2>`…** no prompt. Se o seu prompt já cita as imagens, fica como está; senão o OpenFlow acrescenta («Edit <Picture 1>. …» com uma referência; «Reference images: <Picture 1>, … .» com várias). As referências valem também no modo Gerar.
- **Tamanhos em múltiplos de 32** (cada token do modelo cobre 32×32 pixels); em edição de uma imagem, o tamanho segue a proporção dela (o cartão avisa que um tamanho quadrado corta uma referência larga).
- **Famílias separadas:** imagem, vídeo (texto + quadros) e vídeo por referências do H3 não se confundem mais pelo nome do arquivo (`minimax_h3_image…` antes casava com a família de vídeo).
- A biblioteca Python do PyPI nunca reconhece o H3: vai direto ao `sd-cli` (como o H3 de vídeo da v0.22). Na lista da Unsloth (Modelos → Baixar mais modelos) o **MiniMax H3 Image** aparece como «Experimental».

### Ainda não verificado
- **Não gerei imagens com o H3 Image aqui** (sem GPU, sem rede, sem `sd-cli`; o modelo tem 33B): os testes cobrem família, receita, arquivos de apoio, argumentos do `sd-cli`, convenção `<Picture N>` e tamanhos. O `sd-cli` precisa ser recente (o suporte entrou na stable-diffusion.cpp pelo PR #2324).
- A regra do prompt `<Picture N>` quando você não as cita é uma **escolha minha a partir do cartão**, não testada; se o resultado ficar estranho, cite as imagens no prompt.
- **O codificador de texto (≈ 18 GB) é baixado uma vez por tipo de modelo:** usar o H3 de imagem e o de vídeo ocupa duas cópias dele. O OpenFlow ainda não compartilha o arquivo entre as pastas.
- O pipeline original em diffusers (68 GB, `MiniMaxAI/MiniMax-H3-Image`) e o expansor de prompt `MiniMax-H3-Image-PE` (um modelo de texto de 27B) **não** foram incluídos; o PE pode ser usado como modelo de texto à parte.
- No H3 de vídeo nada mudou além de a família não capturar mais os arquivos de imagem.

## [0.29.0] — 2026-11-15

### Novo — GPU Upgrade: modelos locais mais rápidos em placas NVIDIA, AMD e Intel (núcleo Rust)
- **Detecção de placas** (`gpu.rs`, interface 6 do núcleo): NVIDIA pelo `nvidia-smi`; **AMD e Intel pelo `/sys/class/drm` (Linux)**, com a memória total/livre, o tipo (**dedicada** ou **integrada**), o nome do banco `pci.ids` do sistema e o backend certo (CUDA, Vulkan, Metal). Antes só a NVIDIA existia para o OpenFlow: numa AMD/Intel o texto caía sempre na CPU (ou, com «GPU» forçada, mandava tudo para a placa sem medir a memória).
- **Planejador de GPU** para modelos de texto: quantas camadas vão para a placa e **onde fica o cache de atenção**. Em **placas pequenas (2–6 GB, notebooks)** o cache fica na RAM e a VRAM recebe só camadas — cabem mais camadas, e a conta (largura de banda da placa × RAM medida na v0.28) decide quando vale; **reserva maior de VRAM** nas placas pequenas (o sistema usa uma parte); **atenção flash só em NVIDIA/Apple** (no Vulkan a compatibilidade varia); **GPU integrada não é usada** por padrão (divide a RAM com a CPU, que rende igual) — a menos que você escolha «GPU» em Rodar em.
- **Corrigido um erro de planejamento:** o `llama-cpp-python` do PyPI é **só CPU**. Com uma placa NVIDIA e esse pacote, o OpenFlow planejava como se a placa fosse usada (janela de contexto pela VRAM, só 4 threads, lotes grandes) e o modelo rodava na CPU com os ajustes errados. Agora ele **pergunta ao llama.cpp se há suporte a GPU** (`llama_supports_gpu_offload`) e, não havendo, trata o modelo como de CPU (ajustes da v0.28).
- **sd-cli (imagem e vídeo):** com uma AMD/Intel **dedicada**, o modo Automático passa a baixar o executável **Vulkan** (antes só com «GPU» forçada).
- **Configurações → Desempenho → «Placa de vídeo (aceleração)»:** lista as placas (memória, dedicada/integrada, backend), mostra se o llama.cpp instalado **usa** a placa e, se não, **o comando para reinstalá-lo com CUDA/Vulkan/Metal** (com botão Copiar; PowerShell no Windows), o executável do sd-cli em uso e, por modelo de texto, quantas camadas vão para a placa, se o cache fica na RAM e a velocidade esperada. Nova rota `GET /api/gpu`.
- Equivalente em Python sem o núcleo Rust; os testes conferem que Rust e Python dão o **mesmo plano** em 400 combinações.

### Ainda não verificado
- **Não há placa de vídeo neste computador:** a detecção NVIDIA/AMD/Intel e a leitura do `/sys/class/drm` seguem a documentação do kernel e do `nvidia-smi` mas **nunca rodaram numa placa real**; o planejador foi testado com valores simulados. **Intel Arc:** a leitura da memória dedicada (`lmem_total_bytes`) depende do driver (i915) e pode vir vazia. **Windows e macOS:** só NVIDIA (Windows) e Apple Silicon (já existia) são detectados; AMD/Intel no Windows não.
- As velocidades «≈ tok/s» dependem de uma **tabela de largura de banda de placas comuns** (especificações dos fabricantes, não medidas); placa fora da tabela fica sem estimativa. Não cronometrei nenhum modelo.
- **O OpenFlow não instala o llama.cpp com GPU sozinho:** compilar leva minutos e precisa do kit do fabricante (CUDA Toolkit, Vulkan SDK); ele só mostra o comando. O ROCm da AMD não foi tratado — a rota recomendada é Vulkan.
- `offload_kqv` e a atenção flash dependem de a versão instalada do llama-cpp-python aceitá-los; em versão antiga o carregamento cai para as opções básicas, como já acontecia.

## [0.28.0] — 2026-11-15

### Novo — CPU Upgrade: modelos locais mais rápidos em processadores AMD/Intel (núcleo Rust)
- **O OpenFlow agora conhece o seu processador** (`cpu.rs`, interface 5 do núcleo): fabricante, nome, **núcleos de desempenho (P) e de eficiência (E)** em CPUs híbridas (Intel Alder Lake e mais novos; AMD Zen c e ARM big.LITTLE no Linux, por frequência), caches L2/L3, melhor SIMD (AVX-512 › AVX2 › AVX › NEON) e extensões como VNNI/AMX.
- **Mede a velocidade da memória** (uma vez, uns 0,5 s, guardada em `cpu_bench.json`): na CPU cada token lê o modelo inteiro da RAM, então **tokens/s ≈ largura de banda ÷ tamanho do modelo**. Com isso o planejador escolhe:
  - **threads de geração** só até saturar a memória (+1 de folga, sem passar dos núcleos de desempenho; um núcleo fica livre para o sistema): mais threads que isso só atrapalham;
  - **threads de leitura do prompt** = todos os núcleos de desempenho (essa etapa é de cálculo);
  - **lotes menores em CPUs fracas** (≤ 4 núcleos, sem AVX2, memória < 15 GB/s ou < 6 GB livres): lote 128 / micro-lote 64 (cabem no cache L2), cache de atenção em 8 bits e janela de contexto de até 4096 — antes um PC modesto usava lotes de 256–512 e a janela cheia.
- **CPU híbrida no Linux:** o processo é **fixado nos núcleos de desempenho** (`sched_setaffinity`), para as threads não caírem nos de eficiência e segurarem as outras. Desligue em Configurações → Desempenho ou com `OPENFLOW_CPU_PIN=0`.
- **Configurações → Desempenho → «Processador (CPU)»:** mostra processador, núcleos, SIMD, L3, a **velocidade da memória** (botão «Medir a memória»), **até quantos GB de modelo rodam a 5 e a 10 tokens/s** e, para cada modelo de texto baixado, a velocidade esperada (**Fluido / Usável / Lento**). Novas rotas `GET /api/cpu` e `POST /api/cpu/bench`.
- Tudo tem equivalente em Python (sem o núcleo Rust cai nele, só sem a medida de memória); os testes conferem que Rust e Python dão **exatamente** o mesmo plano em 300 combinações.

### Ainda não verificado
- Testei só **neste computador** (Linux, Intel Xeon, 4 núcleos, sem núcleos E): **a fixação em CPU híbrida e a detecção de núcleos P/E nunca rodaram numa CPU híbrida de verdade** (a lógica é testada com dados simulados). **AMD:** o identificador de fabricante e as caches (cpuid `0x8000001D`) seguem a documentação, mas não rodei numa AMD. **Windows e macOS:** a separação P/E não é detectada (tratados como CPU comum) e a fixação não é feita; a medida de memória e o planejador valem.
- As velocidades «≈ tok/s» são **estimativas** (largura de banda × 0,65 ÷ tamanho do modelo), não medidas com um modelo de verdade; o ganho real em PCs fracos ainda não foi cronometrado. Nem todo modelo MoE segue a regra (só parte dos pesos é lida por token).
- A estimativa de leitura do prompt (`est_pp`) é grosseira e não aparece na interface.

## [0.27.0] — 2026-11-15

### Novo — Biblioteca 2.0 (no estilo do Google Drive)
- **Tela redesenhada:** barra lateral com as seções (**Modelos de IA**, **Arquivos gerados**, **Downloads**) e a árvore de pastas; no topo, **barra de pesquisa**, trilha de navegação (breadcrumb), filtros de tipo e origem e alternância **grade/lista**. Tudo o que a Biblioteca já fazia continua (usar e apagar modelos, baixar mais modelos, baixar/apagar arquivos, abrir o projeto de origem, downloads com progresso e velocidade).
- **Pastas e subpastas** para modelos de IA e para arquivos (escopos separados): **Nova pasta**, renomear, mover, excluir. São **virtuais** (`library.json`): nenhum arquivo muda de lugar ou de nome no disco; os modelos seguem em `models/` e os arquivos dentro dos seus projetos. Excluir uma pasta não apaga nada — o conteúdo sobe para a pasta de cima. Nomes repetidos na mesma pasta são recusados.
- **Arrastar e soltar** para organizar: itens e pastas para uma pasta do corpo, da barra lateral ou do caminho no topo; ou o menu «⋮ → Mover para…».
- **Busca** em todas as pastas: acha pastas e arquivos/modelos pelo nome (também pelo projeto e pelo modelo que gerou) e mostra **onde estão** («em Animais / Pets»).
- **«Baixar mais modelos»** abre o catálogo de antes (recomendados, Unsloth, busca no Hugging Face, velocidade dos downloads, token).
- **No canvas, aba «Biblioteca»** no painel da direita (ao lado de «Projeto»): navega pelas pastas, busca e mostra os arquivos de **todos os projetos** (só imagens, vídeos e sons); **arraste para o fluxo** (ou use o «+») e o OpenFlow copia o arquivo para o projeto e cria um nó **Mídia** com ele, mantendo modelo e prompt de origem. Novas rotas: `GET /api/library/items`, `GET/POST/PUT/DELETE /api/library/folders`, `POST /api/library/move`, `POST /api/projects/<id>/assets/import`.

### Ainda não verificado
- Testei no Chromium (criar/entrar/buscar/mover por menu e por arrastar, excluir pasta, arrastar da aba do canvas) e a API; **não** testei com milhares de arquivos (a lista carrega tudo de uma vez, até 5000 arquivos) nem no celular além do layout responsivo básico.
- Arrastar e soltar depende do navegador: em telas sensíveis ao toque use «Mover para…».
- Arquivos soltos de uma pasta só no seu projeto de origem: apagar o projeto apaga o arquivo, esteja ele em qual pasta estiver. Um modelo apagado fora do OpenFlow deixa só um registro de pasta sem efeito.
- Pastas de modelos não mudam onde o OpenFlow procura o modelo; é só organização.

## [0.26.0] — 2026-11-15

### Novo — várias placas de vídeo (multi-GPU)
- **Todas as placas NVIDIA aparecem** (antes só a primeira era listada) em Configurações → Desempenho → **Placas de vídeo (GPUs)**, onde você marca quais o OpenFlow pode usar (nenhuma marcada = todas).
- **Texto (llama.cpp):** as camadas do modelo são **divididas entre as placas marcadas**, em proporção à memória livre de cada uma (`tensor_split`), o que deixa rodar modelos maiores que a VRAM de uma placa só. Com uma única placa marcada, o modelo inteiro fica nela (`main_gpu`).
- **Imagem, vídeo e som** (sd-cli, a stable-diffusion.cpp em processo à parte e o PyTorch): usam **uma placa por vez — a marcada com mais memória livre na hora** (`CUDA_VISIBLE_DEVICES`/`cuda.set_device`; a numeração segue a do `nvidia-smi`). Uma `CUDA_VISIBLE_DEVICES` definida por você continua mandando.
- Vale a partir do próximo modelo carregado.

### Corrigido
- **`flow libs --sd-cli` saía com código 1 mesmo funcionando** (a função estava definida duas vezes e a segunda devolvia `True`): agora sai com 0 se instalou e 1 se falhou.
- O nome da GPU no Sistema/Desempenho mostrava só a primeira placa quando havia mais de uma.
- Uma variável sobrando no transcrever do OpenRouter (`h` nunca usada) foi removida.

### Removido (legado do ASTA que não se aplica ao OpenFlow)
- **`websearch.py` (766 linhas):** a busca na web do Chat do ASTA — OpenFlow não tem Chat. Só restava, usado pelo nó «Link», a checagem de endereço público; ela foi para um módulo pequeno (`safeurl.py`), com a mesma proteção contra SSRF (localhost, redes privadas e redirecionamentos para elas).
- Funções sem nenhum uso: `lang_name`, `png_of`, `_as_list`, `transcriber` e os atalhos `scan_dir`/`dup_groups` do núcleo; **29 ícones** da interface de recursos que não existem aqui (mundos, avatares, jogos, scriber…).

### Ainda não verificado
- **Não tenho várias placas de vídeo aqui:** a divisão entre placas foi testada com a saída do `nvidia-smi` e a memória simulados; o carregamento real com `tensor_split` em duas GPUs, e a escolha da placa no PyTorch e no sd-cli, **não foram executados**. AMD/Intel (Vulkan) e Apple continuam como antes: sem escolha de placa.
- Um modelo de imagem/vídeo **não** é dividido entre placas (só o texto é); duas gerações ao mesmo tempo também não usam placas diferentes.
- A busca por bugs nos nós foi: rodar cada tipo de nó vazio e em cadeias com o provedor Demo (todos respondem com avisos claros, sem exceções) e uma varredura estática (pyflakes/vulture). Não achei outros bugs nos nós; isso não prova que não há.

## [0.25.0] — 2026-11-15

### Melhorado — downloads mais rápidos e que não se perdem
- **Várias conexões por arquivo:** um modelo de vários GB agora é dividido em faixas (`Range`) baixadas **ao mesmo tempo** (4 por padrão) para um arquivo pré-alocado. Uma única conexão costuma ficar bem abaixo da velocidade da sua internet; com várias, o download tende a usar a banda toda. Arquivos pequenos (< 64 MB) e servidores sem suporte a faixas continuam por uma conexão só, sem erro.
- **Retomada de verdade:** o progresso de cada faixa é guardado num arquivo `.seg` ao lado do `.part`; se você fechar o OpenFlow, cancelar ou a luz cair, baixar de novo **continua de onde parou**. `.part` de versões antigas também continuam.
- **Queda de rede não derruba mais o download:** a conexão que cai é refeita sozinha, a partir do byte em que parou (até 6 tentativas com espera crescente). Se o endereço assinado do CDN vence no meio de um download longo, o OpenFlow pede um novo.
- **Velocidade e tempo restante:** o download mostra «12 MB/s ≈ 4 min» na tela Modelos e na aba Downloads da Biblioteca.
- **Configuração:** Biblioteca → Modelos → «Velocidade dos downloads» → **conexões por download** (1 a 8; padrão 4). Use 1 se o download atrapalhar o resto da sua internet.
- Vale para tudo o que baixa pelo Hugging Face: modelos, VAEs, codificadores de texto, `mmproj`, os recomendados e o botão «Baixar a versão compatível».

### Ainda não verificado
- Testei com um servidor HTTP local que respeita `Range`: arquivo idêntico byte a byte, queda de conexão no meio, cancelamento e retomada, servidor sem `Range`, `.part` antigo. **Não medi a velocidade contra o Hugging Face de verdade** (sem rede aqui): o ganho depende de o servidor limitar cada conexão e da sua internet; se a sua já é saturada por uma conexão, o ganho será pequeno.
- O CDN do Hugging Face recebe a credencial só no servidor original (no CDN a assinatura vai na própria URL); não testei um token de repositório restrito de ponta a ponta.
- Os arquivos de apoio e os modelos divididos em partes continuam baixando um arquivo por vez (cada arquivo, em paralelo por dentro).

## [0.24.0] — 2026-11-15

### Melhorado — FLUX.3 Image Klein
- **Versão «base» com repositório próprio:** o aviso «Baixar a versão compatível» (e o aviso ao abrir um repositório na busca) agora aponta o `leejet/flux-3-image-klein-base-GGUF` para quem usa o FLUX.3 **base**, em vez de empurrá-lo para o repositório do destilado. O botão escolhe sozinho o arquivo equivalente (ex.: `flux3-image-klein-base-Q4_K.gguf`).
- **Receita conferida com o `docs/models/flux3.md` da stable-diffusion.cpp:** destilado = 16 passos, CFG 1,0, `euler`; **base = 20 passos, CFG 3,5, `euler`** (antes o OpenFlow usava 50 passos no base pelo sd-cli, mais do que o necessário — a receita da stable-diffusion.cpp é 20) e o método `euler` agora é passado explicitamente nos dois. Até 10 imagens de referência (`-r`) continuam valendo.
- **Quantizações da Unsloth (`UD-Q4_K_XL`, `Q5_K_XL`…) agora casam com a família K do `leejet`** (Q4_K, Q5_K…) na escolha do arquivo equivalente; antes caíam na «mais próxima por bits», que podia ser a Q4_0.
- A lista de sugestões do provedor Hugging Face local inclui `black-forest-labs/flux-3-image-klein-base`; a dica do catálogo da Unsloth cita o repositório base.

### Ainda não verificado
- Não gerei imagens com o FLUX.3 aqui (sem GPU/rede/sd-cli): a receita vem da documentação da stable-diffusion.cpp e dos nomes de arquivos listados no Hugging Face; os testes cobrem família, repositório compatível, escolha da quantização e argumentos do `sd-cli`.
- O caminho do diffusers (`LocalHF`) continua com 50 passos/guidance 3,5 no base (valor do cartão da Black Forest Labs); não comparei com 20 passos.
- O FLUX.3 Action (robótica) e o expansor de prompt `pup` não são modelos de imagem e não foram incluídos.

## [0.23.0] — 2026-11-15

### Novo — Biblioteca
- **A tela «Modelos» virou «Biblioteca»** (barra lateral, atalho Alt+2; o endereço antigo `#/models` ainda abre a Biblioteca). Ela tem três abas:
  - **Modelos:** tudo o que a tela Modelos já fazia (baixados — agora no topo —, recomendados, lista da Unsloth, busca no Hugging Face, token).
  - **Arquivos gerados:** as imagens, vídeos e sons que os nós geraram, **de todos os projetos**, do mais novo ao mais antigo, com miniatura, modelo usado, tamanho, projeto (link), **busca** (nome, projeto ou modelo), filtros de **tipo** e de **origem** (gerados por modelos / enviados por você / todos), **baixar** e **apagar** (some do projeto também, com confirmação). Novo `GET /api/library/files`.
  - **Downloads:** os downloads **em andamento** (modelos, arquivos de apoio, componentes do LTX-2, sd-cli…) com barra de progresso, bytes e **cancelar**; os **recentes** desta sessão (concluídos, cancelados ou com erro e o motivo); e a lista de **todos os modelos baixados**, dos mais novos aos mais antigos, com tipo, tamanho e quantização. Atualiza sozinha (a cada 1 s enquanto algo baixa, a cada 4 s parada) e para ao sair da aba. Novo `GET /api/library/downloads`.
- Um download que falha com erro agora aparece como **«Falhou»** (antes a tarefa terminava como «concluída»).

### Ainda não verificado
- Testei no Chromium com dados simulados (listas, filtros, apagar, progresso e cancelar) e a API com projetos e tarefas de verdade; **não** acompanhei um download real de vários GB na aba Downloads. A lista de «recentes» vive na memória do servidor: some quando o OpenFlow fecha (os modelos baixados continuam na lista de modelos).
- Os arquivos «gerados» são os que não foram enviados nem vieram de um link; vídeos montados no Editor e arquivos de nós de código contam como gerados.

## [0.22.0] — 2026-11-15

### Novo — MiniMax H3 e LTX-2 / 2.3 / 2.5 (vídeo com áudio)
- **MiniMax H3** (`unsloth/MiniMax-H3-GGUF`, variantes texto + quadros e referências): o OpenFlow agora monta a receita do cartão pelo `sd-cli` — **VAE de vídeo** e **VAE de áudio** (de `Comfy-Org/MiniMax-H3`, baixados junto do modelo), codificador de texto **Qwen3-VL-32B** (Q2_K_M para os denoisers Q2, Q4_K_M para os demais), `--cfg-scale 1.0`, `--backend te=cpu`, flash attention e descarga de parâmetros para a CPU. O `sd-cli` grava o **WebM com áudio estéreo** (24 fps, até 15 s, 960×544 ou 544×960) e o OpenFlow o entrega como está. Novos pontos de apoio: `--audio-vae` e `te_on_cpu` no `sdcli`, `generate_video_file`, e `pick` nos arquivos de apoio (o arquivo depende da quantização do modelo). A biblioteca Python do PyPI nunca o reconhece: vai direto ao `sd-cli`.
- **LTX-2, 2.3 e 2.5** (`unsloth/LTX-2*-GGUF`): rodam pelo **diffusers (≥ 0.43)** — o GGUF vira o transformador (`LTX2VideoTransformer3DModel.from_single_file`) e o resto vem do repositório diffusers da Lightricks. Texto → vídeo ou imagem inicial → vídeo, **MP4 com áudio**, 24 fps, quadros 8k+1, lados múltiplos de 32; «distilled» usa 8 passos e CFG 1, «dev» 30 passos e CFG 3.
- **Os componentes (≈ 25 GB) nunca baixam em silêncio:** faltando, o nó mostra o erro com o botão **«Baixar os componentes do LTX-2»** (`POST /api/media/ltx2-components`).
- Catálogo da Unsloth: MiniMax H3 e LTX-2/2.3/2.5 passam de «Ainda não» a **«Experimental»**. `pip install "openflow[media]"` agora inclui `gguf` e `av`.

### Ainda não verificado / limites
- **Não gerei nada com esses modelos aqui** (sem GPU, sem rede, sem sd-cli): os testes cobrem reconhecimento, escolha dos arquivos de apoio, argumentos do `sd-cli`, o fluxo do botão e mensagens de erro com diffusers/Hugging Face simulados. Por isso aparecem como «Experimental».
- **LTX-2.3:** não achei repositório diffusers próprio; uso o do LTX-2.5 como base (**palpite não confirmado**). `Lightricks/LTX-2.5-Diffusers` é restrito: precisa aceitar a licença e informar o token do Hugging Face.
- O LTX-2 pelo diffusers é pesado (GPU com muita VRAM/RAM) e o formato do GGUF da Unsloth contra a configuração do repositório base pode não bater; nesse caso o nó mostra o erro do diffusers.
- MiniMax H3: ainda sem controle de duração além do limite de 15 s, e a variante de referências roda como texto → vídeo.

## [0.21.0] — 2026-11-15

### Novo — modelos de imagem e vídeo da Unsloth (Hugging Face)
- **Tela Modelos → «Modelos da Unsloth»:** a lista dos modelos GGUF de **imagem** e de **vídeo** da organização `unsloth`, na aba escolhida (Imagem/Vídeo), cada um com o estado real no OpenFlow — **«Funciona»** (o OpenFlow baixa junto o VAE, o codificador de texto e o tokenizer), **«Use outro repositório»** ou **«Ainda não»** (com o motivo). O botão «Ver quantizações» abre o repositório na busca.
- **Funcionam:** Qwen-Image 2.1, 2.1 Turbo, 2512 e original; Qwen-Image-Edit 2511/2509; Z-Image e Z-Image Turbo; FLUX.2 klein 4B/9B (e base) e FLUX.2 dev; FLUX.1 schnell, dev e Kontext dev; Wan2.2 TI2V 5B (vídeo) — e o **novo MOSS-Image (SFT e Base, 5,1B)**.
- **MOSS-Image:** segue a receita do cartão da Unsloth: `sd-cli` (master-975 ou mais novo) com o **VAE e o tokenizer** de `unsloth/MOSS-Image-SFT-FP8` e o **Qwen3.5-9B Q8_0** (≈ 9,5 GB) como codificador de texto, 50 passos e CFG 3. Tudo é baixado junto do modelo; o VAE e o tokenizer são gravados com nomes próprios (`moss-image-vae.safetensors`, `moss-image-tokenizer.json`) para não colidirem com outros arquivos `diffusion_pytorch_model`. A biblioteca Python do PyPI não conhece o MOSS-Image: ele vai direto ao `sd-cli`.
- **FLUX.3 Image Klein** da Unsloth aparece como «Use outro repositório» → `leejet/flux-3-image-klein-GGUF` (v0.18).
- O codificador Qwen3.5-9B e o VAE/tokenizer do MOSS-Image não aparecem como «modelos» na lista de instalados.

### Corrigido
- **FLUX.1 (schnell, dev, Kontext, Krea) usava o CFG padrão 7:** nos FLUX destilados isso estraga a imagem. Agora a receita é CFG 1 e 28 passos (schnell: 4 passos).

### Ainda não verificado / não incluído
- Não baixei nem gerei com nenhum desses modelos aqui (sem rede/GPU/sd-cli); os testes cobrem o reconhecimento, os arquivos de apoio (com os nomes e repositórios conferidos no Hugging Face), a montagem do comando e o catálogo. A receita do FLUX.1 (CFG 1, 28 passos) é a que recomendo pela documentação da stable-diffusion.cpp e não foi testada.
- **Ainda sem receita (aparecem como «Ainda não», com o motivo):** MiniMax H3 (precisa de VAE de vídeo e de áudio, de opções especiais do sd-cli e entrega áudio estéreo, que o OpenFlow ainda não monta), LTX-2, 2.3 e 2.5 (cartões só descrevem o ComfyUI) e ERNIE-Image (não confirmei suporte na stable-diffusion.cpp).

## [0.20.0] — 2026-11-15

### Corrigido
- **O erro do FLUX.3 (e o botão dele) ficava escondido atrás do painel «Gerar fluxo com IA»:** na sua captura a mensagem «A stable-diffusion.cpp não reconhece o formato deste arquivo…» termina exatamente onde o painel cobre o nó — o botão da v0.18 estava embaixo dele e você só via o texto. Agora, depois de uma execução com erro, o canvas **sobe o nó para acima do painel** (se o nó for mais alto que a tela, mostra o fim dele, que é onde ficam o erro e os botões), sem mexer em quem não é coberto.
- **O erro agora se resolve com um clique:** o botão passou de «Abrir … em Modelos» a **«Baixar e usar flux3-image-klein-Q4_K.gguf (3,3 GB)»**. Ele escolhe sozinho o arquivo **equivalente** à quantização que você estava usando no repositório compatível (Q4_K_M → Q4_K; Q5_K_M → Q5_K; Q8_0 → Q8_0), mostra o tamanho antes de baixar, baixa com progresso (e o VAE/codificador que faltarem), **passa a usar o arquivo novo neste nó** (e como padrão de imagem) e avisa «Execute o nó de novo». Se o arquivo já está baixado, o botão vira «Usar …». «Abrir … em Modelos» continua ao lado, para quem quer escolher outra quantização.

### Ainda não verificado
- Não baixei o arquivo do `leejet` de verdade nem gerei com ele (sem rede/modelo/sd-cli aqui); os testes simulam o Hugging Face e conferem a escolha da quantização equivalente, o download, a troca do modelo do nó e o painel. Que o arquivo do `leejet` carregue com o seu `sd-cli` e com o VAE/codificador que você já tem continua sem teste meu.

## [0.19.0] — 2026-11-15

### Corrigido (nó Texto ligado aos nós Imagem e Vídeo)
- **Não dava para ver que texto o nó Imagem/Vídeo ia usar:** com um nó Texto ligado à entrada «Prompt», o campo do nó ficava vazio (com o aviso «Descreva a imagem…») e só o número «1» ao lado da porta mostrava que havia uma ligação. Agora o texto ligado aparece sob o campo («Texto ligado · Texto: “Uma floresta ao amanhecer…”»), **acompanha o que você digita** no nó Texto, e o campo do nó passa a dizer «Opcional: acrescente detalhes ao texto ligado (ele vem primeiro)» — o que reflete o que o motor faz (texto ligado primeiro, depois o do campo). Vale para qualquer nó que entregue texto (Texto IA, Transcrever…): se ele ainda não rodou, o aviso diz «Aguardando o nó … rodar».
- **«Precisa de um prompt: ligue um nó de texto» com o nó de texto já ligado:** quando o nó ligado estava vazio, o erro mandava ligar um nó que já estava ligado. Agora diz qual nó está vazio («O texto ligado ao nó está vazio: Texto (texto vazio)…») e, no Vídeo, lembra que dá para ligar uma imagem inicial.
- **O botão de ação do erro saía do nó:** o rótulo comprido («Abrir leejet/flux-3-image-klein-GGUF em Modelos») ficava numa linha só e passava da borda direita do nó. Agora quebra a linha e cabe dentro do nó.

### Ainda não verificado
- Vi o fluxo no navegador com o provedor Demo (ligar por arrastar, rodar, editar o texto, apagar o nó); não consegui reproduzir com os modelos reais e provedores de nuvem. Se ainda houver algo estranho com o Texto ligado ao Imagem/Vídeo, descreva o que aconteceu (ou mande o erro do nó).

## [0.18.0] — 2026-11-14

### Corrigido
- **«O sd-cli falhou (código 1): … get sd version from file failed: '' … new_sd_ctx_t failed» com o FLUX.3 Klein** (agora com o `sd-cli` compilado e funcionando): o arquivo `flux-3-image-klein-Q4_K_M.gguf` do `unsloth/flux-3-image-klein-GGUF` é a versão para **diffusers/ComfyUI** — os tensores têm os nomes do checkpoint original da Black Forest Labs, que a stable-diffusion.cpp não reconhece (o VAE e o codificador de texto carregavam normalmente; o que falhava era o modelo). O repositório que a stable-diffusion.cpp usa é o **`leejet/flux-3-image-klein-GGUF`** (convertido por ela, ex.: `flux3-image-klein-Q4_K.gguf`).
  - O erro do nó deixou de despejar o log cru do `sd-cli`: agora explica o que aconteceu, diz qual repositório baixar e traz o botão **«Abrir leejet/flux-3-image-klein-GGUF em Modelos»**, que abre a aba Modelos já nesse repositório. O VAE e o codificador de texto que você já tem servem; só o arquivo do modelo muda.
  - Na busca de modelos, abrir um repositório do FLUX.3 que não é o `leejet/…` mostra um aviso (com botão para abrir o correto) antes de você baixar vários GB de um arquivo que não vai carregar.
- Outros modelos que o `sd-cli` recusa com «get sd version from file failed» também ganham uma mensagem clara (sem o log) dizendo que o arquivo provavelmente é para ComfyUI/diffusers e que os GGUF do `leejet` são a referência.

### Ainda não verificado
- Não gerei com o FLUX.3 real (sem o modelo e sem o `sd-cli` aqui). O repositório `leejet/flux-3-image-klein-GGUF` está confirmado no Hugging Face como «convertido com a stable-diffusion.cpp», mas não testei se o arquivo dele carrega com o `sd-cli` e com o VAE/codificador que o OpenFlow baixa. A lista de repositórios de referência tem só o FLUX.3; outras famílias entram quando houver um confirmado.

## [0.17.0] — 2026-11-14

### Corrigido
- **«… faltam: git. Rode flow update … ou instale com: sudo apt install git build-essential…» no nó Imagem (FLUX.3):** o erro se repetia (a mesma frase duas vezes, com «..» no meio) e só mandava você ao terminal. Agora é **uma mensagem só**, que nomeia o que falta e traz o botão **«Instalar o que falta e compilar o sd-cli»**: ele instala git/compilador pelo gerenciador de pacotes do sistema (pede a **senha de administrador**: no terminal onde o OpenFlow está aberto com `sudo` ou, se o OpenFlow foi aberto sem terminal numa sessão gráfica, numa **janela de senha do sistema** com `pkexec`), compila o `sd-cli` (alguns minutos) e o nó volta a funcionar — sem precisar rodar nada no terminal. O botão é o seu consentimento; `OPENFLOW_AUTO_TOOLS=0` só desliga a instalação automática do `flow update`.
- **`flow update`/`flow libs`: as ferramentas de compilação agora vêm ANTES das bibliotecas «local».** Antes, o `llama-cpp-python` (que compila código nativo) era instalado primeiro, falhava sem compilador e, depois que o compilador entrava, não era refeito.
- O instalador de ferramentas escolhe como pedir a senha: `sudo` com terminal, `pkexec` (janela) em sessão gráfica sem terminal, `sudo -n` nos outros casos; os dois comandos do `apt` (`update` e `install`) pedem a senha uma vez só no `pkexec`, e o passo pode ser cancelado.

### Ainda não verificado
- Não abri a janela de senha do `pkexec` nem rodei o `sudo apt-get install` de verdade aqui (sem terminal/sudo/ambiente gráfico): os testes cobrem a escolha do método, os comandos, o botão e a nova tentativa depois de instalar.

## [0.16.0] — 2026-11-14

### Novo
- **`flow update` instala sozinho o que falta para compilar e depois instala/atualiza o `sd-cli`.** Antes, quando faltava git ou compilador («Para compilar o sd-cli aqui falta: git. Instale com: sudo apt install git build-essential»), você tinha que instalar na mão e tentar de novo. Agora o `flow update`:
  1. confere **git** e **compilador C/C++**; se faltam, instala pelo gerenciador de pacotes do sistema (`apt-get` → `git`/`build-essential`; `dnf`/`yum`, `zypper`, `pacman`, `apk` também) usando `sudo` — **pede a sua senha no terminal** (como administrador não usa sudo; sem terminal usa `sudo -n` e só segue se ele não pedir senha). Instala só o que falta;
  2. compila a stable-diffusion-cpp-python do GitHub (v0.13) já com as ferramentas;
  3. **instala o `sd-cli`** se você tem modelos que precisam dele (FLUX.3, Qwen-Image…) e nunca o baixou — pronto, ou compilado aqui quando nenhum executável pronto roda no seu Linux (v0.15) — e o **atualiza** quando há versão nova.
- No macOS e no Windows não existe instalação sem janelas: o `flow update` mostra o comando (`xcode-select --install`…). Sem gerenciador de pacotes reconhecido ou sem `sudo`, mostra o que instalar. **`OPENFLOW_AUTO_TOOLS=0`** desliga a instalação automática; `flow update --core` não mexe nisso.
- O erro do nó «falta git» agora manda rodar `flow update`, que instala o que falta sozinho.

### Mudou
- O critério de «tem compilador» agora é o mesmo no `flow update` e na compilação do `sd-cli` (precisa de um compilador **C++**: `c++`, `g++` ou `clang++`).

### Ainda não verificado
- Não rodei o `sudo apt-get install` de verdade aqui (sem sudo/terminal no ambiente): os testes simulam os gerenciadores de pacotes e conferem os comandos, o uso do sudo (com e sem terminal, como administrador), as falhas e o fluxo completo do `flow update`.

## [0.15.0] — 2026-11-14

### Corrigido
- **«Os executáveis prontos da stable-diffusion.cpp (master-1104-5dcfa79) exigem a glibc 2.43 ou mais nova e este Linux tem 2.39»:** a Release só traz pacotes de Linux compilados no Ubuntu 26.04, que o seu Linux (glibc 2.39) não roda — antes o OpenFlow desistia e mandava você compilar na mão. Agora, quando nenhum executável pronto roda neste Linux, o OpenFlow **compila o `sd-cli` sozinho**: baixa o código-fonte (`git clone` da stable-diffusion.cpp), configura e compila com o cmake (se não há cmake, instala o do pip, com o ninja) e testa o resultado **antes** de trocar o que já existe. Mostra o progresso no nó («Compilando: [ 42%] …») e respeita o cancelamento. Compila para a GPU (CUDA ou Vulkan) só se as ferramentas dela existem (`nvcc`, `glslc`); senão compila para CPU e avisa. Leva alguns minutos, uma vez; as próximas gerações usam o executável compilado.
- Precisa de **git** e de um **compilador C/C++**; se faltarem, o erro nomeia o que falta e o comando para instalar (ex.: `sudo apt install git build-essential`). Desligue a compilação automática com `OPENFLOW_SD_CLI_BUILD=0` (volta a mostrar a mensagem de glibc). Também vale quando os pacotes testados não rodam por outro motivo.

### Ainda não verificado
- Não compilei a stable-diffusion.cpp de verdade aqui (a compilação leva minutos e precisa de rede e de compilador): os testes simulam o git e o cmake e conferem os passos, as flags (CUDA só com `nvcc`), as bibliotecas copiadas, o teste antes de trocar e o apagamento do código-fonte. Se a compilação falhar no seu computador, o erro do nó traz as últimas linhas do compilador; mande-me.

## [0.14.0] — 2026-11-14

### Corrigido
- **«A stable-diffusion.cpp instalada não reconhece o modelo flux-3-image-klein… e fechou (código -11)»:** o FLUX.3 Klein é mais novo que a biblioteca do PyPI (0.4.7) e deve ir direto ao `sd-cli` pronto. Quando o OpenFlow **não conseguia** esse executável (sem rede, glibc antiga demais…), ele caía na biblioteca, que carregava o modelo inteiro, fechava com «código -11» e mostrava uma mensagem que mandava usar o mesmo botão que tinha acabado de falhar — escondendo o motivo real. Agora, sem `sd-cli`, o OpenFlow **nem carrega a biblioteca** e o erro do nó diz **por que o download falhou** (ex.: «exige a glibc 2.43 e este Linux tem 2.39») e o que fazer: `flow update` (compila a stable-diffusion.cpp mais nova do GitHub), apontar `OPENFLOW_SD_CLI` para um sd-cli seu ou usar outro modelo. O botão «Baixar o executável pronto» só é oferecido quando uma nova tentativa pode ajudar (falha de rede, não de glibc).
- **Com a biblioteca do GitHub o FLUX.3 volta a tentar a biblioteca:** o OpenFlow assumia que a biblioteca nunca conhece o FLUX.3. Depois de um `flow update` (que agora compila a do GitHub, v0.13) ou com uma versão acima da 0.4.7, ele tenta primeiro a própria biblioteca, em vez de sempre usar o `sd-cli`.

### Ainda não verificado
- Não reproduzi o «código -11» com o modelo real (sem FLUX.3 e sem a biblioteca aqui); os testes cobrem a escolha do caminho, o motivo mostrado e a detecção da biblioteca do GitHub.

## [0.13.0] — 2026-11-14

### Mudou
- **`flow update` sempre atualiza todas as bibliotecas para as versões mais novas.** Antes, a stable-diffusion.cpp do GitHub só era recompilada se o OpenFlow tivesse avisado de um modelo não reconhecido ou se houvesse GGUF de difusão baixado, o `sd-cli` baixado nunca era atualizado, e uma biblioteca que não compilava fazia o pip desistir do grupo inteiro. Agora:
  - as bibliotecas opcionais (`docs`, `media`, `local`) são atualizadas com `pip --upgrade --upgrade-strategy eager` (as dependências delas também);
  - se o grupo falha, **cada biblioteca é tentada sozinha**: uma que não compila (ex.: `llama-cpp-python`) não impede as outras de atualizarem; o aviso diz qual falhou;
  - a **stable-diffusion-cpp-python do GitHub** é recompilada sempre que houver commit novo (`OPENFLOW_SD_LATEST=always` no `flow update`; `=never` continua desligando), sem recompilar se já está no commit mais novo;
  - o **`sd-cli`** baixado acompanha a Release mais nova (só baixa se a versão mudou);
  - no fim aparece o resumo: «Atualizadas: pacote antes → depois» ou «Todas as bibliotecas já estavam nas versões mais novas».
- `flow update --core` continua atualizando só o OpenFlow e as ferramentas do Python. A abertura automática do app (`flow`) segue no modo «auto», sem compilar a stable-diffusion.cpp à toa.

### Ainda não verificado
- Não rodei o `flow update` com internet e pip de verdade aqui (os testes simulam o pip e o GitHub); a stable-diffusion.cpp do GitHub precisa de git e de um compilador C/C++ para recompilar.

## [0.12.0] — 2026-11-14

### Corrigido
- **Nó Imagem falhava com «O sd-cli falhou … version `GLIBC_2.43' not found»:** o pacote pronto da stable-diffusion.cpp que o OpenFlow baixava foi compilado numa glibc mais nova (Ubuntu 26.04 = 2.43) que a do seu Linux. Agora, no Linux, o OpenFlow **escolhe o pacote que a sua glibc roda** (do Ubuntu mais novo compatível para o mais antigo), **testa o pacote antes de trocar** o que já está instalado (antes ele trocava primeiro e, se o teste falhava, o executável quebrado ficava no lugar e era usado nas gerações seguintes) e, se um pacote não roda, tenta o próximo.
- Um sd-cli que o OpenFlow baixou e que não roda por causa da glibc é **apagado** e, na mesma geração, o pacote compatível é baixado e o pedido é refeito sozinho. Instalações incompletas (sem o arquivo `VERSION`) deixam de ser usadas: a sua, que já estava quebrada, é baixada de novo na próxima geração.
- Quando nenhum pacote serve (glibc mais antiga que a de todos), o erro diz qual glibc eles exigem, qual é a sua e o que fazer (compilar com `flow libs` ou apontar `OPENFLOW_SD_CLI`).

### Ainda não verificado
- Não testei com a Release real da stable-diffusion.cpp (sem acesso ao GitHub aqui): a escolha usa a versão do Ubuntu no nome do pacote (20.04, 22.04, 24.04, 26.04 → glibc 2.31, 2.35, 2.39, 2.43). Se a Release não trouxer um pacote que a sua glibc rode, é preciso compilar.

## [0.11.0] — 2026-11-14

### Corrigido
- **Pesquisar modelos demorava muito:** o OpenFlow perguntava ao Hugging Face **uma consulta de cada vez** (uma busca por «unsloth» em «Outros» eram 12 consultas em fila, cada uma esperando até 20 s se o Hub estivesse lento). Agora as consultas rodam **todas ao mesmo tempo**, cada uma espera no máximo 12 s, e a mesma busca (ou a lista de arquivos de um repositório) vem da memória por 90 s. Erros de rede nunca ficam guardados: a próxima tentativa consulta de novo, e se só parte das consultas falha o resultado das outras aparece.
- **Resultado antigo apagando o novo:** com buscas seguidas, a resposta lenta de uma busca antiga podia chegar depois e substituir a lista da nova (em Modelos e no painel de modelos do Canvas); o mesmo vale para abrir vários repositórios em sequência. Agora só a resposta mais recente vale.
- **Feedback enquanto carrega:** a lista mostra «Buscando “termo” no Hugging Face…» e «Lendo as quantizações de …», e a busca em Modelos também roda sozinha ~0,5 s depois que você para de digitar (3 letras ou mais); Enter pesquisa na hora.

### Ainda não verificado
- Não medi o ganho contra o Hugging Face de verdade (sem acesso a ele aqui); os testes comprovam que as consultas são paralelas, que o cache funciona e que as falhas não ficam guardadas.

## [0.10.0] — 2026-11-14

### Corrigido
- **A edição de imagem quase não mudava nada:** com um pedido solto como «aumente o tamanho do título, mantenha o resto», os modelos locais que editam por referência (FLUX.3/FLUX.2 klein, Kontext, Qwen-Image-Edit…) devolviam praticamente a mesma imagem (no seu exemplo o título cresceu só uns 6%). No modo **Editar**, quando o pedido não é expandido pelo modelo de texto, o OpenFlow agora o envia como instrução de edição clara («Edite a imagem de referência. Aplique exatamente esta mudança: … faça a mudança bem visível e mantenha todo o resto igual»). Ao Gerar, o texto segue como está.
- **Aviso quando a edição não surtiu efeito:** se o resultado fica quase igual à imagem de entrada, o nó mostra um aviso dizendo o que fazer (descrever a mudança com mais detalhe, configurar um modelo de texto para expandir o pedido, ou gerar de novo com outra semente).

### Ainda não verificado
- Não consegui reproduzir a edição com o modelo real (sem o FLUX.3 e sem placa aqui): a moldura do pedido segue o formato que os modelos de edição esperam, mas o ganho só se confirma no seu uso. O FLUX.3 Klein rende melhor com o modelo de texto configurado (Configuração → Modelo), que expande o pedido numa legenda completa.

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
