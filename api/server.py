#!/usr/bin/env python3
# extendo GUI — local server. A thin Flask adapter over core/. It imports the
# domain and only CALLS it — no generation, scan, or filter logic lives here
# (ported from pusher/gui/server.py, minus the SSE/job machinery: a run is
# ~200 ms, so /api/generate is a plain synchronous request, see DECISIONS.md).
#
# The core is the source of truth; delete api/ and interface/ and the domain is
# untouched.

from __future__ import annotations

import argparse
import json
import sys
import threading
import subprocess
import time
from pathlib import Path

# make core/ importable (repo root is one level up)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from flask import Flask, Response, request, send_from_directory  # noqa: E402

import chain_profiles  # noqa: E402  (полка цепочек-слепков, Раунд 50 — см. core/chain_profiles.py)
import blacklist      # noqa: E402  (чёрный список слов, Раунд 57)
import clean          # noqa: E402  (the single validation layer — all input goes through it)
import embeddings     # noqa: E402  (navec theme relevance, see core/embeddings.py)
import filters        # noqa: E402
import generate       # noqa: E402
import knob_profiles  # noqa: E402  (полка профилей настроек, Раунд 50 — см. core/knob_profiles.py)
import series as series_mod  # noqa: E402  (полка серий, Раунд 53 — см. core/series.py)
import series_run  # noqa: E402  (прогон серии — см. core/series_run.py)
import curve  # noqa: E402  (кривая как поставщик крутилок звеньев — см. core/curve.py)
import nlbridge       # noqa: E402  (read-only bridge into ~/nakedlunch, see core/nlbridge.py)
import pipeline       # noqa: E402  (пулы по звеньям + склейка, см. core/pipeline.py)
import refprofile     # noqa: E402  (профиль референсного текста, Раунд 45)
import recorder       # noqa: E402  (каталог записей фристайла, см. core/recorder.py)
import corpus as corpus_mod  # noqa: E402  (RETENTION_PRESETS)
import settings as settings_mod  # noqa: E402  (persisted knob positions, see core/settings.py)
import sheets                    # noqa: E402  (листы — .md-хранилище в ~/Documents/nakedlunch/тексты, см. core/sheets.py)
import stanza_profiles           # noqa: E402  (builtin + custom stanza forms, see core/stanza_profiles.py)
import stats as stats_mod    # noqa: E402  (analytics log, see core/stats.py)
import nlindex               # noqa: E402  (фоновый прогрев карты «текст → номер»)
import jobs                  # noqa: E402  (цепочка фоновых сборок, см. core/jobs.py)
import wordsuggest           # noqa: E402  (попап по слову — рифмы/по звуку/строкой, см. core/wordsuggest.py)
import журнал                # noqa: E402  (один журнал на всё приложение, см. core/журнал.py)
import пути                  # noqa: E402  (где что лежит, см. core/пути.py)
import дочерний              # noqa: E402  (как запускаются части программы)  (один журнал на всё приложение, см. core/журнал.py)
from corpus import Corpus  # noqa: E402

HERE = Path(__file__).resolve().parent
DIST = ROOT / "interface" / "react-app" / "dist"

app = Flask(__name__, static_folder=None)


# ---------------------------------------------------------------------------
# ВСЁ, ЧТО СЛОМАЛОСЬ, ОБЯЗАНО НАЗВАТЬ СЕБЯ (Раунд 59).
#
# Программу дают людям, которые пишут тексты, а не читают стеки. Значит правило
# такое: если что-то не работает, человек видит причину НА ЭКРАНЕ и отправляет
# её одним нажатием. До этого раунда половина отказов уходила в stdout, которого
# в собранном приложении не существует, — снаружи это выглядело как «просто не
# работает», и починить такое можно было только гаданием.
#
# Пятисотку ловим ЦЕЛИКОМ, со стеком, и отвечаем внятным текстом. Ответ остаётся
# машинно-разбираемым (JSON с полем error), но теперь в нём есть и «что делать».

@app.errorhandler(Exception)
def _любая_ошибка(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e                      # 404 и подобное — не поломка, а ответ
    журнал.ошибка("сервер", f"{request.method} {request.path}", e)
    return {"error": f"{type(e).__name__}: {e}",
            "detail": "Ошибка записана в журнал. Настройки → Лог → «скопировать отчёт»."}, 500


@app.before_request
def _замерить_начало():
    request.environ["_начало"] = time.time()


@app.after_request
def _записать_итог(ответ):
    """В журнал идут ТОЛЬКО поломки и долгие запросы. Писать каждый успешный
    опрос статуса — значит утопить в них то единственное, ради чего журнал и
    заведён: строку, объясняющую отказ."""
    try:
        сек = time.time() - request.environ.get("_начало", time.time())
        # ОШИБКА — ЭТО ПОЛОМКА, А НЕ «НЕ НАЙДЕНО» (Раунд 59). Первая живая
        # проверка зажгла метку ошибок на пустом месте: браузер спросил
        # /favicon.ico, получил 404 — и человеку показали красную единицу.
        # Метка, которая горит без причины, обесценивает саму себя: её
        # перестают замечать ровно тогда, когда она наконец права.
        if ответ.status_code >= 500:
            журнал.запись("сервер", f"{ответ.status_code} {request.method} {request.path}", "ошибка")
        elif ответ.status_code >= 400 and ответ.status_code not in (404, 405):
            журнал.запись("сервер", f"{ответ.status_code} {request.method} {request.path}", "внимание")
        elif сек > 5.0 and not request.path.endswith("/status"):
            журнал.запись("сервер", f"{request.method} {request.path} — {сек:.1f} с", "внимание")
    except Exception:
        pass
    return ответ

# One authoritative corpus for the single window; the browser is a mirror.
CORPUS = Corpus.load()

# Load the forms table + wordfreq's frequency data once at startup so every
# /api/generate request is fast from the first one, not just the second.
журнал.запись("сервер", "старт сервера")
generate.warm_caches()
filters.warm_caches()
embeddings.warm_caches()   # navec (~0.3s) — see core/embeddings.py
wordsuggest.warm_caches()  # rhyme_index.json — попап по слову
# Карта «текст → номер» колоночного индекса: 9.8с на 2.87 млн записей. Раньше
# её платил ПЕРВЫЙ запрос генерации, то есть пользователь; теперь она строится
# фоном, пока он открывает окно. Не готова к первому запросу — он просто
# подождёт на замке внутри nlindex, а не построит вторую карту.
# ПРОГРЕВ — ОДИН, ПО ПОРЯДКУ И НА ВИДУ (Раунд 57).
#
# Здесь стояли два независимых фоновых потока: `nlindex.warm_background()` и
# `nlbridge.warm_background()`. Порт они открывали быстро (Раунд 54 ради этого
# и делался — до него старт занимал 39.4 с при потолке ожидания окна 40 с, и
# однажды не уложился), но дальше начиналось то, чего не видел никто:
#
#   1. Оба потока лезли за процессором ОДНОВРЕМЕННО — 550 МБ state.json
#      разбирались наперегонки с картой «текст → номер» (9.8 с) и маской
#      целостности (9.2 с). На пассивно охлаждаемой машине они мешали друг
#      другу и растягивались втрое.
#   2. Генерация ЖДЁТ обоих — `_nl()` встаёт на замке хранилища, а filters
#      встают на тех же картах внутри nlindex. Пользователь в это время сидел во
#      фристайле перед пустой сценой: замерено с его машины — первая пачка
#      56 с, вторая 72 с, а через десять минут тот же запрос отвечает за
#      0.25 с. Медленной генерации не было ни одной секунды; был невидимый
#      прогрев, приехавший в его сессию вместе с быстрым стартом окна.
#   3. Сказать про это было нечего: строка в шапке знала только про корпус.
#
# Теперь этапы идут ПО ОЧЕРЕДИ (хранилище первым — на нём стоит генерация),
# каждый честно называет себя и своё время, а `_ПРОГРЕВ` читает статус в шапке.
_ПРОГРЕВ: dict = {"этап": "корпус", "начат": time.time(), "готов": False, "этапы": []}


def _прогрев() -> None:
    def этап(имя, работа):
        _ПРОГРЕВ["этап"] = имя
        t = time.time()
        try:
            работа()
        except Exception as e:                                   # noqa: BLE001
            # Молчать нельзя: без корпуса не работает ни генерация, ни статус,
            # и пользователь должен увидеть причину в логе, а не пустую выдачу.
            print(f"nakedlunch: прогрев «{имя}» не удался ({e})", flush=True)
        сек = round(time.time() - t, 1)
        _ПРОГРЕВ["этапы"].append([имя, сек])
        print(f"nakedlunch: прогрев «{имя}» — {сек} с", flush=True)

    def карты():
        idx = nlindex.load()
        if idx is None:
            return           # индекса нет — генерация идёт старым путём
        nlindex.text_ids(idx)
        idx.whole_mask()

    этап("корпус", nlbridge.open_store)
    этап("карты индекса", карты)
    _ПРОГРЕВ["готов"] = True
    print("nakedlunch: прогрев завершён за "
          f"{round(time.time() - _ПРОГРЕВ['начат'], 1)} с", flush=True)


threading.Thread(target=_прогрев, name="nl-warm", daemon=True).start()


def _nl():
    """Хранилище корпуса. ЖДЁТ фоновую загрузку, если она ещё идёт."""
    return nlbridge.open_store()


def _nl_ready() -> bool:
    """Корпус уже в памяти? Не ждёт — см. nlbridge.store_if_ready."""
    return nlbridge.store_if_ready() is not None


# ПЕРЕНОС ИСТОРИИ ИЗ CLI ВЫРЕЗАН (Раунд 54). `_merge_nl_used_once` стоял
# здесь с Раунда 40 и своё дело сделал: все 16 862 строки учёта CLI лежат в
# нашей истории (проверено поимённо — не перенесено 0).
#
# «Once» он при этом не был НИ РАЗУ. Отметку о переносе он писал через
# settings.write, а тот молча выбрасывал ключ, которого нет в своём белом
# списке, — ровно та ловушка, что уже описана в /api/settings: «фильтра два, и
# второй молча съедал ключ, пропущенный в первом». В логе «очистить историю»
# отменялось следующим запуском: 16 862 строки вернулись бы обратно.
#
# Чтобы следующая такая отметка падала громко, а не исчезала, settings.write
# теперь на чужой ключ ругается (core/settings.py).

# tools/build_nl_rhyme.py's sidecar — see that file for why this is separate
# from the (large) cache file it describes.
_NL_RHYME_STATUS_PATH = пути.артефакт("nl_rhyme.status.json")
_NL_RHYME_SCRIPT = ROOT / "tools" / "build_nl_rhyme.py"
_NL_RHYME_STALE_SECONDS = 180   # no checkpoint in 3min → probably not actively running
_NL_RHYME_PROC = None            # this process's own handle — avoids double-spawn


def _nl_rhyme_ensure_running(full: bool = False, reban: bool = False) -> None:
    """Spawn the rhyme-cache build in the background if it isn't already
    running. Called after a source is added — new fragments should start
    getting covered without the user having to open a terminal. Safe to call
    repeatedly: a Popen handle we still hold and haven't seen exit means
    skip; the script's own incremental skip-logic (tools/build_nl_rhyme.py)
    means even a slightly-overlapping second run would just re-skip
    already-cached text, never corrupt it — but avoiding two ONNX sessions
    fighting over the same CPU is the actual point here.

    `full=True` (only the user's manual button passes this) passes --full
    through to the script, which ignores the existing cache and recomputes
    EVERY fragment from scratch. Found 2026-07-14: the manual button called
    this with the default incremental mode, same as the auto-trigger — when
    the cache was already ~100% complete (the normal case, since auto-run
    covers new sources already), clicking it finished in a few seconds
    having done nothing, which reads as broken even though it technically
    "ran". Auto-trigger (source add) stays incremental — that path already
    has fresh-only work to do, a full rebuild there would just be slower for
    no benefit."""
    global _NL_RHYME_PROC
    if _nl() is None:
        return False
    if _NL_RHYME_PROC is not None and _NL_RHYME_PROC.poll() is None:
        return False
    # A build from OUTSIDE this process (the user's own terminal, or a
    # previous run of this same server) may already be writing nl_rhyme.json
    # right now — this process's own _NL_RHYME_PROC handle only knows about
    # builds IT started. A fresh updated_at means skip; two ONNX sessions
    # racing to write the same cache file is the actual failure mode, not
    # the (harmless, by design) redundant re-skip of already-cached text.
    if _NL_RHYME_STATUS_PATH.exists():
        try:
            s = json.loads(_NL_RHYME_STATUS_PATH.read_text(encoding="utf-8"))
            if s.get("state") == "running" and time.time() - s.get("updated_at", 0) < _NL_RHYME_STALE_SECONDS:
                # ВЕРНУТЬ False, А НЕ ПРОСТО ВЫЙТИ (Раунд 56). Нажатие «прогнать
                # всё заново» при уже идущей сборке исчезало БЕЗ СЛЕДА: ни отказа,
                # ни отметки в интерфейсе. Молчаливый отказ хуже отказа.
                return False
        except Exception:
            pass
    import subprocess
    args = дочерний.команда("ударения")
    if full:
        args.append("--full")
    elif reban:
        # ПЕРЕСЧЁТ ТОЛЬКО ФОРМУЛЫ КАЧЕСТВА (Раунд 57). Модель ударений не
        # грузится вовсе — минуты вместо часа, см. reban() в самом скрипте.
        args.append("--reban")
    _журнал = _лог_сборки("ударения" + (" (полный пересчёт)" if full else ""))
    _NL_RHYME_PROC = subprocess.Popen(
        args, cwd=str(ROOT), stdout=_журнал, stderr=subprocess.STDOUT,
    )
    # Кэш рифм — только ПОЛОВИНА пути новой книги. Вторая половина, колоночный
    # индекс, печётся ИЗ него, поэтому цепляется следом, а не параллельно
    # (Раунд 52). Без этого шага книга попадала в источники и не попадала в
    # выдачу — молча, при 100% на индикаторе.
    # ЧЕСТНАЯ СМЕРТЬ ВМЕСТО «ВСТАЛО» (Раунд 57). Ребёнок читает весь кэш в
    # память и на 16 ГБ вместе с открытым приложением его иногда убивает
    # система — молча, не написав в статус ни строки. Сайдкар оставался в
    # «идёт», сервер через минуту называл это «встало», и в шапке висело «1 / 2 434 632 (0%)» без единого намёка на причину.
    #
    # Теперь смерть ловится и записывается: «не удалось, код такой-то». Это не
    # чинит саму нехватку памяти — это перестаёт врать о ней.
    _после(_NL_RHYME_PROC, _nl_index_ensure_running)
    _проследить_за_сборкой(_NL_RHYME_PROC)
    return True


# --- колоночный индекс: перепечь и честный статус (Раунд 52) ---------------
#
# ЧТО БЫЛО СЛОМАНО. Добавление книги запускало ТОЛЬКО кэш рифм. Колоночный
# индекс (tools/build_nl_index.py) не пересобирался никогда, а `nlindex.mask_of`
# молча пропускает всё, чего в индексе нет. То есть свежая книга стояла в
# списке источников, её фрагменты честно считались в воронке (`nl_fetched`), и
# в выдаче не появлялись НИ РАЗУ — при том что топбар показывал «Рифма
# nakedlunch 100%», то есть «готово».
#
# Замерено: пул из 300 индексных фрагментов плюс один неиндексный → в маску
# попадает 300, воронка рапортует 301, новый в выдаче отсутствует.
#
# Перепечь безопасна для живого процесса: скрипт пишет во временный каталог и
# переименовывает, а mmap на отвязанные файлы остаётся валидным. Поэтому до
# `nlindex.reload()` процесс читает ПРЕЖНИЙ индекс, а не мусор.
_NL_INDEX_SCRIPT = ROOT / "tools" / "build_nl_index.py"
_NL_INDEX_PROC = None


# ВЫВОД СБОРОК — В ФАЙЛ, А НЕ В НИКУДА (Раунд 56).
#
# Обе сборки запускались с stdout и stderr в DEVNULL. Значит УПАВШАЯ сборка
# выглядела ровно так же, как не запускавшаяся, и на вопрос вопрос «почему 251 727 строк вне индекса» ответить было нечем: следов не осталось.
_СБОРКИ_ЛОГ = пути.данные("сборки.log")


def _лог_сборки(имя):
    """Файл для вывода сборки, открытый на дозапись. Не смогли открыть — пусть
    уходит в никуда, как раньше: сборка важнее своего лога."""
    try:
        _СБОРКИ_ЛОГ.parent.mkdir(parents=True, exist_ok=True)
        f = open(_СБОРКИ_ЛОГ, "ab")
        f.write(f"\n=== {имя} · {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n".encode("utf-8"))
        f.flush()
        return f
    except Exception:
        return subprocess.DEVNULL


def _после(proc, дальше) -> None:
    """Дождаться процесса в фоне и сделать следующий шаг. Нужен именно
    порядок: индекс печётся ИЗ кэша рифм, и запускать его раньше значило бы
    испечь ровно то, что уже было. Сама механика — core/jobs.py: then (там,
    где до неё дотянется тест; импорт этого файла стоит 69 секунд)."""
    jobs.then(proc, дальше,
              on_error=lambda e: print(f"nakedlunch: следующий шаг сборки не удался ({e})",
                                       flush=True))


def _проследить_за_сборкой(proc) -> None:
    """Умер, не дописав статус, — записать это честно."""
    def смотреть():
        try:
            код = proc.wait()
        except Exception:
            return
        try:
            s = json.loads(_NL_RHYME_STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            # СТАТУСА НЕТ ВОВСЕ — ЭТО ХУДШИЙ СЛУЧАЙ, А НЕ ПОВОД МОЛЧАТЬ
            # (Раунд 60). Ребёнок умер, не успев написать о себе ничего:
            # так и вышло в первой сборке приложения — сборщик пытался писать
            # внутрь бандла, падал на первой строке, а снаружи это выглядело
            # как «сборка ещё не запускалась», и счётчик ошибок показывал ноль.
            if код != 0:
                журнал.запись("сборка", f"сборка ударений упала сразу, код {код} — "
                                        f"подробности в {_СБОРКИ_ЛОГ.name}", "ошибка")
            return
        if s.get("state") != "running":
            return          # сам дописал «готово» или «ошибка» — не трогаем
        журнал.запись("сборка", f"сборка ударений умерла, код {код}", "ошибка")
        s.update({"state": "error",
                  "error": f"процесс сборки завершился с кодом {код} "
                           f"(чаще всего — нехватка памяти: он читает весь кэш "
                           f"целиком; запусти из терминала при закрытом окне)",
                  "updated_at": time.time()})
        try:
            _NL_RHYME_STATUS_PATH.write_text(json.dumps(s, ensure_ascii=False), "utf-8")
        except OSError:
            pass
    threading.Thread(target=смотреть, name="nl-rhyme-watch", daemon=True).start()


def _nl_index_ensure_running() -> None:
    """Перепечь колоночный индекс в фоне, если он не печётся прямо сейчас."""
    global _NL_INDEX_PROC
    if _nl() is None:
        return
    if _NL_INDEX_PROC is not None and _NL_INDEX_PROC.poll() is None:
        return
    import subprocess
    _журнал = _лог_сборки("индекс корпуса")
    _NL_INDEX_PROC = subprocess.Popen(
        дочерний.команда("индекс"), cwd=str(ROOT),
        stdout=_журнал, stderr=subprocess.STDOUT,
    )
    # Испекли — но процесс держит в памяти СТАРЫЙ индекс и старую карту
    # «текст → номер». Без перезагрузки новые строки появились бы только
    # после перезапуска окна.
    _после(_NL_INDEX_PROC, lambda: (nlindex.reload(), _forget_pool_mask()))


_NL_TEXTS_CACHE: tuple | None = None      # (сколько фрагментов, множество текстов)
_NL_ACTIVE_TEXTS_CACHE: tuple | None = None
# Композиция, для которой цепочку уже запускали: чтобы не перепекать по кругу.
_ИНДЕКС_ПРОБОВАЛИ: tuple | None = None


def _nl_active_texts() -> set:
    """Разные тексты АКТИВНОГО пула (Раунд 56).

    Отключённая книга не должна попадать в предупреждение. Строка «столько-то
    вне индекса — в выдачу они не попадут» считалась по ВСЕМ фрагментам
    хранилища, вместе с выключенными книгами. Но выключенная книга в выдачу и
    так не попадает — он сам её выключил. Панель тревожилась о том, чего он
    добивался нарочно.

    Меряем по тому, что реально участвует в выдаче. Выключил книгу — её строки
    перестают считаться недостачей, и строка гаснет сама."""
    global _NL_ACTIVE_TEXTS_CACHE
    пул = _nl().get_active_pool()
    n = len(пул)
    if _NL_ACTIVE_TEXTS_CACHE is not None and _NL_ACTIVE_TEXTS_CACHE[0] == n:
        return _NL_ACTIVE_TEXTS_CACHE[1]
    тексты = set(пул)
    _NL_ACTIVE_TEXTS_CACHE = (n, тексты)
    return тексты


def _nl_texts() -> set:
    """РАЗНЫЕ ТЕКСТЫ хранилища.

    Фрагментов больше, чем текстов: на машине пользователя 2 874 175 против
    2 856 289 — 17 886 дублей (одна и та же строка нарезана из двух книг). И
    кэш рифм, и колоночный индекс ключуются ТЕКСТОМ. Значит сравнивать их с
    числом ФРАГМЕНТОВ — это вычитать разное, и обе строки статуса именно так
    и делали: показывали 99% и «6 075 строк вне индекса» там, где вне его
    ноль.

    0.4 с на 2.87 млн, кэш по числу фрагментов: состав меняется только когда
    пользователь трогает источники, а это двигает и число."""
    global _NL_TEXTS_CACHE
    фрагменты = _nl().state.fragments
    n = len(фрагменты)
    if _NL_TEXTS_CACHE is not None and _NL_TEXTS_CACHE[0] == n:
        return _NL_TEXTS_CACHE[1]
    тексты = {f.text for f in фрагменты}
    _NL_TEXTS_CACHE = (n, тексты)
    return тексты


def _nl_store_status() -> dict | None:
    """Строка топбара на время ПРОГРЕВА (Раунд 54, переписана в Раунде 57).

    Пока идёт прогрев, две соседние строки (рифма и индекс) посчитать НЕЧЕМ:
    обе меряются по составу хранилища. Раньше вопрос не стоял — всё грузилось
    до открытия порта, и опросить статус раньше было нельзя. Теперь окно
    открывается первым, и молчащая шапка читалась бы как «всё готово, просто
    пусто».

    Раунд 57: строка знала только про корпус и гасла, когда он загрузился, —
    а генерация после этого ждала ещё карты индекса, и пользователь опять сидел
    перед пустой сценой без объяснений. Теперь строка живёт ровно столько,
    сколько генерация не готова, и называет текущий этап и его секунды."""
    if _ПРОГРЕВ["готов"]:
        return None
    сек = int(time.time() - _ПРОГРЕВ["начат"])
    return {"id": "nl_store", "label": "Готовим генератор", "state": "running",
            "done": 0, "total": 0, "pct": 0,
            "detail": f"{_ПРОГРЕВ['этап']} · {сек} с — до этого генерация подождёт"}


_ИНДЕКС_СБОРКА_ПУТЬ = пути.артефакт("nl_index.status.json")


def _индекс_сборка() -> dict:
    try:
        return json.loads(_ИНДЕКС_СБОРКА_ПУТЬ.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _подхватить_свежий_индекс() -> None:
    """Индекс на диске новее того, что держит процесс, — перечитать.

    Раунд 56. `nlindex.reload()` звался только тогда, когда перепечку запустил
    ЭТОТ процесс. Испекли иначе — из терминала, прошлым инстансом, любым другим
    способом — и сервер продолжал показывать старую дату «испечён» и работать
    по старым колонкам до перезапуска окна: в панели висело время предыдущей
    сборки.

    Сверка по `built_at` из meta.json: дёшево (маленький ключ в уже читаемом
    файле) и честно — это ровно то, что показывается в панели."""
    idx = nlindex.load()
    if idx is None:
        return
    try:
        на_диске = json.loads((nlindex.INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    except Exception:
        return
    if на_диске.get("built_at") and на_диске["built_at"] != idx.built_at:
        nlindex.reload()


def _nl_index_status() -> dict | None:
    """Строка топбара про колоночный индекс. Появилась потому, что «Рифма
    100%» читалась как «книга готова», а готовность решает ЭТОТ индекс."""
    if not _ПРОГРЕВ["готов"]:
        # Греется — про это говорит _nl_store_status. Раунд 57: было
        # `_nl_ready()`, то есть «корпус в памяти», и статус лез считать
        # состав по картам, которые в этот момент строил прогрев, — опрос
        # шапки вставал на том же замке, что и генерация.
        return None
    global _ИНДЕКС_ПРОБОВАЛИ
    _подхватить_свежий_индекс()
    тексты = _nl_active_texts()
    всего = len(тексты)
    idx = nlindex.load()
    отстал = nlindex.lag(тексты, всего)
    база = {"id": "nl_index", "label": "Индекс корпуса", "total": всего}
    # ЖИВОЙ ПРОГРЕСС ИЗ САЙДКАРА (Раунд 56). Требование: показывать состояние в
    # реальном времени и из реальных данных. Раньше здесь было «перепекается» и
    # ноль процентов на все сорок секунд.
    #
    # Сайдкар главнее живости процесса: перепечку мог запустить и не этот
    # процесс (ручной прогон из терминала, прошлый инстанс сервера), а видеть
    # её пользователь обязан в любом случае.
    сб = _индекс_сборка()
    идёт = (_NL_INDEX_PROC is not None and _NL_INDEX_PROC.poll() is None) or \
           (сб.get("state") == "running" and time.time() - сб.get("updated_at", 0) < 120)
    if идёт:
        всего_сб, сделано_сб = int(сб.get("total") or 0), int(сб.get("done") or 0)
        pct_сб = int(100 * сделано_сб / всего_сб) if всего_сб else 0
        этап = сб.get("stage") or "перепекается"
        детали = f"{этап} · {сделано_сб:,} / {всего_сб:,} ({pct_сб}%)".replace(",", " ") \
            if всего_сб else этап
        return {**база, "state": "running", "done": сделано_сб, "total": всего_сб or всего,
                "pct": pct_сб, "detail": детали}
    if idx is None:
        return {**база, "state": "not_started", "done": 0, "pct": 0,
                "detail": "индекса нет — генерация идёт медленным путём"}
    if отстал is None:
        return {**база, "state": "running", "done": 0, "pct": 0,
                "detail": "проверяю состав…"}
    done = всего - отстал
    # Процент ОКРУГЛЯЕТСЯ ВНИЗ: «100%» обязано значить «не осталось ни одной
    # строки», а не «99.79 округлилось».
    pct = int(100 * done / всего) if всего else 100
    if not отстал:
        _ИНДЕКС_ПРОБОВАЛИ = None
        return {**база, "state": "done", "done": done, "pct": 100,
                "detail": f"испечён {idx.built_at}"}

    # ОТСТАВАНИЕ ЛЕЧИТСЯ САМО (Раунд 56). Ручное подтверждение здесь не нужно:
    # приложение уже умеет
    # перепекать фоном и делает это после заливки книги. Заметить отставание и
    # попросить разрешения — значит переложить свою недоделку на пользователя.
    #
    # Побочное действие в функции статуса — цена осознанная: отдельный сторож
    # был бы третьим механизмом опроса рядом с двумя имеющимися. Замок от
    # повторов — `_ИНДЕКС_ПРОБОВАЛИ`: на одну композицию пула одна попытка.
    # Уже идёт сборка ударений — значит цепочка в пути, и никакой «перепечки
    # после которой не помогло» ещё не было. Раньше здесь этого различия не
    # было, и панель через секунду после запуска сообщала пользователю вывод,
    # которого никто не делал.
    if _NL_RHYME_PROC is not None and _NL_RHYME_PROC.poll() is None:
        return {**база, "state": "running", "done": done, "pct": pct,
                "detail": f"догоняю: {отстал:,} строк ещё вне индекса".replace(",", " ")}
    ключ = (всего, отстал)
    if _ИНДЕКС_ПРОБОВАЛИ != ключ:
        # Отмечаем попытку, ТОЛЬКО если она правда началась: иначе занятая
        # чужой сборкой цепочка считалась бы «уже пробовали».
        if _nl_rhyme_ensure_running():      # цепочка: ударения → индекс
            _ИНДЕКС_ПРОБОВАЛИ = ключ
        return {**база, "state": "running", "done": done, "pct": pct,
                "detail": f"догоняю: {отстал:,} строк ещё вне индекса".replace(",", " ")}
    # Перепекли, а отставание осталось — значит дело НЕ в индексе, а в кэше
    # рифм: индекс печётся из него и больше того, что там есть, не покажет.
    # По кругу не перепекаем: вечный цикл вместо ответа хуже, чем ответ.
    # Перепечка была и не помогла. ПРИЧИНУ НЕ УГАДЫВАЕМ: она записана в
    # data/сборки.log — ровно затем этот лог и заведён. Первая версия этой
    # строки уверенно валила вину на кэш ударений, а настоящая причина была
    # другая (сборщик индекса не грузил кэш вовсе, см. tools/build_nl_index.py).
    return {**база, "state": "stalled", "done": done, "pct": pct,
            "detail": (f"{отстал:,} строк вне индекса, перепечка не помогла — "
                       "причина в data/сборки.log").replace(",", " ")}


_КЭШ_СЧЁТ: tuple | None = None      # (mtime, размер) → сколько записей


def _кэш_записей() -> int | None:
    """Сколько записей ЛЕЖИТ в кэше ударений на самом деле. None — построчного
    кэша нет, тогда сказать нечего.

    Считается по факту и запоминается по (времени, размеру) файла: 2.4 млн
    строк читаются за секунду, а опрос шапки идёт каждые несколько секунд —
    пересчитывать на каждый опрос значило бы жечь диск ради числа, которое
    меняется раз в час."""
    global _КЭШ_СЧЁТ
    try:
        import кэш as _кэш
        if not _кэш.есть_строчный():
            return None
        st = _кэш.СТРОЧНЫЙ.stat()
        ключ = (st.st_mtime, st.st_size)
        if _КЭШ_СЧЁТ is None or _КЭШ_СЧЁТ[0] != ключ:
            n = 0
            with _кэш.СТРОЧНЫЙ.open("rb") as f:
                while True:
                    кусок = f.read(1 << 22)
                    if not кусок:
                        break
                    n += кусок.count(b"\n")
            _КЭШ_СЧЁТ = (ключ, n)
        return _КЭШ_СЧЁТ[1]
    except Exception:
        return None                         # статус — удобство, а не работа


def _nl_rhyme_status() -> dict | None:
    """One entry for /api/status. None (not "не начато") only when there's
    nothing to build at all — no nakedlunch installed, so the item would be
    meaningless rather than merely empty."""
    if not _ПРОГРЕВ["готов"]:
        # Греется — про это говорит _nl_store_status. Раунд 57: было
        # `_nl_ready()`, то есть «корпус в памяти», и статус лез считать
        # состав по картам, которые в этот момент строил прогрев, — опрос
        # шапки вставал на том же замке, что и генерация.
        return None
    # РАЗНЫХ ТЕКСТОВ, а не фрагментов (починка Раунда 52): кэш рифм ключуется
    # текстом, а фрагментов на 17 886 больше — одна и та же строка нарезана из
    # двух книг. Из-за этого полностью готовый кэш показывал 99% и читался как
    # «книга ещё не доехала».
    total = len(_nl_texts())
    base = {"id": "nl_rhyme", "label": "Рифма nakedlunch", "total": total}

    if not _NL_RHYME_STATUS_PATH.exists():
        return {**base, "state": "not_started", "done": 0, "pct": 0,
                "detail": "сборка ещё не запускалась"}

    try:
        s = json.loads(_NL_RHYME_STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {**base, "state": "error", "done": 0, "pct": 0, "detail": "статус-файл повреждён"}

    state = s.get("state", "running")
    if state == "running" and time.time() - s.get("updated_at", 0) > _NL_RHYME_STALE_SECONDS:
        state = "stalled"
    # МЁРТВЫЙ САЙДКАР НЕ ИМЕЕТ ПРАВА ВРАТЬ ВЕЧНО (Раунд 58).
    #
    # В шапке висело: «Рифма nakedlunch · встало · 1 / 2 434 632 (0%)».
    # На диске при этом лежал ПОЛНЫЙ кэш на 2 434 632 записи — все тексты до
    # единого. Врал сайдкар: прерванный пересчёт оставил «running, cached=1» и
    # больше его никто не переписал. А шапка другого источника правды не знала,
    # и убрать это из интерфейса было нельзя ничем — только руками, из файла.
    #
    # Судим по КЭШУ, а не по счётчику мертвеца: он и есть работа, а сайдкар —
    # всего лишь чей-то рассказ о ней. Считается один раз (файл читается за
    # секунду) и запоминается по времени и размеру файла.
    if state == "stalled":
        по_факту = _кэш_записей()
        if по_факту is not None:
            есть = min(по_факту, total)
            if есть >= total:
                return {**base, "state": "done", "done": есть, "total": total, "pct": 100,
                        "detail": f"{есть:,} / {total:,} · разных строк".replace(",", " ")}
            return {**base, "state": "stalled", "done": есть, "total": total,
                    "pct": int(100 * есть / total) if total else 0,
                    "detail": (f"{есть:,} / {total:,} · разных строк — прогон прерван, "
                               "нажми «пересчитать качество» ещё раз").replace(",", " ")}
    # ОШИБКА ГОВОРИТ ПРИЧИНУ (Раунд 57). Сборку, убитую системой за память,
    # видно было как «встало · 1 / 2 434 632 (0%)» — ни слова о том, что
    # случилось и что делать. Теперь причина из сайдкара доезжает до шапки.
    if state == "error" and s.get("error"):
        return {**base, "state": "error", "done": 0, "total": total, "pct": 0,
                "detail": str(s["error"])[:200]}
    # Записей в кэше может быть БОЛЬШЕ, чем текстов в хранилище: тексты
    # удалённых источников из него не вычищаются (2 868 100 против 2 856 289 у
    # «2 868 100 из 2 856 289» — значит просить читателя
    # объяснить себе, как сделано больше, чем есть; лишнее — не прогресс.
    done = min(s.get("cached", 0), total)
    # Процент ВНИЗ, а не round (Раунд 52): «100%» обязано значить «не осталось
    # ни одной строки», а не «99.79 округлилось».
    pct = int(100 * done / total) if total else 100
    # «разных строк» СЛОВОМ (Раунд 56). Рядом в той же панели висит «фрагментов
    # 2 755 698», а здесь стоит 2 434 632, и читатель честно спрашивает, почему
    # числа не сходятся. Не сходятся они потому, что считают РАЗНОЕ: там штуки,
    # тут разные тексты, разница — дубли (одна строка нарезана из двух книг).
    # Вопрос возникает сразу; подпись дешевле, чем объяснение.
    detail = s.get("error") or f"{done:,} / {total:,} ({pct}%) · разных строк".replace(",", " ")
    # "mode" sticks in the status file until the NEXT run overwrites it — so
    # after a manual full rebuild finishes, the topbar keeps saying "полный
    # пересчёт" instead of going back to looking like every other tiny
    # incremental pass (user: "показывать какой мы сделали").
    label = base["label"]
    if s.get("mode") == "full":
        label += " (полный пересчёт)"
    return {**base, "label": label, "state": state, "done": done, "pct": pct, "detail": detail}


# --- пайплайн: замок + прогресс (ФАЗА 1, PLAN.md) --------------------------
# Один прогон за раз: пайплайн — это 6-8 внутренних генераций плюс beam-
# перебор, два параллельных прогона дрались бы за CPU и глобальные сторы
# (Flask threaded=True — второй запрос ПРИДЁТ параллельно). Неблокирующий
# acquire → честный 409, а не молчаливая очередь, в которой второй клик
# ждал бы минуту непонятно чего.
_PIPELINE_LOCK = threading.Lock()
# Прогресс — модульный dict в памяти процесса (по образцу _nl_rhyme_status,
# но без файла-сайдкара: прогон живёт и умирает вместе с процессом, чужим
# процессам этот статус не нужен). Пишет его ТОЛЬКО поток прогона, /api/status
# только читает — гонок нет.
_PIPELINE_PROGRESS: dict = {"state": None, "done": 0, "total": 0, "detail": ""}


def _pipeline_status() -> dict | None:
    """Элемент /api/status на время прогона (и после — с state='done', чтобы
    топбар показал завершение, а не молча исчез). None до самого первого
    прогона — несуществующая работа не заслуживает строки статуса."""
    if _PIPELINE_PROGRESS["state"] is None:
        return None
    p = _PIPELINE_PROGRESS
    pct = round(100 * p["done"] / p["total"]) if p["total"] else 0
    return {"id": "pipeline", "label": "Пайплайн", "state": p["state"],
            "done": p["done"], "total": p["total"], "pct": pct, "detail": p["detail"]}


def _nl_pool_counts() -> tuple[int, int, int]:
    """(active_sources, fragments_in_active, available_not_yet_shown) — the
    real numbers behind the nakedlunch funnel's top, so the UI can say from
    how big a base each request actually samples (user 2026-07-14: "из
    скольки источников по факту, а не нарисовано"). Same methods /api/nl/state
    uses, so the two views can't disagree."""
    if _nl() is None:
        return (0, 0, 0)
    active = sum(1 for c in _nl().list_corpora() if c.get("active"))
    return (active, len(_nl().get_active_pool()),
            len(set(_nl().get_active_pool()) - CORPUS.hidden_set()))


# _rich_funnel ВЫРЕЗАН (Раунд 51, замер аудита). Он превращал плоские счётчики
# каскада в двухтрубную инфографику, которой на фронте больше нет: её
# потребитель funnelData вычислялся на каждую перерисовку и выбрасывался
# (переменная `fu` присваивалась и не читалась ни разу). Половина работы была
# бесплатной — переписать словарь; половина стоила набора из 1.96 млн строк на
# КАЖДЫЙ запрос, то есть до 76% его времени.
#
# _nl_pool_counts остаётся: его честно зовёт /api/nl/state, где числа про
# состав пула и нужны, и где запрос идёт раз в сессию, а не на каждую строфу.

# ============================================================
# Routes — generate, favorite (+remove), state, and history
# (mark_shown/restore/restore_theme/clear/retention — 2026-07-14).
# ============================================================

# ВОРОТА КАЧЕСТВА словарного слоя антонимов (PLAN.md №9: «мусор → вкладка
# скрывается, не фейкуется»). Проверка сборки фазы 2 (2026-08-01), отчёта
# словарного агента на диске не было — прогнаны 10 контрольных слов по живому
# data/thesaurus.json (22 858 ant-ключей): быстрый→медленный/неторопливый,
# холодный→горячий/тёплый, любовь→ненависть/вражда, день→ночь,
# говорить→молчать, большой→маленький/мелкий, правда→ложь/кривда, друг→враг;
# «деньги» — честно пусто; «свет→быдло/люмпен» — законный антоним смысла
# «высший свет». Случайная проба 12 ключей — без мусора. Вердикт: слой
# настоящий, вкладка ВКЛЮЧЕНА. Провал будущей пересборки → False, вкладка
# прячется на фронте (render.doc.jsx фильтрует по /api/state.thesaurus.ant).
_ANT_GATE_PASSED = True


@app.get("/api/state")
def api_state():
    # Наличие словарных слоёв попапа (фаза 2): syn — есть ли словарный слой
    # синонимов (векторный «близкое» жив и без него, вкладка видна всегда);
    # ant — словарь есть И ворота качества пройдены (константа выше).
    th = wordsuggest.thesaurus_status()
    return {"corpus": CORPUS.stats(), "accepted": CORPUS.accepted_texts(),
            "thesaurus": {"syn": th["syn"], "ant": th["ant"] and _ANT_GATE_PASSED}}


@app.get("/api/status")
def api_status():
    """Background-job status for the topbar indicator — a plain list so a
    future build step just adds another entry here, no frontend change."""
    items = [x for x in [_nl_store_status(), _import_status(), _nl_rhyme_status(),
                         _nl_index_status(), _pipeline_status(), _series_status()]
             if x is not None]
    # СЧЁТЧИК ОШИБОК ЕДЕТ С ОПРОСОМ, А НЕ ОТДЕЛЬНЫМ ЗАПРОСОМ (Раунд 59). Опрос
    # и так идёт постоянно; заводить ради двух чисел вторую петлю значило бы
    # платить сетью за то, что уже везут. Отсюда шапка узнаёт, что ошибка была,
    # даже если человек её проглядел, — а «проглядел» здесь норма, потому что
    # ошибка случается в момент, когда он занят строкой, а не программой.
    return {"items": items,
            "ошибок": sum(1 for з in журнал.записи(3000) if з["уровень"] == "ошибка"),
            "аварийно": журнал.не_закрыто()}


@app.post("/api/nl/rhyme/run")
def api_nl_rhyme_run():
    """Manual trigger (user: "есть смысл добавить кнопку... прогнать ударения
    вручную") — always a FULL rebuild (found 2026-07-14: this used to call
    _nl_rhyme_ensure_running() with the same incremental mode as the
    auto-trigger, which was a no-op in seconds once the cache was already
    ~100% complete — the button looked broken. "Ручной" is the user
    explicitly asking for a from-scratch recompute, not a repeat of what
    already happens automatically)."""
    err = _nl_guard()
    if err:
        return err
    начали = _nl_rhyme_ensure_running(full=True)
    if not начали:
        return {"ok": False, "busy": True,
                "detail": "сборка уже идёт — дождись её и нажми снова"}
    return {"ok": True}


@app.post("/api/nl/rhyme/reban")
def api_nl_rhyme_reban():
    """Пересчитать только формулу качества (banal/content) по всему кэшу.

    Отдельная кнопка, а не режим полного прогона: пользователь должен видеть, что
    это ДРУГАЯ по цене работа. Полный прогон — час (нейросетевые ударения);
    этот проход ударений не касается и идёт минуты, поэтому формулу качества
    можно пробовать, а не бояться."""
    err = _nl_guard()
    if err:
        return err
    начали = _nl_rhyme_ensure_running(reban=True)
    if not начали:
        return {"ok": False, "busy": True,
                "detail": "сборка уже идёт — дождись её и нажми снова"}
    return {"ok": True}


def _подписать_источники(shortlist) -> None:
    """Дописать каждой строке выдачи имя книги, откуда она (Раунд 57).

    Требование: при выделении строки видно, из какой она книги, и книгу можно
    отсюда же отключить.

    Делается ЗДЕСЬ, а не в отборе, и это не срезка угла: отбору источник не
    нужен ни для одного решения, а у сервера уже есть и карта «текст → номер
    строки индекса» (nlindex.text_ids), и колонка источника, и имена книг из
    хранилища. Класть в горячий путь то, что нужно только для показа, значило
    бы платить за это каждой генерацией.
    """
    if not shortlist:
        return
    idx = nlindex.load()
    if idx is None or getattr(idx, "src", None) is None:
        return
    try:
        карта = nlindex.text_ids(idx)
        номера = getattr(idx, "sources", []) or []
        имена = {}
        for c in (_nl().list_corpora() if _nl() else []):
            имена[c.get("id")] = c.get("name") or c.get("id")
        for r in shortlist:
            i = карта.get(r.get("text"))
            if i is None:
                continue
            s_i = int(idx.src[i])
            if 0 <= s_i < len(номера):
                cid = номера[s_i]
                r["source_id"] = cid
                r["source"] = имена.get(cid, cid)
    except Exception as e:                                       # noqa: BLE001
        # Подпись — удобство показа. Не смогли — выдача уходит без неё, а не
        # падает пятисотой: цена ошибки здесь не стоит сломанной генерации.
        print(f"nakedlunch: источники к выдаче не приписались ({e})", flush=True)


# ---------------------------------------------------------------------------
# ЧЁРНЫЙ СПИСОК (Раунд 57). Правила и живой счётчик «сколько строк убирает».
# Семантика и цена — см. core/blacklist.py и nlindex.строки_правила.

def _чс_ответ() -> dict:
    правила = blacklist.читать()
    счёт = {}
    if _ПРОГРЕВ["готов"]:
        try:
            счёт = nlindex.запрет(правила)["счёт"]
        except Exception as e:                                   # noqa: BLE001
            print(f"nakedlunch: счётчик чёрного списка не посчитался ({e})", flush=True)
    return {"rules": [{"rule": п, "lines": int(счёт.get(п, 0))} for п in правила],
            "ready": _ПРОГРЕВ["готов"]}


@app.get("/api/nl/blacklist")
def api_nl_blacklist():
    return _чс_ответ()


@app.post("/api/nl/blacklist/add")
def api_nl_blacklist_add():
    payload = request.get_json(force=True, silent=True) or {}
    blacklist.добавить((payload.get("rule") or "").strip())
    nlindex.забыть_запрет()
    return _чс_ответ()


@app.post("/api/nl/blacklist/remove")
def api_nl_blacklist_remove():
    payload = request.get_json(force=True, silent=True) or {}
    blacklist.убрать((payload.get("rule") or "").strip())
    nlindex.забыть_запрет()
    return _чс_ответ()


@app.get("/api/nl/funnel")
def api_nl_funnel():
    """Карта воронки: сколько фрагментов и книг доживает до каждой ступени.

    Раунд 57. Требование: видеть, как работает каждая ступень отбора, чтобы
    ею управлять. До этого цена каждой ручки была известна только
    на словах — и три правки подряд били по симптомам ровно потому, что
    посмотреть было некуда.

    Считается по колонкам индекса, без похода в отбор: это карта ПУЛА. Ручки
    берутся из запроса, чтобы пользователь видел цену СВОИХ настроек, а не средних.
    """
    if not _ПРОГРЕВ["готов"]:
        return {"ready": False}
    # ПОЛОЖЕНИЕ РУЧКИ, А НЕ ВЫВЕДЕННЫЙ ИЗ НЕЁ ПОТОЛОК (Раунд 58). Раньше
    # интерфейс считал `6.5 − 2.5·ручка` сам и слал результат — вторая копия
    # формулы, живущая на фронте. Теперь формула одна (nlindex), а сюда
    # приезжает то, что пользователь реально видит на экране.
    try:
        ручка = float(request.args.get("banality", 0.5))
    except (TypeError, ValueError):
        ручка = 0.5
    try:
        слов = int(request.args.get("content", 0))
    except (TypeError, ValueError):
        слов = 0
    имена = {}
    try:
        for c in (_nl().list_corpora() if _nl() else []):
            имена[c.get("id")] = c.get("name") or c.get("id")
    except Exception:
        pass
    данные = nlindex.воронка(
        ручка=ручка,
        no_mat=request.args.get("no_mat") == "1",
        only_mat=request.args.get("only_mat") == "1",
        clausula=int(request.args.get("clausula") or 0),
        content_min=слов,
    )
    if данные is None:
        return {"ready": False, "detail": "индекс не испечён"}
    # Идентификатор книги пользователю ничего не говорит — подставляем имя.
    for и in данные.get("источники", []):
        и["источник"] = имена.get(и["источник"], и["источник"])
    return {"ready": True, **данные}


@app.post("/api/generate")
def api_generate():
    t0 = time.time()
    payload = request.get_json(force=True, silent=True) or {}

    # Theme is optional now (can generate without one)
    theme_raw = payload.get("theme", "").strip()
    tags = []
    forced = set()
    if theme_raw:
        try:
            tags = clean.theme(theme_raw)
        except clean.BadInput as e:
            return {"error": str(e)}, 400
        forced = clean.theme_forced(theme_raw)   # !слово — see PLAN.md 0.2b

    # Bias and rhyme from unified mode (new params)
    bias = (payload.get("bias", "") or "").strip()
    # Строфа-конструктор (2026-07-18, PLAN.md 0.7) — если пришёл валидный
    # `stanza` (список {letter,min_syl,max_syl}), он ПЕРЕОПРЕДЕЛЯЕТ `rhyme`:
    # буквы схемы выводятся ИЗ спеки (clean.stanza_letters), не из отдельно
    # присланной строки — один источник правды на запрос, не два, которые
    # могут разойтись. Без `stanza` — прежнее поведение, ровно как раньше.
    stanza = clean.stanza_spec(payload.get("stanza"))
    rhyme = clean.stanza_letters(stanza) if stanza else clean.rhyme_scheme(payload.get("rhyme", "none"))

    # Крутилки: профиль настроек в КООРДИНАТАХ ИНТЕРФЕЙСА ({mode, params}) —
    # основной путь с Раунда 51. Переводит их единственный переводчик,
    # clean.knobs_from_profile: до этого перевод жил на фронте в JS, а
    # питоновский двойник, объявленный «единственным местом», не вызывался
    # нигде — два независимых списка инверсий, которые уже расходились.
    # Ядерный `knobs` по-прежнему принимается: им ходят тесты и внутренние
    # вызовы домена (core/pipeline.py собирает пулы уже готовыми кнобами).
    if isinstance(payload.get("params"), dict) or payload.get("mode"):
        knobs = clean.knobs_from_profile({"name": "запрос", "mode": payload.get("mode"),
                                          "params": payload.get("params")})
        try:
            knobs["shortlist"] = int(float(payload.get("shortlist", knobs["shortlist"])))
        except (TypeError, ValueError):
            pass
        knobs = clean.knobs(knobs)      # клампы и алиасы — один раз, здесь
    else:
        knobs = clean.knobs(payload.get("knobs"))

    # When there's a bias input, treat it as an additional context (not used yet,
    # but preserved for future use when we wire it into generation/scoring)

    # Two independent pipelines feed the shortlist; each is only run when it
    # can actually REACH the shortlist. real_text=1.0 → 100% nakedlunch, so
    # the grammar generator is skipped entirely instead of making 2000 lines
    # that get filtered and then discarded (2026-07-14 — that wasted work was
    # also what made the "кандидатов 2000" counter lie: it showed a pipeline
    # that contributed nothing). real_text=0.0 → the nl fetch is skipped, same
    # reasoning (already guarded below by nl_mix > 0).
    gen_active = knobs["nl_mix"] < 1.0
    nl_active = knobs["nl_mix"] > 0 and _nl() is not None

    lines = []
    if gen_active:
        # n scales with the SHORTLIST, not the dictionary (see DECISIONS.md
        # Round 13 — measured: rhyme-pair completion and shortlist fill rate
        # don't improve past a few thousand raw candidates regardless of the
        # 32k-lemma vocab; the old vocab-scaled formula only bought 10-40x
        # slower requests, not better output).
        n = max(2000, int(knobs["shortlist"]) * 50)
        lines = generate.generate(tags, n=n)

    nl_frags = []
    if nl_active:
        # The WHOLE active-and-not-yet-shown pool, every request — not a
        # sample (2026-07-14, user: "пусть обрабатывается и перебирается
        # всегда именно полная база абсолютно везде"). Previously fetched a
        # capped random/weighted slice (as few as 320 of 257,630 fragments for
        # an unthemed max-real_text request — the user's own "это бред"
        # finding); that cap only existed because scoring needed live
        # pymorphy3/zipf calls per fragment. tools/build_nl_rhyme.py now
        # precomputes banal/taut/lemmas/tokens offline, so filters._nl_scored
        # scans the full pool as dict lookups — measured ~24ms/200k entries,
        # see DECISIONS.md. Theme relevance still matters: it's now a SCORE
        # (shared tokens with `tags`) computed inside _nl_scored instead of a
        # pre-filter, so on-theme fragments rank first without needing a
        # smaller candidate set to find them in.
        # Раунд 40: активный пул целиком. Показанное скрывает НАША история
        # (единственный источник, см. _merge_nl_used_once) — filters.run
        # вычитает corpus.hidden_set() сам.
        nl_frags = _nl().get_active_pool()

    result = filters.run(lines, knobs, CORPUS, nl_fragments=nl_frags, rhyme=rhyme, tags=tags, forced=forced,
                         stanza=stanza)
    _подписать_источники(result.get("shortlist") or [])
    # NOT marked into history here (2026-07-14 — was `CORPUS.mark_seen(...)`
    # unconditionally on every generate). History now records what's actually
    # DISPLAYED, not what's merely generated — freestyle prefetches a stanza
    # well before showing it, and a prefetched-but-unseen stanza must not
    # count ("в историю идут только непосредственно на экране в данный
    # момент показывающиеся строфы"). The client calls
    # POST /api/history/mark_shown at the moment of actual display.
    # ВОРОНКА УШЛА ИЗ ГОРЯЧЕГО ПУТИ (Раунд 51, замер аудита).
    #
    # `_rich_funnel` звал `_nl_pool_counts`, а тот дважды копировал активный
    # пул (1.96 млн строк) и строил из него set: замерено 0.47–0.92 с — это
    # 75-76% всего запроса в классике и 62-67% в алгоритме без темы. Ради
    # трёх чисел, из которых два не читал НИКТО, а третье (pool_available)
    # нужно только чтобы объяснить ПУСТУЮ выдачу. Инфографика, которую эти
    # числа кормили, вырезана с фронта ещё в Раунде 50 — там даже переменная
    # `fu` присваивалась и не использовалась.
    #
    # Теперь: плоские счётчики каскада отдаём как есть (они бесплатны, их
    # считает сам filters.run), а дорогое число доливаем ТОЛЬКО когда выдача
    # пуста — то есть ровно тогда, когда фронту надо объяснить причину.
    if not result["shortlist"] and nl_active and _nl() is not None:
        result["funnel"]["pool_available"] = len(
            set(_nl().get_active_pool()) - CORPUS.hidden_set())

    # Only the user-facing sliders (matching App.jsx's KNOBS) — clean.knobs()
    # also carries old-name aliases (explore/meter/banal/nl_mix) for the same
    # values plus non-slider fields (shortlist), which would double-count and
    # add a meaningless average if logged as-is.
    ui_knobs = {k: knobs[k] for k in ("melody", "cohesion", "banality", "real_text",
                                       "rhyme_precision", "classic") if k in knobs}
    # ПОЧИНКА: воронка ПЛОСКАЯ, как её отдаёт filters.run. Здесь стояли три
    # выражения по ВЛОЖЕННОМУ виду (funnel["gen"]["used"]) — его давал
    # `_rich_funnel`, вырезанный из горячего пути тем же раундом. То есть
    # КАЖДЫЙ вызов /api/generate падал 500-й ровно здесь, уже собрав выдачу:
    # самое частое действие приложения было мертво целиком при зелёных тестах
    # и зелёной сборке. Разбор воронки уехал в core/stats.py: from_funnel —
    # туда, где его может проверить тест (роут не зовёт ни один).
    stats_mod.log(
        "generate",
        source=(payload.get("source") or "editor"),
        theme=theme_raw,
        rhyme=rhyme,
        knobs=ui_knobs,
        latency_ms=round((time.time() - t0) * 1000, 1),
        **stats_mod.from_funnel(result["funnel"]),
    )
    return result


@app.post("/api/pipeline/profile")
def api_pipeline_profile():
    """Референс → профиль и готовая цепочка (Раунд 45).

    Требование: по референтному тексту и проценту референтности пайплайн сам
    назначает себе структуру. Роут
    ничего не генерирует и ничего не сохраняет — только меряет текст и
    отдаёт то, чем его можно повторить."""
    payload = request.get_json(force=True, silent=True) or {}
    text = payload.get("text") or ""
    if not text.strip():
        return {"error": "пустой референс"}, 400
    try:
        ref = float(payload.get("ref", 1.0))
    except (TypeError, ValueError):
        ref = 1.0
    try:
        prof = refprofile.профиль(text)
    except clean.BadInput as e:
        return {"error": str(e)}, 400
    out = refprofile.цепочка(prof, ref)
    out["profile"] = prof
    return out


@app.post("/api/pipeline/curve")
def api_pipeline_curve():
    """Кривая → крутилки на каждое звено (Раунд 53).

    Тот же слот, что у /api/pipeline/profile: фронт кладёт ответ туда же и
    разбирает тем же резолвером. Разница только в источнике — там замеренный
    текст, здесь форма."""
    payload = request.get_json(force=True, silent=True) or {}
    try:
        n = int(float(payload.get("n", 0)))
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return {"error": "нечего вести: в цепочке нет звеньев"}, 400
    try:
        сила = float(payload.get("сила", payload.get("force", 1.0)))
    except (TypeError, ValueError):
        сила = 1.0
    форма = payload.get("форма") or payload.get("shape") or curve.ФОРМЫ[0]
    out = curve.цепочка(n, форма, сила)
    out["плотность"] = curve.плотность(n, форма, сила)
    return out


@app.post("/api/pipeline/run")
def api_pipeline_run():
    """Пайплайн (ФАЗА 1): пулы по звеньям + комбинаторная склейка — см.
    core/pipeline.py. Роут синхронный, как /api/generate (Flask threaded —
    /api/status опрашивается параллельными запросами и видит прогресс);
    замок отдаёт 409 второму прогону вместо очереди."""
    payload = request.get_json(force=True, silent=True) or {}
    try:
        spec = clean.pipeline_spec(payload)
    except clean.BadInput as e:
        return {"error": str(e)}, 400
    if not _PIPELINE_LOCK.acquire(blocking=False):
        return {"error": "прогон уже идёт"}, 409
    t0 = time.time()
    try:
        _PIPELINE_PROGRESS.update(state="running", done=0, total=1, detail="подготовка")

        def _progress(done: int, total: int, detail: str) -> None:
            _PIPELINE_PROGRESS.update(done=done, total=total, detail=detail)

        nl_frags = _nl().get_active_pool() if _nl() is not None else []
        try:
            result = pipeline.run_pipeline(spec, CORPUS, nl_frags, progress=_progress)
        except clean.BadInput as e:
            # resolve_chain: пользователь назвал несуществующую форму — это 400
            # запроса, не 500 сервера; finally ниже честно погасит статус.
            return {"error": str(e)}, 400
        _PIPELINE_PROGRESS.update(state="done",
                                  detail=f"готово · вариантов: {len(result['variants'])}")
        stats_mod.log(
            "pipeline",
            theme=spec["theme"],
            links=len(spec["chain"]),
            junctions=spec["junctions"],
            runs=spec["runs"],
            evaluated=result["funnel"]["evaluated"],
            variants=len(result["variants"]),
            latency_ms=round((time.time() - t0) * 1000, 1),
        )
        return result
    finally:
        if _PIPELINE_PROGRESS["state"] == "running":   # вышли ошибкой — не врать «running»
            _PIPELINE_PROGRESS.update(state="done", detail="прервано ошибкой")
        _PIPELINE_LOCK.release()


@app.post("/api/favorite")
def api_favorite():
    """The only verb left for a shown line (2026-07-14: reject removed — "минус
    ... бессмысленна", every shown line already lands in reversible history on
    its own, see corpus.py). Favoriting is permanent until explicitly undone
    via /api/favorite/remove."""
    payload = request.get_json(force=True, silent=True) or {}
    try:
        text = clean.favorite(payload)
    except clean.BadInput as e:
        return {"error": str(e)}, 400
    # the client echoes back the lemma set /api/generate computed for this
    # exact candidate (filters._cand_lemmas) — avoids re-parsing the surface
    # text, and is more correct on homographs than a cold re-guess.
    raw = payload.get("lemmas")
    lemmas = [w for w in raw if isinstance(w, str)][:20] if isinstance(raw, list) else None
    CORPUS.accept(text, lemmas=lemmas, rhyme=payload.get("rhyme", ""))
    CORPUS.save()                                  # favorites can't be lost (ergonomic invariant)
    stats_mod.log("favorite", text=text, template=(payload.get("template") or ""),
                   lemmas=lemmas or [])
    return {"corpus": CORPUS.stats(), "accepted": CORPUS.accepted_texts()}


@app.post("/api/favorite/remove")
def api_favorite_remove():
    """The user's own explicit removal — the only way a favorite ever
    disappears ("никуда не пропадает никогда пока я сам не удалю")."""
    payload = request.get_json(force=True, silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return {"error": "пустая строка"}, 400
    CORPUS.unaccept(text)
    CORPUS.save()
    stats_mod.log("unfavorite", text=text)
    return {"corpus": CORPUS.stats(), "accepted": CORPUS.accepted_texts()}


# ---- history — reversible hiding of shown lines -------------------------

@app.get("/api/history")
def api_history_list():
    q = (request.args.get("q") or "").strip()
    return {"items": CORPUS.history_list(q), "stats": CORPUS.stats()}


@app.post("/api/history/mark_shown")
def api_history_mark_shown():
    """Called at the moment lines are actually DISPLAYED — not at generation
    time (see /api/generate's own note). `items`: [{"text","template"}, ...]."""
    payload = request.get_json(force=True, silent=True) or {}
    items = payload.get("items")
    if not isinstance(items, list):
        return {"error": "нужен список items"}, 400
    clean_items = [it for it in items if isinstance(it, dict) and (it.get("text") or "").strip()][:400]
    theme = payload.get("theme") or ""
    CORPUS.mark_shown(clean_items, theme=theme)
    CORPUS.save()
    stats_mod.log("shown", count=len(clean_items), theme=theme)
    return {"stats": CORPUS.stats()}


@app.post("/api/history/restore")
def api_history_restore():
    payload = request.get_json(force=True, silent=True) or {}
    texts = payload.get("texts")
    if not isinstance(texts, list) or not texts:
        return {"error": "нужен непустой список texts"}, 400
    n = CORPUS.restore([t for t in texts if isinstance(t, str)])
    CORPUS.save()
    stats_mod.log("restore", count=n)
    return {"restored": n, "stats": CORPUS.stats()}


@app.post("/api/history/restore_theme")
def api_history_restore_theme():
    payload = request.get_json(force=True, silent=True) or {}
    theme = (payload.get("theme") or "").strip()
    if not theme:
        return {"error": "пустая тема"}, 400
    n = CORPUS.restore_by_theme(theme)
    CORPUS.save()
    stats_mod.log("restore_theme", theme=theme, count=n)
    return {"restored": n, "stats": CORPUS.stats()}


@app.post("/api/history/clear")
def api_history_clear():
    n = CORPUS.clear_history()
    CORPUS.save()
    stats_mod.log("clear_history", count=n)
    return {"cleared": n, "stats": CORPUS.stats()}


@app.get("/api/history/retention")
def api_history_retention_get():
    return {"days": CORPUS.retention_days, "presets": corpus_mod.RETENTION_PRESETS}


@app.post("/api/history/retention")
def api_history_retention_set():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        days = float(payload.get("days"))
    except (TypeError, ValueError):
        return {"error": "days должен быть числом"}, 400
    CORPUS.set_retention(days)
    CORPUS.save()
    return {"days": CORPUS.retention_days}


@app.get("/api/stats")
def api_stats():
    """Aggregated analytics for the sidebar Statistics tab — pure display,
    never fed back into filters.py/corpus.py (that would reintroduce the
    λ-preference mechanism removed 2026-07-14, see core/stats.py)."""
    return {"stats": stats_mod.summary(), "corpus": CORPUS.stats()}


@app.get("/api/stats/export.json")
def api_stats_export_json():
    """The RAW event log, not summary()'s aggregates (user 2026-07-14:
    "чтобы потом проанализировать" — aggregation is for the in-app tab only;
    real offline analysis wants individual events)."""
    return Response(stats_mod.export_json(), mimetype="application/json",
                     headers={"Content-Disposition": "attachment; filename=extendo-stats.json"})


@app.get("/api/stats/export.csv")
def api_stats_export_csv():
    return Response(stats_mod.export_csv(), mimetype="text/csv",
                     headers={"Content-Disposition": "attachment; filename=extendo-stats.csv"})


@app.get("/api/corpus/export.json")
def api_corpus_export():
    """избранное + история + чёрный список, as one downloadable file — the
    user's only copy of this data lives in data/corpus.json, outside git
    (no repo here at all), so a one-click backup costs nothing and saves
    everything if the machine ever loses that file."""
    CORPUS.save()   # make sure the file on disk matches in-memory state
    return send_from_directory(corpus_mod.DATA_DIR, corpus_mod.CORPUS_PATH.name,
                                as_attachment=True, download_name="extendo-corpus-backup.json")


# The sliders the settings panel actually owns — same six as the stats log's
# `ui_knobs` (see api_generate). clean.knobs() also returns the pre-unified-mode
# aliases (explore/meter/banal/nl_mix) holding DUPLICATE values plus a
# `shortlist` the UI overrides per-request anyway; persisting those would make
# data/settings.json a file where "cohesion" and "explore" disagree after a
# hand-edit, and where a stale `shortlist` looks meaningful. Store the six real
# ones — the file is meant to be openable and obvious.
# Раунд 51: ключ `knobs` (координаты ЯДРА) убран из настроек целиком. Живые
# положения панели живут в `nl_params` (координаты интерфейса), и это
# единственный склад. Второй существовал с прежнего интерфейса, никем не
# перезаписывался и при этом читался попапом слова — то есть тихо управлял
# подсказками из прошлого.


@app.get("/api/settings")
def api_settings_get():
    """The user's own slider positions AND stanza spec (2026-07-18) — see
    core/settings.py for why a file and not localStorage. `knobs` and
    `stanza` both go back through their clean.py validators on the way out,
    so a stale-schema or hand-edited file is clamped/defaulted exactly like
    a live value arriving from the UI, never trusted raw.

    `stanza: null` is a MEANINGFUL stored value — the user's own "нет"
    (no scheme) choice — not the same as the key being absent (never saved
    at all, or a hand-edited file dropped it). clean.stanza_spec(None)
    returns None too, so this line does double duty: normalize a real spec,
    or pass an explicit null straight through unharmed."""
    stored = settings_mod.read()
    out = dict(stored)
    if "stanza" in stored:
        out["stanza"] = clean.stanza_spec(stored["stanza"])
    return out


@app.post("/api/settings")
def api_settings_post():
    """Save slider positions and/or the current stanza spec. Same validation
    on the way IN — clean.knobs()/clean.stanza_spec() normalize before
    anything is persisted, so the file can't end up holding a value the
    domain would reject.

    `stanza: null` is stored AS null (2026-07-18) — the user's own "нет"
    (no scheme) choice is a real, persistable preference, not just "ignore
    this key." Gating on truthiness here (`if spec: ...`) would silently
    keep whatever non-null spec was saved last, so choosing "нет" and
    reopening the app later would revert to an old scheme the user
    explicitly moved away from — settings_mod.write() merges by key, so an
    omitted key means "leave the old value," but an explicit None means
    "clear it," and only sending the key when spec is truthy could never
    express the second one."""
    payload = request.get_json(force=True, silent=True) or {}
    to_save = {
        k: payload[k]
        for k in ("stanza_profile", "nl_smart_folders", "nl_chain",
                  "nl_fs_profiles", "nl_ui_profiles", "nl_palette", "nl_view")
        if k in payload
    }
    # nl_params — ПОСЛЕДНИЕ положения крутилок в координатах интерфейса: то,
    # что стоит в панели прямо сейчас, чтобы окно открывалось там же, где его
    # закрыли. Именованные наборы живут на своей полке (/api/knobs/profiles).
    #
    # Ключ заведён и здесь, и в settings._ALLOWED: фильтра два, и второй молча
    # съедал ключ, пропущенный в первом (так и вышло при первой живой проверке
    # — схема сохранялась, крутилки нет).
    #
    # Раунд 50: проверка через clean.knob_params — единственный канон имён и
    # диапазонов. Прежний список _PROFILE_PARAMS жил тут своей жизнью и УЖЕ
    # разошёлся с фронтом: в нём не было ни «Отбор», ни «Мат», и обе крутилки
    # месяцами не сохранялись.
    if "nl_params" in payload:
        raw = payload["nl_params"] if isinstance(payload["nl_params"], dict) else {}
        entry = {"params": clean.knob_params(raw.get("params"))}
        mode = raw.get("mode")
        entry["mode"] = mode if mode in clean.KNOB_MODES else clean.MODE_ALGO
        to_save["nl_params"] = entry
    if "stanza" in payload:
        to_save["stanza"] = clean.stanza_spec(payload["stanza"])
    return settings_mod.write(to_save)


@app.get("/api/stanza/profiles")
def api_stanza_profiles_get():
    """Built-in verse forms (core/data/stanza_forms.json, read-only, 24
    classical/eastern/modern/folk forms) + the user's own saved profiles
    (data/stanza_profiles.json) — see core/stanza_profiles.py. Every
    profile's `lines` is re-validated through clean.stanza_spec() here, not
    trusted raw from either file — a hand-edited custom profile that no
    longer validates is silently dropped rather than shipped broken to the
    constructor UI."""
    def valid(p):
        spec = clean.stanza_spec(p.get("lines"))
        return {**p, "lines": spec} if spec else None

    builtin = [p for p in (valid(p) for p in stanza_profiles.builtin()) if p]
    custom = [p for p in (valid(p) for p in stanza_profiles.custom()) if p]
    return {"builtin": builtin, "custom": custom}


# Раунд 50: _PROFILE_PARAMS вырезан. Профиль строфы хранил рядом со схемой и
# положения крутилок, и выбор формы молча двигал ползунки — то самое смешение
# каркаса с настройками, которое пользователь разделил на две полки. Заодно ушёл
# белый список, который УЖЕ разошёлся с фронтом: в нём не было ни «Отбор», ни
# «Мат», и обе крутилки месяцами не сохранялись (видно в data/settings.json).

@app.post("/api/stanza/profiles")
def api_stanza_profiles_post():
    """Сохранить (или перезаписать по имени) свою форму строфы — только
    КАРКАС. Крутилки живут на своей полке: /api/knobs/profiles."""
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return {"error": "у профиля должно быть имя"}, 400
    spec = clean.stanza_spec(payload.get("lines"))
    if not spec:
        return {"error": "некорректная строфа — не сохранено"}, 400
    return {"custom": stanza_profiles.save(name, spec)}


@app.post("/api/stanza/profiles/delete")
def api_stanza_profiles_delete():
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return {"error": "не указано имя профиля"}, 400
    return {"custom": stanza_profiles.delete(name)}


# ---- профили настроек: вторая полка (Раунд 50) ---------------------------
# Требование: каркас строфы и положения крутилок сохраняются РАЗДЕЛЬНО, двумя
# независимыми полками. Роуты зеркалят
# строфовые один в один: та же форма ответа {builtin, custom}, та же
# перезапись по имени, то же удаление — две полки не должны требовать двух
# разных привычек.

@app.get("/api/knobs/profiles")
def api_knob_profiles_get():
    return {"builtin": knob_profiles.builtin(), "custom": knob_profiles.custom()}


@app.post("/api/knobs/profiles")
def api_knob_profiles_post():
    payload = request.get_json(force=True, silent=True) or {}
    try:
        return {"custom": knob_profiles.save(payload.get("name"),
                                             payload.get("mode"),
                                             payload.get("params"))}
    except clean.BadInput as e:
        return {"error": str(e)}, 400


@app.post("/api/knobs/profiles/delete")
def api_knob_profiles_delete():
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return {"error": "не указано имя профиля"}, 400
    return {"custom": knob_profiles.delete(name)}


# ---- цепочки: третья полка, слепками (Раунд 50) --------------------------
# Раньше жили ключом nl_chain_profiles внутри settings.json, сырьём и без
# единой проверки на обоих концах. Теперь как две соседние полки: свой файл,
# валидатор в clean.py, отказ ДО записи — а не через минуту на прогоне.

@app.get("/api/chains")
def api_chains_get():
    # builtin рядом с custom — как у форм строф и профилей настроек
    # (Раунд 55): встроенные цепочки такие же записи полки, и серия
    # находит их по имени наравне со своими.
    return {"builtin": chain_profiles.builtin(), "custom": chain_profiles.custom()}


@app.post("/api/chains")
def api_chains_post():
    try:
        return {"builtin": chain_profiles.builtin(),
                "custom": chain_profiles.save(request.get_json(force=True, silent=True) or {})}
    except clean.BadInput as e:
        return {"error": str(e)}, 400


@app.post("/api/chains/delete")
def api_chains_delete():
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return {"error": "не указано имя цепочки"}, 400
    return {"builtin": chain_profiles.builtin(), "custom": chain_profiles.delete(name)}


# --- полка СЕРИЙ: четвёртый уровень (Раунд 53) -----------------------------
# Только хранение. Прогон серии — отдельный механизм со своей очередью и
# раскладкой; мешать «что хранится» с «как исполняется» значит завести третью
# сущность, которая ни то ни другое.

def _series_out(items: list[dict]) -> dict:
    """Полка плюс оценка времени на каждую серию. Оценку считает домен
    (core/series.py: estimate) — число берётся из замеров прогона, и пользователь
    обязан видеть его ДО запуска, а не утром."""
    return {"custom": [{**s, "estimate": series_mod.estimate(s)} for s in items],
            # Секунды на текст едут ЧИСЛОМ, а не зеркалятся на фронте: пока
            # серия правится и ещё не сохранена, оценку показывает интерфейс —
            # и считать её он должен ТЕМ ЖЕ числом, что домен, а не своей
            # копией, которая однажды разойдётся.
            "seconds_per_text": series_mod.SECONDS_PER_TEXT}


@app.get("/api/series")
def api_series_get():
    return _series_out(series_mod.custom())


@app.post("/api/series")
def api_series_post():
    try:
        return _series_out(series_mod.save(request.get_json(force=True, silent=True) or {}))
    except clean.BadInput as e:
        return {"error": str(e)}, 400


@app.post("/api/series/delete")
def api_series_delete():
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return {"error": "не указано имя серии"}, 400
    return _series_out(series_mod.delete(name))


# --- ПРОГОН серии ----------------------------------------------------------
#
# Живёт ВНУТРИ окна (решение «можно закрыть окно».
#
# ЗАМОК БЕРЁТСЯ НА ОДИН ТЕКСТ, а не на всю серию: иначе она держала бы его
# часами и пользователь не смог бы сгенерировать ничего руками. Ручной прогон
# получит 409 только на те ~15 секунд, пока считается очередной текст серии.
_SERIES_PROGRESS: dict = {"state": None, "done": 0, "total": 0, "detail": "",
                          "name": "", "link": None, "beda": {}}
_SERIES_STOP = threading.Event()
_SERIES_THREAD = None


# ЗАЛИВКА КНИГИ ИДЁТ ФОНОМ (Раунд 56).
#
# Требование (2026-08-05): заливка книг долгая и до этого шла без единого
# признака жизни — нажатие не подтверждалось ничем. Книга должна появляться в
# списке сразу, а обработка идти фоном и быть видимой.
#
# Раньше роут делал ВСЁ внутри HTTP-запроса: разбор файла, `strip_full_names`
# (pymorphy3 по всему тексту книги — большая часть времени), нарезку и полную
# запись state.json на 549 МБ. Браузер держал соединение минутами и не мог
# сказать ни слова о том, что происходит.
#
# Теперь роут отдаёт ответ сразу, а работа уходит в поток и отчитывается через
# /api/status — тот же список, что показывает кружок в шапке. Фронт под него
# уже написан общим списком, отдельного механизма прогресса заводить не
# пришлось: новый пункт добавляется здесь одной функцией.
_IMPORT: dict = {"state": None, "files": [], "i": 0, "n": 0, "detail": "",
                 "added": [], "errors": [], "done_at": 0.0}
# Сколько держать ЗАКОНЧЕННУЮ заливку в списке работ. Законченная работа не
# должна висеть в панели до перезапуска (замечание 2026-08-05).
#
# Кнопки не будет — по той же причине, что и у перепечки индекса: убирать за
# собой должно приложение. Заливка это СОБЫТИЕ, а не состояние (в отличие от
# «Рифма» и «Индекс», которые описывают, как обстоят дела прямо сейчас, и
# поэтому висят всегда). Событие отжило — уходит само.
_ЗАЛИВКА_ДЕРЖИМ = 40.0
_IMPORT_LOCK = threading.Lock()


def _коротко(имя: str, сколько: int = 24) -> str:
    """Имя книги для строки статуса. Файлы у Файлы называются «Blavatskaya_Teosofiya_2_Razoblachennaya_Izida_Tom_II_7dLwng_1…» — целиком
    они разносят панель, а хвост с хэшем не говорит ничего."""
    имя = str(имя or "").rsplit(".", 1)[0]
    return имя if len(имя) <= сколько else имя[:сколько - 1] + "…"


def _import_status() -> dict | None:
    if _IMPORT["state"] is None:
        return None
    if _IMPORT["state"] != "running" and time.time() - _IMPORT.get("done_at", 0) > _ЗАЛИВКА_ДЕРЖИМ:
        return None                     # отжило — убираем сами, без кнопки
    n, i = _IMPORT["n"], _IMPORT["i"]
    # процент по файлам, а не по этапам: этапы разной длины, и линейная шкала
    # по ним врала бы сильнее, чем грубая по файлам
    pct = int(100 * i / n) if n else 0
    имя = _коротко(_IMPORT["files"][min(i, n - 1)]) if n else ""
    # min: в конце `i` равен числу файлов, и «3 из 2» было бы враньём о счёте
    подпись = f"Книга · {имя}" if n == 1 else f"Книги · {min(i + 1, n)} из {n} · {имя}"
    return {"id": "import", "label": подпись, "state": _IMPORT["state"],
            "done": i, "total": n, "pct": pct, "detail": _IMPORT["detail"]}


def _import_worker(payload: list) -> None:
    """payload — [(имя файла, байты)]. Один поток на пачку: стор не потокобезопасен,
    и две заливки разом порвали бы список фрагментов."""
    added, errors = [], []
    try:
        for i, (имя, data) in enumerate(payload):
            _IMPORT.update({"i": i, "detail": "начинаю"})

            def шаг(этап, _и=i):
                _IMPORT.update({"i": _и, "detail": этап})

            try:
                corp = nlbridge.add_source_from_bytes(_nl(), имя, data, save=False, шаг=шаг)
                added.append({"name": corp.name, "fragment_count": corp.fragment_count})
            except ValueError as ve:
                errors.append({"name": имя, "error": str(ve)})
            except Exception as e:                                   # noqa: BLE001
                errors.append({"name": имя, "error": str(e)})
        if added:
            # ОДНА запись на всю пачку, а не на каждую книгу: state.json это
            # 549 МБ, и пять файлов стоили бы пяти таких записей.
            _IMPORT.update({"i": len(payload), "detail": "сохраняю корпус"})
            _nl().flush()
            _forget_pool_mask()
            _IMPORT.update({"detail": "считаю ударения"})
            _nl_rhyme_ensure_running()
        # Коротко и читаемо. Раньше сюда выкладывались ПОЛНЫЕ имена файлов со
        # своими хэшами — три книги давали простыню на четыре строки, которая
        # вылезала за панель. Сколько книг и сколько строк — это и есть ответ
        # на «залилось ли»; имена пользователь видит в списке источников рядом.
        фраг = sum(a.get("fragment_count") or 0 for a in added)
        чего = "книга" if len(added) == 1 else ("книги" if len(added) < 5 else "книг")
        хвост = f"добавлено {len(added)} {чего} · {фраг:,} фрагментов".replace(",", " ") if added else ""
        if errors:
            хвост += ("; " if хвост else "") + f"не вышло: {len(errors)} — " + \
                     "; ".join(f'{_коротко(e["name"])}: {e["error"]}' for e in errors[:2])
        _IMPORT.update({"state": "error" if errors and not added else "done",
                        "i": len(payload), "added": added, "errors": errors,
                        "done_at": time.time(), "detail": хвост})
    except Exception as e:                                           # noqa: BLE001
        _IMPORT.update({"state": "error", "detail": str(e)})


def _series_status() -> dict | None:
    if _SERIES_PROGRESS["state"] is None:
        return None
    p = _SERIES_PROGRESS
    pct = int(100 * p["done"] / p["total"]) if p["total"] else 0
    return {"id": "series", "label": f"Серия · {p['name']}", "state": p["state"],
            "done": p["done"], "total": p["total"], "pct": pct, "detail": p["detail"]}


# СКОЛЬКО НА САМОМ ДЕЛЕ СТОИТ ТЕКСТ (Раунд 55).
#
# Константа в 15 секунд была замерена на цепочке из четырёх коротких звеньев.
# На цепочке пользователя («тест2»: Частушка, Рубаи, Одическая строфа в десять
# строк, 7200 сочетаний в переборе) один текст идёт СОРОК ОДНУ секунду — и
# панель обещала ему 22 минуты там, где работы на час.
#
# Формулу выдумывать не стал: двух замеров мало, а придуманная формула врёт с
# тем же лицом, что и константа. Меряем настоящее время и заменяем им оценку
# после ПЕРВОГО же текста. Скользящее среднее, чтобы одна медленная тема не
# перекосила остаток.
_SERIES_SEC: dict = {"n": 0, "avg": 0.0}


def _замер(сек: float) -> None:
    n, avg = _SERIES_SEC["n"], _SERIES_SEC["avg"]
    _SERIES_SEC.update({"n": n + 1, "avg": (avg * n + сек) / (n + 1)})


def _секунд_на_текст() -> float:
    """Замеренное среднее, пока его нет — константа домена."""
    return _SERIES_SEC["avg"] if _SERIES_SEC["n"] else series_mod.SECONDS_PER_TEXT


def _series_worker(name: str) -> None:
    def шаг(done, total, detail, link=None):
        _SERIES_PROGRESS.update({"done": done, "total": total, "detail": detail,
                                 "link": link})

    def один(spec, corpus, nl_fragments, progress=None):
        # Замок на ОДИН текст. Ждём его, а не отказываемся: серия идёт ночью,
        # и бросить весь план из-за одной ручной генерации было бы глупо.
        #
        # ПРОГРЕСС ВНУТРИ ТЕКСТА (Раунд 55). Здесь стояло `run_pipeline(...)`
        # БЕЗ progress — отсюда и «прогресс серии завис»: один текст на длинной
        # цепочке идёт
        # сорок-сто секунд, и всё это время строка в шапке не менялась вовсе.
        # Теперь видно, на каком пуле стоим: «дорога 1 из 10 · пулы 2/3».
        хвост = _SERIES_PROGRESS.get("detail") or ""
        def внутри(done, total, detail):
            _SERIES_PROGRESS["detail"] = f"{хвост} · {detail}"
        with _PIPELINE_LOCK:
            t0 = time.time()
            res = pipeline.run_pipeline(spec, corpus, nl_fragments,
                                        progress=внутри, стоп=_SERIES_STOP.is_set)
            _замер(time.time() - t0)
            return res

    try:
        итог = series_run.прогнать(
            name, CORPUS, _nl().get_active_pool() if _nl() else [],
            стоп=_SERIES_STOP.is_set, шаг=шаг, прогон=один)
        CORPUS.save()
        хвост = f"сделано {итог['texts']}"
        if итог["skipped"]:
            хвост += f" · было {итог['skipped']}"
        if итог["errors"]:
            хвост += " · " + "; ".join(итог["errors"][:3])
        _SERIES_PROGRESS.update({
            "state": "error" if итог["errors"] and not итог["texts"] else "done",
            "detail": хвост, "link": None,
            # причина под своим треком (Раунд 55): ключи — номера треков, и
            # меню ставит её под свою строку, а не разбирает общий хвост
            "beda": {str(k): v for k, v in (итог.get("beda") or {}).items()}})
    except Exception as e:                                   # noqa: BLE001
        _SERIES_PROGRESS.update({"state": "error", "detail": str(e), "link": None})


@app.get("/api/series/state")
def api_series_state():
    """Настоящее положение дел по серии: сколько СДЕЛАНО на каждом треке,
    какой идёт сейчас и где что встало.

    Читается из файлов (core/series_run.состояние), поэтому не требует помнить
    ни одного прогона: закрыл окно, вернулся через сутки — цифры те же. До
    Раунда 55 меню не знало об этом ничего и показывало полный план даже
    тогда, когда двадцать восемь текстов из тридцати уже лежали в папках."""
    name = (request.args.get("name") or "").strip()
    entry = series_mod.by_name(name)
    if entry is None:
        return {"error": f"серия «{name}» не найдена"}, 404
    сост = series_run.состояние(entry)
    идёт = _SERIES_THREAD is not None and _SERIES_THREAD.is_alive()
    свой = _SERIES_PROGRESS.get("name") == name
    return {**сост,
            "link": _SERIES_PROGRESS.get("link") if (идёт and свой) else None,
            "beda": _SERIES_PROGRESS.get("beda") if свой else {},
            # ЗАМЕРЕННОЕ время, если оно уже есть: константа врала втрое на
            # тяжёлой цепочке (см. _замер)
            "seconds_per_text": round(_секунд_на_текст(), 1),
            "measured": _SERIES_SEC["n"] > 0}


@app.post("/api/series/run")
def api_series_run():
    global _SERIES_THREAD
    if _SERIES_THREAD is not None and _SERIES_THREAD.is_alive():
        return {"error": "серия уже идёт — останови её или дождись"}, 409
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    entry = series_mod.by_name(name)
    if entry is None:
        return {"error": f"серия «{name}» не найдена"}, 404
    # ОЦЕНКА ОСТАТКА, а не плана (Раунд 55): второй запуск той же серии
    # обещал восемь минут там, где работы на полминуты.
    сост = series_run.состояние(entry)
    осталось = max(0, сост["texts"] - сост["done_total"])
    оценка = {"texts": осталось, "seconds": int(осталось * _секунд_на_текст())}
    _SERIES_STOP.clear()
    _SERIES_PROGRESS.update({"state": "running", "done": сост["done_total"],
                             "name": name, "total": сост["texts"],
                             "detail": "начинаю…", "link": None, "beda": {}})
    _SERIES_THREAD = threading.Thread(target=_series_worker, args=(name,),
                                      name="series", daemon=True)
    _SERIES_THREAD.start()
    return {"ok": True, "estimate": оценка}


@app.post("/api/series/stop")
def api_series_stop():
    """Останов спрашивается МЕЖДУ текстами: бросать посреди — нечего, один
    текст это пятнадцать секунд."""
    _SERIES_STOP.set()
    return {"ok": True}


# ============================================================
# nakedlunch tab — a second, independent mode. All of it reads/writes
# ~/Documents/nakedlunch (nakedlunch's own data), via core/nlbridge.py.
# nakedlunch.py itself (the CLI, the Ghostty CRT launcher) is never touched
# and keeps working exactly as before.
# ============================================================

def _forget_pool_mask() -> None:
    """Сбросить кэш маски активного пула колоночного индекса (core/nlindex.py).
    Маска кэшируется по (длина, первый, последний) — изменение состава
    источников почти всегда сдвигает длину, но полагаться на «почти» там, где
    можно сказать явно, незачем.

    Заодно забываем множество текстов хранилища: его кэш ключуется числом
    фрагментов, а источник могли и переключить (число то же, состав другой)."""
    global _NL_TEXTS_CACHE
    _NL_TEXTS_CACHE = None
    nlindex.forget_pool()


def _nl_guard():
    if _nl() is None:
        return {"error": "nakedlunch не найден на этой машине"}, 503
    return None


@app.get("/api/nl/state")
def api_nl_state():
    err = _nl_guard()
    if err:
        return err
    # Two different numbers were collapsing into one misleading "pool_size"
    # (found 2026-07-14, user spotted it not adding up): get_chat_pool() is
    # the ACTIVE-corpus total MINUS nakedlunch's own "used" tracking (lines
    # already shown in ITS chat history, e.g. via the standalone CLI at
    # ~/nakedlunch — a persistent, shared state file, not anything extendo
    # itself marks) — silently subtracting that under a label that only says
    # "активные источники" hid where a big chunk of the number went. Now both
    # ride along, decomposed and named, so the UI can say what it means
    # instead of showing one number nobody can reconstruct.
    return {
        "available": True,
        "sources": _nl().list_corpora(),
        "pool_total": len(_nl().get_active_pool()),
        # «Доступно» — по НАШЕЙ истории, единственному учёту показанного
        "pool_available": len(set(_nl().get_active_pool()) - CORPUS.hidden_set()),
        "retention": nlbridge.get_config().get("session_retention", "never"),
    }


# Роут /api/nl/generate ВЫРЕЗАН (Раунд 51). Остаток вкладки «нейкедланч» из
# ранней версии: свой путь генерации со своими ползунками banal/novelty, мимо
# core/filters. Фронт не звал его ни разу — сверено по всему interface/. При
# этом он был единственным, кто писал в журнал сессии, из-за чего журнал
# заводился на каждый запуск и оставался пустым (см. nlbridge.SessionLog).

@app.post("/api/nl/source/add")
def api_nl_source_add():
    err = _nl_guard()
    if err:
        return err
    files = request.files.getlist("files")
    if not files:
        return {"error": "нет файлов"}, 400
    if not _IMPORT_LOCK.acquire(blocking=False):
        return {"error": "заливка уже идёт"}, 409
    try:
        if _IMPORT["state"] == "running":
            return {"error": "заливка уже идёт"}, 409
        # Байты читаем ЗДЕСЬ: поток запроса закроется раньше, чем работник
        # доберётся до файла, и `f.read()` в фоне вернул бы пустоту.
        payload = [(f.filename, f.read()) for f in files]
        _IMPORT.update({"state": "running", "files": [n for n, _ in payload],
                        "i": 0, "n": len(payload), "detail": "начинаю",
                        "added": [], "errors": []})
    finally:
        _IMPORT_LOCK.release()
    threading.Thread(target=_import_worker, args=(payload,),
                     name="nl-import", daemon=True).start()
    # Ответ СРАЗУ: список пока прежний, а имена в работе фронт показывает сам
    # (см. methods.corpus.addBooks) и следит за ходом через /api/status.
    return {"queued": [n for n, _ in payload], "sources": _nl().list_corpora()}


@app.post("/api/nl/source/toggle")
def api_nl_source_toggle():
    err = _nl_guard()
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    cid = payload.get("id")
    # toggle_active returns the NEW active state, which is False both when the
    # corpus was switched off and when cid doesn't exist — ambiguous on its
    # own, so check existence first rather than trusting the return value.
    if not cid or _nl().get_corpus(cid) is None:
        return {"error": "источник не найден"}, 404
    _nl().toggle_active(cid)
    _forget_pool_mask()
    return {"sources": _nl().list_corpora()}


@app.post("/api/nl/source/remove")
def api_nl_source_remove():
    err = _nl_guard()
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    cid = payload.get("id")
    if not cid or not _nl().delete_corpus(cid):
        return {"error": "источник не найден"}, 404
    _forget_pool_mask()
    return {"sources": _nl().list_corpora()}


@app.post("/api/nl/clear-used")
def api_nl_clear_used():
    err = _nl_guard()
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    mode = (payload.get("mode") or "").strip().lower()
    try:
        cleared = nlbridge.clear_used_for_period(_nl(), mode)
    except ValueError:
        return {"error": "период: all|hour|day|week|month"}, 400
    return {"cleared": cleared}


@app.post("/api/nl/open-dir")
def api_nl_open_dir():
    err = _nl_guard()
    if err:
        return err
    import subprocess
    subprocess.run(["open", str(nlbridge.NAKEDLUNCH_PROG_DIR)], check=False)
    return {"ok": True}


@app.get("/api/nl/retention")
def api_nl_retention_get():
    err = _nl_guard()
    if err:
        return err
    return {"value": nlbridge.get_config().get("session_retention", "never")}


@app.post("/api/nl/retention")
def api_nl_retention_set():
    err = _nl_guard()
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    try:
        cfg = nlbridge.set_retention((payload.get("value") or "").strip().lower())
    except ValueError:
        return {"error": "never|month|3m|6m|year"}, 400
    return {"value": cfg["session_retention"]}


# ============================================================
# Листы — хранилище .md в ~/Documents/nakedlunch/тексты (PLAN.md, решение
# прожарки №6: «листы = настоящие .md в настоящих папках»). Вся логика в
# core/sheets.py; здесь только тонкие роуты + перевод доменной ошибки в
# честный 400 по-русски. Роуты стоят ДО catch-all раздачи интерфейса.
# ============================================================

def _sheets_call(fn, *args):
    try:
        return fn(*args)
    except sheets.SheetError as e:
        return {"error": str(e)}, 400


@app.get("/api/sheets")
def api_sheets_list():
    return _sheets_call(sheets.overview)


@app.post("/api/sheets/read")
def api_sheets_read():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.read, p.get("id"))


@app.post("/api/sheets/write")
def api_sheets_write():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.write, p.get("id"), p.get("rows"))


@app.post("/api/sheets/create")
def api_sheets_create():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.create, p.get("title"), p.get("folder"))


@app.post("/api/sheets/rename")
def api_sheets_rename():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.rename, p.get("id"), p.get("title"))


@app.post("/api/sheets/duplicate")
def api_sheets_duplicate():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.duplicate, p.get("id"))


@app.post("/api/sheets/trash")
def api_sheets_trash():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.trash, p.get("id"))


@app.post("/api/sheets/restore")
def api_sheets_restore():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.restore, p.get("id"))


@app.post("/api/sheets/purge")
def api_sheets_purge():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.purge, p.get("id"))


@app.post("/api/sheets/purge-all")
def api_sheets_purge_all():
    return _sheets_call(sheets.purge_all)


@app.post("/api/sheets/move")
def api_sheets_move():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.move, p.get("id"), p.get("folder"))


@app.post("/api/sheets/folder/create")
def api_sheets_folder_create():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.folder_create, p.get("name"))


@app.post("/api/sheets/folder/delete")
def api_sheets_folder_delete():
    p = request.get_json(force=True, silent=True) or {}
    return _sheets_call(sheets.folder_delete, p.get("id"))


@app.post("/api/sheets/open-dir")
def api_sheets_open_dir():
    # по образцу /api/nl/open-dir — открыть хранилище листов в Finder
    import subprocess
    subprocess.run(["open", str(sheets.vault_dir())], check=False)
    return {"ok": True}


@app.post("/api/ui/log")
def api_ui_log():
    """Строка из ОКНА — в общий журнал (Раунд 59).

    Раньше окно писало в свой файл `data/интерфейс.log`, сервер — в свой, сборки
    — в третий. Сопоставить их мог только тот, кто знает, где что лежит. Теперь
    источник помечается полем, а журнал один: человек копирует одно и целиком."""
    payload = request.get_json(force=True, silent=True) or {}
    строка = str(payload.get("text") or "")[:4000]
    if not строка:
        return {"ok": False}
    журнал.запись(str(payload.get("откуда") or "окно")[:12], строка,
                  str(payload.get("уровень") or "инфо"))
    return {"ok": True}


@app.get("/api/журнал")
def api_журнал():
    """ОТЧЁТ ОДНИМ ТЕКСТОМ — то, что человек копирует одной кнопкой.

    Сюда же собирается состояние приложения: без него половина обращений
    объясняется не ошибкой, а тем, что артефакт не собран, — и понять это по
    одному стеку нельзя."""
    return {"текст": журнал.отчёт(_добавка_к_отчёту()), "записи": журнал.записи(300),
            "аварийно": журнал.не_закрыто(),
            "ошибок": sum(1 for з in журнал.записи(3000) if з["уровень"] == "ошибка")}


def _добавка_к_отчёту() -> dict:
    """Состояние приложения для отчёта. Без него половина обращений объясняется
    не ошибкой, а несобранным артефактом — а по одному стеку этого не видно."""
    добавка = {}
    try:
        idx = nlindex.load()
        добавка["индекс корпуса"] = ("испечён " + idx.built_at) if idx else "не испечён"
        добавка["правила индекса"] = idx.rules if idx else "—"
        добавка["фрагментов в индексе"] = f"{idx.n:,}".replace(",", " ") if idx else "0"
        добавка["прогрев"] = "готов" if _ПРОГРЕВ["готов"] else _ПРОГРЕВ.get("этап", "идёт")
        добавка["этапы прогрева"] = ", ".join(f"{и}={с}с" for и, с in _ПРОГРЕВ.get("этапы", []))
    except Exception as e:                                       # noqa: BLE001
        добавка["состояние"] = f"не удалось прочитать: {e}"
    try:
        добавка["источников включено"] = str(len(_nl().list_corpora())) if _nl() else "нет корпуса"
    except Exception:
        pass
    return добавка


@app.post("/api/журнал/файл")
def api_журнал_файл():
    """СОХРАНИТЬ ОТЧЁТ НА РАБОЧИЙ СТОЛ И ПОКАЗАТЬ ЕГО (Раунд 59).

    Тестеру нельзя давать задачу «найди папку, собери файлы, приложи»: он её не
    выполнит, и правильно сделает. Задача должна быть одна — нажать кнопку и
    перетащить появившийся файл в переписку. Поэтому файл ложится на рабочий
    стол под понятным именем, и проводник открывается сам.

    В файл идут ВСЕ сессии, а не текущая: странность замечают через день, и
    журнал того запуска нужнее сегодняшнего."""
    try:
        путь = журнал.сохранить_отчёт(_добавка_к_отчёту(), всё=True)
        журнал.показать_в_проводнике(путь)
        return {"ok": True, "путь": str(путь), "имя": путь.name,
                "размер": путь.stat().st_size}
    except Exception as e:                                       # noqa: BLE001
        журнал.ошибка("сервер", "не удалось сохранить отчёт", e)
        return {"ok": False, "error": str(e)}, 500


@app.post("/api/rec/open-dir")
def api_rec_open_dir():
    """Открыть каталог записей в Finder (Раунд 56).

    Папка была всегда — ~/Documents/nakedlunch/записи/<дата время>/, и путь
    даже писался под каждой дорожкой в панели. Но путь строкой панель не
    заменяет: нужна дверь, а не адрес. Третий такой роут в проекте — тот же
    образец, что у корпуса и у листов.

    Без параметра открывается КОРЕНЬ: искать последнюю запись глазами по дате
    честнее, чем помнить, какая сессия была последней."""
    import subprocess
    d = recorder.DEFAULT_ROOT
    d.mkdir(parents=True, exist_ok=True)   # ещё не писал ни разу — не отказ, а пустая папка
    subprocess.run(["open", str(d)], check=False)
    return {"ok": True, "dir": str(d)}


# ============================================================
# Попап по слову (ФАЗА 2, решение прожарки №9) — POST /api/word/suggest.
# Логика в core/wordsuggest.py; здесь только валидация и перевод настроек.
# Роут стоит ДО catch-all раздачи интерфейса (см. границу с бэкендом в
# PLAN.md: каждый /api/* регистрируется явно).
# ============================================================

_SUGGEST_TABS = ("рифмы", "по звуку", "синонимы", "антонимы", "строкой")


@app.post("/api/word/suggest")
def api_word_suggest():
    p = request.get_json(force=True, silent=True) or {}
    word = p.get("word")
    tab = p.get("tab")
    line = p.get("line", "")
    if not isinstance(word, str) or not word.strip():
        return {"error": "нужно слово (word)"}, 400
    if tab not in _SUGGEST_TABS:
        return {"error": "вкладка (tab) — одна из: " + ", ".join(_SUGGEST_TABS)}, 400
    if not isinstance(line, str):
        return {"error": "line — строка (текст текущей строки, можно пустую)"}, 400
    # «Без мата» — из ТОГО ЖЕ места, откуда его берёт генерация (Раунд 51).
    # Раньше читался ключ settings['knobs'] — замороженный склад, в который
    # интерфейс перестал писать: живые положения панели с Раунда 50 живут в
    # nl_params. То есть попап годами подсказывал по настройке, которую нельзя
    # было изменить, и она молча стояла на значении из старого интерфейса.
    _n = settings_mod.read().get("nl_params") or {}
    no_mat = clean.knobs_from_profile({"name": "панель", "mode": _n.get("mode"),
                                       "params": _n.get("params")}).get("no_mat", False)
    items = wordsuggest.suggest(word, tab, line=line, corpus=CORPUS, no_mat=no_mat)
    return {"items": items}


# ---- serve the built interface -----------------------------------------
@app.get("/healthz")
def healthz():
    return "ok", 200


@app.get("/")
def index():
    return send_from_directory(DIST, "index.html")


@app.get("/assets/<path:sub>")
def assets(sub):
    return send_from_directory(DIST / "assets", sub)


@app.get("/<path:root_file>")
def dist_root_file(root_file):
    return send_from_directory(DIST, root_file)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
