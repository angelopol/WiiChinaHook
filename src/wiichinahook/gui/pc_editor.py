"""Editor of a PC mode (mouse and keyboard) for the gamepad tab."""
from __future__ import annotations

import flet as ft

from ..gamepad.pc import (MOUSE_ACTIONS, MOUSE_CLAIMS, MOUSE_SOURCES, PC_TEMPLATE, STICK_DIRECTIONS,
                          SYSTEM_ACTIONS)
from ..gamepad.mapping import AXIS_GESTURES
from .widgets import columns, hint, number, section

KINDS = ("none", "keys", "mouse", "system", "open", "toggle")
WIIMOTE = ("wm_a", "wm_b", "wm_1", "wm_2", "wm_minus", "wm_plus", "wm_home",
           "wm_up", "wm_down", "wm_left", "wm_right")
NUNCHUK = ("nc_c", "nc_z", *STICK_DIRECTIONS)
MOUSE_FIELDS = ("gyro_speed", "gyro_deadzone", "stick_speed", "stick_deadzone", "ir_range", "ir_smoothing")


class ActionRow:
    """One input: action type + its value (text for keys/open/toggle, a list for
    mouse/system). Disabled while the input drives the mouse."""

    def __init__(self, source, label, action, t):
        self.source, self.t = source, t
        kind, value = "none", ""
        if action:
            prefix, _, rest = action.partition(":")
            kind, value = (prefix, rest) if prefix in KINDS else ("keys", action)
        self.kind = ft.Dropdown(value=kind, width=130, dense=True, on_select=self.on_kind,
                                options=[ft.DropdownOption(k, t(f"pc_kind_{k}")) for k in KINDS])
        self.text = ft.TextField(value=value if kind in ("keys", "open", "toggle") else "", dense=True,
                                 expand=True, hint_text=t("pc_hint_keys"))
        self.choice = ft.Dropdown(dense=True, expand=True, value=value if kind in ("mouse", "system") else None)
        self.claimed = hint(t("pc_claimed"))
        self.row = ft.Row([ft.Text(label, width=120, weight=ft.FontWeight.W_500), self.kind, self.text,
                           self.choice, self.claimed], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.show(kind)
        self.set_claimed(False)

    def show(self, kind):
        self.text.visible = kind in ("keys", "open", "toggle")
        self.text.hint_text = self.t(f"pc_hint_{kind}") if self.text.visible else None
        self.choice.visible = kind in ("mouse", "system")
        if self.choice.visible:
            names = MOUSE_ACTIONS if kind == "mouse" else SYSTEM_ACTIONS
            self.choice.options = [ft.DropdownOption(n, self.t(f"pc_{kind}_{n}")) for n in names]
            if self.choice.value not in names:
                self.choice.value = names[0]

    def on_kind(self, e):
        self.show(e.control.value)
        e.control.page.update()

    def set_claimed(self, claimed):
        self.kind.disabled = claimed
        self.claimed.visible = claimed
        if claimed:
            self.text.visible = self.choice.visible = False
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


class PcEditor:
    def __init__(self, t, source_label):
        self.t, self.source_label = t, source_label

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
                                           for s in ("none", *MOUSE_SOURCES)])
        self.numbers = {key: number(t(f"pc_{key}"), mouse[key]) for key in MOUSE_FIELDS}
        self.shake = number(t("pc_shake_g"), template["shake_g"], suffix="g")
        self.rows = {s: ActionRow(s, self.label(s), template["buttons"].get(s), t)
                     for s in (*WIIMOTE, *NUNCHUK, *AXIS_GESTURES)}
        self.apply_claims()
        n = self.numbers
        left = [
            section(t("pc_mouse"), ft.Icons.MOUSE, [
                ft.Row([self.source]),
                ft.Row([n["gyro_speed"], n["gyro_deadzone"]]),
                ft.Row([n["stick_speed"], n["stick_deadzone"]]),
                ft.Row([n["ir_range"], n["ir_smoothing"]])], subtitle=t("pc_mouse_hint")),
            section(t("pc_help_title"), ft.Icons.HELP_OUTLINE, [
                ft.Markdown(t("pc_help"), selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)]),
        ]
        right = [
            section(t("pc_cat_wiimote"), ft.Icons.GAMEPAD, [self.rows[s].row for s in WIIMOTE],
                    subtitle=t("pc_modifier_hint")),
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
        mouse = dict(template["mouse"], source=source)
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
        return result


DEFAULT = PC_TEMPLATE
