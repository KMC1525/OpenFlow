// v0.85 — acessibilidade achada com o axe-core (regras de nomes, títulos e rótulos; contraste fica de fora): o link do logotipo tem o texto visível no nome, o editor do projeto tem um título de página (h1), os títulos dos
// cartões de Configurações e das listas vazias são de nível 2 (a página só tem o h1) e o campo de cor tem nome.
const { run } = require('./_common.js');
run('a11y_v085', async ({ api, open, check }) => {
  for (const lang of ['pt-BR', 'en']) {
    await api('/api/settings', { method: 'PUT', body: { language: lang } });
    const page = await open({ width: 1400, height: 900 });
    await page.evaluate(() => { location.hash = '#/projects'; }); await page.waitForSelector('.brand', { timeout: 10000 }); await page.waitForTimeout(500);
    const brand = await page.evaluate(() => { const a = document.querySelector('.brand'); const visible = [...a.querySelectorAll('.word')].map((e) => e.textContent).join('').trim(); const c = a.cloneNode(true); c.querySelectorAll('[aria-hidden="true"]').forEach((e) => e.remove()); const name = (a.getAttribute('aria-label') || c.textContent || '').replace(/\s+/g, ' ').trim();; return { visible, name, logoHidden: a.querySelector('.logo').getAttribute('aria-hidden') === 'true' }; });
    check(lang + ':logotipo-o-nome-comeca-pelo-texto-visivel', brand.name.startsWith(brand.visible) && brand.name.length > brand.visible.length && brand.logoHidden);
    check(lang + ':projetos-tem-um-h1', (await page.locator('h1').count()) >= 1);
    const empty = page.locator('h3[aria-level="2"]');
    check(lang + ':lista-vazia-titulo-nivel-2', (await empty.count()) >= 1 || (await page.locator('.cv-card').count()) > 0);
    const cv = await api('/api/projects', { method: 'POST', body: { name: 'Acessível', template: 'blank' } });
    await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('#cv-h1', { state: 'attached', timeout: 15000 });
    check(lang + ':editor-tem-um-h1-so-para-leitor-de-tela', (await page.locator('#cv-h1').count()) === 1 && (await page.locator('#cv-h1').evaluate((e) => getComputedStyle(e).position === 'absolute' && e.getBoundingClientRect().width <= 2)));
    check(lang + ':paleta-titulos-nivel-2', (await page.locator('.cv-pal-list h4[aria-level="2"]').count()) >= 3);
    await page.evaluate(() => { location.hash = '#/settings'; }); await page.waitForSelector('.cfgtabs button', { timeout: 10000 });
    const tabs = await page.locator('.cfgtabs button').count();
    let heads = 0, bad = 0;
    for (let i = 0; i < tabs; i++) {
      await page.locator('.cfgtabs button').nth(i).click(); await page.waitForTimeout(300);
      const r = await page.evaluate(() => { const hs = [...document.querySelectorAll('.card h3')]; return { n: hs.length, bad: hs.filter((h) => h.getAttribute('aria-level') !== '2').length }; });
      heads += r.n; bad += r.bad;
    }
    check(lang + ':configuracoes-titulos-dos-cartoes-nivel-2', heads >= 6 && bad === 0);
    const color = await page.evaluate(() => { const i = document.querySelector('input[type=color]'); return i ? !!i.getAttribute('aria-label') : null; });
    check(lang + ':campo-de-cor-tem-nome', color !== false);
    await page.close();
  }
});
