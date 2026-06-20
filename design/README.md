# Naked Lunch CRT Design (Ghostty + Shaders)

This preserves the exact visual design we settled on:
- Fullscreen Ghostty with custom CRT shaders (in-game-crt + bloom + glow-rgbsplit)
- Narrow 4:3 centered text area via padding (for the "window" feel on 16:9)
- Specific font, colors (warm orange on near-black), cursor, etc.
- Subtle effects: top/bottom blur+distort, micro drift, light VHS wobble+wear, animated grain, vignette, etc.
- All tuned for adult stylish premium retro look, pure dark bg, no cheap effects.

## Files
- ghostty-nakedlunch-config : the full Ghostty config (copy to ~/.config/ghostty/nakedlunch )
- crt-shaders/ : the three active .glsl files (copy to ~/.ghostty-shaders/ )
- nakedlunch-ghostty-wrapper : the launch script (copy to ~/.local/bin/nakedlunch and chmod +x)

## How to restore / apply
1. cp ghostty-nakedlunch-config ~/.config/ghostty/nakedlunch
2. cp crt-shaders/*.glsl ~/.ghostty-shaders/
3. cp nakedlunch-ghostty-wrapper ~/.local/bin/nakedlunch && chmod +x ~/.local/bin/nakedlunch
4. source ~/.zshrc or open new terminal
5. Run `nakedlunch` (it will launch Ghostty with the design)

## Notes
- Shaders run on full 16:9.
- Text area is padded to ~4:3 centered.
- Wrapper forces new Ghostty window + native fullscreen.
- To update the inner app: just change the REAL= path in the wrapper (the design is independent).
- Using official latest release binary: nakedlunch-official-macos (downloaded from GitHub v1.1)
- The local dist/ and old nakedlunch-real are kept for reference.
- Current design as of 2026-06 (4:3 centered text via padding, full-screen shaders, all subtle effects).
- Design is independent of which nakedlunch binary is used inside.

To use a different version: edit REAL= in the wrapper.
The backup here is the complete design snapshot.

Keep this folder in git to never lose the visual.
