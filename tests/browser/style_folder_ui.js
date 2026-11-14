// v0.1 — Style Folder: criar pastas e subpastas, renomear, mover arquivos entre pastas, ligar/desligar, apagar e recarregar sem perder nada.
const { run, until } = require('./_common.js');
const { execFileSync } = require('child_process');
const fs = require('fs'); const os = require('os'); const path = require('path');
run('style_folder', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 950 });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'openflow-sf-'));
  const base = page.url().split('#')[0];
  const ids = [];
  for (const [i, color] of ['red', 'green', 'blue'].entries()) {
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', `color=c=${color}:s=64x64`, '-frames:v', '1', path.join(dir, `p${i}.png`)]);
  }
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Pastas', template: 'blank' } });
  for (const [i, color] of ['red', 'green', 'blue'].entries()) {
    const up = await (await fetch(`${base}api/projects/${cv.id}/assets`, { method: 'POST', headers: { 'X-Filename': `p${i}.png`, 'Content-Type': 'image/png' }, body: fs.readFileSync(path.join(dir, `p${i}.png`)) })).json();
    ids.push(up.id);
  }
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Pastas', nodes: [{ id: 'sf1', type: 'style_folder', x: 40, y: 40, params: { files: ids } }] } });

  const tree = async () => (await api('/api/projects/' + cv.id)).nodes.find((n) => n.id === 'sf1').params;
  const saved = async (fn, label) => { await until(page, () => /Salvo|Saved/.test(document.querySelector('.cv-top .sv')?.textContent || ''), null, 8000).catch(() => {}); await page.waitForTimeout(250); return fn(await tree()); };

  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id);
  await page.waitForSelector('.cv-node.t-style_folder', { timeout: 10000 });
  check('arvore:tres-arquivos-na-raiz', (await page.locator('.cv-node.t-style_folder .sf-root .thumb').count()) === 3);
  check('arvore:botoes-nova-pasta-e-arquivos', (await page.locator('[data-act="new-folder"]').count()) === 1 && (await page.locator('[data-act="add-files"]').count()) === 1);

  // ---- criar uma pasta: já abre pedindo o nome; Enter confirma
  await page.locator('[data-act="new-folder"]').click();
  const nameIn = page.locator('.sf-folder .sf-name');
  await nameIn.waitFor({ timeout: 5000 });
  check('pasta:nova-pasta-pede-o-nome', (await nameIn.inputValue()).length > 0);
  await nameIn.fill('Aquarela'); await nameIn.press('Enter');
  await page.waitForSelector('.sf-folder .sf-label', { timeout: 5000 });
  check('pasta:nome-aplicado', (await page.locator('.sf-folder .sf-label').first().innerText()) === 'Aquarela');

  // ---- subpasta dentro da pasta
  await page.locator('.sf-folder [data-act="folder-sub"]').first().click();
  await page.locator('.sf-folder .sf-name').waitFor({ timeout: 5000 });
  await page.locator('.sf-folder .sf-name').fill('Detalhes'); await page.locator('.sf-folder .sf-name').press('Enter');
  await page.waitForSelector('.sf-folder .sf-folder .sf-label', { timeout: 5000 });
  check('subpasta:criada-dentro-da-pasta', (await page.locator('.sf-folder .sf-folder .sf-label').first().innerText()) === 'Detalhes');
  let p = await saved((x) => x);
  check('subpasta:salva-no-projeto', p.folders.length === 1 && p.folders[0].name === 'Aquarela' && p.folders[0].folders.length === 1 && p.folders[0].folders[0].name === 'Detalhes');

  // ---- mover um arquivo da raiz para a subpasta (menu «Mover para…», sem arrastar)
  await page.locator('.sf-root .thumb').first().hover();
  await page.locator('.sf-root .thumb [data-act="thumb-move"]').first().click();
  const choice = page.locator('[role="menuitem"][data-to]', { hasText: 'Aquarela / Detalhes' });
  await choice.waitFor({ timeout: 5000 });
  await choice.click();
  await page.waitForTimeout(300);
  p = await saved((x) => x);
  check('mover:arquivo-sai-da-raiz-e-entra-na-subpasta', p.files.length === 2 && p.folders[0].folders[0].files.length === 1);
  check('mover:miniatura-na-subpasta', (await page.locator('.sf-folder .sf-folder .thumb').count()) === 1);

  // ---- renomear (botão de lápis e duplo clique); nomes iguais ganham « (2)»
  await page.locator('.sf-folder > .sf-head [data-act="folder-rename"]').first().click();
  await page.locator('.sf-folder .sf-name').fill('Estilo A'); await page.locator('.sf-folder .sf-name').press('Enter');
  await page.waitForSelector('.sf-folder .sf-label', { timeout: 5000 });
  check('renomear:pasta-mudou-de-nome', (await page.locator('.sf-folder .sf-label').first().innerText()) === 'Estilo A');
  await page.locator('[data-act="new-folder"]').click();
  await page.locator('.sf-folder .sf-name').first().fill('estilo a'); await page.locator('.sf-folder .sf-name').first().press('Enter');
  await page.waitForTimeout(300);
  const labels = await page.locator('.sf-tree > .sf-folder > .sf-head .sf-label').allInnerTexts();
  check('renomear:nome-repetido-vira-numerado', labels.length === 2 && labels.includes('Estilo A') && labels.includes('estilo a (2)'));
  await page.addStyleTag({ content: '#cv-dock{display:none!important}' });   // o painel flutuante do prompt cobre o nó em alguns sistemas (fontes maiores)
  await page.locator('.sf-tree > .sf-folder').nth(1).locator('.sf-label').first().dblclick();
  const dbl = page.locator('.sf-tree > .sf-folder').nth(1).locator('.sf-name').first();
  await dbl.waitFor({ timeout: 5000 });
  await dbl.fill('Luz'); await dbl.press('Enter');
  await page.waitForTimeout(300);
  check('renomear:duplo-clique-edita-o-nome', (await page.locator('.sf-tree > .sf-folder > .sf-head .sf-label').allInnerTexts()).includes('Luz'));
  await page.locator('.sf-tree > .sf-folder').first().locator('.sf-label').first().dblclick();
  const esc = page.locator('.sf-tree > .sf-folder').first().locator('.sf-name').first();
  await esc.fill('NAO'); await esc.press('Escape');
  await page.waitForTimeout(250);
  check('renomear:escape-cancela', (await page.locator('.sf-tree > .sf-folder > .sf-head .sf-label').allInnerTexts()).includes('Estilo A'));

  // ---- ligar/desligar a pasta (fica fora do estilo) e recolher
  await page.locator('.sf-tree > .sf-folder').first().locator('[data-act="folder-enable"]').first().click();
  p = await saved((x) => x);
  check('ligar:pasta-desligada-fica-no-projeto', p.folders[0].enabled === false && p.folders[1].enabled === true);
  await page.locator('.sf-tree > .sf-folder').first().locator('[data-act="folder-open"]').first().click();
  p = await saved((x) => x);
  check('recolher:estado-aberto-e-salvo', p.folders[0].open === false);
  await page.locator('.sf-tree > .sf-folder').first().locator('[data-act="folder-open"]').first().click();

  // ---- recarregar: a árvore volta igual
  await page.reload(); await page.waitForSelector('.cv-node.t-style_folder', { timeout: 10000 });
  check('recarregar:arvore-igual', (await page.locator('.sf-tree > .sf-folder > .sf-head .sf-label').allInnerTexts()).join('|') === 'Estilo A|Luz' && (await page.locator('.sf-folder .sf-folder .sf-label').count()) === 1);

  // ---- apagar a pasta (com arquivos): pede confirmação; a subpasta vai junto; o arquivo continua no projeto
  await page.locator('.sf-tree > .sf-folder').first().locator('[data-act="folder-delete"]').first().click();
  await page.locator('.modal-bg .btn.danger, .modal-bg .btn.primary').last().click();
  await page.waitForTimeout(400);
  p = await saved((x) => x);
  const proj = await api('/api/projects/' + cv.id);
  check('apagar:pasta-e-subpasta-saem', p.folders.length === 1 && p.folders[0].name === 'Luz');
  check('apagar:arquivo-continua-no-projeto', proj.assets.length === 3);

  // ---- soltar arquivos do computador direto numa pasta
  const fileIn = page.locator('.sf-tree > .sf-folder').first().locator('input[type=file]').first();
  await fileIn.setInputFiles(path.join(dir, 'p0.png'));
  await page.waitForTimeout(900);
  p = await saved((x) => x);
  check('enviar:arquivo-vai-para-a-pasta-certa', p.folders[0].files.length === 1 && (await api('/api/projects/' + cv.id)).assets.length === 4);
});
