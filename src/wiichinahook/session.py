"""One HID session, serialized memory transactions and sensor initialization."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import statistics
import time

from .config import COMBOS, SlotOptions
from .wiimote import AccelCalibration, ReportParser, output_report

log = logging.getLogger(__name__)


class ReportError(RuntimeError):
    pass


class WiimoteSession:
    def __init__(self, state, connection, publish, *, ir=True, motionplus=True, readable=True):
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
        self.sound_task = None
        self.speaker_volume = None   # set while the speaker is configured (speaker.py)
        self.speaker_off = None      # idle switch-off timer
        self.tasks = set()
        self.want_ir, self.want_motionplus = ir, motionplus
        # False behind a DolphinBar: it drops the clone's memory-read replies.
        self.readable = readable
        self.ext_probe = None
        self.ir_enabled = False
        self.initialized = False
        self.closed = False
        self.reconfigure_task = None
        self.status_task = None
        self.mode = 0x30
        self.last_packet = time.monotonic()
        # Reports of the configured mode only: an empty DolphinBar slot keeps
        # emitting stale 0x30 reports, so any-report liveness would never expire.
        self.last_data = time.monotonic()
        self.last_extension_probe = 0.0
        self.gyro_samples = None
        self.axis_samples = None
        self.accel_samples = None
        self.options = SlotOptions()
        self.combo_since = None
        self.combo_fired = False
        self.quick_task = None
        self.on_bias_changed = None  # manager hook to persist a new gyro bias
        self.led_mask = 0x10
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
            # Keep the first cause (e.g. the watchdog's) when it closed the channel.
            already = not self.state.connected and self.state.error
            self.state.disconnect(self.state.error if already else "HID channel closed")
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
        # Only peripheral registers (speaker, extensions, IR camera) are writable.
        # Never write EEPROM/Mii data.
        if address >> 16 not in (0x04A2, 0x04A4, 0x04A6, 0x04B0) or not 1 <= len(data) <= 16:
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
        if report == self.mode:
            self.last_data = self.last_packet
        if self.ext_probe is not None and report in (0x35, 0x37):
            self.ext_probe.append(p[15:21] if report == 0x37 else p[5:11])
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
        # Calibrations see the rates before the noise gate (it would hide what they measure).
        new_gyro = self.state.gyro_timestamp_us == self.state.timestamp_us
        if self.gyro_samples is not None and new_gyro:
            if all(self.parser.gyro_slow):
                self.gyro_samples.append(self.parser.gyro_ungated)
                if self.accel_samples is not None and self.state.accel_g:
                    self.accel_samples.append(self.state.accel_g)
        if self.axis_samples is not None and new_gyro and self.state.accel_g:
            self.axis_samples.append((self.state.gyro_timestamp_us / 1e6, self.state.accel_g,
                                      self.parser.gyro_ungated))
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
        if self.initialized:
            raw = self.state.buttons
            self.check_combo(raw)
            self.state.buttons = self.combo_filter(raw)
        self.publish(self.state)

    # -- per-slot options ------------------------------------------------------
    def apply_options(self, options: SlotOptions):
        self.options = options
        self.parser.ir_heading = options.ir_calibration
        if not options.ir_calibration:
            self.state.calibration.pop("heading", None)
        self.combo_since, self.combo_fired = None, False
        self.combo_down, self.combo_latched, self.combo_taps = {}, 0, {}

    COMBO_TAP = 0.06     # s a quick tap of one is still sent for

    def combo_filter(self, buttons):
        """Hide the recalibration combination from every output (Xbox, DSU, PC, API):
        a member of a multi-button combination does nothing for the slot's combination
        window (combo_window_ms) while the others may still come; once
        the whole combination is held its buttons stay hidden until released. A
        member tapped on its own still goes out as a short press."""
        mask = COMBOS.get(self.options.combo, 0)
        if not self.options.quick_calibration or bin(mask).count("1") < 2:
            self.combo_down, self.combo_latched, self.combo_taps = {}, 0, {}
            return buttons
        now = time.monotonic()
        window = self.options.combo_window_ms / 1000
        waiting = 0
        for bit in (1 << i for i in range(16) if mask >> i & 1):
            if buttons & bit:
                since = self.combo_down.setdefault(bit, now)
                if not self.combo_latched & bit and now - since < window:
                    waiting |= bit
            elif bit in self.combo_down:                   # released
                since = self.combo_down.pop(bit)
                if not self.combo_latched & bit and now - since < window:
                    self.combo_taps[bit] = now + self.COMBO_TAP
                self.combo_latched &= ~bit
        if buttons & mask == mask:
            self.combo_latched |= mask
        self.combo_taps = {bit: end for bit, end in self.combo_taps.items() if now < end}
        taps = 0
        for bit in self.combo_taps:
            taps |= bit
        return (buttons & ~(self.combo_latched | waiting)) | taps

    def check_combo(self, buttons=None):
        buttons = self.state.buttons if buttons is None else buttons
        mask = COMBOS.get(self.options.combo, 0)
        if not self.options.quick_calibration or not mask or buttons & mask != mask:
            self.combo_since, self.combo_fired = None, False
            return
        now = time.monotonic()
        if self.combo_since is None:
            self.combo_since = now
        elif not self.combo_fired and now - self.combo_since >= self.options.combo_hold_ms / 1000:
            self.combo_fired = True  # once per press
            if not self.quick_task or self.quick_task.done():
                self.quick_task = self.spawn(self.quick_calibrate())

    async def quick_calibrate(self, still=1.0):
        """Games-style quick calibration: short rumble, ~1 s of samples; if the remote
        was still, refresh the gyro bias; always recenter the orientation. Double rumble
        = bias and recenter, long rumble = recentered only (it moved)."""
        await self.rumble(150)
        await asyncio.sleep(0.3)
        bias_updated = False
        if self.state.capabilities["motionplus"] and self.gyro_samples is None and self.axis_samples is None:
            self.gyro_samples = []
            try:
                await asyncio.sleep(still)
                samples = self.gyro_samples
            finally:
                self.gyro_samples = None
            axes = list(zip(*samples)) if len(samples) >= 15 else []
            if axes and all(statistics.pstdev(axis) <= 2.5 for axis in axes):
                self.parser.gyro_bias = tuple(old + statistics.mean(axis) / scale for old, axis, scale
                                              in zip(self.parser.gyro_bias, axes, self.parser.gyro_scale))
                self.state.calibration["gyro_bias"] = list(self.parser.gyro_bias)
                bias_updated = True
                if self.on_bias_changed:
                    self.on_bias_changed(self.parser.gyro_bias)
        orientation = self.parser.orientation
        orientation.recenter(self.state.accel_g)        # heading and pitch (neutral grip)
        self.state.calibration["recenter_seq"] = self.state.calibration.get("recenter_seq", 0) + 1
        self.state.calibration["pitch_offset_deg"] = round(math.degrees(orientation.pitch_offset), 1)
        self.publish(self.state)
        if bias_updated:
            await self.rumble(120)
            await asyncio.sleep(0.25)
            await self.rumble(120)
        else:
            await self.rumble(500)
        return {"bias_updated": bias_updated}

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
        self.led_mask = led_mask
        await self.command(0x11, bytes([led_mask]))
        await self.command(0x15, b"\0", response=0x20)
        for address in ((0x16, 0x20) if self.readable else ()):
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
                self.last_data = time.monotonic()
            finally:
                if self.state.connected:
                    self.initialized = True

    async def configure_extensions(self):
        if not self.readable:
            return await self.configure_extensions_blind()
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

    async def configure_extensions_blind(self):
        """Identify extensions without memory reads (DolphinBar, 2026-10-06 tests):
        the status flag reports a Nunchuk while MotionPlus is inactive, and an
        active MotionPlus is recognised by the shape of the extension bytes."""
        self.last_extension_probe = time.monotonic()
        p, s = self.parser, self.state
        p.extension = s.extension = None
        s.nunchuk = s.gyro_dps = s.gyro_raw = None
        s.nunchuk_timestamp_us = s.gyro_timestamp_us = 0
        s.capabilities.update(motionplus=False, nunchuk=False)
        p.nunchuk_calibration = None
        # Deactivates MotionPlus and initialises an unencrypted Nunchuk; with an
        # empty port the remote may answer these writes with an error.
        with contextlib.suppress(ReportError):
            await self.write(0x04A400F0, b"\x55")
            await self.write(0x04A400FB, b"\x00")
        await asyncio.sleep(0.05)
        nunchuk = bool((await self.command(0x15, b"\0", response=0x20))[2] & 2)
        motionplus = False
        if self.want_motionplus:
            try:
                await self.write(0x04A600F0, b"\x55")
                await self.write(0x04A600FE, bytes([5 if nunchuk else 4]))
                await asyncio.sleep(0.3)
                motionplus = await self.motionplus_active(nunchuk)
            except ReportError:
                motionplus = False
            if not motionplus and nunchuk:
                with contextlib.suppress(ReportError):  # restore plain Nunchuk data
                    await self.write(0x04A400F0, b"\x55")
                    await self.write(0x04A400FB, b"\x00")
        if motionplus:
            p.extension = "motionplus+nunchuk" if nunchuk else "motionplus"
            s.capabilities["motionplus"] = True
            s.calibration["motionplus"] = "nominal"
        elif nunchuk:
            p.extension = "nunchuk"
        if nunchuk:
            s.calibration["nunchuk"] = "nominal-stick/raw-accel"
        s.capabilities["nunchuk"] = nunchuk
        s.extension = p.extension
        self.publish(s)

    async def motionplus_active(self, nunchuk):
        """MotionPlus packets end with bits ..10. In plain Nunchuk data those bits
        are C/Z, so with a Nunchuk require the passthrough mix of MotionPlus (..10)
        and Nunchuk (..00) packets, which holding buttons cannot produce."""
        self.ext_probe = []
        try:
            await self.command(0x12, bytes([0x04, 0x37 if self.ir_enabled else 0x35]))
            await asyncio.sleep(0.3)
            samples = [e for e in self.ext_probe if len(e) == 6 and e != b"\xff" * 6]
        finally:
            self.ext_probe = None
        if len(samples) < 10:
            return False
        kinds = [e[5] & 3 for e in samples]
        share = lambda k: kinds.count(k) / len(kinds)
        if nunchuk:
            return share(2) >= 0.2 and share(0) >= 0.1
        return share(2) >= 0.8

    async def watchdog(self):
        while not self.closed:
            await asyncio.sleep(2)
            if time.monotonic() - self.last_data > 10 and not self.feature_lock.locked():
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
        self.led_mask = mask

    async def blink_led(self, mask, times=3, period=0.3):
        """Flash `mask` (e.g. the LED of a gamepad mode), then restore the player LED."""
        try:
            for _ in range(times):
                self.send(0x11, bytes([mask]))
                await asyncio.sleep(period)
                self.send(0x11, b"\x00")
                await asyncio.sleep(period)
        finally:
            if not self.closed:
                self.send(0x11, bytes([self.led_mask]))

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

    async def play_sound(self, adpcm, volume):
        """Play encoded audio on the speaker (speaker.py). A new sound cuts the current
        one; returns False if this one was cut short."""
        from .speaker import play
        if self.sound_task:
            self.sound_task.cancel()
            await asyncio.wait({self.sound_task})
        task = self.sound_task = self.spawn(play(self, adpcm, volume))
        await asyncio.wait({task})   # never propagate a cancellation into the caller
        if self.sound_task is task:
            self.sound_task = None
        if task.cancelled():
            return False
        if task.exception():
            raise task.exception()
        return True

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
            # gyro_dps is already scaled; the bias lives in nominal units.
            self.parser.gyro_bias = tuple(old + statistics.mean(axis) / scale for old, axis, scale
                                          in zip(self.parser.gyro_bias, axes, self.parser.gyro_scale))
            self.state.calibration["gyro_bias"] = list(self.parser.gyro_bias)
            self.publish(self.state)
            return self.state.calibration
        finally:
            self.gyro_samples = None

    NOISE_MOVED_DPS = 12.0      # a 99th-percentile deviation above this = it was moved
    NOISE_MOVED_G = 0.03        # accelerometer standard deviation that means it was touched
    NOISE_MARGIN = 1.25         # gate = margin x the measured noise
    NOISE_GATE_RANGE = (0.3, 10.0)

    async def calibrate_noise(self, seconds=10.0):
        """Remote resting on a table for `seconds`: measure each gyro axis' noise and
        bias, correct the bias and set a per-axis noise gate just above the noise.
        Rumble: short = start (do not touch), double = done, long = it moved."""
        if not self.state.capabilities["motionplus"]:
            raise ValueError("No MotionPlus detected")
        if self.gyro_samples is not None or self.axis_samples is not None:
            raise ValueError("Calibration already running")
        await self.rumble(150)
        await asyncio.sleep(0.4)                 # let the motor stop before measuring
        self.gyro_samples, self.accel_samples = [], []
        try:
            await asyncio.sleep(seconds)
            samples, accel = self.gyro_samples, self.accel_samples
        finally:
            self.gyro_samples = self.accel_samples = None
        if len(samples) < 20 * seconds:
            raise ValueError("Not enough gyro samples; is the remote connected and still?")
        axes = list(zip(*samples))
        means = [statistics.mean(axis) for axis in axes]
        noise = []
        for axis, mean in zip(axes, means):
            deviations = sorted(abs(v - mean) for v in axis)
            noise.append(deviations[int(0.99 * (len(deviations) - 1))])
        moved = max(noise) > self.NOISE_MOVED_DPS or (
            len(accel) > 10 and max(statistics.pstdev(a) for a in zip(*accel)) > self.NOISE_MOVED_G)
        if moved:
            await self.rumble(600)
            raise ValueError("The remote moved during the noise calibration; leave it on the table untouched")
        low, high = self.NOISE_GATE_RANGE
        gate = tuple(round(min(high, max(low, self.NOISE_MARGIN * n)), 2) for n in noise)
        self.parser.gyro_bias = tuple(old + mean / scale for old, mean, scale
                                      in zip(self.parser.gyro_bias, means, self.parser.gyro_scale))
        self.parser.gyro_deadband = gate
        self.state.calibration["gyro_bias"] = list(self.parser.gyro_bias)
        self.state.calibration["gyro_noise_dps"] = list(gate)
        self.publish(self.state)
        await self.rumble(120)
        await asyncio.sleep(0.25)
        await self.rumble(120)
        return {"gyro_noise_dps": list(gate), "noise_dps": [round(n, 2) for n in noise],
                "bias_dps": [round(m, 2) for m in means], "samples": len(samples)}

    def clear_noise(self):
        self.parser.gyro_deadband = (0.0,) * 3
        self.state.calibration.pop("gyro_noise_dps", None)
        self.publish(self.state)
        return {"gyro_noise_dps": [0.0, 0.0, 0.0]}

    async def calibrate_axis(self, axis, still=1.2, turn=5.0):
        """Guided scale/sign calibration of one MotionPlus axis (see calibration.py).
        Rumble cues: short = keep still, short again = turn slowly about the axis and
        hold, long = done."""
        from .calibration import fit_axis_scale
        if not self.state.capabilities["motionplus"]:
            raise ValueError("No MotionPlus detected")
        if self.gyro_samples is not None or self.axis_samples is not None:
            raise ValueError("Calibration already running")
        await self.rumble(200)
        await asyncio.sleep(0.3)  # let the rumble motor stop before measuring "still"
        self.axis_samples = []
        try:
            await asyncio.sleep(still)
            await self.rumble(200)
            await asyncio.sleep(turn)
            samples = self.axis_samples
        finally:
            self.axis_samples = None
        await self.rumble(600)
        result = fit_axis_scale(samples, axis, still_seconds=still - 0.1)
        scale = list(self.parser.gyro_scale)
        scale[result["channel"]] *= result["factor"]
        self.parser.gyro_scale = tuple(scale)
        self.state.calibration["gyro_scale"] = [round(v, 4) for v in scale]
        self.publish(self.state)
        return dict(result, gyro_scale=self.state.calibration["gyro_scale"])

    async def close(self):
        if self.closed:
            return
        self.initialized = False
        self.rumbling = False
        if self.speaker_off:
            self.speaker_off.cancel()
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
