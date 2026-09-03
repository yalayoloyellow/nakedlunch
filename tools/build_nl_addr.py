#!/usr/bin/env python3
"""АДРЕСА СТРОК: где каждая строка корпуса лежит в своей книге.

ЗАЧЕМ. Строка в этом проекте — готовый текст без прошлого: откуда её вырезали,
не знает никто. Поэтому удлинить её нечем — соседнего слова просто негде взять
(замер 2026-09-01: в складе 2 307 826 нарезанных кусков и ни одной книги).
Адрес — книга и границы в её тексте — возвращает это знание, и тогда «взять
слово слева» становится сдвигом границы.

ПОЧЕМУ НЕ ПЕРЕЗАЛИВКА, КОТОРУЮ ПРОСИЛОСЬ. Проверил на его книге: если
нарезать заново тем же кодом из того же файла, совпадает лишь 63% складских
строк — резак с августа изменился, и перезаливка выбросила бы 37% корпуса
вместе с историей и избранным, которые к этим текстам привязаны. А НАЙТИ
нынешние строки в книге удаётся для 99.5% (замер на Керуаке: 25 866 из 25 984).
Значит адрес приписывается, а не пересоздаётся: тексты не меняются, история
цела, индекс тот же.

КАК ИЩЕМ. Строка ищется в тексте книги подстрокой. Две трети находятся как
есть, ещё 17% — после схлопывания пробелов (резак сшивал переносы строк).
Поэтому ищем в «плоском» тексте, где подряд идущие пробелы схлопнуты в один, и
рядом держим карту «позиция в плоском → позиция в исходном».

ЧТО НЕ НАХОДИТСЯ. Мосты — куски, склеенные из двух разных мест книги
(«хвост предложения + голова следующего»), их в корпусе около десятой части.
У них нет одного адреса по определению, и они его не получают: такие строки
просто не умеют удлиняться, и это честно.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))
sys.path.insert(0, str(КОРЕНЬ / "core" / "nlsrc"))

import nlindex  # noqa: E402
import nlbridge  # noqa: E402
import пути  # noqa: E402
from nlsrc.cutter import parse_source_file  # noqa: E402

ГДЕ_КНИГИ = [Path.home() / "Downloads", Path.home() / "Downloads" / "books",
             Path.home() / "Documents"]
ВЫХОД = пути.артефакт("nl_addr")
_ЗНАКИ = re.compile(r"[^a-zA-Zа-яёА-ЯЁ0-9]")


def _ключ_имени(s: str) -> str:
    return _ЗНАКИ.sub("", s).lower()


def найти_файлы(имена: list[str]) -> dict:
    """Имя книги в складе → файл на диске. Сверка по имени без знаков."""
    файлы = {}
    for корень in ГДЕ_КНИГИ:
        if not корень.exists():
            continue
        for п in корень.rglob("*"):
            if п.suffix.lower() in (".fb2", ".txt", ".md"):
                файлы.setdefault(_ключ_имени(п.stem), п)
    итог = {}
    for имя in имена:
        к = _ключ_имени(имя)
        п = файлы.get(к)
        if п is None:                       # имя могло быть подрезано при заливке
            for кф, пф in файлы.items():
                if кф.startswith(к[:40]) or к.startswith(кф[:40]):
                    п = пф
                    break
        if п is not None:
            итог[имя] = п
    return итог


def плоский(текст: str) -> tuple[str, np.ndarray]:
    """Текст со схлопнутыми пробелами и карта «плоская позиция → исходная».

    Резак сшивал переносы строк, поэтому 17.4% строк складе отличаются от книги
    ровно пробелами. Искать в плоском виде — единственный способ найти их, не
    трогая ни строки, ни книгу.
    """
    куски, карта = [], []
    пробел = False
    for i, ч in enumerate(текст):
        if ч.isspace():
            if пробел:
                continue
            куски.append(" ")
            карта.append(i)
            пробел = True
        else:
            куски.append(ч)
            карта.append(i)
            пробел = False
    return "".join(куски), np.asarray(карта, dtype=np.int64)


def адреса_книги(текст: str, строки: list[str]) -> list:
    """[(начало, конец) или None] — по строке на каждую переданную."""
    пл, карта = плоский(текст)
    итог = []
    for т in строки:
        поз = текст.find(т)
        if поз >= 0:
            итог.append((поз, поз + len(т)))
            continue
        сжатая = " ".join(т.split())
        поз = пл.find(сжатая)
        if поз < 0:
            итог.append(None)
            continue
        конец = поз + len(сжатая) - 1
        итог.append((int(карта[поз]), int(карта[конец]) + 1))
    return итог


def построить() -> int:
    t0 = time.time()
    idx = nlindex.load()
    if idx is None:
        print("индекс не испечён — сначала tools/build_nl_index.py", file=sys.stderr)
        return 1
    склад = nlbridge.open_store()
    имена = {к["id"]: к["name"] for к in склад.list_corpora()}
    ид_книг = list(getattr(idx, "sources", []) or [])
    файлы = найти_файлы(list(имена.values()))
    print(f"книг в индексе {len(ид_книг)} · файлов найдено {len(файлы)}", flush=True)

    src = np.asarray(idx.src)
    нач = np.full(idx.n, -1, dtype=np.int64)
    кон = np.full(idx.n, -1, dtype=np.int64)
    книга_кол = np.full(idx.n, -1, dtype=np.int16)
    блоки, смещения = [], [0]
    всего_нашлось = 0

    for номер, ид in enumerate(ид_книг):
        имя = имена.get(ид, ид)
        файл = файлы.get(имя)
        поле = np.flatnonzero(src == номер)
        if файл is None or not len(поле):
            блоки.append(b"")
            смещения.append(смещения[-1])
            print(f"  {имя[:44]:44s} — файла нет, строк {len(поле)}", flush=True)
            continue
        текст = parse_source_file(файл)
        строки = [idx.text(int(j)) for j in поле]
        адреса = адреса_книги(текст, строки)
        нашлось = 0
        for j, а in zip(поле, адреса):
            if а is None:
                continue
            нач[j], кон[j], книга_кол[j] = а[0], а[1], номер
            нашлось += 1
        всего_нашлось += нашлось
        байты = текст.encode("utf-8")
        блоки.append(байты)
        смещения.append(смещения[-1] + len(байты))
        print(f"  {имя[:44]:44s} {нашлось:7d}/{len(поле):7d} ({100*нашлось/len(поле):5.1f}%)",
              flush=True)

    ВЫХОД.mkdir(parents=True, exist_ok=True)
    np.save(ВЫХОД / "addr_a.npy", нач)
    np.save(ВЫХОД / "addr_b.npy", кон)
    np.save(ВЫХОД / "addr_book.npy", книга_кол)
    np.save(ВЫХОД / "book_off.npy", np.asarray(смещения, dtype=np.int64))
    (ВЫХОД / "books_blob.bin").write_bytes(b"".join(блоки))
    (ВЫХОД / "meta.json").write_text(json.dumps(
        {"n": int(idx.n), "книг": len(ид_книг), "с_адресом": int(всего_нашлось),
         "штамп": f"{idx.n}@{getattr(idx, 'built_at', '')}"}, ensure_ascii=False), "utf-8")
    размер = sum(p.stat().st_size for p in ВЫХОД.iterdir()) / 1024 / 1024
    print(f"адреса: {всего_нашлось} из {idx.n} ({100*всего_нашлось/idx.n:.1f}%) · "
          f"{размер:.0f} МБ в {ВЫХОД} · ВСЕГО {time.time()-t0:.0f}с", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(построить())
