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

from ..orientation import heading, rotate
from .inputs import (AXIS_GESTURES, BUTTON_SOURCES, DIRECTIONS, GESTURE_SOURCES, SHAKE_AXES,  # noqa: F401
                     ShakeDetector, ir_pointer, ir_stick)
from .pc import PC_TEMPLATE, pc_problems, validate_pc_template


# gyro_angle: the remote's aim (orientation), so the stick holds where it points;
# gyro: rotation speed, so the stick springs back to centre when the turn stops.
STICK_SOURCES = ("nc_stick", "gyro_angle", "gyro", "ir")

BUTTON_TARGETS = ("A", "B", "X", "Y", "LB", "RB", "LT", "RT", "BACK", "START", "GUIDE", "L3", "R3",
                  "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT")
STICK_TARGETS = ("LEFT_STICK", "RIGHT_STICK")
MODE_ARROWS = {"wm_up": 1, "wm_right": 2, "wm_down": 3, "wm_left": 4}   # clockwise
MAX_CHORD = 3
# "wm_a+wm_b": both held. Home is refused behind a DolphinBar (the bar itself uses
# Home + D-pad), see GamepadHub.forbidden_modifiers.
MODIFIERS = ("wm_b", "wm_a+wm_b", "wm_a", "wm_home", "wm_minus", "wm_plus", "wm_1", "wm_2")


def modifier_held(modifier, pressed):
    return all(member in pressed for member in modifier.split("+"))

GAME_TEMPLATE = {
    "type": "xbox",
    "name": "Game",
    "buttons": {
        "A": "wm_1", "B": "wm_2", "X": "wm_minus", "Y": "wm_plus",
        "LB": "nc_c", "LT": "nc_z", "RB": "wm_a", "RT": "wm_b",
        "START": "wm_home", "BACK": "nc_c+nc_z", "GUIDE": None, "L3": None, "R3": None,
        "DPAD_UP": "wm_up", "DPAD_DOWN": "wm_down", "DPAD_LEFT": "wm_left", "DPAD_RIGHT": "wm_right",
    },
    "sticks": {"LEFT_STICK": "nc_stick", "RIGHT_STICK": "gyro_angle"},
    "angle_full_deg": 35.0,    # aim: degrees turned left/right for a full horizontal deflection
    "angle_full_deg_y": 25.0,  # aim: degrees tilted up/down for a full vertical deflection
    "gyro_full_dps": 200.0,    # turning speed (°/s) for a full horizontal right-stick deflection
    "gyro_full_dps_y": 200.0,  # tilting speed (°/s) for a full vertical deflection
    "ir_range": 0.5,           # fraction of the IR image for a full deflection
    # Dynamic acceleration (g) that counts as a shake, per axis x, y, z. The Nunchuk is
    # read uncalibrated ((raw - 512) / 200), so its thresholds absorb its real scale.
    "shake_wm": [1.3, 1.3, 1.3],
    "shake_nc": [1.3, 1.3, 1.3],
    # A button that belongs to a combination waits this long before firing alone, so
    # members pressed a few ms apart still make the combination. Others never wait.
    "chord_window_ms": 50,
    "deadzone": 0.08,          # Nunchuk stick and IR pointer
    "gyro_deadzone": 0.03,     # gyro aim/speed: hides hand tremor around the centre
}

# DSU mode: no virtual Xbox controller; the remotes go to DSU clients (Dolphin, Cemu)
# with all their features. Other modes keep DSU clients connected but idle.
# The extra DSU servers (dsu.py) carry what one DSU slot cannot: the Nunchuk's
# accelerometer and the IR pointer. On by default; off = their slots disconnected.
DSU_TEMPLATE = {"type": "dsu", "name": "DSU", "nunchuk_server": True, "ir_server": True, "ir_range": 0.5}
CONFIG_VERSION = 4


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
        result = copy.deepcopy(DSU_TEMPLATE)
        result["name"] = str(template.get("name") or "DSU")[:40]
        for key in ("nunchuk_server", "ir_server"):
            result[key] = bool(template.get(key, True))
        ir_range = float(template.get("ir_range", DSU_TEMPLATE["ir_range"]))
        if not 0.05 <= ir_range <= 1.0:
            raise ValueError("ir_range must be 0.05..1")
        result["ir_range"] = ir_range
        return result
    if kind == "pc":
        return validate_pc_template(template)
    if kind != "xbox":
        raise ValueError("Mode type must be xbox, dsu or pc")
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
    for key, low, high in (("angle_full_deg", 5, 90), ("angle_full_deg_y", 5, 90),
                           ("gyro_full_dps", 20, 2000), ("gyro_full_dps_y", 20, 2000), ("ir_range", 0.05, 1.0),
                           ("deadzone", 0.0, 0.5), ("gyro_deadzone", 0.0, 0.5)):
        value = float(result[key])
        if not low <= value <= high:
            raise ValueError(f"{key} must be {low}..{high}")
        result[key] = value
    window = result["chord_window_ms"]
    if isinstance(window, bool) or not isinstance(window, (int, float)) or not 0 <= window <= 300:
        raise ValueError("chord_window_ms must be 0..300")
    result["chord_window_ms"] = int(round(window))
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
    version = int(config.get("version", 1))
    if version < 2 and modes[1] is None and "dsu" not in map(mode_type, modes):
        modes[1] = copy.deepcopy(DSU_TEMPLATE)   # mode 2 became the DSU mode
    if version < 4 and modes[2] is None and "pc" not in map(mode_type, modes):
        modes[2] = copy.deepcopy(PC_TEMPLATE)    # mode 3 became the PC mode
    if version < 3:
        # The rate-based "gyro" stick sprang back to centre when the turn stopped; the
        # aim-based one holds the position, which is what a "gyro stick" was meant to be.
        for template in modes:
            if mode_type(template) == "xbox":
                for target, source in template["sticks"].items():
                    if source == "gyro":
                        template["sticks"][target] = "gyro_angle"
    startup = config.get("startup_mode")
    if startup is not None and (isinstance(startup, bool) or startup not in (1, 2, 3, 4)):
        raise ValueError("startup_mode must be 1..4 or null (last active mode)")
    return {"version": CONFIG_VERSION, "modifier": modifier, "mode": mode, "startup_mode": startup,
            "modes": modes}


def required_capability(source):
    if source is None:
        return None
    if source.startswith("nc_"):
        return "nunchuk"
    if source in ("gyro", "gyro_angle"):
        return "motionplus"
    if source == "ir":
        return "ir"
    return None


def unavailable_bindings(template: dict | None, capabilities: dict) -> list[str]:
    """'TARGET: source (needs capability)' for bindings this remote cannot drive."""
    if mode_type(template) == "pc":
        return pc_problems(template, capabilities)
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


class MappingEngine:
    """One per remote. process() turns a WiimoteState dict into an XboxState and an
    optional global mode request (modifier + arrow)."""

    def __init__(self):
        self.previous = set()
        self.suppressed = set()        # arrows consumed by a mode switch until released
        self.wm_shake = ShakeDetector()
        self.nc_shake = ShakeDetector()
        self._compiled_for, self._compiled = None, None
        self.since = {}                # source -> when it became active (chord window)
        self.waiting = set()           # chord members held back last report
        self.latched = set()           # members of a fired combination, until released
        self.taps = {}                 # quick taps of chord members -> pulse end
        self.aim_reference = None      # heading that counts as "centre" for gyro_angle
        self.aim_key = None

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
        if modifier_held(modifier, pressed):
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
        chords, buttons, members_of_chords = self.compiled(template)
        consumed, firing = set(), set()
        for chord, members in chords:
            if members <= active and not consumed & members:
                firing.add(chord)
                consumed |= members
        alone = self.individual(active, consumed, members_of_chords, t, template["chord_window_ms"] / 1000)
        out = XboxState()
        for target, source, chord in buttons:
            on = source in firing if chord else source in alone
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

    TAP_PULSE = 0.06  # s: a quick tap of a chord member still reaches the game

    def individual(self, active, consumed, members_of_chords, t, window):
        """Sources that fire on their own this report. A chord member waits `window`
        after being pressed (the rest of its combination may follow); one released
        before that, without making a combination, is sent as a short tap. Members of
        a combination stay used until released (releasing C before Z after C+Z must
        not press Z's own button)."""
        for source in active:
            self.since.setdefault(source, t)
        for source in [s for s in self.since if s not in active]:
            del self.since[source]
            if source in self.waiting and source not in self.latched:
                self.taps[source] = t + self.TAP_PULSE      # tapped and released in the window
        self.latched = (self.latched & active) | consumed
        free = active - self.latched
        self.waiting = {s for s in free if s in members_of_chords and t - self.since[s] < window}
        self.taps = {s: end for s, end in self.taps.items() if t < end}
        return (free - self.waiting) | set(self.taps)

    def compiled(self, template):
        """Chords (longest first, as member sets), the bound buttons of a template and
        every source used in a chord; rebuilt only when the template object changes
        (configs are replaced, not edited)."""
        if self._compiled_for is not template:
            chords = sorted({s for s in template["buttons"].values() if is_chord(s)},
                            key=lambda s: -len(chord_members(s)))
            members = [(c, frozenset(chord_members(c))) for c in chords]
            self._compiled = (members,
                              [(t, s, is_chord(s)) for t, s in template["buttons"].items() if s is not None],
                              frozenset().union(*(m for _, m in members)))
            self._compiled_for = template
        return self._compiled

    def aim(self, state, template):
        """Stick from the remote's orientation: horizontal = heading relative to a
        reference, vertical = tip elevation against gravity (no drift). The reference is
        taken when the mode (template) becomes active and again at every quick
        calibration; with the sensor-bar heading correction it is the bar itself."""
        q = state.get("orientation")
        if not q:
            return 0.0, 0.0
        tip = rotate(q, (0.0, 1.0, 0.0))
        calibration = state.get("calibration") or {}
        key = (id(template), calibration.get("recenter_seq"))
        if calibration.get("heading") == "ir":
            self.aim_reference, self.aim_key = 0.0, key
        elif key != self.aim_key or self.aim_reference is None:
            self.aim_reference, self.aim_key = heading(tip), key
        turn = math.atan2(math.sin(heading(tip) - self.aim_reference), math.cos(heading(tip) - self.aim_reference))
        elevation = math.asin(max(-1.0, min(1.0, tip[2])))
        # heading() grows counter-clockwise: turning right is negative -> stick right.
        x = -math.degrees(turn) / template["angle_full_deg"]
        y = math.degrees(elevation) / template["angle_full_deg_y"]
        return _deadzone(max(-1.0, min(1.0, x)), max(-1.0, min(1.0, y)), template["gyro_deadzone"])

    def stick(self, source, state, template):
        zone = template["deadzone"]
        if source == "gyro_angle":
            return self.aim(state, template)
        if source == "nc_stick":
            stick = (state.get("nunchuk") or {}).get("stick")
            return _deadzone(stick[0], stick[1], zone) if stick else (0.0, 0.0)
        if source == "gyro":
            gyro = state.get("gyro_dps")
            if not gyro:
                return 0.0, 0.0
            yaw, _roll, pitch = gyro
            # Turning right (yaw -) moves right; tip up (pitch -) moves up.
            return _deadzone(-yaw / template["gyro_full_dps"], -pitch / template["gyro_full_dps_y"],
                             template["gyro_deadzone"])
        if source == "ir":
            stick = ir_stick(state.get("ir"), template["ir_range"])
            return (0.0, 0.0) if stick is None else _deadzone(stick[0], stick[1], zone)
        return 0.0, 0.0


# startup_mode: the mode the service starts in (1-4), or None for the last active one.
# Mode 1 = Xbox game template, 2 = DSU (Dolphin/Cemu), 3 = PC (mouse and keyboard).
DEFAULT_CONFIG = {"version": CONFIG_VERSION, "modifier": "wm_b", "mode": 1, "startup_mode": None,
                  "modes": [copy.deepcopy(GAME_TEMPLATE), copy.deepcopy(DSU_TEMPLATE),
                            copy.deepcopy(PC_TEMPLATE), None]}
