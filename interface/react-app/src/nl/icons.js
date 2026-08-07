// Иконки хрома из дизайна «Editor First» — дословный перенос. ico()/icoBtn()
// отдают СТРОКИ: императивный рендерер документа вставляет их через innerHTML.
// Для JSX-веток шаблона есть компонент <Ico name/>.

import { createElement } from 'react';

export const ICO = {
  pin: '<line x1="12" y1="17.2" x2="12" y2="22"></line><path d="M5.4 17h13.2v-1.7a2 2 0 0 0-1.1-1.8l-1.7-.86A2 2 0 0 1 14.7 10.8V6.1h.9a2 2 0 0 0 0-4H8.4a2 2 0 0 0 0 4h.9v4.7a2 2 0 0 1-1.1 1.8l-1.7.86A2 2 0 0 0 5.4 15.3Z"></path>',
  star: '<polygon points="12 3 14.85 8.78 21.2 9.71 16.6 14.2 17.69 20.5 12 17.52 6.31 20.5 7.4 14.2 2.8 9.71 9.15 8.78 12 3"></polygon>',
  restore: '<path d="M3.6 12a8.4 8.4 0 1 0 2.46-5.94"></path><polyline points="3.6 4.2 3.6 9 8.4 9"></polyline>',
  check: '<polyline points="4.5 12.6 9.4 17.4 19.5 6.8"></polyline>',
  close: '<line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line>',
  prev: '<polyline points="14.5 5.5 8 12 14.5 18.5"></polyline>',
  next: '<polyline points="9.5 5.5 16 12 9.5 18.5"></polyline>'
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

// <Ico name="star" filled sz={13}/> — та же SVG-строка, но для JSX
export function Ico({ name, filled, sz }) {
  return createElement('span', {
    style: { display: 'flex' },
    dangerouslySetInnerHTML: { __html: ico(name, filled, sz) },
  });
}
