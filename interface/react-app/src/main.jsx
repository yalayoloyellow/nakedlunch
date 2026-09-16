import { Component } from 'react'
import { createRoot } from 'react-dom/client'
import Nakedlunch from './nl/Nakedlunch.jsx'
import './index.css'

// Единственный интерфейс. Старый (App.jsx + ExtendoView + NakedlunchView) жил
// на #old до паритета ядра и удалён 2026-08-03 (Раунд 39): паритет достигнут —
// последние функции, которые звал только он (заливка книг, источники, сроки
// хранения, очистка истории, возврат показанного, бэкап и выгрузка), переехали
// в настройки нового интерфейса. Держать 114 КБ мёртвого кода «на всякий»
// значило бы иметь два разных ответа на вопрос «как это работает».
//
// БЕЗ StrictMode: императивный DOM-рендерер документа не переживает двойной
// mount (это не обход бага React, а свойство самого рендерера).
//
// index.css пока остаётся: из 245 его правил 28 всё ещё попадают в элементы
// сцены фристайла (.line, .colorLayer, .stage). Разбор — отдельным проходом с
// живой проверкой сцены, а не вслепую вместе с удалением файлов.
// ---------------------------------------------------------------------------
// НИ ОДНА ОШИБКА НЕ УХОДИТ В ТИШИНУ (Раунд 59).
//
// Окно — WKWebView внутри pywebview: консоли у него нет, и ошибка в нём видна
// ровно никому. Поэтому всё, что окно роняет, отправляется в общий журнал —
// туда же, куда пишет сервер. Человек потом копирует одно и целиком.
//
// Отправка НЕ должна ломать то, что и так сломалось: любые сбои самой отправки
// глотаются, а очередь ограничена — иначе цикл ошибок утопил бы приложение
// в собственных сообщениях.
let _отправлено = 0;
let вЖурнал = function(текст, уровень) {
  if (_отправлено > 200) return;          // защита от цикла ошибок
  _отправлено += 1;
  try {
    fetch('/api/ui/log', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ откуда: 'окно', уровень: уровень || 'ошибка',
                             text: String(текст).slice(0, 4000) }),
    }).catch(function () {});
  } catch (e) { /* журнал не обязан работать, чтобы работало остальное */ }
}

window.addEventListener('error', function (e) {
  вЖурнал((e.message || 'ошибка') + ' — ' + (e.filename || '') + ':' + (e.lineno || '') +
          (e.error && e.error.stack ? '\n' + e.error.stack : ''));
});
window.addEventListener('unhandledrejection', function (e) {
  const r = e.reason;
  вЖурнал('необработанный отказ: ' + ((r && (r.stack || r.message)) || String(r)));
});
// МЕСТНАЯ КОПИЯ ЖУРНАЛА. Отправленное серверу для окна недоступно, а показать
// причину надо ровно тогда, когда сервера уже нет. Двести строк хватает: это
// последние минуты работы, в которых поломка и произошла.
window.__журналОкна = [];
const _вЖурналИсх = вЖурнал;
вЖурнал = function (текст, уровень) {
  try {
    window.__журналОкна.push(new Date().toLocaleTimeString('ru') + '  ' +
                             (уровень || 'ошибка') + '  ' + String(текст).slice(0, 1000));
    if (window.__журналОкна.length > 200) window.__журналОкна.shift();
  } catch (e) { /* пусто */ }
  _вЖурналИсх(текст, уровень);
};
window.__вЖурнал = вЖурнал;

// Ошибка рендера иначе оставляет пустой root: глобальный обработчик её видит,
// но React уже не может показать человеку, что произошло. Граница держит
// приложение объяснимым и даёт единственное безопасное восстановление —
// перезапуск интерфейса с чистым деревом.
class ИнтерфейсОшибка extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, copied: false };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    var сообщение = error && error.stack ? error.stack : String(error);
    var стекКомпонентов = info && info.componentStack ? '\n' + info.componentStack : '';
    вЖурнал('ошибка рендера: ' + сообщение + стекКомпонентов, 'ошибка');
  }

  отчёт() {
    var error = this.state.error;
    return 'nakedlunch: ошибка интерфейса\n\n'
      + (error && error.stack ? error.stack : String(error))
      + '\n\nлокальный журнал:\n'
      + ((window.__журналОкна || []).join('\n') || 'пусто');
  }

  скопировать = () => {
    var text = this.отчёт();
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => this.setState({ copied: true }), () => {});
      }
    } catch (e) { /* отчёт можно взять из текста ниже */ }
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main style={{ height: '100vh', boxSizing: 'border-box', overflow: 'auto', padding: '40px 28px', background: '#131313', color: '#ededed', fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 13, lineHeight: 1.5 }}>
        <div style={{ maxWidth: 760, margin: '0 auto' }}>
          <div style={{ color: '#e27b7b', fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase', marginBottom: 12 }}>ошибка интерфейса</div>
          <h1 style={{ margin: '0 0 10px', fontSize: 20, fontWeight: 500 }}>Экран не удалось отрисовать</h1>
          <p style={{ margin: '0 0 18px', color: '#cfcfcf' }}>Данные не потеряны. Перезапусти интерфейс; если ошибка повторится, скопируй отчёт и пришли его вместе с журналом.</p>
          <pre style={{ margin: '0 0 18px', padding: 12, overflow: 'auto', whiteSpace: 'pre-wrap', color: '#e27b7b', borderLeft: '2px solid #e27b7b', background: '#1b1b1b' }}>{String(this.state.error.message || this.state.error)}</pre>
          <div style={{ display: 'flex', gap: 8 }}>
            <button type="button" onClick={() => window.location.reload()} style={{ padding: '7px 12px', border: 0, borderRadius: 3, background: '#ededed', color: '#131313', cursor: 'pointer', font: 'inherit' }}>перезапустить</button>
            <button type="button" onClick={this.скопировать} style={{ padding: '7px 12px', border: '1px solid #3d3d3d', borderRadius: 3, background: 'transparent', color: '#ededed', cursor: 'pointer', font: 'inherit' }}>{this.state.copied ? 'отчёт скопирован' : 'скопировать отчёт'}</button>
          </div>
        </div>
      </main>
    );
  }
}

createRoot(document.getElementById('root')).render(<ИнтерфейсОшибка><Nakedlunch /></ИнтерфейсОшибка>)
