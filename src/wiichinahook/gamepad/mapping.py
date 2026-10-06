"""Wiimote -> Xbox controller mapping (pure logic, no Windows APIs).

Modes 1-4 are global for every connected remote. Each mode either has a template
(a virtual Xbox controller per remote) or is empty (no virtual controller; DSU and
the API keep working as always). Holding the modifier (default B) and pressing an
arrow switches mode clockwise: up = 1, right = 2, down = 3, left = 4; that arrow is
not sent to the game. The Wiimote POWER button is not reported by the hardware, so
it cannot be mapped.

Axes (see orientation.py): raw Wiimote accelerometer X = left, Y = back (1/2 end),
Z = buttons face; MotionPlus pitch + = tip down, yaw + = counter-clockwise. The
Nunchuk accelerometer is used uncalibrated (raw - 512) / 200 with the same axis
names; its shake directions are not verified on hardware yet, nor is the IR
vertical direction.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
import math

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
STICK_SOURCES = ("nc_stick", "gyro", "ir")

BUTTON_TARGETS = ("A", "B", "X", "Y", "LB", "RB", "LT", "RT", "BACK", "START", "GUIDE", "L3", "R3",
                  "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT")
STICK_TARGETS = ("LEFT_STICK", "RIGHT_STICK")
MODE_ARROWS = {"wm_up": 1, "wm_right": 2, "wm_down": 3, "wm_left": 4}   # clockwise
MAX_CHORD = 3
MODIFIERS = ("wm_b", "wm_a", "wm_home", "wm_minus", "wm_plus", "wm_1", "wm_2")

GAME_TEMPLATE = {
    "type": "xbox",
    "name": "Game",
    "buttons": {
        "A": "wm_1", "B": "wm_2", "X": "wm_minus", "Y": "wm_plus",
        "LB": "nc_c", "LT": "nc_z", "RB": "wm_a", "RT": "wm_b",
        "START": "wm_home", "BACK": "nc_c+nc_z", "GUIDE": None, "L3": None, "R3": None,
        "DPAD_UP": "wm_up", "DPAD_DOWN": "wm_down", "DPAD_LEFT": "wm_left", "DPAD_RIGHT": "wm_right",
    },
    "sticks": {"LEFT_STICK": "nc_stick", "RIGHT_STICK": "gyro"},
    "gyro_full_dps": 200.0,    # turning speed (°/s) for a full horizontal right-stick deflection
    "gyro_full_dps_y": 200.0,  # tilting speed (°/s) for a full vertical deflection
    "ir_range": 0.5,           # fraction of the IR image for a full deflection
    # Dynamic acceleration (g) that counts as a shake, per axis x, y, z. The Nunchuk is
    # read uncalibrated ((raw - 512) / 200), so its thresholds absorb its real scale.
    "shake_wm": [1.3, 1.3, 1.3],
    "shake_nc": [1.3, 1.3, 1.3],
    "deadzone": 0.08,
}

# DSU mode: no virtual Xbox controller; the remotes go to DSU clients (Dolphin, Cemu)
# with all their features. Other modes keep DSU clients connected but idle.
DSU_TEMPLATE = {"type": "dsu", "name": "DSU"}
CONFIG_VERSION = 2
DEFAULT_CONFIG = {"version": CONFIG_VERSION, "modifier": "wm_b", "mode": 1,
                  "modes": [copy.deepcopy(GAME_TEMPLATE), copy.deepcopy(DSU_TEMPLATE), None, None]}


def mode_type(template):
    return None if template is None else template.get("type", "xbox")


def is_chord(source):
    return isinstance(source, str) and "+" in source


def chord_members(source):
    return source.split("+")


def validate_template(template: dict) -> dict:
    if template is None:
        return None
    if not isinstance(template, dict):
        raise ValueError("A mode template must be an object or null")
    kind = template.get("type", "xbox")
    if kind == "dsu":
        return {"type": "dsu", "name": str(template.get("name") or "DSU")[:40]}
    if kind != "xbox":
        raise ValueError("Mode type must be xbox or dsu")
    result = copy.deepcopy(GAME_TEMPLATE)
    if "shake_g" in template:  # configs from before per-axis sensitivity
        result["shake_wm"] = result["shake_nc"] = [template["shake_g"]] * 3
    if "gyro_full_dps" in template and "gyro_full_dps_y" not in template:
        result["gyro_full_dps_y"] = template["gyro_full_dps"]
    result.update({k: v for k, v in template.items() if k in GAME_TEMPLATE and k not in ("buttons", "sticks")})
    buttons = template.get("buttons", GAME_TEMPLATE["buttons"])
    sticks = template.get("sticks", GAME_TEMPLATE["sticks"])
    unknown = (set(buttons) - set(BUTTON_TARGETS)) | (set(sticks) - set(STICK_TARGETS))
    if unknown:
        raise ValueError(f"Unknown Xbox control: {', '.join(sorted(unknown))}")
    result["buttons"] = {target: buttons.get(target) for target in BUTTON_TARGETS}
    result["sticks"] = {target: sticks.get(target) for target in STICK_TARGETS}
    for target, source in result["buttons"].items():
        if source is None:
            continue
        members = chord_members(source) if is_chord(source) else [source]
        # Up to three buttons and/or shakes held together, e.g. "wm_a+wm_shake_up".
        if any(m not in BUTTON_SOURCES and m not in GESTURE_SOURCES for m in members) or \
                len(members) > MAX_CHORD or len(set(members)) != len(members):
            raise ValueError(f"Invalid source for {target}: {source}")
    for target, source in result["sticks"].items():
        if source is not None and source not in STICK_SOURCES:
            raise ValueError(f"Invalid source for {target}: {source}")
    for key, low, high in (("gyro_full_dps", 20, 2000), ("gyro_full_dps_y", 20, 2000), ("ir_range", 0.05, 1.0),
                           ("deadzone", 0.0, 0.5)):
        value = float(result[key])
        if not low <= value <= high:
            raise ValueError(f"{key} must be {low}..{high}")
        result[key] = value
    for key in ("shake_wm", "shake_nc"):
        values = result[key]
        if not isinstance(values, (list, tuple)) or len(values) != 3:
            raise ValueError(f"{key} must be three values (x, y, z)")
        values = [float(v) for v in values]
        if not all(0.2 <= v <= 6.0 for v in values):
            raise ValueError(f"{key} must be 0.2..6 g")
        result[key] = values
    result["name"] = str(result.get("name") or "Game")[:40]
    return result


def validate_config(config: dict | None) -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG if config is None else config)
    modifier = config.get("modifier", "wm_b")
    if modifier not in MODIFIERS:
        raise ValueError(f"modifier must be one of {', '.join(MODIFIERS)}")
    mode = int(config.get("mode", 1))
    if mode not in (1, 2, 3, 4):
        raise ValueError("mode must be 1..4")
    modes = list(config.get("modes", []))[:4]
    modes += [None] * (4 - len(modes))
    modes = [validate_template(t) for t in modes]
    if int(config.get("version", 1)) < 2 and modes[1] is None and "dsu" not in map(mode_type, modes):
        modes[1] = copy.deepcopy(DSU_TEMPLATE)   # mode 2 became the DSU mode
    return {"version": CONFIG_VERSION, "modifier": modifier, "mode": mode, "modes": modes}


def required_capability(source):
    if source is None:
        return None
    if source.startswith("nc_"):
        return "nunchuk"
    if source == "gyro":
        return "motionplus"
    if source == "ir":
        return "ir"
    return None


def unavailable_bindings(template: dict | None, capabilities: dict) -> list[str]:
    """'TARGET: source (needs capability)' for bindings this remote cannot drive."""
    if mode_type(template) != "xbox":
        return []
    problems = []
    bindings = list(template["buttons"].items()) + list(template["sticks"].items())
    for target, source in bindings:
        if source is None:
            continue
        for member in (chord_members(source) if is_chord(source) else [source]):
            need = required_capability(member)
            if need and not capabilities.get(need):
                problems.append(f"{target}: {source} (needs {need})")
                break
    return problems


@dataclass
class XboxState:
    buttons: set = field(default_factory=set)
    lt: float = 0.0
    rt: float = 0.0
    lx: float = 0.0
    ly: float = 0.0
    rx: float = 0.0
    ry: float = 0.0


def _deadzone(x, y, zone):
    magnitude = math.hypot(x, y)
    if magnitude <= zone:
        return 0.0, 0.0
    scale = min(1.0, (magnitude - zone) / (1 - zone)) / magnitude
    return max(-1.0, min(1.0, x * scale)), max(-1.0, min(1.0, y * scale))


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


def ir_pointer(points):
    visible = [p for p in points or () if p]
    if not visible:
        return None
    if len(visible) >= 2:
        a, b = max(((p, q) for i, p in enumerate(visible) for q in visible[i + 1:]),
                   key=lambda pq: (pq[0]["x"] - pq[1]["x"]) ** 2 + (pq[0]["y"] - pq[1]["y"]) ** 2)
        return (a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2
    return visible[0]["x"], visible[0]["y"]


class MappingEngine:
    """One per remote. process() turns a WiimoteState dict into an XboxState and an
    optional global mode request (modifier + arrow)."""

    def __init__(self):
        self.previous = set()
        self.suppressed = set()        # arrows consumed by a mode switch until released
        self.wm_shake = ShakeDetector()
        self.nc_shake = ShakeDetector()
        self._compiled_for, self._compiled = None, None

    def take_fired(self):
        """Shakes detected since the last call: [(device, axis, g)] for the live test."""
        fired = [("wm", axis, g) for axis, g in self.wm_shake.fired]
        fired += [("nc", axis, g) for axis, g in self.nc_shake.fired]
        self.wm_shake.fired.clear()
        self.nc_shake.fired.clear()
        return fired

    @staticmethod
    def pressed_sources(state):
        pressed = {name for name, bit in BUTTON_SOURCES.items() if bit and state.get("buttons", 0) & bit}
        nunchuk = state.get("nunchuk") or {}
        if nunchuk.get("c"):
            pressed.add("nc_c")
        if nunchuk.get("z"):
            pressed.add("nc_z")
        return pressed

    def process(self, state: dict, template: dict | None, modifier: str = "wm_b"):
        pressed = self.pressed_sources(state)
        newly = pressed - self.previous
        self.previous = pressed
        self.suppressed &= pressed
        mode_request = None
        if modifier in pressed:
            for arrow, mode in MODE_ARROWS.items():
                if arrow in newly:
                    mode_request = mode
                    self.suppressed.add(arrow)
        t = (state.get("timestamp_us") or 0) / 1e6
        if template is None:
            return None, mode_request
        active = pressed - self.suppressed
        active |= {f"wm_shake_{d}" for d in self.wm_shake.update(state.get("accel_g"), t, template["shake_wm"])}
        nunchuk = state.get("nunchuk") or {}
        raw = nunchuk.get("accel_raw")
        nc_accel = [(v - 512) / 200.0 for v in raw] if raw else None
        active |= {f"nc_shake_{d}" for d in self.nc_shake.update(nc_accel, t, template["shake_nc"])}

        # Combinations win over their members (C+Z = Select must not also press LB and
        # LT), and longer combinations over shorter overlapping ones.
        chords, buttons = self.compiled(template)
        consumed, firing = set(), set()
        for chord, members in chords:
            if members <= active and not consumed & members:
                firing.add(chord)
                consumed |= members
        out = XboxState()
        for target, source, chord in buttons:
            on = source in firing if chord else (source in active and source not in consumed)
            if not on:
                continue
            if target == "LT":
                out.lt = 1.0
            elif target == "RT":
                out.rt = 1.0
            else:
                out.buttons.add(target)
        for target, source in template["sticks"].items():
            x, y = self.stick(source, state, template)
            if target == "LEFT_STICK":
                out.lx, out.ly = x, y
            else:
                out.rx, out.ry = x, y
        return out, mode_request

    def compiled(self, template):
        """Chords (longest first, as member sets) and the bound buttons of a template,
        rebuilt only when the template object changes (configs are replaced, not edited)."""
        if self._compiled_for is not template:
            chords = sorted({s for s in template["buttons"].values() if is_chord(s)},
                            key=lambda s: -len(chord_members(s)))
            self._compiled = ([(c, frozenset(chord_members(c))) for c in chords],
                              [(t, s, is_chord(s)) for t, s in template["buttons"].items() if s is not None])
            self._compiled_for = template
        return self._compiled

    @staticmethod
    def stick(source, state, template):
        zone = template["deadzone"]
        if source == "nc_stick":
            stick = (state.get("nunchuk") or {}).get("stick")
            return _deadzone(stick[0], stick[1], zone) if stick else (0.0, 0.0)
        if source == "gyro":
            gyro = state.get("gyro_dps")
            if not gyro:
                return 0.0, 0.0
            yaw, _roll, pitch = gyro
            # Turning right (yaw -) moves right; tip up (pitch -) moves up.
            return _deadzone(-yaw / template["gyro_full_dps"], -pitch / template["gyro_full_dps_y"], zone)
        if source == "ir":
            pointer = ir_pointer(state.get("ir"))
            if pointer is None:
                return 0.0, 0.0
            span = template["ir_range"]
            # The camera image is mirrored: pointing right moves the dots left.
            x = (511.5 - pointer[0]) / (511.5 * span)
            y = (pointer[1] - 383.5) / (383.5 * span)
            return _deadzone(max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)), zone)
        return 0.0, 0.0
