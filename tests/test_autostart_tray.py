import sys
from pathlib import Path

import pytest

from wiichinahook import autostart
from wiichinahook.gui.i18n import Translator


def test_launch_command_for_source_and_frozen(monkeypatch, tmp_path):
    config = tmp_path / "config.local.json"
    command = autostart.launch_command(config)
    assert "-m wiichinahook.gui --minimized" in command and str(config.resolve()) in command
    assert "pythonw.exe" in command or "python" in command
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\WiiChinaHook\WiiChinaHook.exe")
    assert autostart.launch_command(config).startswith(r'"C:\Apps\WiiChinaHook\WiiChinaHook.exe" --minimized --config')


@pytest.mark.skipif(sys.platform != "win32", reason="registry")
def test_enable_refresh_disable_on_a_scratch_key(monkeypatch, tmp_path):
    import winreg
    scratch = r"Software\WiiChinaHookTest\Run"
    winreg.CreateKey(winreg.HKEY_CURRENT_USER, scratch).Close()
    monkeypatch.setattr(autostart, "RUN_KEY", scratch)       # never touch the real Run key
    try:
        assert not autostart.enabled()
        autostart.refresh(tmp_path / "a.json")               # disabled: stays disabled
        assert not autostart.enabled()
        autostart.enable(tmp_path / "a.json")
        assert "a.json" in autostart.current()
        autostart.refresh(tmp_path / "b.json")               # another config never takes it over
        assert "a.json" in autostart.current()
        moved = autostart.current().replace("python", "moved-python", 1)
        import winreg
        with autostart._open(winreg.KEY_SET_VALUE) as key:   # same config, program moved
            winreg.SetValueEx(key, autostart.VALUE_NAME, 0, winreg.REG_SZ, moved)
        autostart.refresh(tmp_path / "a.json")               # follows the app
        assert autostart.current() == autostart.launch_command(tmp_path / "a.json")
        autostart.disable()
        autostart.disable()                                  # idempotent
        assert not autostart.enabled()
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, scratch)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\WiiChinaHookTest")


def test_tray_menu_opens_switches_mode_and_exits():
    pytest.importorskip("pystray")
    from wiichinahook.gui.tray import ICON, Tray
    calls = []

    class Page:
        def run_task(self, coroutine, *args):
            calls.append((coroutine.__name__, args))

    async def open_window(): ...
    async def set_mode(n): ...
    async def exit_app(): ...
    mode = [2]
    tray = Tray(Page(), Translator("es"), on_open=open_window, on_mode=set_mode, on_exit=exit_app,
                current_mode=lambda: mode[0])
    menu = list(tray.menu())
    assert ICON.is_file() and tray.title() == "WiiChinaHook — Modo 2"
    assert menu[0].text == "Abrir WiiChinaHook" and menu[0].default and menu[-1].text == "Salir"
    modes = list(menu[1].submenu)
    assert [m.checked for m in modes] == [False, True, False, False]
    modes[3](None)
    menu[0](None)
    menu[-1](None)
    assert calls == [("set_mode", (4,)), ("open_window", ()), ("exit_app", ())]
