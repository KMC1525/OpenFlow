// Helpers de DOM. Nunca usamos innerHTML com conteúdo do usuário/IA: tudo vira nó de texto.
import { t } from './i18n.js';

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected' || k === 'type' && tag === 'input') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  const add = (c) => {
    if (c == null || c === false) return;
    if (Array.isArray(c)) c.forEach(add);
    else el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  };
  kids.forEach(add);
  // acessibilidade: botão só com ícone usa o título como nome acessível
  if (tag === 'button' && el.title && !el.getAttribute('aria-label') && !el.textContent.trim()) el.setAttribute('aria-label', el.title);
  return el;
}

// replaceChildren que ignora null/false (o DOM transformaria `null` no texto "null").
// `replaceChildren(a, null)` / `append(null)` do DOM nativo escrevem o texto «null» na tela (aparecia nas telas de criação e nos botões de Fontes). Como o `h()`, ignora null/undefined/false.
if (typeof Element !== 'undefined') ['replaceChildren', 'append', 'prepend', 'before', 'after'].forEach((name) => {
  const orig = Element.prototype[name];
  if (typeof orig !== 'function' || orig.__asta) return;
  const safe = function (...args) { return orig.apply(this, args.filter((x) => x != null && x !== false)); };
  safe.__asta = true;
  Element.prototype[name] = safe;
});
export function fill(el, ...kids) { el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false)); return el; }

const ICONS = {
  main: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z"/><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z"/>',
  worlds: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 4 5.7 4 9s-1.4 6.4-4 9c-2.6-2.6-4-5.7-4-9s1.4-6.4 4-9Z"/>',
  characters: '<circle cx="9" cy="8" r="3.4"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><circle cx="17" cy="9" r="2.6"/><path d="M17.5 14.6c2.4.2 4 1.7 4.5 4.4"/>',
  worldbuilding: '<path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="m3 13 9 5 9-5"/><path d="m3 17.5 9 4.5 9-4.5"/>',
  library: '<path d="M4 4h4v16H4zM10 4h4v16h-4z"/><path d="m16.4 5.2 3.8-.9 3 15-3.8.9z" transform="translate(-1 0)"/>',
  config: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  play: '<path d="M7 4.5v15l13-7.5L7 4.5Z"/>',
  download: '<path d="M12 4v11M7 10.5l5 5 5-5M4 20h16"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  more: '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
  clip: '<path d="m21 11-8.5 8.5a5.5 5.5 0 0 1-7.8-7.8l9-9a3.7 3.7 0 0 1 5.2 5.2l-9 9a1.8 1.8 0 0 1-2.6-2.6L15 7.5"/>',
  chev: '<path d="m9 6 6 6-6 6"/>',
  sparkle: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  upload: '<path d="M12 16V5M7 9.5l5-5 5 5M4 20h16"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.5-4M4 4v4h4M4 13a8 8 0 0 0 14.5 4M20 20v-4h-4"/>',
  tag: '<path d="M3 12V4h8l10 10-8 8L3 12Z"/><circle cx="7.5" cy="8.5" r="1.2"/>',
  panel: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
  warn: '<path d="M12 4 2.5 20h19L12 4Z"/><path d="M12 10v4M12 17h0"/>',
  file: '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="1.8"/><path d="m4 18 5-5 4 4 3-3 4 4"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="3"/><path d="m16 10 5-3v10l-5-3"/>',
  audio: '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/>',
  archive: '<rect x="4" y="7" width="16" height="13" rx="2"/><path d="M3 4h18v3H3zM12 7v4m0 2v2m-1.5-6h3m-3 4h3"/>',
  doc: '<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h7M9 8h3"/>',
  sheet: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 10h16M4 15h16M10 4v16"/>',
  slides: '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>',
  mic: '<rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.6 4 5.7 4 9s-1.4 6.4-4 9c-2.6-2.6-4-5.7-4-9s1.4-6.4 4-9Z"/>',
  avatars: '<circle cx="12" cy="12" r="9"/><path d="M8.5 14.5c1 1.4 2.2 2 3.5 2s2.5-.6 3.5-2M9 9.5h.01M15 9.5h.01"/>',
  games: '<rect x="2.5" y="7" width="19" height="10" rx="5"/><path d="M7 10v4M5 12h4M15.5 11h.01M18 13h.01"/>',
  canvas: '<rect x="3" y="4" width="7" height="6" rx="1.5"/><rect x="14" y="4" width="7" height="6" rx="1.5"/><rect x="14" y="14" width="7" height="6" rx="1.5"/><path d="M10 7h4M6.5 10v4a2 2 0 0 0 2 2H14"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  rowsmall: '<path d="M4 8h16M4 12h16M4 16h16"/>', rowbig: '<path d="M4 5h16M4 12h16M4 19h16"/>', expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  scissors: '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><path d="M8 7.5 20 17M8 16.5 20 7"/>',
  zoomin: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M11 8v6M8 11h6"/>',
  fit: '<path d="M4 9V5h4M20 9V5h-4M4 15v4h4M20 15v4h-4"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.4 0 2-.9 2-1.8 0-1.4-1.2-1.4-1.2-2.7 0-1 .8-1.5 1.8-1.5H17a4 4 0 0 0 4-4C21 6.7 17 3 12 3Z"/><path d="M7.5 11h.01M10 7.5h.01M14.5 7.5h.01"/>',
  folder: '<path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8.5A1.5 1.5 0 0 1 21 9v8.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5v-11Z"/>',
  type: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
  columns: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
  film: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 5v14M17 5v14M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  skipback: '<path d="M6 5v14M19 5 9 12l10 7Z"/>', skipfwd: '<path d="M18 5v14M5 5l10 7-10 7Z"/>', stepback: '<path d="M15 6l-6 6 6 6"/>', stepfwd: '<path d="M9 6l6 6-6 6"/>',
  pause: '<path d="M8 5v14M16 5v14"/>', cursor: '<path d="M5 3l14 8-6 2-2 6Z"/>', razor: '<path d="M4 20 20 4M7 4h3M4 7v3M14 20h3M20 14v3"/><path d="M12 12l-2.5 2.5"/>',
  join: '<path d="M4 8h6v8H4zM14 8h6v8h-6z"/><path d="M10 12h4"/>', mute: '<path d="M4 9v6h4l5 4V5L8 9ZM17 9l5 6M22 9l-5 6"/>', ripple: '<path d="M4 6v12M20 6v12M8 12h8M8 12l3-3M8 12l3 3M16 12l-3-3M16 12l-3 3"/>',
  trimstart: '<path d="M5 4v16M9 8h10v8H9z"/>', trimend: '<path d="M19 4v16M5 8h10v8H5z"/>', flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
  undo: '<path d="M9 7 4 12l5 5M4 12h11a5 5 0 0 1 0 10h-3"/>', redo: '<path d="m15 7 5 5-5 5M20 12H9a5 5 0 0 0 0 10h3"/>', magnet: '<path d="M6 3v8a6 6 0 0 0 12 0V3M6 8h4M14 8h4"/>',
  zoomout: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4M8 11h6"/>', music: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>', lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  computer: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/><path d="m9.5 7.5 5 2.2-2 .7-.7 2-2.3-4.9Z"/>',
  wand: '<path d="m4 20 11-11M14 6l1-2 1 2 2 1-2 1-1 2-1-2-2-1 2-1ZM18 14l.7-1.4L20 12l-1.3-.6L18 10l-.7 1.4L16 12l1.3.6L18 14Z"/>',
  code: '<path d="m8 8-5 4 5 4M16 8l5 4-5 4M14 5l-4 14"/>',
  branch: '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="8" r="2"/><path d="M6 7v10M18 10c0 4-6 3-12 7"/>',
  foldero: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H3Z"/><path d="M3 10h18l-1.6 8a2 2 0 0 1-2 1.6H6.6a2 2 0 0 1-2-1.6Z"/>',
  chevd: '<path d="m6 9 6 6 6-6"/>',
  chevr: '<path d="m9 6 6 6-6 6"/>',
  github: '<path d="M9 19c-4 1.3-4-2-6-2.5m12 5v-3.5c0-1 .1-1.5-.5-2.2 2.800-.3 5.500-1.400 5.500-6a4.700 4.700 0 0 0-1.300-3.300 4.400 4.400 0 0 0-.1-3.300s-1.100-.3-3.500 1.300a12 12 0 0 0-6.200 0C6.500 2.800 5.400 3.100 5.400 3.100a4.400 4.400 0 0 0-.1 3.300A4.700 4.700 0 0 0 4 9.700c0 4.600 2.700 5.700 5.500 6-.6.600-.6 1.200-.5 2.200V22"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5Z"/><path d="m3 13 9 5 9-5"/>',
  bolt: '<path d="M13 3 5 14h6l-1 7 8-11h-6Z"/>',
  scriber: '<path d="M4 20c4-1 6-3 9-6l5-5a2.1 2.1 0 0 0-3-3l-5 5c-3 3-5 5-6 9Z"/><path d="M13 9l2 2M9 17l-1.5-1.5M14 20h6"/>',
  book: '<path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4Z"/><path d="M5 17a3 3 0 0 1 3-3h10M9 8h5"/>',
  redo: '<path d="m15 7 5 5-5 5M20 12H9a5 5 0 0 0 0 10h3" transform="translate(0 -3)"/>',
  alignl: '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>', alignc: '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>', alignr: '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>', alignj: '<path d="M4 6h16M4 10h16M4 14h16M4 18h16"/>',
  listul: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>', listol: '<path d="M10 6h10M10 12h10M10 18h10M4 5l1.2-.8V8M4 14c0-1 2-1 2 .2 0 1-2 1.6-2 2.8h2"/>',
  indent: '<path d="M4 6h16M12 10h8M12 14h8M4 18h16M4 9l3 3-3 3"/>', outdent: '<path d="M4 6h16M12 10h8M12 14h8M4 18h16M7 9l-3 3 3 3"/>', minus: '<path d="M5 12h14"/>',
  pagebreak: '<path d="M6 3h12v6M6 21h12v-6M3 12h2.5M8.5 12h2.5M13 12h2.5M18.5 12H21"/>', chat: '<path d="M4 5h16v11H9l-5 4V5Z"/>',
  work: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18M11 13v2h2v-2"/>',
  engine: '<path d="M12 2.5 20 7v10l-8 4.5L4 17V7Z"/><path d="M4 7l8 4.5L20 7M12 11.5v10"/>',
  cube: '<path d="M12 3 20 7.5v9L12 21 4 16.5v-9Z"/><path d="M4 7.5 12 12l8-4.5M12 12v9"/>',
  grid: '<rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M3.5 9.2h17M3.5 14.8h17M9.2 3.5v17M14.8 3.5v17"/>',
  mountain: '<path d="M3 19 9.5 8l4 6.5L16 11l5 8Z"/><circle cx="17" cy="6" r="1.6"/>',
  wave: '<path d="M2 12h2.5l2-6 3 12 3-16 3 14 2-8H22"/>',
  script: '<path d="M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M8.5 8h7M8.5 12h7M8.5 16h4"/>',
  rocket: '<path d="M12 3c3.5 2.2 5.5 5.7 5.5 9.5L15 17H9l-2.5-4.5C6.5 8.7 8.5 5.2 12 3Z"/><circle cx="12" cy="10" r="1.7"/><path d="M9 17l-1 4 4-2M15 17l1 4-4-2"/>',
  bar: '<rect x="3" y="9" width="18" height="6" rx="3"/><path d="M3 12h9"/>',
  vr: '<path d="M3 8h18a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-5l-1.5-2h-5L8 16H3a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z"/>',
  brush: '<path d="M14.5 4.5 19.5 9.5 10 19H5v-5Z"/><path d="M12 7l5 5"/>',
  eraser: '<path d="m4 16 9-10 7 7-6 6H8Z"/><path d="M9 11l6 6"/>',
  bucket: '<path d="M5 11 12 4l7 7-7 8Z"/><path d="M19 15c1 1.5 1.5 2.4 1.5 3a1.5 1.5 0 0 1-3 0c0-.6.5-1.5 1.5-3Z"/>',
  swap: '<path d="M7 7h13M16 3l4 4-4 4M17 17H4M8 13l-4 4 4 4"/>',
  move: '<path d="M12 3v18M3 12h18M12 3l-2.5 2.5M12 3l2.5 2.5M12 21l-2.5-2.5M12 21l2.5-2.5M3 12l2.5-2.5M3 12l2.5 2.5M21 12l-2.5-2.5M21 12l-2.5 2.5"/>',
  lasso: '<path d="M12 4c5 0 8.5 2 8.5 5s-3.5 5-8.5 5S3.5 12 3.5 9 7 4 12 4Z"/><path d="M8 14c-1 3 0 5 3 5"/>',
  select: '<path d="M4 4h4M10 4h4M16 4h4v4M20 10v4M20 16v4h-4M14 20h-4M8 20H4v-4M4 14v-4M4 8V4"/>',
  record: '<circle cx="12" cy="12" r="7"/>',
  loop: '<path d="M17 3l3 3-3 3"/><path d="M20 6H8a4 4 0 0 0-4 4v1M7 21l-3-3 3-3"/><path d="M4 18h12a4 4 0 0 0 4-4v-1"/>',
  split: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
  splitv: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 12h18"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  eyeoff: '<path d="M3 3l18 18M10.6 5.2A9.7 9.7 0 0 1 12 5c5 0 9 4.5 10 7a14 14 0 0 1-3 4M6.5 6.8A14 14 0 0 0 2 12c1 2.5 5 7 10 7a9.5 9.5 0 0 0 4-.9"/>',
  drop: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11Z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/>',
  node: '<circle cx="12" cy="12" r="3"/><path d="M12 3v6M12 15v6M3 12h6M15 12h6"/>',
  box: '<rect x="4" y="4" width="16" height="16" rx="2.5"/>',
  tbar: '<path d="M4 7h16M4 12h16M4 17h10"/>',
  bell: '<path d="M6 17V11a6 6 0 0 1 12 0v6l1.5 2h-15Z"/><path d="M10 21a2 2 0 0 0 4 0"/>',
  network: '<rect x="9" y="3" width="6" height="5" rx="1.2"/><rect x="3" y="16" width="6" height="5" rx="1.2"/><rect x="15" y="16" width="6" height="5" rx="1.2"/><path d="M12 8v4M6 16v-4h12v4"/>',
};
export function icon(name, size = 18) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('width', size); s.setAttribute('height', size); s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('fill', 'none'); s.setAttribute('stroke', 'currentColor'); s.setAttribute('stroke-width', '1.7');
  s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round');
  s.innerHTML = ICONS[name] || ICONS.file; // conteúdo estático, nunca vindo do usuário
  return s;
}
export const kindIcon = (kind) => icon({ image: 'image', video: 'video', audio: 'audio', document: 'doc', spreadsheet: 'sheet', presentation: 'slides', archive: 'archive', text: 'file' }[kind] || 'file', 16);

export function toast(msg, type = '') {
  const box = document.getElementById('toasts');
  const el = h('div', { class: 'toast ' + type }, msg);
  box.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; setTimeout(() => el.remove(), 300); }, type === 'err' ? 6000 : 3000);
}

export function modal(title, body, buttons) {
  return new Promise((resolve) => {
    const back = document.activeElement;  // devolve o foco a quem abriu o diálogo
    const close = (v) => { bg.remove(); document.removeEventListener('keydown', onKey); if (back && back.focus && document.contains(back)) { try { back.focus(); } catch (e) { /* ok */ } } resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') close(null); };
    const foot = h('div', { class: 'foot' }, (buttons || []).map((b) => h('button', { class: 'btn ' + (b.cls || ''), onclick: () => close(b.value) }, b.label)));
    const bg = h('div', { class: 'modal-bg', onmousedown: (e) => { if (e.target === bg) close(null); } }, h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': String(title) }, h('h2', null, title), body, foot));
    document.body.appendChild(bg);
    document.addEventListener('keydown', onKey);
    const first = bg.querySelector('input,textarea,select'); if (first) first.focus();
  });
}
export async function confirmDialog(msg, danger = true, okLabel) {
  const v = await modal(t('Confirmar'), h('p', { class: 'muted', style: { margin: 0 } }, msg),
    [{ label: t('Cancelar'), value: false }, { label: okLabel || (danger ? t('Apagar') : t('Continuar')), value: true, cls: danger ? 'danger' : 'primary' }]);
  return v === true;
}

// campo de tags (chips + input)
export function tagsInput(values, onChange, placeholder) {
  let list = (values || []).slice();
  const wrap = h('div', { class: 'tags' });
  const input = h('input', { placeholder: placeholder || t('adicionar tag…') });
  const commit = (raw) => {
    raw.split(/[,;\n]/).map((s) => s.trim().toLowerCase()).filter(Boolean).forEach((v) => { if (!list.includes(v) && list.length < 20) list.push(v); });
    render(); onChange(list.slice());
  };
  function render() {
    wrap.replaceChildren(...list.map((v) => h('span', { class: 'chip solid' }, v, h('span', { class: 'x', onclick: () => { list = list.filter((x) => x !== v); render(); onChange(list.slice()); } }, '×'))), input);
  }
  input.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) { e.preventDefault(); const v = input.value; input.value = ''; commit(v); }
    else if (e.key === 'Backspace' && !input.value && list.length) { list.pop(); render(); onChange(list.slice()); }
  });
  input.addEventListener('blur', () => { if (input.value.trim()) { const v = input.value; input.value = ''; commit(v); } });
  wrap.addEventListener('click', () => input.focus());
  render();
  wrap.get = () => list.slice();
  return wrap;
}

export function seg(options, value, onChange) {
  const el = h('div', { class: 'seg' });
  const paint = (v) => el.replaceChildren(...options.map(([val, label]) => h('button', { type: 'button', class: val === v ? 'on' : '', onclick: () => { paint(val); onChange(val); } }, label)));
  paint(value);
  return el;
}

export function field(label, control, hint) {
  return h('div', { class: 'field' }, label ? h('label', { class: 'f' }, label) : null, control, hint ? h('div', { class: 'hint' }, hint) : null);
}
export function range(min, max, step, value, onInput, fmt) {
  const out = h('output', null, fmt ? fmt(value) : value);
  const inp = h('input', { type: 'range', min, max, step, value });
  inp.addEventListener('input', () => { const v = parseFloat(inp.value); out.textContent = fmt ? fmt(v) : v; onInput(v); });
  return h('div', { class: 'rng' }, inp, out);
}
export function select(options, value, onChange, attrs) {
  const el = h('select', attrs, options.map(([v, l]) => h('option', { value: v, selected: v === value }, l)));
  el.value = value;
  el.addEventListener('change', () => onChange(el.value));
  return el;
}
export function checkbox(label, checked, onChange) {
  const inp = h('input', { type: 'checkbox', checked: !!checked });
  inp.addEventListener('change', () => onChange(inp.checked));
  return h('label', { class: 'check' }, inp, h('span', null, label));
}
export function accordion(title, body, open = false, right) {
  const el = h('div', { class: 'acc' + (open ? ' open' : '') },
    h('div', { class: 'hd', onclick: () => el.classList.toggle('open') }, h('span', { class: 'tt' }, title), right || null, h('span', { class: 'chev' }, icon('chev', 16))),
    h('div', { class: 'bd' }, body));
  return el;
}

export function popover(anchor, content, onClose) {
  const pop = h('div', { class: 'pop' }, content);
  document.body.appendChild(pop);
  // posiciona acima do botão (ou abaixo, se não couber) e reposiciona quando o conteúdo cresce (listas carregadas depois)
  const place = () => {
    // O .pop usa `zoom: var(--z)` (escala da interface) e navegadores diferentes medem left/top ora na escala do elemento, ora na da página: mede quantos px VISUAIS
    // vale 1px de `left`/`top` neste navegador e corrige, assim o menu fica colado no botão em qualquer escala.
    pop.style.left = '0px'; pop.style.top = '0px';
    const b0 = pop.getBoundingClientRect();
    pop.style.left = '100px'; pop.style.top = '100px';
    const b1 = pop.getBoundingClientRect();
    const kx = (b1.left - b0.left) / 100 || 1, ky = (b1.top - b0.top) / 100 || 1;
    const r = anchor.getBoundingClientRect(), w = b1.width, hgt = b1.height;
    const x = Math.max(8, Math.min(innerWidth - w - 8, r.left));
    const top = r.top - hgt - 8 > 8 ? r.top - hgt - 8 : r.bottom + 8;
    const y = Math.max(8, Math.min(innerHeight - hgt - 8, top));
    pop.style.left = (x - b0.left) / kx + 'px';
    pop.style.top = (y - b0.top) / ky + 'px';
  };
  place();
  let ro = null;
  if (typeof ResizeObserver !== 'undefined') { ro = new ResizeObserver(place); ro.observe(pop); }
  const off = (e) => { if (!pop.contains(e.target) && !anchor.contains(e.target)) close(); };
  const close = () => { if (ro) ro.disconnect(); pop.remove(); document.removeEventListener('mousedown', off); if (onClose) onClose(); };
  setTimeout(() => document.addEventListener('mousedown', off), 0);
  pop.close = close;
  return pop;
}

export const fmtBytes = (n) => { if (!n) return '0 B'; const u = ['B', 'KB', 'MB', 'GB']; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return (i ? n.toFixed(n < 10 ? 1 : 0) : n) + ' ' + u[i]; };
export const fmtDate = (iso) => { try { return new Date(iso).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }); } catch (e) { return ''; } };
export function download(filename, text, mime = 'application/json') {
  const a = h('a', { href: URL.createObjectURL(new Blob([text], { type: mime })), download: filename });
  document.body.appendChild(a); a.click(); a.remove();
}
export function debounce(fn, ms) { let tm; return (...a) => { clearTimeout(tm); tm = setTimeout(() => fn(...a), ms); }; }
export const initial = (s) => (String(s || '?').trim()[0] || '?').toUpperCase();
export function gradient(p) {
  const sky = (p && p.sky) || '#2a2a2a', ground = (p && p.ground) || '#111';
  return `linear-gradient(180deg, ${sky} 0%, ${sky} 52%, ${ground} 52%, ${ground} 100%)`;
}
