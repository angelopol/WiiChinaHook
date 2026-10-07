import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from bumble import hci
from bumble.device import DeviceConfiguration
from bumble.host import Host
from websockets.asyncio.client import connect

from wiichinahook.api import ApiServer
from wiichinahook.bt import legacy_pin, retry_delay, WiiDevice, WiimoteManager
from wiichinahook.config import load_config, AppConfig
from wiichinahook.storage import Registry
from wiichinahook.wiimote import WiimoteState


def test_old_config_and_specific_adapter(tmp_path):
    path=tmp_path/'config.json'
    path.write_text(json.dumps({"dongle":{"vid":"0x8087","pid":"0x0a2a","transport":"usb:0"},
                               "wiimote":{"address":"00:11:22:33:44:55"},"dsu":{"slot":2}}))
    config=load_config(path)
    assert config.dongle.selector == "usb:8087:0a2a"
    assert config.wiimotes[0].slot == 2
    path.write_text(json.dumps({"wiimotes":[{"address":"00:11:22:33:44:55","slot":0}]*2}))
    with pytest.raises(ValueError):
        load_config(path)


def test_registry_slots_persist_per_adapter(tmp_path):
    store=Registry(tmp_path,"11:22:33:44:55:66")
    for i in range(4):
        assert store.add(f"00:11:22:33:44:0{i}")["slot"] == i
    with pytest.raises(ValueError):
        store.add("00:11:22:33:44:05")
    assert Registry(tmp_path,"11:22:33:44:55:66").devices == store.devices
    assert not Registry(tmp_path,"11:22:33:44:55:77").devices
    store.forget("00:11:22:33:44:01")
    assert store.add("00:11:22:33:44:05")["slot"] == 1


async def test_binary_pin_in_actual_bumble_host_callback(tmp_path):
    manager=WiimoteManager(AppConfig(),lambda s:None)
    manager.registry=Registry(tmp_path,"11:22:33:44:55:66")
    host=Host()
    host.send_sync_command=AsyncMock()
    device=WiiDevice(config=DeviceConfiguration(),host=host)
    device.manager=manager
    device.public_address=hci.Address("FF:80:00:44:55:66",hci.Address.PUBLIC_DEVICE_ADDRESS)
    peer=hci.Address("00:11:22:33:44:55",hci.Address.PUBLIC_DEVICE_ADDRESS)
    host.emit('pin_code_request',peer)
    await asyncio.gather(*manager.tasks)
    command=host.send_sync_command.call_args.args[0]
    assert command.pin_code[:6] == bytes.fromhex("66 55 44 00 80 ff")
    assert command.pin_code_length == 6
    assert legacy_pin(device.public_address,peer,'temporary') == bytes.fromhex("55 44 33 22 11 00")


async def test_api_commands_errors_and_subscriptions():
    manager=WiimoteManager(AppConfig(),lambda s:None)
    manager.pair=AsyncMock(return_value={"seconds":20,"mode":"sync"})
    api=await ApiServer(manager,port=0).start()
    port=api.server.sockets[0].getsockname()[1]
    try:
        async with connect(f'ws://127.0.0.1:{port}') as ws:
            await ws.send(json.dumps({"v":2,"id":1,"command":"devices"}))
            assert not json.loads(await ws.recv())["ok"]
            await ws.send(json.dumps({"v":1,"id":2,"command":"pair"}))
            assert json.loads(await ws.recv())["ok"]
            manager.pair.assert_awaited_once_with(20,"sync",None)
            await ws.send(json.dumps({"v":1,"id":3,"command":"subscribe"}))
            assert json.loads(await ws.recv())["result"]["ready"] is False
            state=WiimoteState("00:11:22:33:44:55",2,True)
            api.publish(state)
            reply=json.loads(await asyncio.wait_for(ws.recv(),1))
            assert reply["event"] == 'state' and reply["data"]["slot"] == 2
            assert reply["data"]["gyro_dps"] is None
            await ws.send(json.dumps({"v":1,"id":4,"command":"rumble","args":{"slot":9}}))
            assert not json.loads(await ws.recv())["ok"]
    finally:
        await api.close()


async def test_failed_authentication_does_not_leave_connected_session(tmp_path):
    manager=WiimoteManager(AppConfig(),lambda s:None)
    manager.registry=Registry(tmp_path,"11:22:33:44:55:66")
    address="00:11:22:33:44:55"
    manager.registry.add(address)
    manager.adapter_active=True
    connection=SimpleNamespace(peer_address=hci.Address(address),
                               authenticate=AsyncMock(side_effect=RuntimeError('auth failed')),
                               disconnect=AsyncMock(),on=lambda *a:None)
    manager.on_connection(connection)
    await asyncio.gather(*manager.tasks)
    assert address not in manager.sessions
    assert not manager.states[address].connected
    assert 'auth failed' in manager.states[address].error
    connection.disconnect.assert_awaited_once()


def test_retry_delay_backs_off_and_caps():
    assert [retry_delay(n) for n in (1, 2, 3, 4, 5, 9)] == [5, 10, 20, 40, 60, 60]


async def test_rejected_link_key_is_deleted_for_pin_fallback(tmp_path):
    manager=WiimoteManager(AppConfig(),lambda s:None)
    manager.registry=Registry(tmp_path,"11:22:33:44:55:66")
    address="00:11:22:33:44:55"
    manager.registry.add(address)
    manager.adapter_active=True
    manager.device=SimpleNamespace(keystore=SimpleNamespace(delete=AsyncMock()))
    connection=SimpleNamespace(peer_address=hci.Address(address),
                               authenticate=AsyncMock(side_effect=hci.HCI_Error(0x05)),
                               disconnect=AsyncMock(),on=lambda *a:None)
    manager.on_connection(connection)
    await asyncio.gather(*manager.tasks)
    manager.device.keystore.delete.assert_awaited_once_with(address + "/P")
    assert manager.retry_after[address] - time.monotonic() > 14


async def test_incoming_reconnect_waits_for_remote_hid_without_authenticating(tmp_path):
    manager=WiimoteManager(AppConfig(),lambda s:None)
    manager.registry=Registry(tmp_path,"11:22:33:44:55:66")
    address="00:11:22:33:44:55"
    manager.registry.add(address)
    manager.adapter_active=True
    manager.incoming.add(address)
    connection=SimpleNamespace(peer_address=hci.Address(address),
                               authenticate=AsyncMock(), create_l2cap_channel=AsyncMock(),
                               disconnect=AsyncMock(),on=lambda *a:None)
    manager.on_connection(connection)
    session=manager.sessions[address]
    session.initialize=AsyncMock()
    await asyncio.sleep(0)
    for psm in (0x11, 0x13):  # the Wiimote opens both HID channels itself
        manager.on_channel(SimpleNamespace(psm=psm, connection=connection, on=lambda *a:None, sink=None))
    await asyncio.gather(*manager.tasks)
    connection.authenticate.assert_not_awaited()
    connection.create_l2cap_channel.assert_not_awaited()
    session.initialize.assert_awaited_once()
    await session.close()


async def test_incoming_acl_is_accepted_as_central(tmp_path):
    sent=[]
    device=WiiDevice(config=DeviceConfiguration(), host=Host(None, None))
    device.host.send_command_sync=sent.append
    manager=WiimoteManager(AppConfig(),lambda s:None)
    manager.registry=Registry(tmp_path,"11:22:33:44:55:66")
    manager.registry.add("00:11:22:33:44:55")
    device.manager=manager
    address=hci.Address("00:11:22:33:44:55", hci.Address.PUBLIC_DEVICE_ADDRESS)
    device.on_connection_request(address, 0x002504, hci.HCI_Connection_Complete_Event.LinkType.ACL)
    assert sent[0].role == 0x00 and address in device.pending_connections
    assert "00:11:22:33:44:55" in manager.incoming


def test_save_config_round_trips_and_keeps_unknown_keys(tmp_path):
    from dataclasses import replace
    from wiichinahook.config import DongleConfig, DsuConfig, WiimoteConfig, save_config
    path = tmp_path / "config.local.json"
    path.write_text('{"custom": 1, "wiimote": {"address": "00:11:22:33:44:55"}}')
    config = replace(load_config(path), mode="bluetooth",
                     dongle=DongleConfig(0x0A12, 0x0001, "usb:0a12:0001"),
                     wiimotes=(WiimoteConfig("00:17:AB:AE:1A:6D", 1, "sync", 0x20),),
                     dsu=DsuConfig("127.0.0.1", 26770), ir=False)
    save_config(config, path)
    assert load_config(path) == config
    assert json.loads(path.read_text())["custom"] == 1


def test_save_config_refuses_invalid_values(tmp_path):
    from dataclasses import replace
    from wiichinahook.config import save_config
    path = tmp_path / "config.local.json"
    save_config(AppConfig(), path)
    good = path.read_text()
    with pytest.raises(ValueError):
        save_config(replace(AppConfig(), mode="usb"), path)
    assert path.read_text() == good


async def test_pairing_retries_inquiry_while_a_page_is_in_progress(tmp_path):
    manager = WiimoteManager(AppConfig(), lambda s: None)
    manager.registry = Registry(tmp_path, "11:22:33:44:55:66")
    manager.ready.set()
    attempts = []
    async def start_discovery(auto_restart):
        attempts.append(time.monotonic())
        if len(attempts) < 3:
            raise hci.HCI_Error(hci.HCI_COMMAND_DISALLOWED_ERROR)
    manager.device = SimpleNamespace(set_discoverable=AsyncMock(), start_discovery=start_discovery,
                                     stop_discovery=AsyncMock())
    await manager.pair(seconds=3)
    await asyncio.sleep(1.4)
    assert len(attempts) == 3 and time.monotonic() < manager.pair_until
    manager.pair_task.cancel()
    await asyncio.gather(manager.pair_task, return_exceptions=True)


async def test_stream_rate_pauses_live_state_but_not_mode_changes():
    manager=WiimoteManager(AppConfig(),lambda s:None)
    api=await ApiServer(manager,port=0).start()
    port=api.server.sockets[0].getsockname()[1]
    try:
        async with connect(f'ws://127.0.0.1:{port}') as ws:
            await ws.send(json.dumps({"v":1,"id":1,"command":"subscribe","args":{"hz":0}}))
            assert json.loads(await ws.recv())["ok"]
            state=WiimoteState("00:11:22:33:44:55",1,True)
            api.publish(state)
            api.publish_gamepad({"mode":2})
            reply=json.loads(await asyncio.wait_for(ws.recv(),1))
            assert reply["event"] == "gamepad"                     # the state stays queued
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(ws.recv(),0.2)
            state.buttons=8                                        # latest state wins on resume
            await ws.send(json.dumps({"v":1,"id":2,"command":"stream_rate","args":{"hz":30}}))
            replies=[json.loads(await asyncio.wait_for(ws.recv(),1)) for _ in range(2)]
            assert replies[0]["result"] == {"hz":30}
            assert replies[1]["event"] == "state" and replies[1]["data"]["buttons"] == 8
            await ws.send(json.dumps({"v":1,"id":3,"command":"stream_rate","args":{"hz":500}}))
            assert not json.loads(await ws.recv())["ok"]
    finally:
        await api.close()


def test_state_snapshot_is_independent_of_later_updates():
    state=WiimoteState("00:11:22:33:44:55",0,True)
    snap=state.to_dict()
    state.capabilities["nunchuk"]=True
    state.calibration["heading"]="ir"
    assert snap["capabilities"]["nunchuk"] is False and "heading" not in snap["calibration"]
    assert json.loads(json.dumps(snap))["address"] == "00:11:22:33:44:55"


def test_extra_dsu_ports_round_trip_and_must_differ(tmp_path):
    from wiichinahook.config import save_config, DsuConfig
    path = tmp_path / "config.json"
    save_config(AppConfig(dsu=DsuConfig("127.0.0.1", 26760, 26770, 0)), path)
    assert load_config(path).dsu == DsuConfig("127.0.0.1", 26760, 26770, 0)
    path.write_text(json.dumps({"dsu": {"port": 26760, "nunchuk_port": 26760}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
