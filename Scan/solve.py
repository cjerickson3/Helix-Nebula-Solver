"""
Grid solver: place pieces by depth-first search with grid-consistency backtracking.

The edge matcher (`Scan.match`) is a weak pre-filter -- shape alone does not
uniquely identify a mate on this near-canonical puzzle, so the true mate is
usually in an edge's top few candidates but rarely rank 1. The discrimination
the matcher lacks comes from *consistency*: a candidate placement is only real
if EVERY edge it shares with an already-placed neighbour is a plausible mate at
once. That is what this solver adds.

Strategy (matches how the puzzle is solved by hand -- find an edge, find its
mate, confirm with a second shared edge):

  1. Seed from the globally strongest edge match (or a corner pair if the sheet
     has border pieces).
  2. Frontier = empty cells touching >=1 placed piece. Expand the most
     constrained first (fewest viable piece/rotation candidates).
  3. A candidate must satisfy ALL its placed neighbours: complementary edge
     type, and the shared edge must be in the neighbour edge's matcher
     candidate list. Score = sum of fit errors over the shared edges.
  4. Place the best candidate; recurse; backtrack on a dead end.

Usage:
    python -m Scan.solve --db resources/helix_pieces.db --sheet T03
"""
from __future__ import annotations
import argparse
import numpy as np

from . import db, geometry, match

# compass indices
N, E, S, W = 0, 1, 2, 3
_DELTA = {N: (0, -1), E: (1, 0), S: (0, 1), W: (-1, 0)}
_OPP = {N: S, S: N, E: W, W: E}

CAND_RANK = 10       # how deep into an edge's matcher candidate list to keep
RANK_STRICT = 4      # a placement needs >=1 shared edge with the mate this good
MAX_CAND_PER_SLOT = 12
N_SEEDS = 6          # how many seed pairs to try full DFS from


class Piece:
    __slots__ = ("pid", "label", "edges", "dir0", "types")

    def __init__(self, pid, label, contour, edges):
        self.pid = pid
        self.label = label
        self.edges = edges                       # list of 4 edge dicts (edge_id, type, curve...)
        cen = geometry.area_centroid(contour)
        ci = sorted(int(i) for i in geometry.find_corners(contour))
        arcs = [geometry._arc(contour, ci[k], ci[(k + 1) % 4]) for k in range(4)]
        # bearing of each edge's chord midpoint from the piece centroid
        bear = []
        for a in arcs:
            v = 0.5 * (a[0] + a[-1]) - cen
            bear.append(np.arctan2(v[1], v[0]))     # +y down => this is clockwise
        # assign the 4 edges to N/E/S/W by nearest cardinal bearing (bijective)
        card = {N: -np.pi / 2, E: 0.0, S: np.pi / 2, W: np.pi}
        want = sorted(((d, i,
                        abs(np.angle(np.exp(1j * (bear[i] - card[d])))))
                       for d in card for i in range(4)), key=lambda t: t[2])
        dir0, usedd, usedi = {}, set(), set()
        for d, i, _ in want:
            if d in usedd or i in usedi:
                continue
            dir0[d] = i
            usedd.add(d); usedi.add(i)
        self.dir0 = dir0                          # compass dir -> edge_index at rotation 0
        self.types = [edges[k]["edge_type"] for k in range(4)]

    def edge_facing(self, direction, rot):
        """edge dict on the side that points `direction` when the piece is placed
        at rotation `rot` (rot quarter-turns clockwise)."""
        return self.edges[self.dir0[(direction - rot) % 4]]


def _load(conn, sheet):
    q = "JOIN sheets s ON s.sheet_id=p.sheet_id WHERE s.page_label=?" if sheet else ""
    args = (sheet,) if sheet else ()
    prows = conn.execute(
        f"SELECT p.piece_id,p.piece_label,p.contour FROM pieces p {q} ORDER BY p.piece_id",
        args).fetchall()
    erows = conn.execute(
        f"""SELECT e.piece_id,e.edge_index,e.edge_id,e.edge_type,e.deviation,
                   e.chord_px,e.curve,p.piece_label
            FROM edges e JOIN pieces p ON p.piece_id=e.piece_id {q}
            ORDER BY e.piece_id,e.edge_index""", args).fetchall()
    ebypiece: dict[int, list] = {}
    all_edges = []
    for pid, ix, eid, et, dev, ch, cv, lbl in erows:
        d = dict(edge_id=eid, piece_id=pid, piece_label=lbl, edge_index=ix,
                 edge_type=et, deviation=dev, chord_px=ch, curve=db.unpack(cv))
        ebypiece.setdefault(pid, [None, None, None, None])[ix] = d
        all_edges.append(d)
    pieces = {pid: Piece(pid, lbl, db.unpack(ct), ebypiece[pid])
              for pid, lbl, ct in prows}
    return pieces, all_edges


def _candidate_index(all_edges):
    """(edge_id -> {mate_edge_id: (rank, fit_error)}, raw matches dict)."""
    matches, _ = match.rank_candidates(all_edges, keep=CAND_RANK)
    idx = {}
    for eid, lst in matches.items():
        idx[eid] = {mid: (r, err) for r, (mid, err) in enumerate(lst, 1)}
    return idx, matches


def _fits(piece, rot, cell, board, pieces, cand):
    """If `piece` at `rot` can occupy `cell` given the board, return
    (total_fit_error, n_shared, best_rank); else None.

    Every shared edge must be a matcher candidate of its neighbour, and at least
    one of them must be a *strong* candidate (rank <= RANK_STRICT) -- the
    2-edge-confirmation idea: a placement backed only by weak shape guesses on
    every side is almost always a coincidence.
    """
    col, row = cell
    total, shared, best_rank = 0.0, 0, 99
    for d, (dc, dr) in _DELTA.items():
        nb = board.get((col + dc, row + dr))
        if nb is None:
            continue
        npid, nrot = nb
        my = piece.edge_facing(d, rot)
        their = pieces[npid].edge_facing(_OPP[d], nrot)
        if my["edge_type"] == their["edge_type"] or "BORDER" in (my["edge_type"], their["edge_type"]):
            return None
        hit = cand.get(their["edge_id"], {}).get(my["edge_id"])
        if hit is None:
            return None
        total += hit[1]
        shared += 1
        best_rank = min(best_rank, hit[0])
    if not shared:
        return None
    if shared == 1 and best_rank > RANK_STRICT:
        return None
    return (total, shared, best_rank)


def _seed_pairs(matches, by_id, pieces):
    """Candidate seed pairs, best first. A mutually-rank-1 edge match is a much
    safer seed than the single global-lowest fit error (that is often a shape
    coincidence between two unrelated pieces)."""
    rank1 = {}                      # edge_id -> (mate_id, err) at rank 1
    for eid, lst in matches.items():
        if lst:
            rank1[eid] = lst[0]
    mutual, other = [], []
    for eid, (mid, err) in rank1.items():
        if eid >= mid:
            continue
        e1, e2 = by_id[eid], by_id[mid]
        if e1["piece_id"] == e2["piece_id"]:
            continue
        if rank1.get(mid, (None,))[0] == eid:
            mutual.append((err, e1, e2))
        else:
            other.append((err, e1, e2))
    mutual.sort()
    other.sort()
    return mutual + other


def _grow(seed, pieces, cand, verbose):
    err0, e1, e2 = seed
    p1, p2 = pieces[e1["piece_id"]], pieces[e2["piece_id"]]
    r1 = next(r for r in range(4) if p1.edge_facing(E, r)["edge_id"] == e1["edge_id"])
    r2 = next(r for r in range(4) if p2.edge_facing(W, r)["edge_id"] == e2["edge_id"])
    board = {(0, 0): (p1.pid, r1), (1, 0): (p2.pid, r2)}
    placed = {p1.pid, p2.pid}
    best = dict(board=dict(board), n=2, cost=err0)

    def frontier(bd):
        f = set()
        for (c, r) in bd:
            for dc, dr in _DELTA.values():
                if (c + dc, r + dr) not in bd:
                    f.add((c + dc, r + dr))
        return f

    def candidates_for(cell, bd, pl):
        out = []
        for pid, pc in pieces.items():
            if pid in pl:
                continue
            for rot in range(4):
                res = _fits(pc, rot, cell, bd, pieces, cand)
                if res is not None:
                    out.append((res[0] / res[1], pid, rot))
        out.sort()
        return out[:MAX_CAND_PER_SLOT]

    def dfs(bd, pl, cost):
        if len(bd) > best["n"] or (len(bd) == best["n"] and cost < best["cost"]):
            best.update(board=dict(bd), n=len(bd), cost=cost)
        if len(pl) == len(pieces):
            return
        slots = []
        for cell in frontier(bd):
            cs = candidates_for(cell, bd, pl)
            if cs:
                slots.append((len(cs), cell, cs))
        if not slots:
            return
        slots.sort()
        _, cell, cs = slots[0]
        for score, pid, rot in cs:
            bd[cell] = (pid, rot)
            pl.add(pid)
            dfs(bd, pl, cost + score)
            del bd[cell]
            pl.discard(pid)
            if len(best["board"]) == len(pieces):
                return                 # first full assembly wins

    dfs(board, placed, err0)
    if verbose:
        print(f"  seed {p1.label}<->{p2.label} fit {err0:.1f}px "
              f"-> placed {best['n']}/{len(pieces)} cost {best['cost']:.1f}")
    return best


def solve(pieces, all_edges, verbose=True):
    cand, matches = _candidate_index(all_edges)
    by_id = {e["edge_id"]: e for e in all_edges}
    seeds = _seed_pairs(matches, by_id, pieces)
    if not seeds:
        return {}
    results = [_grow(s, pieces, cand, verbose) for s in seeds[:N_SEEDS]]
    win = max(results, key=lambda b: (b["n"], -b["cost"]))
    return win["board"]


def _score_layout(board, pieces, conn, sheet):
    """Compare the solved layout to the stored grid (translation/rotation/mirror
    invariant), if the sheet has a known grid."""
    truth = {}
    q = "JOIN sheets s ON s.sheet_id=p.sheet_id WHERE s.page_label=?" if sheet else ""
    for pid, c, r in conn.execute(
            f"SELECT p.piece_id,p.grid_col,p.grid_row FROM pieces p {q}",
            (sheet,) if sheet else ()):
        if c is not None:
            truth[pid] = (c, r)
    if len(truth) < 3:
        return None
    sol = {pid: cell for cell, (pid, _) in board.items()}
    common = [pid for pid in sol if pid in truth]
    for flip in (1, -1):
        for rot in range(4):
            def xf(cell):
                x, y = cell
                x *= flip
                for _ in range(rot):
                    x, y = -y, x
                return (x, y)
            t = {pid: xf(truth[pid]) for pid in common}
            s = {pid: sol[pid] for pid in common}
            ox = s[common[0]][0] - t[common[0]][0]
            oy = s[common[0]][1] - t[common[0]][1]
            ok = sum(1 for pid in common
                     if (t[pid][0] + ox, t[pid][1] + oy) == s[pid])
            if ok == len(common):
                return ok, len(common)
    # best partial
    bestok = 0
    for flip in (1, -1):
        for rot in range(4):
            def xf(cell):
                x, y = cell
                x *= flip
                for _ in range(rot):
                    x, y = -y, x
                return (x, y)
            t = {pid: xf(truth[pid]) for pid in common}
            for anchor in common:
                ox = sol[anchor][0] - t[anchor][0]
                oy = sol[anchor][1] - t[anchor][1]
                ok = sum(1 for pid in common
                         if (t[pid][0] + ox, t[pid][1] + oy) == sol[pid])
                bestok = max(bestok, ok)
    return bestok, len(common)


def main():
    ap = argparse.ArgumentParser(description="DFS grid solver")
    ap.add_argument("--db", default="resources/helix_pieces.db")
    ap.add_argument("--sheet", default=None, help="restrict to one page_label")
    ap.add_argument("--write", action="store_true", help="store placement in the DB")
    args = ap.parse_args()

    conn = db.connect(args.db)
    pieces, all_edges = _load(conn, args.sheet)
    if not pieces:
        print("no pieces")
        return
    print(f"{len(pieces)} pieces, {len(all_edges)} edges")

    board = solve(pieces, all_edges)
    print(f"\nplaced {len(board)}/{len(pieces)}")
    cells = sorted(board)
    if cells:
        cmin = min(c for c, r in cells)
        rmin = min(r for c, r in cells)
        rows = max(r for c, r in cells) - rmin + 1
        cols = max(c for c, r in cells) - cmin + 1
        grid = [["  .  "] * cols for _ in range(rows)]
        for (c, r), (pid, rot) in board.items():
            grid[r - rmin][c - cmin] = f"{pieces[pid].label.split('-')[-1]:>3}r{rot}"
        for gr in grid:
            print(" ".join(gr))

    sc = _score_layout(board, pieces, conn, args.sheet)
    if sc:
        print(f"\nvs known grid: {sc[0]}/{sc[1]} pieces in correct relative position")

    if args.write:
        for (c, r), (pid, rot) in board.items():
            conn.execute(
                "UPDATE pieces SET placed_col=?,placed_row=?,placed_rotation=?,"
                "placement_method='dfs' WHERE piece_id=?", (c, r, rot, pid))
        conn.commit()
        print("written")


if __name__ == "__main__":
    main()
