#!/usr/bin/env python3
# nakedlunch — печём колоночный индекс корпуса (Раунд 31 DECISIONS.md).
#
#   python tools/build_nl_index.py            → core/data/nl_index/
#   python tools/build_nl_index.py --check    → только сверить версию правил
#
# ЗАЧЕМ. Раньше каждый запрос заново перебирал весь корпус и лепил словарь на
# каждый из 2.6 млн фрагментов, чтобы выбросить 99.8% из них: 5 с без темы и
# 38–73 с на новом выделенном слове (замеры — Раунды 28/30/31). Всё, что при
# этом считалось, — свойства самого фрагмента, а не запроса. Здесь мы считаем
# их ОДИН раз и кладём колонками, которые читаются через mmap за 0.1 с вместо
# 12–46 с разбора JSON и без 5.5 ГБ в памяти.
#
# ЧТО НЕ МЕНЯЕТСЯ. Полный перебор базы (решение Раунда 20) остаётся: через
# фильтры по-прежнему проходит каждый фрагмент. Уходит только холостая
# материализация. Сверка на полном пуле дала 0 расхождений из 1 761 809 строк
# на трёх наборах ручек — см. DECISIONS.md, Раунд 31, шаг 1.
#
# КОГДА ПЕРЕПЕКАТЬ. (1) выросло число фрагментов — после build_nl_rhyme.py;
# (2) изменились ПРАВИЛА (список клише, корни мата, формула банальности,
# лемматизатор) — тогда меняется RULES ниже, и загрузчик честно откажется
# читать старый индекс. Смена темы, ручек, фильтра мата, включение и
# выключение источников перепечи НЕ требуют — это маски поверх колонок.
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import embeddings  # noqa: E402
import filters     # noqa: E402

OUT = ROOT / "core" / "data" / "nl_index"

# Версия ПРАВИЛ, а не данных: любое изменение того, КАК считаются гейты, обязано
# её сдвинуть, иначе индекс будет тихо отвечать по старым правилам.
# ВЕРСИЯ ПРАВИЛ — ОДНА, У ИНДЕКСА (Раунд 57). Здесь стояла её КОПИЯ, и это
# ровно та порода ошибки, которую проект ловит весь день: правила поменялись в
# `core/nlindex.py`, сборщик испёк индекс со СТАРОЙ строкой, загрузчик сверил и
# честно отказался читать — «индекс не испечён» при только что испечённом
# индексе. Один источник, а не два согласованных вручную.
from nlindex import RULES  # noqa: E402


# ПРОГРЕСС ВИДЕН СНАРУЖИ (Раунд 56). Пользователь: «хочу, чтоб всё чётко
# отображалось и в реальном времени из реальных данных подтягивалось».
#
# У сборки ударений сайдкар со статусом был с самого начала, у сборки индекса —
# нет: снаружи она выглядела чёрным ящиком, который «идёт», и всё. Сорок секунд
# без единого числа читаются как «висит», особенно после того, как она годами
# молча падала.
СТАТУС = OUT.parent / "nl_index.status.json"


def статус(**поля):
    """Дописать сайдкар. Падение записи не должно ронять сборку: статус —
    удобство, а индекс — работа."""
    try:
        было = {}
        if СТАТУС.exists():
            было = json.loads(СТАТУС.read_text("utf-8"))
        было.update(поля)
        было["updated_at"] = time.time()
        СТАТУС.write_text(json.dumps(было, ensure_ascii=False), "utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# СЦЕПКА СОСЕДНИХ СЛОВ (Раунд 58, пункт 7 плана).
#
# Пользователь: «ручка банальность должна по обоим фронтам работать одна крутилка».
# Второй фронт — сочетания: «сердце» обычное, «боль» обычное, а «сердечная
# боль» — штамп. Банальность этого не видит, она смотрит слова поодиночке.
#
# МЕРА — PMI: как часто два слова стоят РЯДОМ против того, как часто каждое
# встречается вообще. Учится на ЕГО корпусе: затасканное у Селина не будет
# затасканным у Мандельштама.
#
# «Рядом» — соседние ЗНАМЕНАТЕЛЬНЫЕ слова: в кэше лежат именно они, по порядку.
# «Боль в сердце» и «сердечная боль» дают одну и ту же пару, и это правильно.
#
# ЧЕТЫРЕ УСЛОВИЯ ДЛЯ ПАРЫ, и каждое выбрано по замеру на его корпусе
# (2026-08-06, 2 434 632 строки, 80 555 лемм, 6.9 млн вхождений пар):
#
# 1. НЕ ИМЕНА. Без этого условия верхушка сцепки — сплошь авторы афоризмов:
#    «джулиан+барнс», «мэрилин+монро», «акутагава+рюноскэ». Ровно та беда, из-за
#    которой имена уже выброшены из банальности (Раунд 57).
# 2. ОБЫЧНЫЕ СЛОВА (zipf ≥ 3.0). Штамп по определению собран из обычных слов;
#    пара редких слов, всегда стоящих вместе, — это термин или имя.
# 3. ПАРА ВСТРЕЧАЕТСЯ ХОТЯ БЫ 30 РАЗ. При пороге 10 в верхушке ещё «пинк+флойд»
#    и «хэмфри+богарт», при 300 — уже чистый русский штамп («пожать плечо»,
#    «точка зрения», «здравый смысл», «крайняя мера»). 30 — начало этой зоны.
# 4. КАЖДОЕ СЛОВО ЖИВЁТ И САМО (dice ≤ 0.55). Это ловит имена, которых не знает
#    морфология: «мейсон+кули» 0.85, «г-жа+сент-анж» 0.68, «уорд+бичер» 0.71 —
#    эти слова в корпусе встречаются ТОЛЬКО друг с другом, значит это не штамп
#    языка, а составное название. У настоящих штампов 0.2–0.45 («пожать плечо»
#    0.31, «точка зрения» 0.43): каждое слово прекрасно живёт отдельно.
#
# СЦЕПКА СТРОКИ — максимум по её парам, как банальность это минимум по её
# словам: одна затасканная связка делает затасканной всю строку. Нет ни одной
# знакомой пары — ноль, «ничего не знаем», а не «свежо».
ПАРА_МИН = 30        # сколько раз пара должна встретиться, чтобы считаться
ZIPF_МИН = 3.0       # оба слова должны быть обычными словами языка
DICE_МАКС = 0.55     # каждое слово обязано жить и вне этой пары
_БАЗА = 1 << 22      # код пары = a * _БАЗА + b (лемм в корпусе ~80 тыс.)


def сцепка_колонка(записи, n: int) -> tuple[np.ndarray, dict]:
    """(колонка сцепки на каждый фрагмент, справка о том, как она вышла).

    `записи` — что угодно, что отдаёт поля кэша по порядку (у сборки это
    `R.values()`, у замера — поток с диска): один проход, дальше всё векторно.
    Вся цена — морфология по СЛОВАРЮ (80 тыс. слов, ~15 с), а не по 2.4 млн
    строк."""
    from array import array
    import corpus as _corpus
    from wordfreq import zipf_frequency

    t = time.time()
    слово: dict[str, int] = {}
    счёт: list[int] = []
    коды = array("q")
    пар_в_строке = np.zeros(n, dtype=np.int32)
    for i, e in enumerate(записи):
        ids = []
        for l in (e.get("lemmas") or ()):
            j = слово.get(l)
            if j is None:
                j = len(счёт)
                слово[l] = j
                счёт.append(0)
            счёт[j] += 1
            ids.append(j)
        for a, b in zip(ids, ids[1:]):
            коды.append(a * _БАЗА + b)
        пар_в_строке[i] = max(0, len(ids) - 1)
    print(f"  сцепка: словарь {len(слово)}, вхождений пар {len(коды)}, {time.time()-t:.0f}с", flush=True)

    леммы = [""] * len(слово)
    for w, j in слово.items():
        леммы[j] = w
    t = time.time()
    имя = np.fromiter((_corpus.имя_ли(w) for w in леммы), dtype=bool, count=len(леммы))
    zipf = np.fromiter((zipf_frequency(w, "ru") for w in леммы), dtype=np.float32, count=len(леммы))
    print(f"  сцепка: морфология по словарю {time.time()-t:.0f}с, имён {int(имя.sum())}", flush=True)

    все = np.frombuffer(коды, dtype=np.int64)
    уник, cnt = np.unique(все, return_counts=True)
    сч = np.array(счёт, dtype=np.int64)
    a = (уник // _БАЗА).astype(np.int64)
    b = (уник % _БАЗА).astype(np.int64)
    dice = 2.0 * cnt / (сч[a] + сч[b])
    годна = ((cnt >= ПАРА_МИН) & (~имя[a]) & (~имя[b])
             & (zipf[a] >= ZIPF_МИН) & (zipf[b] >= ZIPF_МИН) & (dice <= DICE_МАКС))
    N_слов, N_пар = int(сч.sum()), int(cnt.sum())
    pmi = np.log2((cnt.astype(np.float64) * N_слов * N_слов) / (сч[a] * сч[b] * N_пар))
    ключи, знач = уник[годна], np.maximum(pmi[годна], 0.0).astype(np.float32)

    поз = np.searchsorted(ключи, все)
    np.clip(поз, 0, max(0, len(ключи) - 1), out=поз)
    есть = (ключи[поз] == все) if len(ключи) else np.zeros(len(все), dtype=bool)
    на_пару = np.where(есть, знач[поз] if len(ключи) else 0.0, 0.0).astype(np.float32)

    out = np.zeros(n, dtype=np.float32)
    if len(на_пару):
        нач = np.zeros(n, dtype=np.int64)
        нач[1:] = np.cumsum(пар_в_строке)[:-1]
        np.clip(нач, 0, len(на_пару) - 1, out=нач)
        # reduceat на пустой группе возвращает соседний элемент — гасим маской
        r = np.maximum.reduceat(на_пару, нач)
        есть_пары = пар_в_строке > 0
        out[есть_пары] = r[есть_пары]

    # ЧТО ДЕТЕКТОР ВЫУЧИЛ — В ЛОГ СБОРКИ. Метрика, которую нельзя увидеть
    # глазами, однажды тихо начнёт мерить не то; двадцать строк в логе стоят
    # ноль и показывают ровно то, что попадёт под ручку.
    ид = np.flatnonzero(годна)
    верх = [(леммы[int(a[i])], леммы[int(b[i])], int(cnt[i]), round(float(pmi[i]), 2))
            for i in ид[np.argsort(-pmi[ид])[:20]]]
    справка = {"пар_всего": int(len(уник)), "пар_годных": int(годна.sum()),
               "строк_сцепленных": int((out > 0).sum()), "верх": верх}
    print(f"  сцепка: пар {справка['пар_всего']}, годных {справка['пар_годных']}, "
          f"строк со сцепкой {справка['строк_сцепленных']} "
          f"({100.0*справка['строк_сцепленных']/max(1,n):.1f}%)", flush=True)
    print("  самые сцепленные пары: "
          + ", ".join(f"{x} {y} ({c}× pmi {p})" for x, y, c, p in верх[:10]), flush=True)
    return out, справка


def кванты(колонка: np.ndarray, только_ненулевые: bool = False) -> list[float]:
    """101 точка распределения — шкала крутилки берётся отсюда, а не из
    магических чисел. Считается при сборке: это свойство корпуса, а не запроса.

    `только_ненулевые` — для сцепки: у 70% строк её нет вовсе, и перцентиль по
    всему пулу до 70-го был бы нулём, то есть шкала жила бы в последней трети
    хода. Ноль всё равно первой точкой: «не сцеплено» это край шкалы."""
    a = np.asarray(колонка, dtype=np.float64)
    if только_ненулевые:
        a = a[a > 0]
        if not len(a):
            return [0.0] * 101
        точки = [0.0] + [float(np.percentile(a, q)) for q in range(1, 101)]
        return [round(x, 4) for x in точки]
    return [round(float(np.percentile(a, q)), 4) for q in range(101)]


def build() -> int:
    t0 = time.time()
    статус(state="running", stage="загружаю кэш ударений", done=0, total=0, error=None)
    filters.warm_caches()
    embeddings.warm_caches()
    # ПЕЧЁМ ИЗ JSON НАПРЯМУЮ (Раунд 56).
    #
    # `filters.warm_caches()` СПЕЦИАЛЬНО не грузит nl_rhyme.json, когда
    # колоночный индекс уже на месте (Раунд 34: иначе каждый процесс платил бы
    # 14 с и 5.5 ГБ за файл, который больше никто не читает). А сборщику индекса
    # он нужен — индекс печётся ИЗ него.
    #
    # Получалась глухая петля: индекс есть → кэш не грузится → сборщик видит
    # пустоту → «печь нечего» → выход с ошибкой → индекс НИКОГДА не
    # перепекается. Молча: вывод сборки уходил в /dev/null. Так у пользователя и
    # накопились 251 727 строк вне индекса — каждая перепечка после каждой
    # залитой книги умирала на первой же строке.
    R = filters._NL_RHYME
    if not R and filters._NL_RHYME_PATH.exists():
        print("кэш ударений не загружен (индекс на месте) — читаю сам", flush=True)
        import кэш
        R = кэш.читать_всё()
        filters._NL_RHYME = R
    navec = embeddings._index or {}
    n = len(R)
    if not n:
        print("nl_rhyme.json пуст — печь нечего (сначала tools/build_nl_rhyme.py)", file=sys.stderr)
        статус(state="error", error="кэш ударений пуст — сначала прогони ударения")
        return 1
    print(f"загрузка кэша: {time.time()-t0:.1f}с, записей {n}", flush=True)
    статус(stage="обхожу корпус", done=0, total=n)

    # Клише здесь больше НЕТ (Раунд 58): три зашитых выражения заменены
    # измеренной сцепкой соседних слов — см. `сцепка_колонка`.
    VOWELS, has_mat = filters.VOWELS, filters.has_mat
    t = time.time()
    parts: list[bytes] = []
    text_off = np.zeros(n + 1, dtype=np.int64)
    banal = np.empty(n, dtype=np.float32)
    taut = np.zeros(n, dtype=np.uint8)
    mat = np.zeros(n, dtype=np.uint8)
    syl = np.zeros(n, dtype=np.uint16)
    span_a = np.full(n, -1, dtype=np.int16)
    span_b = np.full(n, -1, dtype=np.int16)
    keys: dict[str, int] = {}
    key_id = np.zeros(n, dtype=np.uint32)
    lem_vocab: dict[str, int] = {}
    lem_flat: list[int] = []
    lem_off = np.zeros(n + 1, dtype=np.int64)
    tok_vocab: dict[str, int] = {}
    tok_pairs: list[tuple[int, int]] = []
    pos = 0

    # КОЛОНКА ИСТОЧНИКА (Раунд 57). Индекс не знал, из какой книги строка —
    # четырнадцать колонок и ни одной про происхождение. Поэтому отбор физически
    # не мог заметить, что берёт двенадцать строк из одной книги: для него это
    # просто двенадцать хороших строк. Пользователь видел это как «везде одна и та
    # же книга», а все правки били по симптомам — разброс между равными, полоса
    # лучших, банальность без имён, — потому что причина лежала слоем ниже.
    #
    # Четыре байта на фрагмент, десяток мегабайт на весь корпус, тот же проход.
    import nlbridge as _nb
    _store = _nb.open_store()
    _книга_по_тексту = {}
    _имена = []
    _номер = {}
    for _f in _store.get_all_fragments():
        cid = _f.get("corpus_id") or ""
        if cid not in _номер:
            _номер[cid] = len(_имена)
            _имена.append(cid)
        _книга_по_тексту[_f["text"]] = _номер[cid]
    print(f"источников: {len(_имена)}, текстов с источником: {len(_книга_по_тексту)}", flush=True)
    src = np.full(n, -1, dtype=np.int32)
    # СКОЛЬКО В СТРОКЕ ОБЫЧНЫХ СЛОВ (Раунд 57) — считается в кэше ударений
    # (`_extra_fields`), сюда переносится колонкой. Без неё ворота по нему
    # невыразимы так же, как были невыразимы ворота по источнику.
    content = np.zeros(n, dtype=np.int16)

    for i, (text, e) in enumerate(R.items()):
        src[i] = _книга_по_тексту.get(text, -1)
        content[i] = int(e.get("content") or 0)
        b = text.encode("utf-8")
        parts.append(b)
        pos += len(b)
        text_off[i + 1] = pos
        banal[i] = float(e.get("banal", 9.0))
        taut[i] = 1 if e.get("taut", False) else 0
        low = text.lower()
        mat[i] = 1 if has_mat(low) else 0
        syl[i] = min(65535, sum(map(low.count, VOWELS)))
        k = e.get("key") or ""
        kid = keys.get(k)
        if kid is None:
            kid = len(keys)
            keys[k] = kid
        key_id[i] = kid
        sp = e.get("span")
        if isinstance(sp, (list, tuple)) and len(sp) == 2:
            span_a[i], span_b[i] = int(sp[0]), int(sp[1])
        # МНОЖЕСТВОМ, как в старом пути (`cl = set(entry["lemmas"])`): повторы
        # схлопываются, иначе среднее релевантности разъедется
        for w in dict.fromkeys(e.get("lemmas") or []):
            lid = lem_vocab.get(w)
            if lid is None:
                lid = len(lem_vocab)
                lem_vocab[w] = lid
            lem_flat.append(lid)
        lem_off[i + 1] = len(lem_flat)
        for w in (e.get("tokens") or []):
            tid = tok_vocab.get(w)
            if tid is None:
                tid = len(tok_vocab)
                tok_vocab[w] = tid
            tok_pairs.append((tid, i))
        if (i + 1) % 500_000 == 0:
            print(f"  {i+1}/{n}  {time.time()-t:.0f}с", flush=True)
            статус(done=i + 1)
    print(f"обход: {time.time()-t:.1f}с | лемм {len(lem_vocab)} | токенов {len(tok_vocab)}", flush=True)

    статус(stage="считаю сцепку соседних слов", done=n, total=n)
    bind, _справка = сцепка_колонка(R.values(), n)

    t = time.time()
    lem_ids = np.array(lem_flat, dtype=np.int32)
    del lem_flat
    lem_list = [""] * len(lem_vocab)
    lem2navec = np.full(len(lem_vocab), -1, dtype=np.int32)
    for w, i2 in lem_vocab.items():
        lem_list[i2] = w
        r = navec.get(w)
        if r is not None:
            lem2navec[i2] = r
    # обратный индекс токен → фрагменты: он и даёт literal/forced мгновенно
    tp = np.array(tok_pairs, dtype=np.int32)
    del tok_pairs
    order = np.argsort(tp[:, 0], kind="stable")
    tokpost = tp[order, 1].copy()
    tokoff = np.zeros(len(tok_vocab) + 1, dtype=np.int64)
    np.cumsum(np.bincount(tp[:, 0], minlength=len(tok_vocab)), out=tokoff[1:])
    del tp, order
    статус(stage="постобработка", done=n)
    print(f"постобработка: {time.time()-t:.1f}с", flush=True)

    # пишем во временный каталог и переставляем — краш посреди записи не
    # оставит полуиндекс, который загрузчик примет за целый
    t = time.time()
    tmp = OUT.with_name(OUT.name + ".tmp")
    if tmp.exists():
        for p in tmp.iterdir():
            p.unlink()
        tmp.rmdir()
    tmp.mkdir(parents=True)
    for name, arr in (("banal", banal), ("taut", taut), ("bind", bind), ("mat", mat),
                      ("syl", syl), ("key_id", key_id), ("span_a", span_a), ("span_b", span_b),
                      ("lem_ids", lem_ids), ("lem_off", lem_off), ("lem2navec", lem2navec),
                      ("tokpost", tokpost), ("tokoff", tokoff), ("text_off", text_off),
                      ("src", src), ("content", content)):
        np.save(tmp / f"{name}.npy", arr)
    (tmp / "text_blob.bin").write_bytes(b"".join(parts))
    key_list = [""] * len(keys)
    for k, i2 in keys.items():
        key_list[i2] = k
    (tmp / "meta.json").write_text(json.dumps({
        "n": n, "rules": RULES, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "keys": key_list, "lemmas": lem_list,
        "tokens": [w for w, _ in sorted(tok_vocab.items(), key=lambda kv: kv[1])],
        "sources": _имена,
        # ШКАЛА РУЧКИ «БАНАЛЬНОСТЬ» — ИЗ КОРПУСА, А НЕ ИЗ ГОЛОВЫ (Раунд 58).
        # «Оставить десятую часть самых обычных» осмысленно на любом корпусе,
        # «zipf ≥ 4.45» — только на этом. Считаем при сборке: это свойство
        # данных, и пересчитывать его на каждом запросе незачем.
        "кванты": {"banal": кванты(banal), "bind": кванты(bind, только_ненулевые=True)},
    }, ensure_ascii=False), "utf-8")
    if OUT.exists():
        old = OUT.with_name(OUT.name + ".old")
        OUT.rename(old)
        tmp.rename(OUT)
        for p in old.iterdir():
            p.unlink()
        old.rmdir()
    else:
        tmp.rename(OUT)
    size = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"запись: {time.time()-t:.1f}с | индекс {size/1024/1024:.0f} МБ в {OUT}", flush=True)
    print(f"ВСЕГО {time.time()-t0:.0f}с", flush=True)
    статус(state="done", stage="готово", done=n, total=n, seconds=round(time.time() - t0, 1))
    return 0


def check() -> int:
    meta = OUT / "meta.json"
    if not meta.exists():
        print("индекса нет")
        return 1
    m = json.loads(meta.read_text("utf-8"))
    ok = m.get("rules") == RULES
    print(f"индекс: записей {m.get('n')}, собран {m.get('built_at')}")
    print(f"правила {'совпадают' if ok else 'РАЗОШЛИСЬ — нужна перепечь'}: {m.get('rules')!r} vs {RULES!r}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(check() if "--check" in sys.argv else build())
