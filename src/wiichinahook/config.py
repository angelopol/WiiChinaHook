from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re

from .gamepad.mapping import validate_config as validate_gamepad
from .speaker import validate_speaker


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
    nunchuk_port: int = 26762   # Nunchuk motion server; 0 = not opened
    ir_port: int = 26763        # IR pointer server; 0 = not opened


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
    "minus+home+plus": 0x0010 | 0x0080 | 0x1000,
}
# Combination names saved by earlier versions -> current name.
COMBO_ALIASES = {"one+home+plus": "minus+home+plus"}   # was a misreading of "− + Home + +"


@dataclass(frozen=True)
class SlotOptions:
    # Hold `combo` ~0.6 s: gyro bias (if still) + recenter. Off by default because
    # many games recalibrate on their own.
    quick_calibration: bool = False
    combo: str = "minus+plus"
    # Correct the heading drift while the IR camera sees the sensor bar.
    ir_calibration: bool = False
    # How long the combination must be held to recalibrate.
    combo_hold_ms: int = 600
    # How long each of its buttons waits for the others before acting on its own.
    combo_window_ms: int = 100
    # Switch-bounce filter (cheap clones bounce, notably on A): after a button changes,
    # further changes of that button within this many ms are ignored. 0 = off.
    debounce_ms: int = 20


def slot_options_from(data) -> SlotOptions:
    hold = data.get("combo_hold_ms", 600)
    if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not 200 <= hold <= 3000:
        raise ValueError("combo_hold_ms must be 200..3000")
    window = data.get("combo_window_ms", 100)
    if isinstance(window, bool) or not isinstance(window, (int, float)) or not 0 <= window <= 1000:
        raise ValueError("combo_window_ms must be 0..1000")
    debounce = data.get("debounce_ms", 20)
    if isinstance(debounce, bool) or not isinstance(debounce, (int, float)) or not 0 <= debounce <= 100:
        raise ValueError("debounce_ms must be 0..100")
    combo = data.get("combo", "minus+plus")
    options = SlotOptions(bool(data.get("quick_calibration", False)), COMBO_ALIASES.get(combo, combo),
                          bool(data.get("ir_calibration", False)), int(hold), int(window), int(debounce))
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
    # Virtual Xbox modes (gamepad.mapping): modifier, active mode, four templates.
    gamepad: dict = field(default_factory=lambda: validate_gamepad(None))
    # Optional speaker sounds (speaker.py); off by default.
    speaker: dict = field(default_factory=lambda: validate_speaker(None))


def dsu_config(data: dict) -> DsuConfig:
    ports = [int(data.get(k, d)) for k, d in (("port", 26760), ("nunchuk_port", 26762), ("ir_port", 26763))]
    if not 1 <= ports[0] <= 65535 or not all(0 <= p <= 65535 for p in ports[1:]):
        raise ValueError("Invalid DSU port")
    used = [p for p in ports if p]
    if len(set(used)) != len(used):
        raise ValueError("The DSU servers need different ports")
    return DsuConfig(data.get("host", "127.0.0.1"), *ports)


def default_config_path() -> Path:
    """Where settings and remote data live unless --config says otherwise:
    %APPDATA%/WiiChinaHook, shared by the release executable and source runs (the
    executable may be started by Windows from any folder)."""
    return Path(os.environ.get("APPDATA", Path.home())) / "WiiChinaHook" / "config.local.json"


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
        remotes, dsu_config(dsu),
        ApiConfig(api.get("host", "127.0.0.1"), int(api.get("port", 26761))),
        path.parent / data.get("state_dir", ".wiichinahook"),
        bool(data.get("ir", True)), bool(data.get("motionplus", True)), slots,
        validate_gamepad(data.get("gamepad")),
        validate_speaker(data.get("speaker")),
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
        "dsu": {"host": config.dsu.host, "port": config.dsu.port, "nunchuk_port": config.dsu.nunchuk_port,
                "ir_port": config.dsu.ir_port},
        "api": {"host": config.api.host, "port": config.api.port},
        "state_dir": state_dir.as_posix(),
        "ir": config.ir,
        "motionplus": config.motionplus,
        "slots": [{"quick_calibration": o.quick_calibration, "combo": o.combo, "ir_calibration": o.ir_calibration,
                   "combo_hold_ms": o.combo_hold_ms, "combo_window_ms": o.combo_window_ms,
                   "debounce_ms": o.debounce_ms}
                  for o in config.slots],
        "gamepad": config.gamepad,
        "speaker": config.speaker,
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
