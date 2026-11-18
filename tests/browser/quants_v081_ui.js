// v0.81 — Q2, Q3, Q4, Q6 e Q8: a lista GGUF mostra as cinco faixas (as que o repositório não tem aparecem apagadas, com a saída: outros repositórios), os originais ganham as faixas na precisão (com a
// memória que usam), a Biblioteca cria uma faixa menor a partir de um arquivo baixado e o nó de imagem escolhe a faixa ao carregar (GGUF).
const { run } = require('./_common.js');
run('quants_v081', async ({ api, open, check }) => {
  await api('/api/settings', { method: 'PUT', body: { language: 'pt', media: { active: { image: 'gguf_local' } } } });
  const page = await open({ width: 1500, height: 950 });
  const json = (route, body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  const REPO = 'unsloth/Z-Image-Turbo-GGUF';
  const mk = (name, quant, bits, tier, size) => ({ name, quant, bits, quality: 'good', size, parts: 1, files: [name], sizes: { [name]: size }, fits: true, recommended: quant === 'Q4_K_M', tier });
  const tiers = [{ tier: 'Q2', has: false }, { tier: 'Q3', has: false }, { tier: 'Q4', has: true, quant: 'Q4_K_M', name: 'z-Q4_K_M.gguf', size: 3800000000, recommended: true }, { tier: 'Q6', has: false }, { tier: 'Q8', has: true, quant: 'Q8_0', name: 'z-Q8_0.gguf', size: 7000000000 }];
  const seen = { alts: 0, requant: [] };
  await page.route('**/api/media/hub/search*', (r) => { const fmt = new URL(r.request().url()).searchParams.get('format'); json(r, { results: [fmt === 'original' ? { id: 'acme/diffusers-model', downloads: 900, likes: 5, cap: 'image', format: 'original' } : { id: REPO, downloads: 900, likes: 5, cap: 'image', format: 'gguf' }], format: fmt, cap: 'image' }); });
  await page.route('**/api/hf/files*', (r) => json(r, { files: [mk('z-Q4_K_M.gguf', 'Q4_K_M', 4, 'Q4', 3800000000), mk('z-Q8_0.gguf', 'Q8_0', 8, 'Q8', 7000000000)], support: [], compat: null, tiers }));
  await page.route('**/api/hf/tiers*', (r) => { seen.alts++; json(r, { repo: REPO, tiers, alternatives: [{ repo: 'city96/z-image-gguf', downloads: 40, tiers: ['Q2', 'Q3', 'Q4'], missing_covered: ['Q2', 'Q3'] }] }); });
  await page.route('**/api/hf/local*', (r) => json(r, { models: [], kinds: {} }));
  await page.route('**/api/media/local/**', (r) => json(r, { options: [{ id: 'fp16', size: 8000000000, recommended: false, hint: '' }, { id: 'q4', size: 8000000000, memory: 2300000000, recommended: true, tier: 'Q4' }, { id: 'q2', size: 8000000000, memory: 1300000000, tier: 'Q2' }], variants: [], libs: true, models: {} }));
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Faixas', template: 'blank' } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('#hub-q', { timeout: 15000 });
  await page.locator('#hub-q').focus(); await page.waitForSelector('#hub-recs', { timeout: 8000 });
  await page.locator('.hub-rec[data-repo="' + REPO + '"] [data-act="rec-open"]').click();
  await page.waitForSelector('.tiers [data-tier="Q2"]', { timeout: 8000 });
  check('faixas:as-cinco-aparecem', (await page.locator('.tiers [data-tier]').count()) === 5);
  check('faixas:as-que-faltam-sao-marcadas', (await page.locator('.tiers [data-tier][data-has="0"]').count()) === 3 && (await page.locator('.tiers [data-tier="Q4"]').getAttribute('data-has')) === '1');
  check('faixas:diz-o-que-faltou-e-o-que-fazer', /Q2, Q3, Q6/.test(await page.locator('.tiers').innerText()) && /Criar faixa/.test(await page.locator('.tiers').innerText()));
  check('faixas:as-quantizacoes-do-arquivo-seguem-na-lista', (await page.locator('.hub-q[data-quant="Q8_0"]').count()) === 1);
  await page.locator('[data-act="tiers-alts"]').click(); await page.waitForSelector('.hub-q[data-alt="city96/z-image-gguf"]', { timeout: 8000 });
  check('outros-repositorios:busca-so-quando-pedido', seen.alts === 1);
  check('outros-repositorios:mostra-o-que-cada-um-tem', /Q2/.test(await page.locator('.hub-q[data-alt]').innerText()) && /Q3/.test(await page.locator('.hub-q[data-alt]').innerText()));
  // formato original: as faixas na precisão, com a memória
  await page.selectOption('#hub-fmt', 'original'); await page.waitForTimeout(200);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('flow:hub', { detail: { q: 'acme/diffusers-model', cap: 'image', fmt: 'original' } }))); await page.waitForTimeout(600);
  await page.waitForSelector('.hub-r[data-repo="acme/diffusers-model"]', { timeout: 8000 });
  if (!(await page.locator('.hub-q[data-quant="q4"]').count())) { await page.waitForTimeout(1200); if (!(await page.locator('.hub-q[data-quant="q4"]').count())) await page.locator('.hub-r[data-repo="acme/diffusers-model"]').first().click(); }   // a busca por evento já abre o repositório; se não abriu, abre
  await page.waitForSelector('.hub-q[data-quant="q4"]', { timeout: 8000 });
  check('original:faixa-q4-na-precisao', (await page.locator('.hub-q[data-quant="q2"]').count()) === 1);
  check('original:mostra-a-memoria-estimada', /Mem[oó]ria|Memory/.test(await page.locator('.hub-q[data-quant="q4"]').innerText()));
  check('original:faixa-tem-a-explicacao', /4 bits/.test(await page.locator('.hub-q[data-quant="q4"]').innerText()) && /2 bits/.test(await page.locator('.hub-q[data-quant="q2"]').innerText()));   // v0.84: o hub tinha uma cópia antiga dos textos, só com fp32/fp16/bf16: as faixas ficavam sem explicação
  // Biblioteca: criar uma faixa menor a partir de um arquivo baixado
  await page.route('**/api/library/items*', (r) => json(r, { folders: [], items: [{ key: 'model:image/z-Q8_0.gguf', scope: 'models', kind: 'image', name: 'z-Q8_0.gguf', size: 7000000000, quant: 'Q8_0', bits: 8, tier: 'Q8', parts: 1, mtime: 1 }], path: [], search: false }));
  await page.route('**/api/hf/requant', (r) => { seen.requant.push(JSON.parse(r.request().postData())); json(r, { job_id: 'j_q' }); });
  await page.route('**/api/jobs/j_q/events*', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"done","name":"z-Q4_K.gguf"}\n\n' }));
  await page.evaluate(() => { location.hash = '#/library'; }); await page.waitForSelector('#lib-tab-models', { timeout: 8000 });
  await page.locator('#lib-tab-models').click(); await page.waitForSelector('.lib-card.model[data-model="z-Q8_0.gguf"]', { timeout: 8000 });
  await page.locator('.lib-card.model .lib-menu .btn').click();
  const items = (await page.locator('.lib-pop:not(.hidden) button').allInnerTexts()).join('|');
  check('biblioteca:oferece-so-faixas-menores', /Q6/.test(items) && /Q4/.test(items) && /Q3/.test(items) && /Q2/.test(items) && !/Criar faixa Q8|Create tier Q8/.test(items));
  await page.locator('.lib-pop:not(.hidden) button', { hasText: 'Q4' }).click(); await page.waitForTimeout(800);
  check('biblioteca:criar-faixa-pede-o-arquivo-e-a-faixa', seen.requant.length === 1 && seen.requant[0].name === 'z-Q8_0.gguf' && seen.requant[0].tier === 'Q4' && seen.requant[0].kind === 'image');
  // nó de imagem com o provedor GGUF: campo «Quantização ao carregar» grava extra.quant
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Faixas', nodes: [{ id: 'n1', type: 'image', x: 40, y: 40, params: { provider: 'gguf_local' } }, { id: 'n2', type: 'video', x: 520, y: 40, params: { provider: 'local_hf' } }], edges: [] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node[data-id="n1"]', { timeout: 15000 }); await page.waitForTimeout(700);
  const sel = page.locator('.cv-node[data-id="n1"] select').filter({ has: page.locator('option[value="Q4"]') });
  check('no-de-imagem:campo-quantizacao-ao-carregar', (await sel.count()) === 1);
  check('no-de-video-local-hf:sem-o-campo-so-vale-para-gguf', (await page.locator('.cv-node[data-id="n2"] option[value="Q4"]').count()) === 0);
  await sel.first().selectOption('Q4'); await page.waitForTimeout(1200);
  const saved = await api('/api/projects/' + cv.id);
  check('no-de-imagem:grava-extra-quant', (((saved.nodes.find((n) => n.id === 'n1') || {}).params || {}).extra || {}).quant === 'Q4');
  await page.locator('.cv-node[data-id="n1"] select').filter({ has: page.locator('option[value="Q4"]') }).first().selectOption('');
  await page.waitForTimeout(1200);
  check('no-de-imagem:automatica-tira-o-campo', !('quant' in ((((await api('/api/projects/' + cv.id)).nodes.find((n) => n.id === 'n1') || {}).params || {}).extra || {})));
});
