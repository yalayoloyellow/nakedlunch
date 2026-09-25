# ИСТОРИЯ ПРЯЧЕТ ПОКАЗАННОЕ ПО НОМЕРУ СТРОКИ, А НЕ ПО ТЕКСТУ (2026-09-03).
#
# ЧТО БЫЛО. Показанное вычиталось из выдачи по ТЕКСТУ, и чтобы перевести
# 5 400 текстов в номера строк, строился словарь «текст → номер» на 2.3 млн
# ключей: 5.4 секунды и сотни мегабайт при КАЖДОМ запуске. После того как маску
# активного пула перевели на колонку `src`, это осталось единственной причиной,
# по которой словарь ещё жил, — и всей ценой первой генерации.
#
# ЧТО СТАЛО. Движок кладёт номер строки в саму строку (`_ном`), фронт везёт его
# до истории, `mark_shown` записывает. Маска истории складывается из готовых
# номеров.
#
# ТРИ ВЕЩИ, БЕЗ КОТОРЫХ ЭТО БЫЛО БЫ ОПАСНО, и все три проверяются ниже:
#   · номер верен только для СВОЕГО состава строк — сверяется штамп;
#   · записи без номера (снятые раньше) переводятся словарём, как прежде;
#   · сирота — строка, которой в индексе нет, — помечается −1 «проверено»,
#     иначе она держала бы словарь живым вечно: её номер не появится никогда.
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))
sys.path.insert(0, str(КОРЕНЬ / "api"))

import nlindex  # noqa: E402
from corpus import Corpus  # noqa: E402


class _Идх:
    n = 10

    def text(self, i):
        return f"строка {i}"


class _МаленькийИндекс:
    def __init__(self, строки):
        self.строки = list(строки)
        self.n = len(self.строки)

    def text(self, i):
        return self.строки[i]


def _корпус(записи, штамп="штамп-1"):
    import time
    к = Corpus()
    к.index_stamp = штамп
    к.retention_days = 0            # 0 — «никогда не истекает», см. _expired
    for з in записи:
        к.history.append(dict({"shown_at": time.time(), "restored_at": None}, **з))
    return к


def test_номер_пишется_при_показе():
    к = Corpus()
    к.mark_shown([{"text": "первая", "template": "nakedlunch", "_ном": 7}])
    assert к.history[-1]["ном"] == 7


def test_маска_складывается_из_номеров():
    к = _корпус([{"text": "а", "ном": 2}, {"text": "б", "ном": 5}])
    номера, хвост = к.скрытые_номера("штамп-1")
    assert номера == {2, 5} and not хвост
    м = nlindex.маска_истории(_Идх(), номера, хвост)
    assert [i for i, v in enumerate(м) if v] == [2, 5]


def test_чужой_штамп_отдаёт_всё_текстами():
    """ГЛАВНЫЙ СТОРОЖ. Номер верен только для своего состава строк. Индекс
    перепечён — номера указывают в никуда, и спрятать по ним значило бы
    спрятать ЧУЖУЮ строку. Молча. Отдаём текстами: медленно, зато верно."""
    к = _корпус([{"text": "а", "ном": 2}])
    номера, хвост = к.скрытые_номера("другой-штамп")
    assert номера == set(), "номера приняты при разошедшемся штампе"
    assert хвост == {"а"}


def test_записи_без_номера_идут_текстами():
    """Снятые до этой правки. Их переводит словарь — один раз, при переводе."""
    к = _корпус([{"text": "а", "ном": 3}, {"text": "б"}])
    номера, хвост = к.скрытые_номера("штамп-1")
    assert номера == {3} and хвост == {"б"}


def test_сирота_помечается_и_больше_не_ищется():
    """Строки нет в индексе — её номер не появится никогда. Без пометки −1
    словарь строился бы ради неё при каждом запуске: у живой истории таких
    2 981 из 5 355, больше половины."""
    к = _корпус([{"text": "есть", "ном": None}, {"text": "нет", "ном": None}])
    for з in к.history:
        з.pop("ном")
    сделано = к.проставить_номера({"есть": 4}.get)
    assert сделано == 1
    assert к.history[0]["ном"] == 4
    assert к.history[1]["ном"] == -1, "сирота не помечена — словарь будет строиться вечно"
    # и после пометки хвост пуст: словарь больше не нужен
    номера, хвост = к.скрытые_номера("штамп-1")
    assert номера == {4} and хвост == set()


def test_перепривязка_пересчитывает_номера():
    """Состав сменился — номера обязаны обновиться или исчезнуть. Оставить
    старый значило бы прятать чужую строку."""
    к = _корпус([{"text": "а", "ном": 2}, {"text": "б", "ном": 9}])
    к.перепривязать("новый-штамп", {"а"}.__contains__, lambda т: т,
                    номер={"а": 111}.get)
    assert к.history[0]["ном"] == 111, "номер не пересчитан"
    assert к.history[1]["ном"] == -1, "у сироты остался номер прежнего состава"


@pytest.fixture(scope="module")
def сервер():
    import server
    return server


@pytest.mark.parametrize("строка", [
    {"text": "чужая строка", "template": "nakedlunch", "_ном": 0},
    {"text": "строка 0", "template": "nakedlunch",
     "_исходный": "чужой исходник", "_ном": 0},
    {"text": "за границей", "template": "nakedlunch", "_ном": 2},
], ids=["чужой-номер", "исходный-важнее-обрезка", "за-границей"])
def test_http_снимает_номер_который_не_указывает_на_эту_строку(
    сервер, monkeypatch, строка,
):
    """Клиентский `_ном` — подсказка, а не основание прятать чужую строку."""
    корпус = Corpus()
    monkeypatch.setattr(сервер, "CORPUS", корпус)
    monkeypatch.setattr(корпус, "save", lambda: None)
    monkeypatch.setattr(сервер.stats_mod, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        сервер.nlindex, "load", lambda: _МаленькийИндекс(["строка 0", "строка 1"]))

    ответ = сервер.app.test_client().post(
        "/api/history/mark_shown", json={"items": [строка]})

    assert ответ.status_code == 200
    assert корпус.history[-1]["text"] == строка["text"], (
        "неверный номер не должен выбрасывать сам показанный текст из истории")
    assert "ном" not in корпус.history[-1], (
        "сервер принял номер, который в текущем индексе указывает на другую "
        "строку или лежит за его границей")


def test_http_сохраняет_проверенный_номер(сервер, monkeypatch):
    """Без `_исходный` сверяем показанный текст; с ним — полный текст корпуса."""
    корпус = Corpus()
    monkeypatch.setattr(сервер, "CORPUS", корпус)
    monkeypatch.setattr(корпус, "save", lambda: None)
    monkeypatch.setattr(сервер.stats_mod, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        сервер.nlindex, "load", lambda: _МаленькийИндекс(["строка 0", "полная строка 1"]))

    ответ = сервер.app.test_client().post("/api/history/mark_shown", json={"items": [
        {"text": "строка 0", "template": "nakedlunch", "_ном": 0},
        {"text": "обрезок", "template": "nakedlunch",
         "_исходный": "полная строка 1", "_ном": 1},
    ]})

    assert ответ.status_code == 200
    assert [з.get("ном") for з in корпус.history] == [0, 1]
    assert корпус.history[1]["в_корпусе"] == "полная строка 1"


@pytest.mark.parametrize("дописано", [0, 2], ids=["только-сироты", "две-записи"])
def test_журнал_считает_хвост_после_проставления_номеров(
    сервер, monkeypatch, tmp_path, дописано,
):
    """`хвост` — множество текстов, `сделано` — число записей; их не вычитают.

    Один текст может жить и в истории, и в избранном: тогда две дописанные
    записи при одном старом тексте давали в журнале «осталось −1».
    """
    class Корпус:
        index_stamp = "2@маленький"

        def __init__(self):
            self.проверок_хвоста = 0
            self.сохранений = 0

        def скрытые_номера(self, _штамп):
            self.проверок_хвоста += 1
            if self.проверок_хвоста == 1:
                return set(), {"один текст в двух списках"}
            return {0}, set()

        def проставить_номера(self, номер):
            ожидается = None if дописано == 0 else 0
            assert номер("один текст в двух списках") == ожидается
            return дописано

        def save(self):
            self.сохранений += 1

    корпус = Корпус()
    индекс = _МаленькийИндекс(["один текст в двух списках", "другая строка"])
    записи = []
    monkeypatch.setattr(сервер, "CORPUS", корпус)
    monkeypatch.setattr(сервер, "_ПРОГРЕВ", {
        "этап": "корпус", "начат": time.time(), "готов": False, "этапы": []})
    monkeypatch.setattr(сервер, "_ВЕС_ФАЙЛ", tmp_path / "прогрев.json")
    monkeypatch.setattr(сервер, "_перепривязать_историю", lambda: None)
    monkeypatch.setattr(сервер.nlindex, "load", lambda: индекс)
    monkeypatch.setattr(сервер.nlindex, "прогреть", lambda _idx: None)
    monkeypatch.setattr(сервер.nlindex, "штамп", lambda _idx: "2@маленький")
    monkeypatch.setattr(
        сервер.nlindex, "text_ids",
        lambda _idx: ({"один текст в двух списках": 0} if дописано else {}))
    monkeypatch.setattr(
        сервер.журнал, "запись", lambda *args, **_kwargs: записи.append(args))

    сервер._прогрев()

    assert корпус.проверок_хвоста == 2, (
        "после миграции сервер не спросил Corpus о реально оставшемся хвосте")
    сообщения = [str(args[1]) for args in записи if len(args) > 1]
    assert any(f"дописано {дописано}" in с for с in сообщения)
    assert any("осталось без номера 0" in с for с in сообщения)
    assert all("осталось без номера -" not in с for с in сообщения)
    assert корпус.сохранений == 1


def test_staryy_text_ids_ne_otkatyvaet_istoriyu_posle_reload(
    сервер, monkeypatch,
):
    """Долгая карта прежнего индекса не переписывает номера нового."""
    старый = object()
    новый = object()
    загрузки = iter([старый, новый])

    class Корпус:
        index_stamp = "исходный"
        изменений = 0

        def перепривязать(self, *_args, **_kwargs):
            self.изменений += 1
            raise AssertionError("старая карта дошла до истории")

        def save(self):
            raise AssertionError("старая карта сохранилась")

    корпус = Корпус()
    monkeypatch.setattr(сервер, "CORPUS", корпус)
    monkeypatch.setattr(сервер.nlindex, "load", lambda: next(загрузки))
    monkeypatch.setattr(сервер.nlindex, "штамп", lambda idx: "штамп-старого")
    monkeypatch.setattr(сервер.nlindex, "text_ids", lambda idx: {"строка": 0})

    сервер._перепривязать_историю()

    assert корпус.изменений == 0


def test_migraciya_nomerov_ne_primenyaet_kartu_prezhnego_indeksa(
    сервер, monkeypatch, tmp_path,
):
    старый = object()
    новый = object()
    # карты прогрева, начало миграции, финальная проверка перед записью
    загрузки = iter([старый, старый, новый])

    class Корпус:
        index_stamp = "штамп-старого"

        def скрытые_номера(self, _штамп):
            return set(), {"строка"}

        def проставить_номера(self, _номер):
            raise AssertionError("старая карта дошла до истории")

        def save(self):
            raise AssertionError("старая карта сохранилась")

    monkeypatch.setattr(сервер, "CORPUS", Корпус())
    monkeypatch.setattr(сервер, "_ПРОГРЕВ", {
        "этап": "корпус", "начат": time.time(), "готов": False, "этапы": []})
    monkeypatch.setattr(сервер, "_ВЕС_ФАЙЛ", tmp_path / "прогрев.json")
    monkeypatch.setattr(сервер, "_перепривязать_историю", lambda: None)
    monkeypatch.setattr(сервер.nlindex, "load", lambda: next(загрузки))
    monkeypatch.setattr(сервер.nlindex, "прогреть", lambda _idx: None)
    monkeypatch.setattr(
        сервер.nlindex, "штамп",
        lambda idx: "штамп-старого" if idx is старый else "штамп-нового")
    monkeypatch.setattr(сервер.nlindex, "text_ids", lambda _idx: {"строка": 0})

    сервер._прогрев()

    assert сервер._ПРОГРЕВ["готов"] is True


def test_параллельные_запросы_не_вклиниваются_между_mutate_и_save(
    сервер, monkeypatch,
):
    """Две HTTP-записи истории проходят целыми парами: mutate, затем save."""
    class ИсторияСДатчиком:
        def __init__(self):
            self._сторож = threading.Lock()
            self._поток = threading.local()
            self._незавершённых = 0
            self.пересечение = False
            self.первый_сохраняет = threading.Event()
            self.второй_изменил = threading.Event()

        def mark_shown(self, items, theme="", семя=None):
            имя = items[0]["text"]
            self._поток.имя = имя
            with self._сторож:
                if self._незавершённых:
                    self.пересечение = True
                self._незавершённых += 1
            if имя == "вторая":
                self.второй_изменил.set()

        def save(self):
            if self._поток.имя == "первая":
                self.первый_сохраняет.set()
                # Без серверной критической секции второй mutate успевает сюда.
                self.второй_изменил.wait(1.0)
            with self._сторож:
                self._незавершённых -= 1

        def stats(self):
            return {"accepted": 0, "history_total": 0,
                    "history_hidden": 0, "retention_days": 0}

    корпус = ИсторияСДатчиком()
    ответы = {}
    monkeypatch.setattr(сервер, "CORPUS", корпус)
    monkeypatch.setattr(сервер.stats_mod, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        сервер.nlindex, "load", lambda: _МаленькийИндекс(["первая", "вторая"]))

    def показать(имя, номер):
        ответы[имя] = сервер.app.test_client().post(
            "/api/history/mark_shown",
            json={"items": [{"text": имя, "template": "nakedlunch", "_ном": номер}]},
        ).status_code

    первый = threading.Thread(target=показать, args=("первая", 0))
    первый.start()
    assert корпус.первый_сохраняет.wait(2), "первый запрос не дошёл до save"
    второй = threading.Thread(target=показать, args=("вторая", 1))
    второй.start()
    первый.join(3)
    второй.join(3)

    assert not первый.is_alive() and not второй.is_alive(), "запросы зависли"
    assert ответы == {"первая": 200, "вторая": 200}
    assert not корпус.пересечение, (
        "вторая мутация истории началась до save первой — общий снимок можно "
        "записать в промежуточном состоянии")


@pytest.mark.skipif(nlindex.load() is None, reason="индекс не испечён")
def test_на_живом_индексе_номер_указывает_на_свой_текст():
    """Сверка на настоящих данных: строка, отданная движком, по своему номеру
    читается из индекса той же самой."""
    import clean
    import filters
    import nlbridge
    idx = nlindex.load()
    с = clean.stanza_spec([{"letter": б, "min_syl": 8, "max_syl": 9} for б in "абаб"])
    строки = filters.run([], clean.knobs({"shortlist": 8}), Corpus(), nl_fragments=None,
                         rhyme=clean.stanza_letters(с), stanza=с, семя=3,
                         книги=nlbridge.активные_книги())["shortlist"]
    assert строки, "прогон пуст — тест ни о чём"
    for r in строки:
        н = r.get("_ном")
        assert isinstance(н, int) and 0 <= н < idx.n, f"нет номера у {r['text']!r}"
        свой = idx.text(н)
        # подрезанная строка показывается короче исходной — сверяем с исходной
        assert свой == r.get("_исходный") or свой == r["text"], (
            f"номер {н} указывает на другую строку:\n  в индексе {свой!r}\n"
            f"  в выдаче  {r['text']!r}")
