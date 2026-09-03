"""Remove the printed-linen weave from a piece face.

The puzzle stock has a regular linen finish. On a 600 dpi scan it is a strong,
high-frequency, *globally identical* texture that dominates every appearance
comparison (NCC locks onto the weave, not the image). Because it is periodic it
sits in a sparse lattice of sharp peaks in the Fourier magnitude, well away from
the low-frequency image content -- so a notch filter removes it cleanly.

See CLAUDE.md, Session 9: de-weaving exposes real nebula mottle and faint stars
that were buried, though on the featureless teal interior what remains is still
too weak to localise. It matters most for the star-bearing pieces.
"""
from __future__ import annotations
import numpy as np
import cv2

# fraction of the half-diagonal to protect around DC as "image content"
_PROTECT_FRAC = 0.05
# percentile of the (log) spectrum, outside the protected disc, above which a
# bin is treated as a weave harmonic
_PEAK_PCTILE = 99.6
_PEAK_DILATE = 5


def deweave(gray: np.ndarray) -> np.ndarray:
    """Notch the periodic weave out of a single-channel image.

    Returns a float32 array, same shape, not normalised (caller decides).
    """
    g = gray.astype(np.float32)
    F = np.fft.fftshift(np.fft.fft2(g))
    mag = np.log(np.abs(F) + 1.0)

    h, w = g.shape
    cy, cx = h // 2, w // 2
    yy, xx = np.ogrid[:h, :w]
    rad = np.hypot(yy - cy, xx - cx)
    protect = rad < max(h, w) * _PROTECT_FRAC

    scan = mag.copy()
    scan[protect] = 0.0
    thr = np.percentile(scan[scan > 0], _PEAK_PCTILE)
    peaks = cv2.dilate((scan > thr).astype(np.uint8),
                       np.ones((_PEAK_DILATE, _PEAK_DILATE), np.uint8)) > 0

    keep = np.ones_like(g)
    keep[peaks & ~protect] = 0.0
    out = np.real(np.fft.ifft2(np.fft.ifftshift(F * keep)))
    return out.astype(np.float32)


def deweaved_u8(gray: np.ndarray) -> np.ndarray:
    """`deweave` then min-max stretch to uint8, for display or NCC."""
    out = deweave(gray)
    return cv2.normalize(out, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
