# nakedlunch — ХУК: повтор это НАСТРОЙКА, а не запрет (Раунд 52).
#
# Владелец 2026-08-04, дословно: «хук — это такой тип строфы, он подразумевает
# повтор и прочие механики. Значит хуки, хуковые припевы и хуковые элементы
# механизм должен уметь делать. Это странно, что он борется с повторяющимся —
# он не должен повторять только при соответствующих настройках, но если я хочу
# повторять, пусть повторяет».
#
# Аудит нашёл ТРИ независимых запрета, и все три были безусловными:
#   1. `assemble` — одна строфа не встаёт в двух звеньях;
#   2. `_select_with_rhyme` — лемма не повторяется внутри строфы;
#   3. `W_REPEATS` — общие слова между строфами штрафуются.
# Инвариант меняется с «никогда не повторять» на «повторять, когда попросили».
#
# Отвечают за это ДВЕ РАЗНЫЕ вещи, и путать их нельзя:
#   · `repeat_of` у звена — СТРУКТУРА. Припев второй раз. Точно, видно глазами,
#     не вероятностно. Это и есть хук.
#   · крутилка «Повтор» — мягкие барьеры (лемма внутри строфы, штраф между
#     строфами). Хуковые ЭЛЕМЕНТЫ, а не структура.
#
# Прогон: .venv/bin/python -m pytest tests/test_hook_repeat.py -q

import json
import subprocess
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

import clean
import filters
import pipeline

ПОЛКИ = КОРЕНЬ / "interface" / "react-app" / "src" / "nl" / "methods.shelves.js"


# ---- крутилка: канон и перевод ---------------------------------------------

def test_povtor_целочисленный_и_по_умолчанию_запрещён():
    """Дефолт — прежнее поведение: кто не просил повторов, тот их и не
    получает. И значение ЦЕЛОЕ: промежутка между «барьер стоит» и «барьера
    нет» не существует, а дробный ползунок обещал бы оттенки, которых нет."""
    assert clean.KNOB_SPEC["Повтор"] == (0, 1, 0, True)
    assert clean.knobs({})["repeat"] == 0
    assert clean.knob_params({})["Повтор"] == 0
    # дробь и мусор клампятся, а не проносятся внутрь
    assert clean.knobs({"repeat": 0.7})["repeat"] == 0
    assert clean.knobs({"repeat": 5})["repeat"] == 1
    assert clean.knobs({"repeat": "чушь"})["repeat"] == 0


def test_profil_dovozit_povtor_do_yadra():
    """Переводчик один (knobs_from_profile) — значит и эта ручка обязана через
    него доехать, а не потеряться, как терялись «Отбор» и «Мат»."""
    k = clean.knobs_from_profile({"name": "хук", "mode": clean.MODE_ALGO,
                                  "params": {"Повтор": 1}})
    assert k["repeat"] == 1
    assert clean.knobs_from_profile({"name": "о", "mode": clean.MODE_ALGO})["repeat"] == 0


# ---- барьер на повтор леммы ВНУТРИ строфы ----------------------------------

# Проверяем САМ ОТБОРЩИК, а не круг через filters.run. Причина не в удобстве:
# ранг кандидата в живом прогоне складывается из перцентилей банальности,
# метра, длины и темы, и подобрать фикстуру, где «повтор» решает исход, а не
# случайный перевес одного из этих слагаемых, невозможно честно — пробовал:
# на одном наборе выигрывала строка с ХУДШЕЙ банальностью. Тест с подкрученной
# фикстурой доказывал бы не барьер, а везение. Здесь баллы заданы прямо, и
# видно ровно одно: что делает барьер.
#
# Барьер к тому же мягкий ПО ЗАМЫСЛУ («рифма важнее повтора», решение
# владельца 2026-07-14) — поэтому непротиворечивая альтернатива в пуле ЕСТЬ:
# третья строка с тем же рифмо-ключом и другими леммами. Без неё каскад
# разрешил бы повтор последней ступенью и без всякой крутилки.

def кандидат(text, score, rhyme, lem):
    return {"text": text, "score": score, "rhyme": rhyme, "_lem": set(lem),
            "template": "nakedlunch", "syllables": 6, "mat": False, "_pctl": score}


ПУЛ = [
    кандидат("мой дом стоит пустой", 1.0, "ой", {"дом", "мой"}),
    кандидат("твой дом стоит большой", 0.9, "ой", {"дом", "твой"}),
    кандидат("и ветер за стеной", 0.5, "ой", {"ветер", "стена"}),
]


def отбор(повтор: bool):
    return [r["text"] for r in filters._select_with_rhyme(
        [dict(c) for c in ПУЛ], "аа", 2, set(range(2)), repeat_ok=повтор)]


def test_bez_povtora_lemma_ne_dublируется():
    """Прежнее поведение целиком: вторая позиция берёт ХУДШУЮ по баллу строку
    (0.5 вместо 0.9), лишь бы не повторить лемму «дом». Это и есть барьер."""
    тексты = отбор(False)
    assert len(тексты) == 2
    assert sum(1 for t in тексты if "дом" in t) == 1, тексты
    assert "и ветер за стеной" in тексты


def test_s_povtorom_lemma_vozvraschaetsya():
    """РЕЗУЛЬТАТ, а не наличие флага: барьер снят — и повтор леммы «дом»
    СТАНОВИТСЯ ВОЗМОЖЕН. Возвращающееся слово, на котором и стоит хук.

    Раунд 57: проверка велась на одном прогоне и требовала повтор ОБЯЗАТЕЛЬНО.
    С тех пор отбор берёт случайного из полосы лучших (иначе одна книга
    занимала все строфы подряд), и «лучшая по баллу» перестала быть
    единственной. Свойство хука от этого не изменилось: без него повтор
    НЕВОЗМОЖЕН, с ним — возможен. Так и проверяем, на нескольких семенах."""
    import filters as _f

    def повторов(вкл, семя):
        _f.закрепить_разброс(семя)
        тексты = отбор(вкл)
        return sum(1 for t in тексты if "дом" in t), тексты

    сповтором = [повторов(True, s)[0] for s in range(25)]
    _f.закрепить_разброс(20260806)
    assert max(сповтором) == 2, f"с хуком повтор так и не случился ни разу: {сповтором}"

    без = [повторов(False, s)[0] for s in range(25)]
    _f.закрепить_разброс(20260806)
    assert max(без) == 1, f"без хука повтор всё-таки прошёл: {без}"


def test_krutilka_dohodit_do_otborschika():
    """Связка: `repeat` из knobs обязан доехать до отборщика. Проверяется тем
    же способом — по РЕЗУЛЬТАТУ: подменяем отборщик и смотрим, с чем его
    позвали при разных значениях крутилки."""
    from corpus import Corpus
    видели = []
    прежний = filters._select_with_rhyme

    def перехват(*a, **kw):
        видели.append(kw.get("repeat_ok"))
        return прежний(*a, **kw)

    filters._select_with_rhyme = перехват
    try:
        for v in (0, 1):
            k = clean.knobs({"shortlist": 2, "real_text": 0.0, "repeat": v})
            filters.run([kw for kw in ()], k, Corpus(), rhyme="аа")
    finally:
        filters._select_with_rhyme = прежний
    assert видели == [False, True], f"крутилка не доехала до отбора: {видели}"


# ---- структура: звено-повтор (хук) -----------------------------------------

def каркас(letters="аа", syl=(4, 12)):
    return [{"letter": l, "min_syl": syl[0], "max_syl": syl[1]} for l in letters]


def спека(chain, **kw):
    return clean.pipeline_spec({"theme": "", "chain": chain, **kw})


def test_kontrakt_prinимает_ссылку_назад():
    s = спека([{"spec": каркас()}, {"title": "припев", "repeat_of": 0}])
    assert s["chain"][0]["repeat_of"] is None
    assert s["chain"][1]["repeat_of"] == 0


@pytest.mark.parametrize("плохая", [0, 1, 5, -1])
def test_ssylka_vperyod_ili_na_sebya_chestnyy_otkaz(плохая):
    """Цикл — не «странное значение, которое можно поджать»: подставить вместо
    него ноль значило бы молча собрать не ту песню."""
    with pytest.raises(clean.BadInput):
        спека([{"spec": каркас(), "repeat_of": 0 if плохая == 0 else плохая}])


def test_slepok_cepochki_ne_teryaet_pripev():
    """Звено-повтор своей спеки не имеет по определению. Раньше `chain_link`
    требовал спеку и вернул бы None — то есть каждое сохранение цепочки
    выбрасывало бы все припевы."""
    c = clean.chain_profile({"name": "песня", "links": [
        {"spec": каркас(), "form": "Двустишие"},
        {"title": "припев", "repeat_of": 0},
    ]})
    assert c is not None and len(c["links"]) == 2
    assert c["links"][1]["repeat_of"] == 0 and c["links"][1]["title"] == "припев"


def test_zveno_povtor_nasleduet_karkas_i_krutilki():
    """Разрешение цепочки: у повтора тот же каркас, те же крутилки и ТОТ ЖЕ
    КЛЮЧ ПУЛА — значит генерация за припев не платит ничего."""
    s = спека([{"spec": каркас("абаб")}, {"title": "припев", "repeat_of": 0}])
    links = pipeline.resolve_chain(s["chain"], s["knobs"])
    assert links[1]["spec"] == links[0]["spec"]
    assert links[1]["key"] == links[0]["key"]
    assert links[1]["knobs"] == links[0]["knobs"]
    assert links[1]["title"] == "припев", "свой заголовок звено обязано сохранить"
    assert links[1]["repeat_of"] == 0


def пул(key, n=4):
    """Синтетический пул: n различимых строф с известными леммами."""
    out = []
    for i in range(n):
        rows = [{"text": f"строка {i} раз", "syllables": 5, "rhyme": "аз"},
                {"text": f"строка {i} два", "syllables": 5, "rhyme": "ва"}]
        out.append({"rows": rows, "rank": i, "lemmas": {f"слово{i}"},
                    "forced_words": set(), "forced": False, "id": (key, i)})
    return out


def test_pripev_stavit_tu_zhe_strofu():
    """ГЛАВНОЕ. Куплет — припев — куплет — припев: второй припев обязан быть
    ТЕМ ЖЕ ТЕКСТОМ, что первый. Раньше это было невозможно: `assemble`
    выбрасывал любое расширение, где строфа уже использована."""
    s = спека([{"spec": каркас()}, {"spec": каркас("бб")},
               {"spec": каркас()}, {"title": "припев", "repeat_of": 1}])
    links = pipeline.resolve_chain(s["chain"], s["knobs"])
    pools = {l["key"]: пул(l["key"]) for l in links}
    chosen, _ = pipeline.assemble(links, pools, s["junctions"], 2000, 1, set())
    assert chosen, "цепочка с припевом обязана собираться"
    picks = chosen[0]["picks"]
    assert picks[3] is picks[1], "припев не повторился — это не хук"
    # а обычные звенья по-прежнему не повторяются сами собой
    assert picks[0] is not picks[2]


def test_pripev_ne_stoit_generatsii():
    """Пул строится по УНИКАЛЬНЫМ профилям, и звено-повтор в этот счёт не
    входит: припев не должен стоить владельцу второго прогона генерации."""
    s = спека([{"spec": каркас()}, {"title": "припев", "repeat_of": 0}])
    links = pipeline.resolve_chain(s["chain"], s["knobs"])
    звали = []

    def фейк(link, *a, **k):
        звали.append(link["key"])
        return пул(link["key"])

    прежний = pipeline._build_one_pool
    pipeline._build_one_pool = фейк
    try:
        pipeline.build_pools(links, [], set(), 10, None, [])
    finally:
        pipeline._build_one_pool = прежний
    assert len(звали) == 1, f"пул строился {len(звали)} раза вместо одного"


def test_povtor_ne_schitaetsya_sovpadeniem_dvazhdy():
    """Совпадение припева с самим собой — не дефект, и считать его нельзя.

    Цепочка «куплет — припев — куплет», где припев это повтор первого звена, а
    ЛЕММЫ У ВСЕХ СТРОФ ОДИНАКОВЫ (крайний случай: пересечение везде 1.0).
    Пар, попадающих в штраф, ровно одна — между двумя не-повторами. Если бы
    пара с копией припева считалась тоже, среднее пересечение вышло бы 2.0 при
    максимуме 1.0, и балл уехал бы НИЖЕ НУЛЯ — то есть за пределы собственного
    диапазона. Это и проверяем: не «примерно похоже», а что число осталось
    числом."""
    s = спека([{"spec": каркас()}, {"title": "припев", "repeat_of": 0},
               {"spec": каркас("бб")}],
              junctions=["свободно", "свободно"])
    links = pipeline.resolve_chain(s["chain"], s["knobs"])
    pools = {}
    for l in links:
        p = пул(l["key"], 1)               # ровно одна строфа: ранг 0, качество 1.0
        p[0]["lemmas"] = {"общее"}         # пересечение любой пары ровно 1.0
        pools[l["key"]] = p
    chosen, _ = pipeline.assemble(links, pools, s["junctions"], 2000, 1, set())
    assert chosen
    # Всё в формуле известно: качество 1.0, оба стыка «свободно», пересечение
    # 1.0 при одной паре — значит слагаемое повторов ровно ноль. Сравниваем с
    # формулой модуля, а не с записанным числом: перевесят веса — тест поедет
    # вместе с ними, а не начнёт врать.
    ожидаемый = (pipeline.W_QUALITY * 1.0
                 + pipeline.W_JUNCTION * pipeline.JUNCTION_FREE_SCORE)
    assert chosen[0]["score"] == pytest.approx(ожидаемый), (
        f"балл {chosen[0]['score']} против {ожидаемый}: пара с копией припева "
        f"посчитана как совпадение")


def test_globalnaya_krutilka_dohodit_do_skleyki(monkeypatch):
    """Связка целиком: «Повтор» глобальных настроек прогона обязана доехать до
    склейки. Пулы и склейку подменяем — проверяется ровно провод, и проверяется
    по тому, С ЧЕМ позвали, а не по тому, что где-то есть нужное поле."""
    видели = []
    monkeypatch.setattr(pipeline, "build_pools", lambda *a, **k: {})
    monkeypatch.setattr(pipeline, "assemble",
                        lambda *a, **k: (видели.append(k.get("allow_repeats")), ([], {}))[1])
    for v in (0, 1):
        s = спека([{"spec": каркас()}], knobs={"repeat": v})
        pipeline.run_pipeline(s, None, [])
    assert видели == [False, True], f"крутилка не доехала до склейки: {видели}"


def test_krutilka_snimaet_shtraf_mezhdu_strofami():
    """Глобальная «Повтор» убирает слагаемое штрафа целиком — и балл при этом
    остаётся в тех же пределах, а не подскакивает на вес слагаемого."""
    低 = pipeline._combo_score(2.0, 1.0, 2.0, 2, 1, False)   # полное пересечение
    без = pipeline._combo_score(2.0, 1.0, 2.0, 2, 1, True)
    assert без > 低, "штраф не снят"
    assert без <= 1.0 and 低 >= 0.0
    # без повторов вовсе оба пути обязаны сойтись: штрафовать нечего
    assert pipeline._combo_score(2.0, 1.0, 0.0, 2, 1, False) == pytest.approx(
        pipeline._combo_score(2.0, 1.0, 0.0, 2, 1, True))


# ---- фронт: ссылки повтора переживают правку цепочки -----------------------
#
# Ссылка хранится ИНДЕКСОМ, а индексы едут при каждой перестановке и удалении.
# На этой самой породе ошибок проект уже обжигался: `chainKnobs` забыли
# переставлять вместе со звеном, и профили настроек молча съезжали на чужие
# звенья. Поэтому пересчёт один и чистый — и проверяется настоящим node, а не
# чтением исходника.

def перенумеровать(rep, перевод, длина):
    if subprocess.run(["which", "node"], capture_output=True).returncode:
        pytest.skip("node не установлен — проверка фронта пропущена")
    src = (f"import {{ shelfMethods }} from '{ПОЛКИ.as_posix()}';\n"
           f"console.log(JSON.stringify(shelfMethods.чинитьПовторы.call({{}}, "
           f"{json.dumps(rep)}, {json.dumps(перевод)}, {длина})));")
    p = subprocess.run(["node", "--input-type=module", "-e", src],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"node упал:\n{p.stderr}"
    return json.loads(p.stdout)


def test_perestanovka_zvenyev_taschit_ssylku_za_soboy():
    """Куплет(0) · припев(1) · припев=1(2). Меняем местами 0 и 1: ссылка обязана
    поехать за припевом, то есть теперь показывать на 0."""
    assert перенумеровать([None, None, 1], [1, 0, 2], 3) == [None, None, 0]


def test_ssylka_razvernuvshayasya_vperyod_snimaetsya():
    """Припев уехал ПОСЛЕ того, кто его повторял. «Поджать» ссылку к соседу
    значило бы молча собрать другую песню, поэтому она снимается — и это
    видно в цепочке, а не только в выдаче."""
    assert перенумеровать([None, None, 1], [0, 2, 1], 3) == [None, None, None]


def test_udalenie_cheli_snimaet_povtor():
    """Убрали звено, которое повторяли, — повторять больше нечего."""
    assert перенумеровать([None, None, 1], [0, None, 1], 2) == [None, None]


def test_udalenie_sosednego_sdvigaet_nomera():
    """Убрали звено 0: припев был 1, стал 0, а его повтор был 2, стал 1."""
    assert перенумеровать([None, None, 1], [None, 0, 1], 2) == [None, 0]


def test_cepochka_bez_povtorov_ne_menyaetsya():
    assert перенумеровать([None, None, None], [1, 0, 2], 3) == [None, None, None]
    assert перенумеровать([], [0], 1) == [None]


# ---- ВСТРОЕННЫЕ ЦЕПОЧКИ: припев обязан быть ПОВТОРОМ -----------------------
#
# До Раунда 52 механизма повтора не было, и цепочка с именем «Хук-формат»
# давала ТРИ РАЗНЫХ хука, а «Куплет-припев» — три разных припева. Ровно то, на
# что владелец и указал: «странно, что он борется с повторяющимся».
#
# РАУНД 55: раньше это была константа ФРОНТА (PRESET_CHAINS), и тесты читали её
# через node. Теперь встроенные цепочки — записи полки в домене, как встроенные
# формы строф: владелец справедливо спросил, почему серия не видит «три
# сохранённых пресета», и ответ был — потому что полкой они не были.

import chain_profiles  # noqa: E402

ПОЛКИ = КОРЕНЬ / "interface" / "react-app" / "src" / "nl" / "methods.shelves.js"


def встроенные():
    return {c["name"]: c["links"] for c in chain_profiles.builtin()}


# Что ВОЗВРАЩАЕТСЯ по определению жанра, а что нет. Правило не «одинаковый
# заголовок — значит повтор»: куплетов в песне тоже несколько, и они обязаны
# быть РАЗНЫМИ. Возвращается припев и хук — на этом они и стоят.
ВОЗВРАЩАЮТСЯ = {"Припев", "Хук"}


def test_vse_tri_vstroennye_sobralis():
    """Опора всего блока: если полка пуста или собралась наполовину, остальные
    тесты зелёные и бессмысленные. Заодно это и есть та проверка, которой не
    было: цепочка собирается из ФОРМ СТРОФ по имени, и переименование формы
    молча оставило бы владельца без встроенных цепочек."""
    в = встроенные()
    assert set(в) == {"Куплет-припев", "Хук-формат", "Вольная"}, sorted(в)
    assert [len(l) for l in (в["Куплет-припев"], в["Хук-формат"], в["Вольная"])] == [6, 5, 4]


def test_pripevy_i_huki_povtoryayutsya():
    """Второе и последующие «Припев»/«Хук» обязаны быть повтором ПЕРВОГО —
    иначе имя цепочки врёт о том, что она собирает."""
    for имя, звенья in встроенные().items():
        первый = {}
        for i, з in enumerate(звенья):
            секция, повтор = з.get("title") or "", з.get("repeat_of")
            if секция not in ВОЗВРАЩАЮТСЯ:
                continue
            if секция in первый:
                assert повтор == первый[секция], (
                    f"{имя}: звено {i + 1} «{секция}» не повторяет "
                    f"звено {первый[секция] + 1} — это разные строфы")
            else:
                первый[секция] = i
                assert повтор is None, f"{имя}: первое «{секция}» не может быть повтором"
        assert первый or имя == "Вольная", f"{имя}: в песне нет ни припева, ни хука"


def test_kuplety_i_bridzhi_ne_povtoryayutsya():
    """Обратная сторона того же правила. Если бы повтор стоял и на куплетах,
    песня превратилась бы в одну строфу, повторённую шесть раз."""
    for имя, звенья in встроенные().items():
        for i, з in enumerate(звенья):
            if (з.get("title") or "") in ВОЗВРАЩАЮТСЯ:
                continue
            assert з.get("repeat_of") is None, (
                f"{имя}: звено {i + 1} «{з.get('title') or 'без заголовка'}» — повтор, "
                f"а такие части обязаны быть разными")


def test_ssylki_smotryat_nazad_i_ne_na_povtor():
    """Те же два правила, что у контракта (clean.pipeline_spec): ссылка только
    назад, и цель сама не может быть повтором — иначе цепочка ссылок."""
    for имя, звенья in встроенные().items():
        for i, з in enumerate(звенья):
            повтор = з.get("repeat_of")
            if повтор is None:
                assert з.get("spec"), f"{имя}: у обычного звена {i + 1} нет каркаса"
                continue
            assert 0 <= повтор < i, f"{имя}: звено {i + 1} ссылается вперёд или на себя"
            assert звенья[повтор].get("repeat_of") is None, f"{имя}: цепочка ссылок в звене {i + 1}"
            assert not з.get("form"), (
                f"{имя}: у звена-повтора {i + 1} прописана форма — второй источник "
                f"правды о том же каркасе")


def test_volnaya_bez_povtorov():
    """Стихотворение — не песня: там повторять нечего, и цепочка об этом
    молчит намеренно."""
    assert all(з.get("repeat_of") is None for з in встроенные()["Вольная"])


def test_vstroennaya_prohodit_kontrakt_progona():
    """Сквозь: запись полки → валидатор бэка. Если бы ссылки были кривыми,
    прогон падал бы 400-й уже после нажатия «прогнать»."""
    for имя, звенья in встроенные().items():
        chain = []
        for з in звенья:
            э = {"title": з.get("title") or ""}
            if з.get("repeat_of") is None:
                э["spec"] = з["spec"]
            else:
                э["repeat_of"] = з["repeat_of"]
            chain.append(э)
        s = спека(chain)
        assert len(s["chain"]) == len(звенья), имя
        assert [э["repeat_of"] for э in s["chain"]] == [з.get("repeat_of") for з in звенья], имя


def test_seriya_nahodit_vstroennuyu_po_imeni():
    """ГЛАВНОЕ РАУНДА 55. Серия ищет цепочку по имени через by_name — и до
    этого раунда встроенных там не было, потому что они жили константой во
    фронте. Владелец: «там же уже три сохранённых пресета пайплайна есть,
    почему они не отображаются»."""
    for имя in ("Куплет-припев", "Хук-формат", "Вольная"):
        assert chain_profiles.by_name(имя) is not None, f"серия не найдёт «{имя}»"


def выбрать_цепочку(имя):
    """Настоящий `pickChain` из methods.shelves.js — то, что реально кладёт
    запись полки в состояние. Запись может быть верной, а перекладка терять."""
    if subprocess.run(["which", "node"], capture_output=True).returncode:
        pytest.skip("node не установлен — проверка фронта пропущена")
    полка = json.dumps(chain_profiles.builtin(), ensure_ascii=False)
    src = f"""
    import {{ shelfMethods }} from '{ПОЛКИ.as_posix()}';
    let patch = null;
    const self = Object.assign(Object.create(shelfMethods), {{
      state: {{ chainList: {полка} }}, closeSub: () => {{}},
      setState: (p) => {{ patch = p; }},
    }});
    shelfMethods.pickChain.call(self, {json.dumps(имя, ensure_ascii=False)});
    console.log(JSON.stringify(patch));
    """
    p = subprocess.run(["node", "--input-type=module", "-e", src],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"node упал:\n{p.stderr}"
    return json.loads(p.stdout)


def test_vybor_vstroennoy_donosit_povtory_do_sostoyaniya():
    """РЕГРЕССИЯ. Запись может быть верной, а перекладка — терять `repeat_of`:
    тогда цепочка на экране выглядит песней, а собирает шесть разных строф."""
    patch = выбрать_цепочку("Куплет-припев")
    assert patch["chainRepeat"] == [None, None, None, 1, None, 1]
    assert patch["chain"] == ["Куплет", "Припев", "Куплет", "Припев", "Бридж", "Припев"]
    # у звена-повтора формы нет: каркас он берёт у двойника
    assert patch["chainForms"][3] is None and patch["chainForms"][5] is None
    assert patch["chainForms"][1] == "Катрен парный короткий"


def test_vybor_vstroennoy_bez_povtorov():
    patch = выбрать_цепочку("Вольная")
    assert patch["chainRepeat"] == [None] * 4
    assert all(f == "Катрен перекрёстный" for f in patch["chainForms"])
