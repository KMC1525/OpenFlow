// v0.65 — a barra de pesquisa de modelos do Canvas para SOM: o seletor «Assunto» (música, efeitos…), a lista que já abre com os mais baixados, o selo «Roda no OpenFlow» / «Ainda não roda» e o «Usar» bloqueado
// para o que o OpenFlow não roda. O Hugging Face é simulado pelo próprio Chromium (as respostas de /api/media/hub/* e /api/media/local/*): a rede de verdade não é usada.
const { run, until } = require('./_common.js');
const MUSIC = [
  { id: 'facebook/musicgen-medium', downloads: 2000000, likes: 179, cap: 'sound', format: 'original', topic: 'music', topics: ['music'], library: 'transformers', compat: { level: 'ok', reason: 'Família MusicGen: o OpenFlow tem suporte (usa a biblioteca transformers).' } },
  { id: 'ACE-Step/Ace-Step1.5', downloads: 103900, likes: 972, cap: 'sound', format: 'original', topic: 'music', topics: ['music'], library: 'transformers', compat: { level: 'no', reason: 'O OpenFlow roda MusicGen; este modelo não roda (ele precisa de código próprio do repositório).' } }];
const SFX = [{ id: 'OpenMOSS-Team/MOSS-SoundEffect-v2.0', downloads: 6700, likes: 159, cap: 'sound', format: 'original', topic: 'sfx', topics: ['sfx'], library: 'diffusers', compat: { level: 'no', reason: 'O OpenFlow roda MusicGen; este modelo não roda (ele usa a biblioteca «diffusers»).' } }];
run('sound_search_v065', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 1000 });
  const errs = [];
  page.on('pageerror', (e) => errs.push(String(e)));
  const calls = [];
  await page.route('**/api/media/hub/search**', (route) => {
    const u = new URL(route.request().url()); calls.push({ q: u.searchParams.get('q'), cap: u.searchParams.get('cap'), topic: u.searchParams.get('topic'), format: u.searchParams.get('format') });
    const topic = u.searchParams.get('topic');
    route.fulfill({ contentType: 'application/json', body: JSON.stringify({ results: topic === 'sfx' ? SFX : MUSIC, format: 'original', cap: 'sound', topic }) });
  });
  await page.route('**/api/media/local/options**', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ options: [{ id: 'fp16', size: 3000000000, recommended: true, note: 'Metade do tamanho' }] }) }));
  await page.route('**/api/media/local/quants**', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ variants: [] }) }));
  await page.route('**/api/media/local/state', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ libs: true, models: { sound: { model: 'ACE-Step/Ace-Step1.5', precision: 'fp16' }, voice: {}, stt: {} } }) }));
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Busca de som', template: 'blank' } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('#hub-q', { timeout: 10000 }); await page.waitForTimeout(500); await page.focus('#hub-q'); await page.waitForSelector('#hub-cap', { timeout: 10000 });
  // imagem: nada de assunto
  check('imagem:sem-seletor-de-assunto', await page.locator('#hub-topic-label.hidden').count() === 1);
  // som: o seletor aparece e a lista abre sozinha com os mais baixados do assunto
  await page.selectOption('#hub-cap', 'sound'); await page.waitForTimeout(400);
  check('som:seletor-de-assunto-visivel', await page.locator('#hub-topic-label.hidden').count() === 0);
  const labels = await page.locator('#hub-topic option').allInnerTexts();
  check('som:tres-assuntos', labels.length === 3 && /Música|Music/.test(labels[0]) && /SFX/.test(labels[1]));
  await page.focus('#hub-q'); await page.waitForSelector('.hub-r', { timeout: 10000 });
  check('som:abriu-sozinha-sem-digitar', calls.length >= 1 && calls[calls.length - 1].topic === 'music' && calls[calls.length - 1].q === '' && calls[calls.length - 1].cap === 'sound');
  const rows = await page.locator('.hub-r').count();
  check('som:resultados-listados', rows === 2);
  const compat = await page.locator('.hub-r [data-compat]').evaluateAll((els) => els.map((e) => e.dataset.compat));
  check('som:selos-de-compatibilidade', compat.join() === 'ok,no');
  check('som:selo-diz-roda-ou-nao', /Roda no OpenFlow|Runs in OpenFlow/.test(await page.locator('.hub-r').nth(0).innerText()) && /Ainda não roda|does not run/i.test(await page.locator('.hub-r').nth(1).innerText()));
  check('som:mostra-assunto-e-biblioteca', /transformers/.test(await page.locator('.hub-r').nth(0).innerText()) && (await page.locator('.hub-r [data-topic="music"]').count()) === 2);
  // outro assunto: nova consulta
  const before = calls.length;
  await page.selectOption('#hub-topic', 'sfx'); await page.waitForSelector('.hub-r[data-repo="OpenMOSS-Team/MOSS-SoundEffect-v2.0"]', { timeout: 10000 });
  check('som:trocar-assunto-consulta-de-novo', calls.length > before && calls[calls.length - 1].topic === 'sfx');
  // digitar e Enter manda o texto
  await page.selectOption('#hub-topic', 'music'); await page.waitForSelector('.hub-r[data-repo="facebook/musicgen-medium"]');
  await page.fill('#hub-q', 'musicgen'); await page.press('#hub-q', 'Enter'); await page.waitForTimeout(500);
  check('som:texto-digitado-vai-na-consulta', calls[calls.length - 1].q === 'musicgen' && calls[calls.length - 1].topic === 'music');
  // um modelo que o OpenFlow roda: «Usar» liberado; um que não roda: aviso e «Usar» bloqueado
  await page.fill('#hub-q', ''); await page.press('#hub-q', 'Enter'); await page.waitForSelector('.hub-r[data-repo="ACE-Step/Ace-Step1.5"]');
  await page.click('.hub-r[data-repo="ACE-Step/Ace-Step1.5"]'); await page.waitForSelector('.hub-detail:not(.hidden) .hub-q', { timeout: 10000 });
  check('bloqueado:aviso-com-o-motivo', /código próprio/.test(await page.locator('.hub-detail:not(.hidden) [data-blocked]').innerText()));
  check('bloqueado:usar-desabilitado', await page.locator('.hub-detail:not(.hidden) button[data-act="use"][disabled]').count() === 1);
  // voz e transcrição também têm assuntos
  await page.selectOption('#hub-cap', 'voice'); await page.waitForTimeout(400);
  const v = await page.locator('#hub-topic option').allInnerTexts();
  check('voz:quatro-assuntos-com-dublagem', v.length === 4 && v.some((x) => /Dublagem|Dubbing/.test(x)));
  await page.selectOption('#hub-cap', 'stt'); await page.waitForTimeout(400);
  check('transcricao:um-assunto-sem-seletor', await page.locator('#hub-topic-label.hidden').count() === 1);
  check('sem-erros-na-pagina', errs.length === 0);
});
