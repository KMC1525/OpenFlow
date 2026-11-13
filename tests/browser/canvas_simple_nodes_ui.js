// v0.17.1 — nós de mídia do Canvas: só Provedor, Modelo e Resolução (sem o bloco «Avançado»).
const { run } = require('./_common.js');
run('canvas_simple_nodes', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 1000 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Simples', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Simples', edges: [], nodes: [
    { id: 'im', type: 'image', x: 20, y: 20, params: { negative: 'borrado', seed: 5, extra: { quality: 'high' }, size: '1280x720' } },
    { id: 'vi', type: 'video', x: 360, y: 20, params: {} }, { id: 'so', type: 'sound', x: 700, y: 20, params: {} }, { id: 'vo', type: 'voice', x: 1040, y: 20, params: {} }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node', { timeout: 10000 }); await page.waitForTimeout(500);
  const text = async (id) => page.locator(`.cv-node[data-id="${id}"]`).innerText();
  const labels = async (id) => page.locator(`.cv-node[data-id="${id}"] label.f`).allInnerTexts();
  const li = await labels('im'), lv = await labels('vi'), ls = await labels('so');
  check('imagem:so-modelo-e-resolucao-sem-provedor', !li.some((x) => /Provedor|Provider/.test(x)) && li.some((x) => /Modelo|Model/.test(x)) && li.some((x) => /Resolução|Resolution/.test(x)));
  check('video:modelo-e-resolucao-sem-provedor', !lv.some((x) => /Provedor|Provider/.test(x)) && lv.some((x) => /Resolução|Resolution/.test(x)) && lv.some((x) => /Modelo|Model/.test(x)));
  check('som:so-modelo-sem-resolucao', ls.some((x) => /Modelo|Model/.test(x)) && !ls.some((x) => /Resolução|Resolution/.test(x)));
  const all = (await text('im')) + (await text('vi')) + (await text('so')) + (await text('vo'));
  check('sem-bloco-avancado', !/Avançado|Advanced|Prompt negativo|Negative prompt|Parâmetros extras|Extra parameters|Semente|Seed|Ignorar estilos|Ignore global/.test(all) && (await page.locator('.cv-node textarea.mono').count()) === 0);
  check('imagem:resolucao-mostra-proporcao', /1280×720 \(16:9\)/.test(await page.locator('.cv-node[data-id="im"]').innerHTML().then((h) => h.replace(/<[^>]+>/g, ' '))));
  // trocar a resolução do vídeo salva no servidor
  const sel = page.locator('.cv-node[data-id="vi"] select').filter({ has: page.locator('option[value="720"]') });
  await sel.selectOption('720'); await page.waitForTimeout(1500);
  const saved = (await api(`/api/projects/${cv.id}`)).nodes.find((n) => n.id === 'vi');
  check('video:resolucao-salva', saved.params.resolution === 720);
  // o que estava salvo antes continua no canvas
  const img = (await api(`/api/projects/${cv.id}`)).nodes.find((n) => n.id === 'im');
  check('canvas-antigo:valores-escondidos-continuam-salvos', img.params.negative === 'borrado' && img.params.seed === 5 && img.params.extra.quality === 'high' && img.params.size === '1280x720');
});
