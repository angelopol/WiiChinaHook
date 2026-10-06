import json

from wiichinahook.usb_drivers import parse_pnp


def entry(name, device_id, service, status="OK", code=0):
    return {"Name": name, "DeviceID": device_id, "Service": service, "Status": status,
            "ConfigManagerErrorCode": code}


INTEL = entry("Intel(R) Wireless Bluetooth(R)", r"USB\VID_8087&PID_0A2A\6&3878EF1F", "libusbK")
CSR_FAILED = entry("Generic Bluetooth Radio", r"USB\VID_0A12&PID_0001\6&343B380F", "WinUSB", "Error", 10)
WINDOWS_BT = entry("Realtek Bluetooth", r"USB\VID_0BDA&PID_8771\1", "BTHUSB")
GAMEPAD = entry("Some WinUSB gamepad", r"USB\VID_1234&PID_5678\1", "WinUSB")


def test_single_object_output_from_powershell():
    [intel] = parse_pnp(json.dumps(INTEL))
    assert (intel.key, intel.driver, intel.usable) == ("8087:0a2a", "libusbK", True)
    assert intel.label() == "Intel(R) Wireless Bluetooth(R) — 8087:0A2A (libusbK, OK)"


def test_usable_first_failed_and_windows_driver_not_usable_non_bluetooth_filtered():
    adapters = parse_pnp(json.dumps([WINDOWS_BT, CSR_FAILED, GAMEPAD, INTEL]),
                         bluetooth_ids={(0x8087, 0x0A2A), (0x0A12, 0x0001)})
    assert adapters[0].key == "8087:0a2a" and adapters[0].usable
    csr = next(a for a in adapters if a.key == "0a12:0001")
    assert not csr.usable and csr.problem == 10 and "error 10" in csr.label()
    realtek = next(a for a in adapters if a.driver == "BTHUSB")
    assert realtek.bluetooth and not realtek.usable
    gamepad = next(a for a in adapters if a.key == "1234:5678")
    assert not gamepad.bluetooth and not gamepad.usable
    assert parse_pnp("") == []
