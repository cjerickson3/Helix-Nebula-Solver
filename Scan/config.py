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
FIDUCIAL_AREA_MIN = 1_200
FIDUCIAL_AREA_MAX = 9_000
FIDUCIAL_ASPECT_TOL = 0.35    # |w/h - 1| must be under this
FIDUCIAL_DARK_LEVEL = 150     # fiducials are solid black on magenta

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

# ---------------------------------------------------------------- layout
# Acrylic placement jig: 5 columns x 6 rows, 33mm holes on 39mm pitch
GRID_COLS = 5
GRID_ROWS = 6
PIECES_PER_SHEET = GRID_COLS * GRID_ROWS
