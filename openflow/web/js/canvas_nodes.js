// Canvas: tipos de nó na interface (paleta, controles de cada nó e área de resultado) e regras de compatibilidade das portas.
import { t } from './i18n.js';
import { api, events } from './api.js';
import { withMentions } from './canvas_mention.js';
import { checkbox, confirmDialog, h, icon, popover, seg, select, toast } from './ui.js';

export const compatible = (out, accepts) => accepts.includes(out)
  || (out === 'media' && accepts.some((a) => ['image', 'video', 'audio', 'media'].includes(a)))
  || (['image', 'video', 'audio'].includes(out) && accepts.includes('media'));

export const GROUPS = [   // espelha schema.PALETTE
  ['Texto', ['text', 'llm', 'transcribe', 'text_template', 'text_join', 'text_edit', 'text_pick', 'text_refine']],
  ['Imagem', ['image', 'img_resize', 'img_filter', 'img_text', 'img_collage', 'img_frame']],
  ['Vídeo', ['video', 'vid_trim', 'vid_join', 'vid_speed', 'vid_look', 'vid_slideshow']],
  ['Som', ['sound', 'voice', 'aud_trim', 'aud_mix', 'aud_fx', 'aud_from_video', 'aud_loop']],
  ['Input', ['upload', 'style_prompt', 'style_folder', 'in_color', 'in_silence', 'in_url', 'in_random', 'in_vars']],
  ['Output', ['editor', 'out_export', 'out_gif', 'out_audio', 'out_image', 'out_gallery']],
];
export const TYPE_HELP = {
  text: 'Um texto que você escreve (prompt, roteiro, fala).', llm: 'Reescreve ou cria texto com o modelo de IA configurado.',
  upload: 'Seus arquivos de imagem, vídeo ou áudio.', image: 'Gera ou edita imagens.', video: 'Gera vídeos (de texto ou a partir de uma imagem).',
  sound: 'Gera efeitos sonoros ou música.', voice: 'Transforma texto em fala.', transcribe: 'Transforma áudio ou vídeo em texto.',
  style_prompt: 'Um prompt de sistema de estilo que vale para o projeto todo.', style_folder: 'Imagens, vídeos e áudios de referência de estilo para o projeto todo, organizados em pastas e subpastas.',
  editor: 'Editor de vídeo: monta tudo numa linha do tempo e exporta um MP4.',
  text_template: 'Monta um texto a partir de um modelo, usando {1}, {2}… para os textos ligados.', text_join: 'Junta vários textos em um só (com separador, numeração, prefixo e sufixo).',
  text_edit: 'Maiúsculas, minúsculas, limpar espaços, ordenar, numerar linhas, trocar palavras…', text_pick: 'Escolhe uma linha, frase, parágrafo ou palavra de um texto (ou sorteia).',
  text_refine: 'Com o modelo de texto: melhora o prompt, traduz, resume, expande, corrige, divide em cenas ou em legendas.',
  img_resize: 'Muda o tamanho (encaixar, preencher, esticar), gira e espelha uma imagem — ou o quadro de um vídeo.', img_filter: 'Filtros de cor (P&B, sépia, vívido, VHS…) e ajustes de brilho, contraste e saturação.',
  img_text: 'Escreve um texto (ou o texto de outro nó) sobre a imagem.', img_collage: 'Junta várias imagens numa colagem em grade.', img_frame: 'Tira um ou mais quadros de um vídeo como imagens.',
  vid_trim: 'Corta um trecho do vídeo (início e duração).', vid_join: 'Junta vídeos e imagens em sequência, com transições suaves.', vid_speed: 'Acelera, desacelera ou toca o vídeo ao contrário.',
  vid_look: 'Dá um visual ao vídeo (cinema, VHS, P&B…) com fade de entrada e saída.', vid_slideshow: 'Transforma imagens em um vídeo com zoom suave e música.',
  aud_trim: 'Corta um trecho do áudio (ou do som de um vídeo), com fades.', aud_mix: 'Mistura vários áudios (juntos) ou toca um depois do outro.', aud_fx: 'Efeitos: volume, velocidade, reverso, eco, telefone, graves, normalizar.',
  aud_from_video: 'Extrai o áudio de um vídeo.', aud_loop: 'Repete um áudio até chegar a uma duração, com fade no final.',
  in_color: 'Gera uma imagem de cor lisa ou degradê, no tamanho que você quiser.', in_silence: 'Gera um trecho de silêncio (para espaçar áudios).', in_url: 'Baixa uma imagem, um vídeo ou um áudio de um link público.',
  in_random: 'Sorteia linhas de uma lista (variações de prompt, ideias).', in_vars: 'Texto com a data, a hora e o nome do projeto.',
  out_export: 'Monta o vídeo final: vídeo (ou imagem) + áudios + legendas, na qualidade escolhida.', out_gif: 'Transforma um vídeo em GIF animado.', out_audio: 'Junta e exporta o áudio final (MP3, WAV ou M4A), normalizado.',
  out_image: 'Exporta a imagem final (PNG, JPG ou WebP) com qualidade e largura máxima.', out_gallery: 'Reúne imagens, vídeos, áudios e textos de vários nós num lugar só para ver e baixar.',
};
export const OUT_COLOR = { text: 'var(--c-text)', image: 'var(--c-image)', video: 'var(--c-video)', audio: 'var(--c-audio)', style: 'var(--c-style)', media: 'var(--c-media)' };
export const LABEL = {
  text: 'Texto', llm: 'Texto IA', upload: 'Mídia', image: 'Imagem', video: 'Vídeo', sound: 'Som', voice: 'Voz', transcribe: 'Transcrever',
  style_prompt: 'Style Prompt', style_folder: 'Style Folder', editor: 'Editor',
  text_template: 'Modelo de texto', text_join: 'Juntar textos', text_edit: 'Editar texto', text_pick: 'Escolher trecho', text_refine: 'Refinar com IA',
  img_resize: 'Redimensionar', img_filter: 'Filtros e cor', img_text: 'Texto na imagem', img_collage: 'Colagem', img_frame: 'Quadro do vídeo',
  vid_trim: 'Cortar vídeo', vid_join: 'Juntar clipes', vid_speed: 'Velocidade', vid_look: 'Visual do vídeo', vid_slideshow: 'Imagens em vídeo',
  aud_trim: 'Cortar áudio', aud_mix: 'Misturar áudios', aud_fx: 'Efeitos de áudio', aud_from_video: 'Áudio do vídeo', aud_loop: 'Repetir áudio',
  in_color: 'Cor e degradê', in_silence: 'Silêncio', in_url: 'Link (URL)', in_random: 'Sorteio de texto', in_vars: 'Data e projeto',
  out_export: 'Vídeo final', out_gif: 'GIF animado', out_audio: 'Áudio final', out_image: 'Imagem final', out_gallery: 'Galeria',
};
const CAP = { image: 'image', video: 'video', sound: 'sound', voice: 'voice', transcribe: 'stt' };
const PORT_LABEL = { prompt: 'Prompt', refs: 'Referências', style: 'Estilo', image: 'Imagem inicial', text: 'Fala', audio: 'Áudio/vídeo', clips: 'Clipes', vars: 'Variáveis', texts: 'Textos', images: 'Imagens', video: 'Vídeo', audios: 'Áudios', items: 'Itens', captions: 'Legendas' };
const NEW_PORT = { img_resize: { image: 'Imagem' }, img_filter: { image: 'Imagem' }, img_text: { image: 'Imagem', text: 'Texto' }, text_edit: { text: 'Texto' }, text_pick: { text: 'Texto' }, text_refine: { text: 'Texto' }, vid_slideshow: { audio: 'Áudio' }, aud_trim: { audio: 'Áudio' }, aud_fx: { audio: 'Áudio' }, aud_loop: { audio: 'Áudio' }, out_export: { audio: 'Áudio', video: 'Vídeo' }, out_audio: { audio: 'Áudio' }, out_image: { image: 'Imagem' } };
export const portLabel = (nodeType, p) => (nodeType === 'llm' && p.id === 'prompt' ? t('Entrada') : t((NEW_PORT[nodeType] && NEW_PORT[nodeType][p.id]) || PORT_LABEL[p.id] || p.label));

// ---------------------------------------------------------------------------------------------------- controles
const cut = (e) => e.stopPropagation();
function ta(c, n, key, ph, rows, mention) {
  const el = h('textarea', { placeholder: ph, rows: rows || 3, class: 'nodrag' });
  el.value = n.params[key] || '';
  const grow = () => { if (el.scrollHeight > el.clientHeight + 2) el.style.height = Math.min(el.scrollHeight + 2, 320) + 'px'; };   // o texto cresce o campo (até um limite) em vez de ficar escondido; o que a pessoa puxou à mão não é encolhido
  el.addEventListener('input', () => { c.change(n, key, el.value); grow(); });
  el.addEventListener('keydown', cut);
  requestAnimationFrame(grow);
  return mention && c.mentions ? withMentions(el, c) : el;   // @ cita uma imagem do canvas (Imagem e Vídeo)
}
function txt(c, n, key, ph, type) {
  const el = h('input', { type: type || 'text', placeholder: ph || '', class: 'nodrag' });
  el.value = n.params[key] ?? '';
  el.addEventListener('input', () => c.change(n, key, type === 'number' ? Number(el.value) : el.value));
  el.addEventListener('keydown', cut);
  return el;
}
const lab = (text, ctl) => h('div', null, h('label', { class: 'f' }, text), ctl);

// Provedor + Modelo (+ Resolução, quando o tipo tem). v0.17.1: o antigo bloco «Avançado» (prompt negativo, semente, parâmetros extras em JSON, ignorar estilos) saiu da tela;
// o que já estava salvo nos canvases continua valendo no motor.
const ratio = (w, h) => { const g = (a, b) => (b ? g(b, a % b) : a), d = g(w, h); return (w / d) + ':' + (h / d); };
// Lista de resoluções agrupada por formato (quadrado, paisagem, retrato), com os pixels totais: ajuda a escolher sem decorar
export function sizeSelect(c, n) {
  const kind = (s) => { const [w, h] = s.split('x').map(Number); return w === h ? 'sq' : w > h ? 'land' : 'port'; };
  const groups = [['sq', 'Quadrado'], ['land', 'Paisagem'], ['port', 'Retrato']];
  const el = h('select', { class: 'nodrag', 'aria-label': t('Resolução'), onchange: (e) => c.change(n, 'size', e.target.value) },
    groups.map(([k, label]) => h('optgroup', { label: t(label) }, c.meta.sizes.filter((s) => kind(s) === k).map((s) => h('option', { value: s, selected: s === n.params.size }, sizeLabel(s) + (Number(s.split('x')[0]) * Number(s.split('x')[1]) >= 4e6 ? ' · ' + t('pesado') : ''))))));
  el.value = n.params.size;
  return el;
}
export const sizeLabel = (s) => { const [w, h] = s.split('x').map(Number); return `${w}×${h} (${ratio(w, h)})`; };
// Seletor de modelo único (v0.17.5): sem «Provedor» no nó. A lista junta o que está instalado neste computador (GGUF e Hugging Face local) e os modelos de cada provedor de nuvem
// que está pronto para uso (com chave, ou servidor local) — escolher um modelo já define também o provedor que o executa. Nós antigos com provedor salvo continuam valendo.
const LISTS = new Map();   // «instalados:tipo» e «provedor:tipo» → { t, items }
const NOT_CLOUD = ['demo', 'gguf_local', 'local_hf', 'voice_settings'];   // não têm lista de nuvem (os locais vêm de «instalados»)
async function cachedList(key, loader, force) {
  const hit = LISTS.get(key);
  if (hit && !force && Date.now() - hit.t < 60000) return hit.items;
  let items = []; try { items = await loader(); } catch (e) { items = hit ? hit.items : []; }
  LISTS.set(key, { t: Date.now(), items }); return items;
}
const sizeTxt = (n) => (n >= 1 << 30 ? (n / (1 << 30)).toFixed(1) + ' GB' : n >= 1 << 20 ? Math.round(n / (1 << 20)) + ' MB' : '');
const usable = (p) => p.id === 'demo' || p.has_key || (!p.needs_key && (p.base_url || p.local));   // pronto para uso: Demo, com chave, ou servidor local/compatível com endereço
function modelPicker(c, n, cap) {
  const provs = c.prov.providers.filter((p) => p.caps.includes(cap));
  const defId = c.prov.active[cap] || 'demo';
  const def = c.prov.providers.find((p) => p.id === defId);
  const effId = n.params.provider || defId;
  const label = (id) => { const p = c.prov.providers.find((x) => x.id === id); return p ? t(p.label) : id; };
  const sel = h('select', { class: 'nodrag', id: 'mp_' + n.id + cap, title: t('Modelo') });
  const custom = h('input', { class: 'nodrag hidden', placeholder: t('nome do modelo'), value: n.params.model || '' });
  custom.addEventListener('input', () => c.change(n, 'model', custom.value.trim()));
  custom.addEventListener('keydown', cut);
  custom.addEventListener('blur', () => { if (!custom.value.trim() || custom.value.trim() === (n.params.model || '')) { custom.classList.add('hidden'); build(false, false); } });   // saiu do campo sem mudar nada (ou digitado, já salvo): some e a lista mostra o modelo salvo
  const reload = h('button', { class: 'btn icon sm nodrag', type: 'button', title: t('Atualizar a lista de modelos'), onclick: () => build(true, true) }, icon('refresh', 13));
  const opt = (value, text) => h('option', { value }, text);
  const group = (text, opts) => (opts.length ? h('optgroup', { label: text }, opts) : null);
  const cloudProvs = provs.filter((p) => usable(p) && !NOT_CLOUD.includes(p.id));
  async function build(force, all) {
    // lista de cada provedor de nuvem: sempre as sugestões; os modelos que o provedor oferece, para o provedor do nó (e para todos ao clicar em ↻)
    const [inst, lists] = await Promise.all([cachedList('inst:' + cap, () => api('/api/media/installed?cap=' + cap).then((r) => r.items), force),
      Promise.all(cloudProvs.map((p) => (all || p.id === effId || force ? cachedList(p.id + ':' + cap, () => api(`/api/media/models?provider=${encodeURIComponent(p.id)}&cap=${cap}`).then((r) => r.models), force) : Promise.resolve((LISTS.get(p.id + ':' + cap) || {}).items || []))))]);
    const cur = n.params.model || '', curProv = n.params.provider || '';
    const keyOf = (prov, model) => `P|${prov}|${model}`;
    const have = new Set();
    const groups = [];
    const instOpts = inst.map((m) => { have.add(keyOf(m.provider, m.model)); return opt(keyOf(m.provider, m.model), m.label + (m.detail ? ' · ' + m.detail : '') + (m.size ? ' · ' + sizeTxt(m.size) : '')); });
    groups.push(group(t('Instalados neste computador'), instOpts));
    cloudProvs.forEach((p, i) => {
      const names = [...new Set([...(p.suggest && p.suggest[cap]) || [], ...lists[i] || []])];
      const opts = names.map((m) => { have.add(keyOf(p.id, m)); return opt(keyOf(p.id, m), m); });
      groups.push(group(label(p.id), opts));
    });
    const extra = provs.filter((p) => ['demo', 'voice_settings'].includes(p.id) && usable(p)).map((p) => { have.add(keyOf(p.id, '')); return opt(keyOf(p.id, ''), label(p.id)); });
    groups.push(group(t('Sem modelo da nuvem'), extra));
    // o valor atual (salvo antes, ou digitado) sempre aparece, mesmo que a lista não o traga
    const curKey = !cur && !curProv ? '' : keyOf(curProv || effId, cur);
    const missing = curKey && !have.has(curKey) ? [opt(curKey, (cur || label(curProv || effId)) + (curProv ? ' · ' + label(curProv) : '') + ' (' + t('atual') + ')')] : [];
    sel.replaceChildren(opt('', t('Padrão') + (def ? ' · ' + (((def.models || {})[cap]) || label(def.id)) : '')), ...missing, ...groups.filter(Boolean),
      opt('__config', t('Configurar provedores e chaves…')), opt('__custom', t('Outro modelo…')));
    sel.value = curKey;
    if (sel.value !== curKey) sel.value = '';
    custom.classList.add('hidden');   // a lista foi refeita (↻) e voltou ao modelo salvo: o campo «nome do modelo» só vale enquanto «Outro modelo…» está escolhido
  }
  sel.addEventListener('change', () => {
    const v = sel.value;
    if (v === '__config') { sel.value = ''; c.openConfig(); return; }
    if (v === '__custom') { custom.classList.remove('hidden'); custom.focus(); return; }
    custom.classList.add('hidden');
    if (v === '') { c.change(n, 'provider', ''); c.change(n, 'model', '', true); return; }
    const [, prov, ...rest] = v.split('|'); c.change(n, 'provider', prov); c.change(n, 'model', rest.join('|'), true);   // o modelo escolhido define também o provedor
  });
  build(false, false);
  return h('div', { class: 'mpick' }, h('div', { class: 'row nw', style: { gap: '6px' } }, sel, reload), custom);
}

// Modelo (+ Resolução, quando o tipo tem). v0.17.1: o antigo bloco «Avançado» saiu da tela; v0.17.5: o «Provedor» também — só o Modelo. O que já estava salvo continua valendo no motor.
function providerBlock(c, n, cap, resolutionField) {
  const defId = c.prov.active[cap] || 'demo';
  const eff = c.prov.providers.find((p) => p.id === (n.params.provider || defId));
  const warn = eff && eff.needs_key && !eff.has_key
    ? h('div', { class: 'warnk' }, icon('warn', 13), t('Sem chave de API:'), h('a', { href: '#/config', onclick: () => c.openConfig() }, t('configurar')))
    : (eff && eff.id === 'demo' ? h('div', { class: 'dim small' }, t('Demo: resultado simples, sem IA real.')) : null);
  return [lab(t('Modelo'), modelPicker(c, n, cap)), warn, resolutionField || null];
}

function fileThumbs(c, n) {
  const files = (n.params.files || []).map((id) => c.asset(id)).filter(Boolean);
  const box = h('div', { class: 'thumbs' }, files.map((a) => {
    const pv = a.kind === 'image' ? h('img', { src: c.url(a), loading: 'lazy', draggable: 'false' })
      : a.kind === 'video' ? h('video', { src: c.url(a) + '#t=0.1', preload: 'metadata', muted: true })
        : h('div', null, icon('audio', 20));
    return h('div', { class: 'thumb nodrag', title: a.name, onclick: () => c.preview(a) }, pv, h('div', { class: 'nm' }, a.name),
      h('span', { class: 'x', onclick: (e) => { e.stopPropagation(); c.change(n, 'files', n.params.files.filter((f) => f !== a.id), true); } }, '×'));
  }));
  const input = h('input', { type: 'file', multiple: true, accept: 'image/*,video/*,audio/*', class: 'hidden', onchange: (e) => { c.uploadTo(n, [...e.target.files]); e.target.value = ''; } });
  return [files.length ? box : h('div', { class: 'dim small' }, t('Arraste arquivos aqui ou use o botão.')),
    h('button', { class: 'btn sm nodrag', onclick: () => input.click() }, icon('upload', 13), t('Adicionar arquivos')), input];
}

// ---------------------------------------------------------------------------------------------------- Style Folder: pastas e subpastas
// Os arquivos de estilo ficam na raiz do nó ou em pastas (e subpastas dentro delas). O nome de cada pasta ajuda o modelo a entender o que ela mostra («Personagens», «Luz»…).
// Cada pasta pode ser renomeada, ligada/desligada (uma pasta desligada não entra no estilo) e apagada. Limites iguais aos do servidor (schema.py).
export const MAX_FOLDERS = 60, MAX_DEPTH = 6, MAX_NAME = 40;
const newFolderId = () => 'f_' + Math.random().toString(36).slice(2, 12);
export function findFolder(folders, id) {
  for (const f of folders || []) { if (f.id === id) return f; const hit = findFolder(f.folders, id); if (hit) return hit; }
  return null;
}
export function countFolders(folders) { return (folders || []).reduce((n, f) => n + 1 + countFolders(f.folders), 0); }
const depthOf = (folders, id, d = 1) => { for (const f of folders || []) { if (f.id === id) return d; const r = depthOf(f.folders, id, d + 1); if (r) return r; } return 0; };
export function parentList(params, id) {   // a lista (do nó ou de uma pasta) que contém a pasta `id`
  if ((params.folders || []).some((f) => f.id === id)) return params.folders;
  const walk = (folders) => { for (const f of folders || []) { if ((f.folders || []).some((x) => x.id === id)) return f.folders; const r = walk(f.folders); if (r) return r; } return null; };
  return walk(params.folders);
}
export function uniqueName(siblings, wanted, except) {   // nomes únicos entre pastas irmãs (sem diferenciar maiúsculas): «Aquarela», «Aquarela (2)»…
  const clean = String(wanted || '').replace(/[\\/]/g, '-').trim().slice(0, MAX_NAME) || 'Pasta';
  const used = new Set((siblings || []).filter((f) => f.id !== except).map((f) => f.name.toLowerCase()));
  let name = clean, i = 2;
  while (used.has(name.toLowerCase())) { const suf = ' (' + i++ + ')'; name = clean.slice(0, MAX_NAME - suf.length) + suf; }
  return name;
}
export function removeFileEverywhere(params, aid) {   // tira o arquivo da raiz e de todas as pastas (devolve cópias novas)
  const walk = (folders) => (folders || []).map((f) => Object.assign({}, f, { files: f.files.filter((i) => i !== aid), folders: walk(f.folders) }));
  return { files: (params.files || []).filter((i) => i !== aid), folders: walk(params.folders) };
}
export function folderChoices(folders, prefix = '') {   // [id, «Aquarela / Detalhes»] de todas as pastas, em ordem de árvore
  return (folders || []).flatMap((f) => [[f.id, prefix + f.name], ...folderChoices(f.folders, prefix + f.name + ' / ')]);
}

function styleFolderBody(c, n) {
  const P = n.params;
  P.folders = P.folders || [];
  const touch = () => c.change(n, 'folders', P.folders, true);   // mexeu na árvore no lugar: salva e redesenha

  function addFolder(parent) {
    const list = parent ? parent.folders : P.folders;
    if (countFolders(P.folders) >= MAX_FOLDERS) return toast(t('Este nó já tem o máximo de {n} pastas.', { n: MAX_FOLDERS }), 'err');
    if (parent && depthOf(P.folders, parent.id) >= MAX_DEPTH) return toast(t('Pastas dentro de pastas: até {n} níveis.', { n: MAX_DEPTH }), 'err');
    const f = { id: newFolderId(), name: uniqueName(list, t('Nova pasta')), files: [], folders: [], enabled: true, open: true };
    list.push(f);
    if (parent) parent.open = true;
    c.accOpen.add('rename:' + f.id);   // já abre pedindo o nome
    touch();
  }
  function rename(f, name) {
    const list = parentList(P, f.id) || P.folders;
    const next = uniqueName(list, name || f.name, f.id);
    if (next !== f.name) { f.name = next; touch(); }
  }
  async function remove(f) {
    const n_ = (f.files || []).length + countFolders(f.folders);
    if (n_ && !(await confirmDialog(t('Apagar a pasta “{n}” e tudo o que há nela (as referências saem do estilo; os arquivos continuam no projeto)?', { n: f.name })))) return;
    const list = parentList(P, f.id);
    if (list) { list.splice(list.indexOf(f), 1); touch(); }
  }
  function moveFile(aid, toId) {   // '' = raiz do nó
    const clean = removeFileEverywhere(P, aid);
    P.files = clean.files; P.folders = clean.folders;
    if (toId) { const dst = findFolder(P.folders, toId); if (dst) dst.files.push(aid); else P.files.push(aid); } else P.files.push(aid);
    touch();
  }

  const thumb = (a, where) => {
    const pv = a.kind === 'image' ? h('img', { src: c.url(a), loading: 'lazy', draggable: 'false', alt: a.name })
      : a.kind === 'video' ? h('video', { src: c.url(a) + '#t=0.1', preload: 'metadata', muted: true })
        : h('div', null, icon('audio', 20));
    const el = h('div', { class: 'thumb nodrag', title: a.name, draggable: 'true', tabindex: '0', role: 'button', 'aria-label': t('Ver {n}', { n: a.name }), onclick: () => c.preview(a), onkeydown: (e) => { if (e.key === 'Enter') c.preview(a); } },
      pv, h('div', { class: 'nm' }, a.name),
      h('button', { class: 'x', type: 'button', dataset: { act: 'thumb-remove' }, title: t('Tirar do estilo'), 'aria-label': t('Tirar {n} do estilo', { n: a.name }), onclick: (e) => { e.stopPropagation(); const cl = removeFileEverywhere(P, a.id); P.files = cl.files; P.folders = cl.folders; touch(); } }, '×'),
      h('button', { class: 'mv', type: 'button', dataset: { act: 'thumb-move' }, title: t('Mover para…'), 'aria-label': t('Mover {n} para outra pasta', { n: a.name }), 'aria-haspopup': 'menu', onclick: (e) => { e.stopPropagation(); moveMenu(e.currentTarget, a, where); } }, icon('folder', 11)));
    el.addEventListener('dragstart', (e) => { e.dataTransfer.setData('text/flow-move', a.id); e.dataTransfer.effectAllowed = 'move'; });
    return el;
  };
  function moveMenu(anchor, a, where) {
    const pop = popover(anchor, h('div', { role: 'menu', class: 'toolmenu' },
      h('button', { class: 'opt', type: 'button', role: 'menuitem', dataset: { to: '' }, disabled: where === '', onclick: () => { pop.close(); moveFile(a.id, ''); } }, icon('folder', 14), t('Raiz do nó')),
      ...folderChoices(P.folders).map(([id, label]) => h('button', { class: 'opt', type: 'button', role: 'menuitem', dataset: { to: id }, disabled: where === id, onclick: () => { pop.close(); moveFile(a.id, id); } }, icon('folder', 14), label)),
      !folderChoices(P.folders).length ? h('div', { class: 'dim small', style: { padding: '6px 10px' } }, t('Crie uma pasta primeiro.')) : null));
  }
  const thumbsOf = (ids, where) => {
    const files = (ids || []).map((id) => c.asset(id)).filter(Boolean);
    return files.length ? h('div', { class: 'thumbs' }, files.map((a) => thumb(a, where))) : null;
  };
  const fileInput = (fid) => h('input', { type: 'file', multiple: true, accept: 'image/*,video/*,audio/*', class: 'hidden', onchange: (e) => { c.uploadTo(n, [...e.target.files], fid); e.target.value = ''; } });

  function folderRow(f, depth) {
    const input = fileInput(f.id);
    const renaming = c.accOpen.has('rename:' + f.id);
    const nameEl = renaming
      ? h('input', { class: 'sf-name nodrag', value: f.name, maxlength: MAX_NAME, 'aria-label': t('Nome da pasta'), onkeydown: (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); c.accOpen.delete('rename:' + f.id); rename(f, e.target.value); touch(); } else if (e.key === 'Escape') { c.accOpen.delete('rename:' + f.id); touch(); } },
        onblur: (e) => { if (c.accOpen.has('rename:' + f.id)) { c.accOpen.delete('rename:' + f.id); rename(f, e.target.value); touch(); } } })
      : h('button', { class: 'sf-label nodrag', type: 'button', title: t('Clique duas vezes para renomear'), onclick: () => { f.open = !f.open; touch(); }, ondblclick: () => { c.accOpen.add('rename:' + f.id); touch(); } }, f.name);
    const count = (f.files || []).length + countFolders(f.folders);
    const head = h('div', { class: 'sf-head' + (f.enabled ? '' : ' off') },
      h('button', { class: 'sf-tog nodrag', type: 'button', dataset: { act: 'folder-open' }, 'aria-expanded': f.open ? 'true' : 'false', 'aria-label': (f.open ? t('Recolher') : t('Abrir')) + ' ' + f.name, onclick: () => { f.open = !f.open; touch(); } }, icon(f.open ? 'chevd' : 'chevr', 13)),
      icon(f.open ? 'foldero' : 'folder', 14), nameEl, h('span', { class: 'sf-n dim small' }, '(' + count + ')'), h('span', { class: 'grow' }),
      h('button', { class: 'sf-b nodrag', type: 'button', dataset: { act: 'folder-enable' }, title: f.enabled ? t('Pasta ligada: vale no estilo (clique para desligar)') : t('Pasta desligada: fora do estilo (clique para ligar)'), 'aria-pressed': f.enabled ? 'true' : 'false', 'aria-label': t('Ligar ou desligar a pasta {n}', { n: f.name }), onclick: () => { f.enabled = !f.enabled; touch(); } }, icon('eye', 13)),
      h('button', { class: 'sf-b nodrag', type: 'button', dataset: { act: 'folder-rename' }, title: t('Renomear a pasta'), 'aria-label': t('Renomear a pasta {n}', { n: f.name }), onclick: () => { c.accOpen.add('rename:' + f.id); touch(); } }, icon('edit', 13)),
      h('button', { class: 'sf-b nodrag', type: 'button', dataset: { act: 'folder-sub' }, title: t('Nova subpasta'), 'aria-label': t('Nova subpasta em {n}', { n: f.name }), onclick: () => addFolder(f) }, icon('plus', 13)),
      h('button', { class: 'sf-b nodrag', type: 'button', dataset: { act: 'folder-upload' }, title: t('Adicionar arquivos a esta pasta'), 'aria-label': t('Adicionar arquivos à pasta {n}', { n: f.name }), onclick: () => input.click() }, icon('upload', 13)),
      h('button', { class: 'sf-b danger nodrag', type: 'button', dataset: { act: 'folder-delete' }, title: t('Apagar a pasta'), 'aria-label': t('Apagar a pasta {n}', { n: f.name }), onclick: () => remove(f) }, icon('trash', 13)), input);
    const row = h('div', { class: 'sf-folder', dataset: { folder: f.id }, style: { marginLeft: depth ? '12px' : '0' }, role: 'group', 'aria-label': t('Pasta {n}', { n: f.name }) }, head);
    if (f.open) {
      const inner = h('div', { class: 'sf-body' }, thumbsOf(f.files, f.id) || (f.folders.length ? null : h('div', { class: 'dim small sf-empty' }, t('Pasta vazia: arraste arquivos para cá ou use o botão de enviar.'))), ...f.folders.map((x) => folderRow(x, depth + 1)));
      row.append(inner);
    }
    const accepts = (e) => [...e.dataTransfer.types].includes('text/flow-move');
    row.addEventListener('dragover', (e) => { if (accepts(e)) { e.preventDefault(); e.stopPropagation(); head.classList.add('over'); } });
    row.addEventListener('dragleave', () => head.classList.remove('over'));
    row.addEventListener('drop', (e) => { head.classList.remove('over'); const aid = e.dataTransfer.getData('text/flow-move'); if (aid) { e.preventDefault(); e.stopPropagation(); moveFile(aid, f.id); } });
    return row;
  }

  const rootInput = fileInput('');
  const rootThumbs = thumbsOf(P.files, '');
  const rootDrop = h('div', { class: 'sf-root' }, rootThumbs || (P.folders.length ? h('div', { class: 'dim small' }, t('Sem arquivos soltos na raiz.')) : h('div', { class: 'dim small' }, t('Arraste arquivos aqui ou use o botão. Crie pastas e subpastas para organizar as referências.'))));
  rootDrop.addEventListener('dragover', (e) => { if ([...e.dataTransfer.types].includes('text/flow-move')) { e.preventDefault(); } });
  rootDrop.addEventListener('drop', (e) => { const aid = e.dataTransfer.getData('text/flow-move'); if (aid) { e.preventDefault(); e.stopPropagation(); moveFile(aid, ''); } });
  return [
    h('div', { class: 'row nw sf-bar', style: { gap: '6px', flexWrap: 'wrap' } },
      h('button', { class: 'btn sm nodrag', type: 'button', dataset: { act: 'new-folder' }, onclick: () => addFolder(null) }, icon('plus', 13), t('Nova pasta')),
      h('button', { class: 'btn sm nodrag', type: 'button', dataset: { act: 'add-files' }, onclick: () => rootInput.click() }, icon('upload', 13), t('Adicionar arquivos')), rootInput),
    rootDrop,
    ...(P.folders.length ? [h('div', { class: 'sf-tree', role: 'tree', 'aria-label': t('Pastas de estilo') }, P.folders.map((f) => folderRow(f, 0)))] : []),
  ];
}

const BODY = {
  text: (c, n) => [ta(c, n, 'text', t('Escreva o texto… (digite @ para citar uma imagem, vídeo ou som do projeto)'), 4, true)],
  llm: (c, n) => [ta(c, n, 'instruction', t('O que fazer com o texto de entrada? Ex.: “Descreva a cena com detalhes visuais”.'), 3, true),
    h('div', { class: 'dim small' }, t('Usa o modelo de texto ativo em Configuração → Provedores.')),
    checkbox(t('Ignorar estilos globais'), n.params.ignore_global_styles, (v) => c.change(n, 'ignore_global_styles', v, true))],
  upload: (c, n) => fileThumbs(c, n),
  image: (c, n) => [
    seg([['generate', t('Gerar')], ['edit', t('Editar')]], n.params.mode, (v) => c.change(n, 'mode', v, true)),
    ta(c, n, 'prompt', n.params.mode === 'edit' ? t('O que mudar na imagem ligada em “Referências” (ou citada com @)?') : t('Descreva a imagem (ou ligue um nó de texto). Digite @ para citar uma imagem, vídeo ou som do projeto.'), 3, true),
    lab(t('Quantidade'), select([1, 2, 3, 4].map((i) => [String(i), String(i)]), String(n.params.count), (v) => c.change(n, 'count', Number(v)))),
    ...providerBlock(c, n, 'image', lab(t('Resolução'), sizeSelect(c, n)))],
  video: (c, n) => [
    ta(c, n, 'prompt', t('Descreva o vídeo (ou ligue um texto e/ou uma imagem inicial). Digite @ para citar a imagem inicial.'), 3, true),
    h('div', { class: 'r2' }, lab(t('Duração (s)'), txt(c, n, 'duration', '5', 'number')), lab(t('Proporção'), select(c.meta.aspects.map((a) => [a, a]), n.params.aspect, (v) => c.change(n, 'aspect', v)))),
    ...providerBlock(c, n, 'video', lab(t('Resolução'), select((c.meta.resolutions || [0]).map((r) => [String(r), r ? r + 'p' : t('Automática')]), String(n.params.resolution || 0), (v) => c.change(n, 'resolution', Number(v)))))],
  sound: (c, n) => [
    seg([['sfx', t('Efeito')], ['music', t('Música')]], n.params.kind, (v) => c.change(n, 'kind', v, true)),
    ta(c, n, 'prompt', n.params.kind === 'music' ? t('Estilo da música: calma, piano, noturna…') : t('Ex.: chuva forte com trovões'), 2),
    lab(t('Duração (s)'), txt(c, n, 'duration', '5', 'number')),
    ...providerBlock(c, n, 'sound')],
  voice: (c, n) => [
    ta(c, n, 'text', t('O que a voz vai dizer (ou ligue um nó de texto)…'), 3),
    h('div', { class: 'r2' }, lab(t('Voz'), txt(c, n, 'voice', t('padrão'))), lab(t('Velocidade'), txt(c, n, 'speed', '1', 'number'))),
    ...providerBlock(c, n, 'voice')],
  transcribe: (c, n) => [h('div', { class: 'dim small' }, t('Ligue um áudio ou vídeo na entrada.')), lab(t('Idioma (opcional)'), txt(c, n, 'language', 'pt, en…')), ...providerBlock(c, n, 'stt')],
  style_prompt: (c, n) => [ta(c, n, 'text', t('Ex.: ilustração em aquarela, cores suaves, traço delicado.'), 4), globalCheck(c, n)],
  style_folder: (c, n) => [...styleFolderBody(c, n), globalCheck(c, n),
    n.result.digest ? h('div', { class: 'digest nodrag' }, n.result.digest) : null,
    ((n.params.files || []).length || countFolders(n.params.folders)) ? h('button', { class: 'btn sm nodrag', type: 'button', onclick: () => c.run([n.id], true) }, icon('refresh', 13), t('Analisar estilo')) : null],
  editor: (c, n) => {
    const tl = n.params.timeline;
    return [h('div', { class: 'small muted' }, t('{n} clipe(s) · {s}s', { n: tl.clips.length, s: (tl.duration || 0).toFixed(1) }) + ' · ' + n.params.width + '×' + n.params.height),
      h('button', { class: 'btn sm primary nodrag', onclick: () => c.openTimeline(n) }, icon('film', 13), t('Abrir editor')),
      h('div', { class: 'dim small' }, t('Ligue nós em “Clipes” para usar as saídas deles na linha do tempo.'))];
  },
};
function globalCheck(c, n) {
  return h('div', null, checkbox(t('Vale para o projeto todo'), n.params.global, (v) => c.change(n, 'global', v, true)),
    h('div', { class: 'dim small' }, n.params.global ? t('Aplicado automaticamente a todos os nós de geração.') : t('Aplicado só aos nós ligados em “Estilo”.')));
}


// ---------------------------------------------------------------------------------------------------- nós novos (v0.11): formulários por tabela
const sel = (c, n, key, options) => { const el = select(options.map(([v, l]) => [String(v), l]), String(n.params[key]), (v) => c.change(n, key, typeof options[0][0] === 'number' ? Number(v) : v, true)); el.classList.add('nodrag'); return el; };
const colorIn = (c, n, key) => { const el = h('input', { type: 'color', class: 'nodrag', value: n.params[key] || '#000000' }); el.addEventListener('input', () => c.change(n, key, el.value)); return el; };
const FILTERS = [['none', 'Nenhum'], ['bw', 'Preto e branco'], ['sepia', 'Sépia'], ['vivid', 'Vívido'], ['warm', 'Quente'], ['cool', 'Frio'], ['cinematic', 'Cinema'], ['vhs', 'VHS'], ['phonk', 'Phonk'], ['blur', 'Desfoque'], ['sharpen', 'Nitidez'], ['vignette', 'Vinheta'], ['invert', 'Inverter']];
const SIZE_NUM = (k, ph) => ['num', k, ph];
// cada campo: [tipo, chave, rótulo, opções|placeholder]; tipos: ta, txt, num, sel, chk, color
const FORMS = {
  text_template: [['ta', 'template', 'Modelo', 'Ex.: Cena: {1}. Estilo: {2}. Tudo: {todos}', 4], ['hint', 'Use {1}, {2}… para os textos ligados em «Variáveis», {todos} para todos juntos.']],
  text_join: [['sel', 'sep', 'Separador', [['paragraph', 'Parágrafo'], ['line', 'Linha'], ['space', 'Espaço'], ['comma', 'Vírgula'], ['dash', 'Traço'], ['custom', 'Personalizado']]], ['txt', 'custom', 'Separador personalizado', ' | '], ['chk', 'numbering', 'Numerar os textos'], ['txt', 'prefix', 'Antes', ''], ['txt', 'suffix', 'Depois', '']],
  text_edit: [['sel', 'op', 'O que fazer', [['trim', 'Limpar espaços'], ['upper', 'MAIÚSCULAS'], ['lower', 'minúsculas'], ['title', 'Cada Palavra Maiúscula'], ['dedupe', 'Tirar linhas repetidas'], ['sort', 'Ordenar linhas'], ['reverse', 'Inverter linhas'], ['number', 'Numerar linhas'], ['no_empty', 'Tirar linhas vazias'], ['replace', 'Trocar palavra']]], ['txt', 'find', 'Procurar', ''], ['txt', 'replace', 'Trocar por', '']],
  text_pick: [['sel', 'mode', 'Pegar', [['lines', 'Linhas'], ['sentences', 'Frases'], ['paragraphs', 'Parágrafos'], ['words', 'Palavras']]], ['num', 'index', 'A partir do nº (0 = tudo)'], ['num', 'count', 'Quantos'], ['chk', 'random', 'Sortear'], ['num', 'seed', 'Semente (0 = aleatória)']],
  text_refine: [['sel', 'mode', 'Modo', [['improve', 'Melhorar prompt'], ['translate', 'Traduzir'], ['summarize', 'Resumir'], ['expand', 'Expandir'], ['fix', 'Corrigir'], ['scenes', 'Dividir em cenas'], ['captions', 'Fazer legendas']]], ['txt', 'language', 'Idioma (para traduzir)', 'inglês'], ['ta', 'instruction', 'Instrução extra (opcional)', '', 2], ['hint', 'Usa o modelo de texto ativo em Configuração → Provedores; sem IA, faz uma versão simples.']],
  img_resize: [['num', 'width', 'Largura (0 = automática)'], ['num', 'height', 'Altura (0 = automática)'], ['sel', 'mode', 'Encaixe', [['fit', 'Encaixar'], ['cover', 'Preencher e cortar'], ['stretch', 'Esticar'], ['pad', 'Encaixar com borda']]], ['sel', 'rotate', 'Girar', [[0, 'Não girar'], [90, '90°'], [180, '180°'], [270, '270°']]], ['sel', 'flip', 'Espelhar', [['none', 'Não'], ['h', 'Horizontal'], ['v', 'Vertical'], ['both', 'Os dois']]], ['color', 'bg', 'Cor da borda'], ['sel', 'format', 'Formato', [['png', 'PNG'], ['jpg', 'JPG']]]],
  img_filter: [['sel', 'preset', 'Filtro', FILTERS], ['range', 'brightness', 'Brilho', -1, 1, 0.05], ['range', 'contrast', 'Contraste', 0, 3, 0.05], ['range', 'saturation', 'Saturação', 0, 3, 0.05]],
  img_text: [['ta', 'text', 'Texto (ou ligue um nó de texto)', 'Escreva o texto…', 2], ['sel', 'pos', 'Posição', [['top', 'Em cima'], ['center', 'No meio'], ['bottom', 'Embaixo']]], ['range', 'size', 'Tamanho (% da altura)', 1, 30, 1], ['color', 'color', 'Cor do texto'], ['chk', 'box', 'Faixa escura atrás']],
  img_collage: [['num', 'cols', 'Colunas'], ['num', 'cell', 'Tamanho de cada imagem (px)'], ['num', 'gap', 'Espaço (px)'], ['color', 'bg', 'Cor do fundo']],
  img_frame: [['sel', 'at', 'Quadro', [['first', 'O primeiro'], ['middle', 'O do meio'], ['last', 'O último'], ['seconds', 'Em um segundo exato']]], ['num', 'seconds', 'Segundo'], ['num', 'count', 'Quantos quadros (1 a 4, espaçados)']],
  vid_trim: [['num', 'start', 'Início (s)'], ['num', 'duration', 'Duração (s, 0 = até o fim)']],
  vid_join: [['num', 'width', 'Largura'], ['num', 'height', 'Altura'], ['num', 'fps', 'Quadros por segundo'], ['num', 'image_seconds', 'Segundos por imagem'], ['range', 'fade', 'Transição (s)', 0, 2, 0.05], ['color', 'bg', 'Cor do fundo']],
  vid_speed: [['range', 'factor', 'Velocidade (×)', 0.25, 4, 0.05], ['chk', 'reverse', 'Tocar ao contrário']],
  vid_look: [['sel', 'preset', 'Visual', FILTERS], ['num', 'fade_in', 'Fade de entrada (s)'], ['num', 'fade_out', 'Fade de saída (s)']],
  vid_slideshow: [['num', 'seconds', 'Segundos por imagem'], ['num', 'width', 'Largura'], ['num', 'height', 'Altura'], ['chk', 'zoom', 'Zoom suave'], ['range', 'fade', 'Transição (s)', 0, 2, 0.05], ['range', 'music_volume', 'Volume da música', 0, 2, 0.05]],
  aud_trim: [['num', 'start', 'Início (s)'], ['num', 'duration', 'Duração (s, 0 = até o fim)'], ['num', 'fade_in', 'Fade de entrada (s)'], ['num', 'fade_out', 'Fade de saída (s)']],
  aud_mix: [['sel', 'mode', 'Como juntar', [['mix', 'Ao mesmo tempo'], ['sequence', 'Um depois do outro']]], ['range', 'volume', 'Volume', 0, 2, 0.05]],
  aud_fx: [['sel', 'fx', 'Efeito', [['normalize', 'Normalizar volume'], ['louder', 'Mais alto'], ['quieter', 'Mais baixo'], ['faster', 'Mais rápido'], ['slower', 'Mais lento'], ['reverse', 'Ao contrário'], ['echo', 'Eco'], ['telephone', 'Telefone'], ['bass', 'Mais graves'], ['none', 'Nenhum']]], ['range', 'amount', 'Intensidade', 0.1, 4, 0.1]],
  aud_from_video: [['sel', 'format', 'Formato', [['mp3', 'MP3'], ['wav', 'WAV'], ['m4a', 'M4A']]]],
  aud_loop: [['num', 'duration', 'Duração final (s)'], ['num', 'fade_out', 'Fade no final (s)']],
  in_color: [['color', 'color', 'Cor'], ['sel', 'gradient', 'Degradê', [['none', 'Cor lisa'], ['vertical', 'Vertical'], ['horizontal', 'Horizontal'], ['diagonal', 'Diagonal']]], ['color', 'color2', 'Segunda cor'], ['num', 'width', 'Largura'], ['num', 'height', 'Altura']],
  in_silence: [['num', 'seconds', 'Duração (s)']],
  in_url: [['txt', 'url', 'Endereço (https://…)', 'https://exemplo.com/foto.jpg'], ['hint', 'Só links públicos de imagem, vídeo ou áudio (até 60 MB).']],
  in_random: [['ta', 'lines', 'Uma ideia por linha', '', 5], ['num', 'count', 'Quantas sortear'], ['sel', 'joiner', 'Juntar com', [['line', 'Linhas'], ['comma', 'Vírgulas'], ['space', 'Espaços']]], ['num', 'seed', 'Semente (0 = aleatória)']],
  in_vars: [['ta', 'template', 'Texto', '{data} {hora} · {projeto}', 2], ['hint', 'Variáveis: {data}, {hora}, {ano}, {projeto}, {nos}, {arquivos}, {aleatorio}.']],
  out_export: [['sel', 'quality', 'Qualidade', [['480p', '480p'], ['720p', '720p'], ['1080p', '1080p']]], ['chk', 'burn', 'Gravar as legendas no vídeo'], ['range', 'music_volume', 'Volume dos áudios sobre o som do vídeo', 0, 2, 0.05], ['num', 'image_seconds', 'Segundos (se a entrada for uma imagem)'], ['num', 'fps', 'Quadros por segundo']],
  out_gif: [['num', 'width', 'Largura (px)'], ['num', 'fps', 'Quadros por segundo'], ['num', 'max_seconds', 'Duração máxima (s)']],
  out_audio: [['sel', 'format', 'Formato', [['mp3', 'MP3'], ['wav', 'WAV'], ['m4a', 'M4A']]], ['sel', 'mode', 'Como juntar', [['sequence', 'Um depois do outro'], ['mix', 'Ao mesmo tempo']]], ['chk', 'normalize', 'Normalizar o volume']],
  out_image: [['sel', 'format', 'Formato', [['png', 'PNG'], ['jpg', 'JPG'], ['webp', 'WebP']]], ['range', 'quality', 'Qualidade', 10, 100, 1], ['num', 'max_width', 'Largura máxima (px, 0 = original)']],
  out_gallery: [['hint', 'Ligue em «Itens» imagens, vídeos, áudios e textos de qualquer nó: eles aparecem aqui para ver e baixar.']],
};
function formBody(c, n) {
  return (FORMS[n.type] || []).map(([kind, key, label, a, b, step]) => {
    if (kind === 'hint') return h('div', { class: 'dim small' }, t(key));
    if (kind === 'ta') return lab(t(label), ta(c, n, key, t(a), b));
    if (kind === 'txt') return lab(t(label), txt(c, n, key, a));
    if (kind === 'num') return lab(t(label), txt(c, n, key, '', 'number'));
    if (kind === 'sel') return lab(t(label), sel(c, n, key, a.map(([v, l]) => [v, t(l)])));
    if (kind === 'chk') return checkbox(t(label), !!n.params[key], (v) => c.change(n, key, v, true));
    if (kind === 'color') return lab(t(label), colorIn(c, n, key));
    if (kind === 'range') { const el = h('input', { type: 'range', class: 'nodrag', min: a, max: b, step, value: n.params[key] }); const out = h('span', { class: 'dim small' }, String(n.params[key])); el.addEventListener('input', () => { out.textContent = el.value; c.change(n, key, Number(el.value)); }); return lab(t(label), h('div', { class: 'row nw' }, el, out)); }
    return null;
  });
}

export const nodeBody = (c, n) => h('div', { class: 'bd' }, BODY[n.type] ? BODY[n.type](c, n) : (FORMS[n.type] ? formBody(c, n) : null));
export const capOf = (type) => CAP[type] || '';

// ---------------------------------------------------------------------------------------------------- resultado
export function nodeResult(c, n) {
  const st = c.state(n.id), r = n.result;
  const box = h('div', { class: 'res' });
  const items = (r.assets || []).map((id) => c.asset(id)).filter(Boolean);
  if (st.state === 'running') box.append(h('div', { class: 'run' }, h('div', { class: 'spinner' }), st.note || t('Gerando…')));
  else if (st.state === 'queued') box.append(h('div', { class: 'run' }, t('Na fila…')));
  else if (st.state === 'skipped') box.append(h('div', { class: 'dim small' }, t('Pulado: um nó de entrada falhou.')));
  const error = st.state === 'error' ? st.message : (r.state === 'error' ? r.error : '');
  if (error) {
    const sup = /\[\[flow-support:([^\]]+)\]\]/.exec(error);   // GGUF de difusão sem VAE/codificador de texto: oferece baixar o que falta
    const upd = /\[\[flow-sd-update\]\]/.test(error);   // a stable-diffusion.cpp instalada não reconhece o modelo: oferece compilar a versão mais nova
    const cli = /\[\[flow-sd-cli\]\]/.test(error);   // sem compilar: baixa o executável pronto (sd-cli) da stable-diffusion.cpp
    box.append(h('div', { class: 'err' }, error.replace(/\s*\[\[flow-support:[^\]]+\]\]/, '').replace(/\s*\[\[flow-sd-update\]\]/, '').replace(/\s*\[\[flow-sd-cli\]\]/, '')));
    if (cli) {
      const cb = h('button', { class: 'btn sm primary nodrag', type: 'button', id: 'sdcli-' + n.id, style: { marginTop: '6px', marginRight: '6px' } }, icon('download', 13), t('Baixar o executável pronto (sem compilar)'));
      cb.onclick = async () => {
        cb.disabled = true;
        try {
          const r = await api('/api/media/sd-cli', { method: 'POST', body: {} });
          toast(t('Baixando o sd-cli da stable-diffusion.cpp…'));
          events('/api/jobs/' + r.job_id + '/events', (ev) => {
            if (ev.type === 'note') cb.lastChild.textContent = ' ' + ev.message.slice(0, 40);
            else if (ev.type === 'progress' && ev.total) cb.lastChild.textContent = ' ' + Math.round(100 * ev.done / ev.total) + '%';
            else if (ev.type === 'done') { toast(t('sd-cli pronto. Execute o nó de novo.'), 'ok'); cb.remove(); }
            else if (ev.type === 'error') { toast(ev.message, 'err'); cb.disabled = false; }
            else if (ev.type === 'cancelled') { cb.disabled = false; }
          });
        } catch (e) { cb.disabled = false; toast(e.status === 409 ? t('Já há um download do sd-cli em andamento.') : e.message, 'err'); }
      };
      box.append(cb);
    }
    if (upd) {
      const ub = h('button', { class: 'btn sm primary nodrag', type: 'button', id: 'sdup-' + n.id, style: { marginTop: '6px' } }, icon('download', 13), t('Atualizar a biblioteca agora'));
      ub.onclick = async () => {
        ub.disabled = true;
        try {
          const r = await api('/api/media/sd-latest', { method: 'POST', body: {} });
          toast(t('Compilando a stable-diffusion.cpp mais nova… pode levar vários minutos.'));
          events('/api/jobs/' + r.job_id + '/events', (ev) => {
            if (ev.type === 'note') ub.lastChild.textContent = ' ' + ev.message.slice(0, 40);
            else if (ev.type === 'done') { toast(t('Biblioteca atualizada. Execute o nó de novo.'), 'ok'); ub.remove(); }
            else if (ev.type === 'error') { toast(ev.message, 'err'); ub.disabled = false; }
            else if (ev.type === 'cancelled') { ub.disabled = false; }
          });
        } catch (e) { ub.disabled = false; toast(e.status === 409 ? t('Já há uma atualização da biblioteca em andamento.') : e.message, 'err'); }
      };
      box.append(ub);
    }
    if (sup) {
      const btn = h('button', { class: 'btn sm primary nodrag', type: 'button', id: 'sup-' + n.id, style: { marginTop: '6px' } }, icon('download', 13), t('Baixar os arquivos de apoio'));
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          const r = await api('/api/media/support/download', { method: 'POST', body: { model: sup[1], cap: n.type === 'video' ? 'video' : 'image' } });
          toast(t('Baixando {f} (≈ {g} GB)…', { f: r.files.join(', '), g: r.approx_gb }));
          events('/api/jobs/' + r.job_id + '/events', (ev) => {
            if (ev.type === 'progress' && ev.total) btn.lastChild.textContent = ' ' + Math.round(ev.done / ev.total * 100) + '%';
            else if (ev.type === 'done') { toast(t('Arquivos de apoio baixados. Execute o nó de novo.'), 'ok'); btn.remove(); }
            else if (ev.type === 'error') { toast(ev.message, 'err'); btn.disabled = false; }
            else if (ev.type === 'cancelled') { btn.disabled = false; }
          });
        } catch (e) { btn.disabled = false; toast(e.status === 409 ? t('Já há um download de arquivos de apoio em andamento.') : e.message, 'err'); }
      };
      box.append(btn);
    }
    if (/ainda não foi baixado|not been downloaded/i.test(error)) box.append(h('button', { class: 'btn sm primary nodrag', type: 'button', style: { marginTop: '6px' }, onclick: () => window.dispatchEvent(new CustomEvent('flow:go', { detail: { route: 'config', ctx: { tab: 'media' } } })) }, icon('download', 13), t('Baixar o modelo agora')));   // abre Configuração → Mídia na escolha da precisão
  }
  if (st.state === 'running' || st.state === 'queued') return box;
  const imgs = items.filter((a) => a.kind === 'image');
  if (imgs.length) box.append(h('div', { class: 'rimgs nodrag' + (imgs.length === 1 ? ' one' : '') }, imgs.map((a) => h('img', { src: c.url(a), loading: 'lazy', title: a.prompt || a.name, draggable: 'false', onclick: () => c.preview(a, imgs) }))));
  items.filter((a) => a.kind === 'video').forEach((a) => box.append(h('video', { src: c.url(a), controls: true, preload: 'metadata', class: 'nodrag' })));
  items.filter((a) => a.kind === 'audio').forEach((a) => box.append(h('audio', { src: c.url(a), controls: true, preload: 'metadata', class: 'nodrag' })));
  if (r.text && !['text', 'style_prompt'].includes(n.type) && !(st.state === 'error')) box.append(h('div', { class: 'rtxt nodrag' }, r.text));
  (st.warnings || []).forEach((w) => box.append(h('div', { class: 'wr' }, w)));
  if (items.length) box.append(h('div', { class: 'dim small', style: { marginTop: '6px' } }, items.map((a) => (a.provider ? t(c.providerLabel(a.provider)) : '') + (a.model ? ' · ' + a.model : '')).filter(Boolean)[0] || ''));
  return box.childNodes.length ? box : null;
}
