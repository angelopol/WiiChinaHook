"""Wiimote/Nunchuk input basics shared by the Xbox (mapping.py) and PC (pc.py) modes:
button sources, shake detection and the IR pointer."""
from __future__ import annotations

BUTTON_SOURCES = {
    "wm_up": 0x0800, "wm_down": 0x0400, "wm_left": 0x0100, "wm_right": 0x0200,
    "wm_a": 0x0008, "wm_b": 0x0004, "wm_minus": 0x0010, "wm_plus": 0x1000,
    "wm_home": 0x0080, "wm_1": 0x0002, "wm_2": 0x0001,
    "nc_c": None, "nc_z": None,           # from the Nunchuk state
}
DIRECTIONS = ("left", "right", "up", "down", "forward", "back")
# A shake along an axis, either direction (testing showed the sign of a quick shake
# cannot be told apart reliably: every shake has a rebound). x = sideways,
# y = forward/back, z = up/down. Directional shakes stay accepted for old configs.
SHAKE_AXES = ("x", "y", "z")
AXIS_GESTURES = tuple(f"{device}_shake_{axis}" for device in ("wm", "nc") for axis in SHAKE_AXES)
GESTURE_SOURCES = AXIS_GESTURES + tuple(f"{device}_shake_{d}" for device in ("wm", "nc") for d in DIRECTIONS)


class ShakeDetector:
    """Short pulses when the dynamic acceleration (gravity removed by a slow
    low-pass) exceeds a threshold along an axis; one direction per axis per shake."""
    PULSE, REFRACTORY, TAU = 0.15, 0.35, 0.25

    def __init__(self):
        self.gravity = None
        self.last_t = None
        self.active_until = {}
        self.blocked_until = {}
        self.fired = []      # axes fired since last read (for the GUI's live test)
        self.peak = [0.0, 0.0, 0.0]

    def update(self, accel, t, thresholds):
        if accel is None:
            self.gravity = None
            return set()
        if self.gravity is None:
            self.gravity, self.last_t = list(accel), t
            return set()
        dt = max(0.0, min(0.1, t - self.last_t))
        self.last_t = t
        alpha = dt / (self.TAU + dt) if dt else 0.0
        dynamic = [a - g for a, g in zip(accel, self.gravity)]
        self.gravity = [g + alpha * (a - g) for a, g in zip(accel, self.gravity)]
        # Raw axes: X + = left, Y + = back, Z + = buttons face (up when flat).
        self.peak = [abs(d) for d in dynamic]
        for axis, (positive, negative) in enumerate((("left", "right"), ("back", "forward"), ("up", "down"))):
            if t < self.blocked_until.get(axis, 0) or abs(dynamic[axis]) < thresholds[axis]:
                continue
            direction = positive if dynamic[axis] > 0 else negative
            self.active_until[direction] = t + self.PULSE
            self.active_until[SHAKE_AXES[axis]] = t + self.PULSE  # direction-agnostic
            self.fired.append((SHAKE_AXES[axis], round(abs(dynamic[axis]), 2)))
            self.blocked_until[axis] = t + self.REFRACTORY
        return {d for d, until in self.active_until.items() if t < until}


def ir_stick(points, span):
    """IR pointer as stick axes (-1..1; x right, y up as the Xbox stick), or None
    when the camera sees no dot. `span` = fraction of the image for full deflection."""
    pointer = ir_pointer(points)
    if pointer is None:
        return None
    # The camera image is mirrored: pointing right moves the dots left.
    x = (511.5 - pointer[0]) / (511.5 * span)
    y = (pointer[1] - 383.5) / (383.5 * span)
    return max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y))


def ir_pointer(points):
    visible = [p for p in points or () if p]
    if not visible:
        return None
    if len(visible) >= 2:
        a, b = max(((p, q) for i, p in enumerate(visible) for q in visible[i + 1:]),
                   key=lambda pq: (pq[0]["x"] - pq[1]["x"]) ** 2 + (pq[0]["y"] - pq[1]["y"]) ** 2)
        return (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
    return visible[0]["x"], visible[0]["y"]
