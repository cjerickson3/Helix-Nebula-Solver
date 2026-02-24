# Callan Nebula Puzzle Solver

A computer-vision puzzle solver that detects individual pieces from a photo of a disassembled jigsaw, classifies edges, and reassembles the puzzle automatically.

---

## Project Status

| Area | Status |
|---|---|
| Environment | uv + Python 3.13.1 (.venv) |
| Core solver | Working — tested on sample images |
| CLI entry point | Working (`src/main_no_gui.py`) |
| GUI entry point | Untested (`src/main.py`, requires PyQt5 display) |
| Profiling entry point | Requires `pycallgraph2` + graphviz (not installed) |
| Larger puzzle (WIP) | In progress — see `larger-puzzle` branch |

---

## Repository Layout

```
Solver/
├── src/
│   ├── main.py              # GUI entry point (PyQt5)
│   ├── main_no_gui.py       # CLI entry point
│   ├── graph_main.py        # Call-graph profiling entry point
│   ├── GUI/
│   │   ├── Viewer.py        # Main window, zoom/nav, solve buttons
│   │   ├── SolveThread.py   # Background QThread for solving
│   │   └── ScrollMessageBox.py
│   ├── Puzzle/
│   │   ├── Puzzle.py        # Core solving engine
│   │   ├── PuzzlePiece.py   # Piece model (edges, position, type)
│   │   ├── Edge.py          # Edge model (shape, color, HOLE/HEAD/BORDER)
│   │   ├── Distance.py      # Edge-matching distance functions
│   │   ├── Mover.py         # Piece alignment and rotation
│   │   ├── Extractor.py     # Contour → PuzzlePiece pipeline
│   │   ├── Enums.py         # Direction, TypeEdge, TypePiece, Strategy
│   │   └── tuple_helper.py  # Grid coordinate utilities
│   └── Img/
│       ├── filters.py       # Corner detection, edge classification
│       ├── peak_detect.py   # 1D peak detection
│       ├── GreenScreen.py   # Green-screen background removal
│       └── Pixel.py         # Pixel model with rotate/translate
├── resources/
│   ├── jigsaw-samples/      # Test input images (gitignored)
│   └── jigsaw-solved/       # Reference solved images
├── pyproject.toml           # Dependencies (uv)
└── uv.lock                  # Locked dependency graph
```

---

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync          # creates .venv and installs all dependencies
```

---

## Usage

### CLI (no GUI)

```bash
uv run python src/main_no_gui.py <image>
uv run python src/main_no_gui.py -g <image>   # green-screen background removal
```

Output images are written to `/tmp/` (`stick*.png`, `colored*.png`).

### GUI

```bash
uv run python src/main.py
```

Opens a PyQt5 viewer. Use **Open** to load an image, then **Solve puzzle** or **Solve puzzle (Green Background)**.

---

## How It Works

### 1. Piece Extraction (`Extractor.py`, `Img/filters.py`)

- Threshold + morphological operations isolate piece silhouettes
- OpenCV finds contours; small noise contours are discarded
- For each contour, relative angles along the boundary are computed and Gaussian-smoothed
- 4 corners are detected by finding peaks in the angle derivative
- Each of the 4 edges is classified:
  - **BORDER** — flat (puzzle boundary)
  - **HOLE** — inward tab
  - **HEAD** — outward tab

### 2. Edge Matching (`Distance.py`)

Two modes depending on image type:

- **Generated/synthetic puzzles** — shape + color matching. Point-wise euclidean distance on edge contour points, weighted with LAB color distance (luminance dropped for lighting invariance).
- **Real photos** (`-g` flag) — color-only matching. Edge shape is unreliable on photographic textures.

### 3. Solving (`Puzzle.py`)

Two-phase strategy:

1. **BORDER** — Place corner and border pieces first. Validates each placement against possible grid dimensions. Falls back to FILL if stuck.
2. **FILL** — Place interior pieces, prioritizing positions with the most already-placed neighbors.
3. **NAIVE** — Greedy global best-match, used as a last resort.

Grid dimensions are estimated from piece counts: if there are `b` border pieces, all integer pairs `(w, h)` satisfying `b = 2(w + h - 2) + 4` are candidates, refined as corners are placed.

---

## Branches

| Branch | Purpose |
|---|---|
| `main` | Stable reference — working solver on the small Callan Nebula puzzle |
| `larger-puzzle` | WIP — adapting `Puzzle.py` for the full-size puzzle |

---

## Known Issues / Future Work

- **Hardcoded `/tmp/` output paths** — output directory should be configurable
- **`Bad_Extractor.py.py`** — dead code with a double `.py` extension; safe to delete
- **`graph_main.py`** — requires `pycallgraph2` and system `graphviz`, neither installed; add as dev deps if profiling is needed
- **`src/Path`** — a stray binary Windows PATH dump file; safe to delete
- **Root-level `main_no_gui.py`** — has hardcoded paths to an old install location; use `src/main_no_gui.py` instead
- **No logging module** — solver uses raw `print()` throughout; worth switching to `logging` for the larger puzzle work
- **Performance** — the `best_diff()` inner loop is O(pieces × rotations × neighbors); acceptable for small puzzles, will need optimization for the full Callan Nebula piece count
