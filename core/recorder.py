# extendo/nakedlunch — питон-сторона записи фристайла (PLAN.md, ФАЗА 4).
#
# ЧТО ЗДЕСЬ ПРОИСХОДИТ. Браузерная сторона снимает окно через getDisplayMedia
# (решение пользователя 2026-08-01: захват окна + режим записи, композитный канвас
# НЕ делаем) и параллельно отводит два аудиопотока AudioWorklet'ами. Всё это
# сыплется в питон через мост pywebview кусками. Здесь куски превращаются в
# ТРИ РАЗДЕЛЬНЫХ ФАЙЛА: видео окна, микрофон, луп. Раздельность — требование
# пользователя: сводить будем потом, исходники не трогаем никогда.
#
# ПОЧЕМУ ИМЕННО ТАК (цифры — с замеров спайка фазы 4 на этой машине, не из
# головы):
#
# 1. Инкрементальная запись с плейсхолдерным заголовком. WAV открывается сразу
#    с 44-байтным заголовком, где размеры стоят нулями, PCM дописывается в
#    конец, раз в 0.25с заголовок перепрошивается настоящими размерами. После
#    любой перепрошивки файл валиден для любого читателя, даже если процесс
#    тут же убьют. Проверено: 7 из 7 SIGKILL оставили WAV, который открывается
#    модулем wave, с целыми сэмплами. Потеря = интервал перепрошивки, поэтому
#    он 0.25с (замерено: одна перепрошивка 0.42мс, CPU 0.29% — можно себе
#    позволить).
#
# 2. Заголовок перепрошивается ОДНИМ write на 44 байта. Две отдельные правки
#    по 4 байта (размер RIFF и размер data) рвут заголовок, если процесс убьют
#    между ними: файл будет обещать одно, а содержать другое. Одиночный write
#    в обычный файл ядро выполняет целиком.
#
# 3. fsync ДАННЫХ ПЕРЕД ЗАГОЛОВКОМ, порядок принципиален. Если наоборот, то
#    после аварии заголовок пообещает больше байт, чем реально лежит на диске,
#    и читатель упрётся в обрыв.
#
# 4. .partial + os.replace. Пока идёт запись, на диске лежит «имя.partial»;
#    финальное имя появляется атомарно и только целым. Оборванная запись видна
#    по расширению, а не по тому, что файл «какой-то странный».
#
# 5. ПИК И RMS ПО КАЖДОМУ ЧАНКУ. Это не украшение. В спайке уже случилась
#    ровно эта ошибка: Float32 из диапазона -1..1 записали прямо в Int16Array,
#    всё усеклось в нули, файл оказался чистой тишиной — а ВСЕ счётчики кадров
#    были зелёные и дропов ноль. Поэтому writer сам считает пик по Int16 при
#    записи: «в файле есть сигнал» проверяется по факту, а не по наличию поля.
#
# 6. Ловля разрыва номеров. Мост pywebview заводит НА КАЖДЫЙ ВЫЗОВ отдельный
#    поток Python (webview/util.py:335) — порядок доставки не гарантирован.
#    Поэтому чанк «из будущего» это норма: придерживаем и укладываем, когда
#    придёт предыдущий. А вот чанк, которого не дождались, — сбой, и молчать
#    о нём нельзя (пользователь: испорченную запись лучше увидеть сразу).
#
# 7. Склейка (mux) — только перекодированием. WebM от MediaRecorder это VFR
#    без длительности в заголовке (замерено: ffprobe duration = N/A), -c copy
#    даёт мусор. ffmpeg опционален: нет его — честный отказ, не падение.
#
# Модуль не знает ни про Flask, ни про webview: чистые файлы и subprocess.

from __future__ import annotations

import array
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

HEADER_LEN = 44
SAMPWIDTH = 2                      # Int16 — то, что отдаёт AudioWorklet-отвод
FLUSH_EVERY = 0.25                 # период перепрошивки/fsync, секунды (см. п.1)
SEQ_WINDOW = 32                    # сколько чанков «из будущего» придерживаем (см. п.6)
DEFAULT_ROOT = Path.home() / "Documents" / "nakedlunch" / "записи"
FFMPEG_FALLBACKS = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
MUX_NAME = "сведено.mp4"
VIDEO_EXT = (".webm", ".mp4", ".mov", ".mkv")

_NAME_RE = re.compile(r"^[A-Za-zА-Яа-я0-9_-]{1,32}$")
_EXT_RE = re.compile(r"^[A-Za-z0-9]{1,8}$")


class RecorderError(RuntimeError):
    """Доменная ошибка записи — мост переводит её в {ok: False, error: …}."""


# ---------------------------------------------------------------- порядок чанков

class _SeqGate:
    """Укладывает чанки по порядку, хотя мост доставляет их как попало.

    Мост pywebview обслуживает каждый вызов своим потоком Python, так что
    chunk(5) вполне может обогнать chunk(4). Пришедший раньше времени чанк
    придерживаем — это НЕ сбой. Сбоем считаем две вещи, и обе кричим наверх:
      * придержанных стало больше окна — значит предыдущий потерян насовсем;
      * чанк пришёл после того, как дорожка ушла вперёд, — его уже не вставить.
    В обоих случаях дорожка продолжает писаться: оборвать живую запись из-за
    дырки хуже, чем дописать её и громко сообщить о дырке.
    """

    def __init__(self, window: int = SEQ_WINDOW):
        self.expected = 0
        self.window = int(window)
        self.missing: list[int] = []
        self._pending: dict[int, bytes] = {}   # номер -> придержанный кусок

    def offer(self, seq: int, data: bytes) -> tuple[list[bytes], str | None]:
        """Вернуть (готовые к записи чанки по порядку, честный текст сбоя|None)."""
        seq = int(seq)
        if seq < self.expected:
            return [], (f"чанк {seq} пришёл, когда дорожка уже на {self.expected} — "
                        f"вставить некуда, кусок отброшен")
        if seq in self._pending:
            return [], f"чанк {seq} пришёл дважды — второй отброшен"
        self._pending[seq] = data

        problem = None
        if len(self._pending) > self.window:
            # ждать больше нечего: предыдущий чанк не придёт
            self.missing.append(self.expected)
            problem = (f"чанк {self.expected} потерян (придержано {len(self._pending)} "
                       f"следующих) — в записи дырка")
            self.expected = min(self._pending)
        return self._drain(), problem

    def close(self) -> tuple[list[bytes], str | None]:
        """Дописать всё придержанное. Непришедшие номера — честный список дырок."""
        if not self._pending:
            return [], None
        ready: list[bytes] = []
        gaps: list[int] = []
        while self._pending:
            nxt = min(self._pending)
            if nxt != self.expected:
                gaps.append(self.expected)
                self.expected = nxt
            ready.extend(self._drain())
        if gaps:
            self.missing.extend(gaps)
            return ready, ("чанки не пришли: " + ", ".join(str(g) for g in gaps) +
                           " — в записи дырки")
        return ready, None

    def _drain(self) -> list[bytes]:
        out: list[bytes] = []
        while self.expected in self._pending:
            out.append(self._pending.pop(self.expected))
            self.expected += 1
        return out


# ---------------------------------------------------------------------- писатели

class _Writer:
    """Общее для WAV и видео: .partial, периодический fsync, статус, номера."""

    kind = "?"

    def __init__(self, path, flush_every: float = FLUSH_EVERY):
        self.path = str(path)
        self.partial = self.path + ".partial"
        self.flush_every = float(flush_every)
        self.bytes_written = 0
        self.error: str | None = None        # липкий: сбой видно и потом
        self.opened_at = time.monotonic()
        self.chunks = 0
        self._last_write = 0.0
        self._last_flush = self.opened_at
        self._closed = False
        self._gate = _SeqGate()
        self._f = open(self.partial, "wb")

    # --- внутреннее --------------------------------------------------------
    def _raw_write(self, data: bytes) -> None:
        self._f.write(data)
        self.bytes_written += len(data)

    def _sync(self) -> None:
        """Дотолкать данные до диска. У WAV поверх этого ещё заголовок."""
        self._f.flush()
        os.fsync(self._f.fileno())
        self._last_flush = time.monotonic()

    def _maybe_sync(self) -> None:
        if time.monotonic() - self._last_flush >= self.flush_every:
            self._sync()

    # --- публичное ---------------------------------------------------------
    def append(self, data: bytes, seq: int | None = None) -> tuple[int, str | None]:
        """Дописать кусок. Вернуть (сколько байт легло, честный текст сбоя|None).

        seq=None — прямая запись без контроля порядка (тесты, внутренние
        вызовы). Мост всегда передаёт номер.
        """
        if self._closed:
            raise RecorderError(f"дорожка {os.path.basename(self.path)} уже закрыта")
        if seq is None:
            ready, problem = [bytes(data)], None
        else:
            ready, problem = self._gate.offer(seq, bytes(data))
        n = 0
        for chunk in ready:
            self._raw_write(chunk)
            n += len(chunk)
        if ready:
            self.chunks += len(ready)
            self._last_write = time.monotonic()
        self._maybe_sync()
        if problem:
            self.error = problem
        return n, problem

    def close(self) -> str:
        if self._closed:
            return self.path
        ready, problem = self._gate.close()
        for chunk in ready:
            self._raw_write(chunk)
        if problem:
            self.error = problem
        self._sync()                 # у WAV это ещё и финальная штамповка заголовка
        self._f.close()
        # финальное имя появляется атомарно и только целым
        os.replace(self.partial, self.path)
        self._closed = True
        return self.path

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def last_write_ago(self) -> float:
        """Сколько секунд дорожка молчит. Интерфейсу это и есть громкий сбой:
        писали-писали и перестали — значит отвод отвалился, а не «всё хорошо»."""
        ref = self._last_write or self.opened_at
        return round(time.monotonic() - ref, 3)

    def status(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path if self._closed else self.partial,
            "open": not self._closed,
            "bytes": self.bytes_written,
            "seconds": self.seconds,
            "peak": self.peak,
            "chunks": self.chunks,
            "last_write_ago": self.last_write_ago,
            "error": self.error,
        }

    # переопределяют наследники
    @property
    def seconds(self) -> float:
        return round(time.monotonic() - self.opened_at, 3)

    @property
    def peak(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class WavWriter(_Writer):
    """PCM 16 бит, дописываемый инкрементально, безопасный к SIGKILL."""

    kind = "wav"

    def __init__(self, path, channels: int = 2, rate: int = 48000,
                 flush_every: float = FLUSH_EVERY):
        self.channels = int(channels)
        self.rate = int(rate)
        if self.channels < 1 or self.rate < 1:
            raise RecorderError("каналы и частота должны быть положительными")
        self._peak = 0.0
        self._odd = b""              # хвостовой байт: пик считаем по целым сэмплам
        super().__init__(path, flush_every)
        # плейсхолдер: размеры нулевые, чинятся первой же перепрошивкой
        self._f.write(self._header(0))
        self._sync()

    def _header(self, data_len: int) -> bytes:
        byte_rate = self.rate * self.channels * SAMPWIDTH
        block_align = self.channels * SAMPWIDTH
        return b"".join([
            b"RIFF", struct.pack("<I", 36 + data_len),
            b"WAVEfmt ", struct.pack("<I", 16),
            struct.pack("<H", 1),                  # PCM без сжатия
            struct.pack("<H", self.channels),
            struct.pack("<I", self.rate),
            struct.pack("<I", byte_rate),
            struct.pack("<H", block_align),
            struct.pack("<H", SAMPWIDTH * 8),
            b"data", struct.pack("<I", data_len),
        ])

    def _raw_write(self, data: bytes) -> None:
        super()._raw_write(data)
        self._track_peak(data)

    def _track_peak(self, data: bytes) -> None:
        """Пик по Int16 прямо на записи — страховка от «зелёные счётчики, а в
        файле тишина» (эта ошибка в спайке уже случилась). Цена замерена здесь:
        1.51 мс на чанк 96 КБ = 0.512с аудио, то есть 0.29% CPU на дорожку.
        За это не жалко: без пика молчащий отвод выглядит как работающий."""
        buf = (self._odd + data) if self._odd else data
        n = len(buf) - (len(buf) % 2)
        self._odd = bytes(buf[n:])
        if not n:
            return
        a = array.array("h")
        a.frombytes(buf[:n])
        if sys.byteorder == "big":
            a.byteswap()             # в WAV сэмплы всегда little-endian
        m = max(max(a), -min(a))
        p = m / 32768.0
        if p > self._peak:
            self._peak = p

    def _sync(self) -> None:
        """Перепрошить заголовок фактическими размерами и додавить на диск.

        Порядок обязателен: СНАЧАЛА данные на диск, ПОТОМ заголовок про них.
        Заголовок пишется ОДНИМ вызовом на 44 байта — две правки по 4 байта
        рвутся пополам, если процесс убить между ними.
        """
        self._f.flush()
        os.fsync(self._f.fileno())
        self._f.seek(0)
        self._f.write(self._header(self.bytes_written))
        self._f.flush()
        os.fsync(self._f.fileno())
        self._f.seek(0, os.SEEK_END)
        self._last_flush = time.monotonic()

    @property
    def seconds(self) -> float:
        return round(self.bytes_written / (self.rate * self.channels * SAMPWIDTH), 3)

    @property
    def peak(self) -> float:
        return round(self._peak, 6)

    def status(self) -> dict:
        s = super().status()
        s.update(channels=self.channels, rate=self.rate)
        return s


class BlobWriter(_Writer):
    """Видео как есть: WebM/mp4 самоописывающиеся, заголовки не трогаем.

    Единственное, что делаем сверх дописывания, — fsync раз в 0.25с, чтобы
    оборванный файл был как можно длиннее. WebM переживает обрыв лучше mp4
    (замерено: декодируется 51% против 44% с ошибками NAL), поэтому просить
    у MediaRecorder стоит именно WebM — но решает это браузерная сторона,
    здесь мы пишем то, что дали.
    """

    kind = "blob"

    @property
    def seconds(self) -> float:
        """ПО СТЕННЫМ ЧАСАМ, а не по файлу. WebM от MediaRecorder — VFR без
        длительности в заголовке (замерено: ffprobe duration = N/A), честной
        длительности из недописанного файла не достать. Врать про «столько-то
        в файле» хуже, чем сказать «столько идёт запись»."""
        return round((self._last_write or time.monotonic()) - self.opened_at, 3)


# ------------------------------------------------------------------- сессия

def _unique_dir(root: Path, stamp: str) -> Path:
    """Каталог на запись. Две записи в одну секунду — редкость, но имя не
    должно молча срастаться с чужим: добавляем суффикс."""
    d = root / stamp
    n = 2
    while d.exists():
        d = root / f"{stamp} {n}"
        n += 1
    return d


class Session:
    """Одна запись: каталог + писатели по имени дорожки.

    Каталог по умолчанию ~/Documents/nakedlunch/записи/<дата время>/ (env
    NAKEDLUNCH_RECORDINGS переопределяет корень — так тесты работают во
    временной папке, ровно как NAKEDLUNCH_VAULT в core/sheets.py).
    """

    def __init__(self, directory=None):
        if directory is None:
            # Через `пути.хранилище` (Раунд 61): своя переменная →
            # NAKEDLUNCH_HOME → умолчание. Записи — третье хранилище, которое
            # одна NAKEDLUNCH_HOME раньше не покрывала.
            import пути
            root = пути.хранилище("NAKEDLUNCH_RECORDINGS", "записи", DEFAULT_ROOT)
            root.mkdir(parents=True, exist_ok=True)
            directory = _unique_dir(root, time.strftime("%Y-%m-%d %H-%M-%S"))
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.started_at = time.time()
        self.tracks: dict[str, _Writer] = {}

    # --- дорожки -----------------------------------------------------------
    def open_track(self, name: str, kind: str = "wav", channels: int = 2,
                   rate: int = 48000, ext: str | None = None) -> _Writer:
        name = str(name or "").strip()
        if not _NAME_RE.match(name):
            raise RecorderError(f"негодное имя дорожки: {name!r}")
        if name in self.tracks:
            w = self.tracks[name]
            raise RecorderError(f"дорожка {name} уже {'пишется' if not w.closed else 'записана'}")
        if kind == "wav":
            w = WavWriter(self.dir / f"{name}.wav", channels=channels, rate=rate)
        elif kind == "blob":
            ext = (ext or "webm").lstrip(".").lower()
            if not _EXT_RE.match(ext):
                raise RecorderError(f"негодное расширение: {ext!r}")
            # имя файла строится по ФАКТИЧЕСКОМУ rec.mimeType: в спайке
            # запросили webm, а получили mp4 — расширение обязано идти
            # с браузерной стороны, а не угадываться здесь
            w = BlobWriter(self.dir / f"{name}.{ext}")
        else:
            raise RecorderError(f"неизвестный вид дорожки: {kind!r}")
        self.tracks[name] = w
        return w

    def _track(self, name: str) -> _Writer:
        w = self.tracks.get(str(name))
        if w is None:
            raise RecorderError(f"дорожка {name} не открыта")
        return w

    def append(self, name: str, data: bytes, seq: int | None = None):
        return self._track(name).append(data, seq)

    def stop(self, name: str) -> str:
        return self._track(name).close()

    def stop_all(self) -> list[str]:
        return [w.close() for w in self.tracks.values() if not w.closed]

    def all_closed(self) -> bool:
        return bool(self.tracks) and all(w.closed for w in self.tracks.values())

    def status(self) -> dict:
        """На каждую дорожку — {bytes, seconds, peak, last_write_ago, error}."""
        return {name: w.status() for name, w in self.tracks.items()}

    def mux(self, **kw) -> dict:
        if any(not w.closed for w in self.tracks.values()):
            return {"ok": False, "reason": "запись ещё идёт — сначала остановить дорожки"}
        return mux(self.dir, **kw)


# --------------------------------------------------------------------- склейка

def find_ffmpeg() -> str | None:
    """ffmpeg опционален (PLAN.md: единственная внешняя опциональная зависимость).
    Ищем в PATH и в обычных местах homebrew — .app-запуск не читает ~/.zshrc,
    поэтому PATH там может быть голый."""
    explicit = os.environ.get("NAKEDLUNCH_FFMPEG")
    if explicit:
        return explicit if (os.path.isfile(explicit) and os.access(explicit, os.X_OK)) else None
    found = shutil.which("ffmpeg")
    if found:
        return found
    for cand in FFMPEG_FALLBACKS:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _pick_video(d: Path, out_name: str) -> Path | None:
    """Готовое видео сессии. .partial сюда не попадает (расширение другое) —
    склеивать оборванную запись молча нельзя."""
    cand = [p for p in sorted(d.iterdir())
            if p.is_file() and p.suffix.lower() in VIDEO_EXT and p.name != out_name]
    if not cand:
        return None
    cand.sort(key=lambda p: (VIDEO_EXT.index(p.suffix.lower()), p.name))
    return cand[0]


def mux(session_dir, out_name: str = MUX_NAME, timeout: float = 3600.0) -> dict:
    """Склеить видео и звуковые дорожки в один файл. Исходники не трогаются.

    ПЕРЕКОДИРОВАНИЕ, НЕ -c copy: WebM от MediaRecorder — VFR без длительности
    в заголовке (замерено: ffprobe duration = N/A), покадровое копирование
    даёт файл с поехавшим временем.

    ЗВУК СВОДИТСЯ В ОДНУ ДОРОЖКУ (amix), а не раскладывается отдельными
    дорожками контейнера. Почему: обычный плеер играет ПЕРВУЮ звуковую
    дорожку и молчит про остальные — зритель услышал бы только микрофон или
    только луп и решил бы, что запись испорчена. Тихий сбой хуже громкого.
    Разделение при этом никуда не девается: mic.wav и loop.wav лежат рядом
    нетронутыми, для настоящего сведения берут их, а не этот файл.
    normalize=0 обязателен: по умолчанию amix делит громкость на число входов,
    и «сведёнка» вышла бы тише исходников без единого сообщения (замерено на
    двух одинаково громких дорожках: mean_volume -9.5 dB против -5.5 dB).
    Обратная сторона честная: два горячих источника в сумме могут клиппировать
    (в том же замере max_volume упёрся в 0.0 dB). Это слышно сразу, а исходники
    лежат рядом нетронутыми — настоящее сведение делают из них.
    """
    d = Path(session_dir)
    if not d.is_dir():
        return {"ok": False, "reason": f"каталог записи не найден: {d}"}
    ff = find_ffmpeg()
    if not ff:
        return {"ok": False, "reason": "ffmpeg не найден"}
    video = _pick_video(d, out_name)
    if video is None:
        return {"ok": False, "reason": "нет готовой видеодорожки — склеивать нечего"}
    wavs = sorted(p for p in d.glob("*.wav") if p.is_file())
    out = d / out_name

    cmd = [ff, "-y", "-i", str(video)]
    for w in wavs:
        cmd += ["-i", str(w)]
    if len(wavs) == 1:
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
    elif wavs:
        chain = "".join(f"[{i + 1}:a]" for i in range(len(wavs)))
        chain += f"amix=inputs={len(wavs)}:duration=longest:normalize=0[a]"
        cmd += ["-filter_complex", chain, "-map", "0:v:0", "-map", "[a]",
                "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-map", "0:v:0", "-an"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-r", "30",
            "-movflags", "+faststart", str(out)]

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"ffmpeg не уложился в {int(timeout)}с", "cmd": cmd}
    except OSError as e:
        return {"ok": False, "reason": f"ffmpeg не запустился: {e}", "cmd": cmd}
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-12:])
        return {"ok": False, "reason": f"ffmpeg вернул код {p.returncode}",
                "stderr": tail, "cmd": cmd}
    return {"ok": True, "path": str(out), "bytes": out.stat().st_size if out.exists() else 0,
            "video": str(video), "audio": [str(w) for w in wavs], "ffmpeg": ff,
            "cmd": cmd}
