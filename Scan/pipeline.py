"""
Top-level pipeline: take a sheet's two scans and produce database records.

Usage:
    python -m Scan.pipeline PAGE_LABEL scan_a.tiff [scan_b.tiff] [--db pieces.db]
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import argparse
import numpy as np

from . import config, scan, geometry, db


# -------------------------------------------------------------------- colour

def classify_colour(mean_lab) -> str:
    """Coarse colour class from mean LAB.

    Only three buckets, because that is all the solver needs as a pre-filter:
    teal ring, dark background, everything else. OpenCV LAB is 0-255 with the
    a/b channels offset by 128.
    """
    L, a, b = float(mean_lab[0]), float(mean_lab[1]) - 128.0, float(mean_lab[2]) - 128.0
    if L < 60:
        return "dark"
    if b < -5 and a < 5:
        return "teal"
    return "other"


# ---------------------------------------------------------------------- grid

def assign_grid(centroids, pitch_hint=None):
    """Assign each piece a (col, row) by clustering centroids on each axis.

    The number of columns and rows is INFERRED from the data, not taken from
    config. Sheets differ -- the acrylic jig is 5x6, but older sheets are 6x6 --
    and forcing centroids into the wrong lattice silently collides piece labels.

    Clustering uses a gap threshold at half the median spacing between adjacent
    sorted coordinates, which separates columns cleanly because within-column
    scatter is far smaller than the column pitch.
    """
    if len(centroids) == 0:
        return []
    C = np.asarray(centroids, dtype=np.float64)
    col_of, ncols = _cluster_axis(C[:, 0], pitch_hint)
    row_of, nrows = _cluster_axis(C[:, 1], pitch_hint)
    return list(zip(col_of, row_of)), ncols, nrows


def _cluster_axis(values, pitch_hint=None):
    """Cluster 1-D coordinates into lattice positions. Returns (labels, count)."""
    values = np.asarray(values, dtype=np.float64)
    order = np.argsort(values)
    v = values[order]

    if len(v) == 1:
        return np.zeros(1, dtype=int), 1

    gaps = np.diff(v)
    positive = gaps[gaps > 1e-9]
    if len(positive) == 0:
        return np.zeros(len(v), dtype=int), 1

    # A gap larger than half the typical piece pitch means a new column/row.
    # Physical threshold, not statistical: within-column centroid scatter is a
    # few pixels while the column pitch is ~670 px at 600 dpi, so half a piece
    # width separates them with enormous margin. A purely statistical gap test
    # is far too sensitive and splits rows that should be single.
    threshold = pitch_hint * 0.5 if pitch_hint else np.median(positive) * 8.0
    labels_sorted = np.zeros(len(v), dtype=int)
    current = 0
    for i in range(1, len(v)):
        if gaps[i - 1] > threshold:
            current += 1
        labels_sorted[i] = current

    labels = np.zeros(len(values), dtype=int)
    labels[order] = labels_sorted
    return labels, current + 1


def cell_label(col, row) -> str:
    return f"{chr(ord('A') + int(col))}{int(row) + 1}"


# ------------------------------------------------------------------ per piece

def build_record(contour, residual, mean_lab, page_label, col, row):
    """Turn an averaged contour into a full database record."""
    contour = scan.correct_anisotropy(contour)
    centroid = geometry.area_centroid(contour)

    corner_idx = geometry.find_corners(contour)
    edges = geometry.split_edges(contour, corner_idx)

    edge_records, types = [], []
    for i, e in enumerate(edges):
        etype, dev = geometry.classify_edge(e, centroid)
        types.append(etype)
        edge_records.append({
            "index": i,
            "type": etype,
            "deviation": dev,
            "chord_px": float(np.hypot(*(e[-1] - e[0]))),
            "curve": geometry.normalise_edge(e),
        })

    xs, ys = contour[:, 0], contour[:, 1]
    scale = config.MM_PER_INCH / config.DPI

    return {
        "piece_label": f"{page_label}-{cell_label(col, row)}",
        "grid_col": int(col),
        "grid_row": int(row),
        "n_tabs": types.count("TAB"),
        "n_blanks": types.count("BLANK"),
        "n_borders": types.count("BORDER"),
        "edge_sequence": "|".join(types),
        "cyclic_key": geometry.cyclic_signature(types),
        "area_px": geometry.polygon_area(contour),
        "perimeter_px": geometry.perimeter(contour),
        "width_mm": float(xs.max() - xs.min()) * scale,
        "height_mm": float(ys.max() - ys.min()) * scale,
        "residual_px": float(residual),
        "colour_class": classify_colour(mean_lab),
        "mean_l": float(mean_lab[0]),
        "mean_a": float(mean_lab[1]),
        "mean_b": float(mean_lab[2]),
        "contour": contour,
        "edges": edge_records,
    }


# ------------------------------------------------------------------ per sheet

@dataclass
class SheetResult:
    page_label: str
    records: list
    diagnostics: dict


def process_sheet(page_label, scan_a_path, scan_b_path=None, verbose=True):
    """Process one sheet: two passes if available, one if not."""
    img_a = scan.load_scan(scan_a_path)
    pieces_a, diag_a = scan.extract_pieces(img_a)
    fid_a = scan.detect_fiducials(img_a)

    if verbose:
        print(f"[{page_label}] pass A: {len(pieces_a)} pieces, "
              f"threshold {diag_a['threshold']} (backing {diag_a['backing']}), "
              f"fiducials {'yes' if fid_a.found else 'no'}")
        if diag_a["merges"]:
            print(f"    WARNING: {len(diag_a['merges'])} possible merged pieces "
                  f"(indices {diag_a['merges']}) -- re-space and rescan")
        if diag_a.get("largest_rejected", 0) > config.PIECE_AREA_MIN * 0.5:
            print(f"    note: largest rejected contour {diag_a['largest_rejected']:.0f} px")

    contours, residuals = [], []

    if scan_b_path:
        img_b = scan.load_scan(scan_b_path)
        pieces_b, diag_b = scan.extract_pieces(img_b)
        fid_b = scan.detect_fiducials(img_b)
        if verbose:
            print(f"[{page_label}] pass B: {len(pieces_b)} pieces, "
                  f"fiducials {'yes' if fid_b.found else 'no'}")
            if len(pieces_b) != len(pieces_a):
                print(f"    WARNING: pass counts differ ({len(pieces_a)} vs "
                      f"{len(pieces_b)}) -- some pieces will fall back to single-pass")

        # A fiducial homography (B pixel frame -> A pixel frame) makes pairing a
        # direct nearest-neighbour lookup and absorbs sheet re-seating offset.
        # (The 4-corner fit is exact, so its own reprojection residual is 0 and
        # not worth printing -- the pair-centroid residual below is the real QC.)
        H_ba = scan.sheet_homography(fid_b, fid_a)
        pairs = scan.pair_passes(pieces_a, pieces_b, img_a.shape, H=H_ba)
        matched = {i: j for i, j, _ in pairs}
        if verbose:
            d = [d for _, _, d in pairs]
            if d:
                print(f"    paired {len(pairs)}/{len(pieces_a)} "
                      f"({'homography' if H_ba is not None else 'W-x,H-y fallback'}), "
                      f"centroid residual median {np.median(d):.1f} px")

        for i, pa in enumerate(pieces_a):
            if i in matched:
                pb = pieces_b[matched[i]]
                avg, resid = geometry.average_contours(pa.contour, pb.contour)
                contours.append(avg)
                residuals.append(resid)
            else:
                contours.append(geometry.smooth_closed(
                    geometry.resample_closed(pa.contour)))
                residuals.append(float("nan"))
    else:
        if verbose:
            print(f"[{page_label}] single pass -- no shadow cancellation, "
                  f"expect ~2x boundary error")
        for pa in pieces_a:
            contours.append(geometry.smooth_closed(
                geometry.resample_closed(pa.contour)))
            residuals.append(float("nan"))

    # Use half the median piece width as the clustering threshold -- a physical
    # scale, robust regardless of how many columns a given sheet happens to have.
    widths = []
    for p in pieces_a:
        xs = p.contour[:, 0]
        widths.append(float(xs.max() - xs.min()))
    pitch_hint = float(np.median(widths)) if widths else None

    cells, ncols, nrows = assign_grid([p.centroid for p in pieces_a], pitch_hint)
    if verbose:
        print(f"    grid inferred: {ncols} cols x {nrows} rows "
              f"for {len(pieces_a)} pieces")
        if ncols * nrows < len(pieces_a):
            print(f"    WARNING: inferred grid has fewer cells than pieces")

    records, seen = [], {}
    for k, (contour, resid) in enumerate(zip(contours, residuals)):
        col, row = cells[k] if k < len(cells) else (0, k)
        rec = build_record(contour, resid, pieces_a[k].mean_lab,
                           page_label, col, row)
        # Guard against label collisions: a duplicate means the grid inference
        # went wrong, and silently overwriting would corrupt the database.
        label = rec["piece_label"]
        if label in seen:
            seen[label] += 1
            rec["piece_label"] = f"{label}#{seen[label]}"
            if verbose:
                print(f"    WARNING: duplicate cell {label} -- "
                      f"grid inference may be wrong, renamed to {rec['piece_label']}")
        else:
            seen[label] = 0
        records.append(rec)

    finite = [r for r in residuals if np.isfinite(r)]
    diag_a["mean_residual"] = float(np.mean(finite)) if finite else None
    diag_a["fiducials_found"] = fid_a.found

    if verbose and finite:
        mm = np.mean(finite) / config.DPI * config.MM_PER_INCH * 1000
        print(f"    boundary agreement: {np.mean(finite):.2f} px ({mm:.0f} um), "
              f"worst {max(finite):.2f} px")
        counts = {}
        for r in records:
            counts[r["cyclic_key"]] = counts.get(r["cyclic_key"], 0) + 1
        print(f"    topology classes: {len(counts)} distinct")
        for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"        {key:34s} {n}")

    return SheetResult(page_label, records, diag_a)


def store(result: SheetResult, scan_a, scan_b, db_path):
    conn = db.connect(db_path)
    sheet_id = db.insert_sheet(conn, result.page_label, scan_a, scan_b,
                               result.diagnostics,
                               result.diagnostics.get("mean_residual"),
                               result.diagnostics.get("fiducials_found", False))
    for rec in result.records:
        db.insert_piece(conn, sheet_id, rec)
    conn.commit()
    conn.close()
    return sheet_id


def main():
    ap = argparse.ArgumentParser(description="Process one sheet of puzzle pieces")
    ap.add_argument("page_label")
    ap.add_argument("scan_a")
    ap.add_argument("scan_b", nargs="?", default=None)
    ap.add_argument("--db", default="resources/helix_pieces.db")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    result = process_sheet(args.page_label, args.scan_a, args.scan_b)
    if args.dry_run:
        print(f"\ndry run -- {len(result.records)} records not written")
        return
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    sid = store(result, args.scan_a, args.scan_b, args.db)
    print(f"\nwrote sheet {sid} with {len(result.records)} pieces to {args.db}")


if __name__ == "__main__":
    main()
