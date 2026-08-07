# nakedlunch — имена крутилок на диске обязаны быть каноном (Раунд 52).
#
# ЧТО НАШЛОСЬ. В data/settings.json пользователя, в `nl_params.params`, лежал
# ключ «Разнообразие» — крутилка, вырезанная в Раунде 48, — и НЕ лежали пять
# живых: «Мат», «Клаузула», «Диссонанс», «Связность», «Повтор». Мёртвый ключ
# уезжал в КАЖДОМ запросе генерации, где домен молча его выбрасывал.
#
# Само по себе это ничего не ломало: `clean.knob_params` отбрасывает чужое.
# Но файл — то, что пользователь открывает руками, и он показывал набор ручек,
# которого в приложении нет уже четыре раунда.
#
# ГРАНИЦА, чтобы не размыть §6: своих правил здесь не появляется. Имена и
# диапазоны берутся у `clean.knob_params` — чинятся ИМЕНА на диске, которые
# не чинил никто, а не значения, которые и так клампятся на входе в домен.
#
# Прогон: .venv/bin/python -m pytest tests/test_settings_canon.py -q

import json
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

import clean
import settings as settings_mod


@pytest.fixture()
def файл(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", p)
    return p


СТАРЫЙ = {"nl_params": {"mode": "алгоритм", "params": {
    "Источники": 1.0, "Точность рифм": 0.25, "Мелодичность": 0.35,
    "Банальность": 0.35, "Разнообразие": 0.5}}}


def test_chtenie_vybrasyvaet_myortvyy_klyuch(файл):
    файл.write_text(json.dumps(СТАРЫЙ, ensure_ascii=False), "utf-8")
    p = settings_mod.read()["nl_params"]["params"]
    assert "Разнообразие" not in p
    # живое сохранено, а не сброшено заодно с мёртвым
    assert p["Источники"] == 1.0 and p["Мелодичность"] == 0.35


def test_chtenie_dobivaet_zhivye_klyuchi(файл):
    файл.write_text(json.dumps(СТАРЫЙ, ensure_ascii=False), "utf-8")
    p = settings_mod.read()["nl_params"]["params"]
    assert set(p) == set(clean.KNOB_SPEC), "набор ручек на диске обязан быть каноном"
    # добитые берут ДЕФОЛТ ядра, а не ноль
    assert p["Мат"] == -1.0 and p["Повтор"] == 0


def test_zapis_lechit_fayl_na_diske(файл):
    """Иначе старый файл лечился бы только в памяти, а на диске мёртвый ключ
    жил бы дальше."""
    файл.write_text(json.dumps(СТАРЫЙ, ensure_ascii=False), "utf-8")
    settings_mod.write({"stanza_profile": "Катрен"})
    сырое = json.loads(файл.read_text("utf-8"))
    assert "Разнообразие" not in сырое["nl_params"]["params"]
    assert set(сырое["nl_params"]["params"]) == set(clean.KNOB_SPEC)
    assert сырое["stanza_profile"] == "Катрен"


def test_rezhim_klampitsya_no_polozheniya_ne_teryayutsya(файл):
    """Классику НЕ обрезаем до KNOB_CLASSIC, в отличие от именованного
    профиля: это последние положения ПАНЕЛИ, и переключение в классику и
    обратно не должно стирать, где стояли ползунки."""
    файл.write_text(json.dumps({"nl_params": {"mode": "классика", "params": {
        "Источники": 0.3, "Диссонанс": 0.9}}}, ensure_ascii=False), "utf-8")
    np = settings_mod.read()["nl_params"]
    assert np["mode"] == "классика"
    assert np["params"]["Источники"] == 0.3 and np["params"]["Диссонанс"] == 0.9


def test_musornyy_rezhim_i_musornye_znacheniya(файл):
    файл.write_text(json.dumps({"nl_params": {"mode": "чушь", "params": {
        "Мат": "не число", "Клаузула": 99}}}, ensure_ascii=False), "utf-8")
    np = settings_mod.read()["nl_params"]
    assert np["mode"] == clean.MODE_ALGO
    assert np["params"]["Мат"] == -1.0        # мусор → дефолт
    assert np["params"]["Клаузула"] == 3      # вне диапазона → в диапазон


def test_bez_nl_params_nichego_ne_pridumyvaetsya(файл):
    """Не было ключа — не появляется: иначе файл обрастал бы разделами,
    которых пользователь не заводил."""
    файл.write_text(json.dumps({"stanza_profile": "Катрен"}, ensure_ascii=False), "utf-8")
    assert "nl_params" not in settings_mod.read()


def test_zapis_lechit_i_to_chto_prislal_front(файл):
    """ГЛАВНЫЙ путь мёртвого ключа: фронт шлёт `nl_params` при каждом движении
    ползунка, и без починки НА ЗАПИСИ его набор ложится на диск как есть —
    сколько бы раз чтение ни лечило прежнее содержимое."""
    settings_mod.write({"nl_params": {"mode": "алгоритм", "params": {
        "Источники": 0.8, "Разнообразие": 0.5, "Выдуманная ручка": 1}}})
    сырое = json.loads(файл.read_text("utf-8"))["nl_params"]["params"]
    assert "Разнообразие" not in сырое and "Выдуманная ручка" not in сырое
    assert set(сырое) == set(clean.KNOB_SPEC)
    assert сырое["Источники"] == 0.8, "живое значение обязано доехать"


# ---------------------------------------------------------------------------
# ПОТЕРЯ ПРОФИЛЕЙ (Раунд 57). 2026-08-05 у пользователя из data/settings.json
# исчезли ВСЕ профили сцены фристайла — остался один ключ `nl_view`,
# записанный последним. Механизм: `read()` намеренно молчалив и на битом файле
# возвращает `{}` (иначе программа не откроется), а `write()` сливал payload
# именно в этот `{}` и записывал результат поверх. Одно неудачное чтение —
# недописанный файл, гонка двух окон, что угодно — стирало всё, чего в payload
# не было. Плюс сама запись шла `write_text`, то есть с усечением на месте:
# прерваться посреди неё значило оставить на диске ровно такой обрубок.
#
# Сторожа два, потому что и дыр было две: не писать поверх непрочитанного, и
# не оставлять обрубков.

def test_zapis_ne_zatiraet_nechitaemyy_fayl(файл):
    """Битый файл — это «не знаю, что там», а не «там пусто»."""
    settings_mod.write({"nl_palette": {"было": 1}})
    файл.write_text('{"nl_palette": {"бы', "utf-8")     # обрубок
    with pytest.raises(ValueError, match="не разбирается"):
        settings_mod.write({"nl_view": {"новое": 2}})
    assert файл.read_text("utf-8") == '{"nl_palette": {"бы', "файл тронули"


def test_pustoy_i_otsutstvuyushchiy_fayl_pishutsya_kak_ran6she(файл):
    """Первый запуск и пустой файл — законные случаи, запись обязана пройти."""
    settings_mod.write({"nl_view": {"a": 1}})           # файла не было
    assert settings_mod.read()["nl_view"] == {"a": 1}
    файл.write_text("   ", "utf-8")
    settings_mod.write({"nl_view": {"b": 2}})
    assert settings_mod.read()["nl_view"] == {"b": 2}


def test_zapis_ostavlyaet_kopiyu_predydushchego(файл):
    """Копия предыдущего состояния — то, из чего можно вернуть потерянное."""
    settings_mod.write({"nl_fs_profiles": {"list": [{"id": "p1"}]}})
    settings_mod.write({"nl_view": {"a": 1}})
    копия = json.loads(settings_mod._запасной().read_text("utf-8"))
    assert копия["nl_fs_profiles"]["list"] == [{"id": "p1"}]


def test_soseddniy_klyuch_ne_propadaet(файл):
    """Главное свойство: запись одного ключа не трогает остальные."""
    settings_mod.write({"nl_fs_profiles": {"list": [{"id": "p1"}]}})
    settings_mod.write({"nl_view": {"a": 1}})
    итог = settings_mod.read()
    assert итог["nl_fs_profiles"]["list"] == [{"id": "p1"}]
    assert итог["nl_view"] == {"a": 1}


# ---------------------------------------------------------------------------
# ПОЛКИ ТОЖЕ НАДЁЖНЫ (Раунд 57). Потеря профилей сцены научила чинить настройки,
# но полки — профили крутилок, цепочек, форм строфы — писались тем же
# `write_text` и защиты не получили: тот же сбой унёс бы и их, причём тихо.
# Правила теперь в одном месте (core/склад.py), и сторож проверяет их там же:
# иначе следующий склад, который кто-то заведёт, снова забудет одно из трёх.

def test_sklad_ne_pishet_poverh_neprochitannogo(tmp_path):
    import склад
    п = tmp_path / "полка.json"
    склад.писать(п, {"было": 1})
    п.write_text('{"бы', "utf-8")                    # обрубок
    with pytest.raises(ValueError, match="не разбирается"):
        склад.писать(п, {"новое": 2})
    assert п.read_text("utf-8") == '{"бы', "склад тронул непрочитанный файл"


def test_sklad_pishet_celikom_i_hranit_kopiyu(tmp_path):
    import склад
    п = tmp_path / "полка.json"
    склад.писать(п, [{"имя": "первый"}])
    склад.писать(п, [{"имя": "второй"}])
    assert склад.читать(п, None) == [{"имя": "второй"}]
    assert json.loads(склад.копия(п).read_text("utf-8")) == [{"имя": "первый"}]
    # обрубков не остаётся: временный файл подменяется одним вызовом
    assert not list(tmp_path.glob("*.новый"))


def test_polki_hodyat_cherez_sklad():
    """Свойство, а не реализация: ни одна полка не смеет писать сама.

    Проверка по исходнику намеренно — она ловит именно то, что ломается при
    добавлении новой полки: человек копирует соседний модуль вместе с его
    `write_text` и обходит все три правила разом."""
    from pathlib import Path as _P
    корень = _P(__file__).resolve().parent.parent / "core"
    for имя in ("knob_profiles.py", "chain_profiles.py", "stanza_profiles.py"):
        текст = (корень / имя).read_text("utf-8")
        assert "PROFILES_PATH.write_text" not in текст, (
            f"{имя} пишет полку сама, минуя склад — три правила надёжности обойдены")
        assert "склад.писать" in текст, f"{имя} не пишет через склад вовсе"
