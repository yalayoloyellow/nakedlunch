# extendo — the user's own persistent state: favorites (permanent, never
# auto-removed) and history (every line actually shown on screen — hidden from
# future output, but reversible: searchable, restorable one-by-one or by
# theme, and auto-returns to circulation after a configurable retention
# period). Replaces the old permanent seen-set + accept/reject + λ-distance
# scoring (2026-07-14, user: "всё что отвечает за алгоритмическую оценку
# предпочтений и коррекцию выдачи — убрать"; "показанные строчки перемещать
# в историю, можно восстановить, настроить срок хранения"). One JSON file,
# atomic writes, one source of truth (invariant #3 — user's own data only).

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CORPUS_PATH = DATA_DIR / "corpus.json"

_DAY = 86400.0
# Same shape as nakedlunch's own retention presets (nlbridge._RETENTION_DAYS)
# — not shared code (extendo's history is its own store, nakedlunch's is a
# different file this project never touches), just a familiar preset set.
RETENTION_PRESETS = {"never": 0, "week": 7, "month": 30, "3m": 90, "6m": 180, "year": 365}


@lru_cache(maxsize=1)
def _morph():
    import pymorphy3
    return pymorphy3.MorphAnalyzer()


_CONTENT_POS = ("NOUN", "ADJF", "ADJS", "VERB", "INFN", "PRTF", "GRND")


_HOMOGRAPH_FLOOR = 0.05   # a content-POS parse below this is noise (e.g. 'и' as a
                          # NOUN abbreviation reading, score ~0.0001), not a real ambiguity


# ИМЯ СОБСТВЕННОЕ — ПОМЕТА МОРФОЛОГИИ, А НЕ ЗАГЛАВНАЯ БУКВА (Раунд 57).
#
# Первая версия опознавала имена по заглавной. Замечание: капс сам по себе не порок — важно, что это имя.. И он прав: в строке целиком капсом
# «ТИМОН» от «ЖИЗНЬ» по регистру не отличить вовсе, а строки капсом — нормальный
# материал, не мусор.
#
# Пометы pymorphy3 от регистра не зависят: Name — имя, Surn — фамилия, Patr —
# отчество, Geox — география, Orgn — организация, Trad — торговая марка.
_ИМЕННЫЕ = ("Name", "Surn", "Patr", "Geox", "Orgn", "Trad")


@lru_cache(maxsize=200_000)
def имя_ли(tok: str) -> bool:
    """Слово — имя собственное? По морфологии, независимо от регистра."""
    try:
        for p in _morph().parse(tok):
            if any(g in p.tag for g in _ИМЕННЫЕ):
                return True
            # первый разбор решает: дальше идут маловероятные чтения, и по ним
            # «Тимон» стал бы то именем, то глаголом от прогона к прогону
            break
    except Exception:
        return False
    return False


@lru_cache(maxsize=200_000)
def _lemma_of(tok: str) -> str | None:
    """Cached per surface token — the same inflected wordform (e.g. 'холодный')
    recurs across thousands of candidate lines drawn from the same vocabulary,
    so this is the difference between one parse and one per occurrence.

    Trusting only pymorphy3's top-ranked parse silently drops genuine content
    words: 'ночью' ranks ADVB "at night" (0.79) above NOUN instrumental (0.21),
    so parse()[0]-only lost 'ночь' from an accepted line's lemma set, which let
    it fail to recognize itself as a duplicate and resurface right after being
    accepted. But scanning ALL parses unconditionally overcorrects: 'и' has a
    NOUN parse too, just a noise-level abbreviation reading at ~0.0001 — so a
    content-POS parse only counts if its score clears _HOMOGRAPH_FLOOR."""
    top = _morph().parse(tok)[0]
    if top.tag.POS in _CONTENT_POS:
        return top.normal_form
    for p in _morph().parse(tok):
        if p.tag.POS in _CONTENT_POS and p.score >= _HOMOGRAPH_FLOOR:
            return p.normal_form
    return None


# Пунктуация, которую надо снять с краёв токена. 2026-07-17: сюда добавлены
# «…» (U+2026) и «–» (U+2013, КОРОТКОЕ тире) — их не было, хотя длинное «—»
# (U+2014) обрабатывалось. Найдено спайком на реальных данных пользователя: 75 из
# 2406 строк теряли слова ЦЕЛИКОМ («ночь…» → [], «морфия…» → []), потому что
# pymorphy3 не знает словоформу с прилипшим многоточием, а `_lemma_of` честно
# возвращает None. Бьёт именно по nakedlunch-фрагментам — это сырые куски книг
# с типографской пунктуацией. Последствия были тихие и повсюду: леммы, которые
# UI эхо-возвращает в `accept()`, тема (совпадение по леммам), тавтология и
# разнообразие соседей в `_diversify` — всё считалось по обрезанному множеству.
_STRIP_CHARS = ".,!?;:—–-«»\"'()…"


def lemmatize_pairs(text: str) -> list[tuple[str, str, bool]]:
    """Тройки (исходное слово, лемма, имя собственное) — тем же разбором, что
    `lemmatize`.

    Нужны там, где решение зависит от самого слова, а не от его леммы:
    банальность не считается по именам собственным (Раунд 57). Опознаются они
    морфологией, а не заглавной буквой — см. `имя_ли`.
    """
    out = []
    for tok in text.replace("—", " ").replace("–", " ").split():
        сырое = tok.strip(_STRIP_CHARS)
        if not сырое:
            continue
        lemma = _lemma_of(сырое.lower())
        if lemma:
            out.append((сырое, lemma, имя_ли(сырое)))
    return out


def lemmatize(text: str) -> list[str]:
    """Content-word lemmas of a free line (for accepting a text the UI sends back,
    or an imported line). Function words drop out — they don't carry topic."""
    out = []
    for tok in text.replace("—", " ").replace("–", " ").split():
        tok = tok.strip(_STRIP_CHARS).lower()
        if not tok:
            continue
        lemma = _lemma_of(tok)
        if lemma:
            out.append(lemma)
    return out


_TAG_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def _tags_of(theme: str) -> list[str]:
    """Real WHOLE-WORD tokens of a theme string, for "restore by theme" —
    matched by set overlap against a history entry's stored tags, never by
    substring (the same noise a bare substring match caused for nakedlunch's
    own bias-scoring, fixed earlier this session, applies here too)."""
    return sorted({m.lower() for m in _TAG_RE.findall(theme or "")})


@dataclass
class Corpus:
    accepted: list = field(default_factory=list)    # [{text, lemmas, rhyme, ts}] — favorites, PERMANENT
    # Чёрного списка тут больше нет (вырезан 2026-08-03, Раунд 39). Замечание: функционально он не нужен, можно вырезать. — за всё
    # время в нём было НОЛЬ записей, а стоил он подстрочной проверки на
    # каждый фрагмент в каждом из трёх путей отбора. Старые файлы корпуса с
    # ключом "blacklist" читаются молча: ключ просто игнорируется.
    history: list = field(default_factory=list)      # [{text, template, tags, shown_at, restored_at}]
    retention_days: float = 30.0                      # 0 = "никогда" — only manual restore brings a line back

    # ---- persistence -------------------------------------------------------
    @classmethod
    def load(cls) -> "Corpus":
        if not CORPUS_PATH.exists():
            return cls()
        try:
            d = json.loads(CORPUS_PATH.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            # a corrupt corpus is the one file we must not silently reset; refuse.
            raise RuntimeError(f"corpus повреждён: {CORPUS_PATH} — почини или удали вручную")
        return cls(accepted=d.get("accepted", []),
                   history=d.get("history", []), retention_days=d.get("retention_days", 30.0))

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"accepted": self.accepted,
                   "history": self.history, "retention_days": self.retention_days}
        fd, tmp = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=1)
            os.replace(tmp, CORPUS_PATH)   # atomic: accepted lines can't be half-written
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # ---- favorites (accept) — permanent, never auto-removed ----------------
    def accept(self, text: str, lemmas: list[str] | None = None, rhyme: str = "") -> bool:
        """`ts` used to default to 0 and no caller ever set it (found
        2026-07-14) — every favorite's "added at" time was silently lost.
        Always stamps the real time now; pre-fix entries keep their old
        ts=0 (honestly unknown, not backfilled with a guess)."""
        if any(a["text"] == text for a in self.accepted):
            return False
        self.accepted.append({"text": text, "lemmas": lemmas or lemmatize(text),
                              "rhyme": rhyme, "ts": time.time()})
        return True

    def unaccept(self, text: str) -> bool:
        """The user's own explicit removal — the only way a favorite ever
        disappears ("никуда не пропадает никогда пока я сам не удалю")."""
        n = len(self.accepted)
        self.accepted = [a for a in self.accepted if a["text"] != text]
        return len(self.accepted) != n

    # ---- history — reversible, searchable, time-limited hiding -------------
    def mark_shown(self, items, theme: str = "") -> None:
        """Record lines actually DISPLAYED to the user right now — called at
        the moment of display, not at generation time (2026-07-14: a freestyle
        stanza sitting in a prefetch buffer, not yet on screen, must NOT count
        — only what's "непосредственно на экране в данный момент"). `items` is
        [{"text":..., "template":...}, ...]. Already-favorited or
        already-recorded texts are skipped, not re-timestamped — re-showing
        something already in history (e.g. a restored line) shouldn't reset
        its clock without the user re-generating it as fresh content."""
        now = time.time()
        tags = _tags_of(theme)
        have = {h["text"] for h in self.history}
        accepted_texts = {a["text"] for a in self.accepted}
        for it in items:
            text = (it or {}).get("text")
            if not text or text in have or text in accepted_texts:
                continue
            self.history.append({"text": text, "template": it.get("template", ""),
                                  "tags": tags, "shown_at": now, "restored_at": None})
            have.add(text)

    def _expired(self, entry: dict, now: float) -> bool:
        if entry.get("restored_at") is not None:
            return True
        if self.retention_days <= 0:
            return False
        return (now - entry["shown_at"]) >= self.retention_days * _DAY

    def hidden_set(self) -> set:
        """Texts currently excluded from generation — the old seen_set()'s
        job, but time-limited: an entry ages out on its own past the
        retention period, or the user restores it explicitly. Favorites are
        ALWAYS included too — a favorited line stays out of fresh candidate
        pools permanently, same as before, just via a separate permanent list
        rather than duplicated bookkeeping in history."""
        now = time.time()
        s = {h["text"] for h in self.history if not self._expired(h, now)}
        s.update(a["text"] for a in self.accepted)
        return s

    def history_list(self, query: str = "") -> list[dict]:
        """Newest first. `query` is a plain substring filter on the text —
        history is a durable log (restored entries stay listed, marked
        `expired: true`), not a queue that empties as things return."""
        now = time.time()
        q = query.strip().lower()
        out = []
        for h in reversed(self.history):
            if q and q not in h["text"].lower():
                continue
            out.append({**h, "expired": self._expired(h, now)})
        return out

    def restore(self, texts) -> int:
        want = set(texts)
        now = time.time()
        n = 0
        for h in self.history:
            if h["text"] in want and h.get("restored_at") is None:
                h["restored_at"] = now
                n += 1
        return n

    def restore_by_theme(self, theme: str) -> int:
        tags = set(_tags_of(theme))
        if not tags:
            return 0
        now = time.time()
        n = 0
        for h in self.history:
            if h.get("restored_at") is None and tags & set(h.get("tags") or []):
                h["restored_at"] = now
                n += 1
        return n

    def clear_history(self) -> int:
        n = len(self.history)
        self.history = []
        return n

    def set_retention(self, days: float) -> None:
        self.retention_days = max(0.0, float(days))

    # ---- misc reads ----------------------------------------------------
    def accepted_texts(self) -> list[str]:
        return [a["text"] for a in reversed(self.accepted)]   # newest first for the panel

    def stats(self) -> dict:
        now = time.time()
        hidden = sum(1 for h in self.history if not self._expired(h, now))
        return {"accepted": len(self.accepted),
                "history_total": len(self.history), "history_hidden": hidden,
                "retention_days": self.retention_days}
