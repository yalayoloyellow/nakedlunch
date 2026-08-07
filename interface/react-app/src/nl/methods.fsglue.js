// Связка фазы 3: сцена (render.fs/methods.fs) ↔ движок Butterchurn
// (freestyle/engine.js) ↔ аудио-граф (freestyle/audio.js).
//
// ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ. Дизайн («Editor First.dc.html», 2180..2187, 2404..
// 2427, 3044..3076, 3097..3116) разговаривал с движком через DOM: внешний
// скрипт freestyle-engine.js сам находил #btnMic/#trackFile/#presetPanel,
// сам держал AudioContext и сам рисовал список пресетов, а класс лишь
// «толкал» его инпуты и ждал появления строк опросом (whenEngine, kickResize).
// Внешнего скрипта больше нет — движок и звук собраны в бандл и отвечают
// объектами. Поэтому здесь живёт всё, что дизайн раздавал по DOM:
//   enterFs/loadEngine   — ленивая загрузка чанка движка (пресеты — 2.8 МБ,
//                          в стартовый экран редактора им нельзя);
//   syncEngine           — порт 2404..2427 без kickResize/guardMicIcon: гонки
//                          с внешним скриптом, ради которых они жили, больше
//                          нет; вместо этого честный engine.start()/stop();
//   onCardInput          — порт 3044..3076 дословно, кроме точки
//                          __bcSetRenderScale: зовём метод движка напрямую;
//   микрофон и трек      — реальные вызовы audio.js вместо фиктивных
//                          fsTog('micOn')/fsTog('trackOn') макета;
//   bloomLoop            — слой ореола: в прототипе его рисовал внешний движок
//                          (ut(): bcCanvas → bloomCanvas с блюром), наш движок
//                          в чужие канвасы не лезет, поэтому рисуем сами.
//
// Запись (recOn/MediaRecorder) — ФАЗА 4, здесь её нет.

import { createAudio } from './freestyle/audio.js';

// Режимы наложения цветовой плашки: список прототипа (freestyle-engine.js, T)
// с его же значением по умолчанию «Цвет». В дизайне #blendSelect наполнял сам
// движок — наш в DOM не ходит, поэтому список переехал сюда.
export const BLENDS = [
  ['normal', 'Обычный'], ['multiply', 'Умножение'], ['screen', 'Экран'], ['overlay', 'Перекрытие'],
  ['darken', 'Затемнение'], ['lighten', 'Осветление'], ['color-burn', 'Затемн. основы'],
  ['color-dodge', 'Осветл. основы'], ['hard-light', 'Жёсткий свет'], ['soft-light', 'Мягкий свет'],
  ['difference', 'Разница'], ['exclusion', 'Исключение'], ['hue', 'Оттенок'],
  ['saturation', 'Насыщенность'], ['color', 'Цвет'], ['luminosity', 'Яркость'],
];
export const BLEND_DEF = 'color';

// ореол перерисовываем ~30 раз в секунду, как в прототипе (setInterval 33 мс):
// это полноэкранный блюр, на каждом кадре он стоит дороже пользы
const BLOOM_MS = 33;
// суффиксы паков движка: профиль, снятый прототипом, мог сохранить голое имя,
// которое в нашем каталоге ушло к другому паку (см. риски engine.js)
const PACK_SUFFIX = [' (md1)', ' (extra)', ' (extra2)', ' (base)'];

// ЖУРНАЛ ИНТЕРФЕЙСА (Раунд 56). Окно владельца — WKWebView внутри pywebview,
// консоли у него нет, и я его не вижу. Три захода подряд на «движок не
// работает» упёрлись ровно в это: я чинила по догадке, потому что настоящего
// сообщения из ЕГО окна не было ни разу. Пусть окно говорит само — в
// data/интерфейс.log, как сборки говорят в data/сборки.log.
export function журнал(текст) {
  try {
    fetch('/api/ui/log', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                           body: JSON.stringify({ text: String(текст).slice(0, 2000) }) }).catch(function () {});
  } catch (e) { /* журнал не обязан работать, чтобы работало остальное */ }
}

export const fsGlueMethods = {
  BLENDS,
  BLEND_DEF,

  // ---- аудио ----------------------------------------------------------
  // Граф собирается при первом входе во фристайл, а не при старте приложения:
  // редактору AudioContext не нужен, а браузер за «немотивированный» контекст
  // ругается в консоль.
  fsAudioStart() {
    if (!this._audio) {
      this._audio = createAudio();
      // resume() разрешён только из обработчика реального ввода — вешаем
      // одноразовые слушатели, снималка уедет в размонтирование
      this._audioOff = this._audio.resumeOnGesture();
    }
    try { this._audio.start(); } catch (e) { this.flash(e && e.message ? e.message : String(e)); }
    return this._audio;
  },
  fsAudio() { return this._audio || null; },

  async fsToggleMic() {
    var a = this.fsAudioStart();
    try {
      var on = await a.toggleMic();
      // synthetic — не «включена ли кнопка», а ВОДИТ ЛИ синтетика картинку
      // прямо сейчас: микрофон её вытесняет, и панель должна это показывать
      // сама, без второго источника правды (см. freestyle/audio.js: synthOn).
      this.setState({ micOn: on, synthOn: a.state().synthetic });
    } catch (e) {
      this.setState({ micOn: false });
      this.flash(e && e.message ? e.message : String(e));
    }
  },
  // Синтетический шум вручную (Раунд 56, просьба владельца). Кнопка нужна
  // потому, что вытеснение автоматическое: выключив микрофон и трек, шум
  // вернётся сам — а иногда его не хочется вовсе.
  fsToggleSynth() {
    var a = this.fsAudioStart();
    a.setSynth(!this.state.synthWanted);
    var st = a.state();
    this.setState({ synthWanted: st.synthWanted, synthOn: st.synthetic });
  },
  // трек: снять — сразу, поставить — через скрытый #trackFile (разметка сцены)
  fsToggleTrack() {
    if (this.state.trackOn) {
      var a = this.fsAudio();
      if (a) a.stopTrack();
      var lab = document.getElementById('trackLabel');
      if (lab) lab.textContent = '';
      this.setState({ trackOn: false });
      return;
    }
    var inp = document.getElementById('trackFile');
    if (inp) inp.click();
  },
  async onTrackFile(e) {
    var file = e && e.target && e.target.files && e.target.files[0];
    // сбрасываем значение: без этого повторный выбор того же файла не даёт change
    if (e && e.target) e.target.value = '';
    if (!file) return;
    var a = this.fsAudioStart();
    try {
      var res = await a.loadTrack(file);
      var lab = document.getElementById('trackLabel');
      if (lab) lab.textContent = '♪ ' + res.name;
      this.setState({ trackOn: true });
      this.flash('трек: ' + res.name);
    } catch (err) {
      this.setState({ trackOn: false });
      this.flash(err && err.message ? err.message : String(err));
    }
  },

  // ---- движок ---------------------------------------------------------
  // Вход во фристайл: звук, движок, профиль сцены. Порядок дизайна (2180),
  // но loadEngine теперь асинхронный — профиль доберёт себя сам (topUpProfile
  // ждёт готовности движка через whenEngine).
  // ХРОНИКА ФРИСТАЙЛА (Раунд 56). Владелец: «ты ж нихуя не видишь, сделай так,
  // чтоб нормально видеть, когда что реально загружается, а не долби вслепую».
  //
  // Он прав: я третий раз чиню по догадке, потому что вижу его окно только
  // через то, что сама туда положила. Кладём хронику: раз в две секунды одна
  // строка — сколько строк в листе, сколько в буфере и очереди, идёт ли поход
  // за текстом, есть ли что на экране. Двадцать записей и хватит: этого
  // достаточно, чтобы увидеть, ЧТО приезжает раньше чего.
  fsХроника() {
    if (this._хроникаT) return;
    var self = this, n = 0;
    this._хроникаT = setInterval(function () {
      if (self.state.tab !== 'fs' || ++n > 20) { clearInterval(self._хроникаT); self._хроникаT = 0; return; }
      var док = (self.cur ? self.cur() : []) || [];
      var строк = 0;
      for (var i = 0; i < док.length; i++) if (док[i] && док[i].type === 'line' && String(док[i].text || '').trim()) строк++;
      журнал('хроника ' + n + ': лист ' + док.length + ' строк (с текстом ' + строк + ')'
        + ' · буфер ' + ((self._fsBuf || []).length) + ' · очередь ' + ((self._fsQ || []).length)
        + ' · поход ' + (self._fsFetching ? 'идёт' : 'нет')
        + ' · на экране ' + (self._lineTxt ? '«' + String(self._lineTxt).slice(0, 24) + '»' : 'ПУСТО')
        + ' · лист открыт: ' + (self.state.sheetId ? 'да' : 'нет'));
    }, 2000);
  },

  enterFs() {
    this.fsХроника();
    this.fsAudioStart();
    this.loadEngine();
    this.bloomLoop();
    if (this.bootProfile) this.bootProfile();
    if (this.topUpProfile) this.topUpProfile();
  },

  // ПЕРЕЗАПУСК ДВИЖКА БЕЗ ПЕРЕЗАПУСКА ПРИЛОЖЕНИЯ (Раунд 56).
  //
  // Владелец: «было бы круто добавить кнопку перезапустить butterchurn… когда
  // он сбивается, было бы славно его перезапускать, не перезапуская само
  // приложение».
  //
  // Что именно «сбивается». Движок держит контекст WebGL2, а браузер вправе
  // отобрать его в любой момент (переключение видеокарты, сон, нехватка
  // памяти) — после этого сцена чёрная, и никакой ошибки в консоли может не
  // быть. Перезапуск приложения помогал потому, что новый контекст выдавался
  // с нуля; ровно это и делает кнопка, только дёшево.
  //
  // Порядок важен: сначала снять старый (dispose освобождает контекст), потом
  // сбросить флаги — иначе `loadEngine` увидит `fsEngineRaw` и выйдет молча.
  fsRestartEngine() {
    if (this._engineBusy) { this.flash('движок ещё грузится'); return; }
    // ЗВУК ПЕРВЫМ (Раунд 56, починка починки). Butterchurn читает аудио на
    // КАЖДОМ кадре: визуализатор, собранный без звука, падает на
    // `getByteTimeDomainData` и через три кадра сам себя останавливает —
    // молча, чёрным экраном. Замерено: со звуком движок идёт, ошибок ноль;
    // без звука умирает за три кадра.
    //
    // Моя вчерашняя кнопка звук не поднимала, а `enterFs` — поднимает. Значит
    // после ухода из фристайла и обратно (аудио-граф снимается) кнопка
    // собирала ГЛУХОЙ движок и делала ровно то, на что владелец пожаловался:
    // «ни кнопка, ни перезагрузка не работают».
    try { this.fsAudioStart(); } catch (e) {
      журнал('перезапуск: звук не поднялся: ' + (e && e.message ? e.message : e));
      this.flash('звук не поднялся: ' + (e && e.message ? e.message : e));
    }
    try {
      if (this.fsEngineRaw) this.fsEngineRaw.dispose();
    } catch (e) { /* контекст уже потерян — это и есть повод перезапустить */ }
    this.fsEngineRaw = null;
    this.fsEngine = null;
    this._engErrAt = 0;
    this._fsDead = false;
    this.flash('перезапускаю движок…');
    // НОВЫЙ КАНВАС, а не тот же самый. `dispose` гасит контекст через
    // loseContext (иначе текстуры сцены висят до сборки мусора), и вернуть
    // рабочий контекст ЭТОМУ канвасу уже нельзя. Меняем key — React монтирует
    // чистый элемент, и только после этого поднимаем движок.
    var self = this;
    this.setState({ bcEpoch: (this.state.bcEpoch || 0) + 1 }, function () {
      self.loadEngine();
    });
  },

  loadEngine() {
    if (this._engineBusy || this.fsEngineRaw) return;
    this._engineBusy = true;
    var self = this;
    // динамический импорт: пресеты (2.8 МБ) уезжают в отдельный чанк и не
    // утяжеляют первый экран редактора — как в дизайне, где движок грузился
    // отдельным скриптом при первом входе во фристайл
    import('./freestyle/engine.js').then(function (mod) {
      self._engineBusy = false;
      if (self._fsDead) return;
      var canvas = document.getElementById('bcCanvas');
      if (!canvas) { self.flash('сцена ещё не смонтирована'); return; }
      // Без живого звука движок собирать нельзя — он гарантированно умрёт на
      // первых кадрах (см. fsRestartEngine). Поднимаем граф, а если и это не
      // вышло — говорим честно и не строим обречённое.
      var audio = null;
      try { audio = self.fsAudio() || self.fsAudioStart(); } catch (e) {
        журнал('движок: звук не поднялся: ' + (e && e.message ? e.message : e));
      }
      var драйвер = null;
      try { драйвер = audio && typeof audio.getDriver === 'function' ? audio.getDriver() : null; } catch (e) {
        журнал('движок: getDriver упал: ' + (e && e.message ? e.message : e));
      }
      if (!драйвер) {
        журнал('движок: нет аудио-драйвера, сборку не начинаю (audio=' + (!!audio) + ')');
        self.flash('движок не поднять без звука — проверь аудио');
        return;
      }
      var eng;
      try {
        eng = mod.createEngine(canvas, драйвер, {
          renderScale: self.slider('bcRenderScaleSlider', 70) / 100,
          favorites: self.cfg().fsBcFav || [],
          recent: self.cfg().fsBcRecent || [],
          // избранное и недавние живут в nl_view (решение прожарки 11);
          // ключи с приставкой fs — их не трогают профили вида
          onFavorites: function (list) { self.setCfg('fsBcFav', list); },
          onRecent: function (list) { self.setCfg('fsBcRecent', list); },
          onError: function (e) { self._engErr = e; журнал('движок остановлен: ' + (e && e.message ? e.message : e)); self.onEngineError(); },
        });
      } catch (e) {
        // WebGL2 нет — честный текст вместо чёрного экрана
        журнал('движок: сборка упала: ' + (e && e.message ? e.message : e));
        self.flash(e && e.message ? e.message : String(e));
        return;
      }
      self.fsEngineRaw = eng;
      self.fsEngine = self.fsEngineFacade(eng);
      // первый пресет: без него сцена — чёрный кадр (у Butterchurn стартовый
      // blankPreset пустой). Прототип делал ровно это же при инициализации
      if (!eng.current()) eng.randomPreset(0);
      if (self.state.tab === 'fs') eng.start();
      // СНИМОК СОСТОЯНИЯ (Раунд 56). Журнал ошибок из окна владельца пришёл
      // ПУСТЫМ — значит движок не падает, и чинить «падение» бессмысленно.
      // Чёрная сцена без ошибки — это уже другой разговор: не запустился цикл,
      // нулевой канвас, выключенная визуализация, спящий звук. Спрашиваем всё
      // это разом через две секунды после сборки и пишем одной строкой.
      setTimeout(function () {
        // НЕВИДИМЫЙ ВИЗУАЛИЗАТОР — СКАЗАТЬ ВСЛУХ (Раунд 56).
        //
        // `blankScene()` намеренно гасит подложку визуализатора
        // (fsBcOpacity: 0) — это её работа. Но настройки вида СОХРАНЯЮТСЯ, и
        // ноль оставался навсегда: движок исправно рисовал в невидимый холст,
        // ошибок не было ни одной, и три захода подряд я чинила падение,
        // которого не существовало. Владелец видел чёрный экран и «мигает на
        // несколько кадров и пропадает» — это канвас со значением по умолчанию
        // до того, как приедут сохранённые настройки.
        //
        // Молчать нельзя: ноль плотности неотличим от поломки.
        try {
          var оп = Number((self.cfg() || {}).fsBcOpacity);
          if (self.state.bcOn && оп === 0) {
            self.flash('визуализатор невидим: плотность 0% — подними её в панели сцены');
          }
        } catch (e) { /* подсказка не обязана работать */ }
        try {
          var e2 = self.fsEngineRaw, c2 = document.getElementById('bcCanvas');
          var a2 = self.fsAudio(), st2 = a2 && a2.state ? a2.state() : {};
          var r2 = c2 ? c2.getBoundingClientRect() : {};
          журнал('снимок движка: жив=' + (e2 && e2.isAlive ? e2.isAlive() : '?')
            + ' идёт=' + (e2 && e2.isRunning ? e2.isRunning() : '?')
            + ' fps=' + (e2 && e2.fps ? e2.fps() : '?')
            + ' пресет=' + (e2 && e2.current ? e2.current() : '?')
            + ' | канвас=' + (c2 ? c2.width + 'x' + c2.height : 'нет')
            + ' на экране=' + (c2 ? Math.round(r2.width) + 'x' + Math.round(r2.height) : '?')
            + ' видим=' + (c2 ? getComputedStyle(c2).visibility + '/' + getComputedStyle(c2).display
                                + '/прозр' + getComputedStyle(c2).opacity : '?')
            + ' | вкладка=' + self.state.tab + ' bcOn=' + self.state.bcOn
            + ' | звук=' + (st2.ctx || 'нет') + ' синтетика=' + st2.synthetic
            + ' микрофон=' + st2.mic + ' трек=' + !!st2.track);
        } catch (e) { журнал('снимок движка не снялся: ' + (e && e.message ? e.message : e)); }
      }, 2000);
      var wait = self._engineWait || [];
      self._engineWait = null;
      self.setState({ presetTick: (self.state.presetTick || 0) + 1 }, function () {
        wait.forEach(function (fn) { try { fn(); } catch (e) { console.error('фристайл: отложенный вызов', e); } });
      });
    }, function (e) {
      self._engineBusy = false;
      self.flash('движок не загрузился: ' + (e && e.message ? e.message : String(e)));
    });
  },

  // Случайный пресет — метод прототипа: его зовёт автосмена сцены (bcAutoLoop
  // в methods.fs.js). Без него автосмена падала бы на запасной путь дизайна —
  // клик по скрытой кнопке #btnRandomPreset внутри закрытой панели: работает,
  // но это разговор с движком через DOM, ради ухода от которого и написана
  // связка. Нет движка — тишина, а не ошибка: автосмену включают до входа во
  // фристайл штатно
  randomPreset() {
    var eng = this.fsEngineRaw;
    if (!eng || !eng.isAlive()) return;
    eng.randomPreset();
    this.setState({ presetTick: (this.state.presetTick || 0) + 1 });
  },

  // три подряд упавших кадра гасят цикл движка — говорим честно и уходим на
  // следующий пресет, но не чаще раза в 5 секунд (иначе перебор битых уравнений
  // превратится в мельницу)
  onEngineError() {
    var eng = this.fsEngineRaw;
    if (!eng || !eng.isAlive()) return;
    var now = Date.now();
    if (now - (this._engErrAt || 0) < 5000) return;
    this._engErrAt = now;
    // Честная причина, а не догадка. Раньше здесь всегда стояло «пресет не
    // рисуется», и это увело с толку всех, включая меня: чаще ломается не
    // пресет, а ЗВУК — Butterchurn читает его каждый кадр.
    var e = this._engErr;
    var проЗвук = e && /getByteTimeDomainData|audio/i.test(String(e.message || e));
    if (проЗвук) {
      this.flash('движок остановлен: нет звука — включи микрофон, трек или синтетику');
      return;
    }
    this.flash('пресет не рисуется — беру следующий');
    eng.randomPreset(0);
    if (this.state.tab === 'fs') eng.start();
  },

  // Фасад для панели пресетов (render.fspanels.jsx ждёт presets/current/pick/
  // toggleFav/random/recent). Каталог движка отдаёт имена, панель — строки.
  fsEngineFacade(eng) {
    var self = this;
    var tick = function () { self.setState({ presetTick: (self.state.presetTick || 0) + 1 }); };
    return {
      presets: function () {
        var st = self.state;
        var rec = {};
        eng.recentList().forEach(function (n) { rec[n] = 1; });
        return eng.query({ tab: st.presetTab || 'all', q: st.presetQ || '' })
          .map(function (n) { return { name: n, tag: '', fav: eng.isFav(n), recent: !!rec[n] }; });
      },
      current: function () { return eng.current(); },
      pick: function (name) {
        if (!eng.loadPreset(name)) self.flash('пресет не найден: ' + name);
        tick();
      },
      toggleFav: function (name) { eng.toggleFav(name); tick(); },
      random: function () { eng.randomPreset(); tick(); },
      recent: function () { return eng.recentList(); },
    };
  },

  // ---- ореол: bcCanvas → bloomCanvas ----------------------------------
  bloomLoop() {
    if (this._bloomRAF) return;
    var self = this;
    var tick = function (ts) {
      self._bloomRAF = requestAnimationFrame(tick);
      if (self.state.tab !== 'fs' || !self.state.bcOn) return;
      if (self._bloomT && ts - self._bloomT < BLOOM_MS) return;
      self._bloomT = ts;
      self.drawBloom();
    };
    this._bloomRAF = requestAnimationFrame(tick);
  },
  // Блюр здесь делается уменьшением и обратным растягиванием, а НЕ ctx.filter:
  // у canvas 2D в WebKit (движок окна приложения) свойства filter НЕТ ВООБЩЕ,
  // причём присваивание проходит молча — блюр просто не применялся, и блум
  // выглядел резкой копией картинки поверх неё же. Найдено замером фазы 4.
  // Билинейная фильтрация при обратном растягивании даёт настоящее размытие,
  // а яркость и насыщенность добавляем режимом наложения 'lighter' с повтором.
  drawBloom() {
    var src = document.getElementById('bcCanvas'), dst = document.getElementById('bloomCanvas');
    if (!src || !dst || !src.width || !dst.width) return;
    var g = dst.getContext('2d');
    if (!g) return;
    g.clearRect(0, 0, dst.width, dst.height);
    // промежуточный буфер живёт между кадрами — на каждый кадр его не создаём
    var tmp = this._bloomTmp;
    if (!tmp) { tmp = this._bloomTmp = document.createElement('canvas'); }
    // 1/8 от цели: радиус размытия задаётся именно этим коэффициентом
    var tw = Math.max(1, dst.width >> 3), th = Math.max(1, dst.height >> 3);
    if (tmp.width !== tw || tmp.height !== th) { tmp.width = tw; tmp.height = th; }
    var t = tmp.getContext('2d');
    if (!t) return;
    t.clearRect(0, 0, tw, th);
    // ПОЛЯ ВОКРУГ УМЕНЬШЕННОГО КАДРА (Раунд 56). Владелец: «свечение как будто
    // вылезает за какую-то рамку и резко обрывается». Так и было: размытие
    // здесь делается уменьшением и обратным растягиванием, а билинейная
    // фильтрация на краю ЗАЖИМАЕТ крайний пиксель — свечение не угасает, а
    // упирается в границу и обрывается по прямой.
    //
    // Рисуем кадр внутрь буфера с отступом в один пиксель: по периметру
    // остаётся прозрачная рамка, и при растягивании свечение уходит в неё
    // плавно. Цена — ноль, тот же единственный drawImage.
    try { t.drawImage(src, 1, 1, Math.max(1, tw - 2), Math.max(1, th - 2)); }
    catch (e) { return; /* канвас ещё пуст */ }
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = 'high';
    // два прохода 'lighter' поверх друг друга — это и есть подъём яркости
    // (взамен brightness(1.7)); слой composited в CSS через mix-blend-mode: screen
    g.globalCompositeOperation = 'source-over';
    g.globalAlpha = 0.75;
    g.drawImage(tmp, 0, 0, dst.width, dst.height);
    g.globalCompositeOperation = 'lighter';
    g.globalAlpha = 0.55;
    g.drawImage(tmp, 0, 0, dst.width, dst.height);
    g.globalAlpha = 1;
    g.globalCompositeOperation = 'source-over';
  },

  // ---- прокидывание настроек в сцену (дизайн 2404..2427) ---------------
  syncEngine() {
    var eng = this.fsEngineRaw;
    if (this.state.tab !== 'fs') {
      // Уход с вкладки гасит ТОЛЬКО цикл кадров. Визуализатор, его связь с
      // шиной и сам аудио-граф живы — поэтому возврат мгновенный, без
      // пересборки и без паузы в показе (решение прожарки 10).
      if (eng && eng.isAlive() && eng.isRunning()) eng.stop();
      return;
    }
    // визуализация выключена — канвас скрыт, и гонять кадры незачем; включат
    // обратно, и цикл поднимется тем же путём, без пересборки
    if (eng && eng.isAlive()) {
      if (this.state.bcOn === false) { if (eng.isRunning()) eng.stop(); }
      else if (!eng.isRunning()) eng.start();
    }
    this.fsSeed();
    this.fitLine();
    this.fsAutoLoop();
    // громкость лупа: ползунок движка — вход, cfg.fsGain — источник правды
    var gain = Math.max(0, Math.min(100, this.cfgNumVal('fsGain', 80)));
    var el = document.getElementById('trackGainSlider');
    if (el && el.value !== String(Math.round(gain))) el.value = String(Math.round(gain));
    if (this._gainNow !== gain) {
      this._gainNow = gain;
      if (this._audio) this._audio.setTrackGain(gain / 100);
    }
    this.harvestFonts();
    this.autoColorLoop();
    this.bcAutoLoop();
    this.pushScene();
    this.watchStage();
    this.fitStage();
  },

  // ---- ручки окон (дизайн 3044..3076) ---------------------------------
  onCardInput(e) {
    var t = e.target;
    if (!t || !t.id) return;
    var out = (t.closest && t.closest('[data-row]') && t.closest('[data-row]').querySelector('[data-val-for="' + t.id + '"]'))
      || (this._cards && this._cards.querySelector('[data-val-for="' + t.id + '"]'))
      || document.querySelector('[data-val-for="' + t.id + '"]');
    if (out) out.textContent = t.value + (out.getAttribute('data-val-suffix') || '');
    var v = parseFloat(t.value);
    var stage = this.fsStage();
    if (stage) {
      if (t.id === 'panelOpacitySlider') stage.style.setProperty('--panel-opacity', String(v / 100));
      if (t.id === 'panelColorPicker') stage.style.setProperty('--panel', t.value);
      if (t.id === 'glowColorPicker') this.setState({ glowColor: t.value });
      if (e.isTrusted && (t.id === 'panelColorPicker' || t.id === 'inkColor' || t.id === 'glowColorPicker')) {
        this.rememberPal(t.id === 'panelColorPicker' ? 'panel' : (t.id === 'glowColorPicker' ? 'glow' : 'ink'), t.value);
      }
      if (t.id === 'blendSelect') stage.style.setProperty('--blend', t.value);
      // слой красится только через --panel: своих инлайн-значений сюда не пишем
      if (t.id === 'bloomSlider') stage.style.setProperty('--bloom-opacity', String(v / 100));
      if (t.id === 'grainSlider') stage.style.setProperty('--grain-opacity', String(v / 100));
      if (t.id === 'bgBlurSlider') stage.style.setProperty('--bg-blur', (v / 2.5) + 'px');
      if (t.id === 'inkColor') stage.style.setProperty('--ink-on-color', t.value);
    }
    // размер буфера визуализатора принадлежит движку (дизайн звал сюда
    // window.__bcSetRenderScale внешнего скрипта); блум и зерно — наши
    if (t.id === 'bcRenderScaleSlider') {
      if (this.fsEngineRaw && this.fsEngineRaw.isAlive()) this.fsEngineRaw.setRenderScale(v / 100);
      this.sizeBuffers();
    }
    // громкость лупа: единственный вход, который идёт не в картинку, а в звук
    if (t.id === 'trackGainSlider') {
      this._gainNow = v;
      if (this._audio) this._audio.setTrackGain(v / 100);
    }
    var key = this.FSLIVE[t.id];
    if (key) {
      this._live = this._live || {};
      this._live[key] = v;
      this.pushFilters();
      if (key === 'scale' || key === 'glow' || key === 'textBlur' || key === 'distort') this.fitLine();
      // Слой строки на видеокарте держит текст в текстуре, поэтому крутилки,
      // меняющие ЕГО картинку, обязаны перепечь её: иначе они отзывались бы
      // только на следующей строке.
      if ((key === 'distort' || key === 'glow' || key === 'scale' || key === 'textBlur') && this.fsВарп) this.fsВарп(this._lineTxt || '');
      this.setState({ live: Object.assign({}, this._live) });
    }
  },

  // Избранное и журнал пресетов из nl_view — в уже живой движок. setFavorites/
  // setRecent сделаны для этого: они молчат, иначе загрузка настроек сама же
  // вызвала бы их перезапись
  fsHydrateEngine() {
    var eng = this.fsEngineRaw;
    if (!eng || !eng.isAlive()) return;
    var C = this.cfg();
    if (C.fsBcFav) eng.setFavorites(C.fsBcFav);
    if (C.fsBcRecent) eng.setRecent(C.fsBcRecent);
    this.setState({ presetTick: (this.state.presetTick || 0) + 1 });
  },

  // имя пресета из чужого профиля: сначала как есть, потом с суффиксом пака
  // (наш каталог разводит дубликаты имён — см. риски engine.js)
  fsPresetName(name) {
    var eng = this.fsEngineRaw;
    if (!eng || !name) return name;
    if (eng.has(name)) return name;
    for (var i = 0; i < PACK_SUFFIX.length; i++) {
      if (eng.has(name + PACK_SUFFIX[i])) return name + PACK_SUFFIX[i];
    }
    return name;
  },

  // ---- снос ------------------------------------------------------------
  fsGlueUnmount() {
    this._fsDead = true;
    if (this._bloomRAF) cancelAnimationFrame(this._bloomRAF);
    this._bloomRAF = 0;
    if (this.fsEngineRaw) { this.fsEngineRaw.dispose(); this.fsEngineRaw = null; }
    this.fsEngine = null;
    if (this._audioOff) { this._audioOff(); this._audioOff = null; }
    if (this._audio) { this._audio.dispose(); this._audio = null; }
  },
};
