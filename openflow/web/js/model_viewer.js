// v0.37 — visualizador 3D sem bibliotecas: lê GLB ou OBJ e desenha com um renderizador de software no <canvas> (arrastar gira, roda aproxima, giro automático até tocar).
// v0.58 — também mostra a textura (cor por face, pelo centro da face no mapa UV), o esqueleto (ossos por cima) e toca a animação do arquivo (pele por CPU + trilhas das juntas).
import { h } from './ui.js';

// glTF 2.0 (GLB): todas as malhas da cena (não só a primeira), com a transformação de cada nó (matriz ou T/R/S), índices de 8/16/32 bits, cores normalizadas (COLOR_0 em
// byte/short) e primitivas sem índices ou em tiras/leques (v0.53). Pontos e linhas não são superfície e ficam de fora.
const COMPONENT = { 5120: [Int8Array, 'getInt8', 127], 5121: [Uint8Array, 'getUint8', 255], 5122: [Int16Array, 'getInt16', 32767], 5123: [Uint16Array, 'getUint16', 65535], 5125: [Uint32Array, 'getUint32', 1], 5126: [Float32Array, 'getFloat32', 1] };
const NCOMP = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 };

function matMul(a, b) { const o = new Array(16).fill(0); for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) o[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k]; return o; }
function nodeMatrix(n) {
  if (Array.isArray(n.matrix) && n.matrix.length === 16) return n.matrix;
  const [x, y, z, w] = n.rotation && n.rotation.length === 4 ? n.rotation : [0, 0, 0, 1], [sx, sy, sz] = n.scale || [1, 1, 1], [tx, ty, tz] = n.translation || [0, 0, 0];
  return [(1 - 2 * (y * y + z * z)) * sx, 2 * (x * y + z * w) * sx, 2 * (x * z - y * w) * sx, 0, 2 * (x * y - z * w) * sy, (1 - 2 * (x * x + z * z)) * sy, 2 * (y * z + x * w) * sy, 0,
    2 * (x * z + y * w) * sz, 2 * (y * z - x * w) * sz, (1 - 2 * (x * x + y * y)) * sz, 0, tx, ty, tz, 1];
}

const IDENT = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
const affineInvTranslation = (m) => {   // posição de uma junta a partir da sua «inverse bind matrix» (afim, sem perspectiva)
  const a = m[0], b = m[4], c = m[8], d = m[1], e = m[5], f = m[9], g = m[2], hh = m[6], i = m[10];
  const det = a * (e * i - f * hh) - b * (d * i - f * g) + c * (d * hh - e * g);
  if (Math.abs(det) < 1e-12) return [-m[12], -m[13], -m[14]];
  const inv = [[(e * i - f * hh) / det, (c * hh - b * i) / det, (b * f - c * e) / det], [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det], [(d * hh - e * g) / det, (b * g - a * hh) / det, (a * e - b * d) / det]];
  return [0, 1, 2].map((r) => -(inv[r][0] * m[12] + inv[r][1] * m[13] + inv[r][2] * m[14]));
};

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
  const nodes = doc.nodes || [];
  const parentOf = {};
  nodes.forEach((n, i) => (n.children || []).forEach((c) => { parentOf[c] = i; }));
  const pos = [], idx = [], col = [], uv = [], jnt = [], wgt = [];
  let anyCol = false, anyUv = false, anySkin = false, skinIdx = -1, texture = null, tint = null;
  const addPrim = (prim, m, skinned) => {
    if (prim.mode !== undefined && ![4, 5, 6].includes(prim.mode)) return;
    const att = prim.attributes, P = read(att.POSITION).data, nv = P.length / 3, base = pos.length / 3;
    for (let i = 0; i < nv; i++) {
      const x = P[i * 3], y = P[i * 3 + 1], z = P[i * 3 + 2];
      if (skinned) pos.push(x, y, z);   // malha com pele: a transformação do nó é ignorada (especificação do glTF)
      else pos.push(m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14]);
    }
    let ix = prim.indices !== undefined ? Array.from(read(prim.indices).data) : Array.from({ length: nv }, (_, i) => i);
    const tris = [];
    const mode = prim.mode === undefined ? 4 : prim.mode;
    if (mode === 4) for (let i = 0; i + 2 < ix.length; i += 3) tris.push(ix[i], ix[i + 1], ix[i + 2]);
    else if (mode === 5) for (let i = 0; i + 2 < ix.length; i++) i % 2 ? tris.push(ix[i + 1], ix[i], ix[i + 2]) : tris.push(ix[i], ix[i + 1], ix[i + 2]);
    else for (let i = 1; i + 1 < ix.length; i++) tris.push(ix[0], ix[i], ix[i + 1]);
    for (const t of tris) idx.push(t < nv ? base + t : base);   // índice fora da lista não derruba o desenho
    const mat = prim.material !== undefined && doc.materials && doc.materials[prim.material];
    const pbr = (mat && mat.pbrMetallicRoughness) || {};
    if (att.COLOR_0 !== undefined) {
      const c = read(att.COLOR_0); anyCol = true;
      for (let i = 0; i < nv; i++) col.push(c.data[i * c.comp], c.data[i * c.comp + 1], c.data[i * c.comp + 2]);
    } else {
      const f = pbr.baseColorFactor;
      for (let i = 0; i < nv; i++) col.push(f ? f[0] : 0.78, f ? f[1] : 0.78, f ? f[2] : 0.8);   // sem cor por vértice: a cor do material (ou um cinza)
    }
    if (att.TEXCOORD_0 !== undefined) { const u = read(att.TEXCOORD_0); anyUv = true; for (let i = 0; i < nv; i++) uv.push(u.data[i * 2], u.data[i * 2 + 1]); } else for (let i = 0; i < nv; i++) uv.push(0, 0);
    if (skinned && att.JOINTS_0 !== undefined && att.WEIGHTS_0 !== undefined) {
      const J = read(att.JOINTS_0), W = read(att.WEIGHTS_0); anySkin = true;
      for (let i = 0; i < nv; i++) for (let k = 0; k < 4; k++) { jnt.push(J.data[i * J.comp + k] || 0); wgt.push(W.data[i * W.comp + k] || 0); }
    } else for (let i = 0; i < nv; i++) for (let k = 0; k < 4; k++) { jnt.push(0); wgt.push(0); }   // sem pele: peso 0 = o vértice não se mexe com os ossos
    if (!tint && pbr.baseColorFactor) tint = pbr.baseColorFactor;
    if (!texture && pbr.baseColorTexture !== undefined && doc.textures && doc.images) {
      const tx = doc.textures[pbr.baseColorTexture.index], im = tx && doc.images[tx.source];
      if (im && im.bufferView !== undefined) { const v = doc.bufferViews[im.bufferView], o = binOff + (v.byteOffset || 0); texture = { bytes: new Uint8Array(buf, o, v.byteLength), mime: im.mimeType || 'image/png' }; }
    }
  };
  const seen = new Set();
  const visit = (ni, parent) => {
    if (seen.has(ni) || !nodes[ni]) return;   // ciclo (arquivo malformado)
    seen.add(ni);
    const n = nodes[ni], m = matMul(parent, nodeMatrix(n));
    if (n.mesh !== undefined && doc.meshes[n.mesh]) {
      const skinned = n.skin !== undefined && doc.skins && doc.skins[n.skin] && (skinIdx < 0 || skinIdx === n.skin);
      if (skinned) skinIdx = n.skin;
      for (const prim of doc.meshes[n.mesh].primitives) addPrim(prim, m, !!skinned);
    }
    for (const c of n.children || []) visit(c, m);
    seen.delete(ni);
  };
  const scene = (doc.scenes && doc.scenes[doc.scene || 0]) || null;
  if (nodes.length) {
    const roots = scene ? scene.nodes || [] : nodes.map((_, i) => i);
    for (const r of roots) visit(r, IDENT);
  }
  if (!pos.length) for (const mesh of doc.meshes) for (const prim of mesh.primitives) addPrim(prim, IDENT, false);   // sem nós: as malhas soltas
  if (!pos.length || !idx.length) throw new Error('GLB sem superfície');
  const out = { pos: Float32Array.from(pos), idx: Uint32Array.from(idx), col: anyCol || col.length ? { data: Float32Array.from(col), comp: 3 } : null, uv: anyUv ? Float32Array.from(uv) : null, texture: anyUv ? texture : null, tint: tint ? tint.slice(0, 3) : [1, 1, 1], skin: null, anim: null };
  let jointOf = {};
  if (anySkin && skinIdx >= 0) {   // pele: juntas (nome, pai, posição de repouso) e pesos
    const sk = doc.skins[skinIdx], J = sk.joints.length;
    jointOf = Object.fromEntries(sk.joints.map((nid, k) => [nid, k]));
    const ibm = sk.inverseBindMatrices !== undefined ? read(sk.inverseBindMatrices).data : null;
    const gl = (nid) => { let m = nodeMatrix(nodes[nid]), a = parentOf[nid]; while (a !== undefined) { m = matMul(nodeMatrix(nodes[a]), m); a = parentOf[a]; } return m; };
    const joints = sk.joints.map((nid, k) => {
      let par = -1, a = parentOf[nid];
      while (a !== undefined) { if (jointOf[a] !== undefined) { par = jointOf[a]; break; } a = parentOf[a]; }
      const rest = ibm ? affineInvTranslation(Array.from(ibm.slice(k * 16, k * 16 + 16))) : (() => { const g = gl(nid); return [g[12], g[13], g[14]]; })();
      return { name: nodes[nid].name || ('junta ' + k), parent: par, pos: rest };
    });
    const ib = new Float32Array(J * 16);
    for (let k = 0; k < J; k++) { const r = joints[k].pos, src = ibm ? ibm.slice(k * 16, k * 16 + 16) : [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -r[0], -r[1], -r[2], 1]; ib.set(src, k * 16); }
    out.skin = { joints, ibm: ib, jointsAttr: Float32Array.from(jnt), weights: Float32Array.from(wgt) };
  }
  if (doc.animations && doc.animations.length) {   // a primeira animação: trilhas de translação/rotação/escala das juntas (ou do modelo todo, quando o alvo não é uma junta)
    const an = doc.animations[0], tracks = [];
    for (const ch of an.channels || []) {
      const tg = ch.target || {};
      if (!['translation', 'rotation', 'scale'].includes(tg.path) || tg.node === undefined) continue;
      const smp = an.samplers[ch.sampler];
      let times = read(smp.input).data, vals = read(smp.output), comp = tg.path === 'rotation' ? 4 : 3;
      let v = vals.data;
      if (smp.interpolation === 'CUBICSPLINE' && v.length === times.length * comp * 3) { const w = new Float32Array(times.length * comp); for (let i = 0; i < times.length; i++) w.set(v.slice((i * 3 + 1) * comp, (i * 3 + 2) * comp), i * comp); v = w; }
      if (v.length !== times.length * comp) continue;
      tracks.push({ joint: jointOf[tg.node] !== undefined ? jointOf[tg.node] : -1, path: tg.path, comp, times, values: v });
    }
    if (tracks.length) out.anim = { name: an.name || '', duration: Math.max(...tracks.map((t) => t.times[t.times.length - 1] || 0)), tracks };
  }
  return out;
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
  return { pos: Float32Array.from(pos), idx: Uint32Array.from(idx), col: colored && col.length === pos.length ? { data: Float32Array.from(col), comp: 3 } : null, uv: null, texture: null, tint: [1, 1, 1], skin: null, anim: null };
}

// ---- pose: o modelo (e o esqueleto) num instante da animação -------------------------------------------------------------------------------------------
const slerp = (a, b, t) => {
  let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
  const s = d < 0 ? -1 : 1; d *= s;   // caminho mais curto
  if (d > 0.9995) { const r = [0, 1, 2, 3].map((i) => a[i] + (s * b[i] - a[i]) * t); const n = Math.hypot(...r) || 1; return r.map((x) => x / n); }
  const th = Math.acos(Math.min(1, d)), sn = Math.sin(th), wa = Math.sin((1 - t) * th) / sn, wb = Math.sin(t * th) / sn;
  return [0, 1, 2, 3].map((i) => wa * a[i] + wb * s * b[i]);
};
const sampleTrack = (tr, t) => {
  const ts = tr.times, n = ts.length, c = tr.comp, v = tr.values, at = (i) => Array.from(v.slice(i * c, i * c + c));
  if (n === 1 || t <= ts[0]) return at(0);
  if (t >= ts[n - 1]) return at(n - 1);
  let i = 0; while (i < n - 2 && t >= ts[i + 1]) i++;
  const k = (t - ts[i]) / ((ts[i + 1] - ts[i]) || 1), a = at(i), b = at(i + 1);
  return tr.path === 'rotation' ? slerp(a, b, k) : a.map((x, j) => x + (b[j] - x) * k);
};
const trsMatrix = (t, q, s) => nodeMatrix({ translation: t, rotation: q, scale: s });

/** Posições dos vértices (e das juntas) do modelo `mm` no instante `t` (s) da animação: pele por CPU (até 4 juntas por vértice) e, depois, as trilhas do modelo todo. Sem animação, a pose de repouso. */
export function poseModel(mm, t = 0, jointsOnly = false) {
  const sk = mm.skin, an = mm.anim, n = mm.pos.length / 3;
  const tt = an && an.duration > 0 ? ((t % an.duration) + an.duration) % an.duration : 0;
  const out = new Float32Array(mm.pos);
  let jointPos = null;
  let rootM = null;
  const tracks = an ? an.tracks : [];
  const rootTracks = tracks.filter((x) => x.joint < 0);
  if (rootTracks.length) {
    let T = [0, 0, 0], Q = [0, 0, 0, 1], S = [1, 1, 1];
    for (const tr of rootTracks) { const v = sampleTrack(tr, tt); if (tr.path === 'translation') T = v; else if (tr.path === 'rotation') Q = v; else S = v; }
    rootM = trsMatrix(T, Q, S);
  }
  if (sk) {
    const J = sk.joints.length, G = new Array(J);
    const local = (j) => {
      const jt = sk.joints[j], pp = jt.parent >= 0 ? sk.joints[jt.parent].pos : [0, 0, 0];
      let T = [jt.pos[0] - pp[0], jt.pos[1] - pp[1], jt.pos[2] - pp[2]], Q = [0, 0, 0, 1], S = [1, 1, 1];
      for (const tr of tracks) if (tr.joint === j) { const v = sampleTrack(tr, tt); if (tr.path === 'translation') T = v; else if (tr.path === 'rotation') Q = v; else S = v; }
      return trsMatrix(T, Q, S);
    };
    const glob = (j, depth = 0) => { if (G[j]) return G[j]; const par = sk.joints[j].parent; G[j] = par >= 0 && depth < 256 ? matMul(glob(par, depth + 1), local(j)) : local(j); return G[j]; };
    for (let j = 0; j < J; j++) glob(j);
    jointPos = G.map((g) => [g[12], g[13], g[14]]);
    const SM = G.map((g, j) => matMul(g, Array.from(sk.ibm.slice(j * 16, j * 16 + 16))));
    for (let i = 0; i < (jointsOnly ? 0 : n); i++) {   // só as juntas (esqueleto parado): sem a pele de cada vértice
      const x = mm.pos[i * 3], y = mm.pos[i * 3 + 1], z = mm.pos[i * 3 + 2];
      let ws = 0, ox = 0, oy = 0, oz = 0;
      for (let k = 0; k < 4; k++) {
        const w = sk.weights[i * 4 + k]; if (!(w > 0)) continue;
        const m = SM[sk.jointsAttr[i * 4 + k]]; if (!m) continue;
        ws += w; ox += w * (m[0] * x + m[4] * y + m[8] * z + m[12]); oy += w * (m[1] * x + m[5] * y + m[9] * z + m[13]); oz += w * (m[2] * x + m[6] * y + m[10] * z + m[14]);
      }
      if (ws > 1e-6) { out[i * 3] = ox / ws; out[i * 3 + 1] = oy / ws; out[i * 3 + 2] = oz / ws; }
    }
  }
  if (rootM) {
    for (let i = 0; i < n; i++) { const m = rootM, x = out[i * 3], y = out[i * 3 + 1], z = out[i * 3 + 2]; out[i * 3] = m[0] * x + m[4] * y + m[8] * z + m[12]; out[i * 3 + 1] = m[1] * x + m[5] * y + m[9] * z + m[13]; out[i * 3 + 2] = m[2] * x + m[6] * y + m[10] * z + m[14]; }
    if (jointPos) jointPos = jointPos.map((p) => [rootM[0] * p[0] + rootM[4] * p[1] + rootM[8] * p[2] + rootM[12], rootM[1] * p[0] + rootM[5] * p[1] + rootM[9] * p[2] + rootM[13], rootM[2] * p[0] + rootM[6] * p[1] + rootM[10] * p[2] + rootM[14]]);
  }
  return { pos: out, joints: jointPos };
}

export async function loadModel(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const buf = await r.arrayBuffer();
  return new DataView(buf).getUint32(0, true) === 0x46546C67 ? parseGLB(buf) : parseOBJ(new TextDecoder().decode(buf));
}

const MAX_ANIMATED_VERTS = 60000;   // a pele por CPU a cada quadro; acima disso mostra só a pose de repouso

export function modelViewer(url, opts = {}) {
  const height = opts.height || 220;
  const cv = h('canvas', { class: 'mv3d nodrag', width: 480, height: Math.round(height * 480 / (opts.width || 320)), style: { width: '100%', height: height + 'px', cursor: 'grab', borderRadius: '8px', background: 'var(--surface-2, #1b1f27)', touchAction: 'none' } });
  const info = h('div', { class: 'dim small' }, '…');
  const bar = h('div', { class: 'row nodrag', style: { gap: '10px', alignItems: 'center', flexWrap: 'wrap' } });
  const box = h('div', { class: 'mv3d-box' }, cv, bar, info);
  const ctx = cv.getContext('2d');
  let m = null, ay = 0.6, ax = -0.35, zoom = 1, auto = true, raf = 0, drag = null, alive = true, playing = true, bones = true, t0 = 0, tHold = 0;
  const clock = () => (playing ? (performance.now() - t0) / 1000 : tHold);
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
    const animated = !!(mm.anim || mm.skin) && n <= MAX_ANIMATED_VERTS && !!mm.anim;
    return { mm, q, idx: mm.idx, col: mm.col, face, tris, mid, big, animated, fcol: null };
  }
  // textura: a cor de cada face é a do mapa no centro da face (uma prévia; o arquivo leva a textura inteira)
  function loadTexture(mm) {
    if (!mm.texture || !mm.uv || typeof Image === 'undefined' || typeof document.createElement !== 'function') return;
    const blob = new Blob([mm.texture.bytes], { type: mm.texture.mime }), u = URL.createObjectURL(blob), im = new Image();
    im.onload = () => {
      const c = document.createElement('canvas'), W = Math.min(im.width, 512), Hh = Math.min(im.height, 512); c.width = W; c.height = Hh;
      const g = c.getContext('2d'); g.drawImage(im, 0, 0, W, Hh); const px = g.getImageData(0, 0, W, Hh).data; URL.revokeObjectURL(u);
      const idx = m.idx, uv = mm.uv, tint = mm.tint, fcol = new Float32Array(m.tris * 3);
      for (let f = 0; f < m.tris; f++) {
        const a = idx[f * 3], b = idx[f * 3 + 1], cc = idx[f * 3 + 2];
        let uu = (uv[a * 2] + uv[b * 2] + uv[cc * 2]) / 3, vv = (uv[a * 2 + 1] + uv[b * 2 + 1] + uv[cc * 2 + 1]) / 3;
        uu -= Math.floor(uu); vv -= Math.floor(vv);
        const o = ((Math.min(Hh - 1, Math.floor(vv * Hh))) * W + Math.min(W - 1, Math.floor(uu * W))) * 4;
        fcol[f * 3] = px[o] / 255 * tint[0]; fcol[f * 3 + 1] = px[o + 1] / 255 * tint[1]; fcol[f * 3 + 2] = px[o + 2] / 255 * tint[2];
      }
      m.fcol = fcol;
      if (!raf) draw();
    };
    im.src = u;
  }
  function draw() {
    const W = cv.width, H = cv.height, S = Math.min(W, H) * 0.34 * zoom;
    ctx.clearRect(0, 0, W, H);
    const { idx, col, face, fcol } = m;
    let q = m.q, jpos = null;
    if (m.mm.skin || m.mm.anim) {   // modelo com pele/animação: pose do instante atual (e posição das juntas, para os ossos)
      const pz = m.animated ? poseModel(m.mm, clock()) : poseModel(m.mm, 0, true);
      if (m.animated) { q = new Float32Array(pz.pos.length); for (let i = 0; i < pz.pos.length; i += 3) for (let k = 0; k < 3; k++) q[i + k] = (pz.pos[i + k] - m.mid[k]) / m.big * 2; }
      jpos = pz.joints;
    }
    const cy = Math.cos(ay), sy = Math.sin(ay), cx = Math.cos(ax), sx = Math.sin(ax);
    const n = q.length / 3, X = new Float32Array(n), Y = new Float32Array(n), Z = new Float32Array(n);
    const proj = (x, y, z, i, A, B, C) => { const x1 = x * cy + z * sy, z1 = -x * sy + z * cy, y2 = y * cx - z1 * sx, z2 = y * sx + z1 * cx; A[i] = W / 2 + x1 * S; B[i] = H / 2 - y2 * S; if (C) C[i] = z2; };
    for (let i = 0; i < n; i++) proj(q[i * 3], q[i * 3 + 1], q[i * 3 + 2], i, X, Y, Z);
    const order = face.map((f) => { const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2]; return [f, (Z[a] + Z[b] + Z[c]) / 3]; }).sort((u, v) => u[1] - v[1]);
    for (const [f] of order) {
      const a = idx[f * 3], b = idx[f * 3 + 1], c = idx[f * 3 + 2];
      const ux = X[b] - X[a], uy = Y[b] - Y[a], vx = X[c] - X[a], vy = Y[c] - Y[a];
      const nz = ux * vy - uy * vx;   // orientação na tela (as duas faces aparecem: o material é de dois lados)
      const sh = 0.45 + 0.55 * Math.min(1, Math.abs(nz) / (Math.hypot(ux, uy) * Math.hypot(vx, vy) + 1e-6));
      let r = 200, g = 200, bl = 205;
      if (fcol) { r = 255 * fcol[f * 3]; g = 255 * fcol[f * 3 + 1]; bl = 255 * fcol[f * 3 + 2]; }
      else if (col) { const k = col.comp; r = 255 * (col.data[a * k] + col.data[b * k] + col.data[c * k]) / 3; g = 255 * (col.data[a * k + 1] + col.data[b * k + 1] + col.data[c * k + 1]) / 3; bl = 255 * (col.data[a * k + 2] + col.data[b * k + 2] + col.data[c * k + 2]) / 3; }
      const s = `rgb(${r * sh | 0},${g * sh | 0},${bl * sh | 0})`;
      ctx.fillStyle = s; ctx.strokeStyle = s; ctx.lineWidth = 0.6;
      ctx.beginPath(); ctx.moveTo(X[a], Y[a]); ctx.lineTo(X[b], Y[b]); ctx.lineTo(X[c], Y[c]); ctx.closePath(); ctx.fill(); ctx.stroke();
    }
    if (bones && jpos && m.mm.skin) {   // esqueleto por cima: um osso de cada junta até o pai, e uma bolinha em cada junta
      const jn = jpos.length, JX = new Float32Array(jn), JY = new Float32Array(jn);
      jpos.forEach((p, i) => proj((p[0] - m.mid[0]) / m.big * 2, (p[1] - m.mid[1]) / m.big * 2, (p[2] - m.mid[2]) / m.big * 2, i, JX, JY, null));
      ctx.strokeStyle = '#ffd34d'; ctx.fillStyle = '#ff7a59'; ctx.lineWidth = 2;
      m.mm.skin.joints.forEach((j, i) => { if (j.parent >= 0) { ctx.beginPath(); ctx.moveTo(JX[j.parent], JY[j.parent]); ctx.lineTo(JX[i], JY[i]); ctx.stroke(); } });
      for (let i = 0; i < jn; i++) { ctx.beginPath(); ctx.arc(JX[i], JY[i], 3, 0, 6.2832); ctx.fill(); }
    }
  }
  cv.addEventListener('pointerdown', (e) => { drag = [e.clientX, e.clientY]; auto = false; cv.setPointerCapture(e.pointerId); cv.style.cursor = 'grabbing'; e.stopPropagation(); });
  cv.addEventListener('pointermove', (e) => { if (!drag) return; ay += (e.clientX - drag[0]) * 0.01; ax = Math.max(-1.5, Math.min(1.5, ax + (e.clientY - drag[1]) * 0.01)); drag = [e.clientX, e.clientY]; if (!raf) draw(); });
  cv.addEventListener('pointerup', () => { drag = null; cv.style.cursor = 'grab'; });
  cv.addEventListener('wheel', (e) => { e.preventDefault(); e.stopPropagation(); zoom = Math.max(0.3, Math.min(4, zoom * (e.deltaY < 0 ? 1.1 : 0.9))); draw(); }, { passive: false });
  loadModel(url).then((mm) => {
    m = prep(mm);
    t0 = performance.now();
    const extra = [];
    if (mm.skin) extra.push(`${mm.skin.joints.length} ${opts.jLabel || 'juntas'}`);
    if (mm.anim) extra.push(`${opts.aLabel || 'animação'} ${mm.anim.duration.toFixed(1)} s`);
    if (mm.texture) extra.push(opts.tLabel || 'com textura');
    info.textContent = `${(mm.pos.length / 3).toLocaleString()} ${opts.vLabel || 'vértices'} · ${Math.floor(mm.idx.length / 3).toLocaleString()} ${opts.fLabel || 'faces'}` + (extra.length ? ' · ' + extra.join(' · ') : '')
      + (mm.anim && !m.animated ? ' · ' + (opts.bigLabel || 'malha grande: animação não tocada aqui') : '');
    if (mm.skin) bar.append(h('label', { class: 'row', style: { gap: '4px', cursor: 'pointer' } }, h('input', { type: 'checkbox', id: 'mv-bones', checked: true, onchange: (e) => { bones = e.target.checked; if (!raf) draw(); } }), h('span', { class: 'small' }, opts.boneLabel || 'Esqueleto')));
    if (m.animated) bar.append(h('button', { class: 'btn sm', type: 'button', id: 'mv-play', onclick: (e) => { if (playing) { tHold = clock(); playing = false; } else { t0 = performance.now() - tHold * 1000; playing = true; } e.target.textContent = playing ? (opts.pauseLabel || 'Pausar') : (opts.playLabel || 'Tocar'); } }, opts.pauseLabel || 'Pausar'));
    loadTexture(mm);
    draw();
    raf = requestAnimationFrame(frame);
  }).catch((err) => { info.textContent = (opts.errLabel || 'Não foi possível abrir o modelo 3D') + ': ' + err.message; });
  return box;
}
