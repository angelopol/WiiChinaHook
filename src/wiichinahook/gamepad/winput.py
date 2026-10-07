"""Keyboard and mouse injection for the PC mode (Windows SendInput).

Keys go out as scan codes (KEYEVENTF_SCANCODE), which games reading raw input or
DirectInput also see; media keys go out as virtual keys. `open:` targets start with
the shell (os.startfile: programs, files, https:// links).
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes

log = logging.getLogger(__name__)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0008
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_WHEEL = 0x0001, 0x8000, 0x0800
MOUSE_BUTTON_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}
MAPVK_VK_TO_VSC = 0
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class WindowsInput:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("PC mode needs Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        self.user32.SendInput.restype = wintypes.UINT
        self.user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
        self.user32.MapVirtualKeyW.restype = wintypes.UINT

    def _send(self, *inputs):
        array = (INPUT * len(inputs))(*inputs)
        if self.user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)) != len(inputs):
            # Blocked by UIPI when the foreground app runs as administrator.
            log.debug("SendInput blocked (error %d)", ctypes.get_last_error())

    def key(self, vk, extended, down):
        scan = self.user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        flags = KEYEVENTF_SCANCODE if scan else 0
        flags |= (KEYEVENTF_EXTENDEDKEY if extended else 0) | (0 if down else KEYEVENTF_KEYUP)
        self._send(INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0))))

    def media(self, vk):
        down = INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_EXTENDEDKEY, 0, 0)))
        up = INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0, 0)))
        self._send(down, up)

    def button(self, name, down):
        flag = MOUSE_BUTTON_FLAGS[name][0 if down else 1]
        self._send(INPUT(INPUT_MOUSE, _INPUTUNION(mi=MOUSEINPUT(0, 0, 0, flag, 0, 0))))

    def wheel(self, delta):
        self._send(INPUT(INPUT_MOUSE, _INPUTUNION(mi=MOUSEINPUT(0, 0, ctypes.c_uint32(delta).value,
                                                                  MOUSEEVENTF_WHEEL, 0, 0))))

    def move(self, dx, dy):
        self._send(INPUT(INPUT_MOUSE, _INPUTUNION(mi=MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, 0))))

    def move_abs(self, u, v):
        """u, v in 0..1 across the primary screen."""
        x, y = round(max(0.0, min(1.0, u)) * 65535), round(max(0.0, min(1.0, v)) * 65535)
        self._send(INPUT(INPUT_MOUSE, _INPUTUNION(mi=MOUSEINPUT(x, y, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
                                                                  0, 0))))

    def launch(self, target):
        try:
            os.startfile(target)  # programs, documents and URLs through the shell
        except OSError as exc:
            log.warning("Could not open %s: %s", target, exc)


class NullInput:
    """Used where SendInput is unavailable: PC mode then does nothing."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None
