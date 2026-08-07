// Юнит-проверка аудио-графа фристайла на подменённом AudioContext.
// Пакета 'web-audio-api' в проекте нет и ставить его ради теста незачем:
// проверяем не звук, а МАРШРУТИЗАЦИЮ — кто с кем соединён и куда едут гейны.
// Запуск: cd interface/react-app && node src/nl/freestyle/audio.test.mjs

import { createAudio } from './audio.js';

// ---- мок Web Audio --------------------------------------------------------

let uid = 0;

class P {                                  // AudioParam
  constructor(v) { this.value = v; this.target = v; this.calls = []; }
  cancelScheduledValues(t) { this.calls.push(['cancel', t]); }
  setValueAtTime(v, t) { this.value = v; this.target = v; this.calls.push(['set', v, t]); }
  setTargetAtTime(v, t, tau) { this.target = v; this.value = v; this.calls.push(['ramp', v, t, tau]); }
  // cancelAndHoldAtTime намеренно отсутствует — заодно проверяем запасной путь
}

class N {                                  // AudioNode
  constructor(ctx, kind) {
    this.ctx = ctx; this.kind = kind; this.id = ++uid;
    this.disconnects = 0;
    ctx.nodes.push(this);
  }
  connect(dst) {
    if (dst instanceof P) ctx0(this).paramEdges.push([this, dst]);
    else ctx0(this).edges.push([this, dst]);
    return dst;
  }
  disconnect() { this.disconnects++; }
}
function ctx0(n) { return n.ctx; }

class Gain extends N {
  constructor(ctx) { super(ctx, 'gain'); this.gain = new P(1); }
}
class Analyser extends N {
  constructor(ctx) { super(ctx, 'analyser'); this.fftSize = 2048; this.smoothingTimeConstant = 0; }
}
class Osc extends N {
  constructor(ctx) { super(ctx, 'osc'); this.frequency = new P(440); this.started = false; this.stopped = false; }
  start() { this.started = true; }
  stop() { this.stopped = true; }
}
class BufSrc extends N {
  constructor(ctx) { super(ctx, 'bufsrc'); this.buffer = null; this.loop = false; this.started = false; this.stopped = false; }
  start() { this.started = true; }
  stop() { this.stopped = true; }
}
class StreamSrc extends N {
  constructor(ctx, stream) { super(ctx, 'streamsrc'); this.stream = stream; }
}

class MockCtx {
  constructor(o) {
    this.opts = o || {};
    this.sampleRate = this.opts.sampleRate || 44100;
    this.state = 'suspended';
    this.currentTime = 0;
    this.nodes = [];
    this.edges = [];
    this.paramEdges = [];
    this.closed = false;
    this.destination = new N(this, 'destination');
  }
  createGain() { return new Gain(this); }
  createAnalyser() { return new Analyser(this); }
  createOscillator() { return new Osc(this); }
  createBufferSource() { return new BufSrc(this); }
  createMediaStreamSource(s) { return new StreamSrc(this, s); }
  createBuffer(ch, len, sr) {
    const data = new Float32Array(len);
    return { numberOfChannels: ch, length: len, sampleRate: sr, duration: len / sr, getChannelData: () => data };
  }
  async decodeAudioData() { return this.createBuffer(2, 48000, this.sampleRate); }
  async resume() { this.state = 'running'; }
  async close() { this.closed = true; this.state = 'closed'; }
}

let lastCtx = null;
let ctorArgs = null;
function MockAudioContext(o) {
  ctorArgs = o;
  const c = new MockCtx(o);
  lastCtx = c;
  return c;
}

// ---- утиль ----------------------------------------------------------------

let failed = 0;
function ok(cond, name, extra) {
  if (cond) { console.log('  ok   ' + name); return; }
  failed++;
  console.log('  FAIL ' + name + (extra ? ' — ' + extra : ''));
}

function reaches(ctx, from, to) {         // достижимость по звуковым связям
  const seen = new Set([from]);
  const q = [from];
  while (q.length) {
    const n = q.shift();
    if (n === to) return true;
    for (const [a, b] of ctx.edges) if (a === n && !seen.has(b)) { seen.add(b); q.push(b); }
  }
  return false;
}
function inputsOf(ctx, node) { return ctx.edges.filter(([, b]) => b === node).map(([a]) => a); }
function outputsOf(ctx, node) { return ctx.edges.filter(([a]) => a === node).map(([, b]) => b); }

const track = { name: 'loop.wav', arrayBuffer: async () => new ArrayBuffer(16) };
const micTracks = [{ stop() { this.stopped = true; }, stopped: false }];
const stream = { getTracks: () => micTracks };

// ---- прогон ---------------------------------------------------------------

const vis = { calls: [], connectAudio(n) { this.calls.push(n); }, disconnectAudio() {} };

const audio = createAudio({
  AudioContextCtor: MockAudioContext,
  getUserMedia: async () => stream,
});

console.log('\n0. сборка графа');
audio.start();
const ctx = lastCtx;
const driver = audio.getDriver();
ok(ctorArgs && ctorArgs.sampleRate === 48000, 'AudioContext просит 48000',
  JSON.stringify(ctorArgs));
ok(ctorArgs && ctorArgs.latencyHint === 'playback', "latencyHint 'playback'");

const noise = ctx.nodes.find((n) => n.kind === 'bufsrc');
const lfo = ctx.nodes.find((n) => n.kind === 'osc');
const gains = ctx.nodes.filter((n) => n.kind === 'gain');
const trackGain = gains.find((g) => outputsOf(ctx, g).includes(ctx.destination));
const synthGain = gains.find((g) => g !== driver && outputsOf(ctx, g).includes(driver) && reaches(ctx, noise, g));
// micGain: на шину идёт, из шума не питается и в колонки не заходит
// (последнее и отличает его от trackGain)
const micGain = gains.find((g) => g !== driver && g !== synthGain
  && outputsOf(ctx, g).includes(driver)
  && !reaches(ctx, noise, g)
  && !outputsOf(ctx, g).includes(ctx.destination));

ok(!!noise && noise.loop === true && noise.started, 'кольцо шума заведено и зациклено');
ok(!!lfo && lfo.started, 'медленный LFO заведён');
ok(ctx.paramEdges.length === 1, 'LFO модулирует амплитуду через AudioParam');
ok(!!synthGain && !!trackGain && !!micGain, 'нашлись synthGain / trackGain / micGain');
ok(!reaches(ctx, driver, ctx.destination), 'шина водителя НЕ доходит до колонок');
ok(outputsOf(ctx, driver).some((n) => n.kind === 'analyser'), 'на шине висит терминальный анализатор (automatic pull)');
ok(!reaches(ctx, synthGain, ctx.destination), 'синтетика не слышна');

audio.attachVisualizer(vis);
ok(vis.calls.length === 1 && vis.calls[0] === driver, 'визуализатор подключён к driverBus');

console.log('\n1. луп: слышен и водит картинку');
ctx.currentTime = 1;
await audio.loadTrack(track);
const trackSrc = ctx.nodes.filter((n) => n.kind === 'bufsrc')[1];
ok(!!trackSrc && trackSrc.loop === true && trackSrc.started, 'луп бесконечный и запущен');
ok(reaches(ctx, trackSrc, ctx.destination), 'луп слышен');
ok(reaches(ctx, trackSrc, driver), 'луп водит картинку');
const audiblePath = outputsOf(ctx, trackGain);
ok(audiblePath.includes(ctx.destination), 'слышимый тракт прямой: trackGain → destination');
ok(!outputsOf(ctx, trackSrc).some((n) => n.kind === 'analyser'), 'в слышимом тракте нет анализаторов');
// (2) synthGain целевое 0, осциллятор жив
ok(synthGain.gain.target === 0, 'после loadTrack synthGain → 0', 'target=' + synthGain.gain.target);
ok(synthGain.gain.calls.some((c) => c[0] === 'ramp' && c[3] > 0), 'ушёл рампой, а не скачком');
ok(noise.stopped === false && lfo.stopped === false, 'генератор синтетики НЕ остановлен');
ok(trackGain.gain.target > 0, 'trackGain поднят');
let st = audio.state();
ok(st.synthetic === false && st.track && st.track.name === 'loop.wav', 'state(): водит луп',
  JSON.stringify(st));

console.log('\n2. микрофон параллельно лупу');
ctx.currentTime = 2;
const micOn = await audio.toggleMic();
const micNode = ctx.nodes.find((n) => n.kind === 'streamsrc');
ok(micOn === true && audio.state().mic === true, 'микрофон включился');
ok(reaches(ctx, micNode, driver), 'микрофон водит картинку');
// (4) микрофон никогда не соединён с destination
ok(!reaches(ctx, micNode, ctx.destination), 'микрофон НЕ доходит до колонок (нет обратной связи)');
ok(!reaches(ctx, micGain, ctx.destination), 'micGain НЕ доходит до колонок');
ok(audio.state().track !== null, 'луп продолжает играть вместе с микрофоном');

console.log('\n3. снятие лупа: синтетика подхватывает');
ctx.currentTime = 3;
const nodesBefore = ctx.nodes.length;
audio.stopTrack();
// (3) synthGain вернулся
ok(synthGain.gain.target > 0, 'после stopTrack synthGain вернулся', 'target=' + synthGain.gain.target);
ok(trackGain.gain.target === 0, 'trackGain ушёл в 0');
ok(ctx.nodes.length === nodesBefore, 'ни одного нового узла — подхват мгновенный',
  nodesBefore + ' → ' + ctx.nodes.length);
ok(trackSrc.stopped === true, 'источник лупа остановлен');
ok(noise.stopped === false, 'кольцо шума всё ещё крутится');
st = audio.state();
ok(st.synthetic === true && st.track === null, 'state(): снова водит синтетика', JSON.stringify(st));

console.log('\n4. повторный цикл и инварианты');
ctx.currentTime = 4;
await audio.loadTrack(track);
audio.stopTrack();
await audio.toggleMic();                    // выключаем микрофон
audio.setTrackGain(0.5);
audio.setMicGain(2);                        // должен зажаться в 1
// (1) визуализатор подключён ровно один раз за жизнь
ok(vis.calls.length === 1, 'визуализатор подключался РОВНО один раз за жизнь',
  'вызовов: ' + vis.calls.length);
ok(driver.disconnects === 0, 'шину водителя ни разу не отключали');
ok(!reaches(ctx, driver, ctx.destination), 'шина по-прежнему не доходит до колонок');
ok(!ctx.nodes.some((n) => n.kind === 'streamsrc' && reaches(ctx, n, ctx.destination)),
  'ни один микрофонный узел за всю жизнь не попал в destination');

audio.dispose();
ok(ctx.closed === true, 'dispose() закрыл контекст');
ok(noise.stopped === true, 'dispose() остановил синтетику');

console.log('\n' + (failed ? 'ПРОВАЛЕНО проверок: ' + failed : 'все проверки пройдены'));
process.exit(failed ? 1 : 0);
