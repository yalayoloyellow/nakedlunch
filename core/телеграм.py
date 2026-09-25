"""Приватный Telegram-пульт для Ленты.

Токен и привязка живут отдельно от ``settings.json``: обычные настройки
отдаются окну через HTTP, а секрет никогда не должен попасть туда, в журнал
или в Git. Бот не знает настроек Ленты и не меняет их — сервер передаёт ему
только нажатие, а строфу собирает и показывает открытая Лента.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import пути


API_ROOT = "https://api.telegram.org"
MAX_TEXT = 4096
POLL_TIMEOUT = 8
CALLBACK_NEXT = "nl:next"
_TOKEN = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{20,}$")
_ALLOWED_UPDATES = ["message", "callback_query"]


class ОшибкаTelegram(RuntimeError):
    """Ответ Telegram, пригодный для решения, но без секрета в тексте."""

    def __init__(self, method: str, code: int = 0, retry_after: int = 0):
        self.method = method
        self.code = code
        self.retry_after = retry_after
        super().__init__(f"Telegram: {method} ({code or 'неизвестный ответ'})")


class НетСвязи(RuntimeError):
    """Сеть не дала получить или отправить ответ Telegram."""


class ОшибкаХранилища(RuntimeError):
    """Файл подключения нельзя безопасно прочитать или изменить."""


def проверить_формат_токена(raw: object) -> str:
    token = str(raw or "").strip()
    if not _TOKEN.fullmatch(token):
        raise ValueError("токен BotFather выглядит неверно")
    return token


def _json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


class Клиент:
    """Небольшой синхронный клиент Telegram Bot API без внешних зависимостей."""

    def __init__(self, token: str):
        self._token = проверить_формат_токена(token)

    def вызвать(self, method: str, params: dict[str, Any] | None = None,
               *, timeout: float = 20.0, attempts: int = 3) -> Any:
        payload = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
        url = f"{API_ROOT}/bot{self._token}/{method}"
        last: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                request = urllib.request.Request(url, data=payload, method="POST")
                request.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 -- fixed Telegram endpoint
                    body = response.read()
            except urllib.error.HTTPError as exc:
                reply = _json(exc.read())
                wait = int((reply.get("parameters") or {}).get("retry_after") or 0)
                error = ОшибкаTelegram(method, int(exc.code or 0), wait)
                if exc.code == 429 and attempt + 1 < attempts:
                    time.sleep(min(30, max(1, wait)))
                    last = error
                    continue
                raise error from None
            except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
                last = НетСвязи(f"Telegram недоступен во время {method}")
                if attempt + 1 < attempts:
                    time.sleep(min(4, attempt + 1))
                    continue
                raise last from exc
            reply = _json(body)
            if reply.get("ok"):
                return reply.get("result")
            wait = int((reply.get("parameters") or {}).get("retry_after") or 0)
            error = ОшибкаTelegram(method, int(reply.get("error_code") or 0), wait)
            if error.code == 429 and attempt + 1 < attempts:
                time.sleep(min(30, max(1, wait)))
                last = error
                continue
            raise error
        raise last or НетСвязи(f"Telegram недоступен во время {method}")

    def кто_я(self) -> dict[str, Any]:
        result = self.вызвать("getMe", timeout=15)
        return result if isinstance(result, dict) else {}

    def снять_вебхук(self) -> None:
        self.вызвать("deleteWebhook", {"drop_pending_updates": False}, timeout=15)

    def обновления(self, offset: int) -> list[dict[str, Any]]:
        result = self.вызвать(
            "getUpdates",
            {"offset": offset, "timeout": POLL_TIMEOUT,
             "allowed_updates": _ALLOWED_UPDATES},
            timeout=POLL_TIMEOUT + 12,
            attempts=1,
        )
        return [item for item in (result or []) if isinstance(item, dict)]

    def послать(self, chat_id: int, text: str,
                keyboard: dict[str, Any] | None = None) -> dict[str, Any]:
        if len(text) > MAX_TEXT:
            raise ValueError("текст длиннее лимита Telegram")
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if keyboard is not None:
            params["reply_markup"] = keyboard
        result = self.вызвать("sendMessage", params)
        if not isinstance(result, dict):
            raise НетСвязи("Telegram не подтвердил отправку текста")
        return result

    def ответить_на_кнопку(self, callback_id: str, text: str = "",
                            alert: bool = False) -> None:
        self.вызвать(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": text[:200],
             "show_alert": bool(alert)},
            timeout=10,
            attempts=1,
        )


def проверить_токен(raw: object) -> tuple[str, str]:
    """Проверить токен до записи на диск и вернуть (токен, username)."""
    token = проверить_формат_токена(raw)
    identity = Клиент(token).кто_я()
    username = str(identity.get("username") or "").strip().lstrip("@")
    if not identity.get("is_bot") or not username:
        raise ValueError("Telegram не подтвердил, что это токен бота")
    return token, username


class Хранилище:
    """Один закрытый файл ``data/telegram.json`` с правами только владельца."""

    def __init__(self, path: Path | None = None):
        self.path = path or пути.данные("telegram.json")
        self._lock = threading.RLock()

    @staticmethod
    def _id(raw: object) -> int | None:
        return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0 else None

    def _read_locked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            if os.name != "nt":
                os.chmod(self.path, 0o600)
            raw = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise ОшибкаХранилища("файл подключения Telegram не читается") from exc
        if not isinstance(raw, dict):
            raise ОшибкаХранилища("файл подключения Telegram имеет неверный формат")
        token = str(raw.get("token") or "").strip()
        if token:
            try:
                token = проверить_формат_токена(token)
            except ValueError as exc:
                raise ОшибкаХранилища("в файле Telegram неверный токен") from exc
        secret = raw.get("pair_secret")
        secret = secret if isinstance(secret, str) and secret else ""
        try:
            offset = max(0, int(raw.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        return {
            "token": token,
            "username": str(raw.get("username") or "").strip().lstrip("@"),
            "pair_secret": secret,
            "owner_user_id": self._id(raw.get("owner_user_id")),
            "owner_chat_id": self._id(raw.get("owner_chat_id")),
            "offset": offset,
        }

    def _write_locked(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_name = ""
        try:
            fd, temp_name = tempfile.mkstemp(prefix=".telegram-", suffix=".new",
                                             dir=str(self.path.parent))
            try:
                os.fchmod(fd, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
            temp_name = ""
            if os.name != "nt":
                os.chmod(self.path, 0o600)
        except OSError as exc:
            raise ОшибкаХранилища("не удалось безопасно сохранить подключение Telegram") from exc
        finally:
            if temp_name:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass

    def снимок(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._read_locked())

    def статус(self) -> dict[str, Any]:
        snapshot = self.снимок()
        return {
            "configured": bool(snapshot.get("token")),
            "username": snapshot.get("username", ""),
            "paired": bool(snapshot.get("owner_user_id") and snapshot.get("owner_chat_id")),
            "awaiting_pair": bool(snapshot.get("pair_secret")),
        }

    def подключить(self, token: str, username: str) -> str:
        token = проверить_формат_токена(token)
        username = str(username or "").strip().lstrip("@")
        if not username:
            raise ValueError("Telegram не вернул имя бота")
        secret = secrets.token_urlsafe(24)
        with self._lock:
            self._write_locked({
                "token": token,
                "username": username,
                "pair_secret": secret,
                "owner_user_id": None,
                "owner_chat_id": None,
                "offset": 0,
            })
        return secret

    def отключить(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                return
            except OSError as exc:
                raise ОшибкаХранилища("не удалось удалить подключение Telegram") from exc

    def привязать(self, secret: str, user_id: int, chat_id: int) -> bool:
        with self._lock:
            data = self._read_locked()
            current = data.get("pair_secret") or ""
            try:
                same = secrets.compare_digest(current.encode("ascii"), secret.encode("ascii"))
            except (AttributeError, UnicodeEncodeError):
                same = False
            if not current or not same:
                return False
            if data.get("owner_user_id") or data.get("owner_chat_id"):
                return False
            data["owner_user_id"] = user_id
            data["owner_chat_id"] = chat_id
            data["pair_secret"] = ""
            self._write_locked(data)
            return True

    def разрешён(self, user_id: int, chat_id: int) -> bool:
        data = self.снимок()
        return data.get("owner_user_id") == user_id and data.get("owner_chat_id") == chat_id

    def смещение(self, offset: int) -> None:
        with self._lock:
            data = self._read_locked()
            if not data.get("token"):
                return
            data["offset"] = max(int(data.get("offset") or 0), int(offset))
            self._write_locked(data)


def _клавиатура() -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "выдать текст", "callback_data": CALLBACK_NEXT}]]}


def _части(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    parts: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        if len(text) > MAX_TEXT:
            raise ValueError("одна строка длиннее лимита Telegram")
        extra = len(text) + (1 if current else 0)
        if current and size + extra > MAX_TEXT:
            parts.append(current)
            current, size = [], 0
        current.append(row)
        size += len(text) + (1 if len(current) > 1 else 0)
    if current:
        parts.append(current)
    return parts


class Пульт:
    """Один long-polling поток и строго один привязанный приватный чат."""

    def __init__(self, store: Хранилище,
                 выдать: Callable[[], tuple[str, list[dict[str, Any]] | None]],
                 сообщить: Callable[[str], None] | None = None):
        self.store = store
        self._выдать = выдать
        self._сообщить = сообщить or (lambda _text: None)
        self._stop = threading.Event()
        self._lifecycle = threading.RLock()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._lock_fd: int | None = None
        self._state = "stopped"
        self._error = ""

    def _set_state(self, state: str, error: str = "") -> None:
        with self._state_lock:
            self._state = state
            self._error = error

    def статус(self) -> dict[str, Any]:
        out = self.store.статус()
        with self._state_lock:
            out.update({"running": self._state == "running", "state": self._state,
                        "error": self._error})
        return out

    def _захватить_замок(self) -> bool:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - macOS uses fcntl
            return True
        path = self.store.path.with_name(self.store.path.name + ".lock")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            os.chmod(path, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            try:
                os.close(fd)
            except (UnboundLocalError, OSError):
                pass
            return False
        self._lock_fd = fd
        return True

    def _отпустить_замок(self) -> None:
        fd = self._lock_fd
        self._lock_fd = None
        if fd is None:
            return
        try:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        try:
            os.close(fd)
        except OSError:
            pass

    def запустить(self) -> bool:
        try:
            configured = self.store.статус()["configured"]
        except ОшибкаХранилища as exc:
            self._set_state("error", str(exc))
            return False
        if not configured:
            self._set_state("stopped")
            return False
        with self._lifecycle:
            if self._thread is not None and self._thread.is_alive():
                return not self._stop.is_set()
            if not self._захватить_замок():
                self._set_state("error", "бот уже запущен в другом окне")
                return False
            self._stop.clear()
            self._set_state("starting")
            self._thread = threading.Thread(target=self._цикл, name="nl-telegram", daemon=True)
            self._thread.start()
            return True

    def остановить(self, timeout: float = 20.0) -> bool:
        with self._lifecycle:
            thread = self._thread
            self._stop.set()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        if thread is not None and thread.is_alive():
            self._set_state("stopping", "опрос Telegram ещё останавливается")
            return False
        with self._lifecycle:
            if self._thread is thread:
                self._thread = None
            self._отпустить_замок()
        self._set_state("stopped")
        return True

    def подключить(self, token: str, username: str) -> str:
        if not self.остановить():
            raise RuntimeError("предыдущий опрос Telegram не успел остановиться")
        secret = self.store.подключить(token, username)
        if not self.запустить():
            raise RuntimeError(self.статус().get("error") or "не удалось запустить Telegram")
        return secret

    def отключить(self) -> None:
        if not self.остановить():
            raise RuntimeError("опрос Telegram не успел остановиться")
        self.store.отключить()

    def _цикл(self) -> None:
        try:
            snapshot = self.store.снимок()
            client = Клиент(snapshot["token"])
            try:
                client.снять_вебхук()
            except ОшибкаTelegram as exc:
                if exc.code == 401:
                    self._set_state("error", "Telegram не принял сохранённый токен")
                    return
            self._set_state("running")
            offset = int(snapshot.get("offset") or 0)
            failures = 0
            while not self._stop.is_set():
                try:
                    updates = client.обновления(offset)
                    failures = 0
                except ОшибкаTelegram as exc:
                    if exc.code == 401:
                        self._set_state("error", "Telegram не принял сохранённый токен")
                        self._сообщить("Telegram остановлен: токен не принят")
                        return
                    if exc.code == 409:
                        self._set_state("error", "этот бот уже опрашивает другое окно")
                        self._сообщить("Telegram остановлен: бот уже опрашивает другое окно")
                        return
                    failures += 1
                    self._set_state("waiting", "Telegram временно недоступен")
                    self._stop.wait(min(30, max(1, exc.retry_after or 2 ** min(failures, 5))))
                    continue
                except (НетСвязи, ОшибкаХранилища):
                    failures += 1
                    self._set_state("waiting", "нет связи с Telegram")
                    self._stop.wait(min(30, 2 ** min(failures, 5)))
                    continue
                self._set_state("running")
                for update in updates:
                    if self._stop.is_set():
                        break
                    update_id = update.get("update_id")
                    if not isinstance(update_id, int):
                        continue
                    try:
                        self.обработать(update, client)
                    except Exception:
                        self._сообщить("Telegram: не удалось обработать обновление")
                    offset = max(offset, update_id + 1)
                    try:
                        self.store.смещение(offset)
                    except ОшибкаХранилища:
                        self._set_state("error", "не удалось сохранить состояние Telegram")
                        self._сообщить("Telegram остановлен: не удалось сохранить состояние")
                        return
        except ОшибкаХранилища as exc:
            self._set_state("error", str(exc))
        except (ValueError, НетСвязи):
            self._set_state("error", "не удалось запустить Telegram")
        finally:
            with self._lifecycle:
                self._отпустить_замок()

    @staticmethod
    def _private(chat: object, user: object) -> tuple[int, int] | None:
        if not isinstance(chat, dict) or not isinstance(user, dict):
            return None
        if chat.get("type") != "private":
            return None
        chat_id = chat.get("id")
        user_id = user.get("id")
        if (not isinstance(chat_id, int) or not isinstance(user_id, int)
                or chat_id <= 0 or user_id <= 0 or user.get("is_bot")):
            return None
        return user_id, chat_id

    def обработать(self, update: dict[str, Any], client: Клиент) -> None:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            self._кнопка(callback, client)
            return
        message = update.get("message")
        if isinstance(message, dict):
            self._сообщение(message, client)

    def _сообщение(self, message: dict[str, Any], client: Клиент) -> None:
        ids = self._private(message.get("chat"), message.get("from"))
        if ids is None:
            return
        user_id, chat_id = ids
        text = str(message.get("text") or "").strip()
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            secret = parts[1].strip() if len(parts) == 2 else ""
            if secret and self.store.привязать(secret, user_id, chat_id):
                client.послать(chat_id, "Готово. Настройки берутся из Ленты на компьютере.",
                               _клавиатура())
                self._сообщить("Telegram: приватный чат привязан")
                return
            if self.store.разрешён(user_id, chat_id):
                client.послать(chat_id, "Нажми кнопку, чтобы выдать следующую строфу.",
                               _клавиатура())
                return
            if not self.store.статус().get("paired"):
                client.послать(chat_id, "Открой ссылку подключения из настроек Naked Lunch.")

    def _кнопка(self, callback: dict[str, Any], client: Клиент) -> None:
        callback_id = str(callback.get("id") or "")
        message = callback.get("message")
        ids = self._private(message.get("chat") if isinstance(message, dict) else None,
                            callback.get("from"))
        if ids is None or callback.get("data") != CALLBACK_NEXT:
            try:
                if callback_id:
                    client.ответить_на_кнопку(callback_id, "кнопка недоступна", True)
            except (ОшибкаTelegram, НетСвязи):
                pass
            return
        user_id, chat_id = ids
        if not self.store.разрешён(user_id, chat_id):
            try:
                if callback_id:
                    client.ответить_на_кнопку(callback_id, "этот бот уже подключён", True)
            except (ОшибкаTelegram, НетСвязи):
                pass
            return
        try:
            if callback_id:
                client.ответить_на_кнопку(callback_id)
        except (ОшибкаTelegram, НетСвязи):
            pass
        try:
            state, rows = self._выдать()
            if state == "busy":
                client.послать(chat_id,
                               "На компьютере уже идёт расчёт. Нажми ещё раз, когда он закончится.",
                               _клавиатура())
                return
            if state == "offline":
                client.послать(chat_id,
                               "Лента на компьютере не готова. Открой Naked Lunch и дождись загрузки окна.",
                               _клавиатура())
                return
            if state == "impossible":
                client.послать(chat_id,
                               "Под текущими настройками полная строфа не собралась.",
                               _клавиатура())
                return
            if state == "timeout":
                client.послать(chat_id,
                               "Лента на компьютере не ответила. Проверь, что окно Naked Lunch открыто.",
                               _клавиатура())
                return
            if state in {"cancelled", "error"}:
                client.послать(chat_id,
                               "Лента не завершила выдачу. Причина есть в журнале Naked Lunch.",
                               _клавиатура())
                return
            rows = [row for row in (rows or [])
                    if isinstance(row, dict) and str(row.get("text") or "").strip()]
            if state != "shown" or not rows:
                raise RuntimeError("пульт Ленты не вернул показанный текст")
            chunks = _части(rows)
            for index, chunk in enumerate(chunks):
                client.послать(chat_id, "\n".join(str(row["text"]).strip() for row in chunk),
                               _клавиатура() if index == len(chunks) - 1 else None)
        except (ОшибкаTelegram, НетСвязи):
            self._set_state("waiting", "не удалось отправить текст в Telegram")
            self._сообщить("Telegram: текст не удалось отправить")
        except Exception:
            self._set_state("error", "пульт Ленты не вернул показанный текст")
            self._сообщить("Telegram: выдача Ленты завершилась ошибкой")
