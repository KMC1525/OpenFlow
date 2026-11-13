import { api } from './api.js';
import { setLang, t } from './i18n.js';
import { applyUi, ui } from './prefs.js';
import { installShell, maybeWelcome } from './shell.js';
import { h, icon } from './ui.js';

// Estado global compartilhado entre as telas
export const state = { settings: null, presets: [], hardware: {}, native: {}, version: '', home: '', ctx: {} };

// Telas da barra lateral: «Projetos» é a tela inicial (todos os projetos + barra de pesquisa).
export const NAV = [['projects', 'Projetos', 'canvas'], ['models', 'Modelos', 'cube'], ['settings', 'Configurações', 'config']];
const VIEWS = {
  projects: () => import('./views/projects.js'), project: () => import('./views/canvas_edit.js'),
  models: () => import('./views/models.js'), settings: () => import('./views/settings.js'),
};
const ALIASES = { config: 'settings', canvas: 'projects', library: 'models', main: 'projects' };   // endereços antigos/curtos

// Recarrega a página (uma vez por falha: sem laço se o problema continuar). Devolve true se recarregou.
function reloadPage(force) {
  try {
    const last = Number(sessionStorage.getItem('openflow.reload') || 0);
    if (!force && Date.now() - last < 30000) return false;
    sessionStorage.setItem('openflow.reload', String(Date.now()));
  } catch (e) { if (!force) return false; }
  location.reload();
  return true;
}

export function go(route, ctx) {
  route = ALIASES[route] || route;
  state.ctx = ctx || {};
  if (location.hash === '#/' + route) render(); else location.hash = '#/' + route;
}
export const openProject = (id) => { state.ctx = {}; location.hash = '#/project/' + id; };

export async function refreshState() {
  const s = await api('/api/state');
  // o servidor foi reiniciado numa versão nova com esta página aberta: os módulos da página (já carregados) não combinam mais com os do servidor
  if (state.version && s.version && s.version !== state.version) { if (reloadPage()) return s; }
  Object.assign(state, { settings: s.settings, presets: s.presets, hardware: s.hardware, native: s.native || {}, version: s.version, diskVersion: s.disk_version || '', home: s.home });
  setLang(state.settings.language);
  applyUi(state.settings.ui);  // aparência (tema, cor, escala…) vinda do servidor; o cache local já pintou a tela no primeiro quadro
  return s;
}
export async function saveSettings(patch) {
  state.settings = await api('/api/settings', { method: 'PUT', body: patch });
  setLang(state.settings.language);
  applyUi(state.settings.ui);
  renderSide();
  return state.settings;
}

function route() {
  const m = location.hash.match(/^#\/(\w+)/);
  const r = m ? (ALIASES[m[1]] || m[1]) : 'projects';
  return VIEWS[r] ? r : 'projects';
}

export function renderSide() {
  const side = document.getElementById('side');
  if (!side) return;
  const cur = route() === 'project' ? 'projects' : route();
  const collapsed = localStorage.getItem('openflow.side') === '1';
  side.classList.toggle('collapsed', collapsed);
  const gen = state.settings ? state.settings.active.generation : 'demo';
  const demo = gen === 'demo';
  const stale = state.diskVersion && state.diskVersion !== state.version;   // há uma versão mais nova instalada do que a que está rodando
  side.replaceChildren(
    h('a', { class: 'brand', href: '#/projects', title: 'OpenFlow', 'aria-label': t('OpenFlow — tela inicial'), onclick: () => { state.ctx = {}; } }, h('span', { class: 'logo' }, 'F'), h('span', { class: 'word' }, 'OpenFlow')),
    h('button', { class: 'searchbtn', type: 'button', title: t('Buscar (Ctrl+K)'), onclick: () => shell && shell.openPalette() }, icon('search', 16), h('span', null, t('Buscar…')), h('span', { class: 'kbd' }, 'Ctrl K')),
    h('nav', { 'aria-label': t('Telas') }, NAV.map(([id, label, ic]) => h('a', { class: 'item' + (cur === id ? ' active' : ''), href: '#/' + id, title: t(label), 'aria-current': cur === id ? 'page' : null, onclick: () => { state.ctx = {}; } },
      icon(ic, 19), h('span', { class: 'lbl' }, t(label))))),
    h('div', { class: 'foot' },
      h('div', { class: 'chipstat', role: 'button', tabindex: '0', title: t('Modelo de texto (IA)'), onclick: () => go('settings', { tab: 'providers' }), onkeydown: (e) => { if (e.key === 'Enter') go('settings', { tab: 'providers' }); } },
        h('span', { class: 'dot ' + (demo ? 'warn' : 'ok') }), h('span', { class: 't' }, presetLabel(gen))),
      stale ? h('div', { class: 'small t', style: { padding: '4px', color: 'var(--warn, #f5b942)' } }, t('Versão {v} instalada: feche o OpenFlow e abra de novo.', { v: state.diskVersion })) : null,
      h('div', { class: 'row', style: { justifyContent: 'space-between', padding: '0 4px' } },
        h('span', { class: 'dim small t' }, 'v' + state.version),
        h('button', { class: 'btn ghost icon sm', title: t('Recolher menu'), 'aria-label': t('Recolher menu'), onclick: () => { localStorage.setItem('openflow.side', collapsed ? '0' : '1'); renderSide(); } }, icon('panel', 16)))));
}
const presetLabel = (id) => { const p = state.presets.find((x) => x.id === id); return p ? t(p.label) : id; };

let renderToken = 0;
async function render() {
  const token = ++renderToken, r = route(), main = document.getElementById('main');
  document.title = 'OpenFlow — ' + t((NAV.find(([id]) => id === (r === 'project' ? 'projects' : r)) || [0, 'Projetos'])[1]);
  renderSide();
  main.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'spinner' })));
  let mod;
  try { mod = await VIEWS[r](); }
  catch (e) {
    // Não deu para carregar os arquivos da tela (ex.: o OpenFlow foi atualizado com esta página aberta e ela ficou com arquivos de outra versão).
    console.error(e);
    if (reloadPage()) return;
    if (token !== renderToken) return;
    main.replaceChildren(h('div', { class: 'page narrow' }, h('div', { class: 'errbox' },
      h('p', { style: { margin: '0 0 8px' } }, t('Não foi possível carregar esta tela. Isso costuma acontecer quando o OpenFlow é atualizado com a página aberta.')),
      h('p', { class: 'small', style: { margin: '0 0 12px' } }, t('Recarregue a página (Ctrl+F5). Se continuar, feche o OpenFlow, abra de novo com o comando flow e recarregue.')),
      h('p', { class: 'mono small dim', style: { margin: '0 0 12px' } }, String((e && e.message) || e)),
      h('button', { class: 'btn primary', onclick: () => reloadPage(true) }, t('Recarregar a página')))));
    return;
  }
  try {
    if (token !== renderToken) return;
    const root = h('div');
    main.replaceChildren(root);
    main.scrollTop = 0;
    const m = location.hash.match(/^#\/project\/([\w-]+)/);
    await (r === 'project' ? mod.default(root, state.ctx || {}, m ? m[1] : '') : mod.default(root, state.ctx || {}));
  } catch (e) {
    console.error(e);
    main.replaceChildren(h('div', { class: 'page narrow' }, h('div', { class: 'errbox' }, t('Algo deu errado:') + ' ' + (e.message || e))));
  }
}

let shell = null;
addEventListener('openflow:go', (e) => { if (e.detail && e.detail.route) go(e.detail.route, e.detail.ctx); });   // telas que não importam o main.js pedem navegação por evento
addEventListener('hashchange', () => { render(); });
(async () => {
  try { await refreshState(); } catch (e) { document.getElementById('main').replaceChildren(h('div', { class: 'page narrow' }, h('div', { class: 'errbox' }, e.message))); return; }
  const skip = document.querySelector('.skip');
  if (skip) { skip.textContent = t('Ir para o conteúdo'); skip.addEventListener('click', (e) => { e.preventDefault(); const m = document.getElementById('main'); if (m) m.focus(); }); }
  const app = { state, NAV, go, saveSettings, renderSide, refreshState, openProject };
  shell = installShell(app);
  render();
  maybeWelcome(app).catch((e) => console.error(e));
})();
window.OPENFLOW_WELCOME = () => maybeWelcome({ state, NAV, go, saveSettings, renderSide, refreshState }, true);
