"""Start the GUI with Windows: a per-user `Run` registry value (no admin rights)."""
from __future__ import annotations

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


def refresh(config_path: Path) -> None:
    """Re-point an existing entry at this executable/config (e.g. after moving the app)."""
    if enabled() and current() != launch_command(config_path):
        enable(config_path)
