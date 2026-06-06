# nakedlunch 1.0.0
# Copyright (c) 2026 Шамаев Илья Сергеевич (Yala, @yalayoloyellow). Personal use only.

"""
Тесты нарезки (cutter).

Запуск:
  python -m pytest tests/test_cutter.py -q
  или просто python tests/test_cutter.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.cutter import cut_into_fragments


def test_city_example_has_expected_ragged_fragments():
    text = "В этом городе даже воздух продаётся. Каждый глоток — это чей-то чужой счёт. Люди ходят по улицам, как по минному полю."
    frags = cut_into_fragments(text)

    needles = [
        "В этом городе даже воздух продаётся",
        "Каждый глоток — это чей-то чужой счёт",
        "Люди ходят по улицам",
        "как по минному полю",
        "даже воздух продаётся. Каждый глоток",
    ]
    for n in needles:
        assert any(n in f for f in frags), f"expected fragment missing: {n}"

    # должны быть "грязные"
    assert any("гроде даже воздух" in f or "воздух продаётся. Каждый" in f for f in frags)
    assert len(frags) >= 8


def test_short_text_produces_something():
    frags = cut_into_fragments("Приказ сверху. Кровь на руках.")
    assert len(frags) >= 2
    assert all(len(f.split()) >= 2 for f in frags)


def test_deterministic():
    t = "Случай на улице. Шёл человек. Навстречу ему другой человек."
    a = cut_into_fragments(t)
    b = cut_into_fragments(t)
    assert a == b


def test_poetry_and_prose_same_rules():
    prose = "В этом городе даже воздух продаётся. Каждый глоток."
    poetry = "В этом городе\nдаже воздух продаётся.\n\nКаждый глоток."
    fp = cut_into_fragments(prose)
    ft = cut_into_fragments(poetry)
    # не обязательно идентично, но должны быть похожие обрывки
    assert len(fp) >= 3 and len(ft) >= 3


if __name__ == "__main__":
    # простой раннер без pytest
    tests = [test_city_example_has_expected_ragged_fragments, test_short_text_produces_something,
             test_deterministic, test_poetry_and_prose_same_rules]
    for t in tests:
        try:
            t()
            print(f"✓ {t.__name__}")
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            sys.exit(1)
    print("all cutter tests passed")
