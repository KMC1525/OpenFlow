import { api, events } from '../api.js';
import { t } from '../i18n.js';
import { confirmDialog, debounce, fmtBytes, fmtEta, h, icon, toast } from '../ui.js';
import { GGUF_KINDS } from '../model_labels.js';
import { go } from '../main.js';

// Tela «Biblioteca» (v0.23): o que existe neste computador — modelos baixados (e como baixar mais), arquivos gerados nos projetos e os downloads (em andamento e concluídos).
const TABS = [['models', 'Modelos'], ['files', 'Arquivos gerados'], ['downloads', 'Downloads']];

export default async function render(root, ctx) {
  let tab = (ctx && ctx.tab) || 'models';
  if (!TABS.some(([k]) => k === tab)) tab = 'models';
  let stop = () => {};   // encerra o que a aba atual mantém ligado (atualização dos downloads)
  const body = h('div', { id: 'lib-body' });
  const seg = h('div', { class: 'seg', role: 'tablist', 'aria-label': t('Seções da Biblioteca'), style: { marginBottom: '16px', flexWrap: 'wrap' } });
  const paintTabs = () => seg.replaceChildren(...TABS.map(([k, l]) => h('button', { type: 'button', role: 'tab', id: 'lib-tab-' + k, 'aria-selected': tab === k ? 'true' : 'false', class: tab === k ? 'on' : '',
    onclick: () => { if (tab !== k) { tab = k; show(); } } }, t(l))));

  async function show() {
    stop(); stop = () => {};
    paintTabs();
    const holder = h('div');
    body.replaceChildren(holder);
    if (tab === 'models') { const m = await import('./models.js'); await m.default(holder, { ...(ctx || {}), embedded: true }); }
    else if (tab === 'files') await filesTab(holder);
    else stop = await downloadsTab(holder);
  }

  // ---------------------------------------------------------------------------------------------- arquivos gerados
  async function filesTab(box) {
    let kind = '', source = 'generated', seq = 0;
    const grid = h('div', { class: 'libgrid', 'aria-live': 'polite' });
    const q = h('input', { type: 'search', id: 'lib-q', 'aria-label': t('Buscar arquivos'), placeholder: t('Buscar por nome, projeto ou modelo…'), autocomplete: 'off', oninput: debounce(load, 250) });
    const kindSel = h('select', { id: 'lib-kind', 'aria-label': t('Tipo de arquivo'), onchange: () => { kind = kindSel.value; load(); } },
      [['', 'Todos os tipos'], ['image', 'Imagens'], ['video', 'Vídeos'], ['audio', 'Sons']].map(([v, l]) => h('option', { value: v }, t(l))));
    const srcSel = h('select', { id: 'lib-source', 'aria-label': t('Origem'), onchange: () => { source = srcSel.value; load(); } },
      [['generated', 'Gerados por modelos'], ['upload', 'Enviados por você'], ['all', 'Todos']].map(([v, l]) => h('option', { value: v }, t(l))));
    const count = h('span', { class: 'dim small', id: 'lib-count' });
    box.append(h('div', { class: 'card' }, h('div', { class: 'row nw', style: { marginBottom: '12px', flexWrap: 'wrap' } }, h('div', { class: 'search', style: { maxWidth: 'none', flex: 1, minWidth: '180px' } }, icon('search', 17), q), kindSel, srcSel, count), grid));

    const thumb = (f) => f.kind === 'image' ? h('img', { src: f.url, alt: f.name, loading: 'lazy' })
      : f.kind === 'video' ? h('video', { src: f.url, preload: 'metadata', muted: true, 'aria-label': f.name })
        : h('div', { class: 'ico' }, icon('audio', 30));
    async function load() {
      const my = ++seq;
      try {
        const r = await api('/api/library/files?kind=' + kind + '&source=' + source + '&q=' + encodeURIComponent(q.value.trim()));
        if (my !== seq) return;
        count.textContent = t('{n} arquivo(s)', { n: r.files.length });
        grid.replaceChildren(...(r.files.length ? r.files.map((f) => {
          const card = h('div', { class: 'libfile', 'data-asset': f.id },
            h('a', { class: 'th', href: f.url, target: '_blank', rel: 'noopener', title: t('Abrir {n}', { n: f.name }) }, thumb(f)),
            h('div', { class: 'meta' }, h('div', { class: 'nm', title: f.name }, f.name),
              h('div', { class: 'dim small' }, [f.model || f.provider, fmtBytes(f.bytes), f.w ? f.w + '×' + f.h : '', f.duration ? Math.round(f.duration) + ' s' : ''].filter(Boolean).join(' · ')),
              h('a', { class: 'small', href: '#/project/' + f.project, title: t('Abrir o projeto') }, f.project_name)),
            h('div', { class: 'row', style: { gap: '4px' } },
              h('a', { class: 'btn sm ghost', href: f.url, download: f.name, title: t('Baixar {n}', { n: f.name }), 'aria-label': t('Baixar {n}', { n: f.name }) }, icon('download', 13)),
              h('button', { class: 'btn sm ghost danger', type: 'button', title: t('Apagar {n}', { n: f.name }), 'aria-label': t('Apagar {n}', { n: f.name }), onclick: async () => {
                if (!(await confirmDialog(t('Apagar o arquivo {n}? Ele some do projeto «{p}» também.', { n: f.name, p: f.project_name })))) return;
                try { await api('/api/projects/' + f.project + '/assets/' + f.id, { method: 'DELETE' }); load(); } catch (e) { toast(e.message, 'err'); }
              } }, icon('trash', 13))));
          return card;
        }) : [h('div', { class: 'muted small' }, source === 'generated' ? t('Nenhum arquivo gerado ainda. Rode um nó de imagem, vídeo, som ou voz num projeto.') : t('Nenhum arquivo encontrado.'))]));
      } catch (e) { if (my === seq) grid.replaceChildren(h('div', { class: 'res err', role: 'alert' }, e.message)); }
    }
    await load();
  }

  // ---------------------------------------------------------------------------------------------- downloads
  async function downloadsTab(box) {
    const active = h('div', { class: 'col', id: 'lib-active', 'aria-live': 'polite' }), recent = h('div', { class: 'col', id: 'lib-recent' }), done = h('div', { class: 'col', id: 'lib-done' });
    box.append(h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', null, t('Em andamento')), active),
      h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', null, t('Recentes (desta sessão)')), recent),
      h('div', { class: 'card' }, h('h3', null, t('Modelos baixados')), h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Todos os modelos GGUF neste computador, dos mais novos aos mais antigos.')), done));
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
            : [h('div', { class: 'muted small' }, t('Nenhum modelo baixado ainda.'), ' ', h('button', { class: 'btn sm', type: 'button', onclick: () => { tab = 'models'; show(); } }, t('Baixar modelos')))]));
        }
        timer = setTimeout(tick, run.length ? 1000 : 4000);   // mais rápido enquanto há download; devagar quando parado
      } catch (e) { if (alive) timer = setTimeout(tick, 5000); }
    }
    await tick();
    return () => { alive = false; clearTimeout(timer); };
  }

  root.replaceChildren(h('div', { class: 'page narrow cfg' }, h('div', { class: 'page-h' }, h('div', null, h('h1', null, t('Biblioteca')),
    h('p', null, t('Os modelos baixados, os arquivos gerados nos seus projetos e os downloads.')))), seg, body));
  await show();
  const mo = new MutationObserver(() => { if (!root.isConnected || !document.getElementById('lib-body')) { stop(); mo.disconnect(); } });   // saiu da tela: para de atualizar
  mo.observe(document.body, { childList: true, subtree: true });
}
