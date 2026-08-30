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

    Naively taking the four diagonal extremes fails whenever a tab sits near a
    corner -- the tab tip is further out than the corner is, so the marker lands
    on the tab. Measured failure rate on real scans: ~11% of pieces, and every
    such failure silently corrupts the piece's topology.

    Instead we first recover the piece *body* by morphological opening, which
    erases tabs and fills blanks, leaving a near-square. The minimum-area
    rectangle of that body gives four reliable corner estimates, which are then
    snapped to the contour and refined by intersecting straight-line fits to the
    flat stretches either side of each corner.

    Returns indices into `contour`.
    """
    P = np.asarray(contour, dtype=np.float64)
    n = len(P)

    body_corners = _body_rect_corners(P)
    if body_corners is None:
        return _fallback_diagonal(P)

    # snap each rectangle corner to the nearest contour point
    coarse = []
    for bc in body_corners:
        coarse.append(int(np.argmin(np.hypot(*(P - bc).T))))

    coarse = sorted(set(coarse))
    if len(coarse) != 4:
        return _fallback_diagonal(P)

    return [_refine_corner(P, coarse, k) for k in range(4)]


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
