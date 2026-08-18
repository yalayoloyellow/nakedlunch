# nakedlunch — мост к корпусу нарезанных фрагментов. Даёт крутилке «подмешать
# из nakedlunch» тянуть живые куски реального текста в выдачу, когда своего
# материала грамматическому генератору на тему не хватает.
#
# Код резки и хранилища (nlsrc/{store,cutter,generator}.py) внесён ВНУТРЬ
# приложения 2026-08-01: раньше он читался по пути из ~/nakedlunch, и каталог
# CLI был скрытой рантайм-зависимостью — переименуй его, и корпус пропадал бы
# вместе с ним. Теперь приложение самодостаточно.
#
# ДАННЫЕ при этом остались на месте: ~/Documents/nakedlunch/data (526 МБ,
# ~1.96 млн активных фрагментов). Один и тот же корпус читают и приложение,
# и старый CLI, если он кому-то ещё нужен, — файлы общие, схема та же.
#
# По прямому решению пользователя: подмешивание берёт из ВСЕХ активных корпусов,
# а не только из своих (см. project-notes/DECISIONS.md).

from __future__ import annotations

import json
import re
import sys
import os
import threading
import time
from functools import lru_cache
from pathlib import Path

import пути

# Каталог CLI больше НЕ нужен для работы: его код внесён в core/nlsrc
# (2026-08-01). Данные корпуса лежали и лежат отдельно — см. ниже.
NAKEDLUNCH_PROG_DIR = Path.home() / "Documents" / "nakedlunch"
# Переопределяется переменной среды — тем же приёмом, что NAKEDLUNCH_RECORDINGS
# у записей (Раунд 56). Третьим таким был NAKEDLUNCH_VAULT у листов, но листы
# вырезаны 2026-08-18 вместе с редактором. Нужно ровно затем, чтобы
# проверять заливку книг на ВРЕМЕННОМ корпусе, а не на настоящем: боевой
# state.json весит 549 МБ и содержит книги пользователя.
# Через `пути.хранилище` (Раунд 61): своя переменная → NAKEDLUNCH_HOME → умолчание.
# Раньше NAKEDLUNCH_HOME корпус не покрывал вовсе, и «изоляция проверки» одной
# переменной была обещанием, которого никто не выполнял.
NAKEDLUNCH_DATA = пути.хранилище("NAKEDLUNCH_DATA", "корпус",
                                 NAKEDLUNCH_PROG_DIR / "data")
NAKEDLUNCH_CONFIG = NAKEDLUNCH_PROG_DIR / "config.json"

# Same schema nakedlunch.py itself reads/writes — sharing the one file keeps
# the CLI and this web tab in sync, without importing nakedlunch.py itself
# (its module-level Console()/logging setup isn't needed for a headless server,
# and re-implementing these few lines here avoids any risk of a same-named
# installed `nakedlunch` pip package shadowing the local repo on sys.path).
_RETENTION_DAYS = {"never": 0, "month": 30, "3m": 90, "6m": 180, "year": 365}

_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+")


def _tokens(s: str) -> set[str]:
    return set(_TOKEN_RE.findall(s.lower()))


@lru_cache(maxsize=1)
def _nl_modules():
    """Хранилище корпуса. Раньше читалось по пути из ~/nakedlunch — теперь
    лежит внутри приложения (core/nlsrc, внесено 2026-08-01): каталог CLI был
    скрытой рантайм-зависимостью, и его переименование убивало корпус, хотя
    данные лежат совсем в другом месте. Никогда не None: код свой.

    Отдаёт ОДИН класс, а не пару (2026-08-14). Вторым элементом ехал
    `_weighted_sample`, и брал его единственный вызывающий — `generate_filtered`,
    вырезанный тем же днём (см. ниже). Пара из одного значащего элемента
    заставляла каждого зовущего писать `X, _ = _nl_modules()` — форму, по
    которой не видно, что второго уже нет."""
    from nlsrc.store import NakedLunchStore  # noqa: E402

    return NakedLunchStore


# ХРАНИЛИЩЕ ГРУЗИТСЯ ФОНОМ (Раунд 54). state.json пользователя — 550 МБ, и его
# разбор стоит 13-16 с. Раньше эта цена платилась на уровне модуля api/server.py,
# то есть ДО того, как Flask открывал порт: окно ждало здоровья сервера 39.4 с
# при потолке ожидания 40 с — и однажды не дождалось («сервер не поднялся за
# отведённое время»).
#
# Приём тот же, что у карт индекса: тяжёлая подготовка уходит в поток (с
# Раунда 57 это общий `_прогрев` в api/server.py, корпус в нём первый этап),
# порт открывается сразу, а первый запрос, которому корпус реально нужен, ждёт
# на замке. Статус в шапке при этом честно говорит «загружается» —
# он спрашивает `store_if_ready`, который НЕ ждёт: опрос статуса, повисший на
# 16 секунд, превратил бы индикатор фоновой работы в индикатор её отсутствия.
_STORE = None
_STORE_LOCK = threading.Lock()


def open_store():
    """ОДИН экземпляр NakedLunchStore на процесс.

    Первый вызов разбирает 550 МБ и стоит 13-16 с; остальные отдают готовое.
    Замок именно здесь, а не у зовущего: со старта хранилище греет фоновый
    поток, и запрос, пришедший раньше времени, обязан ЖДАТЬ его, а не начать
    разбирать те же 550 МБ вторым экземпляром."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = _nl_modules()(NAKEDLUNCH_DATA)
        return _STORE


def store_if_ready():
    """Хранилище, если оно УЖЕ загружено, иначе None — без ожидания.

    Для тех, кому нельзя ждать: опрос статуса раз в 12 с и любой роут, чей
    ответ — «идёт работа», а не сама работа."""
    return _STORE


# `warm_background` ВЫРЕЗАН (2026-08-14). Свой поток на корпус завёл Раунд 54
# (порт открывался раньше разбора 550 МБ), а Раунд 57 собрал прогрев в ОДИН
# упорядоченный поток — `_прогрев` в api/server.py, где корпус идёт первым
# этапом, а карты индекса вторым: параллельно они дрались за процессор и
# растягивали друг друга втрое. С тех пор эту функцию не звал никто, и второй
# способ греть корпус был приглашением снова развести два потока.
# Неблокирующий старт и честный `store_if_ready` сторожит tests/test_boot.py.


# ---------------------------------------------------------------------------
# config (session retention) — shared file, own tiny read/write
# ---------------------------------------------------------------------------

def get_config() -> dict:
    if NAKEDLUNCH_CONFIG.exists():
        try:
            cfg = json.loads(NAKEDLUNCH_CONFIG.read_text("utf-8"))
            cfg.setdefault("session_retention", "never")
            return cfg
        except Exception:
            pass
    return {"session_retention": "never", "language": "en"}


def set_retention(value: str) -> dict:
    if value not in _RETENTION_DAYS:
        raise ValueError("bad retention value")
    cfg = get_config()
    cfg["session_retention"] = value
    NAKEDLUNCH_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    NAKEDLUNCH_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")
    return cfg


# SessionLog ВЫРЕЗАН (Раунд 54). Раунд 51 снял его единственного писателя
# (роут /api/nl/generate) и оставил сам класс «на всякий случай»; писать в него
# с тех пор было некому, а экземпляр всё равно заводился на каждый запуск.
# Теперь нет ни того, ни другого. Файлы сессий, что уже лежат в
# ~/Documents/nakedlunch/sessions, не трогаем: они писаны CLI, это его данные.


def clear_used_for_period(store, mode: str) -> int:
    """Same period mapping as nakedlunch.py's /c command."""
    if mode == "all":
        return store.clear_used(None)
    seconds = {"hour": 3600, "day": 86400, "week": 7 * 86400, "month": 30 * 86400}.get(mode)
    if seconds is None:
        raise ValueError("bad period")
    return store.clear_used(time.time() - seconds)


# ФИЛЬТРОВАННАЯ ГЕНЕРАЦИЯ ВЫРЕЗАНА (2026-08-14). `generate_filtered` вместе с
# её быстрым замером банальности `_pool_banality` (zipf по словоформам, чтобы
# просеять весь активный пул за 0.75 с вместо 15 с с лемматизацией) была
# «фильтрующей» половиной двухрежимного расклада и умерла вместе с ним: пул
# фрагментов давно просеивают крутилки в core/filters.py, по своим замерам и
# своей банальности. Вызывающих не осталось ни одного — ни в роутах, ни в
# тестах. Токенизатор `_tokens` при этом ЖИВОЙ и остаётся выше: на него стоят
# core/filters.py и tools/build_nl_rhyme.py — им нужен ровно этот разбор на
# слова, чтобы сравнивать с корпусом на одном основании.


# ---------------------------------------------------------------------------
# add a source from uploaded bytes (web equivalent of the CLI's /a picker)
# ---------------------------------------------------------------------------

def add_source_from_bytes(store, filename: str, data: bytes, save: bool = True, шаг=None):
    """Write to a temp file and reuse nakedlunch's own parse_source_file (same
    .fb2/.txt/.md handling, same cleaning) — mirrors do_add() in nakedlunch.py
    without touching it. Raises ValueError('unsupported_format') same as the CLI."""
    import tempfile

    suffix = Path(filename).suffix.lower()
    if suffix not in (".fb2", ".txt", ".md"):
        raise ValueError("unsupported_format")
    from nlsrc.cutter import parse_source_file  # noqa: E402

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        tf.write(data)
        tmp_path = tf.name
    try:
        if шаг:
            шаг("читаю файл")
        text = parse_source_file(tmp_path)
        if not text or not text.strip():
            raise ValueError("empty_source")
        name = Path(filename).stem
        # save/шаг прокидываются насквозь: заливка идёт фоном и обязана
        # отчитываться, а полная запись корпуса делается ОДНА на всю пачку
        # (см. api/server.py: _import_worker).
        return store.add_corpus(name, text, save=save, шаг=шаг)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
