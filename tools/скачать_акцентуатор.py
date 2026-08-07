#!/usr/bin/env python3
# nakedlunch — забрать из акцентуатора только то, что используется (Раунд 60).
#
#   python tools/скачать_акцентуатор.py
#
# ЗАЧЕМ. `RUAccent.load()` при первом запуске тянет с HuggingFace около
# полутора гигабайт: модель омографов, предсказатель ударности, набор koziev.
# Программа не обращается ни к одному из них — сборка ударений использует
# готовый словарь и модель на одно слово (см. build_nl_rhyme.акцентуатор).
#
# Здесь качается ровно это: 25 МБ вместо 1.4 ГБ. Нужно и человеку, ставящему
# проект из исходников, и сборочной машине, где пакет установлен пустым.
#
# Файлы кладутся ВНУТРЬ пакета ruaccent — туда же, куда положил бы он сам,
# поэтому его собственная проверка «уже скачано» их видит и второй раз в сеть
# не идёт.

from __future__ import annotations

import sys
from pathlib import Path

# Ровно те файлы, к которым обращается наш путь.
НУЖНОЕ = [
    "dictionary/accents.json.gz",     # готовый словарь ударений
    "dictionary/yo_words.json.gz",    # восстановление ё
    "nn/nn_accent/model.onnx",        # модель на одно слово
    "nn/nn_accent/config.json",
    "nn/nn_accent/tokenizer_config.json",
    "nn/nn_accent/special_tokens_map.json",
    "nn/nn_accent/vocab.txt",
]
РЕПО = "ruaccent/accentuator"


def куда() -> Path:
    import ruaccent
    return Path(ruaccent.__file__).resolve().parent


def main() -> int:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("нет huggingface_hub — он ставится вместе с ruaccent", file=sys.stderr)
        return 1

    корень = куда()
    было = сколько = 0
    for имя in НУЖНОЕ:
        цель = корень / имя
        if цель.exists():
            было += 1
            continue
        try:
            hf_hub_download(repo_id=РЕПО, filename=имя, local_dir=str(корень))
            сколько += 1
            print(f"  забрано: {имя}", flush=True)
        except Exception as e:                                   # noqa: BLE001
            # Часть файлов у модели может называться иначе в новых версиях —
            # это не повод валить всю установку: без необязательного файла
            # модель обычно поднимается, а без обязательного упадёт понятно.
            print(f"  не вышло: {имя} ({e})", file=sys.stderr, flush=True)

    итог = sum((корень / и).stat().st_size for и in НУЖНОЕ if (корень / и).exists())
    print(f"акцентуатор: {было} уже было, {сколько} забрано, "
          f"итого {итог / 1024 / 1024:.0f} МБ в {корень}")
    обязательные = ["dictionary/accents.json.gz", "nn/nn_accent/model.onnx"]
    нет = [и for и in обязательные if not (корень / и).exists()]
    if нет:
        print(f"не хватает обязательного: {', '.join(нет)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
