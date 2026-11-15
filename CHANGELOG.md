# Changelog

Formato: `## [versão] — data`. Cada versão traz o que mudou para quem usa e, com honestidade, o que **não** foi verificado. [English](CHANGELOG.en.md)

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
