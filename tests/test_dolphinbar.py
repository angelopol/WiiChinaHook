import asyncio
import queue
import time
from dataclasses import replace

import pytest

from wiichinahook.config import AppConfig, load_config
from wiichinahook.dolphinbar import BarLink, DolphinBarManager, bar_devices, slot_address

# Extension bytes captured through the DolphinBar from the clone (2026-10-06).
MOTIONPLUS_ALONE = bytes.fromhex("74 3a 0c 73 8a 52")      # ..10, port empty
MOTIONPLUS_PASS = bytes.fromhex("74 3a 0c 73 8b 52")       # ..10, Nunchuk attached
NUNCHUK_PASS = bytes.fromhex("7e 86 45 7a 80 fc")          # ..00 passthrough Nunchuk
NUNCHUK_PLAIN = bytes.fromhex("7d 86 45 7a 81 ff")         # C/Z released
NUNCHUK_PLAIN_Z_HELD = bytes.fromhex("7d 86 45 7a 81 fe")  # ..10 like MotionPlus
STALE_EMPTY_SLOT = bytes.fromhex("30 00 00 81 7c 9a") + b"\xff" * 16


class FakeClone:
    """A clone Wiimote as seen through a DolphinBar slot (hid.device API)."""

    def __init__(self, *, present=True, nunchuk=True, motionplus=True, z_held=False, fake_mp_ack=False):
        self.present, self.nunchuk, self.motionplus = present, nunchuk, motionplus
        self.z_held, self.fake_mp_ack = z_held, fake_mp_ack
        self.queue = queue.Queue()
        self.mode = None
        self.mp_mode = 0
        self.writes = []
        self.counter = 0
        self.fail_reads = False

    def open_path(self, path):
        self.path = path

    def close(self):
        pass

    def ack(self, report, error=0):
        self.queue.put(bytes([0x22, 0, 0, report, error]) + bytes(17))

    def write(self, data):
        data = bytes(data)
        assert len(data) == 22, "the bar expects 22-byte output reports"
        self.writes.append(data)
        if not self.present:
            return len(data)
        rid = data[0]
        if rid == 0x15:
            flag = 0x02 if (self.nunchuk or self.mp_mode) else 0
            self.queue.put(bytes([0x20, 0, 0, flag | 0x10, 0, 0, 0x55]) + bytes(15))
        elif rid == 0x16:
            space, address, value = data[1], int.from_bytes(data[2:5], "big"), data[6]
            error = 0
            if address >> 8 == 0xA600:
                if not self.motionplus and not self.fake_mp_ack:
                    error = 7
                elif address == 0xA600FE and self.motionplus:
                    self.mp_mode = value
            elif address == 0xA400F0:
                self.mp_mode = 0
            if space & 0x02:
                self.ack(0x16, error)
        elif rid == 0x17:
            pass  # memory reads: the DolphinBar drops the clone's replies
        elif rid == 0x12:
            self.mode = data[2]
            if data[1] & 0x02:
                self.ack(0x12)
        elif rid in (0x11, 0x13, 0x1A) and data[1] & 0x02:
            self.ack(rid)
        return len(data)

    def extension(self):
        self.counter += 1
        if self.mp_mode == 5 and self.nunchuk:
            return MOTIONPLUS_PASS if self.counter % 3 else NUNCHUK_PASS
        if self.mp_mode == 4:
            return MOTIONPLUS_ALONE
        if self.nunchuk:
            return NUNCHUK_PLAIN_Z_HELD if self.z_held else NUNCHUK_PLAIN
        return b"\xff" * 6

    def read(self, size, timeout_ms=0):
        if self.fail_reads:
            raise OSError("device disconnected")
        try:
            return list(self.queue.get_nowait())
        except queue.Empty:
            pass
        time.sleep(0.004)
        if not self.present:
            return list(STALE_EMPTY_SLOT)
        if self.mode == 0x37:
            return list(bytes([0x37, 0, 0, 0x80, 0x80, 0x9A]) + b"\xff" * 10 + self.extension())
        if self.mode == 0x35:
            return list(bytes([0x35, 0, 0, 0x80, 0x80, 0x9A]) + self.extension() + bytes(10))
        return []


def manager_with(tmp_path, clones):
    config = replace(AppConfig(), state_dir=tmp_path)
    published = []
    paths = {slot: f"path{slot}" for slot in clones}
    by_path = {f"path{slot}": clone for slot, clone in clones.items()}

    class Opener:
        def __init__(self):
            self.clone = None
        def open_path(self, path):
            self.clone = by_path[path]
        def __getattr__(self, name):
            return getattr(self.clone, name)

    manager = DolphinBarManager(config, published.append, devices=lambda: paths, opener=Opener)
    return manager, published


async def connect(manager, slot):
    await manager.probe(slot, f"path{slot}")
    return manager.sessions.get(slot)


async def close_all(manager):
    for slot in list(manager.sessions):
        await manager.drop(slot, "test end")


def test_slot_mapping_uses_interface_numbers():
    devices = [{"product_id": 0x0306, "interface_number": n, "path": f"p{n}".encode()} for n in (2, 0, 3, 1)]
    devices.append({"product_id": 0x1234, "interface_number": 0, "path": b"other"})
    assert bar_devices(lambda vid: devices) == {0: b"p0", 1: b"p1", 2: b"p2", 3: b"p3"}


def test_mode_defaults_to_dolphinbar_and_is_validated(tmp_path):
    assert AppConfig().mode == "dolphinbar"
    path = tmp_path / "c.json"
    path.write_text('{"mode": "bluetooth"}')
    assert load_config(path).mode == "bluetooth"
    path.write_text('{"mode": "usb"}')
    with pytest.raises(ValueError):
        load_config(path)


async def test_motionplus_and_nunchuk_without_memory_reads(tmp_path):
    clone = FakeClone(nunchuk=True, motionplus=True)
    manager, published = manager_with(tmp_path, {0: clone})
    session = await connect(manager, 0)
    state = session.state
    assert state.connected and state.phase == "ready"
    assert state.address == slot_address(0) == "02:00:44:42:00:00"
    assert state.extension == "motionplus+nunchuk"
    assert state.capabilities["motionplus"] and state.capabilities["nunchuk"] and state.capabilities["ir"]
    assert state.calibration["accelerometer"] == "typical"
    assert clone.mp_mode == 5 and clone.mode == 0x37
    await asyncio.sleep(0.1)
    assert state.gyro_dps is not None and state.nunchuk is not None
    # 1 g on the vertical axis with the typical/clone calibration (raw 0x9a << 2).
    assert state.accel_g[2] == pytest.approx(1.0, abs=0.05)
    assert not any(w[0] == 0x17 for w in clone.writes), "read-free: no 3 s timeouts per lost reply"
    await close_all(manager)


async def test_motionplus_alone(tmp_path):
    clone = FakeClone(nunchuk=False, motionplus=True)
    manager, _ = manager_with(tmp_path, {1: clone})
    session = await connect(manager, 1)
    assert session.state.extension == "motionplus" and clone.mp_mode == 4
    assert not session.state.capabilities["nunchuk"]
    await close_all(manager)


async def test_nunchuk_without_motionplus(tmp_path):
    clone = FakeClone(nunchuk=True, motionplus=False)
    manager, _ = manager_with(tmp_path, {0: clone})
    session = await connect(manager, 0)
    assert session.state.extension == "nunchuk"
    assert session.state.capabilities == {"buttons": True, "accelerometer": True, "ir": True,
                                          "motionplus": False, "nunchuk": True}
    await close_all(manager)


async def test_held_z_button_is_not_mistaken_for_motionplus(tmp_path):
    # MotionPlus writes acknowledged but no MotionPlus: plain Nunchuk data with Z
    # held ends in ..10 like MotionPlus packets; the passthrough mix is required.
    clone = FakeClone(nunchuk=True, motionplus=False, z_held=True, fake_mp_ack=True)
    manager, _ = manager_with(tmp_path, {0: clone})
    session = await connect(manager, 0)
    assert session.state.extension == "nunchuk"
    await close_all(manager)


async def test_empty_slot_is_not_a_remote(tmp_path):
    clone = FakeClone(present=False)
    manager, _ = manager_with(tmp_path, {2: clone})
    assert await connect(manager, 2) is None
    assert 2 not in manager.states and 2 not in manager.probing


async def test_link_loss_disconnects_and_frees_slot(tmp_path):
    clone = FakeClone()
    manager, published = manager_with(tmp_path, {0: clone})
    session = await connect(manager, 0)
    clone.fail_reads = True
    for _ in range(50):
        if 0 not in manager.sessions:
            break
        await asyncio.sleep(0.02)
    assert 0 not in manager.sessions
    assert not manager.states[0].connected
    assert published[-1].connected is False
    with pytest.raises(ValueError):
        manager.session_for(0)


async def test_gyro_bias_is_stored_per_slot_and_reused(tmp_path):
    clone = FakeClone()
    manager, _ = manager_with(tmp_path, {3: clone})
    session = await connect(manager, 3)
    async def fake_calibrate():
        session.parser.gyro_bias = (5.6, -4.7, 11.2)
        return {"gyro_bias": [5.6, -4.7, 11.2]}
    session.calibrate = fake_calibrate
    await manager.calibrate(3)
    await close_all(manager)
    manager2, _ = manager_with(tmp_path, {3: FakeClone()})
    session2 = await connect(manager2, 3)
    assert session2.parser.gyro_bias == (5.6, -4.7, 11.2)
    assert (await manager2.forget(3))["forgotten_settings"] == 3
    assert manager2.store.get(3) == {}
    await close_all(manager2)


async def test_pairing_is_done_on_the_bar(tmp_path):
    manager, _ = manager_with(tmp_path, {})
    with pytest.raises(ValueError, match="SYNC"):
        await manager.pair()


def test_barlink_pads_reports_and_strips_bluetooth_header():
    clone = FakeClone(present=False)
    class Opener:
        def __new__(cls):
            return clone
    loop = asyncio.new_event_loop()
    try:
        link = BarLink("p", loop, Opener)
        link.write(bytes([0xA2, 0x11, 0x10]))
        link.close()                                      # waits for queued writes to go out
        assert clone.writes[-1] == bytes([0x11, 0x10]) + bytes(20)
    finally:
        loop.close()


async def test_remote_leaving_the_bar_is_detected_despite_stale_reports(tmp_path):
    clone = FakeClone()
    manager, _ = manager_with(tmp_path, {0: clone})
    session = await connect(manager, 0)
    clone.present = False  # the slot now only emits stale 0x30 reports
    session.last_data = time.monotonic() - 11  # skip the 10 s wait
    for _ in range(80):
        if 0 not in manager.sessions:
            break
        await asyncio.sleep(0.05)
    assert 0 not in manager.sessions
    assert not manager.states[0].connected
    assert manager.states[0].error == "No HID reports for 10 seconds"
