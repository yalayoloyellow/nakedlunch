// Юнит-проверка записи: отвод (rec-worklet.js) и насос в мост (rec-audio.js).
// Стиль и мок Web Audio — те же, что в audio.test.mjs (мок скопирован, а не
// вынесен в общий файл: тот тест — самостоятельный скрипт, и связывать два
// теста третьим файлом дороже, чем держать 60 строк мока дважды).
// Запуск: cd interface/react-app && node src/nl/freestyle/rec-audio.test.mjs
//
// Что проверяем ПО ФАКТУ, а не по наличию полей:
//   1. отвод пре-фейдерный — ползунок громкости не трогает сигнал на отводе;
//   2. насос ждёт ответа моста — seq строго по возрастанию даже когда ранние
//      ответы искусственно медленнее поздних (порядок мостом не гарантирован);
//   3. конвертация не усекает в ноль — синус даёт пик много больше 1000
//      (реальная ошибка спайка: Float32 положили в Int16Array напрямую, файл
//      вышел тишиной, а все счётчики были зелёные);
//   4. переполнение очереди — ошибка наружу, а не молчаливый рост памяти;
//   5. ответ моста {ok:false} — это потеря чанка, а не успех (питон отвечает
//      объектом, а не исключением: проверять надо поле, а не отсутствие бросков).

import { createAudio } from './audio.js';

// ---- мок Web Audio --------------------------------------------------------

let uid = 0;

class P {                                  // AudioParam
  constructor(v) { this.value = v; this.target = v; }
  cancelScheduledValues() {}
  setValueAtTime(v) { this.value = v; this.target = v; }
  setTargetAtTime(v) { this.target = v; this.value = v; }
}

class N {                                  // AudioNode
  constructor(ctx, kind) {
    this.ctx = ctx; this.kind = kind; this.id = ++uid;
    ctx.nodes.push(this);
  }
  connect(dst) {
    if (dst instanceof P) this.ctx.paramEdges.push([this, dst]);
    else this.ctx.edges.push([this, dst]);
    return dst;
  }
  disconnect(dst) {
    this.ctx.edges = this.ctx.edges.filter(([a, b]) => a !== this || (dst && b !== dst));
  }
}

class Gain extends N {
  constructor(ctx) { super(ctx, 'gain'); this.gain = new P(1); }
}
class Analyser extends N {
  constructor(ctx) { super(ctx, 'analyser'); this.fftSize = 2048; this.smoothingTimeConstant = 0; }
}
class Osc extends N {
  constructor(ctx) { super(ctx, 'osc'); this.frequency = new P(440); }
  start() {} stop() {}
}
class BufSrc extends N {
  constructor(ctx) { super(ctx, 'bufsrc'); this.buffer = null; this.loop = false; }
  start() {} stop() {}
}

class MockCtx {
  constructor(o) {
    this.opts = o || {};
    this.sampleRate = 48000;
    this.state = 'suspended';
    this.currentTime = 0;
    this.nodes = [];
    this.edges = [];
    this.paramEdges = [];
    this.destination = new N(this, 'destination');
    this.added = [];
    this.audioWorklet = { addModule: async (url) => { this.added.push(url); } };
  }
  createGain() { return new Gain(this); }
  createAnalyser() { return new Analyser(this); }
  createOscillator() { return new Osc(this); }
  createBufferSource() { return new BufSrc(this); }
  createMediaStreamSource(s) { const n = new N(this, 'streamsrc'); n.stream = s; return n; }
  createBuffer(ch, len, sr) {
    const data = new Float32Array(len);
    return { numberOfChannels: ch, length: len, sampleRate: sr, getChannelData: () => data };
  }
  async decodeAudioData() { return this.createBuffer(2, 4800, this.sampleRate); }
  async resume() { this.state = 'running'; }
  async close() { this.state = 'closed'; }
}

let lastCtx = null;
function MockAudioContext(o) { const c = new MockCtx(o); lastCtx = c; return c; }

// Мок AudioWorkletNode: запоминает опции и даёт тесту вручную «прислать» чанк.
class MockWorkletNode extends N {
  constructor(ctx, name, options) {
    super(ctx, 'worklet');
    this.name = name;
    this.options = options;
    this.cmds = [];
    const self = this;
    this.port = {
      onmessage: null,
      postMessage(m) { self.cmds.push(m); },
    };
  }
  emit(data) { if (this.port.onmessage) this.port.onmessage({ data }); }
}

// ---- утиль ----------------------------------------------------------------

let failed = 0;
function ok(cond, name, extra) {
  if (cond) { console.log('  ok   ' + name); return; }
  failed++;
  console.log('  FAIL ' + name + (extra ? ' — ' + extra : ''));
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function pathTo(ctx, from, to) {           // путь по звуковым связям или null
  const prev = new Map([[from, null]]);
  const q = [from];
  while (q.length) {
    const n = q.shift();
    if (n === to) {
      const path = [];
      for (let c = n; c; c = prev.get(c)) path.unshift(c);
      return path;
    }
    for (const [a, b] of ctx.edges) if (a === n && !prev.has(b)) { prev.set(b, n); q.push(b); }
  }
  return null;
}

// Во сколько раз путь ослабляет сигнал: произведение gain по узлам пути.
// Это и есть «сигнал на отводе» в терминах маршрутизации.
function pathGain(ctx, from, to) {
  const path = pathTo(ctx, from, to);
  if (!path) return null;
  let g = 1;
  for (const n of path) if (n !== from && n.gain instanceof P) g *= n.gain.value;
  return g;
}
function inputsOf(ctx, node) { return ctx.edges.filter(([, b]) => b === node).map(([a]) => a); }

const loopFile = { name: 'loop.wav', arrayBuffer: async () => new ArrayBuffer(16) };
const micStream = { getTracks: () => [{ stop() {} }] };

// ---- 1. отвод в рендер-потоке: конвертация и пик ---------------------------

console.log('\n1. rec-worklet: конвертация Float32 → Int16');

const registered = {};
globalThis.registerProcessor = (n, c) => { registered[n] = c; };
globalThis.AudioWorkletProcessor = class {
  constructor() {
    const self = this;
    this.port = {
      onmessage: null,
      posted: [],
      // Transferable в ноде не имитируем: буфер остаётся читаемым, иначе
      // проверить содержимое чанка было бы нечем
      postMessage(msg) { self.port.posted.push(msg); },
    };
  }
};
globalThis.currentFrame = 0;
globalThis.sampleRate = 48000;
await import('./rec-worklet.js');

ok(typeof registered['rec-tap'] === 'function', 'процессор зарегистрирован как rec-tap');

const Tap = registered['rec-tap'];

// моно, синус 440 Гц амплитудой 0.5 — ровно тот случай, на котором спайк
// получил файл-тишину при наивном присваивании в Int16Array
const mono = new Tap({ processorOptions: { label: 'mic', channels: 1 } });
const CH = 24576 / 128;                              // квантов на полный чанк
for (let q = 0; q < CH; q++) {
  const quant = new Float32Array(128);
  for (let i = 0; i < 128; i++) {
    const t = (q * 128 + i) / 48000;
    quant[i] = 0.5 * Math.sin(2 * Math.PI * 440 * t);
  }
  mono.process([[quant]], [], {});
}
const chunk = mono.port.posted[0];
ok(mono.port.posted.length === 1, 'полный накопитель отдан ровно одним сообщением',
  'сообщений: ' + mono.port.posted.length);
ok(chunk && chunk.frames === 24576 && chunk.seq === 0, 'чанк: 24576 кадров, seq 0',
  chunk && (chunk.frames + '/' + chunk.seq));
ok(chunk.buf instanceof Int16Array && chunk.buf.length === 24576, 'данные — Int16Array нужной длины');
ok(chunk.peak > 1000, 'КОНВЕРТАЦИЯ НЕ УСЕКЛА В НОЛЬ: пик много больше 1000',
  'peak=' + chunk.peak);
ok(Math.abs(chunk.peak - 0.5 * 0x7fff) < 40, 'пик соответствует амплитуде 0.5',
  'peak=' + chunk.peak + ' ожидалось ≈' + Math.round(0.5 * 0x7fff));
ok(chunk.rms > 1000 && chunk.rms < chunk.peak, 'RMS осмысленный (0 < rms < peak)',
  'rms=' + chunk.rms.toFixed(1));
{
  let nz = 0, peakSeen = 0;
  for (let i = 0; i < chunk.buf.length; i++) {
    const v = chunk.buf[i] < 0 ? -chunk.buf[i] : chunk.buf[i];
    if (v) nz++;
    if (v > peakSeen) peakSeen = v;
  }
  ok(nz > chunk.buf.length * 0.9, 'в данных реально есть сигнал, а не тишина',
    'ненулевых: ' + nz + '/' + chunk.buf.length);
  ok(peakSeen === chunk.peak, 'заявленный пик совпадает с содержимым чанка',
    peakSeen + ' против ' + chunk.peak);
}

// стерео: чередование каналов и клиппинг за пределами -1…1
const st = new Tap({ processorOptions: { label: 'loop', channels: 2 } });
const L = new Float32Array(128).fill(0.25);
const R = new Float32Array(128).fill(-0.25);
st.process([[L, R]], [], {});
const clipL = new Float32Array(128).fill(9);
const clipR = new Float32Array(128).fill(-9);
st.process([[clipL, clipR]], [], {});
st.port.onmessage({ data: { cmd: 'flush' } });        // хвост по команде
const stChunk = st.port.posted[0];
ok(!!stChunk && stChunk.frames === 256 && stChunk.channels === 2,
  'flush отдаёт неполный хвост (256 кадров, 2 канала)',
  stChunk && (stChunk.frames + '/' + stChunk.channels));
ok(stChunk.buf.length === 512, 'стерео чередуется: 256 кадров = 512 сэмплов');
ok(stChunk.buf[0] > 0 && stChunk.buf[1] < 0, 'каналы не перепутаны местами',
  stChunk.buf[0] + ',' + stChunk.buf[1]);
ok(stChunk.buf[256] === 32767 && stChunk.buf[257] === -32768,
  'выход за -1…1 зажат в границы int16, а не переполнен',
  stChunk.buf[256] + ',' + stChunk.buf[257]);

// ---- стенд для rec-audio.js ------------------------------------------------

function setup(bridge, opts) {
  const audio = createAudio({
    AudioContextCtor: MockAudioContext,
    getUserMedia: async () => micStream,
  });
  audio.start();
  return { audio, ctx: lastCtx, bridge };
}

async function makeRec(audio, bridge, extra) {
  const { createAudioRec } = await import('./rec-audio.js');
  return createAudioRec(audio, bridge, {
    workletUrl: 'mock://rec-worklet.js',
    WorkletNode: MockWorkletNode,
    ...(extra || {}),
  });
}

// сообщение-чанк как его отдал бы настоящий воркл ет
function chunkMsg(seq, frames, peak) {
  const buf = new Int16Array(frames);
  for (let i = 0; i < frames; i++) buf[i] = Math.round(16000 * Math.sin(i / 7));
  return {
    type: 'chunk', label: 'x', seq, frames, channels: 1,
    peak: peak === undefined ? 16000 : peak,     // 0 — это тоже значение пика
    rms: 11000, buf,
  };
}

// ---- 2. отводы пре-фейдерные ----------------------------------------------

console.log('\n2. отводы стоят ДО ползунков громкости');
{
  const { audio, ctx } = setup();
  const bridge = { rec_chunk: async () => {} };
  const rec = await makeRec(audio, bridge);
  await rec.start();
  await audio.loadTrack(loopFile);
  await audio.toggleMic();

  const taps = audio.getTaps();
  const trackNode = ctx.nodes.find((n) => n.kind === 'worklet' && n.options.processorOptions.label === 'loop');
  const micNode = ctx.nodes.find((n) => n.kind === 'worklet' && n.options.processorOptions.label === 'mic');
  const trackSrc = ctx.nodes.filter((n) => n.kind === 'bufsrc')[1];
  const micSrc = ctx.nodes.find((n) => n.kind === 'streamsrc');

  ok(ctx.added.length === 1 && ctx.added[0] === 'mock://rec-worklet.js',
    'модуль воркл ета зарегистрирован ровно один раз');
  ok(trackNode.options.numberOfOutputs === 0 && micNode.options.numberOfOutputs === 0,
    'отводы — тупики: numberOfOutputs 0');
  ok(trackNode.options.channelCount === 2 && micNode.options.channelCount === 1,
    'каналов: луп 2, микрофон 1');
  ok(inputsOf(ctx, trackNode)[0] === taps.track && taps.track !== undefined,
    'отвод лупа висит на trackPre');
  ok(inputsOf(ctx, micNode)[0] === taps.mic, 'отвод микрофона висит на micPre');

  const beforeTap = pathGain(ctx, trackSrc, trackNode);
  const beforeOut = pathGain(ctx, trackSrc, ctx.destination);
  const beforeMicTap = pathGain(ctx, micSrc, micNode);
  audio.setTrackGain(0.1);
  audio.setMicGain(0.1);
  const afterTap = pathGain(ctx, trackSrc, trackNode);
  const afterOut = pathGain(ctx, trackSrc, ctx.destination);
  const afterMicTap = pathGain(ctx, micSrc, micNode);

  ok(beforeTap === 1 && afterTap === 1,
    'ползунок трека НЕ трогает сигнал на отводе (1 → 1)', beforeTap + ' → ' + afterTap);
  ok(beforeMicTap === 1 && afterMicTap === 1,
    'ползунок микрофона НЕ трогает сигнал на отводе', beforeMicTap + ' → ' + afterMicTap);
  ok(beforeOut > afterOut && afterOut === 0.1,
    'ползунок трека меняет ТОЛЬКО мониторинг', beforeOut + ' → ' + afterOut);
  ok(pathTo(ctx, trackNode, ctx.destination) === null
    && pathTo(ctx, micNode, ctx.destination) === null,
    'ни один отвод не доходит до колонок');

  await rec.stop();
  ok(inputsOf(ctx, trackNode).length === 0 && inputsOf(ctx, micNode).length === 0,
    'stop() снял отводы с точек съёма');
  ok(trackNode.cmds.some((c) => c.cmd === 'flush'), 'stop() попросил хвост (flush)');
  audio.dispose();
}

// ---- 3. насос ждёт ответа моста -------------------------------------------

console.log('\n3. насос: следующий чанк — только после ответа на предыдущий');
{
  const { audio, ctx } = setup();
  const arrived = { loop: [], mic: [] };
  const inFlight = { loop: 0, mic: 0 };
  let overlap = 0;
  const sent = [];
  // Ранние вызовы отвечают МЕДЛЕННЕЕ поздних: при отправке пачкой (мост даёт
  // поток Python на вызов и порядок не держит) чанки приехали бы как 2,1,0.
  const delays = [60, 25, 0];
  const bridge = {
    rec_chunk(track, seq, b64) {
      inFlight[track]++;
      if (inFlight[track] > 1) overlap++;
      sent.push({ track, seq, b64 });
      return new Promise((res) => setTimeout(() => {
        inFlight[track]--;
        arrived[track].push(seq);
        res(null);
      }, delays[seq] || 0));
    },
  };
  const rec = await makeRec(audio, bridge);
  await rec.start();
  const trackNode = ctx.nodes.find((n) => n.kind === 'worklet' && n.options.processorOptions.label === 'loop');
  const micNode = ctx.nodes.find((n) => n.kind === 'worklet' && n.options.processorOptions.label === 'mic');

  for (let i = 0; i < 3; i++) trackNode.emit(chunkMsg(i, 480));
  micNode.emit(chunkMsg(0, 480));
  ok(sent.length <= 2, 'в мост ушло не больше одного чанка на дорожку сразу',
    'вызовов: ' + sent.length);

  await rec.stop();
  ok(arrived.loop.join(',') === '0,1,2', 'seq дорожки строго по возрастанию',
    arrived.loop.join(','));
  ok(overlap === 0, 'ни одного одновременного вызова на дорожку', 'наложений: ' + overlap);

  const s = rec.stats();
  ok(s.tracks.loop.chunks === 3 && s.tracks.mic.chunks === 1, 'посчитаны все чанки',
    JSON.stringify({ t: s.tracks.loop.chunks, m: s.tracks.mic.chunks }));
  ok(s.tracks.loop.bytes === 3 * 480 * 2, 'посчитаны байты (int16 = 2 байта на сэмпл)',
    'bytes=' + s.tracks.loop.bytes);
  ok(s.tracks.loop.peak === 16000 && s.tracks.loop.silent === false,
    'максимальный пик доехал до статистики', 'peak=' + s.tracks.loop.peak);
  ok(s.errors === 0 && s.error === null, 'ошибок нет', JSON.stringify(s.error));

  // base64 — не «поле пришло», а те же сэмплы: раскодируем обратно
  const back = sent[0].b64;
  const raw = Buffer.from(back, 'base64');
  const view = new Int16Array(raw.buffer, raw.byteOffset, raw.byteLength / 2);
  let pk = 0;
  for (let i = 0; i < view.length; i++) { const v = view[i] < 0 ? -view[i] : view[i]; if (v > pk) pk = v; }
  ok(raw.byteLength === 960, 'base64 несёт ровно 960 байт', 'байт: ' + raw.byteLength);
  ok(pk > 1000, 'раскодированный чанк содержит сигнал, а не тишину', 'peak=' + pk);
  audio.dispose();
}

// ---- 4. очередь растёт: ошибка наружу, а не тихая утечка -------------------

console.log('\n4. мост не успевает — беда видна сразу');
{
  const { audio, ctx } = setup();
  let release = null;
  const bridge = { rec_chunk: () => new Promise((r) => { release = r; }) };  // висит
  const errs = [];
  const rec = await makeRec(audio, bridge, {
    maxQueue: 4,
    onError: (track, msg) => errs.push({ track, msg }),
  });
  await rec.start();
  const trackNode = ctx.nodes.find((n) => n.kind === 'worklet' && n.options.processorOptions.label === 'loop');
  for (let i = 0; i < 12; i++) trackNode.emit(chunkMsg(i, 480));
  await sleep(10);

  const s = rec.stats();
  ok(s.tracks.loop.queued <= 4, 'очередь не растёт выше потолка',
    'в очереди: ' + s.tracks.loop.queued);
  ok(s.tracks.loop.dropped >= 7, 'лишние чанки честно посчитаны потерянными',
    'dropped=' + s.tracks.loop.dropped);
  ok(s.tracks.loop.lostFrames >= 7 * 480, 'потерянные кадры посчитаны',
    'lostFrames=' + s.tracks.loop.lostFrames);
  ok(errs.length === 1 && errs[0].track === 'loop', 'onError позвали ровно один раз на дорожку',
    'вызовов: ' + errs.length);
  ok(/не успевает/.test(s.error || ''), 'ошибка честная и по-русски', s.error);
  ok(s.tracks.mic.error === null, 'вторая дорожка не оболгана чужой бедой');

  if (release) release(null);
  await rec.stop();
  ok(rec.stats().tracks.loop.error !== null, 'после stop() беда не стёрлась');
  audio.dispose();
}

// ---- 5. отказ моста на отдельном чанке -------------------------------------

console.log('\n5. мост отверг чанк — запись продолжается, ошибка записана');
{
  const { audio, ctx } = setup();
  const seen = [];
  const bridge = {
    async rec_chunk(track, seq) {
      if (seq === 1) throw new Error('диск переполнен');
      seen.push(seq);
    },
  };
  const rec = await makeRec(audio, bridge);
  await rec.start();
  const trackNode = ctx.nodes.find((n) => n.kind === 'worklet' && n.options.processorOptions.label === 'loop');
  for (let i = 0; i < 3; i++) trackNode.emit(chunkMsg(i, 480));
  await rec.stop();
  const s = rec.stats();
  ok(seen.join(',') === '0,2', 'потерян только отвергнутый чанк, остальные ушли', seen.join(','));
  ok(s.tracks.loop.chunks === 2 && s.tracks.loop.errors === 1, 'счётчики честные',
    JSON.stringify({ chunks: s.tracks.loop.chunks, errors: s.tracks.loop.errors }));
  ok(/диск переполнен/.test(s.error || ''), 'текст ошибки моста сохранён', s.error);
  audio.dispose();
}

// ---- 6. запись без сигнала видна ------------------------------------------

console.log('\n6. тишина в файле не выдаётся за успех');
{
  const { audio, ctx } = setup();
  const rec = await makeRec(audio, { rec_chunk: async () => {} });
  await rec.start();
  const trackNode = ctx.nodes.find((n) => n.kind === 'worklet' && n.options.processorOptions.label === 'loop');
  const silent = chunkMsg(0, 480, 0);
  silent.buf.fill(0);
  silent.rms = 0;
  trackNode.emit(silent);
  await rec.stop();
  const s = rec.stats();
  ok(s.tracks.loop.chunks === 1 && s.tracks.loop.silent === true,
    'чанк доехал, но помечен как тишина (счётчики зелёные — сигнала нет)',
    JSON.stringify({ chunks: s.tracks.loop.chunks, silent: s.tracks.loop.silent }));
  ok(s.sampleRate === 48000, 'частота дискретизации отдана наружу для WAV-заголовка');
  audio.dispose();
}

// ---- 7. питон ответил {ok:false} — это отказ, а не успех -------------------
// Мост почти никогда не бросает исключение: launch.py отвечает объектом.
// Считать такой ответ успехом — значит получить зелёные счётчики поверх дырки
// в файле, то есть ровно тот сбой, ради которого вся эта проверка и живёт.

console.log('\n7. ответ {ok:false} от питона считается потерей, а не успехом');
{
  const { audio, ctx } = setup();
  const errs = [];
  const bridge = {
    async rec_chunk(track, seq) {
      if (seq === 1) return { ok: false, error: 'дорожка loop: чанк 1 потерян — в записи дырка' };
      return { ok: true, bytes: 960, total: 960, peak: 0.5 };
    },
  };
  const rec = await makeRec(audio, bridge, { onError: (track, msg) => errs.push({ track, msg }) });
  await rec.start();
  const loopNode = ctx.nodes.find((n) => n.kind === 'worklet' && n.options.processorOptions.label === 'loop');
  for (let i = 0; i < 3; i++) loopNode.emit(chunkMsg(i, 480));
  await rec.stop();
  const s = rec.stats();
  ok(s.tracks.loop.chunks === 2, 'отвергнутый чанк не посчитан доехавшим',
    'chunks=' + s.tracks.loop.chunks);
  ok(s.tracks.loop.lostFrames === 480, 'потерянные кадры посчитаны', 'lostFrames=' + s.tracks.loop.lostFrames);
  ok(/дырка/.test(s.tracks.loop.error || ''), 'текст питона доехал до статистики', s.tracks.loop.error);
  ok(errs.length === 1 && errs[0].track === 'loop', 'беда ушла наружу ровно один раз',
    'вызовов: ' + errs.length);
  audio.dispose();
}

console.log('\n' + (failed ? 'ПРОВАЛЕНО проверок: ' + failed : 'все проверки пройдены'));
process.exit(failed ? 1 : 0);
