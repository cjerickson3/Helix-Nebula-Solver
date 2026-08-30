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

**Session 7 (2026-08-30): scanning pipeline is in the repo at `Scan/` and verified on real
scans; archival scanning of the 1000 pieces is starting.** See Session 7 in the history below.

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
| Backing (magenta card), red channel | R = 167 | measure per scan; don't hardcode |
| Puzzle pieces, red channel | R = 0–57 | teal and black both well below threshold |
| Threshold | R = 95 | ≈0.57 × backing mode — store the RATIO, not the absolute |
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

## Reference Image — background, no longer critical path

- The puzzle is the **2003 Hubble "Iridescent Glory" mosaic** of the Helix Nebula (NGC 7293)
- Box credit: "NASA ESA/Hubble Space Telescope"; publisher logo STREAMLINE
- Composite of nine Hubble ACS pointings plus the Mosaic Camera at Kitt Peak (NOAO)
- Teal/cyan ring, red/orange centre. NOT the 2004 Cerro Tololo version; NOT JWST 2026.
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
Verified end-to-end on `T01a/b` and `36-page1a/b` in Session 7 — reproduces the documented
172 µm boundary figure. Default DB path is `resources/helix_pieces.db` (gitignored).
Still to do: validate `colour_class` against a known teal/black sheet; test with fiducials present.

### 4. Later — port puzzle-bot's techniques
Read their 44-page writeup, particularly corner enhancement and side comparison. Note their
observation that small improvements to side comparison have outsized impact on solve time,
because runtime blows up as the match graph gets denser — independent confirmation of the
pre-filtering strategy.

---

## Session History

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
(measured constants), `scan.py` (load/threshold/fiducials/piece extraction), `geometry.py`
(resample, ICP register, corner + edge detection), `db.py` (SQLite schema + loader),
`pipeline.py` (`python -m Scan.pipeline`). This schema is deliberately leaner than the
astrometry-era schema still documented above — geometry is the critical path; the star
tables layer back on later.

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
