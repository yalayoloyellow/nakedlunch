// Методы документа из дизайна «Editor First» (project-notes/mockups/design-v2/
// Editor First.dc.html, строки 1519..2113 и 3229..3262) — дословный перенос в
// миксин: интегратор делает Object.assign(Nakedlunch.prototype, docMethods).
// Отличия от дизайна — только решения прожарки (PLAN.md):
//   1) WORD_POPUP=true (фаза 2) — попап по слову живёт на /api/word/suggest:
//      fetchSuggest с кэшем слово+вкладка, скелет-плашки на время похода;
//   2) scheme(): рифмо-ключ ОДИН — из словаря ударений по тексту строки (Раунд 56);
//   3) toggleFavRow/dropFav/bulk('fav'): звёзды живут в corpus.json — api.fav* без ожидания;
//   5) markSaved: автосохранение листа на бэк через api.sheetsWrite.
// Моки дизайна (STANZAS/SYN/ANT/RHYME/POOL/allLines/buildSong/vocab/score/
// suggestList) не переносятся: popList здесь свой, поверх живого бэка.
// Генерация (genStanza/runPipe/stepRun/
// rowsFromVariant) и листы (insertAt/renameSheet/openSheet…) приходят своими
// миксинами — здесь на них только вызовы.

import * as api from './api.js';
import { ico, ICO_BTN } from './icons.js';

// решение прожарки 9: фаза 2 — попап по слову включён, данные из /api/word/suggest.
// Ворота качества словарных вкладок живут дальше: «антонимы» прячет thesaurus
// из /api/state (см. render.doc), мусорная вкладка скрывается, не фейкуется
export const WORD_POPUP = true;

export const docMethods = {
  // «// текст» — метка секции; текст живёт только в DOM, React в него не лезет
  rowText(row) { return row.type === 'role' ? '#'.repeat(row.level || 2) + ' ' + row.text : row.text; },
  // ЧТО ВИДНО В СТРОКЕ (Раунд 56). Решётки заголовка — разметка, а не текст:
  // показываем их только в той строке, где стоит каретка, как в Obsidian.
  // Требование (2026-08-05): markdown-разметка со скрытием спецсимволов..
  //
  // Правило узкое СОЗНАТЕЛЬНО — только заголовки. Прятать разметку жирного и
  // курсива внутри строки значит считать смещения каретки по каждому куску, а
  // это то место, где самодельные редакторы на contentEditable и умирают.
  // Заголовки живут отдельной строкой целиком, поэтому смещение здесь ровно
  // одно и считается точно (см. watchCaretRow).
  rowDisplay(row, i) {
    if (row.type !== 'role') return row.text;
    return i === this._activeRow ? this.rowText(row) : row.text;
  },
  // Длина совпадающего НАЧАЛА рифмо-ключа — зеркало core/filters.py:
  // _rhyme_prefix_len. 0 = ключи обязаны совпасть целиком.
  rhymePrefixLen(precision) {
    var p = parseFloat(precision);
    if (isNaN(p) || p <= 0) return 0;
    if (p <= 0.34) return 3;
    if (p <= 0.67) return 2;
    return 1;
  },

  // Последнее слово строки — зеркало core/filters.py: _last_word. Одинаковое
  // последнее слово это НЕ рифма, а повтор, и ядро его исключает.
  lastWord(text) {
    var w = String(text || '').trim().split(/\s+/);
    return (w[w.length - 1] || '').replace(/^[.,!?:;"'()»«—-]+|[.,!?:;"'()»«—-]+$/g, '').toLowerCase();
  },

  // Живая схема: буква рифмовки внутри секции, номер — тоже внутри секции.
  //
  // ПОЧИНКА Раунда 52. Здесь стояло ТОЧНОЕ равенство ключей, а ядро рифмует
  // по совпадающему НАЧАЛУ ключа, и длина зависит от «Точности рифм» (при
  // дефолтных 0.25 — три знака). То есть гутер был строже генератора: две
  // строки, которые прогон поставил в одну рифмо-группу, получали РАЗНЫЕ
  // буквы — «а б» там, где машина считает «а а». Смотрит пользователь именно на
  // эти буквы, и они врали о том, что он только что сгенерировал.
  //
  // Точность берём тем же резолвером, что и всё остальное (звено → референс →
  // панель): «рифма» в приложении значит ровно то, что значит сейчас.
  // БУКВА РИФМОВКИ УБРАНА (Раунд 56).
  //
  // Пользователь, глядя на «а а а а» у власти / мотылька / Каракалла / храма:
  // «как здесь аааа может быть, это кал… мб легче убрать вообще этот
  // спецсимвол и у генеративных, и у моих? он не нужен по сути, если не может
  // быть корректным».
  //
  // Честно: механизм БЫЛ корректен — замер на его же строках дал 5 из 6 рифм
  // при нуле ложных на строгом ярусе. Врал не он, а ЯРУС: «Точность рифм» у
  // пользователя стояла на максимуме, а максимум этой шкалы — одна ударная
  // гласная, то есть ассонанс. Но это его текст и его экран, а решение об
  // удалении в этом проекте не обсуждается.
  //
  // Ушла ТОЛЬКО буква. Номер строки внутри секции остался: он ни от какой
  // рифмовки не зависит и врать не может. Вместе с буквой ушли добор ключей с
  // бэка (dobratRk), кэш `_rk` и вся возня с `rk` в схеме — они существовали
  // ради неё одной.
  scheme() {
    var doc = this.cur(), out = [], no = 0;
    for (var i = 0; i < doc.length; i++) {
      var r = doc[i];
      if (r.type === 'role') { out.push(null); no = 0; continue; }
      if (!String(r.text || '').trim()) { out.push(null); continue; }
      no++;
      out.push({ no: no });
    }
    return out;
  },
  sectionOf(i) { var doc = this.cur(), s = 0; for (var k = 0; k <= i && k < doc.length; k++) if (doc[k].type === 'role') s++; return s; },
  moveRow(i, dir) {
    var prev = this.cur(), j = i + dir;
    this._restore = { row: j, off: 0 };
    if (j < 0 || j >= prev.length) return;
    var doc = prev.slice(), tmp = doc[i];
    doc[i] = doc[j]; doc[j] = tmp;
    this._focus = j; this._focusAt = null;
    this.push(doc, prev);
  },
  // выделение диапазона строк по гутеру
  markRow(i, shift) {
    var st = this.state, doc = this.cur();
    if (shift && st.markAnchor >= 0) {
      var a = Math.min(st.markAnchor, i), b = Math.max(st.markAnchor, i), m = {};
      for (var k = a; k <= b; k++) if (doc[k]) m[k] = 1;
      this.setState({ marks: m });
    } else {
      var mm = Object.assign({}, st.marks);
      if (mm[i]) delete mm[i]; else mm[i] = 1;
      this.setState({ marks: mm, markAnchor: i });
    }
  },
  markedIdx() { return Object.keys(this.state.marks || {}).map(Number).sort(function (a, b) { return a - b; }); },
  bulk(op) {
    var idx = this.markedIdx(); if (!idx.length) return;
    var prev = this.cur(), doc = prev.slice(), self = this;
    if (op === 'role') {
      var allRoles = idx.every(function (i) { return doc[i] && doc[i].type === 'role'; });
      idx.forEach(function (i) {
        var r = doc[i]; if (!r) return;
        doc[i] = allRoles ? { type: 'line', text: r.text, letter: 'а', src: 'я' } : { type: 'role', text: r.text };
      });
    } else if (op === 'fav') {
      var favs = (this.state.favs || []).slice();
      idx.forEach(function (i) {
        var r = doc[i]; if (!r || r.type !== 'line' || !r.text) return;
        doc[i] = Object.assign({}, r, { fav: true });
        if (!favs.some(function (f) { return f.t === r.text; })) {
          favs.unshift({ t: r.text });
          // как в toggleFavRow (решение 3): звёзды живут в corpus.json, пишем не дожидаясь
          api.favAdd({ text: r.text }).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
        }
      });
      this.setState({ favs: favs, marks: {} });
      this.push(doc, prev);
      return;
    } else if (op === 'del') {
      for (var k2 = idx.length - 1; k2 >= 0; k2--) doc.splice(idx[k2], 1);
      if (!doc.length) doc.push({ type: 'line', text: '', letter: 'а', src: 'я' });
    }
    this.setState({ marks: {} });
    this.push(doc, prev);
  },
  parseRow(row, raw) {
    var m = String(raw).match(/^\s*(#{1,6})\s+(.*)$/) || String(raw).match(/^\s*\/\/\s?()(.*)$/);
    if (m) return { type: 'role', text: m[2], level: m[1] === '//' || !m[1] ? 2 : m[1].length };
    return { type: 'line', text: String(raw).replace(/^\s+/, ''), letter: row.letter || 'а', src: 'я' };
  },
  // ---- единое редактируемое поле ----
  // в дизайне linesRef — стрелочное поле класса; миксин полей не объявляет,
  // поэтому render.doc держит один связанный колбэк (c._linesRefCb)
  linesRef(el) { this._lines = el; if (el && !el.firstChild) this._rowSig = null; if (el) this.watchCaretRow(); },
  // Решётки заголовка появляются и исчезают ПО ДВИЖЕНИЮ КАРЕТКИ, а оно не
  // проходит через состояние: стрелки и клик мимо React не двигают ничего, что
  // вызвало бы перерисовку. Поэтому свой слушатель `selectionchange` — он
  // срабатывает на любое перемещение каретки, включая клавиатурное.
  //
  // Работа делается ТОЛЬКО при смене СТРОКИ, а не на каждое движение внутри
  // неё: иначе перерисовка шла бы на каждую нажатую стрелку.
  watchCaretRow() {
    if (this._caretWatch || typeof document === 'undefined') return;
    var self = this;
    this._caretWatch = function () {
      // КАРЕТКА В САМОМ КОНТЕЙНЕРЕ — ВСЕГДА, А НЕ ТОЛЬКО ПО КЛИКУ (Раунд 57).
      //
      // `caretRescue` звался ровно из одного места — из обработчика клика. Но
      // в контейнер каретка попадает не только кликом: её туда роняет и
      // перерисовка строк, и Escape, и вставка блока генерации. Тогда браузер
      // рисует её в начале координат контейнера — левее текста и выше первой
      // строки, у самого края экрана. по отчёту каретка появлялась у левого верхнего края экрана., и раньше говорил про «по две, по три, по четыре».
      //
      // Спасаем на КАЖДОЕ перемещение выделения. Зацикливания нет: после
      // возврата в поле строки `caretСпасти` видит нормальную каретку и молчит.
      if (self.caretСпасти()) return;
      var c = self.caretSnap();
      var r = c ? c.row : -1;
      if (r === self._activeRow) return;
      self._activeRow = r;
      var doc = self.cur(), стр = r >= 0 ? doc[r] : null;
      self.renderRows();
      // Вошли в заголовок — перед текстом появились решётки, и текстовый узел
      // заменён целиком. Каретку возвращаем со сдвигом ровно на их длину:
      // «## » это (уровень + 1) символ. Без этого она прыгала бы в начало.
      if (стр && стр.type === 'role' && c) {
        var f = self._lines && self._lines.querySelectorAll('[data-idx]')[r];
        if (f) self.setCaret(f, c.off + (стр.level || 2) + 1);
      }
    };
    document.addEventListener('selectionchange', this._caretWatch);
  },
  rowEls() { return this._lines ? Array.prototype.slice.call(this._lines.children) : []; },
  domText(el) {
    var t = '';
    for (var n = el.firstChild; n; n = n.nextSibling) {
      if (n.nodeType === 3) t += n.nodeValue;
      else if (n.nodeType === 1 && !n.hasAttribute('data-nc')) t += n.innerText != null ? n.textContent : '';
    }
    return t.replace(/ /g, ' ').replace(/\n+$/, '');
  },
  // текст выделения собираем из модели, а не из DOM — подписи кнопок в буфер не попадают
  selectionText() {
    try {
      var s = getSelection();
      if (!s || !s.rangeCount || s.isCollapsed || !this._lines) return null;
      var r = s.getRangeAt(0);
      if (!this._lines.contains(r.commonAncestorContainer) && r.commonAncestorContainer !== this._lines) return null;
      var els = this.rowEls(), doc = this.cur(), parts = [], self = this;
      for (var k = 0; k < els.length; k++) {
        var f = els[k].querySelector('[data-idx]'); if (!f) continue;
        var rr = document.createRange(); rr.selectNodeContents(f);
        if (r.compareBoundaryPoints(Range.END_TO_START, rr) > 0 || r.compareBoundaryPoints(Range.START_TO_END, rr) < 0) continue;
        var full = doc[k] ? self.rowText(doc[k]) : self.domText(f);
        var a = 0, b = full.length;
        if (r.startContainer && f.contains(r.startContainer)) { var q = r.cloneRange(); q.selectNodeContents(f); q.setEnd(r.startContainer, r.startOffset); a = q.toString().length; }
        if (r.endContainer && f.contains(r.endContainer)) { var q2 = r.cloneRange(); q2.selectNodeContents(f); q2.setEnd(r.endContainer, r.endOffset); b = q2.toString().length; }
        parts.push(full.slice(a, b));
      }
      return parts.length ? parts.join('\n') : null;
    } catch (e) { return null; }
  },
  caretSnap() {
    try {
      var s = getSelection(); if (!s || !s.rangeCount || !this._lines) return null;
      var fields = Array.prototype.slice.call(this._lines.querySelectorAll('[data-idx]'));
      for (var k = 0; k < fields.length; k++) {
        if (!fields[k].contains(s.focusNode) && fields[k] !== s.focusNode) continue;
        var r = s.getRangeAt(0).cloneRange();
        r.selectNodeContents(fields[k]); r.setEnd(s.focusNode, s.focusOffset);
        return { row: k, off: r.toString().length };
      }
    } catch (e) {}
    return null;
  },
  restoreCaret() {
    var c = this._restore; if (!c) return;
    this._restore = null;
    var els = this.rowEls(), el = els[Math.max(0, Math.min(c.row, els.length - 1))];
    if (!el) return;
    var field = el.querySelector('[data-idx]') || el;
    var node = field.firstChild;
    try {
      var r = document.createRange();
      if (node && node.nodeType === 3) r.setStart(node, Math.max(0, Math.min(c.off, node.length)));
      else { r.selectNodeContents(field); r.collapse(false); }
      r.collapse(true);
      var s = getSelection(); s.removeAllRanges(); s.addRange(r);
    } catch (e) {}
  },
  // строки рисуем сами: React не должен трогать contenteditable-поддерево
  el(tag, style, attrs) {
    var n = document.createElement(tag);
    if (style) n.setAttribute('style', style);
    if (attrs) for (var k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  },
  renderRows() {
    var host = this._lines; if (!host) return;
    // ВО ФРИСТАЙЛЕ ДОКУМЕНТ НЕ ПЕРЕСТРАИВАЕМ (Раунд 56). Его не видно, а
    // перестройка — это снос и сборка ВСЕХ строк с кнопками и слушателями:
    // на листе пользователя их сто девятнадцать. Каждая сгенерированная строфа
    // меняет документ, то есть каждая смена текста во фристайле роняла кадры
    // ровно там, где он на это и жаловался. Вернётся в редактор — соберём.
    if (this.state.tab === 'fs') { this._rowSig = null; return; }
    var st = this.state, doc = this.cur(), sch = this.scheme(), marks = st.marks || {}, self = this;
    var sig = doc.map(function (r, i) {
      return r.type + '|' + (r.src || '') + '|' + (marks[i] ? 1 : 0) + '|' + (sch[i] ? sch[i].no : '') + '|' + (r.fav ? 1 : 0);
    }).join('~') + '#' + st.selAll + '#' + this.docCss();
    // Заполнитель на месте будущей строфы (2026-08-02, требование: видеть, что генерация идёт, прямо в той строке, куда она идёт.). Позиция берётся из insertAt() ПРИ РЕНДЕРЕ, а не
    // запоминается на старте: каретку можно увести за те секунды, что идёт
    // прогон, — и заполнитель должен уехать вместе с ней, а не врать.
    // В подпись сигнатуры идёт только факт и место, БЕЗ секунд: иначе
    // контейнер строк перестраивался бы раз в секунду. Секунды дописывает
    // тикер прямо в узел (см. startGenClock).
    // insertAt() отдаёт {at, съесть} — раньше отдавал число (Раунд 57). Здесь
    // сравнение шло с числом, объект не совпадал ни с одним индексом, и строка
    // «генерация…» пропала совсем. Замечание: без надписи «генерация» состояние перестало читаться..
    // Замороженное место прогона (methods.gen: _genКуда). Раньше здесь стоял
    // ЖИВОЙ insertAt() — заполнитель нарочно бегал за кареткой и потому
    // переезжал на другую строку прямо во время генерации.
    var куда = st.genBusy ? (this._genКуда || null) : null;
    var genAt = куда ? куда.at : -1;
    sig += '#gen' + genAt;
    if (sig !== this._rowSig || !host.querySelector('[data-idx]')) {
      this._rowSig = sig;
      while (host.firstChild) host.removeChild(host.firstChild);
      // ЗАПОЛНИТЕЛЬ ВМЕСТО СЪЕДАЕМОЙ СТРОКИ, А НЕ В ДОБАВОК (Раунд 57).
      //
      // Он рисовался ДОПОЛНИТЕЛЬНОЙ строкой перед той, на которой стоит
      // каретка. А каретка обычно стоит на пустой — и на экране оказывались
      // обе: пустая строка и заполнитель под ней, двойная высота. После
      // генерации пустую съедал блок, и всё вставало ровно; так это и описано: отступы возникали при начале генерации, после неё всё было
      // нормально..
      //
      // Раз место вставки заморожено вместе с решением «съесть пустую»
      // (`_genКуда`), заполнитель просто занимает её место — ровно как займёт
      // будущий блок. Ни одного лишнего пикселя ни до, ни после.
      var съест = куда && куда.съесть ? куда.at : -1;
      doc.forEach(function (r, i) {
        if (i === genAt) host.appendChild(self.genRowNode());
        if (i === съест) return;
        host.appendChild(self.rowNode(r, i, sch[i], marks[i]));
      });
      if (genAt >= doc.length) host.appendChild(this.genRowNode());
    }
    // текст всегда синхронизируем без перестройки. Выборка по [data-idx], а
    // не по позиции ребёнка: заполнитель — лишний узел, и позиционный индекс
    // после него разъехался бы со строками документа.
    var fields = host.querySelectorAll('[data-idx]');
    doc.forEach(function (r, i) {
      var f = fields[i];
      if (!f) return;
      var want = self.rowDisplay(r, i);
      if (self.domText(f) !== want) f.textContent = want;
    });
  },
  // строка-заполнитель: та же сетка, что у обычной строки (номер · текст),
  // пульсация — в CSS (nlGenPulse, style.js)
  genRowNode() {
    var row = this.el('div', 'display: flex; align-items: baseline; gap: 10px; padding: 1px 0;');
    row.setAttribute('data-genrow', '1');
    // Ярлык молчит, как у пустой строки: номера у ещё не существующей строки
    // нет, а пульсирующую точку пользователь отверг. Живость даёт сама строка —
    // [data-genrow] пульсирует целиком (style.js, nlGenPulse).
    var num = this.el('span', 'font-size: 9px; color: var(--muted-soft); width: 7ch; flex-shrink: 0;');
    var txt = this.el('span', 'font-size: inherit; color: var(--muted); letter-spacing: 0.04em;');
    txt.id = 'nlGenSecs';
    txt.textContent = (this.state.genStatus || 'генерация…');
    row.appendChild(num);
    row.appendChild(txt);
    return row;
  },
  docCss() {
    var C = this.cfg(), size = Math.max(11, Math.min(40, parseFloat(C.textSize) || 15));
    var fam = C.docFont && C.docFont !== 'как интерфейс' ? "'" + C.docFont + "', ui-monospace, monospace" : '';
    return size + '|' + (parseFloat(C.lineGap) || 1.5) + '|' + fam;
  },
  rowNode(r, i, s, marked) {
    var self = this, isRole = r.type === 'role', mine = r.src === 'я';
    var sel = (this.state.selAll || marked) ? 'color-mix(in srgb, var(--ink) 14%, transparent)' : 'transparent';
    var row = this.el('div', 'display: flex; align-items: baseline; gap: 10px; border-radius: 3px; background: ' + sel + '; padding: ' + (isRole ? '16px 0 5px' : '1px 0') + ';');
    row._btns = [];
    var dim = function (on) { row._btns.forEach(function (b) { b.style.opacity = b._active ? '1' : (on ? b._hov : b._rest); }); };
    row.addEventListener('mouseenter', function () { dim(true); });
    row.addEventListener('mouseleave', function () { dim(false); });

    var gutBase = 'display: inline-block; flex-shrink: 0; width: 7ch; white-space: nowrap; font-size: 9px; user-select: none; cursor: pointer; appearance: none; background: none; border: none; padding: 0; text-align: left; font-family: inherit; transition: opacity 0.12s var(--ease); ';
    var gut = this.el('button', gutBase + (isRole
      ? 'color: ' + (marked ? 'var(--ink)' : 'var(--muted-soft)') + '; opacity: ' + (marked ? '1' : '0') + ';'
      : 'font-variant-numeric: tabular-nums; overflow: hidden; color: ' + (marked || mine ? 'var(--ink)' : 'inherit') + '; opacity: ' + (marked ? '1' : (mine ? '0.75' : '0.45')) + ';'),
      { contenteditable: 'false', 'data-nc': '1', tabindex: '-1' });
    // Пустая строка не получает ни номера, ни буквы, ни источника: `scheme`
    // вернул для неё null (см. там же). Ярлык остаётся кликабельной областью
    // выделения — просто молчит.
    var пусто = !isRole && !s;
    gut.textContent = isRole ? '#'.repeat(r.level || 2)
      // Пометка источника («я» / «nl») убрана по просьбе пользователя: она
      // ничего не решала, а место занимала. Остались номер и буква рифмы.
      : (пусто ? '' : String(s.no).padStart(2, '0'));
    gut.title = isRole ? 'заголовок markdown · клик — выделить, shift — диапазон'
      : (пусто ? 'пустая строка · клик — выделить, shift — диапазон'
         : 'строка ' + s.no + ' · клик — выделить, shift — диапазон');
    // ВЫДЕЛЕНИЕ СТРОКИ УБИРАЕТ КАРЕТКУ СОВСЕМ (Раунд 57).
    //
    // Ярлык — нередактируемая кнопка внутри общего contenteditable. Клик по
    // ней гасит выделение, но фокус остаётся на редакторе, и браузер рисует
    // каретку в начале координат контейнера — палкой у самого левого края,
    // выше первой строки. По отчёту: каретка появлялась у левого верхнего края экрана. и
    // «это появляется, когда я выбираю строку вот так».
    //
    // Сторож `caretСпасти` сюда не достаёт: спасать нечего, диапазона в
    // выделении уже нет. Да и каретка здесь не нужна по смыслу — идёт выбор
    // строк, а не набор текста. Снимаем выделение и уводим фокус: вернётся он
    // обычным кликом по тексту.
    gut.addEventListener('mousedown', function (e) {
      e.preventDefault(); e.stopPropagation();
      self.markRow(i, e.shiftKey);
      try {
        var sel = window.getSelection && window.getSelection();
        if (sel && sel.removeAllRanges) sel.removeAllRanges();
      } catch (err) { /* нет выделения — тем лучше */ }
      if (self._lines && self._lines.blur) self._lines.blur();
    });
    if (isRole) { gut._active = marked; gut._rest = '0'; gut._hov = '0.5'; row._btns.push(gut); }
    row.appendChild(gut);

    var css = this.docCss().split('|'), fsz = parseFloat(css[0]), lh = parseFloat(css[1]), fam = css[2];
    // ЗАГОЛОВОК ВЫГЛЯДИТ ЗАГОЛОВКОМ (Раунд 56). Раньше строка с `##` рисовалась
    // МЕЛЬЧЕ основного текста (0.62×), капсом и с разрядкой 0.22em — то есть как
    // служебный ярлык секции, а не как заголовок. В markdown ровно наоборот:
    // решётка делает текст крупнее и весомее, и уровень читается размером.
    // Требование (2026-08-05): заголовки и разметка неудобны — перейти на обычный markdown..
    //
    // Шкала на уровень, а не одна ступень: 1.7 / 1.4 / 1.2 / 1.05, дальше 1.0 —
    // после четвёртого уровня разница уже не читается, и врать масштабом не
    // стоит. Регистр и разрядка не трогаются вовсе: это текст пользователя, а не
    // элемент интерфейса.
    var ЗАГ = [1.7, 1.4, 1.2, 1.05, 1.0, 1.0];
    var уров = Math.min(6, Math.max(1, r.level || 2));
    var field = this.el('div', isRole
      // min-height — ЧТОБЫ БЫЛО ГДЕ СТОЯТЬ КАРЕТКЕ (Раунд 56). Убрав
      // многоточие-заполнитель у пустых строк, я забрала у них и высоту:
      // пустой div во флексе схлопывается в ноль, и мигающая палка рисоваться
      // негде. Отчёт: на пустой строке значок ввода не отображался, на непустых отображался.. Высота строки, а не заполнитель:
      // место под каретку — свойство поля, а не текста в нём.
      ? 'flex: 1; min-width: 0; font-size: ' + Math.round(fsz * ЗАГ[уров - 1]) + 'px; line-height: 1.25; min-height: ' + Math.round(fsz * ЗАГ[уров - 1] * 1.25) + 'px; font-weight: 600; color: var(--ink); white-space: pre-wrap; word-break: break-word;' + (fam ? ' font-family: ' + fam + ';' : '')
      : 'flex: 1; min-width: 0; font-size: ' + fsz + 'px; line-height: ' + lh + '; min-height: ' + Math.round(fsz * lh) + 'px; padding: 1px 0; white-space: pre-wrap; word-break: break-word;' + (fam ? ' font-family: ' + fam + ';' : ''),
      // Заполнитель ОСТАЛСЯ ТОЛЬКО У ЗАГОЛОВКА. У обычных строк это было
      // многоточие в каждой пустой — «иногда их по три штуки показывается,
      // это бредово смотрится». Подсказка для пустого листа и так есть
      // отдельным блоком (render.doc: emptySheet), а пустая строка посреди
      // текста — это отступ, и молчать она обязана.
      { 'data-idx': String(i), 'data-ph': isRole ? '## секция' : '' });
    field.textContent = this.rowDisplay(r, i);
    row.appendChild(field);

    // при большом кегле кнопки держим у верха строки и не даём им расти
    var acts = this.el('span', 'display: flex; align-items: center; gap: 8px; flex-shrink: 0; max-width: 40%; overflow: hidden; user-select: none; -webkit-user-select: none; font-size: 10.5px; line-height: 1.4; align-self: flex-start; padding-top: ' + Math.max(0, Math.round(fsz * 0.28) - 2) + 'px;', { contenteditable: 'false', 'data-nc': '1' });
    var mk = function (label, style, fn, title, active, rest, hov) {
      var b = self.el('button', style + ' user-select: none; -webkit-user-select: none;', { contenteditable: 'false', 'data-nc': '1', tabindex: '-1' });
      if (label && label.charAt(0) === '<') b.innerHTML = label; else b.textContent = label;
      if (title) b.title = title;
      b._active = !!active; b._rest = rest || '0'; b._hov = hov || '0.45';
      b._col = active ? 'var(--ink)' : 'var(--muted)';
      b.style.opacity = active ? '1' : b._rest;
      row._btns.push(b);
      b.addEventListener('mouseenter', function () { b.style.opacity = '1'; b.style.color = 'var(--ink)'; });
      b.addEventListener('mouseleave', function () { b.style.opacity = b._active ? '1' : b._hov; b.style.color = b._col; });
      b.addEventListener('mousedown', function (e) { e.preventDefault(); });
      b.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); fn(); });
      return b;
    };
    if (!isRole) {
      var ob = ICO_BTN;
      var fav = !!r.fav;
      acts.appendChild(mk(ico('star', fav), ob(fav), function () { self.toggleFavRow(i); }, fav ? 'Убрать из избранного' : 'В избранное', fav));
    }
    row.appendChild(acts);
    return row;
  },
  // читаем DOM после любой правки и приводим модель в соответствие
  readDom() {
    if (!this._lines) return;
    if (!this.hist) { this.hist = []; this.future = []; } // дизайн заводит их в componentDidMount — миксин полей не объявляет
    var prevDoc = this.cur(), out = [], self = this, snap = this.caretSnap(), seen = {};
    // читаем ВСЕ поля в порядке документа: браузер мог создать второе поле внутри строки
    Array.prototype.slice.call(this._lines.querySelectorAll('[data-idx]')).forEach(function (field) {
      var raw = self.domText(field);
      var ai = parseInt(field.getAttribute('data-idx'), 10);
      var dup = seen[ai]; seen[ai] = 1;
      var old = (!dup && !isNaN(ai) && prevDoc[ai]) ? prevDoc[ai] : null;
      var next = self.parseRow(old || {}, raw);
      // Заголовок, у которого решётки СКРЫТЫ (каретка не в нём), приезжает из
      // DOM голым текстом — и `parseRow` честно назвал бы его обычной строкой.
      // Это и есть цена скрытия разметки, и платить её нельзя: заголовки молча
      // разжаловались бы при первом же нажатии клавиши где угодно в документе.
      //
      // Правим по тому, что знаем: строка была заголовком, каретка не в ней,
      // значит руками её текст сейчас не меняли — уровень сохраняем, текст
      // берём как есть. Строка ПОД кареткой всегда показана с решётками, то
      // есть разжаловать заголовок стиранием решёток по-прежнему можно.
      if (old && old.type === 'role' && next.type === 'line' && ai !== self._activeRow) {
        out.push(old.text === next.text ? old : { type: 'role', text: next.text, level: old.level || 2 });
        return;
      }
      if (next.type === 'role') {
        if (old && old.type === 'role' && old.text === next.text && (old.level || 2) === next.level) out.push(old);
        else out.push(next);
        return;
      }
      // Текст изменился — ключ ядра больше НЕ про эту строку: выбрасываем его
      // вместе со старым текстом, дальше буква придёт из словаря по новому.
      if (old && old.type === 'line') {
        if (next.text === old.text) { out.push(old); return; }
        var свежая = Object.assign({}, old, { text: next.text, src: 'я', fav: false });
        delete свежая.rk;
        out.push(свежая);
        return;
      }
      out.push({ type: 'line', text: next.text, letter: (old && old.letter) || 'а', src: 'я' });
    });
    // после склейки строк остаётся пустая обёртка — убираем пустое только если строк стало меньше
    if (out.length < prevDoc.length) {
      var keepRow = snap ? snap.row : -1;
      out = out.filter(function (r, i) { return r.type === 'role' || r.text !== '' || i === keepRow || prevDoc.indexOf(r) >= 0; });
    }
    if (!out.length) out.push({ type: 'line', text: '', letter: 'а', src: 'я' });
    var same = out.length === prevDoc.length && out.every(function (r, i) { return r === prevDoc[i]; });
    if (same) return;
    this._restore = snap;
    var now = Date.now();
    if (now - (this._typeT || 0) > 1200 || out.length !== prevDoc.length) this.hist.push(JSON.stringify(prevDoc));
    if (this.hist.length > 80) this.hist.shift();
    this._typeT = now;
    this.future = [];
    this._doc$ = out;
    this.setState({ doc: out, undoN: this.hist.length, redoN: 0, dirty: true, pop: null });
    this.markSaved();
  },
  // ВОССТАНОВЛЕНО (Раунд 57). На `push` стоит ВСЁ, что меняет документ не
  // печатью: перенос строки на Enter, вставка блока генерации, перестановка
  // строк, markdown-обёртки. Без него редактор молча падал на первом же таком
  // действии — отчёт: перенос строки по Enter перестал работать, генерация скакала по строкам..
  //
  // Мой сторож вызовов его не поймал: я по недосмотру внесла `push` в список
  // встроенных, рядом с `Array.prototype.push`. Список сузила.
  push(doc, prev) {
    if (!this.hist) { this.hist = []; this.future = []; }
    if (prev) {
      this.hist.push(JSON.stringify(prev));
      if (this.hist.length > 80) this.hist.shift();
    }
    this.future = [];
    this._doc$ = doc;
    this.setState({ doc: doc, undoN: this.hist.length, redoN: 0, dirty: true, pop: null });
    this.markSaved();
  },

  // Отмена и возврат: снимок документа целиком, как его кладёт `push`.
  undo() {
    if (!this.hist || !this.hist.length) return;
    var prev = this.cur();
    var doc = JSON.parse(this.hist.pop());
    this.future = this.future || [];
    this.future.push(JSON.stringify(prev));
    this._doc$ = doc;
    this.setState({ doc: doc, undoN: this.hist.length, redoN: this.future.length, dirty: true, pop: null });
    this.markSaved();
  },
  redo() {
    if (!this.future || !this.future.length) return;
    var prev = this.cur();
    var doc = JSON.parse(this.future.pop());
    this.hist = this.hist || [];
    this.hist.push(JSON.stringify(prev));
    this._doc$ = doc;
    this.setState({ doc: doc, undoN: this.hist.length, redoN: this.future.length, dirty: true, pop: null });
    this.markSaved();
  },

  // ВОССТАНОВЛЕНО (Раунд 57), пятая жертва того же вырезания. Автосохранение
  // листа с задержкой: правка идёт очередями, писать на каждый знак незачем.
  // `flushSave` (methods.sheets) досохраняет по этому же `_saveT`, если
  // разрушительный переход случился раньше срабатывания.
  markSaved() {
    var self = this;
    clearTimeout(this._saveT);
    this._saveT = setTimeout(function () {
      self._saveT = null;
      var st = self.state, id = st.sheetId;
      var here = (st.sheets || []).filter(function (x) { return x.id === id; })[0];
      if (!id || !here || here.trashed) return;
      api.sheetsWrite(id, self.cur()).then(function (res) {
        self.setState({ dirty: false, savedAt: (res && res.at) || self.clock() });
      }, function (e) {
        self.flash('не сохранилось: ' + (e && e.message ? e.message : String(e)));
      });
    }, 700);
  },

  // markdown-обёртки как в Obsidian: ⌘B, ⌘I, ⌘1 — заголовок
  fileName(s) {
    var t = (s && s.title) || 'без-названия';
    return t.toLowerCase().replace(/ё/g, 'е').replace(/[^a-zа-я0-9]+/g, '-').replace(/^-|-$/g, '') + '.md';
  },
  wrapSel(mark) {
    var c = this.caretSnap(); if (!c) return;
    var sel = getSelection(), prev = this.cur(), row = prev[c.row];
    if (!row || row.type !== 'line') return;
    var full = row.text, a = c.off, b = c.off;
    if (sel && !sel.isCollapsed) {
      var fields = this._lines.querySelectorAll('[data-idx]'), f = fields[c.row];
      if (f) {
        var r0 = sel.getRangeAt(0), q = r0.cloneRange();
        q.selectNodeContents(f); q.setEnd(r0.startContainer, r0.startOffset); a = q.toString().length;
        var q2 = r0.cloneRange(); q2.selectNodeContents(f); q2.setEnd(r0.endContainer, r0.endOffset); b = q2.toString().length;
      }
    }
    if (a === b) { // нет выделения — берём слово под курсором
      var pre = full.slice(0, a), post = full.slice(a);
      a -= (pre.match(/[\wа-яА-ЯёЁ-]*$/) || [''])[0].length;
      b += (post.match(/^[\wа-яА-ЯёЁ-]*/) || [''])[0].length;
    }
    if (a === b) return;
    var inner = full.slice(a, b), doc = prev.slice(), out, m = mark.length;
    var wrapped = full.slice(Math.max(0, a - m), a) === mark && full.slice(b, b + m) === mark;
    if (wrapped) { out = full.slice(0, a - m) + inner + full.slice(b + m); b -= m * 2; }
    else out = full.slice(0, a) + mark + inner + mark + full.slice(b);
    doc[c.row] = Object.assign({}, row, { text: out, src: 'я' });
    this._restore = { row: c.row, off: wrapped ? b + m : b + m * 2 };
    this.push(doc, prev);
  },
  toggleHeading(level) {
    var c = this.caretSnap(); if (!c) return;
    var prev = this.cur(), row = prev[c.row]; if (!row) return;
    var doc = prev.slice();
    doc[c.row] = row.type === 'role'
      ? (row.level === level ? { type: 'line', text: row.text, letter: 'а', src: 'я' } : { type: 'role', text: row.text, level: level })
      : { type: 'role', text: row.text, level: level };
    this._restore = { row: c.row, off: doc[c.row].text.length };
    this.push(doc, prev);
  },
  onDocKey(e) {
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      var s = this.caretSnap();
      if (s) this.moveRow(s.row, e.key === 'ArrowUp' ? -1 : 1);
      return;
    }
    // ⌥↵ ИСКЛЮЧЁН (Раунд 57). Здесь проверялись shift, cmd и ctrl — но не alt.
    // Поэтому ⌥↵ срабатывал ДВАЖДЫ: этот обработчик честно делил строку, а
    // глобальный (Nakedlunch.onGlobalKey) тут же запускал принудительную
    // генерацию. Отсюда лишняя пустая строка над блоком — отчёт: при принудительной вставке появлялся отступ сверху..
    if (e.key === 'Enter' && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
      // Chrome делит внутреннее поле, а не строку — делим сами
      e.preventDefault();
      var c = this.caretSnap(); if (!c) return;
      var prev = this.cur(), row = prev[c.row]; if (!row) return;
      var full = this.rowText(row), head = full.slice(0, c.off), tail = full.slice(c.off);
      var doc = prev.slice();
      doc[c.row] = this.parseRow(row, head);
      doc.splice(c.row + 1, 0, this.parseRow({ letter: row.letter }, tail));
      this._restore = { row: c.row + 1, off: 0 };
      this.push(doc, prev);
    }
  },
  // Курсор, севший НЕ в строку (Раунд 56).
  //
  // Редактируемое поле — контейнер `_lines` целиком, а строки лежат в нём
  // флексами: у каждой слева поле-ярлык шириной 7ch, поэтому текст начинается
  // не от левого края контейнера. Клик в отступ контейнера (сверху 40px) или
  // в промежуток слева от ярлыка ставил каретку В САМ КОНТЕЙНЕР — и браузер
  // рисовал её в его начале координат, то есть ЛЕВЕЕ текста и ВЫШЕ первой
  // строки. Отчёт (2026-08-05): курсор ввода виден за листом, слева сверху..
  //
  // Ловим по тому же признаку, по которому `caretSnap` возвращает null:
  // фокус не внутри ни одного `[data-idx]`. Ближайшая строка выбирается по
  // вертикали от точки клика — щелчок над первой строкой уводит в её начало,
  // под последней — в конец последней, ровно как ждёшь от текстового поля.
  // Каретка не внутри поля строки, а в самом редактируемом контейнере?
  // Вернуть её в ближайшую строку. Возвращает true, если пришлось спасать.
  caretСпасти() {
    if (!this._lines || typeof window === 'undefined') return false;
    var sel = window.getSelection && window.getSelection();
    if (!sel) return false;
    // ВЫДЕЛЕНИЯ НЕТ ВОВСЕ, А ФОКУС НА РЕДАКТОРЕ. Тогда браузер тоже рисует
    // каретку в начале координат контейнера — это путь ⌘↵: блок вставился,
    // строки перестроились, диапазон умер вместе со старыми узлами. отчёт: показывается по Cmd+Enter.. Ставим её в ту строку, которую сама
    // генерация назначила текущей.
    if (!sel.rangeCount) {
      // Пока идёт прогон, каретки в редакторе нет НАРОЧНО (methods.gen:
      // снятьКаретку) — сторож обязан не мешать, иначе он вернёт её сразу же и
      // палка появится снова.
      if (this.state.genBusy) return false;
      // Условие было `activeElement === _lines`, и на ⌘↵ оно не выполнялось:
      // после перестройки строк фокус уходит на body, а каретку браузер всё
      // равно рисует в начале координат контейнера. отчёт: по Cmd+Enter каретка всё равно показывалась..
      //
      // Теперь смотрим не на фокус, а на то, ЧЕМ он занят: активен редактор
      // (или ничего) — ставим каретку в строку; активна панель, поле ввода или
      // кнопка — не лезем, там своя жизнь.
      if (typeof document === 'undefined') return false;
      var a = document.activeElement;
      var чужое = a && a !== document.body && a !== this._lines && !this._lines.contains(a);
      if (чужое || this.state.tab !== 'editor') return false;
      var поля = this._lines.querySelectorAll('[data-idx]');
      if (!поля.length) return false;
      var i = Math.max(0, Math.min(поля.length - 1, this.state.caret));
      this.caretEnd(поля[i]);
      return true;
    }
    var узел = sel.anchorNode;
    if (!узел) return false;
    var эл = узел.nodeType === 1 ? узел : узел.parentNode;
    if (!эл || !this._lines.contains(эл)) return false;   // не наш редактор — не трогаем
    if (эл.closest && эл.closest('[data-idx]')) return false;   // всё в порядке
    var верх = 0;
    try { верх = sel.getRangeAt(0).getBoundingClientRect().top || 0; } catch (e) {}
    this.caretRescue(верх);
    return true;
  },

  // ВОССТАНОВЛЕНО (Раунд 57). Эти четыре метода я снесла собственным вырезанием
  // блока «выбор слов»: диапазон удаления захватил соседей, и редактор перестал
  // рисоваться вовсе. Старой сборки на диске не осталось, `wordAt` и `hitsWord`
  // вернулись дословно, `setCaret` и `caretEnd` собраны по их вызовам:
  //   setCaret(f, c.off + уровень + 1)   — смещение В ЗНАКАХ внутри строки;
  //   setCaret(цель, 0) / caretEnd(цель) — начало и конец строки;
  //   setCaret(el, this._focusAt)        — возврат фокуса после перерисовки.

  // Каретка в строку по смещению в знаках.
  setCaret(el, off) {
    try {
      var sel = getSelection();
      if (!sel) return;
      var r = document.createRange(), node = el && el.firstChild;
      if (node && node.nodeType === 3) {
        var n = node.length;
        r.setStart(node, Math.max(0, Math.min(off || 0, n)));
      } else {
        // пустая строка: текстового узла нет, встаём в сам элемент
        r.setStart(el, 0);
      }
      r.collapse(true);
      sel.removeAllRanges();
      sel.addRange(r);
    } catch (e) { /* строка перерисовывается — поставит следующий клик */ }
  },

  // Каретка в конец строки.
  caretEnd(el) {
    var node = el && el.firstChild;
    this.setCaret(el, node && node.nodeType === 3 ? node.length : 0);
  },

  // Слово под кареткой: границы по буквам, дефис считается частью слова.
  wordAt(el) {
    var sel = getSelection();
    if (!sel || !sel.focusNode || !el.contains(sel.focusNode)) return null;
    var t = el.textContent || '', off = sel.focusOffset;
    var pre = t.slice(0, off), post = t.slice(off);
    var a = (pre.match(/[\wа-яА-ЯёЁ-]*$/) || [''])[0];
    var b = (post.match(/^[\wа-яА-ЯёЁ-]*/) || [''])[0];
    var w = a + b;
    if (!w || w.length < 2) return null;
    return { w: w, start: off - a.length, end: off + b.length };
  },

  // Курсор встаёт в конец строки и при клике в пустоту справа — поэтому одного
  // слова под кареткой мало: проверяем, что точка клика попала в сами буквы.
  hitsWord(el, found, x, y) {
    if (x == null || y == null) return true;
    var node = el.firstChild;
    if (!node || node.nodeType !== 3) return true;
    try {
      var r = document.createRange(), n = node.length;
      r.setStart(node, Math.max(0, Math.min(found.start, n)));
      r.setEnd(node, Math.max(0, Math.min(found.end, n)));
      var rects = r.getClientRects();
      for (var k = 0; k < rects.length; k++) {
        var b = rects[k];
        if (x >= b.left - 2 && x <= b.right + 2 && y >= b.top - 2 && y <= b.bottom + 2) return true;
      }
    } catch (err) { return true; }
    return false;
  },

  caretRescue(y) {
    var fields = this._lines ? Array.prototype.slice.call(this._lines.querySelectorAll('[data-idx]')) : [];
    if (!fields.length) return;
    var цель = fields[0], вниз = false;
    if (typeof y === 'number') {
      for (var k = 0; k < fields.length; k++) {
        var r = fields[k].getBoundingClientRect();
        if (y >= r.top) { цель = fields[k]; вниз = y > r.bottom; }
      }
    }
    if (вниз) this.caretEnd(цель); else this.setCaret(цель, 0);
    цель.focus && цель.focus();
  },
  // КНИГА ВЫДЕЛЕННОЙ СТРОКИ (Раунд 57). Показывается в панели выделения, когда
  // выделена РОВНО ОДНА строка и она пришла из корпуса: у своей строки книги
  // нет, а у нескольких это был бы список, а не подпись.
  выделеннаяКнига() {
    var метки = this.state.marks || {};
    var номера = Object.keys(метки).filter(function (k) { return метки[k]; });
    if (номера.length !== 1) return null;
    var r = this.cur()[Number(номера[0])];
    if (!r || r.type !== 'line' || !r.book) return null;
    return { book: r.book, bookId: r.bookId || '' };
  },

  // Отключить книгу прямо из панели выделения. Переключатель тот же, что в
  // корпусе, — второго источника правды не заводим.
  async отключитьКнигу(id) {
    if (!id) { this.flash('у этой строки не записан источник'); return; }
    try {
      await api.sourceToggle(id);
      this.flash('источник отключён — его строки больше не придут');
      if (this.loadNl) this.loadNl();
      this.setState({ marks: {}, markAnchor: -1 });
    } catch (e) { this.flash(e.message); }
  },

  onDocClick(e) {
    // ВЫБОР СЛОВ ПЕРЕЖИВАЕТ ПЕРЕМЕЩЕНИЕ КАРЕТКИ (Раунд 57, уточнение отчёт: выделенные слова пропадали при переносе каретки, а должны — только при
    // повторном нажатии на них.). Здесь стоял сброс набора; это была моя догадка, а не его правило.
    // Снимает выбор только повторный клик по самому слову, и переносит — клик
    // по другому слову. Всё остальное набор не трогает.
    // ПРОТЯЖКА КОНЧАЕТСЯ КЛИКОМ. Без этой проверки попап открывался бы поверх
    // только что сделанного выделения и схлопывал его — отчёт (2026-08-05): выделение мышью сбрасывалось сразу..
    // Признак честный: у клика выделение пустое, у протяжки — нет.
    var sel = typeof getSelection === 'function' ? getSelection() : null;
    if (sel && sel.rangeCount && !sel.isCollapsed) return;
    var field = e.target.closest && e.target.closest('[data-idx]');
    if (!field) { this.caretRescue(e.clientY); return; }
    var i = parseInt(field.getAttribute('data-idx'), 10);
    this.setState({ caret: i });
    if (this.cur()[i] && this.cur()[i].type === 'line') {
      this.onWordClick(i, { currentTarget: field, clientX: e.clientX, clientY: e.clientY });
    }
  },

  // ВЫБОР СЛОВ КЛИКАМИ ВЫРЕЗАН (Раунд 57). Он прожил один заход: подсветка
  // отставала от текста при правке, тема из него читалась ненадёжно, и сам
  // способ оказался неудобным. Требование: убрать усложнение, темы задавать в настройках строфы через запятую.. Тема теперь
  // поле `state.themeKeys` (render.gen), а клик по слову делает ровно одно —
  // открывает попап с рифмами и синонимами.
  //
  // Запрет протяжки и двойного клика тоже снят: «выделять для копирования и
  // удаления протяжкой можно, ну типа как в обычном редакторе, просто у этого
  // нет спец функций». То есть мышью выделяем как везде — копировать, удалять,
  // заменять; смысла для генерации у такого выделения больше нет никакого.

  onWordClick(i, e) {
    // ворота WORD_POPUP оставлены: если словарные слои провалят живую проверку,
    // попап гасится одной константой — клик снова лишь ставит каретку
    if (!WORD_POPUP) { this.setState({ caret: i }); return; }
    var el = e.currentTarget, found = this.wordAt(el);
    if (!found || !this.hitsWord(el, found, e.clientX, e.clientY)) return;
    var p = this.state.pop;
    // повторный клик по тому же слову — закрыть
    if (p && p.i === i && p.start === found.start && p.end === found.end) {
      this.setState({ pop: null });
      return;
    }
    var r = el.getBoundingClientRect();
    var host = (el.offsetParent && el.offsetParent.closest('section')) || this._root;
    var hb = host.getBoundingClientRect();
    var H = 300, gap = 10;
    var below = r.bottom - hb.top + gap, above = r.top - hb.top - gap;
    var up = below + H > hb.height - 190 && above > H * 0.6;
    var x = Math.max(8, Math.min(r.left - hb.left + 40, hb.width - 274));
    var self = this;
    // popLoading сразу в этом же setState: между открытием и fetchSuggest
    // не должен мигать прочерк пустого списка
    this.setState({
      pop: { i: i, word: found.w, start: found.start, end: found.end, x: x, up: up,
             y: up ? Math.max(8, hb.height - above) : below },
      popTab: 'рифмы', popItems: [], popLoading: true,
    }, function () { self.fetchSuggest(); });
  },
  // поход за подсказками для текущего слова и вкладки. Кэш — Map на инстансе,
  // живёт сессию: индексы бэка статичны, повторный поход за тем же — трата
  async fetchSuggest() {
    var p = this.state.pop; if (!p) return;
    var word = p.word, tab = this.state.popTab;
    // номер похода: при быстром щёлканье по вкладкам поздний ответ старого
    // похода не должен перетирать более свежий
    var seq = this._sugSeq = (this._sugSeq || 0) + 1;
    if (!this._sugCache) this._sugCache = new Map();
    var key = word + '|' + tab;
    var hit = this._sugCache.get(key);
    if (hit) { this.setState({ popItems: hit, popLoading: false }); return; }
    this.setState({ popLoading: true, popItems: [] });
    // текст строки — контекст бэка: «строкой» подбирает замену всей строке,
    // остальным вкладкам он уточняет рифмо-контекст
    var row = this.cur()[p.i];
    var line = row && row.type === 'line' ? row.text : '';
    try {
      var res = await api.wordSuggest(word, tab, line);
      var items = (res && res.items) || [];
      this._sugCache.set(key, items);
      if (seq !== this._sugSeq) return; // пока ждали сеть, ушёл запрос свежее
      this.setState({ popItems: items, popLoading: false });
    } catch (e) {
      // честная ошибка: прочерк в списке (applyWord его игнорирует), причина —
      // во flash; в кэш не кладём — следующий клик попробует снова
      if (seq !== this._sugSeq) return;
      this.setState({ popItems: [{ w: '—', n: '' }], popLoading: false });
      this.flash(e && e.message ? e.message : String(e));
    }
  },
  // смена вкладки попапа: подсветка сразу, данные — тем же fetchSuggest
  // (кэш или сеть); колбэк setState — чтобы fetchSuggest увидел новую вкладку
  setPopTab(t) {
    var self = this;
    if (this.state.popTab === t) return;
    this.setState({ popTab: t }, function () { self.fetchSuggest(); });
  },
  // данные списка попапа: во время похода — скелет из трёх плашек (обещание
  // ВСТРАИВАНИЕ.md дизайна), пустой ответ — честный прочерк, не догадки
  // Раунд 32: бэк размечает рифмы типами (богатая/точная/усечённая/неточная)
  // в поле t — требование: категоризировать и помечать разные типы..
  // Заголовок вставляем при СМЕНЕ типа: неточная рифма обязана быть подписана
  // как неточная, а не выдаваться за точную. Вкладки без типов (по звуку,
  // синонимы, антонимы, строкой) присылают t пустым — заголовков не будет.
  popList() {
    if (this.state.popLoading) return [{ skel: 1 }, { skel: 1 }, { skel: 1 }];
    var items = this.state.popItems || [];
    if (!items.length) return [{ w: '—', n: '' }];
    var out = [], last = null;
    for (var i = 0; i < items.length; i++) {
      var o = items[i];
      if (o.t && o.t !== last) out.push({ head: o.t });
      last = o.t || null;
      out.push(o);
    }
    return out;
  },
  norm(s) { return String(s || '').toLowerCase().replace(/ё/g, 'е').replace(/[^а-я0-9]/g, ''); },
  vowels(s) { return s.replace(/[^аеиоуыэюя]/g, ''); },
  // применяет выбор из попапа к items-формату {w,n}: слово — замена диапазона
  // (моё, закреплено), «строкой» — вся строка целиком (от nl, не закреплена)
  applyWord(nw) {
    var p = this.state.pop; if (!p || nw === '—') return;
    var prev = this.cur(), doc = prev.slice(), row = doc[p.i]; if (!row) return;
    var t = row.text, whole = this.state.popTab === 'строкой';
    doc[p.i] = whole
      ? Object.assign({}, row, { text: nw, src: 'nl' })
      : Object.assign({}, row, { text: t.slice(0, p.start) + nw + t.slice(p.end), src: 'я' });
    this._typeAt = -1;
    this.push(doc, prev);
    this.setState({ pop: null });
  },
  fmt(n) { return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' '); },

  // ---- генерация ----
  // решение прожарки 4: перекат строки — реальный вызов генератора на одну строку
  // (мок-пул дизайна удалён); ключ темы — тот же, что у последней генерации (_lastKey)

  // звезда живёт на самой строке: одинаковый текст в двух строках больше не связывает их
  toggleFavRow(i) {
    var prev = this.cur(), doc = prev.slice(), r = doc[i], self = this;
    if (!r || r.type !== 'line') return;
    var on = !r.fav, t = r.text;
    doc[i] = Object.assign({}, r, { fav: on });
    var favs = (this.state.favs || []).slice();
    // решение прожарки 3: звёзды живут в corpus.json — пишем на бэк не дожидаясь ответа,
    // и только когда список избранного реально меняется
    if (on) {
      if (t && !favs.some(function (f) { return f.t === t; })) {
        favs.unshift({ t: t });
        api.favAdd({ text: t }).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
      }
    } else if (!doc.some(function (x) { return x.type === 'line' && x.fav && x.text === t; })) {
      favs = favs.filter(function (f) { return f.t !== t; });
      if (t) api.favRemove(t).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
    }
    this.setState({ favs: favs });
    this.push(doc, prev);
  },
  // снятие из списка избранного гасит звёзды у всех строк с этим текстом
  dropFav(t) {
    var prev = this.cur(), changed = false, self = this;
    var doc = prev.map(function (r) {
      if (r.type === 'line' && r.fav && r.text === t) { changed = true; return Object.assign({}, r, { fav: false }); }
      return r;
    });
    // favUndo — для «вернуть удалённое» в панели избранного (Раунд 40):
    // один промах по «−» не должен стоить строки безвозвратно
    this.setState({ favs: (this.state.favs || []).filter(function (f) { return f.t !== t; }), favUndo: t });
    if (changed) this.push(doc, prev);
    // решение прожарки 3: удаление — тоже в corpus.json, не дожидаясь
    api.favRemove(t).catch(function (e) { self.flash(e && e.message ? e.message : String(e)); });
  },
  insertText(t) {
    var prev = this.cur(), doc = prev.slice(), self = this, at = this.insertAt();
    doc.splice(at, 0, { type: 'line', text: t, letter: 'а', src: 'nl' });
    this.setState({ caret: at });
    this.push(doc, prev);
    this.closePop();
    setTimeout(function () { if (self._doc) self._doc.scrollTop = self._doc.scrollHeight; }, 60);
  },
  // setFilter вырезан (Раунд 50) вместе с тремя флажками «фильтры»:
  // «фильтр банальности» не был подключён ни к одному кнобу, «слоги 8–9»
  // молча переписывал конструктор строфы, «только точные рифмы» ставил
  // rhyme_precision в 1 — то есть САМЫЕ МЯГКИЕ по шкале ядра, обратное
  // своему названию.
};
