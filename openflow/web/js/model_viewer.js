// v0.37 — visualizador 3D sem bibliotecas: lê GLB (uma malha) ou OBJ e desenha com um renderizador de software no <canvas> (arrastar gira, roda aproxima, giro automático até tocar).
import { h } from './ui.js';

// glTF 2.0 (GLB): todas as malhas da cena (não só a primeira), com a transformação de cada nó (matriz ou T/R/S), índices de 8/16/32 bits, cores normalizadas (COLOR_0 em
// byte/short) e primitivas sem índices ou em tiras/leques (v0.53). Pontos e linhas não são superfície e ficam de fora.
const COMPONENT = { 5120: [Int8Array, 'getInt8', 127], 5121: [Uint8Array, 'getUint8', 255], 5122: [Int16Array, 'getInt16', 32767], 5123: [Uint16Array, 'getUint16', 65535], 5125: [Uint32Array, 'getUint32', 1], 5126: [Float32Array, 'getFloat32', 1] };
const NCOMP = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };

function matMul(a, b) { const o = new Array(16).fill(0); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k]; return o; }
function nodeMatrix(n) {
  if (Array.isArray(n.matrix) && n.matrix.length === 16) return n.matrix;
  const [x, y, z, w] = n.rotation && n.rotation.length === 4 ? n.rotation : [0, 0, 0, 1], [sx, sy, sz] = n.scale || [1, 1, 1], [tx, ty, tz] = n.translation || [0, 0, 0];
  return [(1 - 2 * (y * y + z * z)) * sx, 2 * (x * y + z * w) * sx, 2 * (x * z - y * w) * sx, 0, 2 * (x * y - z * w) * sy, (1 - 2 * (x * x + z * z)) * sy, 2 * (y * z + x * w) * sy, 0,
    2 * (x * z + y * w) * sz, 2 * (y * z - x * w) * sz, (1 - 2 * (x * x + y * y)) * sz, 0, tx, ty, tz, 1];
}

export function parseGLB(buf) {
  const dv = new DataView(buf);
  if (dv.byteLength < 28 || dv.getUint32(0, true) !== 0x46546C67) throw new Error('não é um GLB');
  let json = null, binOff = 0;
  for (let o = 12; o + 8 <= dv.byteLength;) {   // percorre os blocos (o BIN não precisa vir colado no JSON)
    const len = dv.getUint32(o, true), type = dv.getUint32(o + 4, true);
    if (type === 0x4E4F534A && !json) json = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, o + 8, Math.min(len, dv.byteLength - o - 8))));
    else if (type === 0x004E4942 && !binOff) binOff = o + 8;
    o += 8 + len;   // os tamanhos dos blocos já vêm múltiplos de 4
  }
  if (!json || !json.meshes || !json.meshes.length) throw new Error('GLB sem malha');
  const doc = json;
  const read = (ai) => {
    const a = doc.accessors[ai], n = a.count, comp = NCOMP[a.type], [T, getter, max] = COMPONENT[a.componentType] || [];
    if (!T || !comp) throw new Error('tipo de dado não suportado');
    const out = new Float32Array(n * comp);
    if (a.bufferView === undefined) return { data: out, comp };   // sem dados (zeros)
    const v = doc.bufferViews[a.bufferView], base = binOff + (v.byteOffset || 0) + (a.byteOffset || 0);
    const size = T.BYTES_PER_ELEMENT * comp, stride = v.byteStride || size;
    for (let i = 0; i < n; i++) for (let k = 0; k < comp; k++) {
      const x = dv[getter](base + i * stride + k * T.BYTES_PER_ELEMENT, true);
      out[i * comp + k] = a.normalized ? Math.max(x / max, -1) : x;   // cores em byte/short vêm «normalizadas»: 0–255 → 0–1
    }
    return { data: out, comp };
  };
  const pos = [], idx = [], col = [];
  let anyCol = false;
  const addPrim = (prim, m) => {
    if (prim.mode !== undefined && ![4, 5, 6].includes(prim.mode)) return;
    const P = read(prim.attributes.POSITION).data, nv = P.length / 3, base = pos.length / 3;
    for (let i = 0; i < nv; i++) {
      const x = P[i * 3], y = P[i * 3 + 1], z = P[i * 3 + 2];
      pos.push(m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]);
    }
    let ix = prim.indices !== undefined ? Array.from(read(prim.indices).data) : Array.from({ length: nv }, (_, i) => i);
    const tris = [];
    const mode = prim.mode === undefined ? 4 : prim.mode;
    if (mode === 4) for (let i = 0; i + 2 < ix.length; i += 3) tris.push(ix[i], ix[i + 1], ix[i + 2]);
    else if (mode === 5) for (let i = 0; i + 2 < ix.length; i++) i % 2 ? tris.push(ix[i + 1], ix[i], ix[i + 2]) : tris.push(ix[i], ix[i + 1], ix[i + 2]);
    else for (let i = 1; i + 1 < ix.length; i++) tris.push(ix[0], ix[i], ix[i + 1]);
    for (const t of tris) idx.push(t < nv ? base + t : base);   // índice fora da lista não derruba o desenho
    if (prim.attributes.COLOR_0 !== undefined) {
      const c = read(prim.attributes.COLOR_0); anyCol = true;
      for (let i = 0; i < nv; i++) col.push(c.data[i * c.comp], c.data[i * c.comp + 1], c.data[i * c.comp + 2]);
    } else {
      const f = prim.material !== undefined && doc.materials && doc.materials[prim.material] && doc.materials[prim.material].pbrMetallicRoughness && doc.materials[prim.material].pbrMetallicRoughness.baseColorFactor;
      for (let i = 0; i < nv; i++) col.push(f ? f[0] : 0.78, f ? f[1] : 0.78, f ? f[2] : 0.8);   // sem cor por vértice: a cor do material (ou um cinza)
    }
  };
  const seen = new Set();
  const visit = (ni, parent) => {
    if (seen.has(ni) || !doc.nodes || !doc.nodes[ni]) return;   // ciclo (arquivo malformado)
    seen.add(ni);
    const n = doc.nodes[ni], m = matMul(parent, nodeMatrix(n));
    if (n.mesh !== undefined && doc.meshes[n.mesh]) for (const prim of doc.meshes[n.mesh].primitives) addPrim(prim, m);
    for (const c of n.children || []) visit(c, m);
    seen.delete(ni);
  };
  const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  const scene = (doc.scenes && doc.scenes[doc.scene || 0]) || null;
  if (doc.nodes && doc.nodes.length) {
    const roots = scene ? scene.nodes || [] : doc.nodes.map((_, i) => i);
    for (const r of roots) visit(r, I);
  }
  if (!pos.length) for (const mesh of doc.meshes) for (const prim of mesh.primitives) addPrim(prim, I);   // sem nós: as malhas soltas
  if (!pos.length || !idx.length) throw new Error('GLB sem superfície');
  return { pos: Float32Array.from(pos), idx: Uint32Array.from(idx), col: anyCol || col.length ? { data: Float32Array.from(col), comp: 3 } : null };
}

export function parseOBJ(text) {
  const pos = [], col = [], idx = [];
  let colored = true;
  for (const ln of text.split(/\r?\n/)) {
    if (ln.startsWith('v ')) { const p = ln.trim().split(/\s+/).slice(1).map(Number); pos.push(p[0] || 0, p[1] || 0, p[2] || 0); if (p.length >= 6) col.push(p[3], p[4], p[5]); else colored = false; }
    else if (ln.startsWith('f ')) {
      const n = pos.length / 3;
      const f = ln.trim().split(/\s+/).slice(1).map((s) => { const i = parseInt(s, 10); return i < 0 ? n + i : i - 1; });   // índice negativo conta a partir do último vértice
      if (f.some((i) => !(i >= 0 && i < n))) continue;
      for (let i = 1; i + 1 < f.length; i++) idx.push(f[0], f[i], f[i + 1]);
    }
  }
  if (!pos.length || !idx.length) throw new Error('OBJ sem malha');
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
