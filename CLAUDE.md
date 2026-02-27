# Claude Context — Helix Nebula Puzzle Solver

## Project Overview
This is a computer-vision jigsaw puzzle solver built for the **Helix Nebula** (NGC 7293) puzzle — a large,
complex puzzle with iridescent/teal pieces. The project has two tracks:
1. **Working solver** (`main` branch) — functional on small test images
2. **Larger puzzle effort** (`larger-puzzle` branch) — adapting the solver for the full puzzle,
   which requires a SQLite database, light-box photography pipeline, and smarter pre-filtering

## Project Path (Windows)
```
C:/Users/chris/Documents/Puzzles/Helix_Nebula/Solver/
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
- Repo: `https://github.com/cjerickson3/callan-nebula-solver` (note: repo name still uses old working title)
- `main` — stable working solver on small Helix Nebula test image
- `larger-puzzle` — WIP branch for the full-size puzzle

## Repository Layout
```
Solver/
├── src/
│   ├── main.py              # GUI entry point (PyQt5)
│   ├── main_no_gui.py       # CLI entry point (use this one)
│   ├── graph_main.py        # Call-graph profiling (needs pycallgraph2 + graphviz)
│   ├── GUI/
│   │   ├── Viewer.py        # Main window, zoom/nav, solve buttons
│   │   ├── SolveThread.py   # Background QThread for solving
│   │   └── ScrollMessageBox.py
│   ├── Puzzle/
│   │   ├── Puzzle.py        # Core solving engine (border-first, then fill)
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

## How the Solver Works

### 1. Piece Extraction (`Extractor.py`, `Img/filters.py`)
- Gaussian blur → Otsu auto-threshold → morphological close/open → contour detection
- Small/noise contours discarded; pieces kept if area > 1/3 of second-largest contour
- Corner detection: relative angles along boundary, Gaussian-smoothed, peaks found at sigma=5
- Each of 4 edges classified: **BORDER** (flat), **HOLE** (inward tab), **HEAD** (outward tab)

**Key constants:**
- Resize target: 1024px wide for real photos, 640px for green-screen
- Blur kernel: `image_width // 200` (odd, min 3)
- Close kernel: `image_width // 120` (min 3)
- `PREPROCESS_DEBUG_MODE = 1` in `Extractor.py` saves debug images to `C:\tmp\`

### 2. Edge Matching (`Distance.py`)
Two modes:
- **Generated/synthetic** (`generated_edge_compute`): shape + color. Point-wise contour distance
  weighted with LAB color distance (luminance dropped for lighting invariance). Sigmoid-scaled
  shape score blended in.
- **Real photos** (`-g` flag, `real_edge_compute`): color-only matching via LAB euclidean
  distance (luminance dropped). Edge shape is unreliable on photographic textures.

**Performance note:** The `best_diff()` inner loop in `Puzzle.py` is O(pieces × rotations × neighbors).
Fine for small puzzles; needs pre-filtering for the full Helix Nebula piece count.

### 3. Solving (`Puzzle.py`)
Three-phase strategy:
1. **BORDER** — place corner piece first (requires `piece.number_of_border() > 1`), then border
2. **FILL** — interior pieces, prioritizing positions with most already-placed neighbors
3. **NAIVE** — greedy global best-match, last resort

Grid dimensions estimated from border piece count: find all `(w, h)` where `b = 2(w + h - 2) + 4`.

---

## Piece Terminology
- **Tab** = protrusion that sticks out (HEAD)
- **Blank** = indentation/socket (HOLE)
- **Border** = flat edge (puzzle boundary)
- **Topology** = the pattern of tabs/blanks on a piece's 4 edges, e.g. `[HEAD, HOLE, BORDER, HEAD]`
- **Excel-style labeling**: A1=upper-left, B1=upper-right, A2=lower-left, B2=lower-right

---

## Physical Puzzle State (as of Feb 2026)
- **14 pages** of pieces cataloged by topology in a binder
- **Border completed** on the physical puzzle
- **Regional assemblies** in progress: Upper Left Nebula, various loose assemblies
- **Missing:** one "castle piece" (3-tab/1-blank topology) needed for the transition zone hole —
  likely in the unsorted black piece pile
- Pieces are iridescent/teal with dark background — challenging for CV due to specular highlights

---

## Larger Puzzle — Planned Architecture

The key bottleneck is O(pieces × rotations × neighbors) matching. The plan is a SQLite database
as a pre-filter to reduce the candidate pool before any expensive CV matching runs.

### Pre-filtering pipeline (most to least aggressive filter):
1. **Topology filter** — only compare edges where HEAD meets HOLE (eliminates ~75% of candidates)
2. **Color region filter** — match pieces whose color signature fits the target zone
   (teal, dark red, transition zone, etc.)
3. **Shape pre-check** — fast geometric comparison before full CV
4. **Full CV match** — `Distance.py` only runs on survivors

### Planned SQLite schema (not yet built):
```
pieces (id, page, position, topology, color_region, image_path, notes)
edges  (piece_id, direction, type, shape_blob, color_blob)
```

### Light-box photography pipeline:
- iPhone photos taken in light box with dark background
- Individual piece photos at full resolution for the database
- Existing CV pipeline (`Extractor.py`) adapted to work on single-piece photos

---

## Puzzle Image Details
- **Subject:** Helix Nebula (NGC 7293) — large planetary nebula in Aquarius, ~2.5° across
- **Source:** Believed to be a James Webb Space Telescope (JWST) image
- **Visual features:** Teal/cyan nebula ring with dark interior, red/orange central region ("Eye of God" appearance), rich background star field
- **Color regions:** Dark brown/black background corners, teal nebula ring, dark inner void, red-orange center

---

## Astrometry-Based Placement Approach (Session 3 — 2026-02-25)
New idea: use actual astronomical star positions to determine where puzzle pieces belong, bypassing or supplementing edge/color matching.

### Concept
- The Helix Nebula image has **dozens of background stars** visible in the dark regions
- Stars have precise known coordinates in astronomical catalogs (Gaia DR3, etc.)
- A **plate solution** maps every pixel in the reference image to RA/Dec sky coordinates
- If a puzzle piece photo contains identifiable stars, those stars can be matched to the catalog → piece's position in the puzzle grid is determined directly

### Why this is promising for the Helix Nebula puzzle
- Background stars are point sources — high contrast, easy to detect even on dark iridescent pieces
- Star positions are immune to the iridescent/specular highlight problem that plagues color matching
- Pieces in dark corner regions (hardest to match by color) are most likely to contain stars
- Could serve as a **zero-cost pre-filter**: pieces with stars get placed directly; remaining pieces go through the normal CV pipeline

### Proposed workflow
1. Obtain the reference JWST Helix Nebula image (plate-solved FITS or with known WCS)
2. Run star detection on each puzzle piece photo (centroiding / aperture photometry)
3. Match detected stars to reference catalog → get RA/Dec for each star on the piece
4. Back-project via plate solution → pixel coordinates in reference image → puzzle grid position
5. Store `star_positions` and `grid_position_confidence` in the SQLite `pieces` table

### Tools to investigate
- `astropy` + `photutils` — star detection and centroiding in Python
- `Astrometry.net` — automatic plate solving from star patterns
- ESA Sky / Aladin — browse reference images with WCS
- Gaia DR3 catalog — sub-milliarcsecond star positions

---

## Session History

### Session 3 — Astrometry approach (2026-02-25)
**Big new idea:** Use actual astronomical star positions to determine puzzle piece placement, bypassing the color/edge matching problem entirely for pieces containing stars.

**Key facts established:**
- The puzzle is the **Helix Nebula (NGC 7293)**, NOT the Callan Nebula (old working title was wrong)
- Source image is the **JWST NIRCam image released January 20, 2026** (NASA/ESA/CSA/STScI)
- Two puzzles in play: **Dave's puzzle** (more complete, better overhead photo) and **Chris's puzzle** (light-box rig visible, closer view of inner region)
- The two puzzles have **different die cuts** — astrometry approach is die-cut independent ✓

**Astrometry.net experiment:**
- Uploaded `Daves_progress.jpg` to `nova.astrometry.net`
- Job ID: **15291458**, Submission ID: **14456741**
- Detected **36 stars** ✓
- Job **FAILED** to plate-solve — reason: too much noise from white mat border and loose pieces confusing the star detector; also searched blind (no coordinate hint given)
- Candidate solution briefly found at RA=215.678, Dec=9.762 — this is a false match (Helix is at RA=337.4, Dec=-20.8)

**What to do next session:**
1. Open `cropped_for_astrometry.jpg` in **GIMP**
2. Use Fuzzy Select to paint white mat area **black**
3. Paint loose pieces **black**
4. Optional: boost brightness slightly with `Colors → Curves` to make faint stars pop
5. Resubmit to `nova.astrometry.net` with these **critical settings**:
   - RA = 337.4, Dec = -20.8, Radius = 2 degrees
   - Scale: 0.5 to 2.0 arcsec/pixel
6. Download `corr.fits` and `wcs.fits` from the successful solve
7. Begin writing puzzle placement code using star positions

**Helix Nebula coordinates:** RA = 337.4°, Dec = -20.8° (constellation Aquarius)

**Files:**
- `cropped_for_astrometry.jpg` — already cropped, needs GIMP cleanup before resubmit



### Session 2 — Extraction fixes (2026-02-23)
Fixed 3 bugs in `generated_preprocesing()` and `__init__` that broke real-photo extraction:
1. **Threshold was 254** → fixed with Otsu auto-threshold
2. **No resize for large images** → added resize to 1024px (phone photos were ~4032px wide;
   3×3 morphological kernels did nothing at that scale)
3. **Close kernel too small** → proportional kernel (`image_width // 120`); added Gaussian blur
   before thresholding to suppress thin grid lines in paper background

Test image that works: `Old Photos/IMG_1723.JPG` (4 pieces, top-down, white grid background)

**Status after fixes:** 4 contours correctly found, corner detection succeeds at sigma=5,
solver crashes — see known issue below.

### Known crash: no corner piece
`Puzzle.py` line 62–76 requires a corner piece (2 flat edges) to bootstrap border solving.
The 4 test pieces are all edge pieces (1 flat edge each). `connected_pieces` stays empty → crash.

**Options:**
- Take new photos including a true corner piece (2 flat edges), OR
- Modify solver to start from an edge piece instead of corner

---

## Photo Tips for Better Extraction
- **Black felt/foam board background** — eliminates grid noise, best contrast
- **One piece per photo** — more pixels per piece, cleaner contours
- **Diffuse lighting** — overcast window light or paper-diffused lamp; avoids specular highlights
- **Shoot straight down** — parallel to piece, no perspective distortion
- **Matte tape trick** — cover shiny spots with matte scotch tape before shooting

---

## Key Files for Tuning
- `src/Puzzle/Extractor.py` — `PREPROCESS_DEBUG_MODE = 1` saves debug images to `C:\tmp\`
- `src/Img/filters.py` — corner detection sigma range (5–15), peak thresholds (`mph=0.3*max`)
- `src/Img/GreenScreen.py` — HSV green range and saturation factor (default 0.84)
- `src/Puzzle/Distance.py` — `real_edge_compute` (color-only) and `generated_edge_compute`
  (shape+color); luminance always dropped from LAB for lighting invariance

---

## Dependency Notes
- **PyQt5** pinned to `5.15.10` + `pyqt5-qt5==5.15.2` — do NOT upgrade (newer versions dropped
  Windows wheels)
- `pycallgraph2` + system `graphviz` needed for `graph_main.py` but not installed

## Known Junk to Ignore
- `src/Puzzle/Bad_Extractor.py.py` — dead code, double `.py` extension
- `src/Path` — stray binary Windows PATH dump file
- Root-level `main_no_gui.py` — hardcoded old paths; use `src/main_no_gui.py` instead
