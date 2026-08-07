# extendo — the real-path test (PRINCIPLES §9: test the scenario, not the function).
# The one thing that must hold: тема → шорт-лист → история/избранное реально
# скрывают строки из будущих прогонов, обратимо (история) или навсегда
# (избранное). Run: python tests/test_realpath.py (or: pytest tests/).
#
# 2026-07-14: rewritten after the owner asked to remove all λ-based
# preference/history-distance scoring and replace the permanent seen-set with
# reversible История (see core/corpus.py, core/filters.py). The old
# `test_accepted_corpus_steers_next_run` tested exactly the mechanism that was
# removed — replaced with tests of what favorites/history actually guarantee
# now: permanent exclusion for favorites, reversible exclusion for history.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import clean
from conftest import нет_словаря_рифм, нет_векторов  # noqa: F401
import filters
import generate
import nlbridge
from corpus import Corpus, lemmatize


def test_bad_theme_fails_fast():
    """Bad input → one human sentence, not a traceback or an empty run."""
    for bad in ("", "   ", ",,,"):
        try:
            clean.theme(bad)
            assert False, f"empty theme {bad!r} should have been rejected"
        except clean.BadInput as e:
            assert str(e) and "traceback" not in str(e).lower()


def test_theme_produces_shortlist():
    tags = clean.theme("ночь, город, холод")
    lines = generate.generate(tags, n=1500, seed=1)
    res = filters.run(lines, clean.knobs({"shortlist": 20}), Corpus())
    assert res["shortlist"], "a real theme must yield a shortlist"
    assert res["funnel"]["generated"] > res["funnel"]["shortlist"]  # the cascade actually cuts


def test_favorites_never_resurface():
    """Accepting (favoriting) a line excludes it from every later run, forever
    — no retention period, no restore needed (owner: "избранное... никуда не
    пропадает никогда", and the flip side of that permanence is it never
    comes BACK as fresh output either)."""
    tags = clean.theme("ночь, город, холод")
    lines = generate.generate(tags, n=2000, seed=1)
    corp = Corpus()

    first = filters.run(lines, clean.knobs({"shortlist": 12}), corp)
    assert first["shortlist"], "expected a real shortlist to favorite from"
    for r in first["shortlist"][:4]:
        corp.accept(r["text"], lemmatize(r["text"]))

    favorited = {a["text"] for a in corp.accepted}
    again = filters.run(lines, clean.knobs({"shortlist": 40}), corp)
    assert not (favorited & {r["text"] for r in again["shortlist"]}), \
        "a favorited line resurfaced"


def test_history_hides_then_restore_reverses_it():
    """Every shown line moves to История automatically and is excluded from
    later runs — but (unlike favorites) it's reversible: restoring it makes
    it eligible again (owner: "но пока это не сделано они не показываются
    больше в выдаче" — the key word is "пока", not "никогда")."""
    tags = clean.theme("ночь, город, холод")
    corp = Corpus()
    lines = generate.generate(tags, n=3000, seed=3)

    first = filters.run(lines, clean.knobs({"shortlist": 20}), corp)
    shown = {r["text"] for r in first["shortlist"]}
    assert shown, "expected a real shortlist"
    corp.mark_shown([{"text": t, "template": ""} for t in shown])  # server does this at display time
    assert shown <= corp.hidden_set(), "shown lines should be hidden immediately"

    second = filters.run(generate.generate(tags, n=3000, seed=4), clean.knobs({"shortlist": 20}), corp)
    assert not (shown & {r["text"] for r in second["shortlist"]}), "a hidden line reappeared before restore"

    # Whether a now-eligible line actually gets RE-PICKED by a later random
    # generate() is a sampling question, not a guarantee — _diversify shuffles
    # before a stable sort, so a fresh run over the same candidates can pick a
    # different top-N even among eligible ones. What corpus.py actually
    # promises is the STATE transition: restore() takes it out of hidden_set()
    # — that's what's checked here, not downstream selection luck.
    corp.restore(shown)
    assert not (shown & corp.hidden_set()), "restored lines should no longer be hidden"


def test_adjacent_lines_differ():
    """The shortlist is a SEQUENCE: neighbours should rarely share content words."""
    tags = clean.theme("ночь, город, холод, огонь")
    res = filters.run(generate.generate(tags, n=4000, seed=2),
                      clean.knobs({"shortlist": 20, "explore": 0.4}), Corpus())
    sl = res["shortlist"]
    sets = [set(lemmatize(r["text"])) for r in sl]
    clashes = sum(1 for i in range(1, len(sets)) if len(sets[i] & sets[i - 1]) >= 2)
    assert clashes <= 1, f"too many near-identical neighbours: {clashes}"


@нет_векторов
def test_theme_stuffing_is_capped_and_semantic_lines_surface():
    """Найдено владельцем вживую 2026-07-17: тема «деньги» → слово буквально
    в 19 из 20 строк ("я же говорил что не хочу так"). Причина —
    core/filters.py._nl_scored раньше давало ЛЮБОМУ фрагменту с буквальным
    совпадением фиксированный +1 к баллу против +0 у всех остальных; при
    сотнях буквальных совпадений в пуле они и заполняли шорт-лист почти
    целиком. Сценарий, не функция: синтетический пул из буквальных,
    смысловых-без-слова и нерелевантных фрагментов — после фикса (navec
    relevance + literal_cap, PLAN.md 0.2) буквальных в выдаче не больше
    расчётного лимита (≈1 на строфу), а смысловые фрагменты реально
    попадают в выдачу, не только буквальные."""
    literal = ["нашёл деньги в кармане", "деньги ей не помогли совсем",
               "все деньги ушли на такси", "деньги пропали бесследно вчера",
               "он хранил деньги под матрасом", "деньги решают почти всё сразу"]
    semantic = ["он заплатил за проезд сполна", "она тратила наличные быстро",
                "мы купили квартиру задорого", "продавец получил свои доллары",
                "расплатился щедро и ушёл прочь", "заработал он немного и устал"]
    irrelevant = ["кошка спала на теплом окне", "дождь шёл всю ночь напролёт",
                  "он рисовал закат акварелью", "листья падали медленно вниз",
                  "птицы кружили над рекой тихо", "снег скрипел под сапогами громко"]
    all_texts = literal + semantic + irrelevant

    fake_rhyme = {t: {"banal": 3.0, "taut": False, "lemmas": lemmatize(t),
                      "tokens": list(nlbridge._tokens(t)), "key": "", "span": None}
                 for t in all_texts}
    old_rhyme = filters._NL_RHYME
    filters._NL_RHYME = fake_rhyme
    try:
        tags = clean.theme("деньги")
        # cohesion=1.0 — explicit (2026-07-18, cohesion became bipolar, see
        # filters.run's theme_pull docstring): the knob's default 0.5 is now
        # deliberately NEUTRAL (zero theme pull, by owner's own request — a
        # true midpoint between "консонанс" and "диссонанс"), so at the old
        # implicit default every row here would score identically and this
        # assertion would depend on random.shuffle's draw. This test is
        # specifically about theme pull ranking relevant content up, so it
        # needs the knob set to where that pull actually exists.
        res = filters.run([], clean.knobs({"shortlist": 12, "real_text": 1.0, "cohesion": 1.0}),
                          Corpus(), nl_fragments=all_texts, rhyme="none", tags=tags)
        sl = res["shortlist"]
        assert sl, "тема не должна убивать выдачу"
        n_literal = sum(1 for r in sl if r["text"] in literal)
        n_semantic = sum(1 for r in sl if r["text"] in semantic)
        n_irrelevant = sum(1 for r in sl if r["text"] in irrelevant)
        # без схемы строфа = 4 (FREE_CHUNK), shortlist=12 → лимит = round(12/4) = 3
        assert n_literal <= 3, f"буквальных совпадений {n_literal} > лимита 3 — запихивание вернулось"
        assert n_semantic >= 1, "смысловые совпадения не попали в выдачу — тема не захватывается через окружение"
        assert (n_literal + n_semantic) > n_irrelevant, "нерелевантные строки обогнали релевантные по рангу"
    finally:
        filters._NL_RHYME = old_rhyme


def test_select_with_rhyme_avoids_lemma_repeat_within_stanza():
    """Найдено владельцем вживую 2026-07-18 (скриншот): «Два гонорара» /
    «получил два чека» / «Вот два чека» — «чек» дважды в одной строфе абаб,
    хотя `_select_with_rhyme` (АКТИВНЫЙ путь при схеме — дефолт приложения,
    "абаб") про повторы вообще не знал, только про рифму и балл. Первая
    версия фикса (жёсткий фильтр по недавним леммам) не хватило: якорь
    рифмо-группы проходил по одному лишь count(бакета)>=2, не проверяя,
    отличается ли хоть один партнёр по лемме — а nl-рифмо-бакеты часто
    ЦЕЛИКОМ состоят из вырезок одного предложения (cutter.py), которые
    рифмуются между собой, но повторяют друг друга по смыслу. Сценарий:
    рифмо-бакет "ека" — сплошь "чек"; бакет "еха" — рифмуется, но лемма-
    отличен. Схема должна выбрать "еха", не "ека", даже при равном score."""
    def row(text, rhyme_key):
        return {"text": text, "template": "nakedlunch", "rhyme": rhyme_key,
                "rhyme_span": None, "score": 0.6, "_lem": set(lemmatize(text)),
                "classic": False}

    candidates = [
        row("Вот два чека", "ека"),
        row("получил два чека", "ека"),
        row("отдал ей чек", "ека"),      # бакет "ека" целиком про "чек" — партнёра без повтора нет
        row("плакал от смеха", "еха"),
        row("выпил без спеха", "еха"),   # бакет "еха" — рифмуется, лемма-отличен
    ]
    out = filters._select_with_rhyme(candidates, "аа", 2, precision=0.0)
    assert len(out) == 2
    lem0, lem1 = out[0]["_lem"], out[1]["_lem"]
    assert not (lem0 & lem1), f"строфа содержит повтор леммы: {lem0 & lem1} — {[r['text'] for r in out]}"
    assert out[0]["rhyme"] == "еха", f"выбран бакет с повтором вместо лемма-отличного: {out}"


def test_forced_word_hard_guarantee():
    """!слово (PLAN.md 0.2b, реализовано 2026-07-17) — владелец: «!слово...
    это обязательный показ именно этого слова в одной из строк если в базе
    есть это слово». В отличие от обычной темы (0.2a: ≈1 на строфу,
    вероятностно), forced-слово — ГАРАНТИЯ, проверяется на уже собранном
    шорт-листе, а не через score. Три исхода: уже есть → не трогаем; есть
    подходящий кандидат, но естественно не выбран → принудительно
    вставляем; кандидатов нет вообще → честное 'missing', БЕЗ тихой
    подмены на что попало."""
    def row(text, rhyme_key=""):
        return {"text": text, "template": "nakedlunch", "rhyme": rhyme_key,
                "rhyme_span": None, "score": 0.6, "_lem": set(lemmatize(text)),
                "classic": False}

    # (1) слово уже есть буквально в выдаче — ничего не меняем
    shortlist = [row("деньги решают всё"), row("иду домой пешком")]
    before = list(shortlist)
    notice = filters._ensure_forced(shortlist, {"деньги"},
                                    {"деньги": [row("запасной вариант")]}, "none", 0.0)
    assert notice == {"деньги": "ok"}
    assert shortlist == before, "слово уже было — форсить вставку не нужно"

    # (2) кандидат есть, но естественным отбором не выбран — вставляем силой
    shortlist = [row("иду домой пешком"), row("дождь идёт весь день")]
    candidate = row("у меня много денег")
    notice = filters._ensure_forced(shortlist, {"денег"}, {"денег": [candidate]}, "none", 0.0)
    assert notice == {"денег": "ok"}
    assert candidate in shortlist, "доступный кандидат не был вставлен"

    # (3) слова нет в базе вообще — честное 'missing', БЕЗ тихой подмены
    shortlist = [row("иду домой пешком")]
    before = list(shortlist)
    notice = filters._ensure_forced(shortlist, {"биткоин"}, {"биткоин": []}, "none", 0.0)
    assert notice == {"биткоин": "missing"}
    assert shortlist == before, "при отсутствии слова выдача не должна тихо меняться"

    # (4) со схемой: вставка обязана сохранить рифму — берёт кандидата,
    # который РИФМУЕТСЯ с партнёром по группе, а не первого попавшегося
    scheme = "аа"
    shortlist = [row("белый снег идёт", "эт"), row("на пустой обед", "эт")]
    bad_cand = row("много было денег", "эг")       # не рифмуется с группой "эт"
    good_cand = row("у меня совсем нет денег", "эт")  # рифмуется
    notice = filters._ensure_forced(shortlist, {"денег"}, {"денег": [bad_cand, good_cand]}, scheme, 0.0)
    assert notice == {"денег": "ok"}
    assert good_cand in shortlist and bad_cand not in shortlist, \
        "вставился рифмующийся кандидат, а не первый в списке"

    # (5) со схемой, но ни один кандидат не рифмуется — гарантия честно не выполнена,
    # схема остаётся целой (ничего не сломано вставкой не в рифму)
    shortlist = [row("белый снег идёт", "эт"), row("на пустой обед", "эт")]
    before = list(shortlist)
    only_bad = row("много было денег", "эг")
    notice = filters._ensure_forced(shortlist, {"денег"}, {"денег": [only_bad]}, scheme, 0.0)
    assert notice == {"денег": "unrhymed"}
    assert shortlist == before, "не найдя рифмующегося кандидата, схему ломать нельзя"


def test_typographic_punctuation_does_not_eat_words():
    """Найдено спайком 2026-07-17 на реальных данных: 75 из 2406 строк владельца
    теряли слова ЦЕЛИКОМ, потому что `lemmatize` не снимала «…» и короткое «–».
    Сценарий, а не функция: строка с типографской пунктуацией должна давать те
    же леммы, что и без неё — иначе тема, тавтология и разнообразие соседей
    молча считаются по обрезанному множеству."""
    assert lemmatize("ночь…") == lemmatize("ночь") == ["ночь"]
    assert lemmatize("морфия…") == ["морфий"]
    assert lemmatize("ночь – день") == lemmatize("ночь день") == ["ночь", "день"]
    # длинное тире работало и раньше — не сломали
    assert lemmatize("ночь — день") == ["ночь", "день"]


def test_scheme_typed_in_latin_or_digits_is_the_same_rhyme():
    """Владелец: «возможность прописывать её цифрами и латиницей» (PLAN.md 0.6).
    Сценарий, а не функция: набранная латиницей/цифрами схема должна давать ТУ ЖЕ
    рифмовку, что кириллицей — до 2026-07-17 `aabb` молча превращалось в "none"
    (некириллица проваливала _SCHEME_RE), то есть поле съедало ввод и выдавало
    выдачу вообще без рифмы."""
    assert clean.rhyme_scheme("aabb") == clean.rhyme_scheme("аабб") == "аабб"
    assert clean.rhyme_scheme("1212") == clean.rhyme_scheme("абаб") == "абаб"

    # Смысл схемы — какие ПОЗИЦИИ рифмуются (см. filters._rhyme_scheme_groups),
    # а не какими буквами это записано. Проверяем именно группы позиций.
    assert filters._rhyme_scheme_groups(clean.rhyme_scheme("abba")) == \
           filters._rhyme_scheme_groups("абба")

    # И до реальной выдачи: латинская схема реально рифмует, а не тихо отключается.
    tags = clean.theme("ночь, город, холод")
    lines = generate.generate(tags, n=2000, seed=3)
    res = filters.run(lines, clean.knobs({"shortlist": 8}), Corpus(),
                      rhyme=clean.rhyme_scheme("abab"))
    assert res["shortlist"], "латинская схема не должна убивать выдачу"

    # Чистую кириллицу не трогаем: «баба» остаётся «бабой», а не канонизируется
    # в «абаб» — иначе поле спорило бы с владельцем на полуслове.
    assert clean.rhyme_scheme("баба") == "баба"


def test_cohesion_percentile_spans_the_whole_range():
    """Найдено владельцем вживую 2026-07-18 (тема «секс», ползунок 50→55%):
    «разница в выдаче огромная и очень резкая». Причина — `theme_pull` был
    ПОЛОЖИТЕЛЬНЫМ МНОЖИТЕЛЕМ на монотонную функцию sem, а сортировка
    инвариантна к умножению на любую положительную константу: cohesion=0.55
    и cohesion=1.00 давали ОДИНАКОВЫЙ топ (измерено: 7/8 пересечение,
    идентичная четвёрка лидеров) — вся шкала 0.55..1.00 была ОДНИМ исходом,
    вся 0.00..0.45 — другим, 0.50 — подбрасыванием монеты. Сценарий:
    синтетический пул с явным градиентом релевантности (буквальный /
    смысловой / нейтральный / противоположный); перцентиль-таргет
    (2026-07-18) должен реально сдвигать топ на КАЖДОМ шаге, не только на
    полюсах."""
    literal = [f"деньги решают {i}" for i in range(6)]
    semantic = [f"заплатил наличными за {i}" for i in range(6)]
    neutral = [f"дождь шёл всю ночь {i}" for i in range(6)]
    opposite = [f"бедность и нищета кругом {i}" for i in range(6)]
    all_texts = literal + semantic + neutral + opposite

    fake_rhyme = {t: {"banal": 3.0, "taut": False, "lemmas": lemmatize(t),
                      "tokens": list(nlbridge._tokens(t)), "key": "", "span": None}
                 for t in all_texts}
    old_rhyme = filters._NL_RHYME
    filters._NL_RHYME = fake_rhyme
    old_cache = dict(filters._strict_score_cache)
    old_order = list(filters._strict_score_cache_order)
    filters._strict_score_cache.clear()
    filters._strict_score_cache_order.clear()
    try:
        tags = clean.theme("деньги")

        def top_texts(cohesion, n=6):
            knobs = clean.knobs({"shortlist": n, "real_text": 1.0, "cohesion": cohesion})
            res = filters.run([], knobs, Corpus(), nl_fragments=all_texts, rhyme="none", tags=tags)
            return [r["text"] for r in res["shortlist"]]

        seen = set()
        for c in (0.0, 0.25, 0.5, 0.75, 1.0):
            cur = top_texts(c)
            key = tuple(sorted(cur))
            assert key not in seen, (
                f"cohesion={c} дал ТОТ ЖЕ топ, что уже видели на другом полюсе — "
                f"крутилка снова трёхпозиционная, не непрерывная: {cur}")
            seen.add(key)

        # На верхнем полюсе — однозначный, проверяемый результат по содержанию:
        # консонанс обязан реально подтягивать релевантное (буквальное/смысловое),
        # не просто "отличаться от других полюсов".
        top_consonant = set(top_texts(1.0, n=6))
        assert top_consonant & set(literal + semantic), "консонанс не подтянул ничего релевантного"
    finally:
        filters._NL_RHYME = old_rhyme
        filters._strict_score_cache.clear()
        filters._strict_score_cache.update(old_cache)
        filters._strict_score_cache_order[:] = old_order


@нет_векторов
def test_theme_anchor_present_on_topic_and_not_a_duplicate():
    """Владелец (2026-07-18): «даже при диссонансе должна быть строка которая
    точно в тему по запросу одна чтоб с ней диссонировать, а консонирующие ни
    в коем случае не должны быть идентичными основной но быть рядом... ни
    одна строка не должна быть похожа на константную запрашиваемую». Сценарий:
    синтетическая строфа (схема "аа", 2 позиции — один rhyme-бакет), пул с
    ОДНИМ буквальным по теме кандидатом и несколькими нейтральными в том же
    бакете. Якорь обязан: (1) существовать per стрfoфа, (2) быть буквальным
    совпадением (единственный кандидат с реальной релевантностью), (3) рифмоваться
    со своим партнёром по схеме."""
    # Разные последние слова (_rhymes исключает совпадение по ПОСЛЕДНЕМУ слову
    # как повтор, не рифму — см. filters._rhymes), но ОДИН rhyme-ключ, чтобы
    # реально рифмоваться друг с другом.
    theme_line = "деньги решают всё вокруг"
    others = ["дождь идёт всю ночь без звука", "снег лежит везде без стука", "птицы кружат тут без плуга"]
    all_texts = [theme_line] + others

    fake_rhyme = {t: {"banal": 3.0, "taut": False, "lemmas": lemmatize(t),
                      "tokens": list(nlbridge._tokens(t)), "key": "уга", "span": None}
                 for t in all_texts}
    old_rhyme = filters._NL_RHYME
    filters._NL_RHYME = fake_rhyme
    old_cache = dict(filters._strict_score_cache)
    old_order = list(filters._strict_score_cache_order)
    filters._strict_score_cache.clear()
    filters._strict_score_cache_order.clear()
    try:
        tags = clean.theme("деньги")
        knobs = clean.knobs({"shortlist": 2, "real_text": 1.0, "cohesion": 0.0})
        res = filters.run([], knobs, Corpus(), nl_fragments=all_texts, rhyme="аа", tags=tags)
        sl = res["shortlist"]
        assert len(sl) == 2, f"строфа должна собраться из 2 строк: {sl}"
        anchors = [r for r in sl if r.get("anchor")]
        assert len(anchors) == 1, f"должен быть РОВНО один якорь на строфу: {sl}"
        assert anchors[0]["text"] == theme_line, (
            f"якорь обязан быть строкой, точно попадающей в тему, даже при диссонансе: {anchors[0]}")
        other = [r for r in sl if not r.get("anchor")][0]
        assert filters._rhymes(anchors[0], other, knobs["rhyme_precision"]), \
            "якорь обязан рифмоваться со своим партнёром по схеме, как обычная строка"
    finally:
        filters._NL_RHYME = old_rhyme
        filters._strict_score_cache.clear()
        filters._strict_score_cache.update(old_cache)
        filters._strict_score_cache_order[:] = old_order


def test_all_grammar_templates_actually_produce_output():
    """Найдено владельцем вживую 2026-07-19 (скриншот: 14 строк алгоритма,
    почти все adj_noun/noun_and_noun — «постоянное и», «нет более сложных
    конструкций с несколькими частями речи»). Причина не в дизайне
    (недостаточно шаблонов), а в баге: `_verb_past` строил ключ поиска
    {"past", "sing", gender} для единственного числа, а offline-таблица
    (tools/build_forms.py) хранит формы БЕЗ "sing" в ключе ("masc|past", не
    "masc|past|sing" — род уже подразумевает ед.ч. у прошедшего времени в
    русском). Каждый запрос ед.ч. промахивался мимо таблицы — verb_prep_np
    не собирался НИ РАЗУ (0/3375 в живом прогоне), adj_noun_verb и
    noun_verb_prep_np выживали только на тех ~25% черновиков, что случайно
    попадали на множественное число.

    Позже владелец попросил ещё разнообразия, «в том числе неровных как
    неровная обрезка в кат апе» — добавлены 6 «рваных» шаблонов
    (verb_prep_obryv/kotory_obryvok/sravnenie_obryv/dva_glagola/
    soyuz_nachalo/dlinnaya_tsepochka, 2026-07-19), намеренно НЕзакрытых
    грамматически (висящий предлог, придаточное без главного, оборванное
    сравнение). Сценарий: собрать много строк каждого из ВСЕХ шаблонов
    напрямую — каждый должен реально порождать текст, не только «простые»."""
    rng = generate.random.Random(7)
    pool = generate._theme_pool([])
    hits = {name: 0 for name in generate.TEMPLATES}
    for _ in range(3000):
        for name in generate.TEMPLATES:
            if generate._build(name, rng, pool) is not None:
                hits[name] += 1
    dead = [name for name, n in hits.items() if n == 0]
    assert not dead, f"шаблоны совсем не порождают текст: {dead} — {hits}"
    weak = [name for name, n in hits.items() if n < 3000 * 0.5]
    assert not weak, f"шаблоны срабатывают заметно реже остальных: {weak} — {hits}"


def test_stanza_syllable_length_prefers_but_never_beats_rhyme():
    """Конструктор строф (PLAN.md 0.7) — владелец: «выбор минимального и
    максимального количества слогов в каждой строке», и на прямой вопрос
    «если для позиции не находится кандидата нужной длины, чем жертвовать в
    последнюю очередь» — «рифма важнее». Два сценария: (1) длина
    предпочитается, когда рифма выполнима любым кандидатом — короткая строка
    нужной длины должна победить более длинные варианты той же рифмы;
    (2) когда только ОДИН рифмо-бакет реально имеет достаточно партнёров для
    рифмовки (второй бакет — единственный кандидат нужной длины, без пары),
    схема обязана выбрать рифмующуюся пару, даже вопреки длине."""
    def row(text, rhyme_key, syl):
        return {"text": text, "template": "grammar", "rhyme": rhyme_key,
                "rhyme_span": None, "score": 0.6, "_lem": set(lemmatize(text)),
                "classic": False, "syllables": syl}

    # (1) длина побеждает, когда рифма выполнима любым из трёх лемма-отличных
    # кандидатов одного бакета — должна выбраться строка нужной длины (5-6).
    candidates = [row("гулял по лесу долго и упрямо", "ад", 15),
                  row("веселый сад", "ад", 6),
                  row("прыгал через ямы напролом", "ад", 14)]
    out = filters._select_with_rhyme(candidates, "аа", 2, precision=0.0,
                                     syllable_spec=[(5, 6), (5, 6)])
    assert any(r["syllables"] == 6 for r in out), \
        f"строка нужной длины была доступна, но не выбрана: {[(r['syllables'], r['text']) for r in out]}"

    # (2) только бакет "ад" реально рифмуется (2 лемма-отличных партнёра);
    # бакет "юк" — единственный кандидат нужной длины, партнёра для рифмы нет.
    # Рифма обязана победить, даже ценой длины.
    candidates2 = [row("шел он долго вдоль дороги позабытой напрочь", "ад", 20),
                   row("плыл он мимо острова того же самого", "ад", 18),
                   row("хороший день", "юк", 5)]
    out2 = filters._select_with_rhyme(candidates2, "аа", 2, precision=0.0,
                                      syllable_spec=[(5, 6), (5, 6)])
    assert out2[0]["rhyme"] == out2[1]["rhyme"] == "ад", \
        f"рифма должна была победить длину: {[(r['rhyme'], r['syllables'], r['text']) for r in out2]}"


def test_syllable_reserve_survives_the_score_cap():
    """Найдено владельцем вживую 2026-07-19 (скриншот Онегинской строфы):
    NL_SELECT_CAP резал nl_survivors по COHESION-баллу ДО того, как
    syllable_spec вообще успевал заглянуть в пул — так строка нужной длины
    и рифмы могла реально существовать (859 подходящих «ом»-кандидатов), но
    ни разу не проходила отбор, потому что не входила в топ по баллу.
    `_syllable_reserve` должна вытаскивать кандидата нужной длины ДАЖЕ с
    низким баллом — сценарий: 50 «шумных» кандидатов с высоким баллом вне
    диапазона длины, и один единственный низкобалльный кандидат нужной
    длины в ТОМ ЖЕ рифмо-бакете — реестр обязан его сохранить."""
    def row(text, rhyme_key, syl, score):
        return {"text": text, "template": "nakedlunch", "rhyme": rhyme_key,
                "rhyme_span": None, "score": score, "_lem": set(lemmatize(text)),
                "classic": False, "syllables": syl}

    noise = [row(f"шумная строка номер {i} вне диапазона длины совсем", "ом", 20, 0.9)
             for i in range(50)]
    buried = row("тихий одинокий дом", "ом", 8, 0.1)   # низкий балл, нужная длина
    pool = noise + [buried]
    reserved = filters._syllable_reserve(pool, [(8, 9)] * 2)
    assert any(r["text"] == buried["text"] for r in reserved), \
        f"низкобалльный кандидат нужной длины потерян реестром: {[r['score'] for r in reserved]}"


def test_splice_fills_a_too_short_slot_with_a_rhyming_tail():
    """Идея владельца 2026-07-19: «когда не достает слогов в строку —
    добавлять доп строку ту которая по количеству слогов и по рифме
    подходит». Позиция 2 схемы "аа" может получить нужную длину только
    склейкой: единственный кандидат её рифмо-бакета короче диапазона, но
    рядом есть посторонний «филлер» ровно нужной остаточной длины."""
    def row(text, rhyme_key, syl, lem):
        return {"text": text, "template": "nakedlunch", "rhyme": rhyme_key,
                "rhyme_span": [len(text) - 2, len(text)], "score": 0.6,
                "_lem": set(lem), "classic": False, "syllables": syl}

    anchor = row("первая строка нужной длины", "ад", 9, {"первый", "строка", "нужный", "длина"})
    short_tail = row("вечный лад", "ад", 3, {"вечный", "лад"})
    filler = row("тихий сад цветет", "юк", 5, {"тихий", "сад", "цвести"})
    # nl_positions={0,1}: both slots want "nl"-kind candidates, matching these
    # nakedlunch-template rows — without it want_kind defaults to "grammar"
    # and require_slot=True (used inside the repair's own tail/head search)
    # would reject every candidate here regardless of length.
    out = filters._select_with_rhyme([anchor, short_tail, filler], "аа", 2, nl_positions={0, 1},
                                     precision=0.0, syllable_spec=[(8, 9), (8, 9)])
    assert len(out) == 2, f"ожидались 2 строки: {out}"
    second = out[1]
    assert second.get("spliced"), f"вторая строка должна была получиться склейкой: {second}"
    assert 8 <= second["syllables"] <= 9, f"склейка не попала в диапазон: {second}"
    assert second["rhyme"] == "ад", f"склейка потеряла нужную рифму: {second['rhyme']}"
    assert "лад" in second["text"], f"склейка потеряла исходный короткий вариант: {second['text']}"


def test_trim_shortens_an_overlong_candidate_without_touching_the_rhyme():
    """Идея владельца 2026-07-19: «слишком длинные строки — отрезать самые
    незначимые слова оттуда». Единственный кандидат позиции 2 (25 слогов)
    сильно превышает диапазон 8-9 — механизм должен обрезать ведущие слова,
    никогда не трогая последнее (рифмующееся) слово."""
    anchor_text = "первая строка нужной длины"
    overlong_text = "утренний свет упал совсем случайно на старые холсты и на седые вершины"

    def entry(text, key):
        tokens, lemmas = [], []
        for w in text.split():
            lm = lemmatize(w)
            if lm:
                tokens.append(w.lower())
                lemmas.append(lm[0])
        return {"banal": 3.0, "taut": False, "lemmas": lemmas, "tokens": tokens,
                "key": key, "span": [len(text) - len(key), len(text)]}

    fake_rhyme = {anchor_text: entry(anchor_text, "ины"), overlong_text: entry(overlong_text, "ины")}
    old_rhyme = filters._NL_RHYME
    filters._NL_RHYME = fake_rhyme
    try:
        def row(text):
            e = fake_rhyme[text]
            return {"text": text, "template": "nakedlunch", "rhyme": e["key"],
                    "rhyme_span": e["span"], "score": 0.6, "_lem": set(e["lemmas"]),
                    "classic": False, "syllables": sum(1 for ch in text.lower() if ch in filters.VOWELS)}

        anchor, overlong = row(anchor_text), row(overlong_text)
        out = filters._select_with_rhyme([anchor, overlong], "аа", 2, nl_positions={0, 1},
                                         precision=0.0, syllable_spec=[(8, 9), (8, 9)])
        assert len(out) == 2, f"ожидались 2 строки: {out}"
        second = out[1]
        assert second.get("trimmed"), f"вторая строка должна была получиться обрезкой: {second}"
        assert 8 <= second["syllables"] <= 9, f"обрезка не попала в диапазон: {second}"
        assert second["text"].split()[-1] == "вершины", \
            f"обрезка тронула рифмующееся (последнее) слово: {second['text']}"
        assert second["rhyme"] == "ины", f"обрезка потеряла рифмо-ключ: {second['rhyme']}"
    finally:
        filters._NL_RHYME = old_rhyme


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("\nall real-path tests passed")
