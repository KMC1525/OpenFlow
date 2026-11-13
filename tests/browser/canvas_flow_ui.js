// Caixa de prompt embaixo do Canvas: gera um fluxo com a equipe (esforço e agentes), minimiza/maximiza sem atrapalhar o fluxo e lembra o estado.
const { run } = require('./_common.js');
run('canvas_flow', async ({ api, open, check }) => {
  await api('/api/settings', { method: 'PUT', body: { language: 'pt-BR', active: { generation: 'demo' } } });
  const page = await open({ width: 1500, height: 950 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Fluxo', template: 'blank' } });
  await page.evaluate((id) => { localStorage.removeItem('openflow.cv.dock'); location.hash = '#/project/' + id; }, cv.id);
  await page.waitForSelector('#cv-dock', { timeout: 15000 });
  const box = async () => page.locator('#cv-dock').boundingBox();
  check('dock:aberta-por-padrao-com-as-configs-da-equipe', (await page.locator('#cv-dock-text').isVisible()) && (await page.locator('#cv-team-effort option').count()) === 8 && (await page.locator('#cv-team-agents option').count()) === 10);
  check('dock:fica-embaixo-e-pequena', (await box()).y > 600 && (await box()).height < 220 && (await box()).width < 620);
  check('dock:equipe-saiu-da-barra-de-cima', (await page.locator('.cv-top #cv-team-effort, .cv-pg > :first-child #cv-team-effort').count()) === 0);
  const full = (await box()).height;
  await page.locator('#cv-dock-toggle').click(); await page.waitForTimeout(200);
  check('dock:minimiza-para-uma-barra-fina', !(await page.locator('#cv-dock-text').isVisible()) && (await box()).height < full / 2 && /Maximizar|Maximize/.test(await page.locator('#cv-dock-toggle').getAttribute('title')));
  await page.reload(); await page.waitForSelector('#cv-dock');
  check('dock:lembra-minimizada', !(await page.locator('#cv-dock-text').isVisible()));
  await page.locator('#cv-dock-toggle').click(); await page.waitForTimeout(200);
  check('dock:maximiza-de-novo', await page.locator('#cv-dock-text').isVisible());
  // arrastar/rolar na caixa não mexe na vista do canvas
  const before = await page.evaluate(() => document.querySelector('.cv-world').style.transform);
  await page.locator('#cv-dock-text').click(); await page.mouse.wheel(0, 300); await page.waitForTimeout(100);
  check('dock:rolagem-na-caixa-nao-da-zoom-no-canvas', (await page.evaluate(() => document.querySelector('.cv-world').style.transform)) === before);
  // gerar um fluxo (Demo: modelo de partida) com 4 agentes
  await page.locator('#cv-team-effort').selectOption('mega'); await page.locator('#cv-team-agents').selectOption('4');
  await page.locator('#cv-dock-text').fill('cena de farol com narração');
  await page.locator('#cv-dock-go').click();
  await page.waitForFunction(() => document.querySelectorAll('.cv-node').length >= 5, null, { timeout: 30000 });
  check('fluxo:nos-adicionados-ao-canvas', (await page.locator('.cv-node').count()) >= 5 && (await page.locator('.cv-edges path, .cv-edges line').count()) >= 4);
  check('fluxo:mensagem-de-resultado', /nós|nodes/.test(await page.locator('#cv-dock-msg').innerText()));
  await page.waitForTimeout(1800);
  const saved = await api(`/api/projects/${cv.id}`);
  check('fluxo:salvo-no-servidor', saved.nodes.length >= 5 && saved.edges.length >= 4 && saved.nodes.some((n) => n.type === 'editor'));
  check('fluxo:caixa-limpa-e-pronta', (await page.locator('#cv-dock-text').inputValue()) === '' && !(await page.locator('#cv-dock-go').isDisabled()));
  // inglês
  await api('/api/settings', { method: 'PUT', body: { language: 'en' } });
  await page.reload(); await page.waitForSelector('#cv-dock');
  check('ingles:titulo-traduzido', /Generate a flow with AI/i.test(await page.locator('#cv-dock').innerText()));
});
