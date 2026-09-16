# nakedlunch — статусные пути без загрузки тяжёлого склада.
#
# Полная `книги.json` вместе с `active.json` и колонкой `src` должна позволять
# статусам рифмы и индекса закончить проверку без `_nl()`/store. Legacy-путь
# остаётся разрешённым только когда описи нет.

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest


КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "api"))


@pytest.fixture(scope="module")
def сервер():
    import server

    return server


@pytest.fixture
def готовый_сервер(сервер, monkeypatch):
    """Общий безопасный стенд: только маленькие синтетические данные."""
    monkeypatch.setattr(сервер, "_ПРОГРЕВ", {"готов": True})
    monkeypatch.setattr(сервер, "_подхватить_свежий_индекс", lambda: None)
    monkeypatch.setattr(сервер, "_индекс_сборка", lambda: {"state": "done"})
    monkeypatch.setattr(сервер, "_NL_INDEX_PROC", None)

    def запрещено(*_args, **_kwargs):
        raise AssertionError("статусный fast-path загрузил тяжёлый склад")

    for имя in ("_nl", "_nl_texts", "_nl_active_texts"):
        monkeypatch.setattr(сервер, имя, запрещено)
    for имя in ("open_store", "store_if_ready"):
        monkeypatch.setattr(сервер.nlbridge, имя, запрещено)

    return сервер


def _каталог():
    return [
        {"id": "книга-А", "fragment_count": 2},
        {"id": "книга-Б", "fragment_count": 3},
    ]


class _Индекс:
    built_at = "2026-09-14T12:00:00"
    src = np.array([0, 0, 1, 1, 1], dtype=np.int8)
    sources = ["книга-А", "книга-Б"]

    def text(self, _номер):
        raise AssertionError("статус не должен читать строки индекса")


def test_полная_опись_src_и_lag_sources_дают_done(
    готовый_сервер, monkeypatch, tmp_path,
):
    """Полная опись даёт оба done без `_nl()` и построения text_ids."""
    сервер = готовый_сервер
    индекс = _Индекс()
    каталог = _каталог()
    активные = {"книга-А", "книга-Б"}
    увидено = {}

    monkeypatch.setattr(сервер.nlbridge, "опись_книг", lambda: каталог)
    monkeypatch.setattr(сервер.nlbridge, "активные_книги", lambda: активные)
    monkeypatch.setattr(сервер.nlindex, "load", lambda: индекс)

    def lag_sources(idx, active_sources, expected_counts):
        увидено["idx"] = idx
        увидено["active"] = active_sources
        увидено["expected"] = expected_counts
        return 0

    monkeypatch.setattr(сервер.nlindex, "lag_sources", lag_sources)
    status_path = tmp_path / "nl_rhyme.status.json"
    status_path.write_text(
        json.dumps({"state": "done", "cached": 5}), encoding="utf-8")
    monkeypatch.setattr(сервер, "_NL_RHYME_STATUS_PATH", status_path)

    rhyme = сервер._nl_rhyme_status()
    index = сервер._nl_index_status()

    assert rhyme["state"] == "done"
    assert rhyme["total"] == 5
    assert rhyme["done"] == 5
    assert rhyme["pct"] == 100
    assert index["state"] == "done"
    assert index["total"] == 5
    assert index["done"] == 5
    assert index["pct"] == 100
    assert увидено == {
        "idx": индекс,
        "active": активные,
        "expected": {"книга-А": 2, "книга-Б": 3},
    }


def test_отсутствие_описи_включает_legacy_fallback(
    готовый_сервер, monkeypatch, tmp_path,
):
    """Без `книги.json` оба статуса честно используют старый путь."""
    сервер = готовый_сервер
    индекс = _Индекс()
    вызовы = []

    monkeypatch.setattr(сервер.nlbridge, "опись_книг", lambda: None)
    monkeypatch.setattr(сервер.nlbridge, "активные_книги", lambda: None)
    monkeypatch.setattr(сервер.nlindex, "load", lambda: индекс)
    monkeypatch.setattr(
        сервер, "_nl_texts", lambda: вызовы.append("nl_texts") or {"а", "б", "в"})
    monkeypatch.setattr(
        сервер, "_nl_active_texts",
        lambda: вызовы.append("nl_active_texts") or {"а", "б"},
    )
    monkeypatch.setattr(
        сервер.nlindex, "lag", lambda тексты, total: вызовы.append(("lag", total)) or 0)
    def forbidden_lag_sources(*_args, **_kwargs):
        raise AssertionError("legacy fallback вызвал lag_sources")
    monkeypatch.setattr(сервер.nlindex, "lag_sources", forbidden_lag_sources)
    monkeypatch.setattr(сервер, "_NL_RHYME_STATUS_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(
        сервер, "_статус_по_кэшу",
        lambda base, total, прерван: {
            **base, "state": "done", "done": total, "pct": 100,
            "detail": "legacy cache",
        },
    )

    rhyme = сервер._nl_rhyme_status()
    index = сервер._nl_index_status()

    assert rhyme["state"] == "done"
    assert rhyme["total"] == 3
    assert index["state"] == "done"
    assert index["total"] == 2
    assert index["done"] == 2
    assert вызовы == ["nl_texts", "nl_active_texts", ("lag", 2)]
