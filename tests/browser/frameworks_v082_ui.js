// v0.82 — PyTorch e TensorFlow: o card em Configurações (versão, placa de vídeo e o conselho com o comando), (v0.87: o nó «Modelo PyTorch/TensorFlow» e os «Modelos próprios» da busca saíram; o card fica).
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
  // v0.83: o TensorFlow só é carregado quando a pessoa pede («Verificar o TensorFlow»)
  const asked = [];
  await page.unroute('**/api/media/frameworks*');
  await page.route('**/api/media/frameworks*', (r) => { const u = r.request().url(); asked.push(u); const deep = /tf=1/.test(u); json(r, { ...REPORT, tensorflow: { ...REPORT.tensorflow, probed: deep, gpus: [] }, advice: { torch: [], tensorflow: [{ level: deep ? 'ok' : 'info', text: deep ? 'O TensorFlow 2.21.0 roda na CPU.' : 'O TensorFlow 2.21.0 está instalado. Para saber se ele usa a placa de vídeo é preciso carregá-lo.', text_en: 'x' }] } }); });
  await page.locator('#fw-refresh').click(); await page.waitForSelector('#fw-tf-probe', { timeout: 8000 });
  check('card:tensorflow-nao-e-carregado-sozinho', !asked.some((u) => /tf=1/.test(u)) && /instalado|installed/.test(await page.locator('#fw-tf').innerText()));
  await page.locator('#fw-tf-probe').click(); await page.waitForFunction(() => /roda na CPU/.test(document.getElementById('fw-body').innerText), null, { timeout: 8000 });
  check('card:verificar-o-tensorflow-pede-ao-servidor', asked.some((u) => /tf=1/.test(u)) && (await page.locator('#fw-tf-probe').count()) === 0);
});
