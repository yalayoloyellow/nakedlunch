# КЛАССИКА И МАСКА КЛАУЗУЛЫ (2026-08-29).
#
# ЧТО СЛУЧИЛОСЬ. 2026-08-28 клаузула стала МАСКОЙ концовок (1 мужская ·
# 2 женская · 4 дактилическая, 7 «любая») — по слову владельца «может я хочу
# только мужскую и дактилическую». Алгоритм переучили, а классику забыли:
# `nlindex.select_light` продолжал сравнивать `clau == clausula`, а колонка
# держит номера 1..3, и семёрки в ней не бывает вовсе.
#
# ИТОГ: КЛАССИКА ОТДАВАЛА НОЛЬ СТРОК при любом положении ручки — и молча, без
# ошибки. Поймано не тестом, а живым прогоном в браузере: экран не обновлялся,
# запрос отвечал 200, «ворота: 0».
#
# Почему не поймали тесты: test_classic_binary зовёт классику на стенде БЕЗ
# колоночного индекса, а там работает другой путь (_nl_scored light), и он
# маску понимал. Сторож ниже бьёт именно по индексному пути.
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import nlindex  # noqa: E402


class _Идх:
    """Минимальный индекс: только то, что читает select_light."""
    n = 6
    #                мужская, женская, дактиль, мужская, женская, дактиль
    clau = np.array([1, 2, 3, 1, 2, 3], dtype=np.int8)
    mat = np.zeros(6, dtype=np.uint8)
    rare_word = None
    rare_pair = None
    inner = np.zeros(6, dtype=np.uint8)

    def whole_mask(self):
        return np.ones(self.n, dtype=bool)

    def text(self, i):
        return f"строка {i}"

    def тексты(self, ids):
        return [self.text(int(i)) for i in ids]


@pytest.fixture
def стенд(monkeypatch):
    monkeypatch.setattr(nlindex, "запрет", lambda правила, idx: {"маска": None})
    monkeypatch.setattr(nlindex, "_правила", lambda: ())
    # `_строки` разворачивает номера в словари, читая колонки текста и рифмы —
    # их у стенда нет и не должно быть: сторож про ВОРОТА, а не про раскладку.
    monkeypatch.setattr(nlindex, "_строки",
                        lambda idx, ids, оц, пц: [{"text": idx.text(int(i)),
                                                   "clausula": int(idx.clau[int(i)])}
                                                  for i in ids])
    monkeypatch.setattr(nlindex, "_row",
                        lambda idx, i, score, pctl, light=False: {
                            "text": idx.text(int(i)),
                            "clausula": int(idx.clau[int(i)])})
    return _Идх()


def _классика(идх, маска):
    пул = np.ones(идх.n, dtype=bool)
    скрыт = np.zeros(идх.n, dtype=bool)
    строки, выжило, _ = nlindex.select_light(
        идх, pool_mask=пул, hidden_mask=скрыт, no_mat=False, only_mat=False,
        clausula=маска, cap=10, seed=1, внутр_рифма=0)
    return строки, выжило


def test_любая_клаузула_не_обнуляет_классику(стенд):
    """Маска 7 — «любая». Прежний код сравнивал `clau == 7` и отдавал ноль."""
    строки, выжило = _классика(стенд, 7)
    assert выжило == 6, "«любая» обязана пропускать все концовки"
    assert len(строки) == 6


def test_классика_режет_ровно_выбранные_концовки(стенд):
    for маска, ждём in ((1, {1}), (2, {2}), (4, {3}), (5, {1, 3}), (3, {1, 2})):
        строки, выжило = _классика(стенд, маска)
        вышло = {r["clausula"] for r in строки}
        assert вышло == ждём, f"маска {маска}: вышли {вышло}, ждали {ждём}"
        assert выжило == len(ждём) * 2


def test_ноль_как_старая_любая(стенд):
    """Старые сохранённые настройки несут 0 («любая» до масок) — он обязан
    вести себя как 7, а не резать всё подчистую."""
    _, выжило = _классика(стенд, 0)
    assert выжило == 6
