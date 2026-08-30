"""
Configuration constants for the Helix Nebula scanning pipeline.

Every value here was measured from real scans in Session 6 -- see CLAUDE.md
"Scanning Pipeline -- Measured Constants" for provenance. Do not guess new
values; re-measure and update both places together.
"""

# ---------------------------------------------------------------- capture
DPI = 600                     # 1200 does not help: the shadow is physical, not sampling-limited
MM_PER_INCH = 25.4

# ---------------------------------------------------------------- thresholding
# Threshold is expressed as a FRACTION of the measured backing level, never as an
# absolute. Absolute 95 against a backing of 167 gave the validated results; storing
# the ratio means the pipeline survives a new batch of card stock or lamp ageing.
THRESHOLD_RATIO = 95.0 / 167.0        # ~0.569
THRESHOLD_FALLBACK = 95               # used only if backing detection fails

# Backing must be found above this level, pieces below it, when scanning the
# red channel of magenta card.
BACKING_MIN_LEVEL = 120

# ---------------------------------------------------------------- geometry
# Scanner x/y scale anisotropy, from the square target scanned at 0 and 90 degrees.
# Two independent estimates agreed to 0.04%. Multiply y by this to match x.
ANISOTROPY_SY = 0.99772

# ---------------------------------------------------------------- piece filtering
# Measured piece areas ran 186k-242k px at 600 dpi; the largest non-piece contour
# was ~315 px. These bounds are deliberately wide -- the real gap is 3 orders of
# magnitude, so precision here is not needed.
PIECE_AREA_MIN = 50_000
PIECE_AREA_MAX = 400_000
MERGE_AREA_FACTOR = 1.6       # area > this * median  =>  two pieces touching

# ---------------------------------------------------------------- fiducials
# Near-black dots on the red backing, detected on the RED channel with the same
# ratio threshold as the pieces (luminance greyscale of red card is ~95 and
# floods a fixed grey threshold). Corner dots print at 5.5 mm (~12,900 px at
# 600 dpi); smaller orientation markers at ~3.3 mm (~4,900 px). The band spans
# both; area still separates any fiducial from a piece (~210,000 px) by 15:1+.
FIDUCIAL_AREA_MIN = 2_000
FIDUCIAL_AREA_MAX = 25_000
FIDUCIAL_ASPECT_TOL = 0.35    # |w/h - 1| must be under this
FIDUCIAL_FILL_MIN = 0.55      # area / bbox area; a disc fills ~0.79, thin marks far less
FIDUCIAL_MORPH = 9            # ellipse kernel (px) to open/close the fiducial mask
FIDUCIAL_SIZE_SPLIT = 0.35    # split corner vs marker dots when the largest area
                             # gap exceeds this * mean area; else treat all as corners

# ---------------------------------------------------------------- contour processing
CONTOUR_SAMPLES = 512         # resample whole-piece contours to this many points
EDGE_SAMPLES = 128            # resample each of the 4 edges to this many points
SMOOTH_SIGMA = 6.0            # Gaussian sigma along the contour, in samples
                              # 6 was near-optimal: perimeter agreement bottomed at
                              # 0.54% around sigma 8, and 6 keeps corner detail

# ---------------------------------------------------------------- morphology
MORPH_KERNEL = 5

# ---------------------------------------------------------------- edge classification
# Deviation of an edge from its corner-to-corner chord, as a fraction of chord length.
BORDER_MAX_DEVIATION = 0.04   # flatter than this => BORDER
TAB_MIN_DEVIATION = 0.08      # bulges outward more than this => TAB (inward => BLANK)

# Corner-spacing coefficient of variation (see geometry.corner_spacing_cv) above
# which a piece's topology is flagged as unreliable. Clean pieces measure < 0.10
# on the P01 sheet; the corner-detection failures there sat at 0.20-0.43.
CORNER_DEV_WARN = 0.15

# ---------------------------------------------------------------- layout
# Acrylic placement jig: 5 columns x 6 rows, 33mm holes on 39mm pitch
GRID_COLS = 5
GRID_ROWS = 6
PIECES_PER_SHEET = GRID_COLS * GRID_ROWS
