// v0.88 — contraste de cores (WCAG AA, 4,5:1): o texto «apagado» (--dim) em cada tema e o texto sobre a cor de destaque escolhida (cada amostra de Aparência).
const { run } = require('./_common.js');
run('contrast_v088', async ({ open, check }) => {
  const page = await open({ width: 1300, height: 900 });
  await page.evaluate(() => { location.hash = '#/projects'; }); await page.waitForTimeout(800);
  const r = await page.evaluate(() => {
    const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    const rgb = (s) => { s = s.trim(); if (s[0] === '#') { if (s.length === 4) s = '#' + s[1] + s[1] + s[2] + s[2] + s[3] + s[3]; const n = parseInt(s.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; } return s.match(/\d+/g).slice(0, 3).map(Number); };
    const L = (s) => { const [r, g, b] = rgb(s).map(lin); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const cr = (a, b) => { const x = L(a), y = L(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    const root = document.documentElement, out = { dim: {}, accent: {} };
    const css = (v) => getComputedStyle(root).getPropertyValue(v).trim();
    for (const th of ['dark', 'light']) {
      root.dataset.theme = th;
      out.dim[th] = ['--bg', '--bg1', '--bg2'].map((bg) => +cr(css('--dim'), css(bg)).toFixed(2));
    }
    root.dataset.theme = 'dark';
    for (const ac of ['#4f8cff', '#8b5cf6', '#22c55e', '#f59e0b', '#ec4899', '#ef4444']) {
      window.OPENFLOW_APPLY_UI({ accent: ac });
      out.accent[ac] = +cr(css('--accent'), css('--on-accent')).toFixed(2);
    }
    window.OPENFLOW_APPLY_UI({ accent: '' });
    return out;
  });
  for (const th of ['dark', 'light']) { check('dim-' + th + ':contraste-minimo-4.5', r.dim[th].every((v) => v >= 4.5)); if (!r.dim[th].every((v) => v >= 4.5)) console.error(th, JSON.stringify(r.dim[th])); }
  for (const [ac, v] of Object.entries(r.accent)) check('destaque-' + ac + ':texto-legivel', v >= 4.5);
});
