// v0.62 — nós «Dublagem», «Transcrição» e «Legendas»: aparecem na paleta (grupo Som), têm formulário próprio, e o nó Legendas, a partir de um texto + duração, gera um SRT que o botão «Baixar» entrega como arquivo.
const fs = require('fs');
const { run, until } = require('./_common.js');
run('speech_v062', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 1000 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Fala', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Fala', nodes: [
    { id: 't', type: 'text', x: 20, y: 40, params: { text: 'Primeira frase curta. Segunda frase um pouco maior que a primeira. Terceira frase.' } },
    { id: 's', type: 'sub', x: 340, y: 20, params: { format: 'srt', duration: 12 } },
    { id: 'r', type: 'transcript', x: 740, y: 20, params: {} },
    { id: 'd', type: 'dub', x: 1100, y: 20, params: { language: 'en', mix: 'duck' } }],
    edges: [{ id: 'e1', from: 't', to: 's', port: 'text' }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node[data-id="d"]', { timeout: 10000 }); await page.waitForTimeout(700);
  const pal = await page.locator('.cv-pal').innerText();
  check('paleta:tres-nos-novos', /Dublagem|Dubbing/.test(pal) && /Transcrição|Transcript/.test(pal) && /Legendas|Captions|Subtitles/.test(pal));
  check('legendas:formulario', (await page.locator('.cv-node[data-id="s"] select').count()) >= 4 && (await page.locator('.cv-node[data-id="s"] input[type="number"]').count()) >= 4);
  check('transcricao:formulario', (await page.locator('.cv-node[data-id="r"] select').count()) >= 3);
  check('dublagem:formulario', (await page.locator('.cv-node[data-id="d"] select').count()) >= 4 && (await page.locator('.cv-node[data-id="d"] input[type="checkbox"]').count()) >= 1);
  check('dublagem:portas', /Vídeo ou áudio|Video or audio/.test(await page.locator('.cv-node[data-id="d"] .ports').innerText()) && /Roteiro|Script/.test(await page.locator('.cv-node[data-id="d"] .ports').innerText()));
  check('legendas:portas', /Texto ou legendas|Text or subtitles|Text or captions/.test(await page.locator('.cv-node[data-id="s"] .ports').innerText()));
  // roda só o nó Legendas (texto + duração, sem modelo)
  await page.evaluate(() => { const b = [...document.querySelectorAll('.cv-node[data-id="s"] button')].find((e) => /Executar|Run/i.test(e.title)); if (b) b.click(); });
  await until(page, () => !document.querySelector('.cv-root.running'), null, 60000);
  await page.waitForSelector('.cv-node[data-id="s"] .rtxt', { timeout: 20000 });
  const shown = await page.locator('.cv-node[data-id="s"] .rtxt').innerText();
  check('legendas:srt-no-no', /00:00:00,000 --> /.test(shown) && /Primeira frase curta/.test(shown) && /^1\n/.test(shown));
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 10000 }), page.locator('.cv-node[data-id="s"] button[data-act="download-text"]').click()]);
  const file = fs.readFileSync(await dl.path(), 'utf8');
  check('baixar:nome-srt', /\.srt$/.test(dl.suggestedFilename()));
  check('baixar:conteudo-srt', /^1\n00:00:00,000 --> /.test(file) && file.endsWith('\n') && (file.match(/-->/g) || []).length >= 3);
  // VTT: o botão muda de extensão
  await page.locator('.cv-node[data-id="s"] select').first().selectOption('vtt'); await page.waitForTimeout(900);
  await page.evaluate(() => { const b = [...document.querySelectorAll('.cv-node[data-id="s"] button')].find((e) => /Executar|Run/i.test(e.title)); if (b) b.click(); });
  await until(page, () => !document.querySelector('.cv-root.running'), null, 60000); await page.waitForTimeout(500);
  const [dl2] = await Promise.all([page.waitForEvent('download', { timeout: 10000 }), page.locator('.cv-node[data-id="s"] button[data-act="download-text"]').click()]);
  check('baixar:nome-vtt', /\.vtt$/.test(dl2.suggestedFilename()) && fs.readFileSync(await dl2.path(), 'utf8').startsWith('WEBVTT'));
  check('sem-erros-na-pagina', errs.length === 0);
});
