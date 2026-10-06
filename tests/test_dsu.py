import socket
import struct
import time
import zlib

import pytest
from wiichinahook.dsu import DsuServer, DsuPacketBuilder, parse_client_packet, parse_mac
from wiichinahook.wiimote import WiimoteState


def request(kind, payload):
    packet = bytearray(DsuPacketBuilder(1).build(kind, payload))
    packet[:4] = b"DSUC"
    packet[8:12] = bytes(4)
    struct.pack_into("<I", packet, 8, zlib.crc32(packet))
    return bytes(packet)


@pytest.fixture
def server():
    s = DsuServer(bind_port=0)
    yield s
    s.close()


def test_protocol_crc_and_malformed_packet(server):
    packet = request(0x100000, b"")
    assert parse_client_packet(packet) == (0x100000, b"")
    assert parse_client_packet(packet[:-1]) is None
    assert parse_client_packet(packet[:12]+b"xxxx"+packet[16:]) is None
    for count in (-1,5,0x7fffffff):
        server._handle_packet(request(0x100001, struct.pack("<i",count)), ("127.0.0.1",1))


def test_four_slot_subscriptions_and_disconnect(server):
    received=[]
    server._send=lambda packet,endpoint: received.append((packet,endpoint))
    a,b,c = [("127.0.0.1",port) for port in (101,102,103)]
    server._handle_packet(request(0x100002, bytes([1,1])+bytes(6)), a)
    server._handle_packet(request(0x100002, bytes([0,0])+bytes(6)), b)
    server._handle_packet(request(0x100002, bytes([2,0])+parse_mac("00:11:22:33:44:03")), c)
    states = [WiimoteState(f"00:11:22:33:44:0{i}",i,True) for i in range(4)]
    for state in states:
        server.send_state(state)
    assert [packet[20] for packet,endpoint in received if endpoint==a] == [1]
    assert [packet[20] for packet,endpoint in received if endpoint==b] == [0,1,2,3]
    assert [packet[20] for packet,endpoint in received if endpoint==c] == [3]
    received.clear()
    states[1].disconnect()
    server.send_state(states[1])
    assert all(packet[21] == 0 and packet[31] == 0 for packet,_ in received)
    for key in server.clients:
        server.clients[key] = time.monotonic()-6
    received.clear()
    server.send_state(states[0])
    assert received == []


def test_udp_port_query_and_sensor_mapping(server):
    s = WiimoteState("00:11:22:33:44:55",0,True)
    s.accel_g = (1.,2.,3.)
    s.gyro_dps = (10.,20.,30.)
    s.accel_timestamp_us = 12345
    s.capabilities["motionplus"] = True
    s.nunchuk = {"stick":[-1,1],"c":True,"z":True}
    server.send_state(s)
    packet = server._pad_data_payload(s)
    assert packet[20:22] == bytes([0,255])
    assert packet[17] & 5 == 5
    assert packet[33] == 255 and packet[35] == 255
    # Dolphin reads DSU x as left, -y as up, z as forward, and pitch/yaw/roll as
    # up/right/right; the Wii frame is X left, Y back, Z up (MotionPlus right-handed).
    assert struct.unpack_from("<fff",packet,56) == (1.,-3.,-2.)
    assert struct.unpack_from("<fff",packet,68) == (-30.,-10.,-20.)
    assert struct.unpack_from("<Q",packet,48)[0] == 12345
    client=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    client.settimeout(1)
    try:
        client.sendto(request(0x100001, struct.pack("<i",4)+bytes(range(4))), server.sock.getsockname())
        server.poll()
        replies=[client.recv(1024) for _ in range(4)]
        assert [r[20] for r in replies] == [0,1,2,3]
        assert [r[21] for r in replies] == [2,0,0,0]
        for r in replies:
            expected=struct.unpack_from("<I",r,8)[0]
            assert zlib.crc32(r[:8]+bytes(4)+r[12:]) == expected
    finally:
        client.close()


def test_port_info_keeps_answering_after_a_client_closes_its_socket():
    # Dolphin drops a DSU server's devices when port info goes unanswered for 1 s.
    # A client that closed its socket used to flood recvfrom with WSAECONNRESET
    # (ICMP port unreachable) and starve the real requests.
    import socket as socket_module
    import time
    import zlib

    def client_packet(kind, payload):
        body = struct.pack("<I", kind) + payload
        raw = bytearray(b"DSUC" + struct.pack("<HHII", 1001, len(body), 0, 0xC0FFEE) + body)
        struct.pack_into("<I", raw, 8, zlib.crc32(raw) & 0xFFFFFFFF)
        return bytes(raw)

    server = DsuServer("127.0.0.1", 0)
    port = server.sock.getsockname()[1]
    state = WiimoteState("02:00:44:42:00:00", 0)
    state.connected = True
    stale = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_DGRAM)
    stale.sendto(client_packet(0x100002, bytes([1, 0]) + bytes(6)), ("127.0.0.1", port))
    time.sleep(0.05)
    server.poll()
    stale.close()
    client = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_DGRAM)
    client.setblocking(False)
    answered = 0
    try:
        for request in range(10):
            for _ in range(5):
                server.send_state(state)         # remote reports keep flowing to the stale client
            client.sendto(client_packet(0x100001, struct.pack("<i", 1) + bytes([0])), ("127.0.0.1", port))
            time.sleep(0.01)
            server.poll()
            time.sleep(0.01)
            try:
                while True:
                    data, _ = client.recvfrom(200)
                    answered += struct.unpack_from("<I", data, 16)[0] == 0x100001
            except (BlockingIOError, ConnectionResetError):
                pass
    finally:
        server.close()
        client.close()
    assert answered == 10


def test_inactive_slots_stay_connected_without_input(server):
    s = WiimoteState("00:11:22:33:44:55", 0, True)
    s.buttons, s.accel_g, s.gyro_dps = 0x0008, (1., 2., 3.), (10., 20., 30.)
    s.nunchuk = {"stick": [1, 1], "c": True, "z": True}
    idle = server._pad_data_payload(s, active=False)
    assert idle[11] == 1 and idle[1] == 2               # connected, still announced
    assert idle[16:20] == bytes(4) and idle[20:24] == bytes([0x80]) * 4
    assert idle[56:80] == bytes(24)
    assert server._pad_data_payload(s)[56:80] != bytes(24)


def test_idle_slots_are_sent_at_a_low_rate(server, monkeypatch):
    sent = []
    monkeypatch.setattr(server, "_send", lambda packet, endpoint: sent.append(packet))
    server.clients[(("127.0.0.1", 9), 0, 0, bytes(6))] = time.monotonic()
    s = WiimoteState("00:11:22:33:44:55", 0, True)
    for _ in range(50):                      # a burst of reports within a few ms
        server.send_state(s, active=False)
    assert len(sent) == 1
    for _ in range(50):
        server.send_state(s)                 # DSU mode: every report goes out
    assert len(sent) == 51
