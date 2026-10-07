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


MAX_PITCH_OFFSET = math.radians(45.0)


def tip_pitch(q: Quaternion) -> float:
    """Elevation of the tip above the horizon (radians, + = tip up)."""
    return math.asin(max(-1.0, min(1.0, rotate(q, (0.0, 1.0, 0.0))[2])))


class OrientationFilter:
    """`q` is the physical orientation (gravity keeps correcting it). Recentering
    also stores the tip's pitch as the neutral grip: `output()` reports orientations
    relative to it (a remote held slightly tipped down then reads level), so the 3D
    view and the aim stick start from where the player holds it. Roll is left as is."""

    def __init__(self, kp: float = 1.5):
        self.kp = kp
        self.q: Quaternion | None = None
        self.last_us: int | None = None
        self.pitch_offset = 0.0   # radians, kept across reset() (only recenter() changes it)

    def reset(self):
        self.q, self.last_us = None, None

    def output(self, q: Quaternion) -> Quaternion:
        """`q` seen from the neutral grip: rotated about the body X axis (the remote's
        left-right axis) by the stored pitch."""
        if not self.pitch_offset:
            return q
        return normalize(multiply(q, from_axis_angle((1.0, 0.0, 0.0), -self.pitch_offset)))

    def recenter(self, accel_g=None):
        """Heading -> straight ahead; pitch -> the current tip pitch becomes level.
        Without a filtered orientation (no MotionPlus) the tilt comes from `accel_g`."""
        q = self.q if self.q is not None else (tilt_from_accel(accel_g) if accel_g else None)
        if q is None:
            return
        # Pointing grip only (buttons face up or down): on its side, tilting is steering
        # and its neutral stays level with gravity.
        pointing = abs(rotate(q, (0.0, 0.0, 1.0))[2]) > 0.6
        pitch = tip_pitch(q) if pointing else 0.0
        self.pitch_offset = max(-MAX_PITCH_OFFSET, min(MAX_PITCH_OFFSET, pitch))
        if self.q is not None:
            self.q = recentered(self.q)

    def correct_heading(self, target: float, gain: float = 0.04) -> bool:
        """Pull the tip heading towards `target` (e.g. from the sensor bar)."""
        if self.q is None or not level_enough(self.q):
            return False
        self.q = _rotate_heading(self.q, gain * _wrap(target - yaw_of(self.q)))
        return True

    def update(self, accel_g, gyro_dps, t_us: int) -> Quaternion:
        """gyro_dps is MotionPlus order (yaw, roll, pitch); accel_g Wii (X, Y, Z)."""
        if self.q is None:
            self.q, self.last_us = tilt_from_accel(accel_g) if accel_g else IDENTITY, t_us
            return self.output(self.q)
        dt = (t_us - self.last_us) / 1e6
        self.last_us = t_us
        if not 0 < dt < 0.1:
            return self.output(self.q)  # first sample after a gap: only re-arm the clock
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
        return self.output(self.q)


# Wii IR camera: 1024 px across ~41 degrees. Its image is mirrored as seen from the
# player (pointing right moves the dots left), so a bar left of the image centre
# means the remote is turned left. Sign taken from the usual Wii references; not
# yet verified against a capture of this clone.
IR_WIDTH = 1024
IR_FOV_X = math.radians(41.0)


def ir_heading(points):
    """Heading of the tip relative to the sensor bar (counter-clockwise = +, radians)
    from basic IR points, or None unless two well separated dots are visible."""
    visible = [p for p in points or () if p]
    if len(visible) < 2:
        return None
    a, b = max(((p, q) for i, p in enumerate(visible) for q in visible[i + 1:]),
               key=lambda pq: math.hypot(pq[0]["x"] - pq[1]["x"], pq[0]["y"] - pq[1]["y"]))
    separation = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
    if not 40 <= separation <= 900:  # one source / reflections, or nonsense
        return None
    middle = (a["x"] + b["x"]) / 2
    return (middle - (IR_WIDTH - 1) / 2) / IR_WIDTH * IR_FOV_X


def _wrap(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


def _rotate_heading(q: Quaternion, angle: float) -> Quaternion:
    return normalize(multiply(from_axis_angle((0.0, 0.0, 1.0), angle), q))


def recentered(q: Quaternion) -> Quaternion:
    """Same tilt with the heading reset so the pose reads 'straight ahead'."""
    return _rotate_heading(q, -reference_yaw(q))


def level_enough(q: Quaternion) -> bool:
    """Tip and right side close to horizontal: IR x maps to heading."""
    return abs(rotate(q, (0.0, 1.0, 0.0))[2]) < 0.6 and abs(rotate(q, (1.0, 0.0, 0.0))[2]) < 0.4
