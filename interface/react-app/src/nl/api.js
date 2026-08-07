// Тонкий клиент /api: JSON, таймаут 30 секунд (генерация — 180: холодная
// сборка строгой таблицы на пуле 2.87М строк живёт ~45–70 секунд, обрывать
// её 30-секундным абортом — значит никогда не увидеть первый прогон после
// старта сервера; тёплые повторы укладываются в полсекунды), ошибки —
// честный throw с русским текстом из {error} сервера или из HTTP-статуса.
// Формы тел — из api/server.py и контракта /api/sheets (PLAN.md, фаза 0).

const TIMEOUT_MS = 30000;
const GEN_TIMEOUT_MS = 180000;
// прогон пайплайна — пулы на каждый профиль звена (6–8 внутренних вызовов
// генерации, каждый может быть «холодным») плюс перебор до 200000 сочетаний:
// потолок генерации ему мал, поэтому свой
const PIPE_TIMEOUT_MS = 300000;

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
    throw new Error((data && data.error) || ('ошибка сервера: HTTP ' + res.status));
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
// {available, sources, pool_total, pool_available, retention}
export const nlState = () => get('/api/nl/state');
export const stats = () => get('/api/stats');
// {items:[{text,template,tags,shown_at,restored_at,expired}], stats}
export const history = (q) => get('/api/history' + (q ? '?q=' + encodeURIComponent(q) : ''));
// {items:[{text,template}], theme?} — вызывается в момент реального показа
export const markShown = (payload) => post('/api/history/mark_shown', payload);
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
// Раунд 50: только каркас. Крутилки — своя полка (knobProfileSave ниже).
export const stanzaProfileSave = (name, lines) => post('/api/stanza/profiles', { name, lines });
export const stanzaProfileDelete = (name) => post('/api/stanza/profiles/delete', { name });

// ---- полка профилей настроек (Раунд 50) -----------------------------------
// Вторая полка: положения крутилок отдельно от каркаса строфы. Форма ответа
// та же, что у строф — {builtin, custom}: две полки не должны требовать двух
// разных привычек.
export const knobProfiles = () => get('/api/knobs/profiles');
export const knobProfileSave = (name, mode, params) => post('/api/knobs/profiles', { name, mode, params });
export const knobProfileDelete = (name) => post('/api/knobs/profiles/delete', { name });

// ---- полка цепочек: СЛЕПКИ (Раунд 50) -------------------------------------
// Цепочка хранит копии каркасов и крутилок, а не имена: правка полки не
// меняет уже сохранённое решение. Референс — часть слепка, включая пустой.
export const chains = () => get('/api/chains');
export const chainSave = (payload) => post('/api/chains', payload);
export const chainDelete = (name) => post('/api/chains/delete', { name });
// Полка СЕРИЙ — четвёртый уровень (Раунд 53): серия = список звеньев
// {альбом, тема, цепочка с полки, сколько}. `run` только ЗАПУСКАЕТ: прогон
// идёт фоновым потоком сервера, ход виден в /api/status, как у сборки рифм.
export const series = () => get('/api/series');
export const seriesSave = (payload) => post('/api/series', payload);
export const seriesDelete = (name) => post('/api/series/delete', { name });
export const seriesRun = (name) => post('/api/series/run', { name });
export const seriesStop = () => post('/api/series/stop', {});
// прогон пайплайна (фаза 1): {theme, chain, junctions, knobs, runs, best,
// threshold} → {variants, funnel}; 409 = прогон уже идёт (замок на бэке)
export const pipelineRun = (payload) => post('/api/pipeline/run', payload, PIPE_TIMEOUT_MS);
// референс → профиль и готовая цепочка (Раунд 45): ничего не генерирует,
// только меряет текст и отдаёт то, чем его можно повторить
export const pipelineProfile = (text, ref) => post('/api/pipeline/profile', { text: text, ref: ref });
// Настоящее положение дел по серии (Раунд 55): сколько СДЕЛАНО на каждом
// треке, какой идёт сейчас и где что встало. Читается из файлов, поэтому не
// требует помнить ни одного прогона.
export const seriesState = (name) => get('/api/series/state?name=' + encodeURIComponent(name));
// попап по слову (фаза 2): {word, tab, line} → {items: [{w, n, t}]}; t — тип
// рифмы (богатая/точная/усечённая/неточная) или пусто; n — готовая
// подпись справа (частота/«рифма»/«словарь»/«близкое» — решает бэк, фронт не
// гадает); line — текст текущей строки ('' допустимо): контекст вкладки
// «строкой» и рифмо-контекст остальных
export const wordSuggest = (word, tab, line) => post('/api/word/suggest', { word, tab, line });
// {items} — фоновые задачи для индикатора в шапке
export const status = () => get('/api/status');

// ---- корпус nakedlunch: источники и сборка --------------------------------
// Заливка книг — ЕДИНСТВЕННЫЙ роут не на JSON: бэк читает request.files
// ('/api/nl/source/add'), поэтому тут FormData и свой fetch, а не post().
// Таймаут больше генерации: книга на несколько мегабайт режется на фрагменты
// синхронно в запросе.
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
  return data;   // {added:[{name,fragment_count}], errors:[{name,error}], sources}
}
export const sourceToggle = (id) => post('/api/nl/source/toggle', { id });
export const sourceRemove = (id) => post('/api/nl/source/remove', { id });
// полный пересчёт ударений и рифмо-ключей по всему корпусу; идёт в фоне,
// прогресс виден в индикаторе шапки (/api/status)
export const rhymeRun = () => post('/api/nl/rhyme/run', {});
// пересчёт только формулы качества — минуты вместо часа, ударения не трогает
export const rhymeReban = () => post('/api/nl/rhyme/reban', {});
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
export const historyRestoreTheme = (theme) => post('/api/history/restore_theme', { theme });
// «показанное» самого nakedlunch (его собственный учёт, не наша история)
export const nlRetentionGet = () => get('/api/nl/retention');
export const nlRetentionSet = (value) => post('/api/nl/retention', { value });
export const nlClearUsed = (mode) => post('/api/nl/clear-used', { mode });

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

// ---- листы: контракт /api/sheets (фаза 0) ---------------------------------
// id листа = путь относительно vault ('Папка/Название.md'); id папки = имя каталога

export const sheetsList = () => get('/api/sheets');                              // {sheets, folders}
export const sheetsRead = (id) => post('/api/sheets/read', { id });              // {id,title,rows}
export const sheetsWrite = (id, rows) => post('/api/sheets/write', { id, rows }); // {ok,at}
export const sheetsCreate = (opts) => post('/api/sheets/create', opts || {});    // {title?,folder?} → {id,title}
export const sheetsRename = (id, title) => post('/api/sheets/rename', { id, title }); // id может смениться
export const sheetsDuplicate = (id) => post('/api/sheets/duplicate', { id });
export const sheetsTrash = (id) => post('/api/sheets/trash', { id });
export const sheetsRestore = (id) => post('/api/sheets/restore', { id });
export const sheetsPurge = (id) => post('/api/sheets/purge', { id });
export const sheetsPurgeAll = () => post('/api/sheets/purge-all', {});
export const sheetsMove = (id, folder) => post('/api/sheets/move', { id, folder }); // folder=''=корень
export const sheetsFolderCreate = (name) => post('/api/sheets/folder/create', { name });
export const sheetsFolderDelete = (id) => post('/api/sheets/folder/delete', { id });
export const sheetsOpenDir = () => post('/api/sheets/open-dir', {});

// ОТЧЁТ О СЕССИИ (Раунд 59) — один текст со средой, состоянием артефактов и
// журналом. Собирается сервером: считать состояние на фронте значило бы завести
// второй источник правды о том, что лежит на диске.
export const журнал = () => get('/api/%D0%B6%D1%83%D1%80%D0%BD%D0%B0%D0%BB');

// Сохранить отчёт файлом на рабочий стол и показать его в проводнике.
export const журналФайл = () => post('/api/%D0%B6%D1%83%D1%80%D0%BD%D0%B0%D0%BB/%D1%84%D0%B0%D0%B9%D0%BB', {});
