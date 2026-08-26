# -*- coding: utf-8 -*-
"""ПЕРЕСБОРКА КОРПУСА ЦЕЛИКОМ: снести всё и залить заново из папки исходников.

    .venv/bin/python3 tools/пересборка_корпуса.py [папка-с-книгами]

Без аргумента берёт `тест-книги/` рядом с проектом. Требует страховочную
копию `state.json.до-пересборки` рядом со складом — без неё не стартует.

ЗАЧЕМ ЭТО ОТДЕЛЬНЫЙ ИНСТРУМЕНТ, А НЕ КНОПКА (решение 2026-08-27, закрывает
вопрос «нужен ли залп удаления» из плана, часть 23). Удаление по одному в
интерфейсе — 41 нажатие, но пересборка случается РЕДКО (смена правил нарезки)
и это операция со страховкой и полной перепечкой после. Кнопка «снести всё»
на экране — заряженное ружьё рядом с кнопкой «сгенерировать»; скрипт с
обязательной копией — та же работа без ружья.

Запускать можно повторно: если прошлый заход встал на полпути, скрипт
доснесёт остаток (включая фрагментов-сирот без книги) и зальёт заново.

ПОСЛЕ НЕГО — перепечка, порядок обязателен (индекс печётся из кэша ударений):
    .venv/bin/python3 tools/build_nl_rhyme.py            # дописать новые
    .venv/bin/python3 tools/build_nl_rhyme.py --лишнее   # выбросить мёртвые
    .venv/bin/python3 tools/build_nl_index.py            # индекс + редкость
"""
import sys
import time
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ))
sys.path.insert(0, str(КОРЕНЬ / "core"))

import nlbridge                                     # noqa: E402
from core.nlsrc.store import NakedLunchStore        # noqa: E402


def main() -> int:
    книги_папка = Path(sys.argv[1]) if len(sys.argv) > 1 else КОРЕНЬ / "тест-книги"
    книги = sorted(книги_папка.glob("*.fb2")) + sorted(книги_папка.glob("*.txt")) \
        + sorted(книги_папка.glob("*.md"))
    if not книги:
        sys.exit(f"в {книги_папка} нет книг (.fb2/.txt/.md) — нечего заливать")

    # Тот же корень, что у сервера: своя переменная → NAKEDLUNCH_HOME →
    # умолчание (~/Documents/nakedlunch/data). Разойтись с ним значило бы
    # пересобрать НЕ ТОТ склад.
    данные = nlbridge.NAKEDLUNCH_DATA
    страховка = данные / "state.json.до-пересборки"
    if not страховка.exists():
        sys.exit(f"нет страховочной копии {страховка} — сперва:\n"
                 f"    cp {данные / 'state.json'} {страховка}")

    склад = NakedLunchStore(данные)
    print(f"было: {len(склад.state.corpora)} книг, "
          f"{len(склад.state.fragments)} фрагментов\n")

    if склад.state.corpora:
        print("── СНОСИМ СТАРОЕ ──")
        for к in list(склад.state.corpora):
            склад.delete_corpus(к.id)
            print(f"   снят  {к.name[:52]:<54} −{к.fragment_count}")

    # СИРОТЫ: фрагменты, чьей книги в списке нет. Найдены при пересборке
    # 2026-08-26 — 182 865 штук от тома, у которого пропала запись книги.
    # В выдачу не попадали (маска пула строится из активных источников), но
    # лежали в state.json, в кэше ударений и в индексе мёртвым грузом.
    if склад.state.fragments:
        print(f"\n   снято сирот без книги: {len(склад.state.fragments)}")
        склад.state.fragments = []
        склад._rebuild_active_fragments()

    assert not склад.state.fragments and not склад.state.corpora, "склад не пуст"

    print(f"\n── ЗАЛИВАЕМ {len(книги)} КНИГ ──")
    t0 = time.time()
    for i, путь in enumerate(книги, 1):
        t = time.time()
        к = nlbridge.add_source_from_bytes(склад, путь.name, путь.read_bytes(),
                                           save=False)
        print(f"[{i:>2}/{len(книги)}] {путь.stem[:44]:<46} {к.fragment_count:>7} фр"
              f"  {time.time() - t:>5.1f}с  всего {len(склад.state.fragments):>9}",
              flush=True)
    склад.flush()
    print(f"\nЗАЛИТО: {len(склад.state.fragments)} фрагментов, "
          f"{len(склад.state.corpora)} книг за {time.time() - t0:.0f}с")
    вык = [к.name for к in склад.state.corpora if not к.active]
    print("выключенных:", вык or "нет — все активны")
    print("\nДальше перепечка (см. шапку файла): rhyme → --лишнее → index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
