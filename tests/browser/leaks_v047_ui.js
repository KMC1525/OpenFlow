// v0.47 — abrir e fechar o Canvas várias vezes não acumula ouvintes globais (barra de pesquisa de modelos e indicador de downloads se soltam sozinhos) nem temporizadores de consulta.
const { run } = require('./_common.js');
run('leaks_v047', async ({ api, open, check }) => {
  const page = await open({ width: 1400, height: 900 });
  await page.addInitScript(() => {
    window.__ls = {};
    for (const T of [window, document]) {
      const nm = T === window ? 'w' : 'd', add = T.addEventListener.bind(T), rem = T.removeEventListener.bind(T);
      T.addEventListener = (type, fn, o) => { const k = nm + ':' + type; window.__ls[k] = (window.__ls[k] || new Set()); window.__ls[k].add(fn); return add(type, fn, o); };
      T.removeEventListener = (type, fn, o) => { const k = nm + ':' + type; if (window.__ls[k]) window.__ls[k].delete(fn); return rem(type, fn, o); };
    }
  });
  await page.reload(); await page.waitForSelector('#side nav');   // o script de contagem vale a partir da próxima carga
  let polls = 0;
  await page.route('**/api/library/downloads', (r) => { polls++; r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ downloads: [], running: 0 }) }); });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Vazamentos', template: 'blank' } });
  const count = () => page.evaluate(() => ({ hub: (window.__ls['w:flow:hub'] || new Set()).size, dl: (window.__ls['w:flow:downloads'] || new Set()).size, down: (window.__ls['d:pointerdown'] || new Set()).size }));
  const visit = async () => { await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('#cv-dl-btn', { timeout: 15000 }); await page.waitForTimeout(500); await page.evaluate(() => { location.hash = '#/projects'; }); await page.waitForTimeout(700); };
  await visit();
  const first = await count();
  for (let i = 0; i < 4; i++) await visit();
  await page.waitForTimeout(1500);
  const after = await count();
  check('ouvintes:flow-hub-nao-acumulam', after.hub <= first.hub + 1);
  check('ouvintes:flow-downloads-nao-acumulam', after.dl <= first.dl + 1);
  check('ouvintes:pointerdown-nao-acumula', after.down <= first.down + 2);
  // fora do Canvas não há consulta de downloads
  const before = polls; await page.waitForTimeout(6000);
  check('fora-do-canvas:sem-consultas', polls === before);
});
