# extendo — тесты пайплайна (ФАЗА 1: пулы по звеньям + комбинаторная склейка,
# core/pipeline.py + clean.pipeline_spec + POST /api/pipeline/run). Без
# полного пула: build_pools подменяется синтетическими строфами с
# рукодельными rhyme/syllables/lemmas — проверяется ОЦЕНКА СКЛЕЙКИ и
# контракт, а не генерация (у неё свои тесты и живая проверка).
# Прогон: .venv/bin/python -m pytest tests/test_pipeline.py -q

import importlib.util
import re
import sys
from pathlib import Path

import pytest
from conftest import нет_словаря_рифм, нет_векторов  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

import clean
import pipeline


# ---------------------------------------------------------------------------
# синтетика: строки и строфы с рукодельными rhyme/syllables/lemmas
# ---------------------------------------------------------------------------

def row(text="тестовая строка", rhyme="ана", syllables=8, lemmas=("тест",)):
    return {"text": text, "rhyme": rhyme, "syllables": syllables, "lemmas": list(lemmas)}


def stanza(key, rank, rows, forced_words=()):
    lemmas = set()
    for r in rows:
        lemmas |= set(r["lemmas"])
    return {"rows": rows, "rank": rank, "lemmas": lemmas,
            "forced_words": set(forced_words), "forced": bool(forced_words),
            "id": (key, rank)}


def link(title, key, form="тест-форма"):
    # минимальное звено для assemble (spec/knobs нужны только build_pools).
    # Раунд 50: у звена `title` — заголовок секции, а не роль: роль больше не
    # выбирает форму и не двигает крутилки.
    return {"title": title, "form": form, "key": key}


# Звено обязано принести каркас (Раунд 50): роль его больше не назначает.
КАТРЕН = "Катрен перекрёстный"
КОЛЬЦО = "Катрен кольцевой"


def spec_defaults(**over):
    payload = {"chain": [{"title": "Куплет", "form": КАТРЕН},
                         {"title": "Припев", "form": КОЛЬЦО}]}
    payload.update(over)
    return clean.pipeline_spec(payload)


# ---------------------------------------------------------------------------
# ярусы стыка «рифмовать стык»
# ---------------------------------------------------------------------------

def test_rhyme_junction_tiers_move_score_in_order():
    base = row("глубокая рана", rhyme="ана", lemmas=["рана"])
    exact = row("ночная охрана", rhyme="ана", lemmas=["охрана"])       # полный ключ
    deep = row("гудят барабаны", rhyme="анах", lemmas=["барабан"])     # 3 символа
    weak = row("пустая карта", rhyme="арта", lemmas=["карта"])         # ударная гласная
    none = row("холодный лёд", rhyme="от", lemmas=["лёд"])             # ничего общего

    s = lambda nxt: pipeline._junction_score("рифмовать стык", base, nxt)
    assert s(exact) == pipeline.TIER_EXACT == 1.0
    assert s(deep) == pipeline.TIER_DEEP == 0.7
    assert s(weak) == pipeline.TIER_WEAK == 0.4
    assert s(none) == 0.0
    assert s(exact) > s(deep) > s(weak) > s(none)


def test_rhyme_junction_same_last_word_is_repeat_not_rhyme():
    a = row("глубокая рана", rhyme="ана", lemmas=["рана"])
    b = row("сквозная рана", rhyme="ана", lemmas=["рана"])
    assert pipeline._junction_score("рифмовать стык", a, b) == 0.0


def test_rhyme_junction_missing_key_scores_zero():
    a = row("строка", rhyme="", lemmas=["строка"])
    b = row("другая", rhyme="ая", lemmas=["другой"])
    assert pipeline._junction_score("рифмовать стык", a, b) == 0.0


# ---------------------------------------------------------------------------
# «слом ритма» и «свободно»
# ---------------------------------------------------------------------------

def test_rhythm_break_grows_with_syllable_contrast():
    base = row(syllables=8)
    s = lambda n: pipeline._junction_score("слом ритма", base, row(syllables=n))
    assert s(8) == 0.0
    assert s(9) == pytest.approx(1 / 3)
    assert s(10) == pytest.approx(2 / 3)
    assert s(11) == 1.0
    assert s(3) == 1.0                     # насыщение: дальше трёх слогов не растёт
    assert s(8) < s(9) < s(10) <= s(11)


def test_free_junction_is_neutral_constant():
    a, b = row(syllables=4, rhyme="xx"), row(syllables=12, rhyme="уу")
    assert pipeline._junction_score("свободно", a, b) == pipeline.JUNCTION_FREE_SCORE == 0.7


# ---------------------------------------------------------------------------
# штраф повторов лемм между звеньями
# ---------------------------------------------------------------------------

def test_repeat_penalty_prefers_lemma_distinct_combo():
    # B качественнее (rank 0 против rank 1), но дублирует леммы A; при весах
    # 0.5/0.3/0.2 штраф повторов (0.2) перевешивает разницу качества (0.125)
    A = stanza("k1", 0, [row("ночь и тьма кругом", "ом", 6, ["ночь", "тьма"])])
    B = stanza("k2", 0, [row("тьма и ночь опять", "ять", 6, ["ночь", "тьма"])])
    C = stanza("k2", 1, [row("свет и день во всём", "ём", 6, ["свет", "день"])])

    chosen, funnel = pipeline.assemble(
        [link("Куплет", "k1"), link("Припев", "k2")],
        {"k1": [A], "k2": [B, C]},
        ["свободно"], runs=1000, best=10, forced=set())
    assert funnel["assembled"] == 2
    assert chosen[0]["picks"][1]["id"] == ("k2", 1)   # лемма-чистое комбо выше
    assert chosen[0]["score"] > chosen[1]["score"]


# ---------------------------------------------------------------------------
# жёсткие условия: уникальность строфы, форс-слово
# ---------------------------------------------------------------------------

def test_same_stanza_never_stands_in_two_links():
    # один профиль в двух звеньях = общий пул; единственная строфа не может
    # закрыть оба звена — комбо не собирается вовсе, а не дублируется
    A = stanza("k1", 0, [row("одна строфа", "офа", 4, ["строфа"])])
    chosen, funnel = pipeline.assemble(
        [link("Куплет", "k1"), link("Куплет", "k1")],
        {"k1": [A]},
        ["свободно"], runs=1000, best=10, forced=set())
    assert chosen == []
    assert funnel["assembled"] == 0

    # а с двумя строфами в пуле оба звена берут РАЗНЫЕ
    B = stanza("k1", 1, [row("вторая строфа", "офа", 5, ["второй"])])
    chosen, _ = pipeline.assemble(
        [link("Куплет", "k1"), link("Куплет", "k1")],
        {"k1": [A, B]},
        ["свободно"], runs=1000, best=10, forced=set())
    for combo in chosen:
        ids = [p["id"] for p in combo["picks"]]
        assert len(ids) == len(set(ids))


def test_forced_word_required_somewhere_in_combo():
    A = stanza("k1", 0, [row("без слова", "ова", 4, ["ничто"])])
    B = stanza("k2", 0, [row("тоже без", "ес", 3, ["пусто"])])
    C = stanza("k2", 1, [row("вот деньги мои", "ои", 5, ["деньга"])],
               forced_words={"деньги"})

    chosen, funnel = pipeline.assemble(
        [link("Куплет", "k1"), link("Хук", "k2")],
        {"k1": [A], "k2": [B, C]},
        ["свободно"], runs=1000, best=10,
        forced={"деньги"})
    assert len(chosen) == 1                             # A+B — в мусор до балла
    assert chosen[0]["picks"][1]["id"] == ("k2", 1)
    assert funnel["culled"] == 1

    # форс-слова нет нигде в пулах → честно пусто, не тихая подмена
    chosen, funnel = pipeline.assemble(
        [link("Куплет", "k1"), link("Хук", "k2")],
        {"k1": [A], "k2": [B]},
        ["свободно"], runs=1000, best=10,
        forced={"деньги"})
    assert chosen == [] and funnel["assembled"] == 0


# ---------------------------------------------------------------------------
# отбор лучших по баллу (Раунд 50: порога и MMR-разнообразия больше нет)
# ---------------------------------------------------------------------------

def _rank_pool(key, lemma_sets):
    return [stanza(key, i, [row(f"строфа {i}", "ана", 8, lems)])
            for i, lems in enumerate(lemma_sets)]


def test_lucshie_po_ballu_bez_poroga():
    """Порог отсева вырезан (Раунд 50): фронт не слал его ни разу, дефолт 0.0
    не отсекал ничего, а сохранённые профили несли 0.35 — он резал выдачу почти
    в ноль в первом же живом прогоне. Теперь просто лучшие по баллу."""
    pools = {"k1": _rank_pool("k1", [["а1"], ["б1"], ["в1"]])}
    links = [link("Куплет", "k1")]
    все, f = pipeline.assemble(links, pools, [], 1000, 10, set())
    assert f["assembled"] == 3 and len(все) == 3
    assert f["culled"] == 0
    # порядок — строго по убыванию балла
    assert [round(c["score"], 4) for c in все] == sorted(
        (round(c["score"], 4) for c in все), reverse=True)

    один, _ = pipeline.assemble(links, pools, [], 1000, 1, set())
    assert len(один) == 1 and один[0]["score"] == все[0]["score"]


def test_v_kontrakte_net_poroga_i_raznoobraziya():
    """Разнообразие мертво с Раунда 48 (вариант всегда один — разнообразить
    нечего), порог и веса склейки — с Раунда 50."""
    spec = spec_defaults()
    for мёртвое in ("threshold", "variety", "weights"):
        assert мёртвое not in spec, f"{мёртвое} обязан был уйти из контракта"
    assert not hasattr(pipeline, "_mmr_pick")
    assert not hasattr(pipeline, "_combo_sim")


# ---------------------------------------------------------------------------
# clean.pipeline_spec — клампы и честные отказы
# ---------------------------------------------------------------------------

def test_pipeline_spec_defaults():
    spec = spec_defaults()
    assert spec["runs"] == 5000 and spec["pool_per_link"] == 50
    assert spec["best"] == 1                            # вариант всегда один
    assert spec["junctions"] == ["рифмовать стык"]      # звеньев−1, дефолт
    assert spec["tags"] == [] and spec["forced"] == set()
    # `repeat_of` — Раунд 52 (хук): звено может быть повтором более раннего.
    # У обычного звена оно None, и это часть контракта, а не необязательное
    # поле: pipeline.resolve_chain читает его у КАЖДОГО звена.
    assert set(spec["chain"][0]) == {"title", "form", "spec", "knobs_own", "repeat_of"}
    assert spec["chain"][0]["repeat_of"] is None


def test_pipeline_spec_clamps_garbage():
    spec = spec_defaults(
        runs=10**9, best=999, pool_per_link=1,
        junctions=["чушь", "лишний", "хвост"],
        chain=[{"title": "Куплет" * 40, "form": КАТРЕН}, {"title": "Хук", "form": КОЛЬЦО}])
    assert spec["runs"] == 200000 and spec["best"] == 50
    assert spec["pool_per_link"] == 10
    assert spec["junctions"] == ["рифмовать стык"]      # обрезано до звеньев−1
    assert len(spec["chain"][0]["title"]) == 48          # заголовок обрезан, не отвергнут

    spec = spec_defaults(runs="мусор", best=0, pool_per_link=999)
    assert spec["runs"] == 5000 and spec["best"] == 1
    assert spec["pool_per_link"] == 120


def test_pipeline_spec_junctions_padded_and_kept():
    spec = spec_defaults(chain=[{"role": "а"}, {"role": "б"}, {"role": "в"}],
                         junctions=["слом ритма"])
    assert spec["junctions"] == ["слом ритма", "рифмовать стык"]


def test_pipeline_spec_theme_and_forced():
    spec = spec_defaults(theme="!деньги, ночь")
    assert spec["tags"] == ["деньги", "ночь"]
    assert spec["forced"] == {"деньги"}


def test_pipeline_spec_hard_errors():
    with pytest.raises(clean.BadInput):
        clean.pipeline_spec({"chain": []})
    with pytest.raises(clean.BadInput):
        clean.pipeline_spec({"chain": [{"form": КАТРЕН}] * 13})
    with pytest.raises(clean.BadInput):
        clean.pipeline_spec({"chain": "не список"})
    with pytest.raises(clean.BadInput):
        clean.pipeline_spec({"chain": ["не объект"]})
    with pytest.raises(clean.BadInput):
        clean.pipeline_spec({"theme": "$$$", "chain": [{"form": КАТРЕН}]})


def test_pustoy_zagolovok_eto_ne_oshibka():
    """Заголовок необязателен: раньше пустая роль была BadInput, и фронт из-за
    этого ВСЕГДА подставлял непустое значение — в документе появлялась строка
    «строфа» там, где владелец выбрал «без заголовка»."""
    spec = clean.pipeline_spec({"chain": [{"title": "", "form": КАТРЕН}]})
    assert spec["chain"][0]["title"] == ""


# ---------------------------------------------------------------------------
# resolve_chain — звено приносит СВОЁ (Раунд 50: ролей больше нет)
# ---------------------------------------------------------------------------

def test_rol_bolshe_ne_vliyaet_na_generaciyu(monkeypatch):
    """Раньше слово «Припев» тайно назначало форму строфы (аабб 6-8) и двигало
    крутилки (cohesion +0.2, точность +0.15) — при том что в интерфейсе под
    ним было написано «на генерацию не влияет». Теперь это правда."""
    monkeypatch.setattr(pipeline.settings_mod, "read", lambda: {})
    base = clean.knobs(None)
    spec = spec_defaults(chain=[{"title": "Куплет", "form": КАТРЕН},
                                {"title": "Припев", "form": КАТРЕН},
                                {"title": "Хук", "form": КАТРЕН},
                                {"title": "", "form": КАТРЕН}])
    links = pipeline.resolve_chain(spec["chain"], base)
    # одна форма на всех — значит и каркас, и крутилки, и ключ пула совпадают
    assert {tuple(r["letter"] for r in l["spec"]) for l in links} == {tuple("абаб")}
    assert {l["knobs"]["cohesion"] for l in links} == {base["cohesion"]}
    assert {l["knobs"]["rhyme_precision"] for l in links} == {base["rhyme_precision"]}
    assert len({l["key"] for l in links}) == 1
    # заголовок доезжает как есть, включая пустой
    assert [l["title"] for l in links] == ["Куплет", "Припев", "Хук", ""]
    assert not hasattr(pipeline, "DEFAULT_ROLE_FORMS")
    assert not hasattr(pipeline, "DEFAULT_ROLE_DELTAS")


def test_perenesyonnye_formy_zhivy_na_polke():
    """Двустишие и укороченный парный катрен жили ТОЛЬКО в таблице ролей.
    Вместе с ней они исчезли бы из проекта: двустиший в датасете не было."""
    имена = {p["name"] for p in pipeline.stanza_profiles.builtin()}
    assert {"Двустишие", "Катрен парный короткий"} <= имена
    формы = {p["name"]: p["lines"] for p in pipeline.stanza_profiles.builtin()}
    assert len(формы["Двустишие"]) == 2
    assert [r["letter"] for r in формы["Двустишие"]] == ["а", "а"]
    assert [r["letter"] for r in формы["Катрен парный короткий"]] == list("аабб")


def test_imenovannaya_forma_i_obshchiy_pul(monkeypatch):
    monkeypatch.setattr(pipeline.settings_mod, "read", lambda: {})
    base = clean.knobs(None)
    spec = spec_defaults(chain=[{"title": "Бридж", "form": КОЛЬЦО},
                                {"title": "Куплет", "form": КАТРЕН},
                                {"title": "Куплет", "form": КАТРЕН}])
    links = pipeline.resolve_chain(spec["chain"], base)
    assert [r["letter"] for r in links[0]["spec"]] == list("абба")
    assert links[1]["key"] == links[2]["key"]           # один профиль → один пул
    assert links[0]["key"] != links[1]["key"]

    with pytest.raises(clean.BadInput):
        pipeline.resolve_chain(
            spec_defaults(chain=[{"form": "Нет такой формы"}])["chain"], base)


def test_zveno_bez_karkasa_padaet_chestno(monkeypatch):
    """Тихого «дефолта куплета» больше нет: он превращал всю цепочку в шесть
    одинаковых строф, и понять это можно было только по выдаче."""
    monkeypatch.setattr(pipeline.settings_mod, "read", lambda: {})
    with pytest.raises(clean.BadInput):
        pipeline.resolve_chain(clean.pipeline_spec({"chain": [{"title": "х"}]})["chain"],
                               clean.knobs(None))


def test_zveno_neset_absolyutnye_krutilki(monkeypatch):
    """РЕГРЕССИЯ. Раньше звено получало dict(base_knobs), и поверх ложился
    clean.knobs(item['knobs']) — а он возвращает ПОЛНЫЙ словарь с дефолтами.
    Звено, принёсшее хоть один свой кноб, молча сбрасывало classic в 0:
    бинарная классика в цепочке из референса выключалась бы сама."""
    monkeypatch.setattr(pipeline.settings_mod, "read", lambda: {})
    глобально = clean.knobs({"classic": 1.0, "melody": 0.9})
    spec = spec_defaults(chain=[
        {"form": КАТРЕН, "knobs": {"clausula": 2}},     # своё — абсолютное
        {"form": КАТРЕН},                                # своего нет — глобальное
    ])
    своё, глоб = pipeline.resolve_chain(spec["chain"], глобально)
    assert своё["knobs"]["clausula"] == 2
    assert своё["knobs"]["classic"] == 0.0, "классика звена — своя, а не унаследованная"
    assert глоб["knobs"]["classic"] == 1.0 and глоб["knobs"]["melody"] == 0.9


def test_klyuch_pula_uchityvaet_vorota(monkeypatch):
    """РЕГРЕССИЯ. В ключ входили только cohesion/melody/banality/rhyme_precision.
    Два звена с одинаковым каркасом и разной клаузулой (или матом, или режимом)
    молча делили ОДИН пул — и второе получало строфы по чужим воротам."""
    monkeypatch.setattr(pipeline.settings_mod, "read", lambda: {})
    base = clean.knobs(None)
    for ворота in ({"clausula": 2}, {"mat_share": 1.0}, {"classic": 1.0},
                   {"flow": 0.4}, {"real_text": 0.0}):
        spec = spec_defaults(chain=[{"form": КАТРЕН},
                                    {"form": КАТРЕН, "knobs": ворота}])
        a, b = pipeline.resolve_chain(spec["chain"], base)
        assert a["key"] != b["key"], f"{ворота} не различает звенья — пул поделится молча"


# ---------------------------------------------------------------------------
# Flask: 409 на занятом замке + полный happy-path с подменёнными пулами
# ---------------------------------------------------------------------------

_SERVER = None


@pytest.fixture()
def server_mod():
    """api/server.py с заглушками ТЯЖЁЛЫХ загрузок до импорта: state.json
    nakedlunch — 500MB+, nl_rhyme.json — ~950MB, navec — сотни МБ; тестам
    пайплайна всё это не нужно (build_pools подменяется). Импорт один раз
    на процесс — Flask-приложение и замок дальше переиспользуются."""
    global _SERVER
    if _SERVER is None:
        import embeddings
        import filters
        import generate
        import nlbridge
        saved = (nlbridge.open_store, filters.warm_caches,
                 embeddings.warm_caches, generate.warm_caches)
        nlbridge.open_store = lambda: None
        filters.warm_caches = lambda: None
        embeddings.warm_caches = lambda: None
        generate.warm_caches = lambda: None
        try:
            spec = importlib.util.spec_from_file_location(
                "extendo_test_server", ROOT / "api" / "server.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            (nlbridge.open_store, filters.warm_caches,
             embeddings.warm_caches, generate.warm_caches) = saved
        _SERVER = mod
    return _SERVER


def test_busy_lock_returns_409(server_mod):
    client = server_mod.app.test_client()
    assert server_mod._PIPELINE_LOCK.acquire(blocking=False)
    try:
        resp = client.post("/api/pipeline/run", json={"chain": [{"role": "Куплет"}]})
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "прогон уже идёт"}
    finally:
        server_mod._PIPELINE_LOCK.release()


def test_bad_request_is_russian_400(server_mod):
    client = server_mod.app.test_client()
    resp = client.post("/api/pipeline/run", json={"chain": []})
    assert resp.status_code == 400
    assert "звень" in resp.get_json()["error"]


def test_happy_path_contract(server_mod, monkeypatch):
    # `стоп` — Раунд 55: остановка серии посреди текста. Двойник обязан
    # принимать её тоже, иначе он расходится с настоящей сигнатурой и тест
    # начинает проверять другую функцию.
    def fake_build_pools(links, tags, forced, pool_per_link, corpus,
                         nl_fragments, progress=None, стоп=None):
        pools = {}
        for lk in links:
            if lk["key"] in pools:
                continue
            length = len(lk["spec"])
            pools[lk["key"]] = [
                stanza(lk["key"], rank,
                       [row(f"{lk['title']} {rank}-{j}", rhyme=f"ан{j}",
                            syllables=8, lemmas=[f"{lk['title']}-{rank}-{j}"])
                        for j in range(length)])
                for rank in range(3)]
        if progress:
            progress(len(pools), len(pools))
        return pools

    monkeypatch.setattr(server_mod.pipeline, "build_pools", fake_build_pools)
    monkeypatch.setattr(server_mod.stats_mod, "log", lambda *a, **kw: None)

    client = server_mod.app.test_client()
    resp = client.post("/api/pipeline/run", json={
        "theme": "",
        "chain": [{"title": "Куплет", "form": КАТРЕН},
                  {"title": "Припев", "form": КОЛЬЦО}],
        "junctions": ["свободно"],
        "runs": 200, "best": 3, "pool_per_link": 10,
    })
    assert resp.status_code == 200
    data = resp.get_json()

    # --- variants: дословно по контракту ---
    assert len(data["variants"]) == 3
    for i, v in enumerate(data["variants"]):
        assert isinstance(v["id"], str) and v["id"]
        assert re.fullmatch(r"вариант \d{2} · \d\.\d{2}", v["title"])
        assert isinstance(v["score"], float)
        assert [s["title"] for s in v["sections"]] == ["Куплет", "Припев"]
        for section in v["sections"]:
            for ln in section["lines"]:
                assert set(ln) == {"text", "rhyme", "syllables", "lemmas"}
    assert data["variants"][0]["title"] == f"вариант 01 · {data['variants'][0]['score']:.2f}"

    # --- funnel: дословно по контракту ---
    f = data["funnel"]
    assert set(f) == {"pools", "evaluated", "assembled", "best", "culled", "elapsed_ms"}
    assert f["pools"] == [{"title": "Куплет", "form": КАТРЕН, "stanzas": 3},
                          {"title": "Припев", "form": КОЛЬЦО, "stanzas": 3}]
    assert f["evaluated"] == 12          # уровень 1: 3 расширения, уровень 2: 3×3
    assert f["assembled"] == 9
    assert f["best"] == 3 and f["culled"] == 0
    assert isinstance(f["elapsed_ms"], int)

    # --- /api/status держит элемент пайплайна со state=done после прогона ---
    items = client.get("/api/status").get_json()["items"]
    pipe = [x for x in items if x["id"] == "pipeline"]
    assert pipe and pipe[0]["state"] == "done" and pipe[0]["label"] == "Пайплайн"


# --- Раунд 50: пропорция склейки снова константы ---------------------------
# Ручки завели в Раунде 43 («кто выбирает лучших и по каким признакам»). Ответ
# оказался другим: владелец 2026-08-03 — «качество строф я не понимаю, мне и
# так максимально качественные нужны»; «если я так стыки размечаю, зачем мне
# тут настройка стыков?»; «всё, что если трогать будет хуже, лучше убрать».

def test_proporciya_skleyki_snova_konstanty():
    assert "weights" not in clean.pipeline_spec({"chain": [{"form": КАТРЕН}]})
    import inspect
    assert "w" not in inspect.signature(pipeline._combo_score).parameters
    assert (pipeline.W_QUALITY, pipeline.W_JUNCTION, pipeline.W_REPEATS) == (0.5, 0.3, 0.2)


def test_tri_slagayemyh_dvigayut_ball():
    """Проверяем ФАКТ, а не наличие полей: каждое слагаемое двигает балл в
    свою сторону при прочих равных."""
    b = pipeline._combo_score(q_sum=1.0, j_sum=0.5, rep_sum=0.5, n=2)
    assert pipeline._combo_score(q_sum=1.8, j_sum=0.5, rep_sum=0.5, n=2) > b   # качество ↑
    assert pipeline._combo_score(q_sum=1.0, j_sum=1.0, rep_sum=0.5, n=2) > b   # стык ↑
    assert pipeline._combo_score(q_sum=1.0, j_sum=0.5, rep_sum=0.0, n=2) > b   # повторов меньше
    assert pipeline._combo_score(q_sum=1.0, j_sum=0.5, rep_sum=1.0, n=2) < b   # повторов больше


# --- Раунд 45: референс как вход пайплайна ---------------------------------

def test_refprofile_reads_structure():
    """Профиль снимается по частям: сколько строк, какая схема, сколько слогов.
    Проверяем на игрушечном тексте, где ответ известен глазами."""
    import refprofile
    текст = "кот сидел на окне\nпёс лежал во дворе\n\nночь была коротка\nтень была высока"
    p = refprofile.профиль(текст)
    assert p["частей"] == 2 and p["строк"] == 4
    assert [ч["строк"] for ч in p["части"]] == [2, 2]
    # обе пары рифмуются между собой — значит в каждой части одна буква
    assert all(len(set(ч["схема"])) == 1 for ч in p["части"])


@нет_векторов
def test_ref_percent_widens_and_softens():
    """Процент референтности — не украшение: на единице вилка узкая и клаузула
    воротами, на нуле от текста остаётся только каркас."""
    import refprofile
    текст = "кот сидел на окне\nпёс лежал во дворе\n\nночь была коротка\nтень была высока"
    p = refprofile.профиль(текст)
    жёстко = refprofile.цепочка(p, 1.0)["chain"][0]
    мягко = refprofile.цепочка(p, 0.0)["chain"][0]
    ш_ж = жёстко["spec"][0]["max_syl"] - жёстко["spec"][0]["min_syl"]
    ш_м = мягко["spec"][0]["max_syl"] - мягко["spec"][0]["min_syl"]
    assert ш_м > ш_ж, "на нуле вилка слогов обязана быть шире"
    # Раунд 51: звено носит крутилки в ИНТЕРФЕЙСНЫХ координатах ({mode, params}),
    # переводит их один переводчик на бэке. Раньше поле называлось `knobs` и в
    # него писали два производителя в двух несовместимых системах.
    assert "Клаузула" not in мягко["params"], "на нуле ворота клаузулы не ставятся"
    # Раунд 51: клаузула считается по НАСТОЯЩЕМУ ударению (словарь ruaccent),
    # а не по числу гласных в хвосте. У «окне́ / дворе́ / коротка́ / высока́»
    # ударение на последнем слоге — клаузула МУЖСКАЯ. Прежний измеритель
    # физически не мог вернуть ничего, кроме 1 и 2, и для любого
    # неодносложного слова отвечал 2 — этот тест был написан под ту ошибку.
    assert жёстко["params"]["Клаузула"] == 1, "на единице клаузула обязана быть воротами"
    assert мягко["mode"] == "алгоритм"
    # каркас держится на обоих концах — он и есть то, что даёт референс всегда
    assert len(жёстко["spec"]) == len(мягко["spec"]) == 2


def test_link_carries_own_spec_and_knobs():
    """Контракт: звено может принести свою спеку и свои кнобы (так референс и
    задаёт каждую часть отдельно), и они доезжают до resolve_chain."""
    spec = [{"letter": "а", "min_syl": 6, "max_syl": 8},
            {"letter": "а", "min_syl": 6, "max_syl": 8}]
    s = clean.pipeline_spec({"chain": [{"title": "строфа", "spec": spec,
                                        "params": {"Клаузула": 2, "Связность": 0.4}}]})
    assert s["chain"][0]["spec"] and len(s["chain"][0]["spec"]) == 2
    assert s["chain"][0]["knobs_own"]["clausula"] == 2
    links = pipeline.resolve_chain(s["chain"], s["knobs"])
    # Раунд 50: подпись «из референса» стала честнее — своя спека приезжает и
    # из слепка цепочки, где форму выбирали руками, поэтому имя, если оно
    # есть, остаётся подписью, а без имени пишем «своя строфа».
    assert links[0]["form"] == "своя строфа"
    assert links[0]["knobs"]["clausula"] == 2 and links[0]["knobs"]["flow"] == 0.4
