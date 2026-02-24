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
Output images go to `/tmp/stick*.png`, `/tmp/colored*.png`.

## GitHub
- Repo: `https://github.com/cjerickson3/callan-nebula-solver` (private)
- `main` — stable working solver
- `larger-puzzle` — WIP branch for the full-size Callan Nebula puzzle

## Where We Left Off
The user is working on getting the extractor to recognize **4 real puzzle piece photos**. Previously they could not tune the parameters well enough to get contour detection to work on the actual photos.

**Next session plan:**
1. User will share photos of the 4 pieces
2. Diagnose why `Extractor.py` fails to find them (likely background noise, lighting, or threshold)
3. Tune extraction parameters — key files:
   - `src/Puzzle/Extractor.py` — `PREPROCESS_DEBUG_MODE = 1` shows matplotlib debug windows mid-run; set this to see what the binary mask looks like before contour detection
   - `src/Img/filters.py` — corner detection sigma range (5–15), peak detection thresholds
   - `src/Img/GreenScreen.py` — HSV green range and saturation factor (default 0.84) if using green-screen mode

## PyQt5 Pin
PyQt5 is pinned to `5.15.10` + `pyqt5-qt5==5.15.2` in `pyproject.toml`. Do not upgrade — newer `pyqt5-qt5` dropped Windows wheels.

## Known Junk to Ignore
- `src/Puzzle/Bad_Extractor.py.py` — dead code, double `.py` extension, ignore it
- `src/Path` — stray binary Windows PATH dump file, ignore it
- Root-level `main_no_gui.py` — has old hardcoded paths, use `src/main_no_gui.py` instead
