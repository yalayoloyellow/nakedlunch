// Профили сцены, профили вида и палитра фристайла — миксин на прототипе
// Nakedlunch (как в дизайне: один класс, у нас — модули).
// Источник: project-notes/mockups/design-v2/Editor First.dc.html, class-регион
// 2681..3043 (PAL_DEF/PROF_KEY/engineControls/PROF_SKIP_STATE/UIPROF_KEY/
// UI_SKIP/uiSnapshot/load*/save*/toggleUiDef/applyUiProfile/blankUi/bootUi/
// BLANK_ID/loadDefProf/poke/fsStage/profileList/toggleDefProf/snapshotProfile/
// curPreset/pickPreset/applyProfile/loadPal/savePal/palInput/applyPal/
// syncPanelColor/pickPal/rememberPal) — перенос дословный, кроме:
//
//  1) ХРАНИЛИЩЕ (решение прожарки 11, единственное сознательное отступление):
//     дизайн клал профили, палитру и отметки «по умолчанию» в localStorage —
//     артефакт среды разработки. У нас всё живёт файлом рядом с corpus.json:
//     профили сцены → api.settingsSet({nl_fs_profiles}), профили вида →
//     {nl_ui_profiles}, палитра → {nl_palette}, текущий вид (cfg) → {nl_view}
//     с дебаунсом 600 мс. Чтение — из state.settings, положенного boot()'ом.
//     Отметка «загружать при запуске» едет внутри своего же ключа
//     ({list, def}), а не отдельным: белый список core/settings.py открыт на
//     четыре ключа, и заводить пятый ради одной строки — лишняя сущность.
//  2) curPreset(): запасной путь дизайна читал журнал движка из localStorage
//     ('extendo_bc_recent') — у нас журнал отдаёт сам движок (c.fsEngine).
//  3) bootUi(): без профиля вида по умолчанию дизайн звал blankUi(), то есть
//     сбрасывал вид к исходному. У нас вид ПЕРЕЖИВАЕТ перезапуск (nl_view),
//     и такой сброс стирал бы восстановленное — поэтому без профиля вид
//     остаётся тем, что вернул сервер.
//  4) PROF_SKIP_STATE расширен нашими ключами: дизайн снимал «всё состояние,
//     кроме документа и служебных полей», у нас служебных больше (данные
//     сервера: settings/corpus/nl/favs/hist/stanzaForms). Профиль сцены с
//     копией этих данных воскрешал бы их устаревший снимок поверх живых.
//  5) ИМЕНА, чтобы миксины не перетирали друг друга на одном прототипе:
//     bootFs/topUpFs дизайна здесь зовутся bootProfile/topUpProfile (имя
//     bootFs забрал модуль движка), fsStage() не дублируется — он живёт
//     в methods.fs.js, здесь только тонкая обёртка _stage().
//
// Снятие профиля сцены С DOM-ЭЛЕМЕНТОВ (engineControls читает input[id]/
// select[id]) сохранено как есть — оно работает и с нашей разметкой, id
// ручек движка перенесены в render.fspanels.jsx дословно.

import * as api from './api.js';
import { журнал } from './methods.fsglue.js';
import { КЛЮЧИ_МОДЕЛИ } from './methods.shelves.js';

// «крутилку крутят», а не «нажимают сохранить»: пишем не чаще раза в 600 мс
const VIEW_DEBOUNCE = 600;

export const fsProfileMethods = {
  // ---- константы дизайна ----
  PAL_DEF: {
    panel: ['#2436e0', '#d81b74', '#e6620a', '#5b1fd6', '#0a8f82', '#c81f3f'],
    ink: ['#ffffff', '#f2e8cf', '#ffd166', '#8ecae6', '#ff6b6b', '#b5e48c'],
    glow: ['#7a5cff', '#00e0ff', '#ff2d95', '#ffb703', '#37ff8b', '#ff4d3d']
  },
  // профиль = все ручки фристайла: свои значения, движковые инпуты и режимы.
  // ручки не перечисляем: берём всё, что есть в панелях — новые подхватятся сами
  PROF_SKIP_IDS: { fontFile: 1, trackFile: 1 },
  // состояние снимаем целиком, кроме документа и служебных полей — новые флаги входят сами
  PROF_SKIP_STATE: {
    doc: 1, closing: 1, subPill: 1, subClosing: 1, defProf: 1, uiDefProf: 1, sheets: 1, sheetId: 1,
    folders: 1, marks: 1, markAnchor: 1, undoN: 1, redoN: 1, dirty: 1, savedAt: 1, flashMsg: 1,
    confirm: 1, openPill: 1, fsSetOpen: 1, fsLineOpen: 1, profiles: 1, profId: 1, profEdit: 1,
    uiProfiles: 1, uiProfId: 1, uiProfEdit: 1, popTab: 1, pop: 1,
    // в дизайне ровно так: значение 0 — ложное, поэтому ключ фактически НЕ
    // пропускается. Переносим как есть, чтобы не расходиться с макетом
    fps: 0,
    // recLock рядом с recOn: профиль вида, сохранённый во время записи,
    // воскресил бы замок хрома — интерфейс исчез бы навсегда без записи
    presets: 1, fonts: 1, camList: 1, recOn: 1, recLock: 1, tab: 1, live: 1, liveTick: 1, chipOpen: 1,
    juncOpen: 1, titleEditing: 1, renaming: 1,
    // ---- расширение порта (см. шапку, п.4) ----
    // данные сервера: их снимок в профиле сцены — устаревшая копия живого
    settings: 1, corpus: 1, nl: 1, stanzaForms: 1, favs: 1, hist: 1, thesaurus: 1,
    lastFunnel: 1, lastInsertN: 1, popItems: 1, popLoading: 1, lastPipeFunnel: 1, genStatus: 1,
    // ЖЕЛЕЗО. В дизайне micOn/trackOn были просто флажками подсветки — звуком
    // заведовал внешний скрипт. Теперь это реальный микрофон и реальный файл
    // пользователя: профиль, воскрешающий micOn=true, зажёг бы иконку, не открыв
    // ни одного потока, а trackOn — обещал бы трек, которого в профиле нет и быть
    // не может. camOn остаётся: его applyProfile честно поднимает камерой
    micOn: 1, trackOn: 1,
    // cfg и pal профиль хранит отдельными полями (snapshotProfile) — в stt их дубль не нужен
    cfg: 1, pal: 1,
    // состояние редактора и списков: к сцене отношения не имеет
    titleEdit: 1, trashView: 1, folderId: 1, folderDraft: 1, moveOpen: 1, selAll: 1, caret: 1,
    savedSnap: 1, saveFlash: 1, customProfiles: 1, myProfN: 1, stanzaProfile: 1,
    // ---- МОДЕЛЬ ГЕНЕРАЦИИ ----
    // Не перечисляем руками: список живёт рядом с самой моделью
    // (methods.shelves.js: КЛЮЧИ_МОДЕЛИ) и подмешивается ниже. Ручной список
    // здесь уже дважды отставал от состояния — см. комментарий у КЛЮЧИ_МОДЕЛИ.
    // presetTick — счётчик перерисовки каталога пресетов (движок отвечает
    // объектом, а не DOM: без счётчика панель не узнаёт о смене пресета)
    presetQ: 1, presetTab: 1, presetTick: 1
  },
  // Ключи cfg, которые профиль сцены НЕ снимает и НЕ применяет, хотя они с
  // приставкой fs: избранное и журнал пресетов — общие на приложение. Иначе
  // старый профиль воскрешал бы свой снимок избранного поверх живого.
  PROF_SKIP_CFG: { fsBcFav: 1, fsBcRecent: 1 },
  // всё, кроме настроек сцены: новые ручки вида попадают в профиль сами, без списка
  UI_SKIP: { fsSize: 1, fsAlign: 1, fsWeight: 1, fsColor: 1, fsBcOpacity: 1, fsGain: 1 },
  BLANK_ID: '__blank',
  UI_BLANK_ID: '__uiblank',
  // исходные значения ручек — не «пусто»: ореол 45, свечение 140, зерно 18.
  // Для пустой сцены гасим явно
  BLANK_ENG: { bloomSlider: 0, glowSlider: 0, grainSlider: 0, bgBlurSlider: 0, textBlurSlider: 0, textDistortSlider: 0, postfxBlurSlider: 0, postfxBendSlider: 0, fsScaleSlider: 100, panelOpacitySlider: 0 },

  // ---- мелочи ----
  // окно настроек сцены: onCardInput ищет в нём подписи [data-val-for]
  cardsRef(el) { this._cards = el; },
  // fsStage() здесь НЕ объявлен: он принадлежит миксину сцены (methods.fs.js).
  // Дубль на том же прототипе был бы вторым источником правды
  _stage() { return typeof this.fsStage === 'function' ? this.fsStage() : null; },
  // Нативные контролы движка слушают только свои события — меняем значение и «толкаем» его
  poke(el, v, inputOnly) {
    if (!el) return;
    el.value = v;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    if (!inputOnly) el.dispatchEvent(new Event('change', { bubbles: true }));
  },
  // методы сцены и движка живут в соседних миксинах фазы 3; пока их нет —
  // панель обязана работать, а не падать
  _fs(name, arg) { if (typeof this[name] === 'function') return this[name](arg); },

  // ---- хранилище: сервер вместо localStorage (решение 11) ----
  // патч уходит на бэк не дожидаясь ответа (как звёзды избранного), а копия
  // ложится в state.settings — из неё читают load*-методы в этой же сессии
  _saveSettings(patch) {
    var self = this;
    this.setState({ settings: Object.assign({}, this.state.settings || {}, patch) });
    api.settingsSet(patch).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
  },
  // {list, def} — терпим и голый массив: настройки могли лечь до этой формы
  _profStore(key) {
    var raw = (this.state.settings || {})[key];
    if (Array.isArray(raw)) return { list: raw, def: '' };
    if (raw && typeof raw === 'object') return { list: Array.isArray(raw.list) ? raw.list : [], def: raw.def || '' };
    return { list: [], def: '' };
  },
  // def передаётся явно: setState асинхронен, и чтение this.state сразу после
  // него вернуло бы старое значение — удаление профиля воскрешало бы список
  // ПУСТОЙ СПИСОК ПОВЕРХ НЕПУСТОГО — ТОЛЬКО НАМЕРЕННО (Раунд 56).
  //
  // Пользователь: «куда мой профиль настроек делся, одного профиля нет, я хз».
  // Проверено по коду: дыра здесь. `saveDefProf` сохраняет ВЕСЬ список из
  // состояния, а состояние на старте пусто — настройки приезжают с бэка
  // позже. Любая запись до их приезда (отметить «по умолчанию», сохранить
  // профиль вида) клала `list: []` поверх сохранённого. Молча.
  //
  // Теперь пустой список поверх непустого проходит, ТОЛЬКО когда его просят
  // явно (`явно: true` — удаление последнего профиля). Во всех остальных
  // случаях отказываемся и пишем в журнал: потеря данных не должна быть
  // бесшумной, даже если это «всего лишь» профиль сцены.
  saveProfiles(list, def, явно) {
    var новый = list || [];
    var сохранённый = this._profStore('nl_fs_profiles').list || [];
    if (!новый.length && сохранённый.length && !явно) {
      журнал('профили сцены: отказ записать пустой список поверх ' + сохранённый.length +
             ' — состояние ещё не загружено');
      return;
    }
    this._saveSettings({ nl_fs_profiles: { list: новый, def: def === undefined ? (this.state.defProf || '') : (def || '') } });
  },
  saveDefProf(id) { this.saveProfiles(this.state.profiles || [], id || ''); },
  loadProfiles() { return this._profStore('nl_fs_profiles').list; },
  loadDefProf() { return this._profStore('nl_fs_profiles').def; },
  saveUiProfiles(list, def, явно) {
    var новый = list || [];
    var сохранённый = this._profStore('nl_ui_profiles').list || [];
    if (!новый.length && сохранённый.length && !явно) {
      журнал('профили вида: отказ записать пустой список поверх ' + сохранённый.length +
             ' — состояние ещё не загружено');
      return;
    }
    this._saveSettings({ nl_ui_profiles: { list: новый, def: def === undefined ? (this.state.uiDefProf || '') : (def || '') } });
  },
  saveUiDef(id) { this.saveUiProfiles(this.state.uiProfiles || [], id || ''); },
  loadUiProfiles() { return this._profStore('nl_ui_profiles').list; },
  loadUiDef() { return this._profStore('nl_ui_profiles').def; },
  // текущий вид: пишем весь cfg, дебаунсом. Ответ не ждём и state.settings не
  // трогаем — nl_view читается только при старте, а лишний setState на каждое
  // движение ползунка перерисовывал бы всё приложение
  saveViewSoon() {
    var self = this;
    clearTimeout(this._viewT);
    this._viewT = setTimeout(function () {
      self._viewT = null;
      api.settingsSet({ nl_view: self.state.cfg || {} })
        .catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
    }, VIEW_DEBOUNCE);
  },

  // ---- снятие ручек с DOM (механизм дизайна, сохранён как есть) ----
  engineControls() {
    var out = [], seen = {};
    var roots = [document.getElementById('fsSetPanel'), this._stage()];
    var line = document.getElementById('btnNext');
    if (line) roots.push(line.closest('div[style*="max-height"]') || line.parentElement.parentElement);
    roots.forEach(function (root) {
      if (!root) return;
      root.querySelectorAll('input[id], select[id]').forEach(function (el) {
        if (!el.id || seen[el.id] || this.PROF_SKIP_IDS[el.id] || el.type === 'file') return;
        seen[el.id] = 1; out.push(el);
      }, this);
    }, this);
    return out;
  },

  // ---- профили вида ----
  uiSnapshot() {
    var C = this.cfg(), out = {}, skip = this.UI_SKIP;
    Object.keys(C).forEach(function (k) {
      if (skip[k] || k.indexOf('fs') === 0) return;
      var v = C[k];
      if (v == null || typeof v === 'function' || typeof v === 'object') return;
      out[k] = v;
    });
    return out;
  },
  // по умолчанию может быть только один: повторный клик снимает отметку
  toggleUiDef(id) {
    var next = this.state.uiDefProf === id ? '' : id;
    this.saveUiDef(next);
    this.setState({ uiDefProf: next });
  },
  // вид применяем целиком: настройки сцены фристайла не трогаем, остальное заменяем,
  // иначе значения из прошлого профиля залипают
  applyUiProfile(p, done) {
    var keep = {}, cur = this.state.cfg || {}, self = this;
    Object.keys(cur).forEach(function (k) { if (self.UI_SKIP[k] || k.indexOf('fs') === 0) keep[k] = cur[k]; });
    this.setState({ uiProfId: p.id, cfg: Object.assign(keep, p.cfg), theme: p.theme || this.state.theme }, function () {
      self.applyTheme(); self.saveViewSoon(); if (done) done();
    });
  },
  // базовый вид: всё по умолчанию и без градиента у краёв
  blankUi(done) {
    var keep = {}, cur = this.state.cfg || {}, self = this;
    Object.keys(cur).forEach(function (k) { if (self.UI_SKIP[k] || k.indexOf('fs') === 0) keep[k] = cur[k]; });
    keep.fadeOn = 'нет';
    this.setState({ uiProfId: this.UI_BLANK_ID, cfg: keep }, function () {
      self.applyTheme(); self.saveViewSoon(); if (done) done();
    });
  },
  // вид поднимаем строго до сцены: сцена дёргает инпуты движка, а их обработчик тоже пишет
  // в настройки — если запустить одновременно, одна запись перетрёт другую
  bootUi(done) {
    var id = this.state.uiDefProf;
    var p = (this.state.uiProfiles || []).filter(function (x) { return x.id === id; })[0];
    if (p && id !== this.UI_BLANK_ID) { this.applyUiProfile(p, done); return; }
    // явный «пусто» — уважаем; отсутствие профиля по умолчанию — оставляем
    // восстановленный nl_view (см. шапку, п.3)
    if (id === this.UI_BLANK_ID) { this.blankUi(done); return; }
    if (done) done();
  },

  // ---- профили сцены ----
  toggleDefProf(id) {
    var next = this.state.defProf === id ? '' : id;
    this.saveDefProf(next);
    this.setState({ defProf: next });
  },
  // Один построитель для обоих списков профилей — сцены и вида. Различия сведены в spec:
  // имена ключей состояния и обработчики. Первая строка — встроенный «пусто»: точка отсчёта,
  // её нельзя переименовать, перезаписать или удалить.
  profileList(o) {
    var self = this, st = this.state;
    var ICON = 'appearance: none; background: none; border: none; padding: 2px 3px; display: flex; align-items: center; cursor: pointer; color: var(--muted-soft); opacity: var(--sh, 0);';
    var NOOP = function () {};
    var mk = function (id, name, x) {
      var on = st[o.sel] === id, def = st[o.def] === id, ed = !!(o.edit && st[o.edit] === id);
      return Object.assign({
        id: id, name: name, editing: ed, notEditing: !ed, canEdit: !!x.canEdit,
        nameTitle: x.canEdit ? 'Клик — загрузить · двойной клик — переименовать' : 'Клик — загрузить',
        rowStyle: 'display: flex; align-items: center; gap: 4px; border-radius: 3px; padding: 3px 5px;'
          + (x.first ? ' margin-bottom: 3px; border-bottom: 1px solid var(--border-subtle); padding-bottom: 6px;' : '')
          + ' background: ' + (on ? 'color-mix(in srgb, var(--ink) 8%, transparent)' : 'transparent') + ';',
        nameStyle: 'appearance: none; flex: 1; min-width: 0; background: none; border: none; padding: 3px 2px; font-family: inherit; font-size: 10.5px; text-align: left; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: ' + (on ? 'var(--ink)' : 'var(--muted)') + ';',
        iconStyle: x.canEdit ? ICON : 'display: none;',
        defFill: def ? 'currentColor' : 'none',
        defTitle: def ? 'Загружается при запуске · клик — снять' : 'Загружать при запуске',
        defStyle: 'appearance: none; background: none; border: none; padding: 2px 3px; display: flex; align-items: center; cursor: pointer; color: ' + (def ? 'var(--ink)' : 'var(--muted-soft)') + '; opacity: ' + (def ? '1' : 'var(--sh, 0)') + ';',
        onDefault: function (e) { e.stopPropagation(); o.toggleDef(id); },
        onRename: NOOP, onRenameKey: NOOP, startRename: NOOP, onUpdate: NOOP, onDrop: NOOP
      }, x.row);
    };
    return [mk(o.blankId, 'пусто', { first: true, row: { onLoad: o.onBlank } })]
      .concat((st[o.list] || []).map(function (p) {
        return mk(p.id, p.name, { canEdit: true, row: {
          onLoad: function () { o.onLoad(p); },
          onRename: function (e) { o.rename(p, String(e.target.value || '').trim() || p.name); },
          onRenameKey: function (e) { if (e.key === 'Enter' || e.key === 'Escape') e.target.blur(); },
          startRename: function () { var patch = {}; patch[o.edit] = p.id; self.setState(patch); },
          onUpdate: function () { o.onUpdate(p); },
          onDrop: function () { o.onDrop(p); }
        } });
      }));
  },

  // строки меню «профили сцены» (renderVals 3767..3786)
  fsProfRows() {
    var self = this, st = this.state;
    return this.profileList({
      sel: 'profId', def: 'defProf', list: 'profiles', edit: 'profEdit', blankId: this.BLANK_ID,
      toggleDef: function (id) { self.toggleDefProf(id); },
      onBlank: function () { self.blankScene(true); },
      onLoad: function (p) { self.setState({ profId: p.id }); self.applyProfile(p.data); },
      rename: function (p, nm) {
        var list = (self.state.profiles || []).map(function (x) { return x.id === p.id ? Object.assign({}, x, { name: nm }) : x; });
        self.saveProfiles(list); self.setState({ profiles: list, profEdit: '' });
      },
      onUpdate: function (p) {
        var list = (self.state.profiles || []).map(function (x) { return x.id === p.id ? { id: x.id, name: x.name, data: self.snapshotProfile() } : x; });
        self.saveProfiles(list); self.setState({ profiles: list, profId: p.id });
      },
      onDrop: function (p) {
        var list = (self.state.profiles || []).filter(function (x) { return x.id !== p.id; });
        // список и отметка «по умолчанию» уходят ОДНОЙ записью: два вызова
        // подряд второй раз прочитали бы ещё не обновлённый state
        var def = st.defProf === p.id ? '' : st.defProf;
        self.saveProfiles(list, def, true);   // явное удаление, пустой список законен
        self.setState({ profiles: list, profId: st.profId === p.id ? '' : st.profId, defProf: def });
      }
    });
  },
  // «＋ сохранить» в меню профилей сцены (renderVals 3759..3766)
  saveFsProfile() {
    var list = (this.state.profiles || []).slice();
    var max = list.reduce(function (m, x) { var n = parseInt(String(x.name).replace(/\D+/g, ''), 10); return isNaN(n) ? m : Math.max(m, n); }, 0);
    var id = 'p' + Date.now();
    list.push({ id: id, name: 'профиль ' + (max + 1), data: this.snapshotProfile() });
    this.saveProfiles(list);
    this.closePop({ profiles: list, profId: id });
  },

  // строки списка «профили вида» (renderVals 3973..3992) — их рисует панель
  // общих настроек редактора; методы живут здесь, чтобы оба списка были одним
  uiProfRows() {
    var self = this, st = this.state;
    return this.profileList({
      sel: 'uiProfId', def: 'uiDefProf', list: 'uiProfiles', edit: 'uiProfEdit', blankId: this.UI_BLANK_ID,
      toggleDef: function (id) { self.toggleUiDef(id); },
      onBlank: function () { self.blankUi(); },
      onLoad: function (p) { self.applyUiProfile(p); },
      rename: function (p, nm) {
        var list = (self.state.uiProfiles || []).map(function (x) { return x.id === p.id ? Object.assign({}, x, { name: nm }) : x; });
        self.saveUiProfiles(list); self.setState({ uiProfiles: list, uiProfEdit: '' });
      },
      onUpdate: function (p) {
        var list = (self.state.uiProfiles || []).map(function (x) { return x.id === p.id ? { id: x.id, name: x.name, cfg: self.uiSnapshot(), theme: self.state.theme } : x; });
        self.saveUiProfiles(list); self.setState({ uiProfiles: list, uiProfId: p.id });
      },
      onDrop: function (p) {
        var list = (self.state.uiProfiles || []).filter(function (x) { return x.id !== p.id; });
        var def = st.uiDefProf === p.id ? '' : st.uiDefProf;
        self.saveUiProfiles(list, def);
        self.setState({ uiProfiles: list, uiProfId: st.uiProfId === p.id ? '' : st.uiProfId, uiDefProf: def });
      }
    });
  },
  saveUiProfile() {
    var list = (this.state.uiProfiles || []).slice();
    var max = list.reduce(function (m, x) { var n = parseInt(String(x.name).replace(/\D+/g, ''), 10); return isNaN(n) ? m : Math.max(m, n); }, 0);
    var id = 'u' + Date.now();
    list.push({ id: id, name: 'вид ' + (max + 1), cfg: this.uiSnapshot(), theme: this.state.theme });
    this.saveUiProfiles(list);
    this.setState({ uiProfiles: list, uiProfId: id });
  },

  // ---- снимок и применение сцены ----
  snapshotProfile() {
    var self = this, eng = {}, stt = {};
    this.engineControls().forEach(function (el) { eng[el.id] = el.type === 'checkbox' ? el.checked : el.value; });
    Object.keys(this.state).forEach(function (k) {
      if (self.PROF_SKIP_STATE[k]) return;
      var v = self.state[k];
      if (typeof v === 'function' || v === undefined) return;
      stt[k] = v && typeof v === 'object' ? JSON.parse(JSON.stringify(v)) : v;
    });
    var cur = this.state.cfg || {}, cfgOut = {};
    Object.keys(cur).forEach(function (k) { if ((self.UI_SKIP[k] || k.indexOf('fs') === 0) && !self.PROF_SKIP_CFG[k]) cfgOut[k] = cur[k]; });
    return { eng: eng, stt: stt, preset: this.curPreset(), cfg: cfgOut, pal: this.state.pal || this.loadPal() };
  },
  // выбранный пресет — состояние движка. Дизайн читал его с активной строки
  // списка (#presetPanel .presetRow.current), потому что имя знал только
  // внешний скрипт. Наш движок отвечает объектом, а строки списка рисуются
  // лениво (455 пресетов держать в DOM всегда — дорого), поэтому спрашиваем
  // движок, а DOM остаётся подстраховкой
  curPreset() {
    var eng = this.fsEngine;
    if (eng && typeof eng.current === 'function') {
      var cur = eng.current();
      if (cur) return cur;
    }
    var el = document.querySelector('#presetPanel .presetRow.current .presetName, #presetPanel .presetRow.active .presetName');
    if (el) return el.textContent.trim();
    if (eng && typeof eng.recent === 'function') { var r = eng.recent() || []; return r[0] || ''; }
    return '';
  },
  // по той же причине выбор идёт методом движка, а не кликом по строке:
  // строки может не быть вовсе (панель закрыта, поиск, вкладка «избранное»)
  pickPreset(name) {
    if (!name) return;
    var eng = this.fsEngine;
    if (!eng || typeof eng.pick !== 'function') return;
    eng.pick(this.fsPresetName ? this.fsPresetName(name) : name);
  },
  applyEng(eng) {
    var self = this;
    Object.keys(eng || {}).forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      // у флажка в профиле лежит «отмечен да/нет», а не значение поля: у него value всегда "on",
      // поэтому запись через value молча не срабатывала — все тумблеры сцены не применялись
      if (el.type === 'checkbox') {
        var want = eng[id] === true || eng[id] === 'true';
        if (el.checked === want) return;
        el.checked = want;
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return;
      }
      if (String(el.value) === String(eng[id])) return;
      self.poke(el, eng[id]);
    });
  },
  // пустая сцена: чёрный фон, белый текст, ни обработки, ни визуализации, ни пресета.
  // ручки движка возвращаем к их же исходным значениям, свои — к FS_DEF (пустой объект fsv).
  // Визуализацию НЕ гасим: движок собирает библиотеку пресетов только при включённой
  // визуализации в момент запуска, и выключение схлопывает это окно навсегда.
  // Пустая сцена — плотность подложки 0 при живом визуализаторе: экран чёрный, библиотека цела.
  blankScene(engineReady) {
    var self = this;
    this.engineControls().forEach(function (el) {
      if (el.type === 'checkbox') { if (el.checked !== el.defaultChecked) { el.checked = el.defaultChecked; el.dispatchEvent(new Event('change', { bubbles: true })); } return; }
      var d = el.defaultValue;
      if (d == null || d === '' || el.value === d) return;
      self.poke(el, d);
    });
    var blank = this.BLANK_ENG;
    Object.keys(blank).forEach(function (id) {
      var el = document.getElementById(id);
      if (!el || String(el.value) === String(blank[id])) return;
      self.poke(el, blank[id]);
    });
    this._live = {};
    this._fs('camStop', true);
    var patch = {
      fsv: {}, cfg: Object.assign({}, this.state.cfg || {}, { fsBcOpacity: 0 }), live: {}, camOn: false,
      autoOn: false, bcAutoOn: false, acMode: 'выкл', glowColor: '',
      textAber: false, postAber: false, aspect: '', profId: this.BLANK_ID, bcOn: true
    };
    this.setState(patch, function () {
      self._fs('pushScene'); self._fs('pushFilters'); self._fs('fitStage'); self._fs('fitLine');
      self.applyTheme(); self._fs('paintBand'); self._fs('bandLater');
      self.syncPanelColor();
      self._fs('bcAutoLoop');
      self.saveViewSoon();
    });
  },
  applyProfile(p) {
    if (!p) return;
    var self = this;
    // пустая сцена ставится с задержкой после загрузки движка: если профиль подняли раньше,
    // отложенный сброс прилетал следом и стирал его — снаружи это «профили не работают»
    clearTimeout(this._blankT); this._blankT = null;
    if (this._fsPending === 'blank') this._fsPending = null;
    this.applyEng(p.eng);
    var live = {}, FSLIVE = this.FSLIVE || {};
    Object.keys(FSLIVE).forEach(function (id) { if (p.eng && p.eng[id] != null) live[FSLIVE[id]] = parseFloat(p.eng[id]); });
    this._live = Object.assign({}, this._live, live);
    var stt = {};
    Object.keys(p.stt || {}).forEach(function (k) { if (!self.PROF_SKIP_STATE[k]) stt[k] = p.stt[k]; });
    // из профиля сцены берём только её ручки: настройки вида (тема, шрифт, стекло, градиент) —
    // забота профилей вида, иначе один профиль стирает другой.
    // сначала снимаем все ключи сцены, иначе состояние пустой сцены (например нулевая плотность)
    // протекает в следующий профиль: в нём лежат только те ключи, что отличались от исходных
    var nextCfg = {};
    Object.keys(this.state.cfg || {}).forEach(function (k) {
      if (!(self.UI_SKIP[k] || k.indexOf('fs') === 0) || self.PROF_SKIP_CFG[k]) nextCfg[k] = self.state.cfg[k];
    });
    Object.keys(p.cfg || {}).forEach(function (k) { if ((self.UI_SKIP[k] || k.indexOf('fs') === 0) && !self.PROF_SKIP_CFG[k]) nextCfg[k] = p.cfg[k]; });
    this.setState(Object.assign({}, stt, { pal: p.pal || this.state.pal, cfg: nextCfg, live: Object.assign({}, this._live), openPill: '' }), function () {
      self._fs('pushScene'); self._fs('fitStage'); self._fs('fitLine'); self._fs('autoColorLoop'); self._fs('bcAutoLoop');
      var s = p.stt || {};
      // камеру поднимаем только если профиль её включал — запрос доступа не должен всплывать сам
      if (s.camOn && self.state.tab === 'fs') self._fs('camStart'); else self._fs('camStop', true);
      self._fs('fsAutoLoop');
      self.applyTheme();
      self._fs('paintBand');
      self._fs('bandLater');
      self.syncPanelColor();
      self.saveViewSoon();
      if (p.preset) self.whenEngine(function () { self.pickPreset(p.preset); });
    });
  },

  // ---- подъём при старте ----
  // профиль по умолчанию поднимаем сразу — ждать движок нельзя, иначе видно пустую сцену перед ним
  bootProfile() {
    // Вход во фристайл может случиться РАНЬШЕ ответа /api/settings (медленная
    // сеть, таймаут): тогда профилей ещё нет, и «поднять» нечего. Отмечаться
    // поднятым в этот момент нельзя — иначе профиль по умолчанию не применится
    // уже никогда. bootFsSettings поднимет сцену сам, когда настройки доедут
    if (!this._fsSettingsReady || this._fsBooted) return;
    this._fsBooted = true;
    var id = this.state.defProf;
    var p = (this.state.profiles || []).filter(function (x) { return x.id === id; })[0];
    // явный «пусто» уважаем; ОТСУТСТВИЕ профиля по умолчанию — нет (то же
    // расхождение с дизайном, что у bootUi, п.3 шапки). Дизайн в этом случае
    // звал blankScene, а она гасит подложку визуализатора (fsBcOpacity 0):
    // на чистой машине первый же вход во фристайл давал чёрный экран, и
    // восстановленный nl_view затирался. Без профиля сцена остаётся такой,
    // какой её вернул сервер
    if (id === this.BLANK_ID) { this.blankScene(false); this._fsPending = 'blank'; this.topUpProfile(); return; }
    if (!p) {
      // Профиля нет — сцену не трогаем и плашку НЕ красим: выключенная плашка
      // и есть дизайновый дефолт (слой стоит на `var(--panel, transparent)`),
      // первый вход во фристайл обязан показывать чистый визуализатор.
      // Сводим только выбор кружка и значение пипетки, иначе первый клик по
      // нулевому кружку считается повторным и открывает системный спектр.
      this.syncPanelColor(false);
      return;
    }
    this.setState({ profId: p.id });
    this._fsPending = p.data;
    this.applyProfile(p.data);
    this.topUpProfile();
  },
  // ручки движка и пресет появляются только после его загрузки, а она идёт при первом входе
  // во фристайл. Поэтому добор запускаем и на старте, и на каждом входе — пока не сработает
  topUpProfile() {
    var self = this, pend = this._fsPending;
    if (!pend) return;
    this.whenEngine(function () {
      if (!self._fsPending) return;
      self._fsPending = null;
      if (pend === 'blank') { self._blankT = setTimeout(function () { self._blankT = null; self.blankScene(true); }, 400); return; }
      self.applyEng(pend.eng);
      self.pickPreset(pend.preset);
      self._fs('bandLater');
    });
  },
  // Готовность движка. Дизайн опрашивал DOM (появилась ли строка в #presetPanel)
  // раз в 120 мс до 48 секунд — единственный способ дождаться внешнего скрипта.
  // Наш движок сам сообщает о себе: очередь разбирает loadEngine (methods.fsglue.js).
  // Если во фристайл так и не зашли, отложенный вызов честно не случится —
  // ровно как раньше истекал опрос
  whenEngine(fn) {
    if (this.fsEngine) { fn(); return; }
    (this._engineWait || (this._engineWait = [])).push(fn);
  },
  // единственная точка входа для интегратора: разложить настройки сервера по
  // состоянию, поднять вид, поднять сцену. Зовётся в конце boot() —
  // state.settings к этому моменту уже положен
  bootFsSettings(done) {
    var self = this;
    var fsp = this._profStore('nl_fs_profiles'), uip = this._profStore('nl_ui_profiles');
    var view = (this.state.settings || {}).nl_view;
    var patch = {
      profiles: fsp.list, defProf: fsp.def,
      uiProfiles: uip.list, uiDefProf: uip.def,
      pal: this.loadPal()
    };
    // вид переживает перезапуск (nl_view); ключи сцены из cfg сохраняем — их
    // поднимет профиль сцены
    if (view && typeof view === 'object') patch.cfg = Object.assign({}, this.state.cfg || {}, view);
    this._fsSettingsReady = true;
    this.setState(patch, function () {
      // движок мог собраться раньше настроек (быстрый клик по «freestyle» на
      // медленной сети) — тогда он живёт с пустым избранным; отдаём ему
      // восстановленное молча, без обратных колбэков
      self._fs('fsHydrateEngine');
      self.bootUi(function () { self.bootProfile(); if (done) done(); });
    });
  },

  // ---- палитра ----
  loadPal() {
    var saved = (this.state.settings || {}).nl_palette;
    var pal = { panel: this.PAL_DEF.panel.slice(), ink: this.PAL_DEF.ink.slice(), glow: this.PAL_DEF.glow.slice() };
    if (saved) ['panel', 'ink', 'glow'].forEach(function (k) {
      if (Array.isArray(saved[k])) saved[k].forEach(function (col, i) { if (i < 6 && /^#[0-9a-f]{6}$/i.test(col || '')) pal[k][i] = col; });
    });
    return pal;
  },
  savePal(pal) { this._saveSettings({ nl_palette: pal }); },
  palInput(kind) { return document.getElementById(kind === 'panel' ? 'panelColorPicker' : (kind === 'glow' ? 'glowColorPicker' : 'inkColor')); },
  // цвет отдаём через инпут движка: он и красит сцену, и обновляет свои переменные
  applyPal(kind, hex, smooth) {
    if (kind === 'panel') {
      var cl = document.querySelector('.colorLayer'), stage = this._stage();
      var ease = this.fsv ? this.fsv('acEase') : 0, mode = this.state.acMode || 'выкл';
      var span = mode === 'звук' ? 260 : (this.acPeriod ? this.acPeriod() : 0);
      // перелив во весь интервал — только у авто-перехода; выбор кружка срабатывает сразу
      var dur = smooth && ease > 0 ? Math.round(span * ease / 100) : 0;
      var tr = dur ? '--panel ' + dur + 'ms linear, background-color ' + dur + 'ms linear' : 'none';
      if (cl) cl.style.transition = tr;
      if (stage) { stage.style.transition = tr; stage.style.setProperty('--panel', hex); }
    }
    if (kind === 'glow') this.setState({ glowColor: hex });
    var el = this.palInput(kind);
    if (!el) return;
    this.poke(el, hex);
  },
  // Цвет плашки живёт в двух местах: в состоянии (какой кружок выбран) и в переменной сцены.
  // Если их не свести, первый клик по выбранному кружку считается повторным и открывает
  // системный спектр вместо смены цвета — палитра выглядит неработающей.
  // paint=false — свести ТОЛЬКО выбор и значение пипетки, не крася сцену.
  // Живая проверка 2026-08-01: на чистом старте (профиля по умолчанию нет)
  // покраска включала плашку #2436e0 поверх визуализатора, и первый вход во
  // фристайл встречал сплошной синевой вместо картинки. В дизайне на этом
  // пути syncPanelColor не зовётся вовсе: --panel не задан, а сам слой стоит
  // на `var(--panel, transparent)` — то есть выключенная плашка и есть дефолт.
  // Но свести выбор кружка всё равно надо, иначе первый клик по нулевому
  // кружку считается повторным и открывает системный спектр.
  syncPanelColor(paint) {
    var pal = this.state.pal || this.loadPal();
    var sel = (this.state.palSel || {}).panel;
    var hex = pal.panel[sel == null ? 0 : sel] || pal.panel[0];
    var stage = this._stage();
    if (!stage || !hex) return;
    if (sel == null) { var next = Object.assign({}, this.state.palSel); next.panel = 0; this.setState({ palSel: next }); }
    if (paint !== false) stage.style.setProperty('--panel', hex);
    var el = this.palInput('panel');
    if (el && el.value !== hex) el.value = hex;
  },
  // первый клик — выбор, повторный по выбранному — нативный спектр
  pickPal(kind, i) {
    var st = this.state, sel = (st.palSel || {})[kind];
    var pal = st.pal || this.loadPal();
    if (sel === i) {
      var el = this.palInput(kind);
      if (el) { if (el.showPicker) { try { el.showPicker(); } catch (e) { el.click(); } } else el.click(); }
      return;
    }
    var nextSel = Object.assign({}, st.palSel); nextSel[kind] = i;
    this.setState({ palSel: nextSel });
    this.applyPal(kind, pal[kind][i]);
  },
  // выбранный из спектра цвет остаётся в своём кружке
  rememberPal(kind, hex) {
    var st = this.state, i = (st.palSel || {})[kind];
    if (i == null) return;
    var src = st.pal || this.loadPal();
    var pal = { panel: src.panel.slice(), ink: src.ink.slice(), glow: src.glow.slice() };
    if (pal[kind][i] === hex) return;
    pal[kind][i] = hex;
    this.savePal(pal);
    this.setState({ pal: pal });
  },
};

// Ключи модели генерации подмешиваются в запрет ИЗ ОДНОГО МЕСТА
// (methods.shelves.js: КЛЮЧИ_МОДЕЛИ). Ручной список здесь дважды отставал от
// состояния: сначала пропустил chain/params/threshold — и на диске пользователя
// осел «профиль 1» с чужой цепочкой и полями, удалёнными двумя раундами
// раньше; потом, в тот же день, пропустил все десять ключей трёх новых полок.
// Теперь добавляющий ключ модели правит одно место, и запрет обновляется сам.
КЛЮЧИ_МОДЕЛИ.forEach(function (k) { fsProfileMethods.PROF_SKIP_STATE[k] = 1; });
