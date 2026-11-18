// v0.87 — nós utilitários (Filtros, Redimensionar, Vídeo final…) mostram o ponto de estado e o botão «Executar este nó», como os nós de IA.
const { run } = require('./_common.js');
run('ext_run', async ({ api, open, check }) => {
  await api('/api/settings', { method: 'PUT', body: { language: 'pt' } });
  const page = await open({ width: 1500, height: 950 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Ext', template: 'blank' } });
  await api('/api/projects/' + cv.id, { method: 'PUT', body: { name: 'Ext', nodes: [
    { id: 'c', type: 'in_color', x: 40, y: 40, params: { color: '#ff0000', width: 64, height: 64 } }, { id: 'f', type: 'img_filter', x: 400, y: 40, params: { preset: 'bw' } }],
    edges: [{ id: 'e', from: 'c', to: 'f', port: 'image' }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node[data-id="f"]', { timeout: 15000 }); await page.waitForTimeout(800);
  check('ext:tem-ponto-de-estado', (await page.locator('.cv-node[data-id="f"] .st').count()) === 1);
  check('ext:desatualizado-no-inicio', (await page.locator('.cv-node[data-id="f"] .st.stale').count()) === 1);
  const btn = page.locator('.cv-node[data-id="f"] .hd button[title^="Executar"]');
  check('ext:tem-botao-executar', (await btn.count()) === 1);
  await btn.click(); await page.waitForTimeout(2500);
  check('ext:rodou-e-ficou-atualizado', (await page.locator('.cv-node[data-id="f"] .st.ok').count()) === 1 && (await page.locator('.cv-node[data-id="f"] img').count()) >= 1);
});
