// Rótulos usados com t(variável) nas telas (sem dependências do navegador: o teste de traduções lê este arquivo no Node).
export const TPL_LABEL = {
  blank: ['Em branco', 'Um projeto vazio: adicione os nós que quiser.'], text_image: ['Texto → Imagem', 'Um prompt de texto que vira uma imagem.'],
  image_video: ['Texto → Imagem → Vídeo', 'Gera uma imagem e anima em um vídeo curto.'], styled: ['Com estilo do projeto', 'Style Prompt + prompt + imagem: o estilo vale para todo o projeto.'],
  scene: ['Cena completa (imagem, voz e Editor)', 'Roteiro → imagem → vídeo + narração + som, tudo montado no Editor.'],
};
export const SORTS = [['updated', 'Mais recentes'], ['name', 'Nome (A–Z)'], ['created', 'Mais antigos primeiro'], ['files', 'Mais arquivos']];
export const ROLE_LABEL = { vae: 'VAE', text_encoder: 'Codificador de texto', mmproj: 'mmproj (visão)' };
export const SETTINGS_TABS = [['providers', 'Texto (IA)'], ['media', 'Imagem, vídeo, som e voz'], ['voice', 'Voz'], ['project', 'Projetos'], ['appearance', 'Aparência'], ['performance', 'Desempenho']];
