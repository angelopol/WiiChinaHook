import json
import math
from pathlib import Path

import pytest

from wiichinahook.calibration import CalibrationError, fit_axis_scale
from wiichinahook.orientation import conjugate, from_axis_angle, multiply, rotate, tilt_from_accel

AXIS_VECTORS = {"pitch": (1, 0, 0), "roll": (0, 1, 0), "yaw": (0, 0, 1)}


def simulate(axis, start_accel, degrees=90.0, scale=1.85, sign=1, bias=(5.6, -4.7, 11.2), hz=150):
    """Still 1.5 s, slow turn about the body axis over 3 s, still 1.5 s.
    The fake MotionPlus reports scale*sign times the true rate plus a bias."""
    q = tilt_from_accel(start_accel)
    samples, t, angle = [], 0.0, 0.0
    total, turn = 6.0, math.radians(degrees)
    while t < total:
        rate = turn / 3 if 1.5 <= t < 4.5 else 0.0  # rad/s about the body axis
        body_rate = [0.0, 0.0, 0.0]
        body_rate[list(AXIS_VECTORS).index(axis)] = rate
        up_body = rotate(conjugate(q), (0, 0, 1))
        accel_raw = (-up_body[0], -up_body[1], up_body[2])  # raw Wii: X left, Y back, Z up
        wx, wy, wz = (math.degrees(r) * scale * sign for r in body_rate)
        samples.append((t, accel_raw, (wz + bias[0], -wy + bias[1], -wx + bias[2])))
        q = multiply(q, from_axis_angle(AXIS_VECTORS[axis], rate / hz))
        t += 1 / hz
    return samples


@pytest.mark.parametrize("axis,start", [
    ("pitch", (0, 0, 1)),    # flat, tilt the tip up
    ("roll", (0, 0, 1)),     # flat, roll onto its side
    ("yaw", (-1, 0, 0)),     # sideways grip (right side up), steering-wheel turn
])
@pytest.mark.parametrize("sign", [1, -1])
def test_recovers_scale_and_sign_on_every_axis(axis, start, sign):
    result = fit_axis_scale(simulate(axis, start, sign=sign), axis, still_seconds=1.2)
    assert result["factor"] == pytest.approx(sign / 1.85, rel=0.03)
    assert result["rotation_deg"] == pytest.approx(90, abs=4)


def test_rejects_axis_that_is_not_horizontal():
    # Yaw while lying flat: gravity does not move, nothing to compare against.
    with pytest.raises(CalibrationError, match="horizontal|further"):
        fit_axis_scale(simulate("yaw", (0, 0, 1)), "yaw", still_seconds=1.2)


def test_rejects_small_turn_and_moving_start():
    with pytest.raises(CalibrationError, match="further"):
        fit_axis_scale(simulate("pitch", (0, 0, 1), degrees=20), "pitch", still_seconds=1.2)
    with pytest.raises(CalibrationError, match="still"):
        fit_axis_scale(simulate("pitch", (0, 0, 1)), "pitch", still_seconds=2.5)


def test_real_clone_pitch_capture():
    rows = json.loads((Path(__file__).parent / "data" / "clone_axes_capture.json").read_text())["rows"]
    samples = [(t, a, g) for _, t, a, g in rows]
    still_seconds = max(t for name, t, _, _ in rows if name == "still") - samples[0][0]
    result = fit_axis_scale(samples, "pitch", still_seconds=still_seconds)
    assert result["factor"] == pytest.approx(1 / 1.85, rel=0.1)
