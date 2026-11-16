// v0.58 — nós «Textura 3D», «Esqueleto 3D» e «Animação 3D»: aparecem na paleta (grupo 3D), rodam em cadeia a partir do «Modelo 3D» e o visualizador mostra textura, juntas, animação, esqueleto e o botão Pausar.
const { run, until } = require('./_common.js');
run('model3d_v058', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 1000 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Três D 2', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Três D 2', nodes: [
    { id: 't', type: 'text', x: 20, y: 40, params: { text: 'um vaso de cerâmica azul' } },
    { id: 'm', type: 'model3d', x: 300, y: 20, params: {} },
    { id: 'x', type: 'tex3d', x: 640, y: 20, params: { projection: 'cylindrical', pattern: 'bricks', tile: 2 } },
    { id: 'r', type: 'rig3d', x: 980, y: 20, params: { style: 'spine', bones: 6 } },
    { id: 'a', type: 'anim3d', x: 1320, y: 20, params: { kind: 'sway', duration: 3 } }],
    edges: [{ id: 'e1', from: 't', to: 'm', port: 'prompt' }, { id: 'e2', from: 'm', to: 'x', port: 'model' }, { id: 'e3', from: 'x', to: 'r', port: 'model' }, { id: 'e4', from: 'r', to: 'a', port: 'model' }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node[data-id="a"]', { timeout: 10000 }); await page.waitForTimeout(700);
  const pal = await page.locator('.cv-pal').innerText();
  check('paleta:tres-nos-novos', /Textura 3D|3D texture/.test(pal) && /Esqueleto 3D|3D skeleton/.test(pal) && /Animação 3D|3D animation/.test(pal));
  check('no:formulario-da-animacao', (await page.locator('.cv-node[data-id="a"] select').count()) >= 1 && (await page.locator('.cv-node[data-id="x"] select').count()) >= 2);
  await page.evaluate(() => { const b = [...document.querySelectorAll('button')].find((e) => /Executar|Run|Gerar tudo|Generate/i.test(e.textContent)); if (b) b.click(); });
  await until(page, () => !document.querySelector('.cv-root.running'), null, 90000);
  await page.waitForSelector('.cv-node[data-id="a"] canvas.mv3d', { timeout: 20000 }); await page.waitForTimeout(1200);
  const node = page.locator('.cv-node[data-id="a"]');
  const info = await node.locator('.mv3d-box .dim').first().innerText();
  check('visualizador:juntas', /6 (juntas|joints)/.test(info));
  check('visualizador:animacao', /(animação|animation) 3\.0 s/.test(info));
  check('visualizador:textura', /(com textura|textured)/.test(info));
  check('controles:esqueleto-e-pausar', (await node.locator('#mv-bones').count()) === 1 && (await node.locator('#mv-play').count()) === 1);
  const painted = async () => page.evaluate(() => { const c = document.querySelector('.cv-node[data-id="a"] canvas.mv3d'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; });
  check('visualizador:desenhou', (await painted()) > 2000);
  const shot = async () => page.evaluate(() => document.querySelector('.cv-node[data-id="a"] canvas.mv3d').toDataURL());
  // pausar: dois quadros iguais; tocar: o quadro muda sozinho (a animação anda)
  await node.locator('canvas.mv3d').dispatchEvent('pointerdown', { clientX: 10, clientY: 10, pointerId: 1 }).catch(() => {});
  await node.locator('#mv-play').click(); await page.waitForTimeout(300);
  const p1 = await shot(); await page.waitForTimeout(500); const p2 = await shot();
  check('pausar:quadro-parado', p1 === p2);
  await node.locator('#mv-play').click(); await page.waitForTimeout(250);
  const q1 = await shot(); await page.waitForTimeout(600); const q2 = await shot();
  check('tocar:animacao-anda', q1 !== q2);
  // esqueleto liga/desliga: com os ossos por cima o desenho é diferente
  await node.locator('#mv-play').click(); await page.waitForTimeout(250);
  const withBones = await shot();
  await node.locator('#mv-bones').uncheck(); await page.waitForTimeout(250);
  const without = await shot();
  check('esqueleto:desligar-muda-o-desenho', withBones !== without);
  // a biblioteca e o projeto têm os GLB de cada etapa, e o último tem tudo
  const proj = await api(`/api/projects/${cv.id}`);
  const glbs = proj.assets.filter((a) => a.kind === 'model3d');
  check('arquivos:quatro-modelos', glbs.length === 4 && glbs.every((g) => g.file.endsWith('.glb') && g.mime === 'model/gltf-binary'));
  const done = (id) => proj.nodes.find((n) => n.id === id).result.state;
  check('nos:todos-concluidos', ['m', 'x', 'r', 'a'].every((id) => done(id) === 'done'));
  check('sem-erros-na-pagina', errs.length === 0);
});
