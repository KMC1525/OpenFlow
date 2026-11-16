// v0.50 — fundo cinza-grafite, tamanho da interface de 50% a 200% e mais fontes (Configurações → Aparência).
const { run } = require('./_common.js');
run('design_v050', async ({ api, open, check }) => {
  const page = await open({ width: 1400, height: 950 });
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  check('fundo:nao-e-preto-puro', bg !== 'rgb(0, 0, 0)' && /rgb\(30, 31, 34\)/.test(bg));
  await page.evaluate(() => { location.hash = '#/settings'; }); await page.waitForSelector('.cfgtabs button', { timeout: 8000 });
  await page.locator('.cfgtabs button').nth(3).click(); await page.waitForSelector('#ui-scale', { timeout: 8000 });
  check('escala:intervalo-50-a-200', (await page.getAttribute('#ui-scale', 'min')) === '50' && (await page.getAttribute('#ui-scale', 'max')) === '200');
  await page.locator('button[data-scale="50"]').click(); await page.waitForTimeout(700);
  check('escala:50-salva', (await api('/api/settings')).ui.scale === 50);
  check('escala:50-aplica-no-html', (await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--z').trim())) === '0.5');
  check('escala:50-ainda-usavel', (await page.locator('.cfgtabs button').count()) >= 4 && (await page.locator('#ui-scale').isVisible()));
  await page.locator('button[data-scale="200"]').click(); await page.waitForTimeout(700);
  check('escala:200-salva', (await api('/api/settings')).ui.scale === 200 && (await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--z').trim())) === '2');
  await page.locator('button[data-scale="100"]').scrollIntoViewIfNeeded(); await page.locator('button[data-scale="100"]').click(); await page.waitForTimeout(700);
  check('escala:100-volta', (await api('/api/settings')).ui.scale === 100);
  // fontes
  check('fontes:varias-opcoes', (await page.locator('#ui-fonts .fontopt').count()) >= 8);
  await page.locator('.fontopt[data-font="rounded"]').click(); await page.waitForTimeout(500);
  check('fonte:rounded-salva-e-aplica', (await api('/api/settings')).ui.font === 'rounded' && (await page.evaluate(() => document.documentElement.dataset.font)) === 'rounded');
  await page.fill('#ui-font-custom', 'Fira Sans'); await page.locator('#ui-font-custom').dispatchEvent('change'); await page.waitForTimeout(600);
  const s = (await api('/api/settings')).ui;
  check('fonte:outra-fonte-salva', s.font === 'custom' && s.font_custom === 'Fira Sans');
  check('fonte:outra-fonte-no-css', (await page.evaluate(() => document.documentElement.style.getPropertyValue('--font-custom'))) === '"Fira Sans"');
  await page.locator('.fontopt[data-font="system"]').click(); await page.waitForTimeout(400);
  check('fonte:volta-ao-sistema', (await api('/api/settings')).ui.font === 'system');
});
