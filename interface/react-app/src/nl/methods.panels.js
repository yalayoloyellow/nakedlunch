// Методы панелей из дизайна «Editor First» (project-notes/mockups/design-v2/
// Editor First.dc.html: JS-класс 3258..3294, renderVals 3406..3517 и inline-
// обработчики 4049..4097) — миксин: интегратор делает
// Object.assign(Nakedlunch.prototype, panelMethods).
// Раунд 50: крутилки и полки уехали в methods.shelves.js, панель — в
// render.gen.jsx. Здесь остались общие вещи попапов и настроек: ярусы сжатия
// шапки, стыки цепочки, порядок звеньев и вычислители общих настроек.

import * as api from './api.js';

// Раунд 50 — зеркало core/clean.py: KNOB_SPEC. Значения ПО УМОЛЧАНИЮ те же,
// что у профиля «Обычный» на полке, а он собран из измеренных положений
// пользователя (data/settings.json, nl_params на 2026-08-03).
//
// Чего здесь больше нет:
//   «Отбор» — стал бинарным переключателем режима (алгоритм/классика), а не
//     ползунком: пользователь 2026-08-03 «я бы сделал переключатель, бинарный».
//   «Разнообразие» — мертво с Раунда 48: вариант всегда один, MMR-отбору
//     между вариантами нечего разнообразить.
// Что появилось: «Клаузула» и «Связность» — они работали с Раунда 44, но
// дотянуться до них можно было ТОЛЬКО через референс.
export const PARAM_DEFAULTS = {
  'Источники': 1.0, 'Мат': -1.0, 'Клаузула': 0,
  'Точность рифм': 0.25, 'Мелодичность': 0.35, 'Банальность': 0.83,
  // 0 «не повторять» (прежнее поведение), 1 «можно» — Раунд 52, хук
  'Диссонанс': 0.7, 'Связность': -1.0, 'Повтор': 0,
};

// PRESET_CHAINS ВЫРЕЗАН (Раунд 55). Три готовые цепочки жили здесь константой
// ФРОНТА и полкой не были — а серия ищет цепочку по имени на полке. Пользователь:
// «пайплайн в серии выбирается же из профилей пайплайна, там же уже три
// сохранённых пресета есть, почему они не отображаются».
//
// Он прав: это были три готовых пайплайна, и то, что серия их не видела, —
// случайность реализации, а не замысел. Теперь они встроенные записи полки
// (core/chain_profiles.py: builtin), как встроенные формы строф и профили
// настроек, и приходят с бэка одним списком со своими.

// гарнитуры общих настроек — константа дизайна (FONTS_BASE, строка 2597)
export const FONTS_BASE = ['JetBrains Mono', 'Georgia', 'Helvetica'];

// рецепт кнопки-варианта в строках настроек — из renderVals дизайна (3410)
export function pickStyle(a) {
  return 'appearance: none; border: none; border-radius: 5px; padding: 3px 8px; font-size: 9px; letter-spacing: 0.01em; cursor: pointer; white-space: nowrap; transition: background-color 0.12s var(--ease), color 0.12s var(--ease); '
    + (a ? 'background: var(--ink); color: var(--canvas);' : 'background: color-mix(in srgb, var(--ink) 6.5%, transparent); color: var(--muted);');
}

// одна настройка — одна строка: подпись слева, контрол справа, единая высота.
// волосок ставим сверху всем, кроме первой, — так блок читается как список, а не как таблица
const CFGROW = 'display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 2px 10px; padding: 7px 10px; min-height: 32px;';

// подсказка под подписью — только там, где название непонятно без объяснения
function hint(it, text) { it.hint = text; return it; }

export const panelMethods = {

  // ---- пилюли шапки: одна открыта — остальные закрыты ----
  tog(p) { if (this.state.openPill === p) this.closePop(); else this.openPop({ openPill: p }); },

  // ---- сжатие шапки (Раунд 38) ---------------------------------------------
  // Пользователь: «когда открывается маленькое окошко, шапка и прочее не
  // подстраиваются под этот размер». Так и было: у обеих половин шапки стоял
  // `min-width: fit-content`, у самой шапки — `overflow: visible`, и при узком
  // окне правый край просто уезжал за экран. Замерено на окне 760: ширина
  // шапки 760, содержимого 1098, 50 элементов правее правого края, полосы
  // прокрутки нет — то есть тема, настройки и часы становились недоступны.
  //
  // Правило пользователя: «не согласен с логикой, что нужно убирать полностью.
  // Можно сжать до мелких значков». Поэтому ЯРУСЫ: ничего не исчезает,
  // подписи по очереди становятся короче, потом значками, отступы и просветы
  // ужимаются. Нижний ярус обязан помещаться в минимальное окно (720 —
  // min_size в launch.py).
  //
  //   0 — слова целиком, отступы дизайна;
  //   1 — просветы ужаты, «54 стр.» и часы уходят (число листа есть в его
  //       попапе, часы — в строке меню системы), «сохранено 12:44» → «12:44»;
  //   2 — «избранное 55» → «★ 55», «алгоритм» → «алг»;
  //   3 — только значки, числа уходят в подсказку.
  HDR_MAX: 3,
  hdr() { return Math.max(0, Math.min(this.HDR_MAX, this.state.hdrTier | 0)); },
  // Выбрать форму по ярусу. Массив короче четырёх — последняя форма держится
  // до конца: не всё сжимается в четыре ступени, и выдумывать их незачем.
  hdrPick(формы) { return формы[Math.min(this.hdr(), формы.length - 1)]; },

  hdrFit() {
    var el = this._hdrEl;
    if (!el) return;
    // scrollWidth при `overflow: visible` честно показывает вылет — на этом и
    // построен замер: содержимое не сжимается само (min-width: fit-content),
    // поэтому разница между ним и clientWidth и есть «не влезло».
    var есть = el.clientWidth, надо = el.scrollWidth, т = this.hdr();
    var поднялись = this._hdrUp || (this._hdrUp = {});
    if (надо > есть + 1 && т < this.HDR_MAX) {
      поднялись[т + 1] = есть;      // при какой ширине пришлось сжаться
      this.setState({ hdrTier: т + 1 });
    } else if (т > 0 && есть > (поднялись[т] || 0) + 48) {
      // 48 — гистерезис. Без него на самой границе ярус дрожал бы каждый кадр:
      // разжались → не влезло → сжались → разжались.
      this.setState({ hdrTier: т - 1 });
    }
  },

  // ---- цепочка: стыки ----
  // togChip / togJunc / setChipRole вырезаны (Раунд 50): горизонтальные чипы
  // заменены списком ещё в Раунде 41 и с тех пор никем не звались, а роль
  // перестала быть настройкой генерации. Ключи chipOpen/juncOpen в состоянии
  // ОСТАЮТСЯ: их читает вычисление ключа закрытия попапов (Nakedlunch.jsx),
  // и без них closePop начал бы возвращаться раньше времени.
  setJunc(i, val) {
    var j = (this.state.junctions || []).slice(); j[i] = val;
    this.setState({ junctions: j, juncOpen: -1 });
    var st = this.state;
    if (st.chain[i + 1] && this.emitTrace) this.emitTrace('s:' + st.chain[i], 's:' + st.chain[i + 1], 0.85);
  },
  // Профиль строфы звена (Раунд 39 — теперь это САМА суть звена, а не
  // переопределение роли). Массив параллелен chain — дыры до i заполняем
  // null, чтобы JSON-снапшот профиля цепочки был стабильным.
  setChipForm(i, name) {
    var cf = (this.state.chainForms || []).slice();
    while (cf.length <= i) cf.push(null);
    cf[i] = name || null;
    this.setState({ chainForms: cf, chipOpen: -1 });
  },
  // Секция — необязательный заголовок в документе («## ПРИПЕВ»), не настройка
  // генерации. Пусто = звено без заголовка.
  setChipSection(i, name) {
    var ch = (this.state.chain || []).slice();
    while (ch.length <= i) ch.push('');
    ch[i] = name || '';
    this.setState({ chain: ch, chipOpen: -1 });
  },
  // Порядок звеньев: chain и chainForms параллельны и переставляются вместе,
  // иначе профили съедут на чужие звенья. Стыки НЕ трогаем — их смысл
  // «между i и i+1», и при перестановке они остаются на своих местах.
  // Раунд 51: вместе со звеном переставляются ВСЕ его параллельные массивы.
  // chainKnobs (профиль настроек звена) забыли при вводе — а читается он строго
  // по индексу, поэтому после перестановки или удаления настройки съезжали на
  // чужие звенья молча, без единого признака.
  moveChip(i, шаг) {
    var j = i + шаг, ch = (this.state.chain || []).slice();
    if (i < 0 || j < 0 || j >= ch.length) return;
    var cf = this._параллельно('chainForms', ch.length);
    var ck = this._параллельно('chainKnobs', ch.length);
    var rep = this._параллельно('chainRepeat', ch.length);
    var реф = (this.state.refChain || []).slice();
    var своп = function (a) { if (a.length > Math.max(i, j)) { var t = a[i]; a[i] = a[j]; a[j] = t; } };
    var t = ch[i]; ch[i] = ch[j]; ch[j] = t;
    своп(cf); своп(ck); своп(реф);
    // Ссылки повтора — ИНДЕКСЫ, их мало переставить: цель тоже переехала, а
    // ссылка могла развернуться вперёд (см. чинитьПовторы).
    var перевод = ch.map(function (_, k) { return k === i ? j : (k === j ? i : k); });
    var было = (rep || []).filter(function (v) { return v != null; }).length;
    rep = this.чинитьПовторы(rep, перевод, ch.length);
    if (было && rep.filter(function (v) { return v != null; }).length < было) {
      this.flash('повтор смотрел бы вперёд — снят с переехавшего звена');
    }
    this.setState({ chain: ch, chainForms: cf, chainKnobs: ck, chainRepeat: rep,
                    refChain: реф.length ? реф : this.state.refChain, chipOpen: j });
  },

  // общий помощник: массив той же длины, что цепочка, добитый null
  _параллельно(имя, длина) {
    var a = (this.state[имя] || []).slice();
    while (a.length < длина) a.push(null);
    return a;
  },
  removeChip(i) {
    var ch = (this.state.chain || []).slice();
    if (i < 0 || i >= ch.length || ch.length <= 1) return;   // пустая цепочка — не цепочка
    var cf = this._параллельно('chainForms', ch.length);
    var ck = this._параллельно('chainKnobs', ch.length);
    var rep = this._параллельно('chainRepeat', ch.length);
    var реф = (this.state.refChain || []).slice();
    // перевод строится ДО удаления: звенья правее сдвигаются, само удалённое
    // теряет номер, а звенья, которые его повторяли, становятся обычными
    var перевод = ch.map(function (_, k) { return k === i ? null : (k > i ? k - 1 : k); });
    ch.splice(i, 1); cf.splice(i, 1); ck.splice(i, 1);
    if (i < реф.length) реф.splice(i, 1);
    var было = rep.filter(function (v) { return v != null; }).length;
    rep = this.чинитьПовторы(rep, перевод, ch.length);
    if (было && rep.filter(function (v) { return v != null; }).length < было) {
      this.flash('звено, которое повторяли, убрано — повтор снят');
    }
    var j = (this.state.junctions || []).slice();
    if (i < j.length) j.splice(i, 1);        // стык уходит вместе со звеном
    this.setState({ chain: ch, chainForms: cf, chainKnobs: ck, chainRepeat: rep,
                    refChain: реф.length ? реф : null, junctions: j, chipOpen: -1 });
  },
  // Новое звено наследует форму и профиль у ПРЕДЫДУЩЕГО (Раунд 55).
  //
  // До этого оно брало их из панели — а панель была ещё и невидимым запасным
  // источником для звеньев без полок, и вместе это давало «звено выглядит
  // пустым, а набирается неизвестно чем». Наследование у соседа честнее и
  // ровно так же удобно: в песне подряд идут однотипные куплеты, а строка
  // серии наследует поля точно так же (methods.series.js: addSeriesLink).
  // Пустых звеньев после этого не бывает — если, конечно, предыдущее не пусто
  // само, а такое возможно только у самого первого.
  addChip() {
    var st = this.state;
    var n = (st.chain || []).length;
    var cf = this._параллельно('chainForms', n);
    var ck = this._параллельно('chainKnobs', n);
    var rep = this._параллельно('chainRepeat', n);
    // у звена-повтора своей формы нет — наследуем от того, кого оно повторяет
    var донор = n ? (rep[n - 1] != null ? rep[n - 1] : n - 1) : -1;
    var ch = (st.chain || []).concat('');
    cf = cf.concat(донор >= 0 ? (cf[донор] || st.stanzaProfile || null) : (st.stanzaProfile || null));
    ck = ck.concat(донор >= 0 ? (ck[донор] || st.knobProfile || null) : (st.knobProfile || null));
    // новое звено встаёт В КОНЕЦ, поэтому чужие индексы не едут
    rep = rep.concat(null);
    this.setState({ chain: ch, chainForms: cf, chainKnobs: ck, chainRepeat: rep, chipOpen: -1 });
  },

  // ---- профили цепочек ----
  // chainForms и pipeRuns — фаза 1: формы звеньев и число сочетаний прогона —
  // тоже часть профиля, без них «сохранить» не замечал бы их смену
  // Снимок цепочки для «изменено?». Раунд 50: только то, что в цепочке есть —
  // threshold/limit/pipeRuns вырезаны из состояния ещё в Раундах 47-49, но
  // продолжали сюда попадать как undefined и ездить на диск в сохранённых
  // профилях.
  snap() {
    var st = this.state;
    return JSON.stringify([st.chain, st.junctions, st.chainForms || [],
                           st.refText || '', st.refPct != null ? st.refPct : 1]);
  },
  // Раунд 50: chainProfiles() и saveProfile() вырезаны. Полка цепочек уехала
  // на бэк отдельным файлом со своим валидатором (core/chain_profiles.py), а
  // сохранение стало СЛЕПКОМ — см. methods.shelves.js: saveChain/pickChain.
  //
  // Раунд 55: следом ушёл pickProfile — разбор ПРЕСЕТА из константы фронта.
  // Встроенные цепочки приходят с бэка обычными записями полки, и разбирает
  // их тот же pickChain, что и свои.

  // ---- Раунд 50: здесь были мёртвые обработчики -------------------------
  // onLimit / onPipeRuns / onThr / onPoolPer / setPipeWeight / setPipeRepeats —
  // ручки для полей, которых в панели не было ещё с Раундов 46-49 (порог
  // отсева, число прогонов, размер пула, три веса склейки). Их не вызывал
  // никто, а сохранённые профили цепочек продолжали таскать их значения на
  // диск. Вместе с ними ушли togChip / togJunc / setChipRole (горизонтальные
  // чипы цепочки заменены списком ещё в Раунде 41) и paramKnobs — второй,
  // расходящийся перевод крутилок в координаты ядра: он не отдавал ни classic,
  // ни mat_share, ни cohesion, и переключить на него вызовы значило бы молча
  // потерять три ручки. Перевод теперь ОДИН — methods.shelves.js:
  // knobsOfProfile, зеркало core/clean.py: knobs_from_profile.

  // диссонанс — обычная крутилка профиля настроек; отдельный обработчик
  // остался, потому что фристайл-панель зовёт его напрямую
  onDis(e) { this.setKnob('Диссонанс', parseFloat(e.target.value) || 0); },

  setParam(n, v) { this.setKnob(n, v); },

  // ---- вычислители общих настроек (renderVals 3406..3445, 3510..3517) ----
  cfgNumItem(key, label, min, max, step, dflt, unit) {
    var self = this, C = this.cfg();
    var v = C[key] != null ? parseFloat(C[key]) : dflt; if (isNaN(v)) v = dflt;
    return { label: label, isRange: true, isPick: false, min: min, max: max, step: step, val: String(v), show: (step < 1 ? v.toFixed(2) : String(Math.round(v))) + (unit || ''), onIn: function (e) { self.setCfg(key, parseFloat(e.target.value)); } };
  },
  cfgPickItem(key, label, opts, dflt) {
    var self = this, C = this.cfg();
    var cur = C[key] != null ? C[key] : dflt;
    var wide = opts.length > 3;
    return { label: label, isRange: false, isPick: true, show: '', min: 0, max: 1, step: 1, val: '0', onIn: function () {},
      optsStyle: 'display: flex; gap: 3px; justify-content: flex-end; align-items: center;' + (wide ? ' grid-column: 1 / -1; margin-top: 1px;' : ''),
      opts: opts.map(function (o) { var lbl = o === true ? 'да' : (o === false ? 'нет' : String(o)); return { name: lbl, style: pickStyle(String(cur) === String(o)), onPick: function () { self.setCfg(key, o); } }; }) };
  },
  cfgRowsCalc(items) {
    items.forEach(function (it, i) {
      it.hasHint = !!it.hint;
      it.rowStyle = CFGROW + (i ? ' border-top: 1px solid var(--border-subtle);' : '');
    });
    return items;
  },
  // секции текст/пост/вид/градиент у краёв — дословно из renderVals 3418..3445
  cfgSectionsCalc() {
    var cfgNum = this.cfgNumItem.bind(this), cfgPick = this.cfgPickItem.bind(this), cfgRows = this.cfgRowsCalc.bind(this);
    return [
      { name: 'текст', items: [
        cfgPick('uiFont', 'интерфейс', FONTS_BASE, 'JetBrains Mono'),
        cfgPick('docFont', 'документ', ['как интерфейс'].concat(FONTS_BASE), 'как интерфейс')
      ] },
      { name: 'пост', items: [
        cfgNum('uiGlow', 'свечение', 0, 100, 1, 0),
        cfgNum('uiExpo', 'экспозиция', 40, 220, 5, 100, '%'),
        cfgNum('uiGrain', 'зерно', 0, 100, 1, 0, '%'),
        cfgNum('uiContrast', 'контраст', 60, 180, 1, 100, '%'),
        cfgPick('uiGrainFps', 'кадры зерна', ['15', '24', '30', '60', 'без предела'], '24')
      ] },
      { name: 'вид', items: [
        cfgPick('menuFill', 'заливка меню', ['стекло', 'плотная'], 'стекло'),
        cfgNum('menuAlpha', 'плотность панелей', 40, 100, 1, 82, '%'),
        cfgNum('glassBlur', 'размытие стекла', 0, 32, 1, 7, 'px'),
        hint(cfgNum('glassWarp', 'искажение стекла', 0, 60, 1, 11), 'фон за панелью слегка ведёт, как за настоящим стеклом'),
        cfgPick('glassAber', 'хроматика стекла', ['нет', 'да'], 'нет')
      ] },
      { name: 'градиент у краёв', items: [
        cfgPick('fadeOn', 'включён', ['да', 'нет'], 'да'),
        cfgNum('fadeLen', 'длина', 100, 900, 20, 160, 'px'),
        hint(cfgNum('fadeStr', 'сила', 40, 140, 5, 100, '%'), 'больше 100% — текст уходит раньше и глуше'),
        hint(cfgNum('fadeCurve', 'кривая', 0.3, 2, 0.05, 0.5), 'меньше 1 — гаснет резко у края и долго тянется хвостом; больше 1 — наоборот'),
        cfgNum('fadeBlur', 'размытие', 0, 30, 1, 14, 'px'),
        hint(cfgNum('fadeDither', 'дизер', 0, 10, 0.5, 0, '%'), 'тонкий шум против ступеней на тёмном градиенте')
      ] }
    ].map(function (sec) { return { name: sec.name, items: cfgRows(sec.items) }; });
  },
};


// ---------------------------------------------------------------------------
// Профиль генерации: строфа + крутилки в одном месте (2026-08-02, пользователь:
// «строфа должна как профиль работать — это настройки крутилок плюс сама
// рифмовка; можно и крутилки и рифмовку и строфы как профили в один попап
// собрать»).
//
// ЧТО БЫЛО СЛОМАНО: попап «строфа» только ПОКАЗЫВАЛ имя профиля, выбрать
// другой было нечем вовсе. Схема приезжала из settings.stanza, куда её
// однажды записал старый интерфейс extendo, — и там лежала Онегинская
// строфа на 14 строк. Каждое ⌘↵ поэтому набирало 14 строк по схеме
// абабввггдееджж: 21 секунда на тёплом сервере, 43 на холодном (замерено).
// Со стороны это выглядело как «генерация не срабатывает на клавиши».
//
// Крутилки при этом жили только в памяти вкладки: не сохранялись и не
// восстанавливались. Теперь и схема, и крутилки лежат в settings и
// поднимаются при старте, а именованный профиль хранит их вместе.
// ---------------------------------------------------------------------------

// буквы рифмовки: девяти хватает на любую из 24 встроенных форм (максимум —
// Спенсерова строфа, пять разных букв), а короткий ряд позволяет перебирать
// букву кликом, не заводя ещё один вложенный попап
export const RHYME_LETTERS = ['а', 'б', 'в', 'г', 'д', 'е', 'ж', 'з', 'и'];

// катрен абаб, восьми-девятисложник — то, с чего начинают, если не сохранено
// ничего. Не Онегинская строфа: 14 строк это 20+ секунд ожидания на прогон.
export const DEFAULT_SPEC = [
  { letter: 'а', min_syl: 8, max_syl: 9 }, { letter: 'б', min_syl: 8, max_syl: 9 },
  { letter: 'а', min_syl: 8, max_syl: 9 }, { letter: 'б', min_syl: 8, max_syl: 9 },
];

export const genProfileMethods = {
  RHYME_LETTERS: RHYME_LETTERS,

  // открытие пилюли профиля всегда со свёрнутым списком форм: иначе попап
  // открывается на том, чем его закрыли в прошлый раз, и конструктора не видно
  togProfile() {
    var open = this.state.openPill === 'stanza';
    this.setState({ stanzaPick: false });
    this.tog('stanza');
    return open;
  },

  // действующая схема: своя правка → сохранённая на бэке → катрен
  curSpec() {
    var s = this.state.stanzaSpec;
    return Array.isArray(s) && s.length ? s : DEFAULT_SPEC;
  },

  // все формы одним списком: встроенные (24, сгруппированы) + свои
  allForms() {
    var f = this.state.stanzaForms || {};
    return (f.builtin || []).concat(f.custom || []);
  },

  // Пишем в settings с дебаунсом: ползунок даёт событие на каждый шаг, а это
  // запись файла на диске. 600 мс — как у saveViewSoon фристайла.
  saveGenProfileSoon() {
    var self = this;
    clearTimeout(this._genProfT);
    this._genProfT = setTimeout(function () {
      var st = self.state;
      api.settingsSet({
        stanza: self.curSpec(),
        stanza_profile: st.stanzaProfile || '',
        // последние положения панели: окно должно открываться там, где его
        // закрыли. Именованные наборы — на полке /api/knobs/profiles.
        nl_params: { params: st.params || {}, mode: st.knobMode || 'алгоритм' },
      }).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
    }, 600);
  },

  /** Живая цепочка на диск — «где закрыл, там открыл» (Раунд 55).
   *
   *  Зовётся из componentDidUpdate, поэтому первым делом проверяет, менялось
   *  ли ЧТО-ТО из шести ключей цепочки: без этой проверки запись уходила бы
   *  на каждую перерисовку документа.
   *
   *  Полка цепочек при этом остаётся полкой: там СЛЕПКИ, которые пользователь
   *  сохранил осознанно и которые не меняются от правки полок. Здесь — просто
   *  то, что стоит в меню прямо сейчас, как и положения ползунков рядом. */
  saveChainSoon() {
    var st = this.state;
    var снимок = JSON.stringify([st.chain, st.chainForms, st.chainKnobs,
                                 st.chainRepeat, st.junctions, st.profile]);
    if (снимок === this._chainSaved) return;
    this._chainSaved = снимок;
    if (this._chainFirst === undefined) { this._chainFirst = 1; return; }  // первый кадр — это boot
    var self = this;
    clearTimeout(this._chainT);
    this._chainT = setTimeout(function () {
      api.settingsSet({ nl_chain: {
        chain: self.state.chain || [], forms: self.state.chainForms || [],
        knobs: self.state.chainKnobs || [], repeat: self.state.chainRepeat || [],
        junctions: self.state.junctions || [], profile: self.state.profile || '',
      } }).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
    }, 600);
  },

  // правка схемы руками = профиль больше не «тот самый»: имя гасим, чтобы
  // подпись не врала, будто на экране Онегинская строфа
  setSpec(lines, keepName) {
    var patch = { stanzaSpec: lines };
    if (!keepName) patch.stanzaProfile = '';
    this.setState(patch, this.saveGenProfileSoon.bind(this));
  },

  pickStanzaForm(name) {
    var forms = this.allForms(), f = null;
    for (var i = 0; i < forms.length; i++) if (forms[i].name === name) { f = forms[i]; break; }
    if (!f || !f.lines || !f.lines.length) return;
    // Раунд 50: форма НЕ трогает крутилки. Раньше выбор строфы молча двигал
    // ползунки — то смешение каркаса с настройками, которое пользователь разделил
    // на две полки.
    //
    // Раунд 55: и НЕ трогает звено цепочки. В Раунде 51 выбор формы назначался
    // «выбранному звену», потому что редактор жил под цепочкой и иначе правил
    // не то, на что показывал. Теперь редакторы живут в своём меню «Строфа», у
    // звеньев свои выпадашки в меню «Пайплайн», и записи в чужой этаж не
    // остаётся вовсе — вместе с ней умерло само понятие «выбранное звено».
    this.setState({ stanzaSpec: f.lines.map(function (l) { return Object.assign({}, l); }),
                    stanzaProfile: name, stanzaPick: false },
                  this.saveGenProfileSoon.bind(this));
  },

  cycleLetter(i, back) {
    var lines = this.curSpec().map(function (l) { return Object.assign({}, l); });
    var cur = RHYME_LETTERS.indexOf(lines[i].letter);
    if (cur < 0) cur = 0;
    var next = (cur + (back ? -1 : 1) + RHYME_LETTERS.length) % RHYME_LETTERS.length;
    lines[i].letter = RHYME_LETTERS[next];
    this.setSpec(lines);
  },

  setLineSyl(i, which, raw) {
    var v = parseInt(raw, 10);
    if (isNaN(v)) return;
    v = Math.max(1, Math.min(30, v));
    var lines = this.curSpec().map(function (l) { return Object.assign({}, l); });
    lines[i][which] = v;
    // вилка не должна выворачиваться: правим соседа, а не молча отбрасываем ввод
    if (lines[i].min_syl > lines[i].max_syl) {
      if (which === 'min_syl') lines[i].max_syl = v; else lines[i].min_syl = v;
    }
    this.setSpec(lines);
  },

  addStanzaLine() {
    var lines = this.curSpec().map(function (l) { return Object.assign({}, l); });
    if (lines.length >= 20) { this.flash('20 строк — потолок строфы'); return; }
    var last = lines[lines.length - 1] || DEFAULT_SPEC[0];
    lines.push({ letter: last.letter, min_syl: last.min_syl, max_syl: last.max_syl });
    this.setSpec(lines);
  },

  dropStanzaLine(i) {
    var lines = this.curSpec().map(function (l) { return Object.assign({}, l); });
    if (lines.length <= 1) { this.flash('в строфе должна остаться хотя бы строка'); return; }
    lines.splice(i, 1);
    this.setSpec(lines);
  },

  // сохранение своего профиля: имя из поля, а если пусто — по встроенной
  // форме нельзя писать поверх, поэтому предлагаем своё
  saveStanzaProfile() {
    var self = this, st = this.state;
    var name = (st.profNameDraft || '').trim() || st.stanzaProfile || '';
    var builtinNames = ((st.stanzaForms || {}).builtin || []).map(function (f) { return f.name; });
    if (!name || builtinNames.indexOf(name) >= 0) {
      var n = 1, taken = this.allForms().map(function (f) { return f.name; });
      while (taken.indexOf('Моя строфа ' + n) >= 0) n++;
      name = 'Моя строфа ' + n;
    }
    api.stanzaProfileSave(name, this.curSpec()).then(function (res) {
      var forms = Object.assign({}, self.state.stanzaForms, { custom: (res && res.custom) || [] });
      self.setState({ stanzaForms: forms, stanzaProfile: name, profNameDraft: '', profSaveFlash: true },
        self.saveGenProfileSoon.bind(self));
      clearTimeout(self._profFlashT);
      self._profFlashT = setTimeout(function () { self.setState({ profSaveFlash: false }); }, 1700);
    }).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
  },

  deleteStanzaProfile(name) {
    var self = this;
    api.stanzaProfileDelete(name).then(function (res) {
      var forms = Object.assign({}, self.state.stanzaForms, { custom: (res && res.custom) || [] });
      var patch = { stanzaForms: forms };
      if (self.state.stanzaProfile === name) patch.stanzaProfile = '';
      self.setState(patch, self.saveGenProfileSoon.bind(self));
    }).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
  },
};
