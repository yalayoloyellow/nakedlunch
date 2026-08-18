# nakedlunch — КЭШ РИФМ ПИШЕТСЯ ТУДА, ГДЕ ЕГО ЧИТАЮТ (Раунд 62).
#
# ЧТО СЛУЧИЛОСЬ. Раунд 57 перевёл кэш ударений на построчный формат
# (`nl_rhyme.jsonl`), и читатели ушли на него: `кэш.поток` предпочитает
# построчный, если он есть. А сборка — та самая, что запускается САМА при
# добавлении источника (`api/server.py`) — осталась на старом `nl_rhyme.json`:
# читала его целиком в память и туда же писала.
#
# То есть **залитая книга ложилась в файл, который никто не читает.** В выдачу
# она не попадала бы вовсе.
#
# Почему не поймали раньше: с 6 августа книг не заливали, оба файла на диске
# совпадали (2 434 632 записи), и расхождение было ЛАТЕНТНЫМ — механизм
# сломан, симптом не наступил. Ни один тест не проверял, КУДА пишет сборка.
#
# Здесь проверяется исход: после сборки новая запись обязана быть видна
# читателю. Акцентуатор подменён — он весит 1.3 ГБ и к маршрутизации файлов
# отношения не имеет.
#
# Прогон: .venv/bin/python -m pytest tests/test_кэш_рифм.py -q

import json
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))
sys.path.insert(0, str(КОРЕНЬ / "tools"))

import кэш


@pytest.fixture()
def временный_кэш(tmp_path, monkeypatch):
    """Кэш в песочнице. Пути — модульные глобальные, читаются при вызове."""
    monkeypatch.setattr(кэш, "СТАРЫЙ", tmp_path / "nl_rhyme.json")
    monkeypatch.setattr(кэш, "СТРОЧНЫЙ", tmp_path / "nl_rhyme.jsonl")
    return tmp_path


class ЗаглушкаСклада:
    def __init__(self, тексты):
        self._t = list(тексты)

    def get_all_fragments(self):
        return [{"id": str(i), "text": t, "corpus_id": "к"} for i, t in enumerate(self._t)]


def _подменить_сборщик(monkeypatch, тексты):
    import build_nl_rhyme as сб
    import nlbridge
    monkeypatch.setattr(сб, "акцентуатор", lambda: object())
    monkeypatch.setattr(сб, "_write_status", lambda *a, **k: None)
    monkeypatch.setattr(nlbridge, "open_store", lambda: ЗаглушкаСклада(тексты))
    # расчёт полей подменяем целиком: он требует модели ударений, а проверяем мы
    # маршрутизацию файлов, а не качество ключа
    monkeypatch.setattr(сб, "_поля_фрагмента",
                        lambda morph, acc, text: ({"key": "ы", "span": None,
                                                   "banal": 3.0, "taut": False,
                                                   "lemmas": [], "tokens": []}, False))
    return сб


def test_novaya_kniga_dohodit_do_chitatelya(временный_кэш, monkeypatch):
    """ГЛАВНОЕ: после сборки новая запись видна ЧИТАТЕЛЮ, а не лежит в файле,
    который читатель не открывает."""
    with кэш.Писатель() as п:
        п.запиши("строка, которая уже была", {"key": "а", "span": None})
    assert кэш.есть_строчный()

    сб = _подменить_сборщик(monkeypatch, ["строка, которая уже была", "новая строка книги"])
    сб.build_потоком("incremental")

    видно = dict(кэш.поток())
    assert "новая строка книги" in видно, "новая запись не дошла до читателя"
    assert "строка, которая уже была" in видно, "прежние записи потерялись"
    assert len(видно) == 2


def test_sborka_ne_pishet_v_fayl_kotoryy_nikto_ne_chitaet(временный_кэш, monkeypatch):
    """Прямой сторож на саму поломку: старый файл не должен появляться."""
    with кэш.Писатель() as п:
        п.запиши("была", {"key": "а", "span": None})
    сб = _подменить_сборщик(monkeypatch, ["была", "новая"])
    сб.build_потоком("incremental")
    assert not кэш.СТАРЫЙ.exists(), \
        "сборка создала nl_rhyme.json — тот самый файл, который никто не читает"


def test_povtornaya_sborka_nichego_ne_dubliruet(временный_кэш, monkeypatch):
    """Второй заход (правило 12: ломается именно на нём) — записи не двоятся."""
    сб = _подменить_сборщик(monkeypatch, ["одна", "две"])
    with кэш.Писатель() as п:
        п.запиши("одна", {"key": "а", "span": None})
    сб.build_потоком("incremental")
    сб.build_потоком("incremental")
    строки = кэш.СТРОЧНЫЙ.read_text("utf-8").strip().splitlines()
    тексты = [json.loads(с)["t"] for с in строки]
    assert sorted(тексты) == ["две", "одна"], f"записи задвоились: {тексты}"


def test_obryv_ne_ostavlyaet_obrubka(временный_кэш, monkeypatch):
    """Целиком или никак: падение посреди прохода оставляет ПРЕЖНИЙ файл, а не
    обрубок, который следующее чтение примет за пустой кэш."""
    with кэш.Писатель() as п:
        п.запиши("была", {"key": "а", "span": None})
    было = кэш.СТРОЧНЫЙ.read_text("utf-8")

    сб = _подменить_сборщик(monkeypatch, ["была", "новая"])

    def падает(morph, acc, text):
        raise RuntimeError("модель умерла посреди прохода")

    monkeypatch.setattr(сб, "_поля_фрагмента", падает)
    with pytest.raises(RuntimeError):
        сб.build_потоком("incremental")
    assert кэш.СТРОЧНЫЙ.read_text("utf-8") == было, "кэш повреждён обрывом"


def test_sborka_vyhodit_na_potochnyy_put(временный_кэш, monkeypatch):
    """СТОРОЖ НА САМУ ПОЛОМКУ, а не на новую функцию.

    Тесты выше зовут `build_потоком` напрямую — они проверяют, что она работает.
    Сломано же было ДРУГОЕ: сборка на неё не выходила. Здесь дёргается `main()`
    ровно так, как её зовёт заливка книги, и проверяется, что при живом
    построчном кэше управление уходит в потоковый путь, а старый файл не
    трогается вовсе."""
    import build_nl_rhyme as сб
    with кэш.Писатель() as п:
        п.запиши("была", {"key": "а", "span": None})

    звали = []
    monkeypatch.setattr(сб, "build_потоком", lambda mode="incremental": звали.append(mode))
    monkeypatch.setattr(сб, "_write_status", lambda *a, **k: None)

    def нельзя(*a, **k):
        raise AssertionError("сборка полезла в старый путь, читаемый никем")

    monkeypatch.setattr(сб, "build", нельзя)
    monkeypatch.setattr(сб, "_write_out", нельзя)
    monkeypatch.setattr(sys, "argv", ["build_nl_rhyme.py"])
    assert сб.main() == 0
    assert звали == ["incremental"], f"потоковый путь не позвали: {звали}"


def test_full_ne_chitaet_prezhnee(временный_кэш, monkeypatch):
    """`--full` по договору пересчитывает всё: прежние записи не переливаются,
    иначе снятая книга осталась бы в кэше навсегда."""
    with кэш.Писатель() as п:
        п.запиши("снятая книга", {"key": "а", "span": None})
    сб = _подменить_сборщик(monkeypatch, ["только эта"])
    сб.build_потоком("full")
    видно = dict(кэш.поток())
    assert list(видно) == ["только эта"], f"после --full осталось: {list(видно)}"
