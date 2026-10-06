"""Find USB Bluetooth adapters usable by the Bluetooth passthrough mode (Windows).

An adapter is usable when Windows bound it to a direct-access driver (libusbK or
WinUSB, e.g. installed with Zadig) and the device started. Adapters still on the
Windows Bluetooth driver (BTHUSB) are reported as convertible.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess

DIRECT_DRIVERS = ("libusbK", "WinUSB")
ZADIG_URL = "https://zadig.akeo.ie/"
_PNP_QUERY = (
    "Get-CimInstance Win32_PnPEntity -Filter \"DeviceID LIKE 'USB\\\\VID_%'\" | "
    "Where-Object { $_.Service -in 'libusbK','WinUSB','BTHUSB' } | "
    "Select-Object Name,DeviceID,Service,Status,ConfigManagerErrorCode | ConvertTo-Json -Compress"
)


@dataclass(frozen=True)
class UsbAdapter:
    vid: int
    pid: int
    name: str
    driver: str
    ok: bool
    problem: int = 0
    bluetooth: bool = True

    @property
    def usable(self):
        return self.driver in DIRECT_DRIVERS and self.ok and self.bluetooth

    @property
    def key(self):
        return f"{self.vid:04x}:{self.pid:04x}"

    def label(self):
        state = "OK" if self.ok else f"error {self.problem}"
        return f"{self.name} — {self.vid:04X}:{self.pid:04X} ({self.driver}, {state})"


def parse_pnp(output: str, bluetooth_ids=None) -> list[UsbAdapter]:
    """Parse the ConvertTo-Json output of _PNP_QUERY (an object or a list)."""
    output = output.strip()
    if not output:
        return []
    data = json.loads(output)
    if isinstance(data, dict):
        data = [data]
    adapters = []
    for entry in data:
        match = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", entry.get("DeviceID", ""), re.I)
        if not match:
            continue
        vid, pid = int(match.group(1), 16), int(match.group(2), 16)
        driver = entry.get("Service") or ""
        bluetooth = driver == "BTHUSB" or bluetooth_ids is None or (vid, pid) in bluetooth_ids
        adapters.append(UsbAdapter(vid, pid, entry.get("Name") or "USB device", driver,
                                   entry.get("Status") == "OK", int(entry.get("ConfigManagerErrorCode") or 0),
                                   bluetooth))
    return sorted(adapters, key=lambda a: (not a.usable, a.driver, a.name))


def bluetooth_usb_ids() -> set[tuple[int, int]] | None:
    """(vid, pid) of USB devices whose descriptors declare the Bluetooth class
    (0xE0/0x01/0x01). Descriptors are cached by Windows, no open is needed."""
    try:
        import libusb_package
        import usb.core
        devices = usb.core.find(find_all=True, backend=libusb_package.get_libusb1_backend())
        ids = set()
        for device in devices:
            classes = {(device.bDeviceClass, device.bDeviceSubClass)}
            try:
                for config in device:
                    classes.update((i.bInterfaceClass, i.bInterfaceSubClass) for i in config)
            except Exception:
                pass
            if (0xE0, 0x01) in classes:
                ids.add((device.idVendor, device.idProduct))
        return ids
    except Exception:
        return None  # unknown: do not filter


def list_adapters() -> list[UsbAdapter]:
    if os.name != "nt":
        return []
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PNP_QUERY],
                            capture_output=True, text=True, timeout=30,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return parse_pnp(result.stdout, bluetooth_usb_ids())


def find_zadig() -> Path | None:
    """A downloaded Zadig executable in the usual places, newest first."""
    home = Path.home()
    folders = [home / "Downloads", home / "Desktop", home / "OneDrive" / "Escritorio",
               home / "OneDrive" / "Desktop", Path.cwd()]
    found = [p for folder in folders if folder.is_dir() for p in folder.glob("zadig*.exe")]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None
