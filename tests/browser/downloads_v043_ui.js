// v0.43 — acompanhar os downloads de modelos dentro do Canvas: o botão ao lado direito da barra de pesquisa mostra quantos estão rodando (e uma barrinha geral), abre um painel com o progresso de cada um
// (tamanho, velocidade, tempo restante, cancelar) e os recentes; some o aviso quando não há nada rodando; funciona também em tela de celular.
const { run } = require('./_common.js');
run('downloads_v043', async ({ api, open, check }) => {
  const page = await open({ width: 1500, height: 950 });
  const json = (route, body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  const state = { tick: 0, cancelled: [] };
  const GB = 2 ** 30, MB = 2 ** 20;   // (1 << 32 estoura em JS)
  const job = (over) => ({ id: 'j1', kind: 'download', label: 'Modelo', title: 'qwen-image-2.1-step90000-Q4_K_M.gguf', repo: 'chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized', status: 'running', created: 1, done: GB, total: 4 * GB, speed: 50 * MB, eta: 60, note: '', error: '', ...over });
  await page.route('**/api/library/downloads', (r) => {
    state.tick++;
    const list = state.phase === 'idle' ? [] : state.phase === 'done' ? [job({ status: 'done', done: 4 * GB }), job({ id: 'j3', status: 'error', title: 'vae.safetensors', error: 'sem espaço em disco' })]
      : [job({ done: Math.min(4 * GB, (1 + state.tick) * 256 * MB) }), job({ id: 'j2', title: 'Qwen3-VL-8B-Instruct-UD-Q4_K_XL.gguf', repo: 'unsloth/Qwen3-VL-8B-Instruct-GGUF', done: 0, total: 0, speed: 0, eta: 0 })];
    json(r, { downloads: list, running: list.filter((d) => d.status === 'running').length });
  });
  await page.route('**/api/jobs/j1/cancel', (r) => { state.cancelled.push('j1'); state.phase = 'done'; json(r, { ok: true }); });
  state.phase = 'idle';
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Downloads', template: 'blank' } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('#cv-dl-btn', { timeout: 15000 }); await page.waitForTimeout(600);
  // posição: logo à direita da barra de pesquisa de modelos
  const pos = await page.evaluate(() => { const a = document.querySelector('.cv-top .cv-hub').getBoundingClientRect(), b = document.querySelector('#cv-dl-btn').getBoundingClientRect(); return { right: b.left >= a.right - 2, sameRow: Math.abs((a.top + a.height / 2) - (b.top + b.height / 2)) < 30 }; });
  check('botao:ao-lado-direito-da-barra-de-pesquisa', pos.right && pos.sameRow);
  check('sem-download:sem-contador', await page.locator('#cv-dl-badge.hidden').count() === 1);
  await page.locator('#cv-dl-btn').click(); await page.waitForSelector('#cv-dl-panel:not(.hidden)', { timeout: 3000 });
  check('painel:vazio-explica', /Nenhum download em andamento|No download in progress/.test(await page.locator('#cv-dl-panel').innerText()));
  await page.keyboard.press('Escape'); await page.waitForTimeout(150);
  check('painel:fecha-com-esc', await page.locator('#cv-dl-panel.hidden').count() === 1);
  // começa um download: o contador aparece sozinho (sem abrir nada)
  state.phase = 'run';
  await page.waitForSelector('#cv-dl-badge:not(.hidden)', { timeout: 8000 });
  check('rodando:contador-mostra-2', (await page.locator('#cv-dl-badge').innerText()) === '2');
  check('rodando:botao-destacado-e-barra-geral', (await page.locator('#cv-dl-btn.busy').count()) === 1 && parseInt(await page.locator('.cv-dl-bar > i').evaluate((e) => e.style.width), 10) > 0);
  await page.locator('#cv-dl-btn').click(); await page.waitForSelector('.cv-dl-row.run', { timeout: 3000 });
  const txt = await page.locator('#cv-dl-panel').innerText();
  check('painel:mostra-nome-repo-e-progresso', /qwen-image-2\.1-step90000-Q4_K_M\.gguf/.test(txt) && /chatrlabs\/Qwen-Image-2\.1/.test(txt) && /%/.test(txt) && /GB/.test(txt));
  check('painel:velocidade-e-tempo-restante', /50 MB\/s/.test(txt));
  check('painel:sem-total-diz-preparando', /Preparando|Preparing/.test(await page.locator('.cv-dl-row[data-job="j2"]').innerText()));
  const w1 = parseInt(await page.locator('.cv-dl-row[data-job="j1"] .bar > i').evaluate((e) => e.style.width), 10);
  await page.waitForTimeout(2500);
  const w2 = parseInt(await page.locator('.cv-dl-row[data-job="j1"] .bar > i').evaluate((e) => e.style.width), 10);
  check('painel:progresso-anda-sozinho', w2 > w1);
  // cancelar
  await page.locator('.cv-dl-row[data-job="j1"] [data-act="cancel"]').click(); await page.waitForTimeout(1500);
  check('cancelar:chama-a-api', state.cancelled.includes('j1'));
  check('recentes:concluido-e-falha-com-motivo', (await page.locator('.cv-dl-row[data-status="done"]').count()) === 1 && /sem espaço em disco/.test(await page.locator('.cv-dl-row[data-status="error"]').innerText()));
  check('recentes:sem-contador', await page.locator('#cv-dl-badge.hidden').count() === 1);
  // evento do painel de busca faz o indicador atualizar na hora
  const before = state.tick; await page.evaluate(() => window.dispatchEvent(new CustomEvent('flow:downloads'))); await page.waitForTimeout(400);
  check('evento-flow-downloads:atualiza-na-hora', state.tick > before);
  // celular: o painel cabe na tela
  await page.setViewportSize({ width: 390, height: 800 }); await page.waitForTimeout(400);
  const fit = await page.evaluate(() => { const r = document.querySelector('#cv-dl-panel').getBoundingClientRect(); return { open: !document.querySelector('#cv-dl-panel').classList.contains('hidden'), inside: r.left >= 0 && r.right <= window.innerWidth + 1, noScroll: document.documentElement.scrollWidth - document.documentElement.clientWidth <= 2 }; });
  check('celular:painel-cabe-na-tela', fit.open && fit.inside && fit.noScroll);
});
