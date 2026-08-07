# extendo — the user's OWN saved stanza constructions (2026-07-18, PLAN.md
# 0.7 — the stanza constructor: "профили и уже есть предустановленные
# профили ... надо всё сделать максимально удобно и сохраняемо"). Builtin
# forms (классика/восток/модерн и постмодерн/фольклор — 24 verse-theoretic
# forms) live in core/data/stanza_forms.json, shipped with the app and
# read-only from here. Custom ones are the user's own saved constructions,
# in data/stanza_profiles.json next to corpus.json/settings.json/stats.jsonl
# — same "somewhere concrete" file convention as core/settings.py.
#
# Dumb store, no validation here — same division of labor as settings.py:
# api/server.py runs `lines` through clean.stanza_spec() before it ever
# reaches save(), and again on the way OUT of custom()/builtin() (a stale-
# schema or hand-edited file shouldn't be trusted raw either direction).

from __future__ import annotations

import json

import склад
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PROFILES_PATH = DATA_DIR / "stanza_profiles.json"
BUILTIN_PATH = Path(__file__).resolve().parent / "data" / "stanza_forms.json"

_builtin_cache: list[dict] | None = None


def builtin() -> list[dict]:
    """The 24 shipped verse forms — loaded once, cached for the process
    lifetime (a build artifact like forms.json/nl_rhyme.json, never changes
    at runtime)."""
    global _builtin_cache
    if _builtin_cache is None:
        try:
            data = json.loads(BUILTIN_PATH.read_text("utf-8"))
            _builtin_cache = data.get("forms", []) if isinstance(data, dict) else []
        except (OSError, ValueError):
            _builtin_cache = []
    return _builtin_cache


def custom() -> list[dict]:
    """The user's own saved profiles, or [] if none/unreadable — never
    raises (a corrupt file here just means an empty custom list, not a
    broken app; unlike corpus.json, losing this is annoying, not data loss
    of anything irreplaceable)."""
    try:
        data = json.loads(PROFILES_PATH.read_text("utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def save(name: str, lines: list[dict]) -> list[dict]:
    """Save or overwrite (by name) a custom profile. Returns the full custom
    list, same shape `custom()` returns, so the caller can ship it straight
    back to the client without a second read.

    Раунд 50: аргумент `params` убран. Форма строфы — это только КАРКАС;
    положения крутилок уехали на свою полку (core/knob_profiles.py). Раньше
    они лежали здесь, и выбор формы молча двигал ползунки — требование: каркас строфы и профиль настроек ставятся раздельно."""
    profiles = [p for p in custom() if p.get("name") != name]
    profiles.append({"name": name, "lines": lines})
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    склад.писать(PROFILES_PATH, profiles)
    return profiles


def delete(name: str) -> list[dict]:
    profiles = [p for p in custom() if p.get("name") != name]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    склад.писать(PROFILES_PATH, profiles)
    return profiles
