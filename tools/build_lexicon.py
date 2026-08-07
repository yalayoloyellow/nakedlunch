#!/usr/bin/env python3
# extendo — build the open vocabulary (OFFLINE, one-time). Pulls the most
# frequently used Russian wordforms from wordfreq (aggregated counts, license-
# clean — invariant #3), lemmatizes with pymorphy3, keeps NOUN/ADJF/INFN, drops
# proper nouns and junk. Writes core/data/lexicon.json = {nouns, adjs, verbs},
# each a [lemma, zipf] list sorted by frequency.
#
# Rerun when you want to grow/refresh the open vocabulary. wordfreq is already a
# runtime dependency (used by filters.py for banality), so this adds no new
# runtime dependency.

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import pymorphy3  # noqa: E402
from wordfreq import top_n_list, zipf_frequency  # noqa: E402

OUT = ROOT / "core" / "data" / "lexicon.json"
DEPTH = 300_000     # wordforms to scan (wordfreq's Russian list tops out ~713k, but
                     # quality collapses well before that)
ZIPF_FLOOR = 2.2    # "most frequently used" — cuts rare/noisy tail
JUNK_RE = re.compile(r"[^а-яё-]")           # only Cyrillic + hyphen (compounds)
PROPER_GRAMMEMES = {"Name", "Surn", "Patr", "Geox", "Orgn", "Trad"}


def keep(lemma: str, tag) -> bool:
    if len(lemma) < 3 or JUNK_RE.search(lemma):
        return False
    return not (PROPER_GRAMMEMES & set(str(tag).replace(",", " ").split()))


def main() -> int:
    morph = pymorphy3.MorphAnalyzer()
    t0 = time.time()
    words = top_n_list("ru", DEPTH)
    print(f"wordfreq: {len(words)} wordforms in {time.time() - t0:.1f}s")

    best = {"NOUN": {}, "ADJF": {}, "INFN": {}}
    for w in words:
        z = zipf_frequency(w, "ru")
        if z < ZIPF_FLOOR:
            continue
        if not morph.word_is_known(w):    # OOV guesses misparse foreign names as
            continue                       # plain nouns (e.g. 'эскобар' → NOUN) — skip
        p = morph.parse(w)[0]
        pos = p.tag.POS
        if pos not in best:
            continue
        lemma = p.normal_form
        if not keep(lemma, p.tag):
            continue
        if z > best[pos].get(lemma, -1):
            best[pos][lemma] = z

    out = {
        "nouns": sorted(best["NOUN"].items(), key=lambda kv: -kv[1]),
        "adjs": sorted(best["ADJF"].items(), key=lambda kv: -kv[1]),
        "verbs": sorted(best["INFN"].items(), key=lambda kv: -kv[1]),
    }
    for k, v in out.items():
        print(f"{k}: {len(v)} lemmas")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0), "utf-8")
    print(f"wrote {sum(len(v) for v in out.values())} lemmas -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
