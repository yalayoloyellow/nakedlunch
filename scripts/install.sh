#!/bin/sh
# nakedlunch installer (from GitHub Releases zip or extracted binary)
# Простой, без хуйни. Кладёт бинарник в ~/bin/nakedlunch и делает его исполняемым.
# Иконка: используй assets/icon/logo.jpeg (или .icns если есть) — назначь вручную в Finder (Get Info → drag icon).
#
# Запуск:
#   1. Скачай релиз (nakedlunch-*.zip или отдельный binary + этот install.sh)
#   2. Распакуй в папку
#   3. cd в эту папку
#   4. sh scripts/install.sh   (или ./scripts/install.sh)
#
# После: nakedlunch должен работать в новом терминале (если ~/bin в PATH).
# Если нет — добавь  export PATH="$HOME/bin:$PATH"  в ~/.zshrc или ~/.bash_profile и source его.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Ищем бинарник рядом со скриптом или в текущей папке (учитываем варианты имён из релиза)
BIN=""
for name in nakedlunch-macos nakedlunch-linux nakedlunch nakedlunch.exe; do
  if [ -f "$SCRIPT_DIR/$name" ]; then
    BIN="$SCRIPT_DIR/$name"
    break
  fi
  if [ -f "$(pwd)/$name" ]; then
    BIN="$(pwd)/$name"
    break
  fi
done

if [ -z "$BIN" ]; then
  echo "Не найден бинарник nakedlunch (или nakedlunch-macos / nakedlunch-linux) рядом со скриптом или в текущей папке."
  echo "Положи бинарник из релиза в ту же папку, где лежит scripts/install.sh, и запусти снова."
  exit 1
fi

DEST_DIR="$HOME/bin"
mkdir -p "$DEST_DIR"
DEST="$DEST_DIR/nakedlunch"

cp "$BIN" "$DEST"
chmod +x "$DEST"

echo "Готово."
echo "Бинарник скопирован: $DEST"
echo "Иконка: assets/icon/logo.jpeg (или .icns) — в Finder: правой кнопкой по файлу nakedlunch → Get Info → перетащи иконку в верхний левый угол."
echo ""
echo "Если ~/bin ещё не в PATH — добавь строку:"
echo '  export PATH="$HOME/bin:$PATH"'
echo "в ~/.zshrc (или ~/.bash_profile) и выполни:"
echo "  source ~/.zshrc"
echo ""
echo "Проверь: nakedlunch   (должен показать >  и работать /h)"
echo "Чтобы удалить: rm -f \"$DEST\""

# Пользователь сам решает про /usr/local/bin или sudo — здесь только user-local, без заеба.
