// Editor de fluxos de ponta a ponta no navegador: criar o projeto, conectar, executar (Demo), abrir o Editor de vídeo, editar a linha do tempo e exportar.
const { run, until } = require('./_common.js');
run('canvas', async ({ api, open, check }) => {
  const page = await open();
  // lista → novo projeto pelo modal com o modelo "Cena completa"
  await page.evaluate(() => { location.hash = '#/projects'; }); await page.waitForTimeout(500);
  await page.locator('#pj-new').first().click(); await page.waitForTimeout(300);
  await page.locator('.cv-tpl').nth(4).click(); await page.fill('.modal input', 'Cena do farol');
  await page.locator('.modal .btn.primary').click(); await page.waitForSelector('.cv-node', { timeout: 10000 }); await page.waitForTimeout(800);
  check('editor:7-nos', (await page.locator('.cv-node').count()) === 7);
  check('editor:6-conexoes', (await page.locator('.cv-edges .vis').count()) === 6);
  check('editor:nos-desatualizados', (await page.locator('.cv-node .st.stale').count()) === 5);
  // executar tudo
  await page.locator('.cv-top .btn.primary').click();
  await page.waitForSelector('.cv-root.running', { timeout: 5000 }).catch(() => {});
  await until(page, () => !document.querySelector('.cv-root.running'));
  await page.waitForTimeout(600);
  check('run:imagem-video-audio', (await page.locator('.cv-node .rimgs img').count()) === 1 && (await page.locator('.cv-node video').count()) >= 2 && (await page.locator('.cv-node audio').count()) === 2);
  check('run:tudo-atualizado', (await page.locator('.cv-node .st.stale').count()) === 0 && (await page.locator('.cv-node .st.ok').count()) === 5);
  // Editor de vídeo
  await page.locator('.cv-node.t-editor .btn.primary').click(); await page.waitForSelector('.tl-bg', { timeout: 5000 }); await page.waitForTimeout(700);
  check('timeline:3-clipes-3-trilhas', (await page.locator('.tl-clip').count()) === 3 && (await page.locator('.tl-row').count()) === 3);
  await page.locator('.tl-clip.video, .tl-clip.image').first().click();
  await page.locator('.tl-ruler').click({ position: { x: 140, y: 10 } }); await page.keyboard.press('s'); await page.waitForTimeout(250);
  check('timeline:dividir', (await page.locator('.tl-clip').count()) === 4);
  await page.locator('.tl-bar .btn:has-text("Caption"), .tl-bar .btn:has-text("Legenda")').first().click(); await page.waitForTimeout(250);
  await page.fill('.tl-insp textarea', 'O farol nunca apaga'); await page.waitForTimeout(250);
  check('timeline:legenda-na-previa', (await page.locator('.tl-stage .txt').allInnerTexts()).join('').includes('O farol nunca apaga'));
  const before = (await api(`/api/projects`))[0];
  await page.locator('.tl-hd .btn:has-text("Close"), .tl-hd .btn:has-text("Fechar")').click(); await page.waitForTimeout(1800);
  const cvId = before.id;
  const ed = (await api(`/api/projects/${cvId}`)).nodes.find((n) => n.type === 'editor');
  check('timeline:salva-no-servidor', ed.params.timeline.clips.length === 5 && ed.params.timeline.clips.some((c) => c.text === 'O farol nunca apaga'));
  // exportar
  const old = ed.result.assets[0];
  await page.locator('.cv-node.t-editor .btn.primary').click(); await page.waitForSelector('.tl-bg');
  await page.locator('.tl-hd .btn.primary').click();
  let done = null;
  for (let i = 0; i < 200 && !done; i++) { const r = (await api(`/api/projects/${cvId}`)).nodes.find((n) => n.type === 'editor').result; if (r.state === 'done' && r.assets[0] !== old) done = r; else await page.waitForTimeout(300); }
  check('export:novo-video', !!done);
  // paleta, conexão válida e inválida, apagar
  await page.waitForTimeout(800);
  const n0 = await page.locator('.cv-node').count();
  await page.locator('.cv-pal .it').first().click(); await page.waitForTimeout(200);
  check('paleta:adiciona-no', (await page.locator('.cv-node').count()) === n0 + 1);
  await page.keyboard.press('Delete'); await page.waitForTimeout(200);
  check('teclado:delete-apaga-no', (await page.locator('.cv-node').count()) === n0);
  await page.close();
});
