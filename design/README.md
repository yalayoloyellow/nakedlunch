# nakedlunch v1.2 + Ghostty CRT setup

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

The wrapper uses `nakedlunch` (from PATH after `pip install .` or from release binary). Edit REAL if using custom binary path.

This folder is committed so the exact visual can be restored without loss.

Version: 1.2 (source and binary).
