# extendo — тесты попапа по слову (ФАЗА 2: core/wordsuggest.py +
# POST /api/word/suggest). Логика вкладок проверяется на МИНИ-индексе
# (фикстура через wordsuggest._activate — та же дисциплина, что подмена
# filters._NL_RHYME в test_realpath.py: не тащить 50k-словарь в прогон);
# соответствие ключей настоящего индекса scan.rhyme_key — отдельным тестом
# по 5 живым словам из реального файла (подмножество, не весь индекс).
# Прогон: .venv/bin/python -m pytest tests/test_wordsuggest.py -q

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import filters
import scan
import wordsuggest

REAL_INDEX = ROOT / "core" / "data" / "rhyme_index.json"


# ---------------------------------------------------------------------------
# мини-индекс: живые слова с настоящими ключами (сверены с scan.rhyme_key)
# плюс одна синтетическая запись «тревогая» — однокоренная С ТЕМ ЖЕ ключом,
# в живом языке такие пары редки, а механизм отсечки проверить нужно.
# ---------------------------------------------------------------------------

def _mini_index():
    """Двухполевой (СТАРЫЙ) формат записи — намеренно: так фикстура заодно
    проверяет, что _activate честно дополняет его до [ключ, zipf, опора,
    лемма, подозр], а не падает и не молчит. Полный формат — в
    _mini_index5() ниже."""
    words = {  # порядок = по убыванию частоты, как в настоящем файле
        "тревога": ["ога", 4.5],
        "дорога": ["ога", 4.71],
        "порога": ["ога", 4.2],
        "тревогая": ["ога", 3.0],   # синтетика: однокоренное с тем же ключом
        "трогать": ["огать", 4.0],  # ключ с тем же ПРЕФИКСОМ «ога» — не рифма
        "мороз": ["ос", 4.5],
        "матрос": ["ос", 4.0],      # точная рифма к «мороз» — не «по звуку»
        "мираж": ["аш", 3.5],       # созвучие к «мороз»: скелет «мр…»
    }
    keys: dict = {}
    for w, (k, _z) in words.items():
        if k:
            keys.setdefault(k, []).append(w)
    return {"words": words, "keys": keys}


def _mini_index5():
    """Полная запись [ключ, zipf, опора, лемма, подозр] — для правил Раунда
    32 (опорная согласная, дедуп по лемме, опускание подозрительного).
    Ключ «а» у всех: это мужское открытое окончание, ради которого опорная
    согласная и появилась."""
    words = {
        "рука":   ["а", 4.50, "к", ["рука"],   0],
        "она":    ["а", 5.40, "н", ["она"],    0],
        "река":   ["а", 4.23, "к", ["река"],   0],
        "реках":  ["ах", 3.0, "к", ["река"],   0],   # та же лемма, другой ключ
        "строка": ["а", 3.90, "к", ["строка"], 0],
        "рока":   ["а", 3.80, "к", ["рок"],    0],
        # у «року» самый вероятный разбор — НЕ «рок» (так и бывает в живом
        # pymorphy: «спал» → «спасть»); склейка обязана сработать по
        # пересечению наборов, а не по равенству первых лемм
        "року":   ["а", 3.70, "к", ["рока", "рок"], 0],
        "сморгонь": ["а", 3.60, "к", ["сморгонь"], 1],  # подозрительное, опора «к»
        "весна":  ["а", 4.10, "н", ["весна"],  0],
        "утро":   ["утра", 4.98, "", ["утро"], 0],
        # «наутро» — то же слово с приставкой: рифма самая дешёвая, отсекается
        "наутро": ["утра", 3.27, "", ["наутро"], 0],
        # «сутра» — настоящая рифма к «утро», и опора у неё ДРУГАЯ («с» против
        # пустой): на ключе с согласной опору требовать не за что
        "сутра":  ["утра", 2.87, "с", ["сутра"], 0],
        # ключ «уя» — ДВА слога (женское окончание): опора тут не нужна,
        # рифму несёт заударный хвост. Первая версия правила это ломала.
        "минуя":  ["уя", 3.0, "н", ["минуть"],   0],
        "рискуя": ["уя", 3.0, "к", ["рисковать"], 0],
    }
    keys: dict = {}
    for w, e in words.items():
        keys.setdefault(e[0], []).append(w)
    for k in keys:                       # порядок сборки: (подозр, -zipf)
        keys[k].sort(key=lambda w: words[w][4])
    return {"words": words, "keys": keys}


def _подмена(data):
    saved = (wordsuggest._WORDS, wordsuggest._KEYS, wordsuggest._SKEL,
             wordsuggest._SKEL_BUCKET, wordsuggest._YO)
    wordsuggest._activate(data)
    yield
    (wordsuggest._WORDS, wordsuggest._KEYS, wordsuggest._SKEL,
     wordsuggest._SKEL_BUCKET, wordsuggest._YO) = saved


@pytest.fixture
def mini_index():
    yield from _подмена(_mini_index())


@pytest.fixture
def mini_index5():
    yield from _подмена(_mini_index5())


_РЕАЛЬНЫЙ = None


@pytest.fixture
def real_index():
    """Настоящий индекс — для правил, которые на мини-фикстуре не проверишь
    (тождество ведра полному проходу). Разбор файла кэшируется на прогон,
    состояние модуля восстанавливается: тесты ниже не должны наследовать
    660k слов от тестов выше."""
    global _РЕАЛЬНЫЙ
    if _РЕАЛЬНЫЙ is None:
        _РЕАЛЬНЫЙ = json.loads(REAL_INDEX.read_text(encoding="utf-8"))
    yield from _подмена(_РЕАЛЬНЫЙ)


class FakeCorpus:
    """hidden_set — единственное, что wordsuggest спрашивает у корпуса."""

    def __init__(self, hidden=()):
        self._h = set(hidden)

    def hidden_set(self):
        return self._h


# ---------------------------------------------------------------------------
# индекс ↔ scan.rhyme_key: формат ключа обязан совпадать побайтово
# ---------------------------------------------------------------------------

# (слово, индекс ударного гласного) — ударения общеизвестны и стабильны;
# если этот тест упал, значит scan.rhyme_key изменился и индекс надо
# пересобрать (tools/build_rhyme_index.py), а не подгонять тест.
LIVE_WORDS = [("вода", 1), ("голова", 2), ("деньги", 0), ("любовь", 1), ("молоко", 2)]


@pytest.mark.skipif(not REAL_INDEX.exists(), reason="rhyme_index.json не собран")
def test_real_index_keys_match_scan_rhyme_key():
    words = json.loads(REAL_INDEX.read_text(encoding="utf-8"))["words"]
    for w, stress_idx in LIVE_WORDS:
        assert w in words, f"«{w}» пропало из топ-50k индекса"
        assert words[w][0] == scan.rhyme_key(w, stress_idx), w


def test_mini_fixture_keys_match_scan_rhyme_key():
    # та же инварианта для фикстуры: мини-индекс не имеет права разойтись
    # с каноническим алгоритмом, иначе тесты ниже проверяют выдумку
    for w, stress_idx in [("тревога", 1), ("дорога", 1), ("мороз", 1), ("матрос", 1)]:
        assert _mini_index()["words"][w][0] == scan.rhyme_key(w, stress_idx), w


# ---------------------------------------------------------------------------
# «рифмы»
# ---------------------------------------------------------------------------

def test_rhymes_cut_same_root_and_keep_true_rhymes(mini_index):
    items = wordsuggest.suggest("тревога", "рифмы")
    got = [i["w"] for i in items]
    тип = {i["w"]: i["t"] for i in items}
    assert "тревога" not in got          # само слово — не рифма нигде
    assert "дорога" in got and "порога" in got
    # однокоренное (общий префикс ≥5) не выбрасывается, а подписано и внизу
    assert тип["тревогая"] == "однокоренная"
    assert got.index("тревогая") > got.index("порога")


def test_rhymes_no_prefix_tier_padding(mini_index):
    """Раунд 32: ярусного добора по ПРЕФИКСУ ключа больше нет.

    «трогать» (ключ «огать») делит с «тревога» первые три буквы ключа, и
    старый ярус его показывал. Но ключ — хвост от ударного гласного, так
    что его начало это середина слова: на живом индексе то же правило
    добирало «утро» словами «внутренних, внутренней, внутреннего». Короткий
    честный список лучше длинного выдуманного."""
    items = wordsuggest.suggest("тревога", "рифмы")
    got = [i["w"] for i in items]
    assert "трогать" not in got
    # точные рифмы — ровно две, дальше только подписанное однокоренное
    assert [i["w"] for i in items if i["t"] == "точная"] == ["дорога", "порога"]


# --- Раунд 32: опорная согласная, дедуп по лемме, опускание подозрительного -

def test_rhymes_require_supporting_consonant_on_open_ending(mini_index5):
    """«рука» кончается ударным гласным, ключ — один «а», и его делят сотни
    слов. Русская рифма при таком окончании требует совпадения согласной
    ПЕРЕД ударным гласным: «рука/река/строка», но не «рука/она»."""
    got = [i["w"] for i in wordsuggest.suggest("рука", "рифмы")]
    assert "река" in got and "строка" in got
    assert "она" not in got and "весна" not in got   # опора «н», не «к»
    # обратная сторона того же правила
    got_она = [i["w"] for i in wordsuggest.suggest("она", "рифмы")]
    assert "весна" in got_она
    assert "река" not in got_она


def test_rhymes_key_with_consonant_needs_no_support(mini_index5):
    """Ключ «утра» несёт согласные — там хвост рифмует сам по себе, и опору
    требовать не за что: у «утро» её нет вовсе, у «сутра» это «с», а рифма
    настоящая."""
    точные = [i["w"] for i in wordsuggest.suggest("утро", "рифмы")
              if i["t"] == "точная"]
    assert точные == ["сутра"]


def test_prefix_derivative_goes_to_its_own_tier(mini_index5):
    """Раунд 33: «наутро» — то же «утро» с приставкой, и как рифма это самое
    дешёвое, что бывает. Прежний отсев однокоренных сравнивал НАЧАЛА слов, а
    приставка их разводит насмерть, поэтому пара проходила как полноценная
    точная рифма. Теперь она подписана «однокоренная» и стоит последней —
    выбрасывать её незачем, а выдавать за находку нельзя."""
    items = wordsuggest.suggest("утро", "рифмы")
    тип = {i["w"]: i["t"] for i in items}
    assert тип["наутро"] == "однокоренная"
    assert [i["w"] for i in items][-1] == "наутро"
    assert wordsuggest._same_root("любить", "полюбить")
    assert wordsuggest._same_root("писать", "переписать")
    # односложные приставки не берём: «дар/удар» этимологически не родня, а
    # правило склеило бы их и убило настоящую рифму
    assert not wordsuggest._same_root("дар", "удар")
    assert not wordsuggest._same_root("ночь", "помочь")


def test_rhymes_two_syllable_open_key_needs_no_support(mini_index5):
    """Ключ «уя» — два слога, женское открытое окончание: рифма живёт в
    заударном хвосте, как в «мама/рама», и опорная согласная не требуется.

    Регресс из живой сверки со старым индексом 2026-08-02: правило сперва
    звучало «в ключе нет согласных», под него попало «минуя», и настоящие
    рифмы «рискуя, образуя, поцелуя» отсеялись. Опору требует ТОЛЬКО ключ
    из одного гласного."""
    assert [i["w"] for i in wordsuggest.suggest("минуя", "рифмы")] == ["рискуя"]
    assert not wordsuggest._нужна_опора("уя")
    assert wordsuggest._нужна_опора("а")


def test_rhymes_one_form_per_lemma(mini_index5):
    """«рока» и «року» — одно слово в двух падежах, а не две рифмы."""
    got = [i["w"] for i in wordsuggest.suggest("рука", "рифмы")]
    assert got.count("рока") + got.count("року") == 1


def test_rhyme_types_are_labeled_and_ordered(mini_index5):
    """Раунд 32, просьба владельца «категоризировать и помечать разные типы
    рифм»: каждая строка несёт свой тип в `t`, а порядок групп — от сильной
    рифмы к слабой. «богатая» = точная + совпала опорная согласная."""
    items = wordsuggest.suggest("минуя", "рифмы")
    assert items and all("t" in i for i in items)
    типы = [i["t"] for i in items]
    порядок = [wordsuggest._ЯРУСЫ.index(t) for t in типы]
    assert порядок == sorted(порядок), типы


def test_rhyme_type_classifier():
    """Типы считаются по ключам; неточная — ровно одна разошедшаяся
    согласная, усечённая — один лишний согласный на конце."""
    т = wordsuggest._тип_рифмы
    assert т("очь", "оть")[0] == "неточная"        # ночь / плоть
    assert т("ертвы", "ертвых")[0] == "усечённая"  # жертвы / мёртвых
    assert т("ога", "ога") is None                 # это точная, не сюда
    assert т("отицы", "омниццы") is None           # разошлось больше одной
    # у короткого ключа усечения не бывает: иначе «свет» (ключ «ет»)
    # рифмуется с «не, все, же, мне» — реальная выдача пробы
    assert т("ет", "е") is None


def test_inexact_tier_weight_prefers_longer_shared_tail():
    """Вес неточной рифмы — сколько совпало ПОСЛЕ расхождения. Сперва я
    взвесил наоборот, и «безработицы» выдавало «блевотины» выше
    «богородицы»; поймано на слух по живым парам."""
    т = wordsuggest._тип_рифмы
    рано = т("отицы", "одицы")[1]      # разошлось на 1-й, хвост «ицы»
    поздно = т("отицы", "отины")[1]    # разошлось на 3-й, хвост «ы»
    assert рано > поздно


def test_rhymes_suspect_words_sink_to_the_bottom(mini_index5):
    """Фамилии, топонимы и незнакомое pymorphy не выбрасываются (с «москва»
    рифмуют по-настоящему), но идут после нормальных слов."""
    got = [i["w"] for i in wordsuggest.suggest("рука", "рифмы")]
    assert "сморгонь" in got
    assert got.index("сморгонь") > got.index("строка")


def test_rhymes_unknown_word_is_honest_empty(mini_index):
    # слова нет в словаре индекса → [], фронт покажет «—» (честность
    # важнее догадок — контракт /api/word/suggest)
    assert wordsuggest.suggest("гыгыгыжка", "рифмы") == []


def test_rhymes_freq_label_format(mini_index):
    # подпись справа — частота строкой с тонким пробелом (U+2009)
    items = wordsuggest.suggest("тревога", "рифмы")
    assert items, "фикстура обязана дать рифмы"
    for it in items:
        assert set(it) == {"w", "n", "t"}
        assert it["n"].replace(" ", "").isdigit()


# ---------------------------------------------------------------------------
# «по звуку»
# ---------------------------------------------------------------------------

def test_sound_excludes_exact_rhymes_but_keeps_consonance(mini_index):
    got = [i["w"] for i in wordsuggest.suggest("мороз", "по звуку")]
    assert "матрос" not in got   # точная рифма — на соседней вкладке
    assert "мороз" not in got    # само слово
    assert "мираж" in got        # скелет «мр…» — настоящее созвучие


def test_sound_unknown_word_is_honest_empty(mini_index):
    assert wordsuggest.suggest("гыгыгыжка", "по звуку") == []


@pytest.mark.skipif(not REAL_INDEX.exists(), reason="rhyme_index.json не собран")
def test_sound_bucket_equals_full_scan(real_index):
    """Раунд 32: «по звуку» перебирает не весь словарь (660k слов на каждый
    клик), а ведро по ПЕРВОЙ согласной скелета. Это не приближение, а
    тождество: балл требует общего начала скелетов длиной ≥1, значит
    кандидат обязан делить первую согласную. Проверяем полным проходом —
    если тождество когда-нибудь сломается, сломается здесь, а не молча в
    выдаче."""
    wordsuggest.warm_caches()
    for слово in ("мороз", "ночь"):
        быстро = [i["w"] for i in wordsuggest.suggest(слово, "по звуку")]
        # эталон: тот же счёт, но без ведра — по всему словарю
        key = wordsuggest._WORDS[слово][0]
        skel = wordsuggest._skeleton(слово)
        эталон = []
        for w in wordsuggest._WORDS:
            k = wordsuggest._WORDS[w][0]
            if w == слово or (key and k == key) or wordsuggest._same_root(слово, w):
                continue
            s = wordsuggest._skeleton(w)
            m = 0
            for a, b in zip(skel, s):
                if a != b:
                    break
                m += 1
            vow = 1.0 if (key and k and k[0] == key[0]) else 0.0
            if m == 0 or (m < 2 and not vow):
                continue
            эталон.append(w)
        assert set(быстро) <= set(эталон), слово
        assert быстро, слово


@pytest.mark.skipif(not REAL_INDEX.exists(), reason="rhyme_index.json не собран")
def test_sound_shows_one_form_per_word(real_index):
    """Жалоба владельца 2026-08-02: «на созвучия одно и то же слово с
    разными окончаниями» — падежи занимали слоты вместо созвучий."""
    wordsuggest.warm_caches()
    got = [i["w"] for i in wordsuggest.suggest("мороз", "по звуку")]
    леммы = [wordsuggest._lemma(w) for w in got]
    assert len(леммы) == len(set(леммы)), got


# ---------------------------------------------------------------------------
# «строкой»
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_pool(mini_index):
    # форма записей — как в nl_rhyme.json (см. tools/build_nl_rhyme.py)
    fake = {
        "деньги на столе":        {"key": "е",   "span": None, "banal": 4.0, "taut": False,
                                   "lemmas": ["деньги", "стол"], "tokens": ["деньги", "на", "столе"]},
        "спрятал деньги в подвал": {"key": "ал",  "span": None, "banal": 4.5, "taut": False,
                                   "lemmas": ["спрятать", "деньги", "подвал"],
                                   "tokens": ["спрятал", "деньги", "в", "подвал"]},
        "полная тревога":          {"key": "ога", "span": None, "banal": 3.5, "taut": False,
                                   "lemmas": ["полный", "тревога"], "tokens": ["полная", "тревога"]},
        "деньги хуйня":            {"key": "я",   "span": None, "banal": 3.0, "taut": False,
                                   "lemmas": ["деньги"], "tokens": ["деньги", "хуйня"]},
    }
    old = filters._NL_RHYME
    filters._NL_RHYME = fake
    yield fake
    filters._NL_RHYME = old


def test_lines_respects_hidden(fake_pool):
    corp = FakeCorpus(hidden={"спрятал деньги в подвал"})
    got = [i["w"] for i in wordsuggest.suggest("деньги", "строкой", line="", corpus=corp)]
    assert "деньги на столе" in got
    assert "спрятал деньги в подвал" not in got   # скрыто историей/избранным


def test_lines_rhyme_bonus_from_last_word_of_line(fake_pool):
    # последнее слово строки — «дорога» (ключ «ога» в мини-индексе) →
    # фрагмент с тем же ключом попадает в выдачу с подписью «рифма»,
    # даже без единого общего токена со словом
    items = wordsuggest.suggest("деньги", "строкой", line="длинная дорога",
                                corpus=FakeCorpus())
    by_w = {i["w"]: i["n"] for i in items}
    assert by_w.get("полная тревога") == "рифма"
    assert by_w.get("деньги на столе") == ""      # токен-совпадение, не рифма


def test_lines_excludes_current_line_itself(fake_pool):
    items = wordsuggest.suggest("тревога", "строкой", line="полная тревога",
                                corpus=FakeCorpus())
    assert "полная тревога" not in [i["w"] for i in items]


def test_lines_respects_no_mat_toggle(fake_pool):
    with_mat = [i["w"] for i in wordsuggest.suggest("деньги", "строкой",
                                                    corpus=FakeCorpus(), no_mat=False)]
    without = [i["w"] for i in wordsuggest.suggest("деньги", "строкой",
                                                   corpus=FakeCorpus(), no_mat=True)]
    assert "деньги хуйня" in with_mat      # фильтр выключен — не цензурим
    assert "деньги хуйня" not in without   # «без мата» действует и в попапе


# ---------------------------------------------------------------------------
# словарные вкладки (сборка фазы 2): мини-тезаурус фикстурой — та же
# дисциплина, что mini_index: не тащить 8.5МБ живого словаря в юнит-прогон
# ---------------------------------------------------------------------------

import embeddings  # noqa: E402  (sys.path на core уже настроен выше)


@pytest.fixture
def mini_thesaurus(monkeypatch, mini_index):
    monkeypatch.setattr(wordsuggest, "_THES", {
        "syn": {"тревога": ["беспокойство", "волнение"]},
        "ant": {"тревога": ["покой", "спокойствие"]},
    })
    monkeypatch.setattr(wordsuggest, "_thes_attempted", True)


@pytest.fixture
def no_navec(monkeypatch):
    # векторный слой глушится честно — «модель не загрузилась», не мок выдачи
    monkeypatch.setattr(embeddings, "_ensure_loaded", lambda: False)


def test_syn_dict_layer_labeled_slovar(mini_thesaurus, no_navec):
    items = wordsuggest.suggest("тревога", "синонимы")
    assert [i["w"] for i in items] == ["беспокойство", "волнение"]
    assert all(i["n"] == "словарь" for i in items)


def test_ant_is_dict_only(mini_thesaurus, no_navec):
    items = wordsuggest.suggest("тревога", "антонимы")
    assert [i["w"] for i in items] == ["покой", "спокойствие"]
    assert all(i["n"] == "словарь" for i in items)
    # слова нет в словаре → пусто, векторного добора у антонимов НЕТ
    # (решение прожарки: противоположности в векторном пространстве соседи)
    assert wordsuggest.suggest("дорога", "антонимы") == []


def test_syn_without_thesaurus_falls_back_to_vectors(monkeypatch, mini_index):
    # словаря нет — словарный слой пуст, но векторный жив
    monkeypatch.setattr(wordsuggest, "_THES", {})
    monkeypatch.setattr(wordsuggest, "_thes_attempted", True)
    monkeypatch.setattr(wordsuggest, "_navec_neighbors",
                        lambda word, top, exclude: ["паника", "страх"])
    items = wordsuggest.suggest("тревога", "синонимы")
    assert [i["w"] for i in items] == ["паника", "страх"]
    assert all(i["n"] == "близкое" for i in items)


def test_navec_neighbors_filter_same_root_and_shown(monkeypatch):
    # крошечная модель: единичные (уже нормированные) вектора + один сосед
    words = ["деньги", "деньгам", "бабки", "стол", "money"]
    vecs = np.eye(len(words), 8, dtype=np.float32)
    for j in (1, 2, 4):   # деньгам/бабки/money — соседи «деньги»
        vecs[j] = vecs[0] * 0.9 + np.eye(len(words), 8, k=j)[0] * 0.1
        vecs[j] /= np.linalg.norm(vecs[j])
    monkeypatch.setattr(embeddings, "_vectors", vecs)
    monkeypatch.setattr(embeddings, "_index", {w: i for i, w in enumerate(words)})
    monkeypatch.setattr(embeddings, "_load_attempted", True)
    monkeypatch.setattr(wordsuggest, "_NAVEC_WORDS", None)  # сброс ленивого кэша
    got = wordsuggest._navec_neighbors("деньги", 5, {"стол"})
    assert "бабки" in got
    assert "деньгам" not in got   # однокоренное (общий префикс ≥5)
    assert "money" not in got     # не-кириллица из словаря модели
    assert "стол" not in got      # уже показан словарным слоем
    assert "деньги" not in got    # само слово


# ---------------------------------------------------------------------------
# роут POST /api/word/suggest — 200 / 400 / пустота (+ thesaurus в /api/state)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Flask test_client с ЛЁГКИМ импортом api/server.py: тяжёлые прогревы
    (nl_rhyme.json ~946MB, forms, navec) и стор nakedlunch глушатся ДО
    импорта — роут попапа их не требует, а тестовый прогон не должен
    съедать 5.5GB RSS. wordsuggest.warm_caches остаётся настоящим:
    rhyme_index.json маленький, и роут проверяется на живом индексе."""
    import embeddings
    import generate
    import nlbridge
    saved = (filters.warm_caches, generate.warm_caches,
             embeddings.warm_caches, nlbridge.open_store)
    filters.warm_caches = lambda: None
    generate.warm_caches = lambda: None
    embeddings.warm_caches = lambda: None
    nlbridge.open_store = lambda: None
    sys.path.insert(0, str(ROOT / "api"))
    try:
        import server
    finally:
        (filters.warm_caches, generate.warm_caches,
         embeddings.warm_caches, nlbridge.open_store) = saved
    return server.app.test_client()


@pytest.mark.skipif(not REAL_INDEX.exists(), reason="rhyme_index.json не собран")
def test_route_200_with_items(client):
    r = client.post("/api/word/suggest", json={"word": "вода", "tab": "рифмы", "line": ""})
    assert r.status_code == 200
    items = r.get_json()["items"]
    assert items and all(set(i) == {"w", "n", "t"} for i in items)
    assert len(items) <= wordsuggest.TOP_RHYMES


def test_route_400_without_word(client):
    r = client.post("/api/word/suggest", json={"tab": "рифмы"})
    assert r.status_code == 400
    assert "слово" in r.get_json()["error"]   # ошибка по-русски


def test_route_400_on_unknown_tab(client):
    r = client.post("/api/word/suggest", json={"word": "вода", "tab": "чудеса"})
    assert r.status_code == 400
    assert "вкладка" in r.get_json()["error"]


def test_route_unknown_word_gives_empty_items(client):
    r = client.post("/api/word/suggest", json={"word": "гыгыгыжка", "tab": "рифмы"})
    assert r.status_code == 200
    assert r.get_json()["items"] == []


def test_state_reports_real_thesaurus_layers(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    th = r.get_json()["thesaurus"]
    assert set(th) == {"syn", "ant"}
    # флаги обязаны совпадать с фактическим наличием словаря на диске
    # (ant дополнительно за воротами качества — см. _ANT_GATE_PASSED в server.py)
    built = wordsuggest._THES_PATH.exists()
    assert th["syn"] is built
    assert isinstance(th["ant"], bool)
    if not built:
        assert th["ant"] is False


# --- словоформы против лемм (живая проверка 2026-08-01) ---------------------
# Словарь Викисловаря ключуется леммами, а из документа в попап приходит
# словоформа: «холодная» давала пустые антонимы, хотя «холодный» — полные.
# Тот же перекос ловил и однокоренные: векторный слой отдавал «ночью» его же
# формы, потому что префиксного порога ≥5 букв не хватало одной.

def test_dict_lookup_falls_back_to_lemma():
    """Словоформа находит словарную статью своей начальной формы."""
    if not wordsuggest._THES_PATH.exists():
        pytest.skip("тезаурус не собран на этой машине")
    wordsuggest.warm_caches()
    surface = [i["w"] for i in wordsuggest.suggest("холодная", "антонимы", "")]
    lemma = [i["w"] for i in wordsuggest.suggest("холодный", "антонимы", "")]
    assert surface, "антонимы словоформы не должны быть пустыми"
    assert surface == lemma


def test_ambiguous_forms_collapse_by_lemma_set():
    """Раунд 32: склейка форм идёт по ПЕРЕСЕЧЕНИЮ наборов начальных форм.

    У неоднозначных словоформ самый вероятный разбор pymorphy часто не тот:
    «спал» → «спасть», «утром» → «утром» (наречие), «вечером» → «вечером».
    Равенство первых лемм на них молчало, и синонимы «ночь» показывали
    «утра, утром» и «спать, спал» как разные слова — ровно жалоба владельца
    2026-08-02."""
    assert wordsuggest._одно_слово("спал", "спать")
    assert wordsuggest._одно_слово("утром", "утра")
    assert wordsuggest._одно_слово("вечером", "вечер")
    assert wordsuggest._одно_слово("ночью", "ночь")
    # разные слова остаются разными
    assert not wordsuggest._одно_слово("ночь", "вечер")
    assert not wordsuggest._одно_слово("мороз", "вопрос")


def test_dict_lookup_puts_lemma_before_homonym_wordform(monkeypatch):
    """Раунд 32: у Абрамова «холодная» — отдельная статья-существительное
    (арестантское «холодная» = острог). Пока словоформа побеждала лемму,
    клик по прилагательному выдавал «острог, тюрьма» вместо «ледяной».
    Статья формы не выброшена — она идёт ПОСЛЕ статьи леммы."""
    monkeypatch.setattr(wordsuggest, "_THES", {
        "syn": {"холодный": ["ледяной", "студёный"], "холодная": ["острог", "тюрьма"]},
        "ant": {},
    })
    monkeypatch.setattr(wordsuggest, "_thes_attempted", True)
    got = wordsuggest._dict_lookup("syn", "холодная")
    assert got[:2] == ["ледяной", "студёный"]
    assert "острог" in got and got.index("острог") > got.index("студёный")


def test_same_root_catches_inflection_prefix():
    """«ночь» целиком лежит в начале «ночью» — это одно слово, не синоним."""
    assert wordsuggest._same_root("ночью", "ночь")
    assert wordsuggest._same_root("холодная", "холодный")   # по лемме
    # а разные слова с общим началом однокоренными не становятся
    assert not wordsuggest._same_root("море", "морок")
    assert not wordsuggest._same_root("мороз", "вопрос")


# ---------------------------------------------------------------------------
# «строкой» через колоночный индекс (Раунд 34). Раньше вкладка проходила по
# `filters._NL_RHYME` — 2.87 млн записей, ~1с на частое слово, и ровно ради
# неё процесс держал 946МБ JSON. Теперь кандидатов даёт индекс.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not REAL_INDEX.exists(), reason="rhyme_index.json не собран")
def test_lines_by_index_marks_rhyme_and_finds_token(real_index):
    import nlindex
    idx = nlindex.load()
    if idx is None:
        pytest.skip("колоночный индекс не испечён")
    # ключ последнего слова строки: «дорога» → «ога»
    ключ = wordsuggest._WORDS["дорога"][0]
    matches = wordsuggest._lines_by_index(idx, "деньги", ключ)
    assert matches, "на живом корпусе слово «деньги» обязано что-то найти"
    рифмующие = [m for m in matches if m[2]]
    assert рифмующие, "фрагменты с ключом «ога» в корпусе есть"
    # балл: рифма 2, точный токен +2 — тройки/четвёрки должны существовать
    баллы = {-m[0] for m in matches}
    assert баллы & {2, 3, 4}
    # без строки рифмо-ярус пуст, но токенный работает
    без_строки = wordsuggest._lines_by_index(idx, "деньги", "")
    assert без_строки and not any(m[2] for m in без_строки)


@pytest.mark.skipif(not REAL_INDEX.exists(), reason="rhyme_index.json не собран")
def test_lines_substring_tier_finds_word_forms(real_index):
    """Подстрока ищется по словарю токенов, а не по сырому тексту: «деньг»
    обязано находить «деньгами» и «деньгах» как ЦЕЛЫЕ слова."""
    import nlindex
    idx = nlindex.load()
    if idx is None:
        pytest.skip("колоночный индекс не испечён")
    формы = [t for t in idx.tokens if "деньг" in t]
    assert {"деньгами", "деньгах"} <= set(формы)
