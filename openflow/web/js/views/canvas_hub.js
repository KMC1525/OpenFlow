import { api, events } from '../api.js';
import { t } from '../i18n.js';
import { fill, h, icon, toast } from '../ui.js';

// Barra de pesquisa de modelos no topo do Canvas (Hugging Face): procura, mostra TODAS as quantizações de cada modelo, baixa e passa a usar — no nó selecionado e como padrão do tipo.
const CAPS = [['image', 'Imagem'], ['video', 'Vídeo'], ['sound', 'Som'], ['voice', 'Voz'], ['stt', 'Transcrição'], ['text', 'Texto']];
const GGUF_CAPS = ['image', 'video', 'text'];   // os únicos com provedor GGUF no OpenFlow; os outros usam o formato original (fp32/fp16/bf16)
const NODE_OF = { image: 'image', video: 'video', sound: 'sound', voice: 'voice', stt: 'transcribe', text: 'llm' };
const QUALITY = { very_low: 'qualidade muito baixa', low: 'qualidade baixa', good: 'boa qualidade', very_good: 'ótima qualidade', high: 'alta qualidade', lossless: 'quase sem perdas', original: 'original' };
const PREC_HINT = { fp32: 'Maior e mais lento; funciona em qualquer computador', fp16: 'Metade do tamanho; ideal com placa de vídeo', bf16: 'Como o fp16, com a faixa do fp32' };
const bytes = (n) => (n >= 1 << 30 ? (n / (1 << 30)).toFixed(1) + ' GB' : n >= 1 << 20 ? Math.round(n / (1 << 20)) + ' MB' : n ? Math.round(n / 1024) + ' KB' : '?');
const compact = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'k' : String(n || 0));

// c: { cid, selected(): nó selecionado | null, onUsed(res, node) }
export function modelSearchBar(c) {
  const st = { cap: 'image', fmt: 'gguf', q: '', results: null, open: null, busy: false, err: '' };
  const capSel = h('select', { id: 'hub-cap', title: t('Tipo de modelo'), onchange: (e) => { st.cap = e.target.value; if (!GGUF_CAPS.includes(st.cap)) st.fmt = 'original'; syncFmt(); if (st.q) search(); } }, CAPS.map(([v, l]) => h('option', { value: v }, t(l))));
  const fmtSel = h('select', { id: 'hub-fmt', title: t('Formato'), onchange: (e) => { st.fmt = e.target.value; if (st.q) search(); } }, h('option', { value: 'gguf' }, t('GGUF · quantizações')), h('option', { value: 'original' }, t('Original · fp32/fp16/bf16')));
  const syncFmt = () => { fmtSel.value = st.fmt; fmtSel.disabled = !GGUF_CAPS.includes(st.cap); };
  const input = h('input', { type: 'search', id: 'hub-q', placeholder: t('Buscar modelos no Hugging Face…'), 'aria-label': t('Buscar modelos no Hugging Face'), autocomplete: 'off', onkeydown: (e) => { if (e.key === 'Enter') { st.q = input.value.trim(); search(); } else if (e.key === 'Escape') close(); }, onfocus: () => { openPanel(); } });
  const panel = h('div', { class: 'cv-hub-panel hidden', id: 'hub-panel' });
  const filters = h('div', { class: 'hub-filters' }, h('label', { class: 'dim small' }, t('Tipo'), ' ', capSel), h('label', { class: 'dim small' }, t('Formato'), ' ', fmtSel));
  const root = h('div', { class: 'cv-hub', role: 'search' }, input, h('button', { class: 'btn icon sm', type: 'button', id: 'hub-go', title: t('Buscar'), 'aria-label': t('Buscar modelos'), onclick: () => { st.q = input.value.trim(); search(); } }, icon('search', 15)), panel);
  syncFmt();
  const openPanel = () => { panel.classList.remove('hidden'); paint(); };
  const close = () => panel.classList.add('hidden');
  document.addEventListener('pointerdown', (e) => { if (!root.isConnected) return; if (!root.contains(e.target)) close(); });

  let searchSeq = 0;   // só a resposta mais recente vale (uma busca lenta e antiga não apaga a nova)
  async function search() {
    if (!st.q) return toast(t('Escreva o nome ou o assunto do modelo (ex.: flux, sdxl, whisper, wan).'));
    const my = ++searchSeq;
    st.busy = true; st.err = ''; st.open = null; openPanel();
    try { const r = await api(`/api/media/hub/search?q=${encodeURIComponent(st.q)}&cap=${st.cap}&format=${st.fmt}`); if (my !== searchSeq) return; st.results = r.results; st.fmt = r.format; syncFmt(); } catch (e) { if (my !== searchSeq) return; st.err = e.message; st.results = []; }
    st.busy = false; paint();
  }

  const downloaded = async (kind) => { try { return new Set((await api('/api/hf/local?kind=' + kind)).models.map((m) => m.name)); } catch (e) { return new Set(); } };

  function useModel(provider, model, label) {
    const n = c.selected();
    return api('/api/media/hub/use', { method: 'POST', body: { cap: st.cap, provider, model, canvas: c.cid, node: n && n.type === NODE_OF[st.cap] ? n.id : '' } }).then((res) => {
      toast(t('Usando {m} para {c}.', { m: model, c: t((CAPS.find((x) => x[0] === st.cap) || [0, st.cap])[1]).toLowerCase() }) + (res.node_updated ? ' ' + t('O nó selecionado foi atualizado.') : ''), 'ok');
      c.onUsed(res, res.node_updated ? n : null);
    }).catch((e) => toast(e.message, 'err'));
  }

  function progressRow(slot, label, jid, done) {
    const bar = h('i'), txt = h('span', { class: 'small muted' }, '0%');
    fill(slot, h('div', { class: 'hub-prog' }, h('div', { class: 'row', style: { gap: '8px', marginBottom: '6px' } }, h('span', { class: 'mono small' }, label), h('span', { class: 'grow' }), txt, h('button', { class: 'btn sm', type: 'button', onclick: () => api('/api/jobs/' + jid + '/cancel', { method: 'POST' }).catch(() => {}) }, t('Cancelar'))), h('div', { class: 'bar' }, bar)));
    events('/api/jobs/' + jid + '/events', (ev) => {
      if (ev.type === 'progress' && ev.total) { const pc = Math.min(1, ev.done / ev.total); bar.style.width = Math.round(pc * 100) + '%'; txt.textContent = Math.round(pc * 100) + '% · ' + bytes(ev.done) + ' / ' + bytes(ev.total); }
      else if (ev.type === 'done') { toast(t('Download concluído'), 'ok'); done(true); }
      else if (ev.type === 'error') { toast(ev.message, 'err'); done(false); }
      else if (ev.type === 'cancelled') { toast(t('Download cancelado')); done(false); }
    });
  }

  async function detail(repo, slot) {
    fill(slot, h('div', { class: 'muted small' }, h('span', { class: 'spinner' }), ' ', t('Consultando as versões…')));
    try {
      if (st.fmt === 'gguf') {
        const kind = st.cap, have = await downloaded(kind);
        const r = await api('/api/hf/files?repo=' + encodeURIComponent(repo));
        if (!r.files.length) return fill(slot, h('div', { class: 'muted small' }, t('Este repositório não tem arquivos GGUF utilizáveis.')));
        const draw = () => fill(slot, h('div', { class: 'muted small', style: { marginBottom: '6px' } }, t('{n} quantização(ões): menos bits = arquivo menor e mais rápido, com algum custo de qualidade.', { n: r.files.length })),
          r.files.map((f) => {
            const row = h('div', { class: 'hub-q', dataset: { quant: f.quant || '', file: f.name } });
            const mine = have.has(f.name.split('/').pop());
            fill(row, h('div', { class: 'grow' }, h('div', { class: 'row', style: { gap: '8px', flexWrap: 'wrap' } }, h('b', null, f.quant || t('sem rótulo')), f.recommended ? h('span', { class: 'chip on' }, t('Recomendada')) : null,
              f.fits ? h('span', { class: 'chip' }, t('cabe na sua RAM')) : h('span', { class: 'chip warn' }, t('pesada para a sua RAM')), mine ? h('span', { class: 'chip on' }, t('baixado')) : null),
              h('div', { class: 'dim small' }, (f.bits ? f.bits + ' bits · ' : '') + t(QUALITY[f.quality] || '') + (f.parts > 1 ? ' · ' + t('{n} partes', { n: f.parts }) : ''))),
              h('span', { class: 'chip solid' }, bytes(f.size)),
              mine ? h('button', { class: 'btn sm primary', type: 'button', dataset: { act: 'use' }, onclick: () => (st.cap === 'text' ? useModel('local_hf', f.name.split('/').pop()) : useModel('gguf_local', f.name.split('/').pop())) }, icon('check', 13), t('Usar'))
                : h('button', { class: 'btn sm', type: 'button', dataset: { act: 'download' }, onclick: async () => {
                  let jid; try { jid = (await api('/api/hf/download', { method: 'POST', body: { repo, files: f.files, sizes: f.sizes, quant: f.quant || 'sem-rotulo', kind } })).job_id; } catch (e) { return toast(e.message, 'err'); }
                  progressRow(row, repo.split('/')[1] + ' · ' + (f.quant || ''), jid, async (ok) => { if (ok) have.add(f.name.split('/').pop()); draw(); });
                } }, icon('download', 13), t('Baixar')));
            return row;
          }));
        draw();
      } else {
        const [o, q] = await Promise.all([api('/api/media/local/options?model=' + encodeURIComponent(repo)), api('/api/media/local/quants?model=' + encodeURIComponent(repo)).catch(() => ({ variants: [] }))]);
        let state = {}; try { state = await api('/api/media/local/state'); } catch (e) { /* sem estado */ }
        const prec = (state.models && state.models[st.cap] && state.models[st.cap].model === repo && state.models[st.cap].precision) || '';
        const draw = (cur) => fill(slot, !state.libs ? h('div', { class: 'errbox', style: { marginBottom: '8px' } }, t('Instale as bibliotecas dos modelos locais para baixar:') + ' pip install "openflow[media]"  (' + t('ou rode') + ' flow libs)') : null,
          h('div', { class: 'muted small', style: { marginBottom: '6px' } }, t('Precisão do download: menos bits = menor; o fp16 pede placa de vídeo.')),
          o.options.map((p) => { const row = h('div', { class: 'hub-q', dataset: { quant: p.id } });
            fill(row, h('div', { class: 'grow' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, p.id), p.recommended ? h('span', { class: 'chip on' }, t('Recomendada')) : null, cur === p.id ? h('span', { class: 'chip on' }, t('baixado')) : null), h('div', { class: 'dim small' }, t(PREC_HINT[p.id] || ''))),
              h('span', { class: 'chip solid' }, bytes(p.size)),
              cur === p.id ? h('button', { class: 'btn sm primary', type: 'button', dataset: { act: 'use' }, onclick: () => useModel('local_hf', repo) }, icon('check', 13), t('Usar'))
                : h('button', { class: 'btn sm', type: 'button', dataset: { act: 'download' }, disabled: !state.libs, onclick: async () => {
                  let jid; try { jid = (await api('/api/media/local/download', { method: 'POST', body: { model: repo, precision: p.id } })).job_id; } catch (e) { return toast(e.message, 'err'); }
                  progressRow(row, repo.split('/')[1] + ' · ' + p.id, jid, (ok) => draw(ok ? p.id : cur));
                } }, icon('download', 13), t('Baixar')));
            return row; }),
          (q.variants || []).length ? [h('div', { class: 'muted small', style: { margin: '10px 0 6px' } }, t('Quantizações menores (da comunidade, feitas por terceiros)')), (q.variants || []).map((v) => h('div', { class: 'hub-q qv', dataset: { variant: v.id } },
            h('div', { class: 'grow' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', { class: 'mono small' }, v.id), h('span', { class: 'chip' }, v.kind)), h('div', { class: 'dim small' }, t(v.note))), h('span', { class: 'chip solid' }, v.size ? bytes(v.size) : '?'),
            v.loadable ? h('button', { class: 'btn sm', type: 'button', onclick: () => { st.results = [{ id: v.id, downloads: v.downloads, likes: 0 }].concat(st.results.filter((x) => x.id !== v.id)); st.open = v.id; paint(); } }, t('Ver precisões')) : h('span', { class: 'dim small' }, t('não suportada aqui'))))] : null);
        draw(prec);
      }
    } catch (e) { fill(slot, h('div', { class: 'errbox' }, e.message)); }
  }

  function paint() {
    const hint = st.fmt === 'gguf' ? t('GGUF: cada arquivo é uma quantização do mesmo modelo; você escolhe qual baixar.') : t('Formato original (diffusers/transformers): você escolhe a precisão antes do download.');
    fill(panel, filters, h('div', { class: 'hub-head muted small' }, hint),
      st.busy ? h('div', { class: 'muted small', style: { padding: '12px' } }, h('span', { class: 'spinner' }), ' ', t('Procurando…')) : st.err ? h('div', { class: 'errbox', style: { margin: '8px' } }, st.err)
        : (st.results || []).length ? (st.results || []).map((r) => {
          const slot = h('div', { class: 'hub-detail' + (st.open === r.id ? '' : ' hidden') });
          const row = h('div', { class: 'hub-r' + (st.open === r.id ? ' on' : ''), dataset: { repo: r.id }, onclick: () => { st.open = st.open === r.id ? null : r.id; paint(); } },
            icon('chev', 12), h('span', { class: 'nm mono' }, r.id), h('span', { class: 'muted small' }, '↓ ' + compact(r.downloads) + (r.likes ? ' · ♥ ' + compact(r.likes) : '')));
          if (st.open === r.id) setTimeout(() => detail(r.id, slot), 0);
          return h('div', { class: 'hub-item' }, row, slot);
        }) : h('div', { class: 'muted small', style: { padding: '12px' } }, st.results ? t('Nada encontrado. Tente outro nome.') : ''));
  }
  return { el: root, search: (q) => { input.value = q; st.q = q; search(); } };
}
