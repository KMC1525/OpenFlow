// v0.78 — acessibilidade: todo campo (caixa, lista, texto) das Configurações e dos nós do canvas tem um nome (rótulo ligado ao campo), e clicar no rótulo leva ao campo; botões só com ícone têm nome.
const { run } = require('./_common.js');
run('labels_v078', async ({ api, open, check }) => {
  const names = () => {
    const vis = (e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 && getComputedStyle(e).visibility !== 'hidden'; };
    const missing = [];
    document.querySelectorAll('input:not([type=hidden]):not([type=range]), select, textarea').forEach((e) => {
      if (!vis(e)) return;
      const lab = e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('placeholder') || (e.id && document.querySelector(`label[for="${e.id}"]`)) || e.closest('label');
      if (!lab) missing.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + ' ' + (e.parentElement ? e.parentElement.className : ''));
    });
    document.querySelectorAll('button').forEach((e) => { if (vis(e) && !(e.getAttribute('aria-label') || e.getAttribute('title') || (e.innerText || '').trim())) missing.push('botão sem nome ' + e.className); });
    return missing;
  };
  for (const lang of ['pt-BR', 'en']) {
    await api('/api/settings', { method: 'PUT', body: { language: lang } });
    const page = await open({ width: 1400, height: 900 });
    await page.evaluate(() => { location.hash = '#/settings'; }); await page.waitForSelector('.cfgtabs button', { timeout: 10000 });
    const tabs = await page.locator('.cfgtabs button').count();
    let all = [];
    for (let i = 0; i < tabs; i++) { await page.locator('.cfgtabs button').nth(i).click(); await page.waitForTimeout(350); all = all.concat(await page.evaluate(names)); }
    check(`${lang}:configuracoes-todos-os-campos-tem-nome`, all.length === 0);
    if (all.length) console.error(JSON.stringify(all.slice(0, 8)));
    // clicar no rótulo foca o campo
    await page.locator('.cfgtabs button').nth(4).click(); await page.waitForTimeout(350);
    const labelWorks = await page.evaluate(() => { const l = [...document.querySelectorAll('label.f')].find((x) => x.htmlFor && document.getElementById(x.htmlFor)); if (!l) return false; l.click(); return document.activeElement === document.getElementById(l.htmlFor) || document.getElementById(l.htmlFor).type === 'checkbox'; });
    check(`${lang}:clicar-no-rotulo-foca-o-campo`, labelWorks);
    const types = ['image', 'video', 'voice', 'dub', 'sound', 'music', 'sfx', 'img_watermark', 'img_resize', 'img_filter', 'vid_reframe', 'vid_audio', 'text_refine', 'lyrics', 'transcript', 'sub', 'style_prompt', 'char_sheet', 'comic_page', 'out_export'];
    const cv = await api('/api/projects', { method: 'POST', body: { name: 'Rótulos', template: 'blank' } });
    await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Rótulos', nodes: types.map((t, i) => ({ id: 'n' + i, type: t, x: 40 + (i % 5) * 470, y: 40 + Math.floor(i / 5) * 560, params: {} })), edges: [] } });
    await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node', { timeout: 15000 }); await page.waitForTimeout(1200);
    const bad = await page.evaluate(names);
    check(`${lang}:nos-todos-os-campos-tem-nome`, bad.length === 0);
    if (bad.length) console.error(JSON.stringify(bad.slice(0, 8)));
    await page.close();
  }
});
