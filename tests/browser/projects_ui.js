// Tela inicial: lista de projetos, barra de pesquisa (nome, descrição e textos dos nós; sem acentos), ordenação, criar, renomear, duplicar e apagar.
const { run, until } = require('./_common.js');
run('projects', async ({ api, open, check }) => {
  for (const p of await api('/api/projects')) await api('/api/projects/' + p.id, { method: 'DELETE' });   // começa do zero (o servidor do teste é compartilhado)
  const mk = (name, template = 'blank', prompt = '') => api('/api/projects', { method: 'POST', body: { name, template, prompt } });
  await mk('Floresta Mágica', 'text_image', 'Uma floresta ao amanhecer, névoa suave');
  const urban = await mk('Cenário urbano');
  await api(`/api/projects/${urban.id}/meta`, { method: 'POST', body: { description: 'Ruas molhadas à noite, neon' } });
  await mk('Teste astronauta', 'image_video', 'astronauta no planeta de cristais');
  const page = await open({ width: 1400, height: 900 });
  const names = async () => page.locator('.cv-card .nm').allInnerTexts();
  const settle = () => page.waitForTimeout(650);
  await page.waitForSelector('.cv-card', { timeout: 10000 });
  check('lista:tres-projetos', (await names()).length === 3 && /3 projects/.test(await page.locator('.pj-status').innerText()));
  check('lista:cartao-e-um-link-para-o-projeto', ((await page.locator('.cv-card .cv-open').first().getAttribute('href')) || '').startsWith('#/project/'));

  await page.fill('#pj-search', 'CENARIO'); await settle();
  check('pesquisa:ignora-acentos-e-maiusculas', (await names()).join('|') === 'Cenário urbano' && /1 of 3/.test(await page.locator('.pj-status').innerText()));
  check('pesquisa:destaca-o-trecho-achado', (await page.locator('.cv-card mark').first().innerText()).toLowerCase() === 'cenario' || (await page.locator('.cv-card mark').count()) > 0);
  await page.fill('#pj-search', 'nevoa'); await settle();
  check('pesquisa:acha-pelo-texto-de-um-no', (await names()).join('|') === 'Floresta Mágica' && /névoa/.test(await page.locator('.cv-card .mt.match').innerText()));
  await page.fill('#pj-search', 'neon'); await settle();
  check('pesquisa:acha-pela-descricao', (await names()).join('|') === 'Cenário urbano');
  await page.fill('#pj-search', 'floresta teste'); await settle();
  check('pesquisa:todas-as-palavras-no-mesmo-projeto', (await page.locator('.cv-card').count()) === 0 && (await page.locator('.empty h3').innerText()).includes('floresta teste'));
  await page.fill('#pj-search', 'a'); await page.locator('#pj-search').press('Escape'); await settle();
  check('pesquisa:escape-limpa', (await page.inputValue('#pj-search')) === '' && (await names()).length === 3);

  // ordenar
  await page.selectOption('#pj-sort', 'name'); await settle();
  check('ordenar:por-nome', (await names()).join('|') === 'Cenário urbano|Floresta Mágica|Teste astronauta');
  await page.reload(); await page.waitForSelector('.cv-card');
  check('ordenar:lembra-a-escolha', (await page.inputValue('#pj-sort')) === 'name');

  // sem resultado: criar um projeto com o nome pesquisado
  await page.fill('#pj-search', 'meu clipe'); await settle();
  await page.locator('.empty .btn.primary').click(); await page.waitForSelector('.modal input', { timeout: 5000 });
  check('criar:nome-vem-da-pesquisa', (await page.inputValue('.modal input')) === 'meu clipe');
  await page.locator('.modal .btn.primary').click();
  await page.waitForFunction(() => /^#\/project\//.test(location.hash), null, { timeout: 10000 });
  await page.waitForSelector('.cv-top .nm', { timeout: 8000 });
  check('criar:abre-o-editor-do-projeto-novo', (await page.inputValue('.cv-top .nm')) === 'meu clipe');
  await page.locator('.cv-back').click(); await page.waitForSelector('.cv-card');
  check('editor:voltar-leva-aos-projetos', (await page.evaluate(() => location.hash)) === '#/projects' && (await names()).length === 4);

  // menu do cartão: renomear, duplicar, apagar
  const menuOf = async (name) => { await page.locator('.cv-card', { hasText: name }).locator('.mn').click(); await page.waitForSelector('[role="menu"]'); };
  await menuOf('Teste astronauta'); await page.locator('[role="menuitem"]', { hasText: /Rename/ }).click();
  await page.fill('.modal input', 'Astronauta v2'); await page.locator('.modal .btn.primary').click(); await settle();
  check('menu:renomear', (await names()).includes('Astronauta v2'));
  await menuOf('Astronauta v2'); await page.locator('[role="menuitem"]', { hasText: /Duplicate/ }).click(); await settle();
  check('menu:duplicar', (await names()).filter((n) => n.startsWith('Astronauta v2')).length === 2);
  await menuOf('Astronauta v2 (2)'); await page.locator('[role="menuitem"]', { hasText: /Delete/ }).click();
  await page.locator('.modal .btn.danger, .modal .btn.primary').last().click(); await settle();
  check('menu:apagar', !(await names()).includes('Astronauta v2 (2)') && (await names()).length === 4);

  // a paleta encontra os projetos
  await page.keyboard.press('Control+k'); await page.waitForSelector('.palette');
  await page.fill('.palette input', 'floresta'); await page.waitForTimeout(500);
  check('paleta:acha-projetos', (await page.locator('.palette-item', { hasText: 'Floresta Mágica' }).count()) === 1);
  await page.keyboard.press('Enter'); await page.waitForFunction(() => /^#\/project\//.test(location.hash), null, { timeout: 8000 });
  check('paleta:enter-abre-o-projeto', true);
});
