# extendo — scan a line's sound: syllables, meter, rhyme. Reads the stress each
# Word already carries (authored in the lexicon), so no external stress engine is
# needed for this controlled vocabulary. Pure, no I/O, no external data.
#
# Russian syllabo-tonic verse: a line reads "metrical" when its stresses fall at
# a regular interval (binary = iamb/trochee, ternary = dactyl/amphibrach/anapest).
# We fit the line's actual stressed-syllable positions to the best regular meter
# and score the agreement. Monosyllabic content words carry a flexible ictus, so
# they count for neither side — matching how such words scan in real verse.

from __future__ import annotations

from dataclasses import dataclass

VOWELS = "аеёиоуыэюя"

# unstressed vowel reduction (аканье/иканье) — enough to make rhyme keys match
# by ear, not a full phonetic transcription.
_REDUCE = str.maketrans({"о": "а", "е": "и", "я": "и", "ё": "о", "ю": "у", "э": "и"})
# final-consonant devoicing for the rhyme tail
_DEVOICE = {"б": "п", "в": "ф", "г": "к", "д": "т", "ж": "ш", "з": "с"}


def _no_yo(key: str) -> str:
    """Ударная ё в ключе — это тот же звук /о/, что и ударная о (Раунд 33,
    2026-08-02). _REDUCE давно сводит ё→о в ЗАУДАРНОЙ части, но ударная
    оставалась как есть, и ключ врал в обе стороны сразу:

      «свет» и «идёт» получали один ключ «ет» и выдавались как рифма —
      а /svʲet/ и /ɪdʲot/ не рифмуются вовсе;
      «идёт» и «поворот» получали «ёт» и «от» и рифмой НЕ считались —
      хотя это обычная мужская рифма.

    После правки инвариант простой: ключ рифмы НИКОГДА не содержит ё.
    Мягкость предыдущей согласной ключ и так не различает — она и не
    обязана: «мёд/год», «лёд/поворот» русская рифма принимает."""
    return key.replace("ё", "о") if "ё" in key else key


@dataclass
class Scan:
    syllables: int
    stresses: tuple[int, ...]   # syllable indices (0-based over the whole line) that are stressed
    flex: tuple[int, ...]       # syllable indices with a flexible ictus (monosyllabic content words)
    meter: float                # 0..1 metricality
    rhyme: str                  # normalized rhyme tail of the last content word
    rhyme_span: tuple[int, int] | None = None  # (start, end) of the RAW tail in Line.text, for highlighting


def _vowel_positions(word: str) -> list[int]:
    return [i for i, ch in enumerate(word) if ch in VOWELS]


def _line_pattern(words) -> tuple[int, list[int], list[int]]:
    """Walk the line, assigning each syllable a global index. Return
    (total_syllables, stressed_indices, flexible_indices)."""
    total = 0
    stressed: list[int] = []
    flex: list[int] = []
    for w in words:
        vp = _vowel_positions(w.surface)
        nsyl = len(vp)
        if nsyl == 0:            # e.g. preposition "в" — no syllable
            continue
        content = w.pos in ("NOUN", "ADJF", "VERB")
        if content and nsyl == 1:
            flex.append(total)   # single-syllable content word: flexible ictus
        elif w.stress >= 0 and w.stress < nsyl:
            stressed.append(total + w.stress)
        total += nsyl
    return total, stressed, flex


def _metricality(total: int, stressed: list[int], flex: list[int]) -> float:
    """Best fit of the stressed positions to a regular meter. Reward stresses on
    the beat, punish stresses off the beat; flexible syllables are neutral."""
    if total < 2 or not stressed:
        return 0.0
    stress_set = set(stressed)
    best = 0.0
    for step in (2, 3):
        for offset in range(step):
            beats = set(range(offset, total, step))
            on = len(stress_set & beats)
            off = len(stress_set - beats)
            # normalize by how many real (non-flexible) stresses there are
            denom = len(stressed) or 1
            score = (on - off) / denom
            best = max(best, score)
    # a stress collision (adjacent stressed syllables) always reads badly
    collision = any((i + 1) in stress_set for i in stress_set)
    if collision:
        best -= 0.34
    return max(0.0, min(1.0, best))


def rhyme_key(surface: str, stress_vowel_idx: int) -> str:
    """Rhyme key for a single word: from its stressed vowel to the end, with
    unstressed vowels reduced and the final consonant devoiced. Two words
    rhyme when keys match. Shared by _rhyme_tail (generated Word objects,
    stress known from core/data/forms.json) and tools/build_nl_rhyme.py
    (real nakedlunch text, stress from ruaccent — the generator's own lexicon
    never covers arbitrary prose, so that path needs its own stress source,
    but the key FORMAT must stay identical or the two would never match)."""
    vp = _vowel_positions(surface)
    if not vp or stress_vowel_idx < 0 or stress_vowel_idx >= len(vp):
        return _no_yo(surface[-3:])
    tail = surface[vp[stress_vowel_idx]:]
    # reduce only the vowels AFTER the stressed one (the stressed vowel stays)
    head, rest = tail[0], tail[1:].translate(_REDUCE)
    key = head + rest
    if key and key[-1] in _DEVOICE:
        key = key[:-1] + _DEVOICE[key[-1]]
    return _no_yo(key)


def clausula(key: str) -> int:
    """Тип окончания по рифмо-ключу: 1 — мужское (ударение на последнем слоге),
    2 — женское, 3 — дактилическое и дальше.

    Считать нечего и негде: ключ ПО ОПРЕДЕЛЕНИЮ начинается с ударной гласной и
    идёт до конца слова (см. rhyme_key), значит число гласных в нём и есть
    номер слога от конца. Отдельного разбора ударений не нужно, и для
    2.87 млн фрагментов это важно — ключи уже посчитаны на сборке.

    Замер трёх референсных текстов пользователя (2026-08-03): женская клаузула
    77% / 93% / 100%. Самый устойчивый признак его поэтики из всех, что
    удалось померить, — и до этого раунда машина им не управляла вовсе.
    """
    n = sum(1 for ch in key if ch in VOWELS)
    return min(3, n) if n else 0


def _rhyme_tail(words) -> tuple[str, tuple[int, int] | None]:
    """Rhyme key of the last content word in a generated line (see
    rhyme_key), plus its RAW character range in the joined line text
    (Line.text == ' '.join(w.surface for w in words)) so the UI can bold+
    color the actual substring driving the match instead of only showing the
    abstract (reduced/devoiced) key off to the side. User's own proposed
    fix for chasing rhyme bugs (2026-07-14): "если жирным раскрасить ударную
    рифму — сразу видно, где проблема" — a key alone hid exactly the kind of
    mismatch he spotted by eye once it was in the actual rendered line.
    key and the raw tail always have the SAME LENGTH (reduction/devoicing in
    rhyme_key is char-for-char, never changes length), so the highlight span
    is just the last len(key) characters of the word's own position."""
    content_idx = [i for i, w in enumerate(words) if w.pos in ("NOUN", "ADJF", "VERB")]
    if not content_idx:
        return "", None
    i = content_idx[-1]
    w = words[i]
    key = rhyme_key(w.surface, w.stress)
    if not key:
        return key, None
    offset = sum(len(ww.surface) + 1 for ww in words[:i])   # +1 for the joining space
    end = offset + len(w.surface)
    return key, (end - len(key), end)


def scan(line) -> Scan:
    total, stressed, flex = _line_pattern(line.words)
    rhyme, rhyme_span = _rhyme_tail(line.words)
    return Scan(
        syllables=total,
        stresses=tuple(stressed),
        flex=tuple(flex),
        meter=_metricality(total, stressed, flex),
        rhyme=rhyme,
        rhyme_span=rhyme_span,
    )
