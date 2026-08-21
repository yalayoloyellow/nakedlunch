# extendo — the single validation layer (PRINCIPLES §6: one source of truth).
# Everything that enters the domain — a theme string, a run request, a line the
# user marks — passes through here first. Bad input fails fast with ONE human
# sentence (PRINCIPLES §7), never a half-built object and never a traceback.

from __future__ import annotations

import re


class BadInput(ValueError):
    """Raised with a single human-readable sentence. The caller prints str(e)."""


_THEME_RE = re.compile(r"[^\wёЁа-яА-Я\s,\-]", re.UNICODE)
_SCHEME_RE = re.compile(r"^[а-яё]{2,16}$")
_SCHEME_JUNK_RE = re.compile(r"[^а-яёa-z0-9]")
_SCHEME_CYRILLIC_RE = re.compile(r"^[а-яё]+$")
_SCHEME_ALPHABET = "абвгдежзийклмнопрстуфхцчшщъыьэюя"


def rhyme_scheme(raw) -> str:
    """A rhyme scheme is "none" or 2-16 lowercase Cyrillic letters — a preset
    (абаб) or the user's own (абвабгабд). core/filters.py groups POSITIONS
    by matching letter, so any string in this shape is already meaningful;
    the only real validation is the shape, not membership in a fixed list.

    Латиница и цифры принимаются наравне с кириллицей (2026-07-17, PLAN.md 0.6:
    требование: схему можно прописывать цифрами и латиницей). Раньше любой
    не-кириллический символ проваливал `_SCHEME_RE` и схема МОЛЧА становилась
    "none" — набрал `aabb`, получил отсутствие рифмовки без единого слова.
    Нормализуем по ПАТТЕРНУ, а не по алфавиту: смысл схемы — какие позиции
    совпадают, а не какими буквами записаны, поэтому aabb ≡ 1122 ≡ аабб
    (первый встреченный символ → «а», второй → «б», …). Чистая кириллица
    возвращается КАК НАБРАНА — старое поведение не трогаем, только добавляем
    новые алфавиты (иначе «баба» превратилось бы в «абаб» и поле бы спорило с
    пользователем). Зеркалится в interface/react-app/src/App.jsx: normalizeScheme.
    """
    if not isinstance(raw, str) or raw == "none" or not raw:
        return "none"
    s = _SCHEME_JUNK_RE.sub("", raw.strip().lower())[:16]
    if not _SCHEME_CYRILLIC_RE.match(s):
        mapping: dict[str, str] = {}
        # 16 символов максимум → различных не больше 16, алфавита из 32 хватает всегда
        s = "".join(mapping.setdefault(ch, _SCHEME_ALPHABET[len(mapping)]) for ch in s)
    return s if _SCHEME_RE.match(s) else "none"


def семя(raw) -> int | None:
    """Номер прогона из запроса: целое 0..2³⁰−1, либо None — «сними новое».

    МУСОР ЗДЕСЬ — ЭТО None, А НЕ ОШИБКА. Семя нужно, чтобы ПОВТОРИТЬ выдачу;
    ронять из-за испорченного номера самое частое действие приложения значило
    бы ломать основное ради вспомогательного. Испорченный номер честно
    превращается в новый прогон, и ответ говорит, какой номер снялся на самом
    деле (filters.run → result["seed"]).

    Дробное принимается и урезается: JSON шлёт числа числами, и 12.0 — то же
    самое двенадцать. `bool` отсекается отдельно — в Python True это 1, и
    `{"seed": true}` иначе молча стал бы прогоном номер один."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(float(raw)) % (1 << 30)
    except (TypeError, ValueError, OverflowError):
        return None


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
    user's explicit call: "рифма важнее" when the two conflict).

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
    """Words typed with a leading '!' (2026-07-17, PLAN.md 0.2b — user:
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
    """Sliders for unified mode: cohesion, real_text (melody и banality
    удалены — см. надгробия ниже). Backward compatible with old names
    (explore, nl_mix).
    Missing keys fall back to defaults; out-of-range values are clamped.

    No "novelty"/λ knob anymore (removed 2026-07-14, user: "всё что отвечает
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
    # Дефолты = измеренные средние пользователя по 125 прогонам (stats.jsonl,
    # 2026-07-17) — зеркало DEFAULT_KNOBS в interface/react-app/src/App.jsx,
    # где лежит полное обоснование. Здесь это ФОЛБЭК для вызова без knobs;
    # UI всегда шлёт все ползунки явно. Держать в синхроне: два разных дефолта
    # для одного понятия — это второй источник правды.
    # НАДГРОБИЕ: `melody` (алиас `meter`) УДАЛЁН 2026-08-21 — ручка
    # «Мелодичность» снесена целиком по двум замерам, разбор в надгробии
    # core/filters.py у МЕТР_ПОРОГ. Профили со старым ключом читаются.
    cohesion = num("cohesion", 0.0, 1.0, 0.5, "explore")  # диссонанс → консонанс
    # НАДГРОБИЕ: `banality` (алиас `banal`) УДАЛЁН 2026-08-20 — ручка снесена
    # целиком по замеру, разбор в надгробии core/nlindex.py. Старые настройки и
    # профили с этим ключом читаются как раньше: неизвестные ключи здесь просто
    # не спрашиваются, а `raw` не проверяется на лишнее.
    real_text = num("real_text", 0.0, 1.0, 0.9, "nl_mix") # extendo → nakedlunch

    # Map new sliders to old domain names for now (will gradually adapt internals)
    return {
        "explore": cohesion,                    # cohesion is the new explore
        # Lower bound is 1, not the earlier 5: freestyle generates exactly ONE
        # scheme-length at a time (found 2026-07-14 — a 4-letter scheme like
        # "абаб" was silently padded to 5 lines by this floor). Upper bound
        # raised from 200: "количество строф" × scheme length can legitimately
        # exceed it (e.g. 30 abab stanzas = 120, fine, but a long custom
        # scheme × many stanzas can run past 200 too).
        "shortlist": whole("shortlist", 1, 400, 40),
        "nl_mix": real_text,                    # real_text is the new nl_mix
        "cohesion": cohesion,
        "real_text": real_text,
        # 0.25 (2026-07-17) — ИЗМЕРЕННОЕ среднее пользователя по 125 прогонам, не
        # догадка. Прежний дефолт 0.0 стоял по осторожной причине: ползунок был
        # МЁРТВ до 2026-07-14 (считался здесь, но filters.py его не читал), так
        # что все прежние сессии настраивались против точного совпадения, и
        # поставить тогда 0.5 значило бы молча размягчить выдачу за спиной
        # пользователя. Та причина истекла: ползунок живой, пользователь сам держит
        # его на 0.25 в среднем — теперь это факт из его поведения, а не
        # выбранное за него число. См. core/filters.py: _rhyme_prefix_len.
        "rhyme_precision": num("rhyme_precision", 0.0, 1.0, 0.25),
        # 0 = "алгоритм" (nakedlunch fragments still pass extendo's OWN
        # quality opinions — banality/tautology/dedup-vs-corpus — the
        # 2026-07-13 decision, unchanged default); 1 = "классика" (raw
        # nakedlunch text like the standalone ~/nakedlunch CLI gives you —
        # only the hard invariants survive: never-repeat and the user's own
        # blacklist. Classic content also ignores the rhyme scheme entirely,
        # by the user's own explicit choice 2026-07-14 — see
        # core/filters.py: _select_with_rhyme's classic handling). Proportion
        # between the two, not a blend — same "quota, not soft weight"
        # reasoning as real_text (core/filters.py stage 4b's own docstring).
        "classic": num("classic", 0.0, 1.0, 0.0),
        # Мат — ДОЛЯ, а не запрет (Раунд 39, требование (2026-08-02): задавать желаемый процент мата — при восьмидесяти
        # восемьдесят процентов строк обязаны быть с матом). Раньше это был
        # булев тумблер «без мата»: он умел только вычёркивать, а попросить
        # мата было нечем.
        #   0    — мата нет вовсе (прежнее «без мата», тот же жёсткий фильтр);
        #   0.8  — восемь строк из десяти обязаны быть с матом;
        #   1    — все.
        # Сам фильтр живёт в core/filters.py: has_mat (по началу токена, ноль
        # ложных срабатываний) плюс раскладка долей по позициям строфы в
        # _select_with_rhyme. Дефолт 0 — прежнее поведение по умолчанию, и
        # мат остаётся явным выбором пользователя, а не тихой добавкой.
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
        # Симметрично «без мата», на другом конце шкалы (требование (2026-08-03): крайнее положение работает антифильтром — строки без мата
        # не показываются.). Это именно ВОРОТА, а не
        # предпочтение: на максимуме в пуле не остаётся ни одной строки без
        # мата, поэтому и рифмующийся партнёр гарантированно матерный. Первая
        # версия ставила долю мягким предпочтением при отборе — на максимуме
        # выходила одна матерная строка из четырёх, потому что мат сдаётся
        # раньше рифмы (и правильно делает).
        "only_mat": num("mat_share", -1.0, 1.0, -1.0) >= 0.9995,
        # Клаузула (Раунд 44) — тип окончания строки: 0 любая, 1 мужская,
        # 2 женская, 3 дактилическая. Замер референсов пользователя: женская
        # 77/93/100% — самый устойчивый признак его поэтики, и до этого
        # раунда машина им не управляла. Ворота, а не предпочтение: рифмующая
        # пара обязана быть той же клаузулы, иначе рифмы просто не будет.
        "clausula": max(0, min(3, int(float(raw.get("clausula", 0) or 0)))),
        # Связность соседних строк (Раунд 44). −1 = не задано (прежнее
        # поведение). Иначе 0..1 — насколько соседние строки должны цепляться
        # друг за друга по смыслу. Замер референсов: 0.35 / 0.18 / 0.17 по
        # косинусу центроидов лемм, то есть даже «связный» текст пользователя
        # держится втрое слабее единицы — поэтому шкала переводится в цель
        # 0..0.6, а не 0..1 (см. filters._FLOW_MAX).
        "flow": num("flow", -1.0, 1.0, -1.0),
        # ПОВТОР (Раунд 52) — 0 «не повторять» (прежнее поведение), 1 «можно».
        #
        # Требование (2026-08-04): хук — тип строфы, подразумевающий повтор; механизм обязан
        # уметь хуки и хуковые припевы, а не бороться с повтором..
        #
        # Инвариант меняется с «никогда не повторять» на «повторять, когда
        # попросили». Читает ключ одно место: filters._select_with_rhyme —
        # барьер на повтор леммы ВНУТРИ строфы.
        #
        # Второй читатель был, и его больше нет: `pipeline._combo_score`
        # штрафовал общие леммы МЕЖДУ строфами цепи. Цепь вырезана 2026-08-18
        # (29 прогонов против 587 одиночных строф за 10 дней), и ручка стала
        # ровно тем, чем была по смыслу, — свойством ОДНОЙ строфы.
        #
        # Целое, а не 0..1: промежуточного положения у «барьер стоит / барьера
        # нет» не существует, и рисовать дробный ползунок значило бы обещать
        # оттенки, которых в коде нет (та же ошибка, что была у «Мата» на
        # отрезке −1..0).
        "repeat": whole("repeat", 0, 1, 0),
    }


# --- профиль настроек (Раунд 50) -------------------------------------------
#
# ЗАЧЕМ. требование (2026-08-03): каркас строфы и профиль настроек ставятся раздельно.. До этого раунда каркас строфы и положения крутилок хранились
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
    # вырезал мат из каждой выдачи, хотя в референсах пользователя его 17–21%
    # (замер Раунда 44; сам измеритель референса, core/refprofile.py, вырезан
    # 2026-08-18 вместе с цепью — число осталось, машинки больше нет).
    # Ядро всегда считало дефолтом −1 — расходились
    # именно две стороны, и проигрывала та, что ближе к пользователю.
    # Промежуток (−1, 0) смысла не имеет: интерфейс защёлкивает его к ближнему
    # из двух названных концов, см. render.panels.jsx.
    "Мат": (-1.0, 1.0, -1.0, False),
    # 0 любая · 1 мужская · 2 женская · 3 дактилическая
    "Клаузула": (0, 3, 0, True),
}

KNOB_OPINIONS = {
    "Точность рифм": (0.0, 1.0, 0.25, False),   # 0 точные · 1 ассонанс
    # НАДГРОБИЕ: «Мелодичность» (0.0, 1.0, 0.35) УДАЛЕНА 2026-08-21. Метр на
    # прозе не считается ПО ПОСТРОЕНИЮ (у строк корпуса meter=None — реальный
    # текст никто не писал под долю), то есть ручка была мертва на 89%
    # прогонов. Замена «через звучность» ОТВЕРГНУТА замером по его же
    # избранному — разбор в core/filters.py у МЕТР_ПОРОГ.
    # НАДГРОБИЕ: «Банальность» (0.0, 1.0, 0.83) УДАЛЕНА 2026-08-20. Ручка
    # обещала износ языка, а мерила частоту самого редкого СЛОВА; замена
    # офлайн недостижима, а рабочее положение у неё было ровно одно, и даже оно
    # убивало живую строку на 1.7 снятых. Полный разбор — надгробие в
    # core/nlindex.py. Профили со старым ключом читаются: `knobs_from_profile`
    # берёт ключи по одному, лишние в `params` не мешают.
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

# Режимы отбора. Бинарно (Раунд 50, требование: бинарный переключатель «алгоритм — классика», либо одно, либо другое.). Прежняя
# плавная доля 0..1 умела смешивать два пула в одной строфе; ради этого жили
# classic_quota и раскладка классических строк по позициям — механика без
# спроса, которую невозможно было услышать.
MODE_ALGO, MODE_CLASSIC = "алгоритм", "классика"
KNOB_MODES = (MODE_ALGO, MODE_CLASSIC)


def knob_params(raw) -> dict:
    """Положения крутилок в координатах интерфейса. Мусор клампится, чужие
    ключи отбрасываются, недостающие берут дефолт — профиль всегда полный,
    чтобы «в нём не было половины» не превратилось в тихий разнобой между
    двумя прогонами."""
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
    весь список профилей из-за одной строки в файле, который пользователь может
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
    # глазами то, чего не делает (требование: то, что не работает, лучше убрать вовсе.). Остаётся только то, чему классика подчиняется.
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
        # `"melody": p["Мелодичность"]` снято 2026-08-21 вместе с ручкой.
        # `"banality": p["Банальность"]` снято 2026-08-20 вместе с ручкой.
        "cohesion": 1.0 - p["Диссонанс"],     # у ядра консонанс, у ползунка диссонанс
        "repeat": p["Повтор"],
    })


# НАДГРОБИЕ 2026-08-18: ЦЕПОЧКА, СЕРИЯ И КОНТРАКТ ПАЙПЛАЙНА ВЫРЕЗАНЫ --------
#
# Отсюда ушли: `chain_link`/`chain_profile` с `_CHAIN_LINKS_MAX` (слепок полки
# цепочек), `series_link`/`series` (полка серий вместе с разбором кривой и шума
# искажения), `pipeline_spec` с `JUNCTION_KINDS` и `_PIPE_CHAIN_MAX` (весь
# контракт POST /api/pipeline/run), и импорт `distort`.
#
# Основание — замер журнала событий за 10 живых дней: 29 прогонов цепи против
# 587 одиночных строф (1 к 20), медиана цепи 24.2 с, девяностый процентиль
# 98.7 с. Серия в журнал не писалась вовсе, числа по ней нет: её убрал сам
# владелец решением от 2026-08-18 («строфа единственным режимом»), и это его
# решение, а не замер.
#
# ЧТО ОСТАЛОСЬ И ПОЧЕМУ. `stanza_spec`, `knobs`, `knobs_from_profile`,
# `knob_profile`, `knob_params`, `theme`/`theme_forced` — это контракт САМОЙ
# строфы, единственного оставшегося режима, и цепь ими только пользовалась.
# Их не трогали.



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
