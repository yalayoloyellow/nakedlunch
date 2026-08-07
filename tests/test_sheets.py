# extendo — тесты хранилища листов (core/sheets.py): реальный сценарий на
# реальных файлах во временном vault (env NAKEDLUNCH_VAULT), не моки.
# Формат .md задан дизайном (docText), буквы рифмовки пересчитываются при
# чтении, корзина плоская со сроком 30 дней — см. шапку core/sheets.py.
# Прогон: .venv/bin/python -m pytest tests/test_sheets.py -q

import json
import re
import sys
import time
from pathlib import Path

import pytest
from conftest import нет_словаря_рифм, нет_векторов  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

import sheets


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    v = tmp_path / "тексты"
    monkeypatch.setenv("NAKEDLUNCH_VAULT", str(v))
    return v


def _skeleton(rows):
    """Срез rows без букв — для сравнения раундтрипа (letter в файл не пишется)."""
    out = []
    for r in rows:
        if r["type"] == "role":
            out.append(("role", r["text"], r.get("level", 2)))
        else:
            out.append(("line", r["text"]))
    return out


def test_create_and_read_fresh(vault):
    """Свежий лист = ровно свежий документ дизайна: роль «куплет» + пустая строка."""
    made = sheets.create()
    assert made == {"id": "Без названия.md", "title": "Без названия"}
    doc = sheets.read(made["id"])
    assert doc["title"] == "Без названия"
    assert _skeleton(doc["rows"]) == [("role", "куплет", 2), ("line", "")]
    assert doc["rows"][1]["letter"] == "·"    # одинокая пустая строка — без группы
    # второй лист с тем же названием получает суффикс, ничего не затирается
    assert sheets.create()["id"] == "Без названия 2.md"


def test_write_read_roundtrip(vault):
    made = sheets.create(title="Раундтрип")
    rows = [
        {"type": "role", "text": "куплет", "level": 1},
        {"type": "line", "text": "первая строка"},
        {"type": "line", "text": ""},
        {"type": "role", "text": "припев", "level": 3},
        {"type": "line", "text": "вторая строка", "letter": "я"},   # letter игнорируется
    ]
    res = sheets.write(made["id"], rows)
    assert res["ok"] is True
    assert re.fullmatch(r"\d{2}:\d{2}", res["at"])
    # файл — ровно формат docText из дизайна: заголовки-роли, пустая перед ролью
    raw = (vault / "Раундтрип.md").read_text(encoding="utf-8")
    assert raw == "# куплет\nпервая строка\n\n\n### припев\nвторая строка\n"
    assert _skeleton(sheets.read(made["id"])["rows"]) == _skeleton(rows)


def test_read_tolerates_foreign_file(vault):
    """Чужой .md: любой текст = строки, любые заголовки = роли, ничего не падает."""
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "Чужой.md").write_text("Просто текст\n#### Бридж\nещё строка\n", encoding="utf-8")
    doc = sheets.read("Чужой.md")
    assert _skeleton(doc["rows"]) == [
        ("line", "Просто текст"), ("role", "Бридж", 4), ("line", "ещё строка")]


@нет_словаря_рифм
def test_rhyme_letters_grouping(vault):
    """Реально рифмующиеся строки группируются одной буквой внутри секции;
    одиночки получают «·»; роль сбрасывает счёт букв."""
    made = sheets.create(title="Рифмы")
    sheets.write(made["id"], [
        {"type": "role", "text": "куплет"},
        {"type": "line", "text": "я помню эти ночи"},      # но́чи  → а
        {"type": "line", "text": "горит моя любовь"},       # любо́вь → б
        {"type": "line", "text": "твои родные очи"},        # о́чи   → а
        {"type": "line", "text": "по жилам стынет кровь"},  # кровь  → б
        {"type": "line", "text": "одинокая строка"},        # ни с чем → ·
        {"type": "role", "text": "припев"},
        {"type": "line", "text": "падал белый снег"},       # снег → а (новая секция)
        {"type": "line", "text": "мой недолгий бег"},       # бег  → а
    ])
    rows = sheets.read(made["id"])["rows"]
    letters = [r["letter"] for r in rows if r["type"] == "line"]
    assert letters == ["а", "б", "а", "б", "·", "а", "а"]


def test_rename_collision_gets_suffix(vault):
    sheets.create(title="Один")
    two = sheets.create(title="Два")
    renamed = sheets.rename(two["id"], "Один")
    assert renamed["id"] == "Один 2.md"
    assert (vault / "Один.md").is_file() and (vault / "Один 2.md").is_file()
    assert not (vault / "Два.md").exists()


def test_duplicate(vault):
    made = sheets.create(title="Оригинал")
    sheets.write(made["id"], [{"type": "line", "text": "уникальный текст"}])
    dup = sheets.duplicate(made["id"])
    assert dup == {"id": "Оригинал 2.md", "title": "Оригинал 2"}
    assert _skeleton(sheets.read(dup["id"])["rows"]) == [("line", "уникальный текст")]


def test_trash_restore_purge_cycle(vault):
    sheets.folder_create("Тексты")
    made = sheets.create(title="Песня", folder="Тексты")
    assert made["id"] == "Тексты/Песня.md"

    sheets.trash(made["id"])
    over = sheets.overview()
    entry = next(s for s in over["sheets"] if s["trashed"])
    assert entry["id"] == ".корзина/Песня.md"
    assert entry["days_left"] == 30                 # только что удалён
    assert entry["folder"] == "Тексты"              # откуда — из meta.json
    meta = json.loads((vault / ".корзина" / "meta.json").read_text(encoding="utf-8"))
    assert meta["Песня.md"]["orig_folder"] == "Тексты"

    sheets.restore(entry["id"])
    assert (vault / "Тексты" / "Песня.md").is_file()
    assert not (vault / ".корзина" / "Песня.md").exists()

    sheets.trash("Тексты/Песня.md")
    sheets.purge(".корзина/Песня.md")
    assert not (vault / ".корзина" / "Песня.md").exists()
    assert all(not s["trashed"] for s in sheets.overview()["sheets"])


def test_trash_name_conflict_and_purge_all(vault):
    """Корзина плоская: одноимённый лист получает суффикс « 2», имена не меняются."""
    sheets.create(title="Дубль")
    sheets.folder_create("П")
    sheets.create(title="Дубль", folder="П")
    sheets.trash("Дубль.md")
    sheets.trash("П/Дубль.md")
    assert (vault / ".корзина" / "Дубль.md").is_file()
    assert (vault / ".корзина" / "Дубль 2.md").is_file()
    assert sheets.purge_all() == {"n": 2}
    assert not list((vault / ".корзина").glob("*.md"))


def test_trash_expiry_is_lazy(vault):
    """Просроченный (30 дней) лист удаляется при первом же overview();
    непросроченный показывает честный days_left."""
    old = sheets.create(title="Старый")
    fresh = sheets.create(title="Свежий")
    sheets.trash(old["id"])
    sheets.trash(fresh["id"])
    meta_path = vault / ".корзина" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["Старый.md"]["deleted_at"] = time.time() - 31 * 86400      # просрочен
    meta["Свежий.md"]["deleted_at"] = time.time() - 29 * 86400 - 900  # остался 1 день
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    over = sheets.overview()
    ids = [s["id"] for s in over["sheets"]]
    assert ".корзина/Старый.md" not in ids
    assert not (vault / ".корзина" / "Старый.md").exists()          # файл удалён физически
    entry = next(s for s in over["sheets"] if s["id"] == ".корзина/Свежий.md")
    assert entry["days_left"] == 1


def test_move_between_folders(vault):
    sheets.folder_create("А")
    sheets.folder_create("Б")
    made = sheets.create(title="Песня", folder="А")
    moved = sheets.move(made["id"], "Б")
    assert moved["id"] == "Б/Песня.md"
    assert (vault / "Б" / "Песня.md").is_file() and not (vault / "А" / "Песня.md").exists()
    back = sheets.move(moved["id"], "")            # ''=корень по контракту
    assert back["id"] == "Песня.md"
    with pytest.raises(sheets.SheetError):
        sheets.move(back["id"], "Нет такой")


def test_folder_delete_moves_files_to_root(vault):
    sheets.folder_create("В")
    sheets.create(title="Икс")                      # займёт имя в корне
    sheets.create(title="Икс", folder="В")
    sheets.folder_delete("В")
    assert not (vault / "В").exists()
    assert (vault / "Икс.md").is_file() and (vault / "Икс 2.md").is_file()
    assert sheets.overview()["folders"] == []


def test_bad_input_fails_honestly(vault):
    """Мусорный id/имя → одна русская фраза, не traceback и не тихий успех."""
    for bad in ("", "../чужое.md", "нет.md", "Папка/суб/имя.md", "без-расширения"):
        with pytest.raises(sheets.SheetError) as e:
            sheets.read(bad)
        assert str(e.value)
    with pytest.raises(sheets.SheetError):
        sheets.create(title="со/слэшем")
    with pytest.raises(sheets.SheetError):
        sheets.folder_create(".корзина")


# ---- ВЛОЖЕННЫЕ ПАПКИ (Раунд 53) -------------------------------------------
#
# Были одноуровневые: `_folder_name` отказывался от «/», обзор читал только
# верхний уровень. Пользователь просил дерево ещё в брифе редактора, а раскладка
# серии («альбом → сессия вариаций трека → листы») без него невыразима вовсе.

def test_papka_v_papke_sozdayotsya_odnim_vyzovom(vault):
    f = sheets.folder_create("Серии/Пепел/дорога")
    assert f["id"] == "Серии/Пепел/дорога"
    assert f["name"] == "дорога", "имя — последняя часть, а не весь путь"
    assert f["depth"] == 2
    assert (vault / "Серии" / "Пепел" / "дорога").is_dir()


def test_obzor_vidit_derevo_i_daet_glubinu(vault):
    sheets.folder_create("Серии/Пепел/дорога")
    sheets.folder_create("Свои")
    o = sheets.overview()
    пути = [f["id"] for f in o["folders"]]
    # «Свои» раньше «Серии» — по алфавиту («в» < «е»), соседи сортируются
    assert пути == ["Свои", "Серии", "Серии/Пепел", "Серии/Пепел/дорога"], (
        "родитель обязан идти перед детьми — иначе сдвиг нарисует дерево, которого нет")
    assert [f["depth"] for f in o["folders"]] == [0, 0, 1, 2]


def test_list_lozhitsya_v_glubokuyu_papku_i_chitaetsya(vault):
    sheets.folder_create("Серии/Пепел/дорога")
    made = sheets.create("он ушёл в ночной покой", folder="Серии/Пепел/дорога")
    assert made["id"] == "Серии/Пепел/дорога/он ушёл в ночной покой.md"
    assert sheets.read(made["id"])["title"] == "он ушёл в ночной покой"
    o = sheets.overview()
    лист = [s for s in o["sheets"] if s["id"] == made["id"]][0]
    assert лист["folder"] == "Серии/Пепел/дорога"


def test_perenos_mezhdu_urovnyami(vault):
    sheets.folder_create("Серии/Пепел")
    sheets.folder_create("Свои")
    made = sheets.create("трек", folder="Серии/Пепел")
    res = sheets.move(made["id"], "Свои")
    assert res["id"] == "Свои/трек.md"
    # и обратно в корень
    assert sheets.move(res["id"], "")["id"] == "трек.md"


def test_korzina_pomnit_put_celikom(vault):
    """С вложенностью «Пепел» и «Стекло/Пепел» — разные места. Восстанавливать
    в первое попавшееся значит терять лист."""
    sheets.folder_create("Серии/Пепел/дорога")
    made = sheets.create("трек", folder="Серии/Пепел/дорога")
    sheets.trash(made["id"])
    в_корзине = [s for s in sheets.overview()["sheets"] if s["trashed"]][0]
    assert в_корзине["folder"] == "Серии/Пепел/дорога"
    sheets.restore(в_корзине["id"])
    assert (vault / "Серии" / "Пепел" / "дорога" / "трек.md").is_file()


def test_vosstanovlenie_vossozdayot_udalyonnoe_derevo(vault):
    sheets.folder_create("Серии/Пепел/дорога")
    made = sheets.create("трек", folder="Серии/Пепел/дорога")
    sheets.trash(made["id"])
    sheets.folder_delete("Серии/Пепел/дорога")
    sheets.folder_delete("Серии/Пепел")
    # Корень серий приложением не удаляется (Раунд 55) — но в Finder пользователь
    # его удалить может, и восстановление обязано пережить и это.
    (vault / "Серии").rmdir()
    в_корзине = [s for s in sheets.overview()["sheets"] if s["trashed"]][0]
    sheets.restore(в_корзине["id"])
    assert (vault / "Серии" / "Пепел" / "дорога" / "трек.md").is_file()


def test_udalenie_papki_podnimaet_soderzhimoe_naverh(vault):
    """РАНЬШЕ содержимое уезжало в КОРЕНЬ. С одноуровневыми папками это было
    одно и то же; с деревом — удалив «Серии/Пепел», пользователь высыпал бы весь
    альбом в общий список поверх своих текстов."""
    sheets.folder_create("Серии/Пепел/дорога")
    sheets.create("трек", folder="Серии/Пепел")
    sheets.create("вариант", folder="Серии/Пепел/дорога")
    sheets.folder_delete("Серии/Пепел")
    assert (vault / "Серии" / "трек.md").is_file(), "лист уехал не наверх"
    assert (vault / "Серии" / "дорога" / "вариант.md").is_file(), \
        "подпапка обязана переехать целиком и остаться подпапкой"
    assert not (vault / "Серии" / "Пепел").exists()
    assert not (vault / "трек.md").exists(), "содержимое высыпалось в корень"


@pytest.mark.parametrize("плохая", ["Серии/../тайное", "а/б/в/г/д", "Серии/.скрытая",
                                    "Серии//пусто", "  "])
def test_krivoy_put_papki_chestnyy_otkaz(vault, плохая):
    """id приходит ИЗ БРАУЗЕРА: без предела глубины и запрета на «..» один
    кривой запрос увёл бы обход куда угодно."""
    with pytest.raises(sheets.SheetError):
        sheets.folder_create(плохая)


def test_glubina_lista_ogranichena(vault):
    with pytest.raises(sheets.SheetError):
        sheets.read("а/б/в/г/д/лист.md")
