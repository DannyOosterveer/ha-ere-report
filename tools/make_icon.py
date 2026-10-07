"""Draw the integration icon: a charger, a green leaf and a euro coin.

Run with: python tools/make_icon.py
Writes icon.png (256), icon@2x.png (512) and dark_ variants to the brand folder.
"""

from math import atan2, cos, pi, sin
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

SIZE = 2048
OUT = Path(__file__).resolve().parent.parent / "custom_components/ere_report/brand"
EURO_FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

GREEN = "#43A047"
GREEN_VEIN = "#C8E6C9"
GOLD_RIM = "#E0A100"
GOLD_FACE = "#FFC83D"
GOLD_MARK = "#A86F00"
THEMES = {
    "": {"body": "#3C424A", "detail": "#1E2227"},
    "dark_": {"body": "#AEB6BF", "detail": "#3C424A"},
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


def draw(theme: dict[str, str]) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Cable, drawn first so the body covers its start.
    # Stamp circles along a curve: smoother than a polyline with joints.
    p0, p1, p2 = (600, 1560), (560, 1960), (170, 1850)
    r = 45
    for i in range(801):
        t = i / 800
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
        d.ellipse((x - r, y - r, x + r, y + r), fill=theme["body"])

    # Charger body, screen and button.
    d.rounded_rectangle((330, 150, 1170, 1640), radius=230, fill=theme["body"])
    d.rounded_rectangle((470, 340, 1030, 760), radius=90, fill=theme["detail"])
    d.ellipse((750 - 150, 1080 - 150, 750 + 150, 1080 + 150), fill=theme["detail"])

    # Leaf, top right, with a gap around it.
    base, tip = (1290, 930), (1890, 250)
    gap = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(gap).polygon(leaf_polygon(base, tip, 300), fill=255)
    img = knockout(img, gap)
    d = ImageDraw.Draw(img)
    d.polygon(leaf_polygon(base, tip, 230), fill=GREEN)
    vein_end = (
        base[0] + (tip[0] - base[0]) * 0.78,
        base[1] + (tip[1] - base[1]) * 0.78,
    )
    d.line((base, vein_end), fill=GREEN_VEIN, width=34)
    d.line(((base[0] - 60, base[1] + 70), base), fill=GREEN, width=50)

    # Coin, bottom right, with a gap so it reads on any background.
    cx, cy, radius = 1520, 1500, 430
    gap = Image.new("L", (SIZE, SIZE), 0)
    g = radius + 60
    ImageDraw.Draw(gap).ellipse((cx - g, cy - g, cx + g, cy + g), fill=255)
    img = knockout(img, gap)
    d = ImageDraw.Draw(img)
    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=GOLD_RIM)
    face = radius - 60
    d.ellipse((cx - face, cy - face, cx + face, cy + face), fill=GOLD_FACE)
    font = ImageFont.truetype(EURO_FONT, 520)
    d.text((cx, cy + 10), "€", font=font, fill=GOLD_MARK, anchor="mm")
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
