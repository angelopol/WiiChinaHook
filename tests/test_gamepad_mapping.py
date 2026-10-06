import copy

import pytest

from wiichinahook.gamepad.mapping import (DEFAULT_CONFIG, GAME_TEMPLATE, MappingEngine, mode_type, unavailable_bindings, validate_config,
                                          validate_template)

B, A, HOME, UP, RIGHT, DOWN, LEFT = 0x0004, 0x0008, 0x0080, 0x0800, 0x0200, 0x0400, 0x0100
ONE, TWO, MINUS, PLUS = 0x0002, 0x0001, 0x0010, 0x1000
TEMPLATE = validate_template(GAME_TEMPLATE)


def state(buttons=0, c=False, z=False, stick=(0.0, 0.0), t=0.0, accel=(0.0, 0.0, 1.0), gyro=None, ir=None,
          nunchuk=True):
    return {"buttons": buttons, "timestamp_us": int(t * 1e6), "accel_g": accel, "gyro_dps": gyro, "ir": ir,
            "nunchuk": {"c": c, "z": z, "stick": list(stick), "accel_raw": [512, 512, 712]} if nunchuk else None}


def test_default_game_layout_matches_the_spec():
    engine = MappingEngine()
    out, _ = engine.process(state(MINUS | PLUS | ONE | TWO | A | B | HOME, c=True, z=True), TEMPLATE)
    # − + 1 2 -> X Y A B; A/B -> RB/RT; Home -> Start; C+Z together -> Select only.
    assert out.buttons == {"X", "Y", "A", "B", "RB", "START", "BACK"}
    assert out.rt == 1.0 and out.lt == 0.0 and "LB" not in out.buttons
    out, _ = engine.process(state(0, c=True), TEMPLATE)
    assert out.buttons == {"LB"}
    out, _ = engine.process(state(0, z=True), TEMPLATE)
    assert out.lt == 1.0 and not out.buttons
    out, _ = engine.process(state(UP | RIGHT), TEMPLATE)            # D-pad without the modifier
    assert out.buttons == {"DPAD_UP", "DPAD_RIGHT"}


def test_nunchuk_stick_is_left_stick_with_deadzone():
    engine = MappingEngine()
    out, _ = engine.process(state(stick=(0.05, -0.02)), TEMPLATE)
    assert (out.lx, out.ly) == (0.0, 0.0)
    out, _ = engine.process(state(stick=(1.0, 0.0)), TEMPLATE)
    assert out.lx == pytest.approx(1.0) and out.ly == 0.0


def test_gyro_speed_right_stick_directions():
    template = validate_template(dict(GAME_TEMPLATE, sticks={"LEFT_STICK": "nc_stick", "RIGHT_STICK": "gyro"}))
    engine = MappingEngine()
    out, _ = engine.process(state(gyro=(-200.0, 0.0, 0.0)), template)   # turning right
    assert out.rx == pytest.approx(1.0)
    out, _ = engine.process(state(gyro=(0.0, 0.0, -100.0)), template)   # tip going up
    assert out.ry > 0.4 and out.rx == 0.0
    out, _ = engine.process(state(gyro=(0.0, 0.0, 0.0)), template)      # turn stopped: back to centre
    assert (out.rx, out.ry) == (0.0, 0.0)


def aimed(right_deg=0.0, up_deg=0.0):
    """Body->world quaternion: turned right by right_deg, tip raised by up_deg."""
    import math
    from wiichinahook.orientation import from_axis_angle, multiply
    return list(multiply(from_axis_angle((0.0, 0.0, 1.0), math.radians(-right_deg)),
                         from_axis_angle((1.0, 0.0, 0.0), math.radians(up_deg))))


def aim_state(q, recenter=None, heading=None):
    s = state()
    s["orientation"] = q
    s["calibration"] = {k: v for k, v in (("recenter_seq", recenter), ("heading", heading)) if v is not None}
    return s


def test_gyro_aim_stick_holds_where_the_remote_points():
    engine = MappingEngine()
    out, _ = engine.process(aim_state(aimed(30.0)), TEMPLATE)          # where it points on activation = centre
    assert (out.rx, out.ry) == (0.0, 0.0)
    for _ in range(3):                                                  # turned 35° right and kept there
        out, _ = engine.process(aim_state(aimed(65.0)), TEMPLATE)
        assert out.rx == pytest.approx(1.0) and out.ry == pytest.approx(0.0, abs=1e-9)
    out, _ = engine.process(aim_state(aimed(30.0, up_deg=25.0)), TEMPLATE)   # tip raised 25°: full up
    assert out.ry == pytest.approx(1.0) and out.rx == pytest.approx(0.0, abs=1e-6)
    out, _ = engine.process(aim_state(aimed(10.0)), TEMPLATE)          # turned left of centre
    assert out.rx < -0.3
    out, _ = engine.process(aim_state(aimed(10.0), recenter=1), TEMPLATE)   # quick calibration recentres
    assert (out.rx, out.ry) == (0.0, 0.0)
    out, _ = engine.process(aim_state(aimed(-35.0), heading="ir"), TEMPLATE)  # sensor bar = centre
    assert out.rx == pytest.approx(-1.0)


def test_old_gyro_sticks_migrate_to_aim():
    old = validate_config({"version": 2, "modes": [{"sticks": {"RIGHT_STICK": "gyro"}}, None, None, None]})
    assert old["modes"][0]["sticks"]["RIGHT_STICK"] == "gyro_angle"
    kept = validate_config({"version": 3, "modes": [{"sticks": {"RIGHT_STICK": "gyro"}}, None, None, None]})
    assert kept["modes"][0]["sticks"]["RIGHT_STICK"] == "gyro"


def test_modifier_plus_arrows_switch_mode_clockwise_and_swallow_the_arrow():
    engine = MappingEngine()
    requests = []
    for arrow, mode in ((UP, 1), (RIGHT, 2), (DOWN, 3), (LEFT, 4)):
        engine.process(state(B), TEMPLATE)
        out, request = engine.process(state(B | arrow), TEMPLATE)
        requests.append(request)
        assert out.rt == 1.0                     # B keeps working as RT
        assert not {"DPAD_UP", "DPAD_RIGHT", "DPAD_DOWN", "DPAD_LEFT"} & out.buttons
        out, _ = engine.process(state(arrow), TEMPLATE)   # B released, arrow still held
        assert not {"DPAD_UP", "DPAD_RIGHT", "DPAD_DOWN", "DPAD_LEFT"} & out.buttons
        engine.process(state(0), TEMPLATE)
    assert requests == [1, 2, 3, 4]
    out, request = engine.process(state(UP), TEMPLATE)    # arrow alone is a D-pad press
    assert request is None and "DPAD_UP" in out.buttons


def test_mode_switch_also_works_from_an_empty_mode():
    engine = MappingEngine()
    engine.process(state(B), None)
    out, request = engine.process(state(B | UP), None)
    assert out is None and request == 1


def test_shake_pulses_once_per_shake():
    template = copy.deepcopy(TEMPLATE)
    template["buttons"]["L3"] = "wm_shake_up"
    template["buttons"]["R3"] = "nc_shake_left"
    engine = MappingEngine()
    hits = []
    for i in range(60):
        t = i / 100
        spike = 2.5 if i in (20, 21) else (-2.0 if i == 23 else 0.0)   # up, then the rebound
        out, _ = engine.process(state(t=t, accel=(0.0, 0.0, 1.0 + spike)), template)
        hits.append("L3" in out.buttons)
    assert any(hits[20:23]) and not any(hits[:20]) and not any(hits[40:])
    assert not any("R3" in engine.process(state(t=1.0), template)[0].buttons for _ in range(3))


def test_unavailable_bindings_are_reported():
    caps = {"nunchuk": False, "motionplus": True, "ir": True}
    problems = unavailable_bindings(TEMPLATE, caps)
    assert "LB: nc_c (needs nunchuk)" in problems and "BACK: nc_c+nc_z (needs nunchuk)" in problems
    assert "LEFT_STICK: nc_stick (needs nunchuk)" in problems
    assert not any(p.startswith("RIGHT_STICK") for p in problems)
    assert unavailable_bindings(TEMPLATE, {"nunchuk": True, "motionplus": True, "ir": True}) == []
    assert unavailable_bindings(None, {}) == []


def test_config_validation_and_free_remapping():
    config = validate_config({"modifier": "wm_b", "mode": 1,
                              "modes": [{"buttons": {"A": "wm_a", "GUIDE": "wm_shake_forward"},
                                         "sticks": {"RIGHT_STICK": "ir"}}]})
    assert config["modes"][0]["buttons"]["A"] == "wm_a"
    assert config["modes"][0]["buttons"]["X"] is None            # unspecified = unassigned
    assert config["modes"][0]["sticks"]["RIGHT_STICK"] == "ir" and config["modes"][2:] == [None] * 2
    assert config["modes"][1] == {"type": "dsu", "name": "DSU"}   # old configs: empty mode 2 becomes DSU
    for bad in ({"modifier": "wm_power"}, {"mode": 5}, {"modes": [{"buttons": {"Z": "wm_a"}}]},
                {"modes": [{"buttons": {"A": "wm_power"}}]}, {"modes": [{"sticks": {"LEFT_STICK": "wm_a"}}]},
                {"modes": [{"buttons": {"A": "wm_a+wm_b+wm_1+wm_2"}}]},       # more than three
                {"modes": [{"buttons": {"A": "wm_a+wm_a"}}]}):                 # repeated member
        with pytest.raises(ValueError):
            validate_config(bad)



def shake_up_states(buttons, template, engine):
    """Feed a Wiimote 'shake up' while holding `buttons`; return the outputs."""
    outs = []
    for i in range(30):
        spike = 2.5 if i in (10, 11) else 0.0
        out, _ = engine.process(state(buttons, t=i / 100, accel=(0.0, 0.0, 1.0 + spike)), template)
        outs.append(out)
    return outs


def test_button_plus_shake_combination():
    template = copy.deepcopy(TEMPLATE)
    template["buttons"]["L3"] = "wm_a+wm_shake_up"
    validate_template(template)
    outs = shake_up_states(A, template, MappingEngine())
    assert any("L3" in o.buttons for o in outs[10:13]) and not any("L3" in o.buttons for o in outs[:10])
    # While the combination fires, A alone (RB) is not sent; before the shake it is.
    assert all("RB" not in o.buttons for o in outs if "L3" in o.buttons)
    assert "RB" in outs[0].buttons
    outs = shake_up_states(0, template, MappingEngine())          # shake without A: nothing
    assert not any("L3" in o.buttons for o in outs)


def test_longer_combination_wins_over_overlapping_shorter_one():
    template = copy.deepcopy(TEMPLATE)
    template["buttons"]["GUIDE"] = "nc_c+nc_z+wm_home"
    out, _ = MappingEngine().process(state(HOME, c=True, z=True), template)
    assert out.buttons == {"GUIDE"}                               # not BACK, LB, LT or START
    out, _ = MappingEngine().process(state(0, c=True, z=True), template)
    assert out.buttons == {"BACK"}


def test_axis_shake_fires_in_either_direction_with_per_axis_sensitivity():
    template = copy.deepcopy(TEMPLATE)
    template["buttons"]["L3"] = "wm_shake_z"
    template["buttons"]["R3"] = "nc_shake_x"
    template["shake_wm"] = [1.3, 1.3, 3.0]          # vertical shakes need 3 g
    template = validate_template(template)
    for spike, fires in ((2.0, False), (-3.5, True), (3.5, True)):
        engine = MappingEngine()
        hits = [("L3" in engine.process(state(t=i / 100, accel=(0.0, 0.0, 1.0 + (spike if i == 10 else 0.0))),
                                        template)[0].buttons) for i in range(20)]
        assert any(hits) is fires
    engine = MappingEngine()
    for i in range(20):
        nunchuk_x = 512 + (400 if i == 10 else 0)   # (raw - 512) / 200 = 2 g sideways
        st = state(t=i / 100)
        st["nunchuk"]["accel_raw"] = [nunchuk_x, 512, 712]
        out, _ = engine.process(st, template)
        if i == 10:
            assert "R3" in out.buttons


def test_old_single_shake_threshold_still_loads():
    template = validate_template({"shake_g": 2.0, "gyro_full_dps": 300})
    assert template["shake_wm"] == [2.0, 2.0, 2.0] and template["shake_nc"] == [2.0, 2.0, 2.0]
    assert template["gyro_full_dps_y"] == 300.0
    with pytest.raises(ValueError):
        validate_template({"shake_nc": [1.0, 1.0]})


def test_dsu_mode_type_and_migration():
    assert DEFAULT_CONFIG["modes"][1]["type"] == "dsu" and mode_type(DEFAULT_CONFIG["modes"][0]) == "xbox"
    current = validate_config({"version": 2, "modes": [None, None, {"type": "dsu"}, None]})
    assert [mode_type(t) for t in current["modes"]] == [None, None, "dsu", None]   # no re-migration
    legacy = validate_config({"modes": [None, {"buttons": {"A": "wm_a"}}, None, None]})
    assert [mode_type(t) for t in legacy["modes"]] == [None, "xbox", None, None]   # mode 2 in use: kept
    assert unavailable_bindings({"type": "dsu", "name": "DSU"}, {}) == []
    with pytest.raises(ValueError):
        validate_template({"type": "keyboard"})
