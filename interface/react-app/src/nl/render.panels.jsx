// Панели и хром из дизайна «Editor First» (project-notes/mockups/design-v2/
// Editor First.dc.html: шапка 162..163, 893..1136; легенда-подвал 1249..1280;
// vals — renderVals 3390..4105). Вызывается из render() интегратора:
// renderHeader(this) / renderLegend(this) / renderFlash(this); vals считаются
// здесь же, локально — renderVals целиком не переносится.
// Отличия от дизайна — решения прожарки (PLAN.md) и граница с бэкендом:
//   - фристайл-хром шапки (микрофон/трек/строка/сцена/профили/кадр/запись)
//     приходит слотом c.renderSheetPill(): его заполняет интегратор
//     (Nakedlunch.jsx). Пилюля листов оттуда вырезана 2026-08-18;
//   - пилюли избранного и истории перенесены из подвала в правый блок шапки
//     (план порта), попапы открываются вниз;
//   - воронка — РЕАЛЬНЫЕ числа бэка (/api/nl/state + funnel из /api/generate),
//     клиентский computeFunnel дизайна не переносится;
//   - строфа-меню показывает текущий профиль строфы (boot/stanzaProfiles),
//     а не жёсткий текст макета;
//   - крутилок пять, «Метр» удалён (решение 5, см. methods.panels.js);
//   - легенда и хоткеи строки про ⌥↵ БОЛЬШЕ НЕ ПОЛУЧАЮТ: клавиша ушла
//     вместе с темой 2026-08-29 (надгробие ниже);
//   - профили вида живут не в localStorage дизайна, а в nl_ui_profiles на бэке
//     (решение 11); строки списка готовит methods.fsprofiles.js.

import { Fragment } from 'react';
import { s, hov } from './style.js';
import { icoBtn } from './icons.js';
import { renderStanzaMenu } from './render.gen.jsx';
import { renderSettings } from './render.settings.jsx';
import { renderFavPanel, renderHistPanel, renderStatsPanel, renderBlackPanel } from './render.data.jsx';

// ---- рецепты стилей из renderVals ----
const tabPill = (a) => 'appearance: none; border: none; background: transparent; border-radius: var(--radius); padding: 10px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; cursor: pointer; white-space: nowrap; min-width: 0; flex-shrink: 1; overflow: hidden; text-overflow: ellipsis; position: relative; z-index: 1; transition: color 180ms var(--ease); color: ' + (a ? 'var(--canvas)' : 'var(--muted)') + ';';
const hudBtn = (on) => icoBtn(on ? 'var(--ink)' : 'var(--muted-soft)');
// Значки сжатой шапки (ярус 2+): та же графика, что у остальных значков хрома —
// тонкий штрих currentColor, 12px. Слово заменяется значком, а не пропадает.
const ICO_FAV = (<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" style={{ flexShrink: 0 }}><path d="M12 3.7l2.5 5.1 5.6.8-4.1 4 1 5.6L12 16.5l-5 2.7 1-5.6-4.1-4 5.6-.8z"></path></svg>);
const ICO_HIST = (<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}><path d="M3.6 12a8.4 8.4 0 1 0 2.5-6"></path><path d="M3.3 4.8v3.9h3.9"></path><path d="M12 7.7V12l3 1.8"></path></svg>);
// палитра тона интерфейса — PAL_DEF.panel дизайна (2682); механизм тот же:
// клик выбирает, повторный клик открывает нативный спектр
const UI_TINT_PAL = ['#2436e0', '#d81b74', '#e6620a', '#5b1fd6', '#0a8f82', '#c81f3f'];

// ЛЕГЕНДА ПЕРЕПИСАНА ПОД НОВЫЙ ЭКРАН (2026-08-18, волна «экран»).
//
// В ЭТОЙ ПРОГРАММЕ ИНТЕРФЕЙС ВРАЛ ТРИЖДЫ: легенда обещала «перекатить строку»
// и «закрепить строку», которых в коде не было НИКОГДА, а подсказка внизу
// обещала «⌘⌥↵ — серия» уже после того, как серию вырезали. Каждый раз это
// ловилось только чтением кода — потому что не работающая клавиша молчит.
//
// Отсюда порядок, а не пожелание: сперва выписать, что РЕАЛЬНО обрабатывается,
// потом писать строки. Сегодня обрабатывается ровно это:
//   ↵ / ⌘↵ / Ctrl+↵ — следующая строфа (methods.lenta.js: lentaКлавиша);
//   Esc — закрыть панель (Nakedlunch.jsx: onGlobalKey);
//   клик по звезде — строка в избранное (render.lenta.jsx → сохранитьСтроку);
//   выделение мышью и ⌘C — обычное браузерное, своего кода под ним нет.
// И больше НИЧЕГО: стрелки, Shift, пробел, R и свой ⌘C вырезаны вместе с
// выделением строк, клик по слову — вместе с попапом.
export function legendRowsCalc() {
  return [
    { k: '↵', v: 'следующая строфа' },
    { k: '⌘↵', v: 'то же самое — для привычки' },
    { k: '★', v: 'в избранное; залитая — уже там, и в выдачу такая строка не вернётся' },
    { k: 'мышь', v: 'выделить и скопировать текст как обычно' },
    { k: 'Esc', v: 'закрыть панель' }
  ];
}

// ⌥↵ УБРАНА ОТСЮДА 2026-08-30, И ЭТО ЗАПОЗДАЛО НА ДЕНЬ. Обработчик расстался
// с ней вместе с темой ещё 2026-08-29 (надгробие в methods.lenta.js), а обе
// строки — и в легенде, и в подсказке — остались стоять и обещать с экрана
// то, чего в коде нет. Поймано глазами на живом стенде, не тестом. Правило,
// записанное выше в этом же файле, ровно об этом: строка обязана существовать
// в обработчиках, иначе экран врёт.

// ПОДСКАЗКА ВНИЗУ — ДВЕ СТРОКИ, И ЭТО ПОТОЛОК. Владелец про прежнюю: «дохуя
// много лишней информации». Список короче легенды, но не «правдивее наполовину»:
// каждая строка обязана существовать в обработчиках.
export function hotRowsCalc() {
  return [
    { k: '↵', v: 'дальше' },
    { k: '★', v: 'в избранное' }
  ];
}

// ВОРОНКА ВЫРЕЗАНА (Раунд 51, замер аудита). Её потребитель `fu`
// присваивался и не читался ни разу — инфографика ушла с экрана ещё в
// Раунде 50, а функция осталась и считалась на каждую перерисовку. Вместе с
// ней с бэка ушёл `_rich_funnel`, который ради этих чисел строил набор из
// 1.96 млн строк на КАЖДУЮ генерацию (до 76% времени запроса).

// строка настроек документа / общих настроек — шаблон дизайна 1036..1048 и
// 1075..1089 (различаются только min-width подписи и значения)
// ================================================================
// Шапка: вкладки с бегунком, правый блок пилюль, статус, часы
// ================================================================
export function renderHeader(c) {
  var st = c.state, isFs = st.tab === 'fs';
  var edOnly = isFs ? 'display: none; ' : '';
  var edOnlyFlex = isFs ? 'display: none; ' : 'display: flex; ';
  var fmt = c.fmt ? c.fmt.bind(c) : function (n) { return String(Math.round(n)); };
  var pO = function (k) { return st.closing === k ? '1' : null; };
  var noFocus = function (e) { e.preventDefault(); };

  // ---- ярус сжатия шапки (Раунд 38; см. hdrFit в methods.panels.js) ----
  // Ничего не пропадает: подписи становятся короче, потом значками, отступы и
  // просветы ужимаются. Что именно уходит с какого яруса — расписано у hdrFit.
  var hdrT = c.hdr ? c.hdr() : 0;
  var hdrPad = ['18px 32px', '16px 22px', '13px 14px', '11px 10px'][hdrT];
  var hdrGap = [16, 12, 10, 8][hdrT];          // между тремя блоками шапки
  var hdrGap2 = [14, 12, 10, 8][hdrT];         // внутри блока
  var hdrGap3 = [10, 9, 8, 7][hdrT];           // между значками хрома
  // Половины шапки НЕ сжимаются сами (fit-content) — на этом стоит замер вылета
  // в hdrFit. Но на последнем ярусе сжимать больше нечем, и тогда единственный
  // честный выход — разрешить им ужаться: имя листа уедет в многоточие, а не
  // кнопки за край экрана. Ниже 720 (min_size окна) это уже запас на всякий.
  var hdrMin = hdrT >= 3 ? '0' : 'fit-content';
  var favN = String((st.favs || []).length);
  var histN = String((st.hist || []).length);
  // Счётчик чёрного списка — число ПРАВИЛ, а не убранных строк: в шапке важно
  // «сколько я запретил», сколько это стоит — видно в самой панели.
  var blackN = String(((st.black && st.black.rules) || []).length);

  // ---- индикатор фоновых работ ----
  var jobs = c.jobsSummary ? c.jobsSummary() : { state: 'покой', pct: 0, n: 0, running: 0 };
  var КРУГ = 2 * Math.PI * 7.4;
  var jobsDash = (jobs.pct / 100 * КРУГ).toFixed(1) + ' ' + КРУГ.toFixed(1);
  var jobsColor = jobs.state === 'ошибка' ? '#c96a6a'
    : (jobs.state === 'покой' ? 'var(--muted-soft)' : 'var(--ink)');
  var jobsTitle = jobs.state === 'покой' ? 'Фоновых работ нет'
    : (jobs.state === 'ошибка' ? 'Фоновая работа встала или упала'
      : (jobs.state === 'готово' ? 'Фоновая работа закончена'
        : 'Идёт обработка: ' + jobs.pct + '%'));

  var лента = st.lenta || [];

  // ---- избранное и история (renderVals 4030..4034) ----

  // ---- воронка (реальные числа) ----

  // ---- подпись кнопки генерации (Раунд 50) ----------------------------
  // Раньше здесь считалась «доля сырья» и подпись «алгоритм · 30%»: «Отбор»
  // был ползунком. Теперь режим бинарный — кнопке достаточно знать, что стоит
  // сейчас.
  // 2026-08-18: хвост «N звеньев» убран вместе с цепочкой. Считать длину
  // мёртвого `st.chain` значило бы вечно писать «0 звеньев» — подпись, которая
  // врёт тем убедительнее, чем меньше на неё смотрят. Вместо звеньев — длина
  // самой строфы, единственное, что тут теперь есть.
  // 2026-08-18: подпись называет ПРЕСЕТ, а не режим отбора. Режимов было два
  // на девять ползунков, и «алгоритм» не сообщал ничего — он стоял в 96.4%
  // прогонов. Пресет называет решение целиком; не совпал ни с одним (старые
  // положения из settings.json) — так и говорим, а не выдаём ближайший за свой.
  var классика = (st.knobMode || 'алгоритм') === 'классика';
  var строкВСтрофе = (c.curSpec() || []).length;
  var генTitle = 'Строфа · ↵ · ' + (c.текущийПресет() || 'свои настройки')
    + ' · ' + строкВСтрофе + ' стр.';

  // ---- статистика (renderVals 4013..4021; источники — реальный /api/nl/state) ----
  var nl = st.nl || {};
  var nlSources = (nl.sources || []).filter(function (x) { return x.active; });
  // Счётчики листа, папок, корзины и секций вырезаны 2026-08-18 вместе с
  // документом — считать стало нечего. Осталось то, что есть на экране.
  var statRows = [
    { k: 'строк в ленте', v: String(лента.length) },
    { k: 'избранное', v: String((st.favs || []).length) }, { k: 'история', v: String((st.hist || []).length) },
  ].concat(nlSources.map(function (x) { return { k: x.name, v: fmt(x.fragment_count || 0) }; }))
    .concat([{ k: 'корпус', v: fmt(nl.pool_total || 0) }]);

  // ---- общие настройки ----
  var C = c.cfg();
  var cfgSections = c.cfgSectionsCalc();
  var uiTintSwatches = UI_TINT_PAL.map(function (hex) {
    var on = C.uiTint === hex;
    return {
      title: on ? hex + ' · клик — свой цвет' : hex,
      style: 'appearance: none; flex-shrink: 0; width: 20px; height: 20px; padding: 0; border-radius: 50%; border: 1px solid var(--border-soft); cursor: pointer; background: ' + hex + ';' + (on ? ' box-shadow: 0 0 0 2px var(--ink);' : ''),
      onPick: function () {
        if (C.uiTint === hex) { var el = document.getElementById('uiTintPicker'); if (el) { if (el.showPicker) { try { el.showPicker(); } catch (e) { el.click(); } } else el.click(); } return; }
        c.setCfg('uiTint', hex);
      }
    };
  });
  var uiTintPickerStyle = 'position: absolute; left: ' + (Math.max(0, UI_TINT_PAL.indexOf(C.uiTint)) * 27 + 44) + 'px; top: 0; width: 20px; height: 20px; padding: 0; border: none; opacity: 0; pointer-events: none; background: none;';
  var uiTintOffStyle = 'appearance: none; border: none; border-radius: 3px; padding: 4px 7px; font-family: inherit; font-size: 8.5px; cursor: pointer; ' + (!C.uiTint || C.uiTint === 'нет' ? 'background: var(--ink); color: var(--canvas);' : 'background: color-mix(in srgb, var(--ink) 8%, transparent); color: var(--muted);');

  // ---- настройки ленты + легенда ----
  // Те же три ручки, что управляли строками документа: размер, интерлиньяж и
  // ширина колонки. Документа нет, а строки остались — в ленте, и ручки
  // переподключены к ней (render.lenta.jsx читает textSize/lineGap/docFont,
  // colWidth приходит через --content-max-width из applyTheme). Выбросить их
  // значило бы отнять единственную ручку размера текста во всём приложении.
  var docCfgItems = c.cfgRowsCalc([
    c.cfgNumItem('textSize', 'размер строки', 11, 40, 1, 15, 'px'),
    c.cfgNumItem('lineGap', 'интерлиньяж', 1.2, 2.4, 0.05, 1.5),
    c.cfgPickItem('colWidth', 'ширина колонки', ['очень узкая', 'узкая', 'средняя', 'широкая'], 'очень узкая')
  ]);
  var legendRows = legendRowsCalc();

  // ---- стили панелей с display-переключением (renderVals 3920, 4003, 4059) ----
  var cfgPanelStyle = 'position: absolute; top: calc(100% + 12px); right: 0; z-index: 80; width: 430px; max-height: 68vh; overflow-y: auto; background: var(--menu-bg); backdrop-filter: var(--glass-fx); -webkit-backdrop-filter: var(--glass-fx-fallback); contain: paint; isolation: isolate; box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: 14px 16px; display: ' + (st.openPill === 'cfg' ? 'block' : 'none') + ';';

  return (
    <header ref={c.hdrRef} data-chrome="1" data-float={isFs ? '1' : null} style={s('display: flex; align-items: center; padding: ' + hdrPad + '; gap: ' + hdrGap + 'px; position: relative; z-index: 45; flex-shrink: 0; min-width: 0;')}>
      <div style={s('flex: 1 1 0; min-width: ' + hdrMin + '; display: flex; align-items: center; gap: ' + hdrGap2 + 'px;')}>
        {/* фристайл-хром (микрофон/трек/строка/сцена/профили/кадр/запись) —
            слот интегратора. Пилюля листов, «сохранено 12:44» и отмена-возврат
            стояли здесь же и вырезаны 2026-08-18 вместе с документом. */}
        {typeof c.renderSheetPill === 'function' ? c.renderSheetPill() : null}
      </div>
      <nav ref={c.tabsRef} style={s('flex: 0 0 auto; display: flex; gap: 4px; padding: 3px; position: relative;')}>
        <div data-tab-ind="1" aria-hidden="true" style={s('position: absolute; top: 3px; bottom: 3px; left: 0; width: 0; border-radius: var(--radius); background: var(--ink); z-index: 0; pointer-events: none;')}></div>
        {/* ВКЛАДОК ДВЕ (2026-08-18). Третьей была «nakedlunch» — редактор
            документа; он вырезан целиком, а лента из «отдельной вкладки сбоку»
            стала единственной поверхностью. Требование:
            «лента — отдельная вкладка, которая уже не нужна в таком виде. По
            сути ты наплодил говна, не почистил старое, фактически не убрал». */}
        <button data-tab="lenta" onMouseDown={noFocus} onClick={() => c.setTab('lenta')} style={s(tabPill(c.state.tab === 'lenta'))}>лента</button>
        <button data-tab="fs" onMouseDown={noFocus} onClick={() => c.setTab('fs')} style={s(tabPill(isFs))}>freestyle</button>
      </nav>
      <div style={s('flex: 1 1 0; min-width: ' + hdrMin + '; display: flex; align-items: center; justify-content: flex-end; gap: ' + hdrGap2 + 'px;')}>

        {/* ---- избранное · история (из подвала дизайна 1257..1276; попапы вниз) ---- */}
        <div style={s(edOnlyFlex + 'align-items: center; gap: ' + (hdrGap2 + 2) + 'px;')}>
          <div data-pop="1" style={s('position: relative; z-index: 60;')}>
            <button onClick={() => c.tog('fav')} title={'Избранное · ' + favN} style={s('appearance: none; background: none; border: none; padding: 0; font-size: 10.5px; color: var(--muted-soft); cursor: pointer; font-variant-numeric: tabular-nums; white-space: nowrap; display: flex; align-items: center; gap: 5px;')} className={hov('color: var(--ink)')}>{hdrT >= 2 ? ICO_FAV : 'избранное'}{hdrT >= 3 ? null : (<span style={s('color: var(--ink);')}>{favN}</span>)}</button>
            {st.openPill === 'fav' && renderFavPanel(c)}
          </div>
          <div data-pop="1" style={s('position: relative; z-index: 60;')}>
            <button onClick={() => c.tog('hist')} title={'История · ' + histN} style={s('appearance: none; background: none; border: none; padding: 0; font-size: 10.5px; color: var(--muted-soft); cursor: pointer; font-variant-numeric: tabular-nums; white-space: nowrap; display: flex; align-items: center; gap: 5px;')} className={hov('color: var(--ink)')}>{hdrT >= 2 ? ICO_HIST : 'история'}{hdrT >= 3 ? null : (<span style={s('color: var(--ink);')}>{histN}</span>)}</button>
            {st.openPill === 'hist' && renderHistPanel(c)}
          </div>
          <div data-pop="1" style={s('position: relative; z-index: 60;')}>
            <button onClick={() => { c.tog('black'); if (c.loadBlack) c.loadBlack(); }}
              title={'Чёрный список · ' + blackN}
              style={s('appearance: none; background: none; border: none; padding: 0; font-size: 10.5px; color: var(--muted-soft); cursor: pointer; font-variant-numeric: tabular-nums; white-space: nowrap; display: flex; align-items: center; gap: 5px;')}
              className={hov('color: var(--ink)')}>чс{hdrT >= 3 ? null : (<span style={s('color: var(--ink);')}>{blackN}</span>)}</button>
            {st.openPill === 'black' && renderBlackPanel(c)}
          </div>
        </div>
        <div aria-hidden="true" style={s(edOnly + 'width: 1px; height: 11px; background: var(--border-subtle); flex-shrink: 0;')}></div>

        <div style={s(edOnlyFlex + 'align-items: center; gap: ' + hdrGap3 + 'px;')}>
          {/* ---- генерация: одна кнопка, одно меню ---- */}
          {/* ОДНА КНОПКА (2026-08-18). Раунд 55 развёл их на три — мастерская,
              сборка, конвейер, — и это было верно, пока занятий было три.
              Значки цепи и серии вырезаны вместе со своими режимами: «pipeline и
              серия это бесполезные режимы на самом деле… их можно вырезать.
              Строфа единственным режимом и всё». Замер за десять живых дней:
              29 прогонов цепи против 587 одиночных строф.
              Режим отбора по-прежнему читается точкой на значке строфы. */}
          <div data-pop="1" style={s('position: relative; z-index: 60;')}>
            <button onClick={() => c.togProfile()} title={генTitle} aria-label="Строфа"
              style={s(hudBtn(st.openPill === 'stanza'))} className={hov('color: var(--ink)')}>
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
                <line x1="4" y1="7" x2="20" y2="7"></line>
                <line x1="4" y1="12" x2="20" y2="12"></line>
                <line x1="4" y1="17" x2="20" y2="17"></line>
                <circle cx="9" cy="7" r="2.1" fill="var(--canvas)"></circle>
                <circle cx="15" cy="12" r="2.1" fill="var(--canvas)"></circle>
                <circle cx="7.5" cy="17" r="2.1" fill={классика ? 'currentColor' : 'var(--canvas)'}></circle>
              </svg>
            </button>
            {st.openPill === 'stanza' && renderStanzaMenu(c)}
          </div>
          {/* Здесь стояли ещё два значка — цепь (два прямоугольника со скобой)
              и серия (стопка листов). Убраны 2026-08-18 вместе с режимами. */}
        </div>
        <div aria-hidden="true" style={s(edOnly + 'width: 1px; height: 11px; background: var(--border-subtle); flex-shrink: 0;')}></div>

        <div style={s('display: flex; align-items: center; gap: ' + hdrGap3 + 'px;')}>
          {/* ---- индикатор фоновой работы (Раунд 39) ----
              Кружок в шапке был долей МОИХ строк в листе и открывал статистику.
              Требование: индикатор по числу источников — сколько обработано из наличных;
              заполняется при заливке книги.. Отдаём кружок работам:
              статистика переехала в ⚙ отдельным разделом. Роут /api/status
              существовал с июля, и не звал его никто.
              Покой — тонкий контур (замечание: постоянно заполненный индикатор выглядит плохо), работа — дуга по проценту, несколько
              работ — плюс точка в центре, беда — приглушённый красный. */}
          <div data-pop="1" style={s('position: relative; z-index: 60;')}>
            <button onClick={() => { c.tog('jobs'); c.loadStats(); }} title={jobsTitle} aria-label="Фоновые работы" style={s(icoBtn(jobsColor))} className={hov('color: var(--ink)')}>
              <svg viewBox="0 0 20 20" width="14" height="14">
                <circle cx="10" cy="10" r="7.4" fill="none" stroke="var(--border-soft)" strokeWidth="1.3" />
                {jobs.state !== 'покой' ? (<circle cx="10" cy="10" r="7.4" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray={jobsDash} strokeLinecap="round" transform="rotate(-90 10 10)" />) : null}
                {jobs.running > 1 ? (<circle cx="10" cy="10" r="2" fill="currentColor" />) : null}
              </svg>
            </button>
            {st.openPill === 'jobs' && renderStatsPanel(c)}
          </div>

          {/* ОШИБКУ НЕЛЬЗЯ НЕ ЗАМЕТИТЬ, НО ОНА НЕ МЕШАЕТ (Раунд 59).
              Не окно поверх работы: ошибка случается, когда человек занят
              строкой, и модальное окно он закроет не читая. Метка на шестерёнке
              не уходит сама, ведёт прямо во вкладку «Лог» и при нуле ошибок не
              существует вовсе — обычный пользователь её не видит никогда. */}
          <div data-pop="1" style={s('position: relative; z-index: 60;')}>
            {st.логОшибок ? (
              <span onClick={function () { c.setState({ cfgTab: 'лог' }); c.tog('cfg'); c.обновитьЛог(); }}
                title={'ошибок за сессию: ' + st.логОшибок + ' — нажми, чтобы отправить отчёт'}
                style={s('position: absolute; top: -3px; right: -3px; z-index: 61; min-width: 14px; '
                  + 'height: 14px; padding: 0 3px; border-radius: 999px; background: #e05252; '
                  + 'color: #fff; font-size: 9px; line-height: 14px; text-align: center; '
                  + 'cursor: pointer; box-shadow: 0 0 0 2px var(--canvas);')}>
                {st.логОшибок > 9 ? '9+' : st.логОшибок}</span>
            ) : null}
            <button onClick={() => c.tog('cfg')} aria-label="Настройки" title="Общие настройки" style={s(hudBtn(st.openPill === 'cfg'))}>
              <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3.2"></circle><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.9 19.3a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.56V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.24.6.8 1 1.44 1.03H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.51 1z"></path></svg>
            </button>
            <div data-pa="down" data-po={pO('cfg')} style={s(cfgPanelStyle)}>
              {renderSettings(c, { cfgSections, uiTintSwatches, uiTintOffStyle, uiTintPickerStyle, docCfgItems, legendRows, statRows })}
            </div>
          </div>
        </div>


        {/* ---- статус-виджет: строку пишут методы генерации ('тема: …' / 'без темы' / 'генерация…', state.genStatus в methods.gen.js) ---- */}
        {!isFs && st.genStatus ? (
          <span title={st.genStatus} style={s('max-width: 260px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; font-size: 10.5px; color: ' + (st.genBusy ? 'var(--ink)' : 'var(--muted-soft)') + '; font-variant-numeric: tabular-nums;')}>{st.genStatus}</span>
        ) : null}
        {/* Часы: перерисовываются с любым setState — этого достаточно.
            В редакторе от яруса 1 уходят: рядом стоит «сохранено 12:44», то
            есть время там и так есть, плюс оно всегда есть в строке меню
            системы. Во фристайле остаются на всех ярусах — там правый блок
            почти пуст, а окно бывает во весь экран поверх всего. */}
        {isFs || hdrT < 1 ? (
          <span style={s('font-size: 10.5px; color: var(--muted-soft); font-variant-numeric: tabular-nums; white-space: nowrap;')}>{c.clock()}</span>
        ) : null}
      </div>
    </header>
  );
}

// ================================================================
// Подсказка-подвал: только клавиши (дизайн 1249..1280). Пилюли избранного и
// истории уехали в шапку (см. renderHeader), счётчик справа вырезан 2026-08-18.
// ================================================================
export function renderLegend(c) {
  // СЧЁТЧИК СПРАВА УБРАН (2026-08-18). Он считал сперва документ («N строк ·
  // M моих»), потом накопленную ленту («N строк · M в избранном»). На экране
  // теперь всегда одна строфа — счётчик писал бы вечное «4 строки», то есть
  // длину строфы, которую и так видно целиком. Сколько всего в избранном,
  // говорит пилюля в шапке.
  var hotRows = hotRowsCalc();
  return (
    <div data-chrome="1" style={s('padding: 18px 32px; display: flex; flex-shrink: 0; position: relative; z-index: 45;')}>
      <div style={s('width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 35px;')}>
        <div style={s('flex: 1; min-width: 0; display: flex; align-items: center; flex-wrap: wrap; gap: 4px 14px; font-size: 9px; line-height: 1.6; color: var(--muted);')}>
          {hotRows.map((h, i) => (
            <span key={i} style={s('white-space: nowrap;')}><span style={s('color: var(--muted-hard); font-variant-numeric: tabular-nums;')}>{h.k}</span> {h.v}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ================================================================
// Flash: плавающее сообщение (в дизайне flashMsg живёт в savedLabel шапки —
// здесь отдельный тост, чтобы сообщение было видно и при спрятанном хроме)
// ================================================================
export function renderFlash(c) {
  if (!c.state.flashMsg) return null;
  return (
    <div style={s('position: fixed; left: 50%; bottom: 84px; transform: translateX(-50%); z-index: 95; background: var(--menu-bg); backdrop-filter: var(--glass-fx); -webkit-backdrop-filter: var(--glass-fx-fallback); contain: paint; isolation: isolate; box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: 8px 14px; font-size: 10.5px; color: var(--ink); white-space: nowrap; pointer-events: none;')}>
      {c.state.flashMsg}
    </div>
  );
}
