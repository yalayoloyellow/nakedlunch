#!/usr/bin/env python3
# extendo — precompute rhyme keys for nakedlunch fragments (OFFLINE, one-time;
# ~0.16ms/fragment measured 2026-07-14 — see below — so ≈8 min of compute for
# the 2 868 100-fragment pool of 2026-08-01). Mirrors build_forms.py's pattern:
# run the accentuator ONCE at build time, write a plain dict-lookup cache, so
# the runtime generate path never touches ruaccent.
#
# WHY this exists at all: the owner explicitly rejected exempting nakedlunch
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
# of the rhyme tail within fragment_text, for the owner's rhyme-highlight UI
# (bold+color the actual substring, not just show the abstract key — see
# scan._rhyme_tail's docstring). "banal"/"taut"/"lemmas"/"tokens" (2026-07-14,
# same round) move banality/tautology/diversify-lemmas/theme-bias-matching OFF
# the request path entirely — filters._nl_scored used to call lemmatize() +
# zipf_frequency() + a tautology scan on every fetched fragment on EVERY
# generate(), which is why the runtime only ever looked at a small sample
# instead of the owner's whole active pool ("пусть обрабатывается... полная
# база абсолютно везде"). Precomputing them once here (a benchmark of 200k
# synthetic entries with these fields already computed took ~24ms to filter —
# see DECISIONS.md) makes a full-pool scan on every request cheap instead of
# needing an async job + progress bar. Missing entry (fragment added after the
# last build run) degrades honestly (rhyme="", banal=9.0 i.e. always banal,
# taut=False, empty lemmas/tokens) — rerun this script (or let
# /api/nl/source/add trigger it automatically) after adding a large source.

import argparse
import json
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
from corpus import lemmatize, lemmatize_pairs  # noqa: E402
from _accent import stress_index  # noqa: E402  (shared with build_forms.py)

OUT = ROOT / "core" / "data" / "nl_rhyme.json"
STATUS = ROOT / "core" / "data" / "nl_rhyme.status.json"
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
    of run is/was in progress — found 2026-07-14: the owner's manual "прогнать
    ударения" button looked broken because it silently did the same
    skip-everything-already-cached incremental pass as the auto-trigger, so
    clicking it when the cache was already ~100% complete finished in
    seconds with nothing visibly different from doing nothing at all."""
    STATUS.write_text(json.dumps({
        "cached": cached, "state": state, "mode": mode,
        "error": error, "updated_at": time.time(),
    }, ensure_ascii=False), encoding="utf-8")


def _write_out(out: dict) -> None:
    """Serialize-then-rename: at current scale one checkpoint is a ~1GB dump
    taking double-digit seconds — a kill or sleep mid-write must leave the
    previous complete file in place, not a torn JSON that every reader
    (filters.warm_caches, this script's own incremental resume) would crash
    on. Path.replace is atomic on the same filesystem."""
    tmp = OUT.parent / (OUT.name + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT)


def _clean(tok: str) -> str:
    return tok.strip(_PUNCT).lower()


_TOKEN_RE = re.compile(r"\S+")


def _highlight_span(text: str, idx: int, surface: str, key: str) -> list[int] | None:
    """Absolute [start, end) range in `text` of the RAW (unreduced) rhyme
    tail — same length as `key` (scan.rhyme_key's reduction/devoicing never
    changes length) — for the owner's rhyme-highlight UI: bold+color the
    actual substring driving the match in the rendered line, not just an
    abstract key off to the side (2026-07-14 — the owner's own proposed fix
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
    return {"banal": round(banal, 3), "taut": taut, "lemmas": lemma_list,
            "tokens": tokens, "content": len(обычные)}


def build(existing: dict, mode: str = "incremental") -> dict:
    # Say "running" BEFORE the slow model load, not at the first checkpoint:
    # api/server.py's double-spawn guard can only see runs it didn't start
    # itself through this file, and until it says "running" a second
    # /api/nl/source/add could spawn a second ONNX process — the exact thing
    # that guard exists to prevent.
    _write_status(len(existing), "running", mode)

    morph = pymorphy3.MorphAnalyzer()
    from ruaccent import RUAccent
    acc = RUAccent()
    acc.load(omograph_model_size="turbo2", use_dictionary=True, tiny_mode=False)

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

        tokens = text.split()
        idx = _last_content_index(morph, tokens) if tokens else None
        if idx is None:
            out[text] = {"key": "", "span": None, **_extra_fields(text)}
            n_empty += 1
            continue

        surface = _clean(tokens[idx])
        key = _word_rhyme_key(acc, surface, tokens[idx])
        out[text] = {"key": key, "span": _highlight_span(text, idx, surface, key), **_extra_fields(text)}
        n_new += 1

    return out


def в_строчный() -> int:
    """Одноразовая миграция: старый кэш → построчный формат (Раунд 57).

    Старый файл НЕ удаляется. Пока владелец не убедился, что всё работает,
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


def reban(existing: dict) -> dict:
    """Пересчитать ТОЛЬКО banal и content у уже закэшированных фрагментов.

    Раунд 57. Тот же приём, что `rekey`, и по той же причине: изменилась
    ФОРМУЛА, а не данные. Банальность перестала награждать имена собственные
    (`filters._без_имён`), и появилось поле `content` — сколько в строке обычных
    слов, кроме имён.

    Главное отличие от `--full`: НЕ ГРУЗИТСЯ модель ударений. Она и составляет
    почти всё время полной перепечки, а к банальности отношения не имеет вовсе.
    Проход идёт минуты вместо часа — значит формулу качества можно пробовать, а
    не бояться. Владелец: «может, мы не весь инструментарий используем ещё, чтоб
    грамотно всё делать».

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
    from ruaccent import RUAccent
    acc = RUAccent()
    acc.load(omograph_model_size="turbo2", use_dictionary=True, tiny_mode=False)

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
        tokens = text.split()
        idx = _last_content_index(morph, tokens) if tokens else None
        if idx is None:
            key, span = "", None
        else:
            surface = _clean(tokens[idx])
            key = _word_rhyme_key(acc, surface, tokens[idx])
            span = _highlight_span(text, idx, surface, key)
        if key != entry.get("key"):
            n_changed += 1
        out[text] = {**entry, "key": key, "span": span}
    print(f"перепись ключей: {len(out)} фрагментов за {time.time() - t0:.0f}с, "
          f"ключ изменился у {n_changed}", flush=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                         help="ignore the existing cache and recompute EVERY "
                              "fragment from scratch, not just new ones (the "
                              "owner's manual '↻ прогнать ударения' button)")
    parser.add_argument("--rekey", action="store_true",
                         help="пересчитать только key/span у закэшированных "
                              "фрагментов (когда изменилось ПРАВИЛО ключа, а "
                              "не данные) — см. докстринг rekey()")
    parser.add_argument("--reban", action="store_true",
                         help="пересчитать только banal/content у закэшированных "
                              "фрагментов (когда изменилась ФОРМУЛА качества, а "
                              "не данные) — модель ударений не грузится вовсе, "
                              "проход идёт минуты вместо часа; см. reban()")
    parser.add_argument("--jsonl", action="store_true",
                         help="одноразовая миграция кэша в построчный формат "
                              "(старый файл не удаляется) — см. в_строчный()")
    args = parser.parse_args()
    if args.jsonl:
        в_строчный()
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
                # и шапка навсегда показывала владельцу красное «встало» на
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
