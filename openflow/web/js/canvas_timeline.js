// Editor de vídeo do Canvas: bandeja de mídias, prévia ao vivo, linha do tempo (trilhas e clipes) e inspetor do clipe.
// Edita `node.params.timeline` no lugar; a exportação (MP4) é feita pelo servidor com o ffmpeg.
import { t } from './i18n.js';
import { confirmDialog, fill, h, icon, toast } from './ui.js';

const uid = (p) => p + Math.random().toString(36).slice(2, 10);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const r3 = (v) => Math.round(v * 1000) / 1000;
const HEAD = 104;
const PRESETS = [[1280, 720], [1920, 1080], [720, 1280], [1080, 1920], [1080, 1080]];
export const tc = (s) => { s = Math.max(0, s); const m = Math.floor(s / 60); return String(m).padStart(2, '0') + ':' + (s - m * 60).toFixed(1).padStart(4, '0'); };

export function openTimeline(o) {
  return new Promise((finished) => {
    const P = o.node.params, tl = P.timeline, cv = o.cv;
    let sel = '', pps = 70, head = 0, playing = false, raf = 0, last = 0, bin = 'conn';
    const total = () => Math.max(0, ...tl.clips.map((c) => c.start + c.dur));
    const track = (id) => tl.tracks.find((x) => x.id === id);
    const changed = () => { tl.duration = r3(total()); o.onChange(); };

    // ---------------------------------------------------------------------------- arquivo de cada clipe
    function resolve(c) {
      const src = c.node && cv.nodes.find((n) => n.id === c.node);
      if (src) {
        const ids = src.type === 'upload' ? src.params.files : (src.result.state === 'done' ? src.result.assets : []);
        const a = cv.assets.find((x) => x.id === (ids[c.idx] || ids[0]));
        if (a) return a;
      }
      return c.asset ? cv.assets.find((x) => x.id === c.asset) : null;
    }
    const clipKind = (c) => { const tr = track(c.track); if (tr && tr.kind === 'text') return 'text'; const a = resolve(c); return a ? a.kind : 'missing'; };
    const label = (c) => { const k = clipKind(c); if (k === 'text') return c.text || t('Texto'); const a = resolve(c); return a ? (a.name || a.prompt || a.kind) : t('arquivo ausente'); };

    // ---------------------------------------------------------------------------- prévia (palco)
    const stage = h('div', { class: 'tl-stage' });
    const pool = new Map();  // clip.id → { el, media, key }
    const stageWrap = h('div', { class: 'tl-stagewrap' });
    const timeLbl = h('span', null, '00:00.0');
    function fitStage() {
      const w = stageWrap.clientWidth - 24, hh = stageWrap.clientHeight - 24 - 38, ar = P.width / P.height;
      const sw = Math.max(80, Math.min(w, hh * ar));
      stage.style.width = sw + 'px'; stage.style.height = sw / ar + 'px'; stage.style.background = P.bg;
      stage.dataset.scale = sw / P.width;
      sync(head);
    }
    function sync(tm) {
      const k = Number(stage.dataset.scale || 1), live = new Set();
      tl.tracks.forEach((tr, ti) => {
        if (tr.hidden && tr.kind !== 'audio') return;
        for (const c of tl.clips.filter((x) => x.track === tr.id)) {
          const on = tm >= c.start && tm < c.start + c.dur;
          const kind = clipKind(c);
          live.add(c.id);
          let it = pool.get(c.id);
          const a = tr.kind === 'text' ? null : resolve(c);
          const key = tr.kind + '|' + (a ? a.id : c.text);
          if (it && it.key !== key) { it.el.remove(); pool.delete(c.id); it = null; }
          if (!on) { if (it) { it.el.style.display = 'none'; if (it.media && !it.media.paused) it.media.pause(); } continue; }
          if (!it) {
            let el, media = null;
            if (tr.kind === 'text') el = h('div', { class: 'txt' });
            else if (kind === 'image') el = h('img', { src: o.url(a), draggable: 'false' });
            else if (kind === 'video') { el = media = h('video', { src: o.url(a), preload: 'auto', playsinline: true }); }
            else if (kind === 'audio') { el = media = h('audio', { src: o.url(a), preload: 'auto' }); el.style.display = 'none'; }
            else continue;
            stage.appendChild(el); it = { el, media, key }; pool.set(c.id, it);
          }
          const u = tm - c.start;
          const fade = Math.min(c.fade_in > 0 ? u / c.fade_in : 1, c.fade_out > 0 ? (c.dur - u) / c.fade_out : 1, 1);
          if (kind !== 'audio') {
            const s = it.el.style; s.display = ''; s.zIndex = String(ti + 1); s.opacity = String(clamp(c.opacity * fade, 0, 1));
            if (tr.kind === 'text') {
              s.fontSize = c.size * k + 'px'; s.color = c.color; s.top = c.pos === 'top' ? '7%' : c.pos === 'center' ? '50%' : 'auto'; s.bottom = c.pos === 'bottom' ? '7%' : 'auto';
              s.transform = c.pos === 'center' ? 'translateY(-50%)' : ''; s.left = c.x * 50 + '%'; s.background = 'transparent'; it.el.textContent = c.text;
              if (c.bg) { s.background = c.bg + 'a6'; }
            } else {
              s.width = c.scale * 100 + '%'; s.height = c.scale * 100 + '%'; s.left = (50 + c.x * 50) + '%'; s.top = (50 + c.y * 50) + '%'; s.transform = 'translate(-50%,-50%)';
              s.objectFit = c.fit === 'stretch' ? 'fill' : c.fit === 'cover' ? 'cover' : 'contain';
            }
          }
          if (it.media) {
            const m = it.media, want = c.in + u;
            m.volume = clamp(c.volume * fade, 0, 1); m.muted = !!tr.muted || c.volume <= 0;
            if (!playing || Math.abs(m.currentTime - want) > 0.4) { try { m.currentTime = want; } catch (e) { /* ainda carregando */ } }
            if (playing && m.paused) m.play().catch(() => {});
            if (!playing && !m.paused) m.pause();
          }
        }
      });
      for (const [id, it] of pool) if (!live.has(id)) { it.el.remove(); pool.delete(id); }
      timeLbl.textContent = tc(tm) + ' / ' + tc(total());
      playEl.style.left = HEAD + tm * pps + 'px';
    }
    function play(on) {
      playing = on; playBtn.replaceChildren(icon(on ? 'stop' : 'play', 15));
      cancelAnimationFrame(raf);
      if (on) {
        if (head >= total() - 0.05) head = 0;
        last = performance.now();
        const loop = (now) => {
          head += (now - last) / 1000; last = now;
          if (head >= total()) { head = total(); play(false); sync(head); return; }
          sync(head); raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);
      } else { for (const it of pool.values()) if (it.media && !it.media.paused) it.media.pause(); sync(head); }
    }
    const seek = (tm) => { head = clamp(tm, 0, Math.max(total(), 0.1)); if (playing) last = performance.now(); sync(head); };

    // ---------------------------------------------------------------------------- linha do tempo
    const ruler = h('div', { class: 'tl-ruler' });
    const rows = h('div');
    const playEl = h('div', { class: 'tl-play' });
    const inner = h('div', { class: 'tl-in' }, ruler, rows, playEl);
    const scroll = h('div', { class: 'tl-scroll' }, inner);
    const snap = (v, ignore) => {
      const pts = [0, head, ...tl.clips.filter((c) => c.id !== ignore).flatMap((c) => [c.start, c.start + c.dur])], th = 8 / pps;
      const near = pts.find((p) => Math.abs(p - v) < th);
      return near != null ? near : Math.round(v * 20) / 20;
    };
    function paintTL() {
      const width = Math.max(total() + 12, (scroll.clientWidth - HEAD) / pps) * pps;
      inner.style.width = HEAD + width + 'px';
      const step = pps >= 90 ? 1 : pps >= 45 ? 2 : pps >= 22 ? 5 : 10;
      ruler.style.width = width + 'px';
      fill(ruler, Array.from({ length: Math.ceil(width / pps / step) + 1 }, (_, i) => h('i', { style: { left: i * step * pps + 'px' } }, tc(i * step).slice(0, 5))));
      ruler.onpointerdown = (e) => { const r = ruler.getBoundingClientRect(); const go2 = (ev) => seek((ev.clientX - r.left) / pps); go2(e); const mv = (ev) => go2(ev), up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); }; addEventListener('pointermove', mv); addEventListener('pointerup', up); };
      fill(rows, tl.tracks.map((tr) => {
        const lane = h('div', { class: 'tl-lane', dataset: { track: tr.id }, style: { width: width + 'px' } }, tl.clips.filter((c) => c.track === tr.id).map((c) => clipEl(c, tr)));
        lane.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('text/flow-clip')) { e.preventDefault(); lane.classList.add('drop'); } });
        lane.addEventListener('dragleave', () => lane.classList.remove('drop'));
        lane.addEventListener('drop', (e) => {
          lane.classList.remove('drop'); const raw = e.dataTransfer.getData('text/flow-clip'); if (!raw) return; e.preventDefault();
          const at = (e.clientX - lane.getBoundingClientRect().left) / pps;
          addClip(JSON.parse(raw), tr.id, snap(at));
        });
        lane.addEventListener('pointerdown', (e) => { if (e.target === lane) { select(''); seek((e.clientX - lane.getBoundingClientRect().left) / pps); } });
        return h('div', { class: 'tl-row' },
          h('div', { class: 'tl-th' }, h('span', { class: 'nm', title: tr.kind }, tr.name), tr.kind !== 'text' ? h('button', { class: tr.muted ? 'on' : '', title: t('Silenciar'), onclick: () => { tr.muted = !tr.muted; changed(); paintTL(); } }, icon('audio', 13)) : null,
            tr.kind !== 'audio' ? h('button', { class: tr.hidden ? 'on' : '', title: t('Ocultar'), onclick: () => { tr.hidden = !tr.hidden; changed(); paintTL(); sync(head); } }, icon('image', 13)) : null,
            h('button', { title: t('Apagar trilha'), onclick: async () => { if (tl.tracks.length > 1 && (!tl.clips.some((c) => c.track === tr.id) || await confirmDialog(t('Apagar a trilha {n} e os clipes dela?', { n: tr.name })))) { tl.tracks = tl.tracks.filter((x) => x.id !== tr.id); tl.clips = tl.clips.filter((c) => c.track !== tr.id); changed(); paintTL(); sync(head); } } }, icon('x', 12))), lane);
      }));
      playEl.style.left = HEAD + head * pps + 'px';
    }
    function clipEl(c, tr) {
      const kind = clipKind(c), a = tr.kind === 'text' ? null : resolve(c);
      const el = h('div', { class: 'tl-clip ' + kind + (c.id === sel ? ' sel' : ''), dataset: { id: c.id }, style: { left: c.start * pps + 'px', width: Math.max(6, c.dur * pps) + 'px' }, title: label(c) },
        kind === 'image' && a ? h('div', { class: 'bgimg', style: { backgroundImage: `url("${o.url(a)}")` } }) : null,
        h('div', { class: 'lb' }, (c.node ? '🔗 ' : '') + label(c)), h('div', { class: 'h l' }), h('div', { class: 'h r' }));
      el.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        e.preventDefault(); e.stopPropagation(); select(c.id);
        const mode = e.target.classList.contains('l') ? 'l' : e.target.classList.contains('r') ? 'r' : 'm';
        const sx = e.clientX, s0 = c.start, d0 = c.dur, i0 = c.in, trackKind = tr.kind;
        const mv = (ev) => {
          const dt = (ev.clientX - sx) / pps;
          if (mode === 'm') {
            c.start = r3(Math.max(0, snap(s0 + dt, c.id)));
            const lane = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.tl-lane');
            if (lane && lane.dataset.track !== c.track) { const dest = track(lane.dataset.track); if (dest && dest.kind === trackKind) { c.track = dest.id; paintTL(); } }
          } else if (mode === 'r') {
            let end = snap(s0 + d0 + dt, c.id); const a2 = resolve(c);
            if (a2 && a2.duration && a2.kind !== 'image') end = Math.min(end, s0 + (a2.duration - c.in));
            c.dur = r3(Math.max(0.1, end - s0));
          } else {
            const ns = clamp(snap(s0 + dt, c.id), Math.max(0, s0 - i0), s0 + d0 - 0.1), d = ns - s0;
            c.start = r3(ns); c.dur = r3(d0 - d); if (clipKind(c) !== 'image' && clipKind(c) !== 'text') c.in = r3(i0 + d);
          }
          el.style.left = c.start * pps + 'px'; el.style.width = Math.max(6, c.dur * pps) + 'px';
          if (!el.isConnected) { const n = rows.querySelector(`[data-id="${c.id}"]`); if (n) return; }
          playEl.style.left = HEAD + head * pps + 'px';
        };
        const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); changed(); paintTL(); paintInsp(); sync(head); };
        addEventListener('pointermove', mv); addEventListener('pointerup', up);
      });
      return el;
    }
    function select(id) { sel = id; rows.querySelectorAll('.tl-clip').forEach((n) => n.classList.toggle('sel', n.dataset.id === id)); paintInsp(); }
    const selClip = () => tl.clips.find((c) => c.id === sel);

    // ---------------------------------------------------------------------------- operações
    function ensureTrack(kind) {
      let tr = tl.tracks.filter((x) => x.kind === kind).pop();
      if (!tr) { const n = tl.tracks.filter((x) => x.kind === kind).length + 1; tr = { id: uid('t_'), kind, name: { video: 'V', audio: 'A', text: 'T' }[kind] + n, muted: false, hidden: false }; tl.tracks.push(tr); }
      return tr;
    }
    function newTrack(kind) { const n = tl.tracks.filter((x) => x.kind === kind).length + 1; tl.tracks.push({ id: uid('t_'), kind, name: { video: 'V', audio: 'A', text: 'T' }[kind] + n, muted: false, hidden: false }); changed(); paintTL(); }
    function addClip(item, trackId, start) {
      const kind = item.text != null ? 'text' : item.kind;
      const want = kind === 'text' ? 'text' : kind === 'audio' ? 'audio' : 'video';
      let tr = trackId ? track(trackId) : null;
      if (tr && tr.kind !== want) { toast(t('Esse arquivo não cabe nessa trilha.'), 'err'); return; }
      tr = tr || tl.tracks.filter((x) => x.kind === want).pop() || ensureTrack(want);
      const lastEnd = Math.max(0, ...tl.clips.filter((c) => c.track === tr.id).map((c) => c.start + c.dur));
      const dur = kind === 'text' ? 3 : kind === 'image' ? 3 : (item.duration || 3);
      const c = { id: uid('c_'), track: tr.id, asset: item.asset || '', node: item.node || '', idx: item.idx || 0, start: r3(start != null ? start : (want === 'video' ? lastEnd : head)), dur: r3(dur), in: 0, volume: 1, fade_in: 0, fade_out: 0, opacity: 1, fit: 'contain', x: 0, y: 0, scale: 1,
        text: item.text || '', size: 48, color: '#ffffff', bg: kind === 'text' ? '#000000' : '', pos: 'bottom' };
      tl.clips.push(c); changed(); paintTL(); select(c.id); sync(head);
    }
    function split() {
      const c = selClip(); if (!c || head <= c.start + 0.05 || head >= c.start + c.dur - 0.05) return toast(t('Posicione a linha de reprodução dentro do clipe selecionado.'), 'err');
      const cut = head - c.start, b = Object.assign({}, c, { id: uid('c_'), start: r3(head), dur: r3(c.dur - cut), fade_in: 0 });
      if (clipKind(c) === 'video' || clipKind(c) === 'audio') b.in = r3(c.in + cut);
      c.dur = r3(cut); c.fade_out = 0; tl.clips.push(b); changed(); paintTL(); select(b.id); sync(head);
    }
    function remove() { if (!sel) return; tl.clips = tl.clips.filter((c) => c.id !== sel); sel = ''; changed(); paintTL(); paintInsp(); sync(head); }
    function dup() { const c = selClip(); if (!c) return; const d = Object.assign({}, c, { id: uid('c_'), start: r3(c.start + c.dur) }); tl.clips.push(d); changed(); paintTL(); select(d.id); }

    // ---------------------------------------------------------------------------- bandeja de mídias
    const binBox = h('div', { class: 'lst' });
    function binItem(it) {
      const a = it.asset, isText = it.text != null;
      const payload = isText ? { text: it.text, node: it.node } : { kind: a.kind, asset: a.id, node: it.node || '', idx: it.idx || 0, duration: a.duration || 0 };
      const pv = isText ? icon('type', 18) : a.kind === 'image' ? h('img', { src: o.url(a), loading: 'lazy', draggable: 'false' }) : a.kind === 'video' ? h('video', { src: o.url(a) + '#t=0.1', preload: 'metadata', muted: true }) : icon('audio', 18);
      return h('div', { class: 'tl-item', draggable: 'true', title: t('Arraste para uma trilha ou clique duas vezes para adicionar'), ondragstart: (e) => { e.dataTransfer.setData('text/flow-clip', JSON.stringify(payload)); e.dataTransfer.effectAllowed = 'copy'; }, ondblclick: () => addClip(payload) },
        h('div', { class: 'pv' }, pv), h('div', { class: 'tx' }, h('b', null, isText ? it.text.slice(0, 40) : a.name), h('i', null, (it.label ? it.label + ' · ' : '') + (isText ? t('texto (legenda)') : a.kind + (a.duration ? ' · ' + a.duration.toFixed(1) + 's' : '')))),
        h('button', { class: 'btn ghost icon sm', onclick: () => addClip(payload) }, icon('plus', 13)));
    }
    function paintBin() {
      const items = bin === 'conn' ? o.connected() : [...cv.assets].reverse().map((a) => ({ asset: a }));
      fill(binBox, items.length ? items.map(binItem) : h('div', { class: 'dim small', style: { padding: '10px' } }, bin === 'conn' ? t('Ligue nós na entrada “Clipes” do Editor e execute-os: as saídas aparecem aqui (e acompanham quando forem geradas de novo).') : t('Nenhum arquivo no projeto ainda.')));
      binTabs.querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.k === bin));
    }
    const binTabs = h('div', { class: 'tabs' },
      h('button', { dataset: { k: 'conn' }, onclick: () => { bin = 'conn'; paintBin(); } }, t('Ligados')),
      h('button', { dataset: { k: 'all' }, onclick: () => { bin = 'all'; paintBin(); } }, t('Todos')));

    // ---------------------------------------------------------------------------- inspetor
    const insp = h('div', { class: 'tl-insp' });
    function num(c, key, min, max, step, onSet) {
      const i = h('input', { type: 'number', min, max, step, value: c[key] });
      i.addEventListener('keydown', (e) => e.stopPropagation());
      i.addEventListener('input', () => { const v = parseFloat(i.value); if (Number.isNaN(v)) return; c[key] = r3(clamp(v, min, max)); if (onSet) onSet(); changed(); paintTL(); sync(head); });
      return i;
    }
    const fld = (l, ctl) => h('div', { class: 'fld' }, h('span', null, l), ctl);
    function paintInsp() {
      const c = selClip();
      if (!c) {
        fill(insp, h('h4', null, t('Vídeo')),
          fld(t('Resolução'), (() => { const s = h('select'); PRESETS.forEach(([w, hh]) => s.append(h('option', { value: w + 'x' + hh, selected: w === P.width && hh === P.height }, w + '×' + hh))); if (!PRESETS.some(([w, hh]) => w === P.width && hh === P.height)) s.append(h('option', { selected: true }, P.width + '×' + P.height)); s.onchange = () => { const [w, hh] = s.value.split('x').map(Number); if (w && hh) { P.width = w; P.height = hh; changed(); fitStage(); } }; return s; })()),
          fld('FPS', (() => { const s = h('select'); [24, 30, 60].forEach((f) => s.append(h('option', { value: f, selected: f === P.fps }, f))); s.onchange = () => { P.fps = Number(s.value); changed(); }; return s; })()),
          fld(t('Fundo'), (() => { const i = h('input', { type: 'color', value: P.bg }); i.oninput = () => { P.bg = i.value; changed(); fitStage(); }; return i; })()),
          h('div', { class: 'dim small', style: { marginTop: '12px' } }, t('Selecione um clipe para editar. Arraste as bordas para cortar, o meio para mover. Espaço reproduz; S divide; Delete apaga.')));
        return;
      }
      const kind = clipKind(c), vis = kind === 'image' || kind === 'video', snd = kind === 'video' || kind === 'audio';
      const body = [h('h4', null, kind === 'text' ? t('Legenda') : label(c)),
        fld(t('Início (s)'), num(c, 'start', 0, 36000, 0.1)), fld(t('Duração (s)'), num(c, 'dur', 0.1, 36000, 0.1))];
      if (kind === 'video' || kind === 'audio') body.push(fld(t('Corte inicial (s)'), num(c, 'in', 0, 36000, 0.1)));
      if (snd) body.push(fld(t('Volume'), num(c, 'volume', 0, 2, 0.05)));
      body.push(fld(t('Fade in (s)'), num(c, 'fade_in', 0, 30, 0.1)), fld(t('Fade out (s)'), num(c, 'fade_out', 0, 30, 0.1)));
      if (vis || kind === 'text') body.push(fld(t('Opacidade'), num(c, 'opacity', 0, 1, 0.05)), fld(t('Posição X'), num(c, 'x', -1, 1, 0.05)));
      if (vis) {
        body.push(fld(t('Posição Y'), num(c, 'y', -1, 1, 0.05)), fld(t('Escala'), num(c, 'scale', 0.1, 4, 0.05)),
          fld(t('Ajuste'), (() => { const s = h('select'); [['contain', t('Conter')], ['cover', t('Preencher')], ['stretch', t('Esticar')]].forEach(([v, l]) => s.append(h('option', { value: v, selected: v === c.fit }, l))); s.onchange = () => { c.fit = s.value; changed(); sync(head); }; return s; })()));
      }
      if (kind === 'text') {
        const ta = h('textarea'); ta.value = c.text; ta.addEventListener('keydown', (e) => e.stopPropagation()); ta.oninput = () => { c.text = ta.value; changed(); paintTL(); sync(head); };
        body.push(fld(t('Texto'), ta), fld(t('Tamanho'), num(c, 'size', 8, 300, 2)),
          fld(t('Cor'), (() => { const i = h('input', { type: 'color', value: c.color }); i.oninput = () => { c.color = i.value; changed(); sync(head); }; return i; })()),
          fld(t('Fundo'), (() => { const i = h('input', { type: 'color', value: c.bg || '#000000' }); i.oninput = () => { c.bg = i.value; changed(); sync(head); }; const x = h('button', { class: 'btn sm', onclick: () => { c.bg = ''; changed(); sync(head); } }, t('Sem')); return h('div', { class: 'row nw' }, i, x); })()),
          fld(t('Posição'), (() => { const s = h('select'); [['top', t('Topo')], ['center', t('Centro')], ['bottom', t('Base')]].forEach(([v, l]) => s.append(h('option', { value: v, selected: v === c.pos }, l))); s.onchange = () => { c.pos = s.value; changed(); sync(head); }; return s; })()));
      }
      body.push(h('div', { class: 'row', style: { marginTop: '10px' } },
        h('button', { class: 'btn sm', onclick: split }, icon('scissors', 13), t('Dividir')), h('button', { class: 'btn sm', onclick: dup }, icon('copy', 13), t('Duplicar')), h('button', { class: 'btn sm danger', onclick: remove }, icon('trash', 13), t('Apagar'))));
      if (c.node) body.push(h('div', { class: 'dim small', style: { marginTop: '8px' } }, '🔗 ' + t('Ligado a um nó: usa sempre a saída mais recente dele.')));
      fill(insp, body);
    }

    // ---------------------------------------------------------------------------- montagem da janela
    const playBtn = h('button', { class: 'btn icon sm', title: t('Reproduzir (espaço)'), onclick: () => play(!playing) }, icon('play', 15));
    const zoom = h('input', { type: 'range', min: 20, max: 220, value: pps, oninput: () => { pps = Number(zoom.value); paintTL(); sync(head); } });
    const bar = h('div', { class: 'tl-bar' }, playBtn, h('div', { class: 'tl-ctl' }, timeLbl), h('span', { class: 'grow' }),
      h('button', { class: 'btn sm', title: t('Dividir o clipe na linha de reprodução (S)'), onclick: split }, icon('scissors', 13), t('Dividir')),
      h('button', { class: 'btn sm', onclick: remove }, icon('trash', 13), t('Apagar clipe')),
      h('span', { class: 'dim small' }, t('Zoom')), zoom,
      h('button', { class: 'btn sm', onclick: () => newTrack('video') }, icon('plus', 12), t('Vídeo')),
      h('button', { class: 'btn sm', onclick: () => newTrack('audio') }, icon('plus', 12), t('Áudio')),
      h('button', { class: 'btn sm', onclick: () => newTrack('text') }, icon('plus', 12), t('Texto')),
      h('button', { class: 'btn sm', onclick: () => addClip({ text: t('Sua legenda aqui') }) }, icon('type', 13), t('Legenda')));

    const bg = h('div', { class: 'tl-bg cv-pg' });
    const close = () => { play(false); document.removeEventListener('keydown', key); bg.remove(); finished(); };
    const key = (e) => {
      if (e.target.closest('input,textarea,select')) return;
      if (e.key === ' ') { e.preventDefault(); play(!playing); } else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); remove(); }
      else if (e.key.toLowerCase() === 's') split(); else if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft') seek(head - 0.1); else if (e.key === 'ArrowRight') seek(head + 0.1);
    };
    stageWrap.append(stage, h('div', { class: 'tl-ctl' }, h('span', null, P.width + '×' + P.height + ' · ' + P.fps + ' fps')));
    fill(bg,
      h('div', { class: 'tl-hd' }, icon('film', 18), h('h2', null, o.node.title || t('Editor')), h('span', { class: 'grow' }),
        h('button', { class: 'btn', title: t('Monta uma linha do tempo com as saídas dos nós ligados'), onclick: async () => {
          if (tl.clips.length && !(await confirmDialog(t('Montar automaticamente substitui a linha do tempo atual. Continuar?'), false, t('Substituir')))) return;
          try { const n = await o.autofill(); tl.tracks = n.tracks; tl.clips = n.clips; sel = ''; changed(); paintTL(); paintBin(); paintInsp(); sync(head); if (!n.clips.length) toast(t('Nada para montar: execute os nós ligados ao Editor primeiro.'), 'err'); } catch (e) { toast(e.message, 'err'); }
        } }, icon('wand', 14), t('Montar automaticamente')),
        h('button', { class: 'btn primary', onclick: () => { close(); o.exportNow(); } }, icon('download', 14), t('Exportar vídeo')),
        h('button', { class: 'btn', onclick: close }, t('Fechar'))),
      h('div', { class: 'tl-mid' }, h('div', { class: 'tl-bin' }, binTabs, binBox), stageWrap, insp),
      h('div', { class: 'tl-bot' }, bar, scroll));
    document.body.appendChild(bg); document.addEventListener('keydown', key);
    new ResizeObserver(() => fitStage()).observe(stageWrap);
    paintBin(); paintTL(); paintInsp(); fitStage();
  });
}
