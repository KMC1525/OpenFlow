// Biblioteca 2.0 (v0.27): pastas e subpastas, busca, mover (menu e arrastar), downloads; e a aba «Biblioteca» do canvas (arrastar arquivos para o fluxo).
const { run } = require('./_common.js');
run('library', async ({ api, open, check, base, expectError }) => {
  expectError(/409/);   // o nome de pasta repetido é recusado de propósito
  await api('/api/settings', { method: 'PUT', body: { language: 'en' } });
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64');
  const mk = async (name) => (await api('/api/projects', { method: 'POST', body: { name } }));
  const up = async (pid, name) => { const r = await fetch(`${base}/api/projects/${pid}/assets`, { method: 'POST', body: png, headers: { 'X-Filename': encodeURIComponent(name), 'Content-Type': 'image/png' } }); return r.json(); };
  const p1 = await mk('Filme'), p2 = await mk('Livro');
  const a1 = await up(p1.id, 'gato.png'), a2 = await up(p1.id, 'cachorro.png'), a3 = await up(p2.id, 'paisagem.png');
  const mkf = async (name, parent = '', scope = 'files') => api('/api/library/folders', { method: 'POST', body: { name, parent, scope } });
  const animais = await mkf('Animais'), pets = await mkf('Pets', animais.id);
  await api('/api/library/move', { method: 'POST', body: { items: [`file:${p1.id}/${a1.id}`], folder: pets.id } });

  const page = await open({ width: 1400, height: 900 });
  let running = true;
  await page.route('**/api/library/downloads', (r) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ downloads: running
    ? [{ id: 'j_a', kind: 'download', label: 'Modelo', title: 'flux-Q4_K_M.gguf', repo: 'acme/flux', status: 'running', created: 1, done: 500, total: 1000, speed: 100, eta: 5, note: '', error: '' }] : [], running: running ? 1 : 0 }) }));
  await page.route('**/api/jobs/j_a/cancel', (r) => { running = false; r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }); });
  await page.evaluate(() => { location.hash = '#/library'; }); await page.waitForSelector('#lib-tab-models', { timeout: 10000 });
  check('titulo-biblioteca', (await page.locator('.page-h h1').innerText()) === 'Library');
  check('secoes-na-lateral', (await page.locator('.lib-sec').count()) === 3);

  await page.locator('#lib-tab-files').click(); await page.waitForSelector('#lib-folders .lib-card.folder', { timeout: 8000 });
  check('raiz:mostra-a-pasta-e-os-arquivos-soltos', (await page.locator('#lib-folders .lib-card').count()) === 1 && (await page.locator('#lib-items .lib-card').count()) === 2);   // cachorro + paisagem; o gato está em Pets
  await page.locator('#lib-folders .lib-card', { hasText: 'Animais' }).click();
  await page.waitForSelector('.lib-crumbs b, .lib-crumbs .lib-crumb:nth-of-type(2)', { timeout: 5000 });
  check('entrar-na-pasta:mostra-a-subpasta', (await page.locator('#lib-folders .lib-card', { hasText: 'Pets' }).count()) === 1);
  check('entrar-na-pasta:caminho-no-topo', (await page.locator('.lib-crumbs').innerText()).includes('Animais'));
  await page.locator('#lib-folders .lib-card', { hasText: 'Pets' }).click(); await page.waitForSelector('#lib-items .lib-card[data-asset]', { timeout: 5000 });
  check('subpasta:tem-o-gato', (await page.locator('#lib-items').innerText()).includes('gato.png'));

  // busca em todas as pastas: acha pelo nome e diz onde está
  await page.fill('#lib-q', 'gato'); await page.waitForFunction(() => document.querySelector('#lib-items .lib-card .meta') && /Animais/.test(document.querySelector('#lib-items').innerText), null, { timeout: 8000 });
  check('busca:acha-o-arquivo-em-qualquer-pasta-e-mostra-o-caminho', (await page.locator('#lib-items').innerText()).includes('Animais / Pets'));
  await page.fill('#lib-q', 'pets'); await page.waitForSelector('#lib-folders .lib-card', { timeout: 8000 });
  check('busca:acha-pastas', (await page.locator('#lib-folders').innerText()).includes('Pets'));
  await page.fill('#lib-q', ''); await page.waitForTimeout(500);

  // nova pasta pela interface
  await page.locator('#lib-tab-files').click(); await page.waitForSelector('#lib-newfolder');
  await page.click('#lib-newfolder'); await page.fill('#lib-name', 'Paisagens'); await page.locator('.modal .btn.primary').click();
  await page.waitForSelector('#lib-folders .lib-card:has-text("Paisagens")', { timeout: 8000 });
  check('nova-pasta:criada-pela-interface', true);
  await page.click('#lib-newfolder'); await page.fill('#lib-name', 'paisagens'); await page.locator('.modal .btn.primary').click();
  await page.waitForFunction(() => /Já existe|already/.test(document.getElementById('toasts').innerText), null, { timeout: 5000 });
  check('nova-pasta:nome-repetido-e-recusado', true);

  // mover pelo menu (e pelo arrastar e soltar)
  await page.locator('#lib-items .lib-card', { hasText: 'paisagem.png' }).hover();
  await page.locator('#lib-items .lib-card', { hasText: 'paisagem.png' }).locator('.lib-menu .btn').click();
  await page.locator('.lib-pop:not(.hidden) button', { hasText: 'Move to' }).click();
  await page.locator('.lib-pick .lib-fold', { hasText: 'Paisagens' }).click(); await page.locator('.modal .btn.primary').click();
  await page.waitForFunction(() => !/paisagem\.png/.test(document.getElementById('lib-items') ? document.getElementById('lib-items').innerText : ''), null, { timeout: 8000 });
  const moved = await api('/api/library/items?scope=files&q=paisagem');
  check('mover:pelo-menu', moved.items.length === 1 && moved.items[0].path === 'Paisagens');
  await page.locator('#lib-items .lib-card', { hasText: 'cachorro.png' }).dragTo(page.locator('.lib-fold[data-folder="' + pets.id + '"]'));
  await page.waitForTimeout(800);
  const dd = await api('/api/library/items?scope=files&folder=' + pets.id);
  check('mover:arrastando-para-a-pasta-da-lateral', dd.items.map((i) => i.name).sort().join() === 'cachorro.png,gato.png');

  // excluir pasta: o conteúdo sobe, nada some
  await page.locator('#lib-folders .lib-card', { hasText: 'Paisagens' }).locator('.lib-menu .btn').click();
  await page.locator('.lib-pop:not(.hidden) button', { hasText: 'Delete folder' }).click(); await page.locator('.modal .btn.danger').click();
  await page.waitForFunction(() => !/Paisagens/.test(document.getElementById('lib-folders') ? document.getElementById('lib-folders').innerText : ''), null, { timeout: 8000 });
  const root = await api('/api/library/items?scope=files');
  check('excluir-pasta:arquivos-voltam-para-a-raiz', root.items.some((i) => i.name === 'paisagem.png'));

  // modelos: pastas de modelos são separadas; «Baixar mais modelos» abre o catálogo
  await page.locator('#lib-tab-models').click(); await page.waitForSelector('#lib-get', { timeout: 8000 });
  check('modelos:botao-baixar-mais', true);
  await page.click('#lib-get'); await page.waitForSelector('.prerow', { timeout: 10000 });
  check('modelos:catalogo-abre', (await page.locator('.prerow').count()) >= 1);

  // downloads
  await page.locator('#lib-tab-downloads').click(); await page.waitForSelector('.dlrow[data-job="j_a"]', { timeout: 8000 });
  check('downloads:progresso-e-velocidade', (await page.locator('.dlrow[data-job="j_a"]').innerText()).includes('50%'));

  // canvas: aba Biblioteca e arrastar para o fluxo
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, p2.id);
  await page.waitForSelector('.cv-surface', { timeout: 10000 });
  await page.evaluate(() => localStorage.setItem('openflow.cv.assets', '1'));
  await page.reload(); await page.waitForSelector('.cv-surface'); await page.waitForTimeout(500);
  if (!(await page.locator('#cv-atab-library').count())) await page.locator('button:has-text("Files")').first().click();
  await page.waitForSelector('#cv-atab-library', { timeout: 8000 });
  await page.click('#cv-atab-library'); await page.waitForSelector('#cv-lib-list .cv-lib-folder, #cv-lib-list .cv-asset', { timeout: 8000 });
  check('canvas:aba-biblioteca-lista-pastas', (await page.locator('#cv-lib-list .cv-lib-folder').count()) >= 1);
  await page.locator('#cv-lib-list .cv-lib-folder', { hasText: 'Animais' }).click();
  await page.locator('#cv-lib-list .cv-lib-folder', { hasText: 'Pets' }).click();
  await page.waitForSelector('#cv-lib-list .cv-asset', { timeout: 8000 });
  check('canvas:navega-nas-subpastas', (await page.locator('#cv-lib-list .cv-asset').count()) === 2);
  const before = await page.locator('.cv-node').count();
  await page.locator('#cv-lib-list .cv-asset', { hasText: 'gato.png' }).dragTo(page.locator('.cv-surface'), { targetPosition: { x: 300, y: 250 } });
  await page.waitForFunction((n) => document.querySelectorAll('.cv-node').length > n, before, { timeout: 8000 });
  check('canvas:soltar-cria-no-de-midia', (await page.locator('.cv-node').count()) === before + 1);
  let cv = await api('/api/projects/' + p2.id);
  for (let i = 0; i < 20 && !cv.nodes.some((n) => n.type === 'upload'); i++) { await page.waitForTimeout(400); cv = await api('/api/projects/' + p2.id); }   // o canvas grava sozinho, depois de uma pausa
  check('canvas:arquivo-foi-copiado-para-o-projeto', cv.assets.some((a) => a.name === 'gato.png') && cv.nodes.some((n) => n.type === 'upload' && n.params.files.length === 1));
  await page.fill('#cv-lib-q', 'paisagem'); await page.waitForFunction(() => document.querySelectorAll('#cv-lib-list .cv-asset').length === 1, null, { timeout: 8000 });
  check('canvas:busca-na-biblioteca', true);
});
