// v0.64 — o nó Voz ganha a caixa «Como é a voz» logo abaixo do texto que será falado (e a Dublagem tem a mesma caixa para a voz dela); o que se digita é salvo, e rodar o nó com a voz Demo gera o áudio.
const { run, until } = require('./_common.js');
run('voice_style_v064', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 1000 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Estilo de voz', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Estilo de voz', nodes: [
    { id: 'v', type: 'voice', x: 20, y: 40, params: { text: 'Bom dia a todos, vamos começar a reunião de hoje.', voice: 'x' } },
    { id: 'd', type: 'dub', x: 520, y: 40, params: { language: 'keep' } }], edges: [] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node[data-id="d"]', { timeout: 10000 }); await page.waitForTimeout(700);
  const boxes = page.locator('.cv-node[data-id="v"] textarea');
  check('voz:duas-caixas-de-texto', (await boxes.count()) === 2);
  const first = await boxes.nth(0).getAttribute('placeholder'), second = await boxes.nth(1).getAttribute('placeholder');
  check('voz:primeira-caixa-e-o-texto-falado', /vai dizer|will say/i.test(first || ''));
  check('voz:segunda-caixa-e-a-descricao', /grave|deep/i.test(second || ''));
  const y1 = (await boxes.nth(0).boundingBox()).y, y2 = (await boxes.nth(1).boundingBox()).y;
  check('voz:descricao-fica-abaixo-do-texto', y2 > y1);
  check('voz:rotulo-como-e-a-voz', /Como é a voz|What the voice is like/.test(await page.locator('.cv-node[data-id="v"] .bd').innerText()));
  check('dublagem:tem-a-mesma-caixa', /Como é a voz|What the voice is like/.test(await page.locator('.cv-node[data-id="d"] .bd').innerText()));
  // digita a descrição: é salva no projeto
  await boxes.nth(1).fill('voz grave e lenta, de narrador'); await page.waitForTimeout(1200);
  let proj = await api(`/api/projects/${cv.id}`);
  check('voz:descricao-salva', proj.nodes.find((n) => n.id === 'v').params.voice_style === 'voz grave e lenta, de narrador');
  // roda o nó Voz (Demo): gera o áudio e a Demo não avisa que ignorou a descrição
  await page.evaluate(() => { const b = [...document.querySelectorAll('.cv-node[data-id="v"] button')].find((e) => /Executar|Run/i.test(e.title)); if (b) b.click(); });
  await until(page, () => !document.querySelector('.cv-root.running'), null, 60000);
  await page.waitForSelector('.cv-node[data-id="v"] audio', { timeout: 20000 });
  proj = await api(`/api/projects/${cv.id}`);
  const res = proj.nodes.find((n) => n.id === 'v').result;
  check('voz:audio-gerado', res.state === 'done' && res.assets.length === 1 && proj.assets.find((a) => a.id === res.assets[0]).mime === 'audio/wav');
  check('sem-erros-na-pagina', errs.length === 0);
});
