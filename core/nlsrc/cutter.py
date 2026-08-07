# nakedlunch 1.2.1
# Copyright (c) 2026 Шамаев Илья Сергеевич (Yala, @yalayoloyellow). Personal use only.

"""
Cutter: детерминированная нарезка текста на рваные фрагменты (cut-up стиль).

Правила:
- Однотипная обработка для поэзии и прозы.
- "Грязные" разрезы: обрывы посередине, мосты между предложениями, скользящие окна.
- Детерминировано (без random в основном пути).
- Фильтрация короткого мусора.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

import pymorphy3

_morph = pymorphy3.MorphAnalyzer()


def clean_text(text: str) -> str:
    """Aggressively clean HTML, entities, and artifacts from raw text before fragmentation.
    Centralized cleaning so all sources (via /a or otherwise) are clean.
    """
    if not text or not text.strip():
        return ""

    # Remove script and style blocks entirely (with content)
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML comments
    text = re.sub(r'<!--.*?-->', ' ', text, flags=re.DOTALL)

    # Remove all remaining HTML/XML tags, including self-closing, with attributes, case insensitive
    text = re.sub(r'</?\s*[^>\s]+(?:\s+[^>]*?)?\s*/?>', ' ', text, flags=re.IGNORECASE)

    # Unescape all HTML entities (&amp; -> &, &lt; -> <, &nbsp; -> space, etc.)
    text = html.unescape(text)

    # Replace common entities that unescape might leave as \xa0 etc.
    text = text.replace('\xa0', ' ').replace('&nbsp;', ' ')

    # Collapse all whitespace (newlines, tabs, multiple spaces) to single space
    text = re.sub(r'\s+', ' ', text).strip()

    # Remove other potential markup artifacts, keep letters, digits, basic punctuation for fragments
    # This is aggressive to kill any remaining < > / etc.
    text = re.sub(r'[<>]', '', text)
    text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\—\–\'\"«»\(\)\[\]\{\}…]', '', text, flags=re.UNICODE)

    # Final normalization
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def _grammeme(word: str, grammeme: str) -> bool:
    """Is `word` tagged `grammeme` (Name/Surn/Patr) in pymorphy3's own
    dictionary, at real confidence — only ever checked on a CAPITALIZED
    word, so a common noun that happens to share a surname's spelling
    (e.g. "соловей" the bird vs "Соловьёв" the surname) never collides:
    real personal names are capitalized mid-sentence, common nouns aren't."""
    if not word[:1].isupper():
        return False
    for p in _morph.parse(word):
        if grammeme in p.tag and p.score > 0.1:
            return True
    return False


def _name_tag(word: str) -> str | None:
    stripped = word.strip(".,!?;:—–-\"'«»()")
    if not stripped:
        return None
    for grammeme in ("Name", "Surn", "Patr"):
        if _grammeme(stripped, grammeme):
            return grammeme
    return None


def strip_full_names(text: str) -> str:
    """Remove 'Имя [Отчество] Фамилия' (and the reverse 'Фамилия Имя')
    spans from raw book text — user's own explicit ask (2026-07-19): a real
    person's full name showing up whole in cut-up output isn't something he
    wants, however rarely a source text actually contains one. Deliberately
    narrow — a LONE first name or LONE surname is common (any character's
    given name, an author mentioned once) and stays; only the pair TOGETHER
    triggers removal, matching "имя и фамилию ВМЕСТЕ" exactly.

    Runs on raw text BEFORE fragmentation (see store.add_corpus) so a name
    never even reaches cut_into_fragments's sliding windows. For corpora
    already cut before this existed, see NakedLunchStore.strip_names — the
    same tagging logic, run directly over already-stored fragment text,
    since the raw source text isn't retained after a corpus is added once
    (see Fragment/Corpus in store.py — no source_text field)."""
    words = text.split(" ")
    tags = [_name_tag(w) for w in words]
    drop = [False] * len(words)
    i = 0
    while i < len(words):
        if tags[i] == "Name":
            j = i + 1
            if j < len(words) and tags[j] == "Patr":
                j += 1
            if j < len(words) and tags[j] == "Surn":
                for k in range(i, j + 1):
                    drop[k] = True
                i = j + 1
                continue
        elif tags[i] == "Surn" and i + 1 < len(words) and tags[i + 1] == "Name":
            drop[i] = True
            drop[i + 1] = True
            i += 2
            continue
        i += 1
    kept = [w for w, d in zip(words, drop) if not d]
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


# --- индексно-цифровой мусор (2026-08-01, user's own ask) ------------------
# Живой пример, утёкший в выдачу extendo, дословно из пула:
#   «141, 573 Хазан В. II 468, 670 торн и контратака»
# — скользящее окно по именному указателю книги (собрание Мандельштама,
# сноски Блаватской и т.п.). Детекция ПО-ФРАГМЕНТНО, структурная, только
# regex (без pymorphy: фамилий из указателей часто нет в его словаре, а
# ретро-проход по 2.9М фрагментов должен оставаться быстрым).
# Контракт: ноль ложных срабатываний важнее полноты. Фрагмент с ОДНИМ
# числом («в 1970-ом») неприкосновенен, кроме единственного исключения —
# структурно однозначных входов указателя («573 Хазан В», «Лаврова К. Н.
# I 499»), которыми проза не бывает; все остальные правила требуют минимум
# двух числовых серий (и хотя бы одну многозначную) плюс независимую
# индексную улику. Полу-проза со ссылками («стр. 82)? Или же») сознательно
# выживает.

# «20 000» и «2,726,700» — одно число, не несколько; «141, 573» (запятая
# + пробел) — страничный список, НЕ склеивается.
_THOUSANDS = re.compile(r"(?<=\d)(?:\s+|,)(?=\d{3}(?:\D|$))")
_DIGIT_RUN = re.compile(r"\d+")
_ROMAN_PAGELIST = re.compile(r"\b[IVXLC]{1,5}\s+\d{1,4}\s*[,;]\s*\d{1,4}")
_INITIALS_ROMAN_PAGE = re.compile(
    r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.(?:\s*[А-ЯЁ]\.)?\s+[IVXLC]{1,5}\s+\d{1,4}"
)
_INITIALS_PAGELIST = re.compile(
    r"[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.(?:\s*[А-ЯЁ]\.)?\s+\d{1,4}\s*,\s*\d{1,4}"
)
_PAGELIST_SURNAME = re.compile(r"\d{1,4}\s*,\s*\d{1,4}\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.")
_ANY_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# Числа-НЕ-нумерация: «9)» — маркер перечисления в живом тексте
# («Скорпион; 9) Стрелец; 10) Козерог»), указатели так не нумеруют.
_RUN_NOT_ENUM = re.compile(r"\d+(?=[^)\d]|$)")
# Фрагмент ЦЕЛИКОМ — вход указателя «573 Хазан В» (страница + фамилия +
# инициал, возможно обрезанный без точки). Обнаружен живой проверкой:
# подрезы окна теряют второе число, и общий гейт «минимум два числа»
# такой обломок не видит.
_LONE_INDEX_ENTRY = re.compile(r"^\d{1,4}\s+[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.?$")
# «Фамилия И. О.» (с необязательной скобкой: «Марджанов (Марджанишвили) К.»)
# — две такие группы подряд без единого слова в нижнем регистре бывают
# только в именном указателе, даже когда окно потеряло все страницы:
# «Моргулис А. О. Марджанов (Марджанишвили) К. А» (живая проверка).
_SURNAME_INITIALS_GROUP = re.compile(
    r"[А-ЯЁ][а-яё]+(?:\s*\([^)]{1,40}\))?\s+[А-ЯЁ]\.(?:\s*[А-ЯЁ]\.)?"
)


def is_index_junk(fragment: str) -> bool:
    """True, если фрагмент — обломок книжного указателя/оглавления/сносок,
    а не проза. Каждое правило проверено на живом пуле (2.89М фрагментов):
    библейские номера стихов, даты («ночь с 30 на 31 марта 2001»),
    биографические скобки («1877–1947) — английский писатель») и суммы
    («20,000 Quips») выживают; страничные списки и именные указатели — нет."""
    # Структурно однозначные входы указателя — до числовых гейтов: римский
    # том между инициалами и страницей («Лаврова К. Н. I 499») и целиком-
    # обломок «573 Хазан В» встречаются и с единственным числом.
    if _INITIALS_ROMAN_PAGE.search(fragment) or _LONE_INDEX_ENTRY.search(fragment):
        return True
    if (len(_SURNAME_INITIALS_GROUP.findall(fragment)) >= 2
            and not any(w[0].islower() for w in _ANY_WORD.findall(fragment))):
        return True  # именной указатель без страниц: «Моргулис А. О. Марджанов … К. А»
    merged = _THOUSANDS.sub("", fragment)
    runs = _DIGIT_RUN.findall(merged)
    if len(runs) < 2:
        return False  # одиночное число — неприкосновенно (кроме структурных входов выше)
    if not any(len(r) >= 2 for r in runs):
        # Одни однозначные числа — перечисления живого текста, не страницы:
        # «6… 5… 4… Нет» (Пелевин), «1. Восторг. 2. Разочарование» (афоризм),
        # «Навыки 1, 2, 3» (Кови). Указатель без многозначных номеров не бывает.
        return False
    if len(runs) >= 3:
        digits = sum(map(len, runs))
        nonspace = len(re.sub(r"\s+", "", merged)) or 1
        # Доминирование цифр — но минимум две КОРОТКИЕ серии (≤3 цифр,
        # страничные номера): годы 4-значные, и чисто годовые строки
        # («1911–1971) — поэт. В 1957», «27, 28 и 29 июля» на границе)
        # сюда не попадают. Порог 0.55, не 0.5 — прозаичные датировки
        # («17–31 мая 1912 г.») сидят на 0.50–0.53.
        if digits / nonspace >= 0.55 and sum(1 for r in runs if len(r) <= 3) >= 2:
            return True  # цифр больше, чем текста: «406, 456–458, 481, 486…»
        if (len(_RUN_NOT_ENUM.findall(merged)) >= 3
                and not any(w[0].islower() for w in _ANY_WORD.findall(merged))):
            return True  # числа вперемешку только с Именами: «118 Аполлодор II 502 Апулей I 516»
    if _ROMAN_PAGELIST.search(fragment):
        return True  # том + страницы: «II 468, 670»
    if _INITIALS_PAGELIST.search(fragment) or _PAGELIST_SURNAME.search(fragment):
        return True  # «Гаспаров Б. М. 188, 197» / «141, 573 Хазан В.»
    return False


NS = {"fb": "http://www.gribuser.ru/xml/fictionbook/2.0"}


def _fb2_to_text(path: Path, skip_first: int = 25) -> str:
    """Extract clean literary text from FB2 file.
    Uses body//p and body//v, skips front matter (titles, copyrights etc).
    """
    tree = ET.parse(path)
    root = tree.getroot()
    parts = []
    for p in root.findall(".//fb:body//fb:p", NS) + root.findall(".//fb:body//fb:v", NS):
        t = "".join(p.itertext()).strip()
        t = re.sub(r"\s+", " ", t).strip()
        if t and len(t) > 2:
            parts.append(t)
    if len(parts) > skip_first:
        parts = parts[skip_first:]
    text = "\n\n".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def parse_source_file(path: str | Path) -> str:
    """Load source file (only .fb2, .txt, .md), clean it, return plain text ready for fragmentation.
    Strictly limited: we won't decode anything else for you.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Source file not found: {p}")
    suffix = p.suffix.lower()
    if suffix == ".fb2":
        return _fb2_to_text(p)
    elif suffix in (".txt", ".md"):
        # plain text or markdown — treat as plain text
        raw = p.read_text(encoding="utf-8", errors="replace")
        return clean_text(raw)
    else:
        raise ValueError("unsupported_format")


def _normalize(text: str) -> str:
    # Схлопываем множественные пробелы, но сохраняем одиночные переносы строк
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Временно защитим одиночные \n
    text = re.sub(r"\n", " \n ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" \n ", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_sentences(p: str) -> List[str]:
    """Разбиваем параграф/блок на предложения, сохраняя базовые разделители."""
    if not p:
        return []
    # Разделители предложений + захват группы
    parts = re.split(r"([.!?])\s*", p)
    sents: List[str] = []
    i = 0
    while i < len(parts):
        chunk = parts[i].strip()
        if i + 1 < len(parts) and parts[i + 1] in ".!?":
            delim = parts[i + 1]
            s = (chunk + delim).strip()
            if s:
                sents.append(s)
            i += 2
        else:
            if chunk:
                sents.append(chunk)
            i += 1
    return sents


def _subsplit(sent: str) -> List[str]:
    """Дополнительные разрезы внутри предложения по запятым, тире и т.п."""
    if not sent:
        return []
    # Агрессивно режем по внутренним разделителям — но ТИРЕ только когда оно
    # стоит отдельным знаком, в окружении пробелов.
    #
    # Раньше в классе разделителей последним символом был обычный дефис-минус,
    # и он резал ЛЮБОЕ слово с дефисом пополам: «какая-нибудь» → «какая» +
    # «нибудь», «из-за» → «из» + «за», «по-русски» → «по» + «русски». Отсюда
    # в живой выдаче брались фрагменты вроде «нибудь гнусность скрывается» —
    # строка, безупречная по слогам и клаузуле и бессмысленная на слух.
    # Найдено аудитом Раунда 51 по этой самой строке из документа пользователя.
    subs = re.split(r"[,;]\s*|\s+[—–-]+\s*", sent)
    out = []
    for s in subs:
        s = s.strip()
        if s:
            out.append(s)
    return out


def _bridges(sents: List[str]) -> List[str]:
    """Мосты: хвост предыдущего + голова следующего."""
    bridges = []
    for i in range(len(sents) - 1):
        a = sents[i]
        b = sents[i + 1]
        aw = a.split()
        bw = b.split()
        if len(aw) >= 3 and len(bw) >= 2:
            bridge = " ".join(aw[-3:] + bw[:3])
            if len(bridge) >= 10:
                bridges.append(bridge)
        # ещё один вариант моста подлиннее
        if len(aw) >= 4 and len(bw) >= 3:
            bridge2 = " ".join(aw[-4:] + bw[:3])
            if len(bridge2) >= 12:
                bridges.append(bridge2)
    return bridges


def _sliding_windows(text: str) -> List[str]:
    """Систематические грязные окна по всему тексту (детерминировано)."""
    # Берём чистый текст без лишних переносов для окон
    clean = re.sub(r"\s+", " ", text)
    words = [w for w in clean.split() if w]
    windows: List[str] = []
    if len(words) < 4:
        return windows
    step = 3
    win = 7
    for i in range(0, len(words) - 3, step):
        chunk = " ".join(words[i : i + win])
        if len(chunk) >= 12:
            windows.append(chunk)
    # дополнительные чуть меньшие окна со сдвигом
    win2 = 5
    for i in range(1, len(words) - 3, step + 1):
        chunk = " ".join(words[i : i + win2])
        if len(chunk) >= 10:
            windows.append(chunk)
    return windows


def cut_into_fragments(text: str) -> List[str]:
    if not text or not text.strip():
        return []

    norm = _normalize(text)
    if not norm:
        return []

    fragments: List[str] = []

    # 1. Работаем по абзацам
    paras = [p.strip() for p in norm.split("\n\n") if p.strip()]
    if not paras:
        paras = [norm]

    for p in paras:
        # Учитываем также строки внутри (полезно для поэзии/рэпа)
        lines = [ln.strip() for ln in p.split("\n") if ln.strip()]
        for line in lines:
            if 8 <= len(line) <= 140:
                fragments.append(line)

        sents = _split_sentences(p)
        for s in sents:
            s = s.strip()
            if 8 <= len(s) <= 160:
                fragments.append(s)
            # подразрезы
            for sub in _subsplit(s):
                if 6 <= len(sub) <= 120:
                    fragments.append(sub)

        # мосты между предложениями этого параграфа
        for br in _bridges(sents):
            fragments.append(br)

    # 2. Глобальные скользящие окна (дают самые "дикие" обрывы)
    for w in _sliding_windows(norm):
        fragments.append(w)

    # 3. Финальная чистка + дедуп
    seen = set()
    result: List[str] = []
    for f in fragments:
        f = f.strip().strip(".,;:!?—–- \"'«»()[]{}")
        f = re.sub(r"\s+", " ", f).strip()
        if not f:
            continue
        # минимум 2 слова
        if len(f.split()) < 2:
            continue
        if len(f) < 7:
            continue
        # обломки указателей/оглавлений (2026-08-01) — см. is_index_junk
        if is_index_junk(f):
            continue
        if f not in seen:
            seen.add(f)
            result.append(f)

    return result
