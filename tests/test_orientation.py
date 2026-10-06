import json
import math
from pathlib import Path

import pytest

from wiichinahook.orientation import (OrientationFilter, from_axis_angle, multiply, reference_yaw, rotate,
                                      tilt_from_accel, yaw_of)


def run(filt, gyro, seconds, accel=(0.0, 0.0, 1.0), hz=100):
    t = 1_000_000
    filt.update(accel, (0.0, 0.0, 0.0), t)
    for _ in range(int(seconds * hz)):
        t += int(1e6 / hz)
        q = filt.update(accel, gyro, t)
    return q


def close(a, b, tol=0.03):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def test_tilt_from_accel_points_body_axes_up():
    assert close(rotate(tilt_from_accel((0, 0, 1)), (0, 0, 1)), (0, 0, 1))
    tip_up = tilt_from_accel((0, -1, 0))     # pointing at the ceiling: raw Y (back) reads -1 g
    assert close(rotate(tip_up, (0, 1, 0)), (0, 0, 1))
    upside_down = tilt_from_accel((0, 0, -1))
    assert close(rotate(upside_down, (0, 0, 1)), (0, 0, -1))


@pytest.mark.parametrize("gyro,axis,expected", [
    ((90, 0, 0), (0, 1, 0), (-1, 0, 0)),   # yaw +: counter-clockwise, tip turns left
    ((0, 0, 45), (0, 1, 0), (0, math.sqrt(.5), -math.sqrt(.5))),  # pitch +: tip down
    ((0, 90, 0), (1, 0, 0), (0, 0, 1)),    # raw roll +: left side down, right side up
])
def test_measured_motionplus_sign_conventions(gyro, axis, expected):
    filt = OrientationFilter(kp=0)  # pure gyro integration
    q = run(filt, gyro, 1.0)
    assert close(rotate(q, axis), expected)


def test_yaw_heading():
    q = run(OrientationFilter(kp=0), (90, 0, 0), 1.0)
    assert math.degrees(yaw_of(q)) == pytest.approx(90, abs=2)


def test_gravity_correction_removes_tilt_drift_but_not_yaw():
    filt = OrientationFilter(kp=1.5)
    q = run(filt, (0, 0, 0), 0.5)
    filt.q = (math.cos(0.3), math.sin(0.3), 0, 0)  # wrong 34-degree pitch estimate
    q = run(filt, (0, 0, 0), 4.0)
    assert close(rotate(q, (0, 0, 1)), (0, 0, 1), 0.02)


def test_gap_in_samples_does_not_integrate_a_huge_step():
    filt = OrientationFilter(kp=0)
    filt.update((0, 0, 1), (0, 0, 0), 0)
    q = filt.update((0, 0, 1), (500, 0, 0), 5_000_000)  # 5 s gap
    assert close(q, (1, 0, 0, 0))


def test_replay_of_real_clone_pitch_capture_tracks_gravity():
    data = json.loads((Path(__file__).parent / "data" / "clone_axes_capture.json").read_text())["rows"]
    still = [r for r in data if r[0] == "still"]
    bias = [sum(r[3][i] for r in still) / len(still) for i in range(3)]
    # The clone's nominal pitch rate is ~1.85x too high (integrated gyro vs gravity
    # angle in this very capture); with that scale the filter tracks within degrees.
    scale = (1.0, 1.0, 1 / 1.85)
    filt = OrientationFilter()
    errors = []
    for _, t, accel, gyro in data:
        q = filt.update(accel, [(g - b) * k for g, b, k in zip(gyro, bias, scale)], int(t * 1e6))
        tip = rotate(q, (0, 1, 0))
        estimated = math.degrees(math.asin(max(-1, min(1, tip[2]))))
        measured = math.degrees(math.atan2(-accel[1], math.hypot(accel[0], accel[2])))  # raw Y points back
        errors.append(abs(estimated - measured))
    errors = errors[len(still):]
    assert max(abs(a) for a in [r[2][1] for r in data]) > 0.7  # the capture really pitched ~60 degrees
    assert sorted(errors)[len(errors) // 2] < 5   # median within a few degrees


def test_sideways_mario_kart_pose_from_the_users_photo():
    # Both clones on their side, tip (POWER) to the left, buttons facing the player:
    # the GUI showed accelerometer X = -1.00, Y = -0.04, Z = +0.04.
    q = tilt_from_accel((-1.0, -0.04, 0.04))
    assert rotate(q, (1, 0, 0))[2] > 0.99  # the remote's right side is up
    shown = multiply(from_axis_angle((0, 0, 1), -reference_yaw(q)), q)
    assert close(rotate(shown, (0, 0, 1)), (0, -1, 0), 0.06)   # buttons face the player
    assert close(rotate(shown, (0, 1, 0)), (-1, 0, 0), 0.06)   # tip points left


def test_reference_yaw_points_a_flat_remote_at_the_screen():
    q = multiply(from_axis_angle((0, 0, 1), 1.0), tilt_from_accel((0.0, 0.0, 1.0)))
    shown = multiply(from_axis_angle((0, 0, 1), -reference_yaw(q)), q)
    assert close(rotate(shown, (0, 1, 0)), (0, 1, 0))


@pytest.mark.parametrize("raw_accel,axis,expected", [
    ((0.0, -1.0, 0.0), (0, 1, 0), (0, 0, 1)),       # "lift the tip to the ceiling": tip up
    ((1.0, 0.04, 0.19), (1, 0, 0), (0, 0, -1)),     # "roll the right side down": right side down
])
def test_users_guided_pose_check_readings(raw_accel, axis, expected):
    # Accelerometer readings from the user's guided check on 2026-10-06.
    assert close(rotate(tilt_from_accel(raw_accel), axis), expected, 0.25)
