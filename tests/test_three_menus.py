# nakedlunch — ТРИ МЕНЮ, А НЕ ОДИН ПОПАП (Раунд 55).
#
# Пользователь разобрал раскладку и сформулировал её так:
#
#   СТРОФА     мастерская  — делаются детали: формы и профили настроек
#   ПАЙПЛАЙН   сборка      — из готовых деталей собирается текст
#   СЕРИЯ      конвейер    — готовая сборка повторяется много раз
#
# Всё, что здесь сторожится, — про ОДНО правило: зависимость только вперёд.
# Пайплайн берёт с полок «Строфы» и сам ничего не правит; серия берёт цепочки с
# полки «Пайплайна» и сама ничего не правит. Стоит одному меню полезть в чужой
# этаж — и возвращается тот самый класс ошибок, ради которого попап делили:
# правка относится непонятно к чему.
#
# Проверка текстовая там, где речь о структуре модулей (сборка тут не помогает:
# она зелёная и при утечке), и настоящим node там, где речь о поведении чистой
# функции.
#
# Прогон: .venv/bin/python -m pytest tests/test_three_menus.py -q

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
NL = КОРЕНЬ / "interface" / "react-app" / "src" / "nl"
МЕНЮ = NL / "render.gen.jsx"
ШАПКА = NL / "render.panels.jsx"
ГЕНЕРАЦИЯ = NL / "methods.gen.js"
ПАНЕЛИ = NL / "methods.panels.js"


def node(тело: str):
    if not subprocess.run(["which", "node"], capture_output=True).returncode == 0:
        pytest.skip("node не установлен — проверка фронта пропущена")
    src = f"import {{ panelMethods }} from '{ПАНЕЛИ.as_posix()}';\n{тело}"
    p = subprocess.run(["node", "--input-type=module", "-e", src],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"node упал:\n{p.stderr}"
    return json.loads(p.stdout)


def тело_метода(текст: str, имя: str) -> str:
    """Кусок файла от объявления метода до следующего объявления на том же
    отступе. Грубо, но достаточно: нам нужно знать, что метод ЧИТАЕТ."""
    i = текст.index(имя)
    хвост = текст[i:]
    m = re.search(r"\n  (?:async )?[A-Za-zА-Яа-я_][\w]*\(", хвост[len(имя):])
    return хвост[:len(имя) + m.start()] if m else хвост


# ---- 1. структура: три меню и три кнопки -----------------------------------

def test_три_меню_экспортируются():
    текст = МЕНЮ.read_text("utf-8")
    for имя in ("renderStanzaMenu", "renderPipeMenu", "renderSeriesMenu"):
        assert f"export function {имя}(" in текст, f"{имя} не экспортируется"
    assert "renderGenPanel" not in текст, "единый попап вернулся"


def test_три_кнопки_в_шапке():
    текст = ШАПКА.read_text("utf-8")
    for метка, ключ in (("Строфа", "stanza"), ("Пайплайн", "pipe"), ("Серия", "series")):
        assert f'aria-label="{метка}"' in текст, f"кнопки «{метка}» нет в шапке"
        assert f"st.openPill === '{ключ}'" in текст, f"меню «{метка}» ничем не открывается"


# ---- 2. зависимость только вперёд ------------------------------------------

def test_одиночная_строфа_не_читает_цепочку():
    """ГЛАВНЫЙ. Строфа — своё занятие со своей формой и своим профилем.

    В Раунде 51 genStanza читал linkSpec(0)/linkKnobs(0) — и это было верно,
    пока строфа и пайплайн жили в одном попапе: тогда «цепочка из одного
    звена» и «одиночная строфа» обязаны были совпадать. Теперь это две кнопки,
    и чтение чужого этажа вернуло бы связь, ради разрыва которой попап делили.
    """
    тело = тело_метода(ГЕНЕРАЦИЯ.read_text("utf-8"), "async genStanza(")
    код = [s for s in тело.split("\n") if not s.lstrip().startswith("//")]
    for чужое in ("linkSpec(", "linkKnobs(", "state.chain"):
        assert not [s for s in код if чужое in s], \
            f"одиночная генерация читает {чужое} — это этаж пайплайна"
    assert "this.curSpec()" in тело, "строфа не берёт форму из своей мастерской"


def test_пайплайн_не_правит_полки():
    """Сборка не должна содержать конструкторов и ползунков: новые формы и
    профили делаются в «Строфе». Иначе полка правится из двух мест, и
    «слепок главнее полки» перестаёт что-либо значить."""
    текст = МЕНЮ.read_text("utf-8")
    i = текст.index("export function renderPipeMenu(")
    j = текст.index("export function renderSeriesMenu(")
    тело = текст[i:j]
    for чужое in ("setLineSyl", "cycleLetter", "setKnob(", "saveStanzaProfile", "saveKnobProfile"):
        assert чужое not in тело, f"меню пайплайна правит полку: {чужое}"


def test_выбор_звена_не_вернулся():
    """openLink/selectLink/shelfTab жили ради вопроса «к какому звену
    относится редактор под цепочкой». Редактора под цепочкой больше нет."""
    for файл in (МЕНЮ, ГЕНЕРАЦИЯ, ПАНЕЛИ, NL / "methods.shelves.js"):
        код = [s for s in файл.read_text("utf-8").split("\n")
               if not s.lstrip().startswith("//") and not s.lstrip().startswith("*")]
        for мёртвое in ("openLink", "shelfTab", "selectLink("):
            попались = [s for s in код if мёртвое in s and "КЛЮЧИ_МОДЕЛИ" not in s
                        and "'" + мёртвое + "'" not in s]
            assert not попались, f"{мёртвое} вернулся в {файл.name}: {попались[:2]}"


# ---- 3. пустых звеньев не бывает -------------------------------------------

def test_новое_звено_наследует_у_соседа():
    """Раньше новое звено брало форму и профиль ИЗ ПАНЕЛИ, а панель была ещё и
    невидимым запасным источником для звеньев без полок. Вместе это давало
    «звено выглядит пустым, а набирается неизвестно чем». Теперь наследует у
    предыдущего — как строка серии."""
    res = node("""
    let out = null;
    const self = Object.assign(Object.create(panelMethods), {
      state: { chain: ['Куплет', 'Припев'],
               chainForms: ['Катрен перекрёстный', 'Двустишие'],
               chainKnobs: ['Обычный', 'Плотный'],
               chainRepeat: [null, null],
               stanzaProfile: 'Хайку', knobProfile: 'Мастерская' },
      setState: (p) => { out = p; },
    });
    panelMethods.addChip.call(self);
    console.log(JSON.stringify(out));
    """)
    assert res["chainForms"] == ["Катрен перекрёстный", "Двустишие", "Двустишие"]
    assert res["chainKnobs"] == ["Обычный", "Плотный", "Плотный"]
    assert res["chain"] == ["Куплет", "Припев", ""]


def test_звено_после_повтора_наследует_у_двойника():
    """Край: у звена-повтора своей формы нет по определению — оно берёт её у
    того, кого повторяет. Наследовать у него значило бы получить пустоту."""
    res = node("""
    let out = null;
    const self = Object.assign(Object.create(panelMethods), {
      state: { chain: ['Припев', 'Припев'],
               chainForms: ['Катрен парный', null],
               chainKnobs: ['Плотный', null],
               chainRepeat: [null, 0],
               stanzaProfile: '', knobProfile: '' },
      setState: (p) => { out = p; },
    });
    panelMethods.addChip.call(self);
    console.log(JSON.stringify(out));
    """)
    assert res["chainForms"][2] == "Катрен парный", "новое звено наследовало пустоту повтора"
    assert res["chainKnobs"][2] == "Плотный"


def test_звено_без_полки_подписано():
    """«Пусто» в выпадашке звена не значит «пусто»: звено что-то да возьмёт.
    Подпись обязана говорить что именно — иначе возвращается невидимый
    источник, только теперь под видом прочерка."""
    текст = МЕНЮ.read_text("utf-8")
    assert "как в мастерской" in текст and "из слепка" in текст and "снято по тексту" in текст, \
        "звено без своей полки снова подписано пустотой"


# ---- 4. кривая уехала из пайплайна -----------------------------------------

def test_кривая_не_живёт_в_пайплайне():
    """Требование: искажение живёт в серии и влияет на её пайплайны, а не в пайплайне.. Плюс форму ОДНОГО
    текста и так задают профили звеньев, и вторая машинка для того же самого
    была лишней."""
    for файл in (МЕНЮ, ГЕНЕРАЦИЯ):
        код = [s for s in файл.read_text("utf-8").split("\n")
               if not s.lstrip().startswith("//") and not s.lstrip().startswith("*")]
        assert not [s for s in код if "applyCurve" in s or "pipelineCurve" in s], \
            f"кривая вернулась в пайплайн ({файл.name})"


# ---- 5. одно понятие — одно слово ------------------------------------------

def test_stroka_serii_vezde_trek():
    """Одна и та же строка звалась в ОДНОЙ панели треком (на кнопке), звеном
    (в подсказке удаления) и звеном серии (в ошибке запуска). Слово должно
    быть одно — иначе пользователь ищет в интерфейсе три разные сущности."""
    текст = МЕНЮ.read_text("utf-8")
    i = текст.index("export function renderSeriesMenu(")
    видимое = re.findall(r'title="([^"]*)"|>([а-яА-ЯёЁ ]{3,})<', текст[i:])
    слова = " ".join(a + b for a, b in видимое)
    assert "трек" in слова
    assert "звен" not in слова, f"в меню серии осталось «звено»: {слова}"

    серия = (NL / "methods.series.js").read_text("utf-8")
    ошибки = re.findall(r"flash\('([^']*)'\)", серия)
    assert not [о for о in ошибки if "звен" in о], f"ошибка серии говорит «звено»: {ошибки}"


def test_polka_karkasa_nazyvaetsya_formoy():
    """«Строфа» — это РЕЗУЛЬТАТ, а полка про каркас. Отсюда половина путаницы
    «где строфа, а где цепочка»: одно слово значило две вещи."""
    текст = МЕНЮ.read_text("utf-8")
    i = текст.index("export function renderStanzaMenu(")
    j = текст.index("export function renderPipeMenu(")
    тело = текст[i:j]
    assert ">форма<" in тело, "полка каркаса снова называется строфой"
    assert "своя форма" in МЕНЮ.read_text("utf-8")


def test_tema_a_ne_klyuch():
    """На этажах 1-2 она звалась «ключ», на этаже 3 — «тема», и это одно и то
    же понятие. Бэк, серия и статистика зовут её темой — значит тема."""
    ген = ГЕНЕРАЦИЯ.read_text("utf-8")
    assert "'без темы'" in ген and "'тема: «'" in ген
    assert "без ключа" not in ген, "статусная строка снова говорит «ключ»"
