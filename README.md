# nakedlunch

Local cut-up recombination tool (Dada + Burroughs). 4 eternal base books always active. Used lines don't repeat until cleared by period (chat log untouched).

**Pure terminal CLI only** (radical minimal plain terminal, no TUI, no browser/GUI version — all removed).

## Run

Global (recommended):
```bash
nakedlunch
# or (for muscle memory)
 /nakedlunch
```
Works from any directory (new shell or `source ~/.zshrc`).

Project is now minimal — only the terminal app:
- nakedlunch (script)
- core/ (cutter + generator + store)
- data/base/ (4 eternal books)
- README + tests (optional)

All previous GUI/TUI/browser/_legacy/app/ migration code removed. No "old user" artifacts (you are the only user).

Direct fallback:
```bash
cd /Users/yala/nakedlunch
./nakedlunch
# or python3 nakedlunch
```

- Enter = 4 more lines
- phrase = bias
- All help via /h only. No extra/aux text on startup. Bare "nakedlunch" header.
- Sources numbered (see /s). /r and /t accept only numbers (space separated for multi). No names.
- /a = add (native file chooser immediately, no name prompt, auto name=filename, multi OK)
- /r = remove (y/N confirm, bases protected)
- /t = toggle (no confirm)
- /dir = open program dir (~/Documents/nakedlunch)
- /memory [never|3m|...] = sessions retention (delete old session files after N; never = keep forever)
- /l ru|en = interface language for messages and /h (commands stay English)
- /q = quit

Data dir (self-created on first run): ~/Documents/nakedlunch/
- data/ : state + base books
- sessions/ : lines output per session (real-time append+fsync)
- config.json : retention policy

Debug logs: logs/ (max 10 last sessions, detailed). Check them to verify all works (add/generate/clear/retention etc).

Everything in one clean REPL. No extra text ever.

## Cross-platform
Pure Python stdlib (tkinter only for optional file picker on /a). Same on macOS/Linux/Windows modern terminals. TK deprecation silenced.

## Philosophy
Feed personal associations via ragged recombinations of existing text. Radical minimalism: focus on the 4 lines + Enter, clean line, nothing extra or geeky.

## License
Local use only. Your texts stay yours.

(Note: _legacy/ holds removed GUI/browser/TUI code for reference only.)

## GitHub Releases (binaries + installers for macOS / Windows / Linux)
1. Go to Releases, pick the v1.0.0 (or latest) tag.
2. Download the archive for your OS (or the individual binary + scripts/install.*).
3. Unpack.
4. Run the installer from the release:
   - macOS / Linux: `sh scripts/install.sh`
   - Windows: PowerShell `.\scripts\install.ps1`
5. The binary is placed in ~/bin (or %LOCALAPPDATA%\nakedlunch) and made executable.
6. Icon: the one you provided (logo.jpeg) is used for the builds. After install on mac: right-click the binary in Finder → Get Info → drag assets/icon/nakedlunch.icns or logo.jpeg onto the file icon in the top-left. On Windows assign the .ico to the exe or shortcut. Linux uses the .png via .desktop if you use the full installer bits.

The same icon assets live in `assets/icon/` (icns / png ready; .ico you can generate from the png in 10 seconds when needed for a Windows build).

pip still works as a zero-friction alternative (if you have Python):
```
python3 -m pip install nakedlunch
nakedlunch
```
It will populate the 4 eternal base books on first run exactly as the binaries do.

All releases are built with the icon you gave — no extra art, no changes to behavior.

