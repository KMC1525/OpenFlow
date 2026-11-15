// v0.37 — visualizador 3D sem bibliotecas: lê GLB (uma malha) ou OBJ e desenha com um renderizador de software no <canvas> (arrastar gira, roda aproxima, giro automático até tocar).
import { h } from './ui.js';

export function parseGLB(buf) {
  const dv = new DataView(buf);
  if (dv.byteLength < 28 || dv.getUint32(0, true) !== 0x46546C67) throw new Error('não é um GLB');
  const jl = dv.getUint32(12, true);
  const doc = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, jl)));
  const bo = 20 + jl + 8;
  const prim = doc.meshes[0].primitives[0];
  const read = (ai) => {
    const a = doc.accessors[ai], v = doc.bufferViews[a.bufferView];
    const n = a.count, comp = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 }[a.type];
    const base = bo + (v.byteOffset || 0) + (a.byteOffset || 0);
    const T = { 5126: Float32Array, 5125: Uint32Array, 5123: Uint16Array, 5121: Uint8Array }[a.componentType];
    const out = new T(n * comp);
    const size = T.BYTES_PER_ELEMENT * comp, stride = v.byteStride || size;
    for (let i = 0; i < n; i++) for (let k = 0; k < comp; k++) {
      const o = base + i * stride + k * T.BYTES_PER_ELEMENT;
      out[i * comp + k] = T === Float32Array ? dv.getFloat32(o, true) : T === Uint32Array ? dv.getUint32(o, true) : T === Uint16Array ? dv.getUint16(o, true) : dv.getUint8(o);
    }
    return { data: out, comp };
  };
  const pos = read(prim.attributes.POSITION).data;
  let idx = prim.indices !== undefined ? read(prim.indices).data : Uint32Array.from({ length: pos.length / 3 }, (_, i) => i);
  let col = null;
  if (prim.attributes.COLOR_0 !== undefined) { const c = read(prim.attributes.COLOR_0); col = { data: c.data, comp: c.comp }; }
  return { pos, idx, col };
}

export function parseOBJ(text) {
  const pos = [], col = [], idx = [];
  let colored = true;
  for (const ln of text.split('\n')) {
    if (ln.startsWith('v ')) { const p = ln.trim().split(/\s+/).slice(1).map(Number); pos.push(p[0], p[1], p[2]); if (p.length >= 6) col.push(p[3], p[4], p[5]); else colored = false; }
    else if (ln.startsWith('f ')) {
      const f = ln.trim().split(/\s+/).slice(1).map((s) => parseInt(s, 10) - 1);
      for (let i = 1; i + 1 < f.length; i++) idx.push(f[0], f[i], f[i + 1]);
    }
  }
  return { pos: Float32Array.from(pos), idx: Uint32Array.from(idx), col: colored && col.length === pos.length ? { data: Float32Array.from(col), comp: 3 } : null };
}

export async function loadModel(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const buf = await r.arrayBuffer();
  return new DataView(buf).getUint32(0, true) === 0x46546C67 ? parseGLB(buf) : parseOBJ(new TextDecoder().decode(buf));
}

export function modelViewer(url, opts = {}) {
  const height = opts.height || 220;
  const cv = h('canvas', { class: 'mv3d nodrag', width: 480, height: Math.round(height * 480 / (opts.width || 320)), style: { width: '100%', height: height + 'px', cursor: 'grab', borderRadius: '8px', background: 'var(--surface-2, #1b1f27)', touchAction: 'none' } });
  const info = h('div', { class: 'dim small' }, '…');
  const box = h('div', { class: 'mv3d-box' }, cv, info);
  const ctx = cv.getContext('2d');
  let m = null, ay = 0.6, ax = -0.35, zoom = 1, auto = true, raf = 0, drag = null, alive = true;
  const frame = () => {
    if (!alive || !m) return;
    if (!cv.isConnected && !opts.keep) { alive = false; return; }
    if (auto) ay += 0.012;
    draw();
    raf = requestAnimationFrame(frame);
  };
  function prep(mm) {
    const p = mm.pos, n = p.length / 3;
    let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
    for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], p[i * 3 + k]); hi[k] = Math.max(hi[k], p[i * 3 + k]); }
    const mid = lo.map((v, k) => (v + hi[k]) / 2), big = Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) || 1;
    const q = new Float32Array(p.length);
    for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) q[i * 3 + k] = (p[i * 3 + k] - mid[k]) / big * 2;
    const tris = mm.idx.length / 3, step = Math.max(1, Math.ceil(tris / 40000));   // malhas enormes: desenha uma amostra das faces
    const face = [];
    for (let f = 0; f < tris; f += step) face.push(f);
    return { q, idx: mm.idx, col: mm.col, face, tris };
  }
  function draw() {
    const W = cv.width, H = cv.height, S = Math.min(W, H) * 0.34 * zoom;
    ctx.clearRect(0, 0, W, H);
    const { q, idx, col, face } = m;
    const cy = Math.cos(ay), sy = Math.sin(ay), cx = Math.cos(ax), sx = Math.sin(ax);
    const n = q.length / 3, X = new Float32Array(n), Y = new Float32Array(n), Z = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const x = q[i * 3], y = q[i * 3 + 1], z = q[i * 3 + 2];
      const x1 = x * cy + z * sy, z1 = -x * sy + z * cy;
      const y2 = y * cx - z1 * sx, z2 = y * sx + z1 * cx;
      X[i] = W / 2 + x1 * S; Y[i] = H / 2 - y2 * S; Z[i] = z2;
    }
    const order = face.map((f) => { const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2]; return [f, (Z[a] + Z[b] + Z[c]) / 3]; }).sort((u, v) => u[1] - v[1]);
    for (const [f] of order) {
      const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2];
      const ux = X[b] - X[a], uy = Y[b] - Y[a], vx = X[c] - X[a], vy = Y[c] - Y[a];
      const nz = ux * vy - uy * vx;   // orientação na tela (as duas faces aparecem: o material é de dois lados)
      const sh = 0.45 + 0.55 * Math.min(1, Math.abs(nz) / (Math.hypot(ux, uy) * Math.hypot(vx, vy) + 1e-6));
      let r = 200, g = 200, bl = 205;
      if (col) { const k = col.comp; r = 255 * (col.data[a * k] + col.data[b * k] + col.data[c * k]) / 3; g = 255 * (col.data[a * k + 1] + col.data[b * k + 1] + col.data[c * k + 1]) / 3; bl = 255 * (col.data[a * k + 2] + col.data[b * k + 2] + col.data[c * k + 2]) / 3; }
      const s = `rgb(${r * sh | 0},${g * sh | 0},${bl * sh | 0})`;
      ctx.fillStyle = s; ctx.strokeStyle = s; ctx.lineWidth = 0.6;
      ctx.beginPath(); ctx.moveTo(X[a], Y[a]); ctx.lineTo(X[b], Y[b]); ctx.lineTo(X[c], Y[c]); ctx.closePath(); ctx.fill(); ctx.stroke();
    }
  }
  cv.addEventListener('pointerdown', (e) => { drag = [e.clientX, e.clientY]; auto = false; cv.setPointerCapture(e.pointerId); cv.style.cursor = 'grabbing'; e.stopPropagation(); });
  cv.addEventListener('pointermove', (e) => { if (!drag) return; ay += (e.clientX - drag[0]) * 0.01; ax = Math.max(-1.5, Math.min(1.5, ax + (e.clientY - drag[1]) * 0.01)); drag = [e.clientX, e.clientY]; if (!raf) draw(); });
  cv.addEventListener('pointerup', () => { drag = null; cv.style.cursor = 'grab'; });
  cv.addEventListener('wheel', (e) => { e.preventDefault(); e.stopPropagation(); zoom = Math.max(0.3, Math.min(4, zoom * (e.deltaY < 0 ? 1.1 : 0.9))); draw(); }, { passive: false });
  loadModel(url).then((mm) => {
    m = prep(mm);
    info.textContent = `${(mm.pos.length / 3).toLocaleString()} ${opts.vLabel || 'vértices'} · ${Math.floor(mm.idx.length / 3).toLocaleString()} ${opts.fLabel || 'faces'}`;
    draw();
    raf = requestAnimationFrame(frame);
  }).catch((err) => { info.textContent = (opts.errLabel || 'Não foi possível abrir o modelo 3D') + ': ' + err.message; });
  return box;
}
