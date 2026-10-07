import asyncio
import random

import pytest

from tests.test_speaker import make_session

ZERO, COUNTS_PER_DPS = 8063, 13.768   # nominal MotionPlus scale (slow mode)


def motionplus_report(yaw, roll, pitch, accel_z=154):
    """0x37 report (buttons, accel, IR, extension) carrying a MotionPlus sample in °/s."""
    raw = [round(ZERO + v * COUNTS_PER_DPS) for v in (yaw, roll, pitch)]
    ext = bytes([raw[0] & 0xFF, raw[1] & 0xFF, raw[2] & 0xFF,
                 ((raw[0] >> 8) << 2) | 2 | 1,          # yaw high bits, yaw slow, pitch slow
                 ((raw[1] >> 8) << 2) | 2,              # roll high bits, roll slow
                 ((raw[2] >> 8) << 2) | 2])             # pitch high bits, "MotionPlus data"
    return bytes([0xA1, 0x37, 0, 0, 128, 128, accel_z]) + bytes([0xFF] * 10) + ext


def resting(noise=(2.0, 1.0, 0.3), bias=(1.5, -0.8, 0.0), seed=1):
    rng = random.Random(seed)
    return lambda: motionplus_report(*(b + rng.uniform(-n, n) for b, n in zip(bias, noise)))


async def feed(session, make, stop, period=0.004):
    while not stop.is_set():
        session.receive(make())
        await asyncio.sleep(period)


def remote():
    session, channel = make_session()
    session.parser.extension = "motionplus"
    session.state.capabilities["motionplus"] = True
    return session


async def run_calibration(session, make, seconds=0.6):
    stop = asyncio.Event()
    feeder = asyncio.create_task(feed(session, make, stop))
    try:
        return await session.calibrate_noise(seconds)
    finally:
        stop.set()
        await feeder


async def test_noise_calibration_sets_a_gate_above_the_noise_and_removes_the_bias(monkeypatch):
    session = remote()
    result = await run_calibration(session, resting())
    yaw, roll, pitch = result["gyro_noise_dps"]
    assert 2.0 <= yaw <= 2.6 and 1.0 <= roll <= 1.35 and pitch == pytest.approx(0.375, abs=0.08)
    assert result["bias_dps"][0] == pytest.approx(1.5, abs=0.3)
    assert session.state.calibration["gyro_noise_dps"] == list(session.parser.gyro_deadband)
    jitter = resting(seed=7)
    for _ in range(50):                                   # at rest now: exactly 0, no jitter
        session.receive(jitter())
        assert session.state.gyro_dps == (0.0, 0.0, 0.0)
    session.receive(motionplus_report(1.5 - 30.0, -0.8, 0.0))   # a real 30 °/s turn passes intact
    assert session.state.gyro_dps[0] == pytest.approx(-30.0, abs=0.2)
    assert session.clear_noise()["gyro_noise_dps"] == [0.0, 0.0, 0.0]


async def test_noise_calibration_refuses_when_the_remote_was_moved():
    session = remote()
    rng = random.Random(3)
    turning = lambda: motionplus_report(rng.uniform(-40, 40), 0.0, 0.0)
    with pytest.raises(ValueError, match="moved"):
        await run_calibration(session, turning)
    assert session.parser.gyro_deadband == (0.0, 0.0, 0.0)  # nothing applied
    bumped = iter(range(10**6))
    tapping = lambda: motionplus_report(0.0, 0.0, 0.0, accel_z=154 + (12 if next(bumped) % 9 == 0 else 0))
    with pytest.raises(ValueError, match="moved"):
        await run_calibration(session, tapping)


async def test_bias_calibrations_measure_through_the_gate():
    session = remote()
    session.parser.gyro_deadband = (5.0, 5.0, 5.0)          # a gate wider than the bias
    stop = asyncio.Event()
    feeder = asyncio.create_task(feed(session, resting(noise=(0.2, 0.2, 0.2), bias=(3.0, 0.0, 0.0)), stop))
    await asyncio.sleep(0.2)
    session.gyro_samples = []
    await asyncio.sleep(0.2)
    samples, session.gyro_samples = session.gyro_samples, None
    stop.set()
    await feeder
    assert samples and sum(s[0] for s in samples) / len(samples) == pytest.approx(3.0, abs=0.3)
