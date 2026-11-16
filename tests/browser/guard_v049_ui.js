// v0.49 — proteção do computador: o cartão em Configurações → Desempenho (limite, segundos, o que vigiar, medidas ao vivo, «Parar tudo agora») e a faixa de aviso depois de uma parada.
const { run } = require('./_common.js');
run('guard_v049', async ({ api, open, check }) => {
  const page = await open({ width: 1400, height: 950 });
  await page.evaluate(() => { location.hash = '#/settings'; }); await page.waitForSelector('.cfgtabs button', { timeout: 8000 });
  await page.locator('.cfgtabs button').nth(4).click(); await page.waitForSelector('#guard-limit', { timeout: 8000 });
  check('cartao:limite-padrao-90', (await page.inputValue('#guard-limit')) === '90');
  check('cartao:segundos-padrao-5', (await page.inputValue('#guard-hold')) === '5');
  await page.waitForSelector('#guard-ram', { timeout: 8000 });
  check('cartao:medidas-ao-vivo', (await page.locator('#guard-ram').count()) === 1 && /%|medido|measured/.test(await page.locator('#guard-ram').innerText()));
  await page.fill('#guard-limit', '70'); await page.locator('#guard-limit').dispatchEvent('change'); await page.waitForTimeout(600);
  check('cartao:salva-o-limite', (await api('/api/settings')).performance.guard.limit === 70);
  await page.fill('#guard-limit', '5'); await page.locator('#guard-limit').dispatchEvent('change'); await page.waitForTimeout(600);
  check('cartao:limite-minimo-50', (await api('/api/settings')).performance.guard.limit === 50 && (await page.inputValue('#guard-limit')) === '50');
  await page.fill('#guard-limit', '90'); await page.locator('#guard-limit').dispatchEvent('change'); await page.waitForTimeout(600);
  // outro cartão de Desempenho grava sem desfazer a proteção
  await page.selectOption('#md-conn', '2'); await page.waitForTimeout(500);
  check('cartao:outros-ajustes-nao-desfazem', (await api('/api/settings')).performance.guard.limit === 90);
  // a faixa aparece depois de uma parada. A parada real mata os processos filhos do servidor — que no teste incluem este próprio script —, então a API é simulada aqui (a parada real é coberta em tests/test_guard_v049.py).
  let trips = 0, trip = null;
  await page.route('**/api/guard/stop', (route) => { trips += 1; trip = { id: trips, manual: true, reason: 'Parado por você.', stopped: { jobs: 2, processes: 1, models: 1 } }; route.fulfill({ contentType: 'application/json', body: JSON.stringify(trip) }); });
  await page.route('**/api/guard', async (route) => { const r = await route.fetch(); const g = await r.json(); route.fulfill({ response: r, contentType: 'application/json', body: JSON.stringify(Object.assign(g, { trips, last_trip: trip })) }); });
  await page.waitForTimeout(2500);   // a página já tinha lido o contador (0) antes
  await page.locator('#guard-stop').click();
  await page.waitForSelector('#guard-banner:not(.hidden)', { timeout: 8000 });
  const text = await page.locator('#guard-banner').innerText();
  check('parada:faixa-de-aviso', /parado|stopped/i.test(text));
  check('parada:faixa-mostra-os-numeros', /2/.test(text) && /1/.test(text));
  await page.locator('#guard-ok').click(); await page.waitForTimeout(200);
  check('parada:faixa-some-com-entendi', await page.locator('#guard-banner').evaluate((e) => e.classList.contains('hidden')));
});
