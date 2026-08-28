# nakedlunch — МЁРТВЫЙ КЛЮЧ НАСТРОЕК: `nl_smart_folders` (2026-08-28).
#
# ЧТО БЫЛО. В белом списке `settings._ALLOWED` и в роуте POST /api/settings жил
# ключ `nl_smart_folders` — умные папки ЛИСТОВ. Сами листы вырезаны 2026-08-18
# вместе с core/sheets.py и роутами /api/sheets/*, и с того дня во фронте у
# ключа не осталось ни одного читателя. То есть сервер продолжал принимать,
# валидировать (точнее — хранить как есть) и записывать на диск состояние
# режима, которого нет полторы недели.
#
# ПОЧЕМУ ЭТО НЕ КОСМЕТИКА. Файл настроек — то, что владелец открывает руками, и
# он показывал набор возможностей, которого в приложении нет. Ровно та же
# болезнь уже стоила дорого в Раунде 52 («Разнообразие» в nl_params) и привела
# к надгробию `nl_chain` 2026-08-18.
#
# ЧТО СТОРОЖИТ ЭТОТ ФАЙЛ:
#   1. ключа нет ни в одном из ДВУХ фильтров — белом списке и роуте;
#   2. старый файл владельца с этим ключом читается, а не падает: чтение молча
#      выбрасывает, живое рядом не теряется;
#   3. первая же запись убирает ключ и с диска;
#   4. во фронте у ключа по-прежнему ноль читателей — иначе его вырезание
#      сломало бы живую панель, а не мёртвую.
#
# Пункт 1 читает api/server.py ТЕКСТОМ, как tests/test_вкладка_настроек.py:
# поднимать сервер ради одного кортежа значило бы платить секунды и гигабайты
# за проверку, которая целиком в исходнике.
#
# Прогон: .venv/bin/python -m pytest tests/test_умные_папки_ушли.py -q

import json
import re
import sys
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

import settings as settings_mod  # noqa: E402

КЛЮЧ = "nl_smart_folders"
ФРОНТ = КОРЕНЬ / "interface" / "react-app" / "src"


@pytest.fixture()
def файл(tmp_path, monkeypatch):
    """Настройки во временной папке: боевой settings.json не наш (см. conftest,
    сторож боевых данных)."""
    p = tmp_path / "settings.json"
    monkeypatch.setattr(settings_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", p)
    return p


# Файл, какой может лежать у владельца на диске прямо сейчас: мёртвый ключ
# вперемешку с живыми.
СТАРЫЙ = {КЛЮЧ: [{"name": "Черновики", "rule": "текст"}],
          "stanza_profile": "Катрен",
          "nl_palette": {"фон": "#111"}}


def _тело_роута() -> str:
    """Тело `api_settings_post` БЕЗ комментариев: надгробие обязано называть
    вырезанное по имени, и искать имя в нём — значит ловить самого себя."""
    текст = (КОРЕНЬ / "api" / "server.py").read_text("utf-8")
    i = текст.index("def api_settings_post()")
    тело = текст[i:текст.index("\n@app.", i)]
    return re.sub(r"#[^\n]*", "", тело)


def test_klyucha_net_ni_v_odnom_iz_dvukh_filtrov():
    """Фильтра два, и это уже подводило (см. комментарий у `nl_params` в
    api/server.py: «второй молча съедал ключ, пропущенный в первом»). Здесь
    промах вышел бы громче: ключ, оставленный в роуте и снятый в белом списке,
    роняет `settings.write` в ValueError на КАЖДОМ сохранении панели."""
    assert КЛЮЧ not in settings_mod._ALLOWED
    assert КЛЮЧ not in _тело_роута()


def test_chtenie_starogo_fayla_perezhivaetsya(файл):
    """Ключ лежит на диске у владельца, и чтение обязано молча его выбросить.
    Упасть тут значит не открыть программу из-за настройки вырезанного режима."""
    файл.write_text(json.dumps(СТАРЫЙ, ensure_ascii=False), "utf-8")
    прочитано = settings_mod.read()
    assert КЛЮЧ not in прочитано
    # живое рядом не потеряно заодно с мёртвым
    assert прочитано["stanza_profile"] == "Катрен"
    assert прочитано["nl_palette"] == {"фон": "#111"}


def test_zapis_klyucha_ne_tishina_a_oshibka(файл):
    """Правило `write` с Раунда 54: чужой ключ — ошибка. Мёртвый ключ теперь
    чужой, и попытка его сохранить обязана быть слышной."""
    файл.write_text(json.dumps(СТАРЫЙ, ensure_ascii=False), "utf-8")
    with pytest.raises(ValueError):
        settings_mod.write({КЛЮЧ: [{"name": "Черновики"}]})


def test_pervaya_zhe_zapis_ubiraet_klyuch_s_diska(файл):
    """Иначе мёртвый ключ жил бы в файле владельца вечно — как «Разнообразие»
    в nl_params до Раунда 52."""
    файл.write_text(json.dumps(СТАРЫЙ, ensure_ascii=False), "utf-8")
    settings_mod.write({"stanza_profile": "Двустишие"})
    сырое = json.loads(файл.read_text("utf-8"))
    assert КЛЮЧ not in сырое
    assert сырое["stanza_profile"] == "Двустишие"
    assert сырое["nl_palette"] == {"фон": "#111"}, "слияние стёрло не упомянутое"


def test_vo_fronte_ni_odnogo_chitatelya():
    """Основание вырезать. Появится читатель — значит ключ снова живой, и
    сторож обязан покраснеть раньше, чем панель молча перестанет сохраняться."""
    попались = []
    for п in ФРОНТ.rglob("*"):
        if not п.is_file():
            continue
        try:
            if КЛЮЧ in п.read_text("utf-8", errors="ignore"):
                попались.append(str(п.relative_to(КОРЕНЬ)))
        except OSError:
            continue
    assert not попались, "во фронте снова есть читатель вырезанного ключа: " + \
                         ", ".join(попались)
