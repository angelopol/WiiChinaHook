"""Start the GUI with Windows: a per-user `Run` registry value (no admin rights)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WiiChinaHook"


def launch_command(config_path: Path) -> str:
    """Command line that opens the GUI minimized to the tray with this config."""
    config = f'--config "{Path(config_path).resolve()}"'
    if getattr(sys, "frozen", False):  # release executable
        return f'"{sys.executable}" --minimized {config}'
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")  # no console window
    return f'"{pythonw if pythonw.exists() else python}" -m wiichinahook.gui --minimized {config}'


def _open(access):
    import winreg
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def current() -> str | None:
    """The registered command, or None (also on non-Windows systems)."""
    try:
        import winreg
        with _open(winreg.KEY_READ) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0]
    except (ImportError, OSError):
        return None


def enabled() -> bool:
    return current() is not None


def enable(config_path: Path) -> str:
    import winreg
    command = launch_command(config_path)
    with _open(winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    return command


def disable() -> None:
    import winreg
    try:
        with _open(winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


def configured_path(command: str | None) -> Path | None:
    """The --config path of a registered command."""
    match = re.search(r'--config "([^"]+)"', command or "")
    return Path(match.group(1)) if match else None


def refresh(config_path: Path) -> None:
    """Follow the app if it was moved: re-point an existing entry at this executable,
    but only when it starts this same config. Another instance (e.g. a copy with its
    own config, or a test run) must never take over the user's startup entry."""
    command = current()
    registered = configured_path(command)
    if registered is None or command == launch_command(config_path):
        return
    try:
        same = registered.resolve() == Path(config_path).resolve()
    except OSError:
        same = False
    if same:
        enable(config_path)
