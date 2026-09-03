# nakedlunch — русские векторы слов (navec, natasha project, MIT:
# https://github.com/natasha/navec). ЧТО ЭТОТ МОДУЛЬ ДЕЛАЕТ СЕГОДНЯ: поднимает
# модель и отдаёт две вещи — словарь `_index` («слово → номер») и матрицу
# нормированных векторов `_vectors`. Всё остальное живёт у читателей: слой
# «близкое» во вкладке подсказок по слову (`core/wordsuggest.py`) и печка
# индекса (`tools/build_nl_index.py`).
#
# ЗАЧЕМ ОН ЗАВОДИЛСЯ (2026-07-17) — ради ТЕМЫ, вырезанной 2026-08-29. Владелец
# набирал «деньги» и получал это слово буквально в 19 строках из 20: отбор
# давал фрагменту 0.6+1 за БУКВАЛЬНОЕ вхождение слова темы и 0.6+0 за всё
# прочее, а буквальных совпадений в пуле хватало, чтобы занять всю выдачу.
# требование: «может не встречаться напрямую даже, но всё равно явно
# захватывать запрошенную тему». Отсюда и векторы: строка должна ранжироваться
# по СМЫСЛУ темы, а не по её написанию.
#
# Сама тема ушла, а векторы остались — они оказались нужнее там, где их не
# заводили. Четыре функции темы снесены 2026-09-02, надгробие ниже.
#
# ONE dependency: numpy (already transitive via pymorphy3/wordfreq) — no
# torch. A spike (PLAN.md, "torch проверен и отвергнут ПО ИЗМЕРЕНИЮ") found a
# 560M-parameter sentence encoder gave NO better signal than this 51MB
# word-vector model for the OTHER embeddings use (favorites clustering) —
# same reasoning applies here: word-level cosine is the right-shaped tool for
# "which words belong near this theme," not a heavier one.
#
# Model file is a build artifact like core/data/nl_rhyme —
# committed, loaded once at server startup (see warm_caches, called from
# api/server.py). Re-fetch if missing: the official natasha release,
# navec_hudlit_v1_12B_500K_300d_100q.tar (~51MB, MIT), from
# https://github.com/natasha/navec — save as core/data/navec.tar.

from __future__ import annotations


import numpy as np

import пути

_MODEL_PATH = пути.таблица("navec.tar")

_vectors: np.ndarray | None = None
_index: dict[str, int] | None = None
_load_attempted = False


def warm_caches() -> None:
    """Load the model once at server startup so the first themed request
    isn't the one paying the ~0.3s load cost. Best-effort — a missing or
    unreadable model file just means themed runs fall back to literal-only
    matching (_ensure_loaded returns False every time, cheaply)."""
    _ensure_loaded()


def _ensure_loaded() -> bool:
    global _vectors, _index, _load_attempted
    if _vectors is not None:
        return True
    if _load_attempted:
        return False
    _load_attempted = True
    if not _MODEL_PATH.exists():
        return False
    try:
        from navec import Navec
        nav = Navec.load(str(_MODEL_PATH))
        raw = nav.pq.unpack()
        norms = np.linalg.norm(raw, axis=1)
        _vectors = raw / np.clip(norms[:, None], 1e-9, None)
        _index = {w: i for i, w in enumerate(nav.vocab.words)}
        return True
    except Exception:
        return False


# НАДГРОБИЕ 2026-09-02: ЧЕТЫРЕ ФУНКЦИИ ТЕМЫ — `theme_vector`,
# `theme_similarities`, `lemma_centroid`, `relevance` (девяносто строк из ста
# пятидесяти семи).
#
# Все четыре обслуживали ТЕМУ и якорь строфы, вырезанные 2026-08-29 коммитом
# `2c1eadd`. Читателей вне этого модуля у них с того дня ноль — проверено
# обходом дерева разбором, а не текстом; во фронте их нет вовсе.
#
# ПОЧЕМУ САМ МОДУЛЬ ЖИВ И ОСТАЁТСЯ. Его держит слой «близкое» в
# `core/wordsuggest.py` и печка индекса: обоим нужны `_ensure_loaded`, `_index`
# и `_vectors` — двадцать четыре чтения `warm_caches` по репозиторию. Надгробия
# в `core/filters.py`, `api/server.py` и `core/nlindex.py` хоронили ТЕМУ и
# оправдывали жизнь ФАЙЛА; про эти четыре функции они не говорили ничего, и
# половина модуля осталась притворяться живой.
#
# ЧЕМ ЭТО БЫЛО ВРЕДНО, помимо веса. Уцелевшие докстринги называли снятые
# механизмы в настоящем времени: `relevance` объясняла, что «ручка связности в
# filters.py теперь двусторонняя (`theme_pull`, −1..+1)», а `lemma_centroid` —
# что якорь строфы требует проверки на уровне смысла. Читатель принимал это за
# действующий договор и шёл искать `theme_pull`, которого нет.
#
# Что именно они делали: `theme_vector` — нормированный центроид векторов слов
# темы; `theme_similarities` — косинусы всего словаря к теме одним матмулом на
# запрос (замер: 500k×300 меньше 10 мс против ~600 тысяч отдельных вызовов);
# `lemma_centroid` — «точка смысла» строки для сравнения с якорем; `relevance` —
# средний косинус знаменательных слов строки к теме, нарочно не зажатый в
# [0, 1], чтобы «диссонанс» мог предпочитать отрицательные значения.
