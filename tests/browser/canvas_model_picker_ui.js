// v0.17.3 — seletor de modelo dos nós: instalados neste computador e sugeridos; escolher um instalado troca também o provedor.
const { run } = require('./_common.js');
run('canvas_model_picker', async ({ api, open, check }) => {
  const page = await open({ width: 1600, height: 1000 });
  const json = (route, body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/media/installed*', (r) => json(r, { cap: 'image', items: [
    { provider: 'gguf_local', model: 'z-image-Q4_K_M.gguf', label: 'z-image-Q4_K_M.gguf', size: 3500000000, detail: 'Q4_K_M · GGUF' },
    { provider: 'local_hf', model: 'stabilityai/sd-turbo', label: 'stabilityai/sd-turbo', size: 0, detail: 'fp16 · Hugging Face local', match: true }] }));
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Modelos', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Modelos', edges: [], nodes: [{ id: 'im', type: 'image', x: 20, y: 20, params: {} }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node', { timeout: 10000 }); await page.waitForTimeout(800);
  const sel = page.locator('#mp_imim .mpick select, .cv-node[data-id="im"] .mpick select').first();
  const opts = await sel.locator('option').allTextContents();
  check('sem-seletor-de-provedor-no-no', (await page.locator('.cv-node[data-id="im"] label.f').allInnerTexts()).every((x) => !/Provedor|Provider/.test(x)) && (await page.locator('.cv-node[data-id="im"] select').count()) >= 2);
  check('seletor-no-lugar-do-campo-de-texto', (await page.locator('.cv-node[data-id="im"] .mpick select').count()) === 1);
  check('instalados-aparecem-com-detalhe', opts.some((o) => /z-image-Q4_K_M\.gguf · Q4_K_M · GGUF/.test(o)) && opts.some((o) => /stabilityai\/sd-turbo · fp16/.test(o)));
  check('grupo-instalados-neste-computador', (await sel.locator('optgroup').evaluateAll((g) => g.map((x) => x.label))).some((l) => /Instalados|Installed/.test(l)));
  // escolher um GGUF instalado troca o provedor e o modelo e salva
  await sel.selectOption({ label: opts.find((o) => /z-image/.test(o)) }); await page.waitForTimeout(1500);
  const saved = (await api(`/api/projects/${cv.id}`)).nodes.find((n) => n.id === 'im');
  check('instalado-define-provedor-e-modelo', saved.params.provider === 'gguf_local' && saved.params.model === 'z-image-Q4_K_M.gguf');
  const sel2 = page.locator('.cv-node[data-id="im"] .mpick select');
  check('selecao-fica-marcada-apos-redesenhar', (await sel2.inputValue()) === 'P|gguf_local|z-image-Q4_K_M.gguf');
  // o campo «nome do modelo» só existe enquanto «Outro modelo…» está escolhido: ↻ ou sair do campo vazio o esconde (antes ficava solto abaixo do modelo já escolhido)
  const imSel = page.locator('.cv-node[data-id="im"] .mpick select'), imFree = page.locator('.cv-node[data-id="im"] .mpick input');
  check('campo-livre-comeca-escondido', !(await imFree.isVisible()));
  await imSel.selectOption('__custom');
  check('outro-modelo-mostra-o-campo', await imFree.isVisible());
  await page.locator('.cv-node[data-id="im"] .mpick button[title]').click(); await page.waitForTimeout(800);
  check('recarregar-a-lista-esconde-o-campo-livre', !(await imFree.isVisible()));
  await imSel.selectOption('__custom'); await imFree.focus(); await page.locator('.cv-node[data-id="im"] .mpick select').focus(); await page.waitForTimeout(600);
  check('sair-do-campo-vazio-esconde-e-volta-ao-modelo', !(await imFree.isVisible()) && (await imSel.inputValue()) === 'P|gguf_local|z-image-Q4_K_M.gguf');
  // padrão
  await page.locator('.cv-node[data-id="im"] .mpick select').selectOption(''); await page.waitForTimeout(1500);
  check('padrao-limpa-o-modelo', (await api(`/api/projects/${cv.id}`)).nodes.find((n) => n.id === 'im').params.model === '');
});
