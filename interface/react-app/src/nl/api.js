// Тонкий клиент /api: JSON, таймаут 30 секунд (генерация — 180: холодная
// сборка строгой таблицы на пуле 2.87М строк живёт ~45–70 секунд, обрывать
// её 30-секундным абортом — значит никогда не увидеть первый прогон после
// старта сервера; тёплые повторы укладываются в полсекунды), ошибки —
// честный throw с русским текстом из {error} сервера или из HTTP-статуса.
// Формы тел — из api/server.py и контракта /api/sheets (PLAN.md, фаза 0).

const TIMEOUT_MS = 30000;
const GEN_TIMEOUT_MS = 180000;
// PIPE_TIMEOUT_MS вырезан 2026-08-18 вместе с прогоном цепи: свой потолок в
// 300 секунд нужен был только ему.

async function req(url, opts, timeoutMs) {
  const ms = timeoutMs || TIMEOUT_MS;
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), ms);
  let res;
  try {
    res = await fetch(url, { ...opts, signal: ac.signal });
  } catch (e) {
    throw new Error(e && e.name === 'AbortError'
      ? 'сервер не ответил за ' + Math.round(ms / 1000) + ' секунд'
      : 'нет связи с сервером');
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* не-JSON — ниже честная ошибка по статусу */ }
  if (!res.ok || (data && data.error)) {
    // СЕРВЕР ОТВЕТИЛ — ЗНАЧИТ ОН ЖИВ (2026-09-02). Здесь throw был безымянным,
    // и вызывающий не мог отличить «ядро умерло» от «ядро живо, но в коде
    // ошибка». Из-за этого пятисотая с точной причиной на диске доходила до
    // человека как «закрой и открой заново» — совет, который ничего не чинит.
    var err = new Error((data && data.error) || ('ошибка сервера: HTTP ' + res.status));
    err.живой = true;
    err.статус = res.status;
    throw err;
  }
  return data;
}

export function get(url) { return req(url); }

export function post(url, body, timeoutMs) {
  return req(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body == null ? {} : body),
  }, timeoutMs);
}

// ---- генерация и состояние ------------------------------------------------

// payload как в api_generate: {theme?, bias?, rhyme?|stanza?, knobs?, source?}
export const generate = (payload) => post('/api/generate', payload, GEN_TIMEOUT_MS);
// {corpus, accepted} — accepted это список строк избранного, новые сверху
export const state = () => get('/api/state');
// {available, sources, pool_total, pool_available} — поле retention убрано
// 2026-08-18 вместе с роутами /api/nl/retention: экрана у срока хранения
// «показанного» самого nakedlunch не было никогда, и форма ответа обещала
// значение, которого больше нет
export const nlState = () => get('/api/nl/state');
export const stats = () => get('/api/stats');
// {items:[{text,template,tags,shown_at,restored_at,expired}], stats}
export const history = (q) => get('/api/history' + (q ? '?q=' + encodeURIComponent(q) : ''));
// {items:[{text,template}], theme?} — вызывается в момент реального показа
export const markShown = (payload) => post('/api/history/mark_shown', payload);
// Форма пула — из чего сейчас будет выбираться (Раунд 62). Дёшево по замеру:
// 2.3–9.7 мс на полном индексе, то есть укладывается в движение ползунка,
// в отличие от самого прогона (185 мс без темы, 878 с темой).
export const poolShape = (payload) => post('/api/pool/shape', payload);
// {text, lemmas?, rhyme?, template?} — леммы эхом из выдачи /api/generate
export const favAdd = (payload) => post('/api/favorite', payload);
export const favRemove = (text) => post('/api/favorite/remove', { text });
export const settingsGet = () => get('/api/settings');
// патч как в api_settings_post: {knobs?, stanza?, stanza_profile?}
export const settingsSet = (patch) => post('/api/settings', patch);
// {builtin, custom} — формы строф
export const stanzaProfiles = () => get('/api/stanza/profiles');
// params — положения крутилок в координатах интерфейса, сохраняются вместе
// со схемой (профиль = рифмовка + чем она набиралась)
// Раунд 50: только каркас. Крутилки жили на своей полке — см. надгробие ниже.
export const stanzaProfileSave = (name, lines) => post('/api/stanza/profiles', { name, lines });
export const stanzaProfileDelete = (name) => post('/api/stanza/profiles/delete', { name });

// ПОЛКА ПРОФИЛЕЙ НАСТРОЕК ВЫРЕЗАНА С ФРОНТА 2026-08-18. Здесь стояли три
// обёртки: knobProfiles (GET /api/knobs/profiles), knobProfileSave,
// knobProfileDelete. Полку заменили четыре пресета, зашитые в
// methods.shelves.js: ПРЕСЕТЫ — своих профилей у пользователя не было ни
// одного (`data/knob_profiles.json` = `[]`, не менялся с 2026-08-03), а
// встроенных было два, и оба стали пресетами.
//
// РОУТЫ НА БЭКЕ ЖИВЫ и не тронуты (api/server.py, core/knob_profiles.py): их
// просто больше никто не спрашивает. Это осознанный долг — снести их должен
// тот, кто работает в бэке, а не эта правка.

// ЦЕПЬ И СЕРИЯ ВЫРЕЗАНЫ 2026-08-18. Здесь стояли двенадцать обёрток:
// chains/chainSave/chainDelete (полка цепочек), series/seriesSave/seriesDelete/
// seriesRun/seriesStop/seriesState (полка серий и её прогон),
// pipelineRun/pipelineStop/pipelineProfile (прогон цепи и замер референса).
//
// ПОЧЕМУ. Замер журнала за десять живых дней: 29 прогонов цепи против 587
// одиночных строф, медиана цепи 24.2 с. Решено: «pipeline и
// серия это бесполезные режимы на самом деле… их можно вырезать. Строфа
// единственным режимом и всё».
// ПОПАП СЛОВА ВЫРЕЗАН, ОБЁРТКА ОСТАВЛЕНА НАРОЧНО (2026-08-18).
//
// Единственным вызывающим был methods.слово.js — клик по слову в ленте
// открывал рифмы, синонимы и антонимы и ничего ими не делал (строки ленты не
// редактируются, заменять нечего). Требование: «попап с кликом по тексту не
// нужен». Файл удалён целиком; фристайл этот роут не звал никогда — проверено
// grep'ом по всему src.
//
// Роут /api/word/suggest и core/wordsuggest.py вырезаны на бэке — вместе с
// обёрткой `wordSuggest`, которая жила здесь как последний след их
// контракта. Разбор — в надгробии api/server.py.
// {items} — фоновые задачи для индикатора в шапке
export const status = () => get('/api/status');

// ---- корпус nakedlunch: источники и сборка --------------------------------
// Заливка книг — ЕДИНСТВЕННЫЙ роут не на JSON: бэк читает request.files
// ('/api/nl/source/add'), поэтому тут FormData и свой fetch, а не post().
//
// Роут отвечает СРАЗУ: он читает байты (поток запроса закроется раньше, чем
// работник до них доберётся) и отдаёт `{queued, sources}`, а разбор, чистка и
// нарезка идут в фоновом потоке. Ход виден через /api/status, пункт «Книга».
// Таймаут тут — только на саму передачу файла, не на обработку.
export async function sourceAdd(files) {
  const form = new FormData();
  for (const f of files) form.append('files', f);
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 600000);
  let res;
  try {
    res = await fetch('/api/nl/source/add', { method: 'POST', body: form, signal: ac.signal });
  } catch (e) {
    throw new Error(e && e.name === 'AbortError' ? 'книга не обработалась за 10 минут' : 'нет связи с сервером');
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* ниже честная ошибка по статусу */ }
  if (!res.ok || (data && data.error)) throw new Error((data && data.error) || ('ошибка сервера: HTTP ' + res.status));
  return data;   // {queued:[имена], sources} — итог заливки приходит через /api/status
}
export const sourceToggle = (id) => post('/api/nl/source/toggle', { id });
export const sourceRemove = (id) => post('/api/nl/source/remove', { id });
// полный пересчёт ударений и рифмо-ключей по всему корпусу; идёт в фоне,
// прогресс виден в индикаторе шапки (/api/status)
export const rhymeRun = () => post('/api/nl/rhyme/run', {});
// пересчёт только формулы качества — минуты вместо часа, ударения не трогает
// Чистка склада: `сухой: true` — только посчитать, ничего не менять.
export const corpusClean = (сухой) => post('/api/nl/clean', { сухой: !!сухой });
// карта воронки: сколько фрагментов и книг доживает до каждой ступени отсева
// чёрный список слов и словосочетаний со счётчиком «сколько строк убирает»
export const blacklistList = () => get('/api/nl/blacklist');
export const blacklistAdd = (rule) => post('/api/nl/blacklist/add', { rule });
export const blacklistRemove = (rule) => post('/api/nl/blacklist/remove', { rule });
export const nlFunnel = (q) => get('/api/nl/funnel' + (q || ''));
export const nlOpenDir = () => post('/api/nl/open-dir', {});

// ---- история, пул и сроки хранения ----------------------------------------
export const historyRetentionGet = () => get('/api/history/retention');
export const historyRetentionSet = (days) => post('/api/history/retention', { days });
export const historyClear = () => post('/api/history/clear', {});
export const historyRestore = (texts) => post('/api/history/restore', { texts });
// НАДГРОБИЕ 2026-08-29: `historyRestoreTheme` — роут снят вместе с темой.
// «показанное» самого nakedlunch (его собственный учёт, не наша история):
// обёртки nlRetentionGet/nlRetentionSet/nlClearUsed убраны в Раунде 63 вместе с
// их единственными вызывающими — экрана у этих ручек не было никогда. Сами
// ручки на бэке (/api/nl/retention, /api/nl/clear-used) остались нетронутыми.

// ---- выгрузка данных -------------------------------------------------------
// Сырой текст, не JSON: это файлы на диск, а не ответы для разбора.
export async function fetchText(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error('ошибка сервера: HTTP ' + res.status);
  return res.text();
}

/**
 * Сохранить текст файлом. В окне приложения — НАСТОЯЩИЙ системный диалог
 * «Сохранить как» через мост pywebview: ссылка <a download> внутри WKWebView
 * уводит на файл ВСЁ окно, и вернуться в программу нечем (найдено 2026-07-14).
 * В обычной вкладке браузера моста нет — там честная Blob-ссылка.
 * @returns {Promise<string>} путь или '' при отмене
 */
export async function saveFile(filename, content, mime) {
  const bridge = typeof window !== 'undefined' && window.pywebview && window.pywebview.api;
  if (bridge && bridge.save_file) {
    const res = await bridge.save_file(filename, content);
    if (res && res.ok) return res.path || filename;
    if (res && res.cancelled) return '';
    throw new Error((res && res.error) || 'не удалось сохранить файл');
  }
  const url = URL.createObjectURL(new Blob([content], { type: mime || 'text/plain' }));
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}

// ---------------------------------------------------------------------------
// ЗДЕСЬ БЫЛ КЛИЕНТ ЛИСТОВ — /api/sheets (вырезано 2026-08-18, 14 функций):
// sheetsList / Read / Write / Create / Rename / Duplicate / Trash / Restore /
// Purge / PurgeAll / Move / FolderCreate / FolderDelete / OpenDir.
// Листы и папки жили под редактором документа; редактор вырезан целиком, и
// звать эти роуты стало некому. Держать обёртки без вызывающих значило бы
// оставить второй, немой контракт с бэком.
// ---------------------------------------------------------------------------

// ОТЧЁТ О СЕССИИ (Раунд 59) — один текст со средой, состоянием артефактов и
// журналом. Собирается сервером: считать состояние на фронте значило бы завести
// второй источник правды о том, что лежит на диске.
export const журнал = () => get('/api/%D0%B6%D1%83%D1%80%D0%BD%D0%B0%D0%BB');

// Сохранить отчёт файлом на рабочий стол и показать его в проводнике.
export const журналФайл = () => post('/api/%D0%B6%D1%83%D1%80%D0%BD%D0%B0%D0%BB/%D1%84%D0%B0%D0%B9%D0%BB', {});
