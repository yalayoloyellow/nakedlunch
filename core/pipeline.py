# extendo — пайплайн: пулы по звеньям + комбинаторная склейка (ФАЗА 1,
# PLAN.md, решение прожарки №4: «пулы по звеньям + комбинаторная склейка, а
# не N независимых полных прогонов»). Один прогон = несколько ВНУТРЕННИХ
# вызовов существующего пути generate/filters (никакого HTTP к самому себе:
# api/server.py — тонкий адаптер, домен зовёт домен напрямую), затем beam-
# перебор сочетаний строф с оценкой склейки. Замок «один прогон за раз» и
# прогресс-словарь живут в api/server.py — это свойства процесса-сервера,
# не домена; сюда прогресс приходит колбэком.

from __future__ import annotations

import re
import time

import clean
import filters
import generate
import settings as settings_mod
import stanza_profiles

# ---------------------------------------------------------------------------
# Веса и константы оценки склейки — КОНСТАНТЫ МОДУЛЯ, не зарытые в код числа:
# ворота фазы 1 — живое сравнение с одиночной генерацией («заметно лучше, или
# усиливаем оценку склейки»), то есть эти числа заведомо будут крутиться
# после первого честного прослушивания, без переписывания архитектуры.
# combo = W_QUALITY·качество + W_JUNCTION·стыки + W_REPEATS·(1−повторы).
# ---------------------------------------------------------------------------
W_QUALITY = 0.5
W_JUNCTION = 0.3
W_REPEATS = 0.2

# Ярусы совпадения рифмо-ключей граничных строк стыка. Градация — та же
# механика, что filters._rhyme_prefix_len (3/2/1 символов от ударной гласной):
# полный ключ = точная рифма; 3 символа = «глубокий» ярус (строжайший
# неточный, precision<=0.34); 1 символ = «слабый» (одна ударная гласная,
# самый мягкий ярус той же шкалы — ассонанс). Промежуточный 2-символьный ярус
# шкалы здесь не выделен в отдельный балл сознательно: стыку нужен ПОРЯДОК
# (точнее → выше), а не копия всех настроек точности рифм.
TIER_EXACT = 1.0
TIER_DEEP = 0.7
TIER_WEAK = 0.4
_DEEP_PREFIX = 3
_WEAK_PREFIX = 1

# «Свободно» — нейтральная константа, НЕ 0 и НЕ 1: свободный стык не должен
# ни топить комбо (это не дефект), ни выигрывать у настоящей рифмовки стыка;
# между двумя свободными сортировку двигают качество и повторы.
JUNCTION_FREE_SCORE = 0.7

# «Слом ритма»: слоговой контраст граничных строк, min(1, |Δслогов|/3) —
# делитель 3 = «три слога разницы уже слышны как слом», дальше насыщение.
BREAK_SATURATION = 3.0

# ---------------------------------------------------------------------------
# РОЛЕЙ БОЛЬШЕ НЕТ (Раунд 50).
#
# Здесь жили две таблицы: DEFAULT_ROLE_FORMS (роль выбирала форму строфы) и
# DEFAULT_ROLE_DELTAS (роль сдвигала крутилки). То есть слово «Припев» в
# интерфейсе тайно назначало и рифмовку, и связность, и точность рифм — при
# том что рядом стоял селектор профиля строфы, а подпись под ролью прямо
# обещала «заголовок в документе, на генерацию не влияет».
#
# Пользователь 2026-08-03: «каждому элементу pipeline я выбираю строфу уже из
# заготовленных, уже из сохранённых, и выбираю профиль настроек уже из
# сохранённых. Я ничего не настраиваю, мне не нужно ещё дополнительных
# крутилок туда».
#
# Теперь звено обязано принести СВОЁ: spec (каркас с полки строф) и knobs
# (профиль настроек). Роль осталась необязательным `title` — заголовком
# секции в документе, ровно тем, чем её и подписывали.
#
# Две формы, которые жили ТОЛЬКО в этих таблицах, перенесены на полку строф
# (core/data/stanza_forms.json): «Двустишие» (аа 6-9) и «Катрен парный
# короткий» (аабб 6-8). Двустиший в датасете не было вообще — вместе с
# таблицей они исчезли бы из проекта.
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


# ---------------------------------------------------------------------------
# 1. Цепочка → разрешённые звенья (форма + слитые кнобы + ключ профиля)
# ---------------------------------------------------------------------------

# Крутилки, по которым звенья считаются РАЗНЫМИ. Ключ решает, поделят ли два
# звена один пул строф, поэтому в него обязано входить всё, что меняет состав
# пула или порядок в нём.
#
# Раньше здесь было ЧЕТЫРЕ имени (cohesion/melody/banality/rhyme_precision), а
# ворота — clausula, flow, mat_share, only_mat, no_mat, classic, real_text — в
# ключ не входили. Пока настройки звену задавала роль, значения у всех звеньев
# почти всегда совпадали и это не стреляло. Как только каждое звено приносит
# свой профиль (Раунд 50), два звена с одинаковым каркасом и разным матом или
# разной клаузулой молча поделили бы ОДИН пул — и второе получило бы строфы,
# набранные по чужим воротам. Найдено картой раунда до того, как выстрелило.
_KEY_KNOBS = ("cohesion", "melody", "banality", "rhyme_precision",
              "real_text", "classic", "mat_share", "clausula", "flow")


def resolve_chain(chain: list[dict], base_knobs: dict) -> list[dict]:
    """Каждое звено запроса → {title, form, spec, knobs, key}.

    Раунд 50: звено ПРИНОСИТ СВОЁ. Каркас — либо именованная форма с полки
    строф, либо спека, снятая с референса; крутилки — профиль настроек звена,
    и это АБСОЛЮТНЫЕ значения, а не поправка к глобальным.

    Почему не поправка. Раньше звено получало `dict(base_knobs)`, и поверх
    ложился `clean.knobs(item["knobs"])` — а он возвращает ПОЛНЫЙ словарь с
    дефолтами для всего, чего в запросе не было. То есть звено, принёсшее
    хоть один свой кноб, молча сбрасывало в дефолт и classic, и melody, и
    banality, и real_text. Бинарный переключатель классики в цепочке из
    референса выключался бы сам собой. Абсолютные значения эту породу ошибок
    убирают целиком: что в профиле — то и в прогоне.

    `base_knobs` остаётся фолбэком для звена БЕЗ своего профиля — цепочка,
    собранная до появления полки, продолжает работать.

    `key` — ключ уникального профиля (каркас + все значащие крутилки):
    повторные вхождения одного и того же звена делят пул, генерация не
    гоняется дважды за тем же."""
    profiles: dict[str, list[dict]] = {}
    for p in stanza_profiles.builtin() + stanza_profiles.custom():
        spec = clean.stanza_spec(p.get("lines"))
        if spec and p.get("name"):
            profiles[p["name"]] = spec

    links = []
    for item in chain:
        # Заголовок секции — необязательная пометка для документа. На
        # генерацию не влияет, и теперь это правда, а не подпись в интерфейсе.
        title = str(item.get("title") or item.get("role") or "").strip()

        # ХУК (Раунд 52): звено может быть ПОВТОРОМ более раннего — та же
        # самая строфа, стоящая в песне второй раз. Пользователь: «хуки, хуковые
        # припевы и хуковые элементы механизм должен уметь делать».
        #
        # Это не крутилка и не вероятность, а структура: видно глазами в
        # цепочке и воспроизводится точно. Звено-повтор наследует каркас,
        # крутилки и КЛЮЧ ПУЛА двойника — значит генерация за него не платит
        # ничего (пул уже построен), а `assemble` просто ставит ту же строфу.
        # Свой остаётся только заголовок: «припев» можно подписать иначе.
        повтор = item.get("repeat_of")
        if повтор is not None:
            двойник = links[повтор]      # clean.pipeline_spec уже проверил, что он есть и раньше
            links.append({**двойник, "title": title, "repeat_of": повтор})
            continue

        form_name = item.get("form")
        свой = item.get("spec")
        if свой:
            # Спека приехала С САМИМ ЗВЕНОМ — из референса или из слепка
            # цепочки. Она главнее имени формы: слепок на то и слепок, что
            # правка полки не должна менять сохранённое решение. Имя, если
            # оно есть, остаётся ПОДПИСЬЮ — иначе в воронке у всех звеньев
            # стояло бы «из референса», даже когда форму выбирали руками.
            spec = свой
            form_name = form_name or "своя строфа"
        elif form_name:
            spec = profiles.get(form_name)
            if spec is None:
                # пользователь явно назвал форму — молча подменить её значит
                # спорить с ним
                raise clean.BadInput(f"форма строфы «{form_name}» не найдена")
        else:
            # Звено без каркаса: берём текущую строфу настроек — то, чем
            # пользователь генерирует одиночные, — иначе честный отказ. Тихого
            # «дефолта куплета» больше нет: он превращал всю цепочку в шесть
            # одинаковых строф, и понять это можно было только по выдаче.
            spec = clean.stanza_spec(settings_mod.read().get("stanza"))
            if not spec:
                raise clean.BadInput("у звена нет строфы — выбери форму или сними её с референса")
            form_name = "строфа из настроек"

        # Абсолютные крутилки звена; нет своих — глобальные прогона.
        knobs = clean.knobs(item["knobs_own"]) if item.get("knobs_own") else dict(base_knobs)

        key = (tuple((r["letter"], r["min_syl"], r["max_syl"]) for r in spec),
               tuple(round(float(knobs.get(k, 0.0)), 3) for k in _KEY_KNOBS))
        links.append({"title": title, "form": form_name, "spec": spec,
                      "knobs": knobs, "key": key, "repeat_of": None})
    return links


# ---------------------------------------------------------------------------
# 2. Пулы строф — по одному на УНИКАЛЬНЫЙ профиль (форма+кнобы)
# ---------------------------------------------------------------------------

class Остановлено(Exception):
    """Пользователь нажал «остановить» ПОСРЕДИ текста (Раунд 55).

    До этого остановка спрашивалась только МЕЖДУ текстами — и это было верно,
    пока текст стоил пятнадцать секунд. На цепочке пользователя он стоил 777
    (замерено: 4 уникальных звена, одно из них Одическая строфа в десять строк
    — 688 секунд из 777 на неё одну; 124 950 сочетаний в переборе — 0.8 с).
    Тринадцать минут между нажатием и реакцией читаются как «кнопка не
    работает», и он сказал ровно это: «если зависло, то остановится только
    после генерации текущего, а значит не остановится».

    Раунд 56 срезал текст до 28 секунд (filters._select_with_rhyme, ранний
    выход вместо полного перебора), но проверка осталась внутри отбора.

    Спрашиваем в двух местах, где время и уходит: перед каждым пулом и внутри
    перебора. Брошенный посреди текст просто не рождается — лист не пишется,
    в историю ничего не уходит, счёт не двигается."""


def _build_one_pool(link: dict, tags: list, forced: set, pool_per_link: int,
                    corpus, nl_fragments: list, стоп=None) -> list[dict]:
    """Один внутренний прогон generate→filters.run для профиля звена.
    filters.run с активной схемой отдаёт строки ГРУППАМИ ПО СТРОФАМ
    (shortlist = строф × длина спеки — так его и зовёт /api/generate, беря
    25 строф одним вызовом), поэтому пул строф — это просто нарезка
    shortlist по длине спеки. rank строфы = её порядок в выдаче: каскад уже
    отранжировал, качество звена ниже считается из этого ранга."""
    spec = link["spec"]
    length = len(spec)
    knobs = dict(link["knobs"])
    knobs["shortlist"] = pool_per_link * length
    rhyme = clean.stanza_letters(spec)

    lines = []
    if knobs["nl_mix"] < 1.0:
        # та же формула объёма, что в api_generate: сырых кандидатов нужно
        # кратно больше шортлиста, но не больше — см. DECISIONS.md Round 13
        lines = generate.generate(tags, n=max(2000, knobs["shortlist"] * 50))

    try:
        result = filters.run(lines, knobs, corpus, nl_fragments=nl_fragments,
                             rhyme=rhyme, tags=tags, forced=forced, stanza=spec, стоп=стоп)
    except filters._Остановлено:
        # ЗДЕСЬ уходит почти всё время текста (замер: 101 секунда из 102), и
        # именно поэтому остановка спрашивается внутри отбора, а не только
        # между пулами. Переводим в своё исключение: наружу должно выйти одно
        # понятие «остановлено», а не два.
        raise Остановлено()
    shortlist = result["shortlist"]

    stanzas = []
    for i in range(len(shortlist) // length):
        rows = [{"text": r["text"], "rhyme": r.get("rhyme") or "",
                 "syllables": r.get("syllables"), "lemmas": list(r.get("lemmas") or [])}
                for r in shortlist[i * length:(i + 1) * length]]
        lemmas = set()
        for row in rows:
            lemmas |= set(row["lemmas"])
        forced_words = {w for w in forced
                        if any(w in _tokens(row["text"]) for row in rows)}
        stanzas.append({"rows": rows, "rank": i, "lemmas": lemmas,
                        "forced_words": forced_words, "forced": bool(forced_words),
                        "id": (link["key"], i)})
    return stanzas


def build_pools(links: list[dict], tags: list, forced: set, pool_per_link: int,
                corpus, nl_fragments: list, progress=None, стоп=None) -> dict:
    """{key профиля: [строфы]} — один прогон на уникальный профиль, повторные
    вхождения в цепочке делят пул (уникальность строфы в комбо это учитывает:
    id строфы включает ключ профиля, см. assemble)."""
    pools: dict = {}
    uniq: list[dict] = []
    for link in links:
        # Звено-повтор наследует ключ двойника, поэтому в `pools` уже попало
        # (и попало бы даже без этой строки — но пусть будет видно, что за
        # припев генерация не платит).
        if link.get("repeat_of") is not None:
            continue
        if link["key"] not in pools:
            pools[link["key"]] = []   # заполнится ниже; ключ фиксирует уникальность
            uniq.append(link)
    for i, link in enumerate(uniq):
        if стоп and стоп():
            raise Остановлено()
        pools[link["key"]] = _build_one_pool(link, tags, forced, pool_per_link,
                                             corpus, nl_fragments, стоп)
        if progress:
            progress(i + 1, len(uniq))
    return pools


# ---------------------------------------------------------------------------
# 3. Оценка склейки
# ---------------------------------------------------------------------------

def _rhyme_tier(prev_row: dict, next_row: dict) -> float:
    """Ярус совпадения рифмо-ключей граничных строк. Одинаковое последнее
    слово — не рифма, а повтор (то же правило, что filters._rhymes)."""
    k1, k2 = prev_row.get("rhyme") or "", next_row.get("rhyme") or ""
    if not k1 or not k2:
        return 0.0
    if filters._last_word(prev_row.get("text", "")) == filters._last_word(next_row.get("text", "")):
        return 0.0
    if k1 == k2:
        return TIER_EXACT
    if k1[:_DEEP_PREFIX] == k2[:_DEEP_PREFIX]:
        return TIER_DEEP
    if k1[:_WEAK_PREFIX] == k2[:_WEAK_PREFIX]:
        return TIER_WEAK
    return 0.0


def _junction_score(kind: str, prev_row: dict, next_row: dict) -> float:
    """Балл одного стыка: последняя строка предыдущего звена против первой
    строки следующего — граница, которую слушатель реально слышит."""
    if kind == "свободно":
        return JUNCTION_FREE_SCORE
    if kind == "слом ритма":
        a, b = prev_row.get("syllables"), next_row.get("syllables")
        if a is None or b is None:
            return 0.0
        return min(1.0, abs(a - b) / BREAK_SATURATION)
    return _rhyme_tier(prev_row, next_row)   # 'рифмовать стык' — дефолт


def _combo_score(q_sum: float, j_sum: float, rep_sum: float, n: int,
                 pairs: int | None = None, allow_repeats: bool = False) -> float:
    """Итоговый балл комбо из накопленных сумм. Все три слагаемых в [0,1]:
    качество — среднее по звеньям, стыки — среднее по стыкам (у одного звена
    стыков нет — компонент нейтрально равен 1: не за что штрафовать),
    повторы — средний Жаккар лемм по парам звеньев.

    `pairs` — сколько пар РЕАЛЬНО накоплено в `rep_sum`. Звено-повтор
    (`repeat_of`) в этот счёт не входит: его совпадение с двойником равно
    единице по определению, и считать это «повтором» значило бы штрафовать
    припев за то, что он припев. Без явного счётчика знаменатель C(n,2)
    разбавлял бы среднее тем сильнее, чем больше в песне припевов.

    `allow_repeats` (крутилка «Повтор» глобальных настроек прогона) убирает
    штраф целиком и раздаёт его вес качеству и стыкам — а не оставляет
    слагаемое нулём: нулевое слагаемое опустило бы ВСЕ баллы на 0.2 и сделало
    бы число несравнимым с прогоном без повторов.

    Пропорция снова КОНСТАНТЫ модуля (Раунд 50). Ручки для неё завели в
    Раунде 43 — «кто выбирает лучших и по каким признакам». Ответ оказался
    другим: пользователь 2026-08-03 — «качество строф я не понимаю, мне и так
    максимально качественные нужны»; «если я так стыки размечаю, зачем мне
    тут настройка стыков?». Качество и стыки нужны всегда максимальные, а
    единственная оставшаяся ручка «избегать повторов» — тот самый случай
    «если трогать, будет хуже»: сдвиг вверх выкидывает хорошие строфы за одно
    общее слово."""
    if pairs is None:
        pairs = n * (n - 1) // 2
    quality = q_sum / n if n else 0.0
    junction = j_sum / (n - 1) if n > 1 else 1.0
    if allow_repeats:
        доля = W_QUALITY + W_JUNCTION
        return (W_QUALITY / доля) * quality + (W_JUNCTION / доля) * junction
    repeats = rep_sum / pairs if pairs else 0.0
    return W_QUALITY * quality + W_JUNCTION * junction + W_REPEATS * (1.0 - repeats)


# ---------------------------------------------------------------------------
# 4. Склейка: beam слева направо, лучшие по баллу
# ---------------------------------------------------------------------------

def assemble(links: list[dict], pools: dict, junctions: list[str], runs: int,
             best: int, forced: set, progress=None,
             allow_repeats: bool = False, стоп=None) -> tuple[list[dict], dict]:
    """Beam слева направо по звеньям. Ширина ≈ runs/звенья: «прогонов» из
    панели — это бюджет оценённых сочетаний, а не число независимых полных
    прогонов (решение прожарки №4). Жёсткие условия — В МУСОР ДО БАЛЛА:
    одна строфа не стоит в двух звеньях (проверка при расширении), форс-
    слово присутствует хотя бы в одном звене (проверка на полном комбо —
    раньше конца цепочки слово ещё может появиться). Инкрементальный балл —
    стык с предыдущим звеном + повторы лемм со ВСЕМИ уже взятыми: у всех
    состояний одного уровня одна глубина, значит нормированный частичный
    балл сравним честно.

    ХУК (Раунд 52). «Строфа не встаёт дважды» перестало быть безусловным
    законом и стало правилом по умолчанию: звено с `repeat_of` СТАВИТ ту же
    самую строфу, что и его двойник, — и не выбирает её, а копирует. Пул при
    этом не перебирается вовсе (одно состояние вместо `plen`), то есть припев
    не только разрешён, но и дешевле обычного звена.

    `allow_repeats` — глобальная крутилка «Повтор» прогона: снимает штраф за
    общие леммы между строфами. Пользователь: «он не должен повторять только при
    соответствующих настройках, но если я хочу повторять, пусть повторяет»."""
    n_links = len(links)
    width = max(50, runs // max(1, n_links))
    evaluated = 0
    # Сколько пар звеньев реально попадёт в `rep_sum` к каждой глубине: пары с
    # участием звена-повтора не считаются (см. _combo_score). Считается по
    # структуре цепочки, а не по состоянию: структура у всех комбо одна.
    своих = 0
    pairs_at: list[int] = []
    for l in links:
        if l.get("repeat_of") is None:
            своих += 1
        pairs_at.append(своих * (своих - 1) // 2)

    # состояние: (picks, used_ids, q_sum, j_sum, rep_sum)
    beam: list[tuple] = [([], frozenset(), 0.0, 0.0, 0.0)]
    for li, link in enumerate(links):
        if стоп and стоп():
            raise Остановлено()
        pool = pools.get(link["key"]) or []
        plen = len(pool)
        expanded: list[tuple] = []
        повтор = link.get("repeat_of")
        for picks, used, q_sum, j_sum, rep_sum in beam:
            if повтор is not None:
                # Та же строфа, что у двойника. Стык считается честно (граница
                # звучит и здесь), качество — то же самое, а повторы не
                # копятся: совпадение припева с самим собой это не дефект.
                st = picks[повтор]
                evaluated += 1
                j = j_sum + (_junction_score(junctions[li - 1], picks[-1]["rows"][-1],
                                             st["rows"][0]) if li else 0.0)
                q = 1.0 - st["rank"] / plen if plen else 0.0
                expanded.append((picks + [st], used, q_sum + q, j, rep_sum))
                continue
            for st in pool:
                if st["id"] in used:
                    continue   # правило по умолчанию: строфа не встаёт дважды сама собой
                evaluated += 1
                q = 1.0 - st["rank"] / plen
                j = j_sum + (_junction_score(junctions[li - 1], picks[-1]["rows"][-1],
                                             st["rows"][0]) if li else 0.0)
                # Пары со звеньями-повторами пропускаем: их двойник ту же
                # самую пару уже дал, и считать её дважды значило бы штрафовать
                # куплет тем сильнее, чем чаще в песне звучит припев.
                r = rep_sum + sum(filters._j(st["lemmas"], picks[k]["lemmas"])
                                  for k in range(li) if links[k].get("repeat_of") is None)
                expanded.append((picks + [st], used | {st["id"]}, q_sum + q, j, r))
        depth = li + 1
        expanded.sort(key=lambda s: _combo_score(s[2], s[3], s[4], depth, pairs_at[li],
                                                 allow_repeats), reverse=True)
        beam = expanded[:width]
        if progress:
            progress(li + 1, n_links)
        if not beam:
            break   # пул пуст или исчерпан — комбо не собрать, честно наружу

    combos: list[dict] = []
    complete = 0
    for picks, used, q_sum, j_sum, rep_sum in beam:
        if len(picks) < n_links:
            continue
        complete += 1
        if forced:
            present: set = set()
            for p in picks:
                present |= p["forced_words"]
            if not set(forced) <= present:
                continue   # жёсткое условие: форс-слово так и не появилось — в мусор
        score = _combo_score(q_sum, j_sum, rep_sum, n_links,
                             pairs_at[-1] if pairs_at else 0, allow_repeats)
        lemmas: set = set()
        for p in picks:
            lemmas |= p["lemmas"]
        combos.append({"picks": picks, "score": score, "ids": set(used), "lemmas": lemmas})

    combos.sort(key=lambda c: c["score"], reverse=True)
    # Вариантов всегда один (Раунд 48); срез оставлен, чтобы `best` из
    # контракта не врал, если его когда-нибудь поднимут.
    chosen = combos[:best]
    funnel = {"evaluated": evaluated, "assembled": len(combos),
              "culled": complete - len(combos)}
    return chosen, funnel


# ---------------------------------------------------------------------------
# 5. Точка входа
# ---------------------------------------------------------------------------

def run_pipeline(spec: dict, corpus, nl_fragments: list | None = None,
                 progress=None, стоп=None) -> dict:
    """Весь прогон: spec — уже провалидированный clean.pipeline_spec.
    progress(done, total, detail) — колбэк для /api/status; detail —
    человеческая строка («пулы 2/3 · склейка 40%»), числа — общий ход."""
    t0 = time.time()
    notify = progress or (lambda done, total, detail: None)

    links = resolve_chain(spec["chain"], spec["knobs"])
    n_uniq = len({l["key"] for l in links if l.get("repeat_of") is None})
    total_units = n_uniq + len(links)

    def pool_progress(done, total):
        notify(done, total_units, f"пулы {done}/{total}")

    pools = build_pools(links, spec["tags"], spec["forced"], spec["pool_per_link"],
                        corpus, nl_fragments or [], progress=pool_progress, стоп=стоп)

    def asm_progress(done, total):
        pct = round(100 * done / total) if total else 100
        notify(n_uniq + done, total_units, f"пулы {n_uniq}/{n_uniq} · склейка {pct}%")

    chosen, funnel = assemble(links, pools, spec["junctions"], spec["runs"],
                              spec["best"], spec["forced"], progress=asm_progress,
                              # «Повтор» — свойство ВСЕЙ цепочки, поэтому берётся
                              # из глобальных крутилок прогона, а не из звена:
                              # штраф считается по парам звеньев, и «у второго
                              # куплета повтор разрешён, у третьего нет» не
                              # значило бы ничего.
                              allow_repeats=int(spec["knobs"].get("repeat", 0) or 0) >= 1,
                              стоп=стоп)

    variants = []
    for i, combo in enumerate(chosen):
        score = round(combo["score"], 4)
        variants.append({
            "id": f"var{i + 1:02d}",
            "title": f"вариант {i + 1:02d} · {score:.2f}",
            "score": score,
            # `title` пустой — секция без заголовка: фронт не рисует строку
            # «строфа» просто потому, что заголовок нечем не заполнить
            "sections": [{"title": links[k]["title"], "lines": combo["picks"][k]["rows"]}
                         for k in range(len(links))],
        })

    funnel["pools"] = [{"title": l["title"], "form": l["form"],
                        "stanzas": len(pools.get(l["key"]) or [])} for l in links]
    funnel["best"] = len(variants)
    funnel["elapsed_ms"] = int((time.time() - t0) * 1000)
    return {"variants": variants, "funnel": funnel}
