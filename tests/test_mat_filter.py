# extendo — честный фильтр мата (решение прожарки PLAN.md: «"без мата"
# пишется по-честному (корни + формы)»). Ключевое требование — НОЛЬ ложных
# срабатываний на обычной речи: проверка по НАЧАЛУ токена, не substring
# («рубля» содержит «бля», «команда» — «манд», «хлеб» и «себя» — «еб»,
# «характер» — «хер» — substring-подход поймал бы их все).
# Run: .venv/bin/python -m pytest tests/test_mat_filter.py -q
#
# НАДГРОБИЕ 2026-08-29: `test_run_drops_mat_grammar_lines_only_with_flag`.
# Он стерёг ВТОРОЙ путь отсева мата — ступень 3 в `filters._run`, где рядом с
# чёрным списком и клише отсеивались строки ГРАММАТИЧЕСКОГО ГЕНЕРАТОРА
# (`if no_mat and has_mat(L.text): continue`). Строил он их руками, из
# `generate.Line`/`generate.Word`.
#
# Механизма больше нет по двум причинам сразу, и каждой хватило бы:
#   · `core/generate.py` удалён целиком — `Line`/`Word` неоткуда взять, файл
#     даже не собирался (ModuleNotFoundError на импорте);
#   · производителя у аргумента `lines` не осталось: `api/server.py` шлёт
#     `lines = []` всегда (там своё надгробие «генератор вырезан»), а в
#     `_run` шорт-лист собирается только из `nl_survivors` — грамматические
#     кандидаты до выдачи не доходят физически.
# Переписать было не на что: у ворот нет ни входа, ни выхода. Мат по строкам
# КОРПУСА стерегут `test_run_drops_mat_nl_fragments_only_with_flag` и
# `test_run_hits_requested_mat_share` ниже — они остались.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import clean
import filters
import nlbridge
from corpus import Corpus, lemmatize


# Словоформы по всем корням списка, включая ё/е-варианты и приставочные формы.
MAT = [
    "хуй", "хуйня", "хуево", "хуёво", "хуярить", "нахуй", "похуй", "охуеть",
    "пизда", "пиздец", "пиздёж", "спиздил", "напиздел", "распиздяй",
    "ебать", "еби", "ебло", "ебанутый", "ебучий", "ёбаный", "ёбнул",
    "заебись", "наебал", "уебал", "выебываться", "приебался", "доебался", "поебать",
    "отъебись", "съебаться", "разъебал", "подъебка", "объебал", "въебал",
    "бля", "блядь", "бляди", "блять",
    "сука", "суки", "сучка", "сучара",
    "мудак", "мудачьё", "мудила",
    "гандон", "гондон", "залупа", "дрочить", "дрочка", "подрочить",
    "манда", "мандой", "шлюха", "пидор", "пидорас", "пидарас", "пидрила",
    "хер", "херня", "херовый", "херачить", "похер", "похерить", "схерачить",
    "нахер", "охереть", "дохера",
    "долбоёб", "долбоеб", "елда", "курва", "трахнул", "трахаться", "трахал",
    "хули", "хуле",
]

# Обычная речь — ни одно из этих слов не должно сработать. Первая группа —
# прямые ловушки substring-подхода из задачи; дальше — исключения корней.
CLEAN = [
    "себя", "себе", "хлеб", "требует", "употребил", "употребление",
    "команда", "команд", "мандарин", "характер", "рубля",
    "бляха", "бляшка",                                    # бля- : не мат
    "мандат", "мандатный", "мандраж", "мандолина", "мандала", "мандрагора",
    "мандела", "мандельштам",                             # найдено свипом по топ-100k wordfreq
    "ебрр",                                               # ЕБРР — банк, не мат
    "курвиметр",                                          # курв-
    "дрочёна",                                            # дроч- : блюдо
    "хулиган", "хулить", "хулит", "хуление",              # хули/хуле — только точный токен
    "сукно", "сучок", "сучков", "сучком",                 # сук- шире точных форм не берём
    "херувим", "херес", "схема", "захер",                 # хер — точный токен; торт «захер»
    "трахея", "трахома", "трах",                          # только глагольные трахн-/траха-
    "выхухоль", "успех", "приехал", "заехал", "победа",
]


def test_catches_mat_wordforms():
    for w in MAT:
        assert filters.has_mat(w), f"пропущен мат: {w!r}"


def test_zero_false_positives_on_ordinary_speech():
    for w in CLEAN:
        assert not filters.has_mat(w), f"ложное срабатывание на обычном слове: {w!r}"


def test_sentences_and_case():
    """Токены внутри строки и регистр: фильтр смотрит на начала токенов,
    а не на подстроки, и нормализует lower + ё→е."""
    assert not filters.has_mat("на рубля не купишь себе хлеба")
    assert not filters.has_mat("команда требует мандарин и характер")
    assert not filters.has_mat("Бляха-муха, схема employment не сходится")
    assert filters.has_mat("да ЗАЕБИСЬ же, бля")
    assert filters.has_mat("Схерачить и похер")
    assert filters.has_mat("всё пошло через ХУЁВО-плохое")


def test_knob_no_mat_parses_with_honest_default():
    assert clean.knobs(None)["no_mat"] is False
    assert clean.knobs({})["no_mat"] is False
    assert clean.knobs({"no_mat": True})["no_mat"] is True
    assert clean.knobs({"no_mat": False})["no_mat"] is False


def test_run_drops_mat_nl_fragments_only_with_flag():
    """Сценарий, не функция: мат-фрагмент из пула nakedlunch не доходит до
    шорт-листа при no_mat=True — и в «алгоритме» (кэшируемая strict-таблица),
    и в «классике» (light-путь; «без мата» — жёсткий инвариант уровня
    blacklist, а не мнение о качестве, поэтому классика его НЕ обходит).
    Без флага те же фрагменты живут как обычные — фильтр честный по запросу,
    а не всегда включённая цензура."""
    mat_texts = ["заебись как хорошо", "какая-то херня опять"]
    clean_texts = ["кошка спала на тёплом окне", "дождь шёл всю ночь напролёт",
                   "он рисовал закат акварелью", "листья падали медленно вниз"]
    all_texts = mat_texts + clean_texts
    fake_rhyme = {t: {"banal": 3.0, "taut": False, "lemmas": lemmatize(t),
                      "tokens": list(nlbridge._tokens(t)), "key": "", "span": None}
                  for t in all_texts}
    old_rhyme = filters._NL_RHYME
    filters._NL_RHYME = fake_rhyme
    try:
        for classic in (0.0, 1.0):
            k_on = clean.knobs({"shortlist": 6, "real_text": 1.0, "classic": classic, "no_mat": True})
            res = filters.run([], k_on, Corpus(), nl_fragments=all_texts, rhyme="none")
            got = {r["text"] for r in res["shortlist"]}
            assert got, "фильтр мата не должен убивать выдачу целиком"
            assert not (got & set(mat_texts)), \
                f"мат просочился (classic={classic}): {got & set(mat_texts)}"

            k_off = clean.knobs({"shortlist": 6, "real_text": 1.0, "classic": classic})
            res2 = filters.run([], k_off, Corpus(), nl_fragments=all_texts, rhyme="none")
            got2 = {r["text"] for r in res2["shortlist"]}
            assert got2 & set(mat_texts), \
                f"без флага мат-фрагменты должны жить как обычные (classic={classic})"
    finally:
        filters._NL_RHYME = old_rhyme


# НАДГРОБИЕ 2026-08-29: здесь стоял `test_run_drops_mat_grammar_lines_only_with_flag`
# — разбор в шапке файла.


# --- Раунд 39: мат ДОЛЕЙ, а не запретом ------------------------------------
# Требование (2026-08-02): при восьмидесяти процентах восемьдесят процентов строк обязаны
# быть с матом.. Раньше ручка умела только
# вычёркивать: попросить мата было нечем.

def test_knob_mat_share_parses():
    """−1 = «не задано» (клиент про мат не говорил — не трогаем), 0 = явное
    «без мата», доля > 0 — сколько строк обязаны быть с матом."""
    assert clean.knobs({})["mat_share"] == -1.0
    assert clean.knobs({})["no_mat"] is False
    assert clean.knobs({"mat_share": 0})["no_mat"] is True          # ноль — это выбор
    assert clean.knobs({"mat_share": 0.8})["no_mat"] is False
    assert clean.knobs({"mat_share": 0.8})["mat_share"] == 0.8
    assert clean.knobs({"mat_share": 5})["mat_share"] == 1.0        # клампится
    # старый булев ключ продолжает работать: сохранённые настройки и тесты
    assert clean.knobs({"no_mat": True, "mat_share": 0.8})["no_mat"] is True


def test_mat_slot_plan_spreads_evenly():
    """Позиции раскладываются по строфе, а не кучей: 80% мата — это восемь
    строк из десяти ВРАЗБИВКУ, иначе получилась бы матерная половина и
    чистая половина, а не восемьдесят процентов."""
    план = filters._mat_slot_plan(0.8, 10)
    assert sum(1 for v in план.values() if v) == 8
    assert filters._mat_slot_plan(0.5, 4) and sum(filters._mat_slot_plan(0.5, 4).values()) == 2
    assert filters._mat_slot_plan(1.0, 4) == {i: True for i in range(4)}
    assert filters._mat_slot_plan(0.0, 4) == {}     # ноль — работой ворот, плана не нужно
    assert filters._mat_slot_plan(-1.0, 4) == {}    # «не задано»
    # 25% на четырёх строках — ровно одна, и не подряд с соседней строфой
    четверть = filters._mat_slot_plan(0.25, 4)
    assert sum(четверть.values()) == 1


def test_run_hits_requested_mat_share():
    """Сценарий целиком: пул пополам матерный, просим половину — получаем
    половину. Проверяем ФАКТ в выдаче, а не наличие ручки (протокол: сверять
    по результату, а не по тому, что поле проставилось)."""
    mat_texts = ["заебись как хорошо", "какая-то херня опять",
                 "нахуй это всё вообще", "пиздец полный сегодня"]
    clean_texts = ["кошка спала на тёплом окне", "дождь шёл всю ночь напролёт",
                   "он рисовал закат акварелью", "листья падали медленно вниз"]
    all_texts = mat_texts + clean_texts
    # Рифмо-ключи настоящие: без них ни один кандидат не может быть якорем
    # пары, схема разваливается на запасных ярусах, и опыт мерил бы не долю
    # мата, а поведение при сломанной рифме (поймано этим же тестом).
    ключи = {t: ("о" if i % 2 == 0 else "е") for i, t in enumerate(all_texts)}
    fake_rhyme = {t: {"banal": 3.0, "taut": False, "lemmas": lemmatize(t),
                      "tokens": list(nlbridge._tokens(t)), "key": ключи[t], "span": None}
                  for t in all_texts}
    old_rhyme, old_idx = filters._NL_RHYME, filters._index_for_current_cache
    filters._NL_RHYME = fake_rhyme
    filters._index_for_current_cache = lambda: None   # мимо колоночного индекса: пул тут свой
    try:
        доли = {}
        for share in (0.0, 1.0):
            k = clean.knobs({"shortlist": 4, "real_text": 1.0, "mat_share": share})
            res = filters.run([], k, Corpus(), nl_fragments=all_texts, rhyme="аабб")
            got = [r["text"] for r in res["shortlist"]]
            assert len(got) == 4, f"выдача усохла при share={share}: {got}"
            доли[share] = sum(1 for t in got if filters.has_mat(t))
        assert доли[0.0] == 0, "0% — мата быть не должно вовсе"
        assert доли[1.0] == 4, f"100% — все строки с матом, получено {доли[1.0]}"

        # 50% — ЭТО РАСПРЕДЕЛЕНИЕ, А НЕ РАВЕНСТВО, и так было всегда.
        #
        # Здесь стояло `доли[0.5] == 2` на ОДНОМ семени, и это была удача
        # семени, а не свойство кода. Замер 2026-08-13 на этом же пуле, 200
        # семян: план слота нарушался в 26 прогонах из 200 ещё ДО правки
        # «равные шансы без темы» (после — в 37 из 200). Причина найдена и
        # названа: барьер повтора лемм СИЛЬНЕЕ квоты мата, а лемма бывает
        # служебной — «всё» и «всю» обе дают «весь», и чистая строка «дождь
        # шёл всю ночь напролёт» отвергалась из-за «нахуй это всё вообще».
        # Слот тогда достаётся матерной строке. Починка барьера — этап 4.
        #
        # Поэтому проверяется то, что код действительно обещает («доля мата —
        # предпочтение, а не инвариант», см. _select_with_rhyme): в среднем
        # ровно половина и попадание в точку у большинства прогонов. Такой
        # сторож ловит настоящую поломку — «квота не работает вовсе» даст
        # среднее 0 или 4 — и не врёт про точность, которой нет.
        счёт = []
        for семя in range(40):
            k = clean.knobs({"shortlist": 4, "real_text": 1.0, "mat_share": 0.5})
            res = filters.run([], k, Corpus(), nl_fragments=all_texts, rhyme="аабб",
                              семя=семя)
            got = [r["text"] for r in res["shortlist"]]
            assert len(got) == 4, f"выдача усохла на семени {семя}: {got}"
            счёт.append(sum(1 for t in got if filters.has_mat(t)))
        среднее = sum(счёт) / len(счёт)
        точно = sum(1 for c in счёт if c == 2)
        assert 1.7 <= среднее <= 2.3, f"50% в среднем не половина: {среднее:.2f} из 4"
        assert точно >= len(счёт) * 0.6, \
            f"ровно половина лишь в {точно} прогонах из {len(счёт)}"
    finally:
        filters._NL_RHYME = old_rhyme
        filters._index_for_current_cache = old_idx


# --- Раунд 44: клаузула и связность соседних строк -------------------------
# Откалибровано по трём референсным текстам пользователя (2026-08-03):
# женская клаузула 77/93/100%, связность соседних строк 0.35/0.18/0.17.

def test_clausula_from_rhyme_key():
    """Клаузула читается из готового рифмо-ключа: он начинается с ударной
    гласной, значит число гласных в нём и есть слог от конца. Отдельный разбор
    ударений не нужен — для 2.87М фрагментов это и делает признак бесплатным."""
    import scan
    assert scan.clausula("уть") == 1        # мужская: одна гласная
    assert scan.clausula("ится") == 2       # женская
    assert scan.clausula("ается") == 3      # дактилическая
    assert scan.clausula("") == 0           # ключа нет — тип неизвестен


def test_clausula_knob_parses():
    assert clean.knobs({})["clausula"] == 7   # маска «любая» (2026-08-28)
    assert clean.knobs({"clausula": 2})["clausula"] == 2
    assert clean.knobs({"clausula": 9})["clausula"] == 7       # клампится в маску


def test_clausula_is_a_gate_not_a_preference():
    """Ворота, а не предпочтение: рифмующая пара обязана быть той же клаузулы,
    иначе рифмы не выйдет вовсе. Проверяем ФАКТ на выдаче, а не наличие поля."""
    import scan
    тексты = ["холодная вода", "смотрит без труда", "она уходит", "он не находит",
              "тёмные аллеи", "белые лилеи"]
    fake = {t: {"banal": 3.0, "taut": False, "lemmas": lemmatize(t),
                "tokens": list(nlbridge._tokens(t)),
                "key": ("а" if t.endswith("да") else ("одит" if t.endswith("одит") else "еи")),
                "span": None}
            for t in тексты}
    старый, старый_idx = filters._NL_RHYME, filters._index_for_current_cache
    filters._NL_RHYME = fake
    filters._index_for_current_cache = lambda: None
    try:
        res = filters.run([], clean.knobs({"shortlist": 2, "real_text": 1.0, "clausula": 2}),
                          Corpus(), nl_fragments=тексты, rhyme="none")
        got = [r["text"] for r in res["shortlist"]]
        for t in got:
            assert scan.clausula(fake[t]["key"]) == 2, f"просили женскую, пришло {t!r}"
    finally:
        filters._NL_RHYME = старый
        filters._index_for_current_cache = старый_idx


def test_доля_мата_держится_и_без_схемы_в_алгоритме():
    """НАЙДЕНО УЛЬТРАРЕВЬЮ (bug_002, 2026-08-27). Все три ветки rhyme=="none"
    в `_run` звали `_diversify` напрямую, и середина «Мата» (0<доля<1) на пути
    без схемы молча игнорировалась: подпись «50%» обновлялась, выдача нет.
    Инвариант Раунда 39 — «доля мата обязана соблюдаться и без схемы» — был
    сформулирован в `_select_with_rhyme`, а рядом, в `_run`, нарушался."""
    from filters import _diversify_с_долей_мата
    пул = ([{"text": f"матерная строка {i}", "score": 0.9, "_lem": {f"м{i}"},
             "mat": True} for i in range(20)]
           + [{"text": f"чистая строка {i}", "score": 0.9, "_lem": {f"ч{i}"},
              "mat": False} for i in range(20)])
    взято = _diversify_с_долей_мата(пул, 8, 0.3, 0.5)
    доля = sum(1 for r in взято if r["mat"]) / len(взято)
    assert len(взято) == 8
    assert 0.35 <= доля <= 0.65, f"просили половину, получили {доля:.2f}"


def test_доля_мата_как_есть_не_трогает_отбор():
    """−1 («как есть») — прежний путь: никакой квоты, чистый MMR. Ломать
    поведение по умолчанию починка не имеет права."""
    from filters import _diversify, _diversify_с_долей_мата
    пул = [{"text": f"строка {i}", "score": 0.9 - i * 0.01, "_lem": {f"л{i}"},
            "mat": i % 7 == 0} for i in range(30)]
    assert (_diversify_с_долей_мата(пул, 6, 0.3, -1.0)
            == _diversify(пул, 6, 0.3))


def test_доля_мата_добирает_когда_корзина_пуста():
    """Строка важнее доли: если матерных в пуле нет вовсе, «50%» не смеет
    вернуть половину строфы — добираем чистыми, тот же размен, что в ветке
    scheme=="none" у _select_with_rhyme."""
    from filters import _diversify_с_долей_мата
    пул = [{"text": f"чистая {i}", "score": 0.9, "_lem": {f"ч{i}"},
            "mat": False} for i in range(20)]
    assert len(_diversify_с_долей_мата(пул, 8, 0.3, 0.5)) == 8
