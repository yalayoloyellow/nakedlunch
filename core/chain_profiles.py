# extendo — третья полка сохранённого: ЦЕПОЧКИ (Раунд 50).
#
# Требование (2026-08-03): цепочка хранит копии — правка профиля не трогает сохранённые
# цепочки; готовое решение навсегда такое, каким его сохранили.. Поэтому здесь лежат СЛЕПКИ: каркас и крутилки каждого звена
# копиями, имя формы — только подписью.
#
# ГДЕ ЛЕЖАЛО РАНЬШЕ. Ключ `nl_chain_profiles` внутри data/settings.json,
# который сервер писал сырьём и не проверял ни на одном конце: settings.write()
# пишет что дали, фронт читает что лежит. Битый слепок обнаруживался не при
# сохранении, а на прогоне — 400 из clean.pipeline_spec, уже после ожидания.
# Плюс ключ проходил ДВА независимых белых списка (роут и settings._ALLOWED), и
# пропуск в любом молча съедал запись — на этом проект уже обжигался дважды.
#
# Теперь как у двух соседних полок: свой файл рядом с corpus.json, валидатор в
# clean.py, никаких белых списков. Мигрировать было нечего — на диске пользователя
# сохранённых цепочек не было ни одной (nl_chain_profiles: null).

from __future__ import annotations

import json

import склад
from pathlib import Path

import clean

import пути

DATA_DIR = пути.ДАННЫЕ
PROFILES_PATH = DATA_DIR / "chain_profiles.json"

# ---------------------------------------------------------------------------
# ВСТРОЕННЫЕ ЦЕПОЧКИ (Раунд 55)
#
# Отчёт: сохранённые пресеты пайплайна не отображались при выборе в серии.. И он
# прав, а я нет.
#
# До этого раунда пресеты жили константой ВО ФРОНТЕ и полкой не были: серия
# ищет цепочку по имени через `by_name`, там их не было, и «заготовка не решение»), но это была не архитектура, а
# случайность реализации: у двух соседних полок — форм строф и профилей
# настроек — встроенные записи есть, и полка цепочек была единственной без.
#
# Теперь как у соседей: builtin() + custom(), одна форма записи, один
# валидатор. Каркас звена берётся у формы строфы по имени, крутилки — у
# профиля «Обычный»: то же самое, что делал фронт при выборе пресета, только
# теперь это делает домен и результат виден всем, включая серию.
#
# Звено — [заголовок секции, форма строфы, номер повторяемого звена].
_ВСТРОЕННЫЕ = {
    "Куплет-припев": [["Куплет", "Катрен перекрёстный", None],
                      ["Припев", "Катрен парный короткий", None],
                      ["Куплет", "Катрен перекрёстный", None],
                      ["Припев", None, 1],
                      ["Бридж", "Катрен кольцевой", None],
                      ["Припев", None, 1]],
    "Хук-формат": [["Хук", "Двустишие", None],
                   ["Куплет", "Катрен перекрёстный", None],
                   ["Хук", None, 0],
                   ["Куплет", "Катрен перекрёстный", None],
                   ["Хук", None, 0]],
    # «Вольная» — намеренно без повторов: это стихотворение, а не песня.
    "Вольная": [["", "Катрен перекрёстный", None]] * 4,
}

_builtin_cache: list[dict] | None = None


def builtin() -> list[dict]:
    """Три встроенные цепочки как полноценные записи полки.

    Собираются из форм строф и профиля «Обычный» — ровно так же, как их
    собирал бы пользователь руками. Прогоняются через тот же валидатор, что и
    свои: один источник правды о форме записи, даже для собственных констант.

    Кэш на процесс: формы строф — тоже константа сборки."""
    global _builtin_cache
    if _builtin_cache is not None:
        return _builtin_cache
    import knob_profiles
    import stanza_profiles

    формы = {f["name"]: f for f in stanza_profiles.builtin() + stanza_profiles.custom()}
    обычный = knob_profiles.by_name("Обычный") or {"mode": clean.MODE_ALGO, "params": {}}
    out = []
    for имя, звенья in _ВСТРОЕННЫЕ.items():
        links = []
        for заголовок, форма, повтор in звенья:
            з = {"title": заголовок}
            if повтор is not None:
                з["repeat_of"] = повтор
            else:
                f = формы.get(форма or "")
                if not f:
                    links = []
                    break            # форму переименовали — цепочка молча не собирается
                з.update({"form": форма, "spec": f["lines"], "knobs_profile": "Обычный",
                          "params": обычный.get("params") or {},
                          "mode": обычный.get("mode") or clean.MODE_ALGO})
            links.append(з)
        c = clean.chain_profile({"name": имя, "links": links, "junctions": [],
                                 "reference": {"text": "", "pct": 1}}) if links else None
        if c:
            out.append(c)
    _builtin_cache = out
    return out


def custom() -> list[dict]:
    """Сохранённые цепочки, или [] если файла нет и он нечитаем. Битая запись
    выбрасывается поштучно — одна кривая строка не должна уносить всю полку."""
    try:
        data = json.loads(PROFILES_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [c for c in (clean.chain_profile(x) for x in data) if c]


def _write(items: list[dict]) -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    склад.писать(PROFILES_PATH, items)
    return items


def save(raw: dict) -> list[dict]:
    """Сохранить или перезаписать по имени. Проверка ДО записи: битый слепок
    отвергается одной фразой, а не обнаруживается через минуту на прогоне."""
    entry = clean.chain_profile(raw)
    if entry is None:
        raise clean.BadInput("цепочке нужно имя и хотя бы одно звено со строфой")
    return _write([c for c in custom() if c["name"] != entry["name"]] + [entry])


def delete(name: str) -> list[dict]:
    return _write([c for c in custom() if c["name"] != name])


def by_name(name: str) -> dict | None:
    """Своя цепочка главнее встроенной: сохранил под тем же именем — работает
    твоя. Тот же порядок, что у профилей настроек (knob_profiles.by_name)."""
    if not name:
        return None
    for c in custom() + builtin():
        if c["name"] == name:
            return c
    return None
