# nakedlunch — КАНОН КРУТИЛОК: имена, диапазоны, перевод интерфейс → ядро.
#
# ОТКУДА ЭТОТ ФАЙЛ. Он — выжившая половина `tests/test_knob_profiles.py`,
# который стерёг сразу две разные вещи: полку профилей крутилок (вырезана
# 2026-08-18 вместе с `core/knob_profiles.py`, надгробие в `api/server.py`) и
# сам канон `clean`. Канон ЖИВОЙ: по нему едут четыре пресета фронта и
# `nl_params` в настройках — `clean.knobs_from_profile` зовут `/api/generate`,
# `/api/pool/shape` и `/api/settings`. Уносить его вместе с полкой значило бы
# снять сторожа с работающего.
#
# Проверяется РЕЗУЛЬТАТ, а не наличие ключа: каждый перевод интерфейсной
# координаты в ядерную сверяется числом, а каждое «ворота» — тем, что ворота
# действительно закрылись.
#
# Прогон: .venv/bin/python -m pytest tests/test_канон_крутилок.py -q

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import clean


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
