"""UI-independent helpers for the Flet app (unit tested without a window)."""
from __future__ import annotations

from dataclasses import replace

from ..config import AppConfig, ApiConfig, DongleConfig, DsuConfig, MODES, parse_int

# Wii core button bits as reported in WiimoteState.buttons (see dsu_mapping).
BUTTONS = (
    ("up", 0x0800), ("down", 0x0400), ("left", 0x0100), ("right", 0x0200),
    ("a", 0x0008), ("b", 0x0004), ("minus", 0x0010), ("home", 0x0080),
    ("plus", 0x1000), ("one", 0x0002), ("two", 0x0001),
)
BUTTON_LABELS = {"up": "↑", "down": "↓", "left": "←", "right": "→", "a": "A", "b": "B",
                 "minus": "−", "home": "⌂", "plus": "+", "one": "1", "two": "2"}
IR_WIDTH, IR_HEIGHT = 1024, 768
LED_BITS = (0x10, 0x20, 0x40, 0x80)


def pressed_buttons(mask: int) -> set[str]:
    return {name for name, bit in BUTTONS if mask & bit}


def led_mask(enabled: list[bool]) -> int:
    return sum(bit for bit, on in zip(LED_BITS, enabled) if on)


def ir_to_canvas(points, width: float, height: float):
    """Visible IR points scaled to a canvas. The camera X axis is mirrored as
    seen from the player, so flip it to make the dot follow the pointer."""
    result = []
    for point in points or ():
        if point:
            result.append(((1 - point["x"] / (IR_WIDTH - 1)) * width, point["y"] / (IR_HEIGHT - 1) * height))
    return result


def stick_to_canvas(stick, size: float):
    """Nunchuk stick [-1, 1] (up positive) to canvas pixels (down positive)."""
    x, y = (max(-1.0, min(1.0, v)) for v in stick)
    return (x + 1) / 2 * size, (1 - y) / 2 * size


def bar_value(value, limit: float) -> float:
    """Map [-limit, limit] to a 0..1 progress value centred at 0.5."""
    if value is None:
        return 0.5
    return max(0.0, min(1.0, 0.5 + value / (2 * limit)))


def nunchuk_accel(nunchuk):
    """(x, y, z) in g and whether it is approximate. Clone Nunchuks have no valid
    factory calibration, so raw 10-bit values are shown as (raw - 512) / 200 g."""
    if not nunchuk:
        return None, False
    if nunchuk.get("accel_g"):
        return tuple(nunchuk["accel_g"]), False
    raw = nunchuk.get("accel_raw")
    if not raw:
        return None, False
    return tuple((v - 512) / 200.0 for v in raw), True


def fmt(value, digits=2) -> str:
    return "—" if value is None else f"{value:+.{digits}f}"


def form_from_config(config: AppConfig) -> dict:
    return {
        "mode": config.mode,
        "vid": f"0x{config.dongle.vid:04x}",
        "pid": f"0x{config.dongle.pid:04x}",
        "transport": config.dongle.transport or "",
        "dsu_host": config.dsu.host,
        "dsu_port": str(config.dsu.port),
        "dsu_nunchuk_port": str(config.dsu.nunchuk_port),
        "dsu_ir_port": str(config.dsu.ir_port),
        "api_port": str(config.api.port),
        "ir": config.ir,
        "motionplus": config.motionplus,
    }


def config_from_form(base: AppConfig, form: dict) -> AppConfig:
    """Validate the settings form; raises ValueError with a field name."""
    if form["mode"] not in MODES:
        raise ValueError("mode")
    try:
        vid, pid = parse_int(form["vid"]), parse_int(form["pid"])
    except ValueError:
        raise ValueError("vid/pid") from None
    if vid is None or pid is None or not (0 <= vid <= 0xFFFF and 0 <= pid <= 0xFFFF):
        raise ValueError("vid/pid")
    ports = {}
    for key in ("dsu_port", "api_port"):
        try:
            ports[key] = int(form[key])
        except (TypeError, ValueError):
            raise ValueError(key) from None
        if not 1 <= ports[key] <= 65535:
            raise ValueError(key)
    for key, default in (("dsu_nunchuk_port", base.dsu.nunchuk_port), ("dsu_ir_port", base.dsu.ir_port)):
        try:
            ports[key] = int(form.get(key, default) or 0)  # 0 = server off
        except (TypeError, ValueError):
            raise ValueError(key) from None
        if not 0 <= ports[key] <= 65535:
            raise ValueError(key)
    used = [p for p in ports.values() if p]
    if len(set(used)) != len(used):
        raise ValueError("api_port" if ports["dsu_port"] == ports["api_port"] else "dsu_nunchuk_port/dsu_ir_port")
    host = form["dsu_host"].strip()
    if not host:
        raise ValueError("dsu_host")
    return replace(
        base,
        mode=form["mode"],
        dongle=DongleConfig(vid, pid, form["transport"].strip() or None),
        dsu=DsuConfig(host, ports["dsu_port"], ports["dsu_nunchuk_port"], ports["dsu_ir_port"]),
        api=ApiConfig(base.api.host, ports["api_port"]),
        ir=bool(form["ir"]),
        motionplus=bool(form["motionplus"]),
    )
