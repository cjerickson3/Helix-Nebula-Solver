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
- Repo: `https://github.com/cjerickson3/Helix-Nebula-Solver`
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
│   │   ├── Edge.py          # Edge model (shape, color, BLANK/TAB/BORDER)
│   │   ├── Distance.py      # Edge-matching distance functions
│   │   ├── Mover.py         # Piece alignment and rotation
│   │   ├── Extractor.py     # Contour → PuzzlePiece pipeline
│   │   ├── Enums.py         # Direction, TypeEdge (TAB/BLANK/BORDER), TypePiece, Strategy
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
- Each of 4 edges classified: **BORDER** (flat), **BLANK** (inward socket), **TAB** (outward tab)

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
- **Tab** = protrusion that sticks out (TAB)
- **Blank** = indentation/socket (BLANK)
- **Border** = flat edge (puzzle boundary)
- **Topology** = the pattern of tabs/blanks on a piece's 4 edges, e.g. `[TAB, BLANK, BORDER, TAB]`
- **Excel-style labeling**: A1=upper-left, B1=upper-right, A2=lower-left, B2=lower-right

---

## Physical Puzzle State (as of Feb 2026)
- **14 pages** of pieces cataloged by topology in a binder
- **Border completed** on the physical puzzle
- **Regional assemblies** in progress: Upper Left Nebula, various loose assemblies
- **Missing:** one "castle piece" (3-TAB/1-BLANK topology) needed for the transition zone hole —
  likely in the unsorted black piece pile
- Pieces are iridescent/teal with dark background — challenging for CV due to specular highlights

---

## Larger Puzzle — Planned Architecture

The key bottleneck is O(pieces × rotations × neighbors) matching. The plan is a SQLite database
as a pre-filter to reduce the candidate pool before any expensive CV matching runs.

### Pre-filtering pipeline (most to least aggressive filter):
1. **Topology filter** — only compare edges where TAB meets BLANK (eliminates ~75% of candidates)
2. **Color region filter** — match pieces whose color signature fits the target zone
   (teal, dark red, transition zone, etc.)
3. **Shape pre-check** — fast geometric comparison before full CV
4. **Full CV match** — `Distance.py` only runs on survivors

### Generalized SQLite Schema (v2 — designed for multi-puzzle use)

The schema is designed to be **puzzle-agnostic** — any puzzle can be loaded as a `puzzle` record,
and pieces/edges/descriptors hang off that. Descriptor tracks are optional per-piece; the solver
uses whatever is available.

```sql
-- Top-level puzzle registry
CREATE TABLE puzzles (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,          -- e.g. "Helix Nebula 2000pc"
    width_pieces    INTEGER,                -- grid dimensions if known
    height_pieces   INTEGER,
    image_path      TEXT,                   -- reference solved image (if available)
    -- Astrometry fields (NULL for non-astronomical puzzles)
    ra_center       REAL,                   -- RA of image center (degrees)
    dec_center      REAL,                   -- Dec of image center (degrees)
    pixel_scale     REAL,                   -- arcsec/pixel of reference image
    wcs_fits_path   TEXT,                   -- path to WCS FITS file if obtained
    notes           TEXT
);

-- Page photos: one record per 3x3 grid photo (up to 9 pieces per page)
-- Filename convention: helix_p{page:03d}.jpg e.g. helix_p007.jpg
CREATE TABLE page_photos (
    id              INTEGER PRIMARY KEY,
    puzzle_id       INTEGER REFERENCES puzzles(id),
    page_number     INTEGER NOT NULL,
    image_path      TEXT NOT NULL,          -- full path to original 3x3 page photo
    photographed_at TIMESTAMP,
    piece_count     INTEGER,                -- how many pieces on this page (1-9)
    notes           TEXT,
    UNIQUE(puzzle_id, page_number)
);

-- One record per physical puzzle piece
-- Human-readable piece ID: "{page}-{cell}" e.g. "7-C3"
CREATE TABLE pieces (
    id              INTEGER PRIMARY KEY,
    puzzle_id       INTEGER REFERENCES puzzles(id),
    -- Physical cataloging
    page_photo_id   INTEGER REFERENCES page_photos(id),
    binder_page     INTEGER NOT NULL,
    binder_position TEXT NOT NULL,          -- Excel-style cell: A1-C3
    piece_label     TEXT GENERATED ALWAYS AS
                    (binder_page || '-' || binder_position) STORED,  -- e.g. "7-C3"
    image_path      TEXT,                   -- path to cropped individual piece image
    -- Topology (tab/blank/border pattern)
    topology        TEXT,                   -- e.g. "TAB,BLANK,BORDER,TAB" (N,E,S,W order)
    n_tabs         INTEGER,
    n_blanks         INTEGER,
    n_borders       INTEGER,
    piece_type      TEXT,                   -- CORNER, EDGE, INTERIOR
    -- Orientation (for puzzles where up/down is determinable)
    orientation_known   INTEGER DEFAULT 0,  -- 1 if we know which way is "up" for this piece
    north_edge      TEXT,                   -- TAB, BLANK, or BORDER (when orientation known)
    east_edge       TEXT,
    south_edge      TEXT,
    west_edge       TEXT,
    -- Placement
    grid_col        INTEGER,
    grid_row        INTEGER,
    placement_confidence REAL,
    placement_method TEXT,                  -- "astrometry","color","edge_match","pattern","human"
    notes           TEXT,
    UNIQUE(puzzle_id, binder_page, binder_position)
);

-- All detected bright point sources on a piece (stars + nebula knots)
-- Distinct from piece_stars which only contains Gaia-matched catalogued stars
CREATE TABLE piece_light_sources (
    id              INTEGER PRIMARY KEY,
    piece_id        INTEGER REFERENCES pieces(id),
    pixel_x         REAL,
    pixel_y         REAL,
    zone            TEXT,                   -- 3x3 zone "00"-"22" (col-row, top-left=00)
    flux            REAL,                   -- brightness normalized 0-1
    fwhm            REAL,                   -- point source size in pixels (small=star-like)
    is_point_source INTEGER,                -- 1=star-like, 0=extended nebula knot
    color_b_r       REAL,                   -- blue-red index (stars=blue/positive, knots~0)
    gaia_source_id  TEXT,                   -- Gaia DR3 source ID if matched (else NULL)
    gaia_magnitude  REAL                    -- Gaia G-band magnitude if matched (else NULL)
);

-- Four edges per piece
CREATE TABLE edges (
    id              INTEGER PRIMARY KEY,
    piece_id        INTEGER REFERENCES pieces(id),
    direction       TEXT,                   -- NORTH, SOUTH, EAST, WEST
    edge_type       TEXT,                   -- TAB, BLANK, BORDER
    shape_blob      BLOB,                   -- sampled contour points (numpy array)
    color_blob      BLOB,                   -- LAB color samples along edge
    -- Matching results
    best_match_edge_id  INTEGER REFERENCES edges(id),
    match_score     REAL                    -- lower = better match
);

-- Color summary descriptor (global per piece)
CREATE TABLE piece_colors (
    id              INTEGER PRIMARY KEY,
    piece_id        INTEGER REFERENCES pieces(id),
    region_label    TEXT,                   -- e.g. "teal_nebula", "dark_void", "red_center"
    lab_l_mean      REAL,
    lab_a_mean      REAL,
    lab_b_mean      REAL,
    lab_l_std       REAL,
    lab_a_std       REAL,
    lab_b_std       REAL,
    dominant_hue    REAL,                   -- HSV hue 0-360
    -- Color gradient: captures directionality of color change across the piece
    gradient_magnitude  REAL,              -- how strong the color transition is (0=uniform)
    gradient_angle_deg  REAL,              -- direction brightest->darkest (0=right, 90=up)
    -- Spatial color fingerprint: 3x3 sub-region grid, dominant hue + lightness per zone
    -- Zones numbered col-row: z00=top-left z10=top-center z20=top-right etc.
    zone_00_hue REAL, zone_00_lab_l REAL,  -- top-left
    zone_10_hue REAL, zone_10_lab_l REAL,  -- top-center
    zone_20_hue REAL, zone_20_lab_l REAL,  -- top-right
    zone_01_hue REAL, zone_01_lab_l REAL,  -- mid-left
    zone_11_hue REAL, zone_11_lab_l REAL,  -- center
    zone_21_hue REAL, zone_21_lab_l REAL,  -- mid-right
    zone_02_hue REAL, zone_02_lab_l REAL,  -- bottom-left
    zone_12_hue REAL, zone_12_lab_l REAL,  -- bottom-center
    zone_22_hue REAL, zone_22_lab_l REAL   -- bottom-right
);

-- Human-assigned visual pattern tags (controlled vocabulary)
-- One row per pattern recognized on a piece — a piece can have multiple patterns
CREATE TABLE piece_patterns (
    id              INTEGER PRIMARY KEY,
    piece_id        INTEGER REFERENCES pieces(id),
    pattern_type    TEXT NOT NULL,          -- category from controlled vocabulary (see below)
    pattern_value   TEXT,                   -- specific value within that category
    location_zone   TEXT,                   -- which 3x3 zone: "00","10","20","01","11" etc.
    confidence      REAL,                   -- 1.0=certain human, <1.0=inferred by CV or LLM
    assigned_by     TEXT,                   -- "human", "cv", "llm"
    notes           TEXT
);
-- Controlled vocabulary for pattern_type/pattern_value:
--   structural:   fence, roof, stair, arch, window, column, wall, horizon
--   astronomical: star_bright, star_faint, nebula_filament, nebula_knot, void_boundary
--   color_event:  color_transition, bright_spot, dark_spot, gradient_peak
--   texture:      smooth, granular, wispy, sharp_edge, diffuse
--   landmark:     puzzle-specific e.g. "red_center_boundary", "outer_ring_edge"

-- Astrometry descriptor (only populated for astronomical puzzles)
CREATE TABLE piece_stars (
    id              INTEGER PRIMARY KEY,
    piece_id        INTEGER REFERENCES pieces(id),
    -- Star position in piece photo (pixels)
    pixel_x         REAL,
    pixel_y         REAL,
    -- Sky coordinates (from Gaia cross-match)
    ra              REAL,                   -- degrees
    dec             REAL,                   -- degrees
    gaia_source_id  TEXT,                   -- Gaia DR3 source ID
    gaia_magnitude  REAL,                   -- G-band magnitude
    -- Derived placement constraint
    implied_grid_col    REAL,               -- fractional grid position implied by this star
    implied_grid_row    REAL,
    position_residual   REAL                -- fit quality vs WCS model (arcsec)
);

-- Controlled vocabulary: terms are puzzle-specific, defined once when puzzle is set up
-- piece_patterns.pattern_value must exist here — enforces consistency across all pieces
CREATE TABLE pattern_vocabulary (
    id              INTEGER PRIMARY KEY,
    puzzle_id       INTEGER REFERENCES puzzles(id),
    pattern_type    TEXT NOT NULL,          -- broad category: "landmark", "texture", "astronomical"
    pattern_value   TEXT NOT NULL,          -- the actual tag used in piece_patterns
    description     TEXT,                   -- human-readable definition
    color_hint      TEXT,                   -- approximate color (for UI display e.g. "#00CED1")
    display_order   INTEGER,                -- suggested order for UI dropdowns
    UNIQUE(puzzle_id, pattern_type, pattern_value)
);
-- Example rows for Helix Nebula puzzle (puzzle_id=1):
-- pattern_type  | pattern_value       | description
-- --------------+---------------------+------------------------------------------
-- landmark      | red_center          | Bright red/orange central region (the pupil)
-- landmark      | dark_void           | Dark inner void with radial filaments
-- landmark      | teal_ring_inner     | Inner edge of the teal nebula ring
-- landmark      | teal_ring_outer     | Outer edge of the teal nebula ring
-- landmark      | transition_zone     | Where teal fades into dark background
-- landmark      | dark_background     | Outer dark field containing background stars
-- landmark      | outer_halo          | Faint wispy teal at image periphery
-- texture       | radial_filament     | Spoke-like filament pointing toward center
-- texture       | wispy               | Soft diffuse nebula texture
-- texture       | granular            | Coarse mottled texture in bright regions
-- astronomical  | star_bright         | Clearly visible bright background star
-- astronomical  | star_faint          | Faint but detectable background star

-- Generic extensible descriptor table for future use
-- (e.g. shape moments, texture descriptors, feature vectors)
CREATE TABLE piece_descriptors (
    id              INTEGER PRIMARY KEY,
    piece_id        INTEGER REFERENCES pieces(id),
    descriptor_type TEXT,                   -- e.g. "hu_moments", "orb_features", "edge_fft"
    descriptor_blob BLOB,                   -- serialized numpy array or JSON
    computed_at     TIMESTAMP
);

-- Useful indexes
CREATE INDEX idx_pieces_topology ON pieces(puzzle_id, topology);
CREATE INDEX idx_pieces_grid ON pieces(puzzle_id, grid_col, grid_row);
CREATE INDEX idx_piece_stars_gaia ON piece_stars(gaia_source_id);
CREATE INDEX idx_edges_piece ON edges(piece_id, direction);
CREATE INDEX idx_patterns_piece ON piece_patterns(piece_id, pattern_type);
CREATE INDEX idx_vocab_puzzle ON pattern_vocabulary(puzzle_id, pattern_type);
```

### Key design decisions
- **puzzle_id foreign key everywhere** — same codebase handles multiple puzzles cleanly
- **placement_method field** — records which descriptor track solved each piece; great for analytics
- **piece_stars table** — each star on a piece gets its own row; a piece with 3 stars gets 3 rows,
  each independently implying a grid position — agreement between them = high confidence
- **piece_descriptors** — open-ended overflow table for future descriptor types without schema changes
- **placement_confidence** — lets solver prioritize high-confidence placements first and flag
  low-confidence ones for human review

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

## Pending Tasks — START HERE next session

### 1. Gaia DR3 query code ← NEXT UP
First piece of the astrometry pipeline. Query Gaia DR3 for all stars within ~1° of the
Helix Nebula center and save as a local reference catalog.

```python
# Suggested approach using astroquery
from astroquery.gaia import Gaia
from astropy.coordinates import SkyCoord
import astropy.units as u

coord = SkyCoord(ra=337.4, dec=-20.8, unit='deg')
radius = u.Quantity(1.0, u.deg)
results = Gaia.query_object_async(coordinate=coord, radius=radius)
results.write('resources/gaia_helix_stars.fits', format='fits', overwrite=True)
```

- Store in `resources/gaia_helix_stars.fits` (add to .gitignore — data file, not code)
- Write helper module `src/Astrometry/gaia_catalog.py` to load and query the cache
- Install dependencies: `astroquery`, `astropy` via uv

### 2. Build the SQLite database
Create `src/Database/create_db.py` that:
- Creates all tables from the schema section above
- Seeds the Helix Nebula puzzle record (RA=337.4, Dec=-20.8)
- Seeds `pattern_vocabulary` with Helix-specific terms
- Outputs `resources/helix_puzzle.db`

### 3. Glowforge jig — READY TO CUT ✓
`scripts/helix_jig.svg` is complete. Cut from 1/8" basswood.
136mm × 136mm (5.35" × 5.35"). Red = cut, Blue = engrave labels.

---

## Session History

### Session 4 — Housekeeping, TAB/BLANK rename, Glowforge jig (2026-03-01)

**Completed:**
- Clarified the three Claude interfaces: Chat (this), Code tab (GUI for Claude Code), Cowork (agentic tasks)
- Established workflow: upload CLAUDE.md at start of each Chat session to restore context
- Renamed local folder `Callan_Nebula` → `Helix_Nebula` on disk
- Updated GitHub remote URL to `https://github.com/cjerickson3/Helix-Nebula-Solver`
- Committed up-to-date CLAUDE.md to repo (was behind by one session)
- **TAB/BLANK rename complete** — wrote `scripts/rename_terminology.py`, ran it, verified solver
  still runs correctly on degaulle.png test image, committed and pushed
  - Files changed: `Enums.py`, `Edge.py`, `Puzzle.py`, `filters.py`
  - `PuzzlePiece.py` and `Distance.py` had no HEAD/HOLE references — unchanged
- Moved `rename_terminology.py` to `scripts/` folder (established scripts/ as home for utilities)
- **Glowforge SVG jig complete** — `scripts/helix_jig.svg` ready to cut
  - 136mm × 136mm (5.35" × 5.35"), 1/8" basswood
  - 3×3 grid, 38mm cells, 3mm walls, 8mm margin
  - Labels A1-C3 engraved (blue), cell openings and outer border cut (red)
  - No orientation notch — orientation handled computationally, not physically
  - Generator script: `scripts/make_jig_svg.py`

**Key discussion — orientation and rotation constraints:**
- Interior puzzle pieces have NO determinable orientation — must try all 4 rotations
- This is a major source of human labor and computational cost
- Strategy: layer constraints to eliminate rotations before expensive CV matching:
  1. Topology constraint first (which rotations are valid for this grid position?)
  2. Color gradient direction (which way is "toward nebula center"?)
  3. Light source / star position consistency
  4. Full CV edge matching only on surviving rotation candidates
- Asymmetric topologies (3-TAB/1-BLANK, 1-TAB/3-BLANK) constrain rotation most strongly
- Opposite-TAB pieces (TAB-BLANK-TAB-BLANK) are worst case — only 2 distinct rotations

**stale .venv warning:**
After renaming folder, git-bash may still have `VIRTUAL_ENV` set to old `Callan_Nebula` path.
Fix: `deactivate` then `source .venv/Scripts/activate` from the Helix_Nebula/Solver directory.

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

**Astrometry.net final status — SOLVED but files inaccessible:**
- Used Grok AI to clean up image → black background, no mat, no loose pieces → `Helix_black.jpg`
- Resubmitted with coordinate hints: RA=337.4, Dec=-20.8, Radius=2.0, parity=neg, use-source-extractor
- Job **15297948**, Submission **14463107** → **SOLVER COMPLETED SUCCESSFULLY** ✓
- WCS file confirmed written to server
- File download endpoints returning 500/403 errors — Astrometry.net server flakiness
- Decision: **abandon Astrometry.net, move to local Gaia DR3 approach**

**Next approach — Gaia DR3 + astroquery (fully local, no CPU limits):**
- Query Gaia DR3 catalog directly for all stars within ~1° of Helix Nebula center
- Cross-match against stars detected in puzzle piece photos using `photutils`
- No external service needed, integrates directly into solver pipeline
- Helix Nebula center: **RA=337.4°, Dec=-20.8°** (constellation Aquarius)

**Files:**
- `Helix_black.jpg` — cleaned image, black background, used for successful Astrometry.net solve
- `cropped_for_astrometry.jpg` — earlier crop attempt, superseded by Helix_black.jpg



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