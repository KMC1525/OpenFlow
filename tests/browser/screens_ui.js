// v0.31: telas grandes e ultrawide (a página usa a largura), a busca de nós na paleta do canvas e o painel de armazenamento da Biblioteca.
const { run } = require('./_common.js');
run('screens', async ({ api, open, check }) => {
  await api('/api/settings', { method: 'PUT', body: { language: 'en' } });
  const proj = await api('/api/projects', { method: 'POST', body: { name: 'Telas' } });

  // ultrawide 3440×1440: a lista de projetos usa bem mais que os 1180 px antigos e nada rola para o lado
  const wide = await open({ width: 3440, height: 1440 });
  await wide.waitForSelector('#pj-search', { timeout: 10000 });
  const w = await wide.evaluate(() => ({ page: document.querySelector('.page').getBoundingClientRect().width, scroll: document.documentElement.scrollWidth <= window.innerWidth + 1 }));
  check('ultrawide:a-pagina-usa-a-largura', w.page > 1900);
  check('ultrawide:sem-rolagem-lateral', w.scroll);
  await wide.evaluate((id) => { location.hash = '#/project/' + id; }, proj.id);
  await wide.waitForSelector('#cv-pal-q', { timeout: 10000 });
  check('ultrawide:paleta-mais-larga', (await wide.locator('.cv-pal').evaluate((e) => e.getBoundingClientRect().width)) >= 230);

  // busca de nós
  const all = await wide.locator('#cv-pal-list .it').count();
  await wide.fill('#cv-pal-q', 'imagem');
  check('busca-de-nos:filtra', (await wide.locator('#cv-pal-list .it').count()) < all && (await wide.locator('#cv-pal-list .it').count()) >= 1);
  await wide.fill('#cv-pal-q', 'speed');
  check('busca-de-nos:acha-pelo-nome-em-ingles-ou-tipo', (await wide.locator('#cv-pal-list .it[data-type="vid_speed"]').count()) === 1);
  await wide.fill('#cv-pal-q', 'zzzzqqq');
  check('busca-de-nos:sem-resultado-avisa', (await wide.locator('#cv-pal-list').innerText()).includes('No nodes found'));
  await wide.fill('#cv-pal-q', 'color');
  const before = await wide.locator('.cv-node').count();
  await wide.press('#cv-pal-q', 'Enter');
  await wide.waitForFunction((n) => document.querySelectorAll('.cv-node').length > n, before, { timeout: 5000 });
  check('busca-de-nos:enter-adiciona-o-primeiro', (await wide.locator('.cv-node').count()) === before + 1);
  await wide.press('#cv-pal-q', 'Escape');
  check('busca-de-nos:esc-limpa', (await wide.locator('#cv-pal-list .it').count()) === all);

  // tela de 1920 comum e celular continuam sem rolagem lateral
  for (const [vw, vh] of [[1920, 1080], [390, 844]]) {
    const pg = await open({ width: vw, height: vh });
    await pg.waitForSelector('#pj-search', { timeout: 10000 });
    check(`tela-${vw}:sem-rolagem-lateral`, await pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  }

  // armazenamento na Biblioteca
  const pg = await open({ width: 1500, height: 900 });
  await pg.evaluate(() => { location.hash = '#/library'; }); await pg.waitForSelector('#lib-tab-storage', { timeout: 10000 });
  await pg.click('#lib-tab-storage'); await pg.waitForSelector('#lib-storage .card', { timeout: 8000 });
  const txt = await pg.locator('#lib-storage').innerText();
  check('armazenamento:mostra-o-disco-e-a-limpeza', /disk/i.test(txt) && /cleanup/i.test(txt) && /free of/.test(txt));
});
