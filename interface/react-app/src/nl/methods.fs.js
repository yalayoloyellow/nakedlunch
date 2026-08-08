// Логика сцены фристайла из дизайна «Editor First» (project-notes/mockups/
// design-v2/Editor First.dc.html) — миксин: интегратор делает
// Object.assign(Nakedlunch.prototype, fsMethods).
//
// Что перенесено дословно (строки дизайна):
//   2183..2260 — FSCOLORS, fsTog, refs сцены/строки/обёртки, bandLater,
//                paintLine, SELBG, paintBand;
//   2256..2400 — slider, vowelCount, trimWords, cutupBag, makeFsLines,
//                fsAdvance, bcAutoLoop, fsAutoLoop, fitLine, textWarpRef,
//                postfxRef;
//   2439..2605 — acPeriod, camRef/camStart/camStop, grainRef/grainLoop/
//                drawGrain, fsInnerRef, ASPECTS/parseAspect/fitStage/
//                watchStage/sizeBuffers, srcChunksList;
//   2606..2690 — FONTS_BASE/FONTS_EXTRA, cfgNumVal, fsv/setFsv, pushScene,
//                autoColorLoop/acStep/acBeat, harvestFonts/pickFont.
//
// Осознанные отступления от дизайна (моков нет — данные с бэка):
//   1) makeFsLines, источник «генератор»: вместо мок-пула STANZAS —
//      настоящий POST /api/generate с буфером-префетчем (genFsLines/fsFill/
//      fsTake). КАЖДАЯ реально показанная строка уходит в markShownQueue
//      (решение прожарки 7: в историю попадает то, что было на экране —
//      во фристайле тоже);
//   2) rhymeTail дизайна НЕ перенесён: стыки строк во фристайле клиентски не
//      рифмуем — рифма живёт на бэке, клиентская подмена хвоста была моком;
//   3) cutupBag/«Классика» остаётся КЛИЕНТСКИМ кат-апом (осознанный режим
//      фристайла), но мешок собирается из того, что реально есть у клиента,
//      а не из мок-корпуса. Серверная «классика» — другая механика (knob
//      classic в /api/generate), она живёт в генераторе, не здесь;
//   4) шрифты: FONTS_BASE/FONTS_EXTRA перенесены, но Google-шрифты НЕ грузим
//      (инвариант офлайна) — harvestFonts показывает только те семейства,
//      которые реально есть в системе, плюс загруженные пользователем файлы
//      (FontFace);
//   5) запись (recOn/recLock) — ФАЗА 4, живёт в methods.fsrec.js: этот файл
//      её больше не касается вовсе, кнопка btnRecord зовёт recToggle().
//
// Соседние модули фазы 3 (их методы вызываются защищённо, через if):
//   freestyle/audio.js  — микрофон, трек, аудио-граф;
//   freestyle/engine.js — Butterchurn: loadEngine/bootFs/topUpFs/syncEngine,
//                         пресеты, poke, профили сцены;
//   методы палитры (loadPal/applyPal/pickPal) — модуль панелей.

import * as api from './api.js';
import { создатьВарп, испечьТекст } from './freestyle/warpgl.js';
import { журнал } from './methods.fsglue.js';

// ---- вспомогательное ------------------------------------------------------

// живое значение ручки окна (state.live пишет onCardInput модуля панелей);
// дизайн, строка 3077 — здесь тот же читатель, чтобы сцена не зависела от
// порядка подмешивания миксинов
function live(c, key, dflt) {
  var s = c.state.live || {}, v = s[key];
  if (v == null) v = (c._live || {})[key];
  return v == null || isNaN(v) ? dflt : v;
}

export const fsMethods = {
  // ---- константы дизайна ----
  FSCOLORS: ['по теме', '#ffffff', '#ff5577', '#34d399', '#a78bfa', '#fb923c'],
  SELBG: { 'белая': '#ffffff', 'чёрная': '#101010', 'плашка': 'var(--panel, #2436e0)' },
  // ручки окон — единственный источник правды: подписи, свои фильтры, CSS-переменные сцены
  FS_DEF: { grad: 0, sat: 100, con: 100, taber: 1, ttiltH: 100, ttiltV: 100, gsize: 1, ghard: 100, gblur: 0, expoBc: 100, expoBg: 100, expoPost: 100, acSpeed: 25, acEase: 60, expo: 100, tiltH: 100, tiltV: 100, srcWords: 6, fsSec: 3.2, fsPer: 2, camOp: 100, camTiltH: 100, camTiltV: 100 },
  FSLIVE: { glowSlider: 'glow', textBlurSlider: 'textBlur', textDistortSlider: 'distort', fsScaleSlider: 'scale', postfxBlurSlider: 'postfxBlur', postfxBendSlider: 'postfxBend' },
  CAM_BLENDS: ['normal', 'screen', 'multiply', 'overlay', 'difference', 'hard-light', 'soft-light', 'luminosity', 'color-dodge'],
  GRAIN_FPS: [15, 24, 25, 30, 50, 60, 120, 144, 0],
  ASPECTS: { '9:16': 9 / 16, '16:9': 16 / 9, '4:3': 4 / 3, '1:1': 1 },
  FONTS_BASE: ['JetBrains Mono', 'Georgia', 'Helvetica'],
  // Гарнитуры дизайна. Google-шрифты не подгружаются (офлайн-инвариант): список
  // фильтруется по фактическому наличию в системе — установленное у пользователя
  // появится само, отсутствующее честно не показывается.
  FONTS_EXTRA: ['Unbounded', 'Russo One', 'Oswald', 'Rubik', 'Playfair Display', 'Cormorant', 'Yeseva One', 'Alegreya', 'PT Serif', 'Bad Script', 'Marck Script', 'Podkova'],

  // размер пачки генерации (буфер строк фристайла)
  // РАЗМЕР ПАЧКИ (Раунд 56, ПОСЛЕ ЗАМЕРА НА РАБОЧЕЙ МАШИНЕ).
  //
  // Было 12 строк за поход — при четырёх строках на экран и смене раз в
  // секунду это три секунды показа, то есть генератор дёргался постоянно.
  //
  // Я подняла до 400, рассудив, что «платится просмотр корпуса, один раз за
  // вызов, а не за строку». ЭТО ОКАЗАЛОСЬ НЕВЕРНО, и журнал с рабочей машины
  // сказал это прямо: «пачка 400 строк за 49444 мс». Цена растёт ПРЯМО
  // ПРОПОРЦИОНАЛЬНО — 0.124 с на строку, потому что отбор строит выдачу
  // блоками, и блоков ровно столько, сколько строк просят. Сорок девять
  // секунд с пустым буфером — это и есть «текста нет вовсе».
  //
  // ВТОРОЙ ЗАМЕР НА РАБОЧЕЙ МАШИНЕ ОПРОВЕРГ И ЭТО. Три точки:
  //   12 строк — 14.5 с (1.21 с на строку)
  //   60 строк — 34.2 с (0.57 с на строку)
  //  400 строк — 49.4 с (0.124 с на строку)
  // То есть в каждом походе есть ОГРОМНАЯ ПОСТОЯННАЯ ПЛАТА — около двенадцати
  // секунд, просмотр корпуса, — и только сверх неё плата за строки. Значит
  // мелкая пачка не «дешевле», а строго ХУЖЕ: постоянную плату платим часто, а
  // показа получаем мало. Шестьдесят было худшим из двух миров.
  //
  // Фристайл съедает четыре строки в секунду; генератор на мелкой пачке даёт
  // меньше одной. Успевать он начинает только на крупной, где постоянная плата
  // размазана. Двести — компромисс: набор порядка полуминуты против пятидесяти
  // секунд показа, и пустой экран при промахе вдвое короче, чем на четырёхстах.
  //
  // Настоящее лечение не здесь, а в постоянной плате: в одной сессии фристайла
  // тема и крутилки НЕ МЕНЯЮТСЯ, значит просмотр корпуса можно посчитать один
  // раз и переиспользовать. Это работа на бэке, записана в BACKLOG.
  FS_BATCH: 200,
  // ПЕРВАЯ пачка — маленькая: она между запуском и первой строкой на экране,
  // и ждать её пользователь будет глядя в пустоту. Раунд 57: было 8. Замерено на
  // прогретом сервере: shortlist 8 — 0.25 с, shortlist 200 — 1.3–4.2 с.
  // Значит первая строка стоит ровно один короткий запрос, а не «полминуты
  // набора», как думалось, — четырёх хватает, дальше догоняет FS_BATCH.
  FS_BATCH_FIRST: 4,
  // Запас подачи в СЕКУНДАХ показа: осталось меньше — дозаказ. Раунд 37.
  // Раньше порог был «в буфере осталось ≤3 строки», но с Раунда 36 строка
  // перестала быть единицей показа: при шаге «слова» одна строка — это 4–8
  // тактов, при шаге «строки» и восьми разом — восьмая часть такта. Один и тот
  // же порог означал то минуту запаса, то меньше одного экрана. Секунды — то,
  // что порог и должен мерить: сколько времени сцена продержится, пока идёт
  // дозаказ (замерено: генерация 0.5–1.4 с, так что 25 с — запас с большим
  // избытком, но и лишних заявок не плодит).
  // Порог дозаказа поднят до 90 секунд (Раунд 56): набор крупной пачки идёт
  // полминуты и дольше, и просыпаться за 25 секунд до конца запаса значило бы
  // гарантированно упереться в пустой экран.
  FS_LEAD_SEC: 90,
  // Слов в строке, пока буфер пуст и мерить нечего.
  FS_WORDS_GUESS: 6,
  // Длина синтетической строки клиентского кат-апа. Это НЕ настройка
  // генерации: кат-ап собирает строку из случайных слов мешка, и её длина —
  // свойство самого приёма. В шаге «слова» она вообще не видна, потому что
  // строка тут же разбирается на слова.
  FS_CUTUP_WORDS: 12,

  // ---- доступ к сцене ----
  fsStage() { return document.getElementById('freestyle-stage'); },
  fsTog(k) { var p = {}; p[k] = !this.state[k]; this.setState(p); },
  // значение движкового ползунка по id; нет элемента — дефолт дизайна
  slider(id, dflt) { var el = document.getElementById(id); var v = el ? parseFloat(el.value) : NaN; return isNaN(v) ? dflt : v; },
  // живое значение ручки окна — метод-обёртка (дизайн, строка 3077)
  L(key, dflt) { return live(this, key, dflt); },
  cfgNumVal(k, dflt) { var v = parseFloat((this.cfg() || {})[k]); return isNaN(v) ? dflt : v; },
  fsv(k) { var v = (this.state.fsv || {})[k]; return v == null ? this.FS_DEF[k] : v; },
  setFsv(k, v) {
    var next = Object.assign({}, this.state.fsv); next[k] = v;
    var self = this;
    this.setState({ fsv: next }, function () { self.pushScene(); if (k === 'taber' || k === 'expo' || k === 'ttiltH' || k === 'ttiltV') self.fitLine(); });
    if (this.fsВарп) this.fsВарп(this._lineTxt || '');
  },

  // ---- refs ----
  // В дизайне это стрелки-поля класса (this связан сам). В миксине методы
  // лежат на прототипе, поэтому связываем вручную и КЭШИРУЕМ: новая функция на
  // каждый рендер заставила бы React дёргать ref(null)/ref(el) каждый кадр —
  // fsWrapRef при этом пересоздавал бы ResizeObserver и перезапускал fitLine.
  // Разметка берёт ref так: ref={c.fsRef('fsWrapRef')}
  fsRef(name) {
    var m = this._fsRefs || (this._fsRefs = {});
    if (!m[name]) { var self = this; m[name] = function (el) { self[name](el); }; }
    return m[name];
  },
  fsStageRef(el) { this._fsStage = el; },
  fsLineRef(el) { this._fsLine = el; },
  fsInnerRef(el) { this._fsInner = el; },
  warpRef(el) {
    if (this._warpХолст === el) return;
    if (this._варп) { this._варп.уничтожить(); this._варп = null; }
    this._warpХолст = el;
    if (el) this.fsВарп(this._lineTxt || '');
  },
  // muted у <video> React ставит пропом ненадёжно, а без него autoplay блокируется
  camRef(el) { this._cam = el; if (el) el.muted = true; },
  grainRef(el) { this._grain = el; this.grainLoop(); },
  textWarpRef(el) { this._twEl = el; },
  postfxRef(el) { this._pfEl = el; },
  fsWrapRef(el) {
    this._fsWrap = el;
    if (this._lineObs) { this._lineObs.disconnect(); this._lineObs = null; }
    if (!el) return;
    this.fitLine();
    // подложку строим по реальным прямоугольникам строки, а шрифт и масштаб из профиля приезжают
    // позже самой строки — поэтому не один замер при загрузке, а перерисовка на каждое изменение размера
    var sharp = el.querySelector('[data-fssharp]');
    if (sharp && window.ResizeObserver) {
      this._lineObs = new ResizeObserver(() => this.paintBand());
      this._lineObs.observe(sharp);
    }
    this.bandLater();
    if (!this._lineTxt) this.fsAdvance();
  },

  // ---- строка на сцене ----
  // догоняющие перерисовки: кадр, оба типичных момента подгрузки шрифта и готовность шрифтов
  bandLater() {
    var self = this;
    requestAnimationFrame(function () { self.paintBand(); });
    setTimeout(function () { self.paintBand(); }, 160);
    setTimeout(function () { self.paintBand(); }, 520);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { self.paintBand(); });
  },
  // текст слоёв строки — императивно (React рендерит их пустыми): слои читает
  // и движок, и paintBand по фактическим прямоугольникам.
  // Возвращает true, если текст ДЕЙСТВИТЕЛЬНО сменился — по этому признаку
  // fsAdvance решает, что строка была показана (решение прожарки 7)
  // ПОЧЕМУ СТРОКИ НЕ ВИДНО (Раунд 57). отчёт: текста нет даже с выключенным визуализатором., «он появился на секунду и опять куда-то пропал». А журнал
  // при этом честно пишет смену за сменой — то есть текст ПИШЕТСЯ, но не
  // виден. Гадать, чем именно он погашен, я не буду: спрашиваем браузер про
  // те четыре вещи, которыми строку вообще можно спрятать, — цвет, прозрачность,
  // масштаб обёртки и фактический прямоугольник. Одна строка в журнале вместо
  // ещё одного круга догадок.
  fsВидно(wrap) {
    try {
      var sharp = wrap.querySelector('[data-fssharp]');
      if (!sharp) return 'резкого слоя НЕТ';
      var cs = getComputedStyle(sharp), cw = getComputedStyle(wrap);
      var r = sharp.getBoundingClientRect();
      var shell = this._fsStage && this._fsStage.closest ? this._fsStage.closest('div[style*="z-index: 0"]') : null;
      var ss = shell ? getComputedStyle(shell) : null;
      return 'цвет ' + cs.color + ' · прозр ' + cs.opacity + '/' + cw.opacity
        + (ss ? '/' + ss.opacity + ' ' + ss.visibility : '')
        + ' · масштаб ' + cw.transform
        + ' · ' + Math.round(r.width) + '×' + Math.round(r.height)
        + ' в (' + Math.round(r.left) + ',' + Math.round(r.top) + ')'
        + ' · знаков ' + (sharp.textContent || '').length
        + ' · фильтр ' + (cs.filter || 'нет') + ' · ' + (this._фильтрыОтвет || '—');
    } catch (e) { return 'осмотр не удался: ' + e; }
  },

  // НЕРИСУЕМЫЙ ФИЛЬТР НЕ ИМЕЕТ ПРАВА СТИРАТЬ ТЕКСТ (Раунд 57).
  //
  // По спецификации фильтров ссылка на несуществующий <filter> означает «не
  // рисовать элемент вообще». При этом браузер честно отдаёт и цвет, и
  // прозрачность, и прямоугольник — ровно то, что показал осмотр у пользователя:
  // белый, непрозрачный, 867×111 на экране, пятьдесят знаков, и не видно
  // ничего. Такая ссылка обязана оборачиваться потерей ЭФФЕКТА, а не потерей
  // строки: строка — это то, ради чего всё остальное существует.
  fsФильтрыЖивы(sharp) {
    var цепь = getComputedStyle(sharp).filter || '';
    var ссылки = цепь.match(/url\(["']?#([^)"']+)["']?\)/g) || [];
    var мёртвые = [];
    for (var i = 0; i < ссылки.length; i++) {
      var id = ссылки[i].replace(/^url\(["']?#/, '').replace(/["']?\)$/, '');
      if (!document.getElementById(id)) мёртвые.push(id);
    }
    if (!мёртвые.length) return 'фильтры на месте (' + ссылки.length + ')';
    // Чиним на месте: выкидываем мёртвые ссылки из цепочки, остальное
    // (размытие, яркость) остаётся работать.
    var чистая = цепь;
    for (var j = 0; j < мёртвые.length; j++) {
      чистая = чистая.replace(new RegExp('url\\(["\']?#' + мёртвые[j] + '["\']?\\)', 'g'), '');
    }
    sharp.style.filter = чистая.trim() || 'none';
    return 'МЁРТВЫЕ ФИЛЬТРЫ: ' + мёртвые.join(', ') + ' — выкинуты, текст возвращён';
  },

  // Текст в слои — по одному месту записи на все три (Раунд 57).
  fsПисатьСлои(wrap, t) {
    var layers = wrap.querySelectorAll('[data-fsline]');
    for (var i = 0; i < layers.length; i++) layers[i].textContent = t;
    return layers;
  },

  // СДВИГ ЗНАКОВ ВМЕСТО ФИЛЬТРА — ПРОБОВАЛИ И СНЯЛИ (Раунд 57). Он был почти
  // бесплатным (38 мс против 265 у фильтра, замер на стенде), но оценка: искажение получилось некрасивым..
  // И он прав по существу: фильтр плавит очертания букв ИЗНУТРИ, а сдвиг двигает
  // их целиком — это не то же самое явление, а его грубая подделка. Дешевизна не
  // оправдывает подмену эффекта, ради которого он крутил эту ручку.

  // СТРОКА НА ВИДЕОКАРТЕ (Раунд 57). Замеры и грабли — в freestyle/warpgl.js.
  // сверка бок о бок с исходным SVG-фильтром: выглядит идентично, разницы нет..
  //
  // Падать здесь нельзя ни при каких обстоятельствах: не поднялся слой — ставим
  // `_варпЖив = false`, перерисовываемся, и работает прежний путь фильтром.
  // Хуже по цене, но рабочий; молча чёрный экран — недопустим.
  // ХРОМАТИКА: кайма в пикселях, та же формула, что была у pushFilters для
  // #nl-text-warp-aber — кайма от крутилки плюс доля искажения. Кнопка
  // «хроматика» (state.textAber) её включает; выключена — ровно ноль, и
  // шейдер тогда берёт все три канала из одной точки.
  fsАберПкс() {
    if (!this.state.textAber) return 0;
    var t = this.fsv ? this.fsv('taber') : 0;
    return (t / 100) * (20 + this.L('distort', 0) * 0.6 * 0.15);
  },

  fsВарп(t) {
    var холст = this._warpХолст, wrap = this._fsWrap;
    if (!холст || !wrap || this._варпЖив === false) return;
    var self = this;
    try {
      if (!this._варп) {
        this._варп = создатьВарп(холст, function (беда) {
          self._варпЖив = false;
          журнал('слой строки на видеокарте не поднялся: ' + беда + ' — работаю фильтром');
          self.setState({ live: Object.assign({}, self._live || {}) });
        });
        if (!this._варп) return;
        журнал('слой строки на видеокарте поднят');
      }
      if (!t) return;
      var cs = getComputedStyle(wrap);
      var dpr = Math.min(2, window.devicePixelRatio || 1);
      // ПОДПИСЬ ВМЕСТО СПИСКА КРУТИЛОК (Раунд 57). Я перечисляла поимённо, какие
      // ручки перерисовывают слой, и трижды подряд забывала: сперва искажение,
      // потом размытие, потом экспозицию и вес. требование: всё обновляется в реальном времени при вращении текста..
      //
      // Теперь слой сам сравнивает ВСЁ, из чего он собран — шрифт, кегль, вес,
      // цвет, выравнивание, размер обёртки, свечение, размытие, яркость,
      // искажение, — и перепекается, если что-то разошлось. Забыть ручку больше
      // нельзя: их никто не перечисляет.
      var подпись = [t, cs.font, cs.color, cs.textAlign, wrap.offsetWidth, wrap.offsetHeight,
        this.L('glow', 140), this.L('textBlur', 0), this.L('distort', 0),
        this.fsv ? this.fsv('expo') : 100, this.fsАберПкс(), dpr].join('|');
      if (подпись === this._варпПодпись) return;
      this._варпПодпись = подпись;
      var поле = 70;
      var ш = wrap.offsetWidth + поле * 2, в = wrap.offsetHeight + поле * 2;
      if (ш < 4 || в < 4) return;
      if (!this._варпХолст2) {
        this._варпХолст2 = document.createElement('canvas');
        this._варпХолст2ctx = this._варпХолст2.getContext('2d');
      }
      // цвет чернил берём У САМОЙ обёртки — там уже разрешена переменная
      // --ink-on-color, и второго источника правды заводить незачем
      var цв = (cs.color.match(/\d+\s*,\s*\d+\s*,\s*\d+/) || ['255,255,255'])[0];
      var выр = { left: 'left', right: 'right' }[cs.textAlign] || 'center';
      испечьТекст(this._варпХолст2, this._варпХолст2ctx, {
        текст: t, ширина: ш, высота: в,
        кегль: parseFloat(cs.fontSize) || 48,
        жир: cs.fontWeight || '700',
        семья: cs.fontFamily || 'sans-serif',
        цвет: цв,
        свечение: Math.max(0, this.L('glow', 140)),
        выравн: выр, dpr: dpr,
      });
      this._варп.рисовать(this._варпХолст2, this.L('distort', 0) / 12, dpr,
        (this.L('textBlur', 0) / 5) * dpr,
        (this.fsv ? this.fsv('expo') : 100) / 100,
        this.fsАберПкс() * dpr);
    } catch (e) {
      this._варпЖив = false;
      журнал('слой строки на видеокарте упал: ' + e + ' — работаю фильтром');
      try { this.setState({ live: Object.assign({}, this._live || {}) }); } catch (e2) {}
    }
  },

  paintLine(t) {
    var wrap = this._fsWrap;
    if (!wrap || !t || t === this._lineTxt) return false;
    // ЗАМЕР ПОКАЗА (Раунд 56). Пользователь нажал «строку назад» — генерации там
    // нет вовсе, а фриз тот же. Значит цена в ПОКАЗЕ, а не в генераторе, и
    // всё моё расследование генерации било мимо. Меряем три части раздельно:
    // запись текста в слои, плашки и подгонку размера — чтобы не гадать в
    // третий раз, какая из них.
    var т0 = performance.now();
    // метка для fsКадры(): следующий кадр — тот, в котором смена доехала до экрана
    this._сменаБыла = true;
    this._словПоследних = t.split(/\s+/).filter(Boolean).length;
    this._lineTxt = t;
    var layers = this.fsПисатьСлои(wrap, t);
    var т1 = performance.now();
    this.paintBand();
    var т2 = performance.now();
    this.fitLine();
    this.fsВарп(t);
    var т3 = performance.now();
    // Слои читают ширину текста, то есть браузер обязан посчитать раскладку и
    // фильтры ЗДЕСЬ ЖЕ. Отдельно замеряем и это: если цена там, значит виноваты
    // размытия и аберрация, а не сама запись.
    var т4 = т3;
    try { void wrap.offsetWidth; т4 = performance.now(); } catch (e) {}
    // Проверка живости фильтров идёт на КАЖДОЙ смене, а не только на тех, что
    // попадают в журнал: React ставит filter пропом и на любой перерисовке
    // вернёт мёртвую ссылку обратно, а с ней и пустой экран.
    var резкий = wrap.querySelector('[data-fssharp]');
    if (резкий) this._фильтрыОтвет = this.fsФильтрыЖивы(резкий);
    if (!this._paintN) this._paintN = 0;
    this._paintN++;
    if (this._paintN <= 6 || this._paintN % 25 === 0) {
      журнал('показ строки #' + this._paintN + ': слои ' + Math.round(т1 - т0)
        + ' мс · плашки ' + Math.round(т2 - т1) + ' мс · подгонка ' + Math.round(т3 - т2)
        + ' мс · раскладка ' + Math.round(т4 - т3) + ' мс · ИТОГО ' + Math.round(т4 - т0)
        + ' мс · слоёв ' + layers.length + ' · ' + this.fsВидно(wrap));
    }
    return true;
  },
  // плашки строим по фактическим строчным прямоугольникам текста — ровно как выделение мышью
  paintBand() {
    var wrap = this._fsWrap;
    var band = wrap && wrap.querySelector('[data-fsband]');
    var sharp = wrap && wrap.querySelector('[data-fssharp]');
    if (!band || !sharp) return;
    var bg = this.SELBG[this.state.selMode];
    if (!bg) { band.innerHTML = ''; return; }
    var rng = document.createRange();
    rng.selectNodeContents(sharp);
    var rects = rng.getClientRects(), wr = wrap.getBoundingClientRect();
    var kx = wrap.offsetWidth ? wr.width / wrap.offsetWidth : 1;
    var ky = wrap.offsetHeight ? wr.height / wrap.offsetHeight : 1;
    if (!kx) kx = 1;
    if (!ky) ky = 1;
    var pad = 3, html = '';
    for (var i = 0; i < rects.length; i++) {
      var r = rects[i];
      if (r.width < 2 || r.height < 2) continue;
      html += '<div style="position: absolute; left: ' + ((r.left - wr.left) / kx - pad) + 'px; top: ' + ((r.top - wr.top) / ky - pad) + 'px; width: ' + (r.width / kx + pad * 2) + 'px; height: ' + (r.height / ky + pad * 2) + 'px; background: ' + bg + ';"></div>';
    }
    band.innerHTML = html;
  },

  // ---- текст: источники строк ----
  vowelCount(s) { return (s.match(/[аеёиоуыэюя]/gi) || []).length; },
  // свой текст: строками или порциями слов
  srcChunksList() {
    var t = (this.state.srcText || '').replace(/\r/g, '');
    if (!t.trim()) return [];
    if ((this.state.srcChunk || 'строки') === 'строки') return t.split('\n').map(function (s) { return s.trim(); }).filter(Boolean);
    var w = t.split(/\s+/).filter(Boolean), n = Math.max(1, Math.round(this.fsv('srcWords'))), out = [];
    for (var i = 0; i < w.length; i += n) out.push(w.slice(i, i + n).join(' '));
    return out;
  },

  // ---- генератор: буфер-префетч ----
  // Одна генерация даёт целый shortlist, поэтому набираем пачкой и отдаём по
  // строке; дозаказ — когда в буфере осталось FS_LOW и меньше. Так «следующая»
  // и автосмена мгновенные, а бэк не дёргается на каждый кадр.
  async genFsLines(n) {
    // Раунд 51: тот же формат, что у редактора и прогона — {mode, params},
    // переводит бэк. Раньше фристайл слал ядерные имена своим переводом.
    // И тот же РЕЗОЛВЕР: каркас фристайл брал у звена (linkSpec), а крутилки
    // — прямо с панели, то есть сцена крутилась по референсной строфе с
    // нереференсным звучанием.
    var проф = this.fsНастройки();
    var payload = {
      source: 'freestyle',
      shortlist: Math.max(1, n || this.FS_BATCH),
      mode: проф.mode, params: проф.params,
    };
    // тема — СВОЯ, из поля «темы сцены» (Раунд 57). Здесь стоял `_lastKey` —
    // ключ последней генерации в редакторе, и объяснялось это как «фристайл
    // продолжает начатую мысль». На деле означало «ходит по чужой теме и
    // меняется, когда пользователь работает с текстом».
    var theme = this.fsТема();
    if (theme) payload.theme = theme;
    var spec = проф.spec;
    if (spec) payload.stanza = spec;
    var res = await api.generate(payload);
    // ответ придерживаем: из него берётся честная причина пустой выдачи
    this._fsLastRes = res;
    return ((res && res.shortlist) || [])
      .map(function (r) { return { text: (r && r.text) || '', template: (r && r.template) || '' }; })
      .filter(function (r) { return r.text; });
  },
  // дозаказ в фоне: одна заявка за раз, тяжёлую генерацию редактора не перебиваем
  fsFill() {
    if (this._fsFetching) return;
    if (this.state.tab !== 'fs') return;
    var self = this;
    // Тяжёлую генерацию редактора не перебиваем — но и заявку не бросаем:
    // брошенная означала бы пустую сцену до следующего действия пользователя
    // (автосмена по умолчанию выключена, а fsSeed срабатывает один раз за вход)
    if (this._busy) {
      clearTimeout(this._fsRetryT);
      this._fsRetryT = setTimeout(function () { self._fsRetryT = null; self.fsFill(); }, 600);
      return;
    }
    this._fsFetching = true;
    // Подпись заявки СНИМАЕТСЯ В МОМЕНТ ОТПРАВКИ (Раунд 51). Без этого ответ,
    // собранный по старым крутилкам, ложился в буфер уже ПОСЛЕ его сброса:
    // крутанул ползунок → буфер очистился → но заявка по старой подписи была
    // ещё в воздухе, и её строки приезжали в чистый буфер. Сцена ещё минуту
    // крутила выдачу по прежним настройкам, и крутилка выглядела сломанной.
    var подпись = this.fsGenKey();
    var t0 = (typeof performance !== 'undefined' ? performance.now() : Date.now());
    var сколько = (this._fsBuf && this._fsBuf.length) || this._fsFilled ? this.FS_BATCH : this.FS_BATCH_FIRST;
    this._fsFilled = true;
    this.genFsLines(сколько).then(function (rows) {
      self._fsFetching = false;
      // Числа снимаем С РАБОЧЕЙ МАШИНЫ: взять их иначе негде, а гадать про
      // его нагрузку я уже пробовала — вышло три круга (см. журнал движка).
      журнал('фристайл: пачка ' + (rows ? rows.length : 0) + ' строк за '
        + Math.round((typeof performance !== 'undefined' ? performance.now() : Date.now()) - t0)
        + ' мс · в запасе было ' + self.fsUnitsLeft());
      if (self.fsGenKey() !== подпись) {
        // настройки успели смениться — ответ чужой, выбрасываем и просим заново
        self.fsFill();
        return;
      }
      self._fsErrFlashed = false;
      if (!rows.length) {
        // Флаг «пусто» обязан протухать: без сброса сообщение приходило ОДИН
        // раз за сессию, а дальше сцена замирала молча — буфер не
        // пополнялся, строка не менялась, объяснения не было.
        if (!self._fsEmptyFlashed) {
          self._fsEmptyFlashed = true;
          self.flash(self.почемуПусто ? self.почемуПусто(self._fsLastRes) : 'генератор не вернул строк');
        }
        return;
      }
      self._fsEmptyFlashed = false;      // сбрасываем только на УДАЧНОМ ответе
      self._fsBuf = (self._fsBuf || []).concat(rows);
      // строка ждала буфера — показываем сразу, как только он наполнился
      if (!self._lineTxt) self.fsAdvance();
    }, function (e) {
      self._fsFetching = false;
      // поток фристайла не должен молча вставать: первый отказ показываем
      if (!self._fsErrFlashed) { self._fsErrFlashed = true; self.flash(e && e.message ? e.message : String(e)); }
    });
  },
  // ---- запас подачи (Раунд 37) ----------------------------------------------
  // Единица показа — то, что сменяется на экране за такт: строка при шаге
  // «строки», слово при шаге «слова». Запас и порог дозаказа считаем в них, а
  // не в строках буфера: в строках они означали разное при разных настройках.

  // Сколько единиц даёт одна строка. При шаге «слова» — по фактическому
  // буферу, а не по догадке: строки бывают и в два слова, и в двенадцать.
  fsUnitsPerRow() {
    if (this.fsStep() !== 'слова') return 1;
    var buf = this._fsBuf || [];
    if (!buf.length) return this.FS_WORDS_GUESS;
    var сумма = 0;
    for (var i = 0; i < buf.length; i++) {
      сумма += String(buf[i].text || '').split(/\s+/).filter(Boolean).length;
    }
    return Math.max(1, сумма / buf.length);
  },
  // Весь запас: уже разобранная очередь плюс ещё не разобранный буфер строк.
  fsUnitsLeft() {
    return (this._fsQ || []).length + (this._fsBuf || []).length * this.fsUnitsPerRow();
  },
  // Порог дозаказа: на FS_LEAD_SEC секунд показа, но не меньше двух экранов —
  // иначе при медленном интервале порог схлопнулся бы почти в ноль и сцена
  // ждала бы генерацию с пустыми руками.
  fsLowUnits() {
    var сек = Math.max(0.2, this.fsv('fsSec'));
    return Math.max(this.fsPer() * 2, Math.ceil(this.FS_LEAD_SEC / сек) * this.fsPer());
  },

  // n строк из буфера; пусто — заявка и честный пустой ответ (строка появится,
  // когда буфер наполнится: fsFill сам позовёт fsAdvance)
  fsTake(n) {
    var buf = this._fsBuf || (this._fsBuf = []);
    var out = buf.splice(0, Math.max(1, n));
    // Считаем ПОСЛЕ выемки, но вместе с вынутым: строки из `out` вот-вот станут
    // единицами очереди и тоже пойдут в запас — без них порог срабатывал бы
    // раньше времени и держал бы лишнюю заявку в воздухе.
    if (this.fsUnitsLeft() + out.length * this.fsUnitsPerRow() <= this.fsLowUnits()) this.fsFill();
    return out;
  },

  // «Классика» во фристайле — КЛИЕНТСКИЙ кат-ап: мешок слов режется и
  // пересобирается прямо в браузере. Это НЕ серверная «классика» (knob classic
  // в /api/generate — там другая механика, нарезка корпуса на бэке).
  // Мок-корпуса дизайна (STANZAS) нет, поэтому мешок собираем из того, что у
  // клиента честно есть: показанные строки фристайла, история, избранное и
  // текущий лист.
  cutupBag() {
    var st = this.state, src = [];
    (this._fsSeen || []).forEach(function (t) { src.push(t); });
    (st.hist || []).forEach(function (h) { src.push(h && h.t); });
    (st.favs || []).forEach(function (f) { src.push(typeof f === 'string' ? f : (f && f.t)); });
    (this.cur() || []).forEach(function (r) { if (r && r.type === 'line') src.push(r.text); });
    // дешёвый ключ кэша: мешок пересобирается, когда источников стало больше
    var key = src.length + ':' + (this._fsSeen || []).length;
    if (this._bagKey === key && this._bag) return this._bag;
    var bag = [];
    src.forEach(function (t) {
      String(t || '').split(/\s+/).forEach(function (w) { if (w) bag.push(w); });
    });
    this._bagKey = key; this._bag = bag;
    return bag;
  },

  // ---- подача: очередь ЕДИНИЦ (Раунд 36) ----------------------------------
  // требование (2026-08-02): при показе по одному слову они идут по порядку и не урезаются..
  //
  // До этого раунда фристайл резал КАЖДУЮ пришедшую строку до «слов на строку»
  // (trimWords) и хвост выбрасывал: сгенерированное молча портилось уже после
  // ответа бэка. Пословной подачи для генератора не было вовсе — «шаг:
  // строки/слова» работал только для «своего текста».
  //
  // Теперь одна модель на все источники: строка, откуда бы она ни пришла,
  // разбивается на ЕДИНИЦЫ выбранного шага и уходит в очередь. Показ берёт из
  // очереди по `fsPer` штук ПО ПОРЯДКУ и ничего не теряет: сколько бы слов ни
  // было в строфе, все они будут показаны.
  fsStep() { return this.state.srcChunk || 'строки'; },
  fsPer() { return Math.max(1, Math.round(this.fsv('fsPer'))); },

  // Разбить строку на единицы. Последняя помечается `last` — по ней (а не по
  // первой) строка считается ПОКАЗАННОЙ: пока слово третье из десяти, строка
  // на экране ещё не побывала (решение прожарки 7: «показан = был на экране»).
  fsUnits(row) {
    var текст = String(row.text || '');
    if (this.fsStep() !== 'слова') return [{ w: текст, row: row, last: true }];
    var слова = текст.split(/\s+/).filter(Boolean);
    if (!слова.length) return [];
    return слова.map(function (w, i) {
      return { w: w, row: row, last: i === слова.length - 1 };
    });
  },

  // Строки-источники для очереди. Ровно три ветки, как и было, но БЕЗ обрезки.
  fsPullRows() {
    var st = this.state;
    if ((st.srcMode || 'генератор') === 'свой текст') {
      var chunks = this.srcChunksList();
      if (chunks.length) {
        var p = this._srcPos || 0;
        this._srcPos = (p + 1) % chunks.length;
        return [{ text: chunks[p], template: '', shown: false }];
      }
    }
    var n = this.fsPer();
    if ((st.algo || 'Алгоритм') === 'Классика') {
      // клиентский кат-ап: мешок слов из уже показанного (НЕ бэкендовый отбор)
      var bag = this.cutupBag();
      if (bag.length) {
        var out = [], слов = this.FS_CUTUP_WORDS;
        for (var i = 0; i < n; i++) {
          var ws = [];
          for (var w = 0; w < слов; w++) ws.push(bag[Math.floor(Math.random() * bag.length)]);
          out.push({ text: ws.join(' '), template: '', shown: false });
        }
        return out;
      }
      // мешок пуст (пустая сессия) — берём живые строки: пустая сцена хуже
    }
    return this.fsTake(n).map(function (r) {
      return { text: r.text, template: r.template, shown: true };
    });
  },

  // Подпись заявки к генератору: всё, что влияет на СОДЕРЖИМОЕ строк. Ручки,
  // строфа, тема. Меняется — и буфер, и очередь становятся вчерашними: они
  // набраны по прежним настройкам (Раунд 37).
  //
  // Подпись обязана сниматься С ТОГО ЖЕ, что уезжает в запросе (починка
  // Раунда 51). Здесь стояли genKnobs() и stanzaSpec() — обе с ПАНЕЛИ, — а
  // genFsLines слал крутилки и каркас ЗВЕНА. Из-за этого правка звена или
  // референса подписи не меняла: буфер оставался прежним и сцена ещё десятки
  // строк крутила выдачу по старым настройкам, а сброшенный ползунок панели,
  // наоборот, выбрасывал буфер, набранный не по ней.
  fsGenKey() {
    var проф = this.fsНастройки();
    return JSON.stringify([this.knobsOfProfile(проф), проф.spec, this.fsТема()]);
  },

  // Дозаполнить очередь до нужного числа единиц. Тянет строки, пока не хватит
  // или пока источник не перестал давать (буфер пуст — заявка уже ушла из
  // fsTake, единицы появятся на следующем шаге).
  fsEnsureQueue(нужно) {
    // Очередь набита единицами ОДНОГО вида; сменился шаг или источник — старые
    // единицы становятся чужими (слова от строк, генератор от своего текста),
    // и держать их значило бы показывать вчерашнее ещё несколько тактов.
    var ключ = this.fsStep() + '|' + (this.state.srcMode || 'генератор') + '|' + (this.state.algo || 'Алгоритм');
    if (this._fsQKey !== ключ) { this._fsQKey = ключ; this._fsQ = []; }
    // Ручки крутанули — выбрасываем и буфер, и очередь. Раньше это сходило с
    // рук, потому что в буфере лежало 12 строк; с запасом на 25 секунд показа
    // (Раунд 37) их могут быть десятки, и сцена ещё минуту крутила бы строки,
    // сделанные по старым настройкам, — крутилка выглядела бы сломанной.
    // Только для источника «генератор»: у своего текста куски отдаются по
    // очереди через _srcPos, и сброс просто пропустил бы их без следа.
    var подпись = this.fsGenKey();
    if (this._fsGenKey !== подпись) {
      var было = this._fsGenKey;
      this._fsGenKey = подпись;
      if (было !== undefined && (this.state.srcMode || 'генератор') === 'генератор') {
        this._fsBuf = []; this._fsQ = [];
      }
    }
    var q = this._fsQ || (this._fsQ = []);
    var попыток = 0;
    while (q.length < нужно && попыток < 8) {
      попыток++;
      var rows = this.fsPullRows() || [];
      if (!rows.length) break;
      for (var i = 0; i < rows.length; i++) {
        var u = this.fsUnits(rows[i]);
        for (var j = 0; j < u.length; j++) q.push(u[j]);
      }
    }
    return q;
  },

  // Сцена смонтирована всегда, поэтому при ПЕРВОМ входе во фристайл строку надо
  // посеять явно: ref обёртки уже сработал когда-то в редакторе, второй раз он
  // не придёт. В дизайне это делает syncEngine; здесь — идемпотентный вызов,
  // который интегратор (или freestyle/engine.js) зовёт из componentDidUpdate.
  // setTab сбрасывает _fsSeeded, так что каждый вход сеет заново
  // ТЕКСТ ЕСТЬ СРАЗУ (Раунд 56). отчёт: текста не было и через минуту после запуска..
  //
  // И он прав: один поход в генератор стоит около двенадцати секунд ПОСТОЯННОЙ
  // платы (замерено на его машине), и всё это время сцена пуста. Ждать в
  // пустоту нельзя — а ждать и незачем: строки его собственного листа лежат
  // рядом, в документе, и годятся ровно для того, чтобы сцена жила, пока идёт
  // первый набор. Как только приедет настоящая пачка, она встанет следом — эти
  // строки её не заменяют и не мешают, они просто закрывают паузу.
  // СВОИ НАСТРОЙКИ, А НЕ РЕДАКТОРСКИЕ (Раунд 57). требование: настройки строфы во фристайле и в редакторе должны быть раздельными.. Так и было: `linkKnobs(0)` и `linkSpec(0)` последней
  // ступенью падают на панель редактора («мастерская»), и пока звено цепочки не
  // настроено руками — а его никто не настраивает, — сцена крутилась по
  // настройкам строфы.
  //
  // `null` означает «ещё не отделялся»: наследуем текущее редакторское ОДИН РАЗ
  // и дальше живём своей жизнью. Дальше их меняет только кнопка «взять из
  // редактора» в панели строки.
  fsНастройки() {
    var st = this.state;
    if (st.fsParams == null || st.fsKnobMode == null || st.fsSpec === null) {
      var своё = {
        fsKnobMode: st.fsKnobMode == null ? (st.knobMode || null) : st.fsKnobMode,
        fsParams: st.fsParams == null ? JSON.parse(JSON.stringify(st.params || {})) : st.fsParams,
        fsSpec: st.fsSpec === null ? (this.curSpec ? this.curSpec() : null) : st.fsSpec,
      };
      // правим состояние молча: это не выбор пользователя, а первое отделение
      this.setState(своё);
      return { mode: своё.fsKnobMode, params: своё.fsParams, spec: своё.fsSpec, source: 'фристайл' };
    }
    return { mode: st.fsKnobMode, params: st.fsParams, spec: st.fsSpec, source: 'фристайл' };
  },
  // Тема сцены — своё поле, а не ключ последней генерации в редакторе.
  fsТема() {
    return String(this.state.fsTheme || '')
      .split(',').map(function (s) { return s.replace(/\s+/g, ' ').trim(); })
      .filter(Boolean).join(', ');
  },
  // Явный перенос настроек строфы из редактора — по кнопке, а не молча.
  fsВзятьИзРедактора() {
    var st = this.state;
    this.setState({
      fsKnobMode: st.knobMode || null,
      fsParams: JSON.parse(JSON.stringify(st.params || {})),
      fsSpec: this.curSpec ? this.curSpec() : null,
    });
    this._fsBuf = []; this._fsQ = [];
    this.flash('настройки строфы перенесены в сцену');
  },

  fsSeed() {
    if (this._fsSeeded || this.state.tab !== 'fs') return;
    this._fsSeeded = true;
    this.fsКадры();
    this.fsAdvance();
  },

  // ЗАМЕР КАДРОВ В ЖИВОМ ПРИЛОЖЕНИИ (Раунд 57).
  //
  // Стенд не воспроизвёл фриз НИ РАЗУ — ни с шестью слоями, ни с настоящим
  // WebGL-канвасом 1960×1584 под ними. замечание: в отдельном стенде не подвисает ничего даже близко.. И он же по очереди выключил в
  // приложении искажение, размытие текста, свечение и цветовой слой — фриз
  // остался на каждом шаге. Значит дело не в том, ЧТО рисуется: ни фильтры
  // строки, ни смешивание слоёв, ни площадь размытия ни при чём. Все мои
  // гипотезы этого раунда закрыты его руками.
  //
  // Осталось то, чего в стенде нет вовсе: работа приложения ВОКРУГ смены —
  // перерисовка React-дерева, вынужденные пересчёты раскладки в fitLine и
  // paintBand, поход в историю. Меряем длительность кадра, В КОТОРОМ сменился
  // текст, против обычного кадра — прямо здесь, с его Butterchurn и его
  // настройками. Стоит это один rAF-цикл, который и так крутится рядом.
  //
  // В журнал пишем редко: сам поход в журнал — сетевой запрос, и на каждой
  // смене он бы сам создавал ту рябь, которую мы ищем.
  // Перебор раскладок, которым нашли причину, вырезан (Раунд 57): он своё
  // отработал, числа лежат в DECISIONS.md, а держать в горячем пути код,
  // который на каждой смене переписывает стили слоёв, незачем. Замер кадров
  // ниже оставлен — он стоит один rAF-цикл и в следующий раз ответит сразу.
  fsКадры() {
    if (this._кадрыИдут || typeof requestAnimationFrame !== 'function') return;
    this._кадрыИдут = true;
    var self = this, прошлый = 0, ждём = 0, n = 0;
    (function тик(t) {
      if (прошлый) {
        var d = t - прошлый;
        if (ждём) {
          ждём = 0; n++;
          журнал('кадр смены #' + n + ' [' + (self._переборИмя || '—') + ']: '
            + Math.round(d) + ' мс · обычный кадр ' + Math.round(self._фонКадр || 0)
            + ' мс · слов ' + (self._словПоследних || 0)
            + ' · визуализатор ' + (self.state.bcOn ? 'вкл' : 'выкл'));
        } else if (d < 200) {
          // Скользящее среднее по спокойным кадрам — с чем сравнивать. Всплески
          // от переключения вкладок и заявок в генератор в фон не пускаем.
          self._фонКадр = self._фонКадр ? self._фонКадр * 0.9 + d * 0.1 : d;
        }
      }
      прошлый = t;
      if (self._сменаБыла) { self._сменаБыла = false; ждём = 1; }
      requestAnimationFrame(тик);
    })(typeof performance !== 'undefined' ? performance.now() : Date.now());
  },

  // ЗАСЕВ ЛИСТОМ ВЫРЕЗАН (Раунд 57). Он стоял здесь один раунд и был ошибкой.
  //
  // Я поставила его, чтобы сцена не пустовала, пока идёт первый поход в
  // генератор: строки его собственного листа лежат рядом, в документе. Но
  // фристайл — это генератор, и только он; требование: текст во фристайле должен быть генеративным, а не подгружаться из
  // документа.. Показывать во фристайле его же черновик — это не заглушка паузы,
  // это подмена того, ради чего фристайл существует.
  //
  // И заглушка была не нужна: пауза бралась не от генерации (она отвечает за
  // 0.25 с), а от невидимого прогрева на старте — его и починили, в
  // api/server.py.

  // ЧЕСТНОЕ ОЖИДАНИЕ (Раунд 57). Пока прогрев сервера не закончен, генератор
  // физически не может ответить, и сцена стоит пустой. Раньше в этот момент не
  // было НИЧЕГО — ни строки, ни объяснения; пользователь две минуты смотрел в
  // чёрное и не мог отличить «думает» от «сломалось». Строку берём готовой из
  // /api/status (шапка опрашивает его и так, своего запроса не заводим) и
  // показываем прямо на сцене — она гаснет сама, как только приходит текст.
  fsЖдём() {
    if (this._lineTxt) return '';
    var работы = this.state.jobs || [];
    for (var i = 0; i < работы.length; i++) {
      var j = работы[i];
      if (j && j.id === 'nl_store' && j.state === 'running') {
        return (j.label || 'готовим генератор') + '\n' + (j.detail || '');
      }
    }
    return this._fsFetching ? 'генератор думает' : '';
  },

  fsAdvance() {
    if (this.state.tab !== 'fs') return;
    var сколько = this.fsPer();
    var q = this.fsEnsureQueue(сколько);
    if (!q.length) return;               // буфер пуст — заявка ушла, ждём
    var units = q.splice(0, сколько);
    // шаг «слова» — единицы одного экрана идут через пробел (это части ОДНОЙ
    // строки), шаг «строки» — через перевод строки
    var разделитель = this.fsStep() === 'слова' ? ' ' : '\n';
    var text = units.map(function (u) { return u.w; }).filter(Boolean).join(разделитель);
    if (!this.paintLine(text)) return;
    // решение прожарки 7: показано = было на экране. Строка засчитывается,
    // когда с экрана ушла её ПОСЛЕДНЯЯ единица, а не первая
    var fresh = [];
    units.forEach(function (u) {
      if (u.last && u.row && u.row.shown && u.row.text) fresh.push(u.row);
    });
    if (fresh.length) {
      this._fsSeen = (this._fsSeen || []).concat(fresh.map(function (r) { return r.text; })).slice(-400);
      if (this.markShownQueue) this.markShownQueue(fresh.map(function (r) { return { text: r.text, template: r.template || '' }; }));
    }
  },

  // ---- циклы: автосмена строки, автопресет, автоцвет ----
  // авто-смена: период с той же ручки скорости
  fsAutoLoop() {
    var st = this.state;
    if (!(st.autoOn && st.tab === 'fs')) { if (this._autoT) { clearInterval(this._autoT); this._autoT = null; this._autoMs = 0; } return; }
    // Раунд 36: интервал в СЕКУНДАХ, а не безымянная шкала 1..100. Раньше
    // было `4200 − ползунок×38` мс, и ползунок носил id colorSpeedSlider —
    // наследие скорости цвета, хотя управлял сменой строки.
    var ms = Math.max(200, Math.round(this.fsv('fsSec') * 1000));
    if (this._autoT && this._autoMs === ms) return;
    if (this._autoT) clearInterval(this._autoT);
    this._autoMs = ms;
    var self = this;
    this._autoT = setInterval(function () { self.fsAdvance(); }, ms);
  },
  // автосмена пресетов: своим таймером, потому что у движка её нет. Всегда выключена по умолчанию —
  // включается только вручную и сохраняется в профиль вместе с периодом
  bcAutoLoop() {
    var st = this.state, self = this;
    if (!(st.bcAutoOn && st.tab === 'fs')) { if (this._bcAutoT) { clearInterval(this._bcAutoT); this._bcAutoT = null; this._bcAutoMs = 0; } return; }
    var ms = Math.max(5, st.bcAutoSec || 30) * 1000;
    if (this._bcAutoT && this._bcAutoMs === ms) return;
    if (this._bcAutoT) clearInterval(this._bcAutoT);
    this._bcAutoMs = ms;
    this._bcAutoT = setInterval(function () {
      if (self.state.tab !== 'fs') return;
      // случайный пресет умеет движок (freestyle/engine.js); нет его — кнопка дизайна
      if (self.randomPreset) self.randomPreset();
      else { var b = document.getElementById('btnRandomPreset'); if (b) b.click(); }
    }, ms);
  },
  // темп перехода: квадратичная шкала, чтобы медленный конец был минутами, а не секундами
  acPeriod() { var s = Math.max(1, Math.min(100, this.fsv('acSpeed'))); return Math.round(180 + Math.pow(101 - s, 2) * 3); },
  // авто-переход цвета: по времени либо по громкости — яркость кадра визуализатора как её мера
  autoColorLoop() {
    var mode = this.state.acMode || 'выкл';
    if (mode === 'выкл' || this.state.tab !== 'fs') { if (this._acT) { clearInterval(this._acT); this._acT = null; this._acMs = 0; } return; }
    var ms = mode === 'звук' ? 90 : this.acPeriod();
    if (this._acT && this._acMs === ms && this._acMode === mode) return;
    if (this._acT) clearInterval(this._acT);
    this._acMs = ms; this._acMode = mode;
    var self = this;
    this._acT = setInterval(function () { mode === 'звук' ? self.acBeat() : self.acStep(); }, ms);
  },
  acStep() {
    // палитра живёт в модуле панелей (loadPal/applyPal) — без него шаг просто не делаем
    if (!this.loadPal || !this.applyPal) return;
    var pal = this.state.pal || this.loadPal();
    if (!pal || !pal.panel || !pal.panel.length) return;
    this._acI = ((this._acI == null ? ((this.state.palSel || {}).panel || 0) : this._acI) + 1) % pal.panel.length;
    this.applyPal('panel', pal.panel[this._acI], true);
  },
  // ГРОМКОСТЬ — ИЗ ЗВУКА, А НЕ ИЗ ПИКСЕЛЕЙ (Раунд 56).
  //
  // Здесь стоял замер яркости кадра: `drawImage(bcCanvas → 8×8)` плюс
  // `getImageData`. Читалось это как «громкость снимаем с кадра визуализатора,
  // он и так реагирует на звук» — и было самой дорогой вещью во всей сцене.
  //
  // Замерено на канвасе пользователя (1372×1109): **7.15 мс на вызов** при
  // бюджете кадра 16.7 мс. Сам `drawImage` из WebGL стоит 0.01 мс — платит
  // `getImageData`: она заставляет процессор дождаться видеокарты, и этот
  // барьер рвёт конвейер не только себе, но и отрисовке Butterchurn. Для
  // сравнения: блюм 1.04 мс, зерно 0.64 мс.
  //
  // Настоящий источник громкости лежал рядом всё это время: терминальный
  // анализатор на шине водителя картинки (`audio.getLevels()`), куда сходятся
  // микрофон, трек и синтетика. Он даёт ту же величину без единого обращения к
  // видеокарте.
  acBeat() {
    var a = this.fsAudio();
    var ан = a && a.getLevels ? a.getLevels() : null;
    if (!ан) return;
    var n = ан.frequencyBinCount;
    if (!this._acBuf || this._acBuf.length !== n) this._acBuf = new Uint8Array(n);
    ан.getByteTimeDomainData(this._acBuf);
    // Среднеквадратичное отклонение от тишины (128) — это и есть громкость
    var сум = 0;
    for (var i = 0; i < n; i++) { var d = (this._acBuf[i] - 128) / 128; сум += d * d; }
    var lum = Math.sqrt(сум / n);
    this._avg = this._avg == null ? lum : this._avg * 0.9 + lum * 0.1;
    var thr = 1 + (100 - this.fsv('acSpeed')) / 220;
    if (lum > this._avg * thr && Date.now() - (this._acLast || 0) > 220) { this._acLast = Date.now(); this.acStep(); }
  },

  // ---- геометрия: строка и кадр ----
  // кегль задаётся напрямую, поэтому вписываем строку в сцену и по высоте, и по ширине
  fitLine() {
    var wrap = this._fsWrap, box = this._fsStage;
    if (!wrap || !box) return;
    // тянем от того угла, к которому прижата строка, иначе тильт уводит её из своего положения
    var ox = { 'слева': 'left', 'по центру': 'center', 'справа': 'right' }[this.state.posX || 'по центру'];
    var oy = { 'сверху': 'top', 'по центру': 'center', 'снизу': 'bottom' }[this.state.posY || 'по центру'];
    wrap.style.transformOrigin = ox + ' ' + oy;
    var user = Math.max(0.5, Math.min(1.5, this.L('scale', 100) / 100));
    if (!this.state.fitFrame) {
      // кегль — реальный размер: строка ломается только по своим переносам, лишнее уходит за кадр
      wrap.style.width = 'max-content';
      wrap.style.maxWidth = 'none';
      wrap.style.flex = '0 0 auto';
      wrap.style.transform = 'scale(' + (user * this.fsv('ttiltH') / 100) + ', ' + (user * this.fsv('ttiltV') / 100) + ')';
      this.paintBand();
      return;
    }
    // «вписывать текст»: переносим по ширине кадра, кегль в настройках не переписываем
    var cs = getComputedStyle(box);
    var availW = box.clientWidth - parseFloat(cs.paddingLeft || 0) - parseFloat(cs.paddingRight || 0);
    var availH = box.clientHeight - parseFloat(cs.paddingTop || 0) - parseFloat(cs.paddingBottom || 0);
    if (availW <= 0 || availH <= 0) return;
    var glow = Math.max(0, this.L('glow', 140)) / 140;
    var pad = Math.round(34 * glow + this.L('textBlur', 0) / 6);
    var boxW = Math.max(40, availW - pad * 2), boxH = Math.max(40, availH - pad * 2);
    wrap.style.width = 'auto';
    wrap.style.maxWidth = Math.round(boxW / user) + 'px';
    wrap.style.flex = '0 1 auto';
    wrap.style.transform = 'scale(' + user + ')';
    var h = wrap.scrollHeight * user;
    // по высоте досжимаем только если рядов стало больше, чем влезает
    var fit = h > boxH ? boxH / h : 1;
    var k = user * Math.max(0.08, fit);
    wrap.style.transform = 'scale(' + (k * this.fsv('ttiltH') / 100) + ', ' + (k * this.fsv('ttiltV') / 100) + ')';
    this.paintBand();
  },
  parseAspect(s) {
    if (!s) return null;
    var m = String(s).match(/^(\d+(?:\.\d+)?)\s*[:/xх×]\s*(\d+(?:\.\d+)?)$/);
    var v = m ? parseFloat(m[1]) / parseFloat(m[2]) : parseFloat(s);
    return v && isFinite(v) && v >= 0.2 && v <= 6 ? v : null;
  },
  // формат кадра: сцену сжимаем до нужного соотношения, движок пишет ровно её
  fitStage() {
    var stage = this.fsStage();
    if (!stage) return;
    var host = stage.parentElement, a = this.ASPECTS[this.state.aspect] || this.parseAspect(this.state.aspect);
    var W = host.clientWidth, H = host.clientHeight;
    if (!a || !W || !H) {
      stage.style.left = stage.style.top = '0px';
      stage.style.width = stage.style.height = '';
      stage.style.right = stage.style.bottom = '0px';
      host.style.background = '';
    } else {
      var w = Math.min(W, H * a), h = w / a;
      stage.style.right = stage.style.bottom = 'auto';
      stage.style.left = Math.round((W - w) / 2) + 'px';
      stage.style.top = Math.round((H - h) / 2) + 'px';
      stage.style.width = Math.round(w) + 'px';
      stage.style.height = Math.round(h) + 'px';
      host.style.background = '#000';
    }
    var key = this.state.aspect + ':' + W + 'x' + H;
    if (this._fitKey !== key) {
      this._fitKey = key;
      window.dispatchEvent(new Event('resize'));
      this.sizeBuffers();
      var self = this;
      setTimeout(function () { self.sizeBuffers(); }, 120);
    }
    this.fitLine();
  },
  // движок вешает свой resize и мерит канвас по окну — переписываем буферы после него
  watchStage() {
    if (this._stageWatch) return;
    var self = this, again = function () { requestAnimationFrame(function () { self.sizeBuffers(); }); };
    this._stageWatch = function () { self.sizeBuffers(); again(); setTimeout(again, 60); };
    window.addEventListener('resize', this._stageWatch);
    var stage = this.fsStage();
    if (stage && window.ResizeObserver) {
      this._stageRO = new ResizeObserver(again);
      this._stageRO.observe(stage);
    }
  },
  sizeBuffers() {
    var stage = this.fsStage();
    if (!stage) return;
    var w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    var rs = Math.max(0.25, Math.min(1.5, this.slider('bcRenderScaleSlider', 70) / 100));
    var dpr = Math.min(2, window.devicePixelRatio || 1);
    // bcCanvas здесь НЕТ сознательно: его размером владеет движок
    // (freestyle/engine.js сам считает CSS × dpr × «рендер» и держит буфер).
    // Две записи в один канвас дали бы драку размеров — ту самую, ради которой
    // в дизайне жил kickResize с MutationObserver
    [['bloomCanvas', Math.min(1, rs) * dpr], ['grainCanvas', 0.5 * dpr]].forEach(function (p) {
      var c = document.getElementById(p[0]);
      if (!c) return;
      var bw = Math.max(2, Math.round(w * p[1])), bh = Math.max(2, Math.round(h * p[1]));
      if (c.width !== bw) c.width = bw;
      if (c.height !== bh) c.height = bh;
    });
  },

  // ---- зерно сцены ----
  // процедурный шум: свой кадр каждый тик, без повторяющейся плитки
  grainLoop() {
    if (this._grainRAF) return;
    var self = this;
    var tick = function (ts) {
      self._grainRAF = requestAnimationFrame(tick);
      var c = self._grain;
      if (!c || self.state.tab !== 'fs') return;
      var op = Math.max(0, Math.min(100, self.slider('grainSlider', 18))) / 100;
      if (op <= 0) return;
      var fps = self.state.grainFps == null ? 24 : self.state.grainFps;
      if (fps > 0) {
        var step = 1000 / fps;
        if (self._grainT && ts - self._grainT < step) return;
        self._grainT = ts;
      }
      self.drawGrain(c);
    };
    this._grainRAF = requestAnimationFrame(tick);
  },
  drawGrain(c) {
    var stage = this.fsStage();
    if (!stage) return;
    var sz = Math.max(1, this.fsv('gsize'));
    // буфер меньше кадра ровно во «размер зерна» раз — растяжение и даёт крупное зерно
    var w = Math.max(8, Math.round(stage.clientWidth / (sz * 2)));
    var h = Math.max(8, Math.round(stage.clientHeight / (sz * 2)));
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; this._grainImg = null; }
    var ctx = c.getContext('2d', { alpha: true });
    if (!ctx) return;
    if (!this._grainImg || this._grainImg.width !== w || this._grainImg.height !== h) {
      this._grainImg = ctx.createImageData(w, h);
      this._grainBuf = new Uint32Array(this._grainImg.data.buffer);
    }
    this.fillNoise(this._grainBuf, Math.max(4, Math.min(120, Math.round(this.fsv('ghard') * 0.42))), (this.state.grainMode || 'плёнка') === 'цифра');
    ctx.putImageData(this._grainImg, 0, 0);
  },

  // ---- камера ----
  async camStart() {
    try {
      var want = this.state.camId;
      var st = await navigator.mediaDevices.getUserMedia({ video: want ? { deviceId: { exact: want } } : true, audio: false });
      this.camStop(true);
      this._camStream = st;
      if (this._cam) { this._cam.srcObject = st; this._cam.play().catch(function () {}); }
      var devs = await navigator.mediaDevices.enumerateDevices();
      var cams = devs.filter(function (d) { return d.kind === 'videoinput'; })
        .map(function (d, i) { return { id: d.deviceId, name: d.label || ('камера ' + (i + 1)) }; });
      var track = st.getVideoTracks()[0];
      this.setState({ camOn: true, camList: cams, camId: want || (track && track.getSettings ? track.getSettings().deviceId : '') || (cams[0] && cams[0].id) || '' });
    } catch (e) { this.setState({ camOn: false, camErr: 1 }); }
  },
  camStop(keepFlag) {
    if (this._camStream) { this._camStream.getTracks().forEach(function (t) { t.stop(); }); this._camStream = null; }
    if (this._cam) this._cam.srcObject = null;
    if (!keepFlag) this.setState({ camOn: false });
  },

  // ---- слои сцены и SVG-фильтры ----
  // слои сцены движок не знает — красим их сами по своим ручкам.
  // ВНИМАНИЕ: это метод прототипа, а не стрелка дизайна — передавать его как
  // колбэк (setState(..., c.pushScene)) нельзя, только () => c.pushScene()
  pushScene() {
    var cl = document.querySelector('.colorLayer'), bc = document.getElementById('bcCanvas');
    if (cl) cl.style.filter = 'saturate(' + this.fsv('sat') + '%) contrast(' + this.fsv('con') + '%) brightness(' + this.fsv('expoBg') / 100 + ')';
    var bcExpo = this.fsv('expoBc') === 100 ? '' : 'brightness(' + this.fsv('expoBc') / 100 + ')';
    ['bcCanvas', 'bloomCanvas'].forEach(function (id) { var el = document.getElementById(id); if (el) el.style.filter = bcExpo; });
    var flat = this.fsv('tiltH') === 100 && this.fsv('tiltV') === 100;
    if (this._fsInner) {
      this._fsInner.style.transform = flat ? '' : 'scale(' + this.fsv('tiltH') / 100 + ', ' + this.fsv('tiltV') / 100 + ')';
      this._fsInner.style.transformOrigin = 'center';
      this._fsInner.style.filter = this.fsv('expoPost') === 100 ? '' : 'brightness(' + this.fsv('expoPost') / 100 + ')';
    }
    ['#bcCanvas', '#bloomCanvas', '.colorLayer', '.stage'].forEach(function (sel) {
      var el = document.querySelector(sel);
      if (el && el.style.transform) el.style.transform = '';
    });
    var grad = this.fsv('grad');
    if (bc) bc.style.maskImage = bc.style.webkitMaskImage = grad > 0
      ? 'radial-gradient(120% 120% at 50% 50%, #000 ' + (100 - grad) + '%, transparent 100%)' : '';
    if (this._grain) this._grainImg = null;
    this.pushFilters();
    this.paintBand();
  },
  // искажения строки и кадра держим на своих SVG-фильтрах, значения — из окон.
  // Фильтры объявлены в Nakedlunch.jsx (#nl-text-warp / #nl-postfx): ref может
  // ещё не прийти, поэтому есть фолбэк на querySelector
  pushFilters() {
    var tw = this.L('distort', 0) / 12;
    var twEl = this._twEl || document.querySelector('#nl-text-warp feDisplacementMap');
    if (twEl) twEl.setAttribute('scale', String(tw));
    // канальный разброс фиксированный, поэтому хроматика видна и без искажения
    var base = this.L('distort', 0) * 0.6, fringe = (this.fsv('taber') / 100) * (20 + base * 0.15);
    var ta = document.querySelectorAll('#nl-text-warp-aber feDisplacementMap');
    var offs = [base + fringe, base, base - fringe];
    for (var i = 0; i < ta.length; i++) ta[i].setAttribute('scale', String(offs[i]));
    var pfx = this.L('postfxBend', 0) / 8;
    var pfEl = this._pfEl || document.querySelector('#nl-postfx feDisplacementMap');
    if (pfEl) pfEl.setAttribute('scale', String(pfx));
    var pa = document.querySelectorAll('#nl-postfx-aber feDisplacementMap');
    for (var j = 0; j < pa.length; j++) pa[j].setAttribute('scale', String(pfx * [0.65, 1, 1.45][j]));
  },

  // ---- гарнитуры ----
  // Список гарнитур: базовые + дополнительные дизайна, но ТОЛЬКО те, что реально
  // установлены (Google-шрифты не грузим — офлайн-инвариант), плюс загруженные
  // пользователем файлы. Если движок дал свой #fontSelect — его опции тоже входят.
  harvestFonts() {
    var have = {}, list = [];
    var push = function (v, n) { if (!v || have[v]) return; have[v] = 1; list.push({ v: v, n: n || v }); };
    var installed = function (fam) {
      if (!document.fonts || !document.fonts.check) return true; // нечем проверить — показываем
      try { return document.fonts.check('16px "' + fam + '"'); } catch (e) { return true; }
    };
    this.FONTS_BASE.forEach(function (f) { push(f); });
    (this._fontFiles || []).forEach(function (f) { push(f); });
    this.FONTS_EXTRA.forEach(function (f) { if (installed(f)) push(f); });
    var sel = document.getElementById('fontSelect');
    if (sel) Array.prototype.forEach.call(sel.options, function (o) { push(o.value, (o.textContent || o.value).trim()); });
    var same = (this.state.fonts || []).length === list.length
      && (this.state.fonts || []).every(function (f, i) { return f.v === list[i].v; });
    if (!same) this.setState({ fonts: list });
  },
  pickFont(fam) {
    // движок знает не все семейства — переменную строки выставляем сами
    var stage = this.fsStage();
    if (stage) stage.style.setProperty('--line-font', fam);
    var sel = document.getElementById('fontSelect');
    if (sel) {
      sel.value = fam;
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      sel.dispatchEvent(new Event('input', { bubbles: true }));
    }
    var self = this;
    this.setState({ fontNow: fam }, function () { self.fitLine(); self.bandLater(); });
  },
  // свой шрифт файлом: FontFace вместо сети — единственный офлайн-честный способ
  loadFontFile(file) {
    if (!file || !window.FontFace) return;
    var self = this, fam = String(file.name || 'свой шрифт').replace(/\.[^.]+$/, '');
    var rd = new FileReader();
    rd.onload = function () {
      try {
        var ff = new FontFace(fam, rd.result);
        ff.load().then(function (loaded) {
          document.fonts.add(loaded);
          self._fontFiles = (self._fontFiles || []).concat([fam]);
          self.harvestFonts();
          self.pickFont(fam);
        }, function () { self.flash('шрифт не читается: ' + fam); });
      } catch (e) { self.flash('шрифт не читается: ' + fam); }
    };
    rd.readAsArrayBuffer(file);
  },

  // ---- прочее ----
  // guardMicIcon дизайна (2386..2403) НЕ перенесён: он сторожил #btnMic от
  // внешнего скрипта движка, который писал в кнопку текст об отказе в доступе
  // вместо иконки. Скрипта больше нет, микрофоном заведует freestyle/audio.js,
  // а отказ показывается флешем — сторожить нечего.

  // запись живёт в methods.fsrec.js (фаза 4): recToggle/recStart/recStop.
  // Заглушки fsToggleRec больше нет — кнопка btnRecord зовёт recToggle().

  // таймеры и потоки сцены гасим явно: componentWillUnmount интегратора их не знает
  fsUnmount() {
    if (this._grainRAF) cancelAnimationFrame(this._grainRAF);
    this._grainRAF = 0;
    clearInterval(this._autoT); this._autoT = null;
    clearInterval(this._bcAutoT); this._bcAutoT = null;
    clearInterval(this._acT); this._acT = null;
    clearTimeout(this._fsRetryT); this._fsRetryT = null;
    if (this._lineObs) { this._lineObs.disconnect(); this._lineObs = null; }
    if (this._stageRO) { this._stageRO.disconnect(); this._stageRO = null; }
    if (this._stageWatch) { window.removeEventListener('resize', this._stageWatch); this._stageWatch = null; }
    this.camStop(true);
  },
};
