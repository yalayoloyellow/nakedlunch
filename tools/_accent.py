# extendo — разбор вывода ruaccent. Писался общим на две печки: build_forms.py
# (словарь генератора) и build_nl_rhyme.py (фрагменты корпуса). Первая снесена
# 2026-09-02 вместе с генератором, и звавший остался один — но правило разбора
# метки «+» от этого не изменилось, а перенос его внутрь единственного
# читателя стоил бы правки без выигрыша.

VOWELS = "аеёиоуыэюя"


def stress_index(marked: str) -> int | None:
    """ruaccent marks the stressed vowel with '+' before it → vowel index."""
    if "+" not in marked:
        return None
    pos = marked.index("+")
    return sum(1 for ch in marked[:pos] if ch in VOWELS)
