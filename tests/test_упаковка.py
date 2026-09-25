# nakedlunch — СБОРКА ПАДАЕТ ГРОМКО, И РОЛИ СОЙДУТСЯ (Раунд 62, волна 0.4).
#
# ЧТО НАШЛА ОПИСЬ 2026-08-13.
#
# (а) `collect_data_files` для чужих пакетов был обёрнут в голый `except: pass`
# — ровно тот приём, который осуждает шапка этого же файла двадцатью строками
# выше. Сборка выходила «успешной» со сломанным словарём морфологии, и видно
# это становилось только у пользователя. Прошлый раз такая же тихая деградация
# на входных таблицах стоила целого выпуска.
#
# (б) Имена ролей живут в ТРЁХ местах: `main.РОЛИ` (что умеет запустить бандл),
# `дочерний.РОЛИ` (что код запускает отдельным процессом) и `hiddenimports`
# спеки (что PyInstaller обязан положить внутрь). Что они совпадают, не
# проверяет ничто, а расходятся они молча: роль есть, скрипта в бандле нет —
# и заливка книги падает у пользователя на чужой машине.
#
# Спека здесь ЧИТАЕТСЯ, а не исполняется: исполнить её вне PyInstaller нельзя
# (`SPECPATH` определяет он), а нужно нам содержимое, а не сборка.
#
# Прогон: .venv/bin/python -m pytest tests/test_упаковка.py -q

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

СПЕКА = (КОРЕНЬ / "nakedlunch.spec").read_text("utf-8")
ПЕРЕНОС = (КОРЕНЬ / "tools" / "перенос.sh").read_text("utf-8")
РЕЛИЗ = (КОРЕНЬ / ".github" / "workflows" / "build.yml").read_text("utf-8")


def _словарь_из(исходник: str, имя: str) -> dict:
    """Литерал словаря по имени переменной — читаем дерево, а не исполняем."""
    дерево = ast.parse(исходник)
    for узел in ast.walk(дерево):
        if (isinstance(узел, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == имя for t in узел.targets)
                and isinstance(узел.value, ast.Dict)):
            return {ast.literal_eval(k): None for k in узел.value.keys}
    raise AssertionError(f"в исходнике нет словаря {имя}")


# ------------------------------------------------ (а) сборка падает громко

def test_speka_ne_glotaet_oshibki_chuzhih_paketov():
    """ГЛАВНОЕ: `except: pass` вокруг сбора чужих данных вернуться не может."""
    хвост = СПЕКА[СПЕКА.index("данные чужих пакетов"):]
    хвост = хвост[:хвост.index("СКРЫТЫЕ")]
    # Комментарии выкидываем: они как раз ОБЪЯСНЯЮТ, чего здесь больше нет, и
    # первая версия этой проверки поймала собственное объяснение.
    хвост = "\n".join(с for с in хвост.splitlines() if not с.lstrip().startswith("#"))
    assert "pass" not in хвост, (
        "сбор данных чужих пакетов снова глотает ошибку — сборка выйдет "
        "рабочей со сломанным словарём")
    assert хвост.count("raise SystemExit") >= 2, (
        "нет отказа ни на ошибке сбора, ни на пустом результате")


def test_pustoy_paket_eto_otkaz_a_ne_uspeh():
    """Пакет может УСТАНОВИТЬСЯ и не дать ни одного файла данных — тогда
    исключения нет, а данных тоже нет. Раньше и это проходило молча."""
    хвост = СПЕКА[СПЕКА.index("данные чужих пакетов"):]
    assert re.search(r"if not _файлы", хвост), "пустой результат снова считается успехом"


@pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("PyInstaller") is None,
    reason="PyInstaller не установлен в окружении")
def test_obyazatelnye_pakety_dannye_dayut():
    """Замер, на котором стоит порог «не пусто»: оба пакета реально несут
    данные, значит требовать их — не выдумка."""
    from PyInstaller.utils.hooks import collect_data_files
    assert len(collect_data_files("pymorphy3_dicts_ru")) > 0
    assert len(collect_data_files("wordfreq")) > 0


def test_внутри_только_неизменяемая_таблица_а_не_данные_пользователя():
    """Релиз с чужим корпусом, историей или секретом — необратимая утечка."""
    assert set(_словарь_из(СПЕКА, "ОБЯЗАТЕЛЬНЫЕ")) == {"stanza_forms.json"}
    for запрещено in ("core/data/nl_addr", "core/data/nl_rhyme", "navec.tar",
                       "rhyme_index.json", "thesaurus.json", "telegram.json"):
        assert запрещено not in СПЕКА, (
            f"{запрещено} снова фигурирует в спеке: пользовательские или "
            "вырезанные данные могут попасть в переносимый релиз")


def test_акцентуатор_обязателен_и_полностью_кладётся():
    """Без него звуковые ворота ломаются не на старте, а при первой строке."""
    for ресурс in ("dictionary/accents.json.gz", "dictionary/yo_words.json.gz",
                   "nn/nn_accent/model.onnx"):
        assert ресурс in СПЕКА
    отрезок = СПЕКА[СПЕКА.index("акцентуатор"):СПЕКА.index("данные чужих пакетов")]
    assert "raise SystemExit" in отрезок, (
        "неполный акцентуатор снова может уехать в успешной сборке")


def test_динамические_модули_окна_и_акцентуатора_явно_учтены():
    """PyInstaller не видит динамическую загрузку платформы и печки сам.

    Собрать все backend'ы webview значит тащить Android и Windows в macOS
    (и получать ложные предупреждения о чужих системных библиотеках)."""
    assert 'collect_submodules("webview")' not in СПЕКА
    for backend in ("webview.platforms.cocoa", "webview.platforms.winforms",
                    "webview.platforms.edgechromium", "webview.platforms.mshtml",
                    "webview.platforms.win32", "webview.platforms.gtk",
                    "webview.platforms.qt"):
        assert f'"{backend}"' in СПЕКА
    assert '"_accent"' in СПЕКА


def test_пакет_не_тащит_backendы_чужой_платформы():
    """У pywebview есть статические импорты всех ОС, их надо явно вычесть."""
    хвост = СПЕКА[СПЕКА.index("ЛИШНЕЕ ="):СПЕКА.index("a = Analysis")]
    for backend in ("webview.platforms.android", "webview.platforms.cef",
                    "webview.platforms.cocoa", "webview.platforms.edgechromium",
                    "webview.platforms.gtk", "webview.platforms.mshtml",
                    "webview.platforms.qt", "webview.platforms.win32",
                    "webview.platforms.winforms"):
        assert f'"{backend}"' in хвост


def test_старый_перенос_не_увозит_секрет_или_живой_экземпляр():
    """Архив исходной установки остаётся полезным, но секретом не становится."""
    for имя in ("telegram.json", "telegram.json.lock", "instance.json"):
        assert f"--exclude='data/{имя}'" in ПЕРЕНОС, (
            f"tools/перенос.sh может увезти data/{имя} на другую машину")
    assert "Telegram-токен, его замок и запись живого окна не включены." in ПЕРЕНОС


def test_секрет_игнорируется_гитом_на_самом_деле():
    """Одной записи в .gitignore мало, если её отменит более позднее правило."""
    итог = subprocess.run(["git", "check-ignore", "-q", "data/telegram.json"],
                          cwd=КОРЕНЬ, capture_output=True)
    assert итог.returncode == 0, "data/telegram.json перестал игнорироваться Git"


def test_релизная_сборка_полна_и_проверяет_чистый_профиль():
    """Не дать CI тихо вернуться к старым печкам или архиву с личными данными."""
    for платформа in ("macos-15-intel", "macos-14", "windows-latest", "ubuntu-latest"):
        assert платформа in РЕЛИЗ
    for устарело in ("скачать_векторы.py", "build_rhyme_index.py", "/api/word/suggest"):
        assert устарело not in РЕЛИЗ
    assert РЕЛИЗ.index("tools/скачать_акцентуатор.py") < РЕЛИЗ.index("- name: тесты")
    for проверка in ("telegram.json", "Documents/nakedlunch/data",
                     "Application Support/nakedlunch", "APPDATA"):
        assert проверка in РЕЛИЗ, f"в релизной проверке пропал контракт: {проверка}"


# ------------------------------------------------------- (б) роли сходятся

def test_roli_soshlis_vo_vseh_tryoh_mestah():
    """ГЛАВНОЕ: то, что код запускает отдельным процессом, бандл обязан уметь
    запустить и обязан нести внутри."""
    import дочерний
    главные = _словарь_из((КОРЕНЬ / "main.py").read_text("utf-8"), "РОЛИ")

    лишние = set(дочерний.РОЛИ) - set(главные)
    assert not лишние, (
        f"код запускает роли, которых не знает main.py: {sorted(лишние)} — "
        "в бандле такой запуск падает «неизвестная роль»")

    скрытые = set(re.findall(r'"([^"]+)"', СПЕКА[СПЕКА.index("СКРЫТЫЕ = ["):
                                                 СПЕКА.index("СКРЫТЫЕ +=")]))
    for роль, путь in дочерний.РОЛИ.items():
        модуль = Path(путь).stem
        assert модуль in скрытые, (
            f"роль «{роль}» ведёт в {модуль}.py, а его нет в hiddenimports — "
            "в бандле роль не запустится, и видно это будет только у пользователя")


def test_skripty_roley_sushchestvuyut():
    """Путь роли — не строка, а файл. Переименовали скрипт — роль умерла."""
    import дочерний
    for роль, путь in дочерний.РОЛИ.items():
        assert Path(путь).exists(), f"роль «{роль}» ведёт в несуществующий {путь}"
