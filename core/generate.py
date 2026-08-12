# extendo — the cheap, dumb generator (project philosophy: dumb generator, smart
# filter). A slot grammar fills templates from a curated lemma palette. No
# neural net writes text (invariant #1). It emits thousands of candidates fast;
# scan.py + filters.py do the thinking.
#
# Agreement (gender/number/case/animacy) and stress are both baked offline into
# data/forms.json by tools/build_forms.py (pymorphy3 + ruaccent, once). The
# runtime never touches either library for INFLECTION — every draw is a dict
# lookup, so generation speed doesn't depend on vocabulary size. pymorphy3 is
# still used, lazily and cheaply, to lemmatize the handful of THEME WORDS per
# request (see _theme_pool) — that's a few words, not thousands of candidates.
# Growing the vocabulary = rerun tools/build_lexicon.py then tools/build_forms.py.

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import accumulate

from corpus import lemmatize
import пути               # где что лежит, см. core/пути.py


@dataclass
class Word:
    surface: str
    stress: int          # index of the stressed vowel among this word's vowels; -1 if unstressed (function word)
    pos: str             # NOUN | ADJF | VERB | PREP | CONJ
    lemma: str = ""      # normal form (for the corpus-distance filter); defaults to surface

    def __post_init__(self):
        if not self.lemma:
            self.lemma = self.surface


@dataclass
class Line:
    words: list[Word]
    template: str
    text: str = field(default="")

    def __post_init__(self):
        if not self.text:
            self.text = " ".join(w.surface for w in self.words)


# ---------------------------------------------------------------------------
# Lexicon = a small hand-tagged SEED (loose semantic fields, used to bias
# sampling toward the run's theme) merged with a large untagged OPEN pool
# (core/data/lexicon.json — the most frequently used Russian words, sourced
# from wordfreq's aggregated counts, built by tools/build_lexicon.py). The
# open pool is what gives real linguistic breadth; the seed is what gives
# thematic direction. Tags are hints, not hard categories (the "lego-cringe"
# question is exactly whether formal grammar without deep semantics still
# yields usable lines — see STATE.md).
#
# A SEED key MUST be pymorphy3's own normal_form for that lexeme, not just
# any natural-looking dictionary word (2026-07-18 — found while chasing a
# near-duplicate stanza bug: SEED had "деньги", but build_lexicon.py derives
# the OPEN pool's lemma via pymorphy3 too, and pymorphy3's normal_form for
# this lexeme is the archaic singular "деньга" — so the merge in _vocab()
# silently kept BOTH as separate entries, one tagged {"money"} (from SEED),
# one untagged (from OPEN). Two consequences: (1) a theme typed in any form
# OTHER than the exact SEED string ("деньгами", not "деньги") never matched
# the SEED tag at all, since _theme_pool only lemmatizes the TYPED tag, not
# the SEED keys; (2) two grammar-generated lines could both surface this
# word yet carry different Word.lemma strings, so the anti-repeat filters in
# filters.py (matched by lemma-set overlap) couldn't tell they were the same
# word. Confirmed 3 of the vocabulary's ~32k lemmas actually collided this
# way (деньги/деньга, губы/губа, родной/родный — checked directly against
# core/data/forms.json, not guessed); 2 more flagged by a naive normal_form
# diff (бит/битый, возбуждённый/возбудить) turned out NOT to collide — the
# OPEN pool never independently produced those forms, so "fixing" them would
# only have risked breaking their inflection for no gain. Renamed the 3 real
# collisions to their pymorphy3 lemma; inflecting FROM it verified to still
# produce the natural forms (деньга→деньги, губа→губы, родный→родная), and
# theme-matching now goes through the SAME lemmatize() path either way, so a
# typed theme in any inflected form matches, not just the one exact string
# the seed happened to be written in. core/data/forms.json rebuilt via
# tools/build_forms.py to pick up the merge.
# ---------------------------------------------------------------------------

SEED_NOUNS = [
    # night / dark
    ("ночь", {"night", "dark"}), ("тьма", {"night", "dark"}), ("тень", {"dark", "night"}),
    ("мрак", {"night", "dark"}), ("полночь", {"night"}), ("сон", {"night", "feel"}),
    # city / street
    ("город", {"city", "street"}), ("улица", {"city", "street"}), ("двор", {"city", "street"}),
    ("асфальт", {"street", "city"}), ("бетон", {"street", "city"}), ("окно", {"city"}),
    ("крыша", {"city", "sky"}), ("фонарь", {"city", "light", "night"}), ("район", {"city", "street"}),
    # cold / winter
    ("холод", {"cold"}), ("зима", {"cold", "time"}), ("лёд", {"cold"}),
    ("снег", {"cold", "sky"}), ("ветер", {"cold", "motion"}), ("метель", {"cold", "motion"}),
    # fire / light
    ("огонь", {"fire", "light"}), ("свет", {"light"}), ("пламя", {"fire"}),
    ("искра", {"fire", "light"}), ("дым", {"dark", "fire"}), ("пепел", {"fire", "dark"}),
    # body / blood
    ("сердце", {"body", "feel"}), ("кровь", {"body", "feel"}), ("рука", {"body", "motion"}),
    ("голос", {"speak", "sound"}), ("дыхание", {"body", "feel"}), ("кость", {"body"}),
    # soul / feeling
    ("душа", {"feel", "soul"}), ("боль", {"feel", "body"}), ("страх", {"feel"}),
    ("злость", {"feel"}), ("тоска", {"feel", "soul"}), ("мечта", {"feel", "soul"}),
    ("память", {"feel", "time"}),
    # sound / music
    ("бит", {"sound", "music"}), ("звук", {"sound", "music"}), ("слово", {"speak", "music"}),
    ("ритм", {"sound", "music"}), ("эхо", {"sound"}), ("тишина", {"sound", "dark"}),
    # motion / road
    ("дорога", {"motion", "street"}), ("путь", {"motion", "soul"}), ("шаг", {"motion"}),
    ("край", {"motion", "world"}), ("побег", {"motion", "feel"}),
    # time
    ("время", {"time"}), ("день", {"time", "light"}), ("год", {"time"}),
    ("миг", {"time"}), ("рассвет", {"time", "light"}), ("закат", {"time", "light"}),
    # money / power
    ("деньга", {"money"}), ("цена", {"money", "feel"}), ("долг", {"money", "soul"}),
    ("сила", {"power", "feel"}),
    # sky / water
    ("небо", {"sky", "night"}), ("звезда", {"sky", "night", "light"}), ("луна", {"sky", "night"}),
    ("дождь", {"cold", "sky"}), ("река", {"water", "motion"}), ("туман", {"water", "dark"}),
    # world / fate
    ("мир", {"world"}), ("судьба", {"world", "soul"}), ("свобода", {"world", "soul"}),
    ("война", {"world", "feel"}), ("правда", {"world", "soul"}),
    # desire / body (explicit register — same mechanism as any other theme)
    ("секс", {"desire", "body"}), ("похоть", {"desire"}), ("страсть", {"desire", "feel"}),
    ("жажда", {"desire", "feel"}), ("плоть", {"desire", "body"}), ("грудь", {"body", "desire"}),
    ("бедро", {"body", "desire"}), ("губа", {"body", "desire"}), ("кожа", {"body"}),
    ("пот", {"body"}), ("поцелуй", {"desire", "body"}), ("объятие", {"desire", "body"}),
    ("шлюха", {"desire", "crude"}), ("сука", {"crude", "feel"}),
]

# adjectives given in masc nomn; pymorphy3 re-agrees them to the head noun.
SEED_ADJS = [
    ("холодный", {"cold"}), ("тёмный", {"dark", "night"}), ("пустой", {"dark", "feel"}),
    ("чёрный", {"dark"}), ("живой", {"feel", "body"}), ("чужой", {"feel"}),
    ("бешеный", {"feel", "motion"}), ("новый", {"world"}), ("горячий", {"fire", "feel"}),
    ("светлый", {"light"}), ("ночной", {"night"}), ("городской", {"city", "street"}),
    ("немой", {"speak", "dark"}), ("слепой", {"dark", "feel"}), ("злой", {"feel"}),
    ("святой", {"soul"}), ("грязный", {"street", "dark"}), ("вечный", {"time", "soul"}),
    ("дикий", {"feel", "motion"}), ("гордый", {"feel", "soul"}), ("мёртвый", {"dark", "body"}),
    ("рваный", {"street", "feel"}), ("острый", {"feel"}), ("глухой", {"sound", "dark"}),
    ("далёкий", {"motion", "world"}), ("родный", {"feel", "soul"}), ("последний", {"time"}),
    ("голодный", {"feel", "body"}), ("пьяный", {"feel"}), ("свободный", {"soul", "world"}),
    ("ржавый", {"street", "dark"}), ("голый", {"body", "cold", "desire"}),
    ("страстный", {"desire", "feel"}), ("похотливый", {"desire"}), ("обнажённый", {"desire", "body"}),
    ("влажный", {"desire", "body"}), ("тесный", {"desire", "body"}), ("возбуждённый", {"desire", "feel"}),
]

# verbs given as infinitive; used mostly in past tense (agrees with subject).
SEED_VERBS = [
    ("гореть", {"fire", "light"}), ("молчать", {"speak", "dark"}), ("светить", {"light"}),
    ("дышать", {"body", "motion"}), ("звать", {"speak", "sound"}), ("жечь", {"fire"}),
    ("падать", {"motion"}), ("рваться", {"motion", "feel"}), ("стынуть", {"cold"}),
    ("звенеть", {"sound", "music"}), ("бежать", {"motion"}), ("кричать", {"speak", "feel"}),
    ("ждать", {"feel", "time"}), ("терять", {"feel", "soul"}), ("ломать", {"feel", "motion"}),
    ("гнать", {"motion", "feel"}), ("тонуть", {"water", "feel"}), ("лететь", {"motion", "sky"}),
    ("верить", {"soul", "feel"}), ("плакать", {"feel", "water"}), ("держать", {"body", "feel"}),
    ("расти", {"motion", "time"}), ("таять", {"cold", "water"}), ("стучать", {"sound", "body"}),
    ("гаснуть", {"light", "dark"}), ("зреть", {"time", "soul"}),
    ("хотеть", {"desire", "feel"}), ("желать", {"desire", "feel"}), ("целовать", {"desire", "body"}),
    ("стонать", {"desire", "body"}), ("дрожать", {"desire", "feel"}), ("обнимать", {"desire", "body"}),
    ("раздевать", {"desire", "body"}), ("трахать", {"desire", "crude"}), ("ебать", {"desire", "crude"}),
]

# prepositions with the case they govern (function words: no stress).
PREPS = [
    ("в", "loct"), ("на", "loct"), ("под", "ablt"),
    ("сквозь", "accs"), ("над", "ablt"), ("без", "gent"),
]

TEMPLATES = ("adj_noun", "adj_noun_verb", "noun_verb_prep_np",
             "verb_prep_np", "noun_and_noun", "prep_np_noun",
             "verb_prep_obryv", "kotory_obryvok", "sravnenie_obryv",
             "dva_glagola", "soyuz_nachalo", "dlinnaya_tsepochka")

# ragged/uneven shapes (2026-07-19, user: «нужно больше разнообразных
# всевозможных форм в том числе неровных как неровная обрезка в кат апе»).
# The first 6 templates are all grammatically CLOSED — complete noun phrases,
# complete clauses. Real cut-up text is the opposite: a slice cut at an
# arbitrary point, often starting or ending mid-thought. These 6 are
# deliberately OPEN-ended on one side — a dangling preposition with no
# object, a relative clause with no antecedent, a comparison with nothing to
# compare, two verbs slammed together with no "и" — plus one that just goes
# the other direction (`dlinnaya_tsepochka`, a longer 7-word double-predicate
# chain), for length variety alongside the raggedness. Same "dumb generator"
# contract as the original 6: each just returns None on a missing inflection,
# no different from any other template failing a draw.
_KOTORY = {("masc", "sing"): "который", ("femn", "sing"): "которая",
           ("neut", "sing"): "которое", ("plur", "plur"): "которые"}
_COMPARE = ("более", "менее")
_STARTERS = ("но", "а", "хотя", "зато")


# ---------------------------------------------------------------------------
# open vocabulary — the most frequently used Russian words (core/data/
# lexicon.json, built by tools/build_lexicon.py from wordfreq's aggregated
# counts), merged with the hand-tagged seed. Seed entries keep their tags;
# open-pool entries carry none — they give breadth, the seed gives direction.
# ---------------------------------------------------------------------------

LEXICON_PATH = пути.таблица("lexicon.json")


def _merge(seed: list[tuple[str, set]], open_lemmas: list[list]) -> list[tuple[str, frozenset]]:
    merged = {lemma: frozenset(tags) for lemma, tags in seed}
    for lemma, _zipf in open_lemmas:
        merged.setdefault(lemma, frozenset())
    return list(merged.items())


@lru_cache(maxsize=1)
def _vocab() -> dict:
    try:
        open_lex = json.loads(LEXICON_PATH.read_text("utf-8"))
    except OSError:
        open_lex = {"nouns": [], "adjs": [], "verbs": []}
    return {
        "nouns": _merge(SEED_NOUNS, open_lex["nouns"]),
        "adjs": _merge(SEED_ADJS, open_lex["adjs"]),
        "verbs": _merge(SEED_VERBS, open_lex["verbs"]),
    }


# ---------------------------------------------------------------------------
# forms — read from a prebuilt lemma→grammeme-combo→(surface, stress) table
# (tools/build_forms.py bakes inflection + stress together, offline, via
# pymorphy3 + ruaccent, once). Keying on the exact inflected form dissolves
# mobile stress (холода́) and homographs by construction. The runtime never
# calls pymorphy3 or ruaccent — every draw is a plain dict lookup, so
# generation speed is independent of vocabulary size.
# ---------------------------------------------------------------------------

FORMS_PATH = пути.таблица("forms.json")


@lru_cache(maxsize=1)
def _forms() -> dict:
    try:
        return json.loads(FORMS_PATH.read_text("utf-8"))
    except OSError:
        return {"nouns": {}, "adjs": {}, "verbs": {}}   # not built yet → templates just skip


def warm_caches() -> None:
    """Force-load the forms table at server startup (a JSON read + parse, well
    under a second) instead of on the first request, so every /api/generate is
    fast from the very first call, not just the second one."""
    _forms()


def vocab_size() -> int:
    """How many unique lemmas the generator draws from — the honest 'pool' the
    grammar pipeline samples candidate lines out of, shown in the funnel
    infographic (2026-07-14, user: counters must say from how many things
    each pipeline actually picks). Re-added after Round 13 removed it as an
    n-formula input; here it's display-only, not wired into candidate count."""
    v = _vocab()
    return len(v["nouns"]) + len(v["adjs"]) + len(v["verbs"])


def _gkey(grammemes: set[str]) -> str:
    return "|".join(sorted(grammemes))


def _lookup(table: dict, lemma: str, grammemes: set[str], pos: str) -> Word | None:
    entry = table.get(lemma)
    if not entry:
        return None
    hit = entry["f"].get(_gkey(grammemes))
    if not hit:
        return None
    surface, stress = hit
    return Word(surface, stress, pos, lemma)


def _noun(lemma: str, case: str, number: str) -> Word | None:
    return _lookup(_forms()["nouns"], lemma, {case, number}, "NOUN")


def _noun_gender(lemma: str) -> str:
    e = _forms()["nouns"].get(lemma)
    return e["g"] if e else "masc"


def _noun_animacy(lemma: str) -> str:
    e = _forms()["nouns"].get(lemma)
    return e["a"] if e else "inan"


def _adj(lemma: str, case: str, number: str, gender: str, anim: str | None = None) -> Word | None:
    grammemes = {case, number} if number == "plur" else {case, number, gender}
    if case == "accs" and anim:            # accusative is animacy-sensitive: 'сквозь
        grammemes.add(anim)                # холодный город', not 'холодного город'
    return _lookup(_forms()["adjs"], lemma, grammemes, "ADJF")


def _verb_past(lemma: str, gender: str, number: str) -> Word | None:
    # Unlike nouns/adjs (whose stored keys always spell out "sing" explicitly
    # — see build_forms.py), past-tense verb forms are built keyed by GENDER
    # alone for singular ("masc|past", not "masc|past|sing" — gender already
    # implies singular in Russian past tense; plural has no gender, hence
    # "past|plur"). Including "sing" here made every singular lookup miss the
    # table entirely (found 2026-07-19, user: generation reads monotonous,
    # "no more complex constructions with several parts of speech" — verified
    # live: adj_noun_verb/noun_verb_prep_np only succeeded on the 25% of
    # draws that happened to land on PLURAL by chance; verb_prep_np, always
    # singular, was 0/3375 — a fully dead template, not a design gap).
    grammemes = {"past", number} if number == "plur" else {"past", gender}
    return _lookup(_forms()["verbs"], lemma, grammemes, "VERB")


def _prep(word: str) -> Word:
    return Word(word, -1, "PREP")


def _conj(word: str) -> Word:
    return Word(word, -1, "CONJ")


# ---------------------------------------------------------------------------
# templates — each returns a Line or None (some inflections don't exist)
# ---------------------------------------------------------------------------

def _draw(rng: random.Random, tier: dict) -> str:
    """A word for one slot: with probability ON_THEME_P, from the small
    theme-anchored tier; otherwise, uniformly from the full open pool (breadth —
    "чувствовать объём"). A flat additive weight can't compete with a 19k-word
    tail (a 12x boost is ~0.06% of the mass there), so theme relevance has to
    come from a separate draw, not a bigger multiplier."""
    if tier["on"] and rng.random() < ON_THEME_P:
        return rng.choices(tier["on"], cum_weights=tier["on_w"], k=1)[0]
    return rng.choice(tier["full"])


def _build(name: str, rng: random.Random, pool) -> Line | None:
    noun = lambda: _draw(rng, pool["nouns"])
    adj = lambda: _draw(rng, pool["adjs"])
    verb = lambda: _draw(rng, pool["verbs"])
    number = "plur" if rng.random() < 0.25 else "sing"

    if name == "adj_noun":
        nl = noun()
        g = _noun_gender(nl)
        a = _adj(adj(), "nomn", number, g)
        n = _noun(nl, "nomn", number)
        if a and n:
            return Line([a, n], name)

    elif name == "adj_noun_verb":
        nl = noun()
        g = _noun_gender(nl)
        a = _adj(adj(), "nomn", number, g)
        n = _noun(nl, "nomn", number)
        v = _verb_past(verb(), g, number)
        if a and n and v:
            return Line([a, n, v], name)

    elif name == "noun_verb_prep_np":
        subj_l = noun()
        g = _noun_gender(subj_l)
        subj = _noun(subj_l, "nomn", number)
        v = _verb_past(verb(), g, number)
        pw, case = rng.choice(PREPS)
        oc = noun()
        oa = _adj(adj(), case, "sing", _noun_gender(oc), _noun_animacy(oc))
        on = _noun(oc, case, "sing")
        if subj and v and oa and on:
            return Line([subj, v, _prep(pw), oa, on], name)

    elif name == "verb_prep_np":
        v = _verb_past(verb(), rng.choice(("masc", "femn", "neut")), "sing")
        pw, case = rng.choice(PREPS)
        oc = noun()
        oa = _adj(adj(), case, "sing", _noun_gender(oc), _noun_animacy(oc))
        on = _noun(oc, case, "sing")
        if v and oa and on:
            return Line([v, _prep(pw), oa, on], name)

    elif name == "noun_and_noun":
        n1 = _noun(noun(), "nomn", "sing")
        n2 = _noun(noun(), "nomn", "sing")
        if n1 and n2 and n1.surface != n2.surface:
            return Line([n1, _conj("и"), n2], name)

    elif name == "prep_np_noun":
        pw, case = rng.choice(PREPS)
        hc = noun()
        ha = _adj(adj(), case, "sing", _noun_gender(hc), _noun_animacy(hc))
        hn = _noun(hc, case, "sing")
        gn = _noun(noun(), "gent", "sing")
        if ha and hn and gn:
            return Line([_prep(pw), ha, hn, gn], name)

    elif name == "verb_prep_obryv":
        # dangling preposition, no object at all — reads like the cut landed
        # mid-phrase ("падало из-за", "он повернулся среди").
        v = _verb_past(verb(), rng.choice(("masc", "femn", "neut")), "sing")
        pw, _case = rng.choice(PREPS)
        if v:
            return Line([v, _prep(pw)], name)

    elif name == "kotory_obryvok":
        # opens on a relative pronoun with no antecedent shown — reads like
        # a continuation of a sentence we never saw the start of.
        n2 = "plur" if rng.random() < 0.25 else "sing"
        g2 = rng.choice(("masc", "femn", "neut")) if n2 == "sing" else "plur"
        rel = _KOTORY[(g2, n2)]
        v = _verb_past(verb(), g2, n2)
        pw, case = rng.choice(PREPS)
        oc = noun()
        on = _noun(oc, case, "sing")
        if v and on:
            return Line([_conj(rel), v, _prep(pw), on], name)

    elif name == "sravnenie_obryv":
        # comparison with nothing on the other side of "чем" — the rhyme
        # word (the adjective) stays clean, only the trailing "чем" dangles.
        g = rng.choice(("masc", "femn", "neut"))
        a = _adj(adj(), "nomn", "sing", g)
        if a:
            return Line([_conj(rng.choice(_COMPARE)), a, _conj("чем")], name)

    elif name == "dva_glagola":
        # two verbs slammed together with no "и" — jagged rhythm instead of
        # the flat coordination noun_and_noun always produces. The comma
        # rides on the FIRST verb's surface, never the rhyme-bearing second.
        n2 = "plur" if rng.random() < 0.25 else "sing"
        g2 = rng.choice(("masc", "femn", "neut")) if n2 == "sing" else "plur"
        v1 = _verb_past(verb(), g2, n2)
        v2 = _verb_past(verb(), g2, n2)
        if v1 and v2:
            return Line([Word(v1.surface + ",", v1.stress, v1.pos, v1.lemma), v2], name)

    elif name == "soyuz_nachalo":
        # opens on a conjunction as if picking up a thought already in
        # progress ("но резкий дом", "а он влажный").
        nl = noun()
        g = _noun_gender(nl)
        a = _adj(adj(), "nomn", number, g)
        n = _noun(nl, "nomn", number)
        if a and n:
            return Line([_conj(rng.choice(_STARTERS)), a, n], name)

    elif name == "dlinnaya_tsepochka":
        # the OTHER direction from the ragged shapes above — a longer,
        # 7-word double-predicate chain (one subject, two verbs) for length
        # variety, not just raggedness.
        subj_l = noun()
        g = _noun_gender(subj_l)
        subj = _noun(subj_l, "nomn", number)
        v1 = _verb_past(verb(), g, number)
        pw, case = rng.choice(PREPS)
        oc = noun()
        oa = _adj(adj(), case, "sing", _noun_gender(oc), _noun_animacy(oc))
        on = _noun(oc, case, "sing")
        v2 = _verb_past(verb(), g, number)
        if subj and v1 and oa and on and v2:
            return Line([subj, v1, _prep(pw), oa, on, _conj("и"), v2], name)

    return None


# ---------------------------------------------------------------------------
# public: generate candidates
# ---------------------------------------------------------------------------

ON_THEME_P = 0.6   # share of draws pulled from the theme-anchored tier (see _draw)


def _theme_pool(tags: list[str]) -> dict:
    """Two tiers per POS: a small theme-anchored 'on' tier (drawn ON_THEME_P of
    the time) and the full open pool (drawn uniformly the rest of the time, for
    breadth — "чувствовать объём языка"). A two-tier probability split is scale-
    independent, unlike an additive weight boost, which a ~19k-word tail simply
    outnumbers into irrelevance.

    Theme words are Russian (from clean.theme); the seed's tags are internal
    English category labels. A theme word activates a category by matching a
    SEED lemma exactly (Russian == Russian) — its tags become "active"; any seed
    word sharing an active category joins the 'on' tier. Any word anywhere
    (seed or open pool) whose OWN lemma is literally a theme word also joins it,
    weighted higher within that tier.

    Tags are lemmatized before matching (plus kept raw) — a theme word typed in
    an inflected form ('бляди') otherwise never matches its dictionary lemma
    ('блядь'), silently killing the whole theme-anchoring mechanism for any
    theme word that isn't already in its bare dictionary form."""
    tagset = set(tags)
    for t in tags:
        tagset.update(lemmatize(t))
    active = set()
    for lst in (SEED_NOUNS, SEED_ADJS, SEED_VERBS):
        for lemma, cats in lst:
            if lemma in tagset:
                active |= cats

    def build(entries):
        full = [lemma for lemma, _cats in entries]
        on_pop, on_w = [], []
        for lemma, cats in entries:
            if lemma in tagset:
                on_pop.append(lemma); on_w.append(3.0)
            elif cats & active:
                on_pop.append(lemma); on_w.append(1.0)
        return {"full": full, "on": on_pop,
                "on_w": list(accumulate(on_w)) if on_pop else None}

    return {"nouns": build(_vocab()["nouns"]), "adjs": build(_vocab()["adjs"]),
            "verbs": build(_vocab()["verbs"])}


def generate(tags: list[str], n: int = 2000, seed: int | None = None) -> list[Line]:
    """Return up to `n` unique candidate lines biased toward `tags`. Cheap and
    dumb by design — quality is the filters' job, not the generator's."""
    rng = random.Random(seed)
    pool = _theme_pool(tags)
    seen: set[str] = set()
    out: list[Line] = []
    attempts = 0
    cap = n * 12
    while len(out) < n and attempts < cap:
        attempts += 1
        line = _build(rng.choice(TEMPLATES), rng, pool)
        if line and line.text not in seen:
            seen.add(line.text)
            out.append(line)
    return out
