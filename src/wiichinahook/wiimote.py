"""Wiimote wire reports. Vectors retain Wii axes; DSU transforms at its boundary."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import struct
import time

from .orientation import OrientationFilter, ir_heading, tilt_from_accel

PSM_HID_CONTROL = 0x11
PSM_HID_INTERRUPT = 0x13
HID_INPUT_REPORT = 0xA1
HID_OUTPUT_REPORT = 0xA2


def output_report(report_id: int, *payload: int) -> bytes:
    return bytes([HID_OUTPUT_REPORT, report_id, *payload])


def led_report(mask: int) -> bytes:
    return output_report(0x11, mask & 0xF0)


def data_reporting_report(report_mode: int, continuous: bool = True) -> bytes:
    return output_report(0x12, 0x04 if continuous else 0, report_mode)


@dataclass
class WiimoteState:
    address: str = "00:00:00:00:00:00"
    slot: int = 0
    connected: bool = False
    phase: str = "disconnected"
    error: str | None = None
    buttons: int = 0
    report_id: int = 0
    timestamp_us: int = 0
    accel_timestamp_us: int = 0
    gyro_timestamp_us: int = 0
    ir_timestamp_us: int = 0
    nunchuk_timestamp_us: int = 0
    battery: float | None = None
    accel_raw: tuple[int, int, int] | None = None
    accel_g: tuple[float, float, float] | None = None
    gyro_raw: tuple[int, int, int] | None = None
    gyro_dps: tuple[float, float, float] | None = None
    ir: list[dict | None] | None = None
    nunchuk: dict | None = None
    # Body->world quaternion (w, x, y, z); see orientation.py. Tilt only without MotionPlus.
    orientation: list[float] | None = None
    extension: str | None = None
    capabilities: dict = field(default_factory=lambda: {"buttons": True, "accelerometer": True,
                                                        "ir": False, "motionplus": False, "nunchuk": False})
    calibration: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    def disconnect(self, error=None):
        self.connected = False
        self.phase = "disconnected"
        self.error = error
        self.buttons = 0
        self.accel_raw = self.accel_g = self.gyro_raw = self.gyro_dps = None
        self.ir = self.nunchuk = self.orientation = None
        self.battery = None
        self.accel_timestamp_us = self.gyro_timestamp_us = self.ir_timestamp_us = self.nunchuk_timestamp_us = 0
        self.timestamp_us = time.monotonic_ns() // 1000


@dataclass
class AccelCalibration:
    zero: tuple = (512, 512, 512)
    one: tuple = (768, 768, 768)
    source: str = "nominal"

    @classmethod
    def from_bytes(cls, data):
        if len(data) < 10 or (sum(data[:9]) + 0x55) & 255 != data[9]:
            raise ValueError("Invalid accelerometer calibration checksum")
        unpack = lambda d: tuple((d[i] << 2) | ((d[3] >> (4 - i * 2)) & 3) for i in range(3))
        zero, one = unpack(data[:4]), unpack(data[4:8])
        if any(o <= z for z, o in zip(zero, one)):
            raise ValueError("Invalid accelerometer calibration scale")
        return cls(zero, one, "factory")

    def convert(self, raw):
        return tuple((v - z) / (o - z) for v, z, o in zip(raw, self.zero, self.one))


class ReportParser:
    LENGTHS = {0x20: 6, 0x21: 21, 0x22: 4, 0x30: 2, 0x31: 5, 0x32: 10,
               0x33: 17, 0x34: 21, 0x35: 21, 0x36: 21, 0x37: 21, 0x3D: 21}

    def __init__(self, state=None):
        self.state = state or WiimoteState()
        self.accel = AccelCalibration()
        self.gyro_zero = (8063.0,) * 3
        self.gyro_bias = (0.0,) * 3
        # Per-channel (yaw, roll, pitch) correction from calibrate_axis; may be
        # negative when a remote reports a channel with the opposite sign.
        self.gyro_scale = (1.0,) * 3
        self.gyro_blocks = None
        self.nunchuk_calibration = None
        self.extension = None
        self.extension_connected = False
        self.gyro_slow = (True,) * 3
        self.orientation = OrientationFilter()
        self.ir_heading = False  # SlotOptions.ir_calibration

    def feed(self, data: bytes) -> bool:
        if data[:1] == b"\xa1":
            data = data[1:]
        if data[:1] == b"\x21" and len(data) >= 6 and len(data) - 1 < self.LENGTHS[0x21]:
            # Clone quirk (trace 2026-10-05): memory replies carry only the
            # requested bytes instead of 16 padded ones. Accept when complete.
            se = data[3]
            if len(data) - 6 >= (0 if se & 15 else (se >> 4) + 1):
                data = data.ljust(1 + self.LENGTHS[0x21], b"\0")
        if not data or data[0] not in self.LENGTHS or len(data) - 1 < self.LENGTHS[data[0]]:
            return False
        report, p = data[0], data[1:]
        s = self.state
        now = time.monotonic_ns() // 1000
        s.report_id, s.timestamp_us = report, now
        if report != 0x3D:
            s.buttons = int.from_bytes(p[:2], "big") & 0x1F9F
        if report == 0x20:
            s.battery = min(1.0, p[5] / 192.0)
            self.extension_connected = bool(p[2] & 2)
        if report in (0x31, 0x33, 0x35, 0x37):
            s.accel_raw = ((p[2] << 2) | ((p[0] >> 5) & 3),
                           (p[3] << 2) | ((p[1] >> 4) & 2),
                           (p[4] << 2) | ((p[1] >> 5) & 2))
            s.accel_g = self.accel.convert(s.accel_raw)
            s.accel_timestamp_us = now
            if not (self.extension or "").startswith("motionplus"):
                self.orientation.reset()
                s.orientation = list(tilt_from_accel(s.accel_g))
        if report in (0x33, 0x36, 0x37):
            offset = 2 if report == 0x36 else 5
            s.ir = parse_ir(p[offset:offset + (12 if report == 0x33 else 10)], report == 0x33)
            s.ir_timestamp_us = now
            if self.ir_heading:
                target = ir_heading(s.ir)
                if target is not None and self.orientation.correct_heading(target):
                    s.calibration["heading"] = "ir"  # heading now absolute: 0 = sensor bar
        ext_offset = {0x32: 2, 0x34: 2, 0x35: 5, 0x36: 12, 0x37: 15, 0x3D: 0}.get(report)
        if ext_offset is not None and self.extension:
            self.parse_extension(p[ext_offset:ext_offset + 6], now)
        return True

    def parse_extension(self, p, now):
        if len(p) < 6 or p == b"\xff" * 6:
            return
        s = self.state
        if self.extension.startswith("motionplus") and p[5] & 2:
            raw = (p[0] | ((p[3] & 0xFC) << 6), p[1] | ((p[4] & 0xFC) << 6),
                   p[2] | ((p[5] & 0xFC) << 6))
            slow = (bool(p[3] & 2), bool(p[4] & 2), bool(p[3] & 1))
            self.gyro_slow = slow
            values = []
            for i in range(3):
                if self.gyro_blocks:
                    zero, scale, degrees = self.gyro_blocks[1 if slow[i] else 0]
                    value = (raw[i] - zero[i]) * degrees / (scale[i] - zero[i])
                else:
                    value = (raw[i] - self.gyro_zero[i]) / 13.768 * (1 if slow[i] else 2000 / 440)
                values.append((value - self.gyro_bias[i]) * self.gyro_scale[i])
            s.gyro_raw, s.gyro_dps, s.gyro_timestamp_us = raw, tuple(values), now
            s.orientation = list(self.orientation.update(s.accel_g, s.gyro_dps, now))
            if not p[4] & 1:
                s.nunchuk = None
            return
        if self.extension not in ("nunchuk", "motionplus+nunchuk"):
            return
        if self.extension == "motionplus+nunchuk":
            raw = ((p[2] << 2) | ((p[5] >> 3) & 2), (p[3] << 2) | ((p[5] >> 4) & 2),
                   ((p[4] & 0xFE) << 2) | ((p[5] >> 5) & 2) | ((p[5] >> 5) & 4))
            c, z = not bool(p[5] & 8), not bool(p[5] & 4)
        else:
            raw = ((p[2] << 2) | ((p[5] >> 2) & 3), (p[3] << 2) | ((p[5] >> 4) & 3),
                   (p[4] << 2) | ((p[5] >> 6) & 3))
            c, z = not bool(p[5] & 2), not bool(p[5] & 1)
        stick = [max(-1.0, min(1.0, (v - 128) / 127)) for v in p[:2]]
        accel = None
        if self.nunchuk_calibration:
            nc, ranges = self.nunchuk_calibration
            accel = nc.convert(raw)
            stick = [max(-1.0, min(1.0, (v - center) / ((hi - center) if v >= center else (center - lo))))
                     for v, (hi, lo, center) in zip(p[:2], ranges)]
        s.nunchuk = {"stick": stick, "stick_raw": list(p[:2]), "c": c, "z": z,
                     "accel_raw": raw, "accel_g": accel}
        s.nunchuk_timestamp_us = now

    def expire_samples(self, now_us, max_age_us=1_000_000):
        """Interleaved sensors retain values, but never indefinitely stale ones."""
        for name, fields in (("accel", ("accel_g", "accel_raw")),
                             ("gyro", ("gyro_dps", "gyro_raw")),
                             ("ir", ("ir",)), ("nunchuk", ("nunchuk",))):
            stamp = getattr(self.state, f"{name}_timestamp_us")
            if stamp and now_us - stamp > max_age_us:
                for field_name in fields:
                    setattr(self.state, field_name, None)

    def set_gyro_calibration(self, data):
        if len(data) != 32:
            raise ValueError("MotionPlus calibration needs 32 bytes")
        import zlib
        checksum = int.from_bytes(data[14:16] + data[30:32], "big")
        if zlib.crc32(data[:14] + data[16:30]) & 0xFFFFFFFF != checksum:
            raise ValueError("Invalid MotionPlus calibration checksum")
        blocks = []
        for d in (data[:16], data[16:]):
            nums = struct.unpack(">6H", d[:12])
            zero, scale = tuple(v / 4 for v in nums[:3]), tuple(v / 4 for v in nums[3:])
            if not d[12] or any(abs(a - b) < 1 for a, b in zip(zero, scale)):
                raise ValueError("Invalid MotionPlus scale")
            blocks.append((zero, scale, d[12] * 6))
        self.gyro_blocks = blocks


def parse_ir(data, extended=False):
    points = []
    if extended:
        for i in range(0, 12, 3):
            x, y, bits = data[i:i + 3]
            x |= (bits & 0x30) << 4
            y |= (bits & 0xC0) << 2
            points.append(None if x == 1023 and y == 1023 else {"x": x, "y": y, "size": bits & 15})
    else:
        for i in (0, 5):
            a, b, bits, c, d = data[i:i + 5]
            for x, y in ((a | ((bits & 0x30) << 4), b | ((bits & 0xC0) << 2)),
                         (c | ((bits & 3) << 8), d | ((bits & 12) << 6))):
                points.append(None if x == 1023 and y == 1023 else {"x": x, "y": y, "size": None})
    return points


def parse_input_report(data: bytes) -> WiimoteState | None:
    parser = ReportParser()
    return parser.state if parser.feed(data) else None
