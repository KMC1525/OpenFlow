// v0.88 — foco do teclado visível: o campo «Buscar nós» da paleta (outline:none sem substituto) agora mostra um sinal ao receber o foco.
const { run } = require('./_common.js');
run('focus_v088', async ({ api, open, check }) => {
  const page = await open({ width: 1400, height: 900 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Foco', template: 'blank' } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('#cv-pal-q', { timeout: 15000 });
  const shadow = () => page.evaluate(() => getComputedStyle(document.querySelector('.cv-pal-search')).boxShadow);
  check('paleta:sem-foco-sem-sinal', (await shadow()) === 'none');
  await page.locator('#cv-pal-q').focus(); await page.waitForTimeout(100);
  check('paleta:com-foco-mostra-sinal', (await shadow()) !== 'none');
  await page.locator('#cv-pal-q').blur(); await page.waitForTimeout(100);
  check('paleta:perder-o-foco-tira-o-sinal', (await shadow()) === 'none');
  await page.locator('.cv-top .nm').focus(); await page.waitForTimeout(100);
  check('nome-do-projeto:com-foco-borda-visivel', (await page.evaluate(() => getComputedStyle(document.querySelector('.cv-top .nm')).borderColor)) !== 'rgba(0, 0, 0, 0)');
});
