#!/bin/zsh
# nakedlunch — установка в один двойной клик.
#
# ЧТО ОН ДЕЛАЕТ. Находит подходящий Python, собирает окружение рядом с
# программой, ставит зависимости, показывает опись данных и запускает.
# Больше ничего от человека не требуется.
#
# ЧЕГО ОН НЕ ТРЕБУЕТ. Node. Собранный интерфейс лежит в репозитории — среда
# сборки нужна только тому, кто правит исходники интерфейса.
#
# ПОЧЕМУ ПОИСК ПИТОНА, А НЕ «поставь 3.12». Ядро написано синтаксисом 3.10, и
# любой из 3.10, 3.11, 3.12, 3.13 подойдёт. Требовать ровно одну версию значит
# посылать в установку того, у кого уже есть годная.

set -e
ROOT="${0:A:h}"
cd "$ROOT"

echo "nakedlunch — установка"
echo "  папка: $ROOT"
echo

# ------------------------------------------------------------------ питон

PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 \
            /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  bin=$(command -v "$cand" 2>/dev/null) || continue
  # версию спрашиваем У САМОГО ИНТЕРПРЕТАТОРА, а не по имени файла: python3.12
  # в PATH бывает ссылкой куда угодно
  if "$bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$bin"; break
  fi
done

if [ -z "$PY" ]; then
  echo "НЕ НАШЁЛ ПОДХОДЯЩИЙ PYTHON."
  echo
  echo "Нужен 3.10 или новее. Проверены: python3.13, python3.12, python3.11,"
  echo "python3.10, python3 и обычные места Homebrew."
  echo
  echo "Поставь любым способом:"
  echo "  · с сайта python.org (кнопка Download, поставится сам)"
  echo "  · или через Homebrew:  brew install python@3.12"
  echo
  echo "Потом запусти этот файл ещё раз."
  echo
  echo "Enter — закрыть."
  read -r _
  exit 1
fi

echo "питон: $("$PY" -V 2>&1)  ($PY)"

# ------------------------------------------------------------- окружение

if [ -x ".venv/bin/python" ] && \
   .venv/bin/python -c 'import flask, pymorphy3, wordfreq' 2>/dev/null; then
  echo "окружение: уже собрано"
else
  echo "окружение: собираю…"
  rm -rf .venv
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  echo "зависимости: ставлю (это разово, минуту-две)…"
  .venv/bin/pip install --quiet -r requirements.txt
  echo "окружение: готово"
fi

# ----------------------------------------------------------------- данные

echo
echo "данные:"
have_index=0
for p in core/data/nl_index core/data/nl_rhyme.jsonl data; do
  if [ -e "$p" ]; then
    printf "  %-26s %s\n" "$p" "$(du -sh "$p" 2>/dev/null | cut -f1)"
    [ "$p" = "core/data/nl_index" ] && have_index=1
  else
    printf "  %-26s нет\n" "$p"
  fi
done

if [ "$have_index" = "0" ]; then
  echo
  echo "  Корпуса ещё нет — это нормально для новой установки."
  echo "  Залей книги прямо в окне программы, остальное произойдёт само."
  echo "  Либо привези готовые данные с другой машины:"
  echo "      tools/перенос.sh развернуть /путь/к/перенос.tar"
fi

# ------------------------------------------------------------------ пуск

echo
echo "готово. запускаю…"
echo "  дальше открывай двойным кликом по nakedlunch.app"
echo
exec .venv/bin/python launch.py
