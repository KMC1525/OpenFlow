// v0.19 — nó Texto ligado aos nós Imagem e Vídeo: o texto ligado aparece sob o campo do nó (e acompanha a digitação), texto vazio avisa, e o botão de erro cabe dentro do nó.
const { run } = require('./_common.js');
run('canvas_text_link', async ({ api, open, check }) => {
  const page = await open({ width: 1500, height: 900 });
  const cv = await api('/api/projects', { method: 'POST', body: { name: 'Texto ligado', template: 'blank' } });
  await api(`/api/projects/${cv.id}`, { method: 'PUT', body: { name: 'Texto ligado', edges: [
    { id: 'e1', from: 't', to: 'im', port: 'prompt' }, { id: 'e2', from: 't', to: 'vi', port: 'prompt' }, { id: 'e3', from: 'vazio', to: 'im2', port: 'prompt' }], nodes: [
    { id: 't', type: 'text', x: 20, y: 40, params: { text: 'Uma floresta ao amanhecer, névoa suave' } },
    { id: 'im', type: 'image', x: 420, y: 20, params: {} }, { id: 'vi', type: 'video', x: 800, y: 20, params: {} },
    { id: 'vazio', type: 'text', x: 20, y: 500, params: { text: '' } }, { id: 'im2', type: 'image', x: 420, y: 560, params: {} },
    { id: 'solto', type: 'image', x: 1180, y: 20, params: {} }] } });
  await page.evaluate((id) => { location.hash = '#/project/' + id; }, cv.id); await page.waitForSelector('.cv-node', { timeout: 10000 }); await page.waitForTimeout(700);
  const node = (id) => page.locator(`.cv-node[data-id="${id}"]`);
  const linked = async (id) => (await node(id).locator('.linked').allInnerTexts()).join(' | ');
  check('imagem:mostra-o-texto-ligado', /Uma floresta ao amanhecer, névoa suave/.test(await linked('im')));
  check('video:mostra-o-texto-ligado', /Uma floresta ao amanhecer, névoa suave/.test(await linked('vi')));
  check('sem-ligacao:nada-aparece', (await node('solto').locator('.linked').count()) === 0);
  const ph = async (id) => node(id).locator('textarea').first().getAttribute('placeholder');
  check('imagem:placeholder-muda-com-texto-ligado', /Opcional|Optional/.test(await ph('im')) && !/Opcional|Optional/.test(await ph('solto')));
  // digitar no nó Texto atualiza a prévia dos dois nós ligados
  await node('t').locator('textarea').fill('Uma cidade à noite');
  await page.waitForTimeout(900);
  check('imagem:acompanha-a-digitacao', /Uma cidade à noite/.test(await linked('im')) && !/floresta/.test(await linked('im')));
  check('video:acompanha-a-digitacao', /Uma cidade à noite/.test(await linked('vi')));
  // texto ligado vazio: aviso
  check('texto-vazio:avisa', /vazio|empty/.test(await linked('im2')) && (await node('im2').locator('.linked.warn').count()) === 1);
  // o botão de ação do erro (rótulo comprido) fica dentro do nó
  const fit = await page.evaluate(() => {
    const n = document.querySelector('.cv-node[data-id="im"]');
    const res = document.createElement('div'); res.className = 'res';
    const b = document.createElement('button'); b.className = 'btn sm primary'; b.textContent = 'Abrir leejet/flux-3-image-klein-GGUF em Modelos e baixar a versão compatível';
    res.append(b); n.append(res);
    const nb = n.getBoundingClientRect(), bb = b.getBoundingClientRect();
    return { inside: bb.left >= nb.left - 1 && bb.right <= nb.right + 1, lines: bb.height };
  });
  check('botao-do-erro:cabe-no-no', fit.inside);
});
