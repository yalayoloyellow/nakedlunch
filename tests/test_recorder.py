# extendo/nakedlunch — тесты питон-стороны записи (core/recorder.py).
#
# Проверяем не «поле пришло», а результат: WAV открывается модулем wave и
# содержит ТЕ САМЫЕ сэмплы; пик по тишине действительно ноль; заголовок
# перепрошивается одним write; .partial переезжает в финальное имя только на
# close; разрыв номеров ловится; mux без ffmpeg возвращает причину, а не
# исключение. Отдельно — краш-тест НАСТОЯЩИМ SIGKILL: подпроцесс пишет, его
# убивают посреди записи, .partial обязан открыться модулем wave.
#
# Прогон: .venv/bin/python -m pytest tests/test_recorder.py -q

import os
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

CORE = str(Path(__file__).resolve().parent.parent / "core")
sys.path.insert(0, CORE)

import recorder  # noqa: E402

RATE, CH = 48000, 2
BYTE_RATE = RATE * CH * recorder.SAMPWIDTH


def tone(n_frames, start=0, channels=CH, amp=16000):
    """Детерминированный PCM: сэмпл однозначно определён номером кадра, поэтому
    любая порча или сдвиг данных видны сразу."""
    out = bytearray()
    for i in range(start, start + n_frames):
        v = ((i * 137) % (2 * amp)) - amp
        out += struct.pack("<" + "h" * channels, *([v] * channels))
    return bytes(out)


def frame_at(i, channels=CH, amp=16000):
    v = ((i * 137) % (2 * amp)) - amp
    return struct.pack("<" + "h" * channels, *([v] * channels))


class CountingFile:
    """Прозрачная обёртка дескриптора со счётчиком write — им проверяем, что
    заголовок пишется ОДНИМ вызовом на 44 байта, а не двумя правками по 4."""

    def __init__(self, f):
        self._f = f
        self.writes = []

    def write(self, b):
        self.writes.append(len(b))
        return self._f.write(b)

    def __getattr__(self, name):
        return getattr(self._f, name)


# ----------------------------------------------------------------- WAV раундтрип

def test_wav_roundtrip_opens_and_matches(tmp_path):
    """Записали PCM — модуль wave открыл, длительность и сэмплы совпали."""
    path = tmp_path / "loop.wav"
    w = recorder.WavWriter(path, channels=CH, rate=RATE)
    frames = RATE // 2                      # ровно 0.5 секунды
    for k in range(10):                     # десятью кусками, как ходит мост
        w.append(tone(frames // 10, start=k * (frames // 10)))
    assert abs(w.seconds - 0.5) < 1e-6
    assert w.close() == str(path)

    with wave.open(str(path), "rb") as f:
        assert (f.getnchannels(), f.getsampwidth(), f.getframerate()) == (CH, 2, RATE)
        assert f.getnframes() == frames
        data = f.readframes(frames)
    assert len(data) == frames * CH * 2
    for i in (0, frames // 3, frames - 1):
        assert data[i * 4:(i + 1) * 4] == frame_at(i), f"кадр {i} испорчен"


def test_wav_seconds_and_bytes(tmp_path):
    w = recorder.WavWriter(tmp_path / "mic.wav", channels=1, rate=48000)
    w.append(tone(48000, channels=1))
    assert w.bytes_written == 96000
    assert w.seconds == 1.0
    w.close()


# ------------------------------------------------------- перештамповка одним write

def test_header_restamped_in_a_single_44_byte_write(tmp_path):
    """Две правки по 4 байта рвут заголовок при убийстве между ними — значит
    write должен быть ровно один и ровно на 44 байта."""
    w = recorder.WavWriter(tmp_path / "a.wav", channels=CH, rate=RATE)
    w._f = CountingFile(w._f)               # считаем только то, что после открытия
    w.append(tone(1000))
    w._f.writes.clear()
    w._sync()                               # ровно одна перепрошивка
    assert w._f.writes == [recorder.HEADER_LEN]

    w._f.writes.clear()
    w.append(tone(1000, start=1000))
    w.close()
    # за всю оставшуюся жизнь: куски данных + финальный заголовок, и ни одного
    # писка по 4 байта (размер RIFF и размер data — не отдельные записи)
    assert w._f.writes.count(recorder.HEADER_LEN) == 1
    assert 4 not in w._f.writes


def test_header_placeholder_is_valid_before_any_data(tmp_path):
    """Файл валиден сразу после открытия: нулевые размеры, но wave его берёт."""
    path = tmp_path / "b.wav"
    w = recorder.WavWriter(path, channels=CH, rate=RATE)
    with wave.open(w.partial, "rb") as f:
        assert f.getnframes() == 0
        assert f.getframerate() == RATE
    w.close()


# --------------------------------------------------------------- .partial → финал

def test_partial_moves_to_final_name_only_on_close(tmp_path):
    path = tmp_path / "video.webm"
    w = recorder.BlobWriter(path)
    w.append(b"\x1a\x45\xdf\xa3" + b"webm-ish" * 100)
    assert os.path.exists(w.partial), ".partial обязан существовать во время записи"
    assert not path.exists(), "финальное имя не должно появляться до close"
    w.close()
    assert path.exists() and not os.path.exists(w.partial)


def test_blob_roundtrip(tmp_path):
    path = tmp_path / "video.webm"
    parts = [os.urandom(4096) for _ in range(20)]
    w = recorder.BlobWriter(path)
    for i, p in enumerate(parts):
        n, problem = w.append(p, seq=i)
        assert problem is None and n == len(p)
    w.close()
    assert path.read_bytes() == b"".join(parts)
    assert w.bytes_written == sum(len(p) for p in parts)


# ------------------------------------------------------------------ номера чанков

def test_out_of_order_chunks_are_reordered_not_lost(tmp_path):
    """Мост доставляет вызовы разными потоками — обгон это норма, а не сбой."""
    path = tmp_path / "loop.wav"
    w = recorder.WavWriter(path, channels=CH, rate=RATE)
    parts = [tone(240, start=i * 240) for i in range(6)]
    for i in (0, 2, 1, 4, 3, 5):            # 2 обогнал 1, 4 обогнал 3
        n, problem = w.append(parts[i], seq=i)
        assert problem is None, problem
    w.close()
    with wave.open(str(path), "rb") as f:
        data = f.readframes(f.getnframes())
    assert data == b"".join(parts), "куски легли не в том порядке"
    assert w.error is None


def test_seq_gap_is_caught_and_reported(tmp_path):
    """Чанк, которого не дождались, — сбой, и он обязан прозвучать."""
    w = recorder.WavWriter(tmp_path / "loop.wav", channels=CH, rate=RATE)
    w.append(tone(120, start=0), seq=0)
    problems = []
    # 1 не придёт никогда: сыплем следующие, пока окно придержанных не лопнет
    for i in range(2, 2 + recorder.SEQ_WINDOW + 2):
        _, problem = w.append(tone(120, start=i * 120), seq=i)
        if problem:
            problems.append(problem)
    assert problems, "разрыв последовательности не пойман"
    assert "1" in problems[0] and "потерян" in problems[0]
    assert w.error == problems[0], "сбой обязан остаться липким для статуса"
    w.close()


def test_seq_gap_at_close_is_reported(tmp_path):
    """Дырка меньше окна всплывает на остановке — молчать о ней нельзя."""
    w = recorder.WavWriter(tmp_path / "loop.wav", channels=CH, rate=RATE)
    w.append(tone(120, start=0), seq=0)
    w.append(tone(120, start=240), seq=2)   # 1 потерялся
    assert w.error is None                  # пока ждём — это ещё не сбой
    w.close()
    assert w.error and "не пришли" in w.error and "1" in w.error


def test_late_chunk_is_rejected_loudly(tmp_path):
    w = recorder.BlobWriter(tmp_path / "v.webm")
    for i in range(3):
        w.append(b"x" * 10, seq=i)
    n, problem = w.append(b"x" * 10, seq=1)  # опоздал: дорожка уже на 3
    assert n == 0 and problem and "отброшен" in problem
    assert w.bytes_written == 30
    w.close()


def test_duplicate_pending_chunk_is_rejected(tmp_path):
    w = recorder.BlobWriter(tmp_path / "v.webm")
    w.append(b"a" * 4, seq=0)
    w.append(b"b" * 4, seq=2)               # придержан
    n, problem = w.append(b"c" * 4, seq=2)  # тот же номер второй раз
    assert n == 0 and problem and "дважды" in problem
    w.close()


# -------------------------------------------------------------------------- пик

def test_peak_is_zero_on_silence(tmp_path):
    """Ровно тот случай, ради которого пик и считается: счётчики зелёные,
    байты идут, а в файле тишина."""
    w = recorder.WavWriter(tmp_path / "silent.wav", channels=CH, rate=RATE)
    w.append(b"\x00\x00" * (RATE * CH))
    assert w.peak == 0.0
    assert w.bytes_written == RATE * CH * 2
    w.close()


def test_peak_matches_loudest_sample(tmp_path):
    w = recorder.WavWriter(tmp_path / "loud.wav", channels=1, rate=RATE)
    w.append(struct.pack("<hhh", 100, -8192, 300))
    assert w.peak == pytest.approx(8192 / 32768.0)
    w.append(struct.pack("<h", 24576))
    assert w.peak == pytest.approx(24576 / 32768.0)
    w.append(struct.pack("<h", -1000))      # тише — пик не опускается
    assert w.peak == pytest.approx(24576 / 32768.0)
    w.close()


def test_peak_survives_odd_byte_split(tmp_path):
    """Кусок может разорвать сэмпл пополам — пик обязан считаться по целым."""
    pcm = struct.pack("<hhhh", 0, 0, -30000, 0)
    a = recorder.WavWriter(tmp_path / "whole.wav", channels=1, rate=RATE)
    a.append(pcm)
    b = recorder.WavWriter(tmp_path / "split.wav", channels=1, rate=RATE)
    b.append(pcm[:5])                       # разрез посреди сэмпла
    b.append(pcm[5:])
    assert b.peak == a.peak == pytest.approx(30000 / 32768.0)
    a.close(); b.close()


# ----------------------------------------------------------------------- сессия

@pytest.fixture()
def rec_root(tmp_path, monkeypatch):
    monkeypatch.setenv("NAKEDLUNCH_RECORDINGS", str(tmp_path / "записи"))
    return tmp_path / "записи"


def test_session_dir_and_status(rec_root):
    s = recorder.Session()
    assert s.dir.parent == rec_root and s.dir.is_dir()
    s.open_track("mic", kind="wav", channels=1, rate=RATE)
    s.open_track("video", kind="blob", ext="mp4")
    s.append("mic", tone(RATE // 10, channels=1), 0)
    time.sleep(0.05)
    st = s.status()
    assert set(st) == {"mic", "video"}
    for track in st.values():
        assert {"bytes", "seconds", "peak", "last_write_ago"} <= set(track)
    assert st["mic"]["bytes"] == (RATE // 10) * 2
    assert st["mic"]["peak"] > 0
    assert st["video"]["bytes"] == 0
    # видео молчит с самого открытия — интерфейсу это и есть сигнал сбоя
    assert st["video"]["last_write_ago"] >= 0.05
    assert (s.dir / "video.mp4.partial").exists()
    s.stop_all()
    assert s.all_closed()
    assert (s.dir / "mic.wav").exists() and (s.dir / "video.mp4").exists()


def test_session_rejects_bad_names(rec_root):
    s = recorder.Session()
    with pytest.raises(recorder.RecorderError):
        s.open_track("../побег")
    with pytest.raises(recorder.RecorderError):
        s.open_track("mic", kind="телепатия")
    s.open_track("mic")
    with pytest.raises(recorder.RecorderError):
        s.open_track("mic")
    with pytest.raises(recorder.RecorderError):
        s.append("нетакой", b"\x00\x00")
    s.stop_all()


def test_session_dirs_do_not_collide(rec_root):
    a, b = recorder.Session(), recorder.Session()
    assert a.dir != b.dir


# -------------------------------------------------------------------------- mux

@pytest.fixture()
def no_ffmpeg(monkeypatch):
    monkeypatch.delenv("NAKEDLUNCH_FFMPEG", raising=False)
    monkeypatch.setattr(recorder.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(recorder, "FFMPEG_FALLBACKS", ())


def test_mux_without_ffmpeg_returns_reason(tmp_path, no_ffmpeg):
    """ffmpeg опционален: нет его — честный отказ, а не исключение."""
    (tmp_path / "video.webm").write_bytes(b"\x1a\x45\xdf\xa3")
    res = recorder.mux(tmp_path)
    assert res == {"ok": False, "reason": "ffmpeg не найден"}


def test_mux_without_video_returns_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("NAKEDLUNCH_FFMPEG", sys.executable)   # «ffmpeg есть»
    (tmp_path / "mic.wav").write_bytes(b"")
    res = recorder.mux(tmp_path)
    assert res["ok"] is False and "видеодорожк" in res["reason"]


def test_mux_ignores_partial_video(tmp_path, monkeypatch):
    """Оборванную запись молча склеивать нельзя — .partial не видеодорожка."""
    monkeypatch.setenv("NAKEDLUNCH_FFMPEG", sys.executable)
    (tmp_path / "video.webm.partial").write_bytes(b"\x1a\x45\xdf\xa3")
    assert recorder.mux(tmp_path)["ok"] is False


def test_find_ffmpeg_honours_missing_explicit_path(tmp_path, monkeypatch):
    monkeypatch.setenv("NAKEDLUNCH_FFMPEG", str(tmp_path / "нет-такого"))
    assert recorder.find_ffmpeg() is None


def test_session_mux_refuses_while_recording(rec_root, no_ffmpeg):
    s = recorder.Session()
    s.open_track("mic")
    res = s.mux()
    assert res["ok"] is False and "запись ещё идёт" in res["reason"]
    s.stop_all()


def test_mux_real_ffmpeg_produces_playable_file(rec_root):
    """Живая склейка — только если ffmpeg реально стоит (иначе пропуск)."""
    ff = recorder.find_ffmpeg()
    if not ff:
        pytest.skip("ffmpeg не установлен")
    s = recorder.Session()
    # видео делает сам ffmpeg: WebM/VP8, 2 секунды тестового сигнала
    src = s.dir / "video.webm"
    make = subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30",
                           "-t", "2", "-c:v", "libvpx", "-b:v", "300k", str(src)],
                          capture_output=True, text=True)
    if make.returncode != 0:
        pytest.skip("этот ffmpeg не собрал тестовое видео")
    for name, ch in (("mic", 1), ("loop", 2)):
        w = s.open_track(name, kind="wav", channels=ch, rate=RATE)
        w.append(tone(RATE * 2, channels=ch))
        w.close()
    res = recorder.mux(s.dir)
    assert res["ok"] is True, res
    out = Path(res["path"])
    assert out.exists() and out.stat().st_size > 0
    # исходники не тронуты — это условие пользователя, а не пожелание
    for name in ("video.webm", "mic.wav", "loop.wav"):
        assert (s.dir / name).exists()
    with wave.open(str(s.dir / "loop.wav"), "rb") as f:
        assert f.getnframes() == RATE * 2

    # ПРОВЕРКА ПО ФАКТУ, а не по наличию файла: в сведёнке действительно есть
    # звук. Именно тут ловится главная ловушка спайка — «всё зелёное, а файл
    # тишина»; наличия дорожки для этого недостаточно, нужен уровень.
    probe = subprocess.run([ff, "-hide_banner", "-i", str(out),
                            "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True)
    log = probe.stderr
    assert "Audio:" in log, log[-800:]
    means = [float(l.split("mean_volume:")[1].split("dB")[0])
             for l in log.splitlines() if "mean_volume:" in l]
    assert means, log[-800:]
    assert means[0] > -30.0, f"сведёнка почти тишина: mean_volume {means[0]} dB"
    # деление громкости на число входов проверяется не по уровню (замерено:
    # normalize=1 даёт -9.5 dB против -5.5 — порогом такое не различить честно),
    # а по самой команде: флаг обязан быть в фильтре
    assert any("normalize=0" in str(a) for a in res["cmd"]), res["cmd"]


# ------------------------------------------------------------------- КРАШ-ТЕСТ

CHILD = r'''
import sys, time, struct
sys.path.insert(0, %r)
import recorder
RATE, CH = 48000, 2
w = recorder.WavWriter(sys.argv[1], channels=CH, rate=RATE)
step = RATE // 20                       # 50 мс аудио за итерацию
i = 0
t0 = time.monotonic()
while True:
    buf = bytearray()
    for k in range(i, i + step):
        v = ((k * 137) %% 32000) - 16000
        buf += struct.pack("<hh", v, v)
    w.append(bytes(buf))
    i += step
    d = t0 + i / RATE - time.monotonic()
    if d > 0:
        time.sleep(d)                   # держим реальный темп записи
''' % CORE


@pytest.mark.parametrize("kill_after", [0.6, 0.9, 1.4])
def test_sigkill_mid_write_leaves_readable_wav(tmp_path, kill_after):
    """Настоящий SIGKILL посреди записи: .partial обязан открыться модулем wave
    с целыми сэмплами. Потеря — не больше интервала перепрошивки (0.25с)."""
    final = tmp_path / f"crash{kill_after}.wav"
    partial = str(final) + ".partial"
    p = subprocess.Popen([sys.executable, "-c", CHILD, str(final)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    t0 = time.monotonic()
    time.sleep(kill_after)
    p.kill()                                     # -9, без шансов на atexit
    p.wait()
    lived = time.monotonic() - t0
    # КОД ВОЗВРАТА ЗАВИСИТ ОТ СИСТЕМЫ (Раунд 61). На POSIX это −9 (или 137 из
    # оболочки), на Windows `kill()` — это TerminateProcess, и код там просто
    # ненулевой. Смысл проверки один и тот же: процесс убит снаружи, а не вышел
    # сам, — значит atexit не отработал, и `.partial` обязан быть целым без
    # всякой помощи со стороны программы. Проверка ниже платформ не различает.
    if os.name == "nt":
        assert p.returncode != 0, f"ожидали убийство, процесс вышел сам ({p.returncode})"
    else:
        assert p.returncode in (-9, 137), f"ожидали SIGKILL, получили {p.returncode}"

    assert os.path.exists(partial), ".partial не пережил убийство"
    assert not final.exists(), "финальное имя без close появляться не должно"
    with wave.open(partial, "rb") as f:
        assert (f.getnchannels(), f.getsampwidth(), f.getframerate()) == (2, 2, RATE)
        n = f.getnframes()
        data = f.readframes(n)
    assert n > 0, "заголовок не перепрошился ни разу"
    assert len(data) == n * 4, "заголовок обещает больше, чем лежит на диске"
    for i in (0, n // 2, n - 1):                 # сэмплы целы, не сдвинуты
        assert data[i * 4:(i + 1) * 4] == frame_at(i), f"кадр {i} испорчен"
    header_s = n / RATE
    # запуск интерпретатора съедает часть окна, поэтому сверху ограничиваем
    # прожитым временем, а снизу — тем, что хоть один сброс успел случиться
    assert 0 < header_s <= lived + 0.05
    assert lived - header_s < 1.0, f"потеряно {lived - header_s:.3f}с — слишком много"
