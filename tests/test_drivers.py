from wiichinahook.drivers import GENERIC_BLUETOOTH_ID, choose, packages_for

LIBUSBK = """[Version]
Signature = "$Windows NT$"
Class = "libusbk devices"
Provider = "libusbK"
DriverVer = 06/13/2024, 3.1.0.0
[Devices.NTamd64]
"Intel(R) Wireless Bluetooth(R)" = LUsbK_Device, USB\VID_8087&PID_0A2A
"""
INTEL = """[Version]
Signature="$WINDOWS NT$"
Class=Bluetooth
Provider=%PROVIDER_NAME%
DriverVer=11/29/2022,20.100.10.10
[Intel.NTamd64]
%iBT_Usb.DeviceDesc%=ibtusb, USB\VID_8087&PID_0A2A
"""
OTHER = """[Version]
Class=Bluetooth
DriverVer=01/01/2020,1.0.0.0
[Models]
%x%=y, USB\VID_0BDA&PID_8771
"""


def store(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="latin-1")
    (tmp_path / "bth.inf").write_text("[Version]\nClass=Bluetooth\n")
    return tmp_path


def test_switch_targets_pick_latest_matching_packages(tmp_path):
    packages = packages_for(0x8087, 0x0A2A, store(tmp_path, {
        "oem69.inf": LIBUSBK, "oem102.inf": LIBUSBK, "oem67.inf": INTEL, "oem5.inf": OTHER}))
    direct, bluetooth = choose(packages, "direct"), choose(packages, "bluetooth")
    assert direct.inf.name == "oem102.inf" and direct.kind == "libusbk"
    assert direct.hardware_id == r"USB\VID_8087&PID_0A2A"
    assert bluetooth.inf.name == "oem67.inf" and bluetooth.version == (20, 100, 10, 10)
    assert all(p.inf.name != "oem5.inf" for p in packages)  # other adapters are ignored


def test_generic_windows_driver_when_no_vendor_package(tmp_path):
    packages = packages_for(0x8087, 0x0A2A, store(tmp_path, {"oem69.inf": LIBUSBK}))
    fallback = choose(packages, "bluetooth")
    assert fallback.inf.name == "bth.inf" and fallback.hardware_id == GENERIC_BLUETOOTH_ID
    assert choose(packages_for(0x1234, 0x5678, tmp_path), "direct") is None  # needs Zadig once
