// Аудио-граф фристайла: один AudioContext, один узел-водитель картинки.
//
// ПОЧЕМУ ТАК. В прототипе (mockups/design-v2/freestyle-engine.js) движок
// подключался к самому источнику: `visualizer.connectAudio(synthGain)`, а на
// каждую смену источника вызывались connectAudio/disconnectAudio. Отсюда две
// болезни: свой звук «не влиял» (при живом лупе синтетика оставалась
// подключённой и продолжала водить картинку) и показ дёргался в момент
// пересборки связей.
//
// Здесь связь с движком одна на всю жизнь модуля: driverBus (GainNode) —
// единственный сумматор, в который сходятся ВСЕ источники, влияющие на
// картинку. Визуализатор подключается к нему ровно один раз (attachVisualizer)
// и больше не переподключается никогда. Переключение источников — ТОЛЬКО
// gain-рампы на уже существующих узлах: поэтому подхват мгновенный, без щелчка
// и без единого пропущенного кадра.
//
// Слышимость и «вождение картинки» — две РАЗНЫЕ ветки:
//   синтетика  → synthGain            → driverBus                (не слышна)
//   луп        → trackPre → trackGain → driverBus + destination  (слышен)
//   микрофон   → micPre   → micGain   → driverBus                (не слышен)
// Микрофон в destination не идёт принципиально: это вой обратной связи через
// колонки.
//
// Синтетика УСТУПАЕТ живому звуку — и лупу, и микрофону (см. synthOn ниже).
// Она подпорка на случай тишины, а не фон поверх всего. Слышимый тракт лупа — source → gain → destination напрямую, без
// анализаторов и обработки, частота дискретизации не режется.

// рабочий уровень синтетики на шине водителя; абсолютное значение почти не
// важно (Butterchurn нормирует уровни на скользящее среднее), важно лишь
// чтобы сигнал был широкополосным и ненулевым
const SYNTH_LEVEL = 0.6;

// постоянная времени для setTargetAtTime: за 3τ (≈120 мс) значение проходит
// ~95% пути — это и есть «плавно за ~120мс» из решения прожарки
const FADE_TAU = 0.04;
// когда фактически глушить источник лупа: заметно позже конца рампы, иначе
// обрыв на ненулевом сэмпле даст щелчок в колонках
const FADE_TAIL_S = 0.2;

// длина кольца розового шума; 6 секунд — шва на стыке не слышно (да его и
// некому слышать: синтетика в колонки не идёт), а память не жрём
const NOISE_SEC = 6;

function clamp01(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  return n < 0 ? 0 : (n > 1 ? 1 : n);
}

// Рампа на уже существующем параметре. Сначала гасим всё ранее назначенное,
// иначе две рампы подряд (быстро сняли и вернули луп) складываются в скачок.
function ramp(param, target, ctx) {
  const t = ctx.currentTime;
  if (typeof param.cancelAndHoldAtTime === 'function') {
    param.cancelAndHoldAtTime(t);
  } else {
    param.cancelScheduledValues(t);
    param.setValueAtTime(param.value, t);
  }
  param.setTargetAtTime(target, t, FADE_TAU);
}

// Розовый шум (фильтр Пола Келлета). ПОЧЕМУ шум, а не тон: Butterchurn делит
// спектр на бас 20–320 / серед. 320–2800 / верх 2800–11025 Гц и реагирует на
// все три полосы. Пара осцилляторов из прототипа кормила только бас — картинка
// вяло дышала. Розовый шум даёт честную энергию во всех трёх.
function fillPinkNoise(data) {
  let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
  for (let i = 0; i < data.length; i++) {
    const w = Math.random() * 2 - 1;
    b0 = 0.99886 * b0 + w * 0.0555179;
    b1 = 0.99332 * b1 + w * 0.0750759;
    b2 = 0.96900 * b2 + w * 0.1538520;
    b3 = 0.86650 * b3 + w * 0.3104856;
    b4 = 0.55000 * b4 + w * 0.5329522;
    b5 = -0.7616 * b5 - w * 0.0168980;
    data[i] = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
    b6 = w * 0.115926;
  }
  return data;
}

// честный русский текст ошибки микрофона — показывает вызывающий
function micError(e) {
  const name = e && e.name;
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'доступ к микрофону запрещён — разрешите его в настройках браузера';
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'микрофон не найден';
  }
  if (name === 'NotReadableError') {
    return 'микрофон занят другой программой';
  }
  return 'микрофон не включился: ' + ((e && e.message) || 'неизвестная ошибка');
}

/**
 * @param {object} [opts]
 * @param {Function} [opts.AudioContextCtor] — подмена конструктора (тесты)
 * @param {Function} [opts.getUserMedia] — подмена getUserMedia (тесты)
 */
export function createAudio(opts) {
  const o = opts || {};

  let ctx = null;
  let driverBus = null;   // единственная точка входа визуализатора
  let levels = null;      // терминальный AnalyserNode на шине
  let synthGain = null;   // уровень синтетики на шине
  let synthAm = null;     // узел амплитудной модуляции синтетики
  let noiseSrc = null;    // кольцо розового шума — НИКОГДА не останавливается
  let lfo = null;
  let lfoDepth = null;
  let trackGain = null;   // слышимый уровень лупа
  let micGain = null;     // уровень микрофона на шине
  let trackPre = null;    // ПРЕ-ФЕЙДЕРНАЯ точка отвода лупа (см. ensure)
  let micPre = null;      // ПРЕ-ФЕЙДЕРНАЯ точка отвода микрофона

  let trackSrc = null;
  let trackInfo = null;   // {name, playing}
  let dyingSrc = null;    // источник, который догорает после рампы
  let micSrc = null;
  let micStream = null;

  let trackLevel = 0.8;   // дизайн: ползунок «трек» по умолчанию 80%
  let micLevel = 1;

  // КТО ВОДИТ КАРТИНКУ — одно правило вместо трёх разных мест (Раунд 56).
  //
  // Синтетика — подпорка на случай тишины: она даёт Butterchurn'у сигнал,
  // когда своего звука нет вовсе. Луп её вытеснял, а МИКРОФОН нет — и это
  // была не мелочь. Розовый шум широкополосный и ПОСТОЯННЫЙ, а Butterchurn
  // нормирует уровни на скользящее среднее: голос тонул в шумовом полу, и
  // владелец видел ровно то, что описал — «включил и не работает».
  //
  // Теперь синтетика звучит ТОЛЬКО когда нет ни лупа, ни микрофона, и когда
  // её не выключили руками. Ручной выключатель — его же просьба: «мб есть
  // смысл отдельную кнопку для синтетического шума сделать, чтоб вручную
  // всем этим управлять».
  let synthWanted = true;
  const synthOn = () => synthWanted && !trackInfo && !micSrc;
  const applySynth = () => {
    if (ctx && synthGain) ramp(synthGain.gain, synthOn() ? SYNTH_LEVEL : 0, ctx);
  };
  let visualizer = null;
  let gestureOff = null;
  let dead = false;

  function Ctor() {
    if (o.AudioContextCtor) return o.AudioContextCtor;
    if (typeof window === 'undefined') return null;
    return window.AudioContext || window.webkitAudioContext || null;
  }

  // Ленивое создание графа: до первого жеста пользователя браузер всё равно
  // держит контекст в suspended, а собирать граф раньше незачем.
  function ensure() {
    if (ctx) return ctx;
    if (dead) throw new Error('аудио уже выключено');
    const C = Ctor();
    if (!C) throw new Error('браузер не поддерживает Web Audio');

    // 48000 — просьба, а не требование: часть карт умеет только 44100 и тогда
    // конструктор бросает NotSupportedError. Падать из-за этого нельзя, поэтому
    // честная деградация до системной частоты. latencyHint 'playback' — крупный
    // буфер: меньше нагрузка на звуковую карту, а задержка тут никого не жмёт.
    try {
      ctx = new C({ sampleRate: 48000, latencyHint: 'playback' });
    } catch (e) {
      ctx = new C({ latencyHint: 'playback' });
    }

    driverBus = ctx.createGain();
    driverBus.gain.value = 1;

    // Терминальный анализатор на шине. Две работы сразу:
    //  1) даёт уровни наружу (getLevels), если сцене они понадобятся;
    //  2) держит ветку живой. Узел без выходных связей — «automatic pull node»:
    //     движок Web Audio прокачивает его каждый квант. Без этого граф,
    //     не доходящий до destination, мог бы вообще не считаться, и синтетика
    //     молчала бы до подключения визуализатора. В destination шина не идёт.
    levels = ctx.createAnalyser();
    levels.fftSize = 2048;
    levels.smoothingTimeConstant = 0.7;
    driverBus.connect(levels);

    // --- синтетика: розовый шум + медленная амплитудная модуляция ----------
    const len = Math.max(1, Math.floor(ctx.sampleRate * NOISE_SEC));
    const buf = ctx.createBuffer(1, len, ctx.sampleRate);
    fillPinkNoise(buf.getChannelData(0));

    noiseSrc = ctx.createBufferSource();
    noiseSrc.buffer = buf;
    noiseSrc.loop = true;

    synthAm = ctx.createGain();
    synthAm.gain.value = 0.55;      // центр модуляции
    lfo = ctx.createOscillator();
    lfo.frequency.value = 0.18;     // тот же медленный вдох-выдох, что в прототипе
    lfoDepth = ctx.createGain();
    lfoDepth.gain.value = 0.35;     // итог гуляет ≈0.2…0.9
    lfo.connect(lfoDepth);
    lfoDepth.connect(synthAm.gain);

    synthGain = ctx.createGain();
    synthGain.gain.value = synthOn() ? SYNTH_LEVEL : 0;

    noiseSrc.connect(synthAm);
    synthAm.connect(synthGain);
    synthGain.connect(driverBus);   // и НИКОГДА в destination — она не слышна

    noiseSrc.start(0);
    lfo.start(0);

    // --- луп: слышимый тракт + ветка на картинку ---------------------------
    trackGain = ctx.createGain();
    trackGain.gain.value = 0;       // поднимем рампой при загрузке
    trackGain.connect(ctx.destination); // прямо в выход, без обработки
    trackGain.connect(driverBus);       // параллельно — водить картинку

    // ПРЕ-ФЕЙДЕРНАЯ точка отвода лупа. gain=1 навсегда — узел прозрачный, для
    // слуха и для картинки ничего не меняется, маршрутизация та же.
    // ПОЧЕМУ она вообще нужна: отвод, повешенный на trackGain, снимал бы сигнал
    // ПОСЛЕ ползунка громкости — убавил колонки, получил тихую запись
    // (замерено на спайке: пик 0.0141 при уровне мониторинга 0.02, то есть
    // запись повторяла ползунок). Запись обязана слышать источник, а не то, что
    // в комнате. Ползунки остаются исключительно про мониторинг.
    trackPre = ctx.createGain();
    trackPre.gain.value = 1;
    trackPre.connect(trackGain);

    // --- микрофон: только на картинку --------------------------------------
    micGain = ctx.createGain();
    micGain.gain.value = 0;
    micGain.connect(driverBus);

    // тот же довод, что и для лупа: отвод до ползунка микрофона
    micPre = ctx.createGain();
    micPre.gain.value = 1;
    micPre.connect(micGain);

    return ctx;
  }

  function resumeCtx() {
    if (ctx && ctx.state === 'suspended' && typeof ctx.resume === 'function') {
      const p = ctx.resume();
      if (p && typeof p.catch === 'function') p.catch(() => {});
    }
  }

  return {
    // Создать граф (идемпотентно) и попробовать запустить контекст.
    start() {
      ensure();
      resumeCtx();
      return ctx;
    },

    // Одноразовые слушатели первого жеста — политика автозапуска браузеров
    // разрешает resume() только из обработчика реального ввода.
    resumeOnGesture() {
      if (typeof window === 'undefined') return () => {};
      if (gestureOff) return gestureOff;
      const fire = () => {
        off();
        try { ensure(); } catch (e) { return; }
        resumeCtx();
      };
      const off = () => {
        window.removeEventListener('pointerdown', fire, true);
        window.removeEventListener('keydown', fire, true);
        gestureOff = null;
      };
      window.addEventListener('pointerdown', fire, true);
      window.addEventListener('keydown', fire, true);
      gestureOff = off;
      return off;
    },

    // Узел-сумматор: к нему и только к нему подключается визуализатор.
    getDriver() {
      ensure();
      return driverBus;
    },

    // Терминальный анализатор шины — уровни всех источников разом.
    getLevels() {
      ensure();
      return levels;
    },

    /**
     * Пре-фейдерные точки отвода для записи. Прозрачные узлы gain=1, стоящие
     * МЕЖДУ источником и ползунком: запись снимает то, что дал источник, а не
     * то, что осталось после мониторного гейта. Вешать на них можно только
     * тупики (numberOfOutputs 0) — иначе отвод залезет в слышимый тракт.
     * @returns {{track: GainNode, mic: GainNode}}
     */
    getTaps() {
      ensure();
      return { track: trackPre, mic: micPre };
    },

    // Подключить визуализатор Butterchurn. Вызывается ОДИН раз за жизнь сцены;
    // повтор с тем же объектом — тишина. Смена источников звука сюда не ходит.
    attachVisualizer(vis) {
      ensure();
      if (!vis || typeof vis.connectAudio !== 'function') {
        throw new Error('визуализатор не умеет connectAudio');
      }
      if (visualizer === vis) return;
      // пересоздание визуализатора бывает только при пересборке сцены
      // (StrictMode, смена канваса) — тогда старую связь честно снимаем
      if (visualizer && typeof visualizer.disconnectAudio === 'function') {
        try { visualizer.disconnectAudio(driverBus); } catch (e) { /* уже мёртв */ }
      }
      vis.connectAudio(driverBus);
      visualizer = vis;
    },

    /**
     * Загрузить луп. Он становится слышимым и водит картинку, синтетика молча
     * отходит — но её генератор продолжает крутиться, чтобы возврат был
     * мгновенным.
     * @param {File|Blob} file
     * @returns {Promise<{name:string}>}
     */
    async loadTrack(file) {
      ensure();
      resumeCtx();
      const name = (file && file.name) || 'трек';
      let buf;
      try {
        const ab = await file.arrayBuffer();
        buf = await ctx.decodeAudioData(ab);
      } catch (e) {
        throw new Error('не удалось прочитать «' + name + '»: формат не поддержан');
      }
      if (dead) return { name };

      // замена лупа на лету: гасим уровень ДО обрыва старого источника,
      // иначе его хвост оборвётся на громком сэмпле — щелчок
      trackGain.gain.cancelScheduledValues(ctx.currentTime);
      trackGain.gain.setValueAtTime(0, ctx.currentTime);
      stopSource(true);

      trackSrc = ctx.createBufferSource();
      trackSrc.buffer = buf;
      // бесшовно и бесконечно: петля в самом источнике — она сэмпл-точная,
      // без склейки на JS и без разрыва между проходами
      trackSrc.loop = true;
      trackSrc.connect(trackPre);     // trackPre → trackGain: отвод до ползунка
      trackSrc.start(0);

      trackInfo = { name, playing: true };
      ramp(trackGain.gain, trackLevel, ctx);
      applySynth();                   // синтетика уходит в ноль, но не глохнет
      return { name };
    },

    // Снять луп: синтетика подхватывает мгновенно — обе рампы на уже
    // существующих узлах, ни одного connect/disconnect у визуализатора.
    stopTrack() {
      if (!ctx || !trackInfo) return;
      ramp(trackGain.gain, 0, ctx);
      stopSource(false);
      trackInfo = null;
      applySynth();
    },

    /**
     * Синтетика вручную (Раунд 56). Владелец: «включил микрофон и не работает,
     * мб из-за синтетического шума — мб есть смысл отдельную кнопку сделать,
     * чтоб вручную всем этим управлять».
     * @param {boolean} on
     */
    setSynth(on) {
      synthWanted = !!on;
      applySynth();
    },

    /**
     * Включить/выключить микрофон. Он влияет на картинку ПАРАЛЛЕЛЬНО лупу.
     * @returns {Promise<boolean>} новое состояние
     * @throws {Error} честный русский текст при отказе
     */
    async toggleMic() {
      ensure();
      resumeCtx();
      if (micSrc) {
        ramp(micGain.gain, 0, ctx);
        const src = micSrc, stream = micStream;
        micSrc = null;
        micStream = null;
        applySynth();
        // рвём связь после рампы, иначе щелчок
        setTimeout(() => {
          try { src.disconnect(); } catch (e) { /* уже снят */ }
          if (stream) stream.getTracks().forEach((t) => { try { t.stop(); } catch (e) {} });
        }, FADE_TAIL_S * 1000);
        return false;
      }
      const gum = o.getUserMedia
        || (typeof navigator !== 'undefined' && navigator.mediaDevices
            && navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices));
      if (!gum) throw new Error('браузер не даёт доступ к микрофону');
      let stream;
      try {
        // сырой сигнал: обработка «для телефона» съедает динамику и спектр,
        // а картинке нужен честный сигнал
        stream = await gum({
          audio: {
            echoCancellation: false,
            noiseSuppression: false,
            autoGainControl: false,
          },
          video: false,
        });
      } catch (e) {
        throw new Error(micError(e));
      }
      if (dead) {
        stream.getTracks().forEach((t) => { try { t.stop(); } catch (e2) {} });
        return false;
      }
      micStream = stream;
      micSrc = ctx.createMediaStreamSource(stream);
      micSrc.connect(micPre);         // и только сюда: micPre → micGain → driverBus
      ramp(micGain.gain, micLevel, ctx);
      applySynth();
      return true;
    },

    // 0…1 (панель дизайна даёт 0…100 — делить на 100 её забота)
    setTrackGain(v) {
      trackLevel = clamp01(v);
      if (ctx && trackInfo) ramp(trackGain.gain, trackLevel, ctx);
    },

    setMicGain(v) {
      micLevel = clamp01(v);
      if (ctx && micSrc) ramp(micGain.gain, micLevel, ctx);
    },

    state() {
      return {
        ctx: ctx ? ctx.state : null,
        synthetic: synthOn(),           // синтетика ВОДИТ картинку прямо сейчас
        synthWanted: synthWanted,       // и разрешена ли она вручную
        track: trackInfo ? { name: trackInfo.name, playing: trackInfo.playing } : null,
        mic: !!micSrc,
        sampleRate: ctx ? ctx.sampleRate : 0,
      };
    },

    dispose() {
      dead = true;
      if (gestureOff) gestureOff();
      if (!ctx) return;
      stopSource(true);
      if (micSrc) {
        try { micSrc.disconnect(); } catch (e) {}
        micSrc = null;
      }
      if (micStream) {
        micStream.getTracks().forEach((t) => { try { t.stop(); } catch (e) {} });
        micStream = null;
      }
      try { noiseSrc.stop(); } catch (e) {}
      try { lfo.stop(); } catch (e) {}
      [noiseSrc, lfo, lfoDepth, synthAm, synthGain, trackPre, trackGain, micPre, micGain,
        driverBus, levels]
        .forEach((n) => { try { n.disconnect(); } catch (e) {} });
      if (typeof ctx.close === 'function') {
        const p = ctx.close();
        if (p && typeof p.catch === 'function') p.catch(() => {});
      }
      ctx = null;
      visualizer = null;
      trackInfo = null;
    },
  };

  // Погасить текущий источник лупа. now=true — рвать немедленно (замена трека
  // или снос графа), иначе дать догореть рампе.
  function stopSource(now) {
    if (dyingSrc) {
      try { dyingSrc.stop(); } catch (e) {}
      try { dyingSrc.disconnect(); } catch (e) {}
      dyingSrc = null;
    }
    if (!trackSrc) return;
    const src = trackSrc;
    trackSrc = null;
    if (now) {
      try { src.stop(); } catch (e) {}
      try { src.disconnect(); } catch (e) {}
      return;
    }
    dyingSrc = src;
    try { src.stop(ctx.currentTime + FADE_TAIL_S); } catch (e) {}
    setTimeout(() => {
      if (dyingSrc === src) dyingSrc = null;
      try { src.disconnect(); } catch (e) {}
    }, FADE_TAIL_S * 1000 + 40);
  }
}

export default createAudio;
