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
  [data-row="1"] input[type="range"] { width: 146px; }
  [data-pa] input[type="range"] { width: 146px; }
  [data-row="1"] select { width: 146px; max-width: 146px; }
  [contenteditable] { outline: none; }
  [contenteditable]:empty::before { content: attr(data-ph); color: var(--muted-soft); }
  input[type="text"], input[type="number"] { outline: none; }
  input[type="number"] { -moz-appearance: textfield; appearance: textfield; }
  input[type="number"]::-webkit-outer-spin-button, input[type="number"]::-webkit-inner-spin-button { -webkit-appearance: none; appearance: none; margin: 0; }
  select { -webkit-appearance: none; -moz-appearance: none; appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'%3E%3Cpath d='M1 1.4 5 5 9 1.4' fill='none' stroke='%23888888' stroke-width='1.2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 7px center; background-size: 8px 5px; }
  select::-ms-expand { display: none; }
  input[type="range"] { -webkit-appearance: none; appearance: none; width: 100%; height: 1px; background: var(--border-soft); border: none; border-radius: 1px; outline: none; cursor: pointer; }
  input[type="range"]::-webkit-slider-runnable-track { height: 1px; background: transparent; border: none; }
  input[type="range"]::-webkit-slider-thumb { -webkit-appearance: none; appearance: none; width: 11px; height: 11px; margin-top: -5px; border: none; border-radius: 50%; background: var(--ink); cursor: pointer; transition: transform 0.12s var(--ease); }
  input[type="range"]:hover::-webkit-slider-thumb { transform: scale(1.16); }
  input[type="range"]::-moz-range-track { height: 1px; background: var(--border-soft); border: none; }
  input[type="range"]::-moz-range-thumb { width: 11px; height: 11px; border: none; border-radius: 50%; background: var(--ink); cursor: pointer; }
  input[type="range"]:focus, input[type="range"]:focus-visible { outline: none; }
  /* хром редактора и фристайла: виден только под курсором — открытый попап панель не проявляет.
     уход мгновенный (переход объявлен только в состоянии «показан»), появление — плавное */
  [data-chrome] { opacity: 0; transition: opacity 0s; }
  /* во фристайле хром — плавающий слой поверх сцены: высоты не занимает, но свою плашку несёт,
     и гаснет вместе с ней. !important обязателен: у самой шапки position стоит инлайном */
  [data-chrome][data-float] { position: absolute !important; top: 0; left: 0; right: 0; background: var(--canvas); }
  /* :focus-within держал панель открытой после клика по вкладке — мышь уже ушла, а фокус остался.
     :focus-visible реагирует на клавиатуру и текстовые поля, но не на клик мышью */
  [data-chrome]:hover, [data-chrome]:has(:focus-visible) { opacity: 1; transition: opacity 170ms var(--ease); }
  /* РЕЖИМ ЗАПИСИ: хром заперт наглухо, пока на корне висит data-reclock="1".
     Не «прячется до наведения», а не проявляется ВООБЩЕ — случайно вывести
     интерфейс в кадр нельзя (решение владельца по видео, 2026-08-01).
     Гасим три пути разом: hover, focus-visible и сами клики (pointer-events),
     иначе панель, открытая клавиатурой или оставшимся фокусом, всё равно
     влезла бы в запись. !important обязателен: правило выше поднимает opacity
     тем же весом, и порядок объявлений тут решать не должен */
  [data-reclock="1"] [data-chrome],
  [data-reclock="1"] [data-chrome]:hover,
  [data-reclock="1"] [data-chrome]:has(:focus-visible) {
    opacity: 0 !important; pointer-events: none !important; transition: none !important;
  }
  /* документ листается без системной полосы; в панелях настроек она остаётся — там она нужна */
  [data-noscrollbar] { scrollbar-width: none; -ms-overflow-style: none; }
  [data-noscrollbar]::-webkit-scrollbar { width: 0; height: 0; display: none; }
  ::-webkit-scrollbar { width: 7px; }
  ::-webkit-scrollbar-thumb { background: var(--border-soft); border-radius: 3px; }
  ::-webkit-scrollbar-track { background: transparent; }
  @keyframes streamIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  /* строка-заполнитель на месте будущей строфы: прогон идёт секунды, и он
     должен быть виден ТАМ, КУДА вставится текст, а не только строкой статуса
     в углу (2026-08-02, владелец: «хочу видеть прям в строке») */
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
  @keyframes recPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.45; } }
  /* без @property смена --panel считается дискретной и transition её не анимирует */
  @property --panel { syntax: '<color>'; inherits: true; initial-value: transparent; }
  /* строки пресетов, свотчи палитры и класс .active рисует сам движок — дотянуться инлайном нельзя */
  /* Общий список (Раунд 40). Владелец про выпадашку строф: «отвратительно
     показан… гораздо лаконичнее выглядел список пресетов во фристайле, вот он
     там красиво реализован». Так что правила пресетов вынесены в класс и
     переиспользуются: формы строф, избранное, история. */
  .nl-list { display: flex; flex-direction: column; gap: 1px; max-height: 300px; overflow-y: auto; }
  /* Время — СЛЕВА от текста (владелец: «мы время показываем слева от
     текста, какого хуя оно там»). Пустая ячейка схлопывается вместе с
     просветом, поэтому в избранном, где времени нет, ряд не съезжает. */
  .nl-list .nl-row { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 8px; padding: 4px 6px; border-radius: 3px; }
  .nl-list .nl-when { font-size: 8.5px; color: var(--muted-soft); font-variant-numeric: tabular-nums; white-space: nowrap; }
  .nl-list .nl-when:empty { display: none; }
  .nl-list .nl-row:hover { background: color-mix(in srgb, var(--ink) 5%, transparent); }
  .nl-list .nl-row.current { background: color-mix(in srgb, var(--ink) 10%, transparent); }
  .nl-list .nl-name { min-width: 0; font-size: 10px; line-height: 1.5; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; background: none; border: none; padding: 0; text-align: left; font-family: inherit; }
  .nl-list .nl-row:hover .nl-name, .nl-list .nl-row.current .nl-name { color: var(--ink); }
  /* Тег — подпись В ЦВЕТЕ ТЕМЫ, без плашки. Жёлтая плашка, которую увидел
     владелец, приезжала из мёртвого index.css: там был свой .nl-tag
     старого интерфейса (#d9a441). Файл вычищен, имя теперь наше. */
  .nl-list .nl-tag { font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted-soft); background: none; white-space: nowrap; }
  .nl-list .nl-tag:empty { display: none; }
  /* Действия проявляются по наведению: список читается как список, а не как
     панель кнопок, но всё под рукой без лишнего клика. */
  .nl-list .nl-acts { display: flex; gap: 2px; opacity: 0; transition: opacity 0.12s var(--ease); }
  .nl-list .nl-row:hover .nl-acts, .nl-list .nl-row:focus-within .nl-acts { opacity: 1; }
  .nl-list .nl-acts button { background: none; border: none; padding: 2px 4px; font-size: 10px; line-height: 1; color: var(--muted-soft); cursor: pointer; font-family: inherit; }
  .nl-list .nl-acts button:hover { color: var(--ink); }
  .nl-list .nl-edit { width: 100%; background: none; border: none; border-bottom: 1px solid var(--border-soft); padding: 2px 0; font-family: inherit; font-size: 10px; color: var(--ink); }
  #presetPanel { display: flex; flex-direction: column; gap: 1px; max-height: 288px; overflow-y: auto; }
  #presetPanel .presetRow { display: grid; grid-template-columns: 13px 1fr auto; align-items: center; gap: 8px; padding: 3px 5px; border-radius: 3px; }
  #presetPanel .presetRow:hover { background: color-mix(in srgb, var(--ink) 5%, transparent); }
  #presetPanel .presetRow.active, #presetPanel .presetRow.current { background: color-mix(in srgb, var(--ink) 10%, transparent); }
  #presetPanel .presetName { font-size: 9px; line-height: 1.5; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
  #presetPanel .presetRow:hover .presetName, #presetPanel .presetRow.active .presetName { color: var(--ink); }
  #presetPanel .presetStar { font-size: 10.5px; line-height: 1; color: var(--border-soft); cursor: pointer; background: none; border: none; padding: 0; }
  #presetPanel .presetStar.on, #presetPanel .presetStar.active, #presetPanel .presetStar:hover { color: var(--ink); }
  #presetPanel .presetTag { font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted-soft); }
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
