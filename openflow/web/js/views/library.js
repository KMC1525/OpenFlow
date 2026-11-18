import { api, events } from '../api.js';
import { t } from '../i18n.js';
import { saveSettings } from '../main.js';
import { checkbox, confirmDialog, debounce, fmtBytes, fmtDate, fmtEta, h, icon, modal, toast } from '../ui.js';
import { GGUF_KINDS } from '../model_labels.js';

const TIERS = [['Q8', 8], ['Q6', 6], ['Q4', 4], ['Q3', 3], ['Q2', 2]];   // as cinco faixas (v0.81); só dá para criar uma faixa com MENOS bits que o arquivo

// Biblioteca (v0.27), no estilo do Google Drive: pastas e subpastas (virtuais: nada muda no disco) para modelos de IA e arquivos gerados, busca em todas as pastas, arrastar e soltar para organizar,
// a lista de downloads e o catálogo para baixar mais modelos. No canvas, a aba «Biblioteca» do painel da direita arrasta os arquivos para o fluxo.
const LS = (k, v) => { try { if (v === undefined) return localStorage.getItem('openflow.lib.' + k); localStorage.setItem('openflow.lib.' + k, v); } catch (e) { return null; } return null; };
const DRAG = 'application/x-openflow-library';

export default async function render(root, ctx) {
  const S = { scope: (ctx && ctx.tab === 'downloads') ? 'downloads' : (ctx && ctx.tab === 'files') ? 'files' : 'models', folder: '', q: '', view: LS('view') === 'list' ? 'list' : 'grid', kind: '', source: 'all', tree: [] };
  let stop = () => {};
  const main = h('div', { class: 'lib-main', id: 'lib-body' });
  const side = h('nav', { class: 'lib-side', 'aria-label': t('Seções da Biblioteca') });
  const bar = h('div', { class: 'lib-bar' });
  let seq = 0;

  const pass = (e) => e.stopPropagation();
  async function call(path, opts) { try { return await api(path, opts); } catch (e) { toast(e.message, 'err'); throw e; } }

  // ---------------------------------------------------------------------------------------------- navegação
  async function go(next) { Object.assign(S, next); LS('scope', S.scope); await show(); }

  const search = h('input', { type: 'search', id: 'lib-q', 'aria-label': t('Buscar pastas e arquivos'), placeholder: t('Buscar pastas e arquivos…'), autocomplete: 'off',
    oninput: debounce(() => { S.q = search.value.trim(); if (S.scope === 'downloads' || S.scope === 'storage') { S.scope = 'files'; show(); } else loadItems(); }, 250) });

  function paintSide() {
    const sec = [['models', 'Modelos de IA', 'layers'], ['files', 'Arquivos gerados', 'image'], ['downloads', 'Downloads', 'download'], ['storage', 'Armazenamento', 'archive']];
    const nodes = [];
    for (const [k, label, ic] of sec) {
      const on = S.scope === k;
      nodes.push(h('button', { type: 'button', class: 'lib-sec' + (on && !S.folder ? ' on' : ''), id: 'lib-tab-' + k, 'data-scope': k, 'aria-current': on ? 'page' : null,
        onclick: () => { S.q = ''; search.value = ''; go({ scope: k, folder: '' }); },
        ondragover: (e) => { if (k !== 'downloads' && k !== 'storage' && e.dataTransfer.types.includes(DRAG)) { e.preventDefault(); e.currentTarget.classList.add('drop'); } },
        ondragleave: (e) => e.currentTarget.classList.remove('drop'),
        ondrop: (e) => { e.currentTarget.classList.remove('drop'); if (k !== 'downloads' && k !== 'storage') dropOn(e, ''); } }, icon(ic, 16), h('span', null, t(label))));
      if (k === S.scope && k !== 'downloads' && k !== 'storage') nodes.push(treeNode('', 0));
    }
    side.replaceChildren(...nodes);
  }
  function treeNode(parent, depth) {
    const kids = S.tree.filter((f) => (f.parent || '') === parent).sort((a, b) => a.name.localeCompare(b.name));
    return h('div', { class: 'lib-tree' }, kids.map((f) => h('div', null,
      h('button', { type: 'button', class: 'lib-fold' + (S.folder === f.id ? ' on' : ''), style: { paddingLeft: (10 + depth * 14) + 'px' }, 'data-folder': f.id, onclick: () => { S.q = ''; search.value = ''; go({ folder: f.id }); },
        ondragover: (e) => { if (e.dataTransfer.types.includes(DRAG)) { e.preventDefault(); e.currentTarget.classList.add('drop'); } }, ondragleave: (e) => e.currentTarget.classList.remove('drop'),
        ondrop: (e) => { e.currentTarget.classList.remove('drop'); dropOn(e, f.id); } }, icon('folder', 14), h('span', null, f.name)),
      treeNode(f.id, depth + 1))));
  }

  // ---------------------------------------------------------------------------------------------- arrastar e soltar
  async function dropOn(e, folderId) {
    const raw = e.dataTransfer.getData(DRAG);
    if (!raw) return;
    e.preventDefault(); e.stopPropagation();
    let d; try { d = JSON.parse(raw); } catch (er) { return; }
    try {
      for (const fid of d.folders || []) if (fid !== folderId) await api('/api/library/folders/' + fid, { method: 'PUT', body: { parent: folderId } });
      if ((d.keys || []).length) await api('/api/library/move', { method: 'POST', body: { items: d.keys, folder: folderId } });
      await show();
    } catch (er) { toast(er.message, 'err'); }
  }
  const dragStart = (payload) => (e) => { e.dataTransfer.setData(DRAG, JSON.stringify(payload)); e.dataTransfer.effectAllowed = 'move'; };
  const dropTarget = (folderId) => ({ ondragover: (e) => { if (e.dataTransfer.types.includes(DRAG)) { e.preventDefault(); e.currentTarget.classList.add('drop'); } }, ondragleave: (e) => e.currentTarget.classList.remove('drop'),
    ondrop: (e) => { e.currentTarget.classList.remove('drop'); dropOn(e, folderId); } });

  // ---------------------------------------------------------------------------------------------- ações de pasta e de item
  async function askName(title, value) {
    const inp = h('input', { type: 'text', id: 'lib-name', value: value || '', maxlength: 80, style: { width: '100%' }, onkeydown: (e) => { if (e.key === 'Enter') e.target.closest('.modal').querySelector('.btn.primary').click(); } });
    const v = await modal(title, inp, [{ label: t('Cancelar'), value: null }, { label: t('Salvar'), value: 'ok', cls: 'primary' }]);
    return v === 'ok' ? inp.value.trim() : '';
  }
  async function newFolder() {
    const name = await askName(t('Nova pasta'), '');
    if (!name) return;
    try { await api('/api/library/folders', { method: 'POST', body: { name, parent: S.folder, scope: S.scope } }); await show(); } catch (e) { toast(e.message, 'err'); }
  }
  async function renameFolder(f) {
    const name = await askName(t('Renomear'), f.name);
    if (!name || name === f.name) return;
    try { await api('/api/library/folders/' + f.id, { method: 'PUT', body: { name } }); await show(); } catch (e) { toast(e.message, 'err'); }
  }
  async function deleteFolder(f) {
    if (!(await confirmDialog(t('Excluir a pasta «{n}»? Nada é apagado do disco: o que está dentro sobe para a pasta de cima.', { n: f.name })))) return;
    try { await api('/api/library/folders/' + f.id, { method: 'DELETE' }); if (S.folder === f.id) S.folder = f.parent || ''; await show(); } catch (e) { toast(e.message, 'err'); }
  }
  async function moveDialog(keys, folders) {
    let chosen = null;
    const list = h('div', { class: 'lib-pick' });
    const paint = () => {
      const row = (id, name, depth) => h('button', { type: 'button', class: 'lib-fold' + (chosen === id ? ' on' : ''), style: { paddingLeft: (10 + depth * 14) + 'px', width: '100%' }, onclick: () => { chosen = id; paint(); } }, icon(id ? 'folder' : 'library', 14), h('span', null, name));
      const walk = (parent, depth) => S.tree.filter((f) => (f.parent || '') === parent && !(folders || []).includes(f.id)).sort((a, b) => a.name.localeCompare(b.name)).flatMap((f) => [row(f.id, f.name, depth), ...walk(f.id, depth + 1)]);
      list.replaceChildren(row('', t(S.scope === 'models' ? 'Todos os modelos' : 'Todos os arquivos'), 0), ...walk('', 1));
    };
    paint();
    const v = await modal(t('Mover para…'), list, [{ label: t('Cancelar'), value: null }, { label: t('Mover'), value: 'ok', cls: 'primary' }]);
    if (v !== 'ok' || chosen === null) return;
    try {
      for (const fid of folders || []) await api('/api/library/folders/' + fid, { method: 'PUT', body: { parent: chosen } });
      if ((keys || []).length) await api('/api/library/move', { method: 'POST', body: { items: keys, folder: chosen } });
      await show();
    } catch (e) { toast(e.message, 'err'); }
  }

  // ---------------------------------------------------------------------------------------------- conteúdo
  const content = h('div', { class: 'lib-content', 'aria-live': 'polite' });
  const crumbs = h('div', { class: 'lib-crumbs' });
  const filters = h('div', { class: 'lib-filters' });

  function paintBar() {
    const rootName = S.scope === 'models' ? t('Todos os modelos') : t('Todos os arquivos');
    crumbs.replaceChildren();
    if (S.scope === 'downloads') { crumbs.append(h('b', null, t('Downloads'))); }
    else if (S.scope === 'storage') { crumbs.append(h('b', null, t('Armazenamento'))); }
    else if (S.q) { crumbs.append(h('b', null, t('Resultados para «{q}»', { q: S.q }))); }
    else {
      crumbs.append(h('button', { type: 'button', class: 'lib-crumb', ...dropTarget(''), onclick: () => go({ folder: '' }) }, rootName));
      (S.path || []).forEach((p) => crumbs.append(h('span', { class: 'sep' }, '›'), h('button', { type: 'button', class: 'lib-crumb', ...dropTarget(p.id), onclick: () => go({ folder: p.id }) }, p.name)));
    }
    const kinds = S.scope === 'models' ? [['', 'Todos os tipos'], ...GGUF_KINDS.map(([k, l]) => [k, l])] : [['', 'Todos os tipos'], ['image', 'Imagens'], ['video', 'Vídeos'], ['audio', 'Sons'], ['model3d', 'Modelos 3D']];
    filters.replaceChildren();
    if ((S.scope === 'models' || S.scope === 'files')) {
      filters.append(h('select', { id: 'lib-kind', 'aria-label': t('Tipo de arquivo'), onchange: (e) => { S.kind = e.target.value; loadItems(); } }, kinds.map(([v, l]) => h('option', { value: v, selected: v === S.kind }, t(l)))));
      if (S.scope === 'files') filters.append(h('select', { id: 'lib-source', 'aria-label': t('Origem'), onchange: (e) => { S.source = e.target.value; loadItems(); } },
        [['all', 'Todos'], ['generated', 'Gerados por modelos'], ['upload', 'Enviados por você']].map(([v, l]) => h('option', { value: v, selected: v === S.source }, t(l)))));
    }
    const can = (S.scope === 'models' || S.scope === 'files') && !S.q;
    bar.replaceChildren(
      h('div', { class: 'lib-search' }, icon('search', 16), search),
      h('div', { class: 'grow' }),
      can ? h('button', { class: 'btn', type: 'button', id: 'lib-newfolder', onclick: newFolder }, icon('plus', 14), t('Nova pasta')) : null,
      (S.scope === 'models' || S.scope === 'files') ? h('div', { class: 'seg', role: 'group', 'aria-label': t('Visualização') },
        h('button', { type: 'button', class: S.view === 'grid' ? 'on' : '', id: 'lib-grid', title: t('Grade'), 'aria-label': t('Grade'), onclick: () => { S.view = 'grid'; LS('view', 'grid'); paintBar(); paintItems(); } }, icon('grid', 15)),
        h('button', { type: 'button', class: S.view === 'list' ? 'on' : '', id: 'lib-list', title: t('Lista'), 'aria-label': t('Lista'), onclick: () => { S.view = 'list'; LS('view', 'list'); paintBar(); paintItems(); } }, icon('rowsmall', 15))) : null);
  }

  let data = { folders: [], items: [], path: [], search: false };
  async function loadItems() {
    const my = ++seq;
    try {
      const r = await api('/api/library/items?scope=' + S.scope + '&folder=' + encodeURIComponent(S.folder) + '&q=' + encodeURIComponent(S.q) + '&kind=' + S.kind + '&source=' + S.source);
      if (my !== seq) return;
      data = r; S.path = r.path || []; if (r.tree) S.tree = r.tree;
      paintSide(); paintBar(); paintItems();
    } catch (e) {
      if (my !== seq) return;
      if (e.status === 404 && S.folder) { S.folder = ''; return loadItems(); }   // a pasta foi apagada em outra aba
      content.replaceChildren(h('div', { class: 'res err', role: 'alert' }, e.message));
    }
  }

  const menu = (items) => {
    const wrap = h('div', { class: 'lib-menu', onclick: pass, ondragstart: (e) => e.preventDefault(), draggable: 'false' });
    const pop = h('div', { class: 'lib-pop hidden', role: 'menu' }, items.filter(Boolean).map(([label, fn, cls]) => h('button', { type: 'button', role: 'menuitem', class: cls || '', onclick: (e) => { e.stopPropagation(); pop.classList.add('hidden'); fn(); } }, label)));
    const btn = h('button', { type: 'button', class: 'btn sm ghost', title: t('Mais ações'), 'aria-label': t('Mais ações'), 'aria-haspopup': 'menu', onclick: (e) => {
      e.stopPropagation(); const open = pop.classList.contains('hidden'); document.querySelectorAll('.lib-pop').forEach((p) => p.classList.add('hidden')); pop.classList.toggle('hidden', !open);
      if (open) setTimeout(() => document.addEventListener('click', () => pop.classList.add('hidden'), { once: true }), 0);
    } }, icon('more', 15));
    wrap.append(btn, pop);
    return wrap;
  };

  const folderCard = (f) => h('div', { class: 'lib-card folder', 'data-folder': f.id, draggable: 'true', title: f.path ? f.path : f.name, ondragstart: dragStart({ folders: [f.id] }), ...dropTarget(f.id), ondblclick: () => open(f), onclick: () => open(f) },
    icon('folder', S.view === 'grid' ? 30 : 18),
    h('div', { class: 'meta' }, h('div', { class: 'nm' }, f.name), h('div', { class: 'dim small' }, f.path ? t('em {p}', { p: f.path }) : t('{n} item(ns)', { n: f.count || 0 }))),
    menu([[t('Abrir'), () => open(f)], [t('Renomear'), () => renameFolder(f)], [t('Mover para…'), () => moveDialog([], [f.id])], [t('Excluir pasta'), () => deleteFolder(f), 'danger']]));
  const open = (f) => { S.q = ''; search.value = ''; go({ folder: f.id }); };

  const thumb = (f) => f.kind === 'image' ? h('img', { src: f.url, alt: f.name, loading: 'lazy', draggable: 'false' })
    : f.kind === 'video' ? h('video', { src: f.url, preload: 'metadata', muted: true, 'aria-label': f.name }) : h('div', { class: 'ico' }, icon(f.kind === 'model3d' ? 'cube' : 'audio', 30));

  function fileCard(f) {
    return h('div', { class: 'lib-card file', 'data-asset': f.id, draggable: 'true', ondragstart: dragStart({ keys: [f.key] }) },
      h('a', { class: 'th', href: f.url, target: '_blank', rel: 'noopener', title: t('Abrir {n}', { n: f.name }), draggable: 'false' }, thumb(f)),
      h('div', { class: 'meta' }, h('div', { class: 'nm', title: f.name }, f.name),
        h('div', { class: 'dim small' }, [f.model || f.provider, fmtBytes(f.bytes), f.w ? f.w + '×' + f.h : '', f.duration ? Math.round(f.duration) + ' s' : ''].filter(Boolean).join(' · ')),
        h('a', { class: 'small', href: '#/project/' + f.project, title: t('Abrir o projeto'), draggable: 'false' }, f.project_name), f.path ? h('div', { class: 'dim small' }, t('em {p}', { p: f.path })) : null),
      menu([[t('Mover para…'), () => moveDialog([f.key], [])], [t('Baixar'), () => { const a = h('a', { href: f.url + '?download=1', download: f.name }); document.body.append(a); a.click(); a.remove(); }],
        [t('Apagar'), async () => {
          if (!(await confirmDialog(t('Apagar o arquivo {n}? Ele some do projeto «{p}» também.', { n: f.name, p: f.project_name })))) return;
          try { await api('/api/projects/' + f.project + '/assets/' + f.id, { method: 'DELETE' }); loadItems(); } catch (e) { toast(e.message, 'err'); }
        }, 'danger']]));
  }

  function modelCard(m) {
    const kindLabel = t((GGUF_KINDS.find(([x]) => x === m.kind) || [0, m.kind])[1]);
    const useIt = async () => {
      try {
        if (m.kind === 'text') { await saveSettings({ providers: { local_hf: { model: m.name } }, active: { generation: 'local_hf' } }); toast(t('Usando como modelo de texto'), 'ok'); }
        else { await saveSettings({ media: { models: { gguf_local: { [m.kind]: m.name } }, active: { [m.kind]: 'gguf_local' } } }); toast(m.kind === 'image' ? t('Usando para imagens') : t('Usando para vídeos'), 'ok'); }
      } catch (e) { toast(e.message, 'err'); }
    };
    // v0.81: cria no disco uma faixa menor (Q2…Q8) a partir deste arquivo (sd-cli / llama.cpp, em segundo plano)
    const makeTier = async (q) => {
      let jid; try { jid = (await api('/api/hf/requant', { method: 'POST', body: { kind: m.kind, name: m.name, tier: q } })).job_id; } catch (e) { return toast(e.status === 409 ? t('Já há uma faixa sendo criada: espere ela terminar.') : e.message, 'err'); }
      toast(t('Criando {f}…', { f: m.name + ' → ' + q }));
      events('/api/jobs/' + jid + '/events', (ev) => {
        if (ev.type === 'done') { toast(t('Faixa criada: {f}', { f: ev.name }), 'ok'); loadItems(); }
        else if (ev.type === 'error') toast(ev.message, 'err');
        else if (ev.type === 'cancelled') toast(t('Criar faixa cancelado'));
      });
    };
    const lower = ['text', 'image', 'video'].includes(m.kind) && m.parts <= 1 && m.bits ? TIERS.filter(([, b]) => b < m.bits) : [];
    return h('div', { class: 'lib-card model', 'data-model': m.name, draggable: 'true', ondragstart: dragStart({ keys: [m.key] }) },
      h('div', { class: 'th ico' }, icon(m.kind === 'text' ? 'type' : m.kind === 'image' ? 'image' : m.kind === 'video' ? 'video' : 'audio', 30)),
      h('div', { class: 'meta' }, h('div', { class: 'nm mono', title: m.name }, m.name),
        h('div', { class: 'dim small' }, [kindLabel, fmtBytes(m.size), m.parts > 1 ? t('{n} partes', { n: m.parts }) : ''].filter(Boolean).join(' · ')), m.quant ? h('span', { class: 'chip solid' }, m.quant) : null,
        m.path ? h('div', { class: 'dim small' }, t('em {p}', { p: m.path })) : null),
      menu([m.kind === 'text' || m.kind === 'image' || m.kind === 'video' ? [t('Usar'), useIt] : null, [t('Mover para…'), () => moveDialog([m.key], [])],
        ...lower.map(([q]) => [t('Criar faixa {q}', { q }), () => makeTier(q)]),
        [t('Apagar'), async () => {
          if (!(await confirmDialog(t('Apagar o arquivo {n}?', { n: m.name })))) return;
          try { await api('/api/hf/local/' + encodeURIComponent(m.name) + '?kind=' + m.kind, { method: 'DELETE' }); loadItems(); } catch (e) { toast(e.message, 'err'); }
        }, 'danger']]));
  }

  // v0.89: codificadores de texto e VAEs baixados, com a faixa de cada um; escolha uma faixa menor e o OpenFlow baixa a pronta (se o repositório tem) ou a cria a partir do arquivo
  function supportCard() {
    const body = h('div', { class: 'col', id: 'lib-support-list' });
    const card = h('div', { class: 'card', id: 'lib-support', style: { marginTop: '18px' } }, h('h3', { role: 'heading', 'aria-level': '2' }, t('Codificadores de texto e VAEs')),
      h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Os arquivos de apoio dos modelos de imagem e vídeo. Obtenha uma faixa menor (Q2…Q8) para gastar menos memória; depois escolha a faixa no nó, em «Faixa dos arquivos de apoio». Num VAE quase nada é quantizável: o arquivo mal encolhe.')), body);
    const paint = async () => {
      if (S.support) draw(S.support);   // a lista aparece na hora quando a Biblioteca se redesenha (sem piscar), e a resposta nova a atualiza
      let r; try { r = await api('/api/models/support/files'); } catch (e) { if (!S.support) body.replaceChildren(h('div', { class: 'errbox' }, e.message)); return; }
      S.support = r; draw(r);
    };
    const draw = (r) => {
      if (!r.files.length) { body.replaceChildren(h('div', { class: 'dim small', id: 'lib-support-empty' }, t('Nenhum codificador de texto nem VAE baixado ainda: eles chegam junto dos modelos (botão «Baixar os arquivos de apoio» do nó).'))); return; }
      body.replaceChildren(...r.files.map((f) => {
        const tierSel = h('select', { 'aria-label': t('Faixa'), dataset: { f: f.name } }, f.lower.map((q) => h('option', { value: q }, q)));
        const howSel = h('select', { 'aria-label': t('Como obter') }, [['auto', t('Baixar a pronta ou criar')], ['download', t('Só baixar a pronta')], ['create', t('Só criar deste arquivo')]].map(([v, l]) => h('option', { value: v }, l)));
        const getBtn = h('button', { class: 'btn sm', type: 'button', dataset: { act: 'support-tier' }, onclick: async () => {
          let jid; try { jid = (await api('/api/models/support/tier', { method: 'POST', body: { kind: f.kind, name: f.name, tier: tierSel.value, how: howSel.value } })).job_id; } catch (e) { return toast(e.status === 409 ? t('Já há uma faixa de arquivo de apoio sendo obtida: espere ela terminar.') : e.message, 'err'); }
          getBtn.disabled = true; toast(t('Obtendo {f}…', { f: f.name + ' → ' + tierSel.value }));
          events('/api/jobs/' + jid + '/events', (ev) => {
            if (ev.type === 'done') { toast(t('Faixa pronta: {f}', { f: ev.name }), 'ok'); paint(); }
            else if (ev.type === 'error') { toast(ev.message, 'err'); getBtn.disabled = false; }
            else if (ev.type === 'cancelled') { toast(t('Cancelado')); getBtn.disabled = false; }
          });
        } }, icon('download', 13), t('Obter faixa'));
        return h('div', { class: 'row nw', dataset: { support: f.name }, style: { gap: '8px', flexWrap: 'wrap', alignItems: 'center' } },
          h('div', { class: 'grow', style: { minWidth: 0 } }, h('div', { class: 'mono', style: { fontSize: '13px', overflowWrap: 'anywhere' } }, f.name),
            h('div', { class: 'dim small' }, [t(f.role_label), f.kind === 'video' ? t('Vídeo') : t('Imagem'), fmtBytes(f.size), f.quant || (f.bits ? 'fp' + f.bits : '')].filter(Boolean).join(' · '))),
          f.have.map((q) => h('span', { class: 'chip on', title: t('Faixa já instalada') }, q)),
          f.lower.length ? [tierSel, howSel, getBtn] : h('span', { class: 'dim small' }, t('(nada menor para obter)')));
      }));
    };
    paint();
    return card;
  }

  function emptyText() {
    if (data.search) return t('Nada encontrado para «{q}».', { q: S.q });
    if (S.folder) return t('Esta pasta está vazia. Arraste itens para cá ou crie uma subpasta.');
    return S.scope === 'models' ? t('Nenhum modelo baixado ainda. Para pesquisar e baixar modelos, abra um projeto e use a barra de pesquisa de modelos do Canvas.') : t('Nenhum arquivo ainda. Rode um nó de imagem, vídeo, som ou voz num projeto.');
  }

  function paintItems() {
    const folders = data.folders || [], items = data.items || [];
    content.className = 'lib-content ' + (S.view === 'list' ? 'list' : 'grid');
    content.replaceChildren(
      ...(folders.length ? [h('h4', { class: 'lib-h' }, t('Pastas')), h('div', { class: 'lib-grid', id: 'lib-folders' }, folders.map(folderCard))] : []),
      ...(items.length ? [h('h4', { class: 'lib-h' }, S.scope === 'models' ? t('Modelos') : t('Arquivos')), h('div', { class: 'lib-grid', id: 'lib-items' }, items.map((i) => S.scope === 'models' ? modelCard(i) : fileCard(i)))] : []),
      !folders.length && !items.length ? h('div', { class: 'lib-empty muted' }, emptyText()) : null,
      S.scope === 'models' && !S.folder && !S.q ? supportCard() : null);
    content.ondragover = (e) => { if (S.folder && e.dataTransfer.types.includes(DRAG) && e.target === content) { e.preventDefault(); } };
  }

  // ---------------------------------------------------------------------------------------------- baixar mais modelos (o catálogo e a busca de antes)
  // ---------------------------------------------------------------------------------------------- downloads
  async function downloadsTab(box) {
    const active = h('div', { class: 'col', id: 'lib-active', 'aria-live': 'polite' }), recent = h('div', { class: 'col', id: 'lib-recent' }), done = h('div', { class: 'col', id: 'lib-done' });
    box.append(h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', { role: 'heading', 'aria-level': '2' }, t('Em andamento')), active),
      h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', { role: 'heading', 'aria-level': '2' }, t('Recentes (desta sessão)')), recent),
      h('div', { class: 'card' }, h('h3', { role: 'heading', 'aria-level': '2' }, t('Modelos baixados')), h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Todos os modelos GGUF neste computador, dos mais novos aos mais antigos.')), done));
    let alive = true, timer = 0, lastModels = '';
    const row = (d) => {
      const pc = d.total ? Math.min(1, d.done / d.total) : 0;
      return h('div', { class: 'dlrow', 'data-job': d.id },
        h('div', { class: 'row nw' }, h('div', { class: 'grow', style: { minWidth: 0 } }, h('div', { class: 'mono', style: { fontSize: '13px', overflowWrap: 'anywhere' } }, d.title),
          h('div', { class: 'dim small' }, [t(d.label), d.repo].filter(Boolean).join(' · '))),
        d.status === 'running' ? h('span', { class: 'small muted' }, d.total ? Math.round(pc * 100) + '% · ' + fmtBytes(d.done) + ' / ' + fmtBytes(d.total) + (d.speed ? ' · ' + fmtBytes(d.speed) + '/s ' + fmtEta(d.eta) : '') : t('Preparando…')) : null,
        d.status === 'running' ? h('button', { class: 'btn sm', type: 'button', onclick: () => api('/api/jobs/' + d.id + '/cancel', { method: 'POST' }).then(tick).catch(() => {}) }, t('Cancelar'))
          : h('span', { class: 'chip ' + (d.status === 'done' ? 'on' : d.status === 'error' ? 'warn' : '') }, d.status === 'done' ? '✓ ' + t('Concluído') : d.status === 'error' ? '⚠ ' + t('Falhou') : t('Cancelado'))),
        d.status === 'running' ? h('div', { class: 'bar', role: 'progressbar', 'aria-label': d.title, 'aria-valuenow': Math.round(pc * 100) }, h('i', { style: { width: Math.round(pc * 100) + '%' } })) : null,
        d.status === 'running' && d.note ? h('div', { class: 'dim small' }, d.note) : null,
        d.status === 'error' && d.error ? h('div', { class: 'res err small' }, d.error) : null);
    };
    async function tick() {
      if (!alive) return;
      try {
        const r = await api('/api/library/downloads');
        if (!alive) return;
        const run = r.downloads.filter((d) => d.status === 'running'), rest = r.downloads.filter((d) => d.status !== 'running');
        active.replaceChildren(...(run.length ? run.map(row) : [h('div', { class: 'muted small' }, t('Nenhum download em andamento.'))]));
        recent.replaceChildren(...(rest.length ? rest.map(row) : [h('div', { class: 'muted small' }, t('Nada concluído nesta sessão ainda.'))]));
        const { models } = await api('/api/hf/local?kind=all');
        const sig = JSON.stringify(models.map((m) => [m.name, m.size]));
        if (sig !== lastModels) {
          lastModels = sig;
          const kindLabel = (k) => t((GGUF_KINDS.find(([x]) => x === k) || [0, k])[1]);
          done.replaceChildren(...(models.length ? models.slice().sort((a, b) => (b.mtime || 0) - (a.mtime || 0)).map((m) => h('div', { class: 'dlrow' }, h('div', { class: 'row nw' },
            h('div', { class: 'grow', style: { minWidth: 0 } }, h('div', { class: 'mono', style: { fontSize: '13px', overflowWrap: 'anywhere' } }, m.name),
              h('div', { class: 'dim small' }, [kindLabel(m.kind), fmtBytes(m.size), m.mtime ? new Date(m.mtime * 1000).toLocaleString() : ''].filter(Boolean).join(' · '))),
            m.quant ? h('span', { class: 'chip solid' }, m.quant) : null)))
            : [h('div', { class: 'muted small' }, t('Nenhum modelo baixado ainda. Pesquise e baixe pela barra de pesquisa de modelos dentro de um projeto (Canvas).'))]));
        }
        timer = setTimeout(tick, run.length ? 1000 : 4000);   // mais rápido enquanto há download; devagar quando parado
      } catch (e) { if (alive) timer = setTimeout(tick, 5000); }
    }
    await tick();
    return () => { alive = false; clearTimeout(timer); };
  }


  // ---------------------------------------------------------------------------------------------- onde guardar (v0.33)
  async function paintWhere(box) {
    let r;
    try { r = await api('/api/storage/locations'); } catch (e) { return box.replaceChildren(h('div', { class: 'res err' }, e.message)); }
    const KIND = { ssd: 'SSD', hdd: 'HDD', unknown: '' };
    const row = (k, label) => {
      const x = r[k];
      return h('div', { class: 'row nw', style: { padding: '8px 0', borderBottom: '1px solid var(--line2)' }, 'data-where': k },
        h('div', { class: 'grow', style: { minWidth: 0 } }, h('div', null, h('b', null, label), x.custom ? h('span', { class: 'chip on', style: { marginLeft: '8px' } }, t('personalizada')) : h('span', { class: 'chip', style: { marginLeft: '8px' } }, t('padrão'))),
          h('div', { class: 'mono small', style: { overflowWrap: 'anywhere' } }, x.path),
          h('div', { class: 'dim small' }, t('{f} livres de {t}', { f: fmtBytes(x.free), t: fmtBytes(x.total) }) + (KIND[x.kind] ? ' · ' + KIND[x.kind] : ''))),
        h('button', { class: 'btn sm', type: 'button', id: 'where-' + k, disabled: r.busy, title: r.busy ? t('Espere as tarefas em andamento terminarem.') : '', onclick: () => change(k, label, r) }, t('Alterar…')),
        x.custom ? h('button', { class: 'btn sm ghost', type: 'button', disabled: r.busy, id: 'where-default-' + k, onclick: () => apply(k, '', true) }, t('Usar a padrão')) : null);
    };
    box.replaceChildren(h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', { role: 'heading', 'aria-level': '2' }, t('Onde guardar')),
      h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Guarde os modelos e os arquivos dos projetos em outro disco: um HD ou SSD externo, um pendrive ou outra pasta do computador. O que já existe pode ser movido junto (copia primeiro e só apaga a pasta antiga no fim).')),
      ...(r.warnings || []).map((w) => h('p', { class: 'res warn small' }, '⚠ ' + w)),
      row('models', t('Modelos de IA')), row('files', t('Arquivos dos projetos (imagens, vídeos e sons)'))));
  }
  async function apply(kind, path, move) {
    let res;
    try { res = await api('/api/storage/location', { method: 'POST', body: { kind, path, move } }); } catch (e) { return toast(e.message, 'err'); }
    if (!res.job_id) { toast(t('Pronto: o OpenFlow usa {p}', { p: res.path }), 'ok'); return show(); }
    const bar = h('i'), label = h('span', { class: 'small muted' }, '0%'), note = h('div', { class: 'small muted' });
    const area = h('div', { class: 'card', id: 'where-progress', style: { marginBottom: '16px' } }, h('div', { class: 'row' }, h('b', { class: 'grow' }, t('Movendo para {p}', { p: res.path })), label,
      h('button', { class: 'btn sm', type: 'button', onclick: () => api('/api/jobs/' + res.job_id + '/cancel', { method: 'POST' }).catch(() => {}) }, t('Cancelar'))), h('div', { class: 'bar', role: 'progressbar', 'aria-label': t('Movendo') }, bar), note);
    document.getElementById('lib-where').prepend(area);
    events('/api/jobs/' + res.job_id + '/events', (ev) => {
      if (ev.type === 'progress' && ev.total) { const pc = Math.min(1, ev.done / ev.total); bar.style.width = Math.round(pc * 100) + '%'; label.textContent = Math.round(pc * 100) + '% · ' + fmtBytes(ev.done) + ' / ' + fmtBytes(ev.total); }
      else if (ev.type === 'note') note.textContent = ev.message;
      else if (ev.type === 'done') { toast(t('Movido. O OpenFlow já usa a nova pasta.'), 'ok'); show(); }
      else if (ev.type === 'error') { toast(ev.message, 'err'); show(); }
      else if (ev.type === 'cancelled') { toast(t('Cancelado: nada foi apagado.')); show(); }
    });
  }
  async function change(kind, label, r) {
    const inp = h('input', { type: 'text', id: 'where-path', style: { width: '100%' }, placeholder: t('Caminho da pasta (ex.: E:/OpenFlow ou /media/usuario/HD)'), value: '' });
    const moveBox = { v: true };
    const list = h('div', { class: 'lib-pick', id: 'where-list' });
    const browse = async (path) => {
      try {
        const b = await api('/api/storage/browse?path=' + encodeURIComponent(path || ''));
        const here = h('div', { class: 'dim small', style: { padding: '4px 0' } }, b.path || t('Discos e dispositivos'));
        list.replaceChildren(here, ...(b.parent || (!b.volumes && b.path) ? [h('button', { type: 'button', class: 'lib-fold', onclick: () => browse(b.parent || '') }, icon('chev', 14), h('span', null, t('Voltar')))] : []),
          ...b.dirs.map((d) => { const full = b.volumes ? d : b.path.replace(/[\\/]$/, '') + (b.path.includes('\\') ? '\\' : '/') + d;
            const vol = b.volumes ? r.volumes.find((v) => v.path === d) : null;
            return h('button', { type: 'button', class: 'lib-fold', 'data-dir': full, onclick: () => { inp.value = full; browse(full); } }, icon('folder', 14),
              h('span', null, b.volumes ? ((vol && vol.label) || d) + (vol ? ' · ' + t('{f} livres', { f: fmtBytes(vol.free) }) + (vol.removable ? ' · ' + t('externo') : '') : '') : d)); }));
      } catch (e) { list.replaceChildren(h('div', { class: 'res err small' }, e.message)); }
    };
    await browse('');
    const body = h('div', null, h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Escolha a pasta (ou digite o caminho). A raiz de um disco vira uma subpasta «OpenFlow».')), inp, list,
      checkbox(t('Mover o que já existe para a nova pasta (recomendado)'), true, (v) => { moveBox.v = v; }),
      h('p', { class: 'muted small' }, t('Sem mover, o conteúdo antigo continua na pasta de antes e deixa de aparecer no OpenFlow.')));
    const v = await modal(t('Alterar: {n}', { n: label }), body, [{ label: t('Cancelar'), value: null }, { label: t('Usar esta pasta'), value: 'ok', cls: 'primary' }]);
    if (v !== 'ok') return;
    if (!inp.value.trim()) return toast(t('Escolha uma pasta.'), 'err');
    await apply(kind, inp.value.trim(), moveBox.v);
  }

  // ---------------------------------------------------------------------------------------------- armazenamento (v0.31)
  async function storageTab(box) {
    const body = h('div', { id: 'lib-storage' });
    const where = h('div', { id: 'lib-where' });
    box.append(where, body);
    await paintWhere(where);
    const paint = (r) => {
      const used = Object.values(r.models).reduce((a, b) => a + b, 0) + r.projects + r.uploads;
      const KIND = { ssd: t('SSD'), hdd: t('HDD'), unknown: t('tipo desconhecido') };
      const cl = r.cleanable, total = cl.partials.bytes + cl.temp.bytes + cl.orphans.bytes;
      const row = (label, bytes) => h('div', { class: 'row nw', style: { padding: '4px 0' } }, h('span', { class: 'grow' }, label), h('span', { class: 'dim' }, fmtBytes(bytes)));
      const cleanRow = (id, what, label, hint) => cl[what].files ? h('div', { class: 'row nw', style: { padding: '6px 0' } }, h('div', { class: 'grow' }, h('div', null, label + ' · ' + fmtBytes(cl[what].bytes) + ' (' + t('{n} item(ns)', { n: cl[what].files }) + ')'), h('div', { class: 'dim small' }, hint)),
        h('button', { class: 'btn sm', type: 'button', id: 'st-' + id, onclick: () => clean([what]) }, t('Limpar'))) : null;
      body.replaceChildren(
        h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', { role: 'heading', 'aria-level': '2' }, t('Disco')),
          h('p', { class: 'muted small', style: { marginTop: 0 } }, t('{k} · {f} livres de {t}', { k: KIND[r.disk.kind], f: fmtBytes(r.disk.free), t: fmtBytes(r.disk.total) }) + (r.disk.kind === 'hdd' ? ' · ' + t('Em HDD o OpenFlow baixa por uma conexão só e lê o modelo em sequência, para o disco não ficar procurando.') : '')),
          h('div', { class: 'bar', role: 'img', 'aria-label': t('Espaço usado pelo OpenFlow') }, h('i', { style: { width: Math.min(100, Math.max(1, Math.round(100 * used / Math.max(1, r.disk.total)))) + '%' } })),
          h('p', { class: 'muted small' }, t('O OpenFlow ocupa {n}.', { n: fmtBytes(used) }))),
        h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', { role: 'heading', 'aria-level': '2' }, t('O que ocupa espaço')),
          row(t('Modelos de texto'), r.models.text || 0), row(t('Modelos de imagem'), r.models.image || 0), row(t('Modelos de vídeo'), r.models.video || 0), row(t('Modelos de som, voz e transcrição'), (r.models.sound || 0) + (r.models.voice || 0) + (r.models.stt || 0)),
          row(t('Projetos (arquivos gerados e enviados)'), r.projects), row(t('Envios soltos'), r.uploads)),
        h('div', { class: 'card' }, h('h3', { role: 'heading', 'aria-level': '2' }, t('Limpeza')),
          total ? [cleanRow('partials', 'partials', t('Downloads incompletos'), t('Parciais abandonados há mais de 1 hora (baixar de novo recomeça do zero).')),
            cleanRow('temp', 'temp', t('Temporários'), t('Sobras de gerações interrompidas.')), cleanRow('orphans', 'orphans', t('Arquivos sem projeto'), t('Arquivos na pasta de um projeto que nenhum nó nem a lista de arquivos usa mais.')),
            h('div', { style: { marginTop: '8px' } }, h('button', { class: 'btn primary', type: 'button', id: 'st-all', onclick: () => clean(['partials', 'temp', 'orphans']) }, t('Limpar tudo ({n})', { n: fmtBytes(total) })))]
            : h('div', { class: 'muted small' }, t('Nada para limpar. Os modelos e os arquivos dos seus projetos nunca são apagados por aqui.')),
          r.downloading ? h('p', { class: 'muted small' }, t('Há um download em andamento: os incompletos ficam até ele terminar.')) : null));
    };
    async function load() { try { paint(await api('/api/storage')); } catch (e) { body.replaceChildren(h('div', { class: 'res err' }, e.message)); } }
    async function clean(what) {
      try { const r = await api('/api/storage/clean', { method: 'POST', body: { what } }); toast(t('{b} liberados ({n} item(ns))', { b: fmtBytes(r.freed), n: r.removed }), 'ok'); load(); } catch (e) { toast(e.message, 'err'); }
    }
    await load();
  }

  // ---------------------------------------------------------------------------------------------- tela
  async function show() {
    stop(); stop = () => {};
    paintSide(); paintBar();
    if (S.scope === 'downloads') { const holder = h('div'); main.replaceChildren(bar, crumbs, holder); stop = await downloadsTab(holder); return; }
    if (S.scope === 'storage') { const holder = h('div'); main.replaceChildren(bar, crumbs, holder); await storageTab(holder); return; }
    main.replaceChildren(bar, crumbs, filters, content);
    await loadItems();
  }

  root.replaceChildren(h('div', { class: 'page lib-page' }, h('div', { class: 'page-h' }, h('div', null, h('h1', null, t('Biblioteca')),
    h('p', null, t('Seus modelos de IA e arquivos gerados, organizados em pastas. Arraste para mover; no canvas, a aba «Biblioteca» leva os arquivos para o fluxo.')))),
  h('div', { class: 'lib-layout' }, side, main)));
  // a árvore de pastas é carregada junto da primeira listagem
  try { S.tree = (await api('/api/library/folders?scope=' + (['downloads', 'storage'].includes(S.scope) ? 'files' : S.scope))).folders; } catch (e) { S.tree = []; }
  await show();
  const mo = new MutationObserver(() => { if (!root.isConnected || !document.getElementById('lib-body')) { stop(); mo.disconnect(); } });
  mo.observe(document.body, { childList: true, subtree: true });
}
