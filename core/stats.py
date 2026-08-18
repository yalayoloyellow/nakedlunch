# extendo — append-only analytics log (user 2026-07-14: "лимит клода
# кончается... это чтоб потом проанализировать и инсайды получить"). Pure
# observation: every /api/generate, favorite (+remove), and история action
# writes one JSON line to data/stats.jsonl. Never read back by filters.py or
# corpus.py to steer output — that would reintroduce the λ-preference
# mechanism Round 20 removed. summary() is the only reader, and it only
# aggregates for display (the Statistics sidebar tab).

from __future__ import annotations

import csv
import io
import json
import time
from collections import Counter, defaultdict

import пути

DATA_DIR = пути.ДАННЫЕ
STATS_PATH = DATA_DIR / "stats.jsonl"


def log(kind: str, **fields) -> None:
    """Best-effort — a missed event just means one gap in future analysis,
    never a reason to fail the request that triggered it."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        entry = {"t": time.time(), "kind": kind, **fields}
        with STATS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def from_funnel(funnel: dict) -> dict:
    """Воронка filters.run → три числа, которые пишет запись «generate».

    ПОЧЕМУ ОТДЕЛЬНОЙ ФУНКЦИЕЙ. Раньше эти три выражения стояли прямо в роуте и
    читали ВЛОЖЕННУЮ воронку (funnel["gen"]["used"]), которой не существует:
    её отдавал `_rich_funnel`, вырезанный из горячего пути. Итог — KeyError
    после того, как выдача уже собрана, то есть 500-я на КАЖДЫЙ вызов
    /api/generate. Ни один тест этого не увидел: тесты зовут домен напрямую, а
    роут не звал никто. Здесь тот же разбор стоит в модуле, который тест
    импортирует за миллисекунды, и проверяется НАСТОЯЩЕЙ воронкой из
    filters.run (tests/test_funnel_contract.py).

    `.get` с нулём — сознательно: аналитика не повод ронять запрос (см. log),
    но ключи здесь именно те, что filters.run отдаёт на обеих ветках."""
    всего = int(funnel.get("shortlist", 0))
    из_корпуса = int(funnel.get("nl_used", 0))
    return {
        "shortlist": всего,
        # строк от грамматического генератора — всё, что в выдаче не из корпуса
        "gen_used": max(0, всего - из_корпуса),
        "nl_used": из_корпуса,
        "nl_classic_used": int(funnel.get("nl_classic_used", 0)),
    }


# НАДГРОБИЕ 2026-08-18: ВИД СОБЫТИЯ `pipeline` БОЛЬШЕ НЕ ПИШЕТСЯ.
#
# Его писал POST /api/pipeline/run — роут вырезан вместе со всей цепью. Именно
# этот журнал и стал основанием: 29 прогонов цепи против 587 одиночных строф за
# 10 живых дней, медиана 24.2 с, девяностый процентиль 98.7 с.
#
# СТАРЫЕ ЗАПИСИ В data/stats.jsonl ОСТАЮТСЯ, и читалка обязана их пережить.
# Она и переживает, без единой правки: `summary` раскладывает события по видам
# в defaultdict и просто не заглядывает в корзину «pipeline», а `export_csv`
# идёт с `extrasaction="ignore"` — чужие поля (links, junctions, runs,
# evaluated, variants) молча пропускаются. Проверено чтением, а не надеждой.


def _read_all() -> list[dict]:
    if not STATS_PATH.exists():
        return []
    out = []
    with STATS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------
# ЖИВЫЕ ПРОГОНЫ ПРОТИВ МАШИННЫХ ВСПЛЕСКОВ (2026-08-18)
#
# ЗАЧЕМ. В журнале 7 935 прогонов `generate`, и 7 113 из них сделаны 17 июля
# ЗА 21 МИНУТУ — медиана паузы 0.14 с, у всех пустая выдача. Человек так не
# нажимает: это прогон нагрузки или сорвавшийся цикл. Живых прогонов 822.
#
# ЦЕНА МОЛЧАНИЯ УЖЕ ЗАПЛАЧЕНА. Все, кто считал доли, делили на 7 935 — и мерили
# робота. Из-за этого в план попали как факты: «одно значение крутилки держится
# в 91% прогонов» (на самом деле 57.2%) и «тема задана в 13.3%» (на самом деле
# 30.9%). На этих числах принимались решения о том, какие ручки резать.
#
# ПОРОГИ ЗАМЕРЕНЫ, А НЕ НАЗНАЧЕНЫ. Развёртка по живому журналу даёт ПЛАТО:
#
#     порог, с | 0.5 | 0.75 |  1  | 1.5 |  2  |  3  |  4  |  5  |  10  |  30
#     живых    | 940 | 825  | 824 | 823 | 822 | 822 | 822 | 802 | 799  | 753
#
# От 2 до 4 секунд ответ не меняется вовсе — это и есть признак настоящей
# границы, а не подогнанного параметра. Ниже 0.75 с цепочка всплеска рвётся на
# куски и её хвосты начинают считаться живыми; выше 5 с порог начинает съедать
# настоящие человеческие паузы. Взята середина плато.
#
# ЧТО ЭТО НЕ ДЕЛАЕТ. Не удаляет ничего из журнала и не правит существующие поля
# `summary()` — они как считались по всему журналу, так и считаются. Тихо менять
# смысл поля, которое кто-то уже читает, значит завести второй, невидимый спор о
# том, что означает число. Живое считается ОТДЕЛЬНО и называется отдельно.

ПОРОГ_ВСПЛЕСКА_С = 3.0     # соседи ближе этого — звенья одной цепочки
ДЛИНА_ВСПЛЕСКА = 20        # цепочка от стольких прогонов считается машинной


def разделить_на_живое_и_машину(события: list[dict]) -> tuple[list[dict], list[dict]]:
    """Разложить события на человеческие и машинные всплески.

    Машинным считается КАЖДОЕ звено цепочки, где соседи идут чаще
    `ПОРОГ_ВСПЛЕСКА_С` и звеньев не меньше `ДЛИНА_ВСПЛЕСКА`. Короткая быстрая
    очередь машинной НЕ считается: человек тоже способен нажать пять раз подряд,
    и как раз ради этого в ленте сделан буфер предзагрузки.

    События без метки времени уходят в живые: неизвестное время — не повод
    объявить запись роботом.
    """
    со_временем = [e for e in события if isinstance(e.get("t"), (int, float))]
    без_времени = [e for e in события if not isinstance(e.get("t"), (int, float))]
    со_временем.sort(key=lambda e: e["t"])

    живые, машина = list(без_времени), []
    i = 0
    while i < len(со_временем):
        j = i
        while (j + 1 < len(со_временем)
               and со_временем[j + 1]["t"] - со_временем[j]["t"] < ПОРОГ_ВСПЛЕСКА_С):
            j += 1
        цепочка = со_временем[i:j + 1]
        (машина if len(цепочка) >= ДЛИНА_ВСПЛЕСКА else живые).extend(цепочка)
        i = j + 1
    return живые, машина


def всплески(события: list[dict]) -> list[dict]:
    """Описание каждого машинного всплеска: когда, сколько, за сколько.

    Нужно, чтобы всплеск можно было УВИДЕТЬ, а не только вычесть. Доля, взятая
    на веру, — ровно то, из-за чего этот код и понадобился.
    """
    со_временем = sorted((e for e in события if isinstance(e.get("t"), (int, float))),
                         key=lambda e: e["t"])
    из = []
    i = 0
    while i < len(со_временем):
        j = i
        while (j + 1 < len(со_временем)
               and со_временем[j + 1]["t"] - со_временем[j]["t"] < ПОРОГ_ВСПЛЕСКА_С):
            j += 1
        n = j - i + 1
        if n >= ДЛИНА_ВСПЛЕСКА:
            из.append({
                "начат": со_временем[i]["t"],
                "прогонов": n,
                "секунд": round(со_временем[j]["t"] - со_временем[i]["t"], 1),
            })
        i = j + 1
    return из


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(pct / 100 * (len(s) - 1))))
    return round(s[k], 1)


def summary() -> dict:
    """Aggregated for the Statistics tab — recomputed on every request by
    scanning the whole log. Fine at personal-tool scale (thousands of events,
    not millions); no reason to maintain a running index for one user."""
    events = _read_all()
    if not events:
        return {"events_total": 0}

    by_kind: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_kind[e.get("kind", "")].append(e)

    gens = by_kind.get("generate", [])
    favs = by_kind.get("favorite", [])
    unfavs = by_kind.get("unfavorite", [])
    shown = by_kind.get("shown", [])
    restores = by_kind.get("restore", []) + by_kind.get("restore_theme", [])
    clears = by_kind.get("clear_history", [])

    total_shown = sum(e.get("count", 0) for e in shown)

    theme_counter = Counter()
    scheme_counter = Counter()
    source_counter = Counter()
    knob_sums: dict[str, float] = defaultdict(float)
    knob_counts: dict[str, int] = defaultdict(int)
    latencies = []
    gen_used_total = 0
    nl_used_total = 0
    classic_used_total = 0
    daily = Counter()

    for e in gens:
        t = (e.get("theme") or "").strip()
        if t:
            theme_counter[t] += 1
        scheme_counter[e.get("rhyme") or "none"] += 1
        source_counter[e.get("source") or "editor"] += 1
        for k, v in (e.get("knobs") or {}).items():
            if isinstance(v, (int, float)):
                knob_sums[k] += v
                knob_counts[k] += 1
        lat = e.get("latency_ms")
        if isinstance(lat, (int, float)):
            latencies.append(lat)
        gen_used_total += e.get("gen_used", 0) or 0
        nl_used_total += e.get("nl_used", 0) or 0
        classic_used_total += e.get("nl_classic_used", 0) or 0
        day = time.strftime("%Y-%m-%d", time.localtime(e.get("t", 0)))
        daily[day] += 1

    # ЖИВОЕ СЧИТАЕТСЯ ОТДЕЛЬНО (2026-08-18). Поля выше остаются по ВСЕМУ
    # журналу — их кто-то уже читает, и менять смысл поля молча нельзя. Но доли,
    # посчитанные по всему журналу, мерили робота: 7 113 прогонов из 7 935 — это
    # один всплеск 17 июля длиной 21 минуту. Здесь те же доли, но по человеку.
    живые_гены, машинные_гены = разделить_на_живое_и_машину(gens)
    ж_тема = ж_наборы = 0
    ж_темы: Counter = Counter()
    ж_источники: Counter = Counter()
    ж_крутилки: Counter = Counter()
    for e in живые_гены:
        if (e.get("theme") or "").strip():
            ж_тема += 1
            ж_темы[(e.get("theme") or "").strip()] += 1
        ж_источники[e.get("source") or "editor"] += 1
        к = e.get("knobs") or {}
        if к:
            ж_наборы += 1
            ж_крутилки[json.dumps(к, sort_keys=True, ensure_ascii=False)] += 1
    самый_частый = ж_крутилки.most_common(1)

    template_counter = Counter((e.get("template") or "unknown") for e in favs)
    lemma_counter: Counter = Counter()
    for e in favs:
        for lemma in (e.get("lemmas") or [])[:20]:
            lemma_counter[lemma] += 1

    avg_knobs = {k: round(knob_sums[k] / knob_counts[k], 3) for k in knob_sums if knob_counts[k]}
    total_favorited = len(favs)
    total_unfavorited = len(unfavs)

    return {
        "events_total": len(events),
        "since": min(e.get("t", 0) for e in events),
        "generate": {
            "count": len(gens),
            "by_source": dict(source_counter),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "p95_latency_ms": _percentile(latencies, 95),
            "rhyme_scheme_counts": dict(scheme_counter.most_common()),
            "avg_knobs": avg_knobs,
            "gen_used_total": gen_used_total,
            "nl_used_total": nl_used_total,
            "classic_used_total": classic_used_total,
            "top_themes": theme_counter.most_common(15),
            "daily_last_30": dict(sorted(daily.items())[-30:]),
        },
        # ЧЕЛОВЕЧЕСКИЕ ПРОГОНЫ, БЕЗ МАШИННЫХ ВСПЛЕСКОВ. Считать доли по полю
        # `generate` выше — значит считать вместе с роботом; на этом уже трижды
        # обожглись. Здесь знаменатель — только то, что нажимал человек.
        "живое": {
            "прогонов": len(живые_гены),
            "машинных_прогонов": len(машинные_гены),
            "всплесков": len(всплески(gens)),
            "порог_с": ПОРОГ_ВСПЛЕСКА_С,
            "минимум_в_цепочке": ДЛИНА_ВСПЛЕСКА,
            "с_темой": ж_тема,
            "доля_с_темой_pct": round(100 * ж_тема / len(живые_гены), 1) if живые_гены else None,
            "источники": dict(ж_источники),
            "разных_наборов_крутилок": len(ж_крутилки),
            "доля_самого_частого_набора_pct": (
                round(100 * самый_частый[0][1] / ж_наборы, 1) if самый_частый and ж_наборы else None),
            "топ_тем": ж_темы.most_common(15),
        },
        "shown": {"total_lines": total_shown, "events": len(shown)},
        "favorites": {
            "added": total_favorited,
            "removed": total_unfavorited,
            "net": total_favorited - total_unfavorited,
            "rate_pct": round(100 * total_favorited / total_shown, 2) if total_shown else None,
            "by_template": dict(template_counter),
            "top_lemmas": lemma_counter.most_common(20),
        },
        "history": {
            "restores": len(restores),
            "restored_lines": sum(e.get("count", 0) for e in restores),
            "clears": len(clears),
            "cleared_lines": sum(e.get("count", 0) for e in clears),
        },
    }


# ---- raw export (2026-07-14, user: "статистика... для дальнейшего анализа")
# The RAW event log, not summary()'s aggregates — aggregation is for the
# in-app tab; real offline analysis wants the individual events.

_CSV_FIELDS = [
    "t", "kind", "source", "theme", "rhyme", "shortlist",
    "gen_used", "nl_used", "nl_classic_used", "latency_ms",
    "melody", "cohesion", "banality", "real_text", "rhyme_precision", "classic",
    "text", "template", "lemmas", "count", "days",
]


def export_json() -> str:
    return json.dumps(_read_all(), ensure_ascii=False, indent=1)


def export_csv() -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore", restval="")
    w.writeheader()
    for e in _read_all():
        row = dict(e)
        knobs = row.pop("knobs", None) or {}
        for k in ("melody", "cohesion", "banality", "real_text", "rhyme_precision", "classic"):
            if k in knobs:
                row[k] = knobs[k]
        if isinstance(row.get("lemmas"), list):
            row["lemmas"] = ";".join(row["lemmas"])
        w.writerow(row)
    return buf.getvalue()
