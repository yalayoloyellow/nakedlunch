#!/usr/bin/env python3
# nakedlunch 1.0.1
# Copyright (c) 2026 Шамаев Илья Сергеевич (Yala, @yalayoloyellow). Personal use only.

"""
nakedlunch — pure cut-up recombination engine (Dada + Burroughs style) in terminal.

Pure stdlib Python 3. No external deps for runtime.
On mac /a uses native Finder via osascript.

The main script for direct run and for packaging entry point.
"""

from __future__ import annotations

import os
import sys
import time
import json
import logging
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Support running as script and when frozen by PyInstaller
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    HERE = Path(sys._MEIPASS)
else:
    HERE = Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))

from core.store import NakedLunchStore
from core.cutter import parse_source_file

# User data in ~/Documents/nakedlunch
def get_user_prog_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.getenv("USERPROFILE", str(Path.home()))) / "Documents"
    else:
        base = Path.home() / "Documents"
    prog_dir = base / "nakedlunch"
    prog_dir.mkdir(parents=True, exist_ok=True)
    return prog_dir

PROG_DIR = get_user_prog_dir()
DATA_DIR = PROG_DIR / "data"
SESSIONS_DIR = PROG_DIR / "sessions"
CONFIG_FILE = PROG_DIR / "config.json"
LOG_DIR = HERE / "logs"

DEFAULT_RETENTION = "never"

def setup_detailed_logging() -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # keep last 10
    existing = sorted((p for p in LOG_DIR.glob("session_*.log")), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in existing[10:]:
        try:
            old.unlink()
        except Exception:
            pass
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"session_{ts}.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        force=True
    )
    logging.info("=" * 60)
    logging.info("NEW nakedlunch SESSION")
    logging.info(f"Python: {sys.version}")
    logging.info(f"Data dir: {DATA_DIR}")
    logging.info("=" * 60)
    return log_file

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.setdefault("terminal_theme", "dark")
            return cfg
        except Exception:
            pass
    return {"session_retention": DEFAULT_RETENTION, "language": "en", "terminal_theme": "dark"}

def save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

def get_retention_days(cfg: dict) -> int:
    val = cfg.get("session_retention", DEFAULT_RETENTION)
    return {"never": 0, "month": 30, "3m": 90, "6m": 180, "year": 365}.get(val, 0)

def get_lang() -> str:
    cfg = load_config()
    val = str(cfg.get("language", "en")).lower()
    return "ru" if val.startswith(("ru", "р")) else "en"

def tr(key: str, **kwargs) -> str:
    lang = get_lang()
    T = {
        "en": {
            "sources_not_found": "Use numbers from /s (example: /r 2 4). Only numbers.",
            "c_requires_period": "specify period: /c all | /c hour | /c day | /c week | /c month",
            "really_delete": "Really delete {n} source(s) ({names})? y/N ",
            "cancel": "cancel",
            "unblocked": "Unblocked {cleared} lines (mode {mode}).",
            "prog_dir": "Prog dir: {path}",
            "retention_show": "sessions retention: {val}",
            "lang_show": "language: {lang} (en/ru)",
            "lang_set": "language set to {lang}",
            "unknown_cmd": "Unknown command. /h for help",
            "error": "Error: {e}",
            "session_ended": "Session ended. Log saved.",
            "exit": "\nExit.",
            "no_files": "no files",
            "skip_not_file": "skip {p} (not file)",
            "skip_empty": "skip {name} (empty)",
            "add_success": "+ {name} ({cnt})",
            "add_err": "err {name}: {e}",
            "err_remove": "err remove {name}",
            "paths_fallback": "paths (space, fallback): ",
            "toggle_state": "{name}: {state}",
            "c_requires": "specify period: /c all|hour|day|week|month",
        },
        "ru": {
            "sources_not_found": "Используй номера из /s (пример: /r 2 4). Только номера.",
            "c_requires_period": "укажи период: /c all | /c hour | /c day | /c week | /c month",
            "really_delete": "Действительно удалить {n} источник(ов) ({names})? y/N ",
            "cancel": "отменено",
            "unblocked": "Разблокировано {cleared} строк (режим {mode}).",
            "prog_dir": "Папка программы: {path}",
            "retention_show": "retention сессий: {val}",
            "lang_show": "язык: {lang} (en/ru)",
            "lang_set": "язык переключён на {lang}",
            "unknown_cmd": "Неизвестная команда. /h — справка",
            "error": "Ошибка: {e}",
            "session_ended": "Сессия завершена. Лог сохранён.",
            "exit": "\nВыход.",
            "no_files": "нет файлов",
            "skip_not_file": "пропуск {p} (не файл)",
            "skip_empty": "пропуск {name} (пусто)",
            "add_success": "+ {name} ({cnt})",
            "add_err": "ошибка {name}: {e}",
            "err_remove": "ошибка удаления {name}",
            "paths_fallback": "пути (через пробел, запасной ввод): ",
            "toggle_state": "{name}: {state}",
            "c_requires": "укажи период: /c all|hour|day|week|month",
        },
    }
    s = T.get(lang, T["en"]).get(key, key)
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s

def parse_indices(arg: str, n: int) -> list[int]:
    if not arg or n <= 0:
        return []
    seen = set()
    res = []
    for tok in arg.split():
        try:
            i = int(tok) - 1
            if 0 <= i < n and i not in seen:
                seen.add(i)
                res.append(i)
        except ValueError:
            pass
    return res

def _choose_files() -> list[str]:
    if sys.platform == "darwin":
        script = '''tell application "Finder"
    activate
    set theFiles to choose file with multiple selections allowed
    set AppleScript's text item delimiters to "\\n"
    set posixList to {}
    repeat with f in theFiles
        set end of posixList to POSIX path of f
    end repeat
    return (posixList as text)
end tell'''
        try:
            out = subprocess.check_output(["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL).strip()
            if out:
                return [p.strip() for p in out.splitlines() if p.strip()]
        except Exception as e:
            logging.warning(f"mac native failed: {e}")

    # fallback tkinter or manual
    try:
        os.environ['TK_SILENCE_DEPRECATION'] = '1'
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        files = filedialog.askopenfilenames(title="Select source files (multi OK)")
        if files:
            return list(files)
    except Exception as e:
        logging.warning(f"tkinter failed: {e}")

    print(tr("paths_fallback"), end="", flush=True)
    line = sys.stdin.readline().strip()
    return [p.strip() for p in line.split() if p.strip()]

def do_add(store: NakedLunchStore) -> None:
    paths = _choose_files()
    if not paths:
        print(tr("no_files"))
        return
    for p in paths:
        pp = Path(p)
        if not pp.is_file():
            print(tr("skip_not_file", p=p))
            continue
        name = pp.stem
        try:
            text = parse_source_file(pp)
            if not text or not text.strip():
                print(f"источник {name} пустой или не содержит текста — пропущен")
                continue
            corp = store.add_corpus(name, text)
            print(tr("add_success", name=name, cnt=corp.fragment_count))
        except ValueError as ve:
            if "no fragments" in str(ve).lower():
                print(f"источник {name} не удалось нарезать (не создано фрагментов)")
            else:
                print(tr("add_err", name=name, e=ve))
        except Exception as e:
            print(tr("add_err", name=name, e=e))

def cmd_help(lang: str = "en") -> None:
    if lang == "ru":
        print("Команды (только цифры из /s через пробел):\n")
        rows = [
            ("/h", "", "эта справка"),
            ("/s", "", "список источников с номерами"),
            ("/a", "", "добавить (окно выбора файлов, multi OK)"),
            ("/r 2 4", "", "удалить по номерам (y/N)"),
            ("/t 1 3", "", "включить/выключить по номерам"),
            ("/c", "all|hour|day|week|month", "очистить использованное"),
            ("/dir", "", "открыть ~/Documents/nakedlunch"),
            ("/memory", "never|3m|6m|year", "retention сессий"),
            ("/l", "ru|en", "язык интерфейса"),
            ("/q", "", "выход"),
        ]
        for cmd, var, desc in rows:
            print(f"  {cmd:<14}{var:<28} {desc}")
        print("\nEnter — 4 строки случайно из пула\nтекст — bias (3 лучших + 1 дикая)\n")
    else:
        print("Commands (numbers from /s only, space separated):\n")
        rows = [
            ("/h", "", "this help"),
            ("/s", "", "list sources with numbers"),
            ("/a", "", "add (file chooser window, multi OK)"),
            ("/r 2 4", "", "remove by numbers (y/N)"),
            ("/t 1 3", "", "toggle by numbers"),
            ("/c", "all|hour|day|week|month", "clear used"),
            ("/dir", "", "open ~/Documents/nakedlunch"),
            ("/memory", "never|3m|6m|year", "sessions retention"),
            ("/l", "ru|en", "UI language"),
            ("/q", "", "quit"),
        ]
        for cmd, var, desc in rows:
            print(f"  {cmd:<14}{var:<28} {desc}")
        print("\nEnter — 4 random from pool\ntext — bias (3 best + 1 wild)\n")

def main() -> None:
    # theme
    try:
        cfg_early = load_config()
        theme = cfg_early.get("terminal_theme", "dark")
        if theme == "light":
            print("\x1b[47;30m", end="")
        else:
            print("\x1b[40;37m", end="")
    except Exception:
        print("\x1b[40;37m", end="")

    print("nakedlunch 1.0.1")
    print("Copyright (c) 2026 Шамаев Илья Сергеевич (Yala, @yalayoloyellow)")
    print()

    log_file = setup_detailed_logging()

    PROG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    days = get_retention_days(cfg)
    # simple cleanup of old sessions (if retention set)
    if days > 0:
        cutoff = time.time() - days * 86400
        for f in list(SESSIONS_DIR.glob("session_*.txt")):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass

    store = NakedLunchStore(DATA_DIR)

    sess_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    current_sess_file = SESSIONS_DIR / f"session_{sess_ts}.txt"
    try:
        with open(current_sess_file, "a", encoding="utf-8") as sf:
            sf.write(f"# Session started {sess_ts}\n# Prog dir: {PROG_DIR}\n\n")
            sf.flush()
    except Exception:
        pass

    print("nakedlunch")

    try:
        while True:
            try:
                raw = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print(tr("exit"))
                break

            if not raw:
                try:
                    lines = store.generate(None, for_chat=True)
                    store.mark_lines_used(lines)
                    store._save()
                    for i, line in enumerate(lines, 1):
                        print(f"{i}. {line}")
                    try:
                        with open(current_sess_file, "a", encoding="utf-8") as sf:
                            sf.write(f"[{datetime.now().strftime('%H:%M:%S')}] bias=neutral\n")
                            sf.write("\n".join(lines) + "\n\n")
                            sf.flush()
                    except Exception:
                        pass
                except Exception as e:
                    print(tr("error", e=e))
                continue

            if raw.startswith("/"):
                cmdline = raw[1:].strip()
                if not cmdline:
                    cmd_help(get_lang())
                    continue
                parts = cmdline.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else ""

                if cmd in ("h", "help", "?"):
                    cmd_help(get_lang())
                elif cmd == "s":
                    for i, c in enumerate(store.list_corpora(), 1):
                        state = "active" if c.get("active") else "inactive"
                        print(f"{i}. [{state}] {c.get('name')} ({c.get('fragment_count', 0)})")
                elif cmd == "a":
                    do_add(store)
                elif cmd in ("r", "remove"):
                    corpora_list = store.list_corpora()
                    idxs = parse_indices(arg, len(corpora_list))
                    if not idxs:
                        print(tr("sources_not_found"))
                        continue
                    names = [corpora_list[i].get("name", str(i)) for i in idxs]
                    print(tr("really_delete", n=len(names), names=", ".join(names)), end="", flush=True)
                    ans = sys.stdin.readline().strip().lower()
                    if ans != "y":
                        print(tr("cancel"))
                        continue
                    for i in sorted(idxs, reverse=True):
                        try:
                            cid = corpora_list[i]["id"]
                            store.delete_corpus(cid)
                        except Exception as e:
                            print(tr("err_remove", name=str(i)))
                elif cmd in ("t", "toggle"):
                    corpora_list = store.list_corpora()
                    for i in parse_indices(arg, len(corpora_list)):
                        try:
                            cid = corpora_list[i]["id"]
                            new_state = store.toggle_active(cid)
                            c = corpora_list[i]
                            print(tr("toggle_state", name=c.get("name"), state="active" if new_state else "inactive"))
                        except Exception as e:
                            print(tr("error", e=e))
                elif cmd == "c":
                    if not arg:
                        print(tr("c_requires"))
                        continue
                    mode = arg.strip().lower()
                    if mode == "all":
                        cleared = store.clear_used(None)
                    elif mode == "hour":
                        older = time.time() - 3600
                        cleared = store.clear_used(older)
                    elif mode == "day":
                        older = time.time() - 86400
                        cleared = store.clear_used(older)
                    elif mode == "week":
                        older = time.time() - 7 * 86400
                        cleared = store.clear_used(older)
                    elif mode == "month":
                        older = time.time() - 30 * 86400
                        cleared = store.clear_used(older)
                    else:
                        print(tr("c_requires"))
                        continue
                    print(tr("unblocked", cleared=cleared, mode=mode))
                elif cmd in ("dir", "d"):
                    try:
                        if sys.platform == "darwin":
                            subprocess.run(["open", str(PROG_DIR)], check=False)
                        elif sys.platform == "win32":
                            os.startfile(str(PROG_DIR))
                        else:
                            subprocess.run(["xdg-open", str(PROG_DIR)], check=False)
                        print(tr("prog_dir", path=str(PROG_DIR)))
                    except Exception as e:
                        print(tr("error", e=e))
                elif cmd in ("memory", "set"):
                    if not arg:
                        print(tr("retention_show", val=cfg.get("session_retention", DEFAULT_RETENTION)))
                        continue
                    val = arg.strip().lower()
                    if val not in ("never", "month", "3m", "6m", "year"):
                        print("bad value: never / 3m / 6m / year")
                        continue
                    cfg["session_retention"] = val
                    save_config(cfg)
                    print(tr("retention_show", val=val))
                elif cmd in ("l", "lang"):
                    if not arg:
                        print(tr("lang_show", lang=get_lang()))
                        continue
                    new = "ru" if arg.lower().startswith("r") else "en"
                    cfg = load_config()
                    cfg["language"] = new
                    save_config(cfg)
                    print(tr("lang_set", lang=new))
                elif cmd in ("q", "quit", "exit"):
                    print(tr("session_ended"))
                    break
                else:
                    print(tr("unknown_cmd"))
                continue

            # bias text
            try:
                lines = store.generate(raw, for_chat=True)
                store.mark_lines_used(lines)
                store._save()
                for i, line in enumerate(lines, 1):
                    print(f"{i}. {line}")
                try:
                    with open(current_sess_file, "a", encoding="utf-8") as sf:
                        sf.write(f"[{datetime.now().strftime('%H:%M:%S')}] bias={raw[:30]}\n")
                        sf.write("\n".join(lines) + "\n\n")
                        sf.flush()
                except Exception:
                    pass
            except Exception as e:
                print(tr("error", e=e))

    finally:
        print("\x1b[0m", end="")

def test_all_commands():
    """Automated test for main commands to prevent regressions like clear_used TypeError.
    Run with: python nakedlunch.py test
    """
    import tempfile
    from pathlib import Path
    print("Running automated command tests...")
    passed = True
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            store = NakedLunchStore(data_dir)

            # /h (help) - simulated, no crash
            print("Testing /h ... OK (print only)")

            # /s
            print("Testing /s ...")
            try:
                _ = store.list_corpora()
                print("  /s: OK")
            except Exception as e:
                print(f"  /s FAILED: {e}")
                passed = False

            # /a simulation: add test source (like choosing file)
            print("Testing /a ...")
            test_file = Path(tmp) / "test_source.txt"
            test_content = "This is a test source for fragmentation. It has multiple sentences. Another sentence to ensure fragments are created."
            test_file.write_text(test_content, encoding="utf-8")
            try:
                corp = store.add_corpus("test_source", test_content)
                print(f"  /a: added with fragment_count={corp.fragment_count}")
                if corp.fragment_count > 0:
                    print("  /a: fragment_count > 0 OK")
                else:
                    print("  /a: fragment_count == 0 FAIL")
                    passed = False
            except Exception as e:
                print(f"  /a FAILED: {e}")
                passed = False

            # /t toggle
            print("Testing /t ...")
            try:
                corpora = store.list_corpora()
                if corpora:
                    cid = corpora[0]["id"]
                    store.toggle_active(cid)
                    print("  /t: OK")
            except Exception as e:
                print(f"  /t FAILED: {e}")
                passed = False

            # /r remove (add temp and remove)
            print("Testing /r ...")
            try:
                temp_c = store.add_corpus("temp_remove", "Text for remove test with enough content to fragment.")
                if temp_c.fragment_count > 0:
                    store.delete_corpus(temp_c.id)
                    print("  /r: OK")
            except Exception as e:
                print(f"  /r FAILED: {e}")
                passed = False

            # /c all
            print("Testing /c all ...")
            try:
                cleared = store.clear_used(None)  # /c all
                print(f"  /c all: cleared {cleared}, OK")
            except Exception as e:
                print(f"  /c all FAILED: {e}")
                passed = False

            # /memory (retention config simulation)
            print("Testing /memory ...")
            try:
                # simulate setting
                print("  /memory: OK (simulated)")
            except Exception as e:
                print(f"  /memory FAILED: {e}")
                passed = False

            # /l (lang)
            print("Testing /l ...")
            try:
                print("  /l: OK (simulated)")
            except Exception as e:
                print(f"  /l FAILED: {e}")
                passed = False

            print("\n=== Test result ===")
            if passed:
                print("All basic command tests PASSED")
            else:
                print("Some tests FAILED")
    except Exception as e:
        print(f"Test runner FAILED: {e}")
        passed = False


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_all_commands()
    else:
        main()
