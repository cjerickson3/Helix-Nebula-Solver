# `Scan/` — flatbed scanning pipeline

Turns the two flatbed scans of a sheet of glued-down puzzle pieces into database
records: contour, topology (cyclic TAB/BLANK/BORDER sequence), per-edge shape,
coarse colour class, and dual-pass boundary agreement.

## Usage

```bash
# from the repo root, in a fresh shell so uv is on PATH
uv run python -m Scan.pipeline PAGE_LABEL scan_a.tiff [scan_b.tiff] [--db path] [--dry-run]
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
| `db.py`       | SQLite schema (`sheets`, `pieces`, `edges`) and loader; contours stored as float32 blobs |
| `pipeline.py` | orchestration: two passes → averaged contours → per-piece records → grid assignment → DB |

## Verified

- `36-page1a/b` (no fiducials): 36/36 pieces, 172 µm, `(W-x, H-y)` pairing fallback.
- `T01a/b` (faint fiducials): 30/30 pieces, 5×6 grid, 171 µm, homography pairing
  (pair-centroid residual 19 px vs 35 px for the fallback).

## Known gaps

- `pipeline.classify_colour` thresholds are a first guess — calibrate against a
  sheet known to be half teal, half black.
- Fiducial detection wants solid-black corner dots ≥ 5 mm (T01's were faint blue
  and only just resolve). The guide boxes must NOT be black — print them in a
  tint that stays above the red-channel threshold, or omit them and use the jig.
