"""MotionPlus scale/sign calibration against gravity.

To calibrate a body axis it is held horizontal and the remote is turned slowly
about it: gravity then sweeps the plane perpendicular to the axis, so the
accelerometer measures the real rotation angle while the gyro integrates its own.
The ratio is the gyro scale error (a negative ratio means the channel's sign is
inverted). No exact angle is required.

Gestures: pitch = tilt the tip up from flat; roll = roll a flat remote onto its
side; yaw = with the remote on its side (sideways grip, buttons to the player),
turn it like a steering wheel.
"""
from __future__ import annotations

import math
import statistics

from .orientation import body_accel, body_rates

# Version of the axis conventions the stored factors were measured with; bump it
# when orientation.body_accel/body_rates change so stale factors are ignored.
GYRO_SCALE_FRAME = 2

# Body axis index (right-handed frame of orientation.py) and MotionPlus channel
# index in gyro_dps order (yaw, roll, pitch).
AXES = {"pitch": (0, 2), "roll": (1, 1), "yaw": (2, 0)}
# Plane coordinates whose angle rotates about each body axis.
_PLANE = {0: (2, 1), 1: (0, 2), 2: (1, 0)}


class CalibrationError(ValueError):
    pass


def _unwrap(angles):
    out, offset, previous = [], 0.0, None
    for a in angles:
        if previous is not None:
            delta = a - previous
            if delta > math.pi:
                offset -= 2 * math.pi
            elif delta < -math.pi:
                offset += 2 * math.pi
        out.append(a + offset)
        previous = a
    return out


def fit_axis_scale(samples, axis: str, still_seconds: float = 1.0) -> dict:
    """samples: [(t_seconds, accel_g raw Wii (X, Y, Z), gyro_dps (yaw, roll, pitch))]
    with the remote still for the first `still_seconds`. Returns the factor that
    multiplies that MotionPlus channel so its integral matches gravity."""
    if axis not in AXES:
        raise CalibrationError(f"axis must be one of {', '.join(AXES)}")
    body, channel = AXES[axis]
    if len(samples) < 50:
        raise CalibrationError("Not enough MotionPlus samples")
    t0 = samples[0][0]
    still = [s for s in samples if s[0] - t0 <= still_seconds]
    if len(still) < 10:
        raise CalibrationError("Keep the remote still at the start")
    rates = [body_rates(g)[body] for _, _, g in samples]
    bias = statistics.mean(rates[:len(still)])
    if statistics.pstdev(rates[:len(still)]) > math.radians(4):
        raise CalibrationError("The remote moved during the still part")
    # Integrate the bias-free body rate over every sample (trapezoid).
    integral, gyro_angle = 0.0, [0.0]
    for (t_a, _, _), (t_b, _, _), r_a, r_b in zip(samples, samples[1:], rates, rates[1:]):
        dt = t_b - t_a
        if 0 < dt < 0.2:
            integral += ((r_a + r_b) / 2 - bias) * dt
        gyro_angle.append(integral)
    i, j = _PLANE[body]
    accel_angle, valid = [], []
    for _, accel, _ in samples:
        a = body_accel(accel)
        norm = math.sqrt(sum(c * c for c in a))
        accel_angle.append(-math.atan2(a[i], a[j]))  # body rotation = -(angle of up)
        in_plane = math.hypot(a[i], a[j])
        valid.append(0.85 < norm < 1.15 and in_plane > 0.8 * norm)
    accel_angle = _unwrap(accel_angle)
    xs = [a for a, ok in zip(accel_angle, valid) if ok]
    ys = [g for g, ok in zip(gyro_angle, valid) if ok]
    if len(xs) < 20:
        raise CalibrationError("Keep the calibrated axis horizontal and turn slowly")
    span = max(xs) - min(xs)
    if span < math.radians(45):
        raise CalibrationError(f"Turn further (measured {math.degrees(span):.0f}°, need at least 45°)")
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    slope = sxy / sxx
    correlation = sxy / math.sqrt(sxx * syy) if syy else 0.0
    if abs(correlation) < 0.9:
        raise CalibrationError("Inconsistent motion; keep the axis horizontal and turn slowly")
    return {"axis": axis, "channel": channel, "factor": 1 / slope,
            "rotation_deg": math.degrees(span), "correlation": abs(correlation)}
