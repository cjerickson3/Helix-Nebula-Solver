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
| `scan.py`     | load, red-channel threshold (ratio of measured backing, never Otsu), fiducial detection (red channel; corner dots vs orientation markers), sheet homography, piece extraction, pass-to-pass pairing (homography when fiducials present, `(W-x, H-y)` fallback otherwise) |
| `geometry.py` | arc-length resampling, closed-contour smoothing, rigid ICP registration, body-rectangle corner detection (+ diagonal fallback), edge split & TAB/BLANK/BORDER classification, cyclic topology signature |
| `db.py`       | SQLite schema (`sheets`, `pieces`, `edges`, `edge_matches`) and loaders; contours stored as float32 blobs |
| `pipeline.py` | orchestration: two passes → averaged contours → per-piece records → grid assignment → DB |
| `match.py`    | edge matcher: four corner-relative scalars per edge → scalar pre-filter (opposite type, length, complementary feature position, height/width; cuts ~77%) → fine polyline fit (mirror + shift search) → ranked `edge_matches`. Self-calibrates the tab/blank shadow-inflation bias. |

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
- `pipeline.classify_colour` thresholds are a first guess — calibrate against a
  sheet known to be half teal, half black.
- Guide boxes must NOT print black (they read as pieces) — faint tint or omit
  and use the acrylic jig. Fiducial corner dots: solid black, ≥ 5 mm.
- `match.py` tolerances are a first cut, validated only for mechanism (perfect
  complement → 0 px fit). Real match-quality tuning needs a solved region or the
  full piece set so true adjacencies are present in the DB.
