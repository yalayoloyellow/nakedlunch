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

import пути

DATA_DIR = пути.ДАННЫЕ
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
    history: list = field(default_factory=list)      # [{text, template, tags, shown_at, restored_at, в_корпусе}]
    retention_days: float = 30.0                      # 0 = "никогда" — only manual restore brings a line back
    # Штамп индекса, под который история УЖЕ перепривязана — см. `перепривязать`.
    # Пусто у всех файлов до 2026-08-18: значит перепривязка ещё не шла ни разу.
    index_stamp: str = ""

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
                   history=d.get("history", []), retention_days=d.get("retention_days", 30.0),
                   index_stamp=d.get("index_stamp", ""))

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"accepted": self.accepted,
                   "history": self.history, "retention_days": self.retention_days,
                   "index_stamp": self.index_stamp}
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
    def mark_shown(self, items, theme: str = "", семя=None) -> None:
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
            # `seed` — НОМЕР ПРОГОНА, КОТОРЫЙ ЭТУ СТРОКУ ПОРОДИЛ (Раунд 62).
            # Один int на запись, и он решает столкновение двух обещаний:
            # «показанное не возвращается» против «номер повторяет выдачу в
            # точности». Без него повтор ломался в самом обычном случае —
            # проверено живьём: сгенерировал, вписал тот же номер, получил
            # ДРУГИЕ строки, потому что первые четыре успели уйти в историю.
            # См. `тексты_прогона`. Старые записи номера не имеют — для них
            # None, то есть прежнее поведение: прячутся всегда.
            self.history.append({"text": text, "template": it.get("template", ""),
                                  "tags": tags, "shown_at": now, "restored_at": None,
                                  "seed": семя})
            have.add(text)

    def _expired(self, entry: dict, now: float) -> bool:
        if entry.get("restored_at") is not None:
            return True
        if self.retention_days <= 0:
            return False
        return (now - entry["shown_at"]) >= self.retention_days * _DAY

    @staticmethod
    def _ключ(запись: dict) -> str:
        """Текст, которым запись сверяется с корпусом СЕГОДНЯ.

        Обычно это он и есть. Но если корпус подрезали, а запись сняли до
        подрезки, `перепривязать` кладёт рядом `в_корпусе` — нынешний вид той же
        строки. Показываем при этом по-прежнему `text`: человек видел именно
        его, и подменять показанное задним числом значит врать о том, что было
        на экране."""
        return запись.get("в_корпусе") or запись["text"]

    def hidden_set(self) -> set:
        """Texts currently excluded from generation — the old seen_set()'s
        job, but time-limited: an entry ages out on its own past the
        retention period, or the user restores it explicitly. Favorites are
        ALWAYS included too — a favorited line stays out of fresh candidate
        pools permanently, same as before, just via a separate permanent list
        rather than duplicated bookkeeping in history."""
        now = time.time()
        s = {self._ключ(h) for h in self.history if not self._expired(h, now)}
        s.update(self._ключ(a) for a in self.accepted)
        return s

    def тексты_прогона(self, семя) -> set:
        """Что показал прогон с этим номером. Пусто, если номера нет.

        ЗАЧЕМ. «Показанное не возвращается в выдачу» и «номер повторяет выдачу
        в точности» столкнулись лбами: прогон сам кладёт свои строки в историю,
        история вычитается из пула, и тот же номер сразу после прогона даёт
        СЛЕДУЮЩИЕ строки. Поймано живой проверкой в интерфейсе, а не рассуждением.

        Разрешение без жертвы: инвариант охраняет от чужого — «не показывай
        второй раз то, что я уже видел В ДРУГОЙ РАЗ». Строки, которые породил
        сам прогон N, для прогона N не чужие: их и просят. Поэтому прячем всё,
        кроме собственного следа этого номера.

        Берётся из ИСТОРИИ, а вычитается из всего скрытого разом — значит
        строка, которую потом добавили в избранное, тоже вернётся при повторе:
        избранное прячет её от НОВОЙ выдачи, а не от её собственного прогона.

        Побочное свойство, которое стоит знать: у честного повтора счётчик
        «скрыто» в штампе совпадёт с прежним, а если материал и правда
        изменился — разойдётся. То есть штамп сам показывает, повторимо ли."""
        if семя is None:
            return set()
        return {self._ключ(h) for h in self.history if h.get("seed") == семя}

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

    # ---- перепривязка к изменившемуся корпусу ------------------------------
    #
    # ЧТО СЛУЧИЛОСЬ. Ретро-подрезка обрывков (341 680 фрагментов) укоротила
    # строки, а история сверяется по ТЕКСТУ точным совпадением — и 1 017 записей
    # из 4 571 (22.2%) перестали находить свою строку. Инвариант «показанное не
    # возвращается» на них молча перестал действовать. Любая следующая правка
    # корпуса сделала бы то же самое снова.
    #
    # ПОЧЕМУ НЕ НОМЕР СТРОКИ — ЭТО ЗАМЕР, А НЕ МНЕНИЕ (2026-08-18).
    # Напрашивается «хранить номер строки в индексе, он же устойчивее текста».
    # Проверено на самой этой чистке: старый `nl_rhyme.json` (6 авг, 2 434 632
    # записи) против живого индекса (18 авг, 2 392 262) — номер строки указывает
    # на ТУ ЖЕ строку у **7 454 из 2 392 262, то есть 0.312%**; у 99.688% под
    # номером лежит ЧУЖАЯ строка. Первое расхождение — на номере 268 из двух с
    # лишним миллионов. Причина в самой нумерации: номер это позиция в
    # `dict(кэш.поток())` (см. tools/build_nl_index.py, `enumerate(R.items())`),
    # поэтому ЛЮБОЕ удаление или схлопывание дублей сдвигает весь хвост.
    # На истории то же самое поимённо: из 3 669 записей, чей номер до чистки
    # известен, после чистки верны 5. То есть номер не просто ненадёжен — он
    # ХУЖЕ текста: текст теряется честно (строка не нашлась), а номер молча
    # прячет чужую строку и не прячет ту, которую показывали. Поэтому номер
    # здесь не хранится вовсе; хранить поле, которое в 99.7% случаев врёт, —
    # это добавить работы и убавить правды.
    #
    # ЧТО УСТОЙЧИВО. Подрезка снимает СЛУЖЕБНЫЙ ХВОСТ, то есть новая строка —
    # начало старой. Значит опора — не номер и не сам текст, а текст, приведённый
    # ТЕМ ЖЕ правилом, которым резали корпус (`nlindex.Index.подрезать_хвост`,
    # один список служебных слов на оба применения). Правило идемпотентно, так
    # что оно же переживает и следующую подрезку.
    #
    # ЧЕГО ЭТО НЕ ЧИНИТ, СКАЗАНО ПРЯМО: правку корпуса, которая меняет НАЧАЛО
    # строки или переписывает её целиком. Такой в конвейере сегодня нет, но
    # выдавать этот проход за защиту от любой будущей правки нельзя.
    def перепривязать(self, штамп: str, есть, подрезать) -> dict:
        """Свести историю и избранное с нынешним составом корпуса.

        Идёт РАЗ на штамп индекса: `штамп` — это `nlindex.штамп()`, то есть
        число строк и отпечаток их состава. Совпал с уже записанным — работы
        нет, и это главный случай (каждый запуск, кроме первого после перепечи).

        `есть(текст) -> bool` и `подрезать(текст) -> str` приходят снаружи
        нарочно: корпус не знает про индекс и не должен — иначе `core/corpus.py`
        потянет за собой numpy и mmap в каждый тест, который трогает избранное.

        Возвращает числа, а не пишет в журнал: кто позвал, тот и решает, куда их
        деть. Сама запись на диск тоже на вызывающем — этот проход только метит
        записи в памяти."""
        итог = {"нужна": False, "штамп": штамп, "прежний": self.index_stamp,
                "история": 0, "избранное": 0, "на_месте": 0, "сироты": 0}
        # «без индекса» — честный ответ nlindex.штамп(), когда индекса нет.
        # Перепривязываться не к чему: молча записать такой штамп значило бы
        # объявить историю сведённой с корпусом, которого не читали.
        if not штамп or штамп == "без индекса" or штамп == self.index_stamp:
            return итог
        итог["нужна"] = True
        for имя, записи in (("история", self.history), ("избранное", self.accepted)):
            for з in записи:
                текст = з.get("text")
                if not текст:
                    continue
                if есть(self._ключ(з)):
                    итог["на_месте"] += 1
                    continue
                # Режем ВСЕГДА от исходного текста, а не от прошлой привязки:
                # правило идемпотентно, значит вторая подрезка корпуса найдётся
                # от того же начала, и накопления ошибки не будет.
                короче = подрезать(текст)
                if короче and короче != текст and есть(короче):
                    з["в_корпусе"] = короче
                    итог[имя] += 1
                else:
                    # Сирота. Чаще всего это НЕ поломка: строки, которых больше
                    # нет в корпусе, прятать не от чего. Замер на живом файле —
                    # все 322 сироты отсутствуют и в хранилище, и в кэше ДО
                    # подрезки, то есть их фрагменты вырезаны, а не изменены.
                    итог["сироты"] += 1
        self.index_stamp = штамп
        return итог

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
