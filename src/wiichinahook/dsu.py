"""DSU v1001: one socket, independent subscriptions and four real slot states."""
from __future__ import annotations

import random
import socket
import struct
import time
import zlib

from .dsu_mapping import dsu_buttons_from_wiimote
from .wiimote import WiimoteState

PROTOCOL_VERSION = 1001
EVENT_PROTOCOL_VERSION = 0x100000
EVENT_PORT_INFO = 0x100001
EVENT_PAD_DATA = 0x100002


class DsuPacketBuilder:
    def __init__(self, server_id=None):
        self.server_id = server_id if server_id is not None else random.getrandbits(32)

    def build(self, event_type, payload):
        body = struct.pack("<I", event_type) + payload
        packet = bytearray(struct.pack("<4sHHII", b"DSUS", PROTOCOL_VERSION, len(body), 0, self.server_id) + body)
        struct.pack_into("<I", packet, 8, zlib.crc32(packet) & 0xFFFFFFFF)
        return bytes(packet)


def parse_client_packet(data):
    if len(data) < 20 or data[:4] != b"DSUC":
        return None
    version, length, crc = struct.unpack_from("<HHI", data, 4)
    if version != PROTOCOL_VERSION or length < 4 or len(data) < 16 + length:
        return None
    packet = bytearray(data[:16 + length])
    struct.pack_into("<I", packet, 8, 0)
    if zlib.crc32(packet) & 0xFFFFFFFF != crc:
        return None
    return struct.unpack_from("<I", packet, 16)[0], bytes(packet[20:])


def parse_mac(mac):
    raw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(raw) != 6:
        raise ValueError("Invalid MAC")
    return raw


class DsuServer:
    def __init__(self, bind_host="127.0.0.1", bind_port=26760):
        self.builder = DsuPacketBuilder()
        self.states = {}
        self.clients = {}  # (endpoint, flags, slot, MAC) -> last subscription
        self.counters = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        try:
            self.sock.bind((bind_host, bind_port))
        except BaseException:
            self.sock.close()
            raise

    def close(self):
        self.sock.close()

    def poll(self):
        now = time.monotonic()
        self.clients = {k: t for k, t in self.clients.items() if now - t < 5}
        active = {k[0] for k in self.clients}
        self.counters = {k: v for k, v in self.counters.items() if k[0] in active}
        # Bound work per tick so UDP traffic cannot starve Bluetooth.
        for _ in range(64):
            try:
                data, endpoint = self.sock.recvfrom(2048)
            except (BlockingIOError, ConnectionResetError):
                return
            self._handle_packet(data, endpoint)

    def _send(self, packet, endpoint):
        try:
            self.sock.sendto(packet, endpoint)
        except (BlockingIOError, ConnectionResetError, OSError):
            pass

    def _handle_packet(self, data, endpoint):
        parsed = parse_client_packet(data)
        if parsed is None:
            return
        kind, payload = parsed
        if kind == EVENT_PROTOCOL_VERSION:
            self._send(self.builder.build(kind, struct.pack("<H", PROTOCOL_VERSION)), endpoint)
        elif kind == EVENT_PORT_INFO and len(payload) >= 4:
            count = struct.unpack_from("<i", payload)[0]
            if not 0 <= count <= 4 or len(payload) < 4 + count:
                return
            for slot in payload[4:4 + count]:
                if slot < 4:
                    state = self.states.get(slot)
                    self._send(self.builder.build(kind, self._shared_payload(slot, state) + b"\0"), endpoint)
        elif kind == EVENT_PAD_DATA and len(payload) == 8:
            flags, slot, mac = payload[0], payload[1], payload[2:8]
            if flags & ~3 or (flags & 1 and slot > 3):
                return
            key = (endpoint, flags, slot if flags & 1 else 0, mac if flags & 2 else bytes(6))
            if len(self.clients) < 256 or key in self.clients:
                self.clients[key] = time.monotonic()

    def _shared_payload(self, slot, state):
        connected = state is not None and state.connected
        battery = 0 if not connected or state.battery is None else (1 if state.battery < .1 else
                  2 if state.battery < .25 else 3 if state.battery < .5 else 4 if state.battery < .9 else 5)
        return struct.pack("<BBBB6sB", slot, 2 if connected else 0,
                           (2 if state.capabilities.get("motionplus") else 1) if connected else 0,
                           2 if connected else 0, parse_mac(state.address) if state else bytes(6), battery)

    def send_state(self, state):
        self.states[state.slot] = state
        now = time.monotonic()
        endpoints = set()
        for (endpoint, flags, slot, mac), seen in self.clients.items():
            if now - seen < 5 and (flags == 0 or flags & 1 and slot == state.slot or
                                   flags & 2 and mac == parse_mac(state.address)):
                endpoints.add(endpoint)
        for endpoint in endpoints:
            key = (endpoint, state.slot)
            counter = self.counters.get(key, 0)
            self._send(self.builder.build(EVENT_PAD_DATA, self._pad_data_payload(state, counter)), endpoint)
            self.counters[key] = (counter + 1) & 0xFFFFFFFF

    def _pad_data_payload(self, state, counter=0):
        payload = bytearray(80)
        payload[:11] = self._shared_payload(state.slot, state)
        payload[11] = int(state.connected)
        struct.pack_into("<I", payload, 12, counter)
        payload[20:24] = b"\x80" * 4
        if not state.connected:
            return bytes(payload)
        dpad, face, home, analogs = dsu_buttons_from_wiimote(state.buttons)
        analogs = bytearray(analogs)
        if state.nunchuk:
            x, y = state.nunchuk["stick"]
            payload[20:22] = bytes(max(0, min(255, round(128 + v * (127 if v >= 0 else 128)))) for v in (x, y))
            if state.nunchuk["c"]:
                face |= 0x04
                analogs[9] = 255
            if state.nunchuk["z"]:
                face |= 0x01
                analogs[11] = 255
        payload[16:19] = bytes([dpad, face, home])
        payload[24:36] = analogs
        struct.pack_into("<Q", payload, 48, state.accel_timestamp_us)
        # Axes as Dolphin's DSU client reads them (DualShockUDPClient.cpp: "Accel Up"
        # = -y, "Accel Left" = +x, "Accel Forward" = +z; "Gyro Pitch Up" = +pitch,
        # "Roll Right" = +roll, "Yaw Right" = +yaw), i.e. DSU x left, y down, z forward.
        # Dolphin's IMU frame equals the Wii's (X left, Y back, Z up; IMUAccelerometer:
        # x = Left - Right, y = Backward - Forward, z = Up - Down; IMUGyroscope:
        # x = PitchDown - PitchUp, y = RollLeft - RollRight, z = YawLeft - YawRight),
        # and MotionPlus pitch/roll/yaw are right-handed about those axes.
        x, y, z = state.accel_g or (0., 0., 0.)
        struct.pack_into("<fff", payload, 56, x, -z, -y)
        yaw, roll, pitch = state.gyro_dps or (0., 0., 0.)
        struct.pack_into("<fff", payload, 68, -pitch, -yaw, -roll)
        return bytes(payload)
