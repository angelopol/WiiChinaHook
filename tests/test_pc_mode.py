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

    def center(self):
        self.events.append(("center",))

    def launch(self, target):
        self.events.append(("launch", target))

    def take(self, kind=None):
        out = [e for e in self.events if kind is None or e[0] == kind]
        self.events = [e for e in self.events if not (kind is None or e[0] == kind)]
        return out


def template(**buttons):
    # The A + B mouse gesture has its own test; off here so A and B act at once.
    t = {"type": "pc", "mouse": {"source": None, "ab_action": None}, "buttons": buttons}
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


def test_two_button_modifier_pressed_together_does_not_click():
    out = FakeOutput()
    tpl = template(wm_a="mouse:left", wm_b="mouse:right")
    engine = PcEngine(out)
    step = lambda t, pressed: engine.update(snap(t), set(pressed), tpl, "wm_a+wm_b", t)
    step(0.00, set())
    step(0.01, {"wm_a"})
    step(0.03, {"wm_a", "wm_b"})                                   # B 20 ms later: the gesture
    step(0.20, {"wm_a", "wm_b"})
    step(0.30, set())
    assert out.take() == []                                        # no left or right click
    step(0.40, {"wm_a"})                                           # A alone: clicks after the wait
    step(0.48, {"wm_a"})
    assert out.take() == [("button", "left", True)]
    step(0.60, set())
    assert out.take() == [("button", "left", False)]
    step(0.70, {"wm_b"})                                           # a quick tap of B still clicks
    step(0.72, set())
    assert out.take() == [("button", "right", True), ("button", "right", False)]


def test_quick_calibration_recentres_the_gyro_mouse():
    out = FakeOutput()
    tpl = validate_template({"type": "pc", "mouse": {"source": "gyro"}, "buttons": {}})
    assert tpl["mouse"]["recenter_on_calibration"] is True             # on by default
    engine = PcEngine(out)
    calibrated = lambda t, seq: dict(snap(t, gyro=(0.0, 0.0, 0.0)), calibration={"recenter_seq": seq})
    engine.update(calibrated(0.0, 3), set(), tpl, "wm_b", 0.0)         # entering the mode: no jump
    assert out.take("center") == []
    engine.update(calibrated(0.1, 4), set(), tpl, "wm_b", 0.1)         # quick calibration fired
    assert out.take("center") == [("center",)]
    engine.update(calibrated(0.2, 4), set(), tpl, "wm_b", 0.2)
    assert out.take("center") == []                                        # once per calibration
    off = validate_template({"type": "pc", "mouse": {"source": "gyro", "recenter_on_calibration": False},
                             "buttons": {}})
    engine = PcEngine(out)
    engine.update(calibrated(0.0, 1), set(), off, "wm_b", 0.0)
    engine.update(calibrated(0.1, 2), set(), off, "wm_b", 0.1)
    assert out.take("center") == []                                        # switched off
    stick = validate_template({"type": "pc", "mouse": {"source": "nc_stick"}, "buttons": {}})
    engine = PcEngine(out)
    engine.update(calibrated(0.0, 1), set(), stick, "wm_b", 0.0)
    engine.update(calibrated(0.1, 2), set(), stick, "wm_b", 0.1)
    assert out.take("center") == []                                        # only the gyro mouse
    with pytest.raises(ValueError):
        validate_template({"type": "pc", "mouse": {"recenter_on_calibration": "yes"}, "buttons": {}})


def test_pc_game_mode_is_for_games_only():
    from wiichinahook.gamepad.pc import PC_GAME_TEMPLATE
    tpl = validate_template(PC_GAME_TEMPLATE)
    assert tpl["type"] == "pc_game" and tpl["buttons"]["nc_up"] == "keys:w" and tpl["buttons"]["wm_b"] == "mouse:left"
    assert tpl["mouse"]["source"] == "gyro" and tpl["mouse"]["recenter_on_calibration"] is False
    game = {"type": "pc_game", "mouse": {"source": "gyro"}}
    for bad in ({"buttons": {"wm_a": "system:mute"}}, {"buttons": {"wm_a": "open:notepad"}},
                {"buttons": {"wm_a": "toggle:keys:1 | system:mute"}}, {"mouse": {"source": "ir"}}):
        with pytest.raises(ValueError):
            validate_template(dict(game, **bad))
    forced = validate_template({"type": "pc_game", "mouse": {"source": "gyro", "recenter_on_calibration": True}})
    assert forced["mouse"]["recenter_on_calibration"] is False       # never warps a game camera
    assert validate_config(None)["modes"][3]["type"] == "pc_game"    # mode 4 by default


def test_pc_game_trigger_fires_at_once_and_stays_held():
    out = FakeOutput()
    tpl = validate_template({"type": "pc_game", "mouse": {"source": None}, "buttons": {"wm_b": "mouse:left"}})
    engine = PcEngine(out)
    engine.update(snap(0.0), set(), tpl, "wm_b", 0.0)
    engine.update(snap(0.01), {"wm_b"}, tpl, "wm_b", 0.01)           # B is the modifier and the trigger
    assert out.take() == [("button", "left", True)]                  # fires at once (no wait for release)
    engine.update(snap(0.5), {"wm_b"}, tpl, "wm_b", 0.5)
    assert out.take() == []                                           # held: automatic fire keeps going
    engine.update(snap(0.6), set(), tpl, "wm_b", 0.6)
    assert out.take() == [("button", "left", False)]


async def test_hub_runs_pc_game_like_pc_mode():
    out = FakeOutput()
    hub = GamepadHub(None, pc_output=out, loop=asyncio.get_running_loop())
    hub.set_mode(4)
    assert hub.mode_type == "pc_game" and hub.pads == {}
    s = WiimoteState("02:00:44:42:00:00", 0, True)
    s.capabilities = {"buttons": True, "accelerometer": True, "ir": True, "motionplus": True, "nunchuk": True}
    s.accel_g, s.nunchuk = (0.0, 0.0, 1.0), {"stick": [0.0, 0.95], "c": False, "z": False, "accel_raw": [512, 512, 712]}
    s.timestamp_us = 0
    hub.update(s)                                                    # stick already pushed: ignored at start
    s.nunchuk = dict(s.nunchuk, stick=[0.0, 0.0]); s.timestamp_us = 10_000
    hub.update(s)
    s.nunchuk = dict(s.nunchuk, stick=[0.0, 0.95]); s.timestamp_us = 20_000
    hub.update(s)
    assert ("key", KEYS["w"][0], True) in out.events                 # Nunchuk forward = W
    hub.close()


def swing_pixels(freeze, kind="pc_game"):
    """Aim, then a melee swing (fast turn + jolt) and its recoil, in continuous 5 ms
    reports; returns (pixels moved by the swing, events)."""
    out = FakeOutput()
    tpl = validate_template({"type": kind, "mouse": {"source": "gyro", "gyro_deadzone": 0,
                                                     "freeze_on_shake": freeze},
                             "buttons": {"wm_shake_y": "keys:v"}})
    engine = PcEngine(out)
    t = 0.0
    def step(gyro, accel=(0.0, 0.0, 1.0)):
        nonlocal t
        engine.update(dict(snap(t, gyro=gyro), accel_g=accel), set(), tpl, "wm_b", t)
        t += 0.005
    for _ in range(20):
        step((-20.0, 0.0, 0.0))                                   # aiming
    aimed = sum(e[1] for e in out.take("move"))
    for i in range(10):                                          # the swing: speeds up, then the jolt
        step((-150.0 if i < 3 else -600.0, 0.0, 250.0), (0.0, 2.5, 1.0) if i in (6, 7) else (0.0, 0.0, 1.0))
    for _ in range(20):
        step((200.0, 0.0, -150.0))                                # recoil after the hit
    swing = sum(abs(e[1]) + abs(e[2]) for e in out.take("move"))
    t += 0.35
    for _ in range(5):
        step((-20.0, 0.0, 0.0))                                   # aiming again
    return aimed, swing, sum(e[1] for e in out.take("move")), out


@pytest.mark.parametrize("kind", ["pc", "pc_game"])
def test_a_wiimote_shake_does_not_spin_the_gyro_aim(kind):
    tpl = validate_template({"type": kind, "mouse": {"source": "gyro"}, "buttons": {}})
    assert tpl["mouse"]["freeze_on_shake"] is True and tpl["mouse"]["freeze_dps"] == 300   # on by default
    aimed, swing, after, out = swing_pixels(freeze=True, kind=kind)
    _, unfrozen, _, _ = swing_pixels(freeze=False, kind=kind)
    assert aimed > 0 and after > 0                                # aiming works before and after
    assert unfrozen > 2500 and swing < 0.1 * unfrozen            # the hit barely moves the aim
    assert ("key", KEYS["v"][0], True) in out.events             # and the melee key still fires


def test_pc_game_runs_by_shaking_the_nunchuk():
    from wiichinahook.gamepad.pc import PC_GAME_TEMPLATE
    tpl = validate_template(PC_GAME_TEMPLATE)
    assert {tpl["buttons"][f"nc_shake_{a}"] for a in "xyz"} == {"keys:shift"} and tpl["buttons"]["wm_2"] == "keys:shift"


SETTLE_GAP = 0.35


def test_a_plus_b_recentres_the_pointer_or_pauses_the_gyro():
    out = FakeOutput()
    tpl = validate_template({"type": "pc", "mouse": {"source": "gyro", "gyro_deadzone": 0},
                             "buttons": {"wm_a": "mouse:left", "wm_b": "mouse:right"}})
    assert tpl["mouse"]["ab_action"] == "center"                     # PC default
    engine = PcEngine(out)
    step = lambda t, pressed, gyro=(0.0, 0.0, 0.0): engine.update(snap(t, gyro=gyro), set(pressed), tpl, "wm_b", t)
    step(0.00, set())
    step(0.01, {"wm_a"})
    step(0.03, {"wm_a", "wm_b"})                                    # together (20 ms apart)
    step(0.20, {"wm_a", "wm_b"})
    step(0.30, set())
    assert out.take() == [("center",)]                              # centred once, no clicks
    step(0.40, {"wm_a"})
    step(0.50, {"wm_a"})
    step(0.55, set())
    assert out.take() == [("button", "left", True), ("button", "left", False)]   # A alone still clicks

    game = validate_template({"type": "pc_game", "mouse": {"gyro_deadzone": 0},
                              "buttons": {"wm_a": "keys:e", "wm_b": "mouse:left"}})
    assert game["mouse"]["ab_action"] == "regrip"                  # PC Game default
    engine = PcEngine(out)
    gstep = lambda t, pressed, gyro: engine.update(snap(t, gyro=gyro), set(pressed), game, "wm_b", t)
    gstep(0.00, set(), (0.0, 0.0, 0.0))
    gstep(0.01, {"wm_b"}, (0.0, 0.0, 0.0))
    assert out.take() == [("button", "left", True)]                # the trigger never waits
    gstep(0.02, set(), (0.0, 0.0, 0.0))
    out.take()
    gstep(0.10, {"wm_a"}, (0.0, 0.0, 0.0))
    gstep(0.11, {"wm_a", "wm_b"}, (0.0, 0.0, 0.0))                 # A + B: re-grip
    for i in range(20):                                            # re-pointing the remote: no aim
        gstep(0.12 + i * 0.005, {"wm_a", "wm_b"}, (-200.0, 0.0, 100.0))
    assert out.take() == []                                         # no shot, no use, no movement
    gstep(0.30, set(), (0.0, 0.0, 0.0))
    for i in range(5):
        gstep(0.31 + i * 0.005, set(), (-40.0, 0.0, 0.0))
    assert sum(e[1] for e in out.take("move")) > 0                 # released: aiming resumes
    with pytest.raises(ValueError):
        validate_template({"type": "pc", "mouse": {"ab_action": "spin"}})


def test_centre_of_a_monitor_in_desktop_coordinates():
    from wiichinahook.gamepad.winput import rect_center
    assert rect_center(0, 0, 1920, 1080) == (960, 540)
    assert rect_center(-2560, -300, 0, 1140) == (-1280, 420)      # a monitor left of the primary
    assert rect_center(1920, 0, 3840, 1080) == (2880, 540)         # a second monitor on the right


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows API")
def test_current_monitor_contains_the_cursor():
    import ctypes
    from wiichinahook.gamepad.winput import POINT, WindowsInput
    w = WindowsInput()                                             # read-only: the cursor is not moved
    left, top, right, bottom = w.current_monitor()
    point = POINT()
    w.user32.GetCursorPos(ctypes.byref(point))
    assert left <= point.x < right and top <= point.y < bottom


def shortcut_template(enabled=True, **buttons):
    return validate_template({"type": "pc", "mouse": {"source": None, "ab_action": None},
                              "buttons": buttons or {"wm_1": "keys:1", "wm_minus": "system:volume_down"},
                              "shortcuts_enabled": enabled,
                              "shortcuts": [{"inputs": ["wm_1", "wm_minus"], "action": "keys:ctrl+add+oemcomma"}]})


def test_super_shortcut_runs_its_own_keys_and_not_its_buttons():
    out = FakeOutput()
    tpl = shortcut_template()
    assert tpl["shortcuts"] == [{"inputs": ["wm_1", "wm_minus"], "action": "keys:ctrl+add+oemcomma"}]
    engine = PcEngine(out)
    run(engine, tpl, [(0.00, set()), (0.01, {"wm_1"}), (0.03, {"wm_1", "wm_minus"})])   # − 20 ms after 1
    assert out.take() == [("key", KEYS["ctrl"][0], True), ("key", KEYS["num_add"][0], True),
                          ("key", KEYS[","][0], True)]                       # held, in order
    run(engine, tpl, [(0.50, {"wm_1", "wm_minus"})])
    assert out.take() == []                                                 # still held, no repeats
    run(engine, tpl, [(0.60, {"wm_minus"}), (0.70, set())])                # 1 released first
    assert out.take() == [("key", KEYS[","][0], False), ("key", KEYS["num_add"][0], False),
                          ("key", KEYS["ctrl"][0], False)]                 # released; − never acted alone


def test_incomplete_or_disabled_shortcut_leaves_the_buttons_alone():
    out = FakeOutput()
    tpl = shortcut_template()
    engine = PcEngine(out)
    run(engine, tpl, [(0.00, set()), (0.01, {"wm_1"}), (0.03, {"wm_1"})])
    assert out.take() == []                                                 # 1 waits the 50 ms window
    run(engine, tpl, [(0.07, {"wm_1"})])
    assert out.take() == [("key", KEYS["1"][0], True)]                      # no partner: 1 acts alone
    run(engine, tpl, [(0.10, set())])
    out.take()
    off = shortcut_template(enabled=False)                                  # off by default too
    assert validate_template({"type": "pc"})["shortcuts_enabled"] is False
    engine = PcEngine(out)
    run(engine, off, [(0.00, set()), (0.01, {"wm_1"})])
    assert out.take() == [("key", KEYS["1"][0], True)]                      # disabled: no wait at all


def test_shortcut_validation():
    base = {"type": "pc", "mouse": {"source": "wm_dpad"}, "buttons": {}}
    for bad in ([{"inputs": ["wm_1"], "action": "keys:a"}],                          # one input
                [{"inputs": ["wm_1", "wm_1"], "action": "keys:a"}],                  # repeated
                [{"inputs": ["wm_1", "wm_up"], "action": "keys:a"}],                 # the D-pad moves the mouse
                [{"inputs": ["wm_1", "wm_2"], "action": "keys:nokey"}],              # bad action
                [{"inputs": ["wm_1", "wm_9"], "action": "keys:a"}]):                 # unknown input
        with pytest.raises(ValueError):
            validate_template(dict(base, shortcuts=bad))
    with pytest.raises(ValueError):                                                 # PC Game: no system keys
        validate_template({"type": "pc_game", "shortcuts": [{"inputs": "wm_1+wm_2", "action": "system:mute"}]})
    ok = validate_template(dict(base, shortcuts=[{"inputs": "wm_1+nc_c+wm_shake_x", "action": "oem_period"}]))
    assert ok["shortcuts"][0] == {"inputs": ["wm_1", "nc_c", "wm_shake_x"], "action": "keys:oem_period"}


def three_button(inputs, buttons, ab_action=None):
    return validate_template({"type": "pc", "mouse": {"source": None, "ab_action": ab_action},
                              "buttons": buttons, "shortcuts_enabled": True,
                              "shortcuts": [{"inputs": inputs, "action": "keys:f9"}]})


def test_three_button_shortcut_pressed_one_after_another():
    out = FakeOutput()
    tpl = three_button(["wm_1", "wm_2", "wm_minus"], {"wm_1": "keys:1", "wm_2": "keys:2", "wm_minus": "keys:3"})
    engine = PcEngine(out)
    run(engine, tpl, [(0.00, set()), (0.01, {"wm_1"}), (0.045, {"wm_1", "wm_2"}),
                      (0.09, {"wm_1", "wm_2", "wm_minus"})])            # 80 ms from first to last
    assert out.take() == [("key", KEYS["f9"][0], True)]                 # only the shortcut, no 1 or 2
    run(engine, tpl, [(0.5, set())])
    assert out.take() == [("key", KEYS["f9"][0], False)]


def test_three_button_shortcut_containing_a_plus_b():
    out = FakeOutput()
    tpl = three_button(["wm_a", "wm_b", "wm_1"], {"wm_a": "mouse:left", "wm_b": "mouse:right"}, ab_action="center")
    engine = PcEngine(out)
    run(engine, tpl, [(0.00, set()), (0.01, {"wm_a", "wm_b"}), (0.04, {"wm_a", "wm_b", "wm_1"})])
    assert out.take() == [("key", KEYS["f9"][0], True)]                 # not swallowed by A + B
    run(engine, tpl, [(0.3, set()), (0.4, {"wm_a", "wm_b"}), (0.5, {"wm_a", "wm_b"})])
    assert out.take() == [("key", KEYS["f9"][0], False), ("center",)]  # A + B alone still recentres


def test_overlapping_shortcuts_1_2_and_1_2_minus():
    out = FakeOutput()
    tpl = validate_template({"type": "pc", "mouse": {"source": None, "ab_action": None},
                             "buttons": {"wm_1": "keys:1", "wm_2": "keys:2", "wm_minus": "keys:3"},
                             "shortcuts_enabled": True,
                             "shortcuts": [{"inputs": ["wm_1", "wm_2"], "action": "keys:f8"},
                                           {"inputs": ["wm_1", "wm_2", "wm_minus"], "action": "keys:f9"}]})
    f8, f9 = KEYS["f8"][0], KEYS["f9"][0]
    engine = PcEngine(out)                                              # 1, 2, then − within the window
    run(engine, tpl, [(0.00, set()), (0.01, {"wm_1"}), (0.03, {"wm_1", "wm_2"}),
                      (0.06, {"wm_1", "wm_2", "wm_minus"}), (0.3, {"wm_1", "wm_2", "wm_minus"}), (0.4, set())])
    assert out.take() == [("key", f9, True), ("key", f9, False)]       # only 1 + 2 + −: no F8, no 3
    engine = PcEngine(out)                                              # − arrives late: 1 + 2 grows into it
    run(engine, tpl, [(0.00, set()), (0.01, {"wm_1", "wm_2"}), (0.2, {"wm_1", "wm_2"}),
                      (0.3, {"wm_1", "wm_2", "wm_minus"}), (0.5, set())])
    assert out.take() == [("key", f8, True), ("key", f8, False), ("key", f9, True), ("key", f9, False)]
    engine = PcEngine(out)                                              # 1 + 2 alone
    run(engine, tpl, [(0.00, set()), (0.01, {"wm_1", "wm_2"}), (0.2, {"wm_1", "wm_2"}), (0.3, set())])
    assert out.take() == [("key", f8, True), ("key", f8, False)]


def test_quick_tap_of_a_shortcut_inside_a_longer_one():
    """1 + 2 tapped shorter than the window (300 ms, as in the user's config) while
    1 + 2 + − exists: the 1 + 2 shortcut, never the 1 and 2 buttons."""
    out = FakeOutput()
    tpl = validate_template({"type": "pc", "mouse": {"source": None, "ab_action": None},
                             "buttons": {"wm_1": "keys:1", "wm_2": "keys:2", "wm_minus": "keys:3"},
                             "shortcuts_enabled": True, "shortcut_window_ms": 300,
                             "shortcuts": [{"inputs": ["wm_1", "wm_2"], "action": "keys:f8"},
                                           {"inputs": ["wm_1", "wm_2", "wm_minus"], "action": "keys:f9"}]})
    engine = PcEngine(out)
    t = 0.0
    def step(pressed, n=1):
        nonlocal t
        for _ in range(n):
            engine.update(snap(t), set(pressed), tpl, "wm_b", t)
            t += 0.005
    step(set(), 3); step({"wm_1"}, 3); step({"wm_1", "wm_2"}, 30); step({"wm_2"}, 2); step(set(), 80)
    keys = [e for e in out.events if e[0] == "key"]
    assert keys == [("key", KEYS["f8"][0], True), ("key", KEYS["f8"][0], False)]

