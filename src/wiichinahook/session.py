"""One HID session, serialized memory transactions and sensor initialization."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import statistics
import time

from .wiimote import AccelCalibration, ReportParser, output_report

log = logging.getLogger(__name__)


class ReportError(RuntimeError):
    pass


class WiimoteSession:
    def __init__(self, state, connection, publish, *, ir=True, motionplus=True):
        self.state = state
        self.connection = connection
        self.publish = publish
        self.parser = ReportParser(state)
        self.channels = {}
        self.channel_events = {0x11: asyncio.Event(), 0x13: asyncio.Event()}
        self.transaction_lock = asyncio.Lock()
        self.feature_lock = asyncio.Lock()
        self.pending = None
        self.rumbling = False
        self.rumble_task = None
        self.tasks = set()
        self.want_ir, self.want_motionplus = ir, motionplus
        self.ir_enabled = False
        self.initialized = False
        self.closed = False
        self.reconfigure_task = None
        self.status_task = None
        self.mode = 0x30
        self.last_packet = time.monotonic()
        self.last_extension_probe = 0.0
        self.gyro_samples = None
        self.motionplus_port_connected = None
        self.last_status = time.monotonic()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        def done(t):
            self.tasks.discard(t)
            if not t.cancelled() and t.exception():
                self.state.error = str(t.exception())
                log.warning("%s: %s", self.state.address, t.exception())
                self.publish(self.state)
        task.add_done_callback(done)
        return task

    def attach(self, channel):
        if channel.psm in self.channels:
            self.spawn(channel.disconnect())
            return
        self.channels[channel.psm] = channel
        if channel.psm == 0x13:
            channel.sink = self.receive
        else:
            channel.sink = lambda data: log.debug("HID control %s: %s", self.state.address, data.hex())
        channel.on("close", self.channel_closed)
        if not hasattr(channel, "state") or channel.state == channel.State.OPEN:
            self.channel_events[channel.psm].set()
        else:
            channel.on("open", self.channel_events[channel.psm].set)

    def channel_closed(self):
        if not self.closed:
            self.state.disconnect("HID channel closed")
            self.publish(self.state)
            self.spawn(self.connection.disconnect())

    def send(self, report_id, payload=b"\x00"):
        if self.closed or 0x13 not in self.channels:
            raise ReportError("HID interrupt channel is not open")
        payload = bytearray(payload)
        payload[0] = (payload[0] & 0xFE) | int(self.rumbling)
        self.channels[0x13].write(output_report(report_id, *payload))

    async def command(self, report_id, payload, *, response=0x22, address=None, size=0):
        async with self.transaction_lock:
            if response == 0x22:
                payload = bytes([payload[0] | 0x02]) + payload[1:]
            future = asyncio.get_running_loop().create_future()
            self.pending = {"future": future, "report": response, "command": report_id,
                            "address": address, "size": size, "data": bytearray(), "seen": set()}
            if size:
                self.pending["data"] = bytearray(size)
            try:
                self.send(report_id, payload)
                return await asyncio.wait_for(future, 3.0)
            except TimeoutError as exc:
                raise ReportError(f"Timeout waiting for report 0x{report_id:02x}") from exc
            finally:
                self.pending = None

    async def read(self, address, size):
        if not 1 <= size <= 256:
            raise ValueError("Memory reads must be 1..256 bytes")
        return await self.command(0x17, address.to_bytes(4, "big") + size.to_bytes(2, "big"),
                                  response=0x21, address=address & 0xFFFF, size=size)

    async def write(self, address, data):
        # Only peripheral registers are writable. Never write EEPROM/Mii data.
        if address >> 16 not in (0x04A4, 0x04A6, 0x04B0) or not 1 <= len(data) <= 16:
            raise ValueError("Only 1..16-byte peripheral register writes are allowed")
        await self.command(0x16, address.to_bytes(4, "big") + bytes([len(data)]) + data.ljust(16, b"\0"))

    def receive(self, data):
        if self.closed:
            return
        had_extension = self.parser.extension_connected
        if not data or data[0] != 0xA1 or not self.parser.feed(data):
            return
        self.last_packet = time.monotonic()
        report, p = data[1], data[2:]
        self.parser.expire_samples(self.state.timestamp_us)
        pending = self.pending
        if pending and report == pending["report"] and not pending["future"].done():
            future = pending["future"]
            if report == 0x22 and p[2] == pending["command"]:
                if p[3]:
                    future.set_exception(ReportError(f"Report 0x{p[2]:02x} error 0x{p[3]:02x}"))
                else:
                    future.set_result(b"")
            elif report == 0x20:
                future.set_result(p)
            elif report == 0x21:
                offset = int.from_bytes(p[3:5], "big") - pending["address"]
                count = (p[2] >> 4) + 1
                if count == 16 and len(p) > 21:
                    # Clone quirk (trace 2026-10-05): a 32-byte read comes back in
                    # one oversized report instead of two 16-byte chunks.
                    count = min(len(p) - 5, pending["size"] - max(offset, 0))
                if 0 <= offset < pending["size"]:
                    if p[2] & 15:
                        future.set_exception(ReportError(f"Memory read error 0x{p[2] & 15:x}"))
                    elif offset + count <= pending["size"]:
                        pending["data"][offset:offset + count] = p[5:5 + count]
                        pending["seen"].update(range(offset, offset + count))
                        if len(pending["seen"]) == pending["size"]:
                            future.set_result(bytes(pending["data"]))
        if self.gyro_samples is not None and self.state.gyro_timestamp_us == self.state.timestamp_us:
            if all(self.parser.gyro_slow):
                self.gyro_samples.append(self.state.gyro_dps)
        if report == 0x20:
            self.last_status = time.monotonic()
        requested_status = pending is not None and pending["report"] == 0x20
        if report == 0x20 and self.initialized and (not requested_status or had_extension != self.parser.extension_connected):
            self.status_received()
        # MotionPlus signals changes to its downstream port in gyro packets.
        if self.initialized and self.parser.extension and self.parser.extension.startswith("motionplus"):
            ext = p[15:21] if report == 0x37 else p[5:11] if report == 0x35 else b""
            if len(ext) == 6 and ext[5] & 2:
                attached = bool(ext[4] & 1)
                previous = self.motionplus_port_connected
                self.motionplus_port_connected = attached
                if (previous is not None and attached != previous) or (previous is None and attached != (self.parser.extension == "motionplus+nunchuk")):
                    self.schedule_reconfigure()
        self.publish(self.state)

    def status_received(self):
        if not self.status_task or self.status_task.done():
            self.status_task = self.spawn(self.check_status())

    async def check_status(self):
        # (De)activating MotionPlus toggles the extension flag transiently: the
        # clone sent 0x28 then 0x2a right after the mode write, which looped a
        # full reconfigure every ~3.5 s. Let it settle and compare the result.
        await asyncio.sleep(0.5)
        if self.closed or not self.initialized:
            return
        if self.parser.extension_connected != bool(self.parser.extension):
            self.schedule_reconfigure()
        elif not self.feature_lock.locked():
            # Unsolicited status stops data reports until 0x12 is sent again.
            async with self.feature_lock:
                await self.command(0x12, bytes([0x04, self.mode]))

    def schedule_reconfigure(self):
        if not self.reconfigure_task or self.reconfigure_task.done():
            self.reconfigure_task = self.spawn(self.reconfigure())

    async def initialize(self, led_mask):
        self.state.phase = "initializing"
        self.publish(self.state)
        await self.command(0x11, bytes([led_mask]))
        await self.command(0x15, b"\0", response=0x20)
        for address in (0x16, 0x20):
            try:
                self.parser.accel = AccelCalibration.from_bytes(await self.read(address, 10))
                break
            except (ReportError, ValueError) as exc:
                log.warning("%s calibration: %s", self.state.address, exc)
        self.state.calibration["accelerometer"] = self.parser.accel.source
        if self.want_ir:
            try:
                await self.setup_ir()
                self.ir_enabled = True
            except ReportError as exc:
                self.state.error = f"IR unavailable: {exc}"
                log.warning(self.state.error)
        self.state.capabilities["ir"] = self.ir_enabled
        await self.reconfigure()
        self.initialized = True
        self.state.connected, self.state.phase = True, "ready"
        self.publish(self.state)
        self.spawn(self.watchdog())

    async def setup_ir(self):
        await self.command(0x13, b"\x06")
        await self.command(0x1A, b"\x06")
        await self.write(0x04B00030, b"\x08")
        await asyncio.sleep(0.05)
        await self.write(0x04B00000, bytes.fromhex("02 00 00 71 01 00 64 00 fe"))
        await self.write(0x04B0001A, bytes.fromhex("fd 05"))
        await self.write(0x04B00033, b"\x01")  # basic IR leaves room for extensions
        await self.write(0x04B00030, b"\x08")
        await asyncio.sleep(0.05)

    async def reconfigure(self):
        async with self.feature_lock:
            self.initialized = False
            try:
                await self.configure_extensions()
                if self.ir_enabled:
                    mode = 0x37  # buttons + accel + basic IR + 6 extension bytes
                elif self.parser.extension:
                    mode = 0x35
                else:
                    mode = 0x31
                await self.command(0x12, bytes([0x04, mode]))
                self.mode = mode
            finally:
                if self.state.connected:
                    self.initialized = True

    async def configure_extensions(self):
        self.last_extension_probe = time.monotonic()
        p, s = self.parser, self.state
        p.extension = s.extension = None
        s.nunchuk = s.gyro_dps = s.gyro_raw = None
        s.nunchuk_timestamp_us = s.gyro_timestamp_us = 0
        s.capabilities.update(motionplus=False, nunchuk=False)
        nunchuk = False
        # Deactivate MotionPlus before identifying/calibrating the downstream extension.
        try:
            await self.write(0x04A400F0, b"\x55")
            await self.write(0x04A400FB, b"\x00")
            await asyncio.sleep(0.05)
            identity = await self.read(0x04A400FA, 6)
            nunchuk = identity == bytes.fromhex("00 00 a4 20 00 00")
            if nunchuk:
                p.extension = "nunchuk"
                try:
                    data = await self.read(0x04A40020, 16)
                    zero = tuple((data[i] << 2) | ((data[3] >> (4 - 2 * i)) & 3) for i in range(3))
                    one = tuple((data[i + 4] << 2) | ((data[7] >> (4 - 2 * i)) & 3) for i in range(3))
                    ranges = (tuple(data[8:11]), tuple(data[11:14]))
                    if any(o <= z for z, o in zip(zero, one)) or any(not lo < center < hi for hi, lo, center in ranges):
                        raise ValueError("Invalid Nunchuk calibration")
                    p.nunchuk_calibration = (AccelCalibration(zero, one, "factory"), ranges)
                except (ReportError, ValueError):
                    p.nunchuk_calibration = None
                s.calibration["nunchuk"] = "factory" if p.nunchuk_calibration else "nominal-stick/raw-accel"
            elif identity not in (b"\xff" * 6, b"\x00" * 6):
                log.warning("Unsupported extension %s: %s", s.address, identity.hex())
        except ReportError:
            pass  # No extension responds at A4 when the port is empty.
        if self.want_motionplus:
            try:
                identity = await self.read(0x04A600FA, 6)
                if identity[2:4] == b"\xa6\x20" and identity[5] == 5:
                    try:
                        p.set_gyro_calibration(await self.read(0x04A60020, 32))
                    except (ReportError, ValueError) as exc:
                        p.gyro_blocks = None
                        log.warning("MotionPlus factory calibration unavailable: %s", exc)
                    await self.write(0x04A600FE, bytes([5 if nunchuk else 4]))
                    await asyncio.sleep(0.1)
                    p.extension = "motionplus+nunchuk" if nunchuk else "motionplus"
                    s.capabilities["motionplus"] = True
                    s.calibration["motionplus"] = "factory" if p.gyro_blocks else "nominal"
            except ReportError:
                pass
        s.capabilities["nunchuk"] = nunchuk
        s.extension = p.extension
        self.publish(s)

    async def watchdog(self):
        while not self.closed:
            await asyncio.sleep(2)
            if time.monotonic() - self.last_packet > 10:
                self.state.disconnect("No HID reports for 10 seconds")
                self.publish(self.state)
                await self.connection.disconnect()
                return
            if self.feature_lock.locked():
                continue
            if time.monotonic() - self.last_status > 30:
                try:
                    await self.command(0x15, b"\0", response=0x20)
                except ReportError as exc:
                    log.warning("Status update %s: %s", self.state.address, exc)
                    self.last_status = time.monotonic()
            if self.want_motionplus and not self.state.capabilities["motionplus"] and time.monotonic() - self.last_extension_probe > 8:
                self.last_extension_probe = time.monotonic()
                try:
                    identity = await self.read(0x04A600FA, 6)
                    if identity[2:4] == b"\xa6\x20" and identity[5] == 5:
                        self.schedule_reconfigure()
                except ReportError:
                    pass

    async def set_led(self, mask):
        if not isinstance(mask, int) or mask < 0 or mask > 240 or mask & 15:
            raise ValueError("LED mask must contain only bits 0x10..0x80")
        await self.command(0x11, bytes([mask]))

    async def rumble(self, duration_ms):
        if not isinstance(duration_ms, int) or not 0 <= duration_ms <= 5000:
            raise ValueError("duration_ms must be 0..5000")
        if self.rumble_task:
            self.rumble_task.cancel()
            await asyncio.gather(self.rumble_task, return_exceptions=True)
        self.rumbling = duration_ms > 0
        self.send(0x10)
        async def stop():
            try:
                await asyncio.sleep(duration_ms / 1000)
            finally:
                self.rumbling = False
                if not self.closed:
                    self.send(0x10)
        self.rumble_task = self.spawn(stop()) if duration_ms else None

    async def calibrate(self):
        if not self.state.capabilities["motionplus"]:
            raise ValueError("No MotionPlus detected; accelerometer uses factory calibration")
        if self.gyro_samples is not None:
            raise ValueError("Calibration already running")
        self.gyro_samples = []
        try:
            await asyncio.sleep(3)
            samples = self.gyro_samples
            if len(samples) < 30:
                raise ValueError("Not enough gyro samples; keep the connected controller still")
            axes = list(zip(*samples))
            if any(statistics.pstdev(axis) > 2 for axis in axes):
                raise ValueError("Controller moved during calibration")
            self.parser.gyro_bias = tuple(old + statistics.mean(axis) for old, axis in zip(self.parser.gyro_bias, axes))
            self.state.calibration["gyro_bias"] = list(self.parser.gyro_bias)
            self.publish(self.state)
            return self.state.calibration
        finally:
            self.gyro_samples = None

    async def close(self):
        if self.closed:
            return
        self.initialized = False
        self.rumbling = False
        with contextlib.suppress(Exception):
            self.send(0x10)
        self.closed = True
        if self.pending and not self.pending["future"].done():
            self.pending["future"].set_exception(ReportError("Disconnected"))
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.state.disconnect(self.state.error)
        self.publish(self.state)
