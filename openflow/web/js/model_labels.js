// Rótulos de qualidade das quantizações GGUF (a chave vem de openflow/hf.py: parse_quant).
// (O nome do arquivo evita «quant.js»: bloqueadores de anúncios/rastreadores barram esse nome, que é de um script de rastreamento conhecido.)
export const QUALITY_LABEL = { very_low: 'Qualidade muito baixa', low: 'Qualidade baixa', good: 'Boa qualidade', very_good: 'Muito boa qualidade', high: 'Quase igual ao original', lossless: 'Praticamente sem perdas', original: 'Original (enorme)' };
// Precisão dos modelos locais do Canvas (fp32/fp16/bf16): explicação mostrada na escolha, antes do download.
export const PREC_HINT = { fp32: 'Maior e mais lento, mas funciona em qualquer computador (inclusive só com CPU).', fp16: 'Metade do tamanho e da memória; ideal com placa de vídeo (GPU). Em CPU pode ser lento ou falhar.', bf16: 'Como o fp16, com a faixa de valores do fp32; pede um processador/GPU recente.' };
// Tipos de modelo GGUF (a chave é a mesma de openflow/hf.py: GGUF_KINDS) e o texto de ajuda de cada um.
export const GGUF_KINDS = [['text', 'Texto'], ['image', 'Imagem'], ['video', 'Vídeo'], ['sound', 'Som e música'], ['voice', 'Voz'], ['other', 'Outros']];
export const GGUF_HINT = {
  text: 'Modelos de linguagem: rodam o OpenFlow (mundos, avatars, jogos) no seu computador.', image: 'Modelos de imagem GGUF (FLUX, Stable Diffusion…) para o OpenFlow, pela stable-diffusion.cpp.',
  video: 'Modelos de vídeo GGUF (Wan…) para o OpenFlow, pela stable-diffusion.cpp. Exigem bastante memória.', sound: 'Modelos de som e música em GGUF. Por enquanto o OpenFlow só baixa e organiza esses arquivos: ainda não há motor embutido para rodá-los.',
  voice: 'Modelos de voz (síntese e reconhecimento) em GGUF. Por enquanto o OpenFlow só baixa e organiza esses arquivos: ainda não há motor embutido para rodá-los.', other: 'Outros GGUF (embeddings, visão…). O OpenFlow só baixa e organiza esses arquivos.',
};
