// Preferências de interface (settings.ui): leitura e aplicação na tela.
export const DEFAULT_UI = { theme: 'dark', accent: '', scale: 100, density: 'comfortable', motion: 'auto', font: 'system', shortcuts: true, welcome_done: false };

export const ui = () => Object.assign({}, DEFAULT_UI, window.OPENFLOW_UI || {});
export function applyUi(next) { const merged = Object.assign({}, DEFAULT_UI, next || {}); if (window.OPENFLOW_APPLY_UI) window.OPENFLOW_APPLY_UI(merged); else window.OPENFLOW_UI = merged; return merged; }
