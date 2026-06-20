# nakedlunch 1.2 (with Ghostty CRT design)

Local cut-up recombination tool. Pure terminal CLI. User adds their own source texts. Used lines don't repeat until cleared by period (session logs untouched).

**Pure terminal CLI only** (radical minimal plain terminal, no TUI, no browser/GUI version — all removed).

## Run

Global (recommended):
```bash
nakedlunch
# or (for muscle memory)
 /nakedlunch
```
Works from any directory (new shell or `source ~/.zshrc`).

Project is minimal — only the terminal app:
- nakedlunch (script)
- core/ (cutter + generator + store)
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
- /r = remove (y/N confirm)
- /t = toggle (no confirm)
- /dir = open program dir (~/Documents/nakedlunch)
- /memory [never|3m|...] = sessions retention (delete old session files after N; never = keep forever)
- /l ru|en = interface language for messages and /h (commands stay English)
- /q = quit

Data dir (self-created on first run): ~/Documents/nakedlunch/
- data/ : state (user sources)
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

## GitHub Releases
- v1.2 is the clean release matching the local machine setup.
- Source + design/ folder (exact Ghostty CRT visual).
- Attached working macOS binary.
- For the beautiful look: copy from `design/` as described in design/README.md.
- pip install nakedlunch==1.2 also works (then apply the design).

The same icon assets live in `assets/icon/` (icns / png ready; .ico you can generate from the png in 10 seconds when needed for a Windows build).

pip still works as a zero-friction alternative (if you have Python):
```
python3 -m pip install nakedlunch
nakedlunch
```
It starts empty; user adds their own source texts.

## Ghostty CRT design

The exact visual setup (shaders, 4:3 centered text area, effects) is preserved in the `design/` folder in this repo.

See design/README.md for the files and how to apply the wrapper + config.

The design works with the nakedlunch binary from the release. Visual is independent.

## License

This software is licensed for **personal, non-commercial use only**.
See the [LICENSE](LICENSE) file for full terms.

