// Настройки — один попап ⚙ вместо пяти кнопок в шапке (Раунд 39).
//
// Владелец 2026-08-02: «настройки документа можно в целом в настройки
// перенести, чтоб кнопки не плодить» и «есть функции, которые просто потеряны
// и не отображаются в дизайне… нам надо до конца всё перенести».
//
// Здесь шесть разделов, и три из них — возвращённые функции, до которых из
// нового интерфейса не было пути вообще (их звал только старый App.jsx,
// живущий по адресу #old):
//   вид        — то, что было в ⚙ раньше, плюс тема (её кнопка ушла из шапки);
//   документ   — бывшая отдельная кнопка «настройки документа» + легенда;
//   корпус     — заливка книг, источники, пересборка ударений, папка;
//   история    — сроки хранения, очистка, возврат показанного в пул;
//   данные     — бэкап корпуса и выгрузка статистики;
//   статистика — бывший попап кружка: сам кружок отдан индикатору фоновых
//                работ (владелец: «progress bar, привязанный к количеству
//                источников — сколько обработано из наличествующих»).

import { Fragment } from 'react';
import { s, hov } from './style.js';
import { renderProfileRows } from './render.fspanels.jsx';
import { СРОКИ_ИСТОРИИ, СРОКИ_ПУЛА, ПЕРИОДЫ_СБРОСА } from './methods.corpus.js';

// Порядок по владельцу (Раунд 40): «настройки документа надо сделать
// первыми, настройки вида вторыми». История уехала в саму историю, данные
// и статистика — в попап статистики: выгружают они статистику, там им и место.
export const CFG_TABS = ['документ', 'вид', 'корпус'];

// строка настройки: подпись слева, ползунок или переключалка справа
export function cfgItemRow(it, key, labelStyle, showStyle) {
  return (
    <div key={key} style={s(it.rowStyle)}>
      <span style={s(labelStyle)}>{it.label}</span>
      {it.isRange && (
        <Fragment>
          <input type="range" min={it.min} max={it.max} step={it.step} value={it.val} onChange={it.onIn} style={s('width: 146px; margin: 0;')} />
          <span style={s(showStyle)}>{it.show}</span>
        </Fragment>
      )}
      {it.isPick && (
        <div style={s(it.optsStyle)}>
          {it.opts.map((o, oi) => (<button key={oi} onClick={o.onPick} style={s(o.style)}>{o.name}</button>))}
        </div>
      )}
      {it.hasHint ? (<span style={s('grid-column: 1 / -1; font-size: 9px; line-height: 1.45; color: var(--muted-soft); text-wrap: pretty;')}>{it.hint}</span>) : null}
    </div>
  );
}

const ЗАГОЛОВОК = 'font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--muted-soft); margin: 0 0 7px 2px;';
const БЛОК = 'display: flex; flex-direction: column; background: color-mix(in srgb, var(--ink) 4%, transparent); border-radius: var(--radius); overflow: hidden;';
const КНОПКА = 'appearance: none; background: none; border: 1px solid var(--border-subtle); border-radius: var(--radius); padding: 6px 10px; font-family: inherit; font-size: 10px; color: var(--muted); cursor: pointer; white-space: nowrap;';
const ССЫЛКА = 'appearance: none; background: none; border: none; padding: 0; font-family: inherit; font-size: 10px; color: var(--muted); cursor: pointer; white-space: nowrap;';
const РЯД = 'display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 7px 10px; font-size: 10.5px; color: var(--muted-hard);';
const ЧИСЛО = 'font-variant-numeric: tabular-nums; color: var(--ink);';

// Выбор из нескольких значений одной строкой — тот же вид, что у cfgPickItem,
// но данные приходят не из cfg(), а из своих роутов (сроки хранения).
function выбор(значения, текущее, onPick) {
  return (
    <div style={s('display: flex; gap: 3px; flex-wrap: wrap;')}>
      {значения.map(function (o, i) {
        var on = o.v === текущее;
        return (
          <button key={i} onClick={function () { onPick(o.v); }}
            style={s('appearance: none; border: none; border-radius: 3px; padding: 4px 7px; font-family: inherit; font-size: 9px; cursor: pointer; white-space: nowrap; '
              + (on ? 'background: var(--ink); color: var(--canvas);' : 'background: color-mix(in srgb, var(--ink) 6%, transparent); color: var(--muted);'))}>{o.name}</button>
        );
      })}
    </div>
  );
}

// Имена источников приходят с диска как «Berrouz_Golyy-zavtrak.c4tkNg.599098»:
// подчёркивания вместо пробелов и служебный хвост от nakedlunch. Показываем
// читаемое, полное оставляем подсказкой — врать про имя файла нельзя.
function имяИсточника(raw) {
  return String(raw || '')
    .replace(/[._][A-Za-z0-9]{5,}[._]\d+$/, '')     // «.c4tkNg.599098», «_CnfE0Q_706252»
    .replace(/[._][0-9a-f]{16,}$/i, '')             // голый шестнадцатеричный хвост
    .replace(/[._]+/g, ' ')
    .trim() || raw;
}

function фмт(n) {
  return String(Math.round(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

export function renderSettings(c, vals) {
  var st = c.state;
  var tab = st.cfgTab || 'вид';
  var C = c.cfg();

  var tabBtn = function (name) {
    var on = tab === name;
    return s('appearance: none; border: none; border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: 9px; cursor: pointer; white-space: nowrap; '
      + (on ? 'background: var(--ink); color: var(--canvas);' : 'background: none; color: var(--muted-soft);'));
  };

  return (
    <Fragment>
      <div style={s('display: flex; gap: 3px; flex-wrap: wrap; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border-subtle);')}>
        {CFG_TABS.map(function (name, i) {
          return (<button key={i} onClick={function () { c.setState({ cfgTab: name }); }} style={tabBtn(name)} className={hov('color: var(--ink)')}>{name}</button>);
        })}
      </div>

      {tab === 'вид' && (
        <Fragment>
          {/* тема переехала сюда из шапки: кнопка-полукруг была седьмым
              контролом в ряду, а переключают её раз в месяц */}
          <div style={s(ЗАГОЛОВОК)}>тема</div>
          <div style={s(БЛОК + ' margin-bottom: 16px;')}>
            <div style={s(РЯД)}>
              <span>оформление</span>
              {выбор([{ v: 'dark', name: 'тёмная' }, { v: 'light', name: 'светлая' }], st.theme,
                function (v) { if (v !== st.theme) c.toggleTheme(); })}
            </div>
          </div>
          {vals.cfgSections.map(function (sec, si) {
            return (
              <div key={si} style={s('margin-bottom: 16px;')}>
                <div style={s(ЗАГОЛОВОК)}>{sec.name}</div>
                <div style={s(БЛОК)}>
                  {sec.items.map(function (it, ii) {
                    return cfgItemRow(it, ii,
                      'min-width: 0; font-size: 10.5px; color: var(--muted-hard); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;',
                      'font-size: 9px; color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; min-width: 46px;');
                  })}
                </div>
              </div>
            );
          })}
          <div style={s('margin-bottom: 14px;')}>
            <div style={s('display: flex; justify-content: space-between; align-items: baseline; gap: 8px; font-size: 10.5px; color: var(--muted); margin-bottom: 6px;')}>
              <span>тон интерфейса</span><span style={s('color: var(--muted-soft); font-size: 8.5px;')}>повторный клик — свой цвет</span>
            </div>
            <div style={s('position: relative; display: flex; align-items: center; gap: 8px;')}>
              <button onClick={function () { c.setCfg('uiTint', 'нет'); }} title="По теме" style={s(vals.uiTintOffStyle)}>нет</button>
              {vals.uiTintSwatches.map(function (sw, i) { return (<button key={i} type="button" onClick={sw.onPick} title={sw.title} style={s(sw.style)}></button>); })}
              <input type="color" id="uiTintPicker" defaultValue="#2436e0" onChange={function (e) { c.setCfg('uiTint', e.target.value); }} onInput={function (e) { c.setCfg('uiTint', e.target.value); }} style={s(vals.uiTintPickerStyle)} />
            </div>
          </div>
          <div style={s('border-top: 1px solid var(--border-subtle); padding-top: 12px; margin-bottom: 12px;')}>
            <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 7px;')}>
              <span style={s(ЗАГОЛОВОК + ' margin: 0;')}>профили вида</span>
              <button onClick={function () { c.saveUiProfile(); }} className={hov('color: var(--ink)')} style={s(ССЫЛКА + ' font-size: 9px;')}>＋ сохранить</button>
            </div>
            {renderProfileRows(c.uiProfRows(), 'пусто — «сохранить» запомнит тему, шрифт, стекло и градиент')}
          </div>
          <div style={s('border-top: 1px solid var(--border-subtle); padding-top: 12px; display: flex; justify-content: flex-end;')}>
            <button onClick={function () { c.resetCfg(); }} style={s(ССЫЛКА)} className={hov('color: var(--ink)')}>сбросить всё</button>
          </div>
        </Fragment>
      )}

      {tab === 'документ' && (
        <Fragment>
          <div style={s(ЗАГОЛОВОК)}>строки</div>
          <div style={s(БЛОК)}>
            {vals.docCfgItems.map(function (it, i) {
              return cfgItemRow(it, i,
                'font-size: 10.5px; color: var(--muted-hard); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;',
                'font-size: 9px; color: var(--muted); font-variant-numeric: tabular-nums; text-align: right; min-width: 44px;');
            })}
          </div>
          <div style={s(ЗАГОЛОВОК + ' margin: 16px 0 7px 2px;')}>легенда</div>
          <div style={s('display: grid; grid-template-columns: auto 1fr; gap: 3px 10px; font-size: 9px; line-height: 1.4; color: var(--muted-soft);')}>
            {vals.legendRows.map(function (l, i) {
              return (<Fragment key={i}><span style={s('color: var(--muted); font-variant-numeric: tabular-nums;')}>{l.k}</span><span>{l.v}</span></Fragment>);
            })}
          </div>
        </Fragment>
      )}

      {tab === 'корпус' && (function () {
        var nl = st.nl || {};
        var sources = nl.sources || [];
        var активных = sources.filter(function (x) { return x.active; }).length;
        return (
          <Fragment>
            {/* Заливка книг. Роут /api/nl/source/add — единственный на
                multipart, поэтому обычный <input type=file>, а не JSON. */}
            <div style={s(ЗАГОЛОВОК)}>источники · {активных} из {sources.length} включены{(st.importing || []).length ? ' · ' + (st.importing || []).length + ' в работе' : ''}</div>
            <div style={s('display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap;')}>
              <label style={s(КНОПКА + (st.corpusBusy ? ' opacity: 0.5;' : ''))} className={hov('color: var(--ink); border-color: var(--border-soft)')}>
                ＋ залить книгу
                <input type="file" multiple accept=".txt,.md,.fb2,.epub,.html,.htm" disabled={!!st.corpusBusy}
                  onChange={function (e) { c.addBooks(e.target.files); e.target.value = ''; }}
                  style={s('display: none;')} />
              </label>
              {/* ЧЕСТНОЕ ИМЯ (Раунд 56). Кнопка называлась «пересобрать
                  ударения», хотя делает ОБЕ ступени: полный пересчёт ударений
                  и следом перепечку колоночного индекса (цепочка в server.py).
                  Владелец искал аварийный рычаг «прогнать всё заново» и не
                  находил его — при том что рычаг был вот он. */}
              <button onClick={function () { c.rebuildRhyme(); }}
                title="Полный пересчёт ударений и рифмо-ключей по всему корпусу, следом — перепечка индекса. Идёт в фоне, долго; прогресс в кружке шапки"
                style={s(КНОПКА)} className={hov('color: var(--ink); border-color: var(--border-soft)')}>прогнать всё заново</button>
              {/* Раунд 57: рядом с полным прогоном, но честно другой ценой —
                  этот проход не грузит модель ударений вовсе. */}
              <button onClick={function () { c.rebanQuality(); }}
                title="Пересчитать только качество: банальность (имена собственные больше не считаются редкими) и число знаменательных слов. Ударения и рифмо-ключи не трогаются — идёт минуты, а не час"
                style={s(КНОПКА)} className={hov('color: var(--ink); border-color: var(--border-soft)')}>пересчитать качество</button>
              <button onClick={function () { c.openCorpusDir(); }} style={s(КНОПКА)} className={hov('color: var(--ink); border-color: var(--border-soft)')}>папка</button>
              {st.corpusBusy ? (<span style={s('font-size: 9px; color: var(--ink);')}>{st.corpusBusy}</span>) : null}
            </div>

            <div style={s(БЛОК + ' margin-bottom: 12px;')}>
              {/* Книги В РАБОТЕ — сверху списка, с этапом из /api/status
                  (Раунд 56). Появляются в момент выбора файла, а не когда бэк
                  досчитает: владелец должен видеть, что нажатие сработало. */}
              {(st.importing || []).map(function (имя, k) {
                var р = (st.jobs || []).filter(function (j) { return j.id === 'import'; })[0];
                return (
                  <div key={'imp' + k} style={s('display: flex; align-items: center; gap: 8px; padding: 6px 10px; font-size: 10px; border-top: ' + (k ? '1px solid var(--border-subtle)' : 'none') + ';')}>
                    <span style={s('flex-shrink: 0; width: 8px; height: 8px; border-radius: 50%; border: 1px solid var(--ink); animation: nlGenPulse 1s var(--ease) infinite;')}></span>
                    <span style={s('flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--muted-hard);')}>{имя}</span>
                    <span style={s('flex-shrink: 0; font-size: 9px; color: var(--ink);')}>{(р && р.detail) || 'в очереди'}</span>
                  </div>
                );
              })}
              {sources.length ? sources.map(function (src, i) {
                var удаляем = st.confirm === 'src:' + src.id;
                // «Занято» — не украшение, а ответ на «сработало ли нажатие»
                // (Раунд 56): точка пульсирует, строка приглушена, второй клик
                // не проходит. См. methods.corpus.toggleSource.
                var занят = !!(st.srcBusy || {})[src.id];
                return (
                  <div key={i} style={s('display: flex; align-items: center; gap: 8px; padding: 6px 10px; font-size: 10px; border-top: ' + (i ? '1px solid var(--border-subtle)' : 'none') + ';')}>
                    <button onClick={function () { c.toggleSource(src.id); }} disabled={занят}
                      title={занят ? 'применяю…' : (src.active ? 'Включён — клик выключит' : 'Выключен — клик включит')}
                      style={s('appearance: none; flex-shrink: 0; width: 8px; height: 8px; padding: 0; border-radius: 50%; cursor: ' + (занят ? 'wait' : 'pointer') + '; border: 1px solid ' + (src.active ? 'var(--ink)' : 'var(--border-soft)') + '; background: ' + (src.active ? 'var(--ink)' : 'transparent') + ';' + (занят ? ' animation: nlGenPulse 1s var(--ease) infinite;' : ''))}></button>
                    <span title={src.name} style={s('flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: ' + (src.active ? 'var(--muted-hard)' : 'var(--muted-soft)') + ';')}>{имяИсточника(src.name)}</span>
                    {занят ? (<span style={s('flex-shrink: 0; font-size: 9px; color: var(--ink);')}>применяю…</span>) : null}
                    <span style={s('flex-shrink: 0; font-size: 9px; color: var(--muted-soft); ' + ЧИСЛО)}>{фмт(src.fragment_count)}</span>
                    {удаляем ? (
                      <Fragment>
                        <button onClick={function () { c.removeSource(src.id); }} style={s(ССЫЛКА + ' font-size: 9px; color: var(--ink);')}>удалить</button>
                        <button onClick={function () { c.setState({ confirm: '' }); }} style={s(ССЫЛКА + ' font-size: 9px;')}>нет</button>
                      </Fragment>
                    ) : (
                      <button onClick={function () { c.setState({ confirm: 'src:' + src.id }); }} disabled={занят} title="Удалить источник"
                        style={s(ССЫЛКА + ' flex-shrink: 0; font-size: 11px; color: var(--muted-soft);')} className={hov('color: var(--ink)')}>−</button>
                    )}
                  </div>
                );
              }) : (<div style={s('padding: 10px; font-size: 9px; color: var(--muted-soft);')}>пусто — «залить книгу» добавит первый источник</div>)}
            </div>

            <div style={s(БЛОК)}>
              <div style={s(РЯД)}><span>фрагментов во включённых</span><span style={s(ЧИСЛО)}>{фмт(nl.pool_total)}</span></div>
              <div style={s(РЯД + ' border-top: 1px solid var(--border-subtle);')}><span>ещё не показано</span><span style={s(ЧИСЛО)}>{фмт(nl.pool_available)}</span></div>
            </div>
          </Fragment>
        );
      })()}

    </Fragment>
  );
}
