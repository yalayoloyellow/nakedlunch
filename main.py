#!/usr/bin/env python3
# nakedlunch — точка входа собранного приложения (Раунд 60).
#
# ЗАЧЕМ ОНА ОТДЕЛЬНО. Из исходников каждая часть программы запускается своим
# файлом: `launch.py` открывает окно, `api/server.py` считает, сборщики в
# `tools/` пекут таблицы. В собранном приложении питона нет и этих файлов рядом
# тоже — есть один исполняемый файл. Поэтому он зовёт САМ СЕБЯ, а первым
# аргументом идёт имя роли; разводит роли этот модуль.
#
# Имена ролей — те же, что в core/дочерний.py, и это не совпадение: там они
# составляются, здесь исполняются. Разъехаться им нельзя, поэтому список один.
#
# Без аргументов — окно. Так двойной клик по приложению делает то, чего от него
# ждут, а не показывает справку.

import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent
for каталог in ("core", "api", "tools"):
    путь = str(КОРЕНЬ / каталог)
    if путь not in sys.path:
        sys.path.insert(0, путь)


def _окно() -> int:
    import launch
    return launch.main()


def _сервер() -> int:
    # server.py разбирает свои --port/--host сам; убираем имя роли, чтобы его
    # разбор видел ровно то, что видел бы при прямом запуске.
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    import server
    server.main()
    return 0


def _ударения() -> int:
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    import build_nl_rhyme
    return build_nl_rhyme.main()


def _индекс() -> int:
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    import build_nl_index
    return build_nl_index.check() if "--check" in sys.argv else build_nl_index.build()


РОЛИ = {"окно": _окно, "сервер": _сервер, "ударения": _ударения, "индекс": _индекс}


def main() -> int:
    import пути
    пути.подготовить()
    роль = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "окно"
    делать = РОЛИ.get(роль)
    if делать is None:
        print(f"nakedlunch: неизвестная роль {роль!r}; известны: "
              + ", ".join(РОЛИ), file=sys.stderr)
        return 2
    return делать() or 0


if __name__ == "__main__":
    # multiprocessing в собранном приложении обязан знать, что он ребёнок, —
    # иначе на Windows каждый дочерний процесс заново открывал бы окно.
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()
    raise SystemExit(main())
