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
- `T01a/b` (faint fiducials): 30/30 pieces, 5×6 grid, 171 µm, homography pairing.
- `P01a/b` (black fiducials, opposing-tab pieces): 30/30, 177 µm, homography;
  27/30 topologies correct, the rest flagged via `corner_dev`.

## Known gaps

- **Corner detection**: `find_corners` trusts the body-rect method on clean
  pieces and falls back to a curvature-peak finder + diagonal method on the rest
  (deep blank pinches the body, or a tilted piece), keeping the most regular.
  `pieces.corner_dev` flags what's still shaky (clean ≤ 0.12). 28/30 on P01;
  the geometry fields stay reliable regardless — only topology is affected.
- `pipeline.classify_colour` thresholds are a first guess — calibrate against a
  sheet known to be half teal, half black.
- Guide boxes must NOT print black (they read as pieces) — faint tint or omit
  and use the acrylic jig. Fiducial corner dots: solid black, ≥ 5 mm.
