// nakedlunch — ТРИ МЕНЮ: строфа · пайплайн · серия (Раунд 55).
//
// Требование (2026-08-04): строфа по команде, пайплайн вручную и серия отдельной кнопкой —
// три раздельные вещи..
//
// Отсюда вся раскладка:
//
//   СТРОФА     мастерская  — делаются детали: формы и профили настроек
//   ПАЙПЛАЙН   сборка      — из готовых деталей собирается текст
//   СЕРИЯ      конвейер    — готовая сборка повторяется много раз
//
// ЗАВИСИМОСТЬ ТОЛЬКО ВПЕРЁД. Пайплайн берёт с полок, которые наполнила
// «Строфа», и сам ничего не правит. Серия берёт цепочки с полки, которую
// наполнил «Пайплайн», и сама ничего не правит. Поэтому меню не знают друг о
// друге ничего, кроме полок, — и вместе с разделением умерли выбор звена
// (openLink/selectLink), двусторонняя синхронизация редакторов со звеном, ряд
// вкладок (shelfTab) и правило «звеньев больше одного — жми другую кнопку».
//
// ЧТО БЫЛО ДО ЭТОГО (Раунд 50): всё в одном попапе, где «решение» и «цепочка»
// говорили об одном, кнопка прогона стояла через экран от цепочки, которую
// гонит, а вкладка «референс» правила всю цепочку, сидя в ряду вкладок,
// которые правят одно звено. Замечание: один попап устраивает, не устраивает расположение внутри него..

import { Fragment } from 'react';
import { s, hov } from './style.js';
import { времени, МАСТЕР, КАНАЛЫ, ФИГУРЫ, ШУМЫ } from './methods.series.js';
import { ВОРОТА, МНЕНИЯ, В_КЛАССИКЕ, РЕЖИМ_АЛГО, РЕЖИМ_КЛАССИКА, ШКАЛЫ, КЛАУЗУЛЫ, подпись, имяКрутилки }
  from './methods.shelves.js';

// ---- общие рецепты стилей --------------------------------------------------
const ЗАГОЛОВОК = 'font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--muted-soft); margin: 0 0 6px 2px;';
const РАЗДЕЛ = 'border-top: 1px solid var(--border-subtle); margin-top: 13px; padding-top: 11px;';
const ПОЛЕ = 'appearance: none; min-width: 0; background: none; border: none; border-bottom: 1px solid var(--border-subtle); padding: 3px 2px; font-family: inherit; font-size: 10px; color: var(--ink); cursor: pointer;';
const ТЕКСТ = 'appearance: none; flex: 1; min-width: 0; background: none; border: none; border-bottom: 1px solid var(--border-subtle); padding: 3px 2px; font-family: inherit; font-size: 10px; color: var(--ink);';
const СЛОВО = 'appearance: none; background: none; border: none; padding: 0; font-size: 10px; color: var(--muted); cursor: pointer; white-space: nowrap;';
const ПОЯС = 'font-size: 8.5px; color: var(--muted-soft);';
const ГЛАВНАЯ = 'appearance: none; border: none; border-radius: 3px; padding: 5px 10px; font-family: inherit; font-size: 9px; cursor: pointer; background: var(--ink); color: var(--canvas);';

// «2 звена», «5 звеньев», «21 звено» — иначе панель сама себе врёт грамматикой
function склонение(n, одно, два, много) {
  var с = n % 100, е = n % 10;
  if (с > 10 && с < 20) return n + ' ' + много;
  if (е === 1) return n + ' ' + одно;
  if (е >= 2 && е <= 4) return n + ' ' + два;
  return n + ' ' + много;
}
function звенья(n) { return склонение(n, 'звено', 'звена', 'звеньев'); }
function строки(n) { return склонение(n, 'строка', 'строки', 'строк'); }
function тексты(n) { return склонение(n, 'текст', 'текста', 'текстов'); }

function селект(value, onChange, опции, стиль) {
  return (
    <select value={value} onChange={onChange} style={s(ПОЛЕ + (стиль || ''))}>
      {опции.map(function (o, i) {
        return (<option key={i} value={o.v}>{o.n}</option>);
      })}
    </select>
  );
}

// крестик удаления — только у СВОИХ записей полки: встроенные не удаляются
function св_кнопка(c, своя, onDelete) {
  if (!своя) return null;
  return (<button onClick={onDelete} title="Удалить свою запись полки"
    style={s('appearance: none; background: none; border: none; padding: 2px 4px; font-size: 10px; color: var(--muted-soft); cursor: pointer;')}
    className={hov('color: var(--ink)')}>✕</button>);
}

// Коробка попапа — одна на все три меню: они висят под своими значками в
// шапке, и отличаться формой им незачем.
function попап(c, ключ, ширина, дети) {
  return (
    <div data-pa="down" data-po={c.state.closing === ключ ? '1' : null}
      style={s('position: absolute; top: calc(100% + 10px); right: 0; z-index: 80; width: ' + ширина + 'px; max-height: 78vh; overflow-y: auto; background: var(--menu-bg); backdrop-filter: var(--glass-fx); -webkit-backdrop-filter: var(--glass-fx-fallback); contain: paint; isolation: isolate; box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: 13px 15px; font-size: 11px; color: var(--muted);')}>
      {дети}
    </div>
  );
}

// ============================================================
// МЕНЮ 1 — СТРОФА  (⌘↵)
// ============================================================
// Мастерская. Всё, что здесь стоит, относится к ОДНОЙ строфе, которую «а к чему это относится» — ровно та путаница, которую
// разделение и убирает.

function renderFormShelf(c) {
  var st = c.state, spec = c.curSpec();
  var forms = st.stanzaForms || {};
  var все = (forms.builtin || []).concat(forms.custom || []);
  var свои = {};
  (forms.custom || []).forEach(function (f) { свои[f.name] = 1; });
  var схема = spec.map(function (l) { return l.letter; }).join('');
  var lo = spec.reduce(function (m, l) { return Math.min(m, l.min_syl); }, 99);
  var hi = spec.reduce(function (m, l) { return Math.max(m, l.max_syl); }, 0);

  return (
    <div>
      <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px;')}>
        {селект(st.stanzaProfile || '', function (e) { c.pickStanzaForm(e.target.value); },
                [{ v: '', n: 'своя форма' }].concat(все.map(function (f) { return { v: f.name, n: f.name }; })),
                ' flex: 1;')}
        {св_кнопка(c, свои[st.stanzaProfile], function () { c.deleteStanzaProfile(st.stanzaProfile); })}
      </div>
      <div style={s(ПОЯС + ' margin-bottom: 7px; font-variant-numeric: tabular-nums;')}>
        {схема} · {строки(spec.length)} · {lo}–{hi} слог</div>

      {spec.map(function (l, i) {
        return (
          <div key={i} data-row="1" style={s('display: flex; align-items: center; gap: 7px; padding: 3px 2px; min-height: 24px;')}>
            <span style={s('font-size: 9px; color: var(--muted-soft); font-variant-numeric: tabular-nums; width: 15px;')}>{String(i + 1).padStart(2, '0')}</span>
            <button onClick={function (e) { c.cycleLetter(i, e.altKey); }}
              title="клик — следующая буква рифмовки, ⌥-клик — предыдущая"
              style={s('appearance: none; border: none; border-radius: 3px; width: 21px; height: 19px; font-family: inherit; font-size: 10.5px; cursor: pointer; background: color-mix(in srgb, var(--ink) 8%, transparent); color: var(--ink);')}
              className={hov('background: color-mix(in srgb, var(--ink) 16%, transparent)')}>{l.letter}</button>
            <span style={s(ПОЯС)}>слоги</span>
            <input type="number" min="1" max="30" value={l.min_syl}
              onChange={function (e) { c.setLineSyl(i, 'min_syl', e.target.value); }}
              style={s('width: 32px; appearance: textfield; background: none; border: none; border-bottom: 1px solid var(--border-subtle); padding: 1px 2px; font-family: inherit; font-size: 10px; color: var(--ink); text-align: center; font-variant-numeric: tabular-nums;')} />
            <span style={s('color: var(--muted-soft);')}>–</span>
            <input type="number" min="1" max="30" value={l.max_syl}
              onChange={function (e) { c.setLineSyl(i, 'max_syl', e.target.value); }}
              style={s('width: 32px; appearance: textfield; background: none; border: none; border-bottom: 1px solid var(--border-subtle); padding: 1px 2px; font-family: inherit; font-size: 10px; color: var(--ink); text-align: center; font-variant-numeric: tabular-nums;')} />
            <span style={s('flex: 1;')}></span>
            <button onClick={function () { c.dropStanzaLine(i); }} title="убрать строку"
              style={s('appearance: none; background: none; border: none; padding: 2px 4px; font-size: 10px; color: var(--muted-soft); cursor: pointer;')}
              className={hov('color: var(--ink)')}>✕</button>
          </div>
        );
      })}

      <div style={s('display: flex; align-items: center; gap: 10px; padding: 6px 2px 0;')}>
        <button onClick={function () { c.addStanzaLine(); }} style={s(СЛОВО)}
          className={hov('color: var(--ink)')}>+ строка</button>
        <span style={s('flex: 1;')}></span>
        <input type="text" value={st.profNameDraft || ''} placeholder={st.stanzaProfile || 'имя формы'} spellCheck={false}
          onChange={function (e) { c.setState({ profNameDraft: e.target.value }); }}
          onKeyDown={function (e) { if (e.key === 'Enter') { e.preventDefault(); c.saveStanzaProfile(); } }}
          style={s(ТЕКСТ + ' flex: 0 1 120px;')} />
        <button onClick={function () { c.saveStanzaProfile(); }}
          style={s(СЛОВО + (st.profSaveFlash ? ' color: var(--ink);' : ''))}
          className={hov('color: var(--ink)')}>{st.profSaveFlash ? 'сохранено ✓' : 'сохранить'}</button>
      </div>
    </div>
  );
}

function renderKnobShelf(c) {
  var st = c.state;
  var классика = (st.knobMode || РЕЖИМ_АЛГО) === РЕЖИМ_КЛАССИКА;
  var все = c.allKnobForms();
  var свои = {};
  ((st.knobForms || {}).custom || []).forEach(function (f) { свои[f.name] = 1; });

  // Одна строка-крутилка. Клаузула — не проценты, а список: у неё четыре
  // именованных положения, и показывать «2.00» вместо «женская» значило бы
  // заставлять держать таблицу в голове.
  var строка = function (имя) {
    var v = st.params[имя] != null ? st.params[имя] : 0;
    var мертво = классика && В_КЛАССИКЕ.indexOf(имя) < 0;
    var шкала = ШКАЛЫ[имя] || ['', ''];
    var контрол = имя === 'Клаузула'
      ? селект(String(Math.round(v)), function (e) { c.setKnob(имя, parseInt(e.target.value, 10)); },
               КЛАУЗУЛЫ.map(function (n, i) { return { v: String(i), n: n }; }), ' width: 118px;')
      : (<input type="range"
                min={имя === 'Мат' || имя === 'Связность' ? '-1' : '0'} max="1" step="0.05"
                value={Number(v).toFixed(2)} disabled={мертво}
                onChange={function (e) { c.setKnob(имя, parseFloat(e.target.value)); }}
                style={s('width: 118px;')} />);
    return (
      <div key={имя} data-row="1" style={{
        ...s('display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 6px 10px; padding: 5px 0; min-height: 26px; transition: opacity 0.16s var(--ease);'),
        opacity: мертво ? 0.32 : 1 }}>
        <span style={s('display: flex; flex-direction: column; gap: 1px; min-width: 0;')}>
          <span style={s('font-size: 10px; color: var(--muted);')}>{имяКрутилки(имя)}</span>
          <span style={s(ПОЯС)}>{мертво ? 'в классике не действует' : шкала[0] + ' · ' + шкала[1]}</span>
        </span>
        {контрол}
        <span style={s('font-size: 9.5px; color: var(--ink); font-variant-numeric: tabular-nums; min-width: 58px; text-align: right;')}>
          {подпись(имя, v)}</span>
      </div>
    );
  };

  return (
    <div>
      <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px;')}>
        {селект(st.knobProfile || '', function (e) { c.pickKnobProfile(e.target.value); },
                все.map(function (f) { return { v: f.name, n: f.name + (f.mode === РЕЖИМ_КЛАССИКА ? ' · классика' : '') }; }),
                ' flex: 1;')}
        {св_кнопка(c, свои[st.knobProfile], function () { c.deleteKnobProfile(st.knobProfile); })}
      </div>

      {/* Бинарный переключатель. Требование: либо одно, либо другое; в классике алгоритмических оценок не существует —
      чистая нарезка.. */}
      <div style={s('display: flex; gap: 3px; margin-bottom: 4px;')}>
        {[РЕЖИМ_АЛГО, РЕЖИМ_КЛАССИКА].map(function (m) {
          var on = (st.knobMode || РЕЖИМ_АЛГО) === m;
          return (<button key={m} onClick={function () { c.setKnobMode(m); }}
            style={s('appearance: none; border: none; border-radius: 3px; padding: 4px 9px; font-family: inherit; font-size: 9px; cursor: pointer; '
              + (on ? 'background: var(--ink); color: var(--canvas);' : 'background: none; color: var(--muted-soft);'))}
            className={hov('color: var(--ink)')}>{m}</button>);
        })}
      </div>

      <div style={s(ЗАГОЛОВОК + ' margin-top: 10px;')}>ворота · действуют всегда</div>
      {ВОРОТА.map(строка)}

      <div style={s(ЗАГОЛОВОК + ' margin-top: 12px;')}>
        мнения{классика ? ' · в классике их нет' : ''}</div>
      {МНЕНИЯ.map(строка)}

      <div style={s('display: flex; align-items: center; gap: 8px; margin-top: 10px;')}>
        <input type="text" value={st.knobDraft || ''} placeholder={st.knobProfile || 'имя профиля'} spellCheck={false}
          onChange={function (e) { c.setState({ knobDraft: e.target.value }); }}
          onKeyDown={function (e) { if (e.key === 'Enter') { e.preventDefault(); c.saveKnobProfile(); } }}
          style={s(ТЕКСТ)} />
        <button onClick={function () { c.saveKnobProfile(); }}
          style={s(СЛОВО + (st.knobDirty ? ' color: var(--ink);' : ''))}
          className={hov('color: var(--ink)')}>{st.knobDirty ? 'сохранить ✱' : 'сохранить'}</button>
      </div>
    </div>
  );
}

export function renderStanzaMenu(c) {
  var st = c.state;
  return попап(c, 'stanza', 372, (
    <Fragment>
      <div style={s('display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 8px;')}>
        <span style={s(ЗАГОЛОВОК + ' margin: 0;')}>форма</span>
        <span style={s(ПОЯС)}>⌘↵</span>
      </div>
      {renderFormShelf(c)}

      <div style={s(РАЗДЕЛ)}></div>
      <div style={s(ЗАГОЛОВОК)}>настройки</div>
      {renderKnobShelf(c)}

      <div style={s(РАЗДЕЛ)}></div>
      <div style={s('display: flex; align-items: center; gap: 8px;')}>
        <span style={s('font-size: 10px; color: var(--muted);')}>заголовок</span>
        {селект(st.stanzaSection || '', function (e) { c.setState({ stanzaSection: e.target.value }); },
                [{ v: '', n: '—' }].concat(c.ROLES.map(function (r) { return { v: r, n: r }; })),
                ' width: 128px;')}
      </div>
      {/* ТЕМА — ПОЛЕ, А НЕ ВЫДЕЛЕНИЕ (Раунд 57). Выбор слов кликами прожил один
          заход и был отвергнут: «съезжает и, по-моему, темы не выбирает, да и не
          очень удобно; имеет смысл убрать это усложнение и добавить выбор тем в
          настройки строфы через запятую, как кейворды». Тема теперь ровно там,
          где остальные настройки строфы, и её видно не наводя мышь. */}
      <div style={s('display: flex; align-items: center; gap: 8px; margin-top: 8px;')}>
        <span style={s('font-size: 10px; color: var(--muted);')}>темы</span>
        <input type="text" value={st.themeKeys || ''} placeholder="через запятую"
          onChange={function (e) { c.setState({ themeKeys: e.target.value }); }}
          style={s('flex: 1; min-width: 0; background: none; border: none; border-bottom: 1px solid var(--border-subtle);'
            + ' color: var(--ink); font-family: inherit; font-size: 11px; padding: 3px 0; outline: none;')} />
      </div>
      <div style={s(ПОЯС + ' margin-top: 6px;')}>
        пусто — без темы · ⌥↵ вставить слово принудительно</div>

      <div style={s('display: flex; justify-content: flex-end; margin-top: 10px;')}>
        <button onClick={function () { c.closePop(); c.genStanza({}); }} style={s(ГЛАВНАЯ)}>
          сгенерировать ▶</button>
      </div>
    </Fragment>
  ));
}

// ============================================================
// МЕНЮ 2 — ПАЙПЛАЙН  (⌘⇧↵)
// ============================================================
// Сборка и только сборка: строка звена — это две выпадашки с полок и подпись
// секции. Ни конструкторов, ни ползунков. Новые формы и профили делаются в
// «Строфе» — направление зависимости одно и только вперёд.

function renderChain(c) {
  var st = c.state;
  var формы = ((st.stanzaForms || {}).builtin || []).concat((st.stanzaForms || {}).custom || []);
  var настройки = c.allKnobForms();
  var jname = function (i) { return (st.junctions || [])[i] || 'рифмовать стык'; };

  return (
    <div data-pop="1" style={s('display: flex; flex-direction: column; gap: 2px;')}>
      {/* ШАПКА СТРОКИ (Раунд 55, по вопросу вопрос: назначение столбца «куплет/припев» в пайплайне непонятно.). Три выпадашки стояли подряд
          без единой подписи, и первая — заголовок секции — читалась как
          настройка генерации. Она ею БЫЛА до Раунда 50: слово «Припев» тайно
          назначало форму строфы и двигало крутилки. Теперь это просто
          подпись, которая уйдёт в текст, и подпись столбца об этом говорит. */}
      <div style={s('display: grid; grid-template-columns: 14px 62px 1fr 1fr auto; gap: 4px; padding: 0 2px 3px;' + ЗАГОЛОВОК)}>
        <span></span><span>заголовок</span><span>форма</span><span>настройки</span><span></span>
      </div>
      {(st.chain || []).map(function (секция, i) {
        var повтор = c.linkRepeat(i);
        var формаИмя = (st.chainForms || [])[i] || '';
        var настрИмя = (st.chainKnobs || [])[i] || '';
        // Что звено возьмёт, если своей полки у него нет. Слепок и референс
        // несут спеку и крутилки САМИ — это не «пусто», и подписывать их как
        // «как в мастерской» значило бы врать о том, чем набирается звено.
        var реф = (st.refChain || [])[i];
        var пусто = !(реф && (реф.spec || реф.params)) ? 'как в мастерской'
          : ((st.refText || '').trim() ? 'снято по тексту' : 'из слепка');
        return (
          <Fragment key={i}>
            <div style={s('display: grid; grid-template-columns: 14px 62px 1fr 1fr auto; align-items: center; gap: 4px; padding: 2px 2px;')}>
              <span style={s('font-size: 8.5px; color: var(--muted-soft); font-variant-numeric: tabular-nums;')}>{String(i + 1).padStart(2, '0')}</span>
              {/* Секция — ПОДПИСЬ строки, а не контрол справа: цепочку сканируют
                  по словам «куплет — припев — припев — бридж», а не по именам
                  форм. Освободившееся место уходит селекту формы, и
                  «Катрен перекрёстный» перестаёт обрезаться. */}
              {селект(секция || '', function (e) { c.setChipSection(i, e.target.value); },
                      [{ v: '', n: '—' }].concat(c.ROLES.map(function (r) { return { v: r, n: r }; })),
                      ' font-size: 9px; color: var(--muted); border-bottom-color: transparent;')}
              {/* ХУК (Раунд 52): звено может быть ПОВТОРОМ более раннего — та же
                  самая строфа во второй раз. Тогда ни форма, ни настройки ему не
                  нужны: и то и другое оно берёт у двойника. Выбор повтора живёт
                  в том же селекте, что и форма: это ОДИН вопрос — «чем заполнить
                  звено». */}
              {повтор != null
                ? (<span style={s('grid-column: span 2; display: flex; align-items: center; gap: 5px;')}>
                    {селект('=' + повтор, function (e) { c.setLinkRepeat(i, e.target.value.slice(1)); },
                            [{ v: '', n: 'форма ▾' }].concat((st.chain || []).slice(0, i).map(function (_, k) {
                              return { v: '=' + k, n: '= звено ' + String(k + 1).padStart(2, '0') };
                            })))}
                    <span style={s(ПОЯС)}>та же строфа</span>
                  </span>)
                : (<Fragment>
                    {селект(формаИмя, function (e) {
                        var v = e.target.value;
                        if (v.charAt(0) === '=') { c.setLinkRepeat(i, v.slice(1)); return; }
                        c.setChipForm(i, v || null);
                      },
                      [{ v: '', n: пусто }]
                        .concat(формы.map(function (f) { return { v: f.name, n: f.name }; }))
                        .concat((st.chain || []).slice(0, i).map(function (_, k) {
                          return { v: '=' + k, n: '= звено ' + String(k + 1).padStart(2, '0') };
                        })))}
                    {селект(настрИмя, function (e) { c.setLinkKnobs(i, e.target.value || null); },
                            [{ v: '', n: пусто }].concat(настройки.map(function (f) { return { v: f.name, n: f.name }; })))}
                  </Fragment>)}
              <span style={s('display: flex; gap: 1px;')}>
                <button onClick={function () { c.moveChip(i, -1); }} title="Выше"
                  style={s('appearance: none; background: none; border: none; padding: 2px 2px; font-size: 9px; color: var(--muted-soft); cursor: pointer;')} className={hov('color: var(--ink)')}>↑</button>
                <button onClick={function () { c.moveChip(i, 1); }} title="Ниже"
                  style={s('appearance: none; background: none; border: none; padding: 2px 2px; font-size: 9px; color: var(--muted-soft); cursor: pointer;')} className={hov('color: var(--ink)')}>↓</button>
                <button onClick={function () { c.removeChip(i); }} title="Убрать звено"
                  style={s('appearance: none; background: none; border: none; padding: 2px 2px; font-size: 9px; color: var(--muted-soft); cursor: pointer;')} className={hov('color: var(--ink)')}>✕</button>
              </span>
            </div>
            {i < st.chain.length - 1 && (
              <div style={s('display: grid; grid-template-columns: 14px 1fr; align-items: center; gap: 4px; padding: 0 2px;')}>
                <span style={s('font-size: 9px; color: var(--border-soft); text-align: center;')}>│</span>
                {селект(jname(i), function (e) { c.setJunc(i, e.target.value); },
                        ['рифмовать стык', 'свободно', 'слом ритма'].map(function (j) {
                          return { v: j, n: c.JMARK[j] + '  ' + j };
                        }), ' font-size: 8.5px; color: var(--muted-soft); border-bottom-color: transparent;')}
              </div>
            )}
          </Fragment>
        );
      })}
      <button onClick={function () { c.addChip(); }}
        style={s('appearance: none; background: none; border: 1px dashed var(--border-subtle); border-radius: 3px; padding: 5px; margin-top: 4px; font-family: inherit; font-size: 9px; color: var(--muted-soft); cursor: pointer;')}
        className={hov('color: var(--ink); border-color: var(--border-soft)')}>＋ звено</button>
    </div>
  );
}

// Референс — не искажение, а ЗАМЕР: он собирает цепочку из чужого текста.
// Свёрнут в строку, потому что берутся за него редко (требование: редко используемое должно быть скрыто и открываться отдельно.).
function renderReference(c) {
  var st = c.state, проф = st.refProfile;
  var pct = st.refPct != null ? st.refPct : 1;
  // Пояснение обязано совпадать с тем, что делает refprofile.цепочка. Ниже 0.7
  // клаузула, мат и связность снимаются ЦЕЛИКОМ (у них дефолт лежит вне шкалы,
  // и «полпути к обычному» на них не существует).
  var пояс = pct >= 0.95 ? 'всё как в тексте: слоги, рифма, клаузула, мат'
    : pct >= 0.7 ? 'звук как в тексте, вилка слогов шире'
      : pct >= 0.3 ? 'каркас и рифма — клаузула, мат и связность сняты'
        : 'от текста только каркас — сколько частей и какой длины';
  var макс = Math.max(1, ...((проф && проф.части) || [{ строк: 1 }]).map(function (ч) { return ч.строк; }));

  return (
    <div style={s('margin-top: 7px;')}>
      <textarea value={st.refText || ''} placeholder="вставь свой текст — цепочка соберётся по нему" spellCheck={false}
        onChange={function (e) { c.refSoon({ refText: e.target.value }); }}
        style={s('width: 100%; height: 50px; resize: vertical; appearance: none; background: color-mix(in srgb, var(--ink) 4%, transparent); border: none; border-radius: var(--radius); padding: 7px 9px; font-family: inherit; font-size: 10px; line-height: 1.45; color: var(--ink);')} />
      {/* свой текст уже открыт в редакторе — переносить его руками незачем */}
      <button type="button" onClick={function () { c.refFromDoc(); }} title="строки открытого листа станут референсом; заголовки станут границами частей"
        style={s('appearance: none; background: none; border: none; padding: 3px 0 0; font-family: inherit; font-size: 9px; color: var(--muted-soft); cursor: pointer;')}
        className={hov('color: var(--ink)')}>взять из листа</button>
      <div style={s('display: grid; grid-template-columns: 1fr 96px auto; align-items: center; gap: 8px; margin: 7px 0 4px;')}>
        <span style={s('display: flex; flex-direction: column; gap: 1px; font-size: 10px; color: var(--muted-hard);')}>
          референтность<span style={s(ПОЯС)}>{пояс}</span>
        </span>
        <input type="range" min="0" max="1" step="0.05" value={Number(pct).toFixed(2)}
          onChange={function (e) { c.refSoon({ refPct: parseFloat(e.target.value) }); }} style={s('width: 96px; margin: 0;')} />
        <span style={s('font-size: 9px; color: ' + (st.refBusy ? 'var(--ink)' : 'var(--muted-soft)') + '; font-variant-numeric: tabular-nums; white-space: nowrap;')}>
          {st.refBusy ? 'меряю…' : Math.round(pct * 100) + '%'}</span>
      </div>
      {проф ? (
        <div style={s('margin-top: 9px;')}>
          <div style={s('display: flex; align-items: flex-end; gap: 3px; height: 26px; margin-bottom: 5px;')}>
            {(проф.части || []).map(function (ч, i) {
              return (<div key={i} title={ч.строк + ' строк · схема ' + ч.схема + ' · слогов ' + ч.слогов + '±' + ч.разброс}
                style={{ flex: 1, minWidth: '6px', height: Math.max(4, Math.round(24 * ч.строк / макс)) + 'px',
                         background: 'var(--muted-soft)', borderRadius: '1px' }}></div>);
            })}
          </div>
          <div style={s('display: grid; grid-template-columns: repeat(2, 1fr); gap: 1px 14px; font-size: 8.5px; color: var(--muted-soft); font-variant-numeric: tabular-nums;')}>
            <span>частей <span style={s('color: var(--ink);')}>{проф.частей}</span> · строк <span style={s('color: var(--ink);')}>{проф.строк}</span></span>
            <span>мат <span style={s('color: var(--ink);')}>{Math.round(проф.мат * 100)}%</span></span>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function renderPipeMenu(c) {
  var st = c.state;
  var звеньев = (st.chain || []).length;
  var цепочки = (st.chainList || []).map(function (x) { return x.name; });
  var свои = st.chainMine || [];
  var своя = свои.indexOf(st.profile) >= 0;      // ✕ только у своих: встроенные не удаляются
  // «Нет на полке» — ОТДЕЛЬНОЕ состояние, и молчать о нём нельзя (Раунд 55,
  // живой отчёт отчёт: существующие пайплайны не подтягивались в серию.).
  // Пресет и несохранённая правка выглядят как готовая цепочка, но серия
  // берёт цепочки С ПОЛКИ по имени — а на полке их нет. Раньше кнопка
  // «сохранить» в этом случае была такой же тихой, как когда всё сохранено.
  var наПолке = цепочки.indexOf(st.profile) >= 0;
  var правлено = !!st.savedSnap && c.snap() !== st.savedSnap;
  var грязно = !наПолке || правлено;
  // строк в тексте — сумма по звеньям, повтор считается наравне: он тоже
  // ложится в документ
  var строкВсего = 0;
  for (var i = 0; i < звеньев; i++) {
    var повтор = c.linkRepeat(i);
    var сп = c.linkSpec(повтор != null ? повтор : i);
    строкВсего += (сп && сп.length) || 0;
  }

  return попап(c, 'pipe', 380, (
    <Fragment>
      <div style={s('display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 8px;')}>
        <span style={s(ЗАГОЛОВОК + ' margin: 0;')}>пайплайн</span>
        <span style={s(ПОЯС)}>⌘⇧↵</span>
      </div>

      <div style={s('display: flex; align-items: center; gap: 8px;')}>
        {/* ОДИН список: встроенные и свои — записи одной полки (Раунд 55).
            Делить их на «заготовки» и «мои» я пробовала — и это было ответом
            на неверный вопрос: разница была не в природе, а в том, что
            встроенные жили во фронте и серия их не видела. Теперь не живут. */}
        <select value={st.profile || ''} onChange={function (e) { c.pickChain(e.target.value); }}
          style={s(ПОЛЕ + ' flex: 1;')}>
          <option value="">своя цепочка</option>
          {цепочки.map(function (n) { return (<option key={n} value={n}>{n}</option>); })}
        </select>
        <input type="text" value={st.chainDraft || ''} placeholder={st.profile || 'имя'} spellCheck={false}
          onChange={function (e) { c.setState({ chainDraft: e.target.value }); }}
          onKeyDown={function (e) { if (e.key === 'Enter') { e.preventDefault(); c.saveChain(); } }}
          style={s(ТЕКСТ + ' flex: 0 1 92px;')} />
        <button onClick={function () { c.saveChain(); }}
          style={s(СЛОВО + (грязно ? ' color: var(--ink);' : ''))}
          className={hov('color: var(--ink)')}>{грязно ? 'сохранить ✱' : 'сохранить'}</button>
        {своя ? св_кнопка(c, true, function () { c.deleteChain(st.profile); }) : null}
      </div>

      <div style={s('margin-top: 9px;')}>{renderChain(c)}</div>

      <button onClick={function () { c.setState({ refOpen: !st.refOpen }); }}
        style={s('appearance: none; background: none; border: none; padding: 0; margin-top: 10px; font-family: inherit; font-size: 9px; color: var(--muted-soft); cursor: pointer; display: flex; align-items: center; gap: 6px; width: 100%;')}
        className={hov('color: var(--ink)')}>
        <span>{st.refOpen ? '▾' : '▸'} собрать по тексту</span>
        <span style={s('flex: 1;')}></span>
        <span>референс</span>
      </button>
      {st.refOpen ? renderReference(c) : null}

      <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 12px;' + РАЗДЕЛ)}>
        <span style={s('font-size: 9px; color: var(--muted-soft); font-variant-numeric: tabular-nums;')}>
          {звенья(звеньев)} · {строки(строкВсего)}</span>
        <button onClick={function () { c.closePop(); c.runPipe(); }} style={s(ГЛАВНАЯ)}>прогнать ▶</button>
      </div>

      <div style={s(ПОЯС + ' margin-top: 6px;' + (наПолке ? '' : ' color: var(--muted-hard);'))}>
        {!наПолке
          ? 'этой цепочки нет на полке — сохрани её, иначе не взять в серию'
          : (правлено ? 'изменено — сохрани, иначе правка не доедет до серии'
            : 'на полке · сохраняется КОПИЕЙ, правка полок её не меняет')}</div>
      <div style={s(ПОЯС + ' margin-top: 3px;')}>
        заголовок уходит в текст подписью («## ПРИПЕВ») и на генерацию не влияет ·
        новые формы и профили — в меню «строфа»</div>

      {st.lastPipeFunnel ? (
        <div style={s('font-size: 8.5px; line-height: 1.6; color: var(--muted-soft); margin-top: 7px; font-variant-numeric: tabular-nums;')}>
          {'последний прогон: пулы ' + (st.lastPipeFunnel.pools || []).map(function (p) { return p.stanzas; }).join('+')
            + ' строф · собрано ' + (st.lastPipeFunnel.assembled || 0)
            + (st.lastPipeFunnel.elapsed_ms ? ' · ' + (st.lastPipeFunnel.elapsed_ms / 1000).toFixed(1) + ' с' : '')}
        </div>
      ) : null}
    </Fragment>
  ));
}

// ============================================================
// МЕНЮ 3 — СЕРИЯ
// ============================================================
// Конвейер. Отдельная кнопка и отдельное меню именно потому, что это автомат:
// запустил и ушёл. Ему нечего делать рядом с тем, что правят руками.

// ---- ИСКАЖЕНИЕ: кривая как в фотошопе -------------------------------------
//
// замысел: кривая работает как RGB-кривая в редакторе изображений.. Отсюда
// точки, которые таскаешь, и НЕЙТРАЛЬ, от которой отсчёт: ровная линия
// посередине не делает ничего. Поэтому отдельного ползунка «сила» тут нет —
// насколько отогнул, настолько и подействовало.
//
// Ось X — место в серии, а не входное значение: целое число это трек, дробная
// часть — его звенья. Это единственное отличие от фотошопа, и подписи треков
// под полем существуют затем, чтобы о нём не забывать.
const ХОЛСТ_В = 78;

function renderCurve(c) {
  var st = c.state;
  var канал = st.curveChan || МАСТЕР;
  var точки = c.curvePoints(канал);
  var треков = Math.max(1, (st.seriesLinks || []).length);
  var Ш = 340, В = ХОЛСТ_В;
  var вx = function (x) { return x * Ш; };
  var вy = function (y) { return В / 2 - y * (В / 2 - 4); };
  // Клик по полю ставит точку, тянешь — двигаешь, утащил ниже поля — убрал.
  var изСобытия = function (e) {
    var r = e.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
            Math.max(-1, Math.min(1, ((r.height / 2) - (e.clientY - r.top)) / (r.height / 2))),
            (e.clientY - r.top) > r.height + 14];
  };
  // Рисуем ПО САМПЛАМ той же функции, что считает бэк, а не отрезками между
  // точками: иначе на экране ломаная, а в прогоне гладкая кривая — и пользователь
  // видит не то, что получит.
  var линия = '';
  if (точки.length > 1) {
    var шагов = 120, куски = [];
    for (var k = 0; k <= шагов; k++) {
      var xx = точки[0][0] + (точки[точки.length - 1][0] - точки[0][0]) * (k / шагов);
      куски.push((k ? 'L' : 'M') + вx(xx).toFixed(1) + ' ' + вy(c.curveAt(точки, xx)).toFixed(1));
    }
    линия = куски.join(' ');
  } else if (точки.length === 1) {
    линия = 'M' + вx(точки[0][0]).toFixed(1) + ' ' + вy(точки[0][1]).toFixed(1)
          + ' L' + вx(точки[0][0]).toFixed(1) + ' ' + вy(точки[0][1]).toFixed(1);
  }
  // Края продлеваем ровно так же, как считает бэк (distort.значение): за
  // крайней точкой — её же значение. Иначе картинка обещала бы одно, а прогон
  // делал другое.
  var хвосты = точки.length
    ? 'M0 ' + вy(точки[0][1]).toFixed(1) + ' L' + вx(точки[0][0]).toFixed(1) + ' ' + вy(точки[0][1]).toFixed(1)
      + ' M' + вx(точки[точки.length - 1][0]).toFixed(1) + ' ' + вy(точки[точки.length - 1][1]).toFixed(1)
      + ' L' + Ш + ' ' + вy(точки[точки.length - 1][1]).toFixed(1)
    : '';

  return (
    <div>
      <div style={s('display: flex; align-items: center; gap: 8px; margin-bottom: 6px;')}>
        <span style={s('font-size: 9px; color: var(--muted);')}>канал</span>
        {селект(канал, function (e) { c.setState({ curveChan: e.target.value }); },
                // значение — КЛЮЧ (он в сохранённой серии), подпись — человеческая
                [{ v: МАСТЕР, n: 'все мнения' }].concat(КАНАЛЫ.map(function (n) { return { v: n, n: имяКрутилки(n) }; })),
                ' flex: 1;')}
        <button onClick={function () { c.setCurvePoints([]); }} style={s(СЛОВО)}
          className={hov('color: var(--ink)')}>сброс канала</button>
      </div>

      <svg viewBox={'0 0 ' + Ш + ' ' + В} width="100%" height={В}
        style={{ display: 'block', cursor: 'crosshair', touchAction: 'none',
                 background: 'color-mix(in srgb, var(--ink) 4%, transparent)',
                 borderRadius: 'var(--radius)' }}
        onPointerDown={function (e) {
          e.currentTarget.setPointerCapture(e.pointerId);
          var м = изСобытия(e), сп = точки.slice();
          // рядом с существующей точкой — берём её, иначе ставим новую
          var i = -1, лучш = 1;
          сп.forEach(function (п, k) { var d = Math.abs(п[0] - м[0]); if (d < лучш) { лучш = d; i = k; } });
          if (!(лучш < 0.04)) { сп.push([м[0], м[1]]); сп.sort(function (a, b) { return a[0] - b[0]; }); i = сп.indexOf(сп.filter(function (п) { return п[0] === м[0]; })[0]); }
          c._тянем = i;
          сп[i] = [м[0], м[1]];
          c.setCurvePoints(сп);
        }}
        onPointerMove={function (e) {
          if (c._тянем == null || c._тянем < 0) return;
          var м = изСобытия(e), сп = c.curvePoints(канал).slice();
          if (!сп[c._тянем]) return;
          сп[c._тянем] = [м[0], м[1]];
          c.setCurvePoints(сп);
        }}
        onPointerUp={function (e) {
          var м = изСобытия(e);
          if (м[2] && c._тянем != null && c._тянем >= 0) {     // утащил за нижний край — убрал
            var сп = c.curvePoints(канал).slice();
            сп.splice(c._тянем, 1);
            c.setCurvePoints(сп);
          }
          c._тянем = null;
        }}>
        {/* нейтраль: ровная линия посередине ничего не делает */}
        <line x1="0" y1={В / 2} x2={Ш} y2={В / 2} stroke="var(--border-subtle)" strokeWidth="1" strokeDasharray="3 4" />
        {/* границы треков — чтобы видеть, чью клетку гнёшь */}
        {Array.from({ length: треков - 1 }, function (_, i) {
          return (<line key={i} x1={(i + 1) / треков * Ш} y1="0" x2={(i + 1) / треков * Ш} y2={В}
            stroke="var(--border-subtle)" strokeWidth="1" opacity="0.6" />);
        })}
        {хвосты ? (<path d={хвосты} fill="none" stroke="var(--muted-soft)" strokeWidth="1.4" />) : null}
        {линия ? (<path d={линия} fill="none" stroke="var(--ink)" strokeWidth="1.6" />) : null}
        {точки.map(function (п, i) {
          return (<circle key={i} cx={вx(п[0])} cy={вy(п[1])} r="3.2" fill="var(--ink)" />);
        })}
      </svg>

      <div style={s('display: flex; gap: 2px; margin-top: 2px;')}>
        {(st.seriesLinks || []).map(function (l, i) {
          return (<span key={i} style={{ flex: 1, minWidth: 0, fontSize: '8px', color: 'var(--muted-soft)',
                                         whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {(i + 1) + ' ' + (l.theme || l.album || '—')}</span>);
        })}
      </div>

      <div style={s('display: flex; align-items: center; gap: 8px; margin-top: 7px;')}>
        <span style={s(ПОЯС)}>клик — точка · тяни мышью · утащил вниз — убрал</span>
        <span style={s('flex: 1;')}></span>
        {селект(st.curveShape || '', function (e) { c.putShape(e.target.value); },
                [{ v: '', n: 'фигура ▾' }].concat(Object.keys(ФИГУРЫ).map(function (n) { return { v: n, n: n }; })),
                ' width: 96px;')}
      </div>

      <div style={s(РАЗДЕЛ)}></div>
      <div style={s('display: flex; align-items: center; gap: 8px;')}>
        <span style={s('font-size: 9px; color: var(--muted);')}>шум</span>
        {селект(st.noiseKind || 'белый', function (e) { c.setState({ noiseKind: e.target.value }); },
                ШУМЫ.map(function (п) { return { v: п[0], n: п[0] }; }), ' flex: 1;')}
        <input type="range" min="0" max="1" step="0.05"
          value={Number(st.seriesNoise || 0).toFixed(2)}
          onChange={function (e) { c.setState({ seriesNoise: parseFloat(e.target.value) }); }}
          style={s('width: 88px; margin: 0;')} />
        <span style={s('font-size: 9px; color: var(--muted-soft); font-variant-numeric: tabular-nums; min-width: 26px; text-align: right;')}>
          {Number(st.seriesNoise || 0).toFixed(2)}</span>
      </div>
      {/* ПРИМЕР, а не предсказание: зерно у настоящего шума своё на каждый
          текст, и рисовать «как будет» было бы враньём. Постоянное зерно
          предпросмотра показывает ХАРАКТЕР — чем один тип отличается от
          другого, и это единственное, что тут можно сказать честно. */}
      {(function () {
        var сила = Number(st.seriesNoise || 0);
        var ряд = c.noisePreview(st.noiseKind || 'белый', 40);
        var подпись = (ШУМЫ.filter(function (п) { return п[0] === (st.noiseKind || 'белый'); })[0] || ШУМЫ[0])[1];
        return (
          <div style={s('margin-top: 6px;')}>
            <svg viewBox="0 0 340 30" width="100%" height="30" style={{ display: 'block', opacity: сила > 0 ? 1 : 0.3 }}>
              <line x1="0" y1="15" x2="340" y2="15" stroke="var(--border-subtle)" strokeWidth="1" strokeDasharray="3 4" />
              <path d={ряд.map(function (v, i) {
                return (i ? 'L' : 'M') + (i / (ряд.length - 1) * 340).toFixed(1) + ' '
                  + (15 - v * сила * 13).toFixed(1);
              }).join(' ')} fill="none" stroke="var(--muted-soft)" strokeWidth="1.3" />
            </svg>
            <div style={s(ПОЯС)}>{подпись} · пример, зерно на каждый прогон своё</div>
          </div>
        );
      })()}

      <div style={s(ПОЯС + ' margin-top: 6px;')}>
        трогает только мнения · ворота не трогает · пусто не станет<br />
        кривая — характер трека, шум — разброс между его дублями</div>
    </div>
  );
}

export function renderSeriesMenu(c) {
  var st = c.state;
  var серии = (st.seriesList || []).map(function (x) { return x.name; });
  var своя = серии.indexOf(st.seriesName) >= 0;
  var треки = st.seriesLinks || [];
  var о = c.seriesEstimate();
  var сост = st.seriesState || {};
  var цепочки = (st.chainList || []).map(function (x) { return x.name; });
  var идёт = (st.jobs || []).some(function (j) { return j.id === 'series' && j.state === 'running'; });

  return попап(c, 'series', 396, (
    <Fragment>
      <div style={s(ЗАГОЛОВОК)}>серия</div>

      <div style={s('display: flex; align-items: center; gap: 8px;')}>
        {селект(st.seriesName || '', function (e) { c.pickSeries(e.target.value); },
                [{ v: '', n: 'новая серия' }].concat(серии.map(function (n) { return { v: n, n: n }; })),
                ' flex: 1;')}
        <input type="text" value={st.seriesDraft || ''} placeholder={st.seriesName || 'имя'} spellCheck={false}
          onChange={function (e) { c.setState({ seriesDraft: e.target.value }); }}
          onKeyDown={function (e) { if (e.key === 'Enter') { e.preventDefault(); c.saveSeries(); } }}
          style={s(ТЕКСТ + ' flex: 0 1 92px;')} />
        <button onClick={function () { c.saveSeries(); }} style={s(СЛОВО)}
          className={hov('color: var(--ink)')}>сохранить</button>
        {своя ? св_кнопка(c, true, function () { c.deleteSeries(st.seriesName); }) : null}
      </div>

      <div style={s('display: grid; grid-template-columns: 1fr 1fr 1fr 28px 46px 14px 14px; gap: 4px; margin-top: 10px;' + ЗАГОЛОВОК)}>
        <span>название</span><span>тема</span><span>пайплайн</span><span>×</span>
        <span style={s('text-align: right;')}>сделано</span><span></span><span></span>
      </div>
      <div style={s('display: flex; flex-direction: column; gap: 3px;')}>
        {треки.map(function (l, i) {
          var надо = parseInt(l.count, 10) || 0;
          var есть = Math.min(надо, (сост.done || [])[i] || 0);
          var идётЭтот = сост.link === i;
          var беда = (сост.beda || {})[String(i)];
          // Знак слева от счёта: что с треком прямо сейчас. Молчание тоже
          // знак — «ещё не начинали».
          var знак = беда ? '✕' : (идётЭтот ? '▶' : (надо && есть >= надо ? '✓' : ''));
          var цвет = беда ? '#c96a6a' : (идётЭтот || (надо && есть >= надо) ? 'var(--ink)' : 'var(--muted-soft)');
          return (
            <Fragment key={i}>
              <div style={s('display: grid; grid-template-columns: 1fr 1fr 1fr 28px 46px 14px 14px; align-items: center; gap: 4px;')}>
                <input type="text" value={l.album || ''} placeholder="—" spellCheck={false}
                  onChange={function (e) { c.setSeriesLink(i, 'album', e.target.value); }}
                  style={s(ТЕКСТ + ' font-size: 9.5px;')} />
                <input type="text" value={l.theme || ''} placeholder="—" spellCheck={false}
                  onChange={function (e) { c.setSeriesLink(i, 'theme', e.target.value); }}
                  style={s(ТЕКСТ + ' font-size: 9.5px;')} />
                  {селект(l.chain || '', function (e) { c.setSeriesLink(i, 'chain', e.target.value); },
                        [{ v: '', n: цепочки.length ? '—' : 'полка пуста' }]
                          .concat(цепочки.map(function (n) { return { v: n, n: n }; })),
                        ' font-size: 9.5px;')}
                <input type="number" min="1" value={l.count || 1}
                  onChange={function (e) { c.setSeriesLink(i, 'count', e.target.value); }}
                  title="сколько претендентов на этот трек"
                  style={s(ТЕКСТ + ' font-size: 9.5px; text-align: right; font-variant-numeric: tabular-nums;')} />
                <span title={знак === '✓' ? 'трек готов' : (идётЭтот ? 'делается сейчас' : '')}
                  style={s('font-size: 9px; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; color: ' + цвет + ';')}>
                  {знак ? знак + ' ' : ''}{есть} / {надо}</span>
                <button onClick={function () { c.openSeriesFolder(i); }} title="Открыть папку трека"
                  disabled={!((сост.folders || [])[i])}
                  style={s('appearance: none; background: none; border: none; padding: 2px; font-size: 9px; cursor: pointer; color: '
                    + ((сост.folders || [])[i] ? 'var(--muted-soft)' : 'var(--border-subtle)') + ';')}
                  className={hov('color: var(--ink)')}>→</button>
                <button onClick={function () { c.removeSeriesLink(i); }} title="Убрать трек"
                  style={s('appearance: none; background: none; border: none; padding: 2px; font-size: 9px; color: var(--muted-soft); cursor: pointer;')}
                  className={hov('color: var(--ink)')}>✕</button>
              </div>
              {/* причина — ПОД СВОИМ треком, а не первыми тремя в общем хвосте:
                  иначе не понять, какой именно трек ослаблять */}
              {беда ? (<div style={s(ПОЯС + ' color: #c96a6a; padding: 0 2px 2px 2px;')}>{беда}</div>) : null}
            </Fragment>
          );
        })}
        <button onClick={function () { c.addSeriesLink(); }}
          style={s('appearance: none; background: none; border: 1px dashed var(--border-subtle); border-radius: 3px; padding: 5px; margin-top: 4px; font-family: inherit; font-size: 9px; color: var(--muted-soft); cursor: pointer;')}
          className={hov('color: var(--ink); border-color: var(--border-soft)')}>＋ трек</button>
      </div>
      {/* ЧЕСТНАЯ ПУСТОТА. Серия берёт цепочки С ПОЛКИ по имени — пресет живёт
          только в интерфейсе, и его там нет. Раньше выпадашка просто молчала
          прочерком, и отчёт: пайплайны не подтягивались, профиль серии не сохранялся.. */}
      {!цепочки.length ? (
        <div style={s(ПОЯС + ' margin-top: 6px; color: var(--muted-hard);')}>
          на полке нет ни одной цепочки — собери в меню «пайплайн» и нажми там
          «сохранить». Пресет живёт только в панели: серия берёт с полки.</div>) : null}

      {/* ЦЕНА ДО ЗАПУСКА, а не после: «тысячи претендентов на трек» — это
          семнадцать суток, и узнать об этом пользователь должен здесь. */}
      <div style={s(РАЗДЕЛ)}></div>
      <div style={s(ЗАГОЛОВОК)}>искажение</div>
      {renderCurve(c)}

      {/* ЦЕНА ОСТАТКА, а не плана: второй запуск той же серии обещал восемь
          минут там, где работы на полминуты. И кнопка называет то, что
          сделает: начатое — «продолжить». */}
      <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 12px;' + РАЗДЕЛ)}>
        <span style={s('font-size: 9px; color: var(--muted-soft); font-variant-numeric: tabular-nums;')}>
          {!о.texts ? 'план пуст'
            : (идёт ? 'идёт · ' : '') + о.done + ' из ' + о.texts
              + (о.left ? ' · осталось ' + о.left + ' ≈ ' + времени(о.seconds) : ' · план выполнен')}</span>
        {идёт
          ? (<button onClick={function () { c.stopSeries(); }}
              style={s('appearance: none; border: 1px solid var(--border-soft); border-radius: 3px; padding: 5px 10px; font-family: inherit; font-size: 9px; cursor: pointer; background: none; color: var(--ink);')}>
              остановить ■</button>)
          : (<button onClick={function () { c.runSeries(); }} disabled={!о.left}
              style={s('appearance: none; border: none; border-radius: 3px; padding: 5px 10px; font-family: inherit; font-size: 9px; cursor: ' + (о.left ? 'pointer' : 'default') + '; background: ' + (о.left ? 'var(--ink)' : 'color-mix(in srgb, var(--ink) 12%, transparent)') + '; color: ' + (о.left ? 'var(--canvas)' : 'var(--muted-soft)') + ';')}>
              {о.done ? 'продолжить ▶' : 'запустить ▶'}</button>)}
      </div>
      {/* ОТКУДА ЧИСЛО. Пока текстов не было — грубая прикидка домена; после
          первого текста — настоящий замер этой цепочки. Разница у пользователя
          вышла втрое (15 с против 41), и молчать об этом нельзя. */}
      <div style={s(ПОЯС + ' margin-top: 5px;')}>
        {(сост.measured
          ? 'по замеру этой цепочки: ' + (сост.seconds_per_text || 0) + ' с на текст'
          : 'время прикидочное — уточню по первому же тексту')}
        {' · остановить можно в любой момент, текущий текст бросится'}</div>
      <div style={s(ПОЯС + ' margin-top: 4px;')}>
        ход виден в шапке · окно должно оставаться открытым · прерванная серия
        продолжится с того же места · правка темы — это другой трек, со своей
        папкой</div>
    </Fragment>
  ));
}
