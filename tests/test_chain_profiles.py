# nakedlunch — третья полка: ЦЕПОЧКИ СЛЕПКАМИ (Раунд 50).
#
# Пользователь 2026-08-03: «цепочка хранит копии — правишь профиль, старые цепочки
# не трогаются… готовое решение навсегда такое, каким ты его услышал и
# сохранил». И отдельно: «почему она не хранит референс? Либо, если пустой
# референс, пустоту этого референса — почему не хранит?»
#
# Проверяется то, ради чего слепок и заводился: правка полки строф НЕ меняет
# сохранённую цепочку, и восстановление возвращает референс в точности — в том
# числе пустой, иначе ползунок референтности молча переразметит цепочку по
# чужому тексту.
#
# Прогон: .venv/bin/python -m pytest tests/test_chain_profiles.py -q

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import chain_profiles
import clean
import pipeline

КАТРЕН = [{"letter": c, "min_syl": 8, "max_syl": 9} for c in "абаб"]
ДВУСТИШИЕ = [{"letter": "а", "min_syl": 6, "max_syl": 9}] * 2


def цепочка(**over):
    d = {
        "name": "Ночной панк",
        "links": [
            {"title": "Куплет", "form": "Катрен перекрёстный", "spec": КАТРЕН,
             "knobs_profile": "Обычный", "params": {"Банальность": 0.15}},
            {"title": "", "form": "Двустишие", "spec": ДВУСТИШИЕ,
             "knobs_profile": "Классика", "mode": clean.MODE_CLASSIC},
        ],
        "junctions": ["рифмовать стык"],
        "reference": {"text": "первая строка\nвторая строка", "pct": 0.6},
    }
    d.update(over)
    return d


@pytest.fixture()
def свой_каталог(tmp_path, monkeypatch):
    monkeypatch.setattr(chain_profiles, "DATA_DIR", tmp_path)
    monkeypatch.setattr(chain_profiles, "PROFILES_PATH", tmp_path / "chain_profiles.json")
    return tmp_path


# ---- слепок, а не ссылки ----------------------------------------------------

def test_zveno_hranit_kopiyu_karkasa(свой_каталог):
    """Смысл слепка: имя формы — подпись, каркас — копия. Правка полки строф
    сохранённое решение не трогает."""
    chain_profiles.save(цепочка())
    c = chain_profiles.by_name("Ночной панк")
    assert [r["letter"] for r in c["links"][0]["spec"]] == list("абаб")
    assert c["links"][0]["form"] == "Катрен перекрёстный"      # только подпись
    assert len(c["links"][1]["spec"]) == 2


def test_kopiya_glavnee_imeni_formy(monkeypatch):
    """Если бы главным было имя, звено взяло бы форму с ПОЛКИ и решение
    зазвучало бы иначе после её правки. Проверяем по результату: спека звена
    побеждает одноимённую форму полки."""
    monkeypatch.setattr(pipeline.settings_mod, "read", lambda: {})
    # полка врёт: под именем «Катрен перекрёстный» лежит двустишие
    monkeypatch.setattr(pipeline.stanza_profiles, "builtin",
                        lambda: [{"name": "Катрен перекрёстный", "lines": ДВУСТИШИЕ}])
    monkeypatch.setattr(pipeline.stanza_profiles, "custom", lambda: [])
    spec = clean.pipeline_spec({"chain": [
        {"title": "Куплет", "form": "Катрен перекрёстный", "spec": КАТРЕН}]})
    link, = pipeline.resolve_chain(spec["chain"], clean.knobs(None))
    assert len(link["spec"]) == 4, "копия звена обязана побеждать полку"
    assert link["form"] == "Катрен перекрёстный", "имя остаётся подписью"


def test_svoya_stroфa_bez_imeni_podpisyvaetsya_chestno(monkeypatch):
    monkeypatch.setattr(pipeline.settings_mod, "read", lambda: {})
    spec = clean.pipeline_spec({"chain": [{"spec": КАТРЕН}]})
    link, = pipeline.resolve_chain(spec["chain"], clean.knobs(None))
    assert link["form"] == "своя строфа"


# ---- референс — часть слепка, включая пустой -------------------------------

def test_referens_hranitsya_celikom(свой_каталог):
    chain_profiles.save(цепочка())
    c = chain_profiles.by_name("Ночной панк")
    assert c["reference"]["text"] == "первая строка\nвторая строка"
    assert c["reference"]["pct"] == 0.6


def test_pustoy_referens_eto_znachenie_a_ne_otsutstvie(свой_каталог):
    """Пользователь: «либо, если пустой референс, пустоту этого референса почему не
    хранит?». Пустой текст значит «собрано руками» — и восстановление обязано
    ОЧИСТИТЬ поле, иначе на экране повиснет чужой референс, а сдвиг ползунка
    переразметит цепочку по нему без отката."""
    chain_profiles.save(цепочка(name="Руками", reference={"text": "", "pct": 1.0}))
    c = chain_profiles.by_name("Руками")
    assert "reference" in c and c["reference"]["text"] == ""
    assert c["reference"]["pct"] == 1.0


def test_referens_voobshche_ne_prislan(свой_каталог):
    chain_profiles.save(цепочка(name="Без ключа", reference=None))
    assert chain_profiles.by_name("Без ключа")["reference"] == {"text": "", "pct": 1.0}


def test_procent_klampitsya(свой_каталог):
    chain_profiles.save(цепочка(name="Мусор", reference={"text": "т", "pct": "чушь"}))
    assert chain_profiles.by_name("Мусор")["reference"]["pct"] == 1.0
    chain_profiles.save(цепочка(name="Выше", reference={"text": "т", "pct": 9}))
    assert chain_profiles.by_name("Выше")["reference"]["pct"] == 1.0


# ---- проверка ДО записи ----------------------------------------------------

def test_bez_imeni_i_bez_zvenev_otvergaetsya(свой_каталог):
    with pytest.raises(clean.BadInput):
        chain_profiles.save(цепочка(name=""))
    with pytest.raises(clean.BadInput):
        chain_profiles.save(цепочка(links=[]))
    # звено без каркаса — не звено: восстанавливать нечего
    with pytest.raises(clean.BadInput):
        chain_profiles.save(цепочка(links=[{"title": "Куплет", "form": "Катрен"}]))


def test_bitoe_zveno_vybrasyvaetsya_a_sosednie_zhivut(свой_каталог):
    c = clean.chain_profile(цепочка(links=[
        {"title": "Живое", "spec": КАТРЕН}, {"title": "Битое"}]))
    assert [l["title"] for l in c["links"]] == ["Живое"]


def test_styki_dobivayutsya_i_obrezayutsya(свой_каталог):
    chain_profiles.save(цепочка(junctions=["слом ритма", "лишний", "хвост"]))
    assert chain_profiles.by_name("Ночной панк")["junctions"] == ["слом ритма"]
    chain_profiles.save(цепочка(name="Пусто", junctions=[]))
    assert chain_profiles.by_name("Пусто")["junctions"] == ["рифмовать стык"]


def test_perezapis_po_imeni_i_udalenie(свой_каталог):
    chain_profiles.save(цепочка())
    chain_profiles.save(цепочка(junctions=["свободно"]))
    свои = chain_profiles.custom()
    assert len(свои) == 1 and свои[0]["junctions"] == ["свободно"]
    chain_profiles.delete("Ночной панк")
    assert chain_profiles.custom() == []


def test_bityy_fayl_eto_pustaya_polka(свой_каталог):
    (свой_каталог / "chain_profiles.json").write_text("[{сломано", "utf-8")
    assert chain_profiles.custom() == []


def test_rezhim_zvena_perezhivaet_krug(свой_каталог):
    """Классическое звено внутри цепочки — законный случай: куплеты алгоритмом,
    бридж сырой нарезкой."""
    chain_profiles.save(цепочка())
    c = chain_profiles.by_name("Ночной панк")
    assert c["links"][0]["mode"] == clean.MODE_ALGO
    assert c["links"][1]["mode"] == clean.MODE_CLASSIC
    assert c["links"][0]["params"]["Банальность"] == 0.15
