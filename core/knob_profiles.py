# extendo — вторая полка сохранённого: ПРОФИЛИ НАСТРОЕК (Раунд 50).
#
# Требование (2026-08-03): сохранение строф, профилей настроек и цепочек — раздельные вещи:
# каркас строфы и положения крутилок ставятся независимо..
#
# До этого раунда крутилки хранились ВНУТРИ формы строфы (stanza_profiles.save
# принимал `params`), и выбор формы молча двигал ползунки. Полки разъезжаются:
# строфа — только каркас, крутилки — здесь.
#
# Устройство ровно как у core/stanza_profiles.py, сознательно: тупой стор без
# проверок, свои профили в data/knob_profiles.json рядом с corpus.json и
# settings.json. Проверяет clean.knob_profile() — и на входе, и на выходе
# (файл, который пользователь может открыть руками, не заслуживает доверия ни в
# одну сторону). То же разделение труда, что у settings.py.
#
# Встроенные — КОНСТАНТА модуля, а не файл в core/data: их две, и заводить
# ради двух записей ещё один файл значит плодить сущности на ровном месте
# (в отличие от stanza_forms.json, где 24 стиховедческие формы).

from __future__ import annotations

import json

import склад

import clean

import пути

DATA_DIR = пути.ДАННЫЕ
PROFILES_PATH = DATA_DIR / "knob_profiles.json"

# Стартовые профили. Не «вкусовые пресеты» (их пользователь соберёт сам под свой
# слух), а два необходимых полюса: то, чем звено набирается по умолчанию, и
# единственный способ дотянуться до бинарной классики, пока своих профилей нет.
#
# «Обычный» — ИЗМЕРЕННЫЕ положения пользователя из data/settings.json (nl_params
# на 2026-08-03), а не круглые числа из головы: Источники 1.0 (генератор
# extendo он давно не зовёт), Точность 0.25, Мелодичность 0.35, Банальность
# 0.35, Диссонанс 0.7.
BUILTIN = [
    {
        "name": "Обычный",
        "mode": clean.MODE_ALGO,
        "params": {"Источники": 1.0, "Мат": -1.0, "Клаузула": 0, "Связность": -1.0,
                   "Точность рифм": 0.25, "Мелодичность": 0.35,
                   # 0.83 = его же 0.35 в новой двусторонней шкале (Раунд 58)
                   "Банальность": 0.83, "Диссонанс": 0.7},
    },
    {
        "name": "Классика",
        "mode": clean.MODE_CLASSIC,
        # мнений тут нет и быть не может — режим их отключает целиком
        # (nlindex.select_light); остаются только ворота
        "params": {"Источники": 1.0, "Мат": -1.0, "Клаузула": 0, "Связность": -1.0},
    },
]


def builtin() -> list[dict]:
    """Встроенные профили, прогнанные через валидатор — как и custom(): один
    источник правды о форме записи, даже для своих же констант."""
    return [p for p in (clean.knob_profile(p) for p in BUILTIN) if p]


def custom() -> list[dict]:
    """Свои профили пользователя, или [] если файла нет и он нечитаем. Никогда не
    роняет: испорченный файл здесь — потеря положений ползунков, досадная, но
    не фатальная (в отличие от corpus.json, который падает честно)."""
    try:
        data = json.loads(PROFILES_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [p for p in (clean.knob_profile(p) for p in data) if p]


def _write(profiles: list[dict]) -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    склад.писать(PROFILES_PATH, profiles)
    return profiles


def save(name: str, mode: str, params: dict | None) -> list[dict]:
    """Сохранить или перезаписать по имени. Возвращает весь список своих — той
    же формы, что отдаёт custom(), чтобы вызывающий отдал его клиенту без
    второго чтения диска."""
    entry = clean.knob_profile({"name": name, "mode": mode, "params": params})
    if entry is None:
        raise clean.BadInput("у профиля настроек должно быть имя")
    return _write([p for p in custom() if p.get("name") != entry["name"]] + [entry])


def delete(name: str) -> list[dict]:
    return _write([p for p in custom() if p.get("name") != name])


def by_name(name: str) -> dict | None:
    """Профиль по имени: свои ПОВЕРХ встроенных — своя запись с тем же именем
    это сознательный оверрайд пользователя (то же правило, что у форм строф в
    pipeline.resolve_chain)."""
    if not name:
        return None
    for p in custom() + builtin():
        if p["name"] == name:
            return p
    return None
