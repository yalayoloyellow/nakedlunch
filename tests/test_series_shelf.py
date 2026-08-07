# nakedlunch — ПОЛКА СЕРИЙ, четвёртый уровень (Раунд 53).
#
# Требование (2026-08-04): серия — уровень выше пайплайна: строфа, прогон пайплайна, серия..
#
# Модель повторяет ту, что уровнем ниже, и это не аналогия, а буквально тот же
# приём:
#   цепочка = [строфа с полки + профиль настроек]        → один текст
#   СЕРИЯ   = [альбом + тема + цепочка с полки + сколько] → папки с материалом
#
# Здесь ТОЛЬКО хранение. Прогон серии — отдельный механизм со своей очередью и
# раскладкой по папкам.
#
# Прогон: .venv/bin/python -m pytest tests/test_series_shelf.py -q

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import clean
import series as series_mod

ЗВЕНО = {"album": "Пепел", "theme": "дорога, ночь", "chain": "Куплет-припев", "count": 20}


@pytest.fixture()
def полка(tmp_path, monkeypatch):
    monkeypatch.setattr(series_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(series_mod, "SERIES_PATH", tmp_path / "series.json")
    return tmp_path


# ---- валидатор -------------------------------------------------------------

def test_zveno_bez_cepochki_ne_zveno():
    """Гнать нечего, а подставить «какую-нибудь» цепочку значит собрать не то."""
    assert clean.series_link({**ЗВЕНО, "chain": ""}) is None
    assert clean.series_link({**ЗВЕНО, "chain": "   "}) is None
    assert clean.series_link("не объект") is None


def test_tema_neobyazatelna():
    """Прогон без темы — обычное дело, и требовать её значило бы запретить
    половину того, чем пользователь пользуется."""
    з = clean.series_link({**ЗВЕНО, "theme": ""})
    assert з is not None and з["theme"] == ""


def test_imya_cepochki_ne_proveryaetsya_na_sushestvovanie():
    """Имя цепочки — ПОДПИСЬ, как имя формы строфы в звене цепочки. Полка
    цепочек живёт отдельно, и требовать её здесь значило бы, что серию нельзя
    написать раньше цепочки. Отсутствующая цепочка — ошибка ПРОГОНА."""
    з = clean.series_link({**ЗВЕНО, "chain": "Такой цепочки нет"})
    assert з["chain"] == "Такой цепочки нет"


@pytest.mark.parametrize("плохой", ["Серии/Пепел", ".скрытый", "../наружу"])
def test_krivoe_imya_alboma_chestnyy_otkaz(плохой):
    """Альбом — имя ПАПКИ. Проверяем при сохранении, а не при раскладке: иначе
    кривое имя обнаружилось бы среди ночи, на середине прогона."""
    with pytest.raises(clean.BadInput):
        clean.series_link({**ЗВЕНО, "album": плохой})


def test_kolichestvo_klampitsya():
    assert clean.series_link({**ЗВЕНО, "count": 0})["count"] == 1
    assert clean.series_link({**ЗВЕНО, "count": "чушь"})["count"] == 10
    assert clean.series_link({**ЗВЕНО, "count": 7.9})["count"] == 7


def test_seriya_bez_imeni_ili_zvenev_ne_seriya():
    assert clean.series({"links": [ЗВЕНО]}) is None
    assert clean.series({"name": "Ночь"}) is None
    assert clean.series({"name": "Ночь", "links": [{"chain": ""}]}) is None


def test_predelov_razmaha_net():
    """Требование (2026-08-04): убрать предел.. Любое число здесь
    было бы выдумано мной и запрещало бы ЕГО замыслы: сначала 64 звена молча
    резали «10 альбомов по 10 треков», потом 200 запрещали бы двадцать
    альбомов. Настоящий ограничитель один и честный — время (см. оценку)."""
    ссылки = [{**ЗВЕНО, "album": f"Альбом {a}"} for a in range(50) for _ in range(10)]
    s = clean.series({"name": "Пятьдесят альбомов", "links": ссылки})
    assert len(s["links"]) == 500, "план не должен худеть ни на звено"
    # и число претендентов сверху тоже не режется
    assert clean.series_link({**ЗВЕНО, "count": 10 ** 6})["count"] == 10 ** 6


# ---- полка -----------------------------------------------------------------

def test_sohranenie_i_perezapis_po_imeni(полка):
    series_mod.save({"name": "Ночь", "links": [ЗВЕНО]})
    series_mod.save({"name": "Ночь", "links": [ЗВЕНО, {**ЗВЕНО, "album": "Стекло"}]})
    все = series_mod.custom()
    assert len(все) == 1, "перезапись по имени не должна плодить дубли"
    assert len(все[0]["links"]) == 2
    assert series_mod.by_name("Ночь")["links"][1]["album"] == "Стекло"


def test_udalenie(полка):
    series_mod.save({"name": "Ночь", "links": [ЗВЕНО]})
    assert series_mod.delete("Ночь") == []
    assert series_mod.by_name("Ночь") is None


def test_krivaya_seriya_otvergaetsya_do_zapisi(полка):
    """Отвергается одной фразой СЕЙЧАС, а не среди ночи на середине прогона."""
    with pytest.raises(clean.BadInput):
        series_mod.save({"name": "Ночь", "links": []})
    assert series_mod.custom() == []


def test_bitaya_zapis_ne_unosit_vsyu_polku(полка):
    """Одна кривая строка в файле не должна стоить пользователю всех серий."""
    (полка / "series.json").write_text(json.dumps([
        {"name": "Живая", "links": [ЗВЕНО]},
        {"нет": "имени"},
        {"name": "Кривой альбом", "links": [{**ЗВЕНО, "album": "а/б"}]},
        "вообще не объект",
    ], ensure_ascii=False), "utf-8")
    имена = [s["name"] for s in series_mod.custom()]
    assert имена == ["Живая"]


def test_bityy_fayl_ne_ronyaet_polku(полка):
    (полка / "series.json").write_text("{не json", "utf-8")
    assert series_mod.custom() == []


# ---- оценка времени --------------------------------------------------------

def test_ocenka_schitaet_teksty_i_sekundy():
    """тысячи претендентов на трек — это 17 суток на сто
    треков, и узнать об этом он должен ДО запуска, а не утром."""
    s = clean.series({"name": "Ночь", "links": [
        {**ЗВЕНО, "count": 20}, {**ЗВЕНО, "album": "Стекло", "count": 30}]})
    o = series_mod.estimate(s)
    assert o["texts"] == 50
    assert o["seconds"] == int(50 * series_mod.SECONDS_PER_TEXT)


def test_ocenka_pustoy_serii_nol():
    assert series_mod.estimate({})["texts"] == 0
    assert series_mod.estimate(None)["texts"] == 0


def test_nochnaya_arifmetika_chestna():
    """Тот самый расклад, ради которого оценка и заведена: 10 альбомов по
    10 треков по 20 претендентов — это уже больше восьми часов."""
    ссылки = [{**ЗВЕНО, "album": f"Альбом {a}", "count": 20}
              for a in range(10) for _ in range(10)]
    s = clean.series({"name": "Десять альбомов", "links": ссылки})
    o = series_mod.estimate(s)
    assert o["texts"] == 2000, "план не должен молча худеть"
    # 2000 × 15 с ≈ 8 ч 20 мин — то есть ровно ночь, и ни треком больше
    assert o["seconds"] > 8 * 3600, "оценка обязана показать, что это целая ночь"
