import { api } from '../api.js';
import { t } from '../i18n.js';
import { openProject, state } from '../main.js';
import { SORTS, TPL_LABEL } from '../labels.js';
import { confirmDialog, debounce, fill, fmtDate, h, icon, modal, popover, toast } from '../ui.js';

// Tela inicial do OpenFlow: todos os projetos, com barra de pesquisa (nome, descrição e textos dos nós), ordenação e criação.
const SORT_KEY = 'openflow.pj.sort';

export default async function render(root, ctx) {
  let sort = 'updated';
  try { sort = SORTS.some(([v]) => v === localStorage.getItem(SORT_KEY)) ? localStorage.getItem(SORT_KEY) : 'updated'; } catch (e) { /* ok */ }
  let list = [], total = 0, query = '', seq = 0;
  const grid = h('div', { class: 'cv-grid', role: 'list', 'aria-label': t('Projetos') });
  const status = h('p', { class: 'muted small pj-status', role: 'status', 'aria-live': 'polite' });
  const empty = h('div', { class: 'empty' });

  async function create(opts = {}) {
    const meta = await api('/api/project-templates');
    let tpl = opts.template || (state.settings.canvas && state.settings.canvas.template) || 'text_image';
    const name = h('input', { placeholder: t('Nome do projeto'), 'aria-label': t('Nome do projeto'), id: 'pj-new-name', value: opts.name || '' });
    const prompt = h('textarea', { placeholder: t('Ideia inicial (opcional): ela vira o primeiro prompt do modelo.'), 'aria-label': t('Ideia inicial'), rows: 2, style: { minHeight: '60px' } });
    const tpls = h('div', { class: 'cv-tpls', role: 'radiogroup', 'aria-label': t('Modelo inicial') });
    const paint = () => fill(tpls, meta.templates.map((x) => h('button', { type: 'button', role: 'radio', 'aria-checked': x.id === tpl ? 'true' : 'false', class: 'cv-tpl' + (x.id === tpl ? ' on' : ''), onclick: () => { tpl = x.id; paint(); } },
      h('b', null, t((TPL_LABEL[x.id] || [x.label])[0])), h('span', null, t((TPL_LABEL[x.id] || [0, x.hint])[1])))));
    paint();
    const ok = await modal(t('Novo projeto'), h('div', null, h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Um projeto é um fluxo de nós para gerar e editar imagens, vídeos, sons e vozes. Crie um para cada ideia.')), name, tpls, prompt),
      [{ label: t('Cancelar'), value: false }, { label: t('Criar'), value: true, cls: 'primary' }]);
    if (!ok) return;
    try { const c = await api('/api/projects', { method: 'POST', body: { name: name.value.trim(), template: tpl, prompt: prompt.value.trim() } }); openProject(c.id); }
    catch (e) { toast(e.message, 'err'); }
  }

  async function load() {
    const my = ++seq;
    try {
      const r = await api('/api/projects?sort=' + sort + (query ? '&q=' + encodeURIComponent(query) : ''));
      if (my !== seq) return;   // chegou uma resposta mais nova (digitou mais uma letra): ignora a antiga
      list = r;
      if (!query) total = r.length;
      else if (!total) total = (await api('/api/projects')).length;
    } catch (e) { if (my === seq) toast(e.message, 'err'); return; }
    paint();
  }
  const reload = () => load();

  function menu(anchor, c) {
    const item = (label, ic, fn, cls) => h('button', { type: 'button', class: 'opt ' + (cls || ''), role: 'menuitem', onclick: () => { pop.close(); fn(); } }, icon(ic, 15), label);
    const pop = popover(anchor, h('div', { role: 'menu' },
      item(t('Abrir'), 'canvas', () => openProject(c.id)),
      item(t('Renomear'), 'edit', async () => {
        const inp = h('input', { value: c.name, 'aria-label': t('Nome do projeto') });
        const ok = await modal(t('Renomear projeto'), inp, [{ label: t('Cancelar'), value: false }, { label: t('Salvar'), value: true, cls: 'primary' }]);
        if (ok && inp.value.trim()) { await api(`/api/projects/${c.id}/meta`, { method: 'POST', body: { name: inp.value } }); reload(); }
      }),
      item(t('Duplicar'), 'copy', async () => { await api(`/api/projects/${c.id}/duplicate`, { method: 'POST' }); toast(t('Duplicado')); reload(); }),
      h('a', { class: 'opt', role: 'menuitem', href: `/api/projects/${c.id}/download` }, icon('download', 15), t('Baixar (.zip)')),
      item(t('Apagar'), 'trash', async () => {
        if (!(await confirmDialog(t('Apagar o projeto “{n}” e todos os arquivos dele?', { n: c.name })))) return;
        try { await api('/api/projects/' + c.id, { method: 'DELETE' }); toast(t('Apagado')); reload(); } catch (e) { toast(e.message, 'err'); }
      }, 'danger')));
  }

  // trecho do nome com a pesquisa em destaque
  function mark(textValue) {
    const tokens = fold(query).split(/\s+/).filter(Boolean);
    if (!tokens.length) return textValue;
    const f = fold(textValue);
    const spans = [];
    tokens.forEach((tk) => { let i = f.indexOf(tk); while (i >= 0) { spans.push([i, i + tk.length]); i = f.indexOf(tk, i + tk.length); } });
    if (!spans.length) return textValue;
    spans.sort((a, b) => a[0] - b[0]);
    const merged = [spans[0].slice()];
    spans.slice(1).forEach((s) => { const l = merged[merged.length - 1]; if (s[0] <= l[1]) l[1] = Math.max(l[1], s[1]); else merged.push(s.slice()); });
    const out = []; let at = 0;
    merged.forEach(([a, b]) => { if (a > at) out.push(textValue.slice(at, a)); out.push(h('mark', null, textValue.slice(a, b))); at = b; });
    if (at < textValue.length) out.push(textValue.slice(at));
    return out;
  }
  // a pesquisa ignora acentos; o texto exibido mantém o comprimento (NFD só em letras simples)
  function fold(s) { return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }

  function paint() {
    fill(grid, list.map((c) => h('div', { class: 'cv-card', role: 'listitem' },
      h('a', { class: 'cv-open', href: '#/project/' + c.id, 'aria-label': t('Abrir o projeto {n}', { n: c.name }), onclick: () => { state.ctx = {}; } },
        h('div', { class: 'th', style: c.thumb ? { backgroundImage: `url("${c.thumb}")` } : {} }, c.thumb ? null : icon('canvas', 34)),
        h('div', { class: 'inf' }, h('div', { class: 'nm', title: c.name }, mark(c.name === 'Novo projeto' || c.name === 'Novo projeto' ? t('Novo projeto') : c.name)),
          c.match ? h('div', { class: 'mt match' }, t('Achado em:') + ' ', h('em', null, mark(c.match))) : null,
          h('div', { class: 'mt' }, t('{n} nós · {m} arquivos', { n: c.nodes, m: c.assets }) + ' · ' + fmtDate(c.updated)))),
      h('button', { class: 'btn icon sm mn', type: 'button', title: t('Mais'), 'aria-label': t('Mais ações para {n}', { n: c.name }), 'aria-haspopup': 'menu', onclick: (e) => { e.stopPropagation(); menu(e.currentTarget, c); } }, icon('more', 15)))));
    const none = !list.length;
    grid.classList.toggle('hidden', none);
    empty.classList.toggle('hidden', !none);
    if (none) {
      if (query) fill(empty, h('h3', null, t('Nenhum projeto encontrado para “{q}”', { q: query })), h('p', null, t('A pesquisa olha o nome, a descrição e os textos dos nós (prompts, falas, títulos e pastas de estilo).')),
        h('div', { class: 'row', style: { justifyContent: 'center' } }, h('button', { class: 'btn', type: 'button', onclick: () => { input.value = ''; query = ''; input.focus(); load(); } }, t('Limpar pesquisa')),
          h('button', { class: 'btn primary', type: 'button', onclick: () => create({ name: query }) }, icon('plus', 14), t('Criar um projeto chamado “{q}”', { q: query }))));
      else fill(empty, h('h3', null, t('Crie seu primeiro projeto')), h('p', null, t('Ligue nós de texto, imagem, vídeo, som e voz — e monte tudo no Editor de vídeo. Estilos valem para o projeto inteiro.')),
        h('button', { class: 'btn primary', type: 'button', onclick: () => create() }, icon('plus', 14), t('Novo projeto')));
    }
    status.textContent = query ? (list.length ? t('{n} de {m} projetos', { n: list.length, m: total }) : t('Nenhum projeto encontrado.')) : (total ? t('{n} projetos', { n: total }) : '');
  }

  const importIn = h('input', { type: 'file', accept: '.zip,application/zip', class: 'hidden', id: 'pj-import-file', 'aria-label': t('Importar projeto (.zip)'), onchange: async (e) => {
    const f = e.target.files[0]; e.target.value = '';
    if (!f) return;
    try { const c = await api('/api/projects/import', { method: 'POST', body: f, raw: true, headers: { 'Content-Type': 'application/zip' } }); toast(t('Projeto importado'), 'ok'); openProject(c.id); } catch (err) { toast(err.message, 'err'); }
  } });
  const input = h('input', { type: 'search', id: 'pj-search', placeholder: t('Pesquisar projetos…'), 'aria-label': t('Pesquisar projetos'), autocomplete: 'off', spellcheck: 'false',
    oninput: debounce(() => { query = input.value.trim(); load(); }, 180),
    onkeydown: (e) => { if (e.key === 'Escape' && input.value) { e.preventDefault(); input.value = ''; query = ''; load(); } else if (e.key === 'Enter') { e.preventDefault(); query = input.value.trim(); load(); } } });
  const sortSel = h('select', { id: 'pj-sort', 'aria-label': t('Ordenar por'), onchange: (e) => { sort = e.target.value; try { localStorage.setItem(SORT_KEY, sort); } catch (x) { /* ok */ } load(); } },
    SORTS.map(([v, l]) => h('option', { value: v, selected: v === sort }, t(l))));

  fill(root, h('div', { class: 'page cv-pg' },
    h('div', { class: 'page-h' }, h('div', null, h('h1', null, t('Projetos')), h('p', null, t('Todos os seus fluxos de criação: imagens, vídeos, sons e vozes com modelos de empresas (API) ou locais.'))),
      h('div', { class: 'row' }, h('button', { class: 'btn', type: 'button', id: 'pj-import', onclick: () => importIn.click() }, icon('upload', 14), t('Importar projeto (.zip)')), importIn, h('button', { class: 'btn primary', type: 'button', id: 'pj-new', onclick: () => create() }, icon('plus', 14), t('Novo projeto')))),
    h('form', { class: 'pj-bar', role: 'search', onsubmit: (e) => e.preventDefault() },
      h('div', { class: 'search' }, icon('search', 17), input, h('span', { class: 'kbd', 'aria-hidden': 'true' }, '/')), h('label', { class: 'pj-sort' }, h('span', { class: 'dim small' }, t('Ordenar por')), sortSel)),
    status, grid, empty));
  await load();
  if (ctx && ctx.create) { state.ctx = {}; create(); }
}
