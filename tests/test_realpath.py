# extendo — the real-path test (PRINCIPLES §9: test the scenario, not the function).
# Что обязано держаться: прогон даёт шорт-лист, а история/избранное реально
# скрывают строки из будущих прогонов — обратимо (история) или навсегда
# (избранное). Run: .venv/bin/python -m pytest tests/test_realpath.py -q
#
# 2026-07-14: rewritten after the user asked to remove all λ-based
# preference/history-distance scoring and replace the permanent seen-set with
# reversible История (see core/corpus.py, core/filters.py). The old
# `test_accepted_corpus_steers_next_run` tested exactly the mechanism that was
# removed — replaced with tests of what favorites/history actually guarantee
# now: permanent exclusion for favorites, reversible exclusion for history.
#
# ═══ НАДГРОБИЯ 2026-08-29 ═══════════════════════════════════════════════════
# Владелец снёс тему, обязательное слово «!слово», грамматический генератор и
# сборщик строфы `filters._select_with_rhyme`. Ниже — что этот файл проверял
# ими и почему проверять больше нечего. Ни один тест не «подогнан под зелень»:
# либо переписан на живой путь с тем же смыслом, либо удалён целиком.
#
# · test_bad_theme_fails_fast — пустая ТЕМА обязана давать одно человеческое
#   предложение, а не traceback. `clean.theme` удалён вместе с полем темы.
#   СМЫСЛ СОХРАНЁН: тот же сторож переписан на `clean.favorite` — единственный
#   оставшийся в clean.py вход, который умеет сказать «нет» (см.
#   `test_bad_input_fails_fast` ниже). Проверяется ровно то же свойство:
#   отказ — это фраза для человека, а не падение и не тихий пропуск.
#
# · test_theme_stuffing_is_capped_and_semantic_lines_surface — предел «≈1
#   буквальная строка на строфу» (`literal_cap`) и подъём смысловых совпадений
#   через векторы navec. Тема вырезана целиком: ни буквальных совпадений, ни
#   релевантности, ни ручки «Диссонанс» больше нет. Переписывать не на что.
#
# · test_cohesion_percentile_spans_the_whole_range — крутилка связности обязана
#   двигать топ на КАЖДОМ шаге, а не быть трёхпозиционной. Крутилки нет,
#   перцентиль-таргета нет, `filters._strict_score_cache` снят вместе со
#   строгой безиндексной таблицей.
#
# · test_theme_anchor_present_on_topic_and_not_a_duplicate — тематический якорь
#   (одна строка точно в тему, чтобы с ней диссонировать). Якоря нет; поле
#   `anchor` осталось в форме ответа константой False и ничего не обещает.
#
# · test_forced_word_hard_guarantee — четыре исхода `!слово` (уже есть /
#   вставили / missing / unrhymed). `filters._ensure_forced` удалён,
#   `forced_notice` остался пустым словарём ради формы ответа.
#
# · test_all_grammar_templates_actually_produce_output — все шаблоны
#   грамматического генератора обязаны реально порождать текст. `core/generate.py`
#   удалён, `api/server.py` шлёт `lines = []` всегда. Шаблонов нет.
#
# · test_select_with_rhyme_avoids_lemma_repeat_within_stanza — якорь рифмо-группы
#   обязан выбрать корзину, где есть лемма-отличный партнёр. Сборщик снесён, а
#   прямая тяга выбирает корзину ДО того, как узнаёт леммы (см.
#   `nlindex._первая_своей_буквы`) — этой оглядки в ней нет и по замыслу быть не
#   может. САМ БАРЬЕР на повтор леммы внутри строфы жив и переехал в
#   `nlindex.тянуть_строфы`; его сторож — tests/test_hook_repeat.py, переписанный
#   в тот же день. Дублировать его здесь нечем.
#
# · test_syllable_reserve_survives_the_score_cap — `_syllable_reserve` вытаскивал
#   низкобалльного кандидата нужной длины из-под среза по баллу. Ни среза по
#   баллу, ни резерва больше нет: прямая тяга режет пул слоговой вилкой ПЕРВОЙ
#   и тянет случайного среди уже подходящих форме.
#
# · test_splice_fills_a_too_short_slot_with_a_rhyming_tail и
#   test_trim_shortens_an_overlong_candidate_without_touching_the_rhyme —
#   склейка коротких и обрезка длинных строк под слоговую вилку. Оба механизма
#   жили внутри `_select_with_rhyme` и ушли с ним. Прямая тяга текст не правит
#   вовсе: она берёт строку корпуса как есть либо не берёт никакую (сторож на
#   этот размен — `test_форма_и_рифма_обе_жёсткие` ниже).
# ═══════════════════════════════════════════════════════════════════════════

import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import clean
import filters
import nlbridge
import nlindex
from corpus import Corpus, lemmatize


# ---------------------------------------------------------------------------
# Пул корпуса: единственный источник строк с 2026-08-29 (генератор вырезан).
# `_NL_RHYME` подделан — важно не КАК считаются его поля, а что путь без
# колоночного индекса получает те же данные, что в работе.

def _пул(тексты: list[str], ключ="ело") -> dict:
    return {t: {"banal": 3.0, "taut": False, "lemmas": lemmatize(t),
                "tokens": list(nlbridge._tokens(t)),
                # `content` обязателен: путь без индекса режет по нему строки
                # короче nlindex.СЛОВ_МИН, как это делают ворота индекса
                "content": len(t.split()), "key": ключ, "span": None}
            for t in тексты}


def _без_индекса(monkeypatch, тексты, ключ="ело"):
    """Живой путь БЕЗ колоночного индекса (`filters._nl_scored(light=True)`).

    Это не выдумка ради теста: так работает свежая установка до первой выпечки
    и любая машина, где индекс разошёлся с кэшем рифм. Здесь он нужен потому,
    что проверяется поведение на СВОЁМ пуле из десятков строк, а боевой индекс
    знает свои два с лишним миллиона и наших строк в нём нет вовсе."""
    monkeypatch.setattr(filters, "_NL_RHYME", _пул(тексты, ключ))
    monkeypatch.setattr(filters, "_index_for_current_cache", lambda: None)


ПУЛ = [f"строка номер {i} про разное дело" for i in range(80)]


# ---------------------------------------------------------------------------
# Отказ на кривом вводе

def test_bad_input_fails_fast():
    """Кривой ввод → одно человеческое предложение, а не traceback и не тихий
    пропуск. Раньше сторожил `clean.theme("")`; тема вырезана 2026-08-29, и
    из входов clean.py говорить «нет» умеет только `favorite` — свойство
    проверяется на нём."""
    for bad in (None, {}, {"text": ""}, {"text": "   "}):
        try:
            clean.favorite(bad)
            assert False, f"пустой ввод {bad!r} обязан быть отвергнут"
        except clean.BadInput as e:
            assert str(e) and "traceback" not in str(e).lower()
    # и обратная сторона: годный ввод проходит, иначе «отвергает всё» тоже
    # зеленело бы
    assert clean.favorite({"text": "  живая строка  "}) == "живая строка"


# ---------------------------------------------------------------------------
# Прогон целиком

def test_прогон_даёт_шортлист_и_воронка_не_врёт(monkeypatch):
    """Каскад реально работает: из пула выходит непустой шорт-лист, и воронка
    честно говорит, сколько строк взяли из скольких.

    Раньше вход был `generate.generate(clean.theme(...))` — генератор и тема
    вырезаны, источник остался один: корпус."""
    _без_индекса(monkeypatch, ПУЛ)
    res = filters.run([], clean.knobs({"shortlist": 8}), Corpus(),
                      nl_fragments=ПУЛ, rhyme="none", семя=1)
    assert len(res["shortlist"]) == 8, "прогон обязан отдать запрошенное число строк"
    в = res["funnel"]
    assert в["nl_fetched"] == len(ПУЛ), "воронка обязана называть размер пула"
    assert в["nl_used"] == len(res["shortlist"]) > 0
    assert в["nl_fetched"] > в["nl_used"], "каскад обязан реально резать, а не пропускать всё"


def test_favorites_never_resurface(monkeypatch):
    """Accepting (favoriting) a line excludes it from every later run, forever
    — no retention period, no restore needed (user: «избранное... никуда не
    пропадает никогда», and the flip side of that permanence is it never
    comes BACK as fresh output either)."""
    _без_индекса(monkeypatch, ПУЛ)
    corp = Corpus()

    first = filters.run([], clean.knobs({"shortlist": 12}), corp,
                        nl_fragments=ПУЛ, rhyme="none", семя=1)
    assert first["shortlist"], "expected a real shortlist to favorite from"
    for r in first["shortlist"][:4]:
        corp.accept(r["text"], lemmatize(r["text"]))

    favorited = {a["text"] for a in corp.accepted}
    assert len(favorited) == 4, "избранное должно было пополниться"
    # shortlist=40 из пула в 80 строк: будь избранное видимым, оно попало бы в
    # выдачу почти наверняка — на shortlist=12 отсутствие ничего не значило бы
    again = filters.run([], clean.knobs({"shortlist": 40}), corp,
                        nl_fragments=ПУЛ, rhyme="none", семя=2)
    assert len(again["shortlist"]) == 40
    assert not (favorited & {r["text"] for r in again["shortlist"]}), \
        "a favorited line resurfaced"


def test_history_hides_then_restore_reverses_it(monkeypatch):
    """Every shown line moves to История automatically and is excluded from
    later runs — but (unlike favorites) it's reversible: restoring it makes
    it eligible again (user: «но пока это не сделано они не показываются
    больше в выдаче» — the key word is «пока», not «никогда»)."""
    _без_индекса(monkeypatch, ПУЛ)
    corp = Corpus()

    first = filters.run([], clean.knobs({"shortlist": 20}), corp,
                        nl_fragments=ПУЛ, rhyme="none", семя=3)
    shown = {r["text"] for r in first["shortlist"]}
    assert len(shown) == 20, "expected a real shortlist"
    corp.mark_shown([{"text": t, "template": ""} for t in shown])  # server does this at display time
    assert shown <= corp.hidden_set(), "shown lines should be hidden immediately"

    second = filters.run([], clean.knobs({"shortlist": 40}), corp,
                         nl_fragments=ПУЛ, rhyme="none", семя=4)
    assert not (shown & {r["text"] for r in second["shortlist"]}), \
        "a hidden line reappeared before restore"

    # Whether a now-eligible line actually gets RE-PICKED by a later run is a
    # sampling question, not a guarantee — _diversify shuffles before a stable
    # sort, so a fresh run over the same candidates can pick a different top-N
    # even among eligible ones. What corpus.py actually promises is the STATE
    # transition: restore() takes it out of hidden_set() — that's what's
    # checked here, not downstream selection luck.
    corp.restore(shown)
    assert not (shown & corp.hidden_set()), "restored lines should no longer be hidden"


def test_adjacent_lines_differ(monkeypatch):
    """The shortlist is a SEQUENCE: neighbours should rarely share content words.

    Разнос соседей (`filters._diversify` через `_diversify_с_долей_мата`) —
    единственная ступень, которая на пути без схемы вообще смотрит на порядок.
    2026-08-29 её сила стала КОНСТАНТОЙ 0.55: она считалась от ручки
    «Диссонанс», а ручка вырезана вместе с темой — то есть сторожить это
    свойство теперь некому, кроме этого теста.

    КОНТРОЛЬ ВНУТРИ ТЕСТА, а не рядом. Пул нарочно из десяти слов: пересечения
    у соседей часты по построению, и случайный порядок того же пула даёт
    6-11 столкновений на двадцати строках. Без этого числа «столкновений мало»
    зеленело бы и на пуле, где их неоткуда взять."""
    СЛОВА = ["ночь", "город", "холод", "огонь", "ветер",
             "снег", "дом", "река", "птица", "свет"]
    гсч = random.Random(9)
    тексты: list[str] = []
    while len(тексты) < 300:
        t = " ".join(гсч.sample(СЛОВА, 4))
        if t not in тексты:
            тексты.append(t)
    _без_индекса(monkeypatch, тексты, ключ="ень")

    for семя in range(5):
        res = filters.run([], clean.knobs({"shortlist": 20}), Corpus(),
                          nl_fragments=тексты, rhyme="none", семя=семя)
        sl = [set(lemmatize(r["text"])) for r in res["shortlist"]]
        assert len(sl) == 20
        столкновений = sum(1 for i in range(1, len(sl)) if len(sl[i] & sl[i - 1]) >= 2)
        случайно = [set(lemmatize(t)) for t in гсч.sample(тексты, 20)]
        контроль = sum(1 for i in range(1, len(случайно))
                       if len(случайно[i] & случайно[i - 1]) >= 2)
        assert контроль >= 4, \
            f"контрольный пул сам по себе не даёт столкновений ({контроль}) — сторож беззубый"
        assert столкновений <= 2, \
            f"соседи почти одинаковы: {столкновений} столкновений (случайно — {контроль})"


# ---------------------------------------------------------------------------
# Леммы

def test_typographic_punctuation_does_not_eat_words():
    """Найдено спайком 2026-07-17 на реальных данных: 75 из 2406 строк пользователя
    теряли слова ЦЕЛИКОМ, потому что `lemmatize` не снимала «…» и короткое «–».
    Сценарий, а не функция: строка с типографской пунктуацией должна давать те
    же леммы, что и без неё — иначе тавтология и разнообразие соседей молча
    считаются по обрезанному множеству."""
    assert lemmatize("ночь…") == lemmatize("ночь") == ["ночь"]
    assert lemmatize("морфия…") == ["морфий"]
    assert lemmatize("ночь – день") == lemmatize("ночь день") == ["ночь", "день"]
    # длинное тире работало и раньше — не сломали
    assert lemmatize("ночь — день") == ["ночь", "день"]


# ---------------------------------------------------------------------------
# Схема и форма — на ПРЯМОЙ ТЯГЕ, единственном пути сборки строфы с 2026-08-29

class _Индекс:
    """Колонки, которые читает `nlindex.тянуть_строфы`, и ничего сверх.

    Свой индекс, а не боевой: боевой знает два с лишним миллиона строк, и
    проверить на нём «какие ИМЕННО позиции срифмовались» нельзя — там
    рифмуется всё со всем."""

    def __init__(self, строки):
        # строки: [(текст, рифмо-ключ, слоги)]
        self.keys = sorted({к for _, к, _ in строки})
        номер = {к: i for i, к in enumerate(self.keys)}
        self._т = [т for т, _, _ in строки]
        self.key_id = np.array([номер[к] for _, к, _ in строки], dtype=np.int64)
        self.syl = np.array([с for _, _, с in строки], dtype=np.int64)
        self.mat = np.zeros(len(строки), dtype=np.uint8)
        # по своей лемме на строку: барьер повтора не должен мешать замеру
        self.lem_off = np.arange(len(строки) + 1, dtype=np.int64)
        self.lem_ids = np.arange(len(строки), dtype=np.int64)

    def text(self, i):
        return self._т[i]


def _строфа(monkeypatch, идх, схема, size, spec, семя=0):
    monkeypatch.setattr(nlindex, "_строки", lambda idx, ids, оц, пц: [
        {"text": idx.text(int(i)), "rhyme": idx.keys[int(idx.key_id[i])],
         "syllables": int(idx.syl[i])} for i in ids])
    return nlindex.тянуть_строфы(идх, np.arange(len(идх._т)), spec, схема, size,
                                 np.random.default_rng(семя), ярусы_рифмы=1)


# Две рифмо-группы, разведённые ПО ДЛИНЕ: короткая «ад» и длинная «юк». Так
# видно, какие именно позиции схема свела в пару, — на одинаковых длинах это
# было бы неразличимо.
КОРОТКИЕ_И_ДЛИННЫЕ = [
    ("первый ясный сад", "ад", 6), ("второй тенистый склад", "ад", 6),
    ("третий тихий над", "ад", 6), ("четвёртый мокрый ряд", "ад", 6),
    ("длинная строка про южный сундук", "юк", 10),
    ("другая долгая строка про лук", "юк", 10),
    ("третья долгая строка про стук", "юк", 10),
    ("ещё одна долгая строка про звук", "юк", 10),
]
ВИЛКИ_АББА = [(5, 7), (9, 11), (9, 11), (5, 7)]


def test_scheme_typed_in_latin_or_digits_is_the_same_rhyme(monkeypatch):
    """требование: схему можно прописывать цифрами и латиницей (PLAN.md 0.6).
    Сценарий, а не функция: набранная латиницей/цифрами схема должна давать ТУ
    ЖЕ рифмовку, что кириллицей — до 2026-07-17 `aabb` молча превращалось в
    "none" (некириллица проваливала _SCHEME_RE), то есть поле съедало ввод и
    выдавало выдачу вообще без рифмы.

    2026-08-29: раньше «те же позиции» сверялись через `filters._rhyme_scheme_groups`
    — функцию снесённого сборщика, у которой в живом коде читателей не осталось.
    Теперь сверяются по РЕЗУЛЬТАТУ прямой тяги: какие позиции реально
    срифмовались. Разница видна: «абба» сводит 0-3 и 1-2, «абаб» — 0-2 и 1-3."""
    assert clean.rhyme_scheme("aabb") == clean.rhyme_scheme("аабб") == "аабб"
    assert clean.rhyme_scheme("1212") == clean.rhyme_scheme("абаб") == "абаб"
    # Чистую кириллицу не трогаем: «баба» остаётся «бабой», а не канонизируется
    # в «абаб» — иначе поле спорило бы с пользователем на полуслове.
    assert clean.rhyme_scheme("баба") == "баба"

    идх = _Индекс(КОРОТКИЕ_И_ДЛИННЫЕ)
    выдачи = []
    for набрано in ("abba", "1221", "абба"):
        схема = clean.rhyme_scheme(набрано)
        assert схема == "абба", f"{набрано!r} не доехало до канона: {схема!r}"
        строфа = _строфа(monkeypatch, идх, схема, 4, ВИЛКИ_АББА, семя=7)
        assert len(строфа) == 4, f"{набрано!r}: строфа не собралась: {строфа}"
        ключи = [r["rhyme"] for r in строфа]
        assert ключи[0] == ключи[3], f"{набрано!r}: позиции 1 и 4 не срифмовались: {ключи}"
        assert ключи[1] == ключи[2], f"{набрано!r}: позиции 2 и 3 не срифмовались: {ключи}"
        assert ключи[0] != ключи[1], f"{набрано!r}: «абба» выродилась в одну рифму: {ключи}"
        выдачи.append([r["text"] for r in строфа])
    assert выдачи[0] == выдачи[1] == выдачи[2], \
        f"латиница/цифры/кириллица дали РАЗНЫЕ строфы при одном семени: {выдачи}"


def test_форма_и_рифма_обе_жёсткие(monkeypatch):
    """Конструктор строф (PLAN.md 0.7) — требование: выбор минимального и
    максимального числа слогов в каждой строке. На прямой вопрос «чем
    жертвовать в последнюю очередь» был ответ «рифма важнее».

    2026-08-29 РАЗМЕНА БОЛЬШЕ НЕ СУЩЕСТВУЕТ, и это надо стеречь явно. Прямая
    тяга режет пул слоговой вилкой ПЕРВОЙ (`syl >= lo & syl <= hi`), а
    партнёра ищет уже внутри среза: сломать длину она не может физически, а
    рифму не ломает и запасной путь (он снимает только запрет повтора слов).
    Не нашлось строки, годной по обоим, — позиция остаётся ПУСТОЙ.

    Два сценария: (1) годная пара есть — обе строки в вилке и в рифме;
    (2) годной пары нет — строфа выходит КОРОЧЕ, а не заполняется строкой не
    той длины или не в рифму. Второй и есть настоящий сторож: тихая подстановка
    «почти подходящей» строки — ровно та ложь, которой тут не место."""
    # (1) в вилке (5,7) группа «ад» даёт четырёх партнёров — пара обязана встать
    идх = _Индекс(КОРОТКИЕ_И_ДЛИННЫЕ)
    for семя in range(10):
        строфа = _строфа(monkeypatch, идх, "аа", 2, [(5, 7), (5, 7)], семя=семя)
        assert len(строфа) == 2, f"пара была доступна, строфа не собралась: {строфа}"
        assert строфа[0]["rhyme"] == строфа[1]["rhyme"] == "ад", \
            f"рифма сломана (семя {семя}): {[r['rhyme'] for r in строфа]}"
        for r in строфа:
            assert 5 <= r["syllables"] <= 7, f"строка вне вилки: {r}"

    # (2) в вилке (5,7) есть РОВНО ОДНА строка, и партнёра ей взять неоткуда:
    # остальные того же ключа — длинные. Позиция обязана остаться пустой.
    одиночка = _Индекс([
        ("единственный ясный сад", "ад", 6),
        ("длинная строка про тот же самый сад", "ад", 12),
        ("другая длинная строка про сад", "ад", 12),
        ("длинная строка про южный сундук", "юк", 10),
    ])
    for семя in range(10):
        строфа = _строфа(monkeypatch, одиночка, "аа", 2, [(5, 7), (5, 7)], семя=семя)
        assert len(строфа) == 1, (
            "партнёра нужной длины не было — тяга обязана оставить позицию "
            f"пустой, а не подставить чужую строку: {строфа}")
        assert 5 <= строфа[0]["syllables"] <= 7, f"строка вне вилки: {строфа[0]}"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
