# -*- mode: python ; coding: utf-8 -*-
# nakedlunch — сборка одного приложения (Раунд 60).
#
# ПРИНЦИП: скачал, запустил, работает. Ни терминала, ни докачки, ни установки
# питона. Всё, что нужно программе, лежит внутри — включая акцентуатор, без
# которого залитая книга осталась бы без рифмо-ключей.
#
# ЧЕГО ВНУТРИ НЕТ И ПОЧЕМУ:
#   · корпус, кэш ударений, индекс — это работа пользователя и его книги;
#     программа печёт их сама, у себя, после первой заливки;
#   · модель омографов ruaccent (351 МБ) и предсказатель ударности (114 МБ) —
#     код к ним не обращается ни разу, см. tools/build_nl_rhyme.акцентуатор;
#   · навек (51 МБ) — кладётся, только если лежит рядом: без него работает всё,
#     кроме семантики темы.
#
# СОБИРАЕТСЯ ONEDIR, А НЕ ONEFILE. Onefile каждый раз распаковывает себя во
# временную папку — это секунды на старте и лишняя копия на диске при каждом
# запуске, а программа стартует не мгновенно и без того. В macOS onedir всё
# равно прячется внутрь .app, в Windows и Linux едет папкой в архиве.

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
# ОТСУТСТВИЕ ТАБЛИЦЫ — ОТКАЗ СБОРКИ, А НЕ ТИХИЙ ПРОПУСК (Раунд 61).
#
# Прежде здесь стояло `if п.exists()`, и это стоило целого выпуска: на
# сборочной машине половины таблиц нет (они в .gitignore), спека молча собрала
# приложение без них, проверка запуска прошла — сервер поднимается и без
# словарей, — и людям уехала сборка, где тема не работает, а попап по слову
# пуст. Тихая деградация выглядит успехом ровно до первого пользователя.
#
# Теперь список обязателен целиком. Нет файла — сборка падает и говорит, какого
# именно и чем он делается.
ОБЯЗАТЕЛЬНЫЕ = {
    "forms.json":      "core/data, в репозитории",
    "lexicon.json":    "core/data, в репозитории",
    "stanza_forms.json": "core/data, в репозитории",
    "navec.tar":       "скачать: github.com/natasha/navec, "
                       "navec_hudlit_v1_12B_500K_300d_100q.tar (~51 МБ, MIT)",
    "rhyme_index.json": "собрать: python tools/build_rhyme_index.py (~4 мин)",
}
_нет = []
for имя, откуда in ОБЯЗАТЕЛЬНЫЕ.items():
    п = КОРЕНЬ / "core" / "data" / имя
    if п.exists():
        ДАННЫЕ.append((str(п), "core/data"))
    else:
        _нет.append(f"  core/data/{имя} — {откуда}")

# Тезаурус лежит в data/, а не в core/data: он собирается из сырья, которого в
# репозитории нет, поэтому сам файл держится в git по исключению (.gitignore).
_тезаурус = КОРЕНЬ / "data" / "thesaurus.json"
if _тезаурус.exists():
    ДАННЫЕ.append((str(_тезаурус), "core/data"))
else:
    _нет.append("  data/thesaurus.json — должен быть в репозитории "
                "(см. исключение в .gitignore)")

if _нет:
    raise SystemExit("не хватает входных таблиц, сборка была бы неполной:\n"
                     + "\n".join(_нет))

# --- акцентуатор: только то, что реально используется ------------------------
import ruaccent
РУА = Path(ruaccent.__file__).resolve().parent
for отн in ("dictionary/accents.json.gz", "dictionary/yo_words.json.gz"):
    п = РУА / отн
    if п.exists():
        ДАННЫЕ.append((str(п), f"ruaccent/{Path(отн).parent}"))
модель = РУА / "nn" / "nn_accent"
if модель.is_dir():
    ДАННЫЕ.append((str(модель), "ruaccent/nn/nn_accent"))

# --- данные чужих пакетов ---------------------------------------------------
for пакет in ("pymorphy3_dicts_ru", "wordfreq", "navec"):
    try:
        ДАННЫЕ += collect_data_files(пакет)
    except Exception:
        pass

СКРЫТЫЕ = ["server", "launch", "build_nl_rhyme", "build_nl_index", "пути", "дочерний"]
СКРЫТЫЕ += collect_submodules("pymorphy3")
СКРЫТЫЕ += ["onnxruntime", "ruaccent.char_tokenizer", "ruaccent.accent_model"]

# Тяжёлое и ненужное. torch не установлен вовсе, но если он появится в
# окружении сборки, PyInstaller утянет его целиком — два гигабайта за код,
# который не выполняется.
ЛИШНЕЕ = ["torch", "tensorflow", "flax", "jax", "matplotlib", "IPython",
          "pytest", "PyInstaller", "playwright", "scipy"]

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
    app = BUNDLE(
        coll,
        name="nakedlunch.app",
        icon=str(КОРЕНЬ / "interface" / "icon" / "nakedlunch.icns")
        if (КОРЕНЬ / "interface" / "icon" / "nakedlunch.icns").exists() else None,
        bundle_identifier="com.yala.nakedlunch",
        info_plist={
            "CFBundleName": "nakedlunch",
            "CFBundleDisplayName": "nakedlunch",
            "NSHighResolutionCapable": True,
            # Микрофон нужен фристайлу: без описания macOS убивает процесс
            # молча, и человек видит закрывшееся окно без единого слова.
            "NSMicrophoneUsageDescription": "Запись голоса во фристайле.",
            "NSCameraUsageDescription": "Захват окна при записи фристайла.",
        },
    )
