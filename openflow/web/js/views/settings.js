import { api, events } from '../api.js';
import { t } from '../i18n.js';
import { go, refreshState, renderSide, saveSettings, state } from '../main.js';
import { accentSwatches, themeCards } from '../appearance.js';
import { ui } from '../prefs.js';
import { PREC_HINT } from '../model_labels.js';
import { checkbox, confirmDialog, field, fmtBytes, h, icon, select, seg, toast } from '../ui.js';
import { SETTINGS_TABS } from '../labels.js';
import { AGENT_COUNTS, teamFields } from '../team_ui.js';

// Configurações do OpenFlow: IA de texto, provedores de mídia (imagem, vídeo, som e voz), voz, projetos, aparência e desempenho.
// Modelos locais (download, VAE, codificadores de texto e mmproj) ficam na tela «Modelos».
const TABS = SETTINGS_TABS;

export default async function render(root, ctx) {
  let tab = TABS.some(([id]) => id === ctx.tab) ? ctx.tab : 'providers';
  const body = h('div'), tabs = h('div', { class: 'tabs cfgtabs', role: 'tablist', 'aria-label': t('Configurações') });
  const FNS = { providers, media, voice, project: projectTab, appearance, performance };
  const paintTabs = () => tabs.replaceChildren(...TABS.map(([id, l]) => h('button', { class: tab === id ? 'on' : '', role: 'tab', 'aria-selected': tab === id ? 'true' : 'false', dataset: { tab: id }, onclick: () => { tab = id; paintTabs(); paintBody(); } }, t(l))));
  const paintBody = async () => { body.replaceChildren(h('div', { class: 'spinner' })); body.replaceChildren(await (FNS[tab] || providers)()); };
  root.replaceChildren(h('div', { class: 'page narrow cfg' }, h('div', { class: 'page-h' }, h('div', null, h('h1', null, t('Configurações')), h('p', null, t('Modelos de IA, provedores de mídia, aparência e desempenho: configure uma vez e use em todos os projetos.')))), tabs, body));
  paintTabs(); await paintBody();
}

const teamCard = (cfg, id, note, o = {}) => h('div', { class: 'card', id: id + '-card', style: { marginBottom: '16px' } }, h('h3', null, o.title || t('Equipe de agentes')),
  h('p', { class: 'muted small', style: { marginTop: 0 } }, note || t('Os mesmos 8 níveis de esforço do Code (Low a Omni) e até 32 agentes trabalhando em paralelo em cada etapa, com um Sintetizador que junta o melhor de todos (a partir de 20, os agentes também revisam os rascunhos uns dos outros). Mais agentes e mais esforço = respostas melhores, mas mais tempo e mais chamadas à IA.')),
  teamFields(cfg, Object.assign({ id }, o)));

const cfgCard = (title, ...kids) => h('div', { class: 'card', style: { marginBottom: '16px' } }, title ? h('h3', null, title) : null, ...kids);

const saveRow = (fn) => h('div', { class: 'row', style: { justifyContent: 'flex-end' } }, h('button', { class: 'btn primary', type: 'button', id: 'cfg-save', onclick: async () => { try { await fn(); toast(t('Salvo'), 'ok'); } catch (e) { toast(e.message, 'err'); } } }, icon('check', 15), t('Salvar')));

const numInput = (obj, key, min, max, step) => h('input', { type: 'number', min, max, step: step || 1, value: obj[key], oninput: (e) => { const v = parseFloat(e.target.value); if (!Number.isNaN(v)) obj[key] = v; } });

function accountBox(p, cfg, repaint) {
  const msg = h('p', { class: 'muted small', style: { margin: '6px 0 0' } });
  const connected = cfg.auth === 'account' && cfg.has_key;
  if (p.oauth) {
    const go = async () => {
      msg.textContent = '';
      try {
        const r = await api('/api/auth/openrouter/start', { method: 'POST', body: {} });
        const w = window.open(r.url, 'flow-login', 'width=520,height=720');
        if (!w) { location.href = r.url; return; }
        msg.textContent = t('Faça o login na janela que abriu…');
        const done = async () => { window.removeEventListener('message', onMsg); await refreshState(); toast(t('Conta conectada'), 'ok'); renderSide(); repaint(); };
        const onMsg = (e) => { if (e.data === 'flow-auth-ok') done(); };
        window.addEventListener('message', onMsg);
        const tick = setInterval(async () => { if (w.closed) { clearInterval(tick); await refreshState(); const c = (state.settings.providers || {})[p.id] || {}; if (c.auth === 'account' && c.has_key) done(); else { window.removeEventListener('message', onMsg); msg.textContent = ''; } } }, 800);
      } catch (e) { msg.textContent = e.message; msg.className = 'err small'; }
    };
    return h('div', { class: 'field', dataset: { account: p.id } }, h('label', { class: 'f' }, t('Conta')),
      h('div', { class: 'row' }, h('button', { class: 'btn' + (connected ? '' : ' primary'), type: 'button', id: 'acct-' + p.id, onclick: go }, icon('user', 14), connected ? t('Entrar de novo com a conta') : t('Entrar com a conta do {p}', { p: 'OpenRouter' })),
        connected ? h('span', { class: 'chip on' }, t('conta conectada')) : null,
        connected ? h('button', { class: 'btn sm danger', type: 'button', onclick: async () => { await saveSettings({ providers: { [p.id]: { api_key: null, auth: '' } } }); toast(t('Conta desconectada')); await refreshState(); repaint(); } }, t('Desconectar')) : null),
      h('p', { class: 'muted small', style: { margin: '6px 0 0' } }, t('Login oficial (OAuth): você autoriza no site do OpenRouter e não precisa copiar chave. O uso é cobrado na sua conta de lá.')), msg);
  }
  return h('div', { class: 'field', dataset: { account: p.id } }, h('label', { class: 'f' }, t('Conta')),
    h('div', { class: 'row' }, h('a', { class: 'btn', href: p.login, target: '_blank', rel: 'noopener', id: 'acct-' + p.id }, icon('user', 14), t('Entrar na conta e criar a chave'))),
    h('p', { class: 'muted small', style: { margin: '6px 0 0' } }, t('Este provedor não deixa outros apps usarem o login da conta nem da assinatura (Claude Pro, ChatGPT Plus…): você entra no site dele, cria a chave em um clique e cola no campo abaixo.')));
}

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
        t('Usado pelo nó Texto IA, pelo planejador de fluxos («Montar o fluxo com IA») e para descrever as pastas de estilo. «Demo» funciona offline, sem IA, para testar.')));
  };
  const paint = () => container.replaceChildren(rolesCard(), h('div', null, presets.map(card)));

  function card(p) {
    const S = state.settings, cfg = (S.providers && S.providers[p.id]) || {};
    const isGen = S.active.generation === p.id, isChar = false;
    const configured = p.id === 'demo' || cfg.has_key || cfg.model || (p.local && cfg.base_url);
    const draft = { base_url: cfg.base_url || '', model: cfg.model || '', api_key: '', vision: cfg.vision != null ? cfg.vision : p.vision, n_ctx: cfg.n_ctx > 0 ? cfg.n_ctx : 0 };
    const res = h('div', { class: 'res' });
    const dl = h('datalist', { id: 'models-' + p.id }, (p.kind === 'local_hf' ? localModels : []).map((m) => h('option', { value: m })));
    const cardEl = h('div', { class: 'prov' + (isGen || isChar ? ' open' : '') });
    const bodyEl = h('div', { class: 'bd' });

    const loadModels = async () => {
      res.className = 'res'; res.textContent = '…';
      const r = await api('/api/providers/models', { method: 'POST', body: { id: p.id, config: draft } });
      if (!r.ok) { res.className = 'res err'; res.textContent = r.error; return; }
      dl.replaceChildren(...r.models.map((m) => h('option', { value: m }))); res.className = 'res ok'; res.textContent = t('{n} modelos disponíveis — clique no campo Modelo para escolher.', { n: r.models.length });
    };
    const test = async () => {
      res.className = 'res'; res.textContent = t('Testando…');
      const r = await api('/api/providers/test', { method: 'POST', body: { id: p.id, config: draft } });
      res.className = 'res ' + (r.ok ? 'ok' : 'err');
      res.textContent = r.ok ? '✓ ' + t('Funcionou') + ' (' + (r.ms / 1000).toFixed(1) + ' s) · ' + t('resposta:') + ' ' + r.reply : '✗ ' + r.error;
    };
    const save = async () => {
      const patch = { base_url: draft.base_url, model: draft.model };
      if (p.id !== 'lmstudio') patch.vision = !!draft.vision;   // no LM Studio a visão é detectada pelo tipo do modelo (vlm)
      if (p.kind === 'local_hf') patch.n_ctx = draft.n_ctx > 0 ? draft.n_ctx : 0;   // 0 = automático
      if (draft.api_key) patch.api_key = draft.api_key;
      await saveSettings({ providers: { [p.id]: patch } }); draft.api_key = ''; toast(t('Salvo'), 'ok'); await refreshState(); renderSide(); paint();
    };
    const inputs = [];
    if (p.id === 'demo') inputs.push(h('p', { class: 'muted small', style: { margin: '10px 0 0' } }, t(p.hint)));
    else {
      if (p.id === 'lmstudio') inputs.push(lmStudioBox(p, draft, () => modelIn));
      if (p.oauth || p.login) inputs.push(accountBox(p, cfg, () => { paint(); }));
      if (p.needs_key || p.kind === 'openai' || p.id === 'anthropic') inputs.push(field(t('Chave de API') + (p.needs_key ? '' : ' (' + t('opcional') + ')'),
        h('div', { class: 'row nw' }, h('input', { type: 'password', autocomplete: 'off', placeholder: cfg.has_key ? '•••••••• (' + t('salva') + ')' : 'sk-…', oninput: (e) => { draft.api_key = e.target.value; } }),
          cfg.has_key ? h('button', { class: 'btn sm danger', onclick: async () => { await saveSettings({ providers: { [p.id]: { api_key: null } } }); toast(t('Chave removida')); await refreshState(); paint(); } }, t('Remover')) : null),
        p.docs ? h('a', { href: p.docs, target: '_blank', rel: 'noopener', class: 'muted' }, t('Obter chave →')) : null));
      if (p.kind === 'openai' || p.id === 'anthropic') inputs.push(field(t('URL base'), h('input', { value: draft.base_url || p.base_url, placeholder: p.base_url || 'https://…/v1', oninput: (e) => { draft.base_url = e.target.value.trim(); } })));
      const modelIn = h('input', { list: 'models-' + p.id, value: draft.model, placeholder: p.kind === 'local_hf' ? t('arquivo .gguf baixado') : p.id === 'lmstudio' ? t('automático: o modelo carregado no LM Studio') : t('clique em “Carregar modelos”'), oninput: (e) => { draft.model = e.target.value.trim(); } });
      inputs.push(field(t('Modelo'), h('div', { class: 'row nw' }, modelIn, dl,
        p.kind !== 'local_hf' ? h('button', { class: 'btn sm', onclick: loadModels }, icon('refresh', 13), t('Carregar modelos')) : null)));
      if (p.id === 'lmstudio') { /* visão: automática pelo tipo do modelo */ }
      else if (p.kind !== 'local_hf') inputs.push(checkbox(t('Aceita imagens (visão)'), draft.vision, (v) => { draft.vision = v; }));
      else {
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
      h('span', { class: 'nm' }, t(p.label)), p.local ? h('span', { class: 'badge' }, t('local')) : null,
      h('span', { class: 'roles' }, isGen ? h('span', { class: 'chip on' }, t('geração')) : null, null)), bodyEl);
    return cardEl;
  }
  paint();
  return container;
}

function lmWhy(r) {
  let host = ''; try { host = new URL(r.url).hostname; } catch (e) { /* ok */ }
  const own = /^(127\.|localhost$|\[?::1)/.test(host);
  if (own) return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || '') ? t('O LM Studio não roda neste aparelho. Para usar o do seu computador, use «LM Studio no computador» abaixo (IP do computador, não 127.0.0.1).') : t(r.hint);
  if (r.kind === 'refused') return t('O computador respondeu que a porta está fechada: no LM Studio (Developer) ligue «Serve on Local Network» — sem isso ele só aceita conexões do próprio computador — e reinicie o servidor.');
  if (r.kind === 'timeout') return t('O computador não respondeu a tempo: libere a porta 1234 no firewall (no Windows: «Permitir um aplicativo» para o LM Studio, rede privada), e confira se o celular está no mesmo Wi-Fi (redes de visitantes isolam os aparelhos).');
  if (r.kind === 'dns') return t('Não achei esse endereço. Digite o IP do computador (ex.: 192.168.0.10), que aparece no LM Studio em Developer, ao lado de «Serve on Local Network».');
  if (r.kind === 'unreachable') return t('Sem caminho até esse endereço: confira se o celular está no mesmo Wi-Fi do computador e o IP digitado.');
  return t(r.hint);
}

function pcBox(draft, detect) {
  if (!/Android|iPhone|iPad|iPod/i.test(navigator.userAgent || '')) return null;
  const out = h('div', { class: 'muted small', style: { marginTop: '6px' } });
  const addr = h('input', { id: 'lms-pc-addr', inputmode: 'url', autocapitalize: 'off', placeholder: '192.168.0.10  ·  192.168.0.10:1234', 'aria-label': t('Endereço do computador') });
  const point = async (url) => {
    draft.base_url = url; await saveSettings({ providers: { lmstudio: { base_url: url } } });
    let ok = false; try { ok = (await api('/api/lmstudio?url=' + encodeURIComponent(url))).running; } catch (e) { /* o detect mostra o motivo */ }
    if (ok) { await saveSettings({ active: { generation: 'lmstudio', characters: 'lmstudio' } }); toast(t('Conectado ao LM Studio do computador.'), 'ok'); await refreshState(); renderSide(); }   // quem conectou quer usar: o Chat e os avatares passam a usar os modelos dele
    detect();
  };
  const scan = async () => {
    out.replaceChildren(h('div', { class: 'spinner' }), ' ', t('Procurando o LM Studio na rede…'));
    let r;
    try { r = await api('/api/lmstudio/scan', { method: 'POST', body: {} }); } catch (e) { out.textContent = e.message; return; }
    if (!r.servers.length) { out.textContent = t('Não achei. No computador: LM Studio → Developer → ligue «Serve on Local Network» e «Start Server»; o celular precisa estar no mesmo Wi-Fi. Ou digite o IP do computador.'); return; }
    out.replaceChildren(...r.servers.map((sv) => h('button', { class: 'btn sm', type: 'button', onclick: () => point(sv.url) }, sv.url + ' · ' + t('{n} modelo(s)', { n: sv.models }))));
  };
  const manual = () => {
    let v = addr.value.trim();
    if (!v) { out.textContent = t('Digite o IP do computador (ex.: 192.168.0.10).'); return; }
    const scheme = (v.match(/^(https?):\/\//i) || [, ''])[1].toLowerCase();   // https:// (túnel) é mantido; sem esquema vale http + porta 1234
    v = v.replace(/^https?:\/\//i, '');
    const path = /^[^/]+\/lm\/[\w-]+/.test(v) ? v.slice(v.indexOf('/')).replace(/\/(v1|api\/v0)(\/.*)?$/, '').replace(/\/$/, '') : '';   // link «…/lm/<código>» do acesso de fora de casa
    v = v.replace(/\/.*$/, '');
    if (!scheme && !/:\d+$/.test(v)) v += ':1234';
    point((scheme || 'http') + '://' + v + path);
  };
  return h('div', { class: 'lms-pc', id: 'lms-pc', style: { marginTop: '12px', paddingTop: '10px', borderTop: '1px solid var(--line, rgba(255,255,255,.1))' } },
    h('b', null, t('LM Studio no computador')),
    h('p', { class: 'muted small', style: { margin: '4px 0 8px' } }, t('Use os modelos do LM Studio do seu computador por este aparelho, na mesma rede Wi-Fi.')),
    h('p', { class: 'muted small', style: { margin: '0 0 8px' } }, t('Fora de casa, sem VPN: no computador, abra Configuração → Celular e tablet → «LM Studio fora de casa», ligue e copie o link; cole-o aqui. (Ou use o Tailscale: digite o IP 100.x.x.x ou o nome ….ts.net do computador.)')),
    h('div', { class: 'row', style: { gap: '8px', flexWrap: 'wrap' } }, h('button', { class: 'btn sm primary', type: 'button', id: 'lms-pc-scan', onclick: scan }, icon('refresh', 13), t('Procurar na rede')), addr,
      h('button', { class: 'btn sm', type: 'button', id: 'lms-pc-go', onclick: manual }, t('Conectar'))), out);
}

function lmStudioBox(p, draft, getModelInput) {
  const box = h('div', { class: 'card', style: { background: 'var(--bg2, rgba(255,255,255,.03))', margin: '4px 0 12px', padding: '12px 14px' } });
  const status = h('div', { class: 'row', style: { gap: '8px' } }), list = h('div', { class: 'row', style: { gap: '6px', flexWrap: 'wrap', marginTop: '8px' } }), note = h('p', { class: 'muted small', style: { margin: '8px 0 0' } });
  const use = async (role) => {
    await saveSettings({ providers: { lmstudio: { base_url: draft.base_url, model: draft.model } }, active: { [role]: 'lmstudio' } });
    toast(role === 'characters' ? t('Os avatares vão conversar pelo LM Studio.') : t('A geração vai usar o LM Studio.'), 'ok'); await refreshState(); renderSide();
  };
  async function detect() {
    status.replaceChildren(h('div', { class: 'spinner' })); list.replaceChildren(); note.textContent = '';
    let r;
    try { r = await api('/api/lmstudio?url=' + encodeURIComponent(draft.base_url || '')); } catch (e) { status.replaceChildren(h('span', { class: 'dim small' }, e.message)); return; }
    const dot = h('span', { style: { width: '9px', height: '9px', borderRadius: '50%', background: r.running ? 'var(--ok)' : 'var(--dim)', display: 'inline-block' } });
    status.replaceChildren(dot, h('b', null, r.running ? t('LM Studio detectado em {u}', { u: r.url }) : t('LM Studio não detectado em {u}', { u: r.url })), h('span', { class: 'grow' }),
      h('button', { class: 'btn sm', onclick: detect }, icon('refresh', 13), t('Detectar de novo')),
      r.running ? h('button', { class: 'btn sm primary', onclick: () => use('characters') }, t('Usar nos avatares')) : null,
      r.running ? h('button', { class: 'btn sm', onclick: () => use('generation') }, t('Usar na geração')) : null);
    if (!r.running) { note.textContent = lmWhy(r) + (r.error ? ' (' + r.error + ')' : ''); return; }
    list.replaceChildren(...(r.models.length ? r.models.map((m) => h('button', { class: 'chip' + (draft.model === m.id || (!draft.model && r.selected === m.id) ? ' on' : ''), title: [m.loaded ? t('carregado') : t('não carregado'), m.quant, m.vision ? t('visão') : ''].filter(Boolean).join(' · '),
      onclick: () => { draft.model = m.id; const inp = getModelInput(); if (inp) inp.value = m.id; detect(); } }, (m.loaded ? '● ' : '○ ') + m.id + (m.vision ? ' 👁' : ''))) : [h('span', { class: 'dim small' }, t('Nenhum modelo instalado: baixe um na aba «Discover» do LM Studio.'))]));
    note.textContent = r.loaded.length ? t('● carregado agora · ○ instalado (o LM Studio pode carregar sob demanda). Sem escolher, o OpenFlow usa o modelo carregado.') : t('Nenhum modelo está carregado no LM Studio: carregue um (ou escolha um acima).');
  }
  box.append(status, list, note, pcBox(draft, detect)); detect();
  return box;
}

async function voice() {
  const v = JSON.parse(JSON.stringify(state.settings.voice));
  const block = (key, title, extra) => {
    const x = v[key];
    return h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', null, title),
      field(t('Motor'), seg([['browser', t('Navegador (grátis)')], ['server', t('Servidor compatível com OpenAI')]], x.engine, (val) => { x.engine = val; })),
      h('div', { class: 'grid2' }, field(t('URL base'), h('input', { value: x.base_url, placeholder: 'https://api.openai.com/v1  ·  http://localhost:8000/v1', oninput: (e) => { x.base_url = e.target.value.trim(); } })),
        field(t('Chave de API'), h('input', { type: 'password', autocomplete: 'off', placeholder: state.settings.voice[key].api_key_set ? '•••••••• (' + t('salva') + ')' : '', oninput: (e) => { x.api_key = e.target.value; } }))),
      h('div', { class: 'grid2' }, field(t('Modelo'), h('input', { value: x.model, oninput: (e) => { x.model = e.target.value.trim(); } })), extra(x)));
  };
  return h('div', null,
    h('p', { class: 'muted', style: { marginTop: 0 } }, t('Por padrão a voz usa o navegador (reconhecimento e síntese), sem custo e em vários idiomas. Para vozes de modelos — nuvem ou 100% locais (Whisper, Kokoro, Piper… atrás de uma API compatível com OpenAI) — configure um servidor abaixo.')),
    block('stt', t('Reconhecimento de fala (STT)'), (x) => field(t('Idioma (vazio/auto = detectar)'), h('input', { value: x.lang, oninput: (e) => { x.lang = e.target.value.trim() || 'auto'; } }))),
    block('tts', t('Síntese de voz (TTS)'), (x) => field(t('Voz padrão'), h('input', { value: x.voice, placeholder: 'alloy', oninput: (e) => { x.voice = e.target.value; } }))),
    h('div', { class: 'row', style: { justifyContent: 'flex-end' } }, h('button', { class: 'btn primary', onclick: async () => {
      const clean = (x) => { const o = Object.assign({}, x); delete o.api_key_set; if (!o.api_key) delete o.api_key; return o; };
      await saveSettings({ voice: { stt: clean(v.stt), tts: clean(v.tts) } }); await refreshState(); toast(t('Salvo'), 'ok'); } }, icon('check', 15), t('Salvar'))));
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
      h('div', { class: 'grid2' },
        field(t('Tamanho da interface'), seg([[90, '90%'], [100, '100%'], [110, '110%'], [125, '125%'], [150, '150%']], U().scale, (v) => save({ scale: v })), t('Aumenta ou diminui tudo; útil em telas grandes ou pequenas.')),
        field(t('Densidade'), seg([['comfortable', t('Confortável')], ['compact', t('Compacta')]], U().density, (v) => save({ density: v })), t('Compacta mostra mais conteúdo na tela.'))),
      h('div', { class: 'grid2' },
        field(t('Fonte'), seg([['system', t('Sistema')], ['serif', t('Serifada')], ['mono', t('Monoespaçada')]], U().font, (v) => save({ font: v })))),
      field(t('Animações'), select([['auto', t('Automático (segue o sistema)')], ['reduce', t('Reduzir animações')], ['full', t('Sempre animar')]], U().motion, (v) => save({ motion: v })), t('“Reduzir” desliga transições e animações — bom para quem sente enjoo com movimento ou usa um computador mais fraco.'))),
    card(t('Idioma'),
      field(t('Idioma da interface'), select([['auto', t('Automático (navegador)')], ['pt-BR', 'Português (Brasil)'], ['en', 'English']], state.settings.language, async (v) => { await saveSettings({ language: v }); location.reload(); }),
        t('Os textos do terminal (flow, flow update, instaladores) seguem o idioma do computador; para forçar um, use OPENFLOW_LANG=pt ou OPENFLOW_LANG=en.'))),
    card(t('Padrões da aparência'),
      h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Volta o tema, as cores e o conforto de leitura ao original. Suas chaves, avatares e projetos não mudam.')),
      h('div', { class: 'row' }, h('button', { class: 'btn sm', onclick: () => window.OPENFLOW_WELCOME && window.OPENFLOW_WELCOME() }, t('Rever as boas-vindas')), h('span', { class: 'grow' }),
        h('button', { class: 'btn sm danger', onclick: async () => { if (await confirmDialog(t('Voltar a aparência e as preferências de uso ao padrão? Suas chaves, avatares e projetos não mudam.'), true, t('Restaurar'))) { await api('/api/settings/reset', { method: 'POST', body: { section: 'ui' } }); await refreshState(); location.reload(); } } }, t('Restaurar padrões da aparência')))));
}

async function projectTab() {
  let tpls = [];
  try { tpls = (await api('/api/project-templates')).templates || []; } catch (e) { /* sem a lista, só o padrão */ }
  const cv = JSON.parse(JSON.stringify(state.settings.canvas || { template: 'text_image', agents: 1, effort: 'high' }));
  const opts = (tpls.length ? tpls : [{ id: 'text_image', label: 'Texto → Imagem' }]).map((x) => [x.id, t(x.label)]);
  return h('div', null,
    cfgCard(t('Novos projetos'), field(t('Modelo inicial'), select(opts, cv.template, (v) => { cv.template = v; }), t('O modelo que vem marcado ao criar um projeto novo. Os provedores de imagem, vídeo, som e voz ficam em Mídia.'))),
    teamCard(cv, 'cv', t('Vale para os nós de texto com IA (Texto IA, Refinar texto e a descrição de estilo): o esforço pede o raciocínio ao modelo e, com 4 ou mais agentes, cada um escreve notas que o redator final usa.')),
    saveRow(() => saveSettings({ canvas: cv })));
}

async function performance() {
  const pf = Object.assign({ mode: 'auto', idle_unload_min: 10 }, state.settings.performance || {});
  const nat = state.native || {};
  const hw = state.hardware;
  const cmd = (label, text) => h('div', { class: 'field' }, h('label', { class: 'f' }, label), h('div', { class: 'codebox' }, h('span', null, text), h('button', { class: 'btn sm ghost', onclick: () => { navigator.clipboard.writeText(text).then(() => toast(t('Copiado'))); } }, icon('copy', 13))));
  return h('div', null,
    cfgCard(t('Desempenho'),
      h('div', { class: 'grid2' },
        field(t('Modo'), select([['auto', t('Automático (conforme o hardware)')], ['light', t('Leve — menos RAM/VRAM')], ['balanced', t('Equilibrado')], ['max', t('Máximo')]], pf.mode, async (v) => { pf.mode = v; await saveSettings({ performance: pf }); toast(t('Salvo'), 'ok'); }),
          t('Leve: limita a janela de contexto, comprime o cache de atenção, descarrega modelos ociosos e usa menos memória de vídeo nos modelos de imagem/vídeo.')),
        field(t('Descarregar modelos ociosos após (min)'), h('input', { type: 'number', min: 0, max: 1440, value: pf.idle_unload_min, onchange: async (e) => { pf.idle_unload_min = Math.max(0, parseInt(e.target.value || '0', 10)); await saveSettings({ performance: pf }); toast(t('Salvo'), 'ok'); } }), t('0 = nunca. No modo leve o limite é de até 3 min.'))),
      h('p', { class: 'muted small', style: { marginBottom: 0 } }, t('Seu hardware: {t}', { t: hw.tier }) + ' · ' + hw.cpus + ' CPU · ' + (hw.ram_gb ? hw.ram_gb + ' GB RAM' : '—') + ' · ' + (hw.gpu || t('não detectada (NVIDIA)')))),
    cfgCard(t('Núcleo Rust'),
      h('dl', { class: 'kv', style: { margin: 0 } }, h('dt', null, t('Núcleo Rust')), h('dd', null, nat.active ? h('span', { class: 'chip on' }, t('ativo')) : h('span', { class: 'muted' }, t('inativo — usando Python puro'))),
        h('dt', null, 'Rust (cargo)'), h('dd', null, nat.cargo ? t('encontrado') : t('não encontrado (opcional)')),
        h('dt', null, t('Carga de modelos locais')), h('dd', { id: 'nat-models' }, nat.models ? h('span', { class: 'chip on' }, t('otimizada')) : h('span', { class: 'muted' }, t('padrão (recompile o núcleo: flow native setup)'))),
        h('dt', null, t('Agentes, armazenamento e memória')), h('dd', { id: 'nat-ops' }, nat.ops ? h('span', { class: 'chip on' }, t('otimizados')) : h('span', { class: 'muted' }, t('padrão (atualize o núcleo: flow native setup)'))),
        h('dt', null, t('Processador')), h('dd', null, (nat.cores ? t('{p} núcleos físicos · {l} threads', { p: nat.cores[0], l: nat.cores[1] }) : '—') + ((nat.features || []).length ? ' · ' + nat.features.join(' ').toUpperCase() : '')),
        nat.last && nat.last.llm ? h('dt', null, t('Último modelo de texto')) : null,
        nat.last && nat.last.llm ? h('dd', { id: 'nat-llm' }, nat.last.llm.model + ' · ' + t('contexto {c}', { c: nat.last.llm.n_ctx }) + ' · ' + (nat.last.llm.n_gpu_layers === -1 ? t('tudo na GPU') : nat.last.llm.n_gpu_layers > 0 ? t('{n} camadas na GPU', { n: nat.last.llm.n_gpu_layers }) : t('na CPU')) + ' · ' + t('{n} threads', { n: nat.last.llm.n_threads }) + (nat.last.llm.kv_q8 ? ' · ' + t('cache em 8 bits') : '')) : null,
        nat.last && nat.last.media ? h('dt', null, t('Último modelo de mídia')) : null,
        nat.last && nat.last.media ? h('dd', { id: 'nat-media' }, nat.last.media.model + ' · ' + ({ gpu: t('tudo na GPU'), model_offload: t('descarga do modelo'), sequential_offload: t('descarga sequencial (pouca VRAM)'), cpu: t('na CPU') }[nat.last.media.strategy] || '—')) : null),
      h('p', { class: 'muted small' }, t('O núcleo Rust é parte do OpenFlow: faz a síntese de áudio do OpenFlow, lê o cabeçalho dos modelos locais, escolhe contexto (até 1M de tokens), camadas na GPU e threads pela memória livre, agenda vários agentes locais, procura arquivos duplicados e devolve memória ao sistema. Os instaladores já o trazem; pelo terminal o OpenFlow baixa a biblioteca pronta da Release (sem compilador). Se ele estiver inativo, o OpenFlow funciona em Python, só mais devagar. Para ativar agora, rode no terminal:')),
      cmd(t('Ativar/atualizar o núcleo Rust (baixa a biblioteca pronta)'), 'flow native setup')));
}

const CAPS = [['image', 'Imagem'], ['video', 'Vídeo'], ['sound', 'Som e música'], ['voice', 'Voz (texto → fala)'], ['stt', 'Transcrição (fala → texto)']];

async function media() {
  let data = await api('/api/media/providers');
  const container = h('div');
  const paint = () => container.replaceChildren(defaults(), h('div', null, data.providers.filter((p) => p.id !== 'demo').map(card)), demoCard());

  const reload = async () => { data = await api('/api/media/providers'); await refreshState(); paint(); };
  function defaults() {
    return h('div', { class: 'card', style: { marginBottom: '16px' } }, h('h3', null, t('Modelo padrão de cada tipo de mídia')),
      h('p', { class: 'muted small', style: { marginTop: 0 } }, t('Cada nó do OpenFlow pode escolher outro provedor. Aqui fica o padrão do projeto. “Demo” funciona offline, sem IA, para testar os fluxos.')),
      h('div', { class: 'grid2' }, CAPS.map(([cap, label]) => field(t(label), select(data.providers.filter((p) => p.caps.includes(cap)).map((p) => [p.id, t(p.label) + (p.needs_key && !p.has_key ? ' · ' + t('sem chave') : '')]), data.active[cap] || 'demo',
        async (v) => { await saveSettings({ media: { active: { [cap]: v } } }); data.active[cap] = v; toast(t('Salvo'), 'ok'); })))));
  }
  function demoCard() {
    const d = data.providers.find((p) => p.id === 'demo');
    return h('div', { class: 'card', style: { marginTop: '16px' } }, h('h3', null, t(d.label)), h('p', { class: 'muted small', style: { margin: 0 } }, t(d.hint)));
  }
  function card(p) {
    const draft = { key: '', url: p.base_url === p.default_url ? '' : p.base_url, models: Object.assign({}, p.models) };
    const configured = (!p.needs_key || p.has_key) && (p.id !== 'custom' || p.base_url);
    const res = h('div', { class: 'res' });
    const inUse = CAPS.filter(([cap]) => data.active[cap] === p.id).map(([, l]) => t(l));
    const body = h('div', { class: 'bd' });
    const inputs = [];
    if (p.needs_key) inputs.push(field(t('Chave de API'), h('div', { class: 'row nw' },
      h('input', { type: 'password', autocomplete: 'off', placeholder: p.has_key ? '•••••••• (' + t('salva') + ')' : 'sk-…', oninput: (e) => { draft.key = e.target.value; } }),
      p.has_key ? h('button', { class: 'btn sm danger', onclick: async () => { await saveSettings({ providers: { [p.id]: { api_key: null } } }); toast(t('Chave removida')); reload(); } }, t('Remover')) : null),
      p.docs ? h('a', { href: p.docs, target: '_blank', rel: 'noopener', class: 'muted' }, t('Obter chave →')) : null));
    if (p.local || p.id === 'custom' || p.default_url) {
      if (p.id !== 'local_hf' && p.id !== 'voice_settings') inputs.push(field(t('Endereço do servidor'), h('input', { value: draft.url, placeholder: p.default_url || 'http://127.0.0.1:8000/v1', oninput: (e) => { draft.url = e.target.value.trim(); } })));
    }
    const listId = 'mm-' + p.id;
    inputs.push(h('datalist', { id: listId }));
    const modelCaps = CAPS.filter(([cap]) => p.caps.includes(cap) && p.id !== 'voice_settings' && p.id !== 'a1111');
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
      const patch = { media: { models: { [p.id]: draft.models }, urls: { [p.id]: draft.url } } };
      if (draft.key) patch.providers = { [p.id]: { api_key: draft.key } };
      await saveSettings(patch); toast(t('Salvo'), 'ok'); reload();
    };
    inputs.push(h('div', { class: 'row', style: { marginTop: '8px' } }, h('button', { class: 'btn sm primary', onclick: save }, t('Salvar')), h('button', { class: 'btn sm', onclick: async () => { await save(); test(); } }, t('Salvar e testar')),
      h('span', { class: 'dim small' }, t('Use “Salvar e testar” para conferir a conexão.'))), res);
    body.replaceChildren(...inputs);
    const cardEl = h('div', { class: 'prov' + (inUse.length ? ' open' : '') });
    cardEl.append(h('div', { class: 'hd', onclick: () => cardEl.classList.toggle('open') },
      h('span', { class: 'dot', style: { width: '8px', height: '8px', borderRadius: '50%', background: configured ? 'var(--ok)' : 'var(--dim)' } }),
      h('span', { class: 'nm' }, t(p.label)), p.local ? h('span', { class: 'badge' }, t('local')) : null,
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
            h('div', { class: 'dim small' }, t(PREC_HINT[o.id]))),
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
        catch (e) { area.replaceChildren(); return toast(e.message, 'err'); }
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
        if (!vs.length) { quants.replaceChildren(h('div', { class: 'small dim' }, t('Não há versões menores deste modelo na Hugging Face. Para modelos de texto, use as versões GGUF em Modelos locais.'))); return; }
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
