# nakedlunch — статусные пути без загрузки тяжёлого склада.
#
# Полная `книги.json` вместе с `active.json` и колонкой `src` должна позволять
# статусам рифмы и индекса закончить проверку без `_nl()`/store. Legacy-путь
# остаётся разрешённым только когда описи нет.

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

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


def test_nl_state_otdaet_reviziyu_indeksa_bez_zagruzki_sklada(
    готовый_сервер, monkeypatch,
):
    сервер = готовый_сервер
    индекс = _Индекс()
    monkeypatch.setattr(сервер.nlbridge, "store_if_ready", lambda: None)
    monkeypatch.setattr(сервер.nlbridge, "опись_книг", lambda: [
        {"id": "книга-А", "active": True, "fragment_count": 2},
        {"id": "книга-Б", "active": False, "fragment_count": 3},
    ])
    monkeypatch.setattr(сервер.nlindex, "load", lambda: индекс)
    monkeypatch.setattr(
        сервер.nlindex, "маска_книг",
        lambda idx, книги: np.array([True, True, False, False, False]),
    )
    monkeypatch.setattr(сервер, "_скрытое_в_пуле", lambda idx, маска: 0)

    ответ = сервер.app.test_client().get("/api/nl/state")

    assert ответ.status_code == 200
    данные = ответ.get_json()
    assert данные["revision"] == индекс.built_at
    assert данные["pool_total"] == 2


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


def _запретить_тяжёлый_склад(сервер, monkeypatch):
    """Вернуть следы любой попытки открыть большой `state.json`."""
    вызовы = []

    def запрещено(имя):
        def открыть(*_args, **_kwargs):
            вызовы.append(имя)
            raise AssertionError(f"пассивный fast-path вызвал {имя}")

        return открыть

    monkeypatch.setattr(сервер, "_nl", запрещено("_nl"))
    monkeypatch.setattr(
        сервер.nlbridge, "open_store", запрещено("open_store"))
    return вызовы


def test_отчёт_считает_только_активные_источники_из_готового_склада(
    готовый_сервер, monkeypatch,
):
    """Готовый склад можно спросить без `_nl()` и не считать выключенные книги."""
    сервер = готовый_сервер
    тяжёлые = _запретить_тяжёлый_склад(сервер, monkeypatch)
    быстрые = []
    склад = SimpleNamespace(list_corpora=lambda: [
        {"id": "книга-А", "active": True},
        {"id": "книга-Б", "active": False},
        {"id": "книга-В", "active": True},
    ])

    monkeypatch.setattr(сервер.nlindex, "load", lambda: None)
    monkeypatch.setattr(
        сервер.nlbridge, "store_if_ready",
        lambda: быстрые.append("store_if_ready") or склад,
    )
    monkeypatch.setattr(
        сервер.nlbridge, "опись_книг",
        lambda: (_ for _ in ()).throw(
            AssertionError("при готовом складе отчёт полез в опись")),
    )
    monkeypatch.setattr(
        сервер.nlbridge, "активные_книги",
        lambda: (_ for _ in ()).throw(
            AssertionError("при готовом складе отчёт полез в active.json")),
    )

    отчёт = сервер._добавка_к_отчёту()

    assert тяжёлые == []
    assert быстрые == ["store_if_ready"]
    assert отчёт["источников включено"] == "2"


def test_отчёт_считает_активные_источники_по_маленьким_файлам(
    готовый_сервер, monkeypatch,
):
    """Пока склад не готов, достаточно описи книг и отдельного active.json."""
    сервер = готовый_сервер
    тяжёлые = _запретить_тяжёлый_склад(сервер, monkeypatch)
    быстрые = []

    monkeypatch.setattr(сервер.nlindex, "load", lambda: None)
    monkeypatch.setattr(
        сервер.nlbridge, "store_if_ready",
        lambda: быстрые.append("store_if_ready") or None,
    )
    monkeypatch.setattr(
        сервер.nlbridge, "опись_книг",
        lambda: быстрые.append("опись_книг") or [
            {"id": "книга-А"}, {"id": "книга-Б"}, {"id": "книга-В"},
        ],
    )
    monkeypatch.setattr(
        сервер.nlbridge, "активные_книги",
        lambda: быстрые.append("активные_книги") or {"книга-Б"},
    )

    отчёт = сервер._добавка_к_отчёту()

    assert тяжёлые == []
    assert быстрые == [
        "store_if_ready", "опись_книг", "активные_книги"]
    assert отчёт["источников включено"] == "1"


def test_отчёт_честно_говорит_что_число_источников_неизвестно(
    готовый_сервер, monkeypatch,
):
    """Повреждённые маленькие данные не оправдывают загрузку всего склада."""
    сервер = готовый_сервер
    тяжёлые = _запретить_тяжёлый_склад(сервер, monkeypatch)

    monkeypatch.setattr(сервер.nlindex, "load", lambda: None)
    monkeypatch.setattr(сервер.nlbridge, "store_if_ready", lambda: None)
    monkeypatch.setattr(сервер.nlbridge, "опись_книг", lambda: None)
    monkeypatch.setattr(сервер.nlbridge, "активные_книги", lambda: None)

    отчёт = сервер._добавка_к_отчёту()

    assert тяжёлые == []
    assert отчёт["источников включено"] == "не удалось определить"


def test_пустая_выдача_объясняется_по_индексу_без_склада(
    готовый_сервер, monkeypatch,
):
    """Реальный generate дополняет пустую воронку числом из индексного пула."""
    сервер = готовый_сервер
    тяжёлые = _запретить_тяжёлый_склад(сервер, monkeypatch)
    индекс = SimpleNamespace(
        n=4,
        src=np.array([0, 0, 0, 1], dtype=np.int8),
        sources=["книга-А", "книга-Б"],
    )
    маска = np.array([True, True, True, False], dtype=bool)
    увидено = {}

    monkeypatch.setattr(сервер.nlindex, "load", lambda: индекс)
    monkeypatch.setattr(
        сервер.nlbridge, "активные_книги", lambda: {"книга-А"})
    monkeypatch.setattr(
        сервер.nlindex, "маска_книг", lambda idx, книги: маска.copy())
    monkeypatch.setattr(
        сервер, "_скрытое_в_пуле", lambda idx, pool_mask: 1)

    def пустой_прогон(*_args, **kwargs):
        увидено["книги"] = kwargs.get("книги")
        return {
            "shortlist": [],
            "funnel": {
                "shortlist": 0,
                "ступени": {"твои_книги": 3, "показано": 1},
            },
            "seed": 17,
        }

    monkeypatch.setattr(сервер.filters, "run", пустой_прогон)
    monkeypatch.setattr(сервер.stats_mod, "from_funnel", lambda _funnel: {})
    monkeypatch.setattr(сервер.stats_mod, "log", lambda *_args, **_kwargs: None)

    ответ = сервер.app.test_client().post(
        "/api/generate", json={"knobs": {"shortlist": 4}})

    assert тяжёлые == []
    assert ответ.status_code == 200, ответ.data[:400]
    результат = ответ.get_json()
    assert результат["funnel"]["pool_available"] == 2
    assert увидено == {"книги": {"книга-А"}}


def test_reload_ne_vklinivaetsya_mezhdu_proverkoy_pula_i_otborom(
    готовый_сервер, monkeypatch,
):
    """Решение о fallback и сам run видят один объект индекса.

    На старом пути совместимость проверялась до замка. Перезагрузка могла
    подменить индекс перед run: тексты не загрузили по старому совместимому,
    а новый уже не умел построить маску книг и получал пустой fallback.
    """
    сервер = готовый_сервер
    старый = SimpleNamespace(name="старый")
    новый = SimpleNamespace(name="новый")
    текущий = {"idx": старый}
    маску_проверили = threading.Event()
    перезагрузка_пошла = threading.Event()
    увидено = {}

    monkeypatch.setattr(сервер.nlbridge, "активные_книги", lambda: {"книга-А"})
    monkeypatch.setattr(сервер.nlindex, "load", lambda: текущий["idx"])

    def маска(idx, книги):
        assert книги == {"книга-А"}
        if idx is старый:
            маску_проверили.set()
            assert перезагрузка_пошла.wait(1)
            # Даём соседнему потоку шанс захватить замок. В исправленном коде
            # он не сможет этого сделать до окончания filters.run.
            time.sleep(0.04)
            return np.array([True])
        return None

    monkeypatch.setattr(сервер.nlindex, "маска_книг", маска)

    def прогон(*_args, **kwargs):
        # Настоящий filters.run берёт тот же RLock; повторяем именно границу
        # операции, не весь дорогой доменный расчёт.
        with сервер.nlindex.ЗАМОК:
            увидено["idx"] = сервер.nlindex.load()
            увидено["fragments"] = list(kwargs.get("nl_fragments") or [])
        return {
            "shortlist": [],
            "funnel": {"shortlist": 0,
                       "ступени": {"твои_книги": 1, "показано": 0}},
            "seed": 17,
        }

    monkeypatch.setattr(сервер.filters, "run", прогон)
    monkeypatch.setattr(сервер.stats_mod, "from_funnel", lambda _funnel: {})
    monkeypatch.setattr(сервер.stats_mod, "log", lambda *_args, **_kwargs: None)

    def перезагрузить():
        assert маску_проверили.wait(1)
        перезагрузка_пошла.set()
        with сервер.nlindex.ЗАМОК:
            текущий["idx"] = новый

    поток = threading.Thread(target=перезагрузить)
    поток.start()
    ответ = сервер.app.test_client().post(
        "/api/generate", json={"knobs": {"shortlist": 4}})
    поток.join(2)

    assert ответ.status_code == 200, ответ.data[:400]
    assert not поток.is_alive()
    assert увидено == {"idx": старый, "fragments": []}
    assert текущий["idx"] is новый


def test_nesovmestimyy_indeks_poluchaet_polnyy_tekstovyy_fallback(
    готовый_сервер, monkeypatch,
):
    сервер = готовый_сервер
    индекс = SimpleNamespace(name="чужой состав")
    склад = SimpleNamespace(get_active_pool=lambda: ["а", "б"])
    увидено = {}

    monkeypatch.setattr(сервер.nlbridge, "активные_книги", lambda: {"книга-А"})
    monkeypatch.setattr(сервер.nlindex, "load", lambda: индекс)
    monkeypatch.setattr(сервер.nlindex, "маска_книг", lambda idx, книги: None)
    monkeypatch.setattr(сервер, "_nl", lambda: склад)

    def прогон(*_args, **kwargs):
        увидено["fragments"] = list(kwargs.get("nl_fragments") or [])
        return {
            "shortlist": [],
            "funnel": {"shortlist": 0,
                       "ступени": {"твои_книги": 2, "показано": 0}},
            "seed": 19,
        }

    monkeypatch.setattr(сервер.filters, "run", прогон)
    monkeypatch.setattr(сервер.stats_mod, "from_funnel", lambda _funnel: {})
    monkeypatch.setattr(сервер.stats_mod, "log", lambda *_args, **_kwargs: None)

    ответ = сервер.app.test_client().post(
        "/api/generate", json={"knobs": {"shortlist": 4}})

    assert ответ.status_code == 200, ответ.data[:400]
    assert увидено["fragments"] == ["а", "б"]


def test_подпись_дубля_не_будит_склад_ради_поиска_другой_книги(
    готовый_сервер, monkeypatch,
):
    """Если индексная книга выключена, безопаснее оставить строку без подписи."""
    сервер = готовый_сервер
    тяжёлые = _запретить_тяжёлый_склад(сервер, monkeypatch)
    индекс = SimpleNamespace(
        src=np.array([0], dtype=np.int8),
        sources=["выключенная"],
    )
    строки = [{"text": "общая строка", "_ном": 0}]

    monkeypatch.setattr(сервер.nlindex, "load", lambda: индекс)
    monkeypatch.setattr(сервер.nlbridge, "store_if_ready", lambda: None)
    monkeypatch.setattr(сервер.nlbridge, "опись_книг", lambda: [
        {"id": "выключенная", "name": "Выключенная", "active": False},
        {"id": "включенная", "name": "Включенная", "active": True},
    ])

    сервер._подписать_источники(строки)

    assert тяжёлые == []
    assert "source_id" not in строки[0]
    assert "source" not in строки[0]
