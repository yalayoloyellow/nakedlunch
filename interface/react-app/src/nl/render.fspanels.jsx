// Панели фристайла из дизайна «Editor First» (project-notes/mockups/design-v2/
// Editor First.dc.html: шаблон 164..807, renderVals 3486..3956) — перенос 1:1.
//   renderFsBar(c)      — весь фристайл-блок шапки: микрофон, трек, авто/дальше,
//                         кнопка строки, кнопка сцены, профили сцены, формат
//                         кадра, запись; внутрь вложены обе панели;
//   renderFsLinePanel(c)— панель «строка»: режим, крутилки, источник, подача;
//   renderFsSetPanel(c) — панель «сцена»: камера · пресет · фон · текст · пост.
//
// Отличия от дизайна — только уже принятые решения и честные заглушки:
//   - ЗАПИСЬ (фаза 4): кнопка на месте и по дизайну, но неактивная, подпись
//     честная («запись — фаза 4»); MediaRecorder не трогается, на диск ничего;
//   - крутилок ПЯТЬ, «Метр» удалён (решение прожарки 5, см. methods.panels.js);
//   - блок «Онегинская строфа · абабввггдееджж» — не текст макета, а реальная
//     форма из /api/stanza/profiles (моки дизайна не переносятся, фаза 0);
//   - каталог пресетов дизайн наполнял императивно (#presetPanel + support.js);
//     здесь строки рисует React по данным движка (c.fsEngine), но КЛАССЫ И ID
//     сохранены дословно — на них держатся CSS (style.js) и механизм профилей
//     (pickPreset/curPreset ищут .presetRow/.presetName и жмут #tabAll);
//   - у пипетки свечения в макете id="glowColor", а palInput/onCardInput ищут
//     'glowColorPicker' — из-за расхождения нативный спектр свечения не
//     открывался вовсе. Берём id, который ищет логика;
//   - textarea/поля дизайна с defaultValue сделаны управляемыми (value+onChange):
//     иначе загрузка файла-источника меняет состояние, а поле остаётся старым.
//     Ручки ДВИЖКА (id + defaultValue + [data-val-for]) остаются
//     неуправляемыми — их читает engineControls() прямо из DOM.

import { Fragment } from 'react';
import { s, hov } from './style.js';
import { icoBtn } from './icons.js';
import { pickStyle, PARAM_DEFAULTS } from './methods.panels.js';
import { ВОРОТА, МНЕНИЯ, В_КЛАССИКЕ, ШКАЛЫ, подпись, имяКрутилки } from './methods.shelves.js';
import { BLENDS, BLEND_DEF } from './methods.fsglue.js';

// ---- рецепты стилей (renderVals 3395..3607) ----
const ROW = 'display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px 12px; padding: 9px 0; min-height: 34px;';
const CAP = 'font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--muted-soft); margin: 0 0 6px 2px;';
const CAP2 = 'font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--muted-soft); margin: 16px 0 6px 2px;';
const BOX = 'display: flex; flex-direction: column; border: 1px solid var(--border-subtle); border-radius: var(--radius); padding: 2px 12px;';
const LBL = 'font-size: 10.5px; color: var(--muted);';
const SUB = 'font-size: 8.5px; color: var(--muted-soft);';
const CTL = 'display: flex; align-items: center; gap: 9px;';
const VAL = 'font-size: 10.5px; color: var(--ink); font-variant-numeric: tabular-nums; min-width: 34px; text-align: right;';
const PICKS = 'display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end;';
const SEL = 'appearance: none; width: 146px; max-width: 146px; border: none; border-radius: 3px; padding: 5px 20px 5px 7px; font-family: inherit; font-size: 9px; cursor: pointer; background-color: color-mix(in srgb, var(--ink) 7%, transparent); color: var(--muted);';
const SEARCH = 'flex: 1; min-width: 0; appearance: none; border: none; border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: 10.5px; background: color-mix(in srgb, var(--ink) 6%, transparent); color: var(--ink); outline: none;';
const MINI = 'appearance: none; border: none; border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: 9px; cursor: pointer; white-space: nowrap; background: color-mix(in srgb, var(--ink) 7%, transparent); color: var(--muted);';
const HOVINK = 'color: var(--ink)';

// кнопка-тумблер внутри окна настроек (renderVals 3603)
const winBtn = (on) => 'appearance: none; border: none; border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: 9px; cursor: pointer; white-space: nowrap; ' + (on ? 'background: var(--ink); color: var(--canvas);' : 'background: color-mix(in srgb, var(--ink) 7%, transparent); color: var(--muted);');
// значок хрома (renderVals 3507) и док фристайла (3606): рамку несёт только фрейм
const hudBtn = (on) => icoBtn(on ? 'var(--ink)' : 'var(--muted-soft)');
const fsBtn = (on, rec) => icoBtn(rec && on ? '#ff453a' : (on ? 'var(--ink)' : 'var(--muted-soft)'));
// окна сцены и строки — одна и та же панель, отличается только содержимым (3519)
const fsPanel = (open) => 'position: absolute; top: calc(100% + 6px); left: 32px; right: auto; z-index: 80; width: 386px; max-height: 66vh; overflow-y: auto;'
  + ' background: var(--menu-bg); backdrop-filter: var(--glass-fx); -webkit-backdrop-filter: var(--glass-fx-fallback); contain: paint; isolation: isolate;'
  + ' box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: 14px 16px; display: ' + (open ? 'block' : 'none') + ';';
// меню в шапке фристайла (профили, формат кадра) — рецепт renderVals 3757/3818
const menuBox = (open, w, disp) => 'position: absolute; top: calc(100% + 6px); left: 32px; z-index: 80; width: ' + w + 'px; max-height: 56vh; overflow-y: auto;'
  + ' background: var(--menu-bg); backdrop-filter: var(--glass-fx); -webkit-backdrop-filter: var(--glass-fx-fallback); contain: paint; isolation: isolate;'
  + ' box-shadow: 0 14px 34px -22px rgba(0,0,0,0.45); border-radius: var(--radius); padding: ' + (disp === 'flex' ? '6px' : '10px') + '; display: ' + (open ? disp : 'none') + ';'
  + (disp === 'flex' ? ' flex-direction: column; gap: 1px;' : '');

const SIZES = [24, 32, 40, 48, 64, 80, 96, 116, 140, 180, 220];
const POSY = { 'сверху': 'flex-start', 'по центру': 'center', 'снизу': 'flex-end' };
const POSN = { 'слева': 'flex-start', 'по центру': 'center', 'справа': 'flex-end' };

// ---- кирпичики строк настроек ----

// одна настройка — одна строка: подпись слева, контрол справа, единая высота
function Row({ label, sub, children }) {
  return (
    <div data-row="1" style={s(ROW)}>
      {sub == null
        ? <span style={s(LBL)}>{label}</span>
        : <span style={s('display: flex; flex-direction: column; gap: 2px; min-width: 0;')}>
            <span style={s(LBL)}>{label}</span><span style={s(SUB)}>{sub}</span>
          </span>}
      {children}
    </div>
  );
}

// ползунок ДВИЖКА: неуправляемый, значение живёт в DOM (его читает
// engineControls), подпись обновляет onCardInput через [data-val-for]
function EngRange({ id, valId, min, max, step, def, show, suffix }) {
  return (
    <span style={s(CTL)}>
      <input type="range" id={id} min={min} max={max} step={step} defaultValue={def} style={s('width: 146px;')} />
      <span id={valId} data-val-for={id} data-val-suffix={suffix} style={s(VAL)}>{show}</span>
    </span>
  );
}

// свой ползунок: значение в state.fsv, показ считает renderVals
function MyRange({ min, max, step, value, onIn, show, wrap }) {
  return (
    <span style={s(CTL + (wrap || ''))}>
      <input type="range" min={min} max={max} step={step} value={value} onChange={onIn} style={s('width: 146px;')} />
      <span style={s(VAL)}>{show}</span>
    </span>
  );
}

// ряд кнопок-вариантов (pickStyle) — «кадрирование», «подложка», «тон» и т.п.
function Picks({ items }) {
  return (
    <span style={s(PICKS)}>
      {items.map(function (m, i) {
        return <button key={i} type="button" onClick={m.onPick} style={s(m.style)}>{m.name}</button>;
      })}
    </span>
  );
}

// строка из cfgNumItem/cfgPickItem (sceneBgCfg / sceneTextCfg)
function CfgRow({ it }) {
  return (
    <Row label={it.label}>
      <span style={s(CTL)}>
        {it.isRange ? <input type="range" min={it.min} max={it.max} step={it.step} value={it.val} onChange={it.onIn} style={s('margin: 0;')} /> : null}
        {it.isPick ? <Picks items={it.opts} /> : null}
        <span style={s(VAL)}>{it.show}</span>
      </span>
    </Row>
  );
}

// кружки палитры (renderVals 3489..3503): клик — выбор, повторный — свой цвет
function palRow(c, kind, pal, palSel) {
  return (pal[kind] || []).map(function (hex, i) {
    var on = palSel[kind] === i;
    return {
      hex: hex,
      title: on ? hex + ' · клик — свой цвет' : hex,
      style: 'appearance: none; flex-shrink: 0; width: 20px; height: 20px; padding: 0; border-radius: 50%; border: 1px solid var(--border-soft); cursor: pointer; background: ' + hex + ';' + (on ? ' box-shadow: 0 0 0 2px var(--ink);' : ''),
      onPick: function () { c.pickPal(kind, i); }
    };
  });
}
// нативный спектр держим прозрачным под выбранным кружком: скрытому showPicker() не открыть
function palPicker(palSel, kind, shift) {
  var i = palSel[kind] || 0;
  return 'position: absolute; left: ' + (i * 27 + (shift ? 44 : 0)) + 'px; top: 0; width: 20px; height: 20px; padding: 0; border: none; opacity: 0; pointer-events: none; background: none;';
}
function Swatches({ items }) {
  return (
    <Fragment>
      {items.map(function (sw, i) {
        return <button key={i} type="button" onClick={sw.onPick} title={sw.title} style={s(sw.style)}></button>;
      })}
    </Fragment>
  );
}

// общие вычислялки: миксины сцены и движка приезжают своими модулями, до тех
// пор панель обязана рисоваться, а не падать
function fsvOf(c) { return function (k) { return c.fsv ? c.fsv(k) : ((c.FS_DEF || {})[k] || 0); }; }
function slOf(c) { return function (k) { return function (e) { if (c.setFsv) c.setFsv(k, parseFloat(e.target.value)); }; }; }
function call(c, name, arg) { if (typeof c[name] === 'function') return c[name](arg); }

// ===========================================================================
// ПАНЕЛЬ «СЦЕНА» — шаблон 323..766
// ===========================================================================
export function renderFsSetPanel(c) {
  var st = c.state;
  var fsv = fsvOf(c), mySl = slOf(c);
  var pal = st.pal || c.loadPal(), palSel = st.palSel || {};
  var sec = function (k) { return (st.fsTab || 'cam') === k ? '' : 'display: none;'; };
  var tabs = [['cam', 'камера'], ['preset', 'пресет'], ['bg', 'фон'], ['text', 'текст'], ['post', 'пост']];
  var C = c.cfg();
  var fsSize = Math.max(12, Math.min(400, parseFloat(C.fsSize) || 48));
  var sizeSel = String(SIZES.indexOf(fsSize) >= 0 ? fsSize : 0);
  var posX = st.posX || 'по центру', posY = st.posY || 'по центру';
  var camBlends = c.CAM_BLENDS || [];
  var grainBlends = camBlends.concat(['overlay']).filter(function (b, i, a) { return a.indexOf(b) === i; });
  var grainFps = c.GRAIN_FPS || [];

  // темп авто-перехода: подпись — реальный период, не «сырое» значение ползунка
  var acShow = (function () {
    var ms = c.acPeriod ? c.acPeriod() : 0;
    return ms >= 1000 ? (ms / 1000).toFixed(ms >= 10000 ? 0 : 1) + ' с' : ms + ' мс';
  })();
  var acMode = st.acMode || 'выкл';
  var acHint = acMode === 'звук' ? 'цвет меняется на пиках громкости — микрофон или трек'
    : (acMode === 'время' ? 'цвет идёт по палитре с заданным темпом' : 'переход выключен');

  // положение строки: сетка 3×3 (renderVals 3727..3741)
  var posCells = [];
  ['сверху', 'по центру', 'снизу'].forEach(function (y) {
    ['слева', 'по центру', 'справа'].forEach(function (x) {
      var on = posX === x && posY === y;
      posCells.push({
        title: y + ' · ' + x,
        style: 'appearance: none; border: none; border-radius: 3px; padding: 0; height: 26px; display: flex; align-items: ' + POSY[y] + '; justify-content: ' + POSN[x] + '; cursor: pointer; background: ' + (on ? 'color-mix(in srgb, var(--ink) 14%, transparent)' : 'color-mix(in srgb, var(--ink) 5%, transparent)') + ';',
        dotStyle: 'display: block; width: 9px; height: 2px; margin: 5px; border-radius: 1px; background: ' + (on ? 'var(--ink)' : 'var(--muted-soft)') + ';',
        onPick: function () { c.setState({ posX: x, posY: y }, function () { call(c, 'fitLine'); }); }
      });
    });
  });

  var mk = function (list, cur, set) {
    return list.map(function (m) { return { name: m, style: pickStyle(cur === m), onPick: function () { set(m); } }; });
  };
  var camFits = mk(['заполнить', 'вписать', 'растянуть'], st.camFit || 'заполнить', function (m) { c.setState({ camFit: m }); });
  var selModes = mk(['нет', 'белая', 'чёрная', 'плашка'], st.selMode || 'нет', function (m) {
    c.setState({ selMode: m }, function () { call(c, 'paintBand'); call(c, 'fitLine'); });
  });
  var glowWarpModes = mk(['чисто', 'следует'], st.glowWarp || 'чисто', function (m) { c.setState({ glowWarp: m }); });
  var acModes = mk(['выкл', 'время', 'звук'], acMode, function (m) { c.setState({ acMode: m }, function () { call(c, 'autoColorLoop'); }); });
  var grainModes = mk(['плёнка', 'уголь', 'цифра'], st.grainMode || 'плёнка', function (m) {
    c.setState({ grainMode: m }, function () { call(c, 'pushScene'); });
  });

  // гарнитуры: список отдаёт сцена (state.fonts), выбор — c.pickFont
  var fontQ = (st.fontQ || '').trim().toLowerCase();
  var fontList = (st.fonts || []).filter(function (fo) { return !fontQ || fo.n.toLowerCase().indexOf(fontQ) >= 0; }).map(function (fo) {
    var on = st.fontNow === fo.v;
    return {
      name: fo.n,
      style: 'appearance: none; border: none; border-radius: 3px; padding: 0 8px; height: 27px; flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 10px; overflow: hidden; cursor: pointer; text-align: left; background: ' + (on ? 'color-mix(in srgb, var(--ink) 10%, transparent)' : 'transparent') + ';',
      nameStyle: 'font-family: inherit; font-size: 10.5px; line-height: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: ' + (on ? 'var(--ink)' : 'var(--muted)') + ';',
      sampleStyle: 'flex: 0 0 auto; font-family: ' + fo.v + ', sans-serif; font-size: 13px; line-height: 1; white-space: nowrap; color: ' + (on ? 'var(--ink)' : 'var(--muted-soft)') + ';',
      onPick: function () { call(c, 'pickFont', fo.v); }
    };
  });

  // Каталог пресетов: данные у движка, разметка и классы — дизайна.
  // Строки строим ТОЛЬКО когда вкладка каталога видна: пресетов 455, а панель
  // смонтирована всегда (сцена живёт вне вкладки), и держать их в DOM на каждом
  // рендере редактора — платить за то, чего никто не видит. Профили от списка
  // больше не зависят: pickPreset/curPreset спрашивают сам движок
  var eng = c.fsEngine || null;
  var presetTab = st.presetTab || 'all', presetQ = st.presetQ || '';
  var presetRows = [];
  var presetsShown = !!st.fsSetOpen && (st.fsTab || 'cam') === 'preset';
  if (presetsShown && eng && typeof eng.presets === 'function') {
    var q = presetQ.trim().toLowerCase();
    var cur = typeof eng.current === 'function' ? eng.current() : '';
    presetRows = (eng.presets() || []).filter(function (p) {
      if (presetTab === 'fav' && !p.fav) return false;
      if (presetTab === 'recent' && !p.recent) return false;
      return !q || String(p.name).toLowerCase().indexOf(q) >= 0;
    }).map(function (p) { return { name: p.name, tag: p.tag || '', fav: !!p.fav, current: p.name === cur }; });
  }

  var swPanel = palRow(c, 'panel', pal, palSel);
  var swInk = palRow(c, 'ink', pal, palSel);
  var swGlow = palRow(c, 'glow', pal, palSel);

  // ref через fsRef: cardsRef — метод прототипа, а не стрелка дизайна;
  // передать его напрямую значит потерять this (и кэш ref'а)
  return (
    <div id="fsSetPanel" ref={c.fsRef('cardsRef')} onInput={(e) => call(c, 'onCardInput', e)}
      data-pa="down" data-po={st.closing === 'fsset' ? '1' : null} style={s(fsPanel(st.fsSetOpen))}>

      <nav style={s('display: flex; gap: 4px; margin-bottom: 13px;')}>
        {tabs.map(function (t) {
          return <button key={t[0]} type="button" onClick={() => c.setState({ fsTab: t[0] })}
            style={s(pickStyle((st.fsTab || 'cam') === t[0]))}>{t[1]}</button>;
        })}
      </nav>

      {/* ---- камера ---- */}
      <div style={s(sec('cam'))}>
        <div style={s(CAP)}>камера</div>
        <div style={s(BOX)}>
          <Row label="захват">
            <button type="button" onClick={() => (st.camOn ? call(c, 'camStop') : call(c, 'camStart'))} style={s(winBtn(st.camOn))}>
              {st.camOn ? 'включена' : (st.camErr ? 'нет доступа' : 'выключена')}
            </button>
          </Row>
          <Row label="устройство">
            <select value={st.camId || ''} onChange={(e) => c.setState({ camId: e.target.value }, function () { if (c.state.camOn) call(c, 'camStart'); })} style={s(SEL)}>
              {((st.camList || []).length ? st.camList : [{ id: '', name: 'по умолчанию' }]).map(function (cam) {
                return <option key={cam.id} value={cam.id}>{cam.name}</option>;
              })}
            </select>
          </Row>
          <Row label="плотность"><MyRange min="0" max="100" step="5" value={String(fsv('camOp'))} onIn={mySl('camOp')} show={fsv('camOp') + '%'} /></Row>
          <Row label="наложение">
            <select value={st.camBlend || 'normal'} onChange={(e) => c.setState({ camBlend: e.target.value })} style={s(SEL)}>
              {camBlends.map(function (b) { return <option key={b} value={b}>{b}</option>; })}
            </select>
          </Row>
          <Row label="тильт ↔"><MyRange min="50" max="1000" step="5" value={String(fsv('camTiltH'))} onIn={mySl('camTiltH')} show={fsv('camTiltH') + '%'} /></Row>
          <Row label="тильт ↕"><MyRange min="50" max="1000" step="5" value={String(fsv('camTiltV'))} onIn={mySl('camTiltV')} show={fsv('camTiltV') + '%'} /></Row>
          <Row label="кадрирование"><Picks items={camFits} /></Row>
          <Row label="зеркало">
            <button type="button" onClick={() => c.setState({ camMirror: !st.camMirror })} style={s(winBtn(st.camMirror))}>{st.camMirror ? 'вкл' : 'выкл'}</button>
          </Row>
        </div>
      </div>

      {/* ---- пресет ---- */}
      <div style={s(sec('preset'))}>
        <div style={s(CAP)}>визуализатор</div>
        <div style={s(BOX)}>
          <Row label="визуализация">
            <button type="button" onClick={() => call(c, 'fsTog', 'bcOn')} style={s(winBtn(st.bcOn))}>{st.bcOn ? 'включена' : 'выключена'}</button>
          </Row>
          <Row label="автосмена строки">
            <button type="button" onClick={() => call(c, 'fsTog', 'autoOn')} style={s(winBtn(st.autoOn))}>{st.autoOn ? 'авто: вкл' : 'авто: выкл'}</button>
          </Row>
          <CfgRow it={c.cfgNumItem('fsBcOpacity', 'плотность', 0, 100, 5, 100, '%')} />
          <CfgRow it={c.cfgNumItem('fsGain', 'трек', 0, 100, 5, 80, '%')} />
          <Row label="ореол"><EngRange id="bloomSlider" min="0" max="100" def="45" show="45" /></Row>
          <Row label="экспозиция"><MyRange min="40" max="300" step="5" value={String(fsv('expoBc'))} onIn={mySl('expoBc')} show={fsv('expoBc') + '%'} /></Row>
          <Row label="рендер"><EngRange id="bcRenderScaleSlider" valId="bcRenderScaleVal" min="25" max="150" step="5" def="70" show="70%" suffix="%" /></Row>
        </div>

        <div style={s(CAP2)}>пресет</div>
        <div style={s('display: flex; flex-direction: column; gap: 8px;')}>
          <div style={s('display: flex; align-items: center; gap: 8px;')}>
            <input type="text" id="presetSearch" placeholder="поиск" spellCheck="false" value={presetQ}
              onChange={(e) => c.setState({ presetQ: e.target.value })} style={s(SEARCH)} />
            {/* хук движка из дизайна — на него вешаются внешние вызовы выбора */}
            <button type="button" id="fsPresetTrigger" style={s('display: none;')}><span id="fsPresetTriggerLabel"></span></button>
            <button type="button" id="btnRandomPreset" onClick={() => eng && eng.random && eng.random()} className={hov(HOVINK)} style={s(MINI)}>случайный</button>
          </div>
          <div style={s('display: flex; gap: 4px; flex-wrap: wrap;')}>
            {[['all', 'все', 'tabAll'], ['fav', 'избранное', 'tabFav'], ['recent', 'недавние', 'tabRecent']].map(function (t) {
              // .active — тот же класс, которым метил свои тумблеры движок:
              // подсветку уже рисует правило #fsSetPanel button.active (style.js)
              return <button key={t[0]} type="button" id={t[2]} className={(presetTab === t[0] ? 'active ' : '') + hov(HOVINK)}
                onClick={() => c.setState({ presetTab: t[0] })} style={s(MINI)}>{t[1]}</button>;
            })}
            <button type="button" id="tabTogglePanel" aria-hidden="true" tabIndex={-1} style={s('display: none;')}></button>
          </div>
          <div id="presetPanel">
            {presetRows.map(function (p) {
              return (
                <div key={p.name} className={'presetRow' + (p.current ? ' current' : '')}>
                  <button type="button" className={'presetStar' + (p.fav ? ' on' : '')} title="в избранное"
                    onClick={() => eng && eng.toggleFav && eng.toggleFav(p.name)}>★</button>
                  <div className="presetName" onClick={() => eng && eng.pick && eng.pick(p.name)}>{p.name}</div>
                  {p.tag ? <span className="presetTag">{p.tag}</span> : null}
                </div>
              );
            })}
            {presetRows.length ? null
              : <div style={s('font-size: 9px; line-height: 1.5; color: var(--muted-soft); padding: 4px 5px;')}>{eng ? 'ничего не нашлось' : 'движок ещё не загружен'}</div>}
          </div>
          <div style={s('display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 8px 12px; border-top: 1px solid var(--border-subtle); padding-top: 9px;')}>
            <span style={s(LBL)}>автосмена пресетов</span>
            <button type="button" onClick={() => c.setState({ bcAutoOn: !st.bcAutoOn }, function () { call(c, 'bcAutoLoop'); })}
              className={hov(HOVINK)} style={s(winBtn(!!st.bcAutoOn))}>{st.bcAutoOn ? 'вкл' : 'выкл'}</button>
            <span style={s(LBL)}>период</span>
            <span style={s(CTL)}>
              <input type="range" min="5" max="180" step="5" value={st.bcAutoSec || 30}
                onChange={(e) => c.setState({ bcAutoSec: parseInt(e.target.value, 10) || 30 }, function () { call(c, 'bcAutoLoop'); })} style={s('width: 146px;')} />
              <span style={s(VAL)}>{(st.bcAutoSec || 30) + ' с'}</span>
            </span>
          </div>
        </div>
      </div>

      {/* ---- фон ---- */}
      <div style={s(sec('bg'))}>
        <div style={s(CAP)}>фон</div>
        <div style={s(BOX)}>
          <Row label="блюр"><EngRange id="bgBlurSlider" min="0" max="100" def="0" show="0" /></Row>
          <Row label="наплыв"><MyRange min="0" max="100" step="1" value={String(fsv('grad'))} onIn={mySl('grad')} show={fsv('grad') + '%'} /></Row>
          <Row label="экспозиция"><MyRange min="40" max="300" step="5" value={String(fsv('expoBg'))} onIn={mySl('expoBg')} show={fsv('expoBg') + '%'} /></Row>
        </div>

        <div style={s(CAP2)}>плашка</div>
        <div style={s(BOX)}>
          <Row label="палитра" sub="повторный клик — свой цвет">
            <div style={s('position: relative; display: flex; align-items: center; gap: 8px;')}>
              <Swatches items={swPanel} />
              <input type="color" id="panelColorPicker" defaultValue="#2436e0" style={s(palPicker(palSel, 'panel'))} />
              {/* журнал недавних цветов движка — заполняет он сам */}
              <div id="palette" style={s('display: none;')}></div>
            </div>
          </Row>
          <Row label="режим">
            {/* список режимов наложения в дизайне наполнял внешний движок;
                теперь это константа связки (methods.fsglue.js), а сам select
                остаётся неуправляемым — его читает engineControls() */}
            <select id="blendSelect" defaultValue={BLEND_DEF} style={s(SEL)}>
              {BLENDS.map(function (b) { return <option key={b[0]} value={b[0]}>{b[1]}</option>; })}
            </select>
          </Row>
          <Row label="плотность"><EngRange id="panelOpacitySlider" min="0" max="100" def="85" show="85%" suffix="%" /></Row>
          <Row label="насыщенность"><MyRange min="0" max="300" step="5" value={String(fsv('sat'))} onIn={mySl('sat')} show={fsv('sat') + '%'} /></Row>
          <Row label="контраст"><MyRange min="50" max="300" step="5" value={String(fsv('con'))} onIn={mySl('con')} show={fsv('con') + '%'} /></Row>
        </div>

        <div style={s(CAP2)}>авто-переход</div>
        <div style={s(BOX)}>
          <Row label="источник"><Picks items={acModes} /></Row>
          <Row label="темп"><MyRange min="1" max="100" step="1" value={String(fsv('acSpeed'))} onIn={mySl('acSpeed')} show={acShow} /></Row>
          <Row label="плавность"><MyRange min="0" max="100" step="1" value={String(fsv('acEase'))} onIn={mySl('acEase')} show={fsv('acEase') === 0 ? 'резко' : fsv('acEase') + '%'} /></Row>
          <div data-row="1" style={s('padding: 9px 0;')}>
            <span style={s('font-size: 8.5px; line-height: 1.5; color: var(--muted-soft);')}>{acHint}</span>
          </div>
          <button type="button" id="btnAutoColor" aria-hidden="true" tabIndex={-1} style={s('display: none;')}></button>
        </div>
      </div>

      {/* ---- текст ---- */}
      <div style={s(sec('text'))}>
        <div style={s(CAP)}>текст</div>
        <div style={s(BOX)}>
          <Row label="цвет" sub="повторный клик — свой цвет">
            <div style={s('position: relative; display: flex; align-items: center; gap: 8px;')}>
              <Swatches items={swInk} />
              <input type="color" id="inkColor" defaultValue="#ffffff" style={s(palPicker(palSel, 'ink'))} />
              <div id="inkRecentSwatches" style={s('display: none;')}></div>
            </div>
          </Row>
          <Row label="кегль">
            <span style={s('display: flex; align-items: center; gap: 8px;')}>
              <select value={sizeSel}
                onChange={(e) => { var v = parseFloat(e.target.value); if (v) c.setCfg('fsSize', v); }}
                style={s('appearance: none; width: 88px; border: none; border-radius: 3px; padding: 5px 20px 5px 7px; font-family: inherit; font-size: 9px; cursor: pointer; background-color: color-mix(in srgb, var(--ink) 7%, transparent); color: var(--muted);')}>
                <option value="0">свой</option>
                {SIZES.map(function (z) { return <option key={z} value={String(z)}>{z + 'px'}</option>; })}
              </select>
              {/* поле неуправляемое: у управляемого зажим Math.max(12,…) из макета
                  срабатывал бы на каждой цифре и «150» набрать было бы нельзя.
                  key = выбор из списка: смена кегля списком перемонтирует поле,
                  свой кегль (в списке его нет) печатается спокойно */}
              <input key={sizeSel} type="number" min="12" max="400" step="1" defaultValue={String(fsSize)}
                onChange={(e) => { var v = parseFloat(e.target.value); if (!isNaN(v) && v >= 12 && v <= 400) c.setCfg('fsSize', v); }}
                style={s('width: 50px; appearance: none; border: none; border-radius: 3px; padding: 5px 6px; font-family: inherit; font-size: 9px; background: color-mix(in srgb, var(--ink) 6%, transparent); color: var(--ink); outline: none; text-align: right;')} />
            </span>
          </Row>
          <Row label="положение" sub={posY + ' · ' + posX}>
            <span style={s('display: grid; grid-template-columns: repeat(3, 1fr); gap: 3px; width: 108px;')}>
              {posCells.map(function (cell, i) {
                return <button key={i} type="button" onClick={cell.onPick} title={cell.title} style={s(cell.style)}><span style={s(cell.dotStyle)}></span></button>;
              })}
            </span>
          </Row>
          <Row label="тильт ↔"><MyRange min="50" max="1000" step="5" value={String(fsv('ttiltH'))} onIn={mySl('ttiltH')} show={fsv('ttiltH') + '%'} /></Row>
          <Row label="тильт ↕"><MyRange min="50" max="1000" step="5" value={String(fsv('ttiltV'))} onIn={mySl('ttiltV')} show={fsv('ttiltV') + '%'} /></Row>
          <CfgRow it={c.cfgNumItem('fsWeight', 'вес', 300, 800, 100, 700)} />
          <Row label="масштаб"><EngRange id="fsScaleSlider" min="50" max="150" def="100" show="100%" suffix="%" /></Row>
          <Row label="свечение"><EngRange id="glowSlider" min="0" max="200" def="140" show="140" /></Row>
          <Row label="блюр"><EngRange id="textBlurSlider" min="0" max="100" def="0" show="0" /></Row>
          <Row label="искажение"><EngRange id="textDistortSlider" valId="textDistortVal" min="0" max="400" def="0" show="0" /></Row>
          <Row label="хроматика">
            <button type="button" onClick={() => c.setState({ textAber: !st.textAber })} style={s(winBtn(st.textAber))}>{st.textAber ? 'хроматика: вкл' : 'хроматика: выкл'}</button>
          </Row>
          <Row label="сила хроматики"><MyRange min="1" max="100" step="1" value={String(Math.max(1, fsv('taber')))} onIn={mySl('taber')} show={String(fsv('taber'))} /></Row>
          <Row label="экспозиция"><MyRange min="40" max="300" step="5" value={String(fsv('expo'))} onIn={mySl('expo')} show={fsv('expo') + '%'} /></Row>
          <Row label="подложка"><Picks items={selModes} /></Row>
          <Row label="свечение · искажение"><Picks items={glowWarpModes} /></Row>
          <Row label="цвет свечения" sub={st.glowColor ? 'повторный клик — свой цвет' : 'наследует цвет строки'}>
            <span style={s('position: relative; display: flex; align-items: center; gap: 8px;')}>
              <button type="button" onClick={() => c.setState({ glowColor: '' })}
                style={s('appearance: none; border: none; border-radius: 3px; padding: 4px 7px; font-family: inherit; font-size: 8.5px; cursor: pointer; ' + (st.glowColor ? 'background: color-mix(in srgb, var(--ink) 7%, transparent); color: var(--muted);' : 'background: var(--ink); color: var(--canvas);'))}>авто</button>
              <Swatches items={swGlow} />
              {/* id — тот, который ищут palInput/onCardInput (в макете он разъехался) */}
              <input type="color" id="glowColorPicker" defaultValue="#ffffff" style={s(palPicker(palSel, 'glow', 1))} />
            </span>
          </Row>
          <button type="button" id="textDistortAberrationBtn" aria-hidden="true" tabIndex={-1} style={s('display: none;')}></button>
        </div>

        <div style={s(CAP2)}>гарнитура</div>
        <div style={s('display: flex; flex-direction: column; gap: 8px;')}>
          <div style={s('display: flex; align-items: center; gap: 8px;')}>
            <input type="text" value={st.fontQ || ''} onChange={(e) => c.setState({ fontQ: e.target.value })} placeholder="поиск" spellCheck="false" style={s(SEARCH)} />
            {/* свой шрифт: FontFace вместо сети (офлайн-инвариант) — грузит
                loadFontFile из methods.fs.js; в дизайне обе точки цеплял движок */}
            <button type="button" id="btnCustomFont" onClick={() => { var el = document.getElementById('fontFile'); if (el) el.click(); }}
              className={hov(HOVINK)} style={s(MINI)}>＋ файл</button>
            <input type="file" id="fontFile" accept=".ttf,.otf,.woff,.woff2" style={s('display: none;')}
              onChange={(e) => { var fl = e.target.files && e.target.files[0]; e.target.value = ''; if (fl) call(c, 'loadFontFile', fl); }} />
          </div>
          <div style={s('max-height: 190px; overflow-y: auto; display: flex; flex-direction: column; gap: 1px; padding-right: 2px;')}>
            {fontList.map(function (fn) {
              return (
                <button key={fn.name} type="button" onClick={fn.onPick} style={s(fn.style)}>
                  <span style={s(fn.nameStyle)}>{fn.name}</span>
                  <span style={s(fn.sampleStyle)}>Аа Bb</span>
                </button>
              );
            })}
          </div>
          <select id="fontSelect" aria-hidden="true" tabIndex={-1} style={s('display: none;')}></select>
        </div>
      </div>

      {/* ---- пост ---- */}
      <div style={s(sec('post'))}>
        <div style={s(CAP)}>кадр</div>
        <div style={s(BOX)}>
          <Row label="размытие"><EngRange id="postfxBlurSlider" valId="postfxBlurVal" min="0" max="60" def="0" show="0" /></Row>
          <Row label="искажение"><EngRange id="postfxBendSlider" valId="postfxBendVal" min="0" max="400" def="0" show="0" /></Row>
          <Row label="аберрация">
            <button type="button" id="postfxAberrationBtn" onClick={() => c.setState({ postAber: !st.postAber })} style={s(winBtn(st.postAber))}>{st.postAber ? 'аберрация: вкл' : 'аберрация: выкл'}</button>
          </Row>
          <Row label="экспозиция"><MyRange min="40" max="300" step="5" value={String(fsv('expoPost'))} onIn={mySl('expoPost')} show={fsv('expoPost') + '%'} /></Row>
        </div>

        <div style={s(CAP2)}>тильт</div>
        <div style={s(BOX)}>
          <Row label="по горизонтали"><MyRange min="50" max="1000" step="5" value={String(fsv('tiltH'))} onIn={mySl('tiltH')} show={fsv('tiltH') + '%'} /></Row>
          <Row label="по вертикали"><MyRange min="50" max="1000" step="5" value={String(fsv('tiltV'))} onIn={mySl('tiltV')} show={fsv('tiltV') + '%'} /></Row>
        </div>

        <div style={s(CAP2)}>зерно</div>
        <div style={s(BOX)}>
          <Row label="плотность"><EngRange id="grainSlider" min="0" max="100" def="18" show="18" /></Row>
          <Row label="размер"><MyRange min="1" max="6" step="0.5" value={String(fsv('gsize'))} onIn={mySl('gsize')} show={'×' + fsv('gsize')} /></Row>
          <Row label="жёсткость"><MyRange min="50" max="400" step="10" value={String(fsv('ghard'))} onIn={mySl('ghard')} show={fsv('ghard') + '%'} /></Row>
          <Row label="блюр"><MyRange min="0" max="20" step="0.5" value={String(fsv('gblur'))} onIn={mySl('gblur')} show={fsv('gblur') === 0 ? 'нет' : fsv('gblur') + 'px'} /></Row>
          <Row label="кадры">
            <select value={String(st.grainFps == null ? 24 : st.grainFps)} onChange={(e) => c.setState({ grainFps: parseInt(e.target.value, 10) || 0 })} style={s(SEL)}>
              {grainFps.map(function (v) { return <option key={v} value={String(v)}>{v ? v + ' к/с' : 'без предела'}</option>; })}
            </select>
          </Row>
          <Row label="наложение">
            <select value={st.grainBlend || 'overlay'} onChange={(e) => c.setState({ grainBlend: e.target.value }, function () { call(c, 'pushScene'); })} style={s(SEL)}>
              {grainBlends.map(function (b) { return <option key={b} value={b}>{b}</option>; })}
            </select>
          </Row>
          <Row label="тон"><Picks items={grainModes} /></Row>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// ПАНЕЛЬ «СТРОКА» — шаблон 179..318
// ===========================================================================
export function renderFsLinePanel(c) {
  var st = c.state;
  var fsv = fsvOf(c), mySl = slOf(c);
  // ПОДАЧА СТРОК во фристайле — это НЕ режим генерации (Раунд 51).
  //
  // st.algo («Алгоритм»/«Классика») переключает КЛИЕНТСКИЙ кат-ап: мешок слов
  // из уже показанного, пересобираемый прямо в браузере (methods.fs.js:350).
  // Серверный бинарный режим живёт отдельно — st.knobMode. Панель и её
  // подписи утверждали, что это одно и то же, и перечисляли механизмы,
  // которых во фристайле нет («цепочка ролей, стыки, фильтры, порог отсева» —
  // три из четырёх вырезаны Раундом 50).
  var algo = st.algo || 'Алгоритм';
  var algoModes = ['Алгоритм', 'Классика'].map(function (g) {
    return { name: g === 'Классика' ? 'кат-ап' : 'генератор', style: pickStyle(algo === g), onPick: function () { c.setState({ algo: g }, function () { call(c, 'fsAdvance'); }); } };
  });
  var genNote = algo === 'Классика'
    ? 'мешок слов из уже показанного, пересобирается в браузере — сервер не спрашивается'
    : 'строки приходят с сервера по крутилкам ниже';
  // Гаснут крутилки по СВОЕМУ флагу: при клиентском кат-апе сервер не
  // спрашивается вовсе, поэтому мертвы все. Раньше блок гас по st.algo, а
  // выше по панели уже стоял другой переключатель — и при серверной классике
  // ползунки выглядели живыми, ничего при этом не делая.
  var классикаЯдра = (st.knobMode || 'алгоритм') === 'классика';
  var algoStyle = algo === 'Классика' ? 'opacity: 0.32; pointer-events: none;' : '';

  // ВСЕ восемь крутилок, а не четыре (Раунд 51). «Мат», «Клаузула»,
  // «Диссонанс» и «Связность» реально управляют строками фристайла — он шлёт
  // те же {mode, params}, — но в панели их не было, и крутить их можно было
  // только из редактора. Список и группы зеркалят канон core/clean.py.
  var крутилка = function (имя) {
    var v = st.params[имя] != null ? st.params[имя] : PARAM_DEFAULTS[имя];
    var шкала = ШКАЛЫ[имя] || ['', ''];
    var мертво = классикаЯдра && В_КЛАССИКЕ.indexOf(имя) < 0;
    return {
      // name — ПОДПИСЬ на экран, ключ остаётся внутри замыкания (см.
      // methods.shelves.имяКрутилки: имя крутилки это ключ сохранённых данных)
      name: имяКрутилки(имя), lo: шкала[0], hi: шкала[1],
      val: Number(v).toFixed(2), show: подпись(имя, v), dead: мертво,
      onIn: function (e) { c.setParam(имя, parseFloat(e.target.value)); },
    };
  };
  var genParams = ВОРОТА.concat(МНЕНИЯ).map(крутилка);

  // форма строфы: реальный профиль из /api/stanza/profiles вместо текста макета
  var forms = st.stanzaForms || {};
  var allForms = (forms.builtin || []).concat(forms.custom || []);
  var stName = st.stanzaProfile || (st.settings && st.settings.stanza_profile) || '';
  var prof = null;
  for (var i = 0; i < allForms.length; i++) if (allForms[i].name === stName) { prof = allForms[i]; break; }
  var stanzaNote = '';
  if (prof && prof.lines && prof.lines.length) {
    var lo = prof.lines.reduce(function (m, l) { return Math.min(m, l.min_syl); }, 99);
    var hi = prof.lines.reduce(function (m, l) { return Math.max(m, l.max_syl); }, 0);
    stanzaNote = prof.name + ' · ' + prof.lines.map(function (l) { return l.letter; }).join('')
      + '\n' + prof.lines.length + ' строк · слоги ' + lo + '–' + hi;
  }

  var srcMode = st.srcMode || 'генератор';
  var srcModes = ['генератор', 'свой текст'].map(function (m) {
    return { name: m, style: pickStyle(srcMode === m), onPick: function () { c.setState({ srcMode: m }, function () { c._srcPos = 0; call(c, 'fsAdvance'); }); } };
  });
  var srcChunk = st.srcChunk || 'строки';
  var srcChunks = ['строки', 'слова'].map(function (ch) {
    return { name: ch, style: pickStyle(srcChunk === ch), onPick: function () { c.setState({ srcChunk: ch }, function () { c._srcPos = 0; call(c, 'fsAdvance'); }); } };
  });
  var srcN = c.srcChunksList ? c.srcChunksList().length : 0;
  // подписи подачи зависят от шага — «единиц» звучит абстрактно, а
  // «строк разом» / «слов разом» читается сразу
  var шагЕдиниц = srcChunk === 'слова' ? 'слов разом' : 'строк разом';
  var шагПодписи = srcChunk === 'слова' ? 'по одному слову' : 'целыми строками';

  return (
    <div data-pa="down" data-po={st.closing === 'fsline' ? '1' : null} onInput={(e) => call(c, 'onCardInput', e)} style={s(fsPanel(st.fsLineOpen))}>
      {/* СВОЯ ТЕМА У СЦЕНЫ (Раунд 57). Раньше её не было вовсе: фристайл брал
          `_lastKey` — ключ последней генерации в редакторе, то есть ходил по
          чужой теме и молча менялся, когда владелец работал с текстом. */}
      <div style={s(CAP)}>темы сцены</div>
      <input type="text" value={st.fsTheme || ''} placeholder="через запятую"
        onChange={(e) => c.setState({ fsTheme: e.target.value }, function () { c._fsBuf = []; c._fsQ = []; })}
        style={s('width: 100%; background: none; border: none; border-bottom: 1px solid var(--border-subtle);'
          + ' color: var(--ink); font-family: inherit; font-size: 11px; padding: 3px 0; margin-bottom: 4px; outline: none;')} />
      <button onClick={() => call(c, 'fsВзятьИзРедактора')}
        style={s('appearance: none; border: none; background: none; color: var(--muted-soft);'
          + ' font-family: inherit; font-size: 9px; padding: 2px 0; margin-bottom: 12px; cursor: pointer;')}>
        взять настройки строфы из редактора</button>

      <div style={s(CAP)}>строка · режим</div>
      <div style={s('display: flex; gap: 4px; margin-bottom: 7px;')}>
        {algoModes.map(function (g) { return <button key={g.name} onClick={g.onPick} style={s(g.style)}>{g.name}</button>; })}
      </div>
      <p style={s('margin: 0 0 15px; font-size: 9px; line-height: 1.55; color: var(--muted-soft); text-wrap: pretty;')}>{genNote}</p>

      <div style={s(algoStyle)}>
        <div style={s(CAP)}>параметры</div>
        <div style={s(BOX)}>
          {genParams.map(function (p) {
            return (
              <div key={p.name} data-row="1" style={{ ...s(ROW), opacity: p.dead ? 0.32 : 1 }}>
                <span style={s('display: flex; flex-direction: column; gap: 2px; min-width: 0;')}>
                  <span style={s('font-size: 10.5px; color: var(--muted);')}>{p.name}</span>
                  <span style={s('display: flex; gap: 6px; font-size: 8.5px; color: var(--muted-soft);')}>
                    {p.dead
                      ? <span>в классике не действует</span>
                      : <Fragment><span>{p.lo}</span><span>·</span><span>{p.hi}</span></Fragment>}
                  </span>
                </span>
                <span style={s(CTL)}>
                  {/* Мат и Связность ходят от −1 («как есть» / «выключено») —
                      ползунок 0..1 отрезал бы им половину смысла */}
                  <input type="range"
                         min={p.name === 'Мат' || p.name === 'Связность' ? '-1' : '0'}
                         max={p.name === 'Клаузула' ? '3' : '1'}
                         step={p.name === 'Клаузула' ? '1' : '0.05'}
                         value={p.val} disabled={p.dead} onChange={p.onIn} />
                  <span style={s(VAL)}>{p.show}</span>
                </span>
              </div>
            );
          })}
        </div>
        {stanzaNote
          ? <p style={s('margin: 15px 0 0; font-size: 9px; line-height: 1.6; color: var(--muted-soft); white-space: pre-line;')}>{stanzaNote}</p>
          : null}
      </div>

      <div style={s('border-top: 1px solid var(--border-subtle); margin: 15px 0 13px;')}></div>
      <div style={s(CAP)}>источник</div>
      <div style={s('display: flex; flex-direction: column; gap: 10px; margin-bottom: 15px;')}>
        <div style={s('display: flex; gap: 4px;')}>
          {srcModes.map(function (m) { return <button key={m.name} type="button" onClick={m.onPick} style={s(m.style)}>{m.name}</button>; })}
        </div>
        <div style={s(srcMode === 'свой текст' ? '' : 'display: none;')}>
          <textarea value={st.srcText || ''} onChange={(e) => { c._srcPos = 0; c.setState({ srcText: e.target.value }); }}
            placeholder="вставь текст — строки пойдут по очереди" spellCheck="false"
            style={s('width: 100%; min-height: 68px; resize: vertical; appearance: none; border: none; border-radius: 3px; padding: 7px 8px; font-family: inherit; font-size: 10.5px; line-height: 1.5; background: color-mix(in srgb, var(--ink) 6%, transparent); color: var(--ink); outline: none;')}></textarea>
          <div style={s('display: flex; align-items: center; gap: 8px; margin-top: 7px;')}>
            <button type="button" onClick={() => { if (c._srcFile) c._srcFile.click(); }} className={hov(HOVINK)} style={s(MINI)}>＋ файл</button>
            <input type="file" ref={(el) => { c._srcFile = el; }} accept=".txt,.md,.rtf" style={s('display: none;')}
              onChange={(e) => {
                var fl = e.target.files && e.target.files[0];
                if (!fl) return;
                var rd = new FileReader();
                rd.onload = function () { c.setState({ srcText: String(rd.result || '') }, function () { c._srcPos = 0; call(c, 'fsAdvance'); }); };
                rd.readAsText(fl);
              }} />
            <span style={s('font-size: 9px; color: var(--muted-soft);')}>{srcN ? srcN + ' фрагментов' : 'пусто'}</span>
          </div>
          {/* «Шаг» переехал в «подачу» (Раунд 36) — он общий для генератора и
              своего текста. Здесь остаётся только нарезка своего текста на
              куски: сколько слов в одном фрагменте, если резать не по строкам. */}
          <div style={s('display: grid; grid-template-columns: 1fr 1fr; gap: 13px 18px; border: 1px solid var(--border-subtle); border-radius: var(--radius); padding: 11px 12px; margin-top: 11px;')}>
            <Row label="слов в куске">
              <MyRange min="1" max="20" step="1" value={String(fsv('srcWords'))} onIn={mySl('srcWords')} show={String(fsv('srcWords'))}
                wrap={srcChunk === 'слова' ? '' : ' opacity: 0.32; pointer-events: none;'} />
            </Row>
          </div>
        </div>

        {/* Раунд 36: подача — одна модель на все источники. «Шаг» решает, чем
            меряется единица (строкой или словом), «единиц разом» — сколько их
            на экране, «интервал» — через сколько секунд следующая порция.
            Обрезки «слов на строку» больше нет: сгенерированное показывается
            целиком, по порядку, ничего не теряя. */}
        <div style={s(CAP2)}>подача</div>
        <div style={s(BOX)}>
          <Row label="шаг" sub={шагПодписи}><Picks items={srcChunks} /></Row>
          <Row label={шагЕдиниц}>
            <MyRange min="1" max="8" step="1" value={String(fsv('fsPer'))} onIn={mySl('fsPer')} show={String(fsv('fsPer'))} />
          </Row>
          <Row label="интервал" sub="секунд между сменами">
            <MyRange min="0.2" max="8" step="0.1" value={String(fsv('fsSec'))} onIn={mySl('fsSec')}
              show={Number(fsv('fsSec')).toFixed(1) + ' с'} />
          </Row>
        </div>
      </div>
    </div>
  );
}

// ===========================================================================
// СПИСОК ПРОФИЛЕЙ — один и тот же для сцены (renderFsBar) и вида (панель общих
// настроек редактора). Строки готовит c.profileList() (methods.fsprofiles.js),
// разметка — дизайна (renderVals 3767..3786 / 3973..3992); держим её в одном
// месте, иначе два списка разъедутся при первой же правке
// ===========================================================================
export function renderProfileRows(rows, emptyNote) {
  return (
    <Fragment>
      {rows.map(function (p) {
        return (
          <div key={p.id} className={hov('--sh: 1; background: color-mix(in srgb, var(--ink) 5%, transparent)')} style={s(p.rowStyle)}>
            {p.editing
              ? <input type="text" defaultValue={p.name} onBlur={p.onRename} onKeyDown={p.onRenameKey} autoFocus spellCheck="false"
                  style={s('flex: 1; min-width: 0; appearance: none; background: color-mix(in srgb, var(--ink) 6%, transparent); border: none; border-radius: 3px; padding: 3px 5px; font-family: inherit; font-size: 10.5px; color: var(--ink); outline: none;')} />
              : <button type="button" onClick={p.onLoad} onDoubleClick={p.startRename} title={p.nameTitle} style={s(p.nameStyle)}>{p.name}</button>}
            <button type="button" onClick={p.onDefault} title={p.defTitle} style={s(p.defStyle)}>
              <svg viewBox="0 0 24 24" width="11" height="11" fill={p.defFill} stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" style={{ display: 'block' }}><line x1="12" y1="17.2" x2="12" y2="22"></line><path d="M5.4 17h13.2v-1.7a2 2 0 0 0-1.1-1.8l-1.7-.86A2 2 0 0 1 14.7 10.8V6.1h.9a2 2 0 0 0 0-4H8.4a2 2 0 0 0 0 4h.9v4.7a2 2 0 0 1-1.1 1.8l-1.7.86A2 2 0 0 0 5.4 15.3Z"></path></svg>
            </button>
            {p.canEdit ? (
              <Fragment>
                <button type="button" onClick={p.onUpdate} title="Перезаписать текущими" style={s(p.iconStyle)}>
                  <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" style={{ display: 'block' }}><path d="M3.6 12a8.4 8.4 0 1 0 2.46-5.94"></path><polyline points="3.6 4.2 3.6 9 8.4 9"></polyline></svg>
                </button>
                <button type="button" onClick={p.onDrop} title="Удалить" style={s(p.iconStyle)}>
                  <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" style={{ display: 'block' }}><line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line></svg>
                </button>
              </Fragment>
            ) : null}
          </div>
        );
      })}
      {rows.length > 1 || !emptyNote ? null
        : <div style={s('font-size: 9px; line-height: 1.5; color: var(--muted-soft);')}>{emptyNote}</div>}
    </Fragment>
  );
}

// Кнопка записи (фаза 4). Читает ровно одно поле состояния — st.recOn, — а
// доступность спрашивает у моста: файлы пишет питон, и в обычной вкладке
// браузера записывать физически нечем. Заперта — значит заперта: подпись
// говорит почему, клик не делает вид, что что-то началось.
function renderRecBtn(c, st) {
  var can = typeof c.recBridge === 'function' && !!c.recBridge();
  var on = !!st.recOn;
  var title = can ? (on ? 'стоп (Esc / R)' : 'запись окна') : (c.recWhyNot ? c.recWhyNot() : 'запись только в приложении');
  // recPulse живёт в style.js — пульсирующий кружок виден только владельцу:
  // сам хром во время записи заперт и в кадр не попадает
  var css = fsBtn(on, true) + (on ? ' animation: recPulse 1.6s infinite;' : '')
    + (can ? '' : ' opacity: 0.45; cursor: default;');
  return (
    <button type="button" id="btnRecord" disabled={!can} onClick={() => call(c, 'recToggle')} title={title}
      className={can ? hov(HOVINK) : undefined} style={s(css)}>
      <svg viewBox="0 0 24 24" width="13" height="13"><circle cx="12" cy="12" r="6.5" fill="currentColor"></circle></svg>
    </button>
  );
}

// ===========================================================================
// ВЕРХНЯЯ ПАНЕЛЬ ФРИСТАЙЛА — шаблон 164..807
// ===========================================================================
export function renderFsBar(c) {
  var st = c.state, isFs = st.tab === 'fs';
  var pO = function (k) { return st.closing === k ? '1' : null; };
  var profNow = (st.profiles || []).filter(function (p) { return p.id === st.profId; })[0] || null;
  var profRows = c.fsProfRows ? c.fsProfRows() : [];
  var ASP = c.ASPECTS || {};
  var aspectOpts = ['полный', '9:16', '16:9', '4:3', '1:1'].map(function (a) {
    var on = (st.aspect || 'полный') === a;
    return {
      name: a,
      style: 'appearance: none; border: none; background: ' + (on ? 'color-mix(in srgb, var(--ink) 10%, transparent)' : 'none') + '; border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: 10.5px; font-variant-numeric: tabular-nums; text-align: left; cursor: pointer; color: ' + (on ? 'var(--ink)' : 'var(--muted)') + ';',
      onPick: function () { c.closePop({ aspect: a === 'полный' ? '' : a }); setTimeout(function () { call(c, 'fitStage'); }, 0); }
    };
  });
  var onAspectCustom = function (e) {
    var raw = String(e.target.value || '').trim().replace(',', '.');
    if (!raw) { c.closePop({ aspect: '' }); call(c, 'fitStage'); return; }
    var m = raw.match(/^(\d+(?:\.\d+)?)\s*[:\/xх×]\s*(\d+(?:\.\d+)?)$/);
    var v = m ? parseFloat(m[1]) / parseFloat(m[2]) : parseFloat(raw);
    if (!v || !isFinite(v) || v < 0.2 || v > 6) return;
    c._customAspect = v;
    c.closePop({ aspect: m ? m[1] + ':' + m[2] : raw }); call(c, 'fitStage');
  };

  return (
    <div style={s((isFs ? 'display: flex;' : 'display: none;') + ' align-items: center; gap: 14px;')}>

      {/* ---- источники звука ---- */}
      <div style={s('display: flex; align-items: center; gap: 10px;')}>
        {/* микрофон и трек — реальный аудио-граф (methods.fsglue.js → freestyle/
            audio.js). В дизайне обе кнопки лишь переключали флаг состояния:
            звуком заведовал внешний скрипт движка, которого больше нет */}
        <button type="button" id="btnMic" onClick={() => call(c, 'fsToggleMic')} title="Микрофон" className={hov(HOVINK)} style={s(fsBtn(st.micOn))}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="3" width="6" height="11" rx="3"></rect><path d="M5 11a7 7 0 0 0 14 0"></path><line x1="12" y1="18" x2="12" y2="22"></line><line x1="8" y1="22" x2="16" y2="22"></line></svg>
        </button>
        <button type="button" id="btnTrack" onClick={() => call(c, 'fsToggleTrack')} title={st.trackOn ? 'Снять трек' : 'Трек из файла'} className={hov(HOVINK)} style={s(fsBtn(st.trackOn))}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M9 18V5l11-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="17" cy="16" r="3"></circle></svg>
        </button>
        {/* Синтетический шум — подпорка, которая ВОДИТ картинку, пока нет
            своего звука. Кнопка нужна потому, что вытеснение автоматическое:
            снял микрофон и трек — шум вернулся сам, а иногда его не хочется.
            Подсвечена, только когда шум реально водит (st.synthOn), а не когда
            «разрешён»: иначе она горела бы при живом микрофоне и врала. */}
        <button type="button" id="btnSynth" onClick={() => call(c, 'fsToggleSynth')}
          title={st.synthWanted === false ? 'Синтетический шум выключен'
            : (st.synthOn ? 'Синтетический шум водит картинку' : 'Синтетический шум уступил живому звуку')}
          className={hov(HOVINK)} style={s(fsBtn(!!st.synthOn))}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12h3l2-5 3 10 3-13 3 16 2-8h4"></path></svg>
        </button>
        {/* ПЕРЕЗАПУСК ДВИЖКА (Раунд 56). Владелец: «когда он сбивается, было
            бы славно его перезапускать, не перезапуская само приложение».
            Контекст WebGL2 браузер вправе отобрать в любой момент — сцена
            чернеет молча, и до этой кнопки лечилось только перезапуском окна. */}
        <button type="button" id="btnBcRestart" onClick={() => call(c, 'fsRestartEngine')}
          title="Перезапустить движок Butterchurn — если сцена почернела или замерла"
          className={hov(HOVINK)} style={s(fsBtn(false))}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-3-6.7"></path><path d="M21 3v6h-6"></path></svg>
        </button>
        {/* ПАПКА ЗАПИСЕЙ — ПОСТОЯННО (Раунд 56). Была только в итоге
            законченной записи; владелец: «а она может быть перманентна? это
            было бы славно». Открывает корень, а не последнюю сессию. */}
        <button type="button" id="btnRecDir"
          onClick={() => { fetch('/api/rec/open-dir', { method: 'POST' }).catch(() => {}); }}
          title="Открыть папку записей" className={hov(HOVINK)} style={s(fsBtn(false))}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path></svg>
        </button>
      </div>
      <div style={s('width: 1px; height: 11px; background: var(--border-subtle);')}></div>

      {/* ---- строка: авто, дальше, настройки ---- */}
      <div data-pop="1" style={s('display: flex; align-items: center; gap: 10px;')}>
        <button type="button" id="btnAuto" onClick={() => call(c, 'fsTog', 'autoOn')} title="Автосмена строки" className={hov(HOVINK)} style={s(fsBtn(st.autoOn))}>
          {st.autoOn
            ? <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"></rect><rect x="14" y="5" width="4" height="14" rx="1"></rect></svg>
            : <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor"><polygon points="7,5 20,12 7,19"></polygon></svg>}
        </button>
        <button type="button" id="btnNext" onClick={() => call(c, 'fsAdvance')} title="Следующая строка" className={hov(HOVINK)} style={s(fsBtn(false))}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7.5a8 8 0 1 1-1 4"></path><polyline points="4 3.5 4 8 8.5 8"></polyline></svg>
        </button>
        <button onClick={() => (st.fsLineOpen ? c.closePop() : c.openPop({ fsLineOpen: true }))} aria-label="Настройки строки" title="Настройки строки" className={hov(HOVINK)} style={s(hudBtn(st.fsLineOpen))}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><polyline points="4 6.5 4 4.5 20 4.5 20 6.5"></polyline><line x1="12" y1="4.5" x2="12" y2="19.5"></line><line x1="8.5" y1="19.5" x2="15.5" y2="19.5"></line></svg>
        </button>
        {renderFsLinePanel(c)}
      </div>

      {/* ---- сцена ---- */}
      <div data-pop="1" style={s('display: flex; align-items: center; gap: 10px; position: relative;')}>
        <button onClick={() => (st.fsSetOpen ? c.closePop() : c.openPop({ fsSetOpen: true }))} aria-label="Сцена" title="Сцена: камера, пресет, фон, текст, пост" className={hov(HOVINK)} style={s(hudBtn(st.fsSetOpen))}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="3.5" y="5" width="17" height="12" rx="2"></rect><line x1="8" y1="20" x2="16" y2="20"></line></svg>
        </button>
        {renderFsSetPanel(c)}
      </div>

      {/* ---- профили сцены · формат кадра ---- */}
      <div data-pop="1" style={s('display: flex; align-items: center; gap: 10px; position: relative;')}>
        <button onClick={() => c.tog('prof')} aria-label={profNow ? 'Профиль: ' + profNow.name : 'Профили настроек'} title={profNow ? 'Профиль: ' + profNow.name : 'Профили настроек'}
          className={hov(HOVINK)} style={s(hudBtn(st.openPill === 'prof' || !!profNow))}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6.5h6l1.6 2H20v9H4z"></path></svg>
        </button>
        <div data-pa="down" data-po={pO('prof')} style={s(menuBox(st.openPill === 'prof', 246, 'block'))}>
          <div style={s('display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 7px;')}>
            <span style={s('font-size: 8.5px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--muted-soft);')}>профили сцены</span>
            <button onClick={() => c.saveFsProfile()} className={hov(HOVINK)} style={s('appearance: none; background: none; border: none; padding: 0; font-family: inherit; font-size: 9px; color: var(--muted); cursor: pointer; white-space: nowrap;')}>＋ сохранить</button>
          </div>
          {renderProfileRows(profRows, 'пусто — «сохранить» запомнит сцену, пресет и палитру')}
        </div>

        <button onClick={() => c.tog('aspect')} aria-label={st.aspect ? 'Формат кадра: ' + st.aspect : 'Формат кадра: полный'} title={st.aspect ? 'Формат кадра: ' + st.aspect : 'Формат кадра: полный'}
          className={hov(HOVINK)} style={s('appearance: none; background: none; border: none; padding: 0; display: flex; align-items: center; font-family: inherit; letter-spacing: 0.02em; cursor: pointer; white-space: nowrap; color: ' + (st.aspect ? 'var(--ink)' : 'var(--muted-soft)') + ';')}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="6" width="16" height="12" rx="1.6"></rect><line x1="9" y1="6" x2="9" y2="18"></line></svg>
        </button>
        <span style={s('font-size: 9px; color: var(--muted-soft); font-variant-numeric: tabular-nums;')}>{st.aspect || ''}</span>
        <div data-pa="down" data-po={pO('aspect')} style={s(menuBox(st.openPill === 'aspect', 118, 'flex'))}>
          {aspectOpts.map(function (a) { return <button key={a.name} type="button" onClick={a.onPick} style={s(a.style)}>{a.name}</button>; })}
          {/* поле неуправляемое по той же причине, что кегль: пока «21:9» не
              дописан, обработчик молчит, а управляемому React вернул бы старое
              значение и набрать было бы нечего. key — выбор из списка сверху */}
          <input key={st.aspect || ''} type="text" defaultValue={ASP[st.aspect] ? '' : (st.aspect || '')} onChange={onAspectCustom} placeholder="свой 21:9" spellCheck="false"
            style={s('width: 100%; margin-top: 6px; appearance: none; border: none; border-radius: 3px; padding: 5px 7px; font-family: inherit; font-size: 9px; background: color-mix(in srgb, var(--ink) 6%, transparent); color: var(--ink); outline: none;')} />
          <button type="button" onClick={() => c.setState({ fitFrame: !st.fitFrame }, function () { call(c, 'fitLine'); })}
            style={s('appearance: none; display: flex; align-items: center; gap: 6px; width: 100%; border: none; background: none; border-radius: 3px; padding: 5px 8px; font-family: inherit; font-size: 10.5px; text-align: left; cursor: pointer; color: ' + (st.fitFrame ? 'var(--ink)' : 'var(--muted)') + ';')}>
            <span style={s('display: inline-flex; align-items: center; justify-content: center; width: 11px; height: 11px; flex-shrink: 0; border-radius: 3px; font-size: 8.5px; line-height: 1; ' + (st.fitFrame ? 'background: var(--ink); color: var(--canvas);' : 'box-shadow: inset 0 0 0 1px var(--border-soft);'))}>{st.fitFrame ? '✓' : ''}</span>
            вписывать текст
          </button>
        </div>
      </div>

      {/* ---- запись: фаза 4 (methods.fsrec.js) ----
          Файлы пишет питон, поэтому в обычной вкладке браузера моста нет и
          кнопка честно заперта с подписью «запись только в приложении» — а не
          падает и не делает вид, что пишет. Во время записи кнопка недоступна
          и в окне: она внутри [data-chrome], а хром заперт наглухо — стоп
          живёт на Esc/R (иначе панель полезла бы в кадр). */}
      {renderRecBtn(c, st)}
    </div>
  );
}
