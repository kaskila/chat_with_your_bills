"""Draw the app icon (a receipt on a blue tile) in every size the app needs.

    .venv\\Scripts\\python.exe scripts\\make_icons.py

Writes frontend/icons/*.png (web app / home screen) and scripts/app.ico (desktop shortcut).
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BLUE, WHITE, INK = (42, 120, 214, 255), (255, 255, 255, 255), (42, 120, 214, 255)


def draw(size: int, *, maskable: bool = False) -> Image.Image:
    """Drawn at 4x and scaled down for smooth edges. Maskable icons fill the whole square and
    keep the receipt inside the central safe zone (phones cut the corners into circles etc.)."""
    s = size * 4
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    if maskable:
        d.rectangle([0, 0, s, s], fill=BLUE)
        scale = 0.62
    else:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BLUE)
        scale = 0.74
    # Receipt: a tall white sheet with a zig-zag torn bottom edge and three text lines.
    w, h = s * scale * 0.68, s * scale
    left, top = (s - w) / 2, (s - h) / 2
    right, bottom = left + w, top + h
    teeth = 6
    tooth = w / teeth
    edge = [(right, bottom - tooth * 0.5)]
    for i in range(teeth, 0, -1):
        edge += [(left + tooth * (i - 0.5), bottom), (left + tooth * (i - 1), bottom - tooth * 0.5)]
    d.polygon([(left, top), (right, top), *edge], fill=WHITE)
    line_h = h * 0.07
    for i, frac in enumerate((0.72, 0.72, 0.45)):
        y = top + h * (0.2 + i * 0.17)
        d.rounded_rectangle([left + w * 0.16, y, left + w * (0.16 + frac), y + line_h], radius=line_h / 2, fill=INK)
    # Total line, bold, right-aligned.
    y = top + h * 0.72
    d.rounded_rectangle([left + w * 0.5, y, left + w * 0.84, y + line_h * 1.4], radius=line_h / 2, fill=INK)
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    icons = ROOT / "frontend" / "icons"
    icons.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        draw(size).save(icons / f"icon-{size}.png")
    draw(512, maskable=True).save(icons / "icon-maskable-512.png")
    draw(180, maskable=True).convert("RGB").save(icons / "apple-touch-icon.png")  # iOS adds its own corners
    draw(256).save(ROOT / "scripts" / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Icons written to {icons} and scripts/app.ico")


if __name__ == "__main__":
    main()
