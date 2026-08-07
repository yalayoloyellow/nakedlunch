// Панели и хром из дизайна «Editor First» (project-notes/mockups/design-v2/
// Editor First.dc.html: шапка 162..163, 893..1136; легенда-подвал 1249..1280;
// vals — renderVals 3390..4105). Вызывается из render() интегратора:
// renderHeader(this) / renderLegend(this) / renderFlash(this); vals считаются
// здесь же, локально — renderVals целиком не переносится.
// Отличия от дизайна — решения прожарки (PLAN.md) и граница с бэкендом:
//   - фристайл-хром шапки (микрофон/трек/строка/сцена/профили/кадр/запись) и
//     пилюля листов (лист/переименование/папки) приходят слотом
//     c.renderSheetPill(): его заполняет интегратор (Nakedlunch.jsx);
//   - пилюли избранного и истории перенесены из подвала в правый блок шапки
//     (план порта), попапы открываются вниз;
//   - воронка — РЕАЛЬНЫЕ числа бэка (/api/nl/state + funnel из /api/generate),
//     клиентский computeFunnel дизайна не переносится;
//   - строфа-меню показывает текущий профиль строфы (boot/stanzaProfiles),
//     а не жёсткий текст макета;
//   - крутилок пять, «Метр» удалён (решение 5, см. methods.panels.js);
//   - легенда и хоткеи получают строку про ⌥↵ (решение 2);
//   - профили вида живут не в localStorage дизайна, а в nl_ui_profiles на бэке
//     (решение 11); строки списка готовит methods.fsprofiles.js.

import { Fragment } from 'react';
import { s, hov } from './style.js';
import { icoBtn } from './icons.js';
import { renderStanzaMenu, renderPipeMenu, renderSeriesMenu } from './render.gen.jsx';
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

// легенда гутера и разметки — renderVals 4022..4029 + решение прожарки 2 (⌥↵).
// Везде, где ⌘, работает и Ctrl (2026-08-02, просьба пользователя): обработчик
// всегда считал их равными (onGlobalKey: metaKey || ctrlKey), но легенда об
// этом молчала. Практическая польза не только в привычке: меню Cocoa у
// pywebview забирает ⌘A и ⌘C ДО веб-содержимого, поэтому «выделить весь
// документ» в окне приложения работает именно через Ctrl+A.
export function legendRowsCalc() {
  return [
    { k: '01', v: 'номер строки' }, { k: 'а', v: 'буква рифмовки' }, { k: 'nl', v: 'корпус nakedlunch' }, { k: 'я', v: 'написано мной' },
    { k: 'звезда', v: 'в избранное' }, { k: 'стрелка', v: 'перекатить строку заново' },
    { k: 'кнопка', v: 'закрепить — строка не меняется генерацией' }, { k: '##', v: 'заголовок секции · ⌘1' },
    { k: '**', v: 'жирный · ⌘B' }, { k: '*', v: 'курсив · ⌘I' },
    { k: '· ∘ ≀', v: 'стык: рифмовать / свободно / слом' },
    { k: '⌘↵', v: 'сгенерировать' }, { k: '⌥↵', v: 'строфа с обязательным ключом' },
    { k: '⌘Z', v: 'отменить · ⌘⇧Z вернуть' },
    { k: 'Ctrl', v: 'заменяет ⌘ в любом сочетании' }
  ];
}

// хоткеи подвала — renderVals 4061..4064 + решение прожарки 2 (⌥↵)
export function hotRowsCalc() {
  return [
    { k: '⌘↵', v: 'строфа' }, { k: '⌥↵', v: 'строфа с обязательным ключом' }, { k: '⌘⇧↵', v: 'прогон пайплайна' },
    { k: '⌘B', v: 'жирный' }, { k: '⌘I', v: 'курсив' },
    { k: '⌘1–3', v: 'заголовок' }, { k: '⌥↑↓', v: 'двигать строку' }, { k: '⌘Z', v: 'отменить' },
    { k: 'Ctrl', v: 'вместо ⌘ везде' }
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

  var doc = c.cur();
  var lines = doc.filter(function (r) { return r.type === 'line' && r.text; });
  var mineN = lines.filter(function (r) { return r.src === 'я'; }).length;
  var sheets = st.sheets || [];
  var liveSheets = sheets.filter(function (x) { return !x.trashed; });
  var trashN = sheets.filter(function (x) { return x.trashed; }).length;

  // ---- избранное и история (renderVals 4030..4034) ----

  // ---- воронка (реальные числа) ----

  // ---- подпись кнопки генерации (Раунд 50) ----------------------------
  // Раньше здесь считалась «доля сырья» и подпись «алгоритм · 30%»: «Отбор»
  // был ползунком. Теперь режим бинарный и живёт в профиле настроек звена —
  // кнопке достаточно знать, что стоит сейчас.
  var классика = (st.knobMode || 'алгоритм') === 'классика';
  var звеньевВсего = (st.chain || []).length;
  var генTitle = 'Генерация · ' + (классика ? 'классика' : 'алгоритм')
    + ' · ' + (звеньевВсего === 1 ? 'одна строфа' : звеньевВсего + ' звеньев');

  // ---- статистика (renderVals 4013..4021; источники — реальный /api/nl/state) ----
  var nl = st.nl || {};
  var nlSources = (nl.sources || []).filter(function (x) { return x.active; });
  var statRows = [
    { k: 'строк в листе', v: String(lines.length) }, { k: 'моих строк', v: String(mineN) },
    { k: 'листов', v: String(liveSheets.length) }, { k: 'в корзине', v: String(trashN) },
    { k: 'избранное', v: String((st.favs || []).length) }, { k: 'история', v: String((st.hist || []).length) },
    { k: 'папок', v: String((st.folders || []).length) }, { k: 'секций', v: String(doc.filter(function (r) { return r.type === 'role'; }).length) },
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

  // ---- настройки документа + легенда ----
  var docCfgItems = c.cfgRowsCalc([
    c.cfgNumItem('textSize', 'размер строки', 11, 40, 1, 15, 'px'),
    c.cfgNumItem('lineGap', 'интерлиньяж', 1.2, 2.4, 0.05, 1.5),
    c.cfgPickItem('colWidth', 'ширина колонки', ['узкая', 'средняя', 'широкая'], 'узкая')
  ]);
  var legendRows = legendRowsCalc();

  // ---- стили панелей с display-переключением (renderVals 3920, 4003, 4059) ----
  var cfgPanelStyle = 'position: absolute; top: calc(100% + 12px); right: 0; z-index: 80; width: 430px; max-height: 68vh; overflow-y: auto; background: var(--menu-bg); backdrop-filter: var(--glass-fx); -webkit-backdrop-filter: var(--glass-fx-fallback); contain: paint; isolation: isolate; box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: 14px 16px; display: ' + (st.openPill === 'cfg' ? 'block' : 'none') + ';';

  return (
    <header ref={c.hdrRef} data-chrome="1" data-float={isFs ? '1' : null} style={s('display: flex; align-items: center; padding: ' + hdrPad + '; gap: ' + hdrGap + 'px; position: relative; z-index: 45; flex-shrink: 0; min-width: 0;')}>
      <div style={s('flex: 1 1 0; min-width: ' + hdrMin + '; display: flex; align-items: center; gap: ' + hdrGap2 + 'px;')}>
        {/* фристайл-хром (микрофон/трек/строка/сцена/профили/кадр/запись) и
            пилюля листов + savedLabel + undo/redo — слот интегратора */}
        {typeof c.renderSheetPill === 'function' ? c.renderSheetPill() : null}
      </div>
      <nav ref={c.tabsRef} style={s('flex: 0 0 auto; display: flex; gap: 4px; padding: 3px; position: relative;')}>
        <div data-tab-ind="1" aria-hidden="true" style={s('position: absolute; top: 3px; bottom: 3px; left: 0; width: 0; border-radius: var(--radius); background: var(--ink); z-index: 0; pointer-events: none;')}></div>
        <button data-tab="editor" onMouseDown={noFocus} onClick={() => c.setTab('editor')} style={s(tabPill(!isFs))}>nakedlunch</button>
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
          {/* ---- генерация: строфа и пайплайн одним попапом (Раунд 39) ----
              Было три контрола подряд — значок пайплайна, надпись отбора и
              значок профиля, — и все три вели в одну тему. Требование: кнопки расположены удобно., «чтоб кнопки не плодить». Теперь одна:
              подпись показывает режим отбора не открывая, внутри две вкладки.
              Заодно чинится мёртвый клик — надпись отбора звала попап 'gen',
              которого не рисует никто (Раунд 35, мой недосмотр). */}
          {/* РАУНД 55: три кнопки, три меню. Раунд 39 свёл три контрола в один
              («чтоб кнопки не плодить»), и это было верно: тогда все три вели в
              ОДНУ тему. Теперь они ведут в три разных занятия — мастерская,
              сборка, конвейер, — и общий попап делал их громоздкими. Требование: серия и пайплайн — отдельными кнопками и меню, во избежание
              громоздкости..
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

          {/* пайплайн — звенья, соединённые стыками */}
          <div data-pop="1" style={s('position: relative; z-index: 60;')}>
            <button onClick={() => c.tog('pipe')} title="Пайплайн · ⌘⇧↵" aria-label="Пайплайн"
              style={s(hudBtn(st.openPill === 'pipe'))} className={hov('color: var(--ink)')}>
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
                <rect x="3" y="4.5" width="8.5" height="5" rx="1.4"></rect>
                <rect x="12.5" y="14.5" width="8.5" height="5" rx="1.4"></rect>
                <path d="M7.2 9.5v3a2 2 0 0 0 2 2h3.3"></path>
              </svg>
            </button>
            {st.openPill === 'pipe' && renderPipeMenu(c)}
          </div>

          {/* серия — стопка листов */}
          <div data-pop="1" style={s('position: relative; z-index: 60;')}>
            <button onClick={() => c.tog('series')} title="Серия · много прогонов по плану" aria-label="Серия"
              style={s(hudBtn(st.openPill === 'series'))} className={hov('color: var(--ink)')}>
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <rect x="7" y="3.5" width="13" height="13" rx="1.6"></rect>
                <path d="M16.5 19.5H5.6A1.6 1.6 0 0 1 4 17.9V7.2"></path>
              </svg>
            </button>
            {st.openPill === 'series' && renderSeriesMenu(c)}
          </div>
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
// Легенда-подвал: хоткеи слева, счётчик документа справа (дизайн 1249..1280;
// пилюли избранного и истории уехали в шапку — см. renderHeader)
// ================================================================
export function renderLegend(c) {
  var st = c.state;
  var doc = c.cur();
  var lines = doc.filter(function (r) { return r.type === 'line' && r.text; });
  var mineN = lines.filter(function (r) { return r.src === 'я'; }).length;
  var hotRows = hotRowsCalc();
  return (
    <div data-chrome="1" style={s('padding: 18px 32px; display: flex; flex-shrink: 0; position: relative; z-index: 45;')}>
      <div style={s('width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 35px;')}>
        <div style={s('flex: 1; min-width: 0; display: flex; align-items: center; flex-wrap: wrap; gap: 4px 14px; font-size: 9px; line-height: 1.6; color: var(--muted);')}>
          {hotRows.map((h, i) => (
            <span key={i} style={s('white-space: nowrap;')}><span style={s('color: var(--muted-hard); font-variant-numeric: tabular-nums;')}>{h.k}</span> {h.v}</span>
          ))}
        </div>
        <div style={s('display: flex; align-items: center; gap: 16px; flex-shrink: 0;')}>
          <span style={s('font-size: 10.5px; color: var(--muted-soft); font-variant-numeric: tabular-nums; white-space: nowrap;')}>{lines.length + ' строк · ' + mineN + ' моих'}</span>
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
