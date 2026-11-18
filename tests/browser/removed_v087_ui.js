// v0.87 — o nó Editor e o nó Modelo PyTorch/TensorFlow saíram: não estão na paleta e um projeto antigo que os tinha abre sem eles, avisando.
const { run } = require('./_common.js');
run('removed_v087', async ({ api, open, check }) => {
  await api('/api/settings', { method: 'PUT', body: { language: 'pt' } });
  const page = await open({ width: 1500, height: 950 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Antigo', template: 'blank' } });
  await api('/api/projects/' + cv.id, { method: 'PUT', body: { name: 'Antigo', nodes: [
    { id: 't', type: 'text', x: 40, y: 40, params: { text: 'oi' } }, { id: 'ed', type: 'editor', x: 400, y: 40, params: {} }, { id: 'm', type: 'ai_model', x: 400, y: 300, params: {} }], edges: [] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-pal .it', { timeout: 15000 }); await page.waitForTimeout(800);
  check('antigo:so-o-no-de-texto-ficou', (await page.locator('.cv-node').count()) === 1);
  check('antigo:avisa-dos-nos-que-saíram', /não existem mais/.test(await page.locator('#toasts').innerText()));
  check('paleta:sem-editor-nem-modelo-pytorch', (await page.locator('.cv-pal').innerText()).split('\n').every((l) => !/^(Editor|Modelo PyTorch\/TensorFlow)$/.test(l.trim())));
  await page.evaluate(() => { localStorage.setItem('openflow.lang', 'en'); });
  await api('/api/settings', { method: 'PUT', body: { language: 'en' } });
  await page.reload(); await page.waitForSelector('.cv-pal .it', { timeout: 15000 });
  check('paleta-en:sem-editor', !/\bEditor\b/.test((await page.locator('.cv-pal').innerText()).replace(/Editor do projeto/g, '')));
});
