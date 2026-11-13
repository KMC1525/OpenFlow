// Todas as telas abrem sem erros no computador e no celular (inglês e português), com a navegação e os atalhos básicos.
const { run } = require('./_common.js');
run('smoke', async ({ api, open, check, browser, base }) => {
  const page = await open();
  await page.waitForSelector('.page-h h1', { timeout: 10000 });
  check('inicio:a-tela-inicial-e-a-lista-de-projetos', (await page.locator('.page-h h1').innerText()) === 'Projects' && (await page.locator('#pj-search').count()) === 1);
  check('titulo:openflow', (await page.title()).startsWith('OpenFlow'));
  check('barra:tres-telas', (await page.locator('#side nav a').allInnerTexts()).join('|') === 'Projects|Models|Settings');
  for (const [route, h1] of [['models', 'Models'], ['settings', 'Settings'], ['projects', 'Projects']]) {
    await page.evaluate((r) => { location.hash = '#/' + r; }, route); await page.waitForTimeout(500);
    check(`tela:${route}`, (await page.locator('.page-h h1').first().innerText()) === h1);
  }
  // configurações: todas as abas abrem
  await page.evaluate(() => { location.hash = '#/settings'; }); await page.waitForSelector('.cfgtabs button', { timeout: 8000 });
  const tabs = await page.locator('.cfgtabs button').count();
  let ok = tabs === 6;
  for (let i = 0; i < tabs; i++) { await page.locator('.cfgtabs button').nth(i).click(); await page.waitForTimeout(350); ok = ok && (await page.locator('.cfg .card, .cfg .prov').count()) > 0; }
  check('configuracoes:seis-abas-abrem', ok);
  // atalhos
  await page.evaluate(() => { location.hash = '#/projects'; }); await page.waitForSelector('#pj-search');
  await page.keyboard.press('/'); check('atalho:barra-foca-a-pesquisa', await page.evaluate(() => document.activeElement && document.activeElement.id === 'pj-search'));
  await page.keyboard.press('Escape'); await page.locator('body').click({ position: { x: 700, y: 600 } });
  await page.keyboard.press('Control+k'); await page.waitForSelector('.palette', { timeout: 3000 });
  check('atalho:ctrl-k-abre-a-paleta', (await page.locator('.palette-item').count()) >= 3);
  await page.keyboard.press('Escape');
  await page.keyboard.press('Alt+2'); await page.waitForTimeout(300);
  check('atalho:alt-2-vai-para-modelos', (await page.evaluate(() => location.hash)) === '#/models');
  await page.keyboard.press('Alt+1'); await page.waitForTimeout(300);
  check('atalho:alt-1-volta-aos-projetos', (await page.evaluate(() => location.hash)) === '#/projects');
  // português
  await api('/api/settings', { method: 'PUT', body: { language: 'pt-BR' } });
  await page.reload(); await page.waitForSelector('.page-h h1');
  check('idioma:portugues', (await page.locator('.page-h h1').innerText()) === 'Projetos' && (await page.locator('#side nav a').allInnerTexts()).join('|') === 'Projetos|Modelos|Configurações');
  // celular: sem rolagem lateral e com a busca à vista
  const phone = await open({ width: 390, height: 844 });
  await phone.waitForSelector('#pj-search', { timeout: 10000 });
  for (const r of ['projects', 'models', 'settings']) {
    await phone.evaluate((x) => { location.hash = '#/' + x; }, r); await phone.waitForTimeout(600);
    check(`celular:${r}-sem-rolagem-lateral`, await phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  }
  await api('/api/settings', { method: 'PUT', body: { language: 'auto' } });
});
