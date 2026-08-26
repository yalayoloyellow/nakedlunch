#!/usr/bin/env python3
# extendo — precompute rhyme keys for nakedlunch fragments (OFFLINE, one-time;
# ~0.16ms/fragment measured 2026-07-14 — see below — so ≈8 min of compute for
# the 2 868 100-fragment pool of 2026-08-01). Mirrors build_forms.py's pattern:
# run the accentuator ONCE at build time, write a plain dict-lookup cache, so
# the runtime generate path never touches ruaccent.
#
# WHY this exists at all: the user explicitly rejected exempting nakedlunch
# fragments from rhyme (2026-07-13) — "база нейкедланча одинаково подвержена
# фильтрам всем должна быть". But a rhyme key needs to know which syllable is
# STRESSED, and that's only known for the generator's OWN lexicon (baked into
# core/data/forms.json at generation time) — arbitrary nakedlunch prose has no
# such data. ruaccent is the same Apache-2.0/CPU/onnxruntime tool already used
# for that lexicon (NOT the heavy CC-BY-NC-SA accentuator excluded in Round 1)
# — reusing it here for nakedlunch text, once, offline, is the same trade-off
# already accepted, not a new one.
#
# WHY per-word, not ruaccent's own process_all(): the first version ran the
# full sentence pipeline (stress-usage prediction, yo-homograph model,
# omograph model, per-word accent model) on the WHOLE fragment to get the
# stress of exactly ONE word — the last one. Measured 2026-07-14: ~7.6ms/
# fragment that way. We only need `acc.accents` (the big prebuilt dictionary,
# ~82% hit rate on real nakedlunch text) with `acc.accent_model.put_accent()`
# as a single-word fallback for the rest — measured 0.04ms/fragment for that
# step alone, ~0.16ms/fragment end to end with the pymorphy3 POS scan included
# (~190x faster). Cost: no sentence-context disambiguation for homographs/ё —
# acceptable, since generated lines don't get that treatment either (scan.py
# also just reads a precomputed per-word stress, no sentence context).
#
# Output: core/data/nl_rhyme.json = {fragment_text: {"key", "span", "banal",
# "taut", "lemmas", "tokens"}}. "span" (2026-07-14) is the RAW character range
# of the rhyme tail within fragment_text, for the user's rhyme-highlight UI
# (bold+color the actual substring, not just show the abstract key — see
# scan._rhyme_tail's docstring). "banal"/"taut"/"lemmas"/"tokens" (2026-07-14,
# same round) move banality/tautology/diversify-lemmas/theme-bias-matching OFF
# the request path entirely — filters._nl_scored used to call lemmatize() +
# zipf_frequency() + a tautology scan on every fetched fragment on EVERY
# generate(), which is why the runtime only ever looked at a small sample
# instead of the user's whole active pool ("пусть обрабатывается... полная
# база абсолютно везде"). Precomputing them once here (a benchmark of 200k
# synthetic entries with these fields already computed took ~24ms to filter —
# see DECISIONS.md) makes a full-pool scan on every request cheap instead of
# needing an async job + progress bar. Missing entry (fragment added after the
# last build run) degrades honestly (rhyme="", banal=9.0 i.e. always banal,
# taut=False, empty lemmas/tokens) — rerun this script (or let
# /api/nl/source/add trigger it automatically) after adding a large source.

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import pymorphy3  # noqa: E402
from wordfreq import zipf_frequency  # noqa: E402
import scan  # noqa: E402  (rhyme_key — must match generated lines' key format exactly)
import nlbridge  # noqa: E402  (read-only bridge into ~/nakedlunch, see core/nlbridge.py)
import filters  # noqa: E402  (_text_tautology — single source of truth for that check)
from corpus import lemmatize, lemmatize_pairs, содержательных  # noqa: E402
from _accent import stress_index  # noqa: E402  (shared with build_forms.py)

import пути  # noqa: E402  (где что лежит, см. core/пути.py)

# Испечённое — к пользователю: в собранном приложении папка рядом с кодом
# доступна только на чтение (Раунд 60).
OUT = пути.артефакт("nl_rhyme.json")
STATUS = пути.артефакт("nl_rhyme.status.json")
_PUNCT = ".,!?:;\"'()»«—-…"

# Checkpoint cadence (2026-08-01, DECISIONS.md Раунд 29 — Раунд 28 finding
# (б)): the old trigger was "every 5000 NEW fragments, rewrite the whole
# dict" — O(n²) total serialization, so a --full pass over the 2.87M pool
# would dump the up-to-~1GB JSON ~574 times: hundreds of GB of I/O dwarfing
# the ≈8 min of actual stress compute. Time-based instead: the cache stays
# ONE plain JSON file (same readers, same resume-from-what's-on-disk
# honesty), a crash loses at most CHECKPOINT_SECONDS of recomputable work,
# and the cadence can't degenerate again as the pool grows. The status
# sidecar is ~100 bytes, so it heartbeats every STATUS_SECONDS — must stay
# well under api/server.py's 180s _NL_RHYME_STALE_SECONDS, or the topbar
# would call a healthy run "stalled"; only the DATA file write must be rare.
CHECKPOINT_SECONDS = 300
STATUS_SECONDS = 30

# Real prose ends in far more POS variety than the generator's own templates
# (which only ever produce NOUN/ADJF/VERB) — INFN (infinitive) is common as a
# fragment's last word and would otherwise silently get no rhyme key at all.
_CONTENT_POS = {"NOUN", "ADJF", "VERB", "INFN"}


# САЙДКАР ПИШЕТ ТОЛЬКО ПРОГРАММА, А НЕ ИМПОРТ (2026-08-18).
#
# `reban()`, `build_потоком()` и `jsonl` выглядят как чистые преобразования, но
# каждое писало ГЛОБАЛЬНЫЙ файл состояния `core/data/nl_rhyme.status.json`. И
# это не теория: `tests/test_select_speed.py` зовёт `reban()` напрямую с
# словарём из ОДНОЙ записи, pytest идёт без `NAKEDLUNCH_HOME`, — и в боевом
# каталоге пользователя оставался `{"cached": 1, "state": "running", "mode":
# "reban"}` с номером умершего процесса. Навсегда: строку «done» пишет только
# `main()`, которую тест не зовёт.
#
# Комментарий «Раунд 58» в `api/server.py` описывает ровно этот файл и годами
# лечил его СИМПТОМ, считая оборванным пересчётом. Пересчёта не было — был
# прогон тестов.
#
# Поэтому запись включается явным флагом, и включает его только `main()`.
# Импорт, тест, REPL — не пишут ничего.
_ПИШЕМ_СТАТУС = False


def писать_статус(включить: bool) -> None:
    """Разрешить или запретить запись сайдкара. Зовёт `main()`; тестам нужна,
    чтобы проверить сам формат записи, не пачкая боевой каталог."""
    global _ПИШЕМ_СТАТУС
    _ПИШЕМ_СТАТУС = bool(включить)


def _write_status(cached: int, state: str, mode: str, error: str | None = None) -> None:
    """Sidecar file api/server.py's /api/status reads — separate from OUT so
    polling status doesn't mean re-parsing a 20MB+ cache on every request. No
    `total` here: the server already has NL_STORE in memory and derives that
    live, so it stays correct even if a source was added after this run
    started. `state` is this SCRIPT's own claim (running/done/error); the
    server additionally treats a stale `updated_at` (no heartbeat in a
    while, e.g. the machine slept) as "stalled" — that judgment belongs to
    the reader, not the writer, since only the reader knows what "a while"
    means to it. `mode` ("full"|"incremental") lets the topbar say WHICH kind
    of run is/was in progress — found 2026-07-14: the user's manual "прогнать
    ударения" button looked broken because it silently did the same
    skip-everything-already-cached incremental pass as the auto-trigger, so
    clicking it when the cache was already ~100% complete finished in
    seconds with nothing visibly different from doing nothing at all."""
    # Каталог может не существовать: на новой машине программа ещё ничего не
    # писала. Писатель обязан создать своё место сам — иначе первый же отчёт о
    # прогрессе роняет сборку, и снаружи это выглядит как «ничего не началось».
    if not _ПИШЕМ_СТАТУС:
        return
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({
        "cached": cached, "state": state, "mode": mode,
        "error": error, "updated_at": time.time(),
        # НОМЕР ПРОЦЕССА — чтобы «идёт» можно было ПРОВЕРИТЬ, а не поверить.
        # Одного сердцебиения мало в обе стороны: уснувший ноутбук делает живую
        # сборку «вставшей» (и сервер вправе запустить вторую поверх той же
        # записи), а убитая системой — ещё три минуты выглядит здоровой. Номер
        # процесса отвечает на это прямо; читатель ходит через
        # `server._сборка_идёт`, где номер и сердцебиение судят вместе.
        "pid": os.getpid(),
    }, ensure_ascii=False), encoding="utf-8")


def _write_out(out: dict) -> None:
    """Serialize-then-rename: at current scale one checkpoint is a ~1GB dump
    taking double-digit seconds — a kill or sleep mid-write must leave the
    previous complete file in place, not a torn JSON that every reader
    (filters.warm_caches, this script's own incremental resume) would crash
    on. Path.replace is atomic on the same filesystem."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.parent / (OUT.name + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT)


def _clean(tok: str) -> str:
    return tok.strip(_PUNCT).lower()


_TOKEN_RE = re.compile(r"\S+")


def _highlight_span(text: str, idx: int, surface: str, key: str) -> list[int] | None:
    """Absolute [start, end) range in `text` of the RAW (unreduced) rhyme
    tail — same length as `key` (scan.rhyme_key's reduction/devoicing never
    changes length) — for the user's rhyme-highlight UI: bold+color the
    actual substring driving the match in the rendered line, not just an
    abstract key off to the side (2026-07-14 — the user's own proposed fix
    after spotting a mismatched pair by eye once the real text was on
    screen). `_TOKEN_RE.finditer` mirrors `text.split()`'s whitespace-run
    segmentation exactly, so its match at position `idx` IS `tokens[idx]`,
    just with a known absolute position `text.split()` throws away. None
    if we can't confidently locate `surface` inside it (should be rare —
    `surface` came from cleaning this exact token in the first place)."""
    if not key:
        return None
    matches = list(_TOKEN_RE.finditer(text))
    if idx >= len(matches):
        return None
    m = matches[idx]
    local = text[m.start():m.end()].lower().find(surface)
    if local < 0:
        return None
    word_end = m.start() + local + len(surface)
    return [word_end - len(key), word_end]


def _last_content_index(morph, tokens: list[str]) -> int | None:
    """Index (into `tokens`, whitespace-split) of the last content word, or
    None if the fragment has none — same 'no rhyme data' case as an all-
    function-word generated line (scan._rhyme_tail)."""
    for i in range(len(tokens) - 1, -1, -1):
        w = _clean(tokens[i])
        if not w:
            continue
        parses = morph.parse(w)
        if parses and parses[0].tag.POS in _CONTENT_POS:
            return i
    return None


def _restore_yo(acc, word: str) -> str:
    """Вернуть ё там, где оно ОДНОЗНАЧНО (Раунд 33, 2026-08-02).

    И книги, и wordfreq печатают без ё, а ударная ё — это звук /о/, не /е/.
    Без восстановления «идет» получал ключ «ет» и рифмовался со «свет»
    (на слух — не рифма), а с «поворот» не рифмовался (на слух — рифма).
    Берём только `acc.yo_words` — 85 568 пар вида «идет»→«идёт», где ё
    восстанавливается однозначно; `acc.yo_homographs` (637 пар вроде
    «все/всё», «точен/точён») НЕ трогаем: их различает только контекст
    предложения, а здесь слово одно, и угадывать нечестно."""
    return acc.yo_words.get(word, word)


def _word_rhyme_key(acc, surface: str, word_for_model: str) -> str:
    """Stress just ONE word — dict lookup first (covers the vast majority),
    ruaccent's single-word neural fallback (`accent_model.put_accent`, no
    sentence context needed — verified it tokenizes only the word passed in)
    for anything not in the dictionary. No process_all(), no per-sentence
    models: that's the whole speedup.

    ё восстанавливается ДО подсчёта ключа (см. _restore_yo): ударение ищется
    по написанию без ё (в словаре ударений ключи именно такие), а вот ключ
    обязан считаться уже по ё-форме."""
    if acc.has_punctuation(surface):
        return scan.rhyme_key(_restore_yo(acc, surface), -1)
    if acc.count_vowels(surface) <= 1:
        # A single vowel is trivially the stressed one — no need for
        # ruaccent. Found 2026-07-14: this used to return the raw
        # surface[-3:] unconditionally here, bypassing rhyme_key's own
        # reduction/devoicing — "том" and "дом" (same true -ом rhyme) got
        # DIFFERENT raw keys ("том"/"дом"), so any monosyllabic-ending
        # fragment essentially never matched anything real. rhyme_key(...,0)
        # still degrades to surface[-3:] on its own if count_vowels is 0.
        return scan.rhyme_key(_restore_yo(acc, surface), 0)
    marked = acc.accents.get(surface)
    if marked is None:
        marked = acc.accent_model.put_accent(word_for_model)
    stress_idx = stress_index(marked)
    if stress_idx is None:
        return ""
    # Ударение искали по написанию БЕЗ ё (словарь ударений ключуется так), а
    # ключ считаем по ё-форме: длина и порядок гласных при е→ё не меняются,
    # поэтому индекс ударного гласного остаётся тем же.
    return scan.rhyme_key(_restore_yo(acc, surface), stress_idx)


def _extra_fields(text: str) -> dict:
    """banal/taut/lemmas/tokens — everything filters._nl_scored used to
    compute LIVE on every request (lemmatize + zipf + tautology scan), now
    baked in once so a full-pool scan at request time is just dict lookups.
    `lemmas` doubles as `_diversify`'s near-duplicate set; `tokens` is raw
    whole-word tokens for theme-bias scoring (matches nlbridge._tokens'
    tokenizer, so a "restore by theme"-style overlap check behaves the same
    way here as everywhere else this session)."""
    # ИМЕНА СОБСТВЕННЫЕ НЕ СЧИТАЮТСЯ РЕДКИМИ (Раунд 57) — та же метрика, что в
    # `filters._banality`. Редкость имени это свойство имени, а не находка
    # автора, и без этого любая реплика с именем персонажа получала лучший балл.
    #
    # Пары (слово, лемма), а не отдельно то и другое: первая моя версия
    # сопоставляла ЛЕММЫ со списком выживших ПОВЕРХНОСТНЫХ слов, «надеяться» не
    # совпадало с «надеюсь», под фильтр не проходило почти ничего и срабатывал
    # запасной вариант. Метрика не менялась вовсе — перепечка час считала то же
    # самое.
    пары = lemmatize_pairs(text)
    lemma_list = [l for _, l, _ in пары]
    обычные = [l for _, l, имя in пары if not имя]
    годные = обычные or lemma_list
    banal = min((zipf_frequency(l, "ru") for l in годные), default=9.0)
    # СКОЛЬКО В СТРОКЕ ОБЫЧНЫХ СЛОВ (Раунд 57). Строка вроде «Г-ЖА ДЕ СЕНТ-АНЖ.
    # — Я» проходит ВСЕ существующие фильтры честно: не клише, не тавтология, не
    # мат, слово целое, слоги в норме. Она не стих, а ремарка пьесы — и признак
    # у этого измеримый: знаменательных слов, кроме имён, в ней почти нет.
    # Считаем здесь, потому что разбор на пары уже сделан: цена нулевая.
    taut = filters._text_tautology(lemma_list)
    tokens = list(nlbridge._tokens(text))
    # СЧЁТ СОДЕРЖАТЕЛЬНЫХ — СВОИМ СЧЁТЧИКОМ, А НЕ `len(обычные)` (2026-08-18).
    #
    # `обычные` берутся из `lemmatize_pairs`, а тот считает только шесть частей
    # речи: существительное, прилагательное, глагол, инфинитив, причастие,
    # деепричастие. НАРЕЧИЙ и СРАВНИТЕЛЬНЫХ СТЕПЕНЕЙ там нет — и строка
    # «Дальше — хуже» получала НОЛЬ содержательных слов, то есть выбрасывалась
    # порогом наравне с архивным шифром «РГАЛИ. Ф. 155. Оп».
    #
    # Замер на случайной пробе живого индекса: порогом «не меньше двух» режется
    # 8.62% годных строк, и 39% из них — не мусор, а короткие разговорные
    # строки, не прошедшие только из-за части речи. На корпусе ~79 900 строк:
    # «Нет у меня денег», «ты очень ошибаешься», «как нельзя лучше. Так».
    #
    # Список частей речи расширен ОТДЕЛЬНЫМ списком, а не правкой `_CONTENT_POS`:
    # тот же список задаёт множество ЛЕММ для темы, разнообразия соседей,
    # тавтологии и эха в избранном, и там наречия лишние — «очень», «уже»,
    # «дальше» совпадали бы у всего подряд. Разбор — в `corpus.содержательных`.
    return {"banal": round(banal, 3), "taut": taut, "lemmas": lemma_list,
            "tokens": tokens, "content": содержательных(text)}


def акцентуатор():
    """Акцентуатор, поднятый ЛЕГКО: только то, что проходы правда трогают.

    `RUAccent.load()` поднимает четыре модели, а здесь используются ровно две
    вещи (см. шапку файла): готовый словарь ударений и модель на одно слово для
    тех процентов, которых в словаре нет. Модель омографов при этом не просто
    лишняя — она весит 351 МБ и грузится безусловно, а в собранном приложении
    её пришлось бы тащить внутрь бандла ради кода, который к ней не обращается.

    Разбор омографов нам и не положен: генератор читает предрасчитанные
    ударения без контекста предложения (см. scan.py), и брать здесь более умный
    разбор значило бы рассогласовать два пути, обязанных давать одинаковые
    ключи.

    НЕ ВЫШЕЛ ЛЁГКИЙ ПУТЬ — поднимаем обычным `load()`. Он опирается на
    внутренности чужого пакета, и когда те изменятся, программа должна стать
    медленнее и толще, а не сломаться.
    """
    import gzip
    import pathlib as _pl
    from ruaccent import RUAccent

    acc = RUAccent()
    корень = _pl.Path(__import__("ruaccent").__file__).resolve().parent
    словарь = корень / "dictionary" / "accents.json.gz"
    модель = корень / "nn" / "nn_accent"
    try:
        if not (словарь.exists() and (модель / "model.onnx").exists()):
            raise FileNotFoundError("нет словаря ударений или модели на слово")
        acc.accents = json.load(gzip.open(словарь))
        acc.accents.update(acc.letters_accent)
        acc.accent_model.load(str(модель))
        # Словарь ё: его читает `_restore_yo`. Поймано проверкой ключей — без
        # него лёгкий путь падал на первом же слове, а не выдавал другой ответ,
        # и это ровно та ошибка, которую хочется ловить до сборки, а не после.
        ё = корень / "dictionary" / "yo_words.json.gz"
        acc.yo_words = json.load(gzip.open(ё)) if ё.exists() else {}
        acc.tiny_mode = True
    except Exception as e:                                       # noqa: BLE001
        print(f"акцентуатор: лёгкий путь не вышел ({e}), поднимаю полностью", flush=True)
        acc = RUAccent()
        acc.load(omograph_model_size="turbo2", use_dictionary=True, tiny_mode=False)
        return acc

    # ОТЧЁТ ВНЕ try (Раунд 61). Пока печать стояла внутри, любая её осечка —
    # закрытый поток, кодировка консоли — уводила выполнение в except, то есть в
    # полный `load()`. А он тянет 1.3 ГБ с HuggingFace и пишет ВНУТРЬ пакета
    # ruaccent, который в собранном приложении недоступен на запись: первая же
    # заливка книги на чистой машине падала бы, обвиняя лёгкий путь, который на
    # самом деле отработал.
    #
    # Тот же приём уже применён в tools/скачать_акцентуатор.py — там он появился
    # после Windows-сборки, где отчёт об успешной загрузке ронял процесс и
    # рапортовал о провале. Сюда его тогда не перенесли.
    try:
        print(f"акцентуатор: словарь {len(acc.accents)} словоформ, "
              f"ё-словарь {len(acc.yo_words)}, без омографа", flush=True)
    except Exception:                                            # noqa: BLE001
        pass
    return acc


def build(existing: dict, mode: str = "incremental") -> dict:
    # Say "running" BEFORE the slow model load, not at the first checkpoint:
    # api/server.py's double-spawn guard can only see runs it didn't start
    # itself through this file, and until it says "running" a second
    # /api/nl/source/add could spawn a second ONNX process — the exact thing
    # that guard exists to prevent.
    _write_status(len(existing), "running", mode)

    morph = pymorphy3.MorphAnalyzer()
    acc = акцентуатор()

    store = nlbridge.open_store()
    fragments = store.get_all_fragments()
    print(f"{len(fragments)} fragments total, {len(existing)} already cached")

    out = dict(existing)
    t0 = time.time()
    n_new = n_empty = n_skipped = 0
    n_flushed = 0                  # new entries already checkpointed to disk
    last_status = last_ckpt = t0

    for i, f in enumerate(fragments):
        now = time.time()
        if now - last_status >= STATUS_SECONDS:
            dt = now - t0
            rate = n_new / dt if dt else 0
            print(f"  {i}/{len(fragments)} ({dt:.1f}s, {rate:.0f}/s) — "
                  f"new={n_new} empty={n_empty} skipped={n_skipped}")
            _write_status(len(out), "running", mode)
            last_status = now
        if n_new + n_empty > n_flushed and now - last_ckpt >= CHECKPOINT_SECONDS:
            _write_out(out)
            n_flushed = n_new + n_empty
            # Fresh updated_at AFTER the dump, and the next interval counts
            # from write END: the dump itself takes double-digit seconds at
            # current scale (worse under swap), and that time must neither
            # read as a stall nor eat into the next interval.
            _write_status(len(out), "running", mode)
            last_status = last_ckpt = time.time()

        text = f["text"]
        if text in out:
            n_skipped += 1
            continue

        поля, пусто = _поля_фрагмента(morph, acc, text)
        out[text] = поля
        n_empty += пусто
        n_new += (0 if пусто else 1)

    return out


def _ключ_и_span(morph, acc, text: str) -> tuple[str, list[int] | None, bool]:
    """Ключ рифмы, подсветка и «знаменательного слова не нашлось» для текста.

    ОДНА КОПИЯ НА ЧЕТЫРЕ ПУТИ (2026-08-18). Расчёт жил в двух местах —
    `_поля_фрагмента` (сборка) и `rekey` (перепись ключей). Когда у `--rekey`
    появилась потоковая ветка, копий стало бы три; в этом проекте два списка
    одного и того же расходятся с гарантией, и правило ключа — худшее, чему
    можно дать разойтись: тогда «строкой» и рифмо-бонус перестают попадать
    друг в друга молча."""
    tokens = text.split()
    idx = _last_content_index(morph, tokens) if tokens else None
    if idx is None:
        return "", None, True
    surface = _clean(tokens[idx])
    key = _word_rhyme_key(acc, surface, tokens[idx])
    return key, _highlight_span(text, idx, surface, key), False


def _поля_фрагмента(morph, acc, text: str) -> tuple[dict, bool]:
    """Поля одного фрагмента: (что записать, был ли фрагмент без ключа).

    ОДНА КОПИЯ НА ОБА ПУТИ (Раунд 62). Расчёт стоял прямо в теле `build`, и
    когда рядом появилась потоковая сборка, второй такой же кусок был бы ровно
    тем «вторым источником правды», от которого проект уже горел трижды."""
    key, span, пусто = _ключ_и_span(morph, acc, text)
    return {"key": key, "span": span, **_extra_fields(text)}, пусто


def build_потоком(mode: str = "incremental") -> int:
    """Сборка ПОТОКОМ — в тот файл, который читают.

    ПОЧЕМУ ЭТО ПОЯВИЛОСЬ. Раунд 57 перевёл кэш на построчный формат, и читатели
    ушли на `nl_rhyme.jsonl` (`кэш.поток` предпочитает его). А инкрементальная
    сборка — та самая, что запускается САМА при добавлении источника
    (`api/server.py`) — осталась на старом `nl_rhyme.json`: читала его целиком в
    память и туда же писала. То есть **залитая книга ложилась в файл, который
    никто не читает**, и в выдачу не попадала.

    На 2026-08-13 файлы ещё совпадали (2 434 632 записи в обоих, книг с 6
    августа не заливали) — то есть данные не потеряны, но следующая заливка
    ушла бы в пустоту.

    Заодно снимается вторая беда того же места: старый путь держал в памяти
    словарь на 2.4 млн записей (около 6 ГБ) — из-за него OOM-киллер уже забирал
    процесс. Здесь память постоянная: строка вошла, строка вышла.

    `mode="full"` — не читать прежнее вовсе, пересчитать всё."""
    import кэш

    _write_status(0, "running", mode)
    morph = pymorphy3.MorphAnalyzer()
    acc = акцентуатор()
    store = nlbridge.open_store()
    fragments = store.get_all_fragments()

    t0 = time.time()
    известные: set[str] = set()
    n_new = n_empty = n_skipped = 0
    with кэш.Писатель() as п:
        if mode != "full":
            # Переливаем прежние записи как есть и попутно узнаём, что уже
            # посчитано. Множество текстов — единственное, что держится в
            # памяти: около 300 МБ против шести гигабайт у старого пути.
            for текст, поля in кэш.поток():
                п.запиши(текст, поля)
                известные.add(текст)
                if п.записано % 500_000 == 0:
                    _write_status(п.записано, "running", mode)
        print(f"{len(fragments)} фрагментов всего, {len(известные)} уже в кэше",
              flush=True)
        for i, f in enumerate(fragments):
            text = f["text"]
            if text in известные:
                n_skipped += 1
                continue
            известные.add(text)
            поля, пусто = _поля_фрагмента(morph, acc, text)
            п.запиши(text, поля)
            n_empty += пусто
            n_new += (0 if пусто else 1)
            if (n_new + n_empty) % 20_000 == 0:
                дт = time.time() - t0
                print(f"  {i}/{len(fragments)} ({дт:.0f}с) — новых {n_new}, "
                      f"без ключа {n_empty}, было {n_skipped}", flush=True)
                _write_status(п.записано, "running", mode)
        всего = п.записано
    print(f"готово: {всего} записей ({n_new} новых, {n_empty} без ключа) за "
          f"{time.time() - t0:.0f}с → {кэш.СТРОЧНЫЙ}", flush=True)
    _write_status(всего, "done", mode)
    return всего


def в_строчный() -> int:
    """Одноразовая миграция: старый кэш → построчный формат (Раунд 57).

    Старый файл НЕ удаляется. Пока пользователь не убедился, что всё работает,
    откат — это удалить один новый файл, а не восстанавливать час работы модели
    ударений."""
    import кэш
    _write_status(0, "running", "jsonl")
    t0 = time.time()
    with кэш.Писатель() as п:
        for текст, поля in кэш.поток():
            п.запиши(текст, поля)
            if п.записано % 500_000 == 0:
                print(f"  {п.записано}  ({time.time()-t0:.0f}с)", flush=True)
                _write_status(п.записано, "running", "jsonl")
    print(f"построчный кэш: {п.записано} записей за {time.time()-t0:.0f}с "
          f"→ {кэш.СТРОЧНЫЙ} (старый файл на месте)", flush=True)
    _write_status(п.записано, "done", "jsonl")
    return п.записано


def reban_потоком() -> int:
    """Пересчёт качества БЕЗ загрузки кэша в память (Раунд 57).

    Читает строку, пересчитывает два поля, пишет строку. Память постоянная —
    именно из-за её отсутствия кнопка «пересчитать качество» падала молча.
    Работает только на построчном формате: на старом одной строкой потока не
    существует, поэтому сперва миграция."""
    import кэш
    if not кэш.есть_строчный():
        raise SystemExit("нет построчного кэша — сперва: build_nl_rhyme.py --jsonl")
    _write_status(0, "running", "reban")
    t0 = time.time()
    n_banal = n_content = 0
    with кэш.Писатель() as п:
        for текст, поля in кэш.поток():
            свежее = _extra_fields(текст)
            if свежее["banal"] != поля.get("banal"):
                n_banal += 1
            if свежее["content"] != поля.get("content"):
                n_content += 1
            поля = {**поля, "banal": свежее["banal"], "content": свежее["content"]}
            п.запиши(текст, поля)
            if п.записано % 500_000 == 0:
                print(f"  {п.записано}  ({time.time()-t0:.0f}с) — банальность {n_banal}, "
                      f"слова {n_content}", flush=True)
                _write_status(п.записано, "running", "reban")
    print(f"пересчёт потоком: {п.записано} за {time.time()-t0:.0f}с, "
          f"банальность изменилась у {n_banal}, слова у {n_content}", flush=True)
    _write_status(п.записано, "done", "reban")
    return п.записано


def rekey_потоком() -> int:
    """Перепись ключей БЕЗ загрузки кэша в память (2026-08-18).

    ЧЕГО ЗДЕСЬ НЕ БЫЛО. У `--reban` развилка на построчный формат появилась в
    Раунде 57, у обычной сборки — в Раунде 62, а `--rekey` так и остался
    единственным режимом, который читает `OUT` БЕЗУСЛОВНО. Значит на доме, где
    лежит только `nl_rhyme.jsonl`, он говорил «нечего переписывать: ... нет» —
    при полном кэше рядом; а если старый файл всё же был, он переписывал
    ключи в файле, КОТОРЫЙ НИКТО НЕ ЧИТАЕТ, и правило ключа менялось только
    на бумаге. Ровно та же болезнь, что в `build_потоком`, только с ключами.

    Заодно снимается память: старый путь держал 2.4 млн записей (около 6 ГБ),
    из-за чего OOM-киллер уже забирал процесс. Здесь строка вошла — строка
    вышла.

    Ключ считается тем же `_ключ_и_span`, что и на сборке: расхождения правила
    между режимами быть не может по построению."""
    import кэш
    if not кэш.есть_строчный():
        raise SystemExit("нет построчного кэша — сперва: build_nl_rhyme.py --jsonl")
    _write_status(0, "running", "rekey")
    morph = pymorphy3.MorphAnalyzer()
    acc = акцентуатор()
    t0 = time.time()
    n_changed = 0
    with кэш.Писатель() as п:
        for текст, поля in кэш.поток():
            key, span, _ = _ключ_и_span(morph, acc, текст)
            if key != поля.get("key"):
                n_changed += 1
            # только два поля: всё остальное зависит от текста, а он не менялся
            п.запиши(текст, {**поля, "key": key, "span": span})
            if п.записано % 500_000 == 0:
                print(f"  {п.записано}  ({time.time()-t0:.0f}с) — изменено {n_changed}",
                      flush=True)
                _write_status(п.записано, "running", "rekey")
    print(f"перепись ключей потоком: {п.записано} за {time.time()-t0:.0f}с, "
          f"ключ изменился у {n_changed}", flush=True)
    _write_status(п.записано, "done", "rekey")
    return п.записано


def лишнее_потоком() -> int:
    """Выбросить из кэша записи, которым в складе больше не соответствует
    ни один фрагмент (2026-08-26).

    ЗАЧЕМ. Кэш ударений ТОЛЬКО ДОПИСЫВАЕТ: инкрементальная сборка добавляет
    новые тексты и не трогает старые. Пока книги просто прибавлялись, это было
    верно. Но стоит книгу перерезать или удалить — её прежние фрагменты
    остаются в кэше навсегда, а таких текстов больше не появится никогда.

    ЗАМЕР ПОСЛЕ ПЕРЕСБОРКИ КОРПУСА 2026-08-26: в кэше 3 258 322 записи при
    2 308 734 фрагментах в складе — мертвы 949 588, то есть 29.1%. Все они от
    ПРЕЖНЕЙ нарезки тех же книг: резак изменился, и старый текст фрагмента не
    воспроизведётся.

    ЧЕМ ЭТО ПЛОХО, ЕСЛИ НЕ ЧИСТИТЬ. Печка индекса идёт по ВСЕМ записям кэша
    (`build_nl_index.записи()`), а книгу для строки ищет по тексту. Мёртвая
    запись книги не находит и ложится в индекс строкой с `src = -1`. В выдачу
    такая строка не попадёт — маска пула строится из АКТИВНЫХ текстов, — но
    место в индексе занимает и удлиняет каждый проход по колонкам на те же
    29%. Это ровно тот же мёртвый груз, что и фрагменты-сироты без книги.

    ОТКАЗ ПРИ ПУСТОМ СКЛАДЕ — не перестраховка. Проход оставляет только то,
    что нашлось в складе; склад, который не открылся или пуст, стёр бы кэш
    целиком, и восстанавливать пришлось бы восемь минут работы акцентуатора.
    Пустой склад бывает ровно посреди пересборки — то есть тогда, когда этот
    режим и захочется запустить."""
    import кэш
    if not кэш.есть_строчный():
        raise SystemExit("нет построчного кэша — сперва: build_nl_rhyme.py --jsonl")
    import nlbridge as _nb
    живые = {ф["text"] for ф in _nb.open_store().get_all_fragments()}
    if not живые:
        raise SystemExit("склад пуст — чистка стёрла бы кэш целиком, отказ")
    _write_status(0, "running", "лишнее")
    t0 = time.time()
    прочитано = выброшено = 0
    with кэш.Писатель() as п:
        for текст, поля in кэш.поток():
            прочитано += 1
            if текст in живые:
                п.запиши(текст, поля)
            else:
                выброшено += 1
            if прочитано % 500_000 == 0:
                print(f"  {прочитано}  ({time.time()-t0:.0f}с) — выброшено {выброшено}",
                      flush=True)
                _write_status(п.записано, "running", "лишнее")
    print(f"чистка кэша: было {прочитано}, выброшено {выброшено} "
          f"({выброшено/max(прочитано,1)*100:.1f}%), осталось {п.записано} "
          f"за {time.time()-t0:.0f}с", flush=True)
    _write_status(п.записано, "done", "лишнее")
    return п.записано


def reban(existing: dict) -> dict:
    """Пересчитать ТОЛЬКО banal и content у уже закэшированных фрагментов.

    Раунд 57. Тот же приём, что `rekey`, и по той же причине: изменилась
    ФОРМУЛА, а не данные. Банальность перестала награждать имена собственные
    (`filters._без_имён`), и появилось поле `content` — сколько в строке обычных
    слов, кроме имён.

    Главное отличие от `--full`: НЕ ГРУЗИТСЯ модель ударений. Она и составляет
    почти всё время полной перепечки, а к банальности отношения не имеет вовсе.
    Проход идёт минуты вместо часа — значит формулу качества можно пробовать, а
    не бояться. Замечание: используется не весь доступный инструментарий..

    Ключи, ударения, span, леммы и токены не трогаются ни одним байтом."""
    _write_status(len(existing), "running", "reban")
    out = dict(existing)
    t0 = last_status = time.time()
    n_banal = n_content = 0
    for i, (text, entry) in enumerate(existing.items()):
        now = time.time()
        if now - last_status >= STATUS_SECONDS:
            dt = now - t0
            print(f"  {i}/{len(existing)} ({dt:.0f}s, {i / max(dt, 1e-9):.0f}/s) — "
                  f"банальность {n_banal}, слова {n_content}", flush=True)
            _write_status(len(out), "running", "reban")
            last_status = now
        свежее = _extra_fields(text)
        if свежее["banal"] != entry.get("banal"):
            n_banal += 1
        if свежее["content"] != entry.get("content"):
            n_content += 1
        # только два поля: всё остальное зависит от текста, а он не менялся
        out[text] = {**entry, "banal": свежее["banal"], "content": свежее["content"]}
    print(f"пересчёт банальности: {len(out)} фрагментов за {time.time() - t0:.0f}с, "
          f"банальность изменилась у {n_banal}, слова посчитаны у {n_content}", flush=True)
    return out


def rekey(existing: dict) -> dict:
    """Пересчитать ТОЛЬКО key и span у уже закэшированных фрагментов.

    Появился в Раунде 33 (2026-08-02), когда изменилось ПРАВИЛО ключа
    (ударная ё сводится к о, и ё восстанавливается перед подсчётом). Данные
    при этом не менялись — менялась формула, и `--full` пересчитывал бы
    заодно banal/taut/lemmas/tokens, которые зависят только от текста и
    остались прежними. Здесь дорогая часть (`_extra_fields`: лемматизация
    каждого токена + zipf + тавтология) не трогается вовсе, поэтому проход
    в разы дешевле полного.

    Магазин nakedlunch не открывается: перебираем сам кэш, а он и есть
    список текстов."""
    _write_status(len(existing), "running", "rekey")
    morph = pymorphy3.MorphAnalyzer()
    acc = акцентуатор()

    out = dict(existing)
    t0 = last_status = time.time()
    n_changed = 0
    for i, (text, entry) in enumerate(existing.items()):
        now = time.time()
        if now - last_status >= STATUS_SECONDS:
            dt = now - t0
            print(f"  {i}/{len(existing)} ({dt:.0f}s, {i / dt:.0f}/s) — изменено {n_changed}",
                  flush=True)
            _write_status(len(out), "running", "rekey")
            last_status = now
        key, span, _ = _ключ_и_span(morph, acc, text)
        if key != entry.get("key"):
            n_changed += 1
        out[text] = {**entry, "key": key, "span": span}
    print(f"перепись ключей: {len(out)} фрагментов за {time.time() - t0:.0f}с, "
          f"ключ изменился у {n_changed}", flush=True)
    return out


def main() -> int:
    # Программа — единственный, кто вправе писать сайдкар. См. `_ПИШЕМ_СТАТУС`.
    писать_статус(True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                         help="ignore the existing cache and recompute EVERY "
                              "fragment from scratch, not just new ones (the "
                              "user's manual '↻ прогнать ударения' button)")
    parser.add_argument("--rekey", action="store_true",
                         help="пересчитать только key/span у закэшированных "
                              "фрагментов (когда изменилось ПРАВИЛО ключа, а "
                              "не данные) — см. докстринг rekey()")
    parser.add_argument("--reban", action="store_true",
                         help="пересчитать только banal/content у закэшированных "
                              "фрагментов (когда изменилась ФОРМУЛА качества, а "
                              "не данные) — модель ударений не грузится вовсе, "
                              "проход идёт минуты вместо часа; см. reban()")
    parser.add_argument("--лишнее", dest="лишнее", action="store_true",
                         help="выбросить записи, которым в складе больше не "
                              "соответствует ни один фрагмент (после пересборки "
                              "корпуса их набирается почти треть) — см. "
                              "лишнее_потоком()")
    parser.add_argument("--jsonl", action="store_true",
                         help="одноразовая миграция кэша в построчный формат "
                              "(старый файл не удаляется) — см. в_строчный()")
    args = parser.parse_args()
    if args.jsonl:
        в_строчный()
        return 0
    if args.лишнее:
        лишнее_потоком()
        return 0
    if args.reban:
        # Построчный кэш есть — идём потоком, без загрузки в память. Это и есть
        # починка кнопки «пересчитать качество».
        import кэш as _кэш
        if _кэш.есть_строчный():
            try:
                reban_потоком()
            except Exception as e:
                _write_status(0, "error", "reban", error=str(e))
                raise
            except BaseException:
                # ПРЕРВАЛИ — ЭТО НЕ «ИДЁТ» (Раунд 58). Ctrl-C и любой сигнал
                # проходят мимо `except Exception`, статус оставался «running»,
                # и шапка навсегда показывала пользователю красное «встало» на
                # работе, которой давно нет. Убрать это из интерфейса было
                # нельзя ничем — только правкой файла руками.
                _write_status(0, "error", "reban", error="пересчёт прерван")
                raise
            return 0
        if not OUT.exists():
            sys.exit(f"нечего пересчитывать: {OUT} нет")
        было = json.loads(OUT.read_text(encoding="utf-8"))
        try:
            out = reban(было)
        except Exception as e:
            _write_status(len(было), "error", "reban", error=str(e))
            raise
        _write_out(out)
        print(f"done: {len(out)} fragments -> {OUT}")
        _write_status(len(out), "done", "reban")
        return 0
    if args.rekey:
        # Построчный кэш есть — идём потоком, в тот файл, который читают.
        # Развилки здесь не было вовсе (2026-08-18): единственный режим,
        # читавший `OUT` безусловно, — см. `rekey_потоком`.
        import кэш as _кэш
        if _кэш.есть_строчный():
            try:
                rekey_потоком()
            except Exception as e:
                _write_status(0, "error", "rekey", error=str(e))
                raise
            except BaseException:
                # Прервали — это не «идёт»: тот же разбор, что у `--reban`.
                _write_status(0, "error", "rekey", error="перепись прервана")
                raise
            return 0
        if not OUT.exists():
            sys.exit(f"нечего переписывать: {OUT} нет")
        было = json.loads(OUT.read_text(encoding="utf-8"))
        try:
            out = rekey(было)
        except Exception as e:
            _write_status(len(было), "error", "rekey", error=str(e))
            raise
        _write_out(out)
        with_key = sum(1 for v in out.values() if v.get("key"))
        print(f"done: {len(out)} fragments cached, {with_key} with a real rhyme key -> {OUT}")
        _write_status(len(out), "done", "rekey")
        return 0
    mode = "full" if args.full else "incremental"

    # ПОСТРОЧНЫЙ ФОРМАТ — ГЛАВНЫЙ ПУТЬ (Раунд 62). Здесь была развилка только у
    # `--reban`, а обычная сборка (и та, что запускается сама при заливке книги)
    # шла старым файлом — то есть писала туда, где её никто не читает. Теперь
    # развилка одна и стоит первой.
    import кэш as _кэш
    if _кэш.есть_строчный():
        try:
            build_потоком(mode)
        except Exception as e:
            _write_status(0, "error", mode, error=str(e))
            raise
        except BaseException:
            _write_status(0, "error", mode, error="сборка прервана")
            raise
        return 0

    existing = {} if args.full else (json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {})
    try:
        out = build(existing, mode)
    except Exception as e:
        _write_status(len(existing), "error", mode, error=str(e))
        raise
    # build() only ever ADDS entries, so equal length means nothing new — the
    # file on disk already IS `out` (incremental started from it, and no
    # checkpoint fired): skip the pointless ~1GB rewrite. --full always
    # writes; its whole contract is "recompute and rewrite".
    if mode == "full" or len(out) != len(existing):
        _write_out(out)
    with_key = sum(1 for v in out.values() if v.get("key"))
    print(f"done: {len(out)} fragments cached, {with_key} with a real rhyme key -> {OUT}")
    _write_status(len(out), "done", mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
