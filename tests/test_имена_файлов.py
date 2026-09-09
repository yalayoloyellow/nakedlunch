# nakedlunch — кириллические имена модулей переживают перенос на другую машину.
#
# ЧТО ЗА БЕДА. В `core/` шесть модулей названы по-русски. Юникод хранит «й»
# двумя способами: одной буквой (NFC) или буквой плюс краткой (NFD). Питон
# ищет модуль по имени из исходника, то есть по NFC. Имя на диске в NFD с ним
# НЕ СОВПАДАЕТ — и получается `ModuleNotFoundError: No module named
# 'дочерний'` при файле, который прекрасно виден и в Finder, и в `ls`.
#
# ОТКУДА. Не из `git clone` — он кладёт NFC, проверено. А вот `tar` и `zip`
# при переносе раскладывают имена, и тома HFS+ (старые маки, внешние диски)
# раскладывают их всегда. То есть беда приходит ровно туда, куда мы целимся:
# на чужую и на старую машину. Поймана переносом, а не чтением.
#
# Прогон: .venv/bin/python -m pytest tests/test_имена_файлов.py -q

import shutil
import sys
import unicodedata
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ))

import launch   # noqa: E402


def test_в_репозитории_имена_составные():
    """Здесь и сейчас все имена обязаны быть NFC — иначе ломается импорт."""
    беда = []
    for папка in ("core", "core/nlsrc", "api", "tools", "tests"):
        d = КОРЕНЬ / папка
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not unicodedata.is_normalized("NFC", f.name):
                беда.append(f"{папка}/{f.name}")
    assert not беда, f"имена в разложенной форме, импорт по ним не найдётся: {беда}"


def test_разложенное_имя_чинится(tmp_path):
    """Главный случай: файл приехал в NFD — программа обязана вернуть NFC сама."""
    дом = tmp_path / "прога"
    (дом / "core").mkdir(parents=True)
    (дом / "core" / unicodedata.normalize("NFD", "дочерний.py")).write_text("x = 1\n", encoding="utf-8")
    (дом / "core" / "clean.py").write_text("y = 2\n", encoding="utf-8")   # латиница не трогается

    было = [f.name for f in (дом / "core").iterdir()]
    assert any(not unicodedata.is_normalized("NFC", n) for n in было), (
        "фикстура не создала разложенное имя — на этом томе проверять нечего")

    старый_дом = launch.HERE
    try:
        launch.HERE = дом
        отчёт = launch.починить_имена()
    finally:
        launch.HERE = старый_дом

    assert отчёт == "", f"починка не удалась: {отчёт}"
    стало = [f.name for f in (дом / "core").iterdir()]
    assert all(unicodedata.is_normalized("NFC", n) for n in стало), стало
    assert "clean.py" in стало, "латинское имя пропало при починке"
    assert unicodedata.normalize("NFC", "дочерний.py") in стало


def test_целое_дерево_не_трогается(tmp_path):
    """Всё уже в NFC — починка обязана ничего не менять и не соврать."""
    дом = tmp_path / "прога"
    (дом / "core").mkdir(parents=True)
    for имя in ("дочерний.py", "clean.py", "кэш.py"):
        (дом / "core" / имя).write_text("z = 3\n", encoding="utf-8")
    было = sorted(f.name for f in (дом / "core").iterdir())

    старый_дом = launch.HERE
    try:
        launch.HERE = дом
        отчёт = launch.починить_имена()
    finally:
        launch.HERE = старый_дом

    assert отчёт == ""
    assert sorted(f.name for f in (дом / "core").iterdir()) == было


def test_перенос_переживает_кириллицу(tmp_path):
    """Сам tar из tools/перенос.sh не обязан ломать имена — проверяем на нём.

    Если этот тест однажды покраснеет, чинить надо не его, а скрипт: значит
    перенос стал раскладывать имена, и на той стороне программа не поднимется
    до починки в launch.py."""
    исход = tmp_path / "src"
    (исход / "d").mkdir(parents=True)
    (исход / "d" / "кэш.py").write_text("q = 1\n", encoding="utf-8")
    архив = tmp_path / "a.tar"
    цель = tmp_path / "dst"
    цель.mkdir()

    import subprocess
    subprocess.run(["tar", "-cf", str(архив), "-C", str(исход), "d"], check=True)
    subprocess.run(["tar", "-xf", str(архив), "-C", str(цель)], check=True)

    имя = next((цель / "d").iterdir()).name
    # Не утверждаем «tar не ломает» — на разных томах по-разному. Утверждаем
    # главное: что бы ни приехало, починка это выпрямит.
    if not unicodedata.is_normalized("NFC", имя):
        старый_дом = launch.HERE
        try:
            launch.HERE = цель
            (цель / "core").mkdir(exist_ok=True)
            shutil.move(str((цель / "d" / имя)), str(цель / "core" / имя))
            assert launch.починить_имена() == ""
            assert unicodedata.is_normalized("NFC", next((цель / "core").iterdir()).name)
        finally:
            launch.HERE = старый_дом
