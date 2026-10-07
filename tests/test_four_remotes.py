"""Four remotes at once, end to end: every per-remote path keeps its slot's data and
nothing crosses between slots, through real UDP sockets for the three DSU servers."""
import asyncio
import socket
import struct
import time
import zlib

import pytest

from wiichinahook.app import Outputs
from wiichinahook.dsu import DsuServer, IrDsuServer, NunchukDsuServer
from wiichinahook.gamepad.xbox import GamepadHub
from wiichinahook.wiimote import WiimoteState

A, B, ONE, TWO, RIGHT = 0x0008, 0x0004, 0x0002, 0x0001, 0x0200
SLOT_BUTTONS = (A, B, ONE, TWO)                       # remote N holds a different button
XBOX_BUTTON = {A: "RB", B: None, ONE: "A", TWO: "B"}  # default game template (B = RT trigger)
DSU_FACE = {A: 0x20, B: 0x10, ONE: 0x80, TWO: 0x40}   # Circle, Triangle, Square, Cross


def remote(slot, buttons=None):
    s = WiimoteState(f"02:00:44:42:00:0{slot}", slot, True)
    s.phase = "ready"
    s.buttons = SLOT_BUTTONS[slot] if buttons is None else buttons
    s.capabilities = {"buttons": True, "accelerometer": True, "ir": True, "motionplus": True, "nunchuk": True}
    s.accel_g = (0.1 * slot, 0.0, 1.0)
    s.gyro_dps = (10.0 * slot, 0.0, 0.0)
    s.accel_timestamp_us = s.timestamp_us = 1_000_000 + slot
    s.nunchuk = {"stick": [0.0, 0.0], "c": False, "z": False, "accel_raw": [512 + 20 * slot, 512, 712]}
    x = 300 + 120 * slot                              # each remote points somewhere else
    s.ir = [{"x": x - 50, "y": 384, "size": 2}, {"x": x + 50, "y": 384, "size": 2}, None, None]
    return s


def request(kind, payload):
    body = struct.pack("<I", kind) + payload
    packet = bytearray(struct.pack("<4sHHII", b"DSUC", 1001, len(body), 0, 7) + body)
    struct.pack_into("<I", packet, 8, zlib.crc32(packet) & 0xFFFFFFFF)
    return bytes(packet)


class Client:
    """A DSU client (like Dolphin) subscribed to every slot of one server."""

    def __init__(self, server):
        self.server = server
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(1)
        self.address = server.sock.getsockname()

    def subscribe(self):
        self.sock.sendto(request(0x100002, bytes([0, 0]) + bytes(6)), self.address)   # all slots
        self.server.poll()

    def port_info(self):
        self.sock.sendto(request(0x100001, struct.pack("<i", 4) + bytes(range(4))), self.address)
        self.server.poll()
        return {r[20]: r[21] for r in (self.sock.recv(1024) for _ in range(4))}  # slot -> state

    def pads(self, count):
        """{slot: pad payload} of the next `count` pad-data packets."""
        out = {}
        for _ in range(count):
            packet = self.sock.recv(1024)
            assert zlib.crc32(packet[:8] + bytes(4) + packet[12:]) == struct.unpack_from("<I", packet, 8)[0]
            out[packet[20]] = packet[20:]
        return out

    def close(self):
        self.sock.close()


@pytest.fixture
def rig():
    servers = {"main": DsuServer("127.0.0.1", 0), "nunchuk": NunchukDsuServer("127.0.0.1", 0),
               "ir": IrDsuServer("127.0.0.1", 0)}
    clients = {name: Client(server) for name, server in servers.items()}
    yield servers, clients
    for client in clients.values():
        client.close()
    for server in servers.values():
        server.close()


class FakePad:
    def __init__(self, on_rumble=None):
        self.sent = []

    def send(self, state):
        self.sent.append(state)

    def close(self):
        pass


async def test_dsu_mode_sends_each_remote_on_its_own_slot_in_all_three_servers(rig):
    servers, clients = rig
    hub = GamepadHub(None, pad_factory=FakePad, loop=asyncio.get_running_loop())
    hub.set_mode(2)                                    # DSU
    outputs = Outputs(servers["main"], {"nunchuk": servers["nunchuk"], "ir": servers["ir"]}, hub=hub)
    for client in clients.values():
        client.subscribe()
    for slot in range(4):
        outputs.publish(remote(slot))
    pads = {name: client.pads(4) for name, client in clients.items()}
    macs = set()
    for slot in range(4):
        main, nunchuk, ir = pads["main"][slot], pads["nunchuk"][slot], pads["ir"][slot]
        for pad in (main, nunchuk, ir):
            assert pad[0] == slot and pad[11] == 1                         # its slot, connected
            macs.add(bytes(pad[4:10]))
        assert main[17] == DSU_FACE[SLOT_BUTTONS[slot]]                    # only its own button
        # Pad payload offsets: accelerometer at 56, gyro at 68, right stick X at 22.
        assert struct.unpack_from("<f", main, 56)[0] == pytest.approx(0.1 * slot)   # accel X
        assert struct.unpack_from("<fff", main, 68)[1] == pytest.approx(-10.0 * slot)  # yaw
        assert struct.unpack_from("<f", nunchuk, 56)[0] == pytest.approx(0.1 * slot)  # Nunchuk X
        assert nunchuk[16] == nunchuk[17] == 0                              # motion only
        expected_rx = round(128 + (511.5 - (300 + 120 * slot)) / (511.5 * 0.5) * 127)
        assert abs(ir[22] - min(255, max(0, expected_rx))) <= 1            # its own pointer
    assert len(macs) == 12                                                  # 4 remotes x 3 servers
    assert hub.pads == {}                                                   # no Xbox pads in DSU mode
    hub.close()


async def test_xbox_mode_gives_each_remote_its_own_pad_and_keeps_dsu_idle(rig):
    servers, clients = rig
    hub = GamepadHub(None, pad_factory=FakePad, loop=asyncio.get_running_loop())   # mode 1: Xbox
    outputs = Outputs(servers["main"], {"nunchuk": servers["nunchuk"], "ir": servers["ir"]}, hub=hub)
    clients["main"].subscribe()
    for slot in range(4):
        outputs.publish(remote(slot))
    assert sorted(hub.pads) == [0, 1, 2, 3]
    for slot, pad in hub.pads.items():                 # no crossed inputs
        out, button = pad.sent[-1], XBOX_BUTTON[SLOT_BUTTONS[slot]]
        assert out.buttons == ({button} if button else set())
        assert out.rt == (1.0 if SLOT_BUTTONS[slot] == B else 0.0)
    idle = clients["main"].pads(4)
    assert all(p[11] == 1 and p[17] == 0 for p in idle.values())           # listed, no input
    for state in clients.values():
        assert state.port_info() == {0: 2, 1: 2, 2: 2, 3: 2}                # 4 devices per server
    hub.close()


async def test_switching_off_one_extra_server_hides_only_its_four_devices(rig):
    servers, clients = rig
    hub = GamepadHub({"version": 3, "mode": 2, "modes": [None, {"type": "dsu", "ir_server": False}, None, None]},
                     pad_factory=FakePad, loop=asyncio.get_running_loop())
    outputs = Outputs(servers["main"], {"nunchuk": servers["nunchuk"], "ir": servers["ir"]}, hub=hub)
    for slot in range(4):
        outputs.publish(remote(slot))
    assert clients["ir"].port_info() == {0: 0, 1: 0, 2: 0, 3: 0}
    assert clients["nunchuk"].port_info() == {0: 2, 1: 2, 2: 2, 3: 2}
    assert clients["main"].port_info() == {0: 2, 1: 2, 2: 2, 3: 2}
    hub.close()


async def test_a_mode_switch_on_one_remote_announces_on_all_four():
    pulses, sounds = [], []

    async def rumble(slot, ms):
        pulses.append(slot)

    hub = GamepadHub(None, rumble=rumble, pad_factory=FakePad, loop=asyncio.get_running_loop(),
                     sound=lambda slot, mode: sounds.append((slot, mode)))
    for slot in range(4):
        hub.update(remote(slot, buttons=0))
    hub.update(remote(3, buttons=B))
    hub.update(remote(3, buttons=B | RIGHT))           # remote 4: B + right = mode 2
    await asyncio.sleep(1.0)
    assert hub.mode == 2 and sorted(sounds) == [(0, 2), (1, 2), (2, 2), (3, 2)]
    assert all(pulses.count(slot) == 2 for slot in range(4))               # two pulses each
    hub.close()


async def test_four_speakers_stream_in_parallel_at_full_rate():
    from tests.test_speaker import make_session
    from wiichinahook import speaker
    pairs = [make_session() for _ in range(4)]
    for _, channel in pairs:
        channel.thread_safe_write = True                  # like the DolphinBar link: no loop hop
    sound = bytes(range(200))                            # 10 reports, ~133 ms each remote
    start = time.perf_counter()
    await asyncio.gather(*(speaker.play(session, sound, 0.5) for session, _ in pairs))
    elapsed = time.perf_counter() - start
    assert elapsed < 0.45                                 # parallel (in a row would be > 0.53 s)
    for _, channel in pairs:
        audio = [t for t, data in channel.sent if data[1] == 0x18]
        assert len(audio) == 10
        gaps = [b - a for a, b in zip(audio, audio[1:])]
        # Steady pace with four streams at once: exact on average, no long stall.
        assert 0.010 < sum(gaps) / len(gaps) < 0.017 and max(gaps) < 0.05
