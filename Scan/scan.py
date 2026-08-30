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


def red_channel(image: np.ndarray) -> np.ndarray:
    """The red channel is what everything downstream thresholds on.

    Magenta card reads ~167 here while both teal and black pieces read 0-57,
    a 116-level gap. Blue backing was tested and gives only 95 levels, with teal
    pieces sitting uncomfortably close to it.
    """
    return image[:, :, 0]


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


def detect_fiducials(image: np.ndarray) -> Fiducials:
    """Find the black registration dots.

    Fiducials are ~2,000 px in area against ~210,000 px for a piece -- a hundred
    to one, so area alone separates them unambiguously even though both are dark.
    Centroids are intensity-weighted, which localises a filled disc to well under
    a pixel.
    """
    grey = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, mask = cv2.threshold(grey, config.FIDUCIAL_DARK_LEVEL, 255, cv2.THRESH_BINARY_INV)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

    marks = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        if not (config.FIDUCIAL_AREA_MIN < area < config.FIDUCIAL_AREA_MAX):
            continue
        if abs(w / max(h, 1) - 1.0) > config.FIDUCIAL_ASPECT_TOL:
            continue
        ys, xs = np.where(labels == i)
        weight = 255.0 - grey[ys, xs].astype(np.float64)
        total = weight.sum()
        if total <= 0:
            continue
        marks.append([(xs * weight).sum() / total, (ys * weight).sum() / total])

    marks = np.array(marks, dtype=np.float64)
    if len(marks) < 4:
        return Fiducials(None, None, marks)

    centre = marks.mean(axis=0)
    dist = np.hypot(*(marks - centre).T)
    corner_idx = np.argsort(dist)[-4:]
    corners = marks[corner_idx]

    asym = None
    if len(marks) >= 5:
        asym = marks[np.argsort(dist)[0]]

    cc = corners.mean(axis=0)
    def pick(sx, sy):
        score = (corners[:, 0] - cc[0]) * sx + (corners[:, 1] - cc[1]) * sy
        return corners[int(np.argmax(score))]
    ordered = np.array([pick(-1, -1), pick(1, -1), pick(1, 1), pick(-1, 1)])
    return Fiducials(ordered, asym, marks)


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


def extract_pieces(image: np.ndarray, level: int | None = None):
    """Find every piece in a scan.

    Returns (pieces, diagnostics). Diagnostics reports suspected merges and
    debris rather than silently dropping them -- two touching pieces produce a
    single plausible-looking contour, which is the one failure mode that can
    poison the database without being obvious.
    """
    red = red_channel(image)
    if level is None:
        level = threshold_level(red)
    mask = piece_mask(red, level)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)

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
        mean_lab = cv2.mean(lab, mask=blob)[:3]

        pieces.append(RawPiece(pts, float(area), centroid, np.array(mean_lab)))

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


def pair_passes(pieces_a, pieces_b, shape):
    """Match pieces between the 0 and 180 degree passes.

    Under a 180-degree sheet rotation a piece at (x, y) lands at (W-x, H-y), so
    the expected position is known and matching is a nearest-neighbour lookup
    rather than a shape search. Validated at 36/36 unique matches.
    """
    height, width = shape[0], shape[1]
    used, pairs = set(), []
    for i, pa in enumerate(pieces_a):
        expect = np.array([width - pa.centroid[0], height - pa.centroid[1]])
        best = None
        for j, pb in enumerate(pieces_b):
            if j in used:
                continue
            d = float(np.hypot(*(pb.centroid - expect)))
            if best is None or d < best[1]:
                best = (j, d)
        if best is None:
            continue
        used.add(best[0])
        pairs.append((i, best[0], best[1]))
    return pairs
