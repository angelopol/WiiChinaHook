"""Mayflash DolphinBar transport (mode 4: one raw HID 057E:0306 interface per slot).

Validated with the clone on 2026-10-06: the bar forwards data, acks, status and
writes, but drops the clone's unpadded memory-read replies (0x21). Sessions
therefore run read-free (WiimoteSession(readable=False)). Pairing happens on the
bar itself (SYNC on the bar, then on the Wiimote); the Bluetooth address of the
remote is not visible, so each slot reports a fixed locally administered MAC.
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict, replace
import json
import logging
import queue
import threading
import time

from .calibration import GYRO_SCALE_FRAME
from .config import slot_options_from
from .session import ReportError, WiimoteSession
from .wiimote import AccelCalibration, WiimoteState

log = logging.getLogger(__name__)

WIIMOTE_VID = 0x057E
WIIMOTE_PIDS = (0x0306, 0x0330)
REPORT_SIZE = 22
# Factory accelerometer calibration read over direct Bluetooth from the clone
# 00:17:AB:AE:1A:6D; also typical of genuine remotes (zero 0x80, 1 g 0x9a).
TYPICAL_ACCEL = bytes.fromhex("80 80 80 00 9a 9a 9a 00 40 e3")


def slot_address(slot: int) -> str:
    # Locally administered unicast MAC ("DB" + slot) so DSU clients can tell slots apart.
    return f"02:00:44:42:00:{slot:02X}"


def bar_devices(enumerate_hid=None):
    """Map DolphinBar slot (0..3) -> hid path. The bar exposes all four slots
    even when no remote is paired."""
    if enumerate_hid is None:
        import hid
        enumerate_hid = hid.enumerate
    devices = [d for d in enumerate_hid(WIIMOTE_VID) if d["product_id"] in WIIMOTE_PIDS]
    devices.sort(key=lambda d: (d.get("interface_number", -1), d["path"]))
    slots = {}
    for index, d in enumerate(devices[:4]):
        number = d.get("interface_number", -1)
        slot = number if number in range(4) and number not in slots else index
        slots.setdefault(slot, d["path"])
    return slots


class BarLink:
    """One DolphinBar slot. Acts as the HID interrupt channel and the connection
    for WiimoteSession; a reader thread feeds input reports into the event loop and a
    writer thread sends output reports in order. A HID write is a blocking USB
    transfer: done on the event loop, four remotes streaming speaker audio (~300
    writes/s) would stall input and DSU. Each slot is its own HID device, so the four
    writers run in parallel; one handle never gets concurrent writes (hidapi forbids it)."""
    psm = 0x13
    thread_safe_write = True   # write() only enqueues for the writer thread (speaker.stream)

    def __init__(self, path, loop, opener=None):
        if opener is None:
            import hid
            opener = hid.device
        self.loop = loop
        self.device = opener()
        self.device.open_path(path)
        self.sink = None
        self.handlers = {}
        self.closed = False
        self.stop = threading.Event()
        self.outbox = queue.SimpleQueue()
        self.thread = threading.Thread(target=self.reader, name=f"dolphinbar-{path!r}", daemon=True)
        self.writer = threading.Thread(target=self.write_loop, name=f"dolphinbar-out-{path!r}", daemon=True)
        self.thread.start()
        self.writer.start()

    def reader(self):
        while not self.stop.is_set():
            try:
                data = bytes(self.device.read(64, 100))
            except (OSError, ValueError) as exc:
                if not self.stop.is_set():
                    self.post(self.lost, f"DolphinBar read failed: {exc}")
                return
            if data and not self.stop.is_set():
                self.post(self.deliver, data)

    def post(self, callback, *args):
        try:
            self.loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:  # event loop already closed during shutdown
            self.stop.set()

    def deliver(self, data):
        if self.sink and not self.closed:
            self.sink(b"\xa1" + data)

    def on(self, event, handler):
        self.handlers.setdefault(event, []).append(handler)

    def write(self, data):
        # data carries the 0xA2 output-transaction header used over Bluetooth.
        if self.closed:
            raise ReportError("DolphinBar slot is closed")
        self.outbox.put(bytes(data[1:]).ljust(REPORT_SIZE, b"\0"))

    def write_loop(self):
        while True:
            report = self.outbox.get()
            if report is None:                    # close(): everything before it was sent
                return
            try:
                self.device.write(report)
            except (OSError, ValueError) as exc:
                self.post(self.lost, f"DolphinBar write failed: {exc}")
                return

    def lost(self, reason):
        if not self.closed:
            log.info("DolphinBar slot lost: %s", reason)
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        self.outbox.put(None)                     # let queued reports (e.g. rumble off) go out
        # Never close the hid handle while a thread may be inside read() or write().
        for thread in (self.writer, self.thread):
            if threading.current_thread() is not thread:
                thread.join(1.0)
        handlers = self.handlers.get("close", [])
        self.handlers.clear()
        for handler in handlers:
            handler()
        with contextlib.suppress(Exception):
            self.device.close()

    async def disconnect(self):
        self.close()


class SlotStore:
    """Per-slot settings that cannot be read through the bar (gyro bias)."""

    def __init__(self, directory):
        self.path = directory / "dolphinbar.json"
        try:
            self.slots = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        except ValueError:
            log.warning("Ignoring invalid %s", self.path)
            self.slots = {}

    def get(self, slot):
        return self.slots.get(str(slot), {})

    def update(self, slot, **values):
        self.slots.setdefault(str(slot), {}).update(values)
        self.save()

    def remove(self, slot):
        self.slots.pop(str(slot), None)
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.slots, indent=2), encoding="utf-8")
        temporary.replace(self.path)


class DolphinBarManager:
    """Same interface as bt.WiimoteManager, for the API and DSU."""

    def __init__(self, config, publish, *, devices=bar_devices, opener=None):
        self.config, self.publish = config, publish
        self.slot_options = list(config.slots)
        self.devices, self.opener = devices, opener
        self.sessions = {}
        self.states = {}
        self.probing = set()
        self.tasks = set()
        self.ready = asyncio.Event()
        self.stopping = False
        self.adapter_error = None
        self.store = SlotStore(config.state_dir)

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        def done(t):
            self.tasks.discard(t)
            if not t.cancelled() and t.exception():
                log.warning("DolphinBar task: %s", t.exception())
        task.add_done_callback(done)
        return task

    def snapshot(self):
        return {"adapter": "DolphinBar", "mode": "dolphinbar", "ready": self.ready.is_set(),
                "error": self.adapter_error, "pairing": False,
                "devices": [s.to_dict() for s in sorted(self.states.values(), key=lambda s: s.slot)]}

    async def run(self):
        try:
            while not self.stopping:
                try:
                    slots = self.devices()
                except Exception as exc:  # hidapi missing or enumeration failure
                    slots, self.adapter_error = {}, f"{type(exc).__name__}: {exc}"
                if slots:
                    if not self.ready.is_set():
                        log.info("DolphinBar ready (%d slots); pair remotes with SYNC on the bar", len(slots))
                    self.adapter_error = None
                    self.ready.set()
                    for slot, path in slots.items():
                        if slot not in self.sessions and slot not in self.probing:
                            self.probing.add(slot)
                            self.spawn(self.probe(slot, path))
                else:
                    if self.ready.is_set() or self.adapter_error is None:
                        log.warning("No DolphinBar in mode 4 (HID %04X:0306) found", WIIMOTE_VID)
                    self.adapter_error = self.adapter_error or "DolphinBar not found; set it to mode 4"
                    self.ready.clear()
                await asyncio.sleep(2)
        finally:
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            for slot in list(self.sessions):
                await self.drop(slot, "DolphinBar transport stopped")

    async def probe(self, slot, path):
        """A remote is present when the slot answers a status request."""
        link = None
        try:
            link = BarLink(path, asyncio.get_running_loop(), self.opener)
            answered = asyncio.get_running_loop().create_future()
            def sink(data):
                if len(data) > 1 and data[1] == 0x20 and not answered.done():
                    answered.set_result(True)
            link.sink = sink
            link.write(bytes([0xA2, 0x15, 0x00]))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(answered), 1.0)
            if not answered.done() or link.closed:
                return
            await self.start_session(slot, link)
        except (ReportError, OSError) as exc:
            # OSError: the slot is open elsewhere (e.g. Dolphin) or was unplugged.
            log.debug("Probe slot %d: %s", slot, exc)
        finally:
            self.probing.discard(slot)
            # Also on cancellation (shutdown): never leak a reader thread/handle.
            session = self.sessions.get(slot)
            if link and (session is None or session.connection is not link):
                link.close()

    async def start_session(self, slot, link):
        state = self.states.get(slot) or WiimoteState(slot_address(slot), slot)
        self.states[slot] = state
        state.error = None
        session = WiimoteSession(state, link, self.publish, ir=self.config.ir,
                                 motionplus=self.config.motionplus, readable=False)
        settings = self.store.get(slot)
        accel = AccelCalibration.from_bytes(bytes.fromhex(settings.get("accel", TYPICAL_ACCEL.hex())))
        session.parser.accel = replace(accel, source="stored" if "accel" in settings else "typical")
        session.parser.gyro_bias = tuple(settings.get("gyro_bias", (0.0, 0.0, 0.0)))
        if "gyro_bias" in settings:
            state.calibration["gyro_bias"] = list(session.parser.gyro_bias)
        if settings.get("gyro_scale_frame") == GYRO_SCALE_FRAME:  # older factors used wrong axes
            session.parser.gyro_scale = tuple(settings["gyro_scale"])
            state.calibration["gyro_scale"] = list(session.parser.gyro_scale)
        if settings.get("gyro_noise"):
            session.parser.gyro_deadband = tuple(settings["gyro_noise"])
            state.calibration["gyro_noise_dps"] = list(session.parser.gyro_deadband)
        self.sessions[slot] = session
        session.apply_options(self.slot_options[slot])
        session.on_bias_changed = lambda bias: self.store.update(slot, gyro_bias=list(bias))
        link.on("close", lambda: self.spawn(self.drop(slot, "Remote disconnected from the DolphinBar"))
                if self.sessions.get(slot) is session else None)
        session.attach(link)
        log.info("DolphinBar slot %d: remote connected", slot)
        try:
            await session.initialize(0x10 << slot)
        except Exception as exc:
            state.error = f"{type(exc).__name__}: {exc}"
            log.warning("DolphinBar slot %d: %s", slot, exc)
            link.close()

    async def drop(self, slot, reason):
        session = self.sessions.pop(slot, None)
        if session is None:
            return
        if session.state.error is None and reason:
            session.state.error = reason
        await session.close()
        session.connection.close()
        log.info("DolphinBar slot %d: %s", slot, reason)

    async def pair(self, seconds=20, mode="sync", address=None):
        raise ValueError("With the DolphinBar, pair on the bar: press its SYNC button, then SYNC on the Wiimote")

    def session_for(self, slot):
        if not isinstance(slot, int) or slot not in range(4):
            raise ValueError("slot must be 0..3")
        session = self.sessions.get(slot)
        if session is None or not session.state.connected:
            raise ValueError("Slot is not connected")
        return session

    async def forget(self, slot):
        if not isinstance(slot, int) or slot not in range(4):
            raise ValueError("slot must be 0..3")
        self.store.remove(slot)
        return {"forgotten_settings": slot, "note": "Unpair the remote on the DolphinBar itself"}

    async def calibrate(self, slot):
        session = self.session_for(slot)
        result = await session.calibrate()
        self.store.update(slot, gyro_bias=list(session.parser.gyro_bias))
        return result

    def set_slot_options(self, slot, **changes):
        """Change a slot's quick/IR calibration options live (the GUI also saves them)."""
        if not isinstance(slot, int) or slot not in range(4):
            raise ValueError("slot must be 0..3")
        unknown = set(changes) - {"quick_calibration", "combo", "ir_calibration", "combo_hold_ms",
                                 "combo_window_ms"}
        if unknown:
            raise ValueError(f"Unknown option: {', '.join(sorted(unknown))}")
        current = asdict(self.slot_options[slot])
        current.update({k: v for k, v in changes.items() if v is not None})
        options = slot_options_from(current)
        self.slot_options[slot] = options
        for session in self.sessions.values():
            if session.state.slot == slot:
                session.apply_options(options)
        return dict(asdict(options), slot=slot)

    async def calibrate_noise(self, slot, seconds=10.0, reset=False):
        session = self.session_for(slot)
        result = session.clear_noise() if reset else await session.calibrate_noise(seconds)
        self.store.update(slot, gyro_bias=list(session.parser.gyro_bias),
                          gyro_noise=list(session.parser.gyro_deadband))
        return result

    async def calibrate_axis(self, slot, axis):
        session = self.session_for(slot)
        result = await session.calibrate_axis(axis)
        self.store.update(slot, gyro_scale=list(session.parser.gyro_scale), gyro_scale_frame=GYRO_SCALE_FRAME)
        return result
