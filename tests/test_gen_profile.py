# nakedlunch — профиль генерации: схема строфы ВМЕСТЕ с крутилками
# (2026-08-02, требование: строфа работает как профиль — положения крутилок плюс сама рифмовка). Тесты на реальных файлах во временном
# каталоге, без моков — как в test_sheets.py.
#
# Отдельно проверяется то, на чём я споткнулся при живой проверке: ключ
# настроек проходит ДВА независимых фильтра — список в роуте /api/settings и
# _ALLOWED в core/settings.py, — и пропуск в любом из них молча съедает
# значение. Схема тогда сохранилась, а крутилки нет.
#
# Прогон: .venv/bin/python -m pytest tests/test_gen_profile.py -q

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import clean
import settings as settings_mod
import stanza_profiles

КАТРЕН = [
    {"letter": "а", "min_syl": 8, "max_syl": 9},
    {"letter": "б", "min_syl": 8, "max_syl": 9},
    {"letter": "а", "min_syl": 8, "max_syl": 9},
    {"letter": "б", "min_syl": 8, "max_syl": 9},
]
КРУТИЛКИ = {"Источники": 0.9, "Банальность": 0.15, "Диссонанс": 0.25}


@pytest.fixture()
def свой_каталог(tmp_path, monkeypatch):
    """Профили и настройки — в tmp, чтобы тест не трогал данные пользователя."""
    monkeypatch.setattr(stanza_profiles, "DATA_DIR", tmp_path)
    monkeypatch.setattr(stanza_profiles, "PROFILES_PATH", tmp_path / "stanza_profiles.json")
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "settings.json")
    return tmp_path


def test_forma_hranit_tolko_karkas(свой_каталог):
    """РАУНД 50: расщепление. Форма строфы — это КАРКАС и ничего кроме.
    Требование (2026-08-03): каркас строфы и профиль настроек ставятся раздельно.. Раньше save() принимал третьим аргументом params, и выбор формы
    молча двигал ползунки."""
    stanza_profiles.save("Мой катрен", КАТРЕН)
    got = stanza_profiles.custom()
    assert len(got) == 1
    assert [l["letter"] for l in got[0]["lines"]] == ["а", "б", "а", "б"]
    assert set(got[0]) == {"name", "lines"}, "в форме не должно быть ничего, кроме каркаса"

    import inspect
    assert "params" not in inspect.signature(stanza_profiles.save).parameters


def test_krutilki_zhivut_na_svoey_polke(свой_каталог, monkeypatch):
    """Вторая половина расщепления: то, что ушло из формы, обязано где-то
    быть — иначе это не разделение, а потеря."""
    import knob_profiles
    monkeypatch.setattr(knob_profiles, "DATA_DIR", свой_каталог)
    monkeypatch.setattr(knob_profiles, "PROFILES_PATH", свой_каталог / "knob_profiles.json")
    knob_profiles.save("Мои", "алгоритм", КРУТИЛКИ)
    п = knob_profiles.by_name("Мои")
    for имя, v in КРУТИЛКИ.items():
        assert п["params"][имя] == v
    # и полки не пересекаются: форма о крутилках не знает, профиль — о каркасе
    stanza_profiles.save("Мой катрен", КАТРЕН)
    assert "lines" not in п
    assert "params" not in stanza_profiles.custom()[0]


def test_перезапись_по_имени_и_удаление(свой_каталог):
    stanza_profiles.save("Мой катрен", КАТРЕН)
    stanza_profiles.save("Мой катрен", КАТРЕН[:2])
    got = stanza_profiles.custom()
    assert len(got) == 1, "перезапись по имени не должна плодить дубли"
    assert len(got[0]["lines"]) == 2
    stanza_profiles.delete("Мой катрен")
    assert stanza_profiles.custom() == []


def test_настройки_пропускают_nl_params(свой_каталог):
    """Регрессия живой проверки: ключ терялся молча, потому что фильтров два."""
    settings_mod.write({"nl_params": {"params": КРУТИЛКИ, "mode": "классика"}})
    сохранено = settings_mod.read()["nl_params"]["params"]
    # Раунд 52: набор ручек на диске приводится к КАНОНУ (clean.KNOB_SPEC) —
    # раньше файл хранил ровно то, что прислал фронт, и таскал «Разнообразие»,
    # вырезанное ещё в Раунде 48. Присланные значения при этом обязаны доехать
    # без изменений, а недостающие — взять дефолт ядра.
    assert {k: сохранено[k] for k in КРУТИЛКИ} == КРУТИЛКИ
    assert set(сохранено) == set(clean.KNOB_SPEC)
    # Раунд 50: режим тоже обязан переживать перезапуск. Раньше он не
    # сохранялся вовсе — белый список роута его не пропускал, и переключатель
    # сбрасывался при каждом старте.
    assert settings_mod.read()["nl_params"]["mode"] == "классика"


def test_настройки_сливают_а_не_затирают(свой_каталог):
    """Крутилки пишутся при каждом движении ползунка; схема при этом обязана
    выживать, и наоборот."""
    settings_mod.write({"stanza": КАТРЕН, "stanza_profile": "Катрен перекрёстный"})
    settings_mod.write({"nl_params": {"params": {"Банальность": 0.5}}})
    итог = settings_mod.read()
    assert итог["stanza_profile"] == "Катрен перекрёстный"
    assert len(итог["stanza"]) == 4
    # значение доехало; остальные ручки добиты каноном (Раунд 52)
    assert итог["nl_params"]["params"]["Банальность"] == 0.5


def test_чужой_ключ_это_ошибка_а_не_тишина(свой_каталог):
    """Раунд 54. Раньше чужой ключ просто исчезал — и на этом молчании
    «одноразовый» перенос истории отработал десять раз подряд: он писал сюда
    отметку «сделано», её съедал белый список, и следующий запуск начинал
    заново. Теперь запись чужого ключа — громкая ошибка."""
    with pytest.raises(ValueError) as e:
        settings_mod.write({"nl_params": {"params": {}}, "мусор": 1})
    assert "мусор" in str(e.value)
    # и НИЧЕГО не записано: половина сохранённого хуже честного отказа
    assert settings_mod.read() == {}


def test_polka_cepochek_ushla_iz_nastroek(свой_каталог):
    """Раунд 50: nl_chain_profiles больше не ключ настроек — полка переехала в
    свой файл с валидатором. Здесь она лежала сырьём и проходила ДВА белых
    списка, и пропуск в любом молча съедал запись."""
    with pytest.raises(ValueError):
        settings_mod.write({"nl_chain_profiles": {"Старая": {"chain": []}}})
    assert "nl_chain_profiles" not in settings_mod.read()
