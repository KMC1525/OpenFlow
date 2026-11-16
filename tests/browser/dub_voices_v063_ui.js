// v0.63 — a Dublagem tem a entrada «Vozes» (nós Voz ligados, um por personagem), a escolha «Como escolher a voz de cada fala» e o nó Voz ligado à Dublagem roda sem texto sem dar erro.
const { run, until } = require('./_common.js');
run('dub_voices_v063', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 1000 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Vozes', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Vozes', nodes: [
    { id: 't', type: 'text', x: 20, y: 40, params: { text: 'Maria: Bom dia!\nJoão: Bom dia, tudo bem?' } },
    { id: 'a', type: 'voice', title: 'Maria', x: 20, y: 300, params: { voice: 'tara', speed: 1.1 } },
    { id: 'b', type: 'voice', title: 'João', x: 20, y: 640, params: { voice: 'leo', speed: 0.9 } },
    { id: 'd', type: 'dub', x: 460, y: 40, params: { language: 'keep' } }],
    edges: [{ id: 'e1', from: 't', to: 'd', port: 'script' }, { id: 'e2', from: 'a', to: 'd', port: 'voices' }, { id: 'e3', from: 'b', to: 'd', port: 'voices' }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node[data-id="d"]', { timeout: 10000 }); await page.waitForTimeout(700);
  const ports = await page.locator('.cv-node[data-id="d"] .ports').innerText();
  check('dublagem:porta-vozes', /Vozes|Voices/.test(ports));
  check('dublagem:escolha-da-voz-por-fala', (await page.locator('.cv-node[data-id="d"] select').count()) >= 5);
  check('voz:dica-de-personagem', /Dublagem|Dubbing/.test(await page.locator('.cv-node[data-id="a"] .bd').innerText()));
  // roda só o nó Voz «Maria» (sem texto): é só a voz da Dublagem, não é erro
  await page.evaluate(() => { const b = [...document.querySelectorAll('.cv-node[data-id="a"] button')].find((e) => /Executar|Run/i.test(e.title)); if (b) b.click(); });
  await until(page, () => !document.querySelector('.cv-root.running'), null, 60000); await page.waitForTimeout(600);
  const proj = await api(`/api/projects/${cv.id}`);
  const st = (id) => proj.nodes.find((n) => n.id === id).result;
  check('dublagem:duas-conexoes-na-porta-vozes', proj.edges.filter((e) => e.to === 'd' && e.port === 'voices').length === 2);
  check('voz:sem-texto-nao-e-erro', st('a').state === 'done' && !st('a').error && st('a').assets.length === 0);
  check('dublagem:nao-rodou-sozinha', st('d').state !== 'running');
  check('sem-erros-na-pagina', errs.length === 0);
});
