# nakedlunch — контракт наблюдаемого состояния генерации.
#
# Этот файл проверяет только тонкий HTTP-слой: тяжёлое тело генерации заменено
# monkeypatch-ем, поэтому тесты быстрые и не читают/не меняют корпус, историю
# или другие пользовательские данные.

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest


КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "api"))


@pytest.fixture(scope="module")
def сервер():
    """Импортировать тяжёлый адаптер один раз на весь новый набор тестов."""
    import server

    return server


@pytest.fixture(autouse=True)
def чистое_состояние(сервер):
    """Не дать одному сценарию оставить снимок или замок следующему.

    Если предыдущий тест оставил реальный прогон под замком, это не маскируем
    принудительным сбросом: такой leak должен быть виден как ошибка теста.
    """
    assert сервер._ГЕНЕРАЦИЯ_ЗАМОК.acquire(timeout=2), (
        "предыдущий тест оставил генерацию под замком")
    сервер._ГЕНЕРАЦИЯ_ЗАМОК.release()

    исходное = dict(сервер._ГЕНЕРАЦИЯ_СОСТОЯНИЕ)
    _сбросить_снимок(сервер)
    yield
    _установить_снимок(сервер, **исходное)


def _установить_снимок(сервер, **patch):
    """Записать состояние через тот же lock, что использует production-код."""
    начальное = {
        "state": "idle",
        "phase": "",
        "started_at": None,
        "updated_at": None,
        "elapsed_ms": 0,
        "error": "",
        "result": None,
    }
    with сервер._ГЕНЕРАЦИЯ_СОСТОЯНИЕ_ЗАМОК:
        сервер._ГЕНЕРАЦИЯ_СОСТОЯНИЕ.clear()
        сервер._ГЕНЕРАЦИЯ_СОСТОЯНИЕ.update(начальное)
        сервер._ГЕНЕРАЦИЯ_СОСТОЯНИЕ.update(patch)


def _сбросить_снимок(сервер):
    _установить_снимок(сервер)


def _клиент(сервер):
    return сервер.app.test_client()


def test_снимок_idle_не_выдаётся(сервер):
    """Пока расчёта нет, status не создаёт ложную фоновую работу."""
    assert сервер._генерация_снимок() is None


def test_снимок_running_содержит_живые_поля_и_является_копией(сервер):
    """Running-состояние доступно для опроса и не отдаёт наружу сам словарь."""
    сервер._генерация_обновить(
        state="running",
        phase="проверяю полную базу и совместимость",
        started_at=сервер.time.time() - 0.25,
        error="",
        result=None,
    )

    снимок = сервер._генерация_снимок()

    assert снимок is not None
    assert снимок["state"] == "running"
    assert снимок["phase"] == "проверяю полную базу и совместимость"
    assert снимок["elapsed_ms"] >= 0
    assert снимок["updated_at"] is not None
    снимок["phase"] = "подмена"
    assert сервер._генерация_снимок()["phase"] != "подмена"


def test_wrapper_api_generate_running_to_done(сервер, monkeypatch):
    """Успешный wrapper сам ставит running, а затем фиксирует результат."""
    вошли = threading.Event()

    def body():
        состояние = сервер._генерация_снимок()
        assert состояние["state"] == "running"
        assert состояние["phase"] == "подготовка"
        вошли.set()
        return {"shortlist": ["первая строка", "вторая строка"]}

    monkeypatch.setattr(сервер, "_api_generate_body", body)
    ответ = _клиент(сервер).post("/api/generate", json={})

    assert вошли.is_set()
    assert ответ.status_code == 200
    assert ответ.get_json() == {
        "shortlist": ["первая строка", "вторая строка"]}
    состояние = сервер._генерация_снимок()
    assert состояние["state"] == "done"
    assert состояние["phase"] == "готово"
    assert состояние["error"] == ""
    assert состояние["result"] == {"stanzas": 1, "lines": 2}


def test_wrapper_api_generate_running_to_error(сервер, monkeypatch):
    """Исключение body не оставляет снимок в running и сохраняет причину."""
    def body():
        raise RuntimeError("искусственная ошибка body")

    monkeypatch.setattr(сервер, "_api_generate_body", body)
    ответ = _клиент(сервер).post("/api/generate", json={})

    assert ответ.status_code == 500
    состояние = сервер._генерация_снимок()
    assert состояние["state"] == "error"
    assert состояние["phase"] == "ошибка"
    assert состояние["error"] == "RuntimeError: искусственная ошибка body"


def test_второй_одновременный_generate_получает_409(сервер, monkeypatch):
    """Второй запрос отвергается, пока первый действительно находится в body."""
    вошли = threading.Event()
    отпустить = threading.Event()
    первый_ответ = []
    вызовы_body = []

    def body():
        вызовы_body.append(1)
        вошли.set()
        assert отпустить.wait(5), "первый запрос не был отпущен вовремя"
        return {"shortlist": ["строка"]}

    monkeypatch.setattr(сервер, "_api_generate_body", body)

    def первый_запрос():
        первый_ответ.append(_клиент(сервер).post("/api/generate", json={}))

    поток = threading.Thread(target=первый_запрос)
    поток.start()
    try:
        assert вошли.wait(2), "первый запрос не дошёл до заменённого body"
        assert сервер._генерация_снимок()["state"] == "running"

        второй = _клиент(сервер).post("/api/generate", json={})
    finally:
        отпустить.set()
        поток.join(5)

    assert not поток.is_alive(), "поток первого запроса не завершился"
    assert второй.status_code == 409
    assert второй.get_json() == {
        "error": "расчёт уже идёт",
        "detail": "дождись текущей строфы",
    }
    assert вызовы_body == [1], "второй запрос всё-таки вошёл в body"
    assert первый_ответ and первый_ответ[0].status_code == 200
    assert сервер._генерация_снимок()["state"] == "done"


def test_api_status_отдаёт_generation(сервер, monkeypatch):
    """Публичный status содержит тот же снимок, который видит внутренний API."""
    сервер._генерация_обновить(
        state="running",
        phase="оформляю результат",
        started_at=сервер.time.time(),
    )

    # Опрос не должен в этом контрактном тесте заходить в фоновые артефакты.
    for имя in (
        "_прогрев_статус", "_nl_store_status", "_import_status",
        "_чистка_статус", "_nl_rhyme_status", "_nl_index_status",
        "_устарелость_статус",
    ):
        monkeypatch.setattr(сервер, имя, lambda: None)
    monkeypatch.setattr(сервер.журнал, "записи", lambda *args: [])
    monkeypatch.setattr(сервер.журнал, "не_закрыто", lambda: [])

    ответ = _клиент(сервер).get("/api/status")

    assert ответ.status_code == 200
    тело = ответ.get_json()
    assert "generation" in тело
    assert тело["generation"]["state"] == "running"
    assert тело["generation"]["phase"] == "оформляю результат"
