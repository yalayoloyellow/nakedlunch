// Избранное, история и статистика — три содержательные панели шапки.
//
// ПОЧЕМУ ОНИ ПЕРЕПИСАНЫ (Раунд 40). Требование: у истории и избранного должен быть полноценный набор действий — удалять,
// добавлять, изменять.. Так и было: при переносе интерфейса от избранного остались
// «вставить» и «минус», от истории — только «вставить», а поиск, копирование,
// правка, выгрузка и возврат в пул потерялись вместе со старым App.jsx.
//
// «ВСТАВИТЬ В ДОКУМЕНТ» УБРАНО 2026-08-18. Сама строка была кнопкой, и клик по
// ней клал текст в лист. Листа нет — вставлять некуда, а кнопка, которая ничего
// не делает, хуже её отсутствия: она обещает. Строка стала строкой; копирование
// (⧉) и звезда на месте — через них текст и забирают.
//
// И два решения решение о том, ГДЕ чему жить: настройка истории уезжает в саму историю.:
//     срок хранения и очистка живут в самой истории, а не в настройках;
//   • «статистика в настройках находиться не должна, она должна находиться в
//     этой кнопочке статистика, и всё там должно быть красиво подведено…
//     показывать только обработанную, полезную информацию, а не мусорную»:
//     отдельная кнопка, сводка вместо свалки, выгрузка данных там же — она
//     выгружает статистику, значит ей и место.

import { Fragment } from 'react';
import { s, hov } from './style.js';
import { СРОКИ_ИСТОРИИ } from './methods.corpus.js';

const ПАНЕЛЬ = 'position: absolute; top: calc(100% + 12px); right: 0; z-index: 80; background: var(--menu-bg); backdrop-filter: var(--glass-fx); -webkit-backdrop-filter: var(--glass-fx-fallback); contain: paint; isolation: isolate; box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: 12px 14px;';
const ЗАГОЛОВОК = 'font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--muted-soft);';
const ССЫЛКА = 'appearance: none; background: none; border: none; padding: 0; font-family: inherit; font-size: 9.5px; color: var(--muted); cursor: pointer; white-space: nowrap;';
const ПОИСК = 'flex: 1; min-width: 0; appearance: none; background: none; border: none; border-bottom: 1px solid var(--border-subtle); padding: 4px 2px; font-family: inherit; font-size: 10px; color: var(--ink);';
const ЧИСЛО = 'font-variant-numeric: tabular-nums; color: var(--ink);';

function фмт(n) {
  return String(Math.round(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

// ============================================================
// Избранное: поиск, вставка, копирование, правка, удаление с отменой,
// добавление своей строки, копирование всего и выгрузка
// ============================================================

export function renderFavPanel(c) {
  var st = c.state;
  var q = (st.favQ || '').trim().toLowerCase();
  var все = (st.favs || []).map(function (f) { return typeof f === 'string' ? { t: f } : f; });
  var строки = q ? все.filter(function (f) { return String(f.t || '').toLowerCase().indexOf(q) >= 0; }) : все;

  return (
    <div data-pa="down" data-po={st.closing === 'fav' ? '1' : null} style={s(ПАНЕЛЬ + ' width: 340px;')}>
      <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px;')}>
        <span style={s(ЗАГОЛОВОК)}>избранное · {все.length}</span>
        {st.favUndo ? (
          <button onClick={function () { c.undoFav(); }} style={s(ССЫЛКА + ' color: var(--ink);')}>вернуть удалённое</button>
        ) : null}
      </div>

      <div style={s('display: flex; align-items: center; gap: 8px; margin-bottom: 8px;')}>
        <input type="text" value={st.favQ || ''} placeholder="поиск" spellCheck={false}
          onChange={function (e) { c.setState({ favQ: e.target.value }); }} style={s(ПОИСК)} />
        {/* ЗДЕСЬ БЫЛА КНОПКА ＋ (убрана 2026-08-18). Она звала addFavManual,
            а тот брал «строку под курсором ленты». Курсора по строкам не стало
            вместе с выделением — владелец: «там сейчас можно бессмысленно
            выделить строку одну, и с этим ни хуя не делается». Кнопка осталась
            бы контролом, который на любое нажатие отвечает «встань на строку»,
            то есть просит невозможного. Строка кладётся звездой слева от неё. */}
      </div>

      <div className="nl-list">
        {строки.map(function (f, i) {
          var правим = st.favEdit === f.t;
          return (
            <div key={i} className="nl-row">
              <span className="nl-when"></span>
              {правим ? (
                <input className="nl-edit" defaultValue={f.t} autoFocus spellCheck={false}
                  onKeyDown={function (e) {
                    if (e.key === 'Enter') { e.preventDefault(); c.editFav(f.t, e.target.value); }
                    if (e.key === 'Escape') c.setState({ favEdit: '' });
                  }}
                  onBlur={function (e) { c.editFav(f.t, e.target.value); }} />
              ) : (
                <span className="nl-name" style={{ cursor: 'default' }} title={f.t}>{f.t}</span>
              )}
              <span className="nl-acts">
                <button title="Скопировать" onClick={function () { c.copyText(f.t); }}>⧉</button>
                <button title="Изменить" onClick={function () { c.setState({ favEdit: правим ? '' : f.t }); }}>✎</button>
                <button title="Убрать из избранного" onClick={function () { c.dropFav(f.t); }}>−</button>
              </span>
            </div>
          );
        })}
        {строки.length ? null : (<div style={s('font-size: 9px; color: var(--muted-soft); padding: 6px 5px;')}>{все.length ? 'ничего не нашлось' : 'пусто — звезда слева от строки'}</div>)}
      </div>

      <div style={s('display: flex; align-items: center; gap: 12px; border-top: 1px solid var(--border-subtle); margin-top: 9px; padding-top: 9px;')}>
        <button onClick={function () { c.copyText(все.map(function (f) { return f.t; }).join('\n')); }} style={s(ССЫЛКА)} className={hov('color: var(--ink)')}>копировать всё</button>
        <button onClick={function () { c.exportFavs('txt'); }} style={s(ССЫЛКА)} className={hov('color: var(--ink)')}>txt</button>
        <button onClick={function () { c.exportFavs('md'); }} style={s(ССЫЛКА)} className={hov('color: var(--ink)')}>md</button>
      </div>
    </div>
  );
}

// ============================================================
// История: поиск, вставка, копирование, возврат в пул (поштучно и по теме),
// очистка и СРОК ХРАНЕНИЯ — здесь же, а не в настройках
// ============================================================

export function renderHistPanel(c) {
  var st = c.state;
  var q = (st.histQ || '').trim().toLowerCase();
  var все = st.hist || [];
  var строки = (q ? все.filter(function (h) { return String(h.t || '').toLowerCase().indexOf(q) >= 0; }) : все).slice(0, 300);

  return (
    <div data-pa="down" data-po={st.closing === 'hist' ? '1' : null} style={s(ПАНЕЛЬ + ' width: 360px;')}>
      <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px;')}>
        <span style={s(ЗАГОЛОВОК)}>история · {фмт(все.length)}</span>
        <button onClick={function () { c.setState({ histCfg: !st.histCfg }); }} style={s(ССЫЛКА)} className={hov('color: var(--ink)')}>
          {st.histCfg ? 'скрыть настройки' : 'настройки'}
        </button>
      </div>

      {/* Настройки истории живут в истории (решение пользователя): здесь видно,
          чем именно они управляют, а в общих настройках это была строка без
          контекста рядом с настройками шрифта. */}
      {st.histCfg && (
        <div style={s('background: color-mix(in srgb, var(--ink) 4%, transparent); border-radius: var(--radius); padding: 8px 10px; margin-bottom: 9px;')}>
          <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 10px; color: var(--muted-hard);')}>
            <span>хранить</span>
            <div style={s('display: flex; gap: 3px; flex-wrap: wrap;')}>
              {СРОКИ_ИСТОРИИ.map(function (o, i) {
                var on = o.v === st.histRetention;
                return (<button key={i} onClick={function () { c.setHistRetention(o.v); }}
                  style={s('appearance: none; border: none; border-radius: 3px; padding: 4px 7px; font-family: inherit; font-size: 9px; cursor: pointer; white-space: nowrap; '
                    + (on ? 'background: var(--ink); color: var(--canvas);' : 'background: color-mix(in srgb, var(--ink) 7%, transparent); color: var(--muted);'))}>{o.name}</button>);
              })}
            </div>
          </div>
          <div style={s('font-size: 8.5px; line-height: 1.45; color: var(--muted-soft); margin-top: 7px; text-wrap: pretty;')}>
            показанное скрыто из пула, пока не истечёт срок или пока не вернёшь вручную · история одна на редактор и фристайл
          </div>
        </div>
      )}

      <div style={s('display: flex; align-items: center; gap: 8px; margin-bottom: 8px;')}>
        <input type="text" value={st.histQ || ''} placeholder="поиск" spellCheck={false}
          onChange={function (e) { c.setState({ histQ: e.target.value }); }} style={s(ПОИСК)} />
      </div>

      <div className="nl-list">
        {строки.map(function (h, i) {
          return (
            <div key={i} className="nl-row">
              <span className="nl-when" title={h.full || ''}>{h.time}</span>
              <span className="nl-name" style={{ cursor: 'default' }} title={h.t}>{h.t}</span>
              <span className="nl-acts">
                <button title="Скопировать" onClick={function () { c.copyText(h.t); }}>⧉</button>
                <button title="В избранное" onClick={function () { c.addFavText(h.t); }}>★</button>
                <button title="Вернуть в пул — строка снова сможет выпасть" onClick={function () { c.restoreOne(h.t); }}>↺</button>
              </span>
            </div>
          );
        })}
        {строки.length ? null : (<div style={s('font-size: 9px; color: var(--muted-soft); padding: 6px 5px;')}>{все.length ? 'ничего не нашлось' : 'пусто'}</div>)}
      </div>

      <div style={s('display: flex; align-items: center; gap: 8px; border-top: 1px solid var(--border-subtle); margin-top: 9px; padding-top: 9px;')}>
        {/* НАДГРОБИЕ 2026-08-29: здесь было поле «вернуть в пул по теме» и
            кнопка к нему. Тема вырезана целиком по слову владельца, и
            отбирать показанное по ней стало нечем. Поштучное «вернуть»
            из строки истории — живо, оно ниже. */}
        {st.confirm === 'hist' ? (
          <Fragment>
            <button onClick={function () { c.clearHistory(); }} style={s(ССЫЛКА + ' color: var(--ink);')}>очистить всё</button>
            <button onClick={function () { c.setState({ confirm: '' }); }} style={s(ССЫЛКА)}>нет</button>
          </Fragment>
        ) : (
          <button onClick={function () { c.setState({ confirm: 'hist' }); }} title="Избранное не пострадает" style={s(ССЫЛКА)} className={hov('color: var(--ink)')}>очистить</button>
        )}
      </div>
    </div>
  );
}

// ============================================================
// Статистика: сводка, а не свалка
// ============================================================

// Одна строка сводки: подпись слева, число справа.
// Имя книги — для глаз, не для машины (2026-08-28). Имена источников — это
// имена файлов: «Pelevin_Nepobedimoe-solnce.CJ_RYw.591928», и владелец про
// такой список сказал «некрасивое». Хвост-хэш со счётчиком отрезается,
// подчёркивания становятся пробелами; само имя в данных НЕ трогается — это
// подпись на экране, полное живёт в подсказке.
function имяКниги(s) {
  var t = String(s || '');
  t = t.replace(/[._]\d{3,8}$/, '');                       // счётчик-хвост
  t = t.replace(/[._]([A-Za-z0-9_-]{4,8})$/, function (m, х) {
    return /[0-9]/.test(х) || /[A-Z]/.test(х.slice(1)) ? '' : m;  // хэш, не слово
  });
  return t.replace(/_+/g, ' ').trim();
}


function ряд(k, v, i) {
  return (
    <div key={i} style={s('display: flex; align-items: baseline; justify-content: space-between; gap: 10px; font-size: 10px; color: var(--muted); padding: 2px 0;')}>
      <span style={s('min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;')}>{k}</span>
      <span style={s(ЧИСЛО)}>{v}</span>
    </div>
  );
}

function блок(имя, ряды, key) {
  return (
    <div key={key} style={s('margin-bottom: 12px;')}>
      <div style={s(ЗАГОЛОВОК + ' margin-bottom: 5px;')}>{имя}</div>
      {ряды.map(function (r, i) { return ряд(r[0], r[1], i); })}
    </div>
  );
}

export function renderStatsPanel(c) {
  var st = c.state;
  var d = st.statsData || {};
  var работы = c.jobRows ? c.jobRows() : [];
  var s0 = d.stats || {};
  var g = s0.generate || {}, f = s0.favorites || {}, sh = s0.shown || {}, nl = st.nl || {};

  // КАРТА ВОРОНКИ (Раунд 57). Сколько фрагментов и книг доживает до каждой
  // ступени отсева — чтобы цена каждой ручки была видна числом, а не на словах.
  var ворон = st.funnel && st.funnel.ready ? st.funnel : null;
  var воронка = ворон ? (
    <div style={s('margin-bottom: 18px;')}>
      <div style={s('font-size: 9px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted-soft); margin-bottom: 6px;')}>
        воронка отбора · {ворон.всего.toLocaleString('ru')} строк, {ворон.книг_всего} книг</div>
      {ворон.ступени.map(function (ш, i) {
        return (
          <div key={i} style={s('display: flex; align-items: baseline; gap: 8px; font-size: 10px; padding: 1px 0;')}>
            <span style={s('flex: 1; min-width: 0; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;')}>{ш.шаг}</span>
            <span style={s('width: 78px; text-align: right; color: var(--ink); font-variant-numeric: tabular-nums;')}>{ш.дожило.toLocaleString('ru')}</span>
            <span style={s('width: 42px; text-align: right; color: var(--muted-soft); font-variant-numeric: tabular-nums;')}>{ш.доля}%</span>
            <span style={s('width: 46px; text-align: right; color: var(--muted-soft); font-variant-numeric: tabular-nums;')}>книг {ш.книг}</span>
          </div>
        );
      })}
      {(ворон.источники || []).length ? (
        <div style={s('margin-top: 8px;')}>
          <div style={s('font-size: 9px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted-soft); margin-bottom: 4px;')}>
            кто доходит до отбора · {ворон.источники.length} книг</div>
          {/* ВСЕ книги двумя колонками, а не топ-6 в столбик (2026-08-28,
              владелец: «я вижу только 5, и даже так она дохуя места занимает»).
              Сорок книг ложатся в двадцать строк; имена — для глаз (имяКниги),
              полное имя и счёт строк — в подсказке. */}
          <div style={s('display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px;')}>
            {ворон.источники.map(function (и, j) {
              return (
                <div key={j} title={и.источник + ' · строк ' + фмт(и.строк)}
                     style={s('display: flex; align-items: baseline; gap: 5px; font-size: 9px; padding: 1px 0; min-width: 0;')}>
                  <span style={s('width: 30px; text-align: right; flex-shrink: 0; color: var(--ink); font-variant-numeric: tabular-nums;')}>{и.доля}%</span>
                  <span style={s('min-width: 0; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;')}>{имяКниги(и.источник)}</span>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  ) : null;

  // Дневная активность — столбики за 30 дней. Число в ряд не выносим: тут
  // важна форма, а не значение (значение — в подсказке столбика).
  var дни = g.daily_last_30 || {};
  var ключи = Object.keys(дни).sort();
  var макс = ключи.reduce(function (m, k) { return Math.max(m, дни[k] || 0); }, 0) || 1;

  var темы = (c.textThemes ? c.textThemes() : []).slice(0, 12);
  var схемы = Object.entries(g.rhyme_scheme_counts || {}).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 5);

  return (
    <div data-pa="down" data-po={st.closing === 'jobs' ? '1' : null} style={s(ПАНЕЛЬ + ' width: 340px; max-height: 74vh; overflow-y: auto;')}>
      {/* Фоновые работы и статистика — ОДНА кнопка (требование: статистика переезжает в круглую иконку фоновых работ — двух отдельных мест
      не нужно.). Работы стоят сверху и только когда есть
          о чём говорить: в покое это была бы строка «работ нет» над сводкой. */}
      {воронка}
      {работы.length ? (
        <div style={s('margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid var(--border-subtle);')}>
          <div style={s(ЗАГОЛОВОК + ' margin-bottom: 8px;')}>фоновые работы</div>
          {работы.map(function (j, i) {
            var беда = j.state === 'error' || j.state === 'stalled';
            return (
              <div key={i} style={s('margin-bottom: 9px;')}>
                <div style={s('display: flex; align-items: baseline; justify-content: space-between; gap: 8px; font-size: 10px; color: var(--muted-hard);')}>
                  <span style={s('min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;')}>{j.label}</span>
                  <span style={s('flex-shrink: 0; font-size: 8.5px; color: ' + (беда ? '#c96a6a' : 'var(--muted-soft)') + ';')}>{j.подпись}</span>
                </div>
                <div style={s('height: 2px; background: var(--border-subtle); border-radius: 1px; margin: 5px 0 4px; overflow: hidden;')}>
                  <div style={{ width: j.pct + '%', height: '100%', background: беда ? '#c96a6a' : 'var(--ink)' }}></div>
                </div>
                <div style={s('font-size: 8.5px; color: var(--muted-soft); font-variant-numeric: tabular-nums;')}>{j.detail}</div>
              </div>
            );
          })}
        </div>
      ) : null}

      <div style={s(ЗАГОЛОВОК + ' margin-bottom: 9px;')}>статистика</div>

      {/* НАДГРОБИЕ: ЗДЕСЬ СТОЯЛИ ШЕСТЬ БЛОКОВ — «среда», «работа», «откуда
          строки», «избранное», «корпус», «лента» (сняты 2026-08-28, владелец:
          «всё лишнее, бесполезное и некрасивое из статистики удалить»).
          Что и почему умерло:
            · «среда» (версия/система/ядро/ошибки) — второй источник правды:
              всё это несёт отчёт во вкладке «лог», который и создан, чтобы
              его присылали;
            · «лента: строк 5» — строфа стоит на экране, считать её строки
              цифрой в панели — говорить человеку то, что он видит глазами;
            · «в избранном» и «в истории» — дубли счётчиков шапки;
            · задержки (средняя/p95) — метрика разработчика, живёт в csv;
            · «откуда строки» — три доли, застывшие у него на одном значении
              (корпус ~100%): форма, которая не движется, врёт движением;
            · «источников включено» — то же число стоит строкой выше, в
              шапке воронки («N книг»).
          Осталось то, что отвечает на вопросы «сколько я работаю», «каков
          выход в избранное» и «не кончается ли корпус». */}
      {блок('работа', [
        ['генераций', фмт(g.count)],
        ['строк показано', фмт(sh.total_lines)],
        ['в избранное за всё время', фмт(f.added)],
        // «выход показанного в избранное» стоял здесь прочерком: rate_pct снят
        // на сервере ещё в блоке «живое» (core/stats.py — «мерить не
        // программу, а человека»), а экран продолжал обещать число. Поле без
        // производителя — та же мёртвая строка, что поле без читателя.
        ['фрагментов в корпусе', фмт(nl.pool_total)],
        ['ещё не показано', фмт(nl.pool_available)],
      ], 'work')}

      {ключи.length ? (
        <div style={s('margin-bottom: 12px;')}>
          <div style={s(ЗАГОЛОВОК + ' margin-bottom: 6px;')}>за 30 дней</div>
          <div style={s('display: flex; align-items: flex-end; gap: 2px; height: 34px;')}>
            {ключи.map(function (k, i) {
              var h = Math.max(2, Math.round(32 * (дни[k] || 0) / макс));
              return (<div key={i} title={k + ': ' + дни[k]} style={{ flex: 1, height: h + 'px', background: 'var(--muted-soft)', borderRadius: '1px' }}></div>);
            })}
          </div>
        </div>
      ) : null}

      {темы.length ? (
        <div style={s('margin-bottom: 12px;')}>
          {/* Требование: частые темы считать не по вводимым темам, а по сохранённым текстам.. Считаем по избранному и
              листам — по тому, что пользователь ОСТАВИЛ, а не однажды напечатал. */}
          <div style={s(ЗАГОЛОВОК + ' margin-bottom: 5px;')}>о чём тексты</div>
          <div style={s('display: flex; flex-wrap: wrap; gap: 4px;')}>
            {темы.map(function (t, i) {
              return (<span key={i} style={s('font-size: 9px; color: var(--muted); background: color-mix(in srgb, var(--ink) 6%, transparent); border-radius: 3px; padding: 3px 6px; white-space: nowrap;')}>{t.w}<span style={s('color: var(--muted-soft);')}>{' · ' + t.n}</span></span>);
            })}
          </div>
        </div>
      ) : null}

      {схемы.length ? блок('рифмовки', схемы.map(function (x) { return [x[0], фмт(x[1])]; }), 'sch') : null}

      {/* Выгрузка здесь, а не в настройках: она выгружает СТАТИСТИКУ и корпус,
          и пользователь прав — в настройках ей нечего делать. */}
      <div style={s('display: flex; align-items: center; gap: 12px; border-top: 1px solid var(--border-subtle); padding-top: 9px;')}>
        <span style={s(ЗАГОЛОВОК)}>выгрузить</span>
        <button onClick={function () { c.exportStatsJson(); }} style={s(ССЫЛКА)} className={hov('color: var(--ink)')}>json</button>
        <button onClick={function () { c.exportStatsCsv(); }} style={s(ССЫЛКА)} className={hov('color: var(--ink)')}>csv</button>
        <button onClick={function () { c.exportCorpus(); }} style={s(ССЫЛКА)} className={hov('color: var(--ink)')}>бэкап корпуса</button>
      </div>
    </div>
  );
}


// ЧЁРНЫЙ СПИСОК — своя кнопка рядом с избранным и историей (Раунд 57).
//
// Делает то же, что они: убирает строки из выдачи навсегда. Разница в правиле —
// избранное хранит нужное, история прячет ПОКАЗАННОЕ, чёрный список прячет
// НАЗВАННОЕ. Три родственные вещи, три соседние кнопки.
//
// Счётчик справа от правила — цена этого правила в строках. Считается тем же
// действием, что и сам запрет (пересечение по указателю слов), поэтому
// показывается сразу и ничего не стоит сверх.
export function renderBlackPanel(c) {
  var st = c.state;
  var правила = (st.black && st.black.rules) || [];
  var всего = правила.reduce(function (s, п) { return s + (п.lines || 0); }, 0);
  return (
    <div data-pa="down" data-po={st.closing === 'black' ? '1' : null} style={s(ПАНЕЛЬ + ' width: 360px;')}>
      <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px;')}>
        <span style={s(ЗАГОЛОВОК)}>чёрный список · {правила.length}</span>
        <span style={s('font-size: 9px; color: var(--muted-soft);')}>убрано строк: {фмт(всего)}</span>
      </div>
      <p style={s('margin: 0 0 8px; font-size: 9px; line-height: 1.55; color: var(--muted-soft);')}>
        слово или сочетание · ловятся склонения, но не части других слов:
        «с» уберёт «с» как отдельное слово и не тронет «список»
      </p>
      {/* ПОЛЕ БЕЗ УПРАВЛЕНИЯ ИЗ СОСТОЯНИЯ (Раунд 57). Первая версия была
          управляемой (`value` из state), и отчёт: ввод в попапе не работал.. Управляемое поле в этой панели зависит от того, доедет ли
          setState обратно до отрисовки; здесь между вводом и отрисовкой стоит
          попап-система с таймерами закрытия, и одного лишнего перерисовывания
          хватает, чтобы значение откатилось на прежнее.
          Неуправляемое поле не зависит ни от чего: буквы пишет браузер, а мы
          читаем их в момент ввода. Правило добавляется по Enter, значение
          читается прямо из события. */}
      <input type="text" placeholder="госпожа де сент-анж" spellCheck={false} autoFocus
        onKeyDown={function (e) {
          if (e.key !== 'Enter') return;
          e.preventDefault();
          var п = e.target.value;
          e.target.value = '';
          c.addBlack(п);
        }}
        style={s('width: 100%; background: none; border: none; border-bottom: 1px solid var(--border-subtle);'
          + ' color: var(--ink); font-family: inherit; font-size: 11px; padding: 4px 0; outline: none; margin-bottom: 8px;')} />
      {правила.map(function (п, i) {
        return (
          <div key={i} style={s('display: flex; align-items: baseline; gap: 8px; font-size: 10.5px; padding: 3px 0; border-bottom: 1px solid var(--border-subtle);')}>
            <span style={s('flex: 1; min-width: 0; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;')}>{п.rule}</span>
            <span style={s('color: var(--muted-soft); font-variant-numeric: tabular-nums;')}
              title="сколько строк корпуса убирает это правило">−{фмт(п.lines)}</span>
            <button onClick={function () { c.removeBlack(п.rule); }} title="Убрать правило"
              style={s('appearance: none; border: none; background: none; color: var(--muted-soft); font-family: inherit; font-size: 12px; cursor: pointer; padding: 0 2px;')}
              className={hov('color: var(--ink)')}>×</button>
          </div>
        );
      })}
      {!правила.length ? (
        <div style={s('font-size: 9px; color: var(--muted-soft); padding: 4px 0;')}>пусто · впиши слово и нажми ввод</div>
      ) : null}
    </div>
  );
}
