// Paleta de comandos (Ctrl/⌘+K): vá a qualquer tela, abra um projeto ou rode uma ação digitando.
import { api } from './api.js';
import { t } from './i18n.js';
import { h, icon } from './ui.js';

const fold = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
let openEl = null;

// `host` fornece o que depende do resto do app: { nav, go, actions }
export async function openPalette(host) {
  if (openEl) { openEl.querySelector('input').focus(); return; }
  const back = document.activeElement;
  let items = host.items(), shown = [], sel = 0;
  const input = h('input', { type: 'text', placeholder: t('Buscar telas, projetos e ações…'), role: 'combobox', 'aria-expanded': 'true', 'aria-controls': 'palette-list', autocomplete: 'off', spellcheck: 'false' });
  const list = h('div', { class: 'palette-list', id: 'palette-list', role: 'listbox' });
  const box = h('div', { class: 'palette', role: 'dialog', 'aria-modal': 'true', 'aria-label': t('Paleta de comandos') }, input, list,
    h('div', { class: 'palette-foot' }, h('span', null, '↑↓ ', t('navegar')), h('span', null, 'Enter ', t('abrir')), h('span', null, 'Esc ', t('fechar'))));
  const bg = h('div', { class: 'palette-bg', onmousedown: (e) => { if (e.target === bg) close(); } }, box);
  openEl = bg;
  document.body.appendChild(bg);
  input.focus();

  function close() { bg.remove(); openEl = null; document.removeEventListener('keydown', onKey, true); if (back && back.focus && document.contains(back)) { try { back.focus(); } catch (e) { /* ok */ } } }
  function run(it) { close(); setTimeout(() => it.run(), 0); }
  function score(it, toks) {
    const hay = fold(it.label + ' ' + (it.hint || ''));
    if (!toks.every((k) => hay.includes(k))) return -1;
    const lab = fold(it.label);
    return (lab.startsWith(toks[0]) ? 3 : lab.includes(toks[0]) ? 2 : 1) + (it.rank || 0);
  }
  function paint() {
    const toks = fold(input.value).split(/\s+/).filter(Boolean);
    shown = (toks.length ? items.map((it) => [score(it, toks), it]).filter(([s]) => s >= 0).sort((a, b) => b[0] - a[0]).map(([, it]) => it) : items.slice()).slice(0, 40);
    sel = Math.min(sel, Math.max(0, shown.length - 1));
    let group = '';
    const rows = [];
    shown.forEach((it, i) => {
      if (it.group !== group) { group = it.group; rows.push(h('div', { class: 'palette-group' }, group)); }
      rows.push(h('div', { class: 'palette-item' + (i === sel ? ' on' : ''), id: 'pi-' + i, role: 'option', 'aria-selected': i === sel ? 'true' : 'false',
        onmousemove: () => { if (sel !== i) { sel = i; mark(); } }, onclick: () => run(it) },
      icon(it.icon || 'chev', 16), h('span', { class: 'grow' }, it.label), it.hint ? h('span', { class: 'dim small' }, it.hint) : null, it.keys ? h('span', { class: 'kbd' }, it.keys) : null));
    });
    list.replaceChildren(...(rows.length ? rows : [h('div', { class: 'palette-empty' }, t('Nada encontrado.'))]));
    mark();
  }
  function mark() {
    list.querySelectorAll('.palette-item').forEach((el, i) => { el.classList.toggle('on', i === sel); el.setAttribute('aria-selected', i === sel ? 'true' : 'false'); });
    const el = list.querySelector('#pi-' + sel);
    if (el) { input.setAttribute('aria-activedescendant', 'pi-' + sel); el.scrollIntoView({ block: 'nearest' }); }
  }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); sel = shown.length ? (sel + 1) % shown.length : 0; mark(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = shown.length ? (sel - 1 + shown.length) % shown.length : 0; mark(); }
    else if (e.key === 'Enter') { e.preventDefault(); if (shown[sel]) run(shown[sel]); }
    else if (e.key === 'Tab') { e.preventDefault(); input.focus(); }
  }
  document.addEventListener('keydown', onKey, true);
  input.addEventListener('input', () => { sel = 0; paint(); });
  paint();
  // o que você criou entra na busca assim que chega (as telas e ações já estão disponíveis)
  const projects = await api('/api/projects').catch(() => []);
  if (!openEl) return;
  items = items.concat(host.dataItems(projects));
  paint();
}
