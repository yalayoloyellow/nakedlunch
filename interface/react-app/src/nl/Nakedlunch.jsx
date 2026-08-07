// nakedlunch v2 — порт дизайна «Editor First» (project-notes/mockups/design-v2/
// Editor First.dc.html). Классовый компонент сознательно: DC-runtime дизайна —
// это React-класс, перенос почти дословный. Здесь скелет фазы 0: state, темы,
// вкладки, попап-система, зерно хрома, первичная загрузка с бэка; render и
// lifecycle собраны интегратором из модулей render.* и methods.* внизу файла.
// Моки дизайна (STANZAS/SYN/ANT/RHYME/POOL/CORPUS_TOTAL и их потребители)
// сюда не переносятся — данные живут на бэке (см. ВСТРАИВАНИЕ.md дизайна).

import { Component, Fragment } from 'react';
import { s, hov, injectBase } from './style.js';
import * as api from './api.js';
import { docMethods } from './methods.doc.js';
import { sheetsMethods } from './methods.sheets.js';
import { panelMethods, genProfileMethods, PARAM_DEFAULTS, DEFAULT_SPEC } from './methods.panels.js';
import { genMethods } from './methods.gen.js';
import { shelfMethods } from './methods.shelves.js';
import { seriesMethods } from './methods.series.js';
import { corpusMethods } from './methods.corpus.js';
import { fsMethods } from './methods.fs.js';
import { fsProfileMethods } from './methods.fsprofiles.js';
import { fsGlueMethods, журнал } from './methods.fsglue.js';
import { fsRecMethods } from './methods.fsrec.js';
import { renderDoc, renderDocStatus } from './render.doc.jsx';
import { renderSheets } from './render.sheets.jsx';
import { renderHeader, renderLegend, renderFlash } from './render.panels.jsx';
import { renderFsStage } from './render.fs.jsx';
import { renderFsBar } from './render.fspanels.jsx';

// корневой div — стили дословно из дизайна (строка 156 шаблона)
const ROOT_STYLE = "height: 100vh; position: relative; --canvas:#131313; --ink:#ededed; --muted-hard:#cfcfcf; --muted:#949494; --muted-soft:#5c5c5c; --border-soft:#3d3d3d; --border-subtle:#242424; --menu-bg:color-mix(in srgb, var(--canvas) 82%, transparent); --content-max-width: min(clamp(620px, 34vw, 780px), calc(100% - 120px)); --radius:6px; --ease:cubic-bezier(0.4,0,0.2,1); --ease-spring:cubic-bezier(0.32,0.72,0,1); font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; background: var(--canvas); color: var(--ink); font-size: 13px; line-height: 1.5; display: flex; flex-direction: column; overflow: hidden; -webkit-font-smoothing: antialiased;";

// SVG-фильтры дизайна (строки 99..154 шаблона): стекло панелей (#nl-warp /
// #nl-warp-aber — applyTheme крутит их scale), кнопочный варп и текстовые
// эффекты хрома; ref-крутилки #nl-text-warp / #nl-postfx подключит фристайл
// в фазе 3 — сами фильтры переносятся целиком, на них ссылаются стили хрома
const SVG_FILTERS = (
  <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true">
    <defs>
      <filter id="nl-warp" x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.006" numOctaves="2" seed="7" result="n"></feTurbulence>
        <feGaussianBlur in="n" stdDeviation="9" result="ns"></feGaussianBlur>
        <feDisplacementMap in="SourceGraphic" in2="ns" scale="11" xChannelSelector="R" yChannelSelector="G"></feDisplacementMap>
      </filter>
      <filter id="nl-warp-btn" x="-30%" y="-30%" width="160%" height="160%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.02" numOctaves="2" seed="3" result="bn"></feTurbulence>
        <feDisplacementMap in="SourceGraphic" in2="bn" scale="8" xChannelSelector="R" yChannelSelector="G"></feDisplacementMap>
      </filter>
      {/* ОБЛАСТЬ ФИЛЬТРА 300% → 150% (Раунд 57) — ЭТО И БЫЛ ФРИЗ СТРОКИ.
          Год повторялся один и тот же отчёт: подвисание на каждом показе текста., «по одному
          слову пробовал — фриз каждую смену», «чем больше слов надо
          прорисовывать, тем сильнее виснет». Я трижды искала это в генераторе и
          в свечении и трижды промахнулась.
          Замер на стенде в том же движке (WKWebView, его профиль: distort 51,
          textBlur 24, glow 104), медиана кадра, в котором сменился текст:
              как было (300%)        1 слово 17 мс · 4 слова 43 · 12 слов 113
              без варпа вовсе        1 слово 16 мс · 4 слова 17 · 12 слов  16
              область 150%           1 слово 16 мс · 4 слова 19 · 12 слов  37
              без свечения (варп на месте)          4 слова 40 · 12 слов 108
          То есть свечение невиновно (108 против 113), а вся цена — feTurbulence,
          который считает шум по области ВДЕВЯТЕРО больше строки и пересчитывает
          её на каждую смену текста. Площадь растёт вместе с числом слов — вот
          откуда «чем больше слов, тем сильнее».
          150% — это 2.25 площади вместо 9. Вид не меняется НИСКОЛЬКО: смещение
          при distort 51 равно 4.25 px (pushFilters: distort/12), то есть дальше
          пары процентов от строки ничего не уезжает, а запас в 25% с каждой
          стороны нужен только чтобы не обрезать ореол blur(4.8px), который в
          этой же цепочке стоит ПЕРЕД варпом. */}
      <filter id="nl-text-warp" x="-25%" y="-25%" width="150%" height="150%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.008 0.02" numOctaves="2" seed="5" result="tn"></feTurbulence>
        <feDisplacementMap in="SourceGraphic" in2="tn" scale="0" xChannelSelector="R" yChannelSelector="G"></feDisplacementMap>
      </filter>
      {/* ХРОМАТИКУ НЕ ТРОГАЮ (Раунд 57), хотя она дороже соседа: у неё ТРИ
          feDisplacementMap плюс feGaussianBlur. Причина — смещение здесь не
          4 px, а до восьмидесяти (pushFilters: distort*0.6 плюс кайма от
          taber), и никакая доля от строки его не покроет гарантированно: обрежу
          область — обрежу кайму, а это видно сразу. Она включается только при
          taber > 0; станет заметно тормозить — считать область в пикселях через
          filterUnits="userSpaceOnUse", а не долей от строки. */}
      <filter id="nl-text-warp-aber" x="-100%" y="-100%" width="300%" height="300%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.01" numOctaves="1" seed="7" result="tanRaw"></feTurbulence>
        <feGaussianBlur in="tanRaw" stdDeviation="9" result="tan"></feGaussianBlur>
        <feDisplacementMap in="SourceGraphic" in2="tan" scale="0" xChannelSelector="R" yChannelSelector="G" result="tr"></feDisplacementMap>
        <feColorMatrix in="tr" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="tmr"></feColorMatrix>
        <feDisplacementMap in="SourceGraphic" in2="tan" scale="0" xChannelSelector="R" yChannelSelector="G" result="tg"></feDisplacementMap>
        <feColorMatrix in="tg" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="tmg"></feColorMatrix>
        <feDisplacementMap in="SourceGraphic" in2="tan" scale="0" xChannelSelector="R" yChannelSelector="G" result="tb"></feDisplacementMap>
        <feColorMatrix in="tb" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="tmb"></feColorMatrix>
        <feBlend in="tmr" in2="tmg" mode="screen" result="tmrg"></feBlend>
        <feBlend in="tmrg" in2="tmb" mode="screen"></feBlend>
      </filter>
      <filter id="nl-postfx" x="-60%" y="-60%" width="220%" height="220%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.01" numOctaves="1" seed="11" result="pn"></feTurbulence>
        <feDisplacementMap in="SourceGraphic" in2="pn" scale="0" xChannelSelector="R" yChannelSelector="G"></feDisplacementMap>
      </filter>
      <filter id="nl-postfx-aber" x="-60%" y="-60%" width="220%" height="220%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.01" numOctaves="1" seed="11" result="an"></feTurbulence>
        <feDisplacementMap in="SourceGraphic" in2="an" scale="0" xChannelSelector="R" yChannelSelector="G" result="ar"></feDisplacementMap>
        <feColorMatrix in="ar" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="mr"></feColorMatrix>
        <feDisplacementMap in="SourceGraphic" in2="an" scale="0" xChannelSelector="R" yChannelSelector="G" result="ag"></feDisplacementMap>
        <feColorMatrix in="ag" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="mg"></feColorMatrix>
        <feDisplacementMap in="SourceGraphic" in2="an" scale="0" xChannelSelector="R" yChannelSelector="G" result="ab"></feDisplacementMap>
        <feColorMatrix in="ab" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="mb"></feColorMatrix>
        <feBlend in="mr" in2="mg" mode="screen" result="mrg"></feBlend>
        <feBlend in="mrg" in2="mb" mode="screen"></feBlend>
      </filter>
      <filter id="nl-warp-aber" x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
        <feTurbulence type="fractalNoise" baseFrequency="0.006" numOctaves="2" seed="7" result="wn"></feTurbulence>
        <feGaussianBlur in="wn" stdDeviation="9" result="wns"></feGaussianBlur>
        <feDisplacementMap in="SourceGraphic" in2="wns" scale="8" xChannelSelector="R" yChannelSelector="G" result="wr"></feDisplacementMap>
        <feColorMatrix in="wr" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="wmr"></feColorMatrix>
        <feDisplacementMap in="SourceGraphic" in2="wns" scale="11" xChannelSelector="R" yChannelSelector="G" result="wg"></feDisplacementMap>
        <feColorMatrix in="wg" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="wmg"></feColorMatrix>
        <feDisplacementMap in="SourceGraphic" in2="wns" scale="15" xChannelSelector="R" yChannelSelector="G" result="wb"></feDisplacementMap>
        <feColorMatrix in="wb" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="wmb"></feColorMatrix>
        <feBlend in="wmr" in2="wmg" mode="screen" result="wmrg"></feBlend>
        <feBlend in="wmrg" in2="wmb" mode="screen"></feBlend>
      </filter>
    </defs>
  </svg>
);

// ---------------------------------------------------------------------------
// ПОСЛЕ ПАДЕНИЯ — ОДИН ВОПРОС, ОДНА КНОПКА (Раунд 59).
//
// Прошлый запуск закончился аварийно: об этом знает журнал, и это единственный
// момент, когда человека уместно потревожить — он всё равно уже столкнулся с
// тем, что программа закрылась сама.
//
// Полоса, а не окно: работать она не мешает и закрывается одним нажатием. И
// закрывается НАСОВСЕМ для этого случая: спрашивать дважды об одном падении
// значит превратить заботу в назойливость.
function renderАвария(c) {
  return (
    <div style={s('position: fixed; left: 0; right: 0; top: 0; z-index: 998; display: flex; '
      + 'align-items: center; justify-content: center; gap: 10px; padding: 8px 14px; '
      + 'background: #e05252; color: #fff; font-size: 11px;')}>
      <span>Прошлый запуск закрылся сам. Причина записана — отправь отчёт, и это починят.</span>
      <button onClick={function () { c.сохранитьЛог(); c.setState({ логАвария: false }); }}
        style={s('appearance: none; border: 1px solid rgba(255,255,255,.6); border-radius: 999px; '
          + 'padding: 4px 12px; font-family: inherit; font-size: 11px; cursor: pointer; '
          + 'background: none; color: #fff;')}>сохранить отчёт</button>
      <button onClick={function () { c.setState({ логАвария: false }); }}
        style={s('appearance: none; border: none; background: none; color: rgba(255,255,255,.75); '
          + 'font-family: inherit; font-size: 11px; cursor: pointer;')}>позже</button>
    </div>
  );
}


// ---------------------------------------------------------------------------
// ЯДРО МОЛЧИТ (Раунд 59).
//
// Программа состоит из окна и ядра. Ядро может умереть отдельно — от нехватки
// памяти на сборке индексов, от убитого процесса, от чего угодно. Окно при этом
// остаётся на экране и выглядит рабочим: кнопки нажимаются, ничего не
// происходит, объяснения нет нигде. Хуже такого отказа только молчаливый.
//
// Панель показывает состояние прямо, а копирует то, что знает САМО ОКНО:
// сервера уже нет, спросить у него отчёт невозможно, и единственный источник —
// местная копия журнала (см. main.jsx).
function renderЯдроМолчит(c) {
  var копировать = async function (e) {
    var т = ['nakedlunch · ядро не отвечает',
             'время: ' + new Date().toLocaleString('ru'),
             'окно: ' + navigator.userAgent, '',
             '--- последнее, что видело окно ---'].concat(window.__журналОкна || []).join('\n');
    try { await navigator.clipboard.writeText(т); e.target.textContent = 'скопировано ✓'; }
    catch (err) {
      var ta = document.createElement('textarea');
      ta.value = т; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); e.target.textContent = 'скопировано ✓'; }
      catch (err2) { e.target.textContent = 'скопировать не вышло'; }
      document.body.removeChild(ta);
    }
  };
  return (
    <div style={s('position: fixed; inset: 0; z-index: 999; display: flex; align-items: center; '
      + 'justify-content: center; background: rgba(0,0,0,.82); backdrop-filter: blur(3px);')}>
      <div style={s('max-width: 520px; padding: 26px 24px; border-radius: 12px; '
        + 'background: var(--panel); border: 1px solid var(--border-subtle); text-align: left;')}>
        <div style={s('font-size: 13px; color: var(--ink); margin-bottom: 8px;')}>Ядро не отвечает</div>
        <div style={s('font-size: 11px; line-height: 1.6; color: var(--muted); margin-bottom: 16px;')}>
          Часть программы, которая считает, перестала отвечать. Окно живо, но
          сделать оно сейчас ничего не может.<br /><br />
          Закрой и открой программу заново — журнал этой сессии сохранится, и в
          следующий раз он будет в настройках, во вкладке «Лог».
        </div>
        <button onClick={копировать}
          style={s('appearance: none; border: 1px solid var(--border-subtle); border-radius: 999px; '
            + 'padding: 8px 16px; font-family: inherit; font-size: 11px; cursor: pointer; '
            + 'background: none; color: var(--ink);')}
          className={hov('background: var(--ink); color: var(--canvas)')}>скопировать, что известно</button>
      </div>
    </div>
  );
}


export default class Nakedlunch extends Component {
  // state — дословно из дизайна; fs-ключи (micOn/bcOn/camOn/fsv/...) — фаза 3.
  // Отличия интегратора: doc стартует одной пустой строкой (иначе в contenteditable
  // нет поля [data-idx] и печатать некуда — тот же фолбэк, что в readDom);
  // params — PARAM_DEFAULTS из methods.panels.js: пять крутилок, «Метр» удалён,
  // дефолты производны от бэка (решение прожарки 5), моковые числа макета не переносятся
  state = { doc: [{ type: 'line', text: '', letter: 'а', src: 'я' }], mode: 'gen', tab: 'editor', micOn: false, trackOn: false, synthWanted: true, synthOn: true /* синтетика водит картинку, пока нет ни микрофона, ни трека — см. freestyle/audio.js */, bcOn: true, bcEpoch: 0 /* счётчик перезапусков движка — пересоздаёт канвас, см. methods.fsglue.fsRestartEngine */, autoOn: false, bcAutoOn: false, bcAutoSec: 30, recOn: false, recLock: false /* фаза 4: замок хрома на время записи — панели не проявляются даже по наведению */, textAber: false, postAber: false, aspect: '', profiles: [], profId: '', profEdit: '', uiProfiles: [], uiProfId: '', srcMode: 'генератор', srcText: '', srcChunk: 'строки', camOn: false, fitFrame: false, grainBlend: 'overlay', grainFps: 24, posX: 'по центру', posY: 'по центру', camId: '', camList: [], camBlend: 'normal', camFit: 'заполнить', camMirror: false, glowColor: '', glowWarp: 'чисто', selMode: 'нет', fsv: {}, /* СВОИ НАСТРОЙКИ ФРИСТАЙЛА (Раунд 57). До этого он падал на панель редактора: linkKnobs(0)/linkSpec(0) последней ступенью читают state.knobMode/params/curSpec(), а тема бралась из _lastKey — ключа последней генерации В РЕДАКТОРЕ. Крутил строфу — менял сцену. null = ещё не отделялся, значит наследуем текущее редакторское один раз. */ fsTheme: '', fsKnobMode: null, fsParams: null, fsSpec: null, acMode: 'выкл', grainMode: 'плёнка', fonts: [], fontNow: '', fontQ: '', pal: null, palSel: { panel: 0, ink: 0 }, fsSetOpen: false, fsLineOpen: false, fsTab: 'cam', live: {}, presetTab: 'all', presetQ: '', presetTick: 0, defProf: '', uiDefProf: '', uiProfEdit: '', pop: null, popTab: 'рифмы', popItems: [], popLoading: false /* фаза 2: список попапа и его скелет */, thesaurus: { syn: false, ant: false } /* словарные слои — придут из /api/state в boot; до тех пор «антонимы» честно спрятаны */, undoN: 0, redoN: 0, savedAt: '', caret: -1, dirty: false, selAll: false, flashMsg: '', sheets: [], sheetId: '', srcBusy: {} /* какие источники сейчас переключаются — Раунд 56 */, importing: [] /* книги, которые заливаются прямо сейчас */, renaming: '', trashView: false, confirm: '', folders: [], folderId: '', folderDraft: '', moveOpen: '', marks: {}, markAnchor: -1, titleEdit: false, openPill: '', algo: 'Алгоритм', seed: '', theme: 'dark', cfg: {}, favs: [], hist: [], /* Цепочка из ОДНОГО звена — это и есть одиночная строфа (Раунд 50). Раньше по умолчанию стояли шесть ролей, а форм у них не было ни одной: все шесть звеньев молча падали в одну и ту же строфу настроек. */ chain: [''], junctions: [], chainForms: [null], chainKnobs: [null], chainRepeat: [null],
    /* Раунд 50: три полки. knobForms/chainList приезжают в boot; knobProfile —
       выбранный профиль настроек, knobMode — его режим, knobDirty — «правлено,
       но не сохранено» (молча писать в полку нельзя: тогда выбранное решение
       менялось бы под руками, а от этого слепки цепочек и защищают). */
    knobForms: { builtin: [], custom: [] }, chainList: [],
    /* четвёртая полка (Раунд 53): серия = список звеньев {альбом, тема, цепочка, сколько} */
    seriesList: [], seriesName: '', seriesLinks: [], seriesDraft: '', seriesSec: 15,
    /* seriesState (Раунд 55) — сколько СДЕЛАНО по каждому треку, какой идёт
       и где что встало. Приходит с бэка из ФАЙЛОВ: меню не помнит прогонов
       и потому не может о них соврать. */
    seriesState: null,
    /* искажение — свойство ВСЕЙ серии (Раунд 55): ось кривой это место в
       серии, и лежать оно может только здесь. seriesCurve — точки по
       каналам, seriesNoise — сила шума, curveChan — какой канал гнём. */
    seriesCurve: {}, seriesNoise: 0, noiseKind: 'белый', curveChan: 'все', curveShape: '',
    knobProfile: 'Обычный', knobMode: 'алгоритм', knobDirty: false,
    /* profile ПУСТОЙ на старте (Раунд 55). Здесь стояло 'Куплет-припев' —
       имя пресета из шести звеньев при живой цепочке из одного пустого:
       boot его не применял, и при каждом первом запуске панель показывала
       решение, которого нет. */
    knobDraft: '', chainDraft: '', chipOpen: -1, juncOpen: -1, profile: '', myProfN: 0, savedSnap: '', saveFlash: false, params: Object.assign({}, PARAM_DEFAULTS),
    // профиль генерации: схема строфы + её имя (boot поднимает из /api/settings),
    // stanzaPick — открыт ли список форм внутри попапа, profNameDraft — поле имени
    // stanzaSection (Раунд 55) — заголовок, который одиночная генерация кладёт
    // над строфой. Раньше он брался у первого звена ЦЕПОЧКИ — чужого этажа.
    stanzaSpec: null, stanzaProfile: '', stanzaPick: false, stanzaSection: '', themeKeys: '', profNameDraft: '', profSaveFlash: false,
    // ярус сжатия шапки, 0..HDR_MAX; считает hdrFit по фактической ширине
    hdrTier: 0,
    // Раунд 39: фоновые работы (/api/status) и всё, что вернулось из потерянных
    // функций — корпус, сроки хранения, возврат показанного (methods.corpus.js)
    jobs: [], corpusBusy: '', histRetention: 0, nlRetention: 'never', restoreTheme: '', cfgTab: 'документ',
    // Раунд 40: полноценные избранное и история — поиск, правка, отмена
    favQ: '', histQ: '', favEdit: '', favUndo: '', histCfg: false, statsData: null, funnel: null, black: null, blackDraft: '',
    // poolPer и pipeW вырезаны (Раунд 51, поймано тестом утечки профиля сцены):
    // размер пула выводится из длины цепочки и решения пользователя не требует, а
    // веса склейки вернулись константами модуля (core/pipeline.py) — обе ручки
    // ушли из контракта ещё в Раунде 50, но в состоянии остались висеть.
    // референс как вход пайплайна (Раунд 45)
    /* refOpen (Раунд 55) — референс свёрнут в строку меню «Пайплайн»: берутся
       за него редко, а места он занимает много */
    refText: '', refPct: 1, refChain: null, refProfile: null, refBusy: false, refOpen: false };

  DARK = { '--canvas': '#131313', '--ink': '#ededed', '--muted-hard': '#cfcfcf', '--muted': '#949494', '--muted-soft': '#5c5c5c', '--border-soft': '#3d3d3d', '--border-subtle': '#242424' };
  LIGHT = { '--canvas': '#ffffff', '--ink': '#101010', '--muted-hard': '#222222', '--muted': '#555555', '--muted-soft': '#999999', '--border-soft': '#c8c8c8', '--border-subtle': '#e0e0e0' };
  // Заголовки секций — ТОЛЬКО подписи в документе (Раунд 50). До этого раунда
  // роль тайно выбирала форму строфы и двигала крутилки на бэке.
  ROLES = ['Куплет', 'Припев', 'Хук', 'Бридж', 'Строфа'];
  JMARK = { 'рифмовать стык': '·', 'свободно': '∘', 'слом ритма': '≀' };
  // Пресеты цепочек: пары «заголовок секции + форма строфы». Раньше это были
  // списки одних ролей, и выбор пресета СНОСИЛ все формы звеньев — цепочка
  // собиралась из слов, за которыми не стояло ничего. Формы взяты с полки
  // строф: куплет повествовательным перекрёстным, припев — плотным парным
  // покороче, хук — двустишием, бридж — кольцевым (кольцо ломает инерцию абаб).
  LETTERS = 'абвгдежзиклмноп';
  TABS = ['рифмы', 'по звуку', 'синонимы', 'антонимы', 'строкой'];

  // ---- refs ----
  rootRef = (el) => { this._root = el; this.applyTheme(); };
  sectionRef = (el) => { this._sec = el; };
  bgRef = (el) => { this._bg = el; };
  docRef = (el) => { this._doc = el; };
  inputRef = (el) => { this._input = el; };

  // ---- вид: тема, тонирование, свечение, стекло ----
  cfg() { return Object.assign({}, this.props, this.state.cfg || {}); }
  // текущий вид переживает перезапуск: cfg целиком уезжает в nl_view
  // (api.settingsSet, дебаунс 600 мс внутри saveViewSoon) — решение прожарки 11
  setCfg(k, v) { var c = Object.assign({}, this.state.cfg || {}); c[k] = v; this.setState({ cfg: c }); this.saveViewSoon(); }
  resetCfg() { this.setState({ cfg: {} }); this.saveViewSoon(); }
  applyTheme() {
    var el = this._root; if (!el) return;
    // во фристайле хром следует выбранной теме, как и в редакторе
    var C = this.cfg(), pal = this.state.theme === 'light' ? this.LIGHT : this.DARK;
    for (var k in pal) el.style.setProperty(k, pal[k]);
    el.style.fontFamily = "'" + (C.uiFont || 'JetBrains Mono') + "', ui-monospace, Menlo, monospace";
    // тон красит весь текст: и основной, и приглушённые оттенки, и границы
    if (C.uiTint && C.uiTint !== 'нет' && /^#/.test(C.uiTint)) {
      el.style.setProperty('--ink', C.uiTint);
      el.style.setProperty('--muted-hard', 'color-mix(in srgb, ' + C.uiTint + ' 78%, var(--canvas))');
      el.style.setProperty('--muted', 'color-mix(in srgb, ' + C.uiTint + ' 58%, var(--canvas))');
      el.style.setProperty('--muted-soft', 'color-mix(in srgb, ' + C.uiTint + ' 36%, var(--canvas))');
      el.style.setProperty('--border-soft', 'color-mix(in srgb, ' + C.uiTint + ' 24%, var(--canvas))');
      el.style.setProperty('--border-subtle', 'color-mix(in srgb, ' + C.uiTint + ' 13%, var(--canvas))');
    }
    // свечение интерфейса: тень наследуется всем текстом, поэтому это дёшево
    // фосфор: ореол в цвете самой строки, поэтому серый текст не выцветает и не «плывёт»
    var ug = Math.max(0, Math.min(100, parseFloat(C.uiGlow) || 0));
    // ореол плотный и короткий: длинный радиус на полупрозрачном тексте читается как размытие
    var glowOn = ug > 0 && this.state.tab !== 'fs';
    var shadow = glowOn ? '0 0 ' + (ug * 0.035) + 'px currentColor, 0 0 ' + (ug * 0.11) + 'px currentColor' : 'none';
    el.style.textShadow = glowOn ? shadow : '';
    // наследования мало: у части узлов свой text-shadow, поэтому раздаём правилом всем потомкам
    el.style.setProperty('--ui-text-glow', shadow);
    if (glowOn) el.setAttribute('data-ui-glow', '1'); else el.removeAttribute('data-ui-glow');
    el.style.setProperty('--ui-glow', glowOn
      ? 'drop-shadow(0 0 ' + (ug * 0.04) + 'px currentColor) drop-shadow(0 0 ' + (ug * 0.12) + 'px currentColor)' : 'none');
    var uc = Math.max(60, Math.min(180, parseFloat(C.uiContrast) || 100));
    var ue = Math.max(40, Math.min(220, parseFloat(C.uiExpo) || 100));
    var fx = (uc !== 100 ? 'contrast(' + uc + '%) ' : '') + (ue !== 100 ? 'brightness(' + ue / 100 + ')' : '');
    el.style.filter = fx && this.state.tab !== 'fs' ? fx.trim() : '';
    var mf = C.menuFill || 'стекло', ma = Math.max(40, Math.min(100, parseFloat(C.menuAlpha) || 82));
    el.style.setProperty('--menu-bg', mf === 'плотная' ? 'var(--canvas)' : 'color-mix(in srgb, var(--canvas) ' + ma + '%, transparent)');
    var gb = parseFloat(C.glassBlur != null ? C.glassBlur : 7), gw = parseFloat(C.glassWarp != null ? C.glassWarp : 11);
    if (isNaN(gb)) gb = 7; if (isNaN(gw)) gw = 11;
    var aber = C.glassAber === 'да';
    el.style.setProperty('--glass-fx', (gw > 0 ? 'url(#nl-warp' + (aber ? '-aber' : '') + ') ' : '') + 'blur(' + gb + 'px) saturate(185%) brightness(1.05)');
    el.style.setProperty('--glass-fx-fallback', 'blur(' + (gb + 3) + 'px) saturate(185%) brightness(1.05)');
    var wf = document.querySelector('#nl-warp feDisplacementMap');
    if (wf) wf.setAttribute('scale', String(gw));
    var ga = document.querySelectorAll('#nl-warp-aber feDisplacementMap');
    for (var gi = 0; gi < ga.length; gi++) ga[gi].setAttribute('scale', String(gw * [0.7, 1, 1.38][gi]));
    var cw = {
      'узкая': 'min(clamp(620px, 34vw, 780px), calc(100% - 120px))',
      'средняя': 'min(clamp(900px, 45vw, 1100px), calc(100% - 120px))',
      'широкая': 'min(clamp(1080px, 62vw, 1400px), calc(100% - 80px))'
    };
    el.style.setProperty('--content-max-width', cw[C.colWidth] || cw['узкая']);
  }
  toggleTheme() { this.setState({ theme: this.state.theme === 'light' ? 'dark' : 'light' }); }

  // ---- вкладки ----
  // бегунок вкладок: ширину и место снимаем с активной кнопки, первый замер без анимации
  tabsRef = (el) => { this._tabs = el; if (el) { this.moveTabInd(); setTimeout(() => this.moveTabInd(), 0); } };

  // ---- шапка: ярус сжатия (Раунд 38) ----
  // Поле класса, а не метод: новая функция на каждый рендер заставляла бы React
  // дёргать ref(null)/ref(el) каждый кадр и пересоздавать ResizeObserver.
  // Наблюдаем саму шапку, а не окно: ширина шапки меняется и от боковых
  // панелей, не только от размера окна.
  hdrRef = (el) => {
    if (this._hdrObs) { this._hdrObs.disconnect(); this._hdrObs = null; }
    this.statusStop();
    this._hdrEl = el;
    if (!el) return;
    if (typeof ResizeObserver === 'function') {
      this._hdrObs = new ResizeObserver(() => this.hdrFit());
      this._hdrObs.observe(el);
    }
    this.hdrFit();
  };
  moveTabInd() {
    var nav = this._tabs; if (!nav) return;
    var ind = nav.querySelector('[data-tab-ind]');
    var btn = nav.querySelector('button[data-tab="' + (this.state.tab === 'fs' ? 'fs' : 'editor') + '"]');
    if (!ind || !btn || !btn.offsetWidth) return;
    ind.style.transition = this._tabInd ? 'transform 320ms var(--ease-spring), width 320ms var(--ease-spring)' : 'none';
    ind.style.width = btn.offsetWidth + 'px';
    ind.style.transform = 'translateX(' + btn.offsetLeft + 'px)';
    this._tabInd = true;
  }
  setTab(t) {
    if (t === this.state.tab) return;
    this.openPop({ tab: t, pop: null, marks: {} });
    if (t === 'fs') { this._kicked = false; this._fsSeeded = false; this.enterFs(); }
  }
  // enterFs/loadEngine/syncEngine живут в methods.fsglue.js (связка со сценой,
  // движком и аудио-графом), профили сцены — в methods.fsprofiles.js

  // ---- зерно хрома: живой покадровый шум поверх интерфейса ----
  uiGrainRef = (el) => { this._uiGrain = el; this.uiGrainLoop(); };
  // живое зерно интерфейса: тот же покадровый шум, что на сцене, но мелкий и дешёвый
  uiGrainLoop() {
    if (this._uiRAF) return;
    var self = this;
    var tick = function (ts) {
      self._uiRAF = requestAnimationFrame(tick);
      var c = self._uiGrain, C = self.cfg();
      if (!c || self.state.tab === 'fs') return;
      var g = Math.max(0, Math.min(100, parseFloat(C.uiGrain) || 0));
      if (!g) return;
      var fpsRaw = C.uiGrainFps || '24', fps = fpsRaw === 'без предела' ? 0 : parseInt(fpsRaw, 10) || 24;
      if (fps > 0) {
        var step = 1000 / fps;
        if (self._uiT && ts - self._uiT < step) return;
        self._uiT = ts;
      }
      var w = Math.max(8, Math.round(window.innerWidth / 3)), h = Math.max(8, Math.round(window.innerHeight / 3));
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; self._uiImg = null; }
      var ctx = c.getContext('2d');
      if (!ctx) return;
      if (!self._uiImg) { self._uiImg = ctx.createImageData(w, h); self._uiBuf = new Uint32Array(self._uiImg.data.buffer); }
      self.fillNoise(self._uiBuf, 60, false);
      ctx.putImageData(self._uiImg, 0, 0);
    };
    this._uiRAF = requestAnimationFrame(tick);
  }
  fillNoise(buf, amp, chroma) {
    if (!buf) return;
    var n = buf.length, cl = function (x) { return x < 0 ? 0 : x > 255 ? 255 : x | 0; };
    for (var i = 0; i < n; i++) {
      var v = cl(128 + (Math.random() * 2 - 1) * amp);
      buf[i] = chroma
        ? (255 << 24) | (cl(128 + (Math.random() * 2 - 1) * amp) << 16) | (cl(128 + (Math.random() * 2 - 1) * amp) << 8) | v
        : (255 << 24) | (v << 16) | (v << 8) | v;
    }
  }

  clock() { var d = new Date(); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }

  // ---- попап-система ----
  // открытие гасит всё остальное и снимает висящее закрытие
  openPop(patch) {
    clearTimeout(this._popT); this._popT = null;
    clearTimeout(this._subT); this._subT = null;
    this.setState(Object.assign({ openPill: '', fsSetOpen: false, fsLineOpen: false, chipOpen: -1, juncOpen: -1, closing: '', subPill: '', subClosing: '' }, patch || {}));
  }
  // Меню внутри панели (профиль, фильтры, воронка, роль звена) живут на своём уровне.
  // Если пустить их через openPill, открытие любого из них закрывает панель-родителя —
  // именно поэтому в пайплайне «ничего не нажималось».
  togSub(p) {
    if (this.state.subPill === p) { this.closeSub(); return; }
    clearTimeout(this._subT); this._subT = null;
    this.setState({ subPill: p, subClosing: '', chipOpen: -1, juncOpen: -1 });
  }
  openSub(patch) {
    clearTimeout(this._subT); this._subT = null;
    this.setState(Object.assign({ subPill: '', subClosing: '' }, patch || {}));
  }
  closeSub() {
    var st = this.state, self = this;
    var k = st.subPill || (st.chipOpen >= 0 ? 'chip' : '') || (st.juncOpen >= 0 ? 'junc' : '');
    if (!k || this._subT) return;
    this.setState({ subClosing: k });
    this._subT = setTimeout(function () {
      self._subT = null;
      self.setState({ subPill: '', subClosing: '', chipOpen: -1, juncOpen: -1 });
    }, 140);
  }
  // закрытие: состояние держим ещё кадр анимации, потом гасим по-настоящему
  closePop(extra) {
    var st = this.state, self = this;
    if (extra) this.setState(extra);
    this.closeSub();
    var k = st.openPill || (st.fsSetOpen ? 'fsset' : '') || (st.fsLineOpen ? 'fsline' : '')
      || (st.chipOpen >= 0 ? 'chip' : '') || (st.juncOpen >= 0 ? 'junc' : '');
    if (!k || this._popT) return;
    this.setState({ closing: k });
    this._popT = setTimeout(function () {
      self._popT = null;
      self.setState({ openPill: '', fsSetOpen: false, fsLineOpen: false, chipOpen: -1, juncOpen: -1, closing: '', subPill: '', subClosing: '' });
    }, 140);
  }

  // ---- документ: текст и копирование ----
  // текущий документ; рабочий буфер _doc$ появится с миксином редактора
  cur() { return this._doc$ || this.state.doc; }
  // текст документа: полноценный markdown
  docText() {
    var out = [];
    this.cur().forEach(function (r, i) {
      if (r.type === 'role') { if (i) out.push(''); out.push('#'.repeat(r.level || 2) + ' ' + r.text); }
      else out.push(r.text);
    });
    return out.join('\n');
  }
  inDoc(node) { return !!(this._doc && node && this._doc.contains(node.nodeType === 1 ? node : node.parentNode)); }
  copyAll() {
    var txt = this.docText(), self = this, n = this.cur().filter(function (r) { return r.type === 'line'; }).length;
    var done = function (ok) { self.setState({ savedAt: self.state.savedAt, dirty: false }); self.flash(ok ? ('скопировано · ' + n + ' строк') : 'не удалось скопировать'); };
    try {
      var p = navigator.clipboard && navigator.clipboard.writeText(txt);
      if (p && p.then) { p.then(function () { done(true); }, function () { done(self.fallbackCopy(txt)); }); return; }
    } catch (e) {}
    done(this.fallbackCopy(txt));
  }
  fallbackCopy(txt) {
    try {
      var ta = document.createElement('textarea');
      ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      var ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (e) { return false; }
  }
  flash(msg) {
    var self = this;
    clearTimeout(this._flashMsgT);
    this.setState({ flashMsg: msg });
    this._flashMsgT = setTimeout(function () { self.setState({ flashMsg: '' }); }, 2000);
  }
  onGlobalKey(e) {
    var mod = e.metaKey || e.ctrlKey;
    if (e.key === 'Escape') { this.closePop({ pop: null, selAll: false, marks: {} }); return; }
    // ⌥↵ без ⌘ — строфа с обязательным ключом (решение прожарки, вопрос 2.1)
    if (!mod && e.altKey && e.key === 'Enter') { e.preventDefault(); this.genStanza({ forced: true }); return; }
    if (!mod) return;
    var k = e.key.toLowerCase(), sel = getSelection();
    var inside = this.inDoc(document.activeElement) || (sel && sel.focusNode && this.inDoc(sel.focusNode));
    if (k === 'a' && inside) { e.preventDefault(); this.setState({ selAll: true }); return; }
    if (inside && (k === 'b' || k === 'i')) { e.preventDefault(); this.wrapSel(k === 'b' ? '**' : '*'); return; }
    if (inside && (k === '1' || k === '2' || k === '3')) { e.preventDefault(); this.toggleHeading(parseInt(k, 10) + 1); return; }
    if (k === 'c') {
      var native = sel && String(sel).length > 0;
      if (this.state.selAll || (inside && !native)) { e.preventDefault(); this.copyAll(); this.setState({ selAll: false }); }
      return;
    }
    if (k === 'z') { e.preventDefault(); if (e.shiftKey) this.redo(); else this.undo(); }
    // ⌘↵ строфа в каретку, ⌘⇧↵ прогон пайплайна, ⌥ — принудительный показ ключа (решения прожарки 1–2)
    else if (e.key === 'Enter') { e.preventDefault(); if (e.shiftKey) this.runPipe(); else this.genStanza({ forced: e.altKey }); }
  }

  // ---- первичная загрузка ----
  // всё параллельно; каждая ошибка — flash и пустое значение, приложение живёт
  async boot() {
    var errs = [];
    var grab = function (p) { return p.catch(function (e) { errs.push(e && e.message ? e.message : String(e)); return null; }); };
    const [st, nl, settings, forms, hist, sh, knobs, chains, ser] = await Promise.all([
      grab(api.state()),
      grab(api.nlState()),
      grab(api.settingsGet()),
      grab(api.stanzaProfiles()),
      grab(api.history('')),
      grab(api.sheetsList()),
      // Раунд 50: полка профилей настроек и полка цепочек-слепков
      grab(api.knobProfiles()),
      grab(api.chains()),
      grab(api.series()),
    ]);
    this.setState({
      // /api/state отдаёт accepted — плоский список строк избранного, новые сверху;
      // внутри приложения избранное живёт объектами {t} (методы документа сравнивают f.t)
      favs: (st && st.accepted ? st.accepted : []).map(function (t) { return typeof t === 'string' ? { t: t } : t; }),
      // история: показанное построчно, {time, t} — как ждёт панель истории дизайна
      // подпись времени — одним местом (histRow миксина корпуса): сегодняшнее
      // часами, прежнее датой
      hist: hist && hist.items ? hist.items.map((h) => this.histRow(h)) : [],
      sheets: sh && sh.sheets ? sh.sheets : [],
      folders: sh && sh.folders ? sh.folders : [],
      // решение прожарки 9: наличие словарных слоёв тезауруса — попап прячет
      // вкладку «антонимы» при ant=false (скрыть честнее, чем фейкать); дефолт
      // «слоёв нет» покрывает и старый бэк без поля thesaurus
      thesaurus: st && st.thesaurus ? st.thesaurus : { syn: false, ant: false },
      // сырые ответы бэка — их разложат миксины панелей (воронка, крутилки, конструктор строф)
      corpus: st ? st.corpus : null,
      nl: nl,
      settings: settings,
      stanzaForms: forms,
      // Раунд 50: две новые полки. Форма ответа у обеих такая же, как у
      // строф, — {builtin, custom} и {custom}: три полки, одна привычка.
      knobForms: knobs || { builtin: [], custom: [] },
      // встроенные цепочки — такие же записи полки (Раунд 55): три «пресета»
      // жили константой во фронте, серия их не видела, и «три готовых пайплайна на экране, пустой список в серии»
      chainList: ((chains && chains.builtin) || []).concat((chains && chains.custom) || []),
      chainMine: ((chains && chains.custom) || []).map(function (c) { return c.name; }),
      seriesList: (ser && ser.custom) || [],
      seriesSec: (ser && ser.seconds_per_text) || 15,
      // профиль генерации поднимаем из настроек (2026-08-02). Раньше схема
      // читалась из settings.stanza только в момент генерации, а показать или
      // сменить её было нечем; крутилки не восстанавливались вовсе.
      stanzaSpec: (settings && Array.isArray(settings.stanza) && settings.stanza.length)
        ? settings.stanza : DEFAULT_SPEC.map(function (l) { return Object.assign({}, l); }),
      stanzaProfile: (settings && settings.stanza_profile) || '',
      // последние положения панели: окно открывается там, где его закрыли.
      // Раунд 50: сюда же поднимается РЕЖИМ (алгоритм/классика) — раньше он не
      // сохранялся вовсе (белый список _PROFILE_PARAMS его не пропускал), и
      // переключатель сбрасывался при каждом запуске.
      params: Object.assign({}, PARAM_DEFAULTS,
        (settings && settings.nl_params && settings.nl_params.params) || {}),
      knobMode: (settings && settings.nl_params && settings.nl_params.mode) || 'алгоритм',
      // живая цепочка меню «Пайплайн» — где закрыл, там открыл (Раунд 55)
      ...(function (ц) {
        if (!ц || !Array.isArray(ц.chain) || !ц.chain.length) return {};
        var n = ц.chain.length;
        var добить = (a) => { a = Array.isArray(a) ? a.slice(0, n) : []; while (a.length < n) a.push(null); return a; };
        return { chain: ц.chain, chainForms: добить(ц.forms), chainKnobs: добить(ц.knobs),
                 chainRepeat: добить(ц.repeat), junctions: Array.isArray(ц.junctions) ? ц.junctions : [],
                 profile: ц.profile || '' };
      })(settings && settings.nl_chain),
    }, () => {
      // профили сцены и вида, палитра и текущий вид (nl_fs_profiles /
      // nl_ui_profiles / nl_palette / nl_view) лежат в тех же /api/settings —
      // bootFsSettings разложит их по состоянию и поднимет вид, затем сцену
      this.bootFsSettings();
    });
    // сроки хранения (история и «использованное» nakedlunch) — отдельными
    // роутами, поэтому не в общем Promise.all: их отсутствие не должно ронять
    // загрузку всего остального
    this.loadRetention();
    if (errs.length) this.flash(errs[0]);
    // первый живой лист — в редактор; метод openSheet придёт миксином.
    // Пустое хранилище → лист создаётся сразу: иначе работа до первого «＋»
    // живёт без sheetId, автосейв молчит, и первая же смена листа теряет
    // текст (поймано живой проверкой фазы 0 — сгенерированная строфа пропала).
    var alive = (sh && sh.sheets ? sh.sheets : []).filter(function (x) { return !x.trashed; });
    if (alive.length) {
      if (this.openSheet) this.openSheet(alive[0].id);
    } else {
      try {
        var made = await api.sheetsCreate({});
        var again = await api.sheetsList();
        this.setState({ sheets: again.sheets || [], folders: again.folders || [] });
        if (this.openSheet) this.openSheet(made.id);
      } catch (e) { /* нет бэка листов — честный in-memory режим, флеш уже был */ }
    }
  }

  // слот шапки (renderHeader): пилюля листов + статус сохранения + undo/redo —
  // левый блок шапки дизайна (строки 809..891 шаблона)
  // фристайл-хром (микрофон, трек, строка, сцена, профили, кадр, запись) стоит
  // первым — как в дизайне (шаблон 164..807): он гасит себя сам вне вкладки,
  // а пилюля листов гасит себя вне редактора
  renderSheetPill() {
    return (
      <Fragment>
        {renderFsBar(this)}
        {renderSheets(this)}
        {renderDocStatus(this)}
      </Fragment>
    );
  }

  // ---- lifecycle ----
  componentDidMount() {
    // ЛЮБАЯ ошибка окна — в журнал (Раунд 56). Консоли у pywebview нет, и без
    // этого «не работает» приходит ко мне без единого слова о том, что именно.
    if (typeof window !== 'undefined' && !window.__nlLogged) {
      window.__nlLogged = true;
      window.addEventListener('error', function (e) {
        журнал('ошибка окна: ' + (e && e.message ? e.message : e) + ' @ ' + (e && e.filename ? e.filename : '?') + ':' + (e && e.lineno));
      });
      window.addEventListener('unhandledrejection', function (e) {
        var r = e && e.reason;
        журнал('необработанный отказ: ' + (r && r.message ? r.message : String(r)));
      });
    }
    var self = this;
    injectBase();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { self._tabInd = false; self.moveTabInd(); });
    this._keys = (e) => this.onGlobalKey(e);
    window.addEventListener('keydown', this._keys);
    this._resize = () => this.moveTabInd();
    window.addEventListener('resize', this._resize);
    // копирование: текст выделения собираем из модели (selectionText) —
    // подписи кнопок в буфер не попадают (дизайн, строки 1461..1469)
    this._copy = (e) => {
      var txt = this.state.selAll ? this.docText() : this.selectionText();
      if (txt == null) return;
      e.preventDefault();
      try { e.clipboardData.setData('text/plain', txt); } catch (err) {}
      if (this.state.selAll) this.setState({ selAll: false });
      this.flash('скопировано');
    };
    window.addEventListener('copy', this._copy);
    // клик мимо попапов закрывает их (дизайн, строки 1470..1476)
    this._away = (e) => {
      var t = e.target;
      if (this.state.selAll) this.setState({ selAll: false });
      if (this.state.pop && !(t.closest && (t.closest('[data-pop]') || t.closest('[data-idx]')))) this.setState({ pop: null });
      if (!(t.closest && t.closest('[data-pop]'))) { this.closeSub(); this.closePop(); }
    };
    window.addEventListener('pointerdown', this._away, true);
    this.applyTheme();
    // цикл зерна сам ждёт canvas и настройку uiGrain — пустые кадры дешёвые
    this.uiGrainLoop();
    // опрос фоновых работ: кружок в шапке (Раунд 39). До этого /api/status не
    // звал никто — прогресс сборки рифм и заливки книг был не виден вовсе
    this.statusStart();
    // первый прогон строк — как в дизайне (mount не проходит через componentDidUpdate)
    setTimeout(function () { self.renderRows(); }, 0);
    this.boot();
  }
  componentDidUpdate() {
    // Слой строки на видеокарте догоняет ЛЮБОЕ изменение сцены. Сам он дешёвый
    // и по подписи отсекает лишнее (см. methods.fs.js: fsВарп), поэтому звать
    // его на каждое обновление можно и нужно — иначе крутилки отзывались бы
    // только на следующей строке.
    if (this.state.tab === 'fs' && this.fsВарп) this.fsВарп(this._lineTxt || '');
    // Каретка после перестройки строк редактора: вставка блока убивает старые
    // узлы вместе с выделением, и без этого она остаётся в контейнере.
    if (this.state.tab === 'editor' && this.caretСпасти) this.caretСпасти();
    // ЗАМОК ЗАПИСИ САМ СЕБЯ ОТПУСКАЕТ (Раунд 56).
    //
    // `data-reclock="1"` живёт на КОРНЕ ДОКУМЕНТА, а не в состоянии — и это
    // правильно: правило должно накрывать весь хром, где бы он ни висел. Но
    // цена оказалась высокой. Снимался он только на двух путях (успешный стоп
    // и обработанная ошибка старта); стоило исключению уйти мимо них — и весь
    // хром становился НЕКЛИКАБЕЛЬНЫМ до перезагрузки страницы, потому что
    // правило гасит и hover, и focus, и сами клики. Отчёт (2026-08-05): корпус некликабелен — ничего не меняется, не удаляется, не
    // добавляется. — при
    // том что панель корпуса на свежей странице кликается вся (проверено
    // живьём: pointer-events auto, ничем не накрыта, elementFromPoint даёт
    // саму кнопку).
    //
    // Теперь атрибут — не отдельная правда, а ОТРАЖЕНИЕ `recOn`, и сверяется
    // на каждом обновлении. Опрос статуса и так двигает состояние каждые
    // полсекунды, значит застрять замок может максимум на эти полсекунды.
    // Две операции с атрибутом под сравнением — цена, которой нет.
    if (typeof document !== 'undefined') {
      var надо = this.state.recOn ? '1' : null;
      var есть = document.documentElement.getAttribute('data-reclock');
      if (надо !== есть) {
        if (надо) document.documentElement.setAttribute('data-reclock', надо);
        else document.documentElement.removeAttribute('data-reclock');
      }
    }
    // ЦЕПОЧКА ПЕРЕЖИВАЕТ ПЕРЕЗАПУСК (Раунд 55). Крутилки и каркас
    // восстанавливались с самого Раунда 26, а цепочка — нет: собрал шесть
    // звеньев, закрыл окно, и всё пропало, если не положил её на полку
    // руками. Сторожим ОДНИМ местом, а не двадцатью вызовами по обработчикам:
    // ключей у цепочки шесть, и забыть один из них — вопрос времени.
    this.saveChainSoon();
    // страховку enterFs из дизайна вернёт фаза 3 — заглушка здесь зациклила бы flash
    this.moveTabInd();
    // Ярус шапки пересчитываем и после обычной перерисовки: подписи меняются от
    // содержимого (длинное имя листа, «сохранение…», статус генерации), а не
    // только от размера окна. Цикла не будет: hdrFit трогает состояние, лишь
    // когда порог реально перейдён, а вверх идти некуда после HDR_MAX.
    this.hdrFit();
    this.applyTheme();
    // хуки миксинов — как в дизайне (строки 1502..1504); syncEngine придёт в фазе 3
    if (this.syncEngine) this.syncEngine();
    this.renderRows();
    this.restoreCaret();
    // фокус-проходы дизайна (строки 1505..1516): свежесозданные поля
    // переименования и строки документа
    if (this._focusRename && this._root) {
      var inp = this._root.querySelector(this._focusRename === 'folder' ? '[data-folder-input]' : '[data-title-input]');
      if (inp) { inp.focus(); inp.select(); this._focusRename = null; }
    }
    if (this._focus != null && this._doc) {
      var el = this._doc.querySelector('[data-idx="' + this._focus + '"]');
      if (el) {
        el.focus();
        if (this._focusAt != null) this.setCaret(el, this._focusAt); else this.caretEnd(el);
      }
      this._focus = null; this._focusAt = null;
    }
  }
  componentWillUnmount() {
    window.removeEventListener('keydown', this._keys);
    window.removeEventListener('resize', this._resize);
    window.removeEventListener('copy', this._copy);
    window.removeEventListener('pointerdown', this._away, true);
    if (this._hdrObs) { this._hdrObs.disconnect(); this._hdrObs = null; }
    if (this._uiRAF) cancelAnimationFrame(this._uiRAF);
    this._uiRAF = 0;
    clearTimeout(this._flashMsgT);
    clearTimeout(this._popT);
    clearTimeout(this._subT);
    // таймеры миксинов: автосохранение листа, подтверждение корзины,
    // галочка профиля, очередь mark_shown
    clearTimeout(this._saveT);
    clearTimeout(this._confT);
    clearTimeout(this._flashT);
    clearTimeout(this._shownT);
    // фристайл: зерно, интервалы, наблюдатели и поток камеры (methods.fs.js),
    // отложенная запись вида и сброс сцены (methods.fsprofiles.js), движок и
    // аудио-граф (methods.fsglue.js)
    this.fsUnmount();
    clearTimeout(this._viewT);
    clearTimeout(this._blankT);
    // запись (methods.fsrec.js) гасится ДО аудио-графа: отводам ещё надо
    // получить команду flush, а после dispose() слать её уже некому. Дождаться
    // асинхронного стопа здесь нельзя, но начатое закрытие питон доводит сам —
    // и даже брошенный .partial открывается модулем wave
    this.recUnmount();
    this.fsGlueUnmount();
  }

  render() {
    var st = this.state, C = this.cfg(), isFs = st.tab === 'fs';
    // зерно хрома — стиль дословно из renderVals дизайна (uiGrainStyle, строка 3958)
    var g = Math.max(0, Math.min(100, parseFloat(C.uiGrain) || 0));
    var uiGrainStyle = (isFs || !g) ? 'display: none;'
      : 'position: fixed; inset: 0; width: 100%; height: 100%; z-index: 91; pointer-events: none; mix-blend-mode: overlay; opacity: ' + (0.1 + g / 100 * 0.8) + ';';
    return (
      <div ref={this.rootRef} style={s(ROOT_STYLE)}>
        {st.ядроМолчит ? renderЯдроМолчит(this) : null}
        {st.логАвария ? renderАвария(this) : null}
        {SVG_FILTERS}
        <canvas aria-hidden="true" ref={this.uiGrainRef} style={s(uiGrainStyle)}></canvas>
        {renderHeader(this)}
        <section ref={this.sectionRef} style={s('position: relative; flex: 1; min-height: 0; display: flex;')}>
          {/* сцена смонтирована ВСЕГДА и гасит себя сама вне фристайла: иначе
              движок, камера и аудио-граф пересобирались бы на каждом
              переключении вкладки (контракт render.fs.jsx) */}
          {renderFsStage(this)}
          {!isFs && renderDoc(this)}
        </section>
        {/* легенда-подвал — только в редакторе (в дизайне она внутри sc-if isEditor) */}
        {!isFs && renderLegend(this)}
        {renderFlash(this)}
      </div>
    );
  }
}

// методы редактора, листов, панелей, генерации и фристайла — миксины на
// прототипе, как в дизайне (один класс), но по модулям; tog у листов и панелей
// одинаковый. fsGlueMethods идёт последним: связка знает про соседей (сцену,
// профили) и намеренно доопределяет enterFs/loadEngine/syncEngine/onCardInput
// fsRecMethods — последним: режим записи (фаза 4) знает про сцену, аудио-граф
// и связку, и намеренно доопределяет всё, что касается записи
Object.assign(Nakedlunch.prototype, docMethods, sheetsMethods, panelMethods, genProfileMethods,
  shelfMethods, seriesMethods, genMethods, corpusMethods, fsMethods, fsProfileMethods, fsGlueMethods, fsRecMethods);
