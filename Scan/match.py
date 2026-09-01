"""
Edge matching: for every TAB / BLANK edge, find the candidate mating edges.

Two stages, cheapest first (the pre-filter the CLAUDE.md plan calls for):

1. Scalar pre-filter. Opposite type, matching feature (tab/blank) neck width and
   height, and roughly complementary feature placement along the edge. Cheap;
   rejects most pairs.

2. Feature-anchored fine fit. The tab and blank *shapes* in this puzzle are
   nearly canonical AND corner detection wobbles 10-25% between the two pieces of
   a real join, so a descriptor measured from the corners is too noisy to rank
   mates. Instead: level the edge on its flat shoulders (robust baseline), put
   x = 0 at the centre of the tab/blank feature (robust anchor), and compare only
   a fixed window around the feature -- the corner regions are never looked at.
   Overlay (mirror one, both windings, small shift + scale search), RMS the
   point distance. The lost information -- absolute feature position relative to
   the corners -- is recovered by the solver's grid-consistency check, not here.

Usage:
    python -m Scan.match --db resources/helix_pieces.db          # compute + store
    python -m Scan.match --db ... --explore                      # descriptor stats
    python -m Scan.match --db ... --edge 42                      # ranked mates for one edge
"""
from __future__ import annotations
import argparse
import numpy as np

from . import db, config

# --- pre-filter tolerances (fractions unless noted) -------------------------
NECK_TOL = 0.26         # |neck1 - neck2| / mean   (feature baseline width)
PEAK_TOL = 0.40         # |peak1 - peak2| / mean, AFTER shadow-bias correction
FLAT_TOL = 55.0         # px; complementary feature placement slack. Loose because
                        # the shoulder length depends on the noisy corner
                        # position, but not a free-for-all (see module docs).

# --- fine-fit window and search ------------------------------------------------
BASELINE_FRAC = 0.22    # fraction of each end used as the flat-shoulder baseline
FEATURE_FRAC = 0.15     # |y| above this * peak marks the feature extent
FIT_WIN = 175.0         # px half-window around the feature centre to compare over
FIT_N = 140             # sample count across that window
FIT_SHIFT = 16.0        # px along-edge shift search half-width
FIT_SHIFT_N = 13
FIT_SCALE = (0.90, 0.95, 1.0, 1.05, 1.10)
FIT_MIN_OVERLAP = 70    # finite-sample count required to score a fit


# ------------------------------------------------------------------ descriptor

def _orient(curve: np.ndarray, deviation: float) -> np.ndarray:
    """Edge curve with y flipped so 'outward from the piece centre' is +y
    (TAB peaks positive, BLANK peaks negative)."""
    c = np.asarray(curve, dtype=np.float64).copy()
    ipk = int(np.argmax(np.abs(c[:, 1])))
    if c[ipk, 1] * deviation < 0:
        c[:, 1] = -c[:, 1]
    return c


def _feature_frame(curve: np.ndarray, deviation: float):
    """Oriented, baseline-levelled edge curve, re-anchored so x = 0 is the centre
    of the tab/blank feature. Returns (xy, neck, peak, chord, lflat, rflat)."""
    c = _orient(curve, deviation or 1.0)
    x, y = c[:, 0].copy(), c[:, 1].copy()
    L = float(x[-1] - x[0]) or 1.0
    sh = (x < x[0] + BASELINE_FRAC * L) | (x > x[-1] - BASELINE_FRAC * L)
    if sh.sum() >= 4:
        m, b = np.polyfit(x[sh], y[sh], 1)
        y = y - (m * x + b)
    ipk = int(np.argmax(np.abs(y)))
    peak = float(y[ipk])
    over = np.abs(y) > FEATURE_FRAC * abs(peak)
    lo = hi = ipk
    while lo > 0 and over[lo - 1]:
        lo -= 1
    while hi < len(y) - 1 and over[hi + 1]:
        hi += 1
    neck = float(x[hi] - x[lo])
    xa = float(0.5 * (x[lo] + x[hi]))
    return (np.column_stack([x - xa, y]), neck, peak, L,
            float(xa - x[0]), float(x[-1] - xa))


def edge_descriptor(edge: dict) -> dict | None:
    """Feature-anchored descriptor of one edge. None for BORDER edges."""
    if edge["edge_type"] == "BORDER":
        return None
    xy, neck, peak, chord, lflat, rflat = _feature_frame(
        edge["curve"], edge["deviation"])
    return dict(edge_id=edge["edge_id"], piece_id=edge["piece_id"],
                piece_label=edge["piece_label"], edge_index=edge["edge_index"],
                type=edge["edge_type"], neck=neck, peak=peak, peak_adj=abs(peak),
                chord=chord, lflat=lflat, rflat=rflat,
                x=xy[:, 0], y=xy[:, 1])


# ------------------------------------------------------------------ pre-filter

def _rel(a, b) -> float:
    m = 0.5 * (abs(a) + abs(b))
    return abs(a - b) / m if m else 0.0


def prefilter(d1: dict, d2: dict) -> bool:
    """True if d1 and d2 (opposite types) could plausibly mate. Expects the
    shadow-bias-corrected `peak_adj` field (see `rank_candidates`)."""
    if d1["type"] == d2["type"]:
        return False
    if _rel(d1["neck"], d2["neck"]) > NECK_TOL:
        return False
    if _rel(d1["peak_adj"], d2["peak_adj"]) > PEAK_TOL:
        return False
    # Two pieces sharing an edge face each other, so one's left shoulder maps to
    # the other's right shoulder. Loose because the shoulder length depends on
    # the (noisy) corner position.
    if min(abs(d1["lflat"] - d2["rflat"]),
           abs(d1["rflat"] - d2["lflat"])) > FLAT_TOL:
        return False
    return True


# ------------------------------------------------------------------- fine fit

def fit_error(d1: dict, d2: dict) -> float:
    """RMS px between the two feature-anchored curves representing the same
    physical join. d2 is mirrored (-y) and amplitude-normalised to d1; both
    windings and a small shift/scale search absorb corner-placement noise."""
    s = np.linspace(-FIT_WIN, FIT_WIN, FIT_N)
    y1 = np.interp(s, d1["x"], d1["y"], left=np.nan, right=np.nan)
    amp = (d1["peak_adj"] / d2["peak_adj"]) if d2["peak_adj"] else 1.0
    best = np.inf
    for wind in (1, -1):
        xo = d2["x"] if wind == 1 else -d2["x"][::-1]
        yo = (-d2["y"] if wind == 1 else -d2["y"][::-1]) * amp
        for sc in FIT_SCALE:
            for sh in np.linspace(-FIT_SHIFT, FIT_SHIFT, FIT_SHIFT_N):
                y2 = np.interp(s, xo * sc + sh, yo, left=np.nan, right=np.nan)
                m = np.isfinite(y1) & np.isfinite(y2)
                if m.sum() < FIT_MIN_OVERLAP:
                    continue
                best = min(best, float(np.sqrt(np.mean((y1[m] - y2[m]) ** 2))))
    return best


# ---------------------------------------------------------------- orchestration

def shadow_bias(descs: list[dict]) -> float:
    """Half the systematic gap between TAB peak heights and BLANK peak depths.

    The extraction threshold sits partway up the ~20 px edge shadow, so every
    contour is inflated outward: a tab reads too tall and its mating blank too
    shallow by ~this much. Computed per run so it tracks card stock and lamp
    ageing.
    """
    t = np.mean([abs(d["peak"]) for d in descs if d["type"] == "TAB"] or [0])
    b = np.mean([abs(d["peak"]) for d in descs if d["type"] == "BLANK"] or [0])
    return 0.5 * (t - b)


def rank_candidates(edges: list[dict], keep: int = 8):
    """For every non-BORDER edge, the pre-filter survivors ranked by fit error.

    Returns (matches, stats) where matches is {edge_id: [(mate_edge_id, err), ...]}.
    """
    descs = [d for d in (edge_descriptor(e) for e in edges) if d is not None]
    bias = shadow_bias(descs)
    for d in descs:
        s = -1.0 if d["type"] == "TAB" else 1.0   # shrink tabs, grow blanks
        d["peak_adj"] = abs(d["peak"]) + s * bias

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
            err = fit_error(t, b)
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
        arr = lambda k: np.array([abs(d[k]) for d in g])
        print(f"\n{typ}  (n={len(g)})")
        for k in ("neck", "peak", "chord", "lflat", "rflat"):
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
    print(f"stored. mutual best-match pairs: {len(mutual)}  (strongest first)")
    for err, a, b in mutual[:15]:
        ea, eb = by_id[a], by_id[b]
        print(f"  fit {err:5.1f}px   {ea['piece_label']} #{ea['edge_index']} {ea['edge_type']:5s}"
              f"  <->  {eb['piece_label']} #{eb['edge_index']} {eb['edge_type']}")


if __name__ == "__main__":
    main()
