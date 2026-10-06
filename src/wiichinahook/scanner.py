from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class ScanResult:
    address: str
    class_of_device: int
    rssi: int
    name: str | None = None
    eir_name: str | None = None
    is_wiimote_guess: bool = False


async def scan_classic_devices(
    transport: str = "usb:8087:0a2a",
    duration: float = 12.0,
    request_names: bool = False,
) -> list[ScanResult]:
    from bumble.core import AdvertisingData, DeviceClass
    from bumble.device import Device, DeviceConfiguration
    from bumble.host import Host
    from bumble.hci import Address
    from bumble.transport import open_transport_or_link

    results: dict[str, ScanResult] = {}
    remote_addresses = {}

    async with await open_transport_or_link(transport) as hci_transport:
        config = DeviceConfiguration()
        config.name = "WiiChinaHook Scanner"
        config.classic_enabled = True
        config.le_enabled = False
        device = Device(config=config, host=Host(hci_transport.source, hci_transport.sink))
        await device.power_on()
        print(f"Bluetooth adapter address: {device.public_address}")
        print(f"Scanning Bluetooth Classic for {duration:.0f}s...")

        @device.listens_to("inquiry_result")
        def on_inquiry_result(address, class_of_device: int, data, rssi: int) -> None:
            address_text = address.to_string(False)
            remote_addresses[address_text] = address
            eir_name = extract_name(data)
            result = ScanResult(
                address=address_text,
                class_of_device=class_of_device,
                rssi=rssi,
                eir_name=eir_name,
                is_wiimote_guess=is_probable_wiimote(eir_name, class_of_device),
            )
            results[address_text] = result

            service_classes, major_class, minor_class = DeviceClass.split_class_of_device(
                class_of_device
            )
            major_name = DeviceClass.major_device_class_name(major_class)
            minor_name = DeviceClass.minor_device_class_name(major_class, minor_class)
            marker = " *probable Wiimote*" if result.is_wiimote_guess else ""
            label = f" name={eir_name!r}" if eir_name else ""
            print(
                f"found {address_text} class=0x{class_of_device:06x} "
                f"{major_name}/{minor_name} rssi={rssi}{label}{marker}"
            )

        await device.start_discovery(auto_restart=False)
        try:
            await asyncio.sleep(duration)
        finally:
            await device.stop_discovery()

        if request_names:
            print("Requesting remote names...")
            for address_text, address in remote_addresses.items():
                try:
                    results[address_text].name = await asyncio.wait_for(
                        device.request_remote_name(address),
                        timeout=6.0,
                    )
                except Exception as exc:
                    results[address_text].name = f"<name unavailable: {exc}>"

    return sorted(
        results.values(),
        key=lambda item: (not item.is_wiimote_guess, item.name or item.eir_name or "", item.address),
    )


def extract_name(data) -> str | None:
    from bumble.core import AdvertisingData

    for ad_type in (
        AdvertisingData.COMPLETE_LOCAL_NAME,
        AdvertisingData.SHORTENED_LOCAL_NAME,
        AdvertisingData.BROADCAST_NAME,
    ):
        name = data.get(ad_type)
        if isinstance(name, str) and name:
            return name
    return None


def is_probable_wiimote(name: str | None, class_of_device: int) -> bool:
    if name:
        lowered = name.lower()
        if "nintendo" in lowered or "rvl-cnt" in lowered or "wiimote" in lowered:
            return True

    # Many Wiimotes report Peripheral/Joystick-ish COD values, but clones vary.
    major_device_class = (class_of_device >> 8) & 0x1F
    return major_device_class == 0x05


def print_scan_summary(results: list[ScanResult]) -> None:
    if not results:
        print("No Bluetooth Classic devices found.")
        return

    print("")
    print("Scan results:")
    for result in results:
        name = result.name or result.eir_name or "-"
        hint = " probable-wiimote" if result.is_wiimote_guess else ""
        print(
            f"{result.address}  class=0x{result.class_of_device:06x}  "
            f"rssi={result.rssi:>4}  name={name}{hint}"
        )
