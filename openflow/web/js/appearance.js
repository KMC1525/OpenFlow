// Peças de personalização usadas na Configuração → Aparência e nas boas-vindas: cartões de tema e amostras de cor.
import { t } from './i18n.js';
import { h } from './ui.js';

export const ACCENTS = [['', 'Padrão do tema'], ['#4f8cff', 'Azul'], ['#8b5cf6', 'Violeta'], ['#22c55e', 'Verde'], ['#f59e0b', 'Laranja'], ['#ec4899', 'Rosa'], ['#ef4444', 'Vermelho']];
const PREVIEW = { dark: ['#000', '#181818', '#fff'], light: ['#f6f6f4', '#e6e6e3', '#17171a'] };

export function themeCards(current, onPick) {
  const wrap = h('div', { class: 'themes', role: 'radiogroup', 'aria-label': t('Tema') });
  const paint = (v) => wrap.replaceChildren(...[['dark', 'Escuro'], ['light', 'Claro'], ['auto', 'Automático (segue o sistema)']].map(([id, label]) => {
    const cols = id === 'auto' ? [PREVIEW.dark[0], PREVIEW.dark[1], PREVIEW.light[0], PREVIEW.light[1]] : PREVIEW[id].concat(PREVIEW[id][0]);
    return h('button', { type: 'button', class: 'themecard' + (v === id ? ' on' : ''), role: 'radio', 'aria-checked': v === id ? 'true' : 'false', dataset: { theme: id }, onclick: () => { paint(id); onPick(id); } },
      h('div', { class: 'prev' }, cols.slice(0, id === 'auto' ? 4 : 3).map((c, i, a) => h('i', { style: { background: c, width: (100 / a.length) + '%' } }))), t(label));
  }));
  paint(current);
  return wrap;
}

export function accentSwatches(current, onPick) {
  const wrap = h('div', { class: 'swatches', role: 'radiogroup', 'aria-label': t('Cor de destaque') });
  const custom = h('input', { type: 'color', title: t('Outra cor'), value: /^#[0-9a-f]{6}$/i.test(current) ? current : '#4f8cff' });
  const paint = (v) => {
    wrap.replaceChildren(...ACCENTS.map(([c, label]) => h('button', { type: 'button', class: 'swatch' + (v === c ? ' on' : ''), title: t(label), role: 'radio', 'aria-checked': v === c ? 'true' : 'false', dataset: { accent: c },
      style: { background: c || 'linear-gradient(135deg,#fff 50%,#17171a 50%)' }, onclick: () => { paint(c); onPick(c); } })), custom);
    custom.classList.toggle('on', v && !ACCENTS.some(([c]) => c === v));
  };
  custom.addEventListener('input', () => { onPick(custom.value); });
  custom.addEventListener('change', () => paint(custom.value));
  paint(current);
  return wrap;
}
