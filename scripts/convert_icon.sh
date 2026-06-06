#!/bin/sh
# convert_icon.sh — один раз на macOS (есть sips + iconutil).
# Берёт твою иконку (logo.jpeg, которую ты дал) и делает .icns / png / (заготовка .ico).
#
# Использование:
#   1. Убедись, что assets/icon/logo.jpeg — это та иконка, которую хочешь (или поменяй путь ниже).
#   2. sh scripts/convert_icon.sh
#   3. Проверь, что появились:
#        assets/icon/nakedlunch.icns
#        assets/icon/nakedlunch.png
#   4. Для .ico (Windows) — либо используй онлайн-конвертер (png → multi-size ico),
#      либо `brew install imagemagick` и magick logo.jpeg nakedlunch.ico
#      (после этого положи .ico в assets/icon/ и закоммить).
#
# Потом при сборке PyInstaller и в релизе будут использоваться эти файлы + твоя иконка вшита в бинарники/ярлыки.

set -e

SRC="assets/icon/logo.jpeg"
OUTDIR="assets/icon"
ICONSET="$OUTDIR/nakedlunch.iconset"

if [ ! -f "$SRC" ]; then
  echo "Не найден $SRC — положи свою иконку (ту, что дал) именно по этому пути или отредактируй скрипт."
  exit 1
fi

mkdir -p "$OUTDIR" "$ICONSET"

echo "Генерирую набор PNG для iconset из $SRC ..."

# Стандартные размеры для .icns (иконки приложений). Явно просим png.
sips -z 16 16     -s format png "$SRC" --out "$ICONSET/icon_16x16.png"      >/dev/null 2>&1 || true
sips -z 32 32     -s format png "$SRC" --out "$ICONSET/icon_16x16@2x.png"    >/dev/null 2>&1 || true
sips -z 32 32     -s format png "$SRC" --out "$ICONSET/icon_32x32.png"       >/dev/null 2>&1 || true
sips -z 64 64     -s format png "$SRC" --out "$ICONSET/icon_32x32@2x.png"    >/dev/null 2>&1 || true
sips -z 128 128   -s format png "$SRC" --out "$ICONSET/icon_128x128.png"     >/dev/null 2>&1 || true
sips -z 256 256   -s format png "$SRC" --out "$ICONSET/icon_128x128@2x.png"  >/dev/null 2>&1 || true
sips -z 256 256   -s format png "$SRC" --out "$ICONSET/icon_256x256.png"     >/dev/null 2>&1 || true
sips -z 512 512   -s format png "$SRC" --out "$ICONSET/icon_256x256@2x.png"  >/dev/null 2>&1 || true
sips -z 512 512   -s format png "$SRC" --out "$ICONSET/icon_512x512.png"     >/dev/null 2>&1 || true
sips -z 1024 1024 -s format png "$SRC" --out "$ICONSET/icon_512x512@2x.png"  >/dev/null 2>&1 || true

echo "Собираю .icns ..."
iconutil -c icns "$ICONSET" -o "$OUTDIR/nakedlunch.icns"

echo "Делаю чистый PNG (512) для Linux .desktop ..."
sips -z 512 512 -s format png "$SRC" --out "$OUTDIR/nakedlunch.png" >/dev/null 2>&1 || true

echo ""
echo "Готово (mac + linux png):"
ls -l "$OUTDIR/nakedlunch.icns" "$OUTDIR/nakedlunch.png"

echo ""
echo "Для Windows .ico:"
echo "  - Самый простой: открой assets/icon/nakedlunch.png в любом редакторе/онлайн (convertio, icoconverter) → экспорт multi-size .ico"
echo "  - Или: brew install imagemagick && magick assets/icon/logo.jpeg assets/icon/nakedlunch.ico"
echo ""
echo "После получения .ico положи его в assets/icon/nakedlunch.ico и закоммить перед тегом релиза."
echo "Затем workflow сможет использовать --icon assets/icon/nakedlunch.* для каждой платформы."

# Убираем временный iconset (можно оставить для отладки)
rm -rf "$ICONSET"

echo "Всё. Теперь можно собирать релиз (иконка твоя, без хуйни)."
