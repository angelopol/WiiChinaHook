"""Switch a USB Bluetooth adapter between libusbK and the Windows Bluetooth driver.

Windows keeps every installed driver package in its store (C:\\Windows\\INF\\oem*.inf).
Once a libusbK package exists for an adapter (e.g. created by Zadig the first time),
the adapter can be switched both ways by forcing one package on its hardware ID with
UpdateDriverForPlugAndPlayDevices; no Zadig needed. Without a vendor package the
generic Microsoft driver (bth.inf, by compatible ID) restores normal Bluetooth.
Installing a driver requires administrator rights: the GUI runs this module elevated
(`python -m wiichinahook.drivers apply ...`) and Windows shows its UAC prompt.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

INF_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "INF"
GENERIC_BLUETOOTH_INF = INF_DIR / "bth.inf"
GENERIC_BLUETOOTH_ID = r"USB\Class_E0&SubClass_01&Prot_01"
INSTALLFLAG_FORCE = 0x1


@dataclass(frozen=True)
class DriverPackage:
    inf: Path
    kind: str              # "libusbk", "winusb" or "bluetooth"
    provider: str
    version: tuple
    hardware_id: str

    @property
    def direct(self):
        return self.kind in ("libusbk", "winusb")

    def label(self):
        return f"{self.inf.name} ({self.provider or self.kind}, {'.'.join(map(str, self.version)) or '?'})"


def _field(text, name):
    match = re.search(rf"(?im)^\s*{name}\s*=\s*(.+?)\s*$", text)
    return match.group(1).strip().strip('"') if match else ""


def classify_inf(text: str) -> str | None:
    if re.search(r"libusbk", text, re.I):
        return "libusbk"
    if re.search(r"winusb", text, re.I):
        return "winusb"
    if _field(text, "Class").lower() == "bluetooth":
        return "bluetooth"
    return None


def parse_version(text: str) -> tuple:
    value = _field(text, "DriverVer")
    parts = value.split(",")[-1].strip() if value else ""
    return tuple(int(p) for p in re.findall(r"\d+", parts)[:4])


def packages_for(vid: int, pid: int, inf_dir: Path = INF_DIR) -> list[DriverPackage]:
    """Driver packages in the store that list this adapter, newest first per kind,
    plus the generic Microsoft Bluetooth driver as a last resort."""
    hardware_id = f"USB\\VID_{vid:04X}&PID_{pid:04X}"
    needle = f"VID_{vid:04X}&PID_{pid:04X}".lower()
    found = []
    for inf in sorted(inf_dir.glob("oem*.inf")):
        try:
            text = inf.read_text(encoding="utf-16") if inf.read_bytes()[:2] in (b"\xff\xfe", b"\xfe\xff") \
                else inf.read_text(encoding="latin-1")
        except OSError:
            continue
        if needle not in text.lower():
            continue
        kind = classify_inf(text)
        if kind:
            provider = _field(text, "Provider")
            if provider.startswith("%"):
                provider = ""
            found.append(DriverPackage(inf, kind, provider, parse_version(text), hardware_id))
    oem_number = lambda p: int(re.sub(r"\D", "", p.inf.stem) or 0)  # higher = installed later
    found.sort(key=lambda p: (p.kind, p.version, oem_number(p)), reverse=True)
    if (inf_dir / "bth.inf").exists():
        found.append(DriverPackage(inf_dir / "bth.inf", "bluetooth", "Microsoft (generic)", (), GENERIC_BLUETOOTH_ID))
    return found


def choose(packages: list[DriverPackage], target: str) -> DriverPackage | None:
    """target 'direct' (libusbK preferred, then WinUSB) or 'bluetooth'."""
    if target == "direct":
        for kind in ("libusbk", "winusb"):
            match = next((p for p in packages if p.kind == kind), None)
            if match:
                return match
        return None
    vendor = [p for p in packages if p.kind == "bluetooth" and p.hardware_id != GENERIC_BLUETOOTH_ID]
    return vendor[0] if vendor else next((p for p in packages if p.kind == "bluetooth"), None)


def apply_driver(hardware_id: str, inf: Path) -> dict:
    """Force `inf` on every present device matching `hardware_id`. Needs admin."""
    import ctypes
    from ctypes import wintypes
    newdev = ctypes.WinDLL("newdev", use_last_error=True)
    update = newdev.UpdateDriverForPlugAndPlayDevicesW
    update.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                       ctypes.POINTER(wintypes.BOOL)]
    update.restype = wintypes.BOOL
    reboot = wintypes.BOOL(False)
    ok = update(None, hardware_id, str(inf), INSTALLFLAG_FORCE, ctypes.byref(reboot))
    error = 0 if ok else ctypes.get_last_error()
    return {"ok": bool(ok), "error": error, "message": ctypes.FormatError(error) if error else "",
            "reboot": bool(reboot.value), "inf": str(inf), "hardware_id": hardware_id}


def run_elevated(hardware_id: str, inf: Path, timeout: float = 180.0) -> dict:
    """Run apply_driver in an elevated copy of this Python (UAC prompt)."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    result_file = Path(tempfile.gettempdir()) / f"wiichinahook-driver-{os.getpid()}-{time.time_ns()}.json"
    args = subprocess.list2cmdline(["-m", "wiichinahook.drivers", "apply", "--hardware-id", hardware_id,
                                    "--inf", str(inf), "--result", str(result_file)])
    info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x40,  # NOCLOSEPROCESS
                             lpVerb="runas", lpFile=sys.executable, lpParameters=args, nShow=0)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        return {"ok": False, "error": error, "cancelled": error == 1223,
                "message": "Administrator permission was not granted" if error == 1223 else ctypes.FormatError(error)}
    try:
        kernel32.WaitForSingleObject(info.hProcess, int(timeout * 1000))
    finally:
        kernel32.CloseHandle(info.hProcess)
    try:
        return json.loads(result_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "error": -1, "message": "The elevated driver installer did not report a result"}
    finally:
        result_file.unlink(missing_ok=True)


def switch_adapter(vid: int, pid: int, target: str) -> dict:
    package = choose(packages_for(vid, pid), target)
    if package is None:
        return {"ok": False, "error": -2, "no_package": True,
                "message": "No libusbK/WinUSB package for this adapter in the driver store; install it once with Zadig"}
    result = run_elevated(package.hardware_id, package.inf)
    result.setdefault("package", package.label())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m wiichinahook.drivers")
    sub = parser.add_subparsers(dest="command", required=True)
    apply = sub.add_parser("apply", help="force a driver package (run as administrator)")
    apply.add_argument("--hardware-id", required=True)
    apply.add_argument("--inf", required=True)
    apply.add_argument("--result", required=True)
    listing = sub.add_parser("list", help="driver packages for an adapter")
    listing.add_argument("--vid", required=True)
    listing.add_argument("--pid", required=True)
    args = parser.parse_args(argv)
    if args.command == "apply":
        try:
            result = apply_driver(args.hardware_id, Path(args.inf))
        except Exception as exc:  # report anything to the unelevated caller
            result = {"ok": False, "error": -3, "message": f"{type(exc).__name__}: {exc}"}
        Path(args.result).write_text(json.dumps(result), encoding="utf-8")
    else:
        for package in packages_for(int(args.vid, 16), int(args.pid, 16)):
            print(package.kind, package.label(), package.hardware_id)


if __name__ == "__main__":
    main()
