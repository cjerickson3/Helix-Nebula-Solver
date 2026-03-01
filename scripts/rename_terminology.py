"""
Safe rename of HEAD→TAB, HOLE→BLANK throughout the Helix Nebula Solver codebase.
Run from the Solver/ directory root.
Reports all changes before making them — review output carefully.
"""
import os
import re
from pathlib import Path

# Files to process
TARGET_FILES = [
    "src/Puzzle/Enums.py",
    "src/Puzzle/Edge.py",
    "src/Puzzle/PuzzlePiece.py",
    "src/Puzzle/Puzzle.py",
    "src/Puzzle/Distance.py",
    "src/Img/filters.py",
]

# Ordered replacements — order matters to avoid double-replacing
REPLACEMENTS = [
    # Enum values and type references
    ("TypeEdge.HEAD",       "TypeEdge.TAB"),
    ("TypeEdge.HOLE",       "TypeEdge.BLANK"),
    # String literals
    ('"HEAD"',              '"TAB"'),
    ('"HOLE"',              '"BLANK"'),
    ("'HEAD'",              "'TAB'"),
    ("'HOLE'",              "'BLANK'"),
    # Enum definitions
    ("HEAD = ",             "TAB = "),
    ("HOLE = ",             "BLANK = "),
    # Attribute names
    ("n_heads",             "n_tabs"),
    ("n_holes",             "n_blanks"),
    ("number_of_heads",     "number_of_tabs"),
    ("number_of_holes",     "number_of_blanks"),
    # Comments and strings that say HEAD/HOLE
    ("# HEAD",              "# TAB"),
    ("# HOLE",              "# BLANK"),
    ("HOLE/HEAD",           "BLANK/TAB"),
    ("HEAD/HOLE",           "TAB/BLANK"),
]

def process_file(filepath, dry_run=True):
    path = Path(filepath)
    if not path.exists():
        print(f"  SKIP (not found): {filepath}")
        return 0

    content = original = path.read_text(encoding="utf-8")
    changes = []

    for old, new in REPLACEMENTS:
        if old in content:
            count = content.count(old)
            content = content.replace(old, new)
            changes.append((old, new, count))

    if changes:
        print(f"\n  {filepath}:")
        for old, new, count in changes:
            print(f"    {old!r:30s} → {new!r}  ({count}x)")
        if not dry_run:
            path.write_text(content, encoding="utf-8")
    else:
        print(f"  (no changes): {filepath}")

    return len(changes)

print("=" * 60)
print("DRY RUN — no files will be modified")
print("=" * 60)
total = sum(process_file(f, dry_run=True) for f in TARGET_FILES)
print(f"\nTotal files with changes: {total}")
print("\nRun with --apply to make changes.")

import sys
if "--apply" in sys.argv:
    print("\n" + "=" * 60)
    print("APPLYING CHANGES")
    print("=" * 60)
    total = sum(process_file(f, dry_run=False) for f in TARGET_FILES)
    print(f"\nDone. {total} files modified.")