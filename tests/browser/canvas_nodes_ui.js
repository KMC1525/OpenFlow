// v0.11 Canvas: paleta reorganizada (Texto, Imagem, Vídeo, Som, Input, Output), 30 nós novos que desenham seus controles, e uma cadeia que mistura nós novos e antigos rodando de verdade.
const { run, until } = require('./_common.js');
run('canvas_nodes', async ({ api, open, check }) => {
  const page = await open({ width: 1500, height: 950 });
  // menu «…» do nó fica colado no botão mesmo com a interface ampliada (escala 125%)
  await api('/api/settings', { method: 'PUT', body: { ui: { scale: 125 } } }); await page.reload(); await page.waitForSelector('#side nav');
  const cv0 = await api('/api/projects', { method: 'POST', body: { name: 'Menu' } });
  await api('/api/projects/' + cv0.id, { method: 'PUT', body: { nodes: [{ id: 'a', type: 'text', x: 200, y: 200, params: { text: 'oi' } }], edges: [] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv0.id); await page.waitForSelector('.cv-node', { timeout: 15000 });
  const dots = page.locator('.cv-node .hd button, .cv-node .hd .btn').last(); await dots.click(); await page.waitForSelector('.pop', { timeout: 5000 });
  const gap = await page.evaluate(() => { const a = document.querySelector('.cv-node .hd').querySelectorAll('button'); const b = a[a.length - 1].getBoundingClientRect(), p = document.querySelector('.pop').getBoundingClientRect(); return { inside: p.left >= 0 && p.right <= innerWidth + 1, flush: p.right >= innerWidth - 10, dx: Math.abs(p.left - b.left), dy: Math.min(Math.abs(p.bottom - b.top), Math.abs(p.top - b.bottom)) }; });
  check('menu-do-no:colado-no-botao-com-escala-125', gap.inside && gap.dy < 20 && (gap.dx < 20 || gap.flush));   // alinhado ao botão (ou encostado na borda direita, se faltar espaço)
  await page.keyboard.press('Escape'); await page.mouse.click(5, 5);
  await api('/api/settings', { method: 'PUT', body: { ui: { scale: 100 } } }); await page.reload(); await page.waitForSelector('#side nav');
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Nós novos' } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-pal', { timeout: 15000 });
  const heads = await page.locator('.cv-pal h4').allInnerTexts();
  check('paleta:seis-grupos-na-ordem', heads.join('|').toLowerCase() === 'text|image|video|sound|input|output');
  check('paleta:41-nos', (await page.locator('.cv-pal .it').count()) === 41);
  // cada nó da paleta entra no canvas e desenha o corpo sem erro
  const n = await page.locator('.cv-pal .it').count();
  for (let i = 0; i < n; i++) { await page.locator('.cv-pal .it').nth(i).click(); await page.waitForTimeout(40); }
  await page.waitForTimeout(500);
  check('paleta:todos-entram-no-canvas', (await page.locator('.cv-node').count()) === 41);
  check('nos:todos-com-corpo-e-titulo', (await page.locator('.cv-node > .bd').count()) === 41 && (await page.locator('.cv-node .ti').count()) === 41);
  check('nos:novos-tem-controles', (await page.locator('.cv-node.t-img_resize select, .cv-node.t-out_export select').count()) >= 3 && (await page.locator('.cv-node.t-text_template textarea').count()) === 1);
  // cadeia real: cor → filtro → galeria, silêncio → efeito → áudio final, texto → sorteio/modelo
  const nodes = [
    { id: 'c', type: 'in_color', x: 0, y: 0, params: { color: '#ff0000', width: 64, height: 64 } }, { id: 'f', type: 'img_filter', x: 300, y: 0, params: { preset: 'bw' } },
    { id: 's', type: 'in_silence', x: 0, y: 300, params: { seconds: 2 } }, { id: 'fx', type: 'aud_fx', x: 300, y: 300, params: { fx: 'echo' } }, { id: 'oa', type: 'out_audio', x: 600, y: 300, params: {} },
    { id: 'r', type: 'in_random', x: 0, y: 600, params: { lines: 'a\nb', count: 1, seed: 5 } }, { id: 't', type: 'text_template', x: 300, y: 600, params: { template: 'Ideia: {1}' } },
    { id: 'g', type: 'out_gallery', x: 900, y: 0, params: {} },
  ];
  const edges = [{ from: 'c', to: 'f', port: 'image' }, { from: 'f', to: 'g', port: 'items' }, { from: 's', to: 'fx', port: 'audio' }, { from: 'fx', to: 'oa', port: 'audio' }, { from: 'oa', to: 'g', port: 'items' },
    { from: 'r', to: 't', port: 'vars' }, { from: 't', to: 'g', port: 'items' }];
  const ch = await api('/api/projects', { method: 'POST', body: { name: 'Cadeia' } });   // outro canvas: o do passo anterior se salva sozinho com os 41 nós
  await api('/api/projects/' + ch.id, { method: 'PUT', body: { nodes, edges } });
  await page.evaluate((id) => { location.hash = '#/projects'; setTimeout(() => { location.hash = '#/project/' + id; }, 150); }, ch.id);
  await page.waitForSelector('.cv-node.t-out_gallery', { timeout: 15000 }); await page.waitForTimeout(600);
  check('cadeia:8-nos-7-conexoes', (await page.locator('.cv-node').count()) === 8 && (await page.locator('.cv-edges .vis').count()) === 7);
  await page.locator('.cv-top .btn.primary').click();
  let states = [];
  for (let i = 0; i < 150; i++) { states = (await api('/api/projects/' + ch.id)).nodes.map((x) => x.id + ':' + x.result.state + (x.result.error ? '(' + x.result.error + ')' : '')); if (states.every((x) => /:(done)/.test(x)) || states.some((x) => /:error/.test(x))) break; await page.waitForTimeout(500); }
  check('cadeia:todos-os-nos-rodaram-' + states.join(','), states.every((x) => /:done$/.test(x)));
  await until(page, () => !document.querySelector('.cv-root.running'), null, 30000);
  await page.waitForTimeout(800);
  const gal = page.locator('.cv-node.t-out_gallery');
  check('cadeia:galeria-mostra-imagem-audio-e-texto', (await gal.locator('img').count()) === 1 && (await gal.locator('audio').count()) === 1 && /Ideia: [ab]/.test(await gal.innerText()));
  const saved = await api('/api/projects/' + ch.id);
  check('cadeia:sem-erros', saved.nodes.every((x) => x.result.state === 'done' && !x.result.error));
  await page.close();
});
