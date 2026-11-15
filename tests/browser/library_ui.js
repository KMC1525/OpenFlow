// Tela «Biblioteca» (v0.23): abas Modelos / Arquivos gerados / Downloads; arquivos gerados com filtro e apagar; downloads em andamento com progresso e cancelar.
const { run } = require('./_common.js');
run('library', async ({ api, open, check }) => {
  await api('/api/settings', { method: 'PUT', body: { language: 'en' } });
  const page = await open({ width: 1300, height: 900 });
  const json = (route, body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  const F = (id, kind, name, extra = {}) => ({ id, kind, name, mime: kind + '/x', bytes: 2048, created: '2026-11-15T10:00:00Z', w: 64, h: 64, duration: 0, model: 'z-image-Q4_K_M.gguf', provider: 'gguf_local', generated: true, project: 'p1', project_name: 'Meu filme', url: '/api/projects/p1/assets/' + id + '.png', ...extra });
  let files = [F('as_1', 'image', 'gato.png'), F('as_2', 'video', 'cena.mp4', { url: '/x.mp4' })];
  const seen = { urls: [], deleted: [], cancelled: 0 };
  let running = true;
  const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
  await page.route('**/*.png', (r) => r.fulfill({ status: 200, contentType: 'image/png', body: PNG }));
  await page.route('**/x.mp4', (r) => r.fulfill({ status: 200, contentType: 'video/mp4', body: '' }));
  await page.route('**/api/library/files*', (r) => { seen.urls.push(r.request().url()); json(r, { files }); });
  await page.route('**/api/projects/p1/assets/as_1', (r) => { seen.deleted.push('as_1'); files = files.filter((f) => f.id !== 'as_1'); json(r, { ok: true }); });
  await page.route('**/api/library/downloads', (r) => json(r, { downloads: running
    ? [{ id: 'j_a', kind: 'download', label: 'Modelo', title: 'flux-Q4_K_M.gguf', repo: 'acme/flux', status: 'running', created: 1, done: 500, total: 1000, note: '', error: '' }]
    : [{ id: 'j_a', kind: 'download', label: 'Modelo', title: 'flux-Q4_K_M.gguf', repo: 'acme/flux', status: 'done', created: 1, done: 1000, total: 1000, note: '', error: '' }], running: running ? 1 : 0 }));
  await page.route('**/api/jobs/j_a/cancel', (r) => { seen.cancelled++; running = false; json(r, { ok: true }); });
  await page.route('**/api/hf/local*', (r) => json(r, { models: [{ name: 'flux-Q4_K_M.gguf', kind: 'image', size: 2500000000, parts: 1, quant: 'Q4_K_M', mtime: 1760000000 }], kinds: {} }));

  await page.evaluate(() => { location.hash = '#/library'; }); await page.waitForSelector('#lib-tab-models', { timeout: 10000 });
  check('titulo-biblioteca', (await page.locator('.page-h h1').innerText()) === 'Library');
  check('tres-abas', (await page.locator('[id^=lib-tab-]').count()) === 3 && (await page.locator('#side nav a').allInnerTexts()).includes('Library'));
  check('aba-modelos-mostra-recomendados', await page.waitForSelector('.prerow', { timeout: 8000 }).then(() => true).catch(() => false));
  check('modelos-tem-card-baixados', (await page.locator('h3', { hasText: 'Downloaded' }).count()) >= 1);

  await page.locator('#lib-tab-files').click(); await page.waitForSelector('.libfile', { timeout: 8000 });
  check('arquivos:dois-cards', (await page.locator('.libfile').count()) === 2);
  check('arquivos:pede-so-gerados', seen.urls.some((u) => u.includes('source=generated')));
  check('arquivos:mostra-projeto-e-modelo', (await page.locator('.libfile').first().innerText()).includes('Meu filme') && (await page.locator('.libfile').first().innerText()).includes('z-image'));
  await page.selectOption('#lib-kind', 'video'); await page.waitForTimeout(500);
  check('arquivos:filtro-de-tipo-vai-ao-servidor', seen.urls.some((u) => u.includes('kind=video')));
  await page.selectOption('#lib-kind', ''); await page.waitForTimeout(400);
  await page.locator('.libfile', { hasText: 'gato.png' }).locator('.danger').click();
  await page.locator('.modal .btn.primary, .modal .btn.danger, dialog .btn.primary, .confirm .btn.primary').last().click();
  await page.waitForFunction(() => document.querySelectorAll('.libfile').length === 1, null, { timeout: 8000 });
  check('arquivos:apagar-remove-do-projeto', seen.deleted.includes('as_1'));

  await page.locator('#lib-tab-downloads').click(); await page.waitForSelector('.dlrow[data-job="j_a"]', { timeout: 8000 });
  const row = await page.locator('.dlrow[data-job="j_a"]').innerText();
  check('downloads:mostra-progresso', row.includes('flux-Q4_K_M.gguf') && row.includes('50%'));
  check('downloads:lista-modelos-baixados', (await page.locator('#lib-done').innerText()).includes('flux-Q4_K_M.gguf'));
  await page.locator('.dlrow[data-job="j_a"] .btn', { hasText: 'Cancel' }).click();
  await page.waitForFunction(() => document.querySelector('#lib-recent .dlrow'), null, { timeout: 8000 });
  check('downloads:cancelar-chama-o-servidor', seen.cancelled === 1);

  // endereço antigo continua valendo
  await page.evaluate(() => { location.hash = '#/models'; }); await page.waitForSelector('#lib-tab-models', { timeout: 8000 });
  check('endereco-antigo-models-abre-a-biblioteca', true);
});
