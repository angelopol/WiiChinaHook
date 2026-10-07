"""Editor of a PC mode (mouse and keyboard) for the gamepad tab."""
from __future__ import annotations

import ctypes
import logging
import sys

import flet as ft

from ..gamepad.pc import (GAME_ACTION_TYPES, GAME_MOUSE_SOURCES, KEYS, MOUSE_ACTIONS, MOUSE_CLAIMS,
                          MOUSE_SOURCES, PC_SOURCES, PC_TEMPLATE, STICK_DIRECTIONS,
                          SYSTEM_ACTIONS)
from ..gamepad.mapping import AXIS_GESTURES
from .widgets import columns, hint, number, section

KINDS = ("none", "keys", "mouse", "system", "open", "toggle")
WIIMOTE = ("wm_a", "wm_b", "wm_1", "wm_2", "wm_minus", "wm_plus", "wm_home",
           "wm_up", "wm_down", "wm_left", "wm_right")
NUNCHUK = ("nc_c", "nc_z", *STICK_DIRECTIONS)
SHORTCUT_ROWS = 8
MOUSE_FIELDS = ("gyro_speed", "gyro_deadzone", "freeze_dps", "stick_speed", "stick_deadzone", "ir_range",
                "ir_smoothing")


# Flutter key names as Flet reports them ("Arrow Down", "Numpad Add", "Control Left",
# "Key A"...), normalized (lower case, no spaces/underscores) -> our key names.
FLET_KEYS = {
    "enter": "enter", "numpadenter": "num_enter", "escape": "esc", "esc": "esc", "tab": "tab",
    "space": "space", " ": "space", "backspace": "backspace", "delete": "delete", "insert": "insert",
    "home": "home", "end": "end", "pageup": "pageup", "pagedown": "pagedown",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "controlleft": "ctrl", "control": "ctrl", "controlright": "rctrl",
    "shiftleft": "shift", "shift": "shift", "shiftright": "rshift",
    "altleft": "alt", "alt": "alt", "altright": "ralt", "altgraph": "ralt",
    "metaleft": "win", "meta": "win", "metaright": "rwin", "superleft": "win", "superright": "rwin",
    "contextmenu": "menu", "capslock": "capslock", "numlock": "numlock", "scrolllock": "scrolllock",
    "printscreen": "printscreen", "pause": "pause",
    "numpadadd": "num_add", "numpadsubtract": "num_subtract", "numpadmultiply": "num_multiply",
    "numpaddivide": "num_divide", "numpaddecimal": "num_decimal",
    "comma": ",", "period": ".", "minus": "-", "equal": "=", "slash": "/", "backslash": "\\",
    "semicolon": ";", "quote": "'", "quotesingle": "'", "backquote": "`", "bracketleft": "[",
    "bracketright": "]",
}
MODIFIER_FLAGS = (("ctrl", ("ctrl", "rctrl")), ("shift", ("shift", "rshift")), ("alt", ("alt", "ralt")),
                  ("meta", ("win", "rwin")))
MODIFIER_ORDER = ("ctrl", "rctrl", "shift", "rshift", "alt", "ralt", "win", "rwin")
# Left/right virtual keys of each modifier, read straight from Windows.
MODIFIER_VKS = {"ctrl": (0xA2, 0xA3), "shift": (0xA0, 0xA1), "alt": (0xA4, 0xA5), "win": (0x5B, 0x5C)}
log = logging.getLogger(__name__)


def held_modifiers():
    """Modifiers physically held now, asked to Windows (GetAsyncKeyState), or None
    elsewhere. Flutter does not always report Alt: Ctrl + Alt is AltGr on many
    layouts (e.g. Spanish), and then neither the Alt key nor its flag arrives."""
    if sys.platform != "win32":
        return None
    try:
        state = ctypes.windll.user32.GetAsyncKeyState
        return {name for name, vks in MODIFIER_VKS.items() if any(state(vk) & 0x8000 for vk in vks)}
    except (AttributeError, OSError):
        return None


def flet_key(name):
    """Our key name for a Flet keyboard event's key, or None if not mappable."""
    if not name:
        return None
    if len(name) == 1:                                   # printable: "A", "7", ","
        char = name.lower()
        return char if char in KEYS else FLET_KEYS.get(char)
    n = name.strip().lower().replace(" ", "").replace("_", "")
    for prefix in ("key", "digit"):                      # "Key A", "Digit 7"
        if n.startswith(prefix) and len(n) == len(prefix) + 1:
            n = n[len(prefix):]
    if n.startswith("numpad") and n[6:].isdigit():
        return f"num{n[6:]}"
    if n in KEYS and n not in ("-", "="):
        return n                                          # letters, digits, f1..f24
    return FLET_KEYS.get(n)


_recording = [None]   # the KeyCapture whose field has the focus (one at a time)


def dispatch_key(e):
    """The page's keyboard handler (set once by the app): feeds the recording field."""
    capture = _recording[0]
    if capture is not None:
        capture.on_key(e)


class KeyCapture:
    """Records key combinations into the focused "Keys" field: the first key replaces
    the value, the next ones add to it, Enter accepts (on its own it is the Enter key:
    it cannot be part of a combination); after accepting, a key starts anew."""

    def __init__(self):
        self.target = None
        self.combo, self.accepted = [], True

    def start(self, row, page=None):
        self.target, self.combo, self.accepted = row, [], True
        _recording[0] = self

    def stop(self, row):
        if self.target is row:
            self.target = None
            if _recording[0] is self:
                _recording[0] = None

    def on_key(self, e):
        if self.target is None:
            return
        name = flet_key(e.key)
        if name is None:
            log.info("Key not recognised by the recorder: %r (type it with the pencil button)", e.key)
            return
        if self.accepted:
            self.combo, self.accepted = [], False
        if name in ("enter", "num_enter") and self.combo:
            self.accepted = True                          # accept the combination
        elif name in ("enter", "num_enter"):
            self.combo, self.accepted = [name], True     # Enter alone is a key of its own
        else:
            if name not in self.combo:
                self.combo.append(name)
            held = held_modifiers()
            if held is None:                              # not Windows: the event's flags
                held = {names[0] for flag, names in MODIFIER_FLAGS if getattr(e, flag, False)}
            for flag, names in MODIFIER_FLAGS:
                if names[0] in held and not set(names) & set(self.combo):
                    self.combo.append(names[0])
            # Modifiers first (ctrl, shift, alt, win), then the other keys in pressed order.
            mods = sorted((k for k in self.combo if k in MODIFIER_ORDER), key=MODIFIER_ORDER.index)
            self.combo = mods + [k for k in self.combo if k not in MODIFIER_ORDER]
        self.target.set_keys("+".join(self.combo))


class ActionRow:
    """One input: action type + its value (keys recorded by pressing them, text for
    open/toggle, a list for mouse/system). Disabled while the input drives the mouse."""

    def __init__(self, source, label, action, t, kinds=KINDS, capture=None, label_width=120):
        self.source, self.t, self.capture = source, t, capture
        kind, value = "none", ""
        if action:
            prefix, _, rest = action.partition(":")
            kind, value = (prefix, rest) if prefix in KINDS else ("keys", action)
        self.kind = ft.Dropdown(value=kind, width=130, dense=True, on_select=self.on_kind,
                                options=[ft.DropdownOption(k, t(f"pc_kind_{k}")) for k in kinds])
        self.text = ft.TextField(value=value if kind in ("keys", "open", "toggle") else "", dense=True,
                                 expand=True, hint_text=t("pc_hint_keys"), on_focus=self.on_focus,
                                 on_blur=self.on_blur)
        self.manual = False                               # "edit as text" for keys Windows keeps
        self.clear = ft.IconButton(ft.Icons.BACKSPACE_OUTLINED, tooltip=t("pc_keys_clear"), on_click=self.on_clear,
                                   icon_size=18)
        self.edit = ft.IconButton(ft.Icons.EDIT_OUTLINED, tooltip=t("pc_keys_edit"), on_click=self.on_edit,
                                  icon_size=18)
        self.choice = ft.Dropdown(dense=True, expand=True, value=value if kind in ("mouse", "system") else None)
        self.claimed = hint(t("pc_claimed"))
        self.row = ft.Row([ft.Text(label, width=label_width, weight=ft.FontWeight.W_500), self.kind, self.text,
                           self.clear, self.edit, self.choice, self.claimed], spacing=6,
                          vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.show(kind)
        self.set_claimed(False)

    def recording(self):
        return self.kind.value == "keys" and not self.manual and self.capture is not None

    def show(self, kind):
        self.text.visible = kind in ("keys", "open", "toggle")
        self.clear.visible = self.edit.visible = kind == "keys"
        self.text.read_only = self.recording()
        hint_key = "pc_hint_record" if self.recording() else f"pc_hint_{kind}"
        self.text.hint_text = self.t(hint_key) if self.text.visible else None
        self.choice.visible = kind in ("mouse", "system")
        if self.choice.visible:
            names = MOUSE_ACTIONS if kind == "mouse" else SYSTEM_ACTIONS
            self.choice.options = [ft.DropdownOption(n, self.t(f"pc_{kind}_{n}")) for n in names]
            if self.choice.value not in names:
                self.choice.value = names[0]

    def on_kind(self, e):
        self.show(e.control.value)
        e.control.page.update()

    def on_focus(self, e):
        if self.recording():
            self.capture.start(self, e.control.page)

    def on_blur(self, e):
        if self.capture is not None:
            self.capture.stop(self)

    def set_keys(self, text):
        self.text.value = text
        if self.text.page is not None:
            self.text.update()

    def on_clear(self, e):
        self.set_keys("")
        if self.capture is not None and self.capture.target is self:
            self.capture.combo, self.capture.accepted = [], True

    def on_edit(self, e):
        """Type the keys instead (Win, Print Screen... are kept by Windows)."""
        self.manual = not self.manual
        if self.capture is not None:
            self.capture.stop(self)
        self.show(self.kind.value)
        e.control.page.update()

    def set_claimed(self, claimed):
        self.kind.disabled = claimed
        self.claimed.visible = claimed
        if claimed:
            self.text.visible = self.choice.visible = self.clear.visible = self.edit.visible = False
        else:
            self.show(self.kind.value)

    def action(self):
        kind = self.kind.value
        if self.kind.disabled or kind in (None, "none"):
            return None
        if kind in ("mouse", "system"):
            return f"{kind}:{self.choice.value}"
        value = (self.text.value or "").strip()
        return f"{kind}:{value}" if value else None


class ShortcutRow:
    """A super shortcut: up to three inputs held together -> one action."""

    def __init__(self, shortcut, t, kinds, label, capture=None):
        inputs = list(shortcut["inputs"]) if shortcut else []
        options = [ft.DropdownOption("none", t("gp_none"))] + [ft.DropdownOption(s, label(s)) for s in PC_SOURCES]
        self.inputs = [ft.Dropdown(value=inputs[i] if i < len(inputs) else "none", dense=True, expand=True,
                                   label=None if i == 0 else "+", options=options) for i in range(3)]
        self.action_row = ActionRow("shortcut", "→", shortcut["action"] if shortcut else None, t, kinds,
                                    capture=capture, label_width=24)
        self.row = ft.Column([ft.Row(self.inputs, spacing=6), self.action_row.row], spacing=4, tight=True)

    def value(self):
        """{"inputs", "action"}, or None for an empty row (validation reports half-filled ones)."""
        inputs = [d.value for d in self.inputs if d.value not in (None, "", "none")]
        action = self.action_row.action()
        if not inputs and not action:
            return None
        return {"inputs": inputs, "action": action}


class PcEditor:
    """PC mode editor; `game=True` is the PC Game variant (game actions, relative mouse)."""

    def __init__(self, t, source_label, game=False):
        self.t, self.source_label, self.game = t, source_label, game
        self.kinds = ("none", *GAME_ACTION_TYPES) if game else KINDS
        self.capture = KeyCapture()
        self.sources = GAME_MOUSE_SOURCES if game else MOUSE_SOURCES

    def label(self, source):
        if source in STICK_DIRECTIONS:
            return self.t(f"pc_src_{source}")
        return self.source_label(source, self.t)

    def build(self, template, header):
        t = self.t
        mouse = template["mouse"]
        self.source = ft.Dropdown(label=t("pc_mouse_source"), value=mouse["source"] or "none", dense=True,
                                  expand=True, on_select=self.on_source,
                                  options=[ft.DropdownOption(s, t(f"pc_mouse_src_{s}"))
                                           for s in ("none", *self.sources)])
        self.numbers = {key: number(t(f"pc_{key}"), mouse[key]) for key in MOUSE_FIELDS}
        self.ab_action = ft.Dropdown(label=t("pc_ab_action"), value=mouse["ab_action"] or "off", dense=True,
                                     expand=True, tooltip=t("pc_ab_hint"),
                                     options=[ft.DropdownOption(k, t(f"pc_ab_{k}")) for k in ("center", "regrip",
                                                                                              "off")])
        self.freeze = ft.Switch(label=t("pc_freeze_on_shake"), value=mouse["freeze_on_shake"],
                                tooltip=t("pc_freeze_hint"))
        self.recenter = ft.Switch(label=t("pc_recenter_on_calibration"), value=mouse["recenter_on_calibration"],
                                  tooltip=t("pc_recenter_hint"), visible=not self.game)
        self.shake = number(t("pc_shake_g"), template["shake_g"], suffix="g")
        self.rows = {s: ActionRow(s, self.label(s), template["buttons"].get(s), t, self.kinds, self.capture)
                     for s in (*WIIMOTE, *NUNCHUK, *AXIS_GESTURES)}
        shortcuts = template.get("shortcuts", [])
        self.shortcuts_enabled = ft.Switch(label=t("pc_shortcuts_enabled"), value=template.get("shortcuts_enabled", False))
        self.shortcut_window = number(t("pc_shortcut_window_ms"), template.get("shortcut_window_ms", 50), width=220)
        self.shortcut_rows = [ShortcutRow(shortcuts[i] if i < len(shortcuts) else None, t, self.kinds, self.label,
                                          self.capture)
                              for i in range(max(SHORTCUT_ROWS, len(shortcuts)))]
        self.apply_claims()
        n = self.numbers
        left = [
            section(t("pc_mouse"), ft.Icons.MOUSE, [
                ft.Row([self.source]),
                ft.Row([n["gyro_speed"], n["gyro_deadzone"]]),
                ft.Row([self.freeze, n["freeze_dps"]], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([self.ab_action]),
                self.recenter,
                ft.Row([n["stick_speed"], n["stick_deadzone"]]),
                ft.Row([n["ir_range"], n["ir_smoothing"]], visible=not self.game)],
                subtitle=t("pc_game_mouse_hint" if self.game else "pc_mouse_hint")),
            section(t("pc_shortcuts"), ft.Icons.KEYBOARD_COMMAND_KEY, [
                ft.Row([self.shortcuts_enabled, self.shortcut_window], wrap=True,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                *[row.row for row in self.shortcut_rows]], subtitle=t("pc_shortcuts_hint")),
            section(t("pc_help_title"), ft.Icons.HELP_OUTLINE, [
                ft.Markdown(t("pc_help"), selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)]),
        ]
        right = [
            section(t("pc_cat_wiimote"), ft.Icons.GAMEPAD, [self.rows[s].row for s in WIIMOTE],
                    subtitle=t("pc_game_modifier_hint" if self.game else "pc_modifier_hint")),
            section(t("pc_cat_nunchuk"), ft.Icons.OPEN_WITH, [self.rows[s].row for s in NUNCHUK]),
            section(t("pc_cat_shakes"), ft.Icons.VIBRATION,
                    [ft.Row([self.shake]), *[self.rows[s].row for s in AXIS_GESTURES]]),
        ]
        return [header, columns(left, right)]

    def apply_claims(self):
        claimed = set(MOUSE_CLAIMS.get(self.source.value, ()))
        for source, row in self.rows.items():
            row.set_claimed(source in claimed)

    def on_source(self, e):
        self.apply_claims()
        e.control.page.update()

    def collect(self, template):
        result = dict(template)
        source = None if self.source.value in (None, "none") else self.source.value
        ab = None if self.ab_action.value in (None, "off") else self.ab_action.value
        mouse = dict(template["mouse"], source=source, freeze_on_shake=bool(self.freeze.value), ab_action=ab,
                     recenter_on_calibration=bool(self.recenter.value) and not self.game)
        for key, field in self.numbers.items():
            try:
                mouse[key] = float(field.value)
            except ValueError:
                raise ValueError(f"mouse {key}") from None
        result["mouse"] = mouse
        try:
            result["shake_g"] = float(self.shake.value)
        except ValueError:
            raise ValueError("shake_g") from None
        result["buttons"] = {source: row.action() for source, row in self.rows.items()}
        result["shortcuts_enabled"] = bool(self.shortcuts_enabled.value)
        try:
            result["shortcut_window_ms"] = int(float(self.shortcut_window.value))
        except ValueError:
            raise ValueError("shortcut_window_ms") from None
        result["shortcuts"] = [v for v in (row.value() for row in self.shortcut_rows) if v]
        return result


DEFAULT = PC_TEMPLATE
