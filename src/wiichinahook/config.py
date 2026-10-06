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


MODES = ("dolphinbar", "bluetooth")

# Button combinations for the per-slot quick calibration (WiimoteState.buttons bits).
COMBOS = {
    "minus+plus": 0x0010 | 0x1000,
    "down": 0x0400,          # like the D-pad recenter in Zelda: Skyward Sword
    "one+two": 0x0002 | 0x0001,
    "a+b": 0x0008 | 0x0004,
    "home": 0x0080,
}


@dataclass(frozen=True)
class SlotOptions:
    # Hold `combo` ~0.6 s: gyro bias (if still) + recenter. Off by default because
    # many games recalibrate on their own.
    quick_calibration: bool = False
    combo: str = "minus+plus"
    # Correct the heading drift while the IR camera sees the sensor bar.
    ir_calibration: bool = False


def slot_options_from(data) -> SlotOptions:
    options = SlotOptions(bool(data.get("quick_calibration", False)), data.get("combo", "minus+plus"),
                          bool(data.get("ir_calibration", False)))
    if options.combo not in COMBOS:
        raise ValueError(f"combo must be one of {', '.join(COMBOS)}")
    return options


@dataclass(frozen=True)
class AppConfig:
    # dolphinbar: Mayflash DolphinBar in mode 4 (default).
    # bluetooth: Bumble passthrough on a libusbK adapter (dongle settings).
    mode: str = "dolphinbar"
    dongle: DongleConfig = field(default_factory=DongleConfig)
    wiimotes: tuple[WiimoteConfig, ...] = ()
    dsu: DsuConfig = field(default_factory=DsuConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    state_dir: Path = Path(".wiichinahook")
    ir: bool = True
    motionplus: bool = True
    slots: tuple[SlotOptions, ...] = (SlotOptions(),) * 4


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
    slots_data = data.get("slots", [])
    if not isinstance(slots_data, list) or len(slots_data) > 4:
        raise ValueError("slots must be a list of at most four objects")
    slots = tuple(slot_options_from(slots_data[i] if i < len(slots_data) else {}) for i in range(4))
    mode = data.get("mode", "dolphinbar")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    return AppConfig(
        mode,
        DongleConfig(vid, pid, transport),
        remotes, DsuConfig(dsu.get("host", "127.0.0.1"), int(dsu.get("port", 26760))),
        ApiConfig(api.get("host", "127.0.0.1"), int(api.get("port", 26761))),
        path.parent / data.get("state_dir", ".wiichinahook"),
        bool(data.get("ir", True)), bool(data.get("motionplus", True)), slots,
    )


def config_to_dict(config: AppConfig, base_dir: Path | None = None) -> dict:
    """Inverse of load_config: a JSON-ready dict that loads back to `config`."""
    state_dir = config.state_dir
    if base_dir is not None:
        try:
            state_dir = state_dir.relative_to(base_dir)
        except ValueError:
            pass
    dongle = {"vid": f"0x{config.dongle.vid:04x}", "pid": f"0x{config.dongle.pid:04x}"}
    if config.dongle.transport:
        dongle["transport"] = config.dongle.transport
    remotes = []
    for remote in config.wiimotes:
        entry = {"address": remote.address, "slot": remote.slot, "pin_mode": remote.pin_mode}
        if remote.led_mask is not None:
            entry["led_mask"] = f"0x{remote.led_mask:02x}"
        remotes.append(entry)
    return {
        "mode": config.mode,
        "dongle": dongle,
        "wiimotes": remotes,
        "dsu": {"host": config.dsu.host, "port": config.dsu.port},
        "api": {"host": config.api.host, "port": config.api.port},
        "state_dir": state_dir.as_posix(),
        "ir": config.ir,
        "motionplus": config.motionplus,
        "slots": [{"quick_calibration": o.quick_calibration, "combo": o.combo, "ir_calibration": o.ir_calibration}
                  for o in config.slots],
    }


def save_config(config: AppConfig, path: str | Path) -> None:
    """Write `config`, keeping keys this version does not know, then validate it."""
    path = Path(path)
    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        data.pop("wiimote", None)  # legacy single-remote key is superseded by "wiimotes"
    data.update(config_to_dict(config, path.parent))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    load_config(temporary)  # refuse to replace a good file with an invalid one
    temporary.replace(path)
