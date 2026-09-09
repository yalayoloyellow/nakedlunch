# nakedlunch — всё, что код импортирует в рантайме, объявлено в requirements.
#
# ЗАЧЕМ. `numpy` не был объявлен никогда: он приезжал прицепом с `navec`, и в
# самом requirements.txt про это было написано прямо — «ОДНА зависимость
# (numpy, и так транзитивный)». Когда попап по слову вырезали и navec ушёл,
# numpy остался нужен ядру — и свежая установка перестала запускаться вовсе,
# падая на первом же импорте. На машине разработчика этого не видно: там он
# давно стоит.
#
# Поймала это установка на чистое дерево, а не чтение. Сторож повторяет ту же
# мысль дешевле: спрашивает у кода, что он импортирует, и сверяет со списком.
#
# ЧЕГО СТОРОЖ НАМЕРЕННО НЕ ТРЕБУЕТ:
#   · пакеты сборки таблиц (ruaccent, huggingface_hub) — они нужны печкам, а
#     не программе, и в requirements описаны как необязательные;
#   · pyobjc (AppKit, Foundation) — launch.py зовёт их в try/except и живёт без
#     них: «не macOS/нет pyobjc — не беда»;
#   · werkzeug — приезжает с flask и своей строки не просит.
#
# Прогон: .venv/bin/python -m pytest tests/test_зависимости_объявлены.py -q

import ast
import re
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent

# Импорты, которые не обязаны быть в requirements, и почему — см. шапку.
НЕ_ТРЕБУЕМ = {
    "ruaccent", "huggingface_hub",     # только печки таблиц
    "AppKit", "Foundation", "objc",    # pyobjc: launch.py живёт без них
    "werkzeug",                        # приезжает с flask
    "pytest",                          # тесты, не программа
}

# Имя пакета в requirements и имя модуля при импорте расходятся.
ИМЕНА = {"pymorphy3_dicts_ru": "pymorphy3-dicts-ru"}


def объявлено() -> set[str]:
    """Пакеты из requirements.txt, без версий и комментариев."""
    имена = set()
    for строка in (КОРЕНЬ / "requirements.txt").read_text(encoding="utf-8").splitlines():
        строка = строка.split("#")[0].strip()
        if not строка:
            continue
        имена.add(re.split(r"[<>=!~\[]", строка)[0].strip().lower())
    return имена


def импортируется() -> set[str]:
    """Модули верхнего уровня, которые код зовёт в рантайме."""
    свои = {p.stem for к in ("core", "api", "tools")
            for p in (КОРЕНЬ / к).rglob("*.py")} | {"nlsrc", "core"}
    стд = set(sys.stdlib_module_names)
    найдено = set()
    for к in ("core", "api"):                    # tools — печки, не рантайм
        for f in (КОРЕНЬ / к).rglob("*.py"):
            try:
                дерево = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for у in ast.walk(дерево):
                if isinstance(у, ast.Import):
                    найдено |= {a.name.split(".")[0] for a in у.names}
                elif isinstance(у, ast.ImportFrom) and у.level == 0 and у.module:
                    найдено.add(у.module.split(".")[0])
    return {m for m in найдено
            if m not in свои and m not in стд and not m.startswith("_")}


def test_каждый_импорт_ядра_объявлен():
    """Не объявлен — значит свежая установка не запустится."""
    есть = объявлено()
    беда = []
    for м in sorted(импортируется()):
        if м in НЕ_ТРЕБУЕМ:
            continue
        имя = ИМЕНА.get(м, м).lower()
        if имя not in есть:
            беда.append(м)
    assert not беда, (
        f"ядро импортирует {беда}, а в requirements.txt их нет — свежая "
        f"установка упадёт на первом же импорте, и увидит это только тот, "
        f"кто ставит с нуля")


def test_numpy_именно_объявлен():
    """Отдельно и по имени: ровно он и пропал, когда ушёл navec."""
    assert "numpy" in объявлено(), (
        "numpy не объявлен. Он нужен колоночному индексу и раньше приезжал "
        "прицепом с navec, которого больше нет")


def test_сторож_видит_хоть_что_то():
    """Пустой разбор дал бы зелёный тест ни о чём."""
    м = импортируется()
    assert len(м) >= 3, f"разбор импортов почти ничего не нашёл: {м}"
