"""
Contour geometry: resampling, smoothing, rigid registration (ICP), corner
detection and edge extraction.

The registration routine here is the one piece of this pipeline that is easy to
get subtly wrong. Aligning two contours by their centroids and solving only for
rotation leaves a translation error that looks exactly like a uniform dilation --
during development that made two scans of the same piece appear to differ by 17 px
when the true figure was 4 px. Always use `icp_register`.
"""
from __future__ import annotations
import itertools
import numpy as np
import cv2
from scipy.spatial import cKDTree

from . import config


# ----------------------------------------------------------------- resampling

def resample_closed(points: np.ndarray, n: int = config.CONTOUR_SAMPLES) -> np.ndarray:
    """Resample a closed contour to `n` points evenly spaced by arc length."""
    P = np.asarray(points, dtype=np.float64)
    closed = np.vstack([P, P[:1]])
    seg = np.hypot(*np.diff(closed, axis=0).T)
    d = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0.0, d[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, d, closed[:, 0]),
                            np.interp(t, d, closed[:, 1])])


def resample_open(points: np.ndarray, n: int = config.EDGE_SAMPLES) -> np.ndarray:
    """Resample an open polyline to `n` points evenly spaced by arc length."""
    P = np.asarray(points, dtype=np.float64)
    if len(P) < 2:
        return np.repeat(P, n, axis=0)[:n]
    seg = np.hypot(*np.diff(P, axis=0).T)
    d = np.concatenate([[0.0], np.cumsum(seg)])
    if d[-1] <= 0:
        return np.repeat(P[:1], n, axis=0)
    t = np.linspace(0.0, d[-1], n)
    return np.column_stack([np.interp(t, d, P[:, 0]),
                            np.interp(t, d, P[:, 1])])


def smooth_closed(points: np.ndarray, sigma: float = config.SMOOTH_SIGMA) -> np.ndarray:
    """Gaussian smoothing along a closed contour, wrapping at the seam."""
    P = np.asarray(points, dtype=np.float64)
    n = len(P)
    k = max(3, int(sigma * 4) | 1)
    g = cv2.getGaussianKernel(k, sigma).ravel()
    pad = np.vstack([P[-k:], P, P[:k]])
    sx = np.convolve(pad[:, 0], g, mode="same")[k:k + n]
    sy = np.convolve(pad[:, 1], g, mode="same")[k:k + n]
    return np.column_stack([sx, sy])


def perimeter(points: np.ndarray, closed: bool = True) -> float:
    P = np.asarray(points, dtype=np.float64)
    if closed:
        P = np.vstack([P, P[:1]])
    return float(np.hypot(*np.diff(P, axis=0).T).sum())


def polygon_area(points: np.ndarray) -> float:
    P = np.asarray(points, dtype=np.float64)
    x, y = P[:, 0], P[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def area_centroid(points: np.ndarray) -> np.ndarray:
    """True area centroid of a closed polygon.

    Note this is NOT the mean of arc-length-resampled points -- for a shape with
    tabs and blanks those differ, and using the wrong one corrupts registration.
    """
    P = np.asarray(points, dtype=np.float64)
    x, y = P[:, 0], P[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    a = cross.sum() / 2.0
    if abs(a) < 1e-9:
        return P.mean(axis=0)
    cx = ((x + x1) * cross).sum() / (6.0 * a)
    cy = ((y + y1) * cross).sum() / (6.0 * a)
    return np.array([cx, cy])


# --------------------------------------------------------------- registration

def icp_register(target: np.ndarray, source: np.ndarray,
                 initial_angles=(0.0, 90.0, 180.0, 270.0),
                 iterations: int = 60):
    """Rigid-fit `source` onto `target` by iterative closest point.

    Returns (transformed_source, residuals, rotation_degrees). `residuals` is the
    per-point nearest-neighbour distance, so `residuals.mean()` is the headline
    boundary agreement figure.
    """
    A = np.asarray(target, dtype=np.float64)
    B = np.asarray(source, dtype=np.float64)
    A = A - area_centroid(A)
    B = B - area_centroid(B)
    tree = cKDTree(A)

    best = None
    for a0 in initial_angles:
        th = np.radians(a0)
        R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        t = np.zeros(2)
        for _ in range(iterations):
            Q = B @ R.T + t
            _, idx = tree.query(Q)
            X = A[idx]
            Bc = B - B.mean(axis=0)
            Xc = X - X.mean(axis=0)
            U, _, Vt = np.linalg.svd(Bc.T @ Xc)
            D = np.diag([1.0, np.sign(np.linalg.det(Vt.T @ U.T))])
            R = Vt.T @ D @ U.T
            t = X.mean(axis=0) - (B.mean(axis=0) @ R.T)
        Q = B @ R.T + t
        d, _ = tree.query(Q)
        if best is None or d.mean() < best[1].mean():
            best = (Q, d, float(np.degrees(np.arctan2(R[1, 0], R[0, 0]))))
    return best


def average_contours(a: np.ndarray, b: np.ndarray,
                     n: int = config.CONTOUR_SAMPLES):
    """Register two observations of the same piece and average them.

    The 180-degree second pass exists to cancel the directional component of the
    edge shadow (deficit ~25 levels on down-facing edges vs ~43 on up-facing).
    Averaging after registration collapses that spread.

    Returns (mean_contour, residual_mean_px).
    """
    A = smooth_closed(resample_closed(a, n))
    B = smooth_closed(resample_closed(b, n))
    Q, resid, _ = icp_register(A, B)
    A0 = A - area_centroid(A)

    # Pair each point of A0 with the nearest on Q, then average. Index-matched
    # averaging would fold in arc-length parametrisation drift.
    tree = cKDTree(Q)
    _, idx = tree.query(A0)
    return (A0 + Q[idx]) / 2.0, float(resid.mean())


# ------------------------------------------------------------------- corners

def find_corners(contour: np.ndarray):
    """Locate the four corners of a puzzle piece.

    Fast path: the body-rectangle method (`_body_rect_corners` -- piece body
    recovered by morphological close+open, then its min-area-rect corners). If
    that already splits the outline into even quarters (`corner_spacing_cv` <
    `CORNER_DEV_WARN`) the piece is clean and we keep it.

    Otherwise (deep blank pinching the body, a tilted piece, a lumpy body) run
    every estimator and keep the best by `_corner_set_quality`:
      * `_corners_phase` -- the pieces in this puzzle are extremely regular, so
        four markers slid around the outline in even quarters, snapped to the
        nearest real corner, recover a corner that another method dragged into a
        blank. This is the workhorse for the flagged cases.
      * `_corners_curvature` -- puzzle-bot-style per-vertex corner scoring plus a
        combinatorial four-corner pick; handles genuinely rotated pieces.
      * body-rect and `_fallback_diagonal`.

    A high quality score even in the winner means low confidence --
    `pipeline.build_record` stores `corner_spacing_cv` as `corner_dev` and flags
    the outliers.

    Returns indices into `contour`.
    """
    P = np.asarray(contour, dtype=np.float64)

    body = None
    body_corners = _body_rect_corners(P)
    if body_corners is not None:
        coarse = sorted({int(np.argmin(np.hypot(*(P - bc).T))) for bc in body_corners})
        if len(coarse) == 4:
            body = [_refine_corner(P, coarse, k) for k in range(4)]

    if body is not None and corner_spacing_cv(P, body) < config.CORNER_DEV_WARN:
        return body

    vscore, convex = _vertex_corner_score(P)
    candidates = [c for c in (_corners_phase(P, vscore, convex),
                              _corners_curvature(P, vscore, convex),
                              body,
                              _fallback_diagonal(P)) if c is not None]
    return min(candidates,
               key=lambda idx: _corner_set_quality(P, idx, vscore, convex))


def _wrap(a):
    """Wrap angle(s) to (-pi, pi]."""
    return (np.asarray(a) + np.pi) % (2 * np.pi) - np.pi


def _vertex_corner_score(P: np.ndarray, w: int | None = None):
    """Per-vertex 'how corner-like is this point' score (lower = better) plus a
    convex-vertex mask.

    Three terms: local turn far from 90 degrees, the corner opening away from
    the centroid (tab tips do, real corners don't), and curved sides (real
    corners have straight edges running in). Concave vertices -- blank bottoms --
    take a flat penalty.
    """
    n = len(P)
    w = w or max(6, n // 20)
    centre = area_centroid(P)

    back = P - np.roll(P, w, axis=0)          # P[i-w] -> P[i]
    fwd = np.roll(P, -w, axis=0) - P          # P[i]   -> P[i+w]
    turn = np.abs(_wrap(np.arctan2(fwd[:, 1], fwd[:, 0])
                        - np.arctan2(back[:, 1], back[:, 0])))

    winding = np.sign(_signed_area(P))
    cross = back[:, 0] * fwd[:, 1] - back[:, 1] * fwd[:, 0]
    convex = np.sign(cross) == winding

    bn = back / (np.linalg.norm(back, axis=1, keepdims=True) + 1e-9)
    fn = fwd / (np.linalg.norm(fwd, axis=1, keepdims=True) + 1e-9)
    bis = -(bn + fn)
    to_centre = centre - P
    off_centre = np.abs(_wrap(np.arctan2(bis[:, 1], bis[:, 0])
                              - np.arctan2(to_centre[:, 1], to_centre[:, 0])))

    straight = _spoke_straightness(P, w)

    score = (0.7 * np.abs(turn - np.pi / 2)
             + 0.4 * off_centre
             + 11.0 * straight ** 2)
    score[~convex] += 5.0
    return score, convex


def _corners_phase(P: np.ndarray, vscore, convex):
    """Regular-piece corner detection.

    The pieces in this puzzle are extremely uniform: four corners split the
    outline into near-equal quarters. Slide four evenly spaced markers around
    the contour, score each rotation phase by how corner-like the four points
    are, then let each marker refine to the true corner by side intersection.
    Recovers a corner that the body-rect or curvature method dragged into a
    deep blank, and copes with a slightly rectangular (non-square) piece.
    """
    n = len(P)
    if n < 16:
        return None
    centre = area_centroid(P)
    q = n / 4.0

    best, best_s = None, np.inf
    for phi in range(int(round(q))):
        idx = tuple(int(round(phi + k * q)) % n for k in range(4))
        if len(set(idx)) < 4:
            continue
        s = (_score_quad(P, idx, centre, vscore)
             + 3.0 * sum(0.0 if convex[i] else 1.0 for i in idx))
        if s < best_s:
            best, best_s = idx, s
    if best is None:
        return None
    return [_refine_corner(P, sorted(best), k) for k in range(4)]


def _corners_curvature(P: np.ndarray, vscore, convex):
    """Curvature-peak corner detection (puzzle-bot style).

    Local minima of the per-vertex corner score become candidates; the best four
    by combined spacing / 90-degree-spread / radius / vertex-score, rejecting
    pairs closer than an eighth of the outline (the collapsed-corner failure),
    are refined by side intersection.
    """
    n = len(P)
    if n < 40:
        return None
    centre = area_centroid(P)

    cand = [i for i in range(n)
            if vscore[i] < config.CORNER_CAND_MAX_SCORE
            and vscore[i] <= vscore[(i - 1) % n]
            and vscore[i] <= vscore[(i + 1) % n]]
    if len(cand) < 4:
        return None
    cand = sorted(cand, key=lambda i: vscore[i])[:14]

    min_sep = n / 8.0
    best, best_s = None, np.inf
    for combo in itertools.combinations(sorted(cand), 4):
        d = np.diff(combo + (combo[0] + n,))
        if d.min() < min_sep:
            continue
        s = _score_quad(P, combo, centre, vscore)
        if s < best_s:
            best, best_s = combo, s
    if best is None:
        return None
    return [_refine_corner(P, sorted(best), k) for k in range(4)]


def _corner_set_quality(P: np.ndarray, idx, vscore, convex) -> float:
    """Unified score for a proposed set of four corners (lower = better), used
    to choose between the estimators.

    `corner_spacing_cv` catches a collapsed pair; `_score_quad` rewards an even,
    rectangular quad; the convex term rejects a "corner" that actually sits in a
    blank -- the failure mode of the evenly-spaced phase method.
    """
    n = len(P)
    ii = [int(i) % n for i in idx]
    if len(set(ii)) < 4:
        return 1e9
    centre = area_centroid(P)
    conv_bad = sum(0.0 if convex[i] else 1.0 for i in ii)
    return (2.0 * corner_spacing_cv(P, ii)
            + 1.0 * _score_quad(P, ii, centre, vscore)
            + 3.0 * conv_bad)


def _spoke_straightness(P: np.ndarray, w: int) -> np.ndarray:
    """Per-vertex circular stdev of the heading from P[i] to each of the w
    points on either side. Low where the contour runs straight into P[i]."""
    n = len(P)
    base = np.arange(n)[:, None]
    off = np.arange(1, w + 1)[None, :]
    fwd = P[(base + off) % n] - P[:, None, :]
    bwd = P[(base - off) % n] - P[:, None, :]

    def cstd(v):
        a = np.arctan2(v[..., 1], v[..., 0])
        r = np.clip(np.hypot(np.cos(a).mean(1), np.sin(a).mean(1)), 1e-9, 1.0)
        return np.sqrt(-2.0 * np.log(r))

    return 0.5 * (cstd(bwd) + cstd(fwd))


def _score_quad(P: np.ndarray, idx, centre, vscore) -> float:
    """Score a candidate set of four corner indices (lower = better).

    A rectangular piece's corners: even arc-length quarters, evenly spread ~90
    degrees apart around the centroid, and at a similar radius from it.
    """
    n = len(P)
    idx = sorted(idx)
    pts = P[list(idx)]

    gaps = np.array([(idx[(k + 1) % 4] - idx[k]) % n for k in range(4)], float)
    gaps[gaps == 0] = n
    spacing = gaps.std() / gaps.mean()                       # 0 = even quarters

    ang = np.sort(np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0]))
    step = np.diff(np.concatenate([ang, [ang[0] + 2 * np.pi]]))
    ang_reg = step.std() / (np.pi / 2)                       # 0 = 90 deg apart

    rad = np.hypot(pts[:, 0] - centre[0], pts[:, 1] - centre[1])
    rad_reg = rad.std() / rad.mean()                         # 0 = equidistant

    return (4.0 * spacing + 3.0 * ang_reg + 2.0 * rad_reg
            + 0.05 * sum(vscore[i] for i in idx))


def _signed_area(P: np.ndarray) -> float:
    x, y = P[:, 0], P[:, 1]
    return float(0.5 * (np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def corner_spacing_cv(contour: np.ndarray, corner_idx) -> float:
    """Coefficient of variation of the four corner-to-corner arc lengths (in
    contour-point counts).

    0 = the corners split the contour into exact quarters. A clean piece scores
    below ~0.10; a corner-detection failure (a collapsed pair, or a corner
    dragged onto a tab) typically scores above 0.20.
    """
    n = len(contour)
    idx = sorted(int(i) % n for i in corner_idx)
    if len(set(idx)) < 4:
        return 1.0
    gaps = np.array([(idx[(k + 1) % 4] - idx[k]) % n for k in range(4)], float)
    gaps[gaps == 0] = n
    return float(gaps.std() / gaps.mean())


def _body_rect_corners(P: np.ndarray):
    """Recover the piece body (tabs removed, blanks filled) and return its
    rectangle corners, ordered to match contour traversal order."""
    mins = P.min(axis=0)
    span = P.max(axis=0) - mins
    pad = 40
    w = int(span[0]) + 2 * pad
    h = int(span[1]) + 2 * pad
    if w < 10 or h < 10 or w > 20000 or h > 20000:
        return None

    mask = np.zeros((h, w), np.uint8)
    shifted = (P - mins + pad).astype(np.int32)
    cv2.fillPoly(mask, [shifted], 255)

    # A tab is roughly a quarter of the piece width across at its neck. Opening
    # with a disk near that size removes tabs; closing first fills blanks.
    r = max(3, int(min(span) * 0.18))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    body = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    body = cv2.morphologyEx(body, cv2.MORPH_OPEN, k)

    cnts, _ = cv2.findContours(body, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    big = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(big) < 0.25 * cv2.contourArea(shifted.reshape(-1, 1, 2)):
        return None

    box = cv2.boxPoints(cv2.minAreaRect(big))
    return box.astype(np.float64) + mins - pad


def _fallback_diagonal(P: np.ndarray):
    """Original diagonal-extreme method, kept as a fallback."""
    c = area_centroid(P)
    rect = cv2.minAreaRect(P.astype(np.float32))
    theta = np.radians(rect[2])
    base = np.array([[np.cos(theta), -np.sin(theta)],
                     [np.sin(theta), np.cos(theta)]])
    diagonals = [base @ np.array([s1, s2]) / np.sqrt(2.0)
                 for s1, s2 in [(-1, -1), (1, -1), (1, 1), (-1, 1)]]
    rel = P - c
    coarse = sorted(set(int(np.argmax(rel @ d)) for d in diagonals))
    if len(coarse) != 4:
        return _evenly_spaced_fallback(P, coarse)
    return [_refine_corner(P, coarse, k) for k in range(4)]


def _evenly_spaced_fallback(P, found):
    n = len(P)
    start = found[0] if found else 0
    return [(start + int(round(i * n / 4.0))) % n for i in range(4)]


def _refine_corner(P: np.ndarray, coarse, k: int) -> int:
    """Refine one corner by intersecting line fits from the two adjacent sides.

    Near a corner both sides are straight for roughly the first quarter of their
    length -- the tab or blank lives in the middle. Fitting those straight
    stretches and intersecting them recovers the corner even when the physical
    corner is rounded or slightly dinged.
    """
    n = len(P)
    i_prev, i_this, i_next = coarse[k - 1], coarse[k], coarse[(k + 1) % 4]

    incoming = _arc(P, i_prev, i_this)
    outgoing = _arc(P, i_this, i_next)
    if len(incoming) < 8 or len(outgoing) < 8:
        return i_this

    q_in = incoming[-max(4, len(incoming) // 4):]
    q_out = outgoing[:max(4, len(outgoing) // 4)]

    line_a = _fit_line(q_in)
    line_b = _fit_line(q_out)
    pt = _intersect(line_a, line_b)
    if pt is None:
        return i_this

    # snap the intersection back onto the contour
    return int(np.argmin(np.hypot(*(P - pt).T)))


def _arc(P: np.ndarray, i0: int, i1: int) -> np.ndarray:
    n = len(P)
    if i0 <= i1:
        return P[i0:i1 + 1]
    return np.vstack([P[i0:], P[:i1 + 1]])


def _fit_line(pts: np.ndarray):
    """Total-least-squares line fit. Returns (point_on_line, unit_direction)."""
    mu = pts.mean(axis=0)
    _, _, Vt = np.linalg.svd(pts - mu)
    return mu, Vt[0]


def _intersect(la, lb):
    (p, u), (q, v) = la, lb
    denom = u[0] * v[1] - u[1] * v[0]
    if abs(denom) < 1e-9:
        return None
    w = q - p
    t = (w[0] * v[1] - w[1] * v[0]) / denom
    return p + t * u


# --------------------------------------------------------------------- edges

def split_edges(contour: np.ndarray, corner_idx):
    """Split a closed contour into its four edges, in contour order."""
    P = np.asarray(contour, dtype=np.float64)
    idx = sorted(int(i) for i in corner_idx)
    return [_arc(P, idx[k], idx[(k + 1) % 4]) for k in range(4)]


def classify_edge(edge: np.ndarray, centroid: np.ndarray) -> tuple[str, float]:
    """Classify one edge as TAB, BLANK or BORDER.

    Measures the signed deviation of the edge from its corner-to-corner chord,
    with positive meaning away from the piece centre. Returns (type, deviation)
    where deviation is normalised by chord length.
    """
    E = np.asarray(edge, dtype=np.float64)
    if len(E) < 3:
        return "BORDER", 0.0

    a, b = E[0], E[-1]
    chord = b - a
    length = np.hypot(*chord)
    if length < 1e-9:
        return "BORDER", 0.0

    unit = chord / length
    normal = np.array([-unit[1], unit[0]])
    # orient the normal to point away from the piece centre
    if np.dot(((a + b) / 2.0) - centroid, normal) < 0:
        normal = -normal

    dev = (E - a) @ normal
    peak = dev[np.argmax(np.abs(dev))] / length

    if abs(peak) < config.BORDER_MAX_DEVIATION:
        return "BORDER", float(peak)
    if peak >= config.TAB_MIN_DEVIATION:
        return "TAB", float(peak)
    if peak <= -config.TAB_MIN_DEVIATION:
        return "BLANK", float(peak)
    return ("TAB" if peak > 0 else "BLANK"), float(peak)


def normalise_edge(edge: np.ndarray, n: int = config.EDGE_SAMPLES) -> np.ndarray:
    """Put an edge in a canonical frame so two edges can be compared directly.

    Translates the first corner to the origin and rotates so the chord lies along
    +x. Scale is deliberately NOT normalised -- piece size varies 23% across this
    puzzle and that size difference is real matching information.
    """
    E = resample_open(edge, n)
    a, b = E[0], E[-1]
    chord = b - a
    length = np.hypot(*chord)
    if length < 1e-9:
        return E - a
    th = -np.arctan2(chord[1], chord[0])
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    return (E - a) @ R.T


def cyclic_signature(edge_types) -> str:
    """Canonical rotation-invariant form of the four edge types.

    Interior pieces have no determinable orientation, so the topology is a cyclic
    string, not a fixed N/E/S/W tuple. Returns the lexicographically smallest
    rotation, which makes two pieces of the same class compare equal regardless
    of how they happened to sit on the scanner.
    """
    t = list(edge_types)
    rotations = ["|".join(t[i:] + t[:i]) for i in range(len(t))]
    return min(rotations)
