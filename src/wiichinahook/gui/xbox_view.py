"""Live Xbox controller drawing for the gamepad tab: pressed buttons light up,
triggers fill and sticks move with the virtual controller's output."""
from __future__ import annotations

import flet as ft
import flet.canvas as cv

WIDTH, HEIGHT = 360, 240
BODY = "#3a3d44"
BODY_EDGE = "#55595f"
IDLE = "#5f646c"
LIT = "#ffffff"
FACE = {"A": ("#2e7d32", "#69f0ae"), "B": ("#a32a2a", "#ff6e6e"),
        "X": ("#1f4f9e", "#64b5ff"), "Y": ("#9e7d16", "#ffe066")}
FACE_POS = {"Y": (262, 72), "X": (240, 94), "B": (284, 94), "A": (262, 116)}
LEFT_STICK, RIGHT_STICK = (110, 94), (220, 150)
DPAD = (140, 150)
STICK_TRAVEL = 12


def _paint(color, stroke=None):
    if stroke:
        return ft.Paint(color=color, style=ft.PaintingStyle.STROKE, stroke_width=stroke)
    return ft.Paint(color=color, style=ft.PaintingStyle.FILL)


def _label(x, y, text, color="#ffffff", size=11):
    return cv.Text(x, y, text, style=ft.TextStyle(size=size, color=color, weight=ft.FontWeight.BOLD),
                   alignment=ft.Alignment.CENTER)


def shapes(output: dict | None):
    """Canvas shapes for an Xbox output {'active', 'buttons', 'lt', 'rt', 'lx', 'ly',
    'rx', 'ry'}; None or inactive draws the idle controller."""
    output = output or {}
    active = output.get("active", False)
    pressed = set(output.get("buttons", ())) if active else set()
    lt, rt = (output.get("lt", 0.0), output.get("rt", 0.0)) if active else (0.0, 0.0)
    result = []

    # Triggers (fill grows with the value) and bumpers.
    for x, value, name in ((70, lt, "LT"), (230, rt, "RT")):
        result.append(cv.Rect(x, 6, 60, 20, border_radius=6, paint=_paint(IDLE)))
        if value > 0:
            result.append(cv.Rect(x, 6, 60 * value, 20, border_radius=6, paint=_paint(LIT)))
        result.append(_label(x + 30, 16, name, "#202226" if value > 0.5 else "#ffffff", 10))
    for x, name in ((66, "LB"), (226, "RB")):
        result.append(cv.Rect(x, 32, 68, 14, border_radius=7, paint=_paint(LIT if name in pressed else IDLE)))
        result.append(_label(x + 34, 39, name, "#202226" if name in pressed else "#ffffff", 9))

    # Body: two grips and the central shell.
    for x in (36, 214):
        result.append(cv.Oval(x, 90, 110, 140, paint=_paint(BODY)))
    result.append(cv.Rect(56, 48, 248, 112, border_radius=48, paint=_paint(BODY)))
    result.append(cv.Rect(56, 48, 248, 112, border_radius=48, paint=_paint(BODY_EDGE, 2)))

    # Sticks: base ring + thumb that moves with the axis (L3/R3 light it).
    for (cx, cy), (x, y), name in ((LEFT_STICK, (output.get("lx", 0.0), output.get("ly", 0.0)), "L3"),
                                   (RIGHT_STICK, (output.get("rx", 0.0), output.get("ry", 0.0)), "R3")):
        if not active:
            x = y = 0.0
        result.append(cv.Circle(cx, cy, 24, paint=_paint("#2a2c31")))
        moved = abs(x) > 0.05 or abs(y) > 0.05
        result.append(cv.Circle(cx + x * STICK_TRAVEL, cy - y * STICK_TRAVEL, 15,
                                paint=_paint(LIT if name in pressed else IDLE)))
        if moved:  # outline the thumb while the stick is deflected
            result.append(cv.Circle(cx + x * STICK_TRAVEL, cy - y * STICK_TRAVEL, 15, paint=_paint(LIT, 2)))

    # D-pad.
    dx, dy = DPAD
    for name, (x, y) in (("DPAD_UP", (dx - 7, dy - 23)), ("DPAD_DOWN", (dx - 7, dy + 9)),
                         ("DPAD_LEFT", (dx - 23, dy - 7)), ("DPAD_RIGHT", (dx + 9, dy - 7))):
        result.append(cv.Rect(x, y, 14, 14, border_radius=3, paint=_paint(LIT if name in pressed else IDLE)))
    result.append(cv.Rect(dx - 7, dy - 7, 14, 14, paint=_paint(IDLE)))

    # Back / Guide / Start.
    for (x, y), name, radius in (((158, 94), "BACK", 7), ((180, 70), "GUIDE", 11), ((202, 94), "START", 7)):
        result.append(cv.Circle(x, y, radius, paint=_paint(LIT if name in pressed else IDLE)))

    # Face buttons in their colours, brighter when pressed.
    for name, (x, y) in FACE_POS.items():
        idle, lit = FACE[name]
        on = name in pressed
        result.append(cv.Circle(x, y, 11, paint=_paint(lit if on else idle)))
        if on:
            result.append(cv.Circle(x, y, 13, paint=_paint(LIT, 2)))
        result.append(_label(x, y, name, "#202226" if on else "#ffffff"))
    return result
