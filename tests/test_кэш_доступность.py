# nakedlunch — СТОРОЖ СПРАШИВАЕТ ПРО ТО, ЧТО ЧИТАЕТ (2026-08-18).
#
# ЧТО СЛУЧИЛОСЬ. Раунд 57 перевёл кэш ударений на построчный формат, и
# `кэш.читать_всё()` стал предпочитать `nl_rhyme.jsonl`. А два сторожа снаружи
# остались спрашивать про СТАРЫЙ файл — `_NL_RHYME_PATH.exists()`, то есть про
# `nl_rhyme.json`:
#
#   core/filters.py           `warm_caches`
#   tools/build_nl_index.py   `build()`
#
# Замер на временном доме, где лежал только `.jsonl`: `есть_строчный()` True,
# `читать_всё()` отдаёт запись, `_NL_RHYME_PATH.exists()` False, а после
# `warm_caches()` в кэше НОЛЬ записей.
#
# ЧЕМ ГРОЗИЛО. Убери старый файл (832 МБ, читателей — только эти сторожа) — и
# сборка индекса при ПОЛНОМ кэше рядом выходит с «печь нечего». Это ровно та
# глухая петля, что по надгробию в `tools/build_nl_index.py` уже стоила
# 251 727 строк вне индекса, и молча: вывод сборки уходил в /dev/null.
#
# ПОЧЕМУ ТЕСТ ИМЕННО ТАКОЙ. Проверять «условие написано правильно» нечем —
# написать его неправильно можно бесконечным числом способов. Поэтому здесь
# проверяется ИСХОД в том самом доме, в который дом придёт после переноса
# старого файла: лежит ОДИН `.jsonl`, и оба пути обязаны считать кэш
# доступным и прочитать его до записей.
#
# Прогон: NAKEDLUNCH_HOME=/tmp/дом-рифмы .venv/bin/python -m pytest \
#             tests/test_кэш_доступность.py -q

import json
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))
sys.path.insert(0, str(КОРЕНЬ / "tools"))

import кэш

# Форма записи — как у tools/build_nl_rhyme.py (`_поля_фрагмента`).
ЗАПИСИ = {
    "кот сидел на подоконнике": {
        "key": "ике", "span": [14, 24], "banal": 3.1, "taut": False, "content": 3,
        "lemmas": ["кот", "сидеть", "подоконник"],
        "tokens": ["кот", "сидел", "подоконнике"]},
    "дождь стучал по крыше": {
        "key": "ыше", "span": [16, 21], "banal": 2.8, "taut": False, "content": 3,
        "lemmas": ["дождь", "стучать", "крыша"],
        "tokens": ["дождь", "стучал", "крыше"]},
}


@pytest.fixture()
def только_построчный(tmp_path, monkeypatch):
    """Дом, где НЕТ старого `nl_rhyme.json` — только построчный `.jsonl`.

    Это не выдуманное состояние: ровно в него дом приходит после переноса
    832-мегабайтного файла, у которого не осталось читателей."""
    monkeypatch.setattr(кэш, "СТАРЫЙ", tmp_path / "nl_rhyme.json")
    monkeypatch.setattr(кэш, "СТРОЧНЫЙ", tmp_path / "nl_rhyme.jsonl")
    with кэш.Писатель() as п:
        for текст, поля in ЗАПИСИ.items():
            п.запиши(текст, поля)
    assert кэш.есть_строчный(), "фикстура не создала построчный кэш"
    assert not кэш.СТАРЫЙ.exists(), "фикстура оставила старый файл — дом не тот"
    return tmp_path


class ЗаглушкаСклада:
    def __init__(self, тексты):
        self._t = list(тексты)

    def get_all_fragments(self):
        return [{"id": str(i), "text": t, "corpus_id": "к"} for i, t in enumerate(self._t)]


def test_kesh_dostupen_bez_starogo_fayla(только_построчный):
    """Загрузчик отвечает про СЕБЯ, а не про один из своих файлов."""
    assert кэш.есть(), \
        "кэш читает .jsonl, но на вопрос «есть ли что читать» отвечает «нет»"
    assert len(кэш.читать_всё()) == len(ЗАПИСИ)


def test_warm_caches_chitaet_strochnyy_kesh(только_построчный, monkeypatch):
    """ГЛАВНОЕ ПО filters: при одном `.jsonl` прогрев обязан набрать записи.

    Индекс глушится не для удобства — это ЕДИНСТВЕННАЯ ветка, в которой кэш
    вообще грузится (Раунд 34: при живом индексе `warm_caches` уходит сразу и
    пустой `_NL_RHYME` — договор, а не поломка)."""
    import filters
    import nlindex
    monkeypatch.setattr(nlindex, "available", lambda: False)
    monkeypatch.setattr(filters, "_NL_RHYME", {})

    filters.warm_caches()

    assert len(filters._NL_RHYME) == len(ЗАПИСИ), (
        "прогрев оставил кэш пустым при полном построчном файле: "
        f"{len(filters._NL_RHYME)} записей")
    assert filters._NL_RHYME["дождь стучал по крыше"]["key"] == "ыше", \
        "записи прочитаны, но поля потерялись"


def test_sborka_indeksa_ne_govorit_pech_nechego(только_построчный, tmp_path, monkeypatch):
    """ГЛАВНОЕ ПО СБОРКЕ ИНДЕКСА, и оно же — тот самый дорогой случай.

    Индекс НА МЕСТЕ (`available()` True) — значит `warm_caches` честно уходит
    сразу и оставляет `_NL_RHYME` пустым. Дальше сборщик обязан прочитать кэш
    сам. Когда он спрашивал про старый файл, здесь был выход с ошибкой при
    полном кэше рядом — и индекс не перепекался НИКОГДА.

    Печём по-настоящему, до `meta.json`: возврат 0 без индекса на диске —
    это не доказательство."""
    import filters
    import nlbridge
    import nlindex
    import build_nl_index as би

    monkeypatch.setattr(nlindex, "available", lambda: True)
    monkeypatch.setattr(filters, "_NL_RHYME", {})
    monkeypatch.setattr(nlbridge, "open_store", lambda: ЗаглушкаСклада(ЗАПИСИ))
    monkeypatch.setattr(би, "OUT", tmp_path / "nl_index")
    monkeypatch.setattr(би, "СТАТУС", tmp_path / "nl_index.status.json")

    код = би.build()

    assert код == 0, "сборка индекса сказала «печь нечего» при полном .jsonl"
    мета = json.loads((tmp_path / "nl_index" / "meta.json").read_text("utf-8"))
    assert мета["n"] == len(ЗАПИСИ), f"в индекс попало {мета['n']} записей"


def test_rekey_idyot_potokom_a_ne_v_staryy_fayl(только_построчный, monkeypatch):
    """`--rekey` был единственным режимом БЕЗ развилки на построчный формат.

    Сторож на саму поломку: `main()` дёргается ровно так, как её зовёт
    пользователь, и старый путь заминирован. До развилки этот режим на таком
    доме выходил с «нечего переписывать»."""
    import build_nl_rhyme as сб

    звали = []
    monkeypatch.setattr(сб, "rekey_потоком", lambda: звали.append(True) or 0)
    monkeypatch.setattr(сб, "_write_status", lambda *a, **k: None)
    monkeypatch.setattr(сб, "_ПИШЕМ_СТАТУС", False)

    def нельзя(*a, **k):
        raise AssertionError("--rekey полез в старый файл, которого никто не читает")

    monkeypatch.setattr(сб, "rekey", нельзя)
    monkeypatch.setattr(сб, "_write_out", нельзя)
    monkeypatch.setattr(sys, "argv", ["build_nl_rhyme.py", "--rekey"])

    assert сб.main() == 0
    assert звали == [True], "потоковая перепись ключей не позвана"


def test_rekey_potokom_pishet_v_chitaemyy_fayl(только_построчный, monkeypatch):
    """И сама перепись доходит до ЧИТАТЕЛЯ, не трогая поля качества.

    Акцентуатор подменён — он весит 1.3 ГБ и к маршрутизации файлов отношения
    не имеет; правило ключа проверяют другие тесты."""
    import build_nl_rhyme as сб

    monkeypatch.setattr(сб, "_write_status", lambda *a, **k: None)
    monkeypatch.setattr(сб, "акцентуатор", lambda: object())
    monkeypatch.setattr(сб, "pymorphy3",
                        type("_м", (), {"MorphAnalyzer": staticmethod(lambda: object())}))
    monkeypatch.setattr(сб, "_ключ_и_span",
                        lambda morph, acc, text: ("переписанный", None, False))

    assert сб.rekey_потоком() == len(ЗАПИСИ)

    видно = dict(кэш.поток())
    assert len(видно) == len(ЗАПИСИ), "перепись потеряла записи"
    assert all(v["key"] == "переписанный" for v in видно.values()), \
        "новые ключи не дошли до читателя"
    assert видно["дождь стучал по крыше"]["banal"] == 2.8, \
        "перепись ключей снесла поля качества — их она трогать не вправе"
    assert not кэш.СТАРЫЙ.exists(), \
        "перепись создала nl_rhyme.json — файл, который никто не читает"
