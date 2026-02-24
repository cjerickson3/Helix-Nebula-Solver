# Claude Context — Callan Nebula Puzzle Solver

## Project Path
```
C:/Users/chris/Documents/Puzzles/Callan_Nebula/Solver/
```

## Environment Setup
uv is installed at `~/.local/bin` and may not be on PATH in a fresh shell. Always run:
```bash
export PATH="$HOME/.local/bin:$PATH"
```
Then use `uv run python ...` for all Python execution.

## Running the Solver
```bash
uv run python src/main_no_gui.py resources/jigsaw-samples/degaulle.png
uv run python src/main_no_gui.py -g <image>   # green-screen mode
```
Output images go to `C:\tmp\stick*.png`, `C:\tmp\colored*.png`.

**Note:** Python on Windows interprets `/tmp` as `C:\tmp\` (root of C: drive), NOT the MINGW
`/tmp` which maps to `C:\Users\chris\AppData\Local\Temp`.

## GitHub
- Repo: `https://github.com/cjerickson3/callan-nebula-solver` (private)
- `main` — stable working solver
- `larger-puzzle` — WIP branch for the full-size Callan Nebula puzzle

## Session 2 — What We Fixed (2026-02-23)

### Extraction now works for real photos
The non-green-screen extraction pipeline in `src/Puzzle/Extractor.py` was broken for real photos.
Three bugs were fixed (all in `generated_preprocesing()` and `__init__`):

1. **Threshold was 254 (wrong)** — only pure-white pixels were treated as background, so the
   light gray grid paper all became "foreground". Fixed with Otsu auto-threshold.

2. **No resize for large images** — green-screen mode resized to 640px but non-green-screen
   mode processed full phone photos (~4032px). A 3×3 morphological kernel does nothing at that
   scale. Fixed by resizing to 1024px wide (same approach as green-screen path).

3. **Morphological close kernel too small** — 3×3 couldn't fill specular highlight holes in the
   shiny pieces. Fixed with a proportional kernel (`image_width // 120`) and added a Gaussian
   blur before thresholding to suppress thin grid lines in the background.

Test image that works: `Old Photos/IMG_1723.JPG` (4 pieces separated, top-down, white grid bg).

### Where extraction gets to now
- 4 contours correctly found and filtered from ~25 total (grid noise removed)
- Corner detection succeeds at sigma=5 for all 4 pieces
- Solver runs but then crashes

### Next problem: solver crashes — no corner piece
The solver (`src/Puzzle/Puzzle.py:76`) requires a **corner piece** (2 flat/border edges) to
bootstrap its border-solving strategy. The 4 test pieces are all **edge pieces** (1 flat edge
each — the flat bottom). So `connected_pieces` stays empty and crashes on `connected_pieces[0]`.

**Key code location:** `Puzzle.py` lines 62–76 — the loop that finds the corner piece to start.
`piece.number_of_border()` returns 1 for all 4 pieces; the loop needs `> 1` to proceed.

**Next session plan:**
1. Either take new photos that include a true corner piece (2 flat edges), OR
2. Modify the solver to handle starting from an edge piece instead of a corner piece

### Photo tips for better extraction
- **Black felt/foam board background** — eliminates grid noise, best contrast for dark pieces
- **One piece per photo** — more pixels per piece, cleaner contours
- **Diffuse lighting** — overcast window light, or paper-diffused lamp; avoids specular highlights
- **Shoot straight down** — parallel to piece, no angle distortion
- **Matte tape trick** — cover shiny spots with matte scotch tape before shooting

## Key Files for Tuning
- `src/Puzzle/Extractor.py` — `PREPROCESS_DEBUG_MODE = 1` saves debug images to `C:\tmp\`
- `src/Img/filters.py` — corner detection sigma range (5–15), peak detection thresholds (`mph=0.3*max`)
- `src/Img/GreenScreen.py` — HSV green range and saturation factor (default 0.84) if using green-screen mode

## PyQt5 Pin
PyQt5 is pinned to `5.15.10` + `pyqt5-qt5==5.15.2` in `pyproject.toml`. Do not upgrade — newer `pyqt5-qt5` dropped Windows wheels.

## Known Junk to Ignore
- `src/Puzzle/Bad_Extractor.py.py` — dead code, double `.py` extension, ignore it
- `src/Path` — stray binary Windows PATH dump file, ignore it
- Root-level `main_no_gui.py` — has old hardcoded paths, use `src/main_no_gui.py` instead
