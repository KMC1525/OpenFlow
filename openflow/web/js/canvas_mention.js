import { t } from './i18n.js';
import { h, icon } from './ui.js';

// Menções com «@» nos prompts (nós Texto, Texto IA, Imagem e Vídeo): digite @ e escolha uma imagem, vídeo ou som do canvas; imagens e quadros de vídeo viram referência da geração (veja openflow/canvas/mentions.py).
const TOKEN = /(?:^|[^\w@.])@([A-Za-z0-9_-]*)$/;          // «@ap» logo antes do cursor
const MENTION = /(?<![\w@.])@([A-Za-z0-9][A-Za-z0-9_-]*)/g;  // mesma regra do servidor

// ta: o <textarea> do prompt; c: { mentions(): Promise<[{slug, name, url}]> }. Devolve o elemento que substitui o textarea (caixa + lista + fichas das imagens citadas).
export function withMentions(ta, c) {
  let items = [], open = false, sel = 0, range = null, loaded = 0, seq = 0;   // seq: descarta respostas atrasadas (fechou ou digitou de novo enquanto a lista carregava)
  const pop = h('div', { class: 'mpop nodrag hidden', role: 'listbox' }), chips = h('div', { class: 'mchips' });
  // miniatura por tipo: imagem → ela mesma; vídeo → o primeiro quadro; som → ícone
  const thumb = (it) => (it.kind === 'video' ? h('video', { class: 'mth', src: it.url + '#t=0.5', preload: 'metadata', muted: true, playsinline: true })
    : it.kind === 'audio' ? h('i', { class: 'mth aud', title: t('Som') }, icon('audio', 14)) : h('i', { class: 'mth', style: { backgroundImage: `url("${it.url}")` } }));
  const wrap = h('div', { class: 'mwrap' }, ta, pop, chips);
  const load = async (force) => {
    if (!force && Date.now() - loaded < 4000) return items;
    try { items = await c.mentions(); loaded = Date.now(); } catch (e) { items = []; }
    return items;
  };
  const close = () => { seq++; open = false; pop.classList.add('hidden'); };
  function paintChips() {
    const toks = [...new Set([...ta.value.matchAll(MENTION)].map((m) => m[1]))];
    chips.replaceChildren(...toks.map((tok) => {
      const it = items.find((x) => x.slug === tok.toLowerCase() || x.slug === tok.toLowerCase().replace(/_/g, '-') || x.id === tok);   // mesma regra do servidor (@foto_perfil vale para foto-perfil)
      return it ? h('span', { class: 'mchip ' + (it.kind || 'image'), title: it.name }, thumb(it), '@' + it.slug)
        : h('span', { class: 'mchip bad', title: t('Não há imagem com esse apelido neste projeto') }, '@' + tok);
    }));
  }
  function paintPop(list) {
    pop.replaceChildren(...(list.length ? list.map((it, i) => h('div', { class: 'mi' + (i === sel ? ' on' : ''), role: 'option', dataset: { slug: it.slug },
      onmousedown: (e) => { e.preventDefault(); pick(it); } }, thumb(it), h('b', null, '@' + it.slug), h('span', { class: 'muted small' }, (it.kind === 'video' ? t('vídeo') : it.kind === 'audio' ? t('som') : t('imagem')) + ' · ' + it.name)))
      : [h('div', { class: 'mi none' }, t('Nenhuma mídia neste projeto. Envie ou gere uma imagem, vídeo ou som e cite com @.'))]));
    pop.classList.remove('hidden'); open = true;
  }
  const filtered = () => items.filter((x) => !range || x.slug.includes(range.q.toLowerCase())).slice(0, 8);
  async function refresh() {
    const pos = ta.selectionStart, m = TOKEN.exec(ta.value.slice(0, pos));
    if (!m) { close(); return; }
    range = { start: pos - m[1].length - 1, end: pos, q: m[1] };
    const my = ++seq;
    await load(true);
    if (my !== seq) return;
    sel = 0; paintPop(filtered()); paintChips();
  }
  function pick(it) {
    if (!range) return;
    const v = ta.value, ins = '@' + it.slug + (/^[\s,.;:!?)]/.test(v.slice(range.end)) ? '' : ' ');   // sem espaço a mais quando já há um espaço ou pontuação depois
    ta.value = v.slice(0, range.start) + ins + v.slice(range.end);
    const caret = range.start + ins.length; ta.setSelectionRange(caret, caret);
    close(); ta.dispatchEvent(new Event('input', { bubbles: true })); ta.focus();
  }
  ta.addEventListener('input', () => { refresh(); paintChips(); });
  ta.addEventListener('click', () => { if (ta.value.includes('@')) refresh(); });
  ta.addEventListener('blur', () => setTimeout(close, 120));
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { if (open) e.preventDefault(); close(); return; }   // também cancela uma lista que ainda está carregando
    if (!open) return;
    const list = filtered();
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + Math.max(1, list.length)) % Math.max(1, list.length); paintPop(list); }
    else if ((e.key === 'Enter' || e.key === 'Tab') && list[sel]) { e.preventDefault(); e.stopPropagation(); pick(list[sel]); }
  }, true);
  if (ta.value.includes('@')) load(true).then(paintChips); else paintChips();
  return wrap;
}
