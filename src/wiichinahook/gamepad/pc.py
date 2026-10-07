"""PC mode: the remotes as mouse and keyboard (pure logic; output in winput.py).

A PC template has a mouse source and one action per input:

    "mouse": {"source": "gyro" | "ir" | "nc_stick" | "wm_dpad" | None, ...speeds...}
    "buttons": {"wm_a": "mouse:left", "wm_1": "keys:ctrl+9", ...}

Actions (strings, so they are easy to store and type):

    keys:ctrl+shift+esc      any number of keys, held while the input is held
    mouse:left|right|middle  held while the input is held; mouse:scroll_up|scroll_down repeat
    system:mute|volume_up|volume_down|next_track|previous_track|play_pause|stop|start_menu
    open:<program, file or https:// address>
    toggle:<step> | <step> | ...   each press runs the next step (a step without a
                                   prefix is keys, e.g. "toggle:ctrl+c | ctrl+v")

Inputs: the Wiimote and Nunchuk buttons, the Nunchuk stick as four directions and the
shakes. Whatever drives the mouse cannot be mapped (the D-pad or the Nunchuk stick).
The mode modifier's action fires on release (so modifier + arrow switches mode
without clicking), and inputs already held when the mode starts are ignored until
released.
"""
from __future__ import annotations

import copy
import math

from .inputs import AXIS_GESTURES, BUTTON_SOURCES, SHAKE_AXES, ShakeDetector, ir_stick

STICK_DIRECTIONS = ("nc_up", "nc_down", "nc_left", "nc_right")
PC_SOURCES = (*BUTTON_SOURCES, *STICK_DIRECTIONS, *AXIS_GESTURES)
MOUSE_SOURCES = ("gyro", "ir", "nc_stick", "wm_dpad")
# What a mouse source uses up: those inputs cannot also be keys.
MOUSE_CLAIMS = {"wm_dpad": ("wm_up", "wm_down", "wm_left", "wm_right"), "nc_stick": STICK_DIRECTIONS}
MOUSE_BUTTONS = ("left", "right", "middle")
MOUSE_ACTIONS = (*MOUSE_BUTTONS, "scroll_up", "scroll_down")
SYSTEM_ACTIONS = ("mute", "volume_up", "volume_down", "next_track", "previous_track", "play_pause", "stop",
                  "start_menu")
ACTION_TYPES = ("keys", "mouse", "system", "open", "toggle")
STICK_THRESHOLD = 0.5          # Nunchuk stick deflection that counts as a direction press
MODIFIER_WINDOW = 0.06         # s the members of a two-button modifier wait for each other
SCROLL_DELAY, SCROLL_REPEAT = 0.4, 0.08

# Key name -> (virtual-key code, extended). Letters, digits and F-keys are added below.
KEYS = {
    "ctrl": (0xA2, False), "shift": (0xA0, False), "alt": (0xA4, False), "win": (0x5B, True),
    "rctrl": (0xA3, True), "rshift": (0xA1, False), "ralt": (0xA5, True), "rwin": (0x5C, True),
    "enter": (0x0D, False), "esc": (0x1B, False), "tab": (0x09, False), "space": (0x20, False),
    "backspace": (0x08, False), "delete": (0x2E, True), "insert": (0x2D, True), "home": (0x24, True),
    "end": (0x23, True), "pageup": (0x21, True), "pagedown": (0x22, True), "up": (0x26, True),
    "down": (0x28, True), "left": (0x25, True), "right": (0x27, True), "capslock": (0x14, False),
    "numlock": (0x90, True), "scrolllock": (0x91, False), "printscreen": (0x2C, True), "pause": (0x13, False),
    "menu": (0x5D, True), "num_multiply": (0x6A, False), "num_add": (0x6B, False), "num_subtract": (0x6D, False),
    "num_decimal": (0x6E, False), "num_divide": (0x6F, True), "num_enter": (0x0D, True),
    ";": (0xBA, False), "=": (0xBB, False), ",": (0xBC, False), "-": (0xBD, False), ".": (0xBE, False),
    "/": (0xBF, False), "`": (0xC0, False), "[": (0xDB, False), "\\": (0xDC, False), "]": (0xDD, False),
    "'": (0xDE, False),
}
KEYS.update({chr(c): (ord(chr(c).upper()), False) for c in range(ord("a"), ord("z") + 1)})
KEYS.update({str(d): (0x30 + d, False) for d in range(10)})
KEYS.update({f"num{d}": (0x60 + d, False) for d in range(10)})
KEYS.update({f"f{n}": (0x6F + n, False) for n in range(1, 25)})
ALIASES = {"control": "ctrl", "lctrl": "ctrl", "lshift": "shift", "lalt": "alt", "lwin": "win", "windows": "win",
           "super": "win", "cmd": "win", "escape": "esc", "return": "enter", "del": "delete", "ins": "insert",
           "pgup": "pageup", "pgdn": "pagedown", "apps": "menu", "prtsc": "printscreen", "minus": "-",
           "equals": "=", "comma": ",", "period": ".", "slash": "/", "backslash": "\\", "semicolon": ";",
           "quote": "'", "backquote": "`", "spacebar": "space", "bksp": "backspace", "caps": "capslock",
           "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right"}
# system:* -> media virtual key (sent without scan code); start_menu taps the Windows key.
SYSTEM_VK = {"mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF, "next_track": 0xB0, "previous_track": 0xB1,
             "stop": 0xB2, "play_pause": 0xB3}

PC_TEMPLATE = {
    "type": "pc",
    "name": "PC",
    "mouse": {
        "source": "gyro",
        "gyro_speed": 40.0,       # pixels per degree turned
        "gyro_deadzone": 3.0,     # °/s ignored (residual drift, hand tremor)
        "stick_speed": 1200.0,    # pixels per second at full Nunchuk stick / D-pad
        "stick_deadzone": 0.15,
        "ir_range": 0.5,          # fraction of the IR image that spans the whole screen
        "ir_smoothing": 0.5,      # 0 = raw IR, 0.9 = very smooth (and slower)
        # Gyro mouse: the quick calibration also puts the pointer in the centre of the
        # screen (the remote is recentred at the same time, so both line up again).
        "recenter_on_calibration": True,
    },
    "shake_g": 1.3,
    "buttons": {
        "wm_a": "mouse:left", "wm_b": "mouse:right",
        "wm_up": "keys:up", "wm_down": "keys:down", "wm_left": "keys:left", "wm_right": "keys:right",
        "wm_minus": "system:volume_down", "wm_plus": "system:volume_up", "wm_home": "system:start_menu",
        "wm_1": "keys:alt+tab", "wm_2": "system:play_pause",
        "nc_c": "mouse:middle", "nc_z": "keys:enter",
        "nc_up": "mouse:scroll_up", "nc_down": "mouse:scroll_down", "nc_left": "keys:alt+left",
        "nc_right": "keys:alt+right",
    },
}
MOUSE_LIMITS = {"gyro_speed": (1, 400), "gyro_deadzone": (0, 30), "stick_speed": (50, 10000),
                "stick_deadzone": (0, 0.9), "ir_range": (0.05, 1.0), "ir_smoothing": (0, 0.95)}


def key_codes(text):
    """'ctrl+shift+esc' -> [(vk, extended), ...] in order; raises ValueError."""
    names = [part.strip().lower() for part in text.split("+")]
    if not names or any(not n for n in names):
        raise ValueError(f"Invalid key combination: {text!r}")
    names = [ALIASES.get(n, n) for n in names]
    unknown = [n for n in names if n not in KEYS]
    if unknown:
        raise ValueError(f"Unknown key: {unknown[0]!r}")
    if len(set(names)) != len(names):
        raise ValueError(f"Repeated key in {text!r}")
    return [KEYS[n] for n in names]


def parse_action(text, allow_toggle=True):
    """Action string -> (kind, value); raises ValueError. See the module docstring."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Empty action")
    kind, _, value = text.strip().partition(":")
    kind = kind.strip().lower()
    if kind not in ACTION_TYPES:          # a bare combination is keys
        kind, value = "keys", text.strip()
    value = value.strip()
    if kind == "keys":
        return kind, key_codes(value)
    if kind == "mouse":
        if value not in MOUSE_ACTIONS:
            raise ValueError(f"mouse action must be one of {', '.join(MOUSE_ACTIONS)}")
        return kind, value
    if kind == "system":
        if value not in SYSTEM_ACTIONS:
            raise ValueError(f"system action must be one of {', '.join(SYSTEM_ACTIONS)}")
        return kind, value
    if kind == "open":
        if not value:
            raise ValueError("open: needs a program, file or web address")
        return kind, value
    if not allow_toggle:
        raise ValueError("A toggle step cannot be another toggle")
    steps = [parse_action(step, allow_toggle=False) for step in value.split("|")]
    if len(steps) < 2:
        raise ValueError("toggle: needs at least two steps separated by |")
    return kind, steps


def normalize_action(text):
    """Validated action string as stored ("keys:" prefix added to bare keys)."""
    kind, _ = parse_action(text)
    stripped = text.strip()
    if kind == "keys" and not stripped.lower().startswith("keys:"):
        return "keys:" + stripped
    if kind == "toggle":
        steps = [s.strip() for s in stripped.partition(":")[2].split("|")]
        return "toggle:" + " | ".join(steps)
    return stripped


def validate_pc_template(template: dict) -> dict:
    result = copy.deepcopy(PC_TEMPLATE)
    result["name"] = str(template.get("name") or "PC")[:40]
    mouse = dict(result["mouse"], **(template.get("mouse") or {}))
    if mouse["source"] is not None and mouse["source"] not in MOUSE_SOURCES:
        raise ValueError(f"mouse source must be one of {', '.join(MOUSE_SOURCES)} or null")
    for key, (low, high) in MOUSE_LIMITS.items():
        value = mouse[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise ValueError(f"mouse {key} must be {low}..{high}")
        mouse[key] = float(value)
    if not isinstance(mouse["recenter_on_calibration"], bool):
        raise ValueError("mouse recenter_on_calibration must be true or false")
    result["mouse"] = {k: mouse[k] for k in PC_TEMPLATE["mouse"]}
    shake = template.get("shake_g", PC_TEMPLATE["shake_g"])
    if isinstance(shake, bool) or not isinstance(shake, (int, float)) or not 0.2 <= shake <= 6:
        raise ValueError("shake_g must be 0.2..6")
    result["shake_g"] = float(shake)
    buttons = template.get("buttons", PC_TEMPLATE["buttons"])
    unknown = set(buttons) - set(PC_SOURCES)
    if unknown:
        raise ValueError(f"Unknown input: {', '.join(sorted(unknown))}")
    claimed = set(MOUSE_CLAIMS.get(mouse["source"], ()))
    result["buttons"] = {}
    for source in PC_SOURCES:
        action = buttons.get(source)
        if action in (None, ""):
            result["buttons"][source] = None
            continue
        if source in claimed:
            raise ValueError(f"{source} drives the mouse and cannot also be mapped")
        try:
            result["buttons"][source] = normalize_action(action)
        except ValueError as exc:
            raise ValueError(f"{source}: {exc}") from None
    return result


def pc_problems(template, capabilities):
    """Inputs the remote lacks: 'source: action (needs nunchuk)'."""
    problems = []
    mouse = template["mouse"]["source"]
    need = {"gyro": "motionplus", "ir": "ir", "nc_stick": "nunchuk"}.get(mouse)
    if need and not capabilities.get(need):
        problems.append(f"mouse: {mouse} (needs {need})")
    if not capabilities.get("nunchuk"):
        problems += [f"{s}: {a} (needs nunchuk)" for s, a in template["buttons"].items()
                     if a and s.startswith("nc_")]
    return problems


class PcEngine:
    """One per remote while a PC mode is active: turns its inputs into mouse and
    keyboard events on `output` (winput.WindowsInput or a test double)."""

    UNSEEN = object()

    def __init__(self, output):
        self.output = output
        self.down = set()            # inputs currently pressed (as this engine saw them)
        self.ignored = None          # held when the mode started; ignored until released
        self.held = {}               # input -> what to release: ("keys", codes) | ("mouse", button)
        self.toggles = {}            # input -> next step index
        self.scroll = {}             # input -> (delta, next repeat time)
        self.deferred = set()        # the modifier: its action fires on release
        self.pending = {}            # members of a two-button modifier waiting for each other
        self.wm_shake, self.nc_shake = ShakeDetector(), ShakeDetector()
        self.last_t = None
        self.carry = [0.0, 0.0]      # sub-pixel remainders of relative motion
        self.dpad_since = None
        self.ir_pos = None
        self.recenter_seq = self.UNSEEN   # last quick calibration seen (recenter_seq)

    # -- inputs -----------------------------------------------------------------
    def inputs(self, state, pressed, template, t):
        active = set(pressed)
        stick = (state.get("nunchuk") or {}).get("stick")
        if stick:
            x, y = stick
            for name, on in (("nc_right", x > STICK_THRESHOLD), ("nc_left", x < -STICK_THRESHOLD),
                             ("nc_up", y > STICK_THRESHOLD), ("nc_down", y < -STICK_THRESHOLD)):
                if on:
                    active.add(name)
        thresholds = [template["shake_g"]] * len(SHAKE_AXES)
        active |= {f"wm_shake_{a}" for a in self.wm_shake.update(state.get("accel_g"), t, thresholds)
                   if a in SHAKE_AXES}
        raw = (state.get("nunchuk") or {}).get("accel_raw")
        nc = [(v - 512) / 200.0 for v in raw] if raw else None
        active |= {f"nc_shake_{a}" for a in self.nc_shake.update(nc, t, thresholds) if a in SHAKE_AXES}
        return active

    def update(self, state, pressed, template, modifier, t):
        """`pressed`: the remote's buttons now (mode-switch arrows already removed)."""
        active = self.inputs(state, pressed, template, t)
        if self.ignored is None:
            self.ignored = set(active)            # e.g. B + ↓ that just selected this mode
        self.ignored &= active
        claimed = set(MOUSE_CLAIMS.get(template["mouse"]["source"], ()))
        active -= self.ignored | claimed
        actions = template["buttons"]
        members = modifier.split("+") if "+" in modifier else []
        if members and all(m in active for m in members):      # the A + B gesture: no clicks
            self.ignored |= set(members)
            active -= set(members)
            for m in members:
                self.pending.pop(m, None)
        for source, since in list(self.pending.items()):      # the partner did not come
            if source not in active:
                del self.pending[source]
                self.press(source, actions[source], t)         # a quick tap still acts
                self.release(source)
            elif t - since >= MODIFIER_WINDOW:
                del self.pending[source]
                self.press(source, actions[source], t)
        for source in sorted(active - self.down):             # newly pressed
            action = actions.get(source)
            if not action:
                continue
            if source == modifier:
                self.deferred.add(source)
            elif source in members:
                self.pending[source] = t
            else:
                self.press(source, action, t)
        for source in sorted(self.down - active):             # released
            if source in self.pending:
                continue                                       # handled above
            self.release(source)
            if source in self.deferred:
                self.deferred.discard(source)
                self.press(source, actions[source], t)
                self.release(source)
        self.down = active
        for source, (delta, when) in list(self.scroll.items()):
            if t >= when:
                self.output.wheel(delta)
                self.scroll[source] = (delta, t + SCROLL_REPEAT)
        self.move(state, pressed, template, t)

    def press(self, source, action, t):
        kind, value = parse_action(action)
        if kind == "toggle":
            index = self.toggles.get(source, 0)
            self.toggles[source] = (index + 1) % len(value)
            kind, value = value[index % len(value)]
        if kind == "keys":
            for vk, extended in value:
                self.output.key(vk, extended, True)
            self.held[source] = ("keys", value)
        elif kind == "mouse" and value in MOUSE_BUTTONS:
            self.output.button(value, True)
            self.held[source] = ("mouse", value)
        elif kind == "mouse":
            delta = 120 if value == "scroll_up" else -120
            self.output.wheel(delta)
            self.scroll[source] = (delta, t + SCROLL_DELAY)
        elif kind == "system":
            if value == "start_menu":
                self.output.key(*KEYS["win"], True)
                self.output.key(*KEYS["win"], False)
            else:
                self.output.media(SYSTEM_VK[value])
        elif kind == "open":
            self.output.launch(value)

    def release(self, source):
        self.scroll.pop(source, None)
        held = self.held.pop(source, None)
        if held is None:
            return
        kind, value = held
        if kind == "keys":
            for vk, extended in reversed(value):
                self.output.key(vk, extended, False)
        else:
            self.output.button(value, False)

    def release_all(self):
        """Mode change or disconnection: nothing may stay pressed."""
        for source in list(self.held):
            self.release(source)
        self.scroll.clear()
        self.deferred.clear()
        self.down = set()

    # -- mouse ------------------------------------------------------------------
    def move(self, state, pressed, template, t):
        mouse = template["mouse"]
        source = mouse["source"]
        seq = (state.get("calibration") or {}).get("recenter_seq")
        if self.recenter_seq is self.UNSEEN:
            self.recenter_seq = seq                      # entering the mode: just note it
        elif seq != self.recenter_seq:                   # a quick calibration happened
            self.recenter_seq = seq
            if source == "gyro" and mouse["recenter_on_calibration"]:
                self.carry = [0.0, 0.0]
                self.output.move_abs(0.5, 0.5)           # pointer back to the centre
                self.last_t = t
                return
        dt = 0.0 if self.last_t is None else max(0.0, min(0.05, t - self.last_t))
        self.last_t = t
        if source == "ir":
            stick = ir_stick(state.get("ir"), mouse["ir_range"])
            if stick is None:
                return                                         # bar out of sight: stay put
            target = (0.5 + stick[0] / 2, 0.5 - stick[1] / 2)
            keep = mouse["ir_smoothing"]
            if self.ir_pos is not None:
                target = tuple(p * keep + q * (1 - keep) for p, q in zip(self.ir_pos, target))
            self.ir_pos = target
            self.output.move_abs(*target)
            return
        dx = dy = 0.0
        if source == "gyro" and state.get("gyro_dps"):
            yaw, _roll, pitch = state["gyro_dps"]
            soft = lambda v: math.copysign(max(0.0, abs(v) - mouse["gyro_deadzone"]), v)
            # Turning right (yaw -) moves right; tip up (pitch -) moves up (screen y down).
            dx, dy = -soft(yaw) * mouse["gyro_speed"] * dt, soft(pitch) * mouse["gyro_speed"] * dt
        elif source == "nc_stick":
            stick = (state.get("nunchuk") or {}).get("stick")
            if stick:
                x, y = stick
                magnitude = math.hypot(x, y)
                zone = mouse["stick_deadzone"]
                if magnitude > zone:
                    # Quadratic curve: fine control near the centre, full speed at the edge.
                    scale = ((min(1.0, magnitude) - zone) / (1 - zone)) ** 2 / magnitude
                    dx, dy = x * scale * mouse["stick_speed"] * dt, -y * scale * mouse["stick_speed"] * dt
        elif source == "wm_dpad":
            x = ("wm_right" in pressed) - ("wm_left" in pressed)
            y = ("wm_down" in pressed) - ("wm_up" in pressed)
            if x or y:
                self.dpad_since = self.dpad_since if self.dpad_since is not None else t
                ramp = min(1.0, 0.3 + (t - self.dpad_since) / 0.6)   # precise taps, fast holds
                dx, dy = x * ramp * mouse["stick_speed"] * dt, y * ramp * mouse["stick_speed"] * dt
            else:
                self.dpad_since = None
        self.carry[0] += dx
        self.carry[1] += dy
        step = [int(c) for c in self.carry]                    # whole pixels; keep the rest
        if step[0] or step[1]:
            self.carry = [c - s for c, s in zip(self.carry, step)]
            self.output.move(*step)
