// v0.82 — PyTorch e TensorFlow: o card em Configurações (versão, placa de vídeo e o conselho com o comando), «Modelos próprios» na barra de pesquisa (framework de cada repositório, baixar só o arquivo do
// framework escolhido, usar no nó) e o nó «Modelo PyTorch/TensorFlow» dizendo o que achou no caminho escrito.
const { run } = require('./_common.js');
run('frameworks_v082', async ({ api, open, check }) => {
  await api('/api/settings', { method: 'PUT', body: { language: 'pt' } });
  const page = await open({ width: 1500, height: 950 });
  const json = (route, body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  const REPORT = { system: 'Windows', machine: 'AMD64', python: '3.13.1', gpu_vendors: ['nvidia'], torch: { installed: true, version: '2.15.0', build: 'CPU', device: 'cpu', cuda: false, devices: [] },
    tensorflow: { installed: true, version: '2.21.0', keras: '3.15.1', gpus: [], backend: 'tensorflow', built_with_cuda: false },
    advice: { torch: [{ level: 'warn', text: 'Há uma placa NVIDIA neste computador, mas o PyTorch roda na CPU: é a versão só de CPU.', text_en: 'There is an NVIDIA card…', command: 'python -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu130' }],
      tensorflow: [{ level: 'info', text: 'O TensorFlow 2.11 ou mais novo não usa a placa de vídeo no Windows nativo (só no WSL2). Aqui ele roda na CPU.', text_en: 'TensorFlow 2.11…' }] } };
  let reads = 0;
  await page.route('**/api/media/frameworks*', (r) => { reads++; json(r, REPORT); });
  await page.evaluate(() => { location.hash = '#/settings'; }); await page.waitForSelector('.cfgtabs button', { timeout: 10000 });
  await page.locator('.cfgtabs button').nth(4).click(); await page.waitForSelector('#fw-torch', { timeout: 10000 });
  check('card:versoes', /2\.15\.0/.test(await page.locator('#fw-torch').innerText()) && /2\.21\.0/.test(await page.locator('#fw-tf').innerText()) && /Keras 3\.15\.1/.test(await page.locator('#fw-tf').innerText()));
  check('card:conselho-da-placa-nvidia-com-o-comando', (await page.locator('.fw-advice[data-level="warn"]').count()) === 1 && /cu130/.test(await page.locator('.fw-cmd').first().innerText()));
  check('card:conselho-do-tensorflow-no-windows', /WSL2/.test(await page.locator('#fw-body').innerText()));
  await page.locator('#fw-refresh').click(); await page.waitForSelector('#fw-torch', { timeout: 8000 });
  check('card:ler-de-novo-pede-ao-servidor', reads >= 2);

  // «Modelos próprios» na barra de pesquisa do Canvas
  const seen = { dl: [], use: [] };
  await page.route('**/api/media/hub/search*', (r) => json(r, { results: [{ id: 'acme/esrgan', downloads: 900, likes: 4, cap: 'tool', format: 'original', frameworks: ['pytorch', 'tensorflow'] }, { id: 'acme/solo-keras', downloads: 50, likes: 0, cap: 'tool', format: 'original', frameworks: ['tensorflow'] }], format: 'original', cap: 'tool' }));
  let downloaded = false;
  await page.route('**/api/tool/files*', (r) => json(r, { model: 'acme/esrgan', frameworks: { torch: { files: 3, size: 140000000 }, tf: { files: 5, size: 110000000 } } }));
  await page.route('**/api/tool/info*', (r) => { const u = new URL(r.request().url()); const m = u.searchParams.get('model'); if (m === 'acme/esrgan') return json(r, downloaded ? { found: true, kind: 'torchscript', framework: 'torch', label: 'esrgan.pt', libs: { torch: true, tf: true }, missing_lib: '' } : { found: false, error: 'não baixado', libs: {} });
    if (m === '/home/u/up.keras') return json(r, { found: true, kind: 'keras', framework: 'tf', label: 'up.keras', libs: { torch: true, tf: false }, missing_lib: 'TensorFlow' });
    return json(r, { found: false, error: 'Não achei o modelo «' + m + '» neste computador (confira o caminho).', libs: {} }); });
  await page.route('**/api/tool/download', (r) => { seen.dl.push(JSON.parse(r.request().postData())); downloaded = true; json(r, { job_id: 'j_tool' }); });
  await page.route('**/api/jobs/j_tool/events*', (r) => r.fulfill({ status: 200, contentType: 'text/event-stream', body: 'data: {"type":"done","model":"acme/esrgan"}\n\n' }));
  await page.route('**/api/media/hub/use', (r) => { seen.use.push(JSON.parse(r.request().postData())); json(r, { ok: true, provider: 'tool', label: 'Modelo PyTorch/TensorFlow', model: 'acme/esrgan', cap: 'tool', node_updated: true }); });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Modelos próprios', template: 'blank' } });
  await api('/api/projects/' + cv.id, { method: 'PUT', body: { name: 'Modelos próprios', nodes: [{ id: 'n1', type: 'ai_model', x: 40, y: 40, params: { model: '/home/u/up.keras' } }, { id: 'n2', type: 'ai_model', x: 520, y: 40, params: { model: '/nao/existe.pt' } }, { id: 'n3', type: 'ai_model', x: 1000, y: 40, params: {} }], edges: [] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('#hub-q', { timeout: 15000 });
  await page.waitForSelector('.cv-node[data-id="n1"] [data-toolstatus]', { timeout: 10000 }); await page.waitForTimeout(800);
  const st = (id) => page.locator('.cv-node[data-id="' + id + '"] [data-toolstatus]').innerText();
  check('no:achou-o-keras-e-avisa-que-falta-o-tensorflow', /up\.keras/.test(await st('n1')) && /Keras/.test(await st('n1')) && /TensorFlow/.test(await st('n1')));
  check('no:caminho-que-nao-existe-explica', /Não achei o modelo/.test(await st('n2')));
  check('no:vazio-diz-o-que-escrever', /Escreva o caminho/.test(await st('n3')));
  check('no:tem-os-campos-do-modelo', (await page.locator('.cv-node[data-id="n1"] select option[value="NCHW"]').count()) === 1 && (await page.locator('.cv-node[data-id="n1"] select option[value="tf"]').count()) === 1);
  await page.locator('#hub-q').focus(); await page.waitForSelector('#hub-cap', { timeout: 8000 });
  await page.selectOption('#hub-cap', 'tool'); await page.waitForTimeout(300);
  await page.fill('#hub-q', 'esrgan'); await page.keyboard.press('Enter');
  await page.waitForSelector('.hub-r[data-repo="acme/esrgan"]', { timeout: 8000 });
  check('busca:mostra-o-framework-de-cada-repositorio', (await page.locator('.hub-r[data-repo="acme/esrgan"] [data-framework]').count()) === 2 && (await page.locator('.hub-r[data-repo="acme/solo-keras"] [data-framework="tensorflow"]').count()) === 1);
  check('busca:formato-fica-em-original', (await page.locator('#hub-fmt').inputValue()) === 'original' && (await page.locator('#hub-fmt').isDisabled()));
  await page.locator('.hub-r[data-repo="acme/esrgan"]').click(); await page.waitForSelector('.hub-q[data-quant="torch"]', { timeout: 8000 });
  check('baixar:um-botao-por-framework', (await page.locator('.hub-q[data-quant]').count()) === 2 && (await page.locator('.hub-q[data-quant="tf"]').count()) === 1);
  check('baixar:ainda-sem-usar', (await page.locator('[data-act="use"]').count()) === 0);
  await page.locator('.hub-q[data-quant="torch"] [data-act="download"]').click();
  await page.waitForSelector('[data-act="use"]', { timeout: 8000 });
  check('baixar:pede-so-o-framework-escolhido', seen.dl.length === 1 && seen.dl[0].framework === 'torch' && seen.dl[0].model === 'acme/esrgan');
  await page.locator('[data-act="use"]').click(); await page.waitForTimeout(600);
  check('usar:vai-para-o-no', seen.use.length === 1 && seen.use[0].cap === 'tool' && seen.use[0].model === 'acme/esrgan');
});
