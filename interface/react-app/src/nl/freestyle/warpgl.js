// Слой строки на видеокарте (Раунд 57).
//
// ЗАЧЕМ. Искажение строки во фристайле делал SVG-фильтр `#nl-text-warp`:
// feTurbulence + feDisplacementMap. Карта смещения читает каждый пиксель,
// поэтому строка обязана рисоваться на процессоре, а потом ждать очереди на
// видеокарте, занятой Butterchurn. Замерено в приложении владельца, перебором
// раскладок по кругу (кадр покоя 33 мс — видеокарта уже под завязку):
//     как было (три слоя свечения + фильтр)   ~1170 мс на смену строки
//     без слоёв свечения                       ~700 мс
//     без фильтра строки                       ~350 мс
//     голый текст                                33 мс
// Платит не текст, а каждый слой с `filter`. После переноса сюда — 15-25 мс,
// то есть дешевле обычного кадра: смена строки перестала быть событием.
//
// ЧТО ПРОБОВАЛИ И ОТКЛОНИЛИ (стенд с настоящим WebGL под текстом, пол 33-34 мс):
//     шум испечён заранее, feImage вместо feTurbulence   241 против 265 — почти
//         ничего: дорога не турбулентность, а сама карта смещения;
//     фильтр на мелком растре ×2 / ×3            83 / 50 мс — но буквы мылятся;
//     сдвиг знаков через transform                   38 мс — владелец посмотрел:
//         «очень некрасивое искажение, бредовое». И по существу верно: фильтр
//         плавит очертания ИЗНУТРИ, а сдвиг двигает буквы целиком.
//
// ЧТО ЗДЕСЬ. Тот же приём, что у фильтра: текст пишется в текстуру (это стоит
// один раз на смену строки), а смещение считает шейдер по той же логике —
// fractalNoise в две октавы, частота 0.008 по X и 0.02 по Y в CSS-пикселях,
// смещение = scale × (значение − 0.5), scale = искажение/12. ВРЕМЕНИ В ШЕЙДЕРЕ
// НЕТ: один и тот же текст искажается одинаково. Владелец сверил бок о бок со
// своим фильтром: «идентично выглядит, разницы нет визуально». И отдельно
// потребовал не выдумывать анимаций.
//
// ГРАБЛИ, все ловились замером и ни одна — глазом, и все давали чёрный или
// белый экран без единого сообщения:
//   1. русские имена переменных внутри GLSL — там только латиница, компилятор
//      молча отвергает весь шейдер, не давая лога вообще;
//   2. свечение обычным fillText с тенью кладёт на холст и САМИ БУКВЫ — четыре
//      прохода сливаются в белое пятно. Буквы уводим за край, остаётся тень;
//   3. `texture2D(...).rgb` без alpha: ореол хранится ПРОЗРАЧНОСТЬЮ белого, и
//      любая его точка выходила полностью белой.

const ВЕРШ = 'attribute vec2 p; varying vec2 uv;'
  + 'void main(){ uv = p*0.5+0.5; gl_Position = vec4(p,0.,1.); }';

const ШУМ = [
  'precision highp float;',
  'varying vec2 uv;',
  'uniform sampler2D tex;',
  'uniform vec2 res;',
  'uniform float scale, dpr, sigma, aber, bright;',
  'float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.5453); }',
  'float vnoise(vec2 p){',
  '  vec2 i = floor(p), f = fract(p);',
  '  vec2 u = f*f*(3.0-2.0*f);',
  '  return mix(mix(hash(i), hash(i+vec2(1.0,0.0)), u.x),',
  '             mix(hash(i+vec2(0.0,1.0)), hash(i+vec2(1.0,1.0)), u.x), u.y);',
  '}',
  'float fractal(vec2 p){ return 0.6667*vnoise(p) + 0.3333*vnoise(p*2.0); }',
].join('\n');

// РАЗМЫТИЕ — ГАУСС В ДВА ПРОХОДА, А НЕ ОДНО КОЛЬЦЕВОЕ ЯДРО.
//
// Первая версия брала центр и два кольца по восемь точек — семнадцать выборок
// на пиксель. Владелец прислал снимок: вместо размытия видны ступеньки и резкие
// границы. Так и должно быть: на большом радиусе кольцевое ядро даёт не
// размытие, а несколько сдвинутых копий буквы.
//
// Проход 1: смещение (с хроматикой по каналам) и размытие по горизонтали.
// Проход 2: размытие по вертикали и яркость.
function проход(гориз, первый) {
  const шаг = гориз ? 'vec2(1.0, 0.0)' : 'vec2(0.0, 1.0)';
  const голова = первый ? [
    '  vec2 px = gl_FragCoord.xy / dpr;',
    '  vec2 f = vec2(0.008, 0.02);',
    '  vec2 n = vec2(fractal(px*f), fractal(px*f + vec2(37.3, 11.7))) - 0.5;',
    // ХРОМАТИКА: те же три смещения, что #nl-text-warp-aber делал тремя картами
    // смещения плюс размытием, — здесь это три выборки вместо трёх фильтров.
    '  vec2 dR = n * (scale + aber) * dpr / res;',
    '  vec2 dG = n * scale * dpr / res;',
    '  vec2 dB = n * (scale - aber) * dpr / res;',
  ].join('\n') : '';
  const тело = первый ? [
    '    vec4 cr = texture2D(tex, uv + dR + sh);',
    '    vec4 cg = texture2D(tex, uv + dG + sh);',
    '    vec4 cb = texture2D(tex, uv + dB + sh);',
    '    sum += vec4(cr.r*cr.a, cg.g*cg.a, cb.b*cb.a, (cr.a+cg.a+cb.a)/3.0) * w;',
  ].join('\n') : '    sum += texture2D(tex, uv + sh) * w;';
  return [
    ШУМ,
    'void main(){',
    '  vec2 stp = ' + шаг + ' / res;',
    голова,
    '  vec4 sum = vec4(0.0); float wsum = 0.0;',
    '  float s = max(sigma, 0.0001);',
    '  for (int i = -8; i <= 8; i++) {',
    '    float o = float(i) * s * 0.375;',
    '    float w = exp(-(o*o) / (2.0*s*s));',
    '    vec2 sh = stp * o;',
    тело,
    '    wsum += w;',
    '  }',
    '  vec4 c = sum / wsum;',
    первый ? '  gl_FragColor = c;' : '  gl_FragColor = vec4(c.rgb * bright, c.a);',
    '}',
  ].join('\n');
}

function собрать(gl, тип, код, беда) {
  const s = gl.createShader(тип);
  gl.shaderSource(s, код);
  gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
    // Молча чёрное недопустимо: консоли в окне владельца нет, а компилятор
    // часто не даёт и лога — тогда причина почти всегда не-латинский символ.
    беда('шейдер строки не собрался: '
      + (gl.getShaderInfoLog(s) || '(без сообщения — обычно не-латинский символ в GLSL)'));
    return null;
  }
  return s;
}

export function создатьВарп(canvas, беда) {
  const gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false });
  if (!gl) { беда('видеокарта недоступна для слоя строки'); return null; }

  function программа(код) {
    const в = собрать(gl, gl.VERTEX_SHADER, ВЕРШ, беда);
    const ф = собрать(gl, gl.FRAGMENT_SHADER, код, беда);
    if (!в || !ф) return null;
    const пр = gl.createProgram();
    gl.attachShader(пр, в); gl.attachShader(пр, ф); gl.linkProgram(пр);
    if (!gl.getProgramParameter(пр, gl.LINK_STATUS)) {
      беда('программа слоя строки не слинковалась: ' + gl.getProgramInfoLog(пр));
      return null;
    }
    return пр;
  }
  const прогA = программа(проход(true, true));
  const прогB = программа(проход(false, false));
  if (!прогA || !прогB) return null;

  const буф = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, буф);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  [прогA, прогB].forEach(function (пр) {
    gl.useProgram(пр);
    const ап = gl.getAttribLocation(пр, 'p');
    gl.enableVertexAttribArray(ап);
    gl.vertexAttribPointer(ап, 2, gl.FLOAT, false, 0, 0);
  });

  function текстура() {
    const т = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, т);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    return т;
  }
  const тексИсход = текстура();
  const тексПромеж = текстура();
  const кадр = gl.createFramebuffer();
  let пШ = 0, пВ = 0;

  function ставим(пр, w, h, scale, dpr, sigma, aber, bright) {
    gl.useProgram(пр);
    gl.uniform2f(gl.getUniformLocation(пр, 'res'), w, h);
    gl.uniform1f(gl.getUniformLocation(пр, 'scale'), scale);
    gl.uniform1f(gl.getUniformLocation(пр, 'dpr'), dpr);
    gl.uniform1f(gl.getUniformLocation(пр, 'sigma'), sigma);
    gl.uniform1f(gl.getUniformLocation(пр, 'aber'), aber);
    gl.uniform1f(gl.getUniformLocation(пр, 'bright'), bright);
  }

  return {
    жив: true,
    рисовать(тк, scale, dpr, blurPx, bright, aberPx) {
      if (!тк.width || !тк.height) return;
      const w = тк.width, h = тк.height;
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      if (пШ !== w || пВ !== h) {
        пШ = w; пВ = h;
        gl.bindTexture(gl.TEXTURE_2D, тексПромеж);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      }
      gl.bindTexture(gl.TEXTURE_2D, тексИсход);
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, тк);

      const s = Math.max(0.0001, blurPx || 0);
      gl.viewport(0, 0, w, h);
      gl.clearColor(0, 0, 0, 0);

      gl.bindFramebuffer(gl.FRAMEBUFFER, кадр);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, тексПромеж, 0);
      ставим(прогA, w, h, scale, dpr, s, aberPx || 0, 1);
      gl.bindTexture(gl.TEXTURE_2D, тексИсход);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      ставим(прогB, w, h, scale, dpr, s, 0, bright == null ? 1 : bright);
      gl.bindTexture(gl.TEXTURE_2D, тексПромеж);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    },
    уничтожить() {
      try {
        const l = gl.getExtension('WEBGL_lose_context');
        if (l) l.loseContext();
      } catch (e) { /* терять нечего */ }
    },
  };
}

// Текст в холст: перенос по ширине, свечение теми же радиусами, что text-shadow.
//
// Свечение рисуется БЕЗ ЗАЛИВКИ: буквы уводятся далеко за левый край, а тень
// сдвигается ровно на столько же обратно, поэтому на холст попадает только
// ореол. Иначе каждый проход кладёт ещё и сами буквы, и четыре прохода дают
// сплошное белое пятно — проверено замером: 25% ярких, 0.1% полутонов.
//
// Размытие и яркость здесь НЕ ДЕЛАЮТСЯ: `ctx.filter` в WKWebView отсутствует
// (проверено на машине владельца — журнал сказал прямо), их делает шейдер.
export function испечьТекст(тк, тx, opts) {
  const { текст, ширина, высота, кегль, жир, семья, цвет, свечение, выравн, dpr } = opts;
  тк.width = Math.max(1, Math.round(ширина * dpr));
  тк.height = Math.max(1, Math.round(высота * dpr));
  тx.clearRect(0, 0, тк.width, тк.height);
  тx.font = жир + ' ' + Math.round(кегль * dpr) + 'px ' + семья;
  тx.textBaseline = 'middle';
  тx.textAlign = выравн;

  const макс = тк.width * 0.98;
  const ряды = [];
  String(текст).split('\n').forEach(function (абзац) {
    const слова = абзац.split(' ');
    let cur = '';
    for (let i = 0; i < слова.length; i++) {
      const проба = cur ? cur + ' ' + слова[i] : слова[i];
      if (cur && тx.measureText(проба).width > макс) { ряды.push(cur); cur = слова[i]; }
      else cur = проба;
    }
    ряды.push(cur);
  });

  const шаг = кегль * dpr * 1.06;
  const верх = тк.height / 2 - (ряды.length - 1) * шаг / 2;
  const x = выравн === 'left' ? 0 : (выравн === 'right' ? тк.width : тк.width / 2);

  if (свечение > 0) {
    const g = свечение;
    const ор = [[24 + g * 0.3, 0.40], [12 + g * 0.1, 0.60], [5 + g * 0.05, 0.85]];
    const ОТ = тк.width + 800;
    тx.fillStyle = '#000000';
    for (let о = 0; о < ор.length; о++) {
      тx.shadowColor = 'rgba(' + цвет + ',' + ор[о][1] + ')';
      тx.shadowBlur = ор[о][0] * dpr;
      тx.shadowOffsetX = ОТ;
      for (let i = 0; i < ряды.length; i++) тx.fillText(ряды[i], x - ОТ, верх + i * шаг);
    }
    тx.shadowColor = 'transparent'; тx.shadowBlur = 0; тx.shadowOffsetX = 0;
  }
  тx.fillStyle = 'rgb(' + цвет + ')';
  for (let i = 0; i < ряды.length; i++) тx.fillText(ряды[i], x, верх + i * шаг);
  return { рядов: ряды.length };
}
