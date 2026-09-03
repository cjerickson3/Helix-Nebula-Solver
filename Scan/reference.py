"""The Spitzer reference image, registered to the puzzle print.

The puzzle picture is the 2007 Spitzer "ssc2007-03a" MIPS+IRAC "Eye of God"
(`NASA-PIA09178.tif`). Session 9 registered it to the scanned box front by SIFT
on the star field (256 RANSAC inliers, ghost-free overlay). This module wraps
that: `puzzle_frame()` returns the reference resampled into the puzzle's own
frame -- upright, same aspect and scale as the assembled puzzle -- so a piece
face can be slid over it directly.

Reference resolution over the puzzle is ~83-110 px per piece pitch. That is
enough to *shortlist* candidate positions for a piece; it is not enough to place
the featureless teal-interior pieces outright (see CLAUDE.md, Session 9 and the
zone map).

Paths default to a `Nebula_Eye/` folder beside the repo; override via the
env vars HELIX_REFERENCE_TIF / HELIX_BOX_FRONT or the function arguments.
Everything derived is cached under `resources/` (gitignored).
"""
from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

_REPO = Path(__file__).resolve().parent.parent
_NEBULA = _REPO.parent / "Nebula_Eye"
_CACHE = _REPO / "resources"

REFERENCE_TIF = Path(os.environ.get("HELIX_REFERENCE_TIF",
                                    _NEBULA / "NASA-PIA09178.tif"))
BOX_FRONT = Path(os.environ.get("HELIX_BOX_FRONT",
                                _NEBULA / "Box-Front.png"))

# The puzzle-picture rectangle inside Box-Front.png (portrait scan). Measured
# Session 9; the print bleeds slightly past the reference's left edge (black sky).
BOX_CROP = (80, 120, 4270, 6520)          # x0, y0, x1, y1

# assembled puzzle is ~30 in wide; body pitch ~19.7 mm -> ~38.7 pieces across
PIECES_ACROSS = 38.7

_FRAME_PNG = _CACHE / "reference_puzzle_frame.png"
_XFORM_NPZ = _CACHE / "reference_registration.npz"


def _sift_affine(ref_gray, box_gray, target=1600):
    """Similarity transform ref(full) -> box_crop(full) from SIFT star matches."""
    def scaled(g):
        f = target / max(g.shape)
        return cv2.resize(g, (int(g.shape[1] * f), int(g.shape[0] * f))), f

    rs, rf = scaled(ref_gray)
    bs, bf = scaled(box_gray)
    clahe = cv2.createCLAHE(2.0, (8, 8))
    rs, bs = clahe.apply(rs), clahe.apply(bs)

    sift = cv2.SIFT_create(nfeatures=8000, contrastThreshold=0.02, edgeThreshold=15)
    k1, d1 = sift.detectAndCompute(rs, None)
    k2, d2 = sift.detectAndCompute(bs, None)
    flann = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64))
    good = [m for m, n in flann.knnMatch(d1, d2, k=2) if m.distance < 0.75 * n.distance]
    if len(good) < 30:
        raise RuntimeError(f"reference registration: only {len(good)} SIFT matches")

    src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                         ransacReprojThreshold=3.0,
                                         maxIters=20000, confidence=0.999)
    if M is None or int(inl.sum()) < 20:
        raise RuntimeError("reference registration: RANSAC failed")

    Mh = np.vstack([M, [0, 0, 1]])
    full = (np.diag([1 / bf, 1 / bf, 1.0]) @ Mh @ np.diag([rf, rf, 1.0]))
    return full, int(inl.sum()), len(good)


def register(rebuild=False):
    """Return (transform 3x3 ref->box_crop, n_inliers, n_matches), cached."""
    if _XFORM_NPZ.exists() and not rebuild:
        z = np.load(_XFORM_NPZ)
        return z["transform"], int(z["inliers"]), int(z["matches"])

    if not REFERENCE_TIF.exists() or not BOX_FRONT.exists():
        raise FileNotFoundError(
            f"need {REFERENCE_TIF} and {BOX_FRONT} (set HELIX_REFERENCE_TIF / "
            f"HELIX_BOX_FRONT or pass paths)")

    ref = np.asarray(Image.open(REFERENCE_TIF).convert("RGB"))
    box = np.asarray(Image.open(BOX_FRONT).convert("RGB"))
    x0, y0, x1, y1 = BOX_CROP
    box_crop = box[y0:y1, x0:x1]

    full, inliers, matches = _sift_affine(
        cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY),
        cv2.cvtColor(box_crop, cv2.COLOR_RGB2GRAY))
    _CACHE.mkdir(exist_ok=True)
    np.savez(_XFORM_NPZ, transform=full, inliers=inliers, matches=matches)
    return full, inliers, matches


def puzzle_frame(rebuild=False) -> np.ndarray:
    """RGB reference resampled into the upright puzzle frame (cached PNG)."""
    if _FRAME_PNG.exists() and not rebuild:
        return np.asarray(Image.open(_FRAME_PNG).convert("RGB"))

    full, *_ = register(rebuild=rebuild)
    ref = np.asarray(Image.open(REFERENCE_TIF).convert("RGB"))
    x0, y0, x1, y1 = BOX_CROP
    in_box = cv2.warpAffine(ref, full[:2], (x1 - x0, y1 - y0))
    upright = cv2.rotate(in_box, cv2.ROTATE_90_CLOCKWISE)   # box scanned portrait
    _CACHE.mkdir(exist_ok=True)
    Image.fromarray(upright).save(_FRAME_PNG)
    return upright


def px_per_pitch(frame: np.ndarray | None = None) -> float:
    if frame is None:
        frame = puzzle_frame()
    return frame.shape[1] / PIECES_ACROSS


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="build / inspect the reference registration")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    full, inl, n = register(rebuild=args.rebuild)
    frame = puzzle_frame(rebuild=args.rebuild)
    sc = np.hypot(full[0, 0], full[0, 1])
    rot = np.degrees(np.arctan2(full[0, 1], full[0, 0]))
    print(f"registration: {inl}/{n} inliers, scale {sc:.4f}, rot {rot:.2f} deg")
    print(f"puzzle frame: {frame.shape[1]}x{frame.shape[0]} px, "
          f"~{px_per_pitch(frame):.0f} px/pitch")
    print(f"cached: {_FRAME_PNG.name}, {_XFORM_NPZ.name}")
