#!/usr/bin/env python3
# extendo — build the wordform table (OFFLINE, one-time). For every lemma in
# the ACTUAL runtime vocabulary — generate._vocab(), which merges the hand-
# tagged SEED lists with the open core/data/lexicon.json pool — enumerates
# only the grammeme combos the generator's templates can produce (targeted,
# not the full paradigm), inflects each via pymorphy3 and stresses it via
# ruaccent, and writes core/data/forms.json:
#   {"nouns": {lemma: {"g": gender, "a": animacy, "f": {grammeme_key: [surface, stress_idx]}}},
#    "adjs":  {lemma: {"f": {...}}},
#    "verbs": {lemma: {"f": {...}}}}
#
# Building from generate._vocab() (not lexicon.json alone) matters: a SEED
# word added straight into generate.py (e.g. for a new theme) has no forms
# until this rerenders — reading the SAME merge the runtime uses means adding
# a SEED word and rerunning this script is enough; nothing to keep in sync by
# hand. This bakes inflection AND stress into one lookup so the runtime
# generator never calls pymorphy3 or ruaccent — every draw is a dict lookup.
# ruaccent is a BUILD dependency only (`pip install ruaccent`), not a runtime one.

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import pymorphy3  # noqa: E402
import generate  # noqa: E402  (the source of truth for the runtime vocabulary)
from _accent import stress_index  # noqa: E402  (shared with build_nl_rhyme.py)

VOWELS = "аеёиоуыэюя"
OUT = ROOT / "core" / "data" / "forms.json"

# exactly the grammeme combinations generate.py's _noun/_adj/_verb_past need.
NOUN_GRAMMEMES = [{"nomn", "sing"}, {"nomn", "plur"}, {"loct", "sing"},
                  {"ablt", "sing"}, {"accs", "sing"}, {"gent", "sing"}]
_ADJ_CASES_SING = ("loct", "ablt", "gent")
_GENDERS = ("masc", "femn", "neut")


def adj_grammemes():
    combos = [{"nomn", "plur"}]
    combos += [{"nomn", "sing", g} for g in _GENDERS]
    for case in _ADJ_CASES_SING:
        combos += [{case, "sing", g} for g in _GENDERS]
    combos += [{"accs", "sing", "masc", "anim"}, {"accs", "sing", "masc", "inan"}]
    combos += [{"accs", "sing", g} for g in ("femn", "neut")]
    return combos


VERB_GRAMMEMES = [{"past", g} for g in (*_GENDERS, "plur")]


def gkey(grammemes: set[str]) -> str:
    return "|".join(sorted(grammemes))


def stress_of(acc, word: str) -> int:
    """Stress index for a surface form: ruaccent, falling back to `ё` (always
    stressed) or a lone vowel — the same graceful chain the old runtime used,
    now applied once at build time instead of per request."""
    try:
        idx = stress_index(acc.process_all(word))
        if idx is not None:
            return idx
    except Exception:
        pass
    e = word.find("ё")
    if e != -1:
        return sum(1 for ch in word[:e] if ch in VOWELS)
    return 0 if sum(1 for ch in word if ch in VOWELS) == 1 else -1


def main() -> int:
    morph = pymorphy3.MorphAnalyzer()
    vocab = generate._vocab()   # SEED + open lexicon, merged — the actual runtime pool

    from ruaccent import RUAccent
    acc = RUAccent()
    acc.load(omograph_model_size="turbo3.1", use_dictionary=True, tiny_mode=False)

    t0 = time.time()
    n_forms = 0

    def build_group(lemmas, pos, combos, with_gender=False):
        nonlocal n_forms
        out = {}
        for lemma, _tags in lemmas:
            parses = morph.parse(lemma)
            p = next((x for x in parses if x.tag.POS == pos), parses[0])
            entry = {"f": {}}
            if with_gender:
                entry["g"] = p.tag.gender or "masc"
                entry["a"] = "anim" if p.tag.animacy == "anim" else "inan"
            for g in combos:
                infl = p.inflect(g)
                if not infl:
                    continue
                w = infl.word.lower()
                entry["f"][gkey(g)] = [w, stress_of(acc, w)]
                n_forms += 1
            if entry["f"]:
                out[lemma] = entry
            if len(out) % 5000 == 0 and len(out):
                dt = time.time() - t0
                print(f"  {pos}: {len(out)}/{len(lemmas)} lemmas, {n_forms} forms "
                      f"({dt:.0f}s, {dt / n_forms * 1000:.2f} ms/form)")
        return out

    result = {
        "nouns": build_group(vocab["nouns"], "NOUN", NOUN_GRAMMEMES, with_gender=True),
        "adjs": build_group(vocab["adjs"], "ADJF", adj_grammemes()),
        "verbs": build_group(vocab["verbs"], "INFN", VERB_GRAMMEMES),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=0), "utf-8")
    dt = time.time() - t0
    print(f"wrote {sum(len(v) for v in result.values())} lemmas, {n_forms} forms "
          f"in {dt:.0f}s -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
