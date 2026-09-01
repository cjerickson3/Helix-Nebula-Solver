"""Helix Nebula puzzle solver -- scanning and extraction pipeline."""
from . import config, scan, geometry, db  # noqa: F401
# `pipeline` is intentionally not eagerly imported here: it is the -m entry point,
# and pre-importing it makes `python -m Scan.pipeline` emit a RuntimeWarning.
