// Видео-дорожка записи: захват ОКНА приложения → MediaRecorder → мост в Python.
//
// ПОЧЕМУ ЗАХВАТ ОКНА, А НЕ КОМПОЗИТНЫЙ КАНВАС. Решение владельца (2026-08-01):
// сцену заново не перерисовываем — снимаем окно как есть, а чистоту кадра
// обеспечивает РЕЖИМ ЗАПИСИ (хром заперт наглухо, см. methods.fsrec.js).
// Композитный канвас потребовал бы второй копии всей сцены (bc → блум → плашка
// → скрим → зерно → варп) и второго источника правды на каждый слой.
//
// ЧТО ЗДЕСЬ ИЗМЕРЕНО СПАЙКОМ, А НЕ ПРИДУМАНО (эти числа не пересматривать):
//   1) getDisplayMedia в окне приложения РАБОТАЕТ и системного диалога НЕ
//      показывает: окно захватывает само себя, потому что делегат
//      requestMediaCapturePermissionForOrigin в launch.py отвечает grant.
//      Значит отказ getDisplayMedia = патч launch.py не сработал, и текст
//      ошибки обязан говорить именно это, а не «пользователь отменил».
//   2) MediaRecorder в WKWebView умеет video/webm;codecs=vp9, vp8 и
//      video/mp4;codecs=avc1. WebM переживает обрыв заметно лучше mp4
//      (декодируется 51% против 44% с ошибками NAL) — поэтому webm первым.
//   3) rec.mimeType МОЖЕТ НЕ СОВПАСТЬ с запрошенным (в спайке просили webm,
//      получили mp4). Поэтому расширение файла строится по ФАКТИЧЕСКОМУ
//      rec.mimeType, и узнаём мы его только после rec.start().
//   4) Мост pywebview заводит ПОТОК PYTHON НА КАЖДЫЙ ВЫЗОВ и порядок вызовов
//      НЕ гарантирует. Поэтому куски уходят по одному: следующий rec_chunk
//      начинается только после ответа на предыдущий, плюс каждый несёт свой
//      seq — питон обязан проверять его, а не верить порядку прихода.
//   5) base64 быстрее массива чисел в 16 раз (1.17мс против 18.5мс на 96 КБ),
//      потолок моста 78 МБ/с = 426x реалтайма. Поток видео в 8 Мбит/с — это
//      1 МБ/с, запас двухсоткратный, поэтому насос ничего не «оптимизирует».

// Порядок перебора: сначала переживающий обрыв webm, mp4 — последний шанс.
const MIMES = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/mp4;codecs=avc1'];

// Битрейт ~8 Мбит/с: полноэкранный визуализатор с зерном — тяжёлый материал,
// на меньшем битрейте зерно расползается в кашу блоков.
const BITRATE = 8000000;

// rec.start(1000): кусок раз в секунду. Меньше — чаще дёргаем мост без пользы,
// больше — крупнее потеря при обрыве (незакрытый хвост куска пропадает).
const SLICE_MS = 1000;

// Порция для String.fromCharCode.apply: на большем массиве движок роняет стек
// (RangeError: Maximum call stack size exceeded), причём на файле побольше —
// то есть ровно тогда, когда запись уже идёт.
const B64_STEP = 0x8000;

// Сколько ждём последний кусок после rec.stop(): движок отдаёт его событием, и
// без ожидания хвост записи просто не доедет до диска.
const STOP_WAIT_MS = 4000;
// Сколько ждём, пока насос допихает очередь в мост.
const DRAIN_MS = 15000;

function msgOf(e) {
  if (!e) return 'неизвестная ошибка';
  if (typeof e === 'string') return e;
  return e.message || e.name || String(e);
}

// ArrayBuffer → base64 без сборки промежуточных строк на каждый байт.
function toBase64(buf) {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += B64_STEP) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + B64_STEP));
  }
  return btoa(bin);
}

// Расширение по ФАКТИЧЕСКОМУ mime: 'video/webm;codecs=vp9' → 'webm'.
function extOf(mime) {
  const base = String(mime || '').split(';')[0].trim().toLowerCase();
  if (base === 'video/webm') return 'webm';
  if (base === 'video/mp4') return 'mp4';
  const slash = base.indexOf('/');
  return slash > 0 ? base.slice(slash + 1) : 'bin';
}

function pickMime() {
  if (typeof MediaRecorder === 'undefined') return null;
  for (let i = 0; i < MIMES.length; i++) {
    try { if (MediaRecorder.isTypeSupported(MIMES[i])) return MIMES[i]; } catch (e) { /* движок без isTypeSupported */ }
  }
  return '';   // пустая строка ≠ null: MediaRecorder есть, но ни один наш тип не признан
}

function sleep(ms) { return new Promise((res) => setTimeout(res, ms)); }

/**
 * Видео-дорожка режима записи.
 *
 * @param {object} bridge — window.pywebview.api; обязателен rec_chunk, нужны
 *        также rec_start и rec_stop (см. контракт в methods.fsrec.js).
 * @param {object} [opts]
 * @param {number} [opts.frameRate=30]
 * @param {number} [opts.bitrate=8000000]
 * @returns {{name:string, start:Function, stop:Function, stats:Function, onerror:Function|null}}
 */
export function createVideoRec(bridge, opts) {
  const o = opts || {};
  const kind = 'video';

  let stream = null;
  let rec = null;
  let mime = '';        // фактический тип от MediaRecorder
  let ext = '';
  let path = '';        // путь .partial-файла, как его назвал питон

  let seq = 0;          // позиция следующего куска в потоке; сжигается и при потере
  let chunks = 0;
  let bytes = 0;
  let width = 0, height = 0;

  const queue = [];
  let pumping = false;
  let opened = false;   // до ответа rec_start насос стоит: питон ещё не знает расширения
  let dead = false;
  let startedAt = 0;
  let lastAt = 0;       // когда мост последний раз принял кусок

  const api = {
    name: kind,
    onerror: null,
    start,
    stop,
    stats,
  };

  // Честный сбой наружу. Дорожку не глушим: испорченный кусок — не повод
  // терять остаток записи, а решение принимает владелец по красной плашке.
  function fail(msg) {
    const err = msg instanceof Error ? msg : new Error(msgOf(msg));
    if (typeof api.onerror === 'function') {
      try { api.onerror(err); } catch (e) { console.error('запись: обработчик ошибки упал', e); }
    }
  }

  // Насос: строго по одному вызову моста за раз. Параллелить нельзя — мост
  // раскладывает вызовы по разным потокам питона и порядок не держит.
  async function pump() {
    if (pumping || !opened) return;
    pumping = true;
    try {
      while (queue.length && !dead) {
        const blob = queue.shift();
        const size = blob.size;
        // Номер СЖИГАЕТСЯ в любом случае: seq — это позиция куска в потоке, а
        // не «сколько раз получилось». Переиспользовать номер потерянного
        // куска значит выдать питону непрерывную нумерацию поверх дырки —
        // файл выйдет короче, а состояние записи останется зелёным. Именно
        // так и выглядит худший сбой этой фазы. Питон разрыв ловит сам
        // (_SeqGate) и кричит; повторять один и тот же номер нельзя.
        const my = seq++;
        let b64;
        try {
          b64 = toBase64(await blob.arrayBuffer());
        } catch (e) {
          fail('кусок видео №' + my + ' не прочитался: ' + msgOf(e));
          continue;
        }
        try {
          const res = await bridge.rec_chunk(kind, my, b64);
          // питон отвечает объектом, а не исключением: ok:false — это дырка,
          // а не просьба повторить
          if (res && res.ok === false) {
            fail('питон не принял кусок видео №' + my + ': ' + (res.error || 'без объяснения'));
            continue;
          }
          chunks++;
          bytes += size;
          lastAt = Date.now();
        } catch (e) {
          fail('мост не принял кусок видео №' + my + ': ' + msgOf(e));
        }
      }
    } finally {
      pumping = false;
    }
  }

  async function drain() {
    const t0 = Date.now();
    while ((queue.length || pumping) && Date.now() - t0 < DRAIN_MS) await sleep(30);
    if (queue.length) fail('мост не принял ' + queue.length + ' кусков видео — хвост записи потерян');
  }

  function stopTracks() {
    if (!stream) return;
    try { stream.getTracks().forEach((t) => { try { t.stop(); } catch (e) {} }); } catch (e) {}
    stream = null;
  }

  async function start() {
    if (rec) throw new Error('видео-дорожка уже пишется');
    if (!bridge || typeof bridge.rec_chunk !== 'function') {
      throw new Error('моста записи нет: приложение запущено не в своём окне');
    }
    if (typeof bridge.rec_start !== 'function') {
      throw new Error('мост не умеет rec_start — видео некуда открыть');
    }
    const md = typeof navigator !== 'undefined' && navigator.mediaDevices;
    if (!md || typeof md.getDisplayMedia !== 'function') {
      throw new Error('этот движок не умеет захват окна (нет getDisplayMedia)');
    }

    try {
      // audio: false принципиально — звук пишется своими дорожками из
      // пре-фейдерных отводов, а не тем, что вылезло из колонок
      stream = await md.getDisplayMedia({
        video: { frameRate: o.frameRate || 30 },
        audio: false,
      });
    } catch (e) {
      // Диалога тут не бывает: окно захватывает само себя (проверено 2026-08-01).
      // Значит отказ — это отвалившийся grant в делегате, и говорим прямо
      throw new Error('окно не отдалось в захват (' + msgOf(e)
        + ') — проверь патч launch.py: без grant в requestMediaCapturePermissionForOrigin захвата не будет');
    }

    const vtrack = stream.getVideoTracks()[0];
    if (!vtrack) { stopTracks(); throw new Error('захват окна вернул поток без видео'); }
    try {
      const st = vtrack.getSettings ? vtrack.getSettings() : {};
      width = st.width || 0;
      height = st.height || 0;
    } catch (e) { /* размеры — диагностика, без них живём */ }
    // окно закрыли, свернули, поток отобрали — дорожка мертва, а запись идёт:
    // молчать нельзя, это ровно тот случай, ради которого красная плашка
    vtrack.onended = function () {
      if (!dead) fail('захват окна прерван — видео дальше не пишется');
    };

    const want = pickMime();
    if (want === null) { stopTracks(); throw new Error('в этом движке нет MediaRecorder — записывать нечем'); }
    if (want === '') { stopTracks(); throw new Error('движок не признал ни один видео-формат записи (webm/mp4)'); }

    const cfg = { mimeType: want, videoBitsPerSecond: o.bitrate || BITRATE };
    try {
      rec = new MediaRecorder(stream, cfg);
    } catch (e) {
      // тип признан isTypeSupported, но конструктор его не взял — пробуем без
      // указания типа: движок выберет свой, а мы прочитаем фактический
      try { rec = new MediaRecorder(stream, { videoBitsPerSecond: o.bitrate || BITRATE }); }
      catch (e2) { stopTracks(); throw new Error('MediaRecorder не собрался: ' + msgOf(e2)); }
    }

    rec.ondataavailable = function (ev) {
      if (dead || !ev.data || !ev.data.size) return;
      queue.push(ev.data);
      pump();
    };
    rec.onerror = function (ev) {
      fail('MediaRecorder: ' + msgOf(ev && (ev.error || ev)));
    };

    try {
      rec.start(SLICE_MS);
    } catch (e) {
      rec = null; stopTracks();
      throw new Error('запись видео не стартовала: ' + msgOf(e));
    }
    startedAt = Date.now();
    lastAt = startedAt;

    // фактический тип читаем ПОСЛЕ старта: до него движок вправе врать
    mime = rec.mimeType || want;
    ext = extOf(mime);

    try {
      // kind:'blob' — питон пишет поток как есть, заголовков не трогает.
      // ext идёт из ФАКТИЧЕСКОГО rec.mimeType (см. п.3 в шапке), поэтому
      // rec_start зовётся ПОСЛЕ rec.start(), а не до.
      const res = await bridge.rec_start(kind, {
        kind: 'blob', ext: ext, mime: mime, width: width, height: height,
      });
      if (!res || res.ok === false) {
        throw new Error((res && res.error) || 'питон не ответил на rec_start');
      }
      path = res.path || '';
    } catch (e) {
      try { rec.stop(); } catch (e2) {}
      rec = null; stopTracks();
      throw new Error('питон не открыл файл видео: ' + msgOf(e));
    }
    opened = true;
    pump();   // куски, накопившиеся пока открывался файл
    return { path: path, mime: mime, ext: ext, width: width, height: height };
  }

  async function stop() {
    if (!rec) return null;
    const r = rec;
    rec = null;

    // последний кусок приходит событием после stop() — без ожидания он теряется
    const ended = new Promise((res) => {
      r.onstop = function () { res(true); };
    });
    try { if (r.state !== 'inactive') r.stop(); } catch (e) { fail('остановка видео: ' + msgOf(e)); }
    await Promise.race([ended, sleep(STOP_WAIT_MS)]);
    stopTracks();
    await drain();
    dead = true;

    let res = null;
    if (typeof bridge.rec_stop === 'function') {
      try {
        res = await bridge.rec_stop(kind);
        // ok:false на остановке означает, что дорожка дописана и переименована,
        // но по ней БЫЛ сбой — файл есть, а доверять ему нельзя. Молчать об
        // этом на итоговой плашке нельзя
        if (res && res.ok === false) fail('видео закрыто со сбоем: ' + (res.error || 'без объяснения'));
      } catch (e) { fail('питон не закрыл файл видео: ' + msgOf(e)); }
    }
    return {
      name: kind,
      path: (res && res.path) || path,
      bytes: (res && res.bytes != null) ? res.bytes : bytes,
      chunks: chunks,
      mimeType: mime,
      ext: ext,
      ms: startedAt ? Date.now() - startedAt : 0,
    };
  }

  function stats() {
    return {
      name: kind,
      chunks: chunks,
      bytes: bytes,
      mimeType: mime,
      width: width,
      height: height,
      queue: queue.length,
      lastAt: lastAt,
      path: path,
      ms: startedAt ? Date.now() - startedAt : 0,
    };
  }

  return api;
}

export default createVideoRec;
