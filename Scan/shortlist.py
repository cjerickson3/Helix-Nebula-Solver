"""Candidate-position shortlisting against the reference image.

Not a solver. For a piece you are holding, this ranks the ~15 most plausible
spots in the Spitzer reference and shows them as image crops, so you can make
the final placement by eye using distinctive features (a particular star, a
filament, a colour edge). Session 9 established that autonomous appearance
matching does not place the teal pieces -- six methods failed -- but the human
is fast at it given a short list. This produces the short list.

    python -m Scan.shortlist SCAN.png [--k 15] [--zone x0,y0,x1,y1]
                             [--piece p03] [--out DIR]

SCAN is one flatbed pass of a sheet (a/b both fine; the weave is removed either
way). Pieces are labelled p01, p02, ... in reading order. One PNG per piece is
written to --out (default: ./shortlist/), each a strip: the piece face followed
by the top-k reference crops, rotated to match, labelled with rank / NCC / (x,y).
--zone restricts the search to a rectangle of the reference frame (much faster
and far fewer false peaks) -- get coordinates from resources/reference_puzzle_frame.png.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import numpy as np
import cv2
from PIL import Image

from . import scan, reference
from .deweave import deweave

Image.MAX_IMAGE_PIXELS = None

FACE_PITCH_RATIO = 1.40      # a piece bbox (with tabs) is ~1.4 x the body pitch
HP_SIGMA = 35               # reference / face high-pass, in reference px
COLOUR_GATE = 26.0          # max LAB a/b distance (L dropped) piece vs patch; lenient
MIN_SEP_PITCH = 0.55        # NMS separation between kept candidates


def piece_faces(scan_path):
    """Extract every piece from one scan: face RGB, eroded mask, centroid, LAB, id.

    Pieces are labelled p01, p02, ... in reading order (top-to-bottom rows, then
    left-to-right). This is a shortlisting aid, not a solver -- it does not need
    the sheet's real grid, and `pipeline.assign_grid`'s clustering is unreliable
    on a handful of loose pieces.
    """
    img = scan.load_scan(scan_path)
    pieces, _ = scan.extract_pieces(img)
    if not pieces:
        return []
    med_h = np.median([cv2.boundingRect(p.contour.astype(np.int32))[3] for p in pieces])
    order = sorted(range(len(pieces)),
                   key=lambda i: (round(pieces[i].centroid[1] / max(med_h, 1)),
                                  pieces[i].centroid[0]))
    out = []
    for rank, i in enumerate(order, 1):
        pc = pieces[i]
        x, y, w, h = cv2.boundingRect(pc.contour.astype(np.int32))
        m = np.zeros(img.shape[:2], np.uint8)
        cv2.drawContours(m, [pc.contour.astype(np.int32)], -1, 255, cv2.FILLED)
        m = cv2.erode(m, np.ones((21, 21), np.uint8))
        out.append(dict(
            cell=f"p{rank:02d}",
            face=img[y:y + h, x:x + w].copy(),
            mask=m[y:y + h, x:x + w].copy(),
            centroid=pc.centroid,
            mean_lab=np.asarray(pc.mean_lab, float),
        ))
    return out


def _prep_face(face_rgb, mask, scale):
    """De-weaved, high-passed, mean-filled grey face at reference scale."""
    fw = max(int(face_rgb.shape[1] * scale), 8)
    fh = max(int(face_rgb.shape[0] * scale), 8)
    g = cv2.cvtColor(cv2.resize(face_rgb, (fw, fh)), cv2.COLOR_RGB2GRAY)
    m = cv2.resize(mask, (fw, fh))
    dw = deweave(g)
    dw = dw - cv2.GaussianBlur(dw, (0, 0), HP_SIGMA)
    dw = cv2.normalize(dw, None, 0, 255, cv2.NORM_MINMAX)
    mb = m > 0
    if mb.sum() < 50:
        return None, None
    dw[~mb] = dw[mb].mean()
    return dw.astype(np.float32), mb.astype(np.uint8)


def _pick_peaks(resp, tmpl_wh, pitch, k):
    """Top-k (x_centre, y_centre, score) from a response map, greedy + NMS."""
    tw, th = tmpl_wh
    r = resp.copy()
    sep = int(pitch * MIN_SEP_PITCH)
    picks = []
    for _ in range(k):
        _, mx, _, ml = cv2.minMaxLoc(r)
        if mx < -1:
            break
        cx, cy = ml[0] + tw / 2, ml[1] + th / 2
        picks.append((cx, cy, float(mx)))
        x0, x1 = max(ml[0] - sep, 0), min(ml[0] + sep, r.shape[1])
        y0, y1 = max(ml[1] - sep, 0), min(ml[1] + sep, r.shape[0])
        r[y0:y1, x0:x1] = -9
    return picks


def _lab_of(patch_rgb):
    lab = cv2.cvtColor(patch_rgb, cv2.COLOR_RGB2LAB).reshape(-1, 3).mean(0)
    return lab  # OpenCV LAB 0-255, a/b offset by 128 -- matches scan.mean_lab


def shortlist(face_rgb, mask, mean_lab, frame_rgb, frame_gray, pitch,
              k=15, zone=None):
    """Ranked candidate positions for one piece face, in frame coords."""
    scale = pitch * FACE_PITCH_RATIO / max(face_rgb.shape[:2])
    gx0, gy0 = 0, 0
    search = frame_gray
    if zone:
        gx0, gy0, gx1, gy1 = zone
        search = frame_gray[gy0:gy1, gx0:gx1]

    cand = []
    for rot in range(4):
        g, m = _prep_face(np.rot90(face_rgb, rot), np.rot90(mask, rot), scale)
        if g is None or g.shape[0] >= search.shape[0] or g.shape[1] >= search.shape[1]:
            continue
        resp = cv2.matchTemplate(search, g, cv2.TM_CCOEFF_NORMED, mask=m)
        resp[~np.isfinite(resp)] = -9
        for cx, cy, sc in _pick_peaks(resp, g.shape[::-1], pitch, k):
            cand.append(dict(x=cx + gx0, y=cy + gy0, rot=rot, ncc=sc,
                             half=max(g.shape) / 2))

    # colour gate + final NMS across rotations
    a0, b0 = mean_lab[1], mean_lab[2]
    kept = []
    for c in sorted(cand, key=lambda d: -d["ncc"]):
        hx = int(pitch * FACE_PITCH_RATIO / 2)
        x0, x1 = int(c["x"]) - hx, int(c["x"]) + hx
        y0, y1 = int(c["y"]) - hx, int(c["y"]) + hx
        if x0 < 0 or y0 < 0 or x1 > frame_rgb.shape[1] or y1 > frame_rgb.shape[0]:
            continue
        la, lb = _lab_of(frame_rgb[y0:y1, x0:x1])[1:]
        if np.hypot(la - a0, lb - b0) > COLOUR_GATE:
            continue
        if any(np.hypot(c["x"] - q["x"], c["y"] - q["y"]) < pitch * MIN_SEP_PITCH
               for q in kept):
            continue
        c["lab_dist"] = float(np.hypot(la - a0, lb - b0))
        kept.append(c)
        if len(kept) >= k:
            break
    for i, c in enumerate(kept):
        c["rank"] = i + 1
    return kept


def render(face_rgb, frame_rgb, cands, pitch, out_path, cell="", face_mask=None):
    box = int(pitch * FACE_PITCH_RATIO * 1.15)
    tile = 260

    def fit(im):
        f = tile / max(im.shape[:2])
        r = cv2.resize(im, (int(im.shape[1] * f), int(im.shape[0] * f)))
        c = np.zeros((tile, tile, 3), np.uint8)
        c[:r.shape[0], :r.shape[1]] = r
        return c

    face_show = cv2.convertScaleAbs(face_rgb, alpha=2.3)
    if face_mask is not None:
        face_show[face_mask == 0] = 0
    strip = [fit(face_show)]
    for c in cands:
        x, y = int(c["x"]), int(c["y"])
        crop = frame_rgb[max(y - box, 0):y + box, max(x - box, 0):x + box]
        crop = np.rot90(crop, (-c["rot"]) % 4)
        t = fit(cv2.convertScaleAbs(crop, alpha=1.9, beta=5))
        cv2.putText(t, f'#{c["rank"]} {c["ncc"]:.2f}', (4, 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.putText(t, f'({x},{y}) r{c["rot"]}', (4, tile - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
        strip.append(t)
    grid = np.hstack(strip) if strip else np.zeros((tile, tile, 3), np.uint8)
    cv2.putText(grid, f'{cell}  |  face', (4, tile - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    Image.fromarray(grid).save(out_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan", help="one flatbed pass of a sheet")
    ap.add_argument("--k", type=int, default=15)
    ap.add_argument("--zone", help="restrict search: x0,y0,x1,y1 in reference-frame px")
    ap.add_argument("--piece", help="only this piece id, e.g. p03")
    ap.add_argument("--out", default="shortlist", help="output dir (default ./shortlist)")
    ap.add_argument("--rebuild-ref", action="store_true")
    args = ap.parse_args()

    frame = reference.puzzle_frame(rebuild=args.rebuild_ref)
    fg = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY).astype(np.float32)
    fg = fg - cv2.GaussianBlur(fg, (0, 0), HP_SIGMA)
    fg = cv2.normalize(fg, None, 0, 255, cv2.NORM_MINMAX).astype(np.float32)
    pitch = reference.px_per_pitch(frame)
    zone = tuple(int(v) for v in args.zone.split(",")) if args.zone else None

    out = Path(args.out)
    out.mkdir(exist_ok=True, parents=True)
    faces = piece_faces(args.scan)
    if args.piece:
        faces = [f for f in faces if f["cell"] == args.piece.lower()]

    print(f"reference {frame.shape[1]}x{frame.shape[0]}  ~{pitch:.0f} px/pitch  "
          f"{len(faces)} piece(s)" + (f"  zone {zone}" if zone else ""))
    for f in faces:
        cands = shortlist(f["face"], f["mask"], f["mean_lab"], frame, fg, pitch,
                          k=args.k, zone=zone)
        p = out / f'{f["cell"]}.png'
        render(f["face"], frame, cands, pitch, p, cell=f["cell"],
               face_mask=f["mask"])
        top = ", ".join(f'{c["ncc"]:.2f}@({int(c["x"])},{int(c["y"])})'
                        for c in cands[:5])
        print(f'  {f["cell"]:>4}: {len(cands):2d} candidates  top5 {top}  -> {p}')


if __name__ == "__main__":
    main()
