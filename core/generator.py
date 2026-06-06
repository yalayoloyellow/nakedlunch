# nakedlunch 1.0.1
# Copyright (c) 2026 Шамаев Илья Сергеевич (Yala, @yalayoloyellow). Personal use only.

"""
Generator: выдача 4 рваных строк.

- Нейтральный режим: 4 случайные из пула.
- Режим с толчком (bias): 3 семантически близкие + 1 полностью случайная (дикая).
  После выдачи влияние толчка сбрасывается снаружи (в store/chat логике).
- Лёгкий скоринг на пересечении токенов (без тяжёлых моделей).
- Детерминизм для тестов: можно передать rng.
"""

from __future__ import annotations

import random
import re
from typing import List, Optional, Tuple


def _tokens(s: str) -> set[str]:
    """Простые токены: слова + кириллица."""
    return set(re.findall(r"[a-zа-яё0-9]+", s.lower()))

tokens = _tokens  # for import in store for precompute


def _score(frag: str, bias: str) -> float:
    if not bias or not bias.strip():
        return 0.0
    b = bias.lower().strip()
    f = frag.lower()
    bt = _tokens(bias)
    ft = _tokens(frag)
    if not bt or not ft:
        return 0.0

    inter = len(bt & ft)

    # stronger substring / contains boost for semantic "vibe" (e.g. "война" matches "военный", "кровь" etc.)
    if b and b in f:
        inter += 3.0
    for bw in bt:
        if bw and bw in f:
            inter += 1.5
        for fw in ft:
            if bw and (bw in fw or fw in bw):
                inter += 1.0

    # bonus for number of matched tokens (density)
    matched_count = sum(1 for bw in bt if any(bw in fw or fw in bw for fw in ft))
    inter += matched_count * 0.8

    # penalize very long fragments a bit
    return inter / (1.0 + 0.15 * len(ft))


def _weighted_sample(items: List[str], scores: List[float], k: int, rng: random.Random) -> List[str]:
    """Pick k items with probability proportional to score (higher = much more likely)."""
    if not items:
        return []
    if len(items) <= k:
        return list(items)
    # emphasize differences
    weights = [max(0.0001, s) ** 2.5 for s in scores]
    total = sum(weights)
    if total <= 0:
        return rng.sample(items, k)
    chosen: List[str] = []
    for _ in range(k):
        r = rng.random() * total
        cum = 0.0
        picked = False
        for idx, w in enumerate(weights):
            cum += w
            item = items[idx]
            if cum >= r and item not in chosen:
                chosen.append(item)
                picked = True
                break
        if not picked:
            for item in items:
                if item not in chosen:
                    chosen.append(item)
                    break
    return chosen


def generate_four(
    pool: List[str],
    bias: Optional[str] = None,
    *,
    rng: Optional[random.Random] = None,
) -> List[str]:
    if not pool:
        return ["(пустой пул — загрузите тексты)"] * 4

    if rng is None:
        rng = random.Random()

    n = len(pool)
    if n < 4:
        lines = (pool * ((4 // n) + 1))[:4]
        rng.shuffle(lines)
        return lines

    bias = (bias or "").strip()
    if not bias:
        lines = rng.sample(pool, 4)
        return lines

    # === Режим с семантическим толчком ===
    wild = rng.choice(pool)

    # Score everything
    scored: List[Tuple[str, float]] = [(f, _score(f, bias)) for f in pool]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Take the *best* matches (top N). This is key for large corpora:
    # even if absolute scores are small, we focus on relatively best hits for the bias.
    top_n = min(50, len(scored))
    top_scored = scored[:top_n]
    relevant = [f for f, s in top_scored]
    rel_scores = [s for f, s in top_scored]

    # Weighted pick 3 favoring the highest scoring (much more "sensitive")
    sem3 = _weighted_sample(relevant, rel_scores, 3, rng)

    four = list(sem3) + [wild]
    while len(four) < 4:
        extra = rng.choice(pool)
        if extra not in four:
            four.append(extra)
    rng.shuffle(four)
    return four[:4]


def is_semantic_line(frag: str, bias: str) -> bool:
    """Для тестов/отладки: имеет ли строка ненулевое пересечение с bias."""
    return _score(frag, bias) > 0.0


def generate_four_from_scored(
    scored: List[Tuple[str, float]],
    pool_for_wild: List[str],
    rng: Optional[random.Random] = None,
) -> List[str]:
    """Optimized bias generation when pre-scored list (with precomputed tokens) is provided.
    Avoids re-scoring in hot loop.
    """
    if not scored:
        if not pool_for_wild:
            return ["(пустой пул — загрузите тексты)"] * 4
        if rng is None:
            rng = random.Random()
        n = len(pool_for_wild)
        if n < 4:
            lines = (pool_for_wild * ((4 // n) + 1))[:4]
            rng.shuffle(lines)
            return lines
        return rng.sample(pool_for_wild, 4)

    if rng is None:
        rng = random.Random()

    # ensure sorted desc by score
    scored = sorted(scored, key=lambda x: x[1], reverse=True)

    top_n = min(50, len(scored))
    top_scored = scored[:top_n]
    relevant = [f for f, s in top_scored]
    rel_scores = [s for f, s in top_scored]

    sem3 = _weighted_sample(relevant, rel_scores, 3, rng)

    wild = rng.choice(pool_for_wild) if pool_for_wild else ""
    four = list(sem3) + [wild]
    seen = set(four)
    while len(four) < 4 and pool_for_wild:
        extra = rng.choice(pool_for_wild)
        if extra not in seen:
            four.append(extra)
            seen.add(extra)
    rng.shuffle(four)
    return four[:4]
