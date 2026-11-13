import { api, events } from '../api.js';
import { t } from '../i18n.js';
import { go, state } from '../main.js';
import { teamPicker } from '../team_ui.js';
import { confirmDialog, fill, h, icon, popover, toast } from '../ui.js';
import { modelSearchBar } from './canvas_hub.js';
import { GROUPS, LABEL, OUT_COLOR, TYPE_HELP, compatible, findFolder, nodeBody, nodeResult, portLabel } from '../canvas_nodes.js';

const uid = (p) => p + Math.random().toString(36).slice(2, 12);
const deep = (o) => JSON.parse(JSON.stringify(o));
const RUNNABLE = ['llm', 'image', 'video', 'sound', 'voice', 'transcribe', 'editor'];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// Editor de um canvas: nós ligados por conexões, pan/zoom, arquivos do projeto, execução com acompanhamento ao vivo.
export default async function render(root, ctx, cid) {
  const [meta, cv, prov] = await Promise.all([api('/api/project-templates'), api('/api/projects/' + cid), api('/api/media/providers')]);
  const types = Object.fromEntries(meta.types.map((x) => [x.type, x]));
  const S = { cv, sel: '', selEdge: '', states: {}, job: '', stopEv: null, saveState: 'saved', assetsOpen: localStorage.getItem('openflow.cv.assets') === '1' };
  let view = Object.assign({ x: 0, y: 0, zoom: 1 }, cv.viewport);
  const nodeById = (id) => S.cv.nodes.find((n) => n.id === id);
  const el = {};  // nó id → elemento

  // ---------------------------------------------------------------------------------------------- contexto dos nós
  const c = {
    get cv() { return S.cv; }, meta, prov,
    asset: (id) => S.cv.assets.find((a) => a.id === id),
    url: (a) => `/api/projects/${cid}/assets/${a.file}`,
    state: (id) => S.states[id] || {},
    providerLabel: (pid) => (prov.providers.find((p) => p.id === pid) || { label: pid }).label,
    openConfig: () => { go('settings', { tab: 'media' }); },
    change(n, key, value, rerender) { n.params[key] = value; dirty(); if (rerender) refreshNode(n.id); },
    accOpen: new Set(),
    uploadTo: (n, files, fid) => uploadFiles(files, null, n, fid),
    mentions: () => api(`/api/projects/${cid}/mentions`).then((r) => r.items),
    openTimeline: (n) => openTimeline(n),
    run: (ids, force) => run(ids, force),
    preview: (a, list) => preview(a, list),
  };

  // ---------------------------------------------------------------------------------------------- salvar
  const savedLbl = h('span', { class: 'sv' });
  const paintSaved = (msg) => {
    savedLbl.textContent = { saved: t('Salvo'), saving: t('Salvando…'), dirty: t('Alterações…'), err: msg || t('Não foi possível salvar') }[S.saveState];
    savedLbl.style.color = S.saveState === 'err' ? 'var(--err)' : '';
  };
  const layout = () => ({
    name: nameInput.value.trim() || S.cv.name, viewport: view, edges: S.cv.edges,
    nodes: S.cv.nodes.map((n) => ({ id: n.id, type: n.type, x: n.x, y: n.y, w: n.w, title: n.title, params: n.params })),
  });
  let timer = 0;
  function dirty(ms = 700) { if (S.job) return; S.saveState = 'dirty'; paintSaved(); clearTimeout(timer); timer = setTimeout(save, ms); }
  async function save() {
    clearTimeout(timer);
    if (S.job) return;
    S.saveState = 'saving'; paintSaved();
    try {
      const r = await api('/api/projects/' + cid, { method: 'PUT', body: layout() });
      S.cv.stale = r.stale || []; S.saveState = 'saved'; paintSaved(); paintStale();
    } catch (e) { S.saveState = 'err'; paintSaved(e.message); }
  }
  const onLeave = () => { if (S.saveState === 'dirty') save(); };

  // ---------------------------------------------------------------------------------------------- estrutura
  const nameInput = h('input', { class: 'nm', value: cv.name, title: t('Nome do projeto'), 'aria-label': t('Nome do projeto'), onchange: async () => { try { await api(`/api/projects/${cid}/meta`, { method: 'POST', body: { name: nameInput.value } }); S.cv.name = nameInput.value; } catch (e) { toast(e.message, 'err'); } } });
  const runBtn = h('button', { class: 'btn primary', title: t('Executa o que está desatualizado (o resto vem do cache)'), onclick: () => run(null, false) }, icon('play', 14), t('Executar tudo'));
  const team = teamPicker(state.settings && state.settings.canvas, null, { id: 'cv-team' });   // equipe dos nós de texto com IA (esforço Low … Omni e 1/2/4/8/12/16/20/24/28/32 agentes)
  const cancelBtn = h('button', { class: 'btn danger hidden', onclick: async () => { if (S.job) await api('/api/jobs/' + S.job + '/cancel', { method: 'POST' }).catch(() => {}); } }, icon('stop', 14), t('Cancelar'));
  const assetsBtn = h('button', { class: 'btn', onclick: () => { S.assetsOpen = !S.assetsOpen; localStorage.setItem('openflow.cv.assets', S.assetsOpen ? '1' : '0'); paintAssets(); } }, icon('image', 14), h('span', null, t('Arquivos')));
  // barra de pesquisa de modelos (Hugging Face) no topo: procura, escolhe a quantização, baixa e usa no nó selecionado
  const hub = modelSearchBar({ cid, selected: () => nodeById(S.sel) || null, onUsed: (res, n) => { if (n) { n.params.provider = res.provider; if (res.cap !== 'text') n.params.model = res.model; refreshNode(n.id); } api('/api/media/providers').then((p) => { prov.providers = p.providers; }).catch(() => {}); } });
  const top = h('div', { class: 'cv-top' },
    h('button', { class: 'btn ghost icon sm cv-back', title: t('Voltar aos projetos'), 'aria-label': t('Voltar aos projetos'), onclick: async () => { await save(); location.hash = '#/projects'; } }, icon('chev', 16)),
    nameInput, savedLbl, hub.el, h('span', { class: 'grow' }),
    h('button', { class: 'btn ghost', title: t('Provedores de mídia'), onclick: () => c.openConfig() }, icon('config', 14), t('Provedores')),
    assetsBtn,
    h('a', { class: 'btn', href: `/api/projects/${cid}/download`, title: t('Baixa o projeto e todos os arquivos (.zip)') }, icon('download', 14), t('Baixar')),
    runBtn, cancelBtn);

  const world = h('div', { class: 'cv-world' });
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'cv-edges');
  const nodesLayer = h('div');
  world.append(svg, nodesLayer);
  const hint = h('div', { class: 'cv-hint' }, h('div', null, h('div', { style: { fontSize: '16px', color: 'var(--muted)', marginBottom: '6px' } }, t('Projeto vazio')), t('Clique num nó da paleta, ou arraste arquivos para cá.')));
  const surface = h('div', { class: 'cv-surface' }, world, hint,
    h('div', { class: 'cv-zoom' },
      h('button', { class: 'btn icon sm', title: t('Ampliar'), onclick: () => zoomBy(1.2) }, icon('zoomin', 15)),
      h('button', { class: 'btn icon sm', title: t('Reduzir'), onclick: () => zoomBy(1 / 1.2) }, h('span', { style: { fontSize: '18px', lineHeight: 1 } }, '−')),
      h('button', { class: 'btn icon sm', title: t('Ajustar à tela'), onclick: () => fit() }, icon('fit', 15))));
  const assetsPanel = h('div', { class: 'cv-assets hidden' });

  // ---------------------------------------------------------------------------------------------- caixa de prompt (gerar fluxo com IA)
  // fica embaixo do canvas, pequena; o botão ▾/▴ recolhe e abre para não atrapalhar a montagem do fluxo. A equipe (esforço e agentes) é a mesma da execução.
  const DOCK_KEY = 'openflow.cv.dock';
  const ls = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { /* sem armazenamento */ } return null; };
  const dockText = h('textarea', { rows: 2, id: 'cv-dock-text', placeholder: t('Descreva o fluxo que você quer: ex. «thumb de YouTube com uma foto minha e 3 personagens» ou «cena de farol com narração»…'), 'aria-label': t('Prompt do fluxo') });
  const dockMsg = h('div', { class: 'cv-dock-msg muted small hidden', id: 'cv-dock-msg' });
  const dockGo = h('button', { class: 'btn primary sm', id: 'cv-dock-go', type: 'button', title: t('A equipe de agentes monta os nós e as ligações; você revisa e executa'), onclick: () => genFlow() }, icon('wand', 14), t('Gerar fluxo'));
  const dockBody = h('div', { class: 'cv-dock-body' }, dockText, dockMsg, h('div', { class: 'cv-dock-row' }, team.el, h('span', { class: 'grow' }), dockGo));
  const dockToggle = h('button', { class: 'btn icon sm cv-dock-toggle', id: 'cv-dock-toggle', type: 'button', onclick: () => setDock(dock.classList.contains('min')) });
  const dock = h('div', { class: 'cv-dock', id: 'cv-dock' }, h('div', { class: 'cv-dock-head' }, icon('wand', 14), h('span', { class: 'cv-dock-title' }, t('Gerar fluxo com IA')), h('span', { class: 'grow' }), dockToggle), dockBody);
  function setDock(open) {
    dock.classList.toggle('min', !open); ls(DOCK_KEY, open ? '1' : '0');
    dockToggle.replaceChildren(icon('chevd', 14));
    dockToggle.title = dockToggle.ariaLabel = open ? t('Minimizar a caixa de prompt') : t('Maximizar a caixa de prompt');
    dockToggle.classList.toggle('flip', !open);
    if (open) setTimeout(() => dockText.focus(), 0);
  }
  dock.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); genFlow(); } });
  let flowJob = '';
  async function genFlow() {
    const prompt = dockText.value.trim();
    if (!prompt) { dockText.focus(); return toast(t('Descreva o fluxo que você quer criar.'), 'err'); }
    if (flowJob) return;
    const xs = S.cv.nodes.map((n) => n.x + (n.w || 280)), ys = S.cv.nodes.map((n) => n.y);
    const origin = S.cv.nodes.length ? { x: Math.max(...xs) + 120, y: Math.min(...ys) } : toWorld(surface.getBoundingClientRect().left + 120, surface.getBoundingClientRect().top + 90);
    await save();
    dockGo.disabled = true; dockMsg.classList.remove('hidden'); dockMsg.textContent = t('Equipe de agentes montando o fluxo…');
    let r;
    try { r = await api(`/api/projects/${cid}/flow`, { method: 'POST', body: { prompt, team: team.get(), x: Math.round(origin.x), y: Math.round(origin.y) } }); }
    catch (e) { if (e.status === 409) { try { r = JSON.parse(e.message); } catch (er) { /* ignore */ } } if (!r) { dockGo.disabled = false; dockMsg.classList.add('hidden'); return toast(e.message, 'err'); } }
    flowJob = r.job_id;
    const STEP = { planner: t('Planejador'), reviewer: t('Revisor'), build: t('Montagem') };
    const stop = events('/api/jobs/' + flowJob + '/events', (ev) => {
      if (ev.type === 'step' && ev.status === 'running') dockMsg.textContent = t('Equipe de agentes: {s}…', { s: STEP[ev.id] || ev.id });
      else if (ev.type === 'note') dockMsg.textContent = ev.message;
      else if (ev.type === 'done') applyFlow(ev);
      else if (ev.type === 'error') { dockMsg.textContent = ''; toast(ev.message || t('Não consegui gerar o fluxo.'), 'err'); }
    }, () => { flowJob = ''; dockGo.disabled = false; setTimeout(() => dockMsg.classList.add('hidden'), 4000); if (stop) stop(); });
  }
  function applyFlow(ev) {
    for (const n of ev.nodes || []) { n.w = n.w || (['editor', 'image', 'video'].includes(n.type) ? 300 : 280); S.cv.nodes.push(n); addToDom(n); }
    for (const e of ev.edges || []) S.cv.edges.push(e);
    paintHint(); drawEdges(); fit(); dirty();
    dockMsg.textContent = t('{n} nós e {e} ligações adicionados. Revise e aperte «Executar tudo».', { n: (ev.nodes || []).length, e: (ev.edges || []).length }) + ((ev.warnings || []).length ? ' ⚠ ' + ev.warnings.join(' · ') : '');
    dockText.value = '';
  }

  const palette = h('div', { class: 'cv-pal' }, GROUPS.map(([g, list]) => h('div', null, h('h4', null, t(g)),
    list.map((type) => h('button', { class: 'it', draggable: 'true', title: t(TYPE_HELP[type]), style: { '--c': OUT_COLOR[types[type].out] },
      ondragstart: (e) => { e.dataTransfer.setData('text/flow-node', type); e.dataTransfer.effectAllowed = 'copy'; },
      onclick: () => { const r = surface.getBoundingClientRect(); const p = toWorld(r.left + r.width / 2 - 140 + (Math.random() - .5) * 90, r.top + r.height / 2 - 100 + (Math.random() - .5) * 90); addNode(type, p.x, p.y); } },
      icon(types[type].icon, 17), h('span', null, t(LABEL[type])))))));

  root.replaceChildren(h('div', { class: 'cv-root cv-pg' }, top, h('div', { class: 'cv-main' }, palette, surface, assetsPanel)));
  surface.appendChild(dock); setDock(ls(DOCK_KEY) !== '0');
  const rootEl = root.firstChild;

  // ---------------------------------------------------------------------------------------------- vista (pan/zoom)
  const toWorld = (cx, cy) => { const r = surface.getBoundingClientRect(); return { x: (cx - r.left - view.x) / view.zoom, y: (cy - r.top - view.y) / view.zoom }; };
  function applyView() {
    world.style.transform = `translate(${view.x}px,${view.y}px) scale(${view.zoom})`;
    surface.style.backgroundPosition = `${view.x}px ${view.y}px`;
    surface.style.backgroundSize = `${24 * view.zoom}px ${24 * view.zoom}px`;
  }
  function zoomAt(f, mx, my) {
    const nz = clamp(view.zoom * f, 0.25, 2), wx = (mx - view.x) / view.zoom, wy = (my - view.y) / view.zoom;
    view.zoom = nz; view.x = mx - wx * nz; view.y = my - wy * nz; applyView(); dirty(1500);
  }
  function zoomBy(f) { const r = surface.getBoundingClientRect(); zoomAt(f, r.width / 2, r.height / 2); }
  function fit() {
    if (!S.cv.nodes.length) { view = { x: 0, y: 0, zoom: 1 }; applyView(); return; }
    const xs = S.cv.nodes.map((n) => n.x), ys = S.cv.nodes.map((n) => n.y);
    const x2 = Math.max(...S.cv.nodes.map((n) => n.x + n.w)), y2 = Math.max(...S.cv.nodes.map((n) => n.y + ((el[n.id] && el[n.id].offsetHeight) || 200)));
    const x1 = Math.min(...xs), y1 = Math.min(...ys), r = surface.getBoundingClientRect(), pad = 60;
    const z = clamp(Math.min((r.width - pad * 2) / (x2 - x1), (r.height - pad * 2) / (y2 - y1)), 0.25, 1);
    view = { zoom: z, x: (r.width - (x2 - x1) * z) / 2 - x1 * z, y: (r.height - (y2 - y1) * z) / 2 - y1 * z }; applyView(); drawEdges(); dirty(1500);
  }
  surface.addEventListener('wheel', (e) => {
    if (e.target.closest('textarea,select,input,.rtxt,.digest,.cv-dock')) return;
    e.preventDefault();
    const r = surface.getBoundingClientRect();
    zoomAt(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });

  function drag(e, onMove, onUp) {
    const mv = (ev) => onMove(ev), up = (ev) => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); if (onUp) onUp(ev); };
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
  }
  surface.addEventListener('pointerdown', (e) => {
    const bg = !e.target.closest('.cv-node,.cv-zoom,.cv-dock,.hit,.del');
    if (!(bg && e.button === 0) && e.button !== 1) return;
    e.preventDefault();
    if (bg) select('', '');
    const sx = e.clientX, sy = e.clientY, vx = view.x, vy = view.y;
    surface.classList.add('pan');
    drag(e, (ev) => { view.x = vx + ev.clientX - sx; view.y = vy + ev.clientY - sy; applyView(); }, () => { surface.classList.remove('pan'); dirty(1500); });
  });

  // ---------------------------------------------------------------------------------------------- nós
  function select(nid, eid) {
    S.sel = nid; S.selEdge = eid;
    for (const [id, e] of Object.entries(el)) e.classList.toggle('sel', id === nid);
    drawEdges();
  }
  const isStale = (id) => (S.cv.stale || []).includes(id);
  function dotClass(n) {
    const st = S.states[n.id] || {};
    if (st.state === 'running') return 'st';
    if (st.state === 'queued') return 'st queued';
    if (st.state === 'error' || n.result.state === 'error') return 'st err';
    if (!RUNNABLE.includes(n.type)) return 'st';
    return isStale(n.id) ? 'st stale' : (n.result.state === 'done' ? 'st ok' : 'st');
  }
  const dotTitle = (n) => (RUNNABLE.includes(n.type) ? (isStale(n.id) ? t('Desatualizado: será gerado de novo ao executar') : (n.result.state === 'done' ? t('Atualizado') : '')) : '');
  function paintStale() { for (const n of S.cv.nodes) { const d = el[n.id] && el[n.id].querySelector('.st'); if (d) { d.className = dotClass(n); d.title = dotTitle(n); } } }

  function nodeEl(n) {
    const info = types[n.type];
    const title = h('input', { class: 'ti nodrag', value: n.title || '', placeholder: t(LABEL[n.type]), onchange: (e) => { n.title = e.target.value; dirty(); }, onkeydown: (e) => e.stopPropagation() });
    const menuBtn = h('button', { class: 'btn ghost icon sm nodrag', title: t('Mais'), onclick: (e) => nodeMenu(e.currentTarget, n) }, icon('more', 15));
    const hd = h('div', { class: 'hd' }, icon(info.icon, 16), title, h('span', { class: dotClass(n), title: dotTitle(n) }),
      RUNNABLE.includes(n.type) ? h('button', { class: 'btn ghost icon sm nodrag', title: t('Executar este nó (e o que ele precisa). Shift: gerar de novo'), onclick: (e) => run([n.id], e.shiftKey) }, icon('play', 14)) : null, menuBtn);
    const ports = info.ins.length ? h('div', { class: 'ports' }, info.ins.map((p) => {
      const cnt = S.cv.edges.filter((e) => e.to === n.id && e.port === p.id).length;
      return h('div', { class: 'pin' }, h('span', { class: 'pt in' + (cnt && !p.multi ? ' full' : ''), dataset: { node: n.id, port: p.id }, style: { '--pc': OUT_COLOR[p.accepts[0]] }, title: t('Arraste uma conexão até aqui') }),
        portLabel(n.type, p), cnt && p.multi ? h('span', { class: 'n' }, cnt) : null);
    })) : null;
    const out = h('span', { class: 'pt out', dataset: { node: n.id }, style: { '--pc': OUT_COLOR[info.out] }, title: t('Arraste para ligar a outro nó') });
    const e = h('div', { class: `cv-node t-${n.type}` + (S.sel === n.id ? ' sel' : ''), dataset: { id: n.id }, style: { left: n.x + 'px', top: n.y + 'px', width: n.w + 'px' } }, hd, ports, nodeBody(c, n), nodeResult(c, n), out);
    e.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0) return;
      if (S.sel !== n.id) select(n.id, '');
      if (ev.target.closest('.pt')) return;
      if (!ev.target.closest('.hd') || ev.target.closest('.nodrag')) return;
      ev.preventDefault();
      const sx = ev.clientX, sy = ev.clientY, ox = n.x, oy = n.y;
      drag(ev, (m) => { n.x = Math.round(ox + (m.clientX - sx) / view.zoom); n.y = Math.round(oy + (m.clientY - sy) / view.zoom); e.style.left = n.x + 'px'; e.style.top = n.y + 'px'; drawEdges(); }, () => dirty());
    });
    e.querySelectorAll('.pt.out').forEach((p) => p.addEventListener('pointerdown', (ev) => startConnect(ev, n)));
    e.querySelectorAll('.pt.in').forEach((p) => p.addEventListener('pointerdown', (ev) => {
      const old = S.cv.edges.filter((x) => x.to === n.id && x.port === p.dataset.port).pop();   // pegar uma conexão existente e ligá-la em outro lugar
      if (!old) return;
      S.cv.edges = S.cv.edges.filter((x) => x !== old); refreshNode(n.id); dirty();
      startConnect(ev, nodeById(old.from));
    }));
    return e;
  }
  let roFrame = 0;
  const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(() => { cancelAnimationFrame(roFrame); roFrame = requestAnimationFrame(drawEdges); }) : null;   // a altura do nó mudou (texto que cresce, campo redimensionado à mão, resultado novo): as portas se mexem e as conexões acompanham
  function addToDom(n) { const e = nodeEl(n); el[n.id] = e; nodesLayer.appendChild(e); if (ro) ro.observe(e); }
  function refreshNode(id) {
    const n = nodeById(id); if (!n) return;
    const old = el[id], e = nodeEl(n);
    if (old) { if (ro) ro.unobserve(old); old.replaceWith(e); } else nodesLayer.appendChild(e);
    el[id] = e; if (ro) ro.observe(e); drawEdges(); paintHint();
  }
  const paintHint = () => hint.classList.toggle('hidden', S.cv.nodes.length > 0);

  function addNode(type, x, y, params) {
    const n = { id: uid('n_'), type, x: Math.round(x), y: Math.round(y), w: ['editor', 'image', 'video'].includes(type) ? 300 : 280, title: '', params: Object.assign(deep(meta.defaults[type]), params || {}), result: deep(meta.default_result) };
    S.cv.nodes.push(n); addToDom(n); select(n.id, ''); paintHint(); dirty();
    return n;
  }
  function removeNode(id) {
    S.cv.nodes = S.cv.nodes.filter((n) => n.id !== id);
    S.cv.edges = S.cv.edges.filter((e) => e.from !== id && e.to !== id);
    if (el[id]) { el[id].remove(); delete el[id]; }
    for (const n of S.cv.nodes) refreshNodePorts(n);
    select('', ''); paintHint(); dirty();
  }
  const refreshNodePorts = (n) => { if (types[n.type].ins.length) refreshNode(n.id); };
  function nodeMenu(anchor, n) {
    const item = (label, ic, fn, cls) => h('div', { class: 'opt ' + (cls || ''), onclick: () => { pop.close(); fn(); } }, icon(ic, 15), label);
    const pop = popover(anchor, h('div', null,
      RUNNABLE.includes(n.type) ? item(t('Gerar de novo'), 'refresh', () => run([n.id], true)) : null,
      item(t('Duplicar'), 'copy', () => { const d = addNode(n.type, n.x + 40, n.y + 40, deep(n.params)); d.title = n.title; refreshNode(d.id); }),
      item(t('Apagar nó'), 'trash', () => removeNode(n.id), 'danger')));
  }

  // ---------------------------------------------------------------------------------------------- conexões
  function portPos(nid, port) {
    const n = nodeById(nid), e = el[nid]; if (!n || !e) return null;
    const p = port ? e.querySelector(`.pt.in[data-port="${port}"]`) : e.querySelector('.pt.out');
    if (!p) return null;
    let x = 0, y = 0, cur = p;
    while (cur && cur !== e) { x += cur.offsetLeft; y += cur.offsetTop; cur = cur.offsetParent; }
    return { x: n.x + x + p.offsetWidth / 2, y: n.y + y + p.offsetHeight / 2 };
  }
  const NS = 'http://www.w3.org/2000/svg';
  const bez = (a, b) => { const dx = Math.max(50, Math.abs(b.x - a.x) / 2); return `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`; };
  function drawEdges() {
    const kids = [];
    for (const e of S.cv.edges) {
      const a = portPos(e.from, ''), b = portPos(e.to, e.port); if (!a || !b) continue;
      const d = bez(a, b), g = document.createElementNS(NS, 'g');
      g.setAttribute('class', e.id === S.selEdge ? 'sel' : '');
      g.style.setProperty('--c', OUT_COLOR[types[nodeById(e.from).type].out]);
      const vis = document.createElementNS(NS, 'path'); vis.setAttribute('d', d); vis.setAttribute('class', 'vis');
      const hit = document.createElementNS(NS, 'path'); hit.setAttribute('d', d); hit.setAttribute('class', 'hit');
      hit.addEventListener('pointerdown', (ev) => { ev.stopPropagation(); select('', e.id); });
      g.append(vis, hit);
      if (e.id === S.selEdge) {
        const del = document.createElementNS(NS, 'g'); del.setAttribute('class', 'del'); del.setAttribute('transform', `translate(${(a.x + b.x) / 2},${(a.y + b.y) / 2})`);
        const ci = document.createElementNS(NS, 'circle'); ci.setAttribute('r', 10); const tx = document.createElementNS(NS, 'text'); tx.textContent = '×';
        del.append(ci, tx); del.addEventListener('pointerdown', (ev) => { ev.stopPropagation(); removeEdge(e.id); }); g.append(del);
      }
      kids.push(g);
    }
    fill(svg, kids);
  }
  function removeEdge(id) {
    const e = S.cv.edges.find((x) => x.id === id); if (!e) return;
    S.cv.edges = S.cv.edges.filter((x) => x.id !== id); S.selEdge = '';
    refreshNode(e.to); dirty();
  }
  const reaches = (src, dst, seen = new Set()) => { if (src === dst) return true; if (seen.has(src)) return false; seen.add(src); return S.cv.edges.some((e) => e.from === src && reaches(e.to, dst, seen)); };
  function addEdge(from, to, port) {
    const a = nodeById(from), b = nodeById(to); if (!a || !b || a === b) return false;
    const pd = types[b.type].ins.find((p) => p.id === port); if (!pd) return false;
    if (!compatible(types[a.type].out, pd.accepts)) { toast(t('Essa saída não combina com essa entrada.'), 'err'); return false; }
    if (S.cv.edges.some((e) => e.from === from && e.to === to && e.port === port)) return false;
    if (reaches(to, from)) { toast(t('Isso criaria um ciclo entre os nós.'), 'err'); return false; }
    if (!pd.multi) S.cv.edges = S.cv.edges.filter((e) => !(e.to === to && e.port === port));
    S.cv.edges.push({ id: uid('e_'), from, to, port });
    refreshNode(to); dirty();
    return true;
  }
  function startConnect(ev, src) {
    ev.preventDefault(); ev.stopPropagation();
    const a = portPos(src.id, ''), tmp = document.createElementNS(NS, 'path'); tmp.setAttribute('class', 'tmp'); svg.appendChild(tmp);
    const out = types[src.type].out;
    rootEl.querySelectorAll('.pt.in').forEach((p) => {
      const nd = nodeById(p.dataset.node), pd = nd && types[nd.type].ins.find((x) => x.id === p.dataset.port);
      const ok = nd && nd.id !== src.id && pd && compatible(out, pd.accepts);
      p.classList.add(ok ? 'compat' : 'incompat');
    });
    drag(ev, (m) => { const w = toWorld(m.clientX, m.clientY); tmp.setAttribute('d', bez(a, w)); }, (m) => {
      tmp.remove();
      rootEl.querySelectorAll('.pt.in').forEach((p) => p.classList.remove('compat', 'incompat'));
      const target = document.elementFromPoint(m.clientX, m.clientY);
      const pt = target && target.closest('.pt.in'), nd = target && target.closest('.cv-node');
      if (pt) addEdge(src.id, pt.dataset.node, pt.dataset.port);
      else if (nd && nd.dataset.id !== src.id) {
        const dst = nodeById(nd.dataset.id), ports = types[dst.type].ins.filter((p) => compatible(out, p.accepts));
        const free = ports.find((p) => !S.cv.edges.some((e) => e.to === dst.id && e.port === p.id)) || ports[0];
        if (free) addEdge(src.id, dst.id, free.id); else toast(t('Esse nó não tem uma entrada compatível.'), 'err');
      }
    });
  }

  // ---------------------------------------------------------------------------------------------- arquivos
  async function uploadFiles(files, pos, target, folderId) {
    if (S.job) return toast(t('Aguarde a execução terminar.'), 'err');
    const added = [];
    for (const f of files) {
      try {
        const a = await api(`/api/projects/${cid}/assets`, { method: 'POST', body: f, raw: true, headers: { 'X-Filename': encodeURIComponent(f.name), 'Content-Type': f.type || 'application/octet-stream' } });
        for (const x of [a, ...(a.also || [])]) { S.cv.assets.push(x); added.push(x.id); }
      } catch (e) { toast(`${f.name}: ${e.message}`, 'err'); }
    }
    if (!added.length) return;
    if (target && folderId && target.type === 'style_folder' && findFolder(target.params.folders, folderId)) { findFolder(target.params.folders, folderId).files.push(...added); c.change(target, 'folders', target.params.folders, true); }
    else if (target) c.change(target, 'files', [...target.params.files, ...added], true);
    else { const n = addNode('upload', pos.x, pos.y, { files: added }); refreshNode(n.id); }
    paintAssets();
  }
  surface.addEventListener('dragover', (e) => { if ([...e.dataTransfer.types].some((x) => x === 'Files' || x.startsWith('text/flow'))) { e.preventDefault(); surface.classList.add('drop'); } });
  surface.addEventListener('dragleave', (e) => { if (e.target === surface) surface.classList.remove('drop'); });
  surface.addEventListener('drop', (e) => {
    surface.classList.remove('drop');
    const p = toWorld(e.clientX, e.clientY), type = e.dataTransfer.getData('text/flow-node'), aid = e.dataTransfer.getData('text/flow-asset');
    if (!type && !aid && !e.dataTransfer.files.length) return;
    e.preventDefault();
    if (type && types[type]) return void addNode(type, p.x - 140, p.y - 20);
    if (aid) { const n = addNode('upload', p.x - 140, p.y - 20, { files: [aid] }); return void refreshNode(n.id); }
    const nd = e.target.closest('.cv-node'), tn = nd && nodeById(nd.dataset.id);
    const fe = e.target.closest && e.target.closest('.sf-folder');   // soltou em cima de uma pasta do Style Folder: entra nela
    uploadFiles([...e.dataTransfer.files], { x: p.x - 140, y: p.y - 20 }, tn && ['upload', 'style_folder'].includes(tn.type) ? tn : null, fe ? fe.dataset.folder : '');
  });

  function paintAssets() {
    assetsPanel.classList.toggle('hidden', !S.assetsOpen);
    assetsBtn.querySelector('span').textContent = t('Arquivos') + ' (' + S.cv.assets.length + ')';
    if (!S.assetsOpen) return;
    const input = h('input', { type: 'file', multiple: true, accept: 'image/*,video/*,audio/*,.zip,.rar,.7z,.tar,.tgz,.cbz,.cbr', class: 'hidden', onchange: (e) => { const r = surface.getBoundingClientRect(); const p = toWorld(r.left + 120, r.top + 80); uploadFiles([...e.target.files], p); e.target.value = ''; } });
    const items = [...S.cv.assets].reverse().map((a) => h('div', { class: 'cv-asset', draggable: 'true', title: a.prompt || a.name, ondragstart: (e) => { e.dataTransfer.setData('text/flow-asset', a.id); e.dataTransfer.effectAllowed = 'copy'; } },
      h('div', { class: 'pv', onclick: () => preview(a) }, a.kind === 'image' ? h('img', { src: c.url(a), loading: 'lazy', draggable: 'false' }) : a.kind === 'video' ? h('video', { src: c.url(a) + '#t=0.1', preload: 'metadata', muted: true }) : icon('audio', 28)),
      h('span', { class: 'kd' }, a.kind === 'image' ? t('imagem') : a.kind === 'video' ? t('vídeo') : t('áudio')),
      h('div', { class: 'cap' }, a.name),
      h('div', { class: 'acts' },
        h('a', { href: c.url(a) + '?download=1', title: t('Baixar') }, icon('download', 12)),
        h('button', { title: t('Apagar'), onclick: async () => {
          if (!(await confirmDialog(t('Apagar “{n}”? Ela sai de todos os nós e do Editor.', { n: a.name })))) return;
          try { await save(); await api(`/api/projects/${cid}/assets/${a.id}`, { method: 'DELETE' }); await reload(); } catch (e) { toast(e.message, 'err'); }
        } }, icon('trash', 12)))));
    fill(assetsPanel, h('div', { class: 'hd' }, h('span', { class: 'grow' }, t('Arquivos do projeto')), h('button', { class: 'btn sm', onclick: () => input.click() }, icon('plus', 13), t('Enviar')), input),
      S.cv.assets.length ? h('div', { class: 'lst' }, items) : h('div', { class: 'dim small', style: { padding: '16px' } }, t('Tudo que você envia ou gera aparece aqui. Arraste um arquivo para o projeto para usá-lo.')));
  }

  function preview(a, list) {
    const items = list && list.length ? list : [a];
    let i = Math.max(0, items.findIndex((x) => x.id === a.id));
    const box = h('div', { class: 'cv-lb', onclick: (e) => { if (e.target === box) close(); } });
    const close = () => { box.remove(); document.removeEventListener('keydown', key); };
    const key = (e) => { if (e.key === 'Escape') close(); else if (e.key === 'ArrowRight' && i < items.length - 1) { i++; paint(); } else if (e.key === 'ArrowLeft' && i > 0) { i--; paint(); } };
    function paint() {
      const x = items[i];
      fill(box, x.kind === 'image' ? h('img', { src: c.url(x) }) : x.kind === 'video' ? h('video', { src: c.url(x), controls: true, autoplay: true }) : h('audio', { src: c.url(x), controls: true, autoplay: true }),
        h('div', { class: 'bar2' }, items.length > 1 ? h('button', { class: 'btn', disabled: i === 0, onclick: () => { i--; paint(); } }, '‹') : null,
          h('span', { class: 'chip', style: { maxWidth: '50vw', overflow: 'hidden', textOverflow: 'ellipsis' } }, x.prompt || x.name),
          h('a', { class: 'btn', href: c.url(x) + '?download=1' }, icon('download', 14), t('Baixar')),
          items.length > 1 ? h('button', { class: 'btn', disabled: i === items.length - 1, onclick: () => { i++; paint(); } }, '›') : null,
          h('button', { class: 'btn', onclick: close }, t('Fechar'))));
    }
    paint(); document.body.appendChild(box); document.addEventListener('keydown', key);
  }

  // ---------------------------------------------------------------------------------------------- execução
  const setBusy = (on) => { rootEl.classList.toggle('running', on); runBtn.disabled = on; cancelBtn.classList.toggle('hidden', !on); };
  async function run(ids, force) {
    if (S.job) return;
    await save();
    let r;
    try { r = await api(`/api/projects/${cid}/run`, { method: 'POST', body: { nodes: ids, force: !!force, team: team.get() } }); }
    catch (e) { if (e.status === 409) { try { r = JSON.parse(e.message); } catch (er) { /* ignore */ } } if (!r) return toast(e.message, 'err'); }
    attach(r.job_id);
  }
  function attach(jobId) {
    S.job = jobId; S.states = {}; setBusy(true); S.summary = null;
    S.stopEv = events('/api/jobs/' + jobId + '/events', onEvent, () => finishRun());
  }
  function onEvent(ev) {
    if (ev.type === 'start') { for (const id of ev.nodes) S.states[id] = { state: 'queued' }; for (const id of ev.nodes) refreshNode(id); }
    else if (ev.type === 'node') {
      S.states[ev.id] = { state: ev.state, message: ev.message, warnings: ev.warnings, note: '' };
      if (ev.state === 'done' || ev.state === 'cached') { /* o resultado vem do servidor no fim */ }
      refreshNode(ev.id);
    } else if (ev.type === 'note') { const s = S.states[ev.node]; if (s) { s.note = ev.message; const r = el[ev.node] && el[ev.node].querySelector('.res .run'); if (r) r.lastChild.textContent = ev.message; } }
    else if (ev.type === 'summary') S.summary = ev;
    else if (ev.type === 'error') toast(ev.message, 'err');
    else if (ev.type === 'cancelled') toast(t('Execução cancelada.'));
  }
  async function finishRun() {
    const sum = S.summary;
    S.job = ''; setBusy(false);
    const errs = Object.values(S.states).filter((x) => x.state === 'error');
    const msgs = Object.fromEntries(Object.entries(S.states).filter(([, x]) => x.state === 'error').map(([id, x]) => [id, x.message]));
    await reload();
    for (const [id, m] of Object.entries(msgs)) { const n = nodeById(id); if (n && !n.result.error) { n.result.state = 'error'; n.result.error = m; refreshNode(id); } }
    if (errs.length) toast(t('{n} nó(s) com erro. Veja a mensagem no nó.', { n: errs.length }), 'err');
    else if (sum) toast(sum.ran ? t('Pronto: {n} nó(s) gerado(s).', { n: sum.ran }) + (sum.cached ? ' ' + t('{n} vieram do cache.', { n: sum.cached }) : '') : t('Nada a gerar: tudo já está atualizado.'), 'ok');
  }
  async function reload() {
    const fresh = await api('/api/projects/' + cid);
    S.cv = fresh; S.states = {};
    nodesLayer.replaceChildren(); for (const k of Object.keys(el)) delete el[k];
    for (const n of S.cv.nodes) addToDom(n);
    requestAnimationFrame(() => { drawEdges(); paintStale(); }); paintAssets(); paintHint();
  }

  // ---------------------------------------------------------------------------------------------- Editor (linha do tempo)
  async function openTimeline(n) {
    const mod = await import('../canvas_timeline.js');
    await mod.openTimeline({
      cid, node: n, cv: S.cv, url: c.url, meta,
      connected: () => connectedOutputs(n),
      onChange: () => { dirty(); refreshNode(n.id); },
      exportNow: async () => { await save(); await run([n.id], true); },
      autofill: async () => { await save(); const r = await api(`/api/projects/${cid}/nodes/${n.id}/autofill`, { method: 'POST' }); n.params.timeline = r.timeline; dirty(); return r.timeline; },
    });
    refreshNode(n.id);
  }
  // saídas dos nós ligados ao Editor (cada arquivo, ou o texto), para a "bandeja" do Editor
  function connectedOutputs(ed) {
    const out = [];
    for (const e of S.cv.edges.filter((x) => x.to === ed.id && x.port === 'clips')) {
      const src = nodeById(e.from); if (!src) continue;
      const ids = src.type === 'upload' ? src.params.files : (src.result.state === 'done' ? src.result.assets : []);
      ids.forEach((id, idx) => { const a = c.asset(id); if (a) out.push({ node: src.id, idx, label: src.title || t(LABEL[src.type]), asset: a }); });
      if (src.type === 'text' && src.params.text.trim()) out.push({ node: src.id, idx: 0, label: src.title || t(LABEL.text), text: src.params.text });
    }
    return out;
  }

  // ---------------------------------------------------------------------------------------------- teclado e ciclo de vida
  const onKey = (e) => {
    if (!document.body.contains(rootEl)) return document.removeEventListener('keydown', onKey);
    if (e.target.closest('input,textarea,select,[contenteditable]') || document.querySelector('.tl-bg,.cv-lb,.modal-bg')) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && !S.job) {
      if (S.selEdge) { e.preventDefault(); removeEdge(S.selEdge); } else if (S.sel) { e.preventDefault(); removeNode(S.sel); }
    } else if (e.key === 'Escape') select('', '');
  };
  document.addEventListener('keydown', onKey);
  addEventListener('hashchange', onLeave, { once: true });
  const onUnload = () => { if (!document.body.contains(rootEl)) return removeEventListener('beforeunload', onUnload); if (S.saveState === 'dirty') save(); };
  addEventListener('beforeunload', onUnload);

  for (const n of S.cv.nodes) addToDom(n);
  applyView(); paintSaved(); paintAssets(); paintHint();
  requestAnimationFrame(() => {
    if (cv.viewport.x === 0 && cv.viewport.y === 0 && cv.viewport.zoom === 1) fit(); else drawEdges();
    paintStale();
  });
  if (cv.job_id) attach(cv.job_id);
}
