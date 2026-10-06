import struct
import zlib

import pytest
from wiichinahook.wiimote import AccelCalibration, ReportParser, parse_ir, output_report


def test_accel_low_bits_are_not_buttons():
    parser = ReportParser()
    assert parser.feed(bytes.fromhex("a1 31 60 68 80 80 c0"))
    assert parser.state.buttons == 8
    assert parser.state.accel_raw == (515, 514, 770)
    assert parser.state.accel_g == pytest.approx((3/256, 2/256, 258/256))
    assert parser.state.gyro_dps is None
    assert output_report(0x11, 0x10) == bytes.fromhex("a2 11 10")


@pytest.mark.parametrize("report,size", ReportParser.LENGTHS.items())
def test_every_truncated_report_is_ignored(report, size):
    parser = ReportParser()
    # 0x21 may be unpadded (clone); with SE=0 it is complete at 5 header + 1 byte.
    for length in range(6 if report == 0x21 else size):
        assert not parser.feed(bytes([0xA1, report]) + bytes(length))
    assert parser.state.timestamp_us == 0


def test_factory_accel_checksum_and_scale():
    data = bytes.fromhex("80 80 80 00 c0 c0 c0 00 40")
    data += bytes([(sum(data) + 0x55) & 255])
    cal = AccelCalibration.from_bytes(data)
    assert cal.convert((512, 512, 768)) == (0, 0, 1)
    with pytest.raises(ValueError):
        AccelCalibration.from_bytes(data[:-1] + bytes([data[-1] ^ 1]))


def test_ir_basic_extended_and_missing_points():
    assert parse_ir(b"\xff" * 10) == [None] * 4
    assert parse_ir(b"\xff" * 12, True) == [None] * 4
    points = parse_ir(bytes.fromhex("23 34 61 45 56") + b"\xff" * 5)
    assert points[:2] == [{"x": 547, "y": 308, "size": None}, {"x": 325, "y": 86, "size": None}]
    assert parse_ir(bytes.fromhex("23 34 65") + b"\xff" * 9, True)[0] == {"x": 547, "y": 308, "size": 5}


def test_nunchuk_and_motionplus_interleaved_preserve_samples():
    parser = ReportParser()
    parser.extension = "motionplus+nunchuk"
    # Centered stick, raw accel high bytes, C/Z released in passthrough bits.
    p = bytes.fromhex("80 80 80 80 c0 0c")
    parser.feed(b"\xa1\x37" + bytes(5) + b"\xff" * 10 + p)
    assert parser.state.nunchuk["c"] is False
    assert parser.state.nunchuk["z"] is False
    assert parser.state.nunchuk["accel_raw"] == (512, 512, 768)
    parser.parse_extension(bytes.fromhex("80 80 80 80 c0 fc"), 1)
    assert parser.state.nunchuk["accel_raw"] == (514, 514, 774)
    nunchuk_stamp = parser.state.nunchuk_timestamp_us
    # Three 8063 values (0x1f7f), slow axes and downstream present.
    p = bytes.fromhex("7f 7f 7f 7f 7f 7e")
    parser.feed(b"\xa1\x37" + bytes(5) + b"\xff" * 10 + p)
    assert parser.state.gyro_raw == (8063,) * 3
    assert parser.state.gyro_dps == (0.,) * 3
    assert parser.state.nunchuk_timestamp_us == nunchuk_stamp
    parser.state.disconnect()
    assert parser.state.nunchuk is None and parser.state.gyro_dps is None


def test_motionplus_fast_slow_and_calibration_crc():
    parser = ReportParser()
    parser.extension = "motionplus"
    block = struct.pack(">6HB", 32000, 32000, 32000, 36000, 36000, 36000, 50) + b"\0"
    crc = zlib.crc32(block + block).to_bytes(4, "big")
    parser.set_gyro_calibration(block + crc[:2] + block + crc[2:])
    parser.parse_extension(bytes.fromhex("28 28 28 8f 8e 8e"), 1)  # 9000, 300 deg/sec
    assert parser.state.gyro_dps == (300.,) * 3
    with pytest.raises(ValueError):
        parser.set_gyro_calibration(bytes(32))


def test_status_battery_and_no_fabricated_sensor_data():
    parser = ReportParser()
    parser.feed(bytes.fromhex("a1 20 00 08 12 00 00 60"))
    assert parser.state.battery == .5
    assert parser.extension_connected
    assert parser.state.accel_g is None
    assert parser.state.ir is None


def test_interleaved_measurements_expire():
    parser=ReportParser()
    parser.feed(bytes.fromhex('a1 31 00 00 80 80 c0'))
    stamp=parser.state.accel_timestamp_us
    parser.expire_samples(stamp+500000)
    assert parser.state.accel_g is not None
    parser.expire_samples(stamp+1000001)
    assert parser.state.accel_g is None
