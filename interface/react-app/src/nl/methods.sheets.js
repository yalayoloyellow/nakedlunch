// Методы листов/папок/корзины из дизайна «Editor First» (project-notes/
// mockups/design-v2/Editor First.dc.html, строки 3118..3227) — миксин:
// интегратор делает Object.assign(Nakedlunch.prototype, sheetsMethods).
// Адаптация к серверу (контракт /api/sheets, PLAN.md фаза 0):
//   - листы живут на ДИСКЕ (~/Documents/nakedlunch/тексты, core/sheets.py);
//     state.sheets — кэш списка БЕЗ doc внутри, doc есть только у открытого;
//   - stash() дизайна упразднён: текущий лист досохраняет markSaved
//     (methods.doc, дебаунс 900 мс), а перед сменой/переездом — flushSave();
//   - new/dup/trash/restore/purge/purgeAll/rename/move/folder* = вызов api.*
//     + перечитка списка; оптимизма нет сознательно — объёмы маленькие,
//     список с диска и есть источник правды;
//   - id листа = путь относительно vault ('Папка/Название.md'), поэтому
//     rename/move МЕНЯЮТ id — открытый лист переезжает на новый;
//   - умные папки (addFolder с keys) — клиентские сохранённые запросы
//     (решение прожарки №6): живут в настройках сервера ключом
//     nl_smart_folders, а не каталогами на диске; boot уже кладёт настройки
//     в state.settings — отсюда они и читаются;
//   - буквы рифмовки пересчитывает бэк при чтении (решение №6), пометки
//     src — сессионный, звёзды восстанавливаются по тексту.

import * as api from './api.js';

function msg(e) { return e && e.message ? e.message : String(e); }

export const sheetsMethods = {
  // переключатель пилюль шапки (дизайн, строка 3294) — общий для всех попапов;
  // если другой миксин принесёт свой, реализация та же — Object.assign безвреден
  tog(p) { if (this.state.openPill === p) this.closePop(); else this.openPop({ openPill: p }); },

  // ---- список: перечитка и досохранение ----
  // перечитать список с сервера; вызывается после каждой мутации
  async reloadSheets(extra) {
    var sh = await api.sheetsList();
    var patch = Object.assign({ sheets: sh.sheets || [], folders: sh.folders || [] }, extra || {});
    var переезд = this.открытыйПереехал(sh.sheets || []);
    if (переезд) patch.sheetId = переезд;
    this.setState(patch);
    return sh;
  },

  /** Открытый лист переименовали ПОД НАМИ — куда он делся (Раунд 55).
   *
   *  Серия в конце каждого трека нумерует его листы по баллу: «дверь
   *  скрипнула» становится «03 дверь скрипнула». Если этот лист открыт в
   *  редакторе, его путь перестаёт существовать, и сохранение падает с
   *  честным «лист не найден» — громко, но работать невозможно.
   *
   *  Ищем по имени БЕЗ номера ранга: ровно тот же ключ, по которому серия
   *  хранит баллы в сайдкаре (series_run._чистое). Совпадений в одной папке
   *  быть не может — имена там уникальны по построению.
   *
   *  Чистая функция, поэтому проверяется в node без сервера. */
  открытыйПереехал(листы) {
    var id = this.state.sheetId;
    if (!id) return '';
    if ((листы || []).some(function (x) { return x.id === id; })) return '';   // на месте
    var чистое = function (путь) {
      var части = String(путь).split('/');
      var имя = части.pop().replace(/\.md$/, '').replace(/^\d+\s+/, '');
      return части.join('/') + '/' + имя;
    };
    var ключ = чистое(id);
    var нашёлся = (листы || []).filter(function (x) { return чистое(x.id) === ключ; })[0];
    return нашёлся ? нашёлся.id : '';
  },
  // вместо stash() дизайна: doc чужих листов на клиенте не живёт — перед
  // сменой/переездом досохраняем ТЕКУЩИЙ, если дебаунс markSaved ещё не успел.
  // false = не сохранилось; разрушительные переходы при этом отменяются,
  // чтобы правки не пропали молча
  async flushSave() {
    var st = this.state;
    if (!this._saveT && !st.dirty) return true;
    clearTimeout(this._saveT); this._saveT = null;
    var id = st.sheetId;
    var here = (st.sheets || []).filter(function (x) { return x.id === id; })[0];
    if (!id || !here || here.trashed) return true;
    try {
      var res = await api.sheetsWrite(id, this.cur());
      this.setState({ dirty: false, savedAt: (res && res.at) || this.clock() });
      return true;
    } catch (e) {
      this.flash('не сохранилось: ' + msg(e));
      return false;
    }
  },
  // строки с бэка → строки документа дизайна: буква рифмовки уже пересчитана
  // сервером; пометка src — сессионная (решение №6), текст с диска —
  // «мой» и закреплён; звёзды восстанавливаются по тексту из избранного
  hydrateRows(rows) {
    var favs = this.state.favs || [];
    // избранное может прийти и строками (/api/state), и объектами {t} — сверяем по тексту
    var favHit = function (t) { return favs.some(function (f) { return (f && f.t != null ? f.t : f) === t; }); };
    return (rows || []).map(function (r) {
      if (r.type === 'role') return { type: 'role', text: r.text || '', level: r.level || 2 };
      var t = r.text || '';
      return { type: 'line', text: t, letter: r.letter || 'а', src: 'я', fav: !!t && favHit(t) };
    });
  },

  // ---- открытие и создание ----
  async openSheet(id) {
    if (id === this.state.sheetId) { this.closePop(); return; }
    if (!(await this.flushSave())) return;
    try {
      var res = await api.sheetsRead(id);
      var rows = this.hydrateRows(res.rows);
      var at = ((this.state.sheets || []).filter(function (x) { return x.id === id; })[0] || {}).at || '';
      this.hist = []; this.future = [];
      this._doc$ = rows;
      this.closePop({ sheetId: res.id, doc: rows, undoN: 0, redoN: 0, pop: null, selAll: false, dirty: false, savedAt: at });
    } catch (e) { this.flash(msg(e)); }
  },
  async newSheet() {
    if (!(await this.flushSave())) return;
    try {
      // сервер сам даёт «Без названия» и разводит коллизии суффиксом « 2»
      var made = await api.sheetsCreate({});
      var res = await api.sheetsRead(made.id);
      var sh = await api.sheetsList();
      var rows = this.hydrateRows(res.rows);
      this.hist = []; this.future = [];
      this._doc$ = rows;
      this.closePop({
        sheets: sh.sheets || [], folders: sh.folders || [], sheetId: made.id, doc: rows,
        undoN: 0, redoN: 0, pop: null, selAll: false, marks: {}, renaming: '', dirty: false,
        savedAt: ((sh.sheets || []).filter(function (x) { return x.id === made.id; })[0] || {}).at || ''
      });
      this._focusRename = 'title';
      this.setState({ titleEdit: true });
    } catch (e) { this.flash(msg(e)); }
  },
  async dupSheet(id) {
    // копия открытого должна включать свежие правки — сначала досохранить
    if (id === this.state.sheetId && !(await this.flushSave())) return;
    try {
      await api.sheetsDuplicate(id);
      await this.reloadSheets();
    } catch (e) { this.flash(msg(e)); }
  },
  async renameSheet(id, val) {
    var v = (val || '').trim();
    var cur = (this.state.sheets || []).filter(function (x) { return x.id === id; })[0];
    if (!v || !cur || v === cur.title) { this.setState({ renaming: '' }); return; }
    // rename меняет id (это путь файла) — висящее сохранение по старому id
    // молча промахнулось бы, поэтому сначала досохраняем
    if (id === this.state.sheetId && !(await this.flushSave())) { this.setState({ renaming: '' }); return; }
    try {
      var res = await api.sheetsRename(id, v);
      var patch = { renaming: '' };
      if (this.state.sheetId === id) patch.sheetId = res.id;
      await this.reloadSheets(patch);
    } catch (e) {
      this.setState({ renaming: '' });
      this.flash(msg(e));
    }
  },

  // ---- папки и умные папки ----
  // текст листа для фильтра умной папки. Честное ограничение фазы 0: полного
  // текста чужих листов на клиенте нет (они живут на диске, doc есть только у
  // открытого), поэтому фильтр видит заголовки ВСЕХ листов и содержимое
  // ОТКРЫТОГО; полнотекст придёт с серверным поиском позже
  sheetPlain(sh) {
    var doc = sh.id === this.state.sheetId ? this.cur() : [];
    return (sh.title + ' ' + doc.map(function (r) { return r.text || ''; }).join(' ')).toLowerCase();
  },
  inFolder(sh, f) {
    if (!f) return true;
    if (f.keys) { var t = this.sheetPlain(sh); return f.keys.some(function (k) { return k && t.indexOf(k) >= 0; }); }
    // Папка со ВСЕМ, что под ней (Раунд 53). Точное равенство было верно при
    // одноуровневых папках; с деревом оно означало бы, что «Серии» показывают
    // ноль листов, храня при этом весь материал в подпапках — то есть папка
    // выглядела бы пустой ровно там, где в ней больше всего.
    return sh.folder === f.id || (sh.folder || '').indexOf(f.id + '/') === 0;
  },

  /** Папка, внутри которой создаётся новая. Выбрана обычная — создаём в ней:
   *  так до вложенности можно дотянуться, не заводя ни одной новой кнопки. */
  folderParent() {
    var f = this.folderById(this.state.folderId);
    return f && !f.keys ? f.id : '';
  },
  // умные папки живут в state.settings (зеркало настроек сервера), обычные —
  // в state.folders (кэш каталогов vault); наружу отдаём единый список
  smartFolders() {
    var st = this.state.settings;
    var list = st && Array.isArray(st.nl_smart_folders) ? st.nl_smart_folders : [];
    return list.filter(function (f) { return f && f.id && f.name && Array.isArray(f.keys) && f.keys.length; });
  },
  allFolders() { return (this.state.folders || []).concat(this.smartFolders()); },
  folderById(id) { return this.allFolders().filter(function (f) { return f.id === id; })[0] || null; },
  saveSmartFolders(list) {
    var self = this;
    var st = Object.assign({}, this.state.settings || {});
    st.nl_smart_folders = list;
    this.setState({ settings: st });
    // проверяем результат, а не сам вызов: сервер, не знающий ключа,
    // молча отфильтрует его — тогда папка живёт только до перезапуска
    api.settingsSet({ nl_smart_folders: list }).then(function (res) {
      if (!res || !Array.isArray(res.nl_smart_folders)) self.flash('умные папки не сохранились на сервере');
    }, function (e) { self.flash(msg(e)); });
  },
  async addFolder(name, keys) {
    if (keys) {
      // решение №6: умная папка = сохранённый запрос, не каталог на диске
      var f = { id: 'smart-' + Date.now(), name: name, keys: keys };
      this.saveSmartFolders(this.smartFolders().concat([f]));
      this.setState({ folderDraft: '', folderId: f.id });
      this.flash('умная папка · ' + keys.join(', '));
      return;
    }
    try {
      // внутрь выбранной папки, если она выбрана — см. folderParent
      var род = this.folderParent();
      var made = await api.sheetsFolderCreate(род ? род + '/' + name : name);
      await this.reloadSheets({ folderDraft: '', folderId: made.id });
      this.flash(род ? 'папка создана в «' + род + '»' : 'папка создана');
    } catch (e) { this.flash(msg(e)); }
  },
  async moveSheet(id, folderId) {
    var f = this.folderById(folderId);
    if (f && f.keys) return;   // умная папка — не каталог, физически переложить нельзя
    // move меняет id открытого листа — как и у rename, сначала досохранить
    if (id === this.state.sheetId && !(await this.flushSave())) { this.setState({ moveOpen: '' }); return; }
    try {
      var res = await api.sheetsMove(id, folderId || '');
      var patch = { moveOpen: '' };
      if (this.state.sheetId === id) patch.sheetId = res.id;
      await this.reloadSheets(patch);
    } catch (e) {
      this.setState({ moveOpen: '' });
      this.flash(msg(e));
    }
  },
  async dropFolder(id) {
    var f = this.folderById(id);
    var nextFolderId = this.state.folderId === id ? '' : this.state.folderId;
    if (f && f.keys) {
      // умная папка — клиентская: убираем из настроек, файлы не трогаем
      this.saveSmartFolders(this.smartFolders().filter(function (x) { return x.id !== id; }));
      this.setState({ folderId: nextFolderId });
      return;
    }
    var sid = this.state.sheetId || '';
    var mine = sid.indexOf(id + '/') === 0;
    if (mine && !(await this.flushSave())) return;
    try {
      var title = mine ? (((this.state.sheets || []).filter(function (x) { return x.id === sid; })[0] || {}).title || '') : '';
      await api.sheetsFolderDelete(id);   // файлы переезжают в корень (сервер)
      var sh = await api.sheetsList();
      var patch = { sheets: sh.sheets || [], folders: sh.folders || [], folderId: nextFolderId };
      if (mine) {
        // id открытого сменился ('Папка/x.md' → 'x.md'): ищем его по заголовку
        // среди корневых; коллизия имён могла дать суффикс « 2» — тогда честно
        // переезжаем на первый живой через rehome
        var moved = (sh.sheets || []).filter(function (x) { return !x.trashed && !x.folder && x.title === title; })[0];
        if (moved) patch.sheetId = moved.id;
        else await this.rehome(sh.sheets || [], patch);
      }
      this.setState(patch);
    } catch (e) { this.flash(msg(e)); }
  },

  // ---- корзина ----
  // если текущий лист исчез из живых — переехать на первый, а если живых нет,
  // завести пустой (в дизайне — в памяти, здесь честно на сервере)
  async rehome(sheets, patch) {
    var live = sheets.filter(function (x) { return !x.trashed; });
    var next = live[0];
    if (!next) {
      var made = await api.sheetsCreate({});
      var sh = await api.sheetsList();
      sheets = sh.sheets || [];
      patch.folders = sh.folders || [];
      next = sheets.filter(function (x) { return x.id === made.id; })[0] || { id: made.id, title: made.title, at: '' };
    }
    var res = await api.sheetsRead(next.id);
    var rows = this.hydrateRows(res.rows);
    this.hist = []; this.future = [];
    this._doc$ = rows;
    return Object.assign(patch, { sheets: sheets, sheetId: next.id, doc: rows, undoN: 0, redoN: 0, pop: null, selAll: false, marks: {}, caret: -1, dirty: false, savedAt: next.at || '' });
  },
  async trashSheet(id) {
    // содержимое уезжает в корзину свежим; ошибка сохранения не блокирует —
    // лист всё равно отправляется в корзину, а flash уже честно сказал своё
    if (id === this.state.sheetId) await this.flushSave();
    try {
      await api.sheetsTrash(id);
      var sh = await api.sheetsList();
      var patch = { sheets: sh.sheets || [], folders: sh.folders || [] };
      if (id === this.state.sheetId) await this.rehome(patch.sheets, patch);
      this.setState(patch);
    } catch (e) { this.flash(msg(e)); }
  },
  async restoreSheet(id) {
    try {
      await api.sheetsRestore(id);
      await this.reloadSheets({ confirm: '' });
    } catch (e) { this.flash(msg(e)); }
  },
  async purgeSheet(id) {
    if (this.state.confirm !== id) { this.armConfirm(id); return; }
    try {
      await api.sheetsPurge(id);
      var sh = await api.sheetsList();
      var patch = { sheets: sh.sheets || [], folders: sh.folders || [], confirm: '' };
      // открытый лист не бывает в корзине (trashSheet сразу переезжает),
      // но проверка из дизайна остаётся страховкой
      if (id === this.state.sheetId) await this.rehome(patch.sheets, patch);
      this.setState(patch);
      this.flash('лист удалён навсегда');
    } catch (e) { this.flash(msg(e)); }
  },
  async purgeAll() {
    if (this.state.confirm !== 'all') { this.armConfirm('all'); return; }
    var st = this.state;
    var gone = (st.sheets || []).some(function (x) { return x.trashed && x.id === st.sheetId; });
    try {
      var res = await api.sheetsPurgeAll();
      var sh = await api.sheetsList();
      var patch = { sheets: sh.sheets || [], folders: sh.folders || [], confirm: '', trashView: false };
      if (gone) await this.rehome(patch.sheets, patch);
      this.setState(patch);
      this.flash('корзина очищена · ' + res.n);
    } catch (e) { this.flash(msg(e)); }
  },
  armConfirm(key) {
    var self = this;
    this.setState({ confirm: key });
    clearTimeout(this._confT);
    this._confT = setTimeout(function () { self.setState({ confirm: '' }); }, 3200);
  },

  // ---- фокус ----
  focusFirstLine() {
    var doc = this.cur();
    for (var i = 0; i < doc.length; i++) if (doc[i].type === 'line') { this._focus = i; this._focusAt = null; break; }
    this.forceUpdate();
  },
  // фокус свежесозданного поля: в дизайне это делал componentDidUpdate по
  // _focusRename (строка 1505) — в порте то же самое делает ref самого поля
  titleInputRef(el) { if (el && this._focusRename === 'title') { el.focus(); el.select(); this._focusRename = null; } },
  folderInputRef(el) { if (el && this._focusRename === 'folder') { el.focus(); el.select(); this._focusRename = null; } },

  // «открыть папку» — настоящий Finder через бэк (в дизайне была заглушка с flash)
  openVault() { var self = this; api.sheetsOpenDir().catch(function (e) { self.flash(msg(e)); }); },
};
