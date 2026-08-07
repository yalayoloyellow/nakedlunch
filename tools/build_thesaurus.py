#!/usr/bin/env python3
"""Сборка словаря синонимов/антонимов из ДВУХ источников.

1) data/raw/ru-extract.jsonl.gz — raw-выжимка wiktextract из ru.wiktionary.org
(https://kaikki.org/dictionary/rawdata.html, downloads/ru/ru-extract.jsonl.gz).
Почему raw ru-extract, а не kaikki.org-dictionary-Russian.jsonl: постобработанный
файл помечен DEPRECATED самим kaikki (issue wiktextract#1178), а ru-extract — это
именно русский Викисловарь (в нём разметка синонимов/антонимов у русских слов
намного полнее, чем в англоязычном), и он втрое меньше.

2) data/raw/abramov_dict1w.txt — «Словарь русских синонимов и сходных по смыслу
выражений» Н. Абрамова (1900, общественное достояние; текстовая расшифровка с
speakrus.ru, взята из github.com/egorkaru/synonym_dictionary, MIT). Добавлен
2026-08-02 по решению владельца: Викисловарь размечен неровно, а Абрамов —
СОСТАВЛЕННЫЙ человеком ряд, где синонимы идут в осмысленном порядке.
Готовый dictionary.json из того же репозитория НЕ используется: его разбор
теряет и мнёт данные («деньги» → «финансы; деньжонки», «презренный металл;
бумажка; (простор»), поэтому исходный текст разбирается здесь.

СЛИЯНИЕ. Ряд Абрамова идёт ПЕРВЫМ и в авторском порядке (у него первым стоит
ближайший синоним — это разметка, которой в Викисловаре нет), Викисловарь
дополняет по алфавиту. Проверено на живых словах: «деньги» Викисловарь знает
как «зарплата, капитал», Абрамов — «монета, казна, капитал, касса, финансы,
деньжонки, мелочь, презренный металл»; зато «смерть» и «сон» у Викисловаря
богаче. Источники дополняют друг друга, поэтому берутся оба.

СИММЕТРИЯ. У Абрамова словарная статья односторонняя: «Холод» перечисляет
«мороз», а у «мороз» своей статьи почти нет. Поэтому связи достраиваются в обе
стороны: если X перечисляет Y, то Y получает X. Без этого половина словаря
была бы недоступна с той стороны, с которой в неё обычно и заглядывают.

Выход: data/thesaurus.json
    {"syn": {слово: [слова...]}, "ant": {...}, "meta": {счётчики}}

Запуск:  python3 tools/build_thesaurus.py
Сырые источники в data/raw НЕ удаляем — нужны для пересборок; каталог /data/ и
так в .gitignore (личный корпус), так что гигабайты в git не утекут.
"""

import gzip
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "ru-extract.jsonl.gz"
RAW_ABRAMOV = ROOT / "data" / "raw" / "abramov_dict1w.txt"
OUT = ROOT / "data" / "thesaurus.json"

# Только кириллица и дефис: выбрасываем латиницу, цифры, фразы с пробелами.
# Почему: попап показывает одно слово — многословные обороты и латиница там мусор.
CYR_WORD = re.compile(r"^[а-яё]+(-[а-яё]+)*$")

# Комбинирующее ударение (у́ → у): в ссылках Викисловаря иногда проставлены акценты.
ACCENT = "́̀"


def norm(w):
    """Нормализация слова: NFC, без ударений, lower. Пустая строка = брак."""
    if not w:
        return ""
    w = unicodedata.normalize("NFC", w)
    w = "".join(ch for ch in w if ch not in ACCENT)
    w = w.strip().lower()
    return w if CYR_WORD.match(w) else ""


def extract(items):
    """Из kaikki-списка [{word: ...}, ...] — множество пригодных слов."""
    out = set()
    for it in items or []:
        w = norm(it.get("word", ""))
        if w:
            out.add(w)
    return out


# --- Абрамов ---------------------------------------------------------------
# Формат строки: «Головное#, синоним, синоним; синоним. Пример. Прот. <Антоним>.
# См. отсылка || фразеология». Всё, кроме первого перечисления, — не синонимы:
# примеры-предложения, цитаты, этимология в [], пометы в (), «Ср.» (смежное,
# не то же), «См.» (тематическая отсылка: «страх# см. боязнь, ОЧЕНЬ»), «||»
# (фразеология). Поэтому зона синонимов режется по первому же маркеру.
_A_СКОБКИ = re.compile(r"\([^)]*\)|\[[^\]]*\]|\"[^\"]*\"|<[^>]*>")
_A_МАРКЕР = re.compile(r"\|\||Ср\.|Прот\.|См\.|см\.")
_A_ПРОТ = re.compile(r"Прот\.\s*:?\s*<([^>]*)>")
_A_СЛОВО = re.compile(r"^[а-яё][а-яё \-]*$")
_A_МАКС_СЛОВ = 3   # «презренный металл» нужен, целая фраза — нет


def _a_элементы(зона: str) -> list:
    из = []
    for ч in re.split(r"[,;]", зона):
        ч = " ".join(ч.split()).strip(" .-").lower()
        if ч and _A_СЛОВО.match(ч) and len(ч.split()) <= _A_МАКС_СЛОВ:
            из.append(ч)
    return из


def abramov() -> tuple[dict, dict, dict]:
    """Разбор словаря Абрамова → (syn, ant, счётчики). Ключи и значения —
    списки в АВТОРСКОМ порядке (у Абрамова первым идёт ближайший синоним),
    поэтому здесь нигде нет sorted()."""
    syn: dict = {}
    ant: dict = {}
    n_строк = n_многослов = 0
    if not RAW_ABRAMOV.exists():
        return syn, ant, {"abramov": "нет файла — слой пропущен"}
    for line in RAW_ABRAMOV.read_text(encoding="utf-8", errors="replace").split("\n"):
        if "#" not in line or not line.strip():
            continue
        n_строк += 1
        голова, хвост = line.split("#", 1)
        голова = голова.strip().lower()
        # многословные головы («смерть постигла, похитила») попапу не нужны:
        # он показывает и подставляет ОДНО слово
        if " " in голова or not _A_СЛОВО.match(голова):
            n_многослов += 1
            continue
        for m in _A_ПРОТ.finditer(хвост):
            ant.setdefault(голова, []).extend(_a_элементы(m.group(1)))
        зона = _A_СКОБКИ.sub(" ", _A_МАРКЕР.split(хвост)[0]).split(".")[0]
        ряд = [w for w in _a_элементы(зона) if w != голова]
        if ряд:
            syn.setdefault(голова, []).extend(ряд)
    # симметрия — см. шапку модуля
    обратные: dict = {}
    for г, лст in syn.items():
        for s in лст:
            if s != г:
                обратные.setdefault(s, []).append(г)
    слито = {}
    for г in set(syn) | set(обратные):
        v = list(dict.fromkeys(syn.get(г, []) + обратные.get(г, [])))
        v = [w for w in v if w != г]
        if v:
            слито[г] = v
    ant = {k: list(dict.fromkeys(v)) for k, v in ant.items() if v}
    return слито, ant, {"abramov_lines": n_строк, "abramov_multiword_skipped": n_многослов,
                        "abramov_syn_keys": len(слито), "abramov_ant_keys": len(ant)}


# --- отсев наречий-усилителей (Раунд 33) -----------------------------------
# Викисловарь размечает как синонимы усилительные обороты: «страх как»,
# «смерть хочется», «ужас сколько». В выжимке от них остаются голые наречия,
# и вкладка синонимов у самых поэтических слов выглядела так:
#   страх → боязнь, испуг, ОЧЕНЬ, паника
#   смерть (антонимы) → жизнь, рождение, ЕЛЕ-ЕЛЕ, НЕМНОГО, СЛЕГКА, ЧУТЬ-ЧУТЬ
# Правило узкое СОЗНАТЕЛЬНО: режем только пару «знаменательная голова (и сама
# не наречие) → кандидат, который БЫВАЕТ исключительно наречием или
# предикативом». Широкое правило «части речи должны совпадать» проверено и
# отвергнуто: оно уносит 3% пар, включая настоящие синонимы через
# субстантивацию («бойфренд/возлюбленный», «терпила/потерпевший») — pymorphy
# читает такие слова как прилагательные. Узкое режет 0.39% и почти всё по делу.
_ЗНАМЕН = {"NOUN", "ADJF", "ADJS", "VERB", "INFN", "PRTF", "PRTS"}
_НАРЕЧ = {"ADVB", "PRED"}
_поз_кэш: dict = {}


def _части_речи(morph, w: str) -> set:
    """Части речи слова (у многословного — последнего слова, оно главное)."""
    hit = _поз_кэш.get(w)
    if hit is None:
        hit = {str(p.tag.POS) for p in morph.parse(w.split()[-1]) if p.score >= 0.05}
        _поз_кэш[w] = hit
    return hit


def без_усилителей(слои: dict) -> int:
    """Убрать наречия-усилители из значений. Возвращает число убранных пар."""
    import pymorphy3
    morph = pymorphy3.MorphAnalyzer()
    убрано = 0
    for слой in слои.values():
        for k, v in list(слой.items()):
            pk = _части_речи(morph, k)
            if not (pk & _ЗНАМЕН) or (pk & _НАРЕЧ):
                continue
            оставить = [w for w in v
                        if not (_части_речи(morph, w) and _части_речи(morph, w) <= _НАРЕЧ)]
            убрано += len(v) - len(оставить)
            if оставить:
                слой[k] = оставить
            else:
                del слой[k]
    return убрано


def build():
    if not RAW.exists():
        sys.exit(f"нет дампа: {RAW}\nскачай: curl -L -C - -o {RAW} "
                 "https://kaikki.org/dictionary/downloads/ru/ru-extract.jsonl.gz")

    t0 = time.time()
    syn, ant = {}, {}
    n_lines = n_ru = n_syn_rec = n_ant_rec = 0

    with gzip.open(RAW, "rt", encoding="utf-8") as fh:
        for line in fh:
            n_lines += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # битая строка дампа — не наша проблема, идём дальше
            if rec.get("lang_code") != "ru":
                continue  # в русском Викисловаре описаны слова сотен языков
            n_ru += 1
            word = norm(rec.get("word", ""))
            if not word:
                continue
            # В ru-выжимке kaikki синонимы/антонимы лежат на верхнем уровне записи;
            # senses[].synonyms в этом издании пусты (проверено сканом), но читаем
            # и их — страховка от смены формата при будущих пересборках.
            s_words, a_words = extract(rec.get("synonyms")), extract(rec.get("antonyms"))
            for sense in rec.get("senses", []):
                s_words |= extract(sense.get("synonyms"))
                a_words |= extract(sense.get("antonyms"))
            s_words.discard(word)  # слово само себе не синоним
            a_words.discard(word)
            if s_words:
                n_syn_rec += 1
                syn.setdefault(word, set()).update(s_words)
            if a_words:
                n_ant_rec += 1
                ant.setdefault(word, set()).update(a_words)

    # Абрамов — ВПЕРЁД, в авторском порядке; Викисловарь дополняет по алфавиту
    # (у него порядка нет, поэтому sorted честнее случайного).
    a_syn, a_ant, a_meta = abramov()
    сводно = {}
    for слой, свой, чужой in (("syn", a_syn, syn), ("ant", a_ant, ant)):
        итог = {}
        for k in set(свой) | set(чужой):
            v = list(dict.fromkeys(свой.get(k, []) + sorted(чужой.get(k, ()))))
            v = [w for w in v if w != k]
            if v:
                итог[k] = v
        сводно[слой] = итог

    n_усилителей = без_усилителей(сводно)

    # ё/е: ключ с ё ДОБАВЛЯЕТСЯ к ключу с е (елка → и то, что знает ёлка),
    # значения не трогаем. Почему только ключи: ищут по слову как набрали, а
    # показывать надо как в словаре. Именно ДОБАВЛЯЕТСЯ, а не подменяет: когда
    # в словаре есть и «желчь», и «жёлчь», подмена молча теряла бы одну из
    # статей — поймано сверкой со старым файлом (208 ключей похудели).
    for layer in сводно.values():
        for key in [k for k in layer if "ё" in k]:
            alt = key.replace("ё", "е")
            if alt != key:
                layer[alt] = list(dict.fromkeys(layer.get(alt, []) + layer[key]))

    result = {
        "syn": {k: сводно["syn"][k] for k in sorted(сводно["syn"])},
        "ant": {k: сводно["ant"][k] for k in sorted(сводно["ant"])},
        "meta": {
            **a_meta,
            "source": "kaikki.org ru-extract.jsonl.gz (ru.wiktionary.org, raw wiktextract)"
                      " + Абрамов 1900 (data/raw/abramov_dict1w.txt)",
            "built": time.strftime("%Y-%m-%d %H:%M:%S"),
            "lines_read": n_lines,
            "ru_records": n_ru,
            "records_with_syn": n_syn_rec,
            "records_with_ant": n_ant_rec,
            "wiktionary_syn_keys": len(syn),
            "wiktionary_ant_keys": len(ant),
            "adverb_boosters_dropped": n_усилителей,
            "syn_keys": len(сводно["syn"]),
            "ant_keys": len(сводно["ant"]),
            "build_seconds": round(time.time() - t0, 1),
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    m = result["meta"]
    print(f"строк: {m['lines_read']}  ru-записей: {m['ru_records']}  "
          f"syn-ключей: {m['syn_keys']}  ant-ключей: {m['ant_keys']}  "
          f"{m['build_seconds']}с  → {OUT} ({OUT.stat().st_size // 1024} КБ)")


if __name__ == "__main__":
    build()
