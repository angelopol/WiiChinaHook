"""Bumble owns the adapter; this module adds Wii binary PIN and session lifecycle."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict
import logging
import time

from bumble import hci, l2cap
from bumble.core import PhysicalTransport
from bumble.device import Connection, Device, DeviceConfiguration
from bumble.host import Host
from bumble.keys import JsonKeyStore
from bumble.snoop import BtSnooper
from bumble.transport import open_transport_or_link

from .config import normalize_address, slot_options_from
from .scanner import extract_name, is_probable_wiimote
from .session import WiimoteSession
from .storage import Registry
from .wiimote import WiimoteState
from .bumble_compat import install_l2cap_hint_compat
from .calibration import GYRO_SCALE_FRAME

log = logging.getLogger(__name__)

# Auth Failure / PIN or Key Missing: the remote no longer holds our link key.
KEY_REJECTED = (hci.HCI_AUTHENTICATION_FAILURE_ERROR, hci.HCI_PIN_OR_KEY_MISSING_ERROR)


def retry_delay(failures: int) -> float:
    # Each outgoing page blocks the radio ~5 s; absent remotes must back off
    # so they do not starve the others. Wiimotes also page us on button press.
    return min(5.0 * 2 ** max(failures - 1, 0), 60.0)


def legacy_pin(host: hci.Address, peer: hci.Address, mode: str) -> bytes:
    # Bumble Address bytes already use Bluetooth's little-endian address order.
    return bytes(peer if mode == "temporary" else host)


class WiiDevice(Device):
    manager = None

    def on_pin_code_request(self, address):
        # Override the host handler (address argument, before the base decorator).
        # Bumble's default handler UTF-8 encodes strings, corrupting binary PINs.
        entry = self.manager.registry.devices.get(address.to_string(False), {})
        pin = legacy_pin(self.public_address, address, entry.get("pin_mode", self.manager.pair_mode))
        self.manager.spawn(self.host.send_sync_command(hci.HCI_PIN_Code_Request_Reply_Command(
            bd_addr=address, pin_code_length=6, pin_code=pin)))

    def on_connection_request(self, address, class_of_device, link_type):
        if link_type != hci.HCI_Connection_Complete_Event.LinkType.ACL:
            super().on_connection_request(address, class_of_device, link_type)
        elif self.manager.allowed(address.to_string(False)):
            # Like the Wii, accept a reconnecting remote by becoming central.
            # Bumble always remains peripheral (role 0x01); the clone then drops
            # the link after ~100 ms with 0x13 (trace 2026-10-05).
            self.manager.incoming.add(address.to_string(False))
            self.pending_connections[address] = Connection(
                device=self, handle=0, transport=PhysicalTransport.BR_EDR,
                self_address=self.public_address, self_resolvable_address=None,
                peer_address=address, peer_resolvable_address=None,
                role=hci.Role.PERIPHERAL, parameters=Connection.Parameters(0, 0, 0))
            self.host.send_command_sync(hci.HCI_Accept_Connection_Request_Command(
                bd_addr=address, role=0x00))
        else:
            self.manager.spawn(self.host.send_sync_command(hci.HCI_Reject_Connection_Request_Command(
                bd_addr=address, reason=0x0D)))


class WiimoteManager:
    def __init__(self, config, publish):
        self.config, self.publish = config, publish
        self.slot_options = list(config.slots)
        self.device = None
        self.registry = None
        self.sessions = {}
        self.states = {}
        self.tasks = set()
        self.connecting = set()
        self.incoming = set()
        self.pair_until = 0.0
        self.pair_mode = "sync"
        self.pair_task = None
        self.adapter_address = None
        self.adapter_error = None
        self.ready = asyncio.Event()
        self.stopping = False
        self.adapter_active = False
        self.retry_after = {}
        self.failures = {}
        self.auth_failures = set()

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        def done(t):
            self.tasks.discard(t)
            if not t.cancelled() and t.exception():
                log.warning("Bluetooth task: %s", t.exception())
        task.add_done_callback(done)
        return task

    def schedule_retry(self, address, minimum=0.0):
        self.failures[address] = self.failures.get(address, 0) + 1
        self.retry_after[address] = time.monotonic() + max(retry_delay(self.failures[address]), minimum)

    async def delete_key(self, address):
        # Bumble keys entries by str(Address), which carries a "/P" type suffix.
        with contextlib.suppress(KeyError):
            await self.device.keystore.delete(str(hci.Address(address, hci.Address.PUBLIC_DEVICE_ADDRESS)))

    def allowed(self, address):
        return self.registry is not None and (address in self.registry.devices or
               (time.monotonic() < self.pair_until and len(self.registry.devices) < 4))

    def snapshot(self):
        return {"adapter": self.adapter_address, "mode": "bluetooth", "ready": self.ready.is_set(),
                "error": self.adapter_error, "pairing": time.monotonic() < self.pair_until,
                "devices": [s.to_dict() for s in sorted(self.states.values(), key=lambda s: s.slot)]}

    async def run(self):
        while not self.stopping:
            try:
                await self.run_adapter()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.adapter_error = f"{type(exc).__name__}: {exc}"
                log.error("Adapter %s unavailable: %s (close Dolphin if it owns the adapter)",
                          self.config.dongle.selector, self.adapter_error)
            if not self.stopping:
                await asyncio.sleep(3)

    async def run_adapter(self):
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        async with await open_transport_or_link(self.config.dongle.selector) as transport:
            dc = DeviceConfiguration()
            dc.name = "Nintendo RVL-001"
            dc.class_of_device = 0x000500
            dc.le_enabled = False
            dc.classic_enabled = True
            dc.classic_ssp_enabled = False
            dc.classic_sc_enabled = False
            dc.classic_smp_enabled = False
            dc.discoverable = False
            self.device = WiiDevice(config=dc, host=Host(transport.source, transport.sink))
            self.device.manager = self
            install_l2cap_hint_compat(self.device.l2cap_channel_manager)
            trace_path = self.config.state_dir / f"hci-{time.time_ns()}.btsnoop"
            with trace_path.open("wb", buffering=0) as trace:
                self.device.host.snooper = BtSnooper(trace)
                try:
                    await asyncio.wait_for(self.device.power_on(), 20)
                    self.adapter_address = self.device.public_address.to_string(False)
                    self.registry = Registry(self.config.state_dir, self.adapter_address)
                    self.device.keystore = JsonKeyStore(namespace=self.adapter_address,
                                                         filename=str(self.config.state_dir / "link-keys.json"))
                    for remote in self.config.wiimotes:
                        entry = self.registry.add(remote.address, remote.slot, remote.pin_mode)
                        entry["pin_mode"] = remote.pin_mode
                        if remote.led_mask is not None:
                            entry["led_mask"] = remote.led_mask
                    self.registry.save()
                    self.states = {a: WiimoteState(a, e["slot"]) for a, e in self.registry.devices.items()}
                    for state in self.states.values():
                        self.publish(state)
                    self.device.on("connection", self.on_connection)
                    self.device.on("inquiry_result", self.on_inquiry)
                    for psm in (0x11, 0x13):
                        self.device.create_l2cap_server(l2cap.ClassicChannelSpec(psm=psm, mtu=185), self.on_channel)
                    self.adapter_error = None
                    self.adapter_active = True
                    self.ready.set()
                    log.info("Adapter %s ready; HCI trace: %s", self.adapter_address, trace_path)
                    self.spawn(self.reconnect_loop())
                    await transport.source.terminated
                    raise ConnectionError("USB transport terminated")
                finally:
                    self.adapter_active = False
                    self.ready.clear()
                    self.pair_until = 0
                    for task in list(self.tasks):
                        task.cancel()
                    await asyncio.gather(*self.tasks, return_exceptions=True)
                    for session in list(self.sessions.values()):
                        await session.close()
                        with contextlib.suppress(Exception):
                            await asyncio.wait_for(session.connection.disconnect(), 2)
                    self.sessions.clear()
                    self.connecting.clear()
                    for state in self.states.values():
                        state.disconnect(self.adapter_error or "Adapter stopped")
                        self.publish(state)
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(self.device.host.send_sync_command(hci.HCI_Reset_Command()), 2)
                    self.device.host.snooper = None
                    self.device = None

    async def reconnect_loop(self):
        while True:
            # Paging blocks inquiry (COMMAND_DISALLOWED): no reconnects while pairing.
            pairing = time.monotonic() < self.pair_until
            for address in ([] if pairing else list(self.registry.devices)):
                if address not in self.sessions and address not in self.connecting and time.monotonic() >= self.retry_after.get(address, 0):
                    await self.connect(address)
            await asyncio.sleep(3)

    async def connect(self, address):
        if address in self.connecting or address in self.sessions or not self.ready.is_set():
            return
        self.connecting.add(address)
        self.incoming.discard(address)
        state = self.states.get(address)
        if state:
            state.phase = "connecting"
            self.publish(state)
        try:
            await self.device.connect(address, transport=PhysicalTransport.BR_EDR, timeout=8)
        except Exception as exc:
            self.schedule_retry(address)
            if state:
                state.disconnect(str(exc))
                self.publish(state)
            log.debug("Connect %s: %s", address, exc)
        finally:
            self.connecting.discard(address)

    def on_inquiry(self, address, class_of_device, data, rssi):
        text = address.to_string(False)
        if time.monotonic() >= self.pair_until:
            return
        if text in self.registry.devices or is_probable_wiimote(extract_name(data), class_of_device):
            if text not in self.registry.devices:
                try:
                    entry = self.registry.add(text, pin_mode=self.pair_mode)
                    self.states[text] = WiimoteState(text, entry["slot"])
                except ValueError:
                    return
            self.spawn(self.connect(text))

    def on_connection(self, connection):
        if not self.adapter_active:
            return
        address = connection.peer_address.to_string(False)
        if not self.allowed(address) or address in self.sessions:
            self.spawn(connection.disconnect())
            return
        entry = self.registry.add(address, pin_mode=self.pair_mode)
        state = self.states.setdefault(address, WiimoteState(address, entry["slot"]))
        state.error = None
        session = WiimoteSession(state, connection, self.publish, ir=self.config.ir, motionplus=self.config.motionplus)
        session.incoming = address in self.incoming
        self.incoming.discard(address)
        session.parser.gyro_bias = tuple(entry.get("gyro_bias", (0.0, 0.0, 0.0)))
        if entry.get("gyro_scale_frame") == GYRO_SCALE_FRAME:  # older factors used wrong axes
            session.parser.gyro_scale = tuple(entry["gyro_scale"])
            state.calibration["gyro_scale"] = list(session.parser.gyro_scale)
        self.sessions[address] = session
        session.apply_options(self.slot_options[entry["slot"]])
        session.on_bias_changed = lambda bias, a=address: self.save_entry(a, gyro_bias=list(bias))
        connection.on("disconnection", lambda reason: self.spawn(self.disconnected(address, session, reason)) if self.adapter_active else None)
        self.spawn(self.start_session(address, session, entry))

    async def start_session(self, address, session, entry):
        try:
            if getattr(session, "incoming", False):
                # The remote paged us (button press on a bonded Wiimote). Like the
                # Wii, let it open HID itself: requesting authentication here made
                # the clone drop the link with 0x13 (trace 2026-10-05). It may still
                # authenticate on its own; Bumble answers from the keystore.
                session.state.phase = "opening"
                self.publish(session.state)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.gather(
                        *(e.wait() for e in session.channel_events.values())), 5)
            else:
                session.state.phase = "authenticating"
                self.publish(session.state)
                await asyncio.wait_for(session.connection.authenticate(), 15)
            session.state.phase = "opening"
            for psm in (0x11, 0x13):
                if psm not in session.channels:
                    try:
                        channel = await asyncio.wait_for(session.connection.create_l2cap_channel(
                            l2cap.ClassicChannelSpec(psm=psm, mtu=185)), 8)
                        session.attach(channel)
                    except Exception:
                        if psm not in session.channels:
                            raise
                await asyncio.wait_for(session.channel_events[psm].wait(), 8)
            await session.initialize(entry.get("led_mask", 0x10 << entry["slot"]))
            self.failures.pop(address, None)
            self.auth_failures.discard(address)
        except Exception as exc:
            session.state.error = f"{type(exc).__name__}: {exc}"
            if session.state.phase == "authenticating":
                self.auth_failures.add(address)
                if getattr(exc, "error_code", None) in KEY_REJECTED and self.device:
                    # Observed with the clone: a bond interrupted before HID setup
                    # is dropped by the remote. Fall back to the binary PIN.
                    await self.delete_key(address)
                    log.warning("%s rejected the stored link key; next attempt pairs with PIN "
                                "(press SYNC if it does not connect)", address)
                # 0x17 Repeated Attempts: the remote throttles quick retries.
                self.schedule_retry(address, minimum=15)
            else:
                self.schedule_retry(address)
            log.warning("Session %s: %s", address, exc)
            await session.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(session.connection.disconnect(), 3)
            if self.sessions.get(address) is session:
                self.sessions.pop(address)

    def on_channel(self, channel):
        session = self.sessions.get(channel.connection.peer_address.to_string(False))
        if session:
            session.attach(channel)
        else:
            self.spawn(channel.disconnect())

    async def disconnected(self, address, session, reason):
        log.info("Disconnected %s: 0x%02x", address, reason)
        await session.close()
        if self.sessions.get(address) is session:
            self.sessions.pop(address)

    async def pair(self, seconds=20, mode="sync", address=None):
        if not self.ready.is_set():
            raise RuntimeError("Bluetooth adapter is not ready")
        if mode not in ("sync", "temporary") or not isinstance(seconds, (int, float)) or not 1 <= seconds <= 120:
            raise ValueError("Use mode sync/temporary and seconds 1..120")
        if self.pair_task and not self.pair_task.done():
            raise ValueError("Pairing window is already open")
        if address:
            address = normalize_address(address)
            entry = self.registry.add(address, pin_mode=mode)
            entry["pin_mode"] = mode
            self.registry.save()
            self.states.setdefault(address, WiimoteState(address, entry["slot"]))
            # Explicit synchronization means a new bond. Do not keep replaying a
            # key that the peer has discarded while waiting for a fresh PIN.
            await self.delete_key(address)
            self.auth_failures.discard(address)
            self.retry_after.pop(address, None)
            self.failures.pop(address, None)
        self.pair_mode = mode
        self.pair_until = time.monotonic() + seconds
        async def window():
            try:
                await self.device.set_discoverable(True)
                if address:
                    self.spawn(self.connect(address))
                else:
                    await self.start_discovery_when_idle()
                await asyncio.sleep(max(0.0, self.pair_until - time.monotonic()))
            finally:
                self.pair_until = 0
                if self.device:
                    with contextlib.suppress(Exception):
                        await self.device.stop_discovery()
                    with contextlib.suppress(Exception):
                        await self.device.set_discoverable(False)
        self.pair_task = self.spawn(window())

    async def start_discovery_when_idle(self):
        # A page started by the reconnect loop just before the window opened makes
        # the controller reject inquiry; retry until that page ends (<= ~5 s).
        while True:
            try:
                await self.device.start_discovery(auto_restart=True)
                return
            except hci.HCI_Error as exc:
                if exc.error_code != hci.HCI_COMMAND_DISALLOWED_ERROR or time.monotonic() >= self.pair_until:
                    raise
                await asyncio.sleep(0.5)
        return {"seconds": seconds, "mode": mode}

    def session_for(self, slot):
        if not isinstance(slot, int) or slot not in range(4):
            raise ValueError("slot must be 0..3")
        for session in self.sessions.values():
            if session.state.slot == slot and session.state.connected:
                return session
        raise ValueError("Slot is not connected")

    async def forget(self, slot):
        if not self.ready.is_set():
            raise RuntimeError("Adapter is not ready")
        if self.pair_until > time.monotonic() or self.connecting:
            raise ValueError("Wait for pairing/connection attempts to finish before forgetting")
        address = next((a for a, e in self.registry.devices.items() if e["slot"] == slot), None)
        if address is None:
            raise ValueError("Unknown slot")
        self.registry.forget(address)
        session = self.sessions.get(address)
        if session:
            await session.close()
            await session.connection.disconnect()
            self.sessions.pop(address, None)
        await self.delete_key(address)
        self.states[address].disconnect()
        self.publish(self.states[address])
        self.states.pop(address)
        return {"forgotten": address}

    async def calibrate(self, slot):
        session = self.session_for(slot)
        result = await session.calibrate()
        self.registry.devices[session.state.address]["gyro_bias"] = list(session.parser.gyro_bias)
        self.registry.save()
        return result

    def set_slot_options(self, slot, **changes):
        """Change a slot's quick/IR calibration options live (the GUI also saves them)."""
        if not isinstance(slot, int) or slot not in range(4):
            raise ValueError("slot must be 0..3")
        unknown = set(changes) - {"quick_calibration", "combo", "ir_calibration"}
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

    def save_entry(self, address, **values):
        if address in self.registry.devices:
            self.registry.devices[address].update(values)
            self.registry.save()

    async def calibrate_axis(self, slot, axis):
        session = self.session_for(slot)
        result = await session.calibrate_axis(axis)
        self.registry.devices[session.state.address].update(gyro_scale=list(session.parser.gyro_scale),
                                                            gyro_scale_frame=GYRO_SCALE_FRAME)
        self.registry.save()
        return result
