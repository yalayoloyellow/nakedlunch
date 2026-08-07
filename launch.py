#!/usr/bin/env python3
# nakedlunch launcher — builds the React front end if needed, starts the Flask
# server (api/server.py) on a free port, then opens a native macOS window
# (pywebview) pointing at it. Falls back to the default browser if pywebview
# isn't installed. Ported from pusher/gui/launch.py.
#
# Экземпляр ровно один, и он всегда текущий: перед стартом launch.py смотрит
# data/instance.json и либо поднимает окно уже работающей программы, либо
# перезапускает её, если код с тех пор изменился. См. блок «один экземпляр и
# свежесть кода» ниже — там же, почему без этого ярлык переставал приносить
# обновления.

import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

try:
    import webview   # optional — module-level so ExportApi can reach webview.FileDialog too
except ImportError:
    webview = None

HERE = Path(__file__).resolve().parent
VENV_PY = HERE / ".venv" / "bin" / "python"
PY = str(VENV_PY) if VENV_PY.exists() else sys.executable
SERVER = str(HERE / "api" / "server.py")
REACT_APP = HERE / "interface" / "react-app"
DIST_INDEX = REACT_APP / "dist" / "index.html"
ICON = HERE / "interface" / "icon" / "nakedlunch.icns"   # см. tools/make_icon.py

# --- один экземпляр и свежесть кода ------------------------------------------
# Двойной клик по ярлыку обязан давать ТЕКУЩУЮ программу. До 2026-08-03 не
# давал: запускатель бандла делал exec, питон наследовал PID оболочки бандла, и
# LaunchServices считал com.yala.nakedlunch запущенным. Повторный клик сводился
# к «активировать уже запущенное» и до launch.py не доходил вовсе (измерено:
# PID процессов до и после клика те же — 45333/45335). отчёт: через ярлык открывалась старая версия, без обновлений..
#
# Теперь бандл запускает launch.py отдельным процессом и сразу выходит (см.
# nakedlunch.app/Contents/MacOS/nakedlunch), а решение принимает сам launch.py
# по этому файлу:
#   запущенное свежее      → поднять его окно и выйти, второго окна не будет;
#   запущенное устарело    → перезапустить, это и есть «дай мне обновления»;
#   идёт запись фристайла  → не трогать: дубль дороже апдейта.
INSTANCE = HERE / "data" / "instance.json"
_INSTANCE_LOCK = threading.Lock()   # мост записи ходит сюда из своих потоков

# --- заставка на время подъёма сервера ---------------------------------------
# Холодный старт — 26.6 с (замерено): сервер поднимает корпус, индексы и
# тезаурус. Окно теперь создаётся сразу с этой страницей и переезжает на
# настоящий адрес, когда сервер ответит. Палитра — тёмная тема интерфейса
# (Nakedlunch.jsx, ROOT_STYLE); светлую тему заставка не знает и не угадывает.
# Ничего внешнего не грузим: шрифт берём системный, если JetBrains Mono нет.
_SPLASH_CSS = """
  html,body{height:100%;margin:0}
  body{background:#131313;color:#ededed;display:flex;align-items:center;
       justify-content:center;-webkit-font-smoothing:antialiased;
       font-family:'JetBrains Mono',ui-monospace,Menlo,monospace;font-size:13px}
  .b{display:flex;flex-direction:column;align-items:center;gap:14px}
  .n{letter-spacing:.14em;text-transform:lowercase}
  .s{color:#949494;font-size:11px;letter-spacing:.04em}
  .r{width:180px;height:1px;background:#242424;overflow:hidden}
  .r i{display:block;width:38%;height:100%;background:#5c5c5c;
       animation:go 1.5s cubic-bezier(.4,0,.2,1) infinite}
  @keyframes go{0%{transform:translateX(-100%)}100%{transform:translateX(360%)}}
  @media (prefers-reduced-motion:reduce){.r i{animation:none;width:100%;opacity:.4}}
"""
SPLASH = ("<!doctype html><meta charset=utf-8><style>" + _SPLASH_CSS + "</style>"
          "<div class=b><div class=n>nakedlunch</div>"
          "<div class=r><i></i></div>"
          "<div class=s>поднимаю корпус и индексы</div></div>")
SPLASH_FAIL = ("<!doctype html><meta charset=utf-8><style>" + _SPLASH_CSS + "</style>"
               "<div class=b><div class=n>nakedlunch</div>"
               "<div class=s>сервер не поднялся за отведённое время</div>"
               "<div class=s>подробности: ~/Library/Logs/nakedlunch.log</div></div>")


def _gui_error(msg: str, title: str = "nakedlunch не запустился") -> None:
    """Окно с ошибкой, когда терминала нет. Из .app stderr уходит в лог, и без
    этого двойной клик по сломанной установке выглядел бы как «ничего не
    произошло» — худший вид отказа."""
    if sys.stderr.isatty():
        return
    try:
        subprocess.run(["/usr/bin/osascript", "-", msg, title], input=(
            'on run argv\n'
            '  display alert (item 2 of argv) message (item 1 of argv) as critical\n'
            'end run\n'), text=True, timeout=120)
    except Exception:
        pass


def source_stamp() -> float:
    """Отпечаток версии: самое свежее время изменения того, что реально влияет
    на программу — собранный фронт и живой питон-код. Данные и словари не
    считаем: корпус меняется при каждой работе, и по нему любой экземпляр
    считался бы устаревшим через минуту после запуска."""
    stamps = [Path(__file__).stat().st_mtime]
    if DIST_INDEX.exists():
        stamps.append(DIST_INDEX.stat().st_mtime)
    for root in (HERE / "api", HERE / "core"):
        for dirpath, dirnames, filenames in os.walk(root):
            # core/data — это словари и индексы (гигабайты), обходить их незачем
            dirnames[:] = [d for d in dirnames if d not in ("data", "__pycache__")]
            for name in filenames:
                if name.endswith(".py"):
                    stamps.append(os.path.getmtime(os.path.join(dirpath, name)))
    return max(stamps)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_instance() -> dict:
    """Запись о ЖИВОМ экземпляре или {}. Живой — это и pid на месте, и сервер
    отвечает: файл мог остаться от убитого процесса, а его PID к тому времени
    достаться кому угодно."""
    try:
        rec = json.loads(INSTANCE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    pid, port = int(rec.get("pid") or 0), int(rec.get("port") or 0)
    if not pid or not port or not _pid_alive(pid):
        return {}
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
            if r.status != 200:
                return {}
    except Exception:
        return {}
    return rec


def write_instance(**fields) -> None:
    """Обновить запись, сохранив остальные поля. Через временный файл: оборванная
    запись хуже отсутствующей — по ней следующий запуск решит, что экземпляра
    нет, и поднимет второе окно поверх работающего."""
    with _INSTANCE_LOCK:
        try:
            rec = json.loads(INSTANCE.read_text(encoding="utf-8"))
        except Exception:
            rec = {}
        rec.update(fields)
        try:
            INSTANCE.parent.mkdir(parents=True, exist_ok=True)
            tmp = INSTANCE.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            tmp.replace(INSTANCE)
        except OSError as e:
            print(f"nakedlunch: запись {INSTANCE} не удалась ({e})", file=sys.stderr)


def forget_instance() -> None:
    """Убрать за собой — но только СВОЮ запись: если нас погасил перезапуск,
    файл уже принадлежит новому экземпляру, и стирать его нельзя."""
    with _INSTANCE_LOCK:
        try:
            rec = json.loads(INSTANCE.read_text(encoding="utf-8"))
        except Exception:
            return
        if int(rec.get("pid") or 0) == os.getpid():
            try:
                INSTANCE.unlink()
            except OSError:
                pass


def activate(pid: int) -> bool:
    """Поднять окно уже запущенного экземпляра. NSRunningApplication, а не
    AppleScript через System Events: активация чужого приложения по PID не
    требует разрешений, а System Events требует «Универсальный доступ» — и
    молча ничего не делал бы, пока пользователь его не выдаст."""
    try:
        from AppKit import NSRunningApplication
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        # 1 << 1 — NSApplicationActivateIgnoringOtherApps: клик по ярлыку должен
        # вытащить окно наверх сейчас, а не «когда дойдёт очередь»
        return bool(app.activateWithOptions_(1 << 1))
    except Exception as e:
        print(f"nakedlunch: окно прошлого экземпляра не поднято ({e})", file=sys.stderr)
        return False


def stray_pids() -> list:
    """Процессы прежнего экземпляра, о котором НЕТ записи: аварийно убитый,
    запущенный из терминала или — однократно — та версия, которая ещё не умела
    регистрироваться. Без этого первый же клик после обновления поднял бы второе
    окно рядом со старым. Ищем по абсолютному пути: у соседних проектов свои
    launch.py и server.py, путать их нельзя."""
    found = []
    for pattern in (str(Path(__file__).resolve()), SERVER):
        try:
            res = subprocess.run(["/usr/bin/pgrep", "-f", pattern],
                                 capture_output=True, text=True, timeout=5)
        except Exception as e:
            print(f"nakedlunch: не смог поискать прежние процессы ({e})", file=sys.stderr)
            continue
        for chunk in res.stdout.split():
            try:
                pid = int(chunk)
            except ValueError:
                continue
            if pid != os.getpid() and pid not in found:
                found.append(pid)
    return found


def stop_pids(pids: list, timeout: float = 8.0) -> None:
    """Погасить процессы: сперва вежливо и ВСЕМ сразу, потом жёстко. Осиротевший
    server.py держал бы порт и файлы корпуса, а его окно исчезло бы — худший
    исход из возможных."""
    pids = [p for p in pids if p and _pid_alive(p)]
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + timeout
    while time.time() < deadline and any(_pid_alive(p) for p in pids):
        time.sleep(0.1)
    for p in pids:
        if _pid_alive(p):
            try:
                os.kill(p, signal.SIGKILL)
            except OSError:
                pass


def brand_app() -> None:
    """Иконка и имя в доке. Процесс — это python из .venv, и NSBundle видит
    именно его, а не наш .app (запускатель бандла отвязывает процесс и выходит,
    см. Contents/MacOS/nakedlunch). Поэтому иконку и имя ставим руками — это
    работает и при запуске из .app, и из run.command."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        if ICON.exists():
            img = NSImage.alloc().initWithContentsOfFile_(str(ICON))
            if img is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(img)
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "nakedlunch"
    except Exception as e:                            # не macOS/нет pyobjc — не беда
        print(f"nakedlunch: иконка приложения не поставлена ({e})", file=sys.stderr)


def child_env() -> dict:
    # A Finder/.app launch doesn't source ~/.zshrc, so Homebrew's bin dirs (where
    # node/npm live) may be off PATH. Prepend the usual locations.
    env = os.environ.copy()
    parts = env.get("PATH", "").split(":")
    for p in ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/local/sbin"):
        if p not in parts and Path(p).is_dir():
            parts.insert(0, p)
    env["PATH"] = ":".join(parts)
    return env


def ensure_build() -> bool:
    """Build the front end if dist/ is missing or older than the source."""
    if DIST_INDEX.exists():
        dist_mtime = DIST_INDEX.stat().st_mtime
        stale = any(p.stat().st_mtime > dist_mtime for p in (REACT_APP / "src").rglob("*") if p.is_file())
    else:
        stale = True
    if not stale:
        return True

    npm = shutil.which("npm", path=child_env()["PATH"])
    if not npm:
        print("nakedlunch: npm not found — cannot build the front end", file=sys.stderr)
        return False
    print("nakedlunch: building the front end (first run or source changed)…", file=sys.stderr)
    if not (REACT_APP / "node_modules").exists():
        if subprocess.run([npm, "install"], cwd=str(REACT_APP), env=child_env()).returncode != 0:
            print("nakedlunch: npm install failed", file=sys.stderr)
            return False
    return subprocess.run([npm, "run", "build"], cwd=str(REACT_APP), env=child_env()).returncode == 0


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port


class ExportApi:
    """Exposed to the front end as `window.pywebview.api.*` (user 2026-07-14:
    an <a download> link inside pywebview's embedded webview just navigates
    the WHOLE window to the raw file — no downloads manager, no back button
    to return to the app with. `save_file` opens a real native Save-As dialog
    instead and never navigates anything. Only relevant inside the pywebview
    window; App.jsx falls back to the ordinary Blob+anchor download when this
    bridge isn't present (a plain browser tab)."""

    def __init__(self):
        self.window = None   # set right after create_window(), before start()
        # --- запись фристайла (PLAN.md, ФАЗА 4) --------------------------------
        # Мост pywebview обслуживает КАЖДЫЙ вызов отдельным потоком Python
        # (webview/util.py:335), поэтому все rec_* ходят под одним замком:
        # иначе два чанка одновременно полезут в один дескриптор.
        # Импорты локальные — модуль запуска остаётся модулем запуска, а не
        # тянет писателей WAV при каждом старте окна.
        import threading
        self._rec_lock = threading.Lock()
        self._rec_session = None

    def _recorder(self):
        """core/recorder.py — домен записи. launch.py лежит на уровень выше core."""
        core = str(Path(__file__).resolve().parent / "core")
        if core not in sys.path:
            sys.path.insert(0, core)
        import recorder
        return recorder

    # --- мост записи -----------------------------------------------------------
    # Контракт у всех пяти одинаков: {"ok": True, …} либо {"ok": False,
    # "error": "русский текст"}. Ошибки НЕ глотаются и не превращаются в
    # молчаливое «всё хорошо» — испорченную запись пользователь должен увидеть
    # сразу, а не при монтаже.

    def rec_start(self, track: str, params: dict = None) -> dict:
        """Открыть дорожку. Первая дорожка заводит каталог записи.

        params: {"kind": "wav"|"blob", "channels": 2, "rate": 48000,
                 "ext": "webm"} — ext приходит с браузерной стороны из
        ФАКТИЧЕСКОГО rec.mimeType (в спайке просили webm, получили mp4).
        """
        params = params or {}
        try:
            rec = self._recorder()
            with self._rec_lock:
                s = self._rec_session
                # новая запись начинается, когда прошлая полностью остановлена
                if s is None or s.all_closed():
                    s = rec.Session()
                    self._rec_session = s
                w = s.open_track(
                    str(track),
                    kind=str(params.get("kind") or "wav"),
                    channels=int(params.get("channels") or 2),
                    rate=int(params.get("rate") or 48000),
                    ext=params.get("ext"),
                )
            # Наружу, в файл экземпляра: идущая запись — единственная причина, по
            # которой повторный клик по ярлыку НЕ перезапустит программу ради
            # обновлений (см. main). Порванный дубль не восстановить, апдейт —
            # подождёт.
            write_instance(recording=True)
            return {"ok": True, "track": str(track), "path": w.path,
                    "dir": str(s.dir)}
        except Exception as e:
            return {"ok": False, "error": f"дорожка {track} не открылась: {e}"}

    def rec_chunk(self, track: str, seq: int, b64: str) -> dict:
        """Кусок дорожки. base64 — потому что массив чисел через мост в 16 раз
        медленнее (замерено: 1.17мс против 18.5мс на 96КБ)."""
        import base64
        try:
            data = base64.b64decode(b64 or "", validate=True)
        except Exception as e:
            return {"ok": False, "error": f"чанк {seq} дорожки {track}: битый base64 ({e})"}
        try:
            with self._rec_lock:
                if self._rec_session is None:
                    return {"ok": False, "error": "запись не начата"}
                written, problem = self._rec_session.append(str(track), data, int(seq))
                w = self._rec_session.tracks[str(track)]
                out = {"ok": problem is None, "bytes": written,
                       "total": w.bytes_written, "peak": w.peak}
                if problem:
                    out["error"] = f"дорожка {track}: {problem}"
                return out
        except Exception as e:
            return {"ok": False, "error": f"чанк {seq} дорожки {track} не записан: {e}"}

    def rec_stop(self, track: str) -> dict:
        """Остановить дорожку: финальная штамповка + .partial → финальное имя."""
        try:
            with self._rec_lock:
                if self._rec_session is None:
                    return {"ok": False, "error": "запись не начата"}
                name = str(track)
                path = self._rec_session.stop(name)
                w = self._rec_session.tracks[name]
                out = {"ok": w.error is None, "path": path, "bytes": w.bytes_written,
                       "seconds": w.seconds, "peak": w.peak}
                if w.error:
                    out["error"] = f"дорожка {track}: {w.error}"
                закрыты = self._rec_session.all_closed()
            # Снимаем защиту от перезапуска только когда закрыта ПОСЛЕДНЯЯ
            # дорожка: остановка микрофона при пишущейся картинке — ещё не конец
            # записи. Вне замка, чтобы файл экземпляра не писался под ним.
            if закрыты:
                write_instance(recording=False)
            return out
        except Exception as e:
            return {"ok": False, "error": f"дорожка {track} не остановилась: {e}"}

    def rec_status(self) -> dict:
        """Состояние всех дорожек. last_write_ago и peak — это и есть индикатор:
        дорожка молчит или пишет тишину — сбой, показывать громко."""
        try:
            with self._rec_lock:
                if self._rec_session is None:
                    return {"ok": True, "active": False, "tracks": {}}
                s = self._rec_session
                return {"ok": True, "active": not s.all_closed(),
                        "dir": str(s.dir), "tracks": s.status()}
        except Exception as e:
            return {"ok": False, "error": f"состояние записи недоступно: {e}"}

    def rec_mux(self) -> dict:
        """Склейка через ffmpeg — ПОСЛЕ остановки. Исходники не трогаются."""
        try:
            with self._rec_lock:
                if self._rec_session is None:
                    return {"ok": False, "error": "записи не было"}
                res = self._rec_session.mux()
            if not res.get("ok"):
                # reason у mux уже по-русски; поднимаем его как error, чтобы
                # интерфейсу не пришлось разбирать два разных поля
                res.setdefault("error", res.get("reason", "склейка не удалась"))
            return res
        except Exception as e:
            return {"ok": False, "error": f"склейка не удалась: {e}"}

    def save_file(self, filename: str, content: str) -> dict:
        if self.window is None:
            return {"ok": False, "error": "окно недоступно"}
        try:
            result = self.window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "path": path}


def wait_health(port: int, proc, timeout: float = 40.0) -> bool:
    url = f"http://127.0.0.1:{port}/healthz"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            print(f"nakedlunch: server exited early (code {proc.returncode})", file=sys.stderr)
            return False
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


# WKWebView по умолчанию НЕ отдаёт странице navigator.mediaDevices — микрофон
# фристайла в окне приложения не работал вовсе (в Safari на той же машине —
# работает). Измерено спайком фазы 4: без этого getUserMedia недоступен, с ним
# возвращается настоящая дорожка. Включаем двумя действиями: приватные ключи
# WKPreferences перед загрузкой URL и метод делегата, который отвечает на запрос
# разрешения. Ключи приватные и недокументированные — обновление macOS может их
# убрать, поэтому падать нельзя: не вышло — приложение живёт, микрофон честно
# недоступен (интерфейс это покажет), всё остальное работает.
# ВАЖНО при упаковке в .app: нужен NSMicrophoneUsageDescription в Info.plist,
# иначе система убьёт процесс при первом обращении к микрофону.
_WK_MEDIA_KEYS = ("mediaDevicesEnabled", "mediaStreamEnabled", "peerConnectionEnabled",
                  "mediaCaptureRequiresSecureConnection", "screenCaptureEnabled")


def enable_media_capture() -> None:
    try:
        import objc
        from webview.platforms import cocoa
    except Exception as e:                       # не macOS/нет pyobjc — молча мимо
        print(f"nakedlunch: захват медиа не включён ({e})", file=sys.stderr)
        return

    orig_load = cocoa.BrowserView.load_url

    def load_url(self, url):
        try:
            prefs = self.webview.configuration().preferences()
            for k in _WK_MEDIA_KEYS:
                # единственный ключ-исключение: страница отдаётся по http://127.0.0.1,
                # а захват по умолчанию требует защищённого соединения
                prefs.setValue_forKey_(k != "mediaCaptureRequiresSecureConnection", k)
        except Exception as e:
            print(f"nakedlunch: WKPreferences не приняты ({e})", file=sys.stderr)
        orig_load(self, url)

    cocoa.BrowserView.load_url = load_url

    def _grant(self, webview_, origin, frame, type_, handler):
        handler(1)                                # WKPermissionDecisionGrant

    try:
        objc.classAddMethods(cocoa.BrowserView.BrowserDelegate, [objc.selector(
            _grant,
            selector=b"webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:",
            signature=b"v@:@@@q@?",
        )])
    except Exception as e:
        print(f"nakedlunch: делегат разрешения не добавлен ({e})", file=sys.stderr)


def main() -> int:
    if not ensure_build():
        _gui_error("Не удалось собрать интерфейс.\n\nПохоже, нет npm — поставь Node.js "
                   "или собери фронт руками:\n  cd interface/react-app && npm install && npm run build"
                   f"\n\nПодробности: ~/Library/Logs/nakedlunch.log")
        return 1

    # Сборка уже прошла, значит отпечаток считаем ПОСЛЕ неё: иначе свежий фронт
    # выглядел бы как старый ровно один запуск.
    stamp = source_stamp()
    other = read_instance()
    if other:
        if float(other.get("stamp") or 0) >= stamp:
            print("nakedlunch: уже запущен и свеж — поднимаю его окно", file=sys.stderr)
            activate(int(other["pid"]))
            return 0
        if other.get("recording"):
            # Единственный случай, когда апдейт ждёт: убить процесс посреди
            # записи значит порвать дубль, а его не восстановить.
            print("nakedlunch: запущенный экземпляр устарел, но идёт запись — не трогаю",
                  file=sys.stderr)
            activate(int(other["pid"]))
            _gui_error("Идёт запись фристайла — не перезапускаю.\n\nОбновления подхватятся, "
                       "когда закончишь запись и откроешь программу заново.",
                       title="nakedlunch обновлён")
            return 0
        print("nakedlunch: запущенный экземпляр устарел — перезапускаю с обновлениями",
              file=sys.stderr)
        stop_pids([int(other.get("pid") or 0), int(other.get("server_pid") or 0)])
    else:
        # Записи нет, но процессы могут быть: аварийное завершение, запуск из
        # терминала, обновление с версии без регистрации. Гасим — иначе рядом со
        # старым окном встало бы второе, и оба писали бы в один корпус.
        strays = stray_pids()
        if strays:
            print(f"nakedlunch: прежние процессы без записи {strays} — гашу", file=sys.stderr)
            stop_pids(strays)

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen([PY, SERVER, "--port", str(port), "--host", "127.0.0.1"],
                            cwd=str(HERE), env=child_env())

    def cleanup():
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        # Именно здесь, а не в atexit: закрытие окна уходит через os._exit(0)
        # (см. on_closed), и atexit тогда не отрабатывает — запись пережила бы
        # программу, и следующий запуск полминуты стучался бы в мёртвый порт.
        forget_instance()

    atexit.register(cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: sys.exit(0))
        except Exception:
            pass

    # Регистрируем экземпляр ТОЛЬКО когда сервер ответил: запись о нежившем
    # экземпляре заставила бы следующий запуск уважать пустое место.
    def register():
        write_instance(pid=os.getpid(), server_pid=proc.pid, port=port,
                       stamp=stamp, started=time.time(), recording=False)

    if webview is None:                       # без родного окна — старый путь
        if not wait_health(port, proc):
            print("nakedlunch: server did not come up in time", file=sys.stderr)
            _gui_error("Сервер не поднялся за отведённое время.\n\n"
                       "Подробности: ~/Library/Logs/nakedlunch.log")
            cleanup(); return 1
        register()
        print("nakedlunch: pywebview not installed; opening browser", file=sys.stderr)
        import webbrowser
        webbrowser.open(url)
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
        cleanup(); return 0

    def on_closed():
        # pywebview's start() is not reliably guaranteed to return when the
        # window closes (observed: launch.py stayed alive, server.py
        # orphaned, after clicking the close button). Kill the server the
        # moment the window actually closes and hard-exit the interpreter,
        # instead of trusting start() to fall through to `finally`.
        cleanup()
        os._exit(0)

    try:
        enable_media_capture()
        brand_app()
        api = ExportApi()
        # Окно появляется СРАЗУ, ещё до готовности сервера. Раньше оно ждало
        # wait_health, а холодный старт — 26.6 с (замерено: сервер поднимает
        # корпус, индексы и тезаурус). Всё это время после двойного клика не
        # происходило вообще ничего: ни окна, ни иконки в доке. Половина жалобы
        # «не открывается» — про эти секунды.
        window = webview.create_window("nakedlunch", html=SPLASH, width=980, height=820,
                                        min_size=(720, 560), js_api=api)
        api.window = window
        window.events.closed += on_closed

        def подняться():
            """Ждём сервер в фоне, окно уже на экране; готов — переезжаем на него."""
            if not wait_health(port, proc):
                print("nakedlunch: server did not come up in time", file=sys.stderr)
                try:
                    window.load_html(SPLASH_FAIL)
                except Exception:
                    _gui_error("Сервер не поднялся за отведённое время.\n\n"
                               "Подробности: ~/Library/Logs/nakedlunch.log")
                return
            register()
            window.load_url(url)

        webview.start(подняться)
    except Exception as e:
        print(f"nakedlunch: native window unavailable ({e}); opening browser", file=sys.stderr)
        import webbrowser
        if not wait_health(port, proc):
            _gui_error("Сервер не поднялся за отведённое время.\n\n"
                       "Подробности: ~/Library/Logs/nakedlunch.log")
            return 1
        register()
        webbrowser.open(url)
        try:
            proc.wait()
        except KeyboardInterrupt:
            pass
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
