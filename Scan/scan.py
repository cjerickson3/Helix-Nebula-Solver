"""
Scan loading, thresholding, fiducial detection and piece extraction.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

from . import config

Image.MAX_IMAGE_PIXELS = None


# ------------------------------------------------------------------ loading

def load_scan(path) -> np.ndarray:
    """Load a scan as an RGB array."""
    return np.array(Image.open(str(path)).convert("RGB"))


def red_channel(image: np.ndarray, channel: int = 0) -> np.ndarray:
    """The channel everything downstream thresholds on. Red (0, default) is
    what every teal/dark sheet uses -- magenta card reads ~167 here while both
    teal and black pieces read 0-57, a 116-level gap.

    `channel=1` (green) is for pieces whose own colour collides with the red
    backing -- the puzzle's red/orange core pieces measure R~150-160 against a
    magenta/red backing's R~170-193, nowhere near the usual 100+ level margin,
    and it doesn't matter which orientation they're scanned in (the piece is
    simply the wrong colour for this backing, not a shadow effect). Red and
    green are complementary, so scanning those pieces on a saturated GREEN
    backing restores the gap: red/orange pieces read low green, the backing
    reads high green.
    """
    return image[:, :, channel]


def backing_level(red: np.ndarray) -> int:
    """Estimate the backing level as the histogram mode above BACKING_MIN_LEVEL."""
    hist = np.histogram(red, bins=256, range=(0, 256))[0]
    lo = config.BACKING_MIN_LEVEL
    return int(lo + np.argmax(hist[lo:]))


def threshold_level(red: np.ndarray) -> int:
    """Fixed threshold derived from the measured backing, never Otsu.

    Otsu recomputes per image, so the proportion of dark to teal pieces on a
    sheet shifts the threshold and moves every boundary: measured 1.68% perimeter
    jitter on rescan versus 0.36% for a fixed level.
    """
    backing = backing_level(red)
    if backing < config.BACKING_MIN_LEVEL:
        return config.THRESHOLD_FALLBACK
    return int(round(backing * config.THRESHOLD_RATIO))


def piece_mask(red: np.ndarray, level: int | None = None) -> np.ndarray:
    """Binary mask, 255 where a piece is."""
    if level is None:
        level = threshold_level(red)
    _, mask = cv2.threshold(red, level, 255, cv2.THRESH_BINARY_INV)
    k = np.ones((config.MORPH_KERNEL, config.MORPH_KERNEL), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    return mask


# ---------------------------------------------------------------- anisotropy

def correct_anisotropy(points: np.ndarray) -> np.ndarray:
    """Apply the measured scanner x/y scale correction.

    sx/sy = 0.99772 from a square target scanned at 0 and 90 degrees, two
    independent estimates agreeing to 0.04%. The effect is small (~0.43 px on a
    190 px tab feature, against 4 px boundary noise) but it is exact and free.
    """
    P = np.asarray(points, dtype=np.float64).copy()
    P[:, 1] *= config.ANISOTROPY_SY
    return P


# ----------------------------------------------------------------- fiducials

@dataclass
class Fiducials:
    corners: np.ndarray | None      # 4x2, ordered TL, TR, BR, BL
    asymmetry: np.ndarray | None    # 1x2 or None
    all_marks: np.ndarray

    @property
    def found(self) -> bool:
        return self.corners is not None


def detect_fiducials(image: np.ndarray, red_level: int | None = None,
                     channel: int = 0) -> Fiducials:
    """Find the near-black registration dots on the red backing.

    Worked on the RED channel, not luminance greyscale: the card's greyscale is
    ~95 on magenta stock (and lower still on deep-red stock), so a fixed grey
    threshold floods and the whole sheet reads as one dark blob. In the red
    channel the dots sit at R ~ 45 against a backing of R ~ 167-205, and the same
    ratio threshold the piece extractor uses isolates them.

    The sheet carries dots in two sizes: four large corner dots that define the
    homography (~5.5 mm), plus smaller orientation markers (~3.3 mm) -- an offset
    dot and/or corner satellites. Only the four large corner dots populate
    `corners`; the largest leftover mark becomes `asymmetry`; `all_marks` holds
    every detected dot.

    Fiducials are ~5,000-13,000 px against ~210,000 px for a piece -- 20:1 or
    more -- so area separates them from pieces cleanly even though both are dark.
    Centroids are intensity-weighted, localising a filled disc to well under a
    pixel.
    """
    red = red_channel(image, channel)
    if red_level is None:
        red_level = threshold_level(red)

    _, mask = cv2.threshold(red, red_level, 255, cv2.THRESH_BINARY_INV)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                  (config.FIDUCIAL_MORPH, config.FIDUCIAL_MORPH))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

    marks = []          # [x, y, area]
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not (config.FIDUCIAL_AREA_MIN < area < config.FIDUCIAL_AREA_MAX):
            continue
        if abs(w / max(h, 1) - 1.0) > config.FIDUCIAL_ASPECT_TOL:
            continue
        if area / float(w * h) < config.FIDUCIAL_FILL_MIN:   # discs fill ~0.79 of their bbox
            continue
        ys, xs = np.where(labels == i)
        weight = 255.0 - red[ys, xs].astype(np.float64)
        total = weight.sum()
        if total <= 0:
            continue
        marks.append([(xs * weight).sum() / total,
                      (ys * weight).sum() / total, float(area)])

    marks = np.array(marks, dtype=np.float64)
    if len(marks) < 4:
        return Fiducials(None, None, marks[:, :2] if len(marks) else marks)

    pts, areas = marks[:, :2], marks[:, 2]

    # Split large (corner) dots from small (orientation) dots at the biggest gap
    # in the sorted area list, but only if that gap is genuinely large -- an
    # all-one-size sheet keeps every dot as a corner candidate.
    order = np.argsort(areas)
    gaps = np.diff(areas[order])
    if len(gaps) and gaps.max() > areas.mean() * config.FIDUCIAL_SIZE_SPLIT:
        large = pts[order[int(np.argmax(gaps)) + 1:]]
    else:
        large = pts
    if len(large) < 4:
        large = pts

    # the four extreme corners of the large group
    cc = large.mean(axis=0)
    def pick(sx, sy):
        score = (large[:, 0] - cc[0]) * sx + (large[:, 1] - cc[1]) * sy
        return large[int(np.argmax(score))]
    ordered = np.array([pick(-1, -1), pick(1, -1), pick(1, 1), pick(-1, 1)])
    if len({tuple(np.round(p, 1)) for p in ordered}) < 4:
        return Fiducials(None, None, pts)          # picks collapsed -> not a clean quad

    used = {tuple(np.round(p, 1)) for p in ordered}
    rest = np.array([p for p in pts if tuple(np.round(p, 1)) not in used])
    asym = None
    if len(rest):
        far = [min(np.hypot(*(c - r)) for c in ordered) for r in rest]
        asym = rest[int(np.argmax(far))]

    return Fiducials(ordered, asym, pts)


def sheet_homography(src: Fiducials, dst: Fiducials):
    """Homography mapping one pass's sheet frame onto the other's.

    A homography rather than a rigid transform because the four fiducials showed
    a small trapezoidal component (~8 px) from sheet flatness and drawing error.
    Four point pairs is exactly enough to solve one.

    The second pass is the sheet turned 180 degrees, so corner k of the source
    corresponds to corner k+2 of the destination.
    """
    if not (src.found and dst.found):
        return None
    rolled = np.roll(dst.corners, 2, axis=0)
    H, _ = cv2.findHomography(src.corners.astype(np.float32),
                              rolled.astype(np.float32), 0)
    return H


# -------------------------------------------------------------------- pieces

@dataclass
class RawPiece:
    contour: np.ndarray
    area: float
    centroid: np.ndarray
    mean_lab: np.ndarray = field(default_factory=lambda: np.zeros(3))
    colour: dict = field(default_factory=dict)


def colour_descriptor(lab: np.ndarray, hsv: np.ndarray, blob: np.ndarray) -> dict:
    """Per-piece colour summary for the region / landmark pre-filter.

    Returns mean & std LAB, saturation-weighted dominant hue, a linear lightness
    gradient (`gradient_magnitude` in LAB-L units across the piece, 0 = uniform;
    `gradient_angle_deg` points brightest -> darkest, 0 = right, 90 = up), and a
    3x3 zone fingerprint. Zones are numbered column-row from the piece bounding
    box: zone_00 = top-left, zone_10 = top-centre, ... zone_22 = bottom-right.

    LAB is OpenCV's 0-255 encoding (a/b offset by 128) to match the rest of the
    pipeline; hue is degrees (0-360).
    """
    ys, xs = np.where(blob > 0)
    if len(xs) < 200:
        return {}
    L = lab[ys, xs, 0].astype(np.float64)
    A = lab[ys, xs, 1].astype(np.float64)
    B = lab[ys, xs, 2].astype(np.float64)
    hue = hsv[ys, xs, 0].astype(np.float64) * 2.0        # OpenCV H 0-179 -> deg
    sat = hsv[ys, xs, 1].astype(np.float64)

    x0, y0 = xs.min(), ys.min()
    w = max(int(xs.max() - x0), 1)
    h = max(int(ys.max() - y0), 1)

    def wmean_hue(hh, ss):
        if ss.sum() < 1e-6:
            return 0.0
        a = np.radians(hh)
        return float(np.degrees(np.arctan2((np.sin(a) * ss).sum(),
                                           (np.cos(a) * ss).sum())) % 360.0)

    # linear lightness plane over normalised coords in [-0.5, 0.5]
    xn = (xs - x0) / w - 0.5
    yn = (ys - y0) / h - 0.5
    gx, gy, _ = np.linalg.lstsq(
        np.column_stack([xn, yn, np.ones_like(xn)]), L, rcond=None)[0]
    grad_mag = float(np.hypot(gx, gy))
    grad_ang = (float(np.degrees(np.arctan2(-gy, -gx)) % 360.0)
                if grad_mag > 1e-6 else 0.0)

    out = dict(
        lab_l_mean=float(L.mean()), lab_a_mean=float(A.mean()), lab_b_mean=float(B.mean()),
        lab_l_std=float(L.std()), lab_a_std=float(A.std()), lab_b_std=float(B.std()),
        dominant_hue=wmean_hue(hue, sat),
        gradient_magnitude=grad_mag, gradient_angle_deg=grad_ang,
    )
    col = np.clip(((xs - x0) * 3 // w).astype(int), 0, 2)
    row = np.clip(((ys - y0) * 3 // h).astype(int), 0, 2)
    for cc in range(3):
        for rr in range(3):
            sel = (col == cc) & (row == rr)
            out[f"zone_{cc}{rr}_hue"] = wmean_hue(hue[sel], sat[sel]) if sel.sum() > 20 else 0.0
            out[f"zone_{cc}{rr}_lab_l"] = float(L[sel].mean()) if sel.sum() > 20 else 0.0
    return out


def extract_pieces(image: np.ndarray, level: int | None = None, channel: int = 0):
    """Find every piece in a scan.

    Returns (pieces, diagnostics). Diagnostics reports suspected merges and
    debris rather than silently dropping them -- two touching pieces produce a
    single plausible-looking contour, which is the one failure mode that can
    poison the database without being obvious.

    `channel` selects red (0, default), green (1) or blue (2) -- see
    `red_channel` for when green is needed (red/orange pieces on red backing).
    """
    red = red_channel(image, channel)
    if level is None:
        level = threshold_level(red)
    mask = piece_mask(red, level)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)

    pieces, rejected = [], []
    for c in contours:
        area = cv2.contourArea(c)
        if area < config.PIECE_AREA_MIN:
            rejected.append(area)
            continue
        pts = c[:, 0, :].astype(np.float64)
        m = cv2.moments(c)
        if m["m00"] <= 0:
            continue
        centroid = np.array([m["m10"] / m["m00"], m["m01"] / m["m00"]])

        blob = np.zeros(mask.shape, np.uint8)
        cv2.drawContours(blob, [c], -1, 255, -1)
        # shrink the sampling mask off the shadowed rim before reading colour
        core = cv2.erode(blob, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
        if core.sum() < 200 * 255:
            core = blob
        mean_lab = cv2.mean(lab, mask=core)[:3]
        colour = colour_descriptor(lab, hsv, core)

        pieces.append(RawPiece(pts, float(area), centroid, np.array(mean_lab), colour))

    diag = {
        "threshold": level,
        "backing": backing_level(red),
        "n_pieces": len(pieces),
        "largest_rejected": max(rejected) if rejected else 0.0,
        "merges": [],
    }
    if pieces:
        med = float(np.median([p.area for p in pieces]))
        diag["median_area"] = med
        diag["merges"] = [i for i, p in enumerate(pieces)
                          if p.area > config.MERGE_AREA_FACTOR * med]
    return pieces, diag


def pair_passes(pieces_a, pieces_b, shape, H=None):
    """Match pieces between the 0 and 180 degree passes.

    With a fiducial homography `H` (pass B pixel frame -> pass A pixel frame),
    each B centroid is projected into A's frame and matching is a direct
    nearest-neighbour lookup. Without one, fall back to the assumption that a
    180-degree sheet flip sends a piece at (x, y) to (W-x, H-y) -- good to a few
    mm when the sheet was re-seated carefully (validated 36/36 on the fiducial-
    free regression pair), but the homography is tighter and absorbs re-seating
    offset and trapezoidal distortion.
    """
    height, width = shape[0], shape[1]

    if H is not None and len(pieces_b):
        b_src = np.array([pb.centroid for pb in pieces_b],
                         dtype=np.float64).reshape(-1, 1, 2)
        b_pos = cv2.perspectiveTransform(b_src, H).reshape(-1, 2)
        expect_of = lambda pa: pa.centroid
    else:
        b_pos = np.array([pb.centroid for pb in pieces_b], dtype=np.float64)
        expect_of = lambda pa: np.array([width - pa.centroid[0],
                                         height - pa.centroid[1]])

    used, pairs = set(), []
    for i, pa in enumerate(pieces_a):
        expect = expect_of(pa)
        best = None
        for j in range(len(pieces_b)):
            if j in used:
                continue
            d = float(np.hypot(*(b_pos[j] - expect)))
            if best is None or d < best[1]:
                best = (j, d)
        if best is None:
            continue
        used.add(best[0])
        pairs.append((i, best[0], best[1]))
    return pairs
