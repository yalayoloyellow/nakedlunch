// Движок Butterchurn внутри приложения плюс каталог пресетов.
//
// Дизайн (Editor First.dc.html, 2181..2187) грузил движок внешним скриптом
// freestyle-engine.js и разговаривал с ним через DOM: window.__bcSetRenderScale,
// список строк .presetRow в #presetPanel, клик по #btnRandomPreset, ожидание
// готовности опросом (whenEngine, 2849..2857). Внешнего скрипта больше нет —
// движок собран в бандл, сцена держит объект engine и зовёт методы напрямую.
// Поэтому здесь нет ни одного обращения к DOM за пределами своего канваса:
// никаких getElementById, никаких «подождать, пока появится строка списка».
//
// Каталог (все/избранное/недавние + поиск) живёт в памяти движка. Дизайн клал
// избранное и недавние в localStorage (extendo_bc_recent, 2926) — у нас это
// уходит на сервер в nl_view, поэтому файл сам ничего не хранит, а сообщает
// об изменениях колбэками onFavorites/onRecent (решение прожарки 11).
//
// Запись кадров (recOn) — фаза 4, здесь её нет и MediaRecorder не трогаем.

import bcMod from 'butterchurn';
import packBase from 'butterchurn-presets/lib/butterchurnPresets.min.js';
import packExtra from 'butterchurn-presets/lib/butterchurnPresetsExtra.min.js';
import packExtra2 from 'butterchurn-presets/lib/butterchurnPresetsExtra2.min.js';
import packMD1 from 'butterchurn-presets/lib/butterchurnPresetsMD1.min.js';

// butterchurn собран как UMD с __esModule:true — default и есть API с
// createVisualizer. Страховка на случай, если сборщик отдаст модуль как есть.
const BC = bcMod && typeof bcMod.createVisualizer === 'function'
  ? bcMod
  : ((bcMod && bcMod.default) || bcMod);

// дизайн: перекат между пресетами мягкий, не мгновенный
const DEF_BLEND = 2.7;
// ползунок «рендер» в окне (bcRenderScaleSlider, min 25 max 150, defaultValue 70)
const DEF_SCALE = 0.7;
const MIN_SCALE = 0.25;
const MAX_SCALE = 1.5;
// сколько имён держим в «недавних»: список в окне высотой 288px, больше сорока
// строк там всё равно не смотрят, а каждое изменение уезжает на сервер
const MAX_RECENT = 40;
// пересчёт буфера дорогой (пересоздание текстур), поэтому не на каждый пиксель
const RESIZE_DEBOUNCE = 120;

// Паки пресетов собраны webpack-UMD: module.exports — функция со статикой
// getPresets(), без __esModule. ESM-интероп в зависимости от сборщика отдаёт
// то саму функцию, то обёртку {default}. Форму выясняем на месте, а не гадаем.
function packDict(mod) {
  const m = mod && !mod.getPresets && mod.default ? mod.default : mod;
  if (m && typeof m.getPresets === 'function') return m.getPresets();
  if (m && typeof m === 'object') return m;
  return {};
}

const PACKS = [
  ['base', packBase],
  ['extra', packExtra],
  ['extra2', packExtra2],
  ['md1', packMD1],
];

let CATALOG = null;

// Слияние четырёх паков в один каталог. 59 из 87 имён пака MD1 повторяют имена
// базового — это разные версии одного пресета, и молча затирать одну другой
// значит потерять половину пака. Поэтому поздний дубликат живёт с суффиксом
// пака: «Aderrasi - Agitator» и «Aderrasi - Agitator (md1)».
function buildCatalog() {
  const presets = {};
  for (const [label, mod] of PACKS) {
    const dict = packDict(mod);
    for (const name of Object.keys(dict)) {
      let key = presets[name] === undefined ? name : name + ' (' + label + ')';
      // хвостовая страховка: если и суффикс занят — нумеруем, но не теряем
      let n = 2;
      while (presets[key] !== undefined) key = name + ' (' + label + ' ' + n++ + ')';
      presets[key] = dict[name];
    }
  }
  const names = Object.keys(presets).sort((a, b) =>
    a.localeCompare(b, 'en', { numeric: true, sensitivity: 'base' }));
  return { presets, names };
}

// каталог общий на всё приложение: паки уже в бандле, разбирать их повторно
// на каждый вход во фристайл незачем
export function getCatalog() {
  if (!CATALOG) CATALOG = buildCatalog();
  return CATALOG;
}

function uniqStrings(list) {
  const out = [];
  const seen = Object.create(null);
  for (const v of (Array.isArray(list) ? list : [])) {
    const s = typeof v === 'string' ? v : '';
    if (!s || seen[s]) continue;
    seen[s] = 1;
    out.push(s);
  }
  return out;
}

function clampScale(k) {
  const v = parseFloat(k);
  if (isNaN(v)) return DEF_SCALE;
  return Math.max(MIN_SCALE, Math.min(MAX_SCALE, v));
}

/**
 * Движок сцены фристайла.
 *
 * @param {HTMLCanvasElement} canvas — канвас сцены (#bcCanvas в дизайне)
 * @param {AudioNode|null} audioNode — единая шина звука из audio.js (driverBus);
 *        можно передать null и подключить позже методом connectAudio
 * @param {object} [opts] — renderScale, blendTime, textureRatio, dprCap,
 *        favorites, recent, onFavorites, onRecent, onFps, onError
 */
export function createEngine(canvas, audioNode, opts) {
  if (!canvas) throw new Error('движок: не передан канвас сцены');
  const o = opts || {};
  const { presets, names } = getCatalog();

  const dprCap = o.dprCap == null ? 2 : Math.max(1, o.dprCap);
  const textureRatio = o.textureRatio || 1;
  const blendDefault = o.blendTime == null ? DEF_BLEND : o.blendTime;
  const maxRecent = o.maxRecent == null ? MAX_RECENT : Math.max(1, o.maxRecent);

  let scale = clampScale(o.renderScale == null ? DEF_SCALE : o.renderScale);
  let favs = uniqStrings(o.favorites);
  let recent = uniqStrings(o.recent);

  let vis = null;
  let ctx = (audioNode && audioNode.context) || o.audioContext || null;
  let wired = null;      // узел, который уже подключён к визуализатору
  let cur = '';          // имя текущего пресета
  let raf = 0;
  let running = false;
  let dead = false;
  let fps = 0;
  let frames = 0;
  let fpsAt = 0;
  let errs = 0;
  let bufW = 0;
  let bufH = 0;
  let ro = null;
  let roTimer = 0;

  const fire = (name, arg) => {
    const fn = o[name];
    if (typeof fn !== 'function') return;
    // колбэк сцены не должен ронять кадр движка
    try { fn(arg); } catch (e) { console.error('движок: колбэк ' + name, e); }
  };

  // Размер буфера канваса: CSS-размер × devicePixelRatio × ползунок «рендер».
  // dpr режем потолком (по умолчанию 2), иначе на retina 150% дают буфер
  // вчетверо дороже, чем показывает подпись ползунка.
  const measure = () => {
    const r = canvas.getBoundingClientRect();
    const cssW = r.width || canvas.clientWidth || 2;
    const cssH = r.height || canvas.clientHeight || 2;
    const dpr = Math.min(dprCap, window.devicePixelRatio || 1);
    return {
      w: Math.max(2, Math.round(cssW * dpr * scale)),
      h: Math.max(2, Math.round(cssH * dpr * scale)),
    };
  };

  // Butterchurn берёт width/height как размер вывода и виюпортит ими экран,
  // а внутренние текстуры считает как width*pixelRatio*textureRatio. Весь dpr
  // и ползунок уже сидят в размере буфера, поэтому pixelRatio здесь ровно 1 —
  // иначе стоимость кадра умножится на dpr ещё раз, поверх ползунка.
  const applySize = () => {
    const { w, h } = measure();
    if (w === bufW && h === bufH) return false;
    bufW = w;
    bufH = h;
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    if (vis) vis.setRendererSize(w, h, { pixelRatio: 1, textureRatio });
    return true;
  };

  // Визуализатор строится один раз. Второй раз — только если звук приехал
  // позже движка: AudioProcessor у Butterchurn берёт контекст в конструкторе,
  // и без контекста connectAudio уронить его нечем (audible не создан).
  const build = () => {
    if (!canvas.getContext('webgl2')) {
      throw new Error('движок: WebGL2 недоступен, визуализация не запустится');
    }
    const { w, h } = measure();
    bufW = w;
    bufH = h;
    canvas.width = w;
    canvas.height = h;
    vis = BC.createVisualizer(ctx || undefined, canvas, {
      width: w, height: h, pixelRatio: 1, textureRatio,
    });
    // Renderer стартует с blankPreset, поэтому render() безопасен и до
    // первого loadPreset — сцена может показать чёрный кадр, а не упасть.
    if (cur && presets[cur]) vis.loadPreset(presets[cur], 0);
    if (wired) { try { vis.connectAudio(wired); } catch (e) { wired = null; } }
  };

  const ensure = () => {
    if (dead) throw new Error('движок: уже уничтожен');
    if (!vis) build();
    return vis;
  };

  const tick = (ts) => {
    if (!running || dead) return;
    raf = requestAnimationFrame(tick);
    try {
      vis.render();
      errs = 0;
    } catch (e) {
      // битые уравнения пресета сыплются каждый кадр — не заливаем консоль,
      // а честно останавливаем цикл и говорим сцене
      if (++errs >= 3) {
        stop();
        console.error('движок: кадр не рисуется, цикл остановлен', e);
        fire('onError', e);
        return;
      }
    }
    frames++;
    if (!fpsAt) { fpsAt = ts; return; }
    if (ts - fpsAt >= 500) {
      fps = Math.round((frames * 1000) / (ts - fpsAt));
      frames = 0;
      fpsAt = ts;
      fire('onFps', fps);
    }
  };

  const start = () => {
    if (dead || running) return;
    ensure();
    applySize();
    running = true;
    frames = 0;
    fpsAt = 0;
    raf = requestAnimationFrame(tick);
  };

  // честная остановка: кадр не заказан, счётчик обнулён, никаких «фоновых» rAF
  const stop = () => {
    if (!running) return;
    running = false;
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    frames = 0;
    fpsAt = 0;
    fps = 0;
    fire('onFps', 0);
  };

  const pushRecent = (name) => {
    const next = [name].concat(recent.filter((n) => n !== name)).slice(0, maxRecent);
    if (next.length === recent.length && next[0] === recent[0]) return;
    recent = next;
    fire('onRecent', recent.slice());
  };

  const loadPreset = (name, blendTime) => {
    if (!name || !presets[name]) return false;
    ensure();
    vis.loadPreset(presets[name], blendTime == null ? blendDefault : blendTime);
    cur = name;
    errs = 0;
    pushRecent(name);
    return true;
  };

  // случайный пресет — по умолчанию из всего каталога; from:'fav' даёт
  // «случайный из избранного», если оно не пустое (кнопка «случайный» в окне)
  const randomPreset = (blendTime, from) => {
    let pool = names;
    if (from === 'fav') {
      const f = favs.filter((n) => presets[n]);
      if (f.length) pool = f;
    }
    if (!pool.length) return false;
    let pick = pool[Math.floor(Math.random() * pool.length)];
    // не повторяем текущий, пока есть из чего выбрать
    if (pick === cur && pool.length > 1) {
      const i = pool.indexOf(cur);
      pick = pool[(i + 1 + Math.floor(Math.random() * (pool.length - 1))) % pool.length];
    }
    return loadPreset(pick, blendTime);
  };

  // единый список для окна: вкладка + строка поиска, как в дизайне
  const query = (q) => {
    const tab = (q && q.tab) || 'all';
    const needle = String((q && q.q) || '').trim().toLowerCase();
    let base;
    if (tab === 'fav') base = favs.filter((n) => presets[n]);
    else if (tab === 'recent') base = recent.filter((n) => presets[n]);
    else base = names.slice();
    if (!needle) return base;
    return base.filter((n) => n.toLowerCase().indexOf(needle) >= 0);
  };

  const isFav = (name) => favs.indexOf(name) >= 0;

  const toggleFav = (name) => {
    if (!name) return false;
    favs = isFav(name) ? favs.filter((n) => n !== name) : favs.concat([name]);
    fire('onFavorites', favs.slice());
    return isFav(name);
  };

  // гидрация с сервера (nl_view) — молча, без обратного колбэка,
  // иначе загрузка настроек сама же вызовет их перезапись
  const setFavorites = (list) => { favs = uniqStrings(list); };
  const setRecent = (list) => { recent = uniqStrings(list).slice(0, maxRecent); };

  const setRenderScale = (k) => {
    const next = clampScale(k);
    if (next === scale) return scale;
    scale = next;
    if (vis) applySize();
    return scale;
  };

  const resize = () => { if (vis) applySize(); };

  const onGeom = () => {
    if (dead) return;
    if (roTimer) clearTimeout(roTimer);
    roTimer = setTimeout(() => { roTimer = 0; resize(); }, RESIZE_DEBOUNCE);
  };

  if (typeof ResizeObserver === 'function') {
    ro = new ResizeObserver(onGeom);
    ro.observe(canvas);
  }
  // ResizeObserver не видит смену devicePixelRatio при переезде окна
  // на другой монитор — размер в CSS-пикселях тот же, а буфер должен стать другим
  window.addEventListener('resize', onGeom);

  const connectAudio = (node) => {
    if (dead || !node || node === wired) return;   // ровно один раз на узел
    if (!ctx) {
      // движок собран без звука: контекст у Butterchurn задаётся только в
      // конструкторе, поэтому визуализатор пересобираем и возвращаем пресет
      ctx = node.context;
      vis = null;
      wired = null;
      build();
    }
    if (wired) { try { vis.disconnectAudio(wired); } catch (e) { /* узел уже отвалился */ } }
    ensure().connectAudio(node);
    wired = node;
  };

  const dispose = () => {
    if (dead) return;
    stop();
    dead = true;
    if (roTimer) clearTimeout(roTimer);
    roTimer = 0;
    if (ro) { ro.disconnect(); ro = null; }
    window.removeEventListener('resize', onGeom);
    if (vis && wired) { try { vis.disconnectAudio(wired); } catch (e) { /* контекст мог закрыться */ } }
    wired = null;
    // у Butterchurn нет teardown — отпускаем контекст сами, иначе живые
    // текстуры сцены висят до сборки мусора
    try {
      const gl = canvas.getContext('webgl2');
      const lose = gl && gl.getExtension('WEBGL_lose_context');
      if (lose) lose.loseContext();
    } catch (e) { /* контекста уже нет */ }
    vis = null;
  };

  if (audioNode) connectAudio(audioNode);
  else if (ctx) ensure();

  return {
    // каталог
    names,
    has: (name) => !!presets[name],
    query,
    isFav,
    toggleFav,
    favorites: () => favs.slice(),
    recentList: () => recent.slice(),
    setFavorites,
    setRecent,
    // пресеты
    loadPreset,
    randomPreset,
    current: () => cur,
    // цикл и размер
    start,
    stop,
    isRunning: () => running,
    getFps: () => fps,
    setRenderScale,
    getRenderScale: () => scale,
    bufferSize: () => ({ width: bufW, height: bufH }),
    resize,
    // звук и снос
    connectAudio,
    dispose,
    isAlive: () => !dead,
  };
}

export default createEngine;
