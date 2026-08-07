# nakedlunch — вторая полка: ПРОФИЛИ НАСТРОЕК (Раунд 50, требование: каркас строфы и профиль настроек ставятся раздельно).
#
# Тесты на реальных файлах во временном каталоге, без моков — как в
# test_gen_profile.py и test_sheets.py.
#
# Проверяется РЕЗУЛЬТАТ, а не наличие ключа: «рифмовка работала по наличию ключа, а не по совпадению»), поэтому каждый
# перевод интерфейсной координаты в ядерную сверяется числом, а каждое
# «ворота» — тем, что ворота действительно закрылись.
#
# Прогон: .venv/bin/python -m pytest tests/test_knob_profiles.py -q

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import clean
import knob_profiles


@pytest.fixture()
def свой_каталог(tmp_path, monkeypatch):
    monkeypatch.setattr(knob_profiles, "DATA_DIR", tmp_path)
    monkeypatch.setattr(knob_profiles, "PROFILES_PATH", tmp_path / "knob_profiles.json")
    return tmp_path


# ---- канон имён и диапазонов ----------------------------------------------

def test_ворота_и_мнения_не_пересекаются():
    """Разделение — не оформление панели, а свойство кода: классика гасит
    мнения и подчиняется воротам. Пересечение групп означало бы, что одна
    крутилка обязана быть в классике и того, и другого."""
    assert not (set(clean.KNOB_GATES) & set(clean.KNOB_OPINIONS))
    assert set(clean.KNOB_SPEC) == set(clean.KNOB_GATES) | set(clean.KNOB_OPINIONS)


def test_профиль_всегда_полный():
    """Недостающие ключи берут дефолт: половинчатый профиль на одном звене и
    полный на другом — это тихий разнобой внутри одной цепочки."""
    p = clean.knob_params({"Мелодичность": 0.9})
    assert set(p) == set(clean.KNOB_SPEC)
    assert p["Мелодичность"] == 0.9
    assert p["Точность рифм"] == 0.25


def test_мусор_клампится_а_чужое_отбрасывается():
    p = clean.knob_params({"Мат": 5, "Клаузула": 2.7, "Связность": -9,
                           "Точность рифм": "чушь", "постороннее": 1})
    assert p["Мат"] == 1.0            # выше потолка
    assert p["Клаузула"] == 3         # целое, округлено и прижато к потолку
    assert p["Связность"] == -1.0     # ниже пола
    assert p["Точность рифм"] == 0.25  # нечисло → дефолт
    assert "постороннее" not in p


def test_профиль_без_имени_это_не_профиль():
    """None, а не исключение: одна битая строка в файле, который пользователь
    может открыть руками, не должна ронять весь список профилей."""
    assert clean.knob_profile({"name": "   ", "params": {}}) is None
    assert clean.knob_profile("не объект") is None
    assert clean.knob_profile({"name": "Живой"})["name"] == "Живой"


# ---- бинарная классика -----------------------------------------------------

def test_классика_не_хранит_мнений():
    """Требование: то, что не работает, лучше убрать вовсе.. Профиль в режиме
    классики не должен показывать глазами ползунки, которых режим не читает."""
    p = clean.knob_profile({"name": "Сырьё", "mode": clean.MODE_CLASSIC,
                            "params": {"Банальность": 0.9, "Мат": 0.5}})
    assert p["mode"] == clean.MODE_CLASSIC
    assert "Банальность" not in p["params"]
    assert p["params"]["Мат"] == 0.5      # ворота остались: им классика подчиняется


def test_неизвестный_режим_это_алгоритм():
    assert clean.knob_profile({"name": "т", "mode": "хренотень"})["mode"] == clean.MODE_ALGO


def test_классика_доезжает_до_ядра_единицей():
    k = clean.knobs_from_profile({"name": "т", "mode": clean.MODE_CLASSIC})
    assert k["classic"] == 1.0
    assert clean.knobs_from_profile({"name": "т"})["classic"] == 0.0


# ---- перевод интерфейс → ядро ---------------------------------------------

def test_инвертированные_шкалы_переводятся_один_раз():
    """Банальность и Диссонанс у ядра идут в обратную сторону. Раньше перевод
    дублировался на фронте (genKnobs) и в methods.panels.js (paramKnobs) — два
    места, где можно перепутать знак."""
    k = clean.knobs_from_profile({"name": "т", "params": {"Банальность": 0.15,
                                                          "Диссонанс": 0.25}})
    # Раунд 58: «Банальность» стала двусторонней и ПЕРЕСТАЛА инвертироваться —
    # шкалы интерфейса и ядра совпали (0 банально, 1 свежо, 0.5 нейтраль).
    # «Диссонанс» инвертируется как инвертировался, и проверяется ниже.
    assert k["banality"] == pytest.approx(0.15)
    assert k["cohesion"] == pytest.approx(0.75)
    assert k["banal"] == pytest.approx(0.15)     # старый алиас, его читает filters.run
    assert k["explore"] == pytest.approx(0.75)


def test_прямые_шкалы_не_переворачиваются():
    k = clean.knobs_from_profile({"name": "т", "params": {
        "Источники": 0.4, "Точность рифм": 0.9, "Мелодичность": 0.1,
        "Клаузула": 2, "Связность": 0.3}})
    assert k["real_text"] == 0.4 and k["nl_mix"] == 0.4
    assert k["rhyme_precision"] == 0.9
    assert k["melody"] == 0.1 and k["meter"] == 0.1
    assert k["clausula"] == 2
    assert k["flow"] == pytest.approx(0.3)


@pytest.mark.parametrize("мат, share, no_mat, only_mat", [
    (-1.0, -1.0, False, False),   # как есть — прежнее поведение корпуса
    (0.0, 0.0, True, False),      # без мата — жёсткий фильтр
    (0.5, 0.5, False, False),     # половина строк обязана быть с матом
    (1.0, 1.0, False, True),      # только мат — антифильтр
])
def test_четыре_положения_мата(мат, share, no_mat, only_mat):
    k = clean.knobs_from_profile({"name": "т", "params": {"Мат": мат}})
    assert k["mat_share"] == share
    assert k["no_mat"] is no_mat
    assert k["only_mat"] is only_mat


def test_дефолт_мата_не_режет_мат():
    """ПОЧИНКА Раунда 50: интерфейс по умолчанию слал 0, то есть жёсткое «без
    мата», хотя в референсах пользователя мата 17–21%. Ядро всегда считало
    дефолтом −1 — расходились две стороны."""
    assert clean.KNOB_GATES["Мат"][2] == -1.0
    k = clean.knobs_from_profile(None)
    assert k["no_mat"] is False and k["only_mat"] is False


# ---- полка на диске --------------------------------------------------------

def test_встроенных_два_и_они_валидны():
    имена = [p["name"] for p in knob_profiles.builtin()]
    assert имена == ["Обычный", "Классика"]
    обычный, классика = knob_profiles.builtin()
    assert обычный["mode"] == clean.MODE_ALGO
    assert классика["mode"] == clean.MODE_CLASSIC
    assert "Банальность" not in классика["params"]


def test_сохранение_перезапись_удаление(свой_каталог):
    knob_profiles.save("Мой", clean.MODE_ALGO, {"Банальность": 0.15})
    assert [p["name"] for p in knob_profiles.custom()] == ["Мой"]
    assert knob_profiles.custom()[0]["params"]["Банальность"] == 0.15

    knob_profiles.save("Мой", clean.MODE_ALGO, {"Банальность": 0.8})
    свои = knob_profiles.custom()
    assert len(свои) == 1                       # перезапись по имени, не второй «Мой»
    assert свои[0]["params"]["Банальность"] == 0.8

    knob_profiles.delete("Мой")
    assert knob_profiles.custom() == []


def test_сохранение_без_имени_падает_одной_фразой(свой_каталог):
    with pytest.raises(clean.BadInput):
        knob_profiles.save("  ", clean.MODE_ALGO, {})


def test_битый_файл_это_пустой_список_а_не_падение(свой_каталог):
    (свой_каталог / "knob_profiles.json").write_text("{это не список", "utf-8")
    assert knob_profiles.custom() == []


def test_битая_запись_выбрасывается_а_соседние_живут(свой_каталог):
    (свой_каталог / "knob_profiles.json").write_text(
        '[{"name": "Живой", "params": {}}, {"нет": "имени"}]', "utf-8")
    assert [p["name"] for p in knob_profiles.custom()] == ["Живой"]


def test_свой_профиль_перекрывает_встроенный(свой_каталог):
    """То же правило, что у форм строф в pipeline.resolve_chain: своя запись с
    тем же именем — сознательный оверрайд пользователя."""
    knob_profiles.save("Обычный", clean.MODE_ALGO, {"Мелодичность": 0.05})
    assert knob_profiles.by_name("Обычный")["params"]["Мелодичность"] == 0.05


def test_by_name_молчит_на_несуществующем(свой_каталог):
    assert knob_profiles.by_name("нет такого") is None
    assert knob_profiles.by_name("") is None
