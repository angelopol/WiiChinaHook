from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re


def parse_int(value):
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    value = str(value).strip()
    return int(value, 16 if value.lower().startswith("0x") or re.search("[a-fA-F]", value) else 10)


def normalize_address(value: str) -> str:
    value = value.upper().replace("-", ":")
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", value):
        raise ValueError(f"Invalid Bluetooth address: {value}")
    return value


@dataclass(frozen=True)
class DongleConfig:
    vid: int = 0x8087
    pid: int = 0x0A2A
    transport: str | None = None

    @property
    def selector(self) -> str:
        return self.transport or f"usb:{self.vid:04x}:{self.pid:04x}"


@dataclass(frozen=True)
class WiimoteConfig:
    address: str
    slot: int = 0
    pin_mode: str = "sync"
    led_mask: int | None = None


@dataclass(frozen=True)
class DsuConfig:
    host: str = "127.0.0.1"
    port: int = 26760


@dataclass(frozen=True)
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 26761


@dataclass(frozen=True)
class AppConfig:
    dongle: DongleConfig = field(default_factory=DongleConfig)
    wiimotes: tuple[WiimoteConfig, ...] = ()
    dsu: DsuConfig = field(default_factory=DsuConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    state_dir: Path = Path(".wiichinahook")
    ir: bool = True
    motionplus: bool = True


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    dongle, dsu, api = (data.get(key, {}) for key in ("dongle", "dsu", "api"))
    entries = data.get("wiimotes")
    if entries is None:
        old = data.get("wiimote")
        entries = [dict(old, slot=dsu.get("slot", 0))] if old else []
    remotes = tuple(WiimoteConfig(normalize_address(e["address"]), int(e.get("slot", i)),
                                 e.get("pin_mode", "sync"), parse_int(e.get("led_mask")))
                    for i, e in enumerate(entries))
    if len(remotes) > 4 or any(r.slot not in range(4) for r in remotes):
        raise ValueError("At most four Wiimotes, with slots 0..3, are supported")
    if len({r.slot for r in remotes}) != len(remotes) or len({r.address for r in remotes}) != len(remotes):
        raise ValueError("Wiimote addresses and slots must be unique")
    if any(r.pin_mode not in ("sync", "temporary") for r in remotes):
        raise ValueError("pin_mode must be sync or temporary")
    if any(r.led_mask is not None and (r.led_mask < 0 or r.led_mask > 240 or r.led_mask & 15) for r in remotes):
        raise ValueError("led_mask must contain only LED bits 0x10..0x80")
    for endpoint in (dsu, api):
        if not 1 <= int(endpoint.get("port", 26760)) <= 65535:
            raise ValueError("Invalid port")
    if api.get("host", "127.0.0.1") not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("The control API must bind to loopback")
    transport = dongle.get("transport")
    if transport == "usb:0" and "vid" in dongle and "pid" in dongle:
        transport = None
    vid, pid = parse_int(dongle.get("vid", 0x8087)), parse_int(dongle.get("pid", 0x0A2A))
    if vid is None or pid is None or not 0 <= vid <= 65535 or not 0 <= pid <= 65535:
        raise ValueError("USB VID/PID must be 0..65535")
    return AppConfig(
        DongleConfig(vid, pid, transport),
        remotes, DsuConfig(dsu.get("host", "127.0.0.1"), int(dsu.get("port", 26760))),
        ApiConfig(api.get("host", "127.0.0.1"), int(api.get("port", 26761))),
        path.parent / data.get("state_dir", ".wiichinahook"),
        bool(data.get("ir", True)), bool(data.get("motionplus", True)),
    )
