#!/usr/bin/env python3
# nakedlunch — забрать модель векторов (Раунд 61).
#
#   python tools/скачать_векторы.py
#
# ЗАЧЕМ. `core/data/navec.tar` — 51 МБ, в репозитории его нет (см. .gitignore:
# артефакты сборки). На машине разработчика он лежит с давних пор, а на
# сборочной не появлялся никогда — и спека молча собирала приложение без него.
# Цена: тема не работала ни в одном выпущенном релизе, и об этом никто не знал.
#
# Комментарий в core/embeddings.py при этом утверждал, что файл «committed».
# Не был. Такие расхождения между тем, что код о себе пишет, и тем, что есть на
# диске, — отдельный класс ошибок: они переживают любые проверки, потому что
# проверяют код, а не утверждения о нём.
#
# Модель официальная, из проекта natasha, лицензия MIT.

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
import пути  # noqa: E402,F401  (перенастраивает вывод в utf-8, см. core/пути.py)

ИМЯ = "navec_hudlit_v1_12B_500K_300d_100q.tar"
АДРЕС = f"https://storage.yandexcloud.net/natasha-navec/packs/{ИМЯ}"
ЗАПАСНОЙ = f"https://github.com/natasha/navec/releases/download/v0.10.0/{ИМЯ}"
МЕНЬШЕ_НЕ_БЫВАЕТ = 40 * 1024 * 1024      # настоящий файл ~51 МБ


def main() -> int:
    цель = пути.таблица("navec.tar")
    if цель.exists() and цель.stat().st_size >= МЕНЬШЕ_НЕ_БЫВАЕТ:
        print(f"векторы уже на месте: {цель} "
              f"({цель.stat().st_size / 1024 / 1024:.0f} МБ)")
        return 0

    цель.parent.mkdir(parents=True, exist_ok=True)
    врем = цель.with_suffix(".tar.новый")
    последняя = None
    for адрес in (АДРЕС, ЗАПАСНОЙ):
        try:
            print(f"качаю {адрес}", flush=True)
            with urllib.request.urlopen(адрес, timeout=300) as ответ, \
                 врем.open("wb") as вых:
                while кусок := ответ.read(1 << 20):
                    вых.write(кусок)
        except Exception as e:                                   # noqa: BLE001
            последняя = e
            print(f"  не вышло: {e}", file=sys.stderr, flush=True)
            врем.unlink(missing_ok=True)
            continue

        # РАЗМЕР ПРОВЕРЯЕМ ДО ПОДМЕНЫ. Зеркало может отдать страницу ошибки с
        # кодом 200; сохранив её под нужным именем, мы получили бы «файл есть»
        # при неработающей теме — то есть ровно ту тихую поломку, ради которой
        # этот скрипт и написан.
        размер = врем.stat().st_size
        if размер < МЕНЬШЕ_НЕ_БЫВАЕТ:
            print(f"  скачано всего {размер} байт — это не модель",
                  file=sys.stderr, flush=True)
            врем.unlink(missing_ok=True)
            последняя = ValueError(f"слишком маленький файл: {размер} байт")
            continue

        врем.replace(цель)
        print(f"векторы: {размер / 1024 / 1024:.0f} МБ в {цель}")
        return 0

    print(f"векторы скачать не удалось: {последняя}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
