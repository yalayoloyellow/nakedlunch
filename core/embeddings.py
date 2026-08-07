# extendo — semantic theme relevance via static Russian word vectors (navec,
# natasha project, MIT: https://github.com/natasha/navec). Built 2026-07-17 to
# fix theme stuffing: user typed "деньги" and got it back literally in 19 of
# 20 lines (core/filters.py._nl_scored used to score a fragment 0.6+1 for
# containing the LITERAL theme word and 0.6+0 for everything else — with
# hundreds of literal matches in a 274k-fragment pool, they filled the
# shortlist almost entirely). User: "может не встречаться напрямую даже, но
# всё равно явно захватывать запрошенную тему" — a fragment should rank by
# whether it carries the theme's MEANING, not whether it contains its exact
# spelling. See PLAN.md 0.2 for the full decision record.
#
# ONE dependency: numpy (already transitive via pymorphy3/wordfreq) — no
# torch. A spike (PLAN.md, "torch проверен и отвергнут ПО ИЗМЕРЕНИЮ") found a
# 560M-parameter sentence encoder gave NO better signal than this 51MB
# word-vector model for the OTHER embeddings use (favorites clustering) —
# same reasoning applies here: word-level cosine is the right-shaped tool for
# "which words belong near this theme," not a heavier one.
#
# Model file is a build artifact like core/data/forms.json/nl_rhyme.json —
# committed, loaded once at server startup (see warm_caches, called from
# api/server.py). Re-fetch if missing: the official natasha release,
# navec_hudlit_v1_12B_500K_300d_100q.tar (~51MB, MIT), from
# https://github.com/natasha/navec — save as core/data/navec.tar.

from __future__ import annotations

from pathlib import Path

import numpy as np

import пути

_MODEL_PATH = пути.таблица("navec.tar")

_vectors: np.ndarray | None = None
_index: dict[str, int] | None = None
_load_attempted = False


def warm_caches() -> None:
    """Load the model once at server startup so the first themed request
    isn't the one paying the ~0.3s load cost. Best-effort — a missing or
    unreadable model file just means themed runs fall back to literal-only
    matching (_ensure_loaded returns False every time, cheaply)."""
    _ensure_loaded()


def _ensure_loaded() -> bool:
    global _vectors, _index, _load_attempted
    if _vectors is not None:
        return True
    if _load_attempted:
        return False
    _load_attempted = True
    if not _MODEL_PATH.exists():
        return False
    try:
        from navec import Navec
        nav = Navec.load(str(_MODEL_PATH))
        raw = nav.pq.unpack()
        norms = np.linalg.norm(raw, axis=1)
        _vectors = raw / np.clip(norms[:, None], 1e-9, None)
        _index = {w: i for i, w in enumerate(nav.vocab.words)}
        return True
    except Exception:
        return False


def theme_vector(tags: list[str]) -> np.ndarray | None:
    """Normalized centroid of the theme's own word vectors — the 'meaning' a
    fragment gets scored against. Tries each tag as TYPED first (navec's
    vocab already carries common inflected/plural forms — 'деньги' hits
    directly and gives a better-centered vector than its pymorphy3 lemma
    'деньга', a rarer singular), lemma as fallback for anything typed in an
    unusual form. None if the model isn't loaded or no tag word is known —
    an unfamiliar theme just gets no semantic boost, not an error (see
    filters._nl_scored's literal-only fallback when this is None)."""
    if not _ensure_loaded() or not tags:
        return None
    from corpus import lemmatize
    vecs = []
    for t in tags:
        t = t.strip().lower()
        if t in _index:
            vecs.append(_vectors[_index[t]])
            continue
        for lemma in lemmatize(t):
            if lemma in _index:
                vecs.append(_vectors[_index[lemma]])
                break
    if not vecs:
        return None
    centroid = np.mean(vecs, axis=0)
    norm = np.linalg.norm(centroid)
    return centroid / norm if norm > 1e-9 else None


def theme_similarities(theme_vec):
    """cosine(word, theme) for the WHOLE vocabulary, ONE batched matmul — call
    once per request (see filters.run), not once per fragment. The first cut
    of `relevance()` computed a fresh 300-dim dot product per WORD inside
    core/filters.py:_nl_scored's per-fragment loop — ~150k fragments × ~4
    content words each is ~600k individual numpy calls, measured costing
    ~300-450ms on top of the historical ~700ms baseline (an unthemed request
    doesn't touch this path at all and stayed at baseline, isolating the
    cost). A single (500k×300)·(300,) matmul is sub-10ms; `relevance()` then
    does cheap array indexing instead of recomputing anything."""
    if theme_vec is None or _vectors is None:
        return None
    return _vectors @ theme_vec


def lemma_centroid(lemmas):
    """Normalized centroid of a LINE's own content-word vectors — the line's
    'meaning point', comparable to another line's via a plain dot product
    (both unit-length). Built 2026-07-18 for the anchor mechanism
    (core/filters.py: _select_with_rhyme): the no-repeat rule already bans
    sharing a LEMMA with the stanza's anchor line, but two lines can be
    near-copies without sharing a single lemma ('деньги пропали' / 'бабки
    исчезли') — the user's rule is "ни одна строка не должна быть похожа на
    константную", and 'похожа' needs a meaning-level check, not a
    spelling-level one. None if the model isn't loaded or no lemma is in
    vocabulary — callers must treat that as 'no opinion', never as
    'similar' or 'distinct'."""
    if not _ensure_loaded() or not lemmas:
        return None
    vecs = [_vectors[_index[w]] for w in lemmas if w in _index]
    if not vecs:
        return None
    c = np.mean(vecs, axis=0)
    n = np.linalg.norm(c)
    return c / n if n > 1e-9 else None


def relevance(sims, lemmas) -> float:
    """How much of the theme's MEANING a line's content words carry — MEAN
    precomputed cosine similarity (see theme_similarities) over words
    actually in vocabulary, in [-1, 1]. Mean rather than max: a line needs
    more than one coincidentally-close word to read as on-theme (user's own
    complaint was about matches that don't feel related despite word overlap
    — a single lucky cosine shouldn't buy the same trust as it would for
    max). 0.0 if the model, theme, or line has nothing usable — a themed run
    still produces output, just without semantic ranking for that line.

    NOT clamped to [0, 1] anymore (2026-07-18 — was `max(0.0, ...)` per
    word, "a line pointing away from the theme scores 0, this is a boost
    signal, not a penalty", back when this only ever fed a one-directional
    bias). filters.py's cohesion knob is now bipolar (`theme_pull`, -1..+1)
    — at its "диссонанс" end a NEGATIVE relevance should score HIGHER than a
    merely-unrelated (near-zero) line, since a genuinely opposite-meaning
    line is a better answer to "maximum possible deviation from the theme"
    than a neutral one. Un-clamping here is what lets that happen; the sign
    flip that turns negative relevance into a preference only happens in
    filters.py, not here — this function still just reports the cosine."""
    if sims is None or not lemmas or _index is None:
        return 0.0
    vals = [float(sims[_index[w]]) for w in lemmas if w in _index]
    return sum(vals) / len(vals) if vals else 0.0
