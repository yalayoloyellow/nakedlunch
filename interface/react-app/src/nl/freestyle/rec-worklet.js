// Отвод записи на AudioWorklet: копит сэмплы в рендер-потоке и отдаёт их
// главному потоку чанками готового PCM16.
//
// Этот файл НЕ импортируется как модуль приложения — он грузится
// audioWorklet.addModule() и живёт в AudioWorkletGlobalScope. Отсюда правила:
//   * никакого import и ничего из window;
//   * `performance` тут ЕСТЬ НЕ ВЕЗДЕ (замер спайка: ни в одном движке его не
//     оказалось), поэтому времени не меряем вообще — считаем кадры и сигнал;
//   * узел — ТУПИК: numberOfOutputs = 0 задаётся при создании узла. Отвод
//     физически не может попасть в слышимый тракт.
//
// Режим fused (выбран по замерам спайка): Float32 конвертируется в Int16 прямо
// при копировании кванта, накопитель сразу Int16Array. Та же суммарная работа,
// что и конвертацией одним куском, но размазана по 192 квантам — на границе
// чанка нет всплеска, и проход по данным один вместо двух.
//
// ГРАБЛИ, на которые уже наступили в спайке: присвоить Float32 из диапазона
// -1..1 напрямую в Int16Array НЕЛЬЗЯ — всё усекается в 0, файл выходит чистой
// тишиной, а счётчики кадров при этом зелёные и дропов ноль. Поэтому
// конвертация явная (clamp + масштаб), а в каждом чанке едут пик и RMS: они и
// есть доказательство, что в записи ЕСТЬ сигнал.

// 24576 кадров = 192 × 128, то есть ровно целое число квантов (граница чанка
// всегда совпадает с границей кванта) и ≈0.5 с при 48 кГц.
const CHUNK_FRAMES = 24576;

class RecTapProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = (options && options.processorOptions) || {};
    this.label = o.label || 'tap';
    this.channels = o.channels === 2 ? 2 : 1;
    this.chunkFrames = o.chunkFrames || CHUNK_FRAMES;

    // interleaved PCM16 — в том самом порядке, которого ждёт WAV, чтобы потом
    // никто ничего не перекладывал
    this.buf = new Int16Array(this.chunkFrames * this.channels);
    this.write = 0;      // позиция записи в КАДРАХ

    this.seq = 0;        // сквозной номер чанка: по нему Python ловит дыру
    this.frames = 0;     // сколько кадров всего скопировано
    this.peak = 0;       // пик текущего чанка, в единицах int16 (0…32767)
    this.sumSq = 0;      // сумма квадратов текущего чанка — для RMS
    this.nSq = 0;

    this.port.onmessage = (e) => {
      const cmd = e && e.data && e.data.cmd;
      // flush — хвост при остановке: без него последние <0.5 с просто пропали бы
      if (cmd === 'flush') this.flush();
    };
  }

  flush() {
    const frames = this.write;
    if (!frames) return;
    const used = frames * this.channels;

    // Отдаём накопитель целиком (Transferable, нулевое копирование) и заводим
    // новый. Неполный чанк приходится резать копией — это бывает один раз, на
    // остановке.
    const payload = used === this.buf.length ? this.buf : this.buf.slice(0, used);
    this.buf = new Int16Array(this.chunkFrames * this.channels);
    this.write = 0;

    const peak = this.peak;
    const rms = this.nSq ? Math.sqrt(this.sumSq / this.nSq) : 0;
    this.peak = 0;
    this.sumSq = 0;
    this.nSq = 0;

    this.port.postMessage({
      type: 'chunk',
      label: this.label,
      seq: this.seq++,
      frames,
      channels: this.channels,
      // пик и RMS в единицах int16 (0…32767): «в чанке есть сигнал» проверяется
      // по ним, а не по факту, что сообщение пришло
      peak,
      rms,
      buf: payload,
    }, [payload.buffer]);
  }

  process(inputs) {
    const inp = inputs[0];
    // Вход пуст, пока источник молчит (микрофон выключен, луп не загружен) —
    // это норма, не ошибка: тишину в файл не пишем, но узел живёт дальше.
    if (!inp || inp.length === 0 || !inp[0]) return true;

    const src0 = inp[0];
    const src1 = this.channels > 1 ? (inp[1] || inp[0]) : null;
    const n = src0.length;                 // обычно 128
    const ch = this.channels;
    const b = this.buf;
    let w = this.write;
    let peak = this.peak;
    let sumSq = this.sumSq;
    let i = 0;

    while (i < n) {
      const room = this.chunkFrames - w;
      const take = room < (n - i) ? room : (n - i);
      let d = w * ch;
      for (let k = 0; k < take; k++) {
        let s = src0[i + k];
        if (s > 1) s = 1; else if (s < -1) s = -1;
        // масштаб разный для знаков: -1 → -32768, +1 → +32767, без переполнения
        const v = s < 0 ? (s * 0x8000) : (s * 0x7fff);
        b[d++] = v;
        const a = v < 0 ? -v : v;
        if (a > peak) peak = a;
        sumSq += v * v;
        if (ch > 1) {
          let s2 = src1[i + k];
          if (s2 > 1) s2 = 1; else if (s2 < -1) s2 = -1;
          const v2 = s2 < 0 ? (s2 * 0x8000) : (s2 * 0x7fff);
          b[d++] = v2;
          const a2 = v2 < 0 ? -v2 : v2;
          if (a2 > peak) peak = a2;
          sumSq += v2 * v2;
        }
      }
      this.nSq += take * ch;
      w += take;
      i += take;
      this.frames += take;
      if (w >= this.chunkFrames) {
        this.write = w;
        this.peak = peak;
        this.sumSq = sumSq;
        this.flush();
        w = this.write;                    // flush обнулил позицию и статистику
        peak = this.peak;
        sumSq = this.sumSq;
      }
    }

    this.write = w;
    this.peak = peak;
    this.sumSq = sumSq;
    return true;                           // отвод живёт всё время записи
  }
}

registerProcessor('rec-tap', RecTapProcessor);
