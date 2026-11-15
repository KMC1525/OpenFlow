// v0.37 — nó «Modelo 3D»: aparece na paleta (grupo 3D), roda com o Demo, mostra o visualizador no próprio nó (canvas desenhado, arrastar gira) e na ampliação, e a Biblioteca lista o arquivo.
const { run, until } = require('./_common.js');
run('model3d', async ({ api, open, check }) => {
  const page = await open({ width: 1500, height: 950 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Três D', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Três D', edges: [{ id: 'e1', from: 't', to: 'm', port: 'prompt' }], nodes: [
    { id: 't', type: 'text', x: 20, y: 40, params: { text: 'um vaso de cerâmica azul' } },
    { id: 'm', type: 'model3d', x: 420, y: 20, params: {} }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node[data-id="m"]', { timeout: 10000 }); await page.waitForTimeout(700);
  const node = page.locator('.cv-node[data-id="m"]');
  check('paleta:grupo-3d', (await page.locator('.cv-pal').innerText()).includes('Modelo 3D') || (await page.locator('.cv-pal .it', { hasText: /Modelo 3D|3D model/ }).count()) === 1);
  check('no:formato-e-modelo', (await node.locator('.mpick select').count()) === 1 && /GLB/.test(await node.innerText()) && /OBJ/.test(await node.innerText()));
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));
  await page.evaluate(() => { const b = [...document.querySelectorAll('button')].find((x) => /Executar|Run|Gerar tudo|Generate/i.test(x.textContent)); if (b) b.click(); });
  await until(page, () => !document.querySelector('.cv-root.running'), null, 60000);
  await page.waitForSelector('.cv-node[data-id="m"] canvas.mv3d', { timeout: 15000 });
  await page.waitForTimeout(900);
  const info = await node.locator('.mv3d-box .dim').first().innerText();
  check('visualizador:mostra-vertices-e-faces', /\d/.test(info) && /(vértices|vertices)/.test(info) && /(faces)/.test(info));
  const painted = async () => page.evaluate(() => { const c = document.querySelector('.cv-node[data-id="m"] canvas.mv3d'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; });
  check('visualizador:desenhou-a-malha', (await painted()) > 2000);
  const before = await page.evaluate(() => document.querySelector('.cv-node[data-id="m"] canvas.mv3d').toDataURL().length);
  const box = await node.locator('canvas.mv3d').boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down(); await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2 + 20, { steps: 6 }); await page.mouse.up();
  await page.waitForTimeout(300);
  const after = await page.evaluate(() => document.querySelector('.cv-node[data-id="m"] canvas.mv3d').toDataURL().length);
  check('visualizador:arrastar-gira', before !== after);
  check('no:link-de-download', (await node.locator('a[href*="download=1"]').count()) === 1);
  const proj = await api(`/api/projects/${cv.id}`);
  const asset = proj.assets.find((a) => a.kind === 'model3d');
  check('arquivo:glb-gerado', !!asset && asset.mime === 'model/gltf-binary' && asset.file.endsWith('.glb'));
  const lib = await api('/api/library/files?kind=model3d&source=all');
  check('biblioteca:lista-o-modelo-3d', (lib.files || []).some((f) => f.kind === 'model3d' && f.project === cv.id));
  check('sem-erros-na-pagina', errs.length === 0);
});
