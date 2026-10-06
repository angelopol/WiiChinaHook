"""Projected 3D Wiimote for the GUI (pure geometry; app.py turns it into shapes).

World frame as in orientation.py: X right, Y forward (towards the screen), Z up.
The camera sits behind and above the player, so an identity orientation shows
the remote lying face up and pointing into the screen.
"""
from __future__ import annotations

import math

from ..orientation import rotate

HALF = (18.0, 74.0, 15.5)                 # Wiimote half extents in mm (36 x 148 x 31)
CAMERA = (0.0, -310.0, 190.0)
LIGHT = (-0.35, -0.55, 0.76)
BODY = (236, 236, 240)
IR_WINDOW = (36, 36, 44)
FEATURE = (150, 156, 168)
A_BUTTON = (205, 210, 222)

# (outward normal, corner signs) for each face of the box.
FACES = {
    "top": ((0, 0, 1), [(-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]),
    "bottom": ((0, 0, -1), [(-1, 1, -1), (1, 1, -1), (1, -1, -1), (-1, -1, -1)]),
    "front": ((0, 1, 0), [(-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)]),
    "back": ((0, -1, 0), [(1, -1, -1), (1, -1, 1), (-1, -1, 1), (-1, -1, -1)]),
    "right": ((1, 0, 0), [(1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)]),
    "left": ((-1, 0, 0), [(-1, 1, -1), (-1, -1, -1), (-1, -1, 1), (-1, 1, 1)]),
}


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v):
    n = math.sqrt(_dot(v, v)) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


_FORWARD = _unit(_sub((0.0, 0.0, 0.0), CAMERA))
_RIGHT = _unit(_cross(_FORWARD, (0.0, 0.0, 1.0)))
_UP = _cross(_RIGHT, _FORWARD)
_LIGHT = _unit(LIGHT)


def _shade(color, normal):
    k = 0.42 + 0.58 * max(0.0, _dot(normal, _LIGHT))
    return "#%02x%02x%02x" % tuple(min(255, int(c * k)) for c in color)


def _top_features():
    """Polygons on the buttons face (body coordinates, slightly above it)."""
    z = HALF[2] + 0.2
    def rect(cx, cy, w, h):
        return [(cx - w, cy - h, z), (cx + w, cy - h, z), (cx + w, cy + h, z), (cx - w, cy + h, z)]
    def disc(cx, cy, r, n=10):
        return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n), z) for i in range(n)]
    return [
        (rect(0, 50, 9, 2.6), FEATURE), (rect(0, 50, 2.6, 9), FEATURE),   # D-pad near the tip
        (disc(0, 28, 6.5), A_BUTTON),                                      # A button
        (disc(0, -38, 4), FEATURE), (disc(0, -52, 4), FEATURE),           # 1 and 2
    ]


_FEATURES = _top_features()


def project_point(p_world, width: float, height: float):
    """Screen position of a world point (mm), same camera as project()."""
    focal = 1.9 * min(width, height * 1.35)
    d = _sub(p_world, CAMERA)
    depth = max(_dot(d, _FORWARD), 1.0)
    return (width / 2 + focal * _dot(d, _RIGHT) / depth, height / 2 - focal * _dot(d, _UP) / depth)


def project(q, width: float, height: float):
    """Polygons to draw, back to front: list of (screen points, '#rrggbb')."""
    def to_screen(p_world):
        return project_point(p_world, width, height)

    def world(v):
        return rotate(q, v)

    polygons = []
    for name, (normal, corners) in FACES.items():
        n_world = world(normal)
        corners_world = [world(tuple(s * h for s, h in zip(c, HALF))) for c in corners]
        center = tuple(sum(c[i] for c in corners_world) / 4 for i in range(3))
        if _dot(n_world, _sub(CAMERA, center)) <= 0:
            continue  # back face
        color = IR_WINDOW if name == "front" else BODY
        polygons.append((_dot(_sub(center, CAMERA), _FORWARD), [to_screen(c) for c in corners_world],
                         _shade(color, n_world), name))
    polygons.sort(key=lambda p: -p[0])
    result = []
    for _, points, color, name in polygons:
        result.append((points, color))
        if name == "top":
            top_normal = world((0, 0, 1))
            result.extend(([to_screen(world(v)) for v in poly], _shade(c, top_normal)) for poly, c in _FEATURES)
    return result
