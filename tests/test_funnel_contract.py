# nakedlunch — КОНТРАКТ ВОРОНКИ: у неё один вид, и читатели читают именно его.
#
# ЧТО СЛУЧИЛОСЬ. Раунд 51 вырезал `_rich_funnel` из горячего пути (он дважды
# копировал активный пул на 1.96 млн строк — 0.47–0.92 с, до 76% всего
# запроса). Вырезал правильно, но ДВА читателя остались читать его вложенный
# вид:
#   · api/server.py — `result["funnel"]["gen"]["used"]` в записи статистики.
#     KeyError ПОСЛЕ того, как выдача уже собрана, то есть 500-я на КАЖДЫЙ
#     вызов /api/generate. Одиночная генерация — самое частое действие в
#     приложении — была мертва целиком.
#   · methods.gen.js — `почемуПусто` читала funnel.nl.active / funnel.gen.
#     Все проверки получали undefined, и «честная причина пустой выдачи»
#     всегда сваливалась в последнюю общую фразу — ровно то безадресное
#     сообщение, ради устранения которого функция и писалась.
#
# ПОЧЕМУ ЭТОГО НЕ УВИДЕЛ НИ ОДИН ТЕСТ. Тесты зовут домен напрямую
# (filters.run), а роут не звал никто: импорт api/server.py поднимает корпус и
# индекс — 69 секунд и правка настоящей истории пользователя, в наборе тестов
# такому не место. Значит контракт надо проверять там, где он живёт: воронка
# рождается в filters.run, и оба читателя обязаны съесть ИМЕННО ЕЁ. Здесь она
# настоящая, а не выдуманная руками — выдуманная повторила бы ту же ошибку.
#
# Прогон: .venv/bin/python -m pytest tests/test_funnel_contract.py -q

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

import clean
import filters
import nlbridge
import stats
from corpus import Corpus, lemmatize

ГЕН = КОРЕНЬ / "interface" / "react-app" / "src" / "nl" / "methods.gen.js"

ФРАГМЕНТЫ = {"он ушёл в ночной покой": "ой", "над рекою тишина": "ина",
             "я запомнил это здание": "ание", "дым висел над головой": "ой"}


@pytest.fixture()
def словарь(monkeypatch):
    fake = {t: {"banal": 3.0, "taut": False, "lemmas": lemmatize(t),
                "tokens": list(nlbridge._tokens(t)), "key": key, "span": None}
            for t, key in ФРАГМЕНТЫ.items()}
    monkeypatch.setattr(filters, "_NL_RHYME", fake)
    monkeypatch.setattr(filters, "_index_for_current_cache", lambda *a, **k: None)
    return fake


def воронка(**kw) -> dict:
    """НАСТОЯЩАЯ воронка из домена — не словарь, набранный руками."""
    knobs = clean.knobs({"shortlist": 4, "real_text": 1.0, **kw.pop("knobs", {})})
    return filters.run([], knobs, Corpus(), nl_fragments=list(ФРАГМЕНТЫ),
                       rhyme="none", **kw)["funnel"]


# ---- читатель 1: запись статистики ----------------------------------------

def test_разбор_воронки_не_падает_на_обеих_ветках(словарь):
    """РЕГРЕССИЯ 500-й. Разбор обязан пережить и алгоритм, и классику: у них
    один набор ключей, и ровно на этом обещании стоит весь роут."""
    for режим, k in (("алгоритм", 0.0), ("классика", 1.0)):
        ф = воронка(knobs={"classic": k})
        числа = stats.from_funnel(ф)          # раньше здесь был KeyError
        assert set(числа) == {"shortlist", "gen_used", "nl_used", "nl_classic_used"}
        assert all(isinstance(v, int) and v >= 0 for v in числа.values()), режим


def test_числа_статистики_сходятся(словарь):
    """Не просто «не упало»: строк из корпуса и строк от генератора вместе —
    ровно вся выдача, и ни одна не посчитана дважды."""
    ф = воронка()
    ч = stats.from_funnel(ф)
    assert ч["shortlist"] == ф["shortlist"] == 4
    assert ч["nl_used"] + ч["gen_used"] == ч["shortlist"]
    # весь пул корпусный, генератору браться неоткуда
    assert ч["gen_used"] == 0 and ч["nl_used"] == 4


def test_разбор_читает_только_существующие_ключи(словарь):
    """Прямая проверка того, что и сломалось: имена, которые спрашивает
    разбор, обязаны быть в воронке. Словарь-ловушка роняет любое обращение к
    ключу, которого домен не отдаёт."""
    ф = воронка()

    class Строгая(dict):
        def get(self, k, default=None):
            assert k in ф, f"воронка не отдаёт ключа «{k}» — читатель отстал от домена"
            return super().get(k, default)

    stats.from_funnel(Строгая(ф))


# ---- читатель 2: «честная причина» на фронте -------------------------------

def почему(funnel: dict, params: dict | None = None) -> str:
    """Настоящая `почемуПусто` из methods.gen.js, скормленная настоящей
    воронкой. Через node: сборка тут не поможет — она зелёная и когда функция
    читает несуществующие поля."""
    if shutil.which("node") is None:
        pytest.skip("node не установлен — проверка фронта пропущена")
    src = f"""
    import {{ genMethods }} from '{ГЕН.as_uri()}';
    const self = {{ state: {{ params: {json.dumps(params or {}, ensure_ascii=False)} }} }};
    console.log(JSON.stringify(genMethods.почемуПусто.call(
      self, {{ funnel: {json.dumps(funnel, ensure_ascii=False)} }})));
    """
    p = subprocess.run(["node", "--input-type=module", "-e", src],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"node упал:\n{p.stderr}"
    return json.loads(p.stdout)


ОБЩАЯ = "ни одна строка не прошла отбор — ослабь условия"


def test_причина_пустого_пула(словарь):
    """Воронка настоящая, только выдача пуста и пул исчерпан — роут в этом
    случае доливает pool_available (единственное дорогое число, и только
    когда оно нужно объяснить пустоту)."""
    ф = dict(воронка(), shortlist=0, pool_available=0)
    assert "непоказанных" in почему(ф)


def test_причина_называет_клаузулу(словарь):
    ф = dict(воронка(), shortlist=0, pool_available=100,
             nl_survived=0, nl_classic_survived=0)
    assert "клаузул" in почему(ф, {"Клаузула": 2})


def test_причина_называет_мат(словарь):
    ф = dict(воронка(), shortlist=0, pool_available=100,
             nl_survived=0, nl_classic_survived=0)
    assert "мат" in почему(ф, {"Мат": 0}).lower()


def test_причина_называет_генератор(словарь):
    """Ветка генератора: сырьё было, до конца каскада не дожило ничего."""
    ф = dict(воронка(), shortlist=0, nl_fetched=0, generated=2000, banality=0)
    ответ = почему(ф)
    assert "генератор" in ответ and ответ != ОБЩАЯ


def test_причина_называет_отсутствие_источника(словарь):
    ф = dict(воронка(), shortlist=0, nl_fetched=0, generated=0)
    assert "нет источника" in почему(ф)


def test_причина_не_сваливается_в_общую_фразу(словарь):
    """РЕГРЕССИЯ. Пока функция читала вложенный вид, ВСЕ ветки давали одну
    общую фразу. Одного «называет клаузулу» мало: надо, чтобы разные пустоты
    объяснялись РАЗНО."""
    случаи = [
        dict(воронка(), shortlist=0, pool_available=0),
        dict(воронка(), shortlist=0, pool_available=100, nl_survived=0, nl_classic_survived=0),
        dict(воронка(), shortlist=0, nl_fetched=0, generated=2000, banality=0),
        dict(воронка(), shortlist=0, nl_fetched=0, generated=0),
    ]
    ответы = [почему(ф) for ф in случаи]
    assert len(set(ответы)) == len(ответы), f"причины не различаются: {ответы}"
    assert ОБЩАЯ not in ответы
