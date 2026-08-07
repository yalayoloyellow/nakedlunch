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
from pathlib import Path

from wordfreq import zipf_frequency

import numpy as np

import embeddings
import nlbridge
import nlindex          # колоночный индекс корпуса (Раунд 31); None-безопасен
import scan as scan_mod
from corpus import lemmatize

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

_NL_RHYME_PATH = Path(__file__).resolve().parent / "data" / "nl_rhyme.json"
_NL_RHYME: dict = {}


def warm_caches() -> None:
    """wordfreq lazily unpacks its Russian frequency data (~100ms) on first use
    and caches it for the process lifetime. Force that here at server startup so
    the first /api/generate doesn't pay it.

    2026-08-01: nl_rhyme.json вырос до 946MB / 2 868 100 записей (пользователь
    залил ~40 книг в июне-июле; кэш строится по ВСЕМ корпусам стора, включая
    выключенные — см. tools/build_nl_rhyme.py). Эта загрузка теперь ~9-11s
    и ~5.5GB RSS на весь срок жизни процесса — главный вклад в память
    сервера на 16GB-машине."""
    zipf_frequency("слово", "ru")
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
    if _NL_RHYME_PATH.exists():
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
        import кэш
        _NL_RHYME = кэш.читать_всё()


# ИМЕНА СОБСТВЕННЫЕ НЕ СЧИТАЮТСЯ РЕДКИМИ (Раунд 57).
#
# Банальность — частота САМОГО РЕДКОГО слова строки: чем реже, тем выше балл.
# Имя собственное в языке почти не встречается, поэтому любая строка с ним
# получала лучший балл по редкости и лезла в первый слот строфы. Пользователь
# прислал четыре строфы подряд, начинающиеся репликой одного персонажа: «у меня
# везде почему-то Г-ЖА ДЕ СЕНТ-АНЖ, хотя у меня два миллиона фрагментов; причём
# это пустая строка, это имя персонажа, это бред».
#
# Редкость имени — свойство ИМЕНИ, а не находка автора. Считаем без них.
# Если в строке не осталось ничего, кроме имён, — метрика по ним же, но это
# честный крайний случай, а не награда: строка из одних имён не должна ни
# выигрывать, ни падать в ноль.
def _без_имён(слова: list[str]) -> list[str]:
    """Слова без имён собственных. Пусто — отдаём исходный список: мерить по
    чему-то надо.

    Раунд 57: опознаём МОРФОЛОГИЕЙ, а не заглавной буквой. Регистр врал в обе
    стороны — строка целиком капсом становилась «сплошь именами», а имя со
    строчной проскакивало как обычное слово."""
    from corpus import имя_ли
    обычные = [w for w in слова if not имя_ли(w)]
    return обычные or слова


def _banality(line) -> float:
    """A line's banality = the zipf frequency of its LEAST-common content word.
    High = even the rarest word is ordinary, so the whole line reads generic; a
    single fresh word (low zipf) rescues it. wordfreq is offline, counts-only.

    Раунд 57: имена собственные из подсчёта исключены — см. `_без_имён`."""
    пары = [(w.surface, w.lemma) for w in _content(line)]
    годные = set(_без_имён([s for s, _ in пары]))
    zs = [zipf_frequency(l, "ru") for s, l in пары if s in годные]
    return min(zs) if zs else 0.0


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

# Потолок шкалы «связность соседних строк» (Раунд 44). Замер трёх референсных
# текстов пользователя: 0.35 / 0.18 / 0.17 по косинусу центроидов лемм соседних
# строк. То есть даже у самого связного его текста соседство держится втрое
# слабее единицы — линейная шкала 0..1 означала бы, что верхняя половина
# ползунка недостижима в принципе. Поэтому ползунок 0..1 переводится в цель
# 0..0.6: 0.35 приходится примерно на 0.6 шкалы, есть куда крутить в обе
# стороны.
_FLOW_MAX = 0.6

# Насколько связность двигает выбор против прочих соображений. Прибавка к
# рангу кандидата, а не жёсткое условие: связность — свойство постепенное, в
# отличие от мата и клаузулы, и ломать ради неё рифму нельзя. Число
# предварительное: его калибруем ЗАМЕРОМ выдачи против профиля референса —
# ровно для этого мерилка и написана.
_FLOW_W = 0.9

# Через границу части связь заметно слабее, чем внутри неё — это не догадка, а
# три замера подряд: 0.42/0.23, 0.19/0.16, 0.18/0.15 (отношение 0.55, 0.84,
# 0.83). Значит на стыке целимся ниже той же доли.
_FLOW_EDGE = 0.75


def _cos(a, b) -> float | None:
    """Косинус двух центроидов; None, если любой из них пуст."""
    if a is None or b is None:
        return None
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if not na or not nb:
        return None
    return float(a @ b / (na * nb))


def _nl_scored(fragments, corpus, hidden, ворота, tags=None, light=False,
               theme_sims=None, literal_cap=None, forced=None, cohesion=0.5,
               no_mat=False, only_mat=False, clausula=0):
    """Score raw nakedlunch fragments (real cut-up text, no Word/stress
    structure) for the SAME shortlist grammar-candidates land in: banality,
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
    OWNER'S WHOLE active pool every time (2026-07-14: "пусть обрабатывается и
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
            if clausula and scan_mod.clausula(key) != clausula:
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
        table = _score_strict_table(tags, theme_sims, forced, ворота, no_mat, only_mat, clausula)
        for text in fragments:
            if text in hidden:
                continue
            cached_row = table.get(text)
            if cached_row is None:
                continue   # unknown banal/taut, or failed cliché/banal/taut gate — skip honestly
            row = dict(cached_row)   # copy — run() mutates rows (pops "_lem", etc); never touch the cache's own dict
            bias = _PCTL_SCALE * (0.5 - abs(row["_pctl"] - cohesion))
            row["score"] = round(0.6 + bias, 4)
            out.append(row)
            for w in row["_forced_hits"]:
                forced_candidates[w].append(row)
    if literal_cap is not None and tags:
        # Форсед-фрагменты ИСКЛЮЧЕНЫ из шапки — у них отдельная, жёсткая
        # гарантия ниже (run()), обычный cap про них не должен решать.
        literal_items = [r for r in out if r["_literal"] and not r["_forced"]]
        if len(literal_items) > literal_cap:
            # Литеральный bias теперь ФИКСИРОВАН (см. выше) — почти все
            # literal_items имеют одинаковый score, так что сортировка по
            # score без перемешивания детерминированно оставляла бы одни и
            # те же фрагменты (порядок из пула), а не случайную выборку.
            random.shuffle(literal_items)
            literal_items.sort(key=lambda r: r["score"], reverse=True)
            drop = set(map(id, literal_items[literal_cap:]))
            out = [r for r in out if id(r) not in drop]
    for r in out:
        del r["_literal"]
        del r["_forced"]
        r.pop("_forced_hits", None)   # strict-tier rows only; a SET — must not reach json.dumps in the API response
    return out, forced_candidates


# Cache for _score_strict_table — see that function and _nl_scored's own
# docstring for why (user: 5-10s per stanza; repeated calls within one
# theme/knob session, which is the overwhelmingly common case — a buffer
# refill or freestyle's own prefetch queue — otherwise redo the SAME
# full-pool scoring pass from scratch every time). Bounded to a handful of
# entries: each holds a row per surviving _NL_RHYME entry (2026-08-01: пул
# 2.87M, выживает ~2.6M — таблица ≈ +0.4GB RSS каждая, при том что сам
# _NL_RHYME уже держит ~5.5GB на 16GB-машине со своп-давлением), so an
# unbounded — or even merely LARGER — cache would trade cache misses for
# swap, which is what actually made the measured miss cost float 24→43s.
# 2 covers the realistic pattern (current theme, plus whatever was active
# a moment ago) without keeping a whole history warm.
_STRICT_SCORE_CACHE_MAX = 2
_strict_score_cache: dict = {}
_strict_score_cache_order: list = []

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
    тестах и в старом режиме без индекса."""
    global _index_verdict
    ключ = (id(_NL_RHYME), len(_NL_RHYME))
    if _index_verdict is not None and _index_verdict[0] == ключ:
        return _index_verdict[1]
    idx = nlindex.load()
    if idx is not None and _NL_RHYME:
        try:
            if len(_NL_RHYME) != idx.n or idx.text(0) not in _NL_RHYME:
                idx = None
        except Exception:
            idx = None
    _index_verdict = (ключ, idx)
    return idx


def _score_strict_table(tags: set, theme_sims, forced: set, ворота,
                        no_mat: bool = False, only_mat: bool = False,
                        clausula: int = 0) -> dict:
    """{text: row} for every `_NL_RHYME` entry that survives the STRICT
    tier's cliché/banality/tautology gates for this (tags, banal_ceiling,
    forced, no_mat) — i.e. everything `_nl_scored`'s per-fragment loop used to
    compute fresh on every call. Deliberately keyed WITHOUT the caller's
    `fragments`/pool or `hidden`/blacklist state: a fragment's relevance
    depends only on its own precomputed properties and the theme — not on
    which OTHER fragments happen to be in the currently active pool, or
    which lines the user has since seen — so the exact same table is valid
    for every call in a theme/knob session even as the active pool and
    hidden set keep changing underneath it. `_nl_scored` applies
    `hidden`/blacklist filtering itself, fresh, on every call — those
    genuinely can't be cached (blacklist can change mid-session; hidden
    changes on nearly every request).

    `cohesion` is NOT in this table or its cache key (2026-07-18, see
    _nl_scored's own docstring for the full percentile-target story) — a
    row's `_pctl` (percentile rank of its `sem` within THIS pool) is a
    property of the theme alone, not of where the user's cohesion slider
    happens to sit; `_nl_scored` turns `_pctl` into a `score` per-call using
    whatever `cohesion` it was actually called with. This is why dragging
    the slider no longer busts this cache at all.

    Цена промаха (2026-08-01, пул 2 868 100 — Раунд 28 в DECISIONS.md):
    без темы ~20-24s до оптимизации цикла ниже → ~16s после; no_mat ~33s →
    ~24s; с темой ~28-33s (правка почти не помогает — доминируют
    relevance() по 2.6M строк и постройка 2.6M row-dict'ов, это уже не
    точечная территория). Всё плавает до ~2× под своп-давлением: один
    _NL_RHYME держит ~5.5GB RSS — 43s из замера пользователя это ~24s счёта +
    своп. Промах платится на каждую НОВУЮ комбинацию (тема, банальность,
    no_mat, forced) за пределами 2 кэш-слотов — осознанная цена решения
    Раунда 20 («всегда полная база»); отвергнутые альтернативы (урезание
    таблицы до активного пула, больше кэш-слотов) — в Раунде 28."""
    # id(_NL_RHYME) in the key (2026-07-18, caught live): _NL_RHYME is
    # effectively immutable for a running server's lifetime (see this
    # function's own docstring), but the test suite monkeypatches it
    # between tests — without this, a cache entry built from an EARLIER
    # _NL_RHYME survives the swap and silently serves stale rows for any
    # later call sharing the same (tags, banal_ceiling, forced).
    # Reassignment (`_NL_RHYME = {...}`), not in-place mutation, is the only
    # way _NL_RHYME ever changes (build_nl_rhyme.py's rebuild writes to disk
    # and only takes effect on server restart — see filters.warm_caches) —
    # so id() is a correct, cheap "has the underlying data changed" proxy.
    # no_mat в ключе (2026-07-31): фильтр мата стоит внутри построения таблицы
    # (рядом с клише — то же место отсева по содержимому, и по той же причине
    # кэшируемо: мат — свойство самого фрагмента, не запроса), так что таблицы
    # «с матом» и «без» — разные записи, а не молчаливо переиспользованная одна.
    key = (id(_NL_RHYME), frozenset(tags), tuple(ворота), frozenset(forced), no_mat, only_mat, clausula)
    cached = _strict_score_cache.get(key)
    if cached is not None:
        return cached

    # Тело этого цикла — самое горячее место файла (2026-08-01: пул 2 868 100
    # записей — докстринги вокруг писались при ~274k; промах кэша стоил
    # 24-43s, разброс — от memory pressure: один распарсенный _NL_RHYME
    # держит ~5.5GB RSS на 16GB-машине). cProfile показал: большая часть
    # уходила не в сами гейты, а в питон-оверхед НА ЗАПИСЬ — genexpr-фреймы
    # any()/sum() и лишние set(). Отсюда: (1) дешёвые dict-гейты (banal/taut)
    # раньше строковых; (2) _CLICHE_RE — один C-поиск вместо genexpr по
    # сидам; (3) слоги через str.count (C-сканы) вместо посимвольного
    # genexpr; (4) токены без темы/forced не трогаются вовсе, а с темой —
    # isdisjoint/intersection прямо по списку, без постройки set на запись.
    # Построчная эквивалентность старому циклу проверена на полном пуле
    # перед заменой; замер — в докстринге выше.
    table: dict = {}
    themed = bool(tags) or bool(forced)
    # СЦЕПКИ ЗДЕСЬ НЕТ, И ЭТО ЧЕСТНО (Раунд 58). Вторая ось ручки
    # «Банальность» живёт КОЛОНКОЙ ИНДЕКСА: она считается по статистике всего
    # корпуса, а у отдельной записи кэша такого поля нет и быть не может.
    # Этот путь — запасной (индекса нет или он испечён по другим правилам), и
    # на нём ручка работает одной осью — словами. Ступень «клише» убрана и
    # здесь: три зашитых выражения ушли вместе с колонкой.
    for text, entry in _NL_RHYME.items():
        b = entry.get("banal", 9.0)
        if b > ворота.слова_верх or b < ворота.слова_низ:
            continue
        if entry.get("taut", False):
            continue
        low = text.lower()
        # Мат — ПОСЛЕ дешёвых banal/taut-гейтов (dict-lookups против
        # regex-прохода has_mat по строке): при пуле 2.87M замерено 2026-07-31
        # ~+20s к промаху кэша, только по выжившим — на ~2s меньше. Промах
        # платится один раз на (тема, банальность, no_mat), дальше кэш.
        if no_mat and has_mat(low):
            continue
        if only_mat and not has_mat(low):
            continue
        if clausula and scan_mod.clausula(entry.get("key", "")) != clausula:
            continue
        cl = set(entry.get("lemmas", []))
        syllables = sum(map(low.count, VOWELS))
        if themed:
            tokens = entry.get("tokens", [])
            literal = bool(tags) and not tags.isdisjoint(tokens)
            forced_hits = forced.intersection(tokens) if forced else set()
        else:
            literal = False
            forced_hits = set()
        sem = embeddings.relevance(theme_sims, cl) if tags else 0.0
        table[text] = {"text": text, "template": "nakedlunch", "meter": None,
                       "rhyme": entry.get("key", ""), "rhyme_span": entry.get("span"),
                       "syllables": syllables, "_sem": sem, "_lem": cl,
                       # Раунд 39: мат — доля, а не запрет, поэтому признак
                       # нужен каждой строке (см. _select_with_rhyme). Здесь
                       # low уже посчитан выше для гейта — второй раз не гоним.
                       "mat": has_mat(low), "clausula": scan_mod.clausula(entry.get("key", "")),
                       "classic": False, "_literal": literal, "_forced": bool(forced_hits),
                       "_forced_hits": forced_hits}

    # Percentile rank of each row's `_sem` WITHIN this table (0=least
    # relevant fragment this theme's pool has, 1=most) — see _nl_scored's
    # docstring for why this replaced a scalar multiplier. Ties (the common
    # `sem=0.0` case for an untagged run, or genuinely identical cosines)
    # land at whatever index sort() gives them — fine, since ties by
    # definition don't care which side of the target they land on.
    # Без темы sem у ВСЕХ строк 0.0 — stable sort вернул бы ровно insertion
    # order, поэтому сортировка честно пропускается (идентичный результат,
    # минус ~2s на 2.6M вызовов ключа при промахе без темы).
    if tags:
        ranked = sorted(table.values(), key=itemgetter("_sem"))
    else:
        ranked = list(table.values())
    n = len(ranked)
    for idx, row in enumerate(ranked):
        row["_pctl"] = idx / (n - 1) if n > 1 else 0.5
        del row["_sem"]

    _strict_score_cache[key] = table
    _strict_score_cache_order.append(key)
    if len(_strict_score_cache_order) > _STRICT_SCORE_CACHE_MAX:
        oldest = _strict_score_cache_order.pop(0)
        _strict_score_cache.pop(oldest, None)
    return table


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


def _ensure_forced(shortlist, forced, forced_candidates, rhyme, precision, hidden=None):
    """`!слово` hard guarantee (2026-07-17, PLAN.md 0.2b) — runs AFTER the
    shortlist is fully assembled, on the assembled list directly (mutates
    `shortlist` in place). Unlike ordinary theme words (`literal_cap`: a
    soft, probabilistic ≈1-per-stanza bias applied DURING scoring), a forced
    word needs a certain answer: is it in this response or not, and if not,
    why. That can't be decided during scoring — only after selection is
    final does "is it actually there" have an answer — hence a separate
    corrective pass rather than folding into the ranking machinery.

    Returns {word: "ok"|"missing"|"unrhymed"} for `run()` to turn into an
    honest notice:
      "shown"    — кандидаты есть, но ВСЕ уже в истории. Железное правило
                   пользователя: показанное не возвращается ни при каких
                   обстоятельствах, значит честный отказ — единственный ответ.
      "missing"  — no STRICT-tier-quality fragment anywhere in the active
                   pool contains the word literally (пользователь: "если в базе
                   есть это слово" — не в базе, или только в строках, не
                   прошедших банальность/клише/тавтологию; один честный ответ
                   для обоих случаев, а не два разных сообщения ради
                   формальной точности).
      "unrhymed" — candidates exist, but NONE rhymes with any existing
                   scheme-group slot (only when `rhyme != "none"`) — the
                   scheme wins; a forced word never gets inserted at the cost
                   of breaking rhyme, it's reported unmet instead.
      "ok"       — already present, or successfully placed.

    Insertion for `rhyme == "none"` takes slots from the END of the
    shortlist (one per forced word, first-come-first-served — simple and
    safe, no clustering risk since each word only ever inserts ONE line).
    With a scheme active, a candidate only takes a slot whose existing
    letter-group PARTNER it actually rhymes with (checked against one
    partner — trusted transitively, since `_select_with_rhyme` already
    guarantees every member of a group rhymes with every other member)."""
    result = {}
    if not forced:
        return result
    if not shortlist:
        return {w: "missing" for w in forced}
    used_texts = {r["text"] for r in shortlist}
    free_slot = len(shortlist) - 1
    for word in sorted(forced):   # deterministic order, not set-iteration-order-dependent
        if any(word in nlbridge._tokens(r["text"]) for r in shortlist):
            result[word] = "ok"
            continue
        candidates = [c for c in forced_candidates.get(word, []) if c["text"] not in used_texts]
        # ИСТОРИЮ УЧИТЫВАЕМ И ЗДЕСЬ (Раунд 57). `forced_candidates` собирается
        # в КЭШИРУЕМОЙ строгой таблице, ключ которой — (теги, потолок
        # банальности, forced). История в ключ не входит и входить не может:
        # она меняется после каждого показа, кэш бы не жил ни одного вызова.
        # Из-за этого гарантия `!слово` подставляла ОДНУ И ТУ ЖЕ строку в
        # каждую строфу подряд — пользователь: «буквально идентичная строка
        # достаётся; а если она есть в истории уже, как она в генерацию
        # попадает?».
        #
        # ЖЕЛЕЗНОЕ ПРАВИЛО (Раунд 57, пользователь дословно): «что в истории — оно не
        # повторяется вообще и не генерится, пока я историю не почищу. Это важно.
        # В любых обстоятельствах так. Если материала для генерации на тему не
        # будет — честно отказывай: значит надо залить новые источники или
        # историю очистить».
        #
        # Поэтому здесь НЕТ запасного варианта. Показанное вычитается наглухо, и
        # если у обязательного слова не осталось непоказанных кандидатов — это
        # честный «missing», а не тихий повтор. Первая версия этой правки
        # оставляла показанных «на крайний случай», рассуждая, что обещание
        # `!слово` сильнее свежести. Пользователь решил иначе, и он прав: повтор,
        # который он не заказывал, хуже честного отказа.
        было_до_истории = bool(candidates)
        if hidden:
            candidates = [c for c in candidates if c["text"] not in hidden]
        if not candidates:
            # ДВА РАЗНЫХ ОТКАЗА (Раунд 57). Для пользователя это разные ситуации:
            # «нет в базе» — заливать источники, «всё показано» — чистить
            # историю. Раньше оба назывались «missing», и подсказка врала в
            # половине случаев.
            result[word] = "shown" if было_до_истории else "missing"
            continue
        if rhyme == "none":
            if free_slot < 0:
                result[word] = "missing"   # more forced words than slots — honest, not silently dropped
                continue
            shortlist[free_slot] = candidates[0]
            used_texts.add(candidates[0]["text"])
            free_slot -= 1
            result[word] = "ok"
            continue
        letters = [rhyme[i % len(rhyme)] for i in range(len(shortlist))]
        placed = False
        for i, letter in enumerate(letters):
            partner = next((j for j, l in enumerate(letters) if l == letter and j != i), None)
            if partner is None:
                continue
            for cand in candidates:
                if _rhymes(cand, shortlist[partner], precision):
                    shortlist[i] = cand
                    used_texts.add(cand["text"])
                    placed = True
                    break
            if placed:
                break
        result[word] = "ok" if placed else "unrhymed"
    return result


def _syllable_reserve(pool: list, syllable_spec: list | None, per_bucket: int = 1) -> list:
    """Extra rows to keep alongside the score-based cap so a position's
    syllable_spec range isn't invisible to _select_with_rhyme just because
    its natural score rank falls outside the cap slice (2026-07-19 — same
    starvation shape as the theme-anchor `_pctl` reserve below, this time
    for length: found live, a corpus with 859 correctly-rhyming AND
    correctly-length "ом" survivors still produced an 11-syllable line,
    because none of those 859 were ranked highly enough by cohesion score to
    survive NL_SELECT_CAP before syllable_spec ever got a look).

    A flat top-N-by-score reserve (the first version of this function) isn't
    enough: which RHYME ENDING a position actually needs only gets decided
    live, as _select_with_rhyme picks each group's first (anchor) member —
    a reserve that isn't spread across endings mostly just reserves whatever
    scores highest overall, which is no more likely to share a SPECIFIC
    ending than the plain score cap was (measured live: Онегинская строфа's
    7 distinct endings, 0 splices fired with a flat 20-item reserve — it
    never had the right ending on hand). Fix: group in-range survivors by
    their exact rhyme key first, then take the top `per_bucket` FROM EACH —
    whichever ending later gets established as a group's anchor, its own
    length-conforming members (if any exist at all) are then guaranteed
    present, not just possible. Grouping by the exact key (not the
    precision-adjusted bucket _select_with_rhyme itself uses) is a safe,
    strictly finer split — every precision-bucket is a union of one or more
    exact keys, so per-exact-key coverage implies per-bucket coverage too.

    One reserve pass per DISTINCT (min_syl, max_syl) pair actually used in
    the active stanza, not per line — a scheme rarely uses more than a
    handful of distinct ranges even at 14+ lines (Онегинская строфа: 14
    lines, exactly 1 range). `None`/empty spec (every pre-constructor
    caller) returns [] unconditionally — zero cost, zero behavior change
    for existing schemes."""
    if not syllable_spec:
        return []
    out: list = []
    for lo, hi in {tuple(r) for r in syllable_spec}:
        by_key: dict = {}
        for r in pool:
            syl = r.get("syllables")
            key = r.get("rhyme")
            if syl is not None and key and lo <= syl <= hi:
                by_key.setdefault(key, []).append(r)
        for members in by_key.values():
            members.sort(key=lambda r: r["score"], reverse=True)
            out.extend(members[:per_bucket])
    return out


def _classic_pool(knobs, corpus, nl_fragments, *, hidden, no_mat, only_mat, clausula, cap):
    """Пул «классики»: активный пул минус история, с воротами мата и клаузулы.
    Колоночный путь и старый обязаны давать ОДНО И ТО ЖЕ — иначе режим зависел
    бы от того, испечён индекс или нет."""
    _idx = _index_for_current_cache() if nl_fragments else None
    if _idx is not None:
        pool, survived = nlindex.select_light(
            _idx, pool_mask=nlindex.pool_mask(_idx, nl_fragments),
            hidden_mask=nlindex.mask_of(_idx, hidden),
            no_mat=no_mat, only_mat=only_mat, clausula=clausula, cap=cap)
        return pool, survived
    pool, _ = _nl_scored(nl_fragments or [], corpus, hidden, 9.0, light=True,
                         no_mat=no_mat, only_mat=only_mat, clausula=clausula)
    survived = len(pool)
    random.shuffle(pool)                # оценка у всех одна — верхушки не существует
    return pool[:cap], survived


def _run_classic(knobs, corpus, nl_fragments, *, hidden, no_mat, only_mat, clausula,
                 mat_share, forced, cap) -> dict:
    """«Классика» — ОТДЕЛЬНЫЙ путь, а не квота внутри общего (Раунд 50).

    Пользователь 2026-08-03: «я бы сделал переключатель, бинарный: алгоритм —
    классика. Если выбрана классика, то всех вот этих алгоритмических оценок
    их не существует, классический нейкедланч, классический метод нарезок
    просто вообще без ничего».

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
    pool, survived = _classic_pool(knobs, corpus, nl_fragments, hidden=hidden,
                                   no_mat=no_mat, only_mat=only_mat,
                                   clausula=clausula, cap=cap)

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
        random.shuffle(shortlist)
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
                   "nl_classic_survived": survived, "nl_classic_used": len(shortlist)},
        "forced_notice": forced_notice,
    }


def run(lines, knobs: dict, corpus, nl_fragments: list | None = None, rhyme: str = "none",
        tags: list[str] | None = None, forced: set[str] | None = None,
        stanza: list[dict] | None = None, стоп=None) -> dict:
    """The cascade. Returns {shortlist, funnel, forced_notice} — funnel is the
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
    `syllable_spec` docstring for exactly how soft it is."""
    n0 = len(lines)
    meter_gate = 0.2 + 0.6 * knobs["meter"]         # slider 0..1 → threshold 0.2..0.8
    # РУЧКА «БАНАЛЬНОСТЬ» — ДВУСТОРОННЯЯ (Раунд 58, пользователь: «на минимуме всё
    # максимально стремится к банальности, на максимуме максимально
    # неклишированно и не банально, посередине как будто не работает»).
    # Перевод положения в пороги живёт ОДНИМ куском в nlindex — им пользуются и
    # быстрый путь по индексу, и запасной по словарю, и карта воронки.
    ворота = nlindex.ворота_банальности(knobs["banal"])
    hidden = corpus.hidden_set()                    # history (not yet restored/expired) + favorites
    # «Без мата» (2026-07-31, PLAN.md) — .get, а не knobs["no_mat"]: часть
    # тестов и старых вызовов собирает knobs-словарь руками, без clean.knobs;
    # для них флаг честно отсутствует = False, а не KeyError.
    no_mat = bool(knobs.get("no_mat", False))
    # Антифильтр — второе ворото той же ручки (см. clean.knobs: only_mat)
    only_mat = bool(knobs.get("only_mat", False))
    # Клаузула и связность соседних строк — Раунд 44, откалибровано по
    # референсным текстам пользователя (см. scan.clausula и _FLOW_MAX).
    clausula = int(knobs.get("clausula", 0) or 0)
    flow = float(knobs.get("flow", -1.0))
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
                            cap=max(300, int(knobs["shortlist"]) * 8))

    # Тема без запихивания (2026-07-17, PLAN.md 0.2 — see _nl_scored for the
    # full story). `stanza_size` MIRRORS interface/react-app/src/App.jsx's
    # FREE_CHUNK=4 (no-scheme stanza length) — keep in sync, same discipline
    # as rhyme_scheme/normalizeScheme; drifting apart doesn't break anything,
    # it just makes "≈1 literal match per stanza" less accurate (this is a
    # soft cap over the whole returned buffer, not a per-window guarantee).
    # theme_similarities does ONE batched matmul for the whole vocabulary
    # here (sub-10ms) instead of _nl_scored recomputing a fresh dot product
    # per word per fragment — measured ~300-450ms slower per themed request
    # the first way (~150k fragments × ~4 words each), see embeddings.py.
    theme_sims = embeddings.theme_similarities(embeddings.theme_vector(tags)) if tags else None
    stanza_size = len(rhyme) if rhyme != "none" else 4
    literal_cap = max(1, round(knobs["shortlist"] / stanza_size)) if tags else None
    forced = set(forced) if forced else set()   # normalize: caller may pass a list/None
    # Связность — перцентиль-таргет, не множитель (2026-07-18, ТРЕТЬЯ версия
    # этого механизма — см. _nl_scored для полной истории двух предыдущих и
    # измерений, поймавших баг: 0.55 и 1.00 давали 7/8 одинаковых строк).
    # `knobs["cohesion"]` идёт в _nl_scored НАПРЯМУЮ, без знакового
    # преобразования — сам перцентиль-таргет и есть искомое поведение.
    cohesion = knobs["cohesion"]
    # Якорная строка (2026-07-18, пользователь: «даже при диссонансе должна быть
    # строка которая точно в тему... а консонирующие... не должны быть
    # идентичными основной но быть рядом» — см. _select_with_rhyme). Только
    # когда есть и тема, и nl-контент, из которого можно выбрать якорь —
    # обычные (не-nl) строки не несут `_pctl` вообще, см. _nl_scored.
    use_theme_anchor = bool(tags) and knobs["nl_mix"] > 0
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
    NL_SELECT_CAP = max(300, int(knobs["shortlist"]) * 8)

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

    # -- stage 3: banality (frequency via wordfreq + blacklist + clichés) ----
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
        if clausula and scan_mod.clausula(sc.rhyme or "") != clausula:
            continue
        # Грамматические строки extendo: у них нет колонки сцепки (её даёт
        # статистика корпуса), поэтому здесь работает только словесная ось —
        # обе её стороны.
        _b = _banality(L)
        if _b > ворота.слова_верх or _b < ворота.слова_низ:
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
    _idx = _index_for_current_cache() if nl_fragments else None
    if _idx is not None:
        nl_survivors, n_nl_survived, forced_candidates = nlindex.select(
            _idx,
            pool_mask=nlindex.pool_mask(_idx, nl_fragments),
            hidden_mask=nlindex.mask_of(_idx, hidden),
            tags=set(tags or ()), forced=set(forced or ()),
            ворота=ворота, no_mat=no_mat, only_mat=only_mat,
            clausula=clausula, cohesion=cohesion,
            pctl_scale=_PCTL_SCALE, literal_cap=literal_cap,
            cap=NL_SELECT_CAP, reserve_n=min(1_000_000, max(30, n_blocks * 5)),
            use_theme_anchor=use_theme_anchor, syllable_spec=syllable_spec,
            per_bucket=1, sims=theme_sims)
        nl_survivors_full = nl_survivors      # резервы уже внутри; ниже они не досчитываются
    else:
        nl_survivors, forced_candidates = _nl_scored(nl_fragments or [], corpus, hidden, ворота,
                                                     tags=tags, theme_sims=theme_sims,
                                                     literal_cap=literal_cap, forced=forced,
                                                     cohesion=cohesion, no_mat=no_mat, only_mat=only_mat,
                                                     clausula=clausula)
        random.shuffle(nl_survivors)                   # break ties (mostly bias=0) before a stable sort
        nl_survivors.sort(key=lambda r: r["score"], reverse=True)
        n_nl_survived = len(nl_survivors)               # TRUE count, captured before the selection cap below
        nl_survivors_full = nl_survivors                # pre-cap reference — the reserves below search THIS
    if _idx is not None:
        pass                                            # усечение и резервы сделаны в nlindex.select
    elif use_theme_anchor:
        # NL_SELECT_CAP below truncates by the COHESION-DRIVEN `score` — at
        # "диссонанс" that score deliberately favors LOW-relevance fragments
        # (see _nl_scored's docstring), so without this, truncation throws
        # away every genuinely on-theme fragment before _select_with_rhyme's
        # theme-anchor position ever gets to see them. Found live (2026-07-18):
        # anchors picked at cohesion=0.0 came out completely unrelated to the
        # theme ("Тарас заволновался и мы" for theme «секс») — «точно в тему»
        # needs SOME true-relevance survivors regardless of where the
        # score-sort truncation lands. Reserve the top-percentile fragments
        # unconditionally, on TOP of (not instead of) the score-based cap —
        # `reserve_n` sized generously per stanza block so the anchor
        # position has real choice (rhyme/repeat constraints still apply),
        # not just one single option that might not even fit.
        reserve_n = min(len(nl_survivors_full), max(30, n_blocks * 5))
        reserved = sorted(nl_survivors_full, key=lambda r: r.get("_pctl", 0.0), reverse=True)[:reserve_n]
        capped = nl_survivors_full[:NL_SELECT_CAP]
        capped_ids = {id(r) for r in capped}
        nl_survivors = capped + [r for r in reserved if id(r) not in capped_ids]
    else:
        nl_survivors = nl_survivors_full[:NL_SELECT_CAP]
    if syllable_spec and _idx is None:
        # Same shape as the theme-anchor reserve just above, for LENGTH
        # instead of relevance — see _syllable_reserve's own docstring for
        # the live case that motivated it (859 hidden "ом" matches).
        have = {id(r) for r in nl_survivors}
        nl_survivors = nl_survivors + [r for r in _syllable_reserve(nl_survivors_full, syllable_spec)
                                        if id(r) not in have]

    # -- stage 3c: «Классика» здесь БОЛЬШЕ НЕ СТРОИТСЯ (Раунд 50) ------------
    # До этого раунда рядом со строгим ярусом собирался второй, светлый пул, и
    # дальше две ветки сборки делили выдачу квотами classic_quota/algo_quota,
    # смешивая ярусы в ОДНОЙ строфе. Переключатель стал бинарным (пользователь:
    # «либо одно, либо другое»), и весь этот слой оказался недостижим: до сюда
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
    random.shuffle(scored)
    scored.sort(key=lambda r: r["score"], reverse=True)
    size = min(knobs["shortlist"], len(scored) + len(nl_survivors))
    div = 0.3 + 0.5 * knobs["explore"]              # explore knob = how hard to spread neighbours

    if knobs["nl_mix"] >= 1.0:
        # Hard contract: real_text at max → EVERY line is nakedlunch, never
        # padded with generated ones. Supply-limited themes shrink the
        # shortlist instead of being diluted (found 2026-07-14: the old
        # min(len(nl_survivors), ...) quota silently backfilled the shortfall
        # with grammar lines — the user's "5 nakedlunch lines scattered among
        # generated ones at max real_text" report).
        size = min(knobs["shortlist"], len(nl_survivors))
        if rhyme != "none":
            shortlist = _select_with_rhyme(nl_survivors, rhyme, size, set(range(size)),
                                            precision=knobs["rhyme_precision"],
                                            mat_share=knobs.get("mat_share", 0.0), flow=flow,
                                            repeat_ok=repeat_ok,
                                            theme_anchor=use_theme_anchor, syllable_spec=syllable_spec,
                                            стоп=стоп)
        else:
            shortlist = _diversify(nl_survivors, size, div)
    elif knobs["nl_mix"] <= 0.0:
        # Hard contract: real_text at min → NEVER a nakedlunch line, not even
        # as a rhyme-slot filler (found 2026-07-14: _select_with_rhyme's slot
        # relaxation could let an nl fragment fill a rhyme slot no grammar
        # candidate could satisfy). Excluding nl_survivors from the candidate
        # pool entirely — not just zeroing its quota — is what makes that
        # impossible rather than merely unlikely.
        size = min(knobs["shortlist"], len(scored))
        if rhyme != "none":
            shortlist = _select_with_rhyme(scored, rhyme, size, precision=knobs["rhyme_precision"],
                                            mat_share=knobs.get("mat_share", 0.0), flow=flow,
                                            repeat_ok=repeat_ok,
                                            syllable_spec=syllable_spec, стоп=стоп)
        else:
            shortlist = _diversify(scored[: max(300, size * 8)], size, div)
    else:
        nl_quota = min(len(nl_survivors), round(size * knobs["nl_mix"]))
        if rhyme != "none":
            # Merge grammar + nakedlunch into ONE pool and pick POSITION BY
            # POSITION, so the rhyme scheme and the nl_mix quota are honored on
            # the SAME sequence. Searching the full `scored` list (not an MMR-
            # sized top-300 pool) matters here: rhyme needs a match on ENDING,
            # not on rank — see _select_with_rhyme's own docstring for measurements.
            nl_positions = _nl_slot_plan(size, nl_quota)
            shortlist = _select_with_rhyme(scored + nl_survivors, rhyme, size, nl_positions,
                                            precision=knobs["rhyme_precision"],
                                            mat_share=knobs.get("mat_share", 0.0), flow=flow,
                                            repeat_ok=repeat_ok,
                                            theme_anchor=use_theme_anchor, syllable_spec=syllable_spec,
                                            стоп=стоп)
        else:
            grammar_size = size - nl_quota
            pool = scored[: max(300, grammar_size * 8)]     # diversify among the best candidates
            grammar_picks = _diversify(pool, grammar_size, div)

            # nl_survivors need the SAME diversity pass among themselves: cutter.py's
            # sliding windows produce overlapping near-duplicate cuts of one sentence
            # ('...ХОЛОД. Но Холод ему' / '...ХОЛОД. Но Холод ему нужен так'), all
            # scoring similarly — a naive top-N by score let 3 of them into one
            # shortlist together. A raw top-N is fine for grammar candidates (they're
            # independently generated, rarely near-duplicates of each other), but not here.
            nl_take = _diversify(nl_survivors, nl_quota, div)

            # Spread the reserved nl_take through the sequence (every `stride`-th slot)
            # instead of clumping it at one end — keeps the "reads as one flowing
            # draft" property from the diversity pass even though nl_take bypassed it.
            shortlist = []
            stride = max(1, len(grammar_picks) // max(1, len(nl_take)))
            ni = 0
            for i, item in enumerate(grammar_picks):
                shortlist.append(item)
                if ni < len(nl_take) and (i + 1) % stride == 0:
                    shortlist.append(nl_take[ni]); ni += 1
            while ni < len(nl_take):
                shortlist.append(nl_take[ni]); ni += 1

    # !слово — hard guarantee, AFTER selection is final (see _ensure_forced's
    # own docstring for why this can't fold into the scoring/selection
    # machinery above). Runs on the pre-pop shape (rows still carry `_lem`,
    # same as every other shortlist item at this point) so an inserted
    # candidate goes through the SAME lemmas/classic normalization below.
    forced_notice = _ensure_forced(shortlist, forced, forced_candidates, rhyme,
                                   knobs["rhyme_precision"], hidden)

    nl_in_shortlist = sum(1 for r in shortlist if r["template"] == "nakedlunch")
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
                   "nl_classic_survived": 0, "nl_classic_used": 0},
        "forced_notice": forced_notice,
    }


def _j(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _last_word(text: str) -> str:
    tokens = text.strip().split()
    return tokens[-1].strip(".,!?:;\"'()»«—-").lower() if tokens else ""


def _rhyme_prefix_len(precision: float) -> int | None:
    """None = exact key match (precision<=0 — the only behavior that existed
    before 2026-07-14, kept as the default). Otherwise, the number of LEADING
    characters of the key (which always starts at the stressed vowel) that
    must match for two lines to count as rhyming. Discretized into 3 tiers
    rather than continuous: a fixed prefix length lets the anchor
    partner-count check in _select_with_rhyme bucket candidates in O(1); a
    length computed per-PAIR (e.g. relative to each key's own length) would
    need an O(candidates²) scan to find partners instead."""
    if precision <= 0.0:
        return None
    if precision <= 0.34:
        return 3
    if precision <= 0.67:
        return 2
    return 1


def _rhymes(r1: dict, r2: dict, precision: float = 0.0) -> bool:
    """Check if two lines rhyme by comparing their rhyme keys (stressed vowel
    to end of word, reduced/devoiced — see scan.rhyme_key). Empty rhyme key =
    no rhyme data (nakedlunch fragments missing from the offline build). Same
    final WORD ("пепел"/"пепел") always matches its own rhyme key — that's
    not a rhyme, it's a repeat, so it's excluded explicitly.

    `precision` (user's "Точность рифм" knob, 0=точные..1=мягкие) trades
    strictness for supply: at 0 the keys must match EXACTLY (the only
    behavior before 2026-07-14 — kept as the default so existing tuning
    doesn't shift under anyone). Above 0, only a shared LEADING run of the
    key needs to match — the key always starts at the stressed vowel, so a
    shorter required run keeps the vowel (still recognizably "the same
    sound") but tolerates the tail after it differing (asonance/consonance
    territory: 'сУде'/'красотЕ' share only the stressed 'е' — see the
    user's own screenshot 2026-07-14). At precision=1, a 1-character match
    (the stressed vowel alone) is enough."""
    k1, k2 = r1.get("rhyme"), r2.get("rhyme")
    if not k1 or not k2:
        return False
    if _last_word(r1.get("text", "")) == _last_word(r2.get("text", "")):
        return False
    plen = _rhyme_prefix_len(precision)
    if plen is None:
        return k1 == k2
    return k1[:plen] == k2[:plen]


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


def _mat_slot_plan(share: float, L: int, groups=None) -> dict:
    """Какие позиции строфы обязаны быть с матом, какие — без.

    Пользователь 2026-08-03: «максимальная крутилка берёт только мат и работает как
    антифильтр… если она на середине — половина того, половина того. Если на
    нуле — полная цензура».

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


class _Остановлено(Exception):
    """Прерывание набора по просьбе пользователя. Своё, а не из pipeline: домен
    фильтров ничего не знает о прогоне серии, и импорт ради одного класса
    сделал бы зависимость наоборот. pipeline ловит его и превращает в свой."""


# Ширина полосы разброса при раннем выходе: из скольких лучших кандидатов
# выбираем случайного. Двенадцать — компромисс: достаточно, чтобы одна книга не
# могла занять первый слот четыре строфы подряд, и мало, чтобы качество отбора
# осталось тем же (все члены полосы прошли ОДИН И ТОТ ЖЕ каскад проверок и
# стоят рядом по рангу).
ПОЛОСА = 12

_РАЗБРОС_СЕМЯ: int | None = None


def _разброс_семя():
    """Семя для разведения равных кандидатов. None — новое на каждый вызов;
    тесты (и эталонная сверка) закрепляют его, чтобы выдача была повторимой."""
    return _РАЗБРОС_СЕМЯ if _РАЗБРОС_СЕМЯ is not None else random.randrange(1 << 30)


def закрепить_разброс(семя: int | None) -> None:
    """Закрепить или отпустить семя разведения (для тестов и эталона)."""
    global _РАЗБРОС_СЕМЯ
    _РАЗБРОС_СЕМЯ = семя


def _select_with_rhyme(candidates: list, scheme: str, size: int, nl_positions: set | None = None,
                        precision: float = 0.0, theme_anchor: bool = False,
                        syllable_spec: list | None = None, mat_share: float = 0.0,
                        flow: float = -1.0, repeat_ok: bool = False, стоп=None) -> list:
    """Select `size` lines from candidates while respecting a rhyme scheme,
    applied per STANZA (a repeating block of len(scheme) lines) rather than
    once for the whole shortlist — a 40-line shortlist with "абаб" is 10
    independent abab stanzas, not one 40-line scheme (the letters don't
    extend past position 3). Each position's earlier group-mates are looked
    up within its own stanza (block_start + local_pos), not by global index.

    `candidates` may mix grammar lines and nakedlunch fragments — both carry
    a real "rhyme" key once tools/build_nl_rhyme.py has run (see _nl_scored).
    `nl_positions` reserves specific slots for a nakedlunch pick (the same
    share the "real_text" knob promises elsewhere), tried first but relaxed
    before the rhyme constraint itself is relaxed — an unfilled quota slot is
    a smaller defect than a broken rhyme. `precision` is the user's "Точность
    рифм" knob — see _rhymes for what it does to matching.

    «КЛАССИКИ» ЗДЕСЬ БОЛЬШЕ НЕТ (Раунд 50). Пока «Отбор» был долей 0..1, сюда
    приходил `classic_quota`: он резервировал подмножество nl_позиций под
    строки светлого яруса и освобождал их от рифмы, от вилки слогов, от
    сужения по рифмо-корзине и от роли тематического якоря. Переключатель
    стал бинарным, классика ушла отдельным путём (filters._run_classic) и
    сюда не доходит вовсе — освобождать от рифмы стало нечего, и все четыре
    исключения вместе с раскладкой позиций вырезаны.

    `used_texts` (рядом с индексным `used_indices`) остаётся: два пула больше
    не пересекаются по тексту, но защита от буквального дубля в одной выдаче
    стоит дёшево и переживает будущие правки состава кандидатов.

    Also refuses to repeat a LEMMA across the same stanza (2026-07-18 —
    user's screenshot: "чек" landed in 2 of 4 lines of one абаб stanza; a
    live check right after found at least one lemma clash in every one of 10
    consecutive stanzas, because this function's selection loop only ever
    knew about rhyme and score, never content overlap — unlike _diversify,
    which already had this guard but isn't even called on this path, the
    DEFAULT one, since a rhyme scheme is active by default). Priority order
    when a position can't get everything: syllable length (see
    `syllable_spec` below) is softest of all, giving way first; slot kind
    (grammar/nl) next; a lemma repeat is tried after that, ONLY as a
    last resort BEFORE the rhyme constraint itself gets broken — see the
    scan_for() tier cascade below. Never silently drops a position.

    `syllable_spec` (2026-07-18, PLAN.md 0.7 — the stanza constructor):
    optional list of (min_syl, max_syl) tuples, one per position in
    `scheme` (same length, `syllable_spec[local_pos]`). When given, each
    position PREFERS a candidate whose `syllables` falls in range, but this
    is the softest constraint in the whole cascade — user's explicit call
    when asked "if no candidate of the right LENGTH exists for a position,
    what gives first": "рифма важнее" (rhyme matters more). A length
    mismatch never breaks rhyme, slot kind, or the no-repeat rule; it only
    decides which of several otherwise-equal candidates wins. `None` (the
    default, and what every scheme-string-only caller still passes) means
    no length opinion at all — behavior is byte-for-byte what it was before
    this parameter existed.

    `theme_anchor` (2026-07-18 — user: «даже при диссонансе должна быть
    строка которая точно в тему по запросу... а консонирующие ни в коем
    случае не должны быть идентичными основной но быть рядом... ни одна
    строка не должна быть похожа на константную запрашиваемую»). Two
    DIFFERENT mechanisms, both scoped to `local_pos == 0` of each stanza
    block:
      1. That position becomes a THEME anchor — required to be an
         nl-sourced, algorithm-tier candidate (only those carry `_pctl`,
         see _nl_scored) ranked by RAW relevance percentile, not by `score`
         (whose cohesion-driven target may currently favor LOW relevance —
         wrong signal for "точно в тему", which must hold regardless of
         where the cohesion slider sits). Falls through to the ordinary
         (non-anchor) selection tiers if no such candidate is available for
         that stanza — an honest degrade (`anchor` just stays False for
         that block), never a crash or a broken stanza.
      2. Once an anchor is chosen, EVERY other candidate for the REST of
         that block is checked against it via `embeddings.lemma_centroid`
         cosine similarity (`_ANCHOR_SIM_CEILING`) — independent of, and in
         ADDITION to, the lemma-overlap no-repeat rule above (that rule
         catches exact word reuse; a near-paraphrase can share zero lemmas
         and still be "the same line again" in meaning, which is what the
         user's «не должны быть идентичными» is actually about). This
         applies to EVERY other position regardless of whether cohesion is
         pushing it toward or away from the theme — "near/far from the
         theme" and "a copy of THIS specific line" are orthogonal, and only
         the second one is being policed here.
    Deliberately scoped to `local_pos == 0` only (not randomized, not
    per-group) — simple, deterministic, and the frontend can always find
    "the anchor" at a fixed spot. Only activated when the caller detected a
    theme AND nl-eligible content exist (see `run()`'s `use_theme_anchor`);
    candidates from the grammar generator never carry `_pctl` and can't
    serve as an anchor, but they're still checked against a stanza's anchor
    similarity ceiling like anyone else."""
    if scheme == "none" or not scheme or size == 0:
        # Без схемы позиции ничем не связаны — доля мата всё равно обязана
        # соблюдаться (Раунд 39): иначе «80% мата» молча не работало бы на
        # единственном пути, где рифмы нет вовсе.
        план = _mat_slot_plan(mat_share, size)
        if not план:
            return candidates[:size]
        нужно_мата = sum(1 for v in план.values() if v)
        с_матом = [c for c in candidates if c.get("mat")]
        без_мата = [c for c in candidates if not c.get("mat")]
        взято = с_матом[:нужно_мата] + без_мата[:size - нужно_мата]
        # не хватило одной из корзин — добираем чем есть, строка важнее доли
        if len(взято) < size:
            есть = {id(c) for c in взято}
            взято += [c for c in candidates if id(c) not in есть][:size - len(взято)]
        return взято[:size]

    nl_positions = nl_positions or set()
    groups = _rhyme_scheme_groups(scheme)
    L = len(scheme)
    mat_positions = _mat_slot_plan(mat_share, L, groups)
    selected: list = []
    used_indices: set = set()
    used_texts: set = set()
    plen = _rhyme_prefix_len(precision)

    def bucket(k: str | None) -> str | None:
        """Groups candidates for the O(1) anchor partner-count check below —
        must agree with _rhymes' own notion of "same rhyme" at this precision
        (a fixed prefix length, not min()'d against the OTHER key's length —
        see _rhymes' docstring for why: keeping both sides of this comparison
        on the same rule is what makes the cheap bucket count and the exact
        pairwise check agree)."""
        if not k:
            return None
        return k if plen is None else k[:plen]

    # Live count of not-yet-used candidates per rhyme bucket. Without this,
    # the ANCHOR of a pair (its first line) gets picked by score alone — which
    # regularly locks in a rare/unique ending with zero partners anywhere in
    # the pool, silently breaking that pair for the rest of the run (measured:
    # ~half of abab stanzas had a broken group before this check existed).
    #
    # `bucket_members`/`bucket_lemma_index` (2026-07-18) — the anchor branch
    # below used to answer "does this bucket have an unused, lemma-distinct
    # partner for `cand`" with a scan over ALL candidates, run for every
    # candidate scan_for considers at an anchor position. User reported the
    # editor's normal buffer fetch (100 lines / 25 "абаб" stanzas → ~800
    # candidates once NL_SELECT_CAP applies) taking 5-10s; profiling
    # (cProfile) pinned >80% of that on this exact scan — a 45-MILLION-call
    # genexpr, O(anchor positions × candidates × candidates). Isolated:
    # disabling just this check dropped a measured 16.0s run to 2.6s.
    # Fix: index each bucket's members by the LEMMAS they contain
    # (`bucket_lemma_index[bucket][lemma] = {member indices}`) once, up
    # front; `has_distinct_bucket_partner` then only touches the postings
    # for `cand`'s OWN (few) lemmas — bounded by bucket size, not by the
    # whole candidate pool — instead of rescanning everything per query.
    # `bucket_members` is the live "not yet used" set per bucket, discarded
    # from in `take()`, exactly mirroring what `key_count` already tracked
    # (kept alongside it, not replacing it, since key_count's cheap raw
    # count is still what the `< 2` gate above reads). Produces the IDENTICAL
    # true/false per query as the old scan (same j≠i / unused-by-index /
    # unused-by-text / same-bucket / no-shared-lemma conditions) — this is a
    # complexity fix, not a behavior or quality change.
    key_count: dict = {}
    bucket_members: dict = {}
    bucket_lemma_index: dict = {}
    # Корзина кандидата — срез его рифмо-ключа, величина неизменная. Считалась
    # заново в каждом скане на якорной позиции, то есть десятки тысяч срезов
    # строк на позицию; здесь она считается один раз и живёт списком.
    корзина: list = []
    for idx, c in enumerate(candidates):
        b = bucket(c.get("rhyme"))
        корзина.append(b)
        if b:
            key_count[b] = key_count.get(b, 0) + 1
            bucket_members.setdefault(b, set()).add(idx)
            li = bucket_lemma_index.setdefault(b, {})
            for lemma in c["_lem"]:
                li.setdefault(lemma, set()).add(idx)

    # ПОРЯДОК ПО РАНГУ — то, что превращает полный перебор в ранний выход
    # (Раунд 56).
    #
    # ЗАЧЕМ. Замер на цепочке пользователя: один текст — 777 секунд, и 688 из них
    # уходит на ОДНО звено, Одическую строфу в десять строк. Разбор: пул после
    # слогового резерва — 41-74 тысячи кандидатов (по 4 строки на каждый из
    # 18 489 рифмо-ключей в вилке), а `scan_for` на якорной позиции честно
    # обходит их ВСЕ, чтобы найти максимум ранга. Якорных позиций в оде пять на
    # блок плюс тематическая, блоков пятьдесят — то есть триста полных
    # проходов по семидесяти тысячам за один пул.
    #
    # А максимум искать перебором незачем. Когда связность выключена
    # (`flow_target is None` — у пользователя она выключена, но условие проверяется
    # честно, а не предполагается), ранг кандидата — это его собственный
    # `score` (или `_pctl` у тематического якоря), и от позиции он не зависит
    # вовсе. Значит достаточно идти по заранее отсортированному порядку и взять
    # ПЕРВОГО подходящего: он и есть argmax.
    #
    # ЭКВИВАЛЕНТНОСТЬ, включая ничьи. Старый цикл берёт кандидата по строгому
    # `rank > best_rank`, то есть при равных рангах побеждает ВСТРЕЧЕННЫЙ
    # ПЕРВЫМ — а встречались они в порядке номеров. Поэтому ключ сортировки
    # здесь `(-ранг, номер)`: при равных рангах впереди меньший номер, ровно
    # тот же победитель. Обход по корзине (позиция-последователь) оставлен
    # старым циклом НАРОЧНО: там порядок обхода — это порядок множества
    # `bucket_members`, воспроизвести его сортировкой нельзя, а искать там и
    # нечего — корзина это десятки строк, а не десятки тысяч.
    #
    # Кандидат без `_pctl` тематическим якорем быть не может (см. scan_for), и
    # в порядок по перцентилю не попадает — это не сужение, а тот же отсев.
    # РАВНЫЕ ПО БАЛЛУ — В СЛУЧАЙНОМ ПОРЯДКЕ (Раунд 57).
    #
    # Тай-брейком был индекс, то есть порядок кандидатов в пуле. Порядок этот
    # стабилен, балл округлён до четырёх знаков и совпадает у сотен строк —
    # значит при одних и тех же настройках выдача шла по одному и тому же
    # списку сверху вниз. История вычитает только ТОЧНЫЕ повторы, поэтому
    # следующий прогон брал соседей: та же книга, та же сцена. Пользователь прислал
    # снимок истории — двенадцать реплик одной пьесы подряд — и сказал: «это не
    # строгая выдача, он выдаёт примерно одно и то же». И добавил, что темы при
    # этом не было вовсе: дело не в привязке к теме, а в самом порядке.
    #
    # Случайность идёт ТОЛЬКО между равными: у кого балл выше, тот и выше.
    # Качество отбора не меняется ни на шаг — меняется, кого из одинаково
    # хороших мы возьмём сегодня.
    _мешок = random.Random(_разброс_семя())
    порядок_score = sorted(range(len(candidates)),
                           key=lambda i: (-candidates[i]["score"], _мешок.random()))
    порядок_pctl = sorted((i for i in range(len(candidates)) if "_pctl" in candidates[i]),
                          key=lambda i: (-candidates[i]["_pctl"], _мешок.random()))

    def has_distinct_bucket_partner(i: int, cand: dict, b: str) -> bool:
        """Is there a still-unused member of bucket `b`, other than `cand`
        itself, sharing NONE of `cand`'s lemmas? See the perf note above —
        O(bucket size), touching only postings for `cand`'s own lemmas,
        not a scan of every candidate."""
        overlapping = {i}
        li = bucket_lemma_index.get(b) or {}
        for lemma in cand["_lem"]:
            overlapping |= li.get(lemma, ())
        for j in bucket_members.get(b, ()) - overlapping:
            if candidates[j]["text"] not in used_texts:
                return True
        return False

    def consume(i: int) -> None:
        """Mark candidate `i` used without adding it to `selected` — for a
        source fragment absorbed into a synthetic splice/trim row (see
        `take_synthetic`) rather than appearing on its own."""
        used_indices.add(i)
        used_texts.add(candidates[i]["text"])
        b = корзина[i]
        if b:
            key_count[b] -= 1
            bucket_members[b].discard(i)

    def take(i: int) -> None:
        selected.append(candidates[i])
        consume(i)

    def take_synthetic(row: dict, *idxs: int) -> None:
        """Same bookkeeping as `take`, for a row built out of one or more
        existing candidates (splice: 2 sources; trim: 1) instead of a
        candidate taken as-is."""
        selected.append(row)
        for i in idxs:
            consume(i)

    def kind_of(cand: dict) -> str:
        if cand.get("template") != "nakedlunch":
            return "grammar"
        return "nl"

    # Per-candidate meaning vectors for the theme-anchor similarity check —
    # computed ONCE up front (not per scan_for query, which would reintroduce
    # the exact O(candidates²) shape the perf note above just fixed), and
    # only when `theme_anchor` is actually in play (no cost for themeless or
    # nl_mix=0 runs, the overwhelmingly common case for this branch to skip).
    # `None` for a candidate whose lemmas the embeddings model has nothing
    # for — `has_anchor_conflict` below treats that as "no opinion", never
    # as "similar" or "distinct" (see embeddings.lemma_centroid's docstring).
    # Центроиды нужны и тематическому якорю, и связности соседних строк.
    cand_centroids = ([embeddings.lemma_centroid(c["_lem"]) for c in candidates]
                      if (theme_anchor or flow >= 0.0) else None)
    stanza_anchor_centroid: dict = {}   # block_start -> centroid vector | None
    # Ответ «похож ли кандидат на якорь ЭТОЙ строфы» зависит только от пары
    # (кандидат, блок), а спрашивается он у одного и того же кандидата много
    # раз: каскад зовёт scan_for до шести раз на позицию, а позиций в блоке
    # десять. Считаем скалярное произведение один раз на пару и запоминаем —
    # арифметика та же самая до последнего бита (это memo, а не векторизация:
    # матричное умножение могло бы дать другой порядок суммирования и другой
    # последний разряд, а значит другой ответ ровно на пороге).
    _конфликт: dict = {}

    def has_anchor_conflict(i: int, block_start: int) -> bool:
        ac = stanza_anchor_centroid.get(block_start)
        if ac is None or cand_centroids is None:
            return False
        ключ = (block_start, i)
        ответ = _конфликт.get(ключ)
        if ответ is None:
            cc = cand_centroids[i]
            ответ = cc is not None and float(cc @ ac) > _ANCHOR_SIM_CEILING
            _конфликт[ключ] = ответ
        return ответ

    for pos in range(size):
        # ОСТАНОВКА СЕРИИ СПРАШИВАЕТСЯ ЗДЕСЬ (Раунд 55). Замер: один текст на
        # цепочке пользователя — 777 секунд, и 776 из них уходило на набор пулов,
        # то есть на этот цикл. Проверки в pipeline (перед пулом и на уровне
        # перебора) давали granularity в сотни секунд, и пользователь справедливо
        # сказал: «если зависло, то остановится только после генерации
        # текущего, а значит не остановится». Здесь — доли секунды.
        #
        # Раунд 56 срезал текст до 28 секунд (см. `порядок_score` выше), но
        # проверка остаётся здесь, а не поднимается обратно: цена пула зависит
        # от формы строфы и ширины пула, то есть от того, что пользователь волен
        # выкрутить в любой момент, — а обещание «стоп работает» от его
        # настроек зависеть не должно.
        if стоп is not None and стоп():
            raise _Остановлено()
        block_start = (pos // L) * L
        local_pos = pos % L
        target_group = next((g for g in groups if local_pos in g), None)
        is_rhyme_anchor = bool(target_group) and len(target_group) > 1 and local_pos == min(target_group)
        is_theme_anchor = theme_anchor and local_pos == 0
        want_kind = "nl" if pos in nl_positions else "grammar"
        # Не повторять лемму с уже выбранными строками ЭТОЙ ЖЕ строфы — hard
        # floor (2026-07-18, пользователь, скриншот: «Два гонорара» / «получил
        # два чека» / «Вот два чека» — «чек» дважды в одной строфе абаб, и
        # это НЕ единичный случай: живая проверка после первой попытки фикса
        # показала пересечение лемм в КАЖДОЙ из 10 проверенных строф). Эта
        # функция раньше вообще не знала о повторах — только score и рифма;
        # _diversify получил такой же барьер раньше, но _select_with_rhyme
        # (АКТИВНЫЙ путь при схеме "абаб" — дефолт приложения) им не
        # пользуется вообще, свой независимый цикл выбора. Строфа — не
        # «последние 3», а ВСЕ уже поставленные строки текущего блока
        # (block_start..pos): при показе «одна строфа = один взгляд»
        # (PLAN.md 0.3) именно это и есть окно, которое видит пользователь разом.
        # `repeat_ok` (Раунд 52, крутилка «Повтор») снимает барьер целиком:
        # пустой `recent` означает «повторять нечего запрещать». Пользователь:
        # «он не должен повторять только при соответствующих настройках, но
        # если я хочу повторять, пусть повторяет» — хуковый припев строится
        # именно на возвращающемся слове. Снимаем ЗДЕСЬ, а не флагом внутри
        # scan_for: барьер читается из `recent` в трёх местах каскада, и
        # четвёртое условие в каждом из них было бы четырьмя шансами
        # разойтись.
        recent = [] if repeat_ok else [selected[j]["_lem"] for j in range(block_start, pos)]
        # Барьер повтора спрашивается «пересекается ли кандидат хоть с одной из
        # уже поставленных строк блока» — а это в точности «пересекается ли он с
        # их ОБЪЕДИНЕНИЕМ». Тождество, а не приближение: A∩s≠∅ хоть для одной
        # s ⟺ A∩(∪s)≠∅. В оде поставленных строк к концу блока девять, то есть
        # девять пересечений множеств на КАЖДОГО кандидата в КАЖДОМ скане
        # превращаются в одно.
        recent_union: set = set()
        for s in recent:
            recent_union |= s
        syl_range = syllable_spec[local_pos] if syllable_spec else None

        # Цель связности для ЭТОЙ позиции: внутри части — как просили, на
        # первой строке части (то есть на стыке) — ниже, по измеренному
        # отношению _FLOW_EDGE. Нет предыдущей строки — нет и цели.
        flow_target = None
        prev_centroid = None
        if flow >= 0.0 and selected and cand_centroids is not None:
            prev_centroid = embeddings.lemma_centroid(selected[-1].get("_lem") or ())
            if prev_centroid is not None:
                flow_target = _FLOW_MAX * flow * (_FLOW_EDGE if local_pos == 0 else 1.0)

        def scan_for(require_slot: bool, allow_repeat: bool = False, theme_anchor_mode: bool = False,
                     require_length: bool = False, length_range: tuple | None = None,
                     want_mat: bool | None = None) -> int:
            best_idx, best_rank = -1, -999.0
            # `length_range` overrides the position's own `syl_range` — used by
            # the splice/trim repair below to ask "is there a VALID (rhyme/slot/
            # repeat-correct) candidate specifically in the too-short or
            # too-long band," reusing this same validity logic instead of
            # duplicating it.
            lr = length_range if length_range is not None else syl_range
            # A FOLLOW position in an already-established rhyme group (the
            # group's first member is already `selected`) only ever accepts
            # candidates from that ONE bucket — `bucket()` mirrors `_rhymes()`'s
            # own notion of "same rhyme" at this precision (see `bucket`'s own
            # docstring), so nothing outside it could pass the `_rhymes()` check
            # below anyway. Narrowing the SOURCE we iterate to
            # `bucket_members[that bucket]` (2026-07-19 — this is what makes
            # widening `candidates` past the old NL_SELECT_CAP score-slice safe:
            # without it, a follow position would linearly re-scan the WHOLE
            # pool, reintroducing the O(size×pool) shape #42/#43 already fixed
            # once). Anchor-establishing positions (is_rhyme_anchor) still need
            # the full range — they're choosing WHICH bucket to commit to, not
            # matching an already-fixed one. Same for classic/theme-anchor
            # positions, which aren't bucket-constrained at all.
            search_space = range(len(candidates))
            полный = True            # обходим ВЕСЬ пул, а не одну корзину
            if not theme_anchor_mode and target_group and not is_rhyme_anchor:
                first_global = block_start + min(target_group)
                if first_global < len(selected):
                    tb = bucket(selected[first_global].get("rhyme"))
                    if tb:
                        search_space = bucket_members.get(tb, ())
                        полный = False

            # ЕДИНСТВЕННЫЙ цикл на оба режима — быстрый и обычный. Правила
            # отбора существуют в одной копии (две разошлись бы при первой же
            # правке каскада), а различаются только источник обхода и то, что
            # делать с подошедшим: вернуть сразу или продолжить искать лучшего.
            #
            # Отдельной функцией-предикатом это писать нельзя: замерено на
            # обычной одиночной генерации (35 919 кандидатов) — вызов Python-
            # функции на КАЖДОГО кандидата съедал весь выигрыш и уводил в минус,
            # 15.8 с → 20.6 с. Там, где ранний выход не срабатывает (якорь в
            # мелкой рифмо-корзине), остаётся чистая накладная плата.
            ранний = полный and flow_target is None
            обход = (порядок_pctl if theme_anchor_mode else порядок_score) if ранний else search_space
            полоса: list[int] = []
            best_idx, best_rank = -1, -999.0
            for i in обход:
                cand = candidates[i]
                if i in used_indices or cand["text"] in used_texts:
                    continue
                if theme_anchor_mode:
                    # only algorithm-tier nl rows carry `_pctl` (see
                    # _nl_scored) — nothing else can serve as a theme anchor
                    if "_pctl" not in cand:
                        continue
                elif require_slot and kind_of(cand) != want_kind:
                    continue
                # Вилка слогов — тоже настройка, а значит «классике» она не
                # указ (Раунд 35). Рифмо-схему она не соблюдала с самого
                # начала (см. ниже), и держать её длиной было
                # непоследовательно: режим обещает сырьё как есть, а сырьё
                # бывает любой длины.
                if require_length and lr is not None:
                    syl = cand.get("syllables")
                    if syl is None or not (lr[0] <= syl <= lr[1]):
                        continue
                # Доля мата (Раунд 39). Предпочтение, а не инвариант: ниже по
                # каскаду оно снимается ПЕРВЫМ — раньше слоговой вилки и
                # задолго до рифмы. Порванная строфа ради процента была бы
                # худшей сделкой, чем недобранный процент.
                if want_mat is not None and bool(cand.get("mat")) != want_mat:
                    continue
                if not allow_repeat and (cand["_lem"] & recent_union):
                    continue
                valid = True
                if not is_theme_anchor and has_anchor_conflict(i, block_start):
                    # "too similar to this stanza's anchor line" — see the
                    # function's own docstring; independent of rhyme/slot/
                    # repeat checks below, applies to grammar lines too.
                    valid = False
                # "классика" positions are exempt from the rhyme scheme
                # entirely (user's explicit choice 2026-07-14) — never
                # checked as a group match or an anchor needing a partner.
                if valid:
                    if target_group and not is_rhyme_anchor:
                        for other_local in target_group:
                            if other_local < local_pos:
                                other_global = block_start + other_local
                                if other_global < len(selected) and not _rhymes(cand, selected[other_global], precision):
                                    valid = False
                                    break
                    elif is_rhyme_anchor:
                        # needs itself + at least one more unused candidate sharing
                        # its bucket, or the partner slot later in this stanza is doomed
                        b = корзина[i]
                        if not b or key_count.get(b, 0) < 2:
                            valid = False
                        elif not allow_repeat:
                            # count>=2 alone isn't enough (2026-07-18, found
                            # live: still repeating after the recent-lemma
                            # filter above) — nakedlunch rhyme buckets are
                            # often DOMINATED by near-duplicate cuts of the
                            # SAME source sentence (cutter.py's sliding
                            # windows), all sharing the anchor's own lemmas.
                            # An anchor with 5 same-bucket "partners" that are
                            # all just other slices of "...два чека..." isn't
                            # actually rhyme-safe for the no-repeat rule — the
                            # partner slot is doomed to repeat regardless of
                            # count. Need at least one bucket-mate that's
                            # ACTUALLY lemma-distinct from this anchor (see
                            # has_distinct_bucket_partner's own perf note —
                            # this used to be an inline O(candidates) scan).
                            if not has_distinct_bucket_partner(i, cand, b):
                                valid = False
                if not valid:
                    continue
                # РАННИЙ ВЫХОД С РАЗБРОСОМ (Раунд 57).
                #
                # Здесь стояло `return i` — первый подошедший по убыванию ранга,
                # то есть жадный максимум. И это оказалось уязвимостью, а не
                # оптимизацией. Банальность считается по САМОМУ РЕДКОМУ слову
                # строки: чем реже, тем выше балл. Имя собственное — «СЕНТ-АНЖ»,
                # «ДОЛЬМАНСЕ» — в языке почти не встречается, значит любая
                # строка с ним получает лучший балл по редкости и забирает
                # первый слот строфы. Пользователь: «у меня везде почему-то Г-ЖА ДЕ
                # СЕНТ-АНЖ, хотя у меня два миллиона фрагментов; причём это
                # пустая строка, это имя персонажа, это бред».
                #
                # Копим ПОЛОСУ лучших и берём из неё случайного. Полоса узкая,
                # поэтому качество то же: все её члены прошли те же проверки и
                # стоят рядом по рангу. Ранний выход сохраняется — мы не
                # досматриваем пул до конца, а лишь до конца полосы.
                #
                # ЯКОРЬ ТЕМЫ — БЕЗ РАЗБРОСА. `theme_anchor_mode` — это обещание
                # «строка точно в тему», и оно должно выполняться буквально:
                # лучший по перцентилю, а не случайный из полосы лучших. Полоса
                # нужна обычным слотам, где «лучший» определён с точностью до
                # четвёртого знака и потому произволен.
                if ранний and theme_anchor_mode:
                    return i
                if ранний:
                    полоса.append(i)
                    if len(полоса) >= ПОЛОСА:
                        return _мешок.choice(полоса)
                    continue
                # theme-anchor selection ranks by RAW relevance percentile,
                # not by `score` — `score` reflects the COHESION TARGET
                # (could favor low relevance at "диссонанс"), the wrong
                # signal for "точно в тему по запросу" (see docstring).
                rank = cand["_pctl"] if theme_anchor_mode else cand["score"]
                # Связность с ПРЕДЫДУЩЕЙ строкой (Раунд 44). Не фильтр, а
                # прибавка: чем ближе связь к запрошенной, тем выше ранг.
                # Ломать ради связности рифму нельзя — она свойство
                # постепенное, в отличие от мата и клаузулы.
                if flow_target is not None and cand_centroids is not None:
                    текущ = cand_centroids[i]
                    if текущ is not None:
                        cos = _cos(prev_centroid, текущ)
                        if cos is not None:
                            rank += _FLOW_W * (1.0 - min(1.0, abs(cos - flow_target)))
                if rank > best_rank:
                    best_rank, best_idx = rank, i
            # Полоса не добралась до полной ширины — пул кончился раньше. Берём
            # случайного из того, что набралось: это те же лучшие, просто их
            # оказалось меньше двенадцати.
            if полоса:
                return _мешок.choice(полоса)
            return best_idx

        def _find_filler(lo: int, hi: int, exclude_idx: set, exclude_lem: set) -> int:
            """A short, otherwise-unconstrained candidate to prepend ahead of a
            too-short TAIL (see `_repair_length`) — any kind, any rhyme; only
            length, no-repeat, and anchor-conflict apply. Reused for both nl
            and grammar rows — this is what lets the SAME splice repair also
            cover the generator's own too-short-target case, not just
            nakedlunch's (2026-07-19, user's own connection between the two)."""
            # Тот же ранний выход, что в scan_for, и по той же причине: ранг
            # здесь — чистый `score`, связность в него не входит вовсе, значит
            # первый подходящий в порядке (-score, номер) и есть максимум.
            for i in порядок_score:
                cand = candidates[i]
                if i in used_indices or i in exclude_idx or cand["text"] in used_texts:
                    continue
                syl = cand.get("syllables")
                if syl is None or not (lo <= syl <= hi):
                    continue
                if cand["_lem"] & exclude_lem or (cand["_lem"] & recent_union):
                    continue
                if not is_theme_anchor and has_anchor_conflict(i, block_start):
                    continue
                return i
            return -1

        def _splice_row(head_idx: int, tail_idx: int) -> dict:
            head, tail = candidates[head_idx], candidates[tail_idx]
            text = f'{head["text"]} {tail["text"]}'
            offset = len(head["text"]) + 1
            tail_span = tail.get("rhyme_span")
            span = [tail_span[0] + offset, tail_span[1] + offset] if tail_span else None
            return {"text": text, "template": tail["template"], "meter": tail.get("meter"),
                    "rhyme": tail.get("rhyme"), "rhyme_span": span,
                    "syllables": head["syllables"] + tail["syllables"],
                    "score": round((head["score"] + tail["score"]) / 2, 4),
                    "_lem": head["_lem"] | tail["_lem"],
                    "classic": bool(head.get("classic")) or bool(tail.get("classic")),
                    "spliced": True}

        def _trim_row(idx: int) -> dict | None:
            """Drop whole leading words from an overlong nl fragment until it
            fits `syl_range`, never touching the LAST word — `rhyme_span`
            (see nl_rhyme.json / tools/build_nl_rhyme.py) always lands inside
            it, so the rhyme itself is untouched by construction. NL-sourced
            only (2026-07-19): a grammar Line's per-word lemma structure
            doesn't survive to this layer's flattened `_lem` set (see stage
            3's row construction in run()), so there's no safe way to shrink
            it after trimming a word away — out of scope for this pass;
            overlong grammar candidates keep today's as-is behavior."""
            cand = candidates[idx]
            if cand.get("template") != "nakedlunch":
                return None
            entry = _NL_RHYME.get(cand["text"])
            if not entry:
                return None
            words = cand["text"].split()
            if len(words) < 2:
                return None
            lo, hi = syl_range
            best_cut, best_dist = None, None
            for cut in range(1, len(words)):
                text = " ".join(words[cut:])
                syl = sum(1 for ch in text.lower() if ch in VOWELS)
                if syl < 1:
                    break
                dist = 0 if lo <= syl <= hi else min(abs(syl - lo), abs(syl - hi))
                if best_dist is None or dist < best_dist:
                    best_cut, best_dist = cut, dist
                if syl <= lo:
                    break   # further cuts only remove more — strictly worse past this point
            if best_cut is None:
                return None
            kept = words[best_cut:]
            text = " ".join(kept)
            removed = len(cand["text"]) - len(text)
            span = cand.get("rhyme_span")
            new_span = [span[0] - removed, span[1] - removed] if span else None
            # Леммы обрезанного куска считаем ПО НЕМУ САМОМУ (Раунд 34).
            # Раньше они собирались из записи кэша nl_rhyme.json: там
            # `tokens` и `lemmas` — параллельные списки по СЛОВОФОРМАМ, и zip
            # давал карту слово→лемма. С переездом на колоночный индекс кэш
            # больше не грузится, а в индексе леммы лежат МНОЖЕСТВОМ (так
            # нужно релевантности), и параллельность потеряна. Прямой вызов
            # честнее и не дороже: обрезка случается на единицы кандидатов за
            # запрос, а не на миллионы фрагментов.
            lem = set(lemmatize(text))
            return {"text": text, "template": "nakedlunch", "meter": None,
                    "rhyme": cand.get("rhyme"), "rhyme_span": new_span,
                    "syllables": sum(1 for ch in text.lower() if ch in VOWELS),
                    "score": cand["score"], "_lem": lem, "classic": cand.get("classic", False),
                    "trimmed": True}

        def _repair_length(tail_idx: int) -> tuple:
            """Try to make `tail_idx` — already the position's best
            rhyme/slot/repeat-VALID pick, chosen ignoring length — FIT
            `syl_range` instead of accepting it (or a worse fallback)
            out-of-range as-is. The user's own proposal, 2026-07-19, after
            the Онегинская строфа bug report (859 correct-rhyme
            correct-length "ом" survivors existed, hidden by the score cap
            — see `_syllable_reserve` — but the SPECIFIC candidate
            scan_for(True) picked was an 11 or a 27-syllable one regardless).

            Splice (too short): `tail_idx` already carries the position's
            correct rhyme (scan_for's own `valid` check enforces that
            regardless of `require_length` — true for an ordinary rhyme
            group AND for a theme-anchor pick, since both go through the
            same `valid` computation), so it becomes the line's TAIL;
            prepend a short, otherwise-unconstrained HEAD to reach the
            range. Trim (too long): drop leading words from `tail_idx`; the
            rhyme-bearing LAST word is never touched — see `_trim_row`.
            Returns (None, ()) if the length already fits, or neither repair
            finds a workable pair — the caller then falls through to the
            pre-existing "accept it out-of-range" behavior unchanged, so
            this is purely additive: it can only IMPROVE the outcome, never
            worse than before this existed. A single shared entry point for
            BOTH the theme-anchor's own pick and the ordinary tier-2 pick
            (2026-07-19 — found live: an EARLIER version of this only
            covered the ordinary path, and the Онегинская строфа's own
            anchor line — position 0, badged ◆ — still came out at 10
            syllables against an 8-9 spec)."""
            if syl_range is None or tail_idx < 0:
                return None, ()
            lo, hi = syl_range
            tail = candidates[tail_idx]
            syl = tail["syllables"]
            if lo <= syl <= hi:
                return None, ()
            if syl < lo and hi >= 2:
                shortfall_hi = hi - syl
                shortfall_lo = max(1, lo - syl)
                if shortfall_hi >= 1:
                    head_idx = _find_filler(shortfall_lo, shortfall_hi, {tail_idx}, tail["_lem"])
                    if head_idx >= 0:
                        return _splice_row(head_idx, tail_idx), (head_idx, tail_idx)
            elif syl > hi:
                trimmed = _trim_row(tail_idx)
                if trimmed is not None:
                    return trimmed, (tail_idx,)
            return None, ()

        best_idx = -1
        synthetic, synthetic_sources = None, ()
        anchor_pick = False   # was the (possibly since-repaired) pick made via theme_anchor_mode?
        if is_theme_anchor:
            best_idx = scan_for(True, theme_anchor_mode=True)
            if best_idx < 0:
                best_idx = scan_for(False, theme_anchor_mode=True)
            if best_idx >= 0:
                anchor_pick = True
                synthetic, synthetic_sources = _repair_length(best_idx)
                if synthetic is not None:
                    best_idx = -1   # the repaired row replaces it, not the raw pick
        # Length is the SOFTEST constraint (user: «рифма важнее» — see
        # syllable_spec's own docstring) — tried first, given up first. A
        # scheme with no syllable_spec at all (every pre-constructor caller)
        # makes `require_length=True` and `=False` behave IDENTICALLY (no
        # syl_range to check against), so these two extra tiers are a no-op
        # exactly when no spec was ever passed — zero behavior change for
        # any existing scheme-string-only call site.
        # Проход «с учётом мата» — до всего остального. Не нашлось — идём
        # обычным каскадом, и доля просто не добирается на этой позиции.
        want_mat = mat_positions.get(local_pos)
        if want_mat is not None and best_idx < 0 and synthetic is None and not anchor_pick:
            for _треб_слот, _треб_длина in ((True, True), (True, False), (False, True), (False, False)):
                best_idx = scan_for(_треб_слот, require_length=_треб_длина, want_mat=want_mat)
                if best_idx >= 0:
                    break
        if best_idx < 0 and synthetic is None and not anchor_pick:
            best_idx = scan_for(True, require_length=True)
        if best_idx < 0 and synthetic is None and not anchor_pick:
            # Before giving up on length entirely (next tier), try to REPAIR
            # tier-2's own pick into one that fits — see _repair_length.
            candidate_idx = scan_for(True)
            synthetic, synthetic_sources = _repair_length(candidate_idx)
            if synthetic is None:
                best_idx = candidate_idx
        if best_idx < 0 and synthetic is None:
            best_idx = scan_for(False, require_length=True)
        if best_idx < 0 and synthetic is None:
            best_idx = scan_for(False)   # slot quota is the softer constraint
        if best_idx < 0 and synthetic is None:
            # Рифма важнее повтора (пользователь 2026-07-14: сломанная рифма —
            # больший дефект, чем незаполненная квота слота), НО повтор всё
            # ещё хуже, чем незаполненный слот kind — пробуем разрешить
            # повтор, ПРЕЖДЕ чем сдаваться и ломать саму рифмо-схему ниже.
            best_idx = scan_for(False, allow_repeat=True)

        if synthetic is not None:
            take_synthetic(synthetic, *synthetic_sources)
            if anchor_pick:
                selected[-1]["anchor"] = True
                # `synthetic_sources[-1]` is the tail — the piece that was
                # already theme_anchor_mode-valid, so ITS centroid (not the
                # spliced/trimmed row's, which mixes in an unrelated head)
                # is what later positions' has_anchor_conflict should compare
                # against — see that function's own docstring.
                stanza_anchor_centroid[block_start] = cand_centroids[synthetic_sources[-1]]
        elif best_idx >= 0:
            take(best_idx)
            if is_theme_anchor and "_pctl" in candidates[best_idx]:
                selected[-1]["anchor"] = True
                stanza_anchor_centroid[block_start] = cand_centroids[best_idx]
        else:
            # No candidate satisfies the rhyme constraint at all — best
            # remaining by score (preferring the intended slot type), so a
            # broken rhyme slot at least keeps output quality rather than
            # degrading it further.
            # Тот же ранний выход. `max(..., key=score)` возвращает ПЕРВЫЙ
            # максимум в порядке списка, а список строился по номерам — то
            # есть «лучший по оценке, при ничьей меньший номер». Обход по
            # `порядок_score` даёт ровно того же победителя, но не строит
            # список на десятки тысяч элементов ради одного из них.
            лучший_слот = лучший_любой = -1
            for i in порядок_score:
                if i in used_indices or candidates[i]["text"] in used_texts:
                    continue
                if лучший_любой < 0:
                    лучший_любой = i
                if kind_of(candidates[i]) == want_kind:
                    лучший_слот = i
                    break
            if лучший_любой < 0:
                break
            take(лучший_слот if лучший_слот >= 0 else лучший_любой)

    return selected
