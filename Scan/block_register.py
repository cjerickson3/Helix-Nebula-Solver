"""Register a photo of an assembled, connected region against the Spitzer
reference (`Scan.reference.puzzle_frame()`).

Session 10 found that a large, richly-textured connected block of solved
pieces registers cleanly via SIFT + ZNCC, in sharp contrast to every attempt
at localizing isolated pieces (T03, T04 -- see CLAUDE.md zone map). That run
used a throwaway scratchpad script; this module makes it reproducible and is
the foundation for Pending Task 4c (does *individual* piece geometry within
an anchored block also place against the reference).

IMPORTANT: always register against `reference.puzzle_frame()`, never the raw
reference TIF -- a raw-TIF SIFT fit can RANSAC-fit a plausible-looking but
geometrically impossible transform (corners projecting outside the canvas).
Session 10 hit exactly this trap.

Usage:
    uv run python -m Scan.block_register "../Nebula_Eye/Assembled-Nebula.png"
"""
from __future__ import annotations
import numpy as np
import cv2
from PIL import Image

from . import reference

Image.MAX_IMAGE_PIXELS = None


def _sift_affine(src_gray, dst_gray, target=1600, min_matches=10):
    """Similarity transform src(full) -> dst(full) via SIFT + RANSAC.

    Returns (transform 3x3, n_inliers, n_matches).
    """
    def scaled(g):
        f = target / max(g.shape)
        return cv2.resize(g, (int(g.shape[1] * f), int(g.shape[0] * f))), f

    ss, sf = scaled(src_gray)
    ds, df = scaled(dst_gray)
    clahe = cv2.createCLAHE(2.0, (8, 8))
    ss, ds = clahe.apply(ss), clahe.apply(ds)

    sift = cv2.SIFT_create(nfeatures=8000, contrastThreshold=0.02, edgeThreshold=15)
    k1, d1 = sift.detectAndCompute(ss, None)
    k2, d2 = sift.detectAndCompute(ds, None)
    flann = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64))
    good = [m for m, n in flann.knnMatch(d1, d2, k=2) if m.distance < 0.75 * n.distance]
    if len(good) < min_matches:
        raise RuntimeError(f"block registration: only {len(good)} SIFT matches")

    src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                         ransacReprojThreshold=3.0,
                                         maxIters=20000, confidence=0.999)
    if M is None:
        raise RuntimeError("block registration: RANSAC failed to fit a model")

    Mh = np.vstack([M, [0, 0, 1]])
    full = np.diag([1 / df, 1 / df, 1.0]) @ Mh @ np.diag([sf, sf, 1.0])
    scale = np.hypot(full[0, 0], full[0, 1])
    if not np.isfinite(scale) or scale < 1e-6:
        raise RuntimeError(f"block registration: degenerate transform (scale {scale})")
    return full, int(inl.sum()), len(good)


def _zncc(a, b):
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


def zncc_score(block_gray, frame_gray, transform, dxf=0.0, dyf=0.0):
    """ZNCC between block_gray and the reference frame sampled via `transform`,
    optionally shifted by (dxf, dyf) pixels in FRAME space (i.e. the shift is
    applied in the reference's own coordinate system, so a 1-pitch shift
    means the same physical distance regardless of the block photo's scale).

    `transform` maps block coords -> frame coords (forward). Returns None if
    the shifted footprint falls mostly outside the reference frame.
    """
    h, w = block_gray.shape
    shift = np.array([[1, 0, dxf], [0, 1, dyf], [0, 0, 1]], dtype=np.float64)
    full = shift @ transform
    full_inv = np.linalg.inv(full)
    warped = cv2.warpAffine(frame_gray, full_inv[:2], (w, h), flags=cv2.INTER_LINEAR)
    valid = warped > 0
    if valid.sum() < 0.5 * h * w:
        return None
    return _zncc(block_gray[valid], warped[valid])


def register_block(image_path, rebuild_reference=False):
    """Register a photo of an assembled block against the puzzle reference.

    Returns a dict: transform (block->frame, 3x3), inliers, matches,
    zncc_fit, and zncc_offsets (dict of 8 compass-direction 1-pitch checks +
    a far control), so the caller can judge whether this is a sharp,
    unambiguous lock (Session 10's bar: fit ~0.75, one-pitch-away <0.4,
    negative several pitches out) or a false one (T04: 0.3-0.46 everywhere).
    """
    block = np.asarray(Image.open(image_path).convert("RGB"))
    block_gray = cv2.cvtColor(block, cv2.COLOR_RGB2GRAY)

    frame = reference.puzzle_frame(rebuild=rebuild_reference)
    frame_gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

    transform, inliers, matches = _sift_affine(block_gray, frame_gray)
    pitch = reference.px_per_pitch(frame)

    zncc_fit = zncc_score(block_gray, frame_gray, transform)
    offsets = {}
    for name, (ddx, ddy) in {
        "+pitch_x": (pitch, 0), "-pitch_x": (-pitch, 0),
        "+pitch_y": (0, pitch), "-pitch_y": (0, -pitch),
        "+3pitch_x": (3 * pitch, 0), "-3pitch_x": (-3 * pitch, 0),
        "+3pitch_y": (0, 3 * pitch), "-3pitch_y": (0, -3 * pitch),
    }.items():
        offsets[name] = zncc_score(block_gray, frame_gray, transform, ddx, ddy)

    return dict(transform=transform, inliers=inliers, matches=matches,
                pitch_px=pitch, zncc_fit=zncc_fit, zncc_offsets=offsets)


def block_to_frame_xy(transform, x, y):
    """Map a point (x, y) in the block photo to (x, y) in the reference frame."""
    p = transform @ np.array([x, y, 1.0])
    return float(p[0]), float(p[1])


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image_path")
    ap.add_argument("--rebuild-reference", action="store_true")
    args = ap.parse_args()

    r = register_block(args.image_path, rebuild_reference=args.rebuild_reference)
    sc = np.hypot(r["transform"][0, 0], r["transform"][0, 1])
    rot = np.degrees(np.arctan2(r["transform"][0, 1], r["transform"][0, 0]))
    print(f"{r['inliers']}/{r['matches']} inliers, scale {sc:.4f}, rot {rot:.2f} deg, "
          f"pitch {r['pitch_px']:.1f} px (frame space)")
    print(f"ZNCC at fit: {r['zncc_fit']:.3f}")
    for name, v in r["zncc_offsets"].items():
        print(f"  {name:>10s}: {v if v is None else round(v, 3)}")
