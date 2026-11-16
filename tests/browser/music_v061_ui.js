// v0.61 — nós «Música», «Letra» e «SFX»: aparecem na paleta (grupo Som), têm formulário próprio e rodam em cadeia (Texto → Letra → Música) com o provedor Demo; o SFX gera variações.
const { run, until } = require('./_common.js');
run('music_v061', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 1000 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Musica', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Musica', nodes: [
    { id: 't', type: 'text', x: 20, y: 40, params: { text: 'uma estrada de madrugada, saudade' } },
    { id: 'l', type: 'lyrics', x: 320, y: 20, params: { structure: 'short', language: 'pt' } },
    { id: 'm', type: 'music', x: 700, y: 20, params: { prompt: 'pop suave', duration: 6, seed: 3 } },
    { id: 's', type: 'sfx', x: 1080, y: 20, params: { prompt: 'trovão distante', duration: 2, variations: 2, seed: 5 } }],
    edges: [{ id: 'e1', from: 't', to: 'l', port: 'text' }, { id: 'e2', from: 'l', to: 'm', port: 'lyrics' }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node[data-id="s"]', { timeout: 10000 }); await page.waitForTimeout(700);
  const pal = await page.locator('.cv-pal').innerText();
  check('paleta:tres-nos-novos', /Música|Music/.test(pal) && /Letra|Lyrics/.test(pal) && /SFX/.test(pal));
  check('musica:formulario', (await page.locator('.cv-node[data-id="m"] textarea').count()) >= 2 && (await page.locator('.cv-node[data-id="m"] input[type="checkbox"]').count()) >= 1 && (await page.locator('.cv-node[data-id="m"] input[type="number"]').count()) >= 3);
  check('letra:formulario', (await page.locator('.cv-node[data-id="l"] select').count()) >= 4 && (await page.locator('.cv-node[data-id="l"] textarea').count()) >= 2);
  check('sfx:formulario', (await page.locator('.cv-node[data-id="s"] select').count()) >= 1 && (await page.locator('.cv-node[data-id="s"] textarea').count()) >= 1);
  check('musica:porta-letra', (await page.locator('.cv-node[data-id="m"] .ports').innerText()).match(/Letra|Lyrics/) !== null);
  await page.evaluate(() => { const b = [...document.querySelectorAll('button')].find((e) => /Executar|Run|Gerar tudo|Generate/i.test(e.textContent)); if (b) b.click(); });
  await until(page, () => !document.querySelector('.cv-root.running'), null, 90000);
  await page.waitForSelector('.cv-node[data-id="m"] audio', { timeout: 20000 });
  check('musica:tocador', (await page.locator('.cv-node[data-id="m"] audio').count()) === 1);
  check('sfx:duas-variacoes', (await page.locator('.cv-node[data-id="s"] audio').count()) === 2);
  const proj = await api(`/api/projects/${cv.id}`);
  const res = (id) => proj.nodes.find((n) => n.id === id).result;
  check('letra:texto-com-marcas', /^\[Verse 1\]/.test(res('l').text) && /\[Chorus\]/.test(res('l').text) && /estrada|saudade/.test(res('l').text));
  check('nos:todos-concluidos', ['l', 'm', 's'].every((id) => res(id).state === 'done'));
  check('arquivos:tres-audios', proj.assets.filter((a) => a.kind === 'audio' && a.mime === 'audio/wav').length === 3);
  check('musica:letra-no-arquivo', proj.assets.some((a) => a.node === 'm' && /Lyrics:/.test(a.prompt || '')));
  // instrumental pela tela: o parâmetro é salvo
  await page.locator('.cv-node[data-id="m"] input[type="checkbox"]').first().check(); await page.waitForTimeout(900);
  const after = await api(`/api/projects/${cv.id}`);
  check('musica:instrumental-salvo', after.nodes.find((n) => n.id === 'm').params.instrumental === true);
  check('sem-erros-na-pagina', errs.length === 0);
});
