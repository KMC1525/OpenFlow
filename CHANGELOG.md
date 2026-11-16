# Changelog

Formato: `## [versão] — data`. Cada versão traz o que mudou para quem usa e, com honestidade, o que **não** foi verificado. [English](CHANGELOG.en.md)

## [0.66.0] — 2026-11-16

### Corrigido — «got multiple values for keyword argument 'local_files_only'» na transcrição
- **O erro da imagem:** ao dublar ou transcrever com o **Whisper local**, o nó falhava com *«Erro inesperado: transformers.models.auto.configuration_auto.AutoConfig.from_pretrained() got multiple values for keyword argument 'local_files_only'»*. O transformers novo já passa `local_files_only` sozinho ao carregar a configuração do modelo, e o OpenFlow o repassava de novo em `model_kwargs`. Agora o carregamento tenta como antes e, se o transformers recusar o argumento repetido, **repete o carregamento com o modo offline pela variável `HF_HUB_OFFLINE`** (valendo só durante o carregamento e devolvida como estava), que funciona em todas as versões. Nada é baixado em silêncio, como antes.
- **Onde vale:** transcrição (Whisper — nós Transcrição, Legendas e Dublagem, e o nó Transcrever), **voz** (Bark, MMS-TTS) e **sons/músicas** (MusicGen): os três carregavam o modelo do mesmo jeito e tinham o mesmo risco com o transformers novo.

### Ainda não verificado
- **Não rodei o Whisper nem o transformers de verdade:** os testes usam um `transformers` de mentira que recusa o argumento repetido exatamente como na mensagem. Que o Whisper carregue, transcreva e dê os tempos com o transformers novo (e se aparece outro erro depois deste) **não foi medido**.
- A mensagem continua aparecendo como «Erro inesperado» quando o carregamento falha por outro motivo (por exemplo, modelo não baixado ou biblioteca ausente têm mensagem própria; outros erros do transformers, não).

## [0.65.0] — 2026-11-16

### Novo — Barra de pesquisa de modelos de som, música e SFX (Hugging Face)
A barra de pesquisa de modelos do Canvas ficou muito melhor para **som**, **voz** e **transcrição**. O filtro `text-to-audio` do Hugging Face mistura de tudo — modelos de **vídeo** que também geram áudio (LTX), assistentes «omni», codecs e vozes de texto → fala ao lado das músicas —, então a busca agora **classifica cada resultado**:
- **Assuntos:** um seletor novo, «Assunto», aparece ao escolher o tipo. **Som:** Música · Efeitos sonoros (SFX) · Separar e melhorar áudio. **Voz:** Voz (texto → fala) · Clonar ou trocar a voz · Voz criada por descrição · **Dublagem** (fala → fala em outro idioma). **Transcrição:** Transcrição e legendas. Cada assunto consulta o Hub pelas **tags dele** (`music`, `sound-effects`, `voice-conversion`, `voice-cloning`, `voice-design`, `speech-to-speech`, `source-separation`…), e não só pelo nome.
- **Sem ruído:** modelos de vídeo, assistentes «omni» e codecs/vocoders saem dos resultados de som; música e efeitos se separam (o Stable Audio, que faz os dois, aparece nos dois); vozes não aparecem mais no meio das músicas.
- **Selo «Roda no OpenFlow» / «Ainda não roda no OpenFlow»** em cada resultado, com o motivo ao passar o mouse e ao abrir o modelo (ex.: «precisa de código próprio do repositório», «usa a biblioteca diffusers», «está em GGUF»). Hoje o OpenFlow roda **MusicGen** (sons e músicas), **Bark, MMS-TTS (VITS), Orpheus e CSM** (voz) e **Whisper** (transcrição); os que rodam vêm **primeiro**, depois os mais baixados. Um modelo que o OpenFlow não roda continua podendo ser aberto, mas o botão **«Usar» fica bloqueado**, com o motivo.
- **Já abre com os mais baixados:** ao escolher som, voz ou transcrição, a lista aparece **sem digitar nada**, do assunto escolhido. Escrever filtra: o nome de uma família (`musicgen`, `whisper large`), de um autor (`stabilityai`) ou **um idioma em português** — «voz em português» filtra pela tag de idioma do Hub; palavras que só dizem o assunto («música», «efeitos sonoros», «dublagem») não atrapalham a busca de texto.
- **Servidor:** `GET /api/media/hub/search?cap=sound|voice|stt&topic=…` (resultados com `topics`, `library` e `compat`) e `GET /api/media/hub/topics`. As outras capacidades (imagem, vídeo, 3D, texto) funcionam como antes.

### Ainda não verificado
- A consulta ao Hub foi **simulada** nos testes (e as tags/os resultados reais do Hugging Face foram conferidos à parte, pela ferramenta do Hub, não pelo cliente HTTP do OpenFlow): a busca de verdade pela rede, com o token e o cache do OpenFlow, não foi exercitada aqui. A classificação por assunto e o selo vêm das **tags, da biblioteca e do nome** que o Hub informa: um repositório com tags incompletas pode cair no assunto errado ou ficar de fora.
- **«Roda no OpenFlow» quer dizer «família com suporte»:** não significa que aquele repositório específico foi baixado e testado. O contrário também vale: um modelo marcado «Ainda não roda» pode funcionar se for compatível com uma dessas famílias sem dizê-lo nas tags.
- Música cantada (ACE-Step, YuE), efeitos (Stable Audio, MOSS-SoundEffect), vozes novas (Kokoro, XTTS, OmniVoice…), conversão de voz e dublagem de fala para fala **aparecem na busca, mas o OpenFlow ainda não roda esses modelos**: o selo diz isso. A busca por idioma («voz em português» + «voz em inglês») pede modelos que declarem os dois.
- Não ordena por relevância nem por qualidade: depois do selo, vale a ordem de downloads do Hub.

## [0.64.0] — 2026-11-16

### Novo — Estilo de voz: «Como é a voz» no nó Voz
No nó **Voz**, logo **abaixo do texto que será falado**, há uma caixa nova: **«Como é a voz (opcional)»** — descreva a voz com palavras livres (*«grave e calma, de narrador»*, *«feminina, jovem e animada»*, *«sussurrando»*). A mesma caixa existe na **Dublagem**, para a voz do próprio nó. Em vozes ligadas à Dublagem (v0.63), cada nó Voz leva a descrição do seu personagem.
- **Como vai ao modelo:** a descrição segue no pedido de estilo da voz (`instructions` da API dos provedores) **antes** do Style Prompt do projeto, se houver. Ela entra no **cache**: mudar a descrição refaz o nó Voz, e, numa Dublagem, a descrição de cada voz ligada refaz a dublagem.
- **Voz de demonstração (offline):** a descrição muda o **tom** (grave, masculina, velha → mais baixo; aguda, feminina, criança → mais alto), o **ritmo** (rápida, animada → mais rápida; lenta, calma → mais lenta) e o **volume** (sussurrando, suave → mais baixo), em português e em inglês, sem se importar com acentos ou maiúsculas. Sem palavras que ela reconheça, a voz sai **idêntica** à da versão anterior (conferido byte a byte).
- **Orpheus (local):** a descrição só vale pelo **gênero** (feminina/masculina): com o campo «Voz» **vazio**, o OpenFlow escolhe uma das vozes do modelo que combina (feminina → `tara`, masculina → `leo`); a voz escrita no campo «Voz» sempre vence.
- **Avisos, em vez de ignorar em silêncio:** um modelo que **não lê** a descrição (hoje, todos os outros modelos de voz locais) diz isso no resultado do nó — «… não lê a descrição da voz: ela foi ignorada (a voz vem do campo «Voz»)». Na Dublagem, o mesmo aviso aparece uma vez por modelo, só para as vozes que têm descrição.

### Ainda não verificado
- **Nenhum modelo de voz de verdade leu a descrição.** Os modelos de voz que o OpenFlow oferece hoje (Bark, MMS-TTS, Orpheus, CSM) **não têm** um campo de descrição de voz: só a voz de demonstração e a escolha de voz do Orpheus por gênero fazem algo com ela; os outros avisam que a ignoraram. Modelos feitos para isso (que aceitam «descreva a voz») e provedores com `instructions` **não estão integrados**; a caixa e o caminho até o provedor já estão prontos para eles.
- Quais vozes do Orpheus são femininas (`tara`, `leah`, `jess`, `mia`, `zoe`) e masculinas (`leo`, `dan`, `zac`) vem da documentação do modelo e **não foi conferido ouvindo o modelo**; a escolha automática não leu o resultado.
- Na demonstração a descrição é só uma lista de palavras (tom, ritmo, volume): ela **não imita sotaque, idade nem emoção**, e «mais alto/gritando» não existe (o volume da demonstração já sai no máximo).
- A **velocidade** do campo «Velocidade» continua sem efeito nos modelos de voz locais (só a voz de demonstração a usa) — isso já era assim e não mudou nesta versão.

## [0.63.0] — 2026-11-16

### Novo — Vozes customizadas na Dublagem: um nó Voz para cada personagem
A **Dublagem** ganhou a entrada **«Vozes»**: ligue nela **um ou vários nós Voz** e cada personagem passa a falar com a sua voz.
- **Cada nó Voz é um perfil de voz:** vale o **modelo**, a **voz**, a **velocidade**, os ajustes extras e o **Style Prompt** ligado a ele. O **título do nó é o nome do personagem** (sem título, vale o nome da voz; e sempre «Voz 1», «Voz 2»… pela ordem das conexões). Cada nó pode usar um **modelo/provedor diferente**. Com vozes ligadas, elas valem **no lugar** da voz do próprio nó Dublagem; sem nenhuma, tudo funciona como antes.
- **Quem fala cada trecho — «Como escolher a voz de cada fala»:**
  - **Pelas marcas** (padrão): no roteiro (texto simples ou SRT/VTT ligados em «Roteiro»), marque a fala com `Maria: fala`, `[Maria] fala` ou `(Maria) fala`. Maiúsculas e acentos não importam («joão» = «João»). A marca vale **até a próxima** (um roteiro com a marca só na primeira frase de cada fala segue com o mesmo personagem); antes da primeira marca, fala o primeiro nó Voz. A marca sai do texto: não é lida em voz alta.
  - **Alternar entre as vozes:** as falas alternam, uma de cada vez (um diálogo de duas pessoas sem marcas).
- **Só nomes de nós Voz ligados viram marca:** «(rindo)», «[Música]» ou «Atenção: o trem chega» continuam sendo texto falado. Um «Nome:» que **não** tem voz ligada mas se **repete** em duas falas ou mais é tratado como um personagem sem voz: a marca sai do texto, a fala continua com a voz anterior e o nó **avisa** quais personagens estão sem voz.
- **Avisos:** vozes ligadas mas nenhuma marca no roteiro (usou só a primeira voz e diz como corrigir); a lista de **vozes usadas** com a contagem de falas de cada uma; um nó ligado em «Vozes» que não é um nó Voz (ignorado, com o nome dele). O resultado do nó mostra «Maria: …», «João: …» com as marcas de tempo.
- **O nó Voz ligado à Dublagem não precisa de texto nem de rodar:** sem texto, ele só define a voz (não é mais erro «precisa de um texto» — essa mensagem continua para um nó Voz solto); a Dublagem **não espera** por ele nem deixa de rodar se ele falhar (se ele tem texto e gera um áudio de exemplo, isso é à parte). O **cache** da Dublagem segue os **ajustes** das vozes (voz, velocidade, modelo, estilo e nome do personagem) e não o áudio de exemplo: trocar a voz de um personagem refaz a dublagem; refazer o áudio de exemplo, não.

### Ainda não verificado
- **Nenhum modelo de voz de verdade foi usado**: os testes usam provedores de mentira que anotam o que foi pedido a cada voz, e o ffmpeg real. Que um modelo de voz de verdade soe como o personagem que você imagina não foi medido. Os modelos de voz que o OpenFlow oferece têm vozes fixas ou poucas (o campo «Voz» do nó é o nome que o modelo entende); **clonar a voz de uma pessoa a partir de uma amostra não está nesta versão**.
- A escolha da voz depende de **marcas no roteiro**: quando a fala vem da transcrição de um vídeo (sem marcas), o OpenFlow **não distingue quem está falando** (não há separação de falantes), então tudo sai com a primeira voz — use «Alternar entre as vozes» num diálogo de duas pessoas ou passe a transcrição por um nó de texto, marque os personagens e ligue em «Roteiro».
- A marca «Nome:» só é reconhecida no **começo** da fala/cue; uma fala dividida pelo OpenFlow (muito longa) continua com o mesmo personagem.

## [0.62.0] — 2026-11-16

### Novo — Dublagem, Legendas e Transcrição: três nós no grupo Som
Três nós novos, logo depois do nó **Voz** na paleta. Eles aceitam um vídeo ou áudio (do nó **Mídia** ou de qualquer nó que gere áudio/vídeo) e se encadeiam entre si.
- **Transcrição (`transcript`):** transcreve a fala do vídeo ou áudio com o modelo de transcrição padrão do projeto (Whisper local) e entrega **texto**: corrido, **com marcas de tempo** (`[1:05] frase`) ou em **parágrafos** (uma pausa longa abre um novo). Idioma da fala automático ou à escolha; botão **Baixar (.txt)** no nó. Áudios longos são lidos em janelas de 30 s sem perder o tempo de cada trecho.
- **Legendas (`sub`):** gera **SRT ou VTT** para qualquer reprodutor, a partir da fala do vídeo/áudio **ou de um texto**: um texto que já é legenda (SRT/VTT) é reformatado (troca de formato, adiantar/atrasar); um texto simples é **distribuído ao longo do arquivo** em proporção ao tamanho de cada frase (com a duração do arquivo ligado, ou a que você escrever no nó). Controles: caracteres por linha (20 a 80), linhas por legenda (1 a 3), duração máxima de cada legenda (as longas são divididas de modo que cada parte caiba nos dois limites), adiantar/atrasar em segundos e **tradução** opcional para outro idioma com o modelo de texto (10 idiomas). Botão **Baixar (.srt / .vtt)** no nó (o arquivo é gerado no navegador).
- **Dublagem (`dub`):** dubla um vídeo ou áudio: **transcreve** a fala (ou usa o **roteiro/legendas ligados** na entrada «Roteiro», que são dublados como estão), **traduz** com o modelo de texto, **fala** cada trecho com o modelo de voz do nó (voz e velocidade ajustáveis), **encaixa** cada fala no tempo do trecho original (acelera até 1,6× o que não cabe; a fala nunca se sobrepõe: um trecho que não coube empurra o seguinte e o nó avisa) e **mistura**: troca o áudio original pela dublagem ou o mantém baixinho por baixo. Com vídeo, a imagem é mantida (copiada sem recodificar quando dá) e o áudio é trocado; com áudio, sai um MP3. O que foi dublado, com as marcas de tempo, fica no resultado do nó. Até 300 trechos por dublagem.
- **Fluxo sem modelo de transcrição:** como a voz Demo funciona offline, um **roteiro (ou legendas SRT) ligado em «Roteiro»** dá uma dublagem completa (balbucio da demonstração) sem Whisper; o nó avisa que é uma voz de demonstração.
- Os três entram no **cache** (mudar o roteiro, o modelo de transcrição ou o de texto gera de novo só o que depende), têm tradução em inglês e avisos claros: modelo de transcrição que não devolve tempos, texto sem tempos distribuído no arquivo, linhas que a tradução não devolveu (ficam no idioma original, com a contagem), falta de modelo de texto (não traduz e diz), voz de demonstração, trechos acelerados ou atrasados.
- **Novo na API dos provedores de mídia:** `transcribe_segments` (a fala com tempo de cada trecho) e `timed_segments`; o Whisper local devolve os tempos, os outros provedores caem num bloco só.

### Ainda não verificado
- **Nenhum modelo de transcrição ou de voz de verdade foi usado.** Os testes usam um provedor de mentira com tempos conhecidos e o balbucio da demonstração; o ffmpeg é real. Que o Whisper local acerte as palavras e os **tempos** (e como se comporta em áudios longos, com música ou várias vozes) **não foi medido**; o `chunk_length_s=30` foi escolhido pela documentação do transformers, sem rodar o modelo.
- A **qualidade da dublagem** depende do modelo de voz e do de texto configurados: a mistura, o encaixe no tempo e a troca do áudio são verificados, a naturalidade da voz, o sotaque e o ritmo da fala traduzida, não. A dublagem não separa as vozes dos efeitos e da música do original: com «Manter baixinho por baixo» eles continuam por baixo; com «Trocar pela dublagem» somem.
- A tradução depende do modelo de texto (e de ele obedecer ao formato numerado); linhas que ele não devolver ficam no idioma original.
- **Legendas não são «gravadas» no vídeo** (isso continua no Editor/Vídeo final); aqui o resultado é o arquivo de legenda. Não há troca de falante (diarização) nem estilos (ASS) — só SRT e VTT.
- Os formatos foram conferidos por leitura de ida e volta no próprio OpenFlow (SRT e VTT), **não** carregados em reprodutores de verdade (VLC, navegadores, YouTube).

## [0.61.0] — 2026-11-16

### Novo — Música e SFX: três nós no grupo Som
Três nós novos, no começo do grupo **Som** da paleta (o nó **Som** antigo continua, para quem já o usa):
- **Música:** gera uma música a partir do estilo que você descreve (gênero, clima, instrumentos) — no campo do nó e/ou num texto ligado em «Descrição». Controles: **letra** (opcional; escreva no nó ou ligue um nó Letra na entrada «Letra»), **instrumental** (sem voz), **duração** (5 a 240 s), **andamento em BPM** (0 = automático), semente e o seletor de modelo (como nos outros nós de mídia). A música gerada guarda a letra usada junto do arquivo.
- **Letra:** escreve a letra de uma música com o **modelo de texto** ativo (Configuração → Provedores) a partir de um tema (campo do nó e/ou texto ligado). Escolhe o **idioma** (português, inglês, espanhol, francês, italiano, alemão), **gênero**, **clima**, **estrutura** (música completa com versos, refrão e ponte; curta; só o refrão; rap), **rimas** (em pares, alternadas, livres) e se as partes vêm marcadas com `[Verse 1]`, `[Chorus]`… (o formato que os modelos de música leem). No modo **Arrumar a minha letra** não usa IA: limpa a sua letra e padroniza as marcas («Refrão:», «(verso 2)» → `[Chorus]`, `[Verse 2]`). Sem modelo de texto configurado (provedor Demo), monta uma letra de **exemplo** com as palavras do tema, e avisa.
- **SFX:** gera efeitos sonoros curtos (passos, porta, chuva, laser…) a partir de uma descrição, com 1 a 4 **variações** de uma vez (cada uma com uma semente diferente), duração de 1 a 30 s.
- Os três entram no **cache** do fluxo (mudar a letra ou o tema gera de novo só o que depende dele), aparecem no **Editor** e na **Biblioteca** como qualquer áudio, e têm tradução em inglês.
- **Avisos honestos na execução:** se o modelo não canta letras, a música sai só com o estilo e o nó **avisa** (a letra não é enviada ao modelo como se fosse estilo); se o modelo devolve menos do que a duração pedida (os modelos locais geram um trecho curto de cada vez), o nó diz quantos segundos saíram; com **Instrumental** ligado, a letra é ignorada e isso também é dito.
- **Demo (offline):** a música da demonstração ganha andamento por BPM e, com letra, um **balbucio rítmico** por cima (não é canto de verdade) — serve para testar o fluxo inteiro Texto → Letra → Música sem nenhum modelo.

### Ainda não verificado
- **Nenhum modelo de música de verdade foi usado.** Os testes usam o provedor Demo e provedores de mentira. O modelo local que o OpenFlow oferece para som (MusicGen) **não canta letras**: com ele, a música sai só com o estilo e o nó avisa. Música cantada de verdade (por exemplo ACE-Step ou YuE) **não está integrada nesta versão**: a porta «Letra», o aviso e a interface já estão prontos para um provedor que cante, mas nenhum foi ligado ainda.
- Os modelos locais geram até 30 s de uma vez; durações maiores do que isso recebem o aviso acima (junte trechos com «Repetir áudio» ou no Editor).
- O MusicGen é um modelo de **música**: usado no SFX ele funciona só de forma aproximada (não há ainda um modelo de efeitos sonoros dedicado).
- A letra escrita pelo modelo de texto depende do modelo configurado (qualidade, idioma, respeito à estrutura): a limpeza e o formato são verificados, a qualidade da letra não.

## [0.60.0] — 2026-11-16

### Corrigido — o `flow` no terminal do Windows e do macOS
Uma auditoria do que o terminal faz de diferente em cada sistema, com estas correções (as marcadas com «testado» têm teste automático com saídas de comando e sockets simulados; não há Windows nem macOS reais nos testes):
- **Windows — `flow update` não rodava o instalador direito:** o `install.ps1` baixado era gravado em UTF-8 **sem BOM** e o Windows PowerShell 5.1 lê isso como ANSI: o «✓» do instalador (bytes E2 9C 93) vira «â œ “», e a aspa «“» fecha o texto no meio — erro de sintaxe antes de começar, fora os acentos trocados. Agora o `flow update` grava o instalador com BOM (testado). O arquivo publicado continua **sem** BOM de propósito, porque `irm … | iex` não aceita BOM no começo.
- **Windows — instalador em Windows 10 antigo / Server 2016:** o `install.ps1` liga o TLS 1.2 (o PowerShell 5.1 nem sempre o liga sozinho e o download do GitHub falhava com «Could not create SSL/TLS secure channel»).
- **Windows — saída do terminal quebrava com ✓ ⚠ → …:** com a saída redirecionada (`flow models list | clip`, `> arquivo`, agendador de tarefas) o Windows usa a página de código do sistema (cp1252/cp850), que não tem esses caracteres, e o `print` morria com `UnicodeEncodeError`. Agora o que a codificação não representa vira «?» (stdout e stderr) em vez de derrubar o comando (testado).
- **Windows — abrir o `flow` duas vezes disputava a mesma porta:** o `SO_REUSEADDR` do Windows deixa dois programas abrirem a mesma porta sem erro, então a segunda instância não passava para a porta seguinte (8788…) e o navegador caía numa ou noutra. Agora o servidor usa `SO_EXCLUSIVEADDRUSE` no Windows (a segunda tentativa dá erro e o `flow` segue para a próxima porta). Linux e macOS ficam como estavam (testado o que dá para testar no Linux: a segunda instância não abre a mesma porta; o ramo do Windows é testado com um socket simulado).
- **macOS — sem o núcleo Rust, a RAM aparecia como 0:** o caminho em Python lia só o `/proc` do Linux. Agora lê o total (`sysctl hw.memsize`), a memória disponível de verdade (`vm_stat`: livre + inativa + especulativa + purgável, na página de 16 KB do Apple Silicon ou 4 KB do Intel), os **núcleos físicos** (`hw.physicalcpu`; antes a conta «metade dos lógicos» errava no Apple Silicon, que não tem hyper-threading) e as **extensões da CPU** (NEON no Apple Silicon; SSE4.2/AVX/AVX2/FMA/AVX-512 pelo `sysctl` no Intel) (testado com saídas simuladas).
- **macOS — a RAM disponível era só uma estimativa:** o núcleo Rust estima 60 % do total no macOS. O OpenFlow agora usa a leitura do `vm_stat` quando o núcleo só estima, então o planejador de modelos e a proteção do computador enxergam a memória real (guardada por 2 s para não chamar o `vm_stat` a toda hora).

### Ainda não verificado
- **Nada disto rodou em um Windows ou macOS de verdade.** Os testes usam saídas de `sysctl`/`vm_stat`, sockets e downloads simulados; o `install.ps1` não foi executado (não há PowerShell aqui, só a análise dos bytes). Que o PowerShell 5.1 aceite o instalador com BOM e que o TLS 1.2 resolva o download em um Windows 10 antigo é raciocínio sobre o comportamento conhecido, não uma execução.
- **O núcleo Rust não foi alterado:** no macOS ele continua estimando 60 % de RAM livre e contando núcleos físicos = lógicos; a correção está do lado do Python, que sobrescreve a estimativa. Corrigir no Rust exige compilar e testar no macOS.
- A auditoria foi uma leitura do código: outros problemas específicos de sistema podem existir (por exemplo, a URL mostrada é `localhost` e o Windows tenta `::1` antes do `127.0.0.1`, o que só atrasa a abertura).

## [0.59.0] — 2026-11-16

### Novo — Multi GPU: a VRAM de várias placas juntas, e VRAM + RAM ao mesmo tempo
Para rodar modelos maiores do que cabe em uma placa só. Tudo em **Configurações → Desempenho → Memória** (novo cartão) e com padrões que já funcionam: **dividir entre as placas** (ligado), **usar a RAM junto** (ligado), folga de VRAM por placa (512 MB) e folga de RAM (2 GB).
- **Modelos de texto (llama.cpp):** com duas ou mais placas NVIDIA escolhidas, o planejador passa a contar a **memória usável de todas juntas** — um modelo de 30 GB que antes deixava parte das camadas na RAM numa placa de 24 GB agora cabe inteiro em duas. As camadas são repartidas em proporção à memória livre de cada placa (`tensor_split`, a de mais memória livre é a principal). O que ainda assim não cabe nas placas vai para a **RAM** (camadas na CPU) — as duas coisas ao mesmo tempo.
- **Imagem e vídeo (diffusers):** quando o modelo não cabe numa placa, ele é carregado com `device_map="balanced"` e `max_memory` (VRAM usável de cada placa e, com «usar a RAM junto», a RAM livre). Se a sua versão do diffusers/accelerate recusar, o OpenFlow repete o carregamento do jeito de antes.
- **Imagem e vídeo (sd-cli):** com sd-cli CUDA instalado pelo OpenFlow e que aceite `--backend`, o **codificador de texto e o VAE vão para outra placa** quando não cabem junto do modelo de difusão na principal (o modelo de difusão não se divide: continua numa placa, com descarga para a RAM se preciso). Em qualquer outro caso (Vulkan, sd-cli sem `--backend`, uma placa só), vale o comportamento de antes.
- **«Usar a RAM junto» desligado:** um modelo de texto que não cabe todo nas placas escolhidas **para com uma mensagem clara** (em vez de ir devagar para a CPU em silêncio).
- **Nova rota** `GET /api/perf/memory` e o cartão mostram as placas, a VRAM e a RAM usáveis e, para cada modelo baixado, **onde ele caberia**: numa placa, dividido entre placas, placas + RAM, só RAM ou não cabe.
- As configurações são validadas (folgas de 0–8192 MB e 0–64 GB; valor inválido volta ao padrão) e entram na exportação/importação.

### Ainda não verificado
- **Nenhuma placa de vídeo real foi usada**: os testes usam placas simuladas, um `torch` e um `sd-cli` de mentira. Que o modelo de fato **rode mais rápido ou caiba** com duas placas reais não foi medido; a velocidade entre placas depende de PCIe/NVLink.
- A sintaxe `--backend te=CUDA1,vae=CUDA1` e a numeração CUDA0/CUDA1 (na ordem de `CUDA_VISIBLE_DEVICES`) foram escritas pela documentação do ggml/stable-diffusion.cpp, **não testadas com um sd-cli real**; o OpenFlow só a usa se `--help` do executável mostra `--backend`.
- O `max_memory` do diffusers com a chave `"cpu"` pode ser recusado por algumas versões (há o plano de reserva); a divisão automática do diffusers vale para modelos carregados de pastas do Hugging Face, não para GGUF.
- **AMD/Intel (Vulkan) não dividem entre placas**: só NVIDIA. O estado `_SPLIT_ACTIVE` do sd-cli é global: duas gerações simultâneas com planos diferentes poderiam se confundir (o OpenFlow roda uma por vez).

## [0.58.0] — 2026-11-16

### Novo — 3D 2: textura, esqueleto e animação de modelos 3D
Três nós novos no grupo **3D** da paleta. Eles se encadeiam (**Modelo 3D → Textura 3D → Esqueleto 3D → Animação 3D**) e cada um **preserva o que o anterior fez**: a textura segue até o fim, o esqueleto também, e o arquivo final é um GLB com tudo. Qualquer GLB ou OBJ enviado pelo nó **Mídia** também pode entrar (antes o nó Mídia não ligava em portas de modelo 3D).
- **Textura 3D:** põe uma textura no modelo, com uma **imagem ligada** (ex.: gerada por um nó Imagem) ou, sem imagem, um **padrão procedural** (xadrez, listras, tijolos, ruído, degradê, madeira) entre duas cores. Projeções: caixa (cada face por um lado), plana, cilíndrica e esférica — nas cilíndricas/esféricas os triângulos que cruzam a emenda são refeitos para a textura não «voltar». Controles: repetições, rotação, tamanho do padrão, matiz, metálico, aspereza e se as cores do modelo ficam junto.
- **Esqueleto 3D:** cria um esqueleto automático e prende a malha a ele (pele com até 4 juntas por vértice, mistura suave): **Humanoide** (21 juntas pelas proporções do modelo, em pé e olhando para a frente), **Coluna** (corrente vertical) e **Corrente** (ao longo do maior eixo: cobras, caudas). A suavidade da mistura é ajustável.
- **Animação 3D:** cria uma animação **em laço** e a grava no GLB (tocável em outros programas): para o modelo todo — girar, pular, flutuar, pulsar, balançar — e, com esqueleto, **ondular** (todas as juntas, em fase deslocada), **andar** e **acenar** (esqueleto humanoide) e **respirar**. Duração e intensidade são ajustáveis; uma animação por modelo (a nova substitui a antiga).
- **Visualizador 3D:** agora mostra a **textura** (a cor de cada face pelo mapa, no centro da face), desenha o **esqueleto** por cima (liga/desliga) e **toca a animação** do arquivo (pele calculada no navegador; botão Pausar/Tocar). Lê também GLBs com esqueleto e animação feitos fora do OpenFlow.
- **Núcleo (`model3d_ops.py`):** lê GLB/OBJ por inteiro (geometria, cores, UV, textura, esqueleto, animação) e grava GLB 2.0 completo; inclui a referência em Python da pose, usada para conferir o visualizador.

### Testado
- `tests/test_3d_nodes_v058.py` (28 testes): leitura e gravação (GLB, OBJ com UV, GLB de fora com transformações), esqueletos (contagem de juntas, pesos válidos, cada membro preso às suas juntas num boneco de caixas, limites), animações (laço fechado, erros amigáveis sem esqueleto, juntas certas de andar/acenar/respirar, GLB válido), texturas (UVs, emendas, padrões, imagem embutida, pele copiada nos vértices duplicados), os nós no motor encadeados com imagem de textura (e as mensagens de erro) e o visualizador **rodando em Node**: ele precisa dar a mesma pose que a referência em Python em todas as animações, em vários instantes.
- Teste de navegador (`model3d_v058_ui.js`): paleta, formulários, a cadeia inteira em um projeto, texto das juntas/animação/textura no visualizador, Pausar/Tocar (quadro parado × animação andando) e o liga/desliga do esqueleto.
- O teste que roda todos os tipos de nó passou a incluir um modelo 3D de entrada.

### Corrigido no caminho
- O nó **Mídia** não podia ser ligado a portas de modelo 3D: agora pode (Python e interface).

### Ainda não verificado
- **Modelos reais:** testei com a malha de demonstração, com um boneco de caixas e com GLBs montados à mão; não com modelos gerados pelo Shap-E, TripoSR ou Hunyuan3D, nem com personagens baixados da internet. O esqueleto é **procedural e aproximado** (proporções da caixa do modelo; o «Humanoide» supõe um corpo em pé, olhando para +z, braços ao lado, e avisa quando o modelo é mais largo que alto): em personagens reais os pesos podem pedir ajuste manual, que o OpenFlow não tem.
- **Outros programas:** o GLB gravado segue a especificação (validado pelas contagens, tipos e referências), mas não o abri no Blender, no Three.js nem em outro visualizador.
- **Limites:** uma só pele; juntas sem rotação de repouso; todas as malhas do arquivo viram uma só ao passar por um dos nós; animações de arquivos de fora entram como trilhas de junta (interpolação cúbica vira linear); o esqueleto automático aceita até 400 mil vértices (junto com os pesos, pode levar minutos em malhas grandes); o visualizador só toca a animação de malhas de até 60 mil vértices.
- **Textura no visualizador** é uma prévia (uma cor por face); o arquivo leva a textura inteira. OBJ não leva textura (só o GLB resultante).
- Não há renderização da animação em vídeo (só no visualizador e no GLB) nem pintura manual de pesos; também não testei no Windows e no macOS.

## [0.57.0] — 2026-11-16

### Corrigido — «falta de memória» ao gerar com o Qwen-Image 2.1 (e outros modelos pelo sd-cli)
O erro da captura (`O sd-cli falhou (código -9): O sistema o encerrou por falta de memória (RAM)…`, num projeto com o Qwen-Image 2.1 Q4_0, uma imagem de referência e uma Style Folder) mostrava um conselho genérico e um resto de barra de progresso. O código -9 é o sistema operacional matando o programa por falta de RAM; no log da captura isso aconteceu **ao carregar os pesos do modelo** (`6/297 – 0.00MB/s`), depois de o codificador de texto Qwen3-VL (≈ 5 GB) e o projetor de visão já estarem na memória.
- **A mensagem agora diz o que aconteceu e o que fazer:** em que etapa a memória acabou (carregando os pesos, ou nos passos da geração), quanto os arquivos carregados somam (ex.: «modelo 4,2 GB, codificador de texto 5,1, projetor de visão 1,2, VAE 0,3»), quanta RAM o computador tem e quanta está livre, e as saídas: tirar a imagem de referência (o projetor de visão de ≈ 1,2 GB só é carregado com ela), usar um codificador de texto menor (Qwen3-VL-8B Q3_K_XL ou Q2_K_XL, informado em «extra» do nó) ou uma quantização menor do modelo, e fechar outros programas. Quando acabou nos pesos, a mensagem avisa que **baixar a resolução não resolve** (antes o conselho era justamente esse).
- **Segunda tentativa automática só quando faz sentido:** se a memória acabar **nos passos** da geração (aí a resolução pesa), o OpenFlow tenta de novo uma vez em 0,7× do tamanho (múltiplos de 16) e avisa no log do nó. Nos pesos ou em etapa desconhecida, não repete (cada tentativa recarrega ≈ 11 GB e levaria minutos à toa).
- **Barra de progresso cortada na mensagem:** linhas como `| ## 6/297 - 0.00MB/s` (sem os `###` suficientes para a v0.56 reconhecer) ainda entravam no texto do erro. Agora qualquer linha de progresso (bytes/s, s/it, it/s) é removida.

### Testado
- `tests/test_qwen21_memory_v057.py` (10 testes): a etapa a partir da unidade da barra (bytes/s → pesos, s/it → passos), a barra cortada, um programa que se mata com SIGKILL como o OOM killer (`OutOfMemory` com a etapa, ainda um `ProviderError`), a mensagem com soma dos arquivos, RAM e dicas (com e sem referências, sem informação de hardware), a segunda tentativa a 704×400 a partir de 1024×576 e a ausência de tentativa nos pesos, em etapa desconhecida e em outros erros. Sem a correção, falham.

### Ainda não verificado
- **Não reproduzi a falta de memória de verdade** (nem tenho a sua máquina): o diagnóstico vem do log da captura; a soma de arquivos e as dicas são estimativas dos tamanhos em disco, não da memória real que o sd-cli pede.
- **Não reduzi o uso de memória em si:** o OpenFlow ainda carrega o codificador de texto (≈ 5 GB), o projetor (≈ 1,2 GB) e o modelo juntos quando há imagem de referência. Se a sua RAM não comporta, a saída é uma das da mensagem (codificador/quantização menores ou sem referência). Posso estudar, numa próxima versão, descarregar o codificador antes de carregar o modelo, se o seu sd-cli permitir.
- A escolha do codificador menor continua manual (campo «extra» do nó); o OpenFlow ainda usa o primeiro arquivo que achar na pasta.
- A «Style Folder» de 7 imagens, nesse caso, não foi a causa: com uma referência ligada, as imagens de estilo não viram referências (só o texto de estilo entra no prompt).

## [0.56.0] — 2026-11-16

### Corrigido — gerar e editar com o Qwen-Image 2.1 (ChatR Labs «Uncensored Omni Quantized»)
Li o cartão do modelo (receita do ChatR Labs) e o caminho de geração/edição do OpenFlow (sd-cli e biblioteca) e testei cada ponto com um sd-cli simulado:
- **Mensagem de erro ilegível:** quando o sd-cli falhava, a tela mostrava os últimos 500 caracteres do log com as barras de progresso (`| | ######## 98/98 - 739MB/s`) misturadas, escondendo a causa (era o caso da captura). Agora a mensagem tira as barras e o `---`/`|` do começo das linhas, mostra as linhas de erro (`[E] …`) primeiro e só depois o contexto final do log.
- **Erro do projetor de visão com explicação:** se, mesmo assim, o sd-cli responder «requires Qwen3-VL vision weights / --llm_vision», o nó agora diz o que falta (o mmproj do Qwen3-VL, ≈ 1,2 GB), onde está o botão «Baixar os arquivos de apoio» e o nome do arquivo na pasta.
- **Limite de imagens de referência pelo modelo errado:** ao gerar pelo sd-cli, o máximo de referências vinha do modelo **padrão das configurações**, não do modelo escolhido no nó. Com um modelo padrão que aceita 1 imagem (ex.: Z-Image) e o Qwen-Image 2.1 (4 imagens) no nó, só a primeira referência era usada, em silêncio. Agora vale o do modelo do nó.
- **Prompt negativo:** o cartão diz que um negativo omitido ou vazio desliga o CFG verdadeiro e manda usar um único espaço. Se o negativo do nó estiver vazio, o OpenFlow agora envia um espaço (só para esta família; outros modelos não mudam), tanto no sd-cli (`-n`) quanto na biblioteca.

### Testado
- `tests/test_qwen21_bugs_v056.py` (8 testes): a mensagem a partir do log da captura (sem barras, erro primeiro, limite de tamanho), a execução real de um programa que falha, o limite de referências com modelo padrão diferente do do nó, o negativo (vazio, só espaços, preenchido, outra família), os argumentos do sd-cli e a mensagem do projetor. Sem a correção, 7 falham.

### Ainda não verificado
- **Não rodei o Qwen-Image 2.1 de verdade** (nem o sd-cli): tudo foi testado até a linha de comando e com respostas simuladas. Não sei se, no sd-cli, o negativo de um espaço muda o resultado em relação ao vazio (o cartão fala do pipeline do diffusers); é a receita do autor e é inofensivo.
- **Sampler:** o cartão recomenda `er_sde` com o agendador `simple` (ComfyUI); o OpenFlow segue com `euler`, porque não confirmei que a sua versão do sd-cli tem `er_sde`. Se tiver, dá para trocar em «extra» (`sample_method`).
- **Resolução:** o cartão recomenda 768×1152 ou 1024×1024; as proporções do nó são as de sempre.
- Imagens de referência extremamente estreitas (80:1) seguem com a proporção limitada a 256 px no lado menor (como na v0.51).

## [0.55.0] — 2026-11-16

### Corrigido — Qwen-Image 2.1 (Uncensored Omni Quantized) ao editar imagens
- **O erro da captura:** ao editar uma imagem com o `qwen-image-2.1-step90000-Q4_0.gguf` (ChatR Labs), o sd-cli falhava com «Qwen Image 2.1 editing requires Qwen3-VL vision weights; provide --llm_vision or a combined encoder … failed to encode prompt». O Qwen-Image 2.1 lê a imagem de referência pelo **projetor de visão (mmproj) do Qwen3-VL-8B**, e o OpenFlow só baixava e passava o VAE e o codificador de texto.
- **Agora:** o OpenFlow conhece esse arquivo (`mmproj-F16.gguf` de `unsloth/Qwen3-VL-8B-Instruct-GGUF`, ≈ 1,2 GB). Ele é **baixado junto com o modelo** (e aparece em «Baixar os arquivos de apoio» para quem já tem o modelo instalado), é guardado como `Qwen3-VL-8B-Instruct-mmproj-F16.gguf` (o do Qwen2.5-VL também se chama `mmproj-F16.gguf`, e os dois não podem se sobrescrever) e é passado ao sd-cli como `--llm_vision` quando você edita.
- **Só é exigido ao editar:** gerar só com texto continua funcionando sem ele (quem já tinha o modelo não perde nada), e nesse caso o OpenFlow nem o carrega (≈ 1,2 GB de memória a menos). Se você editar sem o arquivo, o nó explica o que falta e oferece o botão de baixar, em vez do erro técnico do sd-cli. Quem informou o seu próprio mmproj no campo «extra» do nó não é barrado.

### Testado
- `tests/test_qwen21_vision_v055.py` (10 testes): a família conhece o arquivo e de onde baixá-lo; ele é achado ao lado do modelo e não é confundido com o codificador de texto nem com o mmproj do Qwen2.5-VL; plano de download e estado; instalações antigas sem o arquivo continuam carregando para gerar; editar sem o arquivo dá a mensagem clara (sem chegar ao sd-cli); gerar não o carrega; editar com ele o passa ao carregador; o sd-cli recebe `--llm_vision`. Sem a correção, 8 falham.

### Ainda não verificado
- **Não rodei o modelo de verdade** (nem o sd-cli com o Qwen-Image 2.1): a causa vem da mensagem do próprio sd-cli na captura e a correção foi testada até a linha de comando que ele recebe. Se a edição ainda falhar depois de baixar o mmproj, o novo erro (ou o log do sd-cli) mostra o que sobrou.
- Escolhi o mmproj **F16**; se a sua versão do sd-cli exigir outra precisão ou um codificador «combinado» (a mensagem cita essa opção), diga e eu ajusto.
- Os modelos Qwen-Image 2.1 que já estão baixados ganham o arquivo pelo botão «Baixar os arquivos de apoio»; não baixo nada sozinho.
- A numeração pulou a v0.54: nenhuma versão com esse número foi pedida.

## [0.53.0] — 2026-11-16

### Corrigido — melhorias gerais 6 (sons, vozes e modelos 3D)
Gerei sons (efeitos e música, de 1 a 120 s, 16 descrições, caracteres estranhos), vozes (0,5×–2×, textos vazios de letras, longos e com emoji) e modelos 3D (GLB e OBJ, 11 prompts, 2 sementes) pelo provedor de demonstração, conferi os arquivos de saída, e li o código dos provedores locais e do visualizador 3D. Os defeitos achados:
- **Voz de demonstração muda com números e símbolos:** um texto como «123» ou «50% de $20» saía em silêncio total. Cada dígito agora vira uma sílaba, e símbolos viram um chiado curto. Textos longos eram cortados em silêncio nos 1.200 primeiros caracteres; agora vão até 3.000.
- **Música de 1 s saía com 2 s** no provedor de demonstração; agora respeita a duração.
- **Áudio de modelo local com NaN/infinito** virava ruído estourado (e o pico NaN passava despercebido), e uma saída vazia quebrava com erro técnico. Agora os valores inválidos viram silêncio e a saída vazia dá uma mensagem clara. Pedir mais de 30 s de som a um modelo local (que gera até 30 s) agora avisa no log do nó em vez de encurtar em silêncio.
- **GLB válido recusado no envio:** um arquivo sem índices (comum em exportadores), com várias malhas ou com bytes sobrando no fim era rejeitado como «não é um modelo 3D GLB válido». A validação agora conta todas as malhas, aceita primitivas sem índices e ignora pontos e linhas.
- **OBJ não podia ser enviado:** só GLB entrava. Agora um OBJ de texto com malha (vértices numéricos e faces que apontam para vértices existentes, incluindo quadriláteros e índices negativos) entra como modelo 3D; um OBJ quebrado recebe uma mensagem clara.
- **Visualizador 3D mostrava só a primeira malha, sem a posição dos nós:** um GLB com várias peças (como saem do Blender e do trimesh) aparecia incompleto ou desalinhado. Agora lê todas as malhas da cena com a transformação de cada nó (matriz ou posição/rotação/escala), índices de 8/16/32 bits, tiras e leques de triângulos, cores em byte/short normalizadas (antes estouravam para branco), a cor do material quando não há cor por vértice, e acha o bloco de dados sem supor que vem colado ao JSON. OBJ com índices negativos, CRLF e faces inválidas também é lido.
- **Imagem com transparência no 3D:** o TripoSR e o Hunyuan3D separam o objeto do fundo pela transparência, mas a imagem ligada chegava já achatada sobre branco (desde a v0.51). Agora recebem o recorte com transparência quando ele existe; o Shap-E segue com RGB.

### Testado
- `tests/test_3d_audio_v053.py` (18 testes): validação de GLB/OBJ, envio pela API, o leitor do visualizador (rodando de verdade com Node em GLBs sem índices, em tira/leque, uint16, com duas instâncias/pai com escala, cores normalizadas e cor de material, OBJ negativo/CRLF), voz com números, música de 1 s, áudio com NaN e transparência. Sem a correção, 15 falham.
- A bateria de sons/vozes/3D do provedor de demonstração (cerca de 120 casos de som, 30 de voz e 44 de 3D) terminou sem outros defeitos além dos abaixo.

### Ainda não verificado
- **Nenhum modelo local real foi executado** (MusicGen, Kokoro/Orpheus, Shap-E, TripoSR, Hunyuan3D): as correções neles (alfa, NaN, aviso de 30 s) vêm da leitura do código e de testes das funções, não de uma geração de verdade.
- No provedor de demonstração, o efeito sonoro curto (laser, explosão) tem a duração própria do efeito e não a do nó; é como ele foi desenhado, e não mudei.
- O visualizador desenha uma malha com texturas apenas com a cor do material (não aplica texturas); GLB com animações, esqueletos ou KHR_draco_mesh_compression não é suportado e mostra o erro.
- OBJ dentro de um ZIP/RAR enviado ainda não é reconhecido (só o envio direto).
- Não há edição de modelos 3D no Canvas (o nó gera, o visualizador mostra): não criei uma.

## [0.52.0] — 2026-11-16

### Corrigido — melhorias gerais 5 (imagens e vídeos)
Passei os nós de vídeo, áudio e o Editor por uma bateria com entradas difíceis: clipes de 1 frame e de 0,1 s, vídeos de 16×16, de 333×221 (ímpar), verticais, ultrawide, a 5 e a 59,94 fps, sem áudio, WebM, GIF, rotacionados; cortes, velocidades (0,25×–4×), visuais, mudança de proporção, repetição, troca de áudio, juntar clipes, GIF, vídeo final; e o Editor com clipes além do fim do arquivo, fades maiores que o clipe, escala 4×, canvas de 160×160 a 3840×160, textos com aspas, `%`, `:`, emoji e 300 caracteres, clipes sobrepostos, arquivo que sumiu e 40 clipes. Quase tudo já estava certo; os defeitos achados:
- **Áudio dentro de um arquivo de vídeo era tratado como vídeo.** Uma nota de voz salva como `.mp4`/`.mov`/`.3gp`, uma gravação `.webm`/`.mka` só com som, entrava como «vídeo» e quebrava os nós de vídeo com um erro técnico do ffmpeg; um vídeo Ogg (`.ogv`) entrava como «áudio» e sumia das portas de vídeo. Agora o tipo vem das trilhas de dentro do arquivo (envio direto, arquivos dentro de ZIP/RAR e anexos).
- **«Cortar áudio» além do fim gravava um arquivo vazio** sem avisar (e a saída aparecia como um áudio quebrado). Agora o nó diz «O início do corte passa do fim do áudio», o nó «Tirar silêncios» com um limite alto demais salvava um áudio de 0 s em vez de avisar «O áudio ficou vazio»; e qualquer nó de áudio que terminasse sem som (ex.: acelerar 5× um clipe de 0,05 s) avisa «O resultado ficou sem áudio…» em vez de salvar o vazio.

### Testado
- `tests/test_general_v052.py` (8 testes): tipo por trilhas (áudio em .mp4/.mov/.3gp/.webm/.mka, vídeo com e sem som, `.ogv`), envio pela API, corte além do fim, efeito que esvazia o áudio e corte válido. Sem a correção, 7 falham.
- A bateria completa de vídeo (13 vídeos × centenas de parâmetros) e a do Editor (cerca de 170 casos) terminaram sem outros defeitos (só erros esperados e mensagens claras, como «ligue um vídeo» para um GIF numa porta de vídeo).

### Ainda não verificado
- Arquivos já enviados antes da correção continuam classificados como estavam (basta enviá-los de novo).
- Formatos que o OpenFlow não reconhece (`.mpg`, `.flv`, `.ts`) seguem recusados no envio com a mensagem de formato inválido; não os adicionei porque o navegador não os toca na prévia.
- Um arquivo de vídeo sem trilha de vídeo que passe como vídeo por outro caminho (ex.: gerado por um provedor) ainda daria o erro técnico do ffmpeg.
- Não testei vídeos grandes (minutos/GB) nem codecs raros; modelos locais de vídeo reais não rodam neste ambiente.

## [0.51.0] — 2026-11-16

### Corrigido — bugs ao editar imagens nos nós do Canvas
Procurei os erros rodando os nós de edição de imagem (Redimensionar, Filtros e cor, Texto na imagem, Recortar, Marca d'água, Colagem, Miniatura, Imagem final e o modo «Editar» do nó Imagem) com entradas difíceis: imagens de 1 px, muito estreitas, com transparência, em tons de cinza, paleta, 16 bits, JPEG, WebP, GIF e BMP. Foram 14 falhas e 3 defeitos silenciosos:
- **Redimensionar com largura ou altura em 0 (automático)** falhava em imagens muito estreitas (ex.: 50×4000 com altura 50 dava largura 0 e o ffmpeg desistia). Agora a outra medida acompanha a proporção, nunca abaixo de 1 px. Como bônus, o «automático» não arredonda mais para número par.
- **Recortar** podia pedir 0 px (recorte manual de 1% numa imagem fina, proporção 21:9 numa imagem de 1 px) e falhava. Agora o recorte tem sempre ao menos 1 px e, se passar da borda da imagem, encosta na borda e avisa («O recorte passava da borda»).
- **Filtros (desfocar, nitidez, VHS) numa imagem de 1 px** faziam o ffmpeg corromper a memória e fechar. Agora o efeito é pulado com um aviso.
- **Foto de celular (orientação EXIF) saía deitada:** no modo «Editar» do nó Imagem a referência era lida sem a orientação, e os nós de imagem dependiam da versão do ffmpeg (o novo gira sozinho, o antigo não). Agora a foto é girada na entrada e o resultado é o mesmo em qualquer ffmpeg.
- **Transparência virava preto (ou a cor escondida):** a referência de edição com fundo transparente era convertida direto para RGB. Agora é composta sobre branco.
- **PNG de 16 bits saía todo branco** como referência de edição. Agora mantém o brilho.
- A comparação «o resultado ficou quase igual à entrada» e o sd-cli (modelos GGUF) usam a mesma leitura corrigida.

### Testado
- `tests/test_edit_images_v051.py` (12 testes): leitura de transparência, EXIF, 16 bits e formatos; tamanhos automáticos, modos de Redimensionar, recortes de 0 px e na borda, desfoque em 1 px, foto com EXIF e BMP. Com o código antigo, 10 deles falham.
- A bateria de varredura (14 imagens × centenas de parâmetros, mais colagem, miniatura, imagem final e o modo Editar com o provedor de demonstração) terminou com 0 problemas.

### Ainda não verificado
- **Modelos locais reais** (FLUX, Qwen-Image-Edit etc.) não foram executados aqui: o modo «Editar» foi testado com o provedor de demonstração e a leitura das referências em si, não com um modelo de verdade.
- O tamanho de saída do modo «Editar» num modelo local segue com mínimo de 256 px por lado: uma imagem extremamente estreita (ex.: 80:1) sai com a proporção limitada.
- Transparência: a referência é composta sobre **branco**; nenhum modelo recebe o canal de transparência. Marca d'água e Texto na imagem continuam preservando o alfa da imagem de entrada.
- Não revisei a interface do Canvas (arrastar, zoom, visualizador) à procura de bugs de edição: a varredura foi no motor dos nós.

## [0.50.0] — 2026-11-16

### Design e personalização
- **Fundo cinza-grafite no lugar do preto puro:** o tema escuro agora usa um cinza suave (`#1e1f22`, painéis um pouco mais claros, texto em branco-gelo em vez de branco puro, sombras mais leves) que cansa menos a vista em sessões longas. Vale para a interface toda, a área dos nós do Canvas, a linha do tempo e o `theme-color` do navegador/app instalado. Só o palco do vídeo segue preto, porque é a tela de mídia. O tema claro não mudou.
- **Tamanho da interface de 50% a 200%** (de 5 em 5): um controle deslizante em Configurações → Aparência, com atalhos 50 · 75 · 90 · 100 · 110 · 125 · 150 · 175 · 200%. Antes eram só cinco valores (90–150%). O tamanho é aplicado ao soltar o controle (a interface inteira muda junto com ele). Valores antigos continuam valendo.
- **Mais fontes:** Sistema, Inter, Humanista, Arredondada, Verdana, Alta legibilidade (Atkinson Hyperlegible/Lexend/OpenDyslexic), Livro, Serifada e Monoespaçada — cada cartão mostra a própria fonte —, e **«Outra fonte»**, onde você digita o nome de qualquer fonte instalada no computador. O nome é limpo (só letras, números, espaço, ponto e hífen) antes de ir para o CSS.

### Testado
- `tests/test_design_v050.py` (8 testes): intervalo e arredondamento da escala, valores inválidos, nome de fonte sem injeção de CSS, todas as fontes com CSS e cartão, cor do fundo (nem preto, nem claro demais), ida e volta pela API. Teste de navegador: fundo, 50%/200%/100% aplicados e salvos, cartões de fonte, «Outra fonte».

### Ainda não verificado
- **Só medi o fundo pelos valores e por testes**, não por uma pessoa olhando por horas: o tom exato (`#1e1f22`) é uma escolha minha; se ainda incomodar, diga se prefere mais claro ou mais quente.
- As fontes usam o que existe no computador; **nada é baixado**. Inter, Atkinson, Lexend e OpenDyslexic só aparecem se estiverem instaladas (senão cai numa fonte parecida do sistema). Não vi todas renderizadas em Windows, macOS e Linux.
- Em 50% e 200% a tela principal e as Configurações seguem usáveis no teste, mas não percorri todas as telas e modais nesses extremos; o navegador sem suporte a `zoom` (Firefox antigo) ignora o tamanho.

## [0.49.0] — 2026-11-16

### Novo — Proteção do computador
- **O OpenFlow para tudo se o seu computador sobrecarregar.** Um vigia (`openflow/guard.py`) mede, a cada segundo, o uso do **processador (CPU)**, da **memória (RAM)** e da **placa de vídeo (GPU)**. Se qualquer um deles ficar em **90% ou mais por 5 segundos** enquanto o OpenFlow está trabalhando, ele **para tudo**: cancela as tarefas em andamento, encerra os processos que ele iniciou (ffmpeg, sd-cli, llama…) e descarrega os modelos de texto e de mídia da memória.
- **Para você não ser pego de surpresa:** uma faixa vermelha no topo diz o que foi parado e por quê («memória RAM em 94%…»), e cada tarefa cancelada registra a causa no próprio log.
- **Configurações → Desempenho → «Proteção do computador»:** liga/desliga, limite (50–99%, padrão 90), segundos (1–60, padrão 5), o que vigiar (CPU, RAM, GPU), as medidas ao vivo e o botão **«Parar tudo agora»** (a mesma parada, sob demanda). API: `GET /api/guard` e `POST /api/guard/stop`.
- **Regras para não atrapalhar à toa:** um pico curto não dispara (só carga sustentada pelos segundos configurados); só age quando o **OpenFlow está trabalhando** (se outro programa sobrecarrega a máquina, não há o que parar aqui); depois de uma parada há uma pausa de 20 s antes de poder disparar de novo.

### Testado
- `tests/test_guard_v049.py` (15 testes): a máquina de decisão com amostrador e relógio simulados (pico curto, limite exato, desligado, ocioso, métrica desmarcada), a parada completa (tarefa cancelada, processo filho e neto encerrados, modelos descarregados, pausa), a leitura de `/proc/stat` e da memória, e as rotas da API. Mais um teste de navegador (cartão, salvamento, limite mínimo e faixa de aviso).
- Nos testes o vigia fica desligado (`OPENFLOW_NO_GUARD=1`) para não disparar por acaso numa máquina ocupada.

### Ainda não verificado
- **Não testei numa máquina realmente sobrecarregada**: a decisão foi testada com medidas simuladas e a leitura de CPU/RAM no Linux deste ambiente; não vi um disparo real nem em Windows ou macOS (lá a CPU é uma aproximação pela carga do sistema).
- **Gerar na CPU costuma usar ~100% dela e vai disparar a proteção** com a configuração padrão. Se isso atrapalha, desmarque «CPU» ou suba o limite.
- **GPU:** só a placa NVIDIA mede uso (via `nvidia-smi`) e a memória de vídeo dedicada; AMD/Intel/Apple não entram, e sem medida a GPU não dispara.
- Um modelo rodando **dentro** do processo do OpenFlow (llama.cpp embutido) só é cancelado entre uma etapa e outra e descarregado depois; ele não é interrompido no meio de uma conta.
- O instalador e o `flow setup` ainda oferecem os modelos pré-instalados (veja o 0.48).

## [0.48.0] — 2026-11-16

### Removido — «Prontos para instalar» na barra de pesquisa do Canvas
- Saiu a seção **«Prontos para instalar»** (com o Z-Image e o modelo de texto, e o botão Instalar) que aparecia ao clicar na barra de pesquisa de modelos: quem escolhe, pesquisa e baixa o modelo é o usuário. A barra não consulta mais `/api/preinstalled`.
- **Fica** o **«Catálogo recomendado (GGUF)»** (Unsloth e ChatR Labs): ele só **lista** modelos conhecidos e abre a pesquisa de cada um com «Ver quantizações»; nada é instalado sem você escolher a quantização e apertar Baixar.

### Ainda não verificado
- Não mexi no que existe fora da barra: o instalador (`install.sh`/`install.ps1`) e o `flow setup` ainda **perguntam** se você quer os modelos pré-instalados (a variável `OPENFLOW_MODELS=none` desliga), e `flow models install` e a rota `/api/preinstalled` continuam existindo.

## [0.47.0] — 2026-11-16

### Corrigido — varredura geral 4
- **Nó novo some ao salvar no limite:** o projeto aceita até 200 nós, mas o editor deixava criar o 201º, que o servidor descartava ao salvar (ele sumia ao reabrir). Agora o editor avisa «Limite de 200 nós por projeto…» e não cria; apagar um nó libera o espaço (o limite vem do servidor).
- **Configurações com tipo errado:** o modelo ou a janela de contexto de um provedor, e os nomes de modelo de mídia, com tipo errado (vindos da importação de configurações, da API ou de edição à mão) eram gravados como estavam e quebravam a carga do modelo; agora só valem texto (modelo) e inteiro ≥ 0 (contexto, até 4.194.304), o resto é descartado.
- **GLB inválido:** um arquivo que só começava com «glTF» entrava no projeto como modelo 3D; agora o cabeçalho e o JSON são conferidos e o envio recusa com «Esse arquivo não é um modelo 3D GLB válido».
- **Vazamento ao abrir e fechar o Canvas:** a barra de pesquisa de modelos e o indicador de downloads deixavam ouvintes globais (`flow:hub`, `flow:downloads`, `pointerdown`, `Escape`) e um temporizador de consulta para trás a cada visita; agora se soltam ao sair do Canvas, e fora dele não há consulta de downloads.

### Testado
- Os 54 tipos de nó rodam com entradas válidas (`tests/test_all_nodes_v038.py` e a varredura); a matriz de entradas estranhas (imagens, vídeos e áudios) segue sem falhas inesperadas; fuzz de 1.600 requisições na API, de parâmetros de nós e de textos estranhos nos nós de ficha e quadrinhos; corpos gigantes e JSON aninhado são recusados; 400 nós em cadeia rodam em ~4 s e o segundo «Executar tudo» usa o cache em ~10 ms.

### Ainda não verificado
- O limite de 600 ligações por projeto também descarta o excedente em silêncio ao salvar; o editor ainda não avisa (é difícil chegar lá com 200 nós).
- Modelos locais reais e o nó «Transcrever» (falta a biblioteca do Whisper aqui) seguem sem execução neste ambiente.

## [0.46.0] — 2026-11-16

### Mudou — README menor e mais objetivo
- Os dois READMEs (português e inglês) foram reescritos: de 196 para 98 linhas cada. Ficaram instalar, o comando `flow`, os nós, os modelos (pesquisa e download só pela barra do Canvas, com o indicador de downloads), as configurações, os dados, o desenvolvimento, os limites e a licença.
- Saíram as partes desatualizadas: «modelos de empresas (API)», «30 nós utilitários», o catálogo «Baixar mais modelos» da Biblioteca, «provedores de nuvem com chaves reais», o planejador de agentes e a seção longa de pastas do Style Folder e de arquivos de apoio (agora uma linha cada).
- A tabela de variáveis do instalador virou uma linha; a de comandos ficou só com os principais.

### Ainda não verificado
- A lista de nós do README é um resumo: os nomes na interface podem diferir um pouco.
- Nada de código mudou além da versão (0.46.0).

## [0.45.0] — 2026-11-16

### Novo — computadores de 16 GB de RAM (DDR4 e DDR5), com o núcleo Rust
- **Planejador de memória por classe de RAM** (`flow_plan_ram`, interface 7 do núcleo Rust; espelho em Python com as mesmas contas, conferidas nos testes): desconta o que o sistema, o navegador e o OpenFlow usam (≈ 22% da RAM, entre 2,5 e 6 GB) e decide, sobre o que sobra:
  - **Um modelo de cada vez na RAM:** se o modelo de texto e o de imagem/vídeo/som não cabem juntos, o que está carregado **sai antes** de carregar o outro (antes os dois ficavam na RAM e o computador começava a usar o disco).
  - **Contexto** que cabe na RAM que sobra e **cache de atenção em 8 bits** quando o modelo ocupa mais de 60% dela.
  - **Threads e lotes pela velocidade da memória** (DDR4/DDR5 × MT/s × canais, lidos do SMBIOS quando há permissão): mais threads do que a memória consegue alimentar só atrapalham a geração na CPU; DDR5 e dual channel aguentam lotes maiores; RAM apertada usa lotes menores (os buffers de cálculo também ocupam RAM).
  - **`mlock` só quando sobra bastante**, pré-carga só quando o modelo cabe folgado e cache de prompt menor quando aperta.
  - **Imagem, vídeo e som:** fatias de atenção e de VAE ligadas quando o modelo ocupa boa parte da RAM; descarga de ociosos mais cedo (2 a 5 min) nessa classe.
- Só atua nas classes «pequena» (< 12 GB) e «16 GB» (12 a 24 GB); em 32 GB ou mais nada muda. Qualquer falha do planejador volta ao comportamento de antes, e um contexto definido à mão nunca é encolhido.
- **Configurações → Desempenho → Processador:** nova linha «Memória para os modelos» (o que sobra depois do sistema, GB/s e threads úteis) com a classe da sua RAM.
- O núcleo passou à **interface 7**: bibliotecas da interface 6 (v0.29–v0.44) ainda carregam e o OpenFlow usa o espelho em Python do planejador até a biblioteca nova ser baixada (`flow native setup`).

### Ainda não verificado
- **Não medi ganho de velocidade real em uma máquina de 16 GB** (este ambiente não é uma): os testes provam as contas (Rust = Python em 400 casos aleatórios), a integração e os limites; os ganhos esperados vêm de evitar uso de disco quando texto e mídia competem pela RAM e de não usar mais threads do que a memória alimenta.
- DDR4/DDR5, MT/s e canais vêm do SMBIOS (Windows e `dmidecode` no Linux, com permissão); sem isso o planejador assume DDR4-2400 em dois canais, que é conservador.
- Os limites (22% de reserva, 60% de «apertado», ~12 GB/s por núcleo) são heurísticas; ajuste-os se medir diferente.

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
