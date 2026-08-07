// Пилюля «листы» из дизайна «Editor First» (project-notes/mockups/design-v2/
// Editor First.dc.html): разметка — строки 809..885, vals — соответствующий
// кусок renderVals (3390..3710), пересчитывается здесь локально. Дизайн —
// источник истины, стили перенесены дословно. Адаптации к серверу (помечены
// по месту): счёт строк есть только у открытого листа (doc остальных живёт
// на диске); срок корзины — days_left с бэка; vaultPath/vaultTitle — честный
// путь хранилища; «открыть папку» — настоящий Finder (api.sheetsOpenDir через
// c.openVault). Инпуты value=… из шаблона стали defaultValue: поля
// неуправляемые, коммит по Enter/blur — как и вёл себя DC-runtime.
// renderEmptySheet — подсказка пустого листа (шаблон 1203..1211): живёт в
// области документа, интегратор вставляет её в скролл перед contenteditable.

import { s, hov } from './style.js';

export function renderSheets(c) {
  var st = c.state, isFs = st.tab === 'fs';
  var lines = st.doc.filter(function (r) { return r.type === 'line' && r.text; });
  var sheets = st.sheets || [];
  var curSheet = sheets.filter(function (x) { return x.id === st.sheetId; })[0];
  var trashN = sheets.filter(function (x) { return x.trashed; }).length;
  var folders = c.allFolders();
  var curFolder = c.folderById(st.folderId);
  var sheetList = sheets.filter(function (x) { return st.trashView ? x.trashed : (!x.trashed && c.inFolder(x, curFolder)); });
  var liveSheets = sheets.filter(function (x) { return !x.trashed; });
  var hdrT = c.hdr ? c.hdr() : 0;      // ярус сжатия шапки (Раунд 38)
  var docsOpen = st.openPill === 'docs';
  var docsOut = st.closing === 'docs' ? '1' : null;
  var sheetTitle = (curSheet && curSheet.title) || 'Без названия';
  // Путь листа без его имени: «Серии/Пепел/дверь ночь/01 строка.md» →
  // «Пепел › дверь ночь». Корень серий из крошки убираем — он один на все и
  // ничего не различает.
  var крошка = String((curSheet && curSheet.id) || '').split('/').slice(0, -1)
    .filter(function (ч, i) { return !(i === 0 && ч === 'Серии'); })
    .join(' › ');
  // честный путь: vault = ~/Documents/nakedlunch/тексты (core/sheets.py)
  var vaultPath = 'Документы / nakedlunch / тексты / ' + (curFolder && !curFolder.keys ? curFolder.name + ' / ' : '');
  var vaultTitle = 'папка «Документы» вашей системы · листы хранятся как .md · текущий файл: ' + (curSheet ? curSheet.id : '—');
  // ДЕЙСТВИЯ СТРОКИ ВИДНЫ ВСЕГДА (Раунд 55). Здесь стояло `opacity: var(--sh, 0)`
  // — то есть переименовать, переложить, продублировать и выбросить можно было
  // только наведя курсор ровно на строку. Владелец: «у меня кнопок удаления
  // папок и листов нет вообще», и он прав: контрол, которого не видно, для
  // пользователя не существует. Тихие 0.55, при наведении — полные.
  var actStyle = s('appearance: none; background: none; border: none; padding: 4px 3px; font-size: 10.5px; line-height: 1; color: var(--muted-soft); cursor: pointer; opacity: var(--sh, 0.55); transition: opacity 0.12s var(--ease); flex-shrink: 0;');
  var chipStyle = function (on) { return s('appearance: none; border: none; border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: 9px; cursor: pointer; white-space: nowrap; ' + (on ? 'background: var(--ink); color: var(--canvas);' : 'background: color-mix(in srgb, var(--ink) 6%, transparent); color: var(--muted);')); };

  return (
    <div data-pop="1" style={s((isFs ? 'display: none;' : 'display: flex;') + ' position: relative; z-index: 60; flex-shrink: 0; align-items: center; gap: ' + [8, 7, 6, 5][hdrT] + 'px;')}>
      {st.titleEdit && (
        <input data-title-input="1" type="text" key={'title-' + st.sheetId} defaultValue={sheetTitle}
          ref={function (el) { c.titleInputRef(el); }}
          onKeyDown={function (e) {
            if (e.key === 'Enter') { c.renameSheet(st.sheetId, e.target.value); c.setState({ titleEdit: false }); c.focusFirstLine(); }
            if (e.key === 'Escape') { c.setState({ titleEdit: false }); c.focusFirstLine(); }
          }}
          onBlur={function (e) { c.renameSheet(st.sheetId, e.target.value); c.setState({ titleEdit: false }); }}
          style={s('width: 180px; background: transparent; border: none; border-bottom: 1px solid var(--border-soft); padding: 3px 2px; font-size: 11px; color: var(--ink);')} />
      )}
      {!st.titleEdit && (
        <button onClick={function () { c.tog('docs'); }}
          onDoubleClick={function (e) { e.stopPropagation(); c._focusRename = 'title'; c.closePop({ titleEdit: true }); }}
          title="Клик — список листов · двойной клик — переименовать"
          className={hov('opacity: 0.75')}
          style={s('appearance: none; background: none; border: none; padding: 4px 2px; display: flex; align-items: baseline; gap: ' + [8, 7, 6, 5][hdrT] + 'px; cursor: pointer; max-width: ' + [420, 320, 200, 96][hdrT] + 'px;')}>
          {/* КРОШКА (Раунд 55): «Пепел › дверь ночь ›» перед именем листа.
              Id листа и так полный путь, так что это чистая отрисовка — а
              без неё открытый лист не показывал свою папку вовсе, и на текст
              из серии нельзя было посмотреть и понять, чей он трек. На узких
              ярусах шапки уходит первой: имя листа важнее. */}
          {hdrT >= 2 || !крошка ? null : (
            <span style={s('font-size: 9px; color: var(--muted-soft); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-shrink: 1; min-width: 0;')}>{крошка}</span>)}
          <span style={s('font-size: 11px; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;')}>{sheetTitle}</span>
          {/* Раунд 38: со второго яруса число строк уходит — оно есть в самом
              попапе листов, рядом с каждым листом, и это первое, чем можно
              пожертвовать в узком окне. */}
          {hdrT >= 2 ? null : (<span style={s('font-size: 9px; color: var(--muted-soft); font-variant-numeric: tabular-nums; flex-shrink: 0;')}>{lines.length + ' стр.'}</span>)}
          <span style={s('font-size: 8.5px; color: var(--muted-soft); flex-shrink: 0;')}>▾</span>
        </button>
      )}
      <button onClick={function () { c.newSheet(); }} title="Новый лист" className={hov('color: var(--ink)')} style={s('appearance: none; background: none; border: none; padding: 2px 4px; font-size: 13px; line-height: 1; color: var(--muted-soft); cursor: pointer;')}>＋</button>
      {docsOpen && (
        <div data-pa="down" data-po={docsOut} style={s('position: absolute; top: calc(100% + 12px); left: 0; z-index: 80; width: 280px; max-height: 60vh; overflow-y: auto; background: var(--menu-bg); backdrop-filter: var(--glass-fx); -webkit-backdrop-filter: var(--glass-fx-fallback); contain: paint; isolation: isolate; box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: 6px;')}>
          <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 2px 8px 8px;')}>
            <span style={s('font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--muted-soft);')}>{st.trashView ? 'корзина' : 'листы'}</span>
            <button onClick={function () { c.setState({ trashView: !st.trashView, confirm: '' }); }} className={hov('color: var(--ink)')} style={s('appearance: none; background: none; border: none; padding: 0; font-size: 9px; color: var(--muted-soft); cursor: pointer;')}>{st.trashView ? '← листы' : 'корзина ' + trashN}</button>
          </div>
          {!st.trashView && (
            <div style={s('display: flex; flex-wrap: wrap; gap: 3px; padding: 0 4px 9px;')}>
              {[{ id: '', name: 'все', keys: null }].concat(folders).map(function (f) {
                var n = f.id === '' ? liveSheets.length : liveSheets.filter(function (x) { return c.inFolder(x, f); }).length;
                return (
                  <span key={f.id || 'все'} style={s('display: inline-flex; align-items: center;')}>
                  <button
                    onClick={function (e) { if (e.shiftKey && f.id) { c.dropFolder(f.id); return; } c.setState({ folderId: f.id, moveOpen: '' }); }}
                    title={f.keys ? 'умная папка · ' + f.keys.join(', ') : (f.id ? 'папка' : 'все листы')}
                    style={chipStyle(st.folderId === f.id)}>
                    {/* Вложенная папка (Раунд 53) показывает, ГДЕ она лежит:
                        чипы переносятся по строкам, и отступом дерево не
                        нарисовать — а «Пепел» без «Серии ›» рядом с чужим
                        «Пепел» из другой ветки неотличим. */}
                    {f.depth ? <span style={s('opacity: 0.45;')}>{f.id.split('/').slice(-2, -1)[0] + ' › '}</span> : null}
                    {f.keys ? '⌁ ' + f.name : f.name}<span style={s('opacity: 0.5; font-variant-numeric: tabular-nums;')}>{f.id === '' ? '' : ' ' + n}</span>
                  </button>
                  {/* КНОПКА, а не только shift-клик (Раунд 55). Удаление папки
                      жило исключительно в подсказке при наведении — то есть его
                      не было. Крестик у ВЫБРАННОЙ папки: редкое действие открыто
                      выбором, а не висит на каждом чипе. */}
                  {f.id && st.folderId === f.id ? (
                    <button onClick={function (e) { e.stopPropagation(); c.dropFolder(f.id); }}
                      title={'Удалить папку «' + f.name + '»'}
                      style={s('appearance: none; background: none; border: none; padding: 4px 4px; font-size: 10px; line-height: 1; color: var(--muted-soft); cursor: pointer;')}
                      className={hov('color: var(--ink)')}>✕</button>) : null}
                  </span>
                );
              })}
              <button onClick={function () { c.setState({ folderDraft: 'plain' }); c._focusRename = 'folder'; }} title="Новая папка" className={hov('color: var(--ink)')} style={s('appearance: none; background: none; border: none; padding: 4px 6px; font-family: inherit; font-size: 9px; color: var(--muted-soft); cursor: pointer;')}>＋ папка</button>
              <button onClick={function () { c.setState({ folderDraft: 'smart' }); c._focusRename = 'folder'; }} title="Папка по ключевым словам" className={hov('color: var(--ink)')} style={s('appearance: none; background: none; border: none; padding: 4px 6px; font-family: inherit; font-size: 9px; color: var(--muted-soft); cursor: pointer;')}>＋ умная</button>
            </div>
          )}
          {!!st.folderDraft && (
            <div style={s('padding: 0 4px 10px;')}>
              <input type="text" data-folder-input="1"
                placeholder={st.folderDraft === 'smart' ? 'ключевые слова через запятую'
                  : (c.folderParent() ? 'папка внутри «' + c.folderParent() + '»' : 'название папки')}
                ref={function (el) { c.folderInputRef(el); }}
                onKeyDown={function (e) {
                  if (e.key === 'Escape') { c.setState({ folderDraft: '' }); return; }
                  if (e.key !== 'Enter') return;
                  var v = e.target.value.trim(); if (!v) { c.setState({ folderDraft: '' }); return; }
                  if (st.folderDraft === 'smart') {
                    var keys = v.split(',').map(function (x) { return x.trim().toLowerCase(); }).filter(Boolean);
                    c.addFolder(keys.slice(0, 3).join(' · '), keys);
                  } else c.addFolder(v, null);
                }}
                onBlur={function () { c.setState({ folderDraft: '' }); }}
                style={s('width: 100%; background: transparent; border: none; border-bottom: 1px solid var(--border-soft); padding: 4px 2px; font-family: inherit; font-size: 11px; color: var(--ink);')} />
            </div>
          )}
          {sheetList.map(function (sh) {
            var active = sh.id === st.sheetId, renaming = st.renaming === sh.id;
            // счёт строк честный только у открытого: doc остальных живёт на диске
            var n = active ? c.cur().filter(function (r) { return r.type === 'line' && r.text; }).length : null;
            var meta = sh.trashed ? ((sh.days_left != null ? sh.days_left : '?') + ' дн.') : ((n != null ? n + ' стр. · ' : '') + (sh.at || ''));
            var inF = sh.folder && c.folderById(sh.folder);
            return (
              <div key={sh.id} className={hov('--sh: 1; background: color-mix(in srgb, var(--ink) 5%, transparent)')} style={s('display: flex; align-items: center; gap: 6px; border-radius: 3px; --sh: 0.55; padding: 1px 2px;')} /* --sh задаётся ЗДЕСЬ, поэтому фолбэк var(--sh, …) у кнопок недостижим:
                       менять надо это значение, а не запасное (Раунд 55, вторая попытка) */>
                {renaming && (
                  <input type="text" defaultValue={sh.title}
                    onKeyDown={function (e) { if (e.key === 'Enter') c.renameSheet(sh.id, e.target.value); if (e.key === 'Escape') c.setState({ renaming: '' }); }}
                    onBlur={function (e) { c.renameSheet(sh.id, e.target.value); }}
                    style={s('flex: 1; min-width: 0; background: transparent; border: none; border-bottom: 1px solid var(--border-soft); margin: 2px 4px; padding: 3px 2px; font-size: 11px; color: var(--ink);')} />
                )}
                {!renaming && (
                  <>
                    <button onClick={function () { c.openSheet(sh.id); }} style={s('flex: 1; min-width: 0; text-align: left; appearance: none; background: none; border: none; padding: 7px 6px; font-size: 11px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: ' + (active ? 'var(--ink)' : 'var(--muted)') + ';')}>{sh.title}</button>
                    <span style={s('font-size: 8.5px; color: var(--muted-soft); font-variant-numeric: tabular-nums; flex-shrink: 0;')}>{meta}</span>
                    {!sh.trashed && (
                      <>
                        <button onClick={function (e) { e.stopPropagation(); c.setState({ moveOpen: st.moveOpen === sh.id ? '' : sh.id }); }} title={inF ? 'папка · ' + inF.name : 'положить в папку'} style={actStyle}>↦</button>
                        <button onClick={function (e) { e.stopPropagation(); c.setState({ renaming: sh.id }); }} title="Переименовать" style={actStyle}>✎</button>
                        <button onClick={function (e) { e.stopPropagation(); c.dupSheet(sh.id); }} title="Дублировать" style={actStyle}>⧉</button>
                        <button onClick={function (e) { e.stopPropagation(); c.trashSheet(sh.id); }} title="В корзину" style={actStyle}>×</button>
                      </>
                    )}
                    {!!sh.trashed && (
                      <>
                        <button onClick={function (e) { e.stopPropagation(); c.restoreSheet(sh.id); }} title="Вернуть из корзины" style={actStyle}>
                          <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" style={s('display: block;')}><path d="M3.6 12a8.4 8.4 0 1 0 2.46-5.94"></path><polyline points="3.6 4.2 3.6 9 8.4 9"></polyline></svg>
                        </button>
                        <button onClick={function (e) { e.stopPropagation(); c.purgeSheet(sh.id); }}
                          title={st.confirm === sh.id ? 'Нажми ещё раз' : 'Удалить навсегда'}
                          style={s('appearance: none; background: none; border: none; padding: 4px 5px; font-size: ' + (st.confirm === sh.id ? '9px' : '11px') + '; cursor: pointer; flex-shrink: 0; white-space: nowrap; color: ' + (st.confirm === sh.id ? 'var(--ink)' : 'var(--muted-soft)') + '; opacity: ' + (st.confirm === sh.id ? '1' : 'var(--sh, 0.55)') + '; transition: opacity 0.12s var(--ease);')}>{st.confirm === sh.id ? 'точно?' : '⌫'}</button>
                      </>
                    )}
                  </>
                )}
                {st.moveOpen === sh.id && (
                  <div style={s('display: flex; flex-wrap: wrap; gap: 3px; padding: 2px 4px 8px 6px;')}>
                    {folders.filter(function (f) { return !f.keys; }).map(function (f) {
                      return <button key={f.id} onClick={function (e) { e.stopPropagation(); c.moveSheet(sh.id, f.id); }} style={s('appearance: none; border: none; border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: 9px; cursor: pointer; white-space: nowrap; background: color-mix(in srgb, var(--ink) 6%, transparent); color: ' + (sh.folder === f.id ? 'var(--ink)' : 'var(--muted)') + ';')}>{f.name + (sh.folder === f.id ? ' ✓' : '')}</button>;
                    })}
                    <button onClick={function (e) { e.stopPropagation(); c.moveSheet(sh.id, ''); }} style={s('appearance: none; border: none; border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: 9px; cursor: pointer; white-space: nowrap; background: none; color: var(--muted-soft);')}>без папки</button>
                  </div>
                )}
              </div>
            );
          })}
          {sheetList.length === 0 && (
            <div style={s('padding: 10px 8px 6px; font-size: 10.5px; color: var(--muted-soft);')}>{st.trashView ? 'корзина пуста' : 'нет листов'}</div>
          )}
          {st.trashView && trashN > 0 && (
            <div style={s('display: flex; justify-content: space-between; align-items: center; gap: 8px; border-top: 1px solid var(--border-subtle); margin-top: 6px; padding: 9px 8px 3px;')}>
              <span style={s('font-size: 9px; color: var(--muted-soft);')}>удаляются через 30 дней</span>
              <button onClick={function () { c.purgeAll(); }} style={s('appearance: none; background: none; border: none; padding: 0; font-size: 9px; cursor: pointer; white-space: nowrap; color: ' + (st.confirm === 'all' ? 'var(--ink)' : 'var(--muted-soft)') + ';')}>{st.confirm === 'all' ? 'точно очистить?' : 'очистить'}</button>
            </div>
          )}
          <button onClick={function () { c.newSheet(); }} className={hov('color: var(--ink)')} style={s('display: flex; align-items: center; gap: 8px; width: 100%; appearance: none; background: none; border: none; border-top: 1px solid var(--border-subtle); margin-top: 6px; padding: 9px 8px 4px; font-size: 10.5px; color: var(--muted); cursor: pointer; text-align: left;')}><span style={s('font-size: 12px;')}>＋</span>новый лист</button>
          <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 8px 2px;')}>
            <span title={vaultTitle} style={s('font-size: 9px; color: var(--muted-soft); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;')}>{vaultPath}</span>
            <button onClick={function () { c.openVault(); }} title="Показать папку в Finder" className={hov('color: var(--ink)')} style={s('appearance: none; background: none; border: none; padding: 0; font-family: inherit; font-size: 9px; color: var(--muted-soft); cursor: pointer; flex-shrink: 0;')}>открыть папку</button>
          </div>
        </div>
      )}
    </div>
  );
}

// Подсказка пустого листа (шаблон, строки 1203..1211). Живёт в области
// документа: интегратор вставляет вызов в скролл документа сразу перед
// contenteditable-полем строк. emptySheet — из renderVals (строка 3619).
export function renderEmptySheet(c) {
  var lines = c.state.doc.filter(function (r) { return r.type === 'line' && r.text; });
  if (!(lines.length <= 1 && !(lines[0] && lines[0].text))) return null;
  return (
    <div style={s('width: 100%; max-width: var(--content-max-width); display: flex; flex-direction: column; gap: 8px; padding: 28px 0 0; margin-left: 0;')}>
      <div style={s('display: flex; flex-direction: column; gap: 8px; padding-left: calc(7ch + 10px); font-size: 11px; color: var(--muted-soft); line-height: 1.6;')}>
        <span>пиши строку — или ⌘↵, чтобы сгенерировать</span>
        <span>## в начале строки — заголовок секции</span>
        <span>клик по слову — рифмы, синонимы, антонимы</span>
      </div>
    </div>
  );
}
