"""Build the mascot assets from docs/brand/mascot_source.png.

    python scripts/brand_assets.py

Outputs (app/static/brand/):
  mascot_full.png, mascot_head.png  — cropped, white background made transparent
  favicon-32.png, favicon-16.png    — the head, square
  apple-touch-icon.png
  docs/brand/*_vtracer.svg          — only with --svg (vtracer crashes on Python 3.14 / Windows)
It also prints the dominant blue of the mascot, used as the app's accent colour.

Background removal uses a flood fill from the image border over near-white pixels, so white areas
INSIDE the outline (belly, notebook, beak) stay white. A thin ring around the figure gets an alpha
from its darkness, so the anti-aliased edge has no white halo.
"""

from __future__ import annotations

import sys
from collections import Counter, deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "brand" / "mascot_source.png"
OUT_DOCS = ROOT / "docs" / "brand"
OUT_STATIC = ROOT / "app" / "static" / "brand"

WHITE_LEVEL = 232  # a pixel whose channels are all above this counts as background white
PAD = 10


def column_ranges(img: Image.Image) -> list[tuple[int, int]]:
    """Horizontal ranges that contain non-white pixels, split at empty gaps."""
    w, h = img.size
    px = img.load()
    filled = [any(min(px[x, y]) < WHITE_LEVEL for y in range(0, h, 2)) for x in range(w)]
    ranges, start = [], None
    for x, f in enumerate(filled + [False]):
        if f and start is None:
            start = x
        elif not f and start is not None:
            if x - start > 20:
                ranges.append((start, x))
            start = None
    # merge ranges separated by small gaps (e.g. a stray pixel column)
    merged = []
    for r in ranges:
        if merged and r[0] - merged[-1][1] < 25:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(r)
    return merged


def bbox_rows(img: Image.Image, x0: int, x1: int) -> tuple[int, int]:
    px = img.load()
    rows = [y for y in range(img.size[1]) if any(min(px[x, y]) < WHITE_LEVEL for x in range(x0, x1, 2))]
    return rows[0], rows[-1] + 1


def make_transparent(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    w, h = img.size
    px = img.load()
    background = [[False] * w for _ in range(h)]
    queue = deque((x, y) for x in range(w) for y in (0, h - 1))
    queue.extend((x, y) for y in range(h) for x in (0, w - 1))
    while queue:
        x, y = queue.popleft()
        if not (0 <= x < w and 0 <= y < h) or background[y][x] or min(px[x, y]) < WHITE_LEVEL:
            continue
        background[y][x] = True
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    mask = Image.new("L", (w, h), 0)
    mp = mask.load()
    for y in range(h):
        for x in range(w):
            if background[y][x]:
                mp[x, y] = 255
    ring = mask.filter(ImageFilter.MaxFilter(5))  # background grown by 2 px

    out = Image.new("RGBA", (w, h))
    op = out.load()
    rp = ring.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if background[y][x]:
                op[x, y] = (255, 255, 255, 0)
            elif rp[x, y]:
                # Edge pixel: derive alpha from how far it is from white, then un-blend the white.
                a = max(0.0, min(1.0, (255 - min(r, g, b)) / 200))
                if a <= 0.02:
                    op[x, y] = (255, 255, 255, 0)
                else:
                    un = lambda c: int(max(0, min(255, (c - 255 * (1 - a)) / a)))  # noqa: E731
                    op[x, y] = (un(r), un(g), un(b), int(a * 255))
            else:
                op[x, y] = (r, g, b, 255)
    return out


def square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (255, 255, 255, 0))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2), img)
    return canvas


def dominant_blue(img: Image.Image) -> str:
    counts: Counter = Counter()
    for r, g, b, a in img.get_flattened_data():
        if a == 255 and b > 170 and b - r > 90 and g > 70:  # bright blue, not the navy outline
            counts[(r // 8 * 8, g // 8 * 8, b // 8 * 8)] += 1
    (r, g, b), _ = counts.most_common(1)[0]
    return f"#{r + 4:02X}{g + 4:02X}{b + 4:02X}"


def vectorize(png: Path, svg: Path) -> dict:
    import vtracer

    vtracer.convert_image_to_svg_py(
        str(png), str(svg), colormode="color", hierarchical="stacked", mode="spline",
        filter_speckle=6, color_precision=6, layer_difference=24, corner_threshold=60,
        length_threshold=4.0, max_iterations=10, splice_threshold=45, path_precision=2,
    )
    text = svg.read_text(encoding="utf-8")
    return {"bytes": len(text.encode()), "paths": text.count("<path")}


def main() -> int:
    if not SOURCE.exists():
        print(f"Missing {SOURCE}", file=sys.stderr)
        return 1
    OUT_DOCS.mkdir(parents=True, exist_ok=True)
    OUT_STATIC.mkdir(parents=True, exist_ok=True)
    src = Image.open(SOURCE).convert("RGB")
    ranges = column_ranges(src)
    if len(ranges) != 2:
        print(f"Expected two figures, found column ranges {ranges}", file=sys.stderr)
        return 1

    results = {}
    for name, (x0, x1) in zip(("mascot_full", "mascot_head"), ranges):
        y0, y1 = bbox_rows(src, x0, x1)
        crop = src.crop((max(0, x0 - PAD), max(0, y0 - PAD), min(src.width, x1 + PAD), min(src.height, y1 + PAD)))
        clear = make_transparent(crop)
        clear.save(OUT_STATIC / f"{name}.png")
        results[name] = clear
        print(f"{name}: {clear.size[0]}x{clear.size[1]} px")

    head = square(results["mascot_head"])
    for size in (32, 16):
        head.resize((size, size), Image.LANCZOS).save(OUT_STATIC / f"favicon-{size}.png")
    head.resize((180, 180), Image.LANCZOS).save(OUT_STATIC / "apple-touch-icon.png")

    print("dominant blue:", dominant_blue(results["mascot_full"]))
    if "--svg" in sys.argv:
        # vtracer 0.6.15 crashes (access violation) on Python 3.14 / Windows, so this is opt-in.
        for name in ("mascot_full", "mascot_head"):
            stats = vectorize(OUT_STATIC / f"{name}.png", OUT_DOCS / f"{name}_vtracer.svg")
            print(f"{name}_vtracer.svg: {stats['paths']} paths, {stats['bytes'] / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
