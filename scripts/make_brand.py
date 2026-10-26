"""Draw Irminsul's app icons and share preview: an original glowing-tree mark, no game art.

    uv run python scripts/make_brand.py        ->  web/static/icons/*.png

Everything is drawn here from shapes (Pillow only), so the output is ours to publish.
The wordmark uses Saira if it is installed, else Bahnschrift, else Pillow's own font.
"""

import contextlib
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "web" / "static" / "icons"
BG, BG_2, BG_HI = (10, 24, 17), (7, 18, 13), (24, 58, 40)
LEAF, GOLD, SAP = (169, 216, 110), (214, 178, 94), (127, 227, 210)
TEXT, MUTED = (233, 242, 224), (157, 180, 155)
SS = 4  # supersampling: draw big, shrink once


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))


def radial(size, inner, outer, center=(0.5, 0.5), radius=0.75):
    """A soft radial gradient, computed small and scaled up (it has no detail to lose)."""
    small = 128
    im = Image.new("RGB", (small, small))
    px = im.load()
    for y in range(small):
        for x in range(small):
            d = math.hypot(x / small - center[0], y / small - center[1]) / radius
            px[x, y] = mix(inner, outer, min(1.0, d) ** 1.4)
    return im.resize(size, Image.BICUBIC)


def tree(depth, seed=11):
    """The mark: a trunk that forks into a rounded crown, with glowing buds at the tips.

    Returns (branches, tips) in a unit box: x in [0, 1] left to right, y in [0, 1] top down.
    """
    rnd = random.Random(seed)
    branches, tips = [], []

    def grow(x, y, ang, length, width, d):
        x2, y2 = x + math.cos(ang) * length, y + math.sin(ang) * length
        branches.append(((x, y), (x2, y2), width, width * 0.7, d))
        if d >= depth:
            tips.append((x2, y2, d))
            return
        spread = 0.38 if d == 0 else 0.5
        for side in (-1, 1):
            jitter = (rnd.random() - 0.5) * 0.12
            grow(x2, y2, ang + side * spread + jitter, length * 0.74, width * 0.7, d + 1)

    grow(0.5, 0.88, -math.pi / 2, 0.27, 0.05, 0)
    # Two roots each side, curving out along the ground
    roots = []
    for side in (-1, 1):
        for reach, drop, w in ((0.24, 0.05, 0.03), (0.15, 0.08, 0.022)):
            bend = (0.5 + side * reach * 0.45, 0.88 + drop)
            roots.append(((0.5, 0.86), bend, (0.5 + side * reach, 0.89 + drop * 0.6), w))
    return branches, tips, roots


def stamp(draw, pts, w0, w1, col, scale):
    """A tapered stroke along a polyline, drawn as overlapping discs (round ends for free)."""
    total = sum(math.dist(a, b) for a, b in zip(pts, pts[1:], strict=False))
    n = max(2, round(total * scale / 1.5))
    for i in range(n + 1):
        t = i / n
        # walk the polyline to fraction t
        want, (x, y) = t * total, pts[0]
        for a, b in zip(pts, pts[1:], strict=False):
            seg = math.dist(a, b)
            if want <= seg or b is pts[-1]:
                f = 0 if seg == 0 else min(1.0, want / seg)
                x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                break
            want -= seg
        r = (w0 + (w1 - w0) * t) * scale / 2
        draw.ellipse((x * scale - r, y * scale - r, x * scale + r, y * scale + r), fill=col)


def quad(a, c, b, n=24):
    def at(t, i):
        return (1 - t) ** 2 * a[i] + 2 * (1 - t) * t * c[i] + t * t * b[i]

    return [(at(t, 0), at(t, 1)) for t in (i / n for i in range(n + 1))]


def draw_mark(canvas, box, depth=5, glow=True, buds=True, weight=1.0):
    """Paint the tree mark into `box` (x0, y0, x1, y1) of an RGBA canvas."""
    x0, y0, x1, y1 = box
    side = min(x1 - x0, y1 - y0)
    ox, oy = x0 + (x1 - x0 - side) / 2, y0 + (y1 - y0 - side) / 2

    def p(x, y):
        return ox + x * side, oy + y * side

    branches, tips, roots = tree(depth)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    # The crown's halo first, so the branches sit in light
    if glow:
        halo = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo)
        cx, cy = p(0.5, 0.42)
        r = side * 0.34
        hd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*LEAF, 70))
        halo = halo.filter(ImageFilter.GaussianBlur(side * 0.09))
        canvas.alpha_composite(halo)
    local = Image.new("RGBA", (round(side), round(side)), (0, 0, 0, 0))
    ld = ImageDraw.Draw(local)
    for a, c, b, w in roots:
        stamp(ld, quad(a, c, b), w * weight, w * weight * 0.25, (*mix(GOLD, LEAF, 0.15), 200), side)
    for a, b, w0, w1, dep in branches:
        col = mix(GOLD, LEAF, min(1.0, dep / max(1, depth - 1)))
        stamp(ld, [a, b], w0 * weight, w1 * weight, (*col, 255), side)
    layer.paste(local, (round(ox), round(oy)))
    if glow:
        bloom = layer.filter(ImageFilter.GaussianBlur(side * 0.025))
        canvas.alpha_composite(bloom)
    canvas.alpha_composite(layer)
    if buds:
        bud = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(bud)
        for i, (x, y, _) in enumerate(tips):
            cx, cy = p(x, y)
            r = side * (0.026 if i % 3 else 0.034)
            col = GOLD if i % 5 == 2 else SAP if i % 7 == 3 else LEAF
            bd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*col, 255))
        if glow:
            canvas.alpha_composite(bud.filter(ImageFilter.GaussianBlur(side * 0.03)))
        core = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        cd = ImageDraw.Draw(core)
        for i, (x, y, _) in enumerate(tips):
            cx, cy = p(x, y)
            r = side * (0.008 if i % 3 else 0.011)
            cd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(243, 255, 224, 235))
        canvas.alpha_composite(core)


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return m


def icon(px, *, maskable=False, rounded=True, depth=5):
    big = px * SS
    bg = radial((big, big), BG_HI, BG_2, center=(0.5, 0.4), radius=0.8).convert("RGBA")
    # Maskable icons may be cropped to a circle: keep the mark inside the middle 80%
    inset = big * (0.2 if maskable else 0.1 if px >= 48 else 0.04)
    # Tiny sizes (favicons) get thicker strokes so the shape survives the shrink
    box = (inset, inset, big - inset, big - inset)
    draw_mark(bg, box, depth=depth, glow=px >= 48, weight=1.0 if px >= 48 else 2.2)
    if rounded and not maskable:
        out = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        out.paste(bg, mask=rounded_mask((big, big), big * 0.22))
        bg = out
    return bg.resize((px, px), Image.LANCZOS)


def font(size, weight=300):
    for name in ("Saira-Regular.ttf", "Saira.ttf", "bahnschrift.ttf"):
        try:
            f = ImageFont.truetype(name, size)
        except OSError:
            continue
        with contextlib.suppress(OSError, ValueError):  # a static font has no axes
            f.set_variation_by_axes([weight] if name == "bahnschrift.ttf" else [100, weight])
        return f
    return ImageFont.load_default(size)


def spaced(draw, xy, text, f, tracking, fill):
    """Text with letter-spacing (Pillow has none), returns the drawn width."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + tracking
    return x - tracking - xy[0]


def text_width(draw, text, f, tracking):
    return sum(draw.textlength(ch, font=f) for ch in text) + tracking * (len(text) - 1)


def share_image():
    w, h = 1200 * 2, 630 * 2
    s = 2
    im = radial((w, h), (20, 48, 33), BG_2, center=(0.3, 0.55), radius=0.9).convert("RGBA")
    draw_mark(im, (90 * s, 70 * s, 560 * s, 560 * s), depth=6)
    d = ImageDraw.Draw(im)
    left = 590 * s
    word = font(84 * s, 300)
    # Gradient wordmark: draw it as a mask, fill it with text-to-leaf
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    word_w = spaced(md, (left, 200 * s), "IRMINSUL", word, 16 * s, 255)
    grad = Image.new("RGBA", (w, h))
    gd = ImageDraw.Draw(grad)
    top, bottom = 205 * s, 305 * s
    for y in range(h):
        t = min(1.0, max(0.0, (y - top) / (bottom - top)))
        gd.line((0, y, w, y), fill=(*mix(TEXT, mix(LEAF, GOLD, 0.3), t * t), 255))
    im.paste(grad, mask=mask)
    d.line((left, 340 * s, left + word_w, 340 * s), fill=(*GOLD, 80), width=s)
    tag = font(34 * s, 350)
    lines = ["Genshin answers from official", "game data, with sources. No leaks."]
    for i, line in enumerate(lines):
        d.text((left, (368 + i * 48) * s), line, font=tag, fill=TEXT)
    small = font(24 * s, 400)
    x = left
    for label in ("Free", "Cited", "Leak-free"):
        tw = d.textlength(label, font=small)
        box = (x, 500 * s, x + tw + 36 * s, 544 * s)
        d.rounded_rectangle(box, 22 * s, outline=(*LEAF, 120), width=2 * s)
        d.text((x + 18 * s, 506 * s), label, font=small, fill=LEAF)
        x = box[2] + 14 * s
    d.text((left, 576 * s), "Unofficial fan project", font=font(20 * s, 300), fill=MUTED)
    return im.resize((1200, 630), Image.LANCZOS).convert("RGB")


def flatten(im, color=BG):
    out = Image.new("RGB", im.size, color)
    out.paste(im, mask=im.getchannel("A"))
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192).save(OUT / "icon-192.png", optimize=True)
    icon(512).save(OUT / "icon-512.png", optimize=True)
    icon(512, maskable=True).save(OUT / "icon-maskable-512.png", optimize=True)
    # iOS draws its own rounded corners and shows transparency as black: full-bleed square
    flatten(icon(180, rounded=False)).save(OUT / "apple-touch-icon.png", optimize=True)
    icon(32, depth=3).save(OUT / "favicon-32.png", optimize=True)
    share_image().save(OUT / "og.png", optimize=True)
    for p in sorted(OUT.glob("*.png")):
        with Image.open(p) as im:
            print(f"{p.name:24} {im.size[0]}x{im.size[1]}  {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
