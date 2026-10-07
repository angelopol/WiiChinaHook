import asyncio

import pytest

from wiichinahook.gamepad.mapping import validate_config, validate_template
from wiichinahook.gamepad.pc import KEYS, PC_TEMPLATE, PcEngine, normalize_action, parse_action
from wiichinahook.gamepad.xbox import GamepadHub
from wiichinahook.wiimote import WiimoteState

A, B, ONE, TWO, UP, DOWN, LEFT, RIGHT = 0x0008, 0x0004, 0x0002, 0x0001, 0x0800, 0x0400, 0x0100, 0x0200
VK = {name: KEYS[name][0] for name in ("ctrl", "shift", "alt", "9", "c", "v", "win", "up")}


class FakeOutput:
    """Records what would be injected; never touches the real keyboard or mouse."""

    def __init__(self):
        self.events = []

    def key(self, vk, extended, down):
        self.events.append(("key", vk, down))

    def media(self, vk):
        self.events.append(("media", vk))

    def button(self, name, down):
        self.events.append(("button", name, down))

    def wheel(self, delta):
        self.events.append(("wheel", delta))

    def move(self, dx, dy):
        self.events.append(("move", dx, dy))

    def move_abs(self, u, v):
        self.events.append(("abs", round(u, 3), round(v, 3)))

    def launch(self, target):
        self.events.append(("launch", target))

    def take(self, kind=None):
        out = [e for e in self.events if kind is None or e[0] == kind]
        self.events = [e for e in self.events if not (kind is None or e[0] == kind)]
        return out


def template(**buttons):
    t = {"type": "pc", "mouse": {"source": None}, "buttons": buttons}
    return validate_template(t)


def snap(t, gyro=None, stick=None, ir=None):
    return {"buttons": 0, "timestamp_us": int(t * 1e6), "accel_g": (0.0, 0.0, 1.0), "gyro_dps": gyro, "ir": ir,
            "nunchuk": {"stick": list(stick or (0.0, 0.0)), "c": False, "z": False, "accel_raw": [512, 512, 712]}}


def run(engine, tpl, frames):
    """frames: [(t, pressed set, extra snapshot kwargs)]"""
    for t, pressed, *extra in frames:
        engine.update(snap(t, **(extra[0] if extra else {})), set(pressed), tpl, "wm_b", t)


def test_action_syntax_and_validation():
    assert normalize_action("ctrl+9") == "keys:ctrl+9"
    assert normalize_action("toggle: ctrl+c |ctrl+v | system:mute") == "toggle:ctrl+c | ctrl+v | system:mute"
    kind, steps = parse_action("toggle:ctrl+c | mouse:left")
    assert kind == "toggle" and steps[1] == ("mouse", "left")
    many = "+".join(["ctrl", "shift", "alt", "win"] + list("abcdefghijklmnopqrstuvwxyz") + [f"f{n}" for n in range(1, 13)])
    assert len(parse_action(many)[1]) == 42                       # no limit but the keyboard itself
    assert parse_action("Escape+DEL")[1] == [KEYS["esc"], KEYS["delete"]]   # aliases, any case
    for bad in ("ctrl+", "ctrl+nokey", "a+a", "mouse:double", "system:shutdown", "open:", "toggle:a",
                "toggle:a | toggle:b|c", ""):
        with pytest.raises(ValueError):
            parse_action(bad)
    with pytest.raises(ValueError):                               # the D-pad drives the mouse
        validate_template({"type": "pc", "mouse": {"source": "wm_dpad"}, "buttons": {"wm_up": "keys:w"}})
    validate_template({"type": "pc", "mouse": {"source": "wm_dpad"}, "buttons": {"nc_up": "keys:w"}})
    assert validate_template(PC_TEMPLATE)["buttons"]["wm_a"] == "mouse:left"


def test_keys_are_held_while_the_button_is_held():
    out = FakeOutput()
    tpl = template(wm_a="ctrl+shift+9")
    engine = PcEngine(out)
    run(engine, tpl, [(0.00, set()), (0.01, {"wm_a"})])
    assert out.take() == [("key", VK["ctrl"], True), ("key", VK["shift"], True), ("key", VK["9"], True)]
    run(engine, tpl, [(0.02, {"wm_a"})])
    assert out.take() == []                                       # held: nothing repeated
    run(engine, tpl, [(0.03, set())])
    assert out.take() == [("key", VK["9"], False), ("key", VK["shift"], False), ("key", VK["ctrl"], False)]


def test_mouse_buttons_scroll_system_open_and_toggle():
    out = FakeOutput()
    tpl = template(wm_a="mouse:left", wm_1="system:mute", wm_2="open:https://example.com",
                   wm_minus="system:start_menu", wm_plus="toggle:ctrl+c | ctrl+v | system:play_pause",
                   nc_up="mouse:scroll_up")
    engine = PcEngine(out)
    run(engine, tpl, [(0.0, set()), (0.01, {"wm_a"}), (0.02, set())])
    assert out.take() == [("button", "left", True), ("button", "left", False)]
    run(engine, tpl, [(0.03, {"wm_1", "wm_2", "wm_minus"})])
    assert ("media", 0xAD) in out.events and ("launch", "https://example.com") in out.events
    assert ("key", VK["win"], True) in out.events and ("key", VK["win"], False) in out.events
    out.take()
    run(engine, tpl, [(0.04, set())])
    out.take()
    steps = []
    for i in range(4):                                            # each press = the next step
        run(engine, tpl, [(0.1 + i * 0.1, {"wm_plus"}), (0.15 + i * 0.1, set())])
        steps.append(out.take())
    assert steps[0][1] == ("key", VK["c"], True) and steps[1][1] == ("key", VK["v"], True)
    assert steps[2] == [("media", 0xB3)] and steps[3][1] == ("key", VK["c"], True)   # wraps around
    run(engine, tpl, [(1.0, set(), {"stick": (0.0, 0.9)})])       # Nunchuk stick up = a direction input
    assert out.take() == [("wheel", 120)]
    run(engine, tpl, [(1.2, set(), {"stick": (0.0, 0.9)}), (1.45, set(), {"stick": (0.0, 0.9)})])
    assert out.take() == [("wheel", 120)]                         # repeats after holding 0.4 s


def test_modifier_fires_on_release_and_held_inputs_are_ignored_at_start():
    out = FakeOutput()
    tpl = template(wm_b="mouse:right", wm_down="keys:down")
    engine = PcEngine(out)
    run(engine, tpl, [(0.0, {"wm_b", "wm_down"})])                # B + ↓ that selected this mode
    run(engine, tpl, [(0.05, set())])
    assert out.take() == []                                       # neither fires on release
    run(engine, tpl, [(0.1, {"wm_b"})])
    assert out.take() == []                                       # B waits: it may be a mode switch
    run(engine, tpl, [(0.2, set())])
    assert out.take() == [("button", "right", True), ("button", "right", False)]


def test_mouse_from_gyro_ir_and_dpad():
    out = FakeOutput()
    tpl = validate_template({"type": "pc", "mouse": {"source": "gyro", "gyro_speed": 40, "gyro_deadzone": 3},
                             "buttons": {}})
    engine = PcEngine(out)
    for i in range(101):                                          # 0.5 s turning right at 20 °/s
        engine.update(snap(i * 0.005, gyro=(-20.0, 0.0, 0.0)), set(), tpl, "wm_b", i * 0.005)
    moved = sum(e[1] for e in out.take("move"))
    assert moved == pytest.approx((20 - 3) * 40 * 0.5, abs=2)     # deadzone subtracted, then speed
    for i in range(20):                                           # drift under the deadzone: still
        engine.update(snap(1 + i * 0.005, gyro=(2.0, 0.0, -2.0)), set(), tpl, "wm_b", 1 + i * 0.005)
    assert out.take("move") == []

    tpl = validate_template({"type": "pc", "mouse": {"source": "ir", "ir_smoothing": 0}, "buttons": {}})
    engine = PcEngine(out)
    centre = [{"x": 461, "y": 384, "size": 2}, {"x": 562, "y": 384, "size": 2}, None, None]
    engine.update(snap(0, ir=centre), set(), tpl, "wm_b", 0)
    (kind, u, v), = out.take()
    assert kind == "abs" and u == pytest.approx(0.5, abs=0.002) and v == pytest.approx(0.5, abs=0.002)
    engine.update(snap(0.01, ir=[None] * 4), set(), tpl, "wm_b", 0.01)
    assert out.take() == []                                       # bar out of sight: stays

    tpl = validate_template({"type": "pc", "mouse": {"source": "wm_dpad", "stick_speed": 1000}, "buttons": {}})
    engine = PcEngine(out)
    for i in range(201):
        engine.update(snap(i * 0.005), {"wm_right"}, tpl, "wm_b", i * 0.005)
    moved = sum(e[1] for e in out.take("move"))
    assert 700 < moved < 1000                                     # ramps up, then full speed


async def test_hub_runs_pc_mode_and_releases_everything_on_mode_change_and_disconnect():
    out = FakeOutput()
    config = validate_config(None)
    config["modes"][2]["buttons"]["wm_1"] = "keys:ctrl+9"
    hub = GamepadHub(config, pc_output=out, loop=asyncio.get_running_loop())
    hub.set_mode(3)
    assert hub.mode_type == "pc" and hub.pads == {}

    def remote(slot, buttons, t):
        s = WiimoteState(f"02:00:44:42:00:0{slot}", slot, True)
        s.buttons, s.timestamp_us, s.accel_g = buttons, int(t * 1e6), (0.0, 0.0, 1.0)
        s.capabilities = {"buttons": True, "accelerometer": True, "ir": True, "motionplus": True, "nunchuk": False}
        return s

    for slot in range(4):
        hub.update(remote(slot, 0, 0.0))
    hub.update(remote(0, ONE, 0.01))
    hub.update(remote(1, ONE, 0.01))                              # two remotes hold their own keys
    assert out.take("key").count(("key", VK["9"], True)) == 2
    hub.update(remote(1, B, 0.02))                                # remote 2: B + → = mode 2
    hub.update(remote(1, B | RIGHT, 0.03))
    assert hub.mode == 2
    released = out.take("key")
    assert released.count(("key", VK["9"], False)) == 2 and released.count(("key", VK["ctrl"], False)) == 2
    assert ("button", "right", True) not in out.events             # B + arrow is not a right click
    hub.set_mode(3)
    hub.update(remote(2, 0, 0.1))
    hub.update(remote(2, ONE, 0.2))
    out.take()
    gone = WiimoteState("02:00:44:42:00:02", 2, False)
    hub.update(gone)                                               # disconnected mid-press
    assert ("key", VK["9"], False) in out.take("key")
    hub.close()
