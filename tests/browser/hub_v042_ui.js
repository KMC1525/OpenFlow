// v0.42 — pesquisar/baixar modelos é só na barra de pesquisa do Canvas: recomendados (catálogo e prontos para instalar), repositório direto (dono/nome), formato GGUF ou Original (imagem e vídeo),
// o texto só GGUF; a Biblioteca não tem mais busca nem download; os ajustes dos downloads (conexões, token, arquivos de apoio) estão em Configurações → Desempenho.
const { run } = require('./_common.js');
run('hub_v042', async ({ api, open, check }) => {
  const page = await open({ width: 1500, height: 950 });
  const json = (route, body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  const seen = { search: [] };
  await page.route('**/api/media/hub/search*', (r) => { const u = r.request().url(); seen.search.push(u); const fmt = new URL(u).searchParams.get('format'); json(r, { results: fmt === 'original' ? [{ id: 'acme/diffusers-model', downloads: 900, likes: 5 }] : [], format: fmt, cap: 'image' }); });
  await page.route('**/api/hf/files*', (r) => json(r, { files: [{ name: 'qwen-image-2.1-step90000-Q4_K_M.gguf', quant: 'Q4_K_M', bits: 4, quality: 'good', size: 4474346272, parts: 1, files: ['qwen-image-2.1-step90000-Q4_K_M.gguf'], sizes: { 'qwen-image-2.1-step90000-Q4_K_M.gguf': 4474346272 }, fits: true, recommended: true }],
    support: [{ role: 'vae', label: 'VAE do Qwen-Image 2.1', size: 680000000 }, { role: 'text_encoder', label: 'Qwen3-VL-8B', size: 5100000000 }], compat: null }));
  await page.route('**/api/hf/local*', (r) => json(r, { models: [], kinds: {} }));
  await page.route('**/api/media/local/**', (r) => json(r, { options: [{ id: 'fp16', size: 1000, recommended: true }], variants: [], libs: true, models: {} }));
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Barra', template: 'blank' } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('#hub-q', { timeout: 15000 });
  // clicar na barra mostra os recomendados (catálogo GGUF e os prontos para instalar)
  await page.locator('#hub-q').focus(); await page.waitForSelector('#hub-recs', { timeout: 8000 });
  await page.waitForSelector('.hub-rec[data-repo="chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized"]', { timeout: 8000 });
  check('recomendados:catalogo-com-chatrlabs', (await page.locator('.hub-rec[data-repo^="unsloth/"]').count()) >= 5 && (await page.locator('.hub-rec[data-repo^="chatrlabs/"]').count()) === 1);
  check('recomendados:prontos-para-instalar', (await page.locator('[data-act="preinstall"], #hub-recs .chip.on:has-text("Instalado"), #hub-recs .chip.on:has-text("Installed")').count()) >= 1);
  // «Ver quantizações» pesquisa o repositório (GGUF)
  await page.locator('.hub-rec[data-repo="chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized"] [data-act="rec-open"]').click(); await page.waitForTimeout(500);
  check('recomendados:ver-quantizacoes-pesquisa-o-repositorio', seen.search.some((u) => u.includes('q=chatrlabs%2FQwen-Image-2.1-Uncensored-Omni-Quantized') && u.includes('format=gguf')));
  check('repositorio-direto:aparece-mesmo-sem-resultado', (await page.locator('.hub-r[data-repo="chatrlabs/Qwen-Image-2.1-Uncensored-Omni-Quantized"]').count()) === 1);
  await page.waitForSelector('.hub-q[data-quant="Q4_K_M"]', { timeout: 8000 });
  check('quantizacoes:vem-junto-o-vae-e-o-codificador', (await page.locator('.hub-detail .comes .chip').count()) === 2);
  // formatos: imagem e vídeo escolhem GGUF ou Original; texto só GGUF; som/voz/transcrição/3D só Original
  check('formato:imagem-escolhe', !(await page.locator('#hub-fmt').isDisabled()));
  await page.selectOption('#hub-fmt', 'original'); await page.waitForTimeout(200);
  await page.fill('#hub-q', 'diffusers'); await page.keyboard.press('Enter');
  await page.waitForSelector('.hub-r[data-repo="acme/diffusers-model"]', { timeout: 8000 });
  check('formato:imagem-original-pesquisa-sem-gguf', seen.search[seen.search.length - 1].includes('format=original') && seen.search[seen.search.length - 1].includes('cap=image'));
  await page.selectOption('#hub-cap', 'video'); await page.waitForTimeout(200);
  check('formato:video-escolhe', !(await page.locator('#hub-fmt').isDisabled()));
  await page.selectOption('#hub-cap', 'text'); await page.waitForTimeout(200);
  check('formato:texto-so-gguf', (await page.locator('#hub-fmt').isDisabled()) && (await page.locator('#hub-fmt').inputValue()) === 'gguf');
  for (const cap of ['sound', 'voice', 'stt', 'model3d']) { await page.selectOption('#hub-cap', cap); await page.waitForTimeout(150); check('formato:' + cap + '-so-original', (await page.locator('#hub-fmt').isDisabled()) && (await page.locator('#hub-fmt').inputValue()) === 'original'); }
  // endereço dono/nome colado na barra
  await page.selectOption('#hub-cap', 'image'); await page.selectOption('#hub-fmt', 'original');
  await page.fill('#hub-q', 'acme/outro-modelo'); await page.keyboard.press('Enter');
  await page.waitForSelector('.hub-r[data-repo="acme/outro-modelo"]', { timeout: 8000 });
  check('endereco:dono-nome-direto', (await page.locator('.hub-r[data-repo="acme/outro-modelo"]').count()) === 1);
  // outras partes do app pedem a busca pelo evento
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('flow:hub', { detail: { q: 'acme/via-evento', cap: 'image', fmt: 'gguf' } }))); await page.waitForTimeout(500);
  check('evento-flow-hub:abre-a-busca-no-repositorio', seen.search.some((u) => u.includes('q=acme%2Fvia-evento') && u.includes('format=gguf')));
  // Biblioteca: sem busca nem download de modelos
  await page.evaluate(() => { location.hash = '#/library'; }); await page.waitForSelector('#lib-tab-models', { timeout: 8000 }); await page.waitForTimeout(500);
  check('biblioteca:sem-baixar-mais-modelos', (await page.locator('#lib-get').count()) === 0 && !/Baixar mais modelos|Download more models/i.test(await page.locator('body').innerText()));
  await page.evaluate(() => { location.hash = '#/models'; }); await page.waitForTimeout(500);
  check('endereco-antigo-models:vai-para-a-biblioteca', (await page.locator('#lib-tab-models').count()) === 1 && (await page.locator('#md-unsloth').count()) === 0);
  // ajustes dos downloads em Configurações → Desempenho
  await page.evaluate(() => { location.hash = '#/settings'; }); await page.waitForSelector('.cfgtabs button', { timeout: 8000 });
  await page.locator('.cfgtabs button').nth(4).click(); await page.waitForSelector('#md-conn', { timeout: 8000 });
  await page.selectOption('#md-conn', '6'); await page.waitForTimeout(500);
  check('configuracoes:conexoes-por-download-salva', (await api('/api/settings')).hf.connections === 6);
  check('configuracoes:token-do-hugging-face', (await page.locator('#hf-token').count()) === 1 && (await page.locator('#hf-token-save').count()) === 1);
});
