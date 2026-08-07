// РЕЖИМ ЗАПИСИ — фаза 4. Миксин на прототип Nakedlunch (как остальные methods.*).
//
// РЕШЕНИЕ (2026-08-01): захват окна плюс режим записи, продуманный, но без
// усложнений. Отсюда всё устройство модуля:
//
//   1) ЖЁСТКАЯ БЛОКИРОВКА ХРОМА. Старт вешает data-reclock="1" на корень
//      документа, и правило style.js гасит хром намертво: ни hover, ни
//      focus-visible, ни клики. Случайно вывести интерфейс в кадр нельзя —
//      это главное, ради чего режим существует. Панели закрываются при старте,
//      фокус снимается (иначе поле съело бы пробел-хоткей).
//   2) УПРАВЛЕНИЕ — ХОТКЕИ. Кнопка записи заперта вместе с остальным хромом,
//      поэтому стоп живёт на Esc/R, а «следующая строка» — на пробеле: шоу
//      гонится не открывая панелей.
//   3) ИНДИКАТОР ЖИВЁТ ПО ПРАВИЛУ ХРОМА: виден только при движении мыши,
//      через 1.5 с покоя гаснет. Руки убраны — кадр чистый; дёрнул мышь —
//      увидел время, размер и пики.
//   4) СБОЙ — ГРОМКО И В КАДР. Красная плашка не прячется ничем. Испорченную
//      запись лучше увидеть сразу, чем найти вечером в тишине.
//
// ПОЧЕМУ ИНДИКАТОР И ПЛАШКА — ЖИВОЙ DOM, А НЕ JSX. Они обязаны стоять ПОВЕРХ
// сцены и НЕ быть частью хрома (который мы запираем), а разметка сцены и шапки
// живёт в чужих файлах фазы 3. Свой слой на body — единственный способ не
// раздваивать источник правды по хрому и ничего не ломать в render.*.
//
// ПОЧЕМУ FLASH ПЕРЕХВАТЫВАЕТСЯ. Тост flash() рисуется поверх всего (z-index 95)
// и не помечен data-chrome — во время записи любое «генератор не вернул строк»
// влезло бы прямо в кадр. На время записи flash уводится в индикатор, то есть
// подчиняется тому же правилу: руки убраны — кадр чистый.
//
// ГРАНИЦА С ПИТОНОМ (мост pywebview, window.pywebview.api; launch.py:ExportApi):
//   rec_start(track, params)  → {ok, track, path, dir}   — завести дорожку
//   rec_chunk(track, seq, b64)→ {ok, bytes, total, peak} — кусок по порядку
//   rec_status()              → {ok, active, dir, tracks:{…}} — здоровье
//   rec_stop(track)           → {ok, path, bytes, seconds, peak} — закрыть
//   rec_mux()                 → {ok, path, …}            — склейка ffmpeg
// track: 'video' | 'mic' | 'loop' — это же имена файлов в каталоге записи.
// params у видео: {kind:'blob', ext} (ext — из ФАКТИЧЕСКОГО rec.mimeType),
// у звука: {kind:'wav', channels, rate}.
//
// ОТВЕТ {ok:false} — ЭТО НЕ ИСКЛЮЧЕНИЕ. Питон почти никогда не бросает через
// мост: он отвечает объектом. Поэтому каждый вызов проверяется по полю ok, а
// не по тому, что промис не отклонился — иначе сбой выглядел бы как успех.
//
// Нет моста (обычная вкладка браузера) — честный отказ, а не тихая пустая
// запись: кнопка записи заперта и подписана «запись только в приложении».

import { createVideoRec } from './freestyle/rec-video.js';
import { createAudioRec } from './freestyle/rec-audio.js';

// сколько индикатор живёт после последнего движения мыши
const HUD_IDLE_MS = 1500;
// частота перерисовки индикатора (время/размер) и опроса здоровья дорожек
const HUD_TICK_MS = 250;
const POLL_MS = 1000;
// дорожка молчит дольше этого — сбой (мост принял кусок последний раз давно)
const STALE_MS = 3000;
// пик ноль дольше этого при ожидаемом сигнале — сбой. ПОЧЕМУ ВООБЩЕ ПИК:
// в спайке Float32 (-1..1) записали прямо в Int16Array, всё усеклось в ноль,
// файл вышел чистой тишиной — а счётчики кадров были зелёные и дропов ноль.
// «Поле пришло» ничего не значит; значит только сигнал в файле.
const SILENT_MS = 5000;

const Z = 900;   // выше всего живого хрома (шапка 45, панели 80, флеш 95)

function msgOf(e) {
  if (!e) return 'неизвестная ошибка';
  if (typeof e === 'string') return e;
  return e.message || e.name || String(e);
}

function fmtBytes(n) {
  const v = Number(n) || 0;
  if (v >= 1048576) return (v / 1048576).toFixed(1) + ' МБ';
  if (v >= 1024) return Math.round(v / 1024) + ' КБ';
  return v + ' Б';
}

function fmtTime(ms) {
  const s = Math.max(0, Math.round((Number(ms) || 0) / 1000));
  const m = Math.floor(s / 60);
  return (m < 10 ? '0' : '') + m + ':' + (s % 60 < 10 ? '0' : '') + (s % 60);
}

// короткое имя дорожки для индикатора
const RU = { video: 'видео', mic: 'мик', loop: 'луп' };

// Слой поверх сцены. cssText переписываем только при изменении: индикатор
// перерисовывается 4 раза в секунду поверх живого визуализатора, и лишний
// пересчёт стилей тут не нужен никому.
function box(id, css) {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement('div');
    el.id = id;
    document.body.appendChild(el);
  }
  if (el._nlCss !== css) { el.style.cssText = css; el._nlCss = css; }
  return el;
}

export const fsRecMethods = {
  // ---- мост -------------------------------------------------------------
  // Записывать можно только внутри окна приложения: файлы пишет питон. В
  // обычной вкладке браузера window.pywebview нет вовсе — это НЕ ошибка и не
  // повод падать: кнопка записи заперта и честно подписана (render.fspanels).
  // Проверяем оба обязательных метода: мост без rec_start открыл бы поток
  // кусков, которым некуда лечь.
  recBridge() {
    const api = typeof window !== 'undefined' && window.pywebview && window.pywebview.api;
    if (!api) return null;
    return (typeof api.rec_chunk === 'function' && typeof api.rec_start === 'function') ? api : null;
  },

  // Подпись для запертой кнопки — одна строка правды на весь интерфейс.
  recWhyNot() {
    return this.recBridge() ? '' : 'запись только в приложении';
  },

  // ---- аудио-дорожки -------------------------------------------------------
  // Хук, которого ждёт recStart: две НЕЗАПУЩЕННЫЕ дорожки поверх пре-фейдерных
  // отводов (freestyle/rec-audio.js). Отдельный модуль отводов знает только про
  // rec_chunk — файлы за него открывает и закрывает эта склейка, потому что
  // жизненный цикл файла общий на все три дорожки.
  //
  // ПОЧЕМУ ДВЕ ДОРОЖКИ, А ВНУТРИ ОДИН ОБЪЕКТ. Отводы висят на одном
  // AudioContext и снимаются одним flush: делить их на два независимых
  // жизненных цикла — значит уметь остановить микрофон, не остановив луп, чего
  // ни интерфейс, ни пользователь не просят. Поэтому наружу два лица с общим
  // мотором: первое поднявшееся лицо поднимает мотор, первое остановленное —
  // глушит, остальные ждут тот же промис.
  //
  // ПОРЯДОК ЖЁСТКИЙ: сначала оба файла в питоне, потом отводы. Наоборот —
  // первые полсекунды звука приедут в неоткрытую дорожку и станут дыркой в
  // самом начале записи.
  async recAudioTracks(bridge) {
    const self = this;
    const audio = this.fsAudioStart();
    if (!audio) throw new Error('аудио-граф не поднялся — писать звук нечем');
    let ctx;
    try { ctx = audio.start(); } catch (e) { throw new Error('аудио-граф не поднялся: ' + msgOf(e)); }
    const rate = (ctx && ctx.sampleRate) || 0;
    if (!rate) throw new Error('частота дискретизации неизвестна — заголовок WAV писать нечем');

    const faces = {};                        // имя дорожки → её лицо наружу
    const opened = [];                       // что уже открыто в питоне
    let booted = null;
    let stopped = null;

    const rec = createAudioRec(audio, bridge, {
      // беда с дорожки уходит её же лицу — recStart вешает туда обработчик,
      // который красит плашку. Лица ещё нет (сбой до старта) — кричим напрямую
      onError(name, msg) {
        const f = faces[name];
        if (f && typeof f.onerror === 'function') f.onerror(new Error(msg));
        else self.recFail((RU[name] || name) + ': ' + msg);
      },
    });
    const meta = rec.info().tracks;          // {loop:{channels:2}, mic:{channels:1}}
    const names = Object.keys(meta);

    // Поднять мотор. Наполовину поднятая запись хуже отсутствующей, поэтому
    // при сбое закрываем всё, что успели открыть: иначе питон останется с
    // незакрытой дорожкой и следующая попытка упрётся в «дорожка уже пишется».
    function boot() {
      if (booted) return booted;
      booted = (async function () {
        try {
          for (let i = 0; i < names.length; i++) {
            const n = names[i];
            const r = await bridge.rec_start(n, {
              kind: 'wav', channels: meta[n].channels, rate: rate,
            });
            if (!r || r.ok === false) {
              throw new Error((r && r.error) || ('питон не открыл дорожку ' + n));
            }
            opened.push(n);
            faces[n].path = r.path || '';
          }
          const got = await rec.start();
          // Заголовок WAV уже написан с rate: если движок отдал другую частоту,
          // файл будет играть не с той скоростью, а по счётчикам всё зелено
          if (got && got.sampleRate && got.sampleRate !== rate) {
            throw new Error('частота дискретизации сменилась на ходу ('
              + rate + ' → ' + got.sampleRate + ') — заголовок WAV соврал бы');
          }
        } catch (e) {
          for (let i = 0; i < opened.length; i++) {
            try { await bridge.rec_stop(opened[i]); } catch (e2) { /* уже закрыта */ }
          }
          opened.length = 0;
          throw e;
        }
      })();
      return booted;
    }

    function stopMotor() {
      if (!stopped) stopped = rec.stop();
      return stopped;
    }

    names.forEach(function (n) {
      faces[n] = {
        name: n,
        path: '',
        onerror: null,
        async start() { await boot(); },
        async stop() {
          if (!booted) return { name: n, path: '', bytes: 0, ms: 0 };
          try { await stopMotor(); } catch (e) { /* беда уже ушла в onError */ }
          const s = (rec.stats().tracks || {})[n] || {};
          let r = null;
          try {
            r = await bridge.rec_stop(n);
          } catch (e) {
            return { name: n, path: faces[n].path, bytes: 0, error: msgOf(e) };
          }
          const out = {
            name: n,
            path: (r && r.path) || faces[n].path,
            bytes: (r && r.bytes) || 0,
            seconds: r && r.seconds,
            peak: r && r.peak,
            ms: Math.round((s.seconds || 0) * 1000),
          };
          // ok:false — файл дописан и переименован, но по дорожке был сбой
          if (r && r.ok === false) out.error = r.error || 'дорожка закрыта со сбоем';
          else if (s.error) out.error = s.error;
          return out;
        },
        stats() {
          const s = (rec.stats().tracks || {})[n] || {};
          return {
            bytes: s.bytes || 0,
            chunks: s.chunks || 0,
            // пик отдаём в 0…1, как ждёт индикатор и как считает питон:
            // внутри отвода он в единицах int16 (0…32767)
            peak: s.peak != null ? s.peak / 32768 : null,
            silent: !!s.silent,
            dropped: s.dropped || 0,
            queue: s.queued || 0,
            error: s.error || null,
          };
        },
      };
    });

    return names.map(function (n) { return faces[n]; });
  },

  // Кнопка записи в шапке (btnRecord) зовёт только это.
  recToggle() {
    if (this._recBusy) return;
    if (this._recLive) this.recStop();
    else this.recStart();
  },

  // ---- старт -------------------------------------------------------------
  // ПОЧЕМУ ВНУТРИ ВСЁ СМОТРИТ НА _recLive, А НЕ НА state.recOn: setState в
  // React применяется не мгновенно, а индикатор, хоткеи и опрос обязаны быть
  // живыми ровно с той секунды, когда пошли кадры. state.recOn остаётся
  // публичным полем — его читает кнопка записи и любой рендер.
  async recStart() {
    if (this._recLive || this._recBusy) return;
    const bridge = this.recBridge();
    if (!bridge) {
      this.flash('запись только в приложении: моста в питон нет');
      return;
    }
    this._recBusy = true;
    this._recBridge = bridge;
    this._recErr = '';
    this._recNote = '';
    this._recZero = {};
    this._recStatus = {};

    // Итог прошлой записи убираем: новая запись заводит в питоне НОВЫЙ каталог,
    // и кнопка «склеить» на старой плашке склеила бы уже не то, что на ней
    // написано (rec_mux работает с последней сессией — она одна знает, что в
    // ней лежит целым).
    const old = document.getElementById('nlRecDone');
    if (old && old.parentNode) old.parentNode.removeChild(old);

    // Хром запираем ДО первой дорожки: если старт упадёт, замок снимет catch,
    // а вот открытая панель, попавшая в первые кадры, уже не отменяется.
    this.recLockOn();

    const tracks = [];
    try {
      const video = createVideoRec(bridge);
      await video.start();
      tracks.push(video);

      // Аудио-отводы: recAudioTracks выше в этом же миксине. Хук отдаёт
      // дорожки НЕЗАПУЩЕННЫМИ — поднимаем их здесь, чтобы откат при сбое был
      // один на все три. Проверка на наличие хука осталась не для красоты:
      // без неё сборка без аудио-модуля падала бы вместо того, чтобы писать
      // видео и громко сказать «1 из 3».
      if (typeof this.recAudioTracks === 'function') {
        const got = this.recNormalizeTracks(await this.recAudioTracks(bridge));
        for (let i = 0; i < got.length; i++) {
          if (typeof got[i].start === 'function') await got[i].start();
          tracks.push(got[i]);
        }
      }
    } catch (e) {
      // откат: всё, что успело подняться, честно останавливаем
      for (let i = 0; i < tracks.length; i++) {
        try { await tracks[i].stop(); } catch (e2) { /* уже мёртв */ }
      }
      this.recLockOff();
      this._recBusy = false;
      this.flash(msgOf(e));
      return;
    }

    const self = this;
    tracks.forEach(function (t) {
      t.onerror = function (err) { self.recFail((RU[t.name] || t.name) + ': ' + msgOf(err)); };
    });
    this._recTracks = tracks;
    this._recLive = true;
    this._recAt = Date.now();
    this._recHudAt = Date.now();

    if (tracks.length < 3) {
      this.recFail('поднялось дорожек: ' + tracks.length + ' из 3 — аудио-отводы не подключены');
    }
    // без rec_status здоровье дорожек проверяет только сам MediaRecorder, а
    // «в файле тишина» так не поймать — молчать об этом нельзя
    if (typeof bridge.rec_status !== 'function') {
      this.recFail('мост не умеет rec_status — состояние дорожек не проверяется');
    }

    // Тост уводим в индикатор: иначе он влезет в кадр (см. шапку файла).
    if (!this._recFlashSave) {
      this._recFlashSave = this.flash;
      this.flash = function (msg) { self._recNote = String(msg || ''); self._recNoteAt = Date.now(); };
    }

    this.recBindKeys();
    this._recTick = setInterval(function () { self.recPaint(); }, HUD_TICK_MS);
    this._recPoll = setInterval(function () { self.recPoll(); }, POLL_MS);
    this.recPaint();

    this._recBusy = false;
    this.setState({ recOn: true, recLock: true });
  },

  // Соседний модуль вправе отдать массив дорожек, пару {mic, loop} или одну
  // дорожку — принимаем всё, лишь бы у объекта были start/stop/stats.
  recNormalizeTracks(got) {
    if (!got) return [];
    let list;
    if (Array.isArray(got)) list = got;
    else if (typeof got.start === 'function') list = [got];
    else list = [got.mic, got.loop].filter(Boolean);
    return list.filter(function (t) { return t && typeof t.stop === 'function'; });
  },

  // ---- стоп --------------------------------------------------------------
  async recStop() {
    if (!this._recLive || this._recBusy) return;
    this._recBusy = true;
    this._recLive = false;

    this.recUnbindKeys();
    clearInterval(this._recTick); this._recTick = null;
    clearInterval(this._recPoll); this._recPoll = null;

    const tracks = this._recTracks || [];
    this._recTracks = null;
    const results = [];
    for (let i = 0; i < tracks.length; i++) {
      try {
        const r = await tracks[i].stop();
        if (r) results.push(r);
      } catch (e) {
        results.push({ name: tracks[i].name, error: msgOf(e) });
      }
    }

    // тост возвращаем ДО итога: итог сам себе плашка, а дальше приложение
    // снова разговаривает нормально
    if (this._recFlashSave) { this.flash = this._recFlashSave; this._recFlashSave = null; }

    const ms = this._recAt ? Date.now() - this._recAt : 0;
    this.recLockOff();
    this.recHudHide();
    this._recBusy = false;
    this.setState({ recOn: false, recLock: false }, () => this.recShowDone(results, ms));
  },

  // ---- замок хрома -------------------------------------------------------
  // Атрибут на корне документа, а не на своём корне приложения: так правило
  // накрывает весь хром гарантированно, где бы он ни был смонтирован.
  recLockOn() {
    if (typeof document === 'undefined') return;
    document.documentElement.setAttribute('data-reclock', '1');
    this.closePop();
    // фокус в поле съел бы пробел-хоткей и оставил бы каретку в кадре
    try {
      const a = document.activeElement;
      if (a && a !== document.body && typeof a.blur === 'function') a.blur();
    } catch (e) { /* нечего снимать */ }
  },
  recLockOff() {
    if (typeof document === 'undefined') return;
    document.documentElement.removeAttribute('data-reclock');
  },

  // ---- хоткеи ------------------------------------------------------------
  // Слушатель ставится ТОЛЬКО на время записи и снимается при стопе. Фаза
  // перехвата + stopPropagation: до onGlobalKey наши клавиши не доходят, и
  // Escape не начинает закрывать попапы вместо остановки записи.
  recBindKeys() {
    if (this._recKeys) return;
    const self = this;
    this._recKeys = function (e) { self.recKey(e); };
    this._recMove = function () { self._recHudAt = Date.now(); };
    window.addEventListener('keydown', this._recKeys, true);
    window.addEventListener('mousemove', this._recMove, true);
    window.addEventListener('pointermove', this._recMove, true);
  },
  recUnbindKeys() {
    if (this._recKeys) window.removeEventListener('keydown', this._recKeys, true);
    if (this._recMove) {
      window.removeEventListener('mousemove', this._recMove, true);
      window.removeEventListener('pointermove', this._recMove, true);
    }
    this._recKeys = null;
    this._recMove = null;
  },
  recKey(e) {
    if (!this._recLive) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;   // системные сочетания не наши
    // e.code, а не e.key: на русской раскладке физическая R даёт «к»
    const stop = e.key === 'Escape' || e.code === 'Escape' || e.code === 'KeyR';
    const next = e.code === 'Space';
    if (!stop && !next) return;
    // страховка: если фокус всё-таки в поле, пробел — это ввод текста
    const t = e.target;
    const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable);
    if (next && typing) return;
    e.preventDefault();
    e.stopPropagation();
    if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();
    if (stop) { this.recStop(); return; }
    this._recHudAt = Date.now();   // жест руками — индикатор проявляется, как хром
    if (this.fsAdvance) this.fsAdvance();
  },

  // ---- здоровье дорожек --------------------------------------------------
  // Питон — главный свидетель: он один знает, что реально дошло до файла.
  // Клиентские счётчики только дополняют его (мост мог не ответить вовсе).
  async recPoll() {
    if (!this._recLive) return;
    const bridge = this._recBridge;
    if (!bridge || typeof bridge.rec_status !== 'function') return;
    let st;
    try {
      st = await bridge.rec_status();
    } catch (e) {
      this.recFail('питон не отвечает о состоянии записи: ' + msgOf(e));
      return;
    }
    if (!st) return;
    if (st.error) { this.recFail('питон: ' + st.error); return; }
    this._recStatus = st.tracks || {};
    const now = Date.now();
    const tracks = this._recTracks || [];
    for (let i = 0; i < tracks.length; i++) {
      const name = tracks[i].name;
      const info = this._recStatus[name];
      if (!info) { this.recFail((RU[name] || name) + ': питон не знает такой дорожки'); continue; }
      if (info.error) { this.recFail((RU[name] || name) + ': ' + info.error); continue; }
      const ago = Number(info.last_write_ago);
      if (isFinite(ago) && ago * 1000 > STALE_MS) {
        this.recFail((RU[name] || name) + ': ничего не записано ' + ago.toFixed(1) + ' с');
        continue;
      }
      // тишина при ожидаемом сигнале — тот самый случай «все счётчики зелёные,
      // а в файле ноль». Ожидание сигнала берём из состояния сцены
      const expect = (name === 'mic' && this.state.micOn) || (name === 'loop' && this.state.trackOn);
      if (!expect) { this._recZero[name] = 0; continue; }
      const peak = Number(info.peak);
      if (isFinite(peak) && peak > 0) { this._recZero[name] = 0; continue; }
      if (!this._recZero[name]) this._recZero[name] = now;
      else if (now - this._recZero[name] > SILENT_MS) {
        this.recFail((RU[name] || name) + ': в файле тишина, хотя источник включён');
      }
    }
  },

  // Сбой не гасит запись: остаток дорожек может быть цел, а решать пользователю.
  // Плашка не прячется до самого стопа — она обязана попасть в кадр.
  recFail(text) {
    const t = String(text || 'сбой записи');
    if (this._recErr && this._recErr.indexOf(t) >= 0) return;   // не размножаем одно и то же
    this._recErr = this._recErr ? (this._recErr + '\n' + t) : t;
    console.error('запись:', t);
    this.recPaint();
  },

  // ---- индикатор и плашка ------------------------------------------------
  recPaint() {
    if (typeof document === 'undefined') return;
    const on = this._recLive;
    const err = this._recErr;

    // красная плашка: пока есть ошибка — висит, ничем не скрывается
    if (err) {
      const bad = box('nlRecFail',
        'position: fixed; left: 50%; top: 22px; transform: translateX(-50%); z-index: ' + (Z + 2) + ';'
        + ' max-width: 78vw; pointer-events: none; background: #c81e28; color: #fff;'
        + ' border-radius: 4px; padding: 10px 16px; font-family: ui-monospace, monospace; font-size: 12px;'
        + ' line-height: 1.5; letter-spacing: 0.02em; white-space: pre-wrap; text-align: center;'
        + ' box-shadow: 0 10px 30px -12px rgba(0,0,0,0.6);');
      bad.textContent = 'СБОЙ ЗАПИСИ\n' + err;
    } else {
      const bad = document.getElementById('nlRecFail');
      if (bad && bad.parentNode) bad.parentNode.removeChild(bad);
    }

    if (!on) return;

    // индикатор — по правилу хрома: только под движением мыши
    const idle = Date.now() - (this._recHudAt || 0) > HUD_IDLE_MS;
    const hud = box('nlRecHud',
      'position: fixed; right: 18px; top: 16px; z-index: ' + (Z + 1) + '; pointer-events: none;'
      + ' display: ' + (idle ? 'none' : 'block') + '; background: rgba(10,10,10,0.72);'
      + ' color: #f2f2f2; border-radius: 4px; padding: 7px 11px;'
      + ' font-family: ui-monospace, monospace; font-size: 10.5px; line-height: 1.6;'
      + ' letter-spacing: 0.03em; white-space: pre; text-align: right;');
    if (idle) return;
    hud.textContent = this.recHudText();
  },

  recHudText() {
    const parts = [];
    parts.push('● ЗАПИСЬ  ' + fmtTime(Date.now() - (this._recAt || Date.now())));
    const tracks = this._recTracks || [];
    for (let i = 0; i < tracks.length; i++) {
      const t = tracks[i];
      let st = {};
      try { st = t.stats() || {}; } catch (e) { st = {}; }
      const py = (this._recStatus || {})[t.name] || {};
      const bytes = py.bytes != null ? py.bytes : st.bytes;
      const line = [RU[t.name] || t.name, fmtBytes(bytes)];
      const peak = py.peak != null ? py.peak : st.peak;
      if (peak != null) line.push('пик ' + Number(peak).toFixed(3));
      if (st.mimeType) line.push(st.mimeType.split(';')[0].split('/')[1] || '');
      if (st.width) line.push(st.width + '×' + st.height);
      parts.push(line.filter(Boolean).join(' · '));
    }
    // тост, перехваченный на время записи, показываем тут же ~3 секунды
    if (this._recNote && Date.now() - (this._recNoteAt || 0) < 3000) parts.push(this._recNote);
    parts.push('Esc / R — стоп · пробел — строка');
    return parts.join('\n');
  },

  recHudHide() {
    const hud = document.getElementById('nlRecHud');
    if (hud && hud.parentNode) hud.parentNode.removeChild(hud);
  },

  // ---- итог и склейка ----------------------------------------------------
  // Склейка НЕ автомат (решение пользователя): исходники не трогаем, кнопка
  // появляется только если мост реально отдаёт rec_mux.
  recShowDone(results, ms) {
    const self = this;
    const bridge = this._recBridge;
    const done = box('nlRecDone',
      'position: fixed; left: 50%; top: 50%; transform: translate(-50%, -50%); z-index: ' + (Z + 3) + ';'
      + ' max-width: min(720px, 86vw); background: rgba(12,12,12,0.92); color: #f2f2f2;'
      + ' border-radius: 5px; padding: 18px 22px; font-family: ui-monospace, monospace;'
      + ' font-size: 11px; line-height: 1.7; box-shadow: 0 20px 50px -20px rgba(0,0,0,0.8);');
    done.textContent = '';

    const head = document.createElement('div');
    head.style.cssText = 'font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 10px;';
    head.textContent = 'запись остановлена · ' + fmtTime(ms);
    done.appendChild(head);

    const paths = {};
    (results || []).forEach(function (r) {
      if (r && r.path) paths[r.name] = r.path;
      const row = document.createElement('div');
      row.style.cssText = 'white-space: pre-wrap; word-break: break-all; color: ' + (r && r.error ? '#ff8a8a' : '#f2f2f2') + ';';
      row.textContent = r
        ? ((RU[r.name] || r.name) + ' · ' + (r.error ? r.error : (fmtBytes(r.bytes) + ' · ' + (r.path || 'путь неизвестен'))))
        : '';
      done.appendChild(row);
    });
    // Дверь в папку, а не адрес (Раунд 56). Путь под каждой дорожкой был и
    // раньше, но запрос «должна быть папка сохранения» — то есть
    // строкой она ему не заменяется. Тот же роут-образец, что у корпуса и
    // листов: /api/rec/open-dir.
    const открыть = document.createElement('button');
    открыть.type = 'button';
    открыть.style.cssText = 'margin-top: 10px; font: inherit; font-size: 11px; color: inherit; background: none; border: 1px solid currentColor; border-radius: 999px; padding: 5px 12px; cursor: pointer; opacity: 0.75;';
    открыть.textContent = 'открыть папку записей';
    открыть.addEventListener('click', function () {
      fetch('/api/rec/open-dir', { method: 'POST' }).catch(function () {});
    });
    done.appendChild(открыть);
    if (this._recErr) {
      const bad = document.createElement('div');
      bad.style.cssText = 'margin-top: 8px; color: #ff8a8a; white-space: pre-wrap;';
      bad.textContent = 'во время записи: ' + this._recErr;
      done.appendChild(bad);
    }

    const bar = document.createElement('div');
    bar.style.cssText = 'display: flex; gap: 8px; margin-top: 14px;';
    const mkBtn = function (label) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.style.cssText = 'appearance: none; border: none; border-radius: 3px; padding: 7px 14px;'
        + ' font-family: inherit; font-size: 11px; cursor: pointer; background: #f2f2f2; color: #101010;';
      return b;
    };
    if (bridge && typeof bridge.rec_mux === 'function' && paths.video) {
      const mux = mkBtn('склеить');
      mux.onclick = function () { self.recMux(mux); };
      bar.appendChild(mux);
    }
    const close = mkBtn('закрыть');
    close.style.background = 'transparent';
    close.style.color = '#f2f2f2';
    close.style.boxShadow = 'inset 0 0 0 1px rgba(242,242,242,0.35)';
    close.onclick = function () {
      if (done.parentNode) done.parentNode.removeChild(done);
      self._recErr = '';
      self.recPaint();
    };
    bar.appendChild(close);
    done.appendChild(bar);
  },

  // Склейка. Аргументов НЕТ: питон склеивает свой последний каталог записи —
  // он его и завёл, он один знает, что в нём лежит целым, а что оборвано
  // (.partial). Пути с фронта были бы вторым источником правды.
  async recMux(btn) {
    const bridge = this._recBridge;
    if (!bridge || typeof bridge.rec_mux !== 'function') return;
    if (btn) { btn.disabled = true; btn.textContent = 'склеиваю…'; }
    const say = function (text, bad) {
      const row = document.createElement('div');
      row.style.cssText = 'margin-top: 10px; word-break: break-all; white-space: pre-wrap;'
        + (bad ? ' color: #ff8a8a;' : '');
      row.textContent = text;
      if (btn && btn.parentNode && btn.parentNode.parentNode) btn.parentNode.parentNode.appendChild(row);
    };
    try {
      // WebM от MediaRecorder — VFR и без длительности в заголовке
      // (ffprobe duration = N/A), поэтому питон обязан перекодировать: -c copy
      // здесь даёт битый файл. Это забота бэкенда, но повод помнить.
      const res = await bridge.rec_mux();
      // отказ приезжает объектом {ok:false, error} — исключения тут не бывает
      if (!res || res.ok === false) {
        if (btn) { btn.disabled = false; btn.textContent = 'склеить'; }
        say('склейка не вышла: ' + ((res && (res.error || res.reason)) || 'питон промолчал'), true);
        return;
      }
      if (btn) { btn.textContent = 'готово'; }
      if (res.path) say('склеено: ' + res.path);
    } catch (e) {
      if (btn) { btn.disabled = false; btn.textContent = 'склеить'; }
      say('склейка не вышла: ' + msgOf(e), true);
    }
  },

  // ---- снос --------------------------------------------------------------
  // Размонтирование посреди записи: дорожки останавливаем, файлы закрываем,
  // замок снимаем. Ждать асинхронный стоп здесь некому — но начатый rec_stop
  // питон доведёт сам, а .partial в любом случае открывается модулем wave
  // (7 из 7 SIGKILL в спайке).
  recUnmount() {
    this._recLive = false;
    this.recUnbindKeys();
    clearInterval(this._recTick); this._recTick = null;
    clearInterval(this._recPoll); this._recPoll = null;
    if (this._recFlashSave) { this.flash = this._recFlashSave; this._recFlashSave = null; }
    const tracks = this._recTracks || [];
    this._recTracks = null;
    tracks.forEach(function (t) { try { t.stop(); } catch (e) { /* уже мёртв */ } });
    this.recLockOff();
    this.recHudHide();
    ['nlRecFail', 'nlRecDone'].forEach(function (id) {
      const el = document.getElementById(id);
      if (el && el.parentNode) el.parentNode.removeChild(el);
    });
  },
};

export default fsRecMethods;
