# Изоляция проверок одной переменной (Раунд 61).
#
# ЗАЧЕМ. `core/пути.py` обещает, что `NAKEDLUNCH_HOME` уводит программу от
# боевых данных. Обещание было ложным дважды: у переменной не нашлось ни одного
# вызывающего во всём дереве, а корень записи не покрывал ни корпус
# (`NAKEDLUNCH_DATA`), ни листы (`NAKEDLUNCH_VAULT`), ни записи
# (`NAKEDLUNCH_RECORDINGS`) — у каждого своя переменная. Живая проверка,
# доверившаяся документации, писала бы в настоящие тексты пользователя.
#
# Второе: пустая строка была неотличима от «не задано» и молча уводила в боевой
# путь. Поймано на себе — `ВРЕМ=...` в zsh не присвоилось (кириллическое имя),
# подстановка дала пустоту, проверка чуть не пошла по настоящему корпусу.
#
# Здесь оба свойства закреплены. Проверка идёт ОТДЕЛЬНЫМ ПРОЦЕССОМ: корни
# вычисляются при импорте, и в уже загруженном модуле переменную менять поздно.

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent

ПОКАЗАТЬ = """
import sys
sys.path.insert(0, {core!r})
import пути, nlbridge, sheets, recorder
print(пути.ЗАПИСЬ)
print(nlbridge.NAKEDLUNCH_DATA)
print(sheets._vault())
print(пути.хранилище("NAKEDLUNCH_RECORDINGS", "записи", recorder.DEFAULT_ROOT))
"""


def _прогон(среда: dict) -> subprocess.CompletedProcess:
    чистая = {k: v for k, v in os.environ.items()
              if not k.startswith("NAKEDLUNCH_")}
    чистая.update(среда)
    return subprocess.run(
        [sys.executable, "-c", ПОКАЗАТЬ.format(core=str(КОРЕНЬ / "core"))],
        env=чистая, capture_output=True, text=True, cwd=str(КОРЕНЬ), timeout=180)


def test_одна_переменная_уводит_все_хранилища(tmp_path):
    """NAKEDLUNCH_HOME в одиночку обязана увести ВСЁ: запись, корпус, листы,
    записи. Иначе обещание изоляции в документации — ложь, и живая проверка
    пишет в настоящие данные."""
    готово = _прогон({"NAKEDLUNCH_HOME": str(tmp_path)})
    assert готово.returncode == 0, готово.stderr[-800:]
    пути_вывода = [с for с in готово.stdout.splitlines() if с.strip()]
    assert len(пути_вывода) == 4, f"ожидались четыре пути, вышло: {пути_вывода}"
    снаружи = [п for п in пути_вывода if str(tmp_path) not in п]
    assert not снаружи, ("эти хранилища остались вне временной папки, то есть "
                         f"изоляция дырявая: {снаружи}")


def test_пустая_переменная_это_отказ(tmp_path):
    """Пустая строка — почти всегда осечка подстановки в оболочке. Молча уйти в
    боевой путь здесь опаснее, чем упасть."""
    for имя in ("NAKEDLUNCH_HOME", "NAKEDLUNCH_DATA",
                "NAKEDLUNCH_VAULT", "NAKEDLUNCH_RECORDINGS"):
        готово = _прогон({"NAKEDLUNCH_HOME": str(tmp_path), имя: "   "})
        assert готово.returncode != 0, (
            f"{имя} задана пустой строкой, а программа не упала — значит она "
            f"молча ушла бы к боевым данным")
        assert имя in готово.stderr, (
            f"отказ не назвал переменную {имя}: {готово.stderr[-300:]}")


def test_своя_переменная_главнее_общей(tmp_path):
    """Точечный увод одного хранилища обязан продолжать работать: NAKEDLUNCH_HOME
    задаёт общее правило, своя переменная — исключение из него."""
    особый = tmp_path / "особый-корпус"
    готово = _прогон({"NAKEDLUNCH_HOME": str(tmp_path),
                      "NAKEDLUNCH_DATA": str(особый)})
    assert готово.returncode == 0, готово.stderr[-800:]
    строки = [с for с in готово.stdout.splitlines() if с.strip()]
    assert str(особый) in строки[1], (
        f"своя переменная не перебила общую: {строки[1]}")
