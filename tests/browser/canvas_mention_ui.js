// v0.17.2 — «@» nos prompts do nó Imagem: lista as imagens do canvas, insere o apelido, mostra as fichas e salva.
const { run } = require('./_common.js');
const { execFileSync } = require('child_process');
const fs = require('fs'); const os = require('os'); const path = require('path');
run('canvas_mention', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 1000 });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'flow-men-'));
  const base = page.url().split('#')[0];
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Menções', template: 'blank' } });
  for (const [name, color] of [['fnaf-1-office.png', 'red'], ['Foto Perfil.png', 'blue']]) {
    const f = path.join(dir, name); execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', `color=c=${color}:s=64x64`, '-frames:v', '1', f]);
    await fetch(`${base}api/projects/${cv.id}/assets`, { method: 'POST', headers: { 'X-Filename': encodeURIComponent(name), 'Content-Type': 'image/png' }, body: fs.readFileSync(f) });
  }
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Menções', edges: [], nodes: [{ id: 'im', type: 'image', x: 20, y: 20, params: {} }, { id: 'vi', type: 'video', x: 400, y: 20, params: {} }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node', { timeout: 10000 }); await page.waitForTimeout(500);
  const ta = page.locator('.cv-node[data-id="im"] .mwrap textarea');
  check('prompt-de-imagem-e-video-aceitam-menção', (await ta.count()) === 1 && (await page.locator('.cv-node[data-id="vi"] .mwrap textarea').count()) === 1);
  await ta.click(); await ta.pressSequentially('fundo @fn');
  await page.waitForSelector('.mpop:not(.hidden) .mi[data-slug]', { timeout: 5000 });
  check('lista-filtra-pelo-apelido', (await page.locator('.mpop .mi[data-slug]').count()) === 1 && (await page.locator('.mpop .mi[data-slug="fnaf-1-office"]').count()) === 1);
  await page.keyboard.press('Enter'); await page.waitForTimeout(200);
  check('enter-insere-o-apelido', (await ta.inputValue()) === 'fundo @fnaf-1-office ');
  await ta.pressSequentially('e @'); await page.waitForSelector('.mpop:not(.hidden) .mi[data-slug]', { timeout: 5000 });
  check('arroba-sozinho-lista-todas', (await page.locator('.mpop .mi[data-slug]').count()) === 2);
  const order = await page.locator('.mpop .mi[data-slug]').evaluateAll((els) => els.map((e) => e.dataset.slug));
  check('lista-da-mais-nova-para-a-mais-antiga', order.join() === 'foto-perfil,fnaf-1-office');
  await page.keyboard.press('ArrowDown'); await page.keyboard.press('Tab'); await page.waitForTimeout(200);
  check('seta-e-tab-escolhem-a-segunda', (await ta.inputValue()).endsWith('e @fnaf-1-office '));
  await ta.pressSequentially('@'); await page.waitForSelector('.mpop:not(.hidden) .mi[data-slug]', { timeout: 5000 });
  await page.keyboard.press('Enter'); await page.waitForTimeout(200);
  check('enter-escolhe-a-primeira', (await ta.inputValue()).endsWith('@fnaf-1-office @foto-perfil '));
  await ta.pressSequentially('@fantasma'); await page.keyboard.press('Escape'); await page.waitForTimeout(200);
  check('esc-fecha-a-lista', (await page.locator('.mpop:not(.hidden)').count()) === 0);
  check('fichas-das-citadas-e-aviso-da-inexistente', (await page.locator('.mchip:not(.bad)').count()) === 2 && (await page.locator('.mchip.bad').count()) === 1);
  await page.waitForTimeout(1500);
  const saved = (await api(`/api/projects/${cv.id}`)).nodes.find((n) => n.id === 'im');
  check('prompt-salvo-com-as-menções', saved.params.prompt === 'fundo @fnaf-1-office e @fnaf-1-office @foto-perfil @fantasma');
  const h0 = await ta.evaluate((e) => e.clientHeight);
  await ta.fill(Array.from({ length: 14 }, (_, i) => 'linha ' + i + ' @foto-perfil').join('\n')); await page.waitForTimeout(250);
  const h1 = await ta.evaluate((e) => e.clientHeight);
  check('campo-cresce-com-o-texto-em-vez-de-esconde-lo', h1 > h0 + 60 && h1 <= 330);

  // ---- v0.17.4: nó Texto e vídeos/sons
  const cv2 = await api('/api/projects', { method: 'POST', body: { name: 'Menções 2', template: 'blank' } });
  const mp4 = path.join(dir, 'Cena Teste.mp4'), wav = path.join(dir, 'chuva.wav'), png = path.join(dir, 'praia.png');
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc=d=2:s=96x96:r=10', '-pix_fmt', 'yuv420p', mp4]);
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=f=300:d=1', wav]);
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'color=c=green:s=64x64', '-frames:v', '1', png]);
  for (const [f, name, type] of [[png, 'praia.png', 'image/png'], [mp4, 'Cena Teste.mp4', 'video/mp4'], [wav, 'chuva.wav', 'audio/wav']]) await fetch(`${base}api/projects/${cv2.id}/assets`, { method: 'POST', headers: { 'X-Filename': encodeURIComponent(name), 'Content-Type': type }, body: fs.readFileSync(f) });
  await api(`/api/projects/${cv2.id}`, { method: 'PUT', body: { name: 'Menções 2', edges: [], nodes: [{ id: 'tx', type: 'text', x: 20, y: 20, params: {} }, { id: 'li', type: 'llm', x: 400, y: 20, params: {} }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv2.id); await page.waitForSelector('.cv-node.t-text', { timeout: 10000 }); await page.waitForTimeout(600);
  const tx = page.locator('.cv-node[data-id="tx"] .mwrap textarea');
  check('no-texto-e-no-texto-ia-aceitam-menção', (await tx.count()) === 1 && (await page.locator('.cv-node[data-id="li"] .mwrap textarea').count()) === 1);
  await tx.click(); await tx.pressSequentially('fundo @');
  await page.waitForSelector('.mpop:not(.hidden) .mi[data-slug]', { timeout: 5000 });
  const kinds = await page.locator('.mpop .mi[data-slug]').evaluateAll((els) => els.map((e) => e.dataset.slug + ':' + (e.querySelector('video') ? 'video' : e.querySelector('.aud') ? 'audio' : 'image')));
  check('lista-mostra-imagem-video-e-som', kinds.length === 3 && kinds.includes('praia:image') && kinds.includes('cena-teste:video') && kinds.includes('chuva:audio'));
  await tx.pressSequentially('cena'); await page.keyboard.press('Enter'); await page.waitForTimeout(200);
  await tx.pressSequentially('e @chuva '); await page.keyboard.press('Escape'); await page.waitForTimeout(500);
  check('fichas-de-video-e-som', (await page.locator('.cv-node[data-id="tx"] .mchip.video').count()) === 1 && (await page.locator('.cv-node[data-id="tx"] .mchip.audio').count()) === 1);
  await page.waitForTimeout(1300);
  check('texto-salvo-com-as-menções', (await api(`/api/projects/${cv2.id}`)).nodes.find((n) => n.id === 'tx').params.text === 'fundo @cena-teste e @chuva');
  fs.rmSync(dir, { recursive: true, force: true });
});
