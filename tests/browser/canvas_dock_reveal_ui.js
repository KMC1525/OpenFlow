// v0.20 — o painel «Gerar fluxo com IA» não esconde o erro (e os botões dele) de um nó: depois da execução o canvas sobe o nó para acima do painel.
const { run } = require('./_common.js');
run('canvas_dock_reveal', async ({ api, open, check }) => {
  const page = await open({ width: 1300, height: 800 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Painel', template: 'blank' } });
  // modelo GGUF que não existe: o nó dá erro («não encontrado»), e o nó está perto do painel
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Painel', edges: [], viewport: { zoom: 1, x: 0, y: 0 }, nodes: [
    { id: 'im', type: 'image', x: 440, y: 120, params: { provider: 'gguf_local', model: 'nao-existe-Q4.gguf', prompt: 'um farol' } }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node', { timeout: 10000 }); await page.waitForTimeout(700);
  const rects = () => page.evaluate(() => {
    const n = document.querySelector('.cv-node[data-id="im"]').getBoundingClientRect(), d = document.getElementById('cv-dock').getBoundingClientRect();
    const s = document.querySelector('.cv-surface').getBoundingClientRect();
    return { nodeBottom: n.bottom, nodeTop: n.top, dockTop: d.top, areaTop: s.top, overlapX: n.right > d.left && n.left < d.right };
  });
  await page.locator('#cv-run, button:has-text("Executar tudo"), button:has-text("Run all")').first().click();
  await page.waitForSelector('.cv-node[data-id="im"] .res .err', { timeout: 20000 }); await page.waitForTimeout(900);
  const r = await rects();
  const err = await page.evaluate(() => { const e = document.querySelector('.cv-node[data-id="im"] .res .err').getBoundingClientRect(), d = document.getElementById('cv-dock').getBoundingClientRect(), s = document.querySelector('.cv-surface').getBoundingClientRect(); return { top: e.top, bottom: e.bottom, dockTop: d.top, areaTop: s.top }; });
  check('mensagem-de-erro-visivel', err.bottom <= err.dockTop && err.bottom > err.areaTop);   // a mensagem inteira aparece acima do painel
  check('painel-continua-la', r.dockTop > r.areaTop);
  check('o-no-tem-erro-depois-de-rodar', err.bottom > err.top);
  check('no-inteiro-acima-do-painel', !r.overlapX || r.nodeBottom <= r.dockTop);   // o fim do nó (erro e botões) não fica atrás do painel
});
