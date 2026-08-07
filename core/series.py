# nakedlunch — ЧЕТВЁРТАЯ полка сохранённого: СЕРИИ (Раунд 53).
#
# Требование (2026-08-04): серия — уровень выше пайплайна: строфа, затем прогон пайплайна,
# затем серия..
#
# Серия = список звеньев {альбом, тема, цепочка с полки, сколько претендентов}.
# Ровно как звено цепочки = {строфа с полки, профиль настроек} — тот же приём
# уровнем выше, поэтому и хранится тем же способом: свой файл рядом с
# corpus.json, валидатор в clean.py, никаких белых списков (на них проект
# обжигался дважды, см. шапку chain_profiles.py).
#
# ЧЕГО ЗДЕСЬ НЕТ. Самого прогона: полка только хранит. Гонять серию будет
# отдельный механизм — у него своя очередь, свой замок и своя раскладка по
# папкам, и мешать «что хранится» с «как исполняется» значит получить третью
# сущность, которая ни то ни другое.

from __future__ import annotations

import json
from pathlib import Path

import clean

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SERIES_PATH = DATA_DIR / "series.json"


def custom() -> list[dict]:
    """Сохранённые серии, или [] если файла нет и он нечитаем. Битая запись
    выбрасывается поштучно — одна кривая строка не должна уносить всю полку."""
    try:
        data = json.loads(SERIES_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for x in data:
        try:
            s = clean.series(x)
        except clean.BadInput:
            continue      # кривое имя альбома в старой записи — пропускаем её одну
        if s:
            out.append(s)
    return out


def _write(items: list[dict]) -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SERIES_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1), "utf-8")
    return items


def save(raw: dict) -> list[dict]:
    """Сохранить или перезаписать по имени. Проверка ДО записи: кривая серия
    отвергается одной фразой сейчас, а не среди ночи на середине прогона."""
    entry = clean.series(raw)
    if entry is None:
        raise clean.BadInput("серии нужно имя и хотя бы одно звено с цепочкой")
    return _write([s for s in custom() if s["name"] != entry["name"]] + [entry])


def delete(name: str) -> list[dict]:
    return _write([s for s in custom() if s["name"] != name])


def by_name(name: str) -> dict | None:
    if not name:
        return None
    for s in custom():
        if s["name"] == name:
            return s
    return None


# ---- оценка времени ------------------------------------------------------
#
# ЗАЧЕМ ОНА В ДОМЕНЕ, А НЕ В ИНТЕРФЕЙСЕ. тысячи претендентов на трек — это 17 суток на сто треков, и узнать об этом он должен ДО
# запуска, а не утром. Считает домен, потому что число берётся из замеров
# самого прогона, а не из фантазии экрана.

SECONDS_PER_TEXT = 15.0   # замер 2026-08-04: 4 звена 9.7 с, 6 звеньев 16.3 с


def estimate(entry: dict) -> dict:
    """{texts, seconds} — сколько текстов даст серия и сколько это займёт."""
    n = sum(int(l["count"]) for l in (entry or {}).get("links") or ())
    return {"texts": n, "seconds": int(n * SECONDS_PER_TEXT)}
