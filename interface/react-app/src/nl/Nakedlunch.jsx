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
// ЗДЕСЬ ИМПОРТИРОВАЛСЯ ПОПАП СЛОВА — methods.слово.js (файл удалён
// 2026-08-18). Клик по слову открывал рифмы, синонимы и антонимы и ничего
// ими не делал: строки ленты не редактируются, заменять нечего. Владелец:
// «попап с кликом по тексту не нужен». Бэк не тронут — /api/word/suggest на
// месте, см. надгробие в api.js.
import { panelMethods, genProfileMethods, PARAM_DEFAULTS, DEFAULT_SPEC } from './methods.panels.js';
import { genMethods } from './methods.gen.js';
import { shelfMethods, ПРЕСЕТЫ } from './methods.shelves.js';
import { corpusMethods } from './methods.corpus.js';
import { fsMethods } from './methods.fs.js';
import { fsProfileMethods } from './methods.fsprofiles.js';
import { fsGlueMethods, журнал } from './methods.fsglue.js';
import { fsRecMethods } from './methods.fsrec.js';
import { lentaMethods } from './methods.lenta.js';
import { renderHeader, renderLegend, renderFlash } from './render.panels.jsx';
import { renderFsStage } from './render.fs.jsx';
import { renderFsBar } from './render.fspanels.jsx';
import { renderLenta } from './render.lenta.jsx';

// корневой div — стили дословно из дизайна (строка 156 шаблона)
const ROOT_STYLE = "height: 100vh; position: relative; --canvas:#131313; --ink:#ededed; --muted-hard:#cfcfcf; --muted:#949494; --muted-soft:#5c5c5c; --border-soft:#3d3d3d; --border-subtle:#242424; --menu-bg:color-mix(in srgb, var(--canvas) 82%, transparent); --content-max-width: min(clamp(440px, 24vw, 540px), calc(100% - 120px)); --radius:6px; --ease:cubic-bezier(0.4,0,0.2,1); --ease-spring:cubic-bezier(0.32,0.72,0,1); font-family: 'JetBrains Mono', ui-monospace, Menlo, monospace; background: var(--canvas); color: var(--ink); font-size: 13px; line-height: 1.5; display: flex; flex-direction: column; overflow: hidden; -webkit-font-smoothing: antialiased;";

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
// ЗДЕСЬ БЫЛА КРАСНАЯ ПЛАШКА «ПРОШЛЫЙ ЗАПУСК ЗАКРЫЛСЯ САМ» — renderАвария
// (вырезана 2026-08-18). Полоса поверх шапки с кнопками «сохранить отчёт» и
// «позже» вылезала на каждый запуск после падения.
//
// ПОЧЕМУ УШЛА. Дословно: «навязчивая вот эта плашка о том, что
// что-то не так, отправить отчёт — пусть будет без неё, пусть просто фоново
// ведётся лог». Она требовала решения там, где решать нечего: падение уже
// случилось, и человек в этот момент занят строкой, а не отчётом.
//
// ЧТО НЕ ПОТЕРЯНО. Журнал ведётся как вёлся (methods.corpus.js: statusTick →
// логОшибок / логАвария), метка ошибок на шестерёнке осталась
// (render.panels.jsx), а сам отчёт лежит в настройках, во вкладке «Лог», и
// прямо там же написано «прошлый запуск завершился аварийно»
// (render.settings.jsx: renderЛог). То есть правда никуда не делась —
// перестала догонять.
//
// renderЯдроМолчит НИЖЕ ОСТАВЛЕН НАРОЧНО. Это не «что-то пошло не так», а
// «программы нет»: ядро умерло, окно живо и выглядит рабочим. Без панели
// экран был бы просто пустым и молчащим.
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
  // params — PARAM_DEFAULTS из methods.panels.js: пять крутилок, «Метр» удалён,
  // дефолты производны от бэка (решение прожарки 5), моковые числа макета не переносятся.
  //
  // ДОКУМЕНТ И ЛИСТЫ ВЫРЕЗАНЫ 2026-08-18. Отсюда ушли: doc / caret / dirty /
  // savedAt / undoN / redoN / selAll / marks / markAnchor (сам документ и его
  // правка), sheets / sheetId / folders / folderId / folderDraft / moveOpen /
  // renaming / trashView / titleEdit (листы, папки и корзина).
  // Требование: «лента — отдельная вкладка, которая уже не
  // нужна в таком виде. По сути ты наплодил говна, не почистил старое,
  // фактически не убрал» — и раньше: «строфа единственным режимом и всё»,
  // «жмёшь enter — тебе выдаёт», «всё аккумулируется в избранном».
  // Основание замером, а не вкусом: в сессии на 453 минуты и 181 генерацию в
  // избранное ушло НОЛЬ строк, потому что все четыре входа в копилку сидели
  // внутри документа. Лента убирает это условие — строка сохраняется с
  // клавиатуры, документ для этого не нужен.
  // Имена НЕ забыты: они лежат запретом в methods.fsprofiles.js
  // (PROF_SKIP_STATE) — старые профили сцены на диске несут их до сих пор.
  state = { tab: 'lenta',
    /* ЛЕНТА — единственная поверхность выдачи. `lenta` держит строки
       ТЕКУЩЕЙ строфы, а не список показанного: с 2026-08-18 на экране
       всегда ровно одна, новая заменяет старую («жму интер — оно должно
       старое убирать»).
       ОТСЮДА ТОГДА ЖЕ УШЛИ: lentaCur / lentaSel (курсор по строкам и
       диапазон выделения Shift'ом) — «там сейчас можно бессмысленно
       выделить строку одну, и с этим ни хуя не делается. Это просто
       графическое выражение, это бред»; pop / popTab / popItems /
       popLoading и thesaurus (попап слова и ворота его вкладки
       «антонимы») — «попап с кликом по тексту не нужен». */
    lenta: [], micOn: false, trackOn: false, synthWanted: true, synthOn: true /* синтетика водит картинку, пока нет ни микрофона, ни трека — см. freestyle/audio.js */, bcOn: true, bcEpoch: 0 /* счётчик перезапусков движка — пересоздаёт канвас, см. methods.fsglue.fsRestartEngine */, autoOn: false, bcAutoOn: false, bcAutoSec: 30, recOn: false /* замок хрома на время записи в состоянии НЕ живёт (Раунд 63): он и был `data-reclock` на корне документа — см. componentDidUpdate и style.js. Поле recLock писалось при старте и стопе записи, но не читалось ни разу, то есть было второй, немой правдой о замке */, textAber: false, postAber: false, aspect: '', profiles: [], profId: '', profEdit: '', uiProfiles: [], uiProfId: '', srcMode: 'генератор', srcText: '', srcChunk: 'строки', camOn: false, fitFrame: false, grainBlend: 'overlay', grainFps: 24, posX: 'по центру', posY: 'по центру', camId: '', camList: [], camBlend: 'normal', camFit: 'заполнить', camMirror: false, glowColor: '', glowWarp: 'чисто', selMode: 'нет', fsv: {}, /* СВОИ НАСТРОЙКИ ФРИСТАЙЛА (Раунд 57). До этого он падал на панель редактора: linkKnobs(0)/linkSpec(0) последней ступенью читают state.knobMode/params/curSpec(), а тема бралась из _lastKey — ключа последней генерации В РЕДАКТОРЕ. Крутил строфу — менял сцену. null = ещё не отделялся, значит наследуем текущее редакторское один раз. */ /* fsTheme снят 2026-08-30 вместе с полем «темы сцены»: тема вырезана из проекта, а поле стояло и не действовало */ fsKnobMode: null, fsParams: null, fsSpec: null, fsПолосы: null, fsДоли: null, acMode: 'выкл', grainMode: 'плёнка', fonts: [], fontNow: '', fontQ: '', pal: null, palSel: { panel: 0, ink: 0 }, fsSetOpen: false, fsLineOpen: false, fsTab: 'cam', live: {}, presetTab: 'all', presetQ: '', presetTick: 0, defProf: '', uiDefProf: '', uiProfEdit: '', flashMsg: '', srcBusy: {} /* какие источники сейчас переключаются — Раунд 56 */, importing: [] /* книги, которые заливаются прямо сейчас */, confirm: '', openPill: '', algo: 'Алгоритм', theme: 'dark', cfg: {}, favs: [], hist: [],
    /* ЦЕПЬ И СЕРИЯ ВЫРЕЗАНЫ 2026-08-18. Отсюда ушли: chain / junctions /
       chainForms / chainKnobs / chainRepeat / chainList / chainMine /
       chainDraft / profile / savedSnap (цепочка и её полка),
       seriesList / seriesName / seriesLinks / seriesDraft / seriesSec /
       seriesState / seriesCurve / seriesNoise / noiseKind / curveChan (серия и
       её искажение), refText / refPct / refChain / refProfile / refBusy /
       refOpen (референс как вход пайплайна), lastPipeFunnel.
       Решено: «pipeline и серия это бесполезные режимы на
       самом деле… с практической точки зрения бесполезны, их можно вырезать.
       Строфа единственным режимом и всё». Замер журнала за десять живых дней:
       29 прогонов цепи против 587 одиночных строф, медиана цепи 24.2 с.
       Имена НЕ забыты: они остались запретом в methods.shelves.js
       (КЛЮЧИ_МОДЕЛИ) — старые профили сцены на диске несут их до сих пор. */
    /* ПОЛКА ПРОФИЛЕЙ НАСТРОЕК ВЫРЕЗАНА 2026-08-18 (замер «девять крутилок →
       четыре пресета»). Отсюда ушли knobForms (список записей с бэка),
       knobProfile (выбранное имя), knobDirty («правлено, но не сохранено») и
       knobDraft (поле имени). Своих профилей у пользователя не было ни одного,
       встроенных было два, и оба стали пресетами — methods.shelves.js: ПРЕСЕТЫ.
       Имена НЕ забыты: они лежат запретом в methods.shelves.js (КЛЮЧИ_МОДЕЛИ) —
       старые профили СЦЕНЫ на диске несут их до сих пор.
       knobMode остался: режим отбора ставит пресет, и он же уезжает на бэк. */
    /* chipOpen/juncOpen/myProfN/saveFlash вырезаны (Раунд 63) — писались, но не
       читались ни одним рендером: горизонтальные чипы цепочки и их меню ушли
       ещё в Раунде 41/50, а галочку сохранения показывает profSaveFlash. */
    /* СТАРТОВЫЙ ПРЕСЕТ — П1 «Как всегда» (57.2% его живых прогонов), а не голые
       PARAM_DEFAULTS. Изначальная причина была в Банальности 0.83, стоявшей в
       мёртвой половине шкалы; ручка удалена 2026-08-20, а выбор остался: пресет
       называет решение, а набор дефолтов — нет. Сохранённые настройки этот
       выбор перекрывают (см. boot). */
    knobMode: ПРЕСЕТЫ[0].mode,
    params: Object.assign({}, PARAM_DEFAULTS, ПРЕСЕТЫ[0].params),
    // ПОЛОСЫ РЕДКОСТИ — не крутилки, а ВЫБОР: несколько несмежных отрезков
    // шкалы. Пустая строка = ворота не закрыты. Разбор — core/редкость.py.
    полосы: { слова: '', пара: '', плотность: '' },
    // ДОЛИ — тоже не крутилки, а ПРОПОРЦИЯ между сортами, выбранными маской:
    // «1:20,2:50,4:30». Пустая строка = поровну, то есть прежнее поведение
    // маски. Разбор — core/доли.py. Ось `рифма` в хранении есть, но ядро её
    // пока не исполняет, и на экране её нет (см. render.gen.jsx).
    доли: { клаузула: '', рифма: '', позиция: '' },
    // профиль генерации: схема строфы + её имя (boot поднимает из /api/settings),
    // profNameDraft — поле имени.
    // stanzaPick («открыт ли список форм внутри попапа») вырезан в Раунде 63:
    // список форм давно рисуется всегда, флаг только гасили в трёх местах.
    // stanzaSection (заголовок над строфой) вырезан 2026-08-18 вместе с
    // документом: заголовок был строкой ЛИСТА, а листа больше нет.
    stanzaSpec: null, stanzaProfile: '', themeKeys: '', profNameDraft: '', profSaveFlash: false,
    // НОМЕР ПРОГОНА (Раунд 62). seedDraft — что вписано в поле: пусто значит
    // «новый прогон», число значит «повторить тот». seedLast — номер, которым
    // собралась последняя выдача, seedStamp — на чём он снят (версия индекса,
    // размер пула и скрытого): семя воспроизводит ВЫБОР, а не материал, и когда
    // материал сменился, это надо сказать, а не выдать чужое за то же самое.
    seedDraft: '', seedLast: null, seedStamp: null,
    // Воронка последнего прогона — ступени так, как они происходят. Раньше её
    // не показывал никто (инфографику вырезали в Раунде 50), и крупнейшая
    // ступень каскада была невидима.
    funnelLast: null,
    // Форма пула: из чего сейчас будет выбираться. Спрашивается при движении
    // ручек с дебаунсом — живого предпросмотра выдачи нет (замер 3.7), а это
    // есть, и стоит единицы миллисекунд.
    poolShape: null,
    // ярус сжатия шапки, 0..HDR_MAX; считает hdrFit по фактической ширине
    hdrTier: 0,
    // Раунд 39: фоновые работы (/api/status) и всё, что вернулось из потерянных
    // функций — корпус, сроки хранения, возврат показанного (methods.corpus.js).
    // nlRetention вырезан (Раунд 63): срок жизни «показанного» у самого
    // nakedlunch никуда не выводился — ни одной строки настроек, только
    // молчаливый запрос на старте и сеттер без вызывающих.
    jobs: [], corpusBusy: '', histRetention: 0, restoreTheme: '', cfgTab: 'лента',
    // Раунд 40: полноценные избранное и история — поиск, правка, отмена.
    // blackDraft вырезан (Раунд 63): поле-черновик чёрного списка не читал никто.
    favQ: '', histQ: '', favEdit: '', favUndo: '', histCfg: false, statsData: null, funnel: null, black: null };

  DARK = { '--canvas': '#131313', '--ink': '#ededed', '--muted-hard': '#cfcfcf', '--muted': '#949494', '--muted-soft': '#5c5c5c', '--border-soft': '#3d3d3d', '--border-subtle': '#242424' };
  LIGHT = { '--canvas': '#ffffff', '--ink': '#101010', '--muted-hard': '#222222', '--muted': '#555555', '--muted-soft': '#999999', '--border-soft': '#c8c8c8', '--border-subtle': '#e0e0e0' };
  // ROLES (заголовки секций) и LETTERS вырезаны 2026-08-18 вместе с документом:
  // заголовок секции был строкой, которую генерация клала НАД строфой в лист, а
  // класть больше некуда. JMARK (значки стыков) ушёл раньше, вместе со стыками.
  // TABS (вкладки попапа слова: рифмы, по звуку, синонимы, антонимы,
  // строкой) вырезаны 2026-08-18 вместе с самим попапом.

  // ---- refs ----
  rootRef = (el) => { this._root = el; this.applyTheme(); };
  sectionRef = (el) => { this._sec = el; };
  bgRef = (el) => { this._bg = el; };
  inputRef = (el) => { this._input = el; };
  // Прокрутка ленты. Строфа на экране одна: короткая стоит по центру и не
  // листается вовсе, длинная (ода в 14 строк) листается внутри своей области и
  // обязана начинаться СВЕРХУ. Флаг ставит сама лента (lentaПоложить:
  // _lentaВверх), снимает componentDidUpdate.
  lentaRef = (el) => { this._lenta = el; };

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
      // «очень узкая» добавлена и стала умолчанием 2026-08-28 по слову
      // требование: колонка теперь ФИКСИРОВАННОЙ ширины (render.lenta.jsx),
      // и стихам с их короткой строкой узкий столб — родной размер.
      'очень узкая': 'min(clamp(440px, 24vw, 540px), calc(100% - 120px))',
      'узкая': 'min(clamp(620px, 34vw, 780px), calc(100% - 120px))',
      'средняя': 'min(clamp(900px, 45vw, 1100px), calc(100% - 120px))',
      'широкая': 'min(clamp(1080px, 62vw, 1400px), calc(100% - 80px))'
    };
    el.style.setProperty('--content-max-width', cw[C.colWidth] || cw['очень узкая']);
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
    // Вкладок две: лента и фристайл. Ищем кнопку ПО ИМЕНИ вкладки, а не
    // тернарником: тернарник на две кнопки уже однажды увёл бегунок под
    // соседнюю — молча, потому что querySelector находил существующую кнопку
    // и никакой ошибки не случалось.
    var btn = nav.querySelector('button[data-tab="' + this.state.tab + '"]');
    if (!ind || !btn || !btn.offsetWidth) return;
    ind.style.transition = this._tabInd ? 'transform 320ms var(--ease-spring), width 320ms var(--ease-spring)' : 'none';
    ind.style.width = btn.offsetWidth + 'px';
    ind.style.transform = 'translateX(' + btn.offsetLeft + 'px)';
    this._tabInd = true;
  }
  setTab(t) {
    if (t === this.state.tab) return;
    this.openPop({ tab: t, marks: {} });
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
    this.setState(Object.assign({ openPill: '', fsSetOpen: false, fsLineOpen: false, closing: '' }, patch || {}));
  }
  // НАДГРОБИЕ 2026-09-02: ПОДСИСТЕМА ПОДМЕНЮ (`togSub`/`openSub`/`closeSub`,
  // состояние `subPill`/`subClosing`, таймер `_subT`).
  //
  // Она заводилась для меню ВНУТРИ панели — профиль, фильтры, воронка, роль
  // звена, — которым нужен был свой уровень: пущенные через `openPill`, они
  // закрывали панель-родителя, и в пайплайне «ничего не нажималось». Все эти
  // меню уехали вместе с пайплайном и цепью (2026-08-18), и с того дня
  // `togSub` и `openSub` не звал НИКТО, а `subPill` оставался пустым всегда.
  //
  // `closeSub` при этом звали дважды — из `closePop` и из обработчика клика
  // мимо панелей, — и оба раза он выходил на первой строке по пустому ключу.
  // Шесть мест в главном компоненте обслуживали состояние, которого не бывает;
  // тот, кто пошёл бы делать подменю, нашёл бы готовый на вид механизм и
  // выяснял бы, почему он не работает.
  // ФАНТОМНЫЕ КЛЮЧИ ЗАКРЫТИЯ 'chip'/'junc' УБРАНЫ (Раунд 63).
  //
  // Здесь и в closePop к ключу подмешивалось `chipOpen >= 0 ? 'chip'` и то же
  // для `juncOpen`. Меню чипов и стыков, ради которых это писалось, вырезаны в
  // Раундах 41/50, и рисовать по этим ключам стало нечего. С juncOpen выходил
  // просто мёртвый код (его нигде не поднимали выше −1), а с chipOpen — хуже:
  // `moveChip` продолжал класть в него номер переставленного звена, и после
  // первой же перестановки закрытие ВСЕГДА считало, что открыт некий 'chip',
  // проходило мимо раннего выхода и заводило 140-мс таймер на каждый клик мимо
  // панелей. Теперь ключ — только то, что действительно нарисовано.
  // закрытие: состояние держим ещё кадр анимации, потом гасим по-настоящему
  closePop(extra) {
    var st = this.state, self = this;
    if (extra) this.setState(extra);
    var k = st.openPill || (st.fsSetOpen ? 'fsset' : '') || (st.fsLineOpen ? 'fsline' : '');
    if (!k || this._popT) return;
    this.setState({ closing: k });
    this._popT = setTimeout(function () {
      self._popT = null;
      self.setState({ openPill: '', fsSetOpen: false, fsLineOpen: false, closing: '' });
    }, 140);
  }

  // ---------------------------------------------------------------------------
  // ЗДЕСЬ БЫЛ ДОКУМЕНТ: cur() / docText() / inDoc() / copyAll() / fallbackCopy()
  // (вырезано 2026-08-18 вместе с редактором).
  //
  // cur() отдавал рабочий буфер листа, docText() собирал из него markdown,
  // copyAll() клал этот markdown в буфер обмена по ⌘C, inDoc() отвечал, стоит
  // ли каретка внутри контейнера строк. Всё это существовало ради одного —
  // редактируемого документа, которого больше нет.
  //
  // Копирование НЕ потеряно: в ленте оно своё и работает с выделением строк
  // (methods.lenta.js: lentaКопировать → copyText из methods.corpus.js, где и
  // живёт честный запасной путь через скрытое поле).
  // ---------------------------------------------------------------------------

  flash(msg) {
    var self = this;
    clearTimeout(this._flashMsgT);
    this.setState({ flashMsg: msg });
    this._flashMsgT = setTimeout(function () { self.setState({ flashMsg: '' }); }, 2000);
  }
  // ВСЕ КЛАВИШИ ЛЕНТЫ ЖИВУТ В methods.lenta.js, И ЭТО ПОЧИНКА (2026-08-18).
  //
  // Здесь стояло `var mod = e.metaKey || e.ctrlKey;`, а ниже — `if (!mod)
  // return;` РАНЬШЕ проверки Enter. Из-за этого строфу давал только ⌘↵:
  // «я сказал нажатие на интер даёт строфу, а у тебя строфа на комманд интер».
  // Правда о клавише лежала в двух файлах, и, читая любой из них по
  // отдельности, ошибку увидеть было нельзя. Теперь окно только раздаёт
  // событие, а решает лента — она же проверяет вкладку и поле ввода.
  //
  // ЗДЕСЬ ЖЕ РАНЬШЕ БЫЛИ ВЫРЕЗАНЫ (2026-08-18) КЛАВИШИ ДОКУМЕНТА: ⌘A —
  // выделить лист, ⌘B / ⌘I — начертание, ⌘1–3 — заголовок секции, ⌘C —
  // копирование листа из модели, ⌘Z / ⌘⇧Z — отмена и возврат. Все шесть
  // работали только внутри contenteditable-строк, которых больше нет.
  onGlobalKey(e) {
    if (this.lentaКлавиша && this.lentaКлавиша(e)) return;
    if (e.key === 'Escape') { this.closePop(); return; }
  }

  // ---- первичная загрузка ----
  // всё параллельно; каждая ошибка — flash и пустое значение, приложение живёт
  async boot() {
    var errs = [];
    var grab = function (p) { return p.catch(function (e) { errs.push(e && e.message ? e.message : String(e)); return null; }); };
    // Полки цепочек и серий (api.chains / api.series) больше не спрашиваются —
    // 2026-08-18, вырезаны вместе со своими меню.
    // Список листов (api.sheetsList) — тоже: листов нет с 2026-08-18.
    // Полка профилей настроек (api.knobProfiles) не спрашивается с 2026-08-18:
    // её заменили четыре пресета, зашитые в methods.shelves.js — ПРЕСЕТЫ.
    const [st, nl, settings, forms, hist] = await Promise.all([
      grab(api.state()),
      grab(api.nlState()),
      grab(api.settingsGet()),
      grab(api.stanzaProfiles()),
      grab(api.history('')),
    ]);
    // Сохранённых положений нет (чистая установка) — открываемся на П1, а не на
    // голых дефолтах (см. состояние выше). Есть сохранённые — берём их КАК
    // ЕСТЬ и ничего не подтягиваем:
    // подсветка пресета считается по положениям (methods.shelves.js:
    // имяПресета), и если они не совпали ни с одним, панель говорит об этом
    // прямо. Молча подменить чужие настройки ближайшим пресетом значило бы
    // соврать о том, что уедет на бэк (§9.4 отчёта: «молча не подменять»).
    var сохр = (settings && settings.nl_params) || null;
    var своиПоложения = (сохр && сохр.params && Object.keys(сохр.params).length) ? сохр.params : null;
    this.setState({
      // /api/state отдаёт accepted — плоский список строк избранного, новые сверху;
      // внутри приложения избранное живёт объектами {t} (лента и панели сравнивают f.t)
      favs: (st && st.accepted ? st.accepted : []).map(function (t) { return typeof t === 'string' ? { t: t } : t; }),
      // история: показанное построчно, {time, t} — как ждёт панель истории дизайна
      // подпись времени — одним местом (histRow миксина корпуса): сегодняшнее
      // часами, прежнее датой
      hist: hist && hist.items ? hist.items.map((h) => this.histRow(h)) : [],
      // ЗДЕСЬ ПОДНИМАЛИСЬ СЛОВАРНЫЕ СЛОИ ТЕЗАУРУСА — thesaurus (вырезано
      // 2026-08-18). Их читала ровно одна вкладка «антонимы» в попапе слова;
      // попапа нет, и флаг стал бы состоянием без читателя. Само поле бэк
      // в /api/state по-прежнему отдаёт — его просто перестали спрашивать.
      // сырые ответы бэка — их разложат миксины панелей (воронка, крутилки, конструктор строф)
      corpus: st ? st.corpus : null,
      nl: nl,
      settings: settings,
      stanzaForms: forms,
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
      params: Object.assign({}, PARAM_DEFAULTS, своиПоложения || ПРЕСЕТЫ[0].params),
      полосы: {
        слова: (сохр && сохр.полосы && сохр.полосы.слова) || '',
        пара: (сохр && сохр.полосы && сохр.полосы.пара) || '',
        плотность: (сохр && сохр.полосы && сохр.полосы.плотность) || '',
      },
      // Доли поднимаются тем же путём и по той же причине: окно открывается
      // там, где его закрыли. Бэк их уже хранит (settings._nl_params).
      доли: {
        клаузула: (сохр && сохр.доли && сохр.доли.клаузула) || '',
        рифма: (сохр && сохр.доли && сохр.доли.рифма) || '',
        позиция: (сохр && сохр.доли && сохр.доли.позиция) || '',
      },
      knobMode: (сохр && сохр.mode) || ПРЕСЕТЫ[0].mode,
      // Восстановление живой цепочки из settings.nl_chain убрано 2026-08-18:
      // цепочки нет, и поднимать нечего. Сам ключ на диске у пользователя
      // остаётся — читать его просто перестали, поэтому откат ничего не теряет.
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
    // ЗДЕСЬ ОТКРЫВАЛСЯ ПЕРВЫЙ ЛИСТ и создавался лист на пустом хранилище
    // (вырезано 2026-08-18). Листов нет: выдача копится в ленте, а сохраняется
    // не она, а избранное — «всё аккумулируется в избранном».
  }

  // Слот левого блока шапки (renderHeader). Раньше в нём стояли ещё пилюля
  // листов и статус сохранения с отменой-возвратом — вырезаны 2026-08-18
  // вместе с документом. Остался фристайл-хром (микрофон, трек, строка, сцена,
  // профили, кадр, запись): он гасит себя сам вне своей вкладки.
  renderSheetPill() {
    return (
      <Fragment>
        {renderFsBar(this)}
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
    // ПЕРЕХВАТ СОБЫТИЯ `copy` УБРАН 2026-08-18. Он собирал текст выделения из
    // МОДЕЛИ документа (docText/selectionText), чтобы в буфер не попадали
    // подписи кнопок строки — номер, буква рифмовки, звезда. Строк документа
    // нет, кнопок на них нет, и подменять браузеру обычное копирование стало
    // не только незачем, но и вредно: в ленте и панелях мышью копируют как
    // везде. Копирование выделения ленты — своё, по ⌘C (methods.lenta.js).
    //
    // клик мимо попапов закрывает их (дизайн, строки 1470..1476).
    // Ветка `[data-слово]` ушла 2026-08-18 вместе с попапом слова: она
    // существовала ради одного — чтобы повторный клик по тому же слову
    // ЗАКРЫВАЛ попап, а не гасил его pointerdown'ом и тут же открывал заново.
    this._away = (e) => {
      var t = e.target;
      if (!(t.closest && t.closest('[data-pop]'))) { this.closePop(); }
    };
    window.addEventListener('pointerdown', this._away, true);
    this.applyTheme();
    // цикл зерна сам ждёт canvas и настройку uiGrain — пустые кадры дешёвые
    this.uiGrainLoop();
    // опрос фоновых работ: кружок в шапке (Раунд 39). До этого /api/status не
    // звал никто — прогресс сборки рифм и заливки книг был не виден вовсе
    this.statusStart();
    this.boot();
  }
  componentDidUpdate() {
    // Слой строки на видеокарте догоняет ЛЮБОЕ изменение сцены. Сам он дешёвый
    // и по подписи отсекает лишнее (см. methods.fs.js: fsВарп), поэтому звать
    // его на каждое обновление можно и нужно — иначе крутилки отзывались бы
    // только на следующей строке.
    if (this.state.tab === 'fs' && this.fsВарп) this.fsВарп(this._lineTxt || '');
    // ПРОКРУТКА ВВЕРХ, А НЕ ВНИЗ (2026-08-18). Пока лента копилась, свежая
    // строфа падала В КОНЕЦ, и её приходилось догонять прокруткой вниз.
    // Теперь на экране одна: короткая стоит по центру и не листается вовсе,
    // длинная обязана начинаться СВЕРХУ, а не с того места, до которого
    // домотали предыдущую. Флаг ставит сама лента (lentaПоложить).
    if (this._lentaВверх && this._lenta) {
      this._lentaВверх = false;
      this._lenta.scrollTop = 0;
    }
    // ИСТОРИЯ — ПО ФАКТУ ПОКАЗА, А НЕ ПО ФАКТУ ВЫДАЧИ ИЗ БУФЕРА. Владелец:
    // «мы показываем то, что показываем, добавляется в историю, а то, чего нет
    // на экране, не добавляется». Раньше отметка стояла в lentaПоложить, и это
    // было верно, пока положенное оставалось на экране навсегда. При замене
    // два нажатия в одном круге событий берут из буфера ДВЕ строфы, а
    // перерисовка случается одна — первой на экране не будет ни кадра.
    // Отметка после отрисовки и по номеру блока это закрывает
    // (methods.lenta.js: lentaОтметитьПоказ).
    if (this.lentaОтметитьПоказ) this.lentaОтметитьПоказ();
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
    // Здесь стоял saveChainSoon() — запись живой цепочки на диск на каждом
    // обновлении (Раунд 55, «где закрыл, там открыл»). Убран 2026-08-18 вместе
    // с цепочкой; каркас строфы и крутилки пишет saveGenProfileSoon со своих
    // обработчиков, и лишнего прохода по componentDidUpdate им не нужно.
    // страховку enterFs из дизайна вернёт фаза 3 — заглушка здесь зациклила бы flash
    this.moveTabInd();
    // Ярус шапки пересчитываем и после обычной перерисовки: подписи меняются от
    // содержимого (статус генерации), а не только от размера окна. Цикла не
    // будет: hdrFit трогает состояние, лишь когда порог реально перейдён, а
    // вверх идти некуда после HDR_MAX.
    this.hdrFit();
    this.applyTheme();
    // хуки миксинов — как в дизайне (строки 1502..1504)
    if (this.syncEngine) this.syncEngine();
    // Отсюда 2026-08-18 ушли renderRows() и restoreCaret() (императивная
    // отрисовка строк документа и возврат каретки) и оба фокус-прохода —
    // на поле переименования листа и на строку документа. Ни строк, ни листов,
    // ни каретки больше нет.
  }
  componentWillUnmount() {
    window.removeEventListener('keydown', this._keys);
    window.removeEventListener('resize', this._resize);
    window.removeEventListener('pointerdown', this._away, true);
    if (this._hdrObs) { this._hdrObs.disconnect(); this._hdrObs = null; }
    if (this._uiRAF) cancelAnimationFrame(this._uiRAF);
    this._uiRAF = 0;
    clearTimeout(this._flashMsgT);
    clearTimeout(this._popT);
    // таймеры миксинов: подтверждение очистки истории, галочка профиля,
    // очередь mark_shown (автосохранение листа ушло вместе с листами)
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
        {SVG_FILTERS}
        <canvas aria-hidden="true" ref={this.uiGrainRef} style={s(uiGrainStyle)}></canvas>
        {renderHeader(this)}
        <section ref={this.sectionRef} style={s('position: relative; flex: 1; min-height: 0; display: flex;')}>
          {/* сцена смонтирована ВСЕГДА и гасит себя сама вне фристайла: иначе
              движок, камера и аудио-граф пересобирались бы на каждом
              переключении вкладки (контракт render.fs.jsx) */}
          {renderFsStage(this)}
          {/* Колонка документа (renderDoc) стояла здесь до 2026-08-18.
              Поверхность одна — лента. */}
          {renderLenta(this)}
        </section>
        {/* легенда-подвал — вне фристайла (там свой хром и своя строка) */}
        {!isFs && renderLegend(this)}
        {renderFlash(this)}
      </div>
    );
  }
}

// методы ленты, панелей, генерации и фристайла — миксины на прототипе, как в
// дизайне (один класс), но по модулям.
// docMethods, sheetsMethods и словоMethods убраны 2026-08-18 вместе со своими
// файлами (редактор, листы, попап слова).
// fsGlueMethods идёт предпоследним: связка знает про соседей (сцену, профили)
// и намеренно доопределяет enterFs/loadEngine/syncEngine/onCardInput.
// fsRecMethods — последним: режим записи знает про сцену, аудио-граф и связку,
// и намеренно доопределяет всё, что касается записи
Object.assign(Nakedlunch.prototype, lentaMethods, panelMethods, genProfileMethods,
  shelfMethods, genMethods, corpusMethods, fsMethods, fsProfileMethods, fsGlueMethods, fsRecMethods);
