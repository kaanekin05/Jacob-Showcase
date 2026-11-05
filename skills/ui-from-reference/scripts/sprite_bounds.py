#!/usr/bin/env python3
"""Measure a sprite's opaque art and print the rect that lands it on a design number.

A rect set to the design number renders the art undersized and off-centre, because every
exported sprite carries transparent margin from antialiasing and baked drop shadows. This
prints the corrected rect and the offset to apply, so the opaque art lands where the mock
puts it.

Which formula applies depends on the Image type, so say which you are authoring:

  --sliced   a panel that stretches, with its pad inside the fixed corner border.
             The pad is CONSTANT at any rect size, so it is added per axis.
  (default)  a Simple image that scales whole, so the pad scales with it and the
             art keeps its own aspect.

Usage:
    sprite_bounds.py PILL.png  --target-w 174.9 --target-h 101.2 --sliced
    sprite_bounds.py ICON.png  --target-w 70.2  --target-h 63.2
    sprite_bounds.py A.png B.png --swap          # compare a swap pair by alpha centroid
    sprite_bounds.py SPRITE.png --border         # 9-slice border from the corner radius

Needs Pillow.
"""

import argparse
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required:  pip install Pillow")

# Opaque enough to be art rather than antialiasing. 128 tracks the visible silhouette;
# a higher value trims soft shadows, which is what --alpha is for.
DEFAULT_ALPHA = 128


def load(path):
    return Image.open(path).convert("RGBA")


def opaque_bbox(im, threshold):
    """Bounding box of pixels at or above the alpha threshold, as (x0, y0, x1, y1)."""
    w, h = im.size
    px = im.load()
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            if px[x, y][3] >= threshold:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def alpha_centroid(im):
    """Alpha-weighted centre. This is what the eye tracks, not the bounding box."""
    w, h = im.size
    px = im.load()
    sx = sy = sa = 0.0
    for y in range(h):
        for x in range(w):
            a = px[x, y][3]
            if a:
                sx += x * a
                sy += y * a
                sa += a
    if sa == 0:
        return None
    return sx / sa, sy / sa


def corner_border(im, threshold):
    """Where each edge's corner curve ends, which plus the pad is the 9-slice border."""
    w, h = im.size
    px = im.load()
    rows, cols = [], []
    for y in range(h):
        xs = [x for x in range(w) if px[x, y][3] >= threshold]
        rows.append((y, (xs[0], xs[-1]) if xs else None))
    for x in range(w):
        ys = [y for y in range(h) if px[x, y][3] >= threshold]
        cols.append((x, (ys[0], ys[-1]) if ys else None))
    spans = [r[1] - r[0] for _, r in rows if r]
    vspans = [c[1] - c[0] for _, c in cols if c]
    if not spans or not vspans:
        return None
    mx, my = max(spans), max(vspans)
    top = next(y for y, r in rows if r and r[1] - r[0] == mx)
    bottom = h - 1 - next(y for y, r in reversed(rows) if r and r[1] - r[0] == mx)
    left = next(x for x, c in cols if c and c[1] - c[0] == my)
    right = w - 1 - next(x for x, c in reversed(cols) if c and c[1] - c[0] == my)
    return left, bottom, right, top


def report_one(path, target_w, target_h, threshold, sliced):
    im = load(path)
    w, h = im.size
    box = opaque_bbox(im, threshold)
    if box is None:
        print(f"{path}: fully transparent at alpha >= {threshold}")
        return
    x0, y0, x1, y1 = box
    aw, ah = x1 - x0 + 1, y1 - y0 + 1

    print(f"{path}")
    print(f"  sprite        {w} x {h}")
    print(f"  opaque art    {aw} x {ah}   at ({x0}, {y0})")
    print(f"  padding       L{x0}  R{w - 1 - x1}  T{y0}  B{h - 1 - y1}")

    cen = alpha_centroid(im)
    if cen:
        print(f"  alpha centroid ({cen[0]:.1f}, {cen[1]:.1f})"
              f"   bbox centre ({(x0 + x1) / 2:.1f}, {(y0 + y1) / 2:.1f})"
              f"   sprite centre ({(w - 1) / 2:.1f}, {(h - 1) / 2:.1f})")

    if target_w is None:
        return

    if sliced:
        # Sliced with the pad inside the corner border: the pad does not scale, so the
        # rect is the design number plus the pad. The panel is MEANT to stretch here —
        # aspect-fitting it would shrink a pill that should be wide.
        pad_l, pad_r, pad_t, pad_b = x0, w - 1 - x1, y0, h - 1 - y1
        rect_w = target_w + pad_l + pad_r
        rect_h = (target_h + pad_t + pad_b) if target_h is not None else None
        # The rect moves OPPOSITE the art's offset inside it. A bottom-heavy pad leaves the
        # art above the rect centre, so the rect drops: negative in Unity, where y is up.
        off_x = (pad_r - pad_l) / 2.0
        off_y = -(pad_b - pad_t) / 2.0
        if rect_h is None:
            print(f"  -> rect       {rect_w:.1f} x (pass --target-h)")
            print(f"  -> offset     ({off_x:+.1f}, n/a)")
        else:
            print(f"  -> rect       {rect_w:.1f} x {rect_h:.1f}   [sliced: pad added, not scaled]")
            print(f"  -> offset     ({off_x:+.1f}, {off_y:+.1f})   add to the design centre")
        return

    # Simple: the whole quad scales. Fit by the smaller scale when both targets are given,
    # so the art keeps its own aspect and cannot overflow the slot. Mock slots and art
    # aspects rarely agree.
    sx = target_w / aw
    if target_h is None:
        s = sx
        note = "scaled by width"
    else:
        sy = target_h / ah
        s = min(sx, sy)
        note = "scaled by width" if s == sx else "scaled by height"
        if abs(sx - sy) / max(sx, sy) > 0.02:
            print(f"  NOTE  art aspect {aw / ah:.3f} vs slot aspect {target_w / target_h:.3f}"
                  f" — {note}, so the art keeps its proportions")

    rect_w, rect_h = w * s, h * s
    # The rect moves opposite to the art's offset inside its own sprite.
    off_x = -((x0 + x1) / 2 - (w - 1) / 2) * s
    off_y = ((y0 + y1) / 2 - (h - 1) / 2) * s   # Unity y is up, image y is down

    print(f"  -> rect       {rect_w:.1f} x {rect_h:.1f}   [simple: pad scales with the art]")
    print(f"  -> offset     ({off_x:+.1f}, {off_y:+.1f})   add to the design centre")


def report_swap(path_a, path_b, target_h, threshold):
    """Two sprites sharing one slot. A matching bbox does not mean a matching position."""
    ia, ib = load(path_a), load(path_b)
    if ia.size != ib.size:
        print(f"WARNING sprites differ in size: {ia.size} vs {ib.size}")
    ca, cb = alpha_centroid(ia), alpha_centroid(ib)
    ba, bb = opaque_bbox(ia, threshold), opaque_bbox(ib, threshold)

    print(f"A {path_a}  centroid ({ca[0]:.1f}, {ca[1]:.1f})  bbox {ba}")
    print(f"B {path_b}  centroid ({cb[0]:.1f}, {cb[1]:.1f})  bbox {bb}")
    dx_px, dy_px = cb[0] - ca[0], cb[1] - ca[1]
    print(f"  centroid drift  ({dx_px:+.1f}, {dy_px:+.1f}) sprite px")

    bcx_a, bcy_a = (ba[0] + ba[2]) / 2, (ba[1] + ba[3]) / 2
    bcx_b, bcy_b = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    print(f"  bbox drift      ({bcx_b - bcx_a:+.1f}, {bcy_b - bcy_a:+.1f}) sprite px"
          f"   <- agreeing here does NOT mean they line up")

    if target_h:
        s = target_h / ia.size[1]
        print(f"  at rect height {target_h}: offset B by "
              f"({-dx_px * s:+.2f}, {dy_px * s:+.2f}) units while B is shown")
    else:
        print("  pass --target-h <rect height in units> for the offset to apply")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sprites", nargs="+")
    ap.add_argument("--target-w", type=float, help="design width of the OPAQUE art, in units")
    ap.add_argument("--target-h", type=float, help="design height of the OPAQUE art, in units")
    ap.add_argument("--sliced", action="store_true",
                    help="the sprite is 9-sliced with its pad inside the corner border, "
                         "so the pad is constant and gets added rather than scaled")
    ap.add_argument("--swap", action="store_true", help="compare two sprites sharing one slot")
    ap.add_argument("--border", action="store_true", help="suggest a 9-slice border")
    ap.add_argument("--alpha", type=int, default=DEFAULT_ALPHA,
                    help=f"alpha threshold for 'opaque' (default {DEFAULT_ALPHA})")
    args = ap.parse_args()

    if args.swap:
        if len(args.sprites) != 2:
            sys.exit("--swap needs exactly two sprites")
        report_swap(args.sprites[0], args.sprites[1], args.target_h, args.alpha)
        return

    for i, path in enumerate(args.sprites):
        if i:
            print()
        report_one(path, args.target_w, args.target_h, args.alpha, args.sliced)
        if args.border:
            b = corner_border(load(path), args.alpha)
            if b:
                l, bo, r, t = b
                print(f"  -> 9-slice border  L{l + 2}  B{bo + 2}  R{r + 2}  T{t + 2}"
                      f"   (curve ends L{l} B{bo} R{r} T{t}, +2 margin)")
                print("     check an authored border exists first — do not overwrite one")


if __name__ == "__main__":
    main()
