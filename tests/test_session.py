import asyncio
from unittest.mock import AsyncMock

import pytest
from wiichinahook.session import WiimoteSession, ReportError
from wiichinahook.wiimote import WiimoteState


class Channel:
    psm = 0x13
    def __init__(self):
        self.sent = []
        self.sink = None
    def on(self, *args):
        pass
    def write(self, data):
        self.sent.append(data)


def session():
    s = WiimoteSession(WiimoteState(), AsyncMock(), lambda state: None)
    channel = Channel()
    s.attach(channel)
    return s, channel


def memory_reply(address, data, error=0):
    return b"\xa1\x21\0\0" + bytes([((len(data)-1) << 4) | error]) + address.to_bytes(2,"big") + data.ljust(16,b"\0")


async def test_memory_reassembly_out_of_order_and_unrelated_packets():
    s, channel = session()
    task = asyncio.create_task(s.read(0x04A60020, 32))
    await asyncio.sleep(0)
    assert channel.sent[-1] == bytes.fromhex("a2 17 04 a6 00 20 00 20")
    s.receive(memory_reply(0x70, b"x"*16))
    s.receive(memory_reply(0x30, b"b"*16))
    assert not task.done()
    s.receive(memory_reply(0x20, b"a"*16))
    assert await task == b"a"*16 + b"b"*16
    await s.close()


async def test_commands_request_ack_and_preserve_rumble():
    s, channel = session()
    s.rumbling = True
    task = asyncio.create_task(s.set_led(0x20))
    await asyncio.sleep(0)
    assert channel.sent[-1] == bytes.fromhex("a2 11 23")
    s.receive(bytes.fromhex("a1 22 00 00 12 00"))
    assert not task.done()
    s.receive(bytes.fromhex("a1 22 00 00 11 00"))
    await task
    await s.close()
    assert channel.sent[-1] == bytes.fromhex("a2 10 00")


async def test_peripheral_writes_never_write_eeprom():
    s, channel = session()
    with pytest.raises(ValueError):
        await s.write(0x16, b"\0")
    task = asyncio.create_task(s.write(0x04A400F0, b"\x55"))
    await asyncio.sleep(0)
    assert channel.sent[-1][:8] == bytes.fromhex("a2 16 06 a4 00 f0 01 55")
    assert len(channel.sent[-1]) == 23
    s.receive(bytes.fromhex("a1 22 00 00 16 07"))
    with pytest.raises(ReportError, match="error"):
        await task
    await s.close()


async def test_disconnect_fails_pending_read_and_clears_data():
    s, _ = session()
    task = asyncio.create_task(s.read(0x16, 10))
    await asyncio.sleep(0)
    await s.close()
    with pytest.raises(ReportError, match="Disconnected"):
        await task
    s.receive(bytes.fromhex("a1 31 00 00 80 80 c0"))
    assert s.state.accel_g is None


async def test_rumble_expires_and_is_stopped_on_close():
    s, channel = session()
    await s.rumble(10)
    assert channel.sent[-1] == bytes.fromhex("a2 10 01")
    await asyncio.sleep(.04)
    assert channel.sent[-1] == bytes.fromhex("a2 10 00")
    await s.rumble(5000)
    await s.close()
    assert channel.sent[-1] == bytes.fromhex("a2 10 00")


async def test_initialization_basic_device_and_fallback_calibration():
    s, channel = session()
    s.want_ir = s.want_motionplus = False
    old_write = channel.write
    def respond(data):
        old_write(data)
        report = data[1]
        if report == 0x17:
            addr = int.from_bytes(data[4:6], "big")
            reply = memory_reply(addr, b"\0", 7)
        elif report == 0x15:
            reply = bytes.fromhex("a1 20 00 00 10 00 00 c0")
        else:
            reply = bytes([0xA1,0x22,0,0,report,7 if report == 0x16 else 0])
        asyncio.get_running_loop().call_soon(s.receive, reply)
    channel.write = respond
    await s.initialize(0x10)
    assert s.state.connected
    assert s.state.calibration["accelerometer"] == "nominal"
    assert bytes.fromhex("a2 12 06 31") in channel.sent
    await s.close()


async def test_full_initialization_motionplus_nunchuk_and_ir():
    s, channel = session()
    old_write = channel.write
    accel = bytes.fromhex("80 80 80 00 c0 c0 c0 00 40")
    accel += bytes([(sum(accel)+0x55)&255])
    nunchuk_cal = bytes.fromhex("80 80 80 00 c0 c0 c0 00 ff 00 80 ff 00 80 00 00")
    memories = {0x16: accel, 0x04A400FA: bytes.fromhex("00 00 a4 20 00 00"),
                0x04A40020: nunchuk_cal, 0x04A600FA: bytes.fromhex("00 00 a6 20 00 05"),
                0x04A60020: bytes(32)}
    def respond(data):
        old_write(data)
        loop = asyncio.get_running_loop()
        report = data[1]
        if report == 0x17:
            address = int.from_bytes(data[2:6], "big") & ~0x01000000
            content = memories[address]
            for offset in range(0,len(content),16):
                loop.call_soon(s.receive,memory_reply((address+offset)&65535,content[offset:offset+16]))
        elif report == 0x15:
            loop.call_soon(s.receive,bytes.fromhex("a1 20 00 00 12 00 00 c0"))
        elif report != 0x10:
            loop.call_soon(s.receive,bytes([0xA1,0x22,0,0,report,0]))
    channel.write = respond
    await s.initialize(0x10)
    assert s.state.phase == "ready"
    assert s.state.extension == 'motionplus+nunchuk'
    assert all(s.state.capabilities.values())
    assert s.state.calibration['accelerometer'] == 'factory'
    assert s.state.calibration['nunchuk'] == 'factory'
    assert s.state.calibration['motionplus'] == 'nominal'
    assert bytes.fromhex('a2 12 06 37') in channel.sent
    assert any(d[:8] == bytes.fromhex('a2 16 06 a6 00 fe 01 05') for d in channel.sent)
    s.receive(bytes.fromhex('a1 37 00 08 80 80 c0') + b'\xff'*10 + bytes.fromhex('7f 7f 7f 7f 7f 7e'))
    assert s.state.buttons == 8
    assert s.state.gyro_dps == (0.,)*3
    assert s.state.ir == [None]*4
    await s.close()


async def test_incoming_channel_waits_for_open_event():
    from enum import Enum
    s,_=session()
    class Incoming:
        class State(Enum):
            CLOSED=0
            OPEN=1
        psm=0x11
        state=State.CLOSED
        def __init__(self):
            self.callbacks={}
        def on(self,event,callback):
            self.callbacks[event]=callback
    incoming=Incoming()
    s.attach(incoming)
    assert not s.channel_events[0x11].is_set()
    incoming.callbacks['open']()
    assert s.channel_events[0x11].is_set()
    await s.close()


async def test_clone_unpadded_memory_replies_from_capture():
    # Captured from the 00:17:AB:AE:1A:6D clone: replies omit the 16-byte padding.
    s, channel = session()
    task = asyncio.create_task(s.read(0x0016, 10))
    await asyncio.sleep(0)
    s.receive(bytes.fromhex("a1 21 00 03 90 00 16 80 80 80 00 9a 9a 9a 00 40 e3"))
    assert await task == bytes.fromhex("80 80 80 00 9a 9a 9a 00 40 e3")
    task = asyncio.create_task(s.read(0x04A400FA, 6))
    await asyncio.sleep(0)
    s.receive(bytes.fromhex("a1 21 00 00 50 00 fa 00 00 a4 20"))  # missing bytes: ignored
    assert not task.done()
    s.receive(bytes.fromhex("a1 21 00 00 50 00 fa 00 00 a4 20 00 00"))
    assert await task == bytes.fromhex("00 00 a4 20 00 00")
    await s.close()


async def test_clone_oversized_32_byte_reply_from_capture():
    s, channel = session()
    task = asyncio.create_task(s.read(0x04A60020, 32))
    await asyncio.sleep(0)
    s.receive(bytes.fromhex("a1 21 00 00 f0 00 20 55 ff ff ff ff ff 00 08 00 00 00 00 a4 20 05 05"
                            + " 00" * 16))
    assert await task == bytes.fromhex("55 ff ff ff ff ff 00 08 00 00 00 00 a4 20 05 05") + bytes(16)
    await s.close()


async def test_transient_status_after_motionplus_activation_only_restores_mode():
    s, channel = session()
    s.parser.extension = "motionplus+nunchuk"
    s.parser.extension_connected = True
    s.initialized, s.mode = True, 0x37
    s.schedule_reconfigure = lambda: pytest.fail("transient status must not reconfigure")
    async def ack():
        while not channel.sent or channel.sent[-1][1] != 0x12:
            await asyncio.sleep(0.01)
        s.receive(bytes.fromhex("a1 22 00 00 12 00"))
    s.receive(bytes.fromhex("a1 20 00 00 28 00 00 40"))  # extension flag drops...
    s.receive(bytes.fromhex("a1 20 00 00 2a 00 00 40"))  # ...and returns
    await asyncio.gather(ack(), s.status_task)
    assert channel.sent[-1] == bytes.fromhex("a2 12 06 37")
    await s.close()
