# nakedlunch — имена крутилок на диске обязаны быть каноном (Раунд 52).
#
# ЧТО НАШЛОСЬ. В data/settings.json пользователя, в `nl_params.params`, лежал
# ключ «Разнообразие» — крутилка, вырезанная в Раунде 48, — и НЕ лежали пять
# живых: «Мат», «Клаузула», «Диссонанс», «Связность», «Повтор». Мёртвый ключ
# уезжал в КАЖДОМ запросе генерации, где домен молча его выбрасывал.
# (Из тех пяти «Связность» удалена 2026-08-21, «Диссонанс» — 2026-08-29 вместе
# с темой. Список оставлен как запись находки: чинилось не содержимое канона,
# а то, что имена на диске за ним не следуют. Сегодня они пополнили ровно ту
# половину, ради которой файл и написан, — мёртвые ключи в чужом файле.)
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


# «Мелодичность», «Банальность», «Источники» и «Диссонанс» здесь — НАРОЧНО:
# старый файл настроек с диска несёт удалённые ключи, и чтение обязано их
# пережить, выбросив. Последние два удалены 2026-08-29 (генератор и тема), и
# у пользователя на диске они лежат прямо сейчас.
СТАРЫЙ = {"nl_params": {"mode": "алгоритм", "params": {
    "Источники": 1.0, "Точность рифм": 0.25, "Мелодичность": 0.35,
    "Банальность": 0.35, "Разнообразие": 0.5, "Диссонанс": 0.7,
    "Внутренняя рифма": 1}}}


def test_chtenie_vybrasyvaet_myortvyy_klyuch(файл):
    файл.write_text(json.dumps(СТАРЫЙ, ensure_ascii=False), "utf-8")
    p = settings_mod.read()["nl_params"]["params"]
    assert "Разнообразие" not in p
    assert "Мелодичность" not in p and "Банальность" not in p  # удалены
    assert "Источники" not in p and "Диссонанс" not in p       # удалены 2026-08-29
    # живое сохранено, а не сброшено заодно с мёртвым. Раньше живым здесь
    # стояли «Источники» — ручка сама умерла 2026-08-29, и живое взято другое
    # (не «Мат» и не «Повтор»: их дефолты стережёт соседний тест ниже).
    assert p["Внутренняя рифма"] == 1
    # старая «Точность рифм» с диска переведена в маску ярусов, не потеряна
    assert p["Ярусы рифмы"] == 3


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
    # Ползунки берём ЖИВЫЕ и притом НЕ входящие в KNOB_CLASSIC — иначе
    # проверка «не обрезаем» ничего бы не проверяла. Живых мнений два: «Ярусы
    # рифмы» и «Повтор» (раньше здесь стояли «Источники» и «Диссонанс», обе
    # ручки удалены 2026-08-29, и тест зеленел бы на неизвестных ключах).
    assert not (set(clean.KNOB_OPINIONS) & set(clean.KNOB_CLASSIC))
    файл.write_text(json.dumps({"nl_params": {"mode": "классика", "params": {
        "Ярусы рифмы": 15, "Повтор": 1}}}, ensure_ascii=False), "utf-8")
    np = settings_mod.read()["nl_params"]
    assert np["mode"] == "классика"
    assert np["params"]["Ярусы рифмы"] == 15 and np["params"]["Повтор"] == 1


def test_musornyy_rezhim_i_musornye_znacheniya(файл):
    файл.write_text(json.dumps({"nl_params": {"mode": "чушь", "params": {
        "Мат": "не число", "Клаузула": 99}}}, ensure_ascii=False), "utf-8")
    np = settings_mod.read()["nl_params"]
    assert np["mode"] == clean.MODE_ALGO
    assert np["params"]["Мат"] == -1.0        # мусор → дефолт
    assert np["params"]["Клаузула"] == 7      # вне маски 1..7 → в диапазон


def test_bez_nl_params_nichego_ne_pridumyvaetsya(файл):
    """Не было ключа — не появляется: иначе файл обрастал бы разделами,
    которых пользователь не заводил."""
    файл.write_text(json.dumps({"stanza_profile": "Катрен"}, ensure_ascii=False), "utf-8")
    assert "nl_params" not in settings_mod.read()


def test_zapis_lechit_i_to_chto_prislal_front(файл):
    """ГЛАВНЫЙ путь мёртвого ключа: фронт шлёт `nl_params` при каждом движении
    ползунка, и без починки НА ЗАПИСИ его набор ложится на диск как есть —
    сколько бы раз чтение ни лечило прежнее содержимое."""
    # Живое значение — «Ярусы рифмы» (2026-08-29: здесь стояли «Источники»
    # 0.8, ручка удалена вместе с генератором и стала бы просто третьим
    # мёртвым ключом, то есть проверка «живое доезжает» исчезла бы молча).
    settings_mod.write({"nl_params": {"mode": "алгоритм", "params": {
        "Ярусы рифмы": 15, "Разнообразие": 0.5, "Выдуманная ручка": 1}}})
    сырое = json.loads(файл.read_text("utf-8"))["nl_params"]["params"]
    assert "Разнообразие" not in сырое and "Выдуманная ручка" not in сырое
    assert set(сырое) == set(clean.KNOB_SPEC)
    assert сырое["Ярусы рифмы"] == 15, "живое значение обязано доехать"


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
    # chain_profiles.py был третьим в этом списке и ушёл 2026-08-18 вместе с
    # пайплайном; knob_profiles.py был вторым и ушёл в тот же день вместе с
    # полкой профилей крутилок (надгробие в api/server.py) — полка осталась
    # одна. Список из одного элемента правило не ослабляет: оно про то, как
    # полка пишет, и заведётся новая — впишется сюда же.
    for имя in ("stanza_profiles.py",):
        текст = (корень / имя).read_text("utf-8")
        assert "PROFILES_PATH.write_text" not in текст, (
            f"{имя} пишет полку сама, минуя склад — три правила надёжности обойдены")
        assert "склад.писать" in текст, f"{имя} не пишет через склад вовсе"


# ОСИ, КОТОРЫЕ НЕ ЧИСЛА (2026-08-30) — полосы шкал и доли сортов.
#
# ЛОВУШКА, НА КОТОРОЙ ПРОЕКТ ГОРЕЛ ТРИЖДЫ: перечень этих осей лежал в трёх
# местах сразу (clean.knob_profile, core/settings.py, роут /api/settings), и
# каждый новый список молча съедал ось, которую в него забыли вписать. Так
# терялись полосы редкости (2026-08-26) и полоса плотности звука (сегодня, и
# поймана она живым кругом настроек, а не тестом). Теперь список один —
# `clean.ОСИ_ПОЛОС` / `clean.ОСИ_ДОЛЕЙ`, — и сторож ниже проверяет, что круг
# «записал → прочитал» проходят ВСЕ оси канона, а не те, что кто-то помнил.

def test_kazhdaya_os_polos_perezhivaet_krug(файл):
    полосы = {ось: f"{i}-{i + 5}" for i, ось in enumerate(clean.ОСИ_ПОЛОС, start=10)}
    settings_mod.write({"nl_params": {"mode": clean.MODE_ALGO, "params": {},
                                      "полосы": полосы, "доли": {}}})
    прочли = settings_mod.read()["nl_params"]["полосы"]
    assert прочли == полосы, f"круг настроек потерял оси: {set(полосы) - set(прочли)}"


def test_kazhdaya_os_doley_perezhivaet_krug(файл):
    доли = {ось: f"1:{20 + i}" for i, ось in enumerate(clean.ОСИ_ДОЛЕЙ)}
    settings_mod.write({"nl_params": {"mode": clean.MODE_ALGO, "params": {},
                                      "полосы": {}, "доли": доли}})
    прочли = settings_mod.read()["nl_params"]["доли"]
    assert прочли == доли, f"круг настроек потерял оси: {set(доли) - set(прочли)}"


def test_profil_i_nastroyki_znayut_odni_i_te_zhe_osi():
    """Именованный профиль и последние положения панели обязаны сходиться в
    осях: разойдутся — и профиль будет терять то, что панель помнит."""
    проф = clean.knob_profile({"name": "x", "mode": clean.MODE_ALGO, "params": {},
                              "полосы": {}, "доли": {}})
    assert set(проф["полосы"]) == set(clean.ОСИ_ПОЛОС)
    assert set(проф["доли"]) == set(clean.ОСИ_ДОЛЕЙ)
