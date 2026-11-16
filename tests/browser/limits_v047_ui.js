// v0.47 — no limite de nós do projeto (200) o editor avisa em vez de deixar o nó novo sumir ao salvar; apagar um nó libera o espaço.
const { run } = require('./_common.js');
run('limits_v047', async ({ api, open, check }) => {
  const page = await open({ width: 1500, height: 950 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Cheio', template: 'blank' } });
  const nodes = Array.from({ length: 200 }, (_, i) => ({ id: 'n' + i, type: 'text', x: (i % 20) * 40, y: Math.floor(i / 20) * 40, params: { text: 'x' } }));
  await api('/api/projects/' + cv.id, { method: 'PUT', body: { nodes, edges: [] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-pal .it', { timeout: 15000 }); await page.waitForTimeout(800);
  check('projeto-cheio-tem-200-nos', (await page.locator('.cv-node').count()) === 200);
  await page.locator('.cv-pal .it').first().click(); await page.waitForTimeout(500);
  check('limite:nao-cria-o-201', (await page.locator('.cv-node').count()) === 200);
  check('limite:avisa', /Limite de 200|Limit of 200/.test(await page.locator('body').innerText()));
  await page.waitForTimeout(1500);
  check('limite:servidor-continua-com-200', (await api('/api/projects/' + cv.id)).nodes.length === 200);
  // apagar um nó libera o espaço
  await page.locator('.cv-node').last().click({ position: { x: 20, y: 12 } }); await page.keyboard.press('Delete'); await page.waitForTimeout(400);
  await page.locator('.cv-pal .it').first().click(); await page.waitForTimeout(500);
  check('apagar-libera-o-espaco', (await page.locator('.cv-node').count()) === 200);
  await page.waitForTimeout(1500);
  check('salvou-o-novo-no', (await api('/api/projects/' + cv.id)).nodes.length === 200);
});
