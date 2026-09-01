"""
Generate Glowforge-ready SVG for 3x3 puzzle piece photography jig.
- 9 cells, 3.8cm each, arranged in a 3x3 grid
- 5mm border/margin around the grid
- 3mm dividers between cells (so pieces are well separated)
- Red lines = cut (cell openings)
- Blue text = engrave (cell labels A1-C3)
- Outer border = cut (the jig outline itself)
"""

# All measurements in mm
CELL_SIZE = 38.0          # 3.8cm per cell
DIVIDER = 3.0             # 3mm walls between cells
MARGIN = 8.0              # 8mm border around entire grid
COLS = 3
ROWS = 3

# Derived
grid_w = COLS * CELL_SIZE + (COLS - 1) * DIVIDER
grid_h = ROWS * CELL_SIZE + (ROWS - 1) * DIVIDER
total_w = grid_w + 2 * MARGIN
total_h = grid_h + 2 * MARGIN

# Glowforge colors
CUT_COLOR = "#FF0000"
ENGRAVE_COLOR = "#0000FF"
OUTER_COLOR = "#FF0000"

# Font size for labels
FONT_SIZE = 8  # mm

def cell_origin(col, row):
    """Top-left corner of cell opening (inside the walls)."""
    x = MARGIN + col * (CELL_SIZE + DIVIDER)
    y = MARGIN + row * (CELL_SIZE + DIVIDER)
    return x, y

def rect(x, y, w, h, color, stroke_width=0.2, fill="none"):
    return (f'<rect x="{x:.3f}" y="{y:.3f}" '
            f'width="{w:.3f}" height="{h:.3f}" '
            f'fill="{fill}" stroke="{color}" stroke-width="{stroke_width}"/>')

def text(x, y, label, color, size):
    return (f'<text x="{x:.3f}" y="{y:.3f}" '
            f'font-family="Arial" font-size="{size}" '
            f'fill="{color}" text-anchor="middle" '
            f'dominant-baseline="middle">{label}</text>')

lines = []
lines.append(f'<?xml version="1.0" encoding="UTF-8"?>')
lines.append(
    f'<svg xmlns="http://www.w3.org/2000/svg" '
    f'width="{total_w}mm" height="{total_h}mm" '
    f'viewBox="0 0 {total_w:.3f} {total_h:.3f}">'
)
lines.append(f'<!-- Helix Nebula Puzzle Photography Jig -->')
lines.append(f'<!-- Cell size: {CELL_SIZE}mm, Grid: {COLS}x{ROWS}, Total: {total_w:.1f}x{total_h:.1f}mm -->')
lines.append(f'<!-- RED = cut through, BLUE = engrave/score -->')
lines.append("")

# Outer jig boundary (cut)
lines.append(f'<!-- Outer boundary -->')
lines.append(rect(0, 0, total_w, total_h, OUTER_COLOR, stroke_width=0.2))
lines.append("")

# Cell openings (cut) and labels (engrave)
col_letters = ['A', 'B', 'C']
lines.append(f'<!-- Cell openings (cut) and labels (engrave) -->')
for row in range(ROWS):
    for col in range(COLS):
        x, y = cell_origin(col, row)
        label = f"{col_letters[col]}{row + 1}"
        
        # Cut rectangle for cell opening
        lines.append(f'<!-- Cell {label} -->')
        lines.append(rect(x, y, CELL_SIZE, CELL_SIZE, CUT_COLOR, stroke_width=0.2))
        
        # Label centered in cell - engrave
        cx = x + CELL_SIZE / 2
        cy = y + CELL_SIZE / 2
        lines.append(text(cx, cy, label, ENGRAVE_COLOR, FONT_SIZE))
        lines.append("")

lines.append('</svg>')

svg_content = '\n'.join(lines)
with open('/home/claude/helix_jig.svg', 'w') as f:
    f.write(svg_content)

print(f"SVG written: {total_w:.1f} x {total_h:.1f} mm")
print(f"Grid: {grid_w:.1f} x {grid_h:.1f} mm")
print(f"Cell size: {CELL_SIZE}mm ({CELL_SIZE/25.4*1:.2f}\")")
print(f"Total jig: {total_w/25.4:.2f}\" x {total_h/25.4:.2f}\"")
