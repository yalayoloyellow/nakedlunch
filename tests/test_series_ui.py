# nakedlunch — СЕРИЯ И ЛИСТЫ НА СТЫКЕ С ЧЕЛОВЕКОМ (Раунд 55).
#
# Как очередь серия работала и раньше. Ломалась она там, где пользователь забирает
# результат, и все три поломки — в этом файле:
#
#   1. Забрал понравившийся лист к себе — машина печатала замену. «Сделано»
#      считалось файлами в папке; теперь по сайдкару (см. test_series_run.py).
#   2. Серия нумерует листы трека по баллу в конце. Открытый в редакторе лист
#      при этом терял свой путь, и сохранение падало.
#   3. Корень серий удалялся, высыпая все названия поверх собственных текстов
#      пользователя, — при том что в коде было написано, что он защищён.
#
# Прогон: .venv/bin/python -m pytest tests/test_series_ui.py -q

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

import sheets  # noqa: E402

ЛИСТЫ = КОРЕНЬ / "interface" / "react-app" / "src" / "nl" / "methods.sheets.js"
СЕРИЯ_JS = КОРЕНЬ / "interface" / "react-app" / "src" / "nl" / "methods.series.js"
МЕНЮ = КОРЕНЬ / "interface" / "react-app" / "src" / "nl" / "render.gen.jsx"


def node(модуль: Path, импорт: str, тело: str):
    if shutil.which("node") is None:
        pytest.skip("node не установлен — проверка фронта пропущена")
    src = f"import {{ {импорт} }} from '{модуль.as_uri()}';\n{тело}"
    # ВЫВОД ДЕКОДИРУЕМ САМИ, В UTF-8 (Раунд 61). При text=True питон берёт
    # кодировку локали, и на Windows кириллица из node приходила мойбейком —
    # поймано первым же прогоном тестов на трёх системах. node печатает UTF-8
    # всегда, гадать тут нечего.
    p = subprocess.run(["node", "--input-type=module", "-e", src],
                       capture_output=True, timeout=60)
    вывод = (p.stdout or b"").decode("utf-8", "replace")
    ошибки = (p.stderr or b"").decode("utf-8", "replace")
    assert p.returncode == 0, f"node упал:\n{ошибки}"
    assert вывод.strip(), f"node ничего не напечатал. stderr:\n{ошибки}"
    return json.loads(вывод)


@pytest.fixture()
def хранилище(tmp_path, monkeypatch):
    monkeypatch.setattr(sheets, "_VAULT_OVERRIDE", tmp_path / "тексты", raising=False)
    monkeypatch.setattr(sheets, "vault_dir", lambda: tmp_path / "тексты")
    monkeypatch.setattr(sheets, "_vault", lambda: _готовое(tmp_path / "тексты"))
    return tmp_path / "тексты"


def _готовое(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---- 1. корень серий не удаляется ------------------------------------------

def test_nepustoy_koren_seriy_ne_vysypaetsya(хранилище):
    """В коде серии было написано «одна папка, её нельзя удалить». Удалялась —
    и `folder_delete` поднимал содержимое на уровень выше, то есть все
    названия высыпались поверх собственных текстов пользователя.

    Отказ НАЗЫВАЕТ, что внутри: «не удаляется» без причины пользователь читает как
    поломку — так и вышло в первой версии этой защиты."""
    sheets.folder_create("Серии/Пепел")
    with pytest.raises(sheets.SheetError) as e:
        sheets.folder_delete("Серии")
    assert "Пепел" in str(e.value)
    assert (хранилище / "Серии" / "Пепел").is_dir()


def test_pustoy_koren_seriy_udalyaetsya(хранилище):
    """ПОЧИНКА В ТОТ ЖЕ ДЕНЬ. Сначала я запретил корень совсем — и отчёт: папки не удалялись: у него это была единственная папка, к тому
    же пустая, оставшаяся от моей же проверки.

    Запрет ради опасности, которой в пустой папке нет, — не защита, а
    отобранная уборка. Следующий прогон серии заведёт корень заново."""
    sheets.folder_create("Серии")
    sheets.folder_delete("Серии")
    assert not (хранилище / "Серии").exists()


def test_vnutri_kornya_papki_udalyayutsya(хранилище):
    """Защита ровно на один уровень: названия и треки внутри — обычные папки,
    и запрещать их значило бы отобрать у пользователя уборку."""
    sheets.folder_create("Серии/Пепел/дорога")
    sheets.folder_delete("Серии/Пепел/дорога")
    assert not (хранилище / "Серии" / "Пепел" / "дорога").exists()
    sheets.folder_delete("Серии/Пепел")
    assert not (хранилище / "Серии" / "Пепел").exists()
    assert (хранилище / "Серии").is_dir(), "корень обязан пережить уборку внутри"


def test_imya_kornya_odno_na_dvoih():
    """Два экземпляра одной строки однажды разойдутся: `series_run.ROOT`
    обязан брать имя у хранилища, а не заводить своё."""
    import series_run
    assert series_run.ROOT == sheets.КОРЕНЬ_СЕРИЙ


# ---- 2. редактор переезжает за переименованным листом ----------------------

def test_redaktor_pereezzhaet_za_pereimenovannym_listom():
    """Серия нумерует листы трека по баллу, когда трек досчитан. Открытый лист
    теряет путь, и автосохранение падает с «лист не найден» — громко, но
    работать невозможно. Ищем по имени БЕЗ номера ранга: тем же ключом, каким
    серия хранит баллы в сайдкаре."""
    res = node(ЛИСТЫ, "sheetsMethods", """
    const self = Object.assign(Object.create(sheetsMethods), {
      state: { sheetId: 'Серии/Пепел/дорога/дверь скрипнула.md' } });
    console.log(JSON.stringify({
      переехал: sheetsMethods.открытыйПереехал.call(self, [
        { id: 'Серии/Пепел/дорога/03 дверь скрипнула.md' },
        { id: 'Серии/Пепел/дорога/01 другая строка.md' },
      ]),
      наместе: sheetsMethods.открытыйПереехал.call(self, [
        { id: 'Серии/Пепел/дорога/дверь скрипнула.md' },
      ]),
      пропал: sheetsMethods.открытыйПереехал.call(self, [
        { id: 'Серии/Пепел/дорога/совсем другой.md' },
      ]),
    }));
    """)
    assert res["переехал"] == "Серии/Пепел/дорога/03 дверь скрипнула.md"
    assert res["наместе"] == "", "лист на месте — трогать нечего"
    assert res["пропал"] == "", "чужой лист вместо пропавшего хуже, чем честная ошибка"


def test_perenumeratsiya_ne_puta_et_papki():
    """Край: одинаковое имя в РАЗНЫХ папках. Ключ включает путь, иначе
    редактор уехал бы в чужой трек."""
    res = node(ЛИСТЫ, "sheetsMethods", """
    const self = Object.assign(Object.create(sheetsMethods), {
      state: { sheetId: 'Серии/Пепел/зима/строка.md' } });
    console.log(JSON.stringify(sheetsMethods.открытыйПереехал.call(self, [
      { id: 'Серии/Пепел/дорога/01 строка.md' },
      { id: 'Серии/Пепел/зима/02 строка.md' },
    ])));
    """)
    assert res == "Серии/Пепел/зима/02 строка.md"


# ---- 3. меню серии показывает СДЕЛАННОЕ ------------------------------------

def test_ocenka_pokazyvaet_ostatok_a_ne_plan():
    """Прежняя оценка врала на каждом втором запуске: «30 текстов ≈ 8 мин» при
    двадцати восьми готовых."""
    res = node(СЕРИЯ_JS, "seriesMethods", """
    const self = Object.assign(Object.create(seriesMethods), { state: {
      seriesLinks: [{ count: 10 }, { count: 10 }, { count: 10 }],
      seriesState: { done: [10, 8, 0] }, seriesSec: 15 } });
    console.log(JSON.stringify(seriesMethods.seriesEstimate.call(self)));
    """)
    assert res["texts"] == 30 and res["done"] == 18 and res["left"] == 12
    assert res["seconds"] == 12 * 15


def test_ocenka_bez_sostoyaniya_ne_vryot():
    """Серию ещё не сохраняли — состояния нет. Тогда сделанного ноль, и
    «осталось» совпадает с планом: это правда, а не заглушка."""
    res = node(СЕРИЯ_JS, "seriesMethods", """
    const self = Object.assign(Object.create(seriesMethods), { state: {
      seriesLinks: [{ count: 4 }], seriesState: null, seriesSec: 15 } });
    console.log(JSON.stringify(seriesMethods.seriesEstimate.call(self)));
    """)
    assert res == {"texts": 4, "done": 0, "left": 4, "seconds": 60}


def test_menyu_stavit_prichinu_pod_svoy_trek():
    """Раньше первые три ошибки склеивались в общий хвост строки статуса, из
    которого не понять, какой трек ослаблять."""
    текст = МЕНЮ.read_text("utf-8")
    assert "сост.beda" in текст, "причина не привязана к треку"
    assert "openSeriesFolder" in текст, "из трека нет выхода в его папку"


# ---- 4. контролы, которых не видно, для пользователя не существуют ---------

def test_deystviya_lista_vidny_bez_navedeniya():
    """Отчёт: кнопок удаления папок и листов не было вовсе..

    Переименовать, переложить, продублировать и выбросить можно было только
    наведя курсор ровно на строку: `--sh: 0` на строке гасил их в ноль.

    Первая починка была неверной: я поменяла ФОЛБЭК `var(--sh, 0)` на
    `var(--sh, 0.55)` — а фолбэк недостижим, потому что сама переменная задана
    на строке. Меняется значение, а не запасное."""
    текст = (КОРЕНЬ / "interface" / "react-app" / "src" / "nl" / "render.sheets.jsx").read_text("utf-8")
    assert "--sh: 0;" not in текст, "строка листа снова гасит свои кнопки в ноль"
    assert "--sh: 0.55" in текст, "кнопки строки листа не имеют видимого покоя"


def test_u_papki_est_knopka_udaleniya():
    """Удаление папки жило исключительно в подсказке при наведении
    («shift-клик удалит») — то есть его не было."""
    текст = (КОРЕНЬ / "interface" / "react-app" / "src" / "nl" / "render.sheets.jsx").read_text("utf-8")
    assert "'Удалить папку «'" in текст, "у папки нет кнопки удаления с понятным именем"
    assert "c.dropFolder(f.id)" in текст
