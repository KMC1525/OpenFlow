// Aplica a aparência escolhida ANTES da primeira pintura (script clássico no <head>): sem piscar de escuro para claro ao abrir.
// O valor vem do cache local da última sessão; depois o servidor (settings.ui) confirma e corrige (ver prefs.js).
(function () {
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;
  function lum(hex) {
    var n = parseInt(hex.slice(1), 16), c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  window.OPENFLOW_APPLY_UI = function (ui) {
    ui = ui || {};
    var r = document.documentElement, theme = ui.theme === 'light' || ui.theme === 'auto' ? ui.theme : 'dark';
    var resolved = theme === 'auto' ? (mq && mq.matches ? 'light' : 'dark') : theme;
    r.dataset.theme = resolved;
    r.dataset.density = ui.density === 'compact' ? 'compact' : 'comfortable';
    r.dataset.motion = ui.motion === 'reduce' || ui.motion === 'full' ? ui.motion : 'auto';
    r.dataset.font = ui.font === 'serif' || ui.font === 'mono' ? ui.font : 'system';
    r.dataset.chat = ui.chat_size === 'small' || ui.chat_size === 'large' ? ui.chat_size : 'medium';
    var scale = [90, 100, 110, 125, 150].indexOf(Number(ui.scale)) >= 0 ? Number(ui.scale) : 100;
    var zoomOk = !window.CSS || !CSS.supports || CSS.supports('zoom', '1.1');
    r.style.setProperty('--z', zoomOk ? String(scale / 100) : '1');
    var accent = /^#[0-9a-f]{6}$/i.test(ui.accent || '') ? ui.accent.toLowerCase() : '';
    if (accent) { r.style.setProperty('--accent-custom', accent); r.style.setProperty('--on-accent-custom', lum(accent) > 0.4 ? '#000' : '#fff'); }
    else { r.style.removeProperty('--accent-custom'); r.style.removeProperty('--on-accent-custom'); }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', resolved === 'light' ? '#f6f6f4' : '#000000');
    var cs = document.querySelector('meta[name="color-scheme"]');
    if (cs) cs.setAttribute('content', resolved);
    try { localStorage.setItem('openflow.ui', JSON.stringify(ui)); } catch (e) { /* navegação privada: tudo bem, o servidor confirma */ }
    window.OPENFLOW_UI = ui;
  };
  var cached = null;
  try { cached = JSON.parse(localStorage.getItem('openflow.ui') || 'null'); } catch (e) { /* ignora */ }
  window.OPENFLOW_APPLY_UI(cached || {});
  if (mq && mq.addEventListener) mq.addEventListener('change', function () { if ((window.OPENFLOW_UI || {}).theme === 'auto') window.OPENFLOW_APPLY_UI(window.OPENFLOW_UI); });
})();

// Aparelho e tela: phone | foldable | tablet | desktop (+ orientação, layout por largura, plataforma, app instalado). Roda antes da primeira pintura e a cada mudança de tela
// (girar, dobrar/desdobrar, redimensionar). O CSS (mobile.css) e o app (mobile.js) leem só estes atributos do <html>.
(function () {
  var mm = function (q) { try { return !!(window.matchMedia && window.matchMedia(q).matches); } catch (e) { return false; } };
  function classify() {
    var ua = navigator.userAgent || '', plat = navigator.platform || '', touch = (navigator.maxTouchPoints || 0) > 0;
    var coarse = mm('(pointer: coarse)') || (touch && !mm('(hover: hover)'));
    var ipad = /iPad/.test(ua) || (plat === 'MacIntel' && (navigator.maxTouchPoints || 0) > 1);   // iPadOS se apresenta como Mac
    var w = window.innerWidth, hgt = window.innerHeight, shortSide = Math.min(screen.width || w, screen.height || hgt);
    var spanning = mm('(horizontal-viewport-segments: 2)') || mm('(vertical-viewport-segments: 2)') || mm('(spanning: single-fold-vertical)') || mm('(spanning: single-fold-horizontal)');
    var foldUa = /SM-F\d|Fold|Flip|Pixel Fold|Razr|Surface Duo|Mate X|Find N|Magic V/i.test(ua);
    var device = 'desktop';
    if (coarse || ipad) {
      if (spanning || foldUa) device = 'foldable';
      else if (ipad || /Tablet|Tab |SM-T|Nexus 7|Nexus 9|Kindle|Silk/i.test(ua) || shortSide >= 600) device = 'tablet';
      else device = 'phone';
    }
    var r = document.documentElement;
    r.dataset.device = device;
    r.dataset.orient = w >= hgt ? 'landscape' : 'portrait';
    r.dataset.layout = w < 600 ? 'compact' : (w < 1000 ? 'medium' : 'expanded');
    r.dataset.fold = device === 'foldable' ? (spanning ? 'spanned' : (w >= 600 ? 'open' : 'closed')) : '';
    r.dataset.platform = /Android/i.test(ua) ? 'android' : (/iPhone|iPad|iPod/.test(ua) || ipad ? 'ios' : 'other');
    r.dataset.standalone = (mm('(display-mode: standalone)') || window.navigator.standalone === true) ? 'yes' : 'no';
    window.OPENFLOW_DEVICE = { device: device, layout: r.dataset.layout, orient: r.dataset.orient, fold: r.dataset.fold, platform: r.dataset.platform, standalone: r.dataset.standalone === 'yes', width: w, height: hgt, dpr: window.devicePixelRatio || 1 };
  }
  window.OPENFLOW_CLASSIFY = classify;
  classify();
  window.addEventListener('resize', classify);
  window.addEventListener('orientationchange', classify);
  ['(horizontal-viewport-segments: 2)', '(display-mode: standalone)'].forEach(function (q) { try { var m = window.matchMedia(q); (m.addEventListener ? m.addEventListener('change', classify) : m.addListener && m.addListener(classify)); } catch (e) { /* sem suporte */ } });
})();
