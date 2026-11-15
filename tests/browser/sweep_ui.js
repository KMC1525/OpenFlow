// v0.38 — varredura geral: todas as telas (desktop e celular, sem rolagem horizontal), todas as abas de Configurações e TODOS os nós do canvas mexendo em cada controle (cada opção de cada lista, números e textos estranhos),
// depois rodando o canvas inteiro: nada pode gerar erro de página/console e o app precisa continuar respondendo.
const { run, until } = require('./_common.js');
run('sweep', async ({ api, open, check, expectError }) => {
  expectError(/Failed to load resource/);   // os nós de entrada/saída sem ligação respondem 4xx de propósito
  const page = await open({ width: 1500, height: 950 });
  const routes = ['projects', 'library', 'settings'];
  const nav = await page.locator('#side nav a').evaluateAll((a) => a.map((x) => x.getAttribute('href')));
  check('telas:menu-lateral-tem-links', nav.length >= 3);
  const overflow = async () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  for (const vp of [{ width: 1500, height: 950 }, { width: 390, height: 800 }, { width: 3440, height: 1440 }]) {
    await page.setViewportSize(vp);
    for (const href of nav) {
      await page.evaluate((h) => { location.hash = h; }, href); await page.waitForTimeout(350);
      const ov = await overflow();
      check(`tela:${href}:${vp.width}:sem-rolagem-horizontal`, ov <= 2);
    }
  }
  await page.setViewportSize({ width: 1500, height: 950 });
  // Configurações: todas as abas abrem e não deixam a tela vazia
  await page.evaluate(() => { location.hash = '#/settings'; }); await page.waitForSelector('.cfgtabs button', { timeout: 8000 });
  const tabs = await page.locator('.cfgtabs button').count();
  for (let i = 0; i < tabs; i++) { await page.locator('.cfgtabs button').nth(i).click(); await page.waitForTimeout(250); check(`config:aba-${i}-tem-conteudo`, (await page.locator('.cfg').innerText()).trim().length > 20); }
  // canvas com TODOS os nós
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Varredura' } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-pal .it', { timeout: 15000 });
  const total = await page.locator('.cv-pal .it').count();
  for (let i = 0; i < total; i++) { await page.locator('.cv-pal .it').nth(i).click(); await page.waitForTimeout(30); }
  await page.waitForTimeout(500);
  const count = await page.locator('.cv-node').count();
  check('canvas:todos-os-nos-entraram', count === total);
  // mexe em cada controle de cada nó
  const weird = ['', '-5', '99999999999', '😀 ünï', '<b>x</b>', '0', '1e9', ' '.repeat(5)];
  let touched = 0;
  for (let i = 0; i < count; i++) {
    const node = page.locator('.cv-node').nth(i);
    const selects = node.locator('select');
    for (let s = 0; s < await selects.count(); s++) {
      const sel = selects.nth(s);
      const vals = await sel.locator('option').evaluateAll((o) => o.map((x) => x.value).filter((v) => v && v !== '__config' && v !== '__custom'));
      for (const v of vals.slice(0, 14)) { try { await sel.selectOption(v, { timeout: 1500 }); touched++; } catch (e) { /* opção que sai da lista ao mudar */ } }
    }
    const inputs = node.locator('input[type=text], input[type=number], input:not([type]), textarea');
    for (let k = 0; k < await inputs.count(); k++) {
      const el = inputs.nth(k);
      if (!(await el.isVisible())) continue;
      for (const w of weird) { try { await el.fill(w, { timeout: 1500 }); touched++; } catch (e) { /* campo numérico recusa texto */ } }
      await el.blur().catch(() => {});
    }
    const boxes = node.locator('input[type=checkbox]');
    for (let k = 0; k < await boxes.count(); k++) { try { await boxes.nth(k).click({ timeout: 1000 }); await boxes.nth(k).click({ timeout: 1000 }); touched++; } catch (e) { /* oculto */ } }
  }
  await page.waitForTimeout(1200);
  check('canvas:mexeu-em-muitos-controles', touched > 200);
  check('canvas:ainda-tem-todos-os-nos', (await page.locator('.cv-node').count()) === count);
  // o que foi salvo continua válido e carrega de novo
  const saved = await api('/api/projects/' + cv.id);
  check('canvas:salvou-todos-os-nos', saved.nodes.length === count);
  await page.reload(); await page.waitForSelector('.cv-node', { timeout: 15000 }); await page.waitForTimeout(600);
  check('canvas:recarrega-igual', (await page.locator('.cv-node').count()) === count);
  // roda tudo (a maioria falha de propósito por falta de entradas: o importante é não travar nem quebrar a página)
  await page.locator('.cv-top .btn.primary').click();
  await page.waitForSelector('.cv-root.running', { timeout: 5000 }).catch(() => {});   // a corrida começa depois do clique: espera o estado «rodando» aparecer antes de esperar ele sumir
  await until(page, () => !document.querySelector('.cv-root.running'), null, 120000);
  await page.waitForTimeout(600);
  check('canvas:terminou-de-rodar-e-responde', (await page.locator('.cv-node').count()) === count && (await page.locator('.cv-top').count()) === 1);
  let after = await api('/api/projects/' + cv.id);
  const t0 = Date.now(); const trace = [];
  while (Date.now() - t0 < 60000 && after.nodes.some((n) => ['running', 'queued'].includes(n.result.state))) { trace.push(Math.round((Date.now() - t0) / 100) / 10 + 's:' + after.nodes.filter((n) => ['running', 'queued'].includes(n.result.state)).map((n) => n.type).join('+')); await page.waitForTimeout(500); after = await api('/api/projects/' + cv.id); }
  const stuck = after.nodes.filter((n) => ['running', 'queued'].includes(n.result.state)).map((n) => n.type + ':' + n.result.state);
  check('canvas:nenhum-no-ficou-rodando' + (stuck.length ? '-' + stuck.join(',') : ''), stuck.length === 0);
});
