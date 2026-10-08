"""Draw the integration icon: a wall charger with cable, a leaf and a euro coin.

Run with: python tools/make_icon.py
Writes icon.png (256), icon@2x.png (512) and dark_ variants to the brand folder.
"""

from math import atan2, cos, pi, sin
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

SIZE = 2400
OUT = Path(__file__).resolve().parent.parent / "custom_components/ere_report/brand"
EURO_FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

GREEN = "#43A047"
GREEN_VEIN = "#C8E6C9"
GOLD_RIM = "#E0A100"
GOLD_FACE = "#FFC83D"
GOLD_MARK = "#A86F00"
THEMES = {
    "": {"body": "#3C424A", "detail": "#1E2227", "bolt": "#FFC83D"},
    "dark_": {"body": "#AEB6BF", "detail": "#3C424A", "bolt": "#3C424A"},
}


def knockout(layer: Image.Image, shape: Image.Image) -> Image.Image:
    """Clear the pixels of ``layer`` where ``shape`` is drawn."""
    alpha = ImageChops.subtract(layer.getchannel("A"), shape)
    layer.putalpha(alpha)
    return layer


def leaf_polygon(base, tip, half_width, steps=120):
    angle = atan2(tip[1] - base[1], tip[0] - base[0])
    length = ((tip[0] - base[0]) ** 2 + (tip[1] - base[1]) ** 2) ** 0.5
    nx, ny = -sin(angle), cos(angle)
    left, right = [], []
    for i in range(steps + 1):
        t = i / steps
        w = half_width * sin(pi * t) ** 0.8 * (1 - 0.25 * t)
        px = base[0] + cos(angle) * length * t
        py = base[1] + sin(angle) * length * t
        left.append((px + nx * w, py + ny * w))
        right.append((px - nx * w, py - ny * w))
    return left + right[::-1]


def stamp_path(d: ImageDraw.ImageDraw, points, radius: int, fill: str) -> None:
    """Draw a thick round-capped stroke by stamping circles along the points."""
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        steps = max(1, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / 4))
        for i in range(steps + 1):
            x = x0 + (x1 - x0) * i / steps
            y = y0 + (y1 - y0) * i / steps
            d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def u_curve(left_x, right_x, top_y, bottom_y, steps=60):
    """Points down the right side, round the bottom, and up the left side."""
    cx = (left_x + right_x) / 2
    rx = (right_x - left_x) / 2
    points = [(right_x, top_y), (right_x, bottom_y - rx)]
    for i in range(steps + 1):
        a = pi * i / steps
        points.append((cx + rx * cos(a), bottom_y - rx + rx * sin(a)))
    points.append((left_x, top_y))
    return points


def draw(theme: dict[str, str]) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body, detail = theme["body"], theme["detail"]

    # Cable: from the plug down, round the bottom, up into the charger.
    stamp_path(d, u_curve(760, 1230, 1100, 1830), 62, body)

    # Wall box with screen, lightning bolt and a foot.
    d.rounded_rectangle((330, 1290, 600, 1420), radius=40, fill=body)
    d.rounded_rectangle((160, 120, 1060, 1340), radius=170, fill=body)
    d.rounded_rectangle((360, 270, 860, 460), radius=50, fill=detail)
    bolt = [
        (700, 560),
        (440, 960),
        (610, 960),
        (520, 1220),
        (800, 800),
        (630, 800),
        (720, 560),
    ]
    d.polygon(bolt, fill=theme["bolt"])

    # Holster and plug on the right side of the box.
    d.rounded_rectangle((1000, 330, 1200, 470), radius=40, fill=body)
    d.rounded_rectangle((1120, 300, 1340, 900), radius=110, fill=body)
    d.rounded_rectangle((1150, 860, 1310, 1140), radius=60, fill=body)

    # Large leaf with its lower part behind the coin.
    base, tip = (1640, 1700), (2230, 720)
    gap = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(gap).polygon(leaf_polygon(base, tip, 400), fill=255)
    img = knockout(img, gap)
    d = ImageDraw.Draw(img)
    d.polygon(leaf_polygon(base, tip, 330), fill=GREEN)
    vein_end = (base[0] + (tip[0] - base[0]) * 0.8, base[1] + (tip[1] - base[1]) * 0.8)
    d.line((base, vein_end), fill=GREEN_VEIN, width=32)

    # Coin in front, with a gap so it reads on any background.
    cx, cy, radius = 1640, 1720, 380
    gap = Image.new("L", (SIZE, SIZE), 0)
    g = radius + 55
    ImageDraw.Draw(gap).ellipse((cx - g, cy - g, cx + g, cy + g), fill=255)
    img = knockout(img, gap)
    coin = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    c = ImageDraw.Draw(coin)
    c.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=GOLD_RIM)
    face = radius - 54
    c.ellipse((cx - face, cy - face, cx + face, cy + face), fill=GOLD_FACE)
    # A slightly tilted euro sign makes the coin look tossed rather than placed.
    mark = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    font = ImageFont.truetype(EURO_FONT, 460)
    ImageDraw.Draw(mark).text((cx, cy + 8), "€", font=font, fill=GOLD_MARK, anchor="mm")
    mark = mark.rotate(14, resample=Image.Resampling.BICUBIC, center=(cx, cy))
    coin.alpha_composite(mark)
    img.alpha_composite(coin)
    return img


def trim_square(img: Image.Image, margin: float = 0.02) -> Image.Image:
    box = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    cropped = img.crop(box)
    side = int(max(cropped.size) * (1 + 2 * margin))
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(cropped, ((side - cropped.width) // 2, (side - cropped.height) // 2))
    return square


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for prefix, theme in THEMES.items():
        icon = trim_square(draw(theme))
        for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
            resized = icon.resize((size, size), Image.Resampling.LANCZOS)
            resized.save(OUT / f"{prefix}{name}", optimize=True)


if __name__ == "__main__":
    main()
