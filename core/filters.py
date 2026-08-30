# extendo — the smart filter. Turns thousands of dumb candidates into a ranked
# shortlist. Cascade order is cheapest → most expensive (drop the bulk early so
# the costly checks see few lines). Every stage is data-free — no step reads
# accepted/favorited history to steer future output (removed 2026-07-14, user:
# "всё что отвечает за алгоритмическую оценку предпочтений пользователя и из
# этого коррекции выдачи текста — стоит убрать"). Ranking uses only intrinsic,
# per-candidate properties (meter for grammar lines; nothing learned for real
# text) — what you've favorited before no longer biases what you see next.
#
# The remaining knobs (clean.knobs) parameterise everything here — nothing is a
# hard constant (that's the product, not cosmetics):
#   meter     — metric strictness (formal-validity gate)
#   banal     — banality cutoff
#   explore   — share of the shortlist reserved for deliberately-novel lines
#   shortlist — how many lines to surface

from __future__ import annotations

import json
import random
import re
from operator import itemgetter

# `from wordfreq import zipf_frequency` снят 2026-08-20 вместе с ручкой
# «Банальность» — она была единственным читателем частот в этом процессе.

import numpy as np

# НАДГРОБИЕ 2026-08-29: `import embeddings` — векторы navec читались ради
# темы (relevance, центроиды якоря). Тема вырезана; сам модуль жив, его
# держит слой «близкое» в core/wordsuggest.py.
import nlbridge
import редкость as _редкость
import доли as _доли
import nlindex          # колоночный индекс корпуса (Раунд 31); None-безопасен
import scan as scan_mod
from corpus import lemmatize
import кэш               # кэш ударений: он же и отвечает, есть ли что читать

VOWELS = "аеёиоуыэюя"

# ЗАТРАВКА КЛИШЕ ПОЧИНЕНА И СВЕДЕНА К ЧЕСТНОЙ (Раунд 57).
#
# Карта воронки показала: эта ступень отсекала 54 строки из 2 434 632 — то есть
# была выключена, а пользователь об этом не знал. Разбор показал почему:
#   · «сердце боль» и «любовь кровь» искались ПОДСТРОКОЙ ПОДРЯД. В живом тексте
#     между этими словами всегда что-то стоит («сердце от боли»), и совпадения
#     не бывало никогда;
#   · «308» ловило любое число с такими цифрами — год, номер страницы, сумму.
#     Одна из четырёх записей работала, и работала неправильно.
#
# В комментарии рядом с рождения стояло: «крошечная затравка, настоящий список
# растит чёрный список пользователя». Чёрного списка тогда не существовало — он
# появился в этом же раунде и делает ровно это: слово или сочетание, по
# начальным формам, целыми словами, со счётчиком «сколько строк убирает».
#
# Поэтому здесь остаётся ЧЕСТНАЯ затравка: пары слов, стоящие рядом с точностью
# до одного слова между ними, и никаких чисел. Всё остальное — в чёрный список,
# где пользователь видит цену каждого правила и может его снять.
_CLICHE_SEED = (
    r"сердц\w*\s+(?:\w+\s+)?(?:боль|бол\w+)",
    # Скобки обязательны: без них ветка «любв\w*» срабатывала САМА ПО СЕБЕ, и
    # правило уносило каждую строку со словом «любовь» — вдесятеро больше, чем
    # задумано. Поймано проверкой на одиночных словах.
    r"(?:любв|любов)\w*\s+(?:\w+\s+)?кров\w*",
    r"как\s+в\s+кино",
)
# Один компилированный паттерн по сидам (тот же приём, что _mat_pattern ниже):
# при пуле 2.87M записей genexpr `any(c in low for c in _CLICHE_SEED)` был
# крупнейшей статьёй промаха кэша _score_strict_table (~48% под профайлером —
# генераторный фрейм на каждую из ~2.9M строк); один C-поиск его убирает.
# Затравка — уже РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ (Раунд 57), поэтому без re.escape: они
# описывают пары слов с допуском на одно слово между ними, а не буквальные
# подстроки. Один компилированный паттерн, как и был: при пуле 2.87M записей
# genexpr по сидам был крупнейшей статьёй промаха кэша.
_CLICHE_RE = re.compile("|".join(_CLICHE_SEED))

# --- Честный фильтр мата (2026-07-31, решение прожарки PLAN.md: «"без мата"
# пишется по-честному (корни + формы)») -------------------------------------
# Ключевое требование — НОЛЬ ложных срабатываний на обычной речи, поэтому
# НИКАКОГО substring по всей строке: «рубля» содержит «бля», «команда» —
# «манд», «хлеб» и «себя» — «еб», «характер» — «хер». Проверка идёт строго
# ПО НАЧАЛУ токена (плюс известные глагольные приставки), с явными списками
# исключений для корней, задевающих обычные слова. Нормализация: lower + ё→е;
# «ъ» СОХРАНЯЕТСЯ — именно он отличает «съебаться» от «себя» (см. _MAT_PREFIXED).
# Пропустить редкую форму — приемлемо; поймать обычное слово — нет.

# Корни, ловимые с НАЧАЛА токена. Значение — продолжения-исключения: токен,
# где сразу после корня идёт одно из них, — обычное слово, не мат.
_MAT_START = {
    "хуй": (), "хуе": (), "хуя": (),            # хуйня, хуево(←хуёво), хуярить
    "пизд": (),                                  # пизда, пиздец, пиздёж→пиздеж
    # «еб» с начала токена: ебать/еби/ебло/ебан/ебуч/ёб→еб — обычных слов,
    # начинающихся на «еб», в русском нет («себя/хлеб/требует» отсекает само
    # требование начала токена); единственное исключение — ЕБРР (банк).
    "еб": ("р",),
    "бля": ("х", "ш"),                           # бляха, бляшка — не мат
    # Решение прожарки: сук- шире не брать (сука/сук неоднозначно). «сучком/
    # сучков» — однозначно формы сучка-ветки («веток и сучков» — обычная
    # речь, найдено свипом по топ-100k wordfreq); остальные формы делят
    # написание с «сучкой» и остаются пойманными.
    "сучар": (), "сучк": ("ом", "ов"),
    "мудак": (), "мудач": (), "мудил": (),       # мудак, мудачьё, мудила
    "гандон": (), "гондон": (),
    "залуп": (),
    "дроч": ("ен",),                             # дрочёна — блюдо
    "манд": ("арин", "ат", "олин", "р", "ал", "ел"),  # мандарин, мандат(ный), мандолина,
                                                 # мандраж/мандрагора, мандала, Мандела/Мандельштам
    "шлюх": (),
    "пидор": (), "пидар": (), "пидр": (),        # пидор(ас), пидарас, пидрила
    "херн": (), "херов": (), "херач": (),        # херня, херовый, херачить; сам «хер» — только точный токен ниже
    "долбо": (),                                 # долбоёб→долбоеб
    "елд": (),
    "курв": ("иметр",),                          # курвиметр — прибор
    "трахн": (), "траха": (),                    # только глагольные (трахнул, трахаться); «трах» сам — звукоподражание
}

# Точные токены ЦЕЛИКОМ — у этих корней продолжения дают обычные слова
# (хулиган/хулить/хуление, сукно/сучок, херувим/херес), поэтому префиксная
# проверка невозможна: только полная форма.
_MAT_EXACT = ("хули", "хуле",
              "сука", "суки",
              "хер", "хера", "херу", "хере", "хером", "херь")

# Мат и ПОСЛЕ приставки: заебись, похер, схерачить, спиздил. Для «еб»
# согласные приставки — только через «ъ» (отъебись, съебаться): прямое
# «с»+«еб» дало бы ложное срабатывание на «себя/себе» — ровно тот класс
# ошибок, который этот фильтр обязан исключить.
# «раз» и его оглушённый вариант «рас» (распиздяй) — оба реальные приставки.
_PREF = ("вы", "за", "при", "у", "на", "по", "до", "о", "от", "под", "раз", "рас", "с", "об", "в")
_MAT_PREFIXED = {
    "еб":   ("вы", "за", "при", "у", "на", "по", "до",
             "отъ", "подъ", "разъ", "съ", "объ", "въ"),
    "хуй":  _PREF, "хуе": _PREF, "хуя": _PREF,   # нахуй, похуй, охуеть, захуярить
    "пизд": _PREF,                               # спиздил, напиздел, распиздяй, опизденеть
    "хер":  ("по", "с", "на", "о", "до"),        # похер(ить), схерачить, нахер, охереть, дохера;
                                                 # «за» нарочно НЕТ — торт «захер», Захер-Мазох
    "дроч": ("по", "за", "на"),                  # подрочить, задрочить, надрочить
}


def _mat_pattern() -> re.Pattern:
    """Один компилированный паттерн из данных выше — единственный источник
    правды остаётся в _MAT_*, регэксп только собирается из них (скорость:
    один C-поиск на строку вместо питон-цикла по ~30 корням на каждый токен
    каждого из ~150k фрагментов пула). `(?<![а-я])` — граница начала токена
    (текст уже lower + ё→е, так что [а-я] покрывает всё, включая «ъ»);
    точные токены дополнительно требуют конца токена."""
    def root(r: str) -> str:
        exc = _MAT_START.get(r, ())
        return r + (f"(?!(?:{'|'.join(exc)}))" if exc else "")
    parts = [root(r) for r in _MAT_START]
    parts += [f"(?:{'|'.join(prefs)}){root(r)}" for r, prefs in _MAT_PREFIXED.items()]
    parts.append(f"(?:{'|'.join(_MAT_EXACT)})(?![а-я])")
    return re.compile(f"(?<![а-я])(?:{'|'.join(parts)})")


_MAT_RE = _mat_pattern()


def has_mat(text: str) -> bool:
    """Есть ли в строке мат — по началу токенов, не substring (см. блок
    данных выше). Публичная: тесты (tests/test_mat_filter.py) и оба пути
    отсева кандидатов — грамматические строки (run, stage 3) и
    nakedlunch-фрагменты (_score_strict_table / _nl_scored) — зовут её."""
    return _MAT_RE.search(text.lower().replace("ё", "е")) is not None

# НАДГРОБИЕ 2026-08-18: `_NL_RHYME_PATH = пути.артефакт("nl_rhyme.json")` убран
# (вместе с ним — импорт `пути`, других читателей у него здесь не было).
# Это была ВТОРАЯ копия `кэш.СТАРЫЙ` (буквально то же выражение), и жила она
# сторожем: `if _NL_RHYME_PATH.exists()`. Читал же код через `кэш.читать_всё()`,
# который предпочитает построчный `nl_rhyme.jsonl`. В доме с одним только
# `.jsonl` сторож отвечал «нечего» при полном кэше рядом — замер на временном
# доме: `кэш.есть_строчный()` True, `читать_всё()` отдаёт запись, а после
# `warm_caches()` в `_NL_RHYME` ноль записей. Теперь спрашиваем у загрузчика
# (`кэш.есть()`), и список форматов остаётся один — в `core/кэш.py`.
_NL_RHYME: dict = {}


def warm_caches() -> None:
    """Прогрев кэша фрагментов к первому запросу.

    НАДГРОБИЕ: `zipf_frequency("слово", "ru")` УБРАН ОТСЮДА 2026-08-20. Он
    распаковывал русскую частотную таблицу wordfreq (~100 мс) ради ручки
    «Банальность» — единственного, что спрашивало частоты в процессе сервера.
    Ручка удалена целиком (см. надгробие в core/nlindex.py), а колонку `banal`
    печёт ОТДЕЛЬНЫЙ ПРОЦЕСС (`core/дочерний.py` запускает сборщики детьми), так
    что серверу таблица больше не нужна ни разу.

    2026-08-01: nl_rhyme.json вырос до 946MB / 2 868 100 записей (пользователь
    залил ~40 книг в июне-июле; кэш строится по ВСЕМ корпусам стора, включая
    выключенные — см. tools/build_nl_rhyme.py). Эта загрузка теперь ~9-11s
    и ~5.5GB RSS на весь срок жизни процесса — главный вклад в память
    сервера на 16GB-машине."""
    global _NL_RHYME
    # РАУНД 34: когда колоночный индекс на месте и своей версии правил, JSON
    # не грузится ВООБЩЕ. Он был нужен двум последним читателям — «классике»
    # (light=True) и вкладке «строкой» в попапе; оба переехали на индекс, и
    # держать 946 МБ файла ради ничего больше незачем. Индекс отвечает через
    # mmap: старт перестаёт платить ~14 с и ~5.5 ГБ RSS на весь срок жизни
    # процесса. Индекса нет или он чужой версии — грузим JSON как раньше, и
    # весь старый путь работает: это не запасной режим «на всякий случай», а
    # единственный способ вообще что-то ответить, пока индекс не испечён.
    if nlindex.available():
        return
    if кэш.есть():
        # {text: {"key", "span", "banal", "taut", "lemmas", "tokens"}} — see
        # tools/build_nl_rhyme.py's module docstring for what each field is
        # and why they're precomputed offline (2026-07-14: makes a FULL-pool
        # scan on every request cheap — see _nl_scored). Format bump from
        # earlier {text: {"key","span"}}-only — build a fresh
        # core/data/nl_rhyme.json via tools/build_nl_rhyme.py --full if this
        # is loading a pre-bump file, its entries will be missing fields.
        # ЧЕРЕЗ ОБЩИЙ ЧИТАТЕЛЬ (Раунд 57): он предпочитает построчный формат,
        # если тот есть. Разбор одной гигантской строки давал пик вдвое больше
        # результата; поток — ровно столько, сколько занимает сам словарь.
        _NL_RHYME = кэш.читать_всё()


# НАДГРОБИЕ: `_без_имён` и `_banality` УДАЛЕНЫ 2026-08-20.
#
# `_banality(line)` считала частоту самого редкого знаменательного слова строки
# (zipf, имена собственные вон — их редкость свойство имени, а не находка
# автора, Раунд 57). Она обслуживала гейт ручки «Банальность» в `run()` и
# больше ничего. Ручка удалена целиком по замеру — разбор в надгробии
# core/nlindex.py.
#
# ТА ЖЕ ФОРМУЛА ЖИВА В ДВУХ МЕСТАХ, И ЭТО НЕ ЗАБЫТЫЙ ХВОСТ:
#   · tools/build_nl_index.py печёт колонку `banal` — по ней `wordsuggest`
#     сортирует подсказки слов;
#   · tools/build_nl_rhyme.py пишет то же поле в запасной кэш.
# Колонка остаётся, RULES не меняются, перепечка не нужна.


def _content(line):
    return [w for w in line.words if w.pos in ("NOUN", "ADJF", "VERB")]


def _tautology(line) -> bool:
    """Two content words sharing a 4-char stem, or a lemma repeated — 'ночная
    ночь', 'холодный холод'. Precise for the failure mode the real run showed."""
    cw = _content(line)
    lemmas = [w.lemma for w in cw]
    if len(set(lemmas)) < len(lemmas):
        return True
    stems = [w.surface[:4] for w in cw if len(w.surface) >= 4]
    return len(set(stems)) < len(stems)


def _text_tautology(lemmas: list) -> bool:
    """Same defect as _tautology ('ночная ночь'), for plain-text nakedlunch
    fragments — no Word objects, so the stem check runs on lemma strings
    (not surface forms) as the closest available approximation."""
    if len(set(lemmas)) < len(lemmas):
        return True
    stems = [l[:4] for l in lemmas if len(l) >= 4]
    return len(set(stems)) < len(stems)


def _cand_lemmas(line) -> set:
    # Word.lemma is the lemma generation actually inflected FROM — always
    # correct by construction, and free (no re-parse). The shortlist ships this
    # set to the client, which echoes it back on accept (server.api_mark), so
    # the corpus stores the SAME lemmas rather than re-guessing from surface
    # text (which mis-lemmatizes homographs like 'бит'→'битый').
    return {w.lemma for w in _content(line)}


# Bias range for the STRICT tier's percentile-target scoring below — see
# _nl_scored's own docstring. +0.4 at a perfect percentile match, -0.4 at the
# worst possible (opposite-extreme) mismatch — same magnitude the old
# `0.4*sem` bias used, so downstream blending (e.g. _diversify's
# `(1-div)*score + div*(1-sim)`) sees a comparable scale, not a discontinuity.
_PCTL_SCALE = 0.8

# Cosine-similarity ceiling above which a line counts as "too similar to the
# anchor" — see _select_with_rhyme's theme-anchor mechanism. Chosen
# conservatively (only catches near-paraphrase, not "shares the topic") since
# there's no labeled data to tune it against; revisit if live testing shows
# it's too loose or too strict.
_ANCHOR_SIM_CEILING = 0.92

# «Ещё не считали» — отдельно от `None`, потому что `None` здесь законный ОТВЕТ
# («у модели нет мнения об этих леммах»), и путать их значило бы пересчитывать
# самые дорогие случаи по кругу.
_НЕ_СЧИТАН = object()

# НАДГРОБИЕ: РУЧКА «СВЯЗНОСТЬ» УДАЛЕНА 2026-08-21.
#
# Она прибавляла к рангу кандидата за близость к ЦЕНТРОИДУ ПРЕДЫДУЩЕЙ строки:
# `flow_target = _FLOW_MAX(0.6) * flow * (_FLOW_EDGE(0.75) на стыке блоков)`,
# `rank += _FLOW_W(0.9) * (1 - |cos - flow_target|)`. Единственный механизм в
# программе, судивший строфу как ЦЕЛОЕ, а не строку по одной.
#
# ЗАМЕР ПОДТВЕРДИЛ, ЧТО ОНА ЖИВАЯ (2026-08-21, 40 строф «абаб» на положение):
# косинус соседних строк 0.0 → +0.008, выкл → +0.187, 1.0 → +0.292,
# перестановочный P < 0.0001. То есть механизм работал.
#
# УДАЛЕНА НЕ ЗА МЁРТВОСТЬ, А ЗА ОТСУТСТВИЕ ПОЛЬЗЫ — и это решил ЖУРНАЛ:
# из 25 строф, давших хоть одну сохранённую строку, 48% отдали ровно одну, а
# три последних сохранения сделаны в ОДНУ СЕКУНДУ и между собой не связаны
# никак («Боб Арчер «Пользователь» · «выглядит Монмартр» · «треск белых
# взрывов»). Владелец собирает ОТДЕЛЬНЫЕ находки, а соседей выбрасывает.
# Связность решает, что стоит РЯДОМ, — то есть управляет ровно тем, что он
# не уносит.
#
# Довод «пригодится куплетам и припевам» отвергнут им же: «нахуя мне припевы
# и хуки если я пайплайн и серию убрал и только строфы генерю». Цепь и серия
# вырезаны Раундом 63 по его словам «Pipeline и серия с практической точки
# зрения бесполезны. Строфа единственным режимом и всё».
#
# ЧТО ОСТАЛОСЬ ЗАПИСАННЫМ, ЕСЛИ ПОНАДОБИТСЯ ВЕРНУТЬ: возвращать надо НЕ этой
# прибавкой к рангу (у неё верхняя половина мертва — 0.5 и 1.0 дают +0.287 и
# +0.292, и потолок +0.292 не достаёт даже до самого связного референсного
# текста владельца, 0.35), а ПОЛОСОЙ-ФИЛЬТРОМ с равновероятным жребием
# внутри. Прототип замерен 2026-08-21: цель 0.00 → +0.016, 0.15 → +0.214,
# 0.30 → +0.381, 0.45 → +0.529 — вдвое шире размах и честная шкала, цена
# +70 мс на строфу, перепечка не нужна (`Index.relevance` уже считает ровно
# эту форму). Разбор — план, часть 12.
# `_FLOW_MAX` / `_FLOW_W` / `_FLOW_EDGE` жили здесь же и удалены вместе с ней.
#
# Здесь же лежала `_cos(a, b)` — косинус двух центроидов, БЕЗ вызова
# `np.linalg.norm`: оба аргумента приходили из `embeddings.lemma_centroid`,
# который делит на длину сам, поэтому нормы всегда 1.0 и косинус сводился к
# скалярному произведению. Это было замерено, а не предположено: 124 015
# вызовов на трёх прогонах, максимальное отклонение длины от единицы 1.19e-07,
# экономия 0.63 с из 0.92 с всего косинуса в профиле.
#
# Осиротела 2026-08-21: прибавка к рангу за связность была её ЕДИНСТВЕННЫМ
# вызывающим. Якорь темы, вторая работа с центроидами, считает скалярное
# произведение у себя (`float(cc @ ac)` в `has_anchor_conflict`) и через `_cos`
# никогда не ходил. Если функция понадобится снова — вместе с ней вернуть и
# правило: производитель центроидов обязан отдавать единичные векторы.


def _nl_scored(fragments, corpus, hidden, tags=None, light=False,
               theme_sims=None, literal_cap=None, forced=None, cohesion=0.5,
               no_mat=False, only_mat=False, clausula=0, внутр_рифма=0,
               гсч=random):
    """Score raw nakedlunch fragments (real cut-up text, no Word/stress
    structure) for the SAME shortlist grammar-candidates land in:
    blacklist/cliché, tautology apply, same as generated lines — the user
    explicitly rejected exempting nakedlunch from filters generated lines get
    (2026-07-13). No preference/history-distance term (removed 2026-07-14,
    see module docstring) and no meter (a regularity score over FABRICATED
    stress positions the slot grammar controls by construction: real prose was
    never written to hit a beat, so there's no sound 'meter' to compute — not
    the same situation as rhyme/tautology, which are properties of the actual
    words on the page). Score is theme-bias (an intrinsic property of what
    was just typed, not a learned preference from accept/favorite history) —
    with nothing else left to rank by, this is what lets `run()` scan the
    the USER'S WHOLE active pool every time (2026-07-14: "пусть обрабатывается и
    перебирается всегда именно полная база") instead of a small sample, since
    the theme-relevant fragments among 150k+ candidates now surface by score
    instead of by luck of the sample.

    Theme-bias is TWO signals, not one (2026-07-17 — user: набрал «деньги»,
    получил «деньги» буквально в 19 из 20 строк, "я же говорил что не хочу
    так"). The old bias was `len(tags & tokens)`: any fragment containing the
    LITERAL theme word scored 0.6+1 against 0.6+0 for everything else — with
    hundreds of literal matches sitting in a 274k-fragment pool, they filled
    the shortlist almost entirely, drowning out fragments that carry the
    theme's MEANING without its exact spelling (user: "может не встречаться
    напрямую даже, но всё равно явно захватывать запрошенную тему"). Now:
    `embeddings.relevance` (core/embeddings.py, navec word vectors) scores how
    much of the theme's meaning the fragment's lemmas carry — smooth, works
    for "заплатить"/"наличные" same as literal "деньги". Literal match gets a
    FLAT bias (0.15), NOT added on top of its own semantic score — a literal
    fragment's lemmas trivially maximize their OWN cosine to the theme
    (measured: "они деньги платят" → sem=0.46 → an additive bonus would have
    scored it 0.29, ABOVE every purely-semantic line), so the two signals
    would compound and literal fragments would systematically outrank and
    cluster ahead of meaning-only ones — exactly the clustering a live test
    caught even after the cap below (all 4 lines of the first stanza were
    literal). Flat, decoupled bias lets literal and semantic fragments
    compete on equal footing. `literal_cap` (computed by `run()` from the
    requested shortlist size and stanza length) then hard-drops excess
    literal-match fragments after scoring (a random subset, since ties are
    now common — see the cap code), keeping roughly ONE literal occurrence
    per stanza's worth of
    output instead of unboundedly many — the rest of the theme's presence
    comes from meaning, not repetition.

    banal/taut/lemmas/tokens are read from tools/build_nl_rhyme.py's offline
    cache (`_NL_RHYME`), NOT recomputed here — that's what makes scanning the
    full pool on every request cheap (dict lookups, not pymorphy3/zipf calls;
    see that script's own module docstring for the benchmark). A fragment
    missing from the cache (added since the last build) has no known
    banal/taut, so the STRICT tier skips it rather than guessing; "классика"
    doesn't need that data at all and still lemmatizes it live (rare path).

    `light=True` — крутилка «Классика». РАУНД 35: она отдаёт СЫРЬЁ как есть,
    то есть равномерно случайные куски активного пула, как и делает сам
    ~/nakedlunch (`nlsrc/generator.generate_four` → `rng.sample(pool, 4)`).
    Не применяется ничего: ни клише, ни банальность, ни тавтология, ни тема,
    ни принудительные слова, ни ограничитель повторов темы. Оценка у всех
    строк одна и та же, поэтому перемешивание у вызывающего даёт честную
    случайность. Остаются два жёстких инварианта, общих для всех режимов и не
    являющихся мнением о качестве: не показывать скрытое историей/избранным
    (`hidden`) и уважать долю мата.

    До Раунда 35 докстринг утверждал, что тема тут не применяется, а код её
    применял (`0.15 за литерал / 0.4 * sem`) — разошлись при какой-то из
    правок. Теперь совпадают, и зеркалом служит nlindex.select_light. Callers only pass them into the strict-tier
    call, see `run()`.

    `forced` (2026-07-17, PLAN.md 0.2b — `!слово` syntax) is a DIFFERENT
    guarantee from ordinary theme words: not "≈1 per stanza" but "≥1
    somewhere, or say so honestly." A forced word still gets the SAME flat
    0.15 literal bias as any other literal match (no special ranking boost —
    the guarantee comes from placement in `run()`, not from score), and is
    EXEMPT from `literal_cap`'s dropping (a forced fragment must survive to
    be available for `run()`'s placement step even if the ordinary cap would
    otherwise have trimmed it). Returns `(out, forced_candidates)` —
    `forced_candidates[word]` is every STRICT-tier-quality fragment
    containing that word literally, for `run()` to draw from; empty for a
    word that quality filters reject everywhere or don't exist in the pool
    at all — either way `run()` reports it honestly, never silently.

    `cohesion` (2026-07-18, THIRD attempt — see git-free history in
    DECISIONS.md Раунд 24/26 for the first two). Раунд 24 made bias SIGNED
    (`theme_pull = 2*cohesion-1`, -1..+1) so dissonance could push away from
    the theme, not just pull less toward it — real progress, but still a
    POSITIVE-OR-NEGATIVE SCALAR MULTIPLIER on a monotonic function of `sem`,
    and sort order is invariant to multiplying every item's key by the same
    positive constant. User, live-testing cohesion 0.50→0.55 on theme
    «секс»: "разница в выдаче огромная и очень резкая". Measured why:
    cohesion=0.55 (pull=+0.1) and cohesion=1.00 (pull=+1.0) picked the SAME
    top-8 fragments (7/8 overlap, identical top-4) — the whole 0.55..1.00
    range was ONE outcome, the whole 0.00..0.45 range was another, and 0.50
    was a coin flip (all scores tied at 0, `random.shuffle` decides). Three
    positions, not a dial.

    Fix: `cohesion` (0..1, passed straight from the knob — no more sign
    transform) is now a PERCENTILE TARGET, not a multiplier. Every STRICT-
    tier fragment's `sem` gets ranked into a percentile within the current
    theme's pool (`_score_strict_table`'s `_pctl`, 0=least relevant this
    pool has, 1=most); bias rewards fragments whose OWN percentile is close
    to `cohesion` and penalizes distance in EITHER direction:
    `bias = _PCTL_SCALE * (0.5 - abs(pctl - cohesion))`. At cohesion=1,
    that's monotonic in percentile (same ranking as always wanting max
    relevance — consonance, unchanged in effect from before); at cohesion=0,
    monotonic the OTHER way (max deviation); at cohesion=0.5, peaks for
    MIDDLING fragments and actively penalizes both extremes — a real,
    continuously-moving band instead of a coin flip. Every ~5% of knob travel
    now shifts which percentile SLICE of the pool wins, because the target
    itself moves continuously — no positive-multiplier invariance left to
    collapse it back to three positions. `forced` (`!слово`) is untouched —
    its guarantee runs entirely outside scoring, see _ensure_forced.

    Dropped the literal/non-literal branch in the STRICT tier entirely
    (2026-07-18) — a literal match's lemmas trivially maximize their OWN
    cosine to the theme (Раунд 22's finding), so it naturally lands at a high
    percentile without a separate carve-out; percentile-ranking is not
    additive the way the old raw-cosine bonus was, so Раунд 22's original
    compounding bug (literal + semantic stacking) can't recur here — there's
    only one signal (`sem` → `pctl`) now, not two competing for the fragment
    to win on. `light=True` ("классика") keeps the ORIGINAL flat-0.15/0.4*sem
    formula, cohesion-independent — that mode has always meant "no extendo
    opinion at all" (2026-07-14), and it's never received a cohesion argument
    from any caller (see `run()`), so this preserves its exact prior behavior.

    STRICT tier (`light=False`) scoring is cached across calls, keyed by
    (tags, banal_ceiling, forced) — see `_score_strict_table`. `cohesion` is
    deliberately OUT of the key now (percentile rank doesn't depend on it,
    only the final bias does) — a bonus of this fix: dragging the cohesion
    slider no longer busts the cache or re-scores the ~135k-fragment pool at
    all, only the final `bias`/`score` per already-cached row, which is
    orders of magnitude cheaper. 2026-07-18: user reported 5-10s per stanza;
    after fixing the O(n²) rhyme-anchor bug (see _select_with_rhyme) this
    function's own per-fragment loop was the next-largest cost (~0.3-0.6s of
    a ~2s request, cProfile-measured), and it repeats almost EXACTLY the same
    work on every call within one theme/knob session — a buffer refill, or
    freestyle re-prefetching its next 3 stanzas, all score the same
    ~135k-fragment pool against the same theme over and over. Splitting the
    (cacheable) scoring pass over `_NL_RHYME`'s full pool (~274k entries
    when this was written; 2 868 100 на 2026-08-01 — пользователь залил ~40 книг
    в июне-июле) from the (per-call, can't-cache) `hidden`/blacklist
    filtering over the CURRENT `fragments` means a cache hit skips
    embeddings.relevance/cliché/banal/tautology entirely and does only
    cheap dict lookups. `light=True`
    ("классика") is NOT cached — it's already the cheap path (skips banal/
    cliché/taut), and uniquely falls back to live `lemmatize()` for fragments
    missing from `_NL_RHYME`, which the cached table (built FROM `_NL_RHYME`
    alone) can't represent.

    `no_mat` (2026-07-31, PLAN.md: «"без мата" пишется по-честному») —
    жёсткий содержательный фильтр по началу токена (см. has_mat). В STRICT
    он живёт внутри кэшируемой таблицы (рядом с клише), в «классике» —
    здесь, рядом с blacklist: в отличие от банальности/тавтологии это не
    мнение о качестве, а явный запрос пользователя, поэтому действует в ОБОИХ
    режимах."""
    tags = set(tags) if tags else set()
    forced = set(forced) if forced else set()
    out = []
    forced_candidates = {w: [] for w in forced}
    # Нечего скорить — выходим ДО постройки таблицы (2026-08-02). При
    # «Источники 0» (только генератор) роут не даёт фрагментов вовсе, а
    # _score_strict_table всё равно строил таблицу по ВСЕМУ _NL_RHYME:
    # замерено 26.6с чистой работы, результат которой тут же выбрасывался
    # пустым циклом ниже.
    if not fragments:
        return out, forced_candidates
    # Чёрный список пуст у пользователя (0 записей) — а вызов шёл на каждый из
    # ~1.7М фрагментов: 1.2с на запрос под профайлером. Поведение то же:
    # any() по пустому списку — всегда False.
    if light:
        for text in fragments:
            if text in hidden:
                continue
            # «Без мата» действует и в «классике» (в отличие от банальности/
            # клише/тавтологии): это не мнение extendo о качестве, а явный
            # запрос пользователя на СОДЕРЖАНИЕ — та же категория жёстких
            # инвариантов, что blacklist и never-repeat.
            if no_mat and has_mat(text):
                continue
            # Антифильтр (Раунд 40): на максимуме крутилки в пуле остаётся
            # ТОЛЬКО мат — иначе рифмующийся партнёр находится чистым и доля
            # не добирается никогда.
            if only_mat and not has_mat(text):
                continue
            entry = _NL_RHYME.get(text)
            # Тот же порог, что в nlindex.gate_mask: строка обязана иметь хотя
            # бы два обычных слова. Путь без индекса обязан вести себя так же —
            # иначе выдача зависела бы от того, испечён индекс или нет.
            if entry is not None and entry.get("content") is not None \
                    and entry["content"] < nlindex.СЛОВ_МИН:
                continue
            # ВОРОТА ВНУТРЕННЕЙ РИФМЫ ДЕЙСТВУЮТ И БЕЗ КОЛОНОК (починка
            # 2026-08-29). Параметр функция ПРИНИМАЛА и нигде не применяла:
            # оба вызывающих его честно передавали, а `nlindex.gate_mask` и
            # `select_light` его исполняли — то есть ручка «Внутренняя рифма»
            # работала или нет в зависимости от того, испечён ли индекс.
            # Ровно то расхождение двух путей, на котором в этот же день
            # поймали молчаливый ноль у классики. Найдено правкой тестов.
            if внутр_рифма and not (entry or {}).get("inner"):
                continue
            if entry is None:
                lemma_list = lemmatize(text)
                key, span = "", None
            else:
                lemma_list = entry.get("lemmas", [])
                key, span = entry.get("key", ""), entry.get("span")
            # Клаузула — ПОСЛЕ того, как ключ посчитан. Раньше проверка стояла
            # выше по циклу и читала `key` ДО присваивания: на первом фрагменте
            # UnboundLocalError, на остальных — отсев по клаузуле ПРЕДЫДУЩЕГО
            # фрагмента. Баг был скрыт тем, что этот путь (классика без
            # колоночного индекса) на машине пользователя не исполняется — индекс
            # испечён, и режим уходит в nlindex.select_light. Найдено картой
            # Раунда 50: как только у клаузулы появляется своя ручка, путь
            # становится достижимым.
            # Фрагмент без известного рифмо-ключа воротам клаузулы не отвечает
            # (clausula("") == 0) и честно отсеивается — угадывать нечем.
            if clausula and (int(clausula) & 7) != 7 and not (
                    (кл := scan_mod.clausula(key)) and (1 << (кл - 1)) & int(clausula)):
                continue
            cl = set(lemma_list)
            syllables = sum(1 for ch in text.lower() if ch in VOWELS)
            # Оценка ПЛОСКАЯ и одинаковая у всех (Раунд 35). Тема здесь не
            # считается вовсе: «классика» — это изначальный нейкедланч, а он
            # делает rng.sample(pool, 4) и ничего не взвешивает. При равной
            # оценке перемешивание у вызывающего и даёт равномерно случайную
            # выборку. Зеркалит nlindex.select_light — разойтись этим двум
            # путям нельзя, иначе режим зависел бы от того, испечён индекс
            # или нет.
            row = {"text": text, "template": "nakedlunch", "meter": None,
                  "rhyme": key, "rhyme_span": span,
                  "syllables": syllables, "score": 0.6, "_lem": cl, "mat": has_mat(text),
                  "clausula": scan_mod.clausula(key),
                  "classic": True, "_literal": False, "_forced": False}
            out.append(row)
    else:
        # НАДГРОБИЕ: СТРОГАЯ ВЕТКА БЕЗ КОЛОНОК (2026-08-29). Здесь строилась
        # `_score_strict_table` — второй, дословарный движок отбора со своей
        # семантикой темы, буквальными вхождениями и перцентиль-рангом. Тема
        # вырезана, движок остался один (колонки индекса), и без индекса честнее
        # работать светлым путём выше, чем держать вторую машину ради минут
        # между установкой и первой выпечкой.
        raise RuntimeError("строгий ярус без колоночного индекса снят 2026-08-29 — "
                           "зови _nl_scored(light=True)")
    # ВОЗВРАТ ПОТЕРЯЛСЯ ПРИ СНОСЕ СТРОГОЙ ВЕТКИ (починка 2026-08-29). Он стоял
    # ПОСЛЕ обеих веток и отдавал их общий результат; строгую ветку вырезали
    # вместе с темой, и `return` уехал вместе с ней. Светлая ветка стала
    # проваливаться за конец функции и отдавать None — а оба её вызывающих
    # распаковывают пару:
    #     filters._run       →  nl_survivors, forced_candidates = _nl_scored(...)
    #     filters._classic_pool →  pool, _ = _nl_scored(...)
    # то есть `TypeError: cannot unpack non-iterable NoneType object` на ЛЮБОМ
    # прогоне без колоночного индекса — и в алгоритме, и в классике. Это ровно
    # то состояние, в котором живёт свежая установка до первой выпечки и любая
    # машина, где индекс разошёлся с кэшем рифм: генерация падала пятисоткой,
    # а не работала грубее, как обещано надгробием выше.
    return out, forced_candidates


# Вердикт «этот индекс отвечает нынешнему кэшу рифм» — кэшируется по самому
# объекту индекса (разбор ниже). Жил рядом со снесённой строгой таблицей и
# переехал сюда 2026-08-29 вместе с её удалением.
_index_verdict: tuple | None = None


def _index_for_current_cache():
    """Индекс, ЕСЛИ он испечён из того самого `_NL_RHYME`, что сейчас в
    работе, иначе None (тихо уходим на старый путь).

    Та же ловушка, из-за которой в ключе кэша строгой таблицы стоит
    `id(_NL_RHYME)`: тесты подменяют кэш синтетическим, а индекс на диске
    остаётся настоящим — без этой проверки он отвечал бы по чужому корпусу
    (поймано прогоном тестов при подключении, 4 падения). Проверяем число
    записей и что нулевой текст индекса вообще есть в текущем кэше — обе
    проверки O(1), вердикт запоминается по личности словаря.

    ПУСТОЙ `_NL_RHYME` — это НЕ «кэш не совпал», а нормальный боевой режим
    Раунда 34: индекс есть, поэтому JSON не грузился вовсе и сверять не с
    чем. Сверка нужна ровно тогда, когда кэш чем-то занят, — то есть в
    тестах и в старом режиме без индекса.

    В КЛЮЧЕ СТОИТ САМ ИНДЕКС (2026-08-18, из-за него была пятисотка). Ключ был
    `(id(_NL_RHYME), len(_NL_RHYME))` — то есть про КЭШ РИФМ и ни слова про
    индекс. Перезагрузка индекса этот ключ не двигала, и вердикт вечно отдавал
    ПРЕЖНИЙ объект, пока `nlindex.запрет()` брал свежий: колонки разной длины
    складывались, и каждый `POST /api/generate` отвечал
    «operands could not be broadcast together».
    ПОЧЕМУ ОБЪЕКТ, А НЕ `штамп()`. Штамп судит СОСТАВ (`n@отпечаток`), и после
    перепечки, не сдвинувшей ни одной строки (`--reban`, новая ось), он тот же
    — а объект уже другой, и прежний смотрит в отвязанные с диска файлы.
    Ссылка на объект строже штампа, стоит ноль (штамп — 44.5 мс на первый
    вызов) и держит ровно ту дисциплину, что расписана рядом в
    `nlindex._КЭШ_ИНДЕКС`: держим сам индекс, а не `id(idx)`, иначе новый
    объект ляжет по освободившемуся адресу и кэш отдаст чужое под видом
    своего."""
    global _index_verdict
    idx = nlindex.load()
    ключ = (idx, id(_NL_RHYME), len(_NL_RHYME))
    if _index_verdict is not None and _index_verdict[0] == ключ:
        return _index_verdict[1]
    if idx is not None and _NL_RHYME:
        try:
            if len(_NL_RHYME) != idx.n or idx.text(0) not in _NL_RHYME:
                idx = None
        except Exception:
            idx = None
    _index_verdict = (ключ, idx)
    return idx


# Кэш ударений снят НАМИ, потому что его заменил индекс, — а не «его не было».
# Различать обязательно: только в первом случае у нас есть право вернуть его
# обратно, если индекс уйдёт.
_КЭШ_СНЯТ_ИНДЕКСОМ = False


def _индекс_перепечён(idx) -> None:
    """Индекс перепечён — привести в порядок кэш ударений (подписка на
    `nlindex.при_перепечке`, зовётся из `nlindex.reload`).

    ЧТО БЫЛО СЛОМАНО. `_NL_RHYME` грузился один раз на импорте и не
    перечитывался НИКОГДА. Значит после перепечки в живом процессе он оставался
    от прежнего корпуса, `len(_NL_RHYME) != idx.n`, вердикт выше отвечал None —
    и генерация молча уезжала на медленный путь до перезапуска окна. Молча:
    ответ тот же, просто вдесятеро дольше.

    РЕШЕНИЕ ПО ЗАМЕРУ, А НЕ ПО ВКУСУ. Перечитать кэш стоит **17.8 с и ~4.7 ГБ
    RSS** — замерено на живом `core/data/nl_rhyme.jsonl` (786 МБ, 2 392 262
    записи): 200 000 записей читаются за 1.49 с и 400 МБ, дальше линейно. На
    16-гигабайтной машине это не «долго», а своп поверх уже поднятого индекса.
    Платить их незачем НИ ФОНОМ, НИ СИНХРОННО: свежий индекс отвечает ровно на
    те же вопросы (Раунд 34 — потому JSON и не грузится, когда индекс есть).
    Поэтому кэш не перечитывается, а СНИМАЕТСЯ: 0 с, и 4.7 ГБ возвращаются
    системе. Строгие таблицы, построенные из него, уходят следом — они по нему
    и считаны, и весят по ~0.4 ГБ каждая.

    ОБРАТНЫЙ ХОД ЕСТЬ, И ОН НЕ СИММЕТРИЧЕН ПО ЦЕНЕ. Если индекс перепекли и он
    НЕ поднялся (испечён другими правилами, оборван на записи), старому пути
    словарь снова нужен — вот тогда те самые 17.8 с и платятся. Это редкий
    случай и он честнее тишины: без словаря и без индекса генерация не ответит
    ничем.

    ВЕРДИКТ ЗДЕСЬ НЕ СБРАСЫВАЕТСЯ, И ЭТО НАРОЧНО. Соблазн дописать сюда
    `_index_verdict = None` большой — и это был бы ВТОРОЙ механизм того же
    самого: ключ вердикта держит сам индекс, значит перепечка двигает его без
    посторонней помощи. Два механизма одного и того же в этом проекте
    расходятся с гарантией; хуже того, второй скрыл бы поломку первого от
    сторожа (проверено: со сбросом здесь `tests/test_перепечка_индекса.py`
    зеленел даже с нарочно испорченным ключом)."""
    global _NL_RHYME, _КЭШ_СНЯТ_ИНДЕКСОМ
    годен = idx is not None and getattr(idx, "n", 0) > 0
    if годен:
        if _NL_RHYME:
            _NL_RHYME = {}
            _strict_score_cache.clear()
            _strict_score_cache_order.clear()
            _КЭШ_СНЯТ_ИНДЕКСОМ = True
    elif _КЭШ_СНЯТ_ИНДЕКСОМ and not _NL_RHYME:
        _КЭШ_СНЯТ_ИНДЕКСОМ = False
        warm_caches()


nlindex.при_перепечке(_индекс_перепечён)


# НАДГРОБИЕ: `_score_strict_table` — СТРОГИЙ ЯРУС БЕЗ КОЛОНОК (2026-08-29).
# Таблица баллов по фрагментам со своим кэшем: банальность, сцепка, мат,
# клаузула и СЕМАНТИКА ТЕМЫ (`embeddings.relevance`, перцентиль-ранг, буквальные
# вхождения). Это был второй движок отбора — старый, дословарный. Тема вырезана,
# а без неё таблица считала то же, что колонки индекса, только медленнее.

def _diversify(pool: list, k: int, div: float) -> list:
    """Greedy MMR pick: k items from pool (already sorted best-first), each
    high-scoring AND unlike the last few chosen (lemma-set Jaccard), so the
    result doesn't clump — used for both grammar candidates and nakedlunch
    fragments, which can be near-duplicate overlapping cuts of one sentence.

    A shared lemma with a recent pick is a HARD exclusion, not just a soft
    penalty in the score/diversity objective (2026-07-18 — user screenshot:
    «два чека» / «получил два чека» / «вот два чека» — the SAME salient word
    landed in 2 of 4 lines of one stanza, at the cohesion knob's own
    "diссонанс" extreme where a user reading the label would expect MORE
    variety, not less. Measured why: at cohesion=0, `div` is only 0.3 (not
    0), and objective = `(1-div)*score + div*(1-sim)` still lets a high-score
    repeat outscore a lower-score original when the pool is thematically
    narrow — the sim PENALTY was too weak to ever fully rule anything out.
    User: «такого никогда быть не должно вообще и близко» — not "less
    often", never. So repetition is now a hard floor the cohesion knob can't
    trade away; `div` only controls WHICH of the non-repeating survivors wins
    on score vs. novelty, exactly what "как крутилка выглядит" already
    promised. Falls back to the unfiltered pool only if EVERY remaining
    candidate would repeat (pool nearly exhausted) — a repeat is still better
    than an incomplete stanza."""
    pool = list(pool)
    chosen: list = []
    if pool and k > 0:
        chosen.append(pool.pop(0))
        while len(chosen) < k and pool:
            recent = [r["_lem"] for r in chosen[-3:]]
            candidates = [i for i, r in enumerate(pool) if not any(r["_lem"] & s for s in recent)]
            if not candidates:
                candidates = range(len(pool))   # pool exhausted of non-repeats — best-effort, not silent failure
            best_i, best_obj = candidates[0], -1.0
            for i in candidates:
                r = pool[i]
                sim = max((_j(r["_lem"], s) for s in recent), default=0.0)
                obj = (1 - div) * r["score"] + div * (1 - sim)
                if obj > best_obj:
                    best_obj, best_i = obj, i
            chosen.append(pool.pop(best_i))
    return chosen


# НАДГРОБИЕ: `_ensure_forced` — ГАРАНТИЯ СЛОВА «!слово» (2026-08-29).
# Он дожимал обязательное слово ПОСЛЕ отбора: искал строку с этим словом,
# ставил её в свободный слот и следил, чтобы она не порвала рифмо-группу.
# Обязательное слово вырезано вместе с темой по слову владельца («вырезать всё
# вместе с темой»). Поле `forced_notice` в ответе осталось пустым словарём —
# форма ответа не меняется ради сноса.

def _classic_pool(knobs, corpus, nl_fragments, *, hidden, no_mat, only_mat, clausula, cap,
                  гсч=random, семя=None):
    """Пул «классики»: активный пул минус история, с воротами мата и клаузулы.
    Колоночный путь и старый обязаны давать ОДНО И ТО ЖЕ — иначе режим зависел
    бы от того, испечён индекс или нет."""
    _idx = _index_for_current_cache() if nl_fragments else None
    if _idx is not None:
        pool, survived, ступени = nlindex.select_light(
            _idx, pool_mask=nlindex.pool_mask(_idx, nl_fragments),
            hidden_mask=nlindex.mask_of(_idx, hidden),
            no_mat=no_mat, only_mat=only_mat, clausula=clausula, cap=cap, seed=семя,
            редкость_слова=_редкость.разобрать_полосы(knobs.get("rare_word")),
            редкость_пары=_редкость.разобрать_полосы(knobs.get("rare_pair")),
            внутр_рифма=int(knobs.get("inner_rhyme", 0) or 0))
        return pool, survived, ступени
    # Позиционный `9.0` (потолок банальности «пропускать всё») снят 2026-08-20:
    # ворота удалены целиком, а на «светлом» пути их и так не было.
    pool, _ = _nl_scored(nl_fragments or [], corpus, hidden, light=True,
                         no_mat=no_mat, only_mat=only_mat, clausula=clausula, гсч=гсч,
                         внутр_рифма=int(knobs.get("inner_rhyme", 0) or 0))
    survived = len(pool)
    гсч.shuffle(pool)                   # оценка у всех одна — верхушки не существует
    return pool[:cap], survived, {}     # старый путь ступеней не считает — и не выдумывает


def _run_classic(knobs, corpus, nl_fragments, *, hidden, no_mat, only_mat, clausula,
                 mat_share, forced, cap, гсч=random, семя=None) -> dict:
    """«Классика» — ОТДЕЛЬНЫЙ путь, а не квота внутри общего (Раунд 50).

    Требование (2026-08-03): бинарный переключатель «алгоритм — классика»; в классике
    алгоритмических оценок не существует, это классическая нарезка..

    Раньше `classic` был долей 0..1, и ради смешивания двух ярусов В ОДНОЙ
    СТРОФЕ жили: две постройки пула разом, арифметика квот в трёх ветках и
    «третье измерение» позиций в _select_with_rhyme (_classic_slot_plan плюс
    четыре исключения по нему — классику освобождали от рифмы, от вилки
    слогов, от сужения по корзине и от роли якоря). При бинарном режиме всё
    это не нужно: не надо освобождать от рифмы то, что рифмы и не касается.

    Побочный выигрыш — цена. Раньше строгий ярус (16-43 секунды на промахе
    кэша строгой таблицы) считался ВСЕГДА, даже когда классика забирала всю
    выдачу целиком. Теперь при классике он не считается вовсе, как и
    грамматический генератор.

    Остаются ровно ЧЕТЫРЕ ограничения, и ни одно не мнение о качестве: какие
    книги в активном пуле, история показов, мат и клаузула. Это ВОРОТА — про
    то, что содержится, а не про то, насколько хорошо."""
    size = int(knobs["shortlist"])
    pool, survived, ступени = _classic_pool(knobs, corpus, nl_fragments, hidden=hidden,
                                            no_mat=no_mat, only_mat=only_mat,
                                            clausula=clausula, cap=cap, гсч=гсч, семя=семя)

    # Доля мата — единственное, что здесь ещё надо разложить. Без рифмо-схемы
    # раскладывать по позициям нечего (пары не существует), поэтому просто
    # набираем нужное количество матерных и добираем остальным. Края шкалы
    # (0 и 1) сюда не доходят: они уже сработали воротами в _classic_pool.
    if 0.0 < mat_share < 1.0 and pool:
        матерные = [r for r in pool if r.get("mat")]
        чистые = [r for r in pool if not r.get("mat")]
        надо = min(len(матерные), round(size * mat_share))
        shortlist = матерные[:надо] + чистые[:max(0, size - надо)]
        # добираем, если одной из сторон не хватило: сжимать выдачу из-за
        # доли — хуже, чем чуть промахнуться по проценту
        if len(shortlist) < min(size, len(pool)):
            есть = {id(r) for r in shortlist}
            shortlist += [r for r in pool if id(r) not in есть][:size - len(shortlist)]
        гсч.shuffle(shortlist)
    else:
        shortlist = pool[:size]

    # Тема в классике не действует по определению режима (Раунд 35), значит и
    # «!слово» гарантировать нечем. Говорим это прямо, а не выдаём за «нет
    # подходящей строки в базе» — врать о причине хуже, чем признать предел.
    forced_notice = {w: "classic" for w in (forced or ())}

    for r in shortlist:
        r["lemmas"] = sorted(r.pop("_lem"))
        r.setdefault("classic", True)
        r.setdefault("anchor", False)
        r.pop("_pctl", None)                 # у классики его и не было, но форма ответа одна

    return {
        "shortlist": shortlist,
        "funnel": {"generated": 0, "formal": 0, "redundancy": 0, "banality": 0,
                   "shortlist": len(shortlist),
                   "nl_fetched": len(nl_fragments or []), "nl_survived": 0,
                   "nl_used": len(shortlist),
                   "nl_classic_survived": survived, "nl_classic_used": len(shortlist),
                   # Классика грамматический генератор не запускает по определению
                   # режима — так и сказано, а не нулями в чужих счётчиках.
                   "gen_ran": False, "ступени": ступени},
        "forced_notice": forced_notice,
        "seed": _штамп_прогона(семя, пул=len(nl_fragments or []),
                               скрыто=len(hidden or ())),
    }


# ---------------------------------------------------------------------------
# СЕМЯ — ОДНО НА ПРОГОН (Раунд 62). Требование: «раз уж я выбираю настройку, я
# должен выбирать конкретный результат, и он должен воспроизводиться в
# точности».
#
# ЗАМЕР ДО ПРАВКИ (2026-08-13, полный индекс 2 434 632, схема абаб, 8 строк):
# два одинаковых вызова подряд совпадали на 0.0% по местам и на 0.0% по
# составу. Не «почти повторяется» — НЕ ПОВТОРЯЕТСЯ ВОВСЕ.
#
# ПУТЕЙ ГСЧ ОКАЗАЛОСЬ ЧЕТЫРЕ, А НЕ ТРИ, как я записала в план. Четвёртый —
# грамматический генератор (`generate.generate(..., seed=None)`), и его зовёт
# не этот файл, а вызывающий (api/server.py). Поэтому семя
# ВЫБИРАЕТСЯ СНАРУЖИ и передаётся в оба места: закрепи только здесь — половина
# смешанного режима продолжала бы плавать. Замерено по ступеням:
#   · закрепить только `закрепить_разброс`      → 0.0% совпадения;
#   · плюс глобальный `random.seed`             → 0.0% по местам, 12.5% состава;
#   · плюс колоночный `nlindex.select(seed=)`   → 100% и по местам, и по составу.
# Проверено и МЕЖДУ процессами (PYTHONHASHSEED рандомизирован, подтверждено
# разными hash()): 8 из 8 строк совпали — порядок обхода множеств на выдачу не
# влияет, потому что колоночный путь работает номерами, а не множествами.
#
# ЧЕГО СЕМЯ НЕ ОБЕЩАЕТ. Оно воспроизводит выбор, а не материал: другой активный
# пул, другая история показов или пересобранный индекс — и та же цифра даст
# другой текст. Поэтому рядом кладётся штамп (nlindex.штамп + размеры пула и
# скрытого), чтобы приложение могло сказать это прямо, а не выдать чужое за то
# же самое.
#
# `гсч=random` по умолчанию у внутренних помощников — это МОДУЛЬ random, у
# которого те же `.shuffle`/`.random`, что у экземпляра. Значит любой прежний
# вызывающий (тесты зовут помощников напрямую) получает ровно старое поведение,
# а прогон целиком — свой поток.
def семя_прогона(семя) -> int:
    """Семя этого прогона: явное от вызывающего → закреплённое тестами → новое.

    Порядок именно такой. Явное сильнее закреплённого, иначе `закрепить_разброс`
    в conftest молча съедал бы семя, которое проверка передала нарочно.

    Публичная НАРОЧНО: грамматический генератор зовут снаружи (api/server.py,
    и раньше `filters.run`, поэтому число обязано выбираться
    ОДИН раз и до обоих — иначе ответ назвал бы семенем то, по которому
    грамматическая половина не собиралась."""
    if семя is not None:
        return int(семя) % (1 << 30)
    if _РАЗБРОС_СЕМЯ is not None:
        return int(_РАЗБРОС_СЕМЯ)
    return random.randrange(1 << 30)


def _штамп_прогона(семя: int | None, *, пул: int, скрыто: int) -> dict:
    """Что нужно знать, чтобы честно повторить прогон по номеру.

    `семя=None` значит «этот прогон шёл не по семени» — так отвечают прямые
    вызовы помощников из тестов. Подставлять сюда свежее число нельзя: штамп
    называл бы семенем прогона то, что прогоном не управляло."""
    return {"seed": семя, "index": nlindex.штамп(), "pool": пул, "hidden": скрыто}


# РАЗМЕР ПАЧКИ КАНДИДАТОВ, отдаваемой сборщику строфы. Замер 2026-08-20 — см.
# подробный разбор у `NL_SELECT_CAP` внутри `run`. Коротко: восьми кандидатов на
# строку хватает всегда, ниже 32 на строфу рифма начинает рваться, а прежний пол
# в 300 остался от времён, когда пачку набирали вслепую и годной была шестая
# часть. Держим числа здесь, а не по местам вызова: их два потребителя.
_ПАЧКА_НА_СТРОКУ = 8
_ПАЧКА_МИН = 32


def run(lines, knobs: dict, corpus, nl_fragments: list | None = None, rhyme: str = "none",
        tags: list[str] | None = None, forced: set[str] | None = None,
        stanza: list[dict] | None = None, семя: int | None = None) -> dict:
    """Прогон под замком индекса — весь разбор в `_run` ниже.

    ЗАМОК ЗДЕСЬ, А НЕ У ВЫЗЫВАЮЩЕГО (2026-08-18). Он стоял в `api/server.py`,
    вокруг этого самого вызова, и это работало ровно до тех пор, пока про него
    помнили: прогон берёт объект индекса в начале и спрашивает у него маски до
    самого конца, а перепечка, доехавшая в середину, оставляла запрос со
    старыми колонками и новой маской чёрного списка — та самая пятисотка
    «operands could not be broadcast together». Обязанность, о которой можно
    забыть снаружи, — это не починка, а договорённость; здесь её забыть нельзя.

    Замок реентрантный, так что вложенные обращения к индексу (`воронка`,
    `форма_пула`) внутри прогона встают без задержки."""
    with nlindex.ЗАМОК:
        return _run(lines, knobs, corpus, nl_fragments=nl_fragments, rhyme=rhyme,
                    tags=tags, forced=forced, stanza=stanza, семя=семя)


def _run(lines, knobs: dict, corpus, nl_fragments: list | None = None, rhyme: str = "none",
         tags: list[str] | None = None, forced: set[str] | None = None,
         stanza: list[dict] | None = None, семя: int | None = None) -> dict:
    """The cascade. Returns {shortlist, funnel, forced_notice, seed} — funnel is the
    per-stage survivor count so the user can SEE the filter working (and
    where yield is lost); forced_notice reports on `!слово` guarantees (see
    _ensure_forced). `rhyme` enforces a rhyme scheme (абаб, абав, etc.) in
    selection — see _select_with_rhyme. `tags` is the current theme's
    tokens, used ONLY to rank real-text fragments by bias-relevance (see
    _nl_scored) — an intrinsic property of the current query, not a learned
    preference. `forced` (PLAN.md 0.2b) is the subset of tags typed with a
    leading '!' — those get a HARD placement guarantee on top of the
    ordinary ranking, not just a probabilistic nudge.

    `stanza` (2026-07-18, PLAN.md 0.7 — the stanza constructor) is the
    ALREADY-VALIDATED spec from `clean.stanza_spec()` — a list of
    {letter, min_syl, max_syl}, same length as `rhyme`'s letters (the
    caller derives `rhyme` from it via `clean.stanza_letters()` before
    calling here; `run()` doesn't re-derive that itself, keeping the one
    validation/derivation step in clean.py, PRINCIPLES §6). `None` for
    every caller that only ever sends a plain scheme string — the syllable
    constraint layer is purely additive, see _select_with_rhyme's own
    `syllable_spec` docstring for exactly how soft it is.

    `семя` (Раунд 62) закрепляет ВЕСЬ случайный выбор прогона — см. блок
    «СЕМЯ — ОДНО НА ПРОГОН» выше. None означает «сними новое»; какое именно
    снялось, ответ говорит в `seed`, чтобы прогон можно было повторить."""
    n0 = len(lines)
    семя = семя_прогона(семя)
    гсч = random.Random(семя)
    # НАДГРОБИЕ: РУЧКА «МЕЛОДИЧНОСТЬ» УДАЛЕНА 2026-08-21. Здесь стояло
    # `meter_gate = 0.2 + 0.6 * knobs["meter"]`. Порог заморожен на её
    # замеренном умолчании (0.35 → 0.41) и режет только БЕЗНАДЁЖНО рваные
    # строки ГЕНЕРАТОРА — у строк корпуса meter=None по построению.
    #
    # ДВА ЗАМЕРА, УБИВШИЕ РУЧКУ:
    # 1. Метр: мертва на 89% прогонов (Источники >= 0.9 → строк генератора
    #    ноль); даже при Источники 0.5 весь ход давал жаккар 0.904.
    # 2. Замена «через звучность» (план, часть 5) ОТВЕРГНУТА 2026-08-21 по
    #    его же избранному: сохранённые строки чаще случайных содержат
    #    стечения согласных (34% против 17.7%, перестановочный P=0.0018,
    #    n=62) и МЕНЕЕ метричны (регулярность ударений 1.22 против 0.82).
    #    Любые ворота «к звучному» резали бы ровно те строки, которые он
    #    сохраняет. Признаки считаются честно — ухо им противоречит.
    #    Подробности — план, часть 11.
    meter_gate = 0.41
    # НАДГРОБИЕ: здесь считались `ворота = nlindex.ворота_банальности(...)` и
    # прокидывались в select / _nl_scored / _score_strict_table. Ручка удалена
    # целиком 2026-08-20 — разбор в надгробии core/nlindex.py.
    hidden = corpus.hidden_set()                    # history (not yet restored/expired) + favorites
    # СОБСТВЕННЫЙ СЛЕД ПРОГОНА НЕ ПРЯЧЕТСЯ ОТ НЕГО САМОГО (Раунд 62) — см.
    # corpus.тексты_прогона, там весь разбор. `getattr` с запасным вариантом
    # нарочно: `hidden_set` реализуют и заглушки в тестах, и менять их подпись
    # ради этого значило бы тянуть правку туда, где она ничего не значит.
    свой_след = getattr(corpus, "тексты_прогона", None)
    if свой_след is not None:
        hidden = hidden - свой_след(семя)
    # «Без мата» (2026-07-31, PLAN.md) — .get, а не knobs["no_mat"]: часть
    # тестов и старых вызовов собирает knobs-словарь руками, без clean.knobs;
    # для них флаг честно отсутствует = False, а не KeyError.
    no_mat = bool(knobs.get("no_mat", False))
    # Антифильтр — второе ворото той же ручки (см. clean.knobs: only_mat)
    only_mat = bool(knobs.get("only_mat", False))
    # Клаузула — Раунд 44, откалибрована по референсным текстам владельца
    # (см. scan.clausula). Рядом стояла `flow` — удалена 2026-08-21.
    clausula = int(knobs.get("clausula", 0) or 0)
    внутр_рифма = int(knobs.get("inner_rhyme", 0) or 0)
    # «Повтор» (Раунд 52, хук): снимает барьер на повтор леммы внутри строфы.
    # В классике не действует — там нет ни лемм, ни отбора по ним: классика
    # это нарезка корпуса, и `_run_classic` до `_select_with_rhyme` не доходит.
    repeat_ok = int(knobs.get("repeat", 0) or 0) >= 1

    # -- РАЗВИЛКА РЕЖИМА (Раунд 50) -----------------------------------------
    # Бинарно: либо алгоритм, либо классика — третьего не бывает. Ветка стоит
    # ДО каскада, потому что классике не нужен ни грамматический генератор, ни
    # строгий ярус: раньше оба считались всегда, даже когда классика забирала
    # всю выдачу (строгая таблица — 16-43 секунды на промахе кэша).
    # Порог 0.5, а не «== 1.0»: старые сохранённые настройки и тесты шлют
    # дробные значения, и молча трактовать 0.7 как «алгоритм» было бы враньём
    # о том, что просили. Половина и выше — классика.
    if float(knobs.get("classic", 0.0)) >= 0.5:
        return _run_classic(knobs, corpus, nl_fragments,
                            hidden=hidden, no_mat=no_mat, only_mat=only_mat,
                            clausula=clausula,
                            mat_share=float(knobs.get("mat_share", -1.0)),
                            forced=forced,
                            cap=max(300, int(knobs["shortlist"]) * 8),
                            гсч=гсч, семя=семя)

    # Тема без запихивания (2026-07-17, PLAN.md 0.2 — see _nl_scored for the
    # full story). `stanza_size` MIRRORS interface/react-app/src/App.jsx's
    # FREE_CHUNK=4 (no-scheme stanza length) — keep in sync, same discipline
    # as rhyme_scheme/normalizeScheme; drifting apart doesn't break anything,
    # it just makes "≈1 literal match per stanza" less accurate (this is a
    # soft cap over the whole returned buffer, not a per-window guarantee).
    # ТЕМА ВЫРЕЗАНА ЦЕЛИКОМ (2026-08-29, слово владельца: «вообще тему стоит
    # вырезать как функцию, она глупа и сложна в реализации», «вырезать всё
    # вместе с темой»). Здесь стояли: векторный замер близости всего словаря к
    # теме (`embeddings.theme_similarities`), предел «одна буквальная строка на
    # строфу» (`literal_cap`), нормализация обязательных слов `!слово`,
    # перцентиль-таргет связности (`cohesion`) и флаг тематического якоря.
    #
    # ЗАМЕР, КОТОРЫЙ РЕШИЛ ДЕЛО: из 8 116 прогонов журнала тема стояла в 255
    # (3.1%), и почти половина из них — «деньги», то есть прогоны тестов.
    # При этом ТОЛЬКО тема включала старый сборщик с пачкой в 320 кандидатов
    # из 2.3 млн строк — то есть 3% работы держали архитектурную стену для
    # остальных 97%. Со сносом темы стены нет: путь один и он по всему корпусу.
    #
    # Связность соседних строк (единственный механизм «строфа как целое») жила
    # на тех же векторах и уходит вместе с ними — это его осознанный выбор
    # («вырезать всё»), а не побочный ущерб: разбор был перед решением.
    stanza_size = len(rhyme) if rhyme != "none" else 4
    # Строфа-конструктор (2026-07-18, PLAN.md 0.7) — параллельный `rhyme`'s
    # буквам список (min_syl, max_syl) на позицию, или None у всех вызовов,
    # что шлют только строку схемы (см. _select_with_rhyme's syllable_spec).
    syllable_spec = [(row["min_syl"], row["max_syl"]) for row in stanza] if stanza else None
    # _diversify/_select_with_rhyme are O(shortlist × pool) — fine at a few
    # thousand candidates, not at the 100k+ a full-base scan can now survive
    # (2026-07-14: nl_fragments is the WHOLE active pool, see api/server.py).
    # Cap the WORKING selection pool to the best-scored slice (post-sort,
    # below) — same shape as the grammar path's own `scored[:max(300,
    # size*8)]`. This bounds SELECTION cost only; the actual filtering still
    # ran over the full pool moments earlier, so funnel counts stay honest —
    # see n_nl_survived/n_nl_classic_survived, captured before this cap.
    # ПОЛ В 300 УБРАН 2026-08-20. Он стоял с тех пор, когда кандидатов набирали
    # ВСЛЕПУЮ из всего пула: годных по слогам там было 6.1%, и триста тянули
    # ради восемнадцати пригодных. Теперь пачка набирается равновероятно среди
    # ПОДХОДЯЩИХ ФОРМЕ (`nlindex._равновероятно_по_форме`), то есть годны все —
    # и триста стали числом ниоткуда.
    #
    # Сколько нужно на самом деле — ЗАМЕРЕНО на живом индексе, по 40–60 прогонов
    # на точку, считались собранные строфы и сломанные схемы:
    #
    #   строфа «абаб» 4 строки:  пачка 8 и 16 — схема ломается 1 раз из 40;
    #                            с 32 и выше — ноль;
    #   боевой запрос, 9 строк:  пачка 72 — 60/60 собрано, 0 сломано, 0.7 мс;
    #                            пачка 300 — то же самое, но 2.1 мс.
    #
    # То есть формула `shortlist × 8` и была верной, а пол её перебивал. Он же
    # стоил втрое больше времени сборки ни за что. Нижняя граница 32 — не
    # круглое число, а край замеренного плато: ниже него рифма начинает рваться.
    NL_SELECT_CAP = max(_ПАЧКА_МИН, int(knobs["shortlist"]) * _ПАЧКА_НА_СТРОКУ)

    # -- stage 1: formal validity (syllable range + meter), skip hidden ------
    # The upper bound was a flat 13 (2026-07-14, before the stanza constructor
    # existed) — a profile whose syllable_spec asks for MORE than that (the
    # constructor UI allows up to clean.py's _SYL_MAX=30) had every grammar
    # candidate thrown away right here, before syllable_spec ever got a look
    # downstream (found 2026-07-19 chasing the Онегинская строфа bug report).
    # Track the active spec's own max instead of a number that predates it;
    # 13 stays the default for every scheme-string-only caller (syllable_spec
    # None), so nothing shifts for existing schemes.
    syl_ceiling = max((hi for _lo, hi in syllable_spec), default=13) if syllable_spec else 13
    stage1 = []
    for L in lines:
        if L.text in hidden:
            continue
        sc = scan_mod.scan(L)
        if sc.syllables < 4 or sc.syllables > syl_ceiling:
            continue
        if sc.meter < meter_gate:
            continue
        stage1.append((L, sc))
    n1 = len(stage1)

    # -- stage 2: internal redundancy / tautology ---------------------------
    stage2 = [(L, sc) for (L, sc) in stage1 if not _tautology(L)]
    n2 = len(stage2)

    # -- stage 3: blacklist + clichés + mat/clausula ------------------------
    # СТУПЕНИ БАНАЛЬНОСТИ ЗДЕСЬ БОЛЬШЕ НЕТ (2026-08-20): ручка удалена целиком,
    # см. надгробие в core/nlindex.py. Счётчик воронки `banality` остался под
    # прежним именем — он считает выживших ЭТОЙ ступени, а не банальность.
    # then score directly by intrinsic formal quality only (meter) — no
    # distance-to-favorites term anymore (removed 2026-07-14, see module
    # docstring): what you favorited before no longer pulls future output
    # toward or away from it, so there's no separate ranking stage left.
    scored = []
    for (L, sc) in stage2:
        low = L.text.lower()
        if _CLICHE_RE.search(low):
            continue
        # «Без мата» для грамматических строк — то же место отсева по
        # содержимому, что blacklist/клише; nl-путь фильтруется в
        # _score_strict_table/_nl_scored (см. has_mat).
        if no_mat and has_mat(L.text):
            continue
        if only_mat and not has_mat(L.text):
            continue
        if clausula and (int(clausula) & 7) != 7 and not (
                (кл := scan_mod.clausula(sc.rhyme or "")) and (1 << (кл - 1)) & int(clausula)):
            continue
        cl = _cand_lemmas(L)
        scored.append({"text": L.text, "template": L.template, "meter": round(sc.meter, 3),
                       "rhyme": sc.rhyme, "rhyme_span": sc.rhyme_span, "syllables": sc.syllables,
                       "score": round(sc.meter, 4), "_lem": cl, "mat": has_mat(L.text),
                       "clausula": scan_mod.clausula(sc.rhyme or "")})
    n3 = len(scored)

    # -- stage 3b: score real nakedlunch fragments (nl_mix knob) — same
    # banality/blacklist treatment as grammar candidates, minus meter/tautology
    # (see _nl_scored). Kept as a SEPARATE pool, not merged in: nl fragments are
    # typically outnumbered 100:1+ by grammar candidates, so even fair
    # tied-score competition drowns them to statistical invisibility (the same
    # failure shape as the old additive theme-weight bug in generate.py — a
    # slider needs an explicit RESERVED SHARE here, not a soft nudge).
    n_nl = len(nl_fragments or [])
    n_blocks = max(1, knobs["shortlist"] // stanza_size)
    # ── быстрый путь: колоночный индекс (Раунд 31) ───────────────────────────
    # Считает то же самое, но не материализует словарь на каждый из ~1.76M
    # выживших: селекции нужны только три ограниченных набора (верхушка по
    # оценке, резерв по перцентилю, резерв по слоговой вилке), и они же
    # собираются ниже старым путём. Индекса нет или он испечён по другим
    # правилам — молча работаем по-старому, поведение то же.
    # Ступени, как они происходят. Заполняются только на колоночном пути: на
    # старом их просто нет, и выдумывать числа, которых никто не считал, —
    # ровно та ложь, ради устранения которой воронка и переписана.
    ступени: dict = {}
    _idx = _index_for_current_cache() if nl_fragments else None

    # ПРЯМАЯ ТЯГА — ЕДИНСТВЕННЫЙ ПУТЬ (2026-08-29). Прежде она включалась при
    # четырёх условиях: есть индекс, есть слоговая вилка, есть рифмовка, нет
    # обязательного слова, нет тематического якоря и «Источники = корпус».
    # Три последних исчезли вместе с темой, словом и генератором — осталось
    # то, без чего строфу колонками не собрать физически.
    _прямая_тяга = bool(_idx is not None and syllable_spec and rhyme != "none")

    if _idx is not None:
        nl_survivors, n_nl_survived, forced_candidates, ступени = nlindex.select(
            _idx,
            pool_mask=nlindex.pool_mask(_idx, nl_fragments),
            hidden_mask=nlindex.mask_of(_idx, hidden),
            no_mat=no_mat, only_mat=only_mat,
            clausula=clausula,
            cap=NL_SELECT_CAP, reserve_n=min(1_000_000, max(30, n_blocks * 5)),
            syllable_spec=syllable_spec,
            per_bucket=1, seed=семя, схема=rhyme or "",
            тянуть_сразу=(int(knobs["shortlist"]) if _прямая_тяга else 0),
            mat_share=knobs.get("mat_share", -1.0), repeat_ok=repeat_ok,
            # ПОЛОСЫ РЕДКОСТИ РАЗБИРАЮТСЯ ЗДЕСЬ, А НЕ В СЕРВЕРЕ: так у ручки
            # один разбор на всех вызывающих (см. `редкость.разобрать_полосы`).
            редкость_слова=_редкость.разобрать_полосы(knobs.get("rare_word")),
            редкость_пары=_редкость.разобрать_полосы(knobs.get("rare_pair")),
            внутр_рифма=внутр_рифма,
            ярусы_рифмы=int(knobs["rhyme_tiers"]),
            # ДОЛИ КОНЦОВОК — разбираются здесь, как и полосы редкости: один
            # разбор на всех вызывающих (маска нужна разборщику, чтобы
            # выключенный чипом сорт не воскрес из сохранённой строки).
            доли_клаузул=_доли.разобрать(knobs.get("clausula_shares"),
                                         int(clausula) & 7 or 7),
            # ПОЗИЦИЯ РИФМЫ: 1 конечная · 2 внутренняя · 4 начальная. Единица —
            # прежнее поведение (рифмует последнее слово), и тогда ось не
            # разворачивает пул в пары «строка+ключ» вовсе.
            позиции_рифмы=(0 if int(knobs.get("rhyme_pos", 1) or 1) == 1
                           else int(knobs["rhyme_pos"])))
        nl_survivors_full = nl_survivors      # резервы уже внутри; ниже они не досчитываются
    else:
        # ИНДЕКСА НЕТ — ЧЕСТНЫЙ СВЕТЛЫЙ ПУТЬ, А НЕ ВТОРОЙ ДВИЖОК (2026-08-29).
        # Здесь стоял строгий безиндексный ярус (`_nl_scored` со всей темой и
        # `_score_strict_table`) — он умер вместе с темой. Остаётся дешёвый
        # разбор без колонок: ворота по мату, клаузуле и внутренней рифме.
        # Индекса не бывает только до первой выпечки; строфа в этот момент
        # собирается грубее, и это честнее, чем держать ради пяти минут в
        # жизни установки вторую машину отбора.
        nl_survivors, forced_candidates = _nl_scored(
            nl_fragments or [], corpus, hidden, гсч=гсч, light=True,
            no_mat=no_mat, only_mat=only_mat, clausula=clausula,
            внутр_рифма=внутр_рифма)
        гсч.shuffle(nl_survivors)
        nl_survivors.sort(key=lambda r: r["score"], reverse=True)
        n_nl_survived = len(nl_survivors)
        nl_survivors_full = nl_survivors
        nl_survivors = nl_survivors_full[:NL_SELECT_CAP]

    # -- stage 3c: «Классика» здесь БОЛЬШЕ НЕ СТРОИТСЯ (Раунд 50) ------------
    # До этого раунда рядом со строгим ярусом собирался второй, светлый пул, и
    # дальше две ветки сборки делили выдачу квотами classic_quota/algo_quota,
    # смешивая ярусы в ОДНОЙ строфе. Переключатель стал бинарным (требование: либо одно, либо другое.), и весь этот слой оказался недостижим: до сюда
    # доходит только алгоритм, классика ушла в _run_classic развилкой выше.
    # Вместе со слоем ушли и его подпорки в _select_with_rhyme — раскладка
    # классики по позициям и четыре исключения, освобождавшие её от рифмы,
    # от вилки слогов, от сужения по корзине и от роли якоря.

    # -- stage 5: assemble a SEQUENCE, not a ranked pile. Greedy diversification
    # (MMR): each next line is high-scoring AND unlike the last few chosen, so the
    # shortlist reads as flowing text with no near-repeats side by side.
    # Shuffle before the stable sort: meter ties identically across MANY
    # candidates (many lines hit the same regularity score), and a stable sort
    # on a tied score would otherwise keep insertion order every time.
    гсч.shuffle(scored)
    scored.sort(key=lambda r: r["score"], reverse=True)
    size = min(knobs["shortlist"], len(scored) + len(nl_survivors))
    # РАЗНОС СОСЕДЕЙ — КОНСТАНТА (2026-08-29). Он считался от ручки «Диссонанс»
    # (`explore` = связность), а она вырезана вместе с темой. 0.55 — середина
    # прежнего хода 0.3..0.8, то есть поведение при связности 0.5.
    div = 0.55

    # ОДИН ПУТЬ ВМЕСТО ТРЁХ (2026-08-29, снос по слову владельца: «тему стоит
    # вырезать как функцию», «генератор — вырезать»).
    #
    # ЗДЕСЬ СТОЯЛА РАЗВИЛКА ПО `nl_mix` (ручка «Источники»): только корпус ·
    # только генератор · смесь. Генератор грамматических строк вырезан целиком,
    # источник остался один — корпус, и развилке нечего разводить.
    #
    # И ЭТО ЗАОДНО ПОЧИНКА, А НЕ ТОЛЬКО УБОРКА. Прямая тяга требовала
    # `nl_mix >= 1.0`, а её короткое замыкание стояло в ветке СМЕСИ (0 < nl_mix
    # < 1) — то есть при обычных настройках владельца (только корпус, 95.3%
    # прогонов) `nlindex.select` собирал строфу прямой тягой, а потом сборщик
    # пересобирал её заново. Работа делалась дважды, и второй проход мог
    # выбросить строки первого.
    size = min(knobs["shortlist"], len(nl_survivors))
    if _прямая_тяга:
        # Строфа УЖЕ собрана колонками: слоги, ярусы рифмы, доля мата, запрет
        # близнецов — всё сделано в `nlindex.тянуть_строфы`. Искать нечего.
        shortlist = nl_survivors[:size]
    else:
        # Схемы рифмы нет (или нет слоговой вилки/индекса) — собирать пару
        # нечем и незачем: берём разнообразную выборку с той же долей мата.
        shortlist = _diversify_с_долей_мата(
            nl_survivors, size, div, knobs.get("mat_share", -1.0))

    # `forced_notice` остаётся ПУСТЫМ СЛОВАРЁМ, а не исчезает: форма ответа
    # /api/generate не меняется ради сноса — старый бандл в браузере владельца
    # читает это поле. НАДГРОБИЕ: здесь звался `_ensure_forced` — гарантия
    # показа обязательного слова «!слово» (снято 2026-08-29 вместе с темой).
    forced_notice = {}

    nl_in_shortlist = sum(1 for r in shortlist if r["template"] == "nakedlunch")
    # СКОЛЬКО КАНДИДАТОВ ВООБЩЕ МОГУТ ВСТАТЬ В ПАРУ (Раунд 62).
    #
    # На ПУЛЕ это число мёртвое — 95.5–99.6% при любой ручке, потому что на
    # полутора миллионах у каждой строки есть однокорзинник. Нехватка пар
    # возникает ПОСЛЕ жребия: замер 21.6 нашёл, что 300 кандидатов ложатся в
    # ~198 рифмо-корзин, из которых с двумя и более членами только 54, и в них
    # 154 кандидата из 300 — то есть половина буфера физически не может занять
    # рифмующую позицию, и воронка об этом молчала.
    #
    # Считаем по ТОМУ ЖЕ правилу пары, что и отбор (_rhymes/ярус_пары), иначе
    # число описывало бы не то, что происходит. Арифметика по маске: у строки
    # есть партнёр на «точной», если её ключ встречается дважды; на «близкой» —
    # если в её 3-значной корзине есть ДРУГОЙ ключ; на «созвучии» — в 2-значной
    # другой 3-префикс; на «ассонансе» — в 1-значной другой 2-префикс.
    if ступени and rhyme != "none":
        м = int(knobs["rhyme_tiers"])
        c0: dict = {}
        c3: dict = {}
        c2: dict = {}
        c1: dict = {}
        ключи_строк = [r.get("rhyme") for r in nl_survivors if r.get("rhyme")]
        for k in ключи_строк:
            c0[k] = c0.get(k, 0) + 1
            c3[k[:3]] = c3.get(k[:3], 0) + 1
            c2[k[:2]] = c2.get(k[:2], 0) + 1
            c1[k[:1]] = c1.get(k[:1], 0) + 1
        ступени["в_парах"] = sum(
            1 for k in ключи_строк
            if ((м & 1) and c0[k] >= 2)
            or ((м & 2) and c3[k[:3]] - c0[k] >= 1)
            or ((м & 4) and c2[k[:2]] - c3[k[:3]] >= 1)
            or ((м & 8) and c1[k[:1]] - c2[k[:2]] >= 1))
        плен = nlindex.корзина_яруса(м)
        ступени["корзин"] = len(c0 if плен is None else
                                (c3 if плен == 3 else (c2 if плен == 2 else c1)))
    for r in shortlist:
        r["lemmas"] = sorted(r.pop("_lem"))          # echoed back on accept — see corpus.accept
        # Раунд 50: сюда доходит только алгоритм — классика ушла развилкой в
        # начале run(). Поле остаётся в форме ответа (его пишет и _run_classic),
        # чтобы разбирающему не приходилось гадать, какой ярус перед ним.
        r.setdefault("classic", False)
        r.setdefault("anchor", False)                # always present — frontend badges the theme-anchor line
        r.pop("_pctl", None)                         # internal-only, see _select_with_rhyme's theme-anchor use

    return {
        "shortlist": shortlist,
        "funnel": {"generated": n0, "formal": n1, "redundancy": n2,
                   "banality": n3, "shortlist": len(shortlist),
                   "nl_fetched": n_nl, "nl_survived": n_nl_survived, "nl_used": nl_in_shortlist,
                   "nl_classic_survived": 0, "nl_classic_used": 0,
                   # ЧЕСТНЫЕ СТУПЕНИ (Раунд 62). Прежние счётчики остаются —
                   # их читают статистика и «почему пусто», и ломать их ради
                   # красоты нельзя. Но сами по себе они врали дважды:
                   #   · четыре из них (generated/formal/redundancy/banality)
                   #     описывают грамматическую ветку, которая при «Источники
                   #     = корпус» НЕ ЗАПУСКАЕТСЯ вовсе — нули читались как
                   #     «отфильтровано подчистую», хотя ступеней не было;
                   #   · между `nl_survived` и `shortlist` пропадала крупнейшая
                   #     ступень каскада — жребий из 1.5 млн в 300.
                   # `gen_ran` отвечает на первое, `ступени` — на второе.
                   "gen_ran": bool(n0),
                   "ступени": ступени},
        "forced_notice": forced_notice,
        "seed": _штамп_прогона(семя, пул=n_nl, скрыто=len(hidden or ())),
    }


def _j(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _last_word(text: str) -> str:
    tokens = text.strip().split()
    return tokens[-1].strip(".,!?:;\"'()»«—-").lower() if tokens else ""


# НАДГРОБИЕ: `_rhyme_prefix_len` (ползунок 0..1 → длина префикса) жил здесь
# с 2026-07-14 по 2026-08-28 и умер вместе с ползунком: ручка стала битовой
# маской ярусов, корзину считает nlindex.корзина_яруса, годность пары —
# nlindex.ярус_пары. Старое имя rhyme_precision переводится в clean.knobs.


def _rhymes(r1: dict, r2: dict, ярусы: int = 3) -> bool:
    """Рифмуются ли две строки при данной МАСКЕ ярусов (2026-08-28, владелец:
    «хочу только ассонанс и точные»). Ярус пары — теснейшее совпадение её
    ключей (nlindex.ярус_пары — канон один на движок): тождественные ключи —
    «точная», три общих знака — «близкая», два — «созвучие», ударная гласная —
    «ассонанс». Ярусы исключающие; пара годится, если её ярус горит в маске.
    Один и тот же последний ВОРД («пепел»/«пепел») — не рифма, а повтор,
    отсекается всегда."""
    k1, k2 = r1.get("rhyme"), r2.get("rhyme")
    if not k1 or not k2:
        return False
    if _last_word(r1.get("text", "")) == _last_word(r2.get("text", "")):
        return False
    return bool(nlindex.ярус_пары(k1, k2) & int(ярусы))


def _rhyme_scheme_groups(scheme: str) -> list[list[int]]:
    """Parse rhyme scheme (абаб, абав, абба, etc.) into groups of positions that
    must rhyme together. Returns list of lists, e.g. абаб → [[0,2], [1,3]]."""
    if scheme == "none":
        return []

    groups_dict = {}
    for i, letter in enumerate(scheme):
        if letter not in groups_dict:
            groups_dict[letter] = []
        groups_dict[letter].append(i)

    return list(groups_dict.values())


def _nl_slot_plan(size: int, nl_quota: int) -> set:
    """Evenly-spread position indices reserved for a nakedlunch pick — same
    stride idea as the non-rhyme path's post-hoc splice, but computed as
    POSITIONS up front so rhyme-aware selection can target them directly.
    Splicing nl picks in AFTER stanza selection (the pre-2026-07-14 approach)
    shifts every later position and silently breaks the visible rhyme
    pattern — found via the user's own screenshots, not self-testing."""
    if nl_quota <= 0 or size <= 0:
        return set()
    nl_quota = min(nl_quota, size)
    stride = max(1, size // nl_quota)
    positions = list(range(stride - 1, size, stride))[:nl_quota]
    i = size - 1
    while len(positions) < nl_quota and i >= 0:
        if i not in positions:
            positions.append(i)
        i -= 1
    return set(positions)


def _diversify_с_долей_мата(pool: list, k: int, div: float,
                            mat_share: float) -> list:
    """MMR-отбор с квотой мата — для путей БЕЗ схемы рифмы.

    НАЙДЕНО УЛЬТРАРЕВЬЮ (bug_002, 2026-08-27). Все три ветки rhyme=="none" в
    `_run` звали `_diversify` напрямую, а он про мат не знает: середина ручки
    «Мат» (0<доля<1) на этом пути молча игнорировалась — подпись «50%»
    обновлялась, выдача не менялась. Контрол-обманка, худший класс бага.
    Крайности не страдали: 0 и 1 становятся no_mat/only_mat ещё в clean.knobs
    и режут пул воротами до этого места.

    ПОЧЕМУ НЕ ПРОСТО `_select_with_rhyme(scheme="none")`, как предлагало
    ревью: та ветка держит долю, но НЕ делает MMR-прохода, а он здесь стоит
    нарочно — перекрывающиеся окна одного предложения слипаются в выдаче без
    него (см. докстринг `_diversify`). Правильный размен — квота ПОВЕРХ
    разнообразия: каждая корзина набирается своим MMR-проходом.

    Раскладка по позициям — тем же `_mat_slot_plan`, что у пути со схемой и у
    классики: один источник правды о том, «какая доля на каких местах».
    Пустой план (доля «как есть», −1) — прежний путь без квоты."""
    план = _mat_slot_plan(mat_share, k)
    if not план:
        return _diversify(pool, k, div)
    нужно = sum(1 for v in план.values() if v)
    с_матом = _diversify([r for r in pool if r.get("mat")], нужно, div)
    без_мата = _diversify([r for r in pool if not r.get("mat")], k - нужно, div)
    м, ч = iter(с_матом), iter(без_мата)
    взято = []
    for i in range(k):
        r = next(м if план.get(i) else ч, None)
        if r is not None:
            взято.append(r)
    # корзина не добрала — строка важнее доли (тот же размен, что в ветке
    # scheme=="none" у _select_with_rhyme)
    if len(взято) < k:
        есть = {id(r) for r in взято}
        взято += [r for r in pool if id(r) not in есть][:k - len(взято)]
    return взято[:k]


def _mat_slot_plan(share: float, L: int, groups=None) -> dict:
    """Какие позиции строфы обязаны быть с матом, какие — без.

    Требование (2026-08-03): крайнее положение работает антифильтром, середина даёт половину
    на половину, ноль — полная цензура..

    ПОЧЕМУ ПО РИФМО-ГРУППАМ (правка Раунда 40). Первая версия раскладывала мат
    по отдельным позициям — и на максимуме давала одну матерную строку из
    четырёх. Причина: позиции связаны рифмой. Матерная строка на позиции 0
    требует матерного же РИФМУЮЩЕГОСЯ партнёра на позиции 1, а его каскад
    искал уже без учёта мата (мат сдаётся раньше рифмы — и правильно). Значит
    единица раскладки — не строка, а рифмо-группа целиком: обе строки пары
    либо матерные, либо нет, и тогда партнёр ищется в том же матерном пуле.

    `groups` — список групп позиций (_rhyme_scheme_groups). Без него (схемы
    нет) каждая позиция сама себе группа."""
    if L <= 0 or share <= 0.0005:
        return {}
    if share >= 0.9995:
        return {i: True for i in range(L)}
    гр = [sorted(g) for g in (groups or [])] or [[i] for i in range(L)]
    гр.sort(key=lambda g: g[0])
    # Сколько ГРУПП сделать матерными, чтобы доля строк была ближе всего к
    # запрошенной: группы бывают разной длины, поэтому считаем по строкам.
    лучшее, best_k = None, 0
    for k in range(len(гр) + 1):
        строк = sum(len(g) for g in гр[:k])
        d = abs(строк / L - share)
        if лучшее is None or d < лучшее:
            лучшее, best_k = d, k
    # Раскладываем матерные группы РОВНО по строфе, а не подряд.
    матерные = set()
    if best_k:
        for i in range(best_k):
            матерные.add(int(round(i * len(гр) / best_k)) % len(гр))
        i = 0
        while len(матерные) < best_k and i < len(гр):
            матерные.add(i)
            i += 1
    план = {}
    for gi, g in enumerate(гр):
        for pos in g:
            план[pos] = gi in матерные
    return план


# НАДГРОБИЕ 2026-08-18: снят провод остановки набора — параметр `стоп` у `run` и `_select_with_rhyme`, класс `_Остановлено` и проверка в цикле отбора; передавала и ловила его только цепь (`core/pipeline.py`), вырезанная в тот же день, так что `стоп` был всегда None, а `raise` — недостижим.


# Ширина полосы разброса при раннем выходе: из скольких лучших кандидатов
# выбираем случайного. Двенадцать — компромисс: достаточно, чтобы одна книга не
# могла занять первый слот четыре строфы подряд, и мало, чтобы качество отбора
# осталось тем же (все члены полосы прошли ОДИН И ТОТ ЖЕ каскад проверок и
# стоят рядом по рангу).
ПОЛОСА = 12

# БАРЬЕР ПОВТОРА ЛЕММ: СТОП-СПИСОК ПРОВЕРЕН И ОТКЛОНЁН (волна B4, 2026-08-14).
#
# План требовал не считать восемнадцать служебных лемм («весь этот тот который
# быть мочь…») — они и правда составляют 10.1% всех вхождений в колонке лемм
# (934 779 из 9.26 млн), то есть десятую часть запретительной силы барьера.
# Основанием было «плоский стоп-список даёт ~6% слышимых повторов».
#
# ЗАМЕР ЭТОГО НЕ ПОДТВЕРДИЛ, и цифра 6% оказалась артефактом метрики. На 30
# прогонах по 40 строк (1 170 соседних пар), считая ТОЛЬКО знаменательные
# слова, слышимых повторов **4 штуки = 0.3%**. Считая все слова подряд —
# 8.5%, но их дают «и», «в», «с», которых барьер не видит и видеть не должен:
# в `_lem` попадают только знаменательные.
#
# Правка со стоп-списком и оговоркой «кроме соседних строк с той же
# словоформой» была написана и замерена А/Б на одних семенах:
#   • 25 прогонов из 30 совпали побитово;
#   • слышимых повторов 4 → 3 (убрался один: «не успел ЕГО выхватить» /
#     «Я ЕГО угостил стаканчиком»);
#   • разных строк 1 020 → **1 011**, то есть разнообразие УПАЛО.
# Один повтор ценой девяти строк — по правилу 10 («функция принимается, только
# если замер показывает, что она лучше») не проходит. Откачено.
#
# И второе, ради чего пункт затевался: квота мата ломалась НЕ здесь. См.
# `_mat_slot_plan` — там раскладка идёт рифмо-группами, и на схеме «абба»
# достижимы ровно три доли: 0.00, 0.50, 1.00.


_РАЗБРОС_СЕМЯ: int | None = None
# ОБЪЯВЛЕНИЕ ЗДЕСЬ ОБЯЗАТЕЛЬНО, И ВОТ ПОЧЕМУ (2026-08-18).
#
# Откат правки B4 снёс эту строку вместе с двумя функциями ниже. Функции я
# вернула, строку — нет. Весь набор тестов остался ЗЕЛЁНЫМ, а живое приложение
# отдавало 500 на каждую генерацию: `NameError: name '_РАЗБРОС_СЕМЯ' is not
# defined`.
#
# Тесты этого увидеть не могли по построению: `conftest.py` автоматическим
# приспособлением зовёт `закрепить_разброс(...)` перед КАЖДЫМ тестом, а та
# делает `global _РАЗБРОС_СЕМЯ` и тем самым СОЗДАЁТ имя. В прогоне тестов оно
# существует всегда; в приложении его не создаёт никто.
#
# Ровно тот случай, про который правило 12: зелёные тесты не проверка, потому
# что замер держит мир неподвижным, а приложение — нет. Сторож на это —
# `tests/test_семя.py::test_modul_gruzitsya_bez_pomoshchi_testov`, он импортирует
# модуль отдельным процессом, без приспособлений.


def _разброс_семя():
    """Семя для разведения равных кандидатов. None — новое на каждый вызов;
    тесты (и эталонная сверка) закрепляют его, чтобы выдача была повторимой."""
    return _РАЗБРОС_СЕМЯ if _РАЗБРОС_СЕМЯ is not None else random.randrange(1 << 30)


def закрепить_разброс(семя: int | None) -> None:
    """Закрепить или отпустить семя разведения (для тестов и эталона)."""
    global _РАЗБРОС_СЕМЯ
    _РАЗБРОС_СЕМЯ = семя


# НАДГРОБИЕ: `_select_with_rhyme` — СБОРЩИК СТРОФЫ, 884 строки (2026-08-29).
#
# Он собирал строфу из ПАЧКИ кандидатов: строил корзины по рифмо-ключу, шёл по
# рангу, держал схему, слоги, долю мата, запрет повтора лемм, тематический
# якорь и обязательное слово. Всё это теперь делает прямая тяга по колонкам
# (`nlindex.тянуть_строфы`) — без пачки, по всему корпусу.
#
# ПОЧЕМУ УМЕР. Сборщик существовал ради того, чего больше нет: смешивания строк
# генератора с корпусными, тематического якоря и `!слова`. Владелец вырезал все
# три (2026-08-29). А ПАЧКА была его ценой: 320 кандидатов из 2 307 826 строк —
# та самая стена, из-за которой на теме беднели рифмы, редкость и книги.
#
# И ОН ЖЕ БЫЛ ЛИШНЕЙ РАБОТОЙ. Прямая тяга требовала «только корпус», а её
# короткое замыкание стояло в ветке СМЕСИ: при обычных настройках владельца
# строфа собиралась колонками, а потом сборщик пересобирал её заново.
#
# Вместе с ним ушли: `_rhymes` (правило пары — переехало в `nlindex.ярус_пары`),
# `_rhyme_scheme_groups`, `_nl_slot_plan`, `has_distinct_bucket_partner`,
# `bucket`, `_разброс_семя`/`закрепить_разброс`, `ПОЛОСА`.
