"""Wiimote orientation from MotionPlus + accelerometer (Mahony complementary filter).

Raw Wii axes (measured with the clone, 2026-10-06): the accelerometer frame is
right-handed with +X to the remote's LEFT, +Y towards the BACK (the 1/2 buttons end)
and +Z out of the buttons face. Lying face up it reads Z = +1 g; tip pointing at the
ceiling, Y = -1 g; right side down, X = +1 g. The MotionPlus rates (pitch, roll, yaw)
are right-handed about those same X, Y, Z axes: pitch + = tip down, roll + = left side
down, yaw + = counter-clockwise seen from above. Dolphin's IMU uses this same frame.

Internally the body frame is X right, Y tip, Z buttons face: the raw frame turned
180 degrees about Z, so vectors and rates map as (x, y, z) -> (-x, -y, z). Quaternions are (w, x, y, z)
and rotate body vectors into the world frame (X right, Y towards the screen, Z up).
Yaw has no absolute reference and drifts.
"""
from __future__ import annotations

import math

Quaternion = tuple[float, float, float, float]
IDENTITY: Quaternion = (1.0, 0.0, 0.0, 0.0)


def multiply(a: Quaternion, b: Quaternion) -> Quaternion:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def normalize(q: Quaternion) -> Quaternion:
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def conjugate(q: Quaternion) -> Quaternion:
    return (q[0], -q[1], -q[2], -q[3])


def rotate(q: Quaternion, v) -> tuple[float, float, float]:
    """Rotate body vector v into the world frame."""
    w, x, y, z = multiply(multiply(q, (0.0, *v)), conjugate(q))
    return (x, y, z)


def from_axis_angle(axis, angle: float) -> Quaternion:
    s = math.sin(angle / 2)
    return (math.cos(angle / 2), axis[0] * s, axis[1] * s, axis[2] * s)


def body_accel(accel):
    """Raw Wii accelerometer (X left, Y back, Z up) to the body frame (X right, Y tip, Z up)."""
    return (-accel[0], -accel[1], accel[2])


def body_rates(gyro_dps):
    """MotionPlus (yaw, roll, pitch) in deg/s to body rates about (X, Y, Z) in rad/s."""
    yaw, roll, pitch = gyro_dps
    return (math.radians(-pitch), math.radians(-roll), math.radians(yaw))


def tilt_from_accel(accel) -> Quaternion:
    """Orientation (yaw = 0) whose world-up direction matches the raw accelerometer."""
    ax, ay, az = body_accel(accel)
    norm = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
    ax, ay, az = ax / norm, ay / norm, az / norm
    # Shortest rotation taking body-up measured (a) to world up (0, 0, 1),
    # expressed as body->world: rotate a onto +Z.
    dot = az
    if dot < -0.999999:
        return (0.0, 1.0, 0.0, 0.0)  # upside down: 180 degrees about X
    cx, cy, cz = ay, -ax, 0.0  # a x (0, 0, 1)
    return normalize((1.0 + dot, cx, cy, cz))


def heading(v) -> float:
    """Counter-clockwise angle (radians) from world +Y to v's horizontal projection."""
    return math.atan2(-v[0], v[1])


def yaw_of(q: Quaternion) -> float:
    """Heading of the body Y (pointing) axis around world Z, radians."""
    return heading(rotate(q, (0.0, 1.0, 0.0)))


def reference_yaw(q: Quaternion) -> float:
    """Yaw to subtract so the current pose reads as 'straight ahead':
    lying flat (buttons face up or down) the tip points at the screen; on its side
    (e.g. the sideways 'Mario Kart' grip) the buttons face points at the player."""
    face = rotate(q, (0.0, 0.0, 1.0))
    if abs(face[2]) > 0.6:
        return yaw_of(q)
    return heading(face) - math.pi


class OrientationFilter:
    def __init__(self, kp: float = 1.5):
        self.kp = kp
        self.q: Quaternion | None = None
        self.last_us: int | None = None

    def reset(self):
        self.q, self.last_us = None, None

    def update(self, accel_g, gyro_dps, t_us: int) -> Quaternion:
        """gyro_dps is MotionPlus order (yaw, roll, pitch); accel_g Wii (X, Y, Z)."""
        if self.q is None:
            self.q, self.last_us = tilt_from_accel(accel_g) if accel_g else IDENTITY, t_us
            return self.q
        dt = (t_us - self.last_us) / 1e6
        self.last_us = t_us
        if not 0 < dt < 0.1:
            return self.q  # first sample after a gap: only re-arm the clock
        wx, wy, wz = body_rates(gyro_dps)
        if accel_g:
            ax, ay, az = body_accel(accel_g)
            norm = math.sqrt(ax * ax + ay * ay + az * az)
            if 0.7 < norm < 1.3:  # trust gravity only when not accelerating hard
                ax, ay, az = ax / norm, ay / norm, az / norm
                w, x, y, z = self.q
                # World up expressed in the body frame.
                vx, vy, vz = 2 * (x * z - w * y), 2 * (y * z + w * x), w * w - x * x - y * y + z * z
                wx += self.kp * (ay * vz - az * vy)
                wy += self.kp * (az * vx - ax * vz)
                wz += self.kp * (ax * vy - ay * vx)
        dq = multiply(self.q, (0.0, wx, wy, wz))
        self.q = normalize(tuple(c + 0.5 * d * dt for c, d in zip(self.q, dq)))
        return self.q
