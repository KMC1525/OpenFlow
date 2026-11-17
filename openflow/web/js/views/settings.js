import { api, events } from '../api.js';
import { getLang, t } from '../i18n.js';
import { go, refreshState, renderSide, saveSettings, state } from '../main.js';
import { accentSwatches, themeCards } from '../appearance.js';
import { ui } from '../prefs.js';
import { PREC_HINT } from '../model_labels.js';
import { checkbox, confirmDialog, field, fmtBytes, h, icon, select, seg, toast } from '../ui.js';
import { SETTINGS_TABS } from '../labels.js';

// Configurações do OpenFlow: IA de texto, provedores de mídia (imagem, vídeo, som e voz), voz, projetos, aparência e desempenho.
// Modelos locais (download, VAE, codificadores de texto e mmproj) ficam na tela «Modelos».
const TABS = SETTINGS_TABS;

export default async function render(root, ctx) {
  let tab = TABS.some(([id]) => id === ctx.tab) ? ctx.tab : 'providers';
  const body = h('div'), tabs = h('div', { class: 'tabs cfgtabs', role: 'tablist', 'aria-label': t('Configurações') });
  const FNS = { providers, media, project: projectTab, appearance, performance };
  const paintTabs = () => tabs.replaceChildren(...TABS.map(([id, l]) => h('button', { class: tab === id ? 'on' : '', role: 'tab', 'aria-selected': tab === id ? 'true' : 'false', dataset: { tab: id }, onclick: () => { tab = id; paintTabs(); paintBody(); } }, t(l))));
  const paintBody = async () => { body.replaceChildren(h('div', { class: 'spinner' })); body.replaceChildren(await (FNS[tab] || providers)()); };
  root.replaceChildren(h('div', { class: 'page narrow cfg' }, h('div', { class: 'page-h' }, h('div', null, h('h1', null, t('Configurações')), h('p', null, t('Modelos de IA, provedores de mídia, aparência e desempenho: configure uma vez e use em todos os projetos.')))), tabs, body));
  paintTabs(); await paintBody();
}

const cfgCard = (title, ...kids) => h('div', { class: 'card', style: { marginBottom: '16px' } }, title ? h('h3', null, title) : null, ...kids);

const saveRow = (fn) => h('div', { class: 'row', style: { justifyContent: 'flex-end' } }, h('button', { class: 'btn primary', type: 'button', id: 'cfg-save', onclick: async () => { try { await fn(); toast(t('Salvo'), 'ok'); } catch (e) { toast(e.message, 'err'); } } }, icon('check', 15), t('Salvar')));

const numInput = (obj, key, min, max, step) => h('input', { type: 'number', min, max, step: step || 1, value: obj[key], oninput: (e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) obj[key] = v; } });

async function providers() {
  const presets = state.presets;
  const localInfo = (await api('/api/hf/local')).models, localModels = localInfo.map((m) => m.name);
  let preText = [];   // modelos de texto pré-instalados: o contexto base deles (32K) vale enquanto o usuário não escolher outro valor
  try { preText = (await api('/api/preinstalled')).models.filter((m) => m.kind === 'text' && m.n_ctx); } catch (e) { /* sem a lista, só não mostramos o valor automático */ }
  const container = h('div');
  const rolesCard = () => {
    const S = state.settings;
    return h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', null, t('Quem escreve os textos')),
      field(t('Modelo de texto (IA)'), select(presets.map((p) => [p.id, t(p.label)]), S.active.generation, async (v) => { await saveSettings({ active: { generation: v } }); await refreshState(); renderSide(); paint(); }),
        t('Usado pelo nó Texto IA e para descrever as pastas de estilo. «Demo» funciona offline, sem IA, para testar.')));
  };
  const paint = () => container.replaceChildren(rolesCard(), h('div', null, presets.map(card)));

  function card(p) {
    const S = state.settings, cfg = (S.providers && S.providers[p.id]) || {};
    const isGen = S.active.generation === p.id;
    const configured = p.id === 'demo' || !!cfg.model;
    const draft = { model: cfg.model || '', n_ctx: cfg.n_ctx > 0 ? cfg.n_ctx : 0 };
    const res = h('div', { class: 'res' });
    const dl = h('datalist', { id: 'models-' + p.id }, (p.kind === 'local_hf' ? localModels : []).map((m) => h('option', { value: m })));
    const cardEl = h('div', { class: 'prov' + (isGen ? ' open' : '') });
    const bodyEl = h('div', { class: 'bd' });

    const test = async () => {
      res.className = 'res'; res.textContent = t('Testando…');
      const r = await api('/api/providers/test', { method: 'POST', body: { id: p.id, config: draft } });
      res.className = 'res ' + (r.ok ? 'ok' : 'err');
      res.textContent = r.ok ? '✓ ' + t('Funcionou') + ' (' + (r.ms / 1000).toFixed(1) + ' s) · ' + t('resposta:') + ' ' + r.reply : '✗ ' + r.error;
    };
    const save = async () => {
      const patch = { model: draft.model, n_ctx: draft.n_ctx > 0 ? draft.n_ctx : 0 };   // n_ctx 0 = automático
      await saveSettings({ providers: { [p.id]: patch } }); toast(t('Salvo'), 'ok'); await refreshState(); renderSide(); paint();
    };
    const inputs = [];
    if (p.id === 'demo') inputs.push(h('p', { class: 'muted small', style: { margin: '10px 0 0' } }, t(p.hint)));
    else {
      const modelIn = h('input', { list: 'models-' + p.id, value: draft.model, placeholder: t('arquivo .gguf baixado'), oninput: (e) => { draft.model = e.target.value.trim(); } });
      inputs.push(field(t('Modelo'), h('div', { class: 'row nw' }, modelIn, dl)));
      {
        // janela de contexto: vazio = automático (32K nos modelos de texto pré-instalados; nos demais, conforme o hardware)
        const ctxHint = h('p', { class: 'muted small', style: { margin: '4px 0 0' } });
        const showCtx = () => {
          const pre = preText.find((m) => (m.parts || [m.file]).includes(draft.model) || m.file.split('/').pop() === draft.model);
          const loc = localInfo.find((m) => m.name === draft.model);
          let txt = draft.n_ctx > 0 ? t('Usando {n} tokens de contexto.', { n: draft.n_ctx.toLocaleString() })
            : pre ? t('Automático: {n} tokens (base do modelo pré-instalado).', { n: pre.n_ctx.toLocaleString() }) : t('Automático: conforme o seu hardware (2.048 a 8.192 tokens).');
          if (loc && loc.ctx_train) {   // até onde o modelo foi treinado e quanto o cache de atenção custa na memória (lido do arquivo, sem carregar o modelo)
            const gb = (n) => (n / 1073741824).toFixed(n >= 1073741824 * 10 ? 0 : 1) + ' GB', want = draft.n_ctx > 0 ? draft.n_ctx : loc.ctx_train;
            txt += ' ' + t('Este modelo foi treinado com até {n} tokens.', { n: loc.ctx_train.toLocaleString() });
            if (loc.kv_bytes_per_token) txt += ' ' + t('O cache de atenção de {c} tokens ocupa ≈ {a} (≈ {b} com cache de 4 bits).', { c: want.toLocaleString(), a: gb(loc.kv_bytes_per_token * want), b: gb(loc.kv_bytes_per_token * want * 0.28) });
            if (draft.n_ctx > loc.ctx_train) txt += ' ⚠ ' + t('O valor escolhido passa do que o modelo suporta: a qualidade pode cair.');
          }
          ctxHint.textContent = txt;
        };
        const ctxDl = h('datalist', { id: 'ctx-' + p.id }, [4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576].map((n) => h('option', { value: String(n), label: n >= 1048576 ? '1M' : Math.round(n / 1024) + 'K' })));
        const ctxIn = h('input', { type: 'number', list: 'ctx-' + p.id, min: 512, step: 1024, value: draft.n_ctx || '', placeholder: t('automática'), oninput: (e) => { draft.n_ctx = Math.max(0, parseInt(e.target.value || '0', 10) || 0); showCtx(); } });
        inputs.push(field(t('Janela de contexto (tokens)'), h('div', { class: 'row nw' }, ctxIn, ctxDl,
          h('button', { class: 'btn sm', onclick: () => { draft.n_ctx = 0; ctxIn.value = ''; showCtx(); } }, t('Usar o automático'))),
          t('Quanto texto o modelo lê de uma vez. Janelas maiores usam mais memória (RAM/VRAM): 256K (262144), 512K (524288) e 1M (1048576) só valem em modelos treinados para isso — o OpenFlow lê o limite do modelo no arquivo e avisa se você passar dele, e comprime o cache de atenção sozinho para caber. Os modelos de texto pré-instalados começam com 32.768 (32K).')));
        showCtx(); inputs.push(ctxHint);
      }
      if (p.hint) inputs.push(h('p', { class: 'muted small' }, t(p.hint)));
    }
    inputs.push(h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'btn sm', onclick: test }, t('Testar')), h('button', { class: 'btn sm primary', onclick: save }, t('Salvar')), p.id !== 'demo' ? h('span', { class: 'dim small' }, t('Ao testar, usamos os valores acima mesmo sem salvar.')) : null), res);
    bodyEl.replaceChildren(...inputs);
    cardEl.append(h('div', { class: 'hd', onclick: () => cardEl.classList.toggle('open') }, h('span', { class: 'dot ' + (configured ? 'ok' : ''), style: { width: '8px', height: '8px', borderRadius: '50%', background: configured ? 'var(--ok)' : 'var(--dim)' } }),
      h('span', { class: 'nm' }, t(p.label)),
      h('span', { class: 'roles' }, isGen ? h('span', { class: 'chip on' }, t('em uso')) : null)), bodyEl);
    return cardEl;
  }
  paint();
  return container;
}

// Tamanho da interface (v0.50): de 50% a 200%, de 5 em 5. O controle só aplica ao soltar (a interface inteira muda de tamanho, e o próprio controle junto).
function scaleField(current, onSave) {
  const out = h('output', { id: 'ui-scale-out' }, current + '%');
  const inp = h('input', { type: 'range', id: 'ui-scale', min: 50, max: 200, step: 5, value: current, 'aria-label': t('Tamanho da interface'),
    oninput: () => { out.textContent = inp.value + '%'; }, onchange: () => onSave(Number(inp.value)) });
  const presets = h('div', { class: 'row', style: { gap: '6px', flexWrap: 'wrap', marginTop: '8px' } },
    [50, 75, 90, 100, 110, 125, 150, 175, 200].map((v) => h('button', { type: 'button', class: 'btn sm' + (v === current ? ' on' : ''), dataset: { scale: v }, onclick: () => { inp.value = v; out.textContent = v + '%'; onSave(v); } }, v + '%')));
  return field(t('Tamanho da interface'), h('div', null, h('div', { class: 'scalebox' }, inp, out), presets), t('De 50% a 200%. Aumenta ou diminui tudo; útil em telas grandes ou pequenas.'));
}

// Fontes (v0.50): usam as fontes do próprio computador (nada é baixado). «Outra fonte» aceita o nome de qualquer fonte instalada.
const FONT_OPTIONS = [['system', 'Sistema', 'padrão do seu computador'], ['inter', 'Inter', 'limpa e moderna'], ['humanist', 'Humanista', 'Segoe UI, Calibri…'], ['rounded', 'Arredondada', 'cantos suaves'],
  ['verdana', 'Verdana', 'larga, ótima para ler na tela'], ['readable', 'Alta legibilidade', 'Atkinson, Lexend, OpenDyslexic…'], ['book', 'Livro', 'serifada de leitura'], ['serif', 'Serifada', 'Georgia'], ['mono', 'Monoespaçada', 'estilo terminal']];
const FONT_CSS = { system: 'var(--font)', inter: 'Inter,"Helvetica Neue",Arial,sans-serif', humanist: '"Segoe UI","Gill Sans",Candara,Optima,Calibri,sans-serif', rounded: 'ui-rounded,"SF Pro Rounded",Nunito,"Varela Round","Arial Rounded MT Bold",sans-serif',
  verdana: 'Verdana,Tahoma,Geneva,sans-serif', readable: '"Atkinson Hyperlegible",Lexend,OpenDyslexic,"Comic Sans MS",Verdana,sans-serif', book: 'Charter,"Sitka Text",Cambria,Georgia,serif', serif: 'Georgia,"Palatino Linotype",serif', mono: 'ui-monospace,Menlo,Consolas,monospace' };
function fontField(u, onSave) {
  const grid = h('div', { class: 'fontgrid', id: 'ui-fonts', role: 'radiogroup', 'aria-label': t('Fonte') });
  const custom = h('input', { type: 'text', id: 'ui-font-custom', maxlength: 60, value: u.font_custom || '', placeholder: t('Nome de uma fonte instalada, ex.: Fira Sans'), 'aria-label': t('Outra fonte') });
  const btns = FONT_OPTIONS.map(([id, label, sub]) => h('button', { type: 'button', class: 'fontopt', role: 'radio', dataset: { font: id }, style: { fontFamily: FONT_CSS[id] },
    onclick: () => { paint(id); onSave({ font: id }); } }, h('b', null, t(label)), h('small', null, t(sub))));
  grid.append(...btns);
  const paint = (cur) => btns.forEach((b) => { const on = b.dataset.font === cur; b.classList.toggle('on', on); b.setAttribute('aria-checked', on ? 'true' : 'false'); });   // só troca a marca: recriar os botões no meio de um clique o perderia
  paint(u.font === 'custom' ? '' : u.font);
  const apply = () => { const name = custom.value.trim(); if (name) { paint(''); onSave({ font: 'custom', font_custom: name }); } else if (u.font === 'custom') { paint('system'); onSave({ font: 'system', font_custom: '' }); } };
  custom.addEventListener('change', apply);
  return field(t('Fonte'), h('div', null, grid, h('div', { class: 'row nw', style: { marginTop: '10px' } }, h('label', { class: 'f', for: 'ui-font-custom', style: { margin: 0, whiteSpace: 'nowrap' } }, t('Outra fonte')), custom)),
    t('Usa as fontes do seu computador. Se a fonte digitada não estiver instalada, a interface usa a fonte do sistema.'));
}

async function appearance() {
  const save = async (patch, quiet) => { await saveSettings({ ui: patch }); if (!quiet) toast(t('Salvo'), 'ok'); };
  const U = () => ui();
  const card = cfgCard;
  return h('div', null,
    card(t('Tema'), themeCards(U().theme, (v) => save({ theme: v })),
      h('div', { class: 'field', style: { marginTop: '16px', marginBottom: 0 } }, h('label', { class: 'f' }, t('Cor de destaque')), accentSwatches(U().accent, (v) => save({ accent: v }, true)),
        h('div', { class: 'hint' }, t('Usada em botões, seleções e destaques.')))),
    card(t('Leitura e conforto'),
      scaleField(U().scale, (v) => save({ scale: v })),
      field(t('Densidade'), seg([['comfortable', t('Confortável')], ['compact', t('Compacta')]], U().density, (v) => save({ density: v })), t('Compacta mostra mais conteúdo na tela.')),
      fontField(U(), (patch) => save(patch)),
      field(t('Animações'), select([['auto', t('Automático (segue o sistema)')], ['reduce', t('Reduzir animações')], ['full', t('Sempre animar')]], U().motion, (v) => save({ motion: v })), t('“Reduzir” desliga transições e animações — bom para quem sente enjoo com movimento ou usa um computador mais fraco.'))),
    card(t('Idioma'),
      field(t('Idioma da interface'), select([['auto', t('Automático (navegador)')], ['pt-BR', 'Português (Brasil)'], ['en', 'English']], state.settings.language, async (v) => { await saveSettings({ language: v }); location.reload(); }),
        t('Os textos do terminal (flow, flow update, instaladores) seguem o idioma do computador; para forçar um, use OPENFLOW_LANG=pt ou OPENFLOW_LANG=en.'))),
    card(t('Padrões da aparência'),
      h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Volta o tema, as cores e o conforto de leitura ao original. Seus modelos e projetos não mudam.')),
      h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => window.OPENFLOW_WELCOME && window.OPENFLOW_WELCOME() }, t('Rever as boas-vindas')), h('span', { class: 'grow' }),
        h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmDialog(t('Voltar a aparência e as preferências de uso ao padrão? Seus modelos e projetos não mudam.'), true, t('Restaurar'))) { await api('/api/settings/reset', { method: 'POST', body: { section: 'ui' } }); await refreshState(); location.reload(); } } }, t('Restaurar padrões da aparência')))));
}

async function projectTab() {
  let tpls = [];
  try { tpls = (await api('/api/project-templates')).templates || []; } catch (e) { /* sem a lista, só o padrão */ }
  const cv = JSON.parse(JSON.stringify(state.settings.canvas || { template: 'text_image' }));
  const opts = (tpls.length ? tpls : [{ id: 'text_image', label: 'Texto → Imagem' }]).map((x) => [x.id, t(x.label)]);
  return h('div', null,
    cfgCard(t('Novos projetos'), field(t('Modelo inicial'), select(opts, cv.template, (v) => { cv.template = v; }), t('O modelo que vem marcado ao criar um projeto novo. Os provedores de imagem, vídeo, som e voz ficam em Mídia.'))),
    saveRow(() => saveSettings({ canvas: cv })));
}

// PyTorch e TensorFlow (v0.82): o que está instalado, se usa a placa de vídeo e o comando certo para quem não usa (o texto do conselho vem do servidor, em português e em inglês)
function frameworksCard() {
  const body = h('div', { id: 'fw-body', 'aria-live': 'polite' }, h('span', { class: 'muted small' }, t('Lendo o PyTorch e o TensorFlow…')));
  const advice = (a) => h('div', { class: 'fw-advice', dataset: { level: a.level }, style: { marginTop: '6px' } },
    h('span', { class: 'chip ' + (a.level === 'ok' ? 'on' : a.level === 'warn' || a.level === 'error' ? 'warn' : ''), style: { marginRight: '6px' } }, { ok: '✓', info: 'i', warn: '!', error: '×' }[a.level] || 'i'),
    h('span', { class: 'small' }, getLang() === 'en' && a.text_en ? a.text_en : a.text),
    a.command ? h('div', { class: 'codebox' }, h('span', { class: 'fw-cmd' }, a.command), h('button', { class: 'btn sm ghost', type: 'button', onclick: () => navigator.clipboard.writeText(a.command).then(() => toast(t('Copiado'), 'ok')) }, t('Copiar'))) : null);
  const paint = (r) => {
    const tc = r.torch, tf = r.tensorflow;
    body.replaceChildren(
      h('dl', { class: 'kv', style: { margin: 0 } },
        h('dt', null, 'PyTorch'), h('dd', { id: 'fw-torch' }, tc.installed ? tc.version + (tc.build ? ' · ' + tc.build : '') + (tc.device ? ' · ' + tc.device : '') : t('não instalado')),
        h('dt', null, 'TensorFlow'), h('dd', { id: 'fw-tf' }, tf.installed ? tf.version + (tf.keras ? ' · Keras ' + tf.keras : '') + ' · ' + (tf.probed === false ? t('instalado') : (tf.gpus || []).length ? t('usa a placa') : 'CPU') : t('não instalado')),
        h('dt', null, t('Placas de vídeo')), h('dd', null, (r.gpu_vendors || []).join(', ') || t('nenhuma'))),
      ...r.advice.torch.map(advice), ...r.advice.tensorflow.map(advice),
      tf.installed && tf.probed === false ? h('button', { class: 'btn sm', type: 'button', id: 'fw-tf-probe', style: { marginTop: '8px', marginRight: '8px' }, onclick: () => { body.replaceChildren(h('span', { class: 'muted small' }, t('Lendo o PyTorch e o TensorFlow…'))); load(false, true); } }, t('Verificar o TensorFlow')) : null,
      h('button', { class: 'btn sm ghost', type: 'button', id: 'fw-refresh', style: { marginTop: '8px' }, onclick: () => { body.replaceChildren(h('span', { class: 'muted small' }, t('Lendo o PyTorch e o TensorFlow…'))); load(true); } }, t('Ler de novo')));
  };
  const load = (fresh, deep) => api('/api/media/frameworks' + (deep ? '?tf=1' : fresh ? '?refresh=1' : '')).then(paint).catch((e) => body.replaceChildren(h('span', { class: 'muted small' }, e.message)));
  load(false);
  return cfgCard(t('PyTorch e TensorFlow'), h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Os modelos locais usam o PyTorch; o TensorFlow só é preciso para os modelos feitos para ele (Keras, SavedModel), no nó «Modelo PyTorch/TensorFlow». Aqui você vê se cada um usa a placa de vídeo e o que fazer se não usa. No terminal: flow frameworks e flow torch.')), body);
}

// Aceleração por placa de vídeo (v0.29): NVIDIA/AMD/Intel, se o llama.cpp instalado usa a placa e quanto cada modelo de texto deve render nela
function gpuAccelCard(hw) {
  const body = h('div', { id: 'gpu-body', 'aria-live': 'polite' }, h('span', { class: 'muted small' }, t('Procurando placas de vídeo…')));
  const win = /windows/i.test(hw.os || '');
  const cmd = (backend) => { const flag = { cuda: '-DGGML_CUDA=on', vulkan: '-DGGML_VULKAN=on', metal: '-DGGML_METAL=on' }[backend]; const pip = 'pip install --upgrade --force-reinstall --no-cache-dir llama-cpp-python'; return win ? '$env:CMAKE_ARGS="' + flag + '"; ' + pip : 'CMAKE_ARGS="' + flag + '" ' + pip; };
  const paint = (r) => {
    if (!r.gpus.length) return body.replaceChildren(h('p', { class: 'muted small', style: { margin: 0 } }, t('Nenhuma placa de vídeo NVIDIA, AMD ou Intel detectada: os modelos rodam na CPU (veja o card acima). No Windows, só placas NVIDIA são detectadas.')));
    const BK = { cuda: 'CUDA', vulkan: 'Vulkan', metal: 'Metal' };
    body.replaceChildren(
      h('dl', { class: 'kv', style: { margin: 0 } },
        ...r.gpus.flatMap((g) => [h('dt', null, 'GPU ' + g.index), h('dd', { class: 'gpu-row' }, g.name + ' · ' + (g.integrated ? t('integrada (usa a RAM)') : g.vram_total ? fmtBytes(g.vram_total) + ' ' + t('de memória') : '') + ' · ' + BK[g.backend])]),
        h('dt', null, t('llama.cpp (texto)')), h('dd', { id: 'gpu-llama' }, !r.llama.installed ? t('não instalado') : r.llama.offload ? h('span', { class: 'chip on' }, t('usa a placa')) : h('span', { class: 'chip warn' }, t('só CPU: não usa a placa'))),
        h('dt', null, t('Imagem e vídeo (sd-cli)')), h('dd', null, { cuda12: 'CUDA', vulkan: 'Vulkan', cpu: 'CPU' }[r.sd_cli] || r.sd_cli)),
      r.llama.installed && !r.llama.offload && r.backend ? h('div', { class: 'field' }, h('label', { class: 'f' }, t('Para o texto usar a placa, reinstale o llama-cpp-python com suporte a {b} (leva alguns minutos para compilar)', { b: BK[r.backend] })),
        h('div', { class: 'codebox' }, h('span', { id: 'gpu-cmd' }, cmd(r.backend)), h('button', { class: 'btn sm ghost', type: 'button', onclick: () => navigator.clipboard.writeText(cmd(r.backend)).then(() => toast(t('Copiado'), 'ok')) }, t('Copiar')))) : null,
      r.models.length ? h('div', { class: 'col', style: { marginTop: '10px', gap: '6px' }, id: 'gpu-models' }, r.models.map((m) => h('div', { class: 'row nw' }, h('span', { class: 'mono small grow', style: { overflowWrap: 'anywhere' } }, m.name),
        h('span', { class: 'dim small' }, fmtBytes(m.size)),
        h('span', { class: 'small' }, m.all_gpu ? t('tudo na placa') : m.layers_fit ? t('{a} de {b} camadas na placa', { a: m.layers_fit, b: m.layers }) : t('na CPU')),
        m.est_tps ? h('span', { class: 'small' }, '≈ ' + m.est_tps.toFixed(1) + ' tok/s') : null, m.layers_fit && !m.all_gpu && !m.kv_on_gpu ? h('span', { class: 'chip' }, t('cache na RAM')) : null))) : null);
  };
  api('/api/gpu').then(paint).catch((e) => body.replaceChildren(h('span', { class: 'muted small' }, e.message)));
  return cfgCard(t('Placa de vídeo (aceleração)'), h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Em placas pequenas (2–6 GB, notebooks) o OpenFlow deixa o cache de atenção na RAM e enche a memória da placa só com camadas do modelo; GPU integrada não é usada (ela divide a RAM com o processador).')), body);
}

// CPU (v0.28): o processador, a velocidade da memória (o que limita os modelos na CPU) e quanto cada modelo de texto baixado deve render, só na CPU
function cpuCard(pf) {
  const body = h('div', { id: 'cpu-body', 'aria-live': 'polite' }, h('span', { class: 'muted small' }, t('Lendo o processador…')));
  const SIMD = ['SSE', 'AVX', 'AVX2', 'AVX-512', 'NEON'];
  const paint = (r) => {
    const i = r.info, b = r.bench || {}, cores = i.hybrid ? t('{p} núcleos de desempenho + {e} de eficiência', { p: i.p_physical, e: i.e_physical }) : t('{p} núcleos', { p: i.p_physical });
    const verdict = { fast: [t('Fluido'), 'chip on'], ok: [t('Usável'), 'chip'], slow: [t('Lento'), 'chip warn'] };
    body.replaceChildren(
      h('dl', { class: 'kv', style: { margin: 0 } },
        h('dt', null, t('Processador')), h('dd', { id: 'cpu-brand' }, (i.brand || i.vendor.toUpperCase()) + ' · ' + cores + ' · ' + SIMD[i.simd] + (i.l3_kb ? ' · L3 ' + Math.round(i.l3_kb / 1024) + ' MB' : '')),
        h('dt', null, t('Velocidade da memória')), h('dd', { id: 'cpu-bw' }, b.bwn ? b.bwn.toFixed(1) + ' GB/s ' + t('(1 thread: {a} GB/s)', { a: b.bw1.toFixed(1) }) : t('ainda não medida')),
        h('dt', null, t('Modelo que roda bem')), h('dd', null, b.bwn ? t('até ≈ {a} GB com 5 tokens/s · ≈ {b} GB com 10 tokens/s', { a: r.max_gb_5tps, b: r.max_gb_10tps }) : '—'),
        r.memory && r.memory.modules ? h('dt', null, t('Memória RAM')) : null, r.memory && r.memory.modules ? h('dd', { id: 'cpu-ram' }, r.memory.modules + '× ' + (r.memory.type || 'RAM') + (r.memory.speed ? '-' + (r.memory.configured_speed || r.memory.speed) : '') + ' · ' + (r.memory.channels > 1 ? t('{n} canais', { n: r.memory.channels }) : t('canal único')) + (r.memory.estimated_channels ? ' ' + t('(estimado)') : '') + (r.memory.theoretical_gbs ? ' · ' + t('teórico {n} GB/s', { n: r.memory.theoretical_gbs }) : '')) : null,
        r.ram && r.ram.class && r.ram.class !== 'unknown' ? h('dt', null, t('Memória para os modelos')) : null,
        r.ram && r.ram.class && r.ram.class !== 'unknown' ? h('dd', { id: 'cpu-ramplan' }, t('{b} depois do sistema · ≈ {g} GB/s · até {n} threads úteis', { b: fmtBytes(r.ram.budget + 0), g: r.ram.bw_gbs, n: r.ram.useful_threads }) + (r.ram.class === '16' ? ' · ' + t('classe de 16 GB: o OpenFlow descarrega o outro modelo e limita o contexto para caber') : r.ram.class === 'small' ? ' · ' + t('pouca RAM: modo econômico') : '')) : null,
        r.numa_nodes > 1 ? h('dt', null, t('Nós NUMA')) : null, r.numa_nodes > 1 ? h('dd', null, r.numa_nodes + ' · ' + t('threads e memória distribuídas entre os nós')) : null,
        r.info.hybrid ? h('dt', null, t('Núcleos fixados')) : null, r.info.hybrid ? h('dd', null, r.pinned ? t('sim (só os de desempenho)') : t('ainda não (fixa ao carregar um modelo na CPU)')) : null),
      r.models.length ? h('div', { class: 'col', style: { marginTop: '10px', gap: '6px' }, id: 'cpu-models' }, r.models.map((m) => h('div', { class: 'row nw' }, h('span', { class: 'mono small grow', style: { overflowWrap: 'anywhere' } }, m.name),
        h('span', { class: 'dim small' }, fmtBytes(m.size)), m.est_tps ? h('span', { class: 'small' }, '≈ ' + m.est_tps.toFixed(1) + ' tok/s') : null, m.verdict ? h('span', { class: verdict[m.verdict][1] }, verdict[m.verdict][0]) : null))) : null,
      h('div', { class: 'row', style: { marginTop: '10px', flexWrap: 'wrap' } },
        h('button', { class: 'btn sm', type: 'button', id: 'cpu-bench', onclick: async (e) => { e.target.disabled = true; try { paint(await api('/api/cpu/bench', { method: 'POST', body: {} })); toast(t('Memória medida'), 'ok'); } catch (er) { toast(er.message, 'err'); e.target.disabled = false; } } }, t('Medir a memória')),
        i.hybrid ? checkbox(t('Fixar nos núcleos de desempenho (Linux)'), pf.cpu_pin !== false, async (v) => { pf.cpu_pin = v; await saveSettings({ performance: pf }); toast(t('Salvo. Vale a partir do próximo modelo carregado.'), 'ok'); }) : null),
      ...(r.advice || []).map((a) => h('p', { class: 'res warn small', style: { marginBottom: 0 } }, a === 'single_channel' ? t('Só um pente de memória: em canal único a velocidade dos modelos é a metade. Um segundo pente igual (dual channel) dobra a largura de banda.')
        : a === 'xmp_off' ? t('A memória roda mais devagar do que o pente suporta: ative o XMP/EXPO na BIOS para ganhar velocidade nos modelos.') : t('A velocidade medida está bem abaixo da teórica: confira os pentes (iguais, em slots dos canais diferentes) e o XMP/EXPO.'))),
      r.weak ? h('p', { class: 'muted small', style: { marginBottom: 0 } }, t('Computador modesto: o OpenFlow usa lotes e janelas de contexto menores e o cache de atenção compacto. Prefira modelos pequenos (1–4 GB) ou quantizações Q4/Q3.')) : null,
      !r.rust ? h('p', { class: 'muted small', style: { marginBottom: 0 } }, t('Sem o núcleo Rust a memória não é medida e as estimativas ficam em branco: rode  flow native setup.')) : null);
  };
  api('/api/cpu').then(paint).catch((e) => body.replaceChildren(h('span', { class: 'muted small' }, e.message)));
  return cfgCard(t('Processador (CPU)'), h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Na CPU, a velocidade de um modelo de texto depende sobretudo da memória: cada palavra lê o modelo inteiro. O OpenFlow mede a sua e ajusta threads e lotes sozinho.')), body);
}

// Várias placas de vídeo (v0.26): quais o OpenFlow pode usar. Texto (llama.cpp): camadas divididas entre as placas escolhidas; imagem/vídeo/som: a placa escolhida com mais memória livre.
function gpuCard(pf, hw) {
  const gpus = hw.gpus || [];
  if (!gpus.length) return null;
  const chosen = new Set((pf.gpus || []).map(Number));
  const all = !chosen.size;
  const save = async (set) => { pf.gpus = [...set].sort(); await saveSettings({ performance: pf }); toast(t('Salvo. Vale a partir do próximo modelo carregado.'), 'ok'); };
  return cfgCard(t('Placas de vídeo (GPUs)'),
    h('p', { class: 'muted small', style: { marginTop: 0 } }, gpus.length > 1
      ? t('{n} placas NVIDIA detectadas. Modelos de texto (llama.cpp) dividem as camadas entre as placas marcadas, em proporção à memória livre de cada uma. Imagem, vídeo e som usam a marcada com mais memória livre na hora e, se o modelo não couber nela, podem dividi-lo entre as placas (veja «Memória das placas e da RAM»). Sem nenhuma marcada, todas são usadas.', { n: gpus.length })
      : t('Uma placa NVIDIA detectada. Com mais de uma, aqui você escolhe quais usar.')),
    ...gpus.map((g) => checkbox('GPU ' + g.index + ' — ' + g.name + (g.mem_mb ? ' (' + Math.round(g.mem_mb / 1024) + ' GB)' : ''), all || chosen.has(g.index), async (v) => {
      const cur = new Set(all ? gpus.map((x) => x.index) : [...chosen]);
      if (v) cur.add(g.index); else cur.delete(g.index);
      if (!cur.size) { toast(t('Deixe ao menos uma placa marcada.'), 'err'); return; }
      await save(cur.size === gpus.length ? new Set() : cur);   // todas marcadas = sem restrição
    })));
}


// Memória das placas e da RAM (v0.59): o que o OpenFlow tem para dividir e onde cada modelo baixado caberia (uma placa, várias placas, placas + RAM)
function memoryCard(pf) {
  const mem = pf.memory = Object.assign({ multi_gpu: true, ram_spill: true, gpu_reserve_mb: 512, ram_reserve_gb: 2 }, pf.memory || {});   // `pf` é o mesmo objeto que os outros cartões gravam
  const save = async () => { await saveSettings({ performance: { memory: mem } }); toast(t('Salvo. Vale a partir do próximo modelo carregado.'), 'ok'); paint(); };
  const live = h('dl', { class: 'kv', id: 'memory-live', style: { margin: '10px 0 0' } });
  const list = h('div', { class: 'col', id: 'memory-models', style: { marginTop: '10px', gap: '6px' } });
  const gb = (b) => (b / 2 ** 30).toFixed(1) + ' GB';
  const label = (m) => ({ gpu: t('numa placa'), multi_gpu: t('dividido entre {n} placas', { n: (m.gpus || []).length }), 'gpu+ram': t('placa + RAM ({r} na RAM)', { r: gb(m.ram_bytes) }), 'multi_gpu+ram': t('placas + RAM ({r} na RAM)', { r: gb(m.ram_bytes) }), ram: t('só na RAM'), no_fit: t('não cabe') }[m.strategy] || m.strategy);
  const kind = { text: t('texto'), image: t('imagem'), video: t('vídeo') };
  let attached = false;
  async function paint() {
    if (live.isConnected) attached = true; else if (attached) return;
    try {
      const r = await api('/api/perf/memory');
      live.replaceChildren(
        ...(r.pool.gpus.length ? r.pool.gpus.flatMap((g) => [h('dt', null, 'GPU ' + g.index), h('dd', { class: 'gpu-row' }, g.name + ' · ' + gb(g.usable) + ' ' + t('usáveis') + ' (' + gb(g.free) + ' ' + t('livres de') + ' ' + gb(g.total) + ')')]) : [h('dt', null, t('Placas')), h('dd', null, t('nenhuma NVIDIA escolhida: os modelos usam a RAM'))]),
        h('dt', null, t('VRAM usável (soma)')), h('dd', { id: 'memory-vram' }, gb(r.pool.vram_usable)),
        h('dt', null, t('RAM usável')), h('dd', { id: 'memory-ram' }, gb(r.pool.ram_usable) + ' (' + gb(r.pool.ram_avail) + ' ' + t('livres') + ')'));
      list.replaceChildren(...(r.models.length ? r.models.map((m) => h('div', { class: 'row nw', dataset: { strategy: m.strategy } },
        h('span', { class: 'mono small grow', style: { overflowWrap: 'anywhere' } }, m.name), h('span', { class: 'dim small' }, kind[m.kind] + ' · ' + gb(m.size)),
        h('span', { class: 'chip ' + (m.strategy === 'no_fit' ? 'warn' : m.strategy === 'gpu' ? 'on' : '') }, label(m)))) : [h('span', { class: 'muted small' }, t('Nenhum modelo baixado ainda.'))]));
    } catch (e) { /* sem servidor agora */ }
  }
  setTimeout(paint, 0);
  const num = (id, key, min, max, step) => h('input', { type: 'number', id, min, max, step, value: mem[key], onchange: async (e) => { mem[key] = Math.max(min, Math.min(max, Number(e.target.value) || 0)); e.target.value = mem[key]; await save(); } });
  return cfgCard(t('Memória das placas e da RAM'),
    h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Para usar modelos maiores: com mais de uma placa, o OpenFlow divide o modelo entre elas (texto: as camadas; imagem e vídeo: as partes do modelo) e, o que ainda não couber, vai para a RAM do computador. Aqui você liga ou desliga cada parte e define quanta memória deixar livre.')),
    checkbox(t('Dividir modelos grandes entre as placas de vídeo'), mem.multi_gpu, async (v) => { mem.multi_gpu = v; await save(); }),
    checkbox(t('Usar a RAM junto quando o modelo não couber na VRAM'), mem.ram_spill, async (v) => { mem.ram_spill = v; await save(); }),
    h('div', { class: 'grid2', style: { marginTop: '10px' } },
      field(t('Deixar livre em cada placa (MB)'), num('memory-gpu-reserve', 'gpu_reserve_mb', 0, 8192, 64), t('Folga para a tela, o sistema e outros programas.')),
      field(t('Deixar livre na RAM (GB)'), num('memory-ram-reserve', 'ram_reserve_gb', 0, 64, 0.5), t('A RAM que o OpenFlow não toca ao completar o que falta na VRAM.'))),
    live, list);
}

// Proteção do computador (v0.49): se o CPU, a RAM ou a placa de vídeo passam do limite por alguns segundos enquanto o OpenFlow trabalha, ele para tudo (tarefas, processos e modelos carregados)
function guardCard(pf) {
  const cfg = pf.guard = Object.assign({ enabled: true, limit: 90, hold_s: 5, cpu: true, ram: true, gpu: true }, pf.guard || {});   // `pf` é o mesmo objeto que os outros cartões gravam: a proteção não é desfeita por eles
  const save = async () => { await saveSettings({ performance: { guard: cfg } }); toast(t('Salvo'), 'ok'); };
  const live = h('dl', { class: 'kv', id: 'guard-live', style: { margin: '10px 0 0' } });
  const last = h('div', { class: 'muted small', id: 'guard-last', style: { marginTop: '8px' } });
  const label = { cpu: t('Processador (CPU)'), ram: t('Memória (RAM)'), gpu: t('Placa de vídeo (GPU)') };
  let attached = false;
  const paint = (g) => {
    live.replaceChildren(...['cpu', 'ram', 'gpu'].flatMap((m) => [h('dt', null, label[m]), h('dd', { id: 'guard-' + m, class: g.over.includes(m) ? 'warn' : '' }, g.metrics[m] == null ? t('não medido neste computador') : Math.round(g.metrics[m]) + '%' + (g.over.includes(m) ? ' ⚠' : ''))]));
    last.textContent = g.last_trip ? t('Última parada: {r} (tarefas {j}, processos {p}, modelos {m})', { r: g.last_trip.reason, j: g.last_trip.stopped.jobs, p: g.last_trip.stopped.processes, m: g.last_trip.stopped.models }) : t('Nenhuma parada até agora.');
  };
  const tick = async () => { if (live.isConnected) attached = true; else if (attached) return; try { paint(await api('/api/guard')); } catch (e) { /* sem servidor */ } setTimeout(tick, 1500); };   // para sozinho quando o cartão sai da tela
  tick();
  return cfgCard(t('Proteção do computador'),
    h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Se o uso do computador passar do limite por alguns segundos enquanto o OpenFlow está trabalhando, o OpenFlow para tudo: cancela as tarefas, encerra os processos (ffmpeg, sd-cli…) e descarrega os modelos. Gerar na CPU costuma usar quase 100% dela: se isso incomoda, desmarque o processador ou aumente o limite.')),
    checkbox(t('Parar tudo quando o hardware passar do limite'), cfg.enabled, async (v) => { cfg.enabled = v; await save(); }),
    h('div', { class: 'grid2', style: { marginTop: '10px' } },
      field(t('Limite de uso (%)'), h('input', { type: 'number', id: 'guard-limit', min: 50, max: 99, value: cfg.limit, onchange: async (e) => { cfg.limit = Math.max(50, Math.min(99, parseInt(e.target.value, 10) || 90)); e.target.value = cfg.limit; await save(); } })),
      field(t('Por quantos segundos (1–60)'), h('input', { type: 'number', id: 'guard-hold', min: 1, max: 60, value: cfg.hold_s, onchange: async (e) => { cfg.hold_s = Math.max(1, Math.min(60, parseInt(e.target.value, 10) || 5)); e.target.value = cfg.hold_s; await save(); } }))),
    h('div', { class: 'row', style: { gap: '16px', flexWrap: 'wrap' } }, ['cpu', 'ram', 'gpu'].map((m) => checkbox(t('Vigiar: {m}', { m: label[m] }), cfg[m], async (v) => { cfg[m] = v; await save(); }))),
    live, last,
    h('div', { class: 'row', style: { marginTop: '10px' } }, h('button', { class: 'btn danger sm', type: 'button', id: 'guard-stop', onclick: async () => { const r = await api('/api/guard/stop', { method: 'POST', body: {} }); toast(t('Tudo foi parado.') + ' ' + t('Tarefas: {j} · processos: {p} · modelos descarregados: {m}.', { j: r.stopped.jobs, p: r.stopped.processes, m: r.stopped.models }), 'ok'); } }, icon('stop', 14), t('Parar tudo agora'))));
}

// Downloads de modelos (v0.42): a tela «Modelos» saiu da Biblioteca — a pesquisa e o download ficam na barra de pesquisa do Canvas; aqui ficam os ajustes que valem para todos eles
function downloadsCard() {
  const tokenIn = h('input', { type: 'password', autocomplete: 'off', id: 'hf-token', 'aria-label': t('Token do Hugging Face'), placeholder: state.settings.hf.token_set ? '•••••••• (' + t('salvo') + ')' : 'hf_…' });
  return cfgCard(t('Downloads de modelos'),
    h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Os modelos se pesquisam e baixam pela barra de pesquisa dentro de um projeto (Canvas). Aqui ficam os ajustes dos downloads.')),
    h('div', { class: 'field' }, h('label', { class: 'f', for: 'md-conn' }, t('Conexões por download')),
      h('select', { id: 'md-conn', 'aria-label': t('Conexões por download'), onchange: async (e) => { await saveSettings({ hf: { connections: Number(e.target.value) } }); toast(t('Salvo'), 'ok'); } },
        [1, 2, 4, 6, 8].map((n) => h('option', { value: n, selected: n === (state.settings.hf.connections || 4) }, String(n)))),
      h('div', { class: 'hint' }, t('Cada arquivo grande é baixado por várias conexões ao mesmo tempo (e retoma sozinho se a internet cair). Mais conexões costumam ser mais rápidas; use menos se a sua internet ficar lenta para o resto.'))),
    checkbox(t('Baixar junto o VAE, os codificadores de texto e o mmproj que o modelo precisa (recomendado)'), state.settings.hf.auto_support !== false, async (v) => { await saveSettings({ hf: { auto_support: v } }); }),
    h('div', { class: 'field', style: { marginTop: '12px' } }, h('label', { class: 'f', for: 'hf-token' }, t('Token do Hugging Face (opcional)')), h('div', { class: 'row nw' }, tokenIn,
      h('button', { class: 'btn', type: 'button', id: 'hf-token-save', onclick: async () => { if (tokenIn.value) { await saveSettings({ hf: { token: tokenIn.value } }); await refreshState(); tokenIn.value = ''; toast(t('Salvo'), 'ok'); } } }, t('Salvar'))),
      h('div', { class: 'hint' }, t('Necessário apenas para modelos restritos (gated).'))));
}

async function performance() {
  const pf = Object.assign({ mode: 'auto', idle_unload_min: 10 }, state.settings.performance || {});
  const nat = state.native || {};
  const hw = state.hardware;
  const cmd = (label, text) => field(label, h('div', { class: 'codebox' }, h('span', null, text), h('button', { class: 'btn sm ghost', 'aria-label': t('Copiar'), title: t('Copiar'), onclick: () => { navigator.clipboard.writeText(text).then(() => toast(t('Copiado'))); } }, icon('copy', 13))));
  return h('div', null,
    cfgCard(t('Desempenho'),
      h('div', { class: 'grid2' },
        field(t('Modo'), select([['auto', t('Automático (conforme o hardware)')], ['light', t('Leve — menos RAM/VRAM')], ['balanced', t('Equilibrado')], ['max', t('Máximo')]], pf.mode, async (v) => { pf.mode = v; await saveSettings({ performance: pf }); toast(t('Salvo'), 'ok'); }),
          t('Leve: limita a janela de contexto, comprime o cache de atenção, descarrega modelos ociosos e usa menos memória de vídeo nos modelos de imagem/vídeo.')),
        field(t('Rodar em'), select([['auto', t('Automático (GPU se houver)')], ['cpu', t('Só CPU')], ['gpu', t('GPU (placa de vídeo)')], ['hybrid', t('Híbrido: CPU e GPU juntas')]], pf.device || 'auto', async (v) => { pf.device = v; await saveSettings({ performance: pf }); toast(t('Salvo'), 'ok'); }),
          t('Onde os modelos rodam. «GPU» usa a placa de vídeo (NVIDIA: CUDA; AMD/Intel: Vulkan); «Só CPU» nunca a usa; «Híbrido» usa as duas: no texto, a placa leva as camadas que couberem, a CPU o resto e ainda propõe os próximos tokens (a placa confirma); em imagem e vídeo o codificador de texto e o VAE rodam na CPU e a placa fica só com o modelo. O executável sd-cli certo é baixado sozinho na próxima geração.') + ' ' + (hw.gpu ? t('GPU detectada: {g}', { g: hw.gpu }) : t('Nenhuma GPU NVIDIA detectada.'))),
        field(t('Descarregar modelos ociosos após (min)'), h('input', { type: 'number', min: 0, max: 1440, value: pf.idle_unload_min, onchange: async (e) => { pf.idle_unload_min = Math.max(0, parseInt(e.target.value || '0', 10)); await saveSettings({ performance: pf }); toast(t('Salvo'), 'ok'); } }), t('0 = nunca. No modo leve o limite é de até 3 min.'))),
      h('p', { class: 'muted small', style: { marginBottom: 0 } }, t('Seu hardware: {t}', { t: hw.tier }) + ' · ' + hw.cpus + ' CPU · ' + (hw.ram_gb ? hw.ram_gb + ' GB RAM' : '—') + ' · ' + (hw.gpu || t('não detectada (NVIDIA)')))),
    guardCard(pf),
    gpuCard(pf, hw),
    memoryCard(pf),
    cpuCard(pf),
    downloadsCard(),
    gpuAccelCard(hw),
    frameworksCard(),
    cfgCard(t('Núcleo Rust'),
      h('dl', { class: 'kv', style: { margin: 0 } }, h('dt', null, t('Núcleo Rust')), h('dd', null, nat.active ? h('span', { class: 'chip on' }, t('ativo')) : h('span', { class: 'muted' }, t('inativo — usando Python puro'))),
        h('dt', null, 'Rust (cargo)'), h('dd', null, nat.cargo ? t('encontrado') : t('não encontrado (opcional)')),
        h('dt', null, t('Carga de modelos locais')), h('dd', { id: 'nat-models' }, nat.models ? h('span', { class: 'chip on' }, t('otimizada')) : h('span', { class: 'muted' }, t('padrão (recompile o núcleo: flow native setup)'))),
        h('dt', null, t('Armazenamento e memória')), h('dd', { id: 'nat-ops' }, nat.ops ? h('span', { class: 'chip on' }, t('otimizados')) : h('span', { class: 'muted' }, t('padrão (atualize o núcleo: flow native setup)'))),
        h('dt', null, t('Processador')), h('dd', null, (nat.cores ? t('{p} núcleos físicos · {l} threads', { p: nat.cores[0], l: nat.cores[1] }) : '—') + ((nat.features || []).length ? ' · ' + nat.features.join(' ').toUpperCase() : '')),
        nat.last && nat.last.llm ? h('dt', null, t('Último modelo de texto')) : null,
        nat.last && nat.last.llm ? h('dd', { id: 'nat-llm' }, nat.last.llm.model + ' · ' + t('contexto {c}', { c: nat.last.llm.n_ctx }) + ' · ' + (nat.last.llm.n_gpu_layers === -1 ? t('tudo na GPU') : nat.last.llm.n_gpu_layers > 0 ? t('{n} camadas na GPU', { n: nat.last.llm.n_gpu_layers }) : t('na CPU')) + ' · ' + t('{n} threads', { n: nat.last.llm.n_threads }) + (nat.last.llm.kv_q8 ? ' · ' + t('cache em 8 bits') : '')) : null,
        nat.last && nat.last.media ? h('dt', null, t('Último modelo de mídia')) : null,
        nat.last && nat.last.media ? h('dd', { id: 'nat-media' }, nat.last.media.model + ' · ' + ({ gpu: t('tudo na GPU'), model_offload: t('descarga do modelo'), sequential_offload: t('descarga sequencial (pouca VRAM)'), cpu: t('na CPU') }[nat.last.media.strategy] || '—')) : null),
      h('p', { class: 'muted small' }, t('O núcleo Rust é parte do OpenFlow: faz a síntese de áudio do OpenFlow, lê o cabeçalho dos modelos locais, escolhe contexto (até 1M de tokens), camadas na GPU e threads pela memória livre, procura arquivos duplicados e devolve memória ao sistema. Os instaladores já o trazem; pelo terminal o OpenFlow baixa a biblioteca pronta da Release (sem compilador). Se ele estiver inativo, o OpenFlow funciona em Python, só mais devagar. Para ativar agora, rode no terminal:')),
      cmd(t('Ativar/atualizar o núcleo Rust (baixa a biblioteca pronta)'), 'flow native setup')));
}

const CAPS = [['image', 'Imagem'], ['video', 'Vídeo'], ['sound', 'Som e música'], ['voice', 'Voz (texto → fala)'], ['stt', 'Transcrição (fala → texto)'], ['model3d', 'Modelo 3D (texto/imagem → 3D)']];

async function media() {
  let data = await api('/api/media/providers');
  const container = h('div');
  const paint = () => container.replaceChildren(defaults(), h('div', null, data.providers.filter((p) => p.id !== 'demo').map(card)), demoCard());

  const reload = async () => { data = await api('/api/media/providers'); await refreshState(); paint(); };
  function defaults() {
    return h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', null, t('Modelo padrão de cada tipo de mídia')),
      h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Cada nó do OpenFlow pode escolher outro provedor. Aqui fica o padrão do projeto. “Demo” funciona offline, sem IA, para testar os fluxos.')),
      h('div', { class: 'grid2' }, CAPS.map(([cap, label]) => field(t(label), select(data.providers.filter((p) => p.caps.includes(cap)).map((p) => [p.id, t(p.label)]), data.active[cap] || 'demo',
        async (v) => { await saveSettings({ media: { active: { [cap]: v } } }); data.active[cap] = v; toast(t('Salvo'), 'ok'); })))));
  }
  function demoCard() {
    const d = data.providers.find((p) => p.id === 'demo');
    return h('div', { class: 'card', style: { marginTop: '16px' } }, h('h3', null, t(d.label)), h('p', { class: 'muted small', style: { margin: 0 } }, t(d.hint)));
  }
  function card(p) {
    const draft = { models: Object.assign({}, p.models) };
    const res = h('div', { class: 'res' });
    const inUse = CAPS.filter(([cap]) => data.active[cap] === p.id).map(([, l]) => t(l));
    const body = h('div', { class: 'bd' });
    const inputs = [];
    const listId = 'mm-' + p.id;
    inputs.push(h('datalist', { id: listId }));
    const modelCaps = CAPS.filter(([cap]) => p.caps.includes(cap));
    if (p.id === 'local_hf') inputs.push(localModels(p, draft));
    else if (modelCaps.length) inputs.push(h('div', { class: 'grid2' }, modelCaps.map(([cap, label]) => {
      const dl = h('datalist', { id: listId + cap }, ((p.suggest || {})[cap] || []).map((m) => h('option', { value: m })));
      return field(t('Modelo') + ' · ' + t(label), h('div', null, h('input', { list: listId + cap, value: draft.models[cap] || '', placeholder: t('padrão do provedor'), oninput: (e) => { draft.models[cap] = e.target.value.trim(); } }), dl));
    })));
    if (p.hint) inputs.push(h('p', { class: 'muted small' }, t(p.hint)));
    const test = async () => {
      res.className = 'res'; res.textContent = t('Testando…');
      try { const r = await api('/api/media/test', { method: 'POST', body: { provider: p.id } }); res.className = 'res ok'; res.textContent = '✓ ' + r.message; }
      catch (e) { res.className = 'res err'; res.textContent = '✗ ' + e.message; }
    };
    const save = async () => {
      const patch = { media: { models: { [p.id]: draft.models } } };
      await saveSettings(patch); toast(t('Salvo'), 'ok'); reload();
    };
    inputs.push(h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'btn sm primary', onclick: save }, t('Salvar')), h('button', { class: 'btn sm', onclick: async () => { await save(); test(); } }, t('Salvar e testar')),
      h('span', { class: 'dim small' }, t('Use “Salvar e testar” para conferir se o provedor está pronto.'))), res);
    body.replaceChildren(...inputs);
    const cardEl = h('div', { class: 'prov' + (inUse.length ? ' open' : '') });
    cardEl.append(h('div', { class: 'hd', onclick: () => cardEl.classList.toggle('open') },
      h('span', { class: 'nm' }, t(p.label)),
      h('span', { class: 'dim small', style: { marginLeft: '8px' } }, p.caps.map((c) => t((CAPS.find((x) => x[0] === c) || [0, c])[1])).join(' · ')),
      h('span', { class: 'roles' }, inUse.map((l) => h('span', { class: 'chip on' }, l)))), body);
    return cardEl;
  }
  paint();
  return container;
}

function localModels(p, draft) {
  const box = h('div', { class: 'col', style: { gap: '10px' } });
  const rows = {}, chips = {};
  const caps = CAPS.filter(([cap]) => p.caps.includes(cap));
  const modelOf = (cap) => draft.models[cap] || p.models[cap] || '';
  const setChip = (cap, prec) => { chips[cap].className = 'chip ' + (prec ? 'on' : ''); chips[cap].textContent = prec ? t('baixado · {p}', { p: prec }) : t('não baixado'); };
  async function refresh() {
    try {
      const st = await api('/api/media/local/state');
      if (!st.libs) { hint.textContent = t('Instale as bibliotecas dos modelos locais para baixá-los:') + ' pip install "openflow[media]"  (' + t('ou rode') + ' flow libs)'; }
      for (const [cap] of caps) setChip(cap, (st.models[cap] && st.models[cap].model === modelOf(cap) && st.models[cap].precision) || '');
    } catch (e) { /* sem estado: os chips ficam como "não baixado" */ }
  }
  const hint = h('p', { class: 'muted small', style: { margin: 0 } }, t('Escolha o modelo de cada tipo e, antes de usá-lo, a precisão (quantização) do download: o OpenFlow só baixa depois da sua escolha e só carrega o que você baixou.'));
  function panel(cap) {
    const model = modelOf(cap), area = rows[cap].area;
    if (!/^[\w.-]+\/[\w.-]+$/.test(model)) return toast(t('Informe o modelo no formato dono/nome (ex.: stabilityai/sd-turbo).'), 'err');
    area.replaceChildren(h('div', { class: 'spinner' }));
    api('/api/media/local/options?model=' + encodeURIComponent(model)).then((r) => {
      let pick = null;
      const list = h('div', { class: 'col', style: { gap: '6px' } }), btn = h('button', { class: 'btn primary' });
      const paint = () => {
        list.replaceChildren(...r.options.map((o) => h('label', { class: 'quant' + (o === pick ? ' on' : ''), onclick: () => { pick = o; paint(); } },
          h('input', { type: 'radio', name: 'prec-' + cap, checked: o === pick }),
          h('div', { class: 'grow' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', null, o.id), o.recommended ? h('span', { class: 'chip on' }, t('Recomendada')) : null),
            h('div', { class: 'dim small' }, t(PREC_HINT[o.id])), o.memory ? h('div', { class: 'dim small' }, t('Memória ≈ {n}', { n: fmtBytes(o.memory) })) : null),
          h('span', { class: 'chip solid' }, o.size ? fmtBytes(o.size) : '?'))));
        btn.disabled = !pick;
        btn.replaceChildren(icon('download', 14), pick ? t('Baixar {q} ({s})', { q: model + ' · ' + pick.id, s: pick.size ? fmtBytes(pick.size) : '?' }) : t('Escolha uma precisão para baixar'));
      };
      btn.onclick = async () => {
        if (!pick) return;
        const bar = h('i'), label = h('span', { class: 'small muted' }, '0%');
        area.replaceChildren(h('div', { class: 'card' }, h('div', { class: 'row', style: { marginBottom: '8px' } }, h('span', { class: 'mono small' }, model + ' · ' + pick.id), h('span', { class: 'grow' }), label, h('button', { class: 'btn sm', id: 'lm-cancel-' + cap }, t('Cancelar'))), h('div', { class: 'bar' }, bar)));
        let jid;
        try { await saveSettings({ media: { models: { local_hf: { [cap]: model } } } }); jid = (await api('/api/media/local/download', { method: 'POST', body: { model, precision: pick.id } })).job_id; }
        catch (e) { area.replaceChildren(); return toast(e.status === 409 ? t('Já há um download em andamento.') : e.message, 'err'); }
        area.querySelector('#lm-cancel-' + cap).onclick = () => api('/api/jobs/' + jid + '/cancel', { method: 'POST' });
        events('/api/jobs/' + jid + '/events', (ev) => {
          if (ev.type === 'progress' && ev.total) { const pc = Math.min(1, ev.done / ev.total); bar.style.width = Math.round(pc * 100) + '%'; label.textContent = Math.round(pc * 100) + '% · ' + fmtBytes(ev.done) + ' / ' + fmtBytes(ev.total); }
          else if (ev.type === 'done') { toast(t('Download concluído'), 'ok'); area.replaceChildren(); refresh(); }
          else if (ev.type === 'error') { toast(ev.message, 'err'); area.replaceChildren(); }
          else if (ev.type === 'cancelled') { toast(t('Download cancelado')); area.replaceChildren(); }
        });
      };
      paint();
      const quants = h('div', { class: 'col', id: 'quants-' + cap, style: { gap: '6px', marginTop: '14px' } }, h('div', { class: 'small muted' }, t('Procurando versões menores (quantizadas)…')));
      area.replaceChildren(h('div', { class: 'small muted' }, t('Escolha a precisão: menos bits = download menor e mais rápido, com um pequeno custo de qualidade; o fp16 pede placa de vídeo.')), list, h('div', { style: { marginTop: '8px' } }, btn), quants);
      // versões menores (8 e 4 bits, fp8…) feitas pela comunidade: o download encolhe de verdade; usar uma delas troca o modelo escolhido por aquele repositório
      api('/api/media/local/quants?model=' + encodeURIComponent(model)).then((q) => {
        const vs = q.variants || [];
        if (!vs.length) { quants.replaceChildren(h('div', { class: 'small dim' }, t('Não há versões menores deste modelo na Hugging Face. Para modelos de texto, use as versões GGUF pela barra de pesquisa de modelos do Canvas.'))); return; }
        quants.replaceChildren(h('b', { class: 'small' }, t('Quantizações menores (da comunidade)')), h('div', { class: 'small dim' }, t('Pesos já comprimidos (8 ou 4 bits): download e memória bem menores, com algum custo de qualidade. Feitas por terceiros, não pelo OpenFlow.')),
          ...vs.map((v) => h('div', { class: 'quant qv', dataset: { quant: v.id } },
            h('div', { class: 'grow' }, h('div', { class: 'row', style: { gap: '8px' } }, h('b', { class: 'mono small' }, v.id), h('span', { class: 'chip' }, v.kind)), h('div', { class: 'dim small' }, t(v.note))),
            h('span', { class: 'chip solid' }, v.size ? fmtBytes(v.size) : '?'),
            v.loadable ? h('button', { class: 'btn sm', type: 'button', onclick: () => { draft.models[cap] = v.id; rows[cap].input.value = v.id; setChip(cap, ''); panel(cap); } }, icon('download', 13), t('Usar esta')) : h('span', { class: 'dim small' }, t('não suportada aqui')))));
      }).catch(() => { quants.replaceChildren(h('div', { class: 'small dim' }, t('Não consegui procurar versões menores agora (sem conexão com a Hugging Face).'))); });
    }).catch((e) => { area.replaceChildren(h('div', { class: 'res err' }, e.message)); });
  }
  for (const [cap, label] of caps) {
    const dl = h('datalist', { id: 'lm-' + cap }, ((p.suggest || {})[cap] || []).map((m) => h('option', { value: m })));
    const input = h('input', { list: 'lm-' + cap, value: draft.models[cap] || '', placeholder: p.models[cap] || '', oninput: (e) => { draft.models[cap] = e.target.value.trim(); setChip(cap, ''); } });
    chips[cap] = h('span', { class: 'chip' }, t('não baixado'));
    rows[cap] = { area: h('div'), input };
    box.append(h('div', null, h('label', { class: 'f' }, t('Modelo') + ' · ' + t(label)), h('div', { class: 'row nw' }, input, dl, chips[cap], h('button', { class: 'btn sm', onclick: () => panel(cap) }, icon('download', 13), t('Precisão e download'))), rows[cap].area));
  }
  refresh();
  return h('div', { class: 'col', style: { gap: '10px', marginBottom: '8px' } }, hint, box);
}
