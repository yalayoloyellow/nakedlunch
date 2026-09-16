# nakedlunch — актуальность состава индексного пула.
#
# Индекс уже хранит номер книги каждой строки в колонке `src`. Проверяем, что
# маска активных книг берётся оттуда напрямую, а старый дорогой путь через
# text_ids остаётся только fallback-ом у вызывающего кода.

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

import nlindex  # noqa: E402


class _Индекс:
    """Минимальный индекс: источники намеренно равны метаданным индекса."""

    n = 6
    # строки: книга-А, книга-А, книга-Б, книга-Б, книга-В, книга-В
    src = np.array([0, 0, 1, 1, 2, 2], dtype=np.int8)
    sources = ["книга-А", "книга-Б", "книга-В"]

    def text(self, _номер):
        raise AssertionError("актуальность состава не должна читать тексты")


class _ИндексБезSources:
    src = np.array([0, 0], dtype=np.int8)

    def text(self, _номер):
        raise AssertionError("lag_sources не должен читать тексты")


@pytest.fixture(autouse=True)
def чистый_кэш():
    nlindex.forget_pool()
    yield
    nlindex.forget_pool()


def test_маска_по_src_не_строит_text_ids(monkeypatch):
    """Новый путь использует `src` и не запускает дорогую карту текстов."""
    индекс = _Индекс()

    def запрещённый_старый_путь(*_args, **_kwargs):
        raise AssertionError("вызван старый путь через mask_of")

    monkeypatch.setattr(nlindex, "mask_of", запрещённый_старый_путь)

    маска = nlindex.маска_книг(индекс, {"книга-А", "книга-В"})

    assert маска is not None
    assert маска.dtype == np.bool_
    assert маска.tolist() == [True, True, False, False, True, True]


def test_смена_active_состава_не_оставляет_старую_маску():
    """Два состава одинакового размера должны дать разные маски."""
    индекс = _Индекс()

    только_а = nlindex.маска_книг(индекс, {"книга-А"})
    только_б = nlindex.маска_книг(индекс, {"книга-Б"})

    assert только_а.tolist() == [True, True, False, False, False, False]
    assert только_б.tolist() == [False, False, True, True, False, False]


@pytest.mark.parametrize(
    "индекс, активные",
    [
        (type("БезSrc", (), {"sources": ["книга-А"]})(), {"книга-А"}),
        (type("БезSources", (), {"src": np.array([0, 0])})(), {"книга-А"}),
        (type("С пустымиSources", (), {"src": np.array([0, 0]), "sources": []})(), {"книга-А"}),
    ],
    ids=["без-src", "без-метаданных-sources", "пустые-метаданные-sources"],
)
def test_неполный_индексный_состав_даёт_none(индекс, активные):
    """Без `src` или метаданных нельзя честно сопоставить active-книги."""
    assert nlindex.маска_книг(индекс, активные) is None


def test_без_активных_книг_даёт_none():
    """None означает fallback, а не пустой пул и не молчаливый ноль."""
    assert nlindex.маска_книг(_Индекс(), None) is None


def test_чужой_active_состав_даёт_none():
    """Индекс из другого состава нельзя принять за актуальный."""
    assert nlindex.маска_книг(_Индекс(), {"чужая-книга"}) is None


def test_lag_sources_точное_совпадение_даёт_ноль():
    """При полном совпадении `src` и ожидаемых active-counts лага нет."""
    ожидается = {"книга-А": 2, "книга-Б": 2, "книга-В": 2}

    assert nlindex.lag_sources(
        _Индекс(), {"книга-А", "книга-Б", "книга-В"}, ожидается) == 0


@pytest.mark.parametrize(
    "активные, ожидается, пропущено",
    [
        ({"книга-А"}, {"книга-А": 4}, 2),
        ({"книга-Г"}, {"книга-Г": 3}, 3),
    ],
    ids=["источник-короче", "источник-отсутствует"],
)
def test_lag_sources_считает_пропущенные_строки(
    активные, ожидается, пропущено,
):
    """Отсутствующий и укороченный active-источник дают положительный лаг."""
    assert nlindex.lag_sources(_Индекс(), активные, ожидается) == пропущено


@pytest.mark.parametrize(
    "индекс, активные, ожидается",
    [
        (None, {"книга-А"}, {"книга-А": 2}),
        (type("БезSrc", (), {"sources": ["книга-А"]})(), {"книга-А"}, {"книга-А": 2}),
        (_ИндексБезSources(), {"книга-А"}, {"книга-А": 2}),
        (_Индекс(), None, {"книга-А": 2}),
        (_Индекс(), {"книга-А"}, None),
    ],
    ids=[
        "без-индекса", "без-src", "без-метаданных-sources",
        "без-active-описи", "без-expected-counts",
    ],
)
def test_lag_sources_без_достаточных_метаданных_даёт_none(
    индекс, активные, ожидается,
):
    """Без любого обязательного источника истины нельзя гадать о лаге."""
    assert nlindex.lag_sources(индекс, активные, ожидается) is None
