# nakedlunch — журнал прогонов знает ВСЕ крутилки (2026-08-18).
#
# ЧТО СЛУЧИЛОСЬ. `api_generate` писал в `stats.jsonl` пять крутилок из девяти.
# Молчали «Мат», «Клаузула», «Связность» и «Повтор». Обнаружилось это не
# чтением кода, а замером: большой разбор девяти крутилок не смог сказать про
# эти четыре ничего — выводы пришлось пометить «предположение» вместо
# «измерено». То есть про треть настроек было неизвестно, пользуется ими
# человек или нет, и следующее решение о них было бы гаданием.
#
# ПОЧЕМУ СТОРОЖ СВЕРЯЕТСЯ СО СПИСКОМ, А НЕ С ЧИСЛОМ «ДЕВЯТЬ». Ручки заводят и
# убирают; «девять» устареет молча, а расхождение со `clean.KNOB_SPEC` —
# единственным источником правды об именах — покраснеет в тот же день. Ровно
# та же болезнь, что дважды ловил `test_boot.py`: сторож, проверяющий
# написанное, а не свойство, переживает своё правило.

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

import clean  # noqa: E402

# Экранное имя → имя в ядре. Второй такой карты в проекте нет: перевод живёт в
# `clean.knobs_from_profile`, и здесь он повторён НАРОЧНО — сторож обязан
# ловить и то, что перевод молча переименовали.
ЭКРАН_В_ЯДРО = {
    "Источники": "real_text",
    "Мат": "mat_share",
    "Клаузула": "clausula",
    "Точность рифм": "rhyme_precision",
    # «Мелодичность» → "melody" УДАЛЕНА 2026-08-21 (надгробие в filters.py),
    # «Банальность» → "banality" УДАЛЕНА 2026-08-20 вместе с ручкой (надгробие
    # в core/nlindex.py). Карта обязана сойтись с `clean.KNOB_SPEC` — этот
    # сторож и ловит, если ключ забудут снять на одной из сторон.
    "Диссонанс": "cohesion",        # у ядра консонанс, у ползунка диссонанс
    # «Связность» → "flow" УДАЛЕНА 2026-08-21 (надгробие в filters.py).
    "Повтор": "repeat",
}


def test_karta_pokryvaet_vse_krutilki():
    """Сначала сверяем саму карту: если завели десятую ручку, тест ниже без
    этого молча проверял бы девять старых."""
    assert set(ЭКРАН_В_ЯДРО) == set(clean.KNOB_SPEC), (
        "карта «экран → ядро» разошлась с clean.KNOB_SPEC: "
        f"лишние {set(ЭКРАН_В_ЯДРО) - set(clean.KNOB_SPEC)}, "
        f"забытые {set(clean.KNOB_SPEC) - set(ЭКРАН_В_ЯДРО)}")


def test_knobs_yadra_znaet_kazhduyu_krutilku():
    """`clean.knobs` обязана отдавать ключ на каждую ручку — иначе роут не
    сможет её записать при всём желании."""
    ядро = clean.knobs(clean.knobs_from_profile(
        {"name": "проверка", "mode": clean.MODE_ALGO, "params": {}}))
    нет = [э for э, я in ЭКРАН_В_ЯДРО.items() if я not in ядро]
    assert not нет, f"ядро не отдаёт крутилки: {нет}"


@pytest.fixture()
def запись_прогона(tmp_path, monkeypatch):
    """Одна запись «generate», снятая с НАСТОЯЩЕГО роута.

    Проверять сам словарь `ui_knobs` было бы проверкой двойника: он собирается
    внутри роута, и промах был именно там. Поэтому зовём роут и читаем, что
    он положил в журнал."""
    import embeddings
    import filters
    import generate
    было = (filters.warm_caches, generate.warm_caches, embeddings.warm_caches)
    filters.warm_caches = lambda: None
    generate.warm_caches = lambda: None
    embeddings.warm_caches = lambda: None
    sys.path.insert(0, str(КОРЕНЬ / "api"))
    try:
        import server
    finally:
        (filters.warm_caches, generate.warm_caches, embeddings.warm_caches) = было

    import stats as stats_mod
    monkeypatch.setattr(stats_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(stats_mod, "STATS_PATH", tmp_path / "stats.jsonl")

    ответ = server.app.test_client().post("/api/generate", json={
        "mode": "классика", "rhyme": "none",
        "params": {э: сп[2] for э, сп in clean.KNOB_SPEC.items()},
    })
    assert ответ.status_code == 200, ответ.data[:400]

    строки = [json.loads(s) for s in
              (tmp_path / "stats.jsonl").read_text("utf-8").splitlines() if s.strip()]
    прогоны = [x for x in строки if x.get("kind") == "generate"]
    assert прогоны, f"роут не записал прогон вовсе: {строки}"
    return прогоны[-1]


def test_progon_pishet_vse_devyat_krutilok(запись_прогона):
    """ГЛАВНЫЙ. Прогон генерации кладёт в журнал каждую крутилку, а не пять."""
    записаны = запись_прогона.get("knobs") or {}
    нет = sorted(э for э, я in ЭКРАН_В_ЯДРО.items() if я not in записаны)
    assert not нет, (
        f"журнал прогонов молчит про крутилки: {нет}. "
        "Значит замер по ним снова ничего не скажет — см. шапку файла.")


def test_v_zhurnale_net_lishnego(запись_прогона):
    """ОБРАТНАЯ БЕДА. Ключ, которого на экране нет, — это столбец, который
    кто-нибудь примет за живую настройку. Допускается ровно одно исключение:
    `classic` — это РЕЖИМ, а не ползунок, и без него непонятно, к чему
    относятся остальные числа."""
    записаны = set(запись_прогона.get("knobs") or {})
    можно = set(ЭКРАН_В_ЯДРО.values()) | {"classic"}
    лишние = sorted(записаны - можно)
    assert not лишние, (
        f"в журнал пишутся ключи, которых нет среди крутилок: {лишние}")
