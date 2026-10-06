from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import replace

from .app import run_app
from .config import AppConfig, DsuConfig, DongleConfig, WiimoteConfig, load_config, parse_int, normalize_address
from .raw_hci import (
    describe_usb_device,
    listen_raw_hci,
    pair_window_raw_hci,
    scan_raw_hci,
    show_raw_hci_info,
)
from .scanner import print_scan_summary, scan_classic_devices
from .usb_probe import find_device, format_device, list_devices


def main() -> None:
    parser = argparse.ArgumentParser(prog="wiichinahook")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("usb-list", help="list USB devices visible through PyUSB")

    usb_find = subparsers.add_parser("usb-find", help="find a specific USB device")
    usb_find.add_argument("--vid", required=True, help="vendor id, e.g. 0x0a12")
    usb_find.add_argument("--pid", required=True, help="product id, e.g. 0x0001")

    hook = subparsers.add_parser("hook", help="connect Wiimote and serve DSU")
    hook.add_argument("--config", default="config.local.json", help="path to JSON config")
    hook.add_argument("--mode", choices=("dolphinbar", "bluetooth"),
                      help="dolphinbar (default): Mayflash DolphinBar in mode 4; "
                           "bluetooth: Bumble passthrough on the libusbK adapter")
    hook.add_argument("--wiimote", help="Wiimote Bluetooth MAC address (bluetooth mode)")
    hook.add_argument("--transport", help="Explicit Bumble selector, e.g. usb:8087:0a2a")
    hook.add_argument("--duration", type=float, help="Stop after this many seconds (diagnostics)")
    hook.add_argument("--verbose", action="store_true")
    hook.add_argument("--dsu-host", help="DSU bind host, default 127.0.0.1")
    hook.add_argument("--dsu-port", type=int, help="DSU bind port, default 26760")
    hook.add_argument("--slot", type=int, help="DSU slot, default 0")
    hook.add_argument("--dsu-mac", help="MAC reported to DSU clients")

    gui = subparsers.add_parser("gui", help="open the graphical app (needs the [gui] extra)")
    gui.add_argument("--config", default="config.local.json", help="path to JSON config")

    scan = subparsers.add_parser("scan-wiimotes", help="scan Bluetooth Classic devices with Bumble")
    scan.add_argument("--transport", default="usb:8087:0a2a", help="Bumble USB selector")
    scan.add_argument("--seconds", type=float, default=12.0, help="scan duration")
    scan.add_argument(
        "--names",
        action="store_true",
        help="try HCI remote-name requests after inquiry; slower but useful",
    )

    raw_scan = subparsers.add_parser(
        "usb-hci-scan",
        help="scan Bluetooth devices by sending raw HCI commands through PyUSB/libusb",
    )
    raw_scan.add_argument("--vid", required=True, help="USB vendor id, e.g. 0x0a12")
    raw_scan.add_argument("--pid", required=True, help="USB product id, e.g. 0x0001")
    raw_scan.add_argument("--seconds", type=float, default=12.0, help="scan duration")
    raw_scan.add_argument("--reset", action="store_true", help="send HCI reset before scanning")
    raw_scan.add_argument("--describe", action="store_true", help="print USB interfaces/endpoints before scanning")
    raw_scan.add_argument(
        "--inquiry-mode",
        type=int,
        choices=[0, 1, 2],
        default=2,
        help="0=standard, 1=RSSI, 2=extended inquiry result",
    )
    raw_scan.add_argument("--verbose", action="store_true", help="print non-result HCI events")

    raw_listen = subparsers.add_parser(
        "usb-hci-listen",
        help="make the USB HCI adapter discoverable/connectable and print incoming events",
    )
    raw_listen.add_argument("--vid", required=True, help="USB vendor id, e.g. 0x0a12")
    raw_listen.add_argument("--pid", required=True, help="USB product id, e.g. 0x0001")
    raw_listen.add_argument("--seconds", type=float, default=30.0, help="listen duration")
    raw_listen.add_argument("--reset", action="store_true", help="send HCI reset before listening")
    raw_listen.add_argument("--name", default="Nintendo RVL-001", help="local Bluetooth name to advertise")
    raw_listen.add_argument(
        "--class",
        dest="class_of_device",
        default="0x000500",
        help="local class of device, default 0x000500",
    )
    raw_listen.add_argument("--verbose", action="store_true", help="print all HCI events")

    raw_info = subparsers.add_parser(
        "usb-hci-info",
        help="print raw HCI adapter information through PyUSB/libusb",
    )
    raw_info.add_argument("--vid", required=True, help="USB vendor id, e.g. 0x0a12")
    raw_info.add_argument("--pid", required=True, help="USB product id, e.g. 0x0001")
    raw_info.add_argument("--reset", action="store_true", help="send HCI reset before reading info")

    raw_pair = subparsers.add_parser(
        "usb-hci-pair-window",
        help="open a Wii-like raw HCI pairing window and respond to legacy PIN requests",
    )
    raw_pair.add_argument("--vid", required=True, help="USB vendor id, e.g. 0x0a12")
    raw_pair.add_argument("--pid", required=True, help="USB product id, e.g. 0x0001")
    raw_pair.add_argument("--seconds", type=float, default=45.0, help="listen duration")
    raw_pair.add_argument("--reset", action="store_true", help="send HCI reset before listening")
    raw_pair.add_argument("--name", default="Nintendo RVL-001", help="local Bluetooth name to advertise")
    raw_pair.add_argument(
        "--class",
        dest="class_of_device",
        default="0x000500",
        help="local class of device, default 0x000500",
    )
    raw_pair.add_argument(
        "--pin-mode",
        choices=["host", "host-reversed", "peer", "peer-reversed"],
        default="host",
        help="legacy Wiimote PIN strategy; default uses local BD_ADDR bytes",
    )

    for name in ("pair", "devices", "forget", "monitor", "calibrate", "led", "rumble"):
        client = subparsers.add_parser(name, help=f"{name} through the running hook API")
        client.add_argument("--url", default="ws://127.0.0.1:26761")
        if name in ("forget", "calibrate", "led", "rumble"):
            client.add_argument("--slot", type=int, choices=range(4), default=0)
        if name == "pair":
            client.add_argument("--seconds", type=float, default=20)
            client.add_argument("--mode", choices=("sync", "temporary"), default="sync")
            client.add_argument("--address")
        if name == "led":
            client.add_argument("--mask", type=parse_int, required=True)
        if name == "rumble":
            client.add_argument("--duration-ms", type=int, default=500)
        if name == "calibrate":
            client.add_argument("--axis", choices=("pitch", "roll", "yaw"),
                                help="MotionPlus scale/sign calibration of one axis instead of the bias")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "gui":
        try:
            from .gui.app import run as run_gui
        except ImportError as exc:
            raise SystemExit(f"GUI unavailable ({exc}). Install it with: pip install -e .[gui]") from exc
        run_gui(args.config)
        return
    if args.command in ("pair", "devices", "forget", "monitor", "calibrate", "led", "rumble"):
        asyncio.run(command_api(args))
        return
    if args.command == "usb-list":
        command_usb_list()
    elif args.command == "usb-find":
        command_usb_find(args.vid, args.pid)
    elif args.command == "hook":
        asyncio.run(command_hook(args))
    elif args.command == "scan-wiimotes":
        asyncio.run(command_scan_wiimotes(args))
    elif args.command == "usb-hci-scan":
        command_usb_hci_scan(args)
    elif args.command == "usb-hci-listen":
        command_usb_hci_listen(args)
    elif args.command == "usb-hci-info":
        command_usb_hci_info(args)
    elif args.command == "usb-hci-pair-window":
        command_usb_hci_pair_window(args)


def command_usb_list() -> None:
    for device in list_devices():
        print(format_device(device))


def command_usb_find(vid: str, pid: str) -> None:
    device = find_device(parse_int(vid) or 0, parse_int(pid) or 0)
    if device is None:
        print("not found")
        raise SystemExit(1)
    print(format_device(device))


async def command_hook(args: argparse.Namespace) -> None:
    import faulthandler
    config = config_from_args(args)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    log_file = (config.state_dir / "hook.log").open("a", encoding="utf-8")
    handler = logging.StreamHandler(log_file)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)
    if args.duration is not None:
        # A wedged USB transport once blocked the event loop past --duration.
        # Dump every thread's stack to hook.log and exit instead of lingering.
        faulthandler.dump_traceback_later(args.duration + 20, exit=True, file=log_file)
    try:
        await run_app(config, args.duration)
    finally:
        faulthandler.cancel_dump_traceback_later()
        logging.getLogger().removeHandler(handler)
        log_file.close()


async def command_api(args):
    from websockets.asyncio.client import connect
    values = {k: v for k, v in vars(args).items() if k not in ("command", "url") and v is not None}
    command = "subscribe" if args.command == "monitor" else args.command
    if command == "calibrate" and "axis" in values:
        command = "calibrate_axis"
    request = {"v": 1, "id": 1, "command": command, "args": values}
    try:
        async with connect(args.url, open_timeout=5, max_size=262144) as websocket:
            await websocket.send(json.dumps(request))
            while True:
                reply = json.loads(await asyncio.wait_for(websocket.recv(), 30))
                print(json.dumps(reply, ensure_ascii=False, indent=2), flush=True)
                if reply.get("ok") is False:
                    raise SystemExit(1)
                if args.command != "monitor":
                    break
                # Monitoring can remain idle indefinitely when no controller is connected.
                async for message in websocket:
                    print(message, flush=True)
    except OSError as exc:
        raise SystemExit(f"API unavailable: {exc}. Start 'hook' in another terminal first.") from exc


async def command_scan_wiimotes(args: argparse.Namespace) -> None:
    results = await scan_classic_devices(
        transport=args.transport,
        duration=args.seconds,
        request_names=args.names,
    )
    print_scan_summary(results)


def command_usb_hci_scan(args: argparse.Namespace) -> None:
    vid = parse_int(args.vid) or 0
    pid = parse_int(args.pid) or 0
    if args.describe:
        for line in describe_usb_device(vid, pid):
            print(line)
        print("")

    results = scan_raw_hci(
        vid=vid,
        pid=pid,
        seconds=args.seconds,
        reset=args.reset,
        inquiry_mode=args.inquiry_mode,
        verbose=args.verbose,
    )
    if not results:
        print("No devices found through raw HCI inquiry.")
        return
    print("")
    print("Raw HCI scan results:")
    for result in results:
        rssi = result.rssi if result.rssi is not None else "-"
        name = result.name or "-"
        print(f"{result.address}  class=0x{result.class_of_device:06x}  rssi={rssi}  name={name}")


def command_usb_hci_listen(args: argparse.Namespace) -> None:
    listen_raw_hci(
        vid=parse_int(args.vid) or 0,
        pid=parse_int(args.pid) or 0,
        seconds=args.seconds,
        reset=args.reset,
        local_name=args.name,
        class_of_device=parse_int(args.class_of_device) or 0,
        verbose=args.verbose,
    )


def command_usb_hci_info(args: argparse.Namespace) -> None:
    show_raw_hci_info(
        vid=parse_int(args.vid) or 0,
        pid=parse_int(args.pid) or 0,
        reset=args.reset,
    )


def command_usb_hci_pair_window(args: argparse.Namespace) -> None:
    pair_window_raw_hci(
        vid=parse_int(args.vid) or 0,
        pid=parse_int(args.pid) or 0,
        seconds=args.seconds,
        reset=args.reset,
        local_name=args.name,
        class_of_device=parse_int(args.class_of_device) or 0,
        pin_mode=args.pin_mode,
    )


def config_from_args(args: argparse.Namespace) -> AppConfig:
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        if args.config != "config.local.json":
            raise SystemExit(f"Config not found: {args.config}")
        config = AppConfig()
    if args.mode:
        config = replace(config, mode=args.mode)
    if args.wiimote and config.mode != "bluetooth":
        raise SystemExit("--wiimote requires --mode bluetooth; DolphinBar remotes pair on the bar")
    if args.wiimote:
        remote = WiimoteConfig(normalize_address(args.wiimote), args.slot if args.slot is not None else 0)
        config = replace(config, wiimotes=(remote,))
    elif args.slot is not None:
        raise SystemExit("--slot requires --wiimote; use configuration for multiple controllers")
    if args.dsu_mac:
        raise SystemExit("DSU now reports each Wiimote's real MAC; remove --dsu-mac")
    return replace(config,
        dongle=replace(config.dongle, transport=args.transport or config.dongle.transport),
        dsu=DsuConfig(args.dsu_host or config.dsu.host, args.dsu_port or config.dsu.port))
