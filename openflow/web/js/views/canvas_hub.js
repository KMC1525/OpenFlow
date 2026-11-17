import { api, events } from '../api.js';
import { t } from '../i18n.js';
import { ROLE_LABEL } from '../labels.js';
import { fill, h, icon, toast } from '../ui.js';

// Barra de pesquisa de modelos no topo do Canvas (Hugging Face): procura, mostra TODAS as quantizações de cada modelo, baixa e passa a usar — no nó selecionado e como padrão do tipo.
const CAPS = [['image', 'Imagem'], ['video', 'Vídeo'], ['sound', 'Som'], ['voice', 'Voz'], ['stt', 'Transcrição'], ['model3d', '3D'], ['text', 'Texto'], ['tool', 'Modelos próprios']];
const GGUF_CAPS = ['image', 'video', 'text'];   // os únicos com provedor GGUF no OpenFlow
const BOTH_CAPS = ['image', 'video'];   // escolhem entre GGUF e o formato original (diffusers: fp32/fp16/bf16); o texto roda só GGUF (llama.cpp) e som, voz, transcrição e 3D só o formato original
const REPO_RE = /^[A-Za-z0-9][\w.-]{0,95}\/[A-Za-z0-9][\w.-]{0,95}$/;
const SOUND_CAPS = ['sound', 'voice', 'stt'];   // v0.65: pesquisam por assunto (música, efeitos, voz, dublagem…) e já abrem com os mais baixados
const NODE_OF = { image: 'image', video: 'video', sound: 'sound', voice: 'voice', stt: 'transcribe', text: 'llm', model3d: 'model3d', tool: 'ai_model' };
const QUALITY = { very_low: 'qualidade muito baixa', low: 'qualidade baixa', good: 'boa qualidade', very_good: 'ótima qualidade', high: 'alta qualidade', lossless: 'quase sem perdas', original: 'original' };
const PREC_HINT = { fp32: 'Maior e mais lento; funciona em qualquer computador', fp16: 'Metade do tamanho; ideal com placa de vídeo', bf16: 'Como o fp16, com a faixa do fp32' };
const bytes = (n) => (n >= 1 << 30 ? (n / (1 << 30)).toFixed(1) + ' GB' : n >= 1 << 20 ? Math.round(n / (1 << 20)) + ' MB' : n ? Math.round(n / 1024) + ' KB' : '?');
const compact = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'k' : String(n || 0));

// c: { cid, selected(): nó selecionado | null, onUsed(res, node) }
export function modelSearchBar(c) {
  const st = { cap: 'image', fmt: 'gguf', q: '', results: null, open: null, busy: false, err: '', cat: null, topic: '', topics: null, browsed: '' };
  const capSel = h('select', { id: 'hub-cap', title: t('Tipo de modelo'), onchange: (e) => { st.cap = e.target.value; st.topic = ''; st.fmt = st.cap === 'text' ? 'gguf' : BOTH_CAPS.includes(st.cap) ? st.fmt : 'original'; st.results = null; st.open = null; syncFmt(); syncTopic(); if (st.q) search(); else paint(); } }, CAPS.map(([v, l]) => h('option', { value: v }, t(l))));
  const fmtSel = h('select', { id: 'hub-fmt', title: t('Formato'), onchange: (e) => { st.fmt = e.target.value; st.results = null; st.open = null; if (st.q) search(); else paint(); } }, h('option', { value: 'gguf' }, t('GGUF · quantizações')), h('option', { value: 'original' }, t('Original · fp32/fp16/bf16')));
  const topicSel = h('select', { id: 'hub-topic', title: t('Assunto'), onchange: (e) => { st.topic = e.target.value; st.results = null; st.open = null; if (st.q) search(); else paint(); } });
  const topicLabel = h('label', { class: 'dim small hidden', id: 'hub-topic-label' }, t('Assunto'), ' ', topicSel);
  const topicsOf = () => ((st.topics || {})[st.cap] || []);
  const syncTopic = () => {   // v0.65: o seletor de assunto aparece para som, voz e transcrição (os assuntos vêm do servidor)
    const list = topicsOf();
    if (!list.some((x) => x.id === st.topic)) st.topic = list.length ? list[0].id : '';
    fill(topicSel, ...list.map((x) => h('option', { value: x.id }, t(x.label))));
    topicSel.value = st.topic;
    topicLabel.classList.toggle('hidden', list.length < 2);
    input.placeholder = SOUND_CAPS.includes(st.cap) ? t('Buscar modelos de som: musicgen, whisper, voz em português…') : t('Buscar modelos no Hugging Face…');
  };
  const syncFmt = () => { fmtSel.value = st.fmt; fmtSel.disabled = !BOTH_CAPS.includes(st.cap); };
  const input = h('input', { type: 'search', id: 'hub-q', placeholder: t('Buscar modelos no Hugging Face…'), 'aria-label': t('Buscar modelos no Hugging Face'), autocomplete: 'off', onkeydown: (e) => { if (e.key === 'Enter') { st.q = input.value.trim(); search(); } else if (e.key === 'Escape') close(); }, onfocus: () => { openPanel(); } });
  const panel = h('div', { class: 'cv-hub-panel hidden', id: 'hub-panel' });
  const filters = h('div', { class: 'hub-filters' }, h('label', { class: 'dim small' }, t('Tipo'), ' ', capSel), topicLabel, h('label', { class: 'dim small' }, t('Formato'), ' ', fmtSel));
  const root = h('div', { class: 'cv-hub', role: 'search' }, input, h('button', { class: 'btn icon sm', type: 'button', id: 'hub-go', title: t('Buscar'), 'aria-label': t('Buscar modelos'), onclick: () => { st.q = input.value.trim(); search(); } }, icon('search', 15)), panel);
  syncFmt();
  api('/api/media/hub/topics').then((r) => { st.topics = r.topics; syncTopic(); if (!panel.classList.contains('hidden')) paint(); }).catch(() => { st.topics = {}; });
  // v0.83: o painel não passa da borda da tela (com a barra lateral aberta, o `92vw` o empurrava para fora em tablets)
  const fit = () => { const r = root.getBoundingClientRect(); panel.style.maxWidth = Math.max(260, document.documentElement.clientWidth - r.left - 10) + 'px'; };
  window.addEventListener('resize', fit);
  const openPanel = () => { panel.classList.remove('hidden'); fit(); paint(); };
  input.addEventListener('focus', () => { if (panel.classList.contains('hidden')) openPanel(); });   // ao clicar na barra já aparecem os recomendados
  // outras partes do app (avisos dos nós) pedem uma busca aqui: «flow:hub» { q, cap, fmt }
  const onHubEvent = (e) => { if (!root.isConnected) return; const d = (e && e.detail) || {}; if (d.cap && CAPS.some(([v]) => v === d.cap)) { st.cap = d.cap; capSel.value = d.cap; st.topic = d.topic || ''; st.results = null; } if (d.fmt) st.fmt = d.fmt; st.fmt = st.cap === 'text' ? 'gguf' : BOTH_CAPS.includes(st.cap) ? st.fmt : 'original'; syncFmt(); syncTopic(); input.focus(); if (d.q) { input.value = d.q; st.q = d.q; search(); } else openPanel(); };
  window.addEventListener('flow:hub', onHubEvent);
  const close = () => panel.classList.add('hidden');
  const onHubDown = (e) => { if (root.isConnected && !root.contains(e.target)) close(); };
  document.addEventListener('pointerdown', onHubDown);

  let searchSeq = 0;   // só a resposta mais recente vale (uma busca lenta e antiga não apaga a nova)
  async function search() {
    if (!st.q && !SOUND_CAPS.includes(st.cap)) return toast(t('Escreva o nome ou o assunto do modelo (ex.: flux, sdxl, whisper, wan).'));
    const my = ++searchSeq;
    st.busy = true; st.err = ''; st.open = null; openPanel();
    try { const r = await api(`/api/media/hub/search?q=${encodeURIComponent(st.q)}&cap=${st.cap}&format=${st.fmt}` + (SOUND_CAPS.includes(st.cap) ? '&topic=' + encodeURIComponent(st.topic) : '')); if (my !== searchSeq) return; st.results = r.results; st.fmt = r.format; syncFmt(); if (REPO_RE.test(st.q) && !st.results.some((x) => x.id.toLowerCase() === st.q.toLowerCase())) st.results = [{ id: st.q, downloads: 0, likes: 0 }].concat(st.results); if (REPO_RE.test(st.q) && st.results.length === 1) st.open = st.results[0].id; } catch (e) { if (my !== searchSeq) return; st.err = e.message; st.results = []; }
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
    window.dispatchEvent(new CustomEvent('flow:downloads'));   // o indicador ao lado da barra passa a acompanhar este download
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
        const r = await api('/api/hf/files?repo=' + encodeURIComponent(repo) + '&kind=' + encodeURIComponent(kind));
        if (!r.files.length) return fill(slot, h('div', { class: 'muted small' }, t('Este repositório não tem arquivos GGUF utilizáveis.')));
        const extras = () => [r.compat ? h('div', { class: 'errbox', style: { marginBottom: '8px' } }, t(r.compat.text)) : null,
          (r.support || []).length ? h('div', { class: 'comes small', style: { marginBottom: '6px' } }, icon('layers', 14), ' ', t('Vem junto, automaticamente:'), ' ', r.support.map((x) => h('span', { class: 'chip on', title: x.label }, t(ROLE_LABEL[x.role] || x.role) + (x.size ? ' · ' + bytes(x.size) : '')))) : null];
        // v0.81: as cinco faixas (Q2, Q3, Q4, Q6, Q8) de relance; as que o repositório não tem aparecem apagadas, com a saída (criar a partir de um arquivo baixado, usar na hora ou outro repositório)
        const tierBox = h('div', { class: 'tiers', dataset: { tiers: '1' }, style: { marginBottom: '8px' } });
        const paintTiers = (alts) => {
          const missing = (r.tiers || []).filter((x) => !x.has).map((x) => x.tier);
          fill(tierBox, h('div', { class: 'row', style: { gap: '6px', flexWrap: 'wrap', alignItems: 'center' } }, h('span', { class: 'muted small' }, t('Faixas:')),
            (r.tiers || []).map((x) => h('button', { type: 'button', class: 'chip' + (x.has ? (x.recommended ? ' on' : '') : ' warn'), dataset: { tier: x.tier, has: x.has ? '1' : '0' }, style: x.has ? {} : { opacity: '.55' },
              title: x.has ? t('Este repositório tem {q} ({s}).', { q: x.quant || x.tier, s: bytes(x.size) }) : t('Este repositório não tem {q}.', { q: x.tier }),
              onclick: () => { const row = x.has ? slot.querySelector('.hub-q[data-file="' + CSS.escape(x.name) + '"]') : null; if (row) row.scrollIntoView({ block: 'nearest' }); } }, x.tier + (x.has ? ' · ' + bytes(x.size) : '')))),
            missing.length ? h('div', { class: 'dim small', style: { marginTop: '4px' } }, t('Faltam: {q}. Crie uma faixa menor a partir de um arquivo baixado (Biblioteca → Modelos → «Criar faixa»), use-a na hora no nó (campo «Quantização ao carregar») ou procure outros repositórios deste modelo.', { q: missing.join(', ') })) : null,
            missing.length && !alts ? h('button', { class: 'btn sm', type: 'button', dataset: { act: 'tiers-alts' }, style: { marginTop: '4px' }, onclick: async (ev) => {
              ev.currentTarget.disabled = true; fill(tierBox, h('div', { class: 'muted small' }, t('Procurando outros repositórios do mesmo modelo…')));
              let a = []; try { a = (await api('/api/hf/tiers?alts=1&repo=' + encodeURIComponent(repo) + '&kind=' + encodeURIComponent(kind))).alternatives || []; } catch (e) { toast(e.message, 'err'); }
              paintTiers(a);
            } }, icon('search', 13), t('Procurar em outros repositórios')) : null,
            alts ? (alts.length ? alts.map((a) => h('div', { class: 'hub-q qv', dataset: { alt: a.repo } }, h('div', { class: 'grow' }, h('b', { class: 'mono small' }, a.repo), h('div', { class: 'dim small' }, a.missing_covered.map((q) => t('tem {q}', { q })).join(' · '))),
              h('button', { class: 'btn sm', type: 'button', onclick: () => { st.results = [{ id: a.repo, downloads: a.downloads, likes: 0 }].concat((st.results || []).filter((x) => x.id !== a.repo)); st.open = a.repo; paint(); } }, t('Abrir'))))
              : h('div', { class: 'dim small' }, t('Nenhum outro repositório deste modelo tem as faixas que faltam.'))) : null);
        };
        paintTiers(null);
        const draw = () => fill(slot, ...extras(), tierBox, h('div', { class: 'muted small', style: { marginBottom: '6px' } }, t('{n} quantização(ões): menos bits = arquivo menor e mais rápido, com algum custo de qualidade.', { n: r.files.length })),
          r.files.map((f) => {
            const row = h('div', { class: 'hub-q', dataset: { quant: f.quant || '', file: f.name } });
            const mine = have.has(f.name.split('/').pop());
            fill(row, h('div', { class: 'grow' }, h('div', { class: 'row', style: { gap: '8px', flexWrap: 'wrap' } }, h('b', null, f.quant || t('sem rótulo')), f.recommended ? h('span', { class: 'chip on' }, t('Recomendada')) : null,
              f.fits ? h('span', { class: 'chip' }, t('cabe na sua RAM')) : h('span', { class: 'chip warn' }, t('pesada para a sua RAM')), mine ? h('span', { class: 'chip on' }, t('baixado')) : null),
              h('div', { class: 'dim small' }, (f.bits ? f.bits + ' bits · ' : '') + t(QUALITY[f.quality] || '') + (f.parts > 1 ? ' · ' + t('{n} partes', { n: f.parts }) : ''))),
              h('span', { class: 'chip solid' }, bytes(f.size)),
              mine ? h('button', { class: 'btn sm primary', type: 'button', dataset: { act: 'use' }, onclick: () => (st.cap === 'text' ? useModel('local_hf', f.name.split('/').pop()) : useModel('gguf_local', f.name.split('/').pop())) }, icon('check', 13), t('Usar'))
                : h('button', { class: 'btn sm', type: 'button', dataset: { act: 'download' }, onclick: async () => {
                  let jid; try { jid = (await api('/api/hf/download', { method: 'POST', body: { repo, files: f.files, sizes: f.sizes, quant: f.quant || 'sem-rotulo', kind } })).job_id; } catch (e) { return toast(e.status === 409 ? t('Já há um download em andamento.') : e.message, 'err'); }
                  progressRow(row, repo.split('/')[1] + ' · ' + (f.quant || ''), jid, async (ok) => { if (ok) have.add(f.name.split('/').pop()); draw(); });
                } }, icon('download', 13), t('Baixar')));
            return row;
          }));
        draw();
      } else if (st.cap === 'tool') {
        // v0.82: modelos próprios (imagem → imagem) para o nó «Modelo PyTorch/TensorFlow»: escolhe o framework e baixa só o arquivo do modelo
        const FW = { torch: ['PyTorch', 'TorchScript / torch.export (.pt, .pth, .pt2)'], tf: ['TensorFlow', 'Keras / SavedModel (.keras, .h5, saved_model.pb)'] };
        const [o, info] = await Promise.all([api('/api/tool/files?model=' + encodeURIComponent(repo)), api('/api/tool/info?model=' + encodeURIComponent(repo))]);
        const entries = Object.entries(o.frameworks || {});
        const draw = (have) => fill(slot, h('div', { class: 'muted small', style: { marginBottom: '6px' } }, t('Escolha o framework do modelo: só o arquivo dele é baixado (nada do resto do repositório).')),
          !entries.length ? h('div', { class: 'errbox', dataset: { none: '1' } }, t('Este repositório não tem um modelo que o OpenFlow rode (.keras, .h5 completo, SavedModel, .pt, .pth ou .pt2).')) : null,
          entries.map(([fw, d]) => { const row = h('div', { class: 'hub-q', dataset: { quant: fw } });
            fill(row, h('div', { class: 'grow' }, h('b', null, FW[fw][0]), h('div', { class: 'dim small' }, t(FW[fw][1]))), h('span', { class: 'chip solid' }, bytes(d.size)),
              h('button', { class: 'btn sm', type: 'button', dataset: { act: 'download' }, onclick: async () => {
                let jid; try { jid = (await api('/api/tool/download', { method: 'POST', body: { model: repo, framework: fw } })).job_id; } catch (e) { return toast(e.status === 409 ? t('Já há um download em andamento.') : e.message, 'err'); }
                progressRow(row, repo.split('/')[1] + ' · ' + FW[fw][0], jid, (ok) => { if (ok) api('/api/tool/info?model=' + encodeURIComponent(repo)).then((i) => draw(i.found)).catch(() => draw(true)); else draw(have); });
              } }, icon('download', 13), t('Baixar')));
            return row; }),
          have ? h('div', { class: 'row', style: { gap: '8px', marginTop: '8px' } }, h('span', { class: 'chip on' }, t('baixado')), h('button', { class: 'btn sm primary', type: 'button', dataset: { act: 'use' }, onclick: () => useModel('tool', repo) }, icon('check', 13), t('Usar no nó «Modelo PyTorch/TensorFlow»'))) : null);
        draw(info.found);
      } else {
        const [o, q] = await Promise.all([api('/api/media/local/options?model=' + encodeURIComponent(repo)), api('/api/media/local/quants?model=' + encodeURIComponent(repo)).catch(() => ({ variants: [] }))]);
        let state = {}; try { state = await api('/api/media/local/state'); } catch (e) { /* sem estado */ }
        const meta = (st.results || []).find((x) => x.id === repo), blocked = !!(meta && meta.compat && meta.compat.level === 'no');   // v0.65: um modelo que o OpenFlow não roda não vira «Usar»
        const prec = (state.models && state.models[st.cap] && state.models[st.cap].model === repo && state.models[st.cap].precision) || '';
        const draw = (cur) => fill(slot, blocked ? h('div', { class: 'errbox', dataset: { blocked: '1' }, style: { marginBottom: '8px' } }, meta.compat.reason) : null, !state.libs ? h('div', { class: 'errbox', style: { marginBottom: '8px' } }, t('Instale as bibliotecas dos modelos locais para baixar:') + ' pip install "openflow[media]"  (' + t('ou rode') + ' flow libs)') : null,
          h('div', { class: 'muted small', style: { marginBottom: '6px' } }, t('Precisão do download: menos bits = menor; o fp16 pede placa de vídeo.')),
          o.options.map((p) => { const row = h('div', { class: 'hub-q', dataset: { quant: p.id } });
            fill(row, h('div', { class: 'grow' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, p.id), p.recommended ? h('span', { class: 'chip on' }, t('Recomendada')) : null, cur === p.id ? h('span', { class: 'chip on' }, t('baixado')) : null), h('div', { class: 'dim small' }, t(PREC_HINT[p.id] || '')), p.memory ? h('div', { class: 'dim small' }, t('Memória ≈ {n}', { n: bytes(p.memory) })) : null),
              h('span', { class: 'chip solid' }, bytes(p.size)),
              cur === p.id ? h('button', { class: 'btn sm primary', type: 'button', dataset: { act: 'use' }, disabled: blocked, title: blocked ? t('O OpenFlow ainda não roda este modelo') : '', onclick: () => useModel('local_hf', repo) }, icon('check', 13), t('Usar'))
                : h('button', { class: 'btn sm', type: 'button', dataset: { act: 'download' }, disabled: !state.libs, onclick: async () => {
                  let jid; try { jid = (await api('/api/media/local/download', { method: 'POST', body: { model: repo, precision: p.id } })).job_id; } catch (e) { return toast(e.status === 409 ? t('Já há um download em andamento.') : e.message, 'err'); }
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

  // Recomendados: o catálogo da Unsloth/ChatR Labs (GGUF) — só uma lista para abrir; quem escolhe, pesquisa e baixa o modelo é você, pela barra do Canvas (v0.48: sem modelos «prontos para instalar»)
  async function loadRecs() {
    if (!st.cat) { try { st.cat = (await api('/api/unsloth/catalog')).models; } catch (e) { st.cat = []; } }
  }
  function recs() {
    const box = h('div', { class: 'hub-recs', id: 'hub-recs' });
    if (!st.cat) { loadRecs().then(() => { if (st.results === null && !panel.classList.contains('hidden')) paint(); }); return h('div', { class: 'muted small', style: { padding: '12px' } }, h('span', { class: 'spinner' }), ' ', t('Carregando os recomendados…')); }
    const cat = st.fmt === 'gguf' ? st.cat.filter((m) => m.kind === st.cap) : [];
    const chip = { ready: [t('Funciona'), 'chip on'], alt: [t('Use outro repositório'), 'chip'], beta: [t('Experimental'), 'chip on'], soon: [t('Ainda não'), 'chip'] };
    if (cat.length) box.append(h('div', { class: 'hub-head muted small' }, t('Catálogo recomendado (GGUF)')), ...cat.map((m) => {
      const go = (repo) => { input.value = repo; st.q = repo; search(); };
      return h('div', { class: 'hub-rec', dataset: { repo: m.repo } }, h('div', { class: 'row nw', style: { gap: '8px' } }, h('div', { class: 'grow', style: { minWidth: 0 } },
        h('div', { class: 'row', style: { gap: '8px', flexWrap: 'wrap' } }, h('b', null, m.label), h('span', { class: chip[m.status][1] }, chip[m.status][0]), h('span', { class: 'chip' }, m.size)),
        h('div', { class: 'dim small' }, m.status === 'soon' ? t(m.why) : t(m.hint)), h('div', { class: 'mono dim', style: { fontSize: '11px' } }, m.repo)),
        m.status === 'ready' || m.status === 'beta' ? h('button', { class: 'btn sm', type: 'button', dataset: { act: 'rec-open' }, onclick: () => go(m.repo) }, t('Ver quantizações'))
          : m.status === 'alt' ? h('button', { class: 'btn sm primary', type: 'button', onclick: () => go(m.use) }, t('Abrir {r}', { r: m.use })) : null));
    }));
    box.append(h('div', { class: 'hub-head muted small' }, st.cap === 'tool' ? t('Modelos próprios de imagem → imagem (ampliar, tirar ruído, colorir…) para o nó «Modelo PyTorch/TensorFlow». Escreva o que procura (esrgan, denoise, colorize…) ou o endereço dono/nome e aperte Enter.') : st.cap === 'text' ? t('O texto usa só GGUF (llama.cpp). Escreva o nome ou o endereço dono/nome do modelo e aperte Enter.')
      : BOTH_CAPS.includes(st.cap) ? t('Escreva o nome ou o endereço dono/nome do modelo e aperte Enter. Em «Formato» escolha GGUF (quantizações) ou Original (diffusers).') : t('Escreva o nome ou o endereço dono/nome do modelo e aperte Enter (som, voz, transcrição e 3D usam o formato original).')));
    return box;
  }

  const topicName = (id) => { for (const l of Object.values(st.topics || {})) { const x = l.find((y) => y.id === id); if (x) return x.label; } return id; };
  // v0.65: o selo «Roda no OpenFlow» / «Ainda não roda», os assuntos do modelo e a biblioteca dele
  const badges = (r) => (r.compat ? h('div', { class: 'hub-badges' }, h('span', { class: 'chip ' + (r.compat.level === 'ok' ? 'on' : 'warn'), dataset: { compat: r.compat.level }, title: r.compat.reason }, r.compat.level === 'ok' ? t('Roda no OpenFlow') : t('Ainda não roda no OpenFlow')),
    ...(r.topics || []).slice(0, 3).map((x) => h('span', { class: 'chip', dataset: { topic: x } }, t(topicName(x)))), r.library ? h('span', { class: 'chip', title: t('Biblioteca') }, r.library) : null) : null);

  function paint() {
    fit();
    if (st.results === null && !st.busy && !st.err && SOUND_CAPS.includes(st.cap) && st.fmt === 'original' && st.topics) {   // som, voz e transcrição: ao abrir já aparecem os mais baixados do assunto (sem digitar nada)
      const key = st.cap + '|' + st.topic + '|' + st.q;
      if (st.browsed !== key) { st.browsed = key; setTimeout(search, 0); fill(panel, filters, h('div', { class: 'muted small', style: { padding: '12px' } }, h('span', { class: 'spinner' }), ' ', t('Procurando…'))); return; }
    }
    if (st.results === null && !st.busy && !st.err) { fill(panel, filters, recs()); return; }
    const hint = SOUND_CAPS.includes(st.cap) ? t('Mais baixados do assunto; os que o OpenFlow roda vêm primeiro. Escreva o nome de uma família (musicgen, whisper…), de um autor ou um idioma («voz em português») e aperte Enter.')
      : st.fmt === 'gguf' ? t('GGUF: cada arquivo é uma quantização do mesmo modelo; você escolhe qual baixar.') : t('Formato original (diffusers/transformers): você escolhe a precisão antes do download.');
    fill(panel, filters, h('div', { class: 'hub-head muted small' }, hint),
      st.busy ? h('div', { class: 'muted small', style: { padding: '12px' } }, h('span', { class: 'spinner' }), ' ', t('Procurando…')) : st.err ? h('div', { class: 'errbox', style: { margin: '8px' } }, st.err)
        : (st.results || []).length ? (st.results || []).map((r) => {
          const slot = h('div', { class: 'hub-detail' + (st.open === r.id ? '' : ' hidden') });
          const row = h('div', { class: 'hub-r' + (st.open === r.id ? ' on' : ''), dataset: { repo: r.id }, onclick: () => { st.open = st.open === r.id ? null : r.id; paint(); } },
            icon('chev', 12), h('span', { class: 'nm mono' }, r.id), h('span', { class: 'muted small' }, '↓ ' + compact(r.downloads) + (r.likes ? ' · ♥ ' + compact(r.likes) : '')), badges(r),
            (r.frameworks || []).length ? h('span', { class: 'hub-badges' }, r.frameworks.map((f) => h('span', { class: 'chip', dataset: { framework: f }, title: t('Framework do modelo') }, { pytorch: 'PyTorch', tensorflow: 'TensorFlow', jax: 'JAX', onnx: 'ONNX', gguf: 'GGUF' }[f] || f))) : null);
          if (st.open === r.id) setTimeout(() => detail(r.id, slot), 0);
          return h('div', { class: 'hub-item' }, row, slot);
        }) : h('div', { class: 'muted small', style: { padding: '12px' } }, st.results ? t('Nada encontrado. Tente outro nome.') : ''));
  }
  const dispose = () => { window.removeEventListener('resize', fit); window.removeEventListener('flow:hub', onHubEvent); document.removeEventListener('pointerdown', onHubDown); };   // o Canvas chama ao fechar
  return { el: root, dispose, search: (q) => { input.value = q; st.q = q; search(); } };
}
