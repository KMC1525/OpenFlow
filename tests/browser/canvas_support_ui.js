// v0.17.7 — erro de GGUF sem arquivos de apoio: o nó mostra o texto limpo e o botão «Baixar os arquivos de apoio» (download simulado).
const { run } = require('./_common.js');
run('canvas_support', async ({ api, open, check }) => {
  const page = await open({ width: 1400, height: 900 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Apoio', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Apoio', edges: [], nodes: [{ id: 'im', type: 'image', x: 20, y: 20, params: { prompt: 'x' } }] } });
  const MSG = 'O modelo qwen-image-2.1-Q4_K_M.gguf não carregou. Faltam os arquivos de apoio do Qwen-Image: VAE do Qwen-Image (≈ 5 GB). [[flow-support:qwen-image-2.1-Q4_K_M.gguf]]';
  await page.route(new RegExp(`/api/projects/${cv.id}$`), async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const r = await route.fetch(); const j = await r.json();
    j.nodes.forEach((n) => { if (n.id === 'im') n.result = { ...n.result, state: 'error', error: MSG }; });
    route.fulfill({ response: r, json: j });
  });
  let posted = null;
  await page.route('**/api/media/support/download', (r) => { posted = JSON.parse(r.request().postData()); r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ job_id: 'j_sup', files: ['VAE do Qwen-Image'], approx_gb: 0.3 }) }); });
  await page.route('**/api/jobs/j_sup/events', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"progress","done":5,"total":10}\n\ndata: {"type":"done","files":["x"]}\n\ndata: {"type":"end"}\n\n' }));
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node div.err', { timeout: 10000 });
  const txt = await page.locator('.cv-node div.err').innerText();
  check('erro-sem-o-marcador-interno', /Faltam os arquivos de apoio/.test(txt) && !/flow-support/.test(txt));
  check('botao-baixar-os-arquivos-de-apoio', (await page.locator('#sup-im').count()) === 1);
  if (await page.locator('#cv-dock:not(.min)').count()) await page.locator('#cv-dock-toggle').click();   // a caixa de prompt (v0.17.27) cobre o pé do canvas: minimiza para clicar no nó
  await page.locator('#sup-im').click(); await page.waitForTimeout(800);
  check('pede-o-download-do-modelo-certo', !!posted && posted.model === 'qwen-image-2.1-Q4_K_M.gguf');
  check('botao-some-quando-termina', (await page.locator('#sup-im').count()) === 0);
});
