// Разметка документа из дизайна «Editor First» (project-notes/mockups/design-v2/
// Editor First.dc.html) — дословный перенос в JSX:
//   renderDoc(c)       — колонка документа внутри <section ref={c.sectionRef}>:
//                        шаблон, строки 1192..1247 (градиенты у краёв, контейнер строк,
//                        панель массовых действий, попап слова);
//   renderDocStatus(c) — savedLabel + undo/redo для шапки: строки 886..891.
// Нижний хром дизайна (1249..1280) здесь НЕ рендерится: хоткеи и счётчик несёт
// renderLegend (render.panels.jsx), пилюли избранного/истории переехали в шапку
// (план порта) — второй экземпляр открывал бы те же openPill-попапы дважды.
// Заголовок листа для шапки (810..819) целиком несёт renderSheets
// (render.sheets.jsx) — дубликат renderDocTitle удалён интегратором.
// Соответствующие vals пересчитаны локально из c.state/c.cfg() по renderVals
// дизайна (строки 3390..4105). c — экземпляр Nakedlunch.
//
// Контракт с интегратором:
//   - <section ref={c.sectionRef} style={s('position: relative; flex: 1; min-height: 0;
//     display: flex;')}> — секцию (строка 1138) рендерит интегратор: в ней же живёт
//     заглушка фристайла; renderDoc(c) кладётся внутрь;
//   - контейнер строк ИМПЕРАТИВНЫЙ: React отдаёт пустой <div ref>, наполняет его
//     c.renderRows(), каретку возвращает c.restoreCaret() — оба уже вызываются из
//     componentDidUpdate Nakedlunch.jsx (хуки миксинов);
//   - фокус-проходы дизайна (строки 1505..1516): интегратор добавляет в
//     componentDidUpdate обработку c._focusRename ('title' → фокус+select на
//     [data-title-input]) и c._focus/_focusAt (фокус на [data-idx] строки);
//   - renderDocTitle/renderDocStatus кладутся в шапку; обёртка data-pop с кнопкой
//     «＋» и списком листов (строки 809, 820..884) — за модулем листов;
//   - c.tog/renameSheet/focusFirstLine/insertAt приходят миксинами панелей и листов;
//   - кнопка dirtyShow/«сохранить» профиля отбора (строки 933..935) живёт в панели
//     пайплайна — её переносит модуль пайплайна, здесь её нет.
// Решения прожарки: попап слова рендерится только при WORD_POPUP (фаза 2);
// в легенде хоткеев добавлена строка про принудительный ключ (решение 2).

import { Fragment } from 'react';
import { s, hov } from './style.js';
import { WORD_POPUP } from './methods.doc.js';

// ---- колонка документа: строки 1192..1281 шаблона -------------------------
export function renderDoc(c) {
  var st = c.state, C = c.cfg();
  var isFs = st.tab === 'fs', isEditor = !isFs;
  if (!isEditor) return null;
  var pop = st.pop;
  var lines = st.doc.filter(function (r) { return r.type === 'line' && r.text; });

  // Уход текста у краёв листа делает только цвет — никакого размытия. Цвет берётся из --canvas,
  // поэтому в светлой теме градиент сам становится белым. Верх и низ строятся из одной кривой
  // в одной обёртке, которая заканчивается там же, где текст, — размеры совпадают точно.
  // cfgNumVal дизайна (строка 2599) — локально: модуль вида может ещё не подмешаться
  var cfgNumVal = function (k, dflt) { var v = parseFloat((C || {})[k]); return isNaN(v) ? dflt : v; };
  var FADEON = (C.fadeOn || 'да') === 'да';
  var FADE = Math.round(cfgNumVal('fadeLen', 160));
  var FSTR = cfgNumVal('fadeStr', 100) / 100;
  var FGAM = cfgNumVal('fadeCurve', 0.5);
  var FBLUR = cfgNumVal('fadeBlur', 14);
  var FDIT = cfgNumVal('fadeDither', 0) / 100;
  // Опорная кривая: в середине почти линейна, оба конца сглажены, хвост уводит альфу в ноль
  // так, что границы затемнения не видно. «Кривая» гнёт её степенью, «сила» — множителем.
  var SCRIM = [[0, 100], [0.06, 99], [0.14, 95], [0.24, 89], [0.34, 80], [0.44, 69], [0.54, 57], [0.64, 44], [0.74, 31], [0.83, 20], [0.9, 11], [0.95, 5], [0.98, 2], [1, 0]];
  var fadeA = function (v) {
    var a = Math.pow(Math.max(0, Math.min(1, v / 100)), FGAM) * FSTR;
    return Math.max(0, Math.min(100, a * 100));
  };
  var scrimStops = function (fmt) {
    return SCRIM.map(function (p) { return fmt(fadeA(p[1])) + ' ' + (p[0] * 100).toFixed(1) + '%'; }).join(', ');
  };
  var fadeBox = function (to2, z) {
    // кап в процентах съедал бы 88% высоты на любом экране, поэтому ограничиваем иначе:
    // под резкий текст всегда гарантированы 220px, остальное отдаём градиенту
    return 'position: absolute; left: 0; right: 0; ' + (to2 === 'bottom' ? 'top' : 'bottom') + ': 0; height: min(' + FADE + 'px, calc((100% - 220px) / 2)); z-index: ' + z + '; pointer-events: none;';
  };
  var scrim = function (to2) {
    if (!FADEON) return 'display: none;';
    var stops = scrimStops(function (v) {
      return v >= 99.5 ? 'var(--canvas)' : (v <= 0.2 ? 'rgba(0,0,0,0)' : 'color-mix(in srgb, var(--canvas) ' + v.toFixed(1) + '%, transparent)');
    });
    return fadeBox(to2, 26) + ' background: linear-gradient(to ' + to2 + ', ' + stops + ');';
  };
  // Размытие живёт на той же длине и той же кривой, что цвет. Слоёв три: чем больше радиус,
  // тем короче участок у самого края — так у полупрозрачных зон, где резкая картинка смешивается
  // с размытой (это и есть ореол вокруг букв), почти не остаётся места.
  var BLUR = [[0.14, 1], [0.43, 0.6], [1, 0.3]];
  var blurBand = function (to2) {
    if (!FBLUR || !FADEON) return [];
    return BLUR.map(function (L, i) {
      var stops = SCRIM.map(function (p) {
        return 'rgba(0,0,0,' + (fadeA(p[1]) / 100).toFixed(3) + ') ' + (p[0] * L[1] * 100).toFixed(1) + '%';
      }).join(', ');
      var m = 'linear-gradient(to ' + to2 + ', ' + stops + ', rgba(0,0,0,0) 100%)';
      var r = (FBLUR * L[0]).toFixed(2);
      return { style: fadeBox(to2, 12 + i) + ' backdrop-filter: blur(' + r + 'px); -webkit-backdrop-filter: blur(' + r + 'px); mask-image: ' + m + '; -webkit-mask-image: ' + m + ';' };
    });
  };
  // дизер: тёмный градиент в 8 битах ступенчат сам по себе, тонкий шум разбивает эти ступени.
  // маска у шума — ровно та же кривая, что у затемнения, чтобы у него не было своего края
  var DITHER = "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.95' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='180' height='180' filter='url(%23n)'/%3E%3C/svg%3E\")";
  var dither = function (to2) {
    if (!FDIT || !FADEON) return 'display: none;';
    var m = 'linear-gradient(to ' + to2 + ', ' + scrimStops(function (v) { return 'rgba(0,0,0,' + (v / 100).toFixed(3) + ')'; }) + ')';
    return fadeBox(to2, 27) + ' opacity: ' + FDIT.toFixed(3) + '; mix-blend-mode: soft-light; background-image: ' + DITHER + '; background-size: 180px 180px; mask-image: ' + m + '; -webkit-mask-image: ' + m + ';';
  };
  // запас прокрутки равен фактической длине градиента — первая и последняя строки выходят из него
  // целиком, но на низком окне запас не превращается в экран пустоты
  var padStyle = 'flex: 0 0 auto; width: 100%; height: min(' + (FADE + 24) + 'px, calc((100% - 220px) / 2 + 24px));';
  var scrimTopStyle = isFs ? 'display: none;' : scrim('bottom');
  var scrimBotStyle = isFs ? 'display: none;' : scrim('top');
  var blurLayers = isFs ? [] : blurBand('bottom');
  var blurLayersBot = isFs ? [] : blurBand('top');
  var ditherTopStyle = isFs ? 'display: none;' : dither('bottom');
  var ditherBotStyle = isFs ? 'display: none;' : dither('top');

  // linesRef дизайна — стрелочное поле класса; миксин методов полей не объявляет,
  // поэтому держим ОДИН связанный колбэк на экземпляре: смена ref на каждый рендер
  // заставляла бы React отцеплять и цеплять contenteditable-поддерево
  var linesRefCb = c._linesRefCb || (c._linesRefCb = function (el) { c.linesRef(el); });
  var onDocInput = function () { c.readDom(); };
  var onDocKey = function (e) { c.onDocKey(e); };
  var onDocClick = function (e) { c.onDocClick(e); };
  var onScroll = function () { if (c.state.pop) c.setState({ pop: null }); };
  var emptySheet = lines.length <= 1 && !(lines[0] && lines[0].text);

  // ---- панель массовых действий ----
  var bulkShow = c.markedIdx().length > 0;
  var bulkCount = c.markedIdx().length + ' выбрано';
  var bulkBtn = 'appearance: none; background: none; border: none; padding: 0; font-size: 10.5px; color: var(--muted); cursor: pointer;';
  var bulkRoleLabel = c.markedIdx().every(function (i) { return st.doc[i] && st.doc[i].type === 'role'; }) ? 'в строку' : 'в метку';

  // ---- попап слова (фаза 2, рендер только при WORD_POPUP) ----
  var popOpen = !!pop;
  var popWord = pop ? pop.word : '';
  var popHint = st.popTab === 'строкой' ? 'заменить строку' : 'заменить на';
  var popStyle = 'position: absolute; z-index: 70; left: ' + (pop ? pop.x : 0) + 'px; ' + (pop && pop.up ? 'bottom: ' + pop.y + 'px;' : 'top: ' + (pop ? pop.y : 0) + 'px;') + ' width: ' + (st.popTab === 'строкой' ? 330 : 262) + 'px; background: var(--menu-bg); backdrop-filter: url(#nl-warp) blur(7px) saturate(185%) brightness(1.05); -webkit-backdrop-filter: blur(10px) saturate(185%) brightness(1.05); contain: paint; isolation: isolate; box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: 10px;';
  // решение прожарки 9 (ворота качества): «антонимы» — только словарный слой,
  // без словаря вкладка прячется, не фейкуется; «синонимы» живут всегда —
  // у них есть векторный слой «близкое» и без словаря
  var popTabs = (c.TABS || []).filter(function (t) {
    return t !== 'антонимы' || (st.thesaurus && st.thesaurus.ant);
  }).map(function (t) {
    return { name: t, onPick: function () { c.setPopTab(t); }, style: 'appearance: none; border: none; border-radius: 3px; padding: 5px 8px; font-size: 9px; cursor: pointer; white-space: nowrap; ' + (st.popTab === t ? 'background: var(--ink); color: var(--canvas);' : 'background: color-mix(in srgb, var(--ink) 7%, transparent); color: var(--muted);') };
  });
  // popList живой (фаза 2): на время похода в /api/word/suggest отдаёт
  // скелет-элементы {skel:1} — ниже они рисуются плашками, не кнопками
  var popItems = (WORD_POPUP && pop && c.popList ? c.popList() : []).map(function (o) {
    if (o.skel) return { skel: true };
    // заголовок группы типов рифмы — тот же жест, что метка экспоната в
    // каталоге: мелкий разрядканный шрифт, не кнопка
    if (o.head) return { head: o.head };
    return { w: o.w, n: o.n, wStyle: st.popTab === 'строкой' ? 'min-width: 0; font-size: 11px; line-height: 1.4; white-space: normal; overflow-wrap: anywhere;' : '', onPick: function () { c.applyWord(o.w); } };
  });
  var popHeadStyle = 'padding: 8px 9px 3px; font-size: 8.5px; color: var(--muted-soft); letter-spacing: 0.14em; text-transform: uppercase; flex-shrink: 0;';
  // плашка скелета — в духе дизайна: высота строки списка, лёгкий тон чернил
  var skelStyle = 'height: 32px; flex-shrink: 0; margin: 2px 0; border-radius: 3px; background: color-mix(in srgb, var(--ink) 6%, transparent);';

  return (
    <div style={s('position: relative; z-index: 1; flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0;')}>
      <div style={s('position: relative; flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column;')}>
        {blurLayers.map((bl, i) => <div key={i} aria-hidden="true" style={s(bl.style)}></div>)}
        {blurLayersBot.map((bl, i) => <div key={i} aria-hidden="true" style={s(bl.style)}></div>)}
        <div aria-hidden="true" style={s(scrimTopStyle)}></div>
        <div aria-hidden="true" style={s(scrimBotStyle)}></div>
        <div aria-hidden="true" style={s(ditherTopStyle)}></div>
        <div aria-hidden="true" style={s(ditherBotStyle)}></div>

        <div ref={c.docRef} data-noscrollbar="1" onScroll={onScroll} style={s('flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; align-items: center;')}>
          <div aria-hidden="true" style={s(padStyle)}></div>
          {emptySheet && (
            <div style={s('width: 100%; max-width: var(--content-max-width); display: flex; flex-direction: column; gap: 8px; padding: 28px 0 0; margin-left: 0;')}>
              <div style={s('display: flex; flex-direction: column; gap: 8px; padding-left: calc(7ch + 10px); font-size: 11px; color: var(--muted-soft); line-height: 1.6;')}>
                <span>пиши строку — или ⌘↵, чтобы сгенерировать</span>
                <span>## в начале строки — заголовок секции</span>
                {/* подсказка живёт за теми же воротами, что и сам попап */}
                {WORD_POPUP && <span>клик по слову — рифмы, синонимы, антонимы</span>}
              </div>
            </div>
          )}
          {/* строки рисует renderRows() императивно — React в это поддерево не лезет */}
          <div ref={linesRefCb} contentEditable spellCheck={false} onInput={onDocInput} onKeyDown={onDocKey} onClick={onDocClick} style={s('position: relative; width: 100%; max-width: var(--content-max-width); padding: 40px 0; display: flex; flex-direction: column;')}>
          </div>
          <div aria-hidden="true" style={s(padStyle)}></div>
        </div>
      </div>

      {bulkShow && (
        <div style={s('position: absolute; left: 50%; bottom: 172px; transform: translateX(-50%); z-index: 65; display: flex; align-items: center; gap: 14px; background: var(--menu-bg); backdrop-filter: var(--glass-fx); -webkit-backdrop-filter: var(--glass-fx-fallback); contain: paint; isolation: isolate; box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: 10px 14px; font-size: 10.5px; color: var(--muted); white-space: nowrap;')}>
        {/* КНИГА ВЫДЕЛЕННОЙ СТРОКИ (Раунд 57). Одна строка выделена и она из
            корпуса — показываем, откуда, и даём отключить источник прямо
            отсюда. требование: докучающий источник можно отключить отсюда же. */}
        {(function () {
          var от = c.выделеннаяКнига ? c.выделеннаяКнига() : null;
          if (!от) return null;
          return (
            <Fragment>
              <span style={s('color: var(--muted-soft); max-width: 220px; overflow: hidden; text-overflow: ellipsis;')}
                title={от.book}>{от.book}</span>
              <button type="button" onClick={function () { c.отключитьКнигу(от.bookId); }}
                style={s('appearance: none; border: none; background: none; color: var(--muted); font-family: inherit; font-size: 10.5px; cursor: pointer; padding: 0;')}>отключить источник</button>
            </Fragment>
          );
        })()}
          <span style={s('color: var(--ink); font-variant-numeric: tabular-nums;')}>{bulkCount}</span>
          <button onClick={() => c.bulk('fav')} style={s(bulkBtn)}>в избранное</button>
          <button onClick={() => c.bulk('role')} style={s(bulkBtn)}>{bulkRoleLabel}</button>
          <button onClick={() => c.bulk('del')} style={s(bulkBtn)}>удалить</button>
          <button onClick={() => c.setState({ marks: {}, markAnchor: -1 })} style={s('appearance: none; background: none; border: none; padding: 0; font-size: 10.5px; color: var(--muted-soft); cursor: pointer;')} className={hov('color: var(--ink)')}>снять</button>
        </div>
      )}

      {WORD_POPUP && popOpen && (
        <div data-pop="1" data-pa="down" style={s(popStyle)}>
          <div style={s('display: flex; align-items: baseline; gap: 8px; padding: 0 2px 9px;')}>
            <span style={s('font-size: 11px; color: var(--ink);')}>{popWord}</span>
            <span style={s('font-size: 8.5px; color: var(--muted-soft); letter-spacing: 0.1em; text-transform: uppercase;')}>{popHint}</span>
          </div>
          <div style={s('display: flex; gap: 4px; padding-bottom: 9px; flex-wrap: wrap;')}>
            {popTabs.map((t) => (
              <button key={t.name} onClick={t.onPick} style={s(t.style)}>{t.name}</button>
            ))}
          </div>
          <div style={s('display: flex; flex-direction: column; max-height: 214px; overflow-y: auto;')}>
            {popItems.map((w, i) => (w.skel
              ? <div key={i} aria-hidden="true" style={s(skelStyle)}></div>
              : w.head
              ? <div key={i} style={s(popHeadStyle)}>{w.head}</div>
              : <button key={i} onClick={w.onPick} style={s('display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; text-align: left; appearance: none; background: none; border: none; padding: 9px 9px; font-size: 12px; color: var(--muted-hard); cursor: pointer; border-radius: 3px;')} className={hov('background: color-mix(in srgb, var(--ink) 9%, transparent); color: var(--ink)')}><span style={s(w.wStyle)}>{w.w}</span><span style={s('font-size: 9px; color: var(--muted-soft); font-variant-numeric: tabular-nums; flex-shrink: 0;')}>{w.n}</span></button>
            ))}
          </div>
        </div>
      )}

    </div>
  );
}

// ---- статус сохранения и undo/redo для шапки: строки 886..891 шаблона -----
export function renderDocStatus(c) {
  var st = c.state, isFs = st.tab === 'fs';
  var edOnlyStyle = isFs ? 'display: none;' : '';
  var edOnlyFlexStyle = isFs ? 'display: none;' : 'display: flex;';
  var histBtn = function (on) { return 'appearance: none; background: none; border: none; padding: 0; font-size: 13px; line-height: 1; cursor: ' + (on ? 'pointer' : 'default') + '; color: ' + (on ? 'var(--muted)' : 'var(--border-soft)') + ';'; };
  // Ярус сжатия шапки (Раунд 38): со второго яруса «сохранено 12:44» — это
  // просто «12:44». Слово «сохранено» повторяется при каждом сохранении и
  // ничего не добавляет к числу; полная подпись остаётся подсказкой.
  var hdrT = c.hdr ? c.hdr() : 0;
  var savedFull = st.flashMsg ? st.flashMsg : (st.dirty ? 'сохранение…' : (st.savedAt ? 'сохранено ' + st.savedAt : 'черновик'));
  var savedLabel = (hdrT >= 1 && !st.flashMsg && !st.dirty && st.savedAt) ? st.savedAt : savedFull;
  return (
    <>
      <span title={savedFull} style={s(edOnlyStyle + ' flex-shrink: 0; font-size: 10.5px; color: var(--muted-soft); font-variant-numeric: tabular-nums; white-space: nowrap;')}>{savedLabel}</span>
      <div aria-hidden="true" style={s(edOnlyStyle + ' width: 1px; height: 11px; background: var(--border-subtle); flex-shrink: 0;')}></div>
      <div style={s(edOnlyFlexStyle + ' align-items: center; gap: 6px; flex-shrink: 0;')}>
        <button onClick={() => c.undo()} title="Отменить · ⌘Z" style={s((isFs ? 'display: none; ' : '') + histBtn(st.undoN > 0))}>↶</button>
        <button onClick={() => c.redo()} title="Вернуть · ⌘⇧Z" style={s((isFs ? 'display: none; ' : '') + histBtn(st.redoN > 0))}>↷</button>
      </div>
    </>
  );
}
