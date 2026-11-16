// Lê um GLB com o leitor do visualizador e imprime, para cada instante pedido, as posições dos vértices e das juntas (poseModel) e um resumo do que ele leu (juntas, animação, textura).
// Uso: node model_pose_check.mjs arquivo.glb 0 0.5 1.25
import { readFileSync } from 'node:fs';
globalThis.document = {};
const { parseGLB, poseModel } = await import('../../openflow/web/js/model_viewer.js');
const [file, ...times] = process.argv.slice(2);
const raw = readFileSync(file);
const m = parseGLB(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength));
const round = (a) => Array.from(a).map((v) => Math.round(v * 1e5) / 1e5);
const out = {
  summary: { vertices: m.pos.length / 3, triangles: m.idx.length / 3, joints: m.skin ? m.skin.joints.length : 0, jointNames: m.skin ? m.skin.joints.map((j) => j.name) : [], parents: m.skin ? m.skin.joints.map((j) => j.parent) : [],
    anim: m.anim ? { duration: m.anim.duration, tracks: m.anim.tracks.map((t) => ({ joint: t.joint, path: t.path, keys: t.times.length })) } : null, texture: m.texture ? { mime: m.texture.mime, bytes: m.texture.bytes.length } : null, uv: !!m.uv, tint: m.tint, colors: !!m.col },
  poses: {},
};
for (const t of times) { const p = poseModel(m, Number(t)); out.poses[t] = { pos: round(p.pos), joints: p.joints ? p.joints.map(round) : null }; }
console.log(JSON.stringify(out));
