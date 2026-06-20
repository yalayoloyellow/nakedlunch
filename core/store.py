# nakedlunch 1.2
# Copyright (c) 2026 Шамаев Илья Сергеевич (Yala, @yalayoloyellow). Personal use only.

"""
Store: управление корпусами, фрагментами, состоянием чата, персистенция.

- Фрагменты нарезаются один раз при add_corpus.
- Активный пул = фрагменты из active корпусов.
- pending_bias сбрасывается сразу после генерации.
- Автосохранение на каждое изменение.
- Приложение стартует пустым; пользователь добавляет свои тексты.
"""

from __future__ import annotations

import heapq
import json
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.cutter import clean_text, cut_into_fragments
from core.generator import generate_four, generate_four_from_scored, tokens as _tokens


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _make_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{id(object())}"[-24:]


@dataclass
class Corpus:
    id: str
    name: str
    type: str  # "personal"
    active: bool = True
    added_at: str = field(default_factory=_now)
    fragment_count: int = 0


@dataclass
class Fragment:
    id: str
    text: str
    corpus_id: str


@dataclass
class ChatEntry:
    id: str
    role: str  # "user" | "bot"
    text: Optional[str] = None  # for user
    lines: Optional[List[str]] = None  # for bot
    bias_used: Optional[str] = None
    ts: str = field(default_factory=_now)


@dataclass
class State:
    version: int = 1
    updated_at: str = field(default_factory=_now)
    corpora: List[Corpus] = field(default_factory=list)
    fragments: List[Fragment] = field(default_factory=list)
    chat: Dict[str, Any] = field(default_factory=lambda: {"history": [], "pending_bias": None})
    used_lines: Dict[str, float] = field(default_factory=dict)  # exact output line -> unix timestamp when shown in chat


class NakedLunchStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "state.json"
        self.dynamic_path = self.data_dir / "dynamic.json"
        self.state = State()
        self._active_fragments: List[str] = []
        self._active_frag_tokens: List[set[str]] = []
        self._load()
        self._rebuild_active_fragments()

    def _load(self) -> None:
        loaded_full = False
        if self.state_path.exists():
            try:
                raw = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.state = self._dict_to_state(raw)
                loaded_full = True
            except Exception:
                pass
        if not loaded_full:
            self.state = State()
        # Overlay dynamic state (chat + used_lines) from small fast file if present.
        # This allows frequent saves (after every generation) to be tiny instead of
        # rewriting 250k+ fragments every time.
        if self.dynamic_path.exists():
            try:
                dyn_raw = json.loads(self.dynamic_path.read_text(encoding="utf-8"))
                if "chat" in dyn_raw:
                    self.state.chat = dyn_raw["chat"]
                if "used_lines" in dyn_raw:
                    used = dyn_raw.get("used_lines") or {}
                    # Migrate old state: convert all values to float timestamps
                    self.state.used_lines = {k: float(v) for k, v in used.items()}
            except Exception:
                pass

    def _rebuild_active_fragments(self) -> None:
        """Rebuild cached active fragments list and their tokens.
        Call this whenever active corpora set changes (add, toggle, delete, reset).
        This avoids O(N) corpus filtering on every pool request.
        """
        active_ids = {c.id for c in self.state.corpora if c.active}
        self._active_fragments = [f.text for f in self.state.fragments if f.corpus_id in active_ids]
        self._active_frag_tokens = [_tokens(f) for f in self._active_fragments]

    def _sample_non_used(self, k: int, rng: Optional[random.Random] = None) -> List[str]:
        """Fast rejection sampling k non-used fragments from cached active list.
        Extremely fast for neutral generations when |used| << |active| (common case).
        Falls back to filtered sample if needed.
        """
        if k <= 0 or not self._active_fragments:
            return []
        if rng is None:
            rng = random.Random()
        used = self.state.used_lines
        active = self._active_fragments
        n = len(active)
        if n <= k:
            return [f for f in active if f not in used][:k]
        result: List[str] = []
        seen: set[str] = set()
        max_att = k * 100 + 1000
        att = 0
        while len(result) < k and att < max_att:
            att += 1
            f = active[rng.randrange(n)]
            if f not in used and f not in seen:
                result.append(f)
                seen.add(f)
        if len(result) < k:
            cands = [f for f in active if f not in used and f not in seen]
            if cands:
                need = min(k - len(result), len(cands))
                result.extend(rng.sample(cands, need))
        return result

    def _get_non_used_for_bias(self, bias: str, top_k: int = 100) -> List[Tuple[str, float]]:
        """Collect only top_k highest scoring non-used using precomputed tokens + heap.
        No allocation of 250k+ score list. Critical for speed on large corpora while keeping sensitivity.
        """
        if not bias or not self._active_fragments:
            return []
        used = self.state.used_lines
        b = bias.lower().strip()
        bt = _tokens(bias)
        if not bt:
            return []
        # min-heap of (score, frag) size top_k
        heap: List[Tuple[float, str]] = []
        for f, ft in zip(self._active_fragments, self._active_frag_tokens):
            if f in used:
                continue
            inter = len(bt & ft)
            f_lower = f.lower()
            if b and b in f_lower:
                inter += 3.0
            for bw in bt:
                if bw and bw in f_lower:
                    inter += 1.5
                for fw in ft:
                    if bw and (bw in fw or fw in bw):
                        inter += 1.0
            matched_count = sum(1 for bw in bt if any(bw in fw or fw in bw for fw in ft))
            inter += matched_count * 0.8
            sc = inter / (1.0 + 0.15 * len(ft))
            if len(heap) < top_k:
                heapq.heappush(heap, (sc, f))
            elif sc > heap[0][0]:
                heapq.heappushpop(heap, (sc, f))
        # return list sorted desc by score
        top = sorted([(f, sc) for sc, f in heap], key=lambda x: x[1], reverse=True)
        return top

    def _save(self, full: bool = False) -> None:
        self.state.updated_at = _now()
        if full:
            # Full save: includes fragments etc. Only when corpora/fragments change (rare).
            data = self._state_to_dict(self.state)
            self.state_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        # Always (or for fast path) save the small dynamic parts: chat history + used_lines.
        # This is called after every generation/clear, must be fast even with 250k fragments.
        dyn = {
            "chat": self.state.chat,
            "used_lines": self.state.used_lines or {},
            "updated_at": self.state.updated_at,
        }
        self.dynamic_path.write_text(
            json.dumps(dyn, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _state_to_dict(self, s: State) -> Dict[str, Any]:
        return {
            "version": s.version,
            "updated_at": s.updated_at,
            "corpora": [asdict(c) for c in s.corpora],
            "fragments": [asdict(f) for f in s.fragments],
            "chat": s.chat,
            "used_lines": s.used_lines or {},
        }

    def _dict_to_state(self, d: Dict[str, Any]) -> State:
        corpora = [Corpus(**c) for c in d.get("corpora", [])]
        fragments = [Fragment(**f) for f in d.get("fragments", [])]
        chat = d.get("chat", {"history": [], "pending_bias": None})
        used_lines = d.get("used_lines", {}) or {}
        # Migrate: ensure all timestamps are float
        used_lines = {k: float(v) for k, v in used_lines.items()}
        return State(
            version=d.get("version", 1),
            updated_at=d.get("updated_at", _now()),
            corpora=corpora,
            fragments=fragments,
            chat=chat,
            used_lines=used_lines,
        )

    # ---------- Corpora & Fragments ----------

    def list_corpora(self) -> List[Dict[str, Any]]:
        return [asdict(c) for c in self.state.corpora]

    def get_corpus(self, cid: str) -> Optional[Corpus]:
        for c in self.state.corpora:
            if c.id == cid:
                return c
        return None

    def add_corpus(
        self, name: str, text: str, make_active: bool = True
    ) -> Corpus:
        name = name.strip() or "Без названия"
        # Clean the raw text (remove HTML tags, normalize, etc.) immediately after "reading"
        # and before any fragmentation. Centralized here so all add paths benefit.
        text = clean_text(text)

        frags = cut_into_fragments(text)
        if not frags:
            raise ValueError("no fragments created from the source text")

        cid = _make_id("pers")
        # avoid id collisions (rare)
        while any(c.id == cid for c in self.state.corpora):
            cid = _make_id("pers")

        corp = Corpus(
            id=cid,
            name=name,
            type="personal",
            active=make_active,
            fragment_count=len(frags),
        )

        new_fragments: List[Fragment] = []
        for ftxt in frags:
            fid = _make_id("f")
            new_fragments.append(Fragment(id=fid, text=ftxt, corpus_id=cid))

        self.state.corpora.append(corp)
        self.state.fragments.extend(new_fragments)
        self._rebuild_active_fragments()
        self._save(full=True)
        return corp

    def toggle_active(self, cid: str) -> bool:
        c = self.get_corpus(cid)
        if not c:
            return False
        c.active = not c.active
        self._rebuild_active_fragments()
        self._save(full=True)
        return c.active

    def delete_corpus(self, cid: str) -> bool:
        before = len(self.state.corpora)
        self.state.corpora = [c for c in self.state.corpora if c.id != cid]
        self.state.fragments = [f for f in self.state.fragments if f.corpus_id != cid]
        # update counts
        for c in self.state.corpora:
            c.fragment_count = sum(1 for f in self.state.fragments if f.corpus_id == c.id)
        changed = len(self.state.corpora) < before
        if changed:
            self._rebuild_active_fragments()
            self._save(full=True)
        return changed

    def get_active_pool(self) -> List[str]:
        return list(self._active_fragments)  # copy for safety

    def get_all_fragments(self, corpus_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if corpus_id:
            return [
                {"id": f.id, "text": f.text, "corpus_id": f.corpus_id}
                for f in self.state.fragments
                if f.corpus_id == corpus_id
            ]
        return [{"id": f.id, "text": f.text, "corpus_id": f.corpus_id} for f in self.state.fragments]

    # ---------- Chat & Generate ----------

    def get_chat_state(self) -> Dict[str, Any]:
        return {
            "history": list(self.state.chat.get("history", [])),
            "pending_bias": self.state.chat.get("pending_bias"),
        }

    def set_pending_bias(self, bias: Optional[str]) -> None:
        self.state.chat["pending_bias"] = bias.strip() if bias and bias.strip() else None
        self._save()

    def generate(
        self, bias: Optional[str] = None, *, rng: Optional[random.Random] = None, for_chat: bool = False
    ) -> List[str]:
        if rng is None:
            rng = random.Random()
        effective = (bias or "").strip() or self.state.chat.get("pending_bias")
        if for_chat:
            if not effective:
                # Fast neutral path for chat (Ещё, empty send) - no full list build
                lines = self._sample_non_used(4, rng)
                return lines
            else:
                # Bias: use pre-tokenized + heap top_k scoring (major speedup, no 250k list)
                scored = self._get_non_used_for_bias(effective, top_k=100)
                lines = generate_four_from_scored(scored, self._active_fragments, rng=rng)
                return lines
        else:
            pool = self.get_active_pool()
            lines = generate_four(pool, effective, rng=rng)
            return lines

    def send_chat(self, message: str) -> Dict[str, Any]:
        """Отправка сообщения пользователя. Если не пустое — это толчок на ЭТОТ ответ.
        LEGACY path (used by /api/chat/send in server mode). DesktopApi uses store.generate(for_chat=True) + explicit mark.
        """
        msg = (message or "").strip()

        # use chat pool (excludes previously used lines)
        effective_bias = msg or self.state.chat.get("pending_bias")
        lines = self.generate(effective_bias, for_chat=True)

        entries = []
        now = _now()

        if msg:
            uentry = {
                "id": _make_id("u"),
                "role": "user",
                "text": msg,
                "ts": now,
            }
            self.state.chat.setdefault("history", []).append(uentry)
            entries.append(uentry)

        bentry = {
            "id": _make_id("b"),
            "role": "bot",
            "lines": lines,
            "bias_used": effective_bias if effective_bias else None,
            "ts": now,
        }
        self.state.chat.setdefault("history", []).append(bentry)
        entries.append(bentry)

        # mark as used so they don't repeat
        self.mark_lines_used(lines)

        # СБРОС толчка после ответа
        self.state.chat["pending_bias"] = None
        self._save()
        return {"entries": entries, "pool_size": len(self.get_chat_pool())}

    def append_bot_only(self, lines: List[str], note: str = "") -> Dict[str, Any]:
        """Для кнопки «Ещё» без пользовательского сообщения."""
        now = _now()
        bentry = {
            "id": _make_id("b"),
            "role": "bot",
            "lines": lines,
            "bias_used": None,
            "ts": now,
        }
        self.state.chat.setdefault("history", []).append(bentry)

        # mark used
        self.mark_lines_used(lines)
        self._save()
        return {"entries": [bentry], "pool_size": len(self.get_chat_pool())}

    def append_bot_message(self, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a bot message (for menus, status, results). Supports inline reply_markup for TG-like keyboards."""
        now = _now()
        entry = {
            "id": _make_id("b"),
            "role": "bot",
            "text": text,
            "ts": now,
            "reply_markup": reply_markup,
        }
        self.state.chat.setdefault("history", []).append(entry)
        self._save()
        return entry

    def edit_message(self, message_id: str, text: Optional[str] = None, reply_markup: Optional[Dict[str, Any]] = None) -> bool:
        """Edit a previous bot message (text and/or its inline keyboard). Used for in-place menu updates like real TG bots."""
        for e in self.state.chat.get("history", []):
            if e.get("id") == message_id and e.get("role") == "bot":
                if text is not None:
                    e["text"] = text
                if reply_markup is not None:
                    e["reply_markup"] = reply_markup
                self._save()
                return True
        return False

    def clear_chat_history(self, older_than: Optional[float] = None) -> int:
        """Clear chat history.
        If older_than is None: removes all chat history.
        Time-based clear of chat messages is a no-op (chat log stays intact).
        Only used tracking is cleared for the period.
        """
        hist = self.state.chat.get("history", [])
        if older_than is None:
            count = len(hist)
            self.state.chat["history"] = []
        else:
            # Time-based clear of chat messages is intentionally a no-op.
            # We only clear the "used" anti-repeat buffer for the period.
            # This keeps the visible conversation log intact.
            count = 0
        self.state.chat["pending_bias"] = None
        self._save()
        return count

    # ---------- Used lines (previously shown in chat - do not repeat until cleared) ----------

    def get_chat_pool(self) -> List[str]:
        """Active fragments, excluding lines already output in chat.
        Uses cached active list.
        """
        used = self.state.used_lines
        return [f for f in self._active_fragments if f not in used]

    def mark_lines_used(self, lines: List[str]) -> None:
        """Record exact lines that were shown to user in chat.
        Does NOT save here anymore — caller (send_chat / append_bot_only) will do a (fast dynamic) save.
        """
        now = time.time()
        for line in lines:
            if line and line.strip():
                self.state.used_lines[line] = now

    def clear_used(self, older_than: Optional[float] = None) -> int:
        """Clear used lines. If older_than provided, clears the recent period's usages
        (those with timestamp >= older_than are removed from used), so the fragments shown
        during that period go back into circulation (get_chat_pool will include them again).
        Keeps only usages older than the cutoff.
        older_than must be float (unix timestamp) or None.
        """
        if older_than is None:
            count = len(self.state.used_lines)
            self.state.used_lines.clear()
        else:
            older_than = float(older_than)  # ensure float
            to_keep = {k: float(v) for k, v in self.state.used_lines.items() if float(v) < older_than}
            count = len(self.state.used_lines) - len(to_keep)
            self.state.used_lines = to_keep
        self._save()
        return count

    def get_used_stats(self) -> Dict[str, Any]:
        used = self.state.used_lines or {}
        if not used:
            return {"count": 0}
        now = time.time()
        ages = [now - ts for ts in used.values()]
        # Return recent used lines for display in chat (last 20)
        recent = list(used.keys())[-20:]
        return {
            "count": len(used),
            "min_age_sec": min(ages),
            "max_age_sec": max(ages),
            "recent": recent,
        }

    def reset_all(self) -> None:
        self.state = State()
        self._active_fragments = []
        self._active_frag_tokens = []
        self._rebuild_active_fragments()
        # Clean dynamic on full reset
        try:
            if self.dynamic_path.exists():
                self.dynamic_path.unlink()
        except Exception:
            pass
        self._save(full=True)
