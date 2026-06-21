# nakedlunch v1.2.1 + Ghostty CRT setup

Exact files for the setup that runs when executing `nakedlunch` on this machine.

## Contents of this design
- nakedlunch-ghostty-wrapper (the launcher)
- ghostty-nakedlunch-config
- crt-shaders/ (in-game-crt.glsl, bloom.glsl, glow-rgbsplit-twitchy.glsl)

## Restore on a machine
```bash
cp nakedlunch-ghostty-wrapper ~/.local/bin/nakedlunch
chmod +x ~/.local/bin/nakedlunch
cp ghostty-nakedlunch-config ~/.config/ghostty/nakedlunch
mkdir -p ~/.ghostty-shaders
cp crt-shaders/* ~/.ghostty-shaders/
hash -r
```

Then `nakedlunch` will launch Ghostty with the current design and run the binary.

The wrapper now invokes the app via `python3 -c 'from nakedlunch import main; main()'` to avoid PATH shadowing/recursion (the wrapper itself is installed as `nakedlunch` in ~/.local/bin etc).

If you need a custom binary, edit the REAL=... line in the wrapper to a full path or different invocation.

This folder is committed so the exact visual can be restored without loss.

Version: 1.2.1 (source and binary).

**Critical fix:** Ghostty wrapper no longer causes infinite window launches (self-shadowing + PATH) and no longer fails to launch the command on macOS (uses discovered absolute path to the real nakedlunch script because of `login --noprofile --norc`). 

Copy the updated `nakedlunch-ghostty-wrapper` to `~/.local/bin/nakedlunch` (or your location) after installing the new version.
