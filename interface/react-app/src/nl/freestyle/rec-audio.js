// Запись аудио: два отвода (луп и микрофон) → PCM16 чанками → мост в Python.
//
// Где что происходит и почему именно там:
//
//   рендер-поток (rec-worklet.js)  копит кванты и конвертирует Float32 → Int16
//   аудио-колбэк (port.onmessage)  ТОЛЬКО кладёт готовый Int16 в очередь
//   насос (pump)                   base64 + await bridge.rec_chunk(...)
//
// base64 делается в насосе, а не в колбэке: колбэк дёргается из обработчика
// сообщений порта, и любая лишняя работа там — риск для картинки. В насосе она
// стоит своих 1.17 мс на 96 КБ (замер спайка; массивом чисел было бы 18.5 мс —
// в 16 раз дороже, поэтому именно base64).
//
// ПОЧЕМУ СТРОГО await И ОЧЕРЕДЬ НА ДОРОЖКУ. Мост pywebview заводит НА КАЖДЫЙ
// вызов свой поток Python (webview/util.py:335) и порядок доставки не
// гарантирует. Отправить чанки «пачкой» (fire-and-forget или Promise.all) —
// значит разрешить им приехать в файл в перепутанном порядке, то есть получить
// запись с переставленными полусекундами. Поэтому на каждую дорожку — своя
// очередь и свой насос: следующий чанк уходит ТОЛЬКО после ответа на
// предыдущий. Дорожки друг друга не ждут: два насоса работают параллельно.
//
// ЕСЛИ МОСТ НЕ УСПЕВАЕТ. Очередь молча растущая — это утечка памяти и
// испорченная запись, о которой узнаёшь потом. Поэтому у очереди есть потолок:
// перебор — это ошибка наружу (onError + stats().error), а лишние чанки честно
// считаются потерянными. Дыры в seq увидит и Python.

// Потолок очереди на дорожку, в чанках (~0.5 с каждый). Мост замерен на 78 МБ/с
// = 426× реального времени, так что 8 чанков в очереди — это не «пик нагрузки»,
// а сломанный мост.
const MAX_QUEUE = 8;

// Сколько ждать хвост при остановке: flush + последний ответ моста.
const DRAIN_MS = 3000;

// Дорожки: имя → точка съёма в audio.js → сколько каналов писать. Луп стерео
// (его и слушают), микрофон моно — второй канал у него был бы точной копией
// первого, то есть вдвое больший файл ни за что.
//
// ПОЧЕМУ name И tap РАЗНЫЕ. Имя дорожки — это имя ФАЙЛА и ключ во всех
// мостовых вызовах: PLAN.md знает три файла — video, mic, loop. А точка съёма
// в audio.js исторически зовётся track (getTaps() → {track, mic}), и трогать
// чужой аудио-граф ради переименования незачем. Поэтому здесь ровно одно
// место, где «луп» и «трек» встречаются, и дальше наружу идёт только loop.
const TRACKS = [
  { name: 'loop', tap: 'track', channels: 2 },
  { name: 'mic', tap: 'mic', channels: 1 },
];

// Int16Array → base64. Через Uint8Array поверх того же буфера: копии нет,
// порядок байт — родной little-endian, ровно такой, какого ждёт PCM в WAV.
// Кусками по 32 КБ, потому что String.fromCharCode.apply на всём массиве
// разом упирается в потолок аргументов и падает.
function toBase64(int16) {
  const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
  const STEP = 0x8000;
  let s = '';
  for (let i = 0; i < bytes.length; i += STEP) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + STEP));
  }
  return btoa(s);
}

// Адрес модуля воркл ета. import.meta.url — единственный способ получить его
// так, чтобы он пережил сборку (у Vite файл станет ассетом с хешем в имени).
// Тесты и нестандартные сборки подменяют его через opts.workletUrl.
function defaultWorkletUrl() {
  return new URL('./rec-worklet.js', import.meta.url).href;
}

/**
 * @param {object} audio — модуль из audio.js (нужны start() и getTaps())
 * @param {object} bridge — мост Python: обязателен метод rec_chunk(track, seq, b64)
 * @param {object} [opts]
 * @param {string} [opts.workletUrl] — подмена адреса модуля (тесты/сборки)
 * @param {number} [opts.maxQueue] — потолок очереди на дорожку, в чанках
 * @param {Function} [opts.onError] — (track, message) при первой беде на дорожке
 * @param {Function} [opts.WorkletNode] — подмена AudioWorkletNode (тесты)
 * @param {Function} [opts.encode] — подмена base64-кодировщика (тесты)
 */
export function createAudioRec(audio, bridge, opts) {
  const o = opts || {};
  const maxQueue = o.maxQueue || MAX_QUEUE;
  const encode = o.encode || toBase64;

  let running = false;
  let moduleAdded = false;
  let sampleRate = 0;
  const st = {};        // имя дорожки → состояние и статистика
  const nodes = {};     // имя дорожки → AudioWorkletNode

  for (const t of TRACKS) st[t.name] = fresh(t.channels);

  function fresh(channels) {
    return {
      channels,
      queue: [],        // чанки, ждущие моста
      pumping: false,
      accepting: false, // пока true — колбэк кладёт чанки в очередь
      chunks: 0,        // отправлено и подтверждено мостом
      bytes: 0,
      frames: 0,
      peak: 0,          // максимум за всю запись, единицы int16 (0…32767)
      rms: 0,           // последний измеренный
      errors: 0,
      dropped: 0,       // чанков выброшено из-за переполнения очереди
      lostFrames: 0,
      maxQueued: 0,
      lastSeq: -1,
      error: null,      // первая беда: текст по-русски
    };
  }

  // Беда на дорожке. Первая — наружу и в stats; последующие только считаются,
  // чтобы не залить onError сотней одинаковых строк.
  function fail(name, msg) {
    const s = st[name];
    s.errors++;
    if (s.error) return;
    s.error = msg;
    if (typeof o.onError === 'function') {
      try { o.onError(name, msg); } catch (e) { /* обработчик не наша забота */ }
    }
  }

  // Насос дорожки: строго по одному чанку за раз, следующий — после ответа.
  async function pump(name) {
    const s = st[name];
    if (s.pumping) return;
    s.pumping = true;
    try {
      while (s.queue.length) {
        const c = s.queue[0];             // из очереди снимаем ПОСЛЕ ответа:
        let b64;                          // иначе провал моста стёр бы чанк
        try {
          b64 = encode(c.buf);
        } catch (e) {
          s.queue.shift();
          s.lostFrames += c.frames;
          fail(name, 'не удалось закодировать чанк записи: ' + errText(e));
          continue;
        }
        try {
          // Питон отвечает объектом, а не исключением: {ok:false, error} —
          // это НЕ «повторите», это уже случившаяся дырка в файле (номер
          // сожжён). Молча считать такой ответ успехом нельзя: ровно так и
          // получается «все счётчики зелёные, а в записи провал».
          const res = await bridge.rec_chunk(name, c.seq, b64);
          if (res && res.ok === false) {
            s.queue.shift();
            s.lostFrames += c.frames;
            fail(name, 'питон не принял чанк записи #' + c.seq + ': '
              + (res.error || 'без объяснения'));
            continue;
          }
        } catch (e) {
          s.queue.shift();
          s.lostFrames += c.frames;
          fail(name, 'мост не принял чанк записи #' + c.seq + ': ' + errText(e));
          continue;
        }
        s.queue.shift();
        s.chunks++;
        s.bytes += c.buf.byteLength;
        s.frames += c.frames;
        s.lastSeq = c.seq;
      }
    } finally {
      s.pumping = false;
    }
  }

  function onChunk(name, msg) {
    const s = st[name];
    if (!s.accepting) return;             // после остановки — мимо
    if (!msg || msg.type !== 'chunk' || !msg.buf) return;

    if (msg.peak > s.peak) s.peak = msg.peak;
    s.rms = msg.rms;

    // Потолок очереди: молча копить нельзя — это память и испорченная запись.
    if (s.queue.length >= maxQueue) {
      s.dropped++;
      s.lostFrames += msg.frames;
      fail(name, 'мост не успевает принимать запись — дорожка «' + name
        + '» теряет звук (в очереди ' + s.queue.length + ' чанков)');
      return;
    }
    s.queue.push({ seq: msg.seq, frames: msg.frames, buf: msg.buf });
    if (s.queue.length > s.maxQueued) s.maxQueued = s.queue.length;
    // насос живёт сам по себе; неожиданный срыв внутри него обязан стать
    // видимой ошибкой, а не потерянным промисом
    pump(name).catch((e) => fail(name, 'насос записи сорвался: ' + errText(e)));
  }

  function errText(e) {
    return (e && (e.message || e.name)) || String(e);
  }

  // Повесить отводы на точки съёма. Узел — тупик (numberOfOutputs 0), поэтому
  // физически не может оказаться в слышимом тракте: колонки от записи не зависят.
  function wire(ctx, NodeCtor, taps) {
    for (const t of TRACKS) {
      st[t.name] = fresh(t.channels);
      const node = new NodeCtor(ctx, 'rec-tap', {
        numberOfInputs: 1,
        numberOfOutputs: 0,
        // explicit: сколько каналов объявили, столько и придёт, каким бы ни был
        // источник. Иначе число каналов в файле менялось бы вместе с лупом.
        channelCount: t.channels,
        channelCountMode: 'explicit',
        channelInterpretation: 'speakers',
        processorOptions: { label: t.name, channels: t.channels },
      });
      node.port.onmessage = (e) => onChunk(t.name, e.data);
      // отвод ПРЕ-ФЕЙДЕРНЫЙ: taps.track/taps.mic стоят до ползунков громкости
      taps[t.tap].connect(node);
      nodes[t.name] = node;
      st[t.name].accepting = true;
    }
  }

  function detach(taps) {
    for (const t of TRACKS) {
      const node = nodes[t.name];
      if (!node) continue;
      node.port.onmessage = null;
      st[t.name].accepting = false;
      if (taps) { try { taps[t.tap].disconnect(node); } catch (e) { /* уже снят */ } }
      try { node.disconnect(); } catch (e) { /* у тупика выходов нет */ }
      nodes[t.name] = null;
    }
  }

  // Точки съёма для снятия отводов. Если граф уже снесён (dispose), их просто
  // нет — рвать нечего, и это не повод падать на остановке записи.
  function tapsOrNull() {
    try { return audio.getTaps(); } catch (e) { return null; }
  }

  async function drain(name) {
    const s = st[name];
    const until = Date.now() + DRAIN_MS;
    while ((s.queue.length || s.pumping) && Date.now() < until) {
      await new Promise((r) => setTimeout(r, 20));
    }
    if (s.queue.length) {
      let lost = 0;
      for (const c of s.queue) lost += c.frames;
      s.lostFrames += lost;
      s.dropped += s.queue.length;
      s.queue.length = 0;
      fail(name, 'мост не отдал остаток записи за ' + (DRAIN_MS / 1000)
        + ' с — хвост дорожки «' + name + '» потерян');
    }
  }

  return {
    /**
     * Поднять отводы и начать слать чанки в мост. Идемпотентно.
     * @returns {Promise<{sampleRate:number, tracks:object}>}
     */
    async start() {
      if (running) return this.info();
      if (!bridge || typeof bridge.rec_chunk !== 'function') {
        throw new Error('мост записи недоступен: нет метода rec_chunk');
      }
      const ctx = audio.start();
      if (!ctx) throw new Error('аудио не запустилось — записывать нечего');
      sampleRate = ctx.sampleRate;

      const NodeCtor = o.WorkletNode
        || (typeof AudioWorkletNode !== 'undefined' ? AudioWorkletNode : null);
      if (!NodeCtor) throw new Error('браузер не поддерживает AudioWorklet');

      if (!moduleAdded) {
        if (!ctx.audioWorklet || typeof ctx.audioWorklet.addModule !== 'function') {
          throw new Error('браузер не поддерживает AudioWorklet');
        }
        try {
          await ctx.audioWorklet.addModule(o.workletUrl || defaultWorkletUrl());
        } catch (e) {
          throw new Error('не загрузился модуль записи: ' + errText(e));
        }
        moduleAdded = true;                // addModule повторно звать незачем
      }

      const taps = audio.getTaps();
      try {
        wire(ctx, NodeCtor, taps);
      } catch (e) {
        // наполовину поднятая запись хуже отсутствующей: снимаем всё, что
        // успели повесить, и падаем честным текстом
        detach(taps);                      // после detach повторный start() чист
        throw new Error('не поднялись отводы записи: ' + errText(e));
      }
      running = true;
      return this.info();
    },

    /**
     * Остановить отводы, дождавшись хвоста: воркл ет отдаёт недобранный чанк по
     * команде flush, насос его дожимает. Без этого терялись бы последние
     * полсекунды каждой дорожки.
     * @returns {Promise<object>} итоговая статистика
     */
    async stop() {
      if (!running) return this.stats();
      running = false;

      for (const t of TRACKS) {
        const node = nodes[t.name];
        if (!node) continue;
        try { node.port.postMessage({ cmd: 'flush' }); } catch (e) { /* уже мёртв */ }
      }
      // хвостовому чанку нужно доехать из рендер-потока — дать ему такт
      await new Promise((r) => setTimeout(r, 60));
      for (const t of TRACKS) st[t.name].accepting = false;
      await Promise.all(TRACKS.map((t) => drain(t.name)));

      detach(tapsOrNull());
      return this.stats();
    },

    // Что нужно Python, чтобы открыть писателей WAV.
    info() {
      const tracks = {};
      for (const t of TRACKS) tracks[t.name] = { channels: t.channels };
      return { sampleRate, tracks };
    },

    /**
     * Честная сводка: сколько ушло, был ли сигнал, что сломалось.
     * peak/rms — в единицах int16; peak === 0 значит «в файле тишина», сколько
     * бы чанков ни доехало (в спайке именно так и выглядела уничтоженная
     * конвертацией запись — все счётчики зелёные, файл пустой).
     */
    stats() {
      const tracks = {};
      let errors = 0;
      let error = null;
      for (const t of TRACKS) {
        const s = st[t.name];
        tracks[t.name] = {
          channels: s.channels,
          chunks: s.chunks,
          bytes: s.bytes,
          frames: s.frames,
          seconds: sampleRate ? +(s.frames / sampleRate).toFixed(2) : 0,
          peak: s.peak,
          rms: s.rms,
          silent: s.chunks > 0 && s.peak === 0,
          queued: s.queue.length,
          maxQueued: s.maxQueued,
          dropped: s.dropped,
          lostFrames: s.lostFrames,
          lastSeq: s.lastSeq,
          errors: s.errors,
          error: s.error,
        };
        errors += s.errors;
        if (!error && s.error) error = s.error;
      }
      return { running, sampleRate, errors, error, tracks };
    },
  };
}

export default createAudioRec;
