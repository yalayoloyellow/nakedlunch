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
# По прямому решению владельца: подмешивание берёт из ВСЕХ активных корпусов,
# а не только из своих (см. project-notes/DECISIONS.md).

from __future__ import annotations

import json
import random
import re
import sys
import os
import threading
import time
from functools import lru_cache
from pathlib import Path

# Каталог CLI больше НЕ нужен для работы: его код внесён в core/nlsrc
# (2026-08-01). Данные корпуса лежали и лежат отдельно — см. ниже.
NAKEDLUNCH_PROG_DIR = Path.home() / "Documents" / "nakedlunch"
# Переопределяется переменной среды — тем же приёмом, что NAKEDLUNCH_VAULT у
# листов и NAKEDLUNCH_RECORDINGS у записей (Раунд 56). Нужно ровно затем, чтобы
# проверять заливку книг на ВРЕМЕННОМ корпусе, а не на настоящем: боевой
# state.json весит 549 МБ и содержит книги владельца.
NAKEDLUNCH_DATA = Path(os.environ["NAKEDLUNCH_DATA"]) if os.environ.get("NAKEDLUNCH_DATA") \
    else NAKEDLUNCH_PROG_DIR / "data"
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
    """Резка и хранилище корпуса. Раньше читались по пути из ~/nakedlunch —
    теперь лежат внутри приложения (core/nlsrc, внесены 2026-08-01): каталог
    CLI был скрытой рантайм-зависимостью, и его переименование убивало корпус,
    хотя данные лежат совсем в другом месте. Никогда не None: код свой."""
    from nlsrc.generator import _weighted_sample  # noqa: E402
    from nlsrc.store import NakedLunchStore  # noqa: E402

    return NakedLunchStore, _weighted_sample


# ХРАНИЛИЩЕ ГРУЗИТСЯ ФОНОМ (Раунд 54). state.json владельца — 550 МБ, и его
# разбор стоит 13-16 с. Раньше эта цена платилась на уровне модуля api/server.py,
# то есть ДО того, как Flask открывал порт: окно ждало здоровья сервера 39.4 с
# при потолке ожидания 40 с — и однажды не дождалось («сервер не поднялся за
# отведённое время»).
#
# Тот же приём, что у nlindex.warm_background: тяжёлая подготовка уходит в
# поток, порт открывается сразу, а первый запрос, которому корпус реально
# нужен, ждёт на замке. Статус в шапке при этом честно говорит «загружается» —
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
            NakedLunchStore, _ = _nl_modules()
            _STORE = NakedLunchStore(NAKEDLUNCH_DATA)
        return _STORE


def store_if_ready():
    """Хранилище, если оно УЖЕ загружено, иначе None — без ожидания.

    Для тех, кому нельзя ждать: опрос статуса раз в 12 с и любой роут, чей
    ответ — «идёт работа», а не сама работа."""
    return _STORE


def warm_background() -> None:
    """Начать загрузку корпуса фоном (зовётся со старта сервера)."""
    def работа():
        try:
            open_store()
        except Exception as e:                                   # noqa: BLE001
            # Молчать нельзя: без корпуса не работает ни генерация, ни статус,
            # и владелец должен увидеть причину в логе, а не пустую выдачу.
            print(f"nakedlunch: корпус не загрузился ({e})", flush=True)
    threading.Thread(target=работа, name="nl-store-warm", daemon=True).start()


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


# ---------------------------------------------------------------------------
# filtered generation (extendo-style banality + λ-novelty on top of
# nakedlunch's own neutral/biased sampling) — the "фильтрация" half of the
# two-mode split. Applied BEFORE nakedlunch's own sampling, on the pool it
# would draw from, not after: filtering 4 already-chosen lines can't back-fill
# ones that got rejected, filtering the pool first can.
# ---------------------------------------------------------------------------

_STOPWORDS = {"и", "в", "на", "не", "с", "что", "как", "но", "а", "о", "к", "у",
              "же", "за", "из", "то", "это", "я", "он", "она", "они", "мы", "вы"}


def _pool_banality(text: str) -> float:
    """Fast banality proxy for filtering the FULL active pool (100k+ fragments):
    zipf on raw word TOKENS directly, no pymorphy3 lemmatization. Measured
    ~0.75s over a 147k-fragment pool this way vs ~15s lemmatizing every one
    (`filters._nl_scored`'s own lemma-based banality check, which is fine at
    the few-thousand-fragment scale nl_mix scores per request, but unusable
    over the whole pool). wordfreq scores inflected surface forms directly
    (e.g. 'городом' 4.35 vs lemma 'город' 5.35) — a bit lower than the lemma
    score but just as informative for a relative ceiling. A fragment with no
    real content tokens is treated as maximally banal (excluded by any real
    ceiling) rather than as maximally fresh."""
    from wordfreq import zipf_frequency
    toks = [t for t in _tokens(text) if t not in _STOPWORDS and len(t) > 2]
    if not toks:
        return 9.0
    return min(zipf_frequency(t, "ru") for t in toks)


def generate_filtered(store, bias: str, banal_ceiling: float | None,
                      novelty_gate: float | None, recent_tokensets: list, rng=None):
    """nakedlunch's own generate(), but drawn from a pool pre-filtered by
    banality and/or novelty (word-TOKEN Jaccard vs recently shown lines — not
    lemma-based: recent_tokensets should be built via _tokens, not
    corpus.lemmatize, so both sides compare on the same basis) when those
    sliders are on. Both None (both sliders at 0) => nakedlunch's own
    generate(), completely unfiltered."""
    if banal_ceiling is None and novelty_gate is None:
        return store.generate(bias, for_chat=True)

    pool = store.get_chat_pool()
    if banal_ceiling is not None:
        pool = [f for f in pool if _pool_banality(f) <= banal_ceiling]
    if novelty_gate is not None and recent_tokensets:
        kept = []
        for f in pool:
            fl = _tokens(f)
            sim = max((len(fl & r) / len(fl | r) if (fl or r) else 0.0 for r in recent_tokensets), default=0.0)
            if sim <= novelty_gate:
                kept.append(f)
        pool = kept

    if not pool:
        return store.generate(bias, for_chat=True)   # nothing survived — fall back rather than show nothing

    _, weighted_sample = _nl_modules()
    if rng is None:
        rng = random.Random()
    bias = (bias or "").strip()
    if not bias:
        if len(pool) <= 4:
            lines = (pool * ((4 // max(1, len(pool))) + 1))[:4]
            rng.shuffle(lines)
            return lines
        return rng.sample(pool, 4)

    bt = _tokens(bias)
    scored = [(f, len(bt & _tokens(f))) for f in pool]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[: min(100, len(scored))]
    items = [f for f, _s in top]
    scores = [float(s) for _f, s in top]
    wild = rng.choice(pool)
    sem3 = weighted_sample(items, scores, min(3, len(items)), rng)
    four = list(sem3) + [wild]
    seen = set(four)
    while len(four) < 4 and pool:
        extra = rng.choice(pool)
        if extra not in seen:
            four.append(extra); seen.add(extra)
    rng.shuffle(four)
    return four[:4]


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
