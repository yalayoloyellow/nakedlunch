# nakedlunch 1.2.1
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
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .cutter import (СЛОВО, clean_text, cut_into_fragments, is_index_junk,
                     strip_full_names, снять_маркеры)
from .generator import generate_four, generate_four_from_scored, tokens as _tokens


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
        # Раунд 56: какие книги включены — ОТДЕЛЬНЫМ маленьким файлом.
        # См. toggle_active: переключение одной книги переписывало state.json
        # целиком, а он 549 МБ.
        self.active_path = self.data_dir / "active.json"
        self.state = State()
        self._active_fragments: List[str] = []
        # None = ещё не считали. Токены нужны ровно одному методу (поиск по
        # смещению в CLI), а платились они на КАЖДОМ переключении книги:
        # 2.87 млн токенизаций и 2.87 млн множеств. Считаем по первому спросу.
        self._active_frag_tokens: Optional[List[set]] = None
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
        # Флаги активности главнее того, что лежит в state.json: он переписывается
        # редко (только когда меняется состав фрагментов), а переключатель книг
        # пишет свой файл на каждый клик.
        if self.active_path.exists():
            try:
                флаги = json.loads(self.active_path.read_text(encoding="utf-8"))
                if isinstance(флаги, dict):
                    for c in self.state.corpora:
                        if c.id in флаги:
                            c.active = bool(флаги[c.id])
            except Exception:
                pass
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
        self._active_frag_tokens = None      # посчитается по первому спросу

    def _frag_tokens(self) -> List[set]:
        """Токены активных фрагментов — лениво (Раунд 56).

        Читает их ровно один метод, `search_biased` ниже: это путь исходного
        CLI, и extendo им не пользуется вовсе (он берёт `get_active_pool` и
        колоночный индекс). А платились они при КАЖДОЙ смене состава активных
        книг — 2.87 млн вызовов регулярки и столько же множеств в памяти,
        каждый раз заново. Теперь считаются, только если кто-то правда спросил,
        и сбрасываются вместе со списком."""
        if self._active_frag_tokens is None:
            self._active_frag_tokens = [_tokens(f) for f in self._active_fragments]
        return self._active_frag_tokens

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
        for f, ft in zip(self._active_fragments, self._frag_tokens()):
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
            # Без indent (Раунд 56): это машинный файл на полгигабайта, руками в
            # него никто не смотрит, а отступы — четверть объёма и времени.
            data = self._state_to_dict(self.state)
            self.state_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            # Держим сайдкар в согласии с полной записью, иначе он стал бы
            # источником устаревших флагов после залива или удаления книги.
            self._save_active()
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
        self, name: str, text: str, make_active: bool = True, save: bool = True,
        шаг=None
    ) -> Corpus:
        """Залить книгу.

        `save=False` — не писать state.json прямо сейчас (Раунд 56). Полная
        запись стоит полугигабайта, и при заливке ПАЧКИ книг она платилась за
        каждую: пять файлов = пять перезаписей 549 МБ. Вызывающий делает одну
        запись в конце пачки (`flush()`), и это не «оптимизация на потом», а
        разница между минутой и пятью.

        `шаг(этап)` — колбэк прогресса: чистка, имена, нарезка. Разбор имён
        идёт pymorphy3 по всему тексту книги и занимает большую часть времени,
        поэтому молчать на нём нельзя."""
        name = name.strip() or "Без названия"
        # Clean the raw text (remove HTML tags, normalize, etc.) immediately after "reading"
        # and before any fragmentation. Centralized here so all add paths benefit.
        if шаг: шаг("чищу текст")
        text = clean_text(text)
        # Strip real "Имя Фамилия" pairs before cutting (2026-07-19, user's
        # own ask) — a name never even reaches the sliding-window cuts below.
        if шаг: шаг("разбираю имена")
        text = strip_full_names(text)

        if шаг: шаг("режу на фрагменты")
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
        if save:
            if шаг: шаг("сохраняю корпус")
            self._save(full=True)
        return corp

    def flush(self) -> None:
        """Записать корпус на диск — для тех, кто заливал с `save=False`."""
        self._save(full=True)

    def toggle_active(self, cid: str) -> bool:
        """Включить/выключить книгу.

        РАУНД 56. Здесь стоял `_save(full=True)` — то есть перезапись ВСЕГО
        state.json ради одного булева. На корпусе пользователя это 549 МБ:
        json.dumps по 2.87 млн фрагментов плюс запись полугигабайта. Чтение
        того же файла замерено в 7.6 с, запись с сериализацией дороже — и всё
        это на клик по точке рядом с названием книги.

        Отчёт (2026-08-05): после «отключить книгу» непонятно, отключилась ли она, и иногда
        не отключается.. Второе — прямое следствие первого: ответа нет десятки
        секунд, он жмёт ещё раз, и книга переключается обратно.

        Теперь флаги активности живут своим маленьким файлом, а полная запись
        осталась там, где реально меняется состав фрагментов: залив книги,
        удаление, чистка имён, сброс."""
        c = self.get_corpus(cid)
        if not c:
            return False
        c.active = not c.active
        self._rebuild_active_fragments()
        self._save_active()
        self._save()          # только маленький dynamic.json
        return c.active

    def _save_active(self) -> None:
        """Флаги активности книг — килобайты вместо полугигабайта."""
        try:
            self.active_path.write_text(
                json.dumps({c.id: bool(c.active) for c in self.state.corpora},
                           ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass      # не смогли записать флаг — не повод терять переключение в памяти

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

    # НАДГРОБИЕ: `strip_names` УДАЛЁН 2026-08-21.
    #
    # Ретро-проход, снимавший «Имя [Отчество] Фамилия» с уже нарезанных
    # фрагментов (2026-07-19, просьба владельца): исходный текст книги после
    # `add_corpus` не хранится, поэтому перерезать заново нельзя — правило
    # применялось прямо к фрагментам. Написан под находку, запущен один раз из
    # консоли и с тех пор не имел НИ ОДНОГО вызывающего.
    #
    # Его работа целиком внутри `почистить()` ниже, вторым шагом, и там же
    # обломок правила: фрагмент, осыпавшийся ниже порогов после снятия имени,
    # выбрасывается, а не остаётся огрызком. Разница только в том, что теперь до
    # него можно дотянуться кнопкой, а не из консоли.

    # ---------- ОДИН ПОВТОРЯЕМЫЙ ПРОХОД ЧИСТКИ (2026-08-21) ----------
    #
    # ЗАЧЕМ. Требование владельца дословно: «и обогащение и очистка
    # существующего должна быть чтоб я мог пересчитывать и старое
    # пересчитывалось плохое вырезалось».
    #
    # ЧТО БЫЛО НЕ ТАК. Правила чистки в коде БЫЛИ — `strip_names`,
    # `strip_index_junk` рядом, подрезка хвоста в `nlindex`, — но их не звал
    # НИКТО: обе соседние функции написаны под конкретную находку, запущены
    # один раз из консоли и с тех пор мертвы (проверено `grep` по всему дереву:
    # ни одного вызывающего). Правило улучшали, а данные оставались как есть.
    # Здесь эти правила собраны в ОДНУ операцию, которую можно жать сколько
    # угодно раз.
    #
    # ПОЧЕМУ ПО СКЛАДУ, А НЕ ПРИ ВЫПЕЧКЕ ИНДЕКСА. Кэш рифм (`nl_rhyme.jsonl`)
    # ключуется ТЕКСТОМ фрагмента, а подрезка текст меняет — значит у
    # подрезанной строки не окажется ни рифмо-ключа, ни лемм, и она выпадет из
    # выдачи вовсе. Чистить надо ДО кэша, то есть в складе; дальше обычная
    # перепечка («перепечь ударения») донесёт чистоту до конца сама.
    #
    # ИДЕМПОТЕНТЕН, и это не пожелание, а условие: второй прогон обязан ничего
    # не менять, иначе кнопку нельзя жать спокойно. Сторожит тест.

    _ГЛАСНЫЕ = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
    # РАЗБИВЩИК БЕРЁТСЯ ИЗ НАРЕЗЧИКА, А НЕ ЗАВОДИТСЯ СВОЙ. Свой тут уже был, и
    # он отличался от нарезчикова: разные 5-граммы → разный ответ на «лежит ли
    # строка внутри другой», и кнопка находила обломки после свежей заливки.
    # Разбор — у `СЛОВО` в cutter.py.
    _СЛОВО = СЛОВО

    @classmethod
    def _слогов(cls, текст: str) -> int:
        return sum(1 for c in текст if c in cls._ГЛАСНЫЕ)

    def почистить(self, применить: bool = True, прогресс=None) -> Dict[str, int]:
        """Все правила чистки разом. `применить=False` — только посчитать.

        `прогресс(этап, сделано, всего)` зовётся по ходу — БЕЗ НЕГО КНОПКИ БЫТЬ
        НЕ МОЖЕТ. Проход идёт две минуты, и правило владельца (2026-08-21):
        «если что-то происходит где-то, это мне отображается… непонятно, чего я
        жду, какой у этого прогресс в реальном времени». Операция без живого
        счётчика неотличима от зависшей.

        Порядок шагов не произволен: сначала выбрасывается мусор целиком
        (считать близнецов среди мусора незачем), потом правится текст, и
        только на ПОЧИЩЕННЫХ текстах ищутся близнецы — иначе подрезка
        превратила бы двух не-близнецов в близнецов уже после проверки.
        """
        from nlindex import Index                    # ленивый: тяжёлый numpy
        подрезать = Index.подрезать_хвост

        итог = {"было": len(self.state.fragments), "указатель": 0, "имя_вырезано": 0,
                "осыпалось": 0, "хвост_подрезан": 0, "двойник": 0, "обломок": 0,
                "маркер_снят": 0}
        живые: List[Fragment] = []
        # Шаг доклада — не «каждый фрагмент» (два миллиона вызовов через поток
        # в словарь стоили бы дороже самой работы) и не «раз в проценте» (при
        # 2.4 млн это 24 тысячи строк между сдвигами, то есть на глаз почти
        # ровно). Двадцать тысяч дают ~120 обновлений на проход: счётчик живой,
        # накладные нулевые.
        # СЧЁТ ИДЁТ ПО ВСЕЙ ОПЕРАЦИИ, А НЕ ПО ЭТАПУ, и это тоже поймано живой
        # проверкой: первый вариант считал только разбор, доходил до 100% — и
        # ещё минуту стоял на сотне, пока шли близнецы. Сотня, после которой
        # ждут, врёт ровно так же, как молчание. Знаменатель двойной: разбор и
        # поиск близнецов — два прохода по складу примерно равной длины.
        ШАГ = 20_000
        всего = len(self.state.fragments)
        ВЕСЬ = всего * 2
        for _н, f in enumerate(self.state.fragments):
            if прогресс is not None and _н % ШАГ == 0:
                прогресс("разбираю", _н, ВЕСЬ)
            т = f.text
            if is_index_junk(т):
                итог["указатель"] += 1
                continue
            # ССЫЛОЧНЫЕ МАРКЕРЫ — ПЕРВЫМИ ИЗ ПРАВОК ТЕКСТА (2026-08-21).
            #
            # Разбор fb2 снимает их с 2026-08-21, но девять книг владельца уже
            # лежат в складе, нарезанные СТАРЫМ разбором: замер по живому
            # индексу дал ≈11 706 порченых строк — целых маркеров ≈8 501 и
            # обрубленных разрезом ≈3 206.
            #
            # Правило ТО ЖЕ САМОЕ, что у разбора (`cutter.снять_маркеры`), а не
            # своя копия: два списка одного и того же расходятся всегда.
            #
            # Первыми — потому что подрезка хвоста и снятие имени работают по
            # словам, а «Едином»[709 маркер сначала надо убрать, иначе он
            # считается частью последнего слова.
            м = снять_маркеры(т)
            if м != т:
                if len(м.split()) < 2 or len(м) < 7:
                    итог["осыпалось"] += 1
                    continue
                итог["маркер_снят"] += 1
                т = м
            б = strip_full_names(т)
            if б != т:
                if len(б.split()) < 2 or len(б) < 7:
                    итог["осыпалось"] += 1
                    continue
                итог["имя_вырезано"] += 1
                т = б
            х = подрезать(т)
            # ПРИНИМАЕМ, ТОЛЬКО ЕСЛИ УШЛО СЛОВО, А НЕ ПУНКТУАЦИЯ.
            #
            # `подрезать_хвост` начинается с `rstrip` по знакам и возвращает
            # УЖЕ ОБОДРАННЫЙ текст даже когда резать нечего. Для сверки истории
            # это ровно то, что нужно (обе стороны нормализуются одинаково), но
            # здесь мы ПИШЕМ результат в склад — и поймано глазами на живой
            # пробе: «которую я встречал…» превращалось в «которую я встречал»,
            # «Я был враг, вторгшийся на её территорию…» теряло многоточие.
            # Это не обрывки, это авторская пунктуация, и трогать её проход не
            # нанимался. Сравниваем ЧИСЛО СЛОВ: подрезка сняла служебное
            # слово — принимаем, сняла только знаки — оставляем как было.
            if х != т and len(х.split()) < len(т.split()):
                if not х or len(х.split()) < 2 or len(х) < 7:
                    итог["осыпалось"] += 1
                    continue
                итог["хвост_подрезан"] += 1
                т = х
            # МУСОР ПРОВЕРЯЕТСЯ ВТОРОЙ РАЗ — ПОСЛЕ ПРАВОК, и это не
            # перестраховка, а замер: первый вариант ловил указатели только на
            # входе, и второй прогон по живому складу снимал ещё 7 строк из
            # 2 101 501. Фрагмент проходил проверку целым, а после снятия имени
            # или подрезки хвоста ПРЕВРАЩАЛСЯ в запись указателя. Семь строк —
            # мелочь, но «идемпотентен» это либо правда, либо нет.
            if т is not f.text and is_index_junk(т):
                итог["указатель"] += 1
                continue
            живые.append(Fragment(id=f.id, text=т, corpus_id=f.corpus_id))

        # ДО НЕПОДВИЖНОЙ ТОЧКИ, А НЕ ОДИН ПРОХОД. Кандидаты в контейнеры
        # берутся среди ЖИВЫХ, и снятый обломок перестаёт быть контейнером для
        # третьей строки — значит один проход в принципе может оставить
        # остаток. На живом складе замер показал, что здесь он нулевой (те семь
        # строк, что находил второй прогон, оказались мусором указателя, см.
        # проверку выше), но свойство обеспечивается циклом, а не удачей.
        # Круг дешёвый: тяжёлая часть — морфология выше, она уже позади.
        # ДОКЛАДЫВАЕТ ТОЛЬКО ПЕРВЫЙ КРУГ, и это не лень, а починка: цикл идёт
        # до неподвижной точки, а каждый круг считал бы от своего начала — на
        # живой проверке счётчик после 97% прыгал назад на 50%. Пятящийся
        # счётчик читается как сбой. Круги после первого короткие (снимать уже
        # почти нечего) и докладывают одним «проверяю ещё раз» у самого конца.
        круг = 0
        while True:
            if круг == 0:
                стало = self._снять_близнецов(живые, итог, прогресс, всего, ВЕСЬ)
            else:
                if прогресс is not None:
                    прогресс("проверяю ещё раз", ВЕСЬ - 1, ВЕСЬ)
                стало = self._снять_близнецов(живые, итог)
            круг += 1
            if len(стало) == len(живые):
                живые = стало
                break
            живые = стало
        итог["стало"] = len(живые)
        if прогресс is not None:
            прогресс("записываю" if применить else "готово", ВЕСЬ, ВЕСЬ)
        # ПРАВКА ТЕКСТА — ТОЖЕ ИЗМЕНЕНИЕ, и это стоило бага при первом же
        # тесте: условие было `стало != было`, а подрезка хвоста и снятие имени
        # НЕ МЕНЯЮТ ЧИСЛО фрагментов. Склад молча оставался прежним, а счётчики
        # рапортовали работу — ровно тот класс вранья, от которого в этом
        # проекте заведены сторожа.
        тронуто = (итог["стало"] != итог["было"] or итог["хвост_подрезан"]
                   or итог["имя_вырезано"] or итог["маркер_снят"])
        if применить and тронуто:
            self.state.fragments = живые
            for c in self.state.corpora:
                c.fragment_count = sum(1 for f in self.state.fragments if f.corpus_id == c.id)
            self._rebuild_active_fragments()
            self._save(full=True)
        return итог

    def _снять_близнецов(self, фрагменты: List[Fragment], итог: Dict[str, int],
                         прогресс=None, сдвиг: int = 0, весь: int = 0) -> List[Fragment]:
        """Убрать точные двойники и ОБЛОМКИ — строки, целиком лежащие внутри
        другой и отличающиеся не больше чем на два слога.

        ПОЧЕМУ ИМЕННО ДВА СЛОГА. Нарезка идёт скользящим окном (`cutter.
        _sliding_windows`: окно 7 слов, шаг 3), поэтому соседние окна делят
        4 слова из 7, и корпус по построению полон вложенных строк — замер
        2026-08-21: 58.4% фрагментов целиком лежат внутри более длинного.
        Выбрасывать их все НЕЛЬЗЯ: кусок длинной фразы на 9 слогов — это
        рабочий материал для строфы, а сама фраза на 16 слогов в строку не
        влезет. А вот пара, различающаяся на слово, взаимозаменяема, и
        короткая в ней систематически ОБЛОМОК с отрезанным первым словом:
            «за каждой обиды нельзя отрекаться от друга»
            «Из-за каждой обиды нельзя отрекаться от друга»
        Замер порога: ≤2 слога ловит 15.8% корпуса, ≤3 — 24%, ≤4 — 30.7%.
        Взят самый узкий: он ловит обломки и не трогает разные длины.

        ЗАЧЕМ ЭТО ВООБЩЕ, если сборщик их и так не ставит рядом. Затем, что они
        РИФМУЮТСЯ между собой (кончаются одинаково → один рифмо-ключ), и в
        малых рифмо-корзинах близнецы встречаются в 10.4% случаев. Сборщик их
        отбивает запретом общей леммы, но платит попытками, а на корзине из
        двух строк строфа просто не собирается.

        КАНДИДАТЫ ИЩУТСЯ ПО ПЕРВОЙ 5-ГРАММЕ, и это не приближение: если строка
        целиком лежит внутри другой, то ЛЮБАЯ её 5-грамма лежит там же —
        значит владельцы первой достаточно, чтобы найти всех контейнеров.
        Полный перебор кандидатов по всем 5-граммам стоил бы часы.
        """
        def доклад(этап: str, доля: float) -> None:
            """Три внутренних цикла примерно равной длины — отсюда доля 0..1
            внутри этапа, а наружу уходит уже общий счёт операции."""
            if прогресс is not None and весь:
                прогресс(этап, сдвиг + int(доля * (весь - сдвиг)), весь)

        доклад("ищу близнецов", 0.0)
        слова = [tuple(self._СЛОВО.findall(f.text.lower())) for f in фрагменты]
        слогов = [self._слогов(f.text) for f in фрагменты]
        доклад("ищу близнецов", 0.33)

        # 1. точные двойники по нормализованным словам — оставляем первого
        видели: Dict[tuple, int] = {}
        двойник = [False] * len(фрагменты)
        for i, w in enumerate(слова):
            if not w:
                continue
            j = видели.get(w)
            if j is None:
                видели[w] = i
            else:
                двойник[i] = True
                итог["двойник"] += 1

        # 2. обломки: вложена в более длинную, разница ≤2 слога
        первая: Dict[tuple, List[int]] = {}
        for i, w in enumerate(слова):
            if двойник[i] or len(w) < 5:
                continue
            for k in range(len(w) - 4):
                первая.setdefault(w[k:k + 5], []).append(i)
        доклад("ищу обломки", 0.66)

        обломок = [False] * len(фрагменты)
        ШАГ_ОБЛ = 50_000
        for i, w in enumerate(слова):
            if прогресс is not None and i % ШАГ_ОБЛ == 0 and фрагменты:
                доклад("ищу обломки", 0.66 + 0.34 * i / len(фрагменты))
            if двойник[i] or len(w) < 5:
                continue
            for j in первая.get(w[:5], ()):
                if j == i or двойник[j] or обломок[j]:
                    continue
                b = слова[j]
                if len(b) <= len(w):
                    continue
                if abs(слогов[j] - слогов[i]) > 2:
                    continue
                # ОСТАЁТСЯ ДЛИННАЯ, КОРОТКАЯ УХОДИТ — И ЭТО ПРОВЕРЕНО ЗАМЕРОМ,
                # А НЕ ВЫБРАНО НА ГЛАЗ.
                #
                # Сквозной прогон по избранному владельца показал, что правило
                # изредка режет не то: «что я жеста геройского ищу» уходило, а
                # оставалось «…ищу в жизни». Я попробовала различать по
                # ПОЛОЖЕНИЮ: короткая в начале длинной — значит она законченный
                # кусок, а длинная лишь дописала хвост, и обломок тогда длинная.
                #
                # ЗАМЕР ЭТО ОТВЕРГ, НО НЕ ПОЛНОСТЬЮ, И ЧЕСТНОЕ ЧИСЛО ТАКОЕ:
                # на живом складе сложное правило спасло РОВНО ОДНУ сохранённую
                # строку из 46 («что я жеста геройского ищу»), заплатив за неё
                # проходом 654 с вместо 102 и обломками 293 994 вместо 277 755.
                # Вшестеро дольше и режет больше — ради одной строки.
                # Остальные не спаслись потому, что строка часто лежит сразу в
                # двух длинных, началом в одной и хвостом в другой, и
                # «правильного» ответа там нет вовсе.
                #
                # Цена простого правила известна и мала: из 46 избранных, что
                # были в корпусе, уходит 6. Одна из шести — ложная тревога (она
                # жива со строчной буквы, ушёл точный двойник), а у четырёх
                # длинная версия остаётся в корпусе ЦЕЛЕЕ короткой («нежной
                # игрушки, была большая…» вместо «игрушки, была большая…»).
                # То есть настоящая потеря — одна строка на 46.
                if any(b[s:s + len(w)] == w for s in range(len(b) - len(w) + 1)):
                    обломок[i] = True
                    итог["обломок"] += 1
                    break
        return [f for k, f in enumerate(фрагменты) if not двойник[k] and not обломок[k]]

    # НАДГРОБИЕ: `strip_index_junk` УДАЛЁН 2026-08-21.
    #
    # Ретро-проход, выбрасывавший записи именных указателей (2026-08-01, после
    # того как «141, 573 Хазан В. II 468, 670 торн и контратака» утекло в живую
    # выдачу). Та же история, что у `strip_names` выше: написан под находку,
    # прогнан раз из консоли, ноль вызывающих.
    #
    # Работа целиком внутри `почистить()`, причём ЛУЧШЕ: там мусор проверяется
    # ДВАЖДЫ — на входе и после правок, потому что фрагмент становится записью
    # указателя уже после снятия имени и подрезки хвоста (замер: 7 строк из
    # 2 101 501 на живом складе).

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
        self._active_frag_tokens = None
        try:
            if self.active_path.exists():
                self.active_path.unlink()
        except Exception:
            pass
        self._rebuild_active_fragments()
        # Clean dynamic on full reset
        try:
            if self.dynamic_path.exists():
                self.dynamic_path.unlink()
        except Exception:
            pass
        self._save(full=True)
