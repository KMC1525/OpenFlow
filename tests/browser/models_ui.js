// Tela «Modelos»: recomendados (com o que vem junto), busca no Hugging Face (simulada) com a prévia dos arquivos de apoio, download automático junto do modelo e reparo do que falta.
const { run } = require('./_common.js');
run('models', async ({ api, open, check }) => {
  await api('/api/settings', { method: 'PUT', body: { hf: { auto_support: true } } });
  const page = await open({ width: 1400, height: 1000 });
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  const seen = { download: [], repair: [] };
  let downloaded = false, repaired = false;
  const FLUX = { name: 'flux-2-klein-4b-Q4_K_M.gguf', kind: 'image', size: 2500000000, parts: 1, quant: 'Q4_K_M', quality: 'good' };
  await page.route('**/api/hf/search*', (r) => json(r, { results: [{ id: 'acme/flux-2-klein-4b-GGUF', downloads: 1200, likes: 9 }] }));
  await page.route('**/api/hf/files*', (r) => json(r, { files: [{ name: 'flux-2-klein-4b-Q4_K_M.gguf', files: ['flux-2-klein-4b-Q4_K_M.gguf'], sizes: { 'flux-2-klein-4b-Q4_K_M.gguf': 2500000000 }, size: 2500000000, parts: 1, quant: 'Q4_K_M', bits: 4, quality: 'good', fits: true, recommended: true }],
    support: [{ role: 'vae', label: 'VAE do FLUX.2', size: 340000000 }, { role: 'text_encoder', label: 'Qwen3-4B', size: 2500000000 }] }));
  await page.route('**/api/hf/local*', (r) => json(r, { models: downloaded && r.request().url().includes('kind=image') ? [FLUX] : [], kinds: {} }));
  await page.route('**/api/models/support', (r) => json(r, { auto: true, models: downloaded ? [{ kind: 'image', name: FLUX.name, family: 'flux2-klein-4b', label: 'FLUX.2 klein (4B)',
    have: repaired ? [{ role: 'vae', name: 'flux2-vae.safetensors' }, { role: 'text_encoder', name: 'Qwen3-4B-Q4_K_M.gguf' }] : [{ role: 'vae', name: 'flux2-vae.safetensors' }], missing: repaired ? [] : [{ role: 'text_encoder', label: 'Qwen3-4B', approx_gb: 2.5 }], approx_gb: 2.5 }] : [] }));
  await page.route('**/api/hf/download', (r) => { seen.download.push(JSON.parse(r.request().postData())); downloaded = true; json(r, { job_id: 'j_dl' }); });
  await page.route('**/api/jobs/j_dl/events', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"start"}\n\ndata: {"type":"progress","done":50,"total":100}\n\ndata: {"type":"support","items":[{"role":"vae","label":"VAE","size":1},{"role":"text_encoder","label":"Qwen3","size":1}]}\n\ndata: {"type":"done","name":"flux-2-klein-4b-Q4_K_M.gguf","support":["flux2-vae.safetensors"],"support_failed":[{"label":"Qwen3-4B","error":"HTTP 404"}]}\n\ndata: {"type":"end","status":"done"}\n\n' }));
  await page.route('**/api/models/support/install', (r) => { seen.repair.push(JSON.parse(r.request().postData())); repaired = true; json(r, { job_id: 'j_fix' }); });
  await page.route('**/api/jobs/j_fix/events', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"start"}\n\ndata: {"type":"done","files":["Qwen3-4B-Q4_K_M.gguf"],"failed":[]}\n\ndata: {"type":"end","status":"done"}\n\n' }));

  await page.evaluate(() => { location.hash = '#/models'; }); await page.waitForSelector('.prerow', { timeout: 10000 });
  check('recomendados:dois-modelos', (await page.locator('.prerow').count()) === 2);
  const zimg = page.locator('.prerow', { hasText: 'Z-Image' });
  check('recomendados:imagem-mostra-o-que-vem-junto', (await zimg.innerText()).includes('VAE') && /text encoder/i.test(await zimg.innerText()));
  check('recomendados:botao-instalar', (await zimg.locator('.btn.primary').count()) === 1);

  // busca → arquivos: a prévia diz o que vem junto; a caixa liga/desliga
  await page.locator('.seg button', { hasText: /^Image$/ }).click();
  await page.fill('#md-q', 'flux'); await page.keyboard.press('Enter');
  await page.waitForSelector('button.li', { timeout: 8000 });
  await page.locator('button.li').first().click();
  await page.waitForSelector('.comes .chip', { timeout: 8000 });
  check('busca:previa-do-que-vem-junto', (await page.locator('.comes .chip').allInnerTexts()).some((t) => t.startsWith('VAE')) && (await page.locator('.comes .chip').allInnerTexts()).some((t) => /Text encoder/.test(t)));
  const box = page.locator('.cfg label:has-text("Also download") input, .cfg label:has-text("Baixar junto") input').first();
  check('busca:caixa-de-apoio-ligada-por-padrao', await box.isChecked());
  await box.uncheck(); await page.waitForTimeout(400);
  check('busca:desligar-salva-na-configuracao', (await api('/api/settings')).hf.auto_support === false);
  await box.check(); await page.waitForTimeout(400);
  check('busca:ligar-de-novo', (await api('/api/settings')).hf.auto_support === true);

  // baixar: o pedido leva support:true e a tela mostra o que veio e o que falhou
  await page.locator('label.quant').first().click();
  await page.locator('.cfg .btn.primary', { hasText: /Download/ }).click();
  await page.waitForSelector('.modal-bg', { timeout: 5000 });
  check('baixar:a-confirmacao-lista-o-que-vem-junto', /VAE/.test(await page.locator('.modal-bg').innerText()));
  await page.locator('.modal-bg .btn.primary').last().click();
  await page.waitForSelector('.mdrow', { timeout: 10000 });
  check('baixar:pedido-com-apoio-ligado', seen.download.length === 1 && seen.download[0].support === true && seen.download[0].kind === 'image' && seen.download[0].repo === 'acme/flux-2-klein-4b-GGUF');

  // instalados: o estado de cada arquivo de apoio e o reparo com um clique
  const row = page.locator('.mdrow').first();
  check('instalados:vae-ok-e-codificador-faltando', (await row.locator('.chip.on').allInnerTexts()).some((t) => t.includes('VAE')) && (await row.locator('.chip.warn').allInnerTexts()).some((t) => /missing/.test(t)));
  await page.locator('#md-support').click();
  await page.waitForFunction(() => !document.querySelector('#md-support'), null, { timeout: 10000 });
  check('reparo:pedido-para-o-tipo-certo', seen.repair.length === 1 && seen.repair[0].kind === 'image');
  check('reparo:tudo-ok-depois', (await page.locator('.mdrow .chip.warn').count()) === 0 && (await page.locator('.mdrow .chip.on').count()) >= 2);
});
