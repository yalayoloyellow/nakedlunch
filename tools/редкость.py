# nakedlunch — РЕДКОСТЬ: посмотреть глазами, что лежит на шкалах.
#
# ИНСТРУМЕНТ РАЗГЛЯДЫВАНИЯ, А НЕ ИСТОЧНИК ПРАВДЫ (2026-08-27). Формула, обе
# оси и разбор полос живут в `core/редкость.py` — оттуда их берёт печка
# индекса, ворота отбора и этот прогон. Здесь была ВТОРАЯ КОПИЯ формулы,
# написанная в исследовательскую ночь 2026-08-25, — два списка одного и того
# же расходятся всегда, и когда правило въехало в ядро, копия пошла под нож.
# История поправок и все замеры — в шапке core/редкость.py.
#
# С 2026-08-26 индекс несёт готовые колонки rare_word/rare_pair — прогон
# просто читает их, ничего не пересчитывая. Свой кэш в tempdir снят за
# ненадобностью (он был расходником пересчёта, пересчёта больше нет).
#
# Прогон (боевые данные только читает):
#     .venv/bin/python tools/редкость.py --ячейки слова
#     .venv/bin/python tools/редкость.py --выбор 5-10,17-18,97-98
#
# ШКАЛА: 0% — самые нередкие, 100% — самые редкие.

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "core"))

import nlindex  # noqa: E402
import пути  # noqa: E402
import редкость as R  # noqa: E402


def _колонки():
    idx = nlindex.load()
    if idx is None:
        sys.exit("индекса нет — сперва tools/build_nl_index.py")
    if getattr(idx, "rare_word", None) is None:
        sys.exit("индекс без колонок редкости — перепеки: tools/build_nl_index.py")
    return idx, np.asarray(idx.rare_word), np.asarray(idx.rare_pair)


def _слова_полосы(idx, где, мета_леммы, ids, off, сколько=8):
    if not len(где):
        return []
    из = np.concatenate([ids[off[i]:off[i + 1]] for i in где[:3000]])
    счёт = np.bincount(из, minlength=len(мета_леммы))
    return [мета_леммы[j] for j in np.argsort(-счёт)[:сколько]]


def показать_ячейки(ось: str):
    idx, слова, пара = _колонки()
    шкала = слова if ось == "слова" else пара
    мета = json.loads((пути.АРТЕФАКТЫ / "nl_index" / "meta.json").read_text("utf-8"))
    ids, off = np.asarray(idx.lem_ids), np.asarray(idx.lem_off)
    имя = "РЕДКОСТЬ СЛОВ" if ось == "слова" else "РЕДКОСТЬ СОЧЕТАНИЯ"
    print(f"\n{имя} — все сто ячеек, по 1% строк со шкалой в каждой\n")
    рнд = random.Random(17)
    for п in range(100):
        где = np.flatnonzero((шкала >= п) & (шкала < п + 1))
        if not len(где):
            continue
        сл = ", ".join(_слова_полосы(idx, где, мета["lemmas"], ids, off, 5))
        прим = idx.text(int(рнд.choice(где)))
        print(f"{п:>3}%  {сл[:46]:<48} {прим[:58]}")


def показать_выбор(выбор_слова, выбор_пара):
    idx, слова, пара = _колонки()
    мета = json.loads((пути.АРТЕФАКТЫ / "nl_index" / "meta.json").read_text("utf-8"))
    ids, off = np.asarray(idx.lem_ids), np.asarray(idx.lem_off)

    # Маска — ТА ЖЕ функция, что в воротах отбора: смотрим глазами ровно то,
    # что уедет в выдачу, а не похожее на него.
    м = np.ones(idx.n, dtype=bool)
    for шкала, полосы in ((слова, выбор_слова), (пара, выбор_пара)):
        п = R.маска_полос(шкала, полосы)
        if п is not None:
            м &= п
    где = np.flatnonzero(м)

    полоска = lambda д: "".join(  # noqa: E731
        "█" if any(a <= i < b for a, b in д) else "·" for i in range(100)) if д else "█" * 100
    Ш = 2 + 20 + 100 + 2          # отступ + подпись + сто ячеек + отступ
    доля = 100 * len(где) / idx.n if idx.n else 0
    print()
    print("┌" + "─" * Ш + "┐")
    # ВСЕ СТО ЯЧЕЕК ЦЕЛИКОМ. Полоска обрезалась на пятидесяти, и выбор «97–98»
    # в ней просто не был виден — орган управления, который не показывает
    # выбранное, хуже отсутствующего.
    print(f"│  {'РЕДКОСТЬ СЛОВ':<20}{полоска(выбор_слова)}  │")
    print(f"│  {'РЕДКОСТЬ СОЧЕТАНИЯ':<20}{полоска(выбор_пара)}  │")
    ось = "0" + " " * 23 + "25" + " " * 23 + "50" + " " * 23 + "75" + " " * 21 + "100"
    print(f"│  {'':<20}{ось[:100]:<100}  │")
    print("│" + " " * Ш + "│")
    строка = f"выбрано: {len(где)} строк · {доля:.2f}% корпуса"
    print(f"│  {строка:<{Ш - 4}}  │")
    print("└" + "─" * Ш + "┘")
    if not len(где):
        print("\n   пусто — полосы не пересекаются")
        return
    print("\nчастые слова выбранного:")
    print("   " + ", ".join(_слова_полосы(idx, где, мета["lemmas"], ids, off, 12)))
    print("\nчто пойдёт в выдачу:")
    for i in random.Random(5).sample(list(где), min(20, len(где))):
        print(f"   {idx.text(int(i))[:74]}")


def main() -> int:
    р = argparse.ArgumentParser(description="Редкость: две шкалы и их содержимое")
    р.add_argument("--ячейки", choices=["слова", "пара"], nargs="?", const="слова",
                   help="показать все сто ячеек выбранной оси")
    р.add_argument("--выбор", default="", metavar="5-10,17-18",
                   help="полосы по оси СЛОВА (разбор — core/редкость.py)")
    р.add_argument("--сочетание", default="", metavar="0-10",
                   help="полосы по оси СОЧЕТАНИЕ")
    а = р.parse_args()
    if а.ячейки:
        показать_ячейки(а.ячейки)
        return 0
    показать_выбор(R.разобрать_полосы(а.выбор), R.разобрать_полосы(а.сочетание))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
