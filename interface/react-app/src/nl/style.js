// Стили дизайна «Editor First»: инлайновые строки макета → объекты React,
// hover-правила и базовый CSS из helmet. Дизайн — источник истины: строки
// стилей переносятся дословно, а этот модуль их только парсит.

// ---- s(): 'a: b; c: d' → { a: 'b', c: 'd' } -------------------------------

const _sCache = new Map();

// разрез по ';' с уважением к скобкам и кавычкам — url(...) и data:-URI не режем
function splitDecls(css) {
  const out = [];
  let depth = 0, quote = '', cur = '';
  for (let i = 0; i < css.length; i++) {
    const ch = css[i];
    if (quote) { if (ch === quote) quote = ''; cur += ch; continue; }
    if (ch === '"' || ch === "'") { quote = ch; cur += ch; continue; }
    if (ch === '(') depth++;
    if (ch === ')') depth = depth > 0 ? depth - 1 : 0;
    if (ch === ';' && !depth) { out.push(cur); cur = ''; continue; }
    cur += ch;
  }
  if (cur.trim()) out.push(cur);
  return out;
}

// -webkit-x → WebkitX, -moz-x → MozX, -ms-x → msX — так их понимает React
function camel(prop) {
  const c = prop.replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
  return prop.startsWith('-ms-') ? c.charAt(0).toLowerCase() + c.slice(1) : c;
}

// строка инлайн-стиля из макета → объект стилей React; кэш по строке —
// одни и те же строки шаблона парсятся один раз за жизнь приложения
export function s(css) {
  if (!css) return undefined;
  let obj = _sCache.get(css);
  if (obj) return obj;
  obj = {};
  for (const decl of splitDecls(css)) {
    const i = decl.indexOf(':');
    if (i < 0) continue;
    const prop = decl.slice(0, i).trim();
    const val = decl.slice(i + 1).trim();
    if (!prop || !val) continue;
    // кастомные свойства (--canvas) React принимает как есть
    obj[prop.startsWith('--') ? prop : camel(prop)] = val;
  }
  _sCache.set(css, obj);
  return obj;
}

// ---- hov(): style-hover="..." из макета → класс с :hover-правилом ---------

function hash(str) {
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

function sheetEl(id) {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement('style');
    el.id = id;
    document.head.appendChild(el);
  }
  return el;
}

const _hovDone = new Set();

// правило .nl-hov-<хэш>:hover{...} инжектится один раз, дальше отдаём готовый класс
export function hov(css) {
  const cls = 'nl-hov-' + hash(css);
  if (!_hovDone.has(cls)) {
    _hovDone.add(cls);
    sheetEl('nl-hov').textContent += '.' + cls + ':hover{' + css + '}\n';
  }
  return cls;
}

// ---- injectBase(): helmet-CSS дизайна дословно ----------------------------
// Google Fonts из макета сознательно не переносится (офлайн-инвариант):
// 'JetBrains Mono' в системе нет — честный фолбэк на ui-monospace.

const BASE_CSS = `
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  button, input { font-family: inherit; }
  ::selection { background: var(--ink); color: var(--canvas); }
  a { color: var(--ink); } a:hover { color: var(--muted); }
  /* строки настроек: волосок ставим правилом — первую в группе инлайном не отличить,
     а часть строк рождается из одного шаблона sc-for */
  [data-row="1"] + [data-row="1"] { border-top: 1px solid var(--border-subtle); }
  /* один правый столбец у всех строк: ползунки, списки, плашки заканчиваются на одной линии */
  [data-row="1"] input[type="range"] { width: 104px; }
  [data-pa] input[type="range"] { width: 104px; }
  [data-row="1"] select { width: 146px; max-width: 146px; }
  /* Правила [contenteditable] (снятие обводки и подсказка-плейсхолдер через
     data-ph) вырезаны 2026-08-18 вместе с редактором: редактируемых узлов в
     приложении не осталось ни одного. */
  input[type="text"], input[type="number"] { outline: none; }
  input[type="number"] { -moz-appearance: textfield; appearance: textfield; }
  input[type="number"]::-webkit-outer-spin-button, input[type="number"]::-webkit-inner-spin-button { -webkit-appearance: none; appearance: none; margin: 0; }
  select { -webkit-appearance: none; -moz-appearance: none; appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'%3E%3Cpath d='M1 1.4 5 5 9 1.4' fill='none' stroke='%23888888' stroke-width='1.2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 7px center; background-size: 8px 5px; }
  select::-ms-expand { display: none; }
  /* Ползунок — часть инструментальной панели, а не системная «капсула».
     Волосок и прямоугольный бегунок продолжают геометрию полей и разделителей. */
  input[type="range"] { -webkit-appearance: none; appearance: none; width: 100%; height: 16px; background: transparent; border: none; border-radius: 0; outline: none; cursor: ew-resize; }
  input[type="range"]::-webkit-slider-runnable-track { height: 1px; background: var(--border-soft); border: none; }
  input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none; appearance: none; width: 8px; height: 12px; margin-top: -5.5px; border: 1px solid var(--ink); border-radius: 1px; background: var(--menu-bg); cursor: ew-resize; transition: background-color 0.12s var(--ease); }
  input[type="range"]:hover::-webkit-slider-thumb { background: var(--ink); }
  input[type="range"]::-moz-range-track { height: 1px; background: var(--border-soft); border: none; }
  input[type="range"]::-moz-range-thumb { width: 8px; height: 12px; border: 1px solid var(--ink); border-radius: 1px; background: var(--menu-bg); cursor: ew-resize; }
  button:focus-visible, input:focus-visible, select:focus-visible, [role="button"]:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }
  input[type="range"]:focus-visible { outline: 1px solid var(--ink); outline-offset: 2px; }
  /* Один знак выбора везде: квадрат внутри отдельной зоны клика. Поэтому на
     телефоне зона растёт до 44 px, а сам знак не превращается в гигантский. */
  .nl-check, .nl-check-mark { display: inline-grid; place-items: center; flex-shrink: 0; }
  .nl-check { width: 20px; height: 20px; min-width: 20px; min-height: 20px; padding: 0; border: 0; background: transparent; }
  .nl-check::before, .nl-check-mark::before { content: ''; display: block; width: 10px; height: 10px; border: 1px solid var(--border-soft); border-radius: 1px; background: transparent; }
  .nl-check[data-on="1"]::before, .nl-check-mark[data-on="1"]::before { border-color: var(--ink); background: var(--ink); box-shadow: inset 0 0 0 2px var(--menu-bg); }
  .nl-check[data-busy="1"]::before { animation: nlGenPulse 1s var(--ease) infinite; }
  .nl-check-mark { width: 12px; height: 12px; }
  [data-stanza-line-head], [data-stanza-line] { display: grid; grid-template-columns: 18px 24px 78px minmax(0, 1fr) 20px; align-items: center; column-gap: 5px; }
  [data-stanza-line-head] { min-height: 16px; padding: 0 2px; font-size: 9px; color: var(--muted-soft); }
  [data-stanza-line] { min-height: 21px; padding: 1px 2px; }
  [data-stanza-syllables] { display: grid; grid-template-columns: 32px 10px 32px; align-items: center; }
  [data-gate-row] { display: grid; grid-template-columns: 78px minmax(0, 1fr); align-items: center; gap: 3px 7px; padding: 2px 0; min-height: 20px; }
  .nl-gate-label { grid-column: 1; font-size: 10.5px; color: var(--muted); white-space: nowrap; }
  .nl-picks { grid-column: 2; display: flex; flex-wrap: wrap; gap: 3px; }
  .nl-gate-tail { grid-column: 2; font-size: 9px; color: var(--muted-soft); }
  .nl-gate-share { grid-column: 2; }
  /* Desktop-плотность: панели — рабочий инструмент, а не мобильная форма.
     20 px — нижняя граница для строки с текущим размером шрифта: текст не
     режется, но контрол не превращается в мобильную плашку. Тач-минимумы
     возвращаются отдельным правилом в mobile media-query ниже. */
  [data-panel] button, [data-panel] input, [data-panel] select { min-height: 20px; }
  /* У ползунка свой размер: 12 px thumb уже даёт точную визуальную метку,
     а лишняя высота вокруг него и была главным источником крупных «крутилок». */
  [data-panel] input[type="range"] { min-height: 16px; }
  [data-panel] input[type="text"], [data-panel] input[type="number"], [data-panel] select { font-size: 11px; }
  [data-panel] button { touch-action: manipulation; }
  /* Основной хром — часть ориентации, а не скрытая декорация. На тач-экране
     наведения нет, поэтому статус и команды должны быть видны сразу. */
  [data-chrome] { opacity: 1; transition: opacity 170ms var(--ease); }
  /* во фристайле хром — плавающий слой поверх сцены: высоты не занимает, но свою плашку несёт,
     и гаснет вместе с ней. !important обязателен: у самой шапки position стоит инлайном */
  [data-chrome][data-float] { position: absolute !important; top: 0; left: 0; right: 0; background: var(--canvas); }
  /* :focus-within держал панель открытой после клика по вкладке — мышь уже ушла, а фокус остался.
     :focus-visible реагирует на клавиатуру и текстовые поля, но не на клик мышью */
  [data-chrome]:hover, [data-chrome]:has(:focus-visible) { opacity: 1; transition: opacity 170ms var(--ease); }
  /* РЕЖИМ ЗАПИСИ: хром заперт наглухо, пока на корне висит data-reclock="1".
     Не «прячется до наведения», а не проявляется ВООБЩЕ — случайно вывести
     интерфейс в кадр нельзя (решение пользователя по видео, 2026-08-01).
     Гасим три пути разом: hover, focus-visible и сами клики (pointer-events),
     иначе панель, открытая клавиатурой или оставшимся фокусом, всё равно
     влезла бы в запись. !important обязателен: правило выше поднимает opacity
     тем же весом, и порядок объявлений тут решать не должен */
  [data-reclock="1"] [data-chrome],
  [data-reclock="1"] [data-chrome]:hover,
  [data-reclock="1"] [data-chrome]:has(:focus-visible) {
    opacity: 0 !important; pointer-events: none !important; transition: none !important;
  }
  /* лента листается без системной полосы; в панелях настроек она остаётся — там она нужна */
  [data-noscrollbar] { scrollbar-width: none; -ms-overflow-style: none; }
  [data-noscrollbar]::-webkit-scrollbar { width: 0; height: 0; display: none; }
  ::-webkit-scrollbar { width: 7px; }
  ::-webkit-scrollbar-thumb { background: var(--border-soft); border-radius: var(--radius); }
  ::-webkit-scrollbar-track { background: transparent; }
  @keyframes streamIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  /* строка-заполнитель на месте будущей строфы: прогон идёт секунды, и он
     должен быть виден ТАМ, КУДА вставится текст, а состояние — в панели работ
     (2026-08-02, требование: видеть прямо в строке) */
  @keyframes nlGenPulse { 0%, 100% { opacity: 0.32; } 50% { opacity: 0.9; } }
  [data-genrow] { animation: nlGenPulse 1.15s var(--ease) infinite; }
  @media (prefers-reduced-motion: reduce) { [data-genrow] { animation: none; opacity: 0.7; } }
  /* единая анимация всех попапов: data-pa задаёт направление, data-po помечает закрытие */
  @keyframes popIn { from { opacity: 0; transform: translateY(-6px) scale(0.975); } to { opacity: 1; transform: none; } }
  @keyframes popOut { from { opacity: 1; transform: none; } to { opacity: 0; transform: translateY(-5px) scale(0.985); } }
  @keyframes popInUp { from { opacity: 0; transform: translateY(6px) scale(0.975); } to { opacity: 1; transform: none; } }
  @keyframes popOutUp { from { opacity: 1; transform: none; } to { opacity: 0; transform: translateY(5px) scale(0.985); } }
  [data-pa="down"] { animation: popIn 190ms var(--ease-spring); transform-origin: top center; }
  [data-pa="up"] { animation: popInUp 190ms var(--ease-spring); transform-origin: bottom center; }
  [data-pa="down"][data-po] { animation: popOut 140ms var(--ease) forwards; pointer-events: none; }
  [data-pa="up"][data-po] { animation: popOutUp 140ms var(--ease) forwards; pointer-events: none; }
  @media (prefers-reduced-motion: reduce) { [data-pa] { animation-duration: 1ms !important; } }
  @keyframes nlJobSweep { from { transform: translateX(-140%); } to { transform: translateX(420%); } }
  @keyframes nlJobsSpin { from { transform: rotate(-90deg); } to { transform: rotate(270deg); } }
  .nl-jobs-indeterminate { transform-box: fill-box; transform-origin: center; animation: nlJobsSpin 1.4s linear infinite; }
  @media (prefers-reduced-motion: reduce) { .nl-jobs-indeterminate { animation: none; } }
  @media (max-width: 640px) {
    [data-panel="popover"] { position: fixed !important; top: auto !important; right: 12px !important; bottom: 12px !important; left: 12px !important; width: auto !important; max-width: none !important; max-height: calc(100dvh - 24px) !important; overflow-y: auto !important; padding: 16px !important; border-radius: 6px !important; }
    [data-panel="settings"] { position: fixed !important; top: 12px !important; right: 12px !important; bottom: 12px !important; left: 12px !important; width: auto !important; max-width: none !important; max-height: calc(100dvh - 24px) !important; overflow-y: auto !important; padding: 16px !important; }
    [data-panel] button, [data-panel] input, [data-panel] select { min-height: 44px; min-width: 44px; }
    [data-panel] input[type="range"] { min-height: 44px; }
    /* Цветная точка остаётся 20 px, 44 px — только прозрачная зона касания.
       Иначе мобильный стандарт сделал бы саму палитру визуально огромной. */
    [data-panel] button.nl-swatch { min-width: 44px; width: 44px; height: 44px; padding: 12px !important; background-clip: content-box !important; }
    [data-panel] button { padding-top: 9px; padding-bottom: 9px; }
    [data-panel] .nl-check { width: 44px; height: 44px; padding: 0; }
    [data-stanza-line-head], [data-stanza-line] { grid-template-columns: 24px 44px 100px minmax(0, 1fr) 44px; column-gap: 6px; }
    [data-stanza-syllables] { grid-template-columns: 44px 12px 44px; }
    [data-gate-row] { grid-template-columns: 1fr; gap: 4px; padding: 5px 0; }
    .nl-gate-label, .nl-picks, .nl-gate-tail, .nl-gate-share { grid-column: 1; }
    [data-panel] input[type="text"], [data-panel] input[type="number"], [data-panel] select { font-size: 16px; }
    /* В freestyle шапка состоит из двух разных рядов. Раньше длинный ряд
       инструментов оставался flex-элементом слева и физически залезал под
       вкладки: сцена была видна, но клик уходил в «freestyle». */
    [data-chrome][data-float] {
      display: grid !important;
      grid-template-columns: 1fr auto 1fr;
      grid-template-rows: auto auto;
      align-items: center;
      align-content: start;
      gap: 4px 8px !important;
      padding: 8px 12px !important;
    }
    [data-chrome][data-float] > div:first-child {
      grid-column: 1 / -1;
      grid-row: 2;
      width: 100%;
      min-width: 0 !important;
      overflow-x: auto;
      overflow-y: hidden;
      scrollbar-width: none;
      padding: 3px 0;
    }
    [data-chrome][data-float] > div:first-child::-webkit-scrollbar { display: none; }
    [data-chrome][data-float] > div:first-child > div {
      width: max-content;
      min-width: max-content;
    }
    [data-chrome][data-float] > nav {
      grid-column: 1 / -1;
      grid-row: 1;
      justify-self: center;
    }
    [data-chrome][data-float] > div:last-child {
      position: absolute;
      top: 8px;
      right: 12px;
      width: auto;
      min-width: 0 !important;
    }
  }
  /* На сенсорном экране hover не существует. Действия строки должны быть
     видимы сразу, иначе «копировать/изменить/вернуть» фактически пропадают. */
  @media (hover: none) {
    .nl-list .nl-acts { opacity: 1; }
  }
  @keyframes recPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.45; } }
  /* без @property смена --panel считается дискретной и transition её не анимирует */
  @property --panel { syntax: '<color>'; inherits: true; initial-value: transparent; }
  /* строки пресетов, свотчи палитры и класс .active рисует сам движок — дотянуться инлайном нельзя */
  /* Общий список (Раунд 40). Замечание про выпадашку строф: показана плохо, список пресетов во фристайле выглядит
  лаконичнее.. Так что правила пресетов вынесены в класс и
     переиспользуются: формы строф, избранное, история. */
  .nl-list { display: flex; flex-direction: column; gap: 1px; max-height: 300px; overflow-y: auto; }
  /* Время — СЛЕВА от текста (замечание: время показывалось слева от текста без причины). Пустая ячейка схлопывается вместе с
     просветом, поэтому в избранном, где времени нет, ряд не съезжает. */
  .nl-list .nl-row { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 6px; padding: 3px 5px; border-radius: var(--radius); }
  .nl-list .nl-when { font-size: 9px; color: var(--muted-soft); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .nl-list .nl-when:empty { display: none; }
  .nl-list .nl-row:hover { background: color-mix(in srgb, var(--ink) 5%, transparent); }
  .nl-list .nl-row.current { background: color-mix(in srgb, var(--ink) 10%, transparent); }
  .nl-list .nl-name { min-width: 0; font-size: 10.5px; line-height: 1.5; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; background: none; border: none; padding: 0; text-align: left; font-family: inherit; }
  .nl-list .nl-row:hover .nl-name, .nl-list .nl-row.current .nl-name { color: var(--ink); }
  /* Тег — подпись В ЦВЕТЕ ТЕМЫ, без плашки. Жёлтая плашка, которую увидел
     пользователь, приезжала из мёртвого index.css: там был свой .nl-tag
     старого интерфейса (#d9a441). Файл вычищен, имя теперь наше. */
  .nl-list .nl-tag { font-size: 9px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted-soft); background: none; white-space: nowrap; }
  .nl-list .nl-tag:empty { display: none; }
  /* Действия проявляются по наведению: список читается как список, а не как
     панель кнопок, но всё под рукой без лишнего клика. */
  .nl-list .nl-acts { display: flex; gap: 2px; opacity: 0; transition: opacity 0.12s var(--ease); }
  .nl-list .nl-row:hover .nl-acts, .nl-list .nl-row:focus-within .nl-acts { opacity: 1; }
  .nl-list .nl-acts button { background: none; border: none; padding: 2px 4px; font-size: 10.5px; line-height: 1; color: var(--muted-soft); cursor: pointer; font-family: inherit; }
  .nl-list .nl-acts button:hover { color: var(--ink); }
  .nl-list .nl-edit { width: 100%; background: none; border: none; border-bottom: 1px solid var(--border-soft); padding: 2px 0; font-family: inherit; font-size: 10.5px; color: var(--ink); }
  #presetPanel { display: flex; flex-direction: column; gap: 1px; max-height: 288px; overflow-y: auto; }
  #presetPanel .presetRow { display: grid; grid-template-columns: 13px 1fr auto; align-items: center; gap: 6px; padding: 2px 4px; border-radius: var(--radius); }
  #presetPanel .presetRow:hover { background: color-mix(in srgb, var(--ink) 5%, transparent); }
  #presetPanel .presetRow.active, #presetPanel .presetRow.current { background: color-mix(in srgb, var(--ink) 10%, transparent); }
  #presetPanel .presetName { appearance: none; width: 100%; min-width: 0; border: none; background: none; padding: 5px 0; font: inherit; font-size: 9px; line-height: 1.4; color: var(--muted); text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
  #presetPanel .presetRow:hover .presetName, #presetPanel .presetRow.active .presetName { color: var(--ink); }
  #presetPanel .presetStar { font-size: 10.5px; line-height: 1; color: var(--border-soft); cursor: pointer; background: none; border: none; padding: 0; }
  #presetPanel .presetStar.on, #presetPanel .presetStar.active, #presetPanel .presetStar:hover { color: var(--ink); }
  #presetPanel .presetTag { font-size: 9px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted-soft); }
  /* выбранный цвет отмечается кольцом, а не заливкой — иначе теряется сам цвет */
  /* движок метит свои тумблеры классом active — инлайн-стиль кнопки иначе перебивает подсветку */
  #fsSetPanel button.active:not(.swatch) { background: var(--ink) !important; color: var(--canvas) !important; }
  #fsSetPanel select option { background: var(--canvas); color: var(--ink); }
  #fsSetPanel input[type="color"] { width: 20px; height: 20px; padding: 0; border: none; border-radius: 50%; background: none; cursor: pointer; overflow: hidden; }
  #fsSetPanel input[type="color"]::-webkit-color-swatch-wrapper { padding: 0; border-radius: 50%; }
  #fsSetPanel input[type="color"]::-webkit-color-swatch { border: none; border-radius: 50%; }
  /* пипетка = «свой цвет»: отделяем её от готовых кружков палитры кольцом с зазором */
  #fsSetPanel input[type="color"] { box-shadow: 0 0 0 1px var(--border-soft), 0 0 0 3px var(--menu-bg), 0 0 0 4px var(--border-subtle); margin-right: 4px; }
  #fsSetPanel input[type="color"]:hover { box-shadow: 0 0 0 1px var(--border-soft), 0 0 0 3px var(--menu-bg), 0 0 0 4px var(--muted-soft); }
  /* свечение интерфейса: текст берёт text-shadow, иконки — этот фильтр (на стеклянные панели не вешаем: filter ломает backdrop) */
  header svg, footer svg, button > svg { filter: var(--ui-glow, none); }
  [data-ui-glow] *:not(svg):not(path):not(circle):not(rect):not(line):not(polyline):not(polygon) { text-shadow: var(--ui-text-glow, none); }
`;

// вставить базовый CSS дизайна один раз; повторный вызов — no-op
export function injectBase() {
  if (document.getElementById('nl-base')) return;
  const el = document.createElement('style');
  el.id = 'nl-base';
  el.textContent = BASE_CSS;
  document.head.appendChild(el);
}
