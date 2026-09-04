# `Scan/` — flatbed scanning pipeline

Turns the two flatbed scans of a sheet of glued-down puzzle pieces into database
records: contour, topology (cyclic TAB/BLANK/BORDER sequence), per-edge shape,
coarse colour class, and dual-pass boundary agreement.

## Usage

```bash
# from the repo root, in a fresh shell so uv is on PATH
uv run python -m Scan.pipeline PAGE_LABEL scan_a.tiff [scan_b.tiff] [--db path] [--dry-run]

# after one or more sheets are in the DB: rank candidate edge mates
uv run python -m Scan.match [--db path] [--explore] [--edge N]

# build / inspect the Spitzer reference registered to the puzzle print
uv run python -m Scan.reference [--rebuild]

# shortlist reference positions for each piece on a scan (human places from the list)
uv run python -m Scan.shortlist SCAN.png [--zone x0,y0,x1,y1] [--k 15] [--piece p03] [--out DIR]
```

- `PAGE_LABEL` — e.g. `teal-opp_p01`; becomes the `sheets.page_label` and the prefix
  of every `pieces.piece_label` (`teal-opp_p01-C3`).
- `scan_a` is the 0° pass, `scan_b` the 180° pass. With only one pass the shadow
  is not cancelled and boundary error roughly doubles.
- Default DB: `resources/helix_pieces.db` (gitignored).

## Modules

| file | responsibility |
|---|---|
| `config.py`   | every measured constant, with provenance pointing at CLAUDE.md |
| `scan.py`     | load, red-channel threshold (ratio of measured backing, never Otsu), fiducial detection (red channel; corner dots vs orientation markers), sheet homography, piece extraction, pass-to-pass pairing (homography when fiducials present, `(W-x, H-y)` fallback otherwise), per-piece colour descriptor (mean/std LAB, dominant hue, lightness gradient, 3×3 zone fingerprint) |
| `geometry.py` | arc-length resampling, closed-contour smoothing, rigid ICP registration, body-rectangle corner detection (+ diagonal fallback), edge split & TAB/BLANK/BORDER classification, cyclic topology signature |
| `db.py`       | SQLite schema (`sheets`, `pieces`, `edges`, `piece_colors`, `edge_matches`) and loaders; contours stored as float32 blobs |
| `pipeline.py` | orchestration: two passes → averaged contours → per-piece records → grid assignment → DB |
| `match.py`    | edge matcher: **feature-anchored** descriptor (baseline from the flat shoulders, x=0 at the tab/blank feature centre, compare a fixed window, ignore the corner regions) → scalar pre-filter (opposite type, neck width, peak height, shoulder length) → feature-anchored fine fit (mirror + winding + shift/scale search, RMS) → ranked `edge_matches`. Self-calibrates the tab/blank shadow-inflation bias. Improves true-mate top-5 recall but shape alone still does not discriminate on this puzzle — see Known gaps. |
| `solve.py`    | DFS grid solver (`python -m Scan.solve --sheet T03`): N/E/S/W↔edge mapping under 4 rotations, multi-seed from mutual-rank-1 edge matches, most-constrained-frontier expansion, grid-consistency backtracking, writes `pieces.placed_col/row/rotation`. Mechanically works; blocked on matcher quality (needs the colour-continuity descriptor). |
| `reference.py`| the Spitzer reference (`NASA-PIA09178.tif`) registered to the puzzle print by SIFT star matching. `puzzle_frame()` → reference in the upright puzzle frame; `register()` → the cached transform. Paths default to `../Nebula_Eye/`, override via `HELIX_REFERENCE_TIF` / `HELIX_BOX_FRONT`. Caches under `resources/`. |
| `deweave.py`  | `deweave(gray)` — FFT notch of the periodic printed-linen weave, which otherwise dominates every appearance comparison. Exposes nebula mottle + faint stars. |
| `shortlist.py`| **not a solver** — `python -m Scan.shortlist SCAN.png [--zone …]`: for each piece, the ~15 most plausible reference positions (de-weave → 4-rotation `TM_CCOEFF_NORMED` → colour gate) rendered as a strip PNG (face + candidate crops). The human makes the final placement by eye. Session 9: autonomous appearance matching does not place the teal pieces (6 methods failed); this produces the short list a human works from. |

## Verified

- `36-page1a/b` (no fiducials): 36/36 pieces, 172 µm, `(W-x, H-y)` pairing fallback.
- `T01a/b` (faint fiducials): 30/30 pieces, 5×6 grid, 171 µm, homography pairing.
- `P01a/b`, `P02a/b` (black fiducials, opposing-tab pieces): 30/30 each, 176-177 µm,
  homography pairing, **30/30 topologies correct, 0 flagged** (after template-phase
  corner detection).

## Known gaps

- **Corner detection**: `find_corners` trusts the body-rect method on clean
  pieces; the fallback runs a template-phase estimator (four evenly spaced
  markers refined to the real corners — exploits how uniform this puzzle is),
  a curvature-peak estimator, body-rect and diagonal, and keeps the best by
  `_corner_set_quality`. `pieces.corner_dev` flags anything still shaky
  (clean ≤ 0.14). The phase estimator assumes a roughly-rectangular piece with
  even edges; a wildly non-standard die-cut would need the curvature path.
- `pipeline.classify_colour` tuned against P04 (teal stock) / P06 (black stock),
  ~90% each way (`config.COLOUR_*`). The classes overlap for dark ring-interior
  teal vs faintly-green black, so that is close to the mean-LAB ceiling; a
  fraction-of-green-pixels feature could push it further if ever needed.
- Guide boxes must NOT print black (they read as pieces) — faint tint or omit
  and use the acrylic jig. Fiducial corner dots: solid black, ≥ 5 mm.
- **Autonomous appearance matching does not place the low-signal pieces — six
  methods, Sessions 7–9:** shape edge matching (three ways), edge colour
  continuity, reference-image NCC (per-piece, joint-rigid, and de-weaved), and
  star point-pattern matching. The teal ring-interior pieces have almost no
  signal in shape, colour, or texture; the star field is too dense for blind
  point matching. `Scan.match` / `Scan.solve` stay useful only as a *local*
  tie-break once a piece is roughly placed. The shipped answer is
  `Scan.shortlist` (CV triage) + human placement — see CLAUDE.md, Session 9.
- `Scan/db.py` has no `ON DELETE CASCADE`; `db.delete_sheet` (called by
  `pipeline.store`) wipes a sheet + children before a re-scan.
