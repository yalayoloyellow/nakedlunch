// Слоёная сцена фристайла из дизайна «Editor First» (project-notes/mockups/
// design-v2/Editor First.dc.html) — дословный перенос в JSX:
//   renderFsStage(c)  — весь fs-регион шаблона, строки 1140..1191: оболочка,
//                       #freestyle-stage, внутренний слой трансформа, канвас
//                       визуализатора, цветовой слой, стеклянный скрим, блум,
//                       камера, скрытые входы движка, сцена со строкой
//                       (плашка + два слоя хроматики + резкий слой; три слоя
//                       свечения вырезаны в Раунде 57 — свечение тенью),
//                       пост-слой и зерно.
// Значения renderVals дизайна (строки 3390..4105) вычислены ЛОКАЛЬНО из
// c.state/c.cfg(), как это уже сделано в render.doc.jsx. c — экземпляр
// Nakedlunch.
//
// Контракт с интегратором:
//   - сцена монтируется ВСЕГДА, а не только на вкладке «фристайл»: вне её
//     оболочка гасится через visibility/opacity/pointer-events (fsShellStyle
//     дизайна). Иначе движок и камера перезапускались бы на каждом переключении
//     вкладки. То есть в <section> идёт renderFsStage(c) И, отдельно,
//     {isEditor && renderDoc(c)};
//   - строчные слои [data-fsline] React рендерит ПУСТЫМИ: текст в них пишет
//     c.paintLine() императивно (тот же приём, что у контейнера строк
//     документа), а плашку [data-fsband] рисует c.paintBand() по фактическим
//     прямоугольникам текста;
//   - ref'ы берутся через c.fsRef('имя') — миксин methods.fs.js кэширует
//     связанные функции, поэтому React не дёргает ref на каждом рендере;
//   - скрытые входы движка (#trackFile, #trackGainSlider, #btnTrackStop,
//     #btnToggleLine/Text/Bg, popover*Slider, fsTabOffset*Slider) — контракт
//     аудио- и движкового модулей (freestyle/audio.js, freestyle/engine.js):
//     они их находят по id. Разметка их держит ровно как дизайн;
//   - SVG-фильтры (#nl-text-warp, #nl-postfx и их -aber) объявлены в
//     Nakedlunch.jsx; c.pushFilters() дотягивается до них querySelector'ом,
//     ref'ы textWarpRef/postfxRef интегратор может навесить для точности.
// Запись (recOn/MediaRecorder) — ФАЗА 4: кнопку рисует шапка (renderFsBar),
// приглушённой и без обработчика записи.

import { s } from './style.js';

// ---- сцена: строки 1140..1191 шаблона -------------------------------------
export function renderFsStage(c) {
  var st = c.state, C = c.cfg();
  var isFs = st.tab === 'fs';

  // ---- значения renderVals дизайна (3446..3948), посчитанные локально ----
  var num = function (k, d) { var v = parseFloat(C[k] != null ? C[k] : d); return isNaN(v) ? d : v; };
  // живая ручка окна: то же, что c.L(), но модуль сцены может подмешаться
  // раньше модуля панелей — читаем состояние напрямую
  var L = function (key, dflt) {
    var lv = st.live || {}, v = lv[key];
    if (v == null) v = (c._live || {})[key];
    return v == null || isNaN(v) ? dflt : v;
  };
  var fsv = function (k) { return c.fsv ? c.fsv(k) : 100; };

  var selMode = st.selMode || 'нет';
  // строчный слой: фон обнимает каждую строку ровно как выделение мышью, эффекты идут поверх
  var selBg = { 'белая': '#ffffff', 'чёрная': '#101010', 'плашка': 'var(--panel, #2436e0)' }[selMode];
  var selFx = selBg ? ' color: ' + (selMode === 'белая' ? '#101010' : '#ffffff') + ';' : '';
  var glowCol = st.glowColor, expo = fsv('expo');
  var expoFx = expo !== 100 ? ' brightness(' + expo / 100 + ')' : '';

  var fsSize = Math.max(12, Math.min(400, parseFloat(C.fsSize) || 48));
  var fsTextBlur = L('textBlur', 0) / 5, fsTextWarp = L('distort', 0);
  var fsWeight = num('fsWeight', 700), fsBcOp = num('fsBcOpacity', 100);
  var tAber = fsv('taber');
  // ХРОМАТИКА ВКЛЮЧАЕТСЯ ПО ВИДИМОМУ СМЕЩЕНИЮ, А НЕ ПО «БОЛЬШЕ НУЛЯ» (Раунд 57).
  //
  // Условием было `tAber > 0`, а значение по умолчанию — ЕДИНИЦА (FS_DEF.taber).
  // То есть фильтр не выключался никогда. При единице он двигает каналы на
  // 0.2 пикселя — увидеть нельзя, — но отрабатывает целиком: турбулентность,
  // гауссово размытие, ТРИ карты смещения, три цветовые матрицы, два наложения,
  // на области 300%. Вчетверо дороже обычного искажения, и всё это впустую.
  //
  // Владелец выключил искажение, и лаг остался — журнал показал, почему:
  // `фильтр blur(4.8px) url(#nl-text-warp) url(#nl-text-warp-aber)`. Мой же
  // перебор этого не поймал, потому что вариант «без варпа» вычищал из цепочки
  // ВСЕ url(...) разом, то есть и хроматику: я померила «без обоих», а назвала
  // «без искажения».
  //
  // Порог — то же смещение, что считает pushFilters (кайма от taber плюс доля
  // искажения). Меньше полпикселя не видно ни на одном кегле, значит платить за
  // это нельзя.
  var tAberFringe = (tAber / 100) * (20 + fsTextWarp * 0.6 * 0.15);
  var tAberOn = tAberFringe >= 0.5;
  // ИСКАЖЕНИЕ УШЛО НА ВИДЕОКАРТУ (Раунд 57, см. freestyle/warpgl.js — там все
  // замеры и все грабли). Пока слой не поднялся (`c._варпЖив` ставит
  // methods.fs.js), работает прежний путь фильтром: хуже по цене, но рабочий.
  var варпГл = fsTextWarp > 0 && c._варпЖив !== false;
  var glowWarpFx = (fsTextWarp > 0 && !варпГл ? 'url(#nl-text-warp) ' : '')
    + (tAberOn ? 'url(#nl-text-warp-aber)' : '');
  var fsLineFilter = (fsTextBlur > 0 ? 'blur(' + fsTextBlur + 'px) ' : '') + glowWarpFx;
  var fsCol = 'var(--ink-on-color, #ffffff)';
  var POSN = { 'слева': 'flex-start', 'по центру': 'center', 'справа': 'flex-end' };
  var POSY = { 'сверху': 'flex-start', 'по центру': 'center', 'снизу': 'flex-end' };
  var posX = st.posX || 'по центру', posY = st.posY || 'по центру';
  // хроматика строки идёт через SVG-фильтр (taber), поэтому сдвиг слоёв = 0:
  // слои остаются в разметке дизайна и оживают, если сдвиг когда-нибудь вернут
  var fsAberPx = 0;
  var aberLayer = function (dx, col) {
    return fsAberPx > 0
      ? 'white-space: pre-line; position: absolute; inset: 0; pointer-events: none; mix-blend-mode: screen; color: ' + col + '; transform: translateX(' + dx + 'px); opacity: 0.75;' + (fsTextBlur > 0 ? ' filter: blur(' + fsTextBlur + 'px);' : '')
      : 'display: none;';
  };

  var fsPostfxBlur = L('postfxBlur', 0), fsPostfxBend = L('postfxBend', 0);
  var fsPostfxOn = fsPostfxBend > 0 || fsPostfxBlur > 0;
  var fsPostfxFx = (fsPostfxBend > 0 ? 'url(#nl-postfx' + (st.postAber ? '-aber' : '') + ') ' : '') + (fsPostfxBlur > 0 ? 'blur(' + fsPostfxBlur + 'px)' : '');

  var camFit = { 'заполнить': 'cover', 'вписать': 'contain', 'растянуть': 'fill' }[st.camFit || 'заполнить'];

  // ---- строки стилей: дословно из renderVals ----
  var fsShellStyle = 'position: absolute; inset: 0; z-index: 0; overflow: hidden;' + (isFs ? '' : ' visibility: hidden; opacity: 0; pointer-events: none;');
  var fsStageClass = 'freestyle-stage' + (st.bcOn ? ' bc-on' : '');
  var fsInnerStyle = 'position: absolute; inset: 0; will-change: transform;';
  var fsBcStyleCanvas = 'position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1; opacity: ' + (fsBcOp / 100) + '; display: ' + (st.bcOn ? 'block' : 'none') + ';';
  var fsColorLayerStyle = 'position: absolute; inset: 0; z-index: 3; pointer-events: none; background-color: var(--panel, transparent); mix-blend-mode: var(--blend, color); opacity: var(--panel-opacity, 0.85);';
  var fsBloomStyle = 'position: absolute; inset: 0; width: 100%; height: 100%; z-index: 2; mix-blend-mode: screen; pointer-events: none; opacity: var(--bloom-opacity, 0.45); display: ' + (st.bcOn ? 'block' : 'none') + ';';
  var camStyle = 'position: absolute; inset: 0; width: 100%; height: 100%; z-index: 2; pointer-events: none; object-fit: ' + camFit + '; mix-blend-mode: ' + (st.camBlend || 'normal') + '; opacity: ' + (fsv('camOp') / 100) + '; transform: scale(' + (fsv('camTiltH') / 100 * (st.camMirror ? -1 : 1)) + ', ' + fsv('camTiltV') / 100 + '); ' + (st.camOn ? '' : 'display: none;');
  var fsStageStyle = 'position: absolute; inset: 0; z-index: 5; display: flex; padding: 6%; pointer-events: none; align-items: ' + POSY[posY] + '; justify-content: ' + POSN[posX] + ';';
  // ИЗОЛЯЦИЯ ПРОБОВАЛАСЬ И СНЯТА (Раунд 57). Гипотеза была: слои свечения стоят
  // с `mix-blend-mode: screen`, смешиваются с подложкой, подложка — живой
  // WebGL-канвас Butterchurn, значит смена текста требует прочитать кадр
  // обратно с видеокарты. `isolation: isolate` эту связь разрывает.
  // Проверено на его машине: вида не изменило и фриз не убрало. Значит дело не
  // в смешивании — оставлять правку без пользы незачем.
  var fsWrapStyle = 'position: relative; font-family: var(--line-font, inherit); font-weight: ' + fsWeight + '; font-size: ' + fsSize + 'px; line-height: 1.06; letter-spacing: -0.01em; text-align: ' + (posX === 'слева' ? 'left' : (posX === 'справа' ? 'right' : 'center')) + '; ' + (варпГл ? '' : 'text-wrap: balance; ') + 'overflow-wrap: anywhere; color: ' + fsCol + ';';
  var fsBandStyle = 'position: absolute; left: 0; top: 0; width: 100%; height: 100%; z-index: 0; pointer-events: none;' + (selBg ? '' : ' display: none;');
  // СВЕЧЕНИЕ — ТЕНЬЮ, А НЕ ТРЕМЯ СЛОЯМИ-КОПИЯМИ (Раунд 57).
  //
  // Замерено в его приложении, перебором по кругу, при включённом Butterchurn
  // (кадр покоя 33 мс, то есть видеокарта уже под завязку):
  //     как есть (три слоя + фильтр)   ~1170 мс на смену строки
  //     свечение тенью, фильтр как есть 120…1000 мс
  //     свечение тенью, БЕЗ ВАРПА          33 мс  ← обычный кадр, то есть ноль
  //     свечение тенью, без фильтра вовсе   33 мс
  // и отдельно первым кругом: слои свечения без всякого фильтра — ~350 мс.
  //
  // То есть платят две вещи и обе структурные: каждый слой с `filter` — это
  // отдельная растеризация на процессоре, которая потом ждёт очереди на
  // насыщенной видеокарте. Три слоя свечения стоят ~350 мс, SVG-искажение —
  // ~700 мс. Размытие текста не стоит НИЧЕГО: замер без варпа его сохраняет.
  //
  // Тень не заводит слоя вовсе — она рисуется вместе с самим текстом. Формула
  // взята из его собственного дизайна «Freestyle Optimized», где строка это
  // один <h1> с text-shadow: радиусы 5+g*0.05, 12+g*0.1, 24+g*0.3, плотности
  // 0.85 / 0.6 / 0.4. Туда он пришёл сам, когда чинил фризы в дизайне; наш порт
  // взяли из более раннего «Editor First», где ещё слои, — оттуда и регресс.
  var fsGlowRgb = (function (c) {
    if (!c) return '255,255,255';
    var m = String(c).match(/^#?([0-9a-f]{6})$/i);
    if (!m) return '255,255,255';
    var v = parseInt(m[1], 16);
    return ((v >> 16) & 255) + ',' + ((v >> 8) & 255) + ',' + (v & 255);
  })(glowCol);
  var fsGlowPx = Math.max(0, L('glow', 140));
  var fsGlowShadow = fsGlowPx <= 0 ? '' :
    ' text-shadow: 0 0 ' + Math.round(5 + fsGlowPx * 0.05) + 'px rgba(' + fsGlowRgb + ', 0.85), '
    + '0 0 ' + Math.round(12 + fsGlowPx * 0.1) + 'px rgba(' + fsGlowRgb + ', 0.6), '
    + '0 0 ' + Math.round(24 + fsGlowPx * 0.3) + 'px rgba(' + fsGlowRgb + ', 0.4);';
  // НА НЕВИДИМЫЙ СЛОЙ ФИЛЬТРЫ НЕ ВЕШАЕМ ВОВСЕ (Раунд 57, починка починки).
  //
  // Когда строку рисует видеокарта, этот слой прозрачен — он остаётся только
  // ради размера обёртки и прямоугольников подложки. А фильтры на нём всё
  // равно считались: браузер честно растеризует прозрачное. Владелец выкрутил
  // искажение на 400, и мой же порог хроматики `(taber/100)×(20+искажение×0.09)`
  // перевалил за полпикселя — включился САМЫЙ ДОРОГОЙ фильтр, с тремя картами
  // смещения, на слой, которого не видно. Замер: 17 мс до, 415-903 после.
  // Туда же уходило и размытие — поэтому оно пропало из вида: считалось на
  // прозрачном, а на видимой строке его не было.
  var fsSharpStyle = 'white-space: pre-line; position: relative;' + selFx
    + (варпГл ? '' : (fsTextBlur > 0 || fsTextWarp > 0 || tAberOn || expo !== 100 ? ' filter: ' + fsLineFilter + expoFx + ';' : ''))
    // Слой на видеокарте рисует ту же строку сам, поэтому здешнюю гасим — но
    // ОСТАВЛЯЕМ В РАЗМЕТКЕ: по ней считаются размер обёртки (fitLine) и
    // прямоугольники подложки (paintBand). Убрать её значило бы потерять и то,
    // и другое ради одного невидимого слоя.
    + (варпГл ? ' color: transparent; text-shadow: none;' : fsGlowShadow);
  var fsPostfxStyle = 'position: absolute; inset: 0; z-index: 5; overflow: hidden; pointer-events: none; contain: paint; display: ' + (fsPostfxOn ? 'block' : 'none') + ';';
  var fsPostfxInnerStyle = 'position: absolute; left: 37.5%; top: 37.5%; width: 25%; height: 25%; transform: scale(4); transform-origin: center; backdrop-filter: ' + (fsPostfxFx || 'none') + '; -webkit-backdrop-filter: ' + (fsPostfxBlur > 0 ? 'blur(' + fsPostfxBlur + 'px)' : 'none') + ';';
  var fsGrainStyle = 'position: absolute; inset: 0; width: 100%; height: 100%; z-index: 6; pointer-events: none; opacity: var(--grain-opacity, 0.18); image-rendering: ' + (fsv('gsize') > 1.5 && fsv('gblur') === 0 ? 'pixelated' : 'auto') + '; mix-blend-mode: ' + (st.grainBlend || 'overlay') + '; filter: ' + ((fsv('gblur') > 0 ? 'blur(' + fsv('gblur') + 'px) ' : '') + ((st.grainMode || 'плёнка') === 'уголь' ? 'grayscale(1) brightness(0.85)' : '') || 'none') + ';';

  return (
    <div style={s(fsShellStyle)}>
      {/* fitStage() правит left/top/width/height этого узла императивно — React их не трогает,
          пока строка стиля не меняется (s() отдаёт один и тот же объект).
          onInput здесь ради скрытых входов ниже: профиль сцены применяется
          через poke() (input-событие), и трек-гейн должен доехать до аудио —
          панель настроек в этом поддереве не лежит, двойной обработки нет */}
      <div id="freestyle-stage" className={fsStageClass} onInput={(e) => c.onCardInput && c.onCardInput(e)}
        style={s('position: absolute; inset: 0; overflow: hidden; background: #141414; color-scheme: dark;')}>

        <div ref={c.fsRef('fsInnerRef')} style={s(fsInnerStyle)}>
          {/* key — НЕ украшение (Раунд 56). При перезапуске движка канвас
              обязан быть НОВЫМ: dispose гасит контекст через loseContext, а
              канвас с потерянным контекстом нового уже не выдаст — getContext
              вернёт тот же мёртвый. Butterchurn создаёт против него сэмплеры,
              получает null и падает с «Argument 1 ('sampler')… must be an
              instance of WebGLSampler». Смена key заставляет React выбросить
              элемент и смонтировать чистый, с живым контекстом. */}
          <canvas id="bcCanvas" key={'bc' + (st.bcEpoch || 0)} style={s(fsBcStyleCanvas)}></canvas>
          <div className="colorLayer" style={s(fsColorLayerStyle)}></div>
          {/* размытие фона: маленький слой, растянутый вчетверо, — так backdrop-filter
              стоит вчетверо дешевле при том же радиусе */}
          <div className="blurScrim" style={s('position: absolute; inset: 0; z-index: 4; overflow: hidden; pointer-events: none;')}>
            <div className="blurScrim-inner" style={s('position: absolute; left: 37.5%; top: 37.5%; width: 25%; height: 25%; transform: scale(4); transform-origin: center; backdrop-filter: blur(calc(var(--bg-blur, 0px) / 4)); -webkit-backdrop-filter: blur(calc(var(--bg-blur, 0px) / 4));')}></div>
          </div>
          <canvas id="bloomCanvas" style={s(fsBloomStyle)}></canvas>
          <video ref={c.fsRef('camRef')} autoPlay muted playsInline style={s(camStyle)}></video>

          {/* скрытые входы движка и аудио-графа: их контракт — id.
              Модули freestyle/audio.js и freestyle/engine.js находят их сами */}
          <input type="file" id="trackFile" accept="audio/*" onChange={(e) => c.onTrackFile(e)} style={s('display: none;')} />
          <span id="trackLabel" style={s('position: absolute; width: 0; height: 0; overflow: hidden; opacity: 0; pointer-events: none;')}></span>
          <input type="range" id="trackGainSlider" min="0" max="100" defaultValue="80" style={s('display: none;')} />
          <button type="button" id="btnTrackStop" aria-hidden="true" onClick={() => { if (c.state.trackOn) c.fsToggleTrack(); }} style={s('display: none;')}></button>
          <div style={s('display: none;')}>
            <button type="button" id="btnToggleLine"></button>
            <button type="button" id="btnToggleText"></button>
            <button type="button" id="btnToggleBg"></button>
            <input type="range" id="popoverBlurSlider" min="0" max="60" defaultValue="0" />
            <input type="range" id="popoverBendSlider" min="0" max="400" defaultValue="40" />
            <input type="range" id="popoverZoomSlider" min="10" max="600" defaultValue="100" />
            <button type="button" id="popoverAberrationBtn"></button>
            <input type="range" id="fsTabOffsetXSlider" min="-2000" max="2000" defaultValue="0" />
            <input type="range" id="fsTabOffsetYSlider" min="-2000" max="2000" defaultValue="0" />
          </div>

          <div className="stage" ref={c.fsRef('fsStageRef')} style={s(fsStageStyle)}>
            <div className="lineWrap" ref={c.fsRef('fsWrapRef')} style={s(fsWrapStyle)}>
              {/* #line — строчный узел движка; свою строку рисуют слои ниже */}
              <div className="line" id="line" ref={c.fsRef('fsLineRef')} style={s('display: none;')}></div>
              <div aria-hidden="true" data-fsband="1" style={s(fsBandStyle)}></div>
              {/* текст этих слоёв пишет paintLine() — React держит их пустыми */}
              {/* Три слоя-копии свечения вырезаны (Раунд 57) — свечение теперь
                  тенью на резком слое, см. fsGlowShadow. Замерено: сами по себе
                  эти слои стоили ~350 мс на каждую смену строки. */}
              <div data-fsline="1" aria-hidden="true" style={s(aberLayer(-fsAberPx, '#ff2d55'))}></div>
              <div data-fsline="1" aria-hidden="true" style={s(aberLayer(fsAberPx, '#00e0ff'))}></div>
              <div data-fsline="1" data-fssharp="1" style={s(fsSharpStyle)}></div>
              {/* Строка на видеокарте: холст накрывает обёртку с запасом под
                  ореол. Текст в него пишет c.fsВарп() — см. methods.fs.js. */}
              {варпГл ? (
                <canvas data-fswarp="1" aria-hidden="true" ref={c.fsRef('warpRef')}
                  style={s('position: absolute; inset: -70px; width: calc(100% + 140px);'
                    + ' height: calc(100% + 140px); pointer-events: none;')} />
              ) : null}
            </div>
            {/* Раунд 57: пока сцена пуста и сервер греется — говорим, чем он
                занят и сколько уже. Текст даёт c.fsЖдём() из state.jobs, то
                есть из того же /api/status, что и шапка; пришла строка —
                надпись гаснет сама. */}
            {c.fsЖдём && c.fsЖдём() ? (
              <div aria-live="polite" style={s(
                'position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);'
                + ' font: 11px/1.8 ui-monospace, SFMono-Regular, Menlo, monospace;'
                + ' letter-spacing: 0.14em; text-transform: uppercase; text-align: center;'
                + ' white-space: pre-line; color: rgba(255,255,255,0.42);'
                + ' pointer-events: none; user-select: none;')}>{c.fsЖдём()}</div>
            ) : null}
          </div>

          <div className="fs-postfx-layer" style={s(fsPostfxStyle)}>
            <div id="fsPostfxInner" style={s(fsPostfxInnerStyle)}></div>
          </div>
          <canvas id="grainCanvas" style={s('display: none;')}></canvas>
          <canvas ref={c.fsRef('grainRef')} style={s(fsGrainStyle)}></canvas>
        </div>

      </div>
    </div>
  );
}

// Кнопка записи (шаблон 806) здесь НЕ живёт: в дизайне она стоит внутри
// fs-блока шапки, и там её рисует renderFsBar (render.fspanels.jsx). Два
// элемента с id="btnRecord" были бы вторым источником правды.
