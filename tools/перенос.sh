#!/bin/zsh
# nakedlunch — переезд на другую машину.
#
# ЗАЧЕМ ОН ЕСТЬ. Клонировать репозиторий бесполезно: данных в нём нет и не
# будет (README, «Где живут данные»). Свежий клон — это код без корпуса,
# без индекса и без истории, то есть программа, которой не из чего собирать
# строку. Всё нужное лежит рядом с программой и в ~/Documents.
#
# ЧТО ОБЯЗАТЕЛЬНО ЕДЕТ ВМЕСТЕ. Колоночный индекс. Без него программа
# поднимает словарь рифм целиком — около шести объёмов файла в памяти, — и на
# восьми гигабайтах это своп. Проверка стоит и в ядре, и в запускальщике, но
# лучше просто привезти индекс, чем упереться в отказ.
#
# ЧТО НЕ ЕДЕТ. `.venv` — в нём двоичные колёса под свою архитектуру: собранное
# на Apple Silicon не запустится на Intel. Собирается на месте одной командой,
# её печатает распаковка. `node_modules` и `dist` — тоже: фронт соберётся сам.
#
# Использование:
#   собрать:    tools/перенос.sh упаковать [куда.tar]
#   развернуть: tools/перенос.sh развернуть куда.tar [в какую папку]

set -e
ROOT="${0:A:h:h}"

# ---------------------------------------------------------------- упаковать

упаковать() {
  local dst="${1:-$HOME/nakedlunch-перенос.tar}"
  cd "$ROOT"

  local parts=()
  local missing=()
  for p in core/data data; do
    [ -e "$p" ] && parts+=("$p") || missing+=("$p")
  done
  if [ -d "$HOME/Documents/nakedlunch" ]; then
    # BSD tar (он и стоит на macOS) понимает смену папки только как -C,
    # и обрабатывает её ПО ПОРЯДКУ: всё до неё берётся из корня программы.
    parts+=("-C" "$HOME" "Documents/nakedlunch")
  else
    missing+=("~/Documents/nakedlunch")
  fi

  if [ ${#parts} -eq 0 ]; then
    print -r -- "нечего паковать: ни данных, ни корпуса не найдено"
    exit 1
  fi
  if [ ${#missing} -gt 0 ]; then
    print -r -- "предупреждение: не найдено и не поедет — ${missing[*]}"
  fi

  print -r -- "пакую в $dst …"
  tar -cf "$dst" \
      --exclude='*/записи/*' \
      --exclude='.DS_Store' \
      "${parts[@]}"

  print -r -- ""
  print -r -- "готово: $dst  ($(du -h "$dst" | cut -f1))"
  print -r -- ""
  print -r -- "индекс внутри: $([ -d core/data/nl_index ] && print ДА || print 'НЕТ — на слабой машине программа откажется стартовать')"
  print -r -- ""
  print -r -- "Дальше на той машине:"
  print -r -- "  git clone https://github.com/yalayoloyellow/nakedlunch.git"
  print -r -- "  cd nakedlunch && tools/перенос.sh развернуть /путь/к/$(basename "$dst")"
}

# --------------------------------------------------------------- развернуть

развернуть() {
  local arc="$1"
  local into="${2:-$ROOT}"
  [ -f "$arc" ] || { print -r -- "нет такого архива: $arc"; exit 1; }
  [ -f "$into/launch.py" ] || { print -r -- "это не папка программы: $into"; exit 1; }

  print -r -- "распаковываю в $into …"
  tar -xf "$arc" -C "$into"
  # корпус едет в архиве как Documents/nakedlunch — ставим его на место
  if [ -d "$into/Documents/nakedlunch" ]; then
    mkdir -p "$HOME/Documents"
    if [ -e "$HOME/Documents/nakedlunch" ]; then
      print -r -- "~/Documents/nakedlunch уже есть — оставляю ваш, привезённый лежит в $into/Documents"
    else
      mv "$into/Documents/nakedlunch" "$HOME/Documents/nakedlunch"
      rmdir "$into/Documents" 2>/dev/null || true
      print -r -- "корпус поставлен в ~/Documents/nakedlunch"
    fi
  fi

  print -r -- ""
  print -r -- "=== что приехало ==="
  for p in core/data/nl_index core/data/nl_rhyme.jsonl core/data/nl_addr data; do
    if [ -e "$into/$p" ]; then
      printf "  %-28s %s\n" "$p" "$(du -sh "$into/$p" | cut -f1)"
    else
      printf "  %-28s НЕТ\n" "$p"
    fi
  done

  print -r -- ""
  if [ ! -d "$into/core/data/nl_index" ]; then
    print -r -- "ВНИМАНИЕ: колоночного индекса нет. На машине с 8 ГБ программа"
    print -r -- "откажется стартовать — словарь рифм целиком туда не поместится."
    print -r -- "Привези core/data/nl_index или испеки здесь:"
    print -r -- "  .venv/bin/python tools/build_nl_index.py"
    print -r -- ""
  fi

  print -r -- "Осталось собрать окружение — оно НЕ едет, в нём двоичные колёса"
  print -r -- "под чужую архитектуру. Нужен Python 3.10+, разработана на 3.12:"
  print -r -- "  cd \"$into\""
  print -r -- "  python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  print -r -- ""
  print -r -- "Потом двойной клик по nakedlunch.app — или ./run.command."
}

case "${1:-}" in
  упаковать)  shift; упаковать "$@" ;;
  развернуть) shift; развернуть "$@" ;;
  *) print -r -- "tools/перенос.sh упаковать [куда.tar]"
     print -r -- "tools/перенос.sh развернуть архив.tar [папка программы]"
     exit 1 ;;
esac
