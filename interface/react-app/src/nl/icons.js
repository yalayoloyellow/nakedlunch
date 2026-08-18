// Иконки хрома из дизайна «Editor First» — дословный перенос. ico()/icoBtn()
// отдают СТРОКИ: императивный рендерер документа вставляет их через innerHTML.

// ОДНА ИКОНКА, А НЕ НАБОР (Раунд 63). Здесь лежали ещё pin/restore/check/close/
// prev/next — от кнопок, которых в интерфейсе нет: закрытие и стрелки рисуются
// текстовыми знаками (✕, ‹, ›), «вернуть» и «галочка» живут подписями. Единственный
// живой вызов — ico('star') у звезды избранного в methods.doc.js.
export const ICO = {
  star: '<polygon points="12 3 14.85 8.78 21.2 9.71 16.6 14.2 17.69 20.5 12 17.52 6.31 20.5 7.4 14.2 2.8 9.71 9.15 8.78 12 3"></polygon>'
};

export function ico(name, filled, sz) {
  var s = sz || 13;
  return '<svg viewBox="0 0 24 24" width="' + s + '" height="' + s + '" fill="' + (filled ? 'currentColor' : 'none')
    + '" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" style="display:block; pointer-events:none;">' + ICO[name] + '</svg>';
}

// кнопка-значок хрома: один рецепт на всё приложение, отличается только цветом
export function icoBtn(col) { return 'appearance: none; background: none; border: none; padding: 0; display: flex; cursor: pointer; color: ' + col + ';'; }

export const ICO_BTN = function (active) {
  return 'appearance: none; background: none; border: none; padding: 2px; display: flex; align-items: center; justify-content: center; cursor: pointer;'
    + ' transition: opacity 0.12s var(--ease), color 0.12s var(--ease); color: ' + (active ? 'var(--ink)' : 'var(--muted)') + ';';
};

// Компонент <Ico name/> вырезан (Раунд 63): JSX-обёртка над той же строкой SVG,
// которой не воспользовалась ни одна ветка шаблона. Строки документа рисует
// императивный рендерер, а он берёт ico() напрямую.
