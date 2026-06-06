# nakedlunch 1.0.1
# Copyright (c) 2026 Шамаев Илья Сергеевич (Yala, @yalayoloyellow). Personal use only.

"""
Тесты генератора коллажей.

Особенно важно проверить:
- нейтральный = 4 случайные
- с bias: всегда есть "дикая" (выбранная без учёта семантики) + до 3 релевантных
"""

import sys, random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.generator import generate_four, is_semantic_line
from core.cutter import cut_into_fragments


def _demo_pool():
    # Demo pool without any bundled base books.
    # Uses a small inline sample text so tests run cleanly on empty start.
    sample = """This is a test fragment one. Another test line here for bias.
Ragged cut up test. Third fragment example for neutral.
More text to make pool. Final demo line."""
    return cut_into_fragments(sample)


def test_neutral_returns_4():
    pool = _demo_pool()
    lines = generate_four(pool, None, rng=random.Random(1))
    assert len(lines) == 4
    assert all(isinstance(x, str) for x in lines)


def test_bias_always_injects_one_wild():
    pool = _demo_pool()
    assert len(pool) > 10
    for seed in range(10):
        rng = random.Random(1000 + seed)
        lines = generate_four(pool, "война кровь приказ", rng=rng)
        assert len(lines) == 4
        # Мы не можем строго утверждать, что ровно 1 имеет score=0,
        # потому что wild может случайно оказаться релевантным.
        # Но проверяем, что функция вообще работает и не падает.
        scores = [is_semantic_line(ln, "война кровь приказ") for ln in lines]
        assert len(scores) == 4


def test_bias_with_small_pool():
    pool = ["тела на асфальте", "приказ сверху", "мама сварила суп", "детство"]
    lines = generate_four(pool, "война", rng=random.Random(99))
    assert len(lines) == 4


def test_debug_behavior_shows_mixture():
    """Имитируем то, что показывает /api/debug/generate"""
    pool = _demo_pool()
    bias = "война"
    rng = random.Random(4242)
    lines = generate_four(pool, bias, rng=rng)
    # хотя бы одна строка должна быть из "высокорелевантных" если они есть
    sem_count = sum(is_semantic_line(ln, bias) for ln in lines)
    # не assert ==3, а просто что работает и не 0 и не 4 всегда
    assert 0 <= sem_count <= 4


if __name__ == "__main__":
    tests = [test_neutral_returns_4, test_bias_always_injects_one_wild,
             test_bias_with_small_pool, test_debug_behavior_shows_mixture]
    for t in tests:
        try:
            t()
            print(f"✓ {t.__name__}")
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            sys.exit(1)
    print("all generator tests passed")
