// nakedlunch — ЧЕТВЁРТАЯ полка: СЕРИИ (Раунд 53).
//
// Требование (2026-08-04): серия — уровень выше пайплайна и живёт в той же менюшке..
//
// ТРЕК серии = {название, тема, цепочка с полки, сколько претендентов} — ровно
// как звено цепочки = {форма с полки, профиль настроек}. Тот же приём уровнем
// выше, поэтому и правится он теми же средствами: список строк, у каждой свои
// поля, ＋ и ✕.
//
// Слово «трек» — ОДНО на все места (Раунд 55). До него одна и та же строка
// звалась в одной панели треком (на кнопке), звеном (в подсказке удаления) и
// звеном серии (в ошибке запуска).
//
// ПРОГОН ЗДЕСЬ ТОЛЬКО ЗАПУСКАЕТСЯ. Он идёт фоновым потоком сервера и живёт
// внутри окна (решение «можно закрыть окно»). Ход виден в шапке —
// тем же индикатором работ, что и сборка рифм.

import * as api from './api.js';

function msg(e) { return e && e.message ? e.message : String(e); }

export const ПУСТОЙ_ТРЕК = { album: '', theme: '', chain: '', count: 10 };

// Каналы искажения — зеркало core/distort.py: КАНАЛЫ и МАСТЕР. Держать в
// синхроне: два списка для одного понятия — второй источник правды, и на
// расхождении белых списков проект уже обжигался.
export const МАСТЕР = 'все';
export const КАНАЛЫ = ['Точность рифм', 'Мелодичность', 'Банальность', 'Диссонанс', 'Связность'];

// Заготовки: положил фигуру и правь точками. Не источник, а стартовая поза —
// поэтому их всего четыре и они тут, а не на полке.
// Типы шума — зеркало core/distort.py: ШУМЫ. Различает их одно: насколько
// похожи соседние точки. Подписи говорят именно это, а не спектр.
// Их ЧЕТЫРЕ, а не пять: пятым просился броуновский, но на нашем масштабе он
// замерился неотличимым от розового — см. core/distort.py.
export const ШУМЫ = [
  ['белый', 'соседи независимы'],
  ['синий', 'соседи нарочно разные'],
  ['розовый', 'похожи, но дрейфуют'],
  ['перлин', 'плавные волны'],
];

export const ФИГУРЫ = {
  'нарастание': [[0, -0.6], [1, 0.6]],
  'спад': [[0, 0.6], [1, -0.6]],
  'волна': [[0, 0], [0.25, 0.6], [0.5, 0], [0.75, -0.6], [1, 0]],
  'провал': [[0, 0.5], [0.5, -0.6], [1, 0.5]],
};

/** Человеческое время из секунд: «17 мин», «1 ч 25 мин», «8 ч». */
export function времени(сек) {
  var s = Math.max(0, Math.round(сек || 0));
  if (s < 60) return s + ' с';
  var м = Math.round(s / 60);
  if (м < 60) return м + ' мин';
  var ч = Math.floor(м / 60), ост = м % 60;
  return ч + ' ч' + (ост ? ' ' + ост + ' мин' : '');
}

export const seriesMethods = {
  async reloadSeries(extra) {
    try {
      var res = await api.series();
      this.setState(Object.assign({
        seriesList: (res && res.custom) || [],
        // секунды на текст приходят ЧИСЛОМ с бэка — своей копии тут нет
        // намеренно: две константы для одного замера однажды разойдутся
        seriesSec: (res && res.seconds_per_text) || 15,
      }, extra || {}));
    } catch (e) { this.flash(msg(e)); }
  },

  seriesByName(name) {
    return (this.state.seriesList || []).filter(function (s) { return s.name === name; })[0] || null;
  },

  /** Выбрать серию: её треки становятся тем, что правится. */
  pickSeries(name) {
    var s = this.seriesByName(name);
    if (!s) {
      this.setState({ seriesName: '', seriesLinks: [], seriesState: null,
                      seriesCurve: {}, seriesNoise: 0 });
      return;
    }
    this.setState({
      seriesName: name, seriesDraft: '', seriesState: null,
      seriesLinks: (s.links || []).map(function (l) { return Object.assign({}, l); }),
      seriesCurve: s.curve || {}, seriesNoise: s.noise || 0,
      noiseKind: s.noise_kind || 'белый',
    }, this.reloadSeriesState.bind(this));
  },

  /** Настоящее положение дел: сколько сделано по каждому треку, какой идёт,
   *  где что встало. С бэка, из ФАЙЛОВ (см. core/series_run.состояние) —
   *  меню не помнит прогонов и потому не может о них соврать.
   *
   *  Зовётся при выборе серии, при открытии меню и на каждом тике опроса
   *  работ, пока серия идёт: без этого пользователь видел бы вчерашние цифры
   *  ровно там, где смотрит на сегодняшний ход. */
  async reloadSeriesState() {
    var имя = this.state.seriesName;
    if (!имя) { this.setState({ seriesState: null }); return; }
    try {
      var res = await api.seriesState(имя);
      if (this.state.seriesName !== имя) return;
      // ЗАМЕРЕННОЕ время на текст главнее константы (Раунд 55): на тяжёлой
      // цепочке пользователя константа врала втрое — «22 минуты» там, где час.
      var patch = { seriesState: res };
      if (res && res.seconds_per_text) patch.seriesSec = res.seconds_per_text;
      this.setState(patch);
    } catch (e) { /* серия ещё не сохранена — показывать нечего, и это не беда */ }
  },

  setSeriesLink(i, поле, v) {
    var l = (this.state.seriesLinks || []).map(function (x) { return Object.assign({}, x); });
    while (l.length <= i) l.push(Object.assign({}, ПУСТОЙ_ТРЕК));
    l[i][поле] = поле === 'count' ? Math.max(1, parseInt(v, 10) || 1) : v;
    this.setState({ seriesLinks: l });
  },

  addSeriesLink() {
    var l = (this.state.seriesLinks || []).slice();
    // новый трек наследует название и цепочку предыдущего: в альбоме десять
    // треков подряд, и заполнять одно и то же десять раз — не работа
    var прош = l[l.length - 1] || ПУСТОЙ_ТРЕК;
    l.push(Object.assign({}, ПУСТОЙ_ТРЕК, { album: прош.album, chain: прош.chain,
                                             count: прош.count }));
    this.setState({ seriesLinks: l });
  },

  removeSeriesLink(i) {
    var l = (this.state.seriesLinks || []).slice();
    l.splice(i, 1);
    this.setState({ seriesLinks: l });
  },

  /** Сколько сделано, сколько осталось и сколько это времени.
   *
   *  План считается по ТЕКУЩЕЙ правке, а не по сохранённому: цену пользователь
   *  должен видеть до запуска и до сохранения. А вот СДЕЛАННОЕ приходит с
   *  бэка из файлов — и именно поэтому «осталось» честно уменьшается на
   *  каждом следующем запуске. Раньше показывался полный план всегда: «30
   *  текстов ≈ 8 мин» при двадцати восьми готовых.
   *
   *  Если состояния ещё нет (серию не сохраняли), сделанного считаем ноль —
   *  тогда «осталось» совпадает с планом, и это правда. */
  seriesEstimate() {
    var сост = this.state.seriesState || {};
    var сделано = (сост.done || []);
    var n = 0, готово = 0;
    (this.state.seriesLinks || []).forEach(function (l, i) {
      var надо = parseInt(l.count, 10) || 0;
      n += надо;
      готово += Math.min(надо, сделано[i] || 0);
    });
    var осталось = Math.max(0, n - готово);
    return { texts: n, done: готово, left: осталось,
             seconds: осталось * (this.state.seriesSec || 15) };
  },

  // ---- искажение: кривая с точками и шум ---------------------------------
  /** Точки выбранного канала. Пусто = прямая по нейтрали, то есть «не гну». */
  curvePoints(канал) {
    var c = (this.state.seriesCurve || {})[канал || this.state.curveChan || МАСТЕР];
    return Array.isArray(c) ? c : [];
  },

  setCurvePoints(точки) {
    var канал = this.state.curveChan || МАСТЕР;
    var крив = Object.assign({}, this.state.seriesCurve || {});
    var чистые = (точки || []).slice().sort(function (a, b) { return a[0] - b[0]; });
    if (чистые.length) крив[канал] = чистые; else delete крив[канал];
    this.setState({ seriesCurve: крив });
  },

  /** Кривая в точке x — ТА ЖЕ математика, что в core/distort.py: монотонный
   *  кубический сплайн Фрича–Карлсона. Гладко и без выбросов: между двумя
   *  точками значение никогда не выходит за них, поэтому нарисованное и
   *  сделанное совпадают. Держать в синхроне с бэком — расхождение здесь и
   *  есть «кривая обещает одно, прогон делает другое».
   */
  curveAt(точки, x) {
    var т = точки || [];
    if (!т.length) return 0;
    if (т.length === 1 || x <= т[0][0]) return т[0][1];
    if (x >= т[т.length - 1][0]) return т[т.length - 1][1];
    var n = т.length, Δ = [], i;
    for (i = 0; i < n - 1; i++) {
      var dx = т[i + 1][0] - т[i][0];
      Δ.push(dx > 0 ? (т[i + 1][1] - т[i][1]) / dx : 0);
    }
    var m = [Δ[0]];
    for (i = 1; i < n - 1; i++) m.push((Δ[i - 1] + Δ[i]) / 2);
    m.push(Δ[n - 2]);
    for (i = 0; i < n - 1; i++) {
      if (Δ[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
      var a = m[i] / Δ[i], b = m[i + 1] / Δ[i], q = a * a + b * b;
      if (q > 9) { var t3 = 3 / Math.sqrt(q); m[i] = t3 * a * Δ[i]; m[i + 1] = t3 * b * Δ[i]; }
    }
    for (i = 1; i < n; i++) {
      if (x > т[i][0]) continue;
      var x1 = т[i - 1][0], y1 = т[i - 1][1], x2 = т[i][0], y2 = т[i][1];
      var h = x2 - x1; if (h <= 0) return y2;
      var t = (x - x1) / h, tt = t * t, ttt = tt * t;
      return (2 * ttt - 3 * tt + 1) * y1 + (ttt - 2 * tt + t) * h * m[i - 1]
           + (-2 * ttt + 3 * tt) * y2 + (ttt - tt) * h * m[i];
    }
    return т[т.length - 1][1];
  },

  /** Пример шума выбранного типа — ПОКАЗАТЬ ХАРАКТЕР, а не предсказать прогон.
   *
   *  У настоящего шума зерно своё на каждый текст, и рисовать «как будет»
   *  было бы враньём. Зерно предпросмотра постоянное: меняешь тип — видишь,
   *  чем один отличается от другого, и это единственное, что тут можно
   *  честно показать. Математика та же, что в distort._ряд. */
  noisePreview(тип, n) {
    n = Math.max(2, n || 24);
    var зерно = 20260805;
    var rnd = function () { зерно = (зерно * 1103515245 + 12345) % 2147483648; return зерно / 2147483648; };
    var сырьё = [], i;
    for (i = 0; i < n; i++) сырьё.push(rnd() * 2 - 1);
    var out = [], шаг, вес, опоры, k, a, b, t;
    if (тип === 'розовый') {
      for (i = 0; i < n; i++) out.push(0);
      // от КРУПНОЙ октавы вниз — см. core/distort._ряд: обратный порядок даёт
      // почти белый шум вместо розового
      шаг = Math.max(2, Math.floor(n / 2)); вес = 1;
      while (шаг >= 1) {
        опоры = [];
        for (i = 0; i < Math.floor(n / шаг) + 2; i++) опоры.push(rnd() * 2 - 1);
        for (i = 0; i < n; i++) {
          k = i / шаг; a = опоры[Math.floor(k)]; b = опоры[Math.floor(k) + 1]; t = k - Math.floor(k);
          out[i] += вес * (a + (b - a) * t);
        }
        шаг = Math.floor(шаг / 2); вес *= 0.5;
      }
    } else if (тип === 'синий') {
      for (i = 0; i < n; i++) out.push(i ? сырьё[i] - сырьё[i - 1] : сырьё[0]);
    } else if (тип === 'перлин') {
      шаг = Math.max(2, Math.floor(n / 3));
      опоры = [];
      for (i = 0; i < Math.floor(n / шаг) + 2; i++) опоры.push(rnd() * 2 - 1);
      for (i = 0; i < n; i++) {
        k = i / шаг; a = опоры[Math.floor(k)]; b = опоры[Math.floor(k) + 1];
        t = k - Math.floor(k); t = t * t * (3 - 2 * t);
        out.push(a + (b - a) * t);
      }
    } else out = сырьё;
    var пик = Math.max.apply(null, out.map(Math.abs)) || 1;
    return out.map(function (v) { return v / пик; });
  },

  /** Положить готовую фигуру в текущий канал — стартовая поза, дальше руками. */
  putShape(имя) {
    var ф = ФИГУРЫ[имя];
    if (ф) this.setCurvePoints(ф.map(function (п) { return [п[0], п[1]]; }));
  },

  async saveSeries(имя) {
    var st = this.state;
    var name = (имя || st.seriesDraft || st.seriesName || '').trim();
    if (!name) {
      var n = 1, занято = (st.seriesList || []).map(function (s) { return s.name; });
      while (занято.indexOf('Моя серия ' + n) >= 0) n++;
      name = 'Моя серия ' + n;
    }
    try {
      await api.seriesSave({ name: name, links: st.seriesLinks || [],
                             curve: st.seriesCurve || {}, noise: st.seriesNoise || 0,
                             noise_kind: st.noiseKind || 'белый' });
      await this.reloadSeries({ seriesName: name, seriesDraft: '' });
      this.flash('серия сохранена: ' + name);
      // ВОЗВРАЩАЕМ имя, а не полагаемся на состояние: setState применяется не
      // мгновенно, и запуск сразу после сохранения читал бы ПРЕЖНЕЕ значение —
      // на первом сохранении пустое. Живая проверка так и легла: серия
      // сохранилась, а прогон получил пустое имя и честный 404.
      return name;
    } catch (e) { this.flash(msg(e)); return ''; }
  },

  async deleteSeries(name) {
    try {
      await api.seriesDelete(name);
      await this.reloadSeries(this.state.seriesName === name
        ? { seriesName: '', seriesLinks: [] } : {});
    } catch (e) { this.flash(msg(e)); }
  },

  /** Запустить. Сохранённую — по имени; правка обязана быть сохранена, иначе
   *  бэк погнал бы вчерашний вариант, а пользователь смотрел бы на сегодняшний. */
  async runSeries() {
    var st = this.state;
    if (!(st.seriesLinks || []).length) { this.flash('в серии нет ни одного трека'); return; }
    try {
      var имя = await this.saveSeries();
      if (!имя) return;                     // сохранение не прошло — гнать нечего
      var res = await api.seriesRun(имя);
      var о = (res && res.estimate) || {};
      this.flash('серия пошла: ' + (о.texts || 0) + ' текстов ≈ ' + времени(о.seconds));
      this.reloadSeriesState();
    } catch (e) { this.flash(msg(e)); }
  },

  /** Открыть папку трека в списке листов. Выход из меню серии в ту работу,
   *  ради которой серия и гонялась: раньше прогон кончался, и пользователь шёл
   *  искать результат руками. */
  openSeriesFolder(i) {
    var l = (this.state.seriesLinks || [])[i] || {};
    var сост = this.state.seriesState || {};
    var папка = (сост.folders || [])[i];
    if (!папка) { this.flash('папка появится, когда трек начнёт делаться'); return; }
    this.closePop();
    this.setState({ folderId: папка, moveOpen: '' }, function () { this.tog('docs'); }.bind(this));
  },

  async stopSeries() {
    try {
      await api.seriesStop();
      this.flash('остановлю после текущего текста');
    } catch (e) { this.flash(msg(e)); }
  },
};
