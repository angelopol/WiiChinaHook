"""Render the MotionPlus scale-calibration gestures as looping GIFs.

Uses the same 3D Wiimote and camera as the GUI (gui/wiimote3d.py) so the GIFs
match what the app shows. Needs Pillow (the [dev] extra):

    .venv\\Scripts\\python tools\\make_calibration_gifs.py

Writes src/wiichinahook/gui/assets/calibration_{pitch,roll,yaw}.gif.
Each loop: keep still (short vibration), second vibration, slow 90 degree turn
about the calibrated axis, hold, long vibration. A phase bar at the bottom
(grey = still, blue = turn, green = hold) keeps the GIFs language independent.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wiichinahook.gui.wiimote3d import project, project_point  # noqa: E402
from wiichinahook.orientation import (from_axis_angle, multiply, reference_yaw, rotate,  # noqa: E402
                                      tilt_from_accel)

OUT = Path(__file__).resolve().parents[1] / "src" / "wiichinahook" / "gui" / "assets"
W, H, SS = 360, 270, 2          # output size and supersampling factor
FPS = 12
ZOOM, CENTER_Y = 0.72, 0.56   # shrink the GUI framing so a tip-up remote stays in view
STILL, TURN, HOLD, END = 1.4, 2.4, 1.2, 0.8   # seconds; END = long vibration + pause
BG = (43, 45, 49)
TABLE = (64, 67, 74)
AXIS = (255, 196, 64)
PHASES = ((STILL, (120, 124, 132)), (TURN, (66, 133, 244)), (HOLD + END, (52, 168, 83)))

GESTURES = {
    # name: (start pose from the raw accelerometer, body axis, signed angle)
    "pitch": ((0.0, 0.0, 1.0), (1, 0, 0), 90),    # flat -> tip up to the ceiling
    "roll": ((0.0, 0.0, 1.0), (0, 1, 0), 90),     # flat -> rolled onto its side
    "yaw": ((-1.0, 0.0, 0.0), (0, 0, 1), -90),    # sideways grip -> steering wheel to the right
}


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def buzz(draw, cx, cy, strength, color):
    """Vibration marks on both sides of the remote."""
    for side in (-1, 1):
        x0 = cx + side * 150 * SS
        points = [(x0 + side * (i % 2) * 10 * SS, cy - 36 * SS + i * 12 * SS) for i in range(7)]
        draw.line(points, fill=color, width=int(3 * SS * strength) or 1, joint="curve")


def frame(gesture, t):
    start_accel, axis, degrees = GESTURES[gesture]
    q0 = tilt_from_accel(start_accel)
    q0 = multiply(from_axis_angle((0, 0, 1), -reference_yaw(q0)), q0)  # as the GUI recenters it
    angle = math.radians(degrees) * smoothstep((t - STILL) / TURN)
    q = multiply(q0, from_axis_angle(axis, angle))

    image = Image.new("RGB", (W * SS, H * SS), BG)
    draw = ImageDraw.Draw(image)
    w, h = W * SS, (H - 30) * SS

    def fit(point):  # GUI projection, zoomed out and lowered
        return (w / 2 + (point[0] - w / 2) * ZOOM, h * CENTER_Y + (point[1] - h / 2) * ZOOM)

    def screen(p_world):
        return fit(project_point(p_world, w, h))

    # Table edge under the remote for a sense of "flat".
    draw.line([screen((-150, -40, -18)), screen((150, -40, -18))], fill=TABLE, width=3 * SS)
    if gesture == "yaw":
        # Steering wheel: the axis points at the player, so show a circular arrow.
        cx, cy = screen((0, 0, 0))
        r = 92 * SS
        draw.arc([cx - r, cy - r, cx + r, cy + r], start=200, end=320, fill=AXIS, width=3 * SS)
        end = math.radians(320)
        ex, ey = cx + r * math.cos(end), cy + r * math.sin(end)
        draw.polygon([(ex + 9 * SS, ey + 2 * SS), (ex - 6 * SS, ey - 9 * SS), (ex - 4 * SS, ey + 9 * SS)], fill=AXIS)
    else:
        # Rotation axis through the remote, in the world frame.
        a = rotate(q, tuple(c * 105 for c in axis))
        draw.line([screen(tuple(-c for c in a)), screen(a)], fill=AXIS, width=2 * SS)
    for points, color in project(q, w, h):
        draw.polygon([fit(pt) for pt in points], fill=color)
    if gesture != "yaw":
        tip = screen(a)
        draw.ellipse([tip[0] - 5 * SS, tip[1] - 5 * SS, tip[0] + 5 * SS, tip[1] + 5 * SS], fill=AXIS)

    cx, cy = w / 2, h * CENTER_Y
    if t < 0.35:                                   # short vibration: keep still
        buzz(draw, cx, cy, 1.0, (200, 200, 200))
    elif STILL <= t < STILL + 0.35:                # second vibration: start turning
        buzz(draw, cx, cy, 1.0, (120, 170, 255))
    elif STILL + TURN + HOLD <= t < STILL + TURN + HOLD + 0.6:   # long vibration: done
        buzz(draw, cx, cy, 1.4, (110, 220, 140))

    # Phase bar with a moving marker.
    total = STILL + TURN + HOLD + END
    x, y0, y1 = 16 * SS, (H - 20) * SS, (H - 10) * SS
    for seconds, color in PHASES:
        x1 = x + (W - 32) * SS * seconds / total
        draw.rectangle([x, y0, x1 - 2 * SS, y1], fill=color)
        x = x1
    marker = 16 * SS + (W - 32) * SS * min(t, total) / total
    draw.polygon([(marker, y0 - 2 * SS), (marker - 6 * SS, y0 - 10 * SS), (marker + 6 * SS, y0 - 10 * SS)],
                 fill=(240, 240, 240))
    return image.resize((W, H), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    total = STILL + TURN + HOLD + END
    for gesture in GESTURES:
        frames = [frame(gesture, i / FPS) for i in range(int(total * FPS))]
        palette = [f.convert("P", palette=Image.ADAPTIVE, colors=64) for f in frames]
        path = OUT / f"calibration_{gesture}.gif"
        palette[0].save(path, save_all=True, append_images=palette[1:], duration=int(1000 / FPS),
                        loop=0, optimize=True, disposal=2)
        print(f"{path.name}: {len(frames)} frames, {path.stat().st_size // 1024} KiB")


if __name__ == "__main__":
    main()
