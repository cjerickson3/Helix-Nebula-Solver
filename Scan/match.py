"""
Edge matching: for every TAB / BLANK edge, find the candidate mating edges.

Two stages, cheapest first (this is the pre-filter the CLAUDE.md plan calls for):

1. Scalar pre-filter. The tab and blank *shapes* in this puzzle are nearly
   canonical, so comparing full profiles barely discriminates. What matters is
   the geometry relative to the corners: a tab and its mating blank must have
   the same chord length, the feature at complementary positions along the edge
   (peak_pos_a + peak_pos_b ~= 1), and matching feature height and width. Those
   are four cheap scalars per edge; most pairs are rejected here.

2. Fine fit. On the survivors, overlay the two edge curves (flip one, small
   shift search) and score the RMS point distance -- puzzle-bot's
   `error_between_polylines`.

Usage:
    python -m Scan.match --db resources/helix_pieces.db          # compute + store
    python -m Scan.match --db ... --explore                      # descriptor stats, no write
    python -m Scan.match --db ... --edge 42                      # show ranked mates for one edge
"""
from __future__ import annotations
import argparse
import numpy as np

from . import db, config

# --- pre-filter tolerances (fractions unless noted) -------------------------
LEN_TOL = 0.06          # |L1 - L2| / mean            (puzzle-bot SIDE_MAX_LENGTH_DISCREPANCY)
POS_TOL = 0.08          # |peak_pos_a + peak_pos_b - 1|   (complementary feature position)
DEV_TOL = 0.13          # |dev1 - dev2| / mean, AFTER shadow-bias correction
WIDTH_TOL = 0.22        # |w1 - w2| / mean            (feature width)

FIT_RESAMPLE = config.EDGE_SAMPLES       # points to compare curves at
FIT_MAX_SHIFT = 8.0                      # px, half-width of the x/y shift search
                                         # (corner-location noise; the systematic
                                         # tab/blank offset is removed separately)


# ------------------------------------------------------------------ descriptor

def _orient(curve: np.ndarray, deviation: float) -> np.ndarray:
    """Return the edge curve with y flipped so 'outward from the piece centre'
    is +y (TAB peaks positive, BLANK peaks negative). `deviation` is the stored
    centroid-oriented signed peak."""
    c = np.asarray(curve, dtype=np.float64).copy()
    ipk = int(np.argmax(np.abs(c[:, 1])))
    if c[ipk, 1] * deviation < 0:
        c[:, 1] = -c[:, 1]
    return c


def edge_descriptor(edge: dict) -> dict | None:
    """Scalar descriptor of one edge for the pre-filter. None for BORDER edges
    (they never mate)."""
    if edge["edge_type"] == "BORDER":
        return None
    c = _orient(edge["curve"], edge["deviation"] or 1.0)
    x, y = c[:, 0], c[:, 1]
    L = float(x[-1] - x[0]) or edge["chord_px"]
    ipk = int(np.argmax(np.abs(y)))
    peak = float(y[ipk])
    peak_pos = float((x[ipk] - x[0]) / L) if L else 0.5
    # feature width: x-span where |y| exceeds 40% of the peak
    over = np.abs(y) > 0.4 * abs(peak)
    width = float(x[over].max() - x[over].min()) if over.any() else 0.0
    area = float(np.trapezoid(y, x))
    return dict(edge_id=edge["edge_id"], piece_id=edge["piece_id"],
                piece_label=edge["piece_label"], edge_index=edge["edge_index"],
                type=edge["edge_type"], L=L, peak=abs(peak), peak_pos=peak_pos,
                width=width, area=area, curve=c)


# ------------------------------------------------------------------ pre-filter

def _rel(a, b) -> float:
    m = 0.5 * (abs(a) + abs(b))
    return abs(a - b) / m if m else 0.0


def prefilter(d1: dict, d2: dict) -> bool:
    """True if d1 and d2 (opposite types) could plausibly mate. Expects the
    shadow-bias-corrected `peak_adj` field (see `rank_candidates`)."""
    if d1["type"] == d2["type"]:
        return False
    if _rel(d1["L"], d2["L"]) > LEN_TOL:
        return False
    if abs(d1["peak_pos"] + d2["peak_pos"] - 1.0) > POS_TOL:
        return False
    if _rel(d1["peak_adj"], d2["peak_adj"]) > DEV_TOL:
        return False
    if _rel(d1["width"], d2["width"]) > WIDTH_TOL:
        return False
    return True


# ------------------------------------------------------------------- fine fit

def _resample_xy(curve: np.ndarray, n: int) -> np.ndarray:
    x, y = curve[:, 0], curve[:, 1]
    xs = np.linspace(x[0], x[-1], n)
    return np.column_stack([xs, np.interp(xs, x, y)])


def fit_error(c1: np.ndarray, c2: np.ndarray) -> float:
    """RMS distance (px) between two oriented edge curves once c2 is placed
    against c1. c2 is mirrored (-y) and tried both as-is and reversed in x to
    absorb contour-winding differences; a small x/y shift is searched to absorb
    corner-location noise."""
    a = _resample_xy(c1, FIT_RESAMPLE)
    a = a - [a[0, 0], 0.0]                       # start at x=0
    best = np.inf
    for rev in (False, True):
        b = _resample_xy(c2, FIT_RESAMPLE).copy()
        b[:, 1] = -b[:, 1]
        if rev:
            b = b[::-1].copy()
        b = b - [b[0, 0], 0.0]
        # match overall length to a
        if b[-1, 0] > 1e-6:
            b[:, 0] *= a[-1, 0] / b[-1, 0]
        bx_on_a = np.interp(a[:, 0], b[:, 0], b[:, 1])
        for dy in np.linspace(-FIT_MAX_SHIFT, FIT_MAX_SHIFT, 7):
            d = a[:, 1] - (bx_on_a + dy)
            best = min(best, float(np.sqrt(np.mean(d * d))))
    return best


# ---------------------------------------------------------------- orchestration

def shadow_bias(descs: list[dict]) -> float:
    """Half the systematic gap between TAB peak heights and BLANK peak depths.

    The extraction threshold sits partway up the ~20 px edge shadow, so every
    contour is inflated outward: a tab reads too tall by ~this much and its
    mating blank reads too shallow by the same, ~27 px apart on the P01/P02
    sheets. Computed per run so it tracks card stock and lamp ageing.
    """
    t = np.mean([d["peak"] for d in descs if d["type"] == "TAB"] or [0])
    b = np.mean([d["peak"] for d in descs if d["type"] == "BLANK"] or [0])
    return 0.5 * (t - b)


def rank_candidates(edges: list[dict], keep: int = 8):
    """For every non-BORDER edge, the pre-filter survivors ranked by fit error.

    Returns (matches, stats) where matches is {edge_id: [(mate_edge_id, err), ...]}.
    """
    descs = [d for d in (edge_descriptor(e) for e in edges) if d is not None]
    bias = shadow_bias(descs)
    for d in descs:
        s = -1.0 if d["type"] == "TAB" else 1.0
        d["peak_adj"] = d["peak"] + s * bias
        d["curve"] = d["curve"] + [0.0, s * bias]      # meet at the true surface

    tabs = [d for d in descs if d["type"] == "TAB"]
    blanks = [d for d in descs if d["type"] == "BLANK"]

    total_pairs = len(tabs) * len(blanks)
    survivors = 0
    matches: dict[int, list] = {d["edge_id"]: [] for d in descs}

    for t in tabs:
        for b in blanks:
            if b["piece_id"] == t["piece_id"]:
                continue
            if not prefilter(t, b):
                continue
            survivors += 1
            err = fit_error(t["curve"], b["curve"])
            matches[t["edge_id"]].append((b["edge_id"], err))
            matches[b["edge_id"]].append((t["edge_id"], err))

    for eid in matches:
        matches[eid] = sorted(matches[eid], key=lambda p: p[1])[:keep]

    stats = dict(n_edges=len(descs), n_tabs=len(tabs), n_blanks=len(blanks),
                 shadow_bias=bias, total_pairs=total_pairs, survivors=survivors,
                 cut=1.0 - survivors / total_pairs if total_pairs else 0.0)
    return matches, stats


def _explore(edges):
    descs = [d for d in (edge_descriptor(e) for e in edges) if d is not None]
    for typ in ("TAB", "BLANK"):
        g = [d for d in descs if d["type"] == typ]
        arr = lambda k: np.array([d[k] for d in g])
        print(f"\n{typ}  (n={len(g)})")
        for k in ("L", "peak", "peak_pos", "width"):
            v = arr(k)
            print(f"  {k:9s} mean {v.mean():8.2f}  sd {v.std():6.2f}  "
                  f"min {v.min():8.2f}  max {v.max():8.2f}  "
                  f"cv {v.std() / abs(v.mean()):.3f}")


def main():
    ap = argparse.ArgumentParser(description="Edge matcher / pre-filter")
    ap.add_argument("--db", default="resources/helix_pieces.db")
    ap.add_argument("--explore", action="store_true", help="descriptor stats only")
    ap.add_argument("--edge", type=int, help="show ranked mates for this edge_id")
    ap.add_argument("--keep", type=int, default=8, help="candidates stored per edge")
    args = ap.parse_args()

    conn = db.connect(args.db)
    edges = db.load_edges(conn)
    if not edges:
        print("no edges in database -- run Scan.pipeline first")
        return

    if args.explore:
        _explore(edges)
        return

    matches, st = rank_candidates(edges, keep=args.keep)
    print(f"edges {st['n_edges']}  ({st['n_tabs']} TAB, {st['n_blanks']} BLANK)  "
          f"shadow bias {st['shadow_bias']:.1f} px")
    print(f"pre-filter: {st['survivors']} / {st['total_pairs']} pairs kept "
          f"({st['cut'] * 100:.1f}% cut)")
    per = [len(v) for v in matches.values()]
    print(f"candidates per edge: mean {np.mean(per):.1f}  max {max(per)}  "
          f"zero {sum(1 for x in per if x == 0)}")
    best = np.array([v[0][1] for v in matches.values() if v])
    if len(best):
        qs = np.percentile(best, [10, 25, 50, 75, 90])
        print(f"best-candidate fit error (px): p10 {qs[0]:.1f}  p25 {qs[1]:.1f}  "
              f"median {qs[2]:.1f}  p75 {qs[3]:.1f}  p90 {qs[4]:.1f}")

    if args.edge is not None:
        by_id = {e["edge_id"]: e for e in edges}
        e = by_id[args.edge]
        print(f"\nedge {args.edge}: {e['piece_label']} #{e['edge_index']} {e['edge_type']}")
        for rank, (mid, err) in enumerate(matches[args.edge], 1):
            m = by_id[mid]
            print(f"  {rank:2d}. edge {mid:4d}  {m['piece_label']} #{m['edge_index']} "
                  f"{m['edge_type']}   fit {err:.2f} px")
        return

    rows = ((eid, mid, rank, err)
            for eid, lst in matches.items()
            for rank, (mid, err) in enumerate(lst, 1))
    db.store_edge_matches(conn, rows)

    by_id = {e["edge_id"]: e for e in edges}
    mutual = []
    for eid, lst in matches.items():
        if lst and matches.get(lst[0][0]) and matches[lst[0][0]][0][0] == eid \
                and eid < lst[0][0]:
            mutual.append((lst[0][1], eid, lst[0][0]))
    mutual.sort()
    print(f"stored. mutual best-match pairs: {len(mutual)}  "
          f"(strongest first)")
    for err, a, b in mutual[:15]:
        ea, eb = by_id[a], by_id[b]
        print(f"  fit {err:5.1f}px   {ea['piece_label']} #{ea['edge_index']} {ea['edge_type']:5s}"
              f"  <->  {eb['piece_label']} #{eb['edge_index']} {eb['edge_type']}")


if __name__ == "__main__":
    main()
