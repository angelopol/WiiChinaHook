from __future__ import annotations

from dataclasses import dataclass

import usb.core
import usb.util
import usb.backend.libusb1
import libusb_package


def usb_backend():
    return usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)


@dataclass(frozen=True)
class UsbDeviceInfo:
    vid: int
    pid: int
    bus: int | None
    address: int | None
    manufacturer: str | None
    product: str | None


def _safe_string(device: usb.core.Device, index: int | None) -> str | None:
    if not index:
        return None
    try:
        return usb.util.get_string(device, index)
    except Exception:
        return None


def list_devices() -> list[UsbDeviceInfo]:
    devices = []
    for device in usb.core.find(find_all=True, backend=usb_backend()):
        devices.append(
            UsbDeviceInfo(
                vid=device.idVendor,
                pid=device.idProduct,
                bus=getattr(device, "bus", None),
                address=getattr(device, "address", None),
                manufacturer=_safe_string(device, device.iManufacturer),
                product=_safe_string(device, device.iProduct),
            )
        )
    return devices


def find_device(vid: int, pid: int) -> UsbDeviceInfo | None:
    device = usb.core.find(idVendor=vid, idProduct=pid, backend=usb_backend())
    if device is None:
        return None
    return UsbDeviceInfo(
        vid=device.idVendor,
        pid=device.idProduct,
        bus=getattr(device, "bus", None),
        address=getattr(device, "address", None),
        manufacturer=_safe_string(device, device.iManufacturer),
        product=_safe_string(device, device.iProduct),
    )


def format_device(device: UsbDeviceInfo) -> str:
    label = " ".join(part for part in [device.manufacturer, device.product] if part)
    suffix = f" {label}" if label else ""
    location = ""
    if device.bus is not None and device.address is not None:
        location = f" bus={device.bus} address={device.address}"
    return f"{device.vid:04x}:{device.pid:04x}{location}{suffix}"
