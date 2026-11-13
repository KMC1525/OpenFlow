// Barra de pesquisa de modelos no editor (Hugging Face, simulado): todas as quantizações, baixar e usar.
const { run } = require('./_common.js');
const { execFileSync } = require('child_process');
const fs = require('fs'); const os = require('os'); const path = require('path');
run('canvas_hub', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 900 });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'flow-hub-'));
  const png = path.join(dir, 'p.png');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64', '-frames:v', '1', png]);
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Hub', template: 'blank' } });
  const base = page.url().split('#')[0];
  const up = await (await fetch(`${base}api/projects/${cv.id}/assets`, { method: 'POST', headers: { 'X-Filename': 'p.png', 'Content-Type': 'image/png' }, body: fs.readFileSync(png) })).json();
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Hub', nodes: [{ id: 'u1', type: 'upload', x: 0, y: 0, params: { files: [up.id] } }, { id: 'im1', type: 'image', x: 320, y: 0, params: {} }], edges: [] } });

  // ---- Hugging Face simulado: pesquisa, arquivos (quantizações), download, uso
  const seen = { use: null, search: [] }; let downloaded = false;
  const json = (route, body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/media/hub/search*', (r) => { seen.search.push(new URL(r.request().url()).search); const u = new URL(r.request().url()); const fmt = u.searchParams.get('format'); const cap = u.searchParams.get('cap'); json(r, { format: fmt, cap, results: [{ id: 'acme/flux-mini-gguf', downloads: 12345, likes: 7, cap, format: fmt }, { id: 'acme/outro', downloads: 99, likes: 0, cap, format: fmt }] }); });
  await page.route('**/api/hf/files*', (r) => json(r, { files: [{ name: 'flux-Q2_K.gguf', files: ['flux-Q2_K.gguf'], sizes: { 'flux-Q2_K.gguf': 3000000000 }, size: 3000000000, parts: 1, quant: 'Q2_K', bits: 2, quality: 'very_low', fits: true, recommended: false },
    { name: 'flux-Q4_K_M.gguf', files: ['flux-Q4_K_M.gguf'], sizes: { 'flux-Q4_K_M.gguf': 6500000000 }, size: 6500000000, parts: 1, quant: 'Q4_K_M', bits: 4, quality: 'good', fits: true, recommended: true },
    { name: 'flux-Q8_0.gguf', files: ['flux-Q8_0.gguf'], sizes: { 'flux-Q8_0.gguf': 12000000000 }, size: 12000000000, parts: 1, quant: 'Q8_0', bits: 8, quality: 'lossless', fits: false, recommended: false }] }));
  await page.route('**/api/hf/local*', (r) => json(r, { models: downloaded ? [{ name: 'flux-Q4_K_M.gguf', kind: 'image', size: 1 }] : [], kinds: {} }));
  await page.route('**/api/hf/download', (r) => { downloaded = true; json(r, { job_id: 'j_fake' }); });
  await page.route('**/api/jobs/j_fake/events', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"start"}\n\ndata: {"type":"progress","done":50,"total":100}\n\ndata: {"type":"done","name":"flux-Q4_K_M.gguf"}\n\ndata: {"type":"end"}\n\n' }));
  await page.route('**/api/media/hub/use', (r) => { seen.use = JSON.parse(r.request().postData()); json(r, { ok: true, provider: 'gguf_local', label: 'GGUF local', model: seen.use.model, cap: seen.use.cap, node_updated: !!seen.use.node }); });
  await page.route('**/api/media/local/options*', (r) => json(r, { model: 'x', recommended: 'fp16', options: [{ id: 'fp32', size: 4000000000, recommended: false }, { id: 'fp16', size: 2000000000, recommended: true }, { id: 'bf16', size: 2000000000, recommended: false }] }));
  await page.route('**/api/media/local/quants*', (r) => json(r, { variants: [{ id: 'acme/musicgen-int8', size: 900000000, downloads: 5, kind: 'int8', loadable: true, note: '8 bits' }] }));
  await page.route('**/api/media/local/state*', (r) => json(r, { libs: true, models: {} }));

  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node', { timeout: 10000 }); await page.waitForTimeout(500);
  check('barra:no-topo-do-editor-so-com-o-campo', (await page.locator('.cv-top .cv-hub #hub-q').count()) === 1 && (await page.locator('.cv-top > .cv-hub > #hub-cap').count()) === 0);
  await page.locator('.cv-node.t-image').click();
  await page.fill('#hub-q', 'flux'); await page.keyboard.press('Enter');
  await page.waitForSelector('.hub-r[data-repo="acme/flux-mini-gguf"]', { timeout: 8000 });
  check('busca:resultados-do-mais-baixado', (await page.locator('.hub-r').count()) === 2 && seen.search[0].includes('format=gguf') && seen.search[0].includes('cap=image'));
  await page.locator('.hub-r[data-repo="acme/flux-mini-gguf"]').click();
  await page.waitForSelector('.hub-q[data-quant="Q4_K_M"]', { timeout: 8000 });
  check('quantizacoes:todas-listadas', (await page.locator('.hub-q[data-quant]').count()) === 3);
  check('quantizacoes:recomendada-e-aviso-de-ram', (await page.locator('.hub-q[data-quant="Q4_K_M"] .chip.on', { hasText: /Recomendada|Recommended/ }).count()) === 1 && (await page.locator('.hub-q[data-quant="Q8_0"] .chip.warn').count()) === 1);
  await page.locator('.hub-q[data-quant="Q4_K_M"] [data-act="download"]').click();
  await page.waitForSelector('.hub-q[data-quant="Q4_K_M"] [data-act="use"]', { timeout: 8000 });
  check('download:depois-do-download-aparece-usar', true);
  await page.locator('.hub-q[data-quant="Q4_K_M"] [data-act="use"]').click(); await page.waitForTimeout(600);
  check('usar:envia-tipo-provedor-modelo-e-no-selecionado', !!seen.use && seen.use.cap === 'image' && seen.use.provider === 'gguf_local' && seen.use.model === 'flux-Q4_K_M.gguf' && seen.use.canvas === cv.id && seen.use.node === 'im1');

  // ---- tipos sem GGUF usam o formato original: precisões + quantizações da comunidade
  await page.locator('#hub-q').focus(); await page.waitForSelector('#hub-panel #hub-cap', { timeout: 5000 });
  await page.selectOption('#hub-cap', 'sound'); await page.waitForTimeout(300);
  check('formato:som-nao-tem-gguf', await page.locator('#hub-fmt').isDisabled());
  await page.fill('#hub-q', 'musicgen'); await page.keyboard.press('Enter');
  await page.waitForSelector('.hub-r[data-repo="acme/flux-mini-gguf"]', { timeout: 8000 });
  await page.locator('.hub-r').first().click();
  await page.waitForSelector('.hub-q[data-quant="fp16"]', { timeout: 8000 });
  check('original:precisoes-fp32-fp16-bf16', (await page.locator('.hub-q[data-quant]').count()) === 3 && (await page.locator('.hub-q[data-quant="fp16"] .chip.on', { hasText: /Recomendada|Recommended/ }).count()) === 1);
  check('original:quantizacoes-da-comunidade', (await page.locator('.hub-q[data-variant="acme/musicgen-int8"]').count()) === 1);
  await page.mouse.click(5, 300); await page.waitForTimeout(200);
  check('painel:fecha-ao-clicar-fora', await page.locator('#hub-panel.hidden').count() === 1);

  fs.rmSync(dir, { recursive: true, force: true });
});
