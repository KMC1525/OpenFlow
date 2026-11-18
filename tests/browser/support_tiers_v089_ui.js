// v0.89 — faixas dos codificadores de texto e VAEs: o cartão na Biblioteca (lista, escolher faixa e modo, obter) e o campo «Faixa dos arquivos de apoio» no nó.
const { run } = require('./_common.js');
run('support_tiers_v089', async ({ api, open, check }) => {
  await api('/api/settings', { method: 'PUT', body: { language: 'pt', media: { active: { image: 'gguf_local' } } } });
  const page = await open({ width: 1400, height: 900 });
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  const posted = [];
  await page.route('**/api/models/support/files', (r) => json(r, { tiers: ['Q2', 'Q3', 'Q4', 'Q6', 'Q8'], files: [
    { kind: 'image', name: 'ae.safetensors', size: 335000000, key: 'vae_path', role: 'vae', role_label: 'VAE', quant: '', bits: 16, format: 'safetensors', tier: '', have: [], lower: ['Q2', 'Q3', 'Q4', 'Q6', 'Q8'] },
    { kind: 'image', name: 't5xxl_fp8_e4m3fn.safetensors', size: 4900000000, key: 't5xxl_path', role: 'text_encoder', role_label: 'Codificador de texto', quant: '', bits: 8, format: 'safetensors', tier: '', have: ['Q4'], lower: ['Q2', 'Q3', 'Q6'] },
    { kind: 'video', name: 'umt5-xxl-encoder-Q2_K.gguf', size: 2000000000, key: 't5xxl_path', role: 'text_encoder', role_label: 'Codificador de texto', quant: 'Q2_K', bits: 2, format: 'gguf', tier: 'Q2', have: ['Q2'], lower: [] }] }));
  await page.route('**/api/models/support/tier', (r) => { posted.push(JSON.parse(r.request().postData())); json(r, { job_id: 'j_sup' }); });
  await page.route('**/api/jobs/j_sup/events*', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"done","name":"ae-Q4_K.gguf","how":"create"}\n\n' }));
  await page.evaluate(() => { location.hash = '#/library'; }); await page.waitForSelector('#lib-tab-models', { timeout: 10000 });
  await page.locator('#lib-tab-models').click();
  await page.waitForFunction(() => document.querySelectorAll('#lib-support [data-support]').length === 3, null, { timeout: 10000 }).catch(() => {});
  const nRows = await page.locator('#lib-support [data-support]').count(); if (nRows !== 3) console.error('linhas:', nRows, await page.locator('#lib-support').count(), (await page.locator('body').innerText()).slice(0, 300));
  check('biblioteca:lista-os-tres-arquivos', nRows === 3);
  check('biblioteca:vae-oferece-as-cinco-faixas', (await page.locator('[data-support="ae.safetensors"] select').first().locator('option').count()) === 5);
  check('biblioteca:faixa-ja-instalada-aparece', (await page.locator('[data-support="t5xxl_fp8_e4m3fn.safetensors"] .chip.on').innerText()) === 'Q4');
  check('biblioteca:sem-faixa-menor-nao-tem-botao', (await page.locator('[data-support="umt5-xxl-encoder-Q2_K.gguf"] [data-act="support-tier"]').count()) === 0);
  const row = page.locator('[data-support="ae.safetensors"]');
  await row.locator('select').nth(0).selectOption('Q4'); await row.locator('select').nth(1).selectOption('create');
  await row.locator('[data-act="support-tier"]').click(); await page.waitForTimeout(600);
  check('biblioteca:pede-a-faixa-certa', posted.length === 1 && posted[0].kind === 'image' && posted[0].name === 'ae.safetensors' && posted[0].tier === 'Q4' && posted[0].how === 'create');
  check('biblioteca:avisa-quando-fica-pronta', /ae-Q4_K\.gguf/.test(await page.locator('#toasts').innerText()));
  // o nó
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Apoio', template: 'blank' } });
  await api('/api/projects/' + cv.id, { method: 'PUT', body: { name: 'Apoio', nodes: [{ id: 'n1', type: 'image', x: 40, y: 60, params: { provider: 'gguf_local' } }], edges: [] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node[data-id="n1"]', { timeout: 15000 }); await page.waitForTimeout(800);
  const sel = page.locator('.cv-node[data-id="n1"] div:has(> label.f:has-text("Faixa dos arquivos de apoio")) > select');
  check('no:tem-o-campo-faixa-dos-arquivos-de-apoio', (await sel.count()) === 1);
  await sel.selectOption('Q4'); await page.waitForTimeout(1800);
  const saved = (await api('/api/projects/' + cv.id)).nodes.find((n) => n.id === 'n1');
  check('no:guarda-em-extra-support-quant', saved.params.extra && saved.params.extra.support_quant === 'Q4');
});
