"""
SQLite schema and loader for scanned pieces.

Deliberately leaner than the multi-track astrometry schema in CLAUDE.md. That
design was built around star positions; this one is built around geometry, which
is the critical path. The astrometry tables can be layered back on later without
disturbing anything here.
"""
from __future__ import annotations
import sqlite3
import numpy as np

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sheets (
    sheet_id        INTEGER PRIMARY KEY,
    page_label      TEXT NOT NULL UNIQUE,   -- e.g. "07a"
    scan_a_path     TEXT NOT NULL,          -- 0 degree pass
    scan_b_path     TEXT,                   -- 180 degree pass, NULL if single-pass
    threshold_level INTEGER,
    backing_level   INTEGER,
    n_pieces        INTEGER,
    fiducials_found INTEGER DEFAULT 0,
    mean_residual   REAL,                   -- px, mean dual-pass boundary agreement
    scanned_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pieces (
    piece_id        INTEGER PRIMARY KEY,
    sheet_id        INTEGER NOT NULL REFERENCES sheets(sheet_id),
    piece_label     TEXT NOT NULL UNIQUE,   -- e.g. "07a-C3"
    grid_col        INTEGER,
    grid_row        INTEGER,

    -- topology. Interior pieces have no determinable orientation, so the edge
    -- sequence is CYCLIC: store it in contour order and compare all rotations.
    n_tabs          INTEGER,
    n_blanks        INTEGER,
    n_borders       INTEGER,
    edge_sequence   TEXT,                   -- "TAB|BLANK|TAB|BORDER", contour order
    cyclic_key      TEXT,                   -- canonical rotation, for indexing

    -- geometry, in anisotropy-corrected pixels at 600 dpi
    area_px         REAL,
    perimeter_px    REAL,
    width_mm        REAL,
    height_mm       REAL,
    residual_px     REAL,                   -- dual-pass agreement for this piece
    corner_dev      REAL,                   -- arc-length CV of the 4 corners;
                                            -- >~0.15 => topology fields unreliable

    -- appearance
    colour_class    TEXT,                   -- 'teal' | 'dark' | 'other'
    mean_l          REAL,
    mean_a          REAL,
    mean_b          REAL,

    contour         BLOB,                   -- float32 (N,2), averaged contour

    -- placement, filled in by the solver
    placed_col      INTEGER,
    placed_row      INTEGER,
    placed_rotation INTEGER,
    confidence      REAL,
    placement_method TEXT
);

CREATE TABLE IF NOT EXISTS edges (
    edge_id         INTEGER PRIMARY KEY,
    piece_id        INTEGER NOT NULL REFERENCES pieces(piece_id),
    edge_index      INTEGER NOT NULL,       -- 0-3 in contour order, NOT compass
    edge_type       TEXT,                   -- TAB | BLANK | BORDER
    deviation       REAL,                   -- signed, normalised by chord length
    chord_px        REAL,
    curve           BLOB,                   -- float32 (EDGE_SAMPLES,2), normalised
    UNIQUE (piece_id, edge_index)
);

CREATE INDEX IF NOT EXISTS idx_pieces_cyclic  ON pieces(cyclic_key);
CREATE INDEX IF NOT EXISTS idx_pieces_colour  ON pieces(colour_class);
CREATE INDEX IF NOT EXISTS idx_pieces_sheet   ON pieces(sheet_id);
CREATE INDEX IF NOT EXISTS idx_edges_type     ON edges(edge_type);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def pack(points: np.ndarray) -> bytes:
    return np.ascontiguousarray(points, dtype=np.float32).tobytes()


def unpack(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).reshape(-1, 2)


def insert_sheet(conn, page_label, scan_a, scan_b, diag, residual, fiducials_found):
    cur = conn.execute(
        """INSERT OR REPLACE INTO sheets
           (page_label, scan_a_path, scan_b_path, threshold_level, backing_level,
            n_pieces, fiducials_found, mean_residual)
           VALUES (?,?,?,?,?,?,?,?)""",
        (page_label, str(scan_a), str(scan_b) if scan_b else None,
         diag.get("threshold"), diag.get("backing"), diag.get("n_pieces"),
         int(fiducials_found), residual))
    return cur.lastrowid


def insert_piece(conn, sheet_id, record):
    cur = conn.execute(
        """INSERT OR REPLACE INTO pieces
           (sheet_id, piece_label, grid_col, grid_row,
            n_tabs, n_blanks, n_borders, edge_sequence, cyclic_key,
            area_px, perimeter_px, width_mm, height_mm, residual_px, corner_dev,
            colour_class, mean_l, mean_a, mean_b, contour)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sheet_id, record["piece_label"], record["grid_col"], record["grid_row"],
         record["n_tabs"], record["n_blanks"], record["n_borders"],
         record["edge_sequence"], record["cyclic_key"],
         record["area_px"], record["perimeter_px"],
         record["width_mm"], record["height_mm"], record["residual_px"],
         record["corner_dev"],
         record["colour_class"], record["mean_l"], record["mean_a"], record["mean_b"],
         pack(record["contour"])))
    piece_id = cur.lastrowid
    for e in record["edges"]:
        conn.execute(
            """INSERT OR REPLACE INTO edges
               (piece_id, edge_index, edge_type, deviation, chord_px, curve)
               VALUES (?,?,?,?,?,?)""",
            (piece_id, e["index"], e["type"], e["deviation"], e["chord_px"],
             pack(e["curve"])))
    return piece_id
