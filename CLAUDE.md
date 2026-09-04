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
- **Topology** = the pattern of tabs/blanks on a piece's 4 edges, e.g. `[TAB, BLANK, BORDER, HEAD]`
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


## CURRENT STATUS — read this first

**2026-09-02 (Session 9): reference obtained + registered. Reference NCC works on textured
regions but NOT on the featureless teal interior. The puzzle now splits into zones by
solvability — some CV-solvable, one is a hand-solve zone.**

(Session 7, 2026-08-30: scanning pipeline in the repo at `Scan/`, verified on real scans,
archival scanning of the 1000 pieces underway — see Session 7 in the history.)

- Extraction, topology, corner detection, dual-pass geometry: all solid.
- Spitzer reference `NASA-PIA09178.tif` (4279×3559, the 2007 "ssc2007-03a" MIPS+IRAC "Eye of
  God") is in `Nebula_Eye/`. **Registered to the puzzle print sub-pixel** via SIFT on the
  star field (256 RANSAC inliers) against `Box-Front.png`. Transform saved (scratchpad
  `reg_full_transform.npy`). PIA09178 ≈ box print, mild colour-grading difference only.
  Reference resolution over the puzzle ≈ **83–110 px per piece pitch**.
- NCC localization **method is sound** — positive control: a patch cut from the reference is
  re-found at peak 1.000, 0 px error.
- **NCC does NOT localize the T03 teal pieces.** Per-piece 3–5/15 (spurious). Joint rigid
  slide of all 15 as one unit: 0.17 ZNCC. FFT-de-weaved (notch the linen weave — it does
  expose real nebula mottle + faint stars visually): 0.24 ZNCC, 3/15. **Fifth method to fail
  on this piece class** (shape ×3, colour continuity, reference NCC). Cause is not the
  method: these pieces are from a near-featureless zone — under the linen weave is only a
  soft tone gradient, and the reference's ring *interior* is equally smooth.
- **Zone map (rough counts for a ~1000 pc puzzle):**

  | Zone | ~count | Signal | Status |
  |---|---|---|---|
  | Border | ~120 | topology + shape | done physically |
  | Bright teal ring (radial filaments) | ~300 | strong texture vs reference | untested — expected to work |
  | Red / orange core | ~150 | strong colour + brightness gradient | untested — expected to work |
  | Dark background | ~300 | background stars | untested — the astrometry plan; reference now ready |
  | Featureless teal interior + transition | ~150 | none (proven 5 ways) | **hand-solve zone** — T03 is this |

- **T04 ground-truth test (3 real pieces the user hand-placed on the lower-right outer
  nebula, locator = one star in a dark void):** targeted NCC restricted to that region —
  joint 0.31 ZNCC, best single piece 0.46, scale railed; star point-pattern match — a false
  10/24-inlier fit onto the *densest* patch of background star field. **Sixth method to fail.**
  The human placed all three by eye in minutes off one semantically-unique feature; the CV
  has no notion of "this configuration is distinctive".

- **CONCLUSION — the winning strategy is CV triage + shortlisting, human placement.**
  Autonomous CV placement of the low-signal zones is not achievable with this data (uniform
  die-cut, linen weave over near-featureless teal, dense star field, iridescent specular).
  What the software does, and does well:
  1. **Catalog** — the `Scan/` pipeline. Working.
  2. **Coarse zoning** — `pipeline.classify_colour` + colour gradient sort pieces into ring /
     core / background / corner.
  3. **Shortlisting** — `python -m Scan.shortlist SCAN.png [--zone x0,y0,x1,y1]`: for each
     piece, the ~15 best reference positions as image crops (de-weave → 4-rotation NCC →
     colour gate). Human picks the real one by eye. Turns "search the whole nebula" into
     "check these 15 spots".
  4. **Autonomous placement only where signal is strong** — border (done), possibly the
     bright filament ring and the red-core gradient. Not the dark starfield, not the
     featureless teal.
- A higher-res Spitzer original would sharpen the ring filaments but will not change the
  conclusion — not a blocker.

**Session 6 pivoted the project from astrometry to geometry-first solving.**
A literature survey found `puzzle-bot` (github.com/roksenhorn/puzzle-bot) reliably solves
1000-piece **all-white** puzzles from shape alone. Shape matching at this piece count is
proven. Astrometry remains a fun differentiator but is NOT the critical path — the thing
that blocked this project for two years was clean contour extraction, and that is now solved.

**Validated capture protocol:** pieces glued face-down (glue stick, removable) on magenta
card, flatbed scanned at 600 dpi, red channel thresholded, two passes per sheet with the
sheet turned 180° between them. Measured boundary repeatability **172 µm mean, 221 µm worst**
across 36 pieces.

---

## Scanning Pipeline — Measured Constants

| Quantity | Value | Notes |
|---|---|---|
| Backing, red channel | R = 167 (magenta), 193 ("Festive Red"), 170 ("Holiday Red") | measure per scan; don't hardcode. `THRESHOLD_RATIO` absorbs the stock change — no config edit |
| Puzzle pieces, red channel | R = 0–57 (dark/black), up to ~70 mean + specular spikes (light teal) | dark pieces sit far below threshold; the lightest bright-teal pieces run ~12–16% of core px above it, still extract fine (morph close fills highlight holes) |
| Threshold | R = 95 (magenta) → 110 (Festive) → 97 (Holiday) | ≈0.57 × backing mode — store the RATIO, not the absolute; auto-tracks the stock |
| Piece area | 186k–242k px | at 600 dpi |
| Largest non-piece contour (dust) | ~315 px | 3 orders of magnitude gap; segmentation is trivial |
| Piece bounding box | 24.0–29.6 mm | 23% size variation |
| Shadow ramp at piece edge | ~20 px = 0.85 mm | from ~2 mm piece thickness |
| Scanner anisotropy sx/sy | **0.99772 (−0.228%)** | multiply y by 0.99772 (or x by 1.00228) |

### Key findings
- **Fixed threshold, never Otsu.** Otsu gives 1.68% perimeter jitter on rescan; fixed gives
  0.36%. Otsu recomputes per image, so the mix of dark vs teal pieces on a sheet shifts the
  threshold and moves every boundary.
- **1200 dpi does not help.** The shadow is physical, not sampling-limited — at 1200 dpi it's
  a 40 px ramp instead of 20. Stay at 600.
- **The shadow is partly directional** (deficit 25 levels on down-facing edges, 43 on
  up-facing). The 180° second pass cancels it: averaging collapses the 18-level spread to ~3.5.
- **Contour comparison MUST use rigid ICP**, not centroid-align-then-rotate. The arc-length
  centroid of a tabbed contour is not its area centroid, and the leftover translation
  masquerades as uniform dilation. Proper ICP took the residual from 17 px to 4 px.
- **Blue backing is worse than red** (95 vs 116 levels of separation), and teal pieces sit
  close to blue. Magenta/red only.
- Anisotropy at 0.228% is ~0.43 px on a 190 px tab feature — real, but well under the 4 px
  boundary noise. Correct it because it's free and exact, but it is not the limiting factor.
  *(An earlier 4-piece estimate suggested 2%; that was noise from too small a sample.)*

### Fiducials
- Four solid black dots near the sheet corners plus one asymmetry dot, so pass A and pass B
  are distinguishable automatically
- Separated from pieces by area (~2,000 px vs ~210,000 px) — 100:1, unambiguous
- Solve a **homography** from the four corners, not a rigid transform: absorbs the small
  trapezoidal component (~8 px measured) from sheet flatness and drawing error
- Type exact coordinates in Illustrator, don't drag. Freehand gave 8.8 px / 18.5 px edge
  mismatch; typed coordinates gave 0.54 px / 8.03 px.
- Set the Illustrator document to **RGB**, not CMYK — you're designing for a scanner's red channel

### Colour constraint on magenta stock
The pipeline thresholds the **red channel**, and only cyan ink darkens red — magenta and
yellow don't touch it. So on magenta card there is **no ink that is both clearly visible to
the eye and red-channel-safe**: anything visible (grey, black, blue, green) contains cyan and
begins to look like a puzzle piece. Printers cannot print white (subtractive process).
**Therefore: do not print guide circles on the card.** Use a laser-cut placement template.

### Placement jig (supersedes printed guide circles)
- **Thin acrylic**, not 1/8" basswood — pieces are ~2 mm, so a thick template creates
  recessed wells that are fiddly to glue into
- **33 mm square holes** (largest piece measured 29.6 mm), corners slightly rounded
- **39 mm pitch** on both axes
- **5 columns × 6 rows = 30 pieces per sheet.** Five columns needs 189 mm and fits letter's
  216 mm; six columns does not, and that was the source of the old tightness.
- Guaranteed separation = pitch − hole size = **6 mm**, independent of piece size variation.
  A small piece rattling inside its hole still cannot approach its neighbour.
- ≈34 sheets for 1000 pieces

**Correction to an earlier note:** the old 36-per-sheet layout had 28.4 mm column pitch
against pieces up to 29.6 mm wide — typical clearance 2.3 mm, occasionally negative. The
36/36 extraction success was luck (wide pieces happening to sit beside narrow ones), not margin.

---

## Rotation Constraint Strategy

Interior pieces have no determinable orientation, so all four rotations must be tested.
Apply constraints cheapest-first:
1. **Topology** — which rotations are valid for this grid position?
2. **Colour gradient direction** — which way faces the nebula centre?
3. **Light source / star position consistency**
4. **Full CV edge matching**, only on surviving candidates

Asymmetric topologies (3-TAB/1-BLANK) constrain rotation most strongly. Opposite-TAB pieces
(TAB-BLANK-TAB-BLANK) are the worst case — only two distinct rotations.

**Sort by cyclic sequence, not counts.** TAB-TAB-BLANK-BLANK (adjacent) and
TAB-BLANK-TAB-BLANK (alternating) both count as "2 tabs, 2 blanks" but are different piece
classes with different constraints. The CV extracts cyclic order, a strictly finer
classification than the manual count sort; use the page's count as a cross-check on the CV.

Edge labels have no fixed compass meaning for interior pieces. Store the sequence in contour
order from an arbitrary corner and treat it as a cyclic string.

---

## Reference Image — obtained and registered (2026-09-02, Session 9)

The solve strategy is: anchor each piece to its absolute position in the source image.
Reference localization now proven to work on textured regions, not on the featureless teal
interior — see the zone map in CURRENT STATUS.

- **`Nebula_Eye/NASA-PIA09178.tif`** (4279×3559 RGB) is the reference — the 2007 Spitzer
  "ssc2007-03a" MIPS 24µm + IRAC "Eye of God". `NASA-PIA09178-cropped.tif` (4170×3129) is a
  hand crop; prefer computing the crop from the registration transform instead.
- **Registered to the puzzle print** (2026-09-02): SIFT on the star field, PIA09178 →
  `Box-Front.png` puzzle-image region, `cv2.estimateAffinePartial2D` + RANSAC, 256/918
  inliers, rotation −88.8° (box scanned portrait), scale 1.483 (box scan is higher-res than
  PIA09178). Overlay blend is ghost-free = sub-pixel. Transform: scratchpad
  `reg_full_transform.npy` (ref-full → box-crop-full, box crop = `Box-Front.png`[120:6520,
  80:4270]). The puzzle print uses ~middle 82% of PIA09178 vertically and runs ~13% past its
  left edge (pure black sky — pad it).
- **The puzzle image is the SPITZER infrared "Eye of God" — NOT any Hubble image.**
  Confirmed 2026-09-02 from `Nebula_Eye/Box-Front.png`, `Assembled-Nebula.png`, the scanned
  pieces, and now the clean SIFT registration to PIA09178.
- **The box BACK text is a Hubble caption** ("bicycle-spoke filaments", "colorful red and
  blue gas ring", "most detailed celestial images ever made") — that describes the 2003
  Hubble/Kitt Peak mosaic, not the Spitzer picture actually printed. Streamline (publisher,
  "Astrophotography" line, 1000 pc, 30"×20") mismatched picture and caption. This is what
  sent Sessions 3–7 chasing Hubble ACS FITS. **Ignore the caption; trust the picture.**
- The Hubble high-res composites (ESA `heic0307a` 8000², NOIRLab `noao0307a` 16000²) are the
  WRONG image — orange ring, blue centre.
- **Optional upgrade:** a larger Spitzer original (Spitzer Heritage Archive IRAC/MIPS
  mosaics via IRSA) would sharpen the ring filaments. Not a blocker — PIA09178 at ~83–110
  px/pitch is enough for the textured zones and more pixels will not help the featureless
  interior.
- Old MAST/HLA/FITS notes below are for the Hubble image — a dead end for this puzzle.
- MAST portal: `https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html`, search NGC 7293
- **The ACS footprint covers only the inner nebula.** The outer halo — where the unplaced
  pieces live — is the Kitt Peak part, which isn't in MAST at all. There is no single FITS
  covering the whole puzzle; chasing one is a dead end.
- Astronomical FITS render black in GIMP (32-bit float, huge dynamic range). Use astropy +
  matplotlib with an asinh/zscale stretch, or SAOImageDS9.

---

## Pending Tasks — START HERE

### 1. Cut the acrylic placement jig
Spec in the Placement jig section above. Test one row before cutting all 30 cells.

### 2. Re-scan a sheet with fiducials AND pieces together
Still the one untested combination — fiducials have only been validated on white paper,
pieces only on unmarked magenta. Send both passes (0° and 180°). Keep the existing 36a/36b
pair as a regression test that the code degrades gracefully when fiducials are absent.

### 3. Run the scanning pipeline in `Scan/`
Package lives at repo root (`Scan/`), run as `uv run python -m Scan.pipeline PAGE_LABEL a.tiff b.tiff`.
Default DB path is `resources/helix_pieces.db` (gitignored).

**Archival scan status (Session 9):** DB holds **673 pieces / 2692 edges, 23
sheets** — T02, T03, P01, P02, and **P04–P22** (568 pieces, all fiducial homography
pairing), all clean at 161–176 µm. P11 was re-scanned 2026-09-03
(`p11a/b-09-03-26-black-opposed.png`) and re-run — 174 µm, replaces the bad 2026-09-02 pass.
Still loose / not yet scanned: ~160 assembled-region pieces and ~150 border pieces in
`Nebula_Eye/` (the T03/T04-style connected regions and `Border.JPEG`).
- **`classify_colour` re-tuned Session 9** against P04 (teal stock) vs P06 (black stock):
  teal = green cast (`a < -4`, or `a<0 and a-b < -6`); dark = not-green and `L < 55`.
  **90% / 90%** on those exemplars — near the ceiling, the classes overlap in the
  `a ~ -2..-5, L ~ 40..55` band (dark ring-interior teal vs faintly-green-cast black).
  DB reclassified in place: **313 teal / 353 dark / 7 other** (was 34 / 412 / 227).
  Thresholds in `config.COLOUR_*`.
- 3-tab sheets P12–P14 have the expected shaky-corner warnings (2–5 pieces each,
  `corner_dev` up to 0.32) — documented limitation, geometry is fine.

### 4. Use the shortlisting tool; solve by zone (see the zone map + CONCLUSION in CURRENT STATUS)
Autonomous CV placement of the low-signal zones is dead (6 methods, Sessions 7–9). The
software's role is triage + shortlisting; the human places. Tooling shipped Session 9:
`Scan/reference.py` (Spitzer reference registered to the print), `Scan/deweave.py` (FFT
weave notch), `Scan/shortlist.py` (per-piece top-k reference-position crops).

**4a. Shortlist workflow (working now).**
`uv run python -m Scan.shortlist SCAN.png --zone x0,y0,x1,y1` → one strip PNG per piece:
face + the ~15 best reference positions, de-weaved 4-rotation NCC, colour-gated. Pick the
real spot by eye. `--zone` from `resources/reference_puzzle_frame.png` (6400×4190, ~165
px/pitch) cuts false peaks a lot. Tune: `FACE_PITCH_RATIO`, `COLOUR_GATE`, `HP_SIGMA` in
`shortlist.py`.

**4b. Star point-pattern matching — the ~300 dark-background pieces.** The dark pieces have
real stars against true black (unlike the teal, where de-weave "stars" are mostly noise).
De-weave → *true* point sources (aperture photometry / DoG, not a percentile count) → match
the local asterism to the registered reference star field. Worth building as a proper mode;
the T04 teal test gave a false match (dense-field overfit) but dark pieces are a better case.

**4c. Autonomous NCC — only worth trying on bright filament-ring + red-core pieces.**
Strong texture / strong colour gradient. Re-run the joint-rigid test (scratchpad
`t03_joint.py`) on a few. If ZNCC ≳ 0.5 those zones can auto-place.

**4d. Featureless teal interior + transition (~150 pc) — hand zone.** Proven CV-unsolvable
(T03, T04). Shortlist tool assists; no more solver effort here.

Shape (`Scan/match.py`), colour continuity (scratchpad `solve15.py`), DFS grid-consistency
(`Scan/solve.py`) stay as the *local* tie-break on top of whichever method placed a piece.

Session 9 scratchpad scripts (not committed — superseded by the `Scan/` modules):
`register.py`, `t03_localize.py`, `t03_joint.py`, `t03_joint_dw.py`, `t03_sanity.py`,
`deweave.py` (early), `t04_look.py`, `t04_solve.py`, `t04_stars.py`.

### 5. Later — port puzzle-bot's techniques
Read their 44-page writeup, particularly corner enhancement and side comparison. Note their
observation that small improvements to side comparison have outsized impact on solve time,
because runtime blows up as the match graph gets denser — independent confirmation of the
pre-filtering strategy.

---

## Session History

### Session 9 — Spitzer reference obtained + registered; NCC fails on featureless teal; zone strategy (2026-09-02)

**Reference obtained.** User downloaded `Nebula_Eye/NASA-PIA09178.tif` (4279×3559, the 2007
Spitzer "ssc2007-03a" MIPS 24µm + IRAC "Eye of God") + a hand crop `NASA-PIA09178-cropped.tif`.

**Registration to the puzzle print: clean.** SIFT on the star field, PIA09178 →
`Box-Front.png` puzzle-image region (`Box-Front.png`[120:6520, 80:4270], box scanned
portrait). `cv2.estimateAffinePartial2D` + RANSAC: 256/918 inliers, rot −88.8°, scale 1.483.
Overlay blend ghost-free (sub-pixel). Confirms PIA09178 *is* the box image (mild grading
diff only). Transform saved: scratchpad `reg_full_transform.npy`. Puzzle print uses ~middle
82% of PIA09178 vertically, runs ~13% past its left edge (black sky). Reference resolution
over the puzzle ≈ 83–110 px/pitch.

**NCC localization method verified sound** — positive control (`t03_sanity.py`): a patch cut
from the reference is re-found at peak 1.000, 0 px.

**But NCC does NOT localize the T03 teal pieces.**
- Per-piece NCC over the whole reference, 4 rotations (`t03_localize.py`): 3–5/15 in a
  grid-consistent spot, and `TM_CCORR_NORMED` scores all pinned ~0.93 (brightness-dominated,
  no discrimination on dark imagery).
- Joint rigid slide of all 15 as one unit, proper `TM_CCOEFF_NORMED` (`t03_joint.py`): joint
  ZNCC 0.17, per-piece median 0.17. The solver parks the cluster on the flattest reference
  patch.
- FFT-de-weave the linen (scratchpad `deweave.py` — regular lattice, cleanly notched; does
  expose real nebula mottle + faint stars visually) then joint NCC (`t03_joint_dw.py`):
  0.24 ZNCC, 3/15. Still no solve.
- **Fifth independent method to fail on this piece class** (shape ×3 in Sessions 7–8, colour
  continuity in Session 8, reference NCC now). Root cause: the T03 pieces are from a
  near-featureless zone — under the linen weave is only a soft tone gradient, and the
  reference's ring *interior* is equally smooth. Not a fixable data/method problem.

**Strategic outcome: zone map.** The puzzle splits by solvability — border (done),
bright teal ring / red core (strong signal, expected CV-solvable, untested), dark background
(~300 pc, star point-pattern matching — the astrometry plan, reference now ready), and the
featureless teal interior + transition (~150 pc, T03's zone, **CV-unsolvable — hand
assembly**). Full table in CURRENT STATUS.

**T04 ground-truth test — 3 real pieces the user hand-placed.** `Nebula_Eye/T04-3-of-15teal.png`
(3 interlocked teal pieces, on the black-fiducial red sheet). User placed them on the
lower-right outer nebula by eye, locator = one bright star in a dark void.
- Targeted joint NCC restricted to that region (`t04_solve.py`): joint 0.31 ZNCC, best
  single piece 0.46, scale railed to the search edge. Roughly the right area, not a lock.
- Star point-pattern match (`t04_stars.py`): RANSAC over triangle correspondences, piece
  constellation vs ~250 reference stars in the ROI. "Best" 10/24 inliers but a **false
  match** — projected the constellation onto the densest patch of background star field.
  Blind point-pattern matching is ambiguous against a dense field with uncertain piece-star
  detections (the teal-piece "stars" from de-weave are mostly noise; dark pieces will be
  cleaner).
- **Sixth method to fail on the low-signal pieces.**

**CONCLUSION: CV triage + shortlisting, human placement.** Autonomous CV placement of the
low-signal zones is not achievable with this data. Shipped Session 9:
- `Scan/reference.py` — the Spitzer reference registered to the print. `puzzle_frame()`
  returns it in the upright puzzle frame (cached `resources/reference_puzzle_frame.png`,
  6400×4190, ~165 px/pitch); `register()` caches the SIFT transform
  (`resources/reference_registration.npz`). Paths default to `../Nebula_Eye/`, override via
  `HELIX_REFERENCE_TIF` / `HELIX_BOX_FRONT`.
- `Scan/deweave.py` — `deweave(gray)` FFT notch of the periodic linen weave.
- `Scan/shortlist.py` — `python -m Scan.shortlist SCAN.png [--zone x0,y0,x1,y1] [--k 15]
  [--piece p03]`. Per piece: de-weave → 4-rotation `TM_CCOEFF_NORMED` → greedy peak pick +
  NMS → LAB colour gate → strip PNG (face + top-k reference crops, rotated to match,
  labelled rank/NCC/xy). Verified on T04: 12 candidates/piece, runs in seconds with `--zone`.
  Scores are low (0.3–0.4, honest) but the visual shortlist lets the human match the
  distinctive feature fast. Tunables: `FACE_PITCH_RATIO`, `COLOUR_GATE`, `HP_SIGMA`.

### Session 8 — Colour continuity tried; puzzle image is Spitzer; pivot to reference localization (2026-09-01/02)

**Corner detection fix + feature-anchored matcher + DFS scaffold** committed/pushed
(`c34b40a`). Corner fix: `find_corners` fast path now gates on corner turn angle, and
`_corner_set_quality` has a `_turn_penalty` — fixes the rotated-square failure on 3-tab
pieces (big tabs → big morph radius → round body → minAreaRect ~40° off). `db.delete_sheet`
added (re-scanning a sheet tripped the pieces FK). `Scan/match.py` rewritten feature-anchored
(baseline off the flat shoulders, x=0 at the feature centre, ignore corners): true-mate
top-5 recall in the T03 region 4/20 → 14/20, but prefilter power dropped and it still can't
discriminate globally. `Scan/solve.py` DFS scaffold: places T03 15/15 mechanically, ~2/15
correct (seeds on shape coincidences).

**T03 solved-region test data:** `Nebula_Eye/T03{a,b}-expanded.png` — 15 real assembled teal
pieces, glued in solved arrangement but spread apart for clean contours. Stored as sheet
`T03` with true grid. The connected-region validation set.

**Colour continuity built and tested (scratchpad `solve15.py`), caps at ~4/15.** 2D LAB
strip just inside each edge (chord-normal, past the shadow rim), scored by seam colour match
+ gradient cancellation, combined with shape, beam search + grid consistency. Strong-signal
joins rank top few % (F1-G1, D3-E3, C2-C3, E1-E2, A2-B2); ~half the joins in this uniform
teal patch have negligible colour signal (rank 400-1100). The directional edge shadow
corrupts the L channel on vertical joins — fix is pass-A/B colour-strip averaging (attempt
had a grid-pairing bug on the staggered layout). **Local matching, shape or colour, is not
enough on this puzzle.**

**Puzzle image identified: SPITZER infrared, not Hubble.** `Box-Front.png` / `Assembled-
Nebula.png` / the pieces are all teal-ring + red-centre = Spitzer "Eye of God". The box-back
text is a Hubble caption (bicycle-spoke filaments, red/blue gas ring) — a Streamline
publisher mismatch that sent Sessions 3-7 after Hubble ACS FITS. Hubble high-res composites
(ESA heic0307a 8000², NOIRLab noao0307a 16000²) are the wrong (orange/blue) image.

**Decision: pivot to reference-image localization.** Anchor each piece to its absolute
position in the Spitzer source (patch NCC for textured pieces, star point-pattern for dark
ones); shape+colour only refine. Robust to low local texture — which is the failure mode.
Blocker: get a high-res Spitzer Helix image (user working on it 2026-09-02+; `Box-Front.png`
5100×6600 is a stopgap). New files in `Nebula_Eye/`: `Box-Front.png`, `Box-Back.png`,
`Assembled-Nebula.png`, `Border.JPEG`.

### Session 7 — Archival scanning begins; pipeline in-repo and verified (2026-08-30)

**Adhesive solved.** Glue stick hardens after a few days and tears the piece face on
removal. Switched to Aleene's "Tack-It Over & Over" (repositionable). All 36 pieces came off
the original glue-stick test page cleanly once the page was a smoother card stock —
construction paper is the worst case; do not clear-coat it, just use card stock.

**Card stock is now "Festive Red", cut down to fit the printer.** Backing red-channel level
measured 193 on the T01 sheet vs 167 on the older magenta — the `THRESHOLD_RATIO` design
absorbs this (threshold tracked 95→110 automatically). Guide boxes and page text print in a
**blue** outline colour: both blue and beige sit safely above the red-channel threshold
(100+ levels margin, uniform across the sheet), so the tiebreaker was human visibility and
beige lost. Keep text clear of the piece grid and the four corner fiducial zones.

**Pipeline moved into the repo as `Scan/`** (was loose files from Chat). Package: `config.py`
(measured constants), `scan.py` (load/threshold/fiducials/piece extraction/colour descriptor),
`geometry.py` (resample, ICP register, corner + edge detection), `db.py` (SQLite schema +
loader), `pipeline.py` (`python -m Scan.pipeline`), `match.py` (`python -m Scan.match`).
Leaner than the astrometry-era schema documented above — geometry is the critical path; the
star tables layer back on later.

**Colour descriptors ported in (2026-08-31):** `scan.colour_descriptor` +
`db.piece_colors` table — mean/std LAB, saturation-weighted dominant hue, a linear lightness
gradient (`gradient_magnitude` in LAB-L units across the piece, `gradient_angle_deg`
bright→dark), and a 3×3 zone hue/lightness fingerprint. Sampled from the piece *core* (mask
eroded 25 px) to keep the shadowed rim out. This is the region / landmark pre-filter — teal
ring vs red centre vs dark corners — and the anchor for the "build from the colour boundary"
solve strategy. On the 90 teal opposing-tab pieces: `gradient_magnitude` median 42
(min 6, max 130), `dominant_hue` 153-189° (all in the cyan band, as expected). The red-centre
boundary pieces, once scanned on a non-red backing, will show the strong hue split.

**Corner-detection fallback added** (in `geometry.find_corners`). Taking the four diagonal
extremes puts a marker on a tab tip whenever a tab sits near a corner (~11% of real pieces),
silently corrupting topology. Fix: recover the piece *body* by morphological open/close
(erases tabs, fills blanks), take its min-area-rect corners, snap to contour, refine by
intersecting straight-line fits to the flat stretches either side. Diagonal method kept as
fallback.

**Verified on real scans** (`Nebula_Eye/`):
- `36-page1a/b` — 36/36 pieces both passes, 36/36 paired, 6×6 grid, boundary agreement
  172 µm (worst 220). Matches the Session 6 regression figure exactly.
- `T01a/b` — 30/30, 30/30 paired, 5×6 grid, 171 µm. Wrote 30 pieces + 120 edges to
  `resources/helix_pieces.db`. `colour_class` split 20 dark / 7 other / 3 teal — the
  heuristic (`L<60→dark`; `b<-5, a<5→teal`) is still an untested first guess; the planned
  15-teal/15-black sheet is the calibration case.
- `P01a/b` (first sheet on the black-fiducial template, all opposing-tab pieces) — 30/30,
  homography pairing (residual 21 px), 177 µm, **28/30 topologies correct**, 3 flagged.
  Note A5 was deliberately tilted (going over a guide-box line) — harmless, the extractor
  never sees the boxes; won't be done again.

**Corner detection** (`geometry.find_corners`) — solved for this puzzle:
- Fast path: body-rectangle method (`_body_rect_corners` → min-area-rect). Kept when its
  `corner_spacing_cv` < 0.15 (clean piece).
- Fallback runs four estimators and picks the best by `_corner_set_quality`:
  1. **`_corners_phase`** — the workhorse. These pieces are extremely uniform, so the four
     corners split the outline into near-equal quarters. Slide four evenly spaced markers
     around the contour, score each rotation phase (convex, ~90° apart, equal radius),
     refine each to the true corner by intersecting the flat stretches either side.
     Recovers a corner that another method dragged into a deep blank.
  2. `_corners_curvature` — puzzle-bot-style per-vertex scoring + combinatorial 4-pick;
     for genuinely rotated pieces.
  3. body-rect, 4. `_fallback_diagonal`.
  `_corner_set_quality` = spacing CV + quad regularity + a hard penalty for a "corner" that
  is actually concave (in a blank) — the phase method's failure mode.
- `build_record` stores `corner_spacing_cv` as `pieces.corner_dev`; `process_sheet` warns
  above `CORNER_DEV_WARN` (0.15).
- **Result: P01 25→28→30/30, P02 28→30/30, both 0 flagged (max corner_dev 0.14).** T01
  (mixed sheet) keeps all 6 topology classes — no collapse to one type. 36-page1 regression
  36/36. Run time unchanged (~20 s/sheet). `resources/helix_pieces.db` holds P01+P02
  (60 pieces, 240 edges), all clean.
- P02-B4 is a real die-cut outlier (chunky angular tabs, stepped top edge) — corners still
  land correctly (`corner_dev` 0.04). Good sign the "extremely regular" assumption tolerates
  the actual spread.

**Edge matcher** (`Scan/match.py`, `python -m Scan.match`):
- Descriptor per edge = four corner-relative scalars: chord length, feature peak position
  along the edge (0-1), peak height, feature width. Tab/blank *shapes* here are near-
  canonical so full-profile comparison barely discriminates — the corner-relative geometry
  is the signal (a tab centred at 0.45 of its edge only mates a blank centred at 0.55).
- **Shadow-bias self-calibration:** the threshold sits partway up the ~20 px edge shadow, so
  every contour inflates outward — a tab reads ~13 px too tall, its mating blank ~13 px too
  shallow (27 px apart on P01/P02). Measured per run from the TAB−BLANK peak-height gap and
  removed before comparing. Store the mechanism, not the number.
- Two stages: scalar pre-filter (opposite type, matching length ±6%, complementary feature
  position, matching height/width) cuts **77%** of tab×blank pairs; then a fine polyline fit
  (mirror one curve, try both windings, small x/y shift search, RMS distance — puzzle-bot's
  `error_between_polylines`) ranks the survivors.
- Output: `edge_matches` table (edge_id, mate_edge_id, rank, fit_error), rebuilt each run.
- Fine fit is a rigid ICP overlay of the two edge curves (mirror one, try both windings) —
  corner-independent, RMS in px. An earlier chord-normalised metric gave true mates 17-29 px;
  ICP gets them to **4.5-8 px**.

**Edge matcher validation** (2026-08-31, against 5 ground-truth mates from the T02 partials —
`T02-A6/B6`, `B6/C6`, `A5/B5`, `D6/E6`, `C5/D5`, mapped by the user):
- True shared edges fit at **4.5-8.2 px** by ICP. Global rank of the true mate among all
  ~178 opposite-type edges: **3, 4, 5, 50, 94** → 3/5 in the top-5 (top 3%), 2/5 poor.
- **Shape fit alone does not discriminate on this puzzle.** The tabs and blanks are so
  canonical that dozens of non-mating edges also overlay to 3-5 px; the full-DB "mutual
  best match" pairs (2.4-3.1 px) are shape coincidences between unrelated pieces.
- **Corner-relative scalars are the right idea but corner detection isn't consistent
  enough** — the two pieces of a true mate measure the shared edge's chord length 10-25%
  apart, which trips the length/position pre-filter. `_corners_phase` nails topology but the
  absolute corner position on a given edge wobbles.
- So the matcher is a **weak pre-filter** (top-5 of ~178 contains the truth ~60% of the
  time), not a solver. Real discrimination needs (a) a feature-anchored edge descriptor
  that trims to the tab/blank + a fixed flat margin and ignores exact corner position, and
  (b) a backtracking solver whose grid-consistency check rejects the shape coincidences
  (a candidate mate is only real if the pieces' *other* edges also form consistent
  neighbours). This is puzzle-bot's architecture.
- Next: the feature-anchored descriptor, then the DFS solver (schema has
  `pieces.placed_col/row/rotation/confidence/placement_method`).

**T03 solved-region test + feature-anchored matcher + DFS scaffold (2026-09-01):**
- **New ground-truth data:** `Nebula_Eye/T03{a,b}-expanded.png` — a real 15-piece assembled
  teal region (3-7-5 staggered shape), pieces glued in their solved arrangement but spread
  apart so `extract_pieces` gets clean per-piece contours. (Also `T03{a,b}-15Assembled.png`,
  the same 15 interlocked — kept for reference, not used; segmenting the block failed last
  session.) Pipeline: 15/15, 184 µm, 7×3 grid, stored as sheet `T03` with real
  `grid_col/row`. This is the connected-region validation set the matcher was missing.
- **Corner detection — rotated-square failure fixed.** `_body_rect_corners` runs a big
  morphological open (radius ~0.18·piece width) to erase tabs; on a 3-tab piece the tabs are
  large, the radius is large, and the eroded body is round enough that `minAreaRect` returns
  a box rotated ~40°. Its four points are still evenly arc-spaced (`corner_spacing_cv` 0.02)
  and evenly ~90° apart around the centroid, so both the fast-path gate and `_score_quad`
  accepted them — putting every "corner" mid-feature and corrupting topology + all four edge
  curves (T03-A3, T03-C2). Fix: `find_corners` fast path now also requires each body corner
  to sit on a corner-like *turn* (`_corners_are_square`, 45–120°); `_corner_set_quality`
  gained a `_turn_penalty` term (turn <40° or >122° = not a corner). A3/C2 recovered, and
  **36-page1 / T01 / P01 / P02 regression clean** (0 shaky, same topology-class counts).
- **`db.delete_sheet`** — re-scanning a sheet tripped a FK: `INSERT OR REPLACE` on `sheets`
  deletes the row from under its `pieces` (no `ON DELETE CASCADE`). `pipeline.store` now
  wipes the old sheet + children first.
- **Feature-anchored edge descriptor** (`Scan/match.py`, rewritten). Baseline from the flat
  shoulders (robust), x=0 at the tab/blank feature centre (robust), compare only a fixed
  ±175 px window around the feature, never look at the corner regions. Mirror + winding +
  small shift/scale search, RMS. **True-mate top-5 recall in the T03 region: 4/20 → 14/20**
  (old corner-relative scalars vs new). BUT the scalar pre-filter lost most of its power
  (77% → ~18% of tab×blank pairs cut) because neck/peak/shoulder length barely vary on this
  puzzle, and it **still cannot discriminate globally**: `Scan.match` mutual-best pairs are
  all cross-sheet coincidences (P02↔T03 etc.) fitting at 2–3 px. Third confirmation that
  shape alone is a dead end here.
- **DFS solver scaffold** (`Scan/solve.py`, `python -m Scan.solve --db … --sheet T03`).
  Piece model with N/E/S/W↔edge-index mapping under 4 rotations; multi-seed (mutual-rank-1
  pairs first); expand most-constrained frontier cell; a placement must satisfy every shared
  edge and ≥1 must be a strong (rank ≤4) match; backtrack; keep the largest/lowest-cost
  assembly. **Mechanically places 15/15 but seeds on shape coincidences → 2/15 in correct
  relative position.** The machinery is right; the matcher input isn't good enough.
- **Verdict / next lever: edge colour–image continuity.** Adjacent pieces share continuous
  nebula texture/stars across the join — the signal this puzzle has that puzzle-bot's white
  puzzles don't, and the one the user uses by hand ("built from the colour boundary").
  Plan: sample LAB in a thin strip just inside each edge (pipeline + `edges` schema), and
  require a candidate join to match in colour along its length; shape stays a weak
  pre-filter, DFS grid-consistency on top. **Do the colour-continuity descriptor before more
  solver tuning.**

- Fiducials: the T01 sheets DO carry them (4 corner dots + 1 offset), just faint —
  they were printed in the same near-invisible blue as the guide boxes. `detect_fiducials`
  was rewritten (2026-08-30) to work on the **red channel** with the pipeline's ratio
  threshold instead of luminance greyscale (red card greyscale ≈ 95, floods a fixed grey
  threshold), plus a size split so the four large corner dots feed the homography and the
  smaller orientation dots don't. It now resolves T01a/b and drives `pair_passes` through a
  homography (pair-centroid residual 35 px → 19 px); sheets with no fiducials still fall
  back to the (W−x, H−y) map (36-page1 regression unchanged at 36/36, 172 µm).

**Fiducial / template design decisions (2026-08-30):**
- **Corner dots: solid black (K-only), ~5.5 mm.** The "no red-channel-safe visible ink"
  constraint is about the per-piece guide boxes (they sit under a piece and must not read
  as one); fiducials are in the margin and size-filtered ~15:1 from pieces, so black is
  fine and gives ~160 levels of red-channel separation — exposure-proof.
- **Guide boxes must stay off the red channel.** A revised template (P01) printed them
  solid black; `extract_pieces` then found 30 phantom "pieces" (one per box outline) on the
  empty sheet, and with a piece glued in, RETR_EXTERNAL traces the box not the piece. Boxes
  must be the faint blue that T01 used (box lines stayed at R ≈ 150, invisible to the
  extractor), or omitted in favour of the acrylic jig.
- Offset/asymmetry dot: keep it ≥ 8 mm from the sheet edge (P01 had it at 4.2 mm — a skewed
  scan could clip it).

**Environment rebuilt.** The old `.venv` (uv, Python 3.13.1) was dead — both that Python and
uv had been removed from the machine (now Python 3.14 via the Python Install Manager).
Reinstalled uv (`winget install astral-sh.uv`, v0.12.7), rebuilt with `uv sync --python
3.12`; pinned `pyqt5==5.15.10` installs fine on 3.12. **uv is in the WinGet packages dir —
restart the shell before `uv` is on PATH.**

**TODO carried forward:**
- `page_photos` schema comment in the astrometry schema still says "up to 9 pieces per page"
  (old 3×3 jig) — update for 30-piece scan pages if that schema is ever revived.
- Tune `classify_colour` thresholds once a labelled teal/black sheet exists.
- Archival scan order: sorted teal (opposing-tab) pieces first, then black (opposing-tab).
- Filename convention: `teal-opp_p01.tiff`, … then `black-opp_p01.tiff`, … mapping to
  `binder_page` / `binder_position`.

### Session 6 — Pivot to geometry; scanning pipeline validated (2026-08-27)

**Literature survey.** Most academic jigsaw work (Pomeranz, Gallagher, Sholomon, vision
transformers, Positional Diffusion, PuzLM) solves *square-tile* puzzles — an image chopped
into a grid, no tabs, no physical pieces. Those 22,000-piece results are not this problem.
`puzzle-bot` is the one directly comparable project: 1000-piece all-white puzzles, pure
geometry. Demaine proved the general problem NP-complete, but that's worst-case; real puzzles
have enough local structure for greedy-plus-backtracking.

**Goldberg et al. 2004** hit the identical shadow problem — ~1 mm pieces casting shadows on a
flatbed. They photocopied pieces (blank backs, red background) and scanned the copy. We took a
different route (fronts on magenta, red-channel threshold) and it works better.

**Experiments run:** red vs blue backing; Otsu vs fixed threshold; 600 vs 1200 dpi; shadow
profile and directionality; dual-pass averaging; scanner anisotropy via a rotated square target.

**Validated on the 36-piece pair:** 36/36 detected in both passes, no merges, no debris. All 36
paired uniquely under the (W−x, H−y) mapping. Sheet transform fitted at −179.98°, scale 1.0004,
3.6 px centroid residual. Boundary agreement 172 µm.

**Anisotropy calibration:** square target scanned at 0° and 90°. Two independent estimates,
−0.209% and −0.247%, agreeing to 0.04%. Mean sx/sy = 0.99772. This matches the grid sheet's
0.221% combined printer-plus-scanner figure, proving the printer contributes essentially
nothing — the 1.1% uniform oversize there was print-driver scaling, harmless because it scales
both axes equally.

**Tooling note:** files attached in a chat live in a temporary sandbox for that conversation and
have no connection to the local repo. Always upload the current CLAUDE.md at session start.


### Session 5 — Source image identified, scanner working (2026-03-01 evening)

**Key discovery — puzzle image confirmed:**
- Attribution on box: **"Photo Credit: NASA ESA/Hubble Space Telescope"**
- Publisher logo: **STREAMLINE** imaged
- Image confirmed as the **2003 "Iridescent Glory" Hubble mosaic** of Helix Nebula
  - Composite of 9 ultra-sharp Hubble ACS images + Mosaic Camera at Kitt Peak (NOAO)
  - Released May 9, 2003 for Astronomy Day
  - Credit: NASA, NOAO, ESA, Hubble Helix Nebula Team, M. Meixner (STScI), T.A. Rector (NRAO)
  - Visual: teal/cyan nebula ring with red/orange center — matches puzzle exactly
  - NOT the 2004 Cerro Tololo composite, NOT the JWST 2026 image
- Box front and back show the same image
- Box scanned portrait (5100×6600px) — box is landscape, was placed vertically on bed

**Scanner breakthrough:**
- NAPS2 installed successfully (free, open source, no HP Smart needed)
- Connected to HP OfficeJet Pro 9125e via **ESCL driver + manual IP address**
- Windows Firewall was blocking WIA/TWAIN — ESCL over network bypassed this
- Successfully scanned box art and back of box at 600 DPI
- Windows Fax and Scan not available on Windows 11 24H2 — confirmed removed from Optional Features
- NAPS2 batch scan mode will be useful for 8-pass border scan

**MAST STScI archive located:**
- URL: `https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html`
- Searched NGC 7293 — found 1273 total rows of observations
- HST: 667 observations, ACS/WFC: 133, HLA: 237, JWST: 36
- Rows 6-16 show target 69813909 at RA=22:29:38.545, Dec=-20:50:13.75 — this is NGC 7293
- **HLA (Hubble Legacy Archive)** is the best source — pre-combined mosaics with WCS embedded
- HST program **9700** likely contains the 2003 ACS mosaic data
- Will download calibrated FITS with WCS headers next session

**Astrometry pipeline update:**
- Having the original Hubble FITS with WCS means NO plate solving needed
- Every pixel in the reference image already has RA/Dec coordinates
- Puzzle piece stars → match to Gaia → back-project via WCS → grid position
- Scanner (1200 DPI, CIS sensor, no lens distortion) preferred over iPhone for star detection
- Dark background pieces (~200-300) are highest priority for this approach

**Comparison image note:**
- Image sent for comparison was Spitzer "Eye of God" infrared — NOT the puzzle image
- The puzzle uses the Hubble visible-light version (teal/cyan, not the vivid red/teal Spitzer palette)

### Session 4 — Housekeeping, TAB/BLANK rename, Glowforge jig (2026-03-01)

**Completed:**
- Clarified Claude interface differences: Chat (here), Code tab, Cowork
- Established workflow: upload CLAUDE.md at start of each Chat session
- Renamed local folder `Callan_Nebula` → `Helix_Nebula` on disk
- Updated GitHub remote URL to `https://github.com/cjerickson3/Helix-Nebula-Solver`
- **TAB/BLANK rename complete** — `scripts/rename_terminology.py` ran cleanly
  - Files changed: `Enums.py`, `Edge.py`, `Puzzle.py`, `filters.py`
  - Verified: solver runs correctly on degaulle.png after rename
  - `rename_terminology.py` moved to `scripts/` folder
- **Glowforge SVG jig complete** — `scripts/helix_jig.svg` ready to cut
  - 136mm × 136mm, 38mm cells, 3mm walls, 8mm margin, labels A1-C3
  - No orientation notch — orientation handled computationally
  - Generator: `scripts/make_jig_svg.py`

**Key discussion — orientation and rotation constraints:**
- Interior pieces have NO determinable orientation — must try all 4 rotations
- Rotation constraint strategy (apply in order before expensive CV matching):
  1. Topology constraint — which rotations are valid for this grid position?
  2. Color gradient direction — which way faces nebula center?
  3. Light source / star position consistency
  4. Full CV edge matching only on surviving candidates
- Asymmetric topologies (3-TAB/1-BLANK) constrain rotation most strongly
- Opposite-TAB pieces (TAB-BLANK-TAB-BLANK) worst case — only 2 distinct rotations

**stale .venv warning:**
After renaming folder, git-bash may have `VIRTUAL_ENV` set to old `Callan_Nebula` path.
Fix: `deactivate` then `source .venv/Scripts/activate` from Helix_Nebula/Solver directory.



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
