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
from functools import lru_cache
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


# ПАМЯТЬ НА СЛОВО (2026-08-21). Функция чистая — слово в тег, — а зовётся она
# на КАЖДОМ слове каждого фрагмента. Пока это был проход по одной книге при
# заливке, цена не считалась; с появлением повторяемой чистки склада
# (`NakedLunchStore.почистить`) тот же вызов идёт по 2 449 400 фрагментам, а
# слова в книгах повторяются десятками тысяч раз. Размер взят с запасом: в
# живом складе различных словоформ порядка миллиона, и держать их все дешевле,
# чем разбирать одно и то же морфологией.
@lru_cache(maxsize=1 << 20)
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


# ССЫЛОЧНЫЙ МАРКЕР ЛИТЕРАЛОМ (2026-08-21, живые книги владельца).
#
# Часть сносок размечена не тегом, а прямо в тексте:
#     «В первом томе своих «Осколков» [47] профессор Мюллер…»   (скобки — текст,
#                                                                жирный только номер)
#     «…их легко победить {24} .»                               (Сунь-цзы)
# Тег `<a type="note">` их не ловит — там литерал. Скобка или фигурная скобка,
# внутри которой одни цифры, русской прозой не бывает НИКОГДА: это указатель.
# Замер на девяти книгах: 608 порченых фрагментов у Блаватской и 74 у Сунь-цзы,
# у остальных семи — ноль.
#
# Список номеров через запятую или тире («[166, 167]», «[12–14]») — тот же
# случай. Буквы внутри скобок НЕ трогаем: «[так в оригинале]» это речь.
_МАРКЕР_ССЫЛКИ = re.compile(r"[\[{]\s*\d+(?:\s*[-–—,]\s*\d+)*\s*[\]}]")


def _текст_абзаца(эл) -> str:
    """Текст абзаца БЕЗ маркеров сносок.

    ЗАЧЕМ (2026-08-21, найдено на живых книгах владельца). В fb2 ссылка на
    сноску размечена так:

        производят Софию,<a l:href="#n_166" type="note">[166]</a> завершая

    Прежний `"".join(p.itertext())` тянул и текст ссылки, и в корпус попадало
    «в свою очередь производят Софию,[166» — обломок номера посреди фразы. На
    «Разоблачённой Изиде» таких ссылок 776, и все они портили соседний текст.

    Маркер сноски это УКАЗАТЕЛЬ, а не слово автора: выбрасываем его текст, а
    сам абзац сшиваем как был. `type="note"` проверяется явно — обычные ссылки
    внутри текста (их в fb2 почти не бывает, но бывают) остаются."""
    куски = []
    if эл.text:
        куски.append(эл.text)
    for ч in эл:
        имя = ч.tag.split("}")[-1]
        сноска = имя == "a" and (ч.get("type") or "").lower() == "note"
        if сноска:
            # ПРОБЕЛ ВМЕСТО СНОСКИ, А НЕ ПУСТОТА. Поймано собственным тестом:
            # «Софию<a type="note">[166]</a>завершая» без пробела склеивалось в
            # «Софиюзавершая» — несуществующее слово, и порча становилась тише,
            # но хуже: её уже не видно глазом. Лишний пробел безвреден —
            # `re.sub(r"\s+", " ")` в вызывающем схлопнет.
            куски.append(" ")
        else:
            куски.append(_текст_абзаца(ч))
        # хвост после ссылки нужен в любом случае — иначе фраза порвётся
        if ч.tail:
            куски.append(ч.tail)
    из = "".join(куски)
    # Пробел вместо маркера, а не пустота: «Софию[166]завершая» без него
    # склеилось бы в одно слово.
    return _МАРКЕР_ССЫЛКИ.sub(" ", из)


def _fb2_to_text(path: Path, skip_first: int = 25) -> str:
    """Extract clean literary text from FB2 file.
    Uses body//p and body//v, skips front matter (titles, copyrights etc).
    """
    tree = ET.parse(path)
    root = tree.getroot()
    parts = []
    for p in root.findall(".//fb:body//fb:p", NS) + root.findall(".//fb:body//fb:v", NS):
        t = _текст_абзаца(p)
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
        # ОБОРВАННЫЙ ХВОСТ СНИМАЕТСЯ ЗДЕСЬ ЖЕ (2026-08-21).
        #
        # Раньше он снимался только кнопкой «почистить корпус», то есть ЗАДНИМ
        # ЧИСЛОМ. Значит каждая новая книга приносила свои 1.8% обрывков, и
        # владельцу пришлось бы жать чистку после КАЖДОЙ заливки. Его же
        # требование: «при заливе книги уже вся работа делается и не надо
        # второй раз прожимать».
        #
        # Дефект-то нарезки, а не чистки: скользящее окно режет фразу посреди и
        # оставляет висеть служебное слово («…И я бы не»). Чинить его надо там,
        # где он рождается.
        #
        # СПИСОК СЛУЖЕБНЫХ СЛОВ БЕРЁТСЯ ИЗ `nlindex`, А НЕ ЗАВОДИТСЯ СВОЙ.
        # Импорт ленивый и «снизу вверх» — некрасиво, но второй такой список
        # разошёлся бы с первым в первую же волну правок, и это не догадка: у
        # `подрезать_хвост` в докстринге ровно про то и написано, почему он
        # публичный. Одно правило дороже слоёв.
        f = _подрезать_хвост(f)
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
        # ДЕДУП ПО НОРМАЛИЗОВАННЫМ СЛОВАМ, А НЕ ПО ТОЧНОЙ СТРОКЕ (2026-08-21).
        #
        # Точное сравнение пропускало пары, различающиеся регистром или знаком:
        # «Во всяком случае» и «во всяком случае», «родилось бы вообще. )» и
        # «родилось бы вообще.)». `NakedLunchStore.почистить` сравнивает именно
        # по словам, и на живой пробе из 16 866 свежезалитых фрагментов кнопка
        # находила ровно эти три штуки. Разные правила в двух местах — та же
        # болезнь, что и разные разбивщики (см. `СЛОВО` ниже).
        ключ = tuple(СЛОВО.findall(f.lower()))
        if ключ and ключ not in seen:
            seen.add(ключ)
            result.append(f)

    # ДО НЕПОДВИЖНОЙ ТОЧКИ, как и в `NakedLunchStore.почистить`: снятый
    # обломок перестаёт быть контейнером для третьего окна, и один проход
    # оставляет остаток. Проверено: на пробной книге кнопка «почистить» после
    # заливки находила ещё два обломка — теперь ноль.
    while True:
        короче = _снять_обломки(result)
        if len(короче) == len(result):
            return короче
        result = короче


# ОДИН РАЗБИВЩИК НА СЛОВА НА ОБА МЕСТА, ГДЕ ИЩУТ БЛИЗНЕЦОВ (2026-08-21).
#
# Их два: здесь, при нарезке новой книги, и в `NakedLunchStore.почистить` для
# старого склада. Сперва у каждого был свой — тут `_ANY_WORD` (`[^\W\d_]+`,
# буквы без цифр), там `[а-яёa-z0-9]+` (буквы С цифрами). Разные разбивки дают
# разные 5-граммы, а значит разный ответ на «лежит ли эта строка внутри той»:
# на пробной книге кнопка «почистить» после свежей заливки находила ещё два
# обломка, хотя нарезчик уже отработал.
#
# Ровно та болезнь, за которой в этом проекте охотятся отдельно: два списка
# одного и того же расходятся всегда. Список теперь один, и `store.py` берёт
# его отсюда.
СЛОВО = re.compile(r"[а-яёa-z0-9]+")


def _подрезать_хвост(текст: str) -> str:
    """Тот же снимальщик служебного хвоста, что у индекса. Ленивый импорт:
    `nlindex` тянет numpy и mmap, а нарезчик зовут и там, где их нет."""
    from nlindex import Index
    х = Index.подрезать_хвост(текст)
    # Принимаем, ТОЛЬКО если ушло слово: `подрезать_хвост` начинается с
    # `rstrip` по знакам и сдирает авторское многоточие, даже когда резать
    # нечего. Та же оговорка и в `NakedLunchStore.почистить` — правило одно.
    return х if len(х.split()) < len(текст.split()) else текст


def _снять_обломки(фрагменты: List[str]) -> List[str]:
    """Убрать окна, целиком лежащие внутри другого окна той же книги.

    ЗАЧЕМ ЗДЕСЬ. `_sliding_windows` берёт окно в 7 слов с шагом 3 — соседние
    окна делят 4 слова из 7, и корпус ПО ПОСТРОЕНИЮ полон вложенных строк.
    Замер по живому складу 2026-08-21: 58.4% фрагментов целиком лежат внутри
    более длинного, а в каждой десятой малой рифмо-корзине из-за этого сидела
    пара близнецов, которые ещё и рифмуются между собой.

    Порог в два слога и выбор «остаётся длинная» — те же, что в
    `NakedLunchStore.почистить`, и по тем же замерам; там же разбор, почему
    сложное правило «по положению» отвергнуто.

    ВНУТРИ ОДНОЙ КНИГИ, а не по всему складу: близнецы рождаются из соседних
    окон ОДНОГО текста, и здесь их источник. Межкнижные совпадения ловит
    кнопка «почистить корпус» — но их единицы, и ради них незачем поднимать
    полмиллиона чужих фрагментов на каждой заливке."""
    гласные = set("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
    слова = [tuple(СЛОВО.findall(f.lower())) for f in фрагменты]
    слогов = [sum(1 for c in f if c in гласные) for f in фрагменты]
    первая: dict = {}
    for i, w in enumerate(слова):
        if len(w) < 5:
            continue
        for k in range(len(w) - 4):
            первая.setdefault(w[k:k + 5], []).append(i)
    обломок = [False] * len(фрагменты)
    for i, w in enumerate(слова):
        if len(w) < 5:
            continue
        for j in первая.get(w[:5], ()):
            if j == i or обломок[j]:
                continue
            b = слова[j]
            if len(b) <= len(w) or abs(слогов[j] - слогов[i]) > 2:
                continue
            if any(b[s:s + len(w)] == w for s in range(len(b) - len(w) + 1)):
                обломок[i] = True
                break
    return [f for k, f in enumerate(фрагменты) if not обломок[k]]
