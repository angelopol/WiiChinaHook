from __future__ import annotations

import time
from dataclasses import dataclass

import usb.core
import usb.util
from .usb_probe import usb_backend


OGF_LINK_CONTROL = 0x01
OGF_CONTROLLER_BASEBAND = 0x03
OGF_INFORMATIONAL = 0x04

OCF_INQUIRY = 0x0001
OCF_ACCEPT_CONNECTION_REQUEST = 0x0009
OCF_LINK_KEY_REQUEST_NEGATIVE_REPLY = 0x000C
OCF_PIN_CODE_REQUEST_REPLY = 0x000D
OCF_RESET = 0x0003
OCF_SET_EVENT_MASK = 0x0001
OCF_READ_SCAN_ENABLE = 0x0019
OCF_WRITE_LOCAL_NAME = 0x0013
OCF_WRITE_SCAN_ENABLE = 0x001A
OCF_WRITE_CLASS_OF_DEVICE = 0x0024
OCF_WRITE_INQUIRY_SCAN_ACTIVITY = 0x001E
OCF_WRITE_PAGE_SCAN_ACTIVITY = 0x001C
OCF_WRITE_INQUIRY_MODE = 0x0045
OCF_WRITE_SIMPLE_PAIRING_MODE = 0x0056
OCF_READ_LOCAL_VERSION_INFORMATION = 0x0001
OCF_READ_LOCAL_SUPPORTED_COMMANDS = 0x0002
OCF_READ_LOCAL_SUPPORTED_FEATURES = 0x0003
OCF_READ_BD_ADDR = 0x0009

EVT_INQUIRY_COMPLETE = 0x01
EVT_INQUIRY_RESULT = 0x02
EVT_CONNECTION_COMPLETE = 0x03
EVT_CONNECTION_REQUEST = 0x04
EVT_AUTHENTICATION_COMPLETE = 0x06
EVT_COMMAND_COMPLETE = 0x0E
EVT_COMMAND_STATUS = 0x0F
EVT_PIN_CODE_REQUEST = 0x16
EVT_LINK_KEY_REQUEST = 0x17
EVT_LINK_KEY_NOTIFICATION = 0x18
EVT_INQUIRY_RESULT_WITH_RSSI = 0x22
EVT_EXTENDED_INQUIRY_RESULT = 0x2F

HCI_INQUIRY_LAP = bytes([0x33, 0x8B, 0x9E])


@dataclass
class HciInquiryResult:
    address: str
    class_of_device: int
    rssi: int | None = None
    name: str | None = None


class RawHciUsbAdapter:
    def __init__(self, vid: int, pid: int) -> None:
        self.vid = vid
        self.pid = pid
        self.device = usb.core.find(idVendor=vid, idProduct=pid, backend=usb_backend())
        if self.device is None:
            raise RuntimeError(f"USB adapter {vid:04x}:{pid:04x} not found")

        self.interface_number = 0
        self.event_endpoint = None

    def open(self) -> None:
        self.device.set_configuration()
        config = self.device.get_active_configuration()
        interface = config[(self.interface_number, 0)]

        try:
            kernel_driver_active = self.device.is_kernel_driver_active(self.interface_number)
        except (NotImplementedError, usb.core.USBError):
            kernel_driver_active = False

        if kernel_driver_active:
            try:
                self.device.detach_kernel_driver(self.interface_number)
            except (NotImplementedError, usb.core.USBError):
                pass

        usb.util.claim_interface(self.device, self.interface_number)

        for endpoint in interface:
            direction = usb.util.endpoint_direction(endpoint.bEndpointAddress)
            transfer_type = usb.util.endpoint_type(endpoint.bmAttributes)
            if (
                direction == usb.util.ENDPOINT_IN
                and transfer_type == usb.util.ENDPOINT_TYPE_INTR
            ):
                self.event_endpoint = endpoint
                break

        if self.event_endpoint is None:
            raise RuntimeError("Bluetooth HCI event interrupt endpoint not found")

    def close(self) -> None:
        usb.util.release_interface(self.device, self.interface_number)
        usb.util.dispose_resources(self.device)

    def reset(self) -> None:
        self.send_command(OGF_CONTROLLER_BASEBAND, OCF_RESET)
        self.wait_for_command_complete(opcode(OGF_CONTROLLER_BASEBAND, OCF_RESET), timeout=2.0)

    def command_complete(self, ogf: int, ocf: int, params: bytes = b"", timeout: float = 2.0) -> bytes | None:
        expected_opcode = opcode(ogf, ocf)
        self.send_command(ogf, ocf, params)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.read_event(timeout_ms=250)
            if event is None:
                continue
            event_code, event_params = event
            if event_code == EVT_COMMAND_COMPLETE and len(event_params) >= 3:
                completed_opcode = int.from_bytes(event_params[1:3], "little")
                if completed_opcode == expected_opcode:
                    return event_params[3:]
            if event_code == EVT_COMMAND_STATUS and len(event_params) >= 4:
                completed_opcode = int.from_bytes(event_params[2:4], "little")
                if completed_opcode == expected_opcode:
                    return event_params[:1]
        return None

    def read_bd_addr(self) -> str | None:
        response = self.command_complete(OGF_INFORMATIONAL, OCF_READ_BD_ADDR)
        if response is not None and len(response) >= 7 and response[0] == 0:
            return format_bd_addr(response[1:7])
        return None

    def read_scan_enable(self) -> int | None:
        response = self.command_complete(OGF_CONTROLLER_BASEBAND, OCF_READ_SCAN_ENABLE)
        if response is not None and len(response) >= 2 and response[0] == 0:
            return response[1]
        return None

    def read_local_version(self) -> bytes | None:
        response = self.command_complete(OGF_INFORMATIONAL, OCF_READ_LOCAL_VERSION_INFORMATION)
        if response is not None and response[:1] == b"\x00":
            return response[1:]
        return None

    def read_local_supported_commands(self) -> bytes | None:
        response = self.command_complete(OGF_INFORMATIONAL, OCF_READ_LOCAL_SUPPORTED_COMMANDS)
        if response is not None and response[:1] == b"\x00":
            return response[1:]
        return None

    def read_local_supported_features(self) -> bytes | None:
        response = self.command_complete(OGF_INFORMATIONAL, OCF_READ_LOCAL_SUPPORTED_FEATURES)
        if response is not None and response[:1] == b"\x00":
            return response[1:]
        return None

    def set_event_mask(self) -> None:
        self.send_command(OGF_CONTROLLER_BASEBAND, OCF_SET_EVENT_MASK, b"\xff\xff\xff\xff\xff\xff\xff\x3f")
        self.wait_for_command_complete(
            opcode(OGF_CONTROLLER_BASEBAND, OCF_SET_EVENT_MASK),
            timeout=2.0,
            ignore_errors=True,
        )

    def disable_simple_pairing(self) -> None:
        self.send_command(OGF_CONTROLLER_BASEBAND, OCF_WRITE_SIMPLE_PAIRING_MODE, b"\x00")
        self.wait_for_command_complete(
            opcode(OGF_CONTROLLER_BASEBAND, OCF_WRITE_SIMPLE_PAIRING_MODE),
            timeout=2.0,
            ignore_errors=True,
        )

    def set_inquiry_mode(self, mode: int) -> None:
        self.send_command(OGF_CONTROLLER_BASEBAND, OCF_WRITE_INQUIRY_MODE, bytes([mode]))
        self.wait_for_command_complete(
            opcode(OGF_CONTROLLER_BASEBAND, OCF_WRITE_INQUIRY_MODE),
            timeout=2.0,
            ignore_errors=True,
        )

    def start_inquiry(self, seconds: float) -> None:
        length = max(1, min(0x30, round(seconds / 1.28)))
        self.send_command(OGF_LINK_CONTROL, OCF_INQUIRY, HCI_INQUIRY_LAP + bytes([length, 0]))
        self.wait_for_command_complete(opcode(OGF_LINK_CONTROL, OCF_INQUIRY), timeout=2.0)

    def set_connectable_discoverable(self) -> None:
        self.send_command(OGF_CONTROLLER_BASEBAND, OCF_WRITE_SCAN_ENABLE, b"\x03")
        self.wait_for_command_complete(
            opcode(OGF_CONTROLLER_BASEBAND, OCF_WRITE_SCAN_ENABLE),
            timeout=2.0,
        )

    def set_scan_activity(self) -> None:
        # Small intervals keep the controller listening frequently during this diagnostic window.
        interval = (0x0800).to_bytes(2, "little")
        window = (0x0800).to_bytes(2, "little")
        for ocf in (OCF_WRITE_PAGE_SCAN_ACTIVITY, OCF_WRITE_INQUIRY_SCAN_ACTIVITY):
            self.send_command(OGF_CONTROLLER_BASEBAND, ocf, interval + window)
            self.wait_for_command_complete(
                opcode(OGF_CONTROLLER_BASEBAND, ocf),
                timeout=2.0,
                ignore_errors=True,
            )

    def set_class_of_device(self, class_of_device: int) -> None:
        self.send_command(
            OGF_CONTROLLER_BASEBAND,
            OCF_WRITE_CLASS_OF_DEVICE,
            class_of_device.to_bytes(3, "little"),
        )
        self.wait_for_command_complete(
            opcode(OGF_CONTROLLER_BASEBAND, OCF_WRITE_CLASS_OF_DEVICE),
            timeout=2.0,
            ignore_errors=True,
        )

    def set_local_name(self, name: str) -> None:
        name_bytes = name.encode("utf-8")[:248]
        self.send_command(
            OGF_CONTROLLER_BASEBAND,
            OCF_WRITE_LOCAL_NAME,
            name_bytes.ljust(248, b"\x00"),
        )
        self.wait_for_command_complete(
            opcode(OGF_CONTROLLER_BASEBAND, OCF_WRITE_LOCAL_NAME),
            timeout=2.0,
            ignore_errors=True,
        )

    def accept_connection(self, address: bytes, role: int = 0) -> None:
        self.send_command(OGF_LINK_CONTROL, OCF_ACCEPT_CONNECTION_REQUEST, address[:6] + bytes([role]))

    def link_key_negative_reply(self, address: bytes) -> None:
        self.send_command(OGF_LINK_CONTROL, OCF_LINK_KEY_REQUEST_NEGATIVE_REPLY, address[:6])

    def pin_code_reply(self, address: bytes, pin: bytes) -> None:
        self.send_command(
            OGF_LINK_CONTROL,
            OCF_PIN_CODE_REQUEST_REPLY,
            address[:6] + bytes([len(pin)]) + pin[:16].ljust(16, b"\x00"),
        )

    def send_command(self, ogf: int, ocf: int, params: bytes = b"") -> None:
        command = opcode(ogf, ocf).to_bytes(2, "little") + bytes([len(params)]) + params
        self.device.ctrl_transfer(0x20, 0, 0, 0, command, timeout=1000)

    def wait_for_command_complete(
        self, expected_opcode: int, timeout: float, ignore_errors: bool = False
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.read_event(timeout_ms=250)
            if event is None:
                continue
            event_code, params = event
            if event_code == EVT_COMMAND_COMPLETE and len(params) >= 4:
                completed_opcode = int.from_bytes(params[1:3], "little")
                status = params[3]
                if completed_opcode == expected_opcode:
                    if status and not ignore_errors:
                        raise RuntimeError(f"HCI command 0x{expected_opcode:04x} failed: 0x{status:02x}")
                    return
            if event_code == EVT_COMMAND_STATUS and len(params) >= 4:
                status = params[0]
                completed_opcode = int.from_bytes(params[2:4], "little")
                if completed_opcode == expected_opcode:
                    if status and not ignore_errors:
                        raise RuntimeError(f"HCI command 0x{expected_opcode:04x} failed: 0x{status:02x}")
                    return

    def read_event(self, timeout_ms: int = 1000) -> tuple[int, bytes] | None:
        if self.event_endpoint is None:
            raise RuntimeError("adapter is not open")
        try:
            raw = bytes(self.event_endpoint.read(self.event_endpoint.wMaxPacketSize, timeout_ms))
        except usb.core.USBTimeoutError:
            return None
        except usb.core.USBError as exc:
            if is_usb_timeout(exc):
                return None
            raise
        if len(raw) < 2:
            return None
        event_code = raw[0]
        param_len = raw[1]
        return event_code, raw[2 : 2 + param_len]


def scan_raw_hci(
    vid: int,
    pid: int,
    seconds: float = 12.0,
    reset: bool = False,
    inquiry_mode: int = 2,
    verbose: bool = False,
) -> list[HciInquiryResult]:
    adapter = RawHciUsbAdapter(vid, pid)
    adapter.open()
    results: dict[str, HciInquiryResult] = {}
    try:
        if reset:
            adapter.reset()
        local_address = adapter.read_bd_addr()
        if local_address:
            print(f"USB HCI adapter address: {local_address}")
        adapter.set_inquiry_mode(inquiry_mode)
        adapter.start_inquiry(seconds)
        print(
            f"Raw HCI inquiry on {vid:04x}:{pid:04x} for about {seconds:.0f}s "
            f"(mode={inquiry_mode})..."
        )

        deadline = time.monotonic() + seconds + 2.0
        while time.monotonic() < deadline:
            event = adapter.read_event(timeout_ms=500)
            if event is None:
                continue
            event_code, params = event
            if verbose:
                print(f"event {event_name(event_code)} params={params.hex(' ')}")
            if event_code == EVT_INQUIRY_COMPLETE:
                status = params[0] if params else 0
                print(f"Inquiry complete status=0x{status:02x}")
                break
            for result in parse_inquiry_event(event_code, params):
                previous = results.get(result.address)
                if previous is None or result.rssi is not None:
                    results[result.address] = result
                label = f" rssi={result.rssi}" if result.rssi is not None else ""
                name = f" name={result.name!r}" if result.name else ""
                print(
                    f"found {result.address} class=0x{result.class_of_device:06x}"
                    f"{label}{name}"
                )
    finally:
        adapter.close()

    return sorted(results.values(), key=lambda item: (item.name or "", item.address))


def listen_raw_hci(
    vid: int,
    pid: int,
    seconds: float = 30.0,
    reset: bool = False,
    local_name: str = "Nintendo RVL-001",
    class_of_device: int = 0x000500,
    verbose: bool = False,
) -> None:
    adapter = RawHciUsbAdapter(vid, pid)
    adapter.open()
    try:
        if reset:
            adapter.reset()
        adapter.set_event_mask()
        adapter.disable_simple_pairing()
        local_address = adapter.read_bd_addr()
        if local_address:
            print(f"USB HCI adapter address: {local_address}")

        adapter.set_local_name(local_name)
        adapter.set_class_of_device(class_of_device)
        adapter.set_scan_activity()
        adapter.set_connectable_discoverable()
        print(
            f"Listening for raw HCI events on {vid:04x}:{pid:04x} for {seconds:.0f}s "
            f"as {local_name!r}, class=0x{class_of_device:06x}..."
        )

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            event = adapter.read_event(timeout_ms=500)
            if event is None:
                continue
            event_code, params = event
            if verbose or event_code in (
                EVT_CONNECTION_REQUEST,
                EVT_CONNECTION_COMPLETE,
                EVT_INQUIRY_RESULT,
                EVT_INQUIRY_RESULT_WITH_RSSI,
                EVT_EXTENDED_INQUIRY_RESULT,
            ):
                print(format_event(event_code, params))
    finally:
        adapter.close()


def show_raw_hci_info(vid: int, pid: int, reset: bool = False) -> None:
    adapter = RawHciUsbAdapter(vid, pid)
    adapter.open()
    try:
        if reset:
            adapter.reset()
        local_address = adapter.read_bd_addr()
        print(f"USB HCI adapter: {vid:04x}:{pid:04x}")
        print(f"BD_ADDR: {local_address or '-'}")

        version = adapter.read_local_version()
        if version and len(version) >= 8:
            print(
                "Version: "
                f"hci=0x{version[0]:02x} "
                f"hci_rev=0x{int.from_bytes(version[1:3], 'little'):04x} "
                f"lmp=0x{version[3]:02x} "
                f"manufacturer=0x{int.from_bytes(version[4:6], 'little'):04x} "
                f"lmp_subversion=0x{int.from_bytes(version[6:8], 'little'):04x}"
            )

        scan_enable = adapter.read_scan_enable()
        if scan_enable is not None:
            print(f"Scan enable: 0x{scan_enable:02x} ({scan_enable_label(scan_enable)})")

        features = adapter.read_local_supported_features()
        if features:
            print(f"Features: {features.hex(' ')}")

        commands = adapter.read_local_supported_commands()
        if commands:
            print(f"Supported commands: {commands.hex(' ')}")
    finally:
        adapter.close()


def pair_window_raw_hci(
    vid: int,
    pid: int,
    seconds: float = 45.0,
    reset: bool = False,
    local_name: str = "Nintendo RVL-001",
    class_of_device: int = 0x000500,
    pin_mode: str = "host",
) -> None:
    adapter = RawHciUsbAdapter(vid, pid)
    adapter.open()
    try:
        if reset:
            adapter.reset()
        adapter.set_event_mask()
        adapter.disable_simple_pairing()
        local_address = adapter.read_bd_addr()
        local_raw = parse_bd_addr(local_address) if local_address else b"\x00" * 6
        print(f"USB HCI adapter address: {local_address or '-'}")

        adapter.set_local_name(local_name)
        adapter.set_class_of_device(class_of_device)
        adapter.set_scan_activity()
        adapter.set_connectable_discoverable()

        scan_enable = adapter.read_scan_enable()
        if scan_enable is not None:
            print(f"Scan enable now: 0x{scan_enable:02x} ({scan_enable_label(scan_enable)})")

        print(
            f"Pair window open for {seconds:.0f}s as {local_name!r}, "
            f"class=0x{class_of_device:06x}, pin_mode={pin_mode}..."
        )

        peer_raw = None
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            event = adapter.read_event(timeout_ms=500)
            if event is None:
                continue
            event_code, params = event
            print(format_event(event_code, params))

            if event_code == EVT_CONNECTION_REQUEST and len(params) >= 10:
                peer_raw = params[0:6]
                print(f"accepting connection from {format_bd_addr(peer_raw)} as master")
                adapter.accept_connection(peer_raw, role=0)
            elif event_code == EVT_LINK_KEY_REQUEST and len(params) >= 6:
                peer_raw = params[0:6]
                print(f"no link key for {format_bd_addr(peer_raw)}; sending negative reply")
                adapter.link_key_negative_reply(peer_raw)
            elif event_code == EVT_PIN_CODE_REQUEST and len(params) >= 6:
                peer_raw = params[0:6]
                pin = choose_wiimote_pin(pin_mode, local_raw, peer_raw)
                print(f"replying PIN request from {format_bd_addr(peer_raw)} with {pin.hex(' ')}")
                adapter.pin_code_reply(peer_raw, pin)
    finally:
        adapter.close()


def describe_usb_device(vid: int, pid: int) -> list[str]:
    device = usb.core.find(idVendor=vid, idProduct=pid)
    if device is None:
        raise RuntimeError(f"USB adapter {vid:04x}:{pid:04x} not found")

    lines = [f"USB {vid:04x}:{pid:04x}"]
    for config in device:
        lines.append(f"config {config.bConfigurationValue}")
        for interface in config:
            lines.append(
                f"  interface {interface.bInterfaceNumber}, alt {interface.bAlternateSetting}, "
                f"class=0x{interface.bInterfaceClass:02x}, "
                f"subclass=0x{interface.bInterfaceSubClass:02x}, "
                f"protocol=0x{interface.bInterfaceProtocol:02x}"
            )
            for endpoint in interface:
                direction = "IN" if usb.util.endpoint_direction(endpoint.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"
                transfer_type = usb.util.endpoint_type(endpoint.bmAttributes)
                lines.append(
                    f"    ep 0x{endpoint.bEndpointAddress:02x} {direction} "
                    f"type={endpoint_type_name(transfer_type)} "
                    f"max_packet={endpoint.wMaxPacketSize}"
                )
    return lines


def endpoint_type_name(transfer_type: int) -> str:
    names = {
        usb.util.ENDPOINT_TYPE_CTRL: "control",
        usb.util.ENDPOINT_TYPE_ISO: "iso",
        usb.util.ENDPOINT_TYPE_BULK: "bulk",
        usb.util.ENDPOINT_TYPE_INTR: "interrupt",
    }
    return names.get(transfer_type, f"0x{transfer_type:02x}")


def event_name(event_code: int) -> str:
    names = {
        EVT_INQUIRY_COMPLETE: "Inquiry Complete",
        EVT_INQUIRY_RESULT: "Inquiry Result",
        EVT_CONNECTION_COMPLETE: "Connection Complete",
        EVT_CONNECTION_REQUEST: "Connection Request",
        EVT_AUTHENTICATION_COMPLETE: "Authentication Complete",
        EVT_COMMAND_COMPLETE: "Command Complete",
        EVT_COMMAND_STATUS: "Command Status",
        EVT_PIN_CODE_REQUEST: "PIN Code Request",
        EVT_LINK_KEY_REQUEST: "Link Key Request",
        EVT_LINK_KEY_NOTIFICATION: "Link Key Notification",
        EVT_INQUIRY_RESULT_WITH_RSSI: "Inquiry Result With RSSI",
        EVT_EXTENDED_INQUIRY_RESULT: "Extended Inquiry Result",
    }
    return names.get(event_code, f"0x{event_code:02x}")


def format_event(event_code: int, params: bytes) -> str:
    if event_code == EVT_CONNECTION_REQUEST and len(params) >= 10:
        address = format_bd_addr(params[0:6])
        cod = int.from_bytes(params[6:9], "little")
        link_type = params[9]
        return (
            f"event Connection Request from {address} "
            f"class=0x{cod:06x} link_type=0x{link_type:02x}"
        )
    if event_code == EVT_CONNECTION_COMPLETE and len(params) >= 11:
        status = params[0]
        handle = int.from_bytes(params[1:3], "little")
        address = format_bd_addr(params[3:9])
        link_type = params[9]
        encryption = params[10]
        return (
            f"event Connection Complete status=0x{status:02x} handle=0x{handle:04x} "
            f"peer={address} link_type=0x{link_type:02x} encryption=0x{encryption:02x}"
        )
    if event_code == EVT_LINK_KEY_REQUEST and len(params) >= 6:
        return f"event Link Key Request from {format_bd_addr(params[0:6])}"
    if event_code == EVT_PIN_CODE_REQUEST and len(params) >= 6:
        return f"event PIN Code Request from {format_bd_addr(params[0:6])}"
    if event_code == EVT_AUTHENTICATION_COMPLETE and len(params) >= 3:
        status = params[0]
        handle = int.from_bytes(params[1:3], "little")
        return f"event Authentication Complete status=0x{status:02x} handle=0x{handle:04x}"
    if event_code == EVT_LINK_KEY_NOTIFICATION and len(params) >= 23:
        address = format_bd_addr(params[0:6])
        key_type = params[22]
        return f"event Link Key Notification from {address} key_type=0x{key_type:02x}"
    return f"event {event_name(event_code)} params={params.hex(' ')}"


def parse_inquiry_event(event_code: int, params: bytes) -> list[HciInquiryResult]:
    if not params:
        return []
    if event_code == EVT_INQUIRY_RESULT:
        return parse_basic_inquiry_results(params, with_rssi=False)
    if event_code == EVT_INQUIRY_RESULT_WITH_RSSI:
        return parse_basic_inquiry_results(params, with_rssi=True)
    if event_code == EVT_EXTENDED_INQUIRY_RESULT:
        return parse_extended_inquiry_result(params)
    return []


def parse_basic_inquiry_results(params: bytes, with_rssi: bool) -> list[HciInquiryResult]:
    count = params[0]
    results = []
    offset = 1
    address_size = 6 * count
    scan_fields_size = (2 if with_rssi else 3) * count
    class_size = 3 * count
    clock_offset_size = 2 * count
    needed = offset + address_size + scan_fields_size + class_size + clock_offset_size
    if with_rssi:
        needed += count
    if len(params) < needed:
        return results

    addresses_offset = offset
    classes_offset = offset + address_size + scan_fields_size
    rssi_offset = offset + address_size + scan_fields_size + class_size + clock_offset_size

    for index in range(count):
        address = format_bd_addr(params[addresses_offset + index * 6 : addresses_offset + index * 6 + 6])
        cod = int.from_bytes(params[classes_offset + index * 3 : classes_offset + index * 3 + 3], "little")
        rssi = signed_byte(params[rssi_offset + index]) if with_rssi else None
        results.append(HciInquiryResult(address=address, class_of_device=cod, rssi=rssi))
    return results


def parse_extended_inquiry_result(params: bytes) -> list[HciInquiryResult]:
    if len(params) < 14:
        return []
    address = format_bd_addr(params[1:7])
    cod = int.from_bytes(params[9:12], "little")
    rssi = signed_byte(params[14]) if len(params) > 14 else None
    eir = params[15:] if len(params) > 15 else b""
    return [HciInquiryResult(address=address, class_of_device=cod, rssi=rssi, name=eir_name(eir))]


def eir_name(data: bytes) -> str | None:
    offset = 0
    while offset + 1 < len(data):
        length = data[offset]
        if length == 0:
            break
        ad_type = data[offset + 1]
        ad_data = data[offset + 2 : offset + 1 + length]
        if ad_type in (0x08, 0x09):
            try:
                return ad_data.decode("utf-8", errors="replace")
            except UnicodeDecodeError:
                return None
        offset += 1 + length
    return None


def opcode(ogf: int, ocf: int) -> int:
    return (ogf << 10) | ocf


def format_bd_addr(raw: bytes) -> str:
    return ":".join(f"{byte:02X}" for byte in reversed(raw[:6]))


def signed_byte(value: int) -> int:
    return value - 256 if value > 127 else value


def is_usb_timeout(exc: usb.core.USBError) -> bool:
    text = str(exc).lower()
    return "timeout" in text or getattr(exc, "errno", None) in (60, 110, 116)


def parse_bd_addr(address: str) -> bytes:
    return bytes(reversed(bytes.fromhex(address.replace(":", "").replace("-", ""))))


def choose_wiimote_pin(pin_mode: str, local_raw: bytes, peer_raw: bytes) -> bytes:
    if pin_mode == "host":
        return local_raw[:6]
    if pin_mode == "host-reversed":
        return bytes(reversed(local_raw[:6]))
    if pin_mode == "peer":
        return peer_raw[:6]
    if pin_mode == "peer-reversed":
        return bytes(reversed(peer_raw[:6]))
    return local_raw[:6]


def scan_enable_label(scan_enable: int) -> str:
    labels = []
    if scan_enable & 0x01:
        labels.append("inquiry-scan")
    if scan_enable & 0x02:
        labels.append("page-scan")
    return ", ".join(labels) or "disabled"
