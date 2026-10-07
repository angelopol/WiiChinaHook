import asyncio

from wiichinahook.gamepad.xbox import GamepadHub
from wiichinahook.wiimote import WiimoteState

B, RIGHT, UP, ONE = 0x0004, 0x0200, 0x0800, 0x0002
CAPS = {"buttons": True, "accelerometer": True, "ir": True, "motionplus": True, "nunchuk": True}


class FakePad:
    created = []

    def __init__(self, on_rumble=None):
        self.sent, self.closed, self.on_rumble = [], False, on_rumble
        FakePad.created.append(self)

    def send(self, state):
        self.sent.append(state)

    def close(self):
        self.closed = True


def remote(slot, buttons=0, nunchuk=True, t=0.0):
    state = WiimoteState(f"02:00:44:42:00:0{slot}", slot)
    state.connected, state.buttons, state.timestamp_us = True, buttons, int(t * 1e6)
    state.capabilities = dict(CAPS, nunchuk=nunchuk)
    state.accel_g = (0.0, 0.0, 1.0)
    state.nunchuk = {"c": False, "z": False, "stick": [0.0, 0.0], "accel_raw": [512, 512, 712]} if nunchuk else None
    return state


async def make_hub():
    FakePad.created = []
    rumbles, changes = [], []
    async def rumble(slot, ms):
        rumbles.append((slot, ms))
    hub = GamepadHub(None, rumble=rumble, on_change=changes.append, pad_factory=FakePad,
                     loop=asyncio.get_running_loop())
    return hub, rumbles, changes


async def test_each_remote_gets_a_pad_and_one_maps_to_xbox_a():
    hub, _, _ = await make_hub()
    hub.update(remote(0, ONE))
    hub.update(remote(1))
    assert sorted(hub.pads) == [0, 1]
    assert "A" in hub.pads[0].sent[-1].buttons and not hub.pads[1].sent[-1].buttons
    hub.close()
    assert all(p.closed for p in FakePad.created)


async def test_modifier_arrow_switches_every_remote_and_rumbles_the_mode():
    hub, rumbles, changes = await make_hub()
    hub.update(remote(0))
    hub.update(remote(1, nunchuk=False))
    pads = dict(hub.pads)
    hub.update(remote(0, B))
    hub.update(remote(0, B | RIGHT))              # B + right = mode 2 (empty)
    assert hub.mode == 2 and hub.pads == {} and all(p.closed for p in pads.values())
    await asyncio.sleep(1.0)
    assert sorted(rumbles) == [(0, 120), (0, 120), (1, 120), (1, 120)]   # two pulses each
    rumbles.clear()
    hub.update(remote(0, 0))
    hub.update(remote(0, B))
    hub.update(remote(0, B | UP))                 # back to the game mode
    assert hub.mode == 1
    await asyncio.sleep(1.0)
    assert rumbles.count((0, 120)) == 1 and (1, 700) in rumbles and (0, 700) not in rumbles
    assert changes[-1]["problems"]["1"][0].startswith("LB: nc_c")
    hub.update(remote(1))
    assert 1 in hub.pads


async def test_game_rumble_reaches_the_wiimote_and_disconnect_removes_the_pad():
    hub, rumbles, _ = await make_hub()
    hub.update(remote(2))
    pad = hub.pads[2]
    pad.on_rumble(200, 0)          # ViGEm thread
    await asyncio.sleep(0.05)
    pad.on_rumble(0, 0)
    await asyncio.sleep(0.05)
    assert rumbles == [(2, 5000), (2, 0)]
    gone = remote(2)
    gone.connected = False
    hub.update(gone)
    assert pad.closed and hub.pads == {} and 2 not in hub.connected


async def test_missing_vigem_is_reported_not_fatal():
    def broken(on_rumble=None):
        raise OSError("ViGEmBus driver not installed")
    hub = GamepadHub(None, pad_factory=broken)
    hub.update(remote(0, ONE))
    hub.update(remote(0, ONE))
    assert hub.pads == {} and "ViGEm unavailable" in hub.status()["error"]


async def test_mode_switch_blinks_the_mode_led_on_every_remote():
    blinks = []
    async def blink(slot, mask):
        blinks.append((slot, mask))
    hub = GamepadHub(None, blink=blink, pad_factory=FakePad, loop=asyncio.get_running_loop())
    hub.update(remote(0))
    hub.update(remote(3))
    hub.set_mode(2)
    await asyncio.sleep(0.05)
    assert sorted(blinks) == [(0, 0x20), (3, 0x20)]
    hub.set_mode(4)
    await asyncio.sleep(0.05)
    assert (0, 0x80) in blinks and (3, 0x80) in blinks


async def test_session_blink_restores_the_player_led():
    from unittest.mock import AsyncMock
    from wiichinahook.session import WiimoteSession

    class Channel:
        psm, sink = 0x13, None
        def __init__(self):
            self.sent = []
        def on(self, *a):
            pass
        def write(self, data):
            self.sent.append(bytes(data))

    session = WiimoteSession(WiimoteState(), AsyncMock(), lambda s: None)
    channel = Channel()
    session.attach(channel)
    session.led_mask = 0x40                      # player LED 3
    await session.blink_led(0x20, times=2, period=0.01)
    leds = [d[2] for d in channel.sent if d[1] == 0x11]
    assert leds == [0x20, 0x00, 0x20, 0x00, 0x40]
    await session.close()


async def test_shakes_are_reported_with_their_strength_for_tuning():
    changes = []
    hub = GamepadHub(None, on_change=changes.append, pad_factory=FakePad)
    for i in range(20):
        state = remote(0, t=i / 100)
        state.accel_g = (0.0, 0.0, 1.0 + (2.0 if i == 10 else 0.0))
        hub.update(state)
    shakes = changes[-1]["shakes"]
    assert shakes["seq"] == 1 and shakes["by_slot"]["0"] == [{"device": "wm", "axis": "z", "g": 2.0}]


async def test_xbox_output_is_published_only_on_change():
    outputs = []
    hub = GamepadHub(None, on_output=outputs.append, pad_factory=FakePad)
    hub.update(remote(1, ONE))
    hub.update(remote(1, ONE))
    hub.update(remote(1))
    assert [o.get("buttons") for o in outputs] == [["A"], []] and outputs[0]["active"] is True
    hub.set_mode(3)                       # empty mode
    hub.update(remote(1))
    assert outputs[-1] == {"slot": 1, "active": False}


async def test_dsu_mode_has_no_xbox_pads_and_no_problems():
    hub, _, changes = await make_hub()
    hub.update(remote(0, nunchuk=False))
    assert 0 in hub.pads and not hub.dsu_active
    hub.set_mode(2)                                # default mode 2 is the DSU mode
    assert hub.dsu_active and hub.template is None and hub.pads == {}
    hub.update(remote(0, ONE, nunchuk=False))
    status = hub.status()
    assert hub.pads == {} and status["types"][:2] == ["xbox", "dsu"] and not status["problems"]
    hub.close()


def test_xbox_pad_skips_unchanged_updates():
    from types import SimpleNamespace
    from wiichinahook.gamepad.mapping import XboxState
    from wiichinahook.gamepad.xbox import XboxPad
    calls = []
    fake = SimpleNamespace(**{name: (lambda name: lambda **kw: calls.append(name))(name) for name in (
        "press_button", "release_button", "left_trigger_float", "right_trigger_float",
        "left_joystick_float", "right_joystick_float", "update")})
    pad = object.__new__(XboxPad)                    # no ViGEm device needed
    pad.vg = SimpleNamespace(XUSB_BUTTON=SimpleNamespace(XUSB_GAMEPAD_A=1))
    pad.pad, pad.pressed, pad.last = fake, set(), None
    state = XboxState()
    state.buttons.add("A")
    pad.send(state)
    pad.send(state)                                  # identical: no driver call
    assert calls.count("update") == 1
    state.rx = 0.0001                                # tiny gyro motion still goes out
    pad.send(state)
    assert calls.count("update") == 2 and calls.count("press_button") == 1


async def test_dsu_options_follow_the_dsu_mode_even_while_another_plays():
    hub = GamepadHub(None, pad_factory=FakePad)
    assert hub.mode == 1 and hub.dsu_options["nunchuk_server"] is True    # from mode 2 (DSU)
    hub.set_config({"version": 3, "mode": 1, "modes": [None, {"type": "dsu", "ir_server": False}, None, None]})
    assert hub.dsu_options["ir_server"] is False
    hub.set_config({"version": 3, "mode": 1, "modes": [None, None, None, None]})
    assert hub.dsu_options is None                                         # no DSU mode: extra servers off
    hub.close()


def test_startup_mode_fixed_or_last_active(tmp_path):
    from dataclasses import replace
    from wiichinahook.app import read_last_mode, save_last_mode, startup_gamepad
    from wiichinahook.config import AppConfig
    config = replace(AppConfig(), state_dir=tmp_path)
    assert startup_gamepad(config)["mode"] == 1                  # nothing saved yet: the config's
    save_last_mode(tmp_path, 3)
    assert read_last_mode(tmp_path) == 3 and startup_gamepad(config)["mode"] == 3   # last active
    fixed = replace(config, gamepad=dict(config.gamepad, startup_mode=2))
    assert startup_gamepad(fixed)["mode"] == 2                   # a fixed startup mode wins
    (tmp_path / "gamepad_mode.json").write_text("{broken", encoding="utf-8")
    assert read_last_mode(tmp_path) is None and startup_gamepad(config)["mode"] == 1
