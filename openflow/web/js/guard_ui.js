// v0.49 — aviso da proteção do computador: quando o hardware passa do limite e o OpenFlow para tudo (ou quando o usuário aperta «Parar tudo agora»), uma faixa no topo diz o que aconteceu.
import { api } from './api.js';
import { t } from './i18n.js';
import { h } from './ui.js';

export function startGuardWatch() {
  let seen = null, timer = 0;
  const banner = h('div', { class: 'guard-banner hidden', id: 'guard-banner', role: 'alert', 'aria-live': 'assertive' });
  document.body.appendChild(banner);
  const show = (trip) => {
    const s = trip.stopped || {};
    banner.replaceChildren(h('b', null, t(trip.manual ? 'Tudo foi parado.' : 'O OpenFlow parou tudo para proteger o computador.')), ' ', trip.reason || '', ' ',
      t('Tarefas: {j} · processos: {p} · modelos descarregados: {m}.', { j: s.jobs || 0, p: s.processes || 0, m: s.models || 0 }),
      h('button', { class: 'btn sm', type: 'button', id: 'guard-ok', onclick: () => banner.classList.add('hidden') }, t('Entendi')));
    banner.classList.remove('hidden');
  };
  async function tick() {
    clearTimeout(timer);
    if (!document.hidden) {
      try {
        const g = await api('/api/guard');
        if (seen === null) seen = g.trips || 0;   // os disparos de antes de abrir a página não viram faixa
        else if ((g.trips || 0) > seen && g.last_trip) { seen = g.trips; show(g.last_trip); window.dispatchEvent(new CustomEvent('flow:downloads')); }
      } catch (e) { /* sem servidor agora: tenta de novo */ }
    }
    timer = setTimeout(tick, 2000);
  }
  tick();
  return () => clearTimeout(timer);
}
