# nakedlunch installer for Windows (from GitHub Releases)
# Простой, без хуйни. Копирует бинарник в $env:LOCALAPPDATA\nakedlunch\nakedlunch.exe
# и (опционально) создаёт ярлык на Desktop с твоей иконкой.
#
# Запуск из PowerShell (в папке с релизом):
#   .\scripts\install.ps1
#
# После: nakedlunch.exe доступен, если папка в PATH, или запускай напрямую.
# Иконка: используй assets\icon\logo.jpeg — назначь на .exe или на ярлык вручную.

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$searchPaths = @(
    (Join-Path $scriptDir "nakedlunch.exe"),
    (Join-Path $scriptDir "nakedlunch-windows.exe"),
    (Join-Path $scriptDir "nakedlunch"),
    (Join-Path (Get-Location) "nakedlunch.exe")
)

$bin = $null
foreach ($p in $searchPaths) {
    if (Test-Path $p) { $bin = $p; break }
}

if (-not $bin) {
    Write-Host "Не найден бинарник (nakedlunch.exe или nakedlunch-windows.exe) в папке релиза."
    Write-Host "Положи его рядом и запусти скрипт снова."
    exit 1
}

$destDir = Join-Path $env:LOCALAPPDATA "nakedlunch"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null
$dest = Join-Path $destDir "nakedlunch.exe"

Copy-Item $bin $dest -Force

Write-Host "Готово."
Write-Host "Бинарник: $dest"
Write-Host ""
Write-Host "Иконка: assets\icon\logo.jpeg — правой кнопкой по nakedlunch.exe → Properties → Change Icon (или на ярлык)."
Write-Host ""
Write-Host "Рекомендация: добавь $destDir в PATH (System → Advanced → Environment Variables)."
Write-Host "Или просто запускай напрямую: & '$dest'"
Write-Host ""
Write-Host "Проверь: nakedlunch   (или полный путь) — должен работать /h и т.д."

# Простой ярлык на Desktop (опционально, раскомментируй если хочешь)
# $WshShell = New-Object -ComObject WScript.Shell
# $shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\nakedlunch.lnk")
# $shortcut.TargetPath = $dest
# $shortcut.IconLocation = "$scriptDir\..\assets\icon\logo.jpeg,0"
# $shortcut.Save()
