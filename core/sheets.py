# extendo — хранилище листов: настоящие .md в настоящих папках (PLAN.md,
# решение прожарки №6). Vault = ~/Documents/nakedlunch/тексты (env
# NAKEDLUNCH_VAULT переопределяет — так тесты работают во временной папке),
# создаётся лениво при первом обращении. Папка = каталог первого уровня,
# корзина = служебная подпапка .корзина/ со сроком 30 дней.
#
# Формат файла задан ДИЗАЙНОМ (Editor First.dc.html, метод docText, строка
# 3338): роль = '#'*level + ' ' + текст (по умолчанию level 2), перед ролью
# пустая строка (кроме самой первой), строки — как есть. Парсинг обратно
# терпим к чужим файлам: любой заголовок #…###### = роль, всё остальное =
# строки; глотается только ОДНА пустая строка непосредственно перед ролью
# (её добавляет наша же сериализация — это форматирование, не содержимое).
#
# Буквы рифмовки НЕ хранятся в файле — пересчитываются при каждом чтении
# (решение №6: «буквы рифмовки пересчитываются бэкендом (не хранятся)»).
# Ключ — существующий scan.rhyme_key, чтобы формат ключа был единым со всей
# системой (генератор, nl_rhyme.json). Ударение произвольного текста нам
# неизвестно (лексикон покрывает только словарь генератора, а ruaccent —
# офлайн-инструмент, в рантайм его не тянем — см. tools/build_nl_rhyme.py),
# поэтому честная эвристика: слово на гласную → женская рифма (предпоследняя
# гласная ударная), на согласную → мужская (последняя). Ошибочная догадка
# стоит максимум неверной буквы в гутере, не потери данных.
#
# Корзина плоская: имя файла не меняется, конфликт имён решается суффиксом
# « 2» (та же политика, что у дубликата — ничего не теряем и не блокируем).
# Рядом .корзина/meta.json {имя_файла: {deleted_at, orig_folder}} — когда
# удалено и куда восстанавливать. Просроченные (30 дней) удаляются лениво
# при overview() — фонового процесса нет и не нужно.
#
# Запись атомарная: tmp-файл в том же каталоге + os.replace. Блокировок нет
# сознательно — приложение однопользовательское. NL_STORE/CORPUS этот модуль
# не трогает вообще: только файлы vault и scan.rhyme_key (чистая функция).

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path, PurePosixPath

import пути

import scan

TRASH = ".корзина"
TRASH_DAYS = 30

# Корень, куда серия раскладывает свои папки (core/series_run.py: ROOT берёт
# отсюда). Живёт ЗДЕСЬ, а не там, потому что защищать его — дело хранилища:
# `folder_delete` поднимает содержимое на уровень выше, и удаление этого
# корня высыпало бы все названия поверх собственных текстов «одна на всё, её нельзя удалить», — и это
# была неправда до Раунда 55.
КОРЕНЬ_СЕРИЙ = "Серии"
DEFAULT_VAULT = Path.home() / "Documents" / "nakedlunch" / "тексты"

# свежий лист — ровно как в дизайне (Editor First.dc.html:3134):
# роль «куплет» + одна пустая строка
FRESH_DOC = [{"type": "role", "text": "куплет", "level": 2},
             {"type": "line", "text": ""}]

_ROLE_RE = re.compile(r"^\s*(#{1,6})\s+(.*)$")
_LETTERS = "абвгдежзиклмноп"   # алфавит букв схемы — как в дизайне (scheme())


class SheetError(ValueError):
    """Доменная ошибка листов — сервер переводит её в честный HTTP 400."""


# ---- служебное: пути, имена, атомарная запись ---------------------------

def _vault() -> Path:
    # Через `пути.хранилище` (Раунд 61): своя переменная → NAKEDLUNCH_HOME →
    # умолчание. Раньше листы уводились только своей переменной, и «изоляция
    # одной NAKEDLUNCH_HOME» их не покрывала — при живой проверке они писались
    # бы в настоящее хранилище.
    p = пути.хранилище("NAKEDLUNCH_VAULT", "листы", DEFAULT_VAULT)
    p.mkdir(parents=True, exist_ok=True)
    return p


def vault_dir() -> Path:
    """Публичный путь хранилища — для кнопки «открыть папку» на сервере."""
    return _vault()


def _clean_title(title, default: str | None = None) -> str:
    t = str(title or "").strip()
    if not t:
        if default is not None:
            return default
        raise SheetError("пустое название")
    if "/" in t or t.startswith("."):
        raise SheetError("недопустимое название листа")
    return t


# Папки ВЛОЖЕННЫЕ (Раунд 53). Были одноуровневые: `_folder_name` отказывался
# от «/», обзор читал только верхний уровень. требование из брифа редактора: папки внутри папок, как в заметках), а серия без него
# невыразима вовсе: её раскладка это «альбом → сессия вариаций трека → листы».
#
# Предел глубины есть и он тут не формальность: id папки и листа приходят ИЗ
# БРАУЗЕРА, и без предела один кривой запрос уводил бы обход в произвольную
# глубину. Четыре уровня — это «Серии/альбом/трек» плюс запас на то, как
# пользователь разложит своё.
_MAX_DEPTH = 4


def _folder_parts(name) -> tuple[str, ...]:
    """Имя папки → части пути. Пустое имя = корень (пустой кортеж)."""
    raw = str(name or "").strip().strip("/")
    if not raw:
        return ()
    parts = tuple(p.strip() for p in raw.split("/"))
    if (len(parts) > _MAX_DEPTH or any(not p or p.startswith(".") for p in parts)
            or any(p in ("..", ".") for p in parts)):
        raise SheetError("недопустимое имя папки")
    return parts


def _folder_dir(vault: Path, name) -> Path:
    return vault.joinpath(*_folder_parts(name))


def _sheet_path(vault: Path, sid, must_exist: bool = True) -> Path:
    """id листа = путь относительно vault ('Альбом/Трек/Название.md').
    Валидация строгая: глубина ≤ папок+1, никаких '..' — id из браузера."""
    sid = str(sid or "").strip().strip("/")
    parts = PurePosixPath(sid).parts
    if (not sid or not sid.endswith(".md") or len(parts) > _MAX_DEPTH + 1
            or any(p in ("..", ".") for p in parts)):
        raise SheetError("некорректный id листа")
    p = vault.joinpath(*parts)
    if must_exist and not p.is_file():
        raise SheetError("лист не найден")
    return p


def _rel(vault: Path, p: Path) -> str:
    return p.relative_to(vault).as_posix()


def _free_path(d: Path, title: str) -> Path:
    """Свободное имя в каталоге: «Название», «Название 2», «Название 3»…"""
    p = d / (title + ".md")
    n = 2
    while p.exists():
        p = d / (f"{title} {n}.md")
        n += 1
    return p


def _hhmm(p: Path) -> str:
    return time.strftime("%H:%M", time.localtime(p.stat().st_mtime))


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---- meta корзины --------------------------------------------------------

def _meta_load(tr: Path) -> dict:
    try:
        m = json.loads((tr / "meta.json").read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}   # битый/отсутствующий meta.json — не повод ронять список


def _meta_save(tr: Path, meta: dict) -> None:
    _atomic_write(tr / "meta.json", json.dumps(meta, ensure_ascii=False, indent=1))


# ---- формат .md: сериализация и терпимый парсинг ------------------------

def _clean_rows(rows) -> list[dict]:
    """Валидация rows из браузера. letter игнорируется по контракту — буквы
    считаются только при чтении. Перевод строки внутри текста сломал бы
    формат, поэтому заменяется пробелом."""
    if not isinstance(rows, list):
        raise SheetError("нужен список rows")
    out = []
    for r in rows:
        if not isinstance(r, dict) or r.get("type") not in ("role", "line"):
            raise SheetError("некорректная строка листа")
        text = r.get("text", "")
        if not isinstance(text, str):
            raise SheetError("некорректная строка листа")
        row = {"type": r["type"], "text": text.replace("\r", "").replace("\n", " ")}
        if r["type"] == "role":
            try:
                row["level"] = min(6, max(1, int(r.get("level") or 2)))
            except (TypeError, ValueError):
                row["level"] = 2
        out.append(row)
    return out


def _serialize(rows: list[dict]) -> str:
    """1:1 docText() из дизайна: '#'*level + ' ' + роль, пустая строка перед
    ролью (кроме первой), строки как есть."""
    out = []
    for i, r in enumerate(rows):
        if r["type"] == "role":
            if i:
                out.append("")
            out.append("#" * r.get("level", 2) + " " + r["text"])
        else:
            out.append(r["text"])
    return "\n".join(out) + ("\n" if out else "")


def _parse(text: str) -> list[dict]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()   # финальный перевод строки файла — не пустая строка документа
    rows: list[dict] = []
    for i, raw in enumerate(lines):
        m = _ROLE_RE.match(raw)
        if m:
            rows.append({"type": "role", "text": m.group(2), "level": len(m.group(1))})
        elif raw == "" and i + 1 < len(lines) and _ROLE_RE.match(lines[i + 1]):
            continue   # разделительная пустая перед ролью — её добавила сериализация
        else:
            rows.append({"type": "line", "text": raw})
    return rows


# ---- буквы рифмовки ------------------------------------------------------

def _line_key(text: str) -> str | None:
    """Ключ рифмы строки — рифмо-ключ последнего кириллического слова.

    РАУНД 51: берётся из словаря ударений (660k словоформ, ruaccent), который
    и так поднят в память процесса. Здесь стояла ТРЕТЬЯ в проекте копия
    угадывания ударения — своё правило «ударение на предпоследней гласной,
    если слово кончается гласной», своя точность 54.3%. Настоящий источник
    лежал рядом и молчал, потому что достать его можно было только через
    подсказки попапа.

    Промах словаря — честный None: строка остаётся одиночкой «·», а не
    получает выдуманную букву рифмовки. Прежняя эвристика в этом месте
    отвечала ВСЕГДА, и половина букв в гутере была вымышленной."""
    words = re.findall(r"[а-яё]+", str(text).lower())
    if not words:
        return None
    try:
        import wordsuggest
        key = wordsuggest.rhyme_key_of(words[-1])
    except Exception:
        return None
    return key or None


def _assign_letters(rows: list[dict]) -> None:
    """Буквы внутри секции (от роли до роли): группы по ключу рифмы, буквы
    'абвгд…' в порядке появления ГРУППЫ; ≥2 строк — буква, одиночки — «·».
    Роль сбрасывает счёт, как scheme() в дизайне."""
    section: list[tuple[int, str | None]] = []

    def flush() -> None:
        counts: dict[str, int] = {}
        for _, k in section:
            if k:
                counts[k] = counts.get(k, 0) + 1
        order: list[str] = []
        for i, k in section:
            if k and counts[k] >= 2:
                if k not in order:
                    order.append(k)
                rows[i]["letter"] = _LETTERS[order.index(k) % len(_LETTERS)]
            else:
                rows[i]["letter"] = "·"
        section.clear()

    for i, r in enumerate(rows):
        if r["type"] == "role":
            flush()
        else:
            section.append((i, _line_key(r["text"])))
    flush()


def _walk_folders(vault: Path) -> list[str]:
    """Все папки дерева путями относительно vault, в порядке обхода: родитель
    идёт перед своими детьми, соседи по алфавиту. Именно в этом порядке их и
    показывает список — иначе сдвиг по глубине нарисует дерево, которого нет.

    Служебные (с точки — корзина) не обходятся вовсе, и глубже предела мы не
    спускаемся: чужой каталог, случайно оказавшийся в хранилище, не должен
    превращать обзор в обход диска."""
    out: list[str] = []

    def вниз(d: Path, глубина: int) -> None:
        if глубина >= _MAX_DEPTH:
            return
        for p in sorted((x for x in d.iterdir()
                         if x.is_dir() and not x.name.startswith(".")),
                        key=lambda x: x.name):
            out.append(_rel(vault, p))
            вниз(p, глубина + 1)

    вниз(vault, 0)
    return out


# ---- операции контракта /api/sheets --------------------------------------

def overview() -> dict:
    """GET /api/sheets: все листы (живые + корзина) и папки. Просроченные
    в корзине (30 дней) удаляются прямо здесь, лениво."""
    vault = _vault()
    folders = _walk_folders(vault)

    def entry(p: Path, folder: str, trashed: bool, days) -> dict:
        return {"id": _rel(vault, p), "title": p.stem, "folder": folder,
                "trashed": trashed, "days_left": days, "at": _hhmm(p)}

    live = [(p, "") for p in vault.glob("*.md") if not p.name.startswith(".")]
    for f in folders:
        live += [(p, f) for p in (vault / f).glob("*.md") if not p.name.startswith(".")]
    live.sort(key=lambda t: t[0].stat().st_mtime, reverse=True)
    sheets = [entry(p, folder, False, None) for p, folder in live]

    tr = vault / TRASH
    if tr.is_dir():
        meta = _meta_load(tr)
        changed = False
        trashed: list[tuple[float, dict]] = []
        for p in sorted(tr.glob("*.md")):
            e = meta.get(p.name) or {}
            # чужой файл в корзине без meta — считаем от mtime, не падаем
            try:
                deleted_at = float(e.get("deleted_at") or p.stat().st_mtime)
            except (TypeError, ValueError):
                deleted_at = p.stat().st_mtime
            days = TRASH_DAYS - int((time.time() - deleted_at) // 86400)
            if days <= 0:
                p.unlink()
                meta.pop(p.name, None)
                changed = True
                continue
            trashed.append((deleted_at, entry(p, e.get("orig_folder") or "", True, days)))
        if changed:
            _meta_save(tr, meta)
        trashed.sort(key=lambda t: t[0], reverse=True)
        sheets += [e for _, e in trashed]

    # `id` — путь целиком («Серии/Пепел/дорога»), `name` — последняя часть,
    # `depth` — на сколько сдвинуть строку в списке. Фронт двигает по depth и
    # НЕ разбирает путь сам: разбор пути в двух местах — это два разных мнения
    # о том, где кончается имя.
    return {"sheets": sheets,
            "folders": [{"id": f, "name": f.split("/")[-1], "depth": f.count("/")}
                        for f in folders]}


def read(sid) -> dict:
    vault = _vault()
    path = _sheet_path(vault, sid)
    rows = _parse(path.read_text(encoding="utf-8", errors="replace"))
    _assign_letters(rows)
    return {"id": _rel(vault, path), "title": path.stem, "rows": rows}


def write(sid, rows) -> dict:
    vault = _vault()
    path = _sheet_path(vault, sid)
    _atomic_write(path, _serialize(_clean_rows(rows)))
    return {"ok": True, "at": _hhmm(path)}


def create(title=None, folder=None) -> dict:
    vault = _vault()
    t = _clean_title(title, default="Без названия")
    d = _folder_dir(vault, folder)
    if not d.is_dir():
        raise SheetError("папка не найдена")
    path = _free_path(d, t)          # занято → «Название 2»
    _atomic_write(path, _serialize(FRESH_DOC))
    return {"id": _rel(vault, path), "title": path.stem}


def rename(sid, title) -> dict:
    vault = _vault()
    path = _sheet_path(vault, sid)
    if path.parent.name == TRASH:
        raise SheetError("лист в корзине — сначала восстановите")
    t = _clean_title(title)
    if t == path.stem:
        return {"id": _rel(vault, path)}
    # коллизия имён → суффикс « 2»: та же политика «не теряем и не блокируем»,
    # что у корзины и дубликата; итоговое имя видно в вернувшемся id
    new = _free_path(path.parent, t)
    path.rename(new)
    return {"id": _rel(vault, new)}


def duplicate(sid) -> dict:
    vault = _vault()
    path = _sheet_path(vault, sid)
    if path.parent.name == TRASH:
        raise SheetError("лист в корзине — сначала восстановите")
    new = _free_path(path.parent, path.stem)
    _atomic_write(new, path.read_text(encoding="utf-8", errors="replace"))
    return {"id": _rel(vault, new), "title": new.stem}


def trash(sid) -> dict:
    vault = _vault()
    path = _sheet_path(vault, sid)
    if path.parent.name == TRASH:
        raise SheetError("лист уже в корзине")
    tr = vault / TRASH
    tr.mkdir(exist_ok=True)
    dest = _free_path(tr, path.stem)
    # путь ЦЕЛИКОМ, а не имя папки: с вложенностью «Пепел» и «Стекло/Пепел» —
    # разные места, и восстанавливать в первое попавшееся значит терять лист
    folder = _rel(vault, path.parent) if path.parent != vault else ""
    path.rename(dest)
    meta = _meta_load(tr)
    meta[dest.name] = {"deleted_at": time.time(), "orig_folder": folder}
    _meta_save(tr, meta)
    return {"ok": True}


def restore(sid) -> dict:
    vault = _vault()
    path = _sheet_path(vault, sid)
    if path.parent.name != TRASH:
        raise SheetError("лист не в корзине")
    tr = path.parent
    meta = _meta_load(tr)
    entry = meta.pop(path.name, None) or {}
    d = vault
    if entry.get("orig_folder"):
        try:
            d = _folder_dir(vault, entry["orig_folder"])
        except SheetError:
            d = vault          # запись из чужой/старой корзины — кладём в корень
        d.mkdir(parents=True, exist_ok=True)   # папку могли удалить — восстановим и её
    dest = _free_path(d, path.stem)
    path.rename(dest)
    _meta_save(tr, meta)
    return {"ok": True}


def purge(sid) -> dict:
    vault = _vault()
    path = _sheet_path(vault, sid)
    if path.parent.name != TRASH:
        raise SheetError("лист не в корзине")
    path.unlink()
    meta = _meta_load(path.parent)
    if meta.pop(path.name, None) is not None:
        _meta_save(path.parent, meta)
    return {"ok": True}


def purge_all() -> dict:
    vault = _vault()
    tr = vault / TRASH
    n = 0
    if tr.is_dir():
        for p in tr.glob("*.md"):
            p.unlink()
            n += 1
        _meta_save(tr, {})
    return {"n": n}


def move(sid, folder) -> dict:
    vault = _vault()
    path = _sheet_path(vault, sid)
    if path.parent.name == TRASH:
        raise SheetError("лист в корзине — сначала восстановите")
    d = _folder_dir(vault, folder)
    if not d.is_dir():
        raise SheetError("папка не найдена")
    if d == path.parent:
        return {"id": _rel(vault, path)}
    dest = _free_path(d, path.stem)
    path.rename(dest)
    return {"id": _rel(vault, dest)}


def folder_create(name) -> dict:
    vault = _vault()
    parts = _folder_parts(name)
    if not parts:
        raise SheetError("недопустимое имя папки")
    d = vault.joinpath(*parts)
    if d.exists():
        raise SheetError("такая папка уже есть")
    d.mkdir(parents=True)      # «Серии/Пепел/дорога» одним вызовом
    n = "/".join(parts)
    return {"id": n, "name": parts[-1], "depth": len(parts) - 1}


def folder_delete(fid) -> dict:
    """Содержимое переезжает НА УРОВЕНЬ ВЫШЕ, затем каталог удаляется —
    «удаление без вопросов», как везде у nakedlunch.

    Раньше файлы уезжали в КОРЕНЬ, и с одноуровневыми папками это было одно и
    то же. С деревом — уже нет: удалив «Серии/Пепел», пользователь высыпал бы весь
    альбом в общий список поверх своих текстов. Наверх — значит на своё место
    в дереве, а не в кучу.

    Подпапки переезжают целиком и остаются подпапками: «Серии/Пепел/дорога»
    после удаления «Пепла» станет «Серии/дорога». Ничего не теряется и ничего
    не сплющивается."""
    vault = _vault()
    parts = _folder_parts(fid)
    if not parts:
        raise SheetError("недопустимое имя папки")
    d = vault.joinpath(*parts)
    if not d.is_dir():
        raise SheetError("папка не найдена")
    # Корень серий защищён от ВЫСЫПАНИЯ, а не от удаления (Раунд 55, починка в
    # тот же день). Сначала я запретил его совсем — и отчёт: папки не удалялись: у него это была единственная папка, к
    # тому же пустая, оставшаяся от моей же проверки. Запрет ради опасности,
    # которой в пустой папке нет, — это не защита, а отобранная уборка.
    #
    # Опасность настоящая и остаётся: `folder_delete` поднимает содержимое на
    # уровень выше, и удаление непустого корня высыпало бы все названия поверх
    # собственных текстов. Поэтому правило по СОДЕРЖИМОМУ: пустой — удаляется
    # как любая папка (следующий прогон заведёт его заново), с содержимым —
    # честный отказ с именем того, что внутри.
    if parts == (КОРЕНЬ_СЕРИЙ,):
        внутри = [x.name for x in sorted(d.iterdir()) if not x.name.startswith(".")]
        if внутри:
            raise SheetError(
                f"в «{КОРЕНЬ_СЕРИЙ}» лежит {', '.join(внутри[:3])}"
                + (" и другое" if len(внутри) > 3 else "")
                + " — удали это внутри, иначе всё высыплется наружу")
    вверх = d.parent
    for p in sorted(d.glob("*.md")):
        p.rename(_free_path(вверх, p.stem))
    for sub in sorted(x for x in d.iterdir() if x.is_dir()):
        цель = вверх / sub.name
        n = 2
        while цель.exists():                 # такая папка наверху уже есть
            цель = вверх / f"{sub.name} {n}"
            n += 1
        sub.rename(цель)
    shutil.rmtree(d)
    return {"ok": True}
