// Casca do app: paleta de comandos, atalhos de teclado e boas-vindas. Recebe do main.js o que precisa (evita dependência circular).
import { api } from './api.js';
import { accentSwatches, themeCards } from './appearance.js';
import { t } from './i18n.js';
import { openPalette } from './palette.js';
import { ui } from './prefs.js';
import { download, h, modal, toast } from './ui.js';

export function installShell(app) {
  const { state, NAV, go, saveSettings, renderSide, openProject } = app;
  const typing = (e) => { const el = e.target; return el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)); };

  function toggleSidebar() { localStorage.setItem('openflow.side', localStorage.getItem('openflow.side') === '1' ? '0' : '1'); renderSide(); }
  async function toggleTheme() {
    const cur = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
    await saveSettings({ ui: { theme: cur === 'light' ? 'dark' : 'light' } });
  }
  async function exportSettings() {
    const r = await fetch('/api/settings/export');
    download('openflow-configuracoes.json', await r.text());
    toast(t('Configurações exportadas (sem chaves de API).'), 'ok');
  }
  function newProject() { go('projects', { create: true }); }

  function shortcutsHelp() {
    const rows = [['Ctrl/⌘ + K', t('Abrir a paleta de comandos')], ['Alt + 1 … 3', t('Ir para cada tela da barra lateral')], ['Alt + N', t('Novo projeto')], ['/', t('Pesquisar nos projetos')], ['Alt + B', t('Recolher/expandir a barra lateral')], ['Alt + T', t('Alternar tema claro/escuro')],
      ['?', t('Mostrar esta ajuda')], ['Esc', t('Fechar janelas e a paleta')]];
    return modal(t('Atalhos de teclado'), h('dl', { class: 'shortcuts' }, rows.flatMap(([k, d]) => [h('dt', null, h('span', { class: 'kbd' }, k)), h('dd', null, d)])), [{ label: t('Fechar'), value: null, cls: 'primary' }]);
  }

  const host = {
    items() {
      const nav = NAV.map(([id, label, ic], i) => ({ group: t('Ir para'), label: t(label), icon: ic, keys: 'Alt+' + (i + 1), rank: 1, run: () => { state.ctx = {}; location.hash = '#/' + id; } }));
      const actions = [
        { group: t('Ações'), label: t('Novo projeto'), icon: 'plus', keys: 'Alt+N', run: newProject },
        { group: t('Ações'), label: t('Alternar tema claro/escuro'), icon: 'panel', keys: 'Alt+T', run: toggleTheme },
        { group: t('Ações'), label: t('Recolher/expandir a barra lateral'), icon: 'panel', keys: 'Alt+B', run: toggleSidebar },
        { group: t('Ações'), label: t('Ver atalhos de teclado'), icon: 'chev', keys: '?', run: shortcutsHelp },
        { group: t('Ações'), label: t('Exportar configurações (sem chaves de API)'), icon: 'download', run: exportSettings },
        { group: t('Ações'), label: t('Recarregar a página'), icon: 'refresh', run: () => location.reload() },
      ];
      return nav.concat(actions);
    },
    dataItems(projects) {
      return (projects || []).map((p) => ({ group: t('Projetos'), label: p.name, hint: t('{n} nós · {m} arquivos', { n: p.nodes, m: p.assets }), icon: 'canvas', run: () => openProject(p.id) }));
    },
  };
  const open = () => openPalette(host);

  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') { e.preventDefault(); open(); return; }  // a paleta sempre abre
    if (ui().shortcuts === false || document.querySelector('.modal-bg,.palette-bg')) return;
    if (e.altKey && !e.ctrlKey && !e.metaKey) {
      const m = /^Digit([1-9])$/.exec(e.code);
      if (m && NAV[Number(m[1]) - 1]) { e.preventDefault(); state.ctx = {}; location.hash = '#/' + NAV[Number(m[1]) - 1][0]; }
      else if (e.code === 'KeyB') { e.preventDefault(); toggleSidebar(); }
      else if (e.code === 'KeyT') { e.preventDefault(); toggleTheme(); }
      else if (e.code === 'KeyN') { e.preventDefault(); newProject(); }
      return;
    }
    if (typing(e) || e.ctrlKey || e.metaKey) return;
    if (e.key === '?') { e.preventDefault(); shortcutsHelp(); }
    else if (e.key === '/') { const q = document.getElementById('pj-search'); if (q) { e.preventDefault(); q.focus(); q.select(); } }   // «/» pesquisa nos projetos (como em muitos sites)
  });
  return { openPalette: open, shortcutsHelp, toggleSidebar, toggleTheme, exportSettings };
}

// Boas-vindas: só para quem abre o OpenFlow pela primeira vez (instalação nova, sem nenhum projeto). Quem já usa nunca vê.
export async function maybeWelcome(app, force = false) {
  const { state, saveSettings, go, renderSide } = app;
  if (!force) {
    if (ui().welcome_done) return;
    const projects = await api('/api/projects').catch(() => []);
    if (projects.length) { await saveSettings({ ui: { welcome_done: true } }); return; }
  }
  const save = (patch) => saveSettings({ ui: patch });
  const demo = state.settings.active.generation === 'demo';
  const ai = !demo
    ? h('p', { class: 'muted small', style: { margin: 0 } }, '✦ ' + t('IA de texto pronta: {n}', { n: (state.presets.find((p) => p.id === state.settings.active.generation) || { label: state.settings.active.generation }).label }))
    : h('div', { class: 'errbox', style: { margin: 0, whiteSpace: 'normal' } }, t('Nenhuma IA configurada: o OpenFlow funciona em modo Demo (resultados simples, sem inteligência). Instale modelos na tela Modelos ou configure um provedor para gerar imagens, vídeos, sons e vozes de verdade.'));
  const langSel = h('select', { 'aria-label': t('Idioma') }, [['auto', t('Automático (navegador)')], ['pt-BR', 'Português (Brasil)'], ['en', 'English']].map(([v, l]) => h('option', { value: v, selected: v === state.settings.language }, l)));
  langSel.addEventListener('change', async () => { await saveSettings({ language: langSel.value }); location.reload(); });
  const body = h('div', null,
    h('p', { class: 'muted', style: { marginTop: 0 } }, t('Escolha como quer ver o OpenFlow. Dá para mudar tudo depois em Configurações → Aparência.')),
    h('label', { class: 'f' }, t('Tema')), themeCards(ui().theme, (v) => save({ theme: v })),
    h('label', { class: 'f', style: { marginTop: '14px' } }, t('Cor de destaque')), accentSwatches(ui().accent, (v) => save({ accent: v })),
    h('label', { class: 'f', style: { marginTop: '14px' } }, t('Idioma')), langSel,
    h('div', { style: { marginTop: '16px' } }, ai),
    h('p', { class: 'dim small', style: { marginBottom: 0 } }, t('Dica: aperte Ctrl+K a qualquer momento para buscar telas, projetos e ações.')));
  const choice = await modal(t('Bem-vindo ao OpenFlow'), body, [{ label: demo ? t('Explorar no Demo') : t('Começar'), value: 'go' }, ...(demo ? [{ label: t('Instalar modelos'), value: 'models', cls: 'primary' }] : [])]);
  await saveSettings({ ui: { welcome_done: true } });
  renderSide();
  if (choice === 'models') go('models');
}
