// Корпус, история, пул и фоновые работы — миксин: интегратор делает
// Object.assign(Nakedlunch.prototype, corpusMethods).
//
// ЗАЧЕМ ЭТОТ ФАЙЛ ПОЯВИЛСЯ (Раунд 39). требование (2026-08-02): при переносе интерфейса часть функций потерялась — перенести всё
// до конца.. Инвентаризация нашла
// шестнадцать роутов бэкенда, до которых из нового интерфейса было не
// добраться ВООБЩЕ: их звал только старый App.jsx/NakedlunchView.jsx, который
// main.jsx монтирует лишь по адресу #old. Заливка книг, включение и удаление
// источников, пересборка ударений, сроки хранения, очистка истории, возврат
// показанного, сброс «использованного» у nakedlunch, бэкап корпуса и выгрузка
// статистики. Здесь — их клиентская сторона; рисует их раздел настроек.
//
// Второе, что живёт тут же, — ОПРОС ФОНОВЫХ РАБОТ (/api/status). Роут был
// написан ещё в июле, клиентская функция api.status() существовала, и не звал
// её никто. Требование: индикатор по числу источников — сколько обработано из наличных; информативно,
// но не громоздко..

import * as api from './api.js';

// Опрос: пока работа идёт — часто, в покое — редко. Это не «на всякий случай»:
// сборка рифм по 2.87М фрагментов идёт минутами, и полминуты между кадрами
// прогресса выглядели бы как зависание.
const ОПРОС_РАБОТА = 1200;
const ОПРОС_ПОКОЙ = 12000;

// Сроки хранения истории — те же значения, что понимает бэк (дни; 0 = вечно).
export const СРОКИ_ИСТОРИИ = [
  { v: 0, name: 'вечно' }, { v: 7, name: 'неделя' }, { v: 30, name: 'месяц' },
  { v: 90, name: '3 месяца' }, { v: 365, name: 'год' },
];
// Сроки «использованного» самого nakedlunch — у него своя шкала, словами.
export const СРОКИ_ПУЛА = [
  { v: 'never', name: 'вечно' }, { v: 'month', name: 'месяц' },
  { v: '3m', name: '3 месяца' }, { v: '6m', name: 'полгода' }, { v: 'year', name: 'год' },
];
export const ПЕРИОДЫ_СБРОСА = [
  { v: 'hour', name: 'за час' }, { v: 'day', name: 'за день' },
  { v: 'week', name: 'за неделю' }, { v: 'month', name: 'за месяц' }, { v: 'all', name: 'всё' },
];

export const corpusMethods = {

  // ================= фоновые работы =================

  // Одна общая сводка для индикатора шапки. Состояния ровно четыре, и они
  // отвечают на разные вопросы:
  //   'покой'   — работ нет (или все давно закончены): кружок-контур;
  //   'работа'  — идёт одна или несколько: дуга по проценту;
  //   'ошибка'  — что-то упало или встало: приглушённый красный;
  //   'готово'  — только что закончилось: полный круг, гаснет сам.
  // Замечание: постоянно заполненный индикатор выглядит плохо.. Поэтому
  // ЗАКОНЧЕННАЯ работа держится в 'готово' недолго и уходит в покой, а не
  // висит вечно полным кругом.
  ГОТОВО_ДЕРЖИМ: 8000,

  jobsSummary() {
    var работы = this.state.jobs || [];
    if (!работы.length) return { state: 'покой', pct: 0, n: 0, running: 0 };
    var идут = работы.filter(function (j) { return j.state === 'running'; });
    var беда = работы.filter(function (j) { return j.state === 'error' || j.state === 'stalled'; });
    if (беда.length) return { state: 'ошибка', pct: 0, n: работы.length, running: идут.length };
    if (идут.length) {
      // Процент общий: сумма сделанного к сумме плана. Показывать «первую из
      // двух» было бы враньём о том, сколько осталось.
      var done = 0, total = 0;
      идут.forEach(function (j) { done += (j.done || 0); total += (j.total || 0); });
      var pct = total ? Math.round(100 * done / total) : 0;
      return { state: 'работа', pct: Math.max(0, Math.min(100, pct)), n: работы.length, running: идут.length };
    }
    // всё закончено: показываем ненадолго и гасим
    var свежо = this._jobsDoneAt && (Date.now() - this._jobsDoneAt) < this.ГОТОВО_ДЕРЖИМ;
    return { state: свежо ? 'готово' : 'покой', pct: 100, n: работы.length, running: 0 };
  },

  // Строки для попапа. Отдаём как есть с бэка — он и решает, что писать в
  // detail (проценты, «сборка ещё не запускалась», текст ошибки).
  jobRows() {
    return (this.state.jobs || []).map(function (j) {
      return {
        id: j.id, label: j.label || j.id, detail: j.detail || '',
        pct: Math.max(0, Math.min(100, j.pct || 0)),
        state: j.state || 'running',
        подпись: ({ running: 'идёт', done: 'готово', error: 'ошибка',
                    stalled: 'встало', not_started: 'не начато' })[j.state] || j.state,
      };
    });
  },

  async statusTick() {
    if (this._statusDead) return;
    try {
      var res = await api.status();
      var работы = (res && res.items) || [];
      var шли = (this.state.jobs || []).some(function (j) { return j.state === 'running'; });
      var идут = работы.some(function (j) { return j.state === 'running'; });
      if (шли && !идут) this._jobsDoneAt = Date.now();   // момент окончания — для 'готово'
      // Состояние трогаем, только когда сводка реально изменилась: опрос идёт
      // всегда, а перерисовывать документ каждые 1.2 секунды незачем.
      var было = JSON.stringify(this.state.jobs || []);
      if (было !== JSON.stringify(работы)) this.setState({ jobs: работы });
      this._statusFail = 0;
      if (this.state.ядроМолчит) this.setState({ ядроМолчит: false });
      // СЕРИЯ ДЕЛАЕТ ФАЙЛЫ ФОНОМ (Раунд 55). До этого раунда панель листов их
      // не видела, пока пользователь не трогал что-нибудь руками: за ночь
      // появлялось тридцать текстов, а на экране не менялось ничего.
      //
      // Дёргаем не каждый тик, а когда счётчик серии СДВИНУЛСЯ — то есть раз
      // на текст, примерно раз в пятнадцать секунд, а не раз в 1.2. И один
      // раз после окончания, чтобы последний текст тоже появился.
      // Заливка книги: заметить окончание ровно один раз.
      var импорт = работы.filter(function (j) { return j.id === 'import'; })[0];
      var шёл = this._импортШёл;
      this._импортШёл = !!(импорт && импорт.state === 'running');
      if (шёл && !this._импортШёл) this.importDone(импорт);

      var серия = работы.filter(function (j) { return j.id === 'series'; })[0];
      var счёт = серия && серия.state === 'running' ? серия.done : null;
      if (счёт !== this._серияСчёт) {
        this._серияСчёт = счёт;
        if (this.reloadSeriesState) this.reloadSeriesState();
        if (this.reloadSheets) this.reloadSheets();
      }
      this.statusSchedule(идут ? ОПРОС_РАБОТА : ОПРОС_ПОКОЙ);
    } catch (e) {
      // Сервер не ответил — не молчим бесконечно и не спамим: отступаем.
      this._statusFail = (this._statusFail || 0) + 1;
      // ЯДРО УМЕРЛО ПОСРЕДИ РАБОТЫ (Раунд 59). Окно при этом живо и выглядит
      // рабочим: кнопки нажимаются, ничего не происходит, и объяснения нет
      // нигде. Три промаха подряд — это уже не сетевая икота, а отсутствие
      // ядра, и об этом надо сказать прямо, а не молчать до перезапуска.
      if (this._statusFail >= 3 && !this.state.ядроМолчит) this.setState({ ядроМолчит: true });
      this.statusSchedule(Math.min(60000, ОПРОС_ПОКОЙ * Math.pow(2, this._statusFail)));
    }
  },

  statusSchedule(ms) {
    clearTimeout(this._statusT);
    var self = this;
    this._statusT = setTimeout(function () { self.statusTick(); }, ms);
  },

  statusStart() { this._statusDead = false; this.statusTick(); },
  statusStop() { this._statusDead = true; clearTimeout(this._statusT); },
  // после действия, которое ЗАПУСКАЕТ работу, ждать 12 секунд нельзя
  statusSoon() { this.statusSchedule(300); },

  // ================= корпус: источники =================

  // Список источников живёт в state.nl (ответ /api/nl/state). Роуты источников
  // возвращают свежий список — кладём его туда же, чтобы источник правды был
  // один и панель не расходилась с бэком.
  putSources(sources) {
    if (!sources) return;
    this.setState({ nl: Object.assign({}, this.state.nl || {}, { sources: sources }) });
  },

  async reloadNl() {
    try { this.setState({ nl: await api.nlState() }); } catch (e) { this.flash(e.message); }
  },

  // ЗАЛИВКА ИДЁТ ФОНОМ (Раунд 56). требование: книга появляется в списке сразу, обработка идёт фоном; сейчас нажатие не
  // подтверждается ничем..
  //
  // Роут отвечает сразу и ставит работу в очередь; ход виден в /api/status —
  // том же списке, что показывает кружок в шапке. Имена книг кладём в
  // `importing` НЕМЕДЛЕННО: список источников на бэке ещё прежний, а видеть
  // свою книгу пользователь должен с момента выбора файла, а не через минуту.
  async addBooks(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    var имена = files.map(function (f) { return String(f.name || '').replace(/\.[^.]+$/, ''); });
    this.setState({ importing: имена, corpusBusy: '' });
    try {
      var res = await api.sourceAdd(files);
      this.putSources(res.sources);
      this.statusSoon();          // ход заливки — в кружке и в панели корпуса
    } catch (e) {
      this.setState({ importing: [] });
      this.flash(e.message);
    }
  },

  // Заливка закончилась — сообщить и обновить список. Зовётся из statusTick,
  // когда пункт «Книга» ушёл из работы: держать вторую систему опроса ради
  // этого незачем.
  importDone(пункт) {
    this.setState({ importing: [] });
    if (пункт && пункт.detail) this.flash(пункт.detail);
    this.reloadNl();
  },

  // Переключение книги — ОТКЛИК СРАЗУ (Раунд 56).
  //
  // Отчёт (2026-08-05): после «отключить книгу» непонятно, отключилась ли она, и иногда не
  // отключается..
  //
  // Второе было прямым следствием первого. Ответ приходил через десятки секунд
  // (бэк переписывал state.json на 549 МБ ради одного булева — починено, см.
  // core/nlsrc/store.py), интерфейс за это время не менялся ничем, и «не сработало».
  //
  // Лечим оба конца. Точка меняется сразу, до похода на сервер; строка на
  // время похода занята и второй клик не принимает; ответ сервера — истина в
  // последней инстанции и ложится поверх; отказ откатывает точку назад и
  // говорит почему. Ждать молча больше не приходится нигде.
  async toggleSource(id) {
    var занято = this.state.srcBusy || {};
    if (занято[id]) return;                     // поход уже идёт — второй клик не в счёт
    var было = (((this.state.nl || {}).sources) || []).map(function (s) { return s; });
    this.putSources(было.map(function (s) {
      return s.id === id ? Object.assign({}, s, { active: !s.active }) : s;
    }));
    var b0 = Object.assign({}, занято); b0[id] = 1;
    this.setState({ srcBusy: b0 });
    try {
      this.putSources((await api.sourceToggle(id)).sources);
      this.reloadNl();
    } catch (e) {
      this.putSources(было);                    // сервер отказал — точка возвращается на место
      this.flash(e.message);
    } finally {
      var b = Object.assign({}, this.state.srcBusy || {});
      delete b[id];
      this.setState({ srcBusy: b });
    }
  },

  // Удаление источника необратимо, поэтому через то же подтверждение, что и
  // корзина листов (state.confirm), а не молча по клику.
  async removeSource(id) {
    var занято = this.state.srcBusy || {};
    if (занято[id]) return;
    var b1 = Object.assign({}, занято); b1[id] = 1;
    // Удаление книги переписывает state.json целиком — это законно (состав
    // фрагментов правда меняется), но идёт долго. Значит «занято» нужно и
    // здесь: иначе повторный клик по «удалить» уходит вторым запросом на уже
    // удалённый источник и возвращает «источник не найден».
    this.setState({ srcBusy: b1, confirm: '' });
    try {
      this.putSources((await api.sourceRemove(id)).sources);
      this.reloadNl();
    } catch (e) { this.flash(e.message); }
    finally {
      var b2 = Object.assign({}, this.state.srcBusy || {});
      delete b2[id];
      this.setState({ srcBusy: b2 });
    }
  },

  // Нажатие обязано что-то СКАЗАТЬ (Раунд 56). отчёт: повторный запуск прогона никак не отображался.. Запрос
  // молча терялся, если сборка в этот момент уже шла, — теперь бэк честно
  // отвечает `busy`, и мы это показываем, а не делаем вид, что запустили.
  async rebuildRhyme() {
    try {
      var r = await api.rhymeRun();
      this.flash(r && r.busy
        ? (r.detail || 'сборка уже идёт — дождись её и нажми снова')
        : 'прогон запущен: ударения, следом индекс — прогресс в кружке шапки');
      this.statusSoon();
    } catch (e) { this.flash(e.message); }
  },

  // Пересчёт только формулы качества (Раунд 57). Отдельно от полного прогона,
  // потому что это работа другой цены: там час нейросетевых ударений, здесь
  // минуты словаря частот. Сообщение так и говорит — чтобы пользователь не ждал час
  // там, где ждать пять минут.
  async rebanQuality() {
    try {
      var r = await api.rhymeReban();
      this.flash(r && r.busy
        ? (r.detail || 'сборка уже идёт — дождись её и нажми снова')
        : 'пересчёт качества запущен: банальность и слова, ударения не трогаются — минуты, прогресс в кружке шапки');
      this.statusSoon();
    } catch (e) { this.flash(e.message); }
  },

  // ---- чёрный список слов (Раунд 57) ----
  // Счётчик приходит вместе со списком: он считается тем же действием, что и
  // сам запрет (пересечение по указателю слов), поэтому показать его даром.
  async loadBlack() {
    try { this.setState({ black: await api.blacklistList() }); }
    catch (e) { this.flash(e.message); }
  },
  async addBlack(rule) {
    var п = String(rule || '').trim();
    if (!п) return;
    try {
      this.setState({ black: await api.blacklistAdd(п) });
      this.flash('в чёрном списке — эти строки больше не придут');
    } catch (e) { this.flash(e.message); }
  },
  async removeBlack(rule) {
    try { this.setState({ black: await api.blacklistRemove(rule) }); }
    catch (e) { this.flash(e.message); }
  },

  async openCorpusDir() {
    try { await api.nlOpenDir(); } catch (e) { this.flash(e.message); }
  },

  // ================= история и пул =================

  async loadRetention() {
    var h = null, n = null;
    try { h = await api.historyRetentionGet(); } catch (e) { /* нет бэка истории — оставим дефолт */ }
    try { n = await api.nlRetentionGet(); } catch (e) { /* nakedlunch не установлен */ }
    this.setState({
      histRetention: h && h.days != null ? h.days : this.state.histRetention,
      nlRetention: n && n.value ? n.value : this.state.nlRetention,
    });
  },

  async setHistRetention(days) {
    this.setState({ histRetention: days });
    try { await api.historyRetentionSet(days); } catch (e) { this.flash(e.message); }
  },

  async setNlRetention(value) {
    this.setState({ nlRetention: value });
    try { await api.nlRetentionSet(value); } catch (e) { this.flash(e.message); }
  },

  async clearHistory() {
    try {
      await api.historyClear();
      this.setState({ hist: [], confirm: '' });
      this.flash('история очищена · избранное не тронуто');
    } catch (e) { this.flash(e.message); }
  },

  // Вернуть показанное обратно в пул: по теме — пачкой, поштучно — из попапа
  // истории. Это ровно то, чем история и полезна: строка, которую прогнали
  // мимо, снова становится доступной.
  async restoreByTheme() {
    var theme = (this.state.restoreTheme || '').trim();
    if (!theme) return;
    try {
      var res = await api.historyRestoreTheme(theme);
      this.flash(res && res.restored ? ('вернул в пул: ' + res.restored)
        : ('по теме «' + theme + '» в истории ничего нет'));
      this.setState({ restoreTheme: '' });
      this.reloadHistory();
    } catch (e) { this.flash(e.message); }
  },

  async restoreOne(text) {
    try { await api.historyRestore([text]); this.flash('вернул в пул'); this.reloadHistory(); }
    catch (e) { this.flash(e.message); }
  },

  // Подпись времени: сегодняшнее — часами, всё остальное — датой. требование: показывать реальное время либо не показывать вовсе.. Одинаковым оно было по
  // двум причинам: перенос истории ставил всем «сейчас» (починено на бэке), а
  // здесь любое время показывалось как часы, и вчерашнее не отличалось от
  // сегодняшнего.
  histRow(x) {
    var ts = (x.shown_at || 0) * 1000;
    var d = new Date(ts);
    var сегодня = new Date(); сегодня.setHours(0, 0, 0, 0);
    var чч = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    var дата = String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0');
    return {
      t: x.text,
      time: !ts ? '' : (ts >= сегодня.getTime() ? чч : дата),
      full: !ts ? '' : (дата + '.' + d.getFullYear() + ' ' + чч),
    };
  },

  async reloadHistory() {
    try {
      var h = await api.history(''), self = this;
      this.setState({ hist: (h.items || []).map(function (x) { return self.histRow(x); }) });
    } catch (e) { this.flash(e.message); }
  },

  async clearNlUsed(mode) {
    try {
      var res = await api.nlClearUsed(mode);
      this.flash('сброшено показанного: ' + ((res && res.cleared) || 0));
      this.setState({ confirm: '' });
      this.reloadNl();
    } catch (e) { this.flash(e.message); }
  },

  // ================= избранное: полный набор =================
  // Раунд 40. Требование: избранное и история должны уметь удалять, добавлять и изменять..
  // При переносе интерфейса остались «вставить» и «минус»; поиск, копирование,
  // правка, ручное добавление, отмена удаления и выгрузка потерялись вместе со
  // старым App.jsx.

  // Копирование в буфер. Внутри окна программы clipboard недоступен без
  // защищённого соединения, поэтому есть запасной путь через скрытое поле —
  // молча «скопировано» без копирования было бы хуже всего.
  async copyText(t) {
    if (!t) return;
    try {
      await navigator.clipboard.writeText(t);
      this.flash('скопировано');
      return;
    } catch (e) { /* ниже честный запасной путь */ }
    try {
      var ta = document.createElement('textarea');
      ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      var ok = document.execCommand('copy');
      ta.remove();
      this.flash(ok ? 'скопировано' : 'не удалось скопировать');
    } catch (e2) {
      this.flash('не удалось скопировать');
    }
  },

  // Добавить строку в избранное текстом (из истории, из попапа, руками).
  addFavText(t) {
    t = String(t || '').trim();
    if (!t) return;
    var есть = (this.state.favs || []).some(function (f) { return f.t === t; });
    if (есть) { this.flash('уже в избранном'); return; }
    var self = this;
    this.setState({ favs: [{ t: t }].concat(this.state.favs || []) });
    api.favAdd({ text: t }).catch(function (e) { self.flash(e.message); });
    this.flash('в избранное');
  },

  // Ручное добавление: берём выделенную строку документа, иначе — пустую
  // заготовку, которую тут же открываем на правку. Пустых записей не плодим.
  addFavManual() {
    var r = this.cur()[this.state.caret];
    var t = r && r.type === 'line' ? String(r.text || '').trim() : '';
    if (!t) { this.flash('поставь каретку на строку — добавлю её'); return; }
    this.addFavText(t);
  },

  // Правка = удалить старое, добавить новое: отдельного роута правки у бэка
  // нет, а два честных вызова дают ровно тот же результат.
  editFav(было, стало) {
    стало = String(стало || '').trim();
    this.setState({ favEdit: '' });
    if (!стало || стало === было) return;
    var self = this;
    var favs = (this.state.favs || []).map(function (f) { return f.t === было ? { t: стало } : f; });
    this.setState({ favs: favs });
    api.favRemove(было).catch(function (e) { self.flash(e.message); });
    api.favAdd({ text: стало }).catch(function (e) { self.flash(e.message); });
    this.flash('изменено');
  },

  // Отмена удаления: снятое из избранного помним до следующего снятия.
  // Без этого один промах по «−» стоил бы строки безвозвратно.
  undoFav() {
    var t = this.state.favUndo;
    if (!t) return;
    this.setState({ favUndo: '' });
    this.addFavText(t);
  },

  exportFavs(вид) {
    var favs = (this.state.favs || []).map(function (f) { return f.t; });
    if (!favs.length) { this.flash('избранное пусто'); return; }
    var имя = 'избранное-' + this._stamp() + '.' + вид;
    var текст = вид === 'md'
      ? '# Избранное — nakedlunch (' + this._stamp() + ')\n\n' + favs.map(function (t) { return '- ' + t; }).join('\n') + '\n'
      : favs.join('\n');
    var self = this;
    api.saveFile(имя, текст, вид === 'md' ? 'text/markdown' : 'text/plain')
      .then(function (путь) { if (путь) self.flash('сохранено: ' + имя); })
      .catch(function (e) { self.flash(e.message); });
  },

  // ================= журнал =================
  // ОДНА КНОПКА ВМЕСТО ПОХОДА В ПАПКУ (Раунд 59). Отчёт целиком собирает
  // сервер; здесь только показать и положить в буфер. Копирование через
  // navigator.clipboard с запасным путём: в WKWebView разрешение на буфер
  // выдаётся не всегда, а «скопировать» обязано работать всегда.
  async обновитьЛог() {
    try {
      var о = await api.журнал();
      this.setState({ логТекст: о['текст'] || '', логАвария: !!о['аварийно'] });
    } catch (e) {
      this.setState({ логТекст: 'не удалось собрать отчёт: ' + e.message
        + '\n\nЯдро не отвечает. Закрой и открой программу — при следующем '
        + 'запуске журнал этой сессии сохранится и будет здесь.' });
    }
  },

  async копироватьЛог() {
    if (!this.state.логТекст) await this.обновитьЛог();
    var т = this.state.логТекст || '';
    var ок = false;
    try { await navigator.clipboard.writeText(т); ок = true; } catch (e) { ок = false; }
    if (!ок) {
      try {
        var ta = document.createElement('textarea');
        ta.value = т; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        ок = document.execCommand('copy');
        document.body.removeChild(ta);
      } catch (e) { ок = false; }
    }
    this.setState({ логСкопирован: ок });
    if (!ок) this.flash('не удалось скопировать — выдели текст и скопируй вручную');
    var self = this;
    setTimeout(function () { self.setState({ логСкопирован: false }); }, 2000);
  },

  // ================= статистика =================
  // Панель статистики живёт своей кнопкой (требование: статистика живёт в своей кнопке и подводится там целиком.), а
  // цифры тянем при открытии — не на каждый рендер и не на старте.
  async loadStats() {
    // Воронка идёт РЯДОМ со статистикой и с ТЕКУЩИМИ ручками пользователя: смысл
    // карты в том, чтобы он видел цену СВОИХ настроек, а не средних по палате.
    try {
      var к = this.state.params || {};
      // ПОЛОЖЕНИЕ РУЧКИ, А НЕ ФОРМУЛА (Раунд 58). Здесь стояла ВТОРАЯ копия
      // перевода «ручка → потолок»; формула теперь одна, на сервере.
      var q = '?banality=' + (к['Банальность'] == null ? 0.83 : Number(к['Банальность']))
        + (Number(к['Мат']) === 0 ? '&no_mat=1' : '')
        + (Number(к['Мат']) >= 0.9995 ? '&only_mat=1' : '')
        + '&clausula=' + (Number(к['Клаузула']) || 0);
      // Отчёт тянем ВМЕСТЕ со статистикой: снимок панели должен показывать и
      // среду, и число ошибок за сессию — иначе по нему нельзя отличить
      // «работает плохо» от «не собрано».
      var пара = await Promise.all([
        api.stats(),
        api.nlFunnel(q).catch(function () { return null; }),
        api.журнал().catch(function () { return null; }),
      ]);
      var о = пара[2] || {};
      var ошибок = ((о['записи'] || []).filter(function (з) { return з['уровень'] === 'ошибка'; })).length;
      var среда = (о['текст'] || '').split('\n').filter(function (л) { return л.indexOf('среда') === 0; })[0] || '';
      var версия = (о['текст'] || '').split('\n').filter(function (л) { return л.indexOf('правила индекса') === 0; })[0] || '';
      this.setState({ statsData: пара[0], funnel: пара[1],
                      логОшибок: ошибок,
                      среда: среда.replace('среда', '').trim(),
                      версия: версия ? 'индекс: ' + версия.split(' ').slice(-1)[0] : '' });
    }
    catch (e) { this.flash(e.message); }
  },

  // О чём тексты. Требование: частые темы считать не по вводимым темам, а по сохранённым текстам — так
  // картина объективнее..
  //
  // Считаем по тому, что ОСТАВЛЕНО: избранное плюс живые листы. Слово
  // берём по основе (первые пять букв), чтобы «деньги/деньгами/денег» считались
  // одним, — морфологии на клиенте нет, а лемматизировать ради облака слов
  // ходить на бэк дороже, чем оно того стоит.
  СТОП: ('и в не на я он она они мы вы ты что как это то так но да же ли бы за из по до от над под при про для без у о а или если когда где чем чтоб чтобы вот там тут уже ещё еще был была были было быть есть мне меня мной тебя тебе его ему её ее их им нас вам все всё весь вся вcя тот эта этот эти той том тем как-то ну ах ой эх').split(' '),
  textThemes() {
    var куски = [];
    (this.state.favs || []).forEach(function (f) { куски.push(f && f.t ? f.t : f); });
    (this.state.sheets || []).forEach(function (sh) {
      if (sh && !sh.trashed && Array.isArray(sh.doc)) {
        sh.doc.forEach(function (r) { if (r && r.type === 'line' && r.text) куски.push(r.text); });
      }
    });
    (this.cur() || []).forEach(function (r) { if (r && r.type === 'line' && r.text) куски.push(r.text); });
    if (!куски.length) return [];
    var стоп = {}; this.СТОП.forEach(function (w) { стоп[w] = 1; });
    var счёт = {}, показ = {};
    куски.forEach(function (t) {
      String(t).toLowerCase().replace(/ё/g, 'е').split(/[^а-яa-z]+/).forEach(function (w) {
        if (w.length < 4 || стоп[w]) return;
        var корень = w.slice(0, 5);
        счёт[корень] = (счёт[корень] || 0) + 1;
        // показываем самую короткую встреченную форму — она ближе к словарной
        if (!показ[корень] || w.length < показ[корень].length) показ[корень] = w;
      });
    });
    return Object.keys(счёт)
      .filter(function (k) { return счёт[k] > 1; })
      .sort(function (a, b) { return счёт[b] - счёт[a]; })
      .slice(0, 24)
      .map(function (k) { return { w: показ[k], n: счёт[k] }; });
  },

  // ================= выгрузка =================

  // Имя файла с датой: выгрузок со временем накапливается много, и «stats.json»
  // поверх «stats.json» — потеря, а не сохранение.
  _stamp() {
    var d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  },

  async dump(url, name, mime) {
    try {
      var text = await api.fetchText(url);
      var путь = await api.saveFile(name, text, mime);
      if (путь) this.flash('сохранено: ' + name);
    } catch (e) { this.flash(e.message); }
  },

  exportCorpus() { return this.dump('/api/corpus/export.json', 'nakedlunch-корпус-' + this._stamp() + '.json', 'application/json'); },
  exportStatsJson() { return this.dump('/api/stats/export.json', 'nakedlunch-статистика-' + this._stamp() + '.json', 'application/json'); },
  exportStatsCsv() { return this.dump('/api/stats/export.csv', 'nakedlunch-статистика-' + this._stamp() + '.csv', 'text/csv'); },
};
