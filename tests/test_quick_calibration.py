import asyncio
import json
import math
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from wiichinahook.api import ApiServer
from wiichinahook.config import AppConfig, SlotOptions, load_config, save_config
from wiichinahook.dolphinbar import DolphinBarManager
from wiichinahook.orientation import (OrientationFilter, from_axis_angle, multiply, reference_yaw, tilt_from_accel,
                                      yaw_of)
from wiichinahook.session import WiimoteSession
from wiichinahook.wiimote import WiimoteState


class Channel:
    psm = 0x13

    def __init__(self):
        self.sent, self.sink = [], None

    def on(self, *args):
        pass

    def write(self, data):
        self.sent.append(bytes(data))


def make_session(**options):
    session = WiimoteSession(WiimoteState(), AsyncMock(), lambda state: None)
    channel = Channel()
    session.attach(channel)
    session.initialized = True
    session.state.capabilities["motionplus"] = True
    session.apply_options(SlotOptions(**options))
    return session, channel


def buttons_report(mask):
    return bytes([0xA1, 0x30, mask >> 8, mask & 0xFF])


def rumbles(channel):
    return [d for d in channel.sent if d[1] == 0x10]


async def test_combo_must_be_held_and_fires_once(monkeypatch):
    session, _ = make_session(quick_calibration=True, combo="minus+plus")
    session.COMBO_HOLD = 0.05
    calls = []
    async def fake():
        calls.append(1)
    session.quick_calibrate = fake
    session.receive(buttons_report(0x1010))
    await asyncio.sleep(0.08)
    for _ in range(5):
        session.receive(buttons_report(0x1010))
        await asyncio.sleep(0.01)
    assert calls == [1]
    session.receive(buttons_report(0x0010))   # released (only minus)
    session.receive(buttons_report(0x1010))
    await asyncio.sleep(0.01)
    session.receive(buttons_report(0x1010))
    assert calls == [1]                          # pressed again but not held long enough yet
    await session.close()


async def test_combo_ignored_when_disabled():
    session, _ = make_session(quick_calibration=False, combo="home")
    session.COMBO_HOLD = 0.0
    session.quick_calibrate = AsyncMock()
    session.receive(buttons_report(0x0080))
    session.receive(buttons_report(0x0080))
    await asyncio.sleep(0.01)
    session.quick_calibrate.assert_not_called()
    await session.close()


@pytest.mark.parametrize("moving", [False, True])
async def test_quick_calibration_updates_bias_only_when_still(moving):
    session, channel = make_session(quick_calibration=True)
    session.parser.gyro_scale = (0.5, 1.0, 1.0)
    session.parser.orientation.q = multiply(from_axis_angle((0, 0, 1), 1.2), tilt_from_accel((0, 0, 1)))
    saved = []
    session.on_bias_changed = saved.append
    task = asyncio.create_task(session.quick_calibrate(still=0.2))
    await asyncio.sleep(0.35)  # past the first rumble, sampling now
    for i in range(30):
        session.gyro_samples.append((2.0 + (40 * (i % 2) if moving else 0), -1.0, 0.5))
    result = await task
    assert result["bias_updated"] is (not moving)
    assert abs(yaw_of(session.parser.orientation.q)) < 1e-6           # recentered either way
    assert session.state.calibration["recenter_seq"] == 1
    if moving:
        assert saved == [] and len(rumbles(channel)) >= 2               # start + long rumble
    else:
        assert saved == [(4.0, -1.0, 0.5)]                              # yaw bias corrected in nominal units
        assert session.parser.gyro_bias == (4.0, -1.0, 0.5)
    await session.close()


def test_ir_heading_pulls_drifted_yaw_back_to_the_bar():
    filt = OrientationFilter()
    filt.q = multiply(from_axis_angle((0, 0, 1), math.radians(40)), tilt_from_accel((0, 0, 1)))  # drifted
    for _ in range(200):
        filt.correct_heading(0.0)
    assert abs(math.degrees(yaw_of(filt.q))) < 1
    pointing_up = tilt_from_accel((0, -1, 0))
    filt.q = pointing_up
    assert filt.correct_heading(0.3) is False and filt.q == pointing_up  # not level: no IR heading


def test_parser_applies_ir_heading_only_when_enabled():
    from wiichinahook.wiimote import ReportParser
    parser = ReportParser()
    parser.extension = "motionplus"
    parser.orientation.q = multiply(from_axis_angle((0, 0, 1), math.radians(30)), tilt_from_accel((0, 0, 1)))
    # Basic IR (0x37): two dots centred on the image, i.e. pointing straight at the bar.
    def dot(x, y):
        return bytes([x & 0xFF, y & 0xFF, ((y >> 8) << 6) | ((x >> 8) << 4)])
    ir = dot(461, 380)[:2] + bytes([dot(461, 380)[2] | (dot(561, 380)[2] >> 4)]) + dot(561, 380)[:2] + bytes([0xFF] * 5)  # 3rd/4th dots invisible
    report = bytes([0xA1, 0x37, 0, 0, 0x80, 0x80, 0x9A]) + ir + b"\xff" * 6
    parser.feed(report)
    assert math.degrees(yaw_of(parser.orientation.q)) == pytest.approx(30)
    parser.ir_heading = True
    for _ in range(100):
        parser.feed(report)
    assert abs(math.degrees(yaw_of(parser.orientation.q))) < 3
    assert parser.state.calibration["heading"] == "ir"


def test_slot_options_round_trip_and_validation(tmp_path):
    path = tmp_path / "config.local.json"
    config = AppConfig()
    slots = list(config.slots)
    slots[1] = SlotOptions(True, "down", True)
    from dataclasses import replace
    save_config(replace(config, slots=tuple(slots)), path)
    loaded = load_config(path)
    assert loaded.slots[1] == SlotOptions(True, "down", True) and loaded.slots[0] == SlotOptions()
    data = json.loads(path.read_text())
    data["slots"][0]["combo"] = "shake"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="combo"):
        load_config(path)


async def test_live_slot_options_through_the_api(tmp_path):
    manager = DolphinBarManager(replace_state_dir(tmp_path), lambda s: None, devices=lambda: {})
    session = SimpleNamespace(state=WiimoteState(slot=2), apply_options=lambda o: applied.append(o))
    applied = []
    manager.sessions[2] = session
    api = ApiServer(manager)
    result = await api.dispatch("slot_options", {"slot": 2, "quick_calibration": True, "combo": "one+two"})
    assert result == {"slot": 2, "quick_calibration": True, "combo": "one+two", "ir_calibration": False}
    assert applied == [SlotOptions(True, "one+two", False)]
    with pytest.raises(ValueError, match="combo"):
        await api.dispatch("slot_options", {"slot": 2, "combo": "shake"})


def replace_state_dir(tmp_path):
    from dataclasses import replace
    return replace(AppConfig(), state_dir=tmp_path)
