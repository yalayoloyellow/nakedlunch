# extendo — the single validation layer (PRINCIPLES §6: one source of truth).
# Everything that enters the domain — a theme string, a run request, a line the
# owner marks — passes through here first. Bad input fails fast with ONE human
# sentence (PRINCIPLES §7), never a half-built object and never a traceback.

from __future__ import annotations

import re

import distort   # искажение крутилок серии (Раунд 55) — разбор кривой и шума


class BadInput(ValueError):
    """Raised with a single human-readable sentence. The caller prints str(e)."""


_THEME_RE = re.compile(r"[^\wёЁа-яА-Я\s,\-]", re.UNICODE)
_SCHEME_RE = re.compile(r"^[а-яё]{2,16}$")
_SCHEME_JUNK_RE = re.compile(r"[^а-яёa-z0-9]")
_SCHEME_CYRILLIC_RE = re.compile(r"^[а-яё]+$")
_SCHEME_ALPHABET = "абвгдежзийклмнопрстуфхцчшщъыьэюя"


def rhyme_scheme(raw) -> str:
    """A rhyme scheme is "none" or 2-16 lowercase Cyrillic letters — a preset
    (абаб) or the owner's own (абвабгабд). core/filters.py groups POSITIONS
    by matching letter, so any string in this shape is already meaningful;
    the only real validation is the shape, not membership in a fixed list.

    Латиница и цифры принимаются наравне с кириллицей (2026-07-17, PLAN.md 0.6:
    владелец хочет «прописывать её цифрами и латиницей»). Раньше любой
    не-кириллический символ проваливал `_SCHEME_RE` и схема МОЛЧА становилась
    "none" — набрал `aabb`, получил отсутствие рифмовки без единого слова.
    Нормализуем по ПАТТЕРНУ, а не по алфавиту: смысл схемы — какие позиции
    совпадают, а не какими буквами записаны, поэтому aabb ≡ 1122 ≡ аабб
    (первый встреченный символ → «а», второй → «б», …). Чистая кириллица
    возвращается КАК НАБРАНА — старое поведение не трогаем, только добавляем
    новые алфавиты (иначе «баба» превратилось бы в «абаб» и поле бы спорило с
    владельцем). Зеркалится в interface/react-app/src/App.jsx: normalizeScheme.
    """
    if not isinstance(raw, str) or raw == "none" or not raw:
        return "none"
    s = _SCHEME_JUNK_RE.sub("", raw.strip().lower())[:16]
    if not _SCHEME_CYRILLIC_RE.match(s):
        mapping: dict[str, str] = {}
        # 16 символов максимум → различных не больше 16, алфавита из 32 хватает всегда
        s = "".join(mapping.setdefault(ch, _SCHEME_ALPHABET[len(mapping)]) for ch in s)
    return s if _SCHEME_RE.match(s) else "none"


_STANZA_MAX_LINES = 32
_SYL_MIN, _SYL_MAX = 1, 30
_STANZA_LETTER_RE = re.compile(r"^[а-яё]$")


def stanza_spec(raw) -> list[dict] | None:
    """A stanza spec (2026-07-18, PLAN.md 0.7 — the stanza constructor
    replacing the plain rhyme-string field) is a list of
    {letter, min_syl, max_syl} — one entry per line of the stanza. `letter`
    groups positions that must rhyme, same meaning as `rhyme_scheme`'s
    string (core/filters.py: _rhyme_scheme_groups doesn't care what order
    letters first appear in, only which positions share one — so unlike
    `rhyme_scheme`, this does NOT require starting at 'а' with no gaps; a
    hand-edited or constructor-reordered spec using any letters is still
    valid). `min_syl`/`max_syl` are the syllable-count bounds the position's
    line should fall within — see core/filters.py:_select_with_rhyme's
    `require_length` tiers for how that's enforced (softer than rhyme,
    owner's explicit call: "рифма важнее" when the two conflict).

    None = "no spec" — every existing caller that only ever sent the plain
    `rhyme` string keeps working exactly as before; this is an ADDITIVE
    layer, not a replacement of that path. Never raises (PRINCIPLES §7 still
    applies, but a malformed spec from a stale client or hand-edited
    settings file should silently fall back to `rhyme`, not break the
    request) — out-of-range syllable counts clamp, min>max swaps, and a
    structurally invalid item makes the WHOLE spec None rather than
    half-accepting it (a half-valid stanza spec is a worse failure mode than
    "ignore it, use the plain scheme instead")."""
    if not isinstance(raw, list) or not raw or len(raw) > _STANZA_MAX_LINES:
        return None
    out = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        letter = str(item.get("letter", "")).strip().lower()
        if not _STANZA_LETTER_RE.match(letter):
            return None
        try:
            mn = int(item.get("min_syl"))
            mx = int(item.get("max_syl"))
        except (TypeError, ValueError):
            return None
        mn = max(_SYL_MIN, min(_SYL_MAX, mn))
        mx = max(_SYL_MIN, min(_SYL_MAX, mx))
        if mn > mx:
            mn, mx = mx, mn
        out.append({"letter": letter, "min_syl": mn, "max_syl": mx})
    return out


def stanza_letters(spec: list[dict]) -> str:
    """The plain rhyme-scheme letters string implied by a stanza spec — same
    shape `rhyme_scheme` produces, so a themed request built from a
    constructor spec still has a normal scheme string everywhere one is
    logged/displayed (stats.py, the funnel, the scheme-letter badge)."""
    return "".join(row["letter"] for row in spec)


def _clean_tag(part: str) -> str:
    """One comma/newline-separated theme part → one clean tag. Shared by
    theme() and theme_forced() so a forced word's cleaned form always matches
    byte-for-byte what theme() puts in tags (needed for the set-membership
    checks downstream — a mismatch would make a real word silently look
    'not in the base'). Collapses INTERNAL whitespace too, not just the ends
    (found 2026-07-17 while adding theme_forced: `_THEME_RE` allows `\\s`
    through, so a stray '!  деньги' — bang, double space — cleaned to '
    деньги' with leading spaces still attached, which then never matches any
    real fragment's cleanly-tokenized 'деньги'. Pre-existing latent gap in
    theme() too, for any tag typed with odd internal spacing — fixed here at
    the shared source rather than patched twice."""
    return "".join(_THEME_RE.sub("", part).split())


def theme(raw: str) -> list[str]:
    """A run theme is a comma/newline list of tag words. Returns clean lowercase
    tags. Empty or garbage-only input is a hard stop, not an empty run.
    `!слово` (see theme_forced) also lands here as a normal tag — `_THEME_RE`
    already strips the leading `!` since it isn't in the allowed character
    class, so a forced word gets the SAME ordinary semantic/literal theme
    treatment (PLAN.md 0.2a) as any other tag, on top of its own hard
    guarantee (0.2b)."""
    if not isinstance(raw, str):
        raise BadInput("тема должна быть строкой")
    parts = [p.strip().lower() for p in re.split(r"[,\n]", raw)]
    tags = [_clean_tag(p) for p in parts if p.strip()]
    tags = [t for t in tags if t]
    if not tags:
        raise BadInput("пустая тема — напиши хотя бы одно слово")
    return tags


def theme_forced(raw: str) -> set[str]:
    """Words typed with a leading '!' (2026-07-17, PLAN.md 0.2b — owner:
    «!слово... это обязательный показ именно этого слова в одной из строк
    если в базе есть это слово»). Unlike an ordinary theme word (0.2a: ranked
    up via meaning + capped literal occurrence, still probabilistic), a
    forced word gets a HARD guarantee — see core/filters.py: run()'s
    forced_notice. Never raises — an all-'!'-typo input just yields an empty
    set, theme()'s own validation is what still guards overall emptiness."""
    if not isinstance(raw, str):
        return set()
    out = set()
    for p in re.split(r"[,\n]", raw):
        p = p.strip().lower()
        if not p.startswith("!"):
            continue
        word = _clean_tag(p)
        if word:
            out.add(word)
    return out


def knobs(raw: dict | None) -> dict:
    """Sliders for unified mode: melody, cohesion, banality, real_text.
    Backward compatible with old names (explore, meter, banal, nl_mix).
    Missing keys fall back to defaults; out-of-range values are clamped.

    No "novelty"/λ knob anymore (removed 2026-07-14, owner: "всё что отвечает
    за алгоритмическую оценку предпочтений... убрать") — see
    core/filters.py's module docstring for what replaced it (nothing; ranking
    no longer reads accept/favorite history at all)."""
    raw = raw or {}

    def num(key: str, lo: float, hi: float, default: float, alias: str | None = None) -> float:
        # alias = the pre-unified-mode key name (explore, meter, banal,
        # nl_mix). Old callers only ever set the alias, never the new key —
        # reading raw.get(key, default) alone silently dropped every old-name
        # override to its default (found 2026-07-14 chasing a knobs-dict bug).
        source = key if key in raw else (alias if alias and alias in raw else key)
        try:
            v = float(raw.get(source, default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    def whole(key: str, lo: int, hi: int, default: int, alias: str | None = None) -> int:
        return int(num(key, lo, hi, default, alias))

    # New unified mode sliders; old-name aliases actually honored (see num())
    # Дефолты = измеренные средние владельца по 125 прогонам (stats.jsonl,
    # 2026-07-17) — зеркало DEFAULT_KNOBS в interface/react-app/src/App.jsx,
    # где лежит полное обоснование. Здесь это ФОЛБЭК для вызова без knobs;
    # UI всегда шлёт все ползунки явно. Держать в синхроне: два разных дефолта
    # для одного понятия — это второй источник правды.
    melody = num("melody", 0.0, 1.0, 0.35, "meter")       # rvaное → звучное
    cohesion = num("cohesion", 0.0, 1.0, 0.5, "explore")  # диссонанс → консонанс
    # 0.83 — прежнее положение владельца (0.35 по старой односторонней шкале)
    # в новых координатах: тот же потолок 4.875. Раунд 58, см. nlindex.Ворота.
    banality = num("banality", 0.0, 1.0, 0.83, "banal")  # 0 затёрто ↔ 1 нетронуто
    real_text = num("real_text", 0.0, 1.0, 0.9, "nl_mix") # extendo → nakedlunch

    # Map new sliders to old domain names for now (will gradually adapt internals)
    return {
        "explore": cohesion,                    # cohesion is the new explore
        "meter": melody,                        # melody includes meter
        "banal": banality,                      # banality as-is
        # Lower bound is 1, not the earlier 5: freestyle generates exactly ONE
        # scheme-length at a time (found 2026-07-14 — a 4-letter scheme like
        # "абаб" was silently padded to 5 lines by this floor). Upper bound
        # raised from 200: "количество строф" × scheme length can legitimately
        # exceed it (e.g. 30 abab stanzas = 120, fine, but a long custom
        # scheme × many stanzas can run past 200 too).
        "shortlist": whole("shortlist", 1, 400, 40),
        "nl_mix": real_text,                    # real_text is the new nl_mix
        "melody": melody,                       # store raw sliders too for future use
        "cohesion": cohesion,
        "banality": banality,
        "real_text": real_text,
        # 0.25 (2026-07-17) — ИЗМЕРЕННОЕ среднее владельца по 125 прогонам, не
        # догадка. Прежний дефолт 0.0 стоял по осторожной причине: ползунок был
        # МЁРТВ до 2026-07-14 (считался здесь, но filters.py его не читал), так
        # что все прежние сессии настраивались против точного совпадения, и
        # поставить тогда 0.5 значило бы молча размягчить выдачу за спиной
        # владельца. Та причина истекла: ползунок живой, владелец сам держит
        # его на 0.25 в среднем — теперь это факт из его поведения, а не
        # выбранное за него число. См. core/filters.py: _rhyme_prefix_len.
        "rhyme_precision": num("rhyme_precision", 0.0, 1.0, 0.25),
        # 0 = "алгоритм" (nakedlunch fragments still pass extendo's OWN
        # quality opinions — banality/tautology/dedup-vs-corpus — the
        # 2026-07-13 decision, unchanged default); 1 = "классика" (raw
        # nakedlunch text like the standalone ~/nakedlunch CLI gives you —
        # only the hard invariants survive: never-repeat and the owner's own
        # blacklist. Classic content also ignores the rhyme scheme entirely,
        # by the owner's own explicit choice 2026-07-14 — see
        # core/filters.py: _select_with_rhyme's classic handling). Proportion
        # between the two, not a blend — same "quota, not soft weight"
        # reasoning as real_text (core/filters.py stage 4b's own docstring).
        "classic": num("classic", 0.0, 1.0, 0.0),
        # Мат — ДОЛЯ, а не запрет (Раунд 39, владелец 2026-08-02: «допустимый
        # процент мата… желаемый процент мата, чтобы, если там стояло
        # восемьдесят, то восемьдесят обязательно с матом»). Раньше это был
        # булев тумблер «без мата»: он умел только вычёркивать, а попросить
        # мата было нечем.
        #   0    — мата нет вовсе (прежнее «без мата», тот же жёсткий фильтр);
        #   0.8  — восемь строк из десяти обязаны быть с матом;
        #   1    — все.
        # Сам фильтр живёт в core/filters.py: has_mat (по началу токена, ноль
        # ложных срабатываний) плюс раскладка долей по позициям строфы в
        # _select_with_rhyme. Дефолт 0 — прежнее поведение по умолчанию, и
        # мат остаётся явным выбором владельца, а не тихой добавкой.
        # −1 = «не задано»: клиент про мат ничего не сказал, и трогать его не
        # надо (прежнее поведение по умолчанию). Ноль — это уже ВЫБОР «без
        # мата», а не отсутствие выбора; разница видна в тестах, которые зовут
        # knobs({}) и ждут, что мат живёт как обычный текст.
        "mat_share": num("mat_share", -1.0, 1.0, -1.0),
        # Производное, а не вторая ручка: 0% мата — это ровно прежний жёсткий
        # фильтр, и он дешевле (отсекает в таблице, а не при отборе). Старый
        # булев ключ по-прежнему принимается: им пользуются тесты и прошлые
        # сохранённые настройки.
        "no_mat": bool(raw.get("no_mat", False)) or (0.0 <= num("mat_share", -1.0, 1.0, -1.0) <= 0.0005),
        # Симметрично «без мата», на другом конце шкалы (владелец 2026-08-03:
        # «максимальная крутилка берёт только мат и работает как антифильтр —
        # строки, где нет мата, она не показывает»). Это именно ВОРОТА, а не
        # предпочтение: на максимуме в пуле не остаётся ни одной строки без
        # мата, поэтому и рифмующийся партнёр гарантированно матерный. Первая
        # версия ставила долю мягким предпочтением при отборе — на максимуме
        # выходила одна матерная строка из четырёх, потому что мат сдаётся
        # раньше рифмы (и правильно делает).
        "only_mat": num("mat_share", -1.0, 1.0, -1.0) >= 0.9995,
        # Клаузула (Раунд 44) — тип окончания строки: 0 любая, 1 мужская,
        # 2 женская, 3 дактилическая. Замер референсов владельца: женская
        # 77/93/100% — самый устойчивый признак его поэтики, и до этого
        # раунда машина им не управляла. Ворота, а не предпочтение: рифмующая
        # пара обязана быть той же клаузулы, иначе рифмы просто не будет.
        "clausula": max(0, min(3, int(float(raw.get("clausula", 0) or 0)))),
        # Связность соседних строк (Раунд 44). −1 = не задано (прежнее
        # поведение). Иначе 0..1 — насколько соседние строки должны цепляться
        # друг за друга по смыслу. Замер референсов: 0.35 / 0.18 / 0.17 по
        # косинусу центроидов лемм, то есть даже «связный» текст владельца
        # держится втрое слабее единицы — поэтому шкала переводится в цель
        # 0..0.6, а не 0..1 (см. filters._FLOW_MAX).
        "flow": num("flow", -1.0, 1.0, -1.0),
        # ПОВТОР (Раунд 52) — 0 «не повторять» (прежнее поведение), 1 «можно».
        #
        # Владелец 2026-08-04: «хук — это такой тип строфы, он подразумевает
        # повтор и прочие механики. Значит хуки, хуковые припевы и хуковые
        # элементы механизм должен уметь делать. Это странно, что он борется с
        # повторяющимся — он не должен повторять только при соответствующих
        # настройках, но если я хочу повторять, пусть повторяет».
        #
        # Инвариант меняется с «никогда не повторять» на «повторять, когда
        # попросили». Ключ читают ДВА места, каждое в своей области:
        #   · filters._select_with_rhyme — барьер на повтор леммы ВНУТРИ
        #     строфы (крутилка звена: это свойство одной строфы);
        #   · pipeline._combo_score — штраф за общие леммы МЕЖДУ строфами
        #     (глобальные крутилки прогона: это свойство всей цепочки).
        # Целое, а не 0..1: промежуточного положения у «барьер стоит / барьера
        # нет» не существует, и рисовать дробный ползунок значило бы обещать
        # оттенки, которых в коде нет (та же ошибка, что была у «Мата» на
        # отрезке −1..0).
        #
        # Структурный повтор — тот самый «припев ещё раз» — это НЕ эта ручка,
        # а `repeat_of` у звена цепочки: он точный и виден глазами.
        "repeat": whole("repeat", 0, 1, 0),
    }


# --- профиль настроек (Раунд 50) -------------------------------------------
#
# ЗАЧЕМ. Владелец 2026-08-03: «можно делать строфы, и можно сделать профиль
# настроек, то есть как расположены крутилки. И то, и то можно ставить
# отдельно». До этого раунда каркас строфы и положения крутилок хранились
# ОДНИМ объектом (stanza_profiles.save с параметром `params`), и выбор формы
# молча двигал ползунки — то самое смешение, которое он и разделяет.
#
# Координаты ИНТЕРФЕЙСНЫЕ («Банальность», «Диссонанс»), а не ядерные
# (banality, cohesion): часть шкал инвертирована, и переводить туда-обратно
# при каждом чтении значит однажды ошибиться знаком. Та же причина, по
# которой settings.py держит `nl_params` отдельно от `knobs` — см. его
# комментарий.
#
# ДВЕ ГРУППЫ, и это не оформление, а свойство кода. «Классика»
# (nlindex.select_light) отключает все МНЕНИЯ о строке — банальность,
# тавтологию, клише, тему, метр, рифму, слоги, — но подчиняется ВОРОТАМ:
# какие книги в пуле, история показов, мат, клаузула. Поэтому профиль в
# режиме классики хранит только ворота, а мнения в нём не значат ничего.

# ключ → (низ, верх, дефолт, целое?). Единственный источник правды об именах
# и диапазонах крутилок; фронт зеркалит его в PARAM_DEFAULTS.
KNOB_GATES = {
    # 0 — генератор extendo, 1 — корпус nakedlunch. Режет пул, а не ранжир,
    # поэтому ворота. В КЛАССИКЕ неприменимо: классика по определению нарезка
    # корпуса, генератора в ней нет — см. KNOB_CLASSIC.
    "Источники": (0.0, 1.0, 1.0, False),
    # −1 «как есть» (мат живёт в строках как в корпусе) · 0 «без мата» (жёсткий
    # фильтр) · 0..1 доля строк, обязанных быть с матом · 1 «только мат».
    # ДЕФОЛТ −1, и это ПОЧИНКА: интерфейс по умолчанию слал 0, то есть молча
    # вырезал мат из каждой выдачи, хотя в референсах владельца его 17–21%
    # (refprofile, Раунд 44). Ядро всегда считало дефолтом −1 — расходились
    # именно две стороны, и проигрывала та, что ближе к владельцу.
    # Промежуток (−1, 0) смысла не имеет: интерфейс защёлкивает его к ближнему
    # из двух названных концов, см. render.panels.jsx.
    "Мат": (-1.0, 1.0, -1.0, False),
    # 0 любая · 1 мужская · 2 женская · 3 дактилическая
    "Клаузула": (0, 3, 0, True),
}

KNOB_OPINIONS = {
    "Точность рифм": (0.0, 1.0, 0.25, False),   # 0 точные · 1 ассонанс
    "Мелодичность": (0.0, 1.0, 0.35, False),    # 0 рваное · 1 звучное
    # ДВУСТОРОННЯЯ (Раунд 58, владелец): 0 — язык максимально затёртый
    # (ходовые слова, готовые обороты), 0.5 — ручка не влияет, 1 — нетронутый
    # (редкие слова, ни одного заезженного сочетания). Шкала
    # интерфейса теперь ПРЯМАЯ: ядро понимает её так же (см. nlindex.Ворота).
    # Дефолт 0.83 — это ПРЕЖНЕЕ поведение владельца, пересчитанное в новую
    # шкалу: его 0.35 по старой означал потолок 4.875, а по новой тот же
    # потолок даёт 0.83. Не новое предпочтение, а то же самое другими словами.
    "Банальность": (0.0, 1.0, 0.83, False),
    "Диссонанс": (0.0, 1.0, 0.7, False),        # у ядра cohesion = 1 − это
    # −1 «не задано», иначе 0..1 — насколько соседние строки цепляются по
    # смыслу. Мнение, а не ворота: прибавка к рангу в filters.scan_for, и
    # nlindex.select_light её не принимает вовсе.
    "Связность": (-1.0, 1.0, -1.0, False),
    # 0 «не повторять» · 1 «можно повторять» (Раунд 52, хук). Целое: см.
    # разбор у ключа "repeat" в knobs().
    "Повтор": (0, 1, 0, True),
}

KNOB_SPEC = {**KNOB_GATES, **KNOB_OPINIONS}

# Что ПЕРЕЖИВАЕТ классику. Не «ворота минус что-то», а свой короткий список,
# потому что «Источники» — ворота, но в классике неприменимы: классика это
# нарезка корпуса, генератора extendo в ней нет по определению режима
# (filters._run_classic пришпиливает real_text к 1). Показывать ручку, у
# которой в этом режиме нет смысла, — то же враньё, что показывать мнения.
KNOB_CLASSIC = ("Мат", "Клаузула")

# Режимы отбора. Бинарно (Раунд 50, владелец: «я бы сделал переключатель,
# бинарный: алгоритм — классика, то есть либо одно, либо другое»). Прежняя
# плавная доля 0..1 умела смешивать два пула в одной строфе; ради этого жили
# classic_quota и раскладка классических строк по позициям — механика без
# спроса, которую невозможно было услышать.
MODE_ALGO, MODE_CLASSIC = "алгоритм", "классика"
KNOB_MODES = (MODE_ALGO, MODE_CLASSIC)


def knob_params(raw) -> dict:
    """Положения крутилок в координатах интерфейса. Мусор клампится, чужие
    ключи отбрасываются, недостающие берут дефолт — профиль всегда полный,
    чтобы «в нём не было половины» не превратилось в тихий разнобой между
    двумя звеньями цепочки."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for key, (lo, hi, dflt, целое) in KNOB_SPEC.items():
        try:
            v = float(raw[key])
        except (KeyError, TypeError, ValueError):
            v = dflt
        if v != v:                       # nan
            v = dflt
        v = max(lo, min(hi, v))
        out[key] = int(round(v)) if целое else v
    return out


def knob_profile(raw) -> dict | None:
    """Именованный профиль настроек: {name, mode, params}. None — «это не
    профиль» (нет имени): молча пропустить битую запись честнее, чем уронить
    весь список профилей из-за одной строки в файле, который владелец может
    открыть и поправить руками."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()[:64]
    if not name:
        return None
    mode = raw.get("mode")
    mode = mode if mode in KNOB_MODES else MODE_ALGO
    params = knob_params(raw.get("params"))
    # В классике мнения не действуют — и не хранятся: иначе профиль обещал бы
    # глазами то, чего не делает (владелец: «всё, что не работает, лучше
    # убрать вовсе»). Остаётся только то, чему классика подчиняется.
    if mode == MODE_CLASSIC:
        params = {k: v for k, v in params.items() if k in KNOB_CLASSIC}
    return {"name": name, "mode": mode, "params": params}


def knobs_from_profile(profile: dict | None) -> dict:
    """Профиль настроек → knobs ядра. ЕДИНСТВЕННОЕ место перевода интерфейсных
    координат в ядерные: инверсии («Банальность», «Диссонанс») живут здесь и
    больше нигде. Раньше тот же перевод дублировался на фронте (genKnobs) и в
    methods.panels.js (paramKnobs) — два места, где можно перепутать знак, и
    они уже расходились."""
    prof = knob_profile(profile) or {"mode": MODE_ALGO, "params": knob_params(None)}
    p = knob_params(prof["params"])       # классика хранит не всё — добьём дефолтами
    классика = prof["mode"] == MODE_CLASSIC
    return knobs({
        # В классике источник один — корпус: генератора extendo в режиме нет
        # по определению. Пришпиливаем здесь, а не полагаемся на дефолт: иначе
        # «Источники 0 + классика» дала бы пустую выдачу без единого признака,
        # почему (карта Раунда 50 поймала это как молчаливую ловушку).
        "real_text": 1.0 if классика else p["Источники"],
        "classic": 1.0 if классика else 0.0,
        "mat_share": p["Мат"],
        "clausula": p["Клаузула"],
        "flow": p["Связность"],
        "rhyme_precision": p["Точность рифм"],
        "melody": p["Мелодичность"],
        # ПРЯМО, БЕЗ ИНВЕРСИИ (Раунд 58): шкалы совпали, у обеих 0 — банально,
        # 1 — свежо, 0.5 — нейтраль.
        "banality": p["Банальность"],
        "cohesion": 1.0 - p["Диссонанс"],     # у ядра консонанс, у ползунка диссонанс
        "repeat": p["Повтор"],
    })


# --- полка цепочек: СЛЕПОК, а не ссылки (Раунд 50) -------------------------
#
# Владелец 2026-08-03 хотел «одним нажатием сразу выбирать конкретное готовое
# решение». Ссылка на полку это обещание нарушает: подкрутил профиль ради
# одной строфы — и сохранённое решение молча зазвучало иначе. Поэтому звено
# цепочки хранит КОПИИ каркаса и крутилок, а имя формы — только подписью.
#
# Референс — часть слепка, включая ПУСТОЙ. Без этого восстановление цепочки
# оставляло на экране чужой текст референса, а одно случайное касание ползунка
# референтности молча переразмечало её по нему: applyRef перезаписывает всю
# цепочку целиком, без отката и без единого сообщения.

_CHAIN_LINKS_MAX = 12


def chain_link(raw, index: int = 0) -> dict | None:
    """Одно звено слепка. None — звено без каркаса: восстанавливать нечего, и
    молча подставить «какую-нибудь» строфу значит спорить с владельцем.

    Исключение — звено-повтор (`repeat_of`, хук Раунда 52): своего каркаса у
    него нет по определению, он берёт его у двойника. Требовать спеку значило
    бы терять припевы при каждом сохранении цепочки."""
    if not isinstance(raw, dict):
        return None
    repeat_of = raw.get("repeat_of")
    if repeat_of is not None:
        try:
            repeat_of = int(repeat_of)
        except (TypeError, ValueError):
            return None
        if not 0 <= repeat_of < index:      # только назад — вперёд это цикл
            return None
    spec = stanza_spec(raw.get("spec"))
    if not spec and repeat_of is None:
        return None
    return {
        "title": str(raw.get("title") or "").strip()[:48],
        "form": str(raw.get("form") or "").strip()[:64],   # подпись, не источник правды
        "spec": spec or [],
        "repeat_of": repeat_of,
        "knobs_profile": str(raw.get("knobs_profile") or "").strip()[:64],
        "params": knob_params(raw.get("params")),
        "mode": raw.get("mode") if raw.get("mode") in KNOB_MODES else MODE_ALGO,
    }


def chain_profile(raw) -> dict | None:
    """Сохранённая цепочка целиком. None — не цепочка (нет имени или нет ни
    одного живого звена)."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()[:64]
    if not name:
        return None
    # Индекс передаём: звено-повтор обязано указывать НАЗАД, и проверить это
    # можно только зная, сколько звеньев уже принято. Битое звено выпадает —
    # значит следующие сдвигаются, поэтому индекс берётся от принятых, а не от
    # позиции в сыром списке.
    links = []
    for сырое in (raw.get("links") or []):
        звено = chain_link(сырое, len(links))
        if звено:
            links.append(звено)
    if not links:
        return None
    links = links[:_CHAIN_LINKS_MAX]
    n = len(links) - 1
    junc = [(j if j in JUNCTION_KINDS else JUNCTION_KINDS[0])
            for j in (raw.get("junctions") or [])[:n]]
    junc += [JUNCTION_KINDS[0]] * (n - len(junc))
    ref = raw.get("reference") if isinstance(raw.get("reference"), dict) else {}
    try:
        pct = float(ref.get("pct", 1.0))
    except (TypeError, ValueError):
        pct = 1.0
    return {
        "name": name, "links": links, "junctions": junc,
        # пустой текст — полноценное значение: «собрано руками»
        "reference": {"text": str(ref.get("text") or ""), "pct": max(0.0, min(1.0, pct))},
    }


# --- полка СЕРИЙ: четвёртый уровень (Раунд 53) -----------------------------
#
# Владелец 2026-08-04: «это по сути череда прогонов, штука ещё более
# высокоуровневая: строфа самое низкое, потом пайплайн-прогон, потом вот это».
#
# Отсюда вся модель — она повторяет ту, что уровнем ниже:
#   строфа   = буквы рифмовки + вилки слогов          → одна строфа
#   цепочка  = строфа с полки + профиль настроек      → один текст
#   СЕРИЯ    = альбом + тема + цепочка с полки + сколько → папки с материалом
#
# Имя цепочки хранится ПОДПИСЬЮ и не проверяется здесь на существование —
# ровно как имя формы строфы в звене цепочки. Полка цепочек живёт отдельно, и
# требовать её при сохранении серии значило бы, что серию нельзя написать
# раньше цепочки. Отсутствующая цепочка — честная ошибка ПРОГОНА, с именем.

# ПРЕДЕЛОВ ЗДЕСЬ НЕТ, и это решение. Владелец 2026-08-04: «зачем вообще
# предел, убери». Он прав: любое число, которое я бы здесь поставил, было бы
# выдумано мной и запрещало бы ЕГО замыслы — сначала 64 звена молча резали
# «10 альбомов по 10 треков», потом 200 запрещали бы двадцать альбомов.
#
# Настоящий ограничитель у серии один и он честный — ВРЕМЯ: 15 секунд на текст
# (core/series.py: estimate). Оно считается и показывается до запуска, и в него
# упирается любой размах, без всяких выдуманных потолков.


def series_link(raw) -> dict | None:
    """Звено серии: {album, theme, chain, count}. None — звено без цепочки:
    гнать нечего, а подставить «какую-нибудь» значит собрать не то."""
    if not isinstance(raw, dict):
        return None
    chain = str(raw.get("chain") or "").strip()[:64]
    if not chain:
        return None
    # Альбом — имя ПАПКИ. Правила те же, что у core/sheets.py: без «/», без
    # точки в начале. Проверяем ЗДЕСЬ, а не при раскладке: иначе кривое имя
    # обнаружилось бы среди ночи, на середине прогона.
    album = str(raw.get("album") or "").strip()[:48]
    if "/" in album or album.startswith("."):
        raise BadInput("имя альбома не может содержать «/» и начинаться с точки")
    # Число претендентов не ограничено сверху — см. решение о пределах выше.
    # Снизу единица: звено, которое не даёт ни одного текста, владелец потом
    # искал бы глазами в папках, а его там просто нет.
    try:
        count = int(float(raw.get("count", 10)))
    except (TypeError, ValueError):
        count = 10
    return {
        "album": album,
        # Тема НЕОБЯЗАТЕЛЬНА: прогон без темы — обычное дело. Пустую сюда и
        # пропускаем, а непустую разбирает уже пайплайн (theme/theme_forced) —
        # второй разбор здесь дал бы второе мнение о том, что такое тема.
        "theme": str(raw.get("theme") or "").strip()[:120],
        "chain": chain,
        "count": max(1, count),
    }


def series(raw) -> dict | None:
    """Серия целиком. None — не серия (нет имени или ни одного живого звена)."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()[:64]
    if not name:
        return None
    links = [l for l in (series_link(x) for x in (raw.get("links") or [])) if l]
    if not links:
        return None
    # ИСКАЖЕНИЕ (Раунд 55) — свойство ВСЕЙ серии, а не трека: ось кривой это
    # место в серии, и лежать оно может только здесь. Разбор — в core/distort.py,
    # своих правил тут нет: ключ проходит один валидатор, а не два (на двух
    # белых списках проект уже обжигался дважды).
    out = {"name": name, "links": links}
    крив = distort.кривая(raw.get("curve"))
    if крив:
        out["curve"] = крив
    try:
        шум = float(raw.get("noise") or 0.0)
    except (TypeError, ValueError):
        шум = 0.0
    if шум > 0:
        out["noise"] = round(max(0.0, min(1.0, шум)), 3)
        тип = str(raw.get("noise_kind") or "")
        out["noise_kind"] = тип if тип in distort.ШУМЫ else distort.ШУМЫ[0]
    return out


# --- пайплайн (ФАЗА 1, PLAN.md: пулы по звеньям + комбинаторная склейка) ---

# Канонические типы стыков — единственный источник правды и для валидации
# здесь, и для оценки склейки в core/pipeline.py (он импортирует clean).
# Первый — дефолт: рифмованный стык и есть то, ради чего пайплайн затевался.
JUNCTION_KINDS = ("рифмовать стык", "свободно", "слом ритма")

_PIPE_CHAIN_MAX = 12


def pipeline_spec(raw) -> dict:
    """Валидатор POST /api/pipeline/run — весь контракт в одном месте (§6).
    Мусор в числах КЛАМПИТСЯ в диапазон (стиль knobs(): кривое значение —
    не повод ронять прогон), структурный мусор (нет цепочки, звено без
    роли, несуществующая длина) — честный BadInput одной фразой (§7).
    Тема разбирается СРАЗУ (tags/forced), чтобы «пустая тема из мусора»
    падала 400-й ДО захвата замка и постройки пулов."""
    if not isinstance(raw, dict):
        raise BadInput("запрос пайплайна должен быть объектом")

    theme_raw = raw.get("theme", "")
    if not isinstance(theme_raw, str):
        raise BadInput("тема должна быть строкой")
    theme_raw = theme_raw.strip()
    tags: list[str] = []
    forced: set[str] = set()
    if theme_raw:
        tags = theme(theme_raw)            # мусорная непустая тема — BadInput
        forced = theme_forced(theme_raw)   # '!слово' — жёсткая гарантия

    chain_raw = raw.get("chain")
    if not isinstance(chain_raw, list) or not 1 <= len(chain_raw) <= _PIPE_CHAIN_MAX:
        raise BadInput(f"цепочка — список из 1..{_PIPE_CHAIN_MAX} звеньев")
    chain = []
    for item in chain_raw:
        if not isinstance(item, dict):
            raise BadInput("звено цепочки должно быть объектом")
        # Заголовок секции — НЕОБЯЗАТЕЛЬНАЯ пометка для документа (Раунд 50).
        # Раньше здесь была обязательная `role`, и по ней бэк втихую выбирал
        # и форму строфы, и сдвиги крутилок — при том что интерфейс подписывал
        # её «на генерацию не влияет». Теперь это правда: на генерацию влияют
        # только spec и knobs звена. Старое имя ключа принимается, чтобы
        # сохранённая раньше цепочка не отвалилась молча.
        title = str(item.get("title") or item.get("role") or "").strip()[:48]
        form = item.get("form")
        form = form.strip() if isinstance(form, str) and form.strip() else None
        # Звено приносит СВОЙ каркас (снятый с референса) и СВОИ крутилки
        # (профиль настроек). Абсолютные значения, а не дельты: «в припеве
        # связность 0.4» понятнее, чем «+0.1 к тому, что стоит глобально», —
        # и не зависит от того, что стоит глобально.
        spec = stanza_spec(item.get("spec")) if item.get("spec") else None
        # Крутилки звена приезжают в КООРДИНАТАХ ИНТЕРФЕЙСА — {mode, params},
        # и переводит их здесь единственный переводчик (Раунд 51).
        #
        # Раньше поле называлось `knobs` и в него писали ДВА производителя в
        # ДВУХ несовместимых системах: референс клал ядерные имена
        # (clausula/flow/mat_share), а восстановление слепка цепочки — русские
        # («Клаузула», «Мат»). Русские ключи `knobs()` не знает, и звено молча
        # получало полный набор ДЕФОЛТОВ, которые вдобавок перебивали
        # глобальные настройки прогона. То есть восстановленная цепочка
        # генерила не тем, что в ней записано, и без единого признака.
        own = {}
        if isinstance(item.get("params"), dict) or item.get("mode"):
            own = knobs_from_profile({"name": "звено", "mode": item.get("mode"),
                                      "params": item.get("params")})
        elif isinstance(item.get("knobs"), dict):
            # старый формат (ядерные имена) — принимаем, чтобы сохранённая
            # раньше цепочка не отвалилась молча
            own = knobs(item["knobs"])
        # ХУК (Раунд 52): звено-повтор указывает НАЗАД на уже описанное звено.
        # Только назад — вперёд или на себя это цикл, а цикл здесь не «странное
        # значение, которое можно поджать», а неразрешимая ссылка: подставить
        # вместо неё ноль значило бы молча собрать не ту песню.
        repeat_of = item.get("repeat_of")
        if repeat_of is not None:
            try:
                repeat_of = int(repeat_of)
            except (TypeError, ValueError):
                raise BadInput("повтор звена — номер более раннего звена")
            if not 0 <= repeat_of < len(chain):
                raise BadInput(f"звено {len(chain) + 1} повторяет звено "
                               f"{repeat_of + 1}, а такого раньше него нет")
        chain.append({"title": title, "form": form, "spec": spec, "knobs_own": own,
                      "repeat_of": repeat_of})

    # Стыков всегда ровно звеньев−1: лишние отрезаются, недостающие и любое
    # неканоническое значение добиваются дефолтом ('рифмовать стык').
    n_junctions = len(chain) - 1
    junctions_raw = raw.get("junctions") if isinstance(raw.get("junctions"), list) else []
    junctions = [(j if j in JUNCTION_KINDS else JUNCTION_KINDS[0])
                 for j in junctions_raw[:n_junctions]]
    junctions += [JUNCTION_KINDS[0]] * (n_junctions - len(junctions))

    cleaned_knobs = knobs(raw.get("knobs"))

    def whole(key: str, lo: int, hi: int, default: int) -> int:
        try:
            v = int(float(raw.get(key, default)))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    # ЧЕГО ЗДЕСЬ БОЛЬШЕ НЕТ (Раунд 50), и почему.
    #
    # `variety` — вес MMR-отбора между вариантами склейки. Вариант всегда один
    #   (Раунд 48, владелец: «пусть всегда будет 1 вариант без 10 вариаций»),
    #   значит выбирать не из чего и разнообразию нечего разнообразить.
    # `threshold` — порог отсева комбо. Фронт его не слал ни разу, дефолт 0.0
    #   не отсекал ничего, а сохранённые профили несли 0.35, который в первом
    #   же живом прогоне резал выдачу почти в ноль.
    # `weights` — три веса склейки. Владелец 2026-08-03: «всё, что если
    #   трогать будет хуже, лучше убрать». Качество и стыки нужны всегда
    #   максимальные, а сдвиг «избегать повторов» вверх начинает выкидывать
    #   хорошие строфы за одно общее слово. Пропорция вернулась в константы
    #   модуля core/pipeline.py, где ей и место.

    return {
        "theme": theme_raw, "tags": tags, "forced": forced,
        "chain": chain, "junctions": junctions,
        "knobs": cleaned_knobs,
        "runs": whole("runs", 100, 200000, 5000),
        "best": whole("best", 1, 50, 1),
        "pool_per_link": whole("pool_per_link", 10, 120, 50),
    }


def favorite(raw: dict | None) -> str:
    """Add a line to favorites — the only verb left for a shown line (2026-07-14:
    reject removed, "минус... бессмысленна" — nothing needs a negative verdict
    once every shown line already lands in reversible history on its own,
    see corpus.py). Returns the text to favorite."""
    raw = raw or {}
    text = (raw.get("text") or "").strip()
    if not text:
        raise BadInput("нечего добавлять в избранное — пустая строка")
    return text
