// v0.43 — acompanhar os downloads de modelos dentro do Canvas: um botão ao lado direito da barra de pesquisa de modelos mostra quantos downloads estão rodando (com uma barrinha de progresso geral)
// e abre um painel com o progresso de cada um (tamanho, velocidade, tempo restante, cancelar) e os recentes. Vem de /api/library/downloads (os mesmos dados da aba Downloads da Biblioteca).
import { api } from './api.js';
import { t } from './i18n.js';
import { fmtBytes, fmtEta, h, icon } from './ui.js';

export function downloadsIndicator() {
  const st = { list: [], open: false, ok: true };
  const badge = h('span', { class: 'cv-dl-badge hidden', id: 'cv-dl-badge' }, '0');
  const mini = h('i');
  const btn = h('button', { class: 'btn icon sm cv-dl-btn', type: 'button', id: 'cv-dl-btn', 'aria-haspopup': 'dialog', 'aria-expanded': 'false', title: t('Downloads de modelos'), 'aria-label': t('Downloads de modelos'), onclick: () => toggle() },
    icon('download', 15), badge, h('span', { class: 'cv-dl-bar', 'aria-hidden': 'true' }, mini));
  const panel = h('div', { class: 'cv-dl-panel hidden', id: 'cv-dl-panel', role: 'dialog', 'aria-label': t('Downloads de modelos'), 'aria-live': 'polite' });
  const root = h('div', { class: 'cv-dl', id: 'cv-dl' }, btn, panel);
  let timer = 0, alive = true;

  const row = (d) => {
    const pc = d.total ? Math.min(1, d.done / d.total) : 0, run = d.status === 'running';
    return h('div', { class: 'cv-dl-row' + (run ? ' run' : ''), dataset: { job: d.id, status: d.status } },
      h('div', { class: 'row nw', style: { gap: '8px' } }, h('div', { class: 'grow', style: { minWidth: 0 } }, h('div', { class: 'mono cv-dl-t', title: d.title }, d.title), h('div', { class: 'dim small' }, [t(d.label), d.repo].filter(Boolean).join(' · '))),
        run ? h('button', { class: 'btn sm', type: 'button', dataset: { act: 'cancel' }, onclick: () => api('/api/jobs/' + d.id + '/cancel', { method: 'POST' }).then(tick).catch(() => {}) }, t('Cancelar'))
          : h('span', { class: 'chip ' + (d.status === 'done' ? 'on' : d.status === 'error' ? 'warn' : '') }, d.status === 'done' ? '✓ ' + t('Concluído') : d.status === 'error' ? '⚠ ' + t('Falhou') : t('Cancelado'))),
      run ? h('div', { class: 'bar', role: 'progressbar', 'aria-label': d.title, 'aria-valuenow': Math.round(pc * 100) }, h('i', { style: { width: Math.round(pc * 100) + '%' } })) : null,
      run ? h('div', { class: 'dim small' }, d.total ? Math.round(pc * 100) + '% · ' + fmtBytes(d.done) + ' / ' + fmtBytes(d.total) + (d.speed ? ' · ' + fmtBytes(d.speed) + '/s ' + fmtEta(d.eta) : '') : t('Preparando…')) : null,
      run && d.note ? h('div', { class: 'dim small' }, d.note) : null,
      d.status === 'error' && d.error ? h('div', { class: 'res err small' }, d.error) : null);
  };

  function paint() {
    const run = st.list.filter((d) => d.status === 'running'), rest = st.list.filter((d) => d.status !== 'running').slice(0, 8);
    badge.textContent = String(run.length);
    badge.classList.toggle('hidden', !run.length);
    btn.classList.toggle('busy', run.length > 0);
    const tot = run.reduce((a, d) => a + (d.total || 0), 0), don = run.reduce((a, d) => a + Math.min(d.done || 0, d.total || 0), 0);
    mini.style.width = (tot ? Math.round(don / tot * 100) : 0) + '%';
    btn.title = run.length ? t('{n} download(s) em andamento', { n: run.length }) : t('Downloads de modelos');
    if (!st.open) return;
    panel.replaceChildren(
      h('div', { class: 'cv-dl-head' }, h('b', null, t('Downloads de modelos')), h('span', { class: 'grow' })),
      ...(run.length ? run.map(row) : [h('div', { class: 'muted small cv-dl-empty' }, t('Nenhum download em andamento. Pesquise um modelo na barra ao lado e aperte Baixar.'))]),
      rest.length ? h('div', { class: 'cv-dl-sub muted small' }, t('Recentes (desta sessão)')) : null, ...rest.map(row));
  }

  async function tick() {
    clearTimeout(timer);
    if (!alive || !root.isConnected) { if (!root.isConnected && alive) timer = setTimeout(tick, 1500); return; }
    let running = 0;
    try { const r = await api('/api/library/downloads'); st.list = r.downloads || []; running = r.running || 0; st.ok = true; } catch (e) { st.ok = false; }
    paint();
    timer = setTimeout(tick, running || st.open ? 1000 : 4000);   // rápido enquanto há download (ou o painel está aberto); devagar quando parado
  }
  function toggle(force) {
    st.open = force === undefined ? !st.open : !!force;
    panel.classList.toggle('hidden', !st.open);
    btn.setAttribute('aria-expanded', st.open ? 'true' : 'false');
    if (st.open) { paint(); tick(); }
  }
  document.addEventListener('pointerdown', (e) => { if (st.open && root.isConnected && !root.contains(e.target)) toggle(false); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && st.open) toggle(false); });
  window.addEventListener('flow:downloads', (e) => { if (!root.isConnected) return; if (e && e.detail && e.detail.open) toggle(true); else tick(); });   // o painel de busca avisa quando um download começa
  tick();
  return { el: root, refresh: tick, open: () => toggle(true), stop: () => { alive = false; clearTimeout(timer); } };
}
