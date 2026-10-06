"""Draw the app icon (a Wiimote over a sensor-bar glow) into gui/assets.

Writes icon.png (512 px, window/tray) and icon.ico (16-256 px, executable).
Run: python tools/make_icon.py   (needs Pillow, the `dev` extra)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parents[1] / "src" / "wiichinahook" / "gui" / "assets"
SIZE = 1024  # drawn large, then downscaled for smooth edges


def draw():
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    # Background tile: deep blue rounded square with a lighter top half.
    d.rounded_rectangle((32, 32, SIZE - 32, SIZE - 32), radius=220, fill=(24, 74, 160))
    d.rounded_rectangle((32, 32, SIZE - 32, SIZE // 2), radius=220, fill=(36, 98, 196))
    d.rectangle((32, SIZE // 2 - 220, SIZE - 32, SIZE // 2), fill=(36, 98, 196))

    # Sensor bar glow behind the tip: two red IR dots.
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for cx in (300, 724):
        g.ellipse((cx - 70, 130, cx + 70, 270), fill=(255, 70, 70, 210))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(28)))
    for cx in (300, 724):
        d.ellipse((cx - 26, 174, cx + 26, 226), fill=(255, 225, 225))

    # Wiimote body, tilted slightly like a remote pointing at the screen.
    remote = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    r = ImageDraw.Draw(remote)
    left, top, right, bottom = 392, 250, 632, 940
    r.rounded_rectangle((left + 14, top + 18, right + 14, bottom + 18), radius=96, fill=(0, 0, 0, 90))  # shadow
    r.rounded_rectangle((left, top, right, bottom), radius=96, fill=(250, 250, 252))
    r.rounded_rectangle((left, top, right, bottom), radius=96, outline=(200, 205, 215), width=8)
    cx = (left + right) // 2
    # D-pad.
    r.rounded_rectangle((cx - 26, 330, cx + 26, 470), radius=10, fill=(70, 74, 84))
    r.rounded_rectangle((cx - 70, 374, cx + 70, 426), radius=10, fill=(70, 74, 84))
    # A button.
    r.ellipse((cx - 46, 520, cx + 46, 612), fill=(70, 74, 84))
    # -, HOME, +
    for dx in (-62, 0, 62):
        r.ellipse((cx + dx - 16, 672, cx + dx + 16, 704), fill=(150, 156, 168) if dx else (36, 98, 196))
    # 1 and 2.
    for y in (770, 846):
        r.ellipse((cx - 30, y - 30, cx + 30, y + 30), fill=(70, 74, 84))
    # Player LEDs, first one lit.
    for i in range(4):
        x = cx - 63 + i * 42
        r.ellipse((x - 9, 902, x + 9, 920), fill=(64, 160, 255) if i == 0 else (200, 205, 215))
    remote = remote.rotate(-12, resample=Image.BICUBIC, center=(SIZE // 2, SIZE // 2 + 80))
    image.alpha_composite(remote)
    return image


def main():
    image = draw()
    ASSETS.mkdir(parents=True, exist_ok=True)
    image.resize((512, 512), Image.LANCZOS).save(ASSETS / "icon.png")
    image.resize((256, 256), Image.LANCZOS).save(
        ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Wrote", ASSETS / "icon.png", "and", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
