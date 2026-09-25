"""Контракт приватного Telegram-пульта без сети и боевых данных."""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest


КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

import телеграм


ТОКЕН = "123456789:" + "A" * 35


class ФальшивыйКлиент:
    def __init__(self, события: list, *, отказ_отправки: bool = False):
        self.события = события
        self.отказ_отправки = отказ_отправки

    def ответить_на_кнопку(self, callback_id, text="", alert=False):
        self.события.append(("answer", callback_id, text, alert))

    def послать(self, chat_id, text, keyboard=None):
        self.события.append(("send", chat_id, text, keyboard))
        if self.отказ_отправки:
            raise телеграм.НетСвязи("нет связи")
        return {"message_id": len(self.события)}


def _start(secret: str, user_id: int = 41) -> dict:
    return {"message": {
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id},
        "text": "/start " + secret,
    }}


def _button(user_id: int = 41) -> dict:
    return {"callback_query": {
        "id": "callback-1", "data": телеграм.CALLBACK_NEXT,
        "from": {"id": user_id},
        "message": {"chat": {"id": user_id, "type": "private"}},
    }}


def test_токен_лежит_в_закрытом_файле_а_статус_его_не_выдаёт(tmp_path):
    path = tmp_path / "telegram.json"
    store = телеграм.Хранилище(path)
    secret = store.подключить(ТОКЕН, "nakedlunch_test_bot")

    assert path.exists()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text("utf-8"))["token"] == ТОКЕН
    status = store.статус()
    assert status == {
        "configured": True,
        "username": "nakedlunch_test_bot",
        "paired": False,
        "awaiting_pair": True,
    }
    assert ТОКЕН not in json.dumps(status)
    assert secret not in json.dumps(status)


def test_привязка_одноразовая_и_только_для_одного_приватного_чата(tmp_path):
    store = телеграм.Хранилище(tmp_path / "telegram.json")
    secret = store.подключить(ТОКЕН, "nakedlunch_test_bot")

    assert not store.привязать("чужой", 41, 41)
    assert store.привязать(secret, 41, 41)
    assert not store.привязать(secret, 42, 42)
    assert store.разрешён(41, 41)
    assert not store.разрешён(42, 42)
    assert store.статус()["paired"]
    assert not store.статус()["awaiting_pair"]


def test_кнопка_отправляет_только_показанный_лентой_текст(tmp_path):
    store = телеграм.Хранилище(tmp_path / "telegram.json")
    secret = store.подключить(ТОКЕН, "nakedlunch_test_bot")
    события: list = []

    def выдать():
        события.append(("remote",))
        return "shown", [
            {"text": "первая строка"},
            {"text": "вторая строка"},
        ]

    pult = телеграм.Пульт(store, выдать)
    client = ФальшивыйКлиент(события)
    pult.обработать(_start(secret), client)
    assert store.разрешён(41, 41)

    события.clear()
    pult.обработать(_button(), client)

    assert [event[0] for event in события] == ["answer", "remote", "send"]
    assert события[2][2] == "первая строка\nвторая строка"
    assert события[2][3]["inline_keyboard"][0][0]["text"] == "выдать текст"


def test_неотправленный_текст_и_чужой_чат_не_запускают_ленту(tmp_path):
    store = телеграм.Хранилище(tmp_path / "telegram.json")
    secret = store.подключить(ТОКЕН, "nakedlunch_test_bot")
    события: list = []

    def выдать():
        события.append(("remote",))
        return "shown", [{"text": "строка"}]

    pult = телеграм.Пульт(store, выдать)
    pult.обработать(_start(secret), ФальшивыйКлиент(события))
    события.clear()

    pult.обработать(_button(99), ФальшивыйКлиент(события))
    assert события == [("answer", "callback-1", "этот бот уже подключён", True)]

    события.clear()
    pult.обработать(_button(), ФальшивыйКлиент(события, отказ_отправки=True))
    assert [event[0] for event in события] == ["answer", "remote", "send"]


def test_бот_честно_отвечает_занято_без_второго_прогона(tmp_path):
    store = телеграм.Хранилище(tmp_path / "telegram.json")
    secret = store.подключить(ТОКЕН, "nakedlunch_test_bot")
    события: list = []

    def выдать():
        события.append(("generate",))
        return "busy", None

    pult = телеграм.Пульт(store, выдать)
    client = ФальшивыйКлиент(события)
    pult.обработать(_start(secret), client)
    события.clear()
    pult.обработать(_button(), client)

    assert [event[0] for event in события] == ["answer", "generate", "send"]
    assert "уже идёт расчёт" in события[-1][2]


def test_статус_сервера_не_отдаёт_токен_или_ссылку(tmp_path, monkeypatch):
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    store = телеграм.Хранилище(tmp_path / "telegram.json")
    store.подключить(ТОКЕН, "nakedlunch_test_bot")
    pult = телеграм.Пульт(store, lambda: ("busy", None))
    monkeypatch.setattr(server, "_ТЕЛЕГРАМ", pult)

    response = server.app.test_client().get("/api/telegram/status")
    assert response.status_code == 200
    body = response.get_json()
    assert body["configured"] is True
    assert body["username"] == "nakedlunch_test_bot"
    assert "token" not in body
    assert "link" not in body
    assert ТОКЕН not in json.dumps(body)


def test_подключение_возвращает_только_одноразовую_ссылку(tmp_path, monkeypatch):
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    class Пульт:
        def __init__(self):
            self.received = None

        def подключить(self, token, username):
            self.received = (token, username)
            return "одноразовый-секрет"

        def статус(self):
            return {"configured": True, "username": "nakedlunch_test_bot",
                    "paired": False, "awaiting_pair": True,
                    "running": True, "state": "running", "error": ""}

    pult = Пульт()
    monkeypatch.setattr(server.телеграм, "проверить_токен",
                        lambda raw: (ТОКЕН, "nakedlunch_test_bot"))
    monkeypatch.setattr(server, "_пульт_телеграм", lambda: pult)

    response = server.app.test_client().post("/api/telegram/connect", json={"token": ТОКЕН})
    body = response.get_json()
    assert response.status_code == 200
    assert pult.received == (ТОКЕН, "nakedlunch_test_bot")
    assert body["link"] == "https://t.me/nakedlunch_test_bot?start=одноразовый-секрет"
    assert "token" not in body
    assert ТОКЕН not in json.dumps(body)


def test_телеграм_ждёт_показанную_лентой_строфу_а_не_собирает_её_сам():
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    пульт = server._ПультЛенты()
    # Первый долгий опрос — доказательство, что настоящее окно Ленты готово
    # принять нажатие. Без него бот обязан честно отказаться, а не обойти UI.
    assert пульт.взять_нажатие(timeout=0) is None

    def окно():
        ticket = пульт.взять_нажатие(timeout=1)
        assert ticket
        assert пульт.завершить(ticket, "shown", [{"text": "видимая строка"}])

    worker = threading.Thread(target=окно)
    worker.start()
    state, rows = пульт.нажать(timeout=1)
    worker.join(1)

    assert not worker.is_alive()
    assert state == "shown"
    assert rows == [{"text": "видимая строка"}]


def test_роуты_пульта_передают_только_ответ_живой_ленты(monkeypatch):
    """Проверка именно HTTP-стыка: server не умеет собрать текст в обход
    окна, а /done возвращает только тот ticket, который забрало окно."""
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    пульт = server._ПультЛенты()
    monkeypatch.setattr(server, "_ПУЛЬТ_ЛЕНТЫ", пульт)
    client_id = "test-window"
    assert пульт.взять_нажатие(client_id, timeout=0) is None
    готово = threading.Event()
    ответ: dict = {}

    def окно():
        with server.app.test_client() as client:
            готово.set()
            next_response = client.post("/api/telegram/lenta/next", json={"client": client_id})
            ticket = next_response.get_json()["ticket"]
            ответ["ticket"] = ticket
            done_response = client.post("/api/telegram/lenta/done", json={
                "ticket": ticket, "state": "shown", "rows": [{"text": "с экрана"}],
                "client": client_id,
            })
            ответ["done"] = (done_response.status_code, done_response.get_json())

    worker = threading.Thread(target=окно)
    worker.start()
    assert готово.wait(1)
    state, rows = пульт.нажать(timeout=1)
    worker.join(1)

    assert not worker.is_alive()
    assert ответ["ticket"]
    assert ответ["done"] == (200, {"ok": True})
    assert (state, rows) == ("shown", [{"text": "с экрана"}])


def test_долгий_опрос_ленты_не_выдаётся_за_медленный_запрос(monkeypatch):
    """Тайм-аут long poll — нормальное состояние, а не предупреждение."""
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    записи = []
    monkeypatch.setattr(server.журнал, "запись", lambda *args: записи.append(args))

    with server.app.test_request_context("/api/telegram/lenta/next", method="POST"):
        server.request.environ["_начало"] = time.time() - 20
        server._записать_итог(server.app.response_class("", status=200))

    assert записи == []

    with server.app.test_request_context("/api/generate", method="POST"):
        server.request.environ["_начало"] = time.time() - 20
        server._записать_итог(server.app.response_class("", status=200))

    assert len(записи) == 1
    assert записи[0][0] == "сервер"
    assert "POST /api/generate" in записи[0][1]
    assert записи[0][2] == "внимание"

    тихий = logging.makeLogRecord({
        "msg": '127.0.0.1 - - [now] "POST /api/telegram/lenta/next HTTP/1.1" 200 -',
    })
    ошибка = logging.makeLogRecord({
        "msg": '127.0.0.1 - - [now] "POST /api/telegram/lenta/next HTTP/1.1" 500 -',
    })
    фильтр = server._БезСамоопроса()
    assert not фильтр.filter(тихий)
    assert фильтр.filter(ошибка)


def test_повторная_кнопка_во_время_показа_честно_говорит_занято():
    """После получения ticket у окна нет второго long poll, поэтому старая
    проверка живости уже истекает. Но действующая строфа всё равно означает
    «занято», а не ложное «окно офлайн»."""
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    пульт = server._ПультЛенты()
    пульт._ОКНО_ЖИВО = 0.01
    assert пульт.взять_нажатие(timeout=0) is None
    ticket_ready = threading.Event()
    release = threading.Event()
    result: dict = {}

    def окно():
        ticket = пульт.взять_нажатие(timeout=1)
        result["ticket"] = ticket
        ticket_ready.set()
        assert release.wait(1)
        assert пульт.завершить(ticket, "cancelled")

    def бот():
        result["first"] = пульт.нажать(timeout=1)

    window = threading.Thread(target=окно)
    window.start()
    bot = threading.Thread(target=бот)
    bot.start()
    assert ticket_ready.wait(1)
    time.sleep(0.03)
    assert пульт.нажать(timeout=0) == ("busy", None)
    release.set()
    bot.join(1)
    window.join(1)

    assert not bot.is_alive() and not window.is_alive()
    assert result["first"] == ("cancelled", None)


def test_закрытие_окна_сразу_будит_ожидающий_бота():
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    пульт = server._ПультЛенты()
    assert пульт.взять_нажатие(timeout=0) is None
    ticket_ready = threading.Event()
    result: dict = {}

    def окно():
        ticket = пульт.взять_нажатие(timeout=1)
        assert ticket
        ticket_ready.set()

    def бот():
        result["value"] = пульт.нажать(timeout=1)

    window = threading.Thread(target=окно)
    window.start()
    bot = threading.Thread(target=бот)
    bot.start()
    assert ticket_ready.wait(1)
    пульт.отменить()
    bot.join(1)
    window.join(1)

    assert not bot.is_alive() and not window.is_alive()
    assert result["value"] == ("cancelled", None)


def test_новое_окно_вытесняет_оборванный_запрос_старого():
    """Reload не должен отдавать ticket старому fetch: тот уже не сможет
    показать строфу, а значит не вправе ни завершить, ни удерживать бота."""
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    пульт = server._ПультЛенты()
    assert пульт.взять_нажатие("старое-окно", timeout=0) is None
    claimed = threading.Event()
    result: dict = {}

    def старое_окно():
        ticket = пульт.взять_нажатие("старое-окно", timeout=1)
        result["ticket"] = ticket
        claimed.set()

    def бот():
        result["bot"] = пульт.нажать(timeout=1)

    window = threading.Thread(target=старое_окно)
    window.start()
    bot = threading.Thread(target=бот)
    bot.start()
    assert claimed.wait(1)
    assert result["ticket"]
    # Новый webview отменяет запрос предшественника ещё до своей следующей
    # выдачи. Возвращать ему ticket здесь нечего, потому что старый уже снят.
    assert пульт.взять_нажатие("новое-окно", timeout=0) is None
    bot.join(1)
    window.join(1)

    assert not bot.is_alive() and not window.is_alive()
    assert result["bot"] == ("cancelled", None)
    assert not пульт.завершить(result["ticket"], "shown", [{"text": "старое"}],
                                "старое-окно")


def test_роут_подключения_отвергает_не_json_объект_без_пятисотки():
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    response = server.app.test_client().post("/api/telegram/connect", json=[])
    assert response.status_code == 400
    assert "токен" in response.get_json()["error"]


def test_бот_не_читает_профиль_и_не_собирает_текст_в_сервере(monkeypatch):
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    import server

    class Лента:
        def нажать(self):
            return "shown", [{"text": "текст с экрана"}]

    monkeypatch.setattr(server, "_ПУЛЬТ_ЛЕНТЫ", Лента())
    monkeypatch.setattr(server.settings_mod, "read",
                        lambda: pytest.fail("бот не должен читать сохранённый профиль"))
    monkeypatch.setattr(server, "_собрать_строфу",
                        lambda _payload: pytest.fail("бот не должен собирать строфу сам"))

    assert server._телеграм_нажать_ленту() == ("shown", [{"text": "текст с экрана"}])


def test_модуль_пульта_явно_попадает_в_собранное_приложение():
    spec = (КОРЕНЬ / "nakedlunch.spec").read_text("utf-8")
    assert '"телеграм"' in spec


@pytest.mark.parametrize("raw", ["", "abc", "123:короткий"])
def test_неверный_токен_не_принимается(raw):
    with pytest.raises(ValueError):
        телеграм.проверить_формат_токена(raw)
