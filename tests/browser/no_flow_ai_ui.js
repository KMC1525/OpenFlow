// v0.39/v0.40 — o «Gerar fluxo com IA» saiu: não há caixa de prompt no canvas, a API não tem a rota, e (v0.40) também não há seletor de equipe/esforço na barra do topo.
const { run, until } = require('./_common.js');
run('no_flow_ai', async ({ api, open, check }) => {
  const page = await open({ width: 1500, height: 900 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Sem gerador', template: 'blank' } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-pal .it', { timeout: 15000 }); await page.waitForTimeout(500);
  check('sem-caixa-de-prompt', (await page.locator('#cv-dock, #cv-dock-text, #cv-dock-go').count()) === 0);
  check('sem-texto-gerar-fluxo', !/Gerar fluxo|Generate flow/i.test(await page.locator('.cv-root').innerText()));
  check('sem-seletor-de-equipe-nem-esforco', (await page.locator('.cv-top .team-pick, #cv-team, .team-sel').count()) === 0 && !/Low|Omni|agent/i.test(await page.locator('.cv-top').innerText()));
  const top = await page.locator('.cv-top').boundingBox();
  const run_ = await page.locator('.cv-top .btn.primary').boundingBox();
  check('barra-do-topo-cabe-na-tela', top.width <= 1500 && run_.x + run_.width <= 1500 + 1);
  check('rota-removida', (await fetch(`http://127.0.0.1:${process.env.OPENFLOW_PORT}/api/projects/${cv.id}/flow`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"prompt":"x"}' })).status === 404);
  // a execução continua com a equipe escolhida
  await page.locator('.cv-pal .it').first().click(); await page.waitForTimeout(300);
  await page.locator('.cv-top .btn.primary').click();
  await page.waitForSelector('.cv-root.running', { timeout: 5000 }).catch(() => {});
  await until(page, () => !document.querySelector('.cv-root.running'), null, 30000);
  check('executar-tudo-ainda-funciona', (await page.locator('.cv-node').count()) === 1);
  // as telas pequenas também mostram a barra sem estourar
  await page.setViewportSize({ width: 390, height: 800 }); await page.waitForTimeout(300);
  check('celular:sem-rolagem-horizontal', (await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)) <= 2);
});
