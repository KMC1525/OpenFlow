// v0.83 — a interface dos recursos novos (faixas Q2–Q8, modelos próprios, card do PyTorch/TensorFlow, nó «Modelo PyTorch/TensorFlow») não passa da borda em celular, tablet e computador, em português e inglês:
// sem rolagem lateral da página, nenhum botão/campo/texto saindo do cartão, e nada de erro no console.
const { run } = require('./_common.js');
run('layout_v083', async ({ api, open, check, expectError }) => {
  expectError(/409/);   // o 409 de «Criar faixa» é provocado de propósito
  const json = (route, body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  const LONG = 'C:\\Users\\alguem-com-nome-muito-comprido\\Documentos\\modelos-de-ia\\super-resolucao\\esrgan-x4-versao-final-2026-novembro.keras';
  const REPORT = { system: 'Windows', machine: 'AMD64', python: '3.13.1', gpu_vendors: ['nvidia', 'amd', 'intel'], torch: { installed: true, version: '2.15.0+cu130', build: 'CUDA 13.0', device: 'cpu', cuda: false, devices: [] },
    tensorflow: { installed: true, version: '2.21.0', keras: '3.15.1', gpus: [], backend: 'tensorflow' },
    advice: { torch: [{ level: 'warn', text: 'Há uma placa NVIDIA neste computador, mas o PyTorch roda na CPU: é a versão só de CPU. Os modelos locais ficam muito mais lentos.', text_en: 'There is an NVIDIA card in this computer, but PyTorch runs on the CPU: it is the CPU-only build. Local models get much slower.',
      command: 'python -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu130' }], tensorflow: [{ level: 'info', text: 'O TensorFlow 2.11 ou mais novo não usa a placa de vídeo no Windows nativo (só no WSL2). Aqui ele roda na CPU.', text_en: 'TensorFlow 2.11 or newer does not use the graphics card on native Windows (WSL2 only). Here it runs on the CPU.' }] } };
  const REPO = 'unsloth/Z-Image-Turbo-GGUF';
  const tiers = [{ tier: 'Q2', has: false }, { tier: 'Q3', has: false }, { tier: 'Q4', has: true, quant: 'Q4_K_M', name: 'z-Q4_K_M.gguf', size: 3800000000, recommended: true }, { tier: 'Q6', has: false }, { tier: 'Q8', has: true, quant: 'Q8_0', name: 'z-Q8_0.gguf', size: 7000000000 }];
  const file = (name, quant, bits, tier, size) => ({ name, quant, bits, quality: 'good', size, parts: 1, files: [name], sizes: { [name]: size }, fits: true, recommended: quant === 'Q4_K_M', tier });
  const overflow = () => {
    const bad = [];
    const W = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth > W + 1) bad.push('página rola para o lado (' + document.documentElement.scrollWidth + ' > ' + W + ')');
    document.querySelectorAll('.card, .hub-q, .fw-advice, .cv-node, .lib-card').forEach((c) => {
      const b = c.getBoundingClientRect(); if (!b.width || !b.height) return;
      c.querySelectorAll('button, input, select, textarea, .chip, .codebox, h3, b').forEach((e) => {
        const r = e.getBoundingClientRect(); if (!r.width || !r.height || getComputedStyle(e).visibility === 'hidden') return;
        if (r.right > b.right + 2 && r.left < b.right) bad.push((c.className + ' → ' + e.tagName + '.' + e.className + ' ' + (e.innerText || e.value || '').slice(0, 30)).replace(/\s+/g, ' '));
      });
    });
    document.querySelectorAll('.cv-hub-panel:not(.hidden) *').forEach((e) => { const r = e.getBoundingClientRect(); if (r.width && r.right > W + 1 && getComputedStyle(e).position !== 'fixed') { bad.push('painel passa da tela: ' + e.tagName + '.' + e.className + ' ' + (e.innerText || '').slice(0, 20).replace(/\s+/g, ' ')); } });
    return bad;
  };
  for (const lang of ['pt-BR', 'en']) {
    await api('/api/settings', { method: 'PUT', body: { language: lang, media: { active: { image: 'gguf_local' } } } });
    for (const vp of [{ width: 390, height: 800 }, { width: 820, height: 900 }, { width: 1400, height: 900 }]) {
      const tag = lang + '@' + vp.width;
      const page = await open(vp);
      await page.route('**/api/media/frameworks*', (r) => json(r, REPORT));
      await page.route('**/api/media/hub/search*', (r) => json(r, { results: [{ id: REPO, downloads: 900, likes: 5, cap: 'image', format: 'gguf', frameworks: ['pytorch', 'tensorflow', 'jax', 'onnx'] }], format: 'gguf', cap: 'image' }));
      await page.route('**/api/hf/files*', (r) => json(r, { files: [file('z-Q4_K_M.gguf', 'Q4_K_M', 4, 'Q4', 3800000000), file('z-Q8_0.gguf', 'Q8_0', 8, 'Q8', 7000000000)], support: [], compat: null, tiers }));
      await page.route('**/api/hf/tiers*', (r) => json(r, { repo: REPO, tiers, alternatives: [{ repo: 'city96/un-nome-de-repositorio-bem-comprido-gguf-quantizado', downloads: 40, tiers: ['Q2', 'Q3', 'Q4'], missing_covered: ['Q2', 'Q3'] }] }));
      await page.route('**/api/hf/local*', (r) => json(r, { models: [], kinds: {} }));
      await page.route('**/api/library/items*', (r) => json(r, { folders: [], items: [{ key: 'model:image/modelo-com-nome-muito-comprido-de-verdade-Q8_0.gguf', scope: 'models', kind: 'image', name: 'modelo-com-nome-muito-comprido-de-verdade-Q8_0.gguf', size: 7000000000, quant: 'Q8_0', bits: 8, tier: 'Q8', parts: 1, mtime: 1 }], path: [], search: false }));
      // Configurações → card do PyTorch/TensorFlow
      await page.evaluate(() => { location.hash = '#/settings'; }); await page.waitForSelector('.cfgtabs button', { timeout: 10000 });
      const tabs = page.locator('.cfgtabs button'); const n = await tabs.count();
      for (let i = 0; i < n; i++) { await tabs.nth(i).click(); await page.waitForTimeout(250); if (await page.locator('#fw-body').count()) break; }
      await page.waitForSelector('#fw-torch', { timeout: 8000 }); await page.waitForTimeout(300);
      let bad = await page.evaluate(overflow);
      check(tag + ':configuracoes-card-dentro-da-tela', bad.length === 0); if (bad.length) console.error(tag, 'configuracoes', JSON.stringify(bad.slice(0, 5)));
      // Biblioteca: menu de criar faixa
      await page.evaluate(() => { location.hash = '#/library'; }); await page.waitForSelector('#lib-tab-models', { timeout: 8000 });
      await page.locator('#lib-tab-models').click(); await page.waitForSelector('.lib-card.model', { timeout: 8000 });
      await page.locator('.lib-card.model .lib-menu .btn').click(); await page.waitForTimeout(200);
      bad = await page.evaluate(() => { const o = overflow(); return o; }).catch(() => []);
      if (vp.width === 1400) {   // «Criar faixa» com outra já em andamento: mensagem de gente, não o JSON do servidor
        await page.route('**/api/hf/requant', (r) => r.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ error: JSON.stringify({ job_id: 'j_x' }) }) }));
        await page.locator('.lib-pop:not(.hidden) button', { hasText: 'Q4' }).click(); await page.waitForTimeout(500);
        const toastText = await page.locator('#toasts').innerText();
        check(tag + ':faixa-em-andamento-explica-sem-json', /sendo criada|already being created/.test(toastText) && !/job_id/.test(toastText));
        await page.locator('.lib-card.model .lib-menu .btn').click(); await page.waitForTimeout(200);
      }
      const popBox = await page.locator('.lib-pop:not(.hidden)').boundingBox();
      check(tag + ':biblioteca-menu-dentro-da-tela', !!popBox && popBox.x >= -1 && popBox.x + popBox.width <= vp.width + 1); if (!popBox || popBox.x < -1 || popBox.x + popBox.width > vp.width + 1) console.error(tag, 'menu', JSON.stringify(popBox));
      bad = await page.evaluate(overflow);
      check(tag + ':biblioteca-sem-rolagem-lateral', bad.length === 0); if (bad.length) console.error(tag, 'biblioteca', JSON.stringify(bad.slice(0, 5)));
      // Canvas: barra de pesquisa com as faixas e o nó de modelo próprio
      const cv = await api('/api/projects', { method: 'POST', body: { name: 'Layout ' + tag, template: 'blank' } });
      await api('/api/projects/' + cv.id, { method: 'PUT', body: { name: 'Layout', nodes: [{ id: 'n1', type: 'image', x: 20, y: 80, params: { provider: 'gguf_local', model: LONG } }, { id: 'n2', type: 'image', x: 20, y: 700, params: { provider: 'gguf_local', extra: { quant: 'Q4' } } }], edges: [] } });
      await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('#hub-q', { timeout: 15000 });
      await page.waitForSelector('.cv-node[data-id="n1"]', { timeout: 8000 }); await page.waitForTimeout(600);
      bad = await page.evaluate(overflow);
      check(tag + ':canvas-nos-novos-dentro-do-cartao', bad.length === 0); if (bad.length) console.error(tag, 'canvas', JSON.stringify(bad.slice(0, 5)));
      await page.locator('#hub-q').focus(); await page.waitForSelector('#hub-recs', { timeout: 8000 });
      await page.locator('.hub-rec[data-repo="' + REPO + '"] [data-act="rec-open"]').click();
      await page.waitForSelector('.tiers [data-tier="Q2"]', { timeout: 8000 });
      await page.locator('[data-act="tiers-alts"]').click(); await page.waitForSelector('.hub-q[data-alt]', { timeout: 8000 }); await page.waitForTimeout(300);
      bad = await page.evaluate(overflow);
      check(tag + ':busca-faixas-e-alternativas-dentro-da-tela', bad.length === 0); if (bad.length) console.error(tag, 'busca', JSON.stringify(bad.slice(0, 5)));
      if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT + '/' + tag + '-busca.png' });
      const barBox = await page.locator('.tiers').boundingBox();
      check(tag + ':faixas-cabem-na-largura', !!barBox && barBox.x + barBox.width <= vp.width + 1);
      await page.close();
    }
  }
});
