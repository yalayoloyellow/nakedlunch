# -*- mode: python ; coding: utf-8 -*-
# nakedlunch — переносимая сборка одного приложения.
#
# Внутри только код, собранный интерфейс и неизменяемые рантайм-таблицы.
# Корпус, испечённый индекс, кэш ударений, история, настройки и Telegram-токен
# намеренно живут ВНЕ бандла: на новой машине они появляются в её пользовательских
# каталогах, а на старой не могут случайно уехать в релиз.
#
# СОБИРАЕТСЯ ONEDIR, А НЕ ONEFILE. Onefile каждый раз распаковывает себя во
# временную папку — это секунды на старте и лишняя копия на диске при каждом
# запуске, а программа стартует не мгновенно и без того. В macOS onedir всё
# равно прячется внутрь .app, в Windows и Linux едет папкой в архиве.

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

КОРЕНЬ = Path(SPECPATH).resolve()
ДАННЫЕ = []

# --- фронтенд: собранный интерфейс ------------------------------------------
дист = КОРЕНЬ / "interface" / "react-app" / "dist"
if not дист.is_dir():
    raise SystemExit("нет interface/react-app/dist — собери фронт: npm run build")
ДАННЫЕ.append((str(дист), "interface/react-app/dist"))

# --- входные таблицы --------------------------------------------------------
# Отсутствующая таблица — отказ сборки. Единственная таблица формы хранится
# в репозитории; данные пользователя сюда не относятся и не добавляются.
ОБЯЗАТЕЛЬНЫЕ = {
    "stanza_forms.json": "core/data, в репозитории",
}
_нет = []
for имя, откуда in ОБЯЗАТЕЛЬНЫЕ.items():
    п = КОРЕНЬ / "core" / "data" / имя
    if п.exists():
        ДАННЫЕ.append((str(п), "core/data"))
    else:
        _нет.append(f"  core/data/{имя} — {откуда}")

if _нет:
    raise SystemExit("не хватает входных таблиц, сборка была бы неполной:\n"
                     + "\n".join(_нет))

# --- акцентуатор -------------------------------------------------------------
# Он нужен не только печке корпуса: после автоматического сдвига строки им
# перепроверяются включённые звуковые ворота. Поэтому все три ресурса — часть
# рантайма, и их отсутствие останавливает сборку до отправки пользователю.
import ruaccent
РУА = Path(ruaccent.__file__).resolve().parent
for отн in ("dictionary/accents.json.gz", "dictionary/yo_words.json.gz"):
    п = РУА / отн
    if not п.is_file():
        _нет.append(f"  ruaccent/{отн} — запусти tools/скачать_акцентуатор.py")
    else:
        ДАННЫЕ.append((str(п), f"ruaccent/{Path(отн).parent}"))
модель = РУА / "nn" / "nn_accent"
if not (модель / "model.onnx").is_file():
    _нет.append("  ruaccent/nn/nn_accent/model.onnx — "
                "запусти tools/скачать_акцентуатор.py")
else:
    ДАННЫЕ.append((str(модель), "ruaccent/nn/nn_accent"))

if _нет:
    raise SystemExit("не хватает рантайм-ресурсов, сборка была бы неполной:\n"
                     + "\n".join(_нет))

# --- данные чужих пакетов ---------------------------------------------------
# ТИХИЙ ПРОПУСК ЗДЕСЬ — ТА ЖЕ ОШИБКА, ЧТО СТОИЛА ВЫПУСКА ВЫШЕ (волна 0.4).
# Здесь стоял голый `except: pass` — ровно приём, который осуждает шапка этого
# же файла. Сборка выходила «успешной» со сломанным словарём морфологии, и
# видно это становилось только у пользователя.
#
# Сколько файлов даёт каждый пакет — ЗАМЕРЕНО (2026-08-14, это окружение), а не
# предположено: иначе порог «не пусто» был бы такой же догадкой.
ЧУЖИЕ = {
    "pymorphy3_dicts_ru": ("словарь морфологии (11 файлов): без него не "
                           "лемматизируется ни одна строка"),
    "wordfreq": ("частоты слов (67 файлов): на них стоит вся ось «Банальность» "
                 "и половина ворот отбора"),
}
for пакет, зачем in ЧУЖИЕ.items():
    try:
        _файлы = collect_data_files(пакет)
    except Exception as e:
        raise SystemExit(f"не собрать данные пакета {пакет} — {зачем}\n  причина: {e}")
    if not _файлы:
        raise SystemExit(f"пакет {пакет} не дал ни одного файла данных — {зачем}\n"
                         f"  проверь, что он установлен целиком: pip show {пакет}")
    ДАННЫЕ += _файлы
# Часть импортов живёт за динамической развилкой: роль бандла, мост Telegram,
# акцентуатор и платформа pywebview. Явный список не даёт PyInstaller выкинуть
# их лишь потому, что прямого `import` на верхнем уровне нет.
СКРЫТЫЕ = ["server", "launch", "build_nl_rhyme", "build_nl_index", "_accent",
           "пути", "дочерний", "телеграм"]
СКРЫТЫЕ += collect_submodules("pymorphy3")
# pywebview выбирает backend динамически. Брать все его подмодули нельзя:
# Android и чужие системные библиотеки тогда попадают в анализ macOS/Windows
# и дают ложные предупреждения. В бандл идёт ровно то, что может выбрать его
# собственная развилка на целевой платформе.
if sys.platform == "darwin":
    СКРЫТЫЕ += ["webview.platforms.cocoa"]
elif sys.platform == "win32":
    СКРЫТЫЕ += ["webview.platforms.winforms", "webview.platforms.edgechromium",
                "webview.platforms.mshtml", "webview.platforms.win32"]
else:
    СКРЫТЫЕ += ["webview.platforms.gtk", "webview.platforms.qt"]
СКРЫТЫЕ += ["onnxruntime", "ruaccent.char_tokenizer", "ruaccent.accent_model"]

# Тяжёлое и ненужное. torch не установлен вовсе, но если он появится в
# окружении сборки, PyInstaller утянет его целиком — два гигабайта за код,
# который не выполняется.
ЛИШНЕЕ = ["torch", "tensorflow", "flax", "jax", "matplotlib", "IPython",
          "pytest", "PyInstaller", "playwright", "scipy"]
# guilib.py перечисляет backend'ы всех ОС в функциях-ветках, и статический
# анализ честно находит их все. В переносимом пакете это не преимущество, а
# чужие двоичные зависимости и ложные предупреждения. Оставляем ровно
# backend'ы, достижимые на платформе данного пакета; при отсутствии системной
# библиотеки launch.py всё равно честно открывает локальный интерфейс в браузере.
if sys.platform == "darwin":
    ЛИШНЕЕ += ["webview.platforms.android", "webview.platforms.cef",
               "webview.platforms.edgechromium", "webview.platforms.gtk",
               "webview.platforms.mshtml", "webview.platforms.qt",
               "webview.platforms.win32", "webview.platforms.winforms"]
elif sys.platform == "win32":
    ЛИШНЕЕ += ["webview.platforms.android", "webview.platforms.cef",
               "webview.platforms.cocoa", "webview.platforms.gtk",
               "webview.platforms.qt"]
else:
    ЛИШНЕЕ += ["webview.platforms.android", "webview.platforms.cef",
               "webview.platforms.cocoa", "webview.platforms.edgechromium",
               "webview.platforms.mshtml", "webview.platforms.win32",
               "webview.platforms.winforms"]

a = Analysis(
    ["main.py"],
    pathex=[str(КОРЕНЬ / "core"), str(КОРЕНЬ / "api"), str(КОРЕНЬ / "tools")],
    binaries=[],
    datas=ДАННЫЕ,
    hiddenimports=СКРЫТЫЕ,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=ЛИШНЕЕ,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="nakedlunch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="nakedlunch",
)

if sys.platform == "darwin":
    ВЕРСИЯ = os.environ.get("NAKEDLUNCH_VERSION", "development").strip() or "development"
    app = BUNDLE(
        coll,
        name="nakedlunch.app",
        icon=str(КОРЕНЬ / "interface" / "icon" / "nakedlunch.icns")
        if (КОРЕНЬ / "interface" / "icon" / "nakedlunch.icns").exists() else None,
        bundle_identifier="com.yala.nakedlunch",
        info_plist={
            "CFBundleName": "nakedlunch",
            "CFBundleDisplayName": "nakedlunch",
            "CFBundleShortVersionString": ВЕРСИЯ,
            "CFBundleVersion": ВЕРСИЯ,
            "NSHighResolutionCapable": True,
            # Микрофон нужен фристайлу: без описания macOS убивает процесс
            # молча, и человек видит закрывшееся окно без единого слова.
            "NSMicrophoneUsageDescription": "Запись голоса во фристайле.",
            "NSCameraUsageDescription": "Захват окна при записи фристайла.",
        },
    )
