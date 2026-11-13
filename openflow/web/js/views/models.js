import { api, events } from '../api.js';
import { t } from '../i18n.js';
import { refreshState, renderSide, saveSettings, state } from '../main.js';
import { ROLE_LABEL } from '../labels.js';
import { GGUF_HINT, GGUF_KINDS, QUALITY_LABEL } from '../model_labels.js';
import { checkbox, confirmDialog, fmtBytes, h, icon, toast } from '../ui.js';

// Tela «Modelos»: o que está instalado (com o estado dos arquivos de apoio: VAE, codificador de texto e mmproj), os recomendados e a busca no Hugging Face.
// Ao baixar um modelo, o OpenFlow baixa junto o que ele precisa para rodar (a menos que isso seja desligado aqui).

export default async function render(root) {
  let kind = 'image';
  const ram = state.hardware.ram_gb || 8;
  const auto = { on: state.settings.hf.auto_support !== false };
  const installed = h('div', { class: 'col', 'aria-live': 'polite' }), preBox = h('div', { class: 'col', style: { gap: '10px' } });
  const results = h('div', { class: 'col' }), files = h('div', { class: 'col', style: { marginTop: '14px' } }), prog = h('div', { 'aria-live': 'polite' });
  const kindHint = h('p', { class: 'muted small', style: { margin: '10px 0 0' } });
  const q = h('input', { type: 'search', id: 'md-q', 'aria-label': t('Buscar modelos'), onkeydown: (e) => { if (e.key === 'Enter') search(); } });

  // ---------------------------------------------------------------------------------------------- progresso de um job (download)
  function track(jid, title, area, done) {
    const bar = h('i'), label = h('span', { class: 'small muted' }, '0%'), note = h('div', { class: 'small muted', style: { marginTop: '6px' } });
    area.replaceChildren(h('div', { class: 'card', style: { marginTop: '8px' } }, h('div', { class: 'row', style: { marginBottom: '8px' } }, h('span', { class: 'mono small grow' }, title), label,
      h('button', { class: 'btn sm', type: 'button', onclick: () => api('/api/jobs/' + jid + '/cancel', { method: 'POST' }).catch(() => {}) }, t('Cancelar'))),
    h('div', { class: 'bar', role: 'progressbar', 'aria-label': title }, bar), note));
    events('/api/jobs/' + jid + '/events', (ev) => {
      if (ev.type === 'progress' && ev.total) { const pc = Math.min(1, ev.done / ev.total); bar.style.width = Math.round(pc * 100) + '%'; label.textContent = Math.round(pc * 100) + '% · ' + fmtBytes(ev.done) + ' / ' + fmtBytes(ev.total); }
      else if (ev.type === 'note') note.textContent = ev.message;
      else if (ev.type === 'support') note.textContent = t('Vem junto: {l}', { l: ev.items.map((i) => t(ROLE_LABEL[i.role] || i.role)).join(', ') });
      else if (ev.type === 'done') { area.replaceChildren(); const bad = (ev.support_failed || ev.failed || []); toast(bad.length ? t('Pronto, mas {n} arquivo(s) de apoio não baixaram. Use «Instalar o que falta».', { n: bad.length }) : t('Download concluído'), bad.length ? '' : 'ok'); done(true); }
      else if (ev.type === 'error') { area.replaceChildren(); toast(ev.message, 'err'); done(false); }
      else if (ev.type === 'cancelled') { area.replaceChildren(); toast(t('Download cancelado')); done(false); }
    });
  }

  // ---------------------------------------------------------------------------------------------- instalados
  const supportChip = (s) => {
    const parts = [];
    (s.have || []).forEach((x) => parts.push(h('span', { class: 'chip on', title: x.name }, '✓ ' + t(ROLE_LABEL[x.role] || x.role))));
    (s.missing || []).forEach((x) => parts.push(h('span', { class: 'chip warn', title: x.label }, '⚠ ' + t('falta {x}', { x: t(ROLE_LABEL[x.role] || x.role) }))));
    return parts;
  };
  async function paintInstalled() {
    const [{ models }, sup] = await Promise.all([api('/api/hf/local?kind=' + kind), api('/api/models/support').catch(() => ({ models: [] }))]);
    const supOf = (name) => sup.models.find((s) => s.kind === kind && s.name === name);
    const gaps = models.filter((m) => { const s = supOf(m.name); return s && s.missing.length; });
    installed.replaceChildren(...(models.length ? models.map((m) => {
      const s = supOf(m.name) || { have: [], missing: [] };
      const area = h('div');
      return h('div', { class: 'mdrow' }, h('div', { class: 'row nw', style: { padding: '10px 0' } },
        h('div', { class: 'grow', style: { minWidth: 0 } }, h('div', { class: 'mono', style: { fontSize: '13px', overflowWrap: 'anywhere' } }, m.name),
          h('div', { class: 'dim small' }, fmtBytes(m.size) + (m.parts > 1 ? ' · ' + t('{n} partes', { n: m.parts }) : '')),
          (s.have.length || s.missing.length) ? h('div', { class: 'row', style: { gap: '6px', marginTop: '6px', flexWrap: 'wrap' } }, supportChip(s)) : null),
        m.quant ? h('span', { class: 'chip solid', title: t(QUALITY_LABEL[m.quality] || '') }, m.quant) : null,
        useButtons(m),
        h('button', { class: 'btn sm ghost danger', type: 'button', title: t('Apagar {n}', { n: m.name }), 'aria-label': t('Apagar {n}', { n: m.name }), onclick: async () => {
          if (await confirmDialog(t('Apagar o arquivo {n}?', { n: m.name }) + (s.have.some((x) => x.role === 'mmproj') ? ' ' + t('O mmproj dele também será apagado.') : ''))) { await api('/api/hf/local/' + encodeURIComponent(m.name) + '?kind=' + kind, { method: 'DELETE' }); paintInstalled(); }
        } }, icon('trash', 13))), area);
    }) : [h('div', { class: 'muted small' }, t('Nenhum modelo baixado nesta categoria ainda.'))]));
    if (gaps.length) {
      const area = h('div');
      installed.append(h('div', { class: 'card', style: { marginTop: '10px' } }, h('div', { class: 'row nw' }, h('div', { class: 'grow small' }, t('Faltam arquivos de apoio em {n} modelo(s). O OpenFlow baixa só o que falta.', { n: gaps.length })),
        h('button', { class: 'btn primary sm', type: 'button', id: 'md-support', onclick: async () => {
          let jid; try { jid = (await api('/api/models/support/install', { method: 'POST', body: { kind } })).job_id; } catch (e) { return toast(e.message, 'err'); }
          track(jid, t('Arquivos de apoio'), area, () => paintInstalled());
        } }, icon('download', 13), t('Instalar o que falta'))), area));
    }
  }
  function useButtons(m) {
    if (kind === 'text') return h('button', { class: 'btn sm', type: 'button', onclick: async () => { await saveSettings({ providers: { local_hf: { model: m.name } }, active: { generation: 'local_hf' } }); toast(t('Usando como modelo de texto'), 'ok'); } }, t('Usar'));
    if (kind === 'image' || kind === 'video') return h('button', { class: 'btn sm', type: 'button', onclick: async () => { await saveSettings({ media: { models: { gguf_local: { [kind]: m.name } }, active: { [kind]: 'gguf_local' } } }); toast(kind === 'image' ? t('Usando para imagens') : t('Usando para vídeos'), 'ok'); } }, t('Usar'));
    return null;
  }

  // ---------------------------------------------------------------------------------------------- recomendados (pré-instalados)
  async function paintPre() {
    let list = [];
    try { list = (await api('/api/preinstalled')).models; } catch (e) { return; }
    preBox.replaceChildren(...list.map((m) => {
      const area = h('div');
      const act = m.installed ? h('span', { class: 'chip on' }, '✓ ' + t('Instalado')) : h('button', { class: 'btn sm primary', type: 'button', onclick: async () => {
        let jid; try { jid = (await api('/api/preinstalled/install', { method: 'POST', body: { id: m.id } })).job_id; } catch (e) { return toast(e.message, 'err'); }
        track(jid, t('Baixando {n}…', { n: m.label }), area, (ok) => { if (ok) refreshState().then(() => { renderSide(); paintPre(); paintInstalled(); }); });
      } }, icon('download', 13), t('Instalar'));
      return h('div', { class: 'prerow' }, h('div', { class: 'row nw' }, h('div', { class: 'grow', style: { minWidth: 0 } },
        h('div', { class: 'row', style: { gap: '8px', flexWrap: 'wrap' } }, h('b', null, m.label), h('span', { class: 'chip' }, t((GGUF_KINDS.find(([k]) => k === m.kind) || [0, m.kind])[1])), h('span', { class: 'chip solid' }, m.quant), h('span', { class: 'dim small' }, fmtBytes(m.size))),
        h('div', { class: 'dim small' }, t(m.hint)),
        (m.support || []).length ? h('div', { class: 'row', style: { gap: '6px', flexWrap: 'wrap', marginTop: '4px' } }, h('span', { class: 'dim small' }, t('Vem junto:')), (m.support || []).map((x) => h('span', { class: 'chip', title: x.name }, t(ROLE_LABEL[x.role] || x.role) + ' · ' + fmtBytes(x.size)))) : null,
        h('div', { class: 'mono dim', style: { fontSize: '11px' } }, m.source + ' · ' + m.repo + ' · ' + m.license)), act), area);
    }));
  }

  // ---------------------------------------------------------------------------------------------- busca no Hugging Face
  async function search() {
    results.replaceChildren(h('div', { class: 'spinner' }));
    try {
      const r = await api('/api/hf/search?q=' + encodeURIComponent(q.value || 'gguf') + '&kind=' + kind);
      results.replaceChildren(...(r.results.length ? r.results.map((m) => h('button', { type: 'button', class: 'li', onclick: () => openRepo(m.id) }, h('div', { class: 'grow', style: { minWidth: 0, textAlign: 'left' } }, h('div', { class: 't' }, m.id), h('div', { class: 's' }, '⬇ ' + (m.downloads || 0).toLocaleString() + ' · ♥ ' + (m.likes || 0))), icon('chev', 15)))
        : [h('div', { class: 'muted small' }, t('Nada encontrado. Tente outro nome.'))]));
    } catch (e) { results.replaceChildren(h('div', { class: 'res err', role: 'alert' }, e.message)); }
  }
  async function openRepo(repo) {
    files.replaceChildren(h('div', { class: 'spinner' }));
    try {
      const [r, loc] = await Promise.all([api('/api/hf/files?repo=' + encodeURIComponent(repo) + '&kind=' + kind), api('/api/hf/local?kind=' + kind)]);
      const have = new Set(loc.models.map((m) => m.name));
      if (!r.files.length) return files.replaceChildren(h('div', { class: 'res err' }, t('Nenhum arquivo GGUF utilizável neste repositório.')));
      let pick = null;   // nada vem escolhido: o usuário decide a quantização antes de qualquer download
      const list = h('div', { class: 'col', style: { gap: '6px' }, role: 'radiogroup', 'aria-label': t('Quantização') }), btn = h('button', { class: 'btn primary', type: 'button' });
      const comes = h('div', { class: 'comes small' });
      const paintComes = () => {
        const sup = r.support || [];
        comes.replaceChildren(sup.length
          ? h('div', null, icon('layers', 14), ' ', auto.on ? t('Vem junto, automaticamente:') : t('Arquivos de apoio (desligado: marque a opção abaixo para baixar junto):'), ' ', sup.map((x) => h('span', { class: 'chip ' + (auto.on ? 'on' : ''), title: x.label }, t(ROLE_LABEL[x.role] || x.role) + (x.size ? ' · ' + fmtBytes(x.size) : ''))))
          : h('div', { class: 'dim' }, t('Este modelo não precisa de arquivos de apoio conhecidos (VAE, codificador de texto ou mmproj).')));
      };
      const paint = () => {
        list.replaceChildren(...r.files.map((f) => h('label', { class: 'quant' + (f === pick ? ' on' : ''), onclick: () => { pick = f; paint(); } },
          h('input', { type: 'radio', name: 'quant', checked: f === pick }),
          h('div', { class: 'grow', style: { minWidth: 0 } },
            h('div', { class: 'row', style: { gap: '8px', flexWrap: 'wrap' } }, h('b', null, f.quant || t('sem rótulo')), f.quality ? h('span', { class: 'dim small' }, t(QUALITY_LABEL[f.quality])) : null,
              f.recommended ? h('span', { class: 'chip on' }, t('Recomendada')) : null, have.has(f.name) ? h('span', { class: 'chip' }, t('Já baixado')) : null, f.parts > 1 ? h('span', { class: 'chip' }, t('{n} partes', { n: f.parts })) : null),
            h('div', { class: 'mono dim', style: { fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, f.name)),
          h('span', { class: 'chip ' + (f.fits ? 'solid' : '') }, fmtBytes(f.size) + (f.fits ? ' ✓' : ' ⚠')))));
        btn.disabled = !pick;
        btn.replaceChildren(icon('download', 14), pick ? t('Baixar {q} ({s})', { q: pick.quant || pick.name, s: fmtBytes(pick.size) }) : t('Escolha uma quantização para baixar'));
      };
      btn.onclick = () => pick && dl(repo, pick, r.support || []);
      paint(); paintComes();
      files.replaceChildren(h('div', { class: 'small muted' }, repo + ' — ' + t('Escolha a quantização: menos bits = arquivo menor e mais rápido, mas com menos qualidade. Sua RAM: {n} GB; ✓ = cabe (até ~60% da RAM).', { n: ram })), list, comes,
        checkbox(t('Baixar junto o VAE, os codificadores de texto e o mmproj que o modelo precisa (recomendado)'), auto.on, async (v) => { auto.on = v; paintComes(); await saveSettings({ hf: { auto_support: v } }); }),
        h('div', { style: { marginTop: '10px' } }, btn));
    } catch (e) { files.replaceChildren(h('div', { class: 'res err', role: 'alert' }, e.message)); }
  }
  async function dl(repo, f, support) {
    const fitNote = f.fits ? t('Cabe na sua RAM.') : t('Pode não caber na sua RAM ({n} GB).', { n: ram });
    const extra = auto.on && support.length ? ' ' + t('Também vêm: {l}.', { l: support.map((x) => t(ROLE_LABEL[x.role] || x.role)).join(', ') }) : '';
    if (!(await confirmDialog(t('Baixar {q} de {r}? Tamanho: {s}. {f}', { q: f.quant || f.name, r: repo, s: fmtBytes(f.size), f: fitNote }) + extra, false, t('Baixar')))) return;
    if (f.size / 1024 ** 3 > ram * 0.9 && !(await confirmDialog(t('Este modelo é maior que a sua RAM e provavelmente ficará muito lento. Baixar mesmo assim?'), false, t('Baixar')))) return;
    let jid;
    try { jid = (await api('/api/hf/download', { method: 'POST', body: { repo, files: f.files, sizes: f.sizes, quant: f.quant || 'sem-rotulo', kind, support: auto.on } })).job_id; } catch (e) { return toast(e.message, 'err'); }
    track(jid, f.name, prog, () => paintInstalled());
  }

  // ---------------------------------------------------------------------------------------------- tipos e página
  const kindSeg = h('div', { class: 'seg', role: 'tablist', 'aria-label': t('Tipo de modelo'), style: { marginBottom: '14px', flexWrap: 'wrap' } });
  const paintKind = () => {
    kindSeg.replaceChildren(...GGUF_KINDS.map(([k, l]) => h('button', { type: 'button', role: 'tab', 'aria-selected': kind === k ? 'true' : 'false', class: kind === k ? 'on' : '', onclick: () => { kind = k; results.replaceChildren(); files.replaceChildren(); paintKind(); paintInstalled(); } }, t(l))));
    kindHint.textContent = t(GGUF_HINT[kind]);
    q.placeholder = kind === 'text' ? t('Buscar modelos GGUF (ex.: qwen, llama, gemma, mistral)…') : t('Buscar modelos GGUF de {k} (ex.: flux, wan, outetts, qwen-vl)…', { k: t(GGUF_KINDS.find(([x]) => x === kind)[1]).toLowerCase() });
  };
  paintKind();
  const tokenIn = h('input', { type: 'password', autocomplete: 'off', 'aria-label': t('Token do Hugging Face'), placeholder: state.settings.hf.token_set ? '•••••••• (' + t('salvo') + ')' : 'hf_…' });
  root.replaceChildren(h('div', { class: 'page narrow cfg' }, h('div', { class: 'page-h' }, h('div', null, h('h1', null, t('Modelos')), h('p', null, t('Baixe e gerencie modelos locais. VAEs, codificadores de texto e mmproj são instalados junto do modelo, automaticamente.')))),
    h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', null, t('Recomendados')),
      h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Um modelo de texto e um de imagem, já com a quantização definida. O de imagem vem com o VAE e o codificador de texto de que precisa.')), preBox),
    h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', null, t('Buscar no Hugging Face')), kindSeg, kindHint,
      h('div', { class: 'row nw', style: { marginTop: '10px' } }, h('div', { class: 'search', style: { maxWidth: 'none', flex: 1 } }, icon('search', 17), q), h('button', { class: 'btn', type: 'button', onclick: search }, t('Buscar'))),
      h('div', { style: { marginTop: '12px' } }, results), files),
    prog,
    h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', null, t('Instalados')), installed),
    h('div', { class: 'card' }, h('h3', null, t('Token do Hugging Face (opcional)')), h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Necessário apenas para modelos restritos (gated).')),
      h('div', { class: 'row nw' }, tokenIn, h('button', { class: 'btn', type: 'button', onclick: async () => { if (tokenIn.value) { await saveSettings({ hf: { token: tokenIn.value } }); await refreshState(); toast(t('Salvo'), 'ok'); } } }, t('Salvar'))))));
  await Promise.all([paintInstalled(), paintPre()]);
}
