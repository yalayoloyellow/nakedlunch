#!/bin/zsh
# Double-clickable launcher for nakedlunch (Finder → double-click, or ./run.command).
# Runs the isolated venv's python on launch.py, which opens the native window.
HERE="${0:A:h}"
PY="$HERE/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
exec "$PY" "$HERE/launch.py"
