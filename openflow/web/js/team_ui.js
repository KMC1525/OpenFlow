// Equipe de agentes de todas as seções: quantos agentes (1 · 2 · 4 · 8 · 12 · 16 · 20 · 24 · 28 · 32) e o esforço de raciocínio (Low … Omni, os mesmos níveis do Code). Ver openflow/team.py.
// `teamPicker` é o seletor compacto ao lado do botão de criar; `teamFields` são os dois campos das abas de Configuração.
import { api } from './api.js';
import { t } from './i18n.js';
import { h, icon } from './ui.js';

export const AGENT_COUNTS = [1, 2, 4, 8, 12, 16, 20, 24, 28, 32];
export const PEER_FROM = 20;   // a partir daqui os agentes também revisam os rascunhos uns dos outros (openflow/team.py)
export const peerCount = (n) => (n < PEER_FROM ? 0 : Math.min(8, Math.max(2, Math.floor(n / 4))));
export const EFFORTS = ['low', 'medium', 'high', 'extra', 'mega', 'max', 'ultra', 'omni'];
export const EFFORT_NAME = { low: 'Low', medium: 'Medium', high: 'High', extra: 'Extra', mega: 'Mega', max: 'Max', ultra: 'Ultra', omni: 'Omni' };

let cache = null;
// as opções vêm do servidor (as descrições dos níveis são as do Code); se ele não responde, valem as constantes acima
export async function teamOptions() {
  if (cache) return cache;
  try { cache = await api('/api/team'); } catch (e) { cache = { agents: AGENT_COUNTS, efforts: EFFORTS.map((id) => ({ id, hint: '' })) }; }
  return cache;
}
const hintOf = (opts, id) => ((opts.efforts || []).find((e) => e.id === id) || {}).hint || '';
export const agentsLabel = (n) => t('{n} agente(s)', { n });
export const agentsHint = (n) => (n >= PEER_FROM
  ? t('Equipe grande: {n} agentes rascunham em paralelo, {m} deles leem e melhoram os rascunhos dos colegas e um Sintetizador junta tudo (≈ {c} chamadas à IA por etapa).', { n, m: peerCount(n), c: n + peerCount(n) + 1 })
  : n > 1
    ? t('{n} agentes trabalham em paralelo em cada etapa e um Sintetizador junta o melhor de todos (≈ {c} chamadas à IA por etapa).', { n, c: n + 1 })
    : t('Um agente por etapa (o fluxo de sempre: planejar → fazer → conferir).'));

const norm = (v, list, d) => (list.includes(v) ? v : d);
const nearest = (n) => AGENT_COUNTS.reduce((b, c) => (Math.abs(c - n) < Math.abs(b - n) || (Math.abs(c - n) === Math.abs(b - n) && c > b) ? c : b), AGENT_COUNTS[0]);

// ---- seletor compacto: { el, get() → {agents, effort} }; `cfg` é o ajuste da seção (agents/effort) que vem marcado
export function teamPicker(cfg, onChange, o = {}) {
  const agentsKey = o.agentsKey || 'agents', effortKey = o.effortKey || 'effort';
  const v = { agents: nearest(parseInt((cfg || {})[agentsKey], 10) || 1), effort: norm((cfg || {})[effortKey], EFFORTS, o.defaultEffort || 'high') };
  const effort = h('select', { class: 'team-sel', id: (o.id || 'team') + '-effort', title: t('Nível de esforço'), 'aria-label': t('Nível de esforço') },
    EFFORTS.map((id) => h('option', { value: id, selected: id === v.effort }, EFFORT_NAME[id])));
  const agents = h('select', { class: 'team-sel', id: (o.id || 'team') + '-agents', title: t('Agentes em paralelo'), 'aria-label': t('Agentes em paralelo') },
    AGENT_COUNTS.map((n) => h('option', { value: n, selected: n === v.agents }, String(n))));
  // cada seletor tem a largura do texto escolhido (senão ficam com o espaço do item mais comprido e o pílula parece vazia)
  const fit = (sel) => { sel.style.width = (sel.selectedOptions[0].textContent.length * 0.8 + 1.2) + 'ch'; };
  const paintTitles = (opts) => { effort.title = t('Nível de esforço') + ' — ' + t(hintOf(opts, v.effort) || ''); agents.title = agentsHint(v.agents); };
  effort.addEventListener('change', () => { v.effort = effort.value; fit(effort); paintTitles(cache || {}); if (onChange) onChange({ ...v }); });
  agents.addEventListener('change', () => { v.agents = parseInt(agents.value, 10); fit(agents); paintTitles(cache || {}); if (onChange) onChange({ ...v }); });
  fit(effort); fit(agents);
  paintTitles({});
  teamOptions().then(paintTitles);
  const el = h('span', { class: 'tool team-pick' }, icon('layers', 15), effort, icon('characters', 14), agents);   // compacto: «High · 👥 4» cabe na mesma linha do Run
  return { el, get: () => ({ ...v }) };
}

// ---- campos das abas de Configuração: o esforço e os agentes de uma seção (grava em `cfg[agentsKey]` e `cfg[effortKey]`)
export function teamFields(cfg, o = {}) {
  const agentsKey = o.agentsKey || 'agents', effortKey = o.effortKey || 'effort';
  cfg[agentsKey] = nearest(parseInt(cfg[agentsKey], 10) || 1);
  cfg[effortKey] = norm(cfg[effortKey], EFFORTS, o.defaultEffort || 'high');
  const eHint = h('div', { class: 'hint' }), aHint = h('div', { class: 'hint' });
  const paint = () => { eHint.textContent = t(hintOf(cache || {}, cfg[effortKey]) || ''); aHint.textContent = agentsHint(cfg[agentsKey]); };
  const eSel = h('select', { id: (o.id || 'team') + '-cfg-effort' }, EFFORTS.map((id) => h('option', { value: id, selected: id === cfg[effortKey] }, EFFORT_NAME[id])));
  const aSel = h('select', { id: (o.id || 'team') + '-cfg-agents' }, AGENT_COUNTS.map((n) => h('option', { value: n, selected: n === cfg[agentsKey] }, agentsLabel(n))));
  eSel.addEventListener('change', () => { cfg[effortKey] = eSel.value; paint(); });
  aSel.addEventListener('change', () => { cfg[agentsKey] = parseInt(aSel.value, 10); paint(); });
  paint();
  teamOptions().then(paint);
  return h('div', { class: 'grid2 team-fields', id: (o.id || 'team') + '-fields' },
    h('div', { class: 'field' }, h('label', { class: 'f' }, o.effortLabel || t('Esforço de raciocínio')), eSel, eHint),
    h('div', { class: 'field' }, h('label', { class: 'f' }, o.agentsLabel || t('Agentes em paralelo')), aSel, aHint));
}
