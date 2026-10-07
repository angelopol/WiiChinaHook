import asyncio
import socket
from dataclasses import replace

import pytest

from wiichinahook.api import ApiServer
from wiichinahook.config import AppConfig, ApiConfig
from wiichinahook.gui.i18n import TEXT, Translator
from wiichinahook.gui.model import (bar_value, config_from_form, form_from_config, ir_to_canvas, led_mask,
                                    pressed_buttons, stick_to_canvas)
from wiichinahook.gui.service import ServiceRuntime
from wiichinahook.wiimote import WiimoteState


def test_every_language_has_every_key():
    for language, texts in TEXT.items():
        assert texts.keys() == TEXT["en"].keys(), language
    assert Translator("xx")("start") == "Start service"
    assert Translator("es")("slot", n=2) == "Slot 2"


def test_buttons_leds_and_canvas_mapping():
    assert pressed_buttons(0x0008 | 0x0800 | 0x0080) == {"a", "up", "home"}
    assert led_mask([True, False, False, True]) == 0x90
    # Camera X is mirrored: a dot at the camera's left edge is on the right of the canvas.
    assert ir_to_canvas([{"x": 0, "y": 0, "size": None}, None], 100, 75) == [(100.0, 0.0)]
    assert stick_to_canvas((0.0, 0.0), 80) == (40.0, 40.0)
    assert stick_to_canvas((1.0, 1.0), 80) == (80.0, 0.0)
    assert bar_value(None, 3) == 0.5 and bar_value(9, 3) == 1.0 and bar_value(-1.5, 3) == 0.25


def test_settings_form_round_trip_and_validation():
    base = replace(AppConfig(), mode="bluetooth")
    form = form_from_config(base)
    assert config_from_form(base, form) == base
    form.update(mode="dolphinbar", vid="0a12", pid="0x0001", transport=" ", dsu_port="26770", ir=False)
    config = config_from_form(base, form)
    assert (config.mode, config.dongle.vid, config.dongle.transport, config.dsu.port, config.ir) == \
        ("dolphinbar", 0x0A12, None, 26770, False)
    for key, value in (("dsu_port", "70000"), ("api_port", "26770"), ("vid", "zz"), ("mode", "usb"), ("dsu_host", " ")):
        with pytest.raises(ValueError, match=key.split("_")[0] if key != "vid" else "vid"):
            config_from_form(base, dict(form, **{key: value}))


class FakeManager:
    def __init__(self):
        self.stopping = False
        self.calls = []

    def snapshot(self):
        return {"adapter": "fake", "mode": "dolphinbar", "ready": True, "error": None, "pairing": False,
                "devices": [WiimoteState("02:00:44:42:00:00", 0).to_dict()]}

    def session_for(self, slot):
        raise ValueError("Slot is not connected")

    async def calibrate(self, slot):
        self.calls.append(("calibrate", slot))
        return {"gyro_bias": [0, 0, 0]}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def fake_runner(manager):
    async def runner(config):
        api = await ApiServer(manager, config.api.host, config.api.port).start()
        try:
            await asyncio.Event().wait()
        finally:
            await api.close()
    return runner


async def test_runtime_runs_in_process_and_stops_cleanly():
    config = replace(AppConfig(), api=ApiConfig("127.0.0.1", free_port()))
    states, statuses, manager = [], [], FakeManager()
    runtime = ServiceRuntime(states.append, lambda s, e: statuses.append(s), runner=fake_runner(manager))
    await runtime.start(config)
    assert runtime.status == "running" and statuses[:2] == ["starting", "running"]
    assert states and states[0]["slot"] == 0  # snapshot delivered on subscribe
    assert (await runtime.snapshot())["mode"] == "dolphinbar"
    assert await runtime.request("calibrate", slot=0) == {"gyro_bias": [0, 0, 0]}
    with pytest.raises(Exception, match="not connected"):
        await runtime.request("rumble", slot=0, duration_ms=10)
    await runtime.stop()
    assert runtime.status == "stopped" and runtime.task is None


async def test_runtime_attaches_when_the_ports_are_taken():
    config = replace(AppConfig(), api=ApiConfig("127.0.0.1", free_port()))
    manager = FakeManager()
    external = asyncio.create_task(fake_runner(manager)(config))  # e.g. `wiichinahook hook` from the CLI
    await asyncio.sleep(0.2)
    def runner(config):
        async def busy():
            raise OSError(10048, "address in use")
        return busy()
    runtime = ServiceRuntime(lambda s: None, lambda s, e: None, runner=runner)
    await runtime.start(config)
    assert runtime.status == "attached"
    await runtime.stop()
    external.cancel()
    await asyncio.gather(external, return_exceptions=True)


async def test_runtime_reports_start_errors():
    async def broken(config):
        raise RuntimeError("DolphinBar exploded")
    runtime = ServiceRuntime(lambda s: None, lambda s, e: None, runner=broken)
    await runtime.start(AppConfig())
    assert runtime.status == "error" and "DolphinBar exploded" in runtime.error


def test_slot_card_renders_live_and_empty_states():
    ft = pytest.importorskip("flet")
    from wiichinahook.gui.app import SlotCard
    card = SlotCard(1, Translator("en"), controller=None)
    state = WiimoteState("02:00:44:42:00:01", 1).to_dict()
    state.update(connected=True, phase="ready", buttons=0x0008, battery=0.5, accel_g=[0.0, 0.1, 1.0],
                 gyro_dps=[5.6, -4.7, 11.2], extension="motionplus+nunchuk",
                 ir=[{"x": 500, "y": 300, "size": None}, None, None, None],
                 nunchuk={"stick": [0.5, -0.5], "c": True, "z": False, "accel_raw": [512, 712, 412]},
                 calibration={"accelerometer": "typical"})
    card.render(state)
    assert card.buttons["a"].bgcolor == ft.Colors.PRIMARY and card.buttons["b"].bgcolor != ft.Colors.PRIMARY
    assert card.nunchuk_buttons["c"].bgcolor == ft.Colors.PRIMARY
    assert card.accel_labels[2].value == "+1.00" and len(card.ir_canvas.shapes) == 1
    assert len(card.stick_canvas.shapes) == 2 and not card.action_controls[0].disabled
    # Uncalibrated Nunchuk accelerometer shown as approximate g: (raw - 512) / 200.
    assert [label.value for label in card.nc_labels] == ["+0.00", "+1.00", "-0.50"]
    assert card.nc_accel_title.value.endswith("≈")
    card.render(None)
    assert card.action_controls[0].disabled and card.ir_canvas.shapes == []


def test_wiimote3d_visible_faces_follow_orientation():
    import math
    from wiichinahook.gui.wiimote3d import IR_WINDOW, project
    from wiichinahook.orientation import from_axis_angle, tilt_from_accel
    flat = project((1, 0, 0, 0), 200, 150)
    assert len(flat) == 2 + 5  # top + back faces, plus D-pad (2), A, 1, 2 on top
    xs = [x for points, _ in flat for x, _ in points]
    assert 0 < min(xs) and max(xs) < 200  # fits the canvas
    dark = lambda polys: any(color == "#%02x%02x%02x" % tuple(int(c * 0.42) for c in IR_WINDOW) or
                             int(color[1:3], 16) < 60 for _, color in polys)
    assert not dark(flat)
    assert dark(project(tilt_from_accel((0, -1, 0)), 200, 150))  # pointing at the ceiling: IR window shows
    rolled = project(from_axis_angle((0, 1, 0), math.radians(60)), 200, 150)
    assert len(rolled) >= 3


def test_scale_dialog_builds_three_axis_steps():
    pytest.importorskip("flet")
    from types import SimpleNamespace
    from wiichinahook.gui.app import SlotCard
    shown = []
    controller = SimpleNamespace(page=SimpleNamespace(show_dialog=shown.append, pop_dialog=lambda: None,
                                                      update=lambda: None))
    card = SlotCard(0, Translator("es"), controller=controller)
    card.on_scale(None)
    [dialog] = shown
    assert dialog.title.value == "Escala del MotionPlus — slot 0"
    assert len(dialog.content.controls) == 4  # intro + pitch, roll, yaw


async def test_api_rejects_unknown_calibration_axis():
    manager = FakeManager()
    server = ApiServer(manager)
    with pytest.raises(ValueError, match="axis"):
        await server.dispatch("calibrate_axis", {"slot": 0, "axis": "sideways"})


def test_xbox_view_lights_pressed_controls():
    pytest.importorskip("flet")
    import flet.canvas as cv
    from wiichinahook.gui import xbox_view
    idle = xbox_view.shapes(None)
    live = xbox_view.shapes({"active": True, "buttons": ["A", "LB", "DPAD_UP"], "lt": 0.0, "rt": 1.0,
                             "lx": 1.0, "ly": 0.0, "rx": 0.0, "ry": 0.0})
    colors = lambda shapes: [s.paint.color for s in shapes if hasattr(s, "paint") and s.paint]
    assert xbox_view.FACE["A"][1] in colors(live) and xbox_view.FACE["A"][1] not in colors(idle)
    assert colors(live).count(xbox_view.LIT) > colors(idle).count(xbox_view.LIT)
    rt_fill = [s for s in live if isinstance(s, cv.Rect) and s.x == 230 and s.paint.color == xbox_view.LIT]
    assert rt_fill and rt_fill[0].width == 60
    thumbs = [s for s in live if isinstance(s, cv.Circle) and s.radius == 15]
    assert thumbs[0].x == xbox_view.LEFT_STICK[0] + xbox_view.STICK_TRAVEL   # left stick pushed right
    inactive = xbox_view.shapes({"active": False, "buttons": ["A"]})
    assert colors(inactive) == colors(idle)


def test_gamepad_tab_shows_the_dsu_mode_and_its_guides(tmp_path):
    pytest.importorskip("flet")
    from types import SimpleNamespace
    from wiichinahook.gui.gamepad_tab import GamepadTab, load_guide
    controller = SimpleNamespace(t=Translator("es"), config=AppConfig(), page=None)
    tab = GamepadTab(controller)
    tab.editing = 2                                   # default mode 2 is the DSU mode
    tab.build()
    assert tab.mode_type.value == "dsu" and "Dolphin" in tab.guide.value and "Mandos" in tab.guide.value
    tab.on_status({"mode": 2, "problems": {}})
    assert tab.view_hint.value == controller.t("gp_view_dsu")
    assert tab.collect() == {"type": "dsu", "name": "DSU", "nunchuk_server": True, "ir_server": True,
                             "ir_range": 0.5}
    tab.dsu_switches["ir_server"].value = False                 # the IR server can be switched off
    tab.dsu_ir_range.value = "0.7"
    assert tab.collect()["ir_server"] is False and tab.collect()["ir_range"] == 0.7
    tab.editing = 1
    tab.render_editor()
    assert tab.mode_type.value == "xbox" and "A" in tab.combos
    (tmp_path / "x.md").write_text("english", encoding="utf-8")
    assert load_guide("x", "es", [tmp_path]) == "english" and load_guide("y", "en", [tmp_path]) is None


def test_speaker_settings_round_trip():
    pytest.importorskip("flet")
    from wiichinahook.gui.app import Controller
    from wiichinahook.speaker import validate_speaker
    controller = object.__new__(Controller)            # no page/service needed to build the section
    controller.t = Translator("es")
    controller.config = AppConfig(speaker=validate_speaker(
        {"enabled": True, "volume": 0.3, "events": {"mode": "sonidos/modo.wav", "low_battery": None}}))
    card = controller.build_speaker_settings()
    assert card.content.controls[0].controls[1].value == "Altavoz (opcional)"   # section title
    choice, path = controller.sound_rows["mode"]
    assert choice.value == "custom" and path.visible and path.value == "sonidos/modo.wav"
    assert controller.sound_rows["low_battery"][0].value == "off"
    assert controller.speaker_form() == {"enabled": True, "volume": 0.3, "events": {
        "connect": "chime", "mode": "sonidos/modo.wav", "low_battery": None}}


def test_log_export_text_has_a_header_and_every_line():
    import logging
    pytest.importorskip("flet")
    from wiichinahook.gui.app import LogBuffer
    buffer = LogBuffer(size=3)
    for i in range(5):
        buffer.emit(logging.LogRecord("wiichinahook", logging.INFO, __file__, 1, f"line {i}", None, None))
    text = buffer.export_text("0.3.0")
    assert text.startswith("# WiiChinaHook 0.3.0 log") and text.endswith("line 4\n")
    assert "line 1" not in text and text.count("line ") == 3     # only the buffered (latest) lines


def test_pc_editor_round_trip_and_mouse_claims():
    pytest.importorskip("flet")
    from types import SimpleNamespace
    from wiichinahook.gamepad.mapping import validate_template
    from wiichinahook.gui.gamepad_tab import GamepadTab
    controller = SimpleNamespace(t=Translator("es"), config=AppConfig(), page=None)
    tab = GamepadTab(controller)
    tab.editing = 3                                       # default mode 3 is the PC mode
    tab.build()
    assert tab.mode_type.value == "pc"
    editor = tab.pc_editor
    assert editor.rows["wm_1"].text.value == "alt+tab" and editor.rows["wm_a"].choice.value == "left"
    editor.rows["wm_1"].text.value = "ctrl+9"
    editor.rows["wm_2"].kind.value = "toggle"
    editor.rows["wm_2"].text.value = "system:mute | system:mute"
    editor.source.value = "wm_dpad"                        # the D-pad now moves the mouse
    editor.apply_claims()
    assert editor.rows["wm_up"].kind.disabled and not editor.rows["wm_a"].kind.disabled
    result = validate_template(tab.collect())
    assert result["mouse"]["source"] == "wm_dpad" and result["buttons"]["wm_up"] is None
    assert result["buttons"]["wm_1"] == "keys:ctrl+9"
    assert result["buttons"]["wm_2"] == "toggle:system:mute | system:mute"


def test_home_modifier_is_not_offered_with_a_dolphinbar():
    pytest.importorskip("flet")
    from dataclasses import replace
    from types import SimpleNamespace
    from wiichinahook.gui.gamepad_tab import GamepadTab
    bar = GamepadTab(SimpleNamespace(t=Translator("en"), config=AppConfig(), page=None))
    assert "wm_home" not in bar.modifiers() and "wm_a+wm_b" in bar.modifiers()
    bt = GamepadTab(SimpleNamespace(t=Translator("en"), config=replace(AppConfig(), mode="bluetooth"), page=None))
    assert "wm_home" in bt.modifiers()
