// Методы панелей из дизайна «Editor First» (project-notes/mockups/design-v2/
// Editor First.dc.html: JS-класс 3258..3294, renderVals 3406..3517 и inline-
// обработчики 4049..4097) — миксин: интегратор делает
// Object.assign(Nakedlunch.prototype, panelMethods).
// Раунд 50: крутилки и полки уехали в methods.shelves.js, панель — в
// render.gen.jsx. 2026-08-18: стыки цепочки и порядок звеньев ушли вместе с
// пайплайном. Здесь остались общие вещи попапов и настроек: ярусы сжатия
// шапки, вычислители общих настроек и профиль генерации (строфа + крутилки).

import * as api from './api.js';

// Раунд 50 — зеркало core/clean.py: KNOB_SPEC. Значения ПО УМОЛЧАНИЮ те же,
// что у профиля «Обычный» на полке, а он собран из измеренных положений
// пользователя (data/settings.json, nl_params на 2026-08-03).
//
// Чего здесь больше нет:
//   «Отбор» — стал бинарным переключателем режима (алгоритм/классика), а не
//     ползунком: требование (2026-08-03): бинарный переключатель.
//   «Разнообразие» — мертво с Раунда 48: вариант всегда один, MMR-отбору
//     между вариантами нечего разнообразить.
// Что появилось: «Клаузула» и «Связность» — они работали с Раунда 44, но
// дотянуться до них можно было ТОЛЬКО через референс. «Связность» удалена
// 2026-08-21 (надгробие в core/filters.py).
// «Банальность»: 0.83 — УДАЛЕНА 2026-08-20 (надгробие в core/nlindex.py).
// «Мелодичность»: 0.35 и «Связность»: −1.0 — УДАЛЕНЫ 2026-08-21 (надгробия
// в core/filters.py).
export const PARAM_DEFAULTS = {
  'Источники': 1.0, 'Мат': -1.0, 'Клаузула': 0,
  'Точность рифм': 0.25,
  // 0 «не повторять» (прежнее поведение), 1 «можно» — Раунд 52, хук
  'Диссонанс': 0.7, 'Повтор': 0,
};

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
  // Отчёт: в маленьком окне шапка и панели не подстраивались под размер.. Так и было: у обеих половин шапки стоял
  // `min-width: fit-content`, у самой шапки — `overflow: visible`, и при узком
  // окне правый край просто уезжал за экран. Замерено на окне 760: ширина
  // шапки 760, содержимого 1098, 50 элементов правее правого края, полосы
  // прокрутки нет — то есть тема, настройки и часы становились недоступны.
  //
  // Правило решение: не убирать полностью, а сжимать до мелких значков. Поэтому ЯРУСЫ: ничего не исчезает,
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

  // ---------------------------------------------------------------------------
  // ЗДЕСЬ БЫЛА ЦЕПОЧКА: СТЫКИ, ЗВЕНЬЯ И ЕЁ СНИМОК (вырезано 2026-08-18, 128 строк).
  //
  //   setJunc — стык между соседними звеньями (рифмовать / свободно / слом ритма).
  //   setChipForm / setChipSection — форма звена и заголовок секции.
  //   moveChip / removeChip / addChip — порядок звеньев, удаление, добавление с
  //     наследованием формы и профиля у соседа.
  //   _параллельно — общий помощник: массив длиной с цепочку, добитый null.
  //   snap — снимок цепочки для вопроса «изменено?».
  //
  // ПОЧЕМУ. Решение владельца дословно: «pipeline и серия это бесполезные режимы
  // на самом деле… с практической точки зрения бесполезны, их можно вырезать.
  // Строфа единственным режимом и всё». Замер журнала за десять живых дней: 29
  // прогонов цепи против 587 одиночных строф, медиана цепи 24.2 с.
  //
  // Вместе с ними ушёл целый класс ошибок, который эти методы и сторожили:
  // параллельные массивы chain/chainForms/chainKnobs/chainRepeat, съезжающие по
  // индексам при любой перестановке. Параллельных массивов больше нет.
  // ---------------------------------------------------------------------------

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

  // onDis вырезан (Раунд 63). Комментарий над ним обещал, что «фристайл-панель
  // зовёт его напрямую» — по всему дереву фронта не звал никто.
  //
  // НАДГРОБИЕ У ХВОСТА ТОЙ ЖЕ ФРАЗЫ (2026-08-27). Здесь стояло «панель
  // фристайла ходит через setParam/setKnob, как и все остальные» — и это
  // было контрол-обманкой: с Раунда 57 сцена генерирует из СВОЕЙ копии
  // (fsParams), а setParam правит st.params редактора — ползунок панели
  // фристайла для сцены был мёртв. Теперь фристайл ходит через свой
  // fsSetParam (methods.fs.js); setParam остаётся редактору.

  setParam(n, v) { this.setKnob(n, v); },

  // Число с разрядами — переехало сюда из methods.doc.js (2026-08-18) вместе со
  // сносом редактора: читателем всегда была шапка (корпус, статистика), а не
  // документ, и жить ему тут.
  fmt(n) { return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' '); },

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
        // Ключ `docFont` НЕ переименован при сносе документа: он лежит в
        // сохранённом виде (nl_view) и в профилях вида на диске. Меняем только
        // подпись — тот же приём, что у «Точности рифм» (methods.shelves.js).
        cfgPick('docFont', 'лента', ['как интерфейс'].concat(FONTS_BASE), 'как интерфейс')
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
// Профиль генерации: строфа + крутилки в одном месте (2026-08-02, требование: строфа работает как профиль — крутилки плюс рифмовка; крутилки, рифмовку и
// строфы можно собрать в один попап).
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

  // Раунд 63: отсюда ушёл `stanzaPick: false` («открывать со свёрнутым списком
  // форм»). Сворачивать давно нечего — список форм в попапе рисуется всегда, и
  // флаг был обещанием поведения, которого нет.
  togProfile() {
    var open = this.state.openPill === 'stanza';
    this.tog('stanza');
    // Форма пула на ОТКРЫТИЕ, а не только на движение ручки: иначе панель
    // впервые показывалась бы без неё, и «из чего выбирается» появлялось бы
    // лишь после того, как что-нибудь тронешь.
    if (!open && this.спроситьФормуПула) this.спроситьФормуПула();
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
        nl_params: { params: st.params || {}, mode: st.knobMode || 'алгоритм',
                     полосы: st.полосы || { слова: '', пара: '' } },
      }).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
    }, 600);
  },

  // saveChainSoon вырезан 2026-08-18 вместе с цепочкой. Он писал живую цепочку
  // в settings.nl_chain на каждом componentDidUpdate («где закрыл, там открыл»,
  // Раунд 55) — и был единственным вызовом из componentDidUpdate в этот файл.
  // Каркас строфы и положения крутилок переживают перезапуск сами:
  // saveGenProfileSoon выше пишет stanza / stanza_profile / nl_params.

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
    // ползунки — то смешение каркаса с настройками, которое «выбранному звену», потому что редактор жил под цепочкой и иначе правил
    // не то, на что показывал. Теперь редакторы живут в своём меню «Строфа», у
    // звеньев свои выпадашки в меню «Пайплайн», и записи в чужой этаж не
    // остаётся вовсе — вместе с ней умерло само понятие «выбранное звено».
    this.setState({ stanzaSpec: f.lines.map(function (l) { return Object.assign({}, l); }),
                    stanzaProfile: name },
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
