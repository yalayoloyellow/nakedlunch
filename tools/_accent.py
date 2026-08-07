# extendo — shared ruaccent output parsing, used by both build_forms.py
# (generator's own lexicon) and build_nl_rhyme.py (nakedlunch fragments).
# One function, not two copies (PRINCIPLES.md #6) — the '+'-marker convention
# only needs to be right in one place.

VOWELS = "аеёиоуыэюя"


def stress_index(marked: str) -> int | None:
    """ruaccent marks the stressed vowel with '+' before it → vowel index."""
    if "+" not in marked:
        return None
    pos = marked.index("+")
    return sum(1 for ch in marked[:pos] if ch in VOWELS)
