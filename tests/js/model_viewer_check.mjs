// Lê os arquivos de modelo 3D passados na linha de comando com o leitor do visualizador e imprime {arquivo: {vertices, triangles, colors, ...}}.
import { readFileSync } from 'node:fs';
globalThis.document = {};
const { parseGLB, parseOBJ } = await import('../../openflow/web/js/model_viewer.js');
const out = {};
for (const f of process.argv.slice(2)) {
  try {
    const raw = readFileSync(f);
    const m = f.endsWith('.obj') ? parseOBJ(raw.toString('utf8')) : parseGLB(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength));
    const xs = Array.from(m.pos).filter((_, i) => i % 3 === 0);
    out[f.split(/[\\/]/).pop()] = { vertices: m.pos.length / 3, triangles: m.idx.length / 3, maxIndex: Math.max(...m.idx), colors: m.col ? Array.from(m.col.data.slice(0, 3)).map((v) => Math.round(v * 100) / 100) : null, minX: Math.min(...xs), maxX: Math.max(...xs) };
  } catch (e) { out[f.split(/[\\/]/).pop()] = { error: e.message }; }
}
console.log(JSON.stringify(out));
