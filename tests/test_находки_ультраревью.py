# nakedlunch — СТОРОЖА НА НАХОДКИ УЛЬТРАРЕВЬЮ БАНДЛА Б (2026-08-27).
#
# Семь находок облачного ревью подтверждены чтением кода и закрыты; здесь
# сторожа на те из них, что ловятся тестом. Прогон:
#     .venv/bin/python -m pytest tests/test_находки_ультраревью.py -q

import ast
import json
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

from nlsrc.store import NakedLunchStore  # noqa: E402


# ---- bug_001: обработчик ошибки, который сам падает -------------------------

def test_журнал_ошибка_везде_зовётся_с_двумя_аргументами():
    """bug_001: три вызова `журнал.ошибка(f"...")` с ОДНИМ аргументом при двух
    обязательных. Сам обработчик исключения поднимал TypeError, строка
    `_ЧИСТКА.update({"state": "error"})` не выполнялась — чистка навсегда
    оставалась «running», лечилось только перезапуском окна.

    Сторож по AST, а не по одному месту: следующий такой вызов появится в
    другом файле и в другом обработчике."""
    плохие = []
    for файл in [КОРЕНЬ / "api" / "server.py", *(КОРЕНЬ / "core").glob("*.py")]:
        дерево = ast.parse(файл.read_text("utf-8"))
        for узел in ast.walk(дерево):
            if (isinstance(узел, ast.Call) and isinstance(узел.func, ast.Attribute)
                    and узел.func.attr == "ошибка"
                    and isinstance(узел.func.value, ast.Name)
                    and узел.func.value.id == "журнал"
                    and len(узел.args) + len(узел.keywords) < 2):
                плохие.append(f"{файл.name}:{узел.lineno}")
    assert not плохие, f"журнал.ошибка с одним аргументом: {плохие}"


# ---- bug_010: битый склад не сбрасывается молча -----------------------------

def test_битый_склад_отказывает_а_не_сбрасывается(tmp_path):
    """bug_010: битый state.json молча превращался в пустой State(), и первый
    же add_corpus АТОМАРНО затирал 380 МБ книг пустотой. Прецедент отказа —
    core/corpus.py: «the one file we must not silently reset; refuse»."""
    (tmp_path / "state.json").write_text('{"corpora": [{"id": "а", НЕ JSON',
                                         encoding="utf-8")
    with pytest.raises(RuntimeError, match="повреждён"):
        NakedLunchStore(tmp_path)


def test_отсутствующий_склад_это_честный_пустой_старт(tmp_path):
    """Отказ — только на ПОВРЕЖДЁННОМ файле. Свежая установка без state.json
    обязана стартовать пустой, как и раньше."""
    с = NakedLunchStore(tmp_path)
    assert с.state.corpora == [] and с.state.fragments == []


def test_битый_склад_не_затирается_на_диске(tmp_path):
    """Суть находки — не исключение, а СОХРАННОСТЬ файла: после отказа битый
    state.json обязан лежать нетронутым, байт в байт."""
    битый = '{"corpora": [{"id": "а", оборвано на полусло'
    (tmp_path / "state.json").write_text(битый, encoding="utf-8")
    try:
        NakedLunchStore(tmp_path)
    except RuntimeError:
        pass
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == битый


# ---- bug_008: dynamic.json атомарен -----------------------------------------

def test_dynamic_пишется_тем_же_атомом_что_и_склад(tmp_path):
    """bug_008: dynamic.json писался write_text — файл существовал усечённым
    посреди записи, а _load молча глотал обрубок и обнулял used_lines (все
    показанные строки CLI возвращались в выдачу — слом инварианта №1).

    Сторож по исходнику: запись обязана идти через `_записать_целиком`, второй
    путь записи dynamic.json завёлся бы тихо."""
    т = (КОРЕНЬ / "core" / "nlsrc" / "store.py").read_text("utf-8")
    assert "self.dynamic_path.write_text" not in т, \
        "dynamic.json снова пишется неатомарно"
    assert "self.active_path.write_text" not in т, \
        "active.json снова пишется неатомарно"
    # и живой проверкой: запись реально работает
    с = NakedLunchStore(tmp_path)
    с.mark_lines_used(["строка раз", "строка два"])
    с._save()
    д = json.loads((tmp_path / "dynamic.json").read_text("utf-8"))
    assert set(д["used_lines"]) == {"строка раз", "строка два"}


# ---- bug_005: кэш подчищается по всему складу, а не по активному пулу -------

def test_подчистка_кэша_меряет_складом_а_не_активным_пулом():
    """bug_005: `_выбросить_из_кэша(_nl().get_active_pool())` выбрасывал из
    кэша ударений тексты ВЫКЛЮЧЕННЫХ книг, хотя чистка их фрагменты не
    трогает: включаешь книгу обратно — её строки часами пересчитываются.
    Чистка работает по state.fragments целиком — тем же множеством обязана
    мерить и подчистка."""
    т = (КОРЕНЬ / "api" / "server.py").read_text("utf-8")
    assert "_выбросить_из_кэша(_nl().get_active_pool())" not in т, \
        "подчистка кэша снова меряет активным пулом"
    assert "_выбросить_из_кэша(\n        f.text for f in _nl().state.fragments)" in т
